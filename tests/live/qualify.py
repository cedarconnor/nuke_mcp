"""Opt-in native qualification. Reports are evidence, never mutation retry instructions."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from nuke_mcp_bridge.client import BridgeClient

# Required checks are owned here, not supplied by a potentially incomplete probe.
REQUIRED = {
    'two-clients': ('correlated_reads',),
    'legacy-tools': ('legacy_schemas',),
    'slow-render': ('completed', 'longer_than_old_timeout', 'status_observed', 'output_exists'),
    'verified-edit': ('edit_readback', 'deleted'),
    'nc-ambiguity': ('coverage_disclosed', 'revision_refused'),
    'nested-read': ('nested_paths', 'truncation', 'read_identity', 'missing_sequence', 'state_preserved'),
    'channel-statistics': ('constant_signal', 'ramp_signal', 'sample_limits_disclosed', 'state_preserved'),
    'toolset-roundtrip': ('toolset_save', 'library_listing', 'toolset_load', 'known_knob_topology', 'selection'),
    'two-shot': ('shot_plan', 'two_shots', 'original_restored'),
    'aov-reconstruction': ('comp_plan', 'comp_build', 'numeric', 'preview'),
    'event-stale-state': ('revision_advanced', 'stale_refused', 'restored'),
}
READ_ONLY = ('two-clients', 'legacy-tools', 'nc-ambiguity')
MUTATING = set(REQUIRED) - set(READ_ONLY) - {'nested-read'}
FIXTURES = {'nested-read': 'inspection_fixture.nk', 'channel-statistics': 'inspection_fixture.nk',
            'toolset-roundtrip': 'library_fixture.nk', 'two-shot': 'workflow_fixture.nk',
            'aov-reconstruction': 'workflow_fixture.nk'}
IDENTITY = "import os\noutput['pid']=os.getpid()\noutput['path']=nuke.root().name()\noutput['disposable']=os.environ.get('NUKE_MCP_DISPOSABLE_SESSION')\noutput['frame']=nuke.frame()\noutput['fps']=nuke.root()['fps'].value()\noutput['proxy']=nuke.root().proxy()\noutput['library']=os.environ.get('NUKE_MCP_LIBRARY_ROOT')"


def check(expected, actual, passed=None):
    return {'expected': expected, 'actual': actual,
            'passed': expected == actual if passed is None else bool(passed)}


def cleanup_proven(cleanup):
    outcome = cleanup.get('outcome')
    if outcome == 'not_needed':
        return True
    receipt = cleanup.get('receipt', {})
    native = (receipt.get('ok') is True and not receipt.get('transport_error') and
              bool(receipt.get('request_id')) and bool(receipt.get('server_instance_id')))
    if outcome == 'applied':
        return (native and receipt.get('outcome') == 'applied' and 'expected' in cleanup and
                cleanup['expected'] == cleanup.get('actual'))
    if outcome == 'retained_disposable':
        return native and cleanup.get('owned') is True
    return False


def aggregate(host, selected, results):
    qualified = []
    for name in selected:
        row = results.get(name, {})
        checks = row.get('checks', {})
        good = (name in REQUIRED and row.get('status') == 'completed' and
                not row.get('error') and not row.get('evidence', {}).get('error') and
                (name not in MUTATING or row.get('cleanup', {}).get('outcome') != 'not_needed') and
                all(checks.get(k, {}).get('passed') is True and not checks[k].get('skipped')
                    for k in REQUIRED.get(name, ())) and cleanup_proven(row.get('cleanup', {})))
        if good:
            qualified.append(name)
    passed = bool(selected) and len(qualified) == len(selected)
    return {'passed': passed, 'qualified': qualified,
            'unqualified': [name for name in REQUIRED if name not in qualified],
            # Commercial license detection is deliberately unknown in the current capability API.
            # No subset run, NC run, or caller label can certify a commercial release.
            'commercial_qualified': False, 'artist_approved': False,
            'host': host, 'scenarios': results, 'selected': selected}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--scenario', choices=list(REQUIRED), action='append')
    p.add_argument('--port', type=int, default=9877)
    p.add_argument('--mutate', action='store_true')
    p.add_argument('--disposable', action='store_true')
    p.add_argument('--pid', type=int)
    p.add_argument('--fixture', type=Path)
    return p.parse_args(argv)


def selected_scenarios(args):
    return list(dict.fromkeys(args.scenario or READ_ONLY))


def validate_options(args):
    if not args.output.is_absolute():
        raise ValueError('--output must be an absolute NEW directory')
    names = selected_scenarios(args)
    if MUTATING.intersection(names):
        if not (args.mutate and args.disposable and args.pid and args.fixture):
            raise ValueError('Editing requires --mutate --disposable --pid PID --fixture ABSOLUTE_PATH')
    if args.fixture and (not args.fixture.is_absolute() or not args.fixture.is_file()):
        raise ValueError('--fixture must name an existing absolute fixture file')
    if any(n in FIXTURES for n in names) and not (args.pid and args.fixture):
        raise ValueError('Fixture scenarios require --pid and --fixture')
    for name in names:
        if name in FIXTURES and args.fixture.name != FIXTURES[name]:
            raise ValueError(name + ' requires ' + FIXTURES[name])
    # Each mutating scenario starts with a fresh fixture. No implicit reset between tests.
    if len(MUTATING.intersection(names)) > 1:
        raise ValueError('Run one mutating scenario per fresh disposable host')


def prepare_output(path):
    path.mkdir(parents=True, exist_ok=False)
    return path.resolve()


def owned(facts, pid, fixture, instance, expected_instance):
    return bool(instance and instance == expected_instance and facts.get('pid') == pid and
                facts.get('disposable') == '1' and facts.get('path') and
                Path(facts['path']).resolve() == Path(fixture).resolve())


class NativeRun:
    def __init__(self, args, output):
        self.args, self.output = args, output
        self.client = BridgeClient(port=args.port)
        self.receipts = []
        self.instance = None
        self.uncertain = False

    def call(self, command, **params):
        receipt = self.client.call(command, params)
        self.receipts.append(receipt)
        # Persist after every call, including failed/ambiguous calls.
        (self.output/'receipts.json').write_text(json.dumps(self.receipts, indent=2), encoding='utf-8')
        if receipt.get('outcome') in ('unknown', 'partial') or receipt.get('transport_error'):
            self.uncertain = True
        if self.instance and receipt.get('server_instance_id') != self.instance:
            raise RuntimeError('Host instance changed; no further fixture operations')
        return receipt

    def identity(self):
        receipt = self.call('execute_code', code=IDENTITY)
        if not receipt['ok']:
            raise RuntimeError('Host identity unavailable')
        return receipt, receipt['data']['output']

    def require_owned(self, allowed=None):
        receipt, facts = self.identity()
        allowed = allowed or [self.args.fixture]
        if not any(owned(facts, self.args.pid, path, receipt['server_instance_id'], self.instance)
                   for path in allowed):
            raise RuntimeError('Refusing a host other than the specified disposable fixture')
        return receipt, facts

    def helper_client(self, **kwargs):
        # Reuse this exact connection; never reconnect a helper to an unrelated listener.
        parent = self
        class Adapter:
            def call(self, command, params):
                if parent.uncertain:
                    raise RuntimeError('Previous operation uncertain; stop without further fixture calls')
                if parent.args.mutate:
                    folder = parent.args.fixture.parent
                    parent.require_owned([parent.args.fixture, folder/'original.nknc', folder/'roundtrip.nknc'])
                return parent.call(command, **params)
            def close(self): pass
        return Adapter()

    def retained(self):
        if self.uncertain:
            return {'outcome':'unknown'}
        folder = self.args.fixture.parent
        receipt, _ = self.require_owned([self.args.fixture, folder/'original.nknc', folder/'roundtrip.nknc'])
        return {'outcome': 'retained_disposable', 'owned': True, 'receipt': receipt,
                'note': 'Fixture graph and generated files retained for inspection; no rollback or process exit claimed.'}

    def scenario(self, name, contract=None):
        row = {'status': 'completed', 'checks': {}, 'cleanup': {'outcome': 'not_needed'}}
        if name in FIXTURES or name in MUTATING:
            self.require_owned()
        if name in MUTATING:
            row['cleanup'] = {'outcome': 'unknown'}
        try:
            if name in ('two-clients', 'legacy-tools'):
                row['evidence'] = contract
                if name == 'two-clients':
                    row['checks']['correlated_reads'] = check(8, contract['unique_request_ids'])
                else:
                    row['checks']['legacy_schemas'] = check(15, len(contract['legacy_schemas']))
            elif name == 'nc-ambiguity':
                caps = self.call('get_capabilities')
                graph = self.call('inspect_graph', max_nodes=1)
                row['checks']['coverage_disclosed'] = check(True, caps['ok'] and graph['ok'] and
                    caps['data']['license_mode'] == 'noncommercial' and
                    graph['data']['observation']['coverage'] in ('partial', 'unknown'))
                # A dry run cannot edit the scene, even if coverage unexpectedly becomes available.
                denied = self.call('batch_edit', operations=[{'op':'set_knob','node_path':'__Absent__','knob':'label','value':'x'}],
                                   dry_run=True, expected_revision=0)
                row['checks']['revision_refused'] = check('revision_unavailable', (denied.get('error') or {}).get('code'))
            elif name in ('nested-read', 'channel-statistics'):
                from tests.live.inspection_probe import probe
                raw = probe(self.args.pid, self.args.port, client_factory=self.helper_client,
                            statistics=name == 'channel-statistics')
                row['evidence'] = raw
                row['checks'] = {key: check(True, raw['checks'].get(key)) for key in REQUIRED[name]}
                if name in MUTATING:
                    row['cleanup'] = self.retained() if raw['checks'].get('state_preserved') else {'outcome':'unknown'}
            elif name == 'toolset-roundtrip':
                _, facts = self.require_owned()
                library = self.args.fixture.parent/'library'
                if not facts.get('library') or Path(facts['library']).resolve() != library.resolve():
                    raise RuntimeError('Toolsets require the private library beside this fixture')
                if library.exists() and any(library.iterdir()):
                    raise RuntimeError('Toolsets require an empty private library')
                from tests.live.library_probe import probe
                raw = probe(self.args.pid, self.args.port, self.args.fixture.parent, client_factory=self.helper_client)
                row['evidence'] = raw
                row['checks'] = {key: check(True, raw['checks'].get(key)) for key in REQUIRED[name]}
                row['cleanup'] = self.retained()
            elif name in ('two-shot', 'aov-reconstruction'):
                for filename in ('original.nknc', 'shot_1.nknc', 'shot_2.nknc', 'aov-review.png'):
                    if (self.args.fixture.parent/filename).exists():
                        raise RuntimeError('Fresh fixture required; output already exists: '+filename)
                from tests.live.workflow_probe import probe
                raw = probe(self.args.pid, self.args.port, self.args.fixture.parent,
                            client_factory=self.helper_client, scenario=name)
                row['evidence'] = raw
                row['checks'] = {key: check(True, raw['checks'].get(key)) for key in REQUIRED[name]}
                row['cleanup'] = self.retained()
            elif name == 'verified-edit':
                from tests.smoke_mcp import isolated_mutation_probe
                raw = asyncio.run(isolated_mutation_probe(self.args.port, self.instance, self.args.pid, self.args.fixture))
                row['evidence'] = raw
                row['checks']['edit_readback'] = check(True, raw['passed'])
                row['checks']['deleted'] = check('verified_deleted', raw['cleanup'])
                row['cleanup'] = self.retained() if raw['cleanup'] == 'verified_deleted' else {'outcome':'unknown'}
            elif name == 'event-stale-state':
                self.events(row)
            elif name == 'slow-render':
                self.render(row)
        except Exception as exc:
            row['status'] = 'failed'
            row['error'] = str(exc)
        return row

    def events(self, row):
        receipt, before = self.require_owned()
        initial = self.call('get_events')
        revision = initial['data']['revision']
        expected = before['fps'] + 1
        changed = self.call('execute_code', code='assert nuke.root().name()=='+repr(before['path'])+
                            "\nnuke.root()['fps'].setValue("+repr(expected)+")\noutput['fps']=nuke.root()['fps'].value()")
        # An uncertain write is not retried or undone speculatively.
        if not changed['ok'] or changed['data'].get('output', {}).get('fps') != expected:
            raise RuntimeError('FPS write/readback uncertain; retain disposable host')
        observed = self.call('get_events')
        row['checks']['revision_advanced'] = check(True, observed['ok'] and observed['data']['revision'] > revision)
        denied = self.call('batch_edit', operations=[{'op':'set_knob','node_path':'__Absent__','knob':'label','value':'x'}],
                           dry_run=False, expected_revision=revision)
        if self.uncertain:
            raise RuntimeError('Guarded operation uncertain; retain fixture without further mutations')
        reason = 'revision_conflict' if initial['data']['revision_available'] else 'revision_unavailable'
        row['checks']['stale_refused'] = check(reason, (denied.get('error') or {}).get('code'))
        row['coverage'] = 'stale_revision' if reason == 'revision_conflict' else 'degraded_coverage_refusal_only'
        self.require_owned()
        restored = self.call('execute_code', code='assert nuke.root().name()=='+repr(before['path'])+
            "\nassert nuke.root()['fps'].value()=="+repr(expected)+
            "\nnuke.root()['fps'].setValue("+repr(before['fps'])+")\noutput['fps']=nuke.root()['fps'].value()")
        actual = restored.get('data', {}).get('output', {}).get('fps')
        row['checks']['restored'] = check(before['fps'], actual, restored['ok'] and actual == before['fps'])
        row['cleanup'] = {'outcome':'applied' if row['checks']['restored']['passed'] else 'unknown',
                          'expected': before['fps'], 'actual':actual, 'receipt':restored,
                          'scope': 'FPS field only; disposable dirty state retained'}

    def render(self, row):
        # The native fixture must already point its sole Write to a NEW file below the evidence folder.
        facts = self.call('execute_code', code="w=nuke.toNode('MCP_Review')\nassert w is not None and w.Class()=='Write'\noutput['file']=nuke.filename(w,nuke.REPLACE)\noutput['frame']=nuke.frame()\noutput['proxy']=nuke.root().proxy()")
        if not facts['ok']: raise RuntimeError('Render fixture Write unavailable')
        target = Path(facts['data']['output']['file']).resolve()
        if not target.is_relative_to(self.output) or target.exists():
            raise RuntimeError('MCP_Review must resolve to a new file inside --output')
        _, context = self.require_owned()
        planned = facts['data']['output']
        if any(context[key] != planned[key] for key in ('frame','proxy')):
            raise RuntimeError('Render frame/proxy context changed before submission')
        start = time.monotonic()
        accepted = self.client.submit('render', {'write_node':'MCP_Review','first_frame':facts['data']['output']['frame'],
                                                'last_frame':planned['frame'], 'proxy_mode':planned['proxy']}, timeout_ms=120000)
        self.receipts.append(accepted)
        current, polls = accepted, []
        while current['state'] in ('queued','running') and time.monotonic()-start < 125:
            time.sleep(.2)
            current = self.client.status(accepted['request_id'], accepted['server_instance_id'])
            polls.append(current)
            (self.output/'render-status.json').write_text(json.dumps({'accepted':accepted,'polls':polls},indent=2))
        elapsed = time.monotonic()-start
        row['evidence'] = {'accepted':accepted,'final':current,'seconds':elapsed,'target':str(target)}
        row['checks'] = {'completed':check(True,current['ok']),
                         'longer_than_old_timeout':check('>=15 seconds',elapsed,elapsed>=15),
                         'status_observed':check(True,any(p['state']=='running' for p in polls)),
                         'output_exists':check(True,target.is_file() and target.stat().st_size>0)}
        row['cleanup'] = self.retained() if current['state'] not in ('queued','running') and current.get('outcome') not in ('unknown','partial') and not current.get('transport_error') else {'outcome':'unknown'}


def run(args):
    validate_options(args)
    output = prepare_output(args.output)
    selected = selected_scenarios(args)
    results, host, metadata = {}, {}, {}
    native = NativeRun(args, output)
    try:
        metadata = {'timestamp_utc':datetime.now(timezone.utc).isoformat(),
                    'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    'dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
                    'python':sys.version, 'repository':str(ROOT), 'port':args.port,
                    'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        if args.fixture:
            metadata['fixture'] = {'path':str(args.fixture.resolve()),
                'sha256':hashlib.sha256(args.fixture.read_bytes()).hexdigest(), 'pid':args.pid}
        caps = native.call('get_capabilities')
        if not caps['ok']: raise RuntimeError('Capabilities unavailable: '+str(caps.get('error')))
        host = caps['data']; native.instance = caps['server_instance_id']
        metadata['server_instance_id'] = native.instance
        metadata['identity'] = native.identity()[1]
        contract = None
        if set(selected).intersection(('two-clients','legacy-tools')):
            from tests.mcp_contract_probe import probe
            contract = asyncio.run(probe(live=True, port=args.port))
            instances = {r['server_instance_id'] for r in contract['capabilities']}
            if instances != {native.instance}: raise RuntimeError('Stdio clients connected to a different instance')
        for name in selected:
            results[name] = native.scenario(name, contract)
            (output/(name+'.json')).write_text(json.dumps(results[name],indent=2),encoding='utf-8')
        report = aggregate(host, selected, results)
    except Exception as exc:
        report = aggregate(host, selected, results)
        report['passed'] = False; report['error'] = str(exc)
    finally:
        native.client.close()
    report['metadata'] = metadata
    report['cleanup'] = {name:row.get('cleanup', {'outcome':'unknown'}) for name,row in results.items()}
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    result = run(parse_args())
    print(json.dumps({key:result[key] for key in ('passed','qualified','unqualified','commercial_qualified')},indent=2))
    sys.exit(0 if result['passed'] else 1)
