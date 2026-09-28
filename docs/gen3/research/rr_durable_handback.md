# RR-DURABLE handback (2026-09-27)

Worker: RR-DURABLE, for the combined Gen 3 coordinator.
Branch `claude/gen3-rr-durable`, worktree `C:/slink-wt/g3-rrdur`.
Base: integration `4fa041bf`. Final head: `0c444561` (this doc is committed on top of it).

**Goal.** Radical Red native trade becomes available again, under the durable trade contract that FR/LG/E use:
- native scene;
- native save before DONE;
- no raw swap;
- trade journal;
- run_id binding;
- `trade_prepare`;
- server trade recovery.

The named refusal is kept only for an RR build without the witness (the old UPS).

**Status: done.**
- Live PASS on `gen3_rr` for `trade_gen3`, `trade_decline_gen3` and `native_absent_gen3`, all at `source=0c444561`.
- Live companion gates PASS.
- Full `tests/unit` exit 0.

Nothing is pushed and nothing is merged to master.

## Owner-authorized merges

- `e0975691`: the coordinator merged integration `c04420a9` into this branch. The owner said "Just merge what you need".
  - It brought T5 `5eed16cc`: `trade_producer.h`, the durable `native.lua`, and the held-prepare fix.
  - It also brought T2-PUBLISH: the FR/LG/E production companions.
- The owner also authorized further `git merge` of `claude/gen3-integration` into this branch. None was needed after `e0975691`.
- An earlier `git merge --ff-only 646586fd` that I ran myself was denied by the permission classifier. I did not retry it.

## Codex Emerald interface ruling (P1–P4), as implemented

- **P1: ACCEPT, with bounds.**
  - The ABI1 mailbox and tail meanings are unchanged. The separate durable block lives in the proven-free EWRAM tail at `0x0203FE50`. `_Static_assert`s in `patch/src/handlers.c` bound both the producer state/UI and the block end (`RT_BASE + 0x111 <= 0x02040000`).
  - On the durable build, legacy opcodes 16 and 18 are always refused with `REASON_DURABLE_ONLY` (9).
  - Opcode 21 is producer-owned. It needs a READY PREPARE with the same token, epoch and seq. A bare 21 is refused as identity (12). There is no raw fallback.
- **P2: AMEND/ACCEPT.**
  - `COMMIT_ENTERED` is published at scene launch, after the producer's slot and identity recheck. This is the no-return boundary. It is documented as NOT evidence that TradeMons ran, in `handlers.c` `rt_scene_start`, `ADDRESSES.md` and `protocol.md` §6.
  - After that marker, every failure is UNCERTAIN, WITHDRAW is too late (14), and nothing is ever UNCHANGED. No evolution suppression is needed.
  - Success still needs all of: the scene's return, the received PID/OT at the slot, a native post-save OK, and the five bound milestone sequences.
  - The RR save internals are verified on the RR ROM, not inherited from FR (`tests/unit/test_gen3_rr_durable_rom.py`):
    - the hook functions and the save dialog chain are byte-identical to FR;
    - `HandleSavingData` and `HandleWriteSector` are CFRU detours (`0x090B8E09` / `0x090B8CB5`);
    - `UpdateSaveAddresses` points at the CFRU chunk table `0x09148BF0`, which equals the 0xFF0 layout;
    - the RAM words are loaded by the same literal pools.
- **P3: ACCEPT.** `native.lua` has an isolated RR descriptor (`rr_durable`).
  - It is bound only for the production RR companion: title `radical_red`, `production: true`, profile `native.TRADE_BASE`.
  - It never identifies RR as ABI2.
  - Reasons 11 and 12 stay unnamed (legacy RR meanings). Reason 14 is named `withdraw_too_late`.
  - Any other ABI1 world keeps the v1 transport.
- **P4: ACCEPT.**
  - `supports_trade_recovery()` is True for `firered_rr`.
  - The named refusal ("Trade unavailable for Radical Red in this build.") is sent only while either player's hello lacks `trade_prepare`, which means the old UPS.
  - The durable capability is live-validated: `trade_gen3` ran with `trade_prepare` on both clients.
- **RR reload witness.** `lua/gen3/trade_journal.lua` has `RELOAD_LAYOUTS.firered_rr`:
  - chunk 0xFF0, SB2 0xF24, SB1 0x3D68;
  - count and party at SB1+0x34 / +0x38;
  - `gSaveCounter` 0x03005390, ROM-pinned;
  - save-block pointers 0x03005008 / 0x0300500C, from the write checkpoint.

  The existing `verify_reload` validates every selected-slot sector, checksum and counter, plus the trainer and the party bytes.

  Not live-run: the physical reload/recovery path (see "What is left", item 1).

## Commits (this lane, oldest first)

| sha | what |
|---|---|
| `b912c710` | journal RR reload layout (CFRU 0xFF0) + run.lua save-block pointers |
| `f5a165cc` | server: RR opts into trade recovery; named refusal only for undeclared clients; Manager row ok |
| `bd8f7dd2` | companion: `patch/src/rr_trade_relay.h` shadow v2 mailbox running the shared producer; RR engine hooks in `handlers.c` |
| `5a753ddc` | duo trade rows: typed refusal (F1), distinct trade/decline (F2/F3/F5), unavailable chain deleted (F4), save tag fix |
| `e95b9885` | P1: 16/18 refused; P2 docs; ROM facts test |
| `f2eb0802` | profile `TRADE_BASE` + RR `SB2_NAME_OFFSET`; generator fix; protocol §6 |
| `e0975691` | owner-authorized integration merge (coordinator) |
| `d2b8143d` | `native.lua` RR descriptor; `entry.lua` journal support + epoch binding; RR opcode enum 29/30/31 |
| `a974dbb4` | UPS rebuild + companion re-pin; epoch span in the write checkpoint; live gates ported; RR companion `production: true` |
| `e0a6b647` | native_absent_gen3 redesign (apply_prepare; companion pre-save vs clean refusal) |
| `2e4514c8` | trade oracle: the 'Traded' notice is ordered after trade_done only |
| `0c444561` | native_absent: companion half is a saving half (`no_save: ("b",)`) |

## Rebuilt companion

- `patch/dist/SLink-RR.ups` rebuilt from source. `build.py --check` reproduces it.
- Patched md5 `70e7e746e573a2d00df5d3ef41d19d61`, sha1 `da579690db7d6933a0952a1f490312842793f71a`. The previous build was `c372c428…` / `7a386749…`.
- The new pin is in:
  - `engine_signals` (with `production: true`), `write_checkpoint` and the profile citations;
  - the generators' ROM specs, research tools, fixtures and tests;
  - `server/patcher.py`, `patch/README.md` and `docs/gen3_requirements.md`.
- Historical dated probes still name the old pin, on purpose.
- The build needs `SLINK_ARMGCC=E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin`.

## Proven

### Unit

- Full `tests/unit` at `0c444561`: **12731 passed, 4377 skipped, EXIT=0** (568 s).
  - Command: `python -m pytest -q -p no:cacheprovider tests/unit -o tmp_path_retention_policy=failed`, after `source C:/slink-wt/g3-env.sh`.
  - Receipt: `docs/gen3/probes/rr_durable_unit_full_2026-09-27.txt`. Full log: `C:/slink-wt/g3-rrdur-state/unit_full.log`.
- Every change was red first. Several controls were revert-checked, as noted in each commit message.

### Live companion gates (BizHawk, rebuilt ROM)

Receipts are in `docs/gen3/probes/rr_durable_*`.

- **`test_live_tradescene`: PASS, 0 failed.** It runs raw PREPARE 29, then the native "save the game?" dialog, then READY, then SCENE 21, the in-game scene and the native post-save.
  - The witness is COMMITTED: milestones 0x1F, save OK, received PID/OT correct.
  - `gSaveCounter` goes +1 at the pre-save and +1 at the post-save. The party count is unchanged.
  - Cases: vanilla, expanded 1324, and fullname (the unterminated-nickname EWRAM-stomp case).
  - Case bare21: a SCENE without READY is refused as identity 12, with no trade and no save.
- **`test_live_setpartymon` and `test_live_enemyparty_route`: PASS.** Opcodes 18 and 16 ack ST_FAIL with reason 9, and the party, enemy party and counts are untouched.

### Live duo on `gen3_rr`

Run as `python tools/e2e_duo.py --game gen3_rr --scenario <row> --lane rrdur1` with `SLINK_STATE_DIR=C:/slink-wt/g3-rrdur-state`. All three rows ran at `source=0c444561`, clean cut. Receipts are in `docs/gen3/probes/rr_durable_duo_*`; full logs are in `C:/slink-wt/g3-rrdur-state/*_final.log` and `native_absent_gen3_5.log`.

- **`trade_gen3`: PYDEC PASS.**
  - Both sides: apply_prepare, then apply_ready ok, then apply_trade, then trade_done with the partner's key, then the 'Traded' notice, then TRADED.
  - Saved parties are swapped, `links.json` is re-keyed, and the received records are intact.
  - Save witness: saves=3, counter 4→7 on each side (native pre-save, native post-save, runner SAVE).
- **`trade_decline_gen3`: PYDEC PASS.** B declines. There is no apply_prepare or apply_trade, both saves hold their fixture party, and the link is unchanged.
- **`native_absent_gen3`: PYDEC PASS** (redesigned).
  - A (companion) answers apply_ready ok only after its native pre-save: the PREPARE post is a native write after the command, producer phase READY, counter 4→5, and the save witness is byte-checked.
  - B (clean) answers apply_ready ok:false with 0 writes.

## What is left, or not proven here

1. **Physical reload/recovery on RR is not live-run.** That means a reset between the pre-save and the post-save, followed by journal `outstanding` and a reload proof on a real RR battery. The RR layout is unit-proven with a CFRU-chunked synthetic flash plus the ROM facts.

   FR/LG ran their own reload rows. An RR reload row, the analogue of T5's cold-reload leg, would close this.

2. **The first-launch session-counter baton race.** On a fresh worktree, the first duo run had A lose the `slink_gen3_session.baton` birth race. `native trade is off this session` was logged, so the server correctly refused A by name. The second run was fine.

   This is the integration `646586fd` 5-second wait. A client that starts more than 5 s after its partner's birth can still lose on a first-ever run. This is a pre-existing integration behaviour, not something RR changed.

3. **`patch/src/trade_targets/radical_red.h` (the T2 target header) still says `READY 0`.** RR does not use the ABI2 target path; its durable build is the ABI1 + descriptor path described here. Nothing reads that header for RR.

4. **Server change and Gen 2.** `server/*.py` changed (in `f5a165cc`), so the Gen 2 CODE_DIGEST is stale. Ping Gen 2 before landing.

5. **Other RR live rows were not re-run on the rebuilt UPS.** Every RR row outside these three and the three gates (link, release, faint, clause rows and so on) still has receipts from the old companion sha. Those rows now also run with `supports_trade_recovery` True for RR, which defers the hello census and honours `party_hidden`.

   The unit suite covers the logic. A final-cut RR sweep on `0c444561`+ is still owed.

6. **Earlier handoff sha `bd8f7dd2`.** On its own it did not build, because it needed the T5 headers. It is fixed by the `e0975691` merge; the branch head builds and tests green.

## Pointers

- Producer relay: `patch/src/rr_trade_relay.h`.
- RR hooks: `patch/src/handlers.c`, the "RR-DURABLE" block and `drive_ui` kind 3.
- Map and opcodes: `patch/src/ADDRESSES.md` (EWRAM map + opcode rows 16/18/21/29/30/31, reason 9).
- Lua descriptor: `lua/gen3/native.lua` (`rr_durable`); entry binding in `lua/gen3/entry.lua` (`trade_journal_supported`, `rr_native`).
- Journal layout: `lua/gen3/trade_journal.lua` `RELOAD_LAYOUTS.firered_rr`.
- Server: `server/adapters/gen3_frlge.py` (`supports_trade_recovery`, `trade_unavailable_reason`), `server/state.py` `_handle_trade_request`.
- Duo:
  - `lua/tests/duo/scenario_gen3_trade.lua`, `lua/tests/duo/scenario_gen3_native_absent.lua`;
  - `tools/e2e_duo.py`: `gen3_trade_chain`, `orchestrate_trade_gen3`, `_gen3_trade_facts`, `orchestrate_native_absent_gen3`, `assert_native_absent_gen3_saved`.
- Tests:
  - `tests/unit/test_gen3_native_rr_trade.py`, `test_patch_rr_trade_relay.py`, `test_gen3_rr_durable_rom.py`;
  - `test_gen3_rr_trade_unavailable.py`, `test_gen3_entry_trade.py`, `test_e2e_duo_gen3_trade_panel.py`.
