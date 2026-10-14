import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from nuke_mcp_bridge.protocol import BridgeError

if importlib.util.find_spec('nuke_mcp_bridge.manifests'):
    from nuke_mcp_bridge import manifests as m
else:m=None

def shot_manifest(root='C:/delivery'):
    return {'schema_version':1,'output_root':root,'shots':[{
        'shot_id':'sh010','script_path':root+'/sh010.nknc',
        'plates':[{'path':'C:/plates/plate.%04d.exr','colorspace':'linear','first':-2,'last':2}],
        'frame_range':{'work_first':-2,'cut_in':-1,'cut_out':1,'work_last':2},
        'fps':{'numerator':24000,'denominator':1001},
        'format':{'width':1920,'height':1080,'pixel_aspect':1.},
        'color_settings':{'colorManagement':'Nuke'},
        'write':{'path':root+'/out.%04d.exr','channels':'rgba','file_type':'exr',
                 'datatype':'half','compression':'Zip (1 scanline)','colorspace':'linear'}}]}

def comp_manifest():
    return {'schema_version':1,'group_name':'AOV','layers':[
        {'id':'base','source_node_path':'GroupA.Same','channel_layer':'rgba'},
        {'id':'light','source_node_path':'GroupB.Same','channel_layer':'rgba','operation':'plus'}]}

class ManifestTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(m,'Manifest implementation missing')
    def test_valid_negative_frames_rational_fps_and_digest(self):
        value=shot_manifest()
        normalized=m.validate_shot_manifest(value)
        self.assertEqual(normalized,value)
        self.assertEqual(m.plan_digest(value),m.plan_digest(dict(reversed(list(value.items())))))
        changed=copy.deepcopy(value);changed['shots'][0]['fps']['numerator']=24
        self.assertNotEqual(m.plan_digest(value),m.plan_digest(changed))
    def test_invalid_shots_locate_fields_without_side_effects(self):
        for edit in (lambda v:v.update(schema_version=True),lambda v:v.update(unexpected=1),
                     lambda v:v['shots'][0].pop('color_settings'),
                     lambda v:v['shots'][0]['fps'].update(denominator=0),
                     lambda v:v['shots'][0]['format'].update(width=float('nan')),
                     lambda v:v['shots'][0]['frame_range'].update(cut_in=-3),
                     lambda v:v['shots'].append(copy.deepcopy(v['shots'][0]))):
            value=shot_manifest();edit(value)
            with self.assertRaises(BridgeError) as error:m.validate_shot_manifest(value)
            self.assertIn('field',error.exception.data)
    def test_shot_count_bound(self):
        value=shot_manifest();value['shots']*=101
        with self.assertRaises(BridgeError):m.validate_shot_manifest(value)
    def test_comp_order_masks_and_exactly_one_source(self):
        value=comp_manifest()
        value['layers'][1].update(mask_node_path='Masks.Alpha',mask_channel='rgba.alpha',adjustments={'blur':{'size':2}})
        self.assertEqual(m.validate_comp_manifest(value),value)
        for edit in (lambda v:v['layers'][1].update(operation='beauty'),
                     lambda v:v['layers'][0].update(source_file='plate.exr'),
                     lambda v:v['layers'][1].pop('mask_channel'),
                     lambda v:v['layers'][0].update(operation='over'),
                     lambda v:v['layers'][1].update(adjustments={'grade':{'gain':float('inf')}})):
            bad=copy.deepcopy(value);edit(bad)
            with self.assertRaises(BridgeError):m.validate_comp_manifest(bad)
    def test_csv_explicit_mapping_and_duplicate_diagnostics(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'shots.csv'
            defaults=shot_manifest();defaults['shot_defaults']=defaults.pop('shots')[0]
            defaults['shot_defaults'].pop('shot_id')
            path.write_text('ID,Script,Unused\nsh010,C:/delivery/a.nknc,x\nsh010,C:/delivery/b.nknc,y\n')
            result=m.import_shot_csv(str(path),{'ID':'shot_id','Script':'script_path'},defaults)
            self.assertTrue(result['errors'])
            self.assertEqual(result['unmapped_columns'],['Unused'])
            path.write_text('ID,ID\na,b\n')
            with self.assertRaises(BridgeError):m.import_shot_csv(str(path),{'ID':'shot_id'},defaults)
            path.write_text('ID,Script\nsh010,C:/delivery/a.nknc\n')
            result=m.import_shot_csv(str(path),{'ID':'shot_id','Script':'script_path'},defaults)
            self.assertEqual(result['errors'],[])
            self.assertEqual(result['manifest']['shots'][0]['shot_id'],'sh010')
    def test_examples_validate(self):
        root=Path(__file__).resolve().parents[1]/'examples'
        m.validate_shot_manifest(json.loads((root/'shot-manifest.json').read_text()))
        m.validate_comp_manifest(json.loads((root/'layered-comp-manifest.json').read_text()))
