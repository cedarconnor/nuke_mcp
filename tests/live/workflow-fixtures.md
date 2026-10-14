# Native Milestone 5 qualification

Use only a newly launched, owned disposable GUI process with `NUKE_MCP_DISPOSABLE_SESSION=1`
and an owned library/output directory. Retain manifest, plan, request receipts and published files.

`python tests/live/prepare_workflow_fixture.py <new-directory>` creates a new 4x4 RGBA PNG and
`workflow_fixture.nk`. Launch that script in the owned session, then run
`python tests/live/workflow_probe.py --pid <owned-pid> --directory <fixture-directory> --output <report.json>`.
The probe selects the exact observed `linear` fixture colorspace or refuses to substitute. It never
replays failed builds. Numeric sampling and preview rendering are attempted only after a verified build.

For shot generation, provide a small valid plate and exact host color/Write enum labels. Plan two
shots into different new script and Write destinations. Verify plan makes no graph changes, then
apply once. Check final identity and relative Write paths on reload, per-shot completion, and original
saved-clean restoration. Inject a second-shot save failure only in the owned fixture; the first output
must remain unchanged. NC lookup failures are unqualified outcomes, never permission to replay.

For layered compositing, create two known RGBA signals with alpha and an explicit mask. Plan a
two-layer `plus` or `over` Group. Check source full paths, Merge B=accumulation/A=new/mask=2, channel
routing, and unrelated node/selection preservation. Saving and rendering are separate explicit
fixture actions. Compare the rendered result numerically and retain an artist-viewable PNG before
claiming a native reconstruction recipe. Mocks and topology alone do not qualify pixel correctness.
