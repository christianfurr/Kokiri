import Foundation
import KokiriSupport

public struct FramePoint: Identifiable, Equatable, Sendable {
    public var id: Int { frame }
    public let frame: Int
    public let milliseconds: Double
}
public struct ProcessSample: Equatable, Sendable {
    public let footprint: UInt64
    public let start: UInt64
    public static func read(pid: Int32) -> Self? {
        var sample = KokiriProcessSample()
        guard kokiri_process_sample(pid, &sample) != 0 else { return nil }
        return Self(footprint: sample.footprint, start: sample.start)
    }
    public static func executable(pid: Int32) -> String? {
        var bytes = [CChar](repeating: 0, count: 4096)
        guard kokiri_process_path(pid, &bytes, UInt32(bytes.count)) > 0 else { return nil }
        return String(cString: bytes)
    }
}

public struct PerformanceSnapshot: Sendable {
    public var frames: [FramePoint] = []
    public var metrics: [String: Double] = [:]
    public var gamePresents: [Double] = []
    public var duplicatePresents = 0
    public var footprint: UInt64?
    public var area: String?
    public var position: [Double]?
    public var lastUpdate: Date?
    private var metricFrames: [String: Int] = [:]
    public init() {}
    public var observedFPS: Double? {
        guard let first = gamePresents.first, let last = gamePresents.last, gamePresents.count >= 2, last > first else { return nil }
        return Double(gamePresents.count - 1) / (last - first)
    }
    public var gpuSpan: Double? {
        guard metricFrames["@gpu_beg_ms"] == metricFrames["@gpu_end_ms"],
              let first = metrics["@gpu_beg_ms"], let last = metrics["@gpu_end_ms"], last >= first else { return nil }
        return last - first
    }
    public mutating func consumeTiming(_ line: String) {
        let fields = line.split(separator: "\t", omittingEmptySubsequences: false)
        guard fields.count >= 3, let frame = Int(fields[0]), let value = Double(fields[2]), value.isFinite, value >= 0 else { return }
        let name = String(fields[1])
        if frame >= metricFrames[name, default: -1] { metrics[name] = value; metricFrames[name] = frame }
        if name == "@frame_ms", value > 0, value < 120_000 {
            if !frames.contains(where: { $0.frame == frame }) {
                frames.append(FramePoint(frame: frame, milliseconds: value)); frames.sort { $0.frame < $1.frame }
                if frames.count > 120 { frames.removeFirst(frames.count - 120) }
            }
        }
    }
    public mutating func consumePresented(_ line: String) {
        let fields = line.split(separator: "\t", omittingEmptySubsequences: false)
        guard fields.count == 8, fields[0] == "presented", fields[4] == "0",
              let stamp = Double(fields[5]), stamp.isFinite, stamp > 0 else { return }
        if gamePresents.contains(stamp) { duplicatePresents += 1; return }
        gamePresents.append(stamp); gamePresents.sort()
        if let newest = gamePresents.last { gamePresents.removeAll { $0 < newest - 30 } }
        if gamePresents.count > 10_000 { gamePresents.removeFirst(gamePresents.count - 10_000) }
    }
    public mutating func consumeStatus(_ line: String) {
        guard let bytes = line.data(using: .utf8), let object = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              let status = object["status"] as? String, ["position", "arrived", "moved"].contains(status),
              let map = object["map"] as? String, !map.isEmpty,
              let x = object["x"] as? Double, let y = object["y"] as? Double, let z = object["z"] as? Double,
              [x,y,z].allSatisfy({ $0.isFinite && abs($0) < 10_000 }) else { return }
        area = map; position = [x,y,z]
    }
    public mutating func consumeProcess(_ line: String) {
        guard let bytes = line.data(using: .utf8), let object = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              let number = object["phys_footprint"] as? NSNumber else { return }
        footprint = number.uint64Value
    }
}

/// Bounded incremental tail; a renamed, truncated or replaced file starts a fresh read.
public final class LineTail {
    private let url: URL
    private var inode: UInt64 = 0
    private var offset: UInt64 = 0
    private var partial = Data()
    private(set) var madeProgress = false
    public init(_ url: URL, startAtEnd: Bool = false) {
        self.url = url
        if startAtEnd, let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
           attributes[.type] as? FileAttributeType == .typeRegular {
            inode = (attributes[.systemFileNumber] as? NSNumber)?.uint64Value ?? 0
            offset = (attributes[.size] as? NSNumber)?.uint64Value ?? 0
        }
    }
    public func read() -> [String] {
        madeProgress = false
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = attributes[.size] as? NSNumber, let file = attributes[.systemFileNumber] as? NSNumber,
              attributes[.type] as? FileAttributeType == .typeRegular,
              let handle = try? FileHandle(forReadingFrom: url) else { return [] }
        defer { try? handle.close() }
        if file.uint64Value != inode || size.uint64Value < offset { inode = file.uint64Value; offset = 0; partial.removeAll() }
        do {
            try handle.seek(toOffset: offset)
            guard let bytes = try handle.read(upToCount: 256 << 10), !bytes.isEmpty else { return [] }
            madeProgress = true
            offset += UInt64(bytes.count); partial.append(bytes)
            var lines: [String] = []
            while let newline = partial.firstIndex(of: 10) {
                lines.append(String(decoding: partial[..<newline], as: UTF8.self)); partial.removeSubrange(...newline)
            }
            if partial.count > 256 << 10 { partial.removeAll() }
            return lines
        } catch { return [] }
    }
}

public struct RecordedSession: Sendable {
    /// Restore recent observations without replaying a long session on the UI thread.
    public static func recentSnapshot(_ folder: URL) -> PerformanceSnapshot {
        var snapshot = PerformanceSnapshot()
        for name in ["timings.tsv", "timings.tsv.presented.tsv", "status.jsonl", "process.jsonl"] {
            let url = folder.appendingPathComponent(name)
            guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]),
                  values.isRegularFile == true, values.isSymbolicLink != true,
                  let handle = try? FileHandle(forReadingFrom: url) else { continue }
            defer { try? handle.close() }
            let size = UInt64(max(0, values.fileSize ?? 0)), start = size > 256 << 10 ? size - UInt64(256 << 10) : 0
            do {
                try handle.seek(toOffset: start)
                guard let data = try handle.read(upToCount: 256 << 10) else { continue }
                let rows = String(decoding: data, as: UTF8.self).split(separator: "\n", omittingEmptySubsequences: false)
                for row in rows.dropFirst(start > 0 ? 1 : 0).dropLast() {
                    switch name {
                    case "timings.tsv": snapshot.consumeTiming(String(row))
                    case "timings.tsv.presented.tsv": snapshot.consumePresented(String(row))
                    case "status.jsonl": snapshot.consumeStatus(String(row))
                    default: snapshot.consumeProcess(String(row))
                    }
                }
            } catch { continue }
        }
        return snapshot
    }
    public let folder: URL
    public let date: Date
    public let build: String?
    public let snapshot: PerformanceSnapshot
    public static func load(_ folder: URL) throws -> Self {
        let metadataURL = folder.appendingPathComponent("session.json")
        guard let size = try metadataURL.resourceValues(forKeys: [.fileSizeKey]).fileSize, size < 1 << 20 else {
            throw KokiriError.message("This recording’s session metadata is too large.")
        }
        let data = try Data(contentsOf: metadataURL)
        guard data.count < 1 << 20, let session = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let started = session["started"] as? Double, started.isFinite, started > 0 else {
            throw KokiriError.message("Choose a recorded session folder containing session.json and timing files.")
        }
        var snapshot = PerformanceSnapshot()
        let files: [(String, (inout PerformanceSnapshot, String) -> Void)] = [
            ("timings.tsv", { $0.consumeTiming($1) }), ("timings.tsv.presented.tsv", { $0.consumePresented($1) }),
            ("status.jsonl", { $0.consumeStatus($1) }), ("process.jsonl", { $0.consumeProcess($1) })
        ]
        for (name, consume) in files {
            let url = folder.appendingPathComponent(name)
            guard FileManager.default.fileExists(atPath: url.path) else { continue }
            let tail = LineTail(url)
            for _ in 0..<2048 {
                let lines = tail.read()
                if lines.isEmpty && !tail.madeProgress { break }
                for line in lines { consume(&snapshot, line) }
            }
        }
        guard !snapshot.frames.isEmpty || !snapshot.gamePresents.isEmpty else { throw KokiriError.message("No readable timing samples were found in this recording.") }
        snapshot.lastUpdate = Date(timeIntervalSince1970: started)
        return Self(folder: folder, date: Date(timeIntervalSince1970: started), build: session["executable_sha256"] as? String ?? session["source_commit"] as? String, snapshot: snapshot)
    }
}
