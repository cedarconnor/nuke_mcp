# Milestone 3 verification — 2026-10-14

Tasks 7–8 are implemented on `codex/nuke-inspection`, based on Milestone 2
commit `de4aca9`. Task commits: `e1e274c` and `1f35cae`; review fixes: `146e9bf`.
This branch includes the prior local Milestone 2 work. No push, merge, or permanent
Nuke startup change was performed for this milestone.

## Results

| Check | Result |
| --- | --- |
| Full `unittest` discovery | 107 passed, no skips |
| Real offline two-client stdio probe | Passed; legacy required arguments, 24 tools, structured inspection, sequence validation, statistics, batch operations, errors and correlation |
| Live two-client stdio probe | Passed; eight reads across distinct sessions, shared host instance, main-thread execution and expected missing-node error |
| Initial native graph inspection | Expected nested identities and truncation observed; NC coverage labeled partial |
| Final native inspection/diagnostic fixture | Incomplete: NC enumeration and direct lookup became unavailable; Read/sequence/Constant/ramp checks did not pass |
| State preservation in final native probe | Before/after script, frame, proxy, selection and PID matched |
| Commercial Nuke, other platforms/versions, native pixel correctness | Unqualified |

Native host: Nuke Non-commercial 17.0v4 on Windows; external Python 3.11.11.
Owned disposable PID 152572, port 19877, instance
`929bdbc4-5024-45dd-90b2-d005ae7c6fe7`. The seven-node fixture was loaded from
`tests/live/inspection_fixture.nk`. It contains two nested nodes named SameName,
a Constant, a ramp and a deliberately missing Read. The initial graph read
observed all seven nodes. Later direct lookup failed and enumeration returned
empty, so positive earlier observation was not generalized into complete coverage.
The final code was reloaded before the last native probe. The owned fixture was
closed without saving after verification.

The native runner exits nonzero if any required check fails. No fake-host result
is substituted for a missing native result. The known-signal fixture and expected
tolerances remain available for qualification on a reliable host.

## Independent review

The review of `de4aca9..1f35cae` found three important issues. All were reproduced
in failing regressions and fixed in one pass:

1. Channels and ROI were initially validated at the artist's current frame.
   Argument syntax is now checked first; target-dependent validation happens
   after establishing the requested frame inside the restoration scope.
2. Extreme finite statistics could overflow before restoration. The mean now
   uses magnitude scaling, and restoration precedes summary calculation. Tests
   cover both maximum finite floats and an injected summary failure.
3. Read inspection lost completed records on cancellation. It now attaches
   accumulated evidence, marks truncation/coverage, and checks between views.

No minor findings were deferred. The reviewer did not qualify native timing,
sampling or licensed behavior; those limits remain explicit.

## Decisions and costs

- Execute Milestone 3 only in the existing isolated worktree. Later milestones
  and delivery remain pending; the main checkout remains unchanged.
- Add output caps of 4 MiB evidence, 128 input slots, 64 views, and bounded knob
  values to keep transport results usable. Larger requests require narrower
  scope, with truncation/omissions reported.
- Return unknown for unqualified Read timing remapping and range handling.
  Retimed dependency validation remains unavailable rather than guessing files.
- Keep native sampling, negative-frame behavior and commercial/NC behavior
  unqualified where the fixture could not obtain evidence. A reliable native
  host is still needed to close those gaps.
- Check cancellation between synchronous native calls. One blocked enumeration,
  evaluation or sample can delay cancellation; Python cannot safely preempt it.
- Keep prior and future milestone correctness outside this review's scope,
  testing inherited interfaces where used. Earlier documented limitations still
  apply; this is not a new full-repository qualification.

## Evidence and reproduction

- [Offline stdio evidence](milestone-3-evidence/stdio.json)
- [Live two-client evidence](milestone-3-evidence/live.json)
- [Initial native observation](milestone-3-evidence/native-initial.json)
- [Final native fixture evidence](milestone-3-evidence/native-final.json)

```powershell
python -m unittest discover -s tests -p 'test_*.py' -q
python tests/mcp_contract_probe.py --output offline.json
python tests/mcp_contract_probe.py --live --port 19877 --output live.json
python tests/live/inspection_probe.py --pid <owned-host-pid> --port 19877 --output native.json
```

The last two commands require the matching add-on running in the explicitly
owned disposable fixture. Read-only inspection does not guarantee that trusted
Nuke expressions or filename filters are free of side effects. See the
[inspection contract](../inspection.md) for bounds and sampling semantics.
