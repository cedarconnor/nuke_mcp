# Shot and compositing workflows

Schema-v1 JSON manifests are authoritative. See [examples](../examples/README.md) for placeholder
paths and explicit user-provided color settings. CSV conversion accepts an explicit `column_map`
and `defaults` containing `schema_version`, `output_root`, and `shot_defaults`. Returned errors
and unmapped columns are actionable data; conversion never builds a graph.

## Shot scripts

`plan_shot_setup(manifest)` reads source metadata and destination state without changing the graph.
Pass its returned `digest` with the same manifest to `apply_shot_setup`. Planning reserves nothing.
The digest binds normalized input, host instance/version/license, original script state, roots,
toolset bytes/metadata, OCIO environment identity, and evaluated source existence/size/mtime.
It does not hash full plate contents. Metadata-preserving external edits are outside that guarantee.

The host must be GUI Nuke launched explicitly with `NUKE_MCP_DISPOSABLE_SESSION=1` and the
current script must be clean. This opt-in authorizes **fresh-script replacement** within that owned
session; do not set it on an artist's normal session. A saved clean original is restored on exit when
its file identity is unchanged and the host has not switched outside workflow ownership. Foreign
observed changes or newly degraded event coverage prevent restoration; the current graph is retained
for inspection. The revision guard stays active during restoration preflight. An unnamed
original leaves the owned result/partial graph for inspection. Dirty artist scripts are refused.

Every script and Write path must remain under the manifest's absolute `output_root`, including
resolved junction parents. Create directories before planning. Existing script or Write targets
are errors, including on reruns. Source sequences support absolute literals, `%d`/`%04d` and hash
padding; unsupported Tcl, environment and view expressions fail preflight. Write paths additionally
support the explicit prefix `[file dirname [value root.name]]`. At most 100 shots, 32 plates per shot,
and 10000 evaluated paths per plan are accepted.

Without a toolset, exactly one plate feeds the Write. Multi-plate shots require a trusted toolset
with contiguous numbered root Input nodes (one per plate) and exactly one root Output.
Each shot obtains an explicit fresh-script receipt, applies settings, creates Reads and an optional
toolset Group, connects a Write, and verifies known settings/topology. It saves to a unique sibling
staging file and publishes using an atomic no-clobber hard link. Filesystems must support hard links.
Staging files remain as recovery evidence. Published scripts are reopened and their actual identity,
known settings/topology and script-relative Write paths are checked before completion is recorded.

Completion is per script. A later failure preserves earlier outputs and reports `current`, `completed`,
and restoration evidence. A published artifact remains even if reload verification fails. Reconcile
the original request receipt and files; never replay uncertain mutations or overwrite existing outputs.
The workflow saves scripts; it does not render.

## Layered/AOV Groups

`plan_layered_comp(manifest)` binds full source paths, observed channels, supported knob snapshots,
host instance, script identity and frame. `build_layered_comp(manifest, plan_digest)` revalidates and
builds only a new named Group. It never clears the script, saves it, renders, or guesses a beauty recipe.
It reports created paths and individual verified operations; ambiguous creation is not retried/deleted.

Node and mask sources must share a scope; the new Group is created in that scope. Expose Group
outputs when sources live in different Groups. Identical short names are never guessed. A file
source needs one existing observed Read with the exact raw file path and colorspace, allowing
channel preflight without a hidden temporary node. Build creates its own Read inside the new Group.

Each requested layer must expose red, green, blue **and alpha**. No alpha is invented. Adjustments
always run **Grade then Blur**, regardless of JSON object key order. Prefer classic
Shuffle when available, otherwise Shuffle2 with verified mapping readback; unknown knob layouts
fail inside the owned Group with partial evidence. Grade gain maps to `white`, gamma to `gamma`,
and Blur size is explicit. Merge input 0/B is the accumulated comp; input 1/A is the new layer;
input 2 is the explicit mask with its requested channel. Supported operations are over/plus/multiply/screen.
Optional Write creates a node only; saving and rendering remain separate.

Channel/knob observations and class discovery are bounded, especially under NC. A plan reserves no
state. Task 14 adds observed revision stamps; degraded NC coverage still cannot establish a graph revision guarantee or pixel-correct production recipe;
native numeric reconstruction and artist-viewable render evidence are separate qualification gates.

API semantics were checked against Foundry's [Shuffle reference](https://learn.foundry.com/nuke/content/reference_guide/channel_nodes/shuffle.html)
and [Grade knob reference](https://learn.foundry.com/nuke/9.0/content/reference_guide/color_nodes/grade.html).

See [scene events](scene-events.md) for plan invalidation after observed changes and coverage limits.
