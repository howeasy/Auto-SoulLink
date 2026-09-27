/* Match Call ownership controller. Native Emerald adapter is a separate gate. */
#ifndef SLINK_CALL_PRODUCER_H
#define SLINK_CALL_PRODUCER_H
#include "trade_producer.h"
typedef struct {
    uint32_t last_delivery;
    uint8_t active,ui_owned,has_delivery,ack_ok;
} SlinkCallProducer;
typedef struct {
    void *context;
    int (*available)(void *); /* device/feature eligibility, not a UI-window wait */
    int (*safe)(void *);
    int (*start)(void *,const volatile SlinkCallRecordV2 *);
    int (*poll)(void *); /* 0 pending, 1 actually visible, 2 released, -1 failed/released */
    uint32_t (*frame)(void *);
} SlinkCallEngine;
static inline void call_open(volatile SlinkCallWitnessV2 *w)
{
    uint16_t rev=(uint16_t)(w->revision+1u);
    if (!(rev&1u)) rev++;
    w->revision=rev;
}
static inline void call_close(volatile SlinkCallWitnessV2 *w)
{
    uint16_t rev=(uint16_t)(w->revision+1u);
    w->revision=rev?rev:2u;
}
static inline void call_phase(volatile SlinkCallWitnessV2 *w,unsigned phase,unsigned reason)
{
    call_open(w);w->phase=(uint8_t)phase;w->reason=(uint16_t)reason;call_close(w);
}
static inline int call_name(const volatile uint8_t *name,unsigned size)
{
    for (unsigned i=0;i<size;i++) {
        if (name[i]==0xffu) return 1;
        if (name[i]>=0xf7u) return 0; /* no text commands/placeholders in names */
    }
    return 0;
}
static inline int call_record_valid(const volatile SlinkCallRecordV2 *r,unsigned event)
{
    return event>=1 && event<=3 && r->event==event && r->has_names<=1
        && (!r->has_names || r->trainer[0]!=0xffu)
        && call_name(r->trainer,8) && call_name(r->caller_nick,11) && call_name(r->receiver_nick,11);
    /* Species0/out-of-range are absent metadata, not rejection of the generic call. */
}
static inline void call_new_witness(volatile SlinkCallWitnessV2 *w,const volatile SlinkMailboxV2 *m,
                                   unsigned phase,unsigned reason,uint32_t frame)
{
    call_open(w);
    w->session_epoch=m->session_epoch;w->seq=m->seq;w->event=m->args[0];
    w->phase=(uint8_t)phase;w->reason=(uint16_t)reason;
    w->armed_frame=phase==SLINK_CALL_ARMED?frame:0;w->delivered_frame=0;
    call_close(w);
}
static inline void slink_call_service(SlinkCallProducer *s,volatile SlinkMailboxV2 *m,
    volatile SlinkCallWitnessV2 *w,volatile SlinkCallRecordV2 *owned,
    const volatile SlinkCallRecordV2 *input,const SlinkCallEngine *e)
{
    uint32_t now=e->frame(e->context);
    if (s->active && s->ui_owned) {
        int state=e->poll(e->context);
        if (state==1 && w->phase==SLINK_CALL_ARMED) {
            call_open(w);w->phase=SLINK_CALL_DELIVERED;w->delivered_frame=now;call_close(w);
            s->last_delivery=now;s->has_delivery=1;
        } else if (state==2 || state==-1) {
            int delivered=w->phase==SLINK_CALL_DELIVERED;
            call_phase(w,delivered?SLINK_CALL_COMPLETE:SLINK_CALL_REFUSED,
                       delivered?0:SLINK_REASON_CALL_UNAVAILABLE);
            s->active=0;s->ui_owned=0;
        }
    }
    if (s->active && !s->ui_owned && m->session_epoch!=w->session_epoch) {
        s->active=0;call_phase(w,SLINK_CALL_EMPTY,0);
    }
    if (s->active && !s->ui_owned && e->safe(e->context)) {
        if (e->start(e->context,owned)) s->ui_owned=1;
        else { s->active=0;call_phase(w,SLINK_CALL_REFUSED,SLINK_REASON_CALL_UNAVAILABLE); }
    }
    if (m->opcode!=SLINK_OP_MATCH_CALL) return;
    uint16_t seq=m->seq;
    if (w->phase!=SLINK_CALL_EMPTY && w->session_epoch==m->session_epoch && w->seq==seq) {
        if (w->event!=m->args[0]) { tp_ack(m,seq,0,SLINK_REASON_IDENTITY);return; }
        tp_ack(m,seq,s->ack_ok,s->ack_ok?0:w->reason);return;
    }
    if (s->active) { /* occupied-slot exception: preserve old witness AND text */
        tp_ack(m,seq,0,SLINK_REASON_CALL_BUSY);return;
    }
    unsigned reason=0,extra=0;
    for (unsigned i=1;i<32;i++) extra|=m->args[i];
    if (!m->session_epoch) reason=SLINK_REASON_CLIENT_TOO_OLD;
    else if (extra || !call_record_valid(input,m->args[0])) reason=SLINK_REASON_BAD_ARGS;
    else if (!e->available(e->context)) reason=SLINK_REASON_CALL_UNAVAILABLE;
    else if (s->has_delivery && (uint32_t)(now-s->last_delivery)<SLINK_CALL_COOLDOWN_FRAMES) reason=SLINK_REASON_CALL_COOLDOWN;
    if (reason) {
        s->ack_ok=0;call_new_witness(w,m,SLINK_CALL_REFUSED,reason,now);
        tp_ack(m,seq,0,reason);return;
    }
    volatile uint8_t *dst=(volatile uint8_t *)owned;
    const volatile uint8_t *src=(const volatile uint8_t *)input;
    for (unsigned i=0;i<sizeof(*owned);i++) dst[i]=src[i];
    s->active=1;s->ui_owned=0;s->ack_ok=1;
    call_new_witness(w,m,SLINK_CALL_ARMED,0,now);
    tp_ack(m,seq,1,0); /* UI start/delivery happens later; never delay this ACK */
}
#endif
