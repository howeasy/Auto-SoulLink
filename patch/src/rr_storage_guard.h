#ifndef SLINK_RR_STORAGE_GUARD_H
#define SLINK_RR_STORAGE_GUARD_H
#include "native_mailbox.h"
enum {
    RR_STORAGE_CONTEXT = 20, RR_STORAGE_GUARD = 21, RR_STORAGE_COUNT = 22,
    RR_STORAGE_IDENTITY = 23, RR_STORAGE_OCCUPIED = 24,
    RR_STORAGE_LAST_USABLE = 25, RR_STORAGE_NOT_DEAD = 26
};
#define RR_STORAGE_GUARD_TAG SLINK_STORAGE_GUARD
static inline u32 rr_guard_word(volatile const u8 *p)
{
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}
static inline u8 rr_bytes_empty(volatile const u8 *p, u32 size)
{
    for (u32 i = 0; i < size; i++) if (p[i]) return 0;
    return 1;
}
static inline u8 rr_postbattle_writer_active(volatile const u8 *task)
{
    /* RR DestroyTask clears +4, not the function pointer at +0. */
    if (!task[4]) return 0;
    u32 function = rr_guard_word(task);
    return function == 0x09094295u || function == 0x0909411Du;
}
/* A compressed RR mon preserves the first 28 party-header bytes, including
 * PID +0 and OTID +4. Check byte-wise: compressed slots need not be aligned. */
static inline u16 rr_storage_precondition(volatile const u8 *args, u8 count,
                                          volatile const u8 *source)
{
    if (args[3] != RR_STORAGE_GUARD_TAG) return RR_STORAGE_GUARD;
    if (count > 6 || args[12] != count) return RR_STORAGE_COUNT;
    if (rr_guard_word(source) != rr_guard_word(args + 4)
        || rr_guard_word(source + 4) != rr_guard_word(args + 8)) return RR_STORAGE_IDENTITY;
    return 0;
}
#endif
