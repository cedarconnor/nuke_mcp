"""Thread-safe request ledger. Only tick() executes host work."""

from collections import OrderedDict, deque
from collections.abc import Iterator
from copy import deepcopy
import hashlib
import json
import threading
import time
from uuid import uuid4

from .protocol import BridgeError, TERMINAL_STATES, encode_message, make_result, validate_request

READ_ONLY = frozenset(("ping", "get_capabilities", "get_script_info", "get_node_info"))


class OperationRegistry:
    def __init__(self, clock=time.monotonic, instance_id=None, max_receipts=4096):
        self.clock = clock
        self.instance_id = instance_id or str(uuid4())
        self.max_receipts = max_receipts
        self._lock = threading.RLock()
        self._entries = OrderedDict()
        self._queue = deque()
        self._active = None
        self._ticking = False
        self._stopping = False

    def _error(self, request, code, message, outcome="not_started"):
        return make_result(request, state="failed", outcome=outcome,
                           error={"code": code, "message": message})

    def _prune(self):
        now = self.clock()
        for key, entry in list(self._entries.items()):
            if entry["ended"] is not None and now - entry["ended"] >= 1800:
                del self._entries[key]
        # Cancelled/expired queue entries must not consume queue memory indefinitely.
        self._queue = deque(key for key in self._queue
                            if key in self._entries and
                            self._entries[key]["result"]["state"] == "queued")

    def admit(self, request):
        request = deepcopy(request)
        try:
            validate_request(request)
        except BridgeError as exc:
            return self._error(request, exc.code, str(exc))
        with self._lock:
            self._prune()
            if request["server_instance_id"] != self.instance_id:
                return self._error(request, "instance_changed", "Reconnect to the current instance")
            key = request["request_id"]
            digest = hashlib.sha256(json.dumps(request, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
            if key in self._entries:
                entry = self._entries[key]
                if digest != entry["digest"]:
                    return self._error(request, "request_conflict", "Request ID reused with different payload")
                return deepcopy(entry["result"])
            if self._stopping:
                return self._error(request, "stopping", "Host runtime is stopping")
            active = [e for e in self._entries.values()
                      if e["result"]["state"] not in TERMINAL_STATES]
            if (len(self._queue) >= 64 or
                    any(e["request"]["client_session_id"] == request["client_session_id"]
                        for e in active)):
                return self._error(request, "busy", "Session or host queue is busy")
            if len(self._entries) >= self.max_receipts:
                terminal = next((k for k, e in self._entries.items() if e["ended"] is not None), None)
                if terminal is None:
                    return self._error(request, "busy", "Receipt ledger is full of active work")
                del self._entries[terminal]
            result = make_result(request, state="queued")
            self._entries[key] = dict(request=request, digest=digest, result=result,
                                      deadline=self.clock() + request["timeout_ms"] / 1000,
                                      ended=None, cancel=False, job=None)
            self._queue.append(key)
            return deepcopy(result)

    def lookup(self, request_id, instance_id):
        with self._lock:
            self._prune()
            identity = dict(request_id=request_id, server_instance_id=instance_id,
                            client_session_id=None)
            if instance_id != self.instance_id:
                return self._error(identity, "instance_changed", "Original host instance no longer exists", "unknown")
            if request_id not in self._entries:
                return self._error(identity, "receipt_expired_or_unknown",
                                   "No retained receipt; do not replay a mutation", "unknown")
            return deepcopy(self._entries[request_id]["result"])

    def cancel(self, request_id):
        with self._lock:
            entry = self._entries.get(request_id)
            if entry is None:
                return self.lookup(request_id, self.instance_id)
            entry["cancel"] = True
            if entry["result"]["state"] == "queued":
                self.record_result(request_id, make_result(
                    entry["request"], state="cancelled",
                    error={"code": "cancelled", "message": "Cancelled before dispatch"}))
            elif entry["result"]["state"] == "running":
                entry["result"]["warnings"] = ["Cancellation requested; current host call may still run"]
            return deepcopy(entry["result"])

    def record_result(self, request_id, result):
        # This method records evidence only. No Nuke API is touched here.
        with self._lock:
            entry = self._entries[request_id]
            if entry["result"]["state"] in TERMINAL_STATES:
                return
            try:
                encode_message(result)
            except BridgeError as exc:
                result = self._error(entry["request"], exc.code,
                                     "Host result could not be serialized", "unknown")
            entry["result"] = deepcopy(result)
            if result["state"] in TERMINAL_STATES:
                entry["ended"] = self.clock()

    def tick(self, dispatch):
        with self._lock:
            if self._ticking:  # Includes nested Qt event loops during a native render.
                return
            self._ticking = True
        try:
            self._tick(dispatch)
        finally:
            with self._lock:
                self._ticking = False

    def _tick(self, dispatch):
        with self._lock:
            self._prune()
            if self._active is None:
                while self._queue:
                    key = self._queue.popleft()
                    entry = self._entries.get(key)
                    if not entry or entry["result"]["state"] != "queued":
                        continue
                    if self.clock() >= entry["deadline"] or self._stopping:
                        self.record_result(key, make_result(
                            entry["request"], state="expired",
                            error={"code": "deadline_expired", "message": "Expired before dispatch"}))
                        continue
                    self._active = key
                    entry["result"] = make_result(entry["request"], state="running",
                                                  outcome="unknown")
                    break
            if self._active is None:
                return
            key = self._active
            entry = self._entries[key]
            req = entry["request"]
            job = entry["job"]
            cancel = entry["cancel"] or self._stopping
            expired = self.clock() >= entry["deadline"]
        try:
            if job is not None:
                if cancel or expired:
                    job.close()  # Host cleanup is on the same main thread as tick.
                    result = make_result(req, state="cancelled" if cancel else "expired",
                                         outcome="partial" if entry["result"]["data"] else "unknown",
                                         data=entry["result"]["data"],
                                         error={"code": "cancelled" if cancel else "deadline_expired",
                                                "message": "Stopped between host steps"})
                else:
                    try:
                        progress = next(job)
                    except StopIteration as done:
                        result = make_result(req, outcome="applied",
                                             data=done.value or entry["result"]["data"])
                    else:
                        self.record_result(key, make_result(req, state="running", outcome="partial",
                                                           data=progress or {}))
                        return
            else:
                # Repeat the deadline/lifecycle check at the actual dispatch boundary.
                with self._lock:
                    if entry["cancel"] or self._stopping or self.clock() >= entry["deadline"]:
                        result = make_result(req, state="expired", error={
                            "code": "deadline_expired", "message": "Stopped before dispatch"})
                        self.record_result(key, result)
                        self._active = None
                        return
                data = dispatch(deepcopy(req))
                if isinstance(data, Iterator):
                    with self._lock:
                        entry["job"] = data
                    return
                result = make_result(req, data=data,
                                     outcome="not_started" if req["command"] in READ_ONLY else "applied")
            self.record_result(key, result)
        except Exception as exc:
            outcome = exc.outcome if isinstance(exc, BridgeError) else "unknown"
            self.record_result(key, make_result(
                req, state="failed", outcome=outcome,
                data=exc.data if isinstance(exc, BridgeError) else entry["result"]["data"],
                error={"code": exc.code if isinstance(exc, BridgeError) else "host_error",
                       "message": str(exc)}))
        finally:
            with self._lock:
                if entry["result"]["state"] in TERMINAL_STATES:
                    self._active = None

    def shutdown(self):
        with self._lock:
            self._stopping = True
            for key, entry in self._entries.items():
                if entry["result"]["state"] not in TERMINAL_STATES:
                    self.cancel(key)
