"""Opt-in native inspection/diagnostic evidence for inspection_fixture.nk only."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from nuke_mcp_bridge.client import BridgeClient


def probe(pid, port):
    client = BridgeClient(port=port)
    report = {'passed':False, 'checks':{}, 'receipts':{}}
    def call(label, command, **params):
        receipt = client.call(command,params)
        report['receipts'][label] = receipt
        if not receipt['ok']:
            report.setdefault('errors', {})[label] = receipt['error']
            return None
        return receipt['data']
    snapshot = '''import os
output['pid'] = os.getpid()
output['script'] = nuke.root().name()
output['frame'] = nuke.frame()
output['proxy'] = nuke.root().proxy()
output['selection'] = sorted(n.fullName() for n in nuke.selectedNodes())
'''
    try:
        initial = call('before','execute_code',code=snapshot)
        if initial is None: raise RuntimeError('Initial fixture state is unavailable')
        before = initial['output']
        if before['pid'] != pid or not before['script'].replace('\\','/').endswith('/inspection_fixture.nk'):
            raise RuntimeError('Refusing a host other than the owned inspection fixture')
        graph = call('graph','inspect_graph')
        paths = {n['path'] for n in graph['nodes']} if graph else set()
        report['checks']['nested_paths'] = {'GroupA.SameName','GroupB.SameName','MCP_Constant','MCP_Ramp','MCP_MissingRead'} <= paths
        report['checks']['nc_coverage_label'] = bool(graph and graph['observation']['coverage'] in ('partial','unknown'))
        bounded = call('bounded','inspect_graph',max_nodes=1)
        report['checks']['truncation'] = bool(bounded and bounded['truncated'] and len(bounded['nodes'])==1)
        reads = call('reads','inspect_reads',node_paths=['root.MCP_MissingRead'])
        report['checks']['read_identity'] = bool(reads and len(reads['reads'])==1 and reads['reads'][0]['path']=='MCP_MissingRead')
        sequence = call('sequence','validate_reads',first_frame=1,last_frame=3,node_paths=['root.MCP_MissingRead'])
        report['checks']['missing_sequence'] = bool(sequence and sequence['checked_paths']>=3 and sequence['missing_paths']==sequence['requested_paths'] and sequence['unknown_paths']==0)
        constant = call('constant','sample_channel_statistics',node_path='root.MCP_Constant',channels=['rgba'],frame=2,max_samples_per_channel=4)
        actual = {s['channel']:s['mean'] for s in constant['statistics']} if constant else {}
        report['checks']['constant_signal'] = bool(constant and constant['complete'] and all(
            actual.get(c) is not None and abs(actual[c]-v)<=1e-6 for c,v in
            {'rgba.red':.25,'rgba.green':.5,'rgba.blue':.75,'rgba.alpha':1.}.items()))
        ramp = call('ramp','sample_channel_statistics',node_path='root.MCP_Ramp',channels=['rgba.red'],frame=3,max_samples_per_channel=4)
        report['checks']['ramp_signal'] = bool(ramp and ramp['complete'] and abs(ramp['statistics'][0]['mean']-.5)<=1e-6)
        report['checks']['sample_limits_disclosed'] = bool(constant and ramp and not constant['sampling']['samples_every_pixel'] and not ramp['sampling']['samples_every_pixel'])
        after = call('after','execute_code',code=snapshot)
        report['checks']['state_preserved'] = bool(after and before==after['output'])
        report['passed'] = len(report['checks'])==9 and all(report['checks'].values()) and not report.get('errors')
    except Exception as exc:
        report['error'] = str(exc)
    finally: client.close()
    return report


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--port',type=int,default=19877)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=probe(args.pid,args.port)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='receipts'},indent=2))
    sys.exit(0 if result['passed'] else 1)
