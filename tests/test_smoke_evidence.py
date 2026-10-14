import asyncio
import unittest
from types import SimpleNamespace
from tests import smoke_mcp

class SmokeEvidenceTests(unittest.TestCase):
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
