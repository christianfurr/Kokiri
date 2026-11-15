import SwiftUI
import KokiriCore

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        Form {
            Section("Your Mac, your data") {
                LabeledContent("Player profile", value: "Kokiri / OcarinaOfTime / profile")
                Text("Kokiri uses a separate profile. Import copies the complete selected folder; it never replaces an existing Kokiri profile.").font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("Import Save Profile…", action: model.importProfile).disabled(model.busy || model.anyGameRunning)
                    Button("Show Kokiri Data") { model.reveal(KokiriPaths.support) }
                }
            }
            Section("Session observations") {
                Toggle("Record detailed frame timing", isOn: Binding(get: { model.preferences.observeSessions }, set: { model.preferences.observeSessions = $0; model.savePreferences() }))
                Text("Off by default for ordinary play. Physical memory and sampled area remain available. Detailed timing adds overhead and applies to the next launch; nothing is uploaded.").font(.caption).foregroundStyle(.secondary)
                Text("Graphics, audio and controls stay in the game’s native settings (key 1).").font(.caption).foregroundStyle(.secondary)
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
                .disabled(!model.catalog.ready || model.catalog.choicePending)
                Text("Pipeline identifiers and render-state metadata only. No game code, shader source, saves, logs or personal paths.").font(.caption).foregroundStyle(.secondary)
                Text(model.catalog.status).font(.caption).foregroundStyle(.secondary)
                if let queued = model.catalog.queued { LabeledContent("Queued metadata records", value: queued.formatted()) }
            }
            Section("Kokiri launcher updates") { UpdateSettings(service: model.updates) }
            Section("Game runtime updates") {
                LabeledContent("Availability", value: "Not configured")
                Text("Runtime update setup is not available in this build. Launcher updates leave your connected game app, profile and shader caches in place.")
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

struct ShaderLibraryView: View {
    @EnvironmentObject private var model: AppModel
    private let kinds = [("M", "Mesh pipelines", "Task and mesh render states"), ("R", "Render pipelines", "Recorded graphics states"),
                         ("C", "Compute pipelines", "Recorded compute states"), ("S", "Shader variants", "Referenced translation variants")]
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                PageHeading(eyebrow: "Prepared for the next visit", title: "The shader library", detail: "Pipeline metadata records the states a game uses. It helps compatible builds prepare known work before play.")
                Surface {
                    VStack(alignment: .leading, spacing: 15) {
                        HStack {
                            Text("This game’s bundled lists").font(.system(size: 15, weight: .semibold))
                            Spacer(); Button("Refresh", action: model.refreshShaders)
                        }
                        if model.shaderCounts.isEmpty {
                            ContentUnavailableView("No library connected", systemImage: "square.stack.3d.up", description: Text("Connect a built game app to inspect its bundled metadata lists.")).frame(height: 130)
                        } else {
                            ForEach(kinds, id: \.0) { kind in
                                HStack {
                                    Image(systemName: "square.stack").foregroundStyle(Palette.moss).frame(width: 28)
                                    VStack(alignment: .leading, spacing: 3) { Text(kind.1).font(.system(size: 12, weight: .medium)); Text(kind.2).font(.system(size: 10)).foregroundStyle(.secondary) }
                                    Spacer()
                                    Text(model.shaderCounts[kind.0, default: 0].formatted()).font(.system(size: 20, design: .rounded)).monospacedDigit()
                                }.padding(.vertical, 6)
                            }
                            Text("Counts are list entries, not retained GPU objects or a promise of complete area coverage.").font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                    }
                }
                Surface {
                    VStack(alignment: .leading, spacing: 15) {
                        HStack { Image(systemName: "leaf.arrow.triangle.circlepath").font(.system(size: 26, weight: .light)).foregroundStyle(Palette.brass)
                            Text("Help the library grow").font(.system(size: 20, weight: .medium, design: .serif)) }
                        Text("After you choose sharing, a configured catalog adapter can automatically queue reviewed pipeline metadata. Downloads must match the game, shader chain, compiler and target exactly.")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                        if model.catalog.consent == nil {
                            HStack {
                                Button("Allow Automatic Contributions") { model.setContribution(true) }.buttonStyle(.borderedProminent)
                                Button("Keep My Records Local") { model.setContribution(false) }
                            }.disabled(!model.catalog.ready || model.catalog.choicePending)
                        } else {
                            StatusPill(text: model.catalog.consent == true ? "Sharing preference saved" : "Records stay local", symbol: "checkmark")
                        }
                        Text(model.catalog.status).font(.system(size: 11)).foregroundStyle(.secondary)
                        Divider()
                        Text("Verified downloads").font(.system(size: 12, weight: .semibold))
                        Text(model.catalog.downloadStatus).font(.system(size: 11)).foregroundStyle(.secondary)
                        if let index = model.catalog.verifiedIndex {
                            Button("Show Verified Metadata") { model.reveal(index) }
                        }
                        if let queued = model.catalog.queued, let reviewed = model.catalog.reviewedRecords {
                            HStack { StatusPill(text: "\(queued) queued", symbol: "tray"); StatusPill(text: "\(reviewed) verified records", symbol: "checkmark.shield") }
                        }
                        Text("No game files or shader source are uploaded. There is no account.").font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                }
            }.padding(32)
        }
    }
}
