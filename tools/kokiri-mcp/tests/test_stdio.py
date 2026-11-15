"""Official SDK client and server over real stdio, using a closed synthetic session."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client
from mcp.client.stdio import StdioServerParameters


PACKAGE = Path(__file__).resolve().parents[1]
TOOLS = {"sessions_list", "session_status", "session_logs", "session_location", "session_screenshot"}


class StdioTests(unittest.IsolatedAsyncioTestCase):
    async def check_transport(self, mode):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            folder = home/"Library/Application Support/Kokiri/Sessions/synthetic-closed-session"
            folder.mkdir(parents=True)
            (folder/"session.json").write_text(json.dumps({
                "pid": 2147483646, "executable": "/synthetic/KokiriGame",
                "process_start": 1, "started": 100, "source_commit": "synthetic-fixture",
                "game_update": "131072", "role": "kokiri-mcp",
            }))
            (folder/"input.txt").write_text("")
            (folder/"timings.tsv").write_text("1\t@frame_ms\t20\n2\t@frame_ms\t100\n")
            (folder/"status.jsonl").write_text(json.dumps({
                "id": "synthetic", "status": "position", "map": "Synthetic Test Area",
                "x": 1, "y": 2, "z": 3,
            })+"\n")
            (folder/"game-full.log").write_text("synthetic log line\n")
            params = StdioServerParameters(command=sys.executable, args=[str(PACKAGE/"server.py")],
                                           cwd=str(PACKAGE), env={"HOME": str(home)})
            async with Client(params, mode=mode, read_timeout_seconds=10) as client:
                self.assertEqual(client.session.protocol_version, "2026-07-28" if mode == "auto" else "2025-11-25")
                listing = await client.list_tools()
                self.assertEqual({tool.name for tool in listing.tools}, TOOLS)
                annotations = {tool.name: tool.annotations.read_only_hint for tool in listing.tools}
                self.assertEqual(annotations, {name: name in {"sessions_list", "session_status", "session_logs"} for name in TOOLS})
                sessions = await client.call_tool("sessions_list", {})
                self.assertFalse(sessions.is_error)
                rows = sessions.structured_content["sessions"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["control"], "observation-only")
                self.assertFalse(rows[0]["running_verified"])
                identifier = rows[0]["session_id"]
                status = await client.call_tool("session_status", {"session_id": identifier})
                self.assertFalse(status.is_error)
                self.assertEqual(status.structured_content["max_frame_ms"], 100)
                self.assertEqual(status.structured_content["last_observed_location"]["area"], "Synthetic Test Area")
                logs = await client.call_tool("session_logs", {"session_id": identifier, "lines": 1})
                self.assertEqual(logs.structured_content["lines"], ["synthetic log line"])
                location = await client.call_tool("session_location", {"session_id": identifier})
                self.assertTrue(location.is_error)
                resources = await client.list_resources()
                self.assertEqual([str(item.uri) for item in resources.resources], ["kokiri://development-guide"])
                guide = await client.read_resource("kokiri://development-guide")
                self.assertIn("No player-control", guide.contents[0].text)
            self.assertEqual((folder/"input.txt").read_text(), "")
            self.assertFalse((home/"Library/Application Support/Kokiri/Development").exists())

    async def test_modern_sdk_stdio_discovery_and_harmless_calls(self):
        await self.check_transport("auto")

    async def test_legacy_handshake_stdio_discovery_and_harmless_calls(self):
        await self.check_transport("legacy")


if __name__ == "__main__":
    unittest.main()
