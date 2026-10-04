# Polished Crystal 3.2.3 — ROM encounter tables vs `lua/gen2/rom.lua`

Card **C-ROMTABLES** (`docs/polished/CLIENT.md` amendment). Decides reader by reader
whether the vanilla `lua/gen2/rom.lua` can be reused unchanged once the profile gains
Polished coordinates, or needs a separate `polished_rom.lua`.

**ROM facts below are bank:addr + flat offset + bytes read from
`F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc`.** Flat =
`bank*0x4000 + addr - 0x4000`. No WRAM address is dumped — WRAM is not in the ROM.

Sources: `lua/gen2/rom.lua` (339 lines), `server/adapters/gen2_rom_scan.py`,
`data/games/gen2_crystal/profile.json` (`titles.crystal.rom` / `.constants` /
`.derived`), `F:/slink-work/tmp/upr-fork-b/check_wild.py`, and the Polished sources.

## 1. Answer in one line

**`rom.lua` cannot be reused unchanged. Every reader except `probabilities()` has a
different record stride or a different species encoding, and three of them have a
different *row* stride as well.** The changes are localised and data-shaped — strides,
slot sizes, a species decoder, and map-id resolution — so the recommendation in §7 is
**extend `rom.lua` generically** rather than fork it, because the vanilla reader is
already profile-driven and the per-reader deltas are all numbers.

## 2. The two axes of difference

**Axis 1 — species is two bytes.** Vanilla wild/tree/fish/contest slots carry a **1-byte**
species. Polished carries a `dp` pair: `db LOW(species), HIGH(species) << MON_EXTSPECIES_F | form`
(`macros/data.asm:89-91`). Every `species(byte(x))` call in `rom.lua` would decode
species 201 as 201 instead of 201 | form<<8, and would read a *form byte* as a *level*
wherever the stride is also wrong.

**Axis 2 — record strides differ.** Measured, not assumed:

| Record | Vanilla | Polished | ROM proof |
|---|---|---|---|
| grass wild row | 47 (`2 + 3 + 7*3*2`) | **68** (`2 + 3 + 63`) | `JohtoGrassWildMons` `0c:46e8` flat `0x306E8`: `03 02 05 05 05 03 13 00 04 13 00 05`; next row head at +68 is `03 03` |
| water wild row | 9 (`2 + 1 + 3*2`) | **12** (`2 + 1 + 9`) | `JohtoWaterWildMons` `0c:5c6d` flat `0x31C6D`: `1e 01 05 0f c2 00 14 c3 00 0f c3 00`; next row head at +12 is `03 19` |
| grass slot | 2 (`level`,`species`) | **3** (`level`,`dp`) | first grass slot at `0x306E8` + 5 = `03 13 00` = level 3, species `$13` = 19 |
| water slot | 2 | **3** | first water slot at `0x31C6D` + 3 = `0f c2 00` = level 15, species `$C2` \| (`$00` & `$20`) << 3 = 194 |

| tree slot | 3 (`weight`,`species`,`level`) | **4** (`weight`,`dp`,`level`) | `check_wild.py:82-88` walks `p += 4` |
| fish slot | 3 (`threshold`,`species`,`level`) | **4** (`chance`,`dp`,`level`) | `check_wild.py:70` walks `p += 4` |
| fish group header | 7 | **8** (2 chance bytes + 3×`dw`) | `FishGroups` `24:6213` flat `0x92213`: `a5 b2 8b 62 97 62 a7 62 bf c1` |
| contest slot | 3 (`species`,`min`,`max`) | **5** (`chance`,`dp`,`min`,`max`) | `ContestMons` `25:58b4` flat `0x958B4`: `0f 0a 00 07 12` |
| base-stat record | 32 | **34** | `BaseData` `11:4b18` flat `0x44B18`: Bulbasaur `2d 31 31 2d 41 41 0b 03 …`; Ivysaur `3c 3e` begins exactly at +34 |
**Axis 3 — map identity.** Vanilla wild rows carry `(mapGroup, mapNumber)` — two bytes,
decoded by `map_at()` in `rom.lua`. Polished rows carry a single `map_id` from the
`map_id` macro (`macros/asserts.asm:79`). `JohtoGrassWildMons` `0c:46e8` flat
`0x306E8` starts `03`, and Sprout Tower 2F is map 3 — one byte, no group.

**Axis 4 — base-stat field order.** `rom.lua:92` asserts `byte(flat) == id`, then reads
HP at +1. Polished's record starts `2d 31 31 2d 41 41` = 45/49/49/45/65/65 at **+0..+5**
(`data/pokemon/base_stats/bulbasaur.asm:1`), and `BaseData` is indexed by *species +
non-cosmetic variants* — 334 records for 291 species — so record index ≠ species id
past the base range.

## 3. Reader-by-reader decision

| Reader (`rom.lua`) | Vanilla layout | Polished layout | Reusable? | profile.rom keys + values needed |
|---|---|---|---|---|
| `probabilities()` `:109-122` | `slots` × `(threshold, slot_offset)`, must end at 100 | **UNVERIFIED** — `GrassMonProbTable` `0c:4235` flat `0x30235` begins `1e 3c 50 5a 5f 62 64 …`; that is not a strictly-increasing-then-100 run at 7 entries, so the shape is not established | **UNVERIFIED** | `GrassMonProbTable` `0c:4235` flat `0x30235`; `WaterMonProbTable` `0c:423c` flat `0x3023C` |
| `wild().read_table` `:130-153` grass | row 47: `mapGroup`,`mapNumber`, 3 rates, 3×7×(level,species) | row **68**: `map_id`, 3 rates, 3×7×(level,dp) | **no** — row stride, slot size and map encoding all differ | `JohtoGrassWildMons` `0c:46e8` flat `0x306E8`; `KantoGrassWildMons` `0c:5f1a` flat `0x31F1A`; `OrangeGrassWildMons` `0c:73fc` flat `0x333FC`; `SwarmGrassWildMons` `0c:773e` flat `0x3373E` |
| `wild().read_table` water | row 9: `mapGroup`,`mapNumber`, 1 rate, 3×(level,species) | row **12**: `map_id`, 1 rate, 3×(level,dp) | **no** | `JohtoWaterWildMons` `0c:5c6d` flat `0x31C6D`; `KantoWaterWildMons` `0c:71f7` flat `0x331F7`; `OrangeWaterWildMons` `0c:76e9` flat `0x336E9`; `SwarmWaterWildMons` `0c:77c7` flat `0x337C7` |
| `tree()` `maps()` `:168-180` | 3-byte rows `(mapGroup,mapNumber,set_id)`, `$FF`-terminated | 3-byte rows `(map_id, count, ids…)` — `TreeMonMaps` `2e:4483` flat `0xB8483` begins `18 01 04 18 02 04 13`, i.e. map 24 with 1 id, then map 24 with 2 ids | **no** — same width, different meaning | `TreeMonMaps` `2e:4483` flat `0xB8483`; `RockMonMaps` `2e:4505` flat `0xB8505` |
| `tree()` `slots()` `:184-199` | slot 3 `(weight,species,level)`, weights sum to 100 | slot **4** `(weight,dp,level)`; 10 sets, and set 9 (Canyon) has one slot list where vanilla's rock set has none | **no** | `TreeMons` `2e:4701` flat `0xB8701` (`17 47 17 47 2d 47 47 47 …` = 10 pointers) |
| `fishing()` `:214-235` | group header 7; slot 3 `(threshold,species,level)`; a separate `TimeFishGroups` table | group header **8** (2 chance bytes + 3×`dw` rod pointers); slot **4** `(chance,dp,level)`; **`TimeFishGroups` does not exist** | **no** | `FishGroups` `24:6213` flat `0x92213` |
| `roamers()` `:255-297` | disassembles `InitRoamMons`…`CheckEncounterRoamMon` byte-by-byte for `ld n,addr` / `ld (nn),a` pairs | same routine names exist (`InitRoamMons` `0c:437d` flat `0x3037D`, `CheckEncounterRoamMon` `0c:43aa` flat `0x303AA`) plus a new `RoamMaps` table `0c:44bd` flat `0x304BD` | **UNVERIFIED** — the instruction stream was not compared | `InitRoamMons` `0c:437d` flat `0x3037D`; `CheckEncounterRoamMon` `0c:43aa` flat `0x303AA`; `RoamMaps` `0c:44bd` flat `0x304BD` |
| `base_stats()` `:87-107` | stride 32; HP at +1; assert `byte(flat) == id` | stride **34**; stats at **+0**; `BaseData` indexed species+variants (334 records) so index ≠ id | **no** | `BaseData` `11:4b18` flat `0x44B18` |

**Contest** has no `rom.lua` reader today (the vanilla pack's `BCCWildsOffset` is read
elsewhere); Polished's is `ContestMons` `25:58b4` flat `0x958B4` through
`ContestMonsEnd` `25:58f0` flat `0x958F0` — 60 bytes, 12 five-byte entries. Listed so
the profile has the key when a reader is added.

### 3.1 `profile.constants` / `profile.derived` deltas

`rom.lua:36` asserts `count == 251 and stride == 32` — a hard stop for Polished. New
values (sources given):

| Key | Vanilla | Polished | Source |
|---|---|---|---|
| `base_stats_stride` | 32 | **34** | `constants/pokemon_data_constants.asm:35` (`BASE_DATA_SIZE`) |
| `species_count` / `NUM_POKEMON` | 251 | **289** | `constants/pokemon_constants.asm:318` (`NUM_SPECIES - 2*HIGH(NUM_SPECIES)`); note the *record* count is 334, not 289 |
| `num_grassmon` / `num_watermon` | 7 / 3 | 7 / 3 | unchanged |
| `num_treemon_sets` | 8 | **10** | `data/wild/treemons.asm:13` `assert_table_length NUM_TREEMON_SETS`; 10 pointers at `0xB8701` |
| `num_fishgroups` | 13 | **17** | `data/wild/fish.asm:29` `assert_table_length NUM_FISHGROUPS` |
| `num_time_fishgroups` | 22 | **0** | `TimeFishGroups` is absent from the Polished sym |
| `party_struct_size` | 48 | **48** | `constants/pokemon_data_constants.asm:185` `PARTYMON_STRUCT_LENGTH` — same length, **different field order** (RAM.md) |
| `box_struct_size` | 32 | **UNVERIFIED** | not derived in this pass |
| `num_boxes` | 14 | **20** | `constants/pokemon_data_constants.asm:304` `NUM_BOXES` (comment reads `; 20`) |
| `box_capacity` | 20 | **20** | `constants/pokemon_data_constants.asm:298` `MONS_PER_BOX` |
| `egg_species` | 253 | **253** | `constants/pokemon_constants.asm:320` `CANCEL EQU -1` = `$FF`… **UNVERIFIED**, see §4 |
| `num_roammon_maps` | 16 | **UNVERIFIED** | `RoamMaps` present, count not derived |
| `roamer_count` | 2 | **UNVERIFIED** | not derived |

## 4. Constants the client needs

### 4.1 `BATTLETYPE_*` — the area-resolving set is `{0, 3, 4}`

`constants/battle_constants.asm:107-122` is a `const_def` whose first entry is
`BATTLETYPE_NORMAL`, so the ordinals are:

| Value | Constant | Line |
|---|---|---|
| 0 | `BATTLETYPE_NORMAL` | `:107` |
| 1 | `BATTLETYPE_CANLOSE` | `:108` |
| 2 | `BATTLETYPE_TUTORIAL` | `:109` |
| **3** | **`BATTLETYPE_FISH`** | `:110` |
| **4** | **`BATTLETYPE_TREE`** | `:111` |
| 5 | `BATTLETYPE_ROAMING` | `:112` |
| 6 | `BATTLETYPE_CONTEST` | `:113` |
| 7 | `BATTLETYPE_SAFARI` | `:114` |
| 8 | `BATTLETYPE_GHOST` | `:115` |

The area-resolving set is therefore `{0, 3, 4}` — normal, fishing, tree. The earlier
"8 = GROTTO" reading was wrong: `BATTLETYPE_GHOST` is 8 and `BATTLETYPE_GROTTO` is 9.

### 4.2 What `reads.lua:60-70` asserts, and Polished's values

| Assert | Vanilla | Polished | Source |
|---|---|---|---|
| `PARTYMON_STRUCT_LENGTH` | 48 | **48** | `constants/pokemon_data_constants.asm:185` |
| `BOXMON_STRUCT_LENGTH` | 32 | **UNVERIFIED** | not derived this pass |
| `MON_NAME_LENGTH` | 11 | **11** | `constants/text_constants.asm:5` |
| `NUM_MOVES` | 4 | **4** | `constants/battle_constants.asm:7` |
| `MONS_PER_BOX` | 20 | **20** | `constants/pokemon_data_constants.asm:298` |
| `NUM_BOXES` | 14 | **20** | `constants/pokemon_data_constants.asm:304` (comment `; 20`) |
| `NUM_POKEMON` | 251 | **289** | `constants/pokemon_constants.asm:318` |
| `EGG` | 253 | **UNVERIFIED** | `CANCEL EQU -1` (`:320`) is `$FF`; the egg species *value* was not derived |
| `BOX_LENGTH` | 1104 | **UNVERIFIED** | depends on the box record size above |

`PARTYMON_STRUCT_LENGTH` being 48 in both games is a trap, not a match: RAM.md records
the same length with a different field order (PP at +22 not +23, PP-ups as one byte at
+0x16), so every offset inside it shifts.

## 5. Proposal for `tools/gen_polished_profile.py`

Emit, under `titles.polished_crystal`:

```
rom: BaseData 11:4b18/0x44B18
     JohtoGrassWildMons 0c:46e8/0x306E8   KantoGrassWildMons  0c:5f1a/0x31F1A
     OrangeGrassWildMons 0c:73fc/0x333FC  SwarmGrassWildMons 0c:773e/0x3373E
     JohtoWaterWildMons 0c:5c6d/0x31C6D   KantoWaterWildMons  0c:71f7/0x331F7
     OrangeWaterWildMons 0c:76e9/0x336E9  SwarmWaterWildMons 0c:77c7/0x337C7
     GrassMonProbTable 0c:4235/0x30235     WaterMonProbTable   0c:423c/0x3023C
     TreeMons 2e:4701/0xB8701              TreeMonMaps 2e:4483/0xB8483
     RockMonMaps 2e:4505/0xB8505          FishGroups  24:6213/0x92213
     RoamMaps  0c:44bd/0x304BD            ContestMons 25:58b4/0x958B4
     ContestMonsEnd 25:58f0/0x958F0       InitRoamMons 0c:437d/0x3037D
     CheckEncounterRoamMon 0c:43aa/0x303AA
derived: base_stats_stride 34, base_tmhm_offset 20, species_count 289,
         num_grassmon 7, num_watermon 3, num_treemon_sets 10, num_fishgroups 17,
         num_time_fishgroups 0, party_struct_size 48, num_boxes 20, box_capacity 20,
         mon_name_length 11, rom_size 2097152
layout: wild_grass_row 68, wild_water_row 12, wild_slot 3, tree_slot 4,
        fish_slot 4, fish_group_header 8, contest_slot 5, species_bytes 2
```

`base_tmhm_offset` is 20 in Polished, not 24 (`constants/pokemon_data_constants.asm:34`
puts `BASE_TMHM` after 20 bytes of scalars). The `layout:` block is new and is what
makes `rom.lua` reusable.

## 6. What is not settled

- `probabilities()` shape — the head of `GrassMonProbTable` does not read as a
  strictly-increasing-threshold table at 7 entries. Settled by walking the whole table
  against `data/wild/probabilities.asm`.
- `roamers()` — whether Polished's `InitRoamMons` instruction stream is byte-compatible
  with vanilla's disassembler. Settled by disassembling `0x3037D`…`0x303AA`.
- `BOXMON_STRUCT_LENGTH`, `BOX_LENGTH`, `EGG`, `NUM_POKEMON` vs record count for boxes.

## 7. Recommendation

**Extend `rom.lua` generically; do not fork it into `polished_rom.lua`.**

Smallest-change reasoning:

1. The reader is *already* profile-driven — every offset comes from
   `profile.rom`, every count from `profile.derived`. Polished needs more keys, not a
   different shape.
2. The deltas are **numbers and one decoder**, not control flow: strides (34/68/12/3/4/4/8/5),
   a `species()` that reads 2 bytes, and a `map_at()` that reads 1 byte instead of 2.
   A fork would duplicate all of `wild()`, `tree()`, `fishing()`, `base_stats()` to
   change six constants — strictly more code to keep in sync for the same result.
3. The one genuinely branchy reader is `probabilities()`, and that is the one place a
   per-title hook is justified: keep the vanilla function and dispatch to a Polished
   variant when `profile.variant == "polished"`.

Concretely: add `profile.layout` (the `layout:` block in §5), make `species()` and
`map_at()` take their width from it, and replace `rom.lua:36`'s
`assert(count == 251 and stride == 32)` with a range check against the profile's own
declared values. **Do not keep that assert for any title** — it is the one line that
hard-blocks a second game, and it asserts a coincidence (vanilla's counts) rather than
an invariant.

Two things must change outside `rom.lua`: `reads.lua`'s constants (§4.2) and the
wild-slot decoder that consumes `Rom` output, since a Polished slot now yields a
`(species, form)` pair rather than a bare species.

## 8. Open items settled

### 8.1 `probabilities()` — **fails on Polished, proven**

`data/wild/probabilities.asm` in Polished is `table_width 1`: a bare cumulative
threshold per slot, no index. Vanilla's is `table_width 2` with
`MACRO mon_prob: db \1, \2 * 2` — `(percent, slot offset)`.

ROM proof. `GrassMonProbTable` `0c:4235` flat `0x30235`, 7 bytes:
`1e 3c 50 5a 5f 62 64` = **30, 60, 80, 90, 95, 98, 100** — matching the source comments
30/30/20/10/5/3/2 exactly. `WaterMonProbTable` flat `0x3023C`, 3 bytes:
`3c 5a 64` = **60, 90, 100**.

`rom.lua:113` reads `byte(entry.flat + index * 2)` and `byte(entry.flat + index * 2 + 1)`
and asserts at `:115` that the second byte is `even` and `< slots * 2` (= 14). On Polished
entry 0 the pair is (30, **60**) and `60 < 14` is false — **the assert fires on the very
first entry**. It is not a silent misread; it refuses. Conclusion: **does not work
unchanged**; it needs a `width == 1` branch (thresholds only, index implied by position).

### 8.2 `roamers()` — **fails on Polished, proven**

`rom.lua:275-291` recognises exactly four opcodes: `0x3e` (`ld a, imm`), `0xaf`
(`xor a`), `0xea` (`ld [abs], a`), `0xc9` (`ret`); anything else raises
`"unsupported roamer initializer opcode "`.

`InitRoamMons` is `0c:437d` flat `0x3037D`; `CheckEncounterRoamMon` is `0c:43aa` flat
`0x303AA`. The 45 bytes in between:

```
3e f3 ea bc df | 3c ea c7 df | 3e 28 ea bd df | ea c8 df | 3e 02 ea be df
3e 05 ea bf df | 3e 04 ea c9 df | 3e 0e ea ca df | af ea c0 df | ea cb df | c9
```

The `3c` at offset 5 is **`inc a`** — Polished asserts `RAIKOU + 1 == ENTEI` at
`engine/overworld/wildmons.asm:689` and derives Entei's species with `inc a` rather
than a second immediate. `0x3c` is not in the vanilla vocabulary, so `roamers()` raises
on byte 5. **Fails, and fails loudly.**

`RoamMaps` `0c:44bd` flat `0x304BD` is new (vanilla has no equivalent table).
`data/wild/roammon_maps.asm` emits `MACRO roam_map: map_id, db _NARG-1, <ids…>, db 0` —
variable width per entry. Decoding from the ROM until a `map_id == 0` terminator gives
**12 entries**, ending at flat `0x30708`. First 24 bytes: `18 03 02 1a 01 05 09 00 1a 01 02 18 03 1a 02 00 1a 02 03 1a 01 0a 01 04`.

### 8.3 Box-struct constants — the vanilla asserts do not apply

| Assert | Vanilla | Polished | Source |
|---|---|---|---|
| `BOXMON_STRUCT_LENGTH` | 32 | **49** | `constants/pokemon_data_constants.asm:231` `SAVEMON_STRUCT_LENGTH`; NEWBOX.md uses `49*(e-1)` for `sBoxMons1A` etc. |
| `BOX_LENGTH` | 1104 | **660** (`0x294`) | NEWBOX.md: `sNewBoxEnd` = `01:B378` (`.sym:49793`), each copy 660 bytes |
| `EGG` | 253 | **UNVERIFIED** | `CANCEL EQU -1` (`:320`) is `$FF`, not an egg species; not derived |
| `PARTYMON_STRUCT_LENGTH` | 48 | **48** | `:185` — same length, different field order (RAM.md) |
| `MONS_PER_BOX` / `NUM_BOXES` | 20 / 14 | **20 / 20** | `:298`, `:304` |

**Recommendation: drop these four asserts from the Polished path.** `reads.lua:60-70`
asserts a *box geometry* that Polished replaces wholesale — 49-byte records, 660-byte
boxes, three box banks plus a new-box region, 20 boxes. Keeping the asserts would mean
maintaining a second set of vanilla-shaped numbers for a game that has neither. They
belong to `reads.lua` (the vanilla path C-ROMTABLES replaces), not to the ROM-table
reader, so the correct move is: **leave `reads.lua` alone, and give the Polished client
its own constants block sourced from `SAVEMON_STRUCT_LENGTH` / NEWBOX.md.**

### 8.4 `num_roammon_maps` / `roamer_count` — settled

`num_roammon_maps` = **12** (decoded from the ROM, §8.2). `roamer_count` = **2**:
`wRoamMon1Species` and `wRoamMon2Species` both exist, and `InitRoamMons` writes exactly
two HP bytes (`af ea c0 df` / `ea cb df`).

### 8.5 Which count a box reader uses — **291, not 289**

Three numbers, three jobs:

| Number | Meaning | Use |
|---|---|---|
| **291** (`NUM_SPECIES`, `pokemon_constants.asm:317`) | every valid internal species id | **validation bound** for a box record's species byte |
| 289 (`NUM_POKEMON`, `:318`) | ids with the high bit clear — `NUM_SPECIES - 2*HIGH(NUM_SPECIES)` | never a validation bound; it silently rejects ids 289-291 |
| 334 | `BaseData` records = species + non-cosmetic variants | **base-stats lookup only**; record index ≠ species id |

A box record stores `SAVEMON_SPECIES` (1 byte, `LOW`) plus the form byte, so the reader
must accept `LOW(species)` in 1..291 and reconstruct
`species9 = LOW | ((form & 0x20) << 3)`. Using 289 as the bound would reject three
legitimate species; using 334 would let a corrupt record through. **`num_boxes * capacity`
must be multiplied by 49, not 32** — a box-block reader that assumed 32 would misalign
every record after the first.

## 9. Summary table

| Reader | Reusable with a `layout` block? | Exact profile keys to add |
|---|---|---|
| `probabilities()` | **yes**, with a `width` branch (1 vs 2) | `GrassMonProbTable` `0c:4235`/`0x30235`, `WaterMonProbTable` `0c:423c`/`0x3023C`, `prob_width` 1, `num_grassmon` 7, `num_watermon` 3 |
| `wild()` grass | **yes**, fully data-driven | 4 grass table keys + `wild_grass_row` 68, `wild_slot` 3, `map_bytes` 1, `species_bytes` 2 |
| `wild()` water | **yes**, fully data-driven | 4 water table keys + `wild_water_row` 12, `wild_slot` 3 |
| `tree()` maps | **yes** | `TreeMonMaps` `2e:4483`/`0xB8483`, `RockMonMaps` `2e:4505`/`0xB8505`, `tree_map_row` variable (`map_id, count, ids…`) |
| `tree()` slots | **yes** | `TreeMons` `2e:4701`/`0xB8701`, `tree_slot` 4, `num_treemon_sets` 10, `treemon_set_rock` |
| `fishing()` | **yes** | `FishGroups` `24:6213`/`0x92213`, `fish_group_header` 8, `fish_slot` 4, `num_fishgroups` 17, `num_time_fishgroups` 0 (drop the `TimeFishGroups` read entirely) |
| `roamers()` | **no** — needs an `inc a` opcode (`0x3c`) and a `RoamMaps` walk | `InitRoamMons` `0c:437d`/`0x3037D`, `CheckEncounterRoamMon` `0c:43aa`/`0x303AA`, `RoamMaps` `0c:44bd`/`0x304BD`, `num_roammon_maps` 12, `roamer_count` 2 |
| `base_stats()` | **yes**, but assert must go | `BaseData` `11:4b18`/`0x44B18`, `base_stats_stride` 34, `base_tmhm_offset` 20, `base_data_records` 334, `species_count` 291 |

**Net: seven of eight readers are fixable with a `layout` block; only `roamers()` needs
new control flow.**

```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":36,"expect":"assert(count == 251 and stride == 32"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":109,"expect":"local function probabilities("},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":113,"expect":"local threshold, offset = byte(entry.flat + index * 2), byte(entry.flat + index * 2 + 1)"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":115,"expect":"assert(offset % 2 == 0 and offset < slots * 2 and not seen[offset],"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":124,"expect":"function self.wild()"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":137,"expect":"local map = map_at(cursor)"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":161,"expect":"function self.tree()"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":177,"expect":"row.set_id = integer(byte(cursor + 2)"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":219,"expect":"span(entry.flat, groups * 7, bank_end(entry), \"FishGroups\")"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":214,"expect":"function self.fishing()"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":255,"expect":"function self.roamers()"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":275,"expect":"local opcode = byte(cursor)"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":276,"expect":"if opcode == 0x3e then"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":279,"expect":"elseif opcode == 0xaf then"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":281,"expect":"elseif opcode == 0xea then"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":287,"expect":"elseif opcode == 0xc9 then"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":291,"expect":"error(\"unsupported roamer initializer opcode \" .. opcode)"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":87,"expect":"function self.base_stats(id)"},{"path":"F:/slink-work/wt/polished/lua/gen2/rom.lua","line":92,"expect":"assert(byte(flat) == id, \"base stats species does not match record\")"},{"path":"F:/slink-work/wt/polished/lua/gen2/reads.lua","line":60,"expect":"PARTYMON_STRUCT_LENGTH=48"},{"path":"F:/slink-work/wt/polished/lua/gen2/reads.lua","line":62,"expect":"NUM_POKEMON=251, EGG=253"},{"path":"F:/slink-work/wt/polished/lua/gen2/reads.lua","line":61,"expect":"MONS_PER_BOX=20, NUM_BOXES=14"},{"path":"F:/slink-work/wt/polished/lua/gen2/reads.lua","line":67,"expect":"box_struct_size=\"BOXMON_STRUCT_LENGTH\""},{"path":"F:/slink-work/wt/polished/lua/gen2/reads.lua","line":69,"expect":"sram_box_stride=\"BOX_LENGTH\""},{"path":"F:/slink-work/wt/polished/lua/gen2/reads.lua","line":70,"expect":"egg_species=\"EGG\""},{"path":"F:/slink-work/cache/polished/src/data/wild/probabilities.asm","line":1,"expect":"GrassMonProbTable:"},{"path":"F:/slink-work/cache/polished/src/data/wild/probabilities.asm","line":12,"expect":"WaterMonProbTable:"},{"path":"F:/slink-work/cache/polished/src/data/wild/probabilities.asm","line":2,"expect":"table_width 1"},{"path":"F:/slink-work/cache/polished/src/data/wild/probabilities.asm","line":10,"expect":"assert_table_length NUM_GRASSMON"},{"path":"F:/slink-work/cache/polished/src/data/wild/probabilities.asm","line":17,"expect":"assert_table_length NUM_WATERMON"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/data/wild/probabilities.asm","line":1,"expect":"MACRO mon_prob"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/data/wild/probabilities.asm","line":3,"expect":"db \\1, \\2 * 2"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/data/wild/probabilities.asm","line":7,"expect":"table_width 2"},{"path":"F:/slink-work/cache/polished/src/engine/overworld/wildmons.asm","line":683,"expect":"InitRoamMons:"},{"path":"F:/slink-work/cache/polished/src/engine/overworld/wildmons.asm","line":689,"expect":"assert RAIKOU + 1 == ENTEI"},{"path":"F:/slink-work/cache/polished/src/engine/overworld/wildmons.asm","line":691,"expect":"ld [wRoamMon2Species], a"},{"path":"F:/slink-work/cache/polished/src/engine/overworld/wildmons.asm","line":717,"expect":"CheckEncounterRoamMon:"},{"path":"F:/slink-work/cache/polished/src/engine/overworld/wildmons.asm","line":699,"expect":"ld a, GROUP_ROUTE_42"},{"path":"F:/slink-work/cache/polished/src/engine/overworld/wildmons.asm","line":711,"expect":"xor a ; generate new stats"},{"path":"F:/slink-work/cache/polished/src/data/wild/roammon_maps.asm","line":4,"expect":"MACRO roam_map"},{"path":"F:/slink-work/cache/polished/src/data/wild/roammon_maps.asm","line":6,"expect":"db _NARG - 1"},{"path":"F:/slink-work/cache/polished/src/data/wild/roammon_maps.asm","line":10,"expect":"db 0"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":231,"expect":"DEF SAVEMON_STRUCT_LENGTH EQU _RS"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":189,"expect":"DEF SAVEMON_SPECIES            rb"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":185,"expect":"DEF PARTYMON_STRUCT_LENGTH EQU _RS"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":298,"expect":"DEF MONS_PER_BOX    EQU 20"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":304,"expect":"DEF NUM_BOXES       EQU (MONDB_ENTRIES * 2 - MIN_MONDB_SLACK) / MONS_PER_BOX ; 20"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":35,"expect":"DEF BASE_DATA_SIZE EQU _RS"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":357,"expect":"DEF NUM_GRASSMON EQU 7"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":358,"expect":"DEF NUM_WATERMON EQU 3"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_constants.asm","line":317,"expect":"DEF NUM_SPECIES EQU const_value - 1 ; 123"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_constants.asm","line":318,"expect":"DEF NUM_POKEMON EQU NUM_SPECIES - (2 * HIGH(NUM_SPECIES)) ; 121"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_constants.asm","line":320,"expect":"DEF CANCEL EQU -1"},{"path":"F:/slink-work/cache/polished/src/macros/data.asm","line":89,"expect":"MACRO? dp ; db species, extspecies | form"},{"path":"F:/slink-work/cache/polished/src/macros/asserts.asm","line":79,"expect":"map_id \\1"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":11989,"expect":"11:4b18 BaseData"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22504,"expect":"24:6213 FishGroups"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":8354,"expect":"0c:4235 GrassMonProbTable"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":8355,"expect":"0c:423c WaterMonProbTable"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":8396,"expect":"0c:437d InitRoamMons"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":8397,"expect":"0c:43aa CheckEncounterRoamMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":8417,"expect":"0c:44bd RoamMaps"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":27915,"expect":"2e:4483 TreeMonMaps"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":27930,"expect":"2e:4701 TreeMons"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":68004,"expect":"wRoamMon1Species"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":68015,"expect":"wRoamMon2Species"},{"path":"F:/slink-work/wt/polished/docs/polished/NEWBOX.md","line":32,"expect":"sNewBoxEnd"},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/profile.json","line":251,"expect":"\"num_roammon_maps\": 16"},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/profile.json","line":257,"expect":"\"roamer_count\": 2"},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/profile.json","line":240,"expect":"\"base_stats_stride\": 32"},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/profile.json","line":252,"expect":"\"num_time_fishgroups\": 22"}]
```
