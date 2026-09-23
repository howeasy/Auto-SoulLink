# U1 battle-UI + Gold/Silver engine-site parity facts (OMP gen2-O9 cx-fd0c26c2, gen2-O10 cx-9de8faa5, 2026-09-23)

READ-ONLY source cards, recorded by the coordinator. Input for U1c (Crystal live hook proof) and a later
Gold/Silver U1. Pinned clones `.cache/gen2-build/pokecrystal` (7a7881d), `pokegold` (656583c); `.sym` in
`data/gen2/`.

## Crystal wild battle, engine order (O9)

| Step | Wait | Anchor (C .sym) | Cite |
|---|---|---|---|
| `InitEnemyWildmon` (wild mode set, no screen) | none | `0f:7607` | `engine/battle/core.asm:8183` |
| "Wild X appeared!" | `prompt` -> `PromptButton` (A or B) | `PromptButton 00:0aaf`, loop `.input_wait_loop 00:0ad9` | `data/text/battle.asm:10-15`; `core.asm:9139-9146` |
| Send-out text (`SendOutMonText` -> `BattleTextbox`) | `_BattleMonNicknameText` ends `done`: no wait (U1c) | `0f:726d`, `BattleTextbox 00:3ac3` | `core.asm:7622,7655-7700`; `home/battle.asm:193-201` |
| Battle menu | `_2DMenu` -> `MenuJoypadLoop` | `BattleMenu 0f:6139`, `MenuJoypadLoop 09:4216` | `engine/battle/menu.asm:1-9`; `engine/menus/menu.asm:311` |
| PACK -> Ball pocket -> USE | pocket menus | `BallsPocketMenuHeader 04:4aaf` | `engine/items/pack.asm:45-51,194,223,327,624` |
| Failed throw text | `prompt` -> `PromptButton` | | `item_effects.asm:422,1082`; `common_3.asm:1212-1216` |
| "Gotcha!" | **waits**: `Text_GotchaMonWasCaught` returns `WaitButtonText` = `text_promptbutton` (A or B) after the `text_end` text (CORRECTED by U1c, confirmed by OMP) | `Text_BallCaught 71:5b17` | `item_effects.asm:1086-1103`; `common_3.asm:1218-1229` |
| **First catch of a species: Pokédex NEW DATA** | **two `WaitPressAorB_BlinkCursor` (00:0a80)** | `NewPokedexEntry 3e:7877` | `engine/pokedex/new_pokedex_entry.asm:19,23`; `item_effects.asm:516-536` |
| Nickname yes/no | `AskGiveNicknameText` ("Give a nickname to", ends `done`: NO prompt wait) then `YesNoBox` (`_YesNoBox 00:1dd9`) (CORRECTED by U1c, confirmed by OMP; `GiveANickname_YesNo`/`_CaughtAskNicknameText` is the party/trade path) | | `item_effects.asm:574-581`; `common_3.asm:1250-1255`; other path `caught_data.asm:47,110`, `move_mon.asm:1775` |
| Exp text | none on a successful catch | | |
| Battle exit fade | UNVERIFIED | | `core.asm:8273` |

All battle texts end `prompt` (`PromptButton`), not `WaitPressAorB_BlinkCursor`.

## Gold/Silver parity (O10)

- All six engine-site rows (`wild_ready`, `capture_party`, `capture_party_finalized`, `capture_box`,
  `battle_end`, `save_completed`) reproduce byte-for-byte from each title's own ROM, at the same semantic
  points as Crystal (`.skip_pokedex` party-add path, `.return_from_capture`, `.SendToPC`+8, `ExitBattle`,
  the final `ret` (`c9`) of `_SaveGameData`).
- **Silver is not byte-identical to Gold**: the three capture sites sit 2 bytes lower (S `3:6B4E/6C49/6BB1`
  vs G `3:6B50/6C4B/6BB3`). Rows must stay title-keyed.
- **Gold/Silver have no `MenuJoypadLoop`**: the battle-menu input anchor is `_2DMenuInterpretJoypad`
  (`09:419C` in both; `pokegold/engine/menus/menu.asm:208-225`).
- No delta: battle texts (`prompt`), Ball pocket structure (`pack.asm:44-49`), the two NEW-DATA waits
  (`new_pokedex_entry.asm:16-22`), nickname flow (`caught_nickname.asm:123-129`), `ExitBattle 0f:7456`.
- The generator's G/S whiteout script spans (`04:688E`-`68C7`) cover every whiteout script label in pokegold.

## Shared-driver risk (OMP gen2-U1c-review)

`G.parse_menu` (`lua/tests/test_gen2_scripted_gate.lua:305-345`) joins items across a single space, so the
2x2 battle menu (`engine/battle/menu.asm:31-48`, spacing 6) reads "FIGHT <PK><MN>" as one item. U1c reads it by
source grid in its own gate; the shared route driver's `battle_menu` arm (`choose(ui, "RUN", 2)`) would stall the
same way if a route walk ever meets a wild battle. Follow-up card: grid-read 2x2 menus in the shared parser.
