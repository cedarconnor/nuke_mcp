# Milestone 2 verification — 2026-10-14

Implementation: `4346640`, `fd7e0fe`, and review fixes `fab207d`, based on
`59d8ff6`. Tasks 5–6 implement typed edits and bounded batches. Native mutation
qualification remains incomplete; the passing transport checks do not imply
that all edits are qualified on Nuke Non-commercial.

## Results

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -p 'test_*.py' -q` | 80 tests passed |
| `python tests/mcp_contract_probe.py` | Passed: two real stdio MCP processes, 20 tools, eight correlated reads, typed modify, batch dry-run/apply, unavailable revision refusal, errors and status |
| `python tests/mcp_contract_probe.py --live` | Passed: two clients, eight reads, shared instance, distinct sessions/requests, main-thread execution, expected missing-node error |
| Disposable native mutation smoke, before final review fixes | Incomplete: creation, inspection, dry-run, label edit and destruction callback passed; position readback matched but identity verification failed, producing partial batch / unknown item |
| Final disposable native mutation smoke | Failed conservatively: creation returned a handle but lookup became unavailable during preflight; cleanup could not establish ownership and reported partial with `created_path` and `cleanup_error` |
| Commercial Nuke, NukeX/Studio, other platforms, render correctness | Not qualified |

Native host: Windows, Nuke Non-commercial 17.0v4, external Python 3.11.11.
The final live probe used host instance
`c7ed6c29-19af-4aa2-b312-adeed48a6b66`, PID 146716. Only a newly launched
disposable fixture was mutated. The updated mutation module was reloaded in that
owned process before the final tests. No permanent Nuke startup configuration
was changed. The owned fixture was closed without saving after verification;
unknown nodes were not individually replayed or deleted by guessed identity.

## Independent review and fixes

The independent review examined `59d8ff6..fd7e0fe`. Its four findings were
reproduced with failing regressions, then fixed in one pass:

- Later knob/selection callbacks could invalidate values after creation's
  preliminary readback. Final verification now runs after restoration and
  compares all requested values, position and connections.
- Array writes could continue after a callback introduced animation. Each
  component now checks identity and static state; partial component evidence is
  retained on failure.
- Selection restoration could replace existing cleanup evidence with an empty
  error. Original mutation/recovery data and restoration errors are retained.
- Uniform arrays could read back as a scalar. Indexed reads now preserve array
  shape for snapshots and verification.

A native Blur probe confirmed `WH_Knob.value()` can return a scalar while indexed
reads expose two components. A separate fractional-dimension regression corrected
the integer-only WH validation. Its subsequent native mutation could not be
qualified because creation returned no handle. Fractional WH edits therefore
have offline coverage, not a claimed native pass. Foundry documents the indexed
floating-point API in its [Array_Knob reference](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.Array_Knob.html).

Earlier native fixture attempts also exposed a constructor argument error
(`inpanel` is not a knob accepted by `nuke.nodes` factories), corrected with a
regression before the Task 5 commit, and an invalid Root handle that stopped
inspection before mutation. A diagnostic Grade probe used a nonexistent `gain`
knob; its raw error discarded diagnostic output, so its cleanup is not counted
as independently verified. The entire owned disposable session was later closed.

No review findings were deferred. Scene revisions, richer inspection, asset
publication and commercial/native image qualification remain later scope.
No automatic replay or global undo was introduced.

## Retained evidence

- [Offline stdio probe](milestone-2-evidence/stdio.json)
- [Live two-client probe](milestone-2-evidence/live.json)
- [Earlier native partial batch](milestone-2-evidence/native-partial-batch.json)
- [Final native partial creation](milestone-2-evidence/native-final.json)
- [Native array API observation](milestone-2-evidence/native-array-api.json)
- [Fractional-array attempt with no returned handle](milestone-2-evidence/native-array-uncertain.json)

The native reports retain unsuccessful results deliberately. They must not be
aggregated into a full mutation pass. Reconcile unknown operations with host
observation before deciding on new work; never treat failure as proof that a
mutation did not happen.
