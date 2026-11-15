import CryptoKit
import Foundation

public struct RuntimeMetadataCheckpoint: Codable, Sendable {
    public let bytes: Int
    public let sha256: String
    public let device: UInt64?
    public let inode: UInt64?
    public let endsWithNewline: Bool
}
public struct RuntimeMetadataAppend: Sendable {
    public let completeRows: Data
    public let deferredBytes: Int
    public let skippedPrefixContinuationBytes: Int
}

/// Qualifies only newly appended metadata; imported rows never inherit a new context.
public enum RuntimeMetadataDelta {
    public static let maximumBytes = 16 << 20
    private static func hash(_ bytes: Data) -> String {
        SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    }
    private static func read(_ file: URL) throws -> (Data, UInt64, UInt64) {
        let values = try FileManager.default.attributesOfItem(atPath: file.path)
        guard values[.type] as? FileAttributeType == .typeRegular,
              let size = values[.size] as? NSNumber, size.uint64Value <= maximumBytes,
              let device = values[.systemNumber] as? NSNumber, let inode = values[.systemFileNumber] as? NSNumber else {
            throw KokiriError.message("Runtime metadata was replaced, is not a regular file, or exceeds 16 MiB. Sharing was deferred.")
        }
        let data = try Data(contentsOf: file)
        guard data.count <= maximumBytes else { throw KokiriError.message("Runtime metadata grew beyond 16 MiB. Sharing was deferred.") }
        return (data, device.uint64Value, inode.uint64Value)
    }
    public static func checkpoint(_ file: URL) throws -> RuntimeMetadataCheckpoint {
        guard FileManager.default.fileExists(atPath: file.path) else {
            return RuntimeMetadataCheckpoint(bytes: 0, sha256: hash(Data()), device: nil, inode: nil, endsWithNewline: true)
        }
        let (data, device, inode) = try read(file)
        return RuntimeMetadataCheckpoint(bytes: data.count, sha256: hash(data), device: device, inode: inode,
                                         endsWithNewline: data.isEmpty || data.last == 10)
    }
    public static func appended(_ file: URL, since checkpoint: RuntimeMetadataCheckpoint) throws -> RuntimeMetadataAppend {
        guard (0...maximumBytes).contains(checkpoint.bytes), checkpoint.sha256.count == 64,
              (checkpoint.inode != nil || checkpoint.bytes == 0) else {
            throw KokiriError.message("Invalid runtime metadata checkpoint. Sharing was deferred.")
        }
        guard FileManager.default.fileExists(atPath: file.path) else {
            guard checkpoint.inode == nil else { throw KokiriError.message("Runtime metadata disappeared. Sharing was deferred.") }
            return RuntimeMetadataAppend(completeRows: Data(), deferredBytes: 0, skippedPrefixContinuationBytes: 0)
        }
        let (data, device, inode) = try read(file)
        guard (checkpoint.inode == nil || (checkpoint.inode == inode && checkpoint.device == device)),
              data.count >= checkpoint.bytes, hash(Data(data.prefix(checkpoint.bytes))) == checkpoint.sha256 else {
            throw KokiriError.message("Runtime metadata was replaced, truncated or rewritten. Sharing was deferred.")
        }
        var appended = Data(data.dropFirst(checkpoint.bytes)), skipped = 0
        if !checkpoint.endsWithNewline {
            guard let first = appended.firstIndex(of: 10) else {
                return RuntimeMetadataAppend(completeRows: Data(), deferredBytes: appended.count, skippedPrefixContinuationBytes: 0)
            }
            skipped = appended.distance(from: appended.startIndex, to: first) + 1
            appended.removeSubrange(...first)
        }
        guard let end = appended.lastIndex(of: 10) else {
            return RuntimeMetadataAppend(completeRows: Data(), deferredBytes: appended.count, skippedPrefixContinuationBytes: skipped)
        }
        let complete = Data(appended[...end])
        return RuntimeMetadataAppend(completeRows: complete, deferredBytes: appended.count - complete.count, skippedPrefixContinuationBytes: skipped)
    }
}
