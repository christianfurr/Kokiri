import Foundation
import XCTest
@testable import KokiriCore

final class InstallationConnectionTests: XCTestCase {
    private func temporary() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("kokiri-connection-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    private func assertSameInstallation(_ actual: GameInstallation?, _ expected: GameInstallation?,
                                        file: StaticString = #filePath, line: UInt = #line) {
        guard let expected else { XCTAssertNil(actual, file: file, line: line); return }
        guard let actual else { XCTFail("Expected a retained installation", file: file, line: line); return }
        // Bundle URLs may be relative to the app and gain absolute bases during
        // Codable roundtrips. Compare resolved filesystem identity and metadata.
        XCTAssertEqual(actual.app.resolvingSymlinksInPath().standardizedFileURL.path,
                       expected.app.resolvingSymlinksInPath().standardizedFileURL.path, file: file, line: line)
        XCTAssertEqual(actual.executable.resolvingSymlinksInPath().standardizedFileURL.path,
                       expected.executable.resolvingSymlinksInPath().standardizedFileURL.path, file: file, line: line)
        XCTAssertEqual(actual.bundleID, expected.bundleID, file: file, line: line)
        XCTAssertEqual(actual.productVersion, expected.productVersion, file: file, line: line)
        XCTAssertEqual(actual.gameUpdate, expected.gameUpdate, file: file, line: line)
        XCTAssertEqual(actual.sourceCommit, expected.sourceCommit, file: file, line: line)
        XCTAssertEqual(actual.liveStatusVersion, expected.liveStatusVersion, file: file, line: line)
    }

    private func app(at root: URL, name: String) throws -> URL {
        let app = root.appendingPathComponent(name + ".app")
        let contents = app.appendingPathComponent("Contents")
        let executable = contents.appendingPathComponent("MacOS/KokiriGame")
        let module = contents.appendingPathComponent("Resources/totk/rewritten/oot/main.patched.bin")
        try FileManager.default.createDirectory(at: executable.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: module.deletingLastPathComponent(), withIntermediateDirectories: true)
        let info: [String: Any] = [
            "CFBundleIdentifier": "com.christianfurr.kokiri.runtime",
            "CFBundleExecutable": "KokiriGame",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "0.1.0",
            "KokiriGameUpdate": "131072"
        ]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
            .write(to: contents.appendingPathComponent("Info.plist"))
        try Data("synthetic executable".utf8).write(to: executable)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executable.path)
        try Data("synthetic module".utf8).write(to: module)
        return app
    }

    func testAvailabilityRetainsMissingConnectionAndRecovers() throws {
        let root = try temporary(), candidate = try app(at: root, name: "Game")
        var preferences = LauncherPreferences()
        preferences.installation = try GameInstallation.inspect(candidate)
        let saved = root.appendingPathComponent("launcher.json")
        try preferences.save(to: saved)
        XCTAssertEqual(InstallationAvailability.determine(nil), .unconfigured)
        XCTAssertEqual(InstallationAvailability.determine(preferences.installation), .ready)
        let module = candidate.appendingPathComponent("Contents/Resources/totk/rewritten/oot/main.patched.bin")
        let bytes = try Data(contentsOf: module)
        try FileManager.default.removeItem(at: module)
        XCTAssertEqual(InstallationAvailability.determine(preferences.installation), .unavailable)
        assertSameInstallation(LauncherPreferences.load(from: saved).installation, preferences.installation)
        try bytes.write(to: module)
        XCTAssertEqual(InstallationAvailability.determine(preferences.installation), .ready)
        let executable = candidate.appendingPathComponent("Contents/MacOS/KokiriGame")
        try FileManager.default.removeItem(at: executable)
        XCTAssertEqual(InstallationAvailability.determine(preferences.installation), .unavailable)
        assertSameInstallation(LauncherPreferences.load(from: saved).installation, preferences.installation)
    }

    func testConnectionCommitsVerifiedCandidateWithoutTouchingPlayerData() throws {
        let root = try temporary()
        let original = try app(at: root, name: "Original"), candidate = try app(at: root, name: "Candidate")
        var preferences = LauncherPreferences()
        preferences.installation = try GameInstallation.inspect(original)
        preferences.repository = root.appendingPathComponent("source")
        preferences.observeSessions = true
        let save = root.appendingPathComponent("profile/slot.bin"), cache = root.appendingPathComponent("cache/mesh-records.tsv")
        for url in [save, cache] {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("keep \(url.lastPathComponent)".utf8).write(to: url)
        }
        let beforeSave = try Data(contentsOf: save), beforeCache = try Data(contentsOf: cache)
        let file = root.appendingPathComponent("launcher.json")
        try preferences.save(to: file)
        let result = try InstallationConnection.connect(candidate, preferences: preferences, savingTo: file)
        XCTAssertEqual(result.installation?.app.standardizedFileURL.path, candidate.standardizedFileURL.path)
        assertSameInstallation(LauncherPreferences.load(from: file).installation, result.installation)
        XCTAssertEqual(result.repository, preferences.repository)
        XCTAssertTrue(result.observeSessions)
        XCTAssertEqual(preferences.installation?.app.standardizedFileURL.path, original.standardizedFileURL.path)
        XCTAssertEqual(try Data(contentsOf: save), beforeSave)
        XCTAssertEqual(try Data(contentsOf: cache), beforeCache)
    }

    func testInvalidCandidateAndFailedSavePreserveExistingBinding() throws {
        let root = try temporary()
        let original = try app(at: root, name: "Original"), candidate = try app(at: root, name: "Candidate")
        var preferences = LauncherPreferences()
        preferences.installation = try GameInstallation.inspect(original)
        let file = root.appendingPathComponent("launcher.json")
        try preferences.save(to: file)
        let originalBytes = try Data(contentsOf: file)
        XCTAssertThrowsError(try InstallationConnection.connect(root.appendingPathComponent("Missing.app"), preferences: preferences, savingTo: file))
        XCTAssertEqual(try Data(contentsOf: file), originalBytes)

        // A file cannot serve as the preference directory. This deterministically
        // exercises persistence failure without relying on user permissions.
        XCTAssertThrowsError(try InstallationConnection.connect(candidate, preferences: preferences,
                                                               savingTo: file.appendingPathComponent("launcher.json")))
        XCTAssertEqual(try Data(contentsOf: file), originalBytes)
        assertSameInstallation(LauncherPreferences.load(from: file).installation, preferences.installation)
        XCTAssertEqual(preferences.installation?.app.standardizedFileURL.path, original.standardizedFileURL.path)
    }

    func testSetupDraftRetainsSelectionsAndStorageAcrossPersistence() throws {
        let root = try temporary()
        let original = SetupDraft(step: 3, game: root.appendingPathComponent("owned game.nup"),
                                  fonts: root.appendingPathComponent("shared fonts"),
                                  work: root.appendingPathComponent("preparation"),
                                  output: root.appendingPathComponent("Game.app"))
        let file = root.appendingPathComponent("setup-draft.json")
        try JSONEncoder().encode(original).write(to: file, options: .atomic)
        let restored = try JSONDecoder().decode(SetupDraft.self, from: Data(contentsOf: file))
        XCTAssertEqual(restored.step, original.step)
        XCTAssertEqual(restored.game?.standardizedFileURL.path, original.game?.standardizedFileURL.path)
        XCTAssertEqual(restored.fonts?.standardizedFileURL.path, original.fonts?.standardizedFileURL.path)
        XCTAssertEqual(restored.work.standardizedFileURL.path, original.work.standardizedFileURL.path)
        XCTAssertEqual(restored.output.standardizedFileURL.path, original.output.standardizedFileURL.path)
    }

    func testStorageContainmentResolvesSymlinksAndMissingChildren() throws {
        let root = try temporary(), source = root.appendingPathComponent("source")
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        let alias = root.appendingPathComponent("source-alias")
        try FileManager.default.createSymbolicLink(at: alias, withDestinationURL: source)
        XCTAssertFalse(SetupInput.isOutside(source, source))
        XCTAssertFalse(SetupInput.isOutside(source.appendingPathComponent("missing/work"), source))
        XCTAssertFalse(SetupInput.isOutside(alias.appendingPathComponent("missing/work"), source))
        XCTAssertTrue(SetupInput.isOutside(root.appendingPathComponent("source-other/work"), source))
        XCTAssertTrue(SetupInput.isOutside(root.appendingPathComponent("external/Game.app"), source))
    }

}
