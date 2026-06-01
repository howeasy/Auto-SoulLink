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

### Opcodes
| op | name | args | effect |
|---|---|---|---|
| 1 | PING | — | ack ok (presence/round-trip check) |
| 2 | FORCE_FAINT | `[0]`=battler | `gBattleMons[battler].hp = 0` |
| 3 | FORCE_MOVE | `[0]`=battler `[1]`=target `[2]`=move_pos `[4..5]`=move_id(u16) | commits a forced move (see below) |
| 4 | CREATE_MON | `[0]`=slot `[2..3]`=species(u16) `[4]`=level | calls engine `CreateMon` into `gPlayerParty[slot]` |

## Phase-2 (CREATE_MON) — validated
`gPlayerParty = 0x02024284` (BPRE.ld ↔ SLink RR profile), MON_SIZE 100; party struct
level@0x54, hp@0x56, maxHP@0x58 (plaintext, outside the encrypted substruct). `CreateMon`
@ `0x0803DA54` called via fixed-address function pointer from injected C. **Live-validated**
(`test_live_createmon.lua`, overworld save): Bulbasaur L50 → maxHP 105 (exact base-45 calc),
Snorlax L50 → maxHP 220; Snorlax ≫ Bulbasaur proves species-specific base stats → fixes the
"Mewtwo with Pidgey stats" bug. **The handlers are now compiled C (`handlers.c` + `slink.ld`,
linked at CODE_BASE); `build.py` uses arm-none-eabi-gcc. The earlier hand-asm dispatcher
(slink_patch.asm) is retired — the C build passes the same PING + battle-logic tests.**

## Phase-1 battle globals (triple-validated: SLink RR profile ↔ BPRE.ld ↔ binary)
| symbol | address | notes |
|---|---|---|
| `gBattleMons` | `0x02023BE4` | stride `0x58`, hp(u16) @+0x28, maxHP @+0x2C |
| `gChosenActionByBank` | `0x02023D7C` | u8[4]; USE_MOVE=0 |
| `gChosenMovesByBanks` | `0x02023DC4` | u16[4]; move id |
| `gBattleCommunication` | `0x02023E82` | u8[8]; 3 = confirmed-standby (skips menu) |
| `gBattleStruct` | `0x02023FE8` | pointer; `chosenMovePositions[]` @+0x80, `moveTarget[]` @+0x0C |

> **Cross-validation caught an error:** an RE pass claimed `chosenMovePositions @ +0x90`; the
> battle-tested SLink profile (`gen3_frlge.lua`) and shipping Explode-mode prove it is **+0x80**.
>
> FORCE_MOVE replicates SLink's production "Variant-3" commit natively. The dispatcher's
> writes are runtime-validated via `lua/tests/test_mailbox_battle.lua` (fake battle state,
> every global confirmed) and FORCE_FAINT zeroes the live battler HP correctly.

### FORCE_MOVE live-execution finding (source-confirmed — pokefirered `battle_main.c`)
Live testing on a real in-battle savestate proved the Variant-3 RAM commit **does not, by
itself, execute a move** from the action menu. `HandleTurnActionSelectionState` at
`STATE_WAIT_ACTION_CHOSEN`:
1. gates on a **multi-nibble** exec mask — `bit | bit<<4 | bit<<8 | bit<<12 | 0xF0000000`,
   not just `1<<battler` (`gBattleControllerExecFlags`/`gBattleExecBuffer` = `0x02023BC8`);
2. reads the action from **`gBattleBufferB[battler][1]`** (`gBattleBufferB = 0x20233C4`,
   stride 0x200), **not** `gChosenActionByBank`;
3. on USE_MOVE it **re-emits ChooseMove** (the move submenu) — so committing the action
   only loops back to move-select.
**Conclusion (validates the report thesis):** a generic, robust live FORCE_MOVE cannot be
done by external RAM-poke; it needs a **controller hook** that calls the engine's
`BtlController_EmitMoveChosen` + `PlayerBufferExecCompleted` (`0x0802E33C`). That is the
C-toolchain approach — deferred. SLink's Lua Explode "works" only because it *also* rewrites
all 4 move slots to Explosion, so whatever the menu path picks is the forced move.
**FORCE_MOVE here is therefore a validated *commit* primitive; live execution is gated on
the controller hook.** (Diagnostics that established this: input reaches the core; the
savestate is a valid singles action-menu; mashing A executes a move → rig is sound.)
