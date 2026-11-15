import Foundation
import XCTest
@testable import KokiriCore

final class MetadataDeltaTests: XCTestCase {
    private func file(_ contents: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("kokiri-delta-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("pso_user.tsv")
        try Data(contents.utf8).write(to: file)
        return file
    }
    private func append(_ text: String, to file: URL) throws {
        let handle = try FileHandle(forWritingTo: file); defer { try? handle.close() }
        try handle.seekToEnd(); try handle.write(contentsOf: Data(text.utf8))
    }
    func testImportedRowsAreNeverRelabelledAsNewSessionData() throws {
        let file = try file("OLD-CONTEXT\n")
        let checkpoint = try RuntimeMetadataDelta.checkpoint(file)
        try append("NEW-ROW\npartial", to: file)
        let delta = try RuntimeMetadataDelta.appended(file, since: checkpoint)
        XCTAssertEqual(String(decoding: delta.completeRows, as: UTF8.self), "NEW-ROW\n")
        XCTAssertEqual(delta.deferredBytes, 7)
    }
    func testReplacementOrPrefixMutationDefersSharing() throws {
        let file = try file("OLD\n")
        let checkpoint = try RuntimeMetadataDelta.checkpoint(file)
        try Data("OLD\nNEW\n".utf8).write(to: file, options: .atomic)
        XCTAssertThrowsError(try RuntimeMetadataDelta.appended(file, since: checkpoint))
        let second = try RuntimeMetadataDelta.checkpoint(file)
        let handle = try FileHandle(forWritingTo: file); try handle.write(contentsOf: Data("BAD".utf8)); try handle.close()
        XCTAssertThrowsError(try RuntimeMetadataDelta.appended(file, since: second))
    }
    func testCompletionOfAnOldPartialRowIsNotAttributedToCurrentContext() throws {
        let file = try file("old-part")
        let checkpoint = try RuntimeMetadataDelta.checkpoint(file)
        try append("-completed\nCURRENT\n", to: file)
        let delta = try RuntimeMetadataDelta.appended(file, since: checkpoint)
        XCTAssertEqual(String(decoding: delta.completeRows, as: UTF8.self), "CURRENT\n")
        XCTAssertEqual(delta.skippedPrefixContinuationBytes, 11)
    }
}
