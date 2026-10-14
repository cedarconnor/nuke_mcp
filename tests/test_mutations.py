import unittest
from tests.mutation_fakes import Host, Knob
from nuke_mcp_bridge import mutations as m
from nuke_mcp_bridge.protocol import BridgeError

class MutationTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.node = self.host.add('Grade1')
    def failure(self, fn, outcome='not_started'):
        with self.assertRaises(BridgeError) as err: fn()
        self.assertEqual(err.exception.outcome, outcome)
        return err.exception
    def test_handleless_creation_never_retries_or_deletes_candidates(self):
        self.host.create_returns_none = True
        self.host.blackout = True
        self.failure(lambda: m.create_node(self.host, 'Grade'), 'unknown')
        self.assertEqual(self.host.create_count, 1)
        self.assertEqual(len(self.host.graph), 2)
        self.assertEqual(self.host.deleted, [])
    def test_create_preserves_selection_and_uses_explicit_inputs(self):
        self.node.selected = True
        result = m.create_node(self.host, 'StudioPlugin', inputs=['Grade1'], parameters={'gain': 2.0})
        created = self.host.graph[result['path']]
        self.assertIs(created.input(0), self.node)
        self.assertTrue(self.node.selected)
        self.assertFalse(created.selected)
        self.assertEqual(created['gain'].value(), 2.0)
        self.assertEqual(result['type'], 'StudioPlugin')
    def test_unavailable_class_does_not_create(self):
        self.failure(lambda: m.create_node(self.host, 'MissingPlugin'))
        self.assertEqual(self.host.create_count, 0)
    def test_invalid_creation_values_fail_before_creation(self):
        for params in ({'gain': float('nan')}, {'knobChanged': 'run()'}):
            self.failure(lambda: m.create_node(self.host, 'Grade', parameters=params))
        self.assertEqual(self.host.create_count, 0)
    def test_partial_creation_only_rolls_back_returned_owned_handle(self):
        self.failure(lambda: m.create_node(self.host, 'Grade', parameters={'missing': 1}), 'rolled_back')
        self.assertEqual(set(self.host.graph), {'Grade1'})
        self.assertNotIn('Grade1', self.host.deleted)
    def test_failed_owned_cleanup_reports_partial(self):
        self.host.fail_delete = True
        err = self.failure(lambda: m.create_node(self.host, 'Grade', parameters={'missing': 1}), 'partial')
        self.assertTrue(err.data['created_path'])
        self.assertEqual(len(self.host.graph), 2)
    def test_exact_group_path_and_ambiguous_short_name(self):
        other = self.host.add('Group.Grade1')
        self.failure(lambda: m.resolve_node(self.host, 'Grade1'))
        self.assertIs(m.resolve_node(self.host, 'Group.Grade1'), other)
        self.assertIs(m.resolve_node(self.host, 'root.Grade1'), self.node)
    def test_nc_empty_lookup_is_uncertain_not_absence(self):
        self.host.blackout = True
        err = self.failure(lambda: m.resolve_node(self.host, 'Grade1'))
        self.assertEqual(err.code, 'state_uncertain')
        self.assertEqual(len(self.host.graph), 1)
    def test_static_knob_readback_and_arrays(self):
        self.assertEqual(m.set_knob(self.host, 'Grade1', 'gain', 2)['value'], 2)
        self.assertEqual(m.set_knob(self.host, 'Grade1', 'translate', [3, 4])['value'], [3, 4])
        self.failure(lambda: m.set_knob(self.host, 'Grade1', 'translate', 7))
        self.failure(lambda: m.set_knob(self.host, 'Grade1', 'translate', [1]))
        self.assertEqual(self.node['translate'].value(), [3, 4])
    def test_executable_dynamic_and_nonfinite_knobs_rejected(self):
        self.node._knobs['button'] = Knob('', 'PyScript_Knob')
        for key, value in [('button','x'), ('knobChanged','x'), ('gain',float('inf'))]:
            self.failure(lambda: m.set_knob(self.host, 'Grade1', key, value))
        for flag in ('animated', 'expression'):
            setattr(self.node['gain'], flag, True)
            self.failure(lambda: m.set_knob(self.host, 'Grade1', 'gain', 3))
            setattr(self.node['gain'], flag, False)
        self.assertEqual(self.node['gain'].value(), 1)
    def test_failed_readback_or_write_exception_is_unknown_without_undo(self):
        self.node['gain'].ignore = True
        self.failure(lambda: m.set_knob(self.host, 'Grade1', 'gain', 4), 'unknown')
        self.node['gain'].ignore = False
        self.node['gain'].fail_after = True
        self.failure(lambda: m.set_knob(self.host, 'Grade1', 'gain', 4), 'unknown')
        self.assertEqual(self.node['gain'].value(), 4)
    def test_connections_and_positions_are_validated_and_read_back(self):
        source = self.host.add('Source')
        m.connect_input(self.host, 'Grade1', 0, 'Source')
        self.assertIs(self.node.input(0), source)
        m.connect_input(self.host, 'Grade1', 0, None)
        self.assertIsNone(self.node.input(0))
        self.failure(lambda: m.connect_input(self.host, 'Grade1', -1, 'Source'))
        self.failure(lambda: m.position_node(self.host, 'Grade1', 1.5, 2))
        self.assertEqual(m.position_node(self.host, 'Grade1', 10, 20)['position'], [10,20])
        self.node.ignore_position = True
        self.failure(lambda: m.position_node(self.host, 'Grade1', 30, 40), 'unknown')
    def test_deletion_requires_affirmative_destroy_evidence_in_nc(self):
        result = m.delete_node(self.host, 'Grade1')
        self.assertEqual(result['deleted'], 'Grade1')
        self.assertEqual(self.host.destroy_callbacks, [])
        self.host.add('Other')
        self.host.emit_destroy = False
        self.failure(lambda: m.delete_node(self.host, 'Other'), 'unknown')
        self.assertNotIn('Other', self.host.graph)
        self.assertEqual(self.host.destroy_callbacks, [])

    def test_uniform_array_readback_uses_components(self):
        knob = self.node['translate']
        original = knob.value
        knob.value = lambda index=None: original(index) if index is not None else original(0)
        result = m.set_knob(self.host, 'Grade1', 'translate', [2., 2.])
        self.assertEqual(result['before'], [0., 0.])
        self.assertEqual(result['value'], [2., 2.])

    def test_wh_knob_accepts_fractional_dimensions(self):
        self.node._knobs['size'] = Knob([0., 0.], 'WH_Knob')
        self.assertEqual(m.set_knob(self.host, 'Grade1', 'size', [2.5, 2.5])['value'], [2.5, 2.5])

    def test_array_stops_when_callback_introduces_animation(self):
        knob = self.node['translate']
        setter = knob.setValue
        writes = []
        def set_value(value, index=None):
            writes.append(index)
            setter(value, index)
            knob.animated = True
        knob.setValue = set_value
        err = self.failure(lambda: m.set_knob(self.host, 'Grade1', 'translate', [2., 3.]), 'unknown')
        self.assertEqual(writes, [0])
        self.assertEqual(knob.v, [2., 0.])
        self.assertEqual(err.data['path'], 'Grade1')
        self.assertEqual(err.data['completed_components'], [0])

    def test_creation_final_readback_after_dependent_and_selection_callbacks(self):
        for trigger in ('label', 'selection'):
            with self.subTest(trigger=trigger):
                host = Host()
                factory = host.nodes.Grade
                def create(**kwargs):
                    node = factory(**kwargs)
                    if trigger == 'label':
                        setter = node['label'].setValue
                        def set_label(value):
                            setter(value)
                            node['gain'].v = 9.
                        node['label'].setValue = set_label
                    else:
                        def select(value):
                            node.selected = value
                            node['gain'].v = 9.
                        node.setSelected = select
                    return node
                host.nodes.Grade = create
                err = self.failure(lambda: m.create_node(host, 'Grade', parameters={'gain':2., 'label':'trigger'}), 'unknown')
                self.assertEqual(err.data['created_path'], 'Grade1')
                self.assertEqual(err.data['parameters']['gain'], 9.)
                self.assertEqual(host.create_count, 1)
                self.assertEqual(host.deleted, [])

    def test_creation_retains_cleanup_evidence_when_selection_restore_fails(self):
        self.node.selected = True
        def fail_select(value): raise RuntimeError('selection failed')
        self.node.setSelected = fail_select
        self.host.fail_delete = True
        err = self.failure(lambda: m.create_node(self.host, 'Grade', parameters={'missing':1}), 'unknown')
        self.assertTrue(err.data['created_path'])
        self.assertIn('delete failed', err.data['cleanup_error'])
        self.assertIn('selection failed', err.data['selection_error'])
