/* T2 target SOURCE candidates: patched_trade_bindings.md sections 1-5.
 * ABI v2 arena/detour/payload are NOT QUALIFIED. READY must remain zero.
 * RR v1 continues through the legacy builder until the v2 delta is proven.
 */
#ifndef SLINK_TARGET_EMERALD_H
#define SLINK_TARGET_EMERALD_H
#define SLINK_TARGET_NAME "emerald"
#define SLINK_TARGET_ROM_SHA1 "f3ae088181bf583e55daf962a92bb46f4f1d07b7"
#define SLINK_TARGET_HEADER "BPEE"
#define SLINK_TARGET_ROM_SIZE 0x1000000u
#define SLINK_TARGET_SYMBOLS "pokeemerald.sym"
#define SLINK_TARGET_CODE_CANDIDATE 0x08E3CF64u
#define SLINK_TARGET_DETOUR_CANDIDATE 0x0800051Cu
#define SLINK_TARGET_DETOUR_BYTES "10b5074c20680028"
#define SLINK_TARGET_HEAP_BASE 0x02000000u
#define SLINK_TARGET_HEAP_SIZE 0x1C000u
#define SLINK_TARGET_ARENA_BASE 0u
#define SLINK_TARGET_ARENA_SIZE 0x1000u
#define SLINK_TARGET_READY 0u
/* SOURCE-only callback contract: entry contains a PC-relative load. A future
 * native composition must relocate it and continue the original two callbacks.
 * No Emerald candidate build path is enabled by these declarations. */
#define SLINK_TARGET_FRAME_REPLAY_REQUIRED 1u
#define SLINK_TARGET_FRAME_ENTRY 0x0800051Cu
#define SLINK_TARGET_FRAME_BYTES "10b5074c20680028"
#define SLINK_TARGET_FRAME_RESUME 0x08000525u
#define SLINK_TARGET_FRAME_GMAIN_LITERAL 0x0800053Cu
#define SLINK_TARGET_GMAIN 0x030022C0u
#define SLINK_TARGET_FRAME_REPLAY_ASM "push {r4,lr}\n ldr r4,=0x030022c0\n ldr r0,[r4]\n cmp r0,#0\n ldr r3,=0x08000525\n bx r3\n"
#endif
