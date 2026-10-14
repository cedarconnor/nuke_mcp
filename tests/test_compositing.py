import importlib.util
import unittest
import tempfile
from pathlib import Path
from nuke_mcp_bridge.protocol import BridgeError
from nuke_mcp_bridge.mutations import operation_context
from tests.test_manifests import comp_manifest
from tests.workflow_fakes import WorkflowHost, Enum
from tests.mutation_fakes import Knob

if importlib.util.find_spec('nuke_mcp_bridge.compositing'):
    from nuke_mcp_bridge import compositing as c
else:c=None

class CompositingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(c,'Compositing implementation missing')
        self.host=WorkflowHost().setup()
        self.a=self.host.add('Base');self.b=self.host.add('Light');self.artist=self.host.add('Artist')
        self.artist.selected=True
        self.manifest=comp_manifest()
        self.manifest['layers'][0]['source_node_path']='root.Base'
        self.manifest['layers'][1]['source_node_path']='root.Light'
        token=operation_context.set({'server_instance_id':'fixture'})
        self.addCleanup(operation_context.reset,token)
    def plan(self):return c.plan_layered_comp(self.host,self.manifest)
    def build(self,plan):return c.build_layered_comp(self.host,self.manifest,plan['digest'])
    def test_plus_order_mask_and_preserved_artist_state(self):
        mask=self.host.add('Mask')
        self.manifest['layers'][1].update(mask_node_path='root.Mask',mask_channel='rgba.alpha')
        original=dict(self.host.graph)
        result=self.build(self.plan())
        self.assertEqual(result['group_path'],'AOV')
        merge=self.host.graph['AOV.Merge_light']
        self.assertEqual(merge.input(0).fullName(),'AOV.Shuffle_base')
        self.assertEqual(merge.input(1).fullName(),'AOV.Shuffle_light')
        self.assertEqual(merge.input(2).fullName(),'AOV.Input_2')
        self.assertEqual(merge['operation'].value(),'plus')
        for path,node in original.items():self.assertIs(self.host.graph[path],node)
        self.assertTrue(self.artist.selected)
        self.assertFalse(self.host.graph['AOV'].selected)
        self.assertEqual(self.host.script_clear_count,0);self.assertEqual(self.host.render_count,0)
    def test_absent_channels_and_changed_channels_refuse_before_creation(self):
        plan=self.plan();self.b._channels=['rgba.red']
        with self.assertRaises(BridgeError):self.build(plan)
        self.assertEqual(self.host.create_count,0)
    def test_duplicate_nested_short_names_are_not_guessed(self):
        self.host.add('GroupA','Group');self.host.add('GroupB','Group')
        self.host.add('GroupA.Same');self.host.add('GroupB.Same')
        self.manifest=comp_manifest()
        with self.assertRaises(BridgeError) as caught:self.plan()
        self.assertEqual(caught.exception.code,'cross_scope_sources')
        self.assertEqual(self.host.create_count,0)
    def test_same_nested_scope_builds_owned_nested_group(self):
        self.host.add('Pack','Group');self.host.add('Pack.One');self.host.add('Pack.Two')
        for layer,name in zip(self.manifest['layers'],('Pack.One','Pack.Two')):layer['source_node_path']=name
        result=self.build(self.plan())
        self.assertEqual(result['group_path'],'Pack.AOV')
    def test_collision_refused(self):
        self.host.add('AOV','Group')
        with self.assertRaises(BridgeError):self.plan()
        self.assertEqual(self.host.create_count,0)
    def test_shuffle2_variant_and_over(self):
        del self.host.nodes.Shuffle
        def make(**kw):
            node=self.host.create('Shuffle2',**kw)
            node._knobs.update(in1=Enum('rgba',['rgba']),out1=Enum('rgba',['rgba']),mappings=Knob([],'ChannelMapping_Knob'))
            return node
        self.host.nodes.Shuffle2=make
        self.manifest['layers'][1]['operation']='over'
        self.build(self.plan())
        mappings=self.host.graph['AOV.Shuffle_base']['mappings'].value()
        self.assertEqual(mappings[3],(0,'rgba.alpha','rgba.alpha'))
    def test_handleless_creation_stops_without_retry_or_cleanup(self):
        plan=self.plan();self.host.create_returns_none=True
        with self.assertRaises(BridgeError) as caught:self.build(plan)
        self.assertEqual(caught.exception.outcome,'unknown')
        self.assertEqual(self.host.create_count,1);self.assertEqual(self.host.deleted,[])
        self.assertTrue(self.artist.selected)
    def test_unknown_shuffle_layout_fails_inside_owned_group(self):
        original=self.host.nodes.Shuffle
        def make(**kw):
            node=original(**kw);node._knobs.pop('in');return node
        self.host.nodes.Shuffle=make
        with self.assertRaises(BridgeError) as caught:self.build(self.plan())
        self.assertEqual(caught.exception.data['group_path'],'AOV')
        self.assertIs(self.host.graph['Artist'],self.artist)

    def test_file_source_uses_observed_read_without_plan_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'plate.exr';path.write_bytes(b'fixture')
            read=self.host.add('Observed','Read');read['file'].v=str(path)
            self.manifest['layers']=[{'id':'base','source_file':str(path),'colorspace':'linear','channel_layer':'rgba'}]
            plan=self.plan();self.assertEqual(self.host.create_count,0)
            result=self.build(plan)
            self.assertEqual(result['group_path'],'AOV')

    def test_extra_callback_connection_is_not_reported_success(self):
        original=self.artist.setSelected
        def select(value):
            original(value)
            if value and 'AOV.Merge_light' in self.host.graph:
                self.host.graph['AOV.Merge_light'].setInput(2,self.host.graph['AOV.Shuffle_base'])
        self.artist.setSelected=select
        with self.assertRaises(BridgeError):self.build(self.plan())
