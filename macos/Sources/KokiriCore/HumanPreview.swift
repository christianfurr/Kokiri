import CryptoKit
import Darwin
import Foundation

/// A private shell binding. Ordinary bundles contain no binding and use the normal launcher.
public struct HumanPreviewBinding: Decodable, Sendable {
    public let schema: Int
    public let app: String
    public let root: String
    public let session_id: String
    public let executable_sha256: String
    public let python: String
    public static let helperSHA256 = "a1a6e4f29e0e13cc38c2ee9644b6a96a7328eeac6b89a528de03e626467d208b"
    public var appURL: URL { URL(fileURLWithPath: app) }
    public var rootURL: URL { URL(fileURLWithPath: root) }
    public var settingsURL: URL { rootURL.appendingPathComponent("settings/game") }

    public static func selected(arguments: [String], resource: URL?) throws -> Self? {
        let indexes = arguments.indices.filter { arguments[$0] == "--human-preview" }
        guard indexes.count <= 1 else { throw KokiriError.message("Choose one human playtest binding.") }
        if let index = indexes.first {
            guard arguments.indices.contains(index + 1), arguments[index + 1].hasPrefix("/") else {
                throw KokiriError.message("The human playtest binding needs an absolute file path.")
            }
            return try load(URL(fileURLWithPath: arguments[index + 1]))
        }
        return try resource.map(load)
    }

    public static func load(_ file: URL) throws -> Self {
        let data = try regularData(file, limit: 65536)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["schema", "app", "root", "session_id", "executable_sha256", "python"] else {
            throw KokiriError.message("The human playtest binding is invalid.")
        }
        let binding = try JSONDecoder().decode(Self.self, from: data)
        guard binding.schema == 1, hex(binding.session_id, count: 32), hex(binding.executable_sha256, count: 64),
              [binding.app, binding.root, binding.python].allSatisfy({ $0.hasPrefix("/") && !$0.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) }) else {
            throw KokiriError.message("The human playtest binding is invalid.")
        }
        try binding.verifyMarker()
        return binding
    }

    static func hex(_ value: String, count: Int) -> Bool {
        value.utf8.count == count && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }

    static func canonicalDirectory(_ url: URL) throws {
        guard url.path == url.resolvingSymlinksInPath().standardizedFileURL.path else {
            throw KokiriError.message("The human playtest folders must not use symbolic links.")
        }
        var current = url.path
        while true {
            var info = stat()
            guard lstat(current, &info) == 0, info.st_mode & S_IFMT == S_IFDIR else {
                throw KokiriError.message("The human playtest folder is unavailable or linked: \(current)")
            }
            if current == "/" { break }
            let parent = (current as NSString).deletingLastPathComponent
            if parent == current || parent.isEmpty { break }
            current = parent
        }
    }

    private static func related(_ first: URL, _ second: URL) throws -> Bool {
        let a = first.resolvingSymlinksInPath().standardizedFileURL
        let b = second.resolvingSymlinksInPath().standardizedFileURL
        if a == b || a.path.hasPrefix(b.path + "/") || b.path.hasPrefix(a.path + "/") { return true }
        for (parent, child) in [(a, b), (b, a)] {
            var identity = stat()
            if stat(parent.path, &identity) != 0 {
                if errno == ENOENT { continue }
                throw KokiriError.message("The human playtest path identity could not be checked.")
            }
            var current = child.path
            while true {
                var item = stat()
                if stat(current, &item) == 0 {
                    if identity.st_dev == item.st_dev && identity.st_ino == item.st_ino { return true }
                } else if errno != ENOENT {
                    throw KokiriError.message("The human playtest path identity could not be checked.")
                }
                if current == "/" { break }
                let next = (current as NSString).deletingLastPathComponent
                if next == current || next.isEmpty { break }
                current = next
            }
        }
        return false
    }

    static func regularData(_ url: URL, limit: Int) throws -> Data {
        let fd = open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard fd >= 0 else { throw KokiriError.message("The human playtest metadata could not be opened.") }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var before = stat(), after = stat()
        guard fstat(fd, &before) == 0, before.st_mode & S_IFMT == S_IFREG,
              before.st_uid == getuid(), before.st_nlink == 1, before.st_size > 0, before.st_size <= limit,
              let data = try handle.read(upToCount: limit + 1), data.count == before.st_size,
              fstat(fd, &after) == 0, before.st_dev == after.st_dev, before.st_ino == after.st_ino,
              before.st_size == after.st_size, before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec,
              before.st_ctimespec.tv_sec == after.st_ctimespec.tv_sec,
              before.st_ctimespec.tv_nsec == after.st_ctimespec.tv_nsec else {
            throw KokiriError.message("The human playtest metadata is invalid or changed while reading.")
        }
        return data
    }

    public func verifyMarker() throws {
        try Self.canonicalDirectory(rootURL)
        try Self.canonicalDirectory(appURL)
        var info = stat()
        guard root.utf8.count <= 768, lstat(root, &info) == 0, info.st_uid == getuid(), info.st_mode & 0o777 == 0o700 else {
            throw KokiriError.message("The human playtest folder must be private and owned by this user.")
        }
        let home = FileManager.default.homeDirectoryForCurrentUser
        for suffix in ["Library/Application Support/Kokiri", "Library/Application Support/MacNativeGames", "Library/Logs/Kokiri", "Library/Logs/MacNativeGames"] {
            if try Self.related(rootURL, home.appendingPathComponent(suffix)) {
                throw KokiriError.message("The human playtest must use its separate private folder.")
            }
        }
        guard try !Self.related(rootURL, appURL) else { throw KokiriError.message("The game and human playtest folders must be separate.") }
        let markerData = try Self.regularData(rootURL.appendingPathComponent("preview.json"), limit: 65536)
        struct Marker: Decodable { let schema: Int; let kind: String; let owner: String; let session_id: String; let executable_sha256: String }
        let marker = try JSONDecoder().decode(Marker.self, from: markerData)
        let object = try JSONSerialization.jsonObject(with: markerData) as? [String: Any]
        guard marker.schema == 1, marker.kind == "human-preview", marker.owner == "user",
              marker.session_id == session_id, marker.executable_sha256 == executable_sha256,
              object?["nonce"] == nil, object?["expires_unix"] == nil else {
            throw KokiriError.message("The human playtest marker does not match this game and session.")
        }
        for name in ["request.json", "lease.json", "ownership.json", "revoked"] {
            var item = stat()
            guard lstat(rootURL.appendingPathComponent(name).path, &item) != 0, errno == ENOENT else {
                throw KokiriError.message("Development-session state cannot be used for human play.")
            }
        }
    }

    public func launchPlan(helper: URL, mods: HumanModLaunch? = nil) throws -> (executable: URL, arguments: [String], environment: [String: String]) {
        try verifyMarker()
        let source = try Self.regularData(helper, limit: 65536)
        guard SHA256.hash(data: source).map({ String(format: "%02x", $0) }).joined() == Self.helperSHA256,
              FileManager.default.isExecutableFile(atPath: python) else {
            throw KokiriError.message("The verified human launch helper or Python is unavailable.")
        }
        let account = getpwuid(getuid())
        guard let account else { throw KokiriError.message("The current Mac account could not be verified.") }
        let user = String(cString: account.pointee.pw_name), home = String(cString: account.pointee.pw_dir)
        var arguments = ["-I", "-B", helper.path, "--app", app, "--private-root", root]
        if let mods {
            try mods.verify(binding: self)
            arguments += ["--mods-session", mods.launchID, "--mods-sha256", mods.handoffSHA256]
        }
        return (URL(fileURLWithPath: python), arguments,
                ["HOME": home, "USER": user, "LOGNAME": user, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8"])
    }

    public func launch(helper: URL, mods: HumanModLaunch? = nil) throws -> Int32 {
        let plan = try launchPlan(helper: helper, mods: mods)
        let process = Process(), output = Pipe(), errors = Pipe()
        process.executableURL = plan.executable; process.arguments = plan.arguments; process.environment = plan.environment
        process.currentDirectoryURL = appURL; process.standardInput = FileHandle.nullDevice
        process.standardOutput = output; process.standardError = errors
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        let errorData = errors.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        struct Reply: Decodable { let status: String; let pid: Int32; let owner: String; let control: String }
        guard process.terminationStatus == 0, data.count <= 65536,
              let reply = try? JSONDecoder().decode(Reply.self, from: data), reply.pid > 1,
              reply.status == "starting", reply.owner == "user", reply.control == "observation-only" else {
            let detail = String(decoding: errorData.prefix(4096), as: UTF8.self)
            throw KokiriError.message(detail.isEmpty ? "The prepared game could not start." : detail)
        }
        return reply.pid
    }

    public func acknowledges(pid: Int32, start: UInt64, expectedMods: HumanModLaunch? = nil, requireUnmodded: Bool = false) -> Bool {
        struct Mods: Decodable {
            let schema: Int; let launch_id: String; let handoff_sha256: String; let manifest_sha256: String
            let overlay: String; let files: Int
        }
        struct Session: Decodable {
            let pid: Int32; let process_start: UInt64; let executable: String; let executable_sha256: String
            let owner: String; let control: String; let kind: String; let session_id: String
            let phase: String?; let game_slot_acquired: Bool?
            let mods_handoff: Mods?
        }
        guard let data = try? Self.regularData(rootURL.appendingPathComponent("session.json"), limit: 65536),
              let session = try? JSONDecoder().decode(Session.self, from: data),
              let isolationData = try? Self.regularData(rootURL.appendingPathComponent("isolation.json"), limit: 65536),
              let isolation = try? JSONDecoder().decode(Session.self, from: isolationData) else { return false }
        func matches(_ value: Session) -> Bool {
            guard value.pid == pid && value.process_start == start && value.executable_sha256 == executable_sha256
                && value.executable == appURL.appendingPathComponent("Contents/MacOS/KokiriGame").path
                && value.owner == "user" && value.control == "observation-only" && value.kind == "human-preview"
                && value.session_id == session_id else { return false }
            guard let record = value.mods_handoff else { return expectedMods == nil }
            guard !requireUnmodded, record.schema == 1, (1...20000).contains(record.files),
                  record.overlay == rootURL.appendingPathComponent("mods/\(record.launch_id)/mods").path else { return false }
            let mods = HumanModLaunch(launchID: record.launch_id, handoffSHA256: record.handoff_sha256, manifestSHA256: record.manifest_sha256)
            guard (try? mods.verify(binding: self)) != nil else { return false }
            return expectedMods == nil || (record.launch_id == expectedMods?.launchID
                && record.handoff_sha256 == expectedMods?.handoffSHA256 && record.manifest_sha256 == expectedMods?.manifestSHA256)
        }
        return matches(session) && matches(isolation) && session.mods_handoff?.launch_id == isolation.mods_handoff?.launch_id
            && session.mods_handoff?.handoff_sha256 == isolation.mods_handoff?.handoff_sha256
            && isolation.phase == "slot-acquired"
            && isolation.game_slot_acquired == true
    }
}
