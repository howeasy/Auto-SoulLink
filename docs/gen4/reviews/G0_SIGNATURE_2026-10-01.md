# Gen 4 G0 signature, 2026-10-01

**Owner signature (verbatim chat ruling):** owner 2026-10-01: "Consider all work signd"

Context: the owner had just said, in the same session, "Some work was done by Codex and the plan approved", and then signed with the line above.

**Covers:** G0, as defined in [../PLAN.md](../PLAN.md) §5. That is:
- plan rev 5, with owner decisions D1-D15
- the C0 prerequisite package at `dffdae4c` ([C0 receipt](C0_RECEIPT_2026-09-30.md)): exact pins (`tools/gen4_pins.py`, `data/gen4_sources.lock.json`) and the 174 planned requirement bindings (`tests/gen4_requirements.json`)
- the ledger skeleton (`docs/gen4_requirements.md`)

**Does not cover:**
- any G1-G6 cell, physical evidence or release claim; every behavioural evidence entry remains OPEN
- hge admission (still `RECORDED_NOT_ADMITTED`)
- Platinum (`BIND_ONLY_NOT_ADMITTED`)
- landing, push or tag authority

**Recorded by:** coordinator Claude (Opus 5.5) at merged source `9033a7be`. Master `ea9c8a07` was merged in; the C0 checks are green after the merge: 111 passed, pins PASS, mapping complete.

**Changes made with this record:**
- `docs/gen4/PLAN.md` status line.
- `tests/gen4_requirements.json` `input_sha256.plan` re-pinned to the edited plan. `--seed` re-derivation showed `checks` and `rows` unchanged; only the plan hash differs.
