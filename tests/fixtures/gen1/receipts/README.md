# Historical Gen 1 receipts

**2026-10-03 — receipt-binding migration.** The archived e2e_*_result.txt files here predate the current Gen 1 ROM binding: their client built lines lack pack= and kind=. They are historical reproduction evidence, not qualification for the current source cut.

The coordinator will capture replacement receipts in the next authorized live rerun. Those receipts must pass the companion-kind and cartridge-hash checks, with the parsed client prefix recorded separately from the computed prefix in GEN1_ROM_SHA1. SYNTH rows must also bind each instance's initial catch ball count to its current GEN1_SYNTH_SETUP disclosure.

Do not backfill or hand-edit the historical logs to make them pass the new contract. Their earlier PASS totals do not close the current live lanes; the new rerun's receipts will supersede them.
