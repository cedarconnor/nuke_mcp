import unittest
from tests.fakes import request
from nuke_mcp_bridge.protocol import (
    BridgeError, FrameDecoder, encode_message, validate_request, make_result,
)


class ProtocolTests(unittest.TestCase):
    def test_every_utf8_split_and_coalesced_messages(self):
        first = {"text": "é } {\ntext"}
        wire = encode_message(first) + encode_message({"n": 2})
        for split in range(len(wire) + 1):
            decoder = FrameDecoder()
            self.assertEqual(decoder.feed(wire[:split]) + decoder.feed(wire[split:]),
                             [first, {"n": 2}])

    def test_bad_frames_are_rejected(self):
        for wire in (b'{"x":"\xff"}\n', b'not json\n', b'[]\n',
                     b'{"x": NaN}\n', b'{"x":1,"x":2}\n'):
            with self.subTest(wire=wire), self.assertRaises(BridgeError):
                FrameDecoder().feed(wire)

    def test_incomplete_and_complete_limits(self):
        for wire in (b"x" * (8 * 1024 * 1024 + 1),
                     b"x" * (8 * 1024 * 1024 + 1) + b"\n"):
            with self.assertRaises(BridgeError) as error:
                FrameDecoder().feed(wire)
            self.assertEqual(error.exception.code, "message_too_large")

    def test_large_coalesced_valid_messages_are_not_rejected_as_one(self):
        wire = encode_message({"x": "a" * (5 * 1024 * 1024)})
        self.assertEqual(len(FrameDecoder().feed(wire + wire)), 2)

    def test_request_validation_before_dispatch(self):
        self.assertEqual(validate_request(request())["timeout_ms"], 30000)
        for changes in ({"request_id": "bad"}, {"protocol_version": 1},
                        {"timeout_ms": True}, {"timeout_ms": 0},
                        {"timeout_ms": 300001}, {"params": []},
                        {"command": ""}, {"extra": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(BridgeError):
                validate_request(request(**changes))

    def test_result_preserves_identity_and_error(self):
        req = request()
        result = make_result(req, state="failed", outcome="unknown",
                             error={"code": "state_uncertain", "message": "unknown"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["request_id"], req["request_id"])
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["observation"]["coverage"], "unknown")
