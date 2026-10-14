import asyncio
import unittest
from fastmcp import FastMCP
from tests.fakes import request
from nuke_mcp_bridge.protocol import make_result
from nuke_mcp_bridge.mcp_adapter import to_mcp_result, bridge_tool, capture_receipt


class AdapterTests(unittest.TestCase):
    def test_failed_optional_read_does_not_hide_successful_mutation(self):
        first = dict(make_result(request(), state='failed', outcome='not_started',
                     error={'code': 'busy', 'message': 'Session busy'}), command='get_node_info')
        changed = dict(make_result(request(), outcome='applied'), command='modify_node')
        mcp = FastMCP('test')
        @bridge_tool(mcp)
        def modify() -> str:
            capture_receipt(first)
            capture_receipt(changed)
            return 'Modified node Grade1'
        async def check():
            result = (await (await mcp.get_tool('modify')).run({})).to_mcp_result()
            self.assertFalse(result.isError)
            self.assertEqual(result.structuredContent['request_id'], changed['request_id'])
            self.assertEqual(result.structuredContent['outcome'], 'applied')
            self.assertTrue(result.structuredContent['warnings'])
            self.assertEqual(result.structuredContent['operation_receipts'], [first, changed])
        asyncio.run(check())

    def test_failure_after_applied_step_cannot_report_not_started(self):
        first = dict(make_result(request(), outcome='applied'), command='modify_node')
        failed = dict(make_result(request(), state='failed', outcome='not_started',
                      error={'code': 'busy', 'message': 'Session busy'}), command='position_node')
        mcp = FastMCP('test')
        @bridge_tool(mcp)
        def modify() -> str:
            capture_receipt(first)
            capture_receipt(failed)
            return 'Error positioning node'
        async def check():
            result = (await (await mcp.get_tool('modify')).run({})).to_mcp_result()
            self.assertTrue(result.isError)
            self.assertEqual(result.structuredContent['outcome'], 'partial')
            self.assertEqual(result.structuredContent['operation_receipts'], [first, failed])
        asyncio.run(check())

    def test_error_retains_structured_receipt(self):
        receipt = make_result(request(), state="failed", outcome="unknown",
                              error={"code": "state_uncertain", "message": "Unknown"})
        result = to_mcp_result(receipt, "Could not verify").to_mcp_result()
        self.assertTrue(result.isError)
        self.assertEqual(result.structuredContent["request_id"], receipt["request_id"])
        self.assertEqual(result.structuredContent["outcome"], "unknown")

    def test_accepted_operation_is_not_false_mcp_error(self):
        result = to_mcp_result(make_result(request(), state="queued"), "Queued").to_mcp_result()
        self.assertFalse(result.isError)
        self.assertFalse(result.structuredContent["ok"])

    def test_legacy_caught_error_is_still_an_mcp_error(self):
        mcp = FastMCP("test")
        receipt = make_result(request(), state="failed", outcome="unknown",
                              error={"code": "host_error", "message": "native failure"})
        @bridge_tool(mcp)
        def old_tool(node_name: str) -> str:
            capture_receipt(receipt)
            return "Error getting node: native failure"
        async def check():
            tool = await mcp.get_tool("old_tool")
            self.assertEqual(tool.parameters["required"], ["node_name"])
            result = (await tool.run({"node_name": "x"})).to_mcp_result()
            self.assertTrue(result.isError)
            self.assertEqual(result.structuredContent["error"]["code"], "host_error")
        asyncio.run(check())

    def test_local_validation_failure_has_no_fabricated_host_receipt(self):
        mcp = FastMCP("test")
        @bridge_tool(mcp)
        def local_fail(name: str) -> str:
            return "Error creating node: invalid parameter"
        async def check():
            result = (await (await mcp.get_tool("local_fail")).run({"name": "x"})).to_mcp_result()
            self.assertTrue(result.isError)
            self.assertEqual(result.structuredContent["outcome"], "not_started")
            self.assertEqual(result.structuredContent["source"], "mcp_validation")
        asyncio.run(check())
