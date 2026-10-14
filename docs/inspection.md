# Graph and Read inspection

`inspect_graph(max_nodes=256, max_knobs_per_node=64, recurse_groups=true,
selected_only=false)` returns full node paths, indexed connections (including
disconnected inputs), supported knob snapshots, omissions, errors and coverage.
Ceilings are 1000 nodes, 128 knobs and 128 input slots per node. Values larger
than 1024 characters or 16 components are omitted. Results stop before 4 MiB
of evidence so receipts fit the transport. These limits are explicit; omitted
fields are never represented as absent scene data.

`inspect_reads(node_paths=null, channel_limit=256)` inspects Read and DeepRead
nodes, recursively by default. Supply full paths to restrict the scope. Results
include raw file text, evaluated paths at the current frame for each project
view, frame range, format, colorspace, channels/layers, and available `part` or
`layer` choices. Channel output is capped at 2048 per Read. Metadata failures
are reported per field. This does not audit EXR headers independently of Nuke.

`validate_reads(first_frame, last_frame, step=1, node_paths=null)` checks at most
10000 frame/view paths. Negative integer frames are supported. Nuke evaluates
file expressions in an explicit `OutputContext`; normalized frame and view
tokens are then expanded. All project views are checked, with a 64-view ceiling.
Only the full-resolution `file` knob is inspected; proxy settings are unchanged.
Unresolved expressions, unknown relative-path bases and I/O errors are `unknown`,
distinct from `missing`. Missing files are evidence, not a failed transport call.
This tool does not relink, render, change frame or change selection.

Read `observation.coverage`, errors and `truncated` before drawing conclusions.
NC enumeration remains partial or unknown. An empty result under NC does not
prove an empty graph. Legacy `get_script_info` and `get_node_info` summarize the
same bounded structured observations and disclose their coverage.

File expressions and registered filename filters remain trusted Nuke code;
inspection is not a sandbox for an untrusted script. No donor code was copied.
API references: [File_Knob](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.File_Knob.html)
and [OutputContext](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.OutputContext.html).
