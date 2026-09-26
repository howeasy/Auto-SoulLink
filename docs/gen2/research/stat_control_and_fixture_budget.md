# Stat control and fixture frame budget (tickets 20, 22)

## Pins

- pokecrystal HEAD: `7a7881d0d62e0ddbd82dcf10e7116807487ac651` (confirmed via `git log -1` in the
  scratchpad clone).
- pokegold HEAD: `656583c939d30f920a316177311a502dd222b57c` (same method).
- Existing Gen 2 code (`gen1_codec.py`, `gen2_playthrough.lua`) is cited only as precedent or
  as the thing being evaluated, never as a fact about the game.

## A. Stat control

**Correction history, 2026-09-22 (SOURCE/MODEL only):** the original R4 note and ticket 20
omitted the doubling of the DV and used a floor square root. Sections A1/A8 and ticket 20
now follow both exact pins above: double `base + DV`, use the capped upward-rounded root,
then truncate after level scaling. The contradictory gender prose/pseudocode is aligned
with the source-resolved `OPEN_QUESTIONS.md` B-11: byte 254 is always female; byte 255 is
genderless. The numeric controls below check arithmetic only. No codec implementation,
GAME control, PHYSICAL evidence, or gate qualification is established by this correction;
the other research sections retain their original scope and limitations.

### A1. `CalcMonStats` / `CalcMonStatC`

Both live in `engine/pokemon/move_mon.asm`. In this corrected section and A8, **C** means
`pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651` and **G** means
`pokegold@656583c939d30f920a316177311a502dd222b57c`; bare line ranges below refer to that
file at the named pin.

- `CalcMonStats` (C/G:1402-1422) loops `c` = `STAT_HP`..`STAT_SDEF` (1..6), calls
  `CalcMonStatC`, and writes each 2-byte result to `[de]`, advancing `de` by two.
  `b` = TRUE/FALSE selects whether stat-exp is included (C/G:1404).
- `CalcMonStatC` (C:1424-1617; G:1424-1630), for stat `c`:
  - reads its base byte from `wBaseStats` into `e` (C/G:1438-1443);
  - selects its stat-exp word, with Sp.Def rewinding the pointer two bytes so it shares
    Sp.Atk's Special word (C/G:1445-1457). Crystal calls `GetSquareRoot`
    (C:1458-1463; `engine/math/get_square_root.asm:9-29`); Gold uses an inline loop
    (G:1458-1477). Both return the first integer root whose square is at least stat-exp,
    capped at 255. For input zero they return 1; after division by four the bonus is still
    zero. For valid word inputs `0..65535`, this is exactly
    `root = min(255, 1 + isqrt(max(0, stat_exp - 1)))`. If the stat-exp flag is false,
    the root/bonus remains zero (C/G:1440,1454-1456);
  - reads Attack DV from the high nibble of byte 1 (C:1510-1514; G:1523-1527), Defense
    from its low nibble (C:1516-1519; G:1529-1532), Speed from the high nibble of byte 2
    (C:1521-1526; G:1534-1539), and Special from its low nibble
    (C:1528-1531; G:1541-1544). Both Special output stats use that same DV branch
    (C:1479-1482; G:1492-1495);
  - assembles HP's DV from the low bits of the four DVs:
    `(Atk & 1) << 3 | (Def & 1) << 2 | (Spd & 1) << 1 | (Spc & 1)`
    (C:1483-1508; G:1496-1521);
  - adds the DV to the base **before** the left shift, then adds `root // 4` via two
    `srl b` instructions (C:1533-1546; G:1546-1559):
    `raw = ((2 * (base + DV) + bonus) * level) // 100`, with
    `bonus = root // 4 if use_stat_exp else 0`. Multiplication by `wCurPartyLevel` and
    floor division by 100 are C:1556-1569 / G:1569-1582;
  - adds `level + 10` for HP, otherwise `5` (C:1570-1595; G:1583-1608), then clamps
    to 999 (C:1597-1611; G:1610-1624). Both pins define `STAT_MIN_NORMAL = 5`,
    `STAT_MIN_HP = 10`, `MAX_STAT_VALUE = 999` in `constants/battle_constants.asm:75-78`.

So Sp.Atk and Sp.Def are computed by the SAME code path (`.Special` DV branch) but against
DIFFERENT base stats (`BASE_SAT` vs `BASE_SDF`, distinct bytes in the base-stats table — see
A2). Both consume the SAME `MON_SPC_EXP` word: there are no separate Special Attack and
Special Defense stat-exp words (C/G `constants/pokemon_data_constants.asm:82-88`; the
pointer rewind is C/G `engine/pokemon/move_mon.asm:1445-1457`). The split is base-stat/output
only; the DV and stat-exp input are shared.

### A2. Party struct: one Special stat-exp, two output stats

`constants/pokemon_data_constants.asm:75-95` (pokecrystal@7a7881d), `rsreset` party struct:

```
MON_STAT_EXP  rw NUM_EXP_STATS        ; 5 words: HP, ATK, DEF, SPD, SPC — no SATK/SDEF split
  MON_HP_EXP    rw
  MON_ATK_EXP   rw
  MON_DEF_EXP   rw
  MON_SPD_EXP   rw
  MON_SPC_EXP   rw                    ; feeds BOTH derived stats in CalcMonStatC
MON_DVS         rw                    ; 1 word: Atk/Def DV nibbles, Spd/Spc DV nibbles
```

Confirmed independently by `lua/tests/gen2_playthrough.lua:286-291` (worktree comment, not
evidence, but consistent): `+0B statExp(5x2)` before `+15..16 DVs`. The OUTPUT side (stored
stats) is the one that splits: `MON_HP..MON_SDEF` continues past `MON_LEVEL`/`MON_STATUS` as
`+22 HP(BE) +24 maxHP +26 Atk +28 Def +2A Spd +2C SpAtk +2E SpDef` (gen2_playthrough.lua:290-291) —
two output words (`+2C`, `+2E`) fed by one input word (`MON_SPC_EXP`) and one input DV nibble.
This is the exact trap the driver's own comment names at gen2_playthrough.lua:293-294: "a Gen
1-shaped writer that stores one value into both is wrong here" — wrong for the OUTPUT (both
words must independently satisfy `CalcMonStatC` against their own base stat), not because the
INPUTS differ.

### A3. Base-stats table layout

`constants/pokemon_data_constants.asm:1-15` (pokecrystal@7a7881d), `rsreset`:

```
BASE_DEX_NO      rb
BASE_STATS       rb NUM_STATS      ; BASE_HP BASE_ATK BASE_DEF BASE_SPD BASE_SAT BASE_SDF
BASE_TYPES       rw
BASE_CATCH_RATE  rb
BASE_EXP         rb
BASE_ITEMS       rw
BASE_GENDER      rb                ; gender ratio byte, see A4
...
```

Verified against `data/pokemon/base_stats/chikorita.asm:1-9` (pokecrystal@7a7881d): the six
stat bytes appear in that exact order with a `; hp atk def spd sat sdf` comment, followed by
type bytes, catch rate, base exp, items, then `db GENDER_F12_5 ; gender ratio` — matching
`BASE_GENDER`'s position in the struct.

### A4. Gender from DVs

`engine/pokemon/mon_stats.asm:124-235` (C), `:126-237` (G), `GetGender`:

- Reads the Attack DV (high nibble of DV byte 1) and Speed DV (high nibble of DV byte 2,
  swapped to its low nibble), then combines them: `b = (AtkDV << 4) | SpdDV`
  (C:179-190; G:181-192, `; Attack DV` / `; Speed DV` / `or b`) — an 8-bit value 0-255, NOT
  attack DV alone.
- Reads `BASE_GENDER` for the species (C:197-207; G:199-209).
- `GENDER_UNKNOWN EQU -1`, encoded as byte **255**, -> genderless
  (C:211-212,233-235; G:213-214,235-237).
- `GENDER_F0` (0) -> always male (C:214-215; G:216-217).
- `GENDER_F100` (`100 percent - 1`) = **254** -> always female (C:217-218; G:219-220).
- Otherwise: `cp b` then `jr c, .Male` (C:221-222; G:223-224) — i.e. **male when the
  ratio byte is LESS than the combined DV byte `b`**; female otherwise.
  Both pins' `constants/pokemon_data_constants.asm:35-41` define the ratio constants;
  `macros/data.asm:23` defines `percent` as `* $ff / 100`, so `GENDER_F100` evaluates to
  `100 * 255 / 100 - 1 = 254`. This is the already-resolved SOURCE fact in
  `OPEN_QUESTIONS.md` B-11; codec encoding and physical gender/shiny controls remain open.

### A5. Shininess from DVs

`engine/gfx/color.asm:1-38` (pokecrystal@7a7881d), `CheckShininess`:

```
DEF SHINY_ATK_MASK EQU %0010
DEF SHINY_DEF_DV EQU 10
DEF SHINY_SPD_DV EQU 10
DEF SHINY_SPC_DV EQU 10
```

Shiny iff: Attack DV's bit 1 (`%0010` against the high nibble, i.e. `AtkDV & 2 != 0`,
color.asm:14-16) AND Defense DV == 10 (:18-21) AND Speed DV == 10 (:23-26) AND Special DV ==
10 (:28-31). All four must hold; carry set on shiny (:34-35), clear otherwise (:37-38). This
is the exact "shiny bonus pairs" mechanic the ticket names — it is a 4-nibble DV predicate,
not a single flag bit, so a control oracle must derive it from the same DV word used for A1's
stat calc.

### A6. Unown letter from DVs

`engine/gfx/load_pics.asm:1-42` (pokecrystal@7a7881d), `GetUnownLetter`:

Takes the middle 2 bits of each of the 4 DV nibbles (Atk, Def, Spd, Spc — `%01100000`/
`%00000110` masks, load_pics.asm:8-27), packs them into one byte `atk_bits:def_bits:
spd_bits:spc_bits` (each 2 bits), then divides by `$FF / NUM_UNOWN + 1` (load_pics.asm:31-38)
and increments (:40-41) to land in 1-26 (`wUnownLetter`). Also DV-derived, same DV word as A1/A4/A5.

### A7. When stats are recomputed (CONTROL oracle timing)

Every caller of `CalcMonStats`/`predef CalcMonStats` (pokecrystal@7a7881d), grepped across
`engine/`:

| Call site | Function | Trigger |
|---|---|---|
| `engine/pokemon/move_mon.asm:345` | `GeneratePartyMonStats` (called from `TryAddMonToParty`, move_mon.asm:3-80) | New mon added to the party (catch, gift, hatch-into-party) |
| `engine/pokemon/move_mon.asm:663` | `SendGetMonIntoFromBox` (move_mon.asm:480-705) | **Box withdrawal** — confirms the ticket's "box withdraw?" question: yes, it recomputes |
| `engine/pokemon/move_mon.asm:871` | `RetrieveBreedmon` (move_mon.asm:805-901) | Egg retrieval from Day Care breeding |
| `engine/battle/core.asm:6233` | `LoadEnemyMon` (core.asm:5963-...) | Enemy/wild mon load for battle (`b=FALSE`, no stat-exp — wild/trainer mons don't carry stat exp state) |
| `engine/battle/core.asm:7228` | `GiveExperiencePoints` (core.asm:6983-...) | **Level-up from battle experience** (`b=TRUE`) |
| `engine/events/battle_tower/battle_tower.asm:464` | rental mon generation | Battle Tower mon build |
| `engine/events/daycare.asm:504` | egg hatch/creation path | Day Care egg production |
| `engine/items/item_effects.asm:1216` (`UpdateStatsAfterItem`) | Rare Candy / stat-boosting vitamin items | Item-driven level/stat-exp change |
| `engine/pokemon/breeding.asm:286` | egg creation | Breeding |
| `engine/pokemon/correct_party_errors.asm:93` | save-corruption repair | Defensive recompute on a malformed party |
| `engine/pokemon/evolve.asm:263` | `EvolveAfterBattle`-adjacent evolution code | **Evolution** |
| `engine/pokemon/tempmon.asm:54` | `ComputeNPCTrademonStats` | NPC trade-mon stat generation |

This mirrors the Gen 1 H-8 precedent named in the ticket almost exactly: stats are stored,
not always-live, and are rebuilt only on level-CHANGE-adjacent events (level-up via
experience, evolution, item-driven stat-exp change), on party/box membership changes (catch,
withdraw, hatch, breed, trade), and on defensive repair — never merely by viewing a status
screen. A CONTROL oracle comparing stored stats against `CalcMonStatC`'s formula must
therefore tolerate staleness immediately after stat-exp accrues in battle (stat exp updates
every KO, per Gen 1's own `GainExperience` precedent, but the stored stat word is untouched
until the mon's OWN level changes) and require equality at every one of the triggers above.

### A8. Python-shaped pseudocode of the control

```python
from math import isqrt


def calc_mon_stat(base: int, dv: int, stat_exp: int, level: int, *,
                  is_hp: bool, use_stat_exp: bool = True) -> int:
    """CalcMonStatC: C move_mon.asm:1424-1617; G:1424-1630 (exact pins in A1).
    Inputs: base byte, DV nibble, stat_exp word 0..65535, valid game level.
    """
    # C engine/math/get_square_root.asm:9-29; G move_mon.asm:1458-1477.
    root = min(255, 1 + isqrt(max(0, stat_exp - 1)))
    bonus = root // 4 if use_stat_exp else 0
    # Add DV before doubling: C:1533-1546; G:1546-1559.
    # Multiply, then floor-divide: C:1556-1569; G:1569-1582.
    raw = ((2 * (base + dv) + bonus) * level) // 100
    # C:1570-1595; G:1583-1608; both constants/battle_constants.asm:75-76.
    raw += level + 10 if is_hp else 5
    # C:1597-1611; G:1610-1624; MAX_STAT_VALUE=999 (battle_constants.asm:78).
    return min(raw, 999)


def calc_mon_stats(base_stats: dict, dvs: dict, stat_exp: dict, level: int, *,
                   use_stat_exp: bool = True) -> dict:
    """dvs keys: atk, def, spd, spc (nibbles 0-15). stat_exp keys: hp, atk, def, spd, spc
    (words 0-65535). Shared Special exp: C/G:1445-1457; DV: C:1479-1482,1528-1531;
    G:1492-1495,1541-1544. Separate base inputs feed satk and sdef.
    """
    dv_hp = ((dvs["atk"] & 1) << 3) | ((dvs["def"] & 1) << 2) \
          | ((dvs["spd"] & 1) << 1) | (dvs["spc"] & 1)  # C:1483-1508; G:1496-1521
    options = {"use_stat_exp": use_stat_exp}
    return {
        "hp":   calc_mon_stat(base_stats["hp"],  dv_hp,      stat_exp["hp"],  level, is_hp=True, **options),
        "atk":  calc_mon_stat(base_stats["atk"], dvs["atk"], stat_exp["atk"], level, is_hp=False, **options),
        "def":  calc_mon_stat(base_stats["def"], dvs["def"], stat_exp["def"], level, is_hp=False, **options),
        "spd":  calc_mon_stat(base_stats["spd"], dvs["spd"], stat_exp["spd"], level, is_hp=False, **options),
        "satk": calc_mon_stat(base_stats["sat"], dvs["spc"], stat_exp["spc"], level, is_hp=False, **options),
        "sdef": calc_mon_stat(base_stats["sdf"], dvs["spc"], stat_exp["spc"], level, is_hp=False, **options),
    }


def get_gender(atk_dv: int, spd_dv: int, gender_ratio: int) -> str | None:
    """C mon_stats.asm:124-235; G:126-237. gender_ratio is the serialized byte:
    0=always male, 254=always female, 255=genderless. Returns 'male'/'female'/None.
    """
    if gender_ratio == 255:           # GENDER_UNKNOWN EQU -1; C:211-212; G:213-214
        return None
    if gender_ratio == 0:             # GENDER_F0; C:214-215; G:216-217
        return "male"
    if gender_ratio == 254:           # GENDER_F100; C:217-218; G:219-220
        return "female"
    combined = ((atk_dv & 0xF) << 4) | (spd_dv & 0xF)   # C:179-190; G:181-192
    return "male" if gender_ratio < combined else "female"   # C:221-226; G:223-228


def check_shininess(atk_dv: int, def_dv: int, spd_dv: int, spc_dv: int) -> bool:
    """color.asm:8-38. All four conditions must hold."""
    return (atk_dv & 0b0010) != 0 and def_dv == 10 and spd_dv == 10 and spc_dv == 10


def get_unown_letter(atk_dv: int, def_dv: int, spd_dv: int, spc_dv: int) -> int:
    """load_pics.asm:1-42. Returns 1-26 (A-Z, ! and ? excluded from this range per
    NUM_UNOWN -- not independently verified here, marked open below)."""
    packed = (((atk_dv >> 1) & 0b11) << 6) | (((def_dv >> 1) & 0b11) << 4) \
           | (((spd_dv >> 1) & 0b11) << 2) | ((spc_dv >> 1) & 0b11)
    divisor = (0xFF // 26) + 1     # NUM_UNOWN not pinned to 26 here -- open question
    return (packed // divisor) + 1
```

MODEL arithmetic controls for the corrected `calc_mon_stat` (stat-exp enabled):

| Base / DV / stat-exp / level | Root / bonus | Non-HP | HP |
|---|---|---:|---:|
| 50 / 15 / 0 / 100 | 1 / 0 | 135 | 240 |
| 50 / 0 / 10 / 100 | 4 / 1 | 106 | 211 |
| 50 / 15 / 10 / 37 | 4 / 1 | 53 | 95 |

The first two isolate DV doubling and upward root rounding; the third checks truncation
after level scaling. With `use_stat_exp=False`, the second case instead yields 105
(non-HP) / 210 (HP). These controls are not original-engine execution or codec qualification.

## B. Fixture path and budget

### B1. Earliest scripted Poke Ball

**Finding: there is no early Poke Ball source.** The player cannot hold a real Poke Ball
until AFTER completing the full Mr. Pokemon "Mystery Egg" errand — not at Elm's lab, not from
the starter, not from Cherrygrove Mart, not from any item ball on Route 29/30.

- `maps/ElmsLab.asm:1-506` (pokecrystal@7a7881d): the starter grant (`givepoke CYNDAQUIL/
  TOTODILE/CHIKORITA, 5, BERRY`, e.g. :182) carries a Berry, never a ball. The aide's ball
  gift (`AideScript_GiveYouBalls`, :498-508, `giveitem POKE_BALL, 5` at :502) only fires on
  `SCENE_ELMSLAB_AIDE_GIVES_POKE_BALLS` (`coord_event` triggers at :1232-1233 in the pokegold
  copy; pokecrystal's equivalent coord_events gate the same scene). That scene is set at the
  very END of `ElmAfterTheftScript` (:349, `setscene SCENE_ELMSLAB_AIDE_GIVES_POKE_BALLS`),
  which itself only runs after `takeitem MYSTERY_EGG` (:333) — i.e. after delivering the
  Mystery Egg Mr. Pokemon gave the player, back to Elm.
- `maps/CherrygroveMart.asm:9-16` (pokecrystal@7a7881d): `pokemart MARTTYPE_STANDARD,
  MART_CHERRYGROVE` (no balls) unless `checkevent EVENT_GAVE_MYSTERY_EGG_TO_ELM` is true, in
  which case `MART_CHERRYGROVE_DEX` is used. `data/items/marts.asm:40-55`: `MartCherrygrove`
  = Potion/Antidote/Parlyz Heal/Awakening only; `MartCherrygroveDex` prepends `POKE_BALL`.
  Same event gate as the aide.
- `maps/Route29.asm:437` and `maps/Route30.asm:434` (pokecrystal@7a7881d): the only item balls
  on these routes are a Potion (Route 29, `EVENT_ROUTE_29_POTION`) and an Antidote (Route 30,
  `EVENT_ROUTE_30_ANTIDOTE`) — no Poke Ball.
- `maps/Route29.asm:39-87`, the catching tutorial (`Route29Tutorial1`/`Tutorial2`,
  `catchtutorial BATTLETYPE_TUTORIAL` at :54/:79): a scripted mini-battle using its own ball
  animation, not a bag-item grant — no `giveitem` in either tutorial script.
- `EVENT_GAVE_MYSTERY_EGG_TO_ELM` is the single flag both gates check (`ElmAfterTheftScript`,
  ElmsLab.asm:333; `checkevent EVENT_GAVE_MYSTERY_EGG_TO_ELM` in CherrygroveMart.asm:11 and
  :27), so both the aide and the mart become available in the SAME frame of scripted play.

**Consequence for the ticket's framing**: "Route 29 grass + >= 1 Poke Ball, Gen 1 F-6
precedent (Route 1 + one ball)" is not a short scripted path in Gen 2 the way it is in Gen 1.
Gen 1's Route 1 ball comes from Oak's parcel-fetch errand alone; Gen 2's ball gate sits behind
the ENTIRE Mr. Pokemon round trip (lab -> Cherrygrove -> Route 30 -> Mr. Pokemon's house ->
back to Elm), which also crosses Route 29/30 wild encounters and at least one more building
interior. This is a materially longer and flakier scripted chain than the Gen 1 fixture ever
needed.

### B2. Segment list, New Game -> Route 29 grass with >= 1 Poke Ball

Numbered by map, using pokecrystal's script/flag names. Coordinates are approximate (object
event / warp positions in the cited files), not measured on hardware here.

1. **Intro**: title screen -> gender/name/clock -> spawn in `PLAYERS_HOUSE_2F` (bedroom).
   Matches `lua/tests/gen2_playthrough.lua:161-237`'s own measured boot (see B3).
2. **PlayersHouse2F -> PlayersHouse1F -> NewBarkTown**: walk downstairs, talk to Mom
   (Pokegear/clock scene per `gen2_playthrough.lua`'s header comment, "driving Mom's Pokegear
   scene... ends in a DST yes/no", maps/PlayersHouse1F.asm — not independently re-read here,
   cited from the driver's own comment as a KNOWN hazard, not re-verified against the map
   file), exit house.
3. **NewBarkTown -> ElmsLab**: walk to the lab; blocked from leaving town westward by
   `coord_event`s at (1,8)/(1,9) firing `SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU`
   (gen2_playthrough.lua's header comment) until the starter is obtained.
4. **ElmsLab**: `ElmsLabWalkUpToElmScript` (ElmsLab.asm:44-88, intro dialogue) -> choose a
   starter (`CyndaquilPokeBallScript`/`TotodilePokeBallScript`/`ChikoritaPokeBallScript`,
   ElmsLab.asm:138-256) -> `ElmDirectionsScript` (:256-283, sets `EVENT_GOT_A_POKEMON_FROM_ELM`
   and `EVENT_RIVAL_CHERRYGROVE_CITY`, :278-279) -> exit lab.
5. **NewBarkTown -> Route 29 -> CherrygroveCity**: walk the route (wild encounters possible;
   `Route29Tutorial1`/`2`'s coord_events at (53,8)/(53,9), Route29.asm:422-423, will fire if
   the player crosses those tiles — this is itself a scripted stop that must be navigated or
   accepted).
6. **CherrygroveCity**: optional rival encounter (`object_event 39,6, ...,
   EVENT_RIVAL_CHERRYGROVE_CITY`, CherrygroveCity.asm:569) — talk-only per the object event
   type (`OBJECTTYPE_SCRIPT`), not confirmed here to force a battle; guide-gent walkthrough
   tour is standard Crystal/GS content not re-read in this pass.
7. **CherrygroveCity -> Route 30 -> Mr. Pokemon's house**: `maps/MrPokemonsHouse.asm` was
   listed in the ticket but NOT read in this pass (time-boxed) — the Mystery Egg pickup
   script and its exact dialogue/flags are `†UNVERIFIED` here; only the RETURN-side flags
   (`EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON`, checked at ElmsLab.asm:145) are confirmed by the
   Elm-side script.
8. **Return trip**: Mr. Pokemon's house -> Route 30 -> CherrygroveCity -> Route 29 ->
   NewBarkTown -> ElmsLab, `ElmAfterTheftScript` (ElmsLab.asm:326-350): `takeitem
   MYSTERY_EGG` -> `setevent EVENT_GAVE_MYSTERY_EGG_TO_ELM` -> `setmapscene ROUTE_29,
   SCENE_ROUTE29_CATCH_TUTORIAL` -> `setscene SCENE_ELMSLAB_AIDE_GIVES_POKE_BALLS`.
9. **ElmsLab, aide**: `AideScript_GiveYouBalls` (ElmsLab.asm:498-508): `giveitem POKE_BALL, 5`
   — **first frame a real Poke Ball exists in the bag**.
10. **ElmsLab -> NewBarkTown -> Route 29 -> tall grass**: walk back out to Route 29 grass,
    now carrying Poke Balls, satisfying the ticket's target state.

This is roughly DOUBLE the map transitions of a "town-only" fixture and revisits Route 29/30
twice, each pass exposed to wild encounters (the Gen 1 lesson in memory
`reference_bizhawk_savestate_rot.md`-style: "grass-derived overworld = flaky walking
scenarios" applies at least as strongly here, doubled).

### B3. Frame estimates per segment

No committed receipt in `tests/fixtures/gen1/receipts/` carries a fixture-BUILD frame count;
that directory holds live-test heartbeats (e.g. `changebox_new_a_result.txt:15`, `"booted at
frame 846"`, and `:45` `"frame=18112"` for an 18k-frame E2E run) — evidence of the
measurement STYLE, not a number transferable to Gen 2's very different map layout. The
mechanism `lua/tests/gen1_scripted_play.lua:198-219` uses (`self.run` returns `receipts =
{module -> frames}`, logged via `on_phase(name, phase, frame)` callbacks) is the pattern to
reuse; it was not run here (no live emulator in this research pass) and gives no absolute
number without execution.

What IS measured for Gen 2 specifically: `lua/tests/gen2_playthrough.lua:164-168`, comment
"MEASURED (lua/tests/probe_gen2_boot.lua on Crystal): pressing nothing for ~1200 frames lands
on the title screen"; `:226`, `ride_intro(40000)` — the intro (segment 1 above) is bounded at
40000 frames in the driver but not reported as an exact measured value (it is a ceiling, not
a receipt).

| Segment | Steps (script events to pass) | Frame estimate |
|---|---|---|
| 1. Intro -> bedroom | title wait (~1200f measured), gender/name/clock menus | ~1200f measured (`gen2_playthrough.lua:164-168`) through title; full intro to walkable bounded at 40000f ceiling (`:226`), NOT a measured value |
| 2. House -> NewBarkTown (Mom scene) | stairs, Mom dialogue/Pokegear, DST prompt | unmeasured — driver's own header flags this as flake-prone, step count not counted here |
| 3. NewBarkTown -> ElmsLab | ~1 screen of walking | unmeasured, ~1 map transition |
| 4. ElmsLab (starter) | dialogue chain (`ElmText_Intro`..`ElmDirectionsScript`), 1 yes/no, starter choice yes/no | unmeasured; this is the segment `gen2_playthrough.lua:283-298` currently SKIPS by writing WRAM directly instead |
| 5. NewBarkTown -> Route 29 -> Cherrygrove | ~2-3 screens, 2 coord_event tutorial stops possible | unmeasured, wild-encounter risk |
| 6. CherrygroveCity | optional rival talk | unmeasured |
| 7. Cherrygrove -> Route 30 -> Mr. Pokemon's house | ~2-3 screens | unmeasured; MrPokemonsHouse.asm script itself not read this pass |
| 8. Return trip (house -> lab) | same routes reversed | unmeasured, doubles segment 5+7's wild-encounter exposure |
| 9. ElmsLab aide (ball grant) | 2-3 text boxes | unmeasured, short |
| 10. Lab -> Route 29 grass | ~2-3 screens | unmeasured |

Bottom line for the owner: **no bounded total frame budget can be stated from source alone**;
every segment past the measured title-screen wait is an unmeasured step count, and segments
5-8 each carry wild-encounter (RNG) exposure that Gen 1's fixture never had to cross even
once, let alone twice. This is worse than "no receipt exists" — the topology itself doubles
the flake surface.

### B4. Crystal vs Gold/Silver script differences along this path

- `maps/ElmsLab.asm`: pokegold's copy carries a `MAPCALLBACK_OBJECTS` object-move callback
  (`ElmsLabMoveElmCallback`, pokegold@656583c maps/ElmsLab.asm:19-47) that pokecrystal's does
  not have inline (diff line 19a20); the initial Elm conversation differs (pokegold has a
  `yesorno`/must-accept gate at `.MustSayYes` plus extra dialogue boxes and a
  `addcellnum PHONE_ELM` phone-number registration beat, diff hunks at 44a54-76 and
  216a257-263) that pokecrystal's does not show in the same place. These are dialogue/UX
  differences, not gating differences.
- **The gating mechanism itself is identical**: `SCENE_ELMSLAB_AIDE_GIVES_POKE_BALLS`
  (pokegold@656583c maps/ElmsLab.asm:17,306,461,1232-1233) and `giveitem POKE_BALL, 5`
  (:461) match pokecrystal's structure exactly (const name, `setscene` call, `giveitem`
  amount).
- `data/items/marts.asm` is BYTE-IDENTICAL between the two repos for this path (`diff`
  produced no output) — `MartCherrygrove`/`MartCherrygroveDex` and the Poke Ball gate are the
  same in Gold/Silver as in Crystal.
- Net: a Gen 2 fixture driver written against Crystal's dialogue timings will need
  Crystal-specific button/A-press counts through `ElmsLab.asm`'s intro (more text boxes and a
  yes/no in Gold/Silver), but the EVENT/SCENE-based gating logic — which is what a
  ram-reactive driver (`gen2_playthrough.lua`'s stated philosophy, "EVERYTHING IS
  RAM-REACTIVE. No phase waits on a frame count.") actually keys off — is portable unchanged.

### B5. What the current Gen 2 driver skips, and what it would have to drive instead

`lua/tests/gen2_playthrough.lua:282-342` (`give_starter`) writes the 48-byte party struct and
bag slot directly into WRAM instead of playing segments 2-4 and 9-10 above:

- **Skips**: Mom's house scene (segment 2), the walk to Elm's lab (3), the full lab dialogue
  and starter-choice script (4) — replaced by a raw `TOTODILE` write with hand-picked DVs
  (`0x99, 0x99`), stat-exp all zero (implicit, block zeroed at :300), caught-data bytes, and
  fixed stat words that the file's own comment (:293-294) flags as a trap for the Sp.Atk/
  Sp.Def split (A2 above) — the driver writes DIFFERENT literal values into `+2C` and `+2E`
  (10 and 10 — actually identical here, but the comment warns a NAIVE port from Gen 1 would
  alias them). It also skips the entire Mr. Pokemon errand (segments 5-9) by writing
  `give_pokeballs(10)` directly into the Balls pocket (`lua/tests/gen2_playthrough.lua:349-362`),
  bypassing `EVENT_GAVE_MYSTERY_EGG_TO_ELM` entirely.
- **To drive it instead**, the script would need: Mom's Pokegear/DST scene handled
  (`maps/PlayersHouse1F.asm`, not read this pass — flagged by the driver's own header as a
  self-looping yes/no hazard); the lab's starter-choice dialogue (`CyndaquilPokeBallScript`
  et al., ElmsLab.asm:138-256, each with a yes/no `TakeXText` prompt and multiple
  `waitbutton`/`promptbutton` steps); AND, if segment B1's finding stands, the full round
  trip to Mr. Pokemon's house and back before Poke Balls exist at all — which the driver's own
  header comment (lines 39-46) already argues against paying for ("Paying for a Gen 2 grass
  fixture would buy a second copy of coverage that exists" via Gen 1's `battle` fixture
  covering the server-side, generation-independent duo rules).

## Open questions

- Exact contents of `maps/MrPokemonsHouse.asm` (Mystery Egg pickup dialogue, any additional
  gating flags) — named in the ticket but not read in this pass; needed before a driver could
  actually script segment 7.
- `maps/Route30.asm`'s full script (rival battle placement, any additional coord_event stops)
  — only the item-ball line was checked.
- Whether the Cherrygrove rival encounter (`CherrygroveCity.asm:569`) forces a battle or is
  optional/skippable; object type is `OBJECTTYPE_SCRIPT` but the script body itself
  (`ObjectEvent`/`EVENT_RIVAL_CHERRYGROVE_CITY`) was not traced.
- `NUM_UNOWN`'s exact value was assumed as 26 in the pseudocode's `divisor` comment; not
  independently grepped from `constants/*.asm` in this pass — mark the pseudocode's divisor
  line `†UNVERIFIED`.
- No frame-count receipt exists anywhere in the repo for ANY Gen 1 fixture-build run (only
  live-test heartbeats were found); the entire B3 table beyond the two Gen-2-specific
  measured/bounded numbers is an unmeasured step count, not a frame count — the owner should
  treat B3 as "topology is known, timing is not" rather than a usable budget.
- **Source question resolved** (`OPEN_QUESTIONS.md` B-11, rechecked in A4): both pinned
  `macros/data.asm:23` definitions make `GENDER_F100` = 254; byte 255 is genderless.
  Codec encoding and physical gender/shiny controls remain open.
