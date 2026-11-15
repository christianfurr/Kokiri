"""Real temporary directories only; no profile copying or runtime launch."""
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from containment import require_disjoint_directories
from kokiri import KokiriError


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kokiri-containment-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "FixtureSource"
        self.workspace = self.root / "Workspace"
        self.source.mkdir()
        self.workspace.mkdir()

    def case_alias(self, path: Path) -> Path:
        alias = path.with_name(path.name.swapcase())
        if not alias.exists() or not os.path.samefile(path, alias):
            self.skipTest("This temporary filesystem does not expose a case-insensitive spelling alias.")
        return alias

    def test_separate_siblings_are_allowed_in_both_orders(self):
        require_disjoint_directories(self.source, self.workspace)
        require_disjoint_directories(self.workspace, self.source)

    def test_exact_same_directory_is_rejected(self):
        with self.assertRaises(KokiriError):
            require_disjoint_directories(self.source, self.source)

    def test_source_ancestor_and_descendant_are_rejected(self):
        nested = self.source / "existing" / "nested"
        nested.mkdir(parents=True)
        for source, workspace in ((self.source, nested), (nested, self.source)):
            with self.subTest(source=source, workspace=workspace), self.assertRaises(KokiriError):
                require_disjoint_directories(source, workspace)

    def test_same_directory_with_case_alias_is_rejected(self):
        alias = self.case_alias(self.source)
        for source, workspace in ((self.source, alias), (alias, self.source)):
            with self.subTest(source=source, workspace=workspace), self.assertRaises(KokiriError):
                require_disjoint_directories(source, workspace)

    def test_case_alias_in_existing_ancestor_is_rejected(self):
        alias = self.case_alias(self.source)
        nested = self.source / "ExistingChild"
        nested.mkdir()
        spelled_differently = alias / "existingchild"
        if not spelled_differently.exists() or not os.path.samefile(nested, spelled_differently):
            self.skipTest("This temporary filesystem does not alias the descendant spelling.")
        for source, workspace in ((self.source, spelled_differently), (spelled_differently, self.source)):
            with self.subTest(source=source, workspace=workspace), self.assertRaises(KokiriError):
                require_disjoint_directories(source, workspace)

    def test_unavailable_identity_fails_closed(self):
        # Root validation is tested separately. Simulate a stat failure during
        # the identity walk after two real temporary roots were selected.
        with patch("containment.checked_directory", side_effect=[self.source, self.workspace]), \
             patch.object(Path, "stat", side_effect=PermissionError(errno.EACCES, "synthetic identity failure")):
            with self.assertRaisesRegex(KokiriError, "could not be verified"):
                require_disjoint_directories(self.source, self.workspace)

    def test_non_directory_root_is_rejected(self):
        file = self.root / "ordinary-file"
        file.write_bytes(b"synthetic")
        with self.assertRaises(KokiriError):
            require_disjoint_directories(self.source, file)


if __name__ == "__main__":
    unittest.main()
