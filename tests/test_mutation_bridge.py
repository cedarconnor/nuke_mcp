import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastmcp import Client
from nuke_mcp_bridge.protocol import BridgeError
from tests.mutation_fakes import Host

class BridgeMutationTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host.menu = lambda name: SimpleNamespace(addCommand=lambda *args: None)
        with patch.dict(sys.modules, {'nuke': self.host, 'nukescripts': SimpleNamespace(PythonPanel=object)}):
            spec = importlib.util.spec_from_file_location('mutation_addon', Path(__file__).resolve().parents[1] / 'nuke_mcp_addon.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.addon = module.NukeMCPServer()
    def test_host_creation_rejects_invalid_knob_and_preserves_artist_node(self):
        artist = self.host.add('Artist')
        with self.assertRaises(BridgeError):
            self.addon.create_node('Grade', parameters={'missing': 1})
        self.assertEqual(list(self.host.graph.values()), [artist])
    def test_host_position_requires_actual_requested_readback(self):
        node = self.host.add('Artist')
        node.ignore_position = True
        with self.assertRaises(BridgeError): self.addon.position_node('Artist', [22, 33])
    def test_backdrop_uses_typed_creation_without_raw_code(self):
        import nuke_mcp_server as server
        seen = []
        class Connection:
            def send_command(self, command, params):
                seen.append((command, params))
                return {'name': 'Backdrop1', 'path': 'Backdrop1', 'type': 'BackdropNode', 'executed': True, 'output': {}}
        async def check():
            with patch.object(server, 'get_nuke_connection', return_value=Connection()):
                async with Client(server.mcp) as client:
                    await client.call_tool('create_node', {'node_type':'BackdropNode', 'parameters':{'label':'quote " and newline\n'}})
        asyncio.run(check())
        self.assertEqual(seen[0][0], 'create_node')
        self.assertEqual(seen[0][1]['parameters'], {'label':'quote " and newline\n'})
