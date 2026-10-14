import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import os
import subprocess
import unittest
from unittest.mock import patch
from nuke_mcp_bridge.protocol import BridgeError
from nuke_mcp_bridge.operations import OperationRegistry
from tests.test_manifests import shot_manifest
from tests.workflow_fakes import WorkflowHost

if importlib.util.find_spec('nuke_mcp_bridge.shots'):
    from nuke_mcp_bridge import shots as s
else:s=None

class ShotTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(s,'Shot workflow implementation missing')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.library=self.root/'library';self.library.mkdir()
        self.host=WorkflowHost().setup();self.registry=OperationRegistry()
        self.token=s.operation_context.set({'server_instance_id':self.registry.instance_id,'request_id':'test'})
        self.addCleanup(s.operation_context.reset,self.token)
        self.env=patch.dict('os.environ',{'NUKE_MCP_DISPOSABLE_SESSION':'1'});self.env.start();self.addCleanup(self.env.stop)
        self.manifest=shot_manifest(str(self.root))
        self.plate=self.root/'plate.exr';self.plate.write_bytes(b'plate')
        shot=self.manifest['shots'][0];shot['plates'][0]['path']=str(self.plate)
        shot['write']['path']='[file dirname [value root.name]]/out.%04d.exr'
    def plan(self):return s.plan_shot_setup(self.host,self.manifest,self.library)
    def apply(self,plan):return s.apply_shot_setup(self.host,self.manifest,plan['digest'],self.library,self.registry)
    def test_plan_is_readonly_and_two_shot_publication(self):
        second=copy.deepcopy(self.manifest['shots'][0]);second.update(shot_id='sh020',script_path=str(self.root/'sh020.nknc'))
        second['write']['path']=str(self.root/'second.%04d.exr');self.manifest['shots'].append(second)
        original=self.root/'original.nknc';original.write_text('{"graph":[]}');self.host.script_path=str(original)
        plan=self.plan();self.assertEqual(self.host.script_clear_count,0)
        result=self.apply(plan)
        self.assertEqual(len(result['completed']),2)
        self.assertTrue(result['restoration']['ok'])
        self.assertEqual(self.host.script_path,str(original))
        self.assertEqual(self.host.script_clear_count,2)
        for record in result['completed']:
            self.assertTrue(record['fresh_script'])
            self.assertTrue(record['published'])
            self.assertTrue(Path(record['script_path']).exists())
            self.assertNotIn('stage',record['write_paths'][0])
    def test_dirty_or_non_disposable_refused(self):
        plan=self.plan();self.host.modified=True
        with self.assertRaises(BridgeError):self.apply(plan)
        self.host.modified=False
        with patch.dict('os.environ',{'NUKE_MCP_DISPOSABLE_SESSION':'0'}):
            with self.assertRaises(BridgeError):self.apply(plan)
        self.assertEqual(self.host.script_clear_count,0)
    def test_changed_input_instance_and_target_refused_before_clear(self):
        plan=self.plan();self.plate.write_bytes(b'changed')
        with self.assertRaises(BridgeError):self.apply(plan)
        plan=self.plan()
        token=s.operation_context.set({'server_instance_id':'changed'})
        try:
            with self.assertRaises(BridgeError):self.apply(plan)
        finally:s.operation_context.reset(token)
        Path(self.manifest['shots'][0]['script_path']).write_text('artist')
        with self.assertRaises(BridgeError):self.apply(plan)
        self.assertEqual(self.host.script_clear_count,0)
    def test_output_escape_and_collision(self):
        self.manifest['shots'][0]['script_path']=str(self.root.parent/'outside.nknc')
        with self.assertRaises(BridgeError):self.plan()
        self.manifest=shot_manifest(str(self.root));self.manifest['shots'][0]['plates'][0]['path']=str(self.plate)
        (self.root/'out.-002.exr').write_text('existing')
        with self.assertRaises(BridgeError):self.plan()
    def test_second_save_failure_preserves_first_and_reconciles(self):
        second=copy.deepcopy(self.manifest['shots'][0]);second.update(shot_id='sh020',script_path=str(self.root/'sh020.nknc'))
        second['write']['path']=str(self.root/'second.%04d.exr');self.manifest['shots'].append(second)
        count=[]
        def fail(path):
            count.append(path)
            if len(count)==2:raise RuntimeError('interrupted second save')
        self.host.save_hook=fail
        plan=self.plan()
        with self.assertRaises(BridgeError) as caught:self.apply(plan)
        self.assertEqual(len(caught.exception.data['completed']),1)
        first=Path(self.manifest['shots'][0]['script_path']);before=first.read_bytes()
        self.assertFalse((self.root/'sh020.nknc').exists())
        with self.assertRaises(BridgeError):self.apply(plan)
        self.assertEqual(first.read_bytes(),before)
    def test_source_changes_during_save_blocks_publication(self):
        self.host.save_hook=lambda path:self.plate.write_bytes(b'new source')
        with self.assertRaises(BridgeError):self.apply(self.plan())
        self.assertFalse(Path(self.manifest['shots'][0]['script_path']).exists())
    def test_published_reload_failure_keeps_artifact(self):
        self.host.open_hook=lambda path:(_ for _ in ()).throw(RuntimeError('reload failed'))
        with self.assertRaises(BridgeError) as caught:self.apply(self.plan())
        self.assertTrue(caught.exception.data['current']['published'])
        self.assertTrue(Path(self.manifest['shots'][0]['script_path']).exists())

    def test_reloaded_knob_corruption_is_not_completed(self):
        def corrupt(path):self.host.graph['ShotWrite']['colorspace'].v='raw'
        self.host.open_hook=corrupt
        with self.assertRaises(BridgeError) as caught:self.apply(self.plan())
        self.assertEqual(caught.exception.data['completed'],[])
        self.assertTrue(caught.exception.data['current']['published'])

    def test_original_restoration_does_not_destroy_callback_switched_script(self):
        original=self.root/'original.nknc';original.write_text('{"graph":[]}');self.host.script_path=str(original)
        other=str(self.root/'artist.nknc')
        def switch(path):
            self.host.script_path=other;self.host.modified=True
            raise RuntimeError('callback switched script')
        self.host.save_hook=switch
        with self.assertRaises(BridgeError) as caught:self.apply(self.plan())
        self.assertEqual(self.host.script_path,other)
        self.assertTrue(self.host.modified)
        self.assertFalse(caught.exception.data['restoration']['ok'])

    def test_constructor_script_switch_stops_before_configuration_and_publication(self):
        plan=self.plan();constructor=self.host.nodes.Read
        def switch(**kw):
            node=constructor(**kw)
            self.host.script_path=str(self.root/'artist.nknc')
            self.host.add('ArtistOnly');self.host.modified=True
            return node
        self.host.nodes.Read=switch
        with self.assertRaises(BridgeError) as caught:self.apply(plan)
        self.assertFalse(Path(self.manifest['shots'][0]['script_path']).exists())
        self.assertNotIn('ShotWrite',self.host.graph)
        self.assertIn('ArtistOnly',self.host.graph)
        self.assertEqual(self.host.script_path,str(self.root/'artist.nknc'))

    def test_native_write_channel_mask_knob(self):
        constructor=self.host.nodes.Write
        def create(**kwargs):
            node=constructor(**kwargs);node['channels'].kind='ChannelMask_Knob';return node
        self.host.nodes.Write=create
        result=self.apply(self.plan())
        self.assertEqual(len(result['completed']),1)

    def test_changed_toolset_refused_before_clear(self):
        from nuke_mcp_bridge.toolsets import save_toolset
        self.host.add('In','Input');self.host.add('Out','Output').setInput(0,self.host.graph['In'])
        saved=save_toolset(self.host,self.library,['root.In','root.Out'],'asset')
        self.manifest['shots'][0]['toolset']='asset'
        plan=self.plan()
        (self.library/saved['manifest']['payload']).write_text('changed')
        with self.assertRaises(BridgeError):self.apply(plan)
        self.assertEqual(self.host.script_clear_count,0)

    def test_nested_windows_junction_output_escape(self):
        if os.name!='nt':self.skipTest('Windows junction qualification requires Windows')
        with tempfile.TemporaryDirectory() as outside:
            nested=self.root/'nested';nested.mkdir();link=nested/'redirect'
            done=subprocess.run(['powershell','-NoProfile','-Command',
                "New-Item -ItemType Junction -Path '"+str(link).replace("'","''")+"' -Target '"+outside.replace("'","''")+"' | Out-Null"],capture_output=True,text=True)
            if done.returncode:self.skipTest('Cannot create junction: '+done.stderr)
            try:
                self.manifest['shots'][0]['script_path']=str(link/'shot.nknc')
                with self.assertRaises(BridgeError):self.plan()
                self.assertEqual(self.host.script_clear_count,0)
            finally:os.rmdir(link)
