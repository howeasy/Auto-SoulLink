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
| 4 | CREATE_MON | `[0]`=slot `[1]`=party(0=player,1=enemy) `[2..3]`=species(u16) `[4]`=level `[5]`=bump_count | engine `CreateMon` into party[slot]; `bump`=GIVE_MON (sets party count → usable member) |
| 5 | FORCE_MOVE_SLOT | `[0]`=battler `[1]`=target `[2]`=move_pos | **live** forced move via controller-swap (see below) |
| 6 | SPAWN_PEER_NPC | `[0]`=gfxId `[1]`=localId `[2..3]`=x `[4..5]`=y `[6]`=movement → `result[0]`=objEventId | spawn a real engine object-event NPC |
| 7 | DESPAWN_PEER_NPC | `[0]`=objEventId | DestroySprite + clear object-event (clean removal) |
| 8 | SHOW_MESSAGE | text pre-written (FR-encoded) to `0x0203F900` → `result[0]`=shown | native field message box (`ShowFieldMessage`) |
| 9 | PLAY_FANFARE | `[0..1]`=songId | `PlayFanfare(songId)` |
| 10 | APPLY_DAMAGE | `[0]`=battler `[1..2]`=amount → `result[0..1]`=new hp | linked HP / chip: `gBattleMons[b].hp -= amount` (clamp 0) |
| 11 | CURE_STATUS | `[0]`=battler | link-cured status: clear `gBattleMons[b].status1` |
| 12 | SET_RULES | `[0]`=enforce | ROM-enforced nuzlocke: persistently keep battle style on SET |
| 13 | ARM_PEER_INTERACT | `[0]`=ghost oeId `[1]`=armed | talk-to-ghost detection (A-press facing it) |

## Phase-5 (peer interaction + ROM-enforced settings) — validated
EWRAM state `SlinkState @ 0x0203F8D0` {enforce_rules, pi_armed, pi_oe, pi_count}. The frame hook runs
`enforce_rules()` + `check_peer_interact()` every frame (no-op until armed).
- **SET_RULES** (ROM-enforced nuzlocke): while enforced, each frame sets `optionsBattleStyle` = SET
  (bit 9 / mask 0x0200 of the options u16 at `*gSaveBlock2Ptr`(0x0300500C)+0x14) — so "no free switch
  after a KO" can't be turned off in the options menu. Live: SHIFT→SET, re-enforced after a change
  attempt, releasable. Extensible to text-speed/scene/etc.
- **ARM_PEER_INTERACT** (talk-to-ghost): each frame, if A is newly pressed (`gMain`(0x030030F0)+0x2E &
  0x0001) and the tile in front of the player (object-event facing@0x18: 1=down/2=up/3=left/4=right)
  equals the ghost object-event's tile, bump `pi_count` (the client polls it to notify the server/
  partner) and run a NAVIGABLE dialogue. Live: A-press facing the ghost -> counter++, native box
  shown, **no softlock** (a real engine-spawned NPC handles A-press cleanly, unlike the old hand-clone).
- **Dismissable dialogue (not bare ShowFieldMessage).** `ShowFieldMessage` only draws a box; the
  close (wait-for-A -> hide -> unlock) is script-driven, so on its own it sticks open. Instead the
  handler builds a 9-byte field script in EWRAM `SLINK_SCRIPT_BUF=0x0203F8E0`:
  `loadword 0, 0x0203F900` (`0F 00 00 F9 03 02`) ; `callstd MSGBOX_SIGN` (`09 03`) ; `end` (`02`),
  and runs it via `ScriptContext1_SetupScript = 0x08069AE4` (Thumb). `gStdScripts = 0x8160450` (10
  entries; **MSGBOX_SIGN = callstd index 3** = lockall/message/waitmessage/waitbuttonpress/releaseall
  — a real A-to-advance/dismiss conversation). Guard: skip if `sScriptContext2Enabled`(`0x03000F9C`)
  != 0 (a dialogue is already up) so mashing A mid-conversation doesn't re-trigger. Live-validated
  (`test_live_peerinteract` on rebuilt ROM: counter++, message shown, no softlock).

## Phase-5 (linked battle rules) — primitives validated
New gameplay only a patch enables. `gBattleMons` hp@0x28, maxHP@0x2C, status1@0x4C (stride 0x58).
- **APPLY_DAMAGE** = shared-fate chip: reduce a battler's battle HP by `amount` (clamped to 0 = a
  linked KO). The engine refreshes the health box on its next touch; at battle end CFRU copies
  gBattleMons.hp back to the party, so the chip persists. Returns the new HP.
- **CURE_STATUS** = link-cured: zero a battler's non-volatile status (poison/burn/etc.).
**Live-validated** (`test_live_linkdamage.lua`, in-battle save): chip 30→25→15, lethal→0, poison→cured.
**Orchestration (the cross-game relay) is server/client integration** — the client detects an HP delta
in battle and reports it; the server relays a fraction to the partner, whose client sends APPLY_DAMAGE
(same pattern as force_faint propagation). That wiring + a run-rule flag is the remaining feature work.

## Phase-4 (native UI) — validated
`ShowFieldMessage = 0x0806943C` `(const u8 *str)` — copies `str` (FR-charmap, 0xFF-terminated) into
`gStringVar4` (0x02021D18), starts the text printer, and creates a task the overworld's RunTasks
drives → a transient native message box. Returns FALSE if a box is already up. Lua writes the
FR-encoded text to `0x0203F900` (via `MB.write_message`/`MB.fr_encode`: space=0x00, 0-9=0xA1, A-Z=0xBB,
a-z=0xD5, EOS=0xFF) then sends SHOW_MESSAGE. `PlayFanfare = 0x08071C60`. **Live-validated**
(`test_live_message.lua`): SHOW returns shown→busy, gStringVar4 holds the text, no crash; fanfare acks.
**Deferred:** a *persistent* shared status bar (badge/area/HP) — high-effort persistent-UI that fights
the field window system and duplicates the existing dashboard/OBS overlays; the message box is the
high-value native-UI win.

## Phase-3 (peer NPC) — validated
Spawn a **real engine object-event** so the engine owns its sprite/palette/VRAM/callback —
retiring the 24-round Lua peer-ghost saga (whose corruption was all about a hand-cloned sprite's
engine-managed resources). `SpawnSpecialObjectEventParameterized = 0x0805E830` (vanilla-FR fn, RR
preserves it) `(gfxId, movementBehavior, localId, s16 x, s16 y, u8 elevation)` — **takes
camera-offset coords and subtracts MAP_OFFSET (7)**, so pass `gObjectEvents` `currentCoords`-style
coordinates. Returns the object-event id (≥16 = failed). `DestroySprite = 0x08007280`.
`gObjectEvents = 0x02036E38` (stride 0x24: flags@0, spriteId@4, gfx@5, movementType@6, localId@8,
currentCoords x@0x10/y@0x12, facing@0x18); `gSprites = 0x0202063C` (stride 0x44; inUse = byte@0x3E bit0).

**Live-validated** (`test_live_spawnnpc.lua`): SPAWN creates an active object-event + allocated
sprite at the target tile; DESPAWN clears it and frees the sprite. **Per-frame position/facing
driving stays in Lua** (the existing `peer_ghost.lua` smooth-tracking logic, now driving the
engine-spawned sprite — no clone, so no callback/palette/VRAM corruption). The NPC is spawned with
`movementType=NONE` so its engine callback won't fight the Lua-driven position.

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
**Both pure-RAM paths are now ruled out (source + empirical):**
- *Variant-3 action commit* (gChosenAction/comm/bs) — insufficient: state-2 reads
  `gBattleBufferB[battler][1]`, not `gChosenActionByBank`, and re-emits ChooseMove.
- *MULTIPLETURNS rampage lock* — SLink already tried `LOCK_STATUS2_VALUE = 0x1000 / 0x1800`
  (the correct CFRU bit) and it failed/softlocked (see `gen3_frlge.lua` RR profile comment,
  `LOCK_STATUS2_VALUE = nil`). Dead end.

**The action→move protocol (pokefirered `battle_main.c` HandleTurnActionSelectionState):**
at `STATE_WAIT_ACTION_CHOSEN`, when the multi-nibble exec mask clears, the engine reads
`gBattleBufferB[battler][1]`; `B_ACTION_USE_MOVE` (0) → `BtlController_EmitChooseMove` +
`MarkBattlerForControllerExec` (the move submenu), staying in WAIT_ACTION_CHOSEN. So it's a
**two-stage** controller handshake (choose action, then choose move), each gated by the exec
mask and read from `gBattleBufferB`.

**Full 3-state protocol RE'd** (`battle_main.c`, comm enum confirmed by live probe):
BEFORE_ACTION_CHOSEN=1 → WAIT_ACTION_CHOSEN=2 → WAIT_ACTION_CASE_CHOSEN=3 → CONFIRMED_STANDBY=4.
- comm 2: engine reads `gBattleBufferB[b][1]` (action); USE_MOVE(0) → emits ChooseMove, comm→3.
- comm 3: reads `gBattleBufferB[b][1]==10` + `[2]`=move_pos + `[3]`=target → sets
  `chosenMovePositions=[2]`, `gChosenMoveByBattler=moves[[2]]`, `moveTarget=[3]`, comm→4 (executes).
Move emit (`battle_controller_player.c:342`): `EmitTwoReturnValues(1, 10, cursor | (target<<8))`.

### SOLVED — FORCE_MOVE_SLOT (opcode 5), live-validated
A pre-callback2 hook can't win the buffer race (the controller/DMA overwrites it during
callback2). The fix is a **controller-pointer swap**: when armed and the player's menu is up,
the frame hook repoints `gBattlerControllerFuncs[battler]` (0x3004FE0) to our own routine, which
therefore runs *as* the controller (authoritative). That routine sets `gChosenActionByBank=USE_MOVE`,
`gChosenMovesByBanks[b]=gBattleMons[b].moves[move_pos]`, `gBattleStruct->chosenMovePositions[b]`/
`moveTarget[b]`, and **jumps comm straight to STATE_WAIT_ACTION_CONFIRMED_STANDBY (4)** + clears the
exec mask, then disarms (fires once via an `armed` guard; the engine reassigns the controller at the
next menu). Jumping to CONFIRMED sidesteps both the buffer-transfer round-trip *and* CFRU's Z-move
byte (a stale value made Scratch fire as "Breakneck Blitz").

**Live-validated** (`test_live_forcemove.lua`): forcing slot 1 (Growl) on the lead → slot-1 PP drops,
fires once, no corruption, no Z-move. Comm enum confirmed: 1 BEFORE → 2 WAIT_ACTION → 3 CASE_CHOSEN
→ 4 CONFIRMED_STANDBY. The exec mask is `bit|bit<<4|bit<<8|bit<<12|0xF0000000` on `gBattleExecBuffer
=0x02023BC8`.

**RR-build-specific addresses (runtime-discovered — re-discover per RR version):**
action-menu controllers `0x0802E439`/`0x0802E3B5`, move-menu controller thunk `0x0802EA11`
(→ real `HandleInputChooseMove` 0x090AB8B8). Also found (used by the abandoned emit approach,
kept for reference): `EmitTwoReturnValues=0x0800E848`, `EmitMoveChosen=0x090AA73C`,
`PlayerBufferExecCompleted=0x0802E33C`, `gBattleBufferB=0x20233C4` (stride 0x200, CFRU format
`[0]=0x21 [1]=10/action [2]=move_pos [3]=target [4]=mega [5]=ultra [6]=zMove [7]=dynamax`).

**This empirically validates the report's core thesis:** pure external RAM-poke is
fundamentally limited; robust battle control needs in-ROM (controller-hook) code.
