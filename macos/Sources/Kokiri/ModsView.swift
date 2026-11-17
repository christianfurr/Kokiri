import SwiftUI
import KokiriCore

struct ModsView: View {
    @ObservedObject var model: ModsModel
    @State private var profileAction: String?
    @State private var profileName = ""
    @State private var showProfileSheet = false
    @State private var confirmDelete = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                PageHeading(eyebrow: "Your library", title: "Mods", detail: "Build a loadout for each way you play. Mod profiles share your game save and apply when you start a new session.")
                actions
                if let message = model.message {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: model.failed ? "exclamationmark.triangle" : "info.circle")
                        Text(message).font(.system(size: 12)).textSelection(.enabled)
                        Spacer()
                        Button(action: model.dismissMessage) { Image(systemName: "xmark") }.buttonStyle(.plain).accessibilityLabel("Dismiss mod message")
                    }.padding(14).background(Palette.brass.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
                }
                profileControls
                if let blocker = model.launchBlocker {
                    Label(blocker, systemImage: "info.circle").font(.system(size: 12)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if model.gameRunning {
                    Label("Game running. Your changes are saved for the next launch.", systemImage: "play.circle")
                        .font(.system(size: 12)).foregroundStyle(Palette.forest)
                }
                if model.selectedPacks.isEmpty { emptyLibrary }
                else {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("Load order").font(.system(size: 15, weight: .semibold))
                            Spacer()
                            Text("Later mods take priority").font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                        ForEach(Array(model.selectedPacks.enumerated()), id: \.element.id) { index, pack in
                            packRow(pack, index: index)
                        }
                    }
                }
                Text("Supports RomFS mod folders for Ocarina of Time. MacNative Mods imports are separate copies. Code patches, cheats and archive imports are not supported in this tab.")
                    .font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }.padding(32).frame(maxWidth: 1140, alignment: .leading)
        }
        .task { model.refresh() }
        .sheet(isPresented: $showProfileSheet) { profileSheet }
        .confirmationDialog("Delete \(model.selected.name)?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete Profile", role: .destructive, action: model.delete)
            Button("Cancel", role: .cancel) {}
        } message: { Text("The mod files and your game save stay in place.") }
    }

    private var actions: some View {
        HStack(spacing: 12) {
            Button(action: model.importFolder) { Label("Import Mod Folder…", systemImage: "plus") }
                .buttonStyle(.borderedProminent)
            Menu("Import from MacNative Mods") {
                Button("Copy Ocarina of Time Library…", action: model.importMacNative).disabled(!model.macNativeAvailable)
                if !model.macNativeAvailable { Text("No local Ocarina of Time library found") }
            }
            Spacer(minLength: 8)
            if model.busy { ProgressView().controlSize(.small).accessibilityLabel("Updating mod library") }
            Button(action: model.refresh) { Image(systemName: "arrow.clockwise") }.help("Refresh mod library").accessibilityLabel("Refresh mod library")
            Button("Show Library", action: model.revealLibrary)
        }.disabled(model.busy)
    }

    private var profileControls: some View {
        Surface {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Mod profile").font(.system(size: 14, weight: .semibold))
                        Text("Selected for next launch · \(model.enabledCount) enabled")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    Spacer()
                    StatusPill(text: model.launchBlocker == nil ? "Next launch" : "Library only", symbol: "square.stack")
                }
                HStack(spacing: 12) {
                    Picker("Profile", selection: Binding(get: { model.state.selectedProfile }, set: model.select)) {
                        ForEach(model.state.profiles) { profile in Text(profile.name).tag(profile.id) }
                    }.labelsHidden().frame(maxWidth: 320)
                    Menu("Manage Profiles") {
                        Button("New Profile…") { editProfile("New Profile") }
                        Button("Duplicate Profile…") { editProfile("Duplicate Profile") }
                        Button("Rename Profile…") { editProfile("Rename Profile") }
                        Divider()
                        Button("Delete Profile…", role: .destructive) { confirmDelete = true }.disabled(model.state.profiles.count < 2)
                    }
                    Spacer(minLength: 0)
                }
            }.disabled(model.busy)
        }
    }

    private var emptyLibrary: some View {
        Surface {
            VStack(alignment: .leading, spacing: 14) {
                Image(systemName: "shippingbox").font(.system(size: 28, weight: .light)).foregroundStyle(Palette.moss)
                Text("Add your first mod").font(.system(size: 18, weight: .medium))
                Text("Import a folder containing romfs, or copy your existing Ocarina of Time library from MacNative Mods.")
                    .font(.system(size: 13)).foregroundStyle(.secondary)
                Text("New imports start disabled. Enable mods in a profile when you’re ready.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }.padding(.vertical, 15)
        }
    }

    private func packRow(_ pack: ModPack, index: Int) -> some View {
        let shared = model.conflicts.filter { $0.value.contains(pack.id) }
        return Surface {
            HStack(alignment: .top, spacing: 14) {
                Toggle("Enable \(pack.name)", isOn: Binding(get: { model.selected.enabled.contains(pack.id) }, set: { model.toggle(pack, enabled: $0) }))
                    .labelsHidden().toggleStyle(.switch).controlSize(.small).padding(.top, 2)
                VStack(alignment: .leading, spacing: 7) {
                    Text(pack.name).font(.system(size: 14, weight: .semibold))
                    Text(pack.detail).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(3)
                    Text("\(pack.files.formatted()) files · \(ByteCountFormatter.string(fromByteCount: Int64(pack.bytes), countStyle: .file))")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                    if !shared.isEmpty {
                        Label("\(shared.count) shared paths · later mods supply those files", systemImage: "square.2.layers.3d")
                            .font(.system(size: 10)).foregroundStyle(Palette.brass)
                            .help(shared.keys.sorted().prefix(8).joined(separator: "\n"))
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
                VStack(spacing: 7) {
                    Button { model.move(pack, by: -1) } label: { Image(systemName: "chevron.up") }
                        .disabled(index == 0).accessibilityLabel("Move \(pack.name) earlier")
                    Button { model.move(pack, by: 1) } label: { Image(systemName: "chevron.down") }
                        .disabled(index == model.selectedPacks.count - 1).accessibilityLabel("Move \(pack.name) later")
                }.buttonStyle(.borderless)
            }.disabled(model.busy)
        }
    }

    private func editProfile(_ action: String) {
        profileAction = action
        profileName = action == "Rename Profile" ? model.selected.name : action == "Duplicate Profile" ? model.selected.name + " Copy" : ""
        showProfileSheet = true
    }

    private var profileSheet: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(profileAction ?? "Mod Profile").font(.title2)
            TextField("Profile name", text: $profileName).textFieldStyle(.roundedBorder)
                .onSubmit { submitProfile() }
            Text(profileAction == "New Profile" ? "A new profile starts with every mod disabled." : "Profiles keep their own mod selection and load order.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Cancel") { showProfileSheet = false }.keyboardShortcut(.cancelAction)
                Button("Save", action: submitProfile).keyboardShortcut(.defaultAction)
                    .disabled(profileName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.busy)
            }
        }.padding(24).frame(width: 380)
    }

    private func submitProfile() {
        guard !profileName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !model.busy else { return }
        if profileAction == "Rename Profile" { model.rename(profileName) }
        else { model.create(profileName, duplicate: profileAction == "Duplicate Profile") }
        showProfileSheet = false
    }
}
