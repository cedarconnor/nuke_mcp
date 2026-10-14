# Guidelines for Creating Nuke Nodes via MCP

Protocol v2: inspect structured `state`/`outcome` and MCP `isError`, and retain
request/instance IDs for `get_operation_status`. A timeout or disconnect does not
prove cancellation. Never automatically retry a mutation, including handle-less
NC creation. Typed edits now require readback, while bounded inspection reports
coverage and omissions. `get_capabilities` reports uncertainty; NC still cannot
establish complete graph observation. Use full Group paths and read the
[inspection and sampling limits](docs/inspection.md) before drawing conclusions.

When creating Nuke node graphs or compositing setups via the Nuke MCP interface, please follow these guidelines to prevent crashes:

## Critical Rules

1. **Never use numbered prefixes in node names**
   - ❌ `1_Primary_Grade`, `2_Saturation`
   - ✅ `Primary_Grade`, `Saturation`

2. **Use labels instead of renaming nodes when possible**
   - Instead of renaming nodes, set their `label` parameter
   - Example: `node["label"].setValue("Exposure Adjustment")`

3. **Create nodes incrementally**
   - Create and test nodes one at a time
   - Add connections only after confirming nodes exist
   - Use `try`/`except` blocks around each node creation

4. **Simplify node creation**
   - Start with minimal node trees (3-4 nodes maximum)
   - Use simpler node types first (Grade, Blur, Transform)
   - Avoid complex nodes like ColorSpace with string parameters

5. **Handle errors gracefully**
   - Catch exceptions for each operation
   - Print detailed error information
   - Avoid allowing one error to crash the entire setup

## Node Creation Pattern

```python
# Safe pattern
try:
    # Create node
    node = nuke.createNode("Grade", inpanel=False)
    
    # Set position
    node.setXYpos(100, 100)
    
    # Set label (instead of renaming)
    node["label"].setValue("Descriptive Label")
    
    # Only then modify parameters
    node["blackpoint"].setValue(0.1)
    
    # Only connect to existing nodes
    if 'previous_node' in locals() and previous_node:
        node.setInput(0, previous_node)
        
    # Store for next connection
    previous_node = node
    
except Exception as e:
    print(f"Error: {str(e)}")
```

## Testing Strategy

1. Start with a single node creation
2. Verify it works before proceeding
3. Add nodes incrementally
4. Test connections separately from creation

Following these guidelines will help ensure reliable operation of the Nuke MCP interface.

## Field notes from live testing (Nuke Non-commercial 17.0v4, 2026-07-30)

The following behavior was measured end-to-end through this bridge (stdio MCP →
`nuke_mcp_server.py` → socket → addon in a live Nuke NC GUI session). It goes
beyond the documented "first 10 nodes" Non-commercial caveat.

### 1. Intermittent Python node-access blackouts

Nuke NC intermittently stops returning node handles to Python, in on/off
windows that flip between calls. During a blackout, with a 6-node graph:

- `nuke.allNodes()` returns `[]` (not "first 10" — empty).
- `nuke.toNode("ExistingNode")` returns `None`.
- `nuke.createNode(...)` **creates the node but returns `None`** — the node
  appears in the graph with a default name (renaming happens after the
  return-value check in the addon, so the requested name is never applied).

The same code returns the full, correct node list in an adjacent call. Graph
state itself is never lost — nodes created during a blackout persist and show
up when a good window returns.

Per-tool consequences:

- `get_script_info` may report `Total Nodes: 0` on a non-empty script.
- `get_node_info`, `modify_node`, `delete_node`, `connect_nodes` may fail with
  "Node not found" for nodes that exist.
- `create_node` may return "Failed to create node of type X" **while still
  creating an unnamed node** — check for orphaned default-named nodes
  (`NoOp1`, `Grade1`, …) after such an error.
- `auto_layout_nodes` and anything else that enumerates may silently do
  nothing.

Mitigation:

- Treat an empty enumeration or a "Node not found" as *suspect*, not
  authoritative. Retry the call; a good window usually appears within a few
  attempts.
- After a `create_node` error, re-check the graph before re-creating, or you
  will accumulate duplicate unnamed nodes.
- Licensed (commercial) Nuke is expected not to show this behavior; treat
  everything above as NC-specific until verified there.

### 2. The addon serves exactly one MCP client at a time

`nuke_mcp_addon.py` uses `listen(1)` and a single client slot. Every MCP
client you register (Claude Code, Claude Desktop, Codex, …) keeps its own
long-lived `main.py` process with a persistent socket to the addon. The first
client to connect holds the slot until it disconnects; all other clients get
"Could not connect to Nuke. Make sure the Nuke addon is running." even though
the addon is fine.

During testing, four concurrent `main.py` processes were found competing for
the slot — including two launched with Nuke's bundled `python.exe` instead of
the repo venv (see `INSTALL_OTHER_CLIENTS.md`; do not use Nuke's Python for
`main.py`).

Mitigation:

- Register the bridge in **one** MCP client at a time, or expect connect
  errors in the others while one is active.
- If connections fail, look for stale bridge processes:
  `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'nuke_mcp' }`
  and kill the ones you are not using. Stopping and restarting the server from
  the NukeMCP panel also drops a stuck client.

### 3. `execute_nuke_code` returns data only via the `output` dict

`print()` inside executed code goes to Nuke's Script Editor, not back to the
MCP client. Assign into the injected `output` dictionary instead:

```python
import nuke
output["nodes"] = [n.name() for n in nuke.allNodes()]
```

### 4. Node types are allowlisted

`create_node` validates against a fixed standard list plus top-level entries
of the Nodes menu. Common types like `CheckerBoard2` are rejected with
"Invalid node type". For anything not on the list, create it through
`execute_nuke_code` with `nuke.nodes.<Class>()` — but note that during an NC
blackout window (see §1) the returned handle may be `None` there as well.
