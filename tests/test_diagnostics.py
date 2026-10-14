import importlib.util
import json
from pathlib import Path
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch
from tests.inspection_fakes import ImageHost
from nuke_mcp_bridge.protocol import BridgeError
from nuke_mcp_bridge.mutations import operation_guard
if importlib.util.find_spec('nuke_mcp_bridge.diagnostics'):
    from nuke_mcp_bridge.diagnostics import sample_channel_statistics as sample
else: sample = None

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(sample, 'Diagnostics implementation is missing')
        self.host = ImageHost()
        self.node = self.host.add('Constant1', 'Constant')
    def test_known_constant_ramp_alpha_signals_and_frame_restoration(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/channel_statistics.json').read_text())
        for name, signal in fixture['signals'].items():
            with self.subTest(signal=name):
                self.host.sampler = (lambda c,x,y,dx,dy: x/4) if name=='ramp' else (lambda c,x,y,dx,dy: signal['value'])
                result = sample(self.host,'Constant1',['rgba.red'],1001,max_samples_per_channel=4)
                stat = result['statistics'][0]
                self.assertAlmostEqual(stat['mean'], signal.get('expected_mean',0.), delta=fixture['tolerance'])
                self.assertEqual(stat['sample_count'],4)
                self.assertFalse(result['sampling']['samples_every_pixel'])
                self.assertEqual(result['sampling']['method'], 'nuke.Node.sample_cubic_filtered_grid')
                self.assertEqual(self.host.current_frame,10)
    def test_sparse_pixel_not_seen_by_grid_is_not_claimed_black(self):
        self.host.sampler = lambda c,x,y,dx,dy: 1. if x < .75 and y < .75 else 0.
        result = sample(self.host,'Constant1',['rgba.red'],1,max_samples_per_channel=4)
        self.assertEqual(result['statistics'][0]['zero_fraction'],1.)
        self.assertFalse(result['sampling']['samples_every_pixel'])
        self.assertIn('not prove', result['sampling']['limitations'])
    def test_nonfinite_values_excluded_from_finite_statistics(self):
        values = iter([float('nan'),float('inf'),0.,2.])
        self.host.sampler = lambda *args: next(values)
        result = sample(self.host,'Constant1',['rgba.red'],1,max_samples_per_channel=4)
        stat = result['statistics'][0]
        self.assertEqual((stat['min'],stat['max'],stat['mean'],stat['zero_fraction']), (0.,2.,1.,.5))
        self.assertEqual(stat['nonfinite_count'],2)
        json.dumps(result, allow_nan=False)
    def test_all_nonfinite_reports_no_finite_extrema(self):
        self.host.sampler = lambda *args: float('nan')
        stat = sample(self.host,'Constant1',['rgba.red'],1,max_samples_per_channel=1)['statistics'][0]
        self.assertIsNone(stat['min'])
        self.assertIsNone(stat['mean'])
        self.assertIsNone(stat['zero_fraction'])
    def test_channel_expansion_and_limits_preserve_frame(self):
        self.node._channels = ['layer.c'+str(i) for i in range(17)]
        for channels in (['layer'],['missing']):
            with self.assertRaises(BridgeError): sample(self.host,'Constant1',channels,1)
        for count in (0,4097,True):
            with self.assertRaises(BridgeError): sample(self.host,'Constant1',['layer.c0'],1,max_samples_per_channel=count)
        self.assertEqual(self.host.current_frame,10)
        self.node._channels = ['rgba.red','rgba.alpha']
        result = sample(self.host,'Constant1',['rgba','rgba.red'],1,max_samples_per_channel=1)
        self.assertEqual(result['channels'], ['rgba.red','rgba.alpha'])
    def test_invalid_roi_and_frame_fail_before_sampling(self):
        for roi in ([0,0,0,1],[-1,0,1,1],[0,0,5,4],[0,0,1.5,1],[0,0,True,1]):
            with self.assertRaises(BridgeError) as error: sample(self.host,'Constant1',['rgba.red'],1,roi=roi)
            self.assertEqual(error.exception.code, 'invalid_roi')
            self.assertEqual(self.host.current_frame,10)
        with self.assertRaises(BridgeError): sample(self.host,'Constant1',['rgba.red'],1.5)
        self.assertEqual(self.host.current_frame,10)

    def test_extreme_finite_statistics_do_not_overflow_or_leak_frame(self):
        self.host.sampler = lambda *args: sys.float_info.max
        result = sample(self.host,'Constant1',['rgba.red'],1001,roi=[0,0,3,1],max_samples_per_channel=3)
        self.assertEqual(result['statistics'][0]['mean'],sys.float_info.max)
        self.assertEqual(self.host.current_frame,10)

    def test_summary_exception_still_restores_frame_and_retains_counts(self):
        with patch('nuke_mcp_bridge.diagnostics.summarize',side_effect=OverflowError('summary failure')):
            with self.assertRaises(BridgeError) as error:
                sample(self.host,'Constant1',['rgba.red'],1001,max_samples_per_channel=1)
        self.assertEqual(self.host.current_frame,10)
        self.assertEqual(error.exception.data['samples_completed'],1)
        self.assertEqual(error.exception.code,'statistics_failed')

    def test_roi_and_channels_resolve_at_requested_frame(self):
        self.node.format = lambda: SimpleNamespace(width=lambda:8 if self.host.current_frame==1001 else 4,
                                                    height=lambda:4)
        self.node.channels = lambda: ['target.red','target.alpha'] if self.host.current_frame==1001 else ['current.red']
        result = sample(self.host,'Constant1',['target'],1001,roi=[4,0,4,4],max_samples_per_channel=4)
        self.assertEqual(result['roi'],[4,0,4,4])
        self.assertEqual(result['channels'],['target.red','target.alpha'])
        self.assertEqual(result['samples_completed'],8)
        self.assertEqual(self.host.current_frame,10)

    def test_invalid_argument_syntax_does_not_change_frame(self):
        with self.assertRaises(BridgeError): sample(self.host,'Constant1',[],1001)
        with self.assertRaises(BridgeError): sample(self.host,'Constant1',['rgba.red'],1001,roi=[0,0,1.5,1])
        self.assertEqual(self.host.frame_writes,[])
    def test_cancel_and_deadline_preserve_partial_statistics_and_restore_frame(self):
        calls = 0
        def sampler(*args):
            nonlocal calls
            calls += 1
            return .25
        self.host.sampler = sampler
        with self.assertRaises(BridgeError) as failure:
            sample(self.host,'Constant1',['rgba.red'],1001,max_samples_per_channel=4,should_stop=lambda:calls==2)
        self.assertEqual(failure.exception.code,'cancelled')
        self.assertEqual(failure.exception.data['statistics'][0]['sample_count'],2)
        self.assertEqual(self.host.current_frame,10)
        calls = 0
        def guard():
            if calls==1: raise BridgeError('deadline_expired','test')
        token = operation_guard.set(guard)
        try:
            with self.assertRaises(BridgeError) as failure: sample(self.host,'Constant1',['rgba.red'],1001,max_samples_per_channel=4)
            self.assertEqual(failure.exception.data['samples_completed'],1)
        finally: operation_guard.reset(token)
        self.assertEqual(self.host.current_frame,10)
    def test_host_failure_restores_frame_and_retains_evidence(self):
        def fail(*args): raise RuntimeError('native evaluation failed')
        self.host.sampler = fail
        with self.assertRaises(BridgeError) as failure: sample(self.host,'Constant1',['rgba.red'],1001)
        self.assertEqual(failure.exception.code,'sampling_failed')
        self.assertEqual(failure.exception.data['frame'],1001)
        self.assertEqual(self.host.current_frame,10)
    def test_failed_frame_restore_cannot_report_success(self):
        frame = self.host.frame
        def set_frame(value=None):
            if value == 10: raise RuntimeError('restore failed')
            return frame(value)
        self.host.frame = set_frame
        with self.assertRaises(BridgeError) as failure: sample(self.host,'Constant1',['rgba.red'],1001,max_samples_per_channel=1)
        self.assertEqual(failure.exception.code,'restoration_failed')
        self.assertEqual(failure.exception.outcome,'unknown')
        self.assertEqual(failure.exception.data['samples_completed'],1)
