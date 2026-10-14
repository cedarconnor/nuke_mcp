"""Typed, main-thread edits with explicit validation and affirmative readback."""
import math
import re
import threading
from contextvars import ContextVar
from .protocol import BridgeError

IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
BLOCKED = frozenset(('name', 'selected', 'xpos', 'ypos', 'knobChanged', 'onCreate',
    'onUserCreate', 'onDestroy', 'updateUI', 'autolabel', 'beforeRender', 'afterRender',
    'beforeFrameRender', 'afterFrameRender', 'renderProgress'))
NUMERIC = frozenset(('Double_Knob', 'Float_Knob', 'Int_Knob', 'XY_Knob', 'XYZ_Knob',
    'WH_Knob', 'Color_Knob', 'AColor_Knob', 'UV_Knob', 'Scale_Knob'))
STRINGS = frozenset(('String_Knob', 'Multiline_Eval_String_Knob', 'File_Knob', 'Eval_String_Knob'))
operation_guard = ContextVar('nuke_edit_guard', default=None)
operation_context = ContextVar('nuke_operation_context', default=None)


def check_guard():
    guard = operation_guard.get()
    if guard is not None: guard()


def main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise BridgeError('wrong_thread', 'Nuke edits require the host main thread')


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise BridgeError('invalid_request', 'Expected a Nuke identifier')
    return value


def canonical_path(path):
    if not isinstance(path, str) or not path:
        raise BridgeError('invalid_request', 'Expected a full node path')
    parts = path.split('.')
    if parts[0] == 'root': parts = parts[1:]
    if not parts: raise BridgeError('invalid_request', 'Root is not an editable node')
    for part in parts: identifier(part)
    return '.'.join(parts)


def resolve_node(nuke, node_path):
    main_thread()
    path = canonical_path(node_path)
    try:
        with nuke.root():
            node = nuke.toNode(path)
            if node is None:
                raise BridgeError('state_uncertain', 'Node lookup unavailable; absence is not established: ' + path)
            if node.fullName() != path:
                raise BridgeError('ambiguous_node', 'Use a full root-relative path')
            if '.' not in node_path:
                matches = [n for n in nuke.allNodes(recurseGroups=True) if n.name() == path]
                if len(matches) > 1:
                    raise BridgeError('ambiguous_node', 'Use root.' + path + ' or a full Group path')
            return node
    except BridgeError:
        raise
    except Exception as exc:
        raise BridgeError('state_uncertain', 'Cannot resolve node: ' + str(exc)) from exc


def finite_value(value):
    if isinstance(value, (list, tuple)):
        if not 1 <= len(value) <= 16:
            raise BridgeError('invalid_value', 'Expected 1..16 components')
        for item in value:
            if isinstance(item, (list, tuple, dict)): raise BridgeError('invalid_value', 'Nested values unsupported')
            finite_value(item)
    elif type(value) in (int, float):
        if not math.isfinite(value): raise BridgeError('invalid_value', 'Non-finite value')
    elif type(value) not in (bool, str):
        raise BridgeError('invalid_value', 'Unsupported value type')


def parameter_syntax(name, value):
    identifier(name)
    if name in BLOCKED:
        raise BridgeError('unsafe_knob', 'Use explicit tools for identity/position; callback knobs require raw Python')
    finite_value(value)


def inspect_knob(node, name, value):
    parameter_syntax(name, value)
    knob = node.knob(name)
    if knob is None: raise BridgeError('knob_unavailable', 'Knob unavailable: ' + name)
    kind = knob.Class()
    if kind not in NUMERIC | STRINGS | {'Boolean_Knob', 'Enumeration_Knob'}:
        raise BridgeError('unsafe_knob', 'Unsupported typed knob class: ' + kind)
    if knob.isAnimated() or knob.hasExpression():
        raise BridgeError('dynamic_knob', 'Static edits cannot replace animation or expressions')
    if kind in NUMERIC:
        size = knob.arraySize()
        if any(knob.isAnimated(i) or knob.hasExpression(i) for i in range(size)):
            raise BridgeError('dynamic_knob', 'Static edits cannot replace animation or expressions')
        values = list(value) if isinstance(value, (tuple, list)) else [value]
        if (size > 1 and not isinstance(value, (tuple, list))) or len(values) != size:
            raise BridgeError('invalid_value', 'Provide exactly %s components' % size)
        if any(type(v) not in (int, float) for v in values):
            raise BridgeError('invalid_value', 'Numeric knob requires numbers')
        if kind == 'Int_Knob' and any(type(v) is not int for v in values):
            raise BridgeError('invalid_value', 'Integer knob requires integers')
    elif kind == 'Boolean_Knob':
        if type(value) is not bool: raise BridgeError('invalid_value', 'Boolean knob requires true/false')
    elif kind == 'Enumeration_Knob':
        if type(value) is not str or value not in knob.values():
            raise BridgeError('invalid_value', 'Use an available enumeration label')
    elif type(value) is not str:
        raise BridgeError('invalid_value', 'String knob requires text')
    return knob


def knob_value(knob):
    """Array_Knob.value() may collapse equal components to one scalar."""
    if knob.Class() in NUMERIC and knob.arraySize() > 1:
        return [knob.value(i) for i in range(knob.arraySize())]
    return knob.value()


def same_value(actual, expected):
    if isinstance(expected, (tuple, list)):
        return isinstance(actual, (tuple, list)) and len(actual) == len(expected) and all(
            same_value(a, b) for a, b in zip(actual, expected))
    if type(expected) in (int, float):
        return type(actual) in (int, float) and math.isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-7)
    return actual == expected


def preflight(nuke, operation):
    """Resolve one batch primitive without writing; snapshots are execution-local."""
    check_guard()
    node = resolve_node(nuke, operation['node_path'])
    kind = operation['op']
    if kind == 'set_knob':
        knob = inspect_knob(node, operation['knob'], operation['value'])
        return dict(node=node, knob=knob, before=knob_value(knob))
    if kind == 'position':
        if any(type(operation[k]) is not int for k in ('x', 'y')):
            raise BridgeError('invalid_value', 'Position requires integer x and y')
        return dict(node=node, before=[node.xpos(), node.ypos()])
    if kind == 'connect':
        index = operation['input_index']
        if type(index) is not int or not 0 <= index < node.maxInputs():
            raise BridgeError('invalid_input', 'Input index outside node range')
        source = resolve_node(nuke, operation['source_path']) if operation['source_path'] is not None else None
        if source is not None and (source.fullName().rpartition('.')[0] != node.fullName().rpartition('.')[0]):
            raise BridgeError('invalid_input', 'Connect nodes within the same Group scope')
        if not node.canSetInput(index, source):
            raise BridgeError('invalid_input', 'Node rejects the requested connection')
        old = node.input(index)
        return dict(node=node, source=source, before=old.fullName() if old else None)
    raise BridgeError('invalid_request', 'Unsupported edit operation')


def apply(nuke, operation):
    prepared = preflight(nuke, operation)
    node = prepared['node']
    path = node.fullName()
    data = dict(path=path, name=node.name(), before=prepared['before'])
    started = False
    try:
        check_guard()
        kind = operation['op']
        if kind == 'set_knob':
            knob, value = prepared['knob'], operation['value']
            if isinstance(value, (tuple, list)):
                data['completed_components'] = []
                for i, component in enumerate(value):
                    check_guard()
                    current = preflight(nuke, operation)
                    if current['node'] != node or current['knob'] != knob:
                        raise BridgeError('state_uncertain', 'Array target changed during edit')
                    started = True
                    knob.setValue(component, i)
                    data['completed_components'].append(i)
            else:
                started = True
                knob.setValue(value)
            actual = knob_value(knob)
            data.update(knob=operation['knob'], value=actual)
            verified = same_value(actual, value) and inspect_knob(node, operation['knob'], value) == knob
        elif kind == 'position':
            started = True
            node.setXYpos(operation['x'], operation['y'])
            data['position'] = [node.xpos(), node.ypos()]
            verified = data['position'] == [operation['x'], operation['y']]
        else:
            started = True
            node.setInput(operation['input_index'], prepared['source'])
            actual = node.input(operation['input_index'])
            data.update(input_index=operation['input_index'], source_path=actual.fullName() if actual else None)
            verified = actual == prepared['source']
        # A handle alone does not establish that the addressed node still owns the path.
        with nuke.root(): verified = verified and nuke.toNode(path) == node
        if not verified:
            raise BridgeError('state_uncertain', 'Edit readback did not match requested state', 'unknown', data)
        return data
    except BridgeError as exc:
        if started and exc.outcome == 'not_started':
            raise BridgeError(exc.code, str(exc), 'unknown', data) from exc
        raise
    except Exception as exc:
        raise BridgeError('state_uncertain', str(exc), 'unknown', data) from exc


def set_knob(nuke, node_path, knob, value):
    return apply(nuke, dict(op='set_knob', node_path=node_path, knob=knob, value=value))


def position_node(nuke, node_path, x, y):
    return apply(nuke, dict(op='position', node_path=node_path, x=x, y=y))


def connect_input(nuke, node_path, input_index, source_path):
    return apply(nuke, dict(op='connect', node_path=node_path, input_index=input_index, source_path=source_path))


def delete_owned(nuke, node):
    """Observe destruction of this exact handle; missing lookup is never proof."""
    observed = []
    def destroyed():
        if nuke.thisNode() == node: observed.append(True)
    nuke.addOnDestroy(destroyed)
    try:
        nuke.delete(node)
        if not observed: raise BridgeError('state_uncertain', 'No affirmative destruction receipt', 'unknown')
    finally:
        nuke.removeOnDestroy(destroyed)


def delete_node(nuke, node_path):
    node = resolve_node(nuke, node_path)
    data = dict(deleted=node.fullName(), type=node.Class())
    check_guard()
    try:
        delete_owned(nuke, node)
        return data
    except Exception as exc:
        raise BridgeError('state_uncertain', 'Deletion could not be verified: ' + str(exc), 'unknown', data) from exc


def create_node(nuke, node_type, name=None, position=None, inputs=None, parameters=None):
    main_thread()
    identifier(node_type)
    if name is not None: identifier(name)
    if parameters is None: parameters = {}
    if not isinstance(parameters, dict): raise BridgeError('invalid_request', 'parameters must be an object')
    for key, value in parameters.items(): parameter_syntax(key, value)
    if position is not None and (not isinstance(position, (tuple, list)) or len(position) != 2 or
                                any(type(v) is not int for v in position)):
        raise BridgeError('invalid_value', 'Position requires two integers')
    if inputs is not None and (not isinstance(inputs, list) or len(inputs) > 100):
        raise BridgeError('invalid_input', 'inputs must be a list of at most 100 paths or nulls')
    for path in inputs or []:
        if path is not None: resolve_node(nuke, path)
    try: constructor = getattr(nuke.nodes, node_type)
    except AttributeError as exc: raise BridgeError('node_class_unavailable', node_type) from exc
    if not callable(constructor): raise BridgeError('node_class_unavailable', node_type)
    if name:
        with nuke.root():
            if nuke.toNode(name) is not None: raise BridgeError('name_conflict', 'Requested name already exists')
    selected = list(nuke.selectedNodes())
    check_guard()
    node = None
    configuring = False
    result = None
    failure = None
    path = None
    try:
        kwargs = {}
        if name is not None: kwargs['name'] = name
        with nuke.root(): node = constructor(**kwargs)
        if node is None:
            raise BridgeError('state_uncertain', 'Creation returned no handle; do not retry or delete candidates', 'unknown')
        path = node.fullName()
        if name is not None and path != name:
            raise BridgeError('state_uncertain', 'Creation returned an unexpected identity', 'unknown', {'created_path': path})
        ops = [dict(op='set_knob', node_path='root.' + path, knob=k, value=v) for k, v in parameters.items()]
        if position is not None: ops.append(dict(op='position', node_path='root.' + path, x=position[0], y=position[1]))
        ops.extend(dict(op='connect', node_path='root.' + path, input_index=i, source_path=source)
                   for i, source in enumerate(inputs or []))
        for op in ops: preflight(nuke, op)
        configuring = True
        for op in ops: apply(nuke, op)
    except Exception as exc:
        data = dict(getattr(exc, 'data', {}), created_path=path)
        outcome = 'unknown'
        if node is not None and isinstance(exc, BridgeError) and exc.outcome == 'not_started' and not configuring:
            try:
                with nuke.root():
                    if nuke.toNode(path) != node: raise RuntimeError('Owned handle not observable')
                delete_owned(nuke, node)
                outcome = 'rolled_back'
                node = None
            except Exception as cleanup:
                outcome = 'partial'
                data['cleanup_error'] = str(cleanup)
        failure = BridgeError(getattr(exc, 'code', 'state_uncertain'), str(exc), outcome, data)
    finally:
        try:
            if node is not None: node.setSelected(False)
            for original in selected: original.setSelected(True)
            if any(not original.isSelected() for original in selected): raise RuntimeError('Selection restoration not verified')
            if node is not None and node.isSelected(): raise RuntimeError('Created node remains selected')
        except Exception as exc:
            data = dict(failure.data if failure else {}, created_path=path, selection_error=str(exc))
            if failure:
                data['prior_error'] = dict(code=failure.code, message=str(failure), outcome=failure.outcome)
            failure = BridgeError('state_uncertain', 'Selection restoration failed: ' + str(exc), 'unknown', data)
    if failure: raise failure
    # Selection and dependent-knob callbacks can invalidate earlier readbacks.
    data = {'created_path': path}
    try:
        result = dict(name=node.name(), path=path, type=node.Class(), position=[node.xpos(), node.ypos()],
                      parameters={key: knob_value(node.knob(key)) for key in parameters})
        data.update(result)
        with nuke.root():
            if nuke.toNode(path) != node:
                raise RuntimeError('Created node is not observable')
        for key, value in parameters.items():
            inspect_knob(node, key, value)
            if not same_value(result['parameters'][key], value):
                raise RuntimeError('Created parameter changed during callbacks: ' + key)
        if position is not None and result['position'] != list(position):
            raise RuntimeError('Created position changed during callbacks')
        # nuke.nodes constructors do not use selection to wire inputs.
        expected_inputs = inputs or []
        for i in range(max(node.inputs(), len(expected_inputs))):
            actual = node.input(i)
            expected = resolve_node(nuke, expected_inputs[i]) if i < len(expected_inputs) and expected_inputs[i] else None
            if actual != expected: raise RuntimeError('Unexpected created input')
    except Exception as exc:
        raise BridgeError('state_uncertain', 'Final creation verification failed: ' + str(exc), 'unknown', data) from exc
    return result
