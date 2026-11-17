import AppKit
import SwiftUI
import KokiriCore
import ImageIO

struct SavesView: View {
    let profileFolder: URL?
    @State private var snapshot: SaveLibrarySnapshot?
    @State private var selection: String?
    @State private var loading = false
    @State private var error: String?
    @State private var refreshID = UUID()
    @State private var inventoryExpanded = false
    @State private var detailsExpanded = false

    private var selectedSlot: SaveSlot? {
        snapshot?.slots.first(where: { $0.id == selection }) ?? snapshot?.slots.first
    }

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider()
            if let profileFolder {
                if let snapshot, !snapshot.slots.isEmpty {
                    HSplitView {
                        slotList(snapshot)
                            .frame(minWidth: 210, idealWidth: 240, maxWidth: 300, maxHeight: .infinity)
                        ScrollView {
                            if let slot = selectedSlot { inspector(slot, profile: profileFolder) }
                        }
                        .frame(minWidth: 320, maxWidth: .infinity, maxHeight: .infinity)
                    }
                } else {
                    emptyState(profile: profileFolder)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else {
                ContentUnavailableView("Player profile unavailable", systemImage: "externaldrive.badge.exclamationmark",
                                       description: Text("The connected player profile could not be verified."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            if let error, snapshot != nil {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.system(size: 11)).foregroundStyle(.secondary).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20).padding(.vertical, 10)
            }
            if let snapshot, !snapshot.warnings.isEmpty { warnings(snapshot.warnings) }
            Divider()
            footer
        }
        .task(id: profileFolder) {
            refreshID = UUID()
            snapshot = nil; selection = nil; error = nil; loading = false
            inventoryExpanded = false; detailsExpanded = false
            guard profileFolder != nil else { return }
            await refresh()
        }
        .onChange(of: selection) { _, _ in
            inventoryExpanded = false
            detailsExpanded = false
        }
    }

    private var toolbar: some View {
        HStack(spacing: 12) {
            Text("Saves").font(.system(size: 22, weight: .semibold)).foregroundStyle(Palette.ink)
            Spacer(minLength: 12)
            Button { Task { await refresh() } } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                .disabled(loading || profileFolder == nil)
            Menu {
                if let slot = selectedSlot {
                    Button("Show Save in Finder") { reveal(slot.folder) }
                }
                if let profileFolder {
                    Button("Show Profile in Finder") { reveal(profileFolder) }
                }
            } label: {
                Image(systemName: "ellipsis").frame(width: 18)
            }
            .menuIndicator(.hidden)
            .accessibilityLabel("Save actions")
            .disabled(profileFolder == nil)
        }
        .controlSize(.small)
        .padding(.horizontal, 20).padding(.vertical, 16)
    }

    private func slotList(_ snapshot: SaveLibrarySnapshot) -> some View {
        List(selection: $selection) {
            Section {
                ForEach(snapshot.slots) { slot in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 8) {
                            Text(slot.title).font(.system(size: 13, weight: .medium))
                            Spacer(minLength: 4)
                            if slot.problem != nil {
                                Image(systemName: "exclamationmark.triangle")
                                    .font(.system(size: 11)).foregroundStyle(Palette.brass)
                            }
                        }
                        Text(slot.summary?.area ?? (slot.problem == nil ? "Saved game" : "Unable to read"))
                            .font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(2)
                        Text(saveDate(slot)).font(.system(size: 10)).foregroundStyle(.secondary)
                        Text(saveType(slot.summary)).font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 7)
                    .tag(slot.id)
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("\(slot.title), \(slot.summary?.area ?? "saved game"), \(saveType(slot.summary)), \(saveDate(slot))")
                    .accessibilityHint("Select to view this save. Account \(slot.account).")
                }
            } header: {
                Text("Saved slots · \(snapshot.slots.count)").font(.system(size: 11)).foregroundStyle(.secondary)
                    .textCase(nil)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .accessibilityLabel("Saved slots")
    }

    @ViewBuilder private func inspector(_ slot: SaveSlot, profile: URL) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            if let summary = slot.summary {
                if let data = summary.previewJPEG, let image = previewImage(data) {
                    Image(nsImage: image).resizable().scaledToFit()
                        .frame(maxWidth: .infinity, maxHeight: 220)
                        .clipShape(RoundedRectangle(cornerRadius: 7))
                        .accessibilityLabel("Screenshot stored with \(slot.title)")
                }
                VStack(alignment: .leading, spacing: 7) {
                    Text(summary.area ?? slot.title).font(.system(size: 18, weight: .semibold)).foregroundStyle(Palette.ink)
                    Text("\(slot.title) · \(saveType(summary))").font(.system(size: 12)).foregroundStyle(.secondary)
                    Text(saveDate(slot)).font(.system(size: 11)).foregroundStyle(.secondary)
                    if let era = summary.era { Text(era).font(.system(size: 11)).foregroundStyle(.secondary) }
                }
                HStack(spacing: 20) {
                    Label("\(number(summary.hearts)) / \(number(summary.maxHearts))", systemImage: "heart")
                        .accessibilityLabel("Hearts, \(number(summary.hearts)) of \(number(summary.maxHearts))")
                    Label("\(summary.rupees) / \(summary.walletLimit)", systemImage: "diamond")
                        .accessibilityLabel("Rupees, \(summary.rupees) of \(summary.walletLimit)")
                }
                .font(.system(size: 13)).monospacedDigit().foregroundStyle(Palette.ink)
                inventory(summary)
                ForEach(Array(summary.notes.enumerated()), id: \.offset) { _, note in
                    Text(note).font(.system(size: 11)).foregroundStyle(.secondary).textSelection(.enabled)
                }
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    Label("\(slot.title) could not be opened", systemImage: "doc.badge.ellipsis")
                        .font(.system(size: 15, weight: .semibold))
                    Text(slot.problem ?? "This save format is not supported.")
                        .font(.system(size: 12)).foregroundStyle(.secondary).textSelection(.enabled)
                    Text("If the game is saving, refresh when it finishes.")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
            fileDetails(profile: profile, slot: slot)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private func inventory(_ summary: SaveSummary) -> some View {
        VStack(spacing: 0) {
            Divider().padding(.bottom, 12)
            DisclosureGroup("Inventory & progress", isExpanded: $inventoryExpanded) {
                VStack(alignment: .leading, spacing: 16) {
                    if let magic = summary.magic, let maximum = summary.maxMagic {
                        DetailRow(title: "Magic", value: "\(number(magic)) / \(number(maximum)) MP")
                    }
                    if let count = summary.skulltulas { DetailRow(title: "Gold Skulltulas", value: String(count)) }
                    if let pieces = summary.heartPieces { DetailRow(title: "Pieces of Heart", value: "\(pieces) / 4") }
                    DetailRow(title: "Wallet", value: summary.walletName)
                    if !summary.equipped.isEmpty {
                        DetailRow(title: "Equipped in saved eras", value: summary.equipped.joined(separator: ", "))
                    }
                    items("Stones & medallions", values: summary.milestones, empty: "None recorded in this slot.")
                    items("Inventory", values: summary.inventory, empty: "No named items recorded in this slot.")
                }
                .padding(.top, 12)
            }
            .font(.system(size: 12))
        }
    }

    private func items(_ title: String, values: [SaveInventoryItem], empty: String) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(title).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
            if values.isEmpty {
                Text(empty).font(.system(size: 11)).foregroundStyle(.secondary)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 145), spacing: 12)], alignment: .leading, spacing: 10) {
                    ForEach(values) { item in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(item.name).font(.system(size: 11))
                            if item.quantity > 1 {
                                Text("×\(item.quantity)").font(.system(size: 10)).monospacedDigit().foregroundStyle(.secondary)
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    private func fileDetails(profile: URL, slot: SaveSlot?) -> some View {
        VStack(spacing: 0) {
            Divider().padding(.bottom, 12)
            DisclosureGroup("File details", isExpanded: $detailsExpanded) {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Connected player profile").foregroundStyle(.secondary)
                        Text(profile.path).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    }
                    if let slot {
                        DetailRow(title: "Account", value: slot.account)
                        if let modified = slot.modifiedAt {
                            DetailRow(title: "Files updated", value: modified.formatted(date: .abbreviated, time: .shortened))
                        }
                        if slot.byteCount > 0 {
                            DetailRow(title: "Save size", value: ByteCountFormatter.string(fromByteCount: Int64(slot.byteCount), countStyle: .file))
                        }
                        Text(slot.folder.path).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                        Button("Show Save in Finder") { reveal(slot.folder) }
                    } else {
                        Button("Show Profile in Finder") { reveal(profile) }
                    }
                }
                .font(.system(size: 11)).padding(.top, 12)
            }
            .font(.system(size: 12))
        }
    }

    @ViewBuilder private func emptyState(profile: URL) -> some View {
        VStack(spacing: 16) {
            if loading {
                ProgressView("Reading saves…").font(.system(size: 12))
            } else if let error {
                ContentUnavailableView("Saves could not be read", systemImage: "exclamationmark.triangle",
                                       description: Text(error))
            } else {
                ContentUnavailableView("No saves in this profile", systemImage: "externaldrive",
                                       description: Text("Saved slots appear after you save in the game."))
            }
            fileDetails(profile: profile, slot: nil)
                .frame(maxWidth: 420).padding(.horizontal, 20)
        }.padding(.vertical, 24)
    }

    private func warnings(_ values: [String]) -> some View {
        DisclosureGroup {
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(values.enumerated()), id: \.offset) { _, warning in
                        Text(warning).font(.system(size: 11)).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
            }.frame(maxHeight: 140)
        } label: {
            Label("Some saves could not be read (\(values.count))", systemImage: "exclamationmark.triangle")
                .font(.system(size: 11)).foregroundStyle(.secondary)
        }
        .padding(.horizontal, 20).padding(.vertical, 10)
    }

    private var footer: some View {
        HStack(spacing: 12) {
            Label("Read-only", systemImage: "lock").foregroundStyle(Palette.moss)
            Spacer(minLength: 8)
            if loading {
                Text("Reading saves…").foregroundStyle(.secondary)
            } else if let snapshot {
                Text("Read \(snapshot.loadedAt.formatted(date: .omitted, time: .standard)) · Refresh after saving")
                    .foregroundStyle(.secondary)
            } else {
                Text("Your save files stay unchanged").foregroundStyle(.secondary)
            }
        }
        .font(.system(size: 10)).padding(.horizontal, 20).padding(.vertical, 12)
    }

    @MainActor private func refresh() async {
        let request = UUID()
        refreshID = request
        guard let folder = profileFolder else {
            snapshot = nil; selection = nil; error = nil; loading = false
            return
        }
        loading = true; error = nil
        defer { if refreshID == request { loading = false } }
        let result = await Task.detached(priority: .userInitiated) { Result { try SaveLibrary.inspect(profileFolder: folder) } }.value
        guard !Task.isCancelled, refreshID == request, profileFolder == folder else { return }
        switch result {
        case .success(let loaded):
            snapshot = loaded
            if !loaded.slots.contains(where: { $0.id == selection }) { selection = loaded.slots.first?.id }
        case .failure(let failure): error = failure.localizedDescription; snapshot = nil
        }
    }

    private func saveType(_ summary: SaveSummary?) -> String {
        guard let autosave = summary?.isAutosave else { return "Saved game" }
        return autosave ? "Autosave" : "Manual save"
    }
    private func saveDate(_ slot: SaveSlot) -> String {
        guard let date = slot.summary?.savedAt ?? slot.modifiedAt else { return "Save time unavailable" }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
    private func reveal(_ folder: URL) { NSWorkspace.shared.activateFileViewerSelecting([folder]) }
    private func number(_ value: Double) -> String { value.formatted(.number.precision(.fractionLength(0...2))) }

    /// Inspect dimensions before decoding and bound the displayed bitmap allocation.
    private func previewImage(_ data: Data) -> NSImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
              width > 0, height > 0, width <= 8192, height <= 8192, width * height <= 16_777_216,
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceThumbnailMaxPixelSize: 1600,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceShouldCacheImmediately: true
              ] as CFDictionary) else { return nil }
        return NSImage(cgImage: image, size: .zero)
    }
}
