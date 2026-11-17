import SwiftUI
import KokiriCore

struct HomeView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                game
                session
                Divider()
                saves
                Text("Built on the credited MacNativeGames native runtime.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(32)
            .frame(maxWidth: 980, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    private var game: some View {
        VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .bottomLeading) {
                ForestScene().frame(height: 220)
                LinearGradient(colors: [.clear, Palette.forest.opacity(0.8)], startPoint: .top, endPoint: .bottom)
                VStack(alignment: .leading, spacing: 6) {
                    Text("The Legend of Zelda").font(.callout)
                    Text("Ocarina of Time").font(.system(size: 36, weight: .semibold))
                }
                .foregroundStyle(.white)
                .padding(28)
            }
            VStack(alignment: .leading, spacing: 16) {
                if model.installationUnavailable {
                    Label("Your game is unavailable", systemImage: "externaldrive.badge.exclamationmark")
                        .font(.headline)
                    Text("Reconnect its drive or locate a compatible app. Your game connection and saves are kept in place.")
                        .foregroundStyle(.secondary)
                    HStack {
                        Button("Locate Game…", action: model.chooseInstallation)
                            .buttonStyle(.borderedProminent)
                        Button("Try Again", action: model.refreshInstallation)
                    }.disabled(!model.canManageGame)
                } else {
                    HStack(alignment: .center, spacing: 20) {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(model.running ? "Game running" : model.installation == nil ? "Add your game to get started" : "Ready to play")
                                .font(.headline)
                            if let installation = model.installation {
                                Text(installation.app.lastPathComponent)
                                    .font(.callout).foregroundStyle(.secondary)
                            } else {
                                Text("Connect a native game app or prepare your own game files.")
                                    .font(.callout).foregroundStyle(.secondary)
                            }
                        }
                        Spacer(minLength: 12)
                        Button(action: playOrSetUp) {
                            Label(model.running ? "Return to Game" : model.installation == nil ? "Add Game…" : "Play", systemImage: model.installation == nil ? "plus" : "play.fill")
                                .font(.headline).padding(.horizontal, 18).padding(.vertical, 9)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.busy || model.building || (!model.running && model.anyGameRunning))
                    }
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.background)
        }
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Palette.line, lineWidth: 1))
    }

    private var session: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "waveform.path.ecg")
                .font(.title3).foregroundStyle(Palette.moss).frame(width: 26)
            VStack(alignment: .leading, spacing: 5) {
                Text(model.running ? "Current session" : "Last session").font(.headline)
                if let date = model.snapshot.lastUpdate {
                    Text(date.formatted(date: .abbreviated, time: .shortened))
                        .font(.callout).foregroundStyle(.secondary)
                    if let area = model.snapshot.area, !area.isEmpty {
                        Text(area).font(.callout).foregroundStyle(.secondary)
                    }
                } else {
                    Text(model.running ? "Session observations are available in Performance." : "Your session observations will appear here after you play.")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 12)
            Button("View Performance") { model.selection = .performance }
        }
    }

    private var saves: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "externaldrive")
                .font(.title3).foregroundStyle(Palette.moss).frame(width: 26)
            VStack(alignment: .leading, spacing: 5) {
                Text("Saves").font(.headline)
                Text("Your progress stays on this Mac. Import copies an existing profile.")
                    .font(.callout).foregroundStyle(.secondary)
                HStack {
                    Button("Show Saves") { model.reveal(model.profileFolder) }
                    if !model.isPlaytest {
                        Button("Import Profile…", action: model.importProfile).disabled(!model.canImportProfile)
                    }
                }.padding(.top, 5)
            }
            Spacer(minLength: 0)
        }
    }

    private func playOrSetUp() {
        if model.installation == nil { model.beginSetup() }
        else { model.play() }
    }
}
