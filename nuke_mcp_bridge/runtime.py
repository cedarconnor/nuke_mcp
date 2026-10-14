"""Bounded loopback server; socket threads never call the Nuke API."""

import socket
import threading

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
    def __init__(self, handlers, registry, host_dispatcher):
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
            self.dispatcher.start(self.tick)
        except Exception:
            server.close()
            raise
        self._server = server
        self._stop.clear()
        self._accept_thread = threading.Thread(target=self._accept, name="NukeMCP-accept", daemon=True)
        self._accept_thread.start()

    def tick(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Host queue must run on the main thread")
        self.registry.tick(self._dispatch)

    def _dispatch(self, request):
        command = request["command"]
        if command == "ping":
            return {"pong": True}
        handler = self.handlers.get(command)
        if handler is None:
            raise BridgeError("unknown_command", "Unsupported command: " + command)
        from .mutations import operation_guard, operation_context
        token = operation_guard.set(lambda: self.registry.check_edit_boundary(request['request_id']))
        context_token = operation_context.set({'server_instance_id':self.registry.instance_id,
                                               'request_id':request['request_id']})
        try:
            return handler(**request["params"])
        finally:
            operation_context.reset(context_token)
            operation_guard.reset(token)

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

    def _handle(self, sock, session, message):
        kind = message.get("type")
        if kind == "request":
            request = message.get("request")
            if not isinstance(request, dict) or request.get("client_session_id") != session:
                raise BridgeError("invalid_request", "Request session does not match connection")
            message_id = validate_uuid(request.get("request_id"))
            result = self.registry.admit(request)
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
        self.dispatcher.stop()
        self._stop.set()
        server, self._server = self._server, None
        if server:
            server.close()
        with self._lock:
            clients = list(self._clients.items())
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
