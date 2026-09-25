# `gen3_emerald` pack

Vanilla Pokémon Emerald (`BPEE` rev 0, sha1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7`).
The JSON files are generated; do not hand-edit them. `admitted` stays `false` until EG4 (ruling 24).

| File | Generator | Check |
|---|---|---|
| `profile.json` | `python tools/gen_gen3_profile.py` (`build_emerald`) | `--check` |
| `engine_signals.json` | `python tools/gen_gen3_engine_signals.py` (`EMERALD_BINDINGS`) | `--check` (needs the pinned ROMs) |

Pins: pret/pokeemerald `c65e93f20a5275ab03b07d6f6411096a82a60ffd`; its published symbols
`data/gen3/pret/pokeemerald.sym` (symbols branch `dba968c6`, provenance
`data/gen3/pret/pokeemerald_provenance.json`).

## `profile.json`

It has the same key set as the `gen3_frlg` `firered` title: 25 `ram`, 14 `rom`, 44 `derived`, and
the same `rom_thumb` list. Unlike FR/LG it is **not** parsed out of `lua/games/gen3_frlge.lua`.

- Every address is read out of `pokeemerald.sym` by symbol name, and must be unique there.
  Code pointers are stored Thumb (`|1`).
- `_src` gives the `.sym` line for each address.
- `POST_BATTLE_WRITER_TASKS` is the `Task_LaunchLvlUpAnim` inside `[SetControllerToPlayer, SetControllerToOpponent)`.
  pokeemerald has two statics with that name; this range picks the one in `battle_controller_player.o`.
- Every derived constant cites the pret `file:line` and the identifier that line carries.
  `tests/unit/test_gen3_emerald_pack.py` re-reads each cited line when the pret checkout exists.
- Four sizes are the `.sym` array size divided by its cited count: `BASESTATS_ENTRY_SIZE`,
  `BATTLE_MOVE_ENTRY_SIZE`, `DISABLE_STRUCT_SIZE` and `TASK_STRUCT_SIZE`.
- `SE_SONG_HEADERS` is keyed by the pokeemerald song ids (`include/constants/songs.h`):
  16 faint, 17 flee, 22 boo, **31** success, **32** failure, **102** shiny. FR uses 25/26/95 for
  the last three.

Controls in the test:

- **HEADER.** The ROM's own GF header at `0x08000100` (`src/rom_header_gf.c:18-94`) must agree with
  the profile. It checks flags `0x1270`, vars `0x139C`, the SaveBlock2/1 sizes `0xF2C`/`0x3D88`, the
  trainer id and name offsets, `gSpeciesInfo`, `gBattleMoves` and the Poké Ball pocket count.
- **Literal pool.** `BATTLE_TYPE_ADDR` must be `0x02022FEC`, with 457 little-endian ROM refs. The
  probe's negative control is that the address one page up has 0 refs.
- **Stub cross-check.** The old unadmitted `emerald` stub in `gen3_frlg/profile.json` is an
  independent second source. The profile must agree with every value that stub carries.

### Recorded limits

- **`derived.SB1_BADGE_BYTE_OFFSET` is `null` by design, not OPEN.** Emerald badge flags are
  `0x867..0x86E`. They straddle `SaveBlock1.flags` bytes `0x10C` (bit 7) and `0x10D` (bits 0-6),
  which a single byte cannot express, so `derived.BADGE_FIRST_FLAG` (`0x867`) carries the flag
  id instead: `lua/gen3/reads.lua:442-468`'s `read_badges()` reads each bit from its own byte
  when `BADGE_FIRST_FLAG` is set (E2-ENTRY+BADGE), and refuses by name if a profile ever sets
  both derived fields at once. The Python twin is `tools/gen3_reads_pydec.py`'s
  `decode_badges_straddle` / `decode_badges_for_profile`.
- **`POKEMON_STORAGE_BASE`** is the base of the ASLR window (`struct PokemonStorageASLR`). The live
  address is `*gPokemonStoragePtr`, the same as FR/LG.

## `engine_signals.json`

All 21 FR site kinds are pinned; none are OPEN. Each capture offset was re-derived on the Emerald
bytes by disassembling the function against the pret source. `docs/gen3_emerald/engine_sites.md`
has the per-kind contracts and the FR vs Emerald capture-offset table. `pc_move` is `CopyMonToPC`,
the Emerald name for the FR `SendMonToPC`.

`evidence` is `SOURCE_BYTE_PIN` and `live_verified` is `false`. No emulator has run against this
pack.
