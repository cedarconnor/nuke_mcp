# Compatibility patch notes

## Task 14: scene events and optimistic revision checks

Adds `subscribe_events` and `get_events` (37 total tools), per-client filters, bounded history,
100 ms knob coalescing, explicit gaps, and request attribution through stepped jobs. Revision changes
are counted before coalescing. Batch edits can reject a stale observed revision while accepting their
own callbacks; workflow digests now bind observed scene state. NC and degraded observation refuse
explicit revision guarantees. Stop removes callbacks; restart creates a new event instance.
Frame events are sampled on the main-thread timer, since Root UI updates may be absent.
See [event contracts](docs/scene-events.md). Task 15 release qualification remains pending.

## Milestone 5: manifest-driven production workflows

Adds five tools for schema-v1 manifests, explicit CSV conversion, shot planning/publication,
and layered/AOV Groups. Plans bind observed inputs to a canonical digest. Shot application requires
an explicitly disposable clean session, refuses existing outputs, publishes staged files without
clobbering, and restores an unchanged saved original when ownership remains provable.
Group builds preserve unrelated nodes and use fixed Grade-then-Blur adjustment ordering.
Callback script switches stop further writes; uncertain creation is retained without retry.

All 168 offline tests and offline/live two-client stdio passed (35 tools). Native NC lookup loss
prevented two-shot publication and full AOV construction, so pixel/render qualification remains open.
See [Milestone 5 evidence](docs/validation/milestone-5.md) and [workflow contracts](docs/production-workflows.md).
Earlier local additions are documented in the [Milestone 2](docs/validation/milestone-2.md),
[Milestone 3](docs/validation/milestone-3.md), and [Milestone 4](docs/validation/milestone-4.md) reports.

## Milestone 1: protocol v2 foundation

The bridge now accepts eight loopback clients, frames UTF-8 JSON explicitly,
correlates replies with request/session/instance IDs, and serializes host work
through a main-thread Qt timer. Bounded receipts support status and cancellation
without replaying uncertain mutations. All 15 existing tools carry structured
results and real MCP errors. New tools report capabilities and submit/poll/cancel
render jobs, with temporary frame/proxy state restored at completion.

Deploy the add-on, shared package, and external server together. FastMCP remains
pinned to 2.14.7. Verified node edits and complete graph observation are later
milestones; existing NC limits remain. The sections below describe earlier patches.

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

## Milestone 2 typed edits and batch preflight

Node creation, deletion, positioning, and connections now use validated host
primitives. Static knob setters reject callbacks, unsupported types, animation,
expressions, non-finite values, and ambiguous array shapes. Edits return actual
paths and readback values; a missing NC handle stays uncertain without retry.
Deletion requires a destruction callback for the exact target handle. Creation
cleanup can delete only its returned, observable owned handle; failed recovery
is reported explicitly. Node factories resolve installed classes at execution.
Backdrop creation also follows this path instead of interpolating raw Python.

Batch edits default to dry-run, validate all items first, use one undo group, and
retain applied items on failure. Legacy modify uses the same executor. Template,
layout, and organization tools explicitly report unverified outcomes. Expected
scene revisions are unavailable until a trustworthy provider is installed.

## Milestone 3 inspection and diagnostics

Added bounded nested graph/Read inspection, sequence-path existence checks, and
filtered channel statistics. Legacy inspection now summarizes the same full-path
observations and discloses incomplete coverage. Read checks distinguish missing
files from unknown evaluation, including unqualified timing remapping. Statistics
resolve channels and ROI at the requested frame, preserve partial progress, and
restore the original frame even if summary calculation fails. The server now has
24 tools; native Read and pixel qualification remain limited by NC lookup failures.
