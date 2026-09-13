# P0: Inspect the RC machine and input prerequisites

This is a self-contained **read-only dispatch brief**. Current assignment/authority lives only in [the master guide](../RC_MASTER_GUIDE.md). The coordinator sends this path with the assignee identity and records its acknowledgment before ACTIVE. This brief grants no implementation or emulator work.

## Outcome and blocking edges

Produce a precise list of available/missing/mismatched RC inputs and unresolved environment/runtime budgets. No code change is required. Research blockers: none after coordinator assignment; unavailable inputs are reportable outcomes, not reasons to guess or install.

## Start and scope

- Canonical checkout: `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, branch `gen1/rc`. Product code reference: `df38453`; later docs-only commits are expected. Record actual HEAD/UTC and refuse an unexplained source difference.
- Coordinator: owning task `01a06d9c-4200-7023-a822-7663ed2ea1dd` via the assigning task/verified ClaudEx route. Report your runtime/session identity and capabilities first.
- Host: inspect the local machine you are executing on; call it the final RC machine only if the coordinator's assignment says so. Use the already available Python interpreter and record its resolved path/version. A missing interpreter or different host is a reported gap.
- Reads: [manifest](../../../tests/gen1_release_requirements.json), [input pins](../../../tests/gen1_release_inputs.json), [evaluator](../../../tools/verify_gen1_release.py), exact dependency paths it resolves, and only the skip sites reached by its unit/integration argv.
- Sole permitted output: `docs/gen1_reference/reviews/P0-<assignment-id>.md`. Choose a filesystem-safe unique assignment ID supplied by the coordinator or return the report to the coordinator if your runtime is read-only. No source, manifest, inventory, privilege or dependency changes.

## Established basis

The manifest has 388 requirements, 224 registered and 164 empty at source cut df38453. Confirm current counts. `prerequisite_problems` checks fixture/source pins plus eight prerequisite entries; seven have hashes, Java only executable presence. `--verify-inputs` returns without invoking test checks or creating an automation report. Code: `tools/verify_gen1_release.py::prerequisite_problems/main`.

## Steps and receipts

1. Record branch/HEAD/dirty paths, host and interpreter. Done when these match the assignment or the exact mismatch is reported.
2. Parse the manifest and input-pins JSON. Record every prerequisite ID, actual resolved path, required hash policy and result; distinguish absent, mismatched and unavailable. Resolve env overrides and executable lookup exactly as the evaluator does. The entries are three local legal R/B/Y ROMs; `SLINK_EMUHAWK` plus adjacent assemblies; `SLINK_UPR_JAR`; `SLINK_JAVA` or `java`; `SLINK_AP_APWORLD` or its manifest default; and the local LuaSocket DLL.
3. Run only `python tools/verify_gen1_release.py --verify-inputs` using the recorded interpreter. Retain exact stdout/stderr/exit code. A failure remains a failure; no re-pin, dependency install, `--quick`, test suite, inventory write or emulator launch under P0.
4. Statically trace skip/import/ROM/symlink conditions in the unit/integration selection. Classify required dependencies separately from intentional conditional behavior; “install dependencies” is not a universal fix. Starting references: `tests/unit/test_http_server_security.py`, `test_sprite_html_contract.py`, `test_routes_smoke.py`. Do not execute the suites under this card.
5. Read configured timeouts and any existing measured duration reports. Current unit/integration caps are one hour each, live-gates four hours and duo-pairs twelve hours; verify current values. A timeout cap is not a duration estimate. Report final-host availability and new-scenario budget as unknown when no receipt exists.
6. Return per-input result, skip-site classifications, evidence path and hash, exact unresolved facts, and one next owner/action. Done when all eight entries and every known mismatch have an explicit outcome and coordinator records acceptance/HOLD in the master guide.

## Suggested skills

`ask-matt` selects a workflow; `research` may help investigate a specific unresolved dependency against primary sources. `writing-for-agents` governs the report. A missing skill does not block these explicit steps. F1's execution census is a later assigned task.
