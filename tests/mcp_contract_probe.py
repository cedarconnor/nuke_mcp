"""Real stdio MCP contract and read-only, live two-client verification."""

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from nuke_mcp_bridge.operations import OperationRegistry
from nuke_mcp_bridge.protocol import BridgeError
from nuke_mcp_bridge.runtime import BridgeRuntime
from tests.test_runtime import ManualDispatcher

LEGACY = {"get_script_info": [], "get_node_info": ["node_name"],
          "create_node": ["node_type"], "modify_node": ["name"],
          "delete_node": ["name"], "position_node": ["name", "x", "y"],
          "connect_nodes": ["output_node", "input_node"], "render": [],
          "viewer_playback": [], "execute_nuke_code": ["code"],
          "auto_layout_nodes": [], "set_frames": [], "create_viewer": [],
          "create_workflow_template": ["template_type"], "organize_node_graph": []}


def data(reply):
    assert reply.structuredContent is not None, "Missing structured receipt"
    return reply.structuredContent


async def probe(live=False, port=9877, slow=False):
    runtime = None
    pump = None
    if not live:
        def missing(**kwargs):
            raise BridgeError("node_not_found", "Node not found")
        def render(**kwargs):
            start = time.monotonic()
            while time.monotonic() - start < (16.1 if slow else .1):
                yield {"frames_completed": []}
            yield {"frames_completed": [1], "status": "Rendering completed"}
        handlers = {
            "get_capabilities": lambda: {"nuke_version": "fake", "license_mode": "unknown"},
            "get_script_info": lambda: {"name": "contract_fixture", "fps": 24, "format": "HD",
                                      "first_frame": 1, "last_frame": 3, "nodes": []},
            "get_node_info": missing, "render": render,
            "execute_code": lambda code: {"executed": True, "output": {"probe": "read-only"}},
        }
        runtime = BridgeRuntime(handlers, OperationRegistry(), ManualDispatcher())
        runtime.start(port=0)
        port = runtime.port
        async def tick():
            while True:
                runtime.tick()
                await asyncio.sleep(.005)
        pump = asyncio.create_task(tick())
    report = {"mode": "live" if live else "offline_stdio", "port": port, "calls": []}
    try:
        async with AsyncExitStack() as stack:
            sessions = []
            for index in range(2):
                log_dir = ROOT / ".superpowers" / "sdd" / "2026-10-14-nuke-mcp-expansion"
                log_dir.mkdir(parents=True, exist_ok=True)
                log = stack.enter_context((log_dir / f"mcp-client-{index}.log").open("w", encoding="utf-8"))
                env = dict(os.environ, NUKE_MCP_PORT=str(port))
                streams = await stack.enter_async_context(stdio_client(
                    StdioServerParameters(command=sys.executable, args=[str(ROOT / "main.py")],
                                          cwd=str(ROOT), env=env), errlog=log))
                session = await stack.enter_async_context(ClientSession(*streams))
                await session.initialize()
                tools = {t.name: t for t in (await session.list_tools()).tools}
                for name, required in LEGACY.items():
                    assert name in tools, name
                    assert tools[name].inputSchema.get("required", []) == required, (name, tools[name].inputSchema)
                for name in ("get_capabilities", "get_operation_status", "cancel_operation", "start_render"):
                    assert name in tools, name
                sessions.append(session)
            capabilities = await asyncio.gather(*(s.call_tool("get_capabilities", {}) for s in sessions))
            receipts = [data(r) for r in capabilities]
            assert all(not r.isError for r in capabilities), receipts
            assert receipts[0]["server_instance_id"] == receipts[1]["server_instance_id"]
            assert receipts[0]["client_session_id"] != receipts[1]["client_session_id"]
            report["capabilities"] = receipts
            for _ in range(4):
                replies = await asyncio.gather(*(s.call_tool("get_script_info", {}) for s in sessions))
                for i, reply in enumerate(replies):
                    receipt = data(reply)
                    assert not reply.isError and receipt["ok"], receipt
                    assert receipt["client_session_id"] == receipts[i]["client_session_id"]
                    report["calls"].append(receipt)
            failure = await sessions[0].call_tool("get_node_info", {"node_name": "__MCP_PROBE_ABSENT__"})
            assert failure.isError, "Host failure was returned as MCP success"
            report["expected_error"] = data(failure)
            assert report["expected_error"]["error"]["code"]
            code = ("import os, threading\n"
                    "output['pid'] = os.getpid()\n"
                    "output['main_thread'] = threading.current_thread() is threading.main_thread()\n"
                    "output['script'] = nuke.root().name()")
            execution = await sessions[1].call_tool("execute_nuke_code", {"code": code})
            assert not execution.isError, data(execution)
            report["read_only_python"] = data(execution)
            if live:
                assert report["read_only_python"]["data"]["output"]["main_thread"] is True
            if not live:
                accepted = data(await sessions[0].call_tool("start_render", {
                    "write_node": "Write1", "first_frame": 1, "last_frame": 1}))
                assert accepted["state"] in ("queued", "running")
                began = time.monotonic()
                current = accepted
                while current["state"] in ("queued", "running"):
                    assert time.monotonic() - began < 25
                    await asyncio.sleep(.05)
                    current = data(await sessions[0].call_tool("get_operation_status", {
                        "request_id": accepted["request_id"],
                        "server_instance_id": accepted["server_instance_id"]}))
                assert current["ok"], current
                report["render_seconds"] = time.monotonic() - began
                report["render"] = current
                unsupported = await sessions[0].call_tool('create_node', {'node_type': '__UNAVAILABLE_CLASS__'})
                assert unsupported.isError, data(unsupported)
                report['unsupported_node'] = data(unsupported)
                runtime.stop()
                unavailable = await sessions[0].call_tool('get_capabilities', {})
                assert unavailable.isError and data(unavailable)['transport_error']
                report['unavailable_host'] = data(unavailable)
            report["passed"] = True
            report["unique_request_ids"] = len({r["request_id"] for r in report["calls"]})
            assert report["unique_request_ids"] == 8
    finally:
        if pump:
            pump.cancel()
            try:
                await pump
            except asyncio.CancelledError:
                pass
        if runtime:
            runtime.stop()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--slow", action="store_true")
    parser.add_argument("--port", type=int, default=9877)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = asyncio.run(probe(args.live, args.port, args.slow))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "mode": report["mode"],
                      "clients": 2, "verified_concurrent_reads": len(report["calls"]),
                      "render_seconds": report.get("render_seconds")}, indent=2))
