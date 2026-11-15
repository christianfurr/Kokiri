import Foundation
import XCTest
@testable import KokiriCore

final class RecordingImportTests: XCTestCase {
    func testLongMalformedLineDoesNotHideLaterTimingSamples() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data("{\"started\":1000}".utf8).write(to: root.appendingPathComponent("session.json"))
        var timing = Data(repeating: 120, count: 600_000)
        timing.append(Data("\n1\t@frame_ms\t25\n".utf8))
        try timing.write(to: root.appendingPathComponent("timings.tsv"))
        let session = try RecordedSession.load(root)
        XCTAssertEqual(session.snapshot.frames.map(\.milliseconds), [25])
    }
}
