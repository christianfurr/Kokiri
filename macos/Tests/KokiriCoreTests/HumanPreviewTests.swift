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
