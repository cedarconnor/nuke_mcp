"""Trusted Nuke toolsets with immutable payloads and one authoritative manifest."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4
from .protocol import BridgeError
from .mutations import main_thread, check_guard, identifier, resolve_node, same_value
from .inspection import node_record, observation

PAYLOAD_LIMIT = 16*1024*1024
MANIFEST_LIMIT = 1024*1024


def library_root():
    return Path(os.environ.get('NUKE_MCP_LIBRARY_ROOT', str(Path.home()/'.nuke/nuke_mcp_toolsets')))


def contained_path(root, candidate):
    """Resolve existing parents, including junctions, before accepting a destination."""
    anchor = Path(root).resolve()
    path = Path(candidate)
    if not path.is_absolute(): path = anchor/path
    path = path.resolve()
    if not path.is_relative_to(anchor) or path == anchor:
        raise BridgeError('path_escape','Path must stay below the configured root')
    return path


def extension(nuke):
    env = getattr(nuke,'env',{})
    mode = env.get('nc',env.get('noncommercial'))
    if type(mode) is not bool:
        raise BridgeError('license_unknown','Cannot choose a script extension without observed NC mode')
    return '.nknc' if mode else '.nk'


def asset_name(name):
    identifier(name)
    if len(name)>64 or name.upper() in {'CON','PRN','AUX','NUL'} | {'COM'+str(i) for i in range(1,10)} | {'LPT'+str(i) for i in range(1,10)}:
        raise BridgeError('invalid_name','Reserved or oversized library name')
    return name


class Library:
    def __init__(self, root):
        self.configured = Path(root).absolute()
        self.anchor = self.configured.resolve()
    def path(self, candidate):
        if self.configured.resolve()!=self.anchor:
            raise BridgeError('path_changed','Library root changed during operation')
        return contained_path(self.anchor,candidate)
    def read(self, candidate, limit):
        path=self.path(candidate)
        with path.open('rb') as stream: data=stream.read(limit+1)
        if len(data)>limit: raise BridgeError('limit_exceeded','Library file exceeds size limit')
        return data
    def write(self, candidate, data):
        with self.path(candidate).open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def read_entry(library, name):
    asset_name(name)
    try:
        raw=library.read(name+'.json',MANIFEST_LIMIT)
        manifest=json.loads(raw)
        if (manifest.get('schema_version')!=1 or manifest.get('name')!=name or
            not re.fullmatch(r'[0-9a-f]{32}\.(?:nk|nknc)',manifest.get('payload','')) or
            not re.fullmatch(r'[0-9a-f]{64}',manifest.get('sha256','')) or
            not isinstance(manifest.get('nodes'),list) or not 1<=len(manifest['nodes'])<=1000):
            raise ValueError('Invalid manifest schema')
        host=manifest['host']
        if (not isinstance(host,dict) or host.get('extension')!=Path(manifest['payload']).suffix
                or host.get('license_mode') not in ('noncommercial','commercial')
                or not isinstance(host.get('version'),str)):
            raise ValueError('Invalid host metadata')
        nodes=manifest['nodes']
        paths=[n['path'] for n in nodes]
        if len(set(paths))!=len(paths) or paths!=sorted(paths):raise ValueError('Invalid node identities')
        for n in nodes:
            if (not isinstance(n['path'],str) or not n['path'] or not isinstance(n['class'],str)
                    or not isinstance(n['parameters'],dict) or not isinstance(n['inputs'],list)):
                raise ValueError('Invalid node metadata')
            for item in n['inputs']:
                if type(item['index']) is not int or item['index']<0 or item['path'] is not None and item['path'] not in paths:
                    raise ValueError('Invalid input identity')
        if manifest['dependencies']!=sorted({n['class'] for n in nodes}):raise ValueError('Invalid dependencies')
        for key in ('inputs','outputs'):
            if not isinstance(manifest[key],list) or any(p not in paths for p in manifest[key]):
                raise ValueError('Invalid interface identities')
        payload=library.read(manifest['payload'],PAYLOAD_LIMIT)
        if hashlib.sha256(payload).hexdigest()!=manifest['sha256']:
            raise ValueError('Payload digest mismatch')
        return manifest,payload,raw
    except BridgeError: raise
    except Exception as exc: raise BridgeError('invalid_toolset',str(exc)) from exc


def list_toolsets(root):
    library=Library(root)
    result={'entries':[],'errors':[],'truncated':False}
    if not library.anchor.exists():return result
    paths=sorted(library.anchor.glob('*.json'))
    result['truncated']=len(paths)>1000
    for path in paths[:1000]:
        check_guard()
        try:
            manifest,_,_=read_entry(library,path.stem)
            result['entries'].append({k:manifest[k] for k in ('name','sha256','payload','host')})
        except Exception as exc: result['errors'].append({'name':path.stem,'error':str(exc)[:256]})
    return result


@contextmanager
def selected_scope(nuke, scope, targets=()):
    """Change selection only in an observed scope, then restore exact original handles."""
    with scope:
        nodes=list(nuke.allNodes(recurseGroups=False))
        if any(n not in nodes for n in targets):
            raise BridgeError('state_uncertain','Selection scope is not observable')
        original=[n for n in nodes if n.isSelected()]
        try:
            for node in nodes:
                check_guard()
                node.setSelected(node in targets)
            if any(n.isSelected()!=(n in targets) for n in nodes):
                raise BridgeError('state_uncertain','Selection setup failed','unknown')
            yield
        finally:
            prior=sys.exc_info()[1]
            try:
                for node in nodes: node.setSelected(node in original)
                if any(n.isSelected()!=(n in original) for n in nodes): raise RuntimeError('Selection readback mismatch')
            except Exception as exc:
                data=dict(getattr(prior,'data',{}),selection_error=str(exc)[:256])
                if prior:data['prior_error']=str(prior)[:256]
                raise BridgeError('restoration_failed','Selection restoration failed','unknown',data) from exc


def signature(nodes, prefix):
    if not 1<=len(nodes)<=1000: raise BridgeError('state_uncertain','Expected 1..1000 observable payload nodes')
    paths={n.fullName() for n in nodes}
    records=[]
    for node in nodes:
        check_guard()
        record=node_record(node,64)
        inputs=[]
        for entry in record['inputs']:
            path=entry['path']
            if path is not None and path not in paths:
                raise BridgeError('external_dependency','Select all input dependencies: '+path)
            inputs.append({'index':entry['index'],'path':path[len(prefix):] if path else None})
        if record.get('inputs_omitted_by_limit') or record['errors']:
            raise BridgeError('state_uncertain','Cannot observe payload topology')
        values={}
        for key,value in record['parameters'].items():
            knob=node.knob(key)
            if not knob.isAnimated() and not knob.hasExpression():values[key]=value['value']
        records.append({'path':record['path'][len(prefix):],'class':record['type'],
                        'inputs':inputs,'parameters':values})
    return sorted(records,key=lambda r:r['path'])


def save_toolset(nuke, root, node_paths, name, overwrite=False):
    main_thread()
    asset_name(name)
    if type(overwrite) is not bool:raise BridgeError('invalid_request','overwrite must be boolean')
    if not isinstance(node_paths,list) or not 1<=len(node_paths)<=100:
        raise BridgeError('invalid_request','Select 1..100 node paths')
    nodes=[resolve_node(nuke,p) for p in node_paths]
    if len({n.fullName() for n in nodes})!=len(nodes):raise BridgeError('invalid_request','Duplicate node path')
    parents={n.fullName().rpartition('.')[0] for n in nodes}
    if len(parents)!=1:raise BridgeError('invalid_request','Selected nodes must share one Group scope')
    parent=parents.pop()
    scope=resolve_node(nuke,parent) if parent else nuke.root()
    prefix=parent+'.' if parent else ''
    with scope:
        inventory=list(nuke.allNodes(recurseGroups=True))
    selected_paths={n.fullName() for n in nodes}
    inventory=[n for n in inventory if n.fullName() in selected_paths or any(n.fullName().startswith(p+'.') for p in selected_paths)]
    if any(n not in inventory for n in nodes):raise BridgeError('state_uncertain','Payload nodes not observable')
    records=signature(inventory,prefix)
    suffix=extension(nuke)
    library=Library(root)
    manifest_path=library.path(name+'.json')
    if manifest_path.exists() and not overwrite:raise BridgeError('file_exists','Toolset already exists')
    check_guard()
    library.anchor.mkdir(parents=True,exist_ok=True)
    payload_name=uuid4().hex+suffix
    data={'name':name,'payload':payload_name,'published':False}
    try:
        with selected_scope(nuke,scope,nodes):
            check_guard()
            if not nuke.nodeCopy(str(library.path(payload_name))):raise RuntimeError('Host did not copy selected nodes')
        payload=library.read(payload_name,PAYLOAD_LIMIT)
        if not payload:raise RuntimeError('Copied payload is empty')
        if signature(inventory,prefix)!=records:raise RuntimeError('Source changed while copying')
        manifest=dict(schema_version=1,name=name,payload=payload_name,sha256=hashlib.sha256(payload).hexdigest(),
                      host={'version':getattr(nuke,'NUKE_VERSION_STRING','unknown'),'extension':suffix,
                            'license_mode':'noncommercial' if suffix=='.nknc' else 'commercial'},
                      verification='observed topology and bounded static knob subset',
                      dependencies=sorted({r['class'] for r in records}),nodes=records,
                      inputs=[r['path'] for r in records if not any(i['path'] for i in r['inputs'])],
                      outputs=[r['path'] for r in records if not any(i['path']==r['path'] for n in records for i in n['inputs'])])
        encoded=json.dumps(manifest,allow_nan=False).encode('utf-8')
        if len(encoded)>MANIFEST_LIMIT:raise BridgeError('limit_exceeded','Metadata exceeds 1 MiB')
        staging='manifest-'+uuid4().hex+'.tmp'
        library.write(staging,encoded)
        check_guard()
        if library.read(payload_name,PAYLOAD_LIMIT)!=payload:raise RuntimeError('Payload changed before publication')
        if overwrite:os.replace(library.path(staging),library.path(name+'.json'))
        else:os.link(library.path(staging),library.path(name+'.json'))
        data['published']=True
        verified,_,_=read_entry(library,name)
        if verified!=manifest:raise RuntimeError('Published manifest readback mismatch')
        return dict(data,manifest=manifest,observation=observation(nuke,len(records)))
    except Exception as exc:
        data.update(getattr(exc,'data',{}))
        raise BridgeError(getattr(exc,'code','toolset_save_failed'),str(exc),'partial',data) from exc


def load_toolset(nuke, root, name, group_name, position=None):
    main_thread()
    identifier(group_name)
    if position is not None and (not isinstance(position,(list,tuple)) or len(position)!=2 or any(type(v) is not int for v in position)):
        raise BridgeError('invalid_request','Position requires two integers')
    library=Library(root)
    manifest,payload,raw=read_entry(library,name)
    if Path(manifest['payload']).suffix!=extension(nuke):raise BridgeError('host_incompatible','Toolset license extension differs from host')
    for cls in manifest['dependencies']:
        if not callable(getattr(nuke.nodes,cls,None)):raise BridgeError('node_class_unavailable',cls)
    with nuke.root():
        if nuke.toNode(group_name) is not None:raise BridgeError('name_conflict','Group name exists')
    data={'name':name,'group_path':None,'sha256':manifest['sha256']}
    group=None
    started=False
    try:
        with selected_scope(nuke,nuke.root()):
            check_guard()
            started=True
            with nuke.root():group=nuke.nodes.Group(name=group_name)
            if group is None:raise RuntimeError('Group creation returned no handle; do not retry')
            data['group_path']=group.fullName()
            if data['group_path']!=group_name or resolve_node(nuke,'root.'+group_name)!=group:
                raise RuntimeError('Created Group identity not verified')
            if position is not None:
                check_guard()
                group.setXYpos(*position)
            # Revalidate the authoritative manifest and original payload after callbacks.
            current,current_payload,current_raw=read_entry(library,name)
            if current_raw!=raw or current_payload!=payload:raise RuntimeError('Toolset changed before paste')
            snapshot='verified-'+uuid4().hex+Path(manifest['payload']).suffix
            library.write(snapshot,payload)
            check_guard()
            if library.read(snapshot,PAYLOAD_LIMIT)!=payload:raise RuntimeError('Verified snapshot changed')
            with group:
                nuke.nodePaste(str(library.path(snapshot)))
                created=list(nuke.allNodes(recurseGroups=True))
            data['created_paths']=[n.fullName() for n in created]
            actual=signature(created,group_name+'.')
            if len(actual)!=len(manifest['nodes']):raise RuntimeError('Pasted node count differs')
            for expected,got in zip(manifest['nodes'],actual):
                if any(got[k]!=expected[k] for k in ('path','class','inputs')) or any(
                    not same_value(got['parameters'].get(k),v) for k,v in expected['parameters'].items()):
                    raise RuntimeError('Pasted topology or knob readback differs')
            group.setSelected(False)
        if resolve_node(nuke,'root.'+group_name)!=group:raise RuntimeError('Final Group identity unavailable')
        with group:final_nodes=list(nuke.allNodes(recurseGroups=True))
        if signature(final_nodes,group_name+'.')!=actual:raise RuntimeError('Pasted state changed during selection restoration')
        if group.isSelected():raise RuntimeError('Group selection restoration failed')
        if position is not None and [group.xpos(),group.ypos()]!=list(position):raise RuntimeError('Group position mismatch')
        return dict(data,observation=observation(nuke,len(created)))
    except Exception as exc:
        data.update(getattr(exc,'data',{}))
        raise BridgeError(getattr(exc,'code','toolset_load_failed'),str(exc),'unknown' if started else 'not_started',data) from exc
