# Protocol v2 coordinated upgrade

The external MCP server and Nuke add-on must come from the same v2 checkout.
Keep `nuke_mcp_bridge/` beside `nuke_mcp_addon.py`; copying only the add-on is
not sufficient. Set `NUKE_MCP_REPO` to the complete checkout, then restart Nuke
and each external MCP process. The default remains loopback port 9877.
To roll back, restore both components together. There is no legacy wire fallback.

The v2 listener accepts up to eight clients and serializes Nuke API operations
on its main-thread timer. A client disconnect does not prove cancellation.
Keep the returned request and server instance IDs to query operation status;
never automatically repeat a timed-out mutation.

## Operation results and rendering

All 15 existing tools retain their names and arguments. Their MCP responses now
include `structuredContent` receipts and use `isError=true` for failures. Inspect
`state`, `outcome`, `error`, `request_id`, and `server_instance_id`; text alone is
not proof of success. A local transport failure is marked `transport_error` and
does not establish what happened inside Nuke.

Four additional tools are available:

- `get_capabilities()` reports host version/flavor, explicit NC mode, and unknown
  or incomplete observations. It does not enumerate nodes or probe mutations.
- `start_render(write_node, first_frame, last_frame, step=1)` returns immediately
  after admission. Use an explicit Write path. Renders continue beyond the client
  wait limit; cancellation is checked between frames, never inside a native frame.
- `get_operation_status(request_id, server_instance_id)` reads the retained
  receipt without calling Nuke. Receipts are bounded to 4096 / 30 minutes after
  completion. Expiry or host restart means unknown, not permission to replay.
- `cancel_operation(request_id, server_instance_id)` cancels queued work or
  requests cancellation of the owning session's running render.

The legacy `render` waits at most 30 seconds and returns the operation identity
on timeout. Frame/proxy state is restored when the render finishes or stops.
Ordinary queued work expires after 30 seconds by default (maximum 300 seconds).
There is at most one active ordinary request per session and 64 queued requests
across sessions. Status/cancellation remain available while a native frame blocks.

Run `python tests/mcp_contract_probe.py --live --output live-two-client.json`
for a read-only check using two separate stdio MCP processes. Run the same command
without `--live` for a fake host; add `--slow` to exercise a job exceeding 15 seconds.
Native render output and commercial Nuke require separate qualification.

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

For a versioned evidence report, use a new absolute output directory:

```powershell
.\.venv\Scripts\python.exe tests/live/qualify.py --output D:/evidence/nuke-read-only
```

Editing qualification requires an exclusive disposable process, its PID and exact fixture path,
plus both `--mutate --disposable`. See [all scenarios and fixture instructions](docs/VALIDATION.md).
The old `smoke_mcp.py --mutate` command now refuses to edit without those guards.

## Nuke Non-commercial limits

Nuke Non-commercial limits Python retrieval to 10 nodes. Keep test scripts
under that limit. Graph-wide inspection, layout, and render-all operations may
otherwise be incomplete. Disabled nodes and output restrictions also remain in
effect.

Live testing against Nuke NC 17.0v4 also found *intermittent* Python
node-access blackouts: `nuke.allNodes()` sporadically returns an empty list,
`nuke.toNode()` returns `None` for existing nodes, and `nuke.createNode()`
creates the node but returns `None` — even in graphs well under 10 nodes.
Read-only inspection can be repeated, but never replay a mutation after an
ambiguous result. See the "Field notes" section of `nuke-mcp-guidelines.md`.

## Local trusted clients

Milestones 1–5 and Task 14 expose 37 tools, including inspection, toolsets, lifecycle, and shot/AOV workflows. Deploy the matching add-on and
shared package, then restart both Nuke and external MCP processes. Inspect
structured coverage, omissions and per-file status; sampled statistics do not
establish full-image extrema or blackness. See [inspection documentation](docs/inspection.md)
and the [native qualification report](docs/validation/milestone-3.md).

Protocol v2 supports eight simultaneous clients. Upgrade all clients and the
add-on together; an older bridge is incompatible and should be restarted.

The server exposes arbitrary Python execution inside Nuke. Keep the listener on
`localhost`, use trusted MCP clients, save your script before testing, and begin
with disposable `.nknc` projects.
# Toolset library

Set `NUKE_MCP_LIBRARY_ROOT` in the **Nuke host process** to choose the library directory.
The default is `%USERPROFILE%/.nuke/nuke_mcp_toolsets`. Public tools cannot override this root.
Only use trusted libraries: Nuke payloads can execute code. SHA-256 checks detect changed bytes,
not malicious code. Do not allow concurrent untrusted writers to the library.

Each entry has an authoritative schema-v1 JSON manifest referring to an immutable `.nk` or `.nknc`
payload. Interrupted writes and old payloads may leave unreferenced files; listing ignores them.
An overwrite replaces the manifest after staging, preserving the old entry until publication.
Loads preserve observed selection and verify relative topology and a bounded static knob subset.
Unknown outcomes may leave an owned Group; inspect the receipt and never automatically retry.

## Disposable shot workflow sessions

Set `NUKE_MCP_DISPOSABLE_SESSION=1` only in a newly owned disposable Nuke GUI process;
leave it unset for normal artist sessions. Shot application requires a clean script and explicitly
replaces it while generating scripts. The option is off by default and is not needed for planning
or layered Group construction. Use the matching checkout in the host and external MCP processes.
See [workflow contracts](docs/production-workflows.md) and the
[native qualification limits](docs/validation/milestone-5.md). No permanent startup change is required.

## Event polling

Use `subscribe_events` separately for each client and `get_events` to poll. Save the returned cursor
with its server instance ID; reconnect resets subscriptions, and a new host instance resets history.
Check `history_gap` and revision availability before relying on observations. NC returns
`revision_unavailable` for guarded batch edits. Upgrade the external server, add-on and shared package
together, then restart both sides. See [scene event contracts](docs/scene-events.md).

## Coordinated upgrade and rollback

1. Keep the current complete checkout and client configuration as the rollback version. Finish
   or cancel outstanding operations and inspect their receipts; do not treat client disconnection
   as cancellation. Save artist work before restarting its host.
2. Stop the Nuke listener and all external MCP processes. Install a complete new checkout with
   `main.py`, `nuke_mcp_server.py`, `nuke_mcp_addon.py`, `nuke_mcp_bridge/`, startup examples and
   dependency requirements. A copied add-on alone cannot run protocol v2.
3. Create an external Python 3.11 environment and install `requirements.txt`. Point both the
   Nuke plug-in path (`NUKE_MCP_REPO` or `nuke.pluginAddPath`) and every MCP client at the same
   checkout. Preserve unrelated startup code and client entries.
4. Restart Nuke and its listener, then reconnect MCP clients. Python module caches mean copying
   files over a running host is insufficient. Call `get_capabilities` and run the default
   `tests/live/qualify.py` report. Verify protocol 2, intended host version, instance, and schemas.
5. To roll back, stop both sides again, restore both checkout paths and the saved client config,
   restart both sides, and rerun the read-only check. Never mix a v1 client with a v2 listener.
   Old operation IDs belong to the old server instance; preserve their evidence separately.

Task 15 does not change permanent startup automatically. The bundled startup examples already
load the full package and fail clearly when it is missing. Neither upgrade nor rollback modifies
shot outputs or trusted toolset libraries. Back up those artifacts separately before a deployment.
Use explicit `.nknc` paths when saving scripts/toolsets in Non-commercial; do not rename a `.nk`
file to imply conversion. Consult [receipt and evidence semantics](docs/VALIDATION.md) and
[third-party notices](docs/THIRD_PARTY_NOTICES.md).
