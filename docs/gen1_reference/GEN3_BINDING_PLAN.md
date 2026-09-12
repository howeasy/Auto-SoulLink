# Gen 3 binding plan: porting Radical Red onto the shared framework

Tree: sweep worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, HEAD `79d5172`,
read 2026-09-11; line numbers are the working tree's, untracked files included. Companion to
`docs/FRAMEWORK.md` (one row per shared module, with its Gen 1 and Gen 3 bindings) and to
`GEN3_STANDARD_COMPARISON.md` (the 19-row behaviour comparison, not repeated here).

Scope statement. This is the ordered plan for the work that happens after the Gen 1 RC: binding the Gen 3
Radical Red client and adapter to the shared modules Gen 1 built, so that "one runtime, one rule engine,
one adapter per generation" is true for the generation that defines the gameplay standard. Nothing in this
document is Gen 1 release work. The Gen 1 manifest `tests/gen1_release_requirements.json` (388 rows,
verified by `tools/verify_gen1_release.py`) is untouched by this plan, and no row of it is closed, opened or
re-scoped here. The only Gen 3 change proposed for the RC window is P1 (`proposals/P1-gen3-trade-gate.md`),
already in the proposal series, because it repairs the standard itself.

## 1. Starting point: what Gen 3 has today

- One monolithic client, `lua/clients/gen3_frlge_client.lua`, 4,526 lines (`wc -l`), at Lua's 200-local
  limit (its own comment at `:108`: "the main chunk is at Lua's 200-local limit"). It loads `memory_gba`
  (`:99`), `connector` (`:100`), `hud` (`:101`), the companion-patch `mailbox` by `pcall` (`:103`), the
  engine peer ghost `peer_ghost_npc` (`:144-150`) and `game_detect` (`:161`). It has its own JSON encoder
  (`:204-239`) and command-array parser (`:241-358`); it binds none of `json_codec`, `wire_protocol`,
  `client_session`, `client_journal`, `command_executor` or `durable_runtime` (`docs/FRAMEWORK.md`,
  "Protocol and delivery", "Runtime").
- One adapter, `server/adapters/gen3_frlge.py`, 626 lines: `Gen3Adapter(GameAdapter)` at `:259`,
  `is_rr` at `:267`, fixed-species gifts at `:48-52` (Magikarp, Eevee, Lapras; starters excluded on purpose,
  comment `:45-47`), RR rival classes at `:103`, `rival_trainer_ids` `:314`, `party_blob_size` `:340`,
  `supports_explode_mode` `:345`, `memorial_box_index` `:584-587` (24 on RR, 13 on vanilla FRLG). It does
  not override `rom_content_fingerprint`, so admission gets the base `None` (`server/adapters/base.py:360-372`,
  `server/server.py:1787`) and `_decide_admission` (`server/server.py:1763-1770`) admits any ROM.
- The rule engine is used directly. `SLinkServer` loads a live `SoulLinkState` (`server/server.py:1551`) and
  every legacy event goes through `_dispatch` (`:2998`) into `handle_event` (`:3062`). This path and the Gen 1
  durable runtime are mutually exclusive (`:2999-3000`). Persistence is `links.json` and `memorial.json`
  (`server/state.py:3081-3104`, `:3187`); `to_document` (`:3107-3190`) carries `pending_memorials` (`:3158`)
  but not `queued_commands`, so a server restart drops every queued command except memorials.
- Free-running observation. The client registers `event.onframeend(on_frame_safe, "t4_events")` (`:4525`) and
  never pauses; it emits a `tick` heartbeat every `TICK_INTERVAL` frames (`:4126-4133`), HELLO on every
  (re)connect (`:1916-1945`), and the semantic events the engine consumes: `capture` (`:3588`, box `:3969`),
  `faint` (`:3682`), `whiteout` (`:3813`), `no_catch` (`:4102`), `trainer_battle_start` (`:2337`),
  `party_to_box` and `box_to_party` from buffered diffs (`:3696-3726`, flushed `:3818-3879`). Frames queued
  while connected replay after a reconnect (`lua/connector.lua:364-376`, no `discard_on_disconnect`), but an
  event emitted while disconnected is dropped (`gen3_frlge_client.lua:1048-1051`).
- Deferred faint for the active slot. `force_faint` and `force_explode` share one branch (`:728-800`): a
  benched or out-of-battle target is written immediately with `M.forceFaint(slot)` (`:790-798`,
  `lua/memory_gba.lua:1275`); the active battler is deferred to switch-out or battle end
  (`pending_battle_faints`, `:781-789`) and flushed at `:2543-2582`. `force_explode` coerces Explosion by
  re-writing the chosen action every frame until PP drops (`:2344-2403`) and settles or falls back after
  `EXPLOSION_FALLBACK_FRAMES` (`:2404-2425`). Writes are gated by `writes_enabled` (`:1862`) and, for the
  sync queue, by `safe_now` (`:2609-2610`); there is no permit, no pre/post image and no server verification.
- Native trade. Server-side machine inside the engine, `server/state.py:482-760` (`_handle_trade_request`
  :536, `_handle_mon_chosen` :557, `_handle_menu_result` :614, `_execute_trade` :656, `_handle_trade_done`
  :691, `_commit_trade` :715); client apply at `:947` and the `pending_trade_apply` phases at `:2214-2296`.
  Regression since `134f007`: the staging step sits inside the `not patch_present()` branch (`:2222-2238`),
  so on a patched ROM phase `pending` can only time out at `:2239-2240`. P1 restores the gate; it must land
  before step (e) below.
- Companion patch and peer ghost. `patch/tools/build.py` (C toolchain, seven-step pipeline, docstring `:1-16`)
  produces `patch/dist/SLink-RR.ups`; base md5 `8529f3a45d32bce4da637976fcf269d4`, patched
  `8dcffce7659be02474dfa0f876639f8a` (`patch/README.md`). The mailbox ABI v1 lives at EWRAM `0x0203F800`
  (`lua/mailbox.lua:13-19`) with opcodes at `:29-311`; the peer ghost is a real engine object-event
  (`lua/peer_ghost_npc.lua:1-19`, `gObjectEvents` at `:25`), and talking to it or to the Center NPC is the
  trade entry (`gen3_frlge_client.lua:2165-2190`). The RR facts the port must not re-derive are in
  `CODEX_HANDOFF_2026-09-10.md` section 4 and `patch/src/ADDRESSES.md`.
- Hold evidence for mGBA already exists: `lua/platform_execution.lua` pins the `mgba` profile (`:4`) and
  `docs/rr_reference/SHARED_PROFILE_HOLD.md` records runs 34 to 36 on RR bytes (unpaused, paused, deliberate
  flag clear). Nothing in the client selects it today.
- Existing evidence gates. Unit: `tests/unit/test_gen3_adapter.py` (216 tests), `test_gen3_adapter_rival_ids.py`
  (8), `test_state.py` (318, the rule oracle), `test_explode_mode_gate.py` (11), `test_state_rival_battle_start.py`
  (15), `test_memorialize_ack.py` (4), `test_link_panel.py` (16), `test_trainer_panel.py` (14),
  `test_staged_state_cross_gen.py` (2), `test_protocol_cross_gen.py` (2), `test_party_blob_size.py` (6),
  `test_client_invariants.py` and `test_client_upvalue_scope.py` (every `lua/clients/*_client.lua`),
  `test_e2e_duo_scenario_selection.py` (8), `test_patcher_routes.py` (6). Live: `tests/live/test_lua_gates.py`
  runs the 39 `lua/tests/test_live_*.lua` and 3 `test_mailbox_*.lua` gates against `patch/build/slink_RR.gba`.
  End to end: `tests/e2e/test_duo.py:45-49` parametrizes `scenarios_for("gen3_rr")` from `tools/e2e_duo.py`
  (`faint`, `boxsync`, `trade`, `ghost`, `infopanel`, `explode`; `lua/tests/duo/scenario_*.lua`), and the
  harness `dofile`s the production client (`lua/tests/duo/duo_main.lua:102`).

## 2. Binding steps

Order is by dependency first, payoff second. Step 0 is the precondition. Each step names the shared modules
bound, what Gen 3 code is replaced or wrapped, what stays in the adapter, the gate that must keep passing,
an effort class (S under a day of focused work, M a few days, L a week or more) and the risk.

### Step 0a (added 2026-09-11). Reconcile the shared spine with gen1/rc

The in-flight shared worktree (`.claude/worktrees/shared-framework`, branch `claude/shared-framework` at
`codex/shared-operation-binding-v1` 9433c80) and `gen1/rc` change 131 of the same paths versus master; 109 are
byte-identical and these 22 diverge. Reconciling them is the first task of the binding work, before any step
below, and nothing here is Gen 1 release work:

- `.gitattributes`
- `docs/gen1_reference/GAMBATTE_EXECUTION_HOLD.md`
- `docs/platform-execution-contract.md`
- `docs/rr_reference/SHARED_PROFILE_HOLD.md`
- `lua/clients/gen3_frlge_client.lua`
- `lua/platform_clock.lua`
- `lua/platform_saveram.lua`
- `requirements-dev.txt`
- `server/durable_runtime.py`
- `server/linked_death_rules.py`
- `server/manager.py`
- `server/protocol_journal.py`
- `server/server.py`
- `server/state.py`
- `server/status_payload.py`
- `tests/unit/test_client_state_store.py`
- `tests/unit/test_http_server_security.py`
- `tests/unit/test_linked_death_rules.py`
- `tests/unit/test_manager_http_hardening.py`
- `tests/unit/test_protocol_records.py`
- `tests/unit/test_runtime_operation_binding.py`
- `tools/emulator_sandbox.py`

### Step 0. P1: restore the trade staging gate

Apply `proposals/P1-gen3-trade-gate.patch` (one inserted `elseif` at `gen3_frlge_client.lua:2221-2241`).
Gate: `lua/tests/test_live_tradescene.lua` through `tests/live/test_lua_gates.py`, duo `trade`. Effort S.
Risk: none beyond restoring pre-`134f007` behaviour (P1 note). Without it step (e) would be verifying a
fallback path.

### Step (a). Durable runtime, journal, run ownership

- Bound: `server/durable_runtime.py` (`DurableRuntime`), `server/durable_dispatch.py`, `server/protocol_journal.py`,
  `server/staged_state.py` (a `StagedGen3State` subclass with one `validate_game_state` override, the shape of
  `server/gen1_staged_state.py:6-10`), `server/protocol.py` `SessionGate` (`:83`) with a Gen 3 HELLO validator,
  `server/runtime_lease.py`, `server/journal_reader.py`; client `lua/durable_runtime.lua`, `lua/client_session.lua`,
  `lua/client_journal.lua`, `lua/state_store.lua`, `lua/platform_storage.lua`, `lua/platform_identity.lua`,
  `lua/json_codec.lua`, `lua/wire_protocol.lua`, `lua/journal_document.lua`, `lua/command_service_router.lua`.
- Replaced: for a Gen 3 run, the legacy loop `server/server.py:2522-2719` and `_dispatch :2998-3062`, `links.json`
  persistence (`server/state.py:3081-3104`, `:3187`) and `server/backup.py`; client `json_encode :204-239`,
  `parse_command_list :241-358`, `send :1047-1060`, the reconnect and HELLO block `:1916-1945`, and the
  if/elseif dispatcher `:698-1042` (each command becomes a routed service). `Gen1Runtime._dispatch_semantic`
  (`server/gen1_runtime.py:274-346`) is the template for the Gen 3 override.
- Stays in the adapter: HELLO metadata (rom type from `lua/games/gen3_frlge.lua:437`, party snapshot
  `gen3_frlge_client.lua:1186`, badges, trainer name), `lua/memory_gba.lua`, `lua/mailbox.lua`,
  `lua/peer_ghost_npc.lua`, the transient `ghost_pos` path (the runtime contract already reserves transients;
  `server/state.py:413`).
- Gate: `tests/unit/test_state.py`, `test_gen3_adapter.py`, `test_staged_state_cross_gen.py`,
  `test_protocol_cross_gen.py`, `test_client_invariants.py`, `test_client_upvalue_scope.py`,
  `test_e2e_duo_scenario_selection.py`; duo `faint` and `boxsync`; the 42 live gates. New: a Gen 3 sibling of
  the 38 durable-server cases the contract cites for Gen 1 (`shared-durable-server-contract.md`, "Qualification").
- Effort: L. Risk: the 200-local limit (`:108`) means the port is a split of the client into modules, not an
  edit; the duo harness `dofile`s the client (`lua/tests/duo/duo_main.lua:102`) and would hang on a blocking
  `run()` loop (P4 note, section 1, last row), so the Gen 3 durable entry must stay on `event.onframeend`
  or the harness must get a launcher mode. Payoff: comparison row 16 (restart loses queued commands) closes.

### Step (f1). Hash admission (the small half of step f, pulled forward)

- Bound: `SessionGate.admit` (`server/protocol.py:115`) with a Gen 3 profile catalog in the shape of
  `server/gen1_cartridge_profiles.py`; `Gen3Adapter.rom_content_fingerprint` implemented instead of the base
  `None`.
- Replaced: header-plus-pointer identity (`lua/games/gen3_frlge.lua:416-437`) as the only check;
  `_decide_admission` (`server/server.py:1763-1770`) admitting a run with no contract.
- Stays: the RR base and patched md5s (`patch/README.md`), the `SLNK` beacon detection (`lua/mailbox.lua:13-14`).
- Gate: `test_gen3_adapter.py`, `lua/tests/test_rr_discovery.lua`, `test_rr_validate.lua`, `test_mailbox_absent.lua`
  (negative control on the clean ROM, `tests/live/test_lua_gates.py:50`).
- Effort: S. Risk: unverified whether canonical hashes exist for vanilla FRLG and AP builds (none found under
  `data/games/gen3_frlge/`); RR is covered. Payoff: comparison row 18.

### Step (b). Observation loop and observation checkpoints

- Bound: the free-run loop of P4/P10 once generalized (`lua/gen1_observation_loop.lua:48-83` is already
  generation-free except its name; `server/gen1_observation_runtime.py` order "inventory, signals, receipts"
  `:14-20`), `lua/observation_stream.lua`, `server/keyed_inventory.py`, `server/source_receipts.py`,
  `server/identity_registry.py`, `server/party_observation_cache.py`.
- Replaced or wrapped: the per-frame party read and diff `gen3_frlge_client.lua:2994-3564`, the box scanner
  `:1316-1468`, the emitters `:3565-4109`, and the `tick` snapshot `:4125-4372` become the heartbeat
  inventory of one `observation` event; the semantic events keep their shape because they are already the
  engine's (`server/gen1_semantic_events.py:5-10` lists the field names).
- Stays: decryption and `monKey` (`lua/memory_gba.lua:635`), the borrowed-party PID detector `:3003-3141`,
  party freeze `:3142`, the RR Nature Changer rekey `:3397-3560`, EvRing fast paths `:1876-1911`,
  `hasPokeballs` (`:4112`, `memory_gba.lua:1121`), the post-battle grace window `:3880-4109`.
- Gate: duo `faint`, `boxsync`; `lua/tests/test_live_partyevents.lua`, `test_live_boxsync.lua`,
  `test_live_events.lua`; `test_state.py` unchanged.
- Effort: M. Risk: sequence contiguity across a reconnect is open on the Gen 1 side too (P10 note, section 6,
  "Reconnect"); heartbeat cost (P4 measured 28 ms per full inventory on Game Boy; the GBA party is already
  decrypted per frame, the box scan is incremental `:1409`).

### Step (d). Held executors for box and party moves and memorials

- Bound: `server/held_write_permit.py` and `lua/held_write_permit.lua`, `lua/command_executor.lua`
  (prepare, classify, apply, receipt; `armed`/`PENDING` for asynchronous mailbox opcodes, which
  `shared-executor-native-contract.md` was written for), `lua/staged_command.lua` for multi-opcode sequences,
  `server/operation_scope.py`, `server/save_file_receipt.py` (only if step (e)'s SaveRAM question is answered
  yes), `lua/control_service.lua` and `lua/platform_execution.lua` (`mgba` profile) for the momentary hold
  around a write, `lua/platform_clock.lua`.
- Wrapped: `exec_box_mon :1601`, `exec_party_mon :1670`, `exec_memorialize :1781` (native `OP_MEMORIALIZE`
  `:1800-1821`, Lua fallback `:1823-1831`), `memorialize_finish :1752`, `memorialize_failed :1829`, the flush
  `:2633-2716`. Each becomes an executor adapter with a prepared intent and a readback receipt; the server
  verifier follows `server/gen1_held_faint.py:70-75` with the GBA party layout.
- Stays: the safe-state predicate `safe_now` (`:2609-2610`, with `isPostBattleSettled` and the end-of-battle
  cooldown `:2591-2595`), `memorial_box_index` (`server/adapters/gen3_frlge.py:584-587`), `findFreeMemorialSlot`
  (`lua/memory_gba.lua:1843`), overflow-box renaming `:1775`, the last-mon refusal `:1603-1607`.
- Gate: duo `boxsync`; `lua/tests/test_live_boxsync.lua`, `test_live_memorialize.lua`, `test_live_setpartymon.lua`,
  `test_live_givemon.lua`; `tests/unit/test_memorialize_ack.py`.
- Effort: M. Risk: blocking `memorialize_failed` (handoff decision, "Adopt") changes `server/state.py:2847-2872`
  for every generation and needs a repair flow the Gen 3 client does not have; the Gen 1 `_handle_memorialize_failed`
  change is item 2 of the handoff and lands first.

### Step (c). In-battle instruction authority for force_faint and force_explode

Comparison of the two behaviours (`SCOPE_CONTROL_PROPOSAL.md` section 2 has the four-column table):

| Situation | Gen 3 today (`gen3_frlge_client.lua`) | Gen 1 instruction authority (`server/battle_force_authority.py`, `lua/battle_force_authority.lua`) |
| --- | --- | --- |
| Out of battle | immediate party write, `:790-798` | overworld held permit, not this mechanism (`lua/gen1_held_faint.lua:38-40`) |
| In battle, target benched | immediate party write, `:790-798` | party HP and status written at the next pinned site (`decide` `:128`, benched writes `:122`); the engine refuses to send the mon out |
| In battle, target is the active battler | deferred to switch-out or battle end, `:781-789`, flushed `:2543-2582` | `wBattleMonHP` zeroed at `ExecutePlayerMove+0` (`active_writes` `:114`); the engine prints the faint that turn |
| Explode Mode | per-frame coercion of the chosen action until PP drops, `:2344-2403`, fallback `:2404-2425` | P11: moveset and PP rewritten at the loop head, selected move at `ExecutePlayerMove` (live PASSED on R/B/Y) |
| Evidence | `force_fainted_keys` (`:795`) in client memory | 18-field snapshot, exact byte footprint, server `verify_window` (`server/instruction_authority.py:141`) |

What the shared layer should expose, and why. The mechanism, not the timing: `server/instruction_authority.py`
(issue, window of at most 64 frames `:30`, verify) and `lua/instruction_executor.lua` (arm one frame, hook at a
pinned site, write the decided footprint, read back) are generation-free; the decision function is the
adapter's (`battle_force_authority.decide` for R/B/Y). The owner has fixed Gen 3 as the standard, so the Gen 3
adapter's `decide` keeps the Gen 3 rule: benched target written now, active battler deferred until switch-out
or battle end. The Gen 1 adapter keeps its stronger rule (the active mon faints in-engine that turn), which
`SCOPE_CONTROL_PROPOSAL.md` section 2 records as exceeding the standard, and which the manifest row
`runtime.battle-write-slot-bounds` asks for. Both are selections of the same executor; neither becomes a
shared rule. What Gen 3 gains from binding is not a timing change but evidence: a prepared intent, the pre
and post bytes of the bench write and of the deferred flush, and server-side verification, replacing a
client-side boolean.

- Bound: `server/instruction_authority.py`, `lua/instruction_executor.lua`; a new Gen 3 sibling of
  `battle_force_authority` (snapshot of `gBattleMons`, `gBattlerPartyIndexes` at `:2549-2553`, the `decide`
  above); `server/state.py:2700-2703` already selects `force_explode` when the adapter opts in.
- Wrapped: `:728-800` and `:2543-2582` (faint), `:2344-2427` (Explode) become the executor's `apply` and the
  deferred flush its second window.
- Stays: the CFRU debounce facts (`:572-580`), the Explosion coercion writes (`:2384-2401`, RR battle-struct
  offsets), the fallback constant, `M.forceFaint` and `M.forceExplodeBattler` (`lua/memory_gba.lua:1275,1303`).
- Gate: `tests/unit/test_explode_mode_gate.py`, `test_state.py` faint cases, duo `faint` and `explode`,
  `lua/tests/test_live_forcemove.lua`, `test_live_explode_route.lua` (server-driven, listed `NOT_STANDALONE` at
  `tests/live/test_lua_gates.py:47-48`).
- Effort: M for the bench write with receipts, L if a one-instruction site is pinned on GBA. Risk: CFRU
  processes damage in multi-step sequences within one frame (`:572-575`), so a single pinned instruction is
  harder to choose than on Game Boy; keep the frame-window form (up to 64 frames) and the Lua fallback. Unverified:
  whether mGBA bus-exec hooks fire with offset 0 like Gambatte (`EXECUTION_MODEL_PROPOSAL.md` section 6 measured
  Gambatte only).

### Step (e). Trade coordinator

- Bound: `server/trade_coordinator.py` (phases `offered` to `link_committed`, atomic paired-trade records),
  `server/trade_driver.py`, `lua/staged_command.lua` for the client phases, `lua/platform_saveram.lua` if the
  SaveRAM question is answered yes.
- Replaced: the in-engine machine `server/state.py:482-760` and `_tick_pending_trade :514`; client `apply_trade`
  `:947`, `emit_trade_done :657`, `relocate_trade_slot :678`, `pending_trade_apply :2214-2296`.
- Stays: the entry points (peer ghost `:2165-2171`, Center NPC `:2178-2190`), the native menus and scene
  (`lua/mailbox.lua:145` `show_menu`, `:183` `choose_party_mon`, `:193` `trade_scene`, `:44`
  `OP_SET_ENEMY_PARTY` staging), the field-clear gate `sScriptContext2Enabled` (`0x03000F9C`,
  `gen3_frlge_client.lua:128-135`), `party_blob_size` 100 (`server/adapters/gen3_frlge.py:340`).
- Gate: `lua/tests/test_live_tradescene.lua`, `test_live_choosepartymon.lua`, `test_live_menu.lua`,
  `test_live_pcnpc.lua`, `test_live_peerinteract.lua`; duo `trade`; shared `tests/unit/test_trade_coordinator.py`,
  `test_trade_driver.py`, `test_trade_runtime_composition.py` unchanged.
- Effort: L. Risk: the coordinator's `verified` callback requires save durability (`shared-trade-coordinator-contract.md`,
  callback table), and `shared-saveram-contract.md` says mGBA save media is not qualified. Either qualify
  `platform_saveram` on mGBA or define the Gen 3 `TradeVerification` without a save receipt (owner decision,
  section 4).

### Step (g). Launcher and UI facts

- Bound: `server/runtime_launcher.py` (`file_bundle`, `render_launcher`) with a Gen 3 file closure in the shape of
  `server/gen1_launcher.py:8-41`, `server/bizhawk_launch.py` with `profile='mgba'` (today only the Gen 1 route at
  `server/server.py:6482-6485` builds a bundle, with `profile='gambatte'`), `server/runtime_boundary.py` journal
  source (`:65-69`) for Gen 3 runs, Manager run creation with a lease and a journal in the shape of
  `server/gen1_run_config.py:97-135`.
- Replaced: `lua/slink_gen3.lua:12-18` and the legacy branch of `lua/slink.lua:82-96` for managed runs (kept for
  unmanaged use); `POST /api/runs/new` (`server/manager.py:1097`) grows the journal path.
- Stays: `lua/games/gen3_frlge.lua` detection, the `data/games/gen3_frlge/` data files.
- Gate: `tests/unit/test_routes_smoke.py`, `test_runtime_boundary.py`, `test_first_run.py`,
  `test_manager_option_labels.py`, `test_http_server_security.py`; the shared launcher tests named in
  `shared-launcher-reader-contract.md` ("Thirteen portable shared tests"; file names unverified).
- Effort: S. Risk: fingerprint refusal on a mismatched file is the feature; `tools/e2e_duo.py` writes its own stubs
  (docstring `:12-14`) and needs a launcher mode or an explicit exemption.

### Step (f2). Patch composition, ROM change accounting, UPR

- Bound: `server/rom_change_audit.py` to account every changed byte of `patch/dist/SLink-RR.ups` against the base
  ROM (today `patch/tools/build.py` verifies by disassembly, step 7 of its docstring); `server/patch_plan.py` for
  the two injection spans (handlers at `CODE_BASE`, the 4-byte `bl` over the CallCallbacks sled, steps 5 and 6).
- Replaced: direct byte injection in `build.py`; nothing in the client.
- Stays: `patch/src/handlers.c`, `patch/src/slink.ld`, `patch/src/ADDRESSES.md`, the ARM toolchain, the bundled
  battle calc (`patch/src/rr41_battle_calc.ups`).
- UPR: there is no Gen 3 randomizer path; `server/upr_pipeline.py` is Gen 1 in body (`:38,249` import
  `server/adapters/gen1_rom_scan`) behind a generic name and the Manager route `server/manager.py:874`. Not part
  of the port unless vanilla FRLG randomization is wanted; if it is, `upr_catalog`, `upr_runner`, `upr_settings`
  are generation-free and `upr_pipeline` needs a Gen 3 content check.
- Gate: `patch/tools/build.py --check`, `tests/unit/test_rom_change_audit.py`, `test_patcher_routes.py`,
  `lua/tests/test_mailbox_ping.lua`.
- Effort: S for the audit, M to move `build.py` onto `patch_plan`. Risk: `build.py` needs the base ROM and
  `arm-none-eabi-gcc`; `patch/src/handlers.c` edits are source-only until a rebuild (handoff section 4).

## 3. What must not move into the shared layer

`CLAUDE.md` is not present in the sweep worktree (it is gitignored, local to the root checkout), so the adapter
isolation rules are restated from `.claude/agents/slink-adapter-guard.md`, which enforces them:

1. No `is_rr`, `is_emerald` or game-id checks in `server/server.py`, `server/state.py`, `server/adapters/base.py`
   or `server/pokemon_data.py`; the fix is an adapter method with an inert default (as `supports_explode_mode`
   `base.py:266` and `memorial_box_index` `base.py:486` already are).
2. Adapters are leaf modules: no import of `server.server`; adapters load their own data from `data/games/<gen>/`.
3. No re-introduction of standalone display helpers; display goes through `self.adapter.<method>()`.
4. Game-specific data lives under `data/games/<gen>_<game>/`, never in another game's directory or at the root.
5. Lua clients live in `lua/clients/`, game modules in `lua/games/`.

Applied to Gen 3, the following stays in the adapter and out of every shared module:

- Radical Red data, which is non-standard and must never serve as a vanilla reference: `data/games/gen3_frlge/rr_types.json`,
  `rr_species.json`, `rr_trainers.json`, `rr_encounters.json`, `rr_items.json`, `rr_sprites.json`,
  `rr_priority_trainers.json`, and `server/rr_ability_overrides.py`. Finding: `server/pokemon_data.py:1017` imports
  `rr_ability_overrides` into a shared module; that is an existing exception to rule 1 to resolve during the port
  (move the override table behind `Gen3Adapter.ability_name`, `server/adapters/gen3_frlge.py:435`).
- Per-ROM offsets and memory maps: `lua/memory_gba.lua` (profiles at `initProfile` `:215`), `lua/games/gen3_frlge.lua`
  (`BOXES_PER_STORE` 25 at `:268`, RR detection `:416-437`), the mailbox ABI (`lua/mailbox.lua:13-19`, opcodes
  `:29-311`), `lua/peer_ghost_npc.lua` (`0x02036E38` at `:25`), `sScriptContext2Enabled` `0x03000F9C`
  (`gen3_frlge_client.lua:128-135`), the START-menu and EWRAM-tail facts (handoff section 4), `patch/src/ADDRESSES.md`.
- Adapter policy: fixed-species gifts (`gen3_frlge.py:48-52`), rival classes (`:103`), memorial box (`:584-587`),
  Explode support (`:345`), party blob size 100 (`:340`), the active-slot faint timing (`gen3_frlge_client.lua:781-789`),
  the safe-state predicate (`:2609-2610`), the CFRU faint debounce (`:572-580`).
- Native UI: the field box, battle message and `PlaySE` opcodes (`lua/mailbox.lua:91-94,204-206`), the info panel
  (`:307-386`), the trade scene (`:192-193`).

Two things the port must not do in the other direction: it must not give Gen 3 a private rule where the engine
has one (the `SoulLinkState` handlers listed in `docs/FRAMEWORK.md`, "Rules"), and it must not copy a Gen 1
adapter fact into a Gen 3 module (Gen 1's memorial box 11 at `server/gen1_memorial_policy.py:20` and
`server/gen1_storage.py:189` is the cautionary example; the Gen 3 value comes from `memorial_box_index`).

## 4. Open decisions for the owner

1. Starters and the clauses. RESOLVED 2026-09-11 by the owner: the clauses apply to starters in every
   generation, as Gen 3 does (`intro` is not in `_FIXED_SPECIES_GIFTS`, `server/adapters/gen3_frlge.py:48-52`).
   Gen 1 exempts Yellow/Yellow only, where both starters are Pikachu by script, as an adapter policy that
   knows the pair (`proposals/P14-starters-under-clauses.md`). The engine does not know the difference.
2. Active-slot faint timing. Recommended: keep the Gen 3 deferral (`gen3_frlge_client.lua:781-789`) as the Gen 3
   adapter's `decide` policy and let Gen 1 keep the in-engine faint; both through the shared authority (step c).
   The alternative, one timing for all, would either weaken Gen 1 or change the standard.
3. Dead-zone casualties. The engine books `force_faint` plus `memorialize` for the partner's catch
   (`server/state.py:1841`); the Gen 1 retirement job archives with its own accounting and P13 releases the engine
   obligation for now (P13 note, item 2). Decide whether retirement reports `memorialize_done` so both generations
   end in `MEMORIAL`.
4. `memorialize_failed`. The handoff adopts blocking with repair for every generation; the Gen 3 client reports the
   failure (`:1829`) and the engine completes the pair anyway (`server/state.py:2847-2872`). The repair flow for
   Gen 3 (retry the Lua path, or a native retry) is unspecified.
5. Heartbeat period. P4 defaults to 30 frames and notes 60 halves the cost; Gen 3's `TICK_INTERVAL` (`:4126`)
   would become the same knob. One value per generation, or one for all.
6. Gen 2. `lua/clients/gen2_crystal_client.lua` (1,483 lines), `server/adapters/gen2_crystal.py` (416),
   `lua/games/gen2_crystal.lua` (612) and `tests/e2e/test_duo_gen2.py` exist and get the same treatment after
   Gen 3; `shared-stat-experience-contract.md` already flags the `CalcMonStats` comparison it needs first.
7. Trade verification without a qualified mGBA SaveRAM flush (step e). Qualify `lua/platform_saveram.lua` on
   mGBA, or accept a Gen 3 `TradeVerification` with native receipts only.
8. Starting point for the Gen 3 durable client. `lua/rr/runtime.lua` exists in git history (`120c80d`,
   "Integrate configured RR sessions journals and paired control") but not in this tree. Recommended: start from
   `lua/durable_runtime.lua` as it is now (the contract, the composed journal and the router post-date that
   commit; unverified how far the old file drifted).
9. Admission scope. RR base and patched hashes are known; whether vanilla FRLG and AP builds get a hash catalog
   or stay on header detection is unverified and undecided.
10. `server/upr_pipeline.py`: rename to a Gen 1 name, or generalize with a per-generation content check.

## 5. Rough size: Gen 3 client lines per concern

Spans are banner to banner in `lua/clients/gen3_frlge_client.lua` (4,526 lines by `wc -l`; the docstring
`1-67` is counted as its own row). "Goes to" says where the lines land after the port: `shared` (deleted from the
client, the shared module does the job), `adapter` (stays as Gen 3 code, possibly moved into a smaller module),
`split` (part of each).

| Lines | Count | Concern | Goes to |
| --- | ---: | --- | --- |
| 1-67 | 67 | file docstring and feature list | adapter |
| 68-164 | 97 | configure, module loading (connector, hud, mailbox, peer ghost, game_detect) | split (launcher supplies configuration) |
| 165-373 | 209 | utility helpers, private JSON encoder, private response parser | shared (`json_codec`, `wire_protocol`) |
| 374-383 | 10 | ROM profile detection and validation | adapter |
| 384-411 | 28 | deferred sync state, party integrity protection | shared (`client_journal` inbox) |
| 412-696 | 285 | HUD wrappers, faint debounce constants, EvRing helpers, trade helpers | split |
| 697-1042 | 346 | command dispatcher (`dispatch_commands`) | shared (`command_service_router` plus per-command executor adapters) |
| 1043-1061 | 19 | send and receive | shared (`client_session`, `durable_runtime`) |
| 1062-1468 | 407 | per-frame helpers: party snapshot, mon keys, incremental box scanner | adapter |
| 1469-1599 | 131 | per-frame state declarations | split |
| 1600-1833 | 234 | sync write helpers: `exec_box_mon`, `exec_party_mon`, memorialize | split (executor adapters with receipts) |
| 1834-2035 | 202 | on_frame 0 to 3: address refresh, writes gate, EvRing drain, TCP pump, HELLO, dispatch | shared (pump and HELLO) plus adapter (EvRing) |
| 2036-2296 | 261 | on_frame 4: read state, peer ghost, PC trade NPC, native UI polls, trade apply machine | split (`staged_command` for the phases) |
| 2297-2542 | 246 | on_frame 4a: sync cooldown, `trainer_battle_start`, Explosion settle, rival team and storage polls | split |
| 2543-2583 | 41 | on_frame 4b: deferred battle faint flush | shared mechanism, adapter policy (step c) |
| 2584-2716 | 133 | on_frame 5: `safe_now` and one sync command per frame | split (predicate stays, queue goes) |
| 2717-2993 | 277 | area_enter, battle start, gBattleMons cache, battle end | adapter |
| 2994-3564 | 571 | party read, borrowed-party detector, party freeze, diff gate, nature change | adapter (feeds the observation batch) |
| 3565-3650 | 86 | capture emission (battle, gift, box) | adapter |
| 3651-3801 | 151 | faint, party_to_box, in-battle faint debounce | adapter |
| 3802-3817 | 16 | whiteout | adapter |
| 3818-3879 | 62 | party_to_box, box_to_party and gift buffers | adapter |
| 3880-4109 | 230 | post-battle grace window and no_catch | adapter |
| 4110-4124 | 15 | nuzlocke activation, safe | adapter |
| 4125-4372 | 248 | auto tick | shared (heartbeat inventory of the observation batch) |
| 4373-4456 | 84 | manual F keys | adapter (debug) |
| 4457-4477 | 21 | HUD draw, write guard, advance prev state | adapter |
| 4478-4526 | 49 | `on_frame_safe` and startup | split |

Totals by destination, counting `split` rows at half: about 1,430 lines leave the client for shared modules,
about 3,100 stay as Gen 3 adapter code. Server side, `server/state.py:482-760` (279 lines of trade machine)
leaves the engine for `trade_coordinator` in step (e), and the legacy loop plus `_dispatch`
(`server/server.py:2514-3062`) stops being reachable for Gen 3 runs after step (a); neither is deleted while
Gen 2, 4 and 5 still use the legacy path.
