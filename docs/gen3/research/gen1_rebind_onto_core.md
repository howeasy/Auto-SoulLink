# Gen 1 rebind onto the shared core: owner handoff

**Source pin: `690e1c63`.** All file:line references below refer to that commit; re-pin them against the pureRGB owner's checkout before implementation. This card writes documentation only: no code, emulator, or release evidence. Gen 1/pureRGB owns `lua/gen1/*`; coordinate any additional core seam with the core owner. The portability boundary remains `docs/shared_runtime.md`: share lifecycle/transport policy, retain generation-specific readers, writers, hook sites, banking, storage, trade and panel facts.

**Prerequisite:** do not adopt the core at this pin as already accepted. REV5 still rejects (a) a wrong-pair ACK consuming the valid pending alias, and (b) a first-hello quiet timer absorbing a next-frame gift. The coordinator accepted both and queued their fixes. Obtain the subsequent accepted core/client cut and rerun those falsifiers. REV4's RR trade FSM is separately rejected; Gen 1 keeps its existing trade implementation rather than borrowing that FSM. Earlier R1 attempted-write counting and R2 save-epoch disposal were accepted; references: `lua/core/session.lua:132-138,251-283`, `lua/gen3/client.lua:715-733,806-826`, `lua/gen3/writes.lua:13-16,43-45`.

## 1. Extraction and state ownership

Delete each duplicate only after its binding below runs through the production Gen 1 World. This is not a deletion of the game reducer.

| Gen 1 client range | Replacement / what remains local |
|---|---|
| `lua/gen1/client.lua:153-167` state initialization | Core owns seq/frame/hello, validation state, resolved areas, config, pending-safe, identity and deferred queues. Driver retains known keys, box cache, pending acquisition, rival/battle observations, ROM content, static encounters, ball/HUD latches, trade/panel/APEX/Transform state. |
| `:171-182` send/envelope | Use `Session.send(event,fields)` exclusively; no second sequence counter. Preserve explicit `json.array` payload lists. |
| `:317-358` validate/pause/reset dispatch | `Session:validate`; retain `game_is_live` at `:310-315` and driver reset cleanup described below. |
| `:361-365,371-440,442-445` cancellation, alias resolution, HUD color | Core generic cancellation/color handling and `Identity`. Reducer callers must be rebound before removing their helpers. |
| `:480-596` command switch | Delete generic branches only; retain game-specific handlers in `driver.commands` (§2). |
| `:717-822` deferred executor loop | `Deferred.new{exec,...}`; retain Gen 1 storage/base-stat operations behind closures (§3). |
| `:1512-1556,1558-1592` hello/tick | Extract pure field builders; core transmits envelopes. Preserve cartridge content, panel/SFX capabilities, snapshots and timing rules. |
| `:1794-1884` frame loop/stop | `Session:frame_end`/`:stop`; move embedded services into driver hooks. Keep synchronous registration logic from `:1768-1791` in `driver.start`. |

Use one identity owner: `self.key_alias` becomes `identity.pending`; `self.retired_alias` becomes the stable `identity.retired_alias` table. Do not retain shadow aliases that diverge after ACK/reset. Reducer departure sites (`client.lua:1067,1112`), acquisition alias exemption (`:1287`), and APEX collision membership (`:1443`) must call/read that same identity instance. Core resolver/evidence/latches: `lua/core/identity.lua:32-67,76-111,115-137`.

The public shapes differ: old `client.deferred` is an array; core `session.deferred` is an object with `items`, and battle flush replaces its array. Update harness/debug accessors or provide a read-through facade; never maintain independently mutable queue copies. Preserve current `start/frame_end/stop`, command and test-driving entry points deliberately (`gen1/client.lua:1768-1884`; `core/session.lua:9-25,73-75`).

## 2. Gen 1 driver table

Core construction contract: `lua/core/session.lua:16-26`; production Gen 1 composition root: `lua/gen1/entry.lua:300-380`. Continue constructing the existing Gen 1 reads/signals/writes/boxes/ROM/trade/panel parts, then construct Identity, Deferred and Session. Do not replace `bank_safe_io` or the flat CartRAM door with GBA I/O (`entry.lua:274-292,334-358`).

| Driver member | Gen 1 source and binding obligation |
|---|---|
| `frame()` | `io.framecount`, currently `client.lua:1795`. |
| `read_party()` | Existing `current_party`; preserve unreadable-as-nil, slot, key, nickname bytes and moves for identity evidence. Do not translate unreadability to an empty party. |
| `game_is_live()` | `:310-315`: readable party; player ID zero plus empty party is pre-game. |
| `save_cleared()` / `on_reset()` | `:334-348`: player ID zero invalidates the save epoch; clear pending acquisition and panel lease. Core clears aliases/held pre-hello events. Retain game-specific APEX/Transform/trade reset cleanup where its own lifecycle requires it. |
| `in_battle()` | Convert Gen 1 numeric battle state to a boolean explicitly. Lua numeric zero is truthy. |
| `checkpoint_ok()` | Gen 1 `safety.check(write_checkpoint, io)`, not Gen 3's snapshot/predicate. Retain native-trade/buffer ownership exclusion from the deferred gate. |
| `hello_ready()` | Live **AND (checkpoint OR battle)**, plus pureRGB internal-version hold. Preserve mismatch handling at `:1812-1825`; this is not checkpoint-only. |
| `hello_fields()` | Build `:1543-1554` payload: identity, foundation/kind/hash, party/PC, ball latch, badges, location, `rom_content`, and per-cartridge panel/ABI/SFX capabilities. No transmission/HUD effects; see §5. |
| `tick_fields()` | Retain `:1583-1591`, including pureRGB `safari_type`, battle/enemy enrichment and explicit empty arrays. Keep field building separate from area/HUD observation. |
| `start()` | Return Gen 1 signal object built with the synchronous callbacks and conditional trade-service site at `:1768-1791`; core must not register those callbacks as delayed frame events. |
| `on_signal(sig)` | Keep the existing Gen 1 reducer (`:910-1251`) and settlement state (`:1253-1370`), including complete acquisition/name windows, daycare and NPC-trade slot rules. |
| `frame_hooks` | Rival-window service, then `settle_pending_change` (`:1846-1847`), then any post-hello area/HUD observation. Core performs identity observation after these hooks. Baseline ownership must follow the corrected acquisition contract, not a copied rejected quiet-timer heuristic. |
| `pre_pump()` | Panel service with its protected error handling (`:1796-1801`); after rebind validation precedes it. Poll completions even when posting is disabled; gate new writes. |
| `after_receive()` | Existing `trade_tick` (`:1877-1878`), preserving its protected invocation and receptionist lifecycle. |
| `on_disconnect()` | Clear panel state (`:1808-1810`), preserving connector drop semantics. Do not create a replay queue across disconnected sessions. |
| `play_sound(id)` | Existing config/capability-aware `request_sfx_local` (`:451-477`), including coalescing and semantic mapping. Gen 3 m4a/native opcodes are not Gen 1 implementations. |
| `party_borrowed()` | No equivalent RR borrowed-party mechanism was found here. Omit or return false unless the Gen 1 owner identifies one; borrowed panel tile storage is not a borrowed Pokémon party. |
| `battle_write(...)` | **Timing bridge required**, not a direct port; see §3. |

`driver.commands` must preserve these intercepts (`gen1/client.lua:483-596`):

- Force-command known-key marking, including the unreadable-party path (`:483-505`); generic queue routing alone loses this echo/acquisition suppression.
- `replace_rival_team`; `pending_keys` for APEX collision avoidance; accepted-alias known-key cleanup; `config` clearing already-queued SFX when disabled (`:526-556`). Generic core ACK/config handling must still run when appropriate: command handlers return **true only when they own the entire response**.
- `trade_mask`, `trade_offer_ack`, receptionist `show_menu`, `apply_trade`, `link_panel`, and deliberate `ghost_pos` ignore (`:568-594`). Keep Gen 1's disabled-trade behavior and token/generation lease; do not substitute RR's no-trade branch.
- Core owns default prompt cancellation. A native/receptionist handler that already replied must consume the command, including failure, to avoid two cancel ACKs (REV MINOR1).

## 3. Battle timing and write doors: migration blockers

**Gen 1 battle writes must stay synchronous.** `on_battle_loop_head` (`gen1/client.lua:1375-1417`) applies active faint/Explosion only at the proven instruction window, with `active_faint_guard`; ordinary bench faints land there too, and special/link-battle bench work goes to the checkpoint. pureRGB `on_battle_loop_no_move` additionally redirects PC after a successful write (`:1424-1432`). Core's default flush invokes `game.battle_write` at frame end (`core/session.lua:155-187,399`): calling those Gen 1 writers there is invalid.

Agree one bridge before cutting over: retain synchronous callbacks and one queue owner, with an explicit core-owned synchronous drain seam, or an audited adapter whose frame-end battle callback only holds while the instruction hook drains the shared queue. The frame-end path must never replay a cached hook point as current proof. Preserve the no-move PC redirect and ensure the battle-end handoff runs once. Do not import Gen 3's active-battler-until-switch-out policy into Gen 1. Core's alias migration must reach whichever single battle queue is chosen.

Keep synchronous APEX preflight/commit, Transform and HP-low handling (`gen1/client.lua:1439-1509`) generation-specific. Their register/ROM-bank/WRAM-bank evidence is not a frame-end event payload.

Deferred executor binding (`gen1/client.lua:717-822`; `core/deferred.lua:7-27`):

- `arm/disarm`: preserve the Gen 1 overworld window and original checkpoint gate. `faint_slot` uses Gen 1 HP/status semantics; no Gen 3 `+0x56` or little-endian fields.
- `deposit`, `memorialize`: call existing Gen 1 box movers with validated physical key/slot hint; memorial index remains the Gen 1 final box. `withdraw`: resolve the matching species' ROM base stats before calling Gen 1's alias (`gen1/boxes.lua:534-537`; client withdrawal `:774-780`).
- `stats_of`: snapshot before mutation; `rescan`: refresh boxes/known keys after success so self-authored moves cannot become user PC events.
- `write_count`: add an **attempt counter incremented before external byte I/O**, shared across System Bus and the CartRAM door. Counting completed log records is unsafe (REV2 R1). Gen 1 currently logs after loops (`gen1/writes.lua:70-86`; `entry.lua:343-357`); both paths need the counter. Never count only WRAM while box writes bypass it through CartRAM.
- Retain WRAM-bank refusal, exact record/name layouts, CartRAM checksum behavior, and panel's explicit no-CartRAM rule (`writes.lua:74-82`; `entry.lua:347-349`). Do not weaken these to make shared tests green.

## 4. Deliberate deltas and their falsifiers

REV labels below identify the coordinator-accepted findings; commit/test references make the changes checkable. The last two REV5 boundary repairs are prerequisites, not silently accepted behavior at this pin.

| Delta Gen 1 acquires | Evidence / gate impact |
|---|---|
| Cache snapshot before deposit, `stats_cache` **after confirmed success** | Gen 1 sends before at `client.lua:761`; core sends after at `core/deferred.lua:156-170`. Accepted extraction delta/PLAN R9. Add production-Gen1 ordering and refusal checks; no cache on failure. Existing HUD tests `test_gen1_client.py:1390,1413` are insufficient. Do not invent `box_mon_done`. |
| Pre-hello semantic hold and save-epoch disposal | REV MAJOR1, REV2 R2; core `session.lua:90-105,132-138,300-307`. Old Gen 1 sends whenever TCP is connected (`client.lua:171-180`). Test exact keys/counts before hello, disconnect disposal, reset disposal, same-frame hello+gift and reconnect between write/hook; tests `test_core_session.py:592-616` are only part of the matrix. |
| Executor exceptions: safe retry / uncertain failure / already answered | REV MAJOR5, REV2 R1; core `deferred.lua:133,207-225`, Gen3 attempted counter `writes.lua:13-16,43-45`. Preserve bounded clean-error retries; no blind retry after attempted mutation; no second terminal reply after completed result. Existing Gen 1 refusal tests do not cover thrown sink errors. |
| ACK migrations need this client's exact-pair alias and sticky evidence | REV MAJOR6 → REV2/3 R3; core `session.lua:251-283`, identity `:43-67`. Changes Gen 1's old ACK cleanup-only behavior (`client.lua:526-545`). Replay false is not rejection. Require lost/twin/unrelated/wrong-pair tests, including wrong ACK followed by correct ACK; **current pin still consumes the alias too early**. |
| Hello reports without learning once a baseline exists | REV3/5 R4; Gen 1 `client.lua:1524-1526` always seeds keys. Initial seeding remains necessary; established baselines must not swallow unresolved acquisitions. Keep Gen 1's pending acquisition/AskName evidence and test first-hello+next-frame gift; current Gen3 timer remains rejected. |
| Opposing move cancellation; memorial dedupe | REV MINOR2; core `deferred.lua:74-89` replaces Gen 1's raw append (`client.lua:505-507`). New desired command survives; only queued opposite is removed. Add both directions and duplicate last-mon memorial tail retries. Preserve full-party/last-party retry semantics (`test_gen1_client.py:1798,2889,2912`). |
| Native/sound posting eligibility | REV BLOCKER: all new posting/arming must respect writes enabled, connected, hello sent; completion polling remains possible. Gen 1's config/capability gate is additional, not replaced. Test queued SFX/panel across pause and config-off; `test_gen1_client.py:1178,1549` protects queued cancellation and terminal-batch coalescing. |
| Validation before `pre_pump` | Old Gen 1 panel first at `client.lua:1796-1801`, validation later at `:1827`; core validates first (`session.lua:339-344`). Fifth invalid validation must prevent same-frame posting; one valid validation resumes intact queues. `test_core_session.py:779,799`; Gen 1 `test_gen1_client.py:670,720`. The misleading “queued before pause still lands” test waits for revalidation; it does not authorize paused writes. |

Static guards also change location, not requirements: `test_client_acks.py:45-59` and `test_client_invariants.py:200-216` currently search reply literals only inside the Gen 1 client. Rebind them to the composed production graph or behavior; retain every ACK/refusal assertion. Rerun `test_client_upvalue_scope.py:73,108` and the other client-invariant scans after moving lexical scopes.

## 5. Hello, area and HUD separation

**Source correction:** Gen 1 at this pin has `send_hello`, not `hello_fields`. It does **not** currently emit `area_enter` from its hello path. That event and the encounter banner/SFX are in `send_tick` (`gen1/client.lua:1564-1577`); first-ball acquisition announcement is at `:1580-1582`. REV MAJOR1's actual offending `hello_fields -> check_area -> send` was in Gen 3. Do not introduce that same side effect during Gen 1 extraction.

Keep `hello_fields` limited to the envelope-free snapshot. Move area-change emission, NEW ENCOUNTER HUD/SFX and first-ball acquisition announcement into the post-hello observer/driver tick orchestration. Preserve the exact guards: server areas seeded, ball gate active, ordinary field state, unresolved area, and the cartridge's own wild table; gift/static/demo/ghost exclusions remain in the Gen 1 reducer. A hello that already has balls is a resume: log/mark the latch, **no new Nuzlocke banner** (`:1516-1522`). Load/cache `rom_content` and `wild_maps` without transmitting another event (`:1527-1541`).

Keep these exact behavioral tests: `test_nuzlocke_banner_not_shown_at_a_hello_that_already_has_balls`, `test_nuzlocke_banner_fires_once_on_the_first_bag_received`, `test_new_encounter_banner_on_area_enter_via_tick`, and the gift/static/demo/ghost/mid-battle negative controls in `tests/unit/test_gen1_client.py`. Add a semantic event simultaneous with hello and verify the complete event sequence, not merely its first two names.

## 6. Falsifier/gate handoff (owner runs later)

No lanes were executed by this research card. Use the owner's Python environment and the accepted shared-core cut; zero unexplained skips/xfails/deselection remain required for release (`docs/shared_runtime.md`, release boundary; `tools/verify_gen1_release.py`).

```powershell
$rebindTests = @(
  'tests/unit/test_gen1_client.py', 'tests/unit/test_gen1_purergb_client.py',
  'tests/unit/test_gen1_identity_and_collisions.py', 'tests/unit/test_gen1_statics_and_trades.py',
  'tests/unit/test_gen1_writes.py', 'tests/unit/test_gen1_boxes.py',
  'tests/unit/test_gen1_trade_overlay.py', 'tests/unit/test_gen1_panel.py',
  'tests/unit/test_gen1_panel_capability.py', 'tests/unit/test_gen1_panel_tiles.py',
  'tests/unit/test_core_session.py', 'tests/unit/test_core_identity.py', 'tests/unit/test_core_deferred.py',
  'tests/unit/test_client_acks.py', 'tests/unit/test_client_invariants.py',
  'tests/unit/test_client_upvalue_scope.py', 'tests/unit/test_mixed_foundations.py',
  'tests/unit/test_protocol_conformance.py'
)
python -m pytest @rebindTests -q -p no:randomly
python tools/lua_syntax_check.py
```

Add the missing **production Gen 1** falsifiers before removing its copies: byte-two failure on both WRAM/CartRAM; pre-mutation bank/pointer refusal then safe retry; cache-after-deposit; valid/replay/wrong-pair ACK sequences with departure/twin latches; pre-hello reset/disconnect; first-hello and reconnect gift timing; paused panel/SFX jobs; active and bench writes at the actual synchronous hook; pureRGB no-move redirect; APEX/Transform evidence; exact trade lease/cancel/completion behavior. Core-only fakes do not prove the binding.

Run the following individually on the serialized emulator lane, with independent save/readback oracles:

| `python tools/e2e_duo.py --game gen1_new --scenario ...` | Why / pinned oracle |
|---|---|
| `link_new`, `deadzone_new` | Acquisition/area timing; `tools/e2e_duo.py:2698,2730`. |
| `pc_ops_new`, `whiteout_new` | Ordering, stats/cache, rebuild, idempotence/persistence; `:3141,3370`. |
| `linked_faint_active_new`, `linked_faint_bench_new`, `explode_new` | Synchronous battle writes; `:2779` and scenario-specific explosion oracle. |
| `reconnect_new --wrong-save <qualified-second-OT-save>` | Same-save/new-save identity, zero writes on refusal; `:2288-2306,2406`. The option requires a real qualifying path; omission does not cover wrong-save. |
| `trade_new`, `trade_decline_new` | Native lease/prompt/cancel/readback; `:3924` and registry at `:98-118`. |
| `ball_gate_new`, `soft_reset_new` | Startup banners, before-ball protection and save-epoch boundary; registry `:92-110`. |

Those vanilla lanes do not qualify pureRGB. Re-run the pureRGB owner's admitted-artifact lane matrix with its own manifests/probes, including CGB/WRAM-bank/no-move stress and identity refusal. **U8 is a pairing rule:** pureRGB pairs only with pureRGB and compatible artifact kind (`docs/purergb/PLAN.md:35,246`). Preserve foundation/kind/hash and save-version admission; run `test_mixed_foundations.py:289,303` and `test_gen1_purergb_client.py:873`, then exercise mixed foundation and clean/overlay refusal through the Manager/server with unchanged persisted bytes. U8 is not the name of a unit-test file.

Finally run the full Gen 1 release verifier and the pureRGB owner's current release gate, plus extracted-zip boot. `tools/make_release.py` already lists `lua/core/{session,identity,deferred}.lua` in `_LUA_CORE`; verify dependency closure rather than assuming source-tree success means packaging success. There is no separate `verify_purergb_release.py` in this pin.

## 7. Risk order and implementation sequence

1. **Freeze accepted dependencies first.** Resolve current REV5 alias/timer boundaries; record the core pin and the pureRGB owner's actual Gen 1 cut. Preserve a rollback bundle and fixture hashes. Do not merge the rejected RR trade FSM into Gen 1.
2. **Add binding falsifiers and the attempted-write counter.** Include CartRAM before changing exception behavior. Characterize current Gen 1 wire/HUD output; mark intentional deltas individually instead of updating snapshots wholesale.
3. **Agree the synchronous battle bridge.** Prove active/bench/no-move/APEX/Transform hook timing before sharing queue ownership. Frame-end equivalence is the highest-risk false assumption.
4. **Extract identity and deferred mechanics behind current Gen 1 entry.** Keep record codecs, banking, ROM readers, box serializers and native protocols intact. Then move session/transport orchestration, preserving custom command fallthrough/consumption.
5. **Separate hello snapshots from observation.** Run exact-key hello/acquisition/reset tests, alias lifecycle and fifth-invalid-frame posting tests before enabling the new root in production.
6. **Gate every admitted family and artifact.** Unit → serialized duo/physical hooks → pureRGB U8 and its lane matrix → full verifier → packaged boot. A green shared-core suite, a renamed method, or vanilla-only receipts cannot close pureRGB behavior.

Primary risks: duplicate ownership of mutable state; synchronous hooks silently delayed; SRAM mutation invisible to error classification; ACK evidence weakened; acquisitions learned by hello; callback ordering reviving a paused native post; native trade/panel latches lost on reset/disconnect; lexical/upvalue/static-guard breakage; wrong foundation/content/version advertised; and pending core fixes being mistaken for accepted abstractions.
