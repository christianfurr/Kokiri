import AppKit
import SwiftUI
import UniformTypeIdentifiers
import KokiriCore

struct SetupView: View {
    @EnvironmentObject private var model: AppModel
    @State private var game: URL?
    @State private var fonts: URL?
    @State private var work: URL?
    @State private var output: URL?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                PageHeading(eyebrow: "A place to begin", title: "Bring your game to Kokiri", detail: "Use your own Ocarina of Time files, update 131072. Your game and build output stay outside the source repository.")
                Surface {
                    HStack(alignment: .top, spacing: 18) {
                        Image(systemName: "app.dashed").font(.system(size: 32, weight: .light)).foregroundStyle(Palette.moss)
                        VStack(alignment: .leading, spacing: 7) {
                            Text("Already have a native game app?").font(.system(size: 16, weight: .semibold))
                            Text(model.installation?.app.lastPathComponent ?? "Connect a built Kokiri Game app, or a compatible MacNativeGames app.")
                                .font(.system(size: 12)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Connect App…", action: model.chooseInstallation).disabled(model.running)
                    }
                }
                Surface {
                    VStack(alignment: .leading, spacing: 18) {
                        HStack {
                            VStack(alignment: .leading, spacing: 5) {
                                Text("Build from your own files").font(.system(size: 18, weight: .semibold, design: .serif))
                                Text("Completed steps are reused when you run the same build again.").font(.system(size: 11)).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if model.building { ProgressView().controlSize(.small) }
                        }
                        Divider()
                        pathRow("Kokiri source", value: model.preferences.repository) { model.chooseRepository() }
                        pathRow("Game dump", value: game) { game = chooseGame() }
                        pathRow("Verified fonts", value: fonts) { fonts = model.chooseFolder(title: "Choose the verified shared-fonts folder", prompt: "Use Fonts") }
                        pathRow("Build workspace", value: work) { work = model.chooseFolder(title: "Choose an external build workspace", prompt: "Use Workspace") }
                        pathRow("Game app", value: output) { output = chooseOutput() }
                        Divider()
                        HStack {
                            Text("Requires Python 3.14, Xcode and the Metal toolchain.")
                                .font(.system(size: 10)).foregroundStyle(.secondary)
                            Spacer()
                            Button(model.building ? "Building…" : "Build Game") {
                                if let game, let fonts, let work, let output { model.startBuild(game: game, fonts: fonts, work: work, output: output) }
                            }.buttonStyle(.borderedProminent)
                                .disabled(model.busy || model.building || model.anyGameRunning || game == nil || fonts == nil || work == nil || output == nil || model.preferences.repository == nil)
                        }
                        if model.building || !model.buildOutput.isEmpty {
                            Text(model.buildStage).font(.system(size: 12, weight: .medium)).textSelection(.enabled)
                            ScrollView {
                                Text(model.buildOutput).font(.system(size: 10, design: .monospaced)).textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading).padding(12)
                            }.frame(height: 160).background(Palette.paper, in: RoundedRectangle(cornerRadius: 8))
                            if !model.building && !model.buildSucceeded {
                                Text("The existing app and profile are preserved. Review the error above, then retry the same paths.")
                                    .font(.system(size: 11)).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }.padding(32)
        }
    }
    private func pathRow(_ title: String, value: URL?, action: @escaping () -> Void) -> some View {
        HStack {
            Text(title).font(.system(size: 12, weight: .medium)).frame(width: 120, alignment: .leading)
            Text(value?.path ?? "Not selected").font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle).help(value?.path ?? title)
            Spacer()
            Button("Choose…", action: action).disabled(model.building)
        }
    }
    private func chooseGame() -> URL? {
        let panel = NSOpenPanel(); panel.title = "Choose your own game dump"; panel.prompt = "Use Game"
        panel.canChooseDirectories = true; panel.canChooseFiles = true
        return panel.runModal() == .OK ? panel.url : nil
    }
    private func chooseOutput() -> URL? {
        let panel = NSSavePanel(); panel.title = "Where should the built game live?"; panel.nameFieldStringValue = "Kokiri Game.app"
        panel.canCreateDirectories = true
        return panel.runModal() == .OK ? panel.url : nil
    }
}
