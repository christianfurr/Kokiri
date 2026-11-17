import SwiftUI
import KokiriCore

struct MainView: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 11) {
                    KokiriMark()
                    VStack(alignment: .leading, spacing: 3) {
                        Text("KOKIRI").font(.system(size: 17, weight: .semibold)).tracking(3)
                        Text("Ocarina of Time for Mac").font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                }.padding(.horizontal, 19).padding(.top, 20).padding(.bottom, 28)
                List(Destination.allCases, selection: $model.selection) { item in
                    Label(item.rawValue, systemImage: item.symbol).tag(item).padding(.vertical, 5)
                }.listStyle(.sidebar).scrollContentBackground(.hidden)
                VStack(alignment: .leading, spacing: 7) {
                    Divider().padding(.bottom, 10)
                    Label(model.running ? "Game running" : "Your library, on this Mac", systemImage: model.running ? "play.circle" : "desktopcomputer")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    Text("KOKIRI \(ProductIdentity.version) · PREVIEW").font(.system(size: 8, weight: .medium)).tracking(1.4).foregroundStyle(Palette.moss)
                }.padding(18)
            }.background(Palette.paper)
            .navigationSplitViewColumnWidth(min: 200, ideal: 216, max: 250)
        } detail: {
            VStack(spacing: 0) {
                if let message = model.message {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "info.circle")
                        Text(message).font(.system(size: 12)).textSelection(.enabled)
                        Spacer()
                        Button { model.message = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain).accessibilityLabel("Dismiss message")
                    }.padding(14).background(Palette.brass.opacity(0.10))
                }
                Group {
                    switch model.selection ?? .home {
                    case .home: HomeView()
                    case .setup: SetupView()
                    case .performance: PerformanceView()
                    case .shaders: ShaderLibraryView()
                    case .settings: SettingsView()
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }.background(Palette.paper.opacity(0.55))
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(action: model.play) { Label(model.running ? "Return to Game" : "Play", systemImage: "play.fill") }
                    .disabled(model.busy || model.building || (model.installation == nil && !model.running))
            }
        }
        .preferredColorScheme(.light)
    }
}

struct HomeView: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack {
                    Eyebrow(text: "Your game")
                    Spacer()
                    StatusPill(text: model.stateTitle, symbol: model.running ? "circle.fill" : "checkmark.seal")
                }
                hero
                HStack(spacing: 14) {
                    MetricCard(label: "Prepared shader libraries", value: model.preparation.map { $0.libraries.formatted() } ?? "—", unit: "", detail: "Compiled for the connected build")
                    MetricCard(label: "Prepared pipelines", value: model.preparation.map { $0.pipelines.formatted() } ?? "—", unit: "", detail: model.preparation.map { "Includes \($0.meshPipelines.formatted()) mesh pipelines" } ?? "Connect a prepared game")
                    MetricCard(label: "Collected locally", value: model.shaderRefreshPending ? "—" : model.collectedRecipeCount.formatted(), unit: "", detail: "Recipes saved while you play")
                }
                HStack(alignment: .top, spacing: 18) {
                    Surface {
                        VStack(alignment: .leading, spacing: 14) {
                            Label("Your saves", systemImage: "externaldrive").font(.system(size: 14, weight: .semibold))
                            Text("Play continues with the connected profile. Your original saves stay in place.")
                                .font(.system(size: 12)).foregroundStyle(.secondary)
                            HStack {
                                Button("Show Saves") { model.reveal(model.profileFolder) }
                                if model.canImportProfile { Button("Import Profile…", action: model.importProfile) }
                            }
                        }
                    }
                    Surface {
                        VStack(alignment: .leading, spacing: 14) {
                            Label(model.running ? "Live session" : "Session observations", systemImage: "waveform.path.ecg").font(.system(size: 14, weight: .semibold))
                            Text(model.running ? "Frame timing and memory observations are available while you play." : model.sessionFolder != nil ? "Your last session is available in Performance." : "Frame timing and memory observations appear after you play.")
                                .font(.system(size: 12)).foregroundStyle(.secondary)
                            Button("Open Performance") { model.selection = .performance }
                        }
                    }
                }
                Surface {
                    HStack(spacing: 14) {
                        Image(systemName: "square.stack.3d.up").font(.system(size: 25, weight: .light)).foregroundStyle(Palette.brass)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Shader Library").font(.system(size: 13, weight: .semibold))
                            Text(model.catalog.reviewedRecords.map { "\($0.formatted()) verified shared recipes · your local preparation is ready to play" } ?? "Local preparation, collected recipes and the public catalog in one place.")
                                .font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Open Library") { model.selection = .shaders }
                    }
                }
                Text("Built on the credited MacNativeGames native runtime. Game files stay on your Mac.")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }.padding(32).frame(maxWidth: 1140)
        }
    }
    private var hero: some View {
        VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .bottomLeading) {
                ForestScene().frame(height: 190)
                LinearGradient(colors: [.clear, Palette.forest.opacity(0.75)], startPoint: .top, endPoint: .bottom)
                VStack(alignment: .leading, spacing: 9) {
                    Text("THE LEGEND OF ZELDA").font(.system(size: 10, weight: .medium)).tracking(2.8)
                    Text("Ocarina of Time").font(.system(size: 40, weight: .medium, design: .serif))
                    Text("Native on your Mac.").font(.system(size: 12)).foregroundStyle(.white.opacity(0.78))
                }.foregroundStyle(.white).padding(30)
            }
            HStack(spacing: 20) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(model.installation == nil ? "Begin with your own game files" : "Ready to play")
                        .font(.system(size: 15, weight: .semibold))
                    Text(model.installation.map { "Connected · \($0.app.lastPathComponent)" }
                         ?? "Connect an existing app, or build one from your verified dump.")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: { if model.installation == nil { model.selection = .setup } else { model.play() } }) {
                    Label(model.installation == nil ? "Set Up Game" : model.running ? "Return to Game" : "Play Game", systemImage: model.installation == nil ? "arrow.right" : "play.fill")
                        .font(.system(size: 13, weight: .semibold)).padding(.horizontal, 16).padding(.vertical, 9)
                }.buttonStyle(.borderedProminent).disabled(model.busy || model.building)
            }.padding(24).background(.background)
        }.clipShape(RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(Palette.line, lineWidth: 1))
    }
}
