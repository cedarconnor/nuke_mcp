# NC node retrieval diagnosis — 2026-10-14

The next unfinished work after Task 15 was native workflow qualification. A bounded
investigation reproduced the missing-node symptom without the bridge, on a one-node
fixture. Repeated retrievals, not just distinct graph size, can exhaust native Python
observation in Nuke Non-commercial 17.0v4. The bridge's existing unknown outcomes are
appropriate; verification was not weakened to turn the failed workflows into passes.

Foundry documents a ten-node Python retrieval limit for NC. The installed 17.0v4
`Documentation/html/content/getting_started/meet_nuke/about_nc.html` states the same
restriction as the [official online NC documentation](https://learn.foundry.com/nuke/17.0v2/content/getting_started/meet_nuke/about_nc.html).
The [Foundry FAQ](https://www.foundry.com/non-commercial-faqs) also describes bounded
enumeration. Neither source promises that graphs with fewer than ten nodes support
unlimited repeated lookups.

## Experiments

Windows, Nuke Non-commercial 17.0v4, external Python 3.11.11. Runtime source was
`6cb9b0b`; no runtime file changed during this investigation. All three fresh hosts loaded
the same fixture content: Root plus one Constant named `MCP_Constant`. The probes waited
for the exact fixture path, ran on Nuke's main thread, and requested no graph mutations.

Each probe made fourteen ordered `nuke.toNode('MCP_Constant')` calls, recording only
the returned full path or null, followed by one `nuke.allNodes()` enumeration.

| Context | Successful lookups | Remaining lookups | Enumeration |
| --- | --- | --- | --- |
| Direct Qt callback; bridge not imported | 1–10 | 11–14 returned null | Empty |
| Direct Qt callback; bridge and scene callbacks installed | 1–9 | 10–14 returned null | Empty |
| One real bridge `execute_code` request | 1–10 | 11–14 returned null | Empty |

After the third probe, four separate read-only bridge requests each attempted one lookup.
All four returned null. They used the same verified PID, instance, and exact fixture path;
the host was not reset or reloaded. The successful transport receipts therefore do not
imply successful graph observation.

The callback-enabled run also recorded `callback_read_failed`, with revision coverage
unavailable. Its one-lookup difference is observed evidence, not proof of which callback
consumed a retrieval. Internal NC accounting, reset timing, other API costs, and the cause
of every historical workflow failure remain unqualified. This investigation establishes
a minimal native reproduction and a mechanism consistent with the documented license
restriction; it is not an exhaustive audit of each failed tool.

## Evidence and reproduction

[Evidence manifest](nc-node-retrieval-evidence/manifest.json) records source HEAD and
SHA-256 digests of retained scripts, fixture files, launch records, traces, receipts, and
exit records. Individual traces:

- [Direct native trace](nc-node-retrieval-evidence/direct/trace.json)
- [Bridge callbacks installed](nc-node-retrieval-evidence/bridge/trace.json)
- [Bridge request trace](nc-node-retrieval-evidence/requests/trace.json)
- [Full bridge receipts](nc-node-retrieval-evidence/requests/receipts.json)

The archived launch scripts are exact local orchestration records, not portable product
entry points. They refer to the original workspace and scratch layout. For a new run,
use new private directories, a free loopback port, and the recorded menu/fixture content.
Set the disposable-session environment only for the newly launched process. Never reuse
an artist session. Wait for its exact fixture path before running this read-only probe:

```python
trace = []
for index in range(1, 15):
    node = nuke.toNode('MCP_Constant')
    trace.append({'index': index, 'path': node.fullName() if node is not None else None})
output['trace'] = trace
output['allNodes'] = [node.fullName() for node in nuke.allNodes()]
```

`output` is injected by the bridge; create a dictionary explicitly in a direct native
callback. A direct baseline must not import the bridge. The archived menu callbacks
provide that baseline and record host version/license facts. Do not turn this exhaustion
probe into a production health check: even read-only retrievals affect later observation.

Owned process IDs 152616, 163796, and 138368 were observed exited. Closing these disposable
hosts did not certify graph rollback or any outstanding workflow. No existing artist
host was closed; no original script, settings, or startup installation was changed.

Archive verification passed: all 19 SHA-256 digests match both working files and staged Git
blobs; all three ordered traces and process-exit records match the claims above; bridge
receipts retain the expected instance; 30 relative documentation links resolve; staged
`git diff --check` is clean. The archive preserves original Windows line endings so its
digests survive checkout. No runtime or test files changed, and the offline suite was not
rerun for this documentation/evidence change; the 221-test result belongs to Task 15.

## Result and next gate

The NC diagnosis is complete. No runtime patch is justified by this reproduction, and no
license-limit workaround was added. The documentation now explains repeated retrieval
exhaustion and removes obsolete single-client, fixed-allowlist, and mutation-retry advice.
Existing capability degradation and fail-closed edit behavior remain in place.

Next, run the outstanding verified-edit, nested Read, channel statistics, toolset, two-shot,
and AOV scenarios on a suitable commercially licensed Nuke host. Adapt fixture output
extensions explicitly where necessary and record actual host/license facts; the current
capability API reports non-NC licensing as unknown. Do not infer commercial qualification
from that flag. Complete the synthetic AOV numeric comparison and retain a preview before
artist review. Commercial event revisions require their own native qualification too.

Task 15 and this follow-up remain local on the `codex/nuke-nc-observation` history until
separately pushed. The original plan's native reconstruction gate remains open.
