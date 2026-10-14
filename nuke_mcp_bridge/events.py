"""Bounded observed callbacks, polling, and optimistic scene revision checks."""
from collections import deque
from contextvars import ContextVar
from copy import deepcopy
import threading
import time
from uuid import uuid4

from .mutations import main_thread, operation_context
from .protocol import BridgeError

EVENT_TYPES = frozenset(('node_created', 'node_deleted', 'knob_changed',
                         'script_loaded', 'script_saved', 'script_closed', 'frame_changed'))
scene_events = ContextVar('nuke_scene_events', default=None)


def validate_types(event_types):
    if event_types is None:
        return None
    if (not isinstance(event_types, list) or len(event_types) > len(EVENT_TYPES) or
            any(not isinstance(t, str) or t not in EVENT_TYPES for t in event_types)):
        raise BridgeError('invalid_request', 'event_types must contain supported event names')
    return sorted(set(event_types))


class EventBuffer:
    def __init__(self, capacity=1000, clock=time.monotonic, instance_id=None):
        if type(capacity) is not int or not 1 <= capacity <= 1000:
            raise ValueError('Event capacity must be 1..1000')
        self.capacity, self.clock = capacity, clock
        self.instance_id = instance_id or str(uuid4())
        self._events = deque()
        self._lock = threading.RLock()
        self._sequence = self._revision = self._dropped_through = 0
        self._script_generation = 0
        self._origin = None
        self._origin_start = 0
        self._installed = False
        self._reasons = []
        self.supported_callbacks = []

    def degrade(self, reason):
        with self._lock:
            if reason not in self._reasons and len(self._reasons) < 8:
                self._reasons.append(reason)

    def snapshot(self):
        with self._lock:
            return dict(server_instance_id=self.instance_id, revision=self._revision,
                        script_generation=self._script_generation,
                        revision_available=self._installed and not self._reasons,
                        reasons=list(self._reasons) if self._installed else ['callbacks_not_installed'])

    def revision(self):
        with self._lock:
            return self._revision

    def require_revision(self):
        with self._lock:
            if not self.snapshot()['revision_available']:
                raise BridgeError('revision_unavailable', 'Scene callback coverage cannot support a revision check',
                                  data=self.snapshot())
            return self._revision

    def check(self, expected, allow_owned=False, require_available=True):
        if type(expected) is not int or expected < 0:
            raise BridgeError('invalid_request', 'expected_revision must be a nonnegative integer')
        with self._lock:
            if require_available:
                self.require_revision()
            if expected == self._revision:
                return
            origin = (operation_context.get() or {}).get('request_id')
            # Only a contiguous streak from this request is allowed after its initial check.
            # Unattributed callbacks never count as owned, including outside runtime dispatch.
            if (allow_owned and origin and origin == self._origin and
                    self._origin_start <= expected < self._revision):
                return
            raise BridgeError('revision_conflict', 'Observed scene revision changed', data=self.snapshot())

    def record(self, event):
        kind = event.get('type')
        if kind not in EVENT_TYPES:
            raise BridgeError('invalid_request', 'Unsupported event type')
        with self._lock:
            now = self.clock()
            origin = (operation_context.get() or {}).get('request_id')
            if origin != self._origin:
                self._origin, self._origin_start = origin, self._revision
            self._revision += 1  # Never coalesce away a revision change.
            self._sequence += 1
            if kind in ('script_loaded', 'script_closed'):
                self._script_generation += 1
            item = dict(type=kind, sequence=self._sequence, first_sequence=self._sequence,
                        revision=self._revision, timestamp=now, first_timestamp=now, count=1,
                        server_instance_id=self.instance_id, request_id=origin)
            # No knob values, callback code, or arbitrary incoming payloads in the ring.
            for key in ('node_path', 'knob'):
                value = event.get(key)
                if isinstance(value, str):
                    item[key] = value[:1024]
                    if len(value) > 1024:
                        self.degrade('event_identity_truncated')
            if kind == 'frame_changed' and type(event.get('frame')) in (int, float):
                item['frame'] = event['frame']
            last = self._events[-1] if self._events else None
            if (kind == 'knob_changed' and last and last['type'] == kind and
                    all(last.get(k) == item.get(k) for k in ('node_path', 'knob', 'request_id')) and
                    now - last['first_timestamp'] < .1):
                item.update(first_sequence=last['first_sequence'], first_timestamp=last['first_timestamp'],
                            count=last['count'] + 1)
                self._events[-1] = item
            else:
                if len(self._events) == self.capacity:
                    self._dropped_through = self._events.popleft()['sequence']
                self._events.append(item)

    def read(self, after_sequence=0, limit=100, event_types=None):
        if type(after_sequence) is not int or after_sequence < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise BridgeError('invalid_request', 'Use a nonnegative cursor and limit 1..500')
        event_types = validate_types(event_types)
        with self._lock:
            if after_sequence > self._sequence:
                raise BridgeError('invalid_cursor', 'Cursor is ahead of this instance; check server_instance_id')
            selected, cursor = [], max(after_sequence, self._dropped_through)
            for event in self._events:
                if event['sequence'] <= after_sequence:
                    continue
                cursor = event['sequence']
                if event_types is None or event['type'] in event_types:
                    selected.append(deepcopy(event))
                    if len(selected) == limit:
                        break
            return dict(self.snapshot(), events=selected, next_sequence=cursor,
                        latest_sequence=self._sequence, history_gap=after_sequence < self._dropped_through,
                        event_types=event_types, frame_observation='sampled',
                        supported_callbacks=list(self.supported_callbacks))


def plan_stamp():
    buffer = scene_events.get()
    return buffer.snapshot() if buffer else None


def check_plan_stamp(stamp, allow_owned=False):
    buffer = scene_events.get()
    if stamp is None:
        if buffer is not None:
            raise BridgeError('stale_plan', 'Event provider changed')
        return
    if buffer is None or buffer.instance_id != stamp['server_instance_id']:
        raise BridgeError('stale_plan', 'Event provider instance changed')
    current = buffer.snapshot()
    if (current['revision_available'] != stamp['revision_available'] or
            current['reasons'] != stamp['reasons']):
        raise BridgeError('revision_unavailable', 'Event observation changed after planning')
    buffer.check(stamp['revision'], allow_owned=allow_owned,
                 require_available=stamp['revision_available'])


def install_callbacks(nuke, buffer):
    """Install once on the main thread. Callbacks read only their context and frame."""
    main_thread()
    attr = '_nuke_mcp_event_registration'
    existing = getattr(nuke, attr, None)
    if existing:
        if existing['buffer'] is buffer:
            return existing['cleanup']
        raise BridgeError('callbacks_in_use', 'Another bridge owns the host event callbacks')
    installed, state = [], {'active': True, 'busy': False, 'frame': None}
    env = getattr(nuke, 'env', {})
    nc = env.get('nc', 'unknown')
    if nc == 'unknown':
        nc = env.get('noncommercial', 'unknown')
    if nc is not False:
        buffer.degrade('noncommercial_or_unknown_observation')
    if getattr(nuke, 'NUKE_VERSION_MAJOR', 0) < 17:
        buffer.degrade('unqualified_callback_coverage')

    def callback(kind):
        def observe():
            if not state['active']:
                return
            if threading.current_thread() is not threading.main_thread():
                buffer.degrade('callback_off_main_thread')
                buffer.record({'type': kind})
                return
            if state['busy']:
                buffer.degrade('recursive_callback')
                return
            state['busy'] = True
            try:
                if kind == 'frame_changed':
                    frame = nuke.frame()
                    if frame == state['frame']:
                        return
                    state['frame'] = frame
                    buffer.record(dict(type=kind, frame=frame))
                    return
                item = {'type': kind}
                node = nuke.thisNode()
                if node is None:
                    buffer.degrade('callback_identity_unavailable')
                else:
                    item['node_path'] = node.fullName()
                if kind == 'knob_changed':
                    item['knob'] = nuke.thisKnob().name()
                    if item['knob'] == 'showPanel':
                        return  # Panel opening is not a scene edit.
                buffer.record(item)
            except Exception:
                # No errors/logging escape into artist callbacks; fail closed on guarantees.
                buffer.degrade('callback_read_failed')
                buffer.record({'type': kind})
            finally:
                state['busy'] = False
        return observe

    def cleanup():
        main_thread()
        state['active'] = False
        buffer.degrade('callbacks_stopped')
        for remove, fn, kwargs in installed[:]:
            try:
                remove(fn, **kwargs)
                installed.remove((remove, fn, kwargs))
            except Exception:
                buffer.degrade('callback_removal_failed')
        if not installed and getattr(nuke, attr, None) is registration:
            delattr(nuke, attr)

    registration = dict(buffer=buffer, cleanup=cleanup)
    cleanup.sample_frame = callback('frame_changed')
    setattr(nuke, attr, registration)
    for suffix, kind in (('OnCreate','node_created'), ('OnDestroy','node_deleted'),
                         ('KnobChanged','knob_changed'), ('OnScriptLoad','script_loaded'),
                         ('OnScriptSave','script_saved'), ('OnScriptClose','script_closed'),
                         ('UpdateUI','frame_changed')):
        add, remove = getattr(nuke, 'add'+suffix, None), getattr(nuke, 'remove'+suffix, None)
        if not callable(add) or not callable(remove):
            buffer.degrade('callback_missing_'+suffix)
            continue
        fn = callback(kind)
        kwargs = {'nodeClass':'Root'} if suffix == 'UpdateUI' else {}
        try:
            if suffix == 'UpdateUI':
                state['frame'] = nuke.frame()
            # Track before calling add, so partial registration can still be removed.
            installed.append((remove, fn, kwargs))
            add(fn, **kwargs)
            buffer.supported_callbacks.append(kind)
        except Exception:
            buffer.degrade('callback_install_failed_'+suffix)
    buffer._installed = True
    return cleanup
