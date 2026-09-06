#include "native_mailbox.h"
#ifndef SLINK_NATIVE_BUILD_ID
#error Build through patch/tools/build.py so the descriptor binds actual native inputs.
#endif
#ifndef SLINK_NATIVE_LAYOUT_SHA256
#error Native layout fingerprint is required.
#endif
const NativeDescriptor slink_native_descriptor = {
    SLINK_DESCRIPTOR_MAGIC, 1, ABI_VER, sizeof(NativeDescriptor),
    SLINK_CAPABILITIES, MAILBOX_ADDR, sizeof(Mailbox), 0xA2,
    SLINK_NATIVE_BUILD_ID, SLINK_NATIVE_LAYOUT_SHA256
};

void native_mailbox_complete(volatile Mailbox *mailbox, u16 seq, u16 status, u16 reason)
{
    for (u32 i = 0; i < 8; i++)
        mailbox->result[NATIVE_RECEIPT_RESERVATION_OFFSET + i] = mailbox->args[NATIVE_RESERVATION_OFFSET + i];
    mailbox->reason = reason;
    mailbox->ack_seq = seq;
    mailbox->opcode = 0;
    /* Publish terminal status LAST. Lua copies the receipt before retiring it;
     * only retirement restores IDLE and permits the next operation. */
    mailbox->status = status;
}

void native_mailbox_describe(volatile Mailbox *mailbox)
{
    u32 address = (u32)&slink_native_descriptor;
    for (u32 i = 0; i < 16; i++) mailbox->result[i] = 0;
    for (u32 i = 0; i < 4; i++) mailbox->result[i] = (u8)(address >> (8 * i));
}
