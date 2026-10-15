"""Opt-in mutating qualification; only a newly owned disposable fixture session."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from nuke_mcp_bridge.client import BridgeClient


def probe(pid,port,directory,client_factory=BridgeClient):
    client=client_factory(port=port)
    report={'passed':False,'receipts':{},'checks':{}}
    def call(label,command,**params):
        receipt=client.call(command,params)
        report['receipts'][label]=receipt
        return receipt
    try:
        identity=call('identity','execute_code',code="import os\noutput['pid']=os.getpid()\noutput['path']=nuke.root().name()\noutput['selection']=sorted(n.fullName() for n in nuke.selectedNodes())")
        before=identity['data'].get('output',{})
        if before.get('pid')!=pid or not before.get('path','').replace('\\','/').endswith('/library_fixture.nk'):
            raise RuntimeError('Not the owned disposable library fixture')
        dry=call('settings_dry','set_project_settings',settings={'fps':30.})
        report['checks']['dry_run']=dry['ok'] and dry['outcome']=='not_started'
        changed=call('settings_apply','set_project_settings',settings={'fps':30.,'first_frame':1,'last_frame':3,
                      'format':{'width':4,'height':4,'pixel_aspect':1.}},dry_run=False)
        report['checks']['settings']=changed['ok']
        saved=call('toolset_save','save_toolset',node_paths=['root.MCP_Source','root.MCP_Grade'],name='roundtrip')
        report['checks']['toolset_save']=saved['ok']
        listing=call('toolset_list','list_toolsets')
        report['checks']['library_listing']=listing['ok'] and len(listing['data']['entries'])==1
        if saved['ok']:
            loaded=call('toolset_load','load_toolset',name='roundtrip',group_name='MCP_Imported',position=[300,100])
            report['checks']['toolset_load']=loaded['ok']
            # No mutation replay even if creation or readback was uncertain.
            if loaded['ok']:
                observed=call('roundtrip_readback','execute_code',code="g=nuke.toNode('MCP_Imported.MCP_Grade')\ns=nuke.toNode('MCP_Imported.MCP_Source')\noutput['known_label']=g['label'].value() if g else None\noutput['connected']=bool(g and s and g.input(0)==s)")
                report['checks']['known_knob_topology']=observed['ok'] and observed['data']['output']=={'known_label':'roundtrip','connected':True}
        selected=call('selection','execute_code',code="output['selection']=sorted(n.fullName() for n in nuke.selectedNodes())")
        report['checks']['selection']=selected['ok'] and selected['data']['output'].get('selection')==before['selection']
        path=str(Path(directory).resolve()/'roundtrip.nknc')
        file_saved=call('script_save','save_script',path=path)
        report['checks']['script_save']=file_saved['ok']
        if file_saved['ok']:
            collision=call('collision','save_script',path=path)
            report['checks']['collision']=not collision['ok'] and collision['error']['code']=='file_exists'
            current=call('save_current','save_script')
            report['checks']['save_current']=current['ok']
            reopened=call('reopen','open_script',path=path)
            report['checks']['saved_clean_reopen']=reopened['ok']
        report['passed']=len(report['checks'])==11 and all(report['checks'].values())
    except Exception as exc:report['error']=str(exc)
    finally:client.close()
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--pid',type=int,required=True)
    p.add_argument('--port',type=int,default=19877)
    p.add_argument('--directory',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    result=probe(args.pid,args.port,args.directory)
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'checks':result['checks'],'error':result.get('error')},indent=2))
