# Radical Red 4.1 flash-save layout — gen3-P2-C2-8

Research date: 2026-09-21. This note **pins from the RR binary and a real RR battery save**
what [flash_save.md §3](flash_save.md) could only quote from upstream CFRU. Every `[ROM]` fact
below was read out of the admitted ROM; every `[SAVE]` fact out of
`tests/fixtures/gen3/rr_town.sav`. `†UNVERIFIED` marks what neither source settles — §7.

Artefacts:

- ROM (base): `E:/Google Drive/SLink/Pokemon - Radical Red.gba`,
  32 MiB, sha256 `679d112cdfe699c2…`, header title `POKEMON FIREBPRE`.
- ROM (companion): `patch/build/slink_RR.gba`, sha256 `1e8f6e8957c1e8eb…`.
  **Every table cited here is byte-identical in both ROMs** — the SLink companion patch does
  not touch the save layout.
- Save: `tests/fixtures/gen3/rr_town.sav`, 0x20000 bytes, no RTC suffix, slot 0, counter 2,
  rotation 2, trainer `B` #2BDDC8BF, party = 1 × species 277 level 6.

File offsets are ROM-file offsets; GBA addresses are `0x08000000 + offset`.

## 1. The chunk table `[ROM]`

**ROM file 0x1148BF0 = address 0x09148BF0.** 14 entries × 4 bytes, `{u16 offset, u16 size}` —
*not* CFRU's `{void* data; u16 size}`: RR stores the object-relative offset, and the base
pointer is applied by the writer. That is why a stride-8 pointer/size search finds nothing.

Verbatim (as u16 pairs, little-endian):

```
1148BF0  00 00 24 0F  00 00 F0 0F  F0 0F F0 0F  E0 1F F0 0F
1148C00  D0 2F 98 0D  00 00 F0 0F  F0 0F F0 0F  E0 1F F0 0F
1148C10  D0 2F F0 0F  C0 3F F0 0F  B0 4F F0 0F  A0 5F F0 0F
1148C20  90 6F F0 0F  80 7F 50 04
```

| id | object | offset | size | id | object | offset | size |
|---|---|---|---|---|---|---|---|
| 0 | SaveBlock2 | 0x0000 | 0x0F24 | 7 | PokemonStorage | 0x1FE0 | 0x0FF0 |
| 1 | SaveBlock1 | 0x0000 | 0x0FF0 | 8 | PokemonStorage | 0x2FD0 | 0x0FF0 |
| 2 | SaveBlock1 | 0x0FF0 | 0x0FF0 | 9 | PokemonStorage | 0x3FC0 | 0x0FF0 |
| 3 | SaveBlock1 | 0x1FE0 | 0x0FF0 | 10 | PokemonStorage | 0x4FB0 | 0x0FF0 |
| 4 | SaveBlock1 | 0x2FD0 | 0x0D98 | 11 | PokemonStorage | 0x5FA0 | 0x0FF0 |
| 5 | PokemonStorage | 0x0000 | 0x0FF0 | 12 | PokemonStorage | 0x6F90 | 0x0FF0 |
| 6 | PokemonStorage | 0x0FF0 | 0x0FF0 | 13 | PokemonStorage | 0x7F80 | 0x0450 |

This is **exactly** upstream CFRU's table (`Skeli789/Complete-Fire-Red-Upgrade` b637a27,
`src/save.c#L17-L55`) and exactly `slot_layout(CHUNK_SIZE_CFRU)` — the `SAVEBLOCK_CHUNK` macro
with a 0xFF0 chunk and the vanilla object sizes 0xF24 / 0x3D68 / 0x83D0. The id→object
assignment is `[ROM]`-consistent (the offset counter restarts at ids 1 and 5) and
`[SAVE]`-confirmed by §3.

`[SAVE]` falsifier for the vanilla table: sector 3 (id 1) has checksum 0x83E7, which matches a
0xFF0 sum and **not** a 0xF80 one; sector 6 (id 4) matches 0xD98 and not vanilla's 0xEE8;
sector 1 (id 13) matches 0x450 and not vanilla's 0x7D0. `qualify_flash(cfru=False)` refuses
this save.

## 2. Object base addresses `[ROM]`

Literal pool at ROM file 0x4C08C (the save-block pointer setter):

| file | value | meaning |
|---|---|---|
| 0x4C08C | 0x03005008 | `gSaveBlock1Ptr` |
| 0x4C090 | 0x0300500C | `gSaveBlock2Ptr` |
| 0x4C094 | 0x02024588 | **gSaveBlock2**, 0x0F24 → ends 0x020254AC |
| 0x4C098 | 0x0202552C | **gSaveBlock1**, 0x3D68 → ends 0x02029294 |
| 0x4C09C | 0x03005010 | `gPokemonStoragePtr` |
| 0x4C0A0 | 0x02029314 | **gPokemonStorage**, 0x83D0 → ends 0x020316E4 |

So a disk chunk of object *X* at offset *o* is the RAM image of `base(X) + o`. Every
box/name/wallpaper address below is converted to a disk offset with these three bases, and
every conversion lands where the real save actually has bytes (§3) — which is the cross-check
that validates the bases.

## 3. The 25 boxes, names and wallpapers `[ROM]` + `[SAVE]`

RR keeps **25 boxes of 30 compressed 0x3A-byte records** (stride 0x6CC per box). Three ROM
pointer tables give the live address of every box, name and wallpaper; they sit consecutively:

| table | ROM file | GBA | entries |
|---|---|---|---|
| box data | 0x1148930 | 0x09148930 | 25 × u32 |
| box name | 0x1148994 | 0x09148994 | 25 × u32 |
| box wallpaper | 0x11489F8 | 0x091489F8 | 25 × u32 |

The box-data table is byte-identical to `data/games/gen3_rr/profile.json`
`CFRU_BOX_BASES` — the profile's RAM bases are now ROM-pinned, not mirrored from CFRU.

**25 × 30 × 0x3A = 0xA9EC does not fit the 0x83D0 PokemonStorage**, so RR scatters the boxes
into the free tails of the three save objects plus a repurposed extension region:

| box | RAM | disk |
|---|---|---|
| 1–19 | 0x02029318 + (b−1)·0x6CC | storage **+0x0004** + (b−1)·0x6CC, ending 0x8128 (ids 5–13) |
| 20 | 0x0203CB44 | extension +0x0B0C — **spans physical sectors 30→31** (0x4E4 B + 0x1E8 B) |
| 21 | 0x0203D210 | extension +0x11D8 (sector 31 +0x01E8) |
| 22 | 0x0203D8DC | extension +0x18A4 (sector 31 +0x08B4) |
| 23 | 0x02027434 | **SaveBlock1 +0x1F08** (ids 2–3) |
| 24 | 0x02027B00 | **SaveBlock1 +0x25D4** (id 3) |
| 25 | 0x02024638 | **SaveBlock2 +0x00B0** (id 0) |

19 × 0x6CC = 0x8124, so boxes 1–19 exactly fill `storage[0x0004 … 0x8128)`.

Names and wallpapers are split the same way, and the split is **visible in the real save**:

| what | disk range | `[SAVE]` |
|---|---|---|
| names, boxes 15–25, **descending** (Box25 first) | storage 0x82E1 … 0x8343 (11 × 9) | non-zero, decodes `Box25`…`Box15` |
| names, boxes 1–14, ascending | storage 0x8344 … 0x83C1 (14 × 9) | non-zero, decodes `Box1`…`Box14` |
| wallpapers, boxes 15–25, ascending | storage 0x8128 … 0x8132 (11 × 1) | `0C 0D 00 01 00 01 04 05 04 05 08` |
| wallpapers, boxes 1–14, ascending | storage 0x83C2 … 0x83CF (14 × 1) | `00 01 00 01 04 05 04 05 08 09 08 09 0C 0D` |

Those four runs are the **only** non-zero bytes in the whole reconstructed 0x83D0 storage
object, which is the receipt that (a) the storage chunk table is right, (b) the box *records*
in `storage[0x4…0x8128)` are genuinely empty in this save, and (c) RR really does keep 25
boxes with the vanilla 14-box name/wallpaper arrays left in place.

## 4. The parasite payload `[ROM]` + `[SAVE]`

CFRU's parasite is real in RR and byte-pinned. Literal pools at ROM file 0x10B8C98 and
0x10B8DEC (the save and load halves) hold, in order:

```
0203B174  parasite base                     0203B240  = base + 0xCC
0203B498  = base + 0x324                    02039A38  (unrelated buffer)
0203C038  extension sector 30 source        0203D028  extension sector 31 source
```

The dispatcher at ROM file 0x10B8D30 switches on the section id — `cmp r2,#4`, `cmp r2,#0xD`,
`cmp r2,#0` — and the immediates `22CC` (0xCC), `2296`+`0092` (0x96 ≪ 2 = 0x258) and
`22BA`+`0112` (0xBA ≪ 4 = 0xBA0) give the three piece lengths:

| section id | chunk size | parasite piece | sector range | parasite offset |
|---|---|---|---|---|
| 0 | 0x0F24 | 0x00CC | 0x0F24 … 0x0FEF | 0x0000 … 0x00CB |
| 4 | 0x0D98 | 0x0258 | 0x0D98 … 0x0FEF | 0x00CC … 0x0323 |
| 13 | 0x0450 | 0x0BA0 | 0x0450 … 0x0FEF | 0x0324 … 0x0EC3 |

Each piece ends at 0x0FEF, immediately before the 12-byte footer at 0x0FF4; total
0xCC + 0x258 + 0xBA0 = 0xEC4 = the parasite block length. The **section checksum covers only
the chunk size**, never the parasite: `[SAVE]` sector 6 (id 4) has non-zero bytes out to
0x0F01 and sector 1 (id 13) out to 0x0892, yet both checksums verify over 0xD98 and 0x450
respectively. Nothing anywhere in the save is non-zero in 0x0FF0 … 0x0FF3.

## 5. Physical sectors 28–31 `[SAVE]`

| sectors | state in the real save | reading |
|---|---|---|
| 28, 29 | every byte 0xFF, id/checksum/signature/counter all 0xFF… | Hall of Fame **never written**; RR does not use them |
| 30, 31 | all zero except one byte at 30+0x071F; footer id/checksum/signature/counter = 0 | written from a **zeroed** 0x1000 buffer with 0xFF0 bytes of RAM and **no section metadata** |

That is exactly CFRU's extension write, and it is what makes boxes 20–22 recoverable: the
extension is the contiguous RAM range 0x0203C038 … 0x0203E018 (0x1FE0 = 2 × 0xFF0), sector 30
first. It carries **no signature and no checksum**, and it is **not** part of the rotating
two-slot scheme: there is one copy, shared by both slots.

## 6. Party `[SAVE]`

RR saves the party in the vanilla SaveBlock1 place: count at **SB1+0x34**, records at
**SB1+0x38**, 100 bytes each, vanilla `struct Pokemon` field layout but with CFRU's
**unencrypted, fixed-order** substructs and a zero BoxPokemon checksum
(`decode_party_mon(rr=True)`). The fixture's single record decodes to PID 0xEBEF11DA, OTID
0x2BDDC8BF, nickname `Treecko`, OT `B`, species 0x0115 = 277, level 6, moves 1/43/71/0, PP
35/30/25/35, all IVs 31, met level 5 — every field self-consistent, which is what proves the
offset at the *disk-chunk* level (flash_save.md §3's open question).

`data/games/gen3_rr/profile.json` `PARTY_IN_SB1 = false` refers to the **live RAM** party
(0x02024244); the saved shadow at SB1+0x38 is what the disk carries.

## 7. †UNVERIFIED

- **No boxed Pokémon exists in the fixture.** Every one of the 25 boxes is empty, so the
  *record* placement inside a box (slot stride 0x3A, 30 slots) is arithmetic from the ROM
  table's 0x6CC stride, not a decoded receipt. `boxsync`'s box-24-slot-29 deposit is not in
  either slot of this save. A fixture with a boxed mon in box 19 (storage), box 20 (sector
  30→31 straddle), box 23/24 (SB1) and box 25 (SB2) would close this.
- **Extension generation coupling.** Sectors 30/31 are single-copy and unauthenticated, so an
  image whose rotating slot was recovered from the *older* counter carries the *newer*
  boxes 20–22. There is no way to detect that from the image; `rr_boxes_from_save` reports it
  as a caveat and refuses only when 30/31 are erased.
- **Parasite semantics.** The three pieces are pinned, but *what* the 0xEC4 block holds is not
  decoded here. It is preserved verbatim, never rewritten.
- **Custom signature / signed counter.** RR uses the vanilla 0x08012025 signature `[SAVE]`
  (all 28 rotating sectors). Whether RR's selector compares the counter signed, as CFRU's does
  (flash_save.md §3), is not established; it cannot matter below 0x80000000.
- **Name/wallpaper writers.** The name and wallpaper tables are read out of the ROM but the
  codec does not decode or write them; the ordering quirk (names for boxes 15–25 run backwards
  from 0x8343) is recorded here only.
- **No emulator was run.** No save was written by RR under observation; this is a ROM+image
  reading, so the *write* path (rotation, damaged-sector handling, extension ordering) is
  inferred from the resulting bytes only.
