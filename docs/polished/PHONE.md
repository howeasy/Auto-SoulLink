# Polished Crystal 3.2.3 — porting SLink PHONE-NAMES

Design for porting the Pokégear phone feature: SLink rings the player with partner
events (the Gen 2 `phone_calls` option, default ON) and, with PHONE-NAMES, prints the
partner's caller names.

**ROM facts carry bank:addr + flat offset + bytes** read from
`F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc`. WRAM is never dumped.

Vanilla implementation mirrored: `patch/gen2/src/phone.asm`,
`patch/gb/slink_abi.inc`, `tools/build_gen2_companion.py`, `lua/gen2/phone.lua`,
`data/games/gen2_crystal/overlay/binding.json`.

## 0. Answer in one line

**The port is feasible and the two mechanisms PHONE-NAMES depends on both survive:
`text_ram` and the `setval`/`readmem` script opcodes.** The blockers are elsewhere — the
staging buffer's home symbol is gone, the caller-name hook is an 8-byte jump rather than
a clean call site, and the special-call slot table is full.

## 1. Vanilla flow, and the Polished mapping

### 1.1 How vanilla raises the call

1. **Host** (`lua/gen2/phone.lua`) stages one **24-byte record** in
   `wUnusedMapBuffer` and posts a request. Record layout, `phone.asm:17-24`:
   `STAGE_EVENT 0`, `STAGE_CALLER 1`, `STAGE_RECEIVER 2`, `STAGE_TRAINER 3`
   (7 glyphs + `@`), `STAGE_NICK 11` (10 glyphs + `@`), `STAGE_NONCE 22`,
   `STAGE_COOKIE 23`. Cookie is `$a6` (layout v1) and
   `ASSERT wUnusedMapBufferEnd - wUnusedMapBuffer == SLINK_STAGE_COOKIE + 1` (`:26`).
2. **Mailbox**: `SLINK_OFS_PHONE_REQUEST EQU 32`, `SLINK_OFS_PHONE_ARMED EQU 33`
   (`patch/gb/slink_abi.inc:29-30`), plus the phone-private tail
   `PHONE_HEADER 34`, `PHONE_NONCE 35`, `PHONE_ARMED_NONCE 36` (`phone.asm:28-30`).
3. **ROM service** `SlinkPhoneService::` (`phone.asm:34`) runs from the frame hook,
   validates `wSpecialPhoneCallID`, scrubs a stale SLink id, validates ARMED, then arms
   the call: `SPECIALCALL_SLINK EQU 9` (`phone.asm:8`).
4. **Script** `SlinkPhoneCallScript::` (`phone.asm:143`) is the row-9 script. It
   `callasm SlinkPhonePrepareCall` (`:152`), which sets `wScriptVar = ARMED`, or
   `ARMED + 3` when names are staged (`SLINK_CALL_NAMED EQU 3`, `:25`).
5. **Text**: five static variants plus two named variants. The named ones are
   `SlinkPhoneNamedFallenText::` (`:215`) and `SlinkPhoneNamedFirstLinkText`, and the
   first line of the first is **`text_ram wStringBuffer5`** — a **RAM** string, not
   compressed text.

### 1.2 The mapping

| vanilla | Polished | verdict |
|---|---|---|
| `SPECIALCALL_SLINK EQU 9`, 9-row `SpecialPhoneCallList` | `data/phone/special_calls.asm`, **12 rows**, `SPECIALCALL_SIZE` 6 (`phone.asm:169` `ld a, 6` / `rst AddNTimes`) | **changed** — table is longer; `SPECIALCALL_SLINK` must be re-picked, not assumed 9 |
| `CheckSpecialPhoneCall` | `CheckSpecialPhoneCall::` `engine/phone/phone.asm:160`, `sym:22078`, `24:40bc` flat `0x900BC`, bytes `fa 6b dc a7 28 33` | **same shape** — `dec a` (1-based), `ld a,6 / rst AddNTimes`, condition `_hl_` |
| `specialphonecall` script macro | `macros/scripts/events.asm:995-998` — `db specialphonecall_command / db \1`, same 2 bytes | **same** |
| `writetext` + `text_ram wStringBuffer5` | `MACRO text_ram` `macros/scripts/text.asm:18-21` — `stop_compressing_text / db "<RAM>" / dw \1` | **same** — the enabler |
| `wScriptVar` (1 byte, WRAM0) | `hScriptVar:: dw` at `$FF85`, HRAM (`docs/polished/HOOKS.md` §3.4) | **moved + widened** — a word in HRAM, not System-Bus WRAM |
| `readmem` / `loadmem` / `setval` | `macros/scripts/events.asm:173`, `:179`, `:138`, `:144` | **same opcodes exist** |
| `wSpecialPhoneCallID` `01:dc31` | `wSpecialPhoneCallID` `01:dc6b` (`sym:67473`) | **moved**, still 1-based |
| `GetCallerName` | `GetCallerClassAndName:` `phone.asm:376`, `GetTrainerName 07:41c8` (`sym:6128`), `GetCallerTrainerClass 24:42af` | **renamed** — HOOKS §3.4 |
| `wUnusedMapBuffer` / `+End` (24 B staging) | **absent** — zero hits in the sym | **absent** — see §2 |
| `wStringBuffer5` `01:d0bf` | `wStringBuffer5` `01:d0c5` (`sym:65726`) | **same role, moved** |

## 2. The staging buffer

Vanilla stages into `wUnusedMapBuffer` and relies on `HandleNewMap` clearing it.
**Neither symbol exists in Polished** — I verified both are absent from
`data/polished/polishedcrystal.sym`, matching HOOKS §3.4.

`docs/polished/HOOKS.md` proposes the mailbox tail instead. Checking the sym directly:
**no symbol at all occupies WRAM bank 1 in `$C600-$C700`**, so `$C633` and the 29 bytes
to `$C64F` are unallocated and usable as the staging record. That matches HOOKS's
"29 spare mailbox bytes at `$C633`".

**Recommendation: stage at `$C633`, and clear it in the same place vanilla cleared
`wUnusedMapBuffer`** — but note the loss HOOKS records: vanilla's clear-on-map-change
guarantee was a side effect of `HandleNewMap`, and **nothing in Polished provides it for
free**. Two options: (a) hook `EnterMap`/map change to `ByteFill` the record, or
(b) accept single-use semantics only. I favour (a): the ADVERSARIAL_REVIEW card
already flags that "the backing slot may be removed and the buffer still holds the mon",
and an explicit clear is cheaper than recovering from that class of bug.

## 3. Text encoding for a staged name

`text_ram` exists (`macros/scripts/text.asm:18-21`) and emits `"<RAM>"` followed by a
`dw` address — the decompressor at `home/text.asm:844` handles `"<RAM>"` by copying
until a terminator. So **a staged name must be a plain charmap string terminated by `@`
(`$53`, `constants/charmap.asm:43`), not Huffman-compressed**, and it must fit the
variable-width font's per-character widths.

Consequences I can state and one I cannot:

- The 10-glyph nickname + `@` layout from `phone.asm:21` ports over unchanged.
- **UNVERIFIED:** the VWF per-character widths for the name glyphs. Vanilla's comment
  says "Lines fit 18 tiles with PLAYER expanded to its seven-character maximum", which
  is a *tilemap* budget in a fixed-width font. Polished uses a variable-width font, so
  a 10-glyph name may occupy more or fewer tiles. **The staged record's glyph budget
  must be re-derived from the font metrics before the layout is frozen.**

## 4. The Pokégear phone list

Vanilla adds a slot for SLink. Polished's list is `SpecialPhoneCallList`
(`sym:22127`, `24:4506` flat `0x90506`, bytes `09 41 04 62 6c 53` — `dw` condition,
`db` contact, `dba` script) with **12 rows** and `assert_table_length NUM_SPECIALCALLS`.

**The table is longer than vanilla's 8, and `SPECIALCALL_SLINK EQU 9` aliases a native
row in Polished** (row 9 is `SPECIALCALL_LYRASEGG`, `data/phone/special_calls.asm`).
So the overlay cannot append a row the way vanilla did without renumbering native rows —
or it can append at row 13 and use `SPECIALCALL_SLINK EQU 13`. **Appending at the end is
the safe choice** because it leaves every native id's numeric value intact.

Contacts: `AddPhoneNumber::` `phone.asm:11` (`sym:22063`, `24:400b` flat `0x9000B`),
`wPhoneList` `01:dc8c` (`sym:67493`). Both exist; **UNVERIFIED** whether the overlay needs
a contact row at all (the vanilla overlay registered `SPECIALCALL_SLINK` against an
existing contact — I have not read which).

## 5. Overlay edits, space and the frame-hook question

| edit | anchor | notes |
|---|---|---|
| extend `SpecialPhoneCallList` | `24:4506` flat `0x90506` | append row 13 (`SPECIALCALL_SIZE` 6 bytes) |
| caller-name hook | `GetCallerClassAndName:` `24:41ff` flat `0x901FF` | HOOKS: an 8-byte jump plus replay |
| script | new, in bank `$7E` | mirrors `SlinkPhoneCallScript::` |
| ROM0 bridge | a 3-byte `call` site | **UNVERIFIED** — I did not locate the exact instruction |

**Space.** Bank `$7E` is entirely unallocated (16384 free, `data/polished/free_space.txt`),
as is `$7F`. The script, the service, the 24-byte record's accessor and the text variants
fit with room to spare. ROM0 has **351 bytes free** in total (SUPERSEDED 2026-10-04: `$015f` is that COUNT, not an address; the real
gaps are `$0089-$00FF` and the part of `$3F34-$3FFF` after the phone bridge -- `docs/polished/HOOKS.md:812-813`),
enough for same-size
`call`/`jp` rewrites.

**Mailbox.** ABI fields `SLINK_OFS_PHONE_REQUEST 32` / `SLINK_OFS_PHONE_ARMED 33`
(`patch/gb/slink_abi.inc:29-30`) plus the private tail 34-36 (`phone.asm:28-30`).
Vanilla's mailbox was a fixed `WRAM0[$CFD8]` 40 B; **Polished has no fixed mailbox
span** (HOOKS §3.1). The overlay must therefore pick a concrete WRAM address for its own
mailbox and record it in `binding.json` — it cannot inherit vanilla's.

**Frame-hook context — the real question.** `DelayFrame`'s bridge runs the service in
bank `$7E`. Starting a phone call *from* there is the risk: `CheckSpecialPhoneCall`
(`phone.asm:160`) walks a pointer table, evaluates a condition callback `_hl_`, and
`LoadCallerScript` (`sym:22095`, `24:41ae` flat `0x901AE`) starts a script — all of
which assume the normal script-start context. **I cannot prove from source that a call
can be *initiated* inside the frame bridge.**

My recommendation: the frame bridge should do what vanilla does — **consume the request
and arm the mailbox only** (`wSpecialPhoneCallID` + ARMED), and let the native
`CheckSpecialPhoneCall` path start the script on its own schedule. That keeps script
initiation on vanilla's own footing and confines the overlay to a pure data write. This
matches the vanilla split, where `SlinkPhoneService` arms and the *script* runs.
**UNVERIFIED** whether the DelayFrame bridge context permits even the arming write; that
is falsifiable statically by reading the bridge and `DelayFrame`.

## 6. Risks

| # | risk | severity | evidence / status |
|---|---|---|---|
| P1 | **`SPECIALCALL_SLINK EQU 9` aliases a native row** — Polished row 9 is `SPECIALCALL_LYRASEGG` (`data/phone/special_calls.asm`) | **high** | appending must be at row 13, not 9 |
| P2 | **staging buffer's home symbol is gone**; the clear-on-map-change guarantee is gone with it | **high** | `wUnusedMapBuffer`/`+End` absent from the sym; needs an explicit `ByteFill` |
| P3 | **VWF widths** — a 10-glyph name may not fit the tile budget vanilla assumed | **medium** | UNVERIFIED; needs font metrics |
| P4 | **frame-hook context** — initiating a call from the `DelayFrame` bridge is unproven | **high** | §5; mitigated by arm-only |
| P5 | **no fixed mailbox span** in Polished, so the ABI offsets 32/33/34-36 have no base | **high** | HOOKS §3.1; the overlay must choose and record one |
| P6 | **`hScriptVar` is a word in HRAM**, not a WRAM byte | **medium** | HOOKS §3.4; the vanilla `callasm` handshake must write 2 bytes and the script must read 2 |
| P7 | **`GetCallerClassAndName` is renamed and its hook is an 8-byte jump plus replay** — a larger, more fragile edit than vanilla's | **medium** | HOOKS §3.4; verified the label exists (`sym:22103`) |
| P8 | ADVERSARIAL_REVIEW's existing findings (`GetCallerClassAndName` empty-slot path, uncleared pointer) are still open and **apply to Polished too** | **high** | carried from m-295588d / m-295d84c |

## 7. Card list, with first falsifiers

| # | card | first falsifier |
|---|---|---|
| P1 | register SLink's special call at **row 13** in `SpecialPhoneCallList` | read `data/phone/special_calls.asm` and assert `NUM_SPECIALCALLS == 12`, so row 13 is the first free index; assert no native row's id changes |
| P2 | choose and record the Polished mailbox base; emit offsets 32/33/34-36 into `binding.json` | assert the chosen span is unallocated in the sym |
| P3 | stage into `$C633` + an explicit map-change clear | assert no sym entry occupies bank 01 `$C600-$C700`; assert the clear site is a same-size `call` |
| P4 | **`text_ram` proof** — print a staged 10-glyph name through a `specialphonecall` script | assert `macros/scripts/text.asm:18` exists and `home/text.asm` handles `"<RAM>"`; then render it |
| P5 | arm-only service in the frame bridge (no script initiation) | assert the bridge writes only `wSpecialPhoneCallID` + ARMED, and that `CheckSpecialPhoneCall` is what starts the script |
| P6 | caller-name hook at `GetCallerClassAndName:` `24:41ff` flat `0x901FF` | whole-ROM diff: assert only the intended bytes change |
| P7 | VWF budget for a 10-glyph name | measure the name at its worst-case glyph mix and assert it fits the textbox line |
| P8 | live: ring the partner, assert the caller name renders and the call can be hung up | **live only** |

### 7.1 What can only be verified live

P8 (an actual ring with a staged name), P5's arming behaviour in situ, and whether the
frame bridge tolerates the write at all under load. Everything in P1-P4, P6, P7 is
falsifiable from source, the sym, or a whole-ROM diff.

## 8. Corrections carried into this document

- `docs/polished/HOOKS.md` §3.4 records that `SPECIALCALL_SLINK EQU 9` now aliases a
  native row; this document confirms it against the source and changes the plan
  (append at 13, not 9).
- HOOKS proposes the `$C633` staging bytes; this document verified the region is
  genuinely unallocated rather than merely unreferenced.

## Coordinator correction (2026-10-04) to F3

Counting `constants/phone_constants.asm:45-58` (`const_def`, NONE = 0): POKERUS 1, ROBBED 2, ASSISTANT 3, WEIRDBROADCAST 4, SSTICKET 5, BIKESHOP 6, WORRIED 7, MASTERBALL 8, **YELLOWFOREST 9**, FIRSTBADGE 10, SECONDBADGE 11, LYRASEGG 12; `NUM_SPECIALCALLS` = 12. So the native row at id 9 is `SPECIALCALL_YELLOWFOREST`, not LYRASEGG (that is id 12). The conclusion is unchanged: `SPECIALCALL_SLINK EQU 9` would alias a native row, and the first free id is 13 (append at the end, `SPECIALCALL_SLINK EQU 13`). Also re-read on the ROM: `CheckSpecialPhoneCall` flat `0x900BC` = `fa 6b dc a7 28 33`; `SpecialPhoneCallList` flat `0x90506` = `09 41 04 62 6c 53`.

```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":8,"expect":"DEF SPECIALCALL_SLINK EQU 9"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":9,"expect":"ASSERT NUM_SPECIALCALLS == 8 && SPECIALCALL_SIZE == 6"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":16,"expect":"DEF SLINK_PHONE_STAGE EQUS \"wUnusedMapBuffer\""},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":23,"expect":"DEF SLINK_STAGE_COOKIE EQU 23"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":24,"expect":"DEF SLINK_PHONE_COOKIE EQU $a6"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":25,"expect":"DEF SLINK_CALL_NAMED EQU 3"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":26,"expect":"ASSERT wUnusedMapBufferEnd - wUnusedMapBuffer == SLINK_STAGE_COOKIE + 1"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":34,"expect":"SlinkPhoneService::"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":143,"expect":"SlinkPhoneCallScript::"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":152,"expect":"callasm SlinkPhonePrepareCall"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":215,"expect":"SlinkPhoneNamedFallenText::"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":28,"expect":"DEF SLINK_OFS_PHONE_HEADER EQU 34"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":244,"expect":"SlinkPhonePrepareCall:"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/phone.asm","line":140,"expect":"ASSERT SlinkSpecialPhoneCallListEnd - SlinkSpecialPhoneCallList == 9 * SPECIALCALL_SIZE"},{"path":"F:/slink-work/wt/polished/patch/gb/slink_abi.inc","line":26,"expect":"DEF SLINK_CAP_PHONE      EQU 1 << 3"},{"path":"F:/slink-work/wt/polished/patch/gb/slink_abi.inc","line":29,"expect":"DEF SLINK_OFS_PHONE_REQUEST EQU 32"},{"path":"F:/slink-work/wt/polished/patch/gb/slink_abi.inc","line":30,"expect":"DEF SLINK_OFS_PHONE_ARMED EQU 33"},{"path":"F:/slink-work/cache/polished/src/data/phone/special_calls.asm","line":8,"expect":"SpecialPhoneCallList:"},{"path":"F:/slink-work/cache/polished/src/data/phone/special_calls.asm","line":22,"expect":"SPECIALCALL_LYRASEGG"},{"path":"F:/slink-work/cache/polished/src/data/phone/special_calls.asm","line":20,"expect":"SPECIALCALL_FIRSTBADGE"},{"path":"F:/slink-work/cache/polished/src/data/phone/special_calls.asm","line":23,"expect":"assert_table_length NUM_SPECIALCALLS"},{"path":"F:/slink-work/cache/polished/src/data/phone/special_calls.asm","line":1,"expect":"MACRO specialcall"},{"path":"F:/slink-work/cache/polished/src/engine/phone/phone.asm","line":160,"expect":"CheckSpecialPhoneCall::"},{"path":"F:/slink-work/cache/polished/src/engine/phone/phone.asm","line":11,"expect":"AddPhoneNumber::"},{"path":"F:/slink-work/cache/polished/src/engine/phone/phone.asm","line":433,"expect":"HangUp::"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":995,"expect":"MACRO specialphonecall"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":138,"expect":"const setval_command"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":173,"expect":"const readmem_command"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":179,"expect":"const readmem16_command"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":144,"expect":"const setval16_command"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/text.asm","line":18,"expect":"MACRO text_ram"},{"path":"F:/slink-work/cache/polished/src/constants/charmap.asm","line":43,"expect":"ctxtmap \"@\",        $53, 001011010"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22127,"expect":"24:4506 SpecialPhoneCallList"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22078,"expect":"24:40bc CheckSpecialPhoneCall"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22095,"expect":"24:41ae LoadCallerScript"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":67473,"expect":"01:dc6b wSpecialPhoneCallID"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22063,"expect":"24:400b AddPhoneNumber"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22103,"expect":"24:41ff GetCallerClassAndName"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":6128,"expect":"07:41c8 GetTrainerName"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":67493,"expect":"01:dc8c wPhoneList"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65726,"expect":"01:d0c5 wStringBuffer5"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":22108,"expect":"24:4250 HangUp"},{"path":"F:/slink-work/wt/polished/data/polished/free_space.txt","line":3,"expect":"2 ROMX bank(s) never allocated by the linker"},{"path":"F:/slink-work/wt/polished/data/polished/free_space.txt","line":10,"expect":"bank 126:  16384 free ($4000)"},{"path":"F:/slink-work/wt/polished/data/polished/free_space.txt","line":6,"expect":"bank   0:    351 free ($015f) of 16384"}]
```
