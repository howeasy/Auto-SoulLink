# P2 site cross-reference — vanilla `gen1_rby` engine signals vs pureRGB S1 sites

Generated for the M1 pureRGB engine-signal generator. Read-only prep artefact; no other file is touched.

Inputs (all cells below are transcribed from these files, never from memory):

- **V** = `gen1-master-release-plan-6b4279/data/games/gen1_rby/engine_signals.json` — `schema: rby-engine-signal-sites-v1`, file `sha256 018f8c6f89a15749ec5470b5c1c54c9c40a50d7079c5c9deb39ba0bd15b4356f`; 17 site kinds per title (red/blue/yellow), `source_commit 405b6246372d7e5a2cb029cbb65219b13286b8c9` (pokered) / `0a0851546ff65f65c4bb2af2b95e279e709a8653` (pokeyellow).
- **S1** = `docs/purergb/research/s1/sites_purergb.json` — `schema: purergb-engine-signal-sites-v1`, 49 sites per title (red/blue/green); companion prose `docs/purergb/research/s1/REPORT.md`.
- **RC** = `gen1-rby-code-sweep-8d06e2/tools/gen_gen1_engine_signals.py:1-120` — the generator standard a site row must follow (source-text assert + operand assert + ROM slice).
- Vanilla symbol bases were resolved from `gen1-master-release-plan-6b4279/data/pret/pokered.sym` (the file `V` was generated from) so that every `+offset` below is a symbol-relative offset, not a guess.

## Legend and semantics (read before using the tables)

A site row has three numbers: **anchor** = the address whose bytes are verified, **hook** = the PC the client fires at, and **flat** = the ROM file offset.

| Field | `V` (vanilla, RC/pin-tool schema) | S1 (pureRGB) |
|---|---|---|
| anchor | `symbol` + (`address` - symbol base) | `symbol` + `offset` |
| hook | anchor + `capture_offset` | `address` (S1 sets `capture_offset: 0` on **every** row) |
| flat | `rom_offset` = `bank*0x4000 + addr - 0x4000` (bank 0: `= addr`) | `rom_offset`, same formula |
| provenance | none per row | `note` (source citation + instruction derivation) and `source_assert_ok` |

**The same field name carries two different meanings.** `V.capture_offset` is a hook delta from the anchor (non-zero on 4 rows: `bag_received` 8, `save_witness` 3, `wild_begin` 5, and `poison_faint`, which stores its +4 in `address` instead — RC style); `S1.capture_offset` is always 0 and the hook is the anchor address. Copying S1's `capture_offset` into a `V`-shaped row puts the hook at the anchor. `V` is itself inconsistent: `poison_faint` keeps its +4 in `address` while `wild_begin`/`save_witness`/`bag_received` keep theirs in `capture_offset`.

**Status vocabulary.** `SAME-SHAPE` = S1 pins the same point (same symbol, same hook offset). `OFFSET-MOVED` = S1 pins the same symbol/role at a different offset. `NEW-SYMBOL` = S1 covers the role with a different symbol. `UNMATCHED` = S1 has no row for that kind. `NEW KIND` (table 2) = a kind vanilla does not have at all.

**S1 records source *basenames* only** (`core.asm`, `item_effects.asm`, `home/header.asm`, ...); the pureRGB repo-relative path (`engine/battle/core.asm`, ...) is in neither S1 nor REPORT and must be supplied by the generator. Cells below quote S1 verbatim; `UNKNOWN` means S1/REPORT carry no citation for that site.

**All pureRGB code sites are byte-identical across red/blue/green** (REPORT §1: "zero cross-title differences found"), so the pureRGB columns quote the `red` capture only. The three `*_corrected` rows are S1's shadow entries for the three sites whose task-literal definition landed on the wrong byte.

## 1. Vanilla site kinds -> pureRGB S1 sites (one row per vanilla kind; red titles)

| vanilla site | vanilla symbol+anchor (hook) | vanilla bank:addr · flat · hex (len) | S1 site | pureRGB symbol+offset (hook = anchor) | pureRGB bank:addr · flat · hex (len) | source file:line to assert (pureRGB) | status |
|---|---|---|---|---|---|---|---|
| `add_party_mon` | `AddPartyMon+$00 (hook +$00)` | `00:3927` · `14631` · `E5D5C5060321` (6) | — | — | — | UNKNOWN | **UNMATCHED** |
| `bag_received` | `AddItemToInventory_.done+$00 (hook +$08)` | `03:4E6B` · `52843` · `E1D1C1C178EA96CFC9` (9) | `bag_received` | `AddItemToInventory_.done+$08` | `03:505C` · `53340` · `C9E523FA92CF8785` (8) | inventory.asm L86-93 | **SAME-SHAPE** |
| `battle_begin` | `InitBattleCommon+$00 (hook +$00)` | `0F:6F3D` · `257853` · `FA5DD3F52158` (6) | `trainer_staging_corrected` | `InitBattleCommon+$48` | `0F:6F22` · `257826` · `3E02EA57D0184921` (8) | core.asm L7044 (inherited from `trainer_staging`) | **OFFSET-MOVED** |
| `battle_end` | `EndOfBattle+$00 (hook +$00)` | `04:77AA` · `79786` · `FA2BD1FE0420` (6) | `whiteout_endofbattle` | `EndOfBattle` | `3A:44FD` · `951549` · `FA33D1FE042036FA` (8) | UNKNOWN | **SAME-SHAPE** |
| `battle_faint` | `RemoveFaintedPlayerMon+$00 (hook +$00)` | `0F:4741` · `247617` · `FA2FCC4F2158D006` (8) | `battle_faint` | `RemoveFaintedPlayerMon` | `0F:47CD` · `247757` · `FA2FCC4F2158D006` (8) | core.asm L1151 | **SAME-SHAPE** |
| `battle_loop_head` | `MainInBattleLoop+$00 (hook +$00)` | `0F:4233` · `246323` · `CD434D2115D0` (6) | `battle_loop_head` | `MainInBattleLoop+$06` | `0F:4253` · `246355` · `CD004E2115D02AB6` (8) | core.asm L309-317 | **OFFSET-MOVED** |
| `blackout` | `ResetStatusAndHalveMoneyOnBlackout+$00 (hook +$00)` | `01:40B0` · `16560` · `AFEA0BCFEA00` (6) | `blackout` | `ResetStatusAndHalveMoneyOnBlackout` | `01:40B0` · `16560` · `AFEA0BCFEA08D7EA` (8) | black_out.asm L3-6 | **SAME-SHAPE** |
| `capture_box` | `SendNewMonToBox+$00 (hook +$00)` | `03:67A4` · `59300` · `1180DA1A3C12` (6) | — | — | — | UNKNOWN | **UNMATCHED** |
| `evolve` | `TryEvolvingMon+$00 (hook +$00)` | `0E:6D0E` · `240910` · `21D3CCAF77FA` (6) | `evolve_species_store` | `Evolution_PartyMonLoop.skipfix_end+$3C` | `2C:56C5` · `726725` · `77E56B6218012323` (8) | evos_moves.asm L293-300 | **NEW-SYMBOL** |
| `move_mon` | `MoveMon+$00 (hook +$00)` | `00:3A68` · `14952` · `F0B8F53E03E0` (6) | — | — | — | UNKNOWN | **UNMATCHED** |
| `npc_trade` | `InGameTrade_DoTrade+$00 (hook +$00)` | `1C:5C07` · `465927` · `AFEA7DD03DEA` (6) | `npc_trade_remove` | `InGameTrade_DoTrade+$7B` | `1C:5547` · `464199` · `CD93343E80EA49CC` (8) | in_game_trades.asm L152 | **OFFSET-MOVED** |
| `poison_faint` | `ApplyOutOfBattlePoisonDamage.noBorrow+$04 (hook +$04)` | `03:46D9` · `50905` · `E52323771AEA1ED1` (8) | `poison_faint` | `ApplyOutOfBattlePoisonDamage.noBorrow+$04` | `03:4731` · `50993` · `E52323771AEA26D1` (8) | poison.asm L40-45 | **SAME-SHAPE** |
| `remove_pokemon` | `RemovePokemon+$00 (hook +$00)` | `00:391F` · `14623` · `21687B0601C3` (6) | — | — | — | UNKNOWN | **UNMATCHED** |
| `save_witness` | `SaveMenu.save+$00 (hook +$03)` | `1C:772D` · `472877` · `CD487821A5C4` (6) | `save_witness` | `SaveMenu.save+$03` | `1C:77D1` · `473041` · `CD562921B9C421FF` (8) | save.asm L162-164 | **SAME-SHAPE** |
| `starter_begin` | `OaksLabMonChoiceMenu.continue+$28 (hook +$28)` | `07:520D` · `119309` · `CD2739` (3) | `starter` | `OaksLabMonChoiceMenu.continue+$23` | `07:49DA` · `117210` · `CD9A342136D7CBDE` (8) | OaksLab.asm L843 | **OFFSET-MOVED** |
| `starter_end` | `OaksLabMonChoiceMenu.continue+$2B (hook +$2B)` | `07:5210` · `119312` · `212ED7CBDE3EFCEA` (8) | — | — | — | UNKNOWN | **UNMATCHED** |
| `wild_begin` | `InitWildBattle+$00 (hook +$05)` | `0F:6F8B` · `257931` · `3E01EA57D0CD016B` (8) | `wild_begin` | `InitWildBattle+$13` | `0F:6F4A` · `257866` · `CD8A6ACD426C2172` (8) | core.asm L7091-7093 | **OFFSET-MOVED** |

### 1b. Why each non-`SAME-SHAPE` row is what it is

- **`add_party_mon` (UNMATCHED)** — No S1 row at the AddPartyMon entry. S1 only pins the three call sites (capture_party_begin/end, npc_trade_add, starter) and names the callee as `call AddPartyMon (CD 9A 34 = call $349A)`.
- **`bag_received` (SAME-SHAPE)** — Same symbol, same hook offset +8 (the `ret` of the 9-byte epilogue). Bytes differ only in the operand of the trailing `ld [n],a` (vanilla `$CF96` = `V.addresses.wItemQuantity`; pureRGB `$CF92`).
- **`battle_begin` (OFFSET-MOVED)** — S1's InitBattleCommon row is at +$48 (the trainer branch `ld a,2` / `ld [wIsInBattle],a`); the vanilla +0 anchor has NO S1 row, so the bytes at +0 are UNKNOWN for pureRGB.
- **`battle_end` (SAME-SHAPE)** — Same symbol, same offset +0; bank moved $04 -> $3A. The S1 note carries no .asm citation (dump-only check).
- **`battle_faint` (SAME-SHAPE)** — Same symbol, same offset +0, byte-identical 8-byte slice.
- **`battle_loop_head` (OFFSET-MOVED)** — Hook moved +0 -> +6; S1's note names the same callee in both (`call ReadPlayerMonCurHPAndStatus`). (PLAN §3.5 attributes the 6 prepended bytes to `ld hl,wPlayerTurnCount; inc [hl]; inc hl; inc [hl]` — not in S1.)
- **`blackout` (SAME-SHAPE)** — Same symbol, same offset +0, same bank $01 and the same absolute address $40B0. The vanilla slice is only 6 bytes, so it cuts the third `ld [n],a` before its high operand byte; the visible byte 5 differs ($00 vs $08) because the operand address moved, not because the instruction shape did.
- **`capture_box` (UNMATCHED)** — No S1 row at the SendNewMonToBox entry; S1 pins the two call sites inside ItemUseBall.sendToBox and names the callee ($654B).
- **`evolve` (NEW-SYMBOL)** — S1 covers the evolution role with a different symbol: Evolution_PartyMonLoop.skipfix_end+$3C (the final wPartySpecies store). Vanilla anchors on TryEvolvingMon+0; S1 pins no row there, so the pureRGB bytes at TryEvolvingMon+0 are UNKNOWN (PLAN §3.3 states the label survives, but that is not byte evidence).
- **`move_mon` (UNMATCHED)** — No S1 row at the MoveMon entry; S1 pins the daycare call site and names the callee ($34DC).
- **`npc_trade` (OFFSET-MOVED)** — Same symbol; S1 pins three finer points (+$7B RemovePokemon, +$83 AddPartyMon, +$89 ClearScreen). None is the vanilla +0 anchor.
- **`poison_faint` (SAME-SHAPE)** — Same symbol, same hook offset +4. Bytes differ only in the operand of the trailing `ld [n],a` ($D11E -> $D126; S1's note names pureRGB's `$D126` as wPokedexNum).
- **`remove_pokemon` (UNMATCHED)** — No S1 row at the RemovePokemon entry; S1 pins every caller (npc_trade_remove, cable_remove, pc_deposit/withdraw/release) and names the callee ($3493).
- **`save_witness` (SAME-SHAPE)** — Same symbol and the same hook position (the instruction after `call SaveGameData`), but the byte shape changed: pureRGB's post-call instruction is `call ClearTextBox` (CD 56 29), vanilla's is `ld hl` (21 A5 C4), and S1 anchors its slice at +3 rather than +0. A copied vanilla expected_hex fails.
- **`starter_begin` (OFFSET-MOVED)** — Same symbol (OaksLabMonChoiceMenu.continue) and the same callee (`call AddPartyMon`), but the call sits at +$23 in pureRGB vs +$28 in vanilla.
- **`starter_end` (UNMATCHED)** — S1 pins only the call (`starter` at +$23); the post-call return point (+$26 in pureRGB) has no row.
- **`wild_begin` (OFFSET-MOVED)** — Same symbol, same callee (`call LoadEnemyMonData`) and the same 3-byte gap after the `ld [wIsInBattle],a` store, but the store/hook moved: vanilla hook +5, pureRGB hook +$13. (PLAN §3.5 attributes the inserted bytes to MissingNoInit + `callfar PreventInvalidEncounters` — not in S1.)

## 2. S1 sites with no vanilla counterpart (same columns; vanilla cells `—`)

S1 names its rows independently of the vanilla kinds. Three of the rows the brief listed as "S1-only" are the same role under a different name and are therefore carried by table 1, not here: `starter` (vanilla `starter_begin`), `evolve_species_store` (vanilla `evolve`) and `whiteout_endofbattle` (vanilla `battle_end`). `trainer_staging` *is* here — it is the superseded FAIL row, and its `*_corrected` shadow is table 1's `battle_begin` counterpart. Vanilla also splits two kinds in two (`starter_begin`/`starter_end`, `add_party_mon` vs the box path) while S1 splits others (`capture_party_begin`/`end`, `npc_trade_remove`/`add`/`done`, `cable_*`), so name-level matching under-reports either way.

| vanilla site | vanilla symbol+anchor (hook) | vanilla bank:addr · flat · hex (len) | S1 site | pureRGB symbol+offset (hook = anchor) | pureRGB bank:addr · flat · hex (len) | source file:line to assert (pureRGB) | status |
|---|---|---|---|---|---|---|---|
| — | — | — | `trainer_staging` | `_InitBattleCommon+$48` | `0F:6FBA` · `257978` · `4E2174740635C7CD` (8) | core.asm L7044 | NEW KIND (assert FAIL as specified) |
| — | — | — | `capture_party_begin` | `ItemUseBall.skipShowingPokedexData+$22` | `03:5405` · `54277` · `CD9A34F1A7283221` (8) | item_effects.asm L602 | NEW KIND |
| — | — | — | `capture_party_end` | `ItemUseBall.skipShowingPokedexData+$25` | `03:5408` · `54280` · `F1A72832219E5606` (8) | item_effects.asm L604-606 | NEW KIND |
| — | — | — | `capture_box_begin` | `ItemUseBall.sendToBox+$03` | `03:5421` · `54305` · `CD4B65216854FAF9` (8) | item_effects.asm L616 | NEW KIND |
| — | — | — | `capture_box_end` | `ItemUseBall.sendToBox+$06` | `03:5424` · `54308` · `216854FAF9D7CB47` (8) | item_effects.asm L617 | NEW KIND |
| — | — | — | `pc_deposit` | `BillsPCDeposit+$4B` | `33:4376` · `836470` · `CDAC33213DCDFAA8` (8) | bills_pc.asm L235-236 | NEW KIND |
| — | — | — | `pc_withdraw` | `BillsPCWithdraw+$67` | `33:441F` · `836639` · `CDAC33212646CDCE` (8) | bills_pc.asm L311-312 | NEW KIND |
| — | — | — | `pc_release` | `BillsPCRelease+$70` | `33:44C2` · `836802` · `CDAC33FA91CFCD5F` (8) | bills_pc.asm L389-390 | NEW KIND |
| — | — | — | `changebox_full_save` | `ChangeBox.yes+$38` | `1C:798D` · `473485` · `3EB6CDA533CDAC33` (8) | save.asm L397-399 | NEW KIND (assert FAIL as specified) |
| — | — | — | `transform_base` | `ChangePartyPokemonSpecies` | `35:65B2` · `878002` · `FA91CFEAB5D0CDBB` (8) | change_mon_species.asm L8 | NEW KIND |
| — | — | — | `transform_species_list` | `ChangePartyPokemonSpecies+$16` | `35:65C8` · `878024` · `77FA92CF2173D101` (8) | change_mon_species.asm L17 | NEW KIND |
| — | — | — | `transform_struct_species` | `ChangePartyPokemonSpecies+$27` | `35:65D9` · `878041` · `77012100092AEA2F` (8) | change_mon_species.asm L24 | NEW KIND |
| — | — | — | `transform_hp_hi` | `ChangePartyPokemonSpecies+$4A` | `35:65FC` · `878076` · `227932E101050009` (8) | change_mon_species.asm L47 | NEW KIND |
| — | — | — | `transform_hp_lo` | `ChangePartyPokemonSpecies+$4C` | `35:65FE` · `878078` · `32E101050009FABE` (8) | change_mon_species.asm L49 | NEW KIND |
| — | — | — | `apex_preflight` | `ItemUseMedicine.useApexChip+$0F` | `03:5B43` · `56131` · `2277E1E5CD4D5AE1` (8) | item_effects.asm L1675-1677 | NEW KIND |
| — | — | — | `apex_commit` | `ItemUseMedicine.useApexChip+$11` | `03:5B45` · `56133` · `E1E5CD4D5AE10122` (8) | item_effects.asm L1678-1679 | NEW KIND |
| — | — | — | `apex_recalc_call` | `ItemUseMedicine.useApexChip+$13` | `03:5B47` · `56135` · `CD4D5AE101220009` (8) | item_effects.asm L1680 | NEW KIND |
| — | — | — | `npc_trade_add` | `InGameTrade_DoTrade+$83` | `1C:554F` · `464207` · `CD9A34CD0756CD34` (8) | in_game_trades.asm L153-155 | NEW KIND |
| — | — | — | `npc_trade_done` | `InGameTrade_DoTrade+$89` | `1C:5555` · `464213` · `CD3416CD95550603` (8) | in_game_trades.asm L158 | NEW KIND |
| — | — | — | `cable_remove` | `TradeCenter_Trade.doTrade+$77` | `01:5650` · `22096` · `CD9334FA3ECD4FEA` (8) | cable_club.asm L787 | NEW KIND |
| — | — | — | `cable_add` | `TradeCenter_Trade.doTrade+$A0` | `01:5679` · `22137` · `FA6BD13DEA92CF3E` (8) | cable_club.asm L804-805 | NEW KIND (assert FAIL as specified) |
| — | — | — | `cable_partial_save` | `TradeCenter_Trade.tradeCompleted+$2C` | `01:56F0` · `22256` · `218078061CC70E32` (8) | cable_club.asm L854 | NEW KIND |
| — | — | — | `daycare_withdraw` | `DaycareGentlemanText.enoughMoney+$27` | `15:69C8` · `354760` · `CDDC34FA67DAEA91` (8) | Daycare.asm L164-166 | NEW KIND |
| — | — | — | `checkpoint_delayframe_halt` | `DelayFrame+$17` | `00:1E8D` · `7821` · `7600F0D6A720F9C9` (8) | vblank.asm L111-113 | NEW KIND |
| — | — | — | `checkpoint_overworldloop` | `OverworldLoop` | `00:03D6` · `982` · `D721BD680635C7CD` (8) | overworld.asm L29 | NEW KIND |
| — | — | — | `checkpoint_init` | `Init` | `00:1D10` · `7440` · `F3AFE00FE0FFE043` (8) | init.asm L10-15 | NEW KIND |
| — | — | — | `checkpoint_softreset` | `SoftReset` | `00:1D07` · `7431` · `CDDD1DCD32380E20` (8) | init.asm L2-4 | NEW KIND |
| — | — | — | `checkpoint_start` | `_Start` | `00:0150` · `336` · `FE113E0128013DE0` (8) | start.asm L2-7 | NEW KIND |
| — | — | — | `checkpoint_vblank_vector` | `(raw address)` | `00:0040` · `64` · `C3F31DA7A0B5A450` (8) | home/header.asm L82 | NEW KIND |
| — | — | — | `rst_0000` | `(raw address)` | `00:0000` · `0` · `C3973215144120FF` (8) | home/header.asm L6 | NEW KIND |
| — | — | — | `rst_0008` | `(raw address)` | `00:0008` · `8` · `C3D038158B7728FD` (8) | home/header.asm L15 | NEW KIND |
| — | — | — | `rst_0010` | `(raw address)` | `00:0010` · `16` · `C3761EA8A6A7B350` (8) | home/header.asm L21 | NEW KIND |
| — | — | — | `rst_0018` | `(raw address)` | `00:0018` · `24` · `D70D20FCC9938C50` (8) | home/header.asm L26-30 | NEW KIND |
| — | — | — | `rst_0020` | `(raw address)` | `00:0020` · `32` · `C3AE00B6A8B3A750` (8) | home/header.asm L38 | NEW KIND |
| — | — | — | `rst_0028` | `(raw address)` | `00:0028` · `40` · `C3A53615AE7728FF` (8) | home/header.asm L45 | NEW KIND |
| — | — | — | `changebox_full_save_corrected` | `ChangeBox.yes+$35` | `1C:798A` · `473482` · `CDB5783EB6CDA533` (8) | save.asm L397-399 (inherited from `changebox_full_save`) | NEW KIND |
| — | — | — | `cable_add_corrected` | `TradeCenter_Trade.doTrade+$9D` | `01:5676` · `22134` · `CDCB34FA6BD13DEA` (8) | cable_club.asm L804-805 (inherited from `cable_add`) | NEW KIND |

Role of each table-2 kind: `capture_party_begin` = capture lands in the party (call-site anchor inside ItemUseBall.skipShowingPokedexData); `capture_party_end` = return point of the party capture (same call site, +3); `capture_box_begin` = capture lands in the box (call-site anchor inside ItemUseBall.sendToBox); `capture_box_end` = return point of the box capture (same call site, +3); `pc_deposit` = Bill's PC deposit (WaitForSoundToFinish after RemovePokemon); `pc_withdraw` = Bill's PC withdraw; `pc_release` = Bill's PC release; `changebox_full_save` = full SaveGameData from ChangeBox. FAIL as specified (+$38); superseded by changebox_full_save_corrected; `changebox_full_save_corrected` = corrected offset +$35 (`call SaveGameData`); `transform_base` = script transformation entry (ChangePartyPokemonSpecies); `transform_species_list` = wPartySpecies array write; `transform_struct_species` = per-mon struct species write; `transform_hp_hi` = new max-HP MSB -> current-HP MSB; `transform_hp_lo` = new max-HP LSB -> current-HP LSB; `apex_preflight` = APEX CHIP preflight (= .setDVs; HL = party mon struct); `apex_commit` = both DV bytes written, before .recalculateStats; `apex_recalc_call` = `call .recalculateStats`; `npc_trade_add` = NPC-trade `call AddPartyMon`; `npc_trade_done` = NPC-trade `call ClearScreen` (receipt final); `cable_remove` = Cable Club `call RemovePokemon`; `cable_add` = Cable Club `call AddEnemyMonToPlayerParty`. FAIL as specified (+$A0); superseded by cable_add_corrected; `cable_add_corrected` = corrected offset +$9D; `cable_partial_save` = Cable Club partial save (callfar SavePartyAndDexData); `daycare_withdraw` = daycare withdrawal (`call MoveMon` after `ld a,DAYCARE_TO_PARTY`); `trainer_staging` = FAIL row as specified (`_InitBattleCommon`+$48); superseded by trainer_staging_corrected; `checkpoint_delayframe_halt` = `halt` inside DelayFrame; `checkpoint_overworldloop` = OverworldLoop entry (`rst _DelayFrame`); `checkpoint_init` = Init (WRAM clear / latch reset); `checkpoint_softreset` = SoftReset; `checkpoint_start` = _Start; `checkpoint_vblank_vector` = raw-address VBlank vector (symbol/offset null); `rst_0000` = raw-address RST vector (symbol/offset null); `rst_0008` = raw-address RST vector (symbol/offset null); `rst_0010` = raw-address RST vector (symbol/offset null); `rst_0018` = raw-address RST vector (symbol/offset null); `rst_0020` = raw-address RST vector (symbol/offset null); `rst_0028` = raw-address RST vector (symbol/offset null).

## 3. Field delta — S1 vs the RC row schema

### S1 provides, the RC/`V` row schema lacks

1. `offset` — the symbol->anchor delta, recorded as a field. The RC `site()` (`gen_gen1_engine_signals.py:31-36`) folds the offset into `address`/`rom_offset` and drops it, so a `V`-shaped row cannot be re-anchored without the `.sym`. (Only 3 of the 17 vanilla rows preserve it, indirectly, via `capture_offset`.)
2. `source_assert_ok` — the per-row verdict of the source-text assert. The RC asserts are bare `assert` statements in generator code; nothing records which site they cover, and `V` has no such field.
3. `note` — the citation (`file Lx-Ly`) plus the derived instruction sequence and, where a callee is named, the resolved callee address (`CD 9A 34 = call $349A`). The RC row carries no citation at all.
4. `symbol: null` / `offset: null` — raw-address anchors (the 6 RST vectors and the VBlank vector). The RC/`V` schema assumes a symbol always resolves.
5. A FAIL + `*_corrected` shadow pair for the 3 mis-specified sites, i.e. the correction is part of the data rather than a commit message.
6. Per-title completeness with an explicit cross-title equality claim (REPORT §1). `V` differs per title in `bank`/`expected_hex` for 15 of 17 kinds (all but `add_party_mon` and `evolve`) but makes no claim about it.

### The RC/`V` row schema provides, S1 lacks

1. `capture_offset` **as a hook delta** (non-zero on `bag_received` 8, `save_witness` 3, `wild_begin` 5). S1 is uniformly 0 — see the legend warning.
2. Per-title file-level provenance: `source_commit`, `symbols_sha256`, `clean_sha1`, `starter_map`, and `addresses{}` (17 RAM symbols the Lua client reads). S1's file has only `schema` + `titles[].sites` — no ROM hashes, no symbol-table digest, no RAM-symbol map.
3. The acquisition-source record for `starter_begin`/`starter_end`: RC merges a census row (`group`, `target_symbol` = `AddPartyMon`, `map_id`, `scope_symbol`, `call{rom_offset, bank, return_address}`, `expected_call_hex`) and asserts `rom[offset:offset+3] == expected_call_hex`. S1's `starter` row has no callee field, no `map_id`, no return address.
4. An explicit slice `length` — both schemas infer it from `len(expected_hex)`, and the lengths disagree in kind: `V` slices are 3/6/8/9 bytes and several end mid-instruction (e.g. `blackout` `AFEA0BCFEA00`, `battle_end` `FA2BD1FE0420`), while S1 slices are uniformly 8.
5. `document` / `notes` at either level. **`V` has no `document` or `notes` key anywhere** (verified by substring search over the whole file); the only prose in either artefact is S1's per-row `note`.

## 4. Traps the generator must not walk into

1. **Do not copy `V.capture_offset` into an S1-shaped row** and do not copy S1's `capture_offset` (0) into a `V`-shaped row: the field means different things in the two files.
2. **The three FAIL rows must be replaced by their `*_corrected` shadow**: `trainer_staging` -> `InitBattleCommon+$48` (no underscore), `changebox_full_save` -> `ChangeBox.yes+$35`, `cable_add` -> `TradeCenter_Trade.doTrade+$9D`. As specified, all three land 3 bytes past the intended instruction or mid-instruction.
3. **`save_witness` cannot reuse the vanilla `expected_hex`**: pureRGB's post-`SaveGameData` instruction is `call ClearTextBox` (`CD 56 29`), vanilla's is `ld hl` (`21 A5 C4`), and S1 anchors its slice at +3, not +0.
4. **Banks are not inheritable.** `battle_end`/`EndOfBattle` is bank `$04` on vanilla and `$3A` on pureRGB (both files). PLAN §11.2 (Live 3) additionally records a same-address false hit for `SaveMenu.save+3` in bank `$0F` during a rival battle. Every hook must take its bank from S1.
5. **The five `UNMATCHED` kinds have no verified bytes on pureRGB.** If M1 must keep all 17 kind names, `add_party_mon`, `capture_box`, `move_mon`, `remove_pokemon` and `starter_end` need new source asserts + slices; S1 gives only the callee addresses (`AddPartyMon $349A`, `SendNewMonToBox $654B`, `MoveMon $34DC`, `RemovePokemon $3493`) and the call-site lines.
6. **`battle_begin`'s pureRGB bytes at `InitBattleCommon+0` are UNKNOWN** — S1 pins `+$48` for that symbol. The row above is a substitute, not a verification.

---

Counts: vanilla kinds 17 | S1 sites 49 (37 of them with no vanilla counterpart) | matched kinds 12 (6 SAME-SHAPE, 5 OFFSET-MOVED, 1 NEW-SYMBOL) | unmatched kinds 5 | rows whose pureRGB source citation is UNKNOWN: 6 (`battle_end`/`whiteout_endofbattle`, `add_party_mon`, `capture_box`, `move_mon`, `remove_pokemon`, `starter_end`).

