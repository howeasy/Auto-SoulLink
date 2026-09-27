#ifndef SLINK_RIVAL_PRODUCER_H
#define SLINK_RIVAL_PRODUCER_H
#include "trade_producer.h"
typedef struct {
    uint32_t callback,main_func,flags; /* normalized flags: double1, link2, trainer8 */
    uint16_t trainer;
    uint8_t stage,in_battle;
} SlinkRivalWindow;
typedef struct {
    void *context;
    uint32_t start_callback,dummy_callback;
    void (*window)(void *,SlinkRivalWindow *);
    int (*validate)(void *,uint8_t *); /* aligned copy: 0 invalid, 1 valid, 2 selectable */
    void (*replace)(void *,const uint8_t *,unsigned);
} SlinkRivalEngine;
static inline int slink_rival_open(const SlinkRivalWindow *w,uint16_t trainer,const SlinkRivalEngine *e)
{
    return w->callback==e->start_callback && w->main_func==e->dummy_callback
        && w->stage<15 && w->in_battle && (w->flags&8) && !(w->flags&2) && w->trainer==trainer;
}
static inline void slink_rival_service(volatile SlinkMailboxV2 *m,const volatile uint8_t *blob,
    const SlinkRivalEngine *e,uint32_t configured_epoch)
{
    if (m->opcode!=SLINK_OP_RIVAL_SWAP) return;
    uint16_t seq=m->seq,trainer=(uint16_t)(m->args[1]|((uint16_t)m->args[2]<<8));
    if (!m->session_epoch) { tp_ack(m,seq,0,SLINK_REASON_CLIENT_TOO_OLD);return; }
    if (m->session_epoch!=configured_epoch) { tp_ack(m,seq,0,SLINK_REASON_IDENTITY);return; }
    unsigned count=m->args[0];
    if (!count || count>6) { tp_ack(m,seq,0,SLINK_REASON_BAD_ARGS);return; }
    SlinkRivalWindow window;
    e->window(e->context,&window);
    if (!slink_rival_open(&window,trainer,e)) { tp_ack(m,seq,0,SLINK_REASON_WINDOW_CLOSED);return; }
    _Alignas(4) uint8_t incoming[600];
    for (unsigned i=0;i<count*100;i++) incoming[i]=blob[i];
    unsigned selectable=0;
    for (unsigned i=0;i<count;i++) {
        int valid=e->validate(e->context,incoming+i*100);
        if (!valid) { tp_ack(m,seq,0,SLINK_REASON_BAD_ARGS);return; }
        if (valid==2) selectable++;
    }
    e->window(e->context,&window); /* authority immediately before any enemy write */
    if (!slink_rival_open(&window,trainer,e)) { tp_ack(m,seq,0,SLINK_REASON_WINDOW_CLOSED);return; }
    if (selectable<((window.flags&1)?2u:1u)) { tp_ack(m,seq,0,SLINK_REASON_SLOTS_UNVIABLE);return; }
    e->replace(e->context,incoming,count);
    tp_ack(m,seq,1,0);
}
#endif
