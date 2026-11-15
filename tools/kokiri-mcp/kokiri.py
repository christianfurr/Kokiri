"""Bounded local observation of Kokiri sessions. No network transport or player controls."""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import plistlib
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid
import zlib


class KokiriError(ValueError):
    pass


MAX_TAIL = 256 << 10
MAX_JSON = 64 << 10
LOG_FILES = {"game": "game-full.log", "timings": "timings.tsv",
             "presented": "timings.tsv.presented.tsv", "status": "status.jsonl",
             "process": "process.jsonl", "events": "events.jsonl"}


def checked_directory(path: Path) -> Path:
    """Normalize system aliases, then refuse symlinks in the actual path chain."""
    path = path.expanduser().absolute()
    if ".." in path.parts:
        raise KokiriError("A managed directory must not contain traversal components.")
    for part in [path, *path.parents]:
        if part.is_symlink() and str(part) not in {"/var", "/tmp"}:
            raise KokiriError("A managed directory must not pass through a symbolic link.")
    path = path.resolve(strict=True)
    if any(ch in str(path) for ch in "\r\n\0"):
        raise KokiriError("A managed path contains unsupported characters.")
    for part in [path, *path.parents]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise KokiriError("A managed directory has an unsupported path component.")
    if path.stat().st_uid != os.getuid():
        raise KokiriError("The managed directory belongs to a different user.")
    return path


def open_relative(root: Path, name: str, flags: int = os.O_RDONLY) -> int:
    parts = Path(name).parts
    if not parts or Path(name).is_absolute() or any(p in {".", ".."} for p in parts):
        raise KokiriError("Expected a contained relative file name.")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            os.close(directory)
            directory = child
        # Reject FIFOs/devices before reading or writing: opening a FIFO without
        # NONBLOCK can wait forever before the regular-file check below runs.
        descriptor = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=directory)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            os.close(descriptor)
            raise KokiriError("Expected a same-user regular file.")
        return descriptor
    finally:
        os.close(directory)


def bounded_bytes(root: Path, name: str, limit: int) -> bytes:
    descriptor = open_relative(root, name)
    with os.fdopen(descriptor, "rb") as stream:
        if os.fstat(stream.fileno()).st_size > limit:
            raise KokiriError("The managed file exceeds its size limit.")
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise KokiriError("The managed file grew beyond its size limit.")
    return value


def json_file(root: Path, name: str) -> dict:
    try:
        value = json.loads(bounded_bytes(root, name, MAX_JSON))
    except (ValueError, UnicodeError) as error:
        raise KokiriError("The managed metadata is not readable JSON.") from error
    if not isinstance(value, dict):
        raise KokiriError("Expected a managed metadata object.")
    return value


def tail(root: Path, name: str, lines: int = 80, limit: int = MAX_TAIL) -> list[str]:
    if not 1 <= lines <= 200:
        raise KokiriError("Choose between 1 and 200 log lines.")
    try:
        descriptor = open_relative(root, name)
    except FileNotFoundError:
        return []
    with os.fdopen(descriptor, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        offset = max(0, size - limit)
        stream.seek(offset)
        data = stream.read(limit)
    if offset:
        data = data.partition(b"\n")[2]
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def complete_png(data: bytes) -> bool:
    """Wait for asynchronous image writes; reject malformed completed chunks."""
    signature = b"\x89PNG\r\n\x1a\n"
    if len(data) < len(signature):
        return False
    if not data.startswith(signature):
        raise KokiriError("The capture did not produce a PNG.")
    offset = len(signature)
    first = True
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        if length > 8 << 20:
            raise KokiriError("The PNG chunk exceeded its size limit.")
        end = offset + 12 + length
        if end > len(data):
            return False
        kind = data[offset+4:offset+8]
        if first and (kind != b"IHDR" or length != 13):
            raise KokiriError("The PNG header is invalid.")
        first = False
        expected = struct.unpack_from(">I", data, end-4)[0]
        if zlib.crc32(memoryview(data)[offset+4:end-4]) != expected:
            raise KokiriError("The PNG chunk checksum is invalid.")
        if kind == b"IEND":
            if length or end != len(data):
                raise KokiriError("The PNG ending is invalid.")
            return True
        offset = end
    return False


class ProcessReader:
    def __init__(self):
        self.library = None
        if sys.platform == "darwin":
            self.library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            self.library.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
            self.library.proc_pid_rusage.restype = ctypes.c_int
            self.library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
            self.library.proc_pidpath.restype = ctypes.c_int

    def sample(self, pid: int) -> dict | None:
        if not self.library or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
            return None
        # RUSAGE_INFO_V4 starts with UUID, user/system/wakeup/pagein/wired/RSS,
        # physical footprint and process-start abstime. A generous destination
        # safely accommodates the complete fixed SDK v4 structure.
        usage = ctypes.create_string_buffer(4096)
        path = ctypes.create_string_buffer(4096)
        if self.library.proc_pid_rusage(pid, 4, usage) or self.library.proc_pidpath(pid, path, len(path)) <= 0:
            return None
        return {"pid": pid, "executable": os.fsdecode(path.value),
                "process_start": struct.unpack_from("=Q", usage, 80)[0],
                "process_uuid": bytes(usage.raw[:16]).hex(),
                "physical_footprint_bytes": struct.unpack_from("=Q", usage, 72)[0],
                "resident_bytes": struct.unpack_from("=Q", usage, 64)[0]}

    def game_running(self) -> bool:
        if sys.platform != "darwin":
            return False
        for name in ("KokiriGame", "OcarinaOfTime", "TOTK", "BotW", "Bananza", "Pokopia", "oot-native.*", "totk-native.*"):
            if subprocess.run(["/usr/bin/pgrep", "-x", name], capture_output=True, timeout=3).returncode == 0:
                return True
        return False

    def windows(self, pid: int) -> list[int]:
        """Public CoreGraphics window metadata only; no image is captured here."""
        if sys.platform != "darwin":
            return []
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        cf.CFPropertyListCreateData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_ulong, ctypes.c_void_p]
        cf.CFPropertyListCreateData.restype = ctypes.c_void_p
        cf.CFDataGetLength.argtypes = [ctypes.c_void_p]; cf.CFDataGetLength.restype = ctypes.c_long
        cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]; cf.CFDataGetBytePtr.restype = ctypes.c_void_p
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        rows = cg.CGWindowListCopyWindowInfo(1 | 16, 0)
        if not rows:
            return []
        data = None
        try:
            data = cf.CFPropertyListCreateData(None, rows, 100, 0, None)
            if not data:
                return []
            size = cf.CFDataGetLength(data)
            if not 0 < size <= 4 << 20:
                raise KokiriError("Window metadata exceeded its bound.")
            values = plistlib.loads(ctypes.string_at(cf.CFDataGetBytePtr(data), size))
            return [row["kCGWindowNumber"] for row in values[:4096]
                    if row.get("kCGWindowOwnerPID") == pid and row.get("kCGWindowLayer") == 0
                    and isinstance(row.get("kCGWindowNumber"), int)]
        finally:
            if data:
                cf.CFRelease(data)
            cf.CFRelease(rows)


class SessionStore:
    def __init__(self, support: Path | None = None, observe_roots: list[Path] | None = None,
                 process_reader: ProcessReader | None = None):
        self.support = (support or Path.home()/"Library/Application Support/Kokiri").expanduser().absolute()
        self.sessions_root = self.support/"Sessions"
        self.development = self.support/"Development"
        self.observe_roots = [checked_directory(p) for p in (observe_roots or [])]
        self.process = process_reader or ProcessReader()
        self.commands: dict[str, float] = {}
        self.capture_lock = threading.Lock()

    def managed_directory(self, path: Path) -> Path:
        path = path.expanduser().absolute()
        if ".." in path.parts or any(c in str(path) for c in "\r\n\0"):
            raise KokiriError("Expected a contained managed directory.")
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in path.parts[1:]:
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
                except FileNotFoundError:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
                os.close(descriptor); descriptor = child
            if os.fstat(descriptor).st_uid != os.getuid():
                raise KokiriError("The managed directory belongs to another user.")
        finally:
            os.close(descriptor)
        return path

    @staticmethod
    def session_id(folder: Path) -> str:
        return hashlib.sha256(os.fsencode(folder)).hexdigest()[:20]

    def candidates(self) -> list[Path]:
        roots = [self.sessions_root, *self.observe_roots]
        result = set()
        for root in roots:
            if not root.exists():
                continue
            try:
                root = checked_directory(root)
                if (root/"session.json").is_file():
                    result.add(root)
                    continue
                with os.scandir(root) as entries:
                    for index, entry in enumerate(entries):
                        if index >= 1024:
                            break
                        if entry.is_dir(follow_symlinks=False):
                            result.add(checked_directory(Path(entry.path)))
            except (OSError, KokiriError):
                continue
        return sorted(result, key=lambda p: p.name, reverse=True)[:128]

    def entry(self, session_id: str) -> tuple[Path, dict]:
        if not isinstance(session_id, str) or len(session_id) != 20 or not all(c in "0123456789abcdef" for c in session_id):
            raise KokiriError("Choose a session ID returned by sessions_list.")
        for folder in self.candidates():
            if self.session_id(folder) == session_id:
                return folder, json_file(folder, "session.json")
        raise KokiriError("That managed session was not found.")

    def verified_process(self, metadata: dict) -> dict | None:
        expected = metadata.get("executable")
        if not isinstance(expected, str) or Path(expected).name not in {"KokiriGame", "OcarinaOfTime"}:
            return None
        sample = self.process.sample(metadata.get("pid"))
        if sample is None:
            return None
        if sample["executable"] != expected:
            return None
        start = metadata.get("process_start")
        if not isinstance(start, int) or isinstance(start, bool) or sample["process_start"] != start:
            return None
        if metadata.get("process_uuid") and metadata["process_uuid"] != sample["process_uuid"]:
            return None
        return sample

    def list_sessions(self) -> dict:
        sessions = []
        for folder in self.candidates():
            try:
                metadata = json_file(folder, "session.json")
                sample = self.verified_process(metadata)
                identifier = self.session_id(folder)
                sessions.append({"session_id": identifier, "name": folder.name,
                                 "started": metadata.get("started"), "running_verified": sample is not None,
                                 "control": "observation-only",
                                 "source_commit": metadata.get("source_commit"),
                                 "game_update": metadata.get("game_update"),
                                 "physical_footprint_bytes": sample.get("physical_footprint_bytes") if sample else None})
            except (OSError, ValueError, TypeError):
                continue
        return {"sessions": sessions, "limit": 128,
                "note": "Discovered human sessions are observation-only. Running means executable and process-start identity both match."}

    def status(self, session_id: str) -> dict:
        folder, metadata = self.entry(session_id)
        sample = self.verified_process(metadata)
        timing = tail(folder, "timings.tsv", 200)
        frames = {}
        for line in timing:
            fields = line.split("\t")
            try:
                if len(fields) == 3 and fields[1] == "@frame_ms":
                    value = float(fields[2]); frame = int(fields[0])
                    if math.isfinite(value) and 0 < value < 120000:
                        frames[frame] = value
            except ValueError:
                continue
        presents = set()
        for line in tail(folder, "timings.tsv.presented.tsv", 200):
            fields = line.split("\t")
            try:
                if len(fields) == 8 and fields[0] == "presented" and fields[4] == "0":
                    stamp = float(fields[5])
                    if math.isfinite(stamp) and stamp > 0:
                        presents.add(stamp)
            except ValueError:
                continue
        ordered = sorted(presents)
        rate = (len(ordered)-1)/(ordered[-1]-ordered[0]) if len(ordered)>1 and ordered[-1]>ordered[0] else None
        location = None
        for line in reversed(tail(folder, "status.jsonl", 200)):
            try:
                row = json.loads(line)
                if row.get("status") in {"position", "moved", "arrived"} and isinstance(row.get("map"), str):
                    xyz = [row.get(k) for k in ("x", "y", "z")]
                    if row["map"] and all(isinstance(x, (int,float)) and not isinstance(x,bool) and math.isfinite(x) and abs(x)<10000 for x in xyz):
                        location = {"area": row["map"], "xyz": xyz, "query_id": row.get("id")}; break
            except (ValueError, AttributeError):
                continue
        return {"session_id": session_id, "running_verified": sample is not None,
                "process": sample, "last_observed_location": location,
                "location_freshness": "Last recorded reply; use session_location for a new read-only sample.",
                "frame_sample_count": len(frames), "max_frame_ms": max(frames.values(), default=None),
                "observed_game_presents_per_second": rate, "generated_frames_excluded": True,
                "certified_benchmark": False, "read_bound_bytes_per_file": MAX_TAIL}

    def logs(self, session_id: str, kind: str, lines: int) -> dict:
        folder, metadata = self.entry(session_id)
        if kind not in LOG_FILES:
            raise KokiriError("Choose game, timings, presented, status, process or events.")
        name = LOG_FILES[kind]
        executable = metadata.get("executable")
        if (kind == "game" and not (folder/name).exists()
                and isinstance(executable, str) and Path(executable).name == "KokiriGame"
                and self.verified_process(metadata)):
            global_log = Path.home()/"Library/Logs/Kokiri"
            return {"session_id": session_id, "kind": kind, "lines": tail(checked_directory(global_log), "ocarina.log", lines),
                    "note": "Current verified runtime's shared log; bounded tail only."}
        return {"session_id": session_id, "kind": kind, "lines": tail(folder, name, lines), "read_bound_bytes": MAX_TAIL}

    def live_capable(self, metadata: dict) -> bool:
        try:
            exe = Path(metadata["executable"])
            app = exe.parent.parent.parent
            info = plistlib.loads(bounded_bytes(checked_directory(app), "Contents/Info.plist", MAX_JSON))
            return info.get("CFBundleIdentifier") == "com.christianfurr.kokiri.runtime" and info.get("KokiriLiveStatusVersion") == 1
        except (OSError, ValueError, KeyError):
            return False

    def send_observation(self, session_id: str, line: str) -> None:
        folder, metadata = self.entry(session_id)
        if not self.verified_process(metadata):
            raise KokiriError("The recorded game process no longer matches; no observation was requested.")
        position = line.startswith("oot-live mcp-") and line.endswith(" position")
        screenshot = line.startswith("wshot ")
        if not (position or screenshot) or not self.live_capable(metadata):
            raise KokiriError("This runtime does not advertise the required observation capability.")
        if "\n" in line or "\r" in line or len(line.encode()) > 1400:
            raise KokiriError("One bounded observation command is required.")
        descriptor = open_relative(folder, "input.txt", os.O_WRONLY | os.O_APPEND)
        try:
            if os.fstat(descriptor).st_size > 8 << 20:
                raise KokiriError("The diagnostic input channel reached its size limit.")
            wire = (line+"\n").encode()
            if os.write(descriptor, wire) != len(wire):
                raise KokiriError("The diagnostic append was incomplete.")
        finally:
            os.close(descriptor)

    def location_request(self, session_id: str) -> str:
        self.entry(session_id)
        now = time.monotonic()
        self.commands = {key: stamp for key, stamp in self.commands.items() if now-stamp < 5}
        if now-self.commands.get(session_id, -100) < 5:
            raise KokiriError("Position sampling is limited to once every five seconds.")
        self.commands[session_id] = now
        token = "mcp-"+uuid.uuid4().hex[:20]
        self.send_observation(session_id, f"oot-live {token} position")
        return token

    def location_reply(self, session_id: str, token: str) -> dict | None:
        folder, _ = self.entry(session_id)
        for line in reversed(tail(folder, "status.jsonl", 200)):
            try:
                row = json.loads(line)
                if row.get("id") == token:
                    return row
            except (ValueError, AttributeError):
                continue
        return None

    def capture_request(self, session_id: str, surface: str = "window") -> Path:
        _, metadata = self.entry(session_id)
        sample = self.verified_process(metadata)
        if not sample:
            raise KokiriError("The game process identity changed; no screenshot was requested.")
        if surface not in {"window", "game_frame"}:
            raise KokiriError("Choose window or game_frame capture.")
        folder = self.managed_directory(self.development/"Captures"/session_id)
        with self.capture_lock:
            # Multiple hosts can run this stdio server against the same tree.
            # Lock the directory itself: no persistent lockfile or stale owner
            # cleanup, and process exit automatically releases the reservation lock.
            directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                try:
                    fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise KokiriError("Another capture is reserving a slot. Retry the observation.") from error
                if sum(1 for _ in itertools.islice(folder.iterdir(), 64)) >= 64:
                    raise KokiriError("This session reached its 64-capture limit. Preserve/review captures before requesting more.")
                destination = folder/(uuid.uuid4().hex+".png")
                # Pending captures count before native/background writers begin.
                descriptor = open_relative(folder, destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                os.close(descriptor)
            finally:
                os.close(directory)
        try:
            if surface == "game_frame":
                self.send_observation(session_id, "wshot "+str(destination))
            elif surface == "window":
                windows = self.process.windows(sample["pid"])
                if len(windows) != 1:
                    raise KokiriError("Expected one visible game window for the verified PID; capture was not attempted.")
                subprocess.run(["/usr/sbin/screencapture", "-x", "-l", str(windows[0]), str(destination)],
                               check=True, capture_output=True, timeout=10)
                current = self.verified_process(metadata)
                if (current is None or any(current[k] != sample[k] for k in ("pid", "executable", "process_start", "process_uuid"))
                        or self.process.windows(sample["pid"]) != windows):
                    raise KokiriError("The game identity changed during native window capture.")
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination
