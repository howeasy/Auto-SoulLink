# RR opcode-table audit: faint and capture bindings

Card gen3-P3-R4, 2026-09-21. Only this research note changed; no emulator, Python, code/pack edits or commits. Companion `patch/build/slink_RR.gba` MD5 verified **bf8e94a01c0aee0aa7eb37c7333329af**. ROM bytes/words read using PowerShell `ReadAllBytes`, `BitConverter`, and `ToHexString`; Thumb BL targets decoded from their two halfwords. ROM offsets below are file offsets; CPU address = offset + 0x08000000. This is source/binary qualification, not physical hook delivery.

## Direct command-body rows: both displaced

Only two of the 19 companion rows have vanilla `Cmd_*` function bodies (`data/games/gen3_rr/engine_signals.json`, companion sites beginning at line 581; function/capture inventory `docs/gen3_engine_sites.md:118-156`). Opcode numbers are explicitly recorded in pinned pret `src/battle_script_commands.c:339,554`, in `E:/Google Drive/SLink/.cache/pret/pokefirered` at c75f352304d529f6ba92d4f74b9cf8b5c3810788 (source pin `docs/gen3/research/pins.md:8-10`).

| Row | Opcode | FR slot offset -> pointer | RR selected slot offset -> pointer | Verdict on existing RR command-body pin |
|---|---|---|---|---|
| faint / Cmd_tryfaintmon | 0x19 | 0x00250180 -> 0x080212AD | 0x0103EF84 -> **0x0909E5BD** | **DEAD for the selected opcode dispatch**; old capture 0x080213C8 is not in the selected body |
| capture_wild / Cmd_givecaughtmon | 0xF0 | 0x002504DC -> 0x0802D801 | 0x0103F2E0 -> **0x0907DD45** | **DEAD for the selected opcode dispatch**; old capture 0x0802D828 is not in the selected body |

The slots are base + opcode*4: FR base **0x0825011C**, RR base **0x0903EF20**. Bit 0 marks Thumb; executable starts are **0x0909E5BC** and **0x0907DD44**. DEAD here does not claim no conceivable direct caller can ever invoke the old function; it means its reference in the unused vanilla table does not establish the actual opcode path.

Upstream names: [CFRU general_bs_commands.c:1172-1283, atk19_tryfaintmon](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/general_bs_commands.c#L1172-L1283), and [catching.c:614-656, atkF0_givecaughtmon](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/catching.c#L614-L656). Names come from the pinned source; RR addresses come from binary table entries, not BPRE.ld.

## The dispatch replacement is wider than three literal pools

R3 proved the first three named runners. This audit additionally scanned aligned words in the first 0x20000 ROM bytes for 0x0903EF20 and compared all five hits against FR. Every corresponding FR word is 0x0825011C:

| Literal ROM offset | Enclosing vanilla function | Role |
|---|---|---|
| **0x00014C1C** | HandleTurnActionSelectionState, entry 0x08014040, size 0xC64 | Turn/action-selection script dispatch; pret battle_main.c:3377 |
| **0x00015A28** | HandleEndTurn_FinishBattle, entry 0x08015910, size 0x120 | Finish-battle script dispatch while controller idle; pret battle_main.c:3855-3857 |
| 0x00015C6C | RunBattleScriptCommands_PopCallbacksStack, 0x08015C00 | Script dispatch or callback-stack pop; pret battle_main.c:3942-3954 |
| 0x00015C98 | RunBattleScriptCommands, 0x08015C74 | Script opcode dispatch; pret battle_main.c:3957-3960 |
| 0x0001D054 | HandleAction_RunBattleScript, 0x0801D030 | Action-table script runner; pret battle_main.c:574 maps B_ACTION_EXEC_SCRIPT |

Function bounds are from `data/gen3/pret/pokefirered.sym` entries named above; the three original runner symbols are at :1642-1643,1692. The last three LDR instructions remain at 0x08015C50 / 0x08015C7E / 0x0801D03A, each halfword 0x4906, selecting the changed pools (R3 note `docs/gen3/research/rr_faint_repin.md`, dispatcher table). The first two new rows prove changed literal words inside the symbol bounds; this note does not claim a full disassembly of those enclosing functions. No whole-ROM claim that these are the only table references is made.

None of these five runner functions is itself a pinned event row. They dispatch commands that can cause later callbacks; they are not aliases for CB2_InitBattle, ReturnFromBattleToOverworld or CB2_WhiteOut. Those callbacks' existing captures are not made dead merely by changing the command table (`docs/gen3_engine_sites.md:78-116,218-236`). The physical natural-play receipt already reports fires for those three callbacks (`docs/gen3/probes/shadow_rr_play_2026-09-21.txt`, conclusion).

## Re-pin candidates (exact bytes; LIVE OPEN)

### faint: retain the R3 common post-counter join

Existing semantics: player-qualified faint after the counter commit, including saturation (`docs/gen3_engine_sites.md:118-136`). Candidate:

| Field | Value |
|---|---|
| address | **0x0909E6E4** |
| capture_offset | **8** (effective hook **0x0909E6EC**) |
| rom_offset | **0x0109E6E4** |
| expected_hex (16 bytes) | **3B78FF2B00D0EAE0029B1878884B06F0** |
| replacement entry | **0x0909E5BC**, bytes **F0B5C44C23685E789B7885B0C24D002B** |
| entry-relative capture | **0x130** |

R3 documents the branch/store decoding: counter byte at [R7], compare FF, saturated branch to E6EC; unsaturated path increments/stores at E8C2/E8C4 then branches back to E6EC. Active battler is RAM 0x02023BC4; do not read pre-load R0 as the battler. Deduplicate identity transitions and do not confuse this with completed animation/party synchronization (`rr_faint_repin.md`, decoded branch evidence and capture contract). RR source player-counter branch: linked general_bs_commands.c:1233-1239. This card does not upgrade R3 to LIVE.

### capture_wild: after the replacement's GiveMonToPlayer call

Vanilla contract is the return from GiveMonToPlayer, before its result is consumed (`docs/gen3_engine_sites.md:138-156`; pret battle_script_commands.c:9617-9645). RR source similarly tests GiveMonToPlayer's result ([catching.c:629-645](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/catching.c#L629-L645)). Binary decoding:

```text
0907DD44 B5F8          push {r3-r7,lr}       ; replacement entry
0907DD46 F7FF FF3F     bl 0907DBC8           ; obtain target mon
0907DD4A 0004          movs r4,r0            ; mon pointer retained in r4
... optional pre-placement item handling ...
0907DD82 0020          movs r0,r4
0907DD84 F7FF FD04     bl 0907D790           ; existing RR GiveMonToPlayer body
0907DD88 4E37          ldr r6,[pc,...]        ; CAPTURE, result still in r0
0907DD8A 2800          cmp r0,#0
0907DD8C D022          beq 0907DDD4          ; party-result branch
```

Manual BL calculation uses signed Thumb-1 high11<<12 plus low11<<1 plus instruction+4. These halfwords at ROM 0x0107DD84 resolve **0x0907D790**, not the unused vanilla GiveMonToPlayer tail.

| Field | Value |
|---|---|
| address | **0x0907DD80** |
| capture_offset | **8** (effective hook **0x0907DD88**) |
| rom_offset | **0x0107DD80** |
| expected_hex (16 bytes) | **5A532000FFF704FD374E002822D0374B** |
| replacement entry | **0x0907DD44**, bytes **F8B5FFF73FFF040010F0ACF9002816D0** |
| entry-relative capture | **0x44** |
| point | R0 = placement result; R4 = captured mon pointer; also record R13/R14 for trace |

If anchoring directly at capture: address=0x0907DD88, capture_offset=0, rom_offset=0x0107DD88, expected_hex=**374E002822D0374B00F082FB364D374B**. All three capture/entry slices were read from both clean RR and companion and match. The hook marks completed placement, not ball throw/animation or all later dex/nickname work. Qualify the returned success/destination and suppress duplicate acquisition with mon_given; a hook fire alone is not successful acquisition (existing contract `docs/gen3_engine_sites.md:140`).

## Complete RR inventory disposition

“Unaffected” below means no direct command-table binding to replace, **not** blanket physical validation. Helpers are ordinary functions and can be called by a replacement command without moving again.

| RR kind(s) | Table-derived status | Evidence / disposition |
|---|---|---|
| faint | opcode 19 displaced | DEAD original command capture; candidate above |
| capture_wild | opcode F0 displaced | DEAD original command capture; candidate above |
| mon_given | ordinary GiveMonToPlayer helper, not an opcode | **VALID for this dispatch audit**: new F0 BL at 0907DD84 targets existing pinned body 0907D790. Existing capture 0907D7F8+8 remains in that body; 16 bytes at ROM 0107D7F8 = 00200E4B01351D7070BD0135062DE3D1 (`docs/gen3_engine_sites.md:158-186`) |
| pc_move | ordinary SendMonToPC helper, not an opcode | **VALID for this dispatch audit**: RR GiveMonToPlayer BL at **0907D812 -> 090B6E38** reaches the already-pinned replacement. Existing capture 090B6E9A+6; bytes at ROM 010B6E9A = 00F0EDF90120F8BD01351E2DD7D10134 (`docs/gen3_engine_sites.md:188-216`). Conditional on full party / placement path |
| battle_begin | CB2_InitBattle callback | Unaffected direct binding; not Cmd_* (`docs/gen3_engine_sites.md:78-96`) |
| battle_end | ReturnFromBattleToOverworld callback | Unaffected direct binding, even though script runners participate earlier in cleanup (`:98-116`; pret battle_main.c:3906,3915-3940) |
| whiteout | CB2_WhiteOut callback | Unaffected direct binding, not a script command (`:218-236`) |
| frame_control | CallCallbacks | Unaffected control, not command dispatch (`:58-76`) |
| map_load | CB2_LoadMap2 callback | Unaffected, not battle command (`:238-256`) |
| evolve_species_store | Task_EvolutionScene | Unaffected task capture (`:258-276`) |
| trade_begin, trade_done | TradeMons helper | Unaffected trade-scene helper, not battle command (`:278-296,500-518`) |
| trade_evolve_species_store | Task_TradeEvolutionScene | Unaffected task capture (`:480-498`) |
| save | TrySavingData | Unaffected save helper (`:298-316`) |
| pc_deposit, pc_withdraw, pc_box_place | TryStorePartyMonInBox / SetPlacedMonData | Unaffected storage frontend/helper sites (`:360-438`); do not conflate with SendMonToPC acquisition |
| pc_release_begin, pc_release | ReleaseMon | Unaffected release helper (`:440-478`) |
| poison_faint, poison_hp_before | DoPoisonFieldEffect, NOT Cmd_* | Not emitted in RR JSON; disabled RR replacement already documented, not explained by battle table (`:318-336,520-548`) |
| borrowed_party, nature_change | RR-only unresolved routines | Not emitted; no justified opcode index/target or capture to assign. Remain UNVERIFIED (`:338-358,548`) |

All 19 emitted kinds are accounted for (two displaced, two traced helper dependencies, fifteen unaffected direct bindings), plus the four excluded kinds. GiveMonToPlayer also serves gifts/eggs; it is not exclusively an F0 descendant (`docs/gen3/research/rr_site_reachability.md:80-84`). The replacement's full-party helper connection is directly decoded here, not assumed from the obsolete vanilla call site.

## Coordinator census (12 function starts maximum)

| Function-start address | Label |
|---|---|
| 0x08014040 | HandleTurnActionSelectionState |
| 0x08015910 | HandleEndTurn_FinishBattle |
| 0x08015C00 | RunBattleScriptCommands_PopCallbacksStack |
| 0x08015C74 | RunBattleScriptCommands |
| 0x0801D030 | HandleAction_RunBattleScript |
| 0x080212AC | old Cmd_tryfaintmon comparison |
| 0x0909E5BC | selected RR atk19_tryfaintmon |
| 0x0802D800 | old Cmd_givecaughtmon comparison |
| 0x0907DD44 | selected RR atkF0_givecaughtmon |
| 0x0907D790 | RR GiveMonToPlayer |
| 0x090B6E38 | RR SendMonToPC |
| 0x08015B58 | ReturnFromBattleToOverworld control |

Symbol-backed vanilla entries: `data/gen3/pret/pokefirered.sym` named entries (runner/faint refs above; Cmd_givecaughtmon :1969; additional runner entries :1625,1637). RR starts are active table targets or decoded BL targets above. Use separate real-player-faint and successful-catch runs; full-party capture must additionally reach SendMonToPC. A faint-only run does not qualify capture, and a failed ball throw does not qualify placement. Watch interior **0x0909E6EC** and **0x0907DD88** separately from this start-only list.

## NOT VERIFIED / handoff

* Neither new candidate has a physical fire receipt from this card. Require exact callback address, raw R15, result/battler identity, player/opponent negatives, saturated faint counter, party/PC capture destinations and duplicate reduction.
* Whole-ROM proof of absence of other direct callers is not made. DEAD labels are scoped to the selected opcode table. Source/binary matches do not replace liveness and semantic oracles.
* No inference that every 0x09 target is a moved function is needed: the two specific selected bodies, their entry bytes, and relevant internal calls were read/decoded.
* Table replacement does not imply repinning the fifteen callback/task/control/storage/trade/save rows. Conversely, prior blanket static “all pins reachable” claims need the active dispatcher selection edge recorded (`docs/gen3/research/rr_site_reachability.md:3-9,18-26`).
* No files beyond this note changed. Coordinator owns generator/JSON edits, tests, census and commits.
