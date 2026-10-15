# Qualification and release boundaries

The qualification CLI records evidence against one running Nuke bridge. It never certifies a
commercial release or artist approval from an NC result. The current results and gaps are in
[Task 15 evidence](validation/task-15.md); earlier runs remain under `docs/validation/`.

## Run the checks

Use the same checkout for the add-on and external Python process. Start a GUI listener first.
A new output directory is required, so evidence from a previous attempt is never overwritten.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -q
.\.venv\Scripts\python.exe tests/mcp_contract_probe.py --slow --output D:/evidence/offline-stdio.json
.\.venv\Scripts\python.exe tests/live/qualify.py --output D:/evidence/native-read-only
```

The default native run is read-only with respect to the scene: two stdio clients, original tool
schemas, and NC coverage/refusal checks. Event subscriptions are connection-local. It writes
local evidence files. `--port` selects a listener (default 9877). Exit 0 means **every selected
scenario** passed, not that the unselected scenarios or a product release are qualified.
Exit 1 records failed/incomplete native checks; invalid arguments fail before contacting Nuke.

Create a fresh **exclusive disposable host** for each mutating scenario. Never use an artist's
working session. Set `NUKE_MCP_DISPOSABLE_SESSION=1` and `NUKE_MCP_LIBRARY_ROOT` to a new private
library directory in that process's environment before launch. Record its PID and load a fixture.
The runner requires all four arguments below and checks the PID, exact script path, instance,
and environment opt-in. These checks detect identity changes; they are not a lock against someone
editing the same disposable host concurrently. Do not interact with that host during the run.

```powershell
.\.venv\Scripts\python.exe tests/live/qualify.py --port 19887 `
  --scenario event-stale-state --mutate --disposable --pid 12345 `
  --fixture D:/fixtures/events_fixture.nk --output D:/evidence/native-events
```

`--scenario` can repeat for read-only checks. Only one mutating scenario is allowed per run;
there is no automatic reset, mutation replay, or speculative deletion after an unknown result.
The old `tests/smoke_mcp.py --mutate` entry point directs callers to this guarded runner.

| Scenario | Fixture / evidence |
| --- | --- |
| `two-clients` | Any running host; two real stdio processes, eight correlated reads and distinct client identities. |
| `legacy-tools` | Any host; records all 15 original required-input schemas, alongside the 37-tool count. This verifies compatibility of discovery and shared read calls, not native execution of every legacy mutator. |
| `nc-ambiguity` | NC host; partial/unknown graph coverage and refusal of explicit revisions. Non-NC is not a passing substitute. |
| `nested-read` | Copy `tests/live/inspection_fixture.nk` to a private directory; provide `--pid --fixture`. Checks both nested SameName paths, truncation, Read identity and missing sequence. Does not sample or set frames. |
| `channel-statistics` | Fresh inspection fixture; requires mutation opt-ins because sampling temporarily changes frame. Checks constant RGBA and ramp means, sampling limits, frame/proxy/selection preservation. |
| `verified-edit` | Fresh minimal `Root {}` fixture; creates one unique Grade, verifies a batch label/position edit and deletion. Uncertain creation is retained, never replayed or guessed at cleanup. |
| `toolset-roundtrip` | Fresh copy of `tests/live/library_fixture.nk`, empty private library. Checks copy/paste, known label/topology and selection; also retains settings/save lifecycle receipts. |
| `two-shot` | Run `tests/live/prepare_workflow_fixture.py D:/fixtures/new-shot-run`, load its workflow fixture. Plans/applies two `.nknc` scripts and verifies original restoration. |
| `aov-reconstruction` | Separate fresh workflow fixture. Builds one plus reconstruction, compares four sampled channels within 1e-5 and retains an `aov-review.png` render. This is not artist approval. |
| `event-stale-state` | Fresh minimal Root fixture. Changes FPS once, checks revision advance and rejects an old revision, then restores that field with readback. NC only qualifies refusal of unavailable coverage, not commercial stale-revision coverage. |
| `slow-render` | Fresh fixture with `MCP_Review` Write resolving at the current frame to a **new file within the future evidence directory**. Prepare an appropriately slow graph in advance. Requires a native render lasting at least 15 seconds, running status, completion and nonempty output. A fast render fails this particular timing gate. |

The helper fixture templates are trusted executable Nuke scripts. Copy them to new directories;
do not reuse a folder with previous shot outputs, library entries, or preview files. The workflow
fixture helper creates its directory exclusively and includes a generated 4x4 PNG.
The NC-specific workflow and library probes use `.nknc` destinations. Commercial qualification
requires adapting those fixture destinations explicitly and separately confirming the host license;
the current capability API reports non-NC license mode as `unknown`.

## Evidence contract

`report.json` contains the timestamp, Git commit and dirty flag, external Python, host
version/license/flavor, instance, fixture path/digest/PID, runner source digest, selected scenarios, required checks,
expected/actual values, qualified and unqualified names. `receipts.json` is updated after each
bridge call. Scenario files preserve detailed native receipts and failures. The stdio probe
also preserves the schema dictionary and tool count. Rendering retains status observations.

The reducer owns the list of required checks. Missing, skipped, false or malformed checks cannot
pass. Neither a probe's `passed: true` nor a successful transport response overrides unknown
cleanup. Cleanup meanings:

- `not_needed`: no graph mutation was requested.
- `applied`: a specific restored field has a successful native receipt and matching readback;
  the scope is recorded. It does not imply graph/disk rollback or a clean dirty flag.
- `retained_disposable`: the final process/script ownership is verified and fixture changes/output
  files are deliberately retained for inspection. It is not deletion, restoration, or process exit.
- `unknown`: restoration, deletion or ownership could not be established; the scenario cannot pass.

Close the owned disposable process after reviewing its artifacts. Preserve failures alongside
later fresh attempts. A timeout remains ambiguous; use the retained request and instance IDs to
query status before deciding on any further work. Separate any later process-exit evidence from
field restoration evidence. Native render output and numerical checks remain separate from
human visual review. `artist_approved` and `commercial_qualified` are deliberately false.

## Deployment and rollback

See [installation](../INSTALL_OTHER_CLIENTS.md) for the coordinated protocol-v2 procedure.
No startup or runtime dependency change is required for Task 15. Deploy the add-on too: native
qualification corrected its Root proxy API calls. Deploy the complete repository,
including `nuke_mcp_bridge/`, not a single add-on file. Run the default qualification after a
coordinated upgrade. Keep the previous complete checkout and client configuration for rollback.

Tool input schemas are available through MCP `tools/list`; don't derive arguments from UI text.
Detailed contracts: [verified edits](verified-edits.md), [inspection](inspection.md),
[toolsets/lifecycle](toolsets-and-lifecycle.md), [workflows](production-workflows.md),
[events](scene-events.md). Dependencies and provenance are recorded in
[third-party notices](THIRD_PARTY_NOTICES.md).
