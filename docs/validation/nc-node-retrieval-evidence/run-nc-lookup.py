import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / '.superpowers/sdd/2026-10-14-nuke-mcp-expansion'
menu = (BASE / 'nc-lookup-menu.py').read_text()
for mode in ('direct', 'bridge'):
    folder = BASE / ('nc-lookup-' + mode)
    folder.mkdir(exist_ok=False)
    fixture = folder / 'lookup_fixture.nk'
    fixture.write_text('Root {\n fps 24\n}\nConstant {\n inputs 0\n color {0.25 0.5 0.75 1}\n name MCP_Constant\n}\n')
    (folder / 'menu.py').write_text(menu)
    env = dict(os.environ, NUKE_MCP_REPO=str(ROOT), NUKE_PATH=str(folder)+';'+str(ROOT),
               NUKE_MCP_DISPOSABLE_SESSION='1', NUKE_MCP_DIAGNOSTIC_DIR=str(folder),
               NUKE_MCP_DIAGNOSTIC_MODE=mode)
    command = "$fixture='"+str(fixture)+"'; $p=Start-Process -FilePath 'C:/Program Files/Nuke17.0v4/Nuke17.0.exe' -ArgumentList @('--nc', ('\"'+$fixture+'\"')) -WindowStyle Hidden -PassThru; $p.Id"
    launch = subprocess.run(['powershell','-NoProfile','-Command',command], env=env, capture_output=True,text=True,check=True)
    pid = int(launch.stdout.strip())
    (folder / 'launch.json').write_text(json.dumps({'pid': pid, 'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(), 'menu_sha256': hashlib.sha256((folder/'menu.py').read_bytes()).hexdigest()}, indent=2))
    print('START', mode, pid, flush=True)
    deadline = time.monotonic()+90
    while not (folder/'trace.json').exists() and time.monotonic()<deadline:
        time.sleep(.5)
    data=json.loads((folder/'trace.json').read_text())
    assert data['pid']==pid
    print(json.dumps(data),flush=True)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        check=subprocess.run(['powershell','-NoProfile','-Command',f'Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'],capture_output=True,text=True)
        if not check.stdout.strip():
            (folder/'exit.json').write_text(json.dumps({'pid':pid,'exited':True}))
            print('EXIT',pid,flush=True)
            break
        time.sleep(.5)
    else:
        raise RuntimeError('Owned diagnostic host still running: '+str(pid))
