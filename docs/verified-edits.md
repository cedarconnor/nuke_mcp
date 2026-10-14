# Verified edits and batches (Milestone 2)

Typed create, modify, position, connect, and delete tools now use exact node
paths and affirmative readback. Use `GroupA.Grade1` for a nested node and
`root.Grade1` to disambiguate a root node. Creation currently targets root scope;
installed classes are resolved at execution rather than through a fixed list.
Returned `path` is the actual identity to use in subsequent calls.

Static setters support ordinary numeric, boolean, string/file, and enumeration
knobs. Provide every component of an array (for example `[1,1,1,1]` for a
four-component color knob); enum values use labels. Animated/expression knobs,
callback/executable knobs, non-finite numbers, and unsupported types are refused.
Requested parameters are no longer silently rewritten by workflow auto-fixes.
Array snapshots use indexed readback, including when equal components collapse
to a scalar in the host's default read API. Array writes revalidate the target
and static state before each component. Creation verifies requested values,
position, and connections after selection restoration and dependent callbacks.

## batch_edit

The default is a read-only dry run. Every item is preflighted before writes.
Supported operations are `set_knob`, `connect` (null source disconnects), and
`position`, with 1–100 items and no duplicate target in the same batch.

```json
{
  "operations": [
    {"op":"set_knob", "node_path":"root.Grade1", "knob":"label", "value":"Primary grade"},
    {"op":"position", "node_path":"root.Grade1", "x":200, "y":100},
    {"op":"connect", "node_path":"root.Grade1", "input_index":0, "source_path":"root.Read1"}
  ],
  "dry_run": true
}
```

Submit the same operations with `dry_run:false` to apply. A dry run does not
reserve the graph. Apply revalidates identities, values, animation, connections,
and cancellation/deadline state at edit boundaries. One undo group helps artist
recovery; it is not an atomic transaction. On failure, earlier applied edits
remain, the failing item's outcome is explicit, and the remaining tail is
`not_started`. Inspect `data.items` even when MCP `isError` is true.

`expected_revision` is reserved for a trustworthy scene-revision provider and
currently fails with `revision_unavailable` before any write. Do not assume a
dry-run receipt protects against artist changes between requests.

## Uncertain results and legacy workflows

A handle-less creation is `unknown`: it is never retried and no candidate node
is deleted. Invalid post-creation settings may be rolled back only through the
returned, still-observable owned handle; failed cleanup is `partial`/`unknown`.
Deletion requires an exact-handle destruction callback, not just missing lookup.
NC observation limits remain; unknown is a useful result, not a retry signal.

Templates, auto-layout, and graph organization still execute their legacy code.
They now return `unverified_workflow` with an unknown outcome and the available
output, even if that code reports success. Inspect the script and do not repeat
the operation automatically. `execute_nuke_code` remains an explicit unrestricted
escape hatch and does not gain typed-edit verification.

API references: Foundry's [Node API](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.Node.html),
[Knob API](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.Knob.html),
and [node creation guide](https://learn.foundry.com/nuke/developers/140/pythonreference/basics.html).
Native version qualification is reported separately from fake-host tests.
See the [Milestone 2 validation report](validation/milestone-2.md) for the
current NC limitations and failed mutation receipts.
