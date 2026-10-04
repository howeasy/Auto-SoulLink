# Polished Crystal — acquisition paths and Soul Link key effects

**Card: facts only, no decisions.** This document gives the owner what is needed to rule on the
Polished-only (or Polished-changed) acquisition paths. Every section states *what the code does*,
*where it is*, *what marks it at runtime*, and then 2–3 **ruling options with consequences**. It
does not choose.

Source: `F:/slink-work/cache/polished/src` (**polishedcrystal v3.2.3**, the same tree
`data/games/polished_crystal/profile.json` and `docs/polished/RAM.md` are pinned to). Pack data:
`data/games/polished_crystal/{gifts,static_encounters,encounter_tables,trainers}.json`.

## 0. What "acquisition" means here, and the vanilla baseline

SLink links two players' Pokémon by a **mon key**. Vanilla Gen 2 classes acquisitions as **wild
catch / static / gift (givepoke) / in-game trade / hatched egg**, and those five were ruled in
`docs/gen2/PLAN.md` and implemented as: a `gift_` namespace remap (`gift_link_area`,
`server/adapters/gen2_gsc.py:331` in the Gen 2 adapter family), a fixed-species-gift-area set
(`_FIXED_SPECIES_GIFT_AREAS`, derived from `gifts.json` rows), and a Lua reducer that proves a
capture by matching a **call site** (`lua/gen2/signals.lua:867` for statics, `:962` for givepoke,
`:899` for roamers) before asserting the observed mon equals the row.

**The decisive fact for this card:** Polished's mon key is **not** Gen 2's.
`server/adapters/polished_codec.py:207` `key()` returns `DDDDDD:OOOO:SSS:TT` — three DV bytes, OT
ID, **9-bit species**, and a **traits byte** (`shiny bit 7 | gender bit 6 | form bits 0-4`). Gen 2's
key had no traits byte. Polished also stores a **personality byte** (party +0x20) carrying the
shiny bit, the ability slot and the nature (`polished_codec.py:10`, `:29`). So a Polished identity
key is sensitive to **three** things vanilla's was not: form, gender, and DV bytes.

Second decisive fact: **the Polished client composition does not exist yet.** `lua/gen2/entry.lua:19-21`
records Polished as DEV-GRADE admitted by `Entry.admit_polished` only, and states "the client
composition is a later card (`lua/gen2/polished.lua` holds the reads)". So there is currently **no**
runtime acquisition reducer for Polished — every ruling below is for code that has yet to be
written, which is exactly why the options matter now.

---

## 1. Wonder Trade — the only path that *removes* a Pokémon

`engine/events/wonder_trade.asm` (599 lines).

### What it does

`WonderTrade::` (`wonder_trade.asm:1`) prompts, calls `SelectTradeOrDayCareMon` with
`PARTYMENUACTION_GIVE_MON` (`:14`), and **refuses eggs** (`:19-24`, substitutes the `EGG` marker)
and **refuses spiky-eared Pichu** (`:26-38`).

`DoWonderTrade` (`:88`) then:

1. Reads the **sent** mon's level into `d` (`:105-108`).
2. Picks a random species with `RandomRange16` over `NUM_SPECIES` (`:110-111`), then **rejects and
   re-rolls until the level band `ValidPokemonLevels` brackets the sent mon's level**
   (`:112-122`). The received species' level is therefore constrained to the sent mon's level.
3. **Removes the sent mon from the party** — `predef RemoveMonFromParty` (`:203`), after setting
   `wCurPartySpecies` to the *received* species and `wCurPartyLevel` to the sent mon's level.
4. Adds the received mon — `predef TryAddMonToParty` (`:208`), form from
   `GetWonderTradeOTForm` (`:205`).
5. Gives the received mon a **random 2-byte OT ID** (`:224-231`), **random 3 DV bytes**
   (`:266-274`), a **random nature** (`:277`, comment "Random nature"), and a **random ball**
   (2/3 Poké Ball, else one of several, `:249-263`).

**The partner is NOT a real player.** It is a generated Pokémon: random species, random OT ID,
random DVs, random nature. There is no second BizHawk instance, no link cable partner, and no
SLink wire traffic.

Special case: if the player has beaten the Elite Four and **not** yet received the GS Ball Pichu,
the received mon is a spiky-eared Pichu holding a GS Ball (`GetGSBallPichu`, `:96-101`).

### Can it be repeated? Does it consume a slot?

Repeatable — there is no `setevent` gating the post-Elite-Four branch except the GS Ball flag, and
nothing marks the trade itself as consumed. It **removes one party slot** (the sent mon) and
**adds one** (the received mon), so a full party means the received mon goes to a box
(`TryAddMonToParty` semantics) — **UNVERIFIED**: I did not read `TryAddMonToParty` to confirm the
box fallback; the route's `iffalse_jumpopenedtext DayCareText_PartyAndBoxFull` pattern at
`maps/DayCare.asm:134` shows this codebase does check, but that is the Day Care script.

### RAM / symbols that mark it

`wPlayerTrademonSpecies`, `wOTTrademonSpecies`, `wPlayerTrademonForm`, `wOTTrademonForm`,
`wPlayerTrademonID`, `wPlayerTrademonDVs`, `wPlayerTrademonPersonality`,
`wOTTrademonID`, `wOTTrademonDVs`, `wOTTrademonForm`, `wCurPartySpecies`, `wCurPartyLevel`,
and `hScriptVar = 1` set by `DoWonderTrade` (`:89-90`) before the animation.

### What a Nuzlocke player would expect, and what breaks

A Nuzlocke player expects to **keep** the Pokémon they send and to receive a partner's. Here the
sent Pokémon is **gone**. Two consequences for a link:

- **Sending a linked mon breaks the pair.** The partner's side still holds its partner; there is no
  Soul Link event for a *departure*, so the pair would silently go stale with one side empty.
- **Receiving a generated mon is an uncatchable acquisition.** It is not a wild encounter, not a
  gift site, and its species is not in any pack table — so there is no area to link it to.

### Ruling options

| Option | Consequence |
|---|---|
| **A. Out of scope — refuse the route** | Simplest and safest. But `wonder_trade.asm` is a stock script reachable from ordinary play; refusing means SLink must detect it and block, or the pair state is unmaintained. |
| **B. Treat as an acquisition in a `trade`-namespaced area** (mirrors vanilla NPC-trade handling) | The received mon links to the partner's next acquisition. Costs: a new acquisition kind in the reducer and a new area namespace; the sent mon still leaves, so **both** rules are needed. |
| **C. Treat send as a forced faint/retirement** (partner gets `force_faint`) | Preserves "both sides lose the pair", matching the whiteout/dead-zone spirit. Costs: the partner's Pokémon is destroyed by a decision the local player made — arguably the most Soul-Linked reading, and the most surprising to the player. |

**Owner decision needed: which of A / B / C, and does a Wonder Trade also count as a *departure* that must propagate?** (Question 1 below.)
---

## 2. Eggs: Day Care breeding, the Odd Egg, and the Mystri Egg

### 2.1 `giveegg` gifts — 7 rows, and the species is a `dw`

`data/games/polished_crystal/gifts.json` has **28 `givepoke` rows and 7 `giveegg` rows**. All 7
`giveegg` rows:

| id | species |
|---|---|
| `DayCare:DayCareLadyScript:125` | 152 (Chikorita) |
| `DayCare:DayCareLadyScript.GiveCyndaquilEgg:129` | 155 (Cyndaquil) |
| `DayCare:DayCareLadyScript.GiveTotodileEgg:133` | 158 (Totodile) |
| `DragonsDenB1F:DragonsDenB1FRivalScript:150` | 158 (Totodile) |
| `DragonsDenB1F:DragonsDenB1FRivalScript.GiveChikoritaEgg:154` | 152 (Chikorita) |
| `DragonsDenB1F:DragonsDenB1FRivalScript.GiveCyndaquilEgg:158` | 155 (Cyndaquil) |
| `VioletPokeCenter1F:VioletPokeCenter1FElmsAideScript.AskTakeEgg:56` | 175 (Togepi) |

**Fact that matters for a decoder:** unlike every `givepoke` row, **all 7 `giveegg` rows carry
`"rom": null`, `"level": null`, `"item": null` and `"area_id": null`.** There is no anchor, so a
ROM-side decoder has nothing to point at *from the pack*. The anchor has to come from the script.

The script does contain the species. `maps/DayCare.asm:124` is `giveegg CHIKORITA`, and the macro
is `macros/scripts/events.asm:354-360`:

```
MACRO giveegg
	db giveegg_command
	if _NARG >= 2
		dp \1, \2 | IS_EGG_MASK
	else
		dp \1, PLAIN_FORM | IS_EGG_MASK
	endc
```

So a `giveegg` command is **3 bytes: `$34` + a `dw`** whose high byte is `form | IS_EGG_MASK`
(`0x40`, `polished_codec.py:IS_EGG_MASK`) and whose low byte is the species. **The offset rule is
`dw` at `command + 1`, not a bare species byte** — this differs from `givepoke`, whose command is
`db $2d, species, level, item, trainer` and therefore a *single* species byte. A decoder written
for `givepoke` would read the low half of the `dw` correctly by luck on a plain form and **wrongly
on any formed egg** (the egg marker lives in the *high* byte, so species is still the low byte —
but a formed egg's form byte is the high one, and a reader that assumes "byte+1 is species and
byte+2 is level" misreads it).

Ruling options: **(A)** decode `giveegg` as its own operation with the `dw` rule and keep the
`gift_` remap; **(B)** treat `giveegg` exactly as vanilla did — a gift whose party slot holds the
egg marker until hatch, so the capture is at **hatch**, never at `GiveEgg` (this is the existing
vanilla ruling, "O-15", cited in `server/adapters/gen2_gsc.py:99-111`); **(C)** drop egg gifts
entirely and let the hatch path own them.

### 2.2 Day Care breeding

`engine/events/daycare.asm` (1105 lines). Breeding produces an egg that is later **received** into
the party via `AddTempMonToParty` (`:500`); the received record has `MON_IS_EGG_F` set (`:1039`).
The received egg's **species follows the parent's**, so it is not a fixed species and cannot come
from a pack table. The hatch is the acquisition, exactly as in vanilla.

### 2.3 The Odd Egg — a random *species*, from a weighted table

`engine/events/odd_egg.asm:1-13`, `GiveOddEgg`:

```
	ld a, 100
	call RandomRange
	ld hl, OddEggProbabilities
.loop
	cp [hl]
	inc hl
	jr nc .loop
	...
	ld hl, OddEggs
	ld bc, ODD_EGG_LENGTH
	rst AddNTimes
```

So the species is drawn from a **weighted table** (`data/events/odd_eggs.asm`, included at
`odd_egg.asm:107`), not a script constant. Gender is then random (`:14-16`). On UPR this table is
rewritten in place, so a randomized cart's odd egg is a different species again.

### 2.4 The Mystri Egg — a fixed species from a struct table

`engine/events/odd_egg.asm:18-21`, `GiveMystriEgg`: gender is *specified in the egg struct*
(`xor a` / `ld [wCurForm], a`, `ld hl, MystriEgg`), then it falls through to `GiveSpecialEgg`
(`:22`), which builds a temp mon at **level `EGG_LEVEL` = 1** (`:57-60`), copies 4 bytes of
**DVs and the first personality byte** (`:44`), and either adds it to the party or a box
(`AddTempMonToParty` / `UpdateStorageBoxMonFromTemp`, `:73-86`), returning a status in `hScriptVar`
(`0` failed / `1` party / `2` box, `:88-89`).

Note this shares one tail with `GiveOddEgg`, so a runtime detector keyed on "an egg appeared"
cannot tell the two apart by tail alone — it must distinguish the caller.

Ruling options for **both** egg kinds: **(A)** one `gift_daycare`-style namespace for every hatch
(mirrors vanilla's `policy.egg_hatch_area == "gift_daycare"`, asserted at
`server/adapters/gen2_gsc.py:215`); **(B)** separate namespaces so an Odd Egg (random species) and
a Mystri Egg (fixed species) do not share an encounter slot; **(C)** refuse hatches from
randomised-species sources because no pack can name the species.

**Owner decision: do Odd Egg and Mystri Egg share the Day Care hatch area, or do they get their
own?** (Question 2.)

---

## 3. In-game trades — 9, and their fields are richer than Gen 2's

`data/events/npc_trades.asm`, `assert_table_length NUM_NPC_TRADES` (`:75`) with exactly **9**
entries: MIKE, KYLE, TIM, EMY, CHRIS, KIM, JACQUES, HARI, JEEVES.

Each record is `dp <wants>` / `dp <gives> <form>|<gender>` / nickname (11) / three `$EE` filler
bytes / `HIDDEN_ABILITY | NAT_*` / ball / held item / `dw <OT ID>` / OT name.

**Polished-specific fields vanilla Gen 2 did not have on the table:**

- **Ability is fixed**: every row says `HIDDEN_ABILITY` (`:5`, `:12`, …). So all 9 trade mons have
  ability slot 2 — the hidden ability.
- **Nature is fixed**: `NAT_ATK_UP_SATK_DOWN`, `NAT_SPE_UP_DEF_DOWN`, … (`:5`, `:12`, …).
- **Gender is fixed**: `dp MACHOP, FEMALE`, `dp VOLTORB, MALE`, … (`:4`, `:11`, …).
- **Forms**: JEEVES gives `dp WEEZING, GALARIAN_FORM | MALE` (`:71`) — a **formed** trade mon, which
  moves the `TT` traits byte of the Polished key.

Consequence: a trade mon's ability/nature/gender/form are all **known in advance from the table**,
and `dw <OT ID>` makes the key's `OOOO` half known too. Only the **DV bytes** (`DDDDDD`) are
outside the table — **UNVERIFIED**: I did not read what fills DVs for an NPC trade mon; vanilla
Gen 2 used a fixed `$EE,$EE,$EE` pattern and Polished may differ.

Ruling options: **(A)** treat each trade as a `givepoke`-class static site in a `trade_<town>`
namespace (the vanilla treatment); **(B)** treat it as a `wild`-class acquisition because the
mon arrives via a party add, not a givepoke; **(C)** rule that a *fixed* ability+ nature + gender +
form trade mon is too deterministic to link and refuse it.

**Owner decision: which namespace class do the 9 NPC trades belong to? (Question 3.)**

---

## 4. Formed statics — the Galarian birds

`maps/CherrygroveBay.asm:32` `CherrygroveBayGalarianBirdsScript` gates three encounters, each with
its own event flag (`:50`, `:71`, `:92`) and its own `ENGINE_PLAYER_CAUGHT_*` flag (`:66`, `:87`,
`:108`):

```
	cry MOLTRES            (:56)
	loadwildmon MOLTRES, GALARIAN_FORM, 65   (:59)
```

and the same shape for ARTICUNO (`:77`, `:80`) and ZAPDOS (`:92`, `:101`) — **all three at level
65**.

So a **formed** static uses `loadwildmon species, form, level`, and the form is part of the command.
This matters because the Polished key's `TT` byte carries the **form** (`polished_codec.py:216-219`):
catching the Galarian form produces a **different key** from the same species in another form. The
existing static matcher in `lua/gen2/signals.lua:868` compares `row.species == after.mon.species_id`
only — **no form comparison** — so under Polished a formed static would match a row whose species
matches but whose form does not.

Ruling options: **(A)** extend the static row with a `form` field and require
`species + form + runtime_battle_type` to match (the strongest); **(B)** key statics by species
only and let the form live inside the key (weaker, and a wrong-form catch would be mis-attributed);
**(C)** give each formed static its own `static_<map>_<species>_<form>` area id.

**Owner decision: do static rows carry a form, and does the area id encode it? (Question 4.)**

---

## 5. Roamers, swarms, and the other wild tables

**Roamers** are unchanged in shape from vanilla: `engine/overworld/wildmons.asm:683` `InitRoamMons`
initialises `wRoamMon1Species`/`wRoamMon2Species` (`:688`, `:691`) and levels (`:695`), and
`CheckEncounterRoamMon` (`:258`) fires the encounter. Polished's `gen2_rom_scan` already decodes
`InitRoamMons` for Gen 2 (`server/adapters/gen2_rom_scan.py:271`), and the vanilla ruling is the
`legend_<species>` namespace with `roamer_consumes_ordinary_area: false`
(`server/adapters/gen2_gsc.py:213-216`, asserted).

**Swarms are new.** `data/wild/swarm_grass.asm` (61 lines) and `data/wild/swarm_water.asm`
(5 lines) are separate tables from the ordinary grass/water tables. The grass swarm example is
Dunsparce and it is **form-bearing**:

```
	wildmon 3, DUNSPARCE, DUDUNSPARCE_THREE_SEGMENT_FORM
	wildmon 3, DUNSPARCE, DUDUNSPARCE_TWO_SEGMENT_FORM
```

Two different forms of one species at the same level in one table — so, as in §4, species alone
does not identify the encounter.

**Headbutt / rock smash** are also present (vanilla has both), and the collision **bug contest**
equivalents exist under `engine/events/bug_contest/`.

Ruling options for swarms: **(A)** treat a swarm encounter as an ordinary wild encounter on that
map (no special class); **(B)** give swarms their own namespace so a swarm does not consume the
route's ordinary encounter slot; **(C)** refuse swarm tables entirely, treating them as a randomizer
surface SLink will not model.

**Owner decision: do swarm encounters consume the ordinary route encounter slot? (Question 5.)**

---

## 6. Kurt apricorn balls and fruit trees — items only, no Pokémon

`engine/events/kurt.asm` (236 lines) and `engine/events/fruit_trees.asm` (175 lines) contain
**no** `givepoke`, **no** `loadwildmon`, **no** `AddMonToParty` and **no** `AddTempMonToParty`
(verified by grep over both files). They hand over **items**. That makes them the cleanest case on
this card: there is nothing to link.

**Ruling option (A, effectively forced): no acquisition event.** The only real question is whether
a Kurt ball / fruit tree can hand over a **species-bearing item** that some other script then
uses. **UNVERIFIED** — I did not audit every consumer of the ball IDs.

---

## 7. Identity mutation — what can change a key in place

This is the section with the most Soul Link consequence, because the Polished key packs **DV
bytes, species, form, gender and shiny** into the identity string (`polished_codec.py:207-219`).
Anything that rewrites a field in the key changes the identity.

| Path | What it writes | Key impact | Evidence |
|---|---|---|---|
| **Ability Patch** | rewrites the ability slot in the personality byte | **none** — ability is not in the key (`polished_codec.py:209` "it drops … the ability slot and nature") | `engine/items/item_effects.asm:3370-3392` (`cp ABILITYPATCH`, `HIDDEN_ABILITY` guard) |
| **Mint Tea / nature change** | rewrites the nature bits of the personality byte | **none**, for the same reason | `engine/events/mint_tea.asm` — **UNVERIFIED**: I did not confirm the byte it writes; the file yielded no `Personality`/`NAT_` hits in my grep |
| **Form change** (e.g. a form item) | rewrites `MON_FORM` | **changes `TT`** — the key's last byte | `engine/items/item_effects.asm:1433` (`ld a, MON_FORM`), `:1980` (`ld bc, MON_FORM - MON_SPECIES`) |
| **Evolution** | changes species | **changes `SSS`** — as in vanilla | `key()` docstring, `polished_codec.py:209` "Evolution changes the species part, as for vanilla" |
| **Hyper training / stat pills** | EVs only | **none** — EVs are not in the key | EV byte is party +11..16 (`polished_codec.py:29`), not key material |

The load-bearing consequence: **ability and nature changes are key-preserving; form changes are
not.** Two mons that are the "same" Pokémon to a player can have different keys after a form
change, and vice-versa an ability patch does not disturb a link.

Ruling options for form changes: **(A)** treat a form change as a **key migration**, exactly like
evolution — emit the old/new key pair so the server can re-point the link; **(B)** forbid form
changes on a linked mon (the client refuses to use the item); **(C)** ignore it and let the link go
stale.

**Owner decision: is a form change a key migration (A), a refused action (B), or ignored (C)?
This is the single highest-consequence decision on the card. (Question 6.)**

---

## 8. Owner decisions needed (7, each answerable in one sentence)

1. **Wonder Trade**: does sending a Pokémon away propagate to the partner as a loss (C), and does
   the received generated Pokémon count as an acquisition (B) or not (A)?
2. **Eggs**: do the Odd Egg and the Mystri Egg share the Day Care hatch area, or each get their own?
3. **NPC trades**: do the 9 trades link in a `trade_<town>` static namespace (A) or a wild-style
   namespace (B)?
4. **Formed statics**: do static rows carry a `form`, and does `static_<map>_<species>_<form>` encode
   it in the area id?
5. **Swarms**: does a swarm encounter consume the route's ordinary wild encounter slot, or is it a
   separate namespace?
6. **Form changes**: is a form change a key migration (A), a refused item on a linked Pokémon (B),
   or ignored (C)? — *highest consequence; see §7*
7. **`giveegg` decoding**: may a ROM-side decoder rely on a `dw` at `command + 1` for egg gifts,
   given those rows currently carry no ROM anchor at all?

## 9. Summary table

| Path | Count | Site | Creates a Pokémon? | Key impact |
|---|---|---|---|---|
| Wonder Trade | unbounded | `engine/events/wonder_trade.asm:1` | **yes, and REMOVES one** | new key in; sent mon's key vanishes |
| `givepoke` gifts | 28 rows | `data/games/polished_crystal/gifts.json` | yes | as vanilla |
| `giveegg` gifts | 7 rows | same pack, `operation: "giveegg"` | yes (egg) | at hatch only |
| Day Care breeding | unbounded | `engine/events/daycare.asm:500` | yes (egg) | species follows parent |
| Odd Egg | 1 route | `engine/events/odd_egg.asm:1` | yes | random species — no pack row |
| Mystri Egg | 1 route | `engine/events/odd_egg.asm:18` | yes | fixed species, level 1 |
| NPC trades | **9** | `data/events/npc_trades.asm` | yes | fixed ability+nature+gender+form |
| Formed statics (Galarian birds) | 3 | `maps/CherrygroveBay.asm:59,80,101` | yes | **form changes `TT`** |
| Roamers | vanilla-shaped | `engine/overworld/wildmons.asm:683` | yes | `legend_<species>` namespace |
| Swarms | new tables | `data/wild/swarm_{grass,water}.asm` | yes | **form-bearing rows** |
| Kurt balls / fruit trees | — | `engine/events/{kurt,fruit_trees}.asm` | **no — items only** | none |
| Ability Patch | — | `engine/items/item_effects.asm:3374` | no | **none** (ability not in key) |
| Form change | — | `engine/items/item_effects.asm:1433` | no | **changes `TT`** |
| Evolution | — | `polished_codec.py:209` | no | changes `SSS`, as vanilla |

## 10. Verification notes

Everything marked **UNVERIFIED** above is a deliberate gap, not an omission:

- `TryAddMonToParty`'s box fallback for a full party on Wonder Trade (§1) — the callee was not read.
- The NPC-trade DV fill (§3) — the `dw` OT ID is in the table; the DV bytes were not traced.
- `mint_tea.asm`'s target byte (§7) — the file produced no `Personality`/`NAT_` grep hits.
- Kurt ball / fruit-tree item consumers (§6) — the two event files are clean, but downstream
  consumers of the ball IDs were not audited.

The claims block below is machine-checkable: each entry names an absolute path, a line and an exact
substring on that line.

```json CLAIMS
[
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 207,
  "expect": "def key(mon) -> str:"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 214,
  "expect": "traits = ((0x80 if mon[\"shiny\"] else 0) | (0x40 if mon[\"gender\"] == \"female\" else 0)"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 211,
  "expect": "it drops is-egg (hatching is not a new mon),"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 45,
  "expect": "GENDER_MASK, IS_EGG_MASK, EXTSPECIES_MASK, FORM_MASK"
 },
 {
  "path": "F:/slink-work/wt/polished/lua/gen2/entry.lua",
  "line": 20,
  "expect": "the client composition is a later card"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/gen2_polished.py",
  "line": 331,
  "expect": "def gift_link_area("
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/gen2_rom_scan.py",
  "line": 271,
  "expect": "def _roamer_initial("
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 1,
  "expect": "WonderTrade::"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 13,
  "expect": "ld b, PARTYMENUACTION_GIVE_MON"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 19,
  "expect": "bit MON_IS_EGG_F, a"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 88,
  "expect": "DoWonderTrade:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 96,
  "expect": "eventflagcheck EVENT_BEAT_ELITE_FOUR"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 102,
  "expect": "call GetGSBallPichu"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 112,
  "expect": "ld bc, NUM_SPECIES"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 114,
  "expect": "ld hl, ValidPokemonLevels"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 121,
  "expect": "jr nc, .random_trademon"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 203,
  "expect": "predef RemoveMonFromParty"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 209,
  "expect": "predef TryAddMonToParty"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 230,
  "expect": "ld de, wOTTrademonID"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 273,
  "expect": "; Random DVs"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm",
  "line": 290,
  "expect": "; Random nature"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/odd_egg.asm",
  "line": 1,
  "expect": "GiveOddEgg:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/odd_egg.asm",
  "line": 4,
  "expect": "ld hl, OddEggProbabilities"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/odd_egg.asm",
  "line": 22,
  "expect": "GiveMystriEgg::"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/odd_egg.asm",
  "line": 26,
  "expect": "ld hl, MystriEgg"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/odd_egg.asm",
  "line": 67,
  "expect": "assert EGG_LEVEL == 1"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/odd_egg.asm",
  "line": 107,
  "expect": "INCLUDE \"data/events/odd_eggs.asm\""
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/daycare.asm",
  "line": 500,
  "expect": "farcall AddTempMonToParty"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/daycare.asm",
  "line": 1039,
  "expect": "set MON_IS_EGG_F, [hl]"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/scripts/events.asm",
  "line": 354,
  "expect": "MACRO giveegg"
 },
 {
  "path": "F:/slink-work/cache/polished/src/maps/DayCare.asm",
  "line": 125,
  "expect": "giveegg CHIKORITA"
 },
 {
  "path": "F:/slink-work/cache/polished/src/data/events/npc_trades.asm",
  "line": 3,
  "expect": "NPC_TRADE_MIKE"
 },
 {
  "path": "F:/slink-work/cache/polished/src/data/events/npc_trades.asm",
  "line": 75,
  "expect": "assert_table_length NUM_NPC_TRADES"
 },
 {
  "path": "F:/slink-work/cache/polished/src/data/events/npc_trades.asm",
  "line": 70,
  "expect": "dp WEEZING, GALARIAN_FORM | MALE"
 },
 {
  "path": "F:/slink-work/cache/polished/src/maps/CherrygroveBay.asm",
  "line": 59,
  "expect": "loadwildmon MOLTRES, GALARIAN_FORM, 65"
 },
 {
  "path": "F:/slink-work/cache/polished/src/maps/CherrygroveBay.asm",
  "line": 80,
  "expect": "loadwildmon ARTICUNO, GALARIAN_FORM, 65"
 },
 {
  "path": "F:/slink-work/cache/polished/src/maps/CherrygroveBay.asm",
  "line": 101,
  "expect": "loadwildmon ZAPDOS, GALARIAN_FORM, 65"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/overworld/wildmons.asm",
  "line": 683,
  "expect": "InitRoamMons:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/data/wild/swarm_grass.asm",
  "line": 8,
  "expect": "DUDUNSPARCE_THREE_SEGMENT_FORM"
 },
 {
  "path": "F:/slink-work/cache/polished/src/data/wild/swarm_grass.asm",
  "line": 11,
  "expect": "DUDUNSPARCE_TWO_SEGMENT_FORM"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/items/item_effects.asm",
  "line": 3373,
  "expect": "cp ABILITYPATCH"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/items/item_effects.asm",
  "line": 1433,
  "expect": "ld a, MON_FORM"
 }
]
```
