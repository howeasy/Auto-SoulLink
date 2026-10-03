/* NDS companion ABI: platform-neutral lift of patch/src/trade_targets/abi.h (v2).
 * NOT a capability/admission claim. No target addresses and no GBA/NDS includes
 * beyond compat.h and <stddef.h>; per-title pin headers supply every address.
 *
 * Mailbox, witness struct layout, revision protocol, milestone ORDER and success
 * predicate are the Gen 3 v2 contract. The NDS ABI is nevertheless VERSION 3,
 * because the witness SEMANTICS diverge: while an asynchronous native save is in
 * flight save_status is SLINK_SAVE_PENDING (2). Gen 3 readers reject a witness
 * with PRE_SAVE_OK set unless save_status is 1 or 255, so a Gen 3 reader must
 * not be pointed at an NDS arena. The NDS reader is lua/nds/native_witness.lua.
 *
 * READER RULE (for the future shared witness reader): under ABI >= 3,
 * save_status == 2 (PENDING) is legal only while milestone bits 8 (POST_SAVE_OK)
 * and 16 (FINAL_RESULT) are both clear; PENDING with either bit set is corrupt.
 * Success still requires save_status == 1 and all five milestone bits.
 *
 * Other differences from Gen 3: the blob region carries a versioned
 * record-staging layout (SlinkRecordStageV1), the post-save milestone is reached
 * through an asynchronous begin/poll pair with a native watchdog, and the
 * Emerald-only call records are not lifted.
 *
 * Native writes witnesses; Lua writes mailbox/staging only. Lua records its queue
 * job.posted when it publishes opcode LAST. This is not COMMIT_ENTERED, which is
 * published natively immediately before the first irreversible party mutation.
 * Snapshot: revision odd => updating; read an equal, nonzero even revision before
 * and after copying. Reject wrong epoch/visit/token or milestone command sequence.
 * A beacon alone proves none of visit acceptance, consent, pre-save or readiness.
 */
#ifndef SLINK_NDS_ABI_H
#define SLINK_NDS_ABI_H
#ifdef SLINK_COMPANION_ABI_H
#error "NDS companion ABI and the Gen 3 trade_targets ABI must not share a translation unit"
#endif
#include "compat.h"   /* fixed-width types + SLINK_STATIC_ASSERT: mwccarm and C11 alike */
#include <stddef.h>

#define SLINK_SIGNATURE 0x4B4E4C53u
#define SLINK_ABI_VERSION 3u          /* 3 = witness save_status PENDING; Gen 3 is 2 */
#define SLINK_NDS_STAGE_LAYOUT 1u     /* record-staging layout version (below) */
#define SLINK_ARENA_SIZE 0x1000u      /* Gen 3 heap carve-out size. An NDS arena hosted in a TCM autoload window
                                       * must be at least this large and must not overlap any autoload image
                                       * (the HGSS/hge ITCM block 0x620 and Gen 5 BW block 0x820 are code images,
                                       * not hosting space). Hosting is a per-title decision: Gen 4 hosts it in the
                                       * ITCM arena tail after the autoload end, Gen 5 plans payload-overlay BSS. */
#define SLINK_MAILBOX_OFFSET 0x000u
#define SLINK_WITNESS_OFFSET 0x050u
#define SLINK_BLOB_OFFSET 0x100u      /* holds SlinkRecordStageV1 */
#define SLINK_BLOB_SIZE 600u
#define SLINK_TEXT_OFFSET 0x360u
#define SLINK_TEXT_SIZE 512u
#define SLINK_MENU_OFFSET 0x560u
#define SLINK_MENU_SIZE 384u
#define SLINK_INFO_OFFSET 0x6E0u
#define SLINK_INFO_SIZE 288u
#define SLINK_INFO_LINE_WIDTH 32u     /* BYTES per row; char count = bytes / text width */
#define SLINK_INFO_ROW_COUNT 8u
#define SLINK_INFO_MAX_LINES 6u
#define SLINK_INFO_PAGE_SLOT 7u
#define SLINK_INFO_BAR_WIDTH 38u
#define SLINK_CONTROL_OFFSET 0x800u
#define SLINK_CONTROL_SIZE 0x600u
#define SLINK_RESERVED_OFFSET 0xE00u  /* Gen 3 call region: reserved, unused on NDS v1 */
/* Title-private region: the FIRST 64 BYTES of the reserved region, written by the
 * per-title ROM and read by the host. Its layout and its version number are owned
 * per title (version the field before publishing, publish it LAST), and shared code
 * never reads or writes it. It is state, never a rules channel and never a write
 * permission. 0xE40..SLINK_ARENA_SIZE stays free for a future shared region. */
#define SLINK_TITLE_OFFSET 0xE00u
#define SLINK_TITLE_SIZE 0x40u

/* Maximum staged Pokemon record on any NDS binding (PK4 party 0xEC, PK5 party 0xDC). */
#define SLINK_MAX_RECORD 256u

/* v1 IDs are stable and shared with Gen 3. Removed IDs 10..12 remain reserved.
 * 18 is raw record replacement ONLY, never a successful trade path. 21 requires
 * a prepared visit and finishes only after native scene/evolution AND native
 * post-save completion. 32 is Emerald-only and never advertised on NDS. */
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
    SLINK_OP_MATCH_CALL = 32
};
/* Capability bits. 0..6 are the shared set defined here. 7..15 are reserved for
 * future SHARED capabilities and must read 0 until a shared id is added below.
 * 16..31 are TITLE-PRIVATE: ROM-owned, documented per title, and never read,
 * written or interpreted by shared code. */
enum SlinkCapability {
    SLINK_CAP_DURABLE_TRADE = 1u << 0,
    SLINK_CAP_INFO_PANEL = 1u << 1,
    SLINK_CAP_NATIVE_SOUND = 1u << 2,
    SLINK_CAP_EXPLODE = 1u << 3,
    SLINK_CAP_RIVAL_SWAP = 1u << 4,
    SLINK_CAP_BATTLE_CALC = 1u << 5,
    SLINK_CAP_MATCH_CALL = 1u << 6
};
enum SlinkStatus { SLINK_ST_BUSY = 1, SLINK_ST_OK = 2, SLINK_ST_FAIL = 3 };
/* CLIENT_TOO_OLD means session_epoch is zero (no handshake); a nonzero
 * mismatched epoch is IDENTITY. */
/* Reasons 2..15 are the shared set. 16..31 are reserved for future SHARED reasons
 * and must read 0 until a shared id is added below. 32..63 are TITLE-PRIVATE:
 * documented per title and decoded through the title adapter only, never by
 * shared code. */
enum SlinkFailureReason {
    SLINK_REASON_BAD_ARGS = 2,
    SLINK_REASON_WINDOW_CLOSED = 8,
    SLINK_REASON_UNCERTAIN = 11,
    SLINK_REASON_IDENTITY = 12,
    SLINK_REASON_CLIENT_TOO_OLD = 13,
    SLINK_REASON_WITHDRAW_TOO_LATE = 14,
    SLINK_REASON_SLOTS_UNVIABLE = 15
};
enum SlinkProducerPhase {
    SLINK_PHASE_IDLE = 0, SLINK_PHASE_PRE_SAVE = 1, SLINK_PHASE_READY = 2,
    SLINK_PHASE_SCENE = 3, SLINK_PHASE_DONE = 4, SLINK_PHASE_UNCERTAIN = 5
};
/* Milestone model: pre-save / ready / scene / done / uncertain phases; separate
 * evolution (SCENE_EVOLUTION_DONE), post-save (POST_SAVE_OK) and final-result
 * milestones. POST_SAVE_OK is published only after the native save COMPLETED. */
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
 * UNCERTAIN, retained until reset/reconciliation; never raw-copy or release.
 * SAVE_PENDING (2) is a witness state while an asynchronous native save is in
 * flight; it is not success and fails the durability predicate. */
#define SLINK_SUCCESS_MILESTONES 0x1Fu
#define SLINK_SAVE_OK 1u
#define SLINK_SAVE_PENDING 2u
#define SLINK_SAVE_FAILED 0xFFu

/* Asynchronous native save contract: post_save_begin() only INITIATES. Completion
 * is observed solely through post_save_poll(); any value other than OK or PENDING
 * is treated as FAIL, and so is PENDING past the engine's save_timeout_frames
 * (a native watchdog: UNCERTAIN must stay reachable after COMMIT_ENTERED).
 * Initiating a save is never recorded as POST_SAVE_OK. */
enum SlinkSavePoll {
    SLINK_SAVEPOLL_PENDING = 0, SLINK_SAVEPOLL_OK = 1, SLINK_SAVEPOLL_FAIL = -1
};

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
 * bound to the server's textual token; never infer it from party identity.
 * PREPARE args: slot[0], role[1], reserved[2:4], old PID[4:8], old OT[8:12],
 * visit_id[12:16], token[16:32]. SCENE/WITHDRAW/STATUS repeat this identity.
 * The 32-bit old/received OT word is binding-defined (PK3 +4, PK4/PK5 logical +0x0C).
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

/* Versioned NDS record staging, written by the host at BLOB_OFFSET before the
 * opcode is published. The producer accepts it only if layout_version, binding_id,
 * generation and the raw flag match its record binding and stage_len is exactly
 * the binding's party_len; it then copies stage_len bytes verbatim. claimed_pid /
 * claimed_otid are host assertions, cross-checked against the binding's identity
 * extraction before any engine call; they are never trusted on their own. */
/* Unknown flag bits are a stage refusal. */
enum SlinkStageFlags { SLINK_STAGE_RAW_ENCRYPTED = 1u << 0 };
typedef struct {
    uint16_t layout_version;        /* 0x00: SLINK_NDS_STAGE_LAYOUT */
    uint16_t binding_id;            /* 0x02: SlinkBindingId */
    uint16_t stage_len;             /* 0x04: bytes of record[] that are valid */
    uint8_t generation;             /* 0x06: game generation 3, 4 or 5 */
    uint8_t flags;                  /* 0x07: SlinkStageFlags */
    uint32_t claimed_pid;           /* 0x08 */
    uint32_t claimed_otid;          /* 0x0C */
    uint8_t record[SLINK_MAX_RECORD]; /* 0x10: engine at-rest bytes, word aligned */
} SlinkRecordStageV1;

/* Host stages epoch/request/rows via the owned queue. Native owns drawn_seq,
 * closed_seq and state. ACK alone is not DRAWN; rows stay owned until closed.
 * Request sequence is published last and bound to session_epoch. Rows are
 * SLINK_INFO_LINE_WIDTH bytes; each must hold the binding's text terminator. */
typedef struct {
    uint32_t session_epoch;          /* INFO+0x00, host */
    uint16_t request_seq;            /* INFO+0x04, host */
    uint16_t drawn_seq;              /* INFO+0x06, native */
    uint8_t lines, page, pages, enable; /* INFO+0x08..0x0B, host */
    uint16_t closed_seq;             /* INFO+0x0C, native */
    uint8_t state, result;           /* INFO+0x0E/F, native; state 0 closed/1 opening/2 drawn;
                                       result 0 A/more (only when a next page exists),
                                       0x7F close (B, or A on the last page), valid at closed_seq */
    uint32_t reserved[4];            /* INFO+0x10..0x1F */
    uint8_t text[8][32];             /* INFO+0x20; each row requires bounded terminator */
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
    unsigned i;
    if (w->milestone_seq[SLINK_PRE_SAVE_OK] != prepare_seq) return 0;
    for (i = SLINK_COMMIT_ENTERED; i <= SLINK_FINAL_RESULT; i++)
        if (w->milestone_seq[i] != scene_seq) return 0;
    return w->final_result == SLINK_TRADE_COMMITTED
        && (w->visit_flags & (SLINK_VISIT_ACCEPTED | SLINK_PRE_SAVE_CONSENT))
            == (SLINK_VISIT_ACCEPTED | SLINK_PRE_SAVE_CONSENT)
        && (w->milestones & SLINK_SUCCESS_MILESTONES) == SLINK_SUCCESS_MILESTONES
        && w->save_status == SLINK_SAVE_OK
        && w->received_pid == expected_pid && w->received_otid == expected_otid;
}

SLINK_STATIC_ASSERT(offsetof(SlinkMailboxV2, producer_phase) == 0x48, "producer phase ABI offset");
SLINK_STATIC_ASSERT(sizeof(SlinkMailboxV2) == 0x50, "mailbox ABI size");
SLINK_STATIC_ASSERT(offsetof(SlinkMailboxV2, capabilities) == 0x40, "capability ABI offset");
SLINK_STATIC_ASSERT(sizeof(SlinkTradeWitnessV2) == 0x50, "witness ABI size");
SLINK_STATIC_ASSERT(offsetof(SlinkTradeWitnessV2, milestone_seq) == 0x20, "milestone ABI offset");
SLINK_STATIC_ASSERT(SLINK_MAILBOX_OFFSET + sizeof(SlinkMailboxV2) <= SLINK_WITNESS_OFFSET, "mailbox/witness overlap");
SLINK_STATIC_ASSERT(SLINK_WITNESS_OFFSET + sizeof(SlinkTradeWitnessV2) <= SLINK_BLOB_OFFSET, "witness/blob overlap");
SLINK_STATIC_ASSERT(sizeof(SlinkRecordStageV1) == 0x10 + SLINK_MAX_RECORD, "record stage ABI size");
SLINK_STATIC_ASSERT(offsetof(SlinkRecordStageV1, record) == 0x10, "record stage payload offset");
SLINK_STATIC_ASSERT(offsetof(SlinkRecordStageV1, claimed_pid) == 0x08, "record stage identity offset");
SLINK_STATIC_ASSERT(offsetof(SlinkRecordStageV1, stage_len) == 0x04, "record stage length offset");
SLINK_STATIC_ASSERT(SLINK_BLOB_OFFSET + sizeof(SlinkRecordStageV1) <= SLINK_BLOB_OFFSET + SLINK_BLOB_SIZE, "stage exceeds blob");
SLINK_STATIC_ASSERT(SLINK_BLOB_OFFSET + SLINK_BLOB_SIZE <= SLINK_TEXT_OFFSET, "blob/text overlap");
SLINK_STATIC_ASSERT(SLINK_TEXT_OFFSET + SLINK_TEXT_SIZE <= SLINK_MENU_OFFSET, "text/menu overlap");
SLINK_STATIC_ASSERT(SLINK_MENU_OFFSET + SLINK_MENU_SIZE <= SLINK_INFO_OFFSET, "menu/info overlap");
SLINK_STATIC_ASSERT(SLINK_INFO_OFFSET + SLINK_INFO_SIZE <= SLINK_CONTROL_OFFSET, "info/control overlap");
SLINK_STATIC_ASSERT(sizeof(SlinkInfoV2) == SLINK_INFO_SIZE, "info ABI size");
SLINK_STATIC_ASSERT(offsetof(SlinkInfoV2, text) == SLINK_INFO_TEXT_FIELD, "info text ABI offset");
SLINK_STATIC_ASSERT(offsetof(SlinkInfoV2, closed_seq) == SLINK_INFO_CLOSED_FIELD, "info closed ABI offset");
SLINK_STATIC_ASSERT(sizeof(SlinkControlV2) == 16, "control prefix ABI size");
SLINK_STATIC_ASSERT(offsetof(SlinkControlV2, pi_count) == SLINK_PI_COUNT_FIELD, "NPC counter ABI offset");
SLINK_STATIC_ASSERT(SLINK_CONTROL_OFFSET + SLINK_CONTROL_SIZE == SLINK_RESERVED_OFFSET, "control/reserved overlap");
SLINK_STATIC_ASSERT(SLINK_RESERVED_OFFSET < SLINK_ARENA_SIZE, "arena ABI extent");
SLINK_STATIC_ASSERT(SLINK_TITLE_OFFSET == SLINK_RESERVED_OFFSET
                    && SLINK_TITLE_OFFSET + SLINK_TITLE_SIZE <= SLINK_ARENA_SIZE,
                    "title-private region starts at the reserved base and fits the arena");
SLINK_STATIC_ASSERT(SLINK_ABI_VERSION == 3u, "NDS witness semantics are ABI 3 (Gen 3 is 2)");
SLINK_STATIC_ASSERT(SLINK_SAVE_PENDING != SLINK_SAVE_OK && SLINK_SAVE_PENDING != SLINK_SAVE_FAILED, "pending is neither success nor failure");
SLINK_STATIC_ASSERT(SLINK_INFO_ROW_COUNT * SLINK_INFO_LINE_WIDTH <= sizeof(((SlinkInfoV2 *)0)->text), "info rows");
#endif
