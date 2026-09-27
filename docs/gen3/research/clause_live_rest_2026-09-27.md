# CLAUSE-LIVE-REST

Private development checkout: `C:/slink-wt/g3-clause-live-rest` on
`codex/gen3-clause-live-rest`. Qualification ran in a separate frozen, clean
checkout at `C:/slink-wt/g3-clause-run`, with its own `SLINK_STATE_DIR` and
temporary server state under `.cache/state/`. The runner terminated only its
own EmuHawk/server PIDs. No other workers' processes or state were modified.

`SOURCE`, `MODEL` and `PHYSICAL` remain separate. PASS here means the named
duo row passed its native-input client results, production-wire and persisted
state oracle, and independent game-save witness at its stated cut. It is not
a full game/release signature. The original pre-card parity table is the
historical reply recorded in `e_parity_ledger_2026-09-27.md`.

| Cell | Title as A | Clean cut | PASS receipt | Specific observed behavior |
| --- | --- | --- | --- | --- |
| C3b pre-ball gate | LeafGreen | `6349ba01` | [receipt](../probes/clause_live_rest_ball_gate_lgfr_6349ba01.txt) | Closed pre-ball gate; native reward; disclosed stock phase; real catch/link; matching saved Balls. |
| C3b pre-ball gate | Emerald | `6349ba01` | [receipt](../probes/clause_live_rest_ball_gate_emerald_6349ba01.txt) | Same gate, native reward and saved second-phase link. |
| C3b pre-ball gate | Radical Red | `49d99c6c` | [receipt](../probes/clause_live_rest_ball_gate_gen3_gen3_rr_49d99c6c.txt) | Same gate and native ten-Ball parcel reward, with no stock edit. An earlier RR final-cut row had failed. |
| C3l PC release | FireRed | `6349ba01` | [receipt](../probes/clause_live_rest_release_gen3_gen3_frlg_6349ba01.txt) | Native PC removal; linked partner retirement/memorial; both saved witnesses. |
| C3l PC release | LeafGreen | `6349ba01` | [receipt](../probes/clause_live_rest_release_gen3_gen3_lgfr_6349ba01.txt) | Same, with LG as A. |
| C3l PC release | Radical Red | `6349ba01` | [receipt](../probes/clause_live_rest_release_gen3_gen3_rr_6349ba01.txt) | Same, including RR extension RAM/save witness. |
| C3s shiny bonus | FireRed | `49d99c6c` | [receipt](../probes/clause_live_rest_shiny_bonus_gen3_gen3_frlg_49d99c6c.txt) | Disclosed PID prep; four native captures; ordinary pair plus shiny bonus pair; saved Ball debits. |
| C3s shiny bonus | LeafGreen | `49d99c6c` | [receipt](../probes/clause_live_rest_shiny_bonus_gen3_gen3_lgfr_49d99c6c.txt) | Same, LG as A. |
| C3s shiny bonus | Radical Red | `49d99c6c` | [receipt](../probes/clause_live_rest_shiny_bonus_gen3_gen3_rr_49d99c6c.txt) | Same, with live extension RAM/save witness. |
| C3s shiny bonus | Emerald | `a643a2b6` | [receipt](../probes/clause_live_rest_shiny_bonus_gen3_gen3_emerald_a643a2b6.txt) | Same. Attempt1 ended in native whiteout; attempt2 passed from fresh state. |
| C3r gender | Radical Red | `49d99c6c` | [receipt](../probes/clause_live_rest_gender_clause_gen3_gen3_rr_49d99c6c.txt) | Native rejected capture/memorial; A quarantined; area retryable; PASS on attempt4/8. |
| C3r type | Radical Red | `49d99c6c` | [receipt](../probes/clause_live_rest_type_clause_gen3_gen3_rr_49d99c6c.txt) | Same rejection/retirement/area readback for type, PASS attempt1/3. |
| C3r species/dupes | Radical Red | `a643a2b6` | [receipt](../probes/clause_live_rest_species_clause_gen3_gen3_rr_a643a2b6.txt) | Native repeated-family RUN/reroll followed by a legal paired catch; PASS attempt3/8. |
| C3r evolution family | Radical Red | `a643a2b6` | [receipt](../probes/clause_live_rest_species_family_gen3_gen3_rr_a643a2b6.txt) | Route1 Galarian Zigzagoon1222, real RUN/reroll prompt/event against B Linoone-Galar1223; staged pair alive and saved, PASS attempt8/16. |

FireRed's ball gate and Emerald's PC release had already passed on earlier
assigned lanes and were not rerun in this card. FR/LG/E gender, type and
species-family rows are not promoted by the new RR receipt. The table names
each new result at the exact source cut it exercised; later unrelated changes
are not silently treated as recut evidence.

## Shiny setup boundary

No natural shiny-generation probability was qualified. O-33 allowed a
**disclosed SYNTH setup**: after the first ordinary native pair was formed,
the driver parked at A's next wild battle action menu. The host read the
cartridge's complete 100-byte enemy record and constructed a shiny PID that
kept its low byte and nature. It re-encoded the record with the own title's
checksum/permutation rule; no other decoded field changed. A Lua helper
independently checked the current preimage, native decoder, changed-field
boundary and readback before one frame resumed. It did not inject a capture,
server event, bonus-pair row or result. The ordinary BAG/throw/catch sequence,
production client `TX capture` events, server exception/entitlement, B's
next native capture, pairing, and both in-game saves followed that setup.

The saved oracle required an existing normal pair in the same area, exactly
one shiny entitlement/pending slot, its consumption by B's ordinary catch,
exactly two persisted alive links (the second in `_bonus_<PID>`), a shiny flag
on A's bonus half, four keyed production captures in order, no rejected or
quarantined bonus catch, complete saved party/box membership, valid own-ROM
records, matching throw debits, and both save witnesses. It rejected wrong
setup bytes, changed fields, wrong scenario or repeated setup in MODEL tests.

## Failures retained without promotion

The first LG gate run completed native steps but the final runner still read
phase-one PASS receipts, omitting `BALL_STOCK_READY` from PYDEC. It is FAIL;
the final-result reader was fixed red/green in `6349ba01`, then LG/E were
rerun. An Emerald gate run was refused solely because the development tree
had a new uncommitted LG receipt (+dirty). The separate frozen run checkout
prevented that on accepted rows. These failed artifacts remain under
`.cache/live/lg_ball_before_result_fix/` and
`.cache/live/emerald_ball_dirty_cut/` in the development checkout.

RR family attempt1 at `49d99c6c` exposed a consumer mismatch: the Lua
producer emitted numeric map `787` (3*256+19, Route1), while the Python oracle
expected dotted text `3.19`. The failing receipt and red/green control are
retained; `a643a2b6` checks the numeric map. In the accepted RR family run,
attempts1–7 observed unrelated species and were correctly unobserved, not
called PASS. Attempt8 observed1222 and passed. Their numbered client/PYDEC
receipts are retained; earlier retry save-witness files were reused, so no
per-attempt native-save claim is made for attempts1–7.

The earlier RR species-clause final-cut receipt was unobserved on all eight
attempts. The new row made one native reroll and passed on attempt3/8; its
first two unrelated attempts remain in the archived numbered receipts.

Emerald shiny attempt1 ended in a native whiteout before the baseline pair;
the runner classified it as game RNG and retried from fresh server/SaveRAM
state. It does not contribute to the accepted attempt2 proof.

The accepted local raw artifact copies and SHA-256 manifests are in
`C:/slink-wt/g3-clause-live-rest/.cache/live/<row>_<title>_<cut>/`;
title-specific saved witness lines and ROM/fixture/profile hashes are in the
tracked receipts above. Server-state directories remain in
`C:/slink-wt/g3-clause-run/.cache/state/`.

## Verification

Shiny setup, real Lua decoder/writer controls and server/saved-model
falsifiers: **23 passed / 0 skipped**. C3 map-shape control was red before the
fix and the affected family/clause controls were **134 passed** after.
Full `tests/unit` on the final combined code exited 0: **12611 passed,
4244 skipped, zero failures**, 680.60 seconds, with three SyntaxWarnings.
The 154 selected clause, reader, shiny and citation controls had **zero
skips or failures**. The first full run found 11 citation offsets drifted by
the integrated `state.py` changes; all nine citation tests passed after the
documentation repair and again in the full rerun. Tests used default pytest
temporary directories and retention on failure. Final receipts:
`.cache/clause-live-full-final.log` and `.xml`. Live results above are from
the frozen checkout, not from unit tests. No web/UI or release gate is claimed.
