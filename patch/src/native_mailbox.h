#ifndef SLINK_NATIVE_MAILBOX_H
#define SLINK_NATIVE_MAILBOX_H
#include <stdint.h>
#include <stddef.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
typedef int8_t s8; typedef int16_t s16; typedef int32_t s32;

/* Existing ABI footprint only. This arena overlaps dormant libc allocator state;
 * ownership remains a release gate, not a claim made by this header. */
#define MAILBOX_ADDR 0x0203F800u
#define SLNK_SIG 0x4B4E4C53u
#define ABI_VER 2u
typedef struct {
    volatile u32 signature;
    volatile u16 abi_version, opcode, seq, status, ack_seq, reason;
    volatile u8 args[32], result[16];
} Mailbox;
#define MB ((Mailbox *)MAILBOX_ADDR)
enum { ST_IDLE = 0, ST_BUSY = 1, ST_OK = 2, ST_FAIL = 3 };
_Static_assert(sizeof(Mailbox) == 64, "mailbox arena must not grow");
_Static_assert(offsetof(Mailbox, args) == 16, "mailbox arguments moved");
_Static_assert(offsetof(Mailbox, result) == 48, "mailbox receipt moved");
void native_mailbox_complete(volatile Mailbox *mailbox, u16 seq, u16 status, u16 reason);
void native_mailbox_describe(volatile Mailbox *mailbox);

#define SLINK_DESCRIPTOR_MAGIC 0x32444C53u /* SLD2 */
#define SLINK_CAPABILITIES 0x1Fu
#define NATIVE_ARGUMENT_BYTES 14u
#define NATIVE_CONTEXT_OFFSET 14u
#define NATIVE_RESERVATION_OFFSET 24u
#define NATIVE_RECEIPT_RESERVATION_OFFSET 8u
typedef struct {
    u32 magic;
    u16 descriptor_version, abi;
    u32 size, capability_mask, mailbox_address;
    u16 mailbox_size, storage_guard;
    char build_id[65], layout_sha256[65];
} NativeDescriptor;
_Static_assert(sizeof(NativeDescriptor) == 156, "descriptor layout changed");
_Static_assert(offsetof(NativeDescriptor, build_id) == 24, "descriptor build offset changed");
_Static_assert(offsetof(NativeDescriptor, layout_sha256) == 89, "descriptor layout offset changed");
extern const NativeDescriptor slink_native_descriptor;
#endif
