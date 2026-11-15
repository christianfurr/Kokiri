import AppKit
import Combine
import Foundation
import KokiriCore
import UniformTypeIdentifiers
import CryptoKit

enum Destination: String, CaseIterable, Identifiable {
    case home = "Home", setup = "Setup", performance = "Performance", shaders = "Shader Library", settings = "Settings"
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .home: "leaf"
        case .setup: "shippingbox"
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
    @Published var buildOutput = ""
    @Published var buildStage = "Not started"
    @Published var building = false
    @Published var buildSucceeded = false
    @Published var hud = HUDPreferences.read(from: KokiriPaths.game)
    let updates = UpdateService()
    let catalog = CatalogFacade()

    private let preferenceFile = KokiriPaths.support.appendingPathComponent("launcher.json")
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
        preferences = LauncherPreferences.load(from: preferenceFile)
        catalogObservation = catalog.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
        refreshInstallation()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        let arguments = ProcessInfo.processInfo.arguments
        if let at = arguments.firstIndex(of: "--recording"), arguments.indices.contains(at + 1) {
            loadRecording(URL(fileURLWithPath: arguments[at + 1]))
        }
        if let at = arguments.firstIndex(of: "--page"), arguments.indices.contains(at + 1),
           let page = Destination.allCases.first(where: { $0.rawValue.caseInsensitiveCompare(arguments[at + 1]) == .orderedSame }) {
            selection = page
        }
    }

    var running: Bool { runtime?.isTerminated == false }
    var anyGameRunning: Bool {
        ["com.christianfurr.kokiri.runtime", "org.macnativegames.oot"].contains {
            !NSRunningApplication.runningApplications(withBundleIdentifier: $0).isEmpty
        }
    }
    var installation: GameInstallation? { preferences.installation }
    var supportsHUD: Bool { installation.flatMap { Bundle(url: $0.app)?.object(forInfoDictionaryKey: "KokiriHUDPreferencesVersion") as? Int } == 1 }
    var stateTitle: String {
        if running, activeInstallation?.supportsLiveStatus != true { return "Game running" }
        if running { return connected ? "Session connected" : "Starting game" }
        if anyGameRunning { return "Another game session is open" }
        return installation == nil ? "Set up your game" : "Ready to launch"
    }
    var isStale: Bool { !running || timingUpdatedAt.map { Date().timeIntervalSince($0) > 5 } ?? true }

    func savePreferences() {
        do { try preferences.save(to: preferenceFile) } catch { message = error.localizedDescription }
    }
    func refreshInstallation() {
        if let selected = preferences.installation {
            do { preferences.installation = try GameInstallation.inspect(selected.app) }
            catch { preferences.installation = nil; message = error.localizedDescription }
        }
        refreshShaders()
    }
    func chooseInstallation() {
        let panel = NSOpenPanel(); panel.title = "Connect your game"; panel.prompt = "Connect Game"
        panel.allowedContentTypes = [.applicationBundle]; panel.canChooseDirectories = false
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications")
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            preferences.installation = try GameInstallation.inspect(url); savePreferences(); refreshShaders()
            message = "Game connected. Kokiri uses its own player profile."
        } catch { message = error.localizedDescription }
    }
    func chooseRepository() {
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
        guard !anyGameRunning else { message = "Another game session is running. Finish it before starting Kokiri’s profile."; return }
        guard let selected = installation else { selection = .setup; return }
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

    private func tick() {
        guard let runtime else { return }
        if runtime.isTerminated {
            let endedInstallation = activeInstallation
            self.runtime = nil; activeInstallation = nil; connected = false
            if let endedInstallation, let folder = sessionFolder {
                catalog.completeOwnedSession(session: folder, runtime: endedInstallation.app, checkpoint: catalogCheckpoint, referenceContext: catalogContext)
            } else {
                catalog.sessionFinished()
            }
            catalogCheckpoint = nil; catalogContext = nil
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
                let id = "kokiri-" + UUID().uuidString.prefix(12)
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
        Task { await catalog.choose(choice) }
    }
    func updateHUD(_ change: (inout HUDPreferences) -> Void) {
        guard supportsHUD, !anyGameRunning else { message = "Close the matching Kokiri game before changing its HUD."; return }
        var value = HUDPreferences.read(from: KokiriPaths.game); change(&value)
        do { try value.save(to: KokiriPaths.game); hud = value }
        catch { message = error.localizedDescription }
    }
    func refreshShaders() {
        catalog.selectRuntime(installation?.app)
        var counts: [String: Int] = [:]
        var seen = Set<String>()
        if let installation {
            let folder = installation.app.appendingPathComponent("Contents/Resources/totk/build")
            for name in ["pso_manifest.tsv", "pso_title.tsv"] {
                let url = folder.appendingPathComponent(name)
                guard let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize, size <= 16 << 20,
                      let text = try? String(contentsOf: url, encoding: .utf8) else { continue }
                for line in text.split(separator: "\n") where !line.hasPrefix("#") {
                    guard let kind = line.split(separator: "\t").first, ["S","C","R","T","M","V","A"].contains(String(kind)),
                          seen.insert(String(line)).inserted else { continue }
                    counts[String(kind), default: 0] += 1
                }
            }
        }
        shaderCounts = counts
    }

    func startBuild(game: URL, fonts: URL, work: URL, output: URL) {
        guard !busy, !building else { return }
        guard !anyGameRunning else { message = "Close the game before building."; return }
        guard let repository = preferences.repository else { message = "Choose the Kokiri source folder first."; return }
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
                self.buildSucceeded = finished.terminationStatus == 0
                if finished.terminationStatus == 0 {
                    do {
                        self.preferences.installation = try GameInstallation.inspect(output)
                        self.savePreferences(); self.refreshShaders(); self.buildStage = "Game built and connected"
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
