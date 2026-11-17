import AppKit
import SwiftUI
import KokiriCore

struct SetupView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showHelp = false
    @State private var showDetails = false
    private var ready: Bool { model.setupReady }
    private var step: Int { model.setupStep }
    private var title: String {
        if ready { return "Your game is ready" }
        return ["Add your game", "Choose your game", "Add firmware fonts", "Prepare your game"][max(0, min(step + 1, 3))]
    }
    private var canContinue: Bool {
        if step == 0 { return model.setupGame != nil && model.setupGameProblem == nil }
        return model.setupFonts != nil && model.setupFontsProblem == nil
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                KokiriMark().frame(width: 38, height: 38)
                Spacer()
                if !ready && step >= 0 { Text("\(step + 1) of 3").font(.callout).foregroundStyle(.secondary) }
            }.padding(.bottom, 28)
            Text(title).font(.system(size: 28, weight: .semibold)).padding(.bottom, 10)
            Text(subtitle).font(.body).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                .padding(.bottom, 24)
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let message = model.message {
                        Label(message, systemImage: "exclamationmark.circle").foregroundStyle(.red).textSelection(.enabled)
                    }
                    if ready { readyContent }
                    else if step == -1 { welcomeContent }
                    else if step == 0 { gameContent }
                    else if step == 1 { fontsContent }
                    else { preparationContent }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer(minLength: 16)
            Divider().padding(.bottom, 16)
            HStack {
                if !model.building {
                    Button(model.onboarding ? "Set Up Later" : "Cancel", action: model.finishSetup)
                        .keyboardShortcut(.cancelAction)
                }
                Spacer()
                if ready {
                    Button("Open Kokiri", action: model.finishSetup).buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                } else if step == -1 {
                    Button("Add Game") { model.setupStep = 0 }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                } else {
                    Button("Back") { model.setupStep -= 1; model.message = nil }.disabled(model.building)
                    if step < 2 {
                        Button("Continue") { advance() }.buttonStyle(.borderedProminent)
                            .keyboardShortcut(.defaultAction).disabled(!canContinue)
                    } else {
                        Button(model.building ? "Preparing…" : "Prepare Game") { prepare() }
                            .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                            .disabled(!model.canManageGame || model.preferences.repository == nil)
                    }
                }
            }
        }.padding(32).background(Palette.paper.opacity(0.45))
            .onChange(of: model.setupStep) { _, _ in showHelp = false }
    }

    private var subtitle: String {
        if ready { return "Your game is connected to Kokiri. You can bring an existing save with you before you play." }
        switch step {
        case 0: return "Select your own Ocarina of Time files for Nintendo Switch 2."
        case 1: return "Choose the shared fonts extracted from your own firmware."
        case 2: return model.building ? "Keep Kokiri open while it prepares your game. Completed work is saved for reuse." : "Kokiri will verify your files and prepare the game on this Mac."
        default: return "Connect your copy of Ocarina of Time to get started."
        }
    }
    private var welcomeContent: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("You’ll need your game files and extracted firmware fonts. They stay on your Mac.")
            Button("Connect Existing App…", action: model.chooseInstallation).disabled(!model.canManageGame)
            Text("Already prepared a native game app? Connect it to skip preparation.").font(.callout).foregroundStyle(.secondary)
        }
    }
    private var gameContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            fileSelection(model.setupGame, symbol: "doc.zipper", empty: "No game selected", action: chooseGame)
            feedback(model.setupGameProblem, selected: model.setupGame != nil)
            DisclosureGroup("Which game files work?", isExpanded: $showHelp) {
                Text("Use a complete .nup package or an extracted Switch 2 dump with update 131072. The dump root must contain updates/131072/romfs and executable files. N64/3DS ROMs, NSP/XCI files and update-only patches aren’t supported. You can also select an existing compatible native .app.")
                    .font(.callout).foregroundStyle(.secondary).padding(.top, 8)
            }
        }
    }
    private var fontsContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            fileSelection(model.setupFonts, symbol: "textformat", empty: "No fonts selected") {
                if let url = model.chooseFolder(title: "Choose extracted shared-fonts", prompt: "Use Fonts") {
                    model.setupFonts = url; model.setupFontsProblem = SetupInput.fontsProblem(url)
                }
            }
            feedback(model.setupFontsProblem, selected: model.setupFonts != nil)
            DisclosureGroup("What should this folder contain?", isExpanded: $showHelp) {
                Text("All six .bfttf firmware font files and manifest.json. Choose the extracted shared-fonts folder, rather than a raw firmware archive or ordinary font folder. File integrity is verified during preparation.")
                    .font(.callout).foregroundStyle(.secondary).padding(.top, 8)
            }
        }
    }
    private var preparationContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            if model.building {
                HStack(spacing: 12) { ProgressView().controlSize(.small); Text(model.buildStage).textSelection(.enabled) }
            } else {
                LabeledContent("Game", value: model.setupGame?.lastPathComponent ?? "Choose game files")
                LabeledContent("Fonts", value: model.setupFonts?.lastPathComponent ?? "Choose firmware fonts")
                Text("Source preview requirements: Xcode with the Metal toolchain, Python 3.14 and internet access. The initial import needs at least 40 GiB free; full preparation may need more.").font(.callout).foregroundStyle(.secondary)
                if model.preferences.repository == nil {
                    Button("Choose Kokiri Source Folder…", action: model.chooseRepository)
                }
            }
            DisclosureGroup("Location and build details", isExpanded: $showDetails) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Game app: \(model.setupOutput.path)").textSelection(.enabled)
                    Button("Change Game Location…", action: chooseOutput)
                    Text("Preparation: \(model.setupWork.path)").textSelection(.enabled)
                    Button("Change Preparation Folder…") {
                        if let url = model.chooseFolder(title: "Choose preparation folder", prompt: "Use Folder") { model.setupWork = url }
                    }
                    Text("Source: \(model.preferences.repository?.path ?? "Not selected")").textSelection(.enabled)
                    Button("Choose Source…", action: model.chooseRepository)
                }.font(.callout).padding(.top, 8)
            }.disabled(model.building)
            if !model.buildOutput.isEmpty {
                DisclosureGroup("Preparation log") {
                    ScrollView {
                        Text(model.buildOutput).font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    }.frame(height: 140)
                }
                if !model.building && !model.buildSucceeded {
                    Text("Preparation stopped. Review the log, correct the issue, then retry with the same paths to reuse completed work. Your existing game and saves stay in place.").font(.callout).foregroundStyle(.secondary)
                }
            }
            if model.anyGameRunning { Text("Close the game before preparing another app.").foregroundStyle(.secondary) }
        }
    }
    private var readyContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(model.installation?.app.lastPathComponent ?? "Game connected", systemImage: "checkmark.circle.fill").foregroundStyle(Palette.forest)
            Button("Import Existing Save…", action: model.importProfile).disabled(!model.canImportProfile)
            Text("Optional. Kokiri copies your complete profile and keeps the original in place.").font(.callout).foregroundStyle(.secondary)
        }
    }
    private func fileSelection(_ url: URL?, symbol: String, empty: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: symbol).font(.system(size: 24)).foregroundStyle(Palette.forest)
                VStack(alignment: .leading, spacing: 5) {
                    Text(url?.lastPathComponent ?? empty).font(.headline)
                    Text(url == nil ? "Choose…" : "Choose a different file or folder…").font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "folder").foregroundStyle(.secondary)
            }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
                .background(.background, in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Palette.line))
        }.buttonStyle(.plain).help(url?.path ?? empty)
    }
    @ViewBuilder private func feedback(_ problem: String?, selected: Bool) -> some View {
        if let problem { Label(problem, systemImage: "exclamationmark.circle").foregroundStyle(.red) }
        else if selected { Label("Files found. Contents will be verified during preparation.", systemImage: "checkmark").font(.callout).foregroundStyle(.secondary) }
    }
    private func chooseGame() {
        let panel = NSOpenPanel(); panel.title = "Choose game files or an existing app"; panel.prompt = "Use Game"
        panel.canChooseDirectories = true; panel.canChooseFiles = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        model.message = nil
        if url.pathExtension.lowercased() == "app" { model.connectInstallation(url); return }
        model.setupGame = url; model.setupGameProblem = SetupInput.gameProblem(url)
    }
    private func chooseOutput() {
        let panel = NSSavePanel(); panel.title = "Choose a new game app location"
        panel.nameFieldStringValue = "Kokiri Game.app"; panel.canCreateDirectories = true
        panel.directoryURL = model.setupOutput.deletingLastPathComponent()
        if panel.runModal() == .OK, let url = panel.url { model.setupOutput = url }
    }
    private func advance() {
        if step == 0, let game = model.setupGame { model.setupGameProblem = SetupInput.gameProblem(game); guard model.setupGameProblem == nil else { return } }
        if step == 1, let fonts = model.setupFonts { model.setupFontsProblem = SetupInput.fontsProblem(fonts); guard model.setupFontsProblem == nil else { return } }
        model.setupStep += 1
    }
    private func prepare() {
        guard let game = model.setupGame, let fonts = model.setupFonts else { model.setupStep = 0; return }
        model.setupGameProblem = SetupInput.gameProblem(game); model.setupFontsProblem = SetupInput.fontsProblem(fonts)
        if model.setupGameProblem != nil { model.setupStep = 0; return }
        if model.setupFontsProblem != nil { model.setupStep = 1; return }
        model.startBuild(game: game, fonts: fonts, work: model.setupWork, output: model.setupOutput)
    }
}
