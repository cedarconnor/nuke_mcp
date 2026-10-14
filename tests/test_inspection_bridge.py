import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastmcp import Client
from tests.inspection_fakes import ImageHost
from nuke_mcp_bridge.protocol import BridgeError, make_result
from nuke_mcp_bridge.mcp_adapter import capture_receipt

class InspectionBridgeTests(unittest.TestCase):
    def test_legacy_node_info_uses_exact_paths_and_bounded_structured_data(self):
        host = ImageHost()
        host.menu = lambda name: SimpleNamespace(addCommand=lambda *args: None)
        a = host.add('A.Grade1')
        b = host.add('B.Grade1')
        a.setInput(0,b)
        with patch.dict(sys.modules, {'nuke':host, 'nukescripts':SimpleNamespace(PythonPanel=object)}):
            spec = importlib.util.spec_from_file_location('inspection_addon', Path(__file__).resolve().parents[1]/'nuke_mcp_addon.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        addon = module.NukeMCPServer()
        result = addon.get_node_info('A.Grade1')
        self.assertEqual(result.get('path'), 'A.Grade1')
        self.assertEqual(result['inputs'][0]['path'], 'B.Grade1')
        with self.assertRaises(BridgeError): addon.get_node_info('Grade1')

    def test_legacy_overview_text_discloses_incomplete_observation(self):
        import nuke_mcp_server as server
        class Connection:
            def send_command(self, *args):
                data = {'nodes':[], 'observation':{'coverage':'unknown','reason':'nc_observation_unreliable'}, 'truncated':False}
                capture_receipt(make_result({},data=data,observation=data['observation']))
                return data
        async def check():
            with patch.object(server,'get_nuke_connection',return_value=Connection()):
                async with Client(server.mcp) as client:
                    result = await client.call_tool('get_script_info', {})
                    text = '\n'.join(c.text for c in result.content)
                    self.assertIn('unknown', text)
                    self.assertIn('Observed Nodes: 0', text)
        asyncio.run(check())
