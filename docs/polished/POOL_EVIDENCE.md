# POOL-EVIDENCE — should the Polished randomizer species pool be 1..251, 1..289, or include forms?

**Doc only. Evidence for an OWNER decision; this document decides nothing.**

Source of truth: `F:/slink-work/cache/polished/src` (polishedcrystal v3.2.3),
`F:/slink-work/wt/polished/data/games/polished_crystal/*.json`, and the UPR patches
`F:/slink-work/wt/polished/patch/upr/0017`, `:0018`, `:0019`.

Every count below was produced by a script over those trees; the counting commands are in §7 so the
coordinator can re-run them. Anything I did not read is labelled **UNVERIFIED**.

---

## 1. The species count: 291 slots, **289** playable — the "291" is not `NUM_POKEMON`

`constants/pokemon_constants.asm`:

```
DEF NUM_POKEMON EQU NUM_SPECIES - (2 * HIGH(NUM_SPECIES)) ; 121
DEF NUM_SPECIES EQU const_value - 1 ; 123
```

**The trailing `; 121` comment is stale.** `data/games/polished_crystal/profile.json` carries
`constants.NUM_POKEMON = 289` and `constants.NUM_SPECIES = 291`, and the arithmetic checks out
exactly: `291 − 2 × HIGH(291) = 291 − 2 = 289`. The two excluded slots are the ones above `$FF`,
which a 8-bit dex list cannot hold.

**Which figure is right: `NUM_POKEMON = 289` is the playable count; `NUM_SPECIES = 291` is the slot
count.** Earlier notes that said "291" were quoting the slot count. `HOOKS.md` §3.5's "NUM_POKEMON
… -> 113" is likewise stale (it predates the profile) and should not be used.

**Occupancy of the 291 slots:** 289 rows are present in `species_index.json`; the gaps are **255 and
256**. So `1..251` is completely full (251 species) and `252..291` holds **38** species across 40
slots.

## 2. Species at 252+ : 38 rows, and base-stat coverage

* **38** species rows at `252..291` (e.g. 252 AZURILL, 253 WYNAUT, 254 AMBIPOM, 257 MISMAGIUS,
  258 HONCHKROW, 259 BONSLY).
* `data/pokemon/base_stats/` holds **334** `.asm` files: 248 match a plain species `const` and **86**
  are per-form files (`arcanine_hisuian`, `articuno_galarian`, `corsola_galarian`, `diglett_alolan`,
  `*_plain`, …).
* **UNVERIFIED:** 41 species rows report no `base_stats` file by `const` name — including
  `RATTATA` (19) and `DIGLETT` (50), which certainly have one. That is a **naming/derivation
  discrepancy in my matching, not a finding about the tree**; I did not chase it. Before the owner
  relies on "every 252+ species has stats", re-run with the profile's own symbol derivation
  (`tools/gen_polished_profile.py`) rather than by filename.

## 3. Variant forms: 46 variant + 56 cosmetic, and what the handler does with them

`species_index.json` `forms`:

| kind | entries | distinct species |
|---|---|---|
| `variant` (Alolan / Galarian / Hisuian / Bloodmoon / three-segment …) | **46** | 43 |
| `cosmetic` (Unown letters, Magikarp patterns) | **56** | 5 |

`patch/upr/0017:50` states the ROM side: `NUM_VARIANT_FORMS = $2e` (**46**), "BaseData/EvosAttacksPointers
records **292..337**", with records `1..291` being species ids (`formeNumber 0`) — 337 records total.
Two variant forms hang off species above 251: **288 Dudunsparc (form 2)** and **285 Ursaluna (form 2)**.

**What the handler does with a formed slot — it refuses.** `patch/upr/0017:118-119`:

> A slot is randomizable only when its form byte is NO_FORM with no gender bit (a plain
> "wildmon level, SPECIES") and it names a real species. Formed slots (ALOLAN_FORM VULPIX, …)

and `:126`: `return (hi & ~PolishedConstants.extSpeciesMask) == 0 && species >= 1 && species <= speciesCount;`

`patch/upr/0018:36-39` repeats it for the trainer/starter/static/trade writers: the writer "keeps the
site's gender and form bits", "**only NO_FORM/PLAIN_FORM sites are in the model, so formed mons are
never read or written**", "Variant forms fold to their species; EGG, the unused `$100` and Unown are
refused", and `bannedForStaticPokemon` / `getBannedFormesForTrainerPokemon` ban them.

**Consequence: the randomizer cannot currently place a variant form into a pool at all.** Widening
the pool to include forms is therefore a *handler* change, not a configuration change.

## 4. The three pool choices and their consequences

| | **A: vanilla `1..251`** | **B: all plain species `1..289`** | **C: all incl. forms** |
|---|---|---|---|
| **SLink key (9-bit)** | Safe. `polished_codec.key` packs species into 3 hex digits (`SSS`, `:207`) and the traits byte carries form; 251 needs 2 digits | Safe — 289 still fits 9 bits; `signals.lua:565` already sets `max_species = 0x1FF` for the Polished key builder | Safe on the wire, but the **form** must arrive in the traits byte or the key is wrong |
| **Server `species_types`** | Unaffected | **Affected**: `gen2_polished.py`'s `species_types(species_id, form=0)` returns `None` for a species that *has* variants (`test_gen2_polished_adapter.py` asserts this for Rattata), so the type clause goes blind on them | Same, plus a **form** argument the clause does not consume today |
| **Calculator** | Full data — the calculator has no Polished set at all (`manager.py` registers no Polished data), so this is already a gap | Adds 38 more species with **no** calc data, and their types/stats are whatever the adapter reports | Worse; forms have no calc entries either |
| **Death / evolution rules** | Unaffected | Evolution **crosses the boundary**: **38** family lines have one side ≤251 and the other ≥252 (e.g. 252→183, 253→202, 257→200, 260→122). A Nuzlocke can therefore catch a 252+ species that evolves into a vanilla one | Same, plus form-change identity risk (form changes alter the key's traits byte) |
| **Handler support** | Already supported | Already supported (a slot is plain iff its form byte is NO_FORM) | **Not supported** — `0017:118-126` and `0018:36-39` refuse formed slots |

## 5. Evolution lines that cross the 251/252 boundary

**38** lines, from `data/games/polished_crystal/evolutions.json` (`family`), where one endpoint is
≤251 and the other ≥252: `252→183, 253→202, 254→190, 257→200, 258→198, 259→185, 260→122, 261→113, …`

Two directions matter and they are **not symmetric**:
* **252+ → vanilla** (e.g. 252 AZURILL → 183 MARILL): a newly-caught species can evolve into a
  vanilla one. Under choice A that species cannot be caught at all, so the line is unreachable; under
  B or C it becomes reachable and the **link key changes species mid-pair** (the identity migration
  the death/evolution rules already handle).
* **vanilla → 252+**: possible only if a vanilla base evolves upward; **UNVERIFIED** — I counted
  family representatives and did not classify each line's direction.

## 6. The decision, stated as options (not made)

* **A — `1..251`.** Zero new code, zero new blind spots: the type clause, the calculator and the
  evolution rules all keep their current coverage, and the randomizer needs no change. Cost: 38
  Polished-native species and 46 variant forms are unrandomizable.
* **B — `1..289`, plain only.** The randomizer needs **no handler change** (a plain slot is already
  in the model). Cost: 38 species enter pools with `species_types` returning `None` for the variant-
  bearing ones, no calculator data, and 38 new evolution crossings.
* **C — include forms.** Requires lifting `0017:118-126` and `0018:36-39`, **and** deciding how a
  form reaches the SLink key (traits byte) and the server's `species_types`. Largest by an order of
  magnitude, and it touches the identity rules rather than a configuration.

## 7. How to re-run the counts

```python
import json, re
from pathlib import Path
S = Path(r"F:/slink-work/cache/polished/src"); W = Path(r"F:/slink-work/wt/polished")
sp  = json.loads((W/"data/games/polished_crystal/species_index.json").read_text())
ks  = sorted(int(k) for k in sp["species"])
prof= json.loads((W/"data/games/polished_crystal/profile.json").read_text())["titles"]["polished"]
print(prof["constants"]["NUM_POKEMON"], prof["constants"]["NUM_SPECIES"])   # 289 291
print(len(ks), [k for k in range(1,292) if k not in set(ks)])             # 289 [255, 256]
print(sum(1 for k in ks if k>=252))                                        # 38
print(len({f["kind"] for f in sp["forms"]}),
      sum(1 for f in sp["forms"] if f["kind"]=="variant"))                 # 2 46
print(sum(1 for k,v in sp["species"].items() if int(k)>251))              # 38
fam = json.loads((W/"data/games/polished_crystal/evolutions.json").read_text())["family"]
print(sum(1 for k,v in fam.items() if (int(k)<=251) != (int(v)<=251)))     # 38
```

## 8. UNVERIFIED, and what settles each

| item | how to settle |
|---|---|
| the 41 species rows with no `base_stats` file by name (§2) | re-derive file names from the profile's own symbol derivation (`tools/gen_polished_profile.py`), not from `const` |
| direction of each of the 38 evolution crossings (§5) | walk `family` and classify; two lines |
| whether `extSpeciesMask` in `PolishedConstants` equals the profile's `EXTSPECIES_MASK` (32) | read the handler constant in `0016` and compare with `profile.json` |
| what the calculator actually has for Polished | `manager.py` registers no Polished set; confirm by reading the registry, not by absence |
| whether any formed slot exists in a *shipped* pool | the handler refuses formed slots at set time, so the answer should be no; confirm against a prepared ROM's `species pool` log |

---

## Coordinator verification (2026-10-04)

Re-counted from `data/games/polished_crystal/species_index.json`: 289 species keys, highest index 291, gaps
at 255 (the Egg index, `egg.index == 255`) and 256 (`invalid_indices`), and 38 species at 252..291. The 16 CLAIMS
quotes verify. Not decided here: the pool is the owner's call. Facts the owner needs: options A (1..251) and B
(all plain species) are handler configuration; C (forms) needs a handler change plus an identity rule. Open
(UNVERIFIED by the OMP): base-stat coverage of the 252+ rows, and the direction of each of the 38 evolution
crossings; re-derive via `tools/gen_polished_profile.py` before relying on either.
