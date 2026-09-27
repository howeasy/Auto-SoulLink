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
#define SLINK_INFO_SIZE 288u
#define SLINK_INFO_LINE_WIDTH 32u
#define SLINK_INFO_ROW_COUNT 8u
#define SLINK_INFO_MAX_LINES 6u
#define SLINK_INFO_PAGE_SLOT 7u
#define SLINK_INFO_BAR_WIDTH 38u
#define SLINK_CONTROL_OFFSET 0x800u
#define SLINK_CONTROL_SIZE 0x600u
#define SLINK_CALL_WITNESS_OFFSET 0xE00u
#define SLINK_CALL_RECORD_OFFSET 0xE40u
#define SLINK_CALL_COOLDOWN_FRAMES 10800u

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
    SLINK_OP_TRADE_STATUS = 31,
    SLINK_OP_MATCH_CALL = 32 /* Emerald only; ACK is queued/copied, not delivered */
};
enum SlinkCapability {
    SLINK_CAP_DURABLE_TRADE = 1u << 0,
    SLINK_CAP_INFO_PANEL = 1u << 1,
    SLINK_CAP_NATIVE_SOUND = 1u << 2,
    SLINK_CAP_EXPLODE = 1u << 3,
    SLINK_CAP_RIVAL_SWAP = 1u << 4,
    SLINK_CAP_BATTLE_CALC = 1u << 5, /* RR only */
    SLINK_CAP_MATCH_CALL = 1u << 6  /* Emerald only; absent => no phone writes */
};
enum SlinkStatus { SLINK_ST_BUSY = 1, SLINK_ST_OK = 2, SLINK_ST_FAIL = 3 };
/* ABI v2 reasons only: RR v1 has legacy meanings for 11/12. Decode by ABI.
 * CLIENT_TOO_OLD means session_epoch is zero (no v2 handshake); it does not
 * establish the client's actual version. A nonzero mismatched epoch is IDENTITY.
 */
enum SlinkFailureReason {
    SLINK_REASON_BAD_ARGS = 2,
    SLINK_REASON_WINDOW_CLOSED = 8,
    SLINK_REASON_UNCERTAIN = 11,
    SLINK_REASON_IDENTITY = 12,
    SLINK_REASON_CLIENT_TOO_OLD = 13,
    SLINK_REASON_WITHDRAW_TOO_LATE = 14,
    SLINK_REASON_SLOTS_UNVIABLE = 15,
    SLINK_REASON_CALL_BUSY = 16,
    SLINK_REASON_CALL_UNAVAILABLE = 17,
    SLINK_REASON_CALL_COOLDOWN = 18
};
enum SlinkProducerPhase {
    SLINK_PHASE_IDLE = 0, SLINK_PHASE_PRE_SAVE = 1, SLINK_PHASE_READY = 2,
    SLINK_PHASE_SCENE = 3, SLINK_PHASE_DONE = 4, SLINK_PHASE_UNCERTAIN = 5
};
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
/* Final success requires all five milestone bits and SAVE_STATUS_OK (1).
 * Refused before mutation => UNCHANGED. Any failure after COMMIT_ENTERED =>
 * UNCERTAIN, retained until reset/reconciliation; never raw-copy or release. */
#define SLINK_SUCCESS_MILESTONES 0x1Fu
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
    uint32_t producer_phase;        /* 0x48: native-only atomic phase, not epoch-retagged */
    uint32_t reserved;              /* 0x4C */
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

/* docs/protocol.md phone_data: fallen=1, dead_zone=2, first_link=3;
 * lower event ID wins pending priority. Stage at TEXT_OFFSET, copy natively
 * into CALL_RECORD_OFFSET before ACK, and retain through COMPLETE. Every name
 * must contain 0xFF within its array. Species IDs are u16, never GB-size bytes.
 * Neither opcode acceptance nor ARMED is delivery. Publish DELIVERED only on
 * actual Match Call UI entry, then COMPLETE when no native UI owns the text. */
typedef struct {
    uint8_t event, has_names;
    uint16_t caller_species, receiver_species;
    uint8_t trainer[8], caller_nick[11], receiver_nick[11];
} SlinkCallRecordV2;
enum SlinkCallPhase {
    SLINK_CALL_EMPTY = 0, SLINK_CALL_ARMED = 1, SLINK_CALL_DELIVERED = 2,
    SLINK_CALL_REFUSED = 3, SLINK_CALL_COMPLETE = 4
};
typedef struct {
    uint32_t session_epoch;
    uint16_t seq, revision; /* same odd/even snapshot rule; bind epoch + seq */
    uint8_t phase, event;
    uint16_t reason;
    uint32_t armed_frame, delivered_frame;
    uint32_t reserved[3];
} SlinkCallWitnessV2;

/* Host stages epoch/request/rows via the owned queue. Native owns drawn_seq,
 * closed_seq and state. ACK alone is not DRAWN; rows stay owned until closed.
 * Request sequence is published last and bound to session_epoch. */
typedef struct {
    uint32_t session_epoch;          /* INFO+0x00, host */
    uint16_t request_seq;            /* INFO+0x04, host */
    uint16_t drawn_seq;              /* INFO+0x06, native */
    uint8_t lines, page, pages, enable; /* INFO+0x08..0x0B, host */
    uint16_t closed_seq;             /* INFO+0x0C, native */
    uint8_t state, result;           /* INFO+0x0E/F, native; state 0 closed/1 opening/2 drawn;
                                       result 0 A/more, 0x7F B/close, valid at closed_seq */
    uint32_t reserved[4];            /* INFO+0x10..0x1F */
    uint8_t text[8][32];             /* INFO+0x20; each row requires bounded EOS */
} SlinkInfoV2;
#define SLINK_INFO_EPOCH_FIELD 0u
#define SLINK_INFO_REQUEST_FIELD 4u
#define SLINK_INFO_DRAWN_FIELD 6u
#define SLINK_INFO_LINES_FIELD 8u
#define SLINK_INFO_PAGE_FIELD 9u
#define SLINK_INFO_PAGES_FIELD 10u
#define SLINK_INFO_ENABLE_FIELD 11u
#define SLINK_INFO_CLOSED_FIELD 12u
#define SLINK_INFO_STATE_FIELD 14u
#define SLINK_INFO_RESULT_FIELD 15u
#define SLINK_INFO_TEXT_FIELD 32u

typedef struct {
    uint32_t session_epoch;          /* CONTROL+0x00, host configuration binding */
    uint32_t pi_count;               /* CONTROL+0x04, native NPC interaction count */
    uint8_t tn_enable;               /* CONTROL+0x08, host enables companion NPC */
    uint8_t calc_off;                /* CONTROL+0x09, host; RR CAP_BATTLE_CALC only */
    uint8_t reserved[6];
} SlinkControlV2;
#define SLINK_CONTROL_EPOCH_FIELD 0u
#define SLINK_PI_COUNT_FIELD 4u
#define SLINK_PI_COUNT_WIDTH 4u
#define SLINK_TN_ENABLE_FIELD 8u
#define SLINK_CALC_OFF_FIELD 9u

/* Structural completion gate only. Caller must first bind the coherent witness
 * to its live epoch, token, visit and per-milestone command sequences. This is
 * not evidence of an actual flash write; producer tests/probes must establish it. */
static inline int slink_trade_success_is_durable(const SlinkTradeWitnessV2 *w,
                                                uint16_t prepare_seq, uint16_t scene_seq,
                                                uint32_t expected_pid, uint32_t expected_otid)
{
    if (w->milestone_seq[SLINK_PRE_SAVE_OK] != prepare_seq) return 0;
    for (unsigned i = SLINK_COMMIT_ENTERED; i <= SLINK_FINAL_RESULT; i++)
        if (w->milestone_seq[i] != scene_seq) return 0;
    return w->final_result == SLINK_TRADE_COMMITTED
        && (w->visit_flags & (SLINK_VISIT_ACCEPTED | SLINK_PRE_SAVE_CONSENT))
            == (SLINK_VISIT_ACCEPTED | SLINK_PRE_SAVE_CONSENT)
        && (w->milestones & SLINK_SUCCESS_MILESTONES) == SLINK_SUCCESS_MILESTONES
        && w->save_status == SLINK_SAVE_OK
        && w->received_pid == expected_pid && w->received_otid == expected_otid;
}

/* Native strings have a bounded source field even when its last byte is not
 * EOS. Capacity includes the required 0xFF terminator (RR regression 2c553181).
 * Target bindings supply capacities; never reuse RR's Var3=20 for Emerald. */
static inline void slink_copy_name_bounded(volatile uint8_t *destination, uint32_t capacity,
                                         const volatile uint8_t *source, uint32_t source_length)
{
    uint32_t i = 0;
    if (!capacity) return;
    while (i < source_length && i + 1 < capacity && source[i] != 0xFFu) {
        destination[i] = source[i];
        i++;
    }
    destination[i] = 0xFFu;
}

_Static_assert(offsetof(SlinkMailboxV2, producer_phase) == 0x48, "producer phase ABI offset");
_Static_assert(sizeof(SlinkMailboxV2) == 0x50, "mailbox ABI size");
_Static_assert(offsetof(SlinkMailboxV2, capabilities) == 0x40, "capability ABI offset");
_Static_assert(sizeof(SlinkTradeWitnessV2) == 0x50, "witness ABI size");
_Static_assert(offsetof(SlinkTradeWitnessV2, milestone_seq) == 0x20, "milestone ABI offset");
_Static_assert(SLINK_WITNESS_OFFSET + sizeof(SlinkTradeWitnessV2) <= SLINK_BLOB_OFFSET, "witness/blob overlap");
_Static_assert(SLINK_BLOB_OFFSET + SLINK_BLOB_SIZE <= SLINK_TEXT_OFFSET, "blob/text overlap");
_Static_assert(SLINK_INFO_OFFSET + SLINK_INFO_SIZE <= SLINK_CONTROL_OFFSET, "info/control overlap");
_Static_assert(sizeof(SlinkCallRecordV2) == 36, "call record ABI size");
_Static_assert(sizeof(SlinkInfoV2) == SLINK_INFO_SIZE, "info ABI size");
_Static_assert(offsetof(SlinkInfoV2, text) == SLINK_INFO_TEXT_FIELD, "info text ABI offset");
_Static_assert(offsetof(SlinkInfoV2, closed_seq) == SLINK_INFO_CLOSED_FIELD, "info closed ABI offset");
_Static_assert(sizeof(SlinkControlV2) == 16, "control prefix ABI size");
_Static_assert(offsetof(SlinkControlV2, pi_count) == SLINK_PI_COUNT_FIELD, "NPC counter ABI offset");
_Static_assert(sizeof(SlinkCallWitnessV2) == 32, "call witness ABI size");
_Static_assert(SLINK_CONTROL_OFFSET + SLINK_CONTROL_SIZE == SLINK_CALL_WITNESS_OFFSET, "control/call overlap");
_Static_assert(SLINK_CALL_WITNESS_OFFSET + sizeof(SlinkCallWitnessV2) <= SLINK_CALL_RECORD_OFFSET, "call witness/record overlap");
_Static_assert(SLINK_CALL_RECORD_OFFSET + sizeof(SlinkCallRecordV2) <= SLINK_ARENA_SIZE, "arena ABI extent");
#endif
