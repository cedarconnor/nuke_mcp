# Milestone 4 validation — 2026-10-14

Implemented Tasks 9–10 on `codex/nuke-toolsets-lifecycle`, based on `81e7108`.
This delivery is local; no push, merge, deployment or permanent Nuke startup changes.

## Verified

- **137 offline tests passed**, no skips, including an actual nested Windows junction escape fixture.
- Real offline stdio: two clients, all **30 tools**, eight concurrent script reads, distinct session/request
  identities and one host instance. All six new tools ran through MCP, including dry-run and read-only outcomes.
- Native Nuke NC **17.0v4**, explicitly owned disposable process **154456**, instance
  `9a579463-ba1a-4e87-8b8a-a654b2ee9e74`: live two-client stdio passed, eight concurrent script reads,
  main-thread execution and expected missing-node error semantics.
- Native project settings dry-run/apply (FPS, frame range, 4x4 format), save-as to `.nknc`, collision refusal,
  save-current and reopening the saved clean script passed. Observed selection was preserved.
- The owned host was closed after qualification; process exit was verified.

## Native limitation

The complete native toolset scenario **did not pass**. `nodeCopy` returned false after creating a
410-byte `.nknc` payload. The bridge reported `partial`, with `published:false`, and did not create
an authoritative manifest. Loading was therefore not attempted. No uncertain mutation was replayed.
Later native `allNodes()` returned an empty list; this does not establish an empty graph in NC.
Toolset topology/known-knob round-trip is covered offline but remains unqualified in native Nuke.

The first probe also exposed native API differences: environment defaults must be explicit strings,
and root FPS/frame knobs report `Array_Knob`. Regression tests and narrow compatibility fixes preceded
the passing lifecycle/settings probe. Final review then fixed failed-save callback preservation and
script-switch detection; those callback failure paths were verified offline, not injected into native Nuke.
The native success evidence predates those final recovery/identity refinements.

Commercial Nuke, NukeX/Studio, other host versions/platforms, native toolset round-trip and production
artist acceptance remain open. File hashes prove observed saved bytes, not complete graph serialization
or absence of executable callbacks. Existing Milestone 2–3 native qualification gaps remain open.

## Independent review

One fresh review of `81e7108..52b6c4e` found two important issues:

1. Failed-save recovery could reset a clean dirty flag over callback edits, or relabel a switched script.
   Added failing tests for edits, switches and rename-callback edits; recovery now preserves those states.
2. Project settings could continue through a script path switch while handles remained valid.
   Added a failing callback-switch regression; apply now binds script identity between writes and at readback.

Both were fixed in one regression-driven pass; the full suite and offline stdio passed afterward.
No minor findings deferred. Scope ruling: Milestone 4 only, retaining the existing isolated worktree;
GitHub publication remains a separate step.

## Evidence and reproduction

- [Final offline stdio](milestone-4-evidence/stdio.json)
- [Native live two-client stdio](milestone-4-evidence/live.json)
- [Initial native compatibility failures](milestone-4-evidence/native-initial.json)
- [Native lifecycle/settings and toolset limitation](milestone-4-evidence/native.json)
- [Owned host close receipt](milestone-4-evidence/close.json)

```powershell
python -m unittest discover -s tests -p 'test_*.py' -q
python tests/mcp_contract_probe.py --output offline.json
python tests/mcp_contract_probe.py --live --port 19877 --output live.json
python tests/live/library_probe.py --pid <owned-host-pid> --port 19877 --directory <owned-output-directory> --output native.json
```

The native library probe mutates only a newly owned disposable session opened with
`tests/live/library_fixture.nk`. Configure its library root to an owned scratch directory before
launch. It saves a `.nknc` script, replaces the fixture through explicit open, and must never target
an artist's working session. The read-only two-client probe does not authorize replaying failed edits.
