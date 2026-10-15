"""End-to-end smoke test for the stdio MCP server and live Nuke bridge."""

import asyncio
import argparse
import json
import os
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


async def mutation_probe(session):
    name = 'MCP_SMOKE_' + uuid4().hex
    report = {'name': name, 'passed': False, 'cleanup': 'not_attempted_unverified_creation'}
    created = False
    try:
        result = await session.call_tool('create_node', arguments={
            'node_type': 'Grade', 'name': name, 'position': [0, 0],
            'parameters': {'label': 'Temporary MCP smoke test'}})
        report['create'] = result.structuredContent
        receipt = checked_receipt(result)
        if receipt['data'].get('path') != name:
            raise RuntimeError('Creation identity uncertain; no guessed cleanup')
        created = True
        info = await session.call_tool('get_node_info', arguments={'node_name': name})
        report['inspect'] = info.structuredContent
        checked_receipt(info)
        operations = [
            {'op':'set_knob', 'node_path':'root.' + name, 'knob':'label', 'value':'Verified batch smoke'},
            {'op':'position', 'node_path':'root.' + name, 'x':120, 'y':80},
        ]
        dry = await session.call_tool('batch_edit', arguments={'operations':operations})
        report['batch_dry_run'] = dry.structuredContent
        checked_receipt(dry)
        applied = await session.call_tool('batch_edit', arguments={'operations':operations, 'dry_run':False})
        report['batch_apply'] = applied.structuredContent
        receipt = checked_receipt(applied)
        if [item['outcome'] for item in receipt['data']['items']] != ['applied', 'applied']:
            raise RuntimeError('Batch did not verify both edits')
        report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        if created:
            try:
                deletion = await session.call_tool('delete_node', arguments={'name': 'root.' + name})
                report['delete'] = deletion.structuredContent
                checked_receipt(deletion)
                report['cleanup'] = 'verified_deleted'
            except Exception as exc:
                report['cleanup'] = 'uncertain'
                report['cleanup_error'] = str(exc)
                report['passed'] = False
    return report


async def verify_disposable_session(session, instance, pid, fixture):
    caps = checked_receipt(await session.call_tool('get_capabilities', arguments={}))
    if caps['server_instance_id'] != instance:
        raise RuntimeError('Disposable host instance changed')
    identity = checked_receipt(await session.call_tool('execute_nuke_code', arguments={'code':
        "import os\noutput['pid']=os.getpid()\noutput['path']=nuke.root().name()\noutput['disposable']=os.environ.get('NUKE_MCP_DISPOSABLE_SESSION')"}))
    facts = identity['data']['output']
    if (identity['server_instance_id'] != instance or facts.get('pid') != pid or
            facts.get('disposable') != '1' or Path(facts.get('path','')).resolve() != fixture.resolve()):
        raise RuntimeError('Disposable fixture identity changed')


async def isolated_mutation_probe(port, instance, pid, fixture):
    """Called only after the qualification runner verifies its disposable fixture."""
    server = StdioServerParameters(command=sys.executable, args=[str(REPO_ROOT/'main.py')],
                                   cwd=str(REPO_ROOT), env=dict(os.environ, NUKE_MCP_PORT=str(port)))
    async with stdio_client(server) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            await verify_disposable_session(session, instance, pid, fixture)
            return await mutation_probe(session)


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
                report['mutation'] = await mutation_probe(session)

            print(json.dumps(report, indent=2))
            if mutate and not report['mutation']['passed']:
                raise RuntimeError('Live mutation qualification incomplete; see the structured report')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mutate",
        action="store_true",
        help="Create, inspect, and delete one temporary Grade node.",
    )
    args = parser.parse_args()
    if args.mutate:
        parser.error('Use tests/live/qualify.py --scenario verified-edit --mutate --disposable --pid PID --fixture PATH --output NEW_DIRECTORY')
    asyncio.run(smoke_test())
