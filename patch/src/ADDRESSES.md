# Cross-validated addresses — Radical Red (md5 8529f3a45d32bce4da637976fcf269d4)

Every entry is derived **two ways** (plan §5): a named **symbol source** and the
**RR binary** itself (capstone via `patch/tools/disasm.py`). Both must agree.

Key validated finding: **RR preserves base FireRed engine addresses** — vanilla-FR /
CFRU `BPRE.ld` symbols resolve to correct, sane prologues in this RR build. So BPRE.ld
is a valid map for the base engine here.

| Symbol | Address | Symbol source | Binary confirmation (RR) |
|---|---|---|---|
| `gMain` | `0x030030F0` | BPRE.ld `gMain = 0x30030F0` | `SetMainCallback2` does `str r0,[r1,#4]` ⇒ callback2 @ gMain+4 = `0x030030F4` (also matches peer-ghost memory) |
| `SetMainCallback2` | `0x08000544` | BPRE.ld | `ldr r1,[pc]; str r0,[r1,#4]` ✓ |
| `CallCallbacks` callback2 dispatch | see hook below | pokefirered `main.c` CallCallbacks | disasm 0x8000510-0x800053E ✓ |
| `RunTasks` | `0x08077578` | BPRE.ld | `push {r4,r5,lr}` clean prologue, **not** CFRU-hooked ✓ |
| `AnimateSprites` | `0x08006B5C` | BPRE.ld | `push {r4,r5,r6,r7,lr}` ✓ |
| `CreateMon` | `0x0803DA54` | BPRE.ld `0x803DA54\|1` | `push {r4-r7,lr}; mov r7,r8; push{r7}; sub sp,#0x1c` ✓ (Phase 2) |
| `CreateMonWithNature` | `0x0803DD98` | BPRE.ld | (Phase 2) |

## Phase-0 injection sites (all binary-confirmed)

- **Hook site `0x0800051A`** — a **5× `mov r8,r8` (Thumb NOP) sled** (10 bytes) inside
  `CallCallbacks`, which runs **every frame, all contexts, main-thread**. RR/CFRU left
  it as NOPs (no existing hook). `lr` is already saved on the stack at the function
  prologue (`push {r4,lr}` @0x8000510), so a `bl` here may clobber `lr` safely. We
  overwrite the first **4 bytes** with `bl slink_hook`; the remaining 6 bytes stay NOP,
  so control falls through to the callback dispatch at `0x08000524`.
  - Binary: `0x0800051A..0x08000523 = C0 46 ×5` (confirmed via disasm).

- **Code region `0x08378CA8`** (file `0x378CA8`) — a `0x14900`-byte (~83 KB) `0xFF`
  free run (from `find_freespace.py`). Distance from the hook `0x0800051A` is
  `0x37 8790` ≈ 3.62 MB, **within Thumb BL ±4 MB range**. Holds the trampoline +
  dispatcher + per-opcode handlers. (Deeper pointer-reference audit before Phase 1.)

- **Mailbox `0x0203F800`** (EWRAM) — above CFRU's highest known EWRAM symbol
  (`0x0203F3AE`), with ~0x450 bytes margin, below EWRAM end `0x0203FFFF`.
  **Runtime-validated**: watched for stray writes across gameplay before trusting
  (Phase-0 gate). Mailbox is ≤256 bytes.

## Mailbox ABI v1 (little-endian)

| off | type | field | meaning |
|---|---|---|---|
| 0 | u32 | signature | `'SLNK'` = bytes `53 4C 4E 4B` (u32 LE `0x4B4E4C53`). Written every frame ⇒ Lua presence beacon. |
| 4 | u16 | abi_version | `1` |
| 6 | u16 | opcode | Lua writes; dispatcher clears to 0 when consumed. `0`=idle, `1`=PING |
| 8 | u16 | seq | Lua increments per command |
| 10 | u16 | status | `0`=idle `1`=busy `2`=ok `3`=fail |
| 12 | u16 | ack_seq | dispatcher echoes `seq` when done |
| 14 | u16 | reason | fail reason code |
| 16 | u8[32] | args | opcode arguments |
| 48 | u8[?] | result | opcode result bytes |
