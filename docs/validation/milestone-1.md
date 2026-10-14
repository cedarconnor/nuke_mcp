# Milestone 1 validation — 2026-10-14

Scope: Tasks 1–4 from the Nuke MCP expansion plan. Implementation branch:
`codex/nuke-bridge-foundation`, based on `ad55c966`. No Milestone 2–6 features
are claimed. The original checkout and permanent Nuke startup were not changed.

## Delivered behavior

- Protocol v2: bounded newline JSON, explicit application/version handshake,
  correlated request/session/host-instance identities, and no mutation replay.
- Up to eight loopback clients, 64 queued operations, and one ordinary operation
  per session. Nuke API work runs through a main-thread Qt timer.
- Retained operation receipts, deadline checks, status and cancellation controls.
- All 15 original tools retain their names/arguments and useful success text,
  with structured receipts and true MCP errors. Four new tools expose capabilities,
  asynchronous render submission, status, and cancellation.
- Cooperative renders restore frame/proxy state and check cancellation between
  native frames. A client timeout does not stop or authorize repeating a render.

FastMCP remains 2.14.7, with no new runtime dependencies. Both sides must be
updated together, including the `nuke_mcp_bridge` package.

## Verification

Final implementation: `1b1bd88`. All **45 offline tests pass**. The independent
review found three issues; each was reproduced by a failing regression before
the fix, and the complete suite passed afterward:

- Stopping during a nested native render now closes its generator and restores
  host state on the main thread after the current frame returns.
- An optional failed read no longer hides a later successful mutation. Compound
  results retain every receipt and cannot claim `not_started` after an applied step.
- Default render uses the string defaults required by Nuke's native environment
  object, preserving the intended NC uncertainty result.

No review findings were deferred. Live evidence confirms bridge operation only;
the render shutdown regression uses a controlled fake native frame.

Run from the implementation checkout with external Python 3.11:

```powershell
D:/nuke_mcp/.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -v
D:/nuke_mcp/.venv/Scripts/python.exe tests/mcp_contract_probe.py --slow --output docs/validation/milestone-1-offline-stdio.json
D:/nuke_mcp/.venv/Scripts/python.exe tests/mcp_contract_probe.py --live --output docs/validation/milestone-1-live.json
git diff --check
```

The offline stdio probe uses two real `main.py` subprocesses against a fake host.
It verifies original required arguments, all 19 tools, distinct client sessions,
matched request IDs, real MCP errors, unavailable-host reporting, and an accepted
render running beyond the previous 15-second wait. This proves MCP/operation
behavior, not native rendered image correctness.

The real stdio probe also verifies a failed preliminary inspection followed by
a successful fake edit: the edit's identity/outcome survives MCP serialization,
and both operation receipts remain available.

The live probe uses two real `main.py` subprocesses against one fresh Nuke NC
17.0v4 GUI process on Windows, loaded from the implementation worktree through
a temporary `NUKE_PATH`. It completed eight paired script reads with eight unique
request IDs, returned the same host instance to both clients, reported explicit
NC uncertainty, retained an expected missing-node failure, and confirmed Python
execution on Nuke's main thread. The fixture script was an unmodified `Root`;
no graph mutations or output renders are part of this check.

The temporary host was closed after checking its PID and confirming the script
remained an unmodified `Root`. Permanent startup and client configuration were
left unchanged. To use this implementation, follow the coordinated upgrade
instructions against this worktree or integrate its branch into the installed
checkout first.

Raw results: [live two-client receipts](milestone-1-live.json) and
[offline stdio receipts](milestone-1-offline-stdio.json).
The [execution ledger](milestone-1-execution.md) records task commits and review fixes.

## Qualification boundaries

Commercial Nuke/NukeX/Studio, other platforms/versions, native render output,
and artist acceptance remain unqualified. NC graph access can be incomplete;
Milestone 1 does not verify legacy mutations by readback. Receipt retention is
bounded and does not establish exactly-once execution across restarts/expiry.

## Execution decisions

1. Implement the four coupled tasks inline, followed by one independent review.
   The risk of author blind spots is addressed by regression tests and that review.
2. Launch a disposable NC host with temporary startup configuration for the live
   check. This leaves commercial behavior unqualified and requires coordinated
   installation before using the new bridge in the user's regular Nuke session.
