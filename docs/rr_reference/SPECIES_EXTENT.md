# Pinned RR 4.1 species-table extent

This is offline binary evidence for the exact base SHA-256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
It establishes reference table records, not release admission or playability.
Addresses below are GBA ROM bus addresses; subtract `0x08000000` for file offsets.

## Two independent boundaries agree

| Table | Start | End exclusive | Record bytes | Count |
|---|---|---|---:|---:|
| Species names | `0x094042CC` | `0x09407DEC` | 11 | 1376 |
| BaseStats | `0x097B98EC` | `0x097C2F6C` | 28 | 1376 |

Therefore the verified reference domain is **0 through 1375**, including sentinels
and placeholders. The extraction now uses this ROM domain independently of the
canonical-name catalog, which currently stops at 1355.

### Names and the following graphics asset

- Pointer `0x08000144` contains `CC 42 40 09` → `0x094042CC`.
- Actual `GetSpeciesName` code at `0x08040FE0` contains
  `02 4F 0B 20 68 43 C3 19 32 1C 04 E0`; `movs r0,#11` and multiply establish
  the stride. Its literal at `0x08040FEC` independently names the same table.
- All 1376 records contain their `0xFF` terminator within 11 bytes. Record 1375
  decodes exactly `Chillet` and ends at `0x09407DEC`.
- `0x09407DEC` starts `10 00 08 00`, an LZ77 graphics header, and is independently
  referenced as an asset at `0x097B6DC4` and `0x097B8A84`. It is not another name.
- Source support: vendored CFRU `include/new/rom_locs.h:11-12` defines the pointer
  location and `SpeciesNames_t`; `include/global.h:44` sets `POKEMON_NAME_LENGTH=10`.
  The pinned ROM code confirms these dimensions rather than trusting the headers.

### BaseStats and the following cry table

- Pointer `0x080001BC` contains `EC 98 7B 09` → `0x097B98EC`.
- The actual gender getter at `0x0803F794` multiplies species by 28 and reads ratio
  byte `+0x10`; its literal at `0x0803F7C8` names the same BaseStats table.
- Actual sound code at `0x08072108` contains
  `48 00 40 18 80 00 01 49 34 E0 00 00 6C 2F 7C 09`.
  The first instructions multiply the cry index by 12; the pointer literal at
  `0x08072114` selects `0x097C2F6C`, the following cry table.
- Source support: vendored pret `src/sound.c:40-41` declares normal/reversed
  `gCryTable`; its `PlayCryInternal` implementation selects a `ToneData` entry.
  `include/gba/m4a_internal.h:57` defines its 12-byte structure.
- The difference `0x097C2F6C - 0x097B98EC` is exactly `1376 × 28`. The apparent
  zero statistics at hypothetical species 1376 are the first cry entry, followed
  by tone data. A partial-zero heuristic would have misclassified it.

The generator checks these instruction bytes, pointers, bounds and the agreement
of the two extents before reading records. It never uses the unrelated graphics
limit `0x565` as a species count; doing that would read into the following data.

## Newly bounded records absent from the canonical-name catalog

These are **exact in-ROM display labels**, including truncation and repeated names.
They are not guessed canonical names or form aliases.

| ID | ROM display label |
|---:|---|
| 1356 | Ursaluna |
| 1357 | Ogerpon |
| 1358 | Ogerpon |
| 1359 | Ogerpon |
| 1360 | Ogerpon |
| 1361 | Polchageis |
| 1362 | Sinistcha |
| 1363 | Dipplin |
| 1364 | Fezandipti |
| 1365 | Munkidori |
| 1366 | Okidogi |
| 1367 | RagingBolt |
| 1368 | Iron Crown |
| 1369 | Archaludon |
| 1370 | Terapagos |
| 1371 | Hydrapple |
| 1372 | Pecharunt |
| 1373 | IronBouldr |
| 1374 | Gouge Fire |
| 1375 | Chillet |

The existing evolution table supplies four relevant permanent edges:
`1132→1363`, `1363→1371`, `1176→1369`, and `1361→1362`.
They now participate in reference components while missing catalog identities
remain explicit. No temporary, regional, or cosmetic form aliases are inferred.

## Supporting source provenance

The following vendored files were read from the original asset checkout without
modifying them. They provide interpretation context; the pinned binary anchors
are the authority for this RR layout. They need not be installed to run the tool.

| Relative source path | SHA-256 |
|---|---|
| `patch/vendor/cfru/include/new/rom_locs.h` | `5c055c94c81d9b00fdfffa46a31a1b928203708d439ca946841be13c20bd91ad` |
| `patch/vendor/cfru/include/global.h` | `871a6e462e79da3c2180579782d12cb8eb98b5062819b757706a6c47472ee8e7` |
| `patch/vendor/cfru/include/pokemon.h` | `3185d24d0577c3eb1c0a87925dcc9c87b96829cf1f5658f79641ddc18ce0032d` |
| `patch/vendor/pokefirered/src/sound.c` | `851313931ebdbf2f0933b52295707f82e948735813fac84fdba74c0446ada958` |
| `patch/vendor/pokefirered/include/gba/m4a_internal.h` | `9e841d8fe72d6af9f2d5a8135f686618e20975132a6d2fc95e6c7604213505e6` |
| `patch/vendor/pokefirered/charmap.txt` | `4da662317b3b5109a52064f9012d85b644d1dbf0f3f24243374aeef4cf25f061` |
