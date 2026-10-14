import unittest
from tests.mutation_fakes import Host
from nuke_mcp_bridge import batch
from nuke_mcp_bridge.protocol import BridgeError

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.host=Host(); self.a=self.host.add('A'); self.b=self.host.add('B')
    def knob(self, node, value): return {'op':'set_knob','node_path':node,'knob':'gain','value':value}
    def test_dry_run_does_not_write_or_open_undo_group(self):
        result=batch.execute_batch(self.host,[self.knob('A',2)])
        self.assertEqual(self.a['gain'].value(),1)
        self.assertEqual(result['items'][0]['outcome'],'not_started')
        self.assertEqual(self.host.undo_begins,0)
    def test_full_preflight_prevents_first_write_when_later_item_invalid(self):
        operations=[self.knob('A',2),dict(self.knob('B',3),knob='missing')]
        with self.assertRaises(BridgeError) as failure: batch.execute_batch(self.host,operations,False)
        self.assertEqual(self.a['gain'].value(),1)
        self.assertEqual(failure.exception.outcome,'not_started')
        self.assertEqual(len(failure.exception.data['items']),2)
    def test_success_uses_one_undo_group_and_explicit_disconnect(self):
        operations=[self.knob('A',2),{'op':'connect','node_path':'B','input_index':0,'source_path':'A'},
                    {'op':'position','node_path':'B','x':10,'y':20}]
        result=batch.execute_batch(self.host,operations,False)
        self.assertEqual([x['outcome'] for x in result['items']],['applied']*3)
        self.assertIs(self.b.input(0),self.a)
        self.assertEqual((self.host.undo_begins,self.host.undo_ends),(1,1))
        batch.execute_batch(self.host,[dict(operations[1],source_path=None)],False)
        self.assertIsNone(self.b.input(0))
    def test_runtime_failure_preserves_success_and_marks_unstarted_tail(self):
        self.b['gain'].fail_after=True
        c=self.host.add('C')
        with self.assertRaises(BridgeError) as failure:
            batch.execute_batch(self.host,[self.knob('A',2),self.knob('B',3),self.knob('C',4)],False)
        self.assertEqual([i['outcome'] for i in failure.exception.data['items']],['applied','unknown','not_started'])
        self.assertEqual(self.a['gain'].value(),2)
        self.assertEqual(c['gain'].value(),1)
        self.assertEqual(self.host.global_undos,0)
        self.assertEqual(self.host.undo_ends,1)
    def test_duplicate_target_aliases_and_unsupported_operations_rejected(self):
        for operations in ([self.knob('A',2),self.knob('root.A',3)],
                           [{'op':'delete','node_path':'A'}], [self.knob('A',2)]*101):
            with self.assertRaises(BridgeError): batch.execute_batch(self.host,operations,False)
        self.assertEqual(self.a['gain'].value(),1)
    def test_revision_guarantee_is_unavailable_without_provider(self):
        with self.assertRaises(BridgeError) as failure:
            batch.execute_batch(self.host,[self.knob('A',2)],False,expected_revision=1)
        self.assertEqual(failure.exception.code,'revision_unavailable')
        self.assertEqual(self.host.undo_begins,0)
    def test_artist_change_after_preflight_is_preserved(self):
        begin=self.host.begin
        def artist_change(label):
            begin(label); self.a['gain'].v=9
        self.host.begin=artist_change
        with self.assertRaises(BridgeError) as failure:
            batch.execute_batch(self.host,[self.knob('A',2)],False)
        self.assertEqual(self.a['gain'].value(),9)
        self.assertEqual(failure.exception.code,'batch_failed')
        self.assertEqual(failure.exception.data['items'][0]['error']['code'],'state_conflict')
    def test_schema_validation_is_before_host_writes(self):
        for bad in ([dict(self.knob('A',2),extra=1)], [], 'bad'):
            with self.assertRaises(BridgeError): batch.execute_batch(self.host,bad,False)
        self.assertEqual(self.a['gain'].value(),1)
