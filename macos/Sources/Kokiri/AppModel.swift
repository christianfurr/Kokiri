import AppKit
import Combine
import Foundation
import KokiriCore
import UniformTypeIdentifiers
import CryptoKit

enum Destination: String, CaseIterable, Identifiable {
    case home = "Home", performance = "Performance", shaders = "Shader Library", settings = "Settings"
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .home: "leaf"
        case .performance: "waveform.path.ecg"
        case .shaders: "square.stack.3d.up"
        case .settings: "slider.horizontal.3"
        }
    }
}

@MainActor final class AppModel: ObservableObject {
    @Published var selection: Destination? = .home
    @Published var preferences: LauncherPreferences
    @Published var message: String?
    @Published var busy = false
    @Published var runtime: NSRunningApplication?
    @Published var snapshot = PerformanceSnapshot()
    @Published var recording: RecordedSession?
    @Published var sessionFolder: URL?
    @Published var connected = false
    @Published var timingUpdatedAt: Date?
    @Published var shaderCounts: [String: Int] = [:]
    @Published var collectedShaderCounts: [String: Int] = [:]
    @Published var preparation: RuntimePreparation?
    @Published var shaderRefreshPending = false
    @Published var buildOutput = ""
    @Published var onboarding = false
    @Published var setupPresented = false
    @Published var installationUnavailable = false
    @Published var setupReady = false
    @Published var setupStep = -1 { didSet { persistSetupDraft() } }
    @Published var setupGame: URL? { didSet { persistSetupDraft() } }
    @Published var setupFonts: URL? { didSet { persistSetupDraft() } }
    @Published var setupGameProblem: String?
    @Published var setupFontsProblem: String?
    @Published var setupWork = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Kokiri/Preparation") { didSet { persistSetupDraft() } }
    @Published var setupOutput = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/Kokiri Game.app") { didSet { persistSetupDraft() } }
    @Published var buildStage = "Not started"
    @Published var building = false
    @Published var buildSucceeded = false
    @Published var hud = HUDPreferences()
    let updates = UpdateService()
    let catalog: CatalogFacade

    private var loadingSetupDraft = true
    private let preferenceFile = KokiriPaths.support.appendingPathComponent("launcher.json")
    private let humanPreview: HumanPreviewBinding?
    private let humanPreviewRequested: Bool
    private var humanPreviewError: String?
    private var hudFolder: URL { humanPreview?.settingsURL ?? KokiriPaths.game }
    private var sampleStart: UInt64?
    private var activeInstallation: GameInstallation?
    private var tails: [String: LineTail] = [:]
    private var timer: Timer?
    private var nextLocation = Date.distantPast
    private var locationPending: String?
    private var buildProcess: Process?
    private var nextProcessWrite = Date.distantPast
    private var catalogCheckpoint: RuntimeMetadataCheckpoint?
    private var catalogContext: Data?
    private var catalogObservation: AnyCancellable?

    init() {
        let arguments = ProcessInfo.processInfo.arguments
        let resource = Bundle.main.url(forResource: "KokiriHumanPreviewBinding", withExtension: "json")
        humanPreviewRequested = arguments.contains("--human-preview") || resource != nil
        var binding: HumanPreviewBinding?
        do { binding = try HumanPreviewBinding.selected(arguments: arguments, resource: resource) }
        catch { humanPreviewError = error.localizedDescription }
        humanPreview = binding
        if humanPreviewRequested {
            var previewPreferences = LauncherPreferences()
            previewPreferences.observeSessions = true
            preferences = previewPreferences
        } else {
            preferences = LauncherPreferences.load(from: preferenceFile)
        }
        if let binding {
            catalog = CatalogFacade(store: binding.rootURL.appendingPathComponent("Catalog"), allowsContributions: false)
        } else { catalog = CatalogFacade() }
        hud = HUDPreferences.read(from: binding?.settingsURL ?? KokiriPaths.game)
        catalogObservation = catalog.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
        if !humanPreviewRequested, let data = try? Data(contentsOf: KokiriPaths.support.appendingPathComponent("setup-draft.json")),
           let draft = try? JSONDecoder().decode(SetupDraft.self, from: data) {
            setupGame = draft.game; setupFonts = draft.fonts; setupWork = draft.work; setupOutput = draft.output
            setupStep = min(2, max(-1, draft.step))
            setupGameProblem = draft.game.flatMap(SetupInput.gameProblem)
            setupFontsProblem = draft.fonts.flatMap(SetupInput.fontsProblem)
            if setupGameProblem != nil || (setupStep > 0 && setupGame == nil) { setupStep = 0 }
            else if setupFontsProblem != nil || (setupStep > 1 && setupFonts == nil) { setupStep = 1 }
        }
        loadingSetupDraft = false
        onboarding = !humanPreviewRequested && preferences.installation == nil
        refreshInstallation()
        if let binding {
            sessionFolder = binding.rootURL
            reconnectHumanPreview()
            Task {
                let previous = await Task.detached(priority: .utility) { RecordedSession.recentSnapshot(binding.rootURL) }.value
                if !running { snapshot = previous }
            }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        if let error = humanPreviewError { message = error }
        if let at = arguments.firstIndex(of: "--recording"), arguments.indices.contains(at + 1) {
            loadRecording(URL(fileURLWithPath: arguments[at + 1]))
        }
        if let at = arguments.firstIndex(of: "--page"), arguments.indices.contains(at + 1),
           let page = Destination.allCases.first(where: { $0.rawValue.caseInsensitiveCompare(arguments[at + 1]) == .orderedSame }) {
            selection = page
        }
    }

    var isPlaytest: Bool { humanPreviewRequested }
    var profileFolder: URL { humanPreview?.rootURL.appendingPathComponent("profile") ?? KokiriPaths.profile }
    var gameDataFolder: URL { humanPreview?.rootURL ?? KokiriPaths.game }
    var canImportProfile: Bool { !humanPreviewRequested && !busy && !anyGameRunning }
    var collectedRecipeCount: Int { collectedShaderCounts.values.reduce(0, +) }
    var running: Bool { runtime?.isTerminated == false }
    var anyGameRunning: Bool {
        ["com.christianfurr.kokiri.runtime", "org.macnativegames.oot"].contains {
            !NSRunningApplication.runningApplications(withBundleIdentifier: $0).isEmpty
        }
    }
    var installation: GameInstallation? {
        if humanPreviewRequested { return humanPreview.flatMap { try? GameInstallation.inspect($0.appURL) } }
        return installationUnavailable ? nil : preferences.installation
    }
    var canManageGame: Bool { !isPlaytest && !busy && !building && !anyGameRunning }
    var supportsHUD: Bool { installation.flatMap { Bundle(url: $0.app)?.object(forInfoDictionaryKey: "KokiriHUDPreferencesVersion") as? Int } == 1 }
    var stateTitle: String {
        if running, activeInstallation?.supportsLiveStatus != true { return "Game running" }
        if running { return connected ? "Session connected" : "Starting game" }
        if anyGameRunning { return "Another game session is open" }
        if installationUnavailable { return "Game unavailable" }
        return installation == nil ? "Set up your game" : "Ready to launch"
    }
    var isStale: Bool { !running || timingUpdatedAt.map { Date().timeIntervalSince($0) > 5 } ?? true }

    func savePreferences() {
        guard !humanPreviewRequested else { return }
        do { try preferences.save(to: preferenceFile) } catch { message = error.localizedDescription }
    }
    func refreshInstallation() {
        if humanPreviewRequested { refreshShaders(); return }
        if let selected = preferences.installation {
            do {
                preferences.installation = try GameInstallation.inspect(selected.app)
                if installationUnavailable { message = nil }
                installationUnavailable = false
            }
            catch { installationUnavailable = true; message = "Your connected game could not be opened. Locate it or reconnect its drive, then try again." }
        }
        refreshShaders()
    }
    private func persistSetupDraft() {
        guard !loadingSetupDraft, !humanPreviewRequested else { return }
        let draft = SetupDraft(step: setupStep, game: setupGame, fonts: setupFonts, work: setupWork, output: setupOutput)
        do {
            try FileManager.default.createDirectory(at: KokiriPaths.support, withIntermediateDirectories: true)
            try JSONEncoder().encode(draft).write(to: KokiriPaths.support.appendingPathComponent("setup-draft.json"), options: .atomic)
        } catch { message = "Setup choices could not be saved. Keep Kokiri open to retain your selections." }
    }
    func beginSetup() {
        guard canManageGame else { return }
        setupReady = false
        setupPresented = true
    }
    func finishSetup() {
        guard !building else { return }
        onboarding = false; setupPresented = false; setupReady = false; selection = .home
        if installation != nil { setupStep = -1 }
    }
    func connectInstallation(_ url: URL) {
        guard canManageGame else { return }
        do {
            preferences = try InstallationConnection.connect(url, preferences: preferences, savingTo: preferenceFile)
            installationUnavailable = false
            refreshShaders(); setupReady = onboarding || setupPresented
            message = nil
        } catch { message = error.localizedDescription }
    }
    func chooseInstallation() {
        guard canManageGame else { return }
        guard !humanPreviewRequested else { message = "This playtest uses the prepared Kokiri game."; return }
        let panel = NSOpenPanel(); panel.title = "Connect your game"; panel.prompt = "Connect Game"
        panel.allowedContentTypes = [.applicationBundle]; panel.canChooseDirectories = false
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications")
        guard panel.runModal() == .OK, let url = panel.url else { return }
        connectInstallation(url)
    }
    func chooseRepository() {
        guard !humanPreviewRequested else { return }
        guard let url = chooseFolder(title: "Choose the Kokiri source folder", prompt: "Use Source") else { return }
        guard FileManager.default.isReadableFile(atPath: url.appendingPathComponent("engine/build.py").path) else {
            message = "Choose the Kokiri repository containing engine/build.py."; return
        }
        preferences.repository = url; savePreferences()
    }
    func chooseFolder(title: String, prompt: String, suggested: URL? = nil) -> URL? {
        let panel = NSOpenPanel(); panel.title = title; panel.prompt = prompt
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
        panel.directoryURL = suggested
        return panel.runModal() == .OK ? panel.url : nil
    }
    func reveal(_ url: URL) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
    func importProfile() {
        guard !humanPreviewRequested else { message = "Your copied player profile is already connected."; return }
        guard !busy, !building else { return }
        guard !anyGameRunning else { message = "Close Ocarina of Time before importing a save profile."; return }
        guard let source = chooseFolder(title: "Import a complete player profile", prompt: "Copy Profile", suggested: KokiriPaths.legacyProfile) else { return }
        let alert = NSAlert(); alert.messageText = "Copy this profile into Kokiri?"
        alert.informativeText = "The complete folder will be verified and copied. The original stays in place. An existing Kokiri profile is never replaced."
        alert.addButton(withTitle: "Copy Profile"); alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        guard !anyGameRunning else { message = "Close Ocarina of Time before importing a save profile."; return }
        busy = true
        Task {
            defer { busy = false }
            do {
                let count = try await Task.detached(priority: .userInitiated) { try ProfileImport.copy(from: source, to: KokiriPaths.profile) }.value
                message = "Imported \(count) files. Your original profile was left untouched."
            } catch { message = error.localizedDescription }
        }
    }

    func play() {
        if let runtime, !runtime.isTerminated { runtime.activate(options: [.activateAllWindows]); return }
        guard !busy, !building else { return }
        if reconnectHumanPreview() { runtime?.activate(options: [.activateAllWindows]); return }
        guard !anyGameRunning else { message = "Another game session is running. Finish it before starting Kokiri’s profile."; return }
        if humanPreviewRequested { playHumanPreview(); return }
        guard let selected = installation else { if installationUnavailable { refreshInstallation() } else { beginSetup() }; return }
        busy = true
        Task {
            defer { busy = false }
            do {
                let verified = try GameInstallation.inspect(selected.app)
                let folder = KokiriPaths.sessions.appendingPathComponent(ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-") + "-" + UUID().uuidString.prefix(8))
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                try FileManager.default.createDirectory(at: KokiriPaths.game, withIntermediateDirectories: true)
                let input = folder.appendingPathComponent("input.txt"), status = folder.appendingPathComponent("status.jsonl")
                for file in [input, status] {
                    try Data().write(to: file, options: .withoutOverwriting)
                    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
                }
                let configuration = NSWorkspace.OpenConfiguration()
                // No graphics, mod, shader, focus or player-input overrides.
                var environment = ["TOTK_PROFILE_DIR": KokiriPaths.profile.path,
                                   "TOTK_GAME_SLOT_DIR": KokiriPaths.sharedSlot.path,
                                   "TOTK_INPUT_FILE": input.path, "OOT_EDITOR_STATUS": status.path,
                                   "TOTK_CLOUD_SAVE_DIR": "0"]
                if preferences.observeSessions {
                    environment["DM_NVN_TSV"] = folder.appendingPathComponent("timings.tsv").path
                    environment["DM_NVN_TSV_CALLS"] = "0"
                }
                environment.merge(await catalog.launchEnvironment(runtime: verified.app, session: folder)) { _, new in new }
                configuration.environment = environment
                catalogCheckpoint = nil; catalogContext = nil
                if catalog.consent == true {
                    do {
                        let contextURL = verified.app.appendingPathComponent("Contents/Resources/KokiriCatalogContext.json")
                        guard let size = try contextURL.resourceValues(forKeys: [.fileSizeKey]).fileSize, size <= 65536 else {
                            throw KokiriError.message("The runtime has no bounded catalog context. Sharing for this session was deferred.")
                        }
                        let context = try Data(contentsOf: contextURL)
                        let checkpoint = try RuntimeMetadataDelta.checkpoint(KokiriPaths.profile.appendingPathComponent("pso_user.tsv"))
                        try context.write(to: folder.appendingPathComponent("catalog-context.json"), options: .atomic)
                        try JSONEncoder().encode(checkpoint).write(to: folder.appendingPathComponent("catalog-prefix.json"), options: .atomic)
                        let contextHash = SHA256.hash(data: context).map { String(format: "%02x", $0) }.joined()
                        try Data((contextHash + "\n").utf8).write(to: folder.appendingPathComponent("catalog-context.sha256"), options: .atomic)
                        catalogCheckpoint = checkpoint; catalogContext = context
                    } catch { catalog.deferSharing(error.localizedDescription) }
                }
                // Catalog preparation can suspend. Recheck before opening an app that
                // NSWorkspace could otherwise reuse with another player's environment.
                guard !anyGameRunning else {
                    throw KokiriError.message("Another game session opened during preparation. Finish it before starting Kokiri’s profile.")
                }
                let launched = try await NSWorkspace.shared.openApplication(at: verified.app, configuration: configuration)
                guard let sample = ProcessSample.read(pid: launched.processIdentifier),
                      ProcessSample.executable(pid: launched.processIdentifier) == verified.executable.path else {
                    throw KokiriError.message("The game opened, but its process could not be verified. Monitoring was not attached.")
                }
                runtime = launched; activeInstallation = verified; sessionFolder = folder; sampleStart = sample.start
                recording = nil; snapshot = PerformanceSnapshot(); connected = false; timingUpdatedAt = nil
                locationPending = nil; nextLocation = .distantPast
                tails = ["timing": LineTail(folder.appendingPathComponent("timings.tsv")),
                         "presented": LineTail(folder.appendingPathComponent("timings.tsv.presented.tsv")),
                         "status": LineTail(status)]
                let metadata: [String: Any] = ["pid": launched.processIdentifier, "executable": verified.executable.path,
                    "started": Date().timeIntervalSince1970, "process_start": sample.start,
                    "game_update": verified.gameUpdate, "product_version": verified.productVersion,
                    "telemetry": preferences.observeSessions, "source_commit": verified.sourceCommit ?? "unknown"]
                try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys])
                    .write(to: folder.appendingPathComponent("session.json"), options: .atomic)
                message = nil
            } catch { activeInstallation = nil; message = error.localizedDescription }
        }
    }

    @discardableResult private func reconnectHumanPreview() -> Bool {
        guard let binding = humanPreview, (try? binding.verifyMarker()) != nil,
              let verified = try? GameInstallation.inspect(binding.appURL) else { return false }
        for application in NSRunningApplication.runningApplications(withBundleIdentifier: verified.bundleID) {
            let pid = application.processIdentifier
            guard let sample = ProcessSample.read(pid: pid),
                  ProcessSample.executable(pid: pid) == verified.executable.path,
                  binding.acknowledges(pid: pid, start: sample.start),
                  ProcessSample.read(pid: pid)?.start == sample.start else { continue }
            observeHumanPreview(application, installation: verified, sample: sample, binding: binding, resuming: true)
            return true
        }
        return false
    }

    private func observeHumanPreview(_ application: NSRunningApplication, installation: GameInstallation,
                                     sample: ProcessSample, binding: HumanPreviewBinding, resuming: Bool) {
        runtime = application; activeInstallation = installation; sessionFolder = binding.rootURL; sampleStart = sample.start
        recording = nil; snapshot = PerformanceSnapshot(); connected = false; timingUpdatedAt = nil
        locationPending = nil; nextLocation = .distantPast; nextProcessWrite = .distantPast
        tails = ["timing": LineTail(binding.rootURL.appendingPathComponent("timings.tsv"), startAtEnd: resuming),
                 "presented": LineTail(binding.rootURL.appendingPathComponent("timings.tsv.presented.tsv"), startAtEnd: resuming),
                 "status": LineTail(binding.rootURL.appendingPathComponent("status.jsonl"), startAtEnd: resuming)]
        catalogCheckpoint = nil; catalogContext = nil
    }

    private func playHumanPreview() {
        guard let binding = humanPreview else { message = humanPreviewError ?? "The human playtest binding is unavailable."; return }
        guard let helper = Bundle.main.url(forResource: "human_preview", withExtension: "py") else {
            message = "The verified human launch helper is missing from Kokiri."; return
        }
        busy = true
        Task {
            defer { busy = false }
            do {
                let verified = try GameInstallation.inspect(binding.appURL)
                let pid = try await Task.detached(priority: .userInitiated) { try binding.launch(helper: helper) }.value
                let deadline = Date().addingTimeInterval(8)
                var application: NSRunningApplication?
                var accepted: ProcessSample?
                repeat {
                    if let sample = ProcessSample.read(pid: pid), ProcessSample.executable(pid: pid) == verified.executable.path,
                       binding.acknowledges(pid: pid, start: sample.start), let app = NSRunningApplication(processIdentifier: pid) {
                        application = app; accepted = sample; break
                    }
                    try await Task.sleep(nanoseconds: 50_000_000)
                } while Date() < deadline
                guard let application, let accepted else {
                    throw KokiriError.message("The game started, but monitoring could not verify its session. The game was left running.")
                }
                observeHumanPreview(application, installation: verified, sample: accepted, binding: binding, resuming: false)
                application.activate(options: [.activateAllWindows]); message = nil
            } catch { message = error.localizedDescription }
        }
    }

    private func tick() {
        guard let runtime else { return }
        if runtime.isTerminated {
            let endedInstallation = activeInstallation
            self.runtime = nil; activeInstallation = nil; connected = false
            if !humanPreviewRequested, let endedInstallation, let folder = sessionFolder {
                catalog.completeOwnedSession(session: folder, runtime: endedInstallation.app, checkpoint: catalogCheckpoint, referenceContext: catalogContext)
            } else if !humanPreviewRequested {
                catalog.sessionFinished()
            }
            catalogCheckpoint = nil; catalogContext = nil
            refreshShaders()
            return
        }
        guard let start = sampleStart, let folder = sessionFolder else { return }
        guard let usage = ProcessSample.read(pid: runtime.processIdentifier), usage.start == start,
              let installation = activeInstallation, ProcessSample.executable(pid: runtime.processIdentifier) == installation.executable.path else {
            self.runtime = nil; activeInstallation = nil; connected = false; message = "Session identity changed. Monitoring stopped."; return
        }
        snapshot.footprint = usage.footprint
        if Date() >= nextProcessWrite {
            let row: [String: Any] = ["utc": ISO8601DateFormatter().string(from: Date()), "pid": runtime.processIdentifier,
                                      "phys_footprint": usage.footprint, "proc_start_abstime": usage.start]
            let file = folder.appendingPathComponent("process.jsonl")
            do {
                if !FileManager.default.fileExists(atPath: file.path) { try Data().write(to: file, options: .withoutOverwriting) }
                let handle = try FileHandle(forWritingTo: file); defer { try? handle.close() }
                try handle.seekToEnd(); try handle.write(contentsOf: JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) + Data([10]))
            } catch { message = "Session memory observations could not be saved: " + error.localizedDescription }
            nextProcessWrite = Date().addingTimeInterval(2)
        }
        let timing = tails["timing"]?.read() ?? []
        for line in timing { snapshot.consumeTiming(line) }
        let presented = tails["presented"]?.read() ?? []
        for line in presented { snapshot.consumePresented(line) }
        if !timing.isEmpty || !presented.isEmpty { timingUpdatedAt = Date(); snapshot.lastUpdate = Date() }
        for line in tails["status"]?.read() ?? [] {
            snapshot.consumeStatus(line)
            if let data = line.data(using: .utf8), let response = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if response["id"] as? String == "session", response["status"] as? String == "ready" { connected = true }
                if response["id"] as? String == locationPending { locationPending = nil; connected = true }
            }
        }
        if installation.supportsLiveStatus, Date() >= nextLocation {
            // Read-only position requests share one owner; never issue a second while one is pending.
            if locationPending == nil {
                let id = humanPreviewRequested ? "mcp-" + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased().prefix(20)
                    : "kokiri-" + UUID().uuidString.prefix(12)
                if let handle = try? FileHandle(forWritingTo: folder.appendingPathComponent("input.txt")) {
                    defer { try? handle.close() }
                    do { try handle.seekToEnd(); try handle.write(contentsOf: Data("oot-live \(id) position\n".utf8)); locationPending = id }
                    catch { message = "Live position is unavailable: " + error.localizedDescription }
                }
            }
            nextLocation = Date().addingTimeInterval(5)
        }
    }
    func chooseRecording() {
        guard !running else { message = "A live session is being observed. Import a recording after it closes."; return }
        if let folder = chooseFolder(title: "Open a recorded performance session", prompt: "Open Recording") { loadRecording(folder) }
    }
    func loadRecording(_ folder: URL) {
        busy = true
        Task {
            defer { busy = false }
            do {
                let result = try await Task.detached(priority: .userInitiated) { try RecordedSession.load(folder) }.value
                recording = result; snapshot = result.snapshot; selection = .performance; timingUpdatedAt = nil
            } catch { message = error.localizedDescription }
        }
    }
    func setContribution(_ choice: Bool?) {
        guard !humanPreviewRequested else { message = "This playtest keeps its records local."; return }
        Task { await catalog.choose(choice) }
    }
    func updateHUD(_ change: (inout HUDPreferences) -> Void) {
        guard supportsHUD, !anyGameRunning else { message = "Close the matching Kokiri game before changing its HUD."; return }
        var value = HUDPreferences.read(from: hudFolder); change(&value)
        do { try value.save(to: hudFolder); hud = value }
        catch { message = error.localizedDescription }
    }
    func refreshShaders() {
        catalog.selectRuntime(installation?.app)
        guard !shaderRefreshPending else { return }
        let app = installation?.app
        let cache = humanPreview?.rootURL.appendingPathComponent("cache") ?? KokiriPaths.game.appendingPathComponent("shader-cache")
        shaderRefreshPending = true
        Task {
            let result = await Task.detached(priority: .utility) {
                let folder = app?.appendingPathComponent("Contents/Resources/totk/build")
                let bundled = ShaderMetadata.counts(files: folder.map { [$0.appendingPathComponent("pso_manifest.tsv"), $0.appendingPathComponent("pso_title.tsv")] } ?? [])
                let collected = ShaderMetadata.counts(files: [cache.appendingPathComponent("pso_collected.tsv")])
                return (bundled, collected, app.flatMap { try? RuntimePreparation.load(app: $0) })
            }.value
            shaderRefreshPending = false
            guard installation?.app == app else { refreshShaders(); return }
            shaderCounts = result.0; collectedShaderCounts = result.1; preparation = result.2
        }
    }

    func refreshLibrary() { refreshShaders(); catalog.retryDownload() }

    func startBuild(game: URL, fonts: URL, work: URL, output: URL) {
        guard !humanPreviewRequested else { message = "The prepared game is already connected."; return }
        guard !busy, !building else { return }
        guard !anyGameRunning else { message = "Close the game before building."; return }
        guard let repository = preferences.repository else { message = "Choose the Kokiri source folder first."; return }
        guard !FileManager.default.fileExists(atPath: output.path) else {
            message = "Choose a new game app location. Your existing app will stay in place."; return
        }
        guard SetupInput.gameProblem(game) == nil, SetupInput.fontsProblem(fonts) == nil else {
            message = "Your input files have changed. Choose the game and fonts again."; return
        }
        guard SetupInput.isOutside(work, repository), SetupInput.isOutside(output, repository),
              SetupInput.isOutside(work, game), SetupInput.isOutside(output, game),
              SetupInput.isOutside(game, work), SetupInput.isOutside(fonts, work),
              SetupInput.isOutside(output, work), SetupInput.isOutside(work, output),
              SetupInput.isOutside(work, fonts), SetupInput.isOutside(output, fonts), SetupInput.isOutside(fonts, output) else {
            message = "Choose separate preparation and game locations outside your source and input folders."; return
        }
        var volume = work
        while !FileManager.default.fileExists(atPath: volume.path), volume.path != "/" { volume.deleteLastPathComponent() }
        if !FileManager.default.fileExists(atPath: work.appendingPathComponent("oot/extracted/oot/romfs/romfs.bin").path),
           let bytes = (try? FileManager.default.attributesOfFileSystem(forPath: volume.path)[.systemFreeSize]) as? NSNumber,
           bytes.int64Value < 40 * 1024 * 1024 * 1024 {
            message = "The preparation drive needs at least 40 GiB free for the initial import."; return
        }
        let metal = Process()
        metal.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun"); metal.arguments = ["--find", "metal"]
        metal.standardOutput = FileHandle.nullDevice; metal.standardError = FileHandle.nullDevice
        do { try metal.run(); metal.waitUntilExit() } catch { message = "Install Xcode and its Metal toolchain before preparing the game."; return }
        guard metal.terminationStatus == 0 else { message = "Install Xcode’s Metal toolchain before preparing the game."; return }
        guard !work.standardizedFileURL.path.hasPrefix(repository.standardizedFileURL.path + "/"),
              work.standardizedFileURL != repository.standardizedFileURL,
              !output.standardizedFileURL.path.hasPrefix(repository.standardizedFileURL.path + "/") else {
            message = "Keep the work folder and game app outside the source repository."; return
        }
        let candidates = ["/opt/homebrew/bin/python3.14", "/usr/local/bin/python3.14", "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14"]
        guard let python = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            message = "Python 3.14 is required to build the game. Install it, then try again."; return
        }
        let entry = repository.appendingPathComponent("engine/build.py")
        guard FileManager.default.isReadableFile(atPath: entry.path) else { message = "The selected source folder has no engine/build.py."; return }
        let process = Process(), pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-I", entry.path, game.path, "--shared-fonts", fonts.path, "--work", work.path, "-o", output.path]
        var environment = ProcessInfo.processInfo.environment
        environment["OOT_SHADERS"] = "full"
        environment["OOT_SHADER_SUBSET"] = "all"
        environment["OOT_BUNDLE_SHADERS"] = "1"
        process.environment = environment
        process.currentDirectoryURL = repository; process.standardOutput = pipe; process.standardError = pipe
        buildOutput = ""; buildStage = "Starting verified build"; buildSucceeded = false
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let bytes = handle.availableData
            if bytes.isEmpty { handle.readabilityHandler = nil; return }
            let text = String(decoding: bytes, as: UTF8.self)
            Task { @MainActor in self?.appendBuild(text) }
        }
        process.terminationHandler = { [weak self] finished in
            Task { @MainActor in
                guard let self else { return }
                self.building = false; self.buildProcess = nil
                self.buildSucceeded = false
                if finished.terminationStatus == 0 {
                    do {
                        self.preferences = try InstallationConnection.connect(output, preferences: self.preferences, savingTo: self.preferenceFile)
                        self.installationUnavailable = false; self.setupReady = true; self.refreshShaders(); self.buildSucceeded = true; self.buildStage = "Game built and connected"
                    } catch { self.buildStage = "Build ended; app verification failed"; self.message = error.localizedDescription }
                } else { self.buildStage = "Build stopped (exit \(finished.terminationStatus))" }
            }
        }
        do { try process.run(); buildProcess = process; building = true }
        catch { pipe.fileHandleForReading.readabilityHandler = nil; message = error.localizedDescription }
    }
    private func appendBuild(_ text: String) {
        buildOutput += text
        if buildOutput.count > 100_000 { buildOutput = String(buildOutput.suffix(100_000)) }
        let stages = ["import-original", "verify-original", "rewrite-", "native-runtime", "prepare-shader-seed", "compile-shader-libraries", "Preparing", "Built "]
        for line in text.split(separator: "\n") where stages.contains(where: { line.contains($0) }) { buildStage = String(line.prefix(160)) }
    }
}
