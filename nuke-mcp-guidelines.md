# Guidelines for Creating Nuke Nodes via MCP

Protocol v2: inspect structured `state`/`outcome` and MCP `isError`, and retain
request/instance IDs for `get_operation_status`. A timeout or disconnect does not
prove cancellation. Never automatically retry a mutation, including handle-less
NC creation. Typed edits now require readback, while bounded inspection reports
coverage and omissions. `get_capabilities` reports uncertainty; NC still cannot
establish complete graph observation. Use full Group paths and read the
[inspection and sampling limits](docs/inspection.md) before drawing conclusions.

For manifest workflows, plan first and pass the returned digest with the same manifest.
Shot application is limited to an explicitly disposable clean session and refuses existing output
files. Layered Groups require observed channels and explicit merge/mask choices. Unknown results
are not permission to rebuild. See [workflow contracts](docs/production-workflows.md).

Use [event polling](docs/scene-events.md) to detect observed changes. A history gap or changed host
instance requires fresh inspection. Only use `expected_revision` when coverage is available; NC
observations do not provide that guarantee. A save event alone does not prove a successful save.

## Creating and editing nodes

Use typed `create_node`, `modify_node`, and `batch_edit` calls for supported edits.
Node identifiers must start with a letter or underscore; use a label for descriptive text.
Use full paths such as `root.Grade1` or `GroupA.Grade1` for existing nodes. Short names
can be ambiguous when Groups contain nodes with the same name.

Inspect the structured receipt before any dependent edit. `unknown` or `partial` means
stop and retain the request ID, observed paths, and cleanup evidence. Query operation status
when available. Do not replay creation, delete guessed candidates, or continue building on
an unverified node. Raw Python creation does not remove NC observation limits or supply
verified rollback.

`create_node` validates the requested identifier and resolves its constructor through
`nuke.nodes`; the old fixed node-type allowlist no longer controls this typed path.
An available constructor is not evidence that its knobs or behavior are qualified.
Use [verified edits](docs/verified-edits.md) for supported values and batch behavior.

## Non-commercial node retrieval limits

Foundry documents a ten-node Python retrieval limit in Nuke Non-commercial.
[Official NC limitations](https://learn.foundry.com/nuke/17.0v2/content/getting_started/meet_nuke/about_nc.html).

A fresh one-node Nuke NC 17.0v4 fixture reproduced the limit on 2026-10-14:
repeated `toNode("MCP_Constant")` calls returned the same node ten times, then returned
`None`; subsequent `allNodes()` returned `[]`. This occurred without importing the bridge.
The same sequence through the bridge also failed after ten successful lookups, and four
later read-only requests still returned `None`. With bridge callbacks installed in a
separate startup probe, nine lookups succeeded. These counts describe those runs; they
are not a guaranteed per-tool allowance or a specification of the host's reset behavior.
See the [diagnosis and raw traces](docs/validation/nc-node-retrieval.md).

A small graph can therefore become unobservable. Counting distinct nodes or reducing the
fixture to fewer than ten nodes does not establish reliable readback. The older description
of intermittent blackouts was an observation, not a diagnosed cause; repeated retrievals
now provide a minimal reproduction of the missing-handle/empty-enumeration behavior.

- An empty list does not prove an empty graph, and `None` does not prove node absence.
- Creation can change the graph before later verification becomes unavailable. Preserve
  an uncertain outcome; no automatic mutation retry or guessed deletion is permitted.
- Read-only observations may be attempted again, but recovery is not guaranteed. Do not
  reset the script, split mutations, or remove verification to work around the license limit.
- Capabilities and revision guarantees remain degraded on NC. Full native edit, toolset,
  shot, AOV, and commercial revision qualification still require separate host evidence.

## Multiple clients and Python output

Protocol v2 supports multiple clients sharing one loopback listener. The old single-client
restriction was replaced in Milestone 1; two-client native evidence is recorded in
[the validation report](docs/validation/milestone-1.md). Each client launches its own external
stdio process. Use matching protocol versions and the intended port/checkouts; see
[installation](INSTALL_OTHER_CLIENTS.md).

`execute_nuke_code` returns data through the injected `output` dictionary. `print()` writes
to Nuke's Script Editor. This read-only example remains subject to NC retrieval limits:

```python
output["nodes"] = [node.fullName() for node in nuke.allNodes()]
```

## Qualification before deployment

Run `tests/live/qualify.py --output <new-absolute-directory>` for scene-read-only checks.
Treat `qualified` as the selected checks that passed on the recorded host, not as approval of
other capabilities. Editing probes require a fresh exclusive disposable host and
`--mutate --disposable --pid <pid> --fixture <absolute-path>`. Never retry an ambiguous mutation;
retain the receipt and inspect its operation status. `retained_disposable` means fixture changes
and files are deliberately left for review, not that rollback or host shutdown occurred.
Use explicit NC `.nknc` save destinations. Render and numeric evidence do not constitute artist
approval. See [qualification and deployment](docs/VALIDATION.md) for the full procedure.
