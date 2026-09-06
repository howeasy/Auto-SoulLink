# Bounded RR precursor acquisition-source audit

**No campaign acquisition example or final lineage assignment is established.**
This slice establishes a conditional wild-source exclusion and preserves a real
legacy-table counterexample. IDs1038/1214/1224 remain catalog unknowns.

All binary evidence uses RR4.1 base ROM SHA-256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
The optional native test is `tests/rr/native/test_precursor_sources.py`.
It performs structural table walks and121 actual Unicorn subroutine calls,
without routine stubs, callee-result replacement, cartridge-file writes or a
game emulator. It does not simulate walking, an encounter, capture or gift.

## Structural wild domains

The parser follows20-byte headers to8-byte method records, then4-byte
`{minimum level, maximum level, species}` slots. Land/water/rock/fishing counts
are12/5/5/10. These agree with the available CFRU structures and actual RR index
routines at`0808274C`, `08082808` and`0808285C`; those routines select indices
0..11,0..4 and rod-specific subsets of0..9. Header traversal stops at its actual
map-group255 sentinel. Pointer bounds, alignment, complete header hashes and
record counts are checked. Zero species slots and raw level bytes are retained;
the parser does not discard inconvenient records or resolve names by suffix.

| Domain | Header address | Headers | Referenced slots | Unresolved-ID occurrences |
|---|---|---:|---:|---|
| Legacy fallback | `0872C984` | 142 | 2338 | Five slots containing1038 |
| Current night/evening | `09166428` | 83 | 1403 | None |
| Current day | `09166AB8` | 83 | 1398 | None |

These are5139 referenced slots, not a claim of5139 distinct physical records.
The legacy pointer comes from`08082990`; the two current pointers occur in the
actual RR loader's literal pool at`090C3600` and`090C3608`. The tests pin every
header domain's full hash. Normal-species controls include legacy Koffing109 and
current Cubone104 entries.

The existing `tools/gen_rr_encounters.py` is useful source context, but its output
is not this proof: it reads an external source file, skips unmapped areas and can
fall back from a form's display name to its first word. This audit instead reads
all slots in the selected binary domains directly.

## The legacy Cubone_A lead and actual selection

The five legacy1038 slots are structurally reachable from these table headers:

| Map | Header | Land slot | Slot address | Raw level range |
|---|---|---:|---|---|
| 1/90 | `0872CC2C` | 5 | `083C7E08` | 44–45 |
| 1/91 | `0872CC40` | 5 | `083C7E40` | 44–45 |
| 1/92 | `0872CC54` | 5 | `083C7E78` | 45–45 |
| 1/93 | `0872CC68` | 3 | `083C7EA8` | 45–46 |
| 1/94 | `0872CC7C` | 5 | `083C7EE8` | 47–47 |

Available CFRU map constants identify these as Pokémon Tower3F–7F. Their actual
RR map headers share section140. A table entry alone is not an encountered mon.

The actual `StandardWildEncounter` detour at`08082CBC` selects`090C385E`; its
land branch calls `LoadProperMonsData` at`090C38A0`, selecting entry`090C3550`.
That loader checks the override pointer first, then current clock-based tables,
then the legacy fallback. The188-byte loader region has SHA-256
`33b84bea16a0caea497fb2acbe6ec04d5b8411d05d3c141790258c15705fa062`.

With override`0203C758` equal to zero, actual CPU calls for all five maps and
all24 hours return their non-null current land records. Hour4..16 selects the
day table; hour17..23 and0..3 selects the night/evening table. Both current
tables use **normal Cubone104 in slot5**, and none of their twelve Tower slots
contains an unresolved ID. The observed entry set excludes the legacy-loader
entry`090C262C` for all120 calls.

Each call uses a synthetic SaveBlock1 pointer at`03005008`, map bytes at its
`+4/+5`, and the actual clock-hour byte`03005EA6`. Non-ROM/non-stack reads are
limited to those inputs and the override pointer. Exactly five stack words are
written:16 bytes from the loader prologue and four from the native Thumb switch
helper at`090003C4`. No game state outside that20-byte stack range changes.

This proves that the legacy1038 entries are shadowed in this specific normal
loader context. It does not prove that no script or different path can use them.

## The override boundary is real

Actual routine`090BA950` copies `gLoadPointer` at`03000F14` to override slot
`0203C758`; routine`090BA964` clears it. Their function pointers occur at
`0815FEC8`/`0815FECC`, matching the available CFRU `routinepointers` entries for
`sp05A_WildDataSwitch` and`sp05B_WildDataSwitchCanceller`. The setter bytes are
`024b1a68024b1a607047c046140f000358c70302`.

A separate **synthetic countercheck** sets the override to legacy header
`0872CC2C`, then executes the same actual loader. It returns that legacy land
record, including1038 at slot5, and bypasses both clock predicates. The loader
therefore does not universally reject those legacy entries. This is a test-input
override, not evidence that a reachable campaign script supplies that pointer.

The test preserves this distinction: the121st call demonstrates why the
conditional exclusion cannot be relabeled global unobtainability.

## Other acquisition paths remain open

The generic script-gift entry`080A011C` really detours to`0907767C`, and the
generic egg constructor entry`08046150` detours to`0908789C`. Their literals at
`090777F8`/`09087A0C` select `CreateMon0803DA54`. Supplied species arguments
therefore reach construction; neither entry identifies the
set of species supplied by campaign callers. Earlier
[`PRECURSOR_CREATION.md`](PRECURSOR_CREATION.md) proves that supplying the three
IDs to the actual box constructor preserves them.

This slice did not establish an exhaustive RR gift, special-egg or NPC-trade
candidate table, nor the complete input domain of DexNav, scripted wild spawns,
roamers, raids or override-writing event scripts. Their absence from the two
current wild tables is not an exclusion from those other sources. No lineage or
reserved/unused classification is assigned from these results.

The next bounded step is to decode event-script roots/call chains reaching the
registered override setter and generic give-mon/egg functions, including how
they populate`gLoadPointer` and species variables. Bind any NPC-trade candidate
table through its actual producer/consumer before enumerating it. Raw species-ID
or opcode byte searches alone cannot establish reachability or completeness.

## Reproduction

```powershell
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
python -m pytest -p no:faulthandler tests/rr/native/test_precursor_sources.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/patch/build/rr_clean.gba' -q -o junit_family=xunit1 --junitxml=patch/build/precursor-sources-review-next.xml
python -m ruff check tests/rr/native/test_precursor_sources.py
```

Result: **10 passed**, Ruff clean. Current JUnit evidence is retained at
`patch/build/precursor-sources-review02.xml`, including every map/hour result.
The earlier`review01.xml` retains a failed16-byte stack assumption in the
countercheck; the final test pins the switch helper and exact20-byte stores.
Choose a new result filename for each attempt. Catalog generation remains blocked.
