/* Gen 4 (HG/SS) companion trade POLICY -- card C5. Spec: docs/gen4/companion/C5_TRADE_SPEC.md.
 * Header-only C11. It binds the SHARED transaction controller
 * (patch/src/nds/common/trade_producer.h) to Gen 4 game facts and adds exactly one
 * Gen 4 invariant the shared layer cannot know: the destination is the PARTY, and an
 * out-of-party slot is REFUSED rather than asserted.
 *
 * NO game header is included here and none may be: this file compiles unchanged under a
 * host C compiler, which is what lets every falsifier below run without a cartridge.
 * Every address, engine call and OPEN decision lives behind SlinkGen4TradeSeam.
 *
 * Build include paths: -I patch/src/nds/common -I patch/src/nds/gen4.
 *
 * There is NO file-scope object in this header: not a binding table, not a static
 * decoder, not a scratch buffer. Everything mutable is in SlinkGen4TradePolicy, which the
 * CALLER owns (see patch/src/nds/gen4/README.md:50-59 -- a static .bss symbol would move
 * SDK_STATIC_BSS_END = 0x021E5900 and every pinned overlay address above it).
 */
#ifndef SLINK_GEN4_TRADE_POLICY_H
#define SLINK_GEN4_TRADE_POLICY_H

#include "abi.h"
#include "record_binding.h"
#include "trade_producer.h"

/* Bumped only by a deliberate change to this file's layout. */
#define SLINK_GEN4_TRADE_POLICY_MAGIC 0x50475453u /* "STGP" little-endian */

/* The party is the ONLY destination. Owner ruling DECISIONS_2026-10-02_companion.md:12
 * ("It should not. In party only."), recorded at C5_TRADE_SPEC.md:17-19 and collapsed
 * to the single row at :68-72. There is deliberately NO box arm here and none may be
 * added: no PCStorage_PlaceMonInFirstEmptySlotInAnyBox, no CountPCEmptySpace gate, no
 * writable 0x88 scratch. A "deliver to box" path would be new behaviour, not this
 * trade (FEATURE_BAR.md:197-201).
 *
 * 6 is the pinned PK4 party size; PARTY_ASSERT_SLOT asserts on `slot < maxCount`, so
 * the ceiling is a live halt, not a style preference (src/party.c:9-12,
 * include/assert.h:12-16, config.mk:36-37). */
#define SLINK_GEN4_PARTY_SLOTS 6u

/* ------------------------------------------------------------------ the seam
 * Every Gen 4 fact the policy cannot know without the game. A test supplies fakes; the
 * real module supplies the pinned engine calls. Each member is fail-closed: a NULL
 * member refuses the operation it belongs to, so a half-built seam cannot arm a trade
 * and cannot crash the service task.
 *
 * OPEN members (decided by C5 SOURCE, NOT here) are marked with their spec section.
 */
typedef struct {
    void *context;

    /* --- party reads. The only destination facts the policy needs. --- */
    /* Party_GetCount(saveData) (src/party.c). PARTY_ASSERT_SLOT bounds slot < curCount,
     * so this is the FAIL-CLOSED bound the shared locate() gate lacks
     * (C5_TRADE_SPEC.md:268-279, falsifier F4). */
    int (*party_count)(void *ctx);
    /* Decoded PID:OTID of one occupied party slot. Linear scan target for locate(). */
    int (*party_slot_identity)(void *ctx, unsigned slot, SlinkIdentity *out);
    /* Pointer + length of one party slot's AT-REST (encrypted, shuffled) bytes. This is
     * the independent readback source for received_key (C5_TRADE_SPEC.md:301-305, F8 :418). */
    int (*party_slot_record)(void *ctx, unsigned slot, const uint8_t **bytes, uint16_t *len);

    /* --- the script arm --- */
    /* OPEN (C5_TRADE_SPEC.md:262, §3.3 step 1): the slot the SCRIPT VARIABLE carries,
     * read out of the ScrCmdContext the native trade command is handed. The exact
     * context field is unread SOURCE detail; no Slink_Gen4_SelectedSlot symbol exists
     * and none may be added (static .bss is forbidden, README.md:50-59). */
    int (*script_chosen_slot)(void *ctx, unsigned *out_slot);

    /* The ONE irreversible arm: Party_SafeCopyMonToSlot_ResetAprijuiceModifiers
     * (src/party.c:97-105) and, OPEN (C5_TRADE_SPEC.md:266 §3.3 step 5, §7 Q4 :474-477),
     * UpdatePokedexWithReceivedSpecies (mirrors src/npc_trade.c:155). Called only from
     * Slink_Gen4Trade_Commit, after the bounds and the commit marker. */
    int (*commit_party_slot)(void *ctx, unsigned slot, const uint8_t *record, uint16_t len);

    /* --- scene lifecycle --- */
    /* OPEN (C5_TRADE_SPEC.md:484-486, §7 Q6): the Gen 4 predicate for "safe to write". It
     * must be true while the nurse script holds LockAll and false inside the party app. */
    int (*safe_field)(void *ctx);
    /* Initiate the YesNo consent gate (C5_TRADE_SPEC.md §3.5). */
    int (*start_pre_save)(void *ctx);
    /* 0 waiting, 2 consented, 1 saved/ready, negative refused. OPEN
     * (C5_TRADE_SPEC.md:470-473, §7 Q3): Gen 4 is INFERRED to need no pre-commit save,
     * but tp_service only reaches READY when this returns 1, so the consent->ready
     * transition is the adapter's to define. The policy forwards it verbatim. */
    int (*poll_pre_save)(void *ctx);
    /* The scene opened and the record is armed (spec §3.3). */
    int (*scene_start)(void *ctx, unsigned slot, const uint8_t *record, uint16_t len);
    /* 0 running, 1 the field returned, negative terminal abort. OPEN
     * (C5_TRADE_SPEC.md:487-490, §7 Q7): "1 once the script reaches ReleaseAll" is
     * INFERRED and the adapter bound must not exceed the host's 6000-frame SCENE budget
     * (README.md:85-88). */
    int (*poll_scene)(void *ctx);
    /* Initiate ONLY; never success (C5_TRADE_SPEC.md §3.5). OPEN (§7 Q1 :461-465): the
     * Save_PrepareForAsyncWrite mode and its legality from a SysTask are unread. */
    int (*post_save_begin)(void *ctx);
    /* Already mapped to SlinkSavePoll. OPEN (C5_TRADE_SPEC.md:466-469, §7 Q2): the exact
     * WRITE_STATUS_CONTINUE/NEXT/SUCCESS -> PENDING/PENDING/OK mapping is INFERRED. The
     * policy never sees WRITE_STATUS_* and never re-maps a SlinkSavePoll. */
    int (*post_save_poll)(void *ctx);

    /* --- the engine's OWN decode primitives (C5_TRADE_SPEC.md:225-232). No cipher is
     * authored here: MonDecryptSegment + CalcMonChecksum, applied by the game. --- */
    /* Read a little-endian word at a LOGICAL (post-decrypt) offset. Mutates its argument
     * in place in the real implementation -- the policy always hands it a private copy. */
    int (*decode_read_u32)(void *ctx, const uint8_t *at_rest, uint16_t len,
                          uint16_t logical_off, uint32_t *out);
    /* The engine's own integrity check of the at-rest bytes (CalcMonChecksum ==
     * box.checksum). Absent means every record is REFUSED (fail closed). */
    int (*verify)(void *ctx, const uint8_t *at_rest, uint16_t len);

    /* Engine frame counter. REQUIRED at Init: the async-save watchdog is
     * save_timeout_frames-bounded and a frozen clock stalls it forever
     * (trade_producer.h:160-171). */
    uint32_t (*frame)(void *ctx);
} SlinkGen4TradeSeam;

/* ------------------------------------------------------------------ policy state
 * Owns the shared producer, the shared engine and one private decoder buffer. The caller
 * owns the instance; the real module embeds it in the service SysTask's heap block, the
 * host tests declare it on the stack.
 */
struct SlinkGen4TradePolicy;
typedef struct { struct SlinkGen4TradePolicy *owner; } SlinkGen4DecoderCtx;

typedef struct SlinkGen4TradePolicy {
    uint32_t magic;
    const SlinkGen4TradeSeam *seam;
    volatile SlinkTradeWitnessV2 *witness;
    const volatile SlinkRecordStageV1 *stage;
    SlinkTradeProducer producer;   /* the shared lifecycle + both record buffers */
    SlinkTradeEngine engine;       /* the 10 callbacks, all routed through the seam */
    SlinkDecoder decoder;          /* staging decoder; NOT the received_key source */
    SlinkGen4DecoderCtx decoder_ctx;
    _Alignas(4) uint8_t decode_scratch[SLINK_MAX_RECORD];
    uint8_t pending_slot;
    uint8_t pending_valid;
    uint16_t pending_len;
} SlinkGen4TradePolicy;

/* ------------------------------------------------------------------ guarded decoder
 * tp_accept_stage runs the binding's validate/identity ON s->incoming
 * (trade_producer.h:146-155), and the real Gen 4 decode primitives MUTATE their argument
 * in place (C5_TRADE_SPEC.md:242-254). So every read is made against a private copy and
 * s->incoming is left byte-identical to the host stage -- which is falsifier F1: a decoder
 * that decrypts s->incoming in place would hand start_scene a PLAINTEXT record and every
 * later GetMonData on that slot would return garbage.
 */
static inline int slink_gen4_dec_read(void *ctx, const uint8_t *rec, uint16_t len,
                                      uint16_t off, uint32_t *out)
{
    SlinkGen4DecoderCtx *d = (SlinkGen4DecoderCtx *)ctx;
    const SlinkGen4TradeSeam *s;
    unsigned n, i;
    if (!d || !d->owner || !rec || !out) return 0;
    s = d->owner->seam;
    if (!s || !s->decode_read_u32) return 0; /* no engine primitive: FAIL CLOSED */
    n = len < (unsigned)SLINK_MAX_RECORD ? len : (unsigned)SLINK_MAX_RECORD;
    for (i = 0; i < n; i++) d->owner->decode_scratch[i] = rec[i];
    return s->decode_read_u32(s->context, d->owner->decode_scratch, len, off, out) ? 1 : 0;
}

static inline int slink_gen4_dec_verify(void *ctx, const uint8_t *rec, uint16_t len)
{
    SlinkGen4DecoderCtx *d = (SlinkGen4DecoderCtx *)ctx;
    const SlinkGen4TradeSeam *s;
    unsigned n, i;
    if (!d || !d->owner || !rec) return 0;
    s = d->owner->seam;
    if (!s || !s->verify) return 0; /* an absent integrity check refuses the record */
    n = len < (unsigned)SLINK_MAX_RECORD ? len : (unsigned)SLINK_MAX_RECORD;
    for (i = 0; i < n; i++) d->owner->decode_scratch[i] = rec[i];
    return s->verify(s->context, d->owner->decode_scratch, len) ? 1 : 0;
}

/* ------------------------------------------------------------------ party bounds
 * The one invariant this card adds. `slot < Party_GetCount` is what makes the commit
 * fail-closed instead of aborting the cartridge: tp_service's locate() gate bounds
 * slot<0||slot>5 but has no curCount (trade_producer.h:261-262, :287-288), and
 * PARTY_ASSERT_SLOT asserts on a stale or empty-party slot (C5_TRADE_SPEC.md:268-279).
 */
static inline int slink_gen4_slot_live(SlinkGen4TradePolicy *p, unsigned slot)
{
    const SlinkGen4TradeSeam *s;
    int count;
    if (!p || !p->seam) return 0;
    if (slot >= SLINK_GEN4_PARTY_SLOTS) return 0;
    s = p->seam;
    if (!s->party_count) return 0;
    count = s->party_count(s->context);
    if (count <= 0 || slot >= (unsigned)count) return 0;
    return 1;
}

/* ------------------------------------------------------------------ engine callbacks
 * Every one is a seam adapter over `p` (the engine's context IS the policy, because the
 * guarded decoder needs p->decode_scratch).
 */
static inline int slink_gen4_trade_safe(void *ctx)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    return (s && s->safe_field && s->safe_field(s->context)) ? 1 : 0;
}

static inline uint32_t slink_gen4_trade_frame(void *ctx)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    return (s && s->frame) ? s->frame(s->context) : 0u;
}

/* The old mon lives in a party slot: locate() is a bounded scan over the live party, and
 * -1 (no such slot) is what makes tp_service refuse the command at both PREPARE and
 * SCENE (trade_producer.h:261-262, :287-288). */
static inline int slink_gen4_trade_locate(void *ctx, uint32_t pid, uint32_t otid)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    SlinkIdentity got;
    int count, i;
    if (!p || p->magic != SLINK_GEN4_TRADE_POLICY_MAGIC || !s) return -1;
    if (!s->party_count || !s->party_slot_identity) return -1;
    count = s->party_count(s->context);
    if (count <= 0) return -1;
    if ((unsigned)count > SLINK_GEN4_PARTY_SLOTS) count = (int)SLINK_GEN4_PARTY_SLOTS;
    for (i = 0; i < count; i++) {
        if (!s->party_slot_identity(s->context, (unsigned)i, &got)) continue;
        if (got.pid == pid && got.otid == otid) return i;
    }
    return -1;
}

static inline int slink_gen4_trade_pre_start(void *ctx)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    return (s && s->start_pre_save && s->start_pre_save(s->context)) ? 1 : 0;
}

/* An absent gate reads as "the player said no": SLINK_TRADE_UNCHANGED before any
 * mutation (trade_producer.h:206-208). */
static inline int slink_gen4_trade_pre_poll(void *ctx)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    return (s && s->poll_pre_save) ? s->poll_pre_save(s->context) : -1;
}

/* OPEN (§7 Q7): absent means a terminal abort rather than "still running", so a missing
 * adapter cannot leave a trade parked in TP_SCENE forever. */
static inline int slink_gen4_trade_scene_poll(void *ctx)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    return (s && s->poll_scene) ? s->poll_scene(s->context) : -1;
}

static inline int slink_gen4_trade_post_begin(void *ctx)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    return (s && s->post_save_begin && s->post_save_begin(s->context)) ? 1 : 0;
}

static inline int slink_gen4_trade_post_poll(void *ctx)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    return (s && s->post_save_poll) ? s->post_save_poll(s->context) : SLINK_SAVEPOLL_FAIL;
}

/* The scene opens: C5_TRADE_SPEC.md:258-265 step 1-2, then arm. The irreversible write is
 * NOT here -- it is Slink_Gen4Trade_Commit, called from the ScrCmd after the commit
 * marker, exactly as §3.3 orders it.
 *
 * The record handed in is the producer's scratch copy, because slink_binding_gen4_pk4 sets
 * SLINK_RB_COMMIT_MUTATES_INPUT (record_binding.h:167-171). For the party arm that flag is
 * carried by analogy rather than by evidence (C5_TRADE_SPEC.md:204-214); the copy is free
 * and correct, and Slink_Gen4Trade_Commit reads the pristine s->incoming regardless.
 */
static inline int slink_gen4_trade_start_scene(void *ctx, unsigned slot,
                                               const uint8_t *record, uint16_t len)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s;
    unsigned chosen = 0u;
    if (!p || p->magic != SLINK_GEN4_TRADE_POLICY_MAGIC || !p->seam) return 0;
    s = p->seam;
    /* step 1: the slot the SCRIPT VARIABLE carries is the only slot that may be written. */
    if (!s->script_chosen_slot || !s->script_chosen_slot(s->context, &chosen)) return 0;
    if (slot != chosen) return 0;
    /* step 2: FAIL-CLOSED bounds. Asserts are LIVE in this build, so this is a halt guard. */
    if (!slink_gen4_slot_live(p, slot)) return 0;
    if (!record) return 0;
    if (len != slink_binding_stage_len(&slink_binding_gen4_pk4, SLINK_STAGE_OP_TRADE)) return 0;
    p->pending_slot = (uint8_t)slot;
    p->pending_len = len;
    p->pending_valid = 0;
    if (!s->scene_start || !s->scene_start(s->context, slot, record, len)) return 0;
    p->pending_valid = 1;
    return 1;
}

/* The independent readback. It decodes the PARTY SLOT's own at-rest bytes with the same
 * engine primitives, never the staged buffer: a received_key derived from s->incoming
 * agrees with incoming_id by construction and is not a witness at all
 * (record_binding.h PK4 binding note, C5_TRADE_SPEC.md:301-305, falsifier F8 :418). */
static inline int slink_gen4_trade_received(void *ctx, unsigned slot,
                                            uint32_t *pid, uint32_t *ot)
{
    SlinkGen4TradePolicy *p = (SlinkGen4TradePolicy *)ctx;
    const SlinkGen4TradeSeam *s = p ? p->seam : 0;
    const uint8_t *bytes = 0;
    uint16_t len = 0u;
    uint32_t value = 0u;
    if (!p || p->magic != SLINK_GEN4_TRADE_POLICY_MAGIC || !s || !pid || !ot) return 0;
    if (!slink_gen4_slot_live(p, slot)) return 0;
    if (!s->party_slot_record) return 0;
    if (!s->party_slot_record(s->context, slot, &bytes, &len)) return 0;
    if (!bytes || len < 8u) return 0;
    *pid = slink_rb_le32(bytes); /* plaintext personality, +0 */
    if (!p->decoder.read_u32(p->decoder.context, bytes, len,
                             slink_binding_gen4_pk4.otid_logical_off, &value)) return 0;
    *ot = value;
    return 1;
}

/* ------------------------------------------------------------------ lifecycle
 * Init wires the shared engine to the seam. It requires only what makes the async-save
 * watchdog meaningful (a clock, a nonzero bound); every other absent callback refuses its
 * own operation at run time, which is the fail-closed shape the ABI demands.
 */
static inline int Slink_Gen4TradePolicy_Init(SlinkGen4TradePolicy *p,
                                             const SlinkGen4TradeSeam *seam,
                                             volatile SlinkTradeWitnessV2 *witness,
                                             const volatile SlinkRecordStageV1 *stage,
                                             uint32_t save_timeout_frames)
{
    unsigned char *bytes;
    unsigned i;
    if (!p || !seam || !witness || !stage) return 0;
    if (!seam->frame || !save_timeout_frames) return 0;
    bytes = (unsigned char *)(void *)p;
    for (i = 0; i < sizeof *p; i++) bytes[i] = 0u;
    p->seam = seam;
    p->witness = witness;
    p->stage = stage;
    p->decoder_ctx.owner = p;
    p->decoder.context = &p->decoder_ctx;
    p->decoder.read_u32 = slink_gen4_dec_read;
    p->decoder.verify = slink_gen4_dec_verify;
    p->engine.context = p;
    p->engine.save_timeout_frames = save_timeout_frames;
    p->engine.binding = &slink_binding_gen4_pk4;
    p->engine.decoder = &p->decoder;
    p->engine.safe_field = slink_gen4_trade_safe;
    p->engine.locate = slink_gen4_trade_locate;
    p->engine.start_pre_save = slink_gen4_trade_pre_start;
    p->engine.poll_pre_save = slink_gen4_trade_pre_poll;
    p->engine.start_scene = slink_gen4_trade_start_scene;
    p->engine.poll_scene = slink_gen4_trade_scene_poll;
    p->engine.post_save_begin = slink_gen4_trade_post_begin;
    p->engine.post_save_poll = slink_gen4_trade_post_poll;
    p->engine.received_key = slink_gen4_trade_received;
    p->engine.frame = slink_gen4_trade_frame;
    p->magic = SLINK_GEN4_TRADE_POLICY_MAGIC;
    return 1;
}

/* One service visit. Exactly what dispatch.c expects the trade module to do per visit,
 * minus the mailbox header, which the beacon owns (single-writer table,
 * C5_TRADE_SPEC.md §6). */
static inline void Slink_Gen4TradePolicy_Service(SlinkGen4TradePolicy *p,
                                                 volatile SlinkMailboxV2 *m)
{
    if (!p || p->magic != SLINK_GEN4_TRADE_POLICY_MAGIC) return;
    if (!p->witness || !p->stage || !m) return;
    slink_trade_service(&p->producer, m, p->witness, p->stage, &p->engine);
}

/* C5_TRADE_SPEC.md:264 step 3. A policy that is not armed returns 1: an ordinary
 * cartridge NPC trade is not ours, and a vanilla trade must never be blocked. */
static inline int Slink_Gen4Trade_CommitEntered(SlinkGen4TradePolicy *p, unsigned actual_slot)
{
    if (!p || p->magic != SLINK_GEN4_TRADE_POLICY_MAGIC) return 1;
    return slink_trade_commit_entered(&p->producer, p->witness, actual_slot, &p->engine) ? 1 : 0;
}

/* C5_TRADE_SPEC.md:265-266 steps 4-5: the ONE irreversible write. It runs only when the
 * scene armed this exact slot, the slot is still inside the live party, and the commit
 * marker is published -- and it copies s->incoming, which the guarded decoder has left
 * byte-identical to the host stage. */
static inline int Slink_Gen4Trade_Commit(SlinkGen4TradePolicy *p, unsigned actual_slot)
{
    const SlinkGen4TradeSeam *s;
    if (!p || p->magic != SLINK_GEN4_TRADE_POLICY_MAGIC) return 1;
    if (!p->pending_valid || p->pending_slot != (uint8_t)actual_slot) return 0;
    if (!slink_gen4_slot_live(p, actual_slot)) return 0;
    if (!(p->witness->milestones & (1u << SLINK_COMMIT_ENTERED))) return 0;
    s = p->seam;
    if (!s || !s->commit_party_slot) return 0;
    if (p->pending_len != p->producer.incoming_len) return 0;
    if (!s->commit_party_slot(s->context, actual_slot, p->producer.incoming,
                              p->producer.incoming_len)) return 0;
    p->pending_valid = 0;
    return 1;
}

#endif /* SLINK_GEN4_TRADE_POLICY_H */