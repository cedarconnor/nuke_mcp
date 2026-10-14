"""Bounded native event smoke test in a newly owned disposable GUI fixture."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from nuke_mcp_bridge.client import BridgeClient


def probe(pid, port, directory):
    folder=Path(directory).resolve()
    client=BridgeClient(port=port)
    report={'passed':False,'checks':{},'receipts':{}}
    original=None
    def call(label,command,**params):
        result=client.call(command,params)
        report['receipts'][label]=result
        return result
    try:
        identity=call('identity','execute_code',code="import os\noutput['pid']=os.getpid()\noutput['path']=nuke.root().name()\noutput['disposable']=os.environ.get('NUKE_MCP_DISPOSABLE_SESSION')\noutput['fps']=nuke.root()['fps'].value()\noutput['frame']=nuke.frame()")
        facts=identity['data'].get('output',{})
        if (facts.get('pid')!=pid or facts.get('disposable')!='1' or
                Path(facts.get('path','')).resolve()!=folder/'events_fixture.nk'):
            raise RuntimeError('Refusing host other than the owned event fixture')
        original=facts
        caps=call('capabilities','get_capabilities')
        report['checks']['nc_revision_unavailable']=caps['ok'] and not caps['data']['scene_events']['revision_available']
        subscribed=call('subscribe','subscribe_events',event_types=['knob_changed','frame_changed'])
        initial=call('initial_events','get_events')
        if not subscribed['ok'] or not initial['ok']:raise RuntimeError('Event tools unavailable')
        cursor=initial['data']['next_sequence']
        revision=initial['data']['revision']
        denied=call('revision_edit','batch_edit',operations=[dict(op='set_knob',node_path='__Absent__',knob='gain',value=1)],
                    dry_run=False,expected_revision=revision)
        report['checks']['revision_edit_refused']=not denied['ok'] and denied['error']['code']=='revision_unavailable' and denied['outcome']=='not_started'
        changed=call('root_change','execute_code',code="nuke.root()['fps'].setValue("+repr(facts['fps']+1)+")\nnuke.frame("+repr(facts['frame']+1)+")\noutput['fps']=nuke.root()['fps'].value()\noutput['frame']=nuke.frame()")
        report['checks']['root_change']=changed['ok'] and changed['data']['output']['fps']==facts['fps']+1
        # Read-only polls give Root updateUI a chance to observe the changed frame.
        deadline=time.monotonic()+3
        seen=[]
        while time.monotonic()<deadline:
            polled=call('changed_events','get_events',after_sequence=cursor)
            if not polled['ok']:break
            seen.extend(polled['data']['events']);cursor=polled['data']['next_sequence']
            if any(x['type']=='frame_changed' for x in seen):break
            time.sleep(.05)
        report['events']=seen
        report['checks']['knob_event_attributed']=any(x['type']=='knob_changed' and x.get('knob')=='fps' and x['request_id']==changed['request_id'] for x in seen)
        report['checks']['frame_event_sampled']=any(x['type']=='frame_changed' and x.get('frame')==facts['frame']+1 for x in seen)
        report['checks']['revision_advanced']=polled['ok'] and polled['data']['revision']>revision
        report['checks']['no_sensitive_payload']=all('value' not in x and 'callback' not in x for x in seen)
    except Exception as exc:
        report['error']=str(exc)
    finally:
        if original:
            # Restore only our two explicitly changed fields, and only on the owned script.
            restored=call('restore','execute_code',code="import os\nassert os.getpid()=="+repr(pid)+"\nassert nuke.root().name()=="+repr(original['path'])+"\nnuke.root()['fps'].setValue("+repr(original['fps'])+")\nnuke.frame("+repr(original['frame'])+")\noutput['fps']=nuke.root()['fps'].value()\noutput['frame']=nuke.frame()")
            report['checks']['restored']=restored['ok'] and restored['data']['output']['fps']==original['fps'] and restored['data']['output']['frame']==original['frame']
        client.close()
    report['passed']=not report.get('error') and len(report['checks'])==8 and all(report['checks'].values())
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--port',type=int,default=19877)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=probe(args.pid,args.port,args.directory)
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'checks':result['checks'],'error':result.get('error')},indent=2))
    sys.exit(0 if result['passed'] else 1)
