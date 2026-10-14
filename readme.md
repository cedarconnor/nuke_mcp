# Nuke MCP

Control Foundry Nuke from an MCP-compatible assistant. Inspect scripts and nodes, edit connections and parameters, organize graphs, and submit renders through a local bridge.

**Milestones 1–3 are implemented:** protocol v2 supports up to eight connected clients, runs Nuke API work on the main thread, and returns structured operation receipts. The existing 15 tools remain available alongside nine capability, operation-status, batch-edit, inspection, and diagnostic tools. Native qualification limits are recorded below.

Live two-client communication has been verified on **Windows with Nuke Non-commercial 17.0v4 and external Python 3.11**. See the [validation report](docs/validation/milestone-1.md) for evidence and qualification limits.

## Quick start

### 1. Install the external server

You need Nuke with a GUI and bundled PySide6 or PySide2, external Python 3.11, and an MCP client that supports stdio servers.

```powershell
git clone https://github.com/cedarconnor/nuke_mcp.git D:/nuke_mcp
cd D:/nuke_mcp
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use your existing checkout if you already cloned the repository. Adjust the paths below if you install elsewhere. Dependencies stay in the external virtual environment; do not install them into Nuke's application directories. [requirements.txt](requirements.txt) pins FastMCP to `2.14.7`.

### 2. Load the add-on in Nuke

Add this to `%USERPROFILE%/.nuke/init.py`, preserving any existing startup code:

```python
import nuke
nuke.pluginAddPath(r"D:/nuke_mcp")
```

Add this to `%USERPROFILE%/.nuke/menu.py`:

```python
import nuke_mcp_addon
```

Restart Nuke normally, open **Nuke > NukeMCP > Show Panel**, and click **Start Server**. The panel should show `Running on port 9877`.

Keep the complete checkout available to Nuke. The add-on requires the adjacent `nuke_mcp_bridge/` package; copying only `nuke_mcp_addon.py` is insufficient. The supplied [startup examples](nuke_startup/init.py) also support `NUKE_MCP_REPO` for choosing the repository location.

### 3. Configure your MCP client

Register `main.py` as a stdio server using the virtual environment's Python executable. For clients accepting an `mcpServers` configuration:

```json
{
  "mcpServers": {
    "nuke": {
      "command": "D:/nuke_mcp/.venv/Scripts/python.exe",
      "args": ["D:/nuke_mcp/main.py"]
    }
  }
}
```

Use absolute paths and preserve existing server entries. If your client asks for a working directory, use `D:/nuke_mcp`. Restart or reconnect the client after changing its configuration. Each client launches its own external server process; they can share the same Nuke listener.

Call `get_capabilities` first, then `get_script_info`. Tool discovery alone does not establish that Nuke is connected.

See [installation details](INSTALL_OTHER_CLIENTS.md) for additional client setup and diagnostics.

## Tools

The server exposes **30 tools**. The client supplies tool arguments; MCP context is handled internally.

| Tool | Purpose |
| --- | --- |
| `list_toolsets` | List verified entries in the configured trusted library. |
| `save_toolset` | Publish node paths and metadata with a payload digest. |
| `load_toolset` | Paste a verified trusted payload into a newly owned Group. |
| `open_script` | Open an absolute script path, refusing unsaved work unless discard is explicit. |
| `save_script` | Save the current target or an explicit save-as path with collision protection. |
| `set_project_settings` | Preflight or apply FPS, frame range, format and exact color enum options. |
| `batch_edit` | Preflight or apply up to 100 typed knob, connection, and position edits; dry-run by default. |
| `get_capabilities` | Report host version, flavor, observable license mode, and supported tool groups. |
| `get_script_info` | Inspect current script settings and observable nodes. |
| `get_node_info` | Inspect a node by `node_name`. |
| `inspect_graph` | Inspect bounded nested graph paths, indexed connections, knob values and omissions. |
| `inspect_reads` | Inspect Read paths, format, colorspace, channels/layers and multipart choices. |
| `validate_reads` | Check up to 10000 frame/view paths, separating missing files from unknown evaluation. |
| `sample_channel_statistics` | Measure a filtered grid on up to 16 channels, with finite statistics and frame restoration. |
| `create_node` | Create a `node_type`, with optional name, position, inputs, and parameters. |
| `modify_node` | Update a named node's parameters, position, or inputs. |
| `delete_node` | Delete a named node. |
| `position_node` | Set a named node's `x` and `y` position. |
| `connect_nodes` | Connect `output_node` to an input of `input_node`. |
| `auto_layout_nodes` | Arrange all observable nodes or selected nodes. |
| `organize_node_graph` | Organize nodes by category in a vertical or horizontal layout. |
| `create_workflow_template` | Build a `keying`, `color_correction`, `lens_distortion`, or `3d_simple` template. |
| `set_frames` | Set the project frame range or current frame. |
| `create_viewer` | Create a Viewer, optionally connected to a node. |
| `viewer_playback` | Play, stop, or step the active Viewer. |
| `render` | Render with a bounded client wait; accepts `frame_range`, `write_node`, and `proxy_mode`. |
| `start_render` | Queue a render using `write_node`, `first_frame`, `last_frame`, and optional `step`. |
| `get_operation_status` | Query a retained receipt using `request_id` and `server_instance_id`. |
| `cancel_operation` | Cancel queued work or request cancellation of the owning session's running render. |
| `execute_nuke_code` | Execute Python in Nuke. This is unrestricted access for trusted local clients. |

Typed node edits validate and read back changes; see [verified edits and batch schema](docs/verified-edits.md). [Inspection and diagnostics](docs/inspection.md) report coverage and sampling limits explicitly. [Toolsets and lifecycle](docs/toolsets-and-lifecycle.md) documents library setup, trusted payloads, save/open guards, and project settings. NC cannot guarantee complete graph observation. Templates, auto-layout, and organization remain legacy workflows and return an explicit unverified outcome. Consult [workflow guidelines and NC field notes](nuke-mcp-guidelines.md) before building larger graphs.

## Operation results and rendering

Tool responses include readable text and a `structuredContent` result. Check the structured result when deciding whether an operation completed:

- `request_id`, `client_session_id`, and `server_instance_id` identify the operation and host.
- `state` is `queued`, `running`, `completed`, `failed`, `cancelled`, or `expired`.
- `outcome` describes mutation evidence: `not_started`, `applied`, `partial`, `rolled_back`, or `unknown`. Successful read-only operations use `not_started` because they make no mutation.
- `error`, `warnings`, and `observation` provide failure and visibility details. Compound calls retain their individual `operation_receipts`.
- Failed operations use MCP `isError=true`. An accepted `queued` or `running` operation is not an MCP error, but it is not completed success either.

A local connection failure is marked `transport_error`; it is not a host-issued receipt. **Never automatically repeat a mutation after a timeout, disconnect, or uncertain result.** Query its status using the original IDs instead.

### Submit and inspect a render

These are MCP tool-call examples, not functions to paste into Nuke's Script Editor. Configure an existing Write node's output path and settings first.

Call `start_render` with:

```json
{"write_node": "Write1", "first_frame": 1001, "last_frame": 1010, "step": 1}
```

Keep the returned `request_id` and `server_instance_id`, then call `get_operation_status` with those values:

```json
{"request_id": "<returned request UUID>", "server_instance_id": "<returned host UUID>"}
```

Pass the same arguments to `cancel_operation` from the owning client session to request cancellation. Cancellation is checked between native frames; a frame already executing cannot be safely interrupted by the bridge. Temporary frame and proxy state is restored when the job finishes or stops.

The legacy `render` tool retains its arguments and a bounded wait of about 30 seconds. A timeout does not establish that rendering stopped. `start_render` returns after admission so the client can poll while a longer render continues. Specify an explicit Write node in NC; render-all is refused because node enumeration may be incomplete.

### Scheduling and receipt limits

- Up to eight connected clients and 64 queued host operations.
- One queued or running ordinary operation per client session; status and cancellation use a separate control path.
- Ordinary admission deadlines default to 30 seconds, with a 300-second maximum. An admitted render can continue beyond the client wait limit once started.
- Up to 4096 receipts, retained for at most 30 minutes after completion and subject to capacity eviction. Active work is not evicted.

`receipt_expired_or_unknown` and `instance_changed` do not authorize replay. Deduplication only applies to retained request IDs in the same host instance.

## Configuration and upgrades

| Setting | Where it applies | Purpose |
| --- | --- | --- |
| `NUKE_MCP_PORT` | Nuke and external MCP processes | Choose a matching loopback port; default `9877`. The Nuke panel also exposes the port. |
| `NUKE_MCP_REPO` | Supplied Nuke startup scripts | Point to the complete checkout; default `D:/nuke_mcp`. |
| `NUKE_MCP_DEBUG_LOG` | Nuke process | Optional absolute path for add-on diagnostics; disabled by default. |

Upgrade the external server, add-on, and shared package together, then restart Nuke and all external MCP processes. Protocol v2 has no legacy wire fallback. Roll back both sides together if needed.

The listener is restricted to loopback. Use trusted local clients: the bridge can change scripts, render files, and execute arbitrary Python. Remote access and remote authentication are outside this release's scope.

## Verification and known limits

Milestone 4 has **137 passing offline tests**, including Windows junction containment, and passing offline and live two-client stdio probes exposing all 30 tools. Native NC 17.0v4 verified project settings, save-as, save-current, collision refusal, and saved-clean reopening. Native toolset round-trip remains **unqualified**: `nodeCopy` returned false after writing a payload; the entry was not published and the operation was not replayed. See the [Milestone 4 validation report](docs/validation/milestone-4.md), including the boundary between native evidence and regression tests.

Milestone 3 has **107 passing offline tests** and passing offline and live two-client stdio probes. The live check used Nuke NC 17.0v4, completed eight paired script reads, verified distinct request IDs and a shared host instance, confirmed main-thread execution, and checked an expected missing-node MCP error. See the [Milestone 3 validation report](docs/validation/milestone-3.md).

Native inspection initially observed the expected nested paths and truncation. Later NC lookup failures prevented full Read/sequence and known-signal pixel-statistics qualification. These checks remain unqualified; passing transport checks do not establish complete native inspection. Retimed Read paths currently return unknown rather than guessing their timeline mapping.

Native mutation qualification is incomplete. One disposable test verified creation, batch dry-run, a label edit, and deletion, but reported the position edit as unknown. The final mutation smoke test returned partial creation because NC lookup became unavailable; it preserved cleanup evidence and did not retry. These results are not a full native edit pass.

Commercial Nuke, NukeX/Studio, other platforms and versions, native rendered image correctness, and artist acceptance remain unqualified. The offline long-render test validates operation behavior against a fake host; it is not a native render-quality test.

NC node access can be incomplete or intermittent. An empty node list does not prove an empty graph, and a failed creation may still have changed the script. Read-only inspection can be repeated; an ambiguous mutation must not be retried automatically. See the [recorded validation and receipts](docs/validation/milestone-1.md).

Run offline tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
.\.venv\Scripts\python.exe tests/mcp_contract_probe.py --slow
```

With Nuke and the panel server running, run the read-only live checks:

```powershell
.\.venv\Scripts\python.exe tests/smoke_mcp.py
.\.venv\Scripts\python.exe tests/mcp_contract_probe.py --live --output live-two-client.json
```

In a disposable script only, `python tests/smoke_mcp.py --mutate` also checks
creation, batch dry-run/apply, and owned deletion. A failed or uncertain check
exits nonzero and preserves its receipt; uncertain creation is not retried.

## Troubleshooting

| Symptom | Check or next step |
| --- | --- |
| Cannot connect | Start Nuke's panel server, verify the matching port, and check that both processes use the intended checkout. |
| `protocol_mismatch` | Update both sides to the same v2 checkout and restart them. |
| `busy` | Check the eight-client limit and queued/running work for the session. Query existing operations before submitting more work. |
| Timeout or disconnect | Retain the original IDs and query operation status; do not replay the mutation. |
| `instance_changed` | The original host instance is gone. Inspect current state before deciding on further work. |
| Empty NC graph or missing node | Treat observation as incomplete. Repeat read-only inspection if useful; do not infer that a preceding mutation did nothing. |
| Missing shared package | Make the complete checkout available to Nuke, including `nuke_mcp_bridge/`. |

## Architecture and development

```text
MCP client A <-> main.py process A --\
                                    > loopback protocol v2 -> Nuke add-on -> main-thread queue
MCP client B <-> main.py process B --/
```

| Component | Responsibility |
| --- | --- |
| `main.py` | Stdio entry point. |
| `nuke_mcp_server.py` | Existing tool signatures and compatibility wrappers. |
| `nuke_mcp_addon.py` | Nuke panel, runtime startup, and host handlers. |
| `nuke_mcp_bridge/` | Framing, correlated client, request registry, host scheduling, MCP result adapter, and capabilities. |
| `tests/` | Offline regressions, actual stdio contract probes, and opt-in live checks. |

For new host operations, register the handler in `NukeMCPServer.start()` and route Nuke API work through the runtime's main-thread queue. Preserve structured errors and operation identity through the MCP adapter. Keep socket-thread controls free of Nuke API calls and never add automatic mutation replay.

The [design](docs/superpowers/specs/2026-10-14-nuke-mcp-expansion-design.md) and [implementation plan](docs/superpowers/plans/2026-10-14-nuke-mcp-expansion.md) track the remaining milestones: reusable assets and script lifecycle, shot/AOV workflows, and scene events. These are planned work, not currently delivered capabilities.

See [patch notes](PATCH_NOTES.md) for compatibility history. This project builds on `dughogan/nuke_mcp`.

## License

MIT.
