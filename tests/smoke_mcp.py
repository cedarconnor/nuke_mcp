"""End-to-end smoke test for the stdio MCP server and live Nuke bridge."""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]


def checked_receipt(result):
    receipt = result.structuredContent
    if not receipt:
        raise RuntimeError('Missing protocol v2 structured result; upgrade both components')
    if result.isError or not receipt.get('ok'):
        prefix = 'LIVE_NUKE_UNAVAILABLE' if receipt.get('transport_error') else 'HOST_OPERATION_FAILED'
        raise RuntimeError(prefix + ': ' + json.dumps(receipt))
    return receipt


def result_text(result) -> str:
    return "\n".join(
        item.text for item in result.content if hasattr(item, "text")
    )


async def smoke_test(mutate: bool = False) -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(REPO_ROOT / "main.py")],
        cwd=str(REPO_ROOT),
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            listed = await session.list_tools()
            tool_names = sorted(tool.name for tool in listed.tools)
            if "get_script_info" not in tool_names:
                raise RuntimeError("get_script_info was not exposed by the MCP server")

            capabilities = checked_receipt(await session.call_tool('get_capabilities', arguments={}))
            result = await session.call_tool("get_script_info", arguments={})
            script_receipt = checked_receipt(result)

            response_text = result_text(result)
            if "Script:" not in response_text or "Total Nodes:" not in response_text:
                raise RuntimeError(
                    "Live Nuke response did not contain expected script information"
                )

            report = {
                "tool_count": len(tool_names),
                "tools": tool_names,
                "get_script_info": response_text,
                "receipt": script_receipt,
                "capabilities": capabilities,
            }

            if mutate:
                smoke_node = "MCP_SMOKE_" + uuid4().hex
                created = False
                report['mutation'] = {}
                try:
                    create_result = await session.call_tool(
                        "create_node",
                        arguments={
                            "node_type": "Grade",
                            "name": smoke_node,
                            "position": [0, 0],
                            "parameters": {"label": "Temporary MCP smoke test"},
                        },
                    )
                    create_text = result_text(create_result)
                    create_receipt = checked_receipt(create_result)
                    if create_receipt['data'].get('name') != smoke_node:
                        raise RuntimeError('Creation identity uncertain; no automatic retry or guessed cleanup')
                    if create_result.isError or "Error creating node" in create_text:
                        raise RuntimeError(
                            "Temporary Grade creation failed: {0}".format(
                                create_text
                            )
                        )
                    created = True

                    info_result = await session.call_tool(
                        "get_node_info",
                        arguments={"node_name": smoke_node},
                    )
                    info_text = result_text(info_result)
                    checked_receipt(info_result)
                    if info_result.isError or smoke_node not in info_text:
                        raise RuntimeError(
                            "Temporary Grade inspection failed: {0}".format(
                                info_text
                            )
                        )

                    report["mutation"] = {
                        "create": create_text,
                        "inspect": info_text,
                    }
                finally:
                    if created:
                        delete_result = await session.call_tool(
                            "delete_node",
                            arguments={"name": smoke_node},
                        )
                        delete_text = result_text(delete_result)
                        checked_receipt(delete_result)
                        if (
                            delete_result.isError
                            or "Error deleting node" in delete_text
                        ):
                            raise RuntimeError(
                                "Temporary Grade cleanup failed: {0}".format(
                                    delete_text
                                )
                            )
                        report["mutation"]["delete"] = delete_text

            print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mutate",
        action="store_true",
        help="Create, inspect, and delete one temporary Grade node.",
    )
    args = parser.parse_args()
    asyncio.run(smoke_test(mutate=args.mutate))
