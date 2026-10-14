import unittest
from uuid import uuid4
from tests.fakes import Clock, request
from nuke_mcp_bridge.operations import OperationRegistry
from nuke_mcp_bridge.protocol import BridgeError


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.instance = str(uuid4())
        self.registry = OperationRegistry(self.clock, self.instance)

    def req(self, **kwargs):
        return request(self.instance, **kwargs)

    def test_cancel_and_expire_never_dispatch(self):
        for action in ("cancel", "expire", "shutdown"):
            registry = OperationRegistry(self.clock, self.instance)
            req = self.req()
            registry.admit(req)
            if action == "cancel":
                registry.cancel(req["request_id"])
            elif action == "expire":
                self.clock.advance(31)
            else:
                registry.shutdown()
            called = []
            registry.tick(lambda r: called.append(r))
            self.assertEqual(called, [])
            self.assertEqual(registry.lookup(req["request_id"], self.instance)["outcome"],
                             "not_started")

    def test_fifo_and_one_active_per_session(self):
        requests = [self.req() for _ in range(8)]
        for req in requests:
            self.assertEqual(self.registry.admit(req)["state"], "queued")
        busy = self.registry.admit(self.req(session=requests[0]["client_session_id"]))
        self.assertEqual(busy["error"]["code"], "busy")
        seen = []
        for _ in requests:
            self.registry.tick(lambda r: seen.append(r["request_id"]) or {"pong": True})
        self.assertEqual(seen, [r["request_id"] for r in requests])

    def test_pending_limit_and_validation(self):
        for _ in range(64):
            self.registry.admit(self.req())
        self.assertEqual(self.registry.admit(self.req())["error"]["code"], "busy")
        other = self.req(server_instance_id=str(uuid4()))
        self.assertEqual(self.registry.admit(other)["error"]["code"], "instance_changed")

    def test_duplicate_receipt_payload_conflict_and_no_reexecution(self):
        req = self.req(command="edit")
        self.registry.admit(req)
        called = []
        self.registry.tick(lambda r: called.append(1) or {"changed": True})
        self.clock.advance(301)
        self.assertEqual(self.registry.admit(req)["state"], "completed")
        self.registry.tick(lambda r: called.append(2))
        self.assertEqual(called, [1])
        conflict = dict(req, params={"different": True})
        self.assertEqual(self.registry.admit(conflict)["error"]["code"], "request_conflict")

    def test_expired_receipt_and_restarted_instance_are_not_success(self):
        req = self.req()
        self.registry.admit(req)
        self.registry.tick(lambda r: {})
        self.clock.advance(1801)
        self.assertEqual(self.registry.lookup(req["request_id"], self.instance)["error"]["code"],
                         "receipt_expired_or_unknown")
        self.assertEqual(self.registry.lookup(req["request_id"], str(uuid4()))["error"]["code"],
                         "instance_changed")

    def test_capacity_evicts_only_terminal_receipts(self):
        registry = OperationRegistry(self.clock, self.instance, max_receipts=2)
        a, b, c = self.req(), self.req(), self.req()
        registry.admit(a)
        registry.admit(b)
        self.assertEqual(registry.admit(c)["error"]["code"], "busy")
        registry.tick(lambda r: {})
        self.assertEqual(registry.admit(c)["state"], "queued")
        self.assertEqual(registry.lookup(b["request_id"], self.instance)["state"], "queued")

    def test_running_cancel_is_not_cancellation_proof(self):
        req = self.req(command="edit")
        self.registry.admit(req)
        def dispatch(r):
            status = self.registry.cancel(r["request_id"])
            self.assertEqual(status["state"], "running")
            self.assertEqual(status["outcome"], "unknown")
            return {"changed": True}
        self.registry.tick(dispatch)
        result = self.registry.lookup(req["request_id"], self.instance)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["outcome"], "applied")

    def test_failure_after_dispatch_is_unknown_and_receipts_are_copies(self):
        req = self.req(command="edit")
        self.registry.admit(req)
        def failure(r):
            raise RuntimeError("after mutation")
        self.registry.tick(failure)
        result = self.registry.lookup(req["request_id"], self.instance)
        self.assertEqual(result["outcome"], "unknown")
        result["state"] = "completed"
        self.assertEqual(self.registry.lookup(req["request_id"], self.instance)["state"], "failed")

    def test_cooperative_job_cancels_between_steps_and_closes(self):
        req = self.req(command="render")
        self.registry.admit(req)
        steps, closed = [], []
        def job():
            try:
                for i in range(3):
                    steps.append(i)
                    yield {"frames_completed": list(steps)}
            finally:
                closed.append(True)
        self.registry.tick(lambda r: job())
        self.registry.tick(lambda r: None)
        self.registry.cancel(req["request_id"])
        self.registry.tick(lambda r: None)
        result = self.registry.lookup(req["request_id"], self.instance)
        self.assertEqual(steps, [0])
        self.assertEqual(closed, [True])
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(result["data"]["frames_completed"], [0])

    def test_shutdown_does_not_admit_new_requests(self):
        self.registry.shutdown()
        result = self.registry.admit(self.req())
        self.assertEqual(result["outcome"], "not_started")
        self.assertEqual(result["error"]["code"], "stopping")
