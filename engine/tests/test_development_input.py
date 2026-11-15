"""CPU fixture using actual typed header and extracted production poll/takeover functions."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ENGINE = Path(__file__).resolve().parents[1]


def function(source: str, start: str) -> str:
    offset = source.index(start)
    opening = source.index("{", offset)
    depth = 1
    end = opening + 1
    while depth:
        if source[end] == "{": depth += 1
        elif source[end] == "}": depth -= 1
        end += 1
    return source[offset:end]


@unittest.skipUnless(sys.platform == "darwin", "native fixture uses macOS weak imports; no GPU")
class DevelopmentInputTests(unittest.TestCase):
    def test_actual_typed_input_delivery_release_and_takeover(self):
        source = (ENGINE / "runtime/input.c").read_text()
        header = (ENGINE / "runtime/kokiri_development_input.h").read_text()
        template = (ENGINE / "tests/development_input.c").read_text()
        button = function(source, "static uint64_t button(unsigned code)")
        user = function(source, "static void user_input(const char *what)")
        poll = function(source, "static int pad_states(NpadState *out,int max,const uint32_t *id,uint32_t want_style){")
        self.assertLess(user.index("atomic_store(&kokiriDevInputActive,0)"), user.index("runtime_kokiri_development_user_takeover"))
        eligibility = "if(enabled&&allowed&&*id==pad_id()&&want_style==pad_style()&&(styles&want_style)){"
        self.assertIn(eligibility, poll)
        self.assertIn('pthread_mutex_unlock(&inputLock);if(physicalTakeover)user_input("controller")', poll)
        self.assertNotIn("runtime_input_key_synthetic", header)
        self.assertNotIn("pending", header)
        wired = template.replace("// ACTUAL_BUTTON_FUNCTION", button).replace("// ACTUAL_USER_INPUT_FUNCTION", user)
        gate = "atomic_load(&kokiriDevInputActive)&&runtime_kokiri_development_active&&runtime_kokiri_development_active()"
        self.assertEqual(poll.count(gate), 1)
        controls = [("production", poll, None),
                    ("missing-lease-gate", poll.replace(gate, "atomic_load(&kokiriDevInputActive)"), "expired input never reaches"),
                    ("missing-human-cancel", poll, "physical stick wins")]
        with tempfile.TemporaryDirectory(prefix="kokiri-development-input-") as temporary:
            root = Path(temporary)
            for name, actual_poll, expected in controls:
                folder = root / name; folder.mkdir()
                actual_user = user
                if name == "missing-human-cancel":
                    actual_user = user.replace("atomic_store(&kokiriDevInputActive,0);", "(void)0;")
                    self.assertEqual(actual_poll.count("atomic_store(&kokiriDevInputActive,0);"), 1)
                    actual_poll = actual_poll.replace("atomic_store(&kokiriDevInputActive,0);", "(void)0;")
                code = wired.replace("// ACTUAL_PAD_STATES_FUNCTION", actual_poll)
                if name == "missing-human-cancel":
                    code = template.replace("// ACTUAL_BUTTON_FUNCTION", button).replace("// ACTUAL_USER_INPUT_FUNCTION", actual_user).replace("// ACTUAL_PAD_STATES_FUNCTION", actual_poll)
                (folder / "kokiri_development_input.h").write_text(header)
                fixture = folder / "fixture.c"; fixture.write_text(code)
                executable = folder / "fixture"
                subprocess.run(["xcrun", "clang", "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror",
                                "-I", str(folder), str(fixture), "-o", str(executable)], check=True, timeout=10)
                result = subprocess.run([str(executable), str(folder / "status.jsonl")], capture_output=True, text=True, timeout=3)
                if expected is None:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("checks PASS", result.stdout)
                else:
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("FAILED: " + expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
