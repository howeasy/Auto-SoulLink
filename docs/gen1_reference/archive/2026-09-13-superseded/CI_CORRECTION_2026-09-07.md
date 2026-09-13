# Shared-branch CI correction - September 7

Fourteen failed runs across thirteen shared branches stopped during collection because the published baseline included PIL image-recording tests without declaring Pillow. Local environments already contained the package. Publishing without checking those remote results was an error.

Added Pillow==11.3.0 to requirements-dev.txt only. No test assertions, selection, workflows or runtime dependencies were changed. Corrections are new fast-forward commits; original component commits and historical runs remain intact.

Fresh exact-tree Python 3.12 environment: 2929 passed, 15 existing Windows skips, 11 subtests; required Ruff and 223 Lua parses passed. The separate snapshot/driver support cut also passed its exact-tree suite and GitHub. These are shared CI results, not release approval.

| Branch | Current commit | GitHub result |
| --- | --- | --- |
| codex/shared-suspension-hook-v1 | e8aa57445845 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118247011) |
| codex/shared-rom-change-audit-v1 | 24873eff2648 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118476095) |
| codex/shared-staged-panel-v1 | ebcba8d2b9d9 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118475193) |
| codex/shared-patch-plan-v1 | aed92192fa3e | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118475680) |
| codex/shared-client-journal-v2 | 350b67caf118 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118476058) |
| codex/shared-trade-runtime-composition-v1 | 71ecaeaa28f1 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118475450) |
| codex/shared-launcher-reader-v1 | ceb7fec31902 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118475270) |
| codex/shared-stat-experience-v1 | ca3247c06a33 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118475667) |
| codex/shared-durable-server-v1 | d5599b80999b | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118475319) |
| codex/shared-integer-journal-json-v1 | 593901d31320 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118476222) |
| codex/shared-saveram-v1 | 524f5ddb3bd4 | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118476447) |
| codex/shared-trade-coordinator-v1 | 031dd87ad0bd | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118476215) |
| codex/shared-atomic-records-core-v1 | 6bb9bfa6652f | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34118475931) |
| codex/shared-native-runtime-support-v1 | e261d1388eef | [Passed](https://github.com/howeasy/Auto-SoulLink/actions/runs/34124342726) |
