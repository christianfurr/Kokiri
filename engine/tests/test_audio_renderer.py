"""Exercise the production renderer without game files, modules or audio devices."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ENGINE = Path(__file__).resolve().parents[1]


class AudioRendererTests(unittest.TestCase):
    def test_production_mixer_and_negative_control(self):
        with tempfile.TemporaryDirectory(prefix="kokiri-audio-") as directory:
            executable = Path(directory) / "audio-renderer"
            command = [
                "xcrun", "clang", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-Wno-unused-function", "-Wno-deprecated-declarations",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-DGAME_OOT=1", "-DGAME_NS2=1", "-Ithird_party/d2r_gfx/gfx/nvn/include",
                "tests/audio_renderer_probe.c", "runtime/audio_renderer.c", "runtime/audio_mixer.c",
                "runtime/audio_reverb.c", "runtime/audio_effects.c", "runtime/ns2_audio_out.c",
                "-framework", "AudioToolbox", "-framework", "CoreFoundation", "-o", str(executable),
            ]
            subprocess.run(command, cwd=ENGINE, check=True, capture_output=True, text=True, timeout=30)
            environment = dict(os.environ, TOTK_AUDIO_OFF="1")
            environment.pop("TOTK_PROBE_NEGATIVE", None)
            result = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(summary["status"], "pass")
            self.assertEqual(summary["probe"], "probe-audio")
            # The existing negative control changes a voice's right-channel gain.
            environment["TOTK_PROBE_NEGATIVE"] = "1"
            negative = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(negative.returncode, 0)
            self.assertIn("audio probe: PCM16 mix", negative.stderr)


if __name__ == "__main__":
    unittest.main()
