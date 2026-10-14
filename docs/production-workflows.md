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
its file identity is unchanged and the host has not switched outside workflow ownership. An unnamed
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
