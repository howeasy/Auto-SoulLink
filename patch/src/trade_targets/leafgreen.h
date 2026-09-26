/* T2 target SOURCE candidates: patched_trade_bindings.md sections 1-5.
 * ABI v2 arena/detour/payload are NOT QUALIFIED. READY must remain zero.
 * RR v1 continues through the legacy builder until the v2 delta is proven.
 */
#ifndef SLINK_TARGET_LEAFGREEN_H
#define SLINK_TARGET_LEAFGREEN_H
#define SLINK_TARGET_NAME "leafgreen"
#define SLINK_TARGET_ROM_SHA1 "574fa542ffebb14be69902d1d36f1ec0a4afd71e"
#define SLINK_TARGET_HEADER "BPGE"
#define SLINK_TARGET_ROM_SIZE 0x1000000u
#define SLINK_TARGET_SYMBOLS "pokeleafgreen.sym"
#define SLINK_TARGET_CODE_CANDIDATE 0x08EB0E14u
#define SLINK_TARGET_DETOUR_CANDIDATE 0x0800051Au
#define SLINK_TARGET_DETOUR_BYTES "3bf195f9"
#define SLINK_TARGET_HEAP_BASE 0x02000000u
#define SLINK_TARGET_HEAP_SIZE 0x1C000u
#define SLINK_TARGET_ARENA_BASE 0u
#define SLINK_TARGET_ARENA_SIZE 0x1000u
#define SLINK_TARGET_READY 0u
#endif
