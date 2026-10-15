"""Temporary read-only diagnostic, launched only in a fresh owned fixture."""
import json
import os
import time
import traceback
from pathlib import Path

import nuke
from PySide6.QtCore import QTimer

folder = Path(os.environ['NUKE_MCP_DIAGNOSTIC_DIR']).resolve()
fixture = folder / 'lookup_fixture.nk'
result = {'pid': os.getpid(), 'mode': os.environ['NUKE_MCP_DIAGNOSTIC_MODE'],
          'version': nuke.NUKE_VERSION_STRING, 'nc': nuke.env.get('nc'),
          'fixture': str(fixture), 'trace': []}
assert os.environ['NUKE_MCP_DISPOSABLE_SESSION'] == '1'
if result['mode'] == 'bridge':
    import nuke_mcp_addon
    assert Path(nuke_mcp_addon.__file__).resolve().parent == Path(os.environ['NUKE_MCP_REPO']).resolve()
    nuke._lookup_server = nuke_mcp_addon.NukeMCPServer(port=19887)
    nuke._lookup_server.start()
    result['instance'] = nuke._lookup_server.runtime.registry.instance_id

deadline = time.monotonic() + 60

def finish():
    (folder / 'trace.json').write_text(json.dumps(result, indent=2))
    assert os.getpid() == result['pid']
    assert Path(nuke.root().name()).resolve() == fixture
    nuke.root().setModified(False)
    QTimer.singleShot(1000, nuke.scriptExit)

def run():
    if Path(nuke.root().name()).resolve() != fixture:
        if time.monotonic() < deadline:
            QTimer.singleShot(250, run)
            return
        result['error'] = 'Exact fixture not ready; no probe or close performed'
        (folder / 'trace.json').write_text(json.dumps(result, indent=2))
        return
    try:
        for index in range(1, 15):
            node = nuke.toNode('MCP_Constant')
            result['trace'].append({'call': 'toNode', 'index': index,
                                    'path': node.fullName() if node is not None else None})
        result['trace'].append({'call': 'allNodes', 'paths': [node.fullName() for node in nuke.allNodes()]})
        if result['mode'] == 'bridge':
            result['events'] = nuke._lookup_server.runtime.events.snapshot()
    except Exception:
        result['error'] = traceback.format_exc()
    finish()

QTimer.singleShot(500, run)
