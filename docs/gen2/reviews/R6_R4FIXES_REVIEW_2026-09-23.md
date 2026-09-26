# R6: independent review of 41e3ea5 (R4 fixes, N10), Codex Gen2-Part2, 2026-09-23

Read-only code/MODEL review of frozen `41e3ea5` against `R4_CODEX_REVIEW_2026-09-22.md`. Not PHYSICAL
qualification; do not sign R4 closure or G3 on it. Coordinator spot-checked #6
(`tests/live/test_gen2_new_gates.py:107-130`) and S1 (`tools/gen2_fixtures.py:666`): both hold.
Reviewer ran `tests/unit/test_gen2_client.py` + `test_gen2_signals.py` (129 passed); fixtures/inspect files
source-reviewed only.

| R4 item | Verdict | Residual (cites at 41e3ea5) |
|---|---|---|
| 1 badges | CLOSED | Johto/Kanto raw_hex compare; one-byte negatives red |
| 2 phone timers | REFUTED (correctly dropped) | unsaved `wMapStatus` |
| 3 map-object fields | PARTIAL, MEDIUM | player map-object Y/X is a blanket free span (`gen2_fixtures.py:139,702-709`) though source derives it from saved `wYCoord/wXCoord`+4 (C `engine/overworld/player_object.asm:102-122`, G `:87-107`); NPC struct IDs free at `:138`; the test at `test_gen2_fixtures.py:577-582` accepts arbitrary changes |
| 4 overworld via boot stage | CLOSED (MODEL) | first live calibration unrun |
| 5 100% speed | CLOSED | — |
| 6 identity binding | PARTIAL, HIGH | `qualified_identity` accepts `{scope:full, passed:true}` with only a `qualify` PASS stage; ignores required_stages, missing boot/resave/post_oracle, report errors, row problems; the unit helper `test_gen2_inspect_gate.py:485-505` builds that truncated receipt and asserts acceptance. Real chain: `tools/fixture_qualification.py:17,180-225` |
| 7 dump provenance | CLOSED (MODEL) | first real dump is a PHYSICAL gate |
| 8 fishing association | OPEN, LOW | `tools/gen_gen2_area_map.py:251-252,269-270` unchanged; stays its own generator card |
| S1 resave transitions | PARTIAL, MEDIUM | `a == b: continue` (`gen2_fixtures.py:666`) bypasses every rule: G/S `wGameTimerPaused` counting bit must be set after `FinishContinueFunction` (G `intro_menu.asm:343-349`); a fired daily reset must clear the whole block (C `overworld/time.asm:103-123`, G `:89-96`), not byte-wise old-or-zero (`:670-671`); roamer history must hold backed-up map indices (C `intro_menu.asm:372`, `wildmons.asm:672-703,743-752`); `test_gen2_fixtures.py:628-629` blesses an un-cleared next-day flag; commit body's "late-game state refuses" is stronger than the code (no input-state guard) |
| S2 timeline abandon | PARTIAL, MEDIUM | `abandon_timeline` leaves `self.deferred`, `pending_safe`, key aliases and hello readiness: a pre-rewind `force_faint` (`lua/gen2/client.lua:340-358`) can run via `run_deferred` (`:771`, `:423-442`); a pre-rewind `battle_end` leaves `pending_safe` (`:525`) and sends a stale `safe` (`:766-769`); no tests |
| S3 resave witness | CLOSED | — |

Disposition: accepted 11/11 as stated. Fix cards: gen2-N14a (#6, S2) and gen2-N14b (#3, S1; after N11
releases `tools/gen2_fixtures.py`). #8 stays with the fishing generator card.
