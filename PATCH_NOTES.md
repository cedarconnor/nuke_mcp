# Compatibility patch notes

This branch contains a small compatibility and portability patch on top of
`dughogan/nuke_mcp`.

## Why the patch is needed

### Nuke main-thread dispatch

The add-on accepts socket requests on a Python worker thread. The upstream code
called Nuke's Python API directly from that thread. Foundry documents that calls
from a child thread back into the Nuke session must be dispatched through
`nuke.executeInMainThread()` or `nuke.executeInMainThreadWithResult()`.

`nuke_mcp_addon.py` now:

1. receives the socket request on the worker thread;
2. dispatches the selected handler with
   `nuke.executeInMainThreadWithResult()`;
3. captures exceptions in the dispatched callable; and
4. returns the handler result to the socket client.

This reduces the risk of UI hangs, crashes, and inconsistent node operations.

### MCP stdio safety

MCP stdio transports reserve standard output for protocol messages. The
upstream `main.py` printed startup diagnostics to standard output and waited for
keyboard input after an import error. Those behaviors can corrupt or hang an
MCP client connection.

`main.py` is now a minimal entry point. Runtime logging from
`nuke_mcp_server.py` goes to standard error through Python logging.

### Reproducible dependency

`requirements.txt` pins `fastmcp==2.14.7`, the FastMCP major-version API used by
this repository and tested by this installation.

### Dedicated Nuke bridge port

The upstream bridge defaults to port `9876`. That port was already occupied by
Blender MCP on the test workstation. Both applications enabled socket address
reuse on Windows, so a client could connect successfully but send its Nuke
request to Blender and then time out.

This branch defaults both bridge components to `9877`. The
`NUKE_MCP_PORT` environment variable can override the port when it is set to
the same value for Nuke and the external MCP process.

## Nuke Non-commercial behavior

This patch does not bypass any Foundry license restriction.

- Use it only for personal, educational, and other license-compliant testing.
- Nuke Non-commercial restricts Python node enumeration to the first 10 nodes.
- Tools that call `nuke.allNodes()` can therefore return or operate on only the
  first 10 nodes.
- Direct operations addressed by node name generally do not need full graph
  enumeration.
- Disabled Non-commercial nodes, including Primatte, remain unavailable even
  though their names appear in this server's allowlist.
- Non-commercial output and file-format restrictions still apply.

Recommended test scripts contain fewer than 10 nodes.

## Files changed

- `nuke_mcp_addon.py`: dispatch Nuke API handlers to the main thread.
- `nuke_mcp_addon.py` and `nuke_mcp_server.py`: use a dedicated configurable
  bridge port (`9877` by default).
- `main.py`: remove stdout diagnostics and interactive error pause.
- `requirements.txt`: pin the tested FastMCP dependency.
- `.gitignore`: exclude the local virtual environment and generated files.
- `nuke_startup/`: reusable Nuke `init.py` and `menu.py` startup files.
- `tests/smoke_mcp.py`: read-only stdio-to-Nuke end-to-end verification.
- `INSTALL_OTHER_CLIENTS.md`: reusable installation and MCP-client examples.

## Upstream reference

- Repository: <https://github.com/dughogan/nuke_mcp>
- Patched from upstream commit: `761ea9e45cb8816a85e0a0b55a132d7b454affe3`
- Local compatibility branch: `codex/nuke-nc-compat`
