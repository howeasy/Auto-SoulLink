/* T2/T3 companion ABI v2 skeleton. NOT a capability/admission claim.
 * Existing RR v1 stays supported until producer + profile + client move together.
 * This header is the canonical v2 input for T3's generator; no target addresses.
 *
 * Native writes witnesses; Lua writes mailbox/staging only. Lua records its queue
 * job.posted when it publishes opcode LAST. This is not COMMIT_ENTERED. The latter
 * is published natively immediately before the first irreversible party mutation.
 * Snapshot: revision odd => updating; read an equal, nonzero even revision before
 * and after copying. Reject wrong epoch/visit/token or milestone command sequence.
 * A beacon alone proves none of visit acceptance, consent, pre-save or readiness.
 */
#ifndef SLINK_COMPANION_ABI_H
#define SLINK_COMPANION_ABI_H
#include <stdint.h>
#include <stddef.h>

#define SLINK_SIGNATURE 0x4B4E4C53u
#define SLINK_ABI_VERSION 2u
#define SLINK_ARENA_SIZE 0x1000u
#define SLINK_MAILBOX_OFFSET 0x000u
#define SLINK_WITNESS_OFFSET 0x050u
#define SLINK_BLOB_OFFSET 0x100u
#define SLINK_BLOB_SIZE 600u
#define SLINK_TEXT_OFFSET 0x360u
#define SLINK_TEXT_SIZE 512u
#define SLINK_MENU_OFFSET 0x560u
#define SLINK_MENU_SIZE 384u
#define SLINK_INFO_OFFSET 0x6E0u
#define SLINK_INFO_SIZE 264u
#define SLINK_CONTROL_OFFSET 0x800u
#define SLINK_CONTROL_SIZE 0x800u

/* v1 IDs are stable. Removed IDs 10..12 remain reserved. 18 is raw record
 * replacement ONLY, never a successful trade path. V2 21 requires a prepared
 * visit and finishes only after native scene/evolution AND native post-save. */
enum SlinkOpcode {
    SLINK_OP_PING = 1, SLINK_OP_FORCE_FAINT = 2, SLINK_OP_FORCE_MOVE = 3,
    SLINK_OP_CREATE_MON = 4, SLINK_OP_FORCE_MOVE_SLOT = 5,
    SLINK_OP_SPAWN_PEER_NPC = 6, SLINK_OP_DESPAWN_PEER_NPC = 7,
    SLINK_OP_SHOW_MESSAGE = 8, SLINK_OP_PLAY_FANFARE = 9,
    SLINK_OP_ARM_PEER_INTERACT = 13, SLINK_OP_GHOST_SPAWN = 14,
    SLINK_OP_GHOST_CLEAR = 15, SLINK_OP_SET_ENEMY_PARTY = 16,
    SLINK_OP_SHOW_MENU = 17, SLINK_OP_SET_PARTY_MON = 18,
    SLINK_OP_PLAY_SE = 19, SLINK_OP_CHOOSE_PARTY_MON = 20,
    SLINK_OP_TRADE_SCENE = 21, SLINK_OP_SHOW_CHOICES = 22,
    SLINK_OP_SHOW_BATTLE_MESSAGE = 23, SLINK_OP_DEPOSIT_MON = 24,
    SLINK_OP_WITHDRAW_MON = 25, SLINK_OP_MEMORIALIZE = 26,
    SLINK_OP_SHOW_INFO = 27, SLINK_OP_RIVAL_SWAP = 28,
    SLINK_OP_TRADE_PREPARE = 29, SLINK_OP_TRADE_WITHDRAW = 30,
    SLINK_OP_TRADE_STATUS = 31
};
enum SlinkCapability {
    SLINK_CAP_DURABLE_TRADE = 1u << 0,
    SLINK_CAP_INFO_PANEL = 1u << 1,
    SLINK_CAP_NATIVE_SOUND = 1u << 2,
    SLINK_CAP_EXPLODE = 1u << 3,
    SLINK_CAP_RIVAL_SWAP = 1u << 4,
    SLINK_CAP_BATTLE_CALC = 1u << 5 /* RR only */
};
enum SlinkStatus { SLINK_ST_BUSY = 1, SLINK_ST_OK = 2, SLINK_ST_FAIL = 3 };
enum SlinkTradeMilestone {
    SLINK_PRE_SAVE_OK = 0, SLINK_COMMIT_ENTERED = 1,
    SLINK_SCENE_EVOLUTION_DONE = 2, SLINK_POST_SAVE_OK = 3,
    SLINK_FINAL_RESULT = 4, SLINK_MILESTONE_COUNT = 5
};
enum SlinkVisitFlags {
    SLINK_VISIT_ACCEPTED = 1u << 0,
    SLINK_PRE_SAVE_CONSENT = 1u << 1
};
enum SlinkTradeResult {
    SLINK_TRADE_PENDING = 0, SLINK_TRADE_COMMITTED = 1,
    SLINK_TRADE_UNCHANGED = 2, SLINK_TRADE_UNCERTAIN = 3
};
/* Final success requires all four milestone bits and SAVE_STATUS_OK (1).
 * Refused before mutation => UNCHANGED. Any failure after COMMIT_ENTERED =>
 * UNCERTAIN, retained until reset/reconciliation; never raw-copy or release. */
#define SLINK_SUCCESS_MILESTONES 0x0Fu
#define SLINK_SAVE_OK 1u
#define SLINK_SAVE_FAILED 0xFFu

typedef struct {
    uint32_t signature;              /* 0x00 */
    uint16_t abi_version, opcode;    /* 0x04, 0x06 */
    uint16_t seq, status;            /* 0x08, 0x0A */
    uint16_t ack_seq, reason;        /* 0x0C, 0x0E */
    uint8_t args[32];               /* 0x10 */
    uint8_t result[16];             /* 0x30 */
    uint32_t capabilities;          /* 0x40: only implemented/qualified features */
    uint32_t session_epoch;         /* 0x44: client handshake; zero unarmed, reset clears */
    uint32_t reserved[2];           /* 0x48 */
} SlinkMailboxV2;

/* Every milestone shares immutable epoch/visit/token identity and has its own
 * sequence, because PREPARE and SCENE are separate mailbox commands. A set bit
 * without the matching milestone_seq is not evidence. Token is 16 opaque bytes
 * bound by T3 to the server's textual token; never infer it from party identity.
 * PREPARE args: slot[0], role[1], reserved[2:4], old PID[4:8], old OT[8:12],
 * visit_id[12:16], token[16:32]. SCENE/WITHDRAW/STATUS repeat this identity.
 * accepted visit/consent are native UI results, never writable READY flags. */
typedef struct {
    uint32_t session_epoch;         /* 0x00 */
    uint32_t visit_id;              /* 0x04 */
    uint8_t token[16];              /* 0x08 */
    uint16_t revision;              /* 0x18: publication guard */
    uint16_t visit_flags;           /* 0x1A: acceptance != save consent */
    uint32_t milestones;            /* 0x1C */
    uint16_t milestone_seq[5];      /* 0x20 */
    uint8_t final_result;           /* 0x2A */
    uint8_t save_status;            /* 0x2B */
    uint32_t milestone_frame[5];    /* 0x2C */
    uint32_t old_pid, old_otid;      /* 0x40, 0x44 */
    uint32_t received_pid, received_otid; /* 0x48, 0x4C */
} SlinkTradeWitnessV2;

/* Structural completion gate only. Caller must first bind the coherent witness
 * to its live epoch, token, visit and per-milestone command sequences. This is
 * not evidence of an actual flash write; producer tests/probes must establish it. */
static inline int slink_trade_success_is_durable(const SlinkTradeWitnessV2 *w)
{
    return w->final_result == SLINK_TRADE_COMMITTED
        && (w->visit_flags & (SLINK_VISIT_ACCEPTED | SLINK_PRE_SAVE_CONSENT))
            == (SLINK_VISIT_ACCEPTED | SLINK_PRE_SAVE_CONSENT)
        && (w->milestones & SLINK_SUCCESS_MILESTONES) == SLINK_SUCCESS_MILESTONES
        && w->save_status == SLINK_SAVE_OK;
}

_Static_assert(sizeof(SlinkMailboxV2) == 0x50, "mailbox ABI size");
_Static_assert(offsetof(SlinkMailboxV2, capabilities) == 0x40, "capability ABI offset");
_Static_assert(sizeof(SlinkTradeWitnessV2) == 0x50, "witness ABI size");
_Static_assert(offsetof(SlinkTradeWitnessV2, milestone_seq) == 0x20, "milestone ABI offset");
_Static_assert(SLINK_WITNESS_OFFSET + sizeof(SlinkTradeWitnessV2) <= SLINK_BLOB_OFFSET, "witness/blob overlap");
_Static_assert(SLINK_BLOB_OFFSET + SLINK_BLOB_SIZE <= SLINK_TEXT_OFFSET, "blob/text overlap");
_Static_assert(SLINK_INFO_OFFSET + SLINK_INFO_SIZE <= SLINK_CONTROL_OFFSET, "info/control overlap");
_Static_assert(SLINK_CONTROL_OFFSET + SLINK_CONTROL_SIZE == SLINK_ARENA_SIZE, "arena ABI extent");
#endif
