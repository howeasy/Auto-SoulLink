# Polished Crystal v3.2.3 PC storage ("newbox"): reader/writer spec

The spec for a BizHawk Lua reader/writer of Polished's PC boxes. Pinned build: `data/polished/build_provenance.json`
(tag v3.2.3, commit `3fa43192`, ROM sha1 `6930b48a…`). Sources: `F:/slink-work/cache/polished/src` (code wins over
`docs/newbox_format.md`, which is stale; see §8) and `data/polished/polishedcrystal.sym`. Citations are
`file:line`; every one appears in the CLAIMS block at the end. Anything not confirmed is marked **UNVERIFIED**.

**Flat CartRAM offset.** BizHawk `CartRAM` holds the 4 SRAM banks back to back, so `flat = bank*0x2000 + (addr - 0xA000)`.
This is the mapping `lua/gen2/boxes.lua` already uses (32 KiB domain). Polished uses 4 banks too.

---

## 1. SRAM map

### 1.1 Box metadata: 20 records, two copies

`sNewBox1..20` hold the **gameplay** copy and `sBackupNewBox1..20` the **saved** copy (`sram.asm:141`, `sram.asm:146`).
Each record is the `newbox` macro, 33 bytes (0x21):

| off | size | field | source |
|---|---|---|---|
| +0x00 | 20 | `Entries`: pokedb entry index per slot, `0` = empty, `1..207` = entry | `macros/ram.asm:143` |
| +0x14 | 3 | `Banks`: `flag_array MONS_PER_BOX`, bit (slot-1) set = pokedb bank 2, clear = bank 1 | `macros/ram.asm:144` |
| +0x17 | 9 | `Name`: box name, charmap bytes, `'@'`-terminated if shorter than 9, no terminator at 9 | `macros/ram.asm:145`, `text_constants.asm:4` |
| +0x20 | 1 | `Theme` | `macros/ram.asm:146` |

| copy | box 1 | box n (1-based) | flat | sym |
|---|---|---|---|---|
| gameplay `sNewBox` | `01:B0E4` | `01:B0E4 + 0x21*(n-1)` | `0x30E4 + 0x21*(n-1)` | `.sym:49691` |
| saved `sBackupNewBox` | `01:B378` | `01:B378 + 0x21*(n-1)` | `0x3378 + 0x21*(n-1)` | `.sym:49791` |

`sNewBoxEnd` = `01:B378` (`.sym:49793`), so each copy is 660 bytes (0x294). A save copies all 660 (§5).

Bank bit layout (FlagPredef: byte `(slot-1)>>3`, bit `(slot-1)&7`, LSB first): `Banks[0]` bit0 = slot 1 … bit7 = slot 8,
`Banks[1]` = slots 9-16, `Banks[2]` bits 0-3 = slots 17-20. The bank bit of an empty slot is junk (release leaves it as is), so ignore it.
Slots go left to right, top to bottom, 4 per row. **Boxes can have holes**: there is no count byte and no compaction.

Slot coordinates in the engine are **1-based box `b` (1..20) and 1-based slot `c` (1..20)**. Box 0 means the party (§2).
`wCurBox` is 0-based (`.sym` `01:DB7A`, see RAM.md). It decides only which box the PC opens on. It plays **no part in durability**,
unlike vanilla, where only the current box sits in the volatile `sBox` (`boxes.lua:109`).

### 1.2 PokeDB: 2 banks × 207 entries, 6 sections

`MONDB_ENTRIES_A = 167` (`pokemon_data_constants.asm:299`), B = 28, C = 12, total 207 per bank. `NUM_BOXES` is derived
from it as 20 (`pokemon_data_constants.asm:304`). Sections: `sram.asm:152`, `sram.asm:162`, `sram.asm:172` (and their `2x` twins).

| pokedb bank `d` | entry `e` | section | SRAM bank:addr of entry | flat | sym |
|---|---|---|---|---|---|
| 1 | 1..167 | `sBoxMons1A` | `02:A000 + 49*(e-1)` | `0x4000 + 49*(e-1)` | `.sym:50810` |
| 1 | 168..195 | `sBoxMons1B` | `00:A000 + 49*(e-168)` | `0x0000 + 49*(e-168)` | `.sym:46732` |
| 1 | 196..207 | `sBoxMons1C` | `01:B60C + 49*(e-196)` | `0x360C + 49*(e-196)` | `.sym:49892` |
| 2 | 1..167 | `sBoxMons2A` | `03:A000 + 49*(e-1)` | `0x6000 + 49*(e-1)` | `.sym:57159` |
| 2 | 168..195 | `sBoxMons2B` | `00:ABF1 + 49*(e-168)` | `0x0BF1 + 49*(e-168)` | `.sym:48151` |
| 2 | 196..207 | `sBoxMons2C` | `01:B858 + 49*(e-196)` | `0x3858 + 49*(e-196)` | `.sym:50351` |

The `OpenPokeDB` routine (`bills_pc.asm:705`) picks the table: `pokedb_section` stores `BANK(sect)` plus
`sect - base*49` (`bills_pc.asm:740`). The table order is A, C, B (`bills_pc.asm:748`, `bills_pc.asm:749`, `bills_pc.asm:750`),
and the entry address is `ptr + 49*(e-1)`. I checked the ends against the sym: 1A ends `02:BFF7`, 1B ends `00:A55C`,
1C ends at `01:B858` (where 2C starts), 2C ends `01:BAA4`, and 2B ends `00:B14D`.
An entry not referenced by any box (active or backup) is garbage. Never scan the pokedb directly.

### 1.3 `savemon_struct`: 49 bytes

`macros/ram.asm:94`. The offsets match the `.sym` field labels of `sBoxMons1AMon1` (`02:A000`..`A031`, `.sym:50849`).
I also checked the `SAVEMON_*` rsreset block in `pokemon_data_constants.asm` and it matches. The known-wrong block is
the `MON_*` party one; RAM.md §2.1 has those numbers.

| off | size | field | notes |
|---|---|---|---|
| 0 | 1 | Species | low 8 bits of the 9-bit species |
| 1 | 1 | Item | |
| 2 | 4 | Moves | |
| 6 | 2 | OT ID | same byte order as `wPlayerID` (big-endian, as vanilla) |
| 8 | 3 | Exp | big-endian (as vanilla) |
| 11 | 6 | EVs | HP, Atk, Def, Spe, SAt, SDf, 1 byte each |
| 17 | 3 | DVs | nibbles HP/Atk, Def/Spe, SAt/SDf |
| 20 | 1 | Personality | shiny bit7 (`:235`), ability bits 5-6 (`:236`), nature bits 0-4 (`:237`) |
| 21 | 1 | Form byte | gender bit7 (`:242`), is-egg bit6 (`:243`), **ext-species bit5** (`:244`), form bits 0-4 (`:245`) |
| 22 | 1 | PPUps | `DDCCBBAA` (A = move 1). Encoded from the 4 party PP bytes (`macros/ram.asm:119`) |
| 23 | 1 | Happiness / egg cycles | party +26 |
| 24 | 1 | Pokérus | party +27 |
| 25 | 1 | Caught time/ball | time bits 5-6, ball bits 0-4 (party +28) |
| 26 | 1 | Caught level | party +29 |
| 27 | 1 | Caught location | party +30 |
| 28 | 1 | Level | party +31 |
| 29 | 3 | Extra | = party OT bytes 8..10 (`macros/ram.asm:128`). Byte 29 & `%11111100` is hyper training (`bills_pc.asm:991`) |
| 32 | 10 | Nickname | 7-bit encoded, **MSB = checksum bit** (`macros/ram.asm:129`) |
| 42 | 7 | OT name | 7-bit encoded, **MSB = checksum bit** (`macros/ram.asm:130`) |

(`:2xx` = `constants/pokemon_data_constants.asm`.) **9-bit species** = `byte0 | (((byte21 >> 5) & 1) << 8)`.
That is `ConvertFormToExtendedSpecies` (`home/pokemon.asm:408`: `and EXTSPECIES_MASK; swap a; rra`). Form = `byte21 & 0x1F`.
Bytes 0-21 equal party_struct bytes 0-21. Party bytes 22-25 (4 PP) collapse into byte 22, which shifts party 26-31 down by 3.

---

## 2. Box slot → pokedb entry

`GetStorageBoxPointer` (`bills_pc.asm:455`), for box `b` ≥ 1 and slot `c`:

```
rec  = sNewBox1 + 0x21*(b-1)            ; b==0 crashes with ERR_NEWBOX (party is not a box)
e    = rec.Entries[c-1]                 ; 0 = empty slot
d    = 1 + ((rec.Banks[(c-1)>>3] >> ((c-1)&7)) & 1)   ; bills_pc.asm:490 "inc d" when the bit is set
addr = section table of §1.2 for (d, e)
```

Reading also needs the WRAM **allocation flag**. `GetStorageMon` (`bills_pc.asm:1342`) first calls `IsStorageUsed`
(`bills_pc.asm:1350`). If bit `(e-1)` of `wPokeDB{d}UsedEntries` is clear, the slot reads as **empty**, whatever SRAM holds.

| flags | bank:addr | size | sym |
|---|---|---|---|
| `wPokeDB1UsedEntries` | `02:D8B7` (WRAMX bank 2) | 26 bytes (207 bits) | `.sym:68279` |
| `wPokeDB2UsedEntries` | `02:D8D1` | 26 bytes | `.sym:68282` |

These flags exist only in WRAM. `FlushStorageSystem` (`bills_pc.asm:421`) clears them, then sets the bit for every pointer
in **both** the active and backup records (`bills_pc.asm:451`: `cp NUM_BOXES * 2 ; current + backup`). Flush runs on load
(`LoadStorageSystem`, `save.asm:215`), and again whenever a free entry runs out. Allocation sets a bit. Removal never clears one.
So between flushes the flags are a superset of the referenced set. BizHawk access: `System Bus 0xD8B7` while `SVBK (FF70)&7 == 2`,
or the `WRAM` domain at `0x2000 + (addr-0xD000)` = `0x28B7` / `0x28D1` (**UNVERIFIED**: Gambatte WRAM domain layout).

---

## 3. Per-entry checksum (Bad Egg guard)

The routines are `EncodeTempMon` (`bills_pc.asm:756`), which falls through into `ChecksumTempMon` (`bills_pc.asm:823`), and
`DecodeTempMon` (`bills_pc.asm:887`). The game works on a 49-byte buffer `E`, the encoded entry exactly as stored in SRAM.

### 3.1 Name encoding (before the checksum)

Bytes `E[32..48]` (10 nickname + 7 OT) are mapped by `.charmap_loop`. A byte equal to `' '` ($7F, `charmap.asm:93`) becomes
$7A, `'@'` ($53, `charmap.asm:43`) becomes $7B, and `<START>` ($00) becomes $7C. Every other byte becomes `b & 0x7F`.
The literal is `ld c, $7a | ~%01111111` (`bills_pc.asm:804`), i.e. $FA/$FB/$FC before the MSB is stripped.
Decode does `b | 0x80` and then maps $FA→`' '`, $FB→`'@'`, $FC→$00 (`bills_pc.asm:906`: `sub $fa`). After that the
nickname gets a `'@'` at [10] and the OT a `'@'` at [7]. Charmap $FA-$FC are box-drawing glyphs, so they never collide in names.

### 3.2 Checksum, exact

```
sum = 127                                   ; bills_pc.asm:829  "ld hl, 127"
for i in 0..31:  sum += E[i]          * (i+1)   ; pass 1: lb de, SAVEMON_NICKNAME, 0 (bills_pc.asm:830)
for i in 32..48: sum += (E[i] & 0x7F) * (i+2)   ; pass 2: d = $80|17 (bills_pc.asm:837), e NOT reset
sum &= 0xFFFF
for k in 0..16:                                  ; .WriteChecksum
    E[32+k] = (E[32+k] & 0x7F) | (((sum << k) >> 15) & 1) << 7   ; bit 15-k, k=16 -> 0
valid  <=>  no byte changed                      ; "or %10000000" bills_pc.asm:855
```

How it falls out of `.DoChecksum` (`bills_pc.asm:868`): each step runs `inc e; dec d` and stops when `bit 6, d`
(`bills_pc.asm:871`) is set. Pass 1 runs d = 31..0, multipliers e = 1..32, bytes 0-31. That covers the box data **and the 3 Extra bytes**,
at full 8 bits. Pass 1 exits with e = 33, then pass 2's first `inc e` makes 34. That is the skipped multiplier the source comment
admits to ("originally a mistake"). Pass 2 has d bit 7 set, so each byte is masked `and %01111111` (`bills_pc.asm:877`).
The multiply is `rst AddNTimes` (`bills_pc.asm:883`), `hl += byte*e` mod 65536. The 17th MSB (`E[48]`) must be 0. A set bit
there also counts as invalid. The checksum ignores the slot's location, so an entry can be copied to any (d,e) without re-sealing.

### 3.3 Test vector (derived by hand, then checked)

Entry: species `01`, level `E[28]=05`, every other data byte `00`. Nickname `"A"` + 9×`'@'` ($80,$53…), OT `"B"` + 6×`'@'`.
- encoded names: `00 7B 7B 7B 7B 7B 7B 7B 7B 7B | 01 7B 7B 7B 7B 7B 7B`
- pass 1: `127 + 1*1 + 5*29 = 273`
- pass 2: `0*34 + 0x7B*(35+…+43) + 1*44 + 0x7B*(45+…+50) = 123*(351+285) + 44 = 78272`
- `273 + 78272 = 78545`, then `& 0xFFFF` = `13009` = **`0x32D1`** = `0011 0010 1101 0001`
- stored `E[32..48]` = **`00 7B FB FB 7B 7B FB 7B FB FB 01 FB 7B 7B 7B FB 7B`**

`F:/slink-work/tmp/newbox_checksum.py` checks this vector two ways. One is a register-level transcription of
`.DoChecksum` + `_AddNTimes` + `.WriteChecksum`. The other is the closed formula above. The script asserts both give `0x32D1`
and the sealed bytes, that the two agree on 2000 random entries, that a sealed entry re-verifies clean, and that flipping one
data bit or setting `E[48]`'s MSB is caught. Output: `checksum 0x32D1 ok; sealed names: 00 7B FB FB 7B 7B FB 7B FB FB 01 FB 7B 7B 7B FB 7B`.

---

## 4. What the engine does

- **Read** (`GetStorageMon`): if the flag is clear, the slot is empty. Otherwise it copies 49 bytes to `wEncodedTempMon`, runs
  `DecodeTempMon`, and expands into `wTempMon` (PP restored, stats recalculated, status 0, HP full, eggs at 0 HP).
- **Bad Egg**: `DecodeTempMon` recomputes the checksum. On any mismatch it replaces `wTempMon` with `BadEggRLE`
  (`bills_pc.asm:975`: Unown-? egg, Hidden Power, level 1, named "Bad Egg") and returns carry. It **never writes SRAM** on a read.
  But a later re-encode of that `wTempMon` makes the Bad Egg permanent: a withdraw, or a PC item give/take through
  `UpdateStorageBoxMonFromTemp` (`bills_pc.asm:495`).
- **Deposit (party→box)**: `SwapStorageBoxSlots` allocates a fresh entry with `NewStoragePointer` (first clear flag:
  bank 1 e=1..207, then bank 2, `bills_pc.asm:409`). `AddStorageMon` (`bills_pc.asm:672`) sets the flag, encodes, seals,
  and writes the 49 bytes. Then `SetStorageBoxPointer` (`bills_pc.asm:539`) writes `Entries[c-1]=e` and the bank bit, and the
  party slot takes the box's old pointer: 0 removes it and shifts the party up. With no free entry it returns
  "save required" and the PC forces a save.
- **Withdraw (box→party)**: the box slot gets pointer 0 and the decoded mon is copied into the party. The old entry is
  **not** freed. Its flag stays set, and the backup record still points at it until the next save.
- **Box↔box move**: `.box_swap` (`bills_pc.asm:229`) swaps two pointers. No pokedb write, no checksum, no flag change.
- **Release**: `RemoveStorageBoxMon` (`bills_pc.asm:535`) sets `Entries[c-1]=0` (`bills_pc.asm:537`). Bank bit and pokedb
  bytes are left alone. `bills_pc_ui.asm:2745` reaches it after a roamer-respawn check.
- **Any edit of a boxed mon** (item, nickname, evolution…) goes through `UpdateStorageBoxMonFromTemp`. That routine zeroes the
  slot, allocates a **new** entry, writes it, and repoints. Entries are copy-on-write, so the entry the backup references stays intact.

---

## 5. Save integrity and durability

- `SAVE_VERSION = 10` (`misc_constants.asm:20`) is stored **big-endian** at `sSaveVersion` `00:ABE2` (`sram.asm:3`).
  The high byte goes first (`save.asm:730`), so the bytes are `00 0A`.
- `sChecksum` `01:AD0D` (`sram.asm:31`, `.sym:49237`) is a 16-bit byte sum (`Checksum`, `save.asm:620`) over
  `sGameData..sGameDataEnd` = `01:A008..01:AB82`, 0xB7B bytes (`save.asm:322`, `.sym:49234`). It is stored little-endian (`e` then `d`).
  `sBackupChecksum` `00:BF0D` (`sram.asm:58`, `.sym:49226`) does the same over `00:B208..00:BD82`.
  **Neither range touches box metadata or the pokedb.** Box edits need no save-checksum fix. Their only integrity check is the per-entry checksum.
- **Edited in place, no WRAM copy.** The engine reads and writes `sNewBox` and the pokedb in SRAM directly
  (`GetStorageBoxPointer`/`SetStorageBoxPointer`). Only the allocation flags live in WRAM.
- **Flush points.** `SaveGameData` writes the main data and checksum, then `WriteBackupSave`. That runs `SaveStorageSystem`,
  which copies `sNewBox1..sNewBoxEnd` → `sBackupNewBox1` (660 bytes, `save.asm:232`), then the backup game data.
  `sWritingBackup` (`sram.asm:5`, `.sym:48147`, `00:ABE5`) is 1 while that runs. `wGameLogicPaused` (`00:CEB9`, `.sym:65477`)
  is 1 for the whole save (`save.asm:64`).
- **On Continue**, `LoadStorageSystem` (`save.asm:215`) copies **backup → gameplay** and flushes the flags. So:
  a gameplay-record edit is **volatile until the next native save** (a reset discards it), and a backup-record edit is
  durable at once. Pokedb entry bytes are durable as soon as they are written, but they only matter while some record points at them.
  (If a save is cut off mid-backup with a valid main save, the load first copies gameplay → backup, then backup → gameplay.)

---

## 6. SLink operations (minimal, safe)

**Preconditions for every write**: `wGameLogicPaused == 0`, `sWritingBackup ~= 1`, the existing overworld safe state
(`wScriptRunning`, RAM.md), and the **PC UI closed**. The PC caches icons and the held cursor mon (**UNVERIFIED**: no PC-open
predicate measured). Do the 49-byte entry first, the flag second, and the pointer last, so a torn write never points at garbage.

### 6.1 Enumerate boxed mons (read-only)

```
for b in 1..20: rec = 0x30E4 + 0x21*(b-1)                 ; gameplay copy = what the game shows
  for c in 1..20:
    e = CartRAM[rec + c-1]; if e == 0: empty
    if e > 207: corrupt pointer (InitializeBoxes would zero it), skip
    d = 1 + bit(c-1) of CartRAM[rec+0x14 .. +0x16]
    if flag(d,e) clear: the game shows empty -> report "unflagged", skip
    E = 49 bytes at flat(d,e)                               ; §1.2
    if checksum(E) mismatch: the game shows a Bad Egg -> report bad_egg
    species = E[0] | ((E[21]>>5)&1)<<8 ; form = E[21]&0x1F ; egg = E[21]&0x40
    level = E[28] ; ot_id = E[6..7] ; dvs = E[17..19] ; personality = E[20]
    nickname = decode(E[32..41]) up to '@' ; ot = decode(E[42..48]) up to '@'
```

An offline `.sav` should be read from the **backup** records (`0x3378`). The gameplay copy differs from it only when edits happened after the last save.

### 6.2 Move a mon to the memorial box (vanilla `ops.memorialize`, boxed path)

This is a pure pointer move, the same as `.box_swap`. Set `M = 20` (vanilla used the last box, `NUM_BOXES-1`; Polished
has 20, so its last box is 20. **Owner ruling needed** if a different box is meant).

1. Find the source `(b,c)` holding `(d,e)` by key in the gameplay records, and an empty memorial slot `m` (`Entries[m-1]==0`).
   If none is empty: "memorial box full".
2. Write `Entries_M[m-1] = e`, and set the bank bit `m-1` to `d==2`. Then write `Entries_b[c-1] = 0`.
3. Leave the pokedb, checksum and flags alone: the entry stays referenced and flagged.

**Durability**: these are gameplay-record edits, so a reset reverts both together. You get the pre-move state, never a loss
and never a duplicate, which is stronger than vanilla's two-box copy. It becomes durable at the next native save, the same way
vanilla's `LOADBOX_REVERTS_ACTIVE_EDIT` does. For immediate durability, apply the same move to the **backup** record
by identity. Locate `(d,e)` in the backup records, because the slot indices there can differ, and use the backup memorial box's
own empty slot. That is safe because flush protects backup references (`bills_pc.asm:451`). The catch: if the mon reached the
box from the party after the last save, the saved party still holds it, so a reset gives a duplicate (never a loss). That matches
vanilla's deferred-withdraw semantics. A party mon must first go to a box (§6.3, entry built from the party record), then follow the vanilla party path.

### 6.3 Insert a partner's mon

1. Build `E` (49 bytes):
   - **Polished partner sending a boxed entry**: take its 49 bytes and verify the checksum (§3.2). Do not re-seal; the checksum ignores the slot.
   - **From a party mon** (`party_struct` P[48] + nickname N[11] + OT O[11]): copy `E[0..21] = P[0..21]`, then
     `E[22] = Σ (P[22+i] >> 6) << 2i` for i = 0..3, `E[23..28] = P[26..31]`, and `E[29..31] = O[8..10]`.
     Then `E[32..41] = enc(N[0..9])` and `E[42..48] = enc(O[0..6])` (§3.1), and seal (§3.2).
     Status, HP and stats are dropped; the game recalculates them on read.
2. Pick `(d,e)`: the first `e` in 1..207 of bank 1, then bank 2 (the game's own order), whose **WRAM flag is clear**.
   As a defence, also check that no gameplay or backup record references it. If none is free: refuse with "native save required".
   Do not flush from Lua.
3. Write `E` at `flat(d,e)`.
4. **Set the WRAM flag** (bit `e-1` of `wPokeDB{d}UsedEntries`). Skip it and the slot reads as empty (`bills_pc.asm:1350`),
   and the next deposit or catch can reallocate and **overwrite** the entry.
5. Find the target box's first empty slot `s`. Write `Entries[s-1] = e` and bank bit `s-1` = `d==2`.
   Optionally write the backup record too (its own empty slot) for immediate durability. Without that, a reset before the next save drops the mon.

Byte budget per insert: 49 (entry) + 1 flag byte (WRAM) + 1 entry byte + 1 bank byte, ×2 if the backup is mirrored. **No save-checksum change.**

---

## 7. UNVERIFIED / open

- BizHawk `WRAM`-domain offset for bank 2 (`0x28B7`). Use System Bus + `SVBK` if unsure.
- A "PC UI open" predicate. `wScriptRunning` is assumed to cover the Bill's PC script.
- No live round trip yet: no Polished save or state was available. The checksum is proven against the asm transcription
  and hand arithmetic only. The first live gate should read one real deposited mon and re-seal it byte-identically.
- Memorial box number 20 is a proposal, not a ruling.
- Whether a Lua write to backup records is preferable to waiting for a native save is a policy choice for the coordinator.

## 8. `docs/newbox_format.md` errata (stale vs v3.2.3 code)

It says 16 boxes (now 20); offsets `0x2d10`/`0x2f20` (now flat `0x30E4`/`0x3378`); 167 entries per database
in 2 ranges (now 207 per bank in 3 sections A/B/C, §1.2); and "EVs (… Special)" (now 6 EV bytes). The checksum section is
right (bytes 0x00-0x1F ×(i+1), 0x20-0x30 low 7 bits ×(i+2), seed 127).

```json CLAIMS
[
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 3, "expect": "sSaveVersion:: dw"},
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 5, "expect": "sWritingBackup:: db"},
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 31, "expect": "sChecksum:: dw"},
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 58, "expect": "sBackupChecksum:: dw"},
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 141, "expect": "sNewBox{d:n}:: newbox sNewBox{d:n}"},
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 146, "expect": "sBackupNewBox{d:n}:: newbox sBackupNewBox{d:n}"},
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 152, "expect": "sBoxMons1A:: pokedb sBoxMons1A, MONDB_ENTRIES_A"},
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 162, "expect": "sBoxMons1B:: pokedb sBoxMons1B, MONDB_ENTRIES_B"},
{"path": "F:/slink-work/cache/polished/src/ram/sram.asm", "line": 172, "expect": "sBoxMons1C:: pokedb sBoxMons1C, MONDB_ENTRIES_C"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 94, "expect": "MACRO savemon_struct"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 119, "expect": "PPUps::          db"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 128, "expect": "Extra::          ds 3"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 129, "expect": "Nickname::       ds MON_NAME_LENGTH - 1"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 130, "expect": "OT::             ds PLAYER_NAME_LENGTH - 1"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 143, "expect": "Entries:: ds MONS_PER_BOX"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 144, "expect": "Banks::   flag_array MONS_PER_BOX"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 145, "expect": "Name::    ds BOX_NAME_LENGTH"},
{"path": "F:/slink-work/cache/polished/src/macros/ram.asm", "line": 146, "expect": "Theme::   db"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 299, "expect": "DEF MONDB_ENTRIES_A EQU 167"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 304, "expect": "DEF NUM_BOXES       EQU (MONDB_ENTRIES * 2 - MIN_MONDB_SLACK) / MONS_PER_BOX"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 235, "expect": "DEF SHINY_MASK       EQU %10000000"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 236, "expect": "DEF ABILITY_MASK     EQU %01100000"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 237, "expect": "DEF NATURE_MASK      EQU %00011111"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 242, "expect": "DEF GENDER_MASK      EQU %10000000"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 243, "expect": "DEF IS_EGG_MASK      EQU %01000000"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 244, "expect": "DEF EXTSPECIES_MASK  EQU %00100000"},
{"path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm", "line": 245, "expect": "DEF FORM_MASK        EQU %00011111"},
{"path": "F:/slink-work/cache/polished/src/constants/text_constants.asm", "line": 4, "expect": "DEF BOX_NAME_LENGTH    EQU 9"},
{"path": "F:/slink-work/cache/polished/src/constants/misc_constants.asm", "line": 20, "expect": "DEF SAVE_VERSION EQU 10"},
{"path": "F:/slink-work/cache/polished/src/constants/charmap.asm", "line": 43, "expect": "ctxtmap \"@\",        $53"},
{"path": "F:/slink-work/cache/polished/src/constants/charmap.asm", "line": 93, "expect": "ctxtmap \" \",        $7f"},
{"path": "F:/slink-work/cache/polished/src/home/pokemon.asm", "line": 408, "expect": "ConvertFormToExtendedSpecies::"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 409, "expect": "cp MONDB_ENTRIES + 1"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 421, "expect": "FlushStorageSystem:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 451, "expect": "cp NUM_BOXES * 2 ; current + backup"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 455, "expect": "GetStorageBoxPointer:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 490, "expect": "inc d"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 495, "expect": "UpdateStorageBoxMonFromTemp:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 535, "expect": "RemoveStorageBoxMon:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 537, "expect": "ld e, 0"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 539, "expect": "SetStorageBoxPointer:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 672, "expect": "AddStorageMon:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 705, "expect": "OpenPokeDB:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 740, "expect": "* SAVEMON_STRUCT_LENGTH"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 748, "expect": "pokedb_section sBoxMons1AMons, 0"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 749, "expect": "pokedb_section sBoxMons1CMons, MONDB_ENTRIES_A + MONDB_ENTRIES_B"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 750, "expect": "pokedb_section sBoxMons1BMons, MONDB_ENTRIES_A"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 756, "expect": "EncodeTempMon:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 804, "expect": "ld c, $7a | ~%01111111"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 823, "expect": "ChecksumTempMon:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 829, "expect": "ld hl, 127"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 830, "expect": "lb de, SAVEMON_NICKNAME, 0"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 837, "expect": "ld d, $80 | (SAVEMON_STRUCT_LENGTH - SAVEMON_NICKNAME)"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 855, "expect": "or %10000000"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 868, "expect": ".DoChecksum:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 871, "expect": "bit 6, d"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 877, "expect": "and %01111111"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 883, "expect": "rst AddNTimes"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 887, "expect": "DecodeTempMon:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 906, "expect": "sub $fa"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 975, "expect": "ld hl, BadEggRLE"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 991, "expect": "ld hl, wTempMonOT + PLAYER_NAME_LENGTH"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 1342, "expect": "GetStorageMon:"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 1350, "expect": "call IsStorageUsed"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc.asm", "line": 229, "expect": ".box_swap"},
{"path": "F:/slink-work/cache/polished/src/engine/menus/save.asm", "line": 215, "expect": "LoadStorageSystem:"},
{"path": "F:/slink-work/cache/polished/src/engine/menus/save.asm", "line": 232, "expect": "ld bc, sNewBoxEnd - sNewBox1"},
{"path": "F:/slink-work/cache/polished/src/engine/menus/save.asm", "line": 322, "expect": "ld bc, sGameDataEnd - sGameData"},
{"path": "F:/slink-work/cache/polished/src/engine/menus/save.asm", "line": 620, "expect": "Checksum:"},
{"path": "F:/slink-work/cache/polished/src/engine/menus/save.asm", "line": 730, "expect": "ld [sSaveVersion], a"},
{"path": "F:/slink-work/cache/polished/src/engine/menus/save.asm", "line": 64, "expect": "ld [wGameLogicPaused], a"},
{"path": "F:/slink-work/cache/polished/src/engine/pc/bills_pc_ui.asm", "line": 2745, "expect": "jmp RemoveStorageBoxMon"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 49691, "expect": "01:b0e4 sNewBox1"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 49791, "expect": "01:b378 sBackupNewBox1"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 49793, "expect": "01:b378 sNewBoxEnd"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 50810, "expect": "02:a000 sBoxMons1A"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 57159, "expect": "03:a000 sBoxMons2A"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 46732, "expect": "00:a000 sBoxMons1B"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 48151, "expect": "00:abf1 sBoxMons2B"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 49892, "expect": "01:b60c sBoxMons1C"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 50351, "expect": "01:b858 sBoxMons2C"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 49237, "expect": "01:ad0d sChecksum"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 49226, "expect": "00:bf0d sBackupChecksum"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 49234, "expect": "01:ab83 sGameDataEnd"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 48147, "expect": "00:abe5 sWritingBackup"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 68279, "expect": "02:d8b7 wPokeDB1UsedEntries"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 68282, "expect": "02:d8d1 wPokeDB2UsedEntries"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 65477, "expect": "00:ceb9 wGameLogicPaused"},
{"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 50849, "expect": "02:a031 sBoxMons1AMon1End"},
{"path": "F:/slink-work/wt/polished/lua/gen2/boxes.lua", "line": 109, "expect": "memorial backing refused while Box 14 is current"}
]
```
