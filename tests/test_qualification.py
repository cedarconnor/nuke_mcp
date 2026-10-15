"""Fail-closed qualification reports and live-run safety boundaries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from tests.live import qualify as q
except ImportError:
    q = None


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(q, 'Qualification runner/report reducer is not implemented')

    def row(self):
        return {'checks': {'correlated_reads': {'expected': 8, 'actual': 8, 'passed': True}},
                'cleanup': {'outcome': 'not_needed'}, 'status': 'completed',
                'evidence': {'request_id': 'request', 'server_instance_id': 'instance'}}

    def report(self, row=None, **kw):
        return q.aggregate({'license_mode': 'noncommercial', 'nuke_version': '17.0v4'},
                           ['two-clients'], {'two-clients': row or self.row()}, **kw)

    def test_nc_success_does_not_certify_commercial_or_artist_review(self):
        report = self.report()
        self.assertTrue(report['passed'])
        self.assertFalse(report['commercial_qualified'])
        self.assertFalse(report['artist_approved'])
        self.assertIn('toolset-roundtrip', report['unqualified'])

    def test_missing_skipped_and_false_required_checks_fail_closed(self):
        for checks in ({}, {'correlated_reads': {'expected': 8, 'actual': 7, 'passed': False}},
                       {'correlated_reads': {'expected': 8, 'actual': 8, 'passed': True, 'skipped': True}}):
            row = self.row(); row['checks'] = checks
            self.assertFalse(self.report(row)['passed'])
        self.assertFalse(q.aggregate({}, ['two-clients'], {})['passed'])

    def test_forged_success_does_not_override_unknown_cleanup(self):
        row = self.row(); row['passed'] = True; row['cleanup'] = {'outcome': 'unknown'}
        self.assertFalse(self.report(row)['passed'])

    def test_applied_cleanup_requires_native_receipt_and_matching_readback(self):
        row = self.row(); row['cleanup'] = {'outcome': 'applied'}
        self.assertFalse(self.report(row)['passed'])
        row['cleanup'].update(expected={'fps': 24}, actual={'fps': 24},
                              receipt={'ok': True, 'request_id': 'r', 'server_instance_id': 'i',
                                       'outcome': 'applied', 'transport_error': False})
        self.assertTrue(self.report(row)['passed'])
        row['cleanup']['actual'] = {'fps': 25}
        self.assertFalse(self.report(row)['passed'])

    def test_empty_selection_and_non_boolean_pass_fail_closed(self):
        self.assertFalse(q.aggregate({}, [], {})['passed'])
        row = self.row(); row['checks']['correlated_reads']['passed'] = 'yes'
        self.assertFalse(self.report(row)['passed'])

    def test_defaults_are_read_only_and_mutations_need_both_flags_and_identity(self):
        args = q.parse_args(['--output', str(Path.cwd()/'evidence')])
        self.assertFalse(args.mutate)
        self.assertEqual(q.selected_scenarios(args), ['two-clients', 'legacy-tools', 'nc-ambiguity'])
        for flags in ([], ['--mutate'], ['--disposable']):
            args = q.parse_args(['--output', str(Path.cwd()/'evidence'), '--scenario', 'verified-edit'] + flags)
            with self.assertRaises(ValueError): q.validate_options(args)

    def test_relative_output_and_reused_output_are_rejected(self):
        with self.assertRaises(ValueError):
            q.validate_options(q.parse_args(['--output', 'relative']))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileExistsError): q.prepare_output(Path(folder))

    def test_ownership_requires_exact_path_pid_instance_and_disposable_flag(self):
        fixture = Path.cwd()/'fixture.nk'
        facts = {'pid': 42, 'path': str(fixture), 'disposable': '1'}
        self.assertTrue(q.owned(facts, 42, fixture, 'a', 'a'))
        for key, value in [('pid', 43), ('path', str(fixture.parent/'other.nk')), ('disposable', None)]:
            changed = dict(facts, **{key:value})
            self.assertFalse(q.owned(changed, 42, fixture, 'a', 'a'))
        self.assertFalse(q.owned(facts, 42, fixture, 'a', 'b'))

    def test_failure_report_preserves_partial_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'new'
            args = q.parse_args(['--output', str(output)])
            with patch.object(q.BridgeClient, 'call', side_effect=RuntimeError('host unavailable')):
                report = q.run(args)
            self.assertFalse(report['passed'])
            self.assertTrue((output/'report.json').is_file())
            self.assertIn('host unavailable', report['error'])

class QualificationBoundaryTests(unittest.TestCase):
    def test_wrong_disposable_host_prevents_any_scenario_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture=Path(folder)/'events_fixture.nk'; fixture.write_text('Root {}')
            args=q.parse_args(['--output',str(Path(folder)/'out'),'--mutate','--disposable','--pid','42',
                               '--fixture',str(fixture),'--scenario','event-stale-state'])
            out=q.prepare_output(args.output); run=q.NativeRun(args,out);run.instance='a'
            receipt={'ok':True,'request_id':'r','server_instance_id':'a','data':{'output':{
                     'pid':43,'path':str(fixture),'disposable':'1'}}}
            with patch.object(run.client,'call',return_value=receipt) as bridge:
                with self.assertRaisesRegex(RuntimeError,'Refusing'): run.scenario('event-stale-state')
            self.assertEqual([c.args[0] for c in bridge.call_args_list],['execute_code'])
            self.assertNotIn('setValue',bridge.call_args.args[1]['code'])

    def test_native_transport_failure_cannot_prove_retention(self):
        row={'checks':{'correlated_reads':q.check(8,8)},'status':'completed',
             'cleanup':{'outcome':'retained_disposable','owned':True,'receipt':{
                 'ok':True,'request_id':'r','server_instance_id':'i','transport_error':True}}}
        self.assertFalse(q.aggregate({},['two-clients'],{'two-clients':row})['passed'])

    def test_nested_read_scenario_never_samples_or_changes_frames(self):
        from tests.live.inspection_probe import probe
        calls=[]
        class Client:
            def call(self,command,params):
                calls.append((command,params))
                if command=='execute_code':
                    return {'ok':True,'data':{'output':{'pid':42,'script':'C:/fixture/inspection_fixture.nk','frame':1,'proxy':False,'selection':[]}}}
                if command=='inspect_graph':
                    paths=['GroupA.SameName','GroupB.SameName','MCP_Constant','MCP_Ramp','MCP_MissingRead']
                    return {'ok':True,'data':{'nodes':[{'path':x} for x in (paths[:1] if params else paths)],'truncated':bool(params),'observation':{'coverage':'partial'}}}
                if command=='inspect_reads': return {'ok':True,'data':{'reads':[{'path':'MCP_MissingRead'}]}}
                if command=='validate_reads': return {'ok':True,'data':{'checked_paths':3,'missing_paths':3,'requested_paths':3,'unknown_paths':0}}
                raise AssertionError('Unexpected mutating or sampling command: '+command)
            def close(self):pass
        result=probe(42,9877,client_factory=lambda **kw:Client(),statistics=False)
        self.assertTrue(result['passed'],result)
        self.assertEqual(len(calls),6)

    def test_scenario_error_cannot_be_masked_by_good_checks(self):
        row={'checks':{'correlated_reads':q.check(8,8)},'status':'failed','cleanup':{'outcome':'not_needed'}}
        self.assertFalse(q.aggregate({},['two-clients'],{'two-clients':row})['passed'])

    def test_mutation_stdio_refuses_replacement_instance_before_edit(self):
        import asyncio
        from tests import smoke_mcp
        self.assertTrue(hasattr(smoke_mcp, "verify_disposable_session"), "Missing stdio identity gate")
        verify_disposable_session=smoke_mcp.verify_disposable_session
        class Reply:
            isError=False
            structuredContent={'ok':True,'server_instance_id':'replacement','data':{}}
        class Session:
            calls=[]
            async def call_tool(self,name,arguments):
                self.calls.append(name)
                return Reply()
        session=Session()
        with self.assertRaisesRegex(RuntimeError,'instance'):
            asyncio.run(verify_disposable_session(session,'original',42,Path('C:/fixture.nk')))
        self.assertEqual(session.calls,['get_capabilities'])

class QualificationUncertaintyTests(unittest.TestCase):
    def test_helper_stops_after_unknown_mutation_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture=Path(folder)/'library_fixture.nk';fixture.write_text('Root {}')
            args=q.parse_args(['--output',str(Path(folder)/'out'),'--mutate','--disposable','--pid','42','--fixture',str(fixture)])
            run=q.NativeRun(args,q.prepare_output(args.output));run.instance='i'
            uncertain={'ok':False,'request_id':'mutation','server_instance_id':'i','outcome':'unknown',
                       'state':'failed','error':{'code':'readback_uncertain'},'data':{}}
            identity={'ok':True,'request_id':'identity','server_instance_id':'i','outcome':'not_started','data':{
                'output':{'pid':42,'path':str(fixture),'disposable':'1'}}}
            with patch.object(run.client,'call',side_effect=[identity,uncertain,identity,identity]) as bridge:
                adapter=run.helper_client()
                self.assertEqual(adapter.call('save_toolset',{})['outcome'],'unknown')
                with self.assertRaisesRegex(RuntimeError,'uncertain'):
                    adapter.call('save_script',{})
            self.assertEqual([call.args[0] for call in bridge.call_args_list],['execute_code','save_toolset'])

    def test_owned_library_must_be_inside_this_fixture_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture=Path(folder)/'library_fixture.nk';fixture.write_text('Root {}')
            args=q.parse_args(['--output',str(Path(folder)/'out'),'--mutate','--disposable','--pid','42','--fixture',str(fixture)])
            run=q.NativeRun(args,q.prepare_output(args.output));run.instance='i'
            facts={'pid':42,'path':str(fixture),'disposable':'1','library':'C:/shared-production-library'}
            receipt={'ok':True,'request_id':'identity','server_instance_id':'i','data':{'output':facts}}
            with patch.object(run.client,'call',return_value=receipt):
                result=run.scenario('toolset-roundtrip')
            self.assertEqual(result['status'],'failed')
            self.assertIn('private library',result['error'])

class QualificationProofTests(unittest.TestCase):
    def test_mutating_scenario_cannot_use_read_only_cleanup(self):
        row={'status':'completed','checks':{k:q.check(True,True) for k in ('edit_readback','deleted')},
             'cleanup':{'outcome':'not_needed'}}
        self.assertFalse(q.aggregate({},['verified-edit'],{'verified-edit':row})['passed'])

    def test_failed_helper_cannot_be_promoted_by_partial_good_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture=Path(folder)/'inspection_fixture.nk';fixture.write_text('Root {}')
            args=q.parse_args(['--output',str(Path(folder)/'out'),'--pid','42','--fixture',str(fixture),'--scenario','nested-read'])
            run=q.NativeRun(args,q.prepare_output(args.output));run.instance='i'
            raw={'checks':{k:True for k in q.REQUIRED['nested-read']},'error':'unhandled receipt failure','receipts':{}}
            identity={'ok':True,'request_id':'r','server_instance_id':'i','data':{'output':{'pid':42,'path':str(fixture),'disposable':'1'}}}
            with patch.object(run.client,'call',return_value=identity), patch('tests.live.inspection_probe.probe',return_value=raw):
                row=run.scenario('nested-read')
            self.assertFalse(q.aggregate({},['nested-read'],{'nested-read':row})['passed'])

class RenderQualificationTests(unittest.TestCase):
    def test_unknown_render_does_not_claim_known_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture=Path(folder)/'events_fixture.nk';fixture.write_text('Root {}')
            args=q.parse_args(['--output',str(Path(folder)/'out'),'--pid','42','--fixture',str(fixture)])
            run=q.NativeRun(args,q.prepare_output(args.output));run.instance='i'
            def call(command,params):
                output=({'file':str(args.output/'new.png'),'frame':1} if 'MCP_Review' in params['code'] else
                        {'pid':42,'path':str(fixture),'disposable':'1','frame':1,'proxy':False})
                return {'ok':True,'request_id':'r','server_instance_id':'i','outcome':'applied','data':{'output':output}}
            failed={'ok':False,'state':'failed','outcome':'unknown','request_id':'render','server_instance_id':'i',
                    'error':{'code':'host_error'}}
            with patch.object(run.client,'call',side_effect=call),patch.object(run.client,'submit',return_value=failed):
                row={'checks':{},'cleanup':{'outcome':'unknown'}}
                run.render(row)
            self.assertEqual(row['cleanup']['outcome'],'unknown')


if __name__ == '__main__': unittest.main()
