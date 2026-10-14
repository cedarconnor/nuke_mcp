# Toolsets and script lifecycle

The six Milestone 4 tools use the serialized host queue and structured receipts.
An unknown outcome never authorizes replay. Toolsets and opened scripts are trusted executable
Nuke code, with the same local trust boundary as `execute_nuke_code`.

## Toolsets

Configure `NUKE_MCP_LIBRARY_ROOT` in Nuke's environment; default: `~/.nuke/nuke_mcp_toolsets`.
`save_toolset(node_paths, name, overwrite=False)` accepts 1–100 explicit full paths in one scope.
Include all input dependencies. Nested Group contents are copied with the selected Group.
Names are simple identifiers, at most 64 characters. Payloads are limited to 16 MiB, metadata
to 1 MiB, and observed nodes to 1000. Root containment resolves existing parents and junctions.

Schema-v1 manifests record SHA-256, host/license extension, class dependencies, relative inputs
and outputs, and a bounded static knob subset. The manifest is the publication point. Old payloads
and interrupted staging files are retained and ignored by listing; no automatic garbage collection.
Hashes are integrity checks, not signatures or code sandboxing. Libraries must not have untrusted writers.

`load_toolset(name, group_name, position=None)` verifies the manifest and payload before paste,
creates a new root Group, rechecks the bytes, and pastes a verified snapshot inside that Group.
It compares observed topology and static values after restoring selection. It does not prove every
knob, callback, plugin or nested Group was observable, especially in NC. A failed load may leave
the owned Group and reports its path if known. There is no speculative deletion or retry.

## Scripts

`open_script(path, discard_unsaved_changes=False)` requires an existing absolute path with the
current host's extension (`.nknc` in NC, `.nk` otherwise). Dirty work is refused by default.
Explicit discard may replace it. Clean-script replacement is also deliberate; no implicit clear
or blanket rollback is performed. Readback verifies the actual host script path.

`save_script()` intentionally overwrites the current named target. Unsaved scripts require an
absolute save-as path. `save_script(path, overwrite=False)` refuses existing targets and missing
parent directories. Results include the observed file size and digest. Failed saves attempt to
restore the original target and dirty flag, but cannot roll back filesystem writes or callback
effects. Recovery retains unsaved callback edits and does not relabel a detected script switch;
`identity_restored` is false when restoration cannot be established. The receipt reports that
distinction. The internal disposable-script helper is not an MCP tool.

## Project settings

`set_project_settings(settings, dry_run=True)` validates before writing. Example:

```json
{"fps":24,"first_frame":1001,"last_frame":1100,
 "format":{"width":1920,"height":1080,"pixel_aspect":1.0},
 "color_management":{"colorManagement":"OCIO"}}
```

Only use the exact enum labels available in your host. Allowed color knob names are
`colorManagement`, `OCIO_config`, `workingSpaceLUT`, `monitorLut`, `int8Lut`, `int16Lut`,
`logLut`, and `floatLut`; unavailable or non-enumerated knobs are refused. No configuration
is guessed or downloaded. Static settings cannot replace expressions or animation.
Apply binds the script path and checks each write and the final values. Earlier writes and newly registered formats may
remain after failure; `completed` is evidence of intermediate verification, not atomic rollback.

Host API references: [nodeCopy](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.nodeCopy.html),
[nodePaste](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.nodePaste.html),
[scriptSaveAs](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.scriptSaveAs.html),
[scriptOpen](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.scriptOpen.html),
[addFormat](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.addFormat.html).
