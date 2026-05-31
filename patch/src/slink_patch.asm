; SLink companion patch — Phase 0 substrate (armips, Thumb)
; Assembled by patch/tools/build.py, which supplies the .open/.close wrapper.
;
; Hook: 4-byte `bl SlinkHook` over the NOP sled at 0x0800051A inside CallCallbacks
;       (runs every frame, all contexts, main-thread; lr already saved on stack).
; Code: trampoline + mailbox dispatcher in the free ROM region at 0x08378CA8.
; Mailbox: EWRAM 0x0203F800 (ABI v1 — see patch/src/ADDRESSES.md).

.definelabel MAILBOX,   0x0203F800
.definelabel SLNK_SIG,  0x4B4E4C53      ; 'SLNK' little-endian (bytes 53 4C 4E 4B)
.definelabel HOOK_SITE, 0x0800051A
.definelabel CODE_BASE, 0x08378CA8

; ---------------------------------------------------------------- hook site
.org HOOK_SITE
.thumb
    bl SlinkHook            ; 4 bytes; 6 NOP bytes remain -> fall through to 0x08000524

; ---------------------------------------------------------------- battle globals (validated)
; gChosenActionByBank u8[4] @0x02023D7C, gChosenMovesByBanks u16[4] @0x02023DC4,
; gBattleCommunication u8[8] @0x02023E82, gBattleStruct ptr @0x02023FE8,
; gBattleMons @0x02023BE4 (stride 0x58, hp @+0x28); BattleStruct.moveTarget @+0x0C,
; chosenMovePositions @+0x80. (SLink RR profile <-> BPRE.ld <-> binary.)
.definelabel gBattleMons,        0x02023BE4
.definelabel gChosenActionByBank,0x02023D7C
.definelabel gChosenMovesByBanks,0x02023DC4
.definelabel gBattleCommunication,0x02023E82
.definelabel gBattleStruct,      0x02023FE8

; ---------------------------------------------------------------- injected code
.org CODE_BASE
.thumb
; Registers: r0 = mailbox base (held), r1 = opcode then battler, r2/r3 scratch.
; Only r0-r3/lr are saved, so handlers must stay within r0-r3.
SlinkHook:
    push {r0-r3, lr}
    ldr  r0, =MAILBOX
    ldr  r1, =SLNK_SIG
    str  r1, [r0, #0]          ; signature beacon (every frame)
    mov  r1, #1
    strh r1, [r0, #4]          ; abi_version = 1
    ldrh r1, [r0, #6]          ; opcode
    cmp  r1, #0
    beq  SlinkDone             ; idle: no ack, just return
    cmp  r1, #1
    beq  SlinkOk               ; PING -> ack ok
    cmp  r1, #2
    beq  OpForceFaint
    cmp  r1, #3
    beq  OpForceMove
    b    SlinkFail             ; unknown opcode

; --- opcode 2: FORCE_FAINT  args[0]=battler ---
OpForceFaint:
    ldrb r1, [r0, #16]         ; battler
    mov  r2, #0x58
    mul  r1, r2                ; battler*0x58
    ldr  r2, =gBattleMons
    add  r2, r2, r1            ; &gBattleMons[battler]
    mov  r3, #0
    strh r3, [r2, #0x28]       ; hp = 0
    b    SlinkOk

; --- opcode 3: FORCE_MOVE  args[0]=battler [1]=target [2]=move_pos [4..5]=move_id(u16) ---
OpForceMove:
    ldrb r1, [r0, #16]         ; battler
    ldr  r2, =gChosenActionByBank
    mov  r3, #0
    strb r3, [r2, r1]          ; action[battler] = USE_MOVE(0)
    ldr  r2, =gChosenMovesByBanks
    lsl  r3, r1, #1
    add  r2, r2, r3            ; &gChosenMovesByBanks[battler]
    ldrh r3, [r0, #20]         ; move_id (aligned)
    strh r3, [r2]
    ldr  r2, =gBattleCommunication
    mov  r3, #3
    strb r3, [r2, r1]          ; comm[battler] = 3 (confirmed standby)
    ldr  r2, =gBattleStruct
    ldr  r2, [r2]              ; bs = *gBattleStruct
    add  r2, #0x80
    ldrb r3, [r0, #18]         ; move_pos
    strb r3, [r2, r1]          ; bs->chosenMovePositions[battler]
    ldr  r2, =gBattleStruct
    ldr  r2, [r2]              ; bs again
    add  r2, #0x0C
    ldrb r3, [r0, #17]         ; target
    strb r3, [r2, r1]          ; bs->moveTarget[battler]
    b    SlinkOk

; --- shared ack tails ---
SlinkFail:
    mov  r3, #1
    strh r3, [r0, #14]         ; reason = 1 (unknown opcode)
    mov  r3, #3               ; status = fail
    b    SlinkAck
SlinkOk:
    mov  r3, #2               ; status = ok
SlinkAck:
    strh r3, [r0, #10]         ; status
    ldrh r2, [r0, #8]
    strh r2, [r0, #12]         ; ack_seq = seq
    mov  r2, #0
    strh r2, [r0, #6]          ; opcode = 0 (consumed)
SlinkDone:
    pop  {r0-r3, pc}           ; restore + return to saved lr (Thumb)
.pool
