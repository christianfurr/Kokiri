"""Identity-based containment checks for existing profile/workspace roots."""
from pathlib import Path
import stat

from kokiri import KokiriError, checked_directory


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise KokiriError("A profile or workspace ancestor is no longer a directory.")
    return info.st_dev, info.st_ino


def require_disjoint_directories(source: Path, workspace: Path) -> None:
    """Reject equal or nested existing roots, including filesystem spelling aliases.

    checked_directory supplies the existing same-user/no-symlink root validation.
    Device/inode comparisons handle case-insensitive filesystem aliases without
    guessing which case-folding or Unicode normalization a volume implements.
    Call before creating or copying anything into either directory.
    """
    try:
        source = checked_directory(source)
        workspace = checked_directory(workspace)
        source_identity = _directory_identity(source)
        workspace_identity = _directory_identity(workspace)
        for ancestor in (source, *source.parents):
            if _directory_identity(ancestor) == workspace_identity:
                raise KokiriError("Keep fixture source profiles separate from the development workspace.")
        for ancestor in (workspace, *workspace.parents):
            if _directory_identity(ancestor) == source_identity:
                raise KokiriError("Keep fixture source profiles separate from the development workspace.")
    except OSError as error:
        raise KokiriError("Profile/workspace directory identities could not be verified; no copy was started.") from error
