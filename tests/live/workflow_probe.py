"""Mutating workflow qualification, requiring an owned disposable host and output root."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from nuke_mcp_bridge.client import BridgeClient


def probe(pid,port,directory):
    client=BridgeClient(port=port);folder=Path(directory).resolve()
    report={'passed':False,'receipts':{},'checks':{}}
    def call(label,command,**params):
        receipt=client.call(command,params);report['receipts'][label]=receipt;return receipt
    try:
        identity=call('identity','execute_code',code="import os\noutput['pid']=os.getpid()\noutput['path']=nuke.root().name()\noutput['disposable']=os.environ.get('NUKE_MCP_DISPOSABLE_SESSION')\noutput['nodes']=[n.fullName() for n in nuke.allNodes()]")
        data=identity['data'].get('output',{})
        if data.get('pid')!=pid or data.get('disposable')!='1' or not data.get('path','').replace('\\','/').endswith('/workflow_fixture.nk'):
            raise RuntimeError('Refusing host other than the owned workflow fixture')
        facts=call('facts','execute_code',code="r=nuke.toNode('MCP_Base')\nw=nuke.toNode('MCP_Review')\nassert r is not None and w is not None\noutput['plate']=r['file'].value()\noutput['plate_colorspace']=r['colorspace'].value()\noutput['write']={k:w[k].value() for k in ['file_type','datatype','compression','colorspace','channels']}\noutput['color']={'colorManagement':nuke.root()['colorManagement'].value()}")
        if not facts['ok']:raise RuntimeError('Fixture facts unavailable; no mutation attempted')
        f=facts['data']['output']
        choices=call('fixture_color_options','execute_code',code="r=nuke.toNode('MCP_Base')\nw=nuke.toNode('MCP_Review')\nassert r is not None and w is not None\noutput['read']=r['colorspace'].values()\noutput['write']=w['colorspace'].values()")
        if not choices['ok'] or any('linear' not in choices['data']['output'][key] for key in ('read','write')):
            raise RuntimeError('Explicit linear fixture colorspace unavailable; no substitution')
        f['plate_colorspace']='linear';f['write']['colorspace']='linear'
        original=call('save_original','save_script',path=str(folder/'original.nknc'))
        if not original['ok']:raise RuntimeError('Could not establish saved-clean original; no workflow attempted')
        shots=[]
        for index in (1,2):
            shots.append({'shot_id':'shot_'+str(index),'script_path':str(folder/('shot_'+str(index)+'.nknc')),
                'plates':[{'path':f['plate'],'colorspace':f['plate_colorspace'],'first':1,'last':2}],
                'frame_range':{'work_first':1,'cut_in':1,'cut_out':2,'work_last':2},
                'fps':{'numerator':24,'denominator':1},'format':{'width':4,'height':4,'pixel_aspect':1.},
                'color_settings':f['color'],'write':dict(f['write'],path='[file dirname [value root.name]]/shot_'+str(index)+'.%04d.exr')})
        manifest={'schema_version':1,'output_root':str(folder),'shots':shots}
        report['shot_manifest']=manifest
        plan=call('shot_plan','plan_shot_setup',manifest=manifest)
        report['checks']['shot_plan']=plan['ok']
        if plan['ok']:
            applied=call('shot_apply','apply_shot_setup',manifest=manifest,plan_digest=plan['data']['digest'])
            report['checks']['two_shots']=applied['ok'] and len(applied['data'].get('completed',[]))==2
            report['checks']['original_restored']=applied['data'].get('restoration',{}).get('ok',False)
            if not report['checks']['original_restored']:raise RuntimeError('Restoration unavailable; stop native fixture')
        comp={'schema_version':1,'group_name':'MCP_AOV','layers':[
            {'id':'base','source_node_path':'root.MCP_Base','channel_layer':'rgba'},
            {'id':'light','source_node_path':'root.MCP_Light','channel_layer':'rgba','operation':'plus'}]}
        report['comp_manifest']=comp
        plan=call('comp_plan','plan_layered_comp',manifest=comp)
        report['checks']['comp_plan']=plan['ok']
        if plan['ok']:
            built=call('comp_build','build_layered_comp',manifest=comp,plan_digest=plan['data']['digest'])
            report['checks']['comp_build']=built['ok']
            if built['ok']:
                numeric=call('numeric','execute_code',code="g=nuke.toNode('MCP_AOV')\na=nuke.toNode('MCP_Base')\nb=nuke.toNode('MCP_Light')\nassert all(x is not None for x in (g,a,b))\noutput['actual']=[g.sample('rgba.'+k,2,2) for k in ('red','green','blue','alpha')]\noutput['expected']=[a.sample('rgba.'+k,2,2)+b.sample('rgba.'+k,2,2) for k in ('red','green','blue','alpha')]")
                report['checks']['numeric']=numeric['ok'] and all(abs(a-b)<1e-5 for a,b in zip(numeric['data']['output']['actual'],numeric['data']['output']['expected']))
                # Existing owned fixture Write; no speculative node creation or retry.
                preview=str(folder/'aov-review.png')
                rendered=call('preview','execute_code',code="w=nuke.toNode('MCP_Review')\ng=nuke.toNode('MCP_AOV')\nassert w is not None and g is not None\nw.setInput(0,g)\nw['file'].setValue("+repr(preview)+")\nw['file_type'].setValue('png')\nnuke.execute(w,1,1)\noutput['preview']="+repr(preview))
                report['checks']['preview']=rendered['ok'] and Path(preview).is_file()
        report['passed']=len(report['checks'])==7 and all(report['checks'].values())
    except Exception as exc:report['error']=str(exc)
    finally:client.close()
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pid',required=True,type=int)
    parser.add_argument('--port',default=19877,type=int);parser.add_argument('--directory',required=True)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    result=probe(args.pid,args.port,args.directory)
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'checks':result['checks'],'error':result.get('error')},indent=2))
