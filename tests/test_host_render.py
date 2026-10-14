import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch
from nuke_mcp_bridge.protocol import BridgeError


class Knob:
    def __init__(self, value):
        self.v = value
    def value(self):
        return self.v


class FakeNuke(ModuleType):
    def __init__(self):
        super().__init__("nuke")
        self.env = {"nc": True}
        self.current = 1001
        self.proxy_value = True
        self.rendered = []
        self.fail = False
        self.node = SimpleNamespace(Class=lambda: "Write", name=lambda: "Write1")
    def menu(self, name):
        return SimpleNamespace(addCommand=lambda *a: None)
    def toNode(self, name):
        return self.node if name == "Write1" else None
    def frame(self, value=None):
        if value is not None:
            self.current = value
        return self.current
    def proxy(self):
        return self.proxy_value
    def setProxy(self, value):
        self.proxy_value = value
    def execute(self, node, first, last):
        self.current = first
        if self.fail:
            raise RuntimeError("native render failed")
        self.rendered.append(first)
    def root(self):
        return {"first_frame": Knob(1), "last_frame": Knob(3)}


class HostRenderTests(unittest.TestCase):
    def setUp(self):
        self.host = FakeNuke()
        nukescripts = SimpleNamespace(PythonPanel=object)
        with patch.dict(sys.modules, {"nuke": self.host, "nukescripts": nukescripts}):
            spec = importlib.util.spec_from_file_location(
                "addon_under_test", Path(__file__).resolve().parents[1] / "nuke_mcp_addon.py")
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.server = self.module.NukeMCPServer()

    def test_frame_steps_and_cancel_restore_host_state(self):
        job = self.server.render(write_node="Write1", first_frame=1, last_frame=5, step=2)
        self.assertEqual(next(job)["frames_completed"], [1])
        job.close()
        self.assertEqual(self.host.rendered, [1])
        self.assertEqual(self.host.frame(), 1001)
        self.assertTrue(self.host.proxy())

    def test_failure_restores_frame_and_proxy(self):
        self.host.fail = True
        with self.assertRaises(RuntimeError):
            list(self.server.render(write_node="Write1", frame_range="1-3"))
        self.assertEqual(self.host.frame(), 1001)
        self.assertTrue(self.host.proxy())

    def test_explicit_sparse_frames_are_not_rendered_as_contiguous_range(self):
        list(self.server.render(write_node="Write1", frame_range="1,3,5"))
        self.assertEqual(self.host.rendered, [1, 3, 5])

    def test_unknown_write_does_not_modify_proxy(self):
        with self.assertRaises(BridgeError):
            list(self.server.render(write_node="missing", first_frame=1, last_frame=2))
        self.assertTrue(self.host.proxy())

    def test_native_nc_environment_rejects_render_all_before_mutation(self):
        class NativeEnvironment(dict):
            def get(self, key, default=None):
                if not isinstance(default, str):
                    raise TypeError('default must be str')
                return super().get(key, default)
        self.host.env = NativeEnvironment(nc=True)
        with self.assertRaises(BridgeError) as failure:
            list(self.server.render(first_frame=1, last_frame=2))
        self.assertEqual(failure.exception.code, 'state_uncertain')
        self.assertEqual(failure.exception.outcome, 'not_started')
        self.assertTrue(self.host.proxy())
