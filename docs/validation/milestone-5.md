# Milestone 5 validation — 2026-10-14

Implemented Tasks 11–13 on `codex/nuke-production-workflows`, based on `b7ed436`.
This delivery is local; no push, merge, deployment, or permanent Nuke startup changes.

## Verified

- **168 offline tests passed**, no skips. Coverage includes schema/CSV validation, digest changes,
  callback script switches, source/toolset changes, publication collisions, partial two-shot results,
  original restoration, native knob variants, AOV topology, and an actual Windows junction escape.
- Final real offline stdio passed with two clients, all **35 tools**, and eight concurrent reads.
  All five new tools ran through MCP; the other client reconciled the completed shot receipt.
- Native NC **17.0v4** live two-client stdio passed: distinct sessions, one host instance,
  eight concurrent reads, main-thread execution, and expected missing-node error semantics.
- Native read-only shot and comp planning and saved-clean original restoration passed.
- Both owned disposable hosts were closed; process exit was verified.

## Native qualification remains incomplete

Initial owned process **134928**, instance `0adb77f2-dda8-4d6a-8027-6d99bf2ee412`, refused the
fixture's `default` colorspace because it was not an exact observed enum option. No shot was
published. Comp creation retained `MCP_AOV` as a created path, but lookup became unavailable;
the receipt did not claim a verified Group. Native facts also identified `ChannelMask_Knob` on
Write channels; a bounded setter compatibility fix and regression test were added.

A fresh owned process **155152**, instance `b0285955-1af5-4089-9188-552e1d85be7d`, used the
corrected fixture's exact observed `linear` option. Shot application obtained an explicit fresh-script
receipt, then stopped when lookup of newly created `Plate_0` became unavailable. Its receipt reports
no completed shots and `published:false`; the saved clean original was restored. Comp construction
then stopped after `MCP_AOV` creation with unknown identity. Neither uncertain mutation was replayed.

**Native two-shot publication, the toolset pipeline, full AOV construction, numeric reconstruction,
and artist-viewable rendering remain unqualified.** No numeric sampling or preview rendering was
attempted after the failed build. The retained PNG is a source fixture, not a rendered comp.
Commercial Nuke, NukeX/Studio, other platforms/versions, and artist acceptance remain open.
Earlier milestones' qualification gaps are unchanged. Offline topology is not native pixel evidence.

## Independent review and fixes

One fresh independent review of `b7ed436..06e64fc` found two important issues:

1. A constructor callback could switch scripts before later shot writes/publication. A failing
   regression reproduced it. Apply now checks the owned root handle and path at each mutation
   boundary, follows identity only after explicit lifecycle operations, and refuses unsafe restoration.
2. Canonically equivalent manifests could produce different Grade/Blur order. A failing regression
   reproduced it; schema v1 now always builds Grade then Blur.

The same fix pass added component-level comp callback guards, native channel-mask compatibility,
changed-toolset rejection coverage, and nested junction containment coverage. The final 168-test suite,
offline stdio, and final native probes ran after the production fixes. No minor findings were deferred.

## Scope rulings

- Milestone 5 only. Task 14's revision/event guarantee and Task 15's release qualification remain pending.
  Review covered inherited lifecycle/mutation interfaces, not a fresh audit of every earlier subsystem.
- Shot manifests declare an output root; unsupported source expressions fail preflight instead of being
  guessed. Callers must supply supported explicit sequence paths and create directories before planning.
- Direct node and mask sources must share a parent scope. Cross-Group sources must expose Group outputs;
  arbitrary internal connections would require modifying unrelated interfaces.
- File sources require one observed matching Read for channel preflight. New assets must be inspected
  through a Read first; planning does not create hidden probe nodes.
- Native lookup failures preserve receipts and partial evidence. They do not justify replay or a claim
  that a failed mutation left the graph unchanged.

## Evidence and reproduction

- [Final offline stdio](milestone-5-evidence/stdio.json)
- [Native live two-client stdio](milestone-5-evidence/live.json)
- [Initial native fixture outcome](milestone-5-evidence/native-initial.json)
- [Final native workflow outcome](milestone-5-evidence/native-final.json)
- [Initial host close](milestone-5-evidence/close-initial.json) and [final host close](milestone-5-evidence/close.json)
- [Source PNG](milestone-5-evidence/source-plate.png) and [historical native fixture](milestone-5-evidence/native-fixture.nk)

The historical fixture contains the original absolute scratch paths. Generate a fresh portable fixture
with the supplied helper; do not reuse those historical paths for a new run.

```powershell
python -m unittest discover -q
python tests/mcp_contract_probe.py --output offline.json
python tests/mcp_contract_probe.py --live --port 19877 --output live.json
python tests/live/prepare_workflow_fixture.py <new-owned-directory>
python tests/live/workflow_probe.py --pid <owned-host-pid> --port 19877 --directory <owned-fixture-directory> --output native.json
```

Before the workflow probe, launch the generated script in a new owned disposable GUI process with
`NUKE_MCP_DISPOSABLE_SESSION=1`, the intended checkout, and an owned library/output directory.
The probe verifies PID and fixture identity before mutation. It saves the clean original, applies each
workflow once, and attempts numeric/preview checks only after verified construction. See
[fixture instructions](../../tests/live/workflow-fixtures.md) and [workflow contracts](../production-workflows.md).
