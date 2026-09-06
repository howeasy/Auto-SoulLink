# Restricted UI handoff validation

The integrated source combines the Gen1 worktree based on
`79d5172ba44acf136b58443015c4a45812ee55e5` with tested UI Track A
`965cc12664b1c9b5ee27d8fc4a97a5cf06a6b065`. The two merge conflicts were imports
in `server.py` and `manager.py`; both sets were retained. The Manager empty-status
factory gained the existing run serializer's admission fields. No normalized
Phase3 projection or renderer was created by the runtime work.

Validation on the integrated source:

- Full unit and integration suite: **3638 passed, 2 skipped**. The two skips are
  existing Windows symlink-privilege cases in HTTP file-serving tests. Actual
  junction-escape checks ran. These skips are not accepted as RBY release proof.
- Explicit Gen3 adapter/rival/state/Explode/launcher checks plus runtime boundary,
  Manager restriction and HTTP-hardening contracts: **643 passed, no skips**.
- Required CI Ruff rules `E9,F6,F7,F81,F82`: passed.
- Every Lua source parsed: **216 files passed**.
- Git whitespace check: passed with the worktree's configured line endings.

Local detailed logs/JUnit artifacts are `.cache/ui-final-full.{log,xml}` and
`.cache/ui-gen3-check.{log,xml}` in the Gen1 worktree. The focused boundary tests
cover all nine ordered RBY title pairs, detached state/contract reads, fresh
observation age, no liveness/receipt fabrication, no queue draining, stopped-run
read refusal, real Gen3 mutation compatibility, AP restriction exclusion, and
RBY mutation refusal before request processing.

The shared library inputs included in this baseline are the reviewed foundation
`654c7c7fb55e9465a493850d19346fee1aabb9f6`, executor
`e1105928246761abe4124535643ffd655be2a208`, frame batch
`5765ce4247d9a08fa1605a270466c1865d9bc0d1`, SaveIdentity
`a6148a1d87adec51435f951babeb4d68ca465ab4`, and recovery/control
`a5c1f075f9d3f10962ea3f81d183fedeade406ea`. Only their reviewed file changes were
imported; the RR development branch was not merged. Later asynchronous native
executor work is a separate handoff and is not required by this UI boundary.

This evidence qualifies the restricted integration candidate for UI inspection.
It does not establish complete RBY gameplay, native receptionist reachability,
paired physical trade/recovery, full UPR provenance, host interlocks or release
readiness. Existing RBY release inventory/proof pins need their next reviewed
refresh after continued implementation; old release reports must not be read as
validation of this new snapshot. No ROM, JAR, emulator or private SaveRAM artifact
is included in the handoff commit.
