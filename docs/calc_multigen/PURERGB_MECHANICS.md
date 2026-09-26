# pureRGB damage-calc mechanics diff

Prototype + mechanics diff for HANDOFF.md task 7 (pureRGB custom data in the damage calc). Every
claim below is cited `file:line` in both trees:

- vanilla = pret/pokered, checked out at `E:/Google Drive/SLink/.cache/pret/pokered`.
- pureRGB = Vortyne/pureRGB v2.7.6, commit `7e7a46535ca332ad24ecb02e326ea2f75e79ebb9` (pinned in
  `data/purergb_sources.lock.json`), checked out at `E:/Google Drive/SLink/.cache/purergb-src`
  (`.cache/purergb` is the same checkout under `tools/gen1_foundation.py`'s default path/env var).
- calc = this branch's `calc/calc/src` (the damage-calc TypeScript engine).

pureRGB is a straight pret/pokered fork: the engine functions below are named and shaped the same
in both trees, so most of this is a line-level diff rather than a rewrite-from-scratch comparison.

## Status

This file started as a prototype report (checkpoint commit `e6af312a`); the work it scoped has
since shipped. pureRGB's calc support is **on local master, not pushed, not released**:
`b56df47f` (flip pureRGB on for Gen 1), `5705d557` (engine: alternate STAB, Ghost dynamic category,
the setter-based dex swap), `bb5ab261` (species-by-id forms, generated trainer sets). It has been
**browser-verified** for one hand-worked case (Porygon Tri Attack vs Chansey, both L50: 57-67 -
`docs/calc_multigen/HANDOFF.md`'s per-game table) but **not live-verified** in a real pureRGB
emulator run. The rest of this file records the mechanics diff (§1, still current) and the engine
implementation as shipped (§2-§4), with remaining gaps in §3 and §5.

## 1. What changed

### 1.1 Six new types

`constants/type_constants.asm:4-24` (pureRGB) defines the 6 new types and, in doing so, also
states pureRGB's physical/special split rule for them (see §1.2):

```
DEF PHYSICAL EQU const_value
  NORMAL($00) FIGHTING($01) FLYING($02) POISON($03) GROUND($04) ROCK($05)
  TYPELESS($06)  <- "CHANGED: used with struggle"
  BUG($07)
  GHOST($08)     <- "CHANGED: dynamic typing" (see §1.3; not one of the 6 new types)
  CRYSTAL($09)   <- "ADDED: used with hardened onix"
  BONEMERANG_TYPE($0A) <- "ADDED: used with bonemerang"
DEF SPECIAL EQU const_value
  TRI($11)       <- "ADDED: used with tri attack"
  FLOATING($12)  <- "ADDED: used with floating magneton / weezing"
  MAGMA($13)     <- "ADDED: used with volcanic magmar"
  FIRE($14) WATER($15) GRASS($16) ELECTRIC($17) PSYCHIC_TYPE($18) ICE($19) DRAGON($1A)
```

The full type chart is generated (never hand-typed) from `data/types/type_matchups.asm` (110
attacker/defender/multiplier rows, `TypeEffects`-format, same "sparse diff over an implicit 1x"
convention as vanilla's own table and as the calc's existing hand-written `RBY`/`GSC` objects in
`calc/calc/src/data/types.ts`) by `tools/gen_purergb_calc_patch.py:build_type_chart`. Notable rows
involving the 6 new types, `data/types/type_matchups.asm:86-109`:

| Attacker | Defender | Multiplier |
|---|---|---|
| Tri | Fire | 0.5 |
| Tri | Flying, Grass, Bug | 2 |
| Tri | Electric, Rock | 0.5 |
| (existing types) | Crystal | Water/Ice/Fire/Normal 0.5, Fighting/Ground 2, Poison/Flying 0.5 |
| Ground | Floating | 0 (immune) |
| Bonemerang | Fire, Electric, Rock, Poison | 2 |
| Bonemerang | Grass, Bug | 0.5 |
| Water, Fire | Magma | 0 (immune) |

(All other pairs involving a new type default to neutral, matching the table's own convention.)

### 1.2 Physical/special split

Vanilla Gen 1 derives a move's category purely from its type: type id `< SPECIAL` ($14/Fire) is
physical, `>= SPECIAL` is special (`constants/type_constants.asm:4-22`, vanilla). The calc mirrors
this exactly for gens < 4 when a move's data doesn't set an explicit category:
`this.category = data.category || (gen.num < 4 ? (SPECIAL.includes(data.type) ? 'Special' :
'Physical') : 'Status')` (`calc/calc/src/move.ts:127-128`, `SPECIAL` list at `move.ts:5`).

pureRGB's type-id split above (§1.1) says the 6 new types would resolve correctly through that
same type-id rule (Bonemerang/Typeless physical, Tri/Floating/Magma special) **if** the calc's
`SPECIAL` list were extended to match - but it doesn't need to be, because
`data/games/gen1_purergb/moves.json` already carries an explicit `split` field
(`"Physical"|"Special"|"Status"`) sourced per-move from the ROM, for all 165 moves. The prototype
(`tools/gen_purergb_calc_patch.py:build_moves_ts`) always emits `category` from that field
directly, the same way the calc's own data files set an explicit `category` to override the
type-based fallback for any move where it doesn't apply. **`move.ts`'s `SPECIAL` array was not
touched and doesn't need to be** - every pureRGB Gen 1 move's category is explicit data, never
inferred.

### 1.3 Ghost's dynamic category (not one of the 6 new types - a gap, not a prototype target)

`constants/type_constants.asm:13`: "GHOST type has dynamic typing, special if your base special is
higher than attack, physical if they're the same or attack is higher." Implemented in
`engine/battle/core.asm:4262-4270` (`DynamicTypeCheckPlayer`) and `:4389-4397`
(`DynamicTypeCheckEnemy`), both new (no vanilla equivalent - vanilla's
`GetDamageVarsForPlayerAttack`/`GetDamageVarsForEnemyAttack`, `engine/battle/core.asm:4030-4478`
in the vanilla tree, only ever do the static type-id compare):

```
DynamicTypeCheckEnemy:
  ld a, [wEnemyMonBaseSpecial]
  ld b, a
  ld a, [wEnemyMonBaseAttack]
  cp b
  jr c, GetDamageVarsForEnemyAttack.specialAttack ; base special > base attack -> special
  jr GetDamageVarsForEnemyAttack.physicalAttack   ; otherwise -> physical
```

This picks physical-vs-special **per attacking Pokemon, at battle time**, from *base* Attack vs
*base* Special - a property of the mon using the move, not of the move itself. The calc's
`move.category` model has no notion of "depends on the user." pureRGB reassigned 8 existing moves
to Ghost type (Sonicboom, Night Shade, Screech, Confuse Ray, Barrier, Lick, Dream Eater, Barrage -
`data/games/gen1_purergb/moves.json`), all carrying a static `split` (7 Physical, 2 Status) that
reflects the common case, not the dynamic rule - the generated `purergb.ts` just takes moves.json's
`split` as given, unchanged. **Implemented in `mechanics/gen12.ts`** instead: a Ghost-type
damaging move's category is recomputed per-attacker from `baseStats.spa` vs `.atk`, overriding the
static `split` for that one case - see §3 item 2.

### 1.4 STAB (same-type attack bonus)

The 1.5x STAB math is byte-identical in both trees (`engine/battle/core.asm:5239-5259` pureRGB vs
`:5075-5095` vanilla: `bc = floor(0.5*damage); hl = damage + bc`) and matches the calc's own STAB
line, `move.hasType(...attacker.types)` -> `Math.floor(baseDamage * 1.5)`
(`calc/calc/src/mechanics/gen12.ts:235-237`).

**Added**: `engine/battle/moved_battle_code.asm:120-148` (`ShouldMoveGetStabBoost`, called from
`AdjustDamageForMoveType` via `callfar` at `engine/battle/core.asm:5240` - vanilla's
`AdjustDamageForMoveType` computed the same type-match test inline instead) adds four
**alternate-STAB** rules, each letting a move of one type get STAB on an attacker of a *different*
type:

```
cp GROUND
  jr z, .checkMagmaStab   ; GROUND-type moves get STAB on MAGMA-type attackers (Volcanic Magmar)
cp ROCK
  jr z, .checkCrystalStab ; ROCK-type moves still get STAB on CRYSTAL-type attackers (Hardened Onix)
cp BONEMERANG_TYPE
  jr z, .checkGroundStab  ; BONEMERANG-type moves get STAB on GROUND-type attackers
cp TRI
  jr nz, .skipSameTypeAttackBonus
  ld a, NORMAL             ; TRI-type moves get STAB on NORMAL-type attackers (Porygon)
```

**Implemented** as a per-move-type special case inside the STAB branch of `calculateRBYGSC`
(`mechanics/gen12.ts`'s `PURERGB_ALT_STAB` table) - see §3 item 1.

### 1.5 Type effectiveness lookup, and four optional "remap" toggles

The `TypeEffects`-table walk is unchanged (`engine/battle/core.asm:5267-5301` pureRGB vs
`:5100-5150ish` vanilla - same loop, same `ApplyDamageMultiplier` calls). Two additions:

**`RemapTypeMatchupBasedOnOptions`** (`engine/battle/core.asm:5393-5469`), called for every
type-pair match right before the multiplier is applied. It's a config toggle for exactly the four
long-argued "should this be the classic Gen 1 chart or the modern one" pairs, gated on
`wOptions3` (`constants/ram_constants.asm:191-198`):

| Bit | Toggle | Base chart value (bit **off**, the default) | Remapped value (bit **on**) |
|---|---|---|---|
| 0 `BIT_GHOST_PSYCHIC` | Ghost vs Psychic | `SUPER_EFFECTIVE` (2x) - `data/types/type_matchups.asm:79`, comment: "ghost was made super effective against psychic by default" (fixes the famous vanilla "Psychic invincibility" bug, where Ghost vs Psychic is `NO_EFFECT`) | `NO_EFFECT` (0x) - restores the vanilla bug |
| 1 `BIT_ICE_FIRE` | Ice vs Fire | `EFFECTIVE` (1x, neutral) - `data/types/type_matchups.asm:37`, comment: "added to facilitate customization... seems redundant" (a deliberate buff over vanilla, where it's 0.5x) | `NOT_VERY_EFFECTIVE` (0.5x) - restores vanilla accuracy |
| 2 `BIT_BUG_PSN` | Bug vs Poison | `SUPER_EFFECTIVE` (2x) - `data/types/type_matchups.asm:71`, unchanged from vanilla's own Gen-1-only quirk (fixed to 0.5x from Gen 6 onward) | `NOT_VERY_EFFECTIVE` (0.5x) - the modern (Gen 6+) value |
| 3 `BIT_PSN_BUG` | Poison vs Bug | `SUPER_EFFECTIVE` (2x) - `data/types/type_matchups.asm:49`, unchanged from vanilla | `EFFECTIVE` (1x) - the modern (Gen 2+) value |

**Default state**: `engine/menus/main_menu.asm:176-181` (`InitOptions`) never touches `wOptions3`;
`ram/wram.asm:2736` declares it as plain (zero-initialized) WRAM. Standard Game Boy convention is
that a fresh save's WRAM/SRAM is zeroed, so all four bits default **off** (base chart values
apply) - not independently re-verified beyond "nothing sets it," flagged here rather than stated
as fully confirmed.

**Not modeled** (known limit, unchanged - §3 item 4). `tools/gen_purergb_calc_patch.py` bakes in
the *base* chart values only (the defaults) - there's no per-battle options state in the calc to
hang a toggle off of, and the calc has no settings UI for it. If a future change wants the toggle,
it's a UI option -> `Field`-or-similar flag -> `mechanics/gen12.ts` remap, small (S) once the data
path exists.

**Also added, not modeled**: a Haze/Mist immunity check before the type loop
(`CheckHazeMistImmunityGetArgs`/`ForceTypeImmunity`, `engine/battle/core.asm:5257-5259`) - the calc
doesn't model Mist in Gen 1/2 at all today, pureRGB or not, so this is an existing gap, not a new
one.

**Also added, a genuinely new defensive move effect**: Defense Curl now forces any super-effective
hit against its user down to neutral (`CheckIfDefenseCurlModifier`, `engine/battle/core.asm:
5316-5344`, called from the type-loop's end-of-table branch at `:5311-5315`). Vanilla Defense Curl
is a pure no-op stat-stage move with no defensive effect. This needs a `Pokemon`/`Field`-level
"is defense-curled" flag plus a `mechanics/gen12.ts` change; not otherwise reachable from static
species/move data, so the calc can't carry it (known limit, unchanged - §3 item 3).

### 1.6 Critical hits

**Focus Energy bug, fixed.** Vanilla (`engine/battle/core.asm:4519-4531`, vanilla tree) shifts the
crit-rate byte the wrong direction when Focus Energy is active (`srl b`, halving it - the
well-documented Gen 1 bug where Focus Energy *lowers* your crit rate instead of raising it).
pureRGB (`engine/battle/core.asm:4746-4764`) doubles it instead (two `sla b` with a 255 cap,
comment: "normal attacks have 4x crit rate under focus energy") - a real fix, not a data change,
and out of the calc's current Gen 1/2 crit model entirely (`isCrit` is caller-supplied in
`mechanics/gen12.ts`, the calc doesn't compute crit *rate* at all - see §3, this is low priority
unless the calc ever adds a "compute crit chance" mode).

**High-crit-move multiplier, changed.** Vanilla's high-crit path (`core.asm:4552-4560`, vanilla)
is two `sla b` steps with no initial halve, giving 4x raw = 8x of the normal (halved) rate -
matching the commonly-cited Gen 1 "high-crit moves are 8x as likely to crit" figure. pureRGB's
version (`core.asm:4779-4791`) adds a **third** `sla b`, giving 8x raw = 16x of the normal rate -
double the effective high-crit bonus vs. vanilla. Same caveat as above: the calc doesn't compute
crit rate, only accepts `isCrit` as a boolean, so this doesn't affect calc output today.

**High-crit move list, one addition.** `data/battle/critical_hit_moves.asm` (both trees) is the
list `CriticalHitTest` actually reads (`core.asm` `ld hl, HighCriticalMoves`); pureRGB adds
`POISON_GAS` to vanilla's {Karate Chop, Razor Leaf, Crabhammer, Slash}. Poison Gas is a 0-power
status move, so this is a no-op for damage either way. (Vanilla also ships a *second*,
never-included list, `data/battle/unused_critical_hit_moves.asm` - true dead code in both trees;
pureRGB repurposes that `INCLUDE` line for an unrelated new feature, a real move-priority table
(`data/battle/priority_moves.asm`) - turn order, not crits, and not modeled by the damage calc
regardless.)

### 1.7 Stat caps, Reflect/Light Screen, Explosion

**`do999StatCap`, a new bug fix** (`engine/battle/core.asm:7337-7349`), called right after Reflect
doubles Defense or Light Screen doubles Special (`core.asm:4297`/`4337` and the enemy-attack
mirror at `:4425`/`4457`) to clamp the doubled stat at 999. Vanilla has no such cap, so a Pokemon
whose Reflect/Light-Screen-doubled stat would exceed 999 gets vanilla's well-known stat-overflow
weirdness instead. **Not applicable to the calc**: `calc/calc/src/mechanics/gen12.ts:156-163`
(`if (isPhysical && field.defenderSide.isReflect) df *= 2; ...`) just multiplies in JS, which
never overflows, and no real Gen 1 base stat gets anywhere near 999 even after a double, so there
is no calc-side bug to replicate or fix either way. No engine change needed.

**Explosion/Self-Destruct** defense halving is untouched (`gen12.ts:151-153` already matches both
trees). Separately, pureRGB changes when Explosion/Self-Destruct actually *faints* the user
(`data/games/gen1_purergb/profile.json`'s `explode_low_hp_fraction: 3` - the user only faints
below ⅓ max HP, and moves first when it would) - this is move-*legality*/turn-order, not the
damage formula, so it doesn't touch the calc's damage output and is out of scope here.

### 1.8 Fixed-damage moves, multi-hit, the random roll

`ApplyAttackToEnemyPokemon`'s `SPECIAL_DAMAGE_EFFECT` branch (`core.asm:4790-4838`, pureRGB) is
functionally the same as vanilla's equivalent (Seismic Toss/Night Shade = user's level, Sonic Boom
= fixed 20) with two changes: Dragon Rage's fixed-40-damage case was deleted (comment: "Dragon
Rage doesn't do a set 40 damage anymore" - it's presumably now a normal power-based move; not
independently confirmed since it isn't one of the 5 named custom moves) and Psywave's
random-damage-from-level code was deleted (comment: "Psywave is a basic low power psychic move
now"). Both already match `calc/calc/src/mechanics/util.ts`'s `handleFixedDamageMoves` in that
neither Dragon Rage nor Psywave should be treated as fixed-damage for pureRGB. Psywave isn't one of
`handleFixedDamageMoves`'s three name checks at all, so it was never at risk. Dragon Rage is - and
this is exactly the bug §2's "Naming policy: moves" section traces and fixes: `handleFixedDamageMoves`
now gates its Night Shade/Dragon Rage/Sonic Boom branches on `isPureRGB(move.gen)`, so pureRGB's
power-based Dragon Rage no longer gets treated as fixed-40-damage. See §2 for the full trace.

The 217-255 random-roll loop and its rounding are unchanged (only a `TWO_OR_THREE_ATTACKS_EFFECT`
constant rename and a dead double `and a` removed - purely cosmetic, `core.asm:4291-4293` and
`:4318` pureRGB vs `:4053`/`:4076` vanilla).

### 1.9 Trainer/enemy stat exp (context for HANDOFF task 4/6, not a damage-formula change)

`GetDamageVarsForEnemyAttack`'s DV-loading (`core.asm:4425-4445`, pureRGB) was rewritten to read
the enemy's live battle stats directly instead of vanilla's `wLoadedMonSpeedExp` DV hack
(comment: "why load this into speedexp? I don't even know like seriously WTF"), and folds in
trainer stat exp via `wEnemyStatEXPStore` when `wIsInBattle == 2` (a trainer battle). A new
optional toggle, `wOptions3` bit 5 `BIT_NPC_STAT_EXP` (default off, same zero-init reasoning as
§1.5), gives enemy trainer Pokemon 450 stat exp per level when on
(`engine/battle/stats_functions.asm:115-136`, `CalcEnemyStatEXP`); off (the default) keeps
vanilla's 0-stat-exp trainers. This is about *where the enemy's stats come from*, not the damage
formula - relevant to HANDOFF's task 4/6 (Gen 1/2 real stats, Gen 1 enemy data), not to this task's
`mechanics/gen12.ts` question.

## 2. Species/move data and the naming policy

`data/games/gen1_purergb/species_index.json` has 190 internal-index slots, classified `ordinary`
(151, real dex 1-151), `form` (7 alternate forms), `spirit` (5 battle-only bosses, not catchable),
`unused` (23 dead slots), `missingno` (1, `$B5`, a real catchable glitchmon) and `picture_only` (3,
never battled). The calc includes `ordinary` + `form` + `spirit` (163 species) and drops the
27 `unused`/`missingno`/`picture_only` slots as not worth modelling in a damage calc.

**Known limit**: dropping the `missingno` slot has one visible consequence - trainers.json's
`GYM_GUIDE` trainer class (id 250) fields a party-slot MISSINGNO (internal id 181). With no species
data for it, `tools/gen_purergb_setdex.py` skips that one party slot (logged to stderr) rather than
emitting a set the calc can't render; every other species referenced by trainers.json resolves
against `purergb.ts`'s species data (verified by `tests/unit/test_calc_purergb.py`).

**Naming policy** (`tools/gen_purergb_calc_patch.py:build_ordinary_names`/`build_form_names`),
three tiers, all sourced from the pinned checkout rather than hand-typed:

1. **`ordinary`**: the ROM's own `MonsterNames` text (`data/pokemon/names.asm`, 1 entry per
   internal index, same order as `constants/pokemon_constants.asm`), Title Cased, with 4 spelling
   fixups to match the calc's existing vanilla names exactly (`NIDORAN♂`/`♀` -> `Nidoran-M`/`-F`,
   `MR.MIME` -> `Mr. Mime`, `FARFETCH'D` -> `Farfetch’d`).
2. **`spirit`**: `species_index.json`'s own `name` field, Title Cased (already unique and
   ROM-display-accurate, e.g. `THE MAW` -> `The Maw`).
3. **`form`**: **not** `species_index.json`'s `name` field, and not `MonsterNames` - both just
   repeat the base species' display name in-game (e.g. internal index 172, Hardened Onix, shows as
   "ONIX" exactly like index 34 does - that's the whole trick behind an alternate form:
   same on-screen name, different internal stats/types/index). Verified via
   `constants/pokemon_constants.asm`'s `; $XX` hex comments matching `species_index.json`'s
   internal-index keys (e.g. `$AC` = 172 = `HARDENED_ONIX`), giving each form the pret/pureRGB
   dev team's own disambiguating symbol name, Title Cased: `Hardened Onix` (172), `Volcanic
   Magmar` (52), `Floating Magneton` (56), `Winter Dragonair` (94), `Floating Weezing` (146),
   `Armored Mewtwo` (174), `Powered Haunter` (175).

**Confirmed adapter/calc name mismatch for all 7 forms** (verified directly against
`species_index.json`, not just inferred): `server/adapters/gen1_purergb.py`'s `species_name()`
returns `national_species_name(entry["dex"], False)` for `classification == "ordinary"` but
`_display_case(entry["name"])` for `"form"` (`gen1_purergb.py:195-204`) - and `species_index.json`'s
own `"name"` field for every one of the 7 form entries is literally the BASE species' all-caps
name (index 172's `"name"` is `"ONIX"`, not `"HARDENED_ONIX"`; same for the other 6). So the
adapter's `species_name(172)` returns plain `"Onix"` - identical to the base Onix's own name, not
`"Hardened Onix"`. The calc can't use that name as-is (species are both a JS object key and a
`toID()` lookup key in `species.ts`'s tables, so `"Onix"` would either collide with or silently
shadow the base Onix entry), so `purergb.ts` keeps the disambiguated `pokemon_constants.asm` name
for these 7 - this is a **known, unresolved gap**: whenever the server sends a form species' name
for a pureRGB battle, it will send the plain (colliding) name the adapter emits, not the
disambiguated one `purergb.ts` uses, so the calc's `species.get(toID(name))` for these 7 forms will
resolve to the *base* species instead (Onix's stats where Hardened Onix's were meant). Fixing this
needs either a pureRGB-only `calc_names.json`-style species table sending the disambiguated name
server-side, or a `species_name()` change in the adapter (out of scope for this branch - the
adapter is a read-only file here); flagging it for the coordinator per HANDOFF task 7's naming-policy
requirement. The 7 forms: `Hardened Onix` (172, base `Onix`), `Volcanic Magmar` (52, base
`Magmar`), `Floating Magneton` (56, base `Magneton`), `Winter Dragonair` (94, base `Dragonair`),
`Floating Weezing` (146, base `Weezing`), `Armored Mewtwo` (174, base `Mewtwo`), `Powered Haunter`
(175, base `Haunter`).

Base stats/types come straight from `species_index.json`'s `stats`/`types` fields (already
source-verified per the data README); `weightkg` isn't in the source data and is stubbed `0`
since `mechanics/gen12.ts`'s `calculateRBYGSC` never reads `Specie.weightkg` (confirmed by reading
the whole function - Gen 1/2 has no Grass-Knot/Low-Kick-style weight-based move).

**Moves**: all 165 `data/games/gen1_purergb/moves.json` entries are emitted, type/power/category
from `type`/`power`/`split` - but the *name* is renamed through `data/games/gen1_rby/calc_names.json`'s
"move" table first (see "Naming policy: moves" below), not moves.json's raw ROM spelling. Not
carried over (gaps, not blockers): per-move `multihit` (moves.json has no such field - e.g.
Bonemerang is vanilla-2-hit but the generator treats it as one hit) and Firewall/Heat Rush's
non-damage side effects (traced and confirmed harmless to the shown damage number - see §3 items 6
and 7). Siphon Snag's drain **is** carried over (`drain: [1, 2]`, hand-pinned in the generator's
`MOVE_DRAIN` table against `engine/battle/move_effects/siphon_snag.asm`) - see §3 item 5.

### Naming policy: moves

`server/adapters/gen1_purergb.py`'s `Gen1PureRGBAdapter` doesn't override `calc_name()`, so it
inherits `Gen1Adapter`'s implementation (`server/adapters/gen1_rby.py:426`) unchanged, including
its table (`data/games/gen1_rby/calc_names.json`). `server/server.py` applies
`adapter.calc_name("move", adapter.move_name(id))` to every move name it sends the frontend
(`server/server.py:163`), and `Gen1PureRGBAdapter.move_name()` just returns moves.json's raw
`"name"` field (`server/adapters/gen1_purergb.py:311-313`) - so the calc name the server actually
emits for a pureRGB move is `calc_names.json["move"].get(raw_name, raw_name)`.

12 of pureRGB's 165 moves reuse a raw ROM spelling this table renames (verified directly against
`data/games/gen1_purergb/moves.json`):

| moves.json raw name | calc name (what the server sends, and what purergb.ts now uses) |
|---|---|
| Doubleslap | Double Slap |
| Thunderpunch | Thunder Punch |
| Vicegrip | Vise Grip |
| Sand-Attack | Sand Attack |
| Sonicboom | Sonic Boom |
| Bubblebeam | Bubble Beam |
| Solarbeam | Solar Beam |
| Poisonpowder | Poison Powder |
| Thundershock | Thunder Shock |
| Selfdestruct | Self-Destruct |
| Softboiled | Soft-Boiled |
| Hi Jump Kick | High Jump Kick |

The prototype (checkpoint commit e6af312a) emitted the raw name for all of these. That was a real
bug, not just cosmetic: the calc looks a move up by `toID(name)`, and `toID('Hi Jump Kick')` !=
`toID('High Jump Kick')` (`hijumpkick` vs `highjumpkick`) - so a server-sent "High Jump Kick" would
have missed the pureRGB table entirely and silently fallen back to *vanilla* Gen 1's High Jump Kick
data. `tools/gen_purergb_calc_patch.py` now renames through this table before computing each
move's id (`build_moves_data`), so `purergb.ts` uses the exact name the server sends.

**A second, more serious bug this uncovered**: `mechanics/util.ts`'s `handleFixedDamageMoves()` is
a pure move-*name* check (`move.named('Night Shade')`, `('Dragon Rage')`, `('Sonic Boom')`) with no
gen/dex gating, inherited by every gen's damage function. Tracing pureRGB's own
`data/moves/moves.asm` (source of truth for which moves still carry the `SPECIAL_DAMAGE_EFFECT`
move-effect, not moves.json's `power` field, which is a plain data column moves.json never marks
as "ignored by a special effect") shows only `SEISMIC_TOSS` still has that effect in pureRGB;
`NIGHT_SHADE` (effect `NO_ADDITIONAL_EFFECT`, power 65) and `DRAGON_RAGE` (effect
`NO_ADDITIONAL_EFFECT`, power 80) are now ordinary power-based moves, and `SONICBOOM` (effect
`FLINCH_SIDE_EFFECT1`, power 50) is a power-based move with a flinch chance. Night Shade and Dragon
Rage already share vanilla's exact spelling (no rename involved) and would have hit
`handleFixedDamageMoves`'s vanilla branches regardless of the naming fix above; Sonic Boom would
only start colliding once renamed from "Sonicboom" to "Sonic Boom". `handleFixedDamageMoves` is now
gated on `isPureRGB(move.gen)` for these three (Seismic Toss's branch stays
unconditional - see `mechanics/util.ts` and the jest cases in `purergb.test.ts` for both the
now-power-based Sonic Boom and the still-fixed Seismic Toss).

## 3. Engine changes in `mechanics/gen12.ts`, gated on `isPureRGB(gen)` (`mechanics/util.ts`)

| # | Change | Status |
|---|---|---|
| 1 | Alternate STAB: Tri->Normal, Magma->Ground, Crystal->Rock, Bonemerang->Ground attackers also get STAB (§1.4) | **Implemented.** `gen12.ts`'s `PURERGB_ALT_STAB` table + an `||` alongside the existing `move.hasType(...attacker.types)` STAB check, gated on `isPureRGB(gen)`. Jest case: `purergb.test.ts` "Porygon Tri Attack vs Chansey" (and a companion case confirming vanilla Tri Attack stays plain Normal-type with no alt STAB). |
| 2 | Ghost dynamic category: physical if attacker's base Attack >= base Special, else special (§1.3) | **Implemented.** `gen12.ts` computes a local `category` (overriding `move.category` only for `move.type === 'Ghost'` under the same gate) from `attacker.species.baseStats.spa`/`.atk` right before the `isPhysical`/`attackStat`/`defenseStat` computation, since `move.category` is fixed at `Move` construction and has no access to the attacker. Jest case: "Gengar Lick vs Machamp resolves Special" (Gengar's base Special exceeds its base Attack, overriding Lick's static "Physical" split from moves.json). |
| 3 | Defense Curl forces super-effective -> neutral for its user (§1.5) | **Skipped, documented gap** (unchanged from the prototype). Needs a new `Pokemon`/`Field` boosted-state flag the calc has no UI surface for ("used Defense Curl this turn" isn't a field the calc's single-shot `calculate()` call can express) - not trivially modelable per this task's scope. |
| 4 | The four optional type-chart remaps (§1.5) | **Skipped, documented gap** (unchanged). The generated chart still bakes in pureRGB's own defaults (all 4 toggles off); no settings UI exists to hang a per-battle override off of. |
| 5 | Siphon Snag/Absorb-style drain flag on the generated move data | **Implemented** (data-only, no `gen12.ts` change needed - confirmed by reading `desc.ts:133-144`, which reads `move.drain` generically regardless of gen). `tools/gen_purergb_calc_patch.py`'s `MOVE_DRAIN` table sets `drain: [1, 2]` on Siphon Snag. Jest case: "Siphon Snag carries drain: [1, 2]". |
| 6 | Firewall's burn + escalating-power-on-burned-target | **Traced, no damage-number change - documented gap.** `engine/battle/move_effects/burn.asm`'s `FirewallEffect_`: on a hit, burns the target (standard burn - halves Attack via the normal burn path, doesn't touch Firewall's own hit) if not already burned/immune, otherwise sets a `BOOSTED_FIREWALL` flag for a *later* use. The power ramp is pure multi-turn history (which prior move a Pokemon used, read back on a later turn) that the calc's single-shot `calculate()` has no way to carry - same class of gap as Defense Curl (#3), not reachable from static move/species data. |
| 7 | Heat Rush's effect (`HeatRushEffect`/`HEAT_RUSH_EFFECT`, `effects.asm`) | **Traced, no damage-number change - documented gap.** A Take Down reskin: 40% chance to raise the user's own Special one stage if the user is Fire-type, plus a chance to burn the target afterward (unless already fainted) - both post-hit secondary effects, neither of which changes *this* hit's own damage (self-buffs across turns aren't modelled by the calc for any gen). |
| 8 | Focus Energy fix / high-crit-multiplier change (§1.6) | N/A - the calc doesn't compute crit *rate*, only accepts `isCrit` as given. Unchanged from the prototype. |

Items 1, 2 and 5 are implemented and covered by jest cases in `purergb.test.ts`. Items 3, 4, 6 and 7
remain accuracy gaps for specific move/species combinations, not a blanket "the numbers are wrong"
problem - `useDex('purergb')` computes correct numbers for every move/species combination this task
covers. A related bug this work also uncovered and fixed (not one of the 8 items above, but
directly caused by the move-naming fix in §2's "Naming policy: moves"): `mechanics/util.ts`'s
`handleFixedDamageMoves()` needed the same `isPureRGB(gen)` gate to stop misclassifying pureRGB's
now-power-based Night Shade/Dragon Rage/Sonic Boom as vanilla's fixed-damage versions.

## 4. Engine implementation status

- **`TypeName` is widened** (`interface.ts`) with the 6 pureRGB types, directly in the closed
  union - the prototype's "engine surgery" concern (widening breaks `stats.ts`'s exhaustive
  Hidden-Power IV/DV table) is real but narrow: `stats.ts`'s `HPTypeName` is defined as
  `Exclude<TypeName, ...>`, so it only needed the 6 new names added to that `Exclude` list (Hidden
  Power doesn't exist until Gen 2, so none of pureRGB's types could ever apply there anyway).
  Every other per-type mapping in the engine (`interface.ts:170`, `types.ts`, `move.ts`'s
  `ZMOVES_TYPING`) is already `[type in TypeName]?:` (optional), so widening doesn't force new
  entries anywhere else - confirmed by `npx tsc -p . --noEmit` staying clean. `purergb.ts` no
  longer needs any `as unknown as` cast anywhere.
- **Clean swap, not prototype patching.** `species.ts` and `moves.ts` each gained a small exported
  setter (`setGen1Species`/`setGen1Moves`) that both reassigns `SPECIES[1]`/`MOVES[1]` (the same
  exported array objects `calc/calc/src/index.ts` re-exports for the frontend's dropdowns) *and*
  rebuilds the private `SPECIES_BY_ID[1]`/`MOVES_BY_ID[1]` lookup cache from it, by running the
  swapped-in data through the exact same `Specie`/`Move` constructors every other gen's
  hand-written table uses - no separate object-literal-plus-cast path, no `Species.prototype`/
  `Moves.prototype` monkey-patching. This is a real bug fix versus the prototype, not just a
  cleanup: prototype-patching `.get()`/`[Symbol.iterator]` never touched the exported `SPECIES`/
  `MOVES` arrays themselves, so `calc.SPECIES[1]` (which `shared_controls.js`'s gen-change handler
  reads to populate the species/move dropdowns) would have kept showing *vanilla* Gen 1 data even
  with `useDex('purergb')` active.
  - `purergb.ts` itself is now just plain `SpeciesData`/`MoveData`/`TypeChart`-shaped tables (the
    same shapes `species.ts`/`moves.ts`/`types.ts`'s own RBY/GSC/... tables use, keyed by display
    name) plus `useDex()`, which calls the two new setters and the pre-existing
    `setGen1TypeChart()`. The §3/naming-policy gate is `isPureRGB(gen)`, defined in
    `mechanics/util.ts` itself (`gen.num === 1 && !!gen.types.get('crystal' as ID)`) - it reads the
    live-swapped type chart rather than importing anything from `data/purergb.ts`, since
    `mechanics/` and `data/` compile to separate bundles that don't share module scope.
  - **Gotcha found and fixed**: `species.ts`'s `Specie` class constructor reads a module-level
    `let gen` *loop variable* (not a constructor parameter!) to decide `bs.sl` (Gen 1's single
    Special stat) vs `bs.sa`/`bs.sd` (Gen 2+). By the time any code outside the module's own
    initial load loop runs, that variable has settled at its final post-loop value (10), so
    `setGen1Species` has to save/restore it around `gen = 1` while constructing, or every pureRGB
    species would silently get `undefined` `spa`/`spd`. `moves.ts`'s `Move` constructor takes
    `gen` as a real parameter, so `setGen1Moves` has no equivalent trap.
- `calc/calc/src/test/purergb.test.ts` covers the original prototype cases (new-type effectiveness,
  custom move Dust Claw, `useDex('vanilla')` round-trip) plus the §3 items 1/2/5 and
  Night-Shade/Sonic-Boom fixed-damage cases (alternate STAB fires/doesn't, Ghost dynamic category,
  Siphon Snag's drain field, Sonic Boom's real power-based damage, Seismic Toss staying
  fixed-damage). All pass as of this writing, hand math in the test comments, cross-checked against
  the pureRGB source (`data/moves/moves.asm`'s effect ids) where relevant. The wider `src/test`
  suite has pre-existing failures unrelated to pureRGB (other gens' `data.test.ts` snapshot
  mismatches) - see the suite's own run output rather than a count here, which would go stale.
  `npx tsc -p . --noEmit`: clean (re-verified 2026-09-26).
- `tools/gen_purergb_calc_patch.py --check` now works from a git worktree (verified from
  `.claude/worktrees/damage-calc-multi-game-744f5c`): it resolves the main checkout's `.git` via
  `git rev-parse --git-common-dir` and points `SLINK_PURERGB_SRC` at `<main>/.cache/purergb`
  (falling back to `<main>/.cache/purergb-src`) when the caller hasn't already set that env var -
  `tools/gen1_foundation.py`'s own `REPO` is pinned to *its own* `__file__` location, which in a
  worktree is the worktree's copy of `tools/`, not the main checkout where `.cache/` actually
  lives.
- **Not modeled** (unchanged, documented gaps - see §3 items 3/4/6/7): Defense Curl's
  damage-reduction effect, the four optional type-chart toggles, Firewall/Heat Rush's non-damage
  side effects, per-move multihit counts (Bonemerang etc.).

## 5. Frontend needs - resolved

This section originally listed three items the prototype left for the frontend. All three shipped
alongside the engine work (`5705d557`) and are done as of this writing:

- **Dex selection is automatic, no manual selector needed.** `slink_bridge.js`'s `_applyCalcGen()`
  reads the server's `calc_profile()["dex"]` field on every `/api/calc/mons` payload and calls
  `calc.useDex('purergb')` or `calc.useDex('vanilla')` before the gen-1 radio switch runs, so the
  right dex is always loaded before anything reads it. There is no "pureRGB checkbox" in the UI,
  and none is needed - the server already knows which dex a given run is on.
- **No type-colour CSS gap - none exists for any type.** `calc/src/css` has no per-type styling for
  *any* of the vanilla types either; `.type1`/`.type2` are plain `<select>` dropdowns
  (`shared_controls.js:614-615` etc.), not colour-swatched badges. The 6 new types just add 6 more
  `<option>` values with no styling work required. (The fork's only colour-coded badges are
  difficulty/status badges in `slink_bridge.js`, unrelated to Pokemon types.)
- **Species/move dropdowns are generation-scoped and verified.** `shared_controls.js` populates
  them from `calc.SPECIES[gen]`/`calc.MOVES[gen]` (`shared_controls.js:1308`/`:1312`), which is
  exactly what `setGen1Species`/`setGen1Moves` mutate. `docs/calc_multigen/HANDOFF.md`'s per-game
  table records this browser-verified for the Porygon Tri Attack vs Chansey case (see Status,
  above) - through the real page, not just the jest harness.
