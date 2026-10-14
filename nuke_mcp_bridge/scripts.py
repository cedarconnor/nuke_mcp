"""Explicit script replacement/saving and bounded, static project settings."""
import hashlib
import math
from pathlib import Path
from uuid import uuid4
from .protocol import BridgeError
from .mutations import main_thread, check_guard, inspect_knob, knob_value, same_value
from .toolsets import extension


def script_path(nuke, path):
    if not isinstance(path,str) or not path or not Path(path).is_absolute():
        raise BridgeError('invalid_path','An explicit absolute script path is required')
    resolved=Path(path).resolve()
    if resolved.suffix.lower()!=extension(nuke):
        raise BridgeError('invalid_extension','Use the current host script extension: '+extension(nuke))
    if not resolved.parent.is_dir():raise BridgeError('missing_directory','Parent directory must already exist')
    if resolved.exists() and not resolved.is_file():raise BridgeError('invalid_path','Target is not a regular file')
    return resolved


def state(nuke):
    root=nuke.root()
    dirty=root.modified()
    if type(dirty) is not bool:raise BridgeError('state_uncertain','Script dirty state unavailable')
    return {'path':root.name(),'modified':dirty}


def path_matches(nuke, target):
    name=nuke.root().name()
    return isinstance(name,str) and Path(name).is_absolute() and Path(name).resolve()==target


def restore_identity(nuke, before, data, owned_root):
    """Restore only save target/dirty metadata, never imply graph or disk rollback."""
    try:
        root=nuke.root()
        current=state(nuke)
        if root!=owned_root or current['modified'] or current['path'] not in (before['path'],data['target']):
            data['identity_restored']=False
            data['restoration_error']='Script changed during save; retaining current identity and unsaved state'
            return
        root.setName(before['path'])
        # Never clear new edits made by a rename callback while restoring metadata.
        if before['modified']:root.setModified(True)
        data['identity_restored']=state(nuke)==before
    except Exception as exc:
        data['identity_restored']=False
        data['restoration_error']=str(exc)[:256]


def save_script(nuke, path=None, overwrite=False):
    main_thread()
    if type(overwrite) is not bool:raise BridgeError('invalid_request','overwrite must be boolean')
    before=state(nuke)
    owned_root=nuke.root()
    current=path is None
    requested=before['path'] if current else path
    target=script_path(nuke,requested)
    if target.exists() and not (current or overwrite):raise BridgeError('file_exists','Save-as target exists')
    data={'before':before,'target':str(target),'save_current':current}
    check_guard()
    if script_path(nuke,requested)!=target:raise BridgeError('path_changed','Destination changed before save')
    try:
        nuke.scriptSaveAs(str(target),overwrite=1 if current or overwrite else 0)
        if script_path(nuke,requested)!=target or not path_matches(nuke,target):raise RuntimeError('Saved script path differs')
        if state(nuke)['modified']:raise RuntimeError('Host still reports unsaved changes')
        if not target.is_file() or target.stat().st_size==0:raise RuntimeError('Saved file is missing or empty')
        digest=hashlib.sha256()
        with target.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        return dict(data,after=state(nuke),sha256=digest.hexdigest(),bytes=target.stat().st_size)
    except Exception as exc:
        restore_identity(nuke,before,data,owned_root)
        raise BridgeError('script_save_failed',str(exc),'unknown',data) from exc


def open_script(nuke, path, discard_unsaved_changes=False):
    main_thread()
    if type(discard_unsaved_changes) is not bool:raise BridgeError('invalid_request','discard_unsaved_changes must be boolean')
    target=script_path(nuke,path)
    if not target.is_file():raise BridgeError('file_missing','Script does not exist')
    before=state(nuke)
    if before['modified'] and not discard_unsaved_changes:
        raise BridgeError('unsaved_changes','Explicit discard_unsaved_changes is required')
    data={'before':before,'target':str(target),'discard_unsaved_changes':discard_unsaved_changes}
    check_guard()
    if script_path(nuke,path)!=target:raise BridgeError('path_changed','Source changed before open')
    try:
        # Avoid a modal save prompt only after explicit discard authorization. No implicit clear.
        if before['modified']:nuke.root().setModified(False)
        nuke.scriptOpen(str(target))
        if not path_matches(nuke,target):raise RuntimeError('Opened script path differs')
        return dict(data,after=state(nuke))
    except Exception as exc:
        # Opening may already have replaced the graph. Never relabel it as the old script.
        try:nuke.root().setModified(True)
        except Exception:pass
        raise BridgeError('script_open_failed',str(exc),'unknown',data) from exc


def new_disposable_script(nuke):
    """Internal only; callers must own the session and enforce Task 12 clean-session guards."""
    main_thread()
    before=state(nuke)
    if before['modified']:raise BridgeError('unsaved_changes','Refusing to clear dirty script')
    check_guard()
    try:
        nuke.scriptClear()
        after=state(nuke)
        if after['path'] not in ('Root','root','') or after['modified']:
            raise RuntimeError('Disposable root state not verified')
        return {'before':before,'after':after,'graph_coverage':'unknown'}
    except Exception as exc:raise BridgeError('script_clear_failed',str(exc),'unknown') from exc


COLOR_KNOBS=frozenset(('colorManagement','OCIO_config','workingSpaceLUT','monitorLut',
                      'int8Lut','int16Lut','logLut','floatLut'))


def format_value(root):
    f=root.format()
    return dict(width=f.width(),height=f.height(),pixel_aspect=f.pixelAspect())


def validate_settings(nuke, settings):
    if not isinstance(settings,dict) or not settings or set(settings)-{'fps','first_frame','last_frame','format','color_management'}:
        raise BridgeError('invalid_settings','Supported fields: fps, first_frame, last_frame, format, color_management')
    root=nuke.root()
    values={k:v for k,v in settings.items() if k not in ('format','color_management')}
    if 'fps' in values and (type(values['fps']) not in (int,float) or not math.isfinite(values['fps']) or not 0<values['fps']<=1000):
        raise BridgeError('invalid_settings','FPS must be finite and in (0,1000]')
    for k in ('first_frame','last_frame'):
        if k in values and (type(values[k]) is not int or not -2147483648<=values[k]<=2147483647):
            raise BridgeError('invalid_settings','Frame bounds require signed 32-bit integers')
    if {'first_frame','last_frame'} & values.keys():
        first=values.get('first_frame',root['first_frame'].value())
        last=values.get('last_frame',root['last_frame'].value())
        if first>last:raise BridgeError('invalid_settings','First frame exceeds last frame')
    color=settings.get('color_management',{})
    if not isinstance(color,dict) or set(color)-COLOR_KNOBS:raise BridgeError('invalid_settings','Unsupported color-management knob')
    values.update(color)
    prepared={}
    for key,value in values.items():
        knob=root.knob(key)
        if key in ('fps','first_frame','last_frame') and knob is not None and knob.Class()=='Array_Knob':
            # Nuke 17 exposes these scalar numeric root fields as Array_Knob.
            if knob.arraySize()!=1 or knob.isAnimated(0) or knob.hasExpression(0):
                raise BridgeError('dynamic_knob','Project numeric fields must be static scalar knobs')
        else:knob=inspect_knob(root,key,value)
        if key in color and knob.Class()!='Enumeration_Knob':
            raise BridgeError('knob_unavailable','Color settings require an observed enumeration')
        prepared[key]={'knob':knob,'before':knob_value(knob),'value':value}
    if 'format' in settings:
        f=settings['format']
        if not isinstance(f,dict) or set(f)!={'width','height','pixel_aspect'}:
            raise BridgeError('invalid_settings','Format requires width, height and pixel_aspect')
        if any(type(f[k]) is not int or not 1<=f[k]<=65536 for k in ('width','height')) or type(f['pixel_aspect']) not in (int,float) or not math.isfinite(f['pixel_aspect']) or not 0<f['pixel_aspect']<=100:
            raise BridgeError('invalid_settings','Invalid format dimensions or pixel aspect')
        knob=root.knob('format')
        if knob is None or knob.Class()!='Format_Knob' or knob.isAnimated() or knob.hasExpression():
            raise BridgeError('knob_unavailable','Static format knob unavailable')
        prepared['format']={'knob':knob,'before':format_value(root),'value':dict(f)}
    return root,prepared


def set_project_settings(nuke, settings, dry_run=True):
    main_thread()
    if type(dry_run) is not bool:raise BridgeError('invalid_request','dry_run must be boolean')
    root,prepared=validate_settings(nuke,settings)
    script_identity=root.name()
    data={'dry_run':dry_run,'before':{k:v['before'] for k,v in prepared.items()},
          'requested':{k:v['value'] for k,v in prepared.items()},'completed':[]}
    if dry_run:return dict(data,outcome='not_started')
    started=False
    try:
        for key,row in prepared.items():
            check_guard()
            if nuke.root()!=root or root.name()!=script_identity:raise RuntimeError('Script changed during settings apply')
            current_root,current=validate_settings(nuke,settings)
            if current_root!=root or current[key]['knob']!=row['knob'] or current[key]['before']!=row['before']:
                raise RuntimeError('Setting target changed before write: '+key)
            started=True
            value=row['value']
            if key=='format':
                value=nuke.addFormat('%s %s %s mcp_%s' % (value['width'],value['height'],value['pixel_aspect'],uuid4().hex))
                if value is None:raise RuntimeError('Host did not create requested format')
                check_guard()
                if nuke.root()!=root or root.name()!=script_identity or root.knob(key)!=row['knob']:
                    raise RuntimeError('Format target changed during format registration')
            row['knob'].setValue(value)
            actual=format_value(root) if key=='format' else knob_value(row['knob'])
            if not same_value(actual,row['value']):raise RuntimeError('Setting readback mismatch: '+key)
            data['completed'].append(key)
        _,final=validate_settings(nuke,settings)
        if nuke.root()!=root or root.name()!=script_identity or any(final[k]['knob']!=r['knob'] or not same_value(final[k]['before'],r['value']) for k,r in prepared.items()):
            raise RuntimeError('Final project settings readback differs')
        return dict(data,after={k:v['before'] for k,v in final.items()},outcome='applied')
    except Exception as exc:
        raise BridgeError(getattr(exc,'code','settings_failed'),str(exc),'unknown' if started else 'not_started',data) from exc
