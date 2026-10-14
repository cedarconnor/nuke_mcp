"""Bounded main-thread observations. Missing host evidence is never absence."""
import json
import math
import os
import re
from .protocol import BridgeError
from .mutations import main_thread, check_guard, resolve_node, knob_value, NUMERIC, STRINGS, BLOCKED

MAX_DATA_BYTES = 4 * 1024 * 1024
READ_CLASSES = frozenset(('Read', 'DeepRead'))


def bounded_int(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise BridgeError('invalid_request', '%s must be an integer in %s..%s' % (name, low, high))
    return value


def json_value(value):
    if type(value) in (bool, int) or value is None: return value
    if type(value) is float and math.isfinite(value): return value
    if isinstance(value, str) and len(value) <= 1024: return value
    if isinstance(value, (list, tuple)) and len(value) <= 16:
        return [json_value(item) for item in value]
    raise ValueError('unsupported, non-finite or oversized value')


def observation(nuke, count, incomplete=False):
    env = getattr(nuke, 'env', {})
    if env.get('nc') is True or env.get('noncommercial') is True:
        return {'coverage':'partial' if count else 'unknown', 'reason':'nc_observation_unreliable'}
    return {'coverage':'partial' if incomplete else 'complete',
            'reason':'bounded_or_unavailable_fields' if incomplete else 'requested_scope_observed'}


def error_field(field, exc):
    return {'field':field, 'message':str(exc)[:256]}


def node_record(node, max_knobs=64):
    result = dict(path=node.fullName(), name=node.name(), type=node.Class(),
                  position=[node.xpos(), node.ypos()], selected=node.isSelected(),
                  inputs=[], parameters={}, omitted_knobs=[], errors=[], truncated=False)
    try:
        size = node.inputs()
        for i in range(min(size, 128)):
            source = node.input(i)
            result['inputs'].append({'index':i, 'path':source.fullName() if source is not None else None})
        result['inputs_omitted_by_limit'] = max(0, size - 128)
        result['truncated'] = size > 128
    except Exception as exc: result['errors'].append(error_field('inputs', exc))
    knobs = node.knobs()
    result['knobs_omitted_by_limit'] = max(0, len(knobs)-max_knobs)
    result['truncated'] |= len(knobs) > max_knobs
    for name in list(knobs)[:max_knobs]:
        check_guard()
        try:
            knob = knobs[name]
            kind = knob.Class()
            if name in BLOCKED or kind not in NUMERIC | STRINGS | {'Boolean_Knob', 'Enumeration_Knob'}:
                result['omitted_knobs'].append({'name':name[:256], 'reason':'unsupported_type'})
                continue
            result['parameters'][name] = {'type':kind, 'value':json_value(knob_value(knob))}
        except BridgeError: raise
        except Exception as exc:
            result['omitted_knobs'].append({'name':name[:256], 'reason':'unavailable_value', 'message':str(exc)[:256]})
            result['truncated'] = True
    return result


def append_bounded(items, item, used):
    size = len(json.dumps(item, ensure_ascii=True, allow_nan=False).encode('utf-8'))
    if used + size > MAX_DATA_BYTES: return None
    items.append(item)
    return used + size


def inspect_graph(nuke, max_nodes=256, max_knobs_per_node=64, recurse_groups=True, selected_only=False):
    main_thread()
    bounded_int(max_nodes, 1, 1000, 'max_nodes')
    bounded_int(max_knobs_per_node, 1, 128, 'max_knobs_per_node')
    if type(recurse_groups) is not bool or type(selected_only) is not bool:
        raise BridgeError('invalid_request', 'Scope flags must be booleans')
    result = dict(nodes=[], errors=[], truncated=False,
                  scope=dict(recurse_groups=recurse_groups, selected_only=selected_only))
    used = 0
    try:
        check_guard()
        with nuke.root(): nodes = nuke.allNodes(recurseGroups=recurse_groups)
        if selected_only: nodes = [n for n in nodes if n.isSelected()]
        result['truncated'] = len(nodes) > max_nodes
        for node in nodes[:max_nodes]:
            check_guard()
            try:
                record = node_record(node, max_knobs_per_node)
                next_used = append_bounded(result['nodes'], record, used)
                if next_used is None:
                    result['truncated'] = True
                    break
                used = next_used
                result['truncated'] |= record['truncated']
            except BridgeError: raise
            except Exception as exc: result['errors'].append(error_field('node', exc))
    except BridgeError as exc:
        result['observation'] = observation(nuke, len(result['nodes']), True)
        raise BridgeError(exc.code, str(exc), 'not_started', result) from exc
    except Exception as exc: result['errors'].append(error_field('enumeration', exc))
    incomplete = result['truncated'] or bool(result['errors']) or any(
        n['errors'] or n['omitted_knobs'] for n in result['nodes'])
    result['observation'] = observation(nuke, len(result['nodes']), incomplete)
    return result


def read_nodes(nuke, node_paths):
    main_thread()
    check_guard()
    if node_paths is not None:
        if not isinstance(node_paths, list) or not 1 <= len(node_paths) <= 1000:
            raise BridgeError('invalid_request', 'node_paths must contain 1..1000 full paths')
        nodes = [resolve_node(nuke, path) for path in node_paths]
        if any(n.Class() not in READ_CLASSES for n in nodes):
            raise BridgeError('invalid_request', 'Only Read and DeepRead nodes are supported')
        return nodes, False
    try:
        with nuke.root(): nodes = [n for n in nuke.allNodes(recurseGroups=True) if n.Class() in READ_CLASSES]
        return nodes[:1000], len(nodes)>1000
    except Exception as exc: raise BridgeError('state_uncertain', 'Read enumeration unavailable: '+str(exc)) from exc


def evaluated_path(nuke, node, frame, view):
    """Nuke evaluates expressions in an explicit context; expand normalized tokens only."""
    mode = node.knob('frame_mode')
    timing = node.knob('frame')
    if mode is not None and (mode.value() not in ('expression', 'none') or
            (timing is not None and timing.value() not in ('', 'frame', None))):
        raise ValueError('Read timing remapping is not qualified; path is unknown')
    for bound, behavior, outside in (('first','before',lambda a,b:a<b), ('last','after',lambda a,b:a>b)):
        limit, handling = node.knob(bound), node.knob(behavior)
        if limit is not None and handling is not None and outside(frame,limit.value()):
            raise ValueError('Read timing outside its declared range is not qualified')
    context = nuke.OutputContext()
    context.setFrame(frame)
    index = context.viewFromName(view)
    if index < 0: raise ValueError('View unavailable')
    context.setView(index)
    knob = node.knob('file')
    if knob is None: raise ValueError('File knob unavailable')
    path = knob.getEvaluatedValue(context)
    if not isinstance(path, str) or not path or len(path)>4096:
        raise ValueError('Empty or oversized evaluated path')
    path = path.replace('%V', view).replace('%v', context.viewshort(index))
    def substitute(match):
        width = int(match.group(1) or 0)
        if width > 32: raise ValueError('Unsupported frame padding')
        return ('%0' + str(width) + 'd') % frame if width else str(frame)
    path = re.sub(r'%0?(\d*)d', substitute, path)
    path = nuke.filenameFilter(path)
    if not isinstance(path, str) or len(path)>4096 or re.search(r'\[|\]|\$|#|%[0-9Vvd]', path):
        raise ValueError('Unresolved path expression or sequence token')
    if not os.path.isabs(path): raise ValueError('Relative path base is not established')
    return path


def inspect_reads(nuke, node_paths=None, channel_limit=256):
    bounded_int(channel_limit, 1, 2048, 'channel_limit')
    nodes, truncated = read_nodes(nuke, node_paths)
    result = dict(reads=[], truncated=truncated, errors=[], frame=nuke.frame())
    views = list(nuke.views())
    if not 1 <= len(views) <= 64: raise BridgeError('limit_exceeded', 'Expected 1..64 views')
    used = 0
    item = None
    try:
        for node in nodes:
            check_guard()
            item = dict(path=node.fullName(), type=node.Class(), errors=[], multipart={}, truncated=False)
            for field, key in [('file','raw_path'), ('first','first_frame'), ('last','last_frame'), ('colorspace','colorspace')]:
                try: item[key] = json_value(node[field].value())
                except Exception as exc: item['errors'].append(error_field(field, exc))
            try:
                fmt = node.format()
                item['format'] = json_value([fmt.width(), fmt.height(), fmt.pixelAspect()])
            except Exception as exc: item['errors'].append(error_field('format', exc))
            try:
                channels = node.channels()
                item['channels'] = [json_value(c) for c in channels[:channel_limit]]
                item['layers'] = sorted({c.rsplit('.',1)[0] for c in item['channels']})
                item['truncated'] = len(channels)>channel_limit
            except Exception as exc: item['errors'].append(error_field('channels', exc))
            for name in ('part', 'layer'):
                try:
                    knob = node.knob(name)
                    if knob is not None:
                        item['multipart'][name] = {'value':json_value(knob.value())}
                        if knob.Class() == 'Enumeration_Knob':
                            choices = knob.values()
                            item['multipart'][name]['choices'] = [json_value(v) for v in choices[:channel_limit]]
                            item['truncated'] |= len(choices)>channel_limit
                except Exception as exc: item['errors'].append(error_field(name, exc))
            item['evaluated_paths'] = []
            for view in views:
                check_guard()
                try: item['evaluated_paths'].append(dict(view=view, path=evaluated_path(nuke,node,result['frame'],view)))
                except Exception as exc: item['errors'].append(error_field('evaluated_path:'+view, exc))
            next_used = append_bounded(result['reads'], item, used)
            if next_used is None:
                result['truncated'] = True
                break
            used = next_used
            result['truncated'] |= item['truncated']
    except BridgeError as exc:
        if item is not None and (not result['reads'] or result['reads'][-1] is not item):
            item['truncated'] = True
            item['errors'].append(error_field('interrupted', exc))
            append_bounded(result['reads'], item, used)
        result['truncated'] = True
        result['observation'] = observation(nuke, len(result['reads']), True)
        raise BridgeError(exc.code, str(exc), 'not_started', result) from exc
    result['observation'] = observation(nuke, len(result['reads']), result['truncated'] or any(r['errors'] for r in result['reads']))
    return result


def validate_reads(nuke, first_frame, last_frame, step=1, node_paths=None):
    bounded_int(first_frame, -2147483648, 2147483647, 'first_frame')
    bounded_int(last_frame, first_frame, 2147483647, 'last_frame')
    bounded_int(step, 1, 2147483647, 'step')
    nodes, truncated = read_nodes(nuke, node_paths)
    views = list(nuke.views())
    if not 1 <= len(views) <= 64: raise BridgeError('limit_exceeded', 'Expected 1..64 views')
    frames = range(first_frame, last_frame+1, step)
    total = len(nodes)*len(views)*len(frames)
    if truncated or total > 10000: raise BridgeError('limit_exceeded', 'At most 10000 evaluated paths per request')
    result = dict(checks=[], requested_paths=total, checked_paths=0, missing_paths=0, unknown_paths=0,
                  truncated=False, frame_range=[first_frame,last_frame,step])
    used = 0
    try:
        for node in nodes:
            for frame in frames:
                for view in views:
                    check_guard()
                    item = dict(node_path=node.fullName(), frame=frame, view=view)
                    try:
                        path = evaluated_path(nuke,node,frame,view)
                        item['path'] = path
                        # stat distinguishes a missing file from access or other I/O failures.
                        import stat
                        try: item['status'] = 'exists' if stat.S_ISREG(os.stat(path).st_mode) else 'missing'
                        except FileNotFoundError: item['status'] = 'missing'
                    except Exception as exc: item.update(status='unknown', reason=str(exc)[:256])
                    next_used = append_bounded(result['checks'], item, used)
                    if next_used is None:
                        raise BridgeError('result_limit', 'Evidence reached 4 MiB')
                    used = next_used
                    result['checked_paths'] += 1
                    result['missing_paths'] += item['status']=='missing'
                    result['unknown_paths'] += item['status']=='unknown'
    except BridgeError as exc:
        result['truncated'] = True
        result['observation'] = observation(nuke, result['checked_paths'], True)
        raise BridgeError(exc.code, str(exc), 'not_started', result) from exc
    result['observation'] = observation(nuke, result['checked_paths'], bool(result['unknown_paths']))
    return result
