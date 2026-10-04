# FORMS — a Polished randomizer pool that includes forms

Owner ruling: the Polished pool **includes forms**. This doc is the design for
getting there from the handler in `patch/upr/0016-0019`, which currently refuses
every formed slot. Design only; nothing here is implemented.

**The one sentence that matters:** a form is not a species. In Polished it is five
bits sharing a byte with gender, is-egg and the high bit of a 9-bit species, and it
*re-indexes the base-stat and evolution tables*. So "widen the pool" is really
"give the handler a second key and a second table index".

## 1. The byte encoding (Q1)

`constants/pokemon_data_constants.asm:243-247`:

```
DEF GENDER_MASK      EQU %10000000
DEF IS_EGG_MASK      EQU %01000000
DEF EXTSPECIES_MASK  EQU %00100000
DEF FORM_MASK        EQU %00011111
DEF SPECIESFORM_MASK EQU EXTSPECIES_MASK | FORM_MASK
```

and `:159-162` — **`MON_GENDER`, `MON_IS_EGG`, `MON_EXTSPECIES` and `MON_FORM` are all
aliases of the same `MON_PERSONALITY + 1` byte**. One physical byte, four meanings.

The `dp` macro (`macros/data.asm:89-91`) emits
`db LOW(\1), HIGH(\1) << MON_EXTSPECIES_F | \2`, i.e. byte0 = `LOW(species)` and
byte1 = `HIGH(species)<<5 | form`. So a formed species is **two bytes**:
`species9 = byte0 | ((byte1 & 0x20) << 3)`, `form = byte1 & 0x1F`.

Per context:

| context | how a formed mon is written | what the handler must learn |
|---|---|---|
| **wild slot** (`macros/asserts.asm:102-105`, `wildmon` = `db level` + `dp`) | `level`, then `LOW`, then `HIGH<<5\|form` | read+write both bytes; the current `plainSlot` refuses on form |
| **water slot** | same 3-byte shape | same |
| **fish entry** (`data/wild/fish.asm:36-41` `fishentry`) | `chance`, `dp`, `level` | same; plus species-0 time rows stay excluded |
| **trainer mon** (`data/trainers/macros.asm:323-324`) | `db level` then `dp species, form` | same; the trainer record is variable-length (`_tr_size`, `:306`) so a size-preserving write is required |
| **starter / static / gift** (`macros/scripts/events.asm:319-327` `givepoke`; `loadwildmon`) | `db givepoke_command`, `dp`, `db level`… | same |
| **NPC trade** (`data/events/npc_trades.asm`, `NPCTRADE_GIVEMON/GETMON` are `rw`) | a `dp` pair inside a fixed 31-byte struct | same |
| **party / box record** (`breed_struct`, `pokemon_data_constants.asm:137,161-162`) | `Species` at +0 is the LOW byte only; the form lives at `MON_PERSONALITY+1` | **hardest.** The form byte is shared with gender/egg; a naive `hi = (sp>>8)<<5\|form` write into a party record **clobbers gender and is-egg** |

**The party-mirror hazard is the single most important line in this document.** A
wild/trainer `dp` has a dedicated form byte. A party record does not: bit 7 is gender
and bit 6 is is-egg. Any writer that copies a `dp` pair into a party mirror must
preserve `byte1 & 0xC0` and only set bits 0-4 (and bit 5 when the species needs it).

## 2. Which forms exist, and what a formed mon needs (Q2)

**46 unique formed wild slots** across `data/wild/*.asm`, matching POOL_EVIDENCE's 46.
The species involved (abridged from the grep): `ARBOK` (3 forms), `CORSOLA`
(GALARIAN), `DIGLETT`/`DUGTRIO` (ALOLAN), `DUNSPARCE` (TWO_SEGMENT, THREE_SEGMENT),
`EKANS` (ARBOK_JOHTO), `GRAVELER` (ALOLAN), `RATTATA` (ALOLAN), `SANDSHREW`/
`SANDSLASH` (ALOLAN), `SNEASEL` (HISUIAN), `TAUROS` (PALDEAN, PALDEAN_FIRE,
PALDEAN_WATER).

Trainer data carries `ALOLAN_FORM` and `HISUIAN_FORM` spellings
(`data/trainers/parties.asm`). **UNVERIFIED** whether the full wild set also appears
in trainers, or only a subset — I did not enumerate that.

`constants/pokemon_constants.asm` has **84 `ext_const` form constants**; forms start at
`FIRST_COSMETIC_FORM_MON` (`:348`). `data/pokemon/base_stats/` has **334 files** for
291 species — the surplus is species+non-cosmetic variants.

**So a randomized formed mon needs a record index that is not `species`.** Today the
handler's model is `pokes[1..N]` keyed by species id
(`Gen2Constants`-style, per `0017:134` `pokes[PolishedConstants.species9(...)]`). A
formed mon must resolve to the `(species, form)` record in `BaseData` and
`EvosAttacksPointers` — **UNVERIFIED** the exact mapping from a form id to a record
index; that is `data/pokemon/base_stats/*.asm`'s include order, and deriving it is the
first implementation task.

## 3. Pool rules a forms-included pool needs (Q3)

**Split the form space before anything else.** `FIRST_COSMETIC_FORM_MON` is the
boundary the source itself draws.

| class | examples | in the pool? | why |
|---|---|---|---|
| **variant** | Alolan, Galarian, Hisuian, Paldean | **yes** (owner ruling) | they change types, stats, evolution and evo family — they are different creatures for Soul Link |
| **cosmetic** | Unown's 28 letters, gender presentation, Spinda dots | **no** | 56 cosmetic forms on 5 species; none changes stats, type or evo family, so a link is decided identically with or without them. Including them multiplies the pool for no semantic gain and makes the Unown 28-letter case a special case everywhere |
| **evolution-only** | a form reachable only by evolving | **yes, but as a target** | it must be in `EvosAttacks`/evolutions, not in the encounter pool; a randomized *evolution* may land on one |
| **gender-locked** | any form whose availability depends on the gender byte | **no** | the form byte's bits 6-7 are gender/egg in party records; a form whose legality depends on them cannot be validated by the form bits alone |

**Concretely: the pool is species × non-cosmetic forms.** Cosmetic forms stay out
because they are invisible to every Soul Link rule we implement.

## 4. The SLink identity side (Q4)

**The key already carries the form — that is good news.**
`server/adapters/polished_codec.py:207-215`: `key(mon)` is
`DDDDDD:OOOO:SSS:TT` where `TT` is "traits (shiny bit 7, gender bit 6, form 0-4)", and
`:142` re-encodes `EXTSPECIES_MASK | form`. `:120` `species_of(low, form_byte) = low |
(form_byte & EXTSPECIES_MASK) << 3`. So **two links of the same species in different
forms are different keys** and Soul Link would accept both. That is the correct
behaviour for variant forms.

**The type clause is the problem.** `server/adapters/gen2_polished.py:411-417`:

```python
def species_types(self, species_id, form=0):
    if form == 0 and any(key[0] == species_id for key in self._variants):
        return None
```

It returns `None` for the **base form of a variant-bearing species**, and `state.py`
passes only the species, never the form. So today an ordinary Rattata has no type row
and the type clause *skips* the pair. With forms in the pool that becomes a hole:
form-0 Rattata vs Alolan Rattata is **skipped rather than judged** — the exact wrong
outcome the comment (`:412-414`, review cx-7110b381 #1) was written to avoid.

Required: resolve types **per form**. The pack has a `form` key
(`self._row(species_id, form)` at `:417`), so the adapter can answer correctly; the
blocker is `state.py` passing no form. **UNVERIFIED** whether `state.py` can be changed
without touching the shared Gen 2 path — that is an owner call.

`evo_family(species_id)` (`:419-420`) is **species-keyed with no form**. An Alolan
Rattata and a Kantonian Rattata would share a family, so a species clause would treat
them as a conflict even though the types differ. **Needs a per-form family or an
explicit same-species-different-form allowance.**

Calculator and trainer-data effects: **none in Polished** — `manager.py:220` refuses
the calculator for Polished ("no Polished Crystal data (new species, forms and
abilities)"), so a forms-included pool has no calculator to disagree with. The type
clause and species clause are the only form-sensitive rules.

## 5. Handler change list (Q5), in order of risk

| # | change | file / method | risk |
|---|---|---|---|
| H1 | replace `plainSlot` (0017, `return (hi & ~extSpeciesMask) == 0 && ...`) with a *readable* slot test and a separate **writable-species** test that also permits `form != 0` for non-cosmetic forms | `PolishedCrystalRomHandler.plainSlot` | **highest** — this is the gate that currently refuses everything |
| H2 | key the model by `(species, form)`; add a form→base-stat/evo **record index** map | `pokemonList` / `pokes[]` construction | **highest** — a wrong index silently gives a mon the wrong stats |
| H3 | write **two** bytes (`LOW`, `HIGH<<5\|form`) in place, preserving the existing level/PP conventions; keep species-0 fishing rows excluded | the wild-slot writer (0017) | medium |
| H4 | trainer mon write must preserve the record's `_tr_size` and `_tr_flags` (`data/trainers/macros.asm:274-310`) | 0018 trainer writer | medium |
| H5 | **party/box mirror write must preserve `byte1 & 0xC0`** (gender, is-egg) — §1 | wherever a party record is written | **highest**, and easy to get wrong because it is a *different* rule from H3 |
| H6 | a cosmetic-form filter, driven by `FIRST_COSMETIC_FORM_MON` | pool construction | low |
| H7 | server side: resolve `species_types`/`evo_family` per form | `gen2_polished.py:411,419` + the `state.py` call | medium; **owner decision** on touching the shared path |

## 6. Test plan

1. **Round-trip, wild**: for every formed wild slot in the release ROM, load →
   randomize with the identity permutation → save, and assert **byte-identity**. This
   is the cheapest proof that H1+H3+H5 lose nothing.
2. **Round-trip, trainers**: same for every formed `tr_mon`. Assert `_tr_size` and
   `_tr_flags` are unchanged and the record length is identical.
3. **Round-trip, statics/starters/gifts/trades**: same, plus the 31-byte trade struct
   length.
4. **Gender-preservation falsifier** (the one I would insist on): set gender=female
   and is-egg on a party record, run a formed-mon write, assert bits 6-7 are intact.
5. **Record-index falsifier**: for each of the 46 formed wild slots, assert the
   resolved `BaseData` record's `Species` byte equals the slot's LOW byte, and that
   its type bytes match the *form's* expected types (Alolan Raichu = electric/psychic,
   not normal/fighting).
6. **Pool falsifier**: assert no cosmetic form (Unown letter != A) is ever chosen.
7. **Soul-Link falsifier**: a form-0 Rattata and an Alolan Rattata must be *judged* by
   the type clause, not skipped. This is the §4 hole and needs H7.
8. **Live**: none required for H1-H5 — every one of them is a byte-level round-trip.

## 7. Size and sequencing

| work | days |
|---|---|
| form space enumeration (cosmetic vs variant, from the sources + `variant_forms.asm`) | 0.5 |
| form→record index map, with a generator + `--check` | 1.5 |
| H1/H3 wild writer + round-trip harness | 1.5 |
| H5 gender-preserving party mirror | 1 |
| H4 trainer writer | 1.5 |
| H2 keyed model + species index rebuild | 1.5 |
| H6 pool filter | 0.5 |
| H7 server-side per-form rules | 1 (+ owner decision) |
| **total** | **~9** |

**Same jar cut as the patch-0019 overlay-signature tighten: only H1 and H6, and only as
a refusal-then-widen change.** H1 is small in isolation (relax one predicate) but it
gates on H2, so widening the pool before the record-index map exists would produce
formed mons with the *base* form's stats — a worse failure than refusing. The
signature tighten is independent (Java-side acceptance, no pool involvement) and
belongs in the same cut.

**Recommendation: tighten 0019's overlay check in the next jar cut now, and hold H1
until H2 lands.**

```json
[
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 242,
  "expect": "DEF GENDER_MASK      EQU %10000000"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 243,
  "expect": "DEF IS_EGG_MASK      EQU %01000000"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 244,
  "expect": "DEF EXTSPECIES_MASK  EQU %00100000"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 245,
  "expect": "DEF FORM_MASK        EQU %00011111"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 247,
  "expect": "DEF SPECIESFORM_MASK EQU EXTSPECIES_MASK | FORM_MASK"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 161,
  "expect": "DEF MON_EXTSPECIES EQU MON_PERSONALITY + 1"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 162,
  "expect": "DEF MON_FORM       EQU MON_PERSONALITY + 1"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 155,
  "expect": "DEF MON_PERSONALITY        rw"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 137,
  "expect": "DEF MON_SPECIES            rb"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 360,
  "expect": "DEF GRASS_WILDDATA_LENGTH EQU 2 + (1 + NUM_GRASSMON * 3) * 3"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/data.asm",
  "line": 89,
  "expect": "MACRO? dp ; db species, extspecies | form"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/data.asm",
  "line": 91,
  "expect": "db LOW(\\1), HIGH(\\1) << MON_EXTSPECIES_F | \\2"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/asserts.asm",
  "line": 102,
  "expect": "MACRO? wildmon"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/scripts/events.asm",
  "line": 319,
  "expect": "MACRO givepoke"
 },
 {
  "path": "F:/slink-work/cache/polished/src/data/trainers/macros.asm",
  "line": 270,
  "expect": "MACRO end_trainer"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/npc_trade_constants.asm",
  "line": 4,
  "expect": "DEF NPCTRADE_GIVEMON     rw"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_constants.asm",
  "line": 348,
  "expect": "DEF FIRST_COSMETIC_FORM_MON EQU const_value ; 124"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_constants.asm",
  "line": 318,
  "expect": "DEF NUM_POKEMON EQU NUM_SPECIES - (2 * HIGH(NUM_SPECIES)) ; 121"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 118,
  "expect": "def species_of(low: int, form_byte: int) -> int:"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 120,
  "expect": "return low | (form_byte & EXTSPECIES_MASK) << 3"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 207,
  "expect": "def key(mon) -> str:"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 208,
  "expect": "DDDDDD:OOOO:SSS:TT"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/gen2_polished.py",
  "line": 411,
  "expect": "    def species_types(self, species_id, form=0):"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/gen2_polished.py",
  "line": 415,
  "expect": "if form == 0 and any(key[0] == species_id for key in self._variants):"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/gen2_polished.py",
  "line": 419,
  "expect": "    def evo_family(self, species_id):"
 },
 {
  "path": "F:/slink-work/wt/polished/server/manager.py",
  "line": 220,
  "expect": "\"gen2_polished\": {\"ok\": False, \"why\": \"The calculator has no Polished Crystal data (new species, forms and abilities).\"}"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/upr/0017-slink-Polished-Crystal-wild-encounters.patch",
  "line": 126,
  "expect": "return (hi & ~PolishedConstants.extSpeciesMask) == 0 && species >= 1 && species <= speciesCount;"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/upr/0017-slink-Polished-Crystal-wild-encounters.patch",
  "line": 123,
  "expect": "    private boolean plainSlot(int speciesOffset) {"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/upr/0017-slink-Polished-Crystal-wild-encounters.patch",
  "line": 134,
  "expect": "enc.pokemon = pokes[PolishedConstants.species9(rom[speciesOffset] & 0xFF, rom[speciesOffset + 1] & 0xFF)];"
 }
]
```


---

## Coordinator verification (2026-10-04)

Re-read: `MON_GENDER`, `MON_IS_EGG`, `MON_EXTSPECIES` and `MON_FORM` are all `MON_PERSONALITY + 1`
(`constants/pokemon_data_constants.asm:159-162`), masks `%10000000/%01000000/%00100000/%00011111`, and `dp` writes
`LOW(species), HIGH(species) << MON_EXTSPECIES_F | form` (`macros/data.asm:89-91`). All 29 CLAIMS quotes verify.
Owner ruling 2026-10-04: forms are IN the pool. Accepted sequencing (the OMP's, kept): the patch-0019 overlay-signature
tighten and the forms work ride ONE jar cut (owner: "tighten, then pin once"), so the jar is not cut until H2
(the form -> BaseData/EvosAttacks record-index map, generated with `--check`) and the H5 party-record bit
preservation (`byte1 & 0xC0`) are built and round-trip tested; `plainSlot` stays as the interlock until then. Open
owner question: cosmetic forms (Unown letters etc.) stay OUT of the pool unless the owner says otherwise; the F4
type-clause hole (form-0 variant pairs skipped in `species_types`) needs a `state.py` change (shared Gen 2 path),
raised with the owner before any edit.


---

## Owner rulings 2026-10-04 (recorded by the coordinator)

* **Cosmetic forms are ONE mon** (Unown letters, other cosmetic-only forms): the SLink identity key must NOT
  distinguish them, so `polished_codec.key` has to normalise the cosmetic form bits to 0 (today it keeps form 0-4
  as traits, `polished_codec.py:207-215`).
* **Regional/variant forms are DIFFERENT mons** from the standard counterpart (Alolan Rattata is not Rattata):
  type clause, evolution family and duplicate handling judge them separately.
* The owner allows editing `server/state.py` if needed. Preferred design (adapter isolation): the Polished codec
  exposes an **effective species id** per mon - a variant form maps to its BaseData record index (292..337,
  from `forms_index.json`, FORMS-H2), plain and cosmetic forms keep the species id - so the shared `state.py`
  and the species-keyed `species_types` / `evo_family` need no signature change, and the form-0-with-variants
  skip in `gen2_polished.species_types` (`:411-417`) is removed.
