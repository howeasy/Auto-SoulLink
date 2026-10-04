# Polished Crystal 3.2.3 — engine signal sites and write checkpoints

The Polished Crystal equivalents of the vanilla Gen 2 signal list
(`data/games/gen2_crystal/engine_signals.json`, 43 Crystal sites) and write
checkpoints (`data/games/gen2_crystal/write_checkpoint.json`, 2 checkpoints).

**Vanilla side** is the pinned pokecrystal decomp at
`E:/Google Drive/SLink/.cache/pret/pokecrystal` (commit
`7a7881d0d62e0ddbd82dcf10e7116807487ac651`, per the `source` block of the signals JSON).
**Polished side** is v3.2.3 (commit `3fa43192379df5c3e7b09a08e4d5d79af4f02f42`,
`data/polished_sources.lock.json:8-9`), symbols from
`F:/slink-work/wt/polished/data/polished/polishedcrystal.sym` (line numbers cited),
source from `F:/slink-work/cache/polished/src`.

## How the vanilla hook works

Every vanilla site is a `CPU_INSTRUCTION` site: an SM83 execute-breakpoint at a
bank:addr, armed only while `hROMBank == site.bank` (each site carries a
`rom_bank_guard`). The hook reads live CPU/RAM state at the breakpoint — the
signals JSON names what it reads per site, e.g. `battle_faint` lists
`instructions: ["ld a, [wCurBattleMon]", "ld c, a", "ld hl, wBattleParticipantsNotFainted"]`
and `point_symbols` for `wCurBattleMon`, `wBattleMonHP`, `wPartyMon1`, `wBattleResult`.
Sites come in phases — a `_begin` / `_complete` pair brackets one logical operation so
the client can tell "player pressed withdraw" from "the copy landed".

## Verdict legend

| Verdict | Meaning |
|---|---|
| `same` | same symbol, same semantics; only the bank/addr moved |
| `renamed` | Polished uses a different symbol name for the same routine |
| `moved` | same symbol, relocated to a different routine |
| `changed-semantics` | the routine exists but its observable state differs (see note) |
| `absent` | no counterpart found in the Polished source or sym |
| `UNVERIFIED` | not established; needs a source read or a runtime check |


## 2. Battle, turn and faint

| Vanilla site | Vanilla symbol (pokecrystal) | Polished equivalent | Verdict | What the hook must read | Note |
|---|---|---|---|---|---|
| `battle_faint` | `UpdateFaintedPlayerMon`, `engine/battle/core.asm:2656` | **absent** — no `UpdateFaintedPlayerMon` and no `HandleFaintedMon*` in the sym | `absent` / `UNVERIFIED` | nearest confirmed anchors: `CheckCurPartyMonFainted` (`sym:12065`, `12:451d`), `CheckAnyFaintedMon` (`sym:13081`, `13:6a39`) | **SUPERSEDED (see BATTLE_FLOW.md §1):** the replacement was located — the boundary is `ldh [hBattleTurn], a` at `0f:44ca`, ROM-verified (`BATTLE_FLOW.md` coordinator note, `:241`-`:243`). This row's `absent` / `UNVERIFIED` verdict and "highest-priority open item" status are withdrawn. |
| `battle_end` | `ExitBattle`, `engine/battle/core.asm:8268` | `ExitBattle`, `sym:11109`, `0f:72e0` | `same` | `wBattleResult` (`sym:65756`, `01:d0f6`) | Bank unchanged at `$0F`; addr `$769e` -> `$72e0`. Instruction-level `expected_hex` must be re-read from the Polished source — not verified here. |
| `wild_ready` | `InitEnemyWildmon.skip_unown`, `engine/battle/core.asm:8206` | `InitEnemy.wildmon`, `sym:11108`, `0f:72bc` | `renamed` | `wEnemyMonSpecies`/form byte + `wEnemyMonLevel` (form byte is new — see §7) | Polished has one `InitEnemy` (`sym:11105`, `0f:7260`) with `.wildmon` (`:11108`) and `.partyloop` (`:11106`) labels; pokecrystal split these into two routines. |
| `trainer_ready` | `InitEnemyTrainer.done`, `engine/battle/core.asm:8180` | ~~`InitEnemy.partyloop`, `sym:11106`, `0f:72a5`~~ | ~~`renamed`~~ → **`wrong`** | — | **SUPERSEDED (see BATTLE_FLOW.md F5, EXPLODE_RIVAL.md §10):** `.partyloop` is the **boss-trainer happiness walk**, not the party build. The enemy party is constructed by `farcall ReadTrainerParty` at `core.asm:8040`. The row's Polished column, verdict and "what the hook must read" are all withdrawn; re-anchor on the send-out copy site, not on `.partyloop`. |
| `poison_faint` | `DoPoisonStep.DamageMonIfPoisoned`, `engine/events/poisonstep.asm:59` | `DoPoisonStep.DamageMonIfPoisoned`, `sym:13058`, `13:68cb` | `same` | `wBattleMonHP` (`sym:63880`, `00:c4b8`), `MON_STATUS` in the party record | Label preserved verbatim. Bank `$13` vs vanilla `$14`. |
| — (no vanilla site) | — | `BattleTurn`, `sym:10379`, `0f:4109` | **new** | see §6 `battle_hold` | Polished's battle-turn entry, the counterpart of pokecrystal's `MainInBattleLoop`. |

## 3. Boot, save and map

| Vanilla site | Vanilla symbol (pokecrystal) | Polished equivalent | Verdict | What the hook must read | Note |
|---|---|---|---|---|---|
| `new_game` | `NewGame`, `engine/menus/intro_menu.asm:61` | `NewGame`, `sym:1907`, `01:5ef8` | `same` | nothing beyond the reset epoch | Bank `$01` preserved. |
| `soft_reset` | `Reset`, `home/init.asm:1` | `SoftReset`, `sym:37`, `00:0150` | `renamed` | reset epoch only | Polished renamed `Reset` -> `SoftReset`; address `$0150` is **identical**, so only the label changed. `SoftResetSpecial` also exists (`sym` lookup), not yet mapped. |
| `save_completed` | `_SaveGameData.ok`, `engine/menus/save.asm:293` | `StartMenu_Save.saved`, `sym:4249`, `04:628f` | `renamed` / `UNVERIFIED` | save epoch | `_SaveGameData` does not exist; `SaveGameData` does (`sym:4664`, `05:478d`) without `.ok`. `StartMenu_Save.saved` is the caller-side success label. Which one the vanilla site corresponds to is **not established**. |
| `map_entry_complete` | `EnterMap.dontresetpoison`, `engine/overworld/events.asm:127` | `EnterMap.dontresetpoison`, `sym:22891`, `25:514b` | `same` | `wMapGroup`/`wMapNumber` | Sub-label preserved verbatim; vanilla bank `$25` (37) is also `$25`, so the bank is unchanged and only the address moved. |
| `continue_confirmed` | `Continue.Check2Pass`, `engine/menus/intro_menu.asm:359` | `Continue`, `sym:1924`, `01:60ca` | `renamed` / `UNVERIFIED` | party snapshot after copy | `Continue.Check2Pass` is gone; the sub-label naming changed. The `ld a, $8` the vanilla site sits on is **not verified** at `$60ca`. |
| `whiteout_before_heal` | `Special`, `engine/events/specials.asm:1` | `Special`, `sym:2648`, `03:401b` | `same` | party HP, whiteout flag | Bank and address identical to vanilla `$03:401b` — remarkable, but see §9 note 1 on the shared `Special` label. |

## 4. Acquisition — catch, gift, trade, contest, roamer, hatch

This is where the client distinguishes *how* a mon arrived. Each row states which
RAM the hook reads to make that distinction, and the rule is unchanged from vanilla:
the acquisition is only latched once the identity is **published into a party or box
record**, not when the script merely stages a species.

| Vanilla site | Vanilla symbol (pokecrystal) | Polished equivalent | Verdict | What the hook must read | Note |
|---|---|---|---|---|---|
| `capture_party` | `PokeBallEffect.not_celebi`, `engine/items/item_effects.asm:546` | `PokeBallEffect`, `sym:3373`, `03:63a0` | `moved` | `wCurPartyMon` (`sym:65782`, `01:d10c`) + `wCurPartySpecies` (`sym:65781`, `01:d10b`) | Vanilla sat on a sub-label that no longer exists; `PokeBallEffect` itself survives. The exact breakpoint inside it is `UNVERIFIED`. |
| `capture_box` | `PokeBallEffect.SendToPC`, `engine/items/item_effects.asm:609` | `PokeBallEffect.SendToPC`, `sym:3381`, `03:6590` | `same` | box slot + `wCurPartySpecies` | Sub-label and name preserved verbatim. |
| `capture_party_finalized` | `PokeBallEffect.return_from_capture`, `engine/items/item_effects.asm:695` | `PokeBallEffect.return_from_capture`, `sym:3392`, `03:666d` | `same` | `wBattleType`, party count | Same site serves capture, contest **and** roamer in both games — the caller disambiguates. |
| `capture_box_finalized` | same as above | same | `same` | as above | Deliberate alias in the vanilla list; kept. |
| `roamer_party_finalized` / `roamer_box_finalized` | `PokeBallEffect.return_from_capture` | same | `same` | `wBattleType` must be the roaming-battle type | Polished keeps roaming in the engine (`UpdateRoamMons`, `sym` present) rather than only in scripts. |
| `gift_begin` | `GivePoke`, `engine/pokemon/move_mon.asm:1619` | `GivePoke`, `sym:3333`, `03:5df9` | `same` | staged species **as a `dp` pair** | Species is 2 bytes: `LOW(species)`, `HIGH(species)<<5 \| form`. A hook that reads one byte silently halves the species id above 255. |
| `gift_party_finalized` / `gift_box_finalized` | `GivePoke.skip_nickname`, `engine/pokemon/move_mon.asm:1780` | `GivePoke.skip_nickname`, `sym:3342`, `03:5ee9` | `same` | party or box record after insert | `scripts` also has a `Script_givepoke` handler (`sym:23463`, `25:6fd2`) — the script opcode path, distinct from the engine routine. |
| `contest_selected` | `BugContest_SetCaughtContestMon.firstcatch`, `engine/events/bug_contest/caught_mon.asm:12` | `BugContest_SetCaughtContestMon.firstcatch`, `sym:3359`, `03:601b` | `same` | `wNamedObjectIndex`-style staged species (2-byte `dp`) | — |
| `contest_party_finalized` | `CheckPartyFullAfterContest.Party_SkipNickname`, `engine/pokemon/caught_data.asm:57` | same, `sym:12664`, `13:4453` | `same` | party record | — |
| `contest_box_inserted` | `CheckPartyFullAfterContest.TryAddToBox`, `engine/pokemon/caught_data.asm:88` | same, `sym:12665`, `13:447f` | `same` | box record | — |
| `contest_box_finalized` | `CheckPartyFullAfterContest.BoxFull`, `engine/pokemon/caught_data.asm:127` | same, `sym:12667`, `13:44d6` | `same` | box record | — |
| `hatch_species` | `HatchEggs.nottogepi`, `engine/pokemon/breeding.asm:246` | `HatchEggs.nottogepi`, `sym:5465`, `05:6fb6` | `same` | `wNamedObjectIndex` (`sym:66097`, `01:d26b`) | Label preserved, including the Togepi special case. |
| `hatch_finalized` | `HatchEggs.next`, `engine/pokemon/breeding.asm:345` | `HatchEggs.next`, `sym:5467`, `05:700e` | `same` | `wCurPartyMon` | `HatchEggs` itself is `sym:5463`, `05:6f56`. |
| `npc_trade_begin` | `DoNPCTrade`, `engine/events/npc_trade.asm:114` | `DoNPCTrade`, `sym:35735`, `3f:51bf` | `same` | trade struct: `dp` want, `dp` give | `NPCTRADE_GIVEMON`/`GETMON` are `rw` (`constants/npc_trade_constants.asm:4-5`) — both species are `dp` pairs in a fixed 31-byte record. |
| `npc_trade_finalized` | `DoNPCTrade.incomplete`, `engine/events/npc_trade.asm:196` | `DoNPCTrade` (`.incomplete` absent), `sym:35735` | `renamed` / `UNVERIFIED` | received party record | The sub-label is gone; the finalized offset inside `DoNPCTrade` is **not located**. |
| `link_trade_received` | `LinkTrade.done_animation`, `engine/link/link.asm:1978` | `LinkTrade.done_animation`, `sym:7337`, `0a:4b4b` | `same` | received party copy | — |
| `link_trade_saved` | `LinkTrade.save`, `engine/link/link.asm:2043` | `LinkTrade.save`, `sym:7339`, `0a:4bb1` | `same` | post-save party | `LinkTrade` is `sym:7325`, `0a:48f1`; `.do_trade` is `sym:7331`, `0a:49f7`. |
| `script_wild_staged` | `Script_loadwildmon`, `engine/overworld/scripting.asm:1141` | `Script_loadwildmon`, `sym:23349`, `25:6a90` | `same` | staged species + level (species is `dp`) | Script opcode path. Species byte offsets inside map scripts are **not** derivable from a `.sym` — see `tools/gen_upr_polished_ini.py` docstring. |
| `bag_ball_received` | `PutItemInPocket.done`, `engine/items/items.asm:230` | `PutItemInPocket`, `sym:3202`, `03:537e` | `renamed` / `UNVERIFIED` | ball pocket item id | `.done` sub-label absent; the breakpoint inside `PutItemInPocket` is **not located**. |

## 5. PC, box, evolution

| Vanilla site | Vanilla symbol (pokecrystal) | Polished equivalent | Verdict | What the hook must read | Note |
|---|---|---|---|---|---|
| `pc_deposit_begin` / `pc_deposit_complete` | `DepositPokemon`, `engine/pokemon/bills_pc.asm:1768` | `BillsPC_Deposit`, `sym:12250`, `12:5035` | `renamed` / `UNVERIFIED` | `wCurPartySpecies`, party slot, box cursor | Routine renamed `DepositPokemon` -> `BillsPC_Deposit`. The two vanilla sub-offsets (`:7094`, `:70a5`) have **no** named Polished counterpart; see NEWBOX.md for the Polished deposit path. |
| `pc_withdraw_begin` / `pc_withdraw_complete` | `TryWithdrawPokemon`, `engine/pokemon/bills_pc.asm:1820` | `BillsPC_Withdraw`, `sym:12249`, `12:5031` | `renamed` / `UNVERIFIED` | as above | Renamed `TryWithdrawPokemon` -> `BillsPC_Withdraw`. `BillsPC_Withdraw.release` exists (`sym` lookup) but the withdraw-completion sub-label does not. |
| `pc_release_party_begin` / `_complete` | `BillsPCDepositFuncRelease`, `engine/pokemon/bills_pc.asm:183` | `BillsPC_Release` (`sym:12440`, `12:5bc7`), `.ReallyReleaseMon` (`sym:12445`, `12:5c46`), `.done` (`sym:12441`, `12:5c14`) | `renamed` | party/box slot identity before and after removal | Three usable labels replace the one vanilla pair, which is an improvement: begin/complete can be bracketed on `.ReallyReleaseMon` / `.done`. |
| `pc_release_box_begin` / `_complete` | `BillsPC_Withdraw.release`, `engine/pokemon/bills_pc.asm:439` | see `BillsPC_Release` above; `BillsPC_Withdraw` `sym:12249`, `12:5031` | `renamed` / `UNVERIFIED` | box slot | The `.release` sub-label is not present at `BillsPC_Withdraw`. **UNVERIFIED.** |
| `change_box_begin` / `change_box_loaded` | `ChangeBoxSaveGame`, `engine/menus/save.asm:39` | `BillsPC_ChangeBox`, `sym:12498`, `12:5e88` | `renamed` / `UNVERIFIED` | active box index | Polished has no `ChangeBoxSaveGame`; box switching moved into the Bills PC. Two distinct phases exist in vanilla and **only one** Polished label is available, so the before/after pair cannot be reconstructed as-is. **UNVERIFIED.** |
| `evolution_species_published` | `EvolveAfterBattle_MasterLoop.skip_unown`, `engine/pokemon/evolve.asm:312` | `EvolveAfterBattle_MasterLoop`, `sym:5620`, `06:4020` | `renamed` | `wCurPartyMon`, the party species list | The `.skip_unown` sub-label is gone; the routine head survives at a different bank. Source: `engine/pokemon/evolve.asm:21`. |

**Standing caveat.** Symbol presence in a `.sym` proves the label was emitted, not
that the routine still does what the vanilla site relied on. Every row below is a
*source-level* mapping; nothing here has been observed firing on hardware.
`runtime_admission` in the vanilla JSON is still `NOT_GRANTED`, and the Polished
side starts from the same zero.

## 6. Write checkpoints

Vanilla defines two (`data/games/gen2_crystal/write_checkpoint.json`, under
`titles.crystal`): `battle_hold` id `battle-turn-before-determine-move-order`, and
`primary` id `ow-player-input-before-check-a-press`. Each carries source anchors, an
`execution_before` (instruction, bank, pc), an SP-window `caller_stack`, and
`oracles`.

| Checkpoint | Vanilla anchors | Polished equivalent | Verdict | Note |
|---|---|---|---|---|
| `battle_hold` | `engine/battle/core.asm:198` bank `$0F` addr `16778`; `execution_before = call DetermineMoveOrder` at pc `16788`; oracles `HandlePlayerMonFaint` `$0F:51AE`, `LostBattle` `$0F:5396` | `BattleTurn`, `sym:10379`, `0f:4109` | `renamed` / `UNVERIFIED` | The vanilla anchor sits inside the battle main loop, not on a `BattleTurn` label. Polished exposes `BattleTurn` but **not** `DetermineMoveOrder`, so `execution_before` has not been re-anchored. Both vanilla oracles (`HandlePlayerMonFaint`, `LostBattle`) are **absent from the Polished sym entirely** — see §2 `battle_faint`. **Do not port this checkpoint until the faint path is resolved.** |
| `primary` | `engine/overworld/events.asm:485` bank `$25` addr `26996`; `execution_before = call CheckAPressOW` at pc `27011`; `player_events_caller` bank `$25` addr `26655` | `OverworldLoop`, `sym:22879`, `25:50d5` | `renamed` / `UNVERIFIED` | `OverworldLoop` is the overworld main loop (`engine/overworld/events.asm:3`) — the right neighbourhood — but `CheckAPressOW` is not a Polished label. The SP window and `execution_before` pc must be re-derived from source. |

### 6.1 What "safe to write" means, and what changes

The vanilla Gen 2 client gates writes on `wScriptRunning` — a WRAM byte, nonzero
while a script or full-screen menu owns the game. Polished keeps that name
(`wScriptRunning`, `sym:66438`, `01:d437`) but also exposes the **HRAM** script
cursor: `hScriptBank` (`sym:70158`, `00:ffeb`) and `hScriptPos` (`sym:70159`,
`00:ffec`).

Consequence: `wScriptRunning == 0` alone is **not** sufficient in Polished. The
HRAM cursor says a script is mid-execution, and HRAM is not visible on the System
Bus — it needs the HRAM/CPU domain, as `docs/polished/RAM.md` documents. A gate
that reads only System-Bus WRAM will believe it is in a safe overworld window while
a script holds the game.

## 7. Register/RAM deltas the hook layer must absorb

1. **Species is 9-bit plus a form byte.** `dp` emits
   `db LOW(species), HIGH(species) << MON_EXTSPECIES_F | form`
   (`macros/data.asm:89-91`; `MON_EXTSPECIES_F = 5`,
   `constants/pokemon_data_constants.asm:244-245,253`). Decode
   `species9 = b0 | ((b1 & 0x20) << 3)`, `form = b1 & 0x1F`, `gender = b1 & 0x80`.
   **Every** single-byte species read in the vanilla client is wrong for Polished.
2. **The form byte shares storage with personality.** `MON_EXTSPECIES` aliases
   `MON_PERSONALITY + 1`, so it also carries gender, is-egg and the ability/nature
   bits. Reading `form` without masking `FORM_MASK` reads personality.
3. **Party PP at +22** — see `docs/polished/RAM.md`; the vanilla client assumes a
   different PP position.
4. **HRAM script cursor** — see §6.1; the domain matters, not just the address.
5. **Acquisition has two paths per source.** `Script_loadwildmon` (`sym:23349`) and
   `Script_givepoke` (`sym:23463`) are the script-opcode twins of `GivePoke`
   (`sym:3333`). Hooking only the engine routine misses every scripted gift/static.

## 8. Polished-only acquisition paths (no vanilla counterpart)

None of these has a row in the vanilla 43. Each is a new acquisition source that
SLink's link and dead-zone rules will see and must classify.

| Path | Source | Polished symbol | Verdict | Note |
|---|---|---|---|---|
| Wonder Trade | `engine/events/wonder_trade.asm` | not located in the sym | **new** / `UNVERIFIED` | Online trade of a party mon. Needs both a signal and a server-side ruling on whether the result is a legal link. |
| Apricorn / Kurt balls | `engine/events/kurt.asm`, `engine/events/fruit_trees.asm` | not located | **new** / `UNVERIFIED` | Ball item ids, not species immediates. Kurt's Apricorn ids are outside the vanilla `allowedItems` gate. |
| `giveegg` script opcode | `macros/scripts/events.asm:353-355` | handler not located | **new** / `UNVERIFIED` | Emits `dw`, not `dp` — the species arrives via a pointer, so the `givepoke`-style species-byte decode does **not** apply. |
| Mystri egg | `engine/events/odd_egg.asm:22`; `GiveMystriEgg`, `sym:16762`, `1a:5936` | **new** | The Odd Egg variant yields a different species than vanilla. `HatchEggs` still fires, but with different content — a vanilla-shaped hatch gate would report the wrong species. |
| Day Care hatched eggs | `engine/events/` Day Care scripts | `HatchEggs`, `sym:5463`, `05:6f56` | `changed-semantics` | Polished breeds differently; the hatch site is shared but the pre-hatch species is set elsewhere. **UNVERIFIED.** |

## 9. Risks and open items

1. **`Special` is a shared label.** The vanilla `whiteout_before_heal` site and the
   Polished `Special` (`sym:2648`, `03:401b`) are at the same bank and address.
   Expected for an early, stable routine, but the label alone cannot prove the
   surrounding code is unchanged. Re-read `engine/events/specials.asm` first.
2. ~~**`battle_faint` has no located Polished counterpart.** This blocks both the
   faint event and the `battle_hold` checkpoint, whose two oracles are exactly the
   faint routine and `LostBattle`. Highest priority.~~
   **SUPERSEDED (see BATTLE_FLOW.md §1–§2):** the counterpart is located and the
   checkpoint is **not** blocked. The `battle_faint` boundary is `0f:44ca`
   (ROM-verified); `LostBattle` exists at `0f:4ff6` and `HasPlayerFainted` at
   `00:3684` plays `HandlePlayerMonFaint`. The generated
   `data/games/polished_crystal/engine_signals.json` and `write_checkpoint.json`
   carry the resolved sites and are the authoritative artefacts now.
3. **Seven vanilla sub-labels do not survive in any form:**
   `UpdateFaintedPlayerMon`, `_SaveGameData.ok`, `Continue.Check2Pass`,
   `InitEnemyWildmon.skip_unown`, `InitEnemyTrainer.done`,
   `BillsPCDepositFuncRelease`, and `TryWithdrawPokemon`'s completion offset. Each
   needs a source read to re-anchor.
4. ~~**No `expected_hex` was computed.**~~ **SUPERSEDED (see
   `data/games/polished_crystal/engine_signals.json`, generated by
   `tools/gen_polished_engine_sites.py`):** the sites are now generated with their
   `expected_hex` from the release ROM. This document still quotes none.
5. **Nothing here has run.** No row is backed by a hardware observation.

## 10. Claims

Each entry is (absolute path, 1-indexed line, exact substring on that line).
All were verified against the files at the time of writing.

```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":11109,"expect":"ExitBattle"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":11105,"expect":"InitEnemy"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":11108,"expect":"InitEnemy.wildmon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":11106,"expect":"InitEnemy.partyloop"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10379,"expect":"BattleTurn"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":13058,"expect":"DoPoisonStep.DamageMonIfPoisoned"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1904,"expect":"NewGame"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":37,"expect":"SoftReset"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":5463,"expect":"HatchEggs"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":5465,"expect":"HatchEggs.nottogepi"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":5467,"expect":"HatchEggs.next"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":4664,"expect":"SaveGameData"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":4249,"expect":"StartMenu_Save.saved"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":217,"expect":"Special"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12250,"expect":"BillsPC_Deposit"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12249,"expect":"BillsPC_Withdraw"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12427,"expect":"BillsPC_Release"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12445,"expect":"BillsPC_Release.ReallyReleaseMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12441,"expect":"BillsPC_Release.done"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12498,"expect":"BillsPC_ChangeBox"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":5620,"expect":"EvolveAfterBattle_MasterLoop"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":35735,"expect":"DoNPCTrade"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22891,"expect":"EnterMap.dontresetpoison"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":238,"expect":"Continue"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":3373,"expect":"PokeBallEffect"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":3381,"expect":"PokeBallEffect.SendToPC"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":3392,"expect":"PokeBallEffect.return_from_capture"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":2651,"expect":"LinkTrade"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":7337,"expect":"LinkTrade.done_animation"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":7339,"expect":"LinkTrade.save"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":7331,"expect":"LinkTrade.do_trade"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":3202,"expect":"PutItemInPocket"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":3333,"expect":"GivePoke"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":3342,"expect":"GivePoke.skip_nickname"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":3359,"expect":"BugContest_SetCaughtContestMon.firstcatch"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12664,"expect":"CheckPartyFullAfterContest.Party_SkipNickname"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12665,"expect":"CheckPartyFullAfterContest.TryAddToBox"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12667,"expect":"CheckPartyFullAfterContest.BoxFull"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":23349,"expect":"Script_loadwildmon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":23422,"expect":"Script_givepoke"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22879,"expect":"OverworldLoop"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66438,"expect":"wScriptRunning"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":70158,"expect":"hScriptBank"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":70159,"expect":"hScriptPos"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65728,"expect":"wCurBattleMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63856,"expect":"wBattleMonHP"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":67524,"expect":"wPartyMon1"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65756,"expect":"wBattleResult"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66054,"expect":"wBattleType"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66097,"expect":"wNamedObjectIndex"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65781,"expect":"wCurPartySpecies"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65782,"expect":"wCurPartyMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":12065,"expect":"CheckCurPartyMonFainted"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":13081,"expect":"CheckAnyFaintedMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":2778,"expect":"GiveMystriEgg"},{"path":"F:/slink-work/cache/polished/src/macros/data.asm","line":89,"expect":"MACRO? dp ; db species, extspecies | form"},{"path":"F:/slink-work/cache/polished/src/macros/data.asm","line":91,"expect":"db LOW(\\1), HIGH(\\1) << MON_EXTSPECIES_F | \\2"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":244,"expect":"DEF EXTSPECIES_MASK  EQU %00100000"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":245,"expect":"DEF FORM_MASK        EQU %00011111"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":253,"expect":"DEF MON_EXTSPECIES_F EQU 5"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":161,"expect":"DEF MON_EXTSPECIES EQU MON_PERSONALITY + 1"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":353,"expect":"const giveegg_command"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":354,"expect":"MACRO giveegg"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/evolve.asm","line":21,"expect":"EvolveAfterBattle_MasterLoop:"},{"path":"F:/slink-work/cache/polished/src/engine/overworld/events.asm","line":3,"expect":"OverworldLoop::"},{"path":"F:/slink-work/cache/polished/src/engine/events/odd_egg.asm","line":22,"expect":"GiveMystriEgg::"},{"path":"F:/slink-work/cache/polished/src/data/events/npc_trades.asm","line":1,"expect":"NPCTrades:"},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/engine_signals.json","line":2,"expect":"\"schema\": \"gen2-engine-signals-v1\""},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/engine_signals.json","line":8,"expect":"\"commit\": \"7a7881d0d62e0ddbd82dcf10e7116807487ac651\""},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/engine_signals.json","line":17,"expect":"\"runtime_admission\": \"NOT_GRANTED\""},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/engine_signals.json","line":22,"expect":"\"battle_faint\""},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/write_checkpoint.json","line":98,"expect":"\"battle-turn-before-determine-move-order\""},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/write_checkpoint.json","line":448,"expect":"\"ow-player-input-before-check-a-press\""},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/write_checkpoint.json","line":86,"expect":"\"call DetermineMoveOrder\""},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/write_checkpoint.json","line":436,"expect":"\"call CheckAPressOW\""},{"path":"F:/slink-work/wt/polished/data/polished_sources.lock.json","line":8,"expect":"\"tag\": \"v3.2.3\""},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":8038,"expect":"ExitBattle"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/pokemon/move_mon.asm","line":1619,"expect":"GivePoke:"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/pokemon/breeding.asm","line":201,"expect":"HatchEggs"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/home/init.asm","line":1,"expect":"Reset:"}]
```

## Coordinator note (2026-10-04): leads for the `battle_faint` blocker

The doc's absence finding is about the vanilla label names. The Polished sym does hold a restructured faint path: `ResolveFaints` 0f:44af, `FaintUserPokemon` 0f:4cd2, `PlayerMonFaintHappinessMod` 0f:4f49, `MonFaintedAnimation` 0f:5090, `HasPlayerFainted` 00:3684, `wWhichMonFaintedFirst` 00:c54f (`engine/battle/core.asm:708`, `:2089`). The next card must read that source to pick the `before_party_copyback` equivalent; none of these is claimed to be it yet.
