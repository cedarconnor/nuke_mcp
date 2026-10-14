"""Bounded batch preflight and execution; undo grouping is not a transaction."""
from copy import deepcopy
from . import mutations as m
from .protocol import BridgeError

FIELDS = {'set_knob': {'op','node_path','knob','value'},
          'connect': {'op','node_path','input_index','source_path'},
          'position': {'op','node_path','x','y'}}


def normalize(operations):
    if not isinstance(operations,list) or not 1 <= len(operations) <= 100:
        raise BridgeError('invalid_request','Provide 1..100 explicit edit operations')
    operations=deepcopy(operations)
    seen=set()
    for op in operations:
        if not isinstance(op,dict) or op.get('op') not in FIELDS or set(op) != FIELDS[op['op']]:
            raise BridgeError('invalid_request','Unsupported operation or unexpected fields')
        path=m.canonical_path(op['node_path'])
        target=(path,op['op'],op.get('knob') if op['op']=='set_knob' else op.get('input_index'))
        try:
            if target in seen: raise BridgeError('duplicate_target','Only one edit per target in a batch')
            seen.add(target)
        except TypeError as exc: raise BridgeError('invalid_request','Invalid knob/input target') from exc
    return operations


def initial_items(operations):
    return [dict(index=i,operation=op,state='not_started',outcome='not_started') for i,op in enumerate(operations)]


def prepare(nuke, operations):
    items=initial_items(operations)
    prepared=[]
    for i,op in enumerate(operations):
        try:
            value=m.preflight(nuke,op)
            value['before']=deepcopy(value['before'])
            prepared.append(value)
            items[i].update(state='validated',before=value['before'])
        except Exception as exc:
            items[i].update(state='failed',error={'code':getattr(exc,'code','state_uncertain'),'message':str(exc)})
            raise BridgeError('preflight_failed','Batch validation failed before writes','not_started',{'items':items}) from exc
    return prepared,items


def validate_batch(nuke, operations):
    m.main_thread()
    operations=normalize(operations)
    _,items=prepare(nuke,operations)
    return {'dry_run':True,'outcome':'not_started','items':items,'atomic':False}


def execute_batch(nuke, operations, dry_run=True, expected_revision=None, revision_provider=None):
    m.main_thread()
    if type(dry_run) is not bool: raise BridgeError('invalid_request','dry_run must be boolean')
    operations=normalize(operations)
    def revision_check():
        if expected_revision is not None:
            if type(expected_revision) is not int: raise BridgeError('invalid_request','expected_revision must be integer')
            if revision_provider is None: raise BridgeError('revision_unavailable','No trustworthy scene revision provider installed')
            if revision_provider() != expected_revision: raise BridgeError('revision_conflict','Scene revision changed')
    revision_check()
    prepared,items=prepare(nuke,operations)
    result={'dry_run':dry_run,'outcome':'not_started','items':items,'atomic':False}
    if dry_run: return result
    for item in items: item['state']='not_started'
    undo=nuke.Undo()
    undo.begin('Nuke MCP batch edit')
    failure=None
    try:
        for i,op in enumerate(operations):
            try:
                revision_check()
                current=m.preflight(nuke,op)
                earlier=prepared[i]
                if (current['node'] != earlier['node'] or current.get('knob') != earlier.get('knob') or
                    current.get('source') != earlier.get('source') or not m.same_value(current['before'],earlier['before'])):
                    raise BridgeError('state_conflict','Target changed after preflight')
                data=m.apply(nuke,op)
                items[i].update(state='completed',outcome='applied',data=data)
            except Exception as exc:
                outcome=exc.outcome if isinstance(exc,BridgeError) else 'unknown'
                items[i].update(state='failed',outcome=outcome,
                    error={'code':getattr(exc,'code','host_error'),'message':str(exc)},
                    data=exc.data if isinstance(exc,BridgeError) else {})
                result['outcome']='partial' if any(x['outcome']=='applied' for x in items) else outcome
                failure=BridgeError('batch_failed','Stopped at item %s; earlier applied edits remain' % i,result['outcome'],result)
                break
        if failure is None: result['outcome']='applied'
    finally:
        try: undo.end()
        except Exception as exc:
            result['undo_error']=str(exc)
            failure=BridgeError('undo_group_failed','Could not close undo group','unknown',result)
    if failure: raise failure
    return result
