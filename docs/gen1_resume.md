# Gen 1 master release — resume note (2026-09-14, refreshed 16:20Z)

Read this first after a context reset. The ledger `docs/gen1_requirements.md` is the authority on
evidence; this note is the working state around it. Plan (owner-approved):
`C:\Users\howar\.claude\plans\system-reminder-you-are-operating-gleaming-pretzel.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`, branch
  `claude/gen1-master-release-plan-6b4279` = **master `e2fefa9`** (the merged UI-migration branch; master
  was FF'd to `79d5172` by the owner, then the UI session merged) **+ ~65 rewrite commits**, rebased
  2026-09-14 (pre-rebase tip tagged `pre-rebase-gen1-release-912a7df`). HEAD `2979c97` at the time of writing.
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

PHYSICAL so far (receipts under `tests/fixtures/gen1/receipts/`, PYDEC receipts `patch/build/e2e_*_pydec_result.txt`):
inspect gate 6/6, S-1 lab route Red+Blue, panel gates, D-1/D-3/D-8/D-9 (`link_new`/`deadzone_new` with
in-game SAVE + Python readback of the flushed cartridges), T-1(one Center)/T-2 (receptionist gate),
T-3/T-4 (`trade_new`, twice), C-5 (`admit_randomized_new`: randomized Red admitted, clean Blue rejected),
S-2/S-8 (server-side), and — from the first `linked_faint_bench_new` run — the whole D-6 bench window:
A's ENGINE faint -> server -> B `force_faint` at the checkpoint (`BENCH_HP_STATUS 0000 00`) -> memorial
-> links.json `memorial`/cause `battle` -> `game_over` (D-12). Its only failure was the FNT tilemap probe:
the server queues memorialize with force_faint and the client drains one command per checkpoint frame,
so no normal-input driver can open the party menu in between (probe made best-effort; PYDEC of Box 12
is the oracle). The active window (`linked_faint_active_new`) failed by design on first contact: a switch
costs the turn and the wild foe's free hit kills a 4-HP linked mon before the partner's faint arrives —
fix in flight: B makes its linked mon the LEAD via the overworld party menu before the battle.

Client bugs found by receipts/reviews today (all fixed with falsified tests): writes revoked and queue
dropped during AddPartyMon's AskName window; force_faint dropped in that window; hello at frame 1 /
at the main menu (now: checkpoint or battle; WRAM clear re-hellos); poison faint never read
wWhichPokemon; a SLINK apply emitted party_to_box for the incoming key; every box refusal said
"no box module" (Lua `a and f()` truncation); the initialised-boxes flag lived only in WRAM (memorial
wipe-able by ChangeBox after a reset). Driver facts: no console.log per frame; re-pulse native menus;
FIGHT-drawn guard; 1800-frame NPC stall + detour; one-ball fixtures miss ~10-15% (bounded retry).

## In flight (peers; coordinator integrates and commits, peers never commit)

| Card | Worker | Files | State |
|---|---|---|---|
| FAINT-DUO-2 | Codex live `Gen1-SunkCost` (cx-5942b396) | `lua/tests/duo/duo_gen1_main.lua`, `lua/tests/gen1_rb_hunt_inputs.lua`, `tools/e2e_duo.py`, `tests/unit/test_e2e_duo_admission.py` | active window: B leads with its linked mon (party-menu SWITCH) so no free hit; FNT probe best-effort; GAME_OVER milestone; `could not hold` = FINAL |
| REVIEW-BOXES-1 | OMP (cx-a254a0c8) | none (read-only) | adversarial review of the durable initialised flag (36b3772): checksum domain, offsets, write ordering, mid-SAVE race, Yellow |

Lane order after FAINT-DUO-2 lands: `linked_faint_bench_new`, `linked_faint_active_new`, then the full
`duo-pairs` lane. Then: C-1/C-2 reconnect scenario, T-1 all Centers (or record one-Center limit),
W-3/W-4/D-11 (explode/rival swap), D-2 ball gate by play, S-3..S-7, R-3, C-3 dashboard.

Receptionist gate: `SLINK_LIVE=1 python -m pytest tests/live/test_gen1_trade_gates.py -q`; never rerun an
unchanged failure — read `patch/build/test_gen1_receptionist_gate_result.txt` first. Next on the lane after
it: paired trade scenario (T-3/T-4) on the duo harness, then a randomized-output admission boot
(UI session's line 3: hello lands "admitted").

## Next steps, in order

1. Integrate FAINT-DUO-2 / REVIEW-BOXES-1 reports (verify, commit, `outcome` the task, re-dispatch —
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
