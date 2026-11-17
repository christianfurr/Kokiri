import Foundation

/// Fast structural checks for the picker. The builder remains responsible for content hashes.
public struct SetupDraft: Codable, Sendable {
    public var step: Int
    public var game: URL?
    public var fonts: URL?
    public var work: URL
    public var output: URL
    public init(step: Int, game: URL?, fonts: URL?, work: URL, output: URL) {
        self.step = step; self.game = game; self.fonts = fonts; self.work = work; self.output = output
    }
}

public enum SetupInput {
    private static func resolvedPath(_ url: URL) -> String {
        var ancestor = url.standardizedFileURL
        var missing: [String] = []
        while !FileManager.default.fileExists(atPath: ancestor.path), ancestor.path != "/" {
            missing.append(ancestor.lastPathComponent)
            ancestor.deleteLastPathComponent()
        }
        var resolved = ancestor.resolvingSymlinksInPath()
        for name in missing.reversed() { resolved.appendPathComponent(name) }
        return resolved.standardizedFileURL.path
    }
    public static func isOutside(_ candidate: URL, _ root: URL) -> Bool {
        let candidate = resolvedPath(candidate), root = resolvedPath(root)
        return candidate != root && !candidate.hasPrefix(root == "/" ? "/" : root + "/")
    }
    public static func gameProblem(_ url: URL) -> String? {
        let fm = FileManager.default
        var directory: ObjCBool = false
        guard fm.fileExists(atPath: url.path, isDirectory: &directory) else { return "The selected game is no longer available. Choose it again." }
        if !directory.boolValue {
            return url.pathExtension.lowercased() == "nup" ? nil : "Choose a complete .nup package or extracted Switch 2 dump folder. N64/3DS ROMs and NSP/XCI files are unsupported."
        }
        let romfs = url.appendingPathComponent("updates/131072/romfs")
        guard fm.fileExists(atPath: romfs.path, isDirectory: &directory), directory.boolValue else {
            return "Choose the dump root containing updates/131072/romfs, with the complete patched game data."
        }
        let code = ["updates/131072/exefs", "base/exefs"].contains { path in
            ["main", "subsdk0", "sdk"].allSatisfy { fm.isReadableFile(atPath: url.appendingPathComponent(path).appendingPathComponent($0).path) }
        }
        return code ? nil : "This dump is missing executable files in updates/131072/exefs or base/exefs."
    }

    public static func fontsProblem(_ url: URL) -> String? {
        let names = ["0-standard", "1-chinese-simplified", "2-chinese-simplified-extension", "3-chinese-traditional", "4-korean", "5-nintendo-extension"]
        guard FileManager.default.isReadableFile(atPath: url.appendingPathComponent("manifest.json").path),
              names.allSatisfy({ FileManager.default.isReadableFile(atPath: url.appendingPathComponent($0 + ".bfttf").path) }) else {
            return "Choose the extracted shared-fonts folder containing all six .bfttf files and manifest.json. A firmware ZIP or ordinary font folder will not work."
        }
        return nil
    }
}
