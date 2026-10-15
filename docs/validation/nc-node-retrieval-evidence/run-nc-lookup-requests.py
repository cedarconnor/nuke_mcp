"""Bounded read-only trace through the real bridge in a fresh owned host."""
import json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from nuke_mcp_bridge.client import BridgeClient
BASE = ROOT / '.superpowers/sdd/2026-10-14-nuke-mcp-expansion'
folder = BASE / 'nc-lookup-requests'
folder.mkdir(exist_ok=False)
fixture = folder / 'lookup_fixture.nk'
fixture.write_text((BASE/'nc-lookup-direct/lookup_fixture.nk').read_text())
(folder/'menu.py').write_text((BASE/'task15-events-host/menu.py').read_text())
env = dict(os.environ, NUKE_MCP_REPO=str(ROOT), NUKE_PATH=str(folder)+';'+str(ROOT),
           NUKE_MCP_DISPOSABLE_SESSION='1', NUKE_MCP_BOOTSTRAP_REPORT=str(folder/'started.json'))
command = "$fixture='"+str(fixture)+"'; $p=Start-Process -FilePath 'C:/Program Files/Nuke17.0v4/Nuke17.0.exe' -ArgumentList @('--nc', ('\"'+$fixture+'\"')) -WindowStyle Hidden -PassThru; $p.Id"
launch = subprocess.run(['powershell','-NoProfile','-Command',command],env=env,capture_output=True,text=True,check=True)
pid = int(launch.stdout.strip())
(folder/'pid.json').write_text(json.dumps({'pid':pid}))
print('START',pid,flush=True)
deadline = time.monotonic()+60
while not (folder/'started.json').exists() and time.monotonic()<deadline: time.sleep(.5)
started=json.loads((folder/'started.json').read_text())
assert started['started'] and started['pid']==pid, started
client=BridgeClient(port=19887)
receipts=[]
def call(code):
    receipt=client.call('execute_code',{'code':code})
    receipts.append(receipt)
    (folder/'receipts.json').write_text(json.dumps(receipts,indent=2))
    assert receipt['server_instance_id']==started['instance']
    assert receipt['ok'],receipt
    return receipt['data']['output']
guard="import os\nfrom pathlib import Path\nassert os.getpid()=="+repr(pid)+"\nassert os.environ.get('NUKE_MCP_DISPOSABLE_SESSION')=='1'\nassert Path(nuke.root().name()).resolve()==Path("+repr(str(fixture))+ ").resolve()\n"
deadline=time.monotonic()+60
while time.monotonic()<deadline:
    state=call("output['path']=nuke.root().name()")
    if Path(state['path']).resolve()==fixture.resolve():break
    time.sleep(.5)
else: raise RuntimeError('Fixture not ready; no further probe or close')
batch=call(guard+"output['trace']=[]\nfor index in range(1,15):\n node=nuke.toNode('MCP_Constant')\n output['trace'].append({'index':index,'path':node.fullName() if node is not None else None})\noutput['allNodes']=[node.fullName() for node in nuke.allNodes()]\n")
singles=[]
for index in range(4):
    singles.append(call(guard+"node=nuke.toNode('MCP_Constant')\noutput['path']=node.fullName() if node is not None else None\n"))
result={'pid':pid,'instance':started['instance'],'batch':batch,'separate_requests':singles,'graph_mutations_requested':False}
(folder/'trace.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
call(guard+"from PySide6.QtCore import QTimer\nnuke.root().setModified(False)\nQTimer.singleShot(1000,nuke.scriptExit)\noutput['close_scheduled']=True")
client.close()
deadline=time.monotonic()+60
while time.monotonic()<deadline:
    check=subprocess.run(['powershell','-NoProfile','-Command',f'Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'],capture_output=True,text=True)
    if not check.stdout.strip():
        (folder/'exit.json').write_text(json.dumps({'pid':pid,'exited':True}))
        print('EXIT',pid,flush=True)
        break
    time.sleep(.5)
else: raise RuntimeError('Owned diagnostic host still running: '+str(pid))
