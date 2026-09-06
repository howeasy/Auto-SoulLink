#ifndef SLINK_NATIVE_MAILBOX_H
#define SLINK_NATIVE_MAILBOX_H
#include <stdint.h>
#include <stddef.h>
#include "native_layout_generated.h"
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
typedef int8_t s8; typedef int16_t s16; typedef int32_t s32;

/* Existing ABI footprint only. This arena overlaps dormant libc allocator state;
 * ownership remains a release gate, not a claim made by this header. */
#define MAILBOX_ADDR SLINK_MAILBOX_ADDR
#define SLNK_SIG SLINK_SIGNATURE
#define ABI_VER SLINK_ABI
typedef struct {
    volatile u32 signature;
    volatile u16 abi_version, opcode, seq, status, ack_seq, reason;
    volatile u8 args[32], result[16];
} Mailbox;
#define MB ((Mailbox *)MAILBOX_ADDR)
enum { ST_IDLE = 0, ST_BUSY = 1, ST_OK = 2, ST_FAIL = 3 };
SLINK_ASSERT_MAILBOX(Mailbox);
void native_mailbox_complete(volatile Mailbox *mailbox, u16 seq, u16 status, u16 reason);
void native_mailbox_describe(volatile Mailbox *mailbox);

#define SLINK_CAPABILITIES SLINK_CAPABILITY_MASK
#define NATIVE_ARGUMENT_BYTES SLINK_ARGUMENT_BYTES
#define NATIVE_CONTEXT_OFFSET SLINK_CONTEXT_OFFSET
#define NATIVE_RESERVATION_OFFSET SLINK_RESERVATION_OFFSET
#define NATIVE_RECEIPT_RESERVATION_OFFSET SLINK_RECEIPT_RESERVATION_OFFSET
typedef struct {
    u32 magic;
    u16 descriptor_version, abi;
    u32 size, capability_mask, mailbox_address;
    u16 mailbox_size, storage_guard;
    char build_id[65], layout_sha256[65];
} NativeDescriptor;
SLINK_ASSERT_NATIVE_DESCRIPTOR(NativeDescriptor);
extern const NativeDescriptor slink_native_descriptor;
#endif
