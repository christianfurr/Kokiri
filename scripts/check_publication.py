#!/usr/bin/env python3
"""Check prospective or staged public source without printing sensitive bytes."""
import argparse
import hashlib
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PINNED_METADATA = {
    "engine/assets/shader_list.tsv": "db776121d89d47912088dac9ff9fb10b9de38084242a39a374b1e0f722f9a6e4",
    "engine/assets/romfs-v131072.tsv.gz": "c6aebc42c403721d5a0e060e385de28c6bad54afa52e1153cf8ba49895f0d6a9",
}
# Exact hashes bind the website exceptions to visually reviewed image bytes.
REVIEWED_WEBSITE_IMAGES = {
    "website/assets/forest.jpg": "2c04bb88c2ae6e6ede68b6aed2b51b572d06323828e89adc7d7fe92d5a471a6a",
    "website/assets/hyrule-field.jpg": "3bb38871a4368f363e97049dfa5c252c9c3ae449a218cef874de63808dd76ee1",
    "website/assets/kakariko.jpg": "afdf3452c54ab83e497806af7926892fde08aad5c2d033615b586f74f689f228",
    "website/assets/kokiri-home.png": "99a1a4937ec420ce0f4fdd069b3041928d2a5379d346a895c8f19aa554fdf5af",
    "website/assets/kokiri-mark.png": "fabe818a53f39cf79e7102264c2152cff977f4c9b0c5794a74f66013ef44eaa2",
}
APPROVED_IMAGES = {
    "assets/brand/kokiri-mark.png",
    "assets/readme/kokiri-home.png",
    "assets/readme/kokiri-performance.png",
    "assets/readme/kokiri-menu.png",
}
FORBIDDEN_PARTS = {
    "extracted", "rewritten", "prebuilt", "node_modules", "__pycache__",
    ".build", "DerivedData", "shader-seed", "shader-libs", "shader-cache",
    "profile", "profiles", ".env", ".local",
}
FORBIDDEN_SUFFIXES = {
    ".nup", ".nsp", ".xci", ".nca", ".nso", ".bin", ".spv", ".metallib", ".air",
    ".dylib", ".dll", ".exe", ".o", ".a", ".so", ".p8", ".p12", ".pem", ".key",
    ".keys", ".sav", ".log", ".zip", ".dmg", ".pyc", ".bfttf", ".ttf", ".otf",
}
SECRET_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
]
MACHO = {bytes.fromhex(x) for x in ("feedface", "cefaedfe", "feedfacf", "cffaedfe", "cafebabe", "bebafeca")}


def issue(name: str, data: bytes, mode: str = "100644") -> str | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or mode in {"120000", "160000"}:
        return "symlink, submodule or invalid path"
    if any(p in FORBIDDEN_PARTS or p.endswith((".app", ".dSYM")) for p in path.parts):
        return "private/build directory"
    if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith(".env.") and path.name != ".env.example":
        return "private/build file type"
    if len(data) > 32 << 20:
        return "file exceeds source size bound"
    if name in PINNED_METADATA:
        return None if hashlib.sha256(data).hexdigest() == PINNED_METADATA[name] else "public metadata pin changed; review provenance"
    if name in REVIEWED_WEBSITE_IMAGES:
        return None if hashlib.sha256(data).hexdigest() == REVIEWED_WEBSITE_IMAGES[name] else "website image changed; review provenance"
    if name in APPROVED_IMAGES:
        return None if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) <= 8 << 20 else "invalid approved image"
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".gz", ".tsv"}:
        return "unreviewed image, archive or metadata file"
    if data[:4] in MACHO or data.startswith((b"MZ", b"\x7fELF", b"PK\x03\x04")) or b"\0" in data:
        return "binary payload"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "non-text payload"
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        return "possible credential; contents suppressed"
    return None


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="inspect index blobs, not working copies")
    args = parser.parse_args()
    entries = {}
    for row in git("ls-files", "--stage", "-z").split(b"\0"):
        if not row:
            continue
        meta, raw_name = row.split(b"\t", 1)
        mode, blob, stage = meta.decode().split()
        if stage != "0":
            raise SystemExit("Resolve index conflicts before publication")
        entries[raw_name.decode()] = (mode, blob)
    if not args.staged:
        for raw in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
            if raw:
                entries[raw.decode()] = ("100644", None)
    errors = []
    total = 0
    for name, (mode, blob) in sorted(entries.items()):
        if args.staged:
            data = git("cat-file", "blob", blob)
        else:
            file = ROOT / name
            if file.is_symlink():
                errors.append((name, "symlink"))
                continue
            if not file.exists():
                continue
            if file.stat().st_size > 32 << 20:
                errors.append((name, "file exceeds source size bound"))
                continue
            data = file.read_bytes()
        total += len(data)
        reason = issue(name, data, mode)
        if reason:
            errors.append((name, reason))
    for name, reason in errors:
        print(f"REJECT {name}: {reason}")
    print(f"Publication scan: {len(entries)} paths, {total:,} bytes, {len(errors)} rejected")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
