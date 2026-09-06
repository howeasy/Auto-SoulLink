/* INACTIVE research helper. Not included by patch/tools/build.py.
 * No cartridge image or production mailbox is relocated by this file.
 *
 * Proposed entry detour replaces exactly 08002B80..08002B87 with:
 *   ldr r2, [pc, #0]; bx r2; .word slink_heap_tail_guard | 1
 *
 * Accepted calls replay those displaced instructions, then branch to
 * 08002B88 (the original size store). Only caller-scratch r2/r3 are used
 * before replaying push{lr}; r4-r12, caller LR and stack are untouched.
 * The real engine constructs the header and returns normally.
 *
 * Rejection is a non-returning, observable loop with no RAM/stack writes.
 * This prevents a void InitHeap caller continuing after a rejected setup.
 * It is NOT a production recovery policy; activation requires review and
 * positive proof that every reachable initializer has supported arguments.
 */
.syntax unified
.cpu arm7tdmi
.thumb
.section .text.heap_tail_guard, "ax", %progbits
.align 2
.global slink_heap_tail_guard
.type slink_heap_tail_guard, %function
.thumb_func
slink_heap_tail_guard:
    /* A valid game heap has four-byte aligned, in-EWRAM boundaries and
     * room for its 16-byte first header. Guard overflow before range use. */
    movs r2, #3
    tst r0, r2
    bne slink_heap_tail_reject
    tst r1, r2
    bne slink_heap_tail_reject
    cmp r1, #16
    blo slink_heap_tail_reject
    ldr r2, =0x02000000
    cmp r0, r2
    blo slink_heap_tail_reject
    adds r3, r0, r1
    bcs slink_heap_tail_reject
    ldr r2, =0x02040000
    cmp r3, r2
    bhi slink_heap_tail_reject

    ldr r2, =0x0201B800
    cmp r3, r2
    bls .Lreplay                 /* heap ends at/before reservation */
    ldr r3, =0x0201C000
    cmp r0, r3
    bhs .Lreplay                 /* heap begins at/after reservation */
    cmp r0, r2
    bhs slink_heap_tail_reject   /* no room before the reservation */
    subs r2, r2, r0
    cmp r2, #16
    blo slink_heap_tail_reject
    movs r1, r2                  /* clipped size; original r0 preserved */

.Lreplay:
    push {lr}
    ldr r2, =0x03000A38
    str r0, [r2]
    ldr r2, =0x03000A3C
    ldr r3, =0x08002B89
    bx r3
.size slink_heap_tail_guard, .-slink_heap_tail_guard

.global slink_heap_tail_reject
.type slink_heap_tail_reject, %function
.thumb_func
slink_heap_tail_reject:
    b slink_heap_tail_reject
.size slink_heap_tail_reject, .-slink_heap_tail_reject
.ltorg
