# Task 15 qualification — 2026-10-14

Task 15 implements the opt-in qualification runner, fail-closed reports, deployment/rollback
instructions, and source/dependency notices. It does not certify the outstanding native
workflow capabilities or commercial Nuke. Branch: `codex/nuke-release-qualification`, based
on Task 14 commit `1238ba2c71f4b8c2efe1cb8527157f8f31ae7b42`.

Task 14 was pushed to `origin/codex/nuke-scene-events`; local and remote SHA matched exactly.
Task 15 work is local until separately pushed. Main remains at `59d8ff6`.

Follow-up: the [NC retrieval investigation](nc-node-retrieval.md) reproduced missing
handles and empty enumeration on a one-node fixture without the bridge. That narrows
the observation failure to a native NC constraint; it does not retroactively qualify
the failed workflow scenarios below.

## Verification

- Full offline suite: 221 tests pass, no skips after the review fixes.
- Real stdio contract: 37 tools, all 15 legacy required-input schemas, two clients, eight
  correlated reads, and a simulated render lasting 16.11 seconds passed in the final stdio run. This is transport
  evidence, not native pixel evidence.
- Native read-only default: two clients, legacy schema compatibility and NC coverage/refusal
  checks passed on Windows, Nuke Non-commercial 17.0v4, external Python 3.11.11.
- Native events: revision advance, unavailable-coverage refusal and FPS restoration passed.
  This is NC refusal evidence, not a commercial stale-revision guarantee.

Evidence directories include failed attempts. The first verified-edit and nested-read attempts
were refused because the host still reported `Root`; no fixture edits ran. After correcting the
local launcher and waiting for the exact fixture path, new hosts produced the `*-ready` reports.
Do not combine a failed attempt with a later partial attempt into a passing scenario.

| Native scenario | Result |
| --- | --- |
| Verified edit | Unqualified: creation returned unknown when NC node lookup became unavailable. No mutation replay or guessed deletion. |
| Nested graph / Read | Partial: expected nested paths initially observed; later truncation/Read sequence checks failed with unavailable lookup. State preservation observed. |
| Channel statistics | Unqualified: known constant/ramp lookup unavailable; original frame/proxy/selection retained. |
| Toolset roundtrip | Unqualified: uncertain save/copy stops further helper operations. Cleanup remains unknown, even though the disposable process is later closed. |
| Two-shot | Planning and original-script restoration passed; apply returned partial due to edit readback mismatch. No shot published. |
| AOV reconstruction | Preflight stopped on unavailable MCP_Light lookup. Build, numeric comparison and preview not attempted. |
| Native slow-render | Passed after fixing Root proxy API access: one PNG render with a controlled 16-second beforeRender delay, running-status observations and nonempty output. This tests responsiveness/duration handling, not render performance or image correctness. |

The initial render failed because `nuke.proxy()` is absent. Foundry's installed Root API docs
and `nukescripts/renderdialog.py` confirm `nuke.root().proxy()` / `.setProxy()`. A regression
reproduced that failure before fixing all three proxy calls. The fresh `slow-render-proxy-fixed`
report passed. Initial failure evidence remains in `slow-render-ready`; its cleanup label predates
the stricter unknown-outcome cleanup reducer and is not used as current qualification.

All thirteen owned native processes (including early refused starts and the post-review render/edit runs)
were observed exited; unrelated pre-existing Nuke processes were left alone. Per-attempt runner
reports retain unknown graph cleanup even after process exit. Generated fixture files remain
under task scratch and evidence directories. No AOV preview or shot publication is claimed.

The runner records Git HEAD plus dirty state and its own source SHA-256 (added after the initial
read-only/event attempt). These native attempts ran from the implementation worktree before its
Task 15 commit; they do not falsely claim to have run from an already committed release.
The fixture digest, host instance/PID, request receipts, expected/actual values and cleanup scope
are retained. Process-close/exit receipts are separate artifacts, not retroactive graph cleanup.

## Independent release review

One independent review covered false-success/cleanup claims, protocol races, mutation ownership,
render output binding, and workflow publication integration. It found two Important issues:

1. Preflight used the current proxy filename but rendering defaulted to full resolution. Fixed
   by resolving with `nuke.REPLACE`, binding the same explicit proxy/frame context, and refusing
   changed context before submission. Regression tests use the actual add-on generator to prove
   that an existing full-resolution file outside the evidence root remains untouched.
2. The edit smoke helper could delete after an ambiguous batch timeout or host replacement.
   It now retains uncertainty across stdio receipts, skips cleanup mutations after ambiguity,
   and checks instance/PID/script before every mutation, including deletion.

Both were reproduced with failing tests and fixed in one pass. The older smoke test expecting
deletion after an uncertain dry run was updated to the corrected contract. Full suite: 221/221.
The task-routing status header was also corrected: its stale Task 15 pending state could cause
later work to repeat this task. No deferred minor findings remain. No second review was run.

Post-review native evidence is in `slow-render-reviewed`: proxy enabled, concrete
`proxy.0000.png`, 16.20-second render, no full-resolution file created. This is a controlled
beforeRender delay, not a performance benchmark or image-quality test. The native edit rerun
retains its own report; unknown NC creation still prevents a full edit qualification.

The reviewer declined commercial/other-host/artist certification, successful native toolset,
shot and AOV correctness beyond the failed attempts, an exhaustive historical re-audit, and
concurrent artist or malicious fixture behavior. Those limits are accepted: real-host and artist
qualification remain open; inherited defects outside the sampled integration review may remain;
the runner requires an exclusive host and trusted fixture scripts.

## Boundaries and decisions

- One mutating scenario per fresh exclusive disposable host. Ownership checks do not lock out
  artist edits; the host must not be shared during qualification. Cost: extra fixture launches.
- `retained_disposable` means final identity verified with graph/files intentionally retained.
  It is not rollback or host exit. Unknown operation/cleanup never passes. Cost: artifact review
  and process closure remain explicit responsibilities.
- NC fixtures use `.nknc`; the runner never promotes NC or unknown license facts to commercial
  certification. Other versions/platforms and NukeX/Studio remain unqualified.
- Commercial revision coverage, native mutation/inspection limitations, toolset/shot/AOV
  correctness and artist approval remain separate gates. Render completion is not recipe approval.
- No donor source was copied, and no overall project license was inferred from dependency licenses.
- Keep the existing isolated worktree and scratch evidence. No permanent startup deployment or
  cleanup of prior scratch is part of this change.

See [runner usage and schemas](../VALIDATION.md), [deployment](../../INSTALL_OTHER_CLIENTS.md),
and [third-party notices](../THIRD_PARTY_NOTICES.md).
