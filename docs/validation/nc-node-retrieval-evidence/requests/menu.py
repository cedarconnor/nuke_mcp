import json, os, traceback
from pathlib import Path
import nuke
try:
    import nuke_mcp_addon
    assert Path(nuke_mcp_addon.__file__).resolve().parent == Path(os.environ['NUKE_MCP_REPO']).resolve()
    nuke._task15_server = nuke_mcp_addon.NukeMCPServer(port=19887)
    nuke._task15_server.start()
    result={'started':True,'pid':os.getpid(),'instance':nuke._task15_server.runtime.registry.instance_id}
except Exception:
    result={'started':False,'error':traceback.format_exc()}
Path(os.environ['NUKE_MCP_BOOTSTRAP_REPORT']).write_text(json.dumps(result,indent=2))
