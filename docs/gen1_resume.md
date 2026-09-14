# Gen 1 master release — resume note (2026-09-14, refreshed 14:47Z)

Read this first after a context reset. The ledger `docs/gen1_requirements.md` is the authority on
evidence; this note is the working state around it. Plan (owner-approved):
`C:\Users\howar\.claude\plans\system-reminder-you-are-operating-gleaming-pretzel.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`, branch
  `claude/gen1-master-release-plan-6b4279` = `79d5172` (gen1/rc's adapter sweep, FF, 0 conflicts)
  + `07ba1ca` cherry-pick + ~90 commits of the rewrite. HEAD `02344b3` at the time of writing.
- **master is still `adf3362`.** The UI-migration session (Claude, worktree `dreamy-pike-09f3e3`,
  branch `claude/soul-link-ui-mockups-40f67b`, based on `79d5172`) holds all its merges until master
  contains `79d5172`. The owner has NOT yet said go for `git -C "E:/Google Drive/SLink" merge
  --ff-only 79d5172` (pure FF; touches the shared root checkout). Ask, do it, then message that
  session (`local_2c735b55-b185-4adc-9986-38df0aac44f2`, name "Soul Link UI mockups").
- gen1/rc (`gen1-rby-code-sweep-8d06e2`) stays parked; its RC_MASTER_GUIDE.md checkpoint has a
  `master-release-lane` worker entry that is refreshed at transitions (owner courtesy only).
- Old Gen 1 code is reference-only until Phase 8: `lua/slink_gen1.lua` still launches
  `lua/clients/gen1_rby_client.lua`; the rewrite is launched by `lua/gen1/run.lua` (over
  `lua/gen1/entry.lua`). `tests/unit/test_gen1_adapter.py` is already deleted.

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
panel gates on the trade-carrying build, D-1/D-3 (`link_new`/`deadzone_new` through the real server,
receipts `patch/build/e2e_*_new_*_result.txt`), T-2 + T-1(one Center) — the receptionist gate PASSES on
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
| TRADE-DUO-1 | Codex live `Gen1-SunkCost` (cx-5c08cf80) | `lua/tests/duo/duo_gen1_main.lua`, NEW `lua/tests/gen1_rb_center_inputs.lua` (Center walk factored out of the receptionist gate; gate requires it), `tools/e2e_duo.py` (`trade_new`), `tests/e2e/test_duo_gen1_new.py` | paired SLINK trade scenario (T-3/T-4), MODEL only; its on-disk WIP broke the gate at `:137` (format args) — reported; do not run the trade lane until it reports |
| REVIEW-CLIENT-1 | OMP (cx-887161cd) | none (read-only) | adversarial review of `1a5941f` (pause-not-drop, deferred force_faint, live-game hello) |

Receptionist gate: `SLINK_LIVE=1 python -m pytest tests/live/test_gen1_trade_gates.py -q`; never rerun an
unchanged failure — read `patch/build/test_gen1_receptionist_gate_result.txt` first. Next on the lane after
it: paired trade scenario (T-3/T-4) on the duo harness, then a randomized-output admission boot
(UI session's line 3: hello lands "admitted").

## Next steps, in order

1. Integrate TRADE-DUO-1 / REVIEW-CLIENT-1 reports (verify, commit, `outcome` the task, re-dispatch —
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
