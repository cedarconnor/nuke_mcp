"""Bounded loopback server; socket threads never call the Nuke API."""

import socket
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager

from . import __version__
from .protocol import (APPLICATION, PROTOCOL_VERSION, BridgeError, FrameDecoder,
                       encode_message, validate_uuid)


class QtDispatcher:
    def __init__(self):
        self.timer = None

    def start(self, tick):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Start the bridge on Nuke's main thread")
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            from PySide2.QtCore import QTimer
        self.timer = QTimer()
        self.timer.setInterval(16)
        self.timer.timeout.connect(tick)
        self.timer.start()

    def stop(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer.timeout.disconnect()
            self.timer.deleteLater()
            self.timer = None


class BridgeRuntime:
    def __init__(self, handlers, registry, host_dispatcher, event_host=None):
        self.handlers = handlers
        self.registry = registry
        self.dispatcher = host_dispatcher
        self.port = None
        self._server = None
        self._accept_thread = None
        self._clients = {}
        self._sessions = set()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        from .events import EventBuffer
        self.events = EventBuffer(instance_id=registry.instance_id)
        self.event_host = event_host
        self._event_cleanup = None
        self._event_filters = OrderedDict()
        self._subscription_connections = {}

    def start(self, host="127.0.0.1", port=9877):
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise BridgeError("invalid_host", "Only loopback listeners are supported")
        if self._server is not None:
            return
        family = socket.AF_INET6 if host == "::1" else socket.AF_INET
        server = socket.socket(family, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            server.bind(("127.0.0.1" if host == "localhost" else host, port))
            server.listen(8)
            server.settimeout(.1)
            self.port = server.getsockname()[1]
            if self.event_host is not None:
                from .events import install_callbacks
                self._event_cleanup = install_callbacks(self.event_host, self.events)
            self.dispatcher.start(self.tick)
        except Exception:
            if self._event_cleanup:
                self._event_cleanup()
            server.close()
            raise
        self._server = server
        self._stop.clear()
        self._accept_thread = threading.Thread(target=self._accept, name="NukeMCP-accept", daemon=True)
        self._accept_thread.start()

    def tick(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Host queue must run on the main thread")
        if self._event_cleanup:
            self._event_cleanup.sample_frame()
        self.registry.tick(self._dispatch)

    def _dispatch(self, request):
        command = request["command"]
        if command == "ping":
            return {"pong": True}
        handler = self.handlers.get(command)
        if command == 'subscribe_events':
            handler = lambda event_types: self._subscribe(request, event_types)
        elif command == 'get_events':
            with self._lock:
                event_types = self._event_filters.get(request['client_session_id'])
            handler = lambda after_sequence=0, limit=100: self.events.read(after_sequence, limit, event_types)
        if handler is None:
            raise BridgeError("unknown_command", "Unsupported command: " + command)
        with self._request_scope(request):
            result = handler(**request['params'])
        if isinstance(result, Iterator):
            return self._contextual_job(request, result)
        return result

    def _subscribe(self, request, event_types):
        from .events import validate_types
        event_types = validate_types(event_types)
        session = request['client_session_id']
        with self._lock:
            connection = self._subscription_connections.pop(request['request_id'], None)
            if connection is None or connection[0] not in self._clients or connection[1] != session:
                raise BridgeError('session_disconnected', 'Subscription connection has closed; subscribe on the new connection')
            self._event_filters[session] = event_types
        return dict(self.events.snapshot(), event_types=event_types, delivery='polling')

    @contextmanager
    def _request_scope(self, request):
        from .mutations import operation_guard, operation_context
        from .events import scene_events
        token = operation_guard.set(lambda: self.registry.check_edit_boundary(request['request_id']))
        context_token = operation_context.set({'server_instance_id':self.registry.instance_id,
                                               'request_id':request['request_id'],
                                               'client_session_id':request['client_session_id']})
        event_token = scene_events.set(self.events)
        try:
            yield
        finally:
            scene_events.reset(event_token)
            operation_context.reset(context_token)
            operation_guard.reset(token)

    def _contextual_job(self, request, job):
        try:
            while True:
                with self._request_scope(request):
                    try:
                        progress = next(job)
                    except StopIteration as done:
                        return done.value
                yield progress
        finally:
            with self._request_scope(request):
                job.close()

    @staticmethod
    def _send(sock, message):
        sock.sendall(encode_message(message))

    def _accept(self):
        while not self._stop.is_set():
            try:
                sock, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.settimeout(2)
            with self._lock:
                if len(self._clients) >= 8:
                    try:
                        # Drain the small hello before close: unread incoming bytes
                        # cause Windows to reset the connection and discard our error.
                        sock.settimeout(.2)
                        sock.recv(65536)
                        self._send(sock, {"type": "error", "error": {
                            "code": "busy", "message": "Eight clients already connected"}})
                    except OSError:
                        pass
                    sock.close()
                    continue
                worker = threading.Thread(target=self._serve, args=(sock,), daemon=True,
                                          name="NukeMCP-client")
                self._clients[sock] = worker
                worker.start()

    def _serve(self, sock):
        decoder = FrameDecoder()
        session = None
        try:
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    if session is None:
                        break
                    continue
                if not chunk:
                    break
                for message in decoder.feed(chunk):
                    if session is None:
                        if (message.get("type") != "hello" or
                                message.get("application") != APPLICATION or
                                type(message.get("protocol_version")) is not int or
                                message.get("protocol_version") != PROTOCOL_VERSION):
                            raise BridgeError("protocol_mismatch", "Nuke MCP requires coordinated protocol v2")
                        candidate = validate_uuid(message.get("client_session_id"))
                        with self._lock:
                            if candidate in self._sessions:
                                raise BridgeError("session_in_use", "This client session is already connected")
                            self._sessions.add(candidate)
                        session = candidate
                        self._send(sock, dict(type="hello", application=APPLICATION,
                                              protocol_version=PROTOCOL_VERSION,
                                              server_instance_id=self.registry.instance_id,
                                              addon_version=__version__,
                                              client_session_id=session))
                    else:
                        self._handle(sock, session, message)
        except (BridgeError, OSError) as exc:
            if isinstance(exc, BridgeError):
                try:
                    self._send(sock, {"type": "error", "error": {"code": exc.code, "message": str(exc)}})
                except (OSError, BridgeError):
                    pass
        finally:
            sock.close()
            with self._lock:
                self._clients.pop(sock, None)
                if session:
                    self._sessions.discard(session)
                    self._event_filters.pop(session, None)

    def _handle(self, sock, session, message):
        kind = message.get("type")
        if kind == "request":
            request = message.get("request")
            if not isinstance(request, dict) or request.get("client_session_id") != session:
                raise BridgeError("invalid_request", "Request session does not match connection")
            message_id = validate_uuid(request.get("request_id"))
            with self._lock:
                # Keep metadata only for admitted nonterminal subscription requests (queue <=64).
                for key in list(self._subscription_connections):
                    if self.registry.lookup(key, self.registry.instance_id)['state'] not in ('queued', 'running'):
                        self._subscription_connections.pop(key, None)
                result = self.registry.admit(request)
                if request.get('command') == 'subscribe_events' and result['state'] == 'queued':
                    # A duplicate admission must retain the original connection, even after reconnect.
                    self._subscription_connections.setdefault(message_id, (sock, session))
        elif kind in ("status", "cancel"):
            message_id = validate_uuid(message.get("message_id"))
            request_id = validate_uuid(message.get("request_id"))
            instance = validate_uuid(message.get("server_instance_id"))
            result = self.registry.lookup(request_id, instance)
            if kind == "cancel" and result["server_instance_id"] == self.registry.instance_id:
                if result["client_session_id"] not in (None, session):
                    raise BridgeError("session_mismatch", "Only the owning session may cancel work")
                result = self.registry.cancel(request_id)
        elif kind == "heartbeat":
            message_id = validate_uuid(message.get("message_id"))
            self._send(sock, {"type": "reply", "message_id": message_id,
                              "result": {"pong": True, "server_instance_id": self.registry.instance_id}})
            return
        else:
            raise BridgeError("invalid_request", "Unknown wire message")
        self._send(sock, {"type": "reply", "message_id": message_id, "result": result})

    def stop(self):
        self.registry.shutdown()
        # Must be called on the host main thread. Finish generator cleanup there.
        if threading.current_thread() is threading.main_thread():
            self.registry.tick(self._dispatch)
        if self._event_cleanup:
            self._event_cleanup()
        self.dispatcher.stop()
        self._stop.set()
        server, self._server = self._server, None
        if server:
            server.close()
        with self._lock:
            clients = list(self._clients.items())
            self._event_filters.clear()
            self._subscription_connections.clear()
        for sock, _ in clients:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        for _, thread in clients:
            if thread is not threading.current_thread():
                thread.join(2)
        if self._accept_thread:
            self._accept_thread.join(2)
            self._accept_thread = None
