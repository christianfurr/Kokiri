"""Synthetic Switch-2-shaped save fixtures only; never opens an installed profile."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from save_workshop import Workshop, WorkshopError
from save_workshop import workshop as implementation


class SaveWorkshopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = next((str(Path(p).resolve()) for p in implementation.NODE_CANDIDATES if os.path.isfile(p) and os.access(p, os.X_OK)), None)
        if cls.node is None:
            raise unittest.SkipTest("A local Node executable is required for the synthetic domain tests")
        script = "const d=require(" + json.dumps(str(implementation.MODULE / "domain.cjs")) + ");process.stdout.write(JSON.stringify(d));"
        cls.constants = json.loads(subprocess.run([cls.node, "-e", script], capture_output=True, check=True, timeout=2).stdout)
        cls.catalog = json.loads((implementation.MODULE / "catalog.json").read_text())

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.profile = self.root / "profile"
        self.account = self.profile / "save" / "synthetic-account"
        self.slot = self.account / "slot_00"
        self.slot.mkdir(parents=True)
        self.state = self.root / "state"
        self.state.mkdir()
        self.running = False
        self.workshop = Workshop(self.profile, self.state, lambda: not self.running)
        self._fixture()

    def _fixture(self):
        d = self.constants
        scalars = {row[0] for row in self.catalog["fields"]}
        scalars.update(row[0] for row in self.catalog["inventory"])
        for stocks, acquired, related, *_ in self.catalog["registrations"]:
            scalars.update(stocks)
            scalars.update(x for x in (acquired, related) if x)
        scalars.update(d["key"].values())
        scalars.update(w["stock"] for w in d["wallets"])
        for group in d["capacityGroups"]:
            scalars.add(group["hash"])
            scalars.update(row[1] for row in group["tiers"])
        scalars.update(row["stock"] for row in d["quantityFields"])
        scalars.update(x for row in d["bottleSlots"] for x in row)
        scalars.update(row["progress"] for row in d["vitalsFields"])
        scalars.update([0xCEA220D3, 0x1EA93BD8, 0xA4AEE8CD])
        scalars.update(hash for groups in d["worldSongs"].values() for group in groups for hash in group)
        blocks = {d["key"]["wallet"]: 64, **{x: 64 for x in d["equippedItemFields"]}}
        blocks.update({0x1D6189DA: 64, 0x4A6BDB7D: 32, 0xC884818D: 12, 0x960AD56A: 12, 0x8773F02D: 12})
        blocks.update({row["nameHash"]: 64 for row in d["capacityGroups"] if "nameHash" in row})
        progress, offsets = self._save(0x175D8, scalars, blocks)
        self.offsets = offsets
        for wallet in d["wallets"]:
            self._put(progress, offsets[wallet["stock"]], int(wallet == d["wallets"][0]))
        self._put(progress, offsets[d["key"]["limit"]], 200)
        self._put(progress, offsets[d["key"]["rupees"]], 10)
        wallet = d["key"]["wallet"]
        pointer = struct.unpack_from("<I", progress, offsets[wallet])[0]
        text = b"Item_Wallet_Small"
        progress[pointer:pointer + len(text)] = text
        for row in d["vitalsFields"]:
            self._put(progress, offsets[row["progress"]], 12 if row["id"] in {"hearts", "maxHearts"} else 0)
        for _, _, content in d["bottleSlots"]:
            self._put(progress, offsets[content], d["emptyBottle"])
        caption_fields = {d["key"]["previewRupees"], *[row["caption"] for row in d["vitalsFields"]]}
        caption, caption_offsets = self._save(0x2A0, caption_fields, {0xF74E0E8E: 64, 0x0CCCC6CD: 64})
        for row in d["vitalsFields"]:
            self._put(caption, caption_offsets[row["caption"]], 12 if row["id"] in {"hearts", "maxHearts"} else 0)
        self._put(caption, caption_offsets[d["key"]["previewRupees"]], 10)
        (self.slot / "progress.sav").write_bytes(progress)
        (self.slot / "caption.sav").write_bytes(caption)
        (self.account / "untouched.txt").write_bytes(b"preserve unknown account file\n")

    @staticmethod
    def _put(data, offset, value):
        struct.pack_into("<I", data, offset, value)

    def _save(self, header, fields, blocks):
        fields = sorted(set(fields) | set(blocks))
        data = bytearray(header + sum(blocks.values()))
        struct.pack_into("<III", data, 0, 0x01020304, 0x002D80EB, header)
        offsets, cursor = {}, header
        for index, field in enumerate(fields):
            offset = 40 + index * 8
            self.assertLess(offset + 7, header)
            self._put(data, offset, field)
            offsets[field] = offset + 4
            if field in blocks:
                self._put(data, offset + 4, cursor)
                cursor += blocks[field]
        return data, offsets

    def hashes(self):
        return {str(p.relative_to(self.account)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.account.rglob("*") if p.is_file()}

    def test_snapshot_plan_atomic_apply_idempotency_and_restore(self):
        original = self.hashes()
        snapshot = self.workshop.snapshot(0)
        self.assertEqual(snapshot["state"]["rupees"], 10)
        plan = self.workshop.plan(0, {"rupees": 150, "max_hearts": 5, "hearts": 4.5, "ammo": {"bombs": 10},
                                      "equipment": {"add": ["Weapon_Range_Bow"]}}, snapshot["snapshot_id"])
        self.assertEqual(self.hashes(), original)
        self.assertTrue(any(row["field"] == "rupees" and row["after"] == 150 for row in plan["diff"]))
        receipt = self.workshop.apply(plan["plan_id"])
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(receipt["backup_snapshot_id"], snapshot["snapshot_id"])
        current = self.hashes()
        self.assertNotEqual(current, original)
        self.assertEqual(current["untouched.txt"], original["untouched.txt"])
        after = self.workshop.snapshot(0)["state"]
        self.assertEqual((after["rupees"], after["hearts"], after["ammo"]["bombs"]), (150, 4.5, 10))
        self.assertEqual(after["inventory"]["Weapon_Range_Bow"], 1)
        again = self.workshop.apply(plan["plan_id"])
        self.assertTrue(again["already_applied"])
        self.assertEqual(self.hashes(), current)
        self.workshop.restore(snapshot["snapshot_id"])
        self.assertEqual(self.hashes(), original)
        self.assertTrue(self.workshop.restore(snapshot["snapshot_id"])["already_restored"])

    def test_stale_snapshot_and_plan_do_not_overwrite_changes(self):
        snapshot = self.workshop.snapshot(0)
        plan = self.workshop.plan(0, {"rupees": 50}, snapshot["snapshot_id"])
        (self.account / "untouched.txt").write_text("changed independently")
        changed = self.hashes()
        with self.assertRaises(WorkshopError):
            self.workshop.plan(0, {"rupees": 60}, snapshot["snapshot_id"])
        with self.assertRaises(WorkshopError):
            self.workshop.apply(plan["plan_id"])
        self.assertEqual(changed, self.hashes())

    def test_commit_failure_rolls_back_whole_account(self):
        snapshot = self.workshop.snapshot(0)
        plan = self.workshop.plan(0, {"rupees": 60}, snapshot["snapshot_id"])
        original = self.hashes()
        with patch.object(self.workshop, "_receipt", side_effect=OSError("synthetic receipt failure")):
            with self.assertRaises(OSError):
                self.workshop.apply(plan["plan_id"])
        self.assertEqual(self.hashes(), original)
        self.assertEqual(self.workshop.apply(plan["plan_id"])["status"], "applied")

    def test_source_is_revalidated_immediately_before_swap(self):
        snapshot = self.workshop.snapshot(0)
        plan = self.workshop.plan(0, {"rupees": 60}, snapshot["snapshot_id"])
        original = (self.slot / "progress.sav").read_bytes()
        commit = self.workshop._commit
        def interfere(*args):
            (self.account / "untouched.txt").write_text("concurrent writer")
            return commit(*args)
        with patch.object(self.workshop, "_commit", side_effect=interfere):
            with self.assertRaises(WorkshopError):
                self.workshop.apply(plan["plan_id"])
        self.assertEqual((self.slot / "progress.sav").read_bytes(), original)
        self.assertEqual((self.account / "untouched.txt").read_text(), "concurrent writer")

    def test_running_session_and_invalid_slot_are_rejected(self):
        snapshot = self.workshop.snapshot(0)
        plan = self.workshop.plan(0, {"rupees": 60}, snapshot["snapshot_id"])
        self.running = True
        for operation in (lambda: self.workshop.snapshot(0), lambda: self.workshop.plan(0, {"rupees": 1}, snapshot["snapshot_id"]),
                          lambda: self.workshop.apply(plan["plan_id"]), lambda: self.workshop.restore(snapshot["snapshot_id"])):
            with self.assertRaises(WorkshopError):
                operation()
        self.running = False
        for slot in (True, -1, 6, "0"):
            with self.assertRaises(WorkshopError):
                self.workshop.snapshot(slot)

    def test_symlinks_hardlinks_and_unsupported_entries_are_rejected(self):
        for kind in ("symlink", "hardlink", "fifo"):
            with self.subTest(kind=kind):
                target = self.account / "unsafe"
                if kind == "symlink":
                    target.symlink_to(self.slot / "progress.sav")
                elif kind == "hardlink":
                    os.link(self.slot / "progress.sav", target)
                else:
                    os.mkfifo(target)
                try:
                    with self.assertRaises(WorkshopError):
                        self.workshop.snapshot(0)
                finally:
                    target.unlink()

    def test_unsupported_fields_ranges_and_equipped_removal_are_rejected(self):
        snapshot = self.workshop.snapshot(0)
        for changes in ({"offset": 123}, {"rupees": -1}, {"rupees": 201}, {"hearts": 3.1}, {"max_hearts": 21},
                        {"ammo": {"bombs": 9999}}, {"inventory": {"add": ["unknown"]}}, {"progression": {"0x1234": True}},
                        {"equipment": {"equipped": "Weapon_Range_Bow"}}, {"rupees": None}, {"rupees": True}, {"hearts": True}, {"hearts": "2"}):
            with self.subTest(changes=changes), self.assertRaises(WorkshopError):
                self.workshop.plan(0, changes, snapshot["snapshot_id"])
        data = bytearray((self.slot / "progress.sav").read_bytes())
        bow = next(row[0] for row in self.catalog["inventory"] if row[1] == "Weapon_Range_Bow")
        self._put(data, self.offsets[bow], 1)
        field = self.constants["equippedItemFields"][0]
        at = struct.unpack_from("<I", data, self.offsets[field])[0]
        data[at:at + len(b"Weapon_Range_Bow")] = b"Weapon_Range_Bow"
        (self.slot / "progress.sav").write_bytes(data)
        snapshot = self.workshop.snapshot(0)
        with self.assertRaisesRegex(WorkshopError, "Unequip"):
            self.workshop.plan(0, {"equipment": {"remove": ["Weapon_Range_Bow"]}}, snapshot["snapshot_id"])

    def test_progression_allowlist_and_private_lock(self):
        snapshot = self.workshop.snapshot(0)
        flag = self.catalog["fields"][0][2]
        plan = self.workshop.plan(0, {"progression": {flag: True}}, snapshot["snapshot_id"])
        self.workshop.apply(plan["plan_id"])
        self.assertIs(self.workshop.snapshot(0)["state"]["progression"][flag], True)
        with (self.state / "workshop.lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(WorkshopError, "Another save transaction"):
                self.workshop.snapshot(0)

    def test_checkpoint_and_song_changes_use_existing_domain_rules(self):
        snapshot = self.workshop.snapshot(0)
        plan = self.workshop.plan(0, {"destination": "kokiri", "learn_songs": ["epona"]}, snapshot["snapshot_id"])
        self.assertTrue(any(row["field"] == "checkpoint.map" and row["after"] == "KokiriForest_Adult" for row in plan["diff"]))
        self.workshop.apply(plan["plan_id"])
        after = self.workshop.snapshot(0)["state"]
        self.assertTrue(after["songs"]["epona"])
        self.assertEqual(after["inventory"]["Item_Ocarina_Fairy"], 1)

    def test_receipt_written_then_failed_is_removed_on_rollback(self):
        snapshot = self.workshop.snapshot(0)
        plan = self.workshop.plan(0, {"rupees": 80}, snapshot["snapshot_id"])
        original = self.hashes()
        write = self.workshop._receipt
        def fail_after_write(*args):
            write(*args)
            raise OSError("synthetic directory sync failure")
        with patch.object(self.workshop, "_receipt", side_effect=fail_after_write):
            with self.assertRaises(OSError):
                self.workshop.apply(plan["plan_id"])
        self.assertEqual(self.hashes(), original)
        self.assertFalse((self.state / "receipts" / (plan["plan_id"] + ".json")).exists())
        self.assertFalse(self.workshop.apply(plan["plan_id"])["already_applied"])

    def test_interrupted_rollback_keeps_old_account_and_recovers_idempotently(self):
        snapshot = self.workshop.snapshot(0)
        plan = self.workshop.plan(0, {"rupees": 80}, snapshot["snapshot_id"])
        original = self.hashes()
        swap = implementation._swap
        calls = 0
        def interrupt_rollback(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic rollback interruption")
            swap(*args)
        with patch.object(implementation, "_swap", side_effect=interrupt_rollback), patch.object(self.workshop, "_receipt", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                self.workshop.apply(plan["plan_id"])
        self.assertNotEqual(self.hashes(), original)
        self.assertEqual(len(list(self.account.parent.glob(".kokiri-save-*"))), 1)
        recovered = self.workshop.apply(plan["plan_id"])
        self.assertTrue(recovered["recovered_commit"])
        self.assertTrue(recovered["already_applied"])
        self.assertEqual(list(self.account.parent.glob(".kokiri-save-*")), [])
        self.workshop.restore(snapshot["snapshot_id"])
        self.assertEqual(self.hashes(), original)


if __name__ == "__main__":
    unittest.main()
