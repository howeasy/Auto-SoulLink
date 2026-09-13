# F1 full unit execution, source 15727ec

Coordinator/evidence runner Codex `01a09ae0-ad6f-7b01-8753-5e6b71eb1cfa`, HOUNDOOM. Result: **HOLD — 7,800 passed, 15 failed, zero errors/skips**, 7,815 cases, process exit 1. Console duration 822.92 seconds; XML suite time 822.026 seconds. Started after reviewed N0-root integration on 2026-09-13; completed by 14:31 UTC. Production/tests stayed frozen during the run; later commits were coordinator documentation only.

```text
C:/Users/howar/AppData/Local/Programs/Python/Python312/python.exe -m pytest tests/unit -q -ra -p no:randomly -o addopts= --junitxml=.cache/f1-unit-successor.xml
```

Process-local P0 values: `SLINK_EMUHAWK=E:/Howard/Bizhawk/EmuHawk.exe`, `SLINK_UPR_JAR=E:/Google Drive/SLink/.cache/upr/PokeRandoZX.jar`; `PYTHONDONTWRITEBYTECODE=1`. No `-k`/`-m` selection, installation, input-pin or manifest/inventory rewrite. This is full-directory development evidence, not a release-evaluator verdict.

| File | Failures | Observed failure signature, not yet a root-cause verdict |
| --- | ---: | --- |
| tests/unit/test_gen1_authorized_inventory.py | 4 | Three HUD receipt mismatches; one pending-command count 3 versus expected 1. |
| tests/unit/test_gen1_memorial_policy.py | 6 | HUD receipt mismatch blocks intended memorial/retention or refusal assertions. |
| tests/unit/test_gen1_control_view.py | 1 | Returned view additionally contains `pending_delivery: false`. |
| tests/unit/test_gen1_no_catch_retirement_flow.py | 3 | `one exact pending retirement obligation required`. |
| tests/unit/test_runtime_fairness.py | 1 | Fixture observation ACK lacks exact committed settlement; connection revokes before fairness assertion. |

| Ignored local receipt | Raw SHA256 |
| --- | --- |
| .cache/f1-unit-successor.xml | `e8f1fe83c3221edf2142fd6720d334575522f9d29b6445fd2832ad3fc4d47064` |
| .cache/f1-unit-successor.txt | `cead2a0b23266e0c3f01e2f37cdf8756e4d7a2d6363d9012554713f80d9168d8` |

The XML/text retain all 15 exact IDs and tracebacks. Initial inspection suggests stale fixture contracts in several groups; that is a hypothesis requiring source reconciliation and focused red/green checks. Do not alter production validation, suppress commands, drop assertions, skip tests, or label these passing. Source code written by the coordinator will be delegated to Sol per the owner's latest instruction; context-sensitive Claude work and short OMP receipt/coordination checks continue through their skills.

Next: separately granted disjoint repairs, independent review, and a complete rerun once the combined repaired cut is frozen; integration and actual CLI evidence remain open.
