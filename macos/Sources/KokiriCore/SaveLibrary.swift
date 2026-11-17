// Read-only Swift adaptation of the save-domain format in
// tools/kokiri-mcp/save_workshop/domain.cjs and catalog.json.
// Upstream: Traiver/OOT-SW2SE de26f03d0a299e39e5536bf68eeef9b251fadba1.
// Copyright (c) 2026 Traiver; macOS additions by Christian Furr / contributors.
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

import Foundation
import Darwin

public struct SaveInventoryItem: Identifiable, Sendable {
    public let id: String
    public let name: String
    public let quantity: Int
}

public struct SaveSummary: Sendable {
    public let hearts: Double
    public let maxHearts: Double
    public let rupees: Int
    public let walletLimit: Int
    public let walletName: String
    public let magic: Double?
    public let maxMagic: Double?
    public let era: String?
    public let area: String?
    public let progressID: String?
    public let savedAt: Date?
    public let isAutosave: Bool?
    public let skulltulas: Int?
    public let heartPieces: Int?
    public let equipped: [String]
    public let inventory: [SaveInventoryItem]
    public let milestones: [SaveInventoryItem]
    public let previewJPEG: Data?
    public let notes: [String]
}

public struct SaveSlot: Identifiable, Sendable {
    public let id: String
    public let account: String
    /// The game's on-disk slot index, from zero through five.
    public let number: Int
    public let folder: URL
    public let modifiedAt: Date?
    public let byteCount: Int
    public let summary: SaveSummary?
    public let problem: String?
    public var title: String { "Slot \(number + 1)" }
}

public struct SaveLibrarySnapshot: Sendable {
    public let profileFolder: URL
    public let loadedAt: Date
    public let slots: [SaveSlot]
    public let warnings: [String]
}

public enum SaveLibrary {
    public static let maximumFileBytes = 2 * 1024 * 1024
    private static let maximumProfileBytes = 8 * 1024 * 1024

    /// Inspects only the supplied profile. No legacy lookup, migration, or write occurs.
    public static func inspect(profileFolder: URL) throws -> SaveLibrarySnapshot {
        let profileURL = profileFolder.standardizedFileURL
        guard FileManager.default.fileExists(atPath: profileURL.path) else {
            return SaveLibrarySnapshot(profileFolder: profileURL, loadedAt: Date(), slots: [], warnings: [])
        }
        let profile = try SaveDirectory(url: profileURL)
        guard let saves = try profile.optionalDirectory("save") else {
            return SaveLibrarySnapshot(profileFolder: profileURL, loadedAt: Date(), slots: [], warnings: [])
        }
        var slots: [SaveSlot] = [], warnings: [String] = []
        var budget = maximumProfileBytes
        let accounts = try saves.names().filter { !$0.hasPrefix(".") }
        guard accounts.count <= 64 else { throw SaveReadError("This profile contains too many save accounts to inspect.") }
        // Normal runtime layout: profile/save/<account>/slot_00 ... slot_05.
        for account in accounts {
            do {
                guard let directory = try saves.optionalDirectory(account) else { continue }
                for index in 0..<6 {
                    let name = String(format: "slot_%02d", index)
                    do {
                        guard let slot = try directory.optionalDirectory(name) else { continue }
                        let names = try slot.names()
                        guard names.contains("progress.sav") || names.contains("caption.sav") else { continue }
                        let folder = profileURL.appendingPathComponent("save").appendingPathComponent(account).appendingPathComponent(name)
                        var size = 0
                        var modified: Date?
                        do {
                            let progress = try slot.read("progress.sav", budget: budget)
                            budget -= progress.data.count
                            let caption = try slot.read("caption.sav", budget: budget)
                            budget -= caption.data.count
                            size = progress.data.count + caption.data.count
                            modified = max(progress.modifiedAt, caption.modifiedAt)
                            let summary = try decode(progress: progress.data, caption: caption.data)
                            // Recheck both files after decoding: a game save can replace the pair.
                            try slot.verify("progress.sav", matches: progress.identity)
                            try slot.verify("caption.sav", matches: caption.identity)
                            slots.append(SaveSlot(id: account + "/" + name, account: account, number: index,
                                                  folder: folder, modifiedAt: modified, byteCount: size,
                                                  summary: summary, problem: nil))
                        } catch {
                            slots.append(SaveSlot(id: account + "/" + name, account: account, number: index,
                                                  folder: folder, modifiedAt: modified, byteCount: size,
                                                  summary: nil, problem: error.localizedDescription))
                        }
                    } catch { warnings.append("\(account) / \(name): \(error.localizedDescription)") }
                }
            } catch { warnings.append("\(account): \(error.localizedDescription)") }
        }
        return SaveLibrarySnapshot(profileFolder: profileURL, loadedAt: Date(), slots: slots, warnings: warnings)
    }

    /// Decodes the supported typed Switch 2 save layout, without changing either buffer.
    public static func decode(progress: Data, caption: Data) throws -> SaveSummary {
        guard progress.count <= maximumFileBytes, caption.count <= maximumFileBytes else {
            throw SaveReadError("A save file exceeds the 2 MiB viewing limit.")
        }
        let p = try SaveFields(bytes: progress, headerEnd: 0x175D8)
        let c = try SaveFields(bytes: caption, headerEnd: 0x2A0)
        let wallets: [(String, UInt32, Int, String)] = [
            ("Item_Wallet_Small", 0x1D74617E, 200, "Kokiri Wallet"),
            ("Item_Wallet_Medium", 0x2D2C874B, 500, "Adult's Wallet"),
            ("Item_Wallet_Large", 0xAFA4BB52, 1000, "Giant's Wallet")
        ]
        let walletID = try p.string(0x3E42AFFA, length: 64)
        guard let wallet = wallets.first(where: { $0.0 == walletID }),
              try p.integer(0xE0010A50) == wallet.2, try p.integer(wallet.1) == 1 else {
            throw SaveReadError("The wallet fields are inconsistent or use an unsupported format.")
        }
        let rupees = try p.integer(0xA77921D7)
        let hearts = Double(try p.integer(0x31AB5580)) / 4
        let maxHearts = Double(try p.integer(0xFBE01DA1)) / 4
        guard rupees >= 0, maxHearts >= 3, maxHearts <= 20, hearts >= 0, hearts <= maxHearts else {
            throw SaveReadError("The save contains unsupported health or rupee values.")
        }
        var notes: [String] = []
        if let previewRupees = c.optionalInteger(0xA9557547), previewRupees != rupees {
            notes.append("The saved preview rupee count differs from progress. Values here come from progress.sav.")
        }
        let storedMagic = p.optionalInteger(0x76B18200), storedMax = p.optionalInteger(0x12D63A97)
        let legacyMagic = storedMax == 24 || storedMax == 48
        let magic = storedMagic.map { Double($0) / (legacyMagic ? 1 : 10) }
        let maxMagic = storedMax.map { Double($0) / (legacyMagic ? 1 : 10) }
        if let magic, let maxMagic, (magic < 0 || magic > maxMagic || maxMagic > 48) {
            throw SaveReadError("The save contains unsupported magic values.")
        }
        if legacyMagic { notes.append("Magic values use the older editor's unscaled format.") }
        let era: String?
        switch p.optionalInteger(0xCEA220D3) {
        case 0: era = "Adult Link"
        case 1: era = "Child Link"
        default: era = nil
        }
        let inventory = itemCatalog.compactMap { hash, actor, label -> SaveInventoryItem? in
            guard let quantity = p.optionalInteger(hash), quantity > 0 else { return nil }
            return SaveInventoryItem(id: actor, name: label, quantity: quantity)
        }
        let milestonePrefixes = ["Item_Stone_", "Item_Medal_"]
        let milestones = inventory.filter { item in milestonePrefixes.contains(where: item.id.hasPrefix) }
        var equipped: [String] = []
        for hash in [UInt32(0xA95A3521), 0xEE463235, 0xA1F7EE2B, 0x2342B619] {
            guard let actor = try p.optionalString(hash, length: 64), !actor.isEmpty else { continue }
            let name = itemCatalog.first(where: { $0.1 == actor })?.2 ?? readableName(actor)
            if !equipped.contains(name) { equipped.append(name) }
        }
        let area = try p.optionalString(0x1D6189DA, length: 64)
        let progressID = try p.optionalString(0x874C7ED4, length: 64)
        return SaveSummary(hearts: hearts, maxHearts: maxHearts, rupees: rupees,
                           walletLimit: wallet.2, walletName: wallet.3, magic: magic, maxMagic: maxMagic,
                           era: era, area: area.flatMap { $0.isEmpty ? nil : readableName($0) },
                           progressID: progressID.flatMap { $0.isEmpty ? nil : $0 },
                           savedAt: c.savedDate(), isAutosave: c.optionalInteger(0x25F03CAA).flatMap { [0, 1].contains($0) ? $0 == 1 : nil },
                           skulltulas: p.optionalInteger(0x04735978), heartPieces: p.optionalInteger(0x51EC97B3),
                           equipped: equipped, inventory: inventory.filter { item in !milestonePrefixes.contains(where: item.id.hasPrefix) },
                           milestones: milestones, previewJPEG: try c.previewJPEG(), notes: notes)
    }

    private static func readableName(_ text: String) -> String {
        text.replacingOccurrences(of: "_", with: " ")
            .replacingOccurrences(of: "([a-z])([A-Z])", with: "$1 $2", options: .regularExpression)
    }

    // Named inventory metadata from the credited domain catalog; no game/save bytes.
    private static let itemCatalog: [(UInt32, String, String)] = [
        (0x40AE1183, "Armor_Adult_Gauntlet_Gold", "Golden Gauntlets"),
        (0x0012B8C0, "Armor_Adult_Gauntlet_Silver", "Silver Gauntlets"),
        (0x21ECBD19, "Armor_Adult_Goron", "Goron Tunic"),
        (0x2BAD189A, "Armor_Adult_HeavyBoot", "Iron Boots"),
        (0xC9220366, "Armor_Adult_HoverBoot", "Hover Boots"),
        (0x6F631388, "Armor_Adult_Normal", "Hero's Clothes"),
        (0xB816AF94, "Armor_Adult_Zora", "Zora Tunic"),
        (0xD1317941, "Armor_Child_Gauntlet_Goron", "Goron Bracelet"),
        (0xF5E647DA, "Armor_Child_Mask_Amiibo0", "Fairy-Kid Mask"),
        (0x486C59A4, "Armor_Child_Mask_Amiibo1", "Princess Mask"),
        (0x7E607033, "Armor_Child_Mask_Bunny", "Bunny Hood"),
        (0x0E94A8DF, "Armor_Child_Mask_Gerudo", "Gerudo Mask"),
        (0xFC508DA7, "Armor_Child_Mask_Goron", "Goron Mask"),
        (0xB5C10899, "Armor_Child_Mask_Keaton", "Keaton Mask"),
        (0x47B2D775, "Armor_Child_Mask_Skull", "Skull Mask"),
        (0xF046629E, "Armor_Child_Mask_Spooky", "Spooky Mask"),
        (0x96459CD3, "Armor_Child_Mask_Truth", "Mask of Truth"),
        (0x924E9A46, "Armor_Child_Mask_Zora", "Zora Mask"),
        (0x49D1C374, "Armor_GlassTruth", "Lenses of Truth"),
        (0xF3B14CE2, "Item_AgonyStone", "Echo Gem"),
        (0xB6CA6093, "Item_AlarmCucco", "Wake-Up Cucco"),
        (0x5E529AB9, "Item_Arrow_Fire", "Fire Arrow"),
        (0x40735A8D, "Item_Arrow_Ice", "Ice Arrow"),
        (0xBFB285C8, "Item_Arrow_Light", "Light Arrow"),
        (0x518EC74B, "Item_Arrow_Normal", "Arrow"),
        (0xDB1BCD4F, "Item_Bomb", "Bomb"),
        (0xBD3CA2C6, "Item_BombBag_Large", "Biggest Bomb Bag"),
        (0xE5FF45AA, "Item_BombBag_Medium", "Bigger Bomb Bag"),
        (0xB0A1BF51, "Item_BombBag_Small", "Bomb Bag"),
        (0xDF7C517A, "Item_Bombchu", "Bombchu"),
        (0xA1D76D31, "Item_Boomerang", "Boomerang"),
        (0x2815C82A, "Item_BrokenSword", "Broken Goron Sword"),
        (0x7B9673F5, "Item_BulletBag_Large", "Biggest Deku-Seed Bag"),
        (0x9A30A9E5, "Item_BulletBag_Medium", "Bigger Deku-Seed Bag"),
        (0xDC52ACAF, "Item_BulletBag_Small", "Deku-Seed Bag"),
        (0xDED8E8D3, "Item_ClaimCheck", "Biggoron Receipt"),
        (0x51D89EF0, "Item_CojiroCucco", "Cojiro"),
        (0xF30D9F54, "Item_DekuNut", "Deku Nut"),
        (0x5FADF7FC, "Item_DekuSeed", "Deku Seed"),
        (0xB9494411, "Item_DekuStick", "Deku Stick"),
        (0xB796C16D, "Item_DinFire", "Din's Fire"),
        (0x919EA324, "Item_EyeballFrog", "Eyeball Frog"),
        (0x5C41A6B1, "Item_EyeDrop", "Specialty Eye Drops"),
        (0x9A826FAB, "Item_FairyBless_DefenseDouble", "Gift of Halved Damage"),
        (0x5E671D92, "Item_FairyBless_MP", "Gift of Improved Spin"),
        (0x5F043856, "Item_FairyBless_MPDouble", "Gift of Doubled Magic"),
        (0x47F2CA87, "Item_FaroreWind", "Farore's Wind"),
        (0x1AAFDB66, "Item_Hammer", "Megaton Hammer"),
        (0x8573D2CD, "Item_Hookshot", "Hookshot"),
        (0x8499EA34, "Item_Longshot", "Longshot"),
        (0xB003124D, "Item_MagicBean", "Magic Beans"),
        (0x5CE254A6, "Item_Medal_Fire", "Fire Medallion"),
        (0x692D57CB, "Item_Medal_Forest", "Forest Medallion"),
        (0x235C7D9A, "Item_Medal_Light", "Light Medallion"),
        (0x204D2063, "Item_Medal_Shadow", "Shadow Medallion"),
        (0x0C7A5FD0, "Item_Medal_Spirit", "Spirit Medallion"),
        (0x0151A68F, "Item_Medal_Water", "Water Medallion"),
        (0xF0828CD0, "Item_NayruLove", "Nayru's Love"),
        (0xD60E4B23, "Item_NutBag_Large", "Biggest Deku-Nut Bag"),
        (0xEAA1785E, "Item_NutBag_Medium", "Bigger Deku-Nut Bag"),
        (0x19B80DBC, "Item_NutBag_Small", "Deku-Nut Bag"),
        (0xB7DF60F1, "Item_Ocarina_Fairy", "Fairy Ocarina"),
        (0x54E2A3D1, "Item_Ocarina_Time", "Ocarina of Time"),
        (0x07DE3E6F, "Item_OddMushroom", "Odd Mushroom"),
        (0x58C9BC78, "Item_OddPowder", "Odd Poultice"),
        (0xA862D276, "Item_PoacherSaw", "Poacher's Saw"),
        (0x0165E7CA, "Item_PocketCucco", "Pocket Cucco"),
        (0x07F10AAF, "Item_PocketEgg", "Pocket Egg"),
        (0x897CF7EB, "Item_Prescription", "Prescription"),
        (0xD331C7DA, "Item_Quiver_Large", "Biggest Quiver"),
        (0x3BB370E1, "Item_Quiver_Medium", "Bigger Quiver"),
        (0xA8C3E1FB, "Item_Quiver_Small", "Quiver"),
        (0x4AEB140A, "Item_Scale_Gold", "Golden Scale"),
        (0x1240044B, "Item_Scale_Silver", "Silver Scale"),
        (0x600E29EB, "Item_ScrubBusinessSeed", "Business Scrub Seed"),
        (0x48E53698, "Item_StickBag_Large", "Biggest Deku-Stick Bag"),
        (0x41DB7AB5, "Item_StickBag_Medium", "Bigger Deku-Stick Bag"),
        (0x2FE6AB1A, "Item_StickBag_Small", "Deku-Stick Bag"),
        (0x7D69AD47, "Item_Stone_Fire", "Goron Ruby"),
        (0xCBD1E58C, "Item_Stone_Forest", "Kokiri Emerald"),
        (0xB8E3BF45, "Item_Stone_Water", "Zora Sapphire"),
        (0xFEB4D56B, "Item_Token_Gerudo", "Gerudo Pass"),
        (0x04735978, "Item_Token_Gold", "Token"),
        (0xAFA4BB52, "Item_Wallet_Large", "Giant's Wallet"),
        (0x2D2C874B, "Item_Wallet_Medium", "Adult's Wallet"),
        (0x1D74617E, "Item_Wallet_Small", "Kokiri Wallet"),
        (0x24596E8E, "Item_WeirdEgg", "Weird Egg"),
        (0x6BE5C3B0, "Item_ZeldaLetter", "Zelda's Letter"),
        (0x84BA0D24, "Obj_Armor_Child_Normal", "Kokiri Tunic"),
        (0x51EC97B3, "Obj_Heart_Piece", "Piece of Heart"),
        (0x20820479, "Pouch_Amiibo", "amiibo"),
        (0xE32AD20F, "Pouch_Range_BowAndArrow_Fire", "Bow + Fire Arrow"),
        (0x667C7BA3, "Pouch_Range_BowAndArrow_Ice", "Bow + Ice Arrow"),
        (0x28298287, "Pouch_Range_BowAndArrow_Light", "Bow + Light Arrow"),
        (0x938D56BF, "Weapon_Range_Bow", "Fairy Bow"),
        (0x80D34CE9, "Weapon_Range_SlingShot", "Fairy Slingshot"),
        (0x7CA64F23, "Weapon_Shield_Deku", "Deku Shield"),
        (0x08BEFD3A, "Weapon_Shield_Hylian", "Hylian Shield"),
        (0xF58E0E2F, "Weapon_Shield_Mirror", "Mirror Shield"),
        (0xB0B3E399, "Weapon_Sword_Biggoron", "Biggoron Sword"),
        (0x8D02F5EA, "Weapon_Sword_BrokenGiant", "Broken Giant's Knife"),
        (0x396A5C02, "Weapon_Sword_Giant", "Giant's Knife"),
        (0xEEB495B9, "Weapon_Sword_Kokiri", "Kokiri Sword"),
        (0xF1C45294, "Weapon_Sword_Master", "Master Sword")
    ]
}

private struct SaveReadError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

private struct SaveFields {
    let bytes: Data
    let headerEnd: Int
    let fields: [UInt32: Int]

    init(bytes: Data, headerEnd: Int) throws {
        guard bytes.count >= headerEnd, Self.word(bytes, 0) == 0x01020304,
              Self.word(bytes, 4) == 0x002D80EB, Self.word(bytes, 8) == UInt32(headerEnd) else {
            throw SaveReadError("This file does not match the supported Switch 2 save format.")
        }
        var fields: [UInt32: Int] = [:]
        for offset in stride(from: 40, to: headerEnd, by: 8) {
            let hash = Self.word(bytes, offset)
            guard hash != 0 else { continue }
            guard fields.updateValue(offset + 4, forKey: hash) == nil else {
                throw SaveReadError("This save contains duplicate field records.")
            }
        }
        self.bytes = bytes; self.headerEnd = headerEnd; self.fields = fields
    }

    static func word(_ bytes: Data, _ offset: Int) -> UInt32 {
        UInt32(bytes[offset]) | UInt32(bytes[offset + 1]) << 8 |
            UInt32(bytes[offset + 2]) << 16 | UInt32(bytes[offset + 3]) << 24
    }
    func integer(_ hash: UInt32) throws -> Int {
        guard let offset = fields[hash] else { throw SaveReadError("A required save field is missing.") }
        return Int(Int32(bitPattern: Self.word(bytes, offset)))
    }
    func optionalInteger(_ hash: UInt32) -> Int? {
        fields[hash].map { Int(Int32(bitPattern: Self.word(bytes, $0))) }
    }
    func block(_ hash: UInt32, length: Int) throws -> Int {
        guard let field = fields[hash] else { throw SaveReadError("A required save field is missing.") }
        let offset = Int(Self.word(bytes, field))
        guard length >= 0, offset >= headerEnd, offset <= bytes.count - length else {
            throw SaveReadError("This save contains an invalid data offset.")
        }
        return offset
    }
    func string(_ hash: UInt32, length: Int) throws -> String {
        let offset = try block(hash, length: length)
        let raw = bytes[offset..<(offset + length)].prefix { $0 != 0 }
        guard let text = String(data: Data(raw), encoding: .utf8),
              !text.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else {
            throw SaveReadError("This save contains unsupported text data.")
        }
        return text
    }
    func optionalString(_ hash: UInt32, length: Int) throws -> String? {
        fields[hash] == nil ? nil : try string(hash, length: length)
    }
    func previewJPEG() throws -> Data? {
        guard fields[0x63696A32] != nil else { return nil }
        let offset = try block(0x63696A32, length: 4)
        let length = Int(Self.word(bytes, offset))
        guard length >= 4, length <= 1024 * 1024, length <= bytes.count - offset - 4 else { return nil }
        let start = offset + 4
        guard bytes[start] == 0xFF, bytes[start + 1] == 0xD8,
              bytes[start + length - 2] == 0xFF, bytes[start + length - 1] == 0xD9 else { return nil }
        return Data(bytes[start..<(start + length)])
    }
    func savedDate() -> Date? {
        guard let day = optionalInteger(0xBD46F485), let month = optionalInteger(0xDFD840D3),
              let year = optionalInteger(0x9811A3F7), let hour = optionalInteger(0x23F3D75E),
              let minute = optionalInteger(0x27853BF7), (2000...2200).contains(year),
              (1...12).contains(month), (1...31).contains(day), (0...23).contains(hour), (0...59).contains(minute) else { return nil }
        let calendar = Calendar(identifier: .gregorian)
        let components = DateComponents(year: year, month: month, day: day, hour: hour, minute: minute)
        guard let date = calendar.date(from: components), calendar.component(.day, from: date) == day else { return nil }
        return date
    }
}

private struct SaveFileIdentity {
    let device: dev_t
    let inode: ino_t
    let size: off_t
    let seconds: Int
    let nanoseconds: Int
    init(_ info: stat) {
        device = info.st_dev; inode = info.st_ino; size = info.st_size
        seconds = info.st_mtimespec.tv_sec; nanoseconds = info.st_mtimespec.tv_nsec
    }
    func matches(_ info: stat) -> Bool {
        device == info.st_dev && inode == info.st_ino && size == info.st_size &&
            seconds == info.st_mtimespec.tv_sec && nanoseconds == info.st_mtimespec.tv_nsec &&
            info.st_mode & S_IFMT == S_IFREG
    }
}

/// File descriptors keep every child lookup inside the opened profile, even if a
/// directory is renamed while a human-owned game is saving. Links are never followed.
private final class SaveDirectory {
    let descriptor: Int32
    init(url: URL) throws {
        descriptor = open(url.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw SaveReadError("The profile is unavailable or is a linked folder.") }
    }
    private init(descriptor: Int32) { self.descriptor = descriptor }
    deinit { close(descriptor) }

    func optionalDirectory(_ name: String) throws -> SaveDirectory? {
        let child = openat(descriptor, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        if child >= 0 { return SaveDirectory(descriptor: child) }
        if errno == ENOENT || errno == ENOTDIR {
            var info = stat()
            if fstatat(descriptor, name, &info, AT_SYMLINK_NOFOLLOW) == 0, info.st_mode & S_IFMT == S_IFLNK {
                throw SaveReadError("Linked save folders are not supported.")
            }
            return nil
        }
        throw SaveReadError("A save folder is unavailable or is a symbolic link.")
    }
    func names() throws -> [String] {
        let copy = dup(descriptor)
        guard copy >= 0 else { throw SaveReadError("The save folder could not be inspected.") }
        guard let stream = fdopendir(copy) else { close(copy); throw SaveReadError("The save folder could not be inspected.") }
        defer { closedir(stream) }
        var names: [String] = []
        while let entry = readdir(stream) {
            let name = withUnsafePointer(to: &entry.pointee.d_name) {
                $0.withMemoryRebound(to: CChar.self, capacity: Int(MAXNAMLEN) + 1) { String(cString: $0) }
            }
            guard name != ".", name != ".." else { continue }
            guard names.count < 4096 else { throw SaveReadError("The save folder contains too many files to inspect.") }
            names.append(name)
        }
        return names.sorted()
    }
    func read(_ name: String, budget: Int) throws -> (data: Data, modifiedAt: Date, identity: SaveFileIdentity) {
        let file = openat(descriptor, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard file >= 0 else { throw SaveReadError("\(name) is missing, unreadable, or linked.") }
        let handle = FileHandle(fileDescriptor: file, closeOnDealloc: true)
        defer { try? handle.close() }
        var before = stat()
        guard fstat(file, &before) == 0, before.st_mode & S_IFMT == S_IFREG,
              before.st_flags & 0x4000_0000 == 0 else {
            throw SaveReadError("\(name) must be a downloaded regular file.")
        }
        let limit = min(SaveLibrary.maximumFileBytes, budget)
        guard before.st_size >= 0, before.st_size <= off_t(limit) else {
            throw SaveReadError("The save exceeds the 2 MiB file or 8 MiB profile viewing limit.")
        }
        let data = try handle.read(upToCount: limit + 1) ?? Data()
        let identity = SaveFileIdentity(before)
        var after = stat()
        guard off_t(data.count) == before.st_size, fstat(file, &after) == 0, identity.matches(after) else {
            throw SaveReadError("The game changed this save while it was read. Refresh to try again.")
        }
        try verify(name, matches: identity)
        return (data, Date(timeIntervalSince1970: Double(before.st_mtimespec.tv_sec)), identity)
    }
    func verify(_ name: String, matches identity: SaveFileIdentity) throws {
        var info = stat()
        guard fstatat(descriptor, name, &info, AT_SYMLINK_NOFOLLOW) == 0, identity.matches(info) else {
            throw SaveReadError("The game changed this save while it was read. Refresh to try again.")
        }
    }
}
