import threading
import time
import unittest
from uuid import uuid4
from nuke_mcp_bridge.client import BridgeClient
from nuke_mcp_bridge.operations import OperationRegistry
from nuke_mcp_bridge.runtime import BridgeRuntime
from tests.test_runtime import ManualDispatcher


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = ManualDispatcher()
        self.seen = []
        self.runtime = BridgeRuntime(
            {"ping": lambda: {"pong": True},
             "edit": lambda **p: self.seen.append(p) or {"changed": True}},
            OperationRegistry(), self.dispatcher)
        self.runtime.start(port=0)
        self.addCleanup(self.runtime.stop)
        self.client = BridgeClient(port=self.runtime.port)
        self.addCleanup(self.client.close)

    def run_with_pump(self, fn):
        results = []
        thread = threading.Thread(target=lambda: results.append(fn()))
        thread.start()
        until = time.monotonic() + 4
        while thread.is_alive() and time.monotonic() < until:
            self.dispatcher.tick()
            time.sleep(.005)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results)
        return results[0]

    def test_late_outcome_not_mistaken_for_next_request(self):
        self.client.connect()
        first = self.client.call("edit", {"name": "one"}, timeout_ms=20)
        self.assertFalse(first["ok"])
        self.assertEqual(first["outcome"], "unknown")
        # Expired queued work never executes when the UI becomes responsive.
        self.dispatcher.tick()
        second = self.run_with_pump(lambda: self.client.call("ping", {}))
        self.assertTrue(second["data"]["pong"])
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.assertEqual(self.seen, [])
        status = self.client.status(first["request_id"], first["server_instance_id"])
        self.assertEqual(status["outcome"], "not_started")

    def test_async_start_and_poll_retain_request_identity(self):
        accepted = self.client.submit("edit", {"a": 1})
        self.assertEqual(accepted["state"], "queued")
        self.dispatcher.tick()
        result = self.client.status(accepted["request_id"], accepted["server_instance_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["request_id"], accepted["request_id"])
        self.assertEqual(self.seen, [{"a": 1}])

    def test_restart_returns_instance_changed_no_replay(self):
        accepted = self.client.submit("edit", {})
        port = self.runtime.port
        self.runtime.stop()
        replacement = BridgeRuntime({}, OperationRegistry(), ManualDispatcher())
        replacement.start(port=port)
        self.addCleanup(replacement.stop)
        self.client.close()
        self.client.connect()
        status = self.client.status(accepted["request_id"], accepted["server_instance_id"])
        self.assertEqual(status["error"]["code"], "instance_changed")
        self.assertEqual(self.seen, [])

    def test_wrong_receipt_identity_is_rejected_and_socket_closed(self):
        send = self.runtime._send
        def corrupt(sock, message):
            if message.get('type') == 'reply':
                message['result']['request_id'] = str(uuid4())
            send(sock, message)
        self.runtime._send = corrupt
        result = self.client.submit('edit', {})
        self.assertEqual(result['error']['code'], 'response_mismatch')
        self.assertIsNone(self.client.sock)

    def test_stale_outer_message_is_rejected_without_replay(self):
        send = self.runtime._send
        def corrupt(sock, message):
            if message.get('type') == 'reply':
                message['message_id'] = str(uuid4())
            send(sock, message)
        self.runtime._send = corrupt
        result = self.client.submit('edit', {})
        self.assertEqual(result['error']['code'], 'response_mismatch')
        self.dispatcher.tick()
        self.assertEqual(self.seen, [{}])
