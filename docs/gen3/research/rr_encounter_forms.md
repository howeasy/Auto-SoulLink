# RR encounter forms: cartridge facts and generator audit

RR-ENC-FORMS starts at integration `d9a928d79a99aef33ac923cfbf589cda2715762d`,
branch `codex/gen3-rr-enc-forms`, worktree `C:/slink-wt/g3-rr-enc-forms`.
No emulator is used. These are ROM/SOURCE and MODEL facts, not a new live receipt.

## Cartridge reader

The verified RR clean ROM is SHA1 `964f951a0fdaf209e4ea1344883ef0d557bb3a80`,
32 MiB. The admitted companion SHA1 `7a3867499d66eb3621e0e7dde43bd033fc679f01`
has byte-identical decoded wild tables and selector heads. Inputs were read from
`C:/slink-wt/g3-int/patch/build/{rr_clean,slink_RR}.gba`; no ROM is committed.

`tools/rr_rom_encounters.py` follows RR's actual pointer loads and both info/slot
pointer levels. `load_rom(path)` checks those pins; `decode_encounters(rom)`
returns the complete raw tables, including each header/slot address and four
slot bytes. Bounds and missing sentinels raise named errors. It never reads
vanilla encounter data.

The [pinned CFRU header](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/include/wild_encounter.h)
is the layout reference: 20-byte headers, 8-byte info records, and four-byte
min/max/species slots; land/water/rock/fishing counts are 12/5/5/10. Its
`08082990` pointer identifies only the **fallback**, not RR's active Day override.

| Table | RR selector instruction | Literal/pointer path | Head | Headers | Raw slots |
| --- | --- | --- | --- | ---: | ---: |
| Night override | `090C356E: 244a` | `090C3600 -> 09166428` | `09166428` | 83 | 1403 |
| Day override | `090C3590: 1d4a` | `090C3608 -> 09166AB8` | `09166AB8` | 83 | 1398 |
| Fallback | `090C2668: 1c4c` | `090C26DC -> 08082990 -> 0872C984` | `0872C984` | 142 | 2338 |

The 142 fallback headers represent 134 map keys, retaining Altering Cave's
variants. `effective_maps(decoded, "Day"|"Night")[(group,num)]` selects the
primary map/habitat when present and otherwise its fallback. That projection
assumes `gWildDataSwitch` is NULL and Altering Cave variant zero; the raw census
retains every variant. Script overrides, swarms and other runtime encounter
modifiers are not inferred from static tables.

The pointers above are reached by RR encounter code, not just matching data:

- RR bytes at `080833B0` are `00490847a5390c09`, a detour to `090C39A4`.
  That wrapper calls `090C385E` at `090C39BC`; the land branch passes kind 0
  to the table selector `090C3550` at `090C38A0`.
- RR bytes at `08082FB0` are `00490847613a0c09`, a detour to `090C3A60`.
  It passes kind 2 to `090C3550` at `090C3A66`; `090C3A90` loads the selected
  slot's u16 species at +2 and passes it to the wild-mon creator at `090C3A94`.
- `090C3550` handles the override pointer, map search and per-habitat fallback
  calls to `090C262C`. The old `08082934` body and its `08082990` pointer remain
  readable, but their Route 1 roster has Panpour and no Yungoos; it is insufficient
  as an oracle for the current override roster.
- The selector calls predicates at `0908CC04` and `0908CFDC`, both reading the
  clock hour at `03005EA0+6`. Their comparisons select Night for hours 0–3 and
  17–23, Day for 4–16. This is static code evidence; this card does not change
  the clock or claim a live clock observation.

## Route 1 (map 3:19)

Day info `09169998`, slots `091699A0`:
`452,288,19,672,52,951,16,16,1324,1324,566,566`.

Night info `09169960`, slots `09169968`:
`286,1222,1020,612,1208,163,16,16,298,298,566,566`.

Both arrays' complete 48 bytes match the pinned community constants/levels
after resolving the actual RR form IDs. The Night slots at indices 1, 2 and 4
are Galarian Zigzagoon 1222, Alolan Rattata 1020 and Galarian Meowth 1208.
The former JSON instead used 288, 19 and 52. Day's Zigzagoon remains 288.
This supports Emerald-2's separate base Linoone289/Galarian Linoone1223 paired
family control; its production family-map correction is a separate owned change.

## ROM-authoritative generation

The initial bounded repair corrected 155 IDs across 66 form names/31 areas, but
left unrelated community-data drift. The coordinator explicitly expanded this
card to replace the entire encounter catalog with ROM-authoritative generation.
The final generator no longer uses community slot populations, levels or rates.

`gen_rr_encounters.py` reads every override/fallback header and every statically
selectable fallback variant. It follows RR's map/habitat precedence, omits
SPECIES_NONE slots, and deduplicates shared slot arrays within an area. The
probabilities come from RR's own chooser CMP instructions at
`0808274C` (land), `08082808` (water/rock) and `0808285C` (fishing). They are
conditional slot rates for their source pool; combining floors does not invent
one normalized probability distribution for the whole dungeon.

The result has **81 client location keys and 3,745 slots**, replacing 53/2,103.
Treasure Beach has distinct Day/Night rod tables, so its methods retain those
period labels. Other identical non-land populations share the ordinary method
label. Land retains Day/Night separately. All 134 map keys are covered through
the existing client coarse-area routing or its existing fine-location fallback;
no vanilla wild data or guessed area names enter generation. The three fine
fallbacks are map1:4 `ss_anne_exterior`, map3:57 `five_island_memorial_pillar`,
and map3:63 `seven_island_sevault_canyon_entrance`.

`data/gen3_rr_encounters_rom.json` records each output row's source map, period,
variant, selected table, header/info/slot addresses and four slot bytes. It also
records chooser rates, input hashes and all excluded NONE addresses. Gameplay
fields come from ROM; names come from the species catalog or pinned display-label
metadata. Changing labels cannot change species IDs, levels or probabilities.

`rr_encounter_forms_diff.json` contains before/after details for **every area**.
Against the complete selection model the old file differs in **66 areas and
197 methods**; the regenerated file differs in **zero areas/methods**. This
includes the initial forms bug, stale populations, Route10/24/25 swaps, missing
fallback areas, and commented/placeholder rows that the community parser leaked.
Example: Route22 Good Rod's first slot is ROM species1144 **Clobbopus**, not the
old Carvanha326. (An earlier message called1144 Arrokuda; that name was wrong.)

## Species-name extension and provenance

RR's own header pointers give name table `094042CC` (11-byte rows, pointer at
`08000144`) and base stats `097B98EC` (28-byte rows, pointer at `080001BC`).
The ROM contains 20 additional named/stat-bearing records, IDs1356–1375, after
the old catalog maximum1355. Record1376 has an unterminated name and six zero
stats, marking the end of this verified contiguous extension; this is a pinned
RR4.1 boundary, not an inferred limit for every CFRU build.

Every added record is independently read from those ROM tables. Existing display
labels remain stable. The ROM's short names (e.g.1361 `Polchageis`) do not always
carry full spelling or form labels. For those presentation details, the pinned
Jwow display key supplies `Poltchageist`, `Ursaluna-Bloodmoon`, Ogerpon masks, etc.
Its numeric ID and six stats must match the ROM record before a label is accepted.
No JavaScript executes: the data-only object is parsed through a literal AST.

`data/gen3_rr_species_rom.json` stores raw name/base-stat bytes, addresses,
ROM names, display-label source and the extension boundary. All nonzero wild IDs
resolve in the final **1,349-entry** species catalog. Missing/ambiguous tail data
is a named generator failure, not an unknown species on the panel.

The pinned community sources are display metadata only:

- wild C SHA256 `24ebfcda8be7e0fce44cd47165d0acb70154d2e05c825a9480112351c6429ea9`;
- species header SHA256 `775bedd9b0afd37b5e62f9d18558302992aa4149dd1150c96033ee04dadf71cd`;
- Jwow data.js SHA256 `04c9dc94b6a7e3d33f5dcb5e804487466e7a249f4d340cf19853d70f37596df9`.

Their URLs/commits remain in `data/gen3_rr_sources.lock.json`. They were fetched
through its verifying cache. ROMs are never committed. Generated catalogs use
UTF-8/LF so the intentional catalog-byte hash in the evolution artifact survives
Windows checkout/regeneration.

## Consumer audit and C3 composition

- `server/adapters/gen3_frlge.py:288-292,620-632` loads/returns the RR JSON as-is;
  `server/server.py:1392-1399,2912` publishes it in per-player status. The API did
  expose base IDs beside regional labels.
- `server/templates/_board.html:201-207` renders unique **name** strings, not
  species IDs or sprites. Names such as `Zigzagoon G` already looked regional;
  that text was not evidence that their numeric IDs were correct. The final
  catalog preserves those existing display abbreviations where available.
- `tools/gen3_clause_rows.py` consumed JSON IDs for wild capture/clause/family
  oracles. Its old fixture assumed base Zigzagoon288 exists in both times.
  C3 now consumes the ROM reader and uses the disclosed base/Galar evolved pair.
- Production dupes use the live species ID and `adapter.evo_family`, not encounter
  JSON. The initial base incorrectly separated1222/1223 and attached1154 to288.
  Emerald-2's completed C3 `97205f26632dd9abb179af5666f0894e5d36e728` was merged as
  `a5294c0`; it supplies the ROM-derived RR family generator and corrected test.
  Its generated artifact was regenerated under the transferred lease against
  this extended name catalog: **1,349 species, 735 edges**.
- The coordinator expanded this card to fix the tail's missing production types.
  `gen_rr_types.py` now reads ROM type bytes for every nonempty catalog record,
  producing 1,348 type entries. An explicit bijection maps raw0–17 identically
  and rawFairy23 to canonicalFairy18; all raw IDs present are round-trip tested.
  `data/gen3_rr_types_rom.json` records every source address/raw pair/conversion.
  Twenty new rows are added; the ROM also corrects Raichu26's secondary Normal
  type and Masquerain312's type order. The empty reserved record920 is not given
  invented types. Generic/non-RR type behavior is unchanged.

No server or Lua consumer source was changed by this catalog card beyond the
explicit C3 merge. The catalog describes statically selectable tables, including
conditional fallback variants. It does not observe a save's current override
pointer, swarm state or encounter-modifying ability; those limits remain explicit.

## Reproduction and tests

```powershell
$env:SLINK_RR_ROM='C:/slink-wt/g3-int/patch/build/rr_clean.gba'
python tools/gen_rr_species.py --rom $env:SLINK_RR_ROM
python tools/gen_rr_encounters.py --rom $env:SLINK_RR_ROM
python tools/gen_rr_types.py --rom $env:SLINK_RR_ROM
python tools/gen_rr_evolutions.py --rom $env:SLINK_RR_ROM
python tools/rr_rom_encounters.py --rom $env:SLINK_RR_ROM --catalog data/games/gen3_frlge/rr_encounters.json --output .cache/rr-wild-census.json --diff-output .cache/rr-catalog-check.json
python -m pytest tests/unit/test_rr_encounter_forms.py tests/unit/test_rr_rom_species.py tests/unit/test_rr_rom_encounters.py -q -p no:randomly
```

The tests first reproduced the collapsed form IDs and four unnamed live wild IDs.
They now read every generated slot back from its ROM pointer, verify probability
intervals, header/info/slot ownership and complete source coverage, and exercise
sample areas including both Route1 periods. Bounds, missing sentinel, changed
selector, slot order, unknown form, wrong display metadata and executable display
input all have negative controls. The C3 composition resolves the earlier failing
single-family Night fixture test. The final full-gate receipt follows below.
