import importlib.util
import unittest
from types import SimpleNamespace
from uuid import uuid4
from tests.fakes import Clock, request
from tests.event_fakes import EventHost
from tests.test_runtime import ManualDispatcher
from nuke_mcp_bridge.operations import OperationRegistry
from nuke_mcp_bridge.runtime import BridgeRuntime
from nuke_mcp_bridge.mutations import operation_context
from nuke_mcp_bridge.batch import execute_batch
from nuke_mcp_bridge.protocol import BridgeError

if importlib.util.find_spec('nuke_mcp_bridge.events'):
    from nuke_mcp_bridge import events as e
else:
    e = None


class EventTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(e, 'Scene events are not implemented')
        self.clock = Clock()
        self.buffer = e.EventBuffer(capacity=3, clock=self.clock)

    def event(self, kind='knob_changed', path='Grade1', **kwargs):
        self.buffer.record(dict(type=kind, node_path=path, knob='gain', **kwargs))

    def test_revision_precedes_coalescing_and_consumed_updates_are_visible(self):
        self.event(value='do not expose', callback='secret')
        first = self.buffer.read()
        self.clock.advance(.05)
        self.event()
        self.assertEqual(self.buffer.revision(), 2)
        result = self.buffer.read(after_sequence=first['next_sequence'])
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['sequence'], 2)
        self.assertEqual(result['events'][0]['count'], 2)
        self.assertNotIn('value', result['events'][0])
        self.assertNotIn('callback', result['events'][0])
        self.clock.advance(.06)
        self.event()
        self.assertEqual(len(self.buffer.read()['events']), 2)

    def test_overflow_filter_progress_and_gap_are_independent(self):
        for kind in ('node_created', 'node_deleted', 'script_loaded', 'script_saved'):
            self.event(kind)
        result = self.buffer.read(event_types=['knob_changed'])
        self.assertTrue(result['history_gap'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['next_sequence'], 4)
        self.assertFalse(self.buffer.read(4, event_types=[])['history_gap'])
        result = self.buffer.read(1, limit=1, event_types=['script_loaded'])
        self.assertFalse(result['history_gap'])
        self.assertEqual(result['next_sequence'], 3)
        self.assertEqual([x['sequence'] for x in self.buffer.read(3)['events']], [4])

    def test_poll_validation_and_instance_identity(self):
        self.event('node_created')
        for args in ({'limit':501}, {'limit':True}, {'limit':0}, {'after_sequence':-1},
                     {'after_sequence':2}, {'event_types':['arbitrary']}, {'event_types':'knob_changed'}):
            with self.assertRaises(BridgeError): self.buffer.read(**args)
        other = e.EventBuffer()
        self.assertNotEqual(self.buffer.read()['server_instance_id'], other.read()['server_instance_id'])
        self.assertEqual(other.read()['next_sequence'], 0)

    def test_default_ring_and_max_poll_remain_bounded(self):
        buffer=e.EventBuffer()
        for _ in range(1200):buffer.record({'type':'node_created','node_path':'A'})
        first=buffer.read(limit=500)
        self.assertTrue(first['history_gap'])
        self.assertEqual(len(first['events']),500)
        self.assertEqual(first['events'][0]['sequence'],201)
        self.assertEqual(first['next_sequence'],700)
        second=buffer.read(first['next_sequence'],limit=500)
        self.assertFalse(second['history_gap'])
        self.assertEqual(len(second['events']),500)
        self.assertEqual(second['next_sequence'],1200)

    def test_coalescing_never_erases_deletion_script_switch_or_origin(self):
        self.event()
        self.event('node_deleted')
        self.event('script_loaded')
        self.assertEqual([x['type'] for x in self.buffer.read()['events']],
                         ['knob_changed','node_deleted','script_loaded'])
        self.assertEqual(self.buffer.snapshot()['script_generation'], 1)

    def installed(self, host=None):
        host = host or EventHost()
        cleanup = e.install_callbacks(host, self.buffer)
        self.addCleanup(cleanup)
        return host, cleanup

    def test_callbacks_are_single_registration_and_cleanup_is_idempotent(self):
        host, cleanup = self.installed()
        self.assertIs(e.install_callbacks(host, self.buffer), cleanup)
        with self.assertRaises(BridgeError): e.install_callbacks(host, e.EventBuffer())
        node = host.add('Group.Grade')
        for suffix, kind in [('OnCreate','node_created'), ('OnDestroy','node_deleted'),
                             ('KnobChanged','knob_changed'), ('OnScriptLoad','script_loaded'),
                             ('OnScriptSave','script_saved'), ('OnScriptClose','script_closed')]:
            host.emit(suffix, node)
            self.assertEqual(self.buffer.read()['events'][-1]['type'], kind)
        revision = self.buffer.revision()
        cleanup(); cleanup()
        host.emit('OnCreate', node)
        self.assertEqual(self.buffer.revision(), revision)
        other = e.EventBuffer()
        self.addCleanup(e.install_callbacks(host, other))
        host.emit('OnCreate', node)
        self.assertEqual(other.revision(), 1)

    def test_callback_context_loss_and_recursion_degrade_without_escaping(self):
        host, _ = self.installed()
        node = host.add('A')
        def recursive_name():
            host.emit('KnobChanged', node)
            return 'A'
        node.fullName = recursive_name
        host.emit('OnCreate', node)
        self.assertEqual(len(self.buffer.read()['events']), 1)
        with self.assertRaises(BridgeError) as failure: self.buffer.require_revision()
        self.assertEqual(failure.exception.code, 'revision_unavailable')

    def test_nc_missing_callback_and_unknown_license_refuse_guarantees(self):
        for host in (EventHost(nc=True), EventHost(nc='unknown'), EventHost()):
            buffer = e.EventBuffer()
            if host.env['nc'] is False: host.addKnobChanged = None
            self.addCleanup(e.install_callbacks(host, buffer))
            host.emit('OnCreate', host.add('A'))
            self.assertEqual(len(buffer.read()['events']), 1)
            with self.assertRaises(BridgeError) as failure: buffer.require_revision()
            self.assertEqual(failure.exception.code, 'revision_unavailable')

    def test_frame_sampling_is_bounded_and_polling_does_not_mutate(self):
        host, _ = self.installed()
        host.allNodes = lambda **kw: self.fail('Callbacks must not scan graph')
        host.current_frame = 9
        host.emit('UpdateUI')
        host.emit('UpdateUI')
        result = self.buffer.read()
        self.assertEqual([x['type'] for x in result['events']], ['frame_changed'])
        self.assertEqual(result['events'][0]['frame'], 9)
        self.assertEqual(result['frame_observation'], 'sampled')
        self.assertEqual(self.buffer.read(), result)

    def test_runtime_samples_frame_without_root_updateui_callback(self):
        host=EventHost()
        runtime=BridgeRuntime({},OperationRegistry(),ManualDispatcher(),event_host=host)
        runtime.start(port=0);self.addCleanup(runtime.stop)
        host.allNodes=lambda **kw:self.fail('Frame sample must not scan graph')
        host.current_frame=12
        runtime.tick();runtime.tick()
        result=runtime.events.read()
        self.assertEqual([x['type'] for x in result['events']],['frame_changed'])
        self.assertEqual(result['events'][0]['frame'],12)
        self.assertIsNone(result['events'][0]['request_id'])

    def test_stale_batch_refuses_before_mutation_and_own_changes_continue(self):
        host, _ = self.installed()
        a, b = host.add('A'), host.add('B')
        host.emitting_knob(a, 'gain'); host.emitting_knob(b, 'gain')
        ops = [dict(op='set_knob', node_path=x, knob='gain', value=2) for x in ('A','B')]
        revision = self.buffer.require_revision()
        host.emit('KnobChanged', a)
        with self.assertRaises(BridgeError) as failure:
            execute_batch(host, ops, False, revision, self.buffer)
        self.assertEqual(failure.exception.code, 'revision_conflict')
        self.assertEqual(a['gain'].value(), 1)
        token = operation_context.set({'request_id':'owned'})
        try:
            result = execute_batch(host, ops, False, self.buffer.require_revision(), self.buffer)
        finally: operation_context.reset(token)
        self.assertEqual(result['outcome'], 'applied')
        self.assertEqual(b['gain'].value(), 2)
        self.assertEqual(self.buffer.read()['events'][-1]['request_id'], 'owned')

    def test_foreign_callback_stops_array_before_next_component(self):
        host, _ = self.installed()
        node = host.add('A')
        setter = node['translate'].setValue
        def changed(value, index=None):
            setter(value,index)
            token = operation_context.set(None)
            try: host.emit('KnobChanged',node,'translate')
            finally: operation_context.reset(token)
        node['translate'].setValue = changed
        token = operation_context.set({'request_id':'owned'})
        try:
            with self.assertRaises(BridgeError):
                execute_batch(host,[dict(op='set_knob',node_path='A',knob='translate',value=[4,5])],
                              False,self.buffer.require_revision(),self.buffer)
        finally: operation_context.reset(token)
        self.assertEqual(node['translate'].value(), [4,0])

    def test_foreign_change_on_last_write_is_not_reported_as_clean_success(self):
        host, _ = self.installed()
        node = host.add('A')
        setter = node['gain'].setValue
        def changed(value, index=None):
            setter(value,index)
            token=operation_context.set(None)
            try: host.emit('KnobChanged',host.add('Artist'))
            finally: operation_context.reset(token)
        node['gain'].setValue=changed
        with self.assertRaises(BridgeError) as failure:
            execute_batch(host,[dict(op='set_knob',node_path='A',knob='gain',value=4)],
                          False,self.buffer.require_revision(),self.buffer)
        self.assertEqual(failure.exception.outcome,'partial')
        self.assertEqual(node['gain'].value(),4)

    def test_native_environment_and_callback_install_failure(self):
        class NativeEnv(dict):
            def get(self,key,default=None):
                if not isinstance(default,str): raise TypeError('Native defaults require strings')
                return super().get(key,default)
        host=EventHost();host.env=NativeEnv(nc=False,noncommercial=False)
        host.addOnCreate=lambda fn,**kw: (_ for _ in ()).throw(RuntimeError('unavailable'))
        cleanup=e.install_callbacks(host,self.buffer);self.addCleanup(cleanup)
        self.assertFalse(self.buffer.snapshot()['revision_available'])
        host.emit('OnScriptLoad')
        self.assertEqual(self.buffer.read()['events'][0]['type'],'script_loaded')

    def test_runtime_filters_are_per_session_and_generator_origin_is_preserved(self):
        host = EventHost()
        node = host.add('A')
        def render():
            host.emit('KnobChanged', node)
            yield {'frames_completed':[1]}
        runtime = BridgeRuntime({'render':render}, OperationRegistry(), ManualDispatcher(), event_host=host)
        runtime.start(port=0); self.addCleanup(runtime.stop)
        a,b = str(uuid4()),str(uuid4())
        def dispatch(command, session=a, **params):
            return runtime._dispatch(request(runtime.registry.instance_id,session=session,
                                             command=command,params=params))
        dispatch('subscribe_events',event_types=['knob_changed'])
        dispatch('subscribe_events',session=b,event_types=['node_deleted'])
        req = request(runtime.registry.instance_id,session=a,command='render')
        runtime.registry.admit(req); runtime.tick(); runtime.tick()
        found = dispatch('get_events')['events']
        self.assertEqual(found[0]['request_id'],req['request_id'])
        self.assertEqual(dispatch('get_events',session=b)['events'],[])
        self.assertIsNone(operation_context.get())
        runtime.stop()
        revision = runtime.events.revision()
        host.emit('OnCreate',node)
        self.assertEqual(runtime.events.revision(),revision)

    def test_readonly_registry_receipts_and_dry_run_revision(self):
        host = EventHost(); host.add('A')
        registry = OperationRegistry()
        runtime = BridgeRuntime({},registry,ManualDispatcher(),event_host=host)
        runtime.start(port=0);self.addCleanup(runtime.stop)
        for command,params in [('subscribe_events',{'event_types':[]}),('get_events',{})]:
            req=request(registry.instance_id,command=command,params=params)
            registry.admit(req);runtime.tick()
            result=registry.lookup(req['request_id'],registry.instance_id)
            self.assertEqual(result['outcome'],'not_started')
        result=execute_batch(host,[dict(op='set_knob',node_path='A',knob='gain',value=2)],
                             revision_provider=runtime.events)
        self.assertTrue(result['scene_revision']['revision_available'])

    def test_callback_identity_failure_and_save_notification_are_honest(self):
        host,_=self.installed()
        host.thisNode=lambda:None
        host.emit('OnCreate')
        self.assertFalse(self.buffer.snapshot()['revision_available'])
        self.assertNotIn('node_path',self.buffer.read()['events'][0])

    def test_removal_failure_keeps_inert_owner_until_successful_retry(self):
        host=EventHost()
        remove=host.removeOnCreate
        fail=[True]
        def flaky_remove(fn,**kw):
            if fail[0]:raise RuntimeError('busy')
            remove(fn,**kw)
        host.removeOnCreate=flaky_remove
        cleanup=e.install_callbacks(host,self.buffer)
        cleanup()
        host.emit('OnCreate',host.add('A'))
        self.assertEqual(self.buffer.revision(),0)
        with self.assertRaises(BridgeError):e.install_callbacks(host,e.EventBuffer())
        self.assertIn('callback_removal_failed',self.buffer.snapshot()['reasons'])
        fail[0]=False;cleanup()
        other=e.EventBuffer();self.addCleanup(e.install_callbacks(host,other))
        host.emit('OnCreate',host.graph['A'])
        self.assertEqual(other.revision(),1)

    def test_addon_installs_revision_provider_and_restart_changes_instance(self):
        import sys
        from pathlib import Path
        from unittest.mock import patch
        from nuke_mcp_bridge.capabilities import probe_capabilities
        host=EventHost();node=host.add('A')
        host.menu=lambda name:SimpleNamespace(addCommand=lambda *args:None)
        with patch.dict(sys.modules,{'nuke':host,'nukescripts':SimpleNamespace(PythonPanel=object)}):
            spec=importlib.util.spec_from_file_location('event_addon',Path(__file__).resolve().parents[1]/'nuke_mcp_addon.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        addon=module.NukeMCPServer(port=0)
        with patch('nuke_mcp_bridge.runtime.QtDispatcher',ManualDispatcher):
            addon.start();self.addCleanup(addon.stop)
            addon.start()
            old=addon.runtime.events
            host.emit('OnCreate',node)
            self.assertEqual(old.revision(),1)
            result=addon.batch_edit([dict(op='set_knob',node_path='A',knob='gain',value=2)],expected_revision=1)
            self.assertEqual(result['scene_revision']['revision'],1)
            self.assertTrue(probe_capabilities(host,old)['scene_events']['revision_available'])
            addon.stop();addon.start()
            self.assertNotEqual(old.instance_id,addon.runtime.events.instance_id)
            host.emit('OnCreate',node)
            self.assertEqual(old.revision(),1)
            self.assertEqual(addon.runtime.events.revision(),1)


if __name__ == '__main__': unittest.main()
