import unittest
from types import SimpleNamespace
from nuke_mcp_bridge.capabilities import probe_capabilities


class CapabilityTests(unittest.TestCase):
    def test_native_environment_requires_string_defaults(self):
        class NativeEnvironment(dict):
            def get(self, key, default=None):
                if not isinstance(default, str):
                    raise TypeError('GlobalsEnvironment.get() argument 2 must be str')
                return super().get(key, default)
        result = probe_capabilities(SimpleNamespace(
            env=NativeEnvironment(nc=True, nukex=True), NUKE_VERSION_STRING='17.0v4', GUI=True))
        self.assertEqual(result['license_mode'], 'noncommercial')
        self.assertEqual(result['host_flavor'], 'nukex')

    def test_variants_and_unknown_license_do_not_probe_nodes(self):
        for env, expected in (({}, "unknown"), ({"nukex": True}, "nukex"),
                              ({"studio": True}, "nukestudio"), ({"nukex": False}, "nuke")):
            host = SimpleNamespace(env=env, NUKE_VERSION_STRING="17.0v4", GUI=True)
            result = probe_capabilities(host)
            self.assertEqual(result["host_flavor"], expected)
            self.assertEqual(result["license_mode"], "unknown")
            self.assertEqual(result["node_class_discovery"], "advisory")

    def test_noncommercial_is_explicitly_incomplete(self):
        result = probe_capabilities(SimpleNamespace(
            env={"nc": True}, NUKE_VERSION_STRING="17.0v4", GUI=True))
        self.assertEqual(result["license_mode"], "noncommercial")
        self.assertEqual(result["graph_observation"], "partial_or_unknown")
