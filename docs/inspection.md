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
Nontrivial Read timing (offset/start-at/frame expressions) and requests outside
Read ranges with before/after handling are also unknown until native mapping is
qualified. Identity timing is supported; this is not a retimed-dependency audit.
This tool does not relink, render, change frame or change selection.

Read `observation.coverage`, errors and `truncated` before drawing conclusions.
NC enumeration remains partial or unknown. An empty result under NC does not
prove an empty graph. Legacy `get_script_info` and `get_node_info` summarize the
same bounded structured observations and disclose their coverage.
Repeated retrievals of a single node can make that node unavailable to Python;
the limit is not safely modeled as ten distinct nodes. See the
[one-node native reproduction](validation/nc-node-retrieval.md). Later read-only
requests did not restore observation in that run.

File expressions and registered filename filters remain trusted Nuke code;
inspection is not a sandbox for an untrusted script. No donor code was copied.
API references: [File_Knob](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.File_Knob.html)
and [OutputContext](https://learn.foundry.com/nuke/developers/latest/pythondevguide/_autosummary/nuke.OutputContext.html).

## Channel diagnostics

`sample_channel_statistics(node_path, channels, frame, roi=null,
max_samples_per_channel=1024)` resolves channel names or layer names into at
most 16 channels. ROI is `[x,y,width,height]` in integer pixels within the node's
format. Each channel receives at most 4096 samples. The result reports the
actual grid, cell size, frame, ROI, sample counts, finite min/max/mean, non-finite
count, and zero fraction among finite samples. Duplicate channels are measured
once. A layer that expands beyond the limit is rejected before sampling.

The method is `nuke.Node.sample` with explicit cell widths and heights, which
uses cubic filtering. `samples_every_pixel` is false: filtered values are not
individual-pixel extrema, and sampled zero values do not prove a black image.
Cancellation/deadline checks run between samples; an individual native sample
cannot be interrupted. Partial statistics are retained on failure. The original
frame is restored on every exit; restoration failure is an unknown outcome.
Selection, proxy and project settings are not changed by the tool.

Native fixture: `tests/live/inspection_fixture.nk` contains a 4x4 Constant
with expected RGBA means `[0.25,0.5,0.75,1]`, an Expression ramp with expected
red mean `0.5`, two nested Constants with the same short name, and an explicitly
missing Read sequence. Use a 2x2 grid and tolerance `1e-6` for known signals;
record actual native results separately rather than substituting offline tests.

After loading that fixture in an explicitly disposable host, run
`python tests/live/inspection_probe.py --pid <owned-host-pid> --port 19877 --output evidence.json`.
The probe verifies the process and fixture before sampling, preserves failure
receipts, checks before/after state, and exits nonzero unless every check passes.
See [recorded native limits](validation/milestone-3.md).
