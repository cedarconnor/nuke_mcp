import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from tests.inspection_fakes import ImageHost, FileKnob, Knob
from nuke_mcp_bridge.protocol import BridgeError
from nuke_mcp_bridge.mutations import operation_guard

if importlib.util.find_spec('nuke_mcp_bridge.inspection'):
    from nuke_mcp_bridge import inspection as inspect
else:
    inspect = None

class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(inspect, 'Inspection implementation is missing')
        self.host = ImageHost()
    def test_nested_paths_disconnected_inputs_and_selection_scope(self):
        a = self.host.add('GroupA.Grade1')
        b = self.host.add('GroupB.Grade1')
        a.setInput(2, b)
        a.selected = True
        result = inspect.inspect_graph(self.host, selected_only=True)
        self.assertEqual([n['path'] for n in result['nodes']], ['GroupA.Grade1'])
        self.assertEqual(result['nodes'][0]['inputs'], [
            {'index':0, 'path':None}, {'index':1, 'path':None}, {'index':2, 'path':'GroupB.Grade1'}])
        self.assertEqual(result['scope']['selected_only'], True)
        self.assertTrue(a.selected)
    def test_truncation_and_unsupported_knobs_are_explicit(self):
        node = self.host.add('A')
        node._knobs = {'a':Knob(3), 'b':Knob('', 'PyScript_Knob'), 'c':Knob(9)}
        self.host.add('B')
        result = inspect.inspect_graph(self.host, max_nodes=1, max_knobs_per_node=2)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['observation']['coverage'], 'partial')
        self.assertEqual(result['nodes'][0]['parameters']['a']['value'], 3)
        self.assertEqual(result['nodes'][0]['omitted_knobs'][0]['reason'], 'unsupported_type')
        self.assertEqual(result['nodes'][0]['knobs_omitted_by_limit'], 1)
    def test_nc_empty_enumeration_never_claims_complete(self):
        self.host.env['nc'] = True
        self.host.add('Artist')
        self.host.blackout = True
        result = inspect.inspect_graph(self.host)
        self.assertEqual(result['observation']['coverage'], 'unknown')
        self.assertIn('nc', result['observation']['reason'])
        self.assertEqual(self.host.create_count, 0)
    def test_nonfinite_and_large_values_remain_json_safe_and_bounded(self):
        n = self.host.add('A')
        n._knobs = {'nan':Knob(float('nan')), 'long':Knob('x'*20000, 'String_Knob')}
        result = inspect.inspect_graph(self.host)
        self.assertTrue(result['truncated'])
        self.assertLess(len(json.dumps(result, allow_nan=False)), 10000)
        self.assertEqual(len(result['nodes'][0]['omitted_knobs']), 2)
    def test_read_channels_multipart_unavailable_fields_and_exact_paths(self):
        a = self.host.add('GroupA.Read1', 'Read')
        self.host.add('GroupB.Read1', 'Read')
        a._channels = ['beauty.red', 'beauty.green', 'depth.Z']
        del a._knobs['file']
        result = inspect.inspect_reads(self.host, ['GroupA.Read1'], channel_limit=2)
        read = result['reads'][0]
        self.assertEqual(read['path'], 'GroupA.Read1')
        self.assertEqual(read['channels'], ['beauty.red', 'beauty.green'])
        self.assertEqual(read['multipart']['part']['value'], 'beauty')
        self.assertTrue(read['truncated'])
        self.assertTrue(any(e['field']=='file' for e in read['errors']))
        with self.assertRaises(BridgeError): inspect.inspect_reads(self.host, ['Read1'])
    def test_sequence_evaluation_preserves_frame_and_uses_each_view(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base/'左.-001.l.exr').write_bytes(b'x')
            n = self.host.add('Read1', 'Read')
            n._knobs['file'] = FileKnob('[value root.label]/左.%04d.%v.exr',
                lambda f,v: str(base/'左.%04d.%v.exr'))
            result = inspect.validate_reads(self.host, -1, -1)
            self.assertEqual([c['status'] for c in result['checks']], ['exists','missing'])
            self.assertEqual([c['view'] for c in result['checks']], ['left','right'])
            self.assertEqual(result['checked_paths'], 2)
            self.assertEqual(self.host.frame_writes, [])
    def test_unresolved_expression_is_unknown_not_missing(self):
        n = self.host.add('Read1', 'Read')
        n._knobs['file'] = FileKnob('[bad]', lambda f,v: '[bad]/plate.%04d.exr')
        result = inspect.validate_reads(self.host, 1, 1)
        self.assertEqual(result['missing_paths'], 0)
        self.assertEqual(result['unknown_paths'], 2)
    def test_path_check_limit_is_enforced_before_evaluation(self):
        n = self.host.add('Read1', 'Read')
        n._knobs['file'] = FileKnob('[bad]', lambda f,v: '[bad]')
        result = inspect.validate_reads(self.host, 1, 5000)
        self.assertEqual(result['checked_paths'], 10000)
        with self.assertRaises(BridgeError) as error: inspect.validate_reads(self.host, 1, 5001)
        self.assertEqual(error.exception.code, 'limit_exceeded')
    def test_invalid_bounds_refused_and_cancelled_checks_retain_progress(self):
        self.host.add('Read1', 'Read')
        for kwargs in ({'max_nodes':1001}, {'max_nodes':True}, {'max_knobs_per_node':129}):
            with self.assertRaises(BridgeError): inspect.inspect_graph(self.host, **kwargs)
        with self.assertRaises(BridgeError): inspect.validate_reads(self.host, 2, 1)
        count = 0
        def guard():
            nonlocal count
            count += 1
            if count > 5: raise BridgeError('deadline_expired', 'test deadline')
        token = operation_guard.set(guard)
        try:
            with self.assertRaises(BridgeError) as error: inspect.validate_reads(self.host, 1, 50)
            self.assertGreater(error.exception.data['checked_paths'], 0)
            self.assertEqual(error.exception.outcome, 'not_started')
        finally: operation_guard.reset(token)
