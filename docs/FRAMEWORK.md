# SLink shared framework: modules, contracts and generation bindings

Tree: sweep worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, HEAD `79d5172`
(branch `claude/gen1-rby-code-sweep-8d06e2`), read 2026-09-11. Every `file:line` below was read from that
tree on that day. The worktree carries 64 tracked files modified and everything since Aug 30 untracked;
untracked files (the whole `docs/gen1_reference/` set, the proposal series, `server/gen1_*` and
`lua/gen1_*` modules) are included, so line numbers belong to the working tree, not to the commit.

> **Status after the takeover (2026-09-11 evening).** The Gen 1 branch is now `gen1/rc` (built on
> `codex/gen1-gambatte-hold`, WIP commit `ead07af`, the proposal series applied as commits `07ba1ca`..`c9bf980`).
> The line numbers below were read at HEAD `79d5172` and are historical; the module inventory is current except
> where a row is marked DELETED: `server/capture_rules.py`, `party_grant_rules.py`, `member_identity_rules.py`,
> `acquisition_disposition_rules.py` went with the fold into the shared engine (commit `0d7db99`), and the
> ordinary frame-credit loop `server/gen1_frame_control.py`, `gen1_frame_journal.py`, `gen1_frame_runtime.py`,
> `gen1_frame_acquisitions.py`, `lua/gen1_frame_client.lua` went with the free-run loop (commit `48c64d0`); the
> tier-2 native-trade window machinery (`execution_window`, `frame_progress`, `frame_pacer`, `gen1_native_*`)
> is kept, with the ledger helpers of the deleted modules moved into `server/gen1_native_frame_accounting.py`.
> The shared-framework in-flight worktree is `.claude/worktrees/shared-framework` on `claude/shared-framework`
> at `codex/shared-operation-binding-v1`; its 22 files diverging from `gen1/rc` are listed in
> `docs/gen1_reference/GEN3_BINDING_PLAN.md` step 0.

## Goal, in one paragraph

One generalized Soul Link runtime with one rule engine, and one adapter per generation that supplies only
cartridge semantics (memory map, save layout, safe-state predicate, native UI, species data, ROM identity).
Gen 3 Radical Red is the gameplay standard: what a Soul Link should do is what the Gen 3 client and
`SoulLinkState` do today (`docs/gen1_reference/GEN3_STANDARD_COMPARISON.md`, 19 rows, is the behaviour
comparison and is not repeated here). Gen 1 (Red/Blue/Yellow) is where the durable framework was built:
the journal, the one-use held-write permits, receipt-verified command closure, the recovery barrier, the
lease, the checked launcher, hash admission, native trade and the in-battle instruction authority. After the
Gen 1 RC, Gen 3 is ported onto that framework (`docs/gen1_reference/GEN3_BINDING_PLAN.md`). This file is the
checkable form of that goal: one row per shared module, its contract, who binds it in Gen 1, who binds it in
Gen 3 today, and what the proposal series changes.

## How to read the table

- `Module` is the file. A module is shared when its name has no generation prefix or the subsystem map
  (`docs/shared-subsystem-map.md`) lists it as a shared mechanism. Trivially internal helpers are folded into
  their owning row and named in `Notes`.
- `Contract` links the `docs/shared-*.md` note when one exists, else gives one clause.
- `Gen 1 binding` names the Gen 1 file:line that consumes the module (an import, a `require`, or the call
  site that makes the mechanism do work), or `unbound`.
- `Gen 3 binding today` names the Gen 3 file:line that consumes it, or `new` when Gen 3 has no binding,
  followed by where the Gen 3 code does the equivalent job today (`today: ...`). "Gen 3 code" means
  `lua/clients/gen3_frlge_client.lua` (4,526 lines), `lua/games/gen3_frlge.lua`, `lua/memory_gba.lua`,
  `lua/mailbox.lua`, `lua/peer_ghost_npc.lua`, `server/adapters/gen3_frlge.py` and the legacy path of
  `server/server.py`.
- `Notes` records proposal dependencies (`P1`..`P13` in `docs/gen1_reference/proposals/`), deletions and
  findings. "after P10" means the row changes shape once the free-run patches are applied.
- Where a claim could not be verified from the tree it says `unverified` and why.

Groups follow the subsystem map. Line counts are `wc -l` of the working tree file.

## The table

### Protocol and delivery

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/protocol.py` (194) | [shared-runtime-contract](shared-runtime-contract.md): strict wire JSON (`decode_frame` :31), `SessionGate` (:83, `admit` :115), `nack` (:188) | `server/gen1_admission.py:19-26` re-exports `decode_frame`, `SessionGate`, `nack`; `server/durable_runtime.py:20`; `server/gen1_runtime.py:12` | `server/server.py:2552` decodes every legacy frame through `gen1_admission.decode_frame` (the same `protocol.decode_frame`); no `SessionGate` on the legacy path, HELLO is `SoulLinkState._handle_hello` (`server/state.py:951`) reached from `server/server.py:3062` | Gen 3 has no admission gate; hash admission is binding step (a) in the plan |
| `lua/connector.lua` (380) | shared-runtime-contract table: bounded TCP framing, FIFO with backpressure, reconnect backoff (`M.pump` :256, `M.disconnect` :364, `discard_on_disconnect` :190,371) | `lua/gen1_client_entry.lua:230`; `lua/gen1_native_runtime.lua:332`; legacy `lua/clients/gen1_rby_client.lua:88` | `lua/clients/gen3_frlge_client.lua:100`; pumped at `:1913`, `C.send` at `:1053` | Shared by both today. `lua/socket.lua` (101) is its LuaSocket loader (`connector.lua:28`), folded here. Gen 3 does not pass `discard_on_disconnect`, so frames queued while connected replay after a reconnect, while `send` itself drops an event emitted while disconnected (`gen3_frlge_client.lua:1048-1051`) |
| `lua/json_codec.lua` (283) | shared-runtime-contract table and [shared-native-frame-primitives](shared-native-frame-primitives.md): bounded RFC 8259 codec with explicit null and object/array kinds | `lua/gen1_client_entry.lua:30`; `lua/gen1_runtime.lua:4`; every `lua/gen1_*` module; `lua/slink.lua:23` | new; today a private encoder `json_encode` at `gen3_frlge_client.lua:204-239` and a private response parser `parse_command_list` at `:241-358` | Gen 3 binds none of the shared codec layer |
| `lua/wire_protocol.lua` (38) | shared-runtime-contract table: decode complete command arrays without filtering malformed entries | `lua/client_session.lua:4`; legacy `lua/clients/gen1_rby_client.lua:92` | new; today `parse_command_list` `gen3_frlge_client.lua:241` | |
| `lua/command_validation.lua` (19) | one clause: integer, text and contiguous-array shape predicates; the adapter supplies legal commands | `lua/gen1_commands.lua:11` (command catalog at `:4-7`) | new; today ad hoc checks inside the dispatcher `gen3_frlge_client.lua:698-1042` | |
| `lua/client_session.lua` (111) | shared-runtime-contract "Session contracts": `begin`, `decorate`, sequence and operation envelopes, `durable_ids` (:35,40) | `lua/gen1_session.lua:35`; `lua/durable_runtime.lua:6` | new; today a bare `seq` counter and `send` at `gen3_frlge_client.lua:1044-1060`, HELLO built at `:1939-1945` | Gen 3 has no nonce and no operation id; the server side keys retries on nothing |

### Persistence and replay

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/protocol_journal.py` (486) | [shared-runtime-contract](shared-runtime-contract.md) "Journal contracts" (`commit` :280, `pending_ids` :421, `acknowledge` :476), [shared-atomic-records-contract](shared-atomic-records-contract.md), [shared-event-snapshot](shared-event-snapshot.md) | `server/gen1_runtime.py:13`; `server/gen1_run_config.py:13`; 60 more `server/gen1_*` modules | new; today `links.json` and `memorial.json` written by `SoulLinkState._atomic_write_json` (`server/state.py:3081-3104`) from `_save` (`:3187`); `to_document` (`:3107-3190`) persists `pending_memorials` (`:3158`) but not `queued_commands`, so a server restart drops every queued command except memorials | Handoff decision: adopt the journal for every generation |
| `server/durable_dispatch.py` (78) | shared-runtime-contract table: stage rules, call `handle_event` (:64-68), drain `take_commands` (:71), commit state, both outboxes and validated receipts in one transaction (:74) | via `server/durable_runtime.py:18` | new; today `SLinkServer._dispatch` (`server/server.py:2998-3062`) mutates the live `SoulLinkState` in memory | The durable path and the legacy path are mutually exclusive by construction (`server/server.py:2999-3000`) |
| `server/staged_state.py` (168) | shared-runtime-contract "Rule staging": `StagedSoulLinkState(SoulLinkState)` (:47), `from_live` (:74), `document`/`restore` (:100,126), `take_commands` (:159) | `server/gen1_staged_state.py:3,6` (`StagedGen1State`, refuses non-vanilla RBY at `:9`); `server/gen1_memorial_policy.py:16` | new; today the live `SoulLinkState.load` (`server/server.py:1551`) | The generic class already wraps the shared engine; a Gen 3 subclass is one `validate_game_state` override |
| `lua/client_journal.lua` (253) | [shared-client-journal-composition](shared-client-journal-composition.md) and shared-runtime-contract "client journal" | `lua/gen1_client_entry.lua:84`; `lua/gen1_native_runtime.lua:126` | new; today in-memory `pending_sync_cmds` (`gen3_frlge_client.lua:385`) and `pending_labels` (`:1045`) | |
| `lua/state_store.lua` (105) | [shared-state-snapshot-copy](shared-state-snapshot-copy.md) | `lua/gen1_client_entry.lua:85`; `lua/gen1_native_runtime.lua:127` | new | |
| `lua/platform_storage.lua` (100) | shared-runtime-contract table: exclusive file ownership, SHA-256, flush, atomic replace | `lua/gen1_client_entry.lua:86`; `lua/gen1_native_runtime.lua:128` | new | |
| `lua/journal_document.lua` (54) | [shared-journal-document-contract](shared-journal-document-contract.md) | `lua/gen1_held_faint.lua:3`; `lua/gen1_full_save.lua:5`; `lua/staged_command.lua:4`; 11 more `lua/gen1_*` | new | |
| `server/journal_reader.py` (60) | [shared-launcher-reader-contract](shared-launcher-reader-contract.md) "Read-only journal" | `server/gen1_run_config.py:10`; `server/runtime_boundary.py:177` | new (no journal to read) | |
| `server/event_reference.py` (36) | [shared-frame-progress](shared-frame-progress.md) second section: compact checked reference to a committed event | `server/gen1_observation_provenance.py:6`; `server/gen1_faint_runtime.py:6`; 14 more | new | `server/issued_command.py` (20, `gen1_storage_runtime.py:19`) and `server/retained_physical_record.py` (80, `gen1_storage_runtime.py:23`) are evidence helpers on top of it, folded here |
| `server/json_value_copy.py` (30) | [shared-json-value-copy](shared-json-value-copy.md) | `server/gen1_runtime_state.py:17` | new | Helper; needed once a Gen 3 stage document exists |
| `server/backup.py` (73) | one clause: rolling copies of `links.json` and `events.json` while both players are connected | unbound (the journal replaces it) | `server/server.py:2376` | Retires for Gen 3 when the journal lands |
| `server/json_files.py` (32) | one clause: atomic JSON publication | `server/gen1_run_config.py:11`; `server/gen1_upr_pipeline.py:12` | `server/manager.py:48` for run metadata; `server/state.py:3081` duplicates it for `links.json` | Duplicate to fold when Gen 3 persistence moves |

### Identity

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/identity_registry.py` (652) | [shared-identity-contract](shared-identity-contract.md) | `server/gen1_runtime_state.py:16`; `server/gen1_run_config.py:102`; `server/gen1_acquisition_runtime.py:24`; 9 more; shared `server/trade_coordinator.py:16` | new; today raw keys only: `party_keys`, `find_link` (`server/state.py:2733`), `_handle_key_change` (`:2475`) | Gen 3 keys are personality/OT id strings; the registry stores raw keys unchanged (contract, "Current keys") |
| `server/player_keys.py` (41) | one clause: player-scoped raw key resolution, refuses ambiguity | via `server/state.py:27` | via `server/state.py:27` | Shared by both through the engine |
| `server/save_identity.py` (23) | shared-runtime-contract "save_identity=SaveIdentity(...)" paragraph | `server/gen1_runtime_admission.py:9`; `server/gen1_initial_observation.py:13`; `server/server.py:3058-3061` builds it for the RBY gate only | via `server/state.py:30`: `_hello_identity` (`:927`) falls back to payload `ot_id`/party keys because the legacy path passes no `SaveIdentity` | Partially shared; Gen 3 needs the validated form once it has admission |
| `server/admission_context.py` (23) | [shared-frame-progress](shared-frame-progress.md) third section | `server/gen1_held_faint.py:5`; `server/gen1_inventory_observation.py:5`; 10 more | new | |
| `lua/platform_identity.lua` (19) | shared-runtime-contract table: OS-backed 32-hex nonces | `lua/gen1_session.lua:18`; `lua/gen1_client_entry.lua:38` | new; today no nonce (`seq` only, `gen3_frlge_client.lua:1044`) | |

### Observation checkpoints

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `lua/observation_stream.lua` (59) | [shared-observation-checkpoints](shared-observation-checkpoints.md) | `lua/gen1_initial_observation.lua:5` | new; today the per-frame decrypted party diff (`gen3_frlge_client.lua:2994-3564`) and the incremental box scanner (`:1316-1468`) | |
| `server/keyed_inventory.py` (40) | same note, `compare(before, after, limit)` (:7) | `server/gen1_inventory_transition.py:3` | new; today the diff is client-side | |
| `server/party_observation_cache.py` (48) | one clause: refresh display/planning data from a validated party without acquiring or linking | `server/gen1_rule_inventory.py:5` | new; today `cache_stats` (`server/state.py:2743`) fed by `tick` party snapshots (`gen3_frlge_client.lua:4126-4133`) | |
| `lua/gen1_observation_loop.lua` (96) | P4 note: free-running loop, one `observation` event per signal, receipt or heartbeat (`:48-83`), `tick`/`observe`/`run` (`:91-93`) | P10 wiring patch (`lua/gen1_client_entry.lua`, `mode == "free_service"`), not yet applied | n/a as a module; the same shape already runs in Gen 3: `event.onframeend(on_frame_safe, ...)` (`gen3_frlge_client.lua:4525`), heartbeat `tick` every `TICK_INTERVAL` frames (`:4126`) | Gen 1-prefixed today; it is the proposed shared core loop (`EXECUTION_MODEL_PROPOSAL.md` section 3). Rename after P10 lands |
| `server/gen1_observation_runtime.py` (183) | P10 note: `observation` consumer, sequence contiguity, ROM and context checks, one commit (`:28-38`) | P10 wiring patch (`server/gen1_runtime.py` `_dispatch_semantic`), not yet applied | n/a; Gen 3 events reach the engine one at a time through `server/server.py:3062` | Gen 1-prefixed; the settlement order (inventory, signals, receipts) is the generic part, the decoders are RBY |
| `lua/memory_gb.lua` (2311), `lua/memory_gba.lua` (2167), `lua/memory_nds.lua` (1561) | platform memory profiles, shared per platform not per generation (`memory_gb.lua:1-3`: Gen 1 and Gen 2) | `lua/gen1_client_entry.lua:32` (`initProfile` with `games/gen1_rby.lua`); legacy `:87` | `gen3_frlge_client.lua:99` (`memory_gba`), `M.initProfile` at `memory_gba.lua:215` | Cartridge semantics live here on purpose; not a merge target |

### Engine signals and source receipts

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/source_receipts.py` (48) | docstring (:1-11): index-preserving dispatch of a raw `{kind, receipt}` list; the generation owns kinds and decoders | `server/gen1_source_receipts.py:11` | new; today the client assembles `capture` itself (`gen3_frlge_client.lua:3588`, box `:3969`) and drains the patch EvRing (`:1876-1911`) | The subsystem map's "engine signal publication" rows are the journal batches above; the Gen 1 hooks (`lua/gen1_engine_signals.lua`) are adapter code |

### Rules

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/state.py` (3200), `SoulLinkState` | shared-runtime-contract "Rule staging"; `handle_event` (:241-246) returns the caller's own commands and queues cross-player ones; handlers `_handle_capture` :1212, `_handle_faint` :1704, `_handle_no_catch` :1841, `_handle_whiteout` :1992, `_handle_party_to_box` :2076, `_handle_box_to_party` :2124, `_handle_key_change` :2475, `_check_link_violation` :2578, `_propagate_faint` :2685, `_handle_memorialize_done` :2822, `_handle_memorialize_failed` :2847, `_handle_trainer_battle_start` :2957, `_check_game_over` :3046 | constructed at `server/gen1_run_config.py:103,111`; `handle_event` is unreachable in a production run because `open_runtime` installs `validate_event=no_new_observations` (`server/gen1_run_config.py:84-87`); reached only by the proposal series (`server/gen1_engine_bridge.py:16,27`, P8 and P9 patches) | `server/server.py:1551` (`SoulLinkState.load`), `:3062` (`handle_event` for every legacy event), `:1698` adapter selection | The shared engine. Trade for Gen 3 also lives here (`:482-760`), see Trade |
| `server/adapters/base.py` (578) | one clause: `GameRulesAdapter` (:48) and `GamePresentationAdapter` (:282) with inert defaults: `is_fixed_species_gift` :70, `rival_trainer_ids` :188, `party_blob_size` :204, `supports_explode_mode` :266, `rom_content_fingerprint` :360-372 (returns None), `memorial_box_index` :486 | `server/adapters/gen1_rby.py:318` (`Gen1Adapter(GameAdapter)`; `supports_explode_mode` :367, `rom_content_fingerprint` :554, `memorial_box_index` :609-614 returns 11) | `server/adapters/gen3_frlge.py:29,259` (`Gen3Adapter`; `is_rr` :267, `_FIXED_SPECIES_GIFTS` :48-52, `rival_trainer_ids` :314, `party_blob_size` :340, `supports_explode_mode` :345, `memorial_box_index` :584-587 returns 24 on RR, 13 otherwise; no `rom_content_fingerprint` override) | Shared by both. Registry `server/adapters/__init__.py:20,90,106,126` |
| `server/pokemon_data.py` (1796) | one clause: species, type, gender and key helpers | `server/adapters/gen1_rby.py:14` | `server/adapters/gen3_frlge.py:14`; `server/state.py:29`; `server/server.py:49,56` | Shared. Finding: `server/pokemon_data.py:1017` imports `server/rr_ability_overrides.py` (RR data inside a shared module); see the plan, section 3 |
| `server/gen1_semantic_events.py` (75) | P3 note: pure translators to the events `handle_event` consumes (`:16-75`) | `server/gen1_engine_bridge.py:14`; `server/gen1_whiteout.py` (P12); P8 and P9 patches | n/a: the Gen 3 client already emits these events (`capture` :3588, `no_catch` :4102, `faint` :3682, `whiteout` :3813, `trainer_battle_start` :2337, `memorialize_done` via `memorialize_finish` :1752) | Gen 1 adapter code that exists only to feed the shared engine |
| `server/gen1_engine_bridge.py` (116) | P13 note: `starter_grant`, `no_catch`, `rekey`, `memorial_completion` through `handle_event` (:23-45) | P13 patch call sites (`server/gen1_starter_settlement.py:12,126`, `gen1_wild_encounter_runtime.py`, `gen1_evolution_runtime.py`, `gen1_npc_exchange_runtime.py`, `gen1_memorial_runtime.py`), not yet applied | n/a | Present as a file in the tree, its consumers only in the P13 patch |
| `server/capture_rules.py` (65) | detached copy of `_handle_capture`; GEN3_STANDARD_COMPARISON section 1.1 | `server/acquisition_disposition_rules.py:10` (from `server/gen1_acquisition_runtime.py:251`) | never (Gen 3 runs the engine method) | Unused after P9 and P13; delete with its tests (P13 note, "What is now unused") DELETED 2026-09-11 (commit 0d7db99) |
| `server/no_catch_rules.py` (112) | detached copy of `_handle_no_catch` | `server/gen1_wild_encounter_runtime.py:12` | never | After P13 only `decision` (naming) and `update_run_over` remain in use |
| `server/member_identity_rules.py` (47) | detached copy of `_handle_key_change` | `server/gen1_evolution_runtime.py:18`; `server/gen1_npc_exchange_runtime.py:37` | never | Unused after P13 DELETED 2026-09-11 (commit 0d7db99) |
| `server/acquisition_disposition_rules.py` (31) | adapter over `capture_rules` and `party_grant_rules` | `server/gen1_acquisition_runtime.py:251` | never | Unused after P9 DELETED 2026-09-11 (commit 0d7db99) |

### Exempt party grants

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/party_grant_rules.py` (57) | [shared-party-grants](shared-party-grants.md) | `server/gen1_starter_settlement.py:12`; `server/acquisition_disposition_rules.py:11` | never; a Gen 3 starter is `capture` with `area_id="intro"` (`gen3_frlge_client.lua:3620`) into `_handle_capture` | Unused after P13; starters-and-clauses is an owner decision (plan, section 4) DELETED 2026-09-11 (commit 0d7db99) |

### Linked deaths

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/linked_death_rules.py` (65) | [shared-linked-death](shared-linked-death.md), [shared-memorial-completion](shared-memorial-completion.md) | `server/gen1_faint_runtime.py:12`; `server/gen1_memorial_runtime.py:13`; `server/no_catch_rules.py:10` | never; Gen 3 uses `_propagate_faint` (`server/state.py:2685`, Explode selection `:2700-2703`) and `_handle_memorialize_done` (`:2822`) | P8 routes the faint through the engine; P13 routes memorial completion; the module then keeps only `update_run_over` |

### Physical commands

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `lua/command_executor.lua` (90) | [shared-executor-native-contract](shared-executor-native-contract.md) and shared-runtime-contract "command_executor.new" (prepare, classify, apply, receipt) | via `lua/durable_runtime.lua:8`; adapters `lua/gen1_force_faint_executor.lua:1-6`, `lua/gen1_held_faint.lua:45` | new; today direct writes with no prepared intent or readback receipt: `M.forceFaint(slot)` at `gen3_frlge_client.lua:793`, `exec_box_mon` `:1601`, `exec_party_mon` `:1670`, `exec_memorialize` `:1781` (native `OP_MEMORIALIZE` `:1800-1821`, Lua fallback `:1823-1831`) | Handoff decision: receipt-verified closure for every generation |
| `lua/staged_command.lua` (153) | [shared-staged-command](shared-staged-command.md) | `lua/gen1_native_runtime.lua:144`; `lua/gen1_prepared_save.lua:32` | new; today the `pending_trade_apply` phase machine (`gen3_frlge_client.lua:2214-2296`) and the mailbox polls (`:2194-2208`, `:2429-2435`) | |
| `server/operation_scope.py` (23) | docstring: exact command/context scope for generation-verified permits (`command_scope` :16) | `server/gen1_held_faint.py:6`; `server/gen1_memorial_runtime.py:14`; 5 more; shared `held_write_permit.py:6`, `instruction_authority.py:25`, `battle_force_authority.py:42`, `execution_window.py:9` | new | |
| `server/hex_delta.py` (98) and `lua/hex_delta.lua` (41) | [shared-hex-delta](shared-hex-delta.md) | `server/gen1_save_delta.py:9`; `server/gen1_authorized_inventory.py:12`; `lua/gen1_held_save_image.lua:28-41` | new | |

### In-battle instruction authority

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/instruction_authority.py` (180) | docstring (:1-20): one-instruction write authority, `MAX_WINDOW_FRAMES` 64 (:30), `issue` :62, `verify_window` :141, `verify_footprint` :162 | `server/battle_force_authority.py:41` | new; today the active-battler faint is deferred client-side to switch-out or battle end (`gen3_frlge_client.lua:781-789`, flushed at `:2543-2582`) and Explode is coerced by per-frame RAM writes (`:2344-2427`, fallback at `:2414`) | Proven live on R/B/Y (`BATTLE_FORCE_FAINT_WINDOW.md`); P11 adds the Explode binding. The plan keeps the Gen 3 timing rule as adapter policy (step c) |
| `server/battle_force_authority.py` (212) | R/B/Y binding: `BINDING` :46, `sites` :103, `decide` :128, `prepare` :155, `issue` :178, `verify_evidence` :185 | tests only in this tree (`tests/unit/test_battle_force_*.py`, `tests/live/test_gen1_battle_force.py`); production wiring is handoff item 5 | new; a Gen 3 binding would be a sibling file with GBA sites, not this one | Gen 1 adapter code on a shared mechanism |
| `lua/instruction_executor.lua` (128) | header (:1-12): generation-independent one-instruction executor, window `MAX_WINDOW_FRAMES` 64 (:14) | `lua/battle_force_authority.lua:7` | new | Marked PROTOTYPE at `:1`; wired only by the live gate |
| `lua/battle_force_authority.lua` (46) | R/B/Y snapshot and decision for the executor (`NAME` :8, `decide` :20-41) | `lua/tests/test_gen1_battle_force_gate.lua` (gate only) | new; Gen 3 equivalent would snapshot `gBattleMons` | |

### Trade

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/trade_coordinator.py` (537) | [shared-trade-coordinator-contract](shared-trade-coordinator-contract.md), [shared-trade-runtime-composition](shared-trade-runtime-composition.md) | `server/gen1_runtime.py:15`; `server/gen1_native_policy.py:18`; `server/gen1_trade_rules.py:15`; `server/gen1_trade_recovery.py:9`; `server/gen1_receptionist_runtime.py:178` | new; today an in-engine state machine `server/state.py:482-760` (`_handle_trade_request` :536, `_handle_mon_chosen` :557, `_handle_menu_result` :614, `_execute_trade` :656, `_handle_trade_done` :691, `_commit_trade` :715) and the client apply path `gen3_frlge_client.lua:947` (`apply_trade`), `:2214-2296` | P1 restores the staging gate at `gen3_frlge_client.lua:2221-2241` (today the staging sits inside the `not patch_present()` branch `:2222-2238`, so a patched ROM only times out at `:2239-2240`) |
| `server/trade_driver.py` (48) | [shared-trade-driver](shared-trade-driver.md) | `server/gen1_native_binding.py:9` | new; today `_tick_pending_trade` (`server/state.py:514`) | |
| `lua/platform_saveram.lua` (107) | [shared-saveram-contract](shared-saveram-contract.md) | `lua/gen1_held_save_image.lua:59`; `lua/gen1_native_runtime.lua:186,205` | new; today no save-file receipt for any Gen 3 write | Contract says mGBA save media is not qualified; that is Gen 3 adapter work |
| `lua/staged_panel.lua` (46) | [shared-staged-panel](shared-staged-panel.md) | `lua/memory_gb.lua:1679` (ABI-3 panel) | new; today `link_panel` rows (`gen3_frlge_client.lua:980`) go through `MB.write_info`/`MB.show_info` (`lua/mailbox.lua:358,385`) and `SLinkServer._build_link_panel` (`server/server.py:2744`) | Gen 3 has its own single-slot mailbox ABI v1; the odd/even publisher may not fit it (unverified: the mailbox has no generation counter field, `lua/mailbox.lua:17-19`) |

### Storage and saves

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/binary_codec.py` (35) | shared-runtime-contract "hex-bytes-v1" party caches | via `server/staged_state.py:11` | new; today raw blobs held in memory by `_ingest_party_blobs` (`server/state.py:2874`) and dropped on restart (not in `to_document` `:3107-3190`) | |
| `server/save_file_receipt.py` (32) | [shared-staged-command](shared-staged-command.md) last section | `server/gen1_full_save.py:13`; `server/gen1_memorial.py:16`; `server/gen1_storage.py:20`; `server/gen1_retirement.py:25` | new; today `memorialize_done` is a client claim (`gen3_frlge_client.lua:1752`) and `memorialize_failed` (`:1829`) still completes the pair (`server/state.py:2847-2872`) | Handoff decision: blocking `memorialize_failed` for every generation |
| `server/stat_experience.py` (28) | [shared-stat-experience-contract](shared-stat-experience-contract.md) | `server/gen1_trade_result.py:18` | not applicable: RBY stat-experience arithmetic; Gen 3 stats are engine-owned | Contract itself says Gen 2 must compare against `CalcMonStats` first |

### Runtime

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/durable_runtime.py` (393) | [shared-durable-server-contract](shared-durable-server-contract.md): `DurableRuntime` (:30), `process` :205, `_dispatch_semantic` :254, `_before_suspend` :287, `suspend` :294 | `server/gen1_runtime.py:8,91` (`Gen1Runtime(DurableRuntime)`), `_dispatch_semantic` override `:274-346` | new; today `SLinkServer.handle_client` (`server/server.py:2514`) and `_dispatch` (`:2998`); the durable client is refused at `:2558-2562` unless a Gen 1 runtime is configured | Server-side runtime; generation-neutral by construction (contract, "no cartridge addresses") |
| `lua/durable_runtime.lua` (447) | [shared-durable-runtime-contract](shared-durable-runtime-contract.md) | `lua/gen1_runtime.lua:5` (`PROTOCOL="slink-gen1-durable-v1"` :7) | new; today `on_frame` (`gen3_frlge_client.lua:1852`): pump `:1913`, reconnect and HELLO `:1916-1945`, dispatch `:1967-2035` | The contract names `lua/rr/runtime.lua` as the RR binding; that file is not in this tree (git history only, commit `120c80d`, `codex/rr-foundation` carries `lua/rr/admission.lua` and `lua/rr/battle_snapshot.lua`). Treat the RR binding as not present |
| `lua/control_service.lua` (131) | [shared-recovery-contract](shared-recovery-contract.md) "lua.control_service" | via `lua/durable_runtime.lua:7`; hold policy consumed by `lua/gen1_client_entry.lua` | new; today no hold at all: the client free-runs on `event.onframeend` (`gen3_frlge_client.lua:4525`) | After P10 the hold is taken only around writes (`EXECUTION_MODEL_PROPOSAL.md` section 3), which is the shape Gen 3 can bind |
| `lua/command_service_router.lua` (72) | [shared-runtime-latency](shared-runtime-latency.md) last paragraph | `lua/gen1_client_entry.lua` composes `{gen1_hud_service, gen1_held_faint}` on every launch (base `FILES`); see `gen1_reference/HUD_NOTICE_DELIVERY.md` | new; today the if/elseif dispatcher `gen3_frlge_client.lua:698-1042` (commands at `:721-1033`) | |
| `lua/platform_clock.lua` (19) | shared-recovery-contract: .NET `Stopwatch`, independent of frames | `lua/gen1_client_entry.lua:115`; `lua/gen1_native_runtime.lua:77` | new; today `emu.framecount()` only | |

### Holds and recovery

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `lua/platform_execution.lua` (255) | `docs/platform-execution-contract.md`: pinned exclusive hold actuator; profiles `mgba` and `gambatte` (`:4-14`) | `lua/gen1_client_entry.lua:63`; `lua/gen1_native_runtime.lua:121` | new, but the mGBA profile is pinned (`:4`, capability `bizhawk-2.11.1-mgba-exclusive-hold-v1`) and re-verified on RR bytes (`docs/rr_reference/SHARED_PROFILE_HOLD.md`, runs 34 to 36); today nothing selects it | The only hold Gen 3 needs under free-run is around writes |
| `server/paired_recovery.py` (205) | [shared-recovery-contract](shared-recovery-contract.md) "Durable reconciliation" (`RecoveryBarrier`) | `server/gen1_runtime_state.py:18`; `server/gen1_runtime.py:203`; `server/gen1_trade_recovery.py:7`; shared `server/durable_runtime.py:19` | new; today HELLO re-reconciles everything in memory (`server/state.py:951`) | |
| `server/paired_liveness.py` (105) | shared-recovery-contract "Fresh authority and independent clocks" | unbound in production: only `server/runtime_boundary.py:133,147` reports it as `None`; tests only | new | Unbound by both generations today |

### Bounded frame scheduling (tier 1 deleted in 48c64d0 on 2026-09-11; tier 2 kept for native trade)

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `lua/execution_window.lua` (155) | [shared-execution-window](shared-execution-window.md), [shared-native-frame-primitives](shared-native-frame-primitives.md) | `lua/gen1_frame_client.lua:6`; `lua/gen1_native_runtime.lua:108,276` | none; Gen 3 cannot bind server-granted frame credits without a qualified mGBA bounded host | Delete list, `EXECUTION_MODEL_PROPOSAL.md` section 4; not shipped in `free_service` mode (P10 note, `gen1_launcher.py`) |
| `server/execution_window.py` (43) | same notes | `server/gen1_frame_control.py:6`; `server/gen1_frame_journal.py:13`; `server/gen1_frame_runtime.py:13`; `server/gen1_execution_authority.py:5`; `server/gen1_native_execution.py:10`; `server/gen1_native_frame_accounting.py:13`; `server/gen1_receptionist_runtime.py:5` | none | Finding: `gen1_receptionist_runtime.py:5` imports `command_scope` through this module; it is defined in `server/operation_scope.py:16` (`execution_window.py:9` re-exports it). Re-point that import before the deletion |
| `lua/frame_pacer.lua` (39) | shared-native-frame-primitives "frame_pacer.new" | `lua/gen1_frame_client.lua:164`; `lua/gen1_native_runtime.lua:341` | none; the cartridge runs at its own rate | Delete list |
| `server/frame_progress.py` (217) | [shared-frame-progress](shared-frame-progress.md) | `server/gen1_frame_journal.py:11`; `server/gen1_frame_runtime.py:12`; `server/gen1_authorized_inventory.py:10`; 4 more | none | Delete list; `shared-runtime-latency.md` and `shared-held-runtime-latency.md` retire with it |
| `lua/platform_bounded_execution.lua` (151) | [shared-bounded-execution](shared-bounded-execution.md): `step_one`, Gambatte only (`:6`) | `lua/gen1_client_entry.lua:65`; `lua/gen1_native_runtime.lua:120` | none (Gambatte-only qualification) | Kept as the short-hold tool for the in-battle window (handoff item 5); not on the P10 delete list |

### Held writes

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/held_write_permit.py` (34) and `lua/held_write_permit.lua` (74) | [shared-held-write-permit](shared-held-write-permit.md): one use, at most 1,000 ms, no frame API | `server/gen1_held_faint.py:7`; `server/gen1_memorial_runtime.py:12`; `server/gen1_storage_runtime.py:18`; `server/gen1_retirement_runtime.py:19`; `server/gen1_initial_save_runtime.py:12`; `server/gen1_held_rival_team.py:16` (P12); `lua/gen1_held_faint.lua:5,36-37` | new; today writes are gated only by `safe_now` (`gen3_frlge_client.lua:2609-2610`: overworld, no cooldown, party not frozen, end-of-battle settled) and `writes_enabled` (`:1862`), with no permit and no receipt | The Gen 1 executors behind the permit are adapter code: `lua/gen1_held_faint.lua` (175) with `server/gen1_held_faint.py` (108, refuses battle at `:71`), `lua/gen1_held_memorial.lua` (9), `lua/gen1_held_storage.lua` (39), `lua/gen1_held_initial_save.lua` (9), `lua/gen1_held_retirement.lua` (16), `lua/gen1_held_save_image.lua` (150), `lua/gen1_held_rival_team.lua` (187) with `server/gen1_held_rival_team.py` (137) |

### Launch and inspection

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/runtime_launcher.py` (128) | [shared-launcher-reader-contract](shared-launcher-reader-contract.md) "Checked launcher" (`file_bundle`, `render_launcher`) | `server/gen1_launcher.py:5` (file closures `FILES` :8-18, `OBSERVATION_FILES` :19, `ORDINARY_FILES` :27, `NATIVE_FILES` :38; `build_configuration` :50); `server/manager.py:728` | new; today `lua/slink_gen3.lua:12-18` sets three globals and `dofile`s the client, or `lua/slink.lua:82-96` detects the game and `dofile`s it; no file fingerprints | `server/lua_literals.py` (22; `runtime_launcher.py:9`, `server/server.py:38`, `server/manager.py:49`) is the literal encoder, folded here and already shared |
| `server/bizhawk_launch.py` (117) | docstring (:1): isolated emulator files, never the user's base config or save | `server/manager.py:735`; `server/server.py:6482-6485` (Gen 1 launcher bundle with `profile='gambatte'`); `tools/launch_bizhawk.py:10` | new; the bundle route is reached only from the Gen 1 launcher | |
| `lua/slink.lua` (97) | one clause: universal entry; durable launch at `:14-28` (protocol `slink-gen1-durable-v1` asserted at `:26`), legacy detection at `:78-97` | `:27` (`gen1_client_entry.run`) | `:85` (`gen3_frlge = "clients/gen3_frlge_client.lua"`), `:97` | Shared by both, on two different branches of the same file |
| `lua/game_detect.lua` (80) | one clause: registry and priority dispatch over `lua/games/*` | `lua/slink.lua:78` with `lua/games/gen1_rby.lua:654` (`detect`), `:1003` (`detect_variant`) | `gen3_frlge_client.lua:161`; `lua/memory_gba.lua:216`; `lua/games/gen3_frlge.lua:46` (`detect`), `:437` (`detect_variant`, RR check `:416`) | Shared by both |

### Run ownership

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/runtime_lease.py` (38) | [shared-runtime-lease](shared-runtime-lease.md) | `server/gen1_runtime.py:14`; `tools/launch_bizhawk.py:11`; run creation `server/gen1_run_config.py:97-135` (refuses a directory holding `links.json` at `:107`), Manager `POST /api/runs/gen1` (`server/manager.py:751,1103`) | new; today Manager `POST /api/runs/new` (`server/manager.py:1097`) with no lease | |

### Binary patch composition

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/patch_plan.py` (66) | [shared-patch-plan](shared-patch-plan.md) | `server/gen1_companion_patch.py:7`; `tools/build_gen1_companion.py:22` | new; today `patch/tools/build.py` (C toolchain, seven-step pipeline in its docstring `:1-16`) injects bytes directly and emits `patch/dist/SLink-RR.ups`; base md5 `8529f3a45d32bce4da637976fcf269d4`, patched `8dcffce7659be02474dfa0f876639f8a` (`patch/README.md`) | The UPS codec `patch/tools/make_ups.py` is already shared: `server/gen1_upr_pipeline.py:8`, `server/gen1_prepared_cartridges.py:9`, and the browser port named at `server/patcher.py:13-14` |
| `server/patcher.py` (176) | docstring (:1-14): browser patcher routes, client-side UPS apply | `_gen1_targets` `:61-80` (R/B/Yellow companion targets) | `GET /companion/SLink-RR.ups` (`:8-9`, default target `:51,93`); mounted by `server/server.py:8729` and `server/manager.py:1132` | Shared by both today |

### ROM change accounting

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/rom_change_audit.py` (58) | [shared-rom-change-audit](shared-rom-change-audit.md) | `server/gen1_upr_scan.py:14` | new; today ROM identity is header code plus pointer plausibility (`lua/games/gen3_frlge.lua:416-437`); `Gen3Adapter` has no `rom_content_fingerprint`, so `server/server.py:1787` gets the base `None` (`adapters/base.py:372`) and `_decide_admission` (`:1763-1770`) admits every ROM | Handoff decision: complete-hash admission for every generation |

### UPR generation

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/upr_catalog.py` (93) | docstring (:1): complete UPR wire layout, generation-independent | `server/gen1_upr_policy.py:7` | new; no Gen 3 UPR path exists (Radical Red is not a UPR target) | |
| `server/upr_runner.py` (177) | docstring (:1): pinned external UPR invocation and provenance | `server/gen1_prepared_cartridges.py:15`; `server/gen1_upr_pipeline.py:14` | new | |
| `server/upr_settings.py` (455) | docstring (:1-12): read and write `.rnqs`, admission allowlist | `server/gen1_upr_policy.py:8`; shared `upr_catalog.py:11`, `upr_pipeline.py:41`, `upr_runner.py:13` | new | |
| `server/upr_pipeline.py` (270) | docstring (:1-12): matched randomized pair, same settings, different seeds (`prepare_pair` :189) | imports `server/adapters/gen1_rom_scan` (`:38,249`); `server/manager.py:874` (`POST /api/runs/{run_id}/randomize`) | none; the Manager route exists for any run but the content check is Gen 1 only | Finding: generic name, Gen 1 body; the subsystem map row "upr_catalog and upr_runner: full format ... sequential JVM pairs" does not list it |

### UI and runtime facts

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/runtime_boundary.py` (207) | subsystem map "Shared read-only runtime boundary": `restricted_rby` :29, `operation_decision` :37, `read_rule_state` :63-71, `read_runtime_facts` :74 | journal source at `:65-69`; mutations refused at `:40-42` | live-memory source at `:70-71`; `server/server.py:36`; `server/manager.py:45` | Shared by both. Handoff decision: dashboard mutations return as journaled operations |
| `server/server.py` (8865) | one clause: per-run TCP and HTTP server (`SLinkServer` :1526, `handle_client` :2514, `_dispatch` :2998, `build_app` :8617, `asyncio.start_server` :8774) | `gen1_runtime` constructor argument `:1534-1542`; `gen1_runtime.handle_client` `:2516`; `_gen1_wire_response` `:2452`; gen1 connection detection `:2583-2588` | the legacy loop `:2522-2719`, `_dispatch` `:2998-3062`, panel rows `:2744`, admission `:1763` | Two mutually exclusive paths (`:2999-3000`) in one file |
| `server/manager.py` (1176) | one clause: run manager and launcher routes (`:1096-1106`) | `handle_create_gen1` `:751`, launcher `:720-735` | `handle_new` (`:1097`), `handle_randomize` (`:874`) | Shared |
| `lua/hud.lua` (313) | header (:1-7): overlay message queue, center prompts, banner; `sanitize` folds glyphs to ASCII (:14-20); additive `present`/`retained` path for durable notices | legacy `lua/clients/gen1_rby_client.lua:93`; durable client `lua/gen1_client_entry.lua` (`init` at start, `render` once per new frame, `present` from `lua/gen1_hud_service.lua`), in `gen1_launcher.py` `FILES` | `gen3_frlge_client.lua:101` | Shared by the legacy clients and the Gen 1 durable client |
| `lua/mailbox.lua` (536) | header (:1-9): RR companion-patch EWRAM mailbox ABI v1 at `0x0203F800` (:13-19); opcodes `:29-311` | none (Gen 1 has its own panel ABI-3 in `lua/memory_gb.lua:1679` and `patch/gen1/`) | `gen3_frlge_client.lua:103`; `lua/peer_ghost_npc.lua:21` | Not generation-neutral despite the unprefixed name; it is the Gen 3 native endpoint |
| `lua/peer_ghost_npc.lua` (207) | header (:1-19): engine object-event peer ghost, RR only (`gObjectEvents` `0x02036E38` at `:25`) | none | `gen3_frlge_client.lua:144-150` | Gen 3 adapter code |
| `server/status_payload.py` (70), `server/html_render.py` (197), `server/templating.py` (179), `server/chrome.py` (145), `server/http_safety.py` (93), `server/overlay_catalog.py` (284) | one clause each: Manager empty status; display primitives; Jinja and static wiring; sidebar chrome; browser-origin checks; OBS overlay catalog | via `server/manager.py:51,52,47,50` and `server/server.py` | `server/server.py:123,77,2333,37,39`; `server/manager.py:956,1131` | Generation-neutral presentation, shared today |
| `server/obs_controller.py` (564), `server/twitch_bot.py` (555) | one clause: OBS scene switching and Twitch chat, driven by rule events | via `server/server.py` | `server/server.py:62,69,7538,7590` | Peripheral, generation-neutral |

### Source and provenance

| Module | Contract | Gen 1 binding | Gen 3 binding today | Notes |
| --- | --- | --- | --- | --- |
| `server/verified_content_cache.py` (83) | [shared-verified-content-cache](shared-verified-content-cache.md) | `server/gen1_bootstrap_receipt.py:13`; `server/gen1_initial_observation.py:14`; `server/gen1_initial_save.py:19` | new | Provenance for RBY canonical sources is `server/gen1_cartridge_profiles.py`, `server/gen1_admission.py`, `tools/verify_canonical_sources.py` (adapter code) |

Row count: 91 module rows (helpers folded into 8 of them; `grep -c "^| \`" docs/FRAMEWORK.md`).

## What is already shared by both generations

Verified consumers on both sides of the same file:

- `server/state.py` `SoulLinkState`: Gen 3 through `server/server.py:1551,3062`; Gen 1 constructs it at `server/gen1_run_config.py:111` but reaches `handle_event` only through the proposal series (P3, P8, P9, P13), because `server/gen1_run_config.py:84-87` refuses every gameplay event in held-service mode.
- `server/adapters/base.py`, `server/pokemon_data.py`, `server/player_keys.py`, `server/save_identity.py` (partially): both adapters and the engine.
- `lua/connector.lua`, `lua/hud.lua`, `lua/game_detect.lua`, `lua/slink.lua`: both Lua clients (Gen 1 legacy and durable, Gen 3).
- `server/protocol.py` `decode_frame`: every wire frame on both paths (`server/server.py:2552`).
- `server/runtime_boundary.py`, `server/manager.py`, `server/server.py`, `server/patcher.py`, `server/bizhawk_launch.py` (Gen 1 bundle only), the presentation helpers and the UPS codec `patch/tools/make_ups.py`.

Not shared by Gen 3 in this tree, although the contracts describe an RR binding: `lua/durable_runtime.lua` and everything under it (`client_session`, `client_journal`, `command_executor`, `control_service`, `state_store`, `platform_storage`, `json_codec`, `wire_protocol`). `lua/rr/runtime.lua` exists only in git history (`120c80d`); the sweep tree has no `lua/rr/`.

## What Gen 1 built that Gen 3 must bind

In the order the binding plan takes them:

1. Durable runtime, journal and run ownership: `server/durable_runtime.py`, `server/durable_dispatch.py`, `server/protocol_journal.py`, `server/staged_state.py`, `server/runtime_lease.py`, `server/runtime_launcher.py`, `server/journal_reader.py`; client `lua/durable_runtime.lua`, `lua/client_session.lua`, `lua/client_journal.lua`, `lua/state_store.lua`, `lua/platform_storage.lua`, `lua/platform_identity.lua`, `lua/json_codec.lua`, `lua/wire_protocol.lua`, `lua/journal_document.lua`.
2. Observation checkpoints on the free-run loop: `lua/gen1_observation_loop.lua` and `server/gen1_observation_runtime.py` (after P10, generalized), `lua/observation_stream.lua`, `server/keyed_inventory.py`, `server/source_receipts.py`, `server/identity_registry.py`.
3. Receipt-verified physical writes: `lua/command_executor.lua`, `lua/staged_command.lua`, `server/held_write_permit.py` with `lua/held_write_permit.lua`, `server/operation_scope.py`, `server/hex_delta.py`, `server/save_file_receipt.py`, `lua/platform_execution.lua` (mGBA profile), `lua/control_service.lua`, `lua/platform_clock.lua`.
4. In-battle instruction authority: `server/instruction_authority.py` and `lua/instruction_executor.lua` with a Gen 3 sibling of `battle_force_authority`.
5. Trade coordinator and driver: `server/trade_coordinator.py`, `server/trade_driver.py`, `lua/platform_saveram.lua`.
6. Patch composition, ROM accounting and hash admission: `server/patch_plan.py`, `server/rom_change_audit.py`, the `upr_*` set if a Gen 3 randomizer path is ever wanted.
7. Recovery: `server/paired_recovery.py`, `server/paired_liveness.py` (unbound by Gen 1 too).

## What is proposed but not yet applied

The proposal series lives in `docs/gen1_reference/proposals/`; nothing in it has been applied to the tree
(`proposals/README.md`, "Apply order"). Verified apply order: P1, P7, P8, P12, P9, P10, P10-verifiers, P10-free-run-live, P11,
P13, P14 (P12 depends on P8; P10-verifiers on P9; P10-free-run-live on P10; P14 on P13 and P10).

| Proposal | What it changes in this table |
| --- | --- |
| P1 | Gen 3 trade staging gate at `gen3_frlge_client.lua:2221-2241` (the standard's own regression); no shared module changes |
| P3 | `server/gen1_semantic_events.py`, already a file; consumed by P8, P9, P12, P13 |
| P4 | `lua/gen1_observation_loop.lua`, already a file; wired by P10 |
| P7 | deletes the Explode refusal in `server/gen1_faint_runtime.py`; the engine selects `force_explode` (`server/state.py:2700-2703`) |
| P8 | faint decided by `_propagate_faint`; `server/linked_death_rules.record_linked_death` unused |
| P9 | acquisition decided by `_handle_capture`; `capture_rules`, `party_grant_rules`, `acquisition_disposition_rules` unused at that site |
| P10 and P10-verifiers | `free_service` mode; `server/gen1_observation_runtime.py` consumes the P4 event; the "Bounded frame scheduling" group becomes deletable; the subsystem map row retires |
| P11 | second instruction-authority binding `rby-battle-force-explode` in `server/battle_force_authority.py` and `lua/battle_force_authority.lua`; live PASSED on R/B/Y |
| P12 | `replace_rival_team` held executor and whiteout detection from the faint signal; both are Gen 1 adapter files on the held-write permit |
| P13 | `server/gen1_engine_bridge.py` call sites; after it, `capture_rules`, `party_grant_rules`, `member_identity_rules`, `acquisition_disposition_rules`, and most of `no_catch_rules` and `linked_death_rules` are unused and are the deletion set |
| P14 | starters under the clauses in every generation (owner decision 2026-09-11); Yellow/Yellow exempt at the Gen 1 adapter, which learns the pair at run creation and restore; `starter_grant` surfaces the engine rejection and the settlement records it |

After the series the Rules group collapses to `server/state.py`, `server/adapters/base.py`,
`server/pokemon_data.py` and the two Gen 1 translator files; that is the state this table should be
re-cut to once root commits.

## Where this table corrects the subsystem map

- `docs/shared-durable-runtime-contract.md` names `lua/rr/runtime.lua` as the RR binding of `lua/durable_runtime.lua`; the file is absent from this tree (git history only).
- The map's closing sentence "Shared infrastructure is already consumed by Gen1, Gen2 and Gen3 workstreams" holds for Gen 3 only for `connector`, `hud`, `game_detect`, `slink.lua`, the engine, the adapter base, `pokemon_data`, `player_keys` and the presentation helpers; Gen 3 binds none of the durable, journal, executor, permit or identity mechanisms in this tree.
- The map's "Protocol and delivery" row lists `json_codec` as shared mechanism; the Gen 3 client has private JSON encode and parse (`gen3_frlge_client.lua:204-239`, `:241-358`).
- `server/upr_pipeline.py` carries a generic name but imports `server/adapters/gen1_rom_scan.py`; it is not in the map's UPR row.
- `docs/gen2/shared_adoption.json`, cited by `EXECUTION_MODEL_PROPOSAL.md` and `SCOPE_CONTROL_PROPOSAL.md`, is not in this tree (unverified: it may exist on `codex/gen2-production`).
- The "Bounded frame scheduling" row is accurate today and retires after P10 (`EXECUTION_MODEL_PROPOSAL.md` section 4, "Change").
