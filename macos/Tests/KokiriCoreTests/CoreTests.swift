import Foundation
import XCTest
@testable import KokiriCore

final class CoreTests: XCTestCase {
    private func temporary() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("kokiri-test-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
    func testCompleteProfileCopyAndExistingDestinationProtection() throws {
        let root = try temporary(), source = root.appendingPathComponent("source"), target = root.appendingPathComponent("target")
        try FileManager.default.createDirectory(at: source.appendingPathComponent("save/account/empty"), withIntermediateDirectories: true)
        try Data([1,2,3,4]).write(to: source.appendingPathComponent("save/account/slot.bin"))
        try Data("account\n".utf8).write(to: source.appendingPathComponent("users.txt"))
        XCTAssertEqual(try ProfileImport.copy(from: source, to: target), 2)
        XCTAssertEqual(try Data(contentsOf: target.appendingPathComponent("save/account/slot.bin")), Data([1,2,3,4]))
        XCTAssertTrue(FileManager.default.fileExists(atPath: target.appendingPathComponent("save/account/empty").path))
        XCTAssertThrowsError(try ProfileImport.copy(from: source, to: target))
        XCTAssertEqual(try Data(contentsOf: source.appendingPathComponent("users.txt")), Data("account\n".utf8))
    }
    func testProfileSymlinkCannotEscapeImport() throws {
        let root = try temporary(), source = root.appendingPathComponent("source")
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        try Data("outside".utf8).write(to: root.appendingPathComponent("outside"))
        try FileManager.default.createSymbolicLink(at: source.appendingPathComponent("link"), withDestinationURL: root.appendingPathComponent("outside"))
        XCTAssertThrowsError(try ProfileImport.copy(from: source, to: root.appendingPathComponent("target")))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("target").path))
    }
    func testProfileDestinationAliasCannotNestImportInsideSource() throws {
        let fm = FileManager.default, root = try temporary()
        let source = root.appendingPathComponent("source"), alias = root.appendingPathComponent("alias")
        try fm.createDirectory(at: source, withIntermediateDirectories: true)
        let save = source.appendingPathComponent("slot.bin"), bytes = Data([1, 2, 3, 4])
        try bytes.write(to: save)
        try fm.createSymbolicLink(at: alias, withDestinationURL: source)
        let destination = alias.appendingPathComponent("missing-parent/profile")

        XCTAssertThrowsError(try ProfileImport.copy(from: source, to: destination))
        XCTAssertEqual(try Data(contentsOf: save), bytes)
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: source.path), ["slot.bin"])
    }
    func testGeneratedAndDuplicatePresentsDoNotInflateObservedRate() {
        var snapshot = PerformanceSnapshot()
        snapshot.consumePresented("presented\t1\t0\t0\t0\t100.0\t0\t0")
        snapshot.consumePresented("presented\t2\t0\t0\t1\t100.008\t0\t0")
        snapshot.consumePresented("presented\t3\t0\t0\t0\t100.0166666667\t0\t0")
        snapshot.consumePresented("presented\t3\t0\t0\t0\t100.0166666667\t0\t0")
        snapshot.consumePresented("presented\t4\t0\t0\t0\tnan\t0\t0")
        XCTAssertEqual(snapshot.gamePresents.count, 2)
        XCTAssertEqual(snapshot.duplicatePresents, 1)
        XCTAssertEqual(snapshot.observedFPS ?? 0, 60, accuracy: 0.001)
    }
    func testMalformedMetricsAndLocationAreRejected() {
        var snapshot = PerformanceSnapshot()
        snapshot.consumeTiming("1\t@frame_ms\tNaN")
        snapshot.consumeTiming("1\t@frame_ms\t-2")
        snapshot.consumeTiming("2\t@frame_ms\t20.5")
        snapshot.consumeTiming("2\t@frame_ms\t20.5")
        XCTAssertEqual(snapshot.frames.count, 1)
        snapshot.consumeStatus("{\"status\":\"not-ready\",\"map\":\"Forest\",\"x\":1,\"y\":2,\"z\":3}")
        XCTAssertNil(snapshot.area)
        snapshot.consumeStatus("{\"status\":\"position\",\"map\":\"KokiriForest\",\"x\":1,\"y\":2,\"z\":3}")
        XCTAssertEqual(snapshot.area, "KokiriForest")
    }
    func testTailHandlesPartialLinesAndRotation() throws {
        let file = try temporary().appendingPathComponent("timing")
        try Data("first\npart".utf8).write(to: file)
        let tail = LineTail(file)
        XCTAssertEqual(tail.read(), ["first"])
        let handle = try FileHandle(forWritingTo: file); try handle.seekToEnd(); try handle.write(contentsOf: Data("ial\n".utf8)); try handle.close()
        XCTAssertEqual(tail.read(), ["partial"])
        try Data("replacement\n".utf8).write(to: file, options: .atomic)
        XCTAssertEqual(tail.read(), ["replacement"])
    }
    func testUpdatesRequireHTTPSAndPublicKey() throws {
        let key = Data(repeating: 1, count: 32).base64EncodedString()
        XCTAssertThrowsError(try UpdateConfiguration(feed: nil, publicKey: nil))
        XCTAssertThrowsError(try UpdateConfiguration(feed: "http://updates.example/appcast.xml", publicKey: key))
        XCTAssertThrowsError(try UpdateConfiguration(feed: "https://user:password@updates.example/appcast.xml", publicKey: key))
        XCTAssertThrowsError(try UpdateConfiguration(feed: "https://updates.example/appcast.xml", publicKey: "bad"))
        XCTAssertEqual(try UpdateConfiguration(feed: "https://updates.example/appcast.xml", publicKey: key).publicKey.count, 32)
    }
    func testHUDRejectsUnsupportedValuesBeforeWriting() throws {
        let root = try temporary()
        var value = HUDPreferences(); value.position = "bottom-left"; value.scale = 125; value.detail = 2
        try value.save(to: root)
        XCTAssertEqual(HUDPreferences.read(from: root), value)
        value.scale = 900
        XCTAssertThrowsError(try value.save(to: root))
        XCTAssertEqual(HUDPreferences.read(from: root).scale, 125)
    }
    func testGPUIntervalsMustBelongToSameFrame() {
        var value = PerformanceSnapshot()
        value.consumeTiming("1\t@gpu_beg_ms\t100")
        value.consumeTiming("2\t@gpu_end_ms\t200")
        XCTAssertNil(value.gpuSpan)
        value.consumeTiming("2\t@gpu_beg_ms\t180")
        XCTAssertEqual(value.gpuSpan, 20)
        value.consumeTiming("1\t@gpu_beg_ms\t90")
        XCTAssertEqual(value.gpuSpan, 20)
    }
    func testRecordingRequiresDatedActualSamples() throws {
        let root = try temporary()
        try Data("{\"started\":1000,\"executable_sha256\":\"abc\"}".utf8).write(to: root.appendingPathComponent("session.json"))
        XCTAssertThrowsError(try RecordedSession.load(root))
        try Data("1\t@frame_ms\t25\n".utf8).write(to: root.appendingPathComponent("timings.tsv"))
        let session = try RecordedSession.load(root)
        XCTAssertEqual(session.date.timeIntervalSince1970, 1000)
        XCTAssertEqual(session.snapshot.frames.first?.milliseconds, 25)
        XCTAssertEqual(session.build, "abc")
    }
}
