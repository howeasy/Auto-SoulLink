# RR 4.1 unresolved regional precursor records: engine probes

**Keep final catalog generation blocked.** This follow-up establishes actual
ancestry and evolution behavior for IDs1038,1214,1224, but does not establish an
acquisition/form-resolution path that assigns their canonical lineage. No
catalog mapping, reader rule, generated catalog or runtime code was changed.

The exact base ROM is SHA-256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
`tests/rr/native/test_regional_precursor_cpu.py` executes the actual ROM routines
with Unicorn2.1.4 against synthetic RAM, without routine stubs, altered callee
results, code replacement, cartridge writes, a game emulator or PPU/frame
simulation. These are subroutine probes, not proofs of obtainable campaign mons.

## Exact native ancestry behavior

The old `GetEggSpecies` entry at `0x08045970` is detoured by bytes
`00 49 08 47 B9 1A 3F 09` to `0x093F1AB8`. The entire64-byte function/literal
region has SHA-256
`8b3a2daa26185eebdf52fdd0d1f147bf4898f691d1f73fb6bf60bb8da985569f`.

Its binary differs from the unpatched pret algorithm:

- It searches16 evolution slots per candidate species, stride128 bytes.
- It skips rows with method254 (`cmp r6,#0xFE` at `0x093F1AD6`).
- It chooses the first numeric predecessor whose row's target equals the current
  species, then restarts, with a16-pass ancestry budget.
- The literal at `0x093F1AF0` is **0x565**: it scans candidate IDs1..1380.
  This is an actual function bound, not a species-table extent inferred from it.
  The independently proved name/BaseStats extent remains0..1375.
- If no predecessor is found, it returns the current ID. It contains no special
  Cubone/Koffing/Mime Jr. normalization.

Actual CPU execution through the old detoured entry returns:

| Input ID | Actual result | Meaning established by this routine |
|---:|---:|---|
| 1038 Cubone_A | 1038 | No ancestor was selected; this does not prove a new lineage. |
| 1214 Koffing_G | 1214 | Same limitation. |
| 1224 Mime_Jr_G | 1224 | Same limitation. |
| 1036 Exeggcute_A | 1036 | Has an outgoing1036→1037 edge, but no selected ancestor. |
| 1037 Exeggutor-Alola | 102 | Normal Exeggcute's branch appears before1036's regional edge. |
| 1039 Marowak-Alola | 104 | The native predecessor is normal Cubone. |
| 1215 Weezing-Galar | 109 | The native predecessor is normal Koffing. |
| 1216 Mr. Mime-Galar | 492 | The native predecessor is normal Mime Jr. |
| 1158 Mr. Rime | 492 | Walks1158→1216→492. |

Tests require the actual detoured entry and body to execute, no non-ROM reads
except the16-byte stack frame, and no writes outside that stack. They inspect the
actual returned register; a Python graph lookup does not supply the results.

## Evolution dispatch, including a positive control

The actual evolution entry at `0x08042EC4` is detoured by
`00 4B 18 47 55 38 09 09` to `0x09093854`. Synthetic valid mon records for
1038/1214/1224 are supplied at level100, friendship255, with Mimic available.
Normal mode0, trade mode1, item modes2/3, and representative regional evolution
items93/98/99/102 all return **0: no evolution**. The source mon is unchanged.
Only stack writes are allowed by the probe's canaries.

The same actual dispatcher, same CPU fixture and level100 input for
Mr. Mime-Galar1216 returns **1158 Mr. Rime**, proving the test is not simply
forcing a universal no-evolution result. This covers the tested entry modes,
not every possible species-changing script in the game.

All16 native evolution rows for each unresolved record are zero:

| ID | Actual128-byte row block | SHA-256 |
|---:|---|---|
| 1038 | `0x097EE0B0` | `38723a2e5e8a17aa7950dc008209944e898f69a7bd10a23c839d341e935fd5ca` |
| 1214 | `0x097F38B0` | `38723a2e5e8a17aa7950dc008209944e898f69a7bd10a23c839d341e935fd5ca` |
| 1224 | `0x097F3DB0` | `38723a2e5e8a17aa7950dc008209944e898f69a7bd10a23c839d341e935fd5ca` |

## Daycare caller and source discrepancy

Available CFRU `hooks:533` identifies the old `GiveEggFromDaycare` entry at
`0x080460D4`; its actual RR detour bytes `00 49 08 47 31 7A 08 09` select
`0x09087A30`. That implementation calls the actual
egg-ancestry entry: `0x09087C42` loads the pointer at `0x09087D60`
(`0x08045971`), and `0x09087C46` reaches it through the unmodified veneer.
The following species-to-dex branch includes overrides for other species
(including Pikachu/Rotom), but not dex104,109 or439. This is static caller
evidence; the new tests do not execute the complete daycare egg-creation flow.

The publicly available [evolution table](https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/main/data/species/Evolution%20Table.c)
contains1038→1039,1214→1215 and1224→1216 declarations. **Those declarations do
not match the pinned RR row blocks above.** They cannot be imported as proof of
current engine behavior. Exeggcute_A1036 is different: the pinned ROM really
contains1036→1037, method7/parameter98, at `0x097EDFB0`.

Source fingerprints read during this follow-up:

| Public file under `funnotbun/funnotbun.github.io/main` | SHA-256 | Scope |
|---|---|---|
| `data/species/Evolution Table.c` | `0d0bf7306ab9175aa182d051a7c2bbf98a34f1336ec3425ed2e50ab83bdf5342` | Declares the three missing regional precursor edges; disagrees with the binary. |
| `data/locations/wild_encounter_tables.c` | `24ebfcda8be7e0fce44cd47165d0acb70154d2e05c825a9480112351c6429ea9` | No `SPECIES_CUBONE_A`, `SPECIES_KOFFING_G` or `SPECIES_MIME_JR_G` tokens. |
| `data/locations/raid_encounters.h` | `7ebf6c53dc60d666bd126ed11c29d0c731ac35032c7390dc6ef5473421ad6936` | Same absence. |
| `data/species/Base_Stats.c` | `2cd667a4a03079aa3f0674c08206d19b70fef34db0102dd3e23cc9a2f404a470` | Declares all three records, without proving acquisition/normalization. |
| `data/species/Front_Pic_Table.c` | `2dc5a6fe69e9d32b5644af09fe7ffc34c9cadd7878c0ca1a36b215adf8292088` | Mime_Jr_G uses normal Mime Jr. graphics; Koffing_G uses normal Koffing graphics; Cubone_A has its own named asset. None establishes a family policy by itself. |

The absence of named tokens from those wild/raid sources is **not** a proof of
unreachability in the full ROM. Scripts, gifts, NPC trades, other generated
encounters and generic mon-creation functions are not exhaustively excluded by
that search. No record is labeled impossible or permanently unsupported here.

## What remains necessary to resolve the mappings

At least one authoritative RR path must explain whether each record is:

1. A regional precursor that should share the matching regional terminal lineage;
2. An ordinary cosmetic/internal alias that should share the normal lineage; or
3. Reserved metadata with a proved exclusion from supported owned-party sources.

Useful decisive evidence would be an actual species-normalization/form-resolution
routine handling these exact IDs, a verified creation/breeding path producing
them with their intended regional state, or a complete reachable acquisition
domain establishing their reserved status. The current ancestry return-to-self
is the generic no-predecessor behavior. Treating it as proof of a singleton
biological root would repeat the inference the catalog refusal is meant to avoid.

The safe current result is specific: the external intended evolution graph is
not the pinned graph, and the tested engine routines do not supply a missing
alias. All three unknown records remain explicit; no final catalog is emitted.

## Reproduction

The native CPU dependency is the existing isolated lane
`tests/rr/native/requirements-cpu.txt` (`unicorn==2.1.4`). Reuse the installed
`patch/build/native-cpu-deps` path; no global package install is required.

```powershell
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
python -m pytest -p no:faulthandler tests/rr/native/test_regional_precursor_cpu.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/patch/build/rr_clean.gba' -q
python -m ruff check tests/rr/native/test_regional_precursor_cpu.py
```

`-p no:faulthandler` follows the existing Windows Unicorn lane because Unicorn
handles a Windows exception internally. Actual Unicorn errors, non-returning
functions, out-of-frame writes and mismatched register results still fail.
Validation result: **31 passed**, no skips/xfails or native routine replacements.
