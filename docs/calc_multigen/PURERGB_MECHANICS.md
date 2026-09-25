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
reflects the common case, not the dynamic rule. **Gap**: any Ghost-type damaging move used by a
Pokemon whose base Special exceeds its base Attack will be mis-classified by this prototype (and
by the generated `purergb.ts`, which just takes moves.json's `split` as given). Fixing it needs a
`mechanics/gen12.ts` change - see §3.

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

**Not implemented in this prototype.** It's a per-move-type special case inside the STAB branch of
`calculateRBYGSC`, which lives in `mechanics/gen12.ts` (one of this branch's read-only files -
"stop and report" rather than edit). See §3 for the estimated engine change.

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

**Not modeled by this prototype.** `tools/gen_purergb_calc_patch.py` bakes in the *base* chart
values only (the defaults) - there's no per-battle options state in the calc to hang a toggle off
of, and the calc has no settings UI for it. If the full build-out wants the toggle, it's a UI
option -> `Field`-or-similar flag -> `mechanics/gen12.ts` remap, small (S) once the data path
exists.

**Also added, not modeled**: a Haze/Mist immunity check before the type loop
(`CheckHazeMistImmunityGetArgs`/`ForceTypeImmunity`, `engine/battle/core.asm:5257-5259`) - the calc
doesn't model Mist in Gen 1/2 at all today, pureRGB or not, so this is an existing gap, not a new
one.

**Also added, a genuinely new defensive move effect**: Defense Curl now forces any super-effective
hit against its user down to neutral (`CheckIfDefenseCurlModifier`, `engine/battle/core.asm:
5316-5344`, called from the type-loop's end-of-table branch at `:5311-5315`). Vanilla Defense Curl
is a pure no-op stat-stage move with no defensive effect. This needs a `Pokemon`/`Field`-level
"is defense-curled" flag plus a `mechanics/gen12.ts` change (§3); not otherwise reachable from
static species/move data, so this prototype can't carry it at all.

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
neither Dragon Rage nor Psywave should be treated as fixed-damage for pureRGB - **not yet reflected
in the prototype's move data** (Dragon Rage/Psywave aren't among the 165 moves.json entries I
special-cased; their `split`/`power` from moves.json is used as-is, which is correct as long as
`handleFixedDamageMoves` keys off move *name*, not a data flag - worth a one-line grep-check before
the full build-out, not done here for time).

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
never battled). The prototype includes `ordinary` + `form` + `spirit` (163 species) and drops the
27 `unused`/`missingno`/`picture_only` slots as not worth modelling in a damage calc.

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

Base stats/types come straight from `species_index.json`'s `stats`/`types` fields (already
source-verified per the data README); `weightkg` isn't in the source data and is stubbed `0`
since `mechanics/gen12.ts`'s `calculateRBYGSC` never reads `Specie.weightkg` (confirmed by reading
the whole function - Gen 1/2 has no Grass-Knot/Low-Kick-style weight-based move).

**Moves**: all 165 `data/games/gen1_purergb/moves.json` entries are emitted as-is
(type/power/category from `type`/`power`/`split`). Not carried over (gaps, not blockers): per-move
`multihit` (moves.json has no such field - e.g. Bonemerang is vanilla-2-hit but the prototype
treats it as one hit) and the 3 non-trivial custom-move side effects beyond damage: **Siphon
Snag** drains HP to the user (`engine/battle/move_effects/siphon_snag.asm`, like vanilla
Absorb/Mega Drain - `drain` isn't set on the generated entry), **Firewall** burns the target and
ramps its own power against an already-burned target (`engine/battle/move_effects/burn.asm:1-36`,
`FirewallEffect_`), and **Heat Rush** (a Take Down reskin, `effects.asm:1950-1995`,
`HeatRushEffect`/`HEAT_RUSH_EFFECT` - not traced in depth). None of these change the *base* damage
roll the calc computes (drain/burn are separate from the hit's own damage, and Firewall's ramp
would need per-turn state the calc's single-shot `calculate()` doesn't track anyway), so they're
display/description gaps rather than damage-number bugs.

## 3. Engine changes needed in `mechanics/gen12.ts`, gated on a pureRGB flag

None of these were made in this prototype (`mechanics/gen12.ts` is a read-only file for this
branch - "stop and report" rather than edit). Estimates assume a `gen.num === 1 && purergb` guard
(a flag threaded through `Field` or `Generation`, TBD by whoever picks this up) around each:

| # | Change | Where | Est. |
|---|---|---|---|
| 1 | Alternate STAB: Tri->Normal, Magma->Ground, Crystal->Rock, Bonemerang->Ground attackers also get STAB (§1.4) | `gen12.ts`'s STAB check (`move.hasType(...attacker.types)`) | S |
| 2 | Ghost dynamic category: physical if attacker's base Attack >= base Special, else special (§1.3) | Move category is currently fixed at `Move` construction (`move.ts:127`); needs the *attacker's* base stats, which `Move` doesn't have access to - most likely resolved in `gen12.ts` itself, overriding `move.category` for Ghost-type moves before the `isPhysical` check | M |
| 3 | Defense Curl forces super-effective -> neutral for its user (§1.5) | Needs a new `Pokemon`/`Field` boosted-state flag (not in `state.ts` today) plus a `gen12.ts` check after computing `typeEffectiveness` | M |
| 4 | The four optional type-chart remaps (§1.5), if the full build-out wants them togglable rather than baked to pureRGB's own defaults | A `Field`-level option flag threaded into `getMoveEffectiveness` (`mechanics/util.ts`) | S (once a settings surface exists) |
| 5 | Siphon Snag/Absorb-style drain flag on the generated move data | Data-only (`purergb.ts`'s `drain: [1,2]`) - `gen12.ts` doesn't need to change, drain is already handled generically wherever the calc surfaces "recovers X HP" today | XS |
| 6 | Firewall's burn + escalating-power-on-burned-target | New move-effect, no existing analogue in `gen12.ts`'s minimal Gen 1/2 effect set (only Explosion/Present/Pursuit/Flail-Reversal are special-cased today) | M |
| 7 | Heat Rush's effect (unverified - `HEAT_RUSH_EFFECT`, `effects.asm:1950-1995`) | Needs tracing before it can be estimated | ? (needs investigation first) |
| 8 | Focus Energy fix / high-crit-multiplier change (§1.6) | Only matters if the calc ever computes crit *rate* itself instead of taking `isCrit` as given - currently N/A | N/A today |

None of these block `useDex('purergb')` from computing correct numbers for the *common* case (an
existing move, on a Pokemon whose own type matches the move, against a target without Defense
Curl up) - they're accuracy gaps for specific move/species combinations, not a blanket "the
numbers are wrong" problem.

## 4. Prototype status

- `useDex('purergb'|'vanilla')` swaps the Gen 1 slot's species, moves and type chart and restores
  it. See `calc/calc/src/data/purergb.ts`'s header comment for exactly how (types.ts adds a real
  `setGen1TypeChart()` export since it's this branch's own file; species.ts/moves.ts are patched
  via `Species.prototype`/`Moves.prototype` instead, since their per-item lookup caches
  (`SPECIES_BY_ID`/`MOVES_BY_ID`) are private and built once at module load - reassigning the
  exported `SPECIES`/`MOVES` arrays after that point silently does nothing. See the "engine
  surgery" note below for why `TypeName` itself was *not* widened this way.
- 3 jest tests (`calc/calc/src/test/purergb.test.ts`): a new-type effectiveness case (Fighting vs
  Crystal/Ground), a custom move (Dust Claw), and a `useDex('vanilla')` round-trip. All pass, hand
  math in the test comments. `npx jest src/test`: 119 failed / 121 passed (baseline before this
  branch's addition was 119 failed / 118 passed - the +3 passed are these tests; no new failures).
  `npx tsc -p . --noEmit`: clean.
- **Engine surgery finding**: extending `interface.ts`'s closed `TypeName` union with the 6 new
  names (the literal ask in HANDOFF's task 7) breaks `stats.ts`'s exhaustive Hidden-Power IV/DV
  table (`stats.ts:17,24` - `HPTypeName = Exclude<TypeName, ...>`; `HP: {[type in HPTypeName]:
  ...}` then requires an entry for every pureRGB type too, even though Hidden Power doesn't exist
  until Gen 2 and none of pureRGB's types apply there). `stats.ts` is out of scope for this branch
  ("don't touch stats.ts/pokemon.ts"). Resolution used here: `TypeName` in `interface.ts` is
  **unchanged**; `purergb.ts` builds its species/move data as untyped object literals (so
  `"Magma"` etc. infer fine on their own) and casts the whole table once,
  `as unknown as {[id: string]: I.Specie}` / `I.Move`, at its module boundary. This is confined
  entirely to `purergb.ts` and doesn't touch any shared exhaustive-per-type table elsewhere in the
  engine (grepped for `[type in TypeName]`-style mappings outside this branch's files: only
  `stats.ts`'s `HP` table is non-optional/exhaustive; the others - `interface.ts:170`,
  `types.ts:5,459,465`, `move.ts:223,311` - are all `?:` and don't force new-type entries).
- **Not modeled**: alternate STAB, Ghost's dynamic category, Defense Curl's damage-reduction
  effect, the four optional type-chart toggles, Siphon Snag/Firewall/Heat Rush's non-damage
  effects, per-move multihit counts. All listed in §3 with estimates.

## 5. Frontend needs (beyond this prototype's scope, noted for the coordinator)

- A pureRGB gen-1-variant selector (or a "pureRGB" checkbox next to the Gen 1 radio) that calls
  `useDex('purergb')`/`useDex('vanilla')` before the calc runs - this prototype only exposes the
  function, nothing calls it yet.
- Type color CSS for the 6 new types (`calc/src/css` or wherever the gen 1-8 type badges are
  themed) - Crystal/Bonemerang/Tri/Floating/Magma/Typeless have no existing swatch.
  `species.types`/`move.type` will render as their literal string otherwise (unstyled).
  `slink_bridge.js`'s "(No Move)" fallback warning (HANDOFF task 3) should already catch a
  pureRGB move name that doesn't resolve, once the bridge sends `gen: 1` + a pureRGB flag and the
  calc-preview path calls `useDex`.
- Species/move dropdowns are presumably already generation-scoped (task 2 of HANDOFF); once
  `useDex('purergb')` runs before populating them, the 163 species / 165 moves above should just
  appear - not verified against the live UI since this task was scoped to the engine only.
