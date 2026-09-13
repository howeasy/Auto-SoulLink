# F1 integration execution, 2026-09-13

Coordinator ran all tests/integration on HOUNDOOM with production15727ec, HEADedcbf60 and unchanged integration/imported helper source. **157 passed, 4 failed, zero errors/skips**, 161 cases, process exit1 (unified session12862 completion chunkaa068e). Console96.80s, XML96.782s. No selection/deselection.

Command: existing Python3.12.10 `-m pytest tests/integration -q -ra -p no:randomly -p no:cacheprovider -o addopts= --junitxml=.cache/f1-integration-successor.xml`, with the verified P0 process-local emulator/JAR values. No dependency, pin, source or manifest edit.

All four failures are tests/integration/test_gen1_browser_patcher.py: canonical browser patching and three player-specific UPR pair variants. Every failure occurs at the Node subprocess import: **Cannot find module 'playwright'**, Node23.11.0, requiring tests/browser/gen1_patcher.cjs. Browser assertions did not execute; this is an environment blocker, not a proved browser-product defect.

| Frozen local receipt | SHA256 |
| --- | --- |
| .cache/f1-integration-successor.xml | `578bdf38bea638960e1a6b1b70028f18973db3172587f27c95a3a432d6c5be21` |
| .cache/f1-integration-successor.txt | `4027c996cb6609efed8eacdba23c1b5c20aaf36a383e9ca598e87ed76c9a5e3c` |

Next action: resolve an existing Node/Playwright/Chromium installation before any installation request, then one changed-environment rerun. Full F qualification remains HOLD.
