"""Bounded shot plans, explicit disposable sessions and no-clobber publication."""
import hashlib
import os
from pathlib import Path
import re
from uuid import uuid4
from . import manifests
from .capabilities import probe_capabilities
from .mutations import (main_thread, check_guard, operation_guard, operation_context,
                        create_node, connect_input, resolve_node, inspect_knob, knob_value, same_value)
from .protocol import BridgeError
from .scripts import state, script_path, set_project_settings, save_script, open_script, new_disposable_script
from .toolsets import Library, read_entry, extension, load_toolset
from .events import plan_stamp, check_plan_stamp


RELATIVE_PREFIX='[file dirname [value root.name]]'
MAX_PATHS=10000


def host_binding(nuke):
    context=operation_context.get()
    if not context or not context.get('server_instance_id'):raise BridgeError('context_unavailable','Workflow plans require a host instance')
    caps=probe_capabilities(nuke)
    config=os.environ.get('OCIO','')
    return {'instance':context['server_instance_id'],'version':caps['nuke_version'],
            'license':extension(nuke),'gui':getattr(nuke,'GUI',False),
            'ocio':file_fact(config) if config and Path(config).is_absolute() else config}


def file_fact(path):
    p=Path(path).resolve()
    fact={'path':str(p),'exists':p.exists()}
    if fact['exists']:
        if not p.is_file():raise BridgeError('invalid_path','Expected a regular file: '+str(p))
        stat=p.stat();fact.update(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    return fact


def expand_path(nuke, raw, frame, script=None):
    """Explicit literal/printf/hash sequences; refuse unevaluated Tcl or view tokens."""
    value=raw
    if script and value.startswith(RELATIVE_PREFIX):value=str(Path(script).parent)+value[len(RELATIVE_PREFIX):]
    if any(c in value for c in ('[',']','$')):raise BridgeError('path_unresolved','Unsupported source/output expression')
    value=nuke.filenameFilter(value)
    def hashes(match):return ('%0'+str(len(match[0]))+'d')%frame
    value=re.sub(r'#{1,12}',hashes,value)
    def printf(match):return ('%0'+(match[1] or '1')+'d')%frame
    value=re.sub(r'%0?([1-9][0-9]?)?d',printf,value)
    if '%' in value or '#' in value or not Path(value).is_absolute():raise BridgeError('path_unresolved','Expected an absolute literal or supported sequence')
    return str(Path(value).resolve())


def settings_for(shot):
    return {'fps':shot['fps']['numerator']/shot['fps']['denominator'],
            'first_frame':shot['frame_range']['work_first'],'last_frame':shot['frame_range']['work_last'],
            'format':shot['format'],'color_management':shot['color_settings']}


def shot_binding(nuke,shot,library,output,budget):
    check_guard()
    target=output.path(shot['script_path'])
    if script_path(nuke,shot['script_path'])!=target:raise BridgeError('path_changed','Script destination changed')
    if target.exists():raise BridgeError('file_exists','Script already exists; reconcile receipts: '+str(target))
    inputs=[];writes=[]
    for plate in shot['plates']:
        if plate['last']-plate['first']+1>MAX_PATHS:raise BridgeError('limit_exceeded','Plate range exceeds path limit')
        for frame in range(plate['first'],plate['last']+1):
            check_guard();budget[0]+=1
            if budget[0]>MAX_PATHS:raise BridgeError('limit_exceeded','Workflow exceeds 10000 evaluated paths')
            fact=file_fact(expand_path(nuke,plate['path'],frame))
            if not fact['exists']:raise BridgeError('file_missing','Missing plate: '+fact['path'])
            inputs.append(dict(fact,frame=frame))
    frames=shot['frame_range']
    if frames['work_last']-frames['work_first']+1>MAX_PATHS:raise BridgeError('limit_exceeded','Write range exceeds path limit')
    for frame in range(frames['work_first'],frames['work_last']+1):
        check_guard();budget[0]+=1
        if budget[0]>MAX_PATHS:raise BridgeError('limit_exceeded','Workflow exceeds 10000 evaluated paths')
        path=output.path(expand_path(nuke,shot['write']['path'],frame,str(target)))
        if not path.parent.is_dir():raise BridgeError('missing_directory','Write directory must exist')
        fact=file_fact(path)
        if fact['exists']:raise BridgeError('file_exists','Write output already exists: '+str(path))
        writes.append(dict(fact,frame=frame))
    toolset=None
    if 'toolset' in shot:
        entry,_,raw=read_entry(library,shot['toolset'])
        if Path(entry['payload']).suffix!=extension(nuke):raise BridgeError('host_incompatible','Toolset license differs')
        ports=[n for n in entry['nodes'] if n['class']=='Input' and '.' not in n['path']]
        outlets=[n for n in entry['nodes'] if n['class']=='Output' and '.' not in n['path']]
        if len(ports)!=len(shot['plates']) or len(outlets)!=1 or sorted(p['parameters'].get('number',-1) for p in ports)!=list(range(len(ports))):
            raise BridgeError('invalid_toolset','Shot toolset needs contiguous numbered Inputs and one Output')
        toolset={'name':shot['toolset'],'manifest_sha256':hashlib.sha256(raw).hexdigest(),'payload_sha256':entry['sha256']}
    elif len(shot['plates'])!=1:raise BridgeError('invalid_manifest','Multiple plates require an explicit toolset input contract')
    return {'shot_id':shot['shot_id'],'script_path':str(target),'sources':inputs,'writes':writes,'toolset':toolset}


def plan_shot_setup(nuke,manifest,library_root):
    main_thread();normalized=manifests.validate_shot_manifest(manifest)
    scene_revision=plan_stamp()
    if not Path(normalized['output_root']).is_absolute():raise BridgeError('invalid_path','output_root must be absolute')
    output=Library(normalized['output_root']);library=Library(library_root)
    if not output.anchor.is_dir():raise BridgeError('missing_directory','output_root must exist')
    host=host_binding(nuke)
    for cls in ('Read','Write'):
        if not callable(getattr(nuke.nodes,cls,None)):raise BridgeError('node_class_unavailable',cls)
    shots=[];budget=[0];destinations=set()
    for shot in normalized['shots']:
        set_project_settings(nuke,settings_for(shot))
        bound=shot_binding(nuke,shot,library,output,budget)
        # Static Write paths legitimately repeat across frames of one shot, but never across shots.
        paths={bound['script_path']}|{w['path'] for w in bound['writes']}
        if bound['script_path'] in {w['path'] for w in bound['writes']} or paths & destinations:
            raise BridgeError('file_conflict','Shot outputs overlap')
        destinations.update(paths);shots.append(bound)
    plan={'schema_version':1,'manifest':normalized,'host':host,'original_script':state(nuke),
          'scene_revision':scene_revision,
          'library_root':str(library.anchor),'output_root':str(output.anchor),
          'disposable':os.environ.get('NUKE_MCP_DISPOSABLE_SESSION')=='1','shots':shots,
          'provenance':'source existence, size and mtime; plate contents are not hashed',
          'proposed_nodes':['Read per plate','optional toolset Group','Write'],'errors':[]}
    check_plan_stamp(scene_revision)
    return dict(plan,digest=manifests.plan_digest(plan))


def set_field(nuke,node,key,value):
    """Verified static workflow fields; native scalar/array numeric knobs are explicit."""
    check_guard();path=node.fullName()
    if resolve_node(nuke,'root.'+path)!=node:raise BridgeError('state_uncertain','Workflow node identity changed')
    knob=node.knob(key)
    if knob is not None and knob.Class() in ('Channel_Knob','ChannelMask_Knob') and key in ('channels','maskChannel','in','in1','out','out1'):
        source=node.input(2 if key=='maskChannel' else 0)
        channels=set(source.channels()) if source is not None else set()
        choices=channels if key=='maskChannel' else {c.rsplit('.',1)[0] for c in channels}
        if key=='channels' and {'rgba.red','rgba.green','rgba.blue'}<=channels:choices.add('rgb')
        if key in ('out','out1'):choices={'rgba'}
        if value not in choices:raise BridgeError('channels_unavailable','Requested channel or layer is unavailable')
        if any(getattr(knob,method,lambda:False)() for method in ('isAnimated','hasExpression')):
            raise BridgeError('dynamic_knob','Channel settings must be static')
        knob.setValue(value)
        if knob.value()!=value:raise BridgeError('state_uncertain','Channel readback differs','unknown')
    elif knob is not None and knob.Class()=='Array_Knob' and key in ('first','last','white','gamma','size','number'):
        count=knob.arraySize()
        if not 1<=count<=4 or type(value) not in (int,float):raise BridgeError('unsafe_knob','Unsupported numeric workflow knob')
        for i in range(count):
            if knob.isAnimated(i) or knob.hasExpression(i):raise BridgeError('dynamic_knob','Workflow setting must be static')
        for i in range(count):check_guard();knob.setValue(value,i)
        actual=[knob.value(i) for i in range(count)]
        if any(not same_value(v,value) for v in actual):raise BridgeError('state_uncertain','Numeric readback differs','unknown')
    else:
        knob=inspect_knob(node,key,value);knob.setValue(value)
        if not same_value(knob_value(knob),value):raise BridgeError('state_uncertain','Workflow readback differs','unknown')
    if resolve_node(nuke,'root.'+path)!=node or node.knob(key)!=knob:raise BridgeError('state_uncertain','Workflow knob identity changed','unknown')


def evaluated_write(nuke,node,frame):
    context=nuke.OutputContext();context.setFrame(frame)
    return str(Path(nuke.filenameFilter(node['file'].getEvaluatedValue(context))).resolve())


def verify_setup(nuke,shot):
    settings=set_project_settings(nuke,settings_for(shot))
    if settings['before']!=settings['requested']:raise BridgeError('state_uncertain','Project settings changed','unknown')
    def verify(node,values):
        for key,value in values.items():
            knob=node.knob(key)
            if knob is None:raise BridgeError('state_uncertain','Missing workflow knob','unknown')
            if knob.Class()=='Array_Knob':
                actual=[knob.value(i) for i in range(knob.arraySize())]
                matches=all(same_value(v,value) for v in actual)
            else:matches=same_value(knob_value(knob),value)
            if not matches:raise BridgeError('state_uncertain','Workflow final knob differs: '+key,'unknown')
    reads=[]
    for i,plate in enumerate(shot['plates']):
        node=resolve_node(nuke,'root.Plate_'+str(i));reads.append(node)
        verify(node,{'file':plate['path'],'colorspace':plate['colorspace'],'first':plate['first'],'last':plate['last']})
    source=reads[0]
    if 'toolset' in shot:
        source=resolve_node(nuke,'root.ShotToolset')
        if any(source.input(i)!=node for i,node in enumerate(reads)):raise BridgeError('state_uncertain','Toolset inputs differ','unknown')
    write=resolve_node(nuke,'root.ShotWrite')
    verify(write,{'file' if k=='path' else k:v for k,v in shot['write'].items()})
    if write.input(0)!=source:raise BridgeError('state_uncertain','Write input differs','unknown')
    return write


def apply_shot_setup(nuke,manifest,plan_digest,library_root,operations):
    main_thread();plan=plan_shot_setup(nuke,manifest,library_root)
    if plan['digest']!=plan_digest:raise BridgeError('stale_plan','Plan binding changed; replan before apply')
    if operations.instance_id!=plan['host']['instance']:raise BridgeError('instance_changed','Operation registry changed')
    if not plan['disposable'] or not plan['host']['gui']:raise BridgeError('disposable_session_required','Launch an owned GUI host with NUKE_MCP_DISPOSABLE_SESSION=1')
    original=plan['original_script']
    if original['modified']:raise BridgeError('unsaved_changes','Shot generation refuses a dirty current script')
    original_path=original['path'] if Path(original['path']).is_absolute() else None
    original_fact=file_fact(original_path) if original_path else None
    if original_fact and not original_fact['exists']:raise BridgeError('file_missing','Original saved script unavailable for restoration')
    output=Library(manifest['output_root']);library=Library(library_root)
    result={'completed':[],'current':None,'restoration':{'ok':False},'request':dict(operation_context.get()),'outcome':'applied'}
    started=False;failure=None;owned_paths={original['path'],'Root','root',''}
    active=[nuke.root(),original['path']]
    inherited_guard=operation_guard.get()
    def workflow_boundary():
        if inherited_guard:inherited_guard()
        check_plan_stamp(plan['scene_revision'],allow_owned=True)
        if nuke.root()!=active[0] or nuke.root().name()!=active[1]:
            raise BridgeError('script_changed','Script ownership changed during shot generation','unknown')
    workflow_token=operation_guard.set(workflow_boundary)
    try:
        for index,shot in enumerate(plan['manifest']['shots']):
            check_guard()
            if host_binding(nuke)!=plan['host'] or shot_binding(nuke,shot,library,output,[0])!=plan['shots'][index]:
                raise BridgeError('stale_plan','Shot source or host changed')
            if state(nuke)['modified']:raise BridgeError('unsaved_changes','Current script changed between shots')
            started=True
            record={'shot_id':shot['shot_id'],'script_path':plan['shots'][index]['script_path'],'published':False,'created_paths':[]}
            result['current']=record
            record['fresh_script']=new_disposable_script(nuke)
            active[:]=[nuke.root(),nuke.root().name()]
            owned_paths={active[1]}
            set_project_settings(nuke,settings_for(shot),False)
            reads=[]
            for i,plate in enumerate(shot['plates']):
                data=create_node(nuke,'Read',name='Plate_'+str(i),parameters={'file':plate['path'],'colorspace':plate['colorspace']})
                node=resolve_node(nuke,'root.'+data['path']);record['created_paths'].append(data['path'])
                set_field(nuke,node,'first',plate['first']);set_field(nuke,node,'last',plate['last']);reads.append(data['path'])
            source=reads[0]
            if 'toolset' in shot:
                loaded=load_toolset(nuke,library_root,shot['toolset'],'ShotToolset')
                source=loaded['group_path'];record['created_paths'].append(source)
                for i,path in enumerate(reads):connect_input(nuke,'root.'+source,i,'root.'+path)
            write=create_node(nuke,'Write',name='ShotWrite',inputs=['root.'+source])
            record['created_paths'].append(write['path']);node=resolve_node(nuke,'root.'+write['path'])
            for key,value in shot['write'].items():set_field(nuke,node,'file' if key=='path' else key,value)
            verify_setup(nuke,shot)
            target=output.path(shot['script_path']);staging=target.parent/('.stage-'+uuid4().hex+extension(nuke))
            owned_paths.update((str(target),str(staging)))
            record['staging_path']=str(output.path(staging));record['save']=save_script(nuke,str(output.path(staging)))
            active[:]=[nuke.root(),nuke.root().name()]
            check_guard()
            if host_binding(nuke)!=plan['host'] or shot_binding(nuke,shot,library,output,[0])!=plan['shots'][index]:
                raise BridgeError('stale_plan','Shot changed before publication')
            # link is an atomic, same-filesystem no-clobber publication. Staging is retained for evidence.
            os.link(output.path(staging),output.path(shot['script_path']))
            record['published']=True
            record['reload']=open_script(nuke,str(output.path(shot['script_path'])))
            active[:]=[nuke.root(),nuke.root().name()]
            node=verify_setup(nuke,shot)
            actual=[evaluated_write(nuke,node,w['frame']) for w in plan['shots'][index]['writes']]
            expected=[w['path'] for w in plan['shots'][index]['writes']]
            if actual!=expected:raise BridgeError('state_uncertain','Published relative Write paths differ','partial')
            record['write_paths']=actual
            result['completed'].append(record);result['current']=None
    except Exception as exc:failure=exc
    finally:
        operation_guard.reset(workflow_token)
        if started and original_path:
            # Cleanup is allowed after cancellation, but only restores the saved original in this opted-in disposable session.
            token=operation_guard.set(None)
            try:
                current=state(nuke)['path']
                canonical=lambda p:str(Path(p).resolve()) if Path(p).is_absolute() else p
                if canonical(current) not in {canonical(p) for p in owned_paths}:
                    raise RuntimeError('Script switched outside workflow ownership; restoration refused')
                if file_fact(original_path)!=original_fact:raise RuntimeError('Original script changed on disk; restoration refused')
                result['restoration']={'ok':True,'receipt':open_script(nuke,original_path,discard_unsaved_changes=True)}
            except Exception as exc:
                result['restoration']={'ok':False,'error':str(exc)}
                if failure is None:failure=exc
            finally:operation_guard.reset(token)
        elif started:result['restoration']={'ok':True,'reason':'Original was unnamed; owned result retained'}
    if failure:
        result['cause']=dict(getattr(failure,'data',{}))
        result['outcome']='partial' if result['completed'] or started else 'not_started'
        raise BridgeError(getattr(failure,'code','shot_setup_failed'),str(failure),result['outcome'],result) from failure
    return result
