"""Manifest-driven basic RGBA reconstruction in an explicitly owned Group."""
from pathlib import Path
from . import manifests
from .inspection import node_record, inspect_reads, observation
from .mutations import main_thread,check_guard,resolve_node,connect_input,knob_value,same_value,operation_guard
from .protocol import BridgeError
from .scripts import state
from .shots import host_binding,expand_path,file_fact,set_field
from .toolsets import selected_scope
from .events import plan_stamp, check_plan_stamp

COMPONENTS=('red','green','blue','alpha')


def node_evidence(nuke,node):
    channels=list(node.channels())
    if len(channels)>2048:raise BridgeError('limit_exceeded','Source channels exceed 2048')
    record=node_record(node,128)
    if record['errors']:raise BridgeError('state_uncertain','Source topology unavailable')
    # Selection/position are intentionally outside this content binding.
    return {'path':node.fullName(),'class':node.Class(),'channels':sorted(channels),
            'inputs':record['inputs'],'parameters':record['parameters'],
            'knob_coverage':'bounded supported subset'}


def source_evidence(nuke,layer,frame,observed_read=None):
    if 'source_node_path' in layer:
        node=resolve_node(nuke,layer['source_node_path'])
        return node_evidence(nuke,node)
    path=expand_path(nuke,layer['source_file'],frame)
    fact=file_fact(path)
    if not fact['exists']:raise BridgeError('file_missing','Comp source file is missing')
    reads=inspect_reads(nuke,node_paths=['root.'+observed_read] if observed_read else None,channel_limit=2048)
    matches=[r for r in reads['reads'] if r.get('raw_path')==layer['source_file'] and r.get('colorspace')==layer['colorspace'] and 'channels' in r and not r['truncated']]
    if len(matches)!=1:raise BridgeError('channels_unavailable','File source needs one observed matching Read with the requested colorspace')
    return {'file':fact,'observed_read':matches[0]['path'],'channels':sorted(matches[0]['channels'])}


def plan_layered_comp(nuke,manifest):
    main_thread();manifest=manifests.validate_comp_manifest(manifest)
    scene_revision=plan_stamp()
    frame=nuke.frame();sources=[];scopes=set();masks={}
    for layer in manifest['layers']:
        check_guard();source=source_evidence(nuke,layer,frame)
        needed={layer['channel_layer']+'.'+c for c in COMPONENTS}
        if not needed<=set(source['channels']):raise BridgeError('channels_unavailable','Explicit RGBA channels unavailable for '+layer['id'])
        sources.append(source)
        if 'path' in source:scopes.add(source['path'].rpartition('.')[0])
        if 'mask_node_path' in layer:
            mask=resolve_node(nuke,layer['mask_node_path']);evidence=node_evidence(nuke,mask)
            if layer['mask_channel'] not in evidence['channels']:raise BridgeError('channels_unavailable','Mask channel unavailable')
            scopes.add(mask.fullName().rpartition('.')[0]);masks[layer['id']]=evidence
    if len(scopes)>1:raise BridgeError('cross_scope_sources','Sources must share a Group scope; expose Group outputs for cross-Group sources')
    scope=next(iter(scopes),'')
    group_path=(scope+'.' if scope else '')+manifest['group_name']
    with nuke.root():existing=nuke.toNode(group_path)
    if existing is not None:raise BridgeError('name_conflict','Requested Group already exists')
    shuffle=next((k for k in ('Shuffle','Shuffle2') if callable(getattr(nuke.nodes,k,None))),None)
    if shuffle is None:raise BridgeError('node_class_unavailable','Shuffle or Shuffle2 required')
    required={'Group','Input','Output',shuffle}
    if len(sources)>1:required.add('Merge2')
    for layer in manifest['layers']:
        if 'source_file' in layer:required.add('Read')
        required.update({'grade':'Grade','blur':'Blur'}[k] for k in layer.get('adjustments',{}))
    if 'write' in manifest:required.add('Write')
    for cls in required:
        if not callable(getattr(nuke.nodes,cls,None)):raise BridgeError('node_class_unavailable',cls)
    plan={'manifest':manifest,'host':host_binding(nuke),'script':state(nuke),
          'scene_revision':scene_revision,
          'frame':frame,'group_path':group_path,'scope':scope,'shuffle':shuffle,
          'sources':sources,'masks':masks,'merge_inputs':{'B':0,'A':1,'mask':2},
          'knob_layout':'validated on owned nodes at build; discovery is advisory','errors':[]}
    check_plan_stamp(scene_revision)
    return dict(plan,digest=manifests.plan_digest(plan))


def build_layered_comp(nuke,manifest,plan_digest):
    main_thread();plan=plan_layered_comp(nuke,manifest)
    if plan['digest']!=plan_digest:raise BridgeError('stale_plan','Layer sources, host or script changed')
    manifest=plan['manifest'];scope=resolve_node(nuke,plan['scope']) if plan['scope'] else nuke.root()
    root=nuke.root();script=root.name()
    data={'group_path':None,'created_paths':[],'operations':[],'source_paths':[],
          'output_path':None,'write_path':None}
    group=None;started=False;expected_knobs=[];expected_inputs=[];created=[]
    def boundary():
        check_guard()
        if nuke.root()!=root or root.name()!=script or nuke.frame()!=plan['frame']:
            raise BridgeError('stale_plan','Script/frame changed during construction')
        for layer,expected in zip(manifest['layers'],plan['sources']):
            if source_evidence(nuke,layer,plan['frame'],expected.get('observed_read'))!=expected:raise BridgeError('stale_plan','Source changed during construction')
        for layer in manifest['layers']:
            if layer['id'] in plan['masks'] and node_evidence(nuke,resolve_node(nuke,layer['mask_node_path']))!=plan['masks'][layer['id']]:
                raise BridgeError('stale_plan','Mask changed during construction')
    def create(parent,cls,name):
        nonlocal started
        boundary();started=True
        with parent:node=getattr(nuke.nodes,cls)(name=name)
        if node is None:raise BridgeError('state_uncertain','Creation returned no handle; do not retry','unknown')
        path=(parent.fullName()+'.' if parent!=root else '')+name
        data['created_paths'].append(node.fullName())
        created.append(node)
        if node.fullName()!=path or resolve_node(nuke,'root.'+path)!=node:raise BridgeError('state_uncertain','Created identity differs','unknown')
        node.setSelected(False)
        data['operations'].append({'op':'create','path':path,'class':cls,'outcome':'applied'})
        return node
    def field(node,key,value):
        boundary();set_field(nuke,node,key,value)
        expected_knobs.append((node,key,value))
        data['operations'].append({'op':'set_knob','path':node.fullName(),'knob':key,'outcome':'applied'})
    def connect(node,index,source):
        boundary();connect_input(nuke,'root.'+node.fullName(),index,'root.'+source.fullName())
        expected_inputs.append((node,index,source))
    inherited_guard=operation_guard.get()
    def identity_guard():
        if inherited_guard:inherited_guard()
        check_plan_stamp(plan['scene_revision'],allow_owned=True)
        if nuke.root()!=root or root.name()!=script or nuke.frame()!=plan['frame']:
            raise BridgeError('script_changed','Script/frame changed during construction','unknown')
    guard_token=operation_guard.set(identity_guard)
    try:
        with selected_scope(nuke,scope):
            group=create(scope,'Group',manifest['group_name']);data['group_path']=group.fullName()
            ports={}
            def port(path):
                resolved=resolve_node(nuke,path);path=resolved.fullName()
                if path not in ports:
                    number=len(ports)
                    connect(group,number,resolved)
                    inner=create(group,'Input','Input_'+str(number));field(inner,'number',number)
                    ports[path]=inner;data['source_paths'].append(path)
                return ports[path]
            accumulated=None
            for layer in manifest['layers']:
                if 'source_node_path' in layer:source=port(layer['source_node_path'])
                else:
                    source=create(group,'Read','Read_'+layer['id'])
                    field(source,'file',layer['source_file']);field(source,'colorspace',layer['colorspace'])
                shuffle=create(group,plan['shuffle'],'Shuffle_'+layer['id']);connect(shuffle,0,source)
                if plan['shuffle']=='Shuffle':
                    field(shuffle,'in',layer['channel_layer']);field(shuffle,'out','rgba')
                    for component in COMPONENTS:field(shuffle,component,component)
                else:
                    field(shuffle,'in1',layer['channel_layer']);field(shuffle,'out1','rgba')
                    mapping=[(0,layer['channel_layer']+'.'+k,'rgba.'+k) for k in COMPONENTS]
                    knob=shuffle.knob('mappings')
                    if knob is None:raise BridgeError('knob_unavailable','Shuffle2 mappings unavailable')
                    boundary();knob.setValue(mapping)
                    if [tuple(v) for v in knob.value()]!=mapping:raise BridgeError('state_uncertain','Shuffle2 mapping readback differs','unknown')
                    expected_knobs.append((shuffle,'mappings',mapping))
                current=shuffle
                # Schema-v1 adjustments are an object: canonical hashing ignores key order.
                for kind in ('grade','blur'):
                    if kind not in layer.get('adjustments',{}):continue
                    params=layer['adjustments'][kind]
                    adjusted=create(group,{'grade':'Grade','blur':'Blur'}[kind],kind.title()+'_'+layer['id'])
                    connect(adjusted,0,current)
                    for key,value in params.items():field(adjusted,'white' if key=='gain' else key,value)
                    current=adjusted
                if accumulated is not None:
                    merge=create(group,'Merge2','Merge_'+layer['id'])
                    connect(merge,0,accumulated);connect(merge,1,current);field(merge,'operation',layer['operation'])
                    if 'mask_node_path' in layer:
                        connect(merge,2,port(layer['mask_node_path']));field(merge,'maskChannel',layer['mask_channel'])
                    current=merge
                accumulated=current
            output=create(group,'Output','Output');connect(output,0,accumulated)
            data['output_path']=output.fullName()
            if 'write' in manifest:
                write=create(group,'Write','Write');connect(write,0,accumulated)
                for key,value in manifest['write'].items():field(write,'file' if key=='path' else key,value)
                data['write_path']=write.fullName()
            group.setSelected(False)
        boundary()
        for node in created:
            if resolve_node(nuke,'root.'+node.fullName())!=node:raise BridgeError('state_uncertain','Owned node replaced','unknown')
            inputs={i:source for target,i,source in expected_inputs if target==node}
            if any(node.input(i)!=inputs.get(i) for i in range(max(node.inputs(),max(inputs,default=-1)+1))):
                raise BridgeError('state_uncertain','Unexpected owned connection','unknown')
        for node,key,value in expected_knobs:
            knob=node.knob(key)
            actual=knob.value()
            if key=='mappings':actual=[tuple(v) for v in actual]
            if knob.Class()=='Array_Knob':
                valid=all(same_value(knob.value(i),value) for i in range(knob.arraySize()))
            else:valid=same_value(actual,value)
            if not valid:raise BridgeError('state_uncertain','Final knob readback differs','unknown')
        if any(node.input(i)!=source for node,i,source in expected_inputs):raise BridgeError('state_uncertain','Final connection readback differs','unknown')
        if group.isSelected():raise BridgeError('state_uncertain','Group selection changed','unknown')
        return dict(data,observation=observation(nuke,len(data['created_paths']),True))
    except Exception as exc:
        data['cause']=getattr(exc,'data',{})
        raise BridgeError(getattr(exc,'code','comp_build_failed'),str(exc),'unknown' if started else 'not_started',data) from exc
    finally:operation_guard.reset(guard_token)
