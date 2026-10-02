# Gen 4 G2 producer plan (oracle + physical receipt plan per producer group)

Closes the last G2 clause of `docs/gen4/PLAN.md:243` ("Every required producer has an independent oracle and physical receipt plan"). Status date 2026-10-01, branch `claude/gen4-support-framework-dfd5e2` @ `2ee772b3`. Nothing here is a PASS; every row is SOURCE-only, planned or blocked.

## 0. Inputs and conventions

- **Inventory:** `data/games/gen4_hgss/acquisition.json` (script_sites 61, c_producers 25, npc_trade_records 13, runtime_branches 27, unresolved 11, out_of_scope_commands 5) and `data/games/gen4_hge/acquisition.json` (script sites byte-identical to HG per the NARC member proof, c_producers 18, replaced_non_producers 7, vanilla_c_producers 25 with a hge status, unresolved 12). A site id such as `scr_seq_0843_T20R0101:169` is the key into `script_sites[].id`.
- **Detector:** the client polls, it does not hook (`docs/gen4/reviews/DECISIONS_2026-10-01.md`, performance ruling: zero steady-state hooks). `lua/gen4/poll_events.lua` runs set diffs only on a SETTLED snapshot (header `poll_events.lua:27-38`, `settled()` at `:267`). Admission is `lua/gen4/entry.lua:127` (`Entry.admit`), hash-first; it does not detect events.
- **Independent oracle** = a reader that shares no code with the reducer or `lua/gen4/pk4.lua`. Default oracle O1: after a native SAVE, decode the battery with `server/adapters/gen4_codec.py` (`parse_save` `:509`; `Gen4Save.party/boxes/pc_meta` `:451-493`; `decode_plain` `:285` gives key, species, level, `is_egg`, `egg_location`, `met_location`, `met_level`, `ot_name`, `otid`, `ball`, `hp`). O2 = the pret script/NARC record named in `acquisition.json` (species/level/otId/OT name), which comes from the generator, not the client. O3 = an emulator-side read of RAM that the reducer does not consume (e.g. the probe's own foe PID read, `lua/tests/probe_gen4_*.lua`).
- **Event vocabulary** (wire set `tests/unit/protocol_schema.py:29-70`): `capture` (`gift:true` = gift namespace, `in_box:true`), `no_catch`, `party_to_box`, `box_to_party`, `release`, `key_change{reason:"npc_trade"}` (`:61`, reasons `:107`), `faint`, `whiteout`.
- **Tooling reused:** `tools/gen4_routes.py` (`plan`, `run --target grass|pc`, `--errand pokegear`, `:1048-1115`; pack `route_legs` in `data/games/gen4_hgss/profile.json`: boot_continue_to_overworld, open_start_menu, save_confirm_until_saved, pc_*, run_from_wild, fight_until_enemy_faints, exit_battle_to_overworld, soft_reset_in_fight_menu). `tools/gen4_synth_save.py party2` (clone party slot 1; SYNTH sidecar; docstring `:1-30`). Lanes: `C:/slink/g4/<lane>`, up to 2 concurrent functional lanes (DECISIONS "emulator lanes").
- **SYNTH rule** (owner 2026-10-01 "Synth tests ARE allowed"): any row may use disclosed SYNTH setup; receipt carries `setup: SYNTH` + sidecar sha256; the behaviour under test (script, hatch, deposit, save, reload) stays native. New SYNTH kinds listed in section 4 do not exist yet.
- **What already exists on HG/hge:** a wild battle is reachable from a starter-only save (C1-9 route; `C:/slink/g4/route/route_leg2_battle_settled.State`, hge `C:/slink/g4/faint2/p2hge_leg5_battle_settled.State`); the Cherrygrove PC route (`edf3d5f4`) is offline-built and its last live run FAILED at leg 4 (`C:/slink/g4/route_pc/route_pc_receipt.json`: `pc_not_launched taskman 0 m69 (11,13)`; `C:/slink/g4/route_pc_run1.txt`).
- **Estimated lane time** is wall time per receipt at 300% route-development speed (PLAN §7), excluding tool authoring; "tool" lists new code first. All estimates are coordinator-grade guesses (no measured baseline except route leg 4 = 29.9 s wall, `route_pc_run1.txt`).

## 1. Required vs limited scope (PLAN §5 limits `:302`, D10/D11/D14, `:260`)

| Scope | Producers |
|---|---|
| **REQUIRED for the RC** | wild capture (party + PC-full), starter, GiveMon gifts, eggs + hatch (daycare egg O-15), loans (as gifts), executed NPC exchanges (`key_change`), static encounters (gift namespace, D10), PC deposit/withdraw/release (box sync), hge replaced producers (section 3) |
| **Limited, D14** | Bug Contest result, Safari, roamers: SOURCE + MODEL (lupa) + zone mapping only; no live-play receipt |
| **Out of scope / unobservable** | Mystery Gift (14 sites, `acquisition.json out_of_scope_commands.MysteryGift`), Pal Park (`scrcmd_12.c:68`), GTS/Wi-Fi/link trade, Pokewalker. Never a required receipt; see the polling flags in section 5 for what the reducer does if one occurs |
| **Not producers** | `not_acquisition` rows: trainer parties (`trainer_data.c:347-427`), wild enemy generation (`encounter_check.c:1355`), tutorial (`battle_setup.c:128`), fossil var fill `GetFossilPokemon` (2 sites), `NPCTradeExec` (11 sites, 1:1 with LoadNPCTrade). Negative-control rows only |

## 2. Vanilla HG / SS producers

SS physical cells use the owner SS save (D4 met 2026-10-01: `C:/slink/g4/saves/ss_DDDD_25944.SaveRAM`, decoded `663c5f3d`); script data is shared pret source, with HG/SS differences kept in 3 `version_branch` WildBattle sites (`Ho-Oh/Lugia D17R0110:73, D40R0107:85`, `T03:396` Latios/Latias) and the 27 `runtime_branches`.

| # | Producer (file:function, sites) | Event and `poll_events` path | Independent oracle | Physical receipt plan (route, tool, est.) | Status |
|---|---|---|---|---|---|
| V1 | Wild catch, party: `src/battle/battle_command.c:7003` `Task_GetPokemon`/`Party_AddMon`. Not a script site | `capture` (area = battle area). Encounter latch `end_battle` `poll_events.lua:163` then `settled()` foe match `take()` `:361-385`, `foe_match` | O1: new key with `ot_name`/`otid` = player, `met_level`, `met_location` = area, `ball`; O3: foe PID read from battle RAM by the probe before the catch; resolves the open OTID question (DECISIONS "Capture identity": PID match, OTID = foe's or player's) | Grass leg (`gen4_routes run --target grass`) reaches the battle without balls. Throwing needs balls: bag layout not measured (`profile.json:2404`, array id only `:2984`). Tool: SYNTH `bag` kind. Then native catch, SAVE, cold reload. ~12 min lane | **BLOCKED**: no balls, no bag SYNTH, no bag read for `has_pokeballs` |
| V2 | Wild catch, party full: `battle_command.c:7025` `PCStorage_PlaceMonInBoxFirstEmptySlot` | `capture{in_box:true}` `poll_events.lua:372-376` | O1: key in `boxes()` and not in party; `pc_meta()["modified"]` set | As V1 plus a full party. Tool: SYNTH `party6` (extend `party2`) | **BLOCKED** (V1 + new kind) |
| V3 | Wild encounter ends without a catch (negative path) | `no_catch` `poll_events.lua:406-421`; needs `st.has_pokeballs` (`:415`) | O1: boxes/party unchanged across the battle; O3 foe PID | Grass leg + `run_from_wild`; the no-balls control (no event) is runnable now, the positive no_catch needs `has_pokeballs` (V1 blocker). ~8 min | planned (negative control runnable now) |
| V4 | Starter: `src/choose_starter.c:81` `CreateStarter`; script `ChooseStarter` `scr_seq_0843_T20R0101:169` (candidates Chikorita/Cyndaquil/Totodile, L5) | `capture{gift:true}`, area = current area `:380-384` | O1: key + `met_location` (Elm's lab) + species in the 3 candidates, level 5 (O2: `c_fact_checks.starter_level`) | **Cannot be reached from the owner saves**: they already hold the starter, so the first settled view learns it silently (`poll_events.lua:284`). Needs a new-game route: boot, intro, naming, Elm's lab choice. Tool: new route legs (not in `route_legs`). ~30 min lane (est.) | **BLOCKED**: no pre-starter save, no new-game route |
| V5 | GiveMon gifts: `script_pokemon_util.c:41`, `scrcmd_party.c:31`. 13 sites: 7 literal (Tyrogue `D38R0104:37`, Dratini `D44R0103:351`, Dialga/Palkia/Giratina `D51R0201:697/704/709`, Tentacool `T24PC0101:56`, Eevee `T25R0401:34`), 5 `candidates` (fossil `T03R0101:359`, Celadon `T07R0501:479`, Saffron `T11R0701:178`, Goldenrod `T25R1101:984`, `T25SP0101:582`), 1 `unresolved` cross_entry (`T01R0301:629`) | `capture{gift:true}` `:380-384` (no foe) | O1 + O2: species = literal, level = literal arg, `met_location` = site map. Candidates: species in the candidate set | Story-gated; no flag/position SYNTH. Pick one representative per class (Eevee literal, one candidate site) since the C path is shared; the other sites are covered by the SOURCE join. Tool: SYNTH `place` (Location + script flags). ~15 min each | **planned**, blocked on the `place` kind |
| V6 | Eggs: `scrcmd_party.c:93` `ScrCmd_GiveEgg` (3 sites `T22PC0101:79/91/103` Mareep/Wooper/Slugma); `scrcmd_pokemon_misc.c:1071` `GiveTogepiEgg` (`T22FS0101:53`); `get_egg.c:640` `GiveEggToPlayer` (daycare, `GiveDaycareEgg` `scr_seq_0265:101` listed in out_of_scope_commands) | Receipt: no event (eggs wait for hatch, `poll_events.lua:365`). Hatch: `capture{area_id:"gift_daycare", gift:true, is_egg:false}` `:298-310` (O-15) | O1 twice: before hatch the key is an egg (`is_egg`, `egg_location`); after, same key, `is_egg` false, `met_location` set | Hatch is the testable half: SYNTH egg (cloned mon, `is_egg` bit, egg-cycle byte = friendship `decode_plain:300` set to 1), then walk steps to the native hatch scene. Tool: SYNTH `egg1`. ~10 min. GiveEgg/Togepi script receipt stays SOURCE (story-gated at Violet) | hatch **planned** (tool); script sites SOURCE-only |
| V7 | Loans: `npc_trade.c:70` `NPCTrade_MakeAndGiveLoanMon`; `GiveLoanMon` `R35R0101:61` (Spearow, record 7), `T24R0201:47` (Shuckle, record 6) | `capture{gift:true}` (loan = acquisition, `zone_policy.loan`, D11). The loan returning vanishes without the PC: `vanished` note only `poll_events.lua:401`, never a release | O1 + O2: OT name (Webster/Kirk) and `otid` from the NARC record (`npc_trade_records[6,7].record.otId`) | Story-gated (Route 35 gate house; Cianwood). SYNTH `place`. ~15 min | **planned**, blocked on `place` |
| V8 | NPC exchange: `npc_trade.c:154` `NPCTrade_ReceiveMonToSlot`; `LoadNPCTrade` 11 sites, 10 reachable identities (ids 0,1,2,3,5,8,9,10,11,12), same-species Steelix (5) and Pikachu (10) | **`key_change{reason:"npc_trade"}`**, but the reducer only emits the note `slot_replace:old>new` (`poll_events.lua:340-355`, test `test_gen4_poll_events.py:194-207`). The wiring is a client card (DECISIONS "D11 npc_trade": `identity:begin_alias`, `box_generation()`, `rescan_boxes()`) | O1: old key absent, new key in the SAME party slot, `otid`/`ot_name`/species equal the NARC record (O2, `a/1/1/2`, generator), held item; same-species case: keys differ | Needs an ask-species mon in the party. Tool: SYNTH `species` (rewrite the party2 clone to the ask species incl. checksum/tail). Walk to the NPC (Violet record 0 `T22R0601:40` is nearest; extend `plan_errand` for a house visit); decline = negative control; loan = `V7`. ~15 min per case (replacement, same-species, decline) | **BLOCKED**: event not emitted (client card) + SYNTH kind. Reducer half is tested offline |
| V9 | Special gift: `scrcmd_pokemon_misc.c:1139` `GiveSpikyEarPichu` (`D36R0101:1910`, L30 form 1) | `capture{gift:true}` | O1: species Pichu, form 1, level 30 | Reachability not verified (event gate unknown). SOURCE only | SOURCE-only |
| V10 | Statics: `WildBattle` 21 sites (18 literal, 3 version_branch); catch through `Task_GetPokemon` | Should be gift namespace (`zone_policy.static`, D10). **Reducer cannot tell**: no static table, so it emits an ordinary area capture and marks the area resolved (`poll_events.lua:263-266, 372-378`). `cfg.gift_area` only suppresses `no_catch` (`:415`) | O1 + O2 (species/level/area from the site row) | Needs a client classifier keyed on (area, species, level) from `script_sites[kind=static]`, then one physical: Route 36 Sudowoodo or Snorlax (needs balls + flags). ~20 min | **GAP** (section 5 F2), then planned |
| V11 | PC moves: `pokemon_storage_system.c` helpers; deposit/withdraw/release by the player (infrastructure) | `party_to_box`, `box_to_party`, `release` (`poll_events.lua:313-330`, `:392-404`); needs `pc_active` | O1: key moved party to box, `pc_meta()["modified"]` set, key absent on release; counter advanced | Existing `pc_*` legs + `--target pc` with `party2` SYNTH (`13844937`, `edf3d5f4`). ~10 min | **IN PROGRESS** (live run FAILED at leg 4, `route_pc_receipt.json`) |
| V12 | Daycare withdraw: `get_egg.c:156` `Save_Daycare_MoveMonToParty`; script `RetrieveDaycareMon` `scr_seq_0265:444` | None. Deposit: `vanished` note (no PC); return: `returned:` note (`poll_events.lua:363`). `open_policy` in `unresolved` | O1: the same key is absent from party+boxes while deposited, back after withdraw | MODEL (lupa) only; physical needs the Route 34 daycare and a story-gated party. ~20 min if ever | MODEL + SOURCE |

## 3. hg-engine replaced or kept-with-replaced-callee producers (own rows)

hge `acquisition.json` ends with `unresolved: hge_runtime_receipt open`: replaced C needs a runtime receipt, the inventory is SOURCE + ROM data only. All hge physical cells use the pinned build `cb2dc435` and the populated hge saves (D15); one populated save was used to FILE-confirm `party_off` (`5514d94d`).

| # | hge producer (replaced hook, address) | Event/path | Oracle | Physical plan | Status |
|---|---|---|---|---|---|
| H1 | `GiveMon` `pokemon.c:1357/1370/1394` (hook `020541DC`, full replacement; adds forme, ability, ball, encounterType) | `capture{gift:true}` as V5 | O1 via the `hge` profile (ability MSB, hidden-ability bit `d52cc4c7`); O2 | As V5, on hge. Note the 61 script sites are byte-identical, so no new site rows | planned, blocked on `place` + populated save |
| H2 | `ScrCmd_GiveEgg` `script_commands.c:48/62` (`0204D248`); `ScrCmd_GiveTogepiEgg` `:94/125` (`022020CC`, source notes a use-after-free read of the freed party buffer) | Hatch capture as V6 | O1 | Hatch via the V6 egg SYNTH on hge | planned |
| H3 | Hatch rewrite `sub_0206D328` (`get_egg` hatch_stats, hidden ability carried) | Hatch capture `gift_daycare` as V6 | O1 `is_egg` flips with the key unchanged and the ability preserved | V6 on hge. **Highest hge priority**: a replaced function on the O-15 path | planned |
| H4 | `_CreateTradeMon` `npc_trade.c:14` (`02259C40`) building the exchange/loan mon; insertion stays vanilla `ReceiveMonToSlot` | `key_change` / loan gift as V8/V7 | O2: the NARC is byte-identical to vanilla (`trade_narc.all_equal`), so the O2 record applies unchanged | V8/V7 on hge | blocked (as V8) |
| H5 | PC storage 30-box rewrite `PCStorage_PlaceMonInBoxFirstEmptySlot` `:82`, `...InFirstEmptySlotInAnyBox` `:66`, `...ByIndexPair` `:101` | V2/V11 events | O1 with the hge box stride, modified flag at SOURCE projection `PCStorage+0x1E004` | PC route on hge. **Dirty-flag offset still OPEN** (`hge/profile.json:376`, "G2 measures it (mutation/save/reload)") | **IN PROGRESS** |
| H6 | Starter inline patch `starters.c:54` `CreateStarter_CreateMon` (`020960E6`); `Party_AddMon` kept | gift as V4 | O1 (form field), O2 (`c_fact_checks` starter equal) | New-game route on hge (V4) | blocked (as V4) |
| H7 | Wild capture: kept `Task_GetPokemon` (patched inline) with replaced storage callee; wild enemy generation replaced `enemy_party.c:474` | as V1 | O1 + O3 | As V1 on hge; the foe identity now comes from the replaced generator | blocked (as V1) |
| H8 | Roamer generation `field_roamer.c:123`, `ScrCmd_CreateRoamer` (`02045264`); evolution dispatch `GetMonEvolution` (`02070E34`); `ScrCmd_DaycareSanitizeMon`; `SetFixedWildEncounter`; tutorial | Roamer: D14 limit. Evolution: same PID:OTID, no event (negative control only). Others: not producers | O1: key unchanged across evolution | Roamer SOURCE+MODEL. Evolution key-stability could ride a SYNTH level-up; optional | limited / negative-only |
| H9 | DNA Splicers restore `PartyMenu_HandleUseItemOnMon.c:179` (hge-only, `open_policy`) | `vanished`/`returned:` notes while the fused mon sits in save-misc storage | O1: party count and keys across the fuse | Not required for the RC; needs the Reshiram/Zekrom story | OPEN policy |

## 4. New tooling this plan needs (none exists)

| Tool | Purpose | Unblocks |
|---|---|---|
| `gen4_synth_save.py bag` (+ a Lua/codec bag read) | Poke Balls so a catch can be thrown; `has_pokeballs` source | V1, V2, V3 positive, V10, H7 |
| `gen4_synth_save.py party6` | Full party for the PC-full capture | V2 |
| `gen4_synth_save.py egg1` | A party egg with 1 egg cycle, for a native hatch | V6, H2, H3 |
| `gen4_synth_save.py species` | Rewrite the clone to an NPC's ask species | V8, H4 |
| `gen4_synth_save.py place` | Write `Location` (known at general+`0x1234`, `tools/gen4_routes.py:179-203`) plus script flags/vars; flag area not decoded by the codec | V5, V7, V9, V10 |
| New-game route legs | boot, intro, naming, Elm's lab | V4, H6 |

Every one of these keeps the SYNTH/native boundary: the tool writes setup bytes into lane copies with a sidecar; the game runs the script, the hatch, the trade or the deposit.

## 5. Polling cannot observe truthfully (flags)

- **F1 starter swallowed by the baseline.** The first settled view is learned silently (`poll_events.lua:284-287`); a save that already holds the starter never reports it. Only a new game exercises V4/H6.
- **F2 static and roamer catches look like ordinary captures.** `take()` knows only the foe identity (`:361-385`); `cfg.gift_area` (`:263-266`) is not wired anywhere in `lua/gen4/` and only mutes `no_catch`. The 21 statics (D10, required) and the roamers (`special_modes.roamers`: Raikou/Entei L40, Latias/Latios L35, D14) both need a classifier from `acquisition.json`, or the server will fill an area slot that policy says it must not (`zone_policy.static`, `.roamer`).
- **F3 `key_change` is never emitted** (`:340-355` notes only). V8/H4 cannot pass until the client card lands.
- **F4 external distributions look like gifts.** A Mystery Gift or link-traded mon arrives as a no-foe new party key, so the reducer reports `capture{gift:true}`; a Pal Park box arrival is only a `box_fresh_unattributed` note (`:386`). Recorded limit, not fixable by polling.
- **F5 Safari area is unresolvable by polling the map.** The area comes from the save's `SafariZoneAreaSet` (`special_modes.safari.resolution`; `area_map.json` safari_* have `maps: []`). SOURCE + MODEL only (D14).
- **F6 Bug Contest.** The in-contest catch is held in the battle system and the kept bug appears at the result (`overlay_bug_contest.c:219-229`). Reported correctly only if a pending foe still matches; else a gift in the current area. MODEL only (D14).
- **F7 `has_pokeballs` gates `no_catch`** (`poll_events.lua:415`) but the bag is unmeasured, so the positive `no_catch` cannot be receipted.
- **F8 events fire only at idle + settled** (`ready` at `poll_events.lua:498`, `settle_frames=2` at `:54`): by design, so receipts must allow a settle window after the copy-back.

## 6. G2 checklist (PLAN `:243`)

Commit hashes from `git log --oneline` on this branch; receipt paths under `C:/slink/g4/`.

| Clause | Evidence now | Status | Next action |
|---|---|---|---|
| Registration pins + four-byte fire words resolve for HG/SS/hge | Pack generator `260a904c`, hge extension `3ec5a0c6`, sites/diagnostics `f891ad9f`; `tests/unit/test_gen4_pack.py:124-140,193` (3-byte, 5-byte and reversed fire words go red). Live fire/overlay residency = G1 rows b/c, never run on the frozen cut (`G1_SIGNATURE_2026-10-01.md`) | SOURCE DONE; physical IN PROGRESS | Re-run rows a-n on the frozen cut for HG and hge; `C:/slink/g4/probe/heartgold-0cc5b0ee2c21` is the earlier cut |
| Generated acquisitions join script/C producers, NPC reachability, unresolved branches | HGSS `c6698595`, `e917eae8`; hge `1271b01a`; `tests/unit/test_gen4_data_tools.py:242-316` (counts, nothing unresolved vanishes, unclassified C producer fails). 7 species-unresolved sites + 4 policy rows carried in `unresolved` | DONE (SOURCE) | NPC *reachability* (story gates per site) is not generated: add it in the per-row plans above (V5/V7/V8/V9) |
| Independent codec/save-layout controls: counter wrap, coherent banks, CRC, torn/ambiguous | `073cddd4` codec, `663c5f3d` (Pt + SS + hge geometry); `tests/unit/test_gen4_save_layout.py:87-112` (wrap, equal counters ambiguous, torn newest falls back, torn only bank refused) | DONE | None |
| HG fixtures boot, native SAVE, cold reload with counter/keys | PC deposit + native SAVE + cold reload PHYSICAL on HG/SS/hge (`02705ce5`, `01dd2bb3`, hardening `8db9c26f`; `C:/slink/g4/route_pc*/`); row-o save/reload `a15b7d74`, `0f75c938` | PHYSICAL PASS (receipts pre-`1bbc1f88` read STALE by binding) | Re-run at the landing HEAD |
| hge `party_off`, dirty flag, ability offset: source/FILE + populated mon decode | `party_off` `5514d94d`; ability 9-bit FILE-confirmed (`5514d94d`); hidden-ability bit 6 `d52cc4c7`; dirty flag MEASURED HG +0x12004 / hge +0x1E004 (RAM set by deposit, 0 after SAVE and load; battery keeps 1, `f426a76b`) | DONE | None |
| SS fixture cells | SS PC deposit/SAVE/reload, capture (`catch_ss/catch_204123/verdict.json` PASS; the `CATCH OPEN` header in `receipt.txt` is the probe's raw observation, the Python judge writes the verdict) and hatch (`hatch_ss/hatch_ss_receipt.json`, HATCH_OK) PHYSICAL | PHYSICAL PASS (re-run at landing HEAD) | None beyond the landing re-run |
| Pt profile generation SOURCE; Pt decode (D3) | Pt profile + geometry `663c5f3d`; owner Pt save decoded (TTT TID 44361, Turtwig) | DONE (emulator-free, non-shipping) | None |
| Every required producer has an independent oracle + physical receipt plan | This document: V1-V12, H1-H9, tooling in section 4, flags F1-F8 | IN PROGRESS | Owner/coordinator accepts the plan; build the section 4 tools in order bag, egg1, species, place (each unblocks the most rows); client card for F2/F3 before V8/V10 |

### 6a. Remaining G2 work in priority order (checkpoint 5, OMP cx-3a3322b0, reconciled)

1. The withdraw/release PC legs in `tools/gen4_routes.py`. Deposit is PHYSICAL; withdraw and release are not yet routed.
2. A SYNTH `place` kind in `tools/gen4_synth_save.py`, for statics and gifts. Then add `species`.
3. A SYNTH `party6` kind, for the full-party and box-overflow cells.
4. A new-game route (intro to first control) for the fresh-save cells.
5. F2: the static gift-area classifier.
6. F3: the `key_change` client wiring. This depends on the client card, see `reviews/CLIENT_DESIGN_PROPOSAL_2026-10-01.md`, and N2 must be settled first.

Already PHYSICAL on HG, SS and hge, needing only the landing-HEAD re-run: PC deposit/SAVE/reload, wild capture and egg hatch. Row o is PHYSICAL on HG and hge, both one-mon and 2-mon.

### 6b. Withdraw / release leg design (OMP cx-44f63aff, coordinator-reconciled)

**Withdraw**
- **Inputs:** reuse the `pc_deposit()` prologue (`lua/tests/gen4_route_play.lua:462-497`). Then, where deposit taps A on toolbar node 6 (STORE), tap Right then A.
  - The toolbar is a four-node ring (`ov14_021F8A40`, pinned pokeheartgold `asm/overlay_14.s:37480-37485`).
  - Node 7 = WITHDRAW is INFERRED from the ring order. Confirm it once with the manager-state readback before writing the leg.
  - The box-side selection state after node 7 is UNKNOWN. That is the largest gap.
- **Oracle:**
  - party +1 with the box PID;
  - `box_census` shows the slot empty and the total −1;
  - the box-1 modified bit is set;
  - all of the above hold after SAVE and a cold reload (template: the `RELOAD_OK` block at `:698-708`).
- **Falsifiers:**
  - no Right tap (presses STORE) must FAIL `withdraw_not_committed`;
  - Right×2 (MOVE) must FAIL, not hang.

**Release**
- **Inputs:** the box slot action menu and its confirm states are unnamed in the ov14 asm. Read them from source before coding. Build release after withdraw is green.
- **Oracle:** the PID is absent from party and boxes, the modified bit is set, and the PID is **still absent after SAVE and a cold reload**. Only the reload half separates a real release from a RAM-only zeroing.
- **Falsifiers:**
  - a run stopped before SAVE must read OPEN;
  - releasing a party mon is refused.

**Receipts:** keep the existing `route` kind. `RECEIPT_KINDS` `pass` is any-of (`gen4_routes.py:1059`, `status in spec["pass"]`), so appending `PC_WITHDRAW` and `PC_RELEASE` is safe. De-hard-code the `PC_DEPOSIT` literals (`gen4_routes.py:985, 1235, 1397`) into a per-target map.

**State machine (OMP cx-450724f8).** `PCBox_Main` wraps `ov14_021EAF8C`, which dispatches through the word table `ov14_021F7D9C`: entry N handles state N, and each handler returns the next state. Exit is `cmp r0,#0xb3` (`asm/overlay_14.s:11368-11385`), and the state is the word read at `man+0x14`. The toolbar labels are BG tilemaps, so there are no strings to name the nodes.

**Next step:** find the handler for the toolbar-select state (`ST_LIST` 0x5B), follow its branch for cursor node 7, and check which storage call it reaches. Note that the toolbar node index is NOT the state index; the OMP's "read entry 7" conflates the two.

**ST_LIST handler (OMP cx-c0eda9f7).**
- State 0x5B is handled by `ov14_021EDFA0` (pinned `asm/overlay_14.s:17200-17519`; table entry at `:37057`).
- The cursor node is `[data+0x21] - 0x1E` (handler-relative lines 60-65 and 201-206), so toolbar nodes 6-9 are bytes 0x24-0x27. This is usable as a probe assertion now.
- Successors are set by `bl ov14_021F2270` with the state in r2. The 0x94 state appears there, which agrees with the deposit leg.
- **Toolbar SETTLED (OMP cx-903f44a7). This SUPERSEDES the node 6/7 assumption above.**
  - The A branch is a 12-case jump table (`asm/overlay_14.s:17313-17342`).
  - Node 7 → state 0xA9 (`:17367`). That is the deposit leg's documented first-button path, so the deposit's bare A is on **node 7 = STORE**.
  - Node 8 → state 0x97 (`:17377`), after writing 8 to `data+0x2C` (`:17374`). This is a free in-RAM witness that the branch was taken.
  - **WITHDRAW is most likely node 8**, i.e. one Right from where the deposit presses A.
  - **Confirm before coding:** read state 0x97's handler (table entry at `:37117`) for a box→party call.
  - The toolbar spans nodes 6..11 plus three negative-coded nodes; their meaning is UNKNOWN.
