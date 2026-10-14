# Nuke MCP reliability and workflow expansion design

Date: 2026-10-14. Baseline: `987abf67dab81c3573780ce5e4fd888e5f8b422a` on `codex/nuke-nc-compat`.

## Purpose and scope

Extend the existing bridge so an assistant can inspect a comp accurately, make verifiable changes, reuse artist-approved setups, and prepare shots without risking unrelated work. Retain the current Python/FastMCP architecture and the 15 existing tool names. The implementation plan is [here](../plans/2026-10-14-nuke-mcp-expansion.md).

The user requested a plan following the repository comparison. The technical defaults below are proposed engineering choices, not claims of prior user approval. This document authorizes no implementation or deployment by itself.

### Included

1. Framed transport, request identity, explicit mutation outcomes, multi-client access, and bounded scheduling.
2. Host capabilities and honest Non-commercial observability.
3. Verified node edits and batch edits with per-operation results.
4. Structured graph, Read, channel, and file-sequence inspection.
5. Bounded channel statistics and compositing diagnostics.
6. Toolset libraries, script lifecycle operations, and explicit project settings.
7. Manifest-driven shot setup and layered/AOV graph construction.
8. Bounded scene events and revision-aware edits.
9. Offline contract tests, live qualification scenarios, installation documentation, and release evidence.

### Follow-ons outside the first release

ML tiling, Cattery/CopyCat, BlinkScript authoring, camera tracking, deep-comp recipes, headless process launching, Studio editorial tools, searchable Nuke documentation, and persistent project/correction memory. These need separate host capability and artist acceptance work. LiveGroup authoring and gizmo packaging follow plain toolsets; the library must preserve existing Group nodes but does not publish LiveGroups in this release. Preview images are a later addition; numerical diagnostics do not establish visual quality.

## Existing constraints

The add-on currently accepts one long-lived client, detects message completeness by counting braces, and dispatches host work through `executeInMainThreadWithResult`. The external server uses a 15-second response timeout and converts many failures into ordinary text. The current inspection returns top-level nodes and a subset of visible knob types. Templates and graph organization already exist and should be extended rather than duplicated.

The local field notes describe NC enumeration and node-handle failures, including node creation returning no handle after changing the graph. Treat those as recorded observations to reproduce, not guarantees about every Nuke installation. An empty enumeration cannot prove that a comp is empty or that creation failed without side effects.

## Global constraints

- Keep `fastmcp==2.14.7`; add no runtime dependency in this release.
- Qualify Windows with Nuke 17 and external Python 3.11 first; report other hosts as unqualified until tested.
- Keep `main.py`, port `9877`, and `NUKE_MCP_PORT` as supported entry points and settings.
- Bind only to loopback. Remote/network access and authentication for remote clients are out of scope.
- Run every Nuke API call on the host main thread; never infer thread safety from a read-only label.
- Keep the existing 15 MCP tool names and required arguments; retain useful success text while adding structured results and true MCP error signaling.
- Never automatically replay a mutation after timeout, disconnect, ambiguous readback, or host restart.
- Never clear an existing script or overwrite a file as an implicit step of a graph-building workflow.
- Preserve unrelated nodes, selection, frame, proxy mode, and project settings unless explicitly targeted.
- Use full node paths for identity and connections inside Groups; reject ambiguous short-name matches.
- Label incomplete observation and sampled measurements explicitly; neither is a complete graph or pixel audit.
- Borrow designs selectively; record source and license notices if any code is copied.

## Architecture and installation

Keep the external stdio MCP process and in-process add-on. Add a dependency-free `nuke_mcp_bridge/` package shared by both, with Nuke imports confined to host-facing modules. `main.py` remains the entry point; `nuke_mcp_server.py` owns registration and compatibility wrappers; `nuke_mcp_addon.py` owns the panel and starts/stops the host runtime.

Extract transport and domain logic as each phase needs it. Do not rewrite the entire existing server before delivering a usable phase. Repository-path loading remains the development installation. A release must install the add-on and the new package together; copying only `nuke_mcp_addon.py` is no longer sufficient and must produce actionable guidance. Introduce protocol v2 as a coordinated client/add-on upgrade, with an explicit mismatch error and no automatic legacy fallback. Rollback restores both components together.

## Request and result contract

Use UTF-8 JSON messages delimited by a newline. Escaped newlines inside JSON strings are ordinary payload. Set the maximum encoded message to 8 MiB, reject invalid UTF-8, and cap incomplete buffers. The hello exchange identifies `protocol_version=2`, `server_instance_id` (new UUID at each add-on start), version, and a client session UUID. A wrong protocol, different application, or unexpected instance must fail before mutation.

Requests contain `request_id`, `client_session_id`, `server_instance_id`, `command`, `params`, and `timeout_ms`. IDs are UUID strings. The host converts `timeout_ms` into a monotonic deadline at admission; 30 seconds is the default and 300 seconds the maximum for ordinary operations. Long rendering uses the operation registry below. Client waiting time is not proof that host work stopped.

Every response carries the same request identity and a structured result:

```json
{
  "ok": false,
  "state": "failed",
  "outcome": "unknown",
  "data": {},
  "error": {"code": "state_uncertain", "message": "Creation could not be verified"},
  "warnings": [],
  "observation": {"coverage": "unknown", "reason": "node_access_unreliable"},
  "revision": 12
}
```

`state` is one of `queued`, `running`, `completed`, `failed`, `cancelled`, `expired`. `outcome` is one of `not_started`, `applied`, `partial`, `rolled_back`, `unknown`; read-only successful operations use `not_started` for mutation outcome. Only verified successful work is `ok=true`. `coverage` is `complete`, `partial`, or `unknown`, describing visibility within the requested scope, not artistic correctness. MCP errors must set `isError=true`; successful legacy text remains available alongside structured content. A transport failure has a request ID and error code, not a fabricated host receipt.

Support up to 8 connected clients and 64 pending host commands, with one queued/running command per client session. Admit operations in FIFO order, execute one host operation at a time, and reject overload as `busy` before mutation. Socket threads may answer hello, heartbeat, operation status, and cancellation from cached thread-safe state; they never query Nuke. A Qt timer on Nuke's main thread drains the queue, and each handler rechecks deadline, cancellation, instance, and optional expected revision immediately before mutation. Shut down rejects queued work and detaches the timer/callbacks; work already executing cannot be declared cancelled merely because its socket closes.

Retain up to 4096 request receipts for 30 minutes per server instance; never evict running work. Reuse of a retained request ID with the same canonical payload returns its existing receipt; a different payload yields `request_conflict`. `get_operation_status(request_id, server_instance_id)` is read-only. Eviction returns `receipt_expired_or_unknown`, and a restarted instance returns `instance_changed`. Neither response authorizes replay. Deduplication is bounded to retained receipts; there is no claim of exactly-once execution across restarts or expiry.

Cancellation of queued work proves `not_started`. Cancellation during execution is a request, not an acknowledgement of termination. Long native render calls may block the UI and cannot be preempted safely. Add `start_render` returning an operation ID and poll status; retain `render` as a compatibility wrapper with bounded waiting and an operation-status hint. For multi-frame jobs check cancellation between frames; one native frame can remain running. Existing raw Python stays explicit and unrestricted within the trusted local client model, but has no safe rollback guarantee.

## Capabilities and observation

`get_capabilities()` reports protocol/add-on versions, instance, PID, Nuke version, GUI mode, host flavor, license mode if observable, and supported tool groups. Unknown fields remain unknown. Capability discovery must not create disposable nodes or query private license secrets. Plugin/node class support is advisory until a requested class is actually available; avoid fixed allowlists that reject installed classes. Missing plugins fail explicitly without claiming a completed operation.

Under NC or unreliable graph observation, never claim global completeness, absence of nodes, safe whole-graph rollback, or complete event coverage. Positive direct lookup and readback can prove an addressed knob operation, but absent lookup cannot prove absence. A created handle that cannot be recovered unambiguously yields `state_uncertain`; do not recreate or delete candidates. A zero-node response on a known non-empty comp must be marked suspect.

## Edits and batches

Typed edit tools validate identifiers, knob type/value, input range, and target resolution before writing. Exclude executable/callback knobs from typed setters; raw Python remains the explicit escape hatch. Do not flatten animation or expressions: static setters reject those targets. Reject non-finite numbers and ambiguous array dimensionality. Return actual names/paths and readback values.

Undo groups improve artist recovery but are not transactions. Roll back only a uniquely owned edit with trustworthy prior state and trustworthy readback. Never use a global undo to repair an uncertain operation because it could reverse artist changes. If rollback fails or cannot be established, report partial/unknown plus the exact operations observed.

`batch_edit(operations, dry_run=true, expected_revision=null)` supports set-knob, connect/disconnect, and position changes, up to 100 explicit operations. It does not support arbitrary code, node deletion, rendering, or script replacement. Validate all targets before the first mutation; stop at the first runtime failure, return a result for every requested item (including not-started items), and retain the successfully applied subset. One undo group, no all-or-nothing claim. A dry run provides a preview; it reserves nothing and must be revalidated at apply time. Legacy `modify_node` uses this same executor for its multiple effects.

## Inspection and diagnostics

`inspect_graph(max_nodes=256, max_knobs_per_node=64, recurse_groups=true)` reports full paths, classes, indexed input connections, supported knob values, omitted fields, errors, and `truncated`. Hard limits: 1000 nodes and 128 knobs per node. Selection-only inspection is supported as an explicit scope, never as an accidental default.

`inspect_reads(node_paths=null, channel_limit=256)` reports raw and evaluated file paths, frame range, format, colorspace, channels/layers, multipart choices, and errors. Maximum 2048 channels per Read; all truncation is explicit. `validate_reads(first_frame, last_frame, step=1)` expands paths using Nuke's file evaluation for the specified frames/views and checks file existence, with at most 10000 evaluated paths. It reports checked coverage, missing paths, and unresolved expressions separately. It does not relink automatically or treat one sampled frame as a complete sequence check.

`sample_channel_statistics(node_path, channels, frame, roi=null, max_samples_per_channel=1024)` allows up to 16 resolved channels and 4096 samples each. Validate an integer frame and a positive, in-bounds pixel ROI. Return finite min/max/mean, non-finite counts, zero fraction, actual frame/channels/ROI/grid, and whether every pixel was sampled. A filtered tile sample is not an individual-pixel extremum; zero samples do not establish an all-black image. Restore current frame on all exits if evaluating requires changing it. Limit expensive sampling through the shared operation deadline, with partial progress explicitly reported.

## Toolsets and script lifecycle

Use `NUKE_MCP_LIBRARY_ROOT` or `%USERPROFILE%/.nuke/nuke_mcp_toolsets` as the library root. `list_toolsets`, `save_toolset(node_paths, name, overwrite=false)`, and `load_toolset(name, group_name, position)` operate only within that root. Names are identifiers, not paths; resolve symlinks/junctions and reject root escapes. Save a `.nk`/`.nknc` payload appropriate to the observed host plus metadata containing content hash, host version/license mode, declared inputs/outputs, and dependencies. Preserve artist selection, use atomic publication, and leave existing files unchanged when overwrite is false.

Inspect/hash a toolset before applying; recheck before paste. A stored Nuke script can contain executable callbacks and is trusted artist content, not inert JSON. Do not advertise its metadata as a sandbox. Load into a newly created, explicitly named Group and return actual created paths. Unexpected or unobservable creation produces partial/unknown; do not clean up unrelated nodes.

Add `open_script(path, discard_unsaved_changes=false)`, `save_script(path=null, overwrite=false)`, and `set_project_settings(settings, dry_run=true)`. Validate host-appropriate `.nk`/`.nknc` and explicit requested paths. Opening refuses dirty scripts unless discard was explicitly requested. Saving the current script is an intentional save; save-as refuses an existing different target by default. Settings support FPS, frame range, format, and existing color-management knobs with exact readback; missing OCIO options fail rather than guessing a substitute. All use the same request and outcome contract.

## Shot and AOV workflows

Use a versioned JSON manifest (`schema_version=1`) as the authoritative input. CSV is an import format only. A shot has `shot_id`, `script_path`, `plates` (path, colorspace, first/last), `frame_range` (work_first, cut_in, cut_out, work_last), rational `fps` (numerator/denominator), `format` (width/height/pixel_aspect), explicit `color_settings`, optional `toolset`, and `write` (path, channels, file_type, datatype, compression, colorspace). Validate work_first <= cut_in <= cut_out <= work_last and positive dimensions/FPS; permit negative timeline frames. No hardcoded show paths or guessed ACES configuration.

`import_shot_csv(path, column_map, defaults)` converts explicit columns into this schema and reports duplicate shot IDs/conflicting rows, missing fields, and unmapped fields. `plan_shot_setup(manifest)` returns proposed paths/nodes/settings and errors without mutation. `apply_shot_setup(manifest, plan_digest)` revalidates inputs, destination collisions, host compatibility, and digest. It creates at most 100 shots, sequentially, and records each output separately. First release uses a disposable empty GUI session, requires a clean current script, and opens/builds/saves one new script per shot. It never temporarily replaces a dirty artist comp. Restore a previously saved clean script after the batch; a restore failure is explicit. NC cannot prove an empty script from enumeration alone: establish a fresh blank script through the explicit lifecycle operation and retain its receipt.

The plan digest binds manifest, toolset hashes, evaluated source paths and existence/size/mtime metadata, target existence, host instance/capabilities, and library/config identities. Apply rechecks before each shot and each publication. Full plate-content hashing is not required; report this provenance limit. Existing output collisions are errors, even on a retry; reruns reconcile receipts and existing artifacts rather than overwrite them. Use staging and host readback to publish completed scripts; return partial completion if later shots fail. No distributed transaction is promised.

`plan_layered_comp(manifest)` and `build_layered_comp(manifest, plan_digest)` use a separate schema v1 with `group_name`, `layers`, and optional `write`. Each layer has a unique `id`, exactly one of `source_node_path` or `source_file`, a required `channel_layer`, and optional static `adjustments` (`grade` with gain/gamma or `blur` with size). The first layer establishes the base; each subsequent layer requires `operation` from `over`, `plus`, `multiply`, `screen`, with the accumulated comp on input B and the new layer on A. Optional `mask_node_path` and `mask_channel` are explicit. File sources require colorspace; optional Write settings use the shot schema. Require available channels before construction; do not infer a beauty reconstruction from arbitrary layer names. Read-only validation precedes mutation; build inside a named Group, but saving and rendering are separate actions. No `scriptClear` or implicit render. Cryptomatte material-specific adjustments follow basic channel reconstruction after separate qualification.

Staged shot publication must leave the host's current script identity and any script-relative Write expressions referring to the final path, not the staging path. Reload the published script and verify these values before recording completed publication; a failed reload is a partial outcome, not an instruction to overwrite or delete a successfully published artifact.

## Events and revision checks

Register callbacks once for node creation/deletion, relevant knob changes, script load/save, and frame changes where supported. Keep a 1000-event in-memory ring with sequence numbers, instance ID, monotonic timestamp, full node path when observable, and originating request ID when available. `get_events(after_sequence=0, limit=100)` returns at most 500 events plus `next_sequence` and an explicit history-gap flag. Coalesce repeated knob changes for 100 ms; keep script switches and deletions. Do not expose arbitrary callback text or sensitive knob contents.

`subscribe_events(event_types)` sets a per-client filter; delivery is polling in the first release, with no unsolicited stdio output. Increment the graph revision for observed graph/knob/script changes before coalescing. Event callbacks only enqueue bounded data; they do not perform socket writes, disk writes, or recursively inspect the graph. `expected_revision` is an optimistic check, not a lock against arbitrary scripts or unobservable NC edits. If event observation is degraded, reject requests requiring a revision guarantee with `revision_unavailable`. Stop/restart removes callbacks and distinguishes instances.

## Delivery and acceptance

Deliver six sequential milestones: foundation; verified edits; inspection/diagnostics; reusable assets/lifecycle; shot/AOV workflows; events and release qualification. Earlier milestones remain independently useful. Read-only tests run by default; mutations require an explicitly disposable Nuke session. No tests in this planning task were run to qualify the proposed features.

Offline tests use standard-library `unittest`, a minimal fake Nuke API, and loopback socket fixtures. Pin real stdio MCP behavior with integration tests using the existing MCP SDK. Cover fragmented/coalesced UTF-8, braces inside strings, oversized messages, late replies, timeout before dispatch, disconnect after write, concurrent clients, restart, ambiguous NC reads, nested groups, Windows junctions, animated knobs, and failed rollback. Assert no unintended mutations as well as returned errors.

Live evidence distinguishes protocol/graph correctness, native render correctness, and artist acceptance. NC fixtures remain under ten nodes where possible; capabilities unavailable under NC are recorded as unavailable, not failed commercial qualification. Commercial Nuke qualification requires a real session with that capability; mocks cannot substitute. Artist checks cover reusable setup appearance, AOV reconstruction, and diagnostics at known frames/ROIs. Retain fixture scripts, input metadata, JSON results, and relevant rendered samples.

## Source references

These are design references inspected at pinned revisions; they are not drop-in dependencies or proof of native qualification.

- [DCC-MCP node graph](https://github.com/dcc-mcp/dcc-mcp-nuke/blob/7354b9c3526b8594d0b0cbdf8d50e0d14f75e775/src/dcc_mcp_nuke/node_graph.py): readback and partial-creation handling.
- [DCC-MCP channel statistics](https://github.com/dcc-mcp/dcc-mcp-nuke/blob/7354b9c3526b8594d0b0cbdf8d50e0d14f75e775/src/dcc_mcp_nuke/skills/nuke-script/scripts/sample_channel_statistics.py): bounded measurements and sampling metadata.
- [DCC-MCP layered compositing](https://github.com/dcc-mcp/dcc-mcp-nuke/blob/7354b9c3526b8594d0b0cbdf8d50e0d14f75e775/src/dcc_mcp_nuke/compositing.py): manifest structure; do not adopt its current-graph deletion.
- [kleer001 tools](https://github.com/kleer001/nuke-mcp/tree/6cbed80a2f35b997263fc51c988c5bb1405657fd/src/nukemcp/tools): toolsets and bulk-operation interfaces.
- [kleer001 events](https://github.com/kleer001/nuke-mcp/blob/6cbed80a2f35b997263fc51c988c5bb1405657fd/src/nukemcp/events.py): bounded events; add explicit gaps and revisions.
- [Toolkit shot setup](https://github.com/sideshowroberto/vfx-agent-toolkit/blob/9063d47135ce85bb38d639cc47dab14288c4b627/plugins/nuke-vfx/skills/nuke-shot-setup/scripts/batch_shot_setup.py): plate/CSV setup and layered show settings.

MIT notices exist in these three source projects. Recheck provenance of any copied file and preserve its notices. Other reviewed repositories are not proposed code donors.
