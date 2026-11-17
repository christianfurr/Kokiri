import Foundation
import Darwin
import XCTest
@testable import KokiriCore

final class SaveLibraryTests: XCTestCase {
    private struct FixtureFile {
        var bytes: Data
        let offsets: [UInt32: Int]
    }

    /// Synthetic field records only; no player data or game-derived byte fixture.
    private func save(header: Int, integers: [UInt32: Int32], strings: [UInt32: String] = [:],
                      blocks: [UInt32: Data] = [:]) -> FixtureFile {
        let hashes = Set(integers.keys).union(strings.keys).union(blocks.keys).sorted()
        var bytes = Data(repeating: 0, count: header + strings.count * 64 + blocks.values.reduce(0) { $0 + $1.count })
        put(0x01020304, into: &bytes, at: 0)
        put(0x002D80EB, into: &bytes, at: 4)
        put(UInt32(header), into: &bytes, at: 8)
        var offsets: [UInt32: Int] = [:]
        var cursor = header
        for (index, hash) in hashes.enumerated() {
            let at = 40 + index * 8
            precondition(at + 8 <= header)
            put(hash, into: &bytes, at: at)
            offsets[hash] = at + 4
            if let string = strings[hash] {
                put(UInt32(cursor), into: &bytes, at: at + 4)
                let encoded = Data(string.utf8)
                precondition(encoded.count < 64)
                bytes.replaceSubrange(cursor..<(cursor + encoded.count), with: encoded)
                cursor += 64
            } else if let block = blocks[hash] {
                put(UInt32(cursor), into: &bytes, at: at + 4)
                bytes.replaceSubrange(cursor..<(cursor + block.count), with: block)
                cursor += block.count
            } else {
                put(UInt32(bitPattern: integers[hash]!), into: &bytes, at: at + 4)
            }
        }
        return FixtureFile(bytes: bytes, offsets: offsets)
    }

    private func put(_ value: UInt32, into bytes: inout Data, at: Int) {
        for index in 0..<4 { bytes[at + index] = UInt8(truncatingIfNeeded: value >> (index * 8)) }
    }

    private func pair() -> (progress: FixtureFile, caption: FixtureFile) {
        let progress = save(header: 0x175D8, integers: [
            0x1D74617E: 1, 0xE0010A50: 200, 0xA77921D7: 75,
            0x31AB5580: 17, 0xFBE01DA1: 24, 0x76B18200: 120, 0x12D63A97: 240,
            0xCEA220D3: 1, 0x04735978: 12, 0x51EC97B3: 2,
            0xEEB495B9: 1, 0x7CA64F23: 1, 0xCBD1E58C: 1, 0x5CE254A6: 0,
            0xDB1BCD4F: 10
        ], strings: [0x3E42AFFA: "Item_Wallet_Small", 0x1D6189DA: "KokiriForest_Child",
                     0x874C7ED4: "FixtureProgress", 0xA95A3521: "Weapon_Sword_Kokiri",
                     0xEE463235: "Weapon_Shield_Deku"])
        let caption = save(header: 0x2A0, integers: [
            0xA9557547: 75, 0xBD46F485: 16, 0xDFD840D3: 11, 0x9811A3F7: 2026,
            0x23F3D75E: 18, 0x27853BF7: 25, 0x25F03CAA: 1
        ])
        return (progress, caption)
    }

    private func profile() throws -> URL {
        let root = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("KokiriSaveViewTests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }
    @discardableResult private func writePair(_ pair: (progress: FixtureFile, caption: FixtureFile),
                                            profile: URL, account: String = "test-account", index: Int = 0) throws -> URL {
        let slot = profile.appendingPathComponent("save/" + account + String(format: "/slot_%02d", index))
        try FileManager.default.createDirectory(at: slot, withIntermediateDirectories: true)
        try pair.progress.bytes.write(to: slot.appendingPathComponent("progress.sav"))
        try pair.caption.bytes.write(to: slot.appendingPathComponent("caption.sav"))
        return slot
    }

    func testDecodesTypedVitalsInventoryEquipmentAndMilestonesWithoutMutation() throws {
        let fixture = pair()
        let summary = try SaveLibrary.decode(progress: fixture.progress.bytes, caption: fixture.caption.bytes)
        XCTAssertEqual(summary.hearts, 4.25)
        XCTAssertEqual(summary.maxHearts, 6)
        XCTAssertEqual(summary.rupees, 75)
        XCTAssertEqual(summary.walletLimit, 200)
        XCTAssertEqual(summary.magic, 12)
        XCTAssertEqual(summary.maxMagic, 24)
        XCTAssertEqual(summary.era, "Child Link")
        XCTAssertEqual(summary.area, "Kokiri Forest Child")
        XCTAssertEqual(summary.equipped, ["Kokiri Sword", "Deku Shield"])
        XCTAssertEqual(summary.milestones.map(\.name), ["Kokiri Emerald"])
        XCTAssertEqual(summary.inventory.first(where: { $0.id == "Item_Bomb" })?.quantity, 10)
        XCTAssertEqual(summary.skulltulas, 12)
        XCTAssertTrue(summary.isAutosave == true)
        XCTAssertNotNil(summary.savedAt)
        XCTAssertNil(summary.previewJPEG)
        XCTAssertTrue(summary.notes.isEmpty)
        XCTAssertEqual(fixture.progress.bytes, pair().progress.bytes)
    }

    func testInspectUsesOnlyProvidedProfileAndKeepsOriginalFilesUnchanged() throws {
        let root = try profile(), fixture = pair()
        let slot = try writePair(fixture, profile: root)
        let other = try profile()
        try writePair(fixture, profile: other, account: "unrelated-account", index: 4)
        let loaded = try SaveLibrary.inspect(profileFolder: root)
        XCTAssertEqual(loaded.profileFolder.standardizedFileURL.path, root.standardizedFileURL.path)
        XCTAssertEqual(loaded.slots.map(\.id), ["test-account/slot_00"])
        XCTAssertEqual(loaded.slots.first?.number, 0)
        XCTAssertEqual(loaded.slots.first?.title, "Slot 1")
        XCTAssertEqual(loaded.slots.first?.summary?.rupees, 75)
        XCTAssertEqual(loaded.slots.first?.byteCount, fixture.progress.bytes.count + fixture.caption.bytes.count)
        XCTAssertTrue(loaded.warnings.isEmpty)
        XCTAssertEqual(try Data(contentsOf: slot.appendingPathComponent("progress.sav")), fixture.progress.bytes)
        XCTAssertEqual(try Data(contentsOf: slot.appendingPathComponent("caption.sav")), fixture.caption.bytes)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: slot.path).sorted(), ["caption.sav", "progress.sav"])
    }

    func testMissingProfileAndEmptySlotReturnEmptySnapshotsWithoutCreatingFiles() throws {
        let root = try profile()
        let missing = root.appendingPathComponent("missing")
        XCTAssertTrue(try SaveLibrary.inspect(profileFolder: missing).slots.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: missing.path))
        let slot = root.appendingPathComponent("save/account/slot_00")
        try FileManager.default.createDirectory(at: slot, withIntermediateDirectories: true)
        XCTAssertTrue(try SaveLibrary.inspect(profileFolder: root).slots.isEmpty)
    }

    func testMalformedAndIncompleteSlotsRemainVisibleBesideValidSlots() throws {
        let root = try profile(), fixture = pair()
        try writePair(fixture, profile: root, index: 1)
        let bad = try writePair(fixture, profile: root, index: 0)
        try Data([1, 2, 3]).write(to: bad.appendingPathComponent("progress.sav"))
        let incomplete = try writePair(fixture, profile: root, index: 5)
        try FileManager.default.removeItem(at: incomplete.appendingPathComponent("caption.sav"))
        let loaded = try SaveLibrary.inspect(profileFolder: root)
        XCTAssertEqual(loaded.slots.map(\.number), [0, 1, 5])
        XCTAssertNotNil(loaded.slots[0].problem)
        XCTAssertNil(loaded.slots[0].summary)
        XCTAssertEqual(loaded.slots[1].summary?.rupees, 75)
        XCTAssertNotNil(loaded.slots[2].problem)
    }

    func testRejectsLinkedSaveRootAccountSlotAndFile() throws {
        let foreign = try profile()
        let fixture = pair()
        let foreignSlot = try writePair(fixture, profile: foreign)
        let rootLink = try profile()
        try FileManager.default.createSymbolicLink(at: rootLink.appendingPathComponent("save"), withDestinationURL: foreign.appendingPathComponent("save"))
        XCTAssertThrowsError(try SaveLibrary.inspect(profileFolder: rootLink))

        let accountLink = try profile()
        try FileManager.default.createDirectory(at: accountLink.appendingPathComponent("save"), withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: accountLink.appendingPathComponent("save/foreign"), withDestinationURL: foreignSlot.deletingLastPathComponent())
        let accounts = try SaveLibrary.inspect(profileFolder: accountLink)
        XCTAssertTrue(accounts.slots.isEmpty)
        XCTAssertEqual(accounts.warnings.count, 1)

        let slotLink = try profile()
        try FileManager.default.createDirectory(at: slotLink.appendingPathComponent("save/account"), withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: slotLink.appendingPathComponent("save/account/slot_00"), withDestinationURL: foreignSlot)
        XCTAssertEqual(try SaveLibrary.inspect(profileFolder: slotLink).warnings.count, 1)

        let fileRoot = try profile(), ownSlot = try writePair(fixture, profile: fileRoot)
        let ownFile = ownSlot.appendingPathComponent("progress.sav")
        try FileManager.default.removeItem(at: ownFile)
        try FileManager.default.createSymbolicLink(at: ownFile, withDestinationURL: foreignSlot.appendingPathComponent("progress.sav"))
        XCTAssertNotNil(try SaveLibrary.inspect(profileFolder: fileRoot).slots.first?.problem)
    }

    func testRefusesFIFOAndOversizedFileWithoutReadingThem() throws {
        let root = try profile(), fixture = pair()
        let slot = try writePair(fixture, profile: root)
        let file = slot.appendingPathComponent("progress.sav")
        try FileManager.default.removeItem(at: file)
        XCTAssertEqual(mkfifo(file.path, 0o600), 0)
        XCTAssertNotNil(try SaveLibrary.inspect(profileFolder: root).slots.first?.problem)
        try FileManager.default.removeItem(at: file)
        try Data(repeating: 0, count: SaveLibrary.maximumFileBytes + 1).write(to: file)
        XCTAssertNotNil(try SaveLibrary.inspect(profileFolder: root).slots.first?.problem)
    }

    func testRejectsDuplicateFieldAndInvalidStringPointer() throws {
        var fixture = pair()
        let first = fixture.progress.bytes.subdata(in: 40..<44)
        fixture.progress.bytes.replaceSubrange(48..<52, with: first)
        XCTAssertThrowsError(try SaveLibrary.decode(progress: fixture.progress.bytes, caption: fixture.caption.bytes))
        fixture = pair()
        put(UInt32.max, into: &fixture.progress.bytes, at: fixture.progress.offsets[0x3E42AFFA]!)
        XCTAssertThrowsError(try SaveLibrary.decode(progress: fixture.progress.bytes, caption: fixture.caption.bytes))
        fixture = pair()
        put(5, into: &fixture.progress.bytes, at: 4)
        XCTAssertThrowsError(try SaveLibrary.decode(progress: fixture.progress.bytes, caption: fixture.caption.bytes))
    }

    func testRecognizesLegacyMagicAndPreviewMismatchWithoutChangingSave() throws {
        var fixture = pair()
        put(24, into: &fixture.progress.bytes, at: fixture.progress.offsets[0x12D63A97]!)
        put(12, into: &fixture.progress.bytes, at: fixture.progress.offsets[0x76B18200]!)
        put(20, into: &fixture.caption.bytes, at: fixture.caption.offsets[0xA9557547]!)
        let summary = try SaveLibrary.decode(progress: fixture.progress.bytes, caption: fixture.caption.bytes)
        XCTAssertEqual(summary.magic, 12)
        XCTAssertEqual(summary.maxMagic, 24)
        XCTAssertEqual(summary.rupees, 75)
        XCTAssertEqual(summary.notes.count, 2)
    }

    func testBoundedEmbeddedJPEGAndInvalidDateAreOptional() throws {
        let fixture = pair()
        let jpeg = Data([0xFF, 0xD8, 0xFF, 0xD9])
        var block = Data(repeating: 0, count: 4)
        put(UInt32(jpeg.count), into: &block, at: 0)
        block.append(jpeg)
        let caption = save(header: 0x2A0, integers: [0xA9557547: 75, 0xBD46F485: 31, 0xDFD840D3: 2,
                                                  0x9811A3F7: 2026, 0x23F3D75E: 10, 0x27853BF7: 0],
                           blocks: [0x63696A32: block])
        let summary = try SaveLibrary.decode(progress: fixture.progress.bytes, caption: caption.bytes)
        XCTAssertEqual(summary.previewJPEG, jpeg)
        XCTAssertNil(summary.savedAt)
        var broken = caption
        put(UInt32.max, into: &broken.bytes, at: broken.offsets[0x63696A32]!)
        XCTAssertThrowsError(try SaveLibrary.decode(progress: fixture.progress.bytes, caption: broken.bytes))
    }

    func testSnapshotDoesNotPretendToBeLiveAfterGameChangesAFile() throws {
        let root = try profile()
        var fixture = pair()
        let slot = try writePair(fixture, profile: root)
        let before = try SaveLibrary.inspect(profileFolder: root)
        put(100, into: &fixture.progress.bytes, at: fixture.progress.offsets[0xA77921D7]!)
        try fixture.progress.bytes.write(to: slot.appendingPathComponent("progress.sav"), options: .atomic)
        XCTAssertEqual(before.slots.first?.summary?.rupees, 75)
        XCTAssertEqual(try SaveLibrary.inspect(profileFolder: root).slots.first?.summary?.rupees, 100)
    }
}
