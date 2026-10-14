# Task 14 validation — 2026-10-14

Implemented scene events, revision checks, and workflow invalidation on `codex/nuke-scene-events`,
based on `3d3c84d`. Before implementation, `codex/nuke-production-workflows` was pushed to GitHub
and its remote SHA was verified as `3d3c84d74cddadefa4a5bedb0494209362ee026c`.
Task 14 is a local delivery; Task 15 release qualification remains pending. Main was not changed.

## Verified

- **190 offline tests passed**, no skips. Coverage includes callback registration/removal/restart,
  recursion and missing identity, bounded overflow, filtered cursor progress, 100 ms coalescing,
  revision increments before coalescing, request attribution through generator steps, per-client
  filters, stale workflows, unrelated changes between array components, and NC refusal.
- Final real offline and live two-client stdio passed with **37 tools** and eight concurrent reads.
  New subscription and polling tools return structured read-only receipts. Offline clients received
  distinct filtered views of the same events, and NC guarded edits failed before mutation.
- Native Nuke NC **17.0v4**, owned disposable process **149744**, instance
  `fd9ae4fd-de19-421c-a95b-c46871586051`: knob events carried the request ID of the initiating edit,
  sampled frame notifications arrived, revisions advanced, no knob values/callback code appeared,
  and a guarded batch was refused with `revision_unavailable`/`not_started`.
- Native FPS and frame changes were read back, then restored with affirmative readback.

## Initial native finding

The initial owned process **143280**, instance `507a5b30-aae0-4532-80a4-34736c4dc65b`, passed all
checks except frame notification. Its Root-scoped `updateUI` callback did not report the held frame
change. A failing regression reproduced a runtime with no Root UI notifications. The bridge now
samples one scalar frame value on the existing main-thread queue timer in addition to `updateUI`.
The final fresh native process passed all eight checks. Neither run replayed an uncertain mutation.

## Qualification boundaries and rulings

- NC remains degraded even when callback delivery is observed. Explicit revision guarantees are
  refused on NC, unknown license observation, older/unqualified callback coverage, or callback failures.
  Cost: NC callers use existing target validation/readback without an `expected_revision` guarantee.
- Frame observation is sampled. A Root-only callback proved insufficient, so the main-thread timer
  supplies a bounded scalar sample. Cost: transient changes between samples can still be missed.
- Revisions are optimistic and scoped to the server instance. Contiguous callbacks attributed to
  the current request can advance its edit sequence; other/unattributed changes invalidate it.
  Synchronous artist callbacks triggered by an edit share its request attribution. This is not a
  lock or proof against callback-suppressed changes.
- Workflow plans bind observed revision state even under NC, but this cannot upgrade degraded
  graph coverage to a complete guarantee. Native commercial guarded-edit success and all prior
  shot/AOV/toolset qualification gaps remain open.
- This task implements events only. Task 15's broad release audit, consolidated qualification runner,
  native rendered-image correctness, commercial host coverage, and artist acceptance remain pending.

## Evidence and reproduction

- [Offline stdio](task-14-evidence/stdio.json) and [native two-client stdio](task-14-evidence/live.json)
- [Initial native result](task-14-evidence/native-initial.json) and [final native event result](task-14-evidence/native.json)
- [Initial host close](task-14-evidence/close-initial.json) and [final host close](task-14-evidence/close.json)

```powershell
python -m unittest discover -q
python tests/mcp_contract_probe.py --output offline.json
python tests/mcp_contract_probe.py --live --port 19877 --output live.json
python tests/live/events_probe.py --pid <owned-host-pid> --port 19877 --directory <owned-fixture-directory> --output native.json
```

For the native event probe, launch a fresh owned GUI process with `NUKE_MCP_DISPOSABLE_SESSION=1`,
load an `events_fixture.nk` in the specified directory, and start this checkout's bridge. A minimal
Root-only fixture with FPS 24 and frames 1–3 is sufficient. The probe checks PID, disposable opt-in,
and exact script path before modifying only FPS/current frame. It restores those fields only while
script identity still matches. The default two-client probe remains read-only.

See [event semantics](../scene-events.md) for cursor handling, save-notification timing, and limits.
