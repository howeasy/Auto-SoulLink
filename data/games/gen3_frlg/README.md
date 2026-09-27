# `gen3_frlg` pack

Generated. Do not hand-edit anything here — run `python tools/gen_gen3_profile.py`
(`--check` is the P2 exit condition "profile diff = 0 vs today's literals").

## `profile.json`

First cut (P2 card C2-2), supplemented by pinned storage facts (P3 card C3-6).
The primary source of addresses is the literal table
`GEN3.profiles.vanilla` in `lua/games/gen3_frlge.lua`; the generator parses that Lua text
directly (no Lua runtime) so nothing is re-typed. `source.git_head` is the last commit that
touched that file and `source.sha256` its content hash, so a change there makes `--check` fail.

### Pinned vanilla storage and party facts

Only `firered` and `leafgreen` receive these additions. Their per-title `_src` maps
record provenance for each added key. The generator reads `gPokemonStorage` from
each title's committed `.sym`; C layout constants are recorded in the generator
from pret/pokefirered commit `c75f352304d529f6ba92d4f74b9cf8b5c3810788`.
No external checkout is needed to regenerate or run `--check`.

| Key | Value | Pinned evidence |
|---|---|---|
| `ram.POKEMON_STORAGE_BASE` | `0x02029314` | `data/gen3/pret/pokefirered.sym:173` and `pokeleafgreen.sym:173`, `gPokemonStorage` |
| `derived.BOX_DATA_OFFSET` | `4` | pret `include/pokemon_storage_system.h:44-48`; `include/pokemon.h:105-108`: `u8 currentBox` followed by a struct beginning with `u32`, requiring alignment padding |
| `derived.BOXES_PER_STORE` | `14` | pret `include/pokemon_storage_system.h:7`, `TOTAL_BOXES_COUNT` |
| `derived.MONS_PER_BOX` | `30` | pret `include/pokemon_storage_system.h:8-10`, rows times columns (`5 * 6`) |
| `derived.PARTY_CAPACITY` | `6` | pret `include/constants/global.h:78`, `PARTY_SIZE` |

The `/*0x0001*/` comment on `boxes` is stale: alignment puts the array at offset
4, consistent with the following `boxNames` offset `0x8344`. The box counts
are in `pokemon_storage_system.h`, not `constants/global.h`.

**Reader integration limitation:** this base is a cross-check, not a trusted live
storage address. `gPokemonStoragePtr` is at `0x03005010` in both symbol files
(line 811); pret `src/load_save.c:79` assigns it `&gPokemonStorage + offset`.
The reader must dereference `ram.PSP_PTR_ADDR` at read time. At the C3-6 starting
cut (`959c578`), `lua/gen3/reads.lua:318-326` instead uses the static base and
does **not** dereference that pointer. This card does not modify the reader;
these pack additions alone do not establish correct live PC reads.

RR receives only the shared `derived.PARTY_CAPACITY` addition, parsed from its
existing `_detectRR` party-count limit in `lua/games/gen3_frlge.lua:424`, with
per-title provenance. This preserves the existing RR source assumption rather
than claiming independent verification of RR's engine layout.

Per title: `ram` (EWRAM/IWRAM), `rom` (ROM addresses incl. `SE_SONG_HEADERS`, `BASESTATS_ADDR`,
the `CB2_*` callbacks), `derived` (sizes, offsets, counts, modes and flags), plus `rom_thumb` —
the `rom` keys whose literal already carries the Thumb bit. Those values are kept **verbatim**:
`gTasks[].func` and `gMain.callback2` are read out of RAM with the `+1`, so stripping the bit
here would make the profile disagree with what the client compares.

| title | Lua table | admitted | `rom_sha1` |
|---|---|---|---|
| `firered` | `vanilla` | yes | `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc` |
| `leafgreen` | `vanilla` | yes | `574fa542ffebb14be69902d1d36f1ec0a4afd71e` |
| `firered_ap` | `ap` | **no** | — |
| `emerald` | `emerald` | **no** (superseded, see below) | — |

### LeafGreen divergence is UNVERIFIED

The legacy portion of `leafgreen` copies the FireRed profile, because `lua/games/gen3_frlge.lua` has one
`vanilla` table serving both BPRE and BPGE. Whether any LG address actually diverges from FR has
**not** been established. Pinning LG's own addresses (or proving equality against a pret/LG build)
is **P2 card C2-3**; until it closes, every LG row in `docs/gen3_requirements.md` inherits that
caveat and the pack is not evidence that LG is covered.
The storage additions above independently name each title's symbol file; they
do not verify the remaining legacy addresses.

### Unadmitted titles

`firered_ap` (Archipelago) is carried verbatim so no data from the old client's table is lost
(PLAN §5.1: "`emerald`/`ap` profiles remain in the packs as unadmitted titles"). `admitted: false`
is the machine-readable form of that; the client refuses it by name. Its addresses were never
re-verified for this pack and carry no ROM hash.

The `emerald` stub here is superseded by the real `gen3_emerald` pack
(`data/games/gen3_emerald/`), admitted on its own on this release candidate; this stub's removal
is tracked in the Emerald plan (`docs/gen3_emerald/PLAN.md`).
