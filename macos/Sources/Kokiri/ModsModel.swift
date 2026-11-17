import AppKit
import Combine
import Foundation
import KokiriCore

@MainActor final class ModsModel: ObservableObject {
    @Published private(set) var state = ModLibraryState()
    @Published private(set) var conflicts: [String: [String]] = [:]
    @Published private(set) var busy = false
    @Published private(set) var message: String?
    @Published private(set) var failed = false
    @Published private(set) var gameRunning = false
    @Published private(set) var launchBlocker: String?
    let library: ModLibrary
    private var installation: GameInstallation?

    init(root: URL = KokiriPaths.support.appendingPathComponent("Mods")) {
        library = ModLibrary(root: root)
    }

    var selected: ModProfile { state.selected }
    var enabledCount: Int { selected.enabled.count }
    var selectedPacks: [ModPack] { state.orderedPacks }
    var macNativeAvailable: Bool { FileManager.default.isReadableFile(atPath: ModLibrary.macNativeLibrary.appendingPathComponent("library.json").path) }

    func setContext(installation: GameInstallation?, gameRunning: Bool, launchSupported: Bool = true, mode: ModLaunchMode = .ordinary) {
        self.installation = installation
        self.gameRunning = gameRunning
        if !launchSupported { launchBlocker = "This preview doesn’t launch mods. Play continues without mods." }
        else if let installation { launchBlocker = ModLibrary.launchBlocker(app: installation.app, mode: mode) }
        else { launchBlocker = "Connect a game in Setup before playing with mods." }
    }

    func refresh() { perform { _ in nil } }
    func select(_ id: String) { perform { library in try library.selectProfile(id); return nil } }
    func create(_ name: String, duplicate: Bool) {
        perform { library in try library.createProfile(name, duplicate: duplicate); return "Created mod profile \(name)." }
    }
    func rename(_ name: String) { perform { library in try library.renameProfile(name); return "Renamed mod profile." } }
    func delete() { perform { library in try library.deleteSelectedProfile(); return "Deleted the mod profile. Mod files remain in your library." } }
    func toggle(_ pack: ModPack, enabled: Bool) { perform { library in try library.setEnabled(pack.id, enabled: enabled); return nil } }
    func move(_ pack: ModPack, by offset: Int) { perform { library in try library.move(pack.id, by: offset); return nil } }

    func importFolder() {
        guard !busy else { return }
        let panel = NSOpenPanel(); panel.title = "Import a RomFS mod folder"; panel.prompt = "Copy Mod"
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.message = "Choose a mod folder containing romfs. Code patches and cheats are not supported."
        guard panel.runModal() == .OK, let source = panel.url else { return }
        perform { library in try library.importFolder(source); return "Copied the mod into Kokiri. Enable it in a profile when ready." }
    }

    func importMacNative() {
        guard !busy else { return }
        let alert = NSAlert(); alert.messageText = "Copy your MacNative Mods library?"
        alert.informativeText = "Kokiri copies the Ocarina of Time mod files and named profiles into its own library. MacNative Mods and its applied game files stay in place. Your selected Kokiri profile stays selected."
        alert.addButton(withTitle: "Copy Library"); alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        perform { library in
            let count = try library.importMacNativeLibrary()
            return "Copied \(count) mods and their profiles from MacNative Mods. Choose an imported profile to use its selection."
        }
    }

    func revealLibrary() {
        let url = FileManager.default.fileExists(atPath: library.root.path) ? library.root : library.root.deletingLastPathComponent()
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    func prepareLaunch(app: URL, gameDataFolder: URL, sessionFolder: URL) async throws -> [String: String] {
        guard !busy else { throw KokiriError.message("Finish updating the mod library before starting the game.") }
        guard !gameRunning else { throw KokiriError.message("Finish the current game session before preparing mods.") }
        busy = true; defer { busy = false }
        let library = library
        return try await Task.detached(priority: .userInitiated) {
            try library.prepareLaunch(app: app, gameDataFolder: gameDataFolder, sessionFolder: sessionFolder)
        }.value
    }

    func prepareHumanLaunch(binding: HumanPreviewBinding) async throws -> HumanModLaunch? {
        guard !busy, !gameRunning else { throw KokiriError.message("Finish the current game or mod operation before preparing mods.") }
        busy = true; defer { busy = false }
        let library = library
        return try await Task.detached(priority: .userInitiated) { try binding.prepareModLaunch(library: library) }.value
    }

    func dismissMessage() { message = nil }

    private func perform(_ operation: @escaping @Sendable (ModLibrary) throws -> String?) {
        guard !busy else { return }
        busy = true; failed = false
        let library = library
        Task {
            defer { busy = false }
            do {
                let result = try await Task.detached(priority: .utility) {
                    let message = try operation(library)
                    return (try library.load(), try library.conflicts(), message)
                }.value
                state = result.0; conflicts = result.1
                if let text = result.2 { message = text }
            } catch { failed = true; message = error.localizedDescription }
        }
    }
}
