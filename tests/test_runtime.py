import socket
import threading
import time
import unittest
from uuid import uuid4
from tests.fakes import request
from nuke_mcp_bridge.protocol import FrameDecoder, encode_message, BridgeError
from nuke_mcp_bridge.operations import OperationRegistry
from nuke_mcp_bridge.runtime import BridgeRuntime


class ManualDispatcher:
    def start(self, tick):
        self.tick = tick
    def stop(self):
        self.tick = None


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = ManualDispatcher()
        self.seen = []
        self.runtime = BridgeRuntime(
            {"edit": self.edit, "ping": lambda **kw: {"pong": True}},
            OperationRegistry(), self.dispatcher)
        self.runtime.start(port=0)
        self.addCleanup(self.runtime.stop)
        self.clients = []

    def edit(self, **params):
        self.assertEqual(threading.current_thread(), threading.main_thread())
        self.seen.append(params)
        return {"value": params}

    def receive(self, sock):
        decoder = FrameDecoder()
        while True:
            chunk = sock.recv(65536)
            self.assertTrue(chunk)
            messages = decoder.feed(chunk)
            if messages:
                return messages[0]

    def connect(self, version=2, application="nuke-mcp"):
        sock = socket.create_connection(("127.0.0.1", self.runtime.port), timeout=2)
        self.addCleanup(sock.close)
        session = str(uuid4())
        sock.sendall(encode_message(dict(type="hello", application=application,
                                        protocol_version=version, client_session_id=session)))
        hello = self.receive(sock)
        return sock, session, hello

    def send_request(self, sock, session, **params):
        req = request(self.runtime.registry.instance_id, session=session,
                      command="edit", params=params)
        sock.sendall(encode_message({"type": "request", "request": req}))
        return req, self.receive(sock)

    def test_two_clients_and_main_thread_serialization(self):
        a, sa, _ = self.connect()
        b, sb, _ = self.connect()
        qa, ra = self.send_request(a, sa, who="A")
        qb, rb = self.send_request(b, sb, who="B")
        self.assertEqual(ra["result"]["state"], "queued")
        self.assertEqual(rb["result"]["state"], "queued")
        self.assertEqual(self.seen, [])
        self.dispatcher.tick()
        self.dispatcher.tick()
        self.assertEqual(self.seen, [{"who": "A"}, {"who": "B"}])

    def test_wrong_protocol_and_ninth_client_rejected(self):
        _, _, bad = self.connect(version=1)
        self.assertEqual(bad["error"]["code"], "protocol_mismatch")
        for _ in range(8):
            _, _, hello = self.connect()
            self.assertEqual(hello["type"], "hello")
        _, _, busy = self.connect()
        self.assertEqual(busy["error"]["code"], "busy")

    def test_wrong_application_rejected_before_host_dispatch(self):
        _, _, bad = self.connect(application='other-dcc')
        self.assertEqual(bad['error']['code'], 'protocol_mismatch')
        self.assertEqual(self.seen, [])

    def test_fragmented_and_coalesced_frames(self):
        sock, session, _ = self.connect()
        req = request(self.runtime.registry.instance_id, session=session,
                      command="edit", params={"text": "é } {\nprint('x')"})
        wire = encode_message({"type": "request", "request": req})
        for byte in wire:
            sock.sendall(bytes([byte]))
        self.assertEqual(self.receive(sock)["result"]["state"], "queued")
        self.dispatcher.tick()
        self.assertEqual(self.seen[0]["text"], "é } {\nprint('x')")

    def test_disconnect_after_admission_does_not_replay(self):
        sock, session, _ = self.connect()
        req, _ = self.send_request(sock, session, who="once")
        sock.close()
        self.dispatcher.tick()
        other, other_session, _ = self.connect()
        control = dict(type="status", message_id=str(uuid4()), request_id=req["request_id"],
                       server_instance_id=self.runtime.registry.instance_id)
        other.sendall(encode_message(control))
        result = self.receive(other)["result"]
        self.assertEqual(result["state"], "completed")
        self.assertEqual(len(self.seen), 1)

    def test_stop_rejects_queue_detaches_timer_and_releases_port(self):
        sock, session, _ = self.connect()
        req, _ = self.send_request(sock, session)
        port = self.runtime.port
        self.runtime.stop()
        self.assertIsNone(self.dispatcher.tick)
        self.assertEqual(self.seen, [])
        self.assertEqual(self.runtime.registry.lookup(
            req["request_id"], self.runtime.registry.instance_id)["outcome"], "not_started")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))

    def test_remote_bind_and_port_collision_refused(self):
        other = BridgeRuntime({}, OperationRegistry(), ManualDispatcher())
        with self.assertRaises(BridgeError):
            other.start(host="0.0.0.0")
        with self.assertRaises(OSError):
            other.start(port=self.runtime.port)
        other.stop()
