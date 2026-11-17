import SwiftUI
import KokiriCore

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        Form {
            Section("Game and saves") {
                LabeledContent("Connected game", value: model.preferences.installation?.app.lastPathComponent ?? model.installation?.app.lastPathComponent ?? "Not connected")
                if model.installationUnavailable { Text("Game unavailable. Reconnect its drive or locate the app.").foregroundStyle(.secondary) }
                if !model.isPlaytest {
                    Menu("Manage Game…") {
                        Button(model.installationUnavailable ? "Locate Game…" : "Connect Another Game…", action: model.chooseInstallation)
                        Button("Prepare from Game Files…", action: model.beginSetup)
                        if let app = model.preferences.installation?.app { Button("Show in Finder") { model.reveal(app) } }
                    }.disabled(!model.canManageGame)
                }
                LabeledContent("Player profile", value: model.profileFolder.path).textSelection(.enabled)
                Text("Kokiri uses a separate profile. Import copies the complete selected folder; it never replaces an existing Kokiri profile.").font(.caption).foregroundStyle(.secondary)
                HStack {
                    if !model.isPlaytest { Button("Import Save Profile…", action: model.importProfile).disabled(!model.canImportProfile) }
                    Button("Show Saves") { model.reveal(model.profileFolder) }
                    Button("Show Game Data") { model.reveal(model.gameDataFolder) }
                }
            }
            Section("Session observations") {
                Toggle("Record detailed frame timing", isOn: Binding(get: { model.preferences.observeSessions }, set: { model.preferences.observeSessions = $0; model.savePreferences() })).disabled(model.isPlaytest)
                Text("Timing is enabled for this playtest. Ordinary builds apply this choice on the next launch. Session observations stay on your Mac.").font(.caption).foregroundStyle(.secondary)
                Text("Press 1 or L3 + R3 in the game for graphics, audio and controls.").font(.caption).foregroundStyle(.secondary)
            }
            Section("Game performance HUD") {
                Picker("Position", selection: Binding(get: { model.hud.position }, set: { value in model.updateHUD { $0.position = value } })) {
                    Text("Top right").tag("top-right"); Text("Top left").tag("top-left")
                    Text("Bottom right").tag("bottom-right"); Text("Bottom left").tag("bottom-left")
                }
                Picker("Size", selection: Binding(get: { model.hud.scale }, set: { value in model.updateHUD { $0.scale = value } })) {
                    ForEach(HUDPreferences.scales, id: \.self) { Text("\($0)%").tag($0) }
                }
                Picker("Detail", selection: Binding(get: { model.hud.detail }, set: { value in model.updateHUD { $0.detail = value } })) {
                    Text("Off").tag(0); Text("Full").tag(1); Text("FPS + playtime").tag(2)
                }
                Text(model.supportsHUD ? "Close the game to change these settings. They apply on the next launch." : "Requires a matching Kokiri runtime with HUD customization support.")
                    .font(.caption).foregroundStyle(.secondary)
            }.disabled(!model.supportsHUD || model.anyGameRunning)
            Section("Shared shader catalog") {
                Picker("Automatic contributions", selection: Binding(get: { model.catalog.consent.map { $0 ? 1 : 0 } ?? -1 }, set: { model.setContribution($0 < 0 ? nil : $0 == 1) })) {
                    Text("Choose when ready").tag(-1); Text("Keep local").tag(0); Text("Share reviewed metadata").tag(1)
                }
                .disabled(!model.catalog.allowsContributions || !model.catalog.ready || model.catalog.choicePending)
                Text("Pipeline identifiers and render-state metadata only. No game code, shader source, saves, logs or personal paths.").font(.caption).foregroundStyle(.secondary)
                Text(model.catalog.status).font(.caption).foregroundStyle(.secondary)
                if let queued = model.catalog.queued { LabeledContent("Queued metadata records", value: queued.formatted()) }
            }
            Section("App updates") { UpdateSettings(service: model.updates) }
            Section("Game updates") {
                LabeledContent("Availability", value: "Not configured")
                Text("Game updates are not configured yet. Your connected game, saves and shader caches stay in place when the app updates.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("About Kokiri") {
                Text("KOKIRI \(ProductIdentity.version) (\(ProductIdentity.build))").font(.callout.weight(.medium))
                Text("Credits: MacNativeGames and its native runtime contributors; Sparkle Project. Dependency notices ship with this app. Game update 131072 is distinct from Kokiri’s product version.").font(.caption).foregroundStyle(.secondary)
            }
        }.formStyle(.grouped).scrollContentBackground(.hidden).background(Palette.paper.opacity(0.55))
    }
}

private struct UpdateSettings: View {
    @ObservedObject var service: UpdateService
    var body: some View {
        Toggle("Check automatically", isOn: Binding(get: { service.automaticChecks }, set: { service.automaticChecks = $0 })).disabled(!service.configured)
        Toggle("Download and install signed updates automatically", isOn: Binding(get: { service.automaticDownloads }, set: { service.automaticDownloads = $0 })).disabled(!service.configured)
        Text(service.status).font(.caption).foregroundStyle(.secondary)
        Text("Automatic checks use a one-hour interval when enabled.").font(.caption).foregroundStyle(.secondary)
        Text("These updates replace the Kokiri launcher. Game apps, build workspaces, profiles and shader caches live outside its bundle.").font(.caption).foregroundStyle(.secondary)
        Button("Check for Launcher Updates…", action: service.check).disabled(!service.canCheck)
    }
}
