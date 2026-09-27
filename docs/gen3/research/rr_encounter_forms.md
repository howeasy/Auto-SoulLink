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

## Source chain and scope

The generator reads the hash-pinned community C snapshot from
`data/gen3_rr_sources.lock.json` through `fetch_rr_sources.cached_source`.
Wild source SHA256: `24ebfcda8be7e0fce44cd47165d0acb70154d2e05c825a9480112351c6429ea9`.
Species-header SHA256: `775bedd9b0afd37b5e62f9d18558302992aa4149dd1150c96033ee04dadf71cd`.
Both were fetched into this worktree's ignored `data/.rr_src_cache/` and verified.

`gen_rr_encounters._resolve_species_id` formerly tried the display name and then
`display.split()[0]`. `Zigzagoon G` therefore became base Zigzagoon. The mapping
repair uses the same complete-constant naming rules as `gen_rr_species.to_display`
and fails on an unknown form. It preserves encounter display names and other keys.

The broader census also finds non-form source/parser/projection drift. That is
tracked separately from the form correction; final scope and verification follow
in the completion receipt. The raw ROM uses additional species IDs
1356,1361,1362,1371 absent from the current `rr_species.json` (maximum1355).
The primary header at map1:4 has no coarse `area_map.json` key; it remains in the
raw census instead of being assigned a guessed vanilla area.

Reproduce the raw census:

```powershell
python tools/rr_rom_encounters.py --rom 'C:/slink-wt/g3-int/patch/build/rr_clean.gba' --output .cache/rr-wild-census.json
$env:SLINK_RR_ROM='C:/slink-wt/g3-int/patch/build/rr_clean.gba'
python -m pytest tests/unit/test_rr_rom_encounters.py -q -p no:randomly
```

Initial reader controls: 5 passed, covering real RR heads/Route1, changed
selector bytes, a synthetic moved wild-species slot array, out-of-range
pointers and a bounded missing sentinel. Form-generator red controls reproduced
9 failures before the mapping repair; all 13 mapping controls pass afterward.

## Form correction and complete primary-table comparison

Regeneration changes only **155 species_id fields**, covering **66 form names
in 31 areas**. All 2,103 rows, 53 areas, display names, rates and levels retain
their previous shape/order. Unknown non-NONE constants now fail by name instead
of silently falling back to a base species. Regional variants (Alola/Galar/
Hisui/Paldea/Sevii), size forms and other suffixes use the same full-name mapping
as the RR species generator.

`rr_encounter_forms_diff.json` records every changed row and complete before/
after primary-table differences. Comparison includes species, levels, row counts
and order; it does not claim a ROM audit of encounter probability thresholds.
Area/method differences fall from 80 to 38. Of the remaining 38, 35 differ in
content/counts and three only in order. These are **known remaining data-quality
gaps**, not passing qualifications or silently repaired game facts. Examples:

- Route22 Good Rod: community Carvanha326 vs ROM Arrokuda1144.
- Route10's relevant Day/Night populations and Route24/25 assignments differ.
- Commented-out definitions leak 15 zero-level rows into Cape Brink Super Rod.
- Coarse-area aggregation omits/adds populations in Tower/Mansion/Mt Ember/
  Rock Tunnel/Safari Center, and includes a 12-row NONE placeholder in Tower Day.
- Four nonzero wild IDs exceed the shipped species-name catalog (listed above).

The direct slot-order tests cover every method of Route1, Route2, Mt Moon and
Berry Forest, including both Route1 Day/Night. The wider discrepancies remain
fully listed in the audit artifact; these sample passes do not certify the
entire shipped catalog. The broader ROM-authoritative catalog/source change was
raised to the coordinator separately from this bounded form-mapping repair.

## Consumer audit (integration d9a928d7)

- `server/adapters/gen3_frlge.py:288-292,620-632` loads/returns the RR JSON as-is.
  `server/server.py:1392-1399,2912` publishes it in the per-player status payload.
  Thus the API did expose incorrect base IDs for regional rows.
- `server/templates/_board.html:201-207` renders the unique **name** strings,
  not species IDs or species sprites. Those names already said `Zigzagoon G`
  etc.; this patch preserves them. The current text-only Wild Here widget is
  not evidence that the numeric IDs were correct.
- `tools/gen3_clause_rows.py:225-233,260,502,522,632` treats the JSON IDs as
  actual wild species for capture/clause/family oracles. Its former family seed
  comment/target at 579-581 asserted base Zigzagoon288 exists in both times.
  Corrected Night1222 disproves that assumption. Emerald-2 owns its fixture/
  driver/oracle correction and consumes the independent RR reader.
- Production dupes checks at `server/state.py:2788-2875,2915-2976` use the live
  `species_id` and `adapter.evo_family`, not this encounter JSON. Therefore the
  JSON repair alone cannot fix production family membership. At this base,
  `Gen3Adapter.evo_family(1222/1223/1154)` returns `1222/1223/288`, while the
  actual RR evolution graph places them together. That separate family-map
  defect is being corrected by Emerald-2; generic/NatDex behavior is outside
  this card. No server/UI consumer was changed here.

The existing `test_rr_family_target_exists_in_both_own_time_tables` now fails
on Night for the old single-base-family fixture. It is left intact rather than
weakened to make a misleading green gate; the C3 composition must resolve it.
