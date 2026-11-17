import AppKit
import SwiftUI
import KokiriCore
import ImageIO

struct SavesView: View {
    let profileFolder: URL
    @State private var snapshot: SaveLibrarySnapshot?
    @State private var selection: String?
    @State private var loading = false
    @State private var error: String?
    @State private var refreshID = UUID()

    private var selectedSlot: SaveSlot? {
        snapshot?.slots.first(where: { $0.id == selection }) ?? snapshot?.slots.first
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack(alignment: .top, spacing: 18) {
                    PageHeading(eyebrow: "Your progress", title: "Saves",
                                detail: "Browse the saves in your connected player profile.")
                    Button { Task { await refresh() } } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                        .disabled(loading)
                        .padding(.top, 24)
                }
                Surface {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Label("Connected player profile", systemImage: "person.crop.square").font(.system(size: 13, weight: .semibold))
                            Spacer()
                            Button("Show in Finder") { reveal(profileFolder) }
                        }
                        Text(profileFolder.path).font(.system(size: 11)).foregroundStyle(.secondary)
                            .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    }
                }
                if let error {
                    Surface {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                }
                if let snapshot, !snapshot.slots.isEmpty {
                    slotPicker(snapshot)
                    if let slot = selectedSlot { details(slot) }
                    snapshotNote(snapshot)
                } else if loading {
                    Surface { ProgressView("Reading saves…").frame(maxWidth: .infinity, minHeight: 160) }
                } else if error == nil {
                    Surface {
                        ContentUnavailableView("No saves in this profile", systemImage: "externaldrive",
                                               description: Text("Your saved slots appear here after you save in the game."))
                            .frame(minHeight: 160)
                        Button("Show Profile in Finder") { reveal(profileFolder) }
                    }
                }
                if let snapshot, !snapshot.warnings.isEmpty {
                    Surface {
                        VStack(alignment: .leading, spacing: 9) {
                            Label("Some saves could not be read", systemImage: "exclamationmark.triangle")
                                .font(.system(size: 13, weight: .semibold))
                            ForEach(Array(snapshot.warnings.enumerated()), id: \.offset) { _, warning in
                                Text(warning).font(.system(size: 12)).foregroundStyle(.secondary).textSelection(.enabled)
                            }
                        }
                    }
                }
            }.padding(32).frame(maxWidth: 1140)
        }
        .task(id: profileFolder) {
            snapshot = nil; selection = nil
            await refresh()
        }
    }

    private func slotPicker(_ snapshot: SaveLibrarySnapshot) -> some View {
        Surface {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("Saved slots", systemImage: "square.stack").font(.system(size: 14, weight: .semibold))
                    Spacer()
                    Text("\(snapshot.slots.count) found").font(.system(size: 11)).foregroundStyle(.secondary)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 185), spacing: 12)], alignment: .leading, spacing: 12) {
                    ForEach(snapshot.slots) { slot in
                        Button { selection = slot.id } label: {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text(slot.title).font(.system(size: 13, weight: .semibold))
                                    Spacer(minLength: 8)
                                    Image(systemName: slot.problem == nil ? "doc.text" : "exclamationmark.triangle")
                                        .foregroundStyle(slot.problem == nil ? Palette.moss : Palette.brass)
                                }
                                Text(slot.summary?.area ?? (slot.problem == nil ? "Saved game" : "Unable to read"))
                                    .font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(2)
                                Text(slot.summary?.isAutosave.map { $0 ? "Autosave" : "Manual save" } ?? slot.folder.lastPathComponent)
                                    .font(.system(size: 10)).foregroundStyle(.secondary)
                                Text(slot.account).font(.system(size: 9)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                            }
                            .padding(13).frame(maxWidth: .infinity, minHeight: 92, alignment: .topLeading)
                            .background(selectedSlot?.id == slot.id ? Palette.forest.opacity(0.08) : .clear,
                                        in: RoundedRectangle(cornerRadius: 11))
                            .overlay(RoundedRectangle(cornerRadius: 11).stroke(selectedSlot?.id == slot.id ? Palette.forest : Palette.line, lineWidth: 1))
                            .contentShape(RoundedRectangle(cornerRadius: 11))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(slot.title), \(slot.summary?.area ?? "saved game"), account \(slot.account)")
                        .accessibilityAddTraits(selectedSlot?.id == slot.id ? .isSelected : [])
                    }
                }
            }
        }
    }

    @ViewBuilder private func details(_ slot: SaveSlot) -> some View {
        if let summary = slot.summary {
            Surface {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(slot.title).font(.system(size: 22, weight: .semibold, design: .serif)).foregroundStyle(Palette.ink)
                            Text([summary.area, summary.era].compactMap { $0 }.joined(separator: " · "))
                                .font(.system(size: 12)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Show in Finder") { reveal(slot.folder) }
                    }
                    if let data = summary.previewJPEG, let image = previewImage(data) {
                        Image(nsImage: image).resizable().scaledToFit()
                            .frame(maxWidth: .infinity, maxHeight: 290)
                            .background(Palette.forest.opacity(0.05), in: RoundedRectangle(cornerRadius: 12))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .accessibilityLabel("Screenshot stored with \(slot.title)")
                    }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 160), spacing: 20)], alignment: .leading, spacing: 18) {
                        stat("Hearts", value: "\(number(summary.hearts)) / \(number(summary.maxHearts))", symbol: "heart")
                        stat("Rupees", value: "\(summary.rupees) / \(summary.walletLimit)", symbol: "diamond")
                        if let magic = summary.magic, let maxMagic = summary.maxMagic {
                            stat("Magic", value: "\(number(magic)) / \(number(maxMagic)) MP", symbol: "sparkle")
                        }
                        if let count = summary.skulltulas { stat("Gold Skulltulas", value: String(count), symbol: "ant") }
                    }
                    Divider()
                    VStack(spacing: 4) {
                        if let savedAt = summary.savedAt { DetailRow(title: "Saved in game", value: savedAt.formatted(date: .abbreviated, time: .shortened)) }
                        if let modified = slot.modifiedAt { DetailRow(title: "Files updated", value: modified.formatted(date: .abbreviated, time: .shortened)) }
                        DetailRow(title: "Account", value: slot.account)
                        DetailRow(title: "Wallet", value: summary.walletName)
                        if let pieces = summary.heartPieces { DetailRow(title: "Pieces of Heart", value: "\(pieces) / 4") }
                        if !summary.equipped.isEmpty { DetailRow(title: "Equipped in saved eras", value: summary.equipped.joined(separator: ", ")) }
                    }
                    ForEach(Array(summary.notes.enumerated()), id: \.offset) { _, note in
                        Text(note).font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                }
            }
            itemSection("Spiritual stones & medallions", items: summary.milestones,
                        empty: "No stones or medallions recorded in this slot.")
            itemSection("Inventory", items: summary.inventory, empty: "No named inventory items recorded in this slot.")
        } else {
            Surface {
                VStack(alignment: .leading, spacing: 14) {
                    Label("\(slot.title) could not be opened", systemImage: "doc.badge.ellipsis")
                        .font(.system(size: 15, weight: .semibold))
                    Text(slot.problem ?? "This save format is not supported.").font(.system(size: 12)).foregroundStyle(.secondary)
                    Text("Your files have not been changed. If the game is saving, refresh when it finishes.")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    Button("Show in Finder") { reveal(slot.folder) }
                }
            }
        }
    }

    private func stat(_ title: String, value: String, symbol: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: symbol).font(.system(size: 11)).foregroundStyle(.secondary)
            Text(value).font(.system(size: 22, weight: .medium, design: .rounded)).monospacedDigit().foregroundStyle(Palette.ink)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    private func itemSection(_ title: String, items: [SaveInventoryItem], empty: String) -> some View {
        Surface {
            VStack(alignment: .leading, spacing: 15) {
                Text(title).font(.system(size: 14, weight: .semibold))
                if items.isEmpty {
                    Text(empty).font(.system(size: 12)).foregroundStyle(.secondary)
                } else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 12)], alignment: .leading, spacing: 10) {
                        ForEach(items) { item in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(item.name).font(.system(size: 12))
                                Spacer(minLength: 4)
                                if item.quantity > 1 { Text("×\(item.quantity)").font(.system(size: 11)).monospacedDigit().foregroundStyle(.secondary) }
                            }.padding(.horizontal, 12).padding(.vertical, 9)
                                .background(Palette.forest.opacity(0.04), in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }
            }
        }
    }

    private func snapshotNote(_ snapshot: SaveLibrarySnapshot) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lock").foregroundStyle(Palette.moss)
            Text("Read-only snapshot · read \(snapshot.loadedAt.formatted(date: .omitted, time: .standard)). Refresh after saving in game to see changes.")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer(minLength: 0)
        }
    }

    @MainActor private func refresh() async {
        let request = UUID()
        refreshID = request
        loading = true; error = nil
        defer { if refreshID == request { loading = false } }
        let folder = profileFolder
        let result = await Task.detached(priority: .userInitiated) { Result { try SaveLibrary.inspect(profileFolder: folder) } }.value
        guard !Task.isCancelled, refreshID == request else { return }
        switch result {
        case .success(let loaded):
            snapshot = loaded
            if !loaded.slots.contains(where: { $0.id == selection }) { selection = loaded.slots.first?.id }
        case .failure(let failure): error = failure.localizedDescription; snapshot = nil
        }
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
