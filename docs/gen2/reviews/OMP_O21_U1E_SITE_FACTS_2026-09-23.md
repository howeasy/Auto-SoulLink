# OMP facts — gen2-O21 (U1e engine sites) + O22 (P4 items), 2026-09-23

Crash-proof copy of the reply for task `cx-10e9b606` (peer omp, orchestrator claude). READ-ONLY card:
this file is the only thing written; not committed.

Pins: pokecrystal `7a7881d0d62e0ddbd82dcf10e7116807487ac651` (C) and pokegold
`656583c939d30f920a316177311a502dd222b57c` (G; Silver builds from it and keeps its own `.sym`).
Trees `.cache/gen2-build/{pokecrystal,pokegold}`; built artifacts
`data/gen2/{pokecrystal,pokegold,pokesilver}.{sym,map}`; packs
`data/games/gen2_{crystal,gold,silver}/{engine_signals,write_checkpoint}.json`. Addresses are hex
`bank:addr` (the pack JSON stores decimal; converted here). ROM bytes cited below were re-read from
the pinned `.gbc` files, not only from the packs.

---

## SUMMARY

O21 (U1e): all eleven pack rows for poison_faint, evolution, gift, egg_hatch, npc_trade and whiteout
resolve to their pinned `.sym` labels with no address mismatch; each row's `expected_hex` decodes to
the source anchor cited below. None of the six families is physically proven today (every title's
receipt proves only wild_ready, capture_party, capture_party_finalized, battle_end, save_completed,
battle_faint), but the arming machinery is generic — the missing work is a stimulus per family plus a
per-family PYDEC oracle. Proof cost, cheapest first: **poison_faint < gift < evolution < npc_trade <
egg_hatch < whiteout**.

O22: (a) the START-menu `.Items` table can simply grow by one 6-byte row inside its own bank —
Crystal 04:66eb, Gold/Silver 04:6ab2, bank `$04`, free space after the section 618 B / 509 B — because
**no receipted engine site or checkpoint row lives in bank 4**; moving the table into the SLink bank is
strictly more code, not less. (b) The fewest-byte receptionist redirect is the **2-byte object-event
script pointer** (C `64:73b1-73b2`, currently `9d 68`; G/S `5c:545b-545c`, `6f 4d`); the `special`
table alternative is a 3-byte `dba` (C `03:402c`, G/S `03:423c`) and drags the vanilla continuation
after `SetBitsForLinkTradeRequest` with it. (c) The fade byte to poll is **`wMusicFade`** (C `00:c2a7`,
G/S `00:c1a7`; nonzero while a fade runs, cleared by `FadeMusic`), and **`PlaySFX` refuses a
busy-channel SFX — it never queues**; a priority-winning SFX instead *steals* all four SFX channels.

---

## FINDINGS

### F1 — O21 site table (pack row → `.sym` cross-check, no mismatches)

`engine_signals.json` stores bank/addr decimal; converted to hex here. `expected_hex` is the pack's
exact ROM slice; the anchor column is the source instruction it decodes to.

| family | pack id | symbol (+offset) | Crystal | Gold | Silver | expected_hex C / G | guards |
|---|---|---|---|---|---|---|---|
| poison | `poison_faint` | `DoPoisonStep.DamageMonIfPoisoned` +27 | `14:4649` | `14:467f` | `14:467f` | `3e20cd17393600` / `3e20cd3a3b3600` | 0 |
| evolution | `evolution_species_published` | `EvolveAfterBattle_MasterLoop.skip_unown` +6 | `10:63f2` | `10:63ee` | `10:63ee` | `e5` / `e5` | 0 |
| gift | `gift_begin` | `GivePoke` +0 | `03:6277` | `03:6290` | `03:628e` | `d5` / `d5` | 0 |
| gift | `gift_party_finalized` | `GivePoke.skip_nickname` | `03:63b6` | `03:6391` | `03:638f` | `c8` / `c8` | 6 |
| gift | `gift_box_finalized` | `GivePoke.skip_nickname` | `03:63d3` | `03:63ae` | `03:63ac` | `c9` / `c9` | 5 |
| egg | `hatch_species` | `HatchEggs.nottogepi` +6 | `05:6fc5` | `05:736d` | `05:736d` | `ea65d2` / `ea51d1` | 0 |
| egg | `hatch_finalized` | `HatchEggs.next` +0 | `05:707d` | `05:7425` | `05:7425` | `2109d1` / `2105d0` | 4 |
| npc trade | `npc_trade_begin` | `DoNPCTrade` +0 | `3f:4c63` | `3f:4a69` | `3f:4a69` | `1e01` / `1e01` | 0 |
| npc trade | `npc_trade_finalized` | `DoNPCTrade.incomplete` +165 (C) / `DoNPCTrade` +292 (G/S) | `3f:4dc1` | `3f:4b8d` | `3f:4b8d` | `c9` / `c9` | 4 |
| whiteout | `whiteout_before_heal` | `Special` (CPU dispatch entry) | `03:401b` | `03:422b` | `03:422b` | `212940191919` / `213942191919` | 8 |

Cross-checks done here: `data/gen2/*.sym` labels/addresses for every row (e.g. `GivePoke` S
`03:628e`, `HatchEggs.nottogepi` S `05:7367`, `DoPoisonStep.DamageMonIfPoisoned` S `14:4664`,
`HatchEggs.next` S `05:7425`); pack `rom_offset` obeys `(bank-1)*0x4000 + addr`; and direct ROM reads
for the whiteout/gift rows (`C 04:64ce` = `4c f5 64 54 0f 2e 00 8b 28 0f 1b 00`, byte-equal to the
pack's `script_context.expected_hex`; `C 03:407a` = `03 58 46` = `HealPartySpecial`, entry index 27;
`G 03:422b` = `21 39 42 19 19 19`).

### F2 — poison_faint (`DoPoisonStep.DamageMonIfPoisoned`, C `14:4649` / G,S `14:467f`)

- Anchor: C `engine/events/poisonstep.asm:88-90` — the faint branch of `.DamageMonIfPoisoned`
  (`:59`): after 1 HP of poison damage left HP 0, `ld a, MON_STATUS` (`:88`), `call
  GetPartyParamLocation` (`:89`), `ld [hl], 0` (`:90`). The gold file is byte-identical at the same
  lines (its `GetPartyParamLocation` is `00:3b3a`).
- Fires: from the overworld step handler, once every 4 steps, for each poisoned party mon — C
  `engine/overworld/events.asm:905-912` (`wPoisonStepCount` gate `:906-911`, `farcall DoPoisonStep`
  `:912`); G `:893-900`. `wCurPartyMon` names the affected slot; the status byte is zeroed right after
  the site, so a hook must snapshot at/before it.
- Not fired by: a healthy mon (`ret z`, `:65`), an already-fainted mon (`ret z`, `:74`), or the
  non-fatal tick (`.not_fainted`, `:95`).
- Same-family follow-on: the poison-faint chain continues into the whiteout script
  (`.Script_MonFaintedToPoison` `:109` → `farsjump OverworldWhiteoutScript` `:116`), so one poisoned
  mon + steps can serve both the poison_faint positive and the whiteout poison positive.

### F3 — evolution (`EvolveAfterBattle_MasterLoop.skip_unown` +6, C `10:63f2` / G,S `10:63ee`)

- Anchor: C `engine/pokemon/evolve.asm:312-317` — `.skip_unown:` (`:312`), then `ld a,
  [wTempMonSpecies]` (`:315`), `ld [hl], a` (`:316`) publishes the evolved species into
  `wPartySpecies + wCurPartyMon`, and `push hl` (`:317`) is the site (`e5`). G `:313-318`.
- The pack carries no guards; the binder contract needs A == the slot's struct species, HL ==
  `wPartySpecies + wCurPartyMon`, `wLinkMode == 0`, a species with a pre-evolution, and no second
  party record with the same key. Old species comes from the generated `identity_migration` table —
  **not** `wEvolutionOldSpecies`, which shares a WRAM union byte with `wListMovesLineSpacing`
  (`ram/wram.asm:2582`, gold `:2062`) and is overwritten by `learn.asm:144-145` on a level-up move.
- Negative controls: a B-press makes `EvolutionAnimation` return carry → `jp c, CancelEvolution`
  (C `evolve.asm:228`), which loops back without executing `.skip_unown` (`:379-384`); a link-trade
  evolution runs `EvolvePokemon` with `wLinkMode` set (`link.asm:1998`) and is refused.

### F4 — gift (`GivePoke`, three rows; C `03:6277/63b6/63d3`)

- Anchor: C `engine/pokemon/move_mon.asm:1619` (`GivePoke::`), `.skip_nickname:` `:1780`, party
  success `ret z` `:1785` (B=0, Z=1), box success `:1795-1796` (B=1), `.FailedToGiveMon`
  `:1798-1802` (B=2). G `:1632`, `:1759`, `:1764`, `:1775`, `:1777`.
- The three rows split cleanly: `gift_begin` = the entry (`push de`), `gift_party_finalized` /
  `gift_box_finalized` = the two success returns, distinguished by B and by the 6/5 guards (party vs
  box). A failed insert returns B=2 and must not emit.
- Stimulus already exists for the party row: the committed `<title>_town` fixture play takes the
  starter through the game's own `givepoke TOTODILE, 5, BERRY` (C `maps/ElmsLab.asm:212`; the source
  line is asserted in `tools/gen2_fixtures.py:405`). Replaying that play with the gift rows armed
  should fire begin + party_finalized. [INFERENCE: the played save is "Elm's lab after the starter",
  which implies the givepoke executed; no receipt records the op.]
- The box row needs a full party (6) plus a gift — no fixture does that today.

### F5 — egg_hatch (`HatchEggs`, two rows; C `05:6fc5` / `05:707d`)

- Anchors: C `engine/pokemon/breeding.asm:246` (`.nottogepi:`) with the site instruction
  `ld [wNamedObjectIndex], a` at `:253` (the parallel-species marker write, `ea65d2`; Gold `ea51d1`);
  and `:345` (`.next:`) with the site at `:346` (`ld hl, wCurPartyMon`, `2109d1`), `.done` `:354`.
  G `:244/:251` and `:343/:344/:351`.
- Shared paths: `.next` is the party loop head and runs for every slot (egg or not); `.nottogepi`
  runs for every non-Togepi egg. `hatch_finalized` therefore requires the same-slot `hatch_species`
  latch (pack requires-prior, 4 guards).
- Stimulus: **none exists** — no daycare/egg fixture of any kind. `DoEggStep` is driven from the same
  step handler (C `events.asm:898`) and the hatch entry is `OverworldHatchEgg` (`breeding.asm:198`).

### F6 — npc_trade (`DoNPCTrade`, C `3f:4c63` / `3f:4dc1`)

- Anchors: C `engine/events/npc_trade.asm:114` (`DoNPCTrade:`), begin site = `ld e, NPCTRADE_GIVEMON`
  (`1e01`); `.incomplete:` `:196`; the finalized site is the terminal `ret` at `:273` (pack `c9`),
  immediately before `GetTradeAttr:` `:275`. G `:114`, terminal `ret` `:244`.
- Receiver identity: `wPartyCount - 1` — C `:264-266` (`ld a,[wPartyCount]` / `dec a` / `ld
  [wCurPartyMon],a`) then `farcall ComputeNPCTrademonStats`. `wCurPartyMon` is restored afterwards
  (`:262`, `:268-269`), so it must not be used to select the received record.
- Stimulus: walk an NPC trader (Violet City or later) with the requested species in the party; the
  begin row carries a consume-once prior guard (pack requires-prior), and the trade menu must be
  walked to the terminal ret.

### F7 — whiteout (`Special` CPU entry, C `03:401b` / G,S `03:422b`)

- The hook is **not** the script: `Script_Whiteout` is script bytecode. The site is the CPU `Special`
  dispatch entry (`engine/events/specials.asm:1-13`, `ld hl, SpecialsPointers` + `add hl,de`×3 +
  `rst FarCall`), hence the 8-part guard:
  1. `DE == 27` — `(HealPartySpecial - SpecialsPointers)/3`; `HealPartySpecial` = `03:407a`,
     `SpecialsPointers` = `03:4029` → 27 (verified in `.sym` and ROM `03:407a` = `03 58 46`).
  2. `wScriptBank == 4` and 3. `wScriptPos == 25818` (`$64da`) — the byte after the `special HealParty`
     operand in `Script_Whiteout` (`04:64ce` + 12; ROM bytes `4c f5 64 54 0f 2e 00 8b 28 0f 1b 00`,
     the last three `0f 1b 00` = `special 27`).
  4. Stack words: SP+0 = `$2d6e` (the `FarCall_hl`→`FarCall_JumpToHL` return), SP+4 = `$6e34`
     (`Script_special`'s farcall return after the saved AF).
  plus the pinned script spans in bank 4: `Script_BattleWhiteout` `$64c1`, `OverworldWhiteoutScript`
  `$64c8`, `Script_Whiteout` `$64ce`, `.bug_contest` `$64f2`, `.WhitedOutText` `$64f5` (Gold/Silver
  `$68a3-$68db`).
- Why the guard is needed: `special HealParty` is called from at least twelve other scripts (C
  `maps/CherrygroveCity.asm:173`, `ElmsLab.asm:311`, `FastShipCabins_NNW_NNE_NE.asm:92`,
  `FastShipCabins_SW_SSW_NW.asm:73`, `HallOfFame.asm:40`, `MrPokemonsHouse.asm:115`,
  `Route26HealHouse.asm:19`, `SilverCaveRoom3.asm:32`, `SlowpokeWellB1F.asm:69`,
  `TeamRocketBaseB2F.asm:170`, `engine/events/sacred_ash.asm:49`, and the whiteout script itself).
  Those ordinary heals are the negative control.
- Stimulus: a party wipe (battle loss) or the poison-faint chain (F2); the row is `before_heal`, so
  the proof must snapshot party identity before `HealParty` runs.

### F8 — O21 proof-cost ranking (cheapest → most expensive)

1. **poison_faint** — zero pack guards, overworld-only, no UI, identity witness the same shape as the
   proven `battle_faint`; the only gap is a poisoned mon, and the same stimulus feeds whiteout's
   poison positive. (Stimulus source not established here — see UNKNOWN.)
2. **gift (party row)** — the stimulus is already played by the committed town fixture; cost is the
   6-guard success latch and the party/box split; the box row needs a new (full-party) stimulus.
3. **evolution_species_published** — zero pack guards and the identity table is generated, but needs a
   mon one level short + a won battle (or a stone) plus the timed B-press cancel negative.
4. **npc_trade** — two rows, consume-once prior, a trader NPC and a specific species in the party.
5. **egg_hatch** — two rows with a same-slot latch and **no fixture of any kind** (daycare route, egg,
   long step counts).
6. **whiteout** — one row, but at the hottest CPU site (`Special`) with an 8-part guard; needs a wipe
   plus the ordinary-heal negatives.
(2/3/4 are close and their order depends on how stimulus cost is weighted; 1 and 6 are the clear
ends.)

### F9 — O22a: START menu SLINK row can grow in place; no receipted site lives in bank 4

- Table: `StartMenu.Items` = 9 rows × 6 bytes (`dw fn, dw string, dw desc`) = **54 bytes**.
  C `04:66eb-$6720` (`engine/menus/start_menu.asm:177` label, rows `:179-187`; constants `:2-10`);
  G/S `04:6ab2-$6ae7` (same line numbers in `pokegold/engine/menus/start_menu.asm`).
- Bank/section: ROMX bank **`$04`**, section `bank4` — C `$4000-$7d95`, free `$7d96-$7fff`
  = **618 B**; G/S `$4000-$7e02`, free `$7e03-$7fff` = **509 B** (`data/gen2/*.map`).
- The menu runs in bank 4: `StartMenu` (`04:65cd`) is entered by `callasm StartMenu` from
  `StartMenuScript` (`engine/overworld/events.asm:844-846`), the script's bank is
  `BANK(StartMenuScript)` = 4 (`:826-828`), and `callasm` far-calls with the operand's bank
  (`engine/overworld/scripting.asm:254-263`). The table and strings are then read **in the running
  bank with no switch**: `home/menu.asm:700-704` and `:745-749` (`ld hl, wMenuDataPointerTableAddr` →
  deref) and `StartMenu.GetMenuAccountTextPointer` (`start_menu.asm:275-285`).
- Receipted sites / checkpoint rows, by bank — none in bank 4:
  - U1 receipts (6 proven per title; banks `$03`, `$05`, `$0f`): C `0f:769e` ExitBattle, `0f:51aa`
    UpdateFaintedPlayerMon, `0f:7648` InitEnemyWildmon.skip_unown, `03:6adb` PokeBallEffect.not_celebi,
    `03:6be2` PokeBallEffect.return_from_capture, `05:4c6a` _SaveGameData.ok (plus `03:6b44`
    PokeBallEffect.SendToPC listed as absent); G/S `0f:7456`, `0f:50f4`, `0f:7400`,
    `03:6b50/6c4b` (S `03:6b4e/6c49`), `05:4d0d`.
  - U2 checkpoint rows: 15 WRAM predicates per title (C `wMapStatus $d432`, `wMapEventStatus $d433`,
    `wScriptRunning $d438`, `wScriptMode $d437`, `wScriptFlags $d434`, `wScriptStackSize $d43c`,
    `wJoypadDisable $cfbe`, `wGameLogicPaused $c2cd`, `wInputType $c2c7`, `wBattleMode $d22d`,
    `wStateFlags $d0ed`, `hMapEntryMethod $ff9f`, `wLinkMode $c2dc`, `hSerialConnectionStatus $ffcb`,
    `wSavedAtLeastOnce $d4b4`; G/S shifted) plus two ROM anchors per title, both in bank `$25`:
    C `25:6974` (ow_player_input) and `25:681f` (player_events_caller); G/S `25:68a7` and `25:675e`.
    (The predicates are WRAM addresses — a ROM section growth cannot move them; the anchors are the
    only ROM-pinned checkpoint rows.)
  - The pack's only bank-4 pins are the whiteout script spans (`$64c1-$64f9` C, `$68a3-$68db` G/S) —
    all **before** `$66eb`/`$6ab2`, so a table growth cannot touch them.
- Capacity: `wMenuItemsList:: ds 16` (C `ram/wram.asm:2224`, G `:1682`) → 15 rows max; the list is
  built in `.SetUpMenuItems` (`:287-345`) with `.AppendMenuList` (`:357-361`), so a 10th row costs one
  `ld a, STARTMENUITEM_SLINK / call .AppendMenuList` (5 B) in the same bank. `.MenuReturns` (`:71-78`)
  is indexed by the handler's return code, not by row index, and needs no growth; the handler can
  mirror `StartMenu_Option` (`:431-437`: `call FadeToMenu; farcall …; ld a, 6; ret`).
- Verdict: grow in place. Total new bytes ≈ 40-60 (row 6 + string ~6 + desc ~21 + handler ~6-10 +
  append 5), all inside bank 4's free space. Nothing after the table is receipted or guard-pinned, so
  **no receipt reopens**; the bank-4 symbol shift is a gate-6c "declared hook span" listing, not a
  reopened site. Moving the table into the SLink bank would instead require a farcall-based read path
  or a WRAM copy of table+strings (≈330 B) plus a trigger, because the menu code dereferences them in
  the running bank.

### F10 — O22b: the 2-byte object-event script pointer is the fewest-byte redirect

- The trade receptionist exists in exactly one map file per title (`maps/PokeCenter2F.asm` is the
  shared 2F map of every Pokémon Center; `grep -rln LinkReceptionistScript_Trade maps/` returns only
  that file in both pins).
- **Candidate (a) — object-event `script` word, 2 bytes.** The row is C `maps/PokeCenter2F.asm:1039`
  / G/S `:590`; the `dw` is the 12th argument (`macros/scripts/maps.asm:113-140`; the script field is
  at record offset 9). ROM bytes: **C `64:73b1-73b2` = `9d 68`** (`LinkReceptionistScript_Trade` at
  `64:689d`), **G/S `5c:545b-545c` = `6f 4d`** (`5c:4d6f`). Verified by dumping the object block
  (`C 64:73a8` = `38 06 09 06 00 ff ff a0 00 9d 68 ff ff`; `G 5c:5452` = `38 06 09 06 00 ff ff a0 00
  6f 4d ff ff`).
  Constraint: an object script runs in the **map's** bank — `TryObjectEvent.script`
  (`engine/overworld/events.asm:583-590`) reads `MAPOBJECT_SCRIPT_POINTER` then `call
  GetMapScriptsBank` / `call CallScript` (`home/map.asm:924-935` sets `wScriptBank`); the pointer's own
  high byte is not a bank. So the replacement script must live in bank `$64` (C) / `$5c` (G/S), where
  the free space is `$7688-$7fff` = **2424 B** / `$5609-$7fff` = **10743 B**. It can then
  `callasm <bank>,<addr>` (`scripting.asm:254-263`) into the SLink bank for the heavy lifting. It also
  covers the Crystal mobile branch, because that branch lives inside the same script.
- **Candidate (b) — `special` table entry, 3 bytes.** `SpecialsPointers` (`data/events/special_pointers.asm:9`,
  `add_special` = `dba`, 3 bytes) at C `03:4029` / G/S `03:4239`; the trade row is index 1, i.e. bytes
  **C `03:402c-402e`**, **G/S `03:423c-423e`** (currently `0a e8 5c` / `0a 22 5b`). Its only caller is
  the trade script (C `maps/PokeCenter2F.asm:83`, G/S `:62`), so no other script is touched; dispatch
  (`engine/events/specials.asm:1-13`) `rst FarCall`s with the entry's bank, so the target may live in
  the SLink bank. Cost: the vanilla script **continues** after the special (`writetext Text_PleaseWait`
  → `special WaitForLinkedFriend` → …), so the replacement must hand control back into or out of that
  continuation (e.g. by rewriting `wScriptPos`), whereas (a) replaces the whole interaction.
- Fewest bytes changed: **(a) 2 bytes** vs (b) 3 bytes; both are same-size edits, so no symbol moves
  either way, and no receipt lives in `$64`/`$5c` (see F9's bank list) in any case. Note the map file
  has no `SECTION`; the enclosing sections are declared in `data/maps/scripts.asm` (C `:328` "Map
  Scripts 17" + `INCLUDE` `:342`; G/S `:377` "Map Scripts 26" + `:389`).

### F11 — O22c: the fade byte is `wMusicFade`; busy-channel SFX is refused, never queued

- Fade state: **`wMusicFade`** — C `ram/wram.asm:65-70` (`00:c2a7`), G/S `:57-62` (`00:c1a7`);
  nonzero while a fade runs, bit 7 = `MUSIC_FADE_IN_F` (`constants/audio_constants.asm:129-130`),
  bits 0-5 = frames per volume step. `wMusicFadeCount` (C `:71`, G `:63`) is the per-step countdown;
  `wMusicFadeID` (dw; C `:72`, G `:64`) is the destination song. This is the Gen 1
  `wAudioFadeOutControl` analogue by shape (the Gen 1 side is not verifiable from these pins).
- Consumer: `FadeMusic` (`audio/engine.asm:603-712` both pins) opens with `ld a,[wMusicFade]; and a;
  ret z` (`:614-616` C) and clears it to 0 at `.quit` (`:668-670`) and `.maxvolume` (`:703-705`). It is
  called from `_UpdateSound` (`:204`), which the VBlank ISR drives (`VBlank_Normal`
  `home/vblank.asm:50`, call at `:141` C / `:143` G). **The engine will not hold anything for the
  service** — PlaySFX does not consult `wMusicFade`, so the hold is the service's own poll.
- SFX with busy channels: **REFUSED (dropped), not queued.** `PlaySFX` (C `home/audio.asm:180-218`,
  G `:180-218`): `call CheckSFX` (`:190`) → `jr nc, .play` when no SFX channel is on; otherwise `ld
  a,[wCurSFX]; cp e; jr c, .done` (`:194-196`) → drop when the playing id is numerically lower
  (higher priority — the routine's own comment says ids are ordered highest to lowest). Falling
  through, `.play` does `ld a, e; ld [wCurSFX], a; call _PlaySFX` (`:205-206`). `_PlaySFX`
  (`audio/engine.asm:2472-…`) **clears all four SFX channels first** (`res SOUND_CHANNEL_ON` on ch5-8
  plus hardware resets), so a priority-winning SFX *steals* the channels; nothing is ever queued.
  `CheckSFX` (C `:504-522`, G `:477-495`) tests ch5-8 `SOUND_CHANNEL_ON`. No DI anywhere in PlaySFX
  (it only saves/restores `hROMBank`), and `wCurSFX` is written only by PlaySFX and never cleared when
  an SFX ends.
- The P4 plan §3 claim "`PlaySFX` takes `de`, gates on `CheckSFX` (ch5-8 on) plus the `wCurSFX`
  priority, and has no DI (`home/audio.asm:180-218, 504-522`)" is **confirmed** at the Crystal pin.

---

## DISAGREEMENTS

The orchestrator's conclusions were withheld, so these are the points where a different reading is
likely and would be wrong:

1. **P4 §7's framing of the START row** — "A 10th row either grows that bank (reopens its site
   receipts, gate 6c lists it) or moves the table into the SLink bank". Nothing in bank 4 is
   receipted: the U1 receipts are banks `$03/$05/$0f`, the checkpoint anchors are bank `$25`, and the
   only bank-4 pins in the packs (the whiteout script spans) sit *before* the table. So growth
   reopens nothing; there is no trade-off against moving.
2. **P4.3a's "script-pointer or `special`-table word"** — the specials entry is a 3-byte `dba`, not a
   word, and the specials route leaves the vanilla script running after the special. If "fewest bytes"
   is the criterion, the 2-byte object pointer wins on both counts (bytes and control).
3. **P4 §3's hold semantics** — the engine neither queues a busy-channel SFX nor delays one during a
   fade; both holds must be implemented in the SLink service by polling `wMusicFade` / `CheckSFX`. A
   design that expects the engine to hold a cue would lose it silently.

## UNKNOWN / UNVERIFIED

- **poison_faint stimulus**: no fixture evidence found of a poisoned party mon; whether the battle
  fixture's save or route can produce one is not established here. Settle by reading the battle
  fixture's party status bytes (PYDEC) or by adding a Weedle/poison route step.
- **gift box row stimulus**: no fixture fills the party to six, so the box return path has no planned
  positive.
- **egg_hatch stimulus**: nothing exists (no daycare route, no egg).
- **Town-fixture givepoke execution**: the save state implies it and the source line is asserted in
  `tools/gen2_fixtures.py:405`, but no receipt records the op; marked INFERENCE above.
- **Gen 1 `wAudioFadeOutControl`**: the analogue mapping is by name/shape only; Gen 1 is outside these
  pins.
- **10-row menu layout**: the header coords are full-height and `wMenuItemsList` allows 15, so 10 rows
  fit by construction; no visual/physical check was made.

## RECOMMENDATION

- **O21**: arm and prove `poison_faint` first (cheapest; also the whiteout poison positive), then the
  gift party row on a replay of the town play, then evolution. Plan explicit fixtures for egg_hatch
  (daycare + steps) and whiteout (party wipe + ordinary-heal negatives); they are the two expensive
  ones.
- **O22a**: grow `.Items` in bank 4 by one row; keep the table where it is; let the handler `farcall`
  into the SLink bank; declare the bank-4 shift in gate 6c. Do not move the table.
- **O22b**: rewrite the 2-byte object script pointer (`64:73b1` / `5c:545b`) to a new script placed in
  the map bank's free space (`$7688` / `$5609`), which `callasm`s into the SLink bank. Leave
  `SpecialsPointers` alone.
- **O22c**: hold on `wMusicFade != 0`; when channels are busy, only hold a cue that would lose the
  priority test anyway (otherwise PlaySFX steals the channels, which is correct for a
  higher-priority cue); never rely on engine-side queuing.

## CLAIMS

| # | Claim | Verdict | Evidence | Source | Confidence |
|---|---|---|---|---|---|
| 1 | poison_faint site = C `14:4649` / G,S `14:467f`, `DoPoisonStep.DamageMonIfPoisoned`+27, anchor `poisonstep.asm:88-90` | VERIFIED | pack row + `.sym` + source read | pins | high |
| 2 | Poison damage runs from the overworld step handler every 4 steps (`events.asm:905-912` C / `:893-900` G) | VERIFIED | source read | pins | high |
| 3 | evolution site = C `10:63f2` / G,S `10:63ee`, `push hl` at `evolve.asm:317`/`:318` | VERIFIED | pack + `.sym` + source read | pins | high |
| 4 | gift sites C `03:6277/63b6/63d3`; success returns `ret z` `:1785` (party) and `:1795-1796` (box), failure B=2 `:1798-1802` | VERIFIED | pack + `.sym` + source read | pins | high |
| 5 | The town fixture play takes the starter via `givepoke TOTODILE, 5, BERRY` | VERIFIED (source assertion) / INFERENCE (executed) | `maps/ElmsLab.asm:212`, `tools/gen2_fixtures.py:405` | repo | medium |
| 6 | hatch_species = C `05:6fc5` (`ld [wNamedObjectIndex],a` at `breeding.asm:253`); hatch_finalized = C `05:707d` (`.next` `:345`, site `:346`) | VERIFIED | pack + `.sym` + source read | pins | high |
| 7 | npc_trade begin C `3f:4c63` (`ld e,NPCTRADE_GIVEMON`); finalized C `3f:4dc1` = terminal `ret` `npc_trade.asm:273`; receiver = `wPartyCount-1` (`:264-266`) | VERIFIED | pack + `.sym` + source read | pins | high |
| 8 | whiteout site = `Special` C `03:401b` / G,S `03:422b` with DE=27, `wScriptBank=4`, `wScriptPos=$64da`, and the 12-byte `Script_Whiteout` prefix matching the pack | VERIFIED | pack guards + ROM dump (`04:64ce`, `03:407a`) | pins | high |
| 9 | None of the six families is physically proven today | VERIFIED | `proven` lists in `tests/fixtures/gen2/receipts/*.engine_sites.json` | repo | high |
| 10 | START `.Items` = 54 B at C `04:66eb` / G,S `04:6ab2`, bank `$04`, free 618 B / 509 B | VERIFIED | `.map` + `.sym` + source | pins | high |
| 11 | No receipted engine site or checkpoint row is in bank 4 (U1: `$03/$05/$0f`; U2 anchors: `$25`; pack bank-4 pins are the whiteout spans before the table) | VERIFIED | receipt JSONs, `write_checkpoint.json`, `.map` | repo+pins | high |
| 12 | The menu reads `.Items`/strings in the running bank with no switch (bank 4 active via `callasm`) | VERIFIED | `home/menu.asm:700-704,745-749`; `start_menu.asm:275-285`; `events.asm:826-828,844-846`; `scripting.asm:254-263` | pins | high |
| 13 | `wMenuItemsList` is 16 B (15 rows) | VERIFIED | `ram/wram.asm:2224` (C), `:1682` (G) | pins | high |
| 14 | Receptionist object script `dw` = C `64:73b1-73b2` (`9d 68`) / G,S `5c:545b-545c` (`6f 4d`) | VERIFIED | ROM dumps of the object blocks | pins | high |
| 15 | Object scripts run in the map's bank (`GetMapScriptsBank` + `CallScript`) | VERIFIED | `events.asm:583-590`, `home/map.asm:924-935` | pins | high |
| 16 | `SetBitsForLinkTradeRequestSpecial` entry = C `03:402c` / G,S `03:423c`, 3 bytes, single caller | VERIFIED | `.sym`, `special_pointers.asm:9`, `special.asm:1-13`, caller grep | pins | high |
| 17 | Map-bank free space: C `$7688-$7fff` 2424 B / G,S `$5609-$7fff` 10743 B | VERIFIED | `.map` | pins | high |
| 18 | `wMusicFade` = C `00:c2a7` / G,S `00:c1a7`, nonzero during a fade, cleared at `engine.asm:668-670`/`:703-705`; advanced by `_UpdateSound` from VBlank | VERIFIED | `wram.asm`, `engine.asm`, `vblank.asm` | pins | high |
| 19 | `PlaySFX` refuses (drops) a busy-channel SFX below `wCurSFX` priority; `_PlaySFX` clears ch5-8 (steal); nothing is queued | VERIFIED | `home/audio.asm:180-218`, `:504-522`; `engine.asm:2472+` | pins | high |
| 20 | P4 §3's PlaySFX claim (line numbers, no DI) | VERIFIED | same as 19 | pins | high |
| 21 | Proof-cost ranking poison < gift < evolution < npc_trade < egg_hatch < whiteout | INFERENCE (synthesis of F2-F8) | guards + stimulus availability | repo+pins | medium |
