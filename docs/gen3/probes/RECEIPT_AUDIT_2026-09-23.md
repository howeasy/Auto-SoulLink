# G4 receipt audit, 2026-09-23 (Codex REV-receipt-audit-1)

Independent, read-only audit of the committed G4 live receipts at 1b82522f, re-checked at 72a8ec90.
Protocol conformance at 72a8ec90: 61/61.

| Receipt | Verdict | Note |
|---|---|---|
| faint_cmd_gen3 (a, b) | citable with caveat | b at d199da32. Proves an injected-event OVERWORLD faint and memorial persistence, not a natural battle faint. |
| link_gen3 (a, b) | citable with caveat | b at d199da32. The attempt-2 retry was legitimate: B started with 2 balls and ran out after real throws. The wording "only ball missed" is stale. |
| boxsync_gen3 (a, b) | citable with caveat | b at d199da32. Keyed A PC round trip, B mirrored; not B manually using the LG PC. |
| reconnect_gen3 + wrong_save (a, b) | citable with caveat | C-1/C-2 hold. "Zero writes" counts completed sink logs, not attempted writes or live RAM. Re-take for the stronger claim. |
| linked_faint_active_gen3 | citable with caveat | At eaa96787. FR natural faint, LG active hold, then HP 0 in battle after the switch-out; not doubles, trainer, or all of G4 2b. |
| bootcheck rehearsal | re-take on final cut | Compares only ordered (species, level), with no PID/OTID identity proof. |
| release zip boot rehearsal | re-take on final cut | Cite the correction c8f0c804 (the export matched 99c70d9c). |
| 10 committed *_gen3_new.jsonl goldens | citable | Wire-only conformance evidence. |

Supersession:
- f2aec36f is an ancestor of d199da32.
- 595c434f is generator/tests only (the runtime profile is byte-identical).
- 684bbb7a needs new deadzone evidence.
- eaa96787 needs the full G4 2b matrix.
- 72a8ec90 invalidates no listed oracle.

A final frozen-cut re-run of faint/link/boxsync/reconnect is sensible regression evidence.

Gaps routed as C4-6n:
- self-contained receipt provenance (an IDENTITY line for every scenario);
- raw per-side RESULT lines kept in receipts;
- reconnect C-1 zero ATTEMPTED writes plus unchanged RAM;
- boot-check comparing keys (PID/OTID), not just (species, level).
