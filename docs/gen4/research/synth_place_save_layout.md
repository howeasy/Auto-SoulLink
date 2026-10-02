# SYNTH `place`: save layout for location + flags/vars (2026-10-02)

**Source:** OMP cx-181e65e0. Every citation was re-verified at the PINNED tree, `E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold` @ `ad7a3afa`. The research's first pass used the unpinned `.cache/pret` checkout.

**Status:** SOURCE only. Nothing here has been run.

**Purpose:** a disclosed SYNTH kind that places the player at a story-gated gift or trade site (`G2_PRODUCER_PLAN.md` §4: V5/V7/V9/V10).

## Offsets (general chunk = the 42-array dynamic region, block 0)

The offsets are computed at runtime by `SaveData_InitSubstructs` (`src/save.c:744-768`): each array starts at `((size+3)&~3)+4`.

| Array | HG/SS | hge |
|---|---|---|
| SAVE_BAG (3) | 0x644 | 0x644 |
| SAVE_FLAGS (4): `vars[368]` u16 | 0xDE4-0x10C3 | 0xFD4-0x12B3 |
| SAVE_FLAGS (4): `flags[364]` u8 | 0x10C4-0x1233 | 0x12B4-0x1417 |
| SAVE_LOCAL_FIELD_DATA (5) | 0x1234 | 0x1424 |
| SAVE_MAP_OBJECTS (10) | 0x12B8 | 0x14A8 |

Anchors that confirm these offsets:
- **FILE anchors:** the HGSS Potion at +0xB64, HGSS LocalFieldData at 0x1234, and hge LocalFieldData at 0x1424.
- **hge shift:** the +0x1F0 is the expanded bag (124 slots × 4).
- **hge vars/flags:** derived, not read from a save. They close on the FILE-verified 0x1424, which would break if hge's NUM_VARS or NUM_FLAGS differed.

**Flags and vars** (`include/save_vars_flags.h:9-12`):
- A flag lives at `flags[id/8]`, bit `1<<(id%8)` (`src/save_vars_flags.c:45-54`).
- `flagId 0` is a no-op.
- Ids ≥ 0x4000 are RAM-only temp flags.
- A var lives at `vars[id-0x4000]`.

**Location** (`include/field_types_def.h:10-16`) is five s32: `mapId, warpId, x, y, direction`. Write all five, with `warpId = -1` (`src/location_backup.c:10-29`).

LocalFieldData layout (`src/save_local_field_data.c:13-28`):

| Field | Offset in LocalFieldData |
|---|---|
| current | +0x00 |
| entrance | +0x14 |
| previous | +0x28 |
| dynamicWarp | +0x3C |
| specialSpawn | +0x50 |
| musicId | +0x64 |
| weather | +0x66 |
| lastSpawn | +0x68 |
| cameraType | +0x6A |
| player (PlayerSaveData) | +0x6C |

## Coherence: a Location-only write is NOT enough (F5, F6)

On ordinary CONTINUE (`FieldTask_ContinueGame_Normal`, `src/field_warp_tasks.c:355-`; the non-flag-966 branch), the game calls `sub_0205323C` (`:248-259`). That does the following:
1. `FieldSystem_RestoreMapObjectsFromSave` restores the SAVED map-object list wholesale (`src/save_local_field_data.c:133-151`; `MapObjectManager_RestoreFromSave`, `src/map_object.c:413-425`). There is no mapId filter.
2. `PlayerAvatar_CreateWithActiveMapObject` then re-attaches the avatar to the restored `movement == 1` object at its OLD coordinates (`src/player_avatar.c:169-180`).

Consequences of writing only the Location:
- The old map's objects appear on the new map.
- The player stands at the old coordinates.

`PlayerSaveData.state` (bike/surf, `include/player_avatar.h:20-24`) is also consumed at boot (`field_warp_tasks.c:225,230`).

**`place` must write all of the following:**
- Location (×5);
- the `movement == 1` SavedMapObject in the 64-entry list at SAVE_MAP_OBJECTS: mapId +0xC, currentX/Y/Z +0x1C/+0x1E/+0x20, facing +0x8;
- clear `MAPOBJECTFLAG_ACTIVE` on every other entry;
- `player.state = 0`.

It must also check a positive anchor: exactly one active `movement == 1` entry.

The map matrix itself is derived from mapId (`field_warp_tasks.c:266`, `map_matrix.c:71`), so no geometry is cached in the save.

**First physical check, before building on this:** boot one Location-only SYNTH save, then the full write, and record where the avatar lands.

## CRC (F8)

- **Only seal:** the per-sector `SaveChunkFooter` CRC over `size - 0x10` (`src/save.c:304-307, 329-348`). `gen4_codec` already matches it field for field.
- **No per-array CRC** on the main arrays. `CreateChunkFooter` and `ValidateChunk` are only on the extra-chunk paths; `SaveSubstruct_*CRC` covers only Easy Chat, Mystery Gift, Rankings, Wi-Fi history and unk_23.
- **Consequence:** `_seal` needs no change.

## Repo fixes noted

- The `tools/gen4_routes.py:179-203` cite for 0x1234 is stale; the value comes from `profile.json location.file_cross_check.general_off_of_array`.
- The `profile.json:2967 / :8080` docstring pointer is stale.
- Record the flags, vars and map_objects offsets in the packs, with SOURCE + file_cross_check, not in the codec. The codec is the independent oracle.

## Unknown

- The runtime behaviour of the full write. Settle it with one boot.
- The hge LocalFieldData internal layout is assumed vanilla.
