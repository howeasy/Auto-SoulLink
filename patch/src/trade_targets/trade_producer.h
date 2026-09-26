/* Shared native transaction controller. Game addresses/calls belong to the
 * target binding. No allocator, encoder, raw-swap fallback or Lua dependency.
 * Callers must provide engine-verified terminal observations, not time guesses.
 */
#ifndef SLINK_TRADE_PRODUCER_H
#define SLINK_TRADE_PRODUCER_H
#include "abi.h"

enum SlinkTradePhase { TP_IDLE, TP_PRE_SAVE, TP_READY, TP_SCENE, TP_DONE, TP_UNCERTAIN };
typedef struct {
    void *context;
    int (*safe_field)(void *);
    int (*locate)(void *, uint32_t, uint32_t); /* unique physical slot, or -1 */
    int (*validate_incoming)(void *, const uint8_t *);
    int (*start_pre_save)(void *);
    int (*poll_pre_save)(void *); /* 0 waiting, 2 consented, 1 saved, negative refused */
    int (*start_scene)(void *, unsigned, const uint8_t *);
    int (*poll_scene)(void *); /* 0 running, 1 field returned, negative terminal abort */
    int (*post_save)(void *);  /* native synchronous return: 1 success, else failure */
    int (*received_key)(void *, unsigned, uint32_t *, uint32_t *);
    uint32_t (*frame)(void *);
} SlinkTradeEngine;
typedef struct {
    uint32_t phase;
    uint16_t prepare_seq, scene_seq;
    uint8_t slot, cancel_scene;
    uint8_t incoming[100];
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
    /* A clobbered mailbox cannot acquire another operation's result. */
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
    s->phase = result == SLINK_TRADE_UNCERTAIN ? TP_UNCERTAIN : TP_DONE;
    tp_ack(m,seq,result == SLINK_TRADE_COMMITTED, result == SLINK_TRADE_UNCERTAIN ? 11u : 0u);
}

/* Called at the real TradeMons entry, before mail removal / record swap. Native
 * binding skips the original mutation AND trade evolution if this returns false.
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

static inline void slink_trade_service(SlinkTradeProducer *s, volatile SlinkMailboxV2 *m,
    volatile SlinkTradeWitnessV2 *w, const volatile uint8_t *blob, const SlinkTradeEngine *e)
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
                if (!e->received_key(e->context,s->slot,&pid,&ot)
                    || pid != tp_word(s->incoming) || ot != tp_word(s->incoming+4)) {
                    tp_finish(s,m,w,s->scene_seq,SLINK_TRADE_UNCERTAIN,e);
                } else {
                    tp_open(w); tp_mark(w,SLINK_SCENE_EVOLUTION_DONE,s->scene_seq,e); tp_close(w);
                    int saved = e->post_save(e->context);
                    tp_open(w);
                    w->save_status = saved == 1 ? SLINK_SAVE_OK : SLINK_SAVE_FAILED;
                    if (saved == 1) {
                        w->received_pid=pid; w->received_otid=ot;
                        tp_mark(w,SLINK_POST_SAVE_OK,s->scene_seq,e);
                    }
                    tp_close(w);
                    tp_finish(s,m,w,s->scene_seq,saved == 1 ? SLINK_TRADE_COMMITTED : SLINK_TRADE_UNCERTAIN,e);
                }
            }
        }
    }
    uint16_t op=m->opcode,seq=m->seq;
    if (!op) return;
    if ((s->phase==TP_PRE_SAVE && op==SLINK_OP_TRADE_PREPARE && seq==s->prepare_seq)
        || (s->phase==TP_SCENE && op==SLINK_OP_TRADE_SCENE && seq==s->scene_seq)) return;
    if (op==SLINK_OP_TRADE_PREPARE) {
        if (s->phase==TP_READY && seq==s->prepare_seq && tp_identity(m,w)) { tp_ack(m,seq,1,0); return; }
        unsigned token=0;
        for (unsigned i=0;i<16;i++) token |= m->args[16+i];
        if ((s->phase!=TP_IDLE && s->phase!=TP_DONE) || !m->session_epoch
            || !tp_word(m->args+12) || !token || !e->safe_field(e->context)
            || (s->phase==TP_DONE && tp_identity(m,w))) { tp_ack(m,seq,0,12); return; }
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
        s->prepare_seq=seq;s->slot=(uint8_t)slot;s->cancel_scene=0;s->phase=TP_PRE_SAVE;
        m->status=SLINK_ST_BUSY;
        if (!e->start_pre_save(e->context)) tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e);
    } else if (!tp_identity(m,w)) {
        tp_ack(m,seq,0,12);
    } else if (op==SLINK_OP_TRADE_STATUS) {
        tp_ack(m,seq,1,0); /* witness remains bound to the original command sequences */
    } else if (op==SLINK_OP_TRADE_WITHDRAW) {
        if (s->phase==TP_READY) tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e);
        else tp_ack(m,seq,0,11); /* running UI/scene is not a certainly unpicked job */
    } else if (op==SLINK_OP_TRADE_SCENE) {
        if (s->phase==TP_DONE && seq==s->scene_seq && w->final_result==SLINK_TRADE_COMMITTED) {
            tp_ack(m,seq,1,0); return;
        }
        if (s->phase!=TP_READY || !e->safe_field(e->context)) { tp_ack(m,seq,0,12); return; }
        int slot=e->locate(e->context,w->old_pid,w->old_otid);
        if (slot<0 || slot>5 || (unsigned)slot!=m->args[0]) { tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e); return; }
        for (unsigned i=0;i<100;i++) s->incoming[i]=blob[i];
        if (!e->validate_incoming(e->context,s->incoming)) { tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e); return; }
        s->scene_seq=seq;s->slot=(uint8_t)slot;s->phase=TP_SCENE;s->cancel_scene=0;
        m->status=SLINK_ST_BUSY;
        if (!e->start_scene(e->context,(unsigned)slot,s->incoming)) tp_finish(s,m,w,seq,SLINK_TRADE_UNCHANGED,e);
    } else {
        tp_ack(m,seq,0,2);
    }
}
#endif
