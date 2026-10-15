# Nuke MCP expansion implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dependable inspection, verified edits, reusable assets, shot/AOV setup, capabilities, and scene events to the existing Nuke MCP.

**Architecture:** Retain the external stdio FastMCP server and Nuke add-on. Extract a shared, dependency-free package incrementally, beginning with protocol and scheduling contracts. All features share request identity, explicit outcomes, bounded observation, and main-thread execution.

**Tech Stack:** Python 3.11, FastMCP 2.14.7, existing MCP SDK, Python standard library, Nuke Python API, Nuke's bundled PySide6/PySide2 for the host queue timer.

**Spec:** [Nuke MCP reliability and workflow expansion design](../specs/2026-10-14-nuke-mcp-expansion-design.md). Read it before implementing any task.

**Status:** All six milestones and Tasks 1–15 are implemented, with bounded NC qualification rather than full production certification. See `docs/validation/task-15.md` for current checks and remaining commercial, native workflow, and artist-review gates. Milestones 2–5 were pushed on `codex/nuke-production-workflows`; Task 14 was pushed on `codex/nuke-scene-events` at `1238ba2`. Task 15 is local on `codex/nuke-release-qualification`. Main remains `59d8ff6`.

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

## Milestones and gates

| Milestone | Tasks | Usable result | Gate before advancing |
| --- | --- | --- | --- |
| 1 Foundation | 1–4 | Multiple clients, matched receipts, capability reporting, explicit failures | Socket fault tests and real stdio result tests pass |
| 2 Verified editing | 5–6 | Checked edits and bulk changes with precise outcomes | NC ambiguity and partial mutation regressions pass |
| 3 Inspection | 7–8 | Graph/Read/sequence inspection and channel statistics | Nested identity, truncation, and known image tests pass |
| 4 Reuse | 9–10 | Toolset library, script lifecycle, explicit settings | Selection preservation, dirty-script protection, path containment pass |
| 5 Production workflows | 11–13 | Validated manifests, shot generation, AOV Groups | No overwrite or graph clearing; fixtures reproduce intended topology |
| 6 Events and delivery | 14–15 | Scene revisions, event polling, qualified release | Offline suite plus separately recorded native and artist checks |

Milestones 1–5 results are recorded in their validation reports; Milestone 6 has bounded NC evidence in the Task 14/15 reports, with the listed native and commercial gates still open. Unavailable licensed capabilities are reported as unqualified; they are not silently substituted with mock results. Schedule estimates depend on live Nuke availability and are intentionally not promised here.

## File responsibilities

Existing files retained: `main.py` is the stdio entry point; `nuke_mcp_server.py` keeps old tool signatures and registers new tools; `nuke_mcp_addon.py` keeps panel/startup and legacy host handlers until each is migrated. Update `nuke_startup/init.py`, `nuke_startup/menu.py`, `readme.md`, `INSTALL_OTHER_CLIENTS.md`, `PATCH_NOTES.md`, and `nuke-mcp-guidelines.md` as behavior changes.

New package files are introduced only by their owning tasks:

| File under `nuke_mcp_bridge/` | Responsibility |
| --- | --- |
| `protocol.py` | Encoding, framing, envelopes, shared result/error types |
| `operations.py` | Admission, queue, deadlines, cancellation, receipt retention |
| `runtime.py` | Socket clients, host timer, dispatch registry, lifecycle |
| `client.py` | External connection and response correlation |
| `mcp_adapter.py` | Structured content, text compatibility, MCP errors, tool registration helpers |
| `capabilities.py` | Host flavor, NC mode, observable feature reports |
| `mutations.py`, `batch.py` | Checked edits, owned recovery, bounded batch executor |
| `inspection.py`, `diagnostics.py` | Graph/Read/files and channel measurements |
| `toolsets.py`, `scripts.py` | Asset library and script/settings lifecycle |
| `manifests.py`, `shots.py`, `compositing.py` | Pure validation and host workflow execution |
| `events.py` | Callback lifecycle, ring buffer, gaps, revisions |

`protocol.py` defines `Request` and `Result` TypedDicts with the spec's exact envelope fields, `BridgeError(code, message, outcome='not_started', data=None)`, and `make_result(...)`. Domain functions accept the injected `nuke` API and return JSON-safe data dictionaries or raise `BridgeError`. The runtime owns request receipts and converts domain outcomes to `Result`; domain functions must not fabricate unrelated request IDs. Data types referenced below are these dictionaries, not undocumented classes.

Tests use `unittest` and `tests/fakes.py`; fake host mutations assert main-thread affinity. New `tests/__init__.py` enables module test invocation. `tests/mcp_contract_probe.py` exercises the actual MCP stdio client/server against a loopback fake host, without importing Nuke. `tests/live/qualify.py` runs opt-in native scenarios and writes results to a caller-supplied directory.

## Review focus

1. A cancelled or expired queued operation must not mutate after the UI becomes responsive — Tasks 2–3.
2. An NC blackout after creation must not cause a duplicate node or deletion of an artist's node — Task 5.
3. Identically named nodes inside different Groups and sequence paths with Unicode/expressions must resolve exactly — Task 7.
4. A Windows junction or changed library payload between planning and use must not publish outside the intended directory — Tasks 9 and 12.
5. An artist change or script switch between a dry run and apply must invalidate the expected state, without a global undo of the artist's work — Tasks 6 and 14.

## Execution discipline

Before code changes, inspect the working tree and preserve unrelated edits. Create an implementation branch with the `codex/` prefix using the applicable worktree workflow if isolation is needed. This plan does not request a push, PR, deployment, dependency upgrade, or changes to the user's Nuke startup files.

Each task follows the checkboxes below. Test assertions are contract examples to express as `unittest.TestCase` methods; named fake fixtures are created with their owning tests. First run the focused tests and capture the expected failure, then implement, rerun, and commit only the task's files. Missing dependencies, skipped tests, and environment failures are not expected red results. Each task's commit includes its relevant documentation update. Run the full offline suite at milestone boundaries, not repeatedly after every unchanged check.

Standard commands from the repository root:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -v
.venv/Scripts/python.exe tests/mcp_contract_probe.py
git diff --check
```

## Milestone 1 Foundation

### Task 1 Framed protocol and shared result contract

**Files:** Create `nuke_mcp_bridge/__init__.py`, `nuke_mcp_bridge/protocol.py`, `tests/__init__.py`, `tests/fakes.py`, `tests/test_protocol.py`.

**Interfaces:** Produce `encode_message(message: dict) -> bytes`, `FrameDecoder.feed(chunk: bytes) -> list[dict]`, `validate_request(message: dict) -> Request`, `BridgeError`, and `make_result(...) -> Result`. Define `PROTOCOL_VERSION=2`, `MAX_MESSAGE_BYTES=8*1024*1024`. Pure functions import no Nuke or FastMCP.

- [x] Write tests for every split of a UTF-8 message, coalesced messages, escaped newlines/braces, invalid UTF-8/JSON, invalid IDs, unsupported version, and oversized/incomplete input.

```python
decoder = FrameDecoder()
first = {'text': 'é } {\ntext'}
wire = encode_message(first) + encode_message({'n': 2})
self.assertEqual(decoder.feed(wire[:-1]), [first])
self.assertEqual(decoder.feed(wire[-1:]), [{'n': 2}])
```

- [x] Run `python -m unittest tests.test_protocol -v` with the repository venv; expect failing protocol assertions/imports before implementation.
- [x] Implement the frame decoder, strict envelope validation, result factory, and stable public error codes from the spec. Cap bytes before attempting JSON parsing.
- [x] Rerun `tests.test_protocol`; all cases must pass without stdout diagnostics.
- [x] Commit as `feat: define framed bridge protocol and operation results`.

### Task 2 Request registry and bounded host scheduling

**Files:** Create `nuke_mcp_bridge/operations.py`, `tests/test_operations.py`; extend `tests/fakes.py` with a fake monotonic clock.

**Interfaces:** Consume `Request`, `Result`, `BridgeError`. Produce `OperationRegistry(clock, instance_id)`, `.admit(request) -> Result`, `.tick(dispatch: Callable) -> None`, `.lookup(request_id, instance_id) -> Result`, `.cancel(request_id) -> Result`, `.shutdown() -> None`. Dispatch receives the accepted request and returns domain data; registry tracks start/end and mutation outcome. Expose a thread-safe `record_result` path for long operations without executing host code on workers.

- [x] Write tests for 8 clients, 64 pending commands, one active request per client, FIFO ordering, canonical payload conflict, retained-ID deduplication, receipt expiry/capacity, unknown/restarted identities, and cancellation before dispatch.

```python
registry.admit(request)
registry.cancel(request['request_id'])
registry.tick(dispatch)
self.assertEqual(dispatch.call_count, 0)
self.assertEqual(registry.lookup(request['request_id'], instance)['outcome'], 'not_started')
```

- [x] Run `python -m unittest tests.test_operations -v`; confirm red assertions for missing admission/deadline behavior.
- [x] Implement monotonic deadlines (30 seconds default, 300 seconds maximum), receipt retention (4096 / 30 minutes), and instance-bound status. Check lifecycle immediately before dispatch; never infer completion from disconnect. Retained duplicate IDs return the original receipt even after its deadline.
- [x] Rerun focused tests, including timeout while queued, shutdown before dispatch, and cancellation after a mutation begins; the latter must never return a false `not_started` receipt.
- [x] Commit as `feat: track request outcomes and serialize host operations`.

### Task 3 Multi-client runtime and correlated external client

**Files:** Create `nuke_mcp_bridge/runtime.py`, `nuke_mcp_bridge/client.py`, `tests/test_runtime.py`, `tests/test_client.py`; modify `nuke_mcp_addon.py:34`, `nuke_mcp_server.py:296`, and the startup modules.

**Interfaces:** Produce `BridgeRuntime(handlers, registry, host_dispatcher)`, `.start(host='127.0.0.1', port=9877)`, `.stop()`. The injected host dispatcher installs/removes a main-thread Qt timer. Produce `BridgeClient.connect() -> dict`, `.call(command, params, timeout_ms=30000) -> Result`, `.status(request_id, instance_id) -> Result`, `.close()`. There is one pending ordinary call per client session; status and cancellation remain available over the control path.

- [x] Write loopback tests with real sockets: two simultaneous clients, fragmented/coalesced traffic, braces in Python payloads, wrong application/version, stale responses, partial sends, port collision, reconnect, stop/restart, and deadline expiry before timer dispatch.

```python
fixture.delay_reply('first')
first = fixture.client_call_that_times_out('first')
second = fixture.client.call('ping', {})
self.assertNotEqual(first['request_id'], second['request_id'])
self.assertEqual(second['data']['pong'], True)
self.assertEqual(fixture.mutation_execution_count, 1)
```

- [x] Run `python -m unittest tests.test_runtime tests.test_client -v`; verify the late-response and multi-client tests fail against the original behavior.
- [x] Replace brace counting and persistent single-client state with bounded readers/writers and the shared registry. Install the UI pump on the main thread, cache heartbeat data, close failed sockets, and stop all owned threads/timers without waiting on the main thread for itself. Refuse coordinated-version mismatch before dispatch. Integrate existing handlers without moving their Nuke calls to workers.
- [x] Run focused tests; assert the fake host sees only main-thread calls and teardown leaves no clients/timers. Update installation docs to deploy the package and add-on together; preserve loopback port configuration.
- [x] Commit as `feat: support correlated multi-client Nuke connections`.

### Task 4 MCP results capabilities and render status

**Files:** Create `nuke_mcp_bridge/mcp_adapter.py`, `nuke_mcp_bridge/capabilities.py`, `tests/test_mcp_adapter.py`, `tests/test_capabilities.py`, `tests/mcp_contract_probe.py`; modify `nuke_mcp_server.py`, `tests/smoke_mcp.py`, `INSTALL_OTHER_CLIENTS.md`.

**Interfaces:** Produce `probe_capabilities(nuke) -> dict`, `register_tools(mcp, client) -> None`, and `to_mcp_result(result: Result, legacy_text: str)`. Public tools: `get_capabilities()`, `get_operation_status(request_id, server_instance_id)`, `cancel_operation(request_id, server_instance_id)`, `start_render(write_node, first_frame, last_frame, step=1)`. Retain the old `render` signature and its success text while adding operation identity on a bounded wait.

- [x] Write stdio tests for the original 15 tool names/signatures, real `isError=true`, structured receipt round-trip, host unavailable, unknown license mode, Nuke/NukeX/Studio classification, unsupported nodes, and render beyond the old 15-second wait.

```python
reply = await session.call_tool('get_node_info', {'node_name': 'missing'})
self.assertTrue(reply.isError)
# Probe also asserts request_id and error.code survive the actual MCP serialization.
```

- [x] Run `python -m unittest tests.test_mcp_adapter tests.test_capabilities -v` and `python tests/mcp_contract_probe.py`; confirm the failure contract is red before changing wrappers.
- [x] Implement the result adapter against installed FastMCP 2.14.7, testing its actual `CallToolResult` handling rather than assuming serialization. Wire lifespan cleanup. Remove graph enumeration as the transport ping. Render registration polls the same ledger, executes on the main thread, restores temporary proxy/frame state, and checks cancellation between frames; a blocked native frame stays running.
- [x] Rerun focused tests and the full Milestone 1 suite. Update the smoke test to read structured failures and report unavailable live Nuke distinctly. Document capability uncertainty and protocol migration.
- [x] Commit as `feat: expose capabilities and truthful MCP operation status`.

## Milestone 2 Verified editing

### Task 5 Checked node mutations and partial creation recovery

**Files:** Create `nuke_mcp_bridge/mutations.py`, `tests/test_mutations.py`; modify add-on host dispatch and legacy node wrappers.

**Interfaces:** Produce `resolve_node(nuke, node_path)`, `create_node(nuke, node_type, name=None, position=None, inputs=None, parameters=None) -> dict`, `set_knob(nuke, node_path, knob, value) -> dict`, `connect_input(nuke, node_path, input_index, source_path) -> dict`, `position_node(nuke, node_path, x, y) -> dict`, `delete_node(nuke, node_path) -> dict`. Outcomes travel through `BridgeError` and the registry. Each routine validates, changes, reads back, and returns actual identity/value.

- [x] Write tests for handle-less creation, partial creation, NC empty enumeration, duplicate short names, unavailable classes, pre-existing selection auto-connections, array knobs, NaN/Inf, executable knobs, animated/expression targets, failed readback, and failed recovery.

```python
host.create_returns_none_after_mutation = True
with self.assertRaises(BridgeError) as error:
    create_node(host, 'Grade', name='MCPGrade')
self.assertEqual(error.exception.outcome, 'unknown')
self.assertEqual(host.create_count, 1)
self.assertEqual(host.unrelated_delete_count, 0)
```

- [x] Run `python -m unittest tests.test_mutations -v`; ensure the NC scenario fails before implementing recovery policy.
- [x] Implement exact lookup and explicit connection wiring, restoring selection after creation. Resolve requested classes at execution rather than rejecting every class absent from the old allowlist. Use uniquely attributable recovery only; never blanket-delete a before/after difference from unreliable enumeration. Reject static writes to dynamic knobs. Preserve meaningful NC restrictions.
- [x] Rerun tests; prove original graph state is unchanged on validation failure and report partial/unknown where rollback cannot be verified. Add a disposable native single-Grade scenario to `tests/smoke_mcp.py` with cleanup uncertainty reported rather than hidden.
- [x] Commit as `feat: verify Nuke edits and report uncertain mutations`.

### Task 6 Bulk edits and migration of compound legacy operations

**Files:** Create `nuke_mcp_bridge/batch.py`, `tests/test_batch.py`; modify `modify_node` and new tool registration.

**Interfaces:** Produce `validate_batch(nuke, operations) -> dict`, `execute_batch(nuke, operations, dry_run=True, expected_revision=None, revision_provider=None) -> dict`. Public `batch_edit(operations, dry_run=True, expected_revision=None)` supports at most 100 set-knob/connect/position operations. Revision guarantees remain unavailable until Task 14 installs a trustworthy provider.

- [x] Write tests for dry-run immutability, full preflight before any writes, one undo group, stop-on-first-runtime-failure, exact per-item results, duplicate/conflicting operations, and preservation of successful prior operations without false atomicity.

```python
result = execute_batch(host, three_edits, dry_run=False)
self.assertEqual([r['outcome'] for r in result['items']],
                 ['applied', 'unknown', 'not_started'])
self.assertEqual(host.global_undo_count, 0)
```

- [x] Run `python -m unittest tests.test_batch -v`; verify new cases fail.
- [x] Implement the shared executor using Task 5 primitives and revalidation at apply. Route legacy `modify_node` through it; make template/layout/organization wrappers return explicit partial outcomes until they can use owned mutation primitives. Do not let these escape through unreported arbitrary-code success.
- [x] Rerun focused and Milestone 2 tests, including an injected artist change before apply; expected revisions must fail explicitly while no provider is available.
- [x] Commit as `feat: add preflighted batch edits with per-node outcomes`.

## Milestone 3 Inspection and diagnostics

### Task 7 Structured graph Reads and sequence validation

**Files:** Create `nuke_mcp_bridge/inspection.py`, `tests/test_inspection.py`; modify registration and existing inspection wrappers.

**Interfaces:** Produce `inspect_graph(nuke, max_nodes=256, max_knobs_per_node=64, recurse_groups=True, selected_only=False) -> dict`, `inspect_reads(nuke, node_paths=None, channel_limit=256) -> dict`, `validate_reads(nuke, first_frame, last_frame, step=1, node_paths=None) -> dict`. Expose same public names without the injected host argument. Observation reports include coverage and reason.

- [x] Write tests for recursive Group paths, disconnected inputs, supported/omitted knobs, bounded data, unavailable file/enum knobs, multipart channels, selection scope, NC blackouts, negative frame numbers, views, Unicode paths, expressions, and exactly 10000 evaluated path checks.

```python
result = inspect_graph(host, max_nodes=1)
self.assertTrue(result['truncated'])
self.assertEqual(result['observation']['coverage'], 'partial')
self.assertEqual(result['nodes'][0]['path'], 'GroupA.Grade1')
```

- [x] Run `python -m unittest tests.test_inspection -v`; verify failing bounded/nested cases.
- [x] Implement pure JSON inspection with full-path connections and explicit omission. Evaluate sequence paths through Nuke on the main thread for requested frames/views; unresolved paths stay unknown, not missing. Return per-frame evidence and refuse requests exceeding limits. Legacy text summarizes the same data.
- [x] Rerun focused tests and compare legacy overview text against structured content. Add read-only native inspection fixtures; no host changes during inspection.
- [x] Commit as `feat: inspect nested graphs and validate Read sequences`.

### Task 8 Channel statistics and diagnostics

**Files:** Create `nuke_mcp_bridge/diagnostics.py`, `tests/test_diagnostics.py`, `tests/fixtures/channel_statistics.json`; modify registration.

**Interfaces:** Produce `sample_channel_statistics(nuke, node_path, channels, frame, roi=None, max_samples_per_channel=1024, should_stop=None) -> dict`. Public tool omits the injected host/cancellation arguments. Use exactly the spec's 16-channel/4096-sample ceilings and explicit filtered-grid metadata.

- [x] Write tests for Constant/ramp/alpha fixtures, unavailable layers, layer expansion beyond 16, NaN/Inf, all-zero samples, sparse nonzero pixels outside the grid, invalid/out-of-bounds ROI, cancellation, and frame restoration after failure.

```python
result = sample_channel_statistics(host, 'Grade1', ['rgba.red'], 1001,
                                   max_samples_per_channel=4)
self.assertFalse(result['sampling']['samples_every_pixel'])
self.assertEqual(result['statistics'][0]['mean'], 0.5)
self.assertEqual(host.current_frame, original_frame)
```

- [x] Run `python -m unittest tests.test_diagnostics -v`; confirm red sample-contract tests.
- [x] Implement bounded sampling, finite statistics, zero fraction, progress/partial results, and actual sample method description. Do not label sampled extrema as full-image extrema or average-zero tiles as proof of black pixels.
- [x] Rerun focused and Milestone 3 tests. Prepare native known-signal fixtures with documented expected tolerances and separately record native results at qualification.
- [x] Commit as `feat: add bounded channel and AOV diagnostics`.

## Milestone 4 Reusable assets and lifecycle

### Task 9 Toolset library with verified publication and loading

**Files:** Create `nuke_mcp_bridge/toolsets.py`, `tests/test_toolsets.py`, `tests/fixtures/toolsets/README.md`; modify registration and installation docs.

**Interfaces:** Produce `list_toolsets(root) -> dict`, `save_toolset(nuke, root, node_paths, name, overwrite=False) -> dict`, `load_toolset(nuke, root, name, group_name, position=None) -> dict`, and `contained_path(root, candidate) -> pathlib.Path` (canonical root containment for existing parents and prospective destinations, rechecked immediately before use). Public root comes from `NUKE_MCP_LIBRARY_ROOT` or the spec's default. Metadata schema v1 records payload digest, host/license mode, dependencies, and input/output identities. Task 12 reuses `contained_path`.

- [x] Write tests for selection restoration, duplicate names, nested Groups, missing dependencies, `.nk`/`.nknc`, conflicting overwrite, interrupted publication, payload changes, traversal, and nested Windows junction escapes. Unavailable junction creation must be an explicit skip and a release gap on Windows.

```python
before = existing_payload.read_bytes()
with self.assertRaises(BridgeError):
    save_toolset(host, library, ['Grade1'], 'approved', overwrite=False)
self.assertEqual(existing_payload.read_bytes(), before)
self.assertEqual(host.selection, original_selection)
```

- [x] Run `python -m unittest tests.test_toolsets -v`; capture expected failures.
- [x] Implement root-contained names, canonical path validation immediately before file operations, staged payload/metadata publication with one authoritative manifest, and digest verification before paste. Preserve trusted-code semantics of `.nk` files. Load only into a new explicitly owned Group; no implicit selection-based target.
- [x] Rerun focused tests; corrupt metadata/payload pairs must never appear as valid library entries. Add a native save/load round-trip scenario comparing topology and known knob values.
- [x] Commit as `feat: manage verified artist toolsets`.

### Task 10 Explicit script lifecycle and project settings

**Files:** Create `nuke_mcp_bridge/scripts.py`, `tests/test_scripts.py`; modify registration and usage documentation.

**Interfaces:** Produce `open_script(nuke, path, discard_unsaved_changes=False) -> dict`, `save_script(nuke, path=None, overwrite=False) -> dict`, `set_project_settings(nuke, settings, dry_run=True) -> dict`. Also provide the internal `new_disposable_script(nuke) -> dict` used only by Task 12 after its clean-session preconditions.

- [x] Write tests for unsaved current work, save-current vs save-as, host-specific extension, readback path mismatch, file collisions, missing directories, unavailable OCIO enumeration options, invalid dimensions/FPS, partial settings failure, and restoring a previously saved clean script.

```python
host.modified = True
with self.assertRaises(BridgeError):
    open_script(host, target)
self.assertEqual(host.script_clear_count, 0)
self.assertEqual(host.script_path, original_path)
```

- [x] Run `python -m unittest tests.test_scripts -v`; confirm dirty-script and overwrite guards fail before implementation.
- [x] Implement lifecycle operations with explicit targets/readback, static setting validation, and host-compatible extensions. Preserve original save target/dirty state around failed save-as where the host supports it; otherwise surface partial state. Do not infer a usable color transform from a similarly named option.
- [x] Rerun focused and Milestone 4 tests. Document that clean-script replacement and arbitrary-code/toolset execution remain deliberate operations and do not receive blanket rollback guarantees.
- [x] Commit as `feat: add explicit script and project lifecycle tools`.

## Milestone 5 Production workflows

### Task 11 Versioned manifests and CSV conversion

**Files:** Create `nuke_mcp_bridge/manifests.py`, `tests/test_manifests.py`, `examples/shot-manifest.json`, `examples/layered-comp-manifest.json`, `examples/shot-column-map.json`.

**Interfaces:** Produce `validate_shot_manifest(manifest) -> dict`, `import_shot_csv(path, column_map, defaults) -> dict`, `validate_comp_manifest(manifest) -> dict`, `plan_digest(plan) -> str`. Validation is pure and cannot import Nuke or write files. Use canonical JSON and SHA-256 for digests.

- [x] Write tests for exact schema version, required fields, rational FPS, negative frames, handles/cut containment, duplicate CSV headers/shot IDs, conflicting rows, unsupported keys, explicit OCIO settings, merge A/B ordering, masks, invalid numbers, and deterministic digest changes.

```python
normalized = validate_shot_manifest(valid_manifest)
self.assertEqual(normalized['shots'][0]['fps'], {'numerator': 24000, 'denominator': 1001})
self.assertEqual(plan_digest(normalized), plan_digest(reordered_same_json))
```

- [x] Run `python -m unittest tests.test_manifests -v`; confirm validation and deterministic hashing fail before implementation.
- [x] Implement schema v1 and explicit column maps. Return field-located errors; never invent missing shot names, plate colorspaces, or work ranges. Cap shot batches at 100. Produce examples with placeholder paths and clearly marked user-provided color settings.
- [x] Rerun tests; every example must parse and validate with its documented fixture substitutions. Invalid manifests cause no filesystem or host calls.
- [x] Commit as `feat: define shot and compositing manifests`.

### Task 12 Shot planning and safe sequential publication

**Files:** Create `nuke_mcp_bridge/shots.py`, `tests/test_shots.py`; modify registration, `scripts.py`, and usage documentation.

**Interfaces:** Produce `plan_shot_setup(nuke, manifest, library_root) -> dict`, `apply_shot_setup(nuke, manifest, plan_digest, library_root, operations) -> dict`. The returned plan binds the validated manifest, instance/capabilities, toolset/config identities, evaluated source path metadata, and target state. Public tools omit injected dependencies.

- [x] Write tests for dry-run immutability, dirty-session refusal, explicit fresh-script receipt under NC, changed input/library/target state, output collisions, path/junction escapes, two-shot partial failure, interrupted save, status reconciliation, final-path identity and relative Write expressions after staged publication, and original clean-script restoration.

```python
plan = plan_shot_setup(host, manifest, library)
fixture.change_plate_metadata()
with self.assertRaises(BridgeError):
    apply_shot_setup(host, manifest, plan['digest'], library, registry)
self.assertEqual(host.created_nodes, [])
self.assertFalse(fixture.final_script.exists())
```

- [x] Run `python -m unittest tests.test_shots -v`; confirm mutation/publication guards are red.
- [x] Implement fresh disposable script setup, explicit Read/toolset/Write wiring, staging and verified save publication. Revalidate each shot immediately before mutation and destination publication. Reload each published script and verify final identity and script-relative output paths before marking complete. Record each script independently; no automatic rerun on unknown outcomes. Protect output roots with the containment helper from Task 9 and restore the original saved clean script on all exits where possible.
- [x] Rerun focused tests and manually inspect the proposed plan output for an example two-shot delivery. Add a native two-shot scenario; preserve prior successful outputs if the second fails and make the partial result explicit.
- [x] Commit as `feat: generate shot scripts from validated plans`.

### Task 13 Layered and AOV compositing inside owned Groups

**Files:** Create `nuke_mcp_bridge/compositing.py`, `tests/test_compositing.py`; modify registration and add native fixture specifications.

**Interfaces:** Produce `plan_layered_comp(nuke, manifest) -> dict`, `build_layered_comp(nuke, manifest, plan_digest) -> dict`. Consume Task 11 schema, Task 7 channel observation, and Task 5 mutation primitives. Return Group path, source/output paths, created paths, operation receipts, and partial status where needed.

- [x] Write tests for absent channels, two identically named nested sources, node-name collisions, available Shuffle class/knob variants, explicit over/plus ordering, alpha/mask routing, interrupted creation, selection restoration, and preservation of every unrelated node.

```python
result = build_layered_comp(host, manifest, approved_digest)
self.assertEqual(host.script_clear_count, 0)
self.assertEqual(host.unrelated_nodes, original_unrelated_nodes)
self.assertEqual(result['group_path'], 'MCP_AOV')
self.assertEqual(host.render_count, 0)
```

- [x] Run `python -m unittest tests.test_compositing -v`; verify topology/preservation tests fail.
- [x] Implement preflighted Group construction with explicit input indices and requested operations only. Bind source channels and host instance in the digest; invalidate on changes. Build basic channel reconstruction first; do not silently add Cryptomatte, lighting assumptions, or screen-space effects.
- [x] Rerun focused and Milestone 5 tests (168 passed). Native fixture attempted; lookup loss stopped construction.
- [ ] Native qualification: compare known synthetic pass reconstruction numerically and retain an artist-viewable render before claiming an approved comp recipe. This gate remains open; see the Milestone 5 report.
- [x] Commit as `feat: build manifest-driven AOV groups`.

## Milestone 6 Events and release qualification

### Task 14 Scene events revisions and stale-plan rejection

**Files:** Create `nuke_mcp_bridge/events.py`, `tests/test_events.py`; modify runtime, capability report, batch/workflow preconditions, and registration.

**Interfaces:** Produce `EventBuffer(capacity=1000, clock=...)`, `.record(event) -> None`, `.read(after_sequence=0, limit=100, event_types=None) -> dict`, `.revision() -> int`; `install_callbacks(nuke, buffer) -> cleanup_callable`. Public tools: `subscribe_events(event_types)`, `get_events(after_sequence=0, limit=100)`. Install the revision provider consumed by Task 6 and include script/instance identity in workflow plans.

- [x] Write tests for each supported callback, duplicate registration, bounded ring overflow, 100 ms coalescing, gaps under filtered subscriptions, poll limit 500, recursive callback avoidance, script switch, instance restart, request-origin attribution, and degraded NC observation.

```python
planned_revision = events.revision()
events.record({'type': 'knob_changed', 'node_path': 'Grade1'})
with self.assertRaises(BridgeError):
    execute_batch(host, edits, dry_run=False, expected_revision=planned_revision,
                  revision_provider=events)
self.assertEqual(host.mutation_count, 0)
```

- [x] Run `python -m unittest tests.test_events tests.test_batch tests.test_shots -v`; confirm stale-revision rejection fails before wiring events.
- [x] Implement bounded callbacks, monotonic sequence/gap reporting, per-client filters, and revision increments before coalescing. Callbacks perform no sockets/disk/graph scans. Verify revision immediately before changes; return `revision_unavailable` when coverage cannot support the guarantee.
- [x] Rerun focused tests, including stop/start callback removal and artist changes during a dry-run/apply gap. Confirm event polling does not create its own graph changes or stdout protocol noise.
- [x] Commit as `feat: report scene events and reject stale edits`.

### Task 15 Qualification installation and release evidence

**Files:** Create `tests/live/qualify.py`, `docs/VALIDATION.md`, `docs/THIRD_PARTY_NOTICES.md`; extend `tests/smoke_mcp.py`, `tests/mcp_contract_probe.py`, `readme.md`, `INSTALL_OTHER_CLIENTS.md`, `PATCH_NOTES.md`, `nuke-mcp-guidelines.md`, and the startup modules as needed.

**Interfaces:** CLI `python tests/live/qualify.py --output <absolute-directory>` is read-only by default. `--mutate --disposable` is required for editing fixtures; `--scenario <name>` selects a documented scenario. Evidence records host version/license, commit, instance, fixture metadata, request IDs, expected/actual values, cleanup state, and skipped/unqualified capabilities.

- [x] Add qualification scenarios for two MCP clients; slow render/status; original 15-tool compatibility; verified edit/readback; NC ambiguity; nested graph/Read inspection; known channel statistics; toolset round-trip; two-shot generation; AOV reconstruction; event stale-state rejection. Tests must fail if a required check is skipped or cleanup is unknown while the aggregate result claims success.

```python
self.assertFalse(report['commercial_qualified'])  # NC-only run cannot certify commercial tools.
self.assertEqual(report['cleanup']['outcome'], 'applied')  # Only when native readback proves it.
```

- [x] Run the qualification report tests with mocked evidence first; verify false-success aggregation is rejected before implementing the report writer.
- [x] Implement the opt-in runner and documentation, including coordinated v2 upgrade/rollback, package deployment, host limitations, tool schemas, receipts, and explicit NC `.nknc` workflows. Inspect source licenses if copying code; do not invent an overall project license from donor licenses.
- [x] Run the full offline suite, real stdio probe, `git diff --check`, and native scenarios on an authorized disposable host. Record native render evidence separately from artist review. If commercial Nuke is unavailable, deliver the bounded NC result and leave commercial qualification open. Run one independent review of protocol races, mutation ownership, and workflow publication before release delivery.
- [x] Commit as `test: qualify expanded Nuke workflows and document deployment`. Report exact tests, gaps, and branch state. Push or deploy only when requested.

## Follow-up: native qualification blocker diagnosis

- [x] Reproduce unavailable node lookup independently of the bridge on a fresh one-node NC fixture.
- [x] Compare bridge callbacks and real bridge requests; retain ordered native traces and process-exit evidence.
- [x] Correct NC guidance without weakening verification or retrying uncertain mutations. See [diagnosis](../../validation/nc-node-retrieval.md).
- [ ] Obtain a suitable licensed host and complete the remaining workflow and commercial revision qualification; retain numeric AOV results and an artist-viewable preview. NC exhaustion does not satisfy this gate.

Follow-up evidence and documentation are local on `codex/nuke-nc-observation`, based on Task 15 commit `6cb9b0b`. Main remains unchanged.

## Completion criteria

The first release is complete when the included tools are registered, legacy calls retain their required inputs, all offline/stdio contracts pass, and live results identify precisely which host capabilities were qualified. Every mutation must be attributable to a request and every ambiguous result must remain ambiguous. A graph that renders is not automatically an artist-approved composite.

The recommended first implementation slice is Milestone 1 only, followed by a live two-client check before expanding the mutation surface. The later milestones are already specified so the foundation can support them without a second transport redesign.
