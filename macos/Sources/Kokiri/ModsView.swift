import SwiftUI
import KokiriCore

struct ModsView: View {
    @ObservedObject var model: ModsModel
    @State private var selectedPackID: String?
    @State private var search = ""
    @State private var filter: LibraryFilter = .all
    @State private var profileAction: String?
    @State private var profileName = ""
    @State private var showProfileSheet = false
    @State private var confirmDelete = false

    private enum LibraryFilter: String, CaseIterable {
        case all = "All Mods", enabled = "Enabled", conflicts = "Conflicts"
    }

    private var visiblePacks: [ModPack] {
        let term = search.trimmingCharacters(in: .whitespacesAndNewlines)
        return model.selectedPacks.filter { pack in
            let matchesSearch = term.isEmpty || pack.name.localizedStandardContains(term)
            let matchesFilter = filter == .all
                || (filter == .enabled && model.selected.enabled.contains(pack.id))
                || (filter == .conflicts && model.conflicts.values.contains { $0.contains(pack.id) })
            return matchesSearch && matchesFilter
        }
    }

    private var selectedPack: ModPack? {
        model.selectedPacks.first { $0.id == selectedPackID }
    }

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            if let message = model.message { feedback(message) }
            if model.selectedPacks.isEmpty {
                emptyLibrary
            } else {
                libraryTools
                HSplitView {
                    modList
                        .frame(minWidth: 340, idealWidth: 400, maxWidth: .infinity)
                    inspector
                        .frame(minWidth: 280, idealWidth: 320, maxWidth: 400, maxHeight: .infinity, alignment: .topLeading)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(.background)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.line.opacity(0.75)).allowsHitTesting(false)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 20)
            }
            footer
        }
        .tint(Palette.forest)
        .task {
            model.refresh()
            keepSelection()
        }
        .onChange(of: visiblePacks.map(\.id)) { keepSelection() }
        .sheet(isPresented: $showProfileSheet) { profileSheet }
        .confirmationDialog("Delete \(model.selected.name)?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete Profile", role: .destructive, action: model.delete)
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The mod files and your game save stay in place.")
        }
    }

    private var toolbar: some View {
        HStack(spacing: 14) {
            Text("Mods")
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(Palette.ink)
            Spacer(minLength: 12)
            if model.busy {
                ProgressView().controlSize(.small).accessibilityLabel("Updating mod library")
            }
            Picker("Mod profile", selection: Binding(get: { model.state.selectedProfile }, set: model.select)) {
                ForEach(model.state.profiles) { profile in
                    Text(profile.name).tag(profile.id)
                }
            }
            .labelsHidden()
            .frame(minWidth: 120, idealWidth: 180, maxWidth: 230)
            Menu {
                Button("Mod Folder…", action: model.importFolder)
                Button("From MacNative Mods…", action: model.importMacNative)
                    .disabled(!model.macNativeAvailable)
                if !model.macNativeAvailable { Text("No Ocarina of Time library found") }
            } label: {
                Label("Import", systemImage: "tray.and.arrow.down")
            }
            .fixedSize()
            .accessibilityLabel("Import mods")
            Menu {
                Button("New Profile…") { editProfile("New Profile") }
                Button("Duplicate Profile…") { editProfile("Duplicate Profile") }
                Button("Rename Profile…") { editProfile("Rename Profile") }
                Button("Delete Profile…", role: .destructive) { confirmDelete = true }
                    .disabled(model.state.profiles.count < 2)
                Divider()
                Button("Refresh", action: model.refresh)
                Button("Show Library in Finder", action: model.revealLibrary)
            } label: {
                Image(systemName: "ellipsis")
                    .frame(width: 18)
            }
            .menuIndicator(.hidden)
            .fixedSize()
            .accessibilityLabel("Mod profile actions")
        }
        .controlSize(.regular)
        .disabled(model.busy)
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
    }

    private var libraryTools: some View {
        HStack(spacing: 14) {
            Picker("Show mods", selection: $filter) {
                ForEach(LibraryFilter.allCases, id: \.self) { item in
                    Text(item.rawValue).tag(item)
                }
            }
            .labelsHidden()
            .pickerStyle(.segmented)
            .fixedSize()
            Spacer(minLength: 12)
            TextField("Search mods", text: $search)
                .textFieldStyle(.roundedBorder)
                .frame(minWidth: 130, idealWidth: 180, maxWidth: 240)
                .onExitCommand { search = "" }
                .accessibilityLabel("Search mods")
        }
        .controlSize(.small)
        .padding(.horizontal, 24)
        .padding(.bottom, 12)
    }

    private var modList: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Text("#").frame(width: 22).help("Load order")
                Text("Mod").frame(maxWidth: .infinity, alignment: .leading)
                Text("Status").frame(width: 64, alignment: .leading)
                Text("On").frame(width: 36)
            }
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 10)
            .background(Palette.forest.opacity(0.035))
            Divider()
            if visiblePacks.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("No matching mods").font(.system(size: 14, weight: .medium))
                    Text("Change the search or filter.").font(.system(size: 12)).foregroundStyle(.secondary)
                }
                .padding(20)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            } else {
                List(selection: $selectedPackID) {
                    ForEach(visiblePacks) { pack in
                        modRow(pack)
                            .tag(pack.id)
                            .listRowInsets(EdgeInsets(top: 0, leading: 10, bottom: 0, trailing: 10))
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .accessibilityLabel("Mods in load order")
            }
        }
    }

    private func modRow(_ pack: ModPack) -> some View {
        let conflictCount = model.conflicts.values.filter { $0.contains(pack.id) }.count
        let index = model.selectedPacks.firstIndex { $0.id == pack.id } ?? 0
        let enabled = model.selected.enabled.contains(pack.id)
        return HStack(spacing: 10) {
            Text(String(index + 1))
                .font(.system(size: 12))
                .monospacedDigit()
                .foregroundStyle(.secondary)
                .frame(width: 22)
            Text(pack.name)
                .font(.system(size: 13, weight: .medium))
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .help(pack.name)
            Group {
                if conflictCount > 0 {
                    Label("Shared", systemImage: "square.2.layers.3d")
                        .foregroundStyle(Palette.brass)
                        .help("\(conflictCount) shared file paths")
                        .accessibilityLabel("\(conflictCount) shared file paths")
                } else {
                    Text(enabled ? "Enabled" : "Disabled").foregroundStyle(.secondary)
                }
            }
            .font(.system(size: 12))
            .frame(width: 64, alignment: .leading)
            Toggle("Enable \(pack.name)", isOn: Binding(
                get: { model.selected.enabled.contains(pack.id) },
                set: { model.toggle(pack, enabled: $0) }
            ))
            .labelsHidden()
            .toggleStyle(.switch)
            .controlSize(.mini)
            .frame(width: 36)
            .disabled(model.busy)
        }
        .padding(.vertical, 9)
        .contentShape(Rectangle())
    }

    @ViewBuilder private var inspector: some View {
        if let pack = selectedPack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(pack.name)
                        .font(.system(size: 19, weight: .semibold))
                        .foregroundStyle(Palette.ink)
                        .textSelection(.enabled)
                    Text(pack.detail)
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                    Text("\(pack.files.formatted()) files · \(ByteCountFormatter.string(fromByteCount: Int64(pack.bytes), countStyle: .file))")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                    reorderControls(pack)
                    Divider().padding(.top, 4)
                    DisclosureGroup("Details") {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("RomFS mod · Stored in Kokiri’s library")
                            Text("Mod profiles share the same game save.")
                        }
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 10)
                    }
                    sharedFiles(pack)
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .id(pack.id)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Text("Select a mod").font(.system(size: 16, weight: .medium))
                Text("View its details and adjust its load order.")
                    .font(.system(size: 13)).foregroundStyle(.secondary)
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private func reorderControls(_ pack: ModPack) -> some View {
        let index = model.selectedPacks.firstIndex { $0.id == pack.id } ?? 0
        return HStack(spacing: 10) {
            Button("Move Up") { model.move(pack, by: -1) }
                .disabled(index == 0)
                .accessibilityLabel("Move \(pack.name) earlier")
            Button("Move Down") { model.move(pack, by: 1) }
                .disabled(index == model.selectedPacks.count - 1)
                .accessibilityLabel("Move \(pack.name) later")
            Spacer(minLength: 0)
        }
        .disabled(model.busy)
        .padding(.top, 4)
    }

    private func sharedFiles(_ pack: ModPack) -> some View {
        let shared = model.conflicts.filter { $0.value.contains(pack.id) }
        return DisclosureGroup(shared.isEmpty ? "Shared Files" : "Shared Files (\(shared.count))") {
            VStack(alignment: .leading, spacing: 10) {
                if shared.isEmpty {
                    Text("No shared paths in this profile.")
                } else {
                    Text("Later mods supply files that overlap.")
                    ForEach(shared.keys.sorted(), id: \.self) { path in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(path).textSelection(.enabled)
                            if let winner = shared[path]?.last,
                               let name = model.state.packs.first(where: { $0.id == winner })?.name {
                                Text("Supplied by \(name)").foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .font(.system(size: 12))
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 10)
        }
    }

    private var emptyLibrary: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Add your first mod").font(.system(size: 18, weight: .medium))
            Text("Use Import to add a mod folder or copy your MacNative Mods library.")
                .font(.system(size: 13)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var footer: some View {
        HStack(alignment: .top, spacing: 8) {
            if model.launchBlocker != nil { Image(systemName: "info.circle") }
            Text(model.launchBlocker ?? (model.gameRunning
                ? "Changes apply when you start a new session."
                : "Selected profile applies at the next launch."))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .font(.system(size: 12))
        .foregroundStyle(.secondary)
        .padding(.horizontal, 24)
        .padding(.vertical, 13)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .top) { Divider() }
    }

    private func feedback(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: model.failed ? "exclamationmark.triangle" : "info.circle")
            Text(message).font(.system(size: 12)).textSelection(.enabled)
            Spacer()
            Button(action: model.dismissMessage) { Image(systemName: "xmark") }
                .buttonStyle(.plain).accessibilityLabel("Dismiss mod message")
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(Palette.brass.opacity(0.10))
    }

    private func keepSelection() {
        if !visiblePacks.contains(where: { $0.id == selectedPackID }) {
            selectedPackID = visiblePacks.first?.id
        }
    }

    private func editProfile(_ action: String) {
        profileAction = action
        if action == "Rename Profile" { profileName = model.selected.name }
        else if action == "Duplicate Profile" { profileName = model.selected.name + " Copy" }
        else { profileName = "" }
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
        }
        .padding(24)
        .frame(width: 380)
    }

    private func submitProfile() {
        guard !profileName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !model.busy else { return }
        if profileAction == "Rename Profile" { model.rename(profileName) }
        else { model.create(profileName, duplicate: profileAction == "Duplicate Profile") }
        showProfileSheet = false
    }
}
