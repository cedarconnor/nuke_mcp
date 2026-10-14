"""External client with correlated acknowledgements and explicit polling."""

import socket
import threading
import time
from uuid import uuid4

from .protocol import (APPLICATION, PROTOCOL_VERSION, BridgeError, FrameDecoder,
                       TERMINAL_STATES, encode_message, make_result, validate_uuid)


class BridgeClient:
    def __init__(self, host="127.0.0.1", port=9877):
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise BridgeError("invalid_host", "Only loopback hosts are supported")
        self.host, self.port = host, port
        self.session_id = str(uuid4())
        self.instance_id = None
        self.sock = None
        self._lock = threading.RLock()
        self._decoder = FrameDecoder()
        self._messages = []

    def _receive(self):
        while not self._messages:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise BridgeError("connection_lost", "Host closed connection", "unknown")
            self._messages.extend(self._decoder.feed(chunk))
        message = self._messages.pop(0)
        if message.get("type") == "error":
            error = message.get("error", {})
            raise BridgeError(error.get("code", "protocol_error"), error.get("message", "Host error"))
        return message

    def connect(self):
        with self._lock:
            self.close()
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=2)
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sock.sendall(encode_message(dict(type="hello", application=APPLICATION,
                                                     protocol_version=PROTOCOL_VERSION,
                                                     client_session_id=self.session_id)))
                hello = self._receive()
                if (hello.get("type") != "hello" or hello.get("application") != APPLICATION or
                        hello.get("protocol_version") != PROTOCOL_VERSION or
                        hello.get("client_session_id") != self.session_id):
                    raise BridgeError("protocol_mismatch", "Not a compatible Nuke MCP v2 add-on")
                self.instance_id = validate_uuid(hello.get("server_instance_id"))
                return hello
            except Exception:
                self.close()
                raise

    def _ensure(self):
        if self.sock is None:
            previous = self.instance_id
            self.connect()
            if previous is not None and previous != self.instance_id:
                raise BridgeError("instance_changed", "Host restarted; verify state before new work", "unknown")

    def _exchange(self, message, timeout=2):
        with self._lock:
            try:
                self._ensure()
                self.sock.settimeout(max(.001, timeout))
                self.sock.sendall(encode_message(message))
                reply = self._receive()
                expected = (message["request"]["request_id"] if message["type"] == "request"
                            else message["message_id"])
                if reply.get("type") != "reply" or reply.get("message_id") != expected:
                    raise BridgeError("response_mismatch", "Uncorrelated response; connection closed", "unknown")
                result = reply.get("result")
                target = message["request"] if message["type"] == "request" else message
                if (not isinstance(result, dict) or
                        any(result.get(k) != target[k] for k in ("request_id", "server_instance_id")) or
                        (message["type"] == "request" and result.get("client_session_id") != self.session_id)):
                    raise BridgeError("response_mismatch", "Receipt identity does not match request", "unknown")
                return result
            except Exception:
                self.close()
                raise

    def submit(self, command, params, timeout_ms=30000):
        identity = dict(request_id=str(uuid4()), client_session_id=self.session_id,
                        server_instance_id=self.instance_id)
        try:
            with self._lock:
                self._ensure()
                identity["server_instance_id"] = self.instance_id
                req = dict(identity, protocol_version=PROTOCOL_VERSION,
                           command=command, params=params, timeout_ms=timeout_ms)
                return self._exchange({"type": "request", "request": req},
                                      timeout=min(2, timeout_ms / 1000))
        except Exception as exc:
            return self._transport_failure(identity, exc)

    @staticmethod
    def _transport_failure(identity, exc):
        result = make_result(identity, state="failed", outcome="unknown",
                             error={"code": getattr(exc, "code", "transport_error"),
                                    "message": str(exc)})
        result["transport_error"] = True  # Not a host-issued receipt.
        return result

    def call(self, command, params, timeout_ms=30000):
        deadline = time.monotonic() + timeout_ms / 1000
        result = self.submit(command, params, timeout_ms)
        while result["state"] not in TERMINAL_STATES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._transport_failure(result, BridgeError(
                    "wait_timeout", "Host may still run; query operation status; do not replay", "unknown"))
            time.sleep(min(.02, remaining))
            result = self.status(result["request_id"], result["server_instance_id"],
                                 timeout=min(2, max(.001, deadline - time.monotonic())))
        return result

    def status(self, request_id, instance_id, timeout=2):
        return self._control("status", request_id, instance_id, timeout)

    def cancel(self, request_id, instance_id):
        return self._control("cancel", request_id, instance_id, 2)

    def _control(self, kind, request_id, instance_id, timeout):
        try:
            return self._exchange(dict(type=kind, message_id=str(uuid4()), request_id=request_id,
                                       server_instance_id=instance_id), timeout)
        except Exception as exc:
            return self._transport_failure(dict(request_id=request_id, server_instance_id=instance_id,
                                                client_session_id=self.session_id), exc)

    def close(self):
        with self._lock:
            if self.sock is not None:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.sock.close()
                self.sock = None
            self._decoder = FrameDecoder()
            self._messages = []
