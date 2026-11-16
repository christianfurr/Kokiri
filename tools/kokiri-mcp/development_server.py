"""Separate, unregistered-until-accepted development MCP. Human observer is server.py."""
from __future__ import annotations

import argparse
import asyncio
import base64
from pathlib import Path
from typing import Any, Literal

from mcp.server import MCPServer
from pydantic import StrictInt, StrictFloat
from mcp.types import ImageContent, TextContent
from development import Development
from server import checked_call, READ, WRITE


def save_call(manager: Development, session_id: str, operation: str, **arguments) -> dict[str, Any]:
    return checked_call(lambda: manager.workshop(session_id,operation,**arguments))


def create_server(manager: Development) -> MCPServer:
    server=MCPServer("Kokiri Disposable Development",version="0.1.0",log_level="WARNING",
        instructions="Controls target only newly copied, leased development sessions. Never adopts or controls human gameplay. Launch requires a registered isolation-accepted runtime and an Integration-issued exclusive test grant. Save edits require a stopped owned profile. No arbitrary paths, shell commands or memory writes. Queued actions require correlated replies; they are not completion evidence.")

    @server.tool(annotations=READ)
    def development_options() -> dict[str, Any]:
        """List privately registered runtime and fixture IDs. Registration is a separate local setup operation."""
        return checked_call(manager.options)

    @server.tool(annotations=READ)
    def development_sessions() -> dict[str, Any]:
        """Rediscover up to32created disposable sessions without adopting any existing human process."""
        return checked_call(manager.sessions)

    @server.tool(annotations=WRITE)
    async def development_create(runtime_id: str, fixture_id: str) -> dict[str, Any]:
        """Copy and verify a complete disposable profile; create private settings/cache/log roots. Does not launch."""
        return await asyncio.to_thread(checked_call,manager.create,runtime_id,fixture_id)

    @server.tool(annotations=WRITE)
    async def development_launch(session_id: str, seconds: StrictInt = 600) -> dict[str, Any]:
        """Launch only an accepted pinned runtime with an exclusive test grant and a10–1800second lease."""
        return await asyncio.to_thread(checked_call,manager.launch,session_id,seconds)

    @server.tool(annotations=READ)
    def development_status(session_id: str) -> dict[str, Any]:
        """Observe exact process identity and effective isolation acceptance. A starting process is not accepted control."""
        return checked_call(manager.status,session_id)

    @server.tool(annotations=READ)
    def development_logs(session_id: str,kind: Literal["game","timings","presented","status","process","events"]="game",lines: StrictInt=80) -> dict[str, Any]:
        """Read1–200bounded lines from this owned session only; no global logs or arbitrary paths."""
        return checked_call(manager.logs,session_id,kind,lines)

    @server.tool(annotations=WRITE)
    def development_close(session_id: str) -> dict[str, Any]:
        """Request close of the exactly verified owned session only. Check status and close again after exit to mark stopped."""
        return checked_call(manager.close,session_id)

    @server.tool(annotations=WRITE)
    async def development_restart(session_id: str, seconds: StrictInt=600) -> dict[str, Any]:
        """Close then relaunch this owned test session only after verified exit, fresh grant and human-session checks."""
        return await asyncio.to_thread(checked_call,manager.restart,session_id,seconds)

    @server.tool(annotations=WRITE)
    async def development_reset(session_id: str) -> dict[str, Any]:
        """Reset a stopped test profile to its verified initial copy, retaining displaced test progress and its warm cache."""
        return await asyncio.to_thread(checked_call,manager.reset,session_id)

    @server.tool(annotations=WRITE,structured_output=False)
    async def development_screenshot(session_id: str) -> list[ImageContent|TextContent]:
        """Capture exactly the verified owned native game window, including startup/HUD/menus. Permission and live acceptance required."""
        result=await asyncio.to_thread(checked_call,manager.capture,session_id)
        return [TextContent(type="text",text="Verified development window: "+result["path"]),
                ImageContent(type="image",data=base64.b64encode(result["png"]).decode("ascii"),mimeType="image/png")]

    @server.tool(annotations=WRITE)
    def development_position(session_id: str) -> dict[str, Any]:
        """Queue a correlated position query on the leased test session."""
        return checked_call(manager.action,session_id,{"action":"position"})

    @server.tool(annotations=WRITE)
    def development_move(session_id: str, area: str, x: StrictFloat, y: StrictFloat, z: StrictFloat) -> dict[str, Any]:
        """Queue same-area physics-controller movement (runtime bound250metres). Verify moved reply."""
        return checked_call(manager.action,session_id,{"action":"move","map":area,"x":x,"y":y,"z":z})

    @server.tool(annotations=WRITE)
    def development_travel(session_id: str, destination: Literal["field","kokiri","kakariko","crater"]) -> dict[str, Any]:
        """Queue named area travel for test setup. Verify arrived reply; use walking/camera inputs for measured routes."""
        return checked_call(manager.action,session_id,{"action":"warp","destination":destination})

    @server.tool(annotations=WRITE)
    def development_button(session_id: str, button: Literal["a","b","x","y","l","r","zl","zr","plus","minus","l3","r3","left","up","right","down"], milliseconds: StrictInt=100) -> dict[str, Any]:
        """Hold a named game button for1–5000ms with guaranteed bounded release; inspect guest poll evidence."""
        return checked_call(manager.action,session_id,{"action":"button","button":button,"milliseconds":milliseconds})

    @server.tool(annotations=WRITE)
    def development_stick(session_id: str, stick: Literal["left","right"], x: StrictFloat, y: StrictFloat, milliseconds: StrictInt=250) -> dict[str, Any]:
        """Apply a finite normalized stick vector for1–5000ms, then return to neutral. Right stick controls camera."""
        return checked_call(manager.action,session_id,{"action":"stick","stick":stick,"x":x,"y":y,"milliseconds":milliseconds})

    @server.tool(annotations=WRITE)
    def development_menu(session_id: str, page: StrictInt) -> dict[str, Any]:
        """Request native settings page0–4 or-1closed. Reply acknowledges request; screenshot proves visible state."""
        return checked_call(manager.action,session_id,{"action":"settings","page":page})

    @server.tool(annotations=WRITE)
    def development_configure(session_id: str, settings: dict) -> dict[str, Any]:
        """Set allowlisted test HUD/display preferences while the owned session is stopped."""
        return checked_call(manager.configure,session_id,settings)

    @server.tool(annotations=READ)
    def development_reply(session_id: str, request_id: str) -> dict[str, Any]:
        """Read the correlated runtime reply for a typed action. Pending/warping is not completion."""
        return checked_call(manager.reply,session_id,request_id)

    @server.tool(annotations=WRITE)
    def development_marker_save(session_id: str, name: str, area: str, x: StrictFloat, y: StrictFloat, z: StrictFloat) -> dict[str, Any]:
        """Save a bounded scene coordinate marker inside this disposable session."""
        return checked_call(manager.marker,session_id,name,{"map":area,"x":x,"y":y,"z":z})

    @server.tool(annotations=WRITE)
    def development_marker_return(session_id: str, name: str) -> dict[str, Any]:
        """Queue return to a session marker; runtime rejects different areas or moves beyond250metres."""
        return checked_call(manager.marker,session_id,name)

    @server.tool(annotations=WRITE)
    async def development_save_snapshot(session_id: str, slot: StrictInt) -> dict[str, Any]:
        """Snapshot a stopped owned test profile. Returns immutable snapshot identity; never reads a human profile."""
        return await asyncio.to_thread(save_call,manager,session_id,"snapshot",slot=slot)

    @server.tool(annotations=WRITE)
    async def development_save_plan(session_id: str, slot: StrictInt, changes: dict, expected_snapshot: str) -> dict[str, Any]:
        """Validate typed test-save changes and return a semantic diff/plan ID without applying them."""
        return await asyncio.to_thread(save_call,manager,session_id,"plan",slot=slot,changes=changes,expected_snapshot=expected_snapshot)

    @server.tool(annotations=WRITE)
    async def development_save_apply(session_id: str, plan_id: str) -> dict[str, Any]:
        """Apply one validated plan with snapshot conflict checks, backup and atomic replacement. Retries are idempotent."""
        return await asyncio.to_thread(save_call,manager,session_id,"apply",plan_id=plan_id)

    @server.tool(annotations=WRITE)
    async def development_save_restore(session_id: str, snapshot_id: str) -> dict[str, Any]:
        """Restore a snapshot only inside the stopped owned test profile, retaining the displaced version."""
        return await asyncio.to_thread(save_call,manager,session_id,"restore",snapshot_id=snapshot_id)

    @server.tool(annotations=WRITE)
    async def development_scenario(session_id: str, steps: list[dict]) -> dict[str, Any]:
        """Execute1–64fully validated typed steps, max300s including deadlines; fail on lease/identity changes. Checkpoints record real presented-frame observations and footprint, not benchmark certification."""
        return await asyncio.to_thread(checked_call,manager.run,session_id,steps)

    @server.tool(annotations=WRITE)
    async def development_scenario_preset(session_id: str, scenario_id: str) -> dict[str, Any]:
        """Run a privately registered typed scenario preset with the same300second bound and evidence checkpoints."""
        return await asyncio.to_thread(checked_call,manager.preset,session_id,scenario_id)

    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",type=Path,default=Path.home()/"Library/Application Support/KokiriDevelopment/Workbench")
    args=parser.parse_args()
    create_server(Development(args.workspace)).run(transport="stdio")


if __name__=="__main__":main()
