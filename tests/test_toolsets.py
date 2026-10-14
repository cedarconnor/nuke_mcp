import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tests.library_fakes import LibraryHost
from nuke_mcp_bridge.protocol import BridgeError

if importlib.util.find_spec('nuke_mcp_bridge.toolsets'):
    from nuke_mcp_bridge import toolsets as t
else: t=None

class ToolsetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(t,'Toolset implementation missing')
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'library'
        self.root.mkdir()
        self.host=LibraryHost()
        self.a=self.host.add('Artist')
        self.b=self.host.add('Grade1')
        self.a.selected=True
        self.b['gain'].v=2.
    def save(self,**kw): return t.save_toolset(self.host,self.root,['root.Grade1'],'approved',**kw)
    def test_save_and_load_preserve_selection_and_known_state(self):
        saved=self.save()
        self.assertTrue(self.a.selected)
        self.assertFalse(self.b.selected)
        self.assertEqual(saved['manifest']['schema_version'],1)
        self.assertEqual(Path(saved['manifest']['payload']).suffix,'.nknc')
        loaded=t.load_toolset(self.host,self.root,'approved','Imported',[12,34])
        self.assertEqual(loaded['group_path'],'Imported')
        self.assertEqual(self.host.graph['Imported.Grade1']['gain'].value(),2.)
        self.assertTrue(self.a.selected)
        self.assertEqual(self.host.graph['Imported'].xy,[12,34])
    def test_duplicate_name_no_overwrite_or_selection_change(self):
        self.save()
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        with self.assertRaises(BridgeError):self.save()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual(self.host.copy_count,1)
        self.assertTrue(self.a.selected)
    def test_commercial_payload_extension_and_nested_groups(self):
        self.host.env['nc']=False
        g=self.host.add('Pack','Group')
        child=self.host.add('Pack.Inside')
        child['gain'].v=3.
        saved=t.save_toolset(self.host,self.root,['Pack'],'nested')
        self.assertTrue(saved['manifest']['payload'].endswith('.nk'))
        t.load_toolset(self.host,self.root,'nested','Imported')
        self.assertEqual(self.host.graph['Imported.Pack.Inside']['gain'].value(),3.)
    def test_missing_external_dependency_refused_before_copy(self):
        self.b.setInput(0,self.a)
        with self.assertRaises(BridgeError) as error:self.save()
        self.assertEqual(error.exception.code,'external_dependency')
        self.assertEqual(self.host.copy_count,0)
    def test_interrupted_copy_preserves_old_manifest(self):
        old=self.save()['manifest']
        self.host.fail_copy=True
        with self.assertRaises(BridgeError):self.save(overwrite=True)
        listed=t.list_toolsets(self.root)
        self.assertEqual(listed['entries'][0]['sha256'],old['sha256'])
        self.assertTrue(self.a.selected)
    def test_payload_corruption_is_not_listed_or_pasted(self):
        saved=self.save()
        (self.root/saved['manifest']['payload']).write_text('changed')
        listed=t.list_toolsets(self.root)
        self.assertEqual(listed['entries'],[])
        self.assertTrue(listed['errors'])
        with self.assertRaises(BridgeError):t.load_toolset(self.host,self.root,'approved','Imported')
        self.assertEqual(self.host.paste_count,0)
        self.assertNotIn('Imported',self.host.graph)
    def test_changed_payload_during_group_creation_is_not_pasted(self):
        saved=self.save()
        constructor=self.host.nodes.Group
        def create(**kwargs):
            result=constructor(**kwargs)
            (self.root/saved['manifest']['payload']).write_text('changed')
            return result
        self.host.nodes.Group=create
        with self.assertRaises(BridgeError) as error:t.load_toolset(self.host,self.root,'approved','Imported')
        self.assertIn(error.exception.outcome,('partial','unknown'))
        self.assertEqual(self.host.paste_count,0)
        self.assertEqual(error.exception.data['group_path'],'Imported')
    def test_handleless_group_creation_does_not_retry_or_delete(self):
        self.save()
        self.host.create_returns_none=True
        with self.assertRaises(BridgeError) as error:t.load_toolset(self.host,self.root,'approved','Imported')
        self.assertEqual(error.exception.outcome,'unknown')
        self.assertEqual(self.host.create_count,1)
        self.assertEqual(self.host.deleted,[])
    def test_traversal_and_foreign_manifest_payload_are_rejected(self):
        for candidate in ('../outside.nk','a/../../outside.nk'):
            with self.assertRaises(BridgeError):t.contained_path(self.root,candidate)
        saved=self.save()
        manifest=dict(saved['manifest'],payload='../outside.nknc')
        (self.root/'approved.json').write_text(json.dumps(manifest))
        self.assertEqual(t.list_toolsets(self.root)['entries'],[])
    def test_nested_windows_junction_escape(self):
        if os.name!='nt':self.skipTest('Windows junction qualification requires Windows')
        outside=Path(self.temp.name)/'outside'
        outside.mkdir()
        nested=self.root/'nested'
        nested.mkdir()
        link=nested/'redirect'
        # Create only a junction to an owned empty fixture. Remove only the link.
        args=['powershell','-NoProfile','-Command',
              "New-Item -ItemType Junction -Path '"+str(link).replace("'","''")+"' -Target '"+str(outside).replace("'","''")+"' | Out-Null"]
        done=subprocess.run(args,capture_output=True,text=True)
        if done.returncode:self.skipTest('Cannot create junction: '+done.stderr)
        try:
            with self.assertRaises(BridgeError):t.contained_path(self.root,link/'payload.nk')
        finally:os.rmdir(link)

    def test_malformed_metadata_not_listed(self):
        manifest=self.save()['manifest']
        for changes in ({'dependencies':None},{'nodes':[{}]},{'host':None}):
            (self.root/'approved.json').write_text(json.dumps(dict(manifest,**changes)))
            self.assertEqual(t.list_toolsets(self.root)['entries'],[])

    def test_selection_callback_cannot_hide_paste_change(self):
        self.save()
        original=self.a.setSelected
        def selection(value):
            original(value)
            if value and 'Imported.Grade1' in self.host.graph:
                self.host.graph['Imported.Grade1']['gain'].v=99
        self.a.setSelected=selection
        with self.assertRaises(BridgeError):t.load_toolset(self.host,self.root,'approved','Imported')

    def test_publication_failure_leaves_previous_entry(self):
        old=self.save()['manifest']
        with patch.object(t.os,'replace',side_effect=OSError('interrupted')):
            with self.assertRaises(BridgeError):self.save(overwrite=True)
        self.assertEqual(t.list_toolsets(self.root)['entries'][0]['sha256'],old['sha256'])

    def test_unavailable_class_refused_before_group_creation(self):
        self.save()
        del self.host.nodes.Grade
        with self.assertRaises(BridgeError):t.load_toolset(self.host,self.root,'approved','Imported')
        self.assertEqual(self.host.create_count,0)
