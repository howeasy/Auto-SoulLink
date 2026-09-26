# Platinum bind check (D3), SOURCE level

Source: pret/pokeplatinum `c248fb3f` (clone at `.cache/gen4/pokeplatinum`), addresses from `platinumus.xMAP` @ `a2a62d3d`.
OMP card G4-R8 `cx-5e4819dc`. The coordinator re-checked `src/savedata.c:101-111`, `include/pc_boxes.h:18-24`, `src/field_task.c:95-98` and every `SaveData_SetChecksum` caller.

## Verdict per shared assumption

| HGSS assumption | Platinum | Expressible as pack data? |
|---|---|---|
| Overlay residency `{id, active}[3][8]` static | **Same shape**: `Unk_021BF370` 0x021BF370 (0xC0), `src/game_overlay.c:13-32`; set `:129-136`, cleared `:80` | Yes: address from the xMAP (statics are in it; being file-static doesn't matter to an address reader) |
| `sSaveDataPtr` static | Same: `src/savedata.c:36`, 0x021C0794 | Yes |
| `SaveArray_Get(id) = &save->dynamic_region[save->arrayHeaders[id].offset]` | **Different name, same shape:** `&save->body.data[save->pageInfo[id].location]` (`src/savedata.c:107-111`). Both are `base + u32[save + table_off + id*entry_size + field_off]`. | Yes: the profile gives `body_off`, `table_off`, `entry_size`, `field_off` |
| Save array ids | Party 2, player 1, **bag 3**, **PC 38** (the only table in block 1), field player state 6, overworld state 11 (`include/constants/savedata/save_table.h:12-50`) | Yes (per-pack ids) |
| Flash: banks 0x0/0x40000, footer magic 0x20060623, CRC-16-CCITT | Same banks and magic. The footer has one extra field: `{saveCounter, blockCounter, size, signature, u8 blockID, u16 crc}` (`include/savedata.h:8-15`). | The codec reads the footer layout from the profile |
| Per-table midpoint CRC | Platinum-only, **but only for the TV/rankings/Mystery Gift/email/Wi-Fi/easy-chat/contest tables** (`SaveData_SetChecksum` callers). Never party or PC. | Not needed for Soul Link writes |
| PC: `boxes[18]` of 0x1000, curBox +0x12000, modified bits +0x12004 | **Different:** `{u32 currentBoxID @0; BoxPokemon boxMons[18][30] (stride 0xFF0, no pad); names; wallpapers}` (`include/pc_boxes.h:18-24`). There is **no per-box modified flag**; mutators set `SaveData.fullSaveRequired` (`src/savedata.c:251-254`). | Yes: `box_base`, `box_stride`, `cur_box_off`; `modified_flag: null` plus a `full_save_flag` write clause |
| PK4 geometry and crypto | Same (0x88/0xEC, checksum/PID-seeded LCG, same shuffle) | Yes |
| PK4 field meaning | Block D +0x1E is unused in Pt (the HGSS ball/mood); the Pt ball is D+0x1B; met locations DP vs Pt/HGSS | The `pkm` profile says where ball/met live (the HGSS rule `src/pokemon.c:833-837` already picks by originGame) |
| Idle: `taskman(+0x10)==NULL` and app pointers NULL | **Different.** `+0x10` is a transient `FieldTask*`, so it is **not** an idle test in Pt. The idle signal is `FieldSystem_IsRunningApplication` = `processManager(+0x00)->parent/child` (`src/field_task.c:95-98`). | Yes: the safety clause language (one pointer hop + compare) covers both. The HGSS pack adds the `taskman` clause; the Pt pack omits it. |
| `FieldSystem.saveData` @+0x0C | Same (`sFieldSystem` static, `src/field_system.c:55`) | Yes |
| Battle copy-in / copy-back of party, bag, profile | **Same mechanism, different container** (`FieldBattleDTO`; `src/battle/battle_main.c:703-714, 1040-1196`; `src/field_battle_data_transfer.c:415-429`) | Yes: "refuse from battle setup to encounter end" |
| Field poison floors at 1 HP | Same (`src/unk_02054884.c:191-200`) | n/a |

## Consequences for the design

- The D3 claim holds **with a richer profile schema**:
  - a table-of-offsets save accessor (not HGSS field names)
  - explicit box base/stride/current-box offsets
  - a nullable per-box modified flag plus an optional whole-save dirty flag
  - a footer layout description
  - idle clauses as data
- `lua/gen4/storage.lua` must write the pack's "dirty" clause: the per-box bit for HGSS, `fullSaveRequired` for Pt.
- Remaining Pt unknowns (for its own bring-up, not this release): the offsets of `processManager` parent/child and `fullSaveRequired`, from the xMAP and live.
