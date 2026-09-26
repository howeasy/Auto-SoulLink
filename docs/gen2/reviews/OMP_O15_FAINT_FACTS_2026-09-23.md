# OMP gen2-O15: source facts for the Gen 2 faint duo (2026-09-23)

OMP card cx-950eb630 (read-only). Read at `a32dc385` and from the pinned decomps
`.cache/gen2-build/pokecrystal` (7a7881d) and `.cache/gen2-build/pokegold` (656583c); `.cache/pret` not used.
Fixtures decoded with `server/adapters/gen2_codec.py`. Consumers: H1c (the gen2_faint duo driver) and U1d
(the battle_faint U1 proof). Both need the same input plan.

## Summary

The linked mon is the fresh Route 29 capture in **party slot 1**. The party is not full: each fixture starts
with one level-5 Totodile. The only deterministic way to faint it is to send it out and never attack.
**Spam Growl** (its second move: no damage, 38 PP) while the foe's Tackle chips it down. Every successful hit
deals **≥ 2 HP** (`MIN_DAMAGE EQU 2`), so a 14-HP Hoothoot faints in **≤ 7 damaging hits**, whatever the
damage rolls.
- **Don't use RUN to pass a turn.** It can end the battle.
- **Answer YES at "Use next #MON?"** (the default cursor). The surviving Totodile then RUNs out.
- **Gold/Silver difference:** a Route 29 foe can reach level 4 there. A level-4 Rattata may outspeed the
  Totodile, so the escape may need retries.

## F1 — Party composition

Fixtures are 32790 bytes: 32768 CartRAM plus a 22-byte RTC trailer (`tools/gen2_playthrough.py:67`). All four
pass the checksum witness, have party count 1 and no boxed mons.

| fixture | mon | level | HP | moves | OT |
|---|---|---|---|---|---|
| crystal_battle | Totodile (158) | 5 | 21/21 | Scratch(10) 35PP, Leer(43) 30PP | 46401 |
| crystal_battle_ot2 | Totodile (158) | 5 | 20/20 | Scratch, Leer | 44068 |
| gold_battle | Totodile (158) | 5 | 20/20 | Scratch, Leer | 50342 |
| silver_battle | Totodile (158) | 5 | 20/20 | Scratch, Leer | 51084 |

All carry the O-10 ball stack (Poké Ball ×10). Save anchor `_SaveGameData(.ok)`, bank 5: C 05:4C6A, G/S 05:4D0D.

After the C<->C `link` duo the party count is 2, the capture sits in slot index 1, and nothing is boxed
(`duo_link_cc_a_result.txt`: `ENGINE_CAPTURE {"destination":"party","slot":1,...}`).
- **A:** slot 0 Totodile 5 (17/21). **Slot 1 Hoothoot 2, 14/14**, moves Tackle(33) 33PP + Growl(45) 38PP, atk 6,
  def 6, spd 7, key D34C:B541:A3.
- **B:** slot 0 Totodile 5 (20/20). **Slot 1 Rattata 2, 13/13**, moves Tackle + Tail Whip, atk 7, def 6, spd 8.

The G/S post-link party is not yet receipted. It is inferred from the shared night clock (see F3).

## F2 — The deterministic faint

**Getting the capture into the active slot.** Two routes:
1. **In battle, via the PKMN menu (preferred).**
   - `BattleMenu` (`engine/battle/core.asm:4881-4931`) is a 2×2 grid with `menu_coords 8,12,19,17`
     (`engine/battle/menu.asm:32-45`; Gold `:25-42` identical). Row 1 is FIGHT/PKMN, row 2 is PACK/RUN, and the
     default is FIGHT. So: **RIGHT, A** selects PKMN.
   - The party list (`InitPartyMenuWithCancel`, `engine/pokemon/party_menu.asm:613-639`) has one row per mon plus
     CANCEL, cursor on row 1. So: **DOWN, A** picks the Hoothoot.
   - `BattleMonMenu` (`engine/pokemon/mon_submenu.asm:247-291`) has rows SWITCH (default), STATS, CANCEL. So a
     single **A** switches.
   - `TryPlayerSwitch` (`core.asm:5156-5229`) then lets the foe attack the incoming mon in the same turn.
2. **Before the battle: START → POKéMON → SWITCH.**
   - The submenu rows are STATS, SWITCH, MOVE, ITEM, CANCEL (`mon_submenu.asm:120-170`, `data/mon_menu.asm:1-40`).
   - `SwitchPartyMons` (`engine/pokemon/mon_menu.asm:155-200`) opens a destination list with no CANCEL row.

**Passing turns.** `MoveSelectionScreen` (`core.asm:5332-5432`) is a vertical wrapped list whose cursor starts on
the last-used move. **GROWL is row 2.** The alternatives don't work:
- **RUN is not safe.** `TryToRunAwayFromBattle` (`core.asm:3680-3790`; Gold `:3469-3555`) always escapes when
  player speed ≥ foe speed, so it can end the battle. Only FIGHT resets the flee counter (`:4927-4929`).
- **Tackle is a race, not deterministic.**
- **Wild foes cannot flee.** Night Hoothoot/Rattata at level ≤ 4 know only Tackle+Growl or Tackle+Tail Whip
  (`data/pokemon/evos_attacks.asm:2216-2228`, `:266-276`).
- **Faint bound:** `+ MIN_DAMAGE` (2) at `engine/battle/effect_commands.asm:3093-3098` (Gold `:3025`) caps it at
  ≤ 7 damaging hits on 14 HP. Growl has 38 PP, so it never runs out.
- **Hazard:** a day/morning Hoppip knows only Splash (`evos_attacks.asm:2521-2531`) and can never faint us.
  Treat a Splash-only foe as "run out and re-encounter".

## F3 — Wild tables

- **Crystal Route 29** (`data/wild/johto_grass.asm:1237-1262`): morning/day are Pidgey/Sentret/Rattata/Hoppip at
  levels 2-3. **Night is Hoothoot 2,2,3,3 plus Rattata 2,3,3.**
- **Gold/Silver** (`pokegold/data/wild/johto_grass.asm:1573-1600`): the same species at levels **2-4**. Night is
  Hoothoot 2,3,3,4,4 plus Rattata 2,4.
- A level-4 Rattata has speed 10-11 and can outspeed the Totodile (10). In G/S, retry RUN on "Can't escape!".
  The second attempt succeeds about 74% of the time.

## F4 — After the faint

- `AskUseNextPokemon` (`core.asm:2695-2722`) prints "Use next #MON?" (`data/text/battle.asm:214-216`) with a
  YES/NO box. YES is the default (`home/menu.asm:428-483`), so a single **A** answers YES.
- YES leads to `ForcePlayerMonChoice` (`:2723`) and `ForcePickPartyMonInBattle` (`:2852-2860`): only healthy mons
  are selectable, so **A** picks the Totodile.
- NO would run a flee roll instead (`:2721`), so YES is the deterministic path.
- Whiteout risk is nil: the lead never takes a hit before the final RUN.
- To leave: `BattleMenu_Run` (`core.asm:5306-5319`) is **DOWN, RIGHT, A**. Retry on `BattleText_CantEscape`
  (`data/text/battle.asm:280-282`).

## F5 — The save

Unchanged from the `link` driver: START → SAVE → YES → YES → A, then wait for `save_success_counter`
(`lua/tests/gen2_frame_align.lua:239-252`). Gate the save on the client's `faint` event, mirroring the capture
gate at `lua/tests/duo/gen2_route29_inputs.lua:52-56`.

## F6 — Gold/Silver vs Crystal

**The same in kind:** the battle menu grid, party rows, BattleMonMenu, SwitchPartyMons, MIN_DAMAGE, the flee
routine and the YES/NO default.

**Different:**
- Route 29 levels (C ≤ 3, G/S ≤ 4), which is why the G/S escape needs retries.
- Every address:

| symbol | Crystal | Gold/Silver |
|---|---|---|
| `BattleMenu` | 0f:6139 | 0f:5f9a |
| `BattleMenu_PKMN` | 0f:628d | 0f:60ba |
| `TryToRunAwayFromBattle` | 0f:58b3 | 0f:574a |
| `AskUseNextPokemon` | 0f:51f8 | 0f:5142 |
| `MoveSelectionScreen` | 0f:64bc | 0f:62f3 |
| `BattleMonMenu` | 09:4e99 | 09:4e09 |
| `PartyMenuSelect` | 14:4457 | 14:43cc |
| `SwitchPartyMons` | 04:6aec | 04:6eb3 |

## F7 — What the driver must add to the gate

`G.MENU_KINDS` (`lua/tests/test_gen2_scripted_gate.lua:53`) needs three new UI kinds and one new prompt anchor:
- **Move list:** `MoveSelectionScreen`.
- **Party list:** `PartyMenuSelect`/`InitPartyMenuWithCancel` (C `14:4457`/`14:4405`, G/S `14:43cc`/`14:437a`).
- **Mon action menu:** `BattleMonMenu`.
- **Prompt anchor:** `use_next_mon: ["Use next"]`.

Labels the driver can match: GROWL, SWITCH, RUN, YES. The PKMN label is the ROM glyph `<PKMN>@`
(`engine/battle/menu.asm:44`), so select PKMN by position (RIGHT from FIGHT), not by label.

## Input plan

1. **Walk** into Route 29 grass until `battle_mode ≠ 0` (unchanged).
2. **Switch-in turn:** battle_menu → RIGHT, A → party_menu → DOWN, A → mon action menu → A → wait for the turn
   text.
3. **Faint loop:** battle_menu → A (FIGHT) → move_menu → GROWL by label → A. Repeat until the faint. Bail to a
   re-encounter only on a Splash-only foe or the frame cap.
4. **After the faint:** answer "Use next" with A (YES) → party_menu → A on the surviving starter → battle_menu →
   DOWN, RIGHT, A (RUN). Retry on "Can't escape!".
5. **Report gate:** hold until the client's `faint` event for the linked key has gone out.
6. **Save:** unchanged.

## Unverified

- The G/S post-link party and the G/S fixtures' clock slot. These are inferred, and the first G/S run's receipt
  settles them.
- Damage counts are formula bounds, not simulations. The ≤ 7-hit bound is decomp-exact.
- Whether the move list reads back as ASCII labels. Confirm on the first live gate run.
