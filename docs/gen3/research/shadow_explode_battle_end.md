# RR shadow: what the six duos actually exercise

Research card gen3-P3-R1; source inspection only, 2026-09-21. No emulator run or code change. Paths below are repository-relative unless explicitly absolute. Upstream source checked locally at `E:/Google Drive/SLink/.cache/pret/pokefirered`, whose HEAD is `c75f352304d529f6ba92d4f74b9cf8b5c3810788` (read-only `git -c safe.directory=… rev-parse HEAD`). `pret:` below means that checkout at that revision. RR executable reachability is a separate question from vanilla source or surviving byte anchors.

## Conclusion and evidence boundary

**Zero `battle_end` is compatible with explode PASS. It is not proof of broken callbacks. But zero ALL non-control hooks is not fully explained by the scenario.** B enters a battle after the observer is installed; a correctly bound reachable battle-start hook should observe that transition. Whether the retained vanilla `CB2_InitBattle` entry is still RR's executed route remains UNVERIFIED. The evidence supports a missing positive-path qualification, not a conclusion that mGBA cannot deliver these hooks (`duo_main.lua:102-120,175-187` under `lua/tests/duo/`; `scenario_explode.lua:45-72`; `docs/gen3_engine_sites.md:78-96`).

The committed receipt reports A=393 and B=903 control fires, registration=19, and the sampled B status at frame 1641 has rejected=0, dropped=0, pending=1, failed=nil. It does not contain final CPU/battle state or every status sample. The earlier faint run was explicitly before the framecount fix and had no STATUS lines; its zero signals are not usable coverage evidence (`docs/gen3/probes/shadow_rr_explode_2026-09-21.txt:1-15`).

## Explode: outcome is earlier than return to the field

1. Runner selects overworld A and prebattle B, disables B fillers, and enables explode mode (`tools/e2e_duo.py:196-200`). Loading the state, one initial frame, filler creation and B identity mutation all precede loading the old client and then the observer (`lua/tests/duo/duo_main.lua:52-55,63-93,102-120`). They cannot retrospectively produce shadow events.
2. B walks Down into the trainer sightline and advances dialogue until its action-select controller appears. Only then does it announce IN_BATTLE and wait for go (`lua/tests/duo/scenario_explode.lua:45-75`). This is a live battle initiation, not a loaded frozen battle. A waits, then directly writes party HP zero and waits for removal (`:34-43`).
3. Old client dispatch calls `M.forceExplodeBattler` for the active battler (`lua/clients/gen3_frlge_client.lua:769-790`). The helper writes Explosion/PP, chosen action/move, communication state, and battle-struct chosen-position/target; it returns without executing the move or calling a battle-return function (`lua/memory_gba.lua:1303-1344`). The client reinforces the commit while PP has not dropped, then settles on HP-zero/inactive/out-of-battle; a timeout can force HP zero (`lua/clients/gen3_frlge_client.lua:2380-2434`). This is distinct from `forceImmediateWhiteout`, which explicitly writes outcome and the return-function pointer (`lua/memory_gba.lua:1347-1377`). Do not attribute that helper to the Variant-3 path.
4. Scenario B waits for move0=153, then mashes A only until `gBattleOutcome != 0`, checks party HP zero, and immediately returns success (`lua/tests/duo/scenario_explode.lua:78-109`). The wrapper detects the dead coroutine before another `emu.frameadvance`, writes RESULT, then calls `client.exit()` (`lua/tests/duo/duo_main.lua:37-40,179-187`). There is **no overworld, inBattle-clear, return-callback, whiteout-completion or save witness requirement**.
5. In vanilla source, setting a loss outcome is separate from the return function: `pret:src/battle_script_commands.c:3401` sets the lost bit; `pret:src/battle_main.c:3906` schedules `ReturnFromBattleToOverworld`; that function clears inBattle and calls saved callback2 at `:3915-3940`. The pinned RR row is anchor **0x08015BCC + capture_offset 4 = hook 0x08015BD0**, flat anchor offset 0x15BCC, bytes `08488068EAF7B8FC70BC01BC`; it is just before final SetMainCallback2, after inBattle clear (`docs/gen3_engine_sites.md:98-114`; `data/games/gen3_rr/engine_signals.json:610` battle_end record). This is neither the outcome store nor the function entry 0x08015B58.

**[INFERENCE, high confidence]** The scenario may finish with battle cleanup still pending. Exact exit-time inBattle/PC for the observed run is UNVERIFIED: the short receipt lacks them. Do not assert that it definitely remained in battle, or that RR necessarily uses the vanilla cleanup branch, solely from PASS.

## Full 19-kind expectation matrix

`+` = required control coverage. `E` = expected semantic path, but exact RR anchor reachability needs physical/caller proof. `C` = conditional/incidental; PASS does not require it. `0` = no directed path in this scenario, **not** a global assertion that unrelated game activity cannot reach it. Explode entries distinguish A/B. The reasons and source chains immediately below apply to every cell; together these tables enumerate every registered kind for every scenario.

| Registered kind | explode A / B | faint A/B | boxsync A/B | trade A/B | ghost A/B | infopanel A/B |
|---|---|---|---|---|---|---|
| frame_control | + / + | + | + | + | + | + |
| battle_begin | 0 / E | 0 | 0 | 0 | C | 0 |
| battle_end | 0 / C | 0 | 0 | 0 | C | 0 |
| faint | 0 / E | 0 | 0 | 0 | C | 0 |
| capture_wild | 0 / 0 | 0 | 0 | 0 | 0 | 0 |
| mon_given | 0 / 0 | 0 | 0 | 0 | 0 | 0 |
| pc_move | 0 / 0 | 0 | 0 | 0 | 0 | 0 |
| pc_deposit | 0 / 0 | 0 | 0 | 0 | 0 | 0 |
| pc_withdraw | 0 / 0 | 0 | 0 | 0 | 0 | 0 |
| pc_box_place | 0 / 0 | 0 | 0 | 0 | 0 | 0 |
| pc_release_begin | 0 / 0 | 0 | 0 | 0 | 0 | 0 |
| pc_release | 0 / 0 | 0 | 0 | 0 | 0 | 0 |
| evolve_species_store | 0 / C | 0 | 0 | 0 | C | 0 |
| trade_begin | 0 / 0 | 0 | 0 | E* | 0 | 0 |
| trade_done | 0 / 0 | 0 | 0 | E* | 0 | 0 |
| trade_evolve_species_store | 0 / 0 | 0 | 0 | C | 0 | 0 |
| map_load | 0 / C | 0 | 0 | C | C | 0 |
| whiteout | 0 / C | 0 | 0 | 0 | C | 0 |
| save | 0 / 0 | 0 | 0 | 0 | 0 | 0 |

The registry inventory and capture contracts are `docs/gen3_engine_sites.md:58-316,360-518`; companion's 19 records are `data/games/gen3_rr/engine_signals.json:581` onward. `poison_faint`, `poison_hp_before`, `borrowed_party`, `nature_change` are **not** among those 19 (inventory exclusions: `docs/gen3_engine_sites.md:318-358,520-548`).

### Per-scenario path and confidence

| Scenario / kinds | Expected fires and source chain | Confidence |
|---|---|---|
| Every scenario: frame_control | Main frame execution -> CallCallbacks control at 0x0800051A. Probe proves this row in the observed explode run; every scenario advances frames (`duo_main.lua:179-187`; `docs/gen3_engine_sites.md:58-76`; receipt :4-14). Not exactly one semantic event per frame promised for all engine states. | High |
| explode B: battle_begin | Live trainer initiation -> vanilla battle transition selects CB2_InitBattle (`pret:src/battle_setup.c:204`) -> pin 0x0800FD9C+0 (`docs/gen3_engine_sites.md:78-96`). Observer installed before scenario. Zero cannot be excused by savestate loading an already active battle. RR may replace the caller/function-pointer route while retaining those bytes. | High for transition; medium for exact RR entry, UNVERIFIED reachability |
| explode B: faint | Engine executes the coerced turn, player-side HP zero should traverse faint processing -> vanilla opcode 0x19 Cmd_tryfaintmon -> playerFaintCounter store -> pin 0x080213C4+4. `pret:src/battle_script_commands.c:339,2831-2905`; `docs/gen3_engine_sites.md:118-136`; scenario :78-109. Host party-HP settlement itself bypasses this function. RR could execute a replacement opcode handler; native faint event expected, retained vanilla pin not proved. | Medium, conditional on actual engine path |
| explode B: battle_end, whiteout, map_load, evolution | Outcome is not cleanup. The harness exits at outcome/HP, before requiring any of these later phases; whiteout pin is completion after its state delay, map_load is specifically CB2_LoadMap2's normal branch, and evolution requires eligible species (`docs/gen3_engine_sites.md:98-114,218-276`; scenario :88-109). | High that none is a required PASS witness |
| faint: faint/battle_* = 0 | A directly pokes party HP (:18-21); B waits for HP0 OR already-removed key (:24-33). Old client uses immediate out-of-battle M.forceFaint (:802-810), whose implementation is host writes (`lua/memory_gba.lua:1275` onward), not Cmd_tryfaintmon. Both then assert party removal/count (:36-48). No battle is started. | High |
| faint/explode A: PC kinds = 0 | Memorialize uses custom OP_MEMORIALIZE compression/zero/swap-with-last, not TryStorePartyMonInBox/SetPlacedMonData/SendMonToPC/ReleaseMon (`patch/src/handlers.c:2125-2145`; client :1822-1825). Lua fallback is also host mutation. Box placement in the rules model does not imply an engine PC-menu hook. | High for named native handler |
| boxsync: PC kinds = 0 | Scenario waits for commanded deposit then statless withdraw (`scenario_boxsync.lua:11-43`). Native OP_DEPOSIT_MON calls CreateCompressedMonFromBoxMon and direct party compaction; OP_WITHDRAW_MON calls CompressedMonToMon and direct box zeroing (`patch/src/handlers.c:2079-2123`). These bypass the six pinned PC frontend/storage-operation sites (`docs/gen3_engine_sites.md:188-216,360-478`). Thus even a successful round-trip does not require any of those six fires. | High |
| trade: trade_begin/trade_done E* | Normal path stages enemy blob -> MB.trade_scene -> patch run_trade_scene -> callnative DO_INGAME_TRADE -> NPC scene -> TradeMons swap. Source chain: client :2248-2258; patch handlers :411-432,1007-1016,1994-2005; `pret:src/trade_scene.c:1776,2276,1054-1084`; pins 0x0805080C+0 and 0x080508C6+4 (`docs/gen3_engine_sites.md:278-296,500-518`). | Medium-high normal route; RR caller reachability still needs receipt |
| trade: starred qualification | **PASS does not prove the scene ran.** Client explicitly supports silent OP_SET_PARTY_MON fallback (client :2224-2239,2276 onward); scenario asserts partner key/maxHP then 600 stable frames (`scenario_trade.lua:25-42`). A fallback can satisfy that oracle without TradeMons. Require a scene-route receipt before demanding these two hooks. Trade evolution additionally needs an eligible received species, not merely a successful swap (`docs/gen3_engine_sites.md:480-498`). Map return need not use the pinned CB2_LoadMap2 branch (:238-256). | High on oracle weakness; conditional fires |
| ghost: all non-control kinds | A drives a six-repetition directional loop, B observes ghost memory/motion (`scenario_ghost.lua:29-49,53-145`). No capture, PC, trade, save or explicit battle action is scripted. A could encounter a trainer/wild battle or warp if movement leaves the intended safe footprint; those are incidental, not required by the movement oracle. No demand for map_load from initial savestate. | High on absence of directed action; medium on environmental exclusions |
| infopanel: all non-control kinds | START -> five Down taps -> SOULLINK -> paging -> B/field unlock (`scenario_infopanel.lua:67-113`), after checking staged pair rows (:31-65). Native panel drawing/script locks are not any of the 19 event kinds. No save selected and no map transition required. | High |

For every scenario the undirected acquisition, release and save zeros follow from the complete scenario action sequences above, not from assuming that every ROM can never perform background work. Initial filler creation does not count: it finishes before registration (`duo_main.lua:63-75,106-120`). Likewise loading an overworld savestate is not execution of the map-load callback under an already installed hook (`:52-55`).

## Can the observer swallow a fire?

* **64 is a between-drains capacity, not lifetime capacity.** S.MAX_PENDING=64 (`lua/gen3/signals.lua:29`); drain hands out the queue and replaces it (`:150-154`). `make_signal_reader` calls the colon drain (`lua/gen3/shadow_run.lua:155-157`), state.poll consumes it (`:287-305`), and duo installs an onframeend poll (`duo_main.lua:120`). One frame-control signal each frame cannot by itself fill this queue if poll succeeds each frame. Overflow requires >64 arrivals between successful drains; overflow sets dropped/failure and subsequent fires stop (`signals.lua:92,107-110,125`). The receipt's 903 continuing control lines and nil failure/zero dropped at its later status are inconsistent with an early permanent overflow explaining all missing kinds (receipt :8-14). Final unsampled failure is not excluded.
* Any fire-time ROM-byte/read/register error latches failure for **all kinds**, not only that one (`signals.lua:92,103-125`). Wrong non-nil callback addresses increment rejected and drop just that fire (`:93-99`). Load-time byte checks/registration failures stop startup, but registration success alone proves neither reachability nor delivery (`:80-89,128-146`). Nil callback addresses are accepted (:96), a weaker identity check than a matching non-nil address.
* Poll errors are swallowed by `pcall(shadow.poll)` with no error report (`duo_main.lua:120`). drain removes the entire batch before per-line formatting/logging (`shadow_run.lua:290-305`, `signals.lua:150-153`): an error during output loses the unlogged remainder. STATUS is only every 600 polls (`shadow_run.lua:287-289`), and the harness never requires shadow health before PASS/exit (`duo_main.lua:179-187`). These are real observability risks, not evidence they happened in this receipt.
* The log uses **poll-time** emu.framecount and a fresh ordinal, discarding the signal's captured frame and nested point table (`shadow_run.lua:245-250,290-305`). Same-frame delivery is assumed in the comment; it is not verified by the logger. That can hide delayed draining and prevents register-point semantics from being reconstructed from SHADOW lines.
* `S.KINDS` is empty, so semantic filters currently cannot explain the missing non-control rows; it logs raw fires (`signals.lua:56,100-101`). Registration is per kind (:130-138); a positive receipt for the one control address does not prove delivery or reachability at the other 18 addresses.
* RR pins prove byte presence, not that the active callback/opcode table references that body. The inventory explicitly says RR bounds are vanilla references, not a proved RR extent (`docs/gen3_engine_sites.md:96,116,136`) and requires live caller coverage (:548). Priority investigation: actual battle-start callback and battle opcode 0x19 target, before blaming mGBA globally.

## NOT VERIFIED / next falsifiers

1. Exact final inBattle/callback2/gBattleMainFunc/outcome/PC for the observed explode run; record these before RESULT, or extend a separate lane to wait for field return. Do not change the existing outcome oracle's meaning silently.
2. RR caller/opcode-table reachability of battle_begin and faint pins. Compare registered entry vs actual transition target on the coordinator's lane; add hook-local raw hit counters before identity/byte/queue validation to separate non-delivery from rejection.
3. Native trade scene versus silent fallback for a passing trade duo. Require route-tagged receipt before interpreting absent trade hooks.
4. Full hook-failure/poll-error/overflow status at exit; final drain and error accounting are not currently part of RESULT. A synthetic burst of 65 signals is the queue falsifier; one control per frame plus a rare second kind should never overflow.
5. No physical proof here that all 19 pins are reachable, and no new runtime claim for faint's obsolete pre-framecount-fix receipt. No tests, ROM modification, emulator or commits on this research card.
