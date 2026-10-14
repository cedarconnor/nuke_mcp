"""Pure schema-v1 validation and explicit CSV conversion; no host API."""
from copy import deepcopy
import csv
import hashlib
import json
import math
import re
from .protocol import BridgeError


def fail(field, message):
    raise BridgeError('invalid_manifest',message,data={'field':field})


def obj(value, required, optional, field):
    if not isinstance(value,dict):fail(field,'Expected an object')
    missing=set(required)-value.keys();extra=value.keys()-set(required)-set(optional)
    if missing:fail(field+'.'+sorted(missing)[0],'Required field missing')
    if extra:fail(field+'.'+sorted(extra)[0],'Unsupported field')


def text(value,field):
    if not isinstance(value,str) or not value.strip() or len(value)>4096 or '\x00' in value:
        fail(field,'Expected nonempty text of at most 4096 characters')


def identity(value,field):
    text(value,field)
    if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}',value):fail(field,'Expected identifier of at most 64 characters')


def number(value,field,integer=False,positive=False):
    if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value):fail(field,'Expected finite number')
    if positive and value<=0:fail(field,'Expected positive number')
    if integer and not -2147483648<=value<=2147483647:fail(field,'Integer outside signed 32-bit range')


def format_schema(value,field):
    obj(value,('width','height','pixel_aspect'),(),field)
    for key in ('width','height'):number(value[key],field+'.'+key,True,True)
    number(value['pixel_aspect'],field+'.pixel_aspect',positive=True)
    if max(value['width'],value['height'])>65536 or value['pixel_aspect']>100:fail(field,'Format exceeds supported bounds')


def write_schema(value,field):
    obj(value,('path','channels','file_type','datatype','compression','colorspace'),(),field)
    for key,v in value.items():text(v,field+'.'+key)


def version(manifest,required):
    obj(manifest,('schema_version',)+required,(),'manifest')
    if type(manifest['schema_version']) is not int or manifest['schema_version']!=1:fail('schema_version','Only schema version 1 is supported')


def validate_shot_manifest(manifest):
    version(manifest,('output_root','shots'))
    text(manifest['output_root'],'output_root')
    shots=manifest['shots']
    if not isinstance(shots,list) or not 1<=len(shots)<=100:fail('shots','Expected 1..100 shots')
    ids=set();paths=set()
    for i,shot in enumerate(shots):
        f='shots.'+str(i)
        obj(shot,('shot_id','script_path','plates','frame_range','fps','format','color_settings','write'),('toolset',),f)
        identity(shot['shot_id'],f+'.shot_id');text(shot['script_path'],f+'.script_path')
        if shot['shot_id'] in ids:fail(f+'.shot_id','Duplicate shot ID')
        if shot['script_path'] in paths:fail(f+'.script_path','Duplicate script path')
        ids.add(shot['shot_id']);paths.add(shot['script_path'])
        plates=shot['plates']
        if not isinstance(plates,list) or not 1<=len(plates)<=32:fail(f+'.plates','Expected 1..32 plates')
        for j,plate in enumerate(plates):
            pf=f+'.plates.'+str(j)
            obj(plate,('path','colorspace','first','last'),(),pf)
            text(plate['path'],pf+'.path');text(plate['colorspace'],pf+'.colorspace')
            number(plate['first'],pf+'.first',True);number(plate['last'],pf+'.last',True)
            if plate['first']>plate['last']:fail(pf,'First exceeds last')
        frames=shot['frame_range'];keys=('work_first','cut_in','cut_out','work_last')
        obj(frames,keys,(),f+'.frame_range')
        for k in keys:number(frames[k],f+'.frame_range.'+k,True)
        if list(frames[k] for k in keys)!=sorted(frames[k] for k in keys):fail(f+'.frame_range','Cuts must lie inside work range')
        fps=shot['fps'];obj(fps,('numerator','denominator'),(),f+'.fps')
        for k in fps:number(fps[k],f+'.fps.'+k,True,True)
        if fps['numerator']/fps['denominator']>1000:fail(f+'.fps','FPS exceeds 1000')
        format_schema(shot['format'],f+'.format')
        color=shot['color_settings']
        if not isinstance(color,dict) or not color:fail(f+'.color_settings','Explicit color settings are required')
        for k,v in color.items():identity(k,f+'.color_settings');text(v,f+'.color_settings.'+k)
        write_schema(shot['write'],f+'.write')
        if 'toolset' in shot:identity(shot['toolset'],f+'.toolset')
    return deepcopy(manifest)


def validate_comp_manifest(manifest):
    obj(manifest,('schema_version','group_name','layers'),('write',),'manifest')
    if type(manifest['schema_version']) is not int or manifest['schema_version']!=1:fail('schema_version','Only schema version 1 is supported')
    identity(manifest['group_name'],'group_name')
    layers=manifest['layers']
    if not isinstance(layers,list) or not 1<=len(layers)<=32:fail('layers','Expected 1..32 layers')
    ids=set()
    for i,layer in enumerate(layers):
        f='layers.'+str(i)
        obj(layer,('id','channel_layer'),('source_node_path','source_file','colorspace','operation','adjustments','mask_node_path','mask_channel'),f)
        identity(layer['id'],f+'.id');text(layer['channel_layer'],f+'.channel_layer')
        if layer['id'] in ids:fail(f+'.id','Duplicate layer ID')
        ids.add(layer['id'])
        if ('source_node_path' in layer)==('source_file' in layer):fail(f,'Specify exactly one source')
        source='source_node_path' if 'source_node_path' in layer else 'source_file'
        text(layer[source],f+'.'+source)
        if source=='source_file':text(layer.get('colorspace'),f+'.colorspace')
        elif 'colorspace' in layer:fail(f+'.colorspace','Node source already defines its colorspace')
        if i==0 and 'operation' in layer:fail(f+'.operation','Base layer has no merge operation')
        if i and layer.get('operation') not in ('over','plus','multiply','screen'):fail(f+'.operation','Explicit supported merge operation required')
        if ('mask_node_path' in layer)!=('mask_channel' in layer):fail(f,'Mask requires path and channel')
        if 'mask_node_path' in layer:
            if i==0:fail(f,'Base layer has no merge to mask')
            text(layer['mask_node_path'],f+'.mask_node_path');text(layer['mask_channel'],f+'.mask_channel')
        if 'adjustments' in layer:
            adj=layer['adjustments'];obj(adj,(),('grade','blur'),f+'.adjustments')
            for kind,settings in adj.items():
                obj(settings,(),('gain','gamma') if kind=='grade' else ('size',),f+'.adjustments.'+kind)
                if not settings:fail(f+'.adjustments.'+kind,'Empty adjustment')
                for k,v in settings.items():
                    number(v,f+'.adjustments.'+kind+'.'+k,positive=k=='gamma')
                    if v<0:fail(f+'.adjustments.'+kind+'.'+k,'Negative adjustment unsupported')
    if 'write' in manifest:write_schema(manifest['write'],'write')
    return deepcopy(manifest)


def plan_digest(plan):
    try:payload=json.dumps(plan,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')
    except (TypeError,ValueError) as exc:fail('plan',str(exc))
    if len(payload)>4*1024*1024:fail('plan','Plan exceeds 4 MiB')
    return hashlib.sha256(payload).hexdigest()


def import_shot_csv(path,column_map,defaults):
    obj(defaults,('schema_version','output_root','shot_defaults'),(),'defaults')
    if not isinstance(column_map,dict) or not column_map or any(not isinstance(v,str) for v in column_map.values()):fail('column_map','Explicit header-to-field map required')
    if len(set(column_map.values()))!=len(column_map):fail('column_map','Duplicate target field')
    result={'manifest':{'schema_version':defaults['schema_version'],'output_root':defaults['output_root'],'shots':[]},'errors':[],'unmapped_columns':[]}
    with open(path,'r',encoding='utf-8-sig',newline='') as stream:
        if stream.seek(0,2)>1024*1024:fail('csv','CSV exceeds 1 MiB')
        stream.seek(0);reader=csv.DictReader(stream)
        headers=reader.fieldnames or []
        if len(headers)!=len(set(headers)):fail('csv.headers','Duplicate headers')
        if set(column_map)-set(headers):fail('column_map','Mapped column missing')
        result['unmapped_columns']=[h for h in headers if h not in column_map]
        for index,row in enumerate(reader):
            if index>=100:fail('csv','More than 100 rows')
            if None in row or any(v is None for v in row.values()):fail('csv.rows.'+str(index),'Column count mismatch')
            shot=deepcopy(defaults['shot_defaults'])
            for header,field in column_map.items():
                parts=field.split('.');cursor=shot
                try:
                    for j,key in enumerate(parts[:-1]):
                        if isinstance(cursor,list):cursor=cursor[int(key)]
                        else:cursor=cursor.setdefault(key,[] if parts[j+1].isdigit() else {})
                    value=row[header]
                    if parts[-1] in ('first','last','work_first','cut_in','cut_out','work_last','numerator','denominator','width','height'):value=int(value)
                    elif parts[-1]=='pixel_aspect':value=float(value)
                    cursor[parts[-1]]=value
                except (ValueError,TypeError,IndexError,AttributeError) as exc:fail('column_map.'+header,str(exc))
            result['manifest']['shots'].append(shot)
    try:result['manifest']=validate_shot_manifest(result['manifest'])
    except BridgeError as exc:result['errors'].append(dict(exc.data,message=str(exc)))
    return result
