"""Kokiri local MCP. stdout belongs exclusively to the official SDK protocol."""
from __future__ import annotations

import argparse
import asyncio
import base64
from pathlib import Path
import subprocess
import time
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations
from kokiri import SessionStore, KokiriError, bounded_bytes, complete_png


READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)


def checked_call(function, *arguments):
    try:
        return function(*arguments)
    except KokiriError as error:
        raise ToolError(str(error)) from error
    except (OSError, subprocess.SubprocessError) as error:
        raise ToolError("The required local file or native window capture is unavailable. Check the session and macOS Screen Recording permission.") from error


def require_identity(store: SessionStore, session_id: str, expected: tuple | None = None) -> tuple:
    _, metadata = checked_call(store.entry, session_id)
    sample = store.verified_process(metadata)
    identity = tuple(sample[key] for key in ("pid", "executable", "process_start", "process_uuid")) if sample else None
    if identity is None or (expected is not None and identity != expected):
        raise ToolError("The game identity changed during observation.")
    return identity


def create_server(store: SessionStore) -> MCPServer:
    server = MCPServer("Kokiri Development", version="0.1.0", log_level="WARNING",
        instructions="All sessions are observation-only. No launch, movement, input, close, arbitrary shell, save editing or free-form game command tools are available. Location and screenshots write private diagnostic files only. Frame rates are observations, not certified benchmarks.")

    @server.tool(annotations=READ)
    def sessions_list() -> dict[str, Any]:
        """List up to 128 Kokiri sessions and their verified running/observation-only status."""
        return checked_call(store.list_sessions)

    @server.tool(annotations=READ)
    def session_status(session_id: str) -> dict[str, Any]:
        """Read bounded timing tails, last recorded location and current libproc physical footprint after PID/start verification."""
        return checked_call(store.status, session_id)

    @server.tool(annotations=READ)
    def session_logs(session_id: str, kind: Literal["game", "timings", "presented", "status", "process", "events"] = "game", lines: int = 80) -> dict[str, Any]:
        """Read 1–200 lines from a fixed session log kind, at most 256 KiB. Never reads saves or arbitrary paths."""
        return checked_call(store.logs, session_id, kind, lines)

    @server.tool(annotations=WRITE)
    async def session_location(session_id: str) -> dict[str, Any]:
        """Ask the verified capable runtime for position only, at most once per five seconds; never moves the player."""
        identity = require_identity(store, session_id)
        token = checked_call(store.location_request, session_id)
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            require_identity(store, session_id, identity)
            reply = checked_call(store.location_reply, session_id, token)
            if reply is not None:
                require_identity(store, session_id, identity)
                return {"session_id": session_id, "observation_only": True, "reply": reply}
            await asyncio.sleep(.1)
        return {"session_id": session_id, "observation_only": True, "status": "timeout", "note": "No movement command was sent. Cold compilation can delay the controller-poll reply."}

    @server.tool(annotations=WRITE, structured_output=False)
    async def session_screenshot(session_id: str, surface: Literal["window", "game_frame"] = "window") -> list[ImageContent | TextContent]:
        """Capture the verified game only. window includes native startup/HUD/menu; game_frame is the raw runtime frame. Writes one private PNG under Kokiri Development/Captures."""
        identity = require_identity(store, session_id)
        path = await asyncio.to_thread(checked_call, store.capture_request, session_id, surface)
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            if path.exists() and path.stat().st_size:
                data = checked_call(bounded_bytes, path.parent, path.name, 8 << 20)
                if checked_call(complete_png, data):
                    require_identity(store, session_id, identity)
                    return [TextContent(type="text", text=f"{surface} capture: {path}"),
                            ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mimeType="image/png")]
            require_identity(store, session_id, identity)
            await asyncio.sleep(.1)
        raise ToolError("Screenshot timed out. No game input or close command was sent.")

    @server.resource("kokiri://development-guide")
    def guide() -> str:
        return "Kokiri Development MCP is local stdio. List sessions first. Human sessions are observation-only. Screenshot window captures include native UI; game_frame captures do not. No player-control or game-launch tools are exposed. Packaged runtimes currently write shared launcher state even with copied profiles; a dedicated isolated runtime entry is required before adding test controls. Frame timing and process physical footprint are distinct from GPU allocation. Keep game files, extracted shader code, saves and private logs out of public issues."

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observe-root", action="append", type=Path, default=[], help="Additional fixed read-only session directory; never grants test control")
    args = parser.parse_args()
    create_server(SessionStore(observe_roots=args.observe_root)).run(transport="stdio")


if __name__ == "__main__":
    main()
