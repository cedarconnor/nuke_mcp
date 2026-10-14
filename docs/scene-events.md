# Scene events and revision checks

Call `subscribe_events(event_types)` to set a filter for the current client connection, then poll
`get_events(after_sequence=0, limit=100)`. There is no push channel or unsolicited stdio output.
The default filter includes all event types; an empty list selects none. Reconnection resets the
filter, so subscribe again. Filters do not own a separate history or change another client's view.

Supported types are `node_created`, `node_deleted`, `knob_changed`, `script_loaded`, `script_saved`,
`script_closed`, and `frame_changed`. These are callback observations, not completed-operation
receipts. In particular, Nuke's save callback runs **before** save; `script_saved` does not prove
that a file was written. Use the actual save operation receipt for that conclusion.

The host retains at most 1000 event records. Each has an instance ID, monotonic timestamp, sequence,
observed revision, and request ID when a callback runs within a bridge operation. Full node paths and
knob names are included when available; values and callback code are excluded. An artist callback
triggered synchronously by a bridge edit inherits that request's origin. Attribution does not prove
that the callback made only the requested change. Async artist/UI events can have a null request ID.

## Polling cursors

- Always retain `server_instance_id` together with `next_sequence`. Reset your cursor and re-inspect
  after an instance change; a sequence or revision from another instance is not comparable.
- `limit` is 1–500. Advance to `next_sequence` even if a filter returned no events. `latest_sequence`
  tells you whether retained events remain to scan.
- `history_gap:true` means events were evicted after your cursor. A filtered-out event is not a gap.
  Re-inspect before making assumptions about the current graph.
- Consecutive changes to the same knob, node, and request are coalesced within 100 ms of the first
  callback. `first_sequence`, `sequence`, `count`, and timestamps describe that range. If you already
  consumed an earlier version of the record, a later poll may return its updated summary; do not
  add the full count again as if every callback were newly delivered.
- Deletions and script lifecycle events are never coalesced. Revision increments happen before
  coalescing, so rapid changes still invalidate an earlier plan.

Frame events sample the current frame on the main-thread queue timer and Root-scoped `updateUI`,
because Nuke 17.0 has no dedicated frame-change callback and Root UI updates may be absent.
Transient frames between samples may be missed. `frame_observation` is always `sampled`.
Callbacks do no graph traversal, file access, or network work. Failure to observe callback identity,
recursive observation, missing callback APIs, or registration/removal failures degrade revision coverage.

## Optimistic edits

`get_capabilities`, `get_events`, and `batch_edit` dry-run results report revision availability.
Use the dry-run's `scene_revision.revision` as `expected_revision` on apply, only within the same host
instance and while `revision_available:true`. Apply checks before mutation and at edit boundaries,
including between array components. A stale revision returns `revision_conflict` before edits, or a
partial result if a change arrives after some edits. Earlier verified changes remain applied.

The current request's contiguous observed changes may advance the revision without invalidating
its remaining edits. Any intervening unattributed or other-request change breaks that allowance.
This is optimistic concurrency, not a lock against arbitrary scripts or callback-suppressed edits.
The bridge client detects a changed instance when reconnecting; never reuse an old revision afterward.

NC, unknown license observation, older/unqualified callback coverage, and degraded callbacks return
`revision_unavailable` when `expected_revision` is requested. Never treat a missing guarantee as
revision zero. Without `expected_revision`, existing target validation and readback still apply.

Shot and comp plans now bind an observed revision and script generation separately from their host
identity. Changes observed between planning and application invalidate the digest, even under NC.
They recheck observed changes between mutation boundaries while allowing the request's own callbacks.
Under degraded coverage this is an additional observation check, not a complete graph guarantee.

Stop removes callbacks. A new add-on start creates a fresh event buffer and server instance. If a
callback cannot be removed, it is made inert and ownership is retained to prevent duplicate installation.
Resolve the host callback cleanup failure or restart Nuke before starting a replacement bridge.

API behavior was checked against the installed Nuke 17.0v4 callback implementation and Foundry's
[callback documentation](https://learn.foundry.com/nuke/developers/latest/pythondevguide/callbacks.html)
and [knob callback reference](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.addKnobChanged.html).
