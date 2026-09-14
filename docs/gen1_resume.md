# Gen 1 master release — resume note (2026-09-14, refreshed 17:05Z — owner paused the session)

Read this first after a context reset. The ledger `docs/gen1_requirements.md` is the authority on
evidence; this note is the working state around it. Plan (owner-approved):
`C:\Users\howar\.claude\plans\system-reminder-you-are-operating-gleaming-pretzel.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`, branch
  `claude/gen1-master-release-plan-6b4279` = **master `e2fefa9`** (the merged UI-migration branch; master
  was FF'd to `79d5172` by the owner, then the UI session merged) **+ ~75 rewrite commits**, rebased
  2026-09-14 (pre-rebase tip tagged `pre-rebase-gen1-release-912a7df`). HEAD `9a8c586` at the time of writing.
  master has since moved to `5c2611e` (UI-only files) — re-rebase once before the final FF.
- The UI-migration session is done; it received the admission receipt (C-5) and closed its last item.
  Reach it via `mcp__ccd_session_mgmt__send_message` to `local_2c735b55-b185-4adc-9986-38df0aac44f2`.
- gen1/rc (`gen1-rby-code-sweep-8d06e2`) stays parked; its RC_MASTER_GUIDE.md checkpoint has a
  `master-release-lane` worker entry that is refreshed at transitions (owner courtesy only).
- Old Gen 1 code is reference-only until Phase 8: `lua/slink_gen1.lua` still launches
  `lua/clients/gen1_rby_client.lua`; the rewrite is launched by `lua/gen1/run.lua` (over
  `lua/gen1/entry.lua`). `tests/unit/test_gen1_adapter.py` is already deleted.
- Receipts for every PHYSICAL row proven by the duo harness or the receptionist gate are committed under
  `tests/fixtures/gen1/receipts/`.

## What is built (all committed; see `git log adf3362..HEAD`)

profile (`tools/gen_gen1_profile.py` from `data/pret/*.sym`, pret 405b624/0a08515) · 17 pinned
engine sites (+ `trade_service` registered at runtime on a patched ROM) (`tools/pin_gen1_site.py`, F-2 tested) · `docs/protocol.md` + `tests/unit/protocol_schema.py`
(pinned to the server) · `docs/gen1_engine_sites.md` · `server/adapters/gen1_codec.py` (oracle) ·
`lua/gen1/{reads,signals,writes,boxes,rom,trade_overlay,client,entry,run}.lua` · adapter rewritten
(species on the wire = INTERNAL index) · `static_encounters.json` · trade patch assembled on master's
toolchain (bank $3F spans; dist `.ups` + patcher md5s regenerated, 76ba1ff) · state.py trade events (`trade_query/offer`,
`trade_mask/offer_ack`) · real R/B fixtures from scripted play (`tools/gen1_fixtures.py`; Yellow
still legacy) · release runner `tools/verify_gen1_release.py` (12 lanes incl. `live-trade-gates`) ·
duo harness on the rewrite (`lua/tests/duo/duo_gen1_main.lua`, `tools/e2e_duo.py` game `gen1_new`,
scenarios `link_new`/`deadzone_new`).

PHYSICAL so far (receipts under `tests/fixtures/gen1/receipts/`, PYDEC receipts `e2e_*_pydec_result.txt`):
inspect gate 6/6, S-1 lab route Red+Blue, panel gates, D-1/D-3/D-8/D-9 (`link_new`/`deadzone_new` with
in-game SAVE + Python readback), T-1 ✓ (menu, SLINK path, CABLE CLUB/CANCEL fall-through; every Center
shares the one home-bank dispatch), T-2, T-3/T-4 (`trade_new`), C-5 (`admit_randomized_new`), S-2/S-8,
**D-6/W-1/W-2 ✓** (`linked_faint_bench_new` + `linked_faint_active_new` PASS with PYDEC: engine faint ->
server -> partner force_faint at the checkpoint / at MainInBattleLoop (`LOOP_HEAD_WRITE` then the
engine's own `BATTLE_FAINT_SITE` and "fainted!" text) -> memorial -> game_over (D-12 ◐)).

Client bugs found by receipts/reviews today (all fixed with falsified tests): writes revoked and queue
dropped during AddPartyMon's AskName window; force_faint dropped in that window; hello at frame 1 /
at the main menu (now: checkpoint or battle; WRAM clear re-hellos); poison faint never read
wWhichPokemon; a SLINK apply emitted party_to_box for the incoming key; every box refusal said
"no box module" (Lua `a and f()` truncation); the initialised-boxes flag lived only in WRAM (memorial
wipe-able by ChangeBox after a reset; now two durable bank-1 bytes); server: a wrong-save hello adopted
party_size/blobs before the identity check (state.py, guard-reviewed). Driver facts: no console.log
per frame; re-pulse native menus; FIGHT-drawn guard; 1800-frame NPC stall + detour; one-ball fixtures
miss ~10-15% (bounded retry incl. nested); a switch spends the turn (lead with the linked mon); the
START menu reopens on the last-used row; memorialize follows force_faint within a frame (FNT unobservable).

## Where it stopped (owner: "Stop after current tasks", 2026-09-14 ~17:00Z)

| Item | State |
|---|---|
| BALLGATE-DUO-1 (Codex, cx-19c2bbe2) | `ball_gate_new` MODEL cut committed (378a386 + 9a8c586, the author's report reconciled); NOT run live. Asserts: the starter gift pair links on arrival with nuzlocke_active=false/ball_count=0 (by design), no propagation from the lab loss, bag_received flips has_pokeballs, SAVE + PYDEC; cold per-run saves, bedroom-checkpoint boot |
| `reconnect_new` (C-2/C-1, committed 1431d08) | first live contact FAILED: "the link changed across the same-save relaunch; A's locked OT ID changed". Hypothesis: `taskkill` does not flush BizHawk's SaveRAM, so the relaunch booted the on-disk save (or a fresh New Game -> new wPlayerID). Diagnose from the kept run dir before changing anything. Wrong-save leg needs a second-OT Red save (`tools/gen1_fixtures.py` plays a fresh New Game -> random wPlayerID; verify it differs from 0x4190, name it red_town_ot2.SaveRAM) |
| duo-pairs lane | link/deadzone/trade/admit PASS as a lane; the faint scenarios PASS individually; a full-lane pass with all scenarios not yet recorded |
| master | `5c2611e` (UI-only files after e2fefa9); the branch is on e2fefa9 — re-rebase before the final FF |

Remaining rows: W-3 explode (variant of the active faint with rules.explode_mode; move menu shows only
EXPLOSION), W-4/D-11 rival swap (needs a rival battle — far; record as limit or drive Route 22), D-4/D-5
clause toggles, D-7 whiteout, D-13/D-14, R-3 trainer-name tilemap, R-4 title-screen live, C-3 dashboard,
S-3 (party full -> box capture), S-6 PC ops by play, T-5 unit. Then Phase 8 (delete old client/gates,
regenerate README/REFERENCE from the ledger, full runner, re-rebase, FF, owner tags).

Receptionist gate: `SLINK_LIVE=1 python -m pytest tests/live/test_gen1_trade_gates.py -q`; never rerun an
unchanged failure — read `patch/build/test_gen1_receptionist_gate_result.txt` first. Next on the lane after
it: paired trade scenario (T-3/T-4) on the duo harness, then a randomized-output admission boot
(UI session's line 3: hello lands "admitted").

## Next steps, in order

1. Read the git log since eb50d45; if BALLGATE-DUO-1 landed, run `python tools/e2e_duo.py --game gen1_new --scenario ball_gate_new` (verify, commit, `outcome` the task, re-dispatch —
   keep both peers busy; the Stop hook blocks the turn otherwise).
2. Run the receptionist gate (T-1/T-2 PHYSICAL); then a paired trade duo scenario (T-3/T-4) on top
   of the duo harness.
3. Remaining D-rows (faint propagation both windows, whiteout, memorial, PC sync, evolution,
   rival swap/explode, game over, reconnect C-2) as duo scenarios; W-rows physical.
4. Phase 8: point `lua/slink_gen1.lua` at `lua/gen1/run.lua`, delete the old client/profile/
   gen1-only `memory_gb.lua` halves and their tests (re-run Gen 2 gates after), regenerate
   README/REFERENCE Gen 1 blocks from the ledger, `ruff`, full `python tools/verify_gen1_release.py`,
   ff to master, owner tags.

## Decisions and limits recorded

- Yellow: fixtures are the old tool's bytes (pinned LEGACY by name in `tools/gen1_fixtures.py` and
  `tests/unit/test_gen1_stat_control.py`); needs a Yellow route or an owner-played save.
- Trade native result 2 ("uncertain append") is held with a HUD warning, never released — no paired
  recovery this release (T-5). Result 1 = nothing changed.
- Three legitimate write windows: overworld checkpoint (`gen1_write_safety`), `MainInBattleLoop+0`,
  the trade lease (`writes:arm("trade_overlay")`).
- Battle fixtures stand on Route 1 (10,35) with ONE ball; town fixtures are in Oak's Lab.
- Boot proof in gates = the CPU checkpoint, never walking (walking triggers encounters).

## Commands

```bash
python tools/verify_gen1_release.py --quick            # fast lanes
python tools/verify_gen1_release.py --lane live-new-gates
SLINK_LIVE=1 python -m pytest tests/live/test_gen1_new_gates.py -q
python tools/gen1_fixtures.py --qualify                 # fixture audit, no emulator
python tools/gen1_fixtures.py red battle                # rebuild a fixture from scripted play
python tools/run_gb_gate.py lua/tests/test_gen1_scripted_gate.lua --rom red_cold --timeout 600
```
