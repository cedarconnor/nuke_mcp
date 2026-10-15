import asyncio
import unittest
from types import SimpleNamespace
from tests import smoke_mcp

class SmokeEvidenceTests(unittest.TestCase):
    def test_uncertain_batch_keeps_evidence_without_further_cleanup(self):
        calls=[]
        class Session:
            async def call_tool(self, name, arguments):
                calls.append(name)
                data = {'path':arguments.get('name')} if name == 'create_node' else {}
                fail = name == 'batch_edit'
                return SimpleNamespace(isError=fail, content=[], structuredContent={
                    'ok':not fail, 'data':data, 'outcome':'unknown' if fail else 'applied',
                    'error':{'code':'state_uncertain'} if fail else None})
        report=asyncio.run(smoke_mcp.mutation_probe(Session()))
        self.assertFalse(report['passed'])
        self.assertEqual(report['batch_dry_run']['outcome'], 'unknown')
        self.assertEqual(report['cleanup'], 'uncertain')
        self.assertEqual(calls, ['create_node','get_node_info','batch_edit'])

    def test_failed_creation_is_recorded_without_retry_or_guessed_delete(self):
        calls=[]
        class Session:
            async def call_tool(self, name, arguments):
                calls.append(name)
                return SimpleNamespace(isError=True, content=[], structuredContent={
                    'ok':False, 'outcome':'unknown', 'error':{'code':'state_uncertain'}})
        report=asyncio.run(smoke_mcp.mutation_probe(Session()))
        self.assertEqual(calls, ['create_node'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['create']['outcome'], 'unknown')
        self.assertEqual(report['cleanup'], 'not_attempted_unverified_creation')
