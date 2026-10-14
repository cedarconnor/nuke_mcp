# SDD ledger — plan: docs/superpowers/plans/2026-10-14-nuke-mcp-expansion.md
Scope: Milestone 1 only (Tasks 1–4), followed by live two-client verification.
Baseline: ad55c966; isolated branch codex/nuke-bridge-foundation. Offline baseline has zero tests; live Nuke absent.
Pre-flight 1->2: Request/Result envelope owns identity; registry owns receipt/deadline; compatible.
Pre-flight 2->3: registry tick must run on host main thread; socket controls stay host-free; compatible.
Pre-flight 3->4: client returns full receipts; adapter must preserve error metadata in pinned FastMCP; characterize actual stdio.
Ruling: Execute inline on the approved scope with one final independent review — four tightly coupled tasks share interfaces — risk is mitigated by task tests and final review.
Ruling: Native Nuke verification may launch a fresh NC GUI with a temporary NUKE_PATH; do not edit permanent user startup — requested live check requires a host — commercial behavior remains unqualified.
Task 1: complete (commits ad55c96..8452dbe, tests: D:/nuke_mcp/.venv/Scripts/python.exe -m unittest tests.test_protocol -v → OK)
Task 2: complete (commits 8452dbe..538d702, tests: D:/nuke_mcp/.venv/Scripts/python.exe -m unittest tests.test_operations -v → OK)
Task 3: complete (commits 538d702..8ea814d, tests: D:/nuke_mcp/.venv/Scripts/python.exe -m unittest tests.test_runtime tests.test_client -v → OK)
Task 4: complete (commits 8ea814d..fc4020a, tests: D:/nuke_mcp/.venv/Scripts/python.exe -m unittest discover -s tests -p test_*.py -v → OK)
Final: fixed shutdown during native nested render — test_stop_in_native_nested_loop_closes_job_after_frame_returns RED→GREEN, suite 45/45.
Final: fixed preliminary failure hiding applied mutation — test_failed_optional_read_does_not_hide_successful_mutation and test_failure_after_applied_step_cannot_report_not_started RED→GREEN, suite 45/45.
Final: fixed native environment default render lookup — test_native_nc_environment_rejects_render_all_before_mutation RED→GREEN, suite 45/45.
Final: no deferred minor findings.
