/* T2 target SOURCE candidates: patched_trade_bindings.md sections 1-5.
 * ABI v2 arena/detour/payload are NOT QUALIFIED. READY must remain zero.
 * RR v1 continues through the legacy builder until the v2 delta is proven.
 */
#ifndef SLINK_TARGET_FIRERED_H
#define SLINK_TARGET_FIRERED_H
#define SLINK_TARGET_NAME "firered"
#define SLINK_TARGET_ROM_SHA1 "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"
#define SLINK_TARGET_HEADER "BPRE"
#define SLINK_TARGET_ROM_SIZE 0x1000000u
#define SLINK_TARGET_SYMBOLS "pokefirered.sym"
#define SLINK_TARGET_CODE_CANDIDATE 0x08EB0B20u
#define SLINK_TARGET_DETOUR_CANDIDATE 0x0800051Au
#define SLINK_TARGET_DETOUR_BYTES "3bf1a9f9"
#define SLINK_TARGET_HEAP_BASE 0x02000000u
#define SLINK_TARGET_HEAP_SIZE 0x1C000u
#define SLINK_TARGET_ARENA_BASE 0u
#define SLINK_TARGET_ARENA_SIZE 0x1000u
/* c75f3523 malloc.c:186-191; pokefirered.sym:625-626,1042-1047.
 * Candidate carve-out only: READY stays zero until full lifecycle qualification. */
#define SLINK_TARGET_ARENA_CANDIDATE 0x0201B000u
#define SLINK_TARGET_HEAP_INIT 0x08002B80u
#define SLINK_TARGET_HEAP_INIT_BYTES "00b5044a1060044a"
#define SLINK_TARGET_HEAP_START_PTR 0x03000A38u
#define SLINK_TARGET_HEAP_SIZE_PTR 0x03000A3Cu
#define SLINK_TARGET_PUT_FIRST_HEADER 0x08002948u
#define SLINK_TARGET_ALLOC_INTERNAL 0x0800295Cu
#define SLINK_TARGET_FREE_INTERNAL 0x08002A08u
#define SLINK_TARGET_READY 0u
#endif
