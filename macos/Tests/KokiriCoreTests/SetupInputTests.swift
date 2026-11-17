import Foundation
import XCTest
@testable import KokiriCore

final class SetupInputTests: XCTestCase {
    func testDumpMustIncludeUpdateAndExecutableFiles() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertNotNil(SetupInput.gameProblem(root))
        try FileManager.default.createDirectory(at: root.appendingPathComponent("updates/131072/romfs"), withIntermediateDirectories: true)
        XCTAssertNotNil(SetupInput.gameProblem(root))
        let code = root.appendingPathComponent("base/exefs")
        try FileManager.default.createDirectory(at: code, withIntermediateDirectories: true)
        for name in ["main", "subsdk0", "sdk"] { try Data().write(to: code.appendingPathComponent(name)) }
        XCTAssertNil(SetupInput.gameProblem(root))
        let rom = root.appendingPathComponent("game.z64")
        try Data().write(to: rom)
        XCTAssertNotNil(SetupInput.gameProblem(rom))
        let package = root.appendingPathComponent("game.nup")
        try Data().write(to: package)
        XCTAssertNil(SetupInput.gameProblem(package)) // Structural check only; builder verifies content.
    }

    func testFontsRequireCompleteSetAndManifest() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertNotNil(SetupInput.fontsProblem(root))
        for name in ["0-standard", "1-chinese-simplified", "2-chinese-simplified-extension", "3-chinese-traditional", "4-korean", "5-nintendo-extension"] {
            try Data().write(to: root.appendingPathComponent(name + ".bfttf"))
        }
        XCTAssertNotNil(SetupInput.fontsProblem(root))
        try Data("{}".utf8).write(to: root.appendingPathComponent("manifest.json"))
        XCTAssertNil(SetupInput.fontsProblem(root))
        try FileManager.default.removeItem(at: root.appendingPathComponent("4-korean.bfttf"))
        XCTAssertNotNil(SetupInput.fontsProblem(root))
    }
}
