/* RR-DURABLE: Radical Red's durable native trade runs the shared FR/LG producer
 * (trade_targets/trade_producer.h) unchanged. RR's ABI1 mailbox header (0x00..0x3F) is
 * byte-identical to SlinkMailboxV2's, but RR keeps SwapState/GhostState at mailbox+0x40,
 * so the producer gets a SHADOW v2 mailbox in the free EWRAM tail instead. The shadow's
 * capabilities/session_epoch/producer_phase words (+0x40..+0x4B) are its own and persist;
 * only the 0x40-byte command header is mirrored in and, for a producer-owned opcode,
 * mirrored back. For a v1 opcode the producer only polls its phase (any refusal it writes
 * stays in the shadow) and the v1 dispatcher owns the mailbox. An old RR UPS never
 * writes the tail, so its zero capability word advertises nothing.
 * Host-tested in tests/unit/test_patch_rr_trade_relay.py.
 */
#ifndef SLINK_RR_TRADE_RELAY_H
#define SLINK_RR_TRADE_RELAY_H
#include "trade_targets/trade_producer.h"

static inline int rr_trade_owned(uint16_t op)
{
    return op == SLINK_OP_TRADE_PREPARE || op == SLINK_OP_TRADE_SCENE
        || op == SLINK_OP_TRADE_WITHDRAW || op == SLINK_OP_TRADE_STATUS;
}

/* One frame. Returns 1 when the mailbox opcode belonged to the producer (the v1 dispatcher
 * must then skip it), 0 otherwise. `mb` is the v1 mailbox as 16 words. */
static inline int rr_trade_relay(volatile uint32_t *mb, volatile SlinkMailboxV2 *shadow,
    SlinkTradeProducer *s, volatile SlinkTradeWitnessV2 *w, const volatile uint8_t *blob,
    const SlinkTradeEngine *e)
{
    volatile uint32_t *sh = (volatile uint32_t *)shadow;
    int owned = rr_trade_owned((uint16_t)(mb[1] >> 16));
    for (unsigned i = 0; i < 16; i++) sh[i] = mb[i];
    shadow->capabilities = SLINK_CAP_DURABLE_TRADE;
    slink_trade_service(s, shadow, w, blob, e);
    /* abi/opcode, seq/status, ack/reason, args (unchanged), result; never the signature */
    if (owned) for (unsigned i = 1; i < 16; i++) mb[i] = sh[i];
    return owned;
}
#endif
