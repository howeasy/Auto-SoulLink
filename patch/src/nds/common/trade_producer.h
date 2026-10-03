/* Shared native transaction controller, NDS lift of trade_targets/trade_producer.h.
 * Same lifecycle, milestone ordering and refusals as Gen 3. Game addresses/calls
 * and the record format belong to the engine + SlinkRecordBinding. No allocator,
 * encoder, raw-swap fallback or Lua dependency. Callers must provide
 * engine-verified terminal observations, not time guesses.
 *
 * Changes vs Gen 3: the staged record is sized by SLINK_MAX_RECORD and handled via
 * the binding (length, validation, identity); the stage is a versioned
 * SlinkRecordStageV1; post-save is post_save_begin()+post_save_poll() so that
 * initiating a save can never be recorded as POST_SAVE_OK, and a native watchdog
 * (save_timeout_frames) turns an unbounded PENDING into FAIL/UNCERTAIN.
 *
 * Save-timeout invariant: the BOUND is shared, the NUMBER is the adapter. The
 * host's own TRADE_SCENE budget is 6000 frames (lua/gen3/native.lua:177-181); an
 * adapter bound that outlasts it would let the host declare the module poisoned
 * before the native side reaches UNCERTAIN, so adapters should pick a smaller one.
 */
#ifndef SLINK_NDS_TRADE_PRODUCER_H
#define SLINK_NDS_TRADE_PRODUCER_H
#include "abi.h"
#include "record_binding.h"

enum SlinkTradePhase { TP_IDLE=SLINK_PHASE_IDLE, TP_PRE_SAVE=SLINK_PHASE_PRE_SAVE,
    TP_READY=SLINK_PHASE_READY, TP_SCENE=SLINK_PHASE_SCENE,
    TP_DONE=SLINK_PHASE_DONE, TP_UNCERTAIN=SLINK_PHASE_UNCERTAIN };

/* Feature implementation beacon; target READY remains a separate release gate. */
static inline void slink_trade_advertise(volatile SlinkMailboxV2 *m)
{
    m->abi_version = SLINK_ABI_VERSION;
    m->capabilities |= SLINK_CAP_DURABLE_TRADE;
    m->signature = SLINK_SIGNATURE;
}
typedef struct {
    void *context;
    uint32_t save_timeout_frames;      /* REQUIRED nonzero: PENDING longer than this is FAIL */
    const SlinkRecordBinding *binding; /* record length/validation/identity */
    const SlinkDecoder *decoder;       /* decoded-body access; NULL for PK3 */
    int (*safe_field)(void *);
    int (*locate)(void *, uint32_t, uint32_t); /* unique physical slot, or -1 */
    int (*start_pre_save)(void *);
    int (*poll_pre_save)(void *); /* 0 waiting, 2 consented, 1 saved, negative refused */
    int (*start_scene)(void *, unsigned, const uint8_t *, uint16_t); /* slot, record, length */
    int (*poll_scene)(void *); /* 0 running, 1 field returned, negative terminal abort */
    int (*post_save_begin)(void *); /* initiate only: 1 started, else refused. NEVER success. */
    int (*post_save_poll)(void *);  /* SlinkSavePoll; anything but OK/PENDING is FAIL */
    int (*received_key)(void *, unsigned, uint32_t *, uint32_t *);
    uint32_t (*frame)(void *);
} SlinkTradeEngine;
typedef struct {
    uint32_t phase;
    uint16_t prepare_seq, scene_seq;
    uint8_t slot, cancel_scene, saving, reserved;
    uint16_t incoming_len, reserved2;
    uint32_t save_start_frame;        /* stamped from e->frame at post_save_begin */
    SlinkIdentity incoming_id;        /* binding identity of the staged record (host claim, checked) */
    SlinkIdentity received_id;        /* identity OBSERVED by the engine after the swap */
    _Alignas(4) uint8_t incoming[SLINK_MAX_RECORD]; /* native getters use word loads */
    _Alignas(4) uint8_t scratch[SLINK_MAX_RECORD];  /* handed to engines whose commit mutates input */
} SlinkTradeProducer;

static inline uint32_t tp_word(const volatile uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1]<<8) | ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}
static inline void tp_open(volatile SlinkTradeWitnessV2 *w)
{
    uint16_t revision = (uint16_t)(w->revision + 1u);
    if (!(revision & 1u)) revision++;
    w->revision = revision;
}
static inline void tp_close(volatile SlinkTradeWitnessV2 *w)
{
    uint16_t revision = (uint16_t)(w->revision + 1u);
    w->revision = revision ? revision : 2u;
}
static inline void tp_mark(volatile SlinkTradeWitnessV2 *w, unsigned kind, uint16_t seq,
                           const SlinkTradeEngine *e)
{
    w->milestone_seq[kind] = seq;
    w->milestone_frame[kind] = e->frame(e->context);
    w->milestones |= 1u << kind;
}
static inline int tp_identity(const volatile SlinkMailboxV2 *m,
                              const volatile SlinkTradeWitnessV2 *w)
{
    if (!m->session_epoch || m->session_epoch != w->session_epoch
        || tp_word(m->args+12) != w->visit_id
        || tp_word(m->args+4) != w->old_pid || tp_word(m->args+8) != w->old_otid) return 0;
    for (unsigned i=0;i<16;i++) if (m->args[16+i] != w->token[i]) return 0;
    return 1;
}
static inline void tp_ack(volatile SlinkMailboxV2 *m, uint16_t seq, int ok, uint16_t reason)
{
    /* A clobbered mailbox cannot acquire another operation's result. Only the
     * sequence is compared, NOT the opcode: this assumes the host never reuses a
     * seq for a different opcode while a command is outstanding. That Gen 3 guard
     * is unchanged; an asynchronous save widens the window in which it matters. */
    if (m->seq != seq) return;
    m->reason = reason;
    m->status = ok ? SLINK_ST_OK : SLINK_ST_FAIL;
    m->ack_seq = seq;
    m->opcode = 0;
}
static inline void tp_finish(SlinkTradeProducer *s, volatile SlinkMailboxV2 *m,
                              volatile SlinkTradeWitnessV2 *w, uint16_t seq,
                              unsigned result, const SlinkTradeEngine *e)
{
    tp_open(w);
    w->final_result = (uint8_t)result;
    tp_mark(w,SLINK_FINAL_RESULT,seq,e);
    tp_close(w);
    s->saving = 0;
    s->phase = result == SLINK_TRADE_UNCERTAIN ? TP_UNCERTAIN : TP_DONE;
    tp_ack(m,seq,result == SLINK_TRADE_COMMITTED, result == SLINK_TRADE_UNCERTAIN ? 11u : 0u);
}

/* Called at the real trade-commit entry, before the record swap. Native binding
 * skips the original mutation AND trade evolution if this returns false.
 * The scene must then unwind normally; no success or second raw swap is allowed. */
static inline int slink_trade_commit_entered(SlinkTradeProducer *s,
    volatile SlinkTradeWitnessV2 *w, unsigned actual_slot, const SlinkTradeEngine *e)
{
    if (s->phase != TP_SCENE) return 1; /* ordinary cartridge trades are not ours */
    int slot = e->locate(e->context,w->old_pid,w->old_otid);
    if (slot < 0 || (unsigned)slot != actual_slot || actual_slot != s->slot) {
        s->cancel_scene = 1;
        return 0;
    }
    tp_open(w); tp_mark(w,SLINK_COMMIT_ENTERED,s->scene_seq,e); tp_close(w);
    return 1;
}

/* Snapshot and validate the host stage into the producer's own buffer. Returns 1
 * only for an exact, binding-conformant record; every refusal leaves the engine
 * untouched (UNCHANGED). The invariant is stage_len == the binding's declared
 * length for the op (TRADE: trade_stage_len or party_len): no truncation to a
 * fixed size, no oversize tail, no unknown flag bits. */
static inline int tp_accept_stage(SlinkTradeProducer *s, const volatile SlinkRecordStageV1 *st,
                                  const SlinkTradeEngine *e, unsigned op)
{
    const SlinkRecordBinding *b = e->binding;
    uint16_t layout = st->layout_version, id = st->binding_id, len = st->stage_len;
    uint8_t gen = st->generation, flags = st->flags;
    SlinkIdentity claimed = { st->claimed_pid, st->claimed_otid }, actual = {0,0};
    if (!slink_binding_ok(b) || layout != SLINK_NDS_STAGE_LAYOUT || id != b->id
        || gen != b->generation || len != slink_binding_stage_len(b,op) || len > b->max_len
        || len > SLINK_MAX_RECORD || (flags & ~(unsigned)SLINK_STAGE_RAW_ENCRYPTED)
        || ((flags & SLINK_STAGE_RAW_ENCRYPTED) != 0) != ((b->flags & SLINK_RB_RAW_ENCRYPTED) != 0))
        return 0;
    for (unsigned i=0;i<SLINK_MAX_RECORD;i++) s->incoming[i] = i < len ? st->record[i] : 0;
    s->incoming_len = len;
    if (!b->validate(e->decoder,s->incoming,len)) return 0;
    if (!b->identity(e->decoder,s->incoming,len,&actual)) return 0;
    if (!b->same_identity(&actual,&claimed)) return 0;
    s->incoming_id = actual;
    return 1;
}

/* One poll; only an explicit OK or PENDING is believed, anything else is FAIL.
 * PENDING for more than save_timeout_frames since post_save_begin is FAIL too,
 * so UNCERTAIN stays reachable after COMMIT_ENTERED. */
static inline int tp_save_poll(const SlinkTradeProducer *s, const SlinkTradeEngine *e)
{
    int r = e->post_save_poll(e->context);
    if (r == SLINK_SAVEPOLL_OK) return r;
    if (r == SLINK_SAVEPOLL_PENDING
        && (uint32_t)(e->frame(e->context) - s->save_start_frame) <= e->save_timeout_frames)
        return r;
    return SLINK_SAVEPOLL_FAIL;
}

/* Finalize the save phase from one poll result. Only OK reaches POST_SAVE_OK. */
static inline void tp_save_resolve(SlinkTradeProducer *s, volatile SlinkMailboxV2 *m,
    volatile SlinkTradeWitnessV2 *w, int polled, const SlinkTradeEngine *e)
{
    if (polled == SLINK_SAVEPOLL_PENDING) return;
    int ok = polled == SLINK_SAVEPOLL_OK;
    tp_open(w);
    w->save_status = ok ? SLINK_SAVE_OK : SLINK_SAVE_FAILED;
    if (ok) {
        /* the identity the engine OBSERVED at the same_identity check, not the host claim */
        w->received_pid = s->received_id.pid; w->received_otid = s->received_id.otid;
        tp_mark(w,SLINK_POST_SAVE_OK,s->scene_seq,e);
    }
    tp_close(w);
    tp_finish(s,m,w,s->scene_seq,ok ? SLINK_TRADE_COMMITTED : SLINK_TRADE_UNCERTAIN,e);
}

static inline void tp_service(SlinkTradeProducer *s, volatile SlinkMailboxV2 *m,
    volatile SlinkTradeWitnessV2 *w, const volatile SlinkRecordStageV1 *stage,
    const SlinkTradeEngine *e)
{
    if (s->phase == TP_PRE_SAVE) {
        int result = e->poll_pre_save(e->context);
        if (result == 2) {
            tp_open(w); w->visit_flags |= SLINK_PRE_SAVE_CONSENT; tp_close(w);
        } else if (result == 1) {
            tp_open(w);
            w->visit_flags |= SLINK_PRE_SAVE_CONSENT;
            w->save_status = SLINK_SAVE_OK;
            tp_mark(w,SLINK_PRE_SAVE_OK,s->prepare_seq,e);
            tp_close(w);
            s->phase = TP_READY;
            tp_ack(m,s->prepare_seq,1,0);
        } else if (result < 0) {
            tp_finish(s,m,w,s->prepare_seq,SLINK_TRADE_UNCHANGED,e);
        }
    } else if (s->phase == TP_SCENE && s->saving) {
        /* Native save in flight: only the poll can resolve it. */
        tp_save_resolve(s,m,w,tp_save_poll(s,e),e);
    } else if (s->phase == TP_SCENE) {
        int result = e->poll_scene(e->context);
        if (result) {
            int committed = !!(w->milestones & (1u<<SLINK_COMMIT_ENTERED));
            if (result < 0 || s->cancel_scene || !committed) {
                /* Missing a marker is not proof that the engine did not swap.
                 * Only our explicit guarded abort suppresses mutation/evolution. */
                tp_finish(s,m,w,s->scene_seq,
                    !committed && s->cancel_scene ? SLINK_TRADE_UNCHANGED : SLINK_TRADE_UNCERTAIN,e);
            } else {
                uint32_t pid=0,ot=0;
                SlinkIdentity got;
                if (!e->received_key(e->context,s->slot,&pid,&ot)) {
                    tp_finish(s,m,w,s->scene_seq,SLINK_TRADE_UNCERTAIN,e);
                } else {
                    got.pid=pid; got.otid=ot;
                    s->received_id = got;
                    if (!e->binding->same_identity(&got,&s->incoming_id)) {
                        tp_finish(s,m,w,s->scene_seq,SLINK_TRADE_UNCERTAIN,e);
                    } else {
                        tp_open(w); tp_mark(w,SLINK_SCENE_EVOLUTION_DONE,s->scene_seq,e); tp_close(w);
                        if (!e->post_save_begin(e->context)) {
                            tp_open(w); w->save_status = SLINK_SAVE_FAILED; tp_close(w);
                            tp_finish(s,m,w,s->scene_seq,SLINK_TRADE_UNCERTAIN,e);
                        } else {
                            s->saving = 1;
                            s->save_start_frame = e->frame(e->context);
                            tp_open(w); w->save_status = SLINK_SAVE_PENDING; tp_close(w);
                            /* A synchronous engine may already be complete; POST_SAVE_OK
                             * still comes only from the poll, never from begin. */
                            tp_save_resolve(s,m,w,tp_save_poll(s,e),e);
                        }
                    }
                }
            }
        }
    }
    uint16_t op=m->opcode,seq=m->seq;
    if (!op) return;
    /* Foreign opcodes (sound/panel producers) are theirs; the state machine above ran anyway
     * so the async save watchdog keeps ticking. */
    if (op != SLINK_OP_TRADE_PREPARE && op != SLINK_OP_TRADE_SCENE
        && op != SLINK_OP_TRADE_WITHDRAW && op != SLINK_OP_TRADE_STATUS) return;
    if ((s->phase==TP_PRE_SAVE && op==SLINK_OP_TRADE_PREPARE && seq==s->prepare_seq)
        || (s->phase==TP_SCENE && op==SLINK_OP_TRADE_SCENE && seq==s->scene_seq)) return;
    if (op==SLINK_OP_TRADE_PREPARE) {
        if (s->phase==TP_READY && seq==s->prepare_seq && tp_identity(m,w)) { tp_ack(m,seq,1,0); return; }
        unsigned token=0;
        for (unsigned i=0;i<16;i++) token |= m->args[16+i];
        if ((s->phase!=TP_IDLE && s->phase!=TP_DONE) || !m->session_epoch
            || !tp_word(m->args+12) || !token || !e->safe_field(e->context)
            || (s->phase==TP_DONE && tp_identity(m,w))) { tp_ack(m,seq,0,12); return; }
        if (!slink_binding_ok(e->binding) || !e->save_timeout_frames) { tp_ack(m,seq,0,SLINK_REASON_BAD_ARGS); return; }
        int slot=e->locate(e->context,tp_word(m->args+4),tp_word(m->args+8));
        if (slot<0 || slot>5 || (unsigned)slot!=m->args[0] || m->args[1]>1) { tp_ack(m,seq,0,2); return; }
        tp_open(w);
        w->session_epoch=m->session_epoch;w->visit_id=tp_word(m->args+12);
        for (unsigned i=0;i<16;i++) w->token[i]=m->args[16+i];
        w->old_pid=tp_word(m->args+4);w->old_otid=tp_word(m->args+8);
        w->received_pid=0;w->received_otid=0;w->milestones=0;
        for (unsigned i=0;i<5;i++) { w->milestone_seq[i]=0;w->milestone_frame[i]=0; }
        w->visit_flags=SLINK_VISIT_ACCEPTED;w->save_status=0;w->final_result=SLINK_TRADE_PENDING;
        tp_close(w);
        s->prepare_seq=seq;s->slot=(uint8_t)slot;s->cancel_scene=0;s->saving=0;s->phase=TP_PRE_SAVE;
        m->status=SLINK_ST_BUSY;
        if (!e->start_pre_save(e->context)) tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e);
    } else if (!tp_identity(m,w)) {
        tp_ack(m,seq,0,12);
    } else if (op==SLINK_OP_TRADE_STATUS) {
        tp_ack(m,seq,1,0); /* witness remains bound to the original command sequences */
    } else if (op==SLINK_OP_TRADE_WITHDRAW) {
        if (s->phase==TP_READY) tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e);
        else tp_ack(m,seq,0,SLINK_REASON_WITHDRAW_TOO_LATE);
    } else if (op==SLINK_OP_TRADE_SCENE) {
        if (s->phase==TP_DONE && seq==s->scene_seq && w->final_result==SLINK_TRADE_COMMITTED) {
            tp_ack(m,seq,1,0); return;
        }
        if (s->phase!=TP_READY) { tp_ack(m,seq,0,12); return; }
        if (!e->safe_field(e->context)) { tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e); return; }
        int slot=e->locate(e->context,w->old_pid,w->old_otid);
        if (slot<0 || slot>5 || (unsigned)slot!=m->args[0]) { tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e); return; }
        if (!tp_accept_stage(s,stage,e,SLINK_STAGE_OP_TRADE)) { tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e); return; }
        s->scene_seq=seq;s->slot=(uint8_t)slot;s->phase=TP_SCENE;s->cancel_scene=0;s->saving=0;
        m->status=SLINK_ST_BUSY;
        const uint8_t *handed = s->incoming;
        if (e->binding->flags & SLINK_RB_COMMIT_MUTATES_INPUT) {
            /* must-not-alias: the engine may scribble on its argument */
            for (unsigned i=0;i<s->incoming_len;i++) s->scratch[i] = s->incoming[i];
            handed = s->scratch;
        }
        if (!e->start_scene(e->context,(unsigned)slot,handed,s->incoming_len))
            tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e);
    }
}
/* Publish ownership after every service path, including an identity rejection.
 * Aligned u32 write is atomic on ARM; host samples only with CPU paused. It is
 * independent of the host-written epoch and cannot be cleared by a rebind.
 */
static inline void slink_trade_service(SlinkTradeProducer *s, volatile SlinkMailboxV2 *m,
    volatile SlinkTradeWitnessV2 *w, const volatile SlinkRecordStageV1 *stage,
    const SlinkTradeEngine *e)
{
    m->producer_phase=s->phase;
    tp_service(s,m,w,stage,e);
    m->producer_phase=s->phase;
}
#endif
