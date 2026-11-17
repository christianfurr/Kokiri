import Foundation
import XCTest
@testable import KokiriCore

final class HumanPreviewTests: XCTestCase {
    private func fixture() throws -> (base: URL, root: URL, file: URL, object: [String: Any]) {
        let base = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Caches/KokiriPreviewTests/" + UUID().uuidString)
        let root = base.appendingPathComponent("human"), app = base.appendingPathComponent("Game.app")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.createDirectory(at: app, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: base) }
        let object: [String: Any] = ["schema": 1, "app": app.path, "root": root.path,
            "session_id": String(repeating: "a", count: 32), "executable_sha256": String(repeating: "b", count: 64), "python": "/usr/bin/true"]
        let marker: [String: Any] = ["schema": 1, "kind": "human-preview", "owner": "user", "session_id": object["session_id"]!, "executable_sha256": object["executable_sha256"]!]
        try JSONSerialization.data(withJSONObject: marker).write(to: root.appendingPathComponent("preview.json"))
        let file = base.appendingPathComponent("binding.json")
        try JSONSerialization.data(withJSONObject: object).write(to: file)
        return (base, root, file, object)
    }

    func testPublicBundleHasNoPreviewAndInvalidCLIIsNotFallback() throws {
        XCTAssertNil(try HumanPreviewBinding.selected(arguments: ["Kokiri"], resource: nil))
        let value = try fixture()
        XCTAssertThrowsError(try HumanPreviewBinding.selected(arguments: ["Kokiri", "--human-preview"], resource: value.file))
        XCTAssertEqual(try HumanPreviewBinding.selected(arguments: ["Kokiri"], resource: value.file)?.root, value.root.path)
    }

    func testProfileLocationSeparatesOrdinaryMissingAndValidPrivateBindings() throws {
        XCTAssertEqual(ProfileLocation.resolve(previewRequested: false, binding: nil)?.path, KokiriPaths.profile.path)
        XCTAssertNil(ProfileLocation.resolve(previewRequested: true, binding: nil))
        let value = try fixture(), binding = try HumanPreviewBinding.load(value.file)
        XCTAssertEqual(ProfileLocation.resolve(previewRequested: true, binding: binding)?.path,
                       value.root.appendingPathComponent("profile").path)
        XCTAssertFalse(FileManager.default.fileExists(atPath: value.root.appendingPathComponent("profile").path))
        XCTAssertEqual(ProfileLocation.resolve(previewRequested: false, binding: binding)?.path, KokiriPaths.profile.path)
    }

    @MainActor func testUnavailablePrivatePreviewCannotReadConsentOrEnableCatalog() async {
        let facade = CatalogFacade.unavailablePreview()
        XCTAssertFalse(facade.allowsContributions)
        XCTAssertFalse(facade.configured)
        XCTAssertFalse(facade.ready)
        XCTAssertNil(facade.consent)
        XCTAssertNil(facade.queued)
        XCTAssertNil(facade.origin)
        await facade.choose(true)
        await facade.reload()
        XCTAssertNil(facade.consent)
        XCTAssertFalse(facade.ready)
        XCTAssertFalse(facade.choicePending)
    }

    func testInvalidBindingCannotResolveToOrdinaryProfile() throws {
        let value = try fixture()
        for file in [value.base.appendingPathComponent("missing.json"), value.file] {
            if file == value.file { try Data("{}".utf8).write(to: file) }
            let binding = try? HumanPreviewBinding.load(file)
            XCTAssertNil(ProfileLocation.resolve(previewRequested: true, binding: binding))
        }
    }

    func testProfileLocationRevalidatesChangedAndRemovedPrivateMarkers() throws {
        let value = try fixture(), binding = try HumanPreviewBinding.load(value.file)
        let marker = value.root.appendingPathComponent("preview.json")
        let valid = try Data(contentsOf: marker)
        for key in ["session_id", "executable_sha256", "owner"] {
            var object = try XCTUnwrap(JSONSerialization.jsonObject(with: valid) as? [String: Any])
            object[key] = "mismatch"
            try JSONSerialization.data(withJSONObject: object).write(to: marker)
            XCTAssertNil(ProfileLocation.resolve(previewRequested: true, binding: binding), key)
            try valid.write(to: marker)
            XCTAssertNotNil(ProfileLocation.resolve(previewRequested: true, binding: binding))
        }
        try FileManager.default.removeItem(at: marker)
        XCTAssertNil(ProfileLocation.resolve(previewRequested: true, binding: binding))
    }

    func testCLIBindingAndCleanFixedHelperPlan() throws {
        let value = try fixture()
        let binding = try XCTUnwrap(HumanPreviewBinding.selected(arguments: ["Kokiri", "--human-preview", value.file.path], resource: nil))
        let helper = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("engine/scripts/dev/human_preview.py")
        let plan = try binding.launchPlan(helper: helper)
        XCTAssertEqual(plan.arguments, ["-I", "-B", helper.path, "--app", binding.app, "--private-root", binding.root])
        XCTAssertEqual(Set(plan.environment.keys), ["HOME", "USER", "LOGNAME", "PATH", "LANG"])
        XCTAssertEqual(binding.settingsURL.path, value.root.appendingPathComponent("settings/game").path)
        XCTAssertNil(plan.environment["TOTK_PROFILE_DIR"])
    }

    func testEmptyHumanModProfileCreatesNoSnapshotAndKeepsOldLaunchArguments() throws {
        let value = try fixture(), binding = try HumanPreviewBinding.load(value.file)
        let library = ModLibrary(root: value.base.appendingPathComponent("Library"))
        XCTAssertNil(try binding.prepareModLaunch(library: library))
        XCTAssertFalse(FileManager.default.fileExists(atPath: value.root.appendingPathComponent("mods").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: value.root.appendingPathComponent("profile").path))
    }

    func testHumanModSnapshotIsBoundToGameAndProfileWithoutWritingTheirInputs() throws {
        let value = try fixture(), binding = try HumanPreviewBinding.load(value.file), fm = FileManager.default
        let app = binding.appURL, resources = app.appendingPathComponent("Contents/Resources/totk")
        let romfs = resources.appendingPathComponent("extracted/oot/romfs")
        try fm.createDirectory(at: romfs, withIntermediateDirectories: true)
        let info: [String: Any] = ["KokiriHumanPreviewVersion": 1, "KokiriHumanPreviewModsVersion": 1]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: app.appendingPathComponent("Contents/Info.plist"))
        let original = Data("original".utf8), name = Data("Model/Link.bin\0".utf8)
        var index = Data("TOTKRFS1".utf8)
        func append(_ word: UInt64, bytes: Int) { for offset in 0..<bytes { index.append(UInt8(truncatingIfNeeded: word >> (offset * 8))) } }
        append(1, bytes: 8); append(48, bytes: 8); append(0, bytes: 8); append(UInt64(original.count), bytes: 8)
        append(0, bytes: 4); append(UInt64(name.count), bytes: 4); index.append(name)
        try index.write(to: romfs.appendingPathComponent("runtime-index.bin"))
        try original.write(to: romfs.appendingPathComponent("romfs.bin"))
        let config = resources.appendingPathComponent("build/game-data/oot/romfs-config.txt")
        try fm.createDirectory(at: config.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("ROMFS_IMAGE_SIZE \(original.count)\nROMFS_IMAGE_SHA256 \(HumanModLaunch.digest(original))\nROMFS_INDEX_SHA256 \(HumanModLaunch.digest(index))\n".utf8).write(to: config)
        let source = value.base.appendingPathComponent("Pack/romfs/Model/Link.bin")
        try fm.createDirectory(at: source.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("modified".utf8).write(to: source)
        let library = ModLibrary(root: value.base.appendingPathComponent("Library"))
        try library.importFolder(source.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent())
        try library.setEnabled(try library.load().packs[0].id, enabled: true)
        let stateBefore = try Data(contentsOf: library.root.appendingPathComponent("library.json"))
        let mods = try XCTUnwrap(binding.prepareModLaunch(library: library))
        try mods.verify(binding: binding)
        let helper = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("engine/scripts/dev/human_preview.py")
        let plan = try binding.launchPlan(helper: helper, mods: mods)
        XCTAssertEqual(Array(plan.arguments.suffix(4)), ["--mods-session", mods.launchID, "--mods-sha256", mods.handoffSHA256])
        XCTAssertEqual(Set(plan.environment.keys), ["HOME", "USER", "LOGNAME", "PATH", "LANG"])
        XCTAssertEqual(try Data(contentsOf: library.root.appendingPathComponent("library.json")), stateBefore)
        XCTAssertEqual(try Data(contentsOf: source), Data("modified".utf8))
        XCTAssertEqual(try Data(contentsOf: romfs.appendingPathComponent("romfs.bin")), original)
        let manifest = binding.rootURL.appendingPathComponent("mods/\(mods.launchID)/mods/manifest.tsv")
        try Data("# changed".utf8).write(to: manifest)
        XCTAssertThrowsError(try binding.launchPlan(helper: helper, mods: mods))
        XCTAssertFalse(fm.fileExists(atPath: value.root.appendingPathComponent("profile").path))
    }

    func testMarkerMismatchAndBooleanSchemaRefused() throws {
        let value = try fixture()
        var object = value.object
        object["session_id"] = String(repeating: "c", count: 32)
        try JSONSerialization.data(withJSONObject: object).write(to: value.file)
        XCTAssertThrowsError(try HumanPreviewBinding.load(value.file))
        object = value.object; object["schema"] = true
        try JSONSerialization.data(withJSONObject: object).write(to: value.file)
        XCTAssertThrowsError(try HumanPreviewBinding.load(value.file))
    }

    func testDevelopmentMarkerAndLinkedBindingRefused() throws {
        let value = try fixture()
        try FileManager.default.createSymbolicLink(atPath: value.root.appendingPathComponent("revoked").path, withDestinationPath: value.root.appendingPathComponent("missing").path)
        XCTAssertThrowsError(try HumanPreviewBinding.load(value.file))
        let link = value.base.appendingPathComponent("linked.json")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: value.file)
        XCTAssertThrowsError(try HumanPreviewBinding.load(link))
    }

    func testObservationAcknowledgementPinsActualIdentityAndOwner() throws {
        let value = try fixture(), binding = try HumanPreviewBinding.load(value.file)
        var session: [String: Any] = ["pid": 123, "process_start": 456,
            "executable": binding.appURL.appendingPathComponent("Contents/MacOS/KokiriGame").path,
            "executable_sha256": binding.executable_sha256, "owner": "user", "control": "observation-only",
            "kind": "human-preview", "session_id": binding.session_id]
        let file = value.root.appendingPathComponent("session.json")
        try JSONSerialization.data(withJSONObject: session).write(to: file)
        XCTAssertFalse(binding.acknowledges(pid: 123, start: 456))
        session["phase"] = "configured"; session["game_slot_acquired"] = false
        let isolation = value.root.appendingPathComponent("isolation.json")
        try JSONSerialization.data(withJSONObject: session).write(to: isolation)
        XCTAssertFalse(binding.acknowledges(pid: 123, start: 456))
        session["phase"] = "slot-acquired"; session["game_slot_acquired"] = true
        try JSONSerialization.data(withJSONObject: session).write(to: isolation)
        XCTAssertTrue(binding.acknowledges(pid: 123, start: 456))
        XCTAssertFalse(binding.acknowledges(pid: 123, start: 457))
        session["owner"] = "kokiri-dev"
        try JSONSerialization.data(withJSONObject: session).write(to: file)
        XCTAssertFalse(binding.acknowledges(pid: 123, start: 456))
    }
}
