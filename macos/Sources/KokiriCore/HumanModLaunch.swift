import CryptoKit
import Foundation

/// A launch token, never an arbitrary overlay path or inherited environment.
public struct HumanModLaunch: Sendable {
    public let launchID: String
    public let handoffSHA256: String
    public let manifestSHA256: String

    struct Handoff: Codable {
        let schema: Int
        let kind: String
        let session_id: String
        let launch_id: String
        let executable_sha256: String
        let manifest_sha256: String
    }

    static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    func verify(binding: HumanPreviewBinding) throws {
        try binding.verifyMarker()
        guard HumanPreviewBinding.hex(launchID, count: 32), HumanPreviewBinding.hex(handoffSHA256, count: 64),
              HumanPreviewBinding.hex(manifestSHA256, count: 64) else { throw KokiriError.message("The mod launch token is invalid.") }
        if let reason = ModLibrary.launchBlocker(app: binding.appURL, mode: .humanPreview) { throw KokiriError.message(reason) }
        let folder = binding.rootURL.appendingPathComponent("mods/" + launchID)
        try HumanPreviewBinding.canonicalDirectory(folder)
        let raw = try HumanPreviewBinding.regularData(folder.appendingPathComponent("handoff.json"), limit: 65536)
        let handoff = try JSONDecoder().decode(Handoff.self, from: raw)
        guard Self.digest(raw) == handoffSHA256, handoff.schema == 1, handoff.kind == "human-mod-overlay",
              handoff.session_id == binding.session_id, handoff.launch_id == launchID,
              handoff.executable_sha256 == binding.executable_sha256, handoff.manifest_sha256 == manifestSHA256,
              Self.digest(try HumanPreviewBinding.regularData(folder.appendingPathComponent("mods/manifest.tsv"), limit: 8 << 20)) == manifestSHA256 else {
            throw KokiriError.message("The mod snapshot changed or belongs to a different game session.")
        }
    }
}

extension HumanPreviewBinding {
    /// Empty profiles create no session files and use the original unmodded helper arguments.
    public func prepareModLaunch(library: ModLibrary) throws -> HumanModLaunch? {
        try verifyMarker()
        guard !(try library.load()).selected.enabled.isEmpty else { return nil }
        if let reason = ModLibrary.launchBlocker(app: appURL, mode: .humanPreview) { throw KokiriError.message(reason) }
        let parent = rootURL.appendingPathComponent("mods")
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        try Self.canonicalDirectory(parent)
        let id = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        let folder = parent.appendingPathComponent(id)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        var complete = false
        defer { if !complete { try? FileManager.default.removeItem(at: folder) } }
        let environment = try library.prepareLaunch(app: appURL, gameDataFolder: rootURL, sessionFolder: folder, mode: .humanPreview)
        guard environment["TOTK_ROMFS_MODS"] != "0" else { return nil }
        let manifest = try Self.regularData(folder.appendingPathComponent("mods/manifest.tsv"), limit: 8 << 20)
        let handoff = HumanModLaunch.Handoff(schema: 1, kind: "human-mod-overlay", session_id: session_id,
            launch_id: id, executable_sha256: executable_sha256, manifest_sha256: HumanModLaunch.digest(manifest))
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(handoff)
        try data.write(to: folder.appendingPathComponent("handoff.json"), options: .withoutOverwriting)
        let result = HumanModLaunch(launchID: id, handoffSHA256: HumanModLaunch.digest(data), manifestSHA256: handoff.manifest_sha256)
        try result.verify(binding: self)
        complete = true
        return result
    }
}
