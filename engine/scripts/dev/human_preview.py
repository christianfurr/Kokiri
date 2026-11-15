#!/usr/bin/env python3
"""Start a prepared human-owned preview with a clean environment.

Integration must grant the actual game launch separately. This helper neither
prepares private data nor waits for, controls, adopts or closes a running game.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import pwd
import re
import stat
import subprocess
import sys


METADATA_LIMIT = 65536
EXECUTABLE_LIMIT = 64 << 20


class PreviewError(ValueError):
    pass


def canonical_directory(value: Path) -> Path:
    path = Path(value)
    if (not path.is_absolute() or str(path) != str(path.resolve(strict=True))
            or any(ord(character) < 32 or ord(character) == 127 for character in str(path))):
        raise PreviewError("Use an existing canonical absolute directory without symlinks.")
    for ancestor in (path, *path.parents):
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise PreviewError("Directory paths must not contain symlinks.")
    return path


def related(first: Path, second: Path) -> bool:
    if first == second or first in second.parents or second in first.parents:
        return True
    # Existing ancestor identities also reject case aliases on APFS.
    for parent, child in ((first, second), (second, first)):
        if not parent.exists():
            continue
        for ancestor in (child, *child.parents):
            if ancestor.exists() and parent.samefile(ancestor):
                return True
    return False


def identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def open_regular(directory: int, name: str, flags: int = os.O_RDONLY) -> int:
    descriptor = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise PreviewError("Private metadata and logs must be same-user regular files without hardlinks.")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def read_metadata(directory: int, name: str) -> bytes:
    with os.fdopen(open_regular(directory, name), "rb") as source:
        before = os.fstat(source.fileno())
        if not 0 < before.st_size <= METADATA_LIMIT:
            raise PreviewError("Preview metadata must be between 1 byte and 64 KiB.")
        data = source.read(METADATA_LIMIT + 1)
        if len(data) != before.st_size or identity(before) != identity(os.fstat(source.fileno())):
            raise PreviewError("Preview metadata changed while being read.")
        return data


def launch(app: Path, private_root: Path) -> int:
    account = pwd.getpwuid(os.getuid())
    home = Path(account.pw_dir)
    app = canonical_directory(app)
    root = canonical_directory(private_root)
    root_info = root.lstat()
    if root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
        raise PreviewError("The existing private root must belong to this user and have mode 0700.")
    if len(os.fsencode(root)) > 768:
        raise PreviewError("The private root path is too long for the native entry.")
    for suffix in ("Library/Application Support/Kokiri", "Library/Application Support/MacNativeGames",
                   "Library/Logs/Kokiri", "Library/Logs/MacNativeGames"):
        if related(root, home / suffix):
            raise PreviewError("The private root must be separate from shared game support and log trees.")
    if related(root, app):
        raise PreviewError("The private root and app must be separate directories.")

    contents = canonical_directory(app / "Contents")
    executable_directory = canonical_directory(contents / "MacOS")
    root_fd = contents_fd = executable_fd = -1
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        contents_fd = os.open(contents, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        executable_fd = os.open(executable_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        if identity(root_info) != identity(os.fstat(root_fd)):
            raise PreviewError("The private root changed during validation.")
        info = plistlib.loads(read_metadata(contents_fd, "Info.plist"))
        if (not isinstance(info, dict) or info.get("CFBundleIdentifier") != "com.christianfurr.kokiri.runtime"
                or info.get("CFBundleExecutable") != "KokiriGame"
                or type(info.get("KokiriHumanPreviewVersion")) is not int
                or info["KokiriHumanPreviewVersion"] != 1):
            raise PreviewError("This app does not advertise the dedicated human preview entry.")
        request = json.loads(read_metadata(root_fd, "preview.json"))
        if (not isinstance(request, dict) or type(request.get("schema")) is not int or request["schema"] != 1
                or request.get("kind") != "human-preview" or request.get("owner") != "user"
                or "nonce" in request or "expires_unix" in request
                or not isinstance(request.get("session_id"), str)
                or not re.fullmatch("[0-9a-f]{32}", request["session_id"])
                or not isinstance(request.get("executable_sha256"), str)
                or not re.fullmatch("[0-9a-f]{64}", request["executable_sha256"])):
            raise PreviewError("The private preview request is invalid.")
        for name in ("request.json", "lease.json", "ownership.json", "revoked"):
            try:
                os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise PreviewError("A human preview root must not contain development-session state.")
        with os.fdopen(open_regular(executable_fd, "KokiriGame"), "rb") as binary:
            binary_info = os.fstat(binary.fileno())
            if not 0 < binary_info.st_size <= EXECUTABLE_LIMIT or not binary_info.st_mode & 0o111:
                raise PreviewError("The pinned main executable is missing, too large or not executable.")
            digest = hashlib.sha256()
            remaining = EXECUTABLE_LIMIT + 1
            while remaining:
                block = binary.read(min(65536, remaining))
                if not block:
                    break
                digest.update(block)
                remaining -= len(block)
            if (not remaining or digest.hexdigest() != request["executable_sha256"]
                    or identity(binary_info) != identity(os.fstat(binary.fileno()))):
                raise PreviewError("The main executable does not match the pinned preview request.")
        executable = executable_directory / "KokiriGame"
        environment = {"HOME": account.pw_dir, "USER": account.pw_name, "LOGNAME": account.pw_name,
                       "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
                       "KOKIRI_HUMAN_PREVIEW_ROOT": str(root)}
        log_fd = open_regular(root_fd, "game-full.log", os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        with os.fdopen(log_fd, "ab") as log:
            current_root = root.lstat()
            if (current_root.st_dev, current_root.st_ino) != (root_info.st_dev, root_info.st_ino):
                raise PreviewError("The private root changed before launch.")
            if identity(executable.lstat()) != identity(binary_info):
                raise PreviewError("The pinned executable changed before launch.")
            process = subprocess.Popen([str(executable), "--kokiri-preview", str(root)], cwd=app,
                                       env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True, close_fds=True)
        return process.pid
    finally:
        for descriptor in (executable_fd, contents_fd, root_fd):
            if descriptor >= 0:
                os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        process_id = launch(args.app, args.private_root)
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        print(f"Human preview was not started: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "starting", "pid": process_id, "owner": "user",
                      "control": "observation-only"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
