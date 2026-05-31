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

; ---------------------------------------------------------------- injected code
.org CODE_BASE
.thumb
SlinkHook:
    push {r0-r3, lr}
    ldr  r0, =MAILBOX
    ldr  r1, =SLNK_SIG
    str  r1, [r0, #0]          ; signature beacon (every frame)
    mov  r1, #1
    strh r1, [r0, #4]          ; abi_version = 1
    ldrh r1, [r0, #6]          ; opcode
    cmp  r1, #0
    beq  SlinkHookDone         ; idle
    cmp  r1, #1
    bne  SlinkHookUnknown
    ; --- opcode 1: PING -> ack ok ---
    ldrh r2, [r0, #8]          ; seq
    strh r2, [r0, #12]         ; ack_seq = seq
    mov  r2, #2
    strh r2, [r0, #10]         ; status = ok
    mov  r2, #0
    strh r2, [r0, #6]          ; opcode = 0 (consumed)
    b    SlinkHookDone
SlinkHookUnknown:
    mov  r2, #3
    strh r2, [r0, #10]         ; status = fail
    mov  r2, #1
    strh r2, [r0, #14]         ; reason = 1 (unknown opcode)
    ldrh r2, [r0, #8]
    strh r2, [r0, #12]         ; ack_seq = seq
    mov  r2, #0
    strh r2, [r0, #6]          ; opcode = 0
SlinkHookDone:
    pop  {r0-r3, pc}           ; restore + return to saved lr (Thumb)
.pool
