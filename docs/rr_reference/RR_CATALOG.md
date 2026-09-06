# Inactive RR 4.1 catalog and regional family partition

The generator and strict reader are implemented, but **final catalog generation
is deliberately blocked** by three unresolved record identities. No existing
adapter, run, session, rule lookup, or history selects the new catalog.

The selected policy is versioned as
`rr41-cosmetic-shared-regional-separate-v1`: cosmetic and battle forms share their
base lineage; regional lineages stay separate. This supersedes the earlier
suggestion to preserve four legacy cross-region unions.

## Files and deterministic generation

- `tools/rr/catalog.py` reads the exact pinned base ROM through the existing
  reference extractor, the baseline literal dictionaries, and the explicit
  `data/games/gen3_frlge/rr_catalog_review.json` policy review. No runtime module
  is imported, no network fetch occurs during generation, and no emulator starts.
- `rr_catalog_review.json` contains exact ID lists for regions and cosmetic forms,
  the reviewed 20 missing names, name corrections, twelve physical-edge cuts,
  independent dex collision exceptions, and unresolved records. Region is never
  inferred from a formatted name or a species' generation of origin.
- `data/games/gen3_frlge/rr_catalog_review_output.json` is deterministic **blocked
  review evidence**, with every raw physical edge and proposed legacy change. It
  is not loadable by the strict reader.
- `server/rr_catalog.py` reads only an explicitly supplied final payload with an
  expected SHA-256 and policy ID. There is no default path, global catalog,
  fallback to legacy tables, auto-selection, or write/migration behavior.

```powershell
python -m tools.rr.catalog --repo . --rom 'E:/Google Drive/SLink/patch/build/rr_clean.gba' --output data/games/gen3_frlge/rr_catalog_review_output.json --review-only

# Expected exit2 until all taxonomy unknowns are resolved. Refusal writes nothing.
python -m tools.rr.catalog --repo . --rom 'E:/Google Drive/SLink/patch/build/rr_clean.gba' --output data/games/gen3_frlge/rr_catalog.json

python -m pytest tests/rr/reference/test_catalog.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/patch/build/rr_clean.gba' -q
python -m ruff check tools/rr/catalog.py server/rr_catalog.py tests/rr/reference/test_catalog.py
```

The content identity covers the complete canonical JSON body, excluding its own
identity field. Source-file hashes and the policy-review hash are preserved.
Generation has no timestamp, host path or nondeterministic ordering. A wrong ROM,
changed native transformation row, undeclared regional cut, conflicting region
assignment or missing evidence is an error, not a silent omission.

## ROM facts versus family policy

The 1376-record domain contains 1348 nonzero species records, None 0, Egg 412, and
26 zero placeholders: IDs 252–276 and **920**, the latter carrying the legacy
name Palkia Primal despite an all-zero BaseStats record. The reader refuses
queries for every sentinel/placeholder. Nonzero records establish metadata, not
proof of player acquisition availability.

Gender ratios and ordered types come from exact BaseStats bytes. Fairy raw type
23 is translated to canonical type18. Gender uses the actual special ratios
0/254/255 and otherwise `(PID & 255) < ratio`; unknown IDs do not receive a
default gender, type or family.

All **592 permanent evolution rows** and **143 method254 transformation rows**
remain in the artifact with their parameters, auxiliary fields, slots and ROM
addresses. The native transformation fact set is explicitly hash-pinned to the
reviewed set; it is not an open-ended rule accepting whatever a future ROM table
contains. The reader independently checks both physical fact-set hashes.

Family construction uses separate graphs for form equivalence and physical
evolution. Physical edges crossing an explicit regional boundary are retained
with `family_disposition="regional_cut"`; other permanent edges join families.
Same-region cosmetic/native battle forms are grouped. A custom ROM dex number is
only a coverage-audit signal: unexplained equal-number pairs become unknowns.
No dex number causes a union. Dex0's heterogeneous records are not a form group.

Lineage roots are selected from the directed physical graph after form
equivalence is applied. Internal graph keys may use minimum IDs, but exported
family IDs do not. Examples:

| Member | Family root | Why |
|---|---:|---|
| Pikachu25 / Raichu26 / costume Pikachu | 172 Pichu | Actual predecessor, preserving the familiar root. |
| Hitmonlee106 / Hitmonchan107 / Hitmontop237 | 236 Tyrogue | Actual predecessor, not minimum106. |
| Marill183 / Azumarill184 | 350 Azurill | Actual predecessor, not minimum183. |
| Lokix-Sevii1186 | 1200 Nymble-Sevii | Actual predecessor, not minimum1186. |
| Exeggutor-Alola1037 | 1036 Exeggcute_A | The ROM has a real regional precursor edge at `0x097EDFB0`, method7/parameter98. |
| Ursaluna-Bloodmoon1356 | 216 Teddiursa | Reviewed Ursaluna form alias into the normal lineage. |
| Ogerpon masks1358–1360 | 1357 Ogerpon | Reviewed mask-form aliases. |
| Chillet1375 | 1375 Chillet | Remains separate from Furret/Sentret despite reused dex162. |

An ambiguous root creates an unresolved review record unless a specific,
evidence-backed root override is supplied. This candidate requires no root
overrides for its resolved families.

## Shared precursors and regional separation

These twelve exact physical edges are cut **only for family partition**:

| Physical source → regional target | Family effect |
|---|---|
| 25 Pikachu → 1022 Raichu-Alola | Pichu lineage remains separate from Alolan Raichu. |
| 102 Exeggcute → 1037 Exeggutor-Alola | Normal Exeggcute remains separate from the explicit1036 regional precursor lineage. |
| 104 Cubone → 1039 Marowak-Alola | Normal Cubone remains separate from Alolan Marowak. |
| 109 Koffing → 1215 Weezing-Galar | Normal Koffing remains separate from Galar Weezing. |
| 156 Quilava → 1299 Typhlosion-Hisui | Regional terminal form gets its separate lineage. |
| 492 Mime Jr. → 1216 Mr. Mime-Galar | Galar Mr. Mime/Mr. Rime remain separate from normal Mime Jr./Mr. Mime. |
| 555 Dewott → 1300 Samurott-Hisui | Regional terminal form stays separate. |
| 601 Petilil → 1303 Lilligant-Hisui | Regional terminal form stays separate. |
| 680 Rufflet → 1269 Braviary-Hisui | Regional terminal form stays separate. |
| 812 Goomy → 1297 Sliggoo-Hisui | Hisui Sliggoo/Goodra remain separate from ordinary Goomy/Sliggoo/Goodra. |
| 820 Bergmite → 1309 Avalugg-Hisui | Regional terminal form stays separate. |
| 940 Dartrix → 1301 Decidueye-Hisui | Regional terminal form stays separate. |

The exact physical edges remain available for an acquisition/evolution detector.
When a real mon crosses one, its PID/OT identity, link and death history must not
be discarded. Its *current eligibility family* changes under the selected policy;
the coordinator must record/recheck that semantic transition. A static union-find
over every permanent edge cannot implement this policy.

## Legacy behavior changes and name corrections

The review output lists every changed species with before/after name, family,
gender and RR type-record values. Missing old type records are reported as null;
this comparison does not pretend to execute all legacy display fallback paths.
Old gender comparison uses the existing default127, not a missing-dictionary
value. Unknown new families are reported as null, not an approved migration.

At this candidate there are 422 changed species: 291 family fields (including
three unresolved outcomes), 294 gender ratios, 22 RR type records and 35 names.
These fields overlap. Counts are audit results, not required constants for
future reviewed changes.

Four explicit policy migrations replace legacy cross-region unions:

| Species | Old family | Proposed regional family |
|---|---:|---:|
| Obstagoon1154 | 288 Zigzagoon | 1222 Zigzagoon-Galar |
| Perrserker1155 | 52 Meowth | 1208 Meowth-Galar |
| Cursola1156 | 222 Corsola | 1221 Corsola-Galar |
| Runerigus1159 | 615 Yamask | 1228 Yamask-Galar |

Other changes repair omitted evolution/form members and include new tail
records. Baseline display-name suffix expansion also incorrectly labels Unown
letters as regions/genders, Oricorio P/S as Paldea/Sevii, Wishiwashi School as
Sevii, and Original Color Magearna as Paldea. Explicit ID corrections prevent
those strings from influencing family policy. Costume Pikachu's Alola cap does
not make that Pokémon a regional lineage.

## Remaining taxonomy blockers

| ID | Current source constant | Missing evidence |
|---:|---|---|
| 1038 | `CUBONE_A` | Nonzero record and shared dex104, but no native outgoing regional precursor edge. Its role as reserved/unused metadata, ordinary alias, or distinct regional precursor is not proved. |
| 1214 | `KOFFING_G` | Same ambiguity for its nonzero record/shared dex109. The physical Galar evolution uses normal Koffing109. |
| 1224 | `MIME_JR_G` | Same ambiguity for shared dex439. The physical Galar evolution uses normal Mime Jr.492. |

Their suffixes alone do not prove a lineage assignment. Available CFRU source
references these constants in learnset/EXP tables; that is insufficient to settle
their actual RR roles. Exeggcute_A1036 initially looked similar but is resolved
by its actual1036→1037 ROM edge; the generator's exhaustive edge pass exposed it.

Final generation fails while these records remain unresolved. Merely deleting
the unknown labels does not bypass this: the independent shared-dex coverage
audit still finds their missing form/independence dispositions. Resolve them
from RR binary/source evidence, update the explicit review, regenerate, and then
review all changed families before final generation. Do not invent singleton
families solely to make the readiness flag pass.

## Reader validation and eventual activation

The reader rejects blocked/review-only artifacts, missing/extra top-level fields,
duplicate JSON keys, NaN/Infinity, wrong selected hash/policy/domain, booleans in
integer fields, incomplete species/family coverage, invalid type translations,
unresolved roots, changed native evolution facts and aliases crossing regional
families. Public species records are immutable. It has no live-run integration.

The positive reader tests use an **in-memory schema fixture** that deliberately
fills the three unresolved fields; those assignments are invented solely to
exercise reader validation and are never generated or written as a final
catalog. Separate tests prove the actual generator and reader refuse the real
blocked artifact. Test success is not taxonomy approval.

After evidence resolves the blockers, activation still requires explicit catalog
revision agreement by both players, stable save/mon identity binding, and a
versioned policy migration. Existing captures, links, memorial obligations and
death history keep their recorded semantics and identifiers. Re-evaluate current
eligibility under the new version without retroactively relabeling those facts.
No such migration or selection is implemented by this slice.
