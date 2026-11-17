import Foundation
import CryptoKit
import CoreFoundation
import Darwin

public struct ModPack: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let detail: String
    public let files: Int
    public let bytes: UInt64
}

public struct ModProfile: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public var name: String
    public var order: [String]
    public var enabled: [String]
}

public struct ModLibraryState: Codable, Equatable, Sendable {
    public var schema = 1
    public var packs: [ModPack] = []
    public var profiles = [ModProfile(id: "default", name: "Default", order: [], enabled: [])]
    public var selectedProfile = "default"
    public var selected: ModProfile { profiles.first { $0.id == selectedProfile }! }
    public var orderedPacks: [ModPack] { selected.order.compactMap { id in packs.first { $0.id == id } } }
    public init() {}
}

/// A separate Kokiri library. Foreign manager libraries are read-only import sources.
public struct ModLibrary: Sendable {
    public let root: URL
    private var record: URL { root.appendingPathComponent("library.json") }
    public static var macNativeLibrary: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/MacNativeMods/mod-library/oot")
    }
    public init(root: URL) { self.root = root.standardizedFileURL }

    public static func supportsLaunch(app: URL) -> Bool { launchBlocker(app: app) == nil }

    public static func launchBlocker(app: URL) -> String? {
        guard let data = try? boundedData(app.appendingPathComponent("Contents/Info.plist"), limit: 1 << 20),
              let info = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else {
            return "The connected game does not advertise verified mod support."
        }
        if info["KokiriHumanPreviewVersion"] != nil { return "This private game preview does not support launching mod profiles yet." }
        guard let version = info["KokiriRomFSModsVersion"] as? NSNumber,
              CFGetTypeID(version) != CFBooleanGetTypeID(), ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: version.objCType)),
              version.intValue == 1 else {
            return "The connected game needs a build with Kokiri RomFS mod support version 1."
        }
        return nil
    }

    public func load() throws -> ModLibraryState {
        guard FileManager.default.fileExists(atPath: record.path) else { return ModLibraryState() }
        try Self.regular(record)
        let data = try Self.boundedData(record, limit: 1 << 20)
        let state = try JSONDecoder().decode(ModLibraryState.self, from: data)
        try validate(state)
        return state
    }

    public func save(_ state: ModLibraryState) throws {
        try validate(state)
        try ensureRoot()
        if FileManager.default.fileExists(atPath: record.path) { try Self.regular(record) }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(state).write(to: record, options: .atomic)
    }

    public func createProfile(_ name: String, duplicate: Bool) throws {
        var state = try load()
        guard state.profiles.count < 64 else { throw fail("Keep at most 64 mod profiles.") }
        let name = try validName(name, in: state)
        let profile = ModProfile(id: UUID().uuidString.lowercased(), name: name,
                                 order: state.selected.order, enabled: duplicate ? state.selected.enabled : [])
        state.profiles.append(profile); state.selectedProfile = profile.id
        try save(state)
    }

    public func selectProfile(_ id: String) throws {
        var state = try load()
        guard state.profiles.contains(where: { $0.id == id }) else { throw fail("That mod profile no longer exists.") }
        state.selectedProfile = id; try save(state)
    }

    public func renameProfile(_ name: String) throws {
        var state = try load()
        let name = try validName(name, in: state, excluding: state.selectedProfile)
        state.profiles[state.profiles.firstIndex { $0.id == state.selectedProfile }!].name = name
        try save(state)
    }

    public func deleteSelectedProfile() throws {
        var state = try load()
        guard state.profiles.count > 1 else { throw fail("Keep at least one mod profile.") }
        state.profiles.removeAll { $0.id == state.selectedProfile }
        state.selectedProfile = state.profiles[0].id; try save(state)
    }

    public func setEnabled(_ id: String, enabled: Bool) throws {
        var state = try load()
        guard state.packs.contains(where: { $0.id == id }) else { throw fail("That mod is no longer in the library.") }
        let index = state.profiles.firstIndex { $0.id == state.selectedProfile }!
        state.profiles[index].enabled.removeAll { $0 == id }
        if enabled { state.profiles[index].enabled.append(id) }
        try save(state)
    }

    public func move(_ id: String, by offset: Int) throws {
        var state = try load()
        let p = state.profiles.firstIndex { $0.id == state.selectedProfile }!
        guard let index = state.profiles[p].order.firstIndex(of: id),
              state.profiles[p].order.indices.contains(index + offset), abs(offset) == 1 else { return }
        state.profiles[p].order.swapAt(index, index + offset); try save(state)
    }

    @discardableResult public func importFolder(_ source: URL, name: String? = nil) throws -> Int {
        var state = try load()
        let staged = try stagePack(source, name: name ?? source.lastPathComponent)
        defer { try? FileManager.default.removeItem(at: staged.folder) }
        let destination = packFolder(staged.pack.id)
        try FileManager.default.moveItem(at: staged.folder, to: destination)
        do {
            state.packs.append(staged.pack)
            for index in state.profiles.indices { state.profiles[index].order.append(staged.pack.id) }
            try save(state)
        } catch { try? FileManager.default.removeItem(at: destination); throw error }
        return 1
    }

    /// Copies every pack and named profile; the current Kokiri selection stays unchanged.
    @discardableResult public func importMacNativeLibrary(_ source: URL = ModLibrary.macNativeLibrary) throws -> Int {
        try Self.directory(source)
        let sourceRecord = source.appendingPathComponent("library.json")
        try Self.regular(sourceRecord)
        let before = try Self.boundedData(sourceRecord, limit: 1 << 20)
        guard let object = try JSONSerialization.jsonObject(with: before) as? [String: Any],
              object["format"] as? Int == 1, let order = object["order"] as? [String],
              let names = object["names"] as? [String: String],
              let profiles = object["profiles"] as? [String: [String: [String]]],
              let selectedName = object["selected_profile"] as? String,
              let activeEnabled = object["enabled"] as? [String],
              !order.isEmpty, order.count <= 1000, Set(order).count == order.count,
              order.allSatisfy(Self.validID), profiles[selectedName] != nil,
              Self.emptyCodeRecord(object["code"]) else {
            throw fail("Choose a MacNative Mods Ocarina of Time library with RomFS-only packs.")
        }
        var state = try load()
        guard state.packs.count + order.count <= 1000, state.profiles.count + profiles.count <= 64 else {
            throw fail("The imported library would exceed 1,000 mods or 64 profiles.")
        }
        var copies: [(pack: ModPack, folder: URL)] = []
        var installed: [URL] = []
        defer { for copy in copies { try? FileManager.default.removeItem(at: copy.folder) } }
        do {
            for id in order { copies.append(try stagePack(source.appendingPathComponent(id), name: names[id] ?? id)) }
            let ids = Dictionary(uniqueKeysWithValues: zip(order, copies.map { $0.pack.id }))
            for index in state.profiles.indices { state.profiles[index].order += copies.map { $0.pack.id } }
            for name in profiles.keys.sorted() {
                let sourceProfile = profiles[name]!
                let sourceOrder = name == selectedName ? order : sourceProfile["order"] ?? []
                let enabled = name == selectedName ? activeEnabled : sourceProfile["enabled"] ?? []
                guard Set(sourceOrder).count == sourceOrder.count, Set(enabled).count == enabled.count,
                      sourceOrder.allSatisfy({ ids[$0] != nil }), Set(enabled).isSubset(of: Set(sourceOrder)) else {
                    throw fail("The MacNative Mods profiles contain unknown or duplicate mods.")
                }
                let profileOrder = sourceOrder.compactMap { ids[$0] } + state.packs.map(\.id)
                    + order.filter { !sourceOrder.contains($0) }.compactMap { ids[$0] }
                let importedName = uniqueName("MacNative · " + name, in: state)
                state.profiles.append(ModProfile(id: UUID().uuidString.lowercased(), name: importedName,
                                                order: profileOrder, enabled: enabled.compactMap { ids[$0] }))
            }
            guard try Self.boundedData(sourceRecord, limit: 1 << 20) == before else {
                throw fail("MacNative Mods changed during the copy. Refresh and import again.")
            }
            for copy in copies {
                let destination = packFolder(copy.pack.id)
                try FileManager.default.moveItem(at: copy.folder, to: destination); installed.append(destination)
                state.packs.append(copy.pack)
            }
            try save(state)
        } catch { for url in installed { try? FileManager.default.removeItem(at: url) }; throw error }
        return copies.count
    }

    /// Paths shared by enabled packs, in load order. The last pack supplies the file.
    public func conflicts() throws -> [String: [String]] {
        let state = try load(); var owners: [String: [String]] = [:]
        for id in state.selected.order where state.selected.enabled.contains(id) {
            for file in try Self.payloadFiles(packFolder(id).appendingPathComponent("romfs")) {
                owners[file.path, default: []].append(id)
            }
        }
        return owners.filter { $0.value.count > 1 }
    }

    /// Creates a session-owned immutable overlay. Never changes the game or foreign manager folders.
    public func prepareLaunch(app: URL, gameDataFolder: URL, sessionFolder: URL) throws -> [String: String] {
        let state = try load()
        let enabled = state.selected.order.filter { state.selected.enabled.contains($0) }
        guard !enabled.isEmpty else { return ["TOTK_ROMFS_MODS": "0"] }
        if let reason = Self.launchBlocker(app: app) { throw fail(reason) }
        var files: [String: URL] = [:]
        for id in enabled {
            for file in try Self.payloadFiles(packFolder(id).appendingPathComponent("romfs")) { files[file.path] = file.url }
        }
        let reference = try ModROMFS(app: app, gameDataFolder: gameDataFolder)
        let destination = sessionFolder.appendingPathComponent("mods")
        guard !FileManager.default.fileExists(atPath: destination.path) else { throw fail("This session already has a mod overlay.") }
        try Self.directory(sessionFolder)
        let staging = sessionFolder.appendingPathComponent(".mods-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: staging) }
        var rows: [String] = []
        for path in files.keys.sorted() {
            guard !reference.reserved.contains(path) else { throw fail("\(path) conflicts with a built-in game patch.") }
            let source = files[path]!, target = staging.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            let hash = try Self.digest(source)
            try FileManager.default.copyItem(at: source, to: target)
            guard try Self.digest(target) == hash, try Self.digest(source) == hash else { throw fail("A mod changed while preparing the launch.") }
            let size = try target.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            rows.append("\(path)\t\(size)\t\(hash)\t\(try reference.originalHash(path))")
        }
        try Data(("# path\tsize\tsha256\toriginal_sha256\n" + rows.joined(separator: "\n") + "\n").utf8)
            .write(to: staging.appendingPathComponent("manifest.tsv"), options: .withoutOverwriting)
        try JSONEncoder().encode(state.selected).write(to: staging.appendingPathComponent("profile.json"), options: .withoutOverwriting)
        try FileManager.default.moveItem(at: staging, to: destination)
        return ["TOTK_ROMFS_MODS": destination.path]
    }

    private func packFolder(_ id: String) -> URL { root.appendingPathComponent("packs").appendingPathComponent(id) }
    private func fail(_ message: String) -> KokiriError { .message(message) }
    private func ensureRoot() throws {
        if FileManager.default.fileExists(atPath: root.path) { try Self.directory(root) }
        else { try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]) }
        let packs = root.appendingPathComponent("packs")
        if FileManager.default.fileExists(atPath: packs.path) { try Self.directory(packs) }
        else { try FileManager.default.createDirectory(at: packs, withIntermediateDirectories: false) }
    }
    private func validate(_ state: ModLibraryState) throws {
        let ids = state.packs.map(\.id), profiles = state.profiles.map(\.id)
        guard state.schema == 1, ids.count <= 1000, ids.allSatisfy(Self.validID), Set(ids).count == ids.count,
              (1...64).contains(profiles.count), profiles.allSatisfy(Self.validID), Set(profiles).count == profiles.count,
              profiles.contains(state.selectedProfile), Set(state.profiles.map { $0.name.lowercased() }).count == profiles.count else {
            throw fail("The Kokiri mod library record is invalid. Its files were left in place.")
        }
        for profile in state.profiles {
            guard Self.nameOK(profile.name), Set(profile.order) == Set(ids), profile.order.count == ids.count,
                  Set(profile.enabled).count == profile.enabled.count, Set(profile.enabled).isSubset(of: Set(ids)) else {
                throw fail("A mod profile contains invalid names or references.")
            }
        }
        for pack in state.packs {
            guard Self.nameOK(pack.name), pack.detail.count <= 2000, (1...20000).contains(pack.files), pack.bytes <= 4 << 30 else {
                throw fail("A mod library entry is invalid.")
            }
        }
    }
    private static func validID(_ id: String) -> Bool {
        !id.isEmpty && id.utf8.count <= 96 && id.utf8.allSatisfy { (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95 }
    }
    private static func emptyCodeRecord(_ value: Any?) -> Bool {
        guard let value else { return true }
        if let list = value as? [Any] { return list.isEmpty }
        if let mapping = value as? [String: Any] { return mapping.isEmpty }
        return false
    }
    private static func nameOK(_ name: String) -> Bool {
        !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && name.count <= 64
            && name.unicodeScalars.allSatisfy { !CharacterSet.controlCharacters.contains($0) }
    }
    private func validName(_ input: String, in state: ModLibraryState, excluding: String? = nil) throws -> String {
        let name = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.nameOK(name) else { throw fail("Use a profile name from 1 to 64 characters.") }
        guard !state.profiles.contains(where: { $0.id != excluding && $0.name.caseInsensitiveCompare(name) == .orderedSame }) else {
            throw fail("A mod profile already uses that name.")
        }
        return name
    }
    private func uniqueName(_ name: String, in state: ModLibraryState) -> String {
        let base = String(name.prefix(54)); var result = base; var count = 2
        while state.profiles.contains(where: { $0.name.caseInsensitiveCompare(result) == .orderedSame }) {
            result = "\(base) (\(count))"; count += 1
        }
        return result
    }
    private func stagePack(_ input: URL, name: String) throws -> (pack: ModPack, folder: URL) {
        try ensureRoot(); try Self.directory(input)
        guard input.lastPathComponent.caseInsensitiveCompare("romfs") != .orderedSame else {
            throw fail("Choose the complete mod folder containing romfs, rather than the romfs folder itself.")
        }
        let source = try Self.canonicalDirectory(input)
        let own = try Self.canonicalDirectory(root)
        guard source != own, !source.path.hasPrefix(own.path + "/"), !own.path.hasPrefix(source.path + "/") else {
            throw fail("Import a mod folder outside Kokiri’s own library.")
        }
        for name in ["exefs", "cheats", "patches", "code", "patches.txt"] {
            if FileManager.default.fileExists(atPath: source.appendingPathComponent(name).path) { throw fail("Code patches and cheats are not supported. Import a RomFS-only mod.") }
        }
        let metadata = source.appendingPathComponent("macnative-mod.json")
        if FileManager.default.fileExists(atPath: metadata.path) {
            guard let value = try JSONSerialization.jsonObject(with: Self.boundedData(metadata, limit: 1 << 20)) as? [String: Any],
                  value["requires"] == nil || (value["requires"] as? [Any])?.isEmpty == true else {
                throw fail("This mod declares dependencies that Kokiri cannot import yet. Import a self-contained RomFS mod.")
            }
        }
        let payload = input.appendingPathComponent("romfs")
        let files = try Self.payloadFiles(payload)
        let id = UUID().uuidString.lowercased(), staging = root.appendingPathComponent(".import-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: staging.appendingPathComponent("romfs"), withIntermediateDirectories: true)
        do {
            var bytes: UInt64 = 0
            for file in files {
                let size = try file.url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                bytes += UInt64(size)
                guard bytes <= 4 << 30 else { throw fail("A mod folder must be smaller than 4 GiB.") }
                let target = staging.appendingPathComponent("romfs").appendingPathComponent(file.path)
                try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
                let hash = try Self.digest(file.url)
                try FileManager.default.copyItem(at: file.url, to: target)
                guard try Self.digest(target) == hash, try Self.digest(file.url) == hash else { throw fail("The mod changed during the copy. Import again after it finishes updating.") }
            }
            let displayName = name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard Self.nameOK(displayName) else { throw fail("Use a mod folder name from 1 to 64 characters.") }
            var detail = "RomFS mod · \(files.count.formatted()) files"
            let description = source.appendingPathComponent(".description.txt")
            if FileManager.default.fileExists(atPath: description.path) {
                try Self.regular(description)
                detail = String(String(decoding: try Self.boundedData(description, limit: 8192), as: UTF8.self).prefix(2000))
            }
            return (ModPack(id: id, name: displayName, detail: detail, files: files.count, bytes: bytes), staging)
        } catch { try? FileManager.default.removeItem(at: staging); throw error }
    }

    fileprivate static func directory(_ url: URL) throws {
        let values = try url.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey])
        guard values.isSymbolicLink != true, values.isDirectory == true else { throw KokiriError.message("Choose a real folder without symbolic links.") }
    }
    private static func canonicalDirectory(_ url: URL) throws -> URL {
        try directory(url)
        return try url.withUnsafeFileSystemRepresentation { path in
            guard let path, let resolved = realpath(path, nil) else { throw KokiriError.message("The mod folder cannot be resolved.") }
            defer { free(resolved) }
            return URL(fileURLWithPath: String(cString: resolved), isDirectory: true)
        }
    }
    fileprivate static func regular(_ url: URL) throws {
        let values = try url.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey])
        guard values.isSymbolicLink != true, values.isRegularFile == true else { throw KokiriError.message("A mod file is missing, linked, or not a regular file.") }
    }
    fileprivate static func boundedData(_ url: URL, limit: Int) throws -> Data {
        try regular(url)
        guard let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize, size >= 0, size <= limit else {
            throw KokiriError.message("A mod metadata file is too large.")
        }
        return try Data(contentsOf: url)
    }
    fileprivate static func pathOK(_ path: String) -> Bool {
        !path.isEmpty && path.utf8.count < 4000 && !path.contains("\\") && !path.contains(":")
            && !path.unicodeScalars.contains { CharacterSet.controlCharacters.contains($0) }
            && path.split(separator: "/", omittingEmptySubsequences: false).allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
    }
    private static func payloadFiles(_ root: URL) throws -> [(path: String, url: URL)] {
        try directory(root)
        let canonical = try canonicalDirectory(root), keys: [URLResourceKey] = [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey]
        var walkError: Error?
        guard let walk = FileManager.default.enumerator(at: canonical, includingPropertiesForKeys: keys, options: [], errorHandler: { _, error in walkError = error; return false }) else {
            throw KokiriError.message("The mod folder cannot be read.")
        }
        var files: [(String, URL)] = [], seen = Set<String>()
        for case let url as URL in walk {
            let value = try url.resourceValues(forKeys: Set(keys))
            guard value.isSymbolicLink != true, value.isDirectory == true || value.isRegularFile == true,
                  url.path.hasPrefix(canonical.path + "/") else { throw KokiriError.message("Mod folders cannot contain symbolic links or special files.") }
            let path = String(url.path.dropFirst(canonical.path.count + 1))
            guard pathOK(path) else { throw KokiriError.message("A mod contains an unsafe RomFS path.") }
            if value.isDirectory == true { continue }
            if ["manifest.tsv", ".ds_store", "desktop.ini", "thumbs.db"].contains(url.lastPathComponent.lowercased()) || url.lastPathComponent.hasSuffix(".mod-original") { continue }
            guard !path.split(separator: "/").contains(where: { $0.hasPrefix(".") }), seen.insert(path.lowercased()).inserted else {
                throw KokiriError.message("A mod contains hidden files or paths that differ only by case.")
            }
            files.append((path, url))
            guard files.count <= 20000 else { throw KokiriError.message("A mod may contain at most 20,000 files.") }
        }
        if let walkError { throw walkError }
        guard !files.isEmpty else { throw KokiriError.message("Choose a mod folder containing a nonempty romfs folder.") }
        return files.sorted { $0.0 < $1.0 }
    }
    fileprivate static func digest(_ url: URL, offset: UInt64 = 0, size: UInt64? = nil) throws -> String {
        try regular(url)
        let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
        try handle.seek(toOffset: offset); var remaining = size; var hash = SHA256()
        while remaining == nil || remaining! > 0 {
            let count = Int(min(remaining ?? UInt64(1 << 20), UInt64(1 << 20)))
            let data = try handle.read(upToCount: count) ?? Data()
            if data.isEmpty {
                guard remaining == nil || remaining == 0 else { throw KokiriError.message("The game image ended before a mod’s original file.") }
                break
            }
            hash.update(data: data)
            if remaining != nil { remaining! -= UInt64(data.count) }
        }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

private struct ModROMFS {
    private struct Entry { let offset: UInt64; let size: UInt64 }
    private let image: URL
    private let entries: [String: Entry]
    private let folded: Set<String>
    let reserved: Set<String>

    init(app: URL, gameDataFolder: URL) throws {
        let resources = app.appendingPathComponent("Contents/Resources/totk")
        let romfs = resources.appendingPathComponent("extracted/oot/romfs")
        let data = try ModLibrary.boundedData(romfs.appendingPathComponent("runtime-index.bin"), limit: 128 << 20)
        let config = try ModLibrary.boundedData(resources.appendingPathComponent("build/game-data/oot/romfs-config.txt"), limit: 65536)
        var pins: [String: String] = [:]
        for line in String(decoding: config, as: UTF8.self).split(separator: "\n") {
            let fields = line.split(whereSeparator: { $0.isWhitespace })
            guard fields.count == 2, pins[String(fields[0])] == nil else { throw KokiriError.message("The game’s RomFS configuration is invalid.") }
            pins[String(fields[0])] = String(fields[1])
        }
        func hashOK(_ text: String) -> Bool { text.utf8.count == 64 && text.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) } }
        guard let pinnedSize = pins["ROMFS_IMAGE_SIZE"].flatMap(UInt64.init), pinnedSize > 0,
              let pinnedHash = pins["ROMFS_IMAGE_SHA256"], hashOK(pinnedHash),
              let indexHash = pins["ROMFS_INDEX_SHA256"], hashOK(indexHash),
              SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == indexHash else {
            throw KokiriError.message("The game’s RomFS index does not match its build configuration.")
        }
        func word(_ at: Int, _ count: Int) throws -> UInt64 {
            guard at >= 0, count > 0, at <= data.count - count else { throw KokiriError.message("The game’s RomFS index is truncated.") }
            return data[at..<at + count].enumerated().reduce(UInt64(0)) { $0 | UInt64($1.element) << (8 * $1.offset) }
        }
        guard data.count >= 24, data.prefix(8) == Data("TOTKRFS1".utf8) else { throw KokiriError.message("The connected game has no supported RomFS index.") }
        let count = try word(8, 8), strings = try word(16, 8)
        guard count < 1_000_000, strings == 24 + count * 24, strings <= UInt64(data.count) else { throw KokiriError.message("The game’s RomFS index layout is invalid.") }
        var found: [String: Entry] = [:]
        for index in 0..<Int(count) {
            let at = 24 + index * 24, offset = try word(at, 8), size = try word(at + 8, 8)
            let nameAt = try strings + word(at + 16, 4), length = try word(at + 20, 4)
            guard nameAt <= UInt64(data.count), length >= 2, length < 4000, length <= UInt64(data.count) - nameAt,
                  data[Int(nameAt + length - 1)] == 0,
                  let name = String(data: data[Int(nameAt)..<Int(nameAt + length - 1)], encoding: .utf8), ModLibrary.pathOK(name), found[name] == nil else {
                throw KokiriError.message("The game’s RomFS index contains an invalid path.")
            }
            found[name] = Entry(offset: offset, size: size)
        }
        let bundle = Bundle(url: app)
        let identifier = bundle?.bundleIdentifier ?? "com.christianfurr.kokiri.runtime"
        let defaults = UserDefaults(suiteName: identifier)?.string(forKey: "MNGGameDataFolder.oot")
        let configured = bundle?.object(forInfoDictionaryKey: "MNGGameDataFolder") as? String
        let folders = [defaults, configured].compactMap { $0 }.filter { !$0.isEmpty }.map { URL(fileURLWithPath: $0) }
            + [gameDataFolder.appendingPathComponent("GameData")]
        let candidates = [romfs.appendingPathComponent("romfs.bin")]
            + folders.flatMap { [$0.appendingPathComponent("oot/romfs.bin"), $0.appendingPathComponent("romfs.bin")] }
        let image = candidates.first { candidate in
            guard (try? ModLibrary.regular(candidate)) != nil,
                  let size = try? candidate.resourceValues(forKeys: [.fileSizeKey]).fileSize, UInt64(size) == pinnedSize else { return false }
            let marker = candidate.deletingLastPathComponent().appendingPathComponent("romfs.sha256")
            if FileManager.default.fileExists(atPath: marker.path) {
                guard let bytes = try? ModLibrary.boundedData(marker, limit: 256),
                      String(decoding: bytes, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == pinnedHash else { return false }
            }
            return true
        }
        guard let image else {
            throw KokiriError.message("Reconnect the game’s original data folder before preparing mods. Its romfs.bin is unavailable.")
        }
        try ModLibrary.regular(image)
        let imageSize = UInt64(try image.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0)
        guard found.values.allSatisfy({ $0.offset <= imageSize && $0.size <= imageSize - $0.offset }) else {
            throw KokiriError.message("The game image does not match its RomFS index.")
        }
        self.image = image; entries = found; folded = Set(found.keys.map { $0.lowercased() })
        // OoT’s plain romfs-patches is the optional shortened opening, disabled in ordinary play.
        let outputs = resources.appendingPathComponent("extracted/oot/romfs-patches-out")
        let overlays = (try? FileManager.default.contentsOfDirectory(at: outputs, includingPropertiesForKeys: nil)) ?? []
        var reserved = Set<String>()
        for overlay in overlays {
            let manifest = overlay.appendingPathComponent("manifest.tsv")
            if FileManager.default.fileExists(atPath: manifest.path) {
                let text = String(decoding: try ModLibrary.boundedData(manifest, limit: 8 << 20), as: UTF8.self)
                for line in text.split(separator: "\n") where !line.hasPrefix("#") {
                    if let path = line.split(separator: "\t").first { reserved.insert(String(path)) }
                }
            }
        }
        self.reserved = reserved
    }

    func originalHash(_ path: String) throws -> String {
        if let entry = entries[path] { return try ModLibrary.digest(image, offset: entry.offset, size: entry.size) }
        guard !folded.contains(path.lowercased()) else { throw KokiriError.message("\(path) differs in case from an existing game file.") }
        return "-"
    }
}
