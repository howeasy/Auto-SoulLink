# RR 4.1 missing names and form-family review

The policy choices described as pending below were subsequently resolved by the
user: cosmetic/battle forms group together and regional lineages stay separate.
The current inactive implementation and explicit legacy migrations are described
in [RR_CATALOG.md](RR_CATALOG.md). This document preserves the preceding evidence
review; its old cross-region preservation recommendations are superseded.

This is reviewed reference evidence, not an activated runtime catalog or a change
to the species/duplicate clause. The exact base ROM is SHA-256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
No cartridge, save, generated reference output, or runtime table was modified.

The 20 missing **species identities** can be named from independent ROM and local
calculator evidence. Two tea authenticity subtypes remain unspecified; Terapagos
has a proven calculator profile match, without proof of a corresponding temporary
transformation in RR. Those distinctions must survive catalog integration.

## Identification method and provenance

The [extent review](SPECIES_EXTENT.md) proves the 1376-record ROM domain. For each
tail record, this review compared all six exact ROM base stats and the type set
against the **current TypeScript source**, evaluated in memory using TypeScript's
CommonJS transpilation and the actual `util.ts` implementation. It did not use a
possibly stale `dist` build. The effective calculator generation is
`extend(true, {}, SS, SV_PATCH, PLA_PATCH, RR_PATCH)` in
`calc/calc/src/data/species.ts:10650`. Single types were deduplicated for matching;
type ordering was ignored for identity matching only. ROM type ordering remains
authoritative for extracted data.

Fourteen records have one matching calculator record. Four Ogerpon records each
match a normal-mask and a Tera calculator record on stats/types; their exact ROM
ability names distinguish them. Two tea records each match two authenticity
subtypes, which the evidence does not distinguish. This is stronger than expanding
a truncated ROM label, but does not certify every other calculator field.

| Input | SHA-256 |
|---|---|
| `calc/calc/src/data/species.ts` | `e0987392993605912fac3ac56dc361b4bf7e3f67387335a99c6276a28c5be779` |
| `calc/calc/src/util.ts` | `0a6da17881b6c9c22b1ccca9e2cbdd79c39063e607576dc64160d5e1ebc2f454` |
| `server/pokemon_data.py` | `155cec53cb4c25d6f1ca571804551b8c679d9b2d0beec990c5f57e4d0af610f0` |
| `generated/rr41_species.json` | `854cd267ad7a98205f10650d814374675b067dc705a684f6c2949b28eefff05c` |
| `generated/rr41_evolution_families.json` | `c4933ab90692f21db9e9e61345b62eb3ccd3f65c868f72769beb4440dbbf1250` |

## Proposed missing-name catalog

Stats below use ROM order **HP / Attack / Defense / Speed / Sp. Attack / Sp. Defense**.
The BaseStats record address is `0x097B98EC + 28 * id`; its name address is
`0x094042CC + 11 * id`. Every row's bytes are independently available in the
generated reference file. "Dex" is the ROM's custom dex group, not a standard
National Pokédex number and not a clause-family identifier.

| ID | Canonical species/form name supported by evidence | Six-stat fingerprint | Dex | Distinction to preserve |
|---:|---|---|---:|---|
| 1356 | Ursaluna-Bloodmoon | 113/70/120/52/140/65 | 902 | Unique calculator match after RR Sp. Attack override; normal Ursaluna also belongs to ROM dex group 902. |
| 1357 | Ogerpon | 80/120/84/110/60/96 | 1017 | Grass; ROM ability Defiant selects the normal Teal Mask profile, not Teal-Tera. |
| 1358 | Ogerpon-Wellspring | 80/120/84/110/60/96 | 1017 | Grass/Water; ROM ability Water Absorb selects Wellspring, not Wellspring-Tera. |
| 1359 | Ogerpon-Hearthflame | 80/120/84/110/60/96 | 1017 | Grass/Fire; ROM ability Mold Breaker selects Hearthflame, not Hearthflame-Tera. |
| 1360 | Ogerpon-Cornerstone | 80/120/84/110/60/96 | 1017 | Grass/Rock; ROM ability Sturdy selects Cornerstone, not Cornerstone-Tera. |
| 1361 | Poltchageist | 40/45/45/50/74/54 | 1012 | Base and Artisan calculator records match; authenticity is unspecified. |
| 1362 | Sinistcha | 71/60/106/70/121/80 | 1013 | Base and Masterpiece calculator records match; authenticity is unspecified. |
| 1363 | Dipplin | 80/80/110/40/95/80 | 1011 | Exact stats/types and Applin → Dipplin → Hydrapple ROM edges. |
| 1364 | Fezandipiti | 88/70/82/99/91/125 | 1016 | Unique stats/types match. |
| 1365 | Munkidori | 88/75/66/106/130/90 | 1015 | Unique stats/types match. |
| 1366 | Okidogi | 88/128/115/80/58/86 | 1014 | Unique stats/types match. |
| 1367 | Raging Bolt | 125/73/91/75/137/89 | 1021 | Unique stats/types match. |
| 1368 | Iron Crown | 90/72/100/98/122/108 | 1023 | Unique stats/types match. |
| 1369 | Archaludon | 90/105/130/85/125/65 | 1018 | Exact stats/types and incoming Duraludon ROM edge. |
| 1370 | Terapagos | 110/95/110/85/105/110 | 1024 | Calculator profile **Terapagos-Terastal**, including RR HP override. Do not invent a separate normal/Tera transformation or another RR species ID. |
| 1371 | Hydrapple | 106/80/110/44/120/80 | 1019 | Exact stats/types and incoming Dipplin ROM edge. |
| 1372 | Pecharunt | 88/88/160/88/88/88 | 1025 | Unique stats/types match. |
| 1373 | Iron Boulder | 90/120/80/124/68/108 | 1022 | Unique stats/types match. |
| 1374 | Gouging Fire | 105/115/121/91/65/93 | 1020 | Unique stats/types match. |
| 1375 | Chillet | 85/100/74/111/45/65 | 162 | Exact independent RR calculator entry; ROM dex group collides with Furret. Keep separate. |

Relevant calculator source anchors are Ogerpon at lines 9540–9599, Poltchageist
at 9668–9684, Terapagos profiles at 9900–9923, Bloodmoon at 9967–9972, RR
Terapagos HP override at 10295, Bloodmoon Sp. Attack override at 10309, and
Chillet at 10387–10391. The latter's calculator ability spelling is a typo;
the ROM's name is `Refrigerate`.

### Additional binary anchors

The exact ROM species-to-dex function at `0x08043298` contains:

```text
00 B5 00 04 01 0C 00 29 08 D0 03 48 01 39 49 00
09 18 08 88 03 E0 00 00 F0 18 82 09
```

The `subs r1,#1`, shift by one and halfword load establish a u16 table indexed by
`species - 1`; its literal at `0x080432B0` is `0x098218F0`. Readbacks show
regular Ursaluna 1302 and Bloodmoon 1356 both map to 902; Basculegion 1268/1306
maps to 903. Thus **902 must not be interpreted as the standard National Dex
902**. Separately, Furret 162 and Chillet 1375 both map to 162. Equal values
are supporting form evidence only when corroborated, never an automatic union.

Ogerpon BaseStats byte `+22` is respectively `8E`, `0B`, `98`, `05`. The actual
ROM ability-name getter at `0x09071C40` multiplies its input by 17 (`11 23` at
`0x09071C42`, multiply at `0x09071C46`) and uses the table literal
`0x090E32C0` at `0x09071C6C`, also exposed by ROM pointer `0x080001C0`.
The selected exact names are Defiant at `0x090E3C2E`, Water Absorb at
`0x090E337B`, Mold Breaker at `0x090E3CD8`, and Sturdy at `0x090E3315`.
These are native bytes, not assumptions from an upstream CFRU ability catalog.

Do not copy calculator abilities or genders wholesale. For example, RR's
Poltchageist/Sinistcha record has ability 97 (`Heatproof`), and Terapagos has 81
(`Multiscale`); these differ from the calculator's default ability labels. The
identity comparison above does not conceal those differences.

## Permanent evolution facts

The reviewed ROM domain has 592 permanent rows in 803 components, counting
singletons. The four tail edges are:

| Source → target | Method / parameter | Row address | Resulting reference component |
|---|---|---|---|
| 1132 Applin → 1363 Dipplin | 4 / 30 | `0x097F0FC0` | 1132, also containing Flapple/Appletun and Hydrapple |
| 1363 Dipplin → 1371 Hydrapple | 4 / 44 | `0x097F8330` | 1132 |
| 1176 Duraludon → 1369 Archaludon | 4 / 50 | `0x097F25B0` | 1176 |
| 1361 Poltchageist → 1362 Sinistcha | 7 / 98 | `0x097F8230` | 1361 |

These edges are not cosmetic/form aliases. All other tail IDs remain singleton
permanent components. In particular, there is no permanent edge from regular
Ursaluna to Bloodmoon, between Ogerpon masks, or between Furret and Chillet.

## Explicit existing clause-policy aliases

An AST read of `EVO_FAMILY` in `server/pokemon_data.py:360` finds **exactly nine**
entries joining different native permanent components. They are existing policy,
not native evolution facts. Preserve them explicitly while reviewing any new
family implementation; a plain replacement with the native graph loses them.

| Existing mapping | Category | Preservation note |
|---|---|---|
| 865 Palafin Hero → 863 Finizen | Battle form | Preserve the existing family. |
| 1154 Obstagoon → 288 Zigzagoon | Regional family alias | Native Galar component is distinct; this cross-region union is existing policy. |
| 1155 Perrserker → 52 Meowth | Regional family alias | Same distinction. |
| 1156 Cursola → 222 Corsola | Regional family alias | Same distinction. |
| 1159 Runerigus → 615 Yamask | Regional family alias | Same distinction. |
| 1291 Centiskorch-Sevii Mega → 1289 Sizzlipede-Sevii | Temporary transformation | Native method-254 reverse row targets 1290 Centiskorch-Sevii, in component 1289. |
| 1293 Wishiwashi-Sevii form → 1292 Wishiwashi-Sevii | Form alias | Preserve exact IDs despite unreliable legacy display suffixes. |
| 1313 Enamorus Therian → 1312 Enamorus | Form alias | Preserve the existing family. |
| 1355 Squawkabilly variant → 1338 Squawkabilly | Cosmetic/form alias | Preserve the existing family without inventing the variant's color. |

The existing lookup is **one hop**, `EVO_FAMILY.get(species_id, species_id)` at
`server/pokemon_data.py:1550`, not a union-find graph. Consequently, adding full
native components plus these aliases can change behavior for members that legacy
tables omitted, including Galar precursor records. Preserve the reviewed policy
intent, but review and enumerate those behavior changes; do not label a graph
replacement behavior-identical just because these nine entries were copied.

## Temporary transformations and unresolved policy extensions

The generated evolution file keeps all **143 method-254 rows** separate: 72 have a
nonzero parameter and 71 have a zero parameter. No method-253 row exists in this
ROM domain. The raw source/target/parameter/auxiliary/address records form a
complete explicit catalog of these table entries and must stay separate from
permanent edges. The auxiliary distribution is 129 rows with 0, eight with 1,
two with 2, and four with 3.

Examples include Venusaur 3 ↔ 869, Charizard 6 ↔ 870/871, Kyogre 404 ↔ 910,
Groudon 405 ↔ 909, Dialga 536 ↔ 919, and Necrozma 1079/1080 ↔ 1081. The
vendored CFRU `include/pokemon.h:627` calls 254 `EVO_MEGA`; `src/mega.c:69–86`
interprets variants and ignores zero-parameter reversion information when testing
forward transformation, while lines 265–274 inspect zero-parameter reversions.
This source supports interpretation; the exact RR table is the authority for
which edges actually exist. It does not prove every RR engine trigger.

Legacy catalog labels `(Giga)` are not a reason to reinterpret these rows as
method 253 or to union them permanently. The RR calculator includes several such
forms as Mega profiles. Preserve raw method/variant evidence until the corresponding
RR engine paths and clause policy have been reviewed.

| Candidate extension | Evidence | Decision for this review |
|---|---|---|
| Bloodmoon 1356 with normal Ursaluna family 216 | Unique calculator form, calculator `baseSpecies`, shared native dex group with 1302; no permanent edge | Identity established; clause alias remains an explicit policy extension. |
| Ogerpon 1357–1360 grouped under 1357 | Exact stats/types/ability profiles, calculator baseSpecies, shared native dex group 1017; no permanent edges | Four mask identities established; clause alias remains an explicit policy extension. |
| Other method-254 targets joined to source permanent families | All 143 raw edges are retained separately | Requires a reviewed temporary-form policy and handling for multiple reverse sources. |
| Other regional/cosmetic forms absent from the nine legacy aliases | Native components and current one-hop map differ | Do not automatically infer a cross-region policy from names, sprite IDs, or equal dex numbers. |
| Chillet 1375 joined to Furret/Sentret | Only a reused ROM dex number; distinct exact calculator profile and no evolution edge | Reject this inferred union. |

This review resolves the 20 species-name gaps and explicitly preserves the nine
existing non-permanent policy mappings. It does **not** claim a complete reviewed
taxonomy of every cosmetic/regional form, actual acquisition availability, exact
withdrawal stats/PP, or release readiness. Integrate the proven names separately
from policy changes; leave tea authenticity and any unproven transformation
semantics explicit rather than manufacturing extra species records.
