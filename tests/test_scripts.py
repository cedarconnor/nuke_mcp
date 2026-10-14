import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from tests.library_fakes import LibraryHost
from tests.mutation_fakes import Knob
from nuke_mcp_bridge.protocol import BridgeError

if importlib.util.find_spec('nuke_mcp_bridge.scripts'):
    from nuke_mcp_bridge import scripts as s
else:s=None

class ScriptHost(LibraryHost):
    def __init__(self):
        super().__init__()
        self.script_path='Root'
        self.modified=True
        self.open_count=self.save_count=self.script_clear_count=0
        self.fail_save=self.wrong_path=False
        root=self.root_node
        root.name=lambda:self.script_path
        root.setName=lambda value:setattr(self,'script_path',value)
        root.modified=lambda:self.modified
        root.setModified=lambda value:setattr(self,'modified',value)
        root._knobs={'fps':Knob(24.),'first_frame':Knob(1,'Int_Knob'),
                     'last_frame':Knob(100,'Int_Knob'),
                     'colorManagement':Knob('linear','Enumeration_Knob'),
                     'format':Knob(None,'Format_Knob')}
        self.format_value={'width':1920,'height':1080,'pixel_aspect':1.}
        root.format=lambda:SimpleNamespace(width=lambda:self.format_value['width'],
            height=lambda:self.format_value['height'],pixelAspect=lambda:self.format_value['pixel_aspect'])
        root['format'].setValue=lambda f:setattr(self,'format_value',f)
        self.addFormat=lambda text:dict(zip(('width','height','pixel_aspect'),map(float,text.split()[:3])))
    def scriptSaveAs(self,path,overwrite):
        self.save_count+=1
        if Path(path).exists() and not overwrite:raise RuntimeError('exists')
        self.script_path=path
        self.modified=False
        if self.fail_save:raise RuntimeError('save failed after name changed')
        Path(path).write_text(json.dumps({'saved':True}))
        if self.wrong_path:self.script_path='Root'
    def scriptOpen(self,path):
        self.open_count+=1
        self.script_path='Root' if self.wrong_path else path
        self.modified=False
    def scriptClear(self):
        self.script_clear_count+=1
        self.script_path='Root'
        self.modified=False

class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(s,'Lifecycle implementation missing')
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir=Path(temp.name)
        self.target=self.dir/'shot.nknc'
        self.host=ScriptHost()
    def test_dirty_open_refused_before_host_call(self):
        self.target.write_text('fixture')
        with self.assertRaises(BridgeError):s.open_script(self.host,str(self.target))
        self.assertEqual(self.host.open_count,0)
        self.assertEqual(self.host.script_clear_count,0)
        self.assertTrue(self.host.modified)
    def test_explicit_discard_and_saved_clean_reopen(self):
        self.target.write_text('fixture')
        s.open_script(self.host,str(self.target),True)
        s.open_script(self.host,str(self.target))
        self.assertEqual(self.host.open_count,2)
        self.assertEqual(self.host.script_path,str(self.target))
    def test_save_as_collision_then_save_current(self):
        s.save_script(self.host,str(self.target))
        with self.assertRaises(BridgeError):s.save_script(self.host,str(self.target))
        s.save_script(self.host)
        self.assertEqual(self.host.save_count,2)
    def test_unsaved_requires_explicit_absolute_path(self):
        for path in (None,'shot.nknc',str(self.dir/'shot.nk'),str(self.dir/'absent'/'shot.nknc')):
            with self.assertRaises(BridgeError):s.save_script(self.host,path)
        self.assertEqual(self.host.save_count,0)
    def test_commercial_extension(self):
        self.host.env['nc']=False
        s.save_script(self.host,str(self.dir/'shot.nk'))

    def test_native_environment_requires_default_and_fps_is_array_knob(self):
        class Environment(dict):
            def get(self,key,default=None):
                if not isinstance(default,str):raise TypeError('default must be str')
                return super().get(key,default)
        self.host.env=Environment(nc=True)
        self.host.root()['fps'].kind='Array_Knob'
        s.set_project_settings(self.host,{'fps':30.},False)
        s.save_script(self.host,str(self.target))
    def test_failed_save_as_restores_original_target_and_dirty_flag(self):
        for dirty in (True,False):
            self.host.script_path=str(self.dir/'original.nknc')
            self.host.modified=dirty
            self.host.fail_save=True
            with self.assertRaises(BridgeError) as caught:s.save_script(self.host,str(self.target))
            self.assertEqual(self.host.script_path,str(self.dir/'original.nknc'))
            self.assertEqual(self.host.modified,dirty)
            self.assertTrue(caught.exception.data['identity_restored'])
    def test_path_mismatch_is_unknown(self):
        self.host.wrong_path=True
        with self.assertRaises(BridgeError) as caught:s.save_script(self.host,str(self.target))
        self.assertEqual(caught.exception.outcome,'unknown')
        with self.assertRaises(BridgeError):s.open_script(self.host,str(self.target),True)
    def test_settings_dry_run_and_format_apply(self):
        settings={'fps':30.,'first_frame':1001,'last_frame':1010,
                  'format':{'width':2048,'height':858,'pixel_aspect':1.}}
        result=s.set_project_settings(self.host,settings)
        self.assertEqual(result['outcome'],'not_started')
        self.assertEqual(self.host.root()['fps'].value(),24.)
        s.set_project_settings(self.host,settings,False)
        self.assertEqual(self.host.root()['fps'].value(),30.)
        self.assertEqual(self.host.format_value['width'],2048)
    def test_invalid_settings_preflight_no_writes(self):
        for settings in ({'fps':0},{'fps':float('nan')},{'first_frame':200},
                         {'format':{'width':0,'height':10,'pixel_aspect':1}},
                         {'color_management':{'colorManagement':'invented'}},
                         {'color_management':{'absent':'linear'}}):
            with self.assertRaises(BridgeError):s.set_project_settings(self.host,settings,False)
        self.assertEqual(self.host.root()['fps'].value(),24.)
    def test_partial_settings_retains_prior_edits(self):
        self.host.root()['last_frame'].fail_after=True
        with self.assertRaises(BridgeError) as caught:
            s.set_project_settings(self.host,{'fps':30.,'last_frame':200},False)
        self.assertIn(caught.exception.outcome,('partial','unknown'))
        self.assertEqual(self.host.root()['fps'].value(),30.)
        self.assertIn('fps',caught.exception.data['completed'])
    def test_final_readback_catches_callbacks(self):
        knob=self.host.root()['last_frame']
        original=knob.setValue
        def change(value):
            original(value)
            self.host.root()['fps'].v=99
        knob.setValue=change
        with self.assertRaises(BridgeError):s.set_project_settings(self.host,{'fps':30.,'last_frame':200},False)
    def test_internal_new_refuses_dirty(self):
        with self.assertRaises(BridgeError):s.new_disposable_script(self.host)
        self.assertEqual(self.host.script_clear_count,0)

    def test_failed_save_does_not_clear_callback_edits_or_relabel_switched_script(self):
        for switched in (False,True):
            self.host.script_path=str(self.dir/'original.nknc')
            self.host.modified=False
            def callback(path,overwrite):
                self.host.script_path=str(self.dir/'other.nknc') if switched else path
                self.host.root()['fps'].v=48
                self.host.modified=True
                raise RuntimeError('callback changed script')
            self.host.scriptSaveAs=callback
            with self.assertRaises(BridgeError) as caught:s.save_script(self.host,str(self.target))
            self.assertTrue(self.host.modified)
            self.assertFalse(caught.exception.data['identity_restored'])
            if switched:self.assertEqual(self.host.script_path,str(self.dir/'other.nknc'))

    def test_setting_callback_script_switch_stops_later_edits(self):
        knob=self.host.root()['fps']
        def callback(value):
            knob.v=value
            self.host.script_path=str(self.dir/'artist.nknc')
        knob.setValue=callback
        with self.assertRaises(BridgeError):
            s.set_project_settings(self.host,{'fps':30.,'last_frame':200},False)
        self.assertEqual(self.host.root()['last_frame'].value(),100)

    def test_restore_name_callback_cannot_clear_new_edits(self):
        self.host.script_path=str(self.dir/'original.nknc')
        self.host.modified=False
        self.host.fail_save=True
        def rename(path):
            self.host.script_path=path
            self.host.root()['fps'].v=48
            self.host.modified=True
        self.host.root().setName=rename
        with self.assertRaises(BridgeError) as caught:s.save_script(self.host,str(self.target))
        self.assertTrue(self.host.modified)
        self.assertFalse(caught.exception.data['identity_restored'])
