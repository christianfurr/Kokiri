"""Typed save plans with copied snapshots and atomic account-directory replacement.

The owning session manager supplies profile/state paths and stopped_check under
its session lease. This module never discovers or adopts a player's profile.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Callable
import uuid


class WorkshopError(ValueError):
    pass


MAX_FILE = 2 << 20
MAX_ACCOUNT = 8 << 20
MAX_ENTRIES = 256
MODULE = Path(__file__).resolve().parent
NODE_CANDIDATES = ("/opt/homebrew/opt/node@22/bin/node", "/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node")


def _encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise WorkshopError("Choose an identifier returned by this workshop.")
    return value


def _directory(path: Path) -> Path:
    path = path.expanduser().absolute()
    if ".." in path.parts:
        raise WorkshopError("A workshop path contains traversal.")
    for component in (path, *path.parents):
        if component.is_symlink() and str(component) not in {"/var", "/tmp"}:
            raise WorkshopError("Workshop directories must not contain symlinks.")
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise WorkshopError("Expected a same-user workshop directory.")
    return path


def _read(path: Path, limit: int = MAX_FILE) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > limit:
            raise WorkshopError("Expected a bounded same-user file without links.")
        value = file.read(limit + 1)
        after = os.fstat(file.fileno())
        if len(value) > limit or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise WorkshopError("A workshop file changed while it was read.")
        return value


def _manifest(root: Path) -> dict:
    root = _directory(root)
    result = {}
    total = 0
    pending = [root]
    while pending:
        folder = pending.pop()
        for path in sorted(folder.iterdir()):
            name = path.relative_to(root).as_posix()
            info = path.lstat()
            if info.st_uid != os.getuid() or stat.S_ISLNK(info.st_mode):
                raise WorkshopError("A save account contains an unowned or linked entry.")
            if stat.S_ISDIR(info.st_mode):
                result[name] = {"type": "directory"}
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                data = _read(path)
                total += len(data)
                result[name] = {"type": "file", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            else:
                raise WorkshopError("A save account contains an unsupported entry.")
            if len(result) > MAX_ENTRIES or total > MAX_ACCOUNT:
                raise WorkshopError("The save account exceeds its bounded size.")
    return result


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(_encoded(value)); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _swap(first: Path, second: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = library.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(-2, os.fsencode(first), -2, os.fsencode(second), 2)  # AT_FDCWD, RENAME_SWAP
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        function = library.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(-100, os.fsencode(first), -100, os.fsencode(second), 2)  # RENAME_EXCHANGE
    else:
        raise WorkshopError("This filesystem has no supported atomic directory swap.")
    if result:
        raise OSError(ctypes.get_errno(), "Atomic save-account swap failed")


class Workshop:
    def __init__(self, profile: Path, state_dir: Path, stopped_check: Callable[[], bool]):
        if not callable(stopped_check):
            raise WorkshopError("A stopped-session check is required.")
        self.profile = _directory(profile)
        # The manager creates this private state root; never create arbitrary external roots here.
        self.state_dir = _directory(state_dir)
        if self.state_dir == self.profile or self.profile in self.state_dir.parents or self.state_dir in self.profile.parents:
            raise WorkshopError("Workshop state must be separate from its profile.")
        self.stopped_check = stopped_check
        self.node = next((Path(path).resolve() for path in NODE_CANDIDATES if os.path.isfile(path) and os.access(path, os.X_OK)), None)
        if self.node is None:
            raise WorkshopError("A supported local Node executable is unavailable.")

    def _stopped(self):
        if self.stopped_check() is not True:
            raise WorkshopError("Save operations require the owned test session to be stopped.")

    @contextmanager
    def _locked(self):
        self._stopped()
        _directory(self.profile); _directory(self.state_dir)
        fd = os.open(self.state_dir / "workshop.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise WorkshopError("The workshop lock is invalid.")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise WorkshopError("Another save transaction owns this workshop.") from error
            self._stopped()
            for name in ("snapshots", "plans", "receipts", "journals"):
                path = self.state_dir / name
                path.mkdir(mode=0o700, exist_ok=True)
                _directory(path)
            yield
        finally:
            os.close(fd)

    def _account(self, slot: int) -> Path:
        if not isinstance(slot, int) or isinstance(slot, bool) or slot not in range(6):
            raise WorkshopError("Choose a save slot from 0 through 5.")
        root = _directory(self.profile / "save")
        candidates = []
        for folder in root.iterdir():
            if folder.name.startswith(".kokiri-save-"):
                continue  # A crash can retain the pre-swap account; it is never a live account.
            if folder.is_symlink():
                raise WorkshopError("Linked save accounts are not supported.")
            if folder.is_dir() and (folder / f"slot_{slot:02d}" / "progress.sav").exists():
                candidates.append(_directory(folder))
        if len(candidates) != 1:
            raise WorkshopError("The selected slot must belong to exactly one save account.")
        _directory(candidates[0] / f"slot_{slot:02d}")
        return candidates[0]

    def _read_json(self, path: Path) -> dict:
        try:
            value = json.loads(_read(path, 8 << 20))
        except (ValueError, UnicodeError) as error:
            raise WorkshopError("The workshop receipt is invalid.") from error
        if not isinstance(value, dict):
            raise WorkshopError("Expected a workshop receipt object.")
        return value

    def _node(self, operation: str, account: Path, slot: int, changes: dict | None = None) -> dict:
        folder = account / f"slot_{slot:02d}"
        request = {"operation": operation,
                   "progress": base64.b64encode(_read(folder / "progress.sav")).decode(),
                   "caption": base64.b64encode(_read(folder / "caption.sav")).decode()}
        if changes is not None:
            request["changes"] = changes
        wire = _encoded(request)
        if len(wire) > 6 << 20:
            raise WorkshopError("The save request exceeds its bounded size.")
        try:
            process = subprocess.run([str(self.node), "--no-addons", "--disallow-code-generation-from-strings", str(MODULE / "cli.cjs")],
                                     input=wire, capture_output=True, timeout=3, env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())})
            if len(process.stdout) > 6 << 20:
                raise WorkshopError("The save parser returned too much data.")
            result = json.loads(process.stdout)
        except (ValueError, subprocess.SubprocessError) as error:
            raise WorkshopError("The bounded save parser could not complete.") from error
        if process.returncode or result.get("ok") is not True:
            raise WorkshopError(str(result.get("error", "The save parser rejected this request.")))
        return result

    def _snapshot(self, slot: int, account: Path) -> dict:
        before = _manifest(account)
        body = {"version": 1, "profile": str(self.profile), "account": account.name, "slot": slot, "manifest": before}
        identifier = _digest(body)
        destination = self.state_dir / "snapshots" / identifier
        if not destination.exists():
            staging = destination.with_name("." + identifier + "-" + uuid.uuid4().hex)
            staging.mkdir(mode=0o700)
            try:
                shutil.copytree(account, staging / "account", symlinks=True)
                if _manifest(staging / "account") != before or _manifest(account) != before:
                    raise WorkshopError("The save account changed while its snapshot was copied.")
                _write_json(staging / "snapshot.json", body)
                os.rename(staging, destination)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        else:
            self._snapshot_record(identifier)
        return {"snapshot_id": identifier, "slot": slot, "files": before}

    def _snapshot_record(self, snapshot_id: str) -> tuple[dict, Path]:
        identifier = _identifier(snapshot_id)
        folder = _directory(self.state_dir / "snapshots" / identifier)
        body = self._read_json(folder / "snapshot.json")
        if _digest(body) != identifier or body.get("profile") != str(self.profile) or body.get("version") != 1:
            raise WorkshopError("This snapshot does not belong to this profile.")
        if _manifest(folder / "account") != body["manifest"]:
            raise WorkshopError("The copied snapshot no longer matches its receipt.")
        return body, folder / "account"

    def snapshot(self, slot: int) -> dict:
        with self._locked():
            account = self._account(slot)
            result = self._snapshot(slot, account)
            parsed = self._node("inspect", account, slot)
            if _manifest(account) != result["files"]:
                raise WorkshopError("The save account changed during inspection.")
            self._stopped()
            return {**result, "state": parsed["state"], "supported": parsed["supported"]}

    def plan(self, slot: int, changes: dict, expected_snapshot: str) -> dict:
        with self._locked():
            account = self._account(slot)
            snapshot, _ = self._snapshot_record(expected_snapshot)
            if snapshot["slot"] != slot or snapshot["account"] != account.name or _manifest(account) != snapshot["manifest"]:
                raise WorkshopError("The save changed. Take a fresh snapshot before planning.")
            if not isinstance(changes, dict) or len(_encoded(changes)) > 64 << 10:
                raise WorkshopError("Expected a bounded typed changes object.")
            result = self._node("plan", account, slot, changes)
            self._stopped()
            if _manifest(account) != snapshot["manifest"]:
                raise WorkshopError("The save changed during planning.")
            replacements = {}
            for name, value in result["replacements"].items():
                if name not in {"progress.sav", "caption.sav"}:
                    raise WorkshopError("The parser returned an unsupported save path.")
                data = base64.b64decode(value, validate=True)
                original = _read(account / f"slot_{slot:02d}" / name)
                if len(data) != len(original) or data[:12] != original[:12]:
                    raise WorkshopError("The parser returned an invalid replacement.")
                replacements[name] = value
            body = {"version": 1, "profile": str(self.profile), "account": account.name, "slot": slot,
                    "snapshot_id": expected_snapshot, "changes": changes, "diff": result["diff"], "before": result["before"],
                    "after": result["after"], "replacements": replacements}
            identifier = _digest(body)
            path = self.state_dir / "plans" / (identifier + ".json")
            if path.exists():
                if self._read_json(path) != body:
                    raise WorkshopError("A conflicting plan already exists.")
            else:
                _write_json(path, body)
            return {"plan_id": identifier, "snapshot_id": expected_snapshot, "slot": slot, "diff": result["diff"],
                    "before": result["before"], "after": result["after"]}

    def _receipt(self, operation_id: str, receipt: dict):
        _write_json(self.state_dir / "receipts" / (operation_id + ".json"), receipt)

    def _commit(self, account: Path, staged: Path, expected: dict, operation_id: str, backup_id: str) -> dict:
        after = _manifest(staged)
        receipt = {"operation_id": operation_id, "profile": str(self.profile), "account": account.name,
                   "before": expected, "after": after, "backup_snapshot_id": backup_id,
                   "staging_name": staged.name, "status": "applied"}
        journal = self.state_dir / "journals" / (operation_id + ".json")
        _write_json(journal, receipt)
        swapped = False
        try:
            self._stopped()
            if _manifest(account) != expected:
                raise WorkshopError("The save changed before commit; nothing was replaced.")
            _swap(staged, account)
            swapped = True
            self._receipt(operation_id, receipt)
        except BaseException:
            if swapped:
                # If rollback itself fails, keep the journal and the old staged
                # account. Never erase the remaining original during cleanup.
                _swap(staged, account)
                (self.state_dir / "receipts" / (operation_id + ".json")).unlink(missing_ok=True)
            journal.unlink(missing_ok=True)
            raise
        journal.unlink(missing_ok=True)
        return {**receipt, "already_applied": False}

    def apply(self, plan_id: str) -> dict:
        identifier = _identifier(plan_id)
        with self._locked():
            body = self._read_json(self.state_dir / "plans" / (identifier + ".json"))
            if _digest(body) != identifier or body.get("profile") != str(self.profile) or body.get("version") != 1:
                raise WorkshopError("This plan does not belong to this workshop.")
            account = self._account(body["slot"])
            if account.name != body["account"]:
                raise WorkshopError("The save account identity changed.")
            receipt_path = self.state_dir / "receipts" / (identifier + ".json")
            if receipt_path.exists():
                receipt = self._read_json(receipt_path)
                if receipt.get("operation_id") != identifier or receipt.get("profile") != str(self.profile) or receipt.get("account") != account.name:
                    raise WorkshopError("The completed plan receipt has a different identity.")
                return {**receipt, "already_applied": True, "current_matches": _manifest(account) == receipt["after"]}
            snapshot, source = self._snapshot_record(body["snapshot_id"])
            journal = self.state_dir / "journals" / (identifier + ".json")
            if journal.exists():
                receipt = self._read_json(journal)
                if receipt.get("operation_id") != identifier or receipt.get("profile") != str(self.profile) or receipt.get("account") != account.name:
                    raise WorkshopError("The recovery journal has a different identity.")
                if _manifest(account) == receipt["after"]:
                    self._receipt(identifier, receipt); journal.unlink()
                    old_name = receipt.get("staging_name", "")
                    if isinstance(old_name, str) and re.fullmatch(r"\.kokiri-save-[0-9a-f]{32}", old_name):
                        old = account.with_name(old_name)
                        if old.exists() and _manifest(old) == receipt["before"]:
                            shutil.rmtree(old)
                    return {**receipt, "already_applied": True, "recovered_commit": True}
            if _manifest(account) != snapshot["manifest"]:
                raise WorkshopError("The save changed after planning; take a fresh snapshot.")
            staged = account.with_name(".kokiri-save-" + uuid.uuid4().hex)
            try:
                shutil.copytree(source, staged, symlinks=True)
                if not isinstance(body.get("replacements"),dict) or not body["replacements"] or not set(body["replacements"]).issubset({"progress.sav","caption.sav"}):
                    raise WorkshopError("This plan contains an unsupported replacement filename.")
                for name, value in body["replacements"].items():
                    destination = staged / f"slot_{body['slot']:02d}" / name
                    edited=base64.b64decode(value, validate=True)
                    original=_read(source / f"slot_{body['slot']:02d}" / name)
                    if len(edited)>MAX_FILE or len(edited)!=len(original) or edited[:12]!=original[:12]:
                        raise WorkshopError("This plan contains an invalid replacement save.")
                    destination.write_bytes(edited)
                return self._commit(account, staged, snapshot["manifest"], identifier, body["snapshot_id"])
            finally:
                if staged.exists() and not journal.exists():
                    shutil.rmtree(staged)

    def restore(self, snapshot_id: str) -> dict:
        with self._locked():
            body, source = self._snapshot_record(snapshot_id)
            account = self._account(body["slot"])
            if account.name != body["account"]:
                raise WorkshopError("The save account identity changed.")
            current = _manifest(account)
            if current == body["manifest"]:
                return {"status": "unchanged", "snapshot_id": snapshot_id, "already_restored": True}
            backup = self._snapshot(body["slot"], account)
            identifier = _digest({"restore": snapshot_id, "before": current, "profile": str(self.profile)})
            staged = account.with_name(".kokiri-save-" + uuid.uuid4().hex)
            try:
                shutil.copytree(source, staged, symlinks=True)
                return {**self._commit(account, staged, current, identifier, backup["snapshot_id"]), "restored_snapshot_id": snapshot_id}
            finally:
                if staged.exists() and not (self.state_dir / "journals" / (identifier + ".json")).exists():
                    shutil.rmtree(staged)
