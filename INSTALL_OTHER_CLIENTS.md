# Install this patched Nuke MCP in other clients

This repository contains two cooperating components:

1. `nuke_mcp_addon.py` runs inside Nuke and listens on
   `localhost:9877`.
2. `main.py` runs as an MCP stdio server in a normal external Python
   environment and connects to the Nuke add-on.

The Nuke add-on must be running before an MCP tool can operate on Nuke.

## 1. Create the external Python environment

From this repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Do not install FastMCP into Nuke's application Python directories. A virtual
environment keeps MCP dependencies isolated.

## 2. Add the repository to Nuke

Create or update `%USERPROFILE%\.nuke\init.py`:

```python
import nuke

nuke.pluginAddPath(r"D:/nuke_mcp")
```

Create or update `%USERPROFILE%\.nuke\menu.py`:

```python
import nuke_mcp_addon
```

Change `D:/nuke_mcp` if the repository is stored elsewhere.
Ready-to-copy versions of these files are included in `nuke_startup/`. They
also honor a `NUKE_MCP_REPO` environment variable, which can point to a
different clone location without editing the files.

Restart Nuke normally. Open **Nuke > NukeMCP > Show Panel**, then click
**Start Server**. The panel should report `Running on port 9877`.

Do not launch Nuke with `--safe`; safe mode disables user Python
customizations.

## 3. Configure an MCP client

Most desktop MCP clients accept the following standard stdio shape:

```json
{
  "mcpServers": {
    "nuke": {
      "command": "D:\\nuke_mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "D:\\nuke_mcp\\main.py"
      ]
    }
  }
}
```

Use absolute paths. The exact location of `mcpServers` varies by client.

### Codex CLI

```powershell
codex mcp add nuke -- D:\nuke_mcp\.venv\Scripts\python.exe D:\nuke_mcp\main.py
codex mcp get nuke
codex mcp list
```

Start a new Codex task after registration if an already-open task does not show
the new tools.

### Claude Desktop

Place the standard JSON block above inside Claude Desktop's
`claude_desktop_config.json`, preserving any existing `mcpServers` entries,
then fully restart Claude Desktop.

### Other MCP-capable LLM applications

Use the same command and argument pair:

- command: `D:\nuke_mcp\.venv\Scripts\python.exe`
- first argument: `D:\nuke_mcp\main.py`
- transport: stdio

If the client has separate fields for working directory, set it to
`D:\nuke_mcp`.

## 4. Verify in stages

1. Start Nuke and start the NukeMCP panel server.
2. Confirm port 9877 is listening:

   ```powershell
   Get-NetTCPConnection -LocalPort 9877 -State Listen
   ```

3. Confirm the MCP client lists the Nuke tools.
4. In an empty Nuke script, call `get_script_info`.
5. Create one `Grade` node, inspect it, and delete it.

Registration alone does not prove that the Nuke-side bridge is running.

Port `9877` is used by this compatibility branch because Blender MCP commonly
uses `9876` on the same workstation. To choose another port, set the same
`NUKE_MCP_PORT` environment variable for both Nuke and the external MCP
process.

For Nuke-side diagnostics, set `NUKE_MCP_DEBUG_LOG` to an absolute log-file
path before launching Nuke. Logging is disabled by default.

This repository also includes an automated read-only end-to-end check:

```powershell
.\.venv\Scripts\python.exe .\tests\smoke_mcp.py
```

It starts the stdio MCP process, enumerates the tools, calls
`get_script_info`, and verifies that the response came from live Nuke.

To additionally test reversible node editing in an empty or disposable script:

```powershell
.\.venv\Scripts\python.exe .\tests\smoke_mcp.py --mutate
```

This creates, inspects, and deletes one temporary `Grade` node.

## Nuke Non-commercial limits

Nuke Non-commercial limits Python retrieval to 10 nodes. Keep test scripts
under that limit. Graph-wide inspection, layout, and render-all operations may
otherwise be incomplete. Disabled nodes and output restrictions also remain in
effect.

The server exposes arbitrary Python execution inside Nuke. Keep the listener on
`localhost`, use trusted MCP clients, save your script before testing, and begin
with disposable `.nknc` projects.
