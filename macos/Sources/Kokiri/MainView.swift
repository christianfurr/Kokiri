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
                    case .mods: ModsView(model: model.mods).disabled(model.busy || model.building)
                    case .saves: SavesView(profileFolder: model.profileFolder)
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
                    .disabled(model.busy || model.building || model.mods.busy || (model.installation == nil && !model.running))
            }
        }
        .sheet(isPresented: $model.setupPresented) {
            SetupView().environmentObject(model).frame(width: 600, height: 620)
                .interactiveDismissDisabled(model.building)
        }
        .preferredColorScheme(.light)
    }
}
