import Foundation
import CryptoKit
import XCTest
@testable import KokiriCore

final class ModLibraryTests: XCTestCase {
    private let fm = FileManager.default

    private func fixture() throws -> URL {
        let root = fm.temporaryDirectory.appendingPathComponent("KokiriModsTests-" + UUID().uuidString)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    private func pack(_ root: URL, _ name: String, path: String = "Model/Link.bin", bytes: String = "modded") throws -> URL {
        let folder = root.appendingPathComponent(name), file = folder.appendingPathComponent("romfs").appendingPathComponent(path)
        try fm.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(bytes.utf8).write(to: file)
        return folder
    }

    private func sha(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

    private func game(_ root: URL, marker: Any? = 1, preview: Any? = nil) throws -> URL {
        let app = root.appendingPathComponent("Game.app"), resources = app.appendingPathComponent("Contents/Resources/totk")
        let romfs = resources.appendingPathComponent("extracted/oot/romfs")
        try fm.createDirectory(at: romfs, withIntermediateDirectories: true)
        var info: [String: Any] = ["CFBundleIdentifier": "tests.kokiri.mods." + UUID().uuidString, "CFBundlePackageType": "APPL"]
        if let marker { info["KokiriRomFSModsVersion"] = marker }
        if let preview { info["KokiriHumanPreviewVersion"] = preview }
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: app.appendingPathComponent("Contents/Info.plist"))
        var index = Data("TOTKRFS1".utf8)
        func append(_ value: UInt64, count: Int) { for byte in 0..<count { index.append(UInt8(truncatingIfNeeded: value >> (byte * 8))) } }
        let original = Data("original".utf8), name = Data("Model/Link.bin\0".utf8)
        append(1, count: 8); append(48, count: 8)
        append(0, count: 8); append(UInt64(original.count), count: 8); append(0, count: 4); append(UInt64(name.count), count: 4)
        index.append(name)
        try index.write(to: romfs.appendingPathComponent("runtime-index.bin"))
        try original.write(to: romfs.appendingPathComponent("romfs.bin"))
        let config = resources.appendingPathComponent("build/game-data/oot/romfs-config.txt")
        try fm.createDirectory(at: config.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("ROMFS_IMAGE_SIZE \(original.count)\nROMFS_IMAGE_SHA256 \(sha(original))\nROMFS_INDEX_SHA256 \(sha(index))\n".utf8).write(to: config)
        return app
    }

    func testProfilesPersistIndependentSelectionAndOrder() throws {
        let root = try fixture(), library = ModLibrary(root: root.appendingPathComponent("Library"))
        try library.importFolder(pack(root, "One")); try library.importFolder(pack(root, "Two", bytes: "second"))
        let first = try library.load().packs[0].id, second = try library.load().packs[1].id
        try library.setEnabled(first, enabled: true)
        try library.createProfile("Alternate", duplicate: true)
        try library.setEnabled(second, enabled: true); try library.move(second, by: -1)
        XCTAssertEqual(try library.load().selected.order, [second, first])
        try library.selectProfile("default")
        XCTAssertEqual(try library.load().selected.enabled, [first])
        XCTAssertEqual(try library.load().selected.order, [first, second])
        XCTAssertThrowsError(try library.createProfile("default", duplicate: false))
        try library.renameProfile("Original")
        try library.deleteSelectedProfile()
        XCTAssertEqual(try library.load().selected.name, "Alternate")
        XCTAssertThrowsError(try library.deleteSelectedProfile())
    }

    func testPreparedManifestUsesRealIndexNULAndLastModWins() throws {
        let root = try fixture(), library = ModLibrary(root: root.appendingPathComponent("Library")), app = try game(root)
        try library.importFolder(pack(root, "One")); try library.importFolder(pack(root, "Two", bytes: "last"))
        for mod in try library.load().packs { try library.setEnabled(mod.id, enabled: true) }
        XCTAssertEqual(try library.conflicts()["Model/Link.bin"]?.count, 2)
        let session = root.appendingPathComponent("Session")
        try fm.createDirectory(at: session, withIntermediateDirectories: true)
        let env = try library.prepareLaunch(app: app, gameDataFolder: root, sessionFolder: session)
        let overlay = URL(fileURLWithPath: try XCTUnwrap(env["TOTK_ROMFS_MODS"]))
        XCTAssertEqual(try String(contentsOf: overlay.appendingPathComponent("Model/Link.bin"), encoding: .utf8), "last")
        let rows = try String(contentsOf: overlay.appendingPathComponent("manifest.tsv"), encoding: .utf8)
        XCTAssertTrue(rows.contains("Model/Link.bin\t4\t\(sha(Data("last".utf8)))\t\(sha(Data("original".utf8)))\n"))
        XCTAssertThrowsError(try library.prepareLaunch(app: app, gameDataFolder: root, sessionFolder: session))
    }

    func testMacNativeCopyUsesLiveSelectedSnapshotAndPreservesForeignFiles() throws {
        let root = try fixture(), source = root.appendingPathComponent("MacNative")
        _ = try pack(source, "first")
        let record: [String: Any] = ["format": 1, "order": ["first"], "enabled": ["first"], "names": ["first": "First"],
                                  "selected_profile": "Live", "profiles": ["Live": ["order": ["first"], "enabled": []]], "code": [:]]
        let sourceRecord = source.appendingPathComponent("library.json")
        let before = try JSONSerialization.data(withJSONObject: record, options: .sortedKeys)
        try before.write(to: sourceRecord)
        let library = ModLibrary(root: root.appendingPathComponent("Kokiri"))
        XCTAssertEqual(try library.importMacNativeLibrary(source), 1)
        XCTAssertEqual(try Data(contentsOf: sourceRecord), before)
        let state = try library.load()
        XCTAssertEqual(state.selectedProfile, "default"); XCTAssertTrue(state.selected.enabled.isEmpty)
        let imported = try XCTUnwrap(state.profiles.first { $0.name == "MacNative · Live" })
        XCTAssertEqual(imported.enabled, [state.packs[0].id])
        try fm.removeItem(at: source)
        try library.selectProfile(imported.id)
        XCTAssertEqual(try library.conflicts(), [:])
    }

    func testCapabilityRejectsMissingUnknownBooleanRealStringAndPreview() throws {
        let markers: [Any?] = [nil, 2, true, 1.0, "1"]
        for marker in markers {
            let root = try fixture(), app = try game(root, marker: marker)
            XCTAssertFalse(ModLibrary.supportsLaunch(app: app), "Unexpected marker: \(String(describing: marker))")
        }
        let root = try fixture(), app = try game(root, preview: 1)
        XCTAssertFalse(ModLibrary.supportsLaunch(app: app))
        let library = ModLibrary(root: root.appendingPathComponent("Library"))
        XCTAssertEqual(try library.prepareLaunch(app: app, gameDataFolder: root, sessionFolder: root), ["TOTK_ROMFS_MODS": "0"])
        try library.importFolder(pack(root, "One")); try library.setEnabled(try library.load().packs[0].id, enabled: true)
        XCTAssertThrowsError(try library.prepareLaunch(app: app, gameDataFolder: root, sessionFolder: root))
    }

    func testLinkedUnsafeCodeAndDependentPacksRefused() throws {
        let root = try fixture(), library = ModLibrary(root: root.appendingPathComponent("Library"))
        let linked = try pack(root, "Linked")
        try fm.createSymbolicLink(at: linked.appendingPathComponent("romfs/escape"), withDestinationURL: root.appendingPathComponent("outside"))
        XCTAssertThrowsError(try library.importFolder(linked))
        let unsafe = try pack(root, "Unsafe", path: "Model/bad\\name")
        XCTAssertThrowsError(try library.importFolder(unsafe))
        let code = try pack(root, "Code")
        try fm.createDirectory(at: code.appendingPathComponent("exefs"), withIntermediateDirectories: true)
        XCTAssertThrowsError(try library.importFolder(code))
        let dependent = try pack(root, "Dependent")
        try Data("{\"requires\":[\"Missing base pack\"]}".utf8).write(to: dependent.appendingPathComponent("macnative-mod.json"))
        XCTAssertThrowsError(try library.importFolder(dependent))
        XCTAssertThrowsError(try library.importFolder(dependent.appendingPathComponent("romfs")))
        XCTAssertTrue(try library.load().packs.isEmpty)
    }

    func testWrongIndexAndWrongImageMarkerRefusedBeforeOverlayPublication() throws {
        let root = try fixture(), app = try game(root), library = ModLibrary(root: root.appendingPathComponent("Library"))
        try library.importFolder(pack(root, "One")); try library.setEnabled(try library.load().packs[0].id, enabled: true)
        let romfs = app.appendingPathComponent("Contents/Resources/totk/extracted/oot/romfs")
        try Data(String(repeating: "0", count: 64).utf8).write(to: romfs.appendingPathComponent("romfs.sha256"))
        XCTAssertThrowsError(try library.prepareLaunch(app: app, gameDataFolder: root, sessionFolder: root))
        try fm.removeItem(at: romfs.appendingPathComponent("romfs.sha256"))
        var data = try Data(contentsOf: romfs.appendingPathComponent("runtime-index.bin")); data[48] = 65
        try data.write(to: romfs.appendingPathComponent("runtime-index.bin"))
        XCTAssertThrowsError(try library.prepareLaunch(app: app, gameDataFolder: root, sessionFolder: root))
        XCTAssertFalse(fm.fileExists(atPath: root.appendingPathComponent("mods").path))
    }
}
