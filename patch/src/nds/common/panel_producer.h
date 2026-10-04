/* Owned native panel lifecycle; no rendering/address assumptions.
 * NDS lift of trade_targets/panel_producer.h. Same ack/drawn/closed ownership
 * rules. Text validation uses the binding's terminator (width, value, charset)
 * instead of a hard-coded 0xFF: Gen 3 rows end in 0xFF, Gen 4/5 rows in 0xFFFF
 * UTF-16 units within the same 32-byte row. SlinkInfoV2.lines counts ROWS, not
 * characters. */
#ifndef SLINK_NDS_PANEL_PRODUCER_H
#define SLINK_NDS_PANEL_PRODUCER_H
#include "trade_producer.h"
typedef struct {
    void *context;
    const SlinkTextSpec *text;  /* terminator width/value + charset; from the record binding */
    int (*safe)(void *);
    int (*start)(void *,const SlinkInfoV2 *);
    int (*poll)(void *,uint8_t *); /* 0 opening, 1 drawn, 2 closed */
} SlinkPanelEngine;
typedef struct {
    SlinkInfoV2 snapshot;
    uint8_t active;
} SlinkPanelProducer;

static inline int slink_panel_valid(const volatile SlinkInfoV2 *i,uint32_t epoch,
                                    const SlinkTextSpec *text)
{
    unsigned row;
    if (!epoch || i->session_epoch!=epoch || !i->request_seq || !i->enable
        || !i->lines || i->lines>SLINK_INFO_MAX_LINES) return 0;
    for (row=0;row<SLINK_INFO_ROW_COUNT;row++) {
        if (row>=i->lines && row!=SLINK_INFO_PAGE_SLOT) continue;
        if (slink_text_terminator_index(i->text[row],SLINK_INFO_LINE_WIDTH,text)<0) return 0;
    }
    return 1;
}
static inline void slink_panel_service(SlinkPanelProducer *s,volatile SlinkMailboxV2 *m,
    volatile SlinkInfoV2 *i,const SlinkPanelEngine *e,int menu_open)
{
    /* C89 wants every declaration ahead of the statements of its block. Each value is
     * still read at the line it was read before, so no statement observes a mailbox or
     * panel state different from the C99 spelling. */
    int posted;
    uint16_t seq;
    const volatile uint8_t *source;
    uint8_t *copy;
    unsigned n;
    if (s->active) {
        uint8_t result=0;
        int phase=e->poll(e->context,&result);
        if (m->session_epoch==s->snapshot.session_epoch
            && i->session_epoch==s->snapshot.session_epoch && i->request_seq==s->snapshot.request_seq) {
            if (phase==1) { i->drawn_seq=s->snapshot.request_seq;i->state=2; }
            if (phase==2) { i->result=result;i->closed_seq=s->snapshot.request_seq;i->state=0; }
        }
        if (phase==2) s->active=0;
    }
    posted=m->opcode==SLINK_OP_SHOW_INFO;
    if (!posted && (!menu_open || m->opcode)) return;
    seq=m->seq;
    if (s->active || !e->safe(e->context) || !slink_panel_valid(i,m->session_epoch,e->text)
        || (posted && i->request_seq!=seq)) {
        if (posted) tp_ack(m,seq,0,2);
        return;
    }
    source=(const volatile uint8_t *)i;
    copy=(uint8_t *)&s->snapshot;
    for (n=0;n<sizeof(s->snapshot);n++) copy[n]=source[n];
    if (!e->start(e->context,&s->snapshot)) {
        if (posted) tp_ack(m,seq,0,2);
        return;
    }
    s->active=1;i->state=1;
    if (posted) tp_ack(m,seq,1,0);
}
#endif
