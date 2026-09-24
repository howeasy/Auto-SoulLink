# P4.4 promotion gap audit (2026-09-24)

Card P4.4-GAP. What stands between `codex/gen2-foundation` today and the owner's **G4** signature
(`docs/gen2/PLAN.md:183` "G4 — first RC-eligible gate"; substep **P4.4** at
`docs/gen2/GEN2_BINDING_PLAN.md:361`: "Reopened receipts + matrix promotion" — reopen build,
admission, site, checkpoint and natural-rules receipts on the patched build; only then do overlay
rows carry real hashes and become ADMITTED; owner plays the overlay build and signs).

## Tool verdicts run for this card (no emulator)

| Command | Verdict |
|---|---|
| `python tools/verify_gen2_release.py --help` | Documents `--quick`/`--list`/`--lane`; states plainly that `patch-build`, `live-gates`, `live-trade-gates`, `duo-pairs`, `release-evidence` are "deliberately unimplemented P3b/P4/P6 bindings and fail when requested, even if a file with the future name happens to exist." |
| `python tools/verify_gen2_release.py --list` | Confirms the above in code (`tools/verify_gen2_release.py:122-147`, `UNIMPLEMENTED` dict at `:176-186`, enforced at `:1197-1198` before the lane's argv even runs). |
| `python tools/verify_gen2_release.py --lane duo-link` | **RED** — 18 gaps, one per (pair × trade scenario): `gen2_trade_new`, `gen2_trade_decline_new`, `gen2_trade_refuse_item`, `gen2_trade_reset_commit`, `gen2_trade_reset_wait`, `gen2_trade_timeout` are registered in `tools/e2e_duo.py` (via `tools/gen2_trade_lane.py`) but **not yet added** to `tests/gen2_release_requirements.json`'s duo matrix for C↔C, G↔S or C↔G. |
| `python tools/verify_gen2_release.py --lane live-new-gates` | **RED** — panel/sfx/w6/phone gate receipts for Crystal, Gold and Silver all say "receipt proves another overlay build than the published one." The last overlay republish (`d09e76c1`, C `651dc6bf`/G `d563669e`/S `76c6c112`) landed **after** the last re-pin (`4a157d4a`), so all four gate families are stale again. |
| `python -m pytest tests/unit -q -x -k "gen2 and (release or receipt or admission)"` | **407 passed, 1 failed** (stopped at first failure, `-x`): `test_gen2_physical_receipts.py`-family and `test_verify_gen2_release_lanes.py` tests pass except `test_committed_new_gates_tree_is_fully_green`, which fails for the identical reason as the `live-new-gates` lane above (`new_gates_errors()` returns the 12 stale-overlay entries). This is the same single root cause, not a second defect. |
| `python tools/verify_gen2_release.py --quick` | Started but did not return within this card's session (background PID contended with the ~7 other subagents' emulator/pytest/build load noted in `docs/gen2/RESUME.md` "Session 8, day 2"); not required to reach a verdict, since `--lane duo-link`, `--lane live-new-gates` and the pytest run above already exercise the same fast-lane code paths and found the same two RED conditions. |

No `git stash` was used. Other workers' uncommitted hunks (`tools/e2e_duo.py`, `lua/gen2/client.lua`,
`patch/gen2/src/trade_service.asm`, `server/state.py`, `tools/gen2_trade_reconciliation.py`, the
`tests/unit/test_gen2_trade_*` and `tests/unit/test_state_trade_uncertain.py` files, new file
`tools/gen2_trade_oracles.py`) are all read but untouched; `git diff --stat` shows a 30-file / 833(+)/167(-)
diff plus 4 untracked files (`tools/gen2_trade_oracles.py`, `lua/tests/gen2_walk.lua`,
`tests/unit/test_e2e_duo_trade.py`, `tests/unit/test_gen2_trade_gates.py`), all attributable to
HARNESS/TRADE-HARDEN/TRADE-ASM per `docs/gen2/RESUME.md`'s "Running at compaction" list. The two RED
verdicts above are read against **committed** state (`.qualification.json`/receipt files and
`tests/gen2_release_requirements.json` are all committed; the uncommitted hunks are server-FSM and
trade-lane code, not receipts), so neither RED is an artifact of someone else's WIP mid-edit — both
are real, currently-true gaps that in-flight cards are already aimed at closing.

## G4 requirement table

| G4 requirement (PLAN §6 / GEN2_BINDING_PLAN P4.1-P4.4) | Status | Evidence | Owner / in-flight worker |
|---|---|---|---|
| **P4.1** panel: saved-region symbol equality, `.map` placement equality, live clean↔overlay round trip, SLINK row opens, UPS byte-reproducible, GBC fade stress (N-1, C-3 panel half) | **PHYSICAL, but STALE** — panel gate passed and was re-pinned once (`4a157d4a`) after an earlier overlay publish, then invalidated again by the next overlay publish (`d09e76c1`) | `new-gates.panel.{crystal,gold,silver}` all RED in `--lane live-new-gates` today | **TRADE-ASM** (a301092ac0ba8f1ce) — "republish overlays, re-pin panel/sfx/phone/W6" is its explicit task |
| **P4.2** native sound: ticket-16 service sites qualified per context, caller/context ABI, busy/consumption, reset controls (N-2) | **PHYSICAL, but STALE** — same overlay-republish invalidation as panel | `new-gates.sfx.{crystal,gold,silver}` RED | **TRADE-ASM**, same task |
| W-6 mailbox writer-exclusion tripwire (feeds P4.1's "no bank placement assumed" writer-exclusion contract) | **PHYSICAL, but STALE** | `new-gates.w6.{crystal,silver,gold}` RED | **TRADE-ASM**, same task |
| P4.5 phone easter egg (O-29: "flavour only; never blocks the release") | STALE too, but **does not gate G4** per O-29 | `new-gates.phone.{crystal,gold,silver}` RED | TRADE-ASM re-pins it anyway as part of the same batch; not itself a G4 blocker |
| **P4.3** trade receptionist takeover: wait/payload/patch/mail exchange/confirmation/both animations/post-trade sync/save ack, over the source `LinkTrade→AddTempmonToParty→EvolvePokemon→SaveAfterLinkTrade` sequence, never a one-byte bypass (T-1, T-2) | asm published (`bd6c68b1`, republished `d09e76c1`) + Lua trade binder committed (`ff576e02`/`8c561345`/`ed7f87c6`); **no live duo has run it yet** | no PASS receipt exists for any `gen2_trade_*` scenario on any pair | **TRADE-DRIVER** (drivers, contract `p43e_driver_contract.md`) + a not-yet-started **LIVE worker** ("Next after HARNESS + TRADE-ASM: a LIVE worker for trade lanes") |
| Held item validated/carried/read back both halves; invalid item refused before commit (T-3, O-14) | Test-only harness proof plan approved (**O-31**, disclosed `HARNESS_WRITE`), but **not yet run live** | O-31 ruling recorded (`26564aed`); `tools/gen2_trade_oracles.py` (untracked) exists but unreceipted | **HARNESS** |
| Save reload after trade shows the exact traded record (T-4) | Not yet run | none | not started — folds into the same LIVE trade-lane worker as T-1/T-2 above |
| One-sided trade commit bug (a proposer-leave race that could apply only the partner's half) | **Fix in progress, uncommitted** in `server/state.py` (initiator-withdraw-before-partner-answer guard, `trade_offer_ack` token, single-journal-per-side uncertain path) | `git diff server/state.py` (33 lines changed, uncommitted) | **TRADE-HARDEN** (a2e4b167c1a20a405) |
| Server uncertain-trade reconciliation (settle from party evidence, never guess) | **Landed but MODEL only** (`1ac09296`, `9a436c95`); no PHYSICAL duo exercises it yet | commit message says "MODEL" explicitly; RESUME session-8-day-2 note | folds into the LIVE trade-lane worker once TRADE-HARDEN + HARNESS land |
| Trade duo matrix registration (`gen2_trade_new`/`decline_new`/`timeout`/`reset_wait`/`reset_commit`/`refuse_item` × C↔C/G↔S/C↔G in `tests/gen2_release_requirements.json`) | **RED today** (verified above), scenarios exist in `tools/gen2_trade_lane.py`/`tools/e2e_duo.py` but the release matrix doesn't list them yet | `--lane duo-link` output, 18 gaps | **HARNESS** ("register 7 trade cases" — 6 scenario names found in `tools/gen2_trade_lane.py`, one more likely a 7th case HARNESS is adding, e.g. a mail/D3-refusal case) |
| `tests/live/test_gen2_trade_gates.py` (named by PLAN P4.2's sound rows and P4.3's exit evidence, and by `verify_gen2_release.py`'s `live-gates`/`live-trade-gates` lane definitions) | **Missing file** — does not exist in the tree at all | `ls tests/live/test_gen2_trade_gates.py` → no such file | **Not explicitly named as anyone's deliverable** in the current worker roster (see gap 1 below) |
| `verify_gen2_release.py` lanes `patch-build`, `live-gates`, `live-trade-gates`, `duo-pairs`, `release-evidence` | **Hardcoded UNIMPLEMENTED placeholders** — always fail regardless of what physical evidence exists, by explicit design (`tools/verify_gen2_release.py:176-186`) | code read, confirmed at `--list` | **Not explicitly named as anyone's deliverable** (see gap 2 below); `duo-pairs`/`fixtures` are at least *documented* as intentionally-future in `docs/gen2/RESUME.md`/`DUO_SCENARIO_ROADMAP`; `patch-build`/`live-gates`/`live-trade-gates`/`release-evidence` are not discussed anywhere as a wiring card |
| P4.4 itself: promote overlay rows PLANNED→ADMITTED in the artifact matrix; write the §6.1 ledger G4 row | **Not started** — correctly blocked on all of the above (RESUME: "P4.4 promotion (owner G4 signature)" sits in the queue, not in flight) | `docs/gen2/PLAN.md` §6.1 ledger still shows `G4 \| — \| — \| — \| —` | **coordinator** (own task per the plan; "frozen-source evaluator") |

## Unowned gaps

Two things stand between the in-flight work finishing and an actual G4 promotion, and neither is
named as any current worker's deliverable:

1. **`tests/live/test_gen2_trade_gates.py` does not exist.** The PLAN names it three times (P4.2's
   sound rows, P4.3's trade rows, and it's literally what `verify_gen2_release.py`'s `live-gates`
   and `live-trade-gates` Lane objects invoke). TRADE-DRIVER/HARNESS own the trade *duo drivers* and
   *oracles*, but nobody's task description mentions authoring this specific pytest file.
2. **`verify_gen2_release.py`'s `patch-build`, `live-gates`, `live-trade-gates` and `release-evidence`
   lanes are permanently-failing placeholders** (`UNIMPLEMENTED` dict, `tools/verify_gen2_release.py:176-186`),
   by original design ("even if a file with the future name happens to exist"). Once TRADE-ASM
   re-pins panel/sfx/w6 and HARNESS/TRADE-DRIVER land real trade receipts, these lane *bodies* still
   need to be turned from hardcoded failures into real checks (or the `UNIMPLEMENTED` entries removed)
   before `tools/verify_gen2_release.py` — without `--quick`, per §9's standing-gate rule — can ever
   go green. `duo-pairs` and `fixtures` are at least called out elsewhere as known-future; these four
   are not discussed as a wiring card anywhere in `docs/gen2/RESUME.md`, `PLAN.md`, `GEN2_BINDING_PLAN.md`
   or `REVIEW_RECORD.md`.

Everything else found in this audit (overlay-republish staleness on panel/sfx/w6/phone, the trade
duo-matrix registration gap, the one-sided-commit race, the MODEL-only server reconciliation, no live
trade run yet) maps cleanly onto an already-running or already-queued worker per `docs/gen2/RESUME.md`'s
"Session 8, day 2" note.
