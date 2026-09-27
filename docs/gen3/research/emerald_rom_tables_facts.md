# Emerald randomized-table facts (for the Emerald `rand` binding)

Source: OMP fact-check cx-b24af4e4 (2026-09-26), read against pret pokeemerald @ c65e93f2 and
`data/gen3/pret/pokeemerald.sym`. Coordinator spot-checked the five table symbols below against the sym.
Not yet verified on a stock Emerald ROM (see Open).

## Same as FR/LG (no decoder stride change)

- `struct Trainer` 40 B: partyFlags +0, class +1, name +4, partySize +0x20, party ptr +0x24 (`include/data.h:80-91`).
- The four TrainerMon layouts are byte-identical to FR/LG (`include/data.h:37-56`); ROM strides 8/16/8/16 are INFERRED (same agbcc).
- Wild header 20 B (pointers at 4/8/12/16), info 8 B, WildPokemon 4 B, slots 12/5/5/10, sentinel map group 0xFF.
- `struct Evolution` 3×u16, EVOS_PER_MON 5, stride 40 per species; `gSpeciesInfo` stride 28, abilities at 0x16/0x17.
- `gTrainerClassNames` stride 13.

## Differs

| Item | FR/LG | Emerald |
|---|---|---|
| trainer name field | 12 B | 11 B (harmless: `decode_name` stops at 0xFF) |
| trainers | 743 | 855 |
| wild headers | — | 125 (124 maps + sentinel) |
| trainer classes | 107 | 66 |
| species rows | 412 | 412 (not 386: a 386 count silently truncates) |

## Emerald symbols (`data/gen3/pret/pokeemerald.sym`)

| Symbol | Address | Size |
|---|---|---|
| gTrainerClassNames | 0x0830FCD4 | 0x35A |
| gTrainers | 0x08310030 | 0x8598 |
| gSpeciesInfo | 0x083203CC | 0x2D10 |
| gEvolutionTable | 0x0832531C | 0x4060 |
| gLevelUpLearnsets | 0x0832937C | 0x670 (412 pointers) |
| gRematchTable | 0x085500A4 | 0x4E0 (78 × 16) |
| gWildMonHeaders | 0x08552D48 | 0x9C4 |

## Binding work (card after RF-1 and T3 land)

1. Open the title gate at `server/adapters/gen3_rom_tables.py` (`table_symbols`) to `emerald`.
2. Emerald `rom_tables` counts in the profile generator (T3-leased `tools/gen_gen3_profile.py`), with a `count * stride == sym size` assertion.
3. A stock-Emerald-ROM control test (sha1 f3ae0881…) that confirms the 8/16 party strides, like the FR/LG one.
4. Emerald-only facts: Altering Cave has 9 variant tables (as in FR/LG); Feebas tiles can't be expressed per map; rematch
   trainers map through `gRematchTable` by linear search; Frontier/Tent/Pyramid trainers and wild tables are outside
   `gTrainers`/`gWildMonHeaders` (their writes are refused anyway).

## Open

- Party strides on a real Emerald ROM (step 3).
- Whether rematch identity is needed for Upcoming Key Trainers.
