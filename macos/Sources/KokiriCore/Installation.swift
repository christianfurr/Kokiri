import Foundation
import CryptoKit
import Darwin

public enum KokiriError: LocalizedError {
    case message(String)
    public var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

public struct GameInstallation: Codable, Equatable, Sendable {
    public let app: URL
    public let executable: URL
    public let bundleID: String
    public let productVersion: String
    public let gameUpdate: String
    public let sourceCommit: String?
    public let liveStatusVersion: Int?
    public var supportsLiveStatus: Bool { liveStatusVersion == 1 }

    public static func inspect(_ app: URL) throws -> Self {
        let app = app.standardizedFileURL
        guard app.pathExtension == "app", let bundle = Bundle(url: app),
              let identifier = bundle.bundleIdentifier,
              ["com.christianfurr.kokiri.runtime", "org.macnativegames.oot"].contains(identifier),
              let executable = bundle.executableURL,
              FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw KokiriError.message("Choose a built Kokiri Game app or a compatible Ocarina of Time app.")
        }
        let product = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Unknown"
        let update = bundle.object(forInfoDictionaryKey: "KokiriGameUpdate") as? String
            ?? (identifier == "org.macnativegames.oot" ? product : "")
        guard update == "131072" else {
            throw KokiriError.message("This app does not declare the supported game update, 131072.")
        }
        let code = app.appendingPathComponent("Contents/Resources/totk/rewritten/oot/main.patched.bin")
        guard FileManager.default.isReadableFile(atPath: code.path) else {
            throw KokiriError.message("The app’s rewritten game module is missing. Finish the game build first.")
        }
        return Self(app: app, executable: executable, bundleID: identifier, productVersion: product,
                    gameUpdate: update, sourceCommit: bundle.object(forInfoDictionaryKey: "KokiriSourceCommit") as? String
                        ?? bundle.object(forInfoDictionaryKey: "MNGSourceCommit") as? String,
                    liveStatusVersion: bundle.object(forInfoDictionaryKey: "KokiriLiveStatusVersion") as? Int)
    }
}

public enum KokiriPaths {
    public static var support: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Kokiri")
    }
    public static var game: URL { support.appendingPathComponent("OcarinaOfTime") }
    public static var profile: URL { game.appendingPathComponent("profile") }
    public static var sessions: URL { support.appendingPathComponent("Sessions") }
    public static var sharedSlot: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/MacNativeGames/TOTK/game-slot")
    }
    public static var legacyProfile: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/MacNativeGames/OcarinaOfTime/profile")
    }
}

public struct LauncherPreferences: Codable, Sendable {
    public var installation: GameInstallation?
    public var repository: URL?
    public var observeSessions = false
    public init() {}

    public static func load(from url: URL) -> Self {
        guard let data = try? Data(contentsOf: url), let result = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        return result
    }
    public func save(to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JSONEncoder().encode(self).write(to: url, options: .atomic)
    }
}

public enum ProfileImport {
    private static func canonicalLocation(_ url: URL) throws -> URL {
        // Resolve existing ancestors even when the destination does not exist yet.
        var ancestor = url
        var missing: [String] = []
        while !FileManager.default.fileExists(atPath: ancestor.path) {
            missing.append(ancestor.lastPathComponent)
            let parent = ancestor.deletingLastPathComponent()
            guard parent != ancestor else { throw KokiriError.message("The profile path cannot be resolved.") }
            ancestor = parent
        }
        let path = try ancestor.withUnsafeFileSystemRepresentation { path -> String in
            guard let path, let resolved = realpath(path, nil) else { throw KokiriError.message("The profile path cannot be resolved.") }
            defer { free(resolved) }
            return String(cString: resolved)
        }
        return missing.reversed().reduce(URL(fileURLWithPath: path)) { $0.appendingPathComponent($1) }
    }

    private static func fingerprint(_ root: URL) throws -> [String: String] {
        let fm = FileManager.default
        let keys: Set<URLResourceKey> = [.isSymbolicLinkKey, .isRegularFileKey, .isDirectoryKey]
        // Foundation may keep /var in a root URL but return /private/var entries.
        let canonicalPath = try root.withUnsafeFileSystemRepresentation { path -> String in
            guard let path, let resolved = realpath(path, nil) else { throw KokiriError.message("The source profile cannot be resolved.") }
            defer { free(resolved) }
            return String(cString: resolved)
        }
        let canonical = URL(fileURLWithPath: canonicalPath)
        guard try root.resourceValues(forKeys: keys).isSymbolicLink != true,
              let walk = fm.enumerator(at: canonical, includingPropertiesForKeys: Array(keys), options: []) else {
            throw KokiriError.message("The source profile cannot be read.")
        }
        var result: [String: String] = [:]
        for case let url as URL in walk {
            let values = try url.resourceValues(forKeys: keys)
            guard values.isSymbolicLink != true else { throw KokiriError.message("A profile containing symbolic links cannot be imported.") }
            guard url.path.hasPrefix(canonicalPath + "/") else { throw KokiriError.message("A profile entry is outside its folder.") }
            let name = String(url.path.dropFirst(canonicalPath.count + 1))
            if values.isDirectory == true { result[name + "/"] = "directory" }
            else if values.isRegularFile == true {
                let file = try FileHandle(forReadingFrom: url); defer { try? file.close() }
                var hash = SHA256()
                while let bytes = try file.read(upToCount: 1 << 20), !bytes.isEmpty { hash.update(data: bytes) }
                result[name] = hash.finalize().map { String(format: "%02x", $0) }.joined()
            } else { throw KokiriError.message("The profile contains an unsupported file type.") }
        }
        guard !result.isEmpty else { throw KokiriError.message("This folder contains no profile files.") }
        return result
    }

    /// Copies a complete profile once. No merge, replacement, or writes to the source.
    public static func copy(from source: URL, to destination: URL) throws -> Int {
        let fm = FileManager.default, source = source.standardizedFileURL, destination = destination.standardizedFileURL
        guard !fm.fileExists(atPath: destination.path) else { throw KokiriError.message("Kokiri already has a profile. It was left untouched.") }
        let sourcePath = try canonicalLocation(source).path, destinationPath = try canonicalLocation(destination).path
        guard sourcePath != destinationPath, !destinationPath.hasPrefix(sourcePath + "/"),
              !sourcePath.hasPrefix(destinationPath + "/") else { throw KokiriError.message("Choose a separate source profile.") }
        let before = try fingerprint(source)
        try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        let staging = destination.deletingLastPathComponent().appendingPathComponent(".profile-import-" + UUID().uuidString)
        defer { try? fm.removeItem(at: staging) }
        try fm.copyItem(at: source, to: staging)
        guard before == (try fingerprint(source)), before == (try fingerprint(staging)) else {
            throw KokiriError.message("The profile changed while it was copied. Close the game and try again.")
        }
        guard !fm.fileExists(atPath: destination.path) else { throw KokiriError.message("A Kokiri profile appeared during import. It was left untouched.") }
        try fm.moveItem(at: staging, to: destination)
        return before.keys.filter { !$0.hasSuffix("/") }.count
    }
}

public struct HUDPreferences: Equatable, Sendable {
    public var position = "top-right"
    public var scale = 100
    public var detail = 1
    public static let positions = ["top-right", "top-left", "bottom-right", "bottom-left"]
    public static let scales = [75, 100, 125, 150]
    public init() {}
    public static func read(from folder: URL) -> Self {
        func word(_ name: String) -> String? {
            guard let data = try? Data(contentsOf: folder.appendingPathComponent(name)), data.count < 128 else { return nil }
            return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        var value = Self()
        if let position = word("graphics-hud-position.txt"), positions.contains(position) { value.position = position }
        if let scale = word("graphics-hud-scale.txt").flatMap(Int.init), scales.contains(scale) { value.scale = scale }
        if let detail = word("graphics-overlay.txt").flatMap(Int.init), (0...2).contains(detail) { value.detail = detail }
        return value
    }
    public func save(to folder: URL) throws {
        guard Self.positions.contains(position), Self.scales.contains(scale), (0...2).contains(detail) else {
            throw KokiriError.message("Unsupported HUD setting. No files were changed.")
        }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        for (name, value) in [("graphics-hud-position.txt", position), ("graphics-hud-scale.txt", String(scale)), ("graphics-overlay.txt", String(detail))] {
            try Data((value + "\n").utf8).write(to: folder.appendingPathComponent(name), options: .atomic)
        }
    }
}

public struct UpdateConfiguration: Equatable, Sendable {
    public let feed: URL
    public let publicKey: Data
    public init(feed: String?, publicKey: String?) throws {
        guard let feed, let url = URL(string: feed), url.scheme == "https", url.host != nil,
              url.user == nil, url.password == nil, url.fragment == nil,
              let publicKey, let key = Data(base64Encoded: publicKey), key.count == 32 else {
            throw KokiriError.message("Signed updates are not configured in this build.")
        }
        self.feed = url; self.publicKey = key
    }
}
