"""Versioned, bounded newline-delimited JSON wire protocol."""

import json
from typing import Any, TypedDict
from uuid import UUID

PROTOCOL_VERSION = 2
APPLICATION = "nuke-mcp"
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
TERMINAL_STATES = frozenset(("completed", "failed", "cancelled", "expired"))


class Request(TypedDict):
    protocol_version: int
    request_id: str
    client_session_id: str
    server_instance_id: str
    command: str
    params: dict[str, Any]
    timeout_ms: int


class Result(TypedDict):
    request_id: str
    client_session_id: str
    server_instance_id: str
    ok: bool
    state: str
    outcome: str
    data: dict[str, Any]
    error: dict | None
    warnings: list
    observation: dict
    revision: int | None


class BridgeError(Exception):
    def __init__(self, code, message, outcome="not_started", data=None):
        super().__init__(message)
        self.code = code
        self.outcome = outcome
        self.data = data or {}


def encode_message(message: dict) -> bytes:
    try:
        wire = json.dumps(message, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise BridgeError("invalid_json", str(exc)) from exc
    if len(wire) > MAX_MESSAGE_BYTES:
        raise BridgeError("message_too_large", "Maximum JSON message is 8 MiB")
    return wire + b"\n"


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-finite JSON number: " + value)


class FrameDecoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[dict]:
        messages = []
        # Bound each frame, not the sum of coalesced valid frames.
        offset = 0
        while offset < len(chunk):
            end = chunk.find(b"\n", offset)
            stop = len(chunk) if end < 0 else end
            if len(self.buffer) + stop - offset > MAX_MESSAGE_BYTES:
                self.buffer.clear()
                raise BridgeError("message_too_large", "Maximum JSON message is 8 MiB")
            self.buffer.extend(chunk[offset:stop])
            if end < 0:
                break
            raw = bytes(self.buffer)
            self.buffer.clear()
            try:
                message = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                                     parse_constant=_invalid_constant)
                if not isinstance(message, dict):
                    raise ValueError("Message must be an object")
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise BridgeError("invalid_json", str(exc)) from exc
            messages.append(message)
            offset = end + 1
        return messages


def validate_uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError("UUID must use canonical lowercase form")
    except (ValueError, AttributeError) as exc:
        raise BridgeError("invalid_request", "Invalid UUID") from exc
    return value


def validate_request(message: dict) -> Request:
    expected = set(Request.__annotations__)
    if set(message) != expected:
        raise BridgeError("invalid_request", "Unexpected or missing request fields")
    if type(message["protocol_version"]) is not int or message["protocol_version"] != 2:
        raise BridgeError("protocol_mismatch", "Upgrade client and add-on together to v2")
    for key in ("request_id", "client_session_id", "server_instance_id"):
        validate_uuid(message[key])
    if (not isinstance(message["command"], str) or
            not 1 <= len(message["command"]) <= 128 or
            not isinstance(message["params"], dict)):
        raise BridgeError("invalid_request", "Invalid command or params")
    if type(message["timeout_ms"]) is not int or not 1 <= message["timeout_ms"] <= 300000:
        raise BridgeError("invalid_request", "timeout_ms must be 1..300000")
    encode_message(message)  # Includes nested finite-number and size validation.
    return message


def make_result(request, *, state="completed", outcome="not_started", data=None,
                error=None, warnings=None, observation=None, revision=None) -> Result:
    return dict(
        **{key: request.get(key) for key in
           ("request_id", "client_session_id", "server_instance_id")},
        ok=state == "completed" and error is None,
        state=state, outcome=outcome, data=data or {}, error=error,
        warnings=warnings or [],
        observation=observation or {"coverage": "unknown", "reason": "not_inspected"},
        revision=revision,
    )
