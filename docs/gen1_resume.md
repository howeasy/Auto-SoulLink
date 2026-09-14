# Gen 1 master release — resume note (2026-09-14, refreshed 15:00Z)

Read this first after a context reset. The ledger `docs/gen1_requirements.md` is the authority on
evidence; this note is the working state around it. Plan (owner-approved):
`C:\Users\howar\.claude\plans\system-reminder-you-are-operating-gleaming-pretzel.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`, branch
  `claude/gen1-master-release-plan-6b4279` = **master `e2fefa9`** (the merged UI-migration branch; master
  was FF'd to `79d5172` by the owner, then the UI session merged) **+ 47 rewrite commits**, rebased
  2026-09-14 (pre-rebase tip tagged `pre-rebase-gen1-release-912a7df`). HEAD `b7f9668` at the time of writing.
- The UI-migration session is done and waits for the "admitted" hello receipt (randomized cartridge);
  message it via `mcp__ccd_session_mgmt__send_message` to `local_2c735b55-b185-4adc-9986-38df0aac44f2`.
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

PHYSICAL so far: inspect gate 6/6 (`tests/live/test_gen1_new_gates.py`), S-1 lab route Red+Blue,
panel gates on the trade-carrying build, D-1/D-3 (`link_new`/`deadzone_new` through the real server),
T-3/T-4 (`trade_new` PASS first run: native prompt, apply, swapped halves in links.json + both SaveRAMs),
T-2 + T-1(one Center) — the receptionist gate PASSES on
Red and Blue (`3650ace`; 8 s per cartridge once per-frame console.log was silenced; drivers must
re-pulse A on the 16-frame cadence for native menus and gate the RUN menu on the drawn FIGHT row).
Everything else is SOURCE/MODEL — the ledger says which.

Client facts learned from the duo receipts (fixed in 1a5941f): after every capture the party is
unreadable for the AskName window (add_mon.asm bumps count + list before the struct) — the writes
gate now pauses and keeps its queue instead of revoking and dropping; `force_faint` during that
window is deferred; hello waits for a live game (home/init.asm clears WRAM until MainMenu reloads
the save).

## In flight (peers; coordinator integrates and commits, peers never commit)

| Card | Worker | Files | State |
|---|---|---|---|
| ADMIT-LIVE-1 | Codex live `Gen1-SunkCost` (cx-afc8ce97) | `tools/e2e_duo.py` (`admit_randomized_new`), `lua/tests/duo/duo_gen1_main.lua` (passive hello scenario), `tests/e2e/test_duo_gen1_new.py`, NEW `tests/unit/test_e2e_duo_admission.py` | randomized Red (unpatched UPR output) admitted + clean Blue rejected against a real prepare_pair contract; MODEL only, coordinator runs it (UPR ≤600 s per call) |
| REVIEW-CLIENT-1 | OMP (cx-887161cd) | none (read-only) | adversarial review of `1a5941f` (pause-not-drop, deferred force_faint, live-game hello) |
| live-new-gates | coordinator (lane) | — | re-running the inspect + S-1 lanes on the rebased tree |

Receptionist gate: `SLINK_LIVE=1 python -m pytest tests/live/test_gen1_trade_gates.py -q`; never rerun an
unchanged failure — read `patch/build/test_gen1_receptionist_gate_result.txt` first. Next on the lane after
it: paired trade scenario (T-3/T-4) on the duo harness, then a randomized-output admission boot
(UI session's line 3: hello lands "admitted").

## Next steps, in order

1. Integrate ADMIT-LIVE-1 / REVIEW-CLIENT-1 reports (verify, commit, `outcome` the task, re-dispatch —
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
