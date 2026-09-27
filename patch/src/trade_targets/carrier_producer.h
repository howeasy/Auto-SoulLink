#ifndef SLINK_CARRIER_PRODUCER_H
#define SLINK_CARRIER_PRODUCER_H
#include "trade_producer.h"
#define SLINK_CARRIER_TEXT_SIZE 256u
#define SLINK_CARRIER_CHOICES_SIZE 112u
typedef struct {
    uint32_t epoch;
    uint16_t seq,opcode;
    uint8_t active,with_text;
    uint8_t text[SLINK_CARRIER_TEXT_SIZE],choices[SLINK_CARRIER_CHOICES_SIZE];
} SlinkCarrierProducer;
typedef struct {
    void *context;
    int (*safe)(void *);
    int (*start)(void *,const SlinkCarrierProducer *);
    int (*poll)(void *,uint8_t *); /* 0 owned/running, 1 returned, -1 failed */
    int (*arm)(void *,uint8_t,uint8_t);
} SlinkCarrierEngine;
static inline int slink_carrier_eos(const volatile uint8_t *p,unsigned size)
{
    for (unsigned i=0;i<size;i++) if (p[i]==0xffu) return 1;
    return 0;
}
static inline int slink_carrier_choices(const volatile uint8_t *p)
{
    unsigned n=p[0],i=1;
    if (!n || n>8) return 0;
    while (n--) {
        while (i<SLINK_CARRIER_CHOICES_SIZE && p[i]!=0xffu) i++;
        if (i==SLINK_CARRIER_CHOICES_SIZE) return 0;
        i++;
    }
    return 1;
}
static inline int slink_carrier_interaction(int safe,int new_a,int idle,int active,
    int px,int py,unsigned facing,int tx,int ty)
{
    if (!safe || !new_a || !idle || !active) return 0;
    if (facing==1) py++; else if (facing==2) py--;
    else if (facing==3) px--; else if (facing==4) px++; else return 0;
    return px==tx && py==ty;
}
static inline void slink_carrier_service(SlinkCarrierProducer *s,volatile SlinkMailboxV2 *m,
    const volatile uint8_t *text,const volatile uint8_t *choices,const SlinkCarrierEngine *e)
{
    if (s->active) {
        uint8_t result=0;
        int done=e->poll(e->context,&result);
        if (done) {
            s->active=0;
            if (m->session_epoch==s->epoch && m->seq==s->seq && !m->opcode) {
                m->result[0]=result;
                tp_ack(m,s->seq,done>0,done>0?0:2);
            }
        }
    }
    uint16_t op=m->opcode,seq=m->seq;
    if (!op) return;
    if (s->active) { tp_ack(m,seq,0,2);return; }
    if (op!=SLINK_OP_ARM_PEER_INTERACT && op!=SLINK_OP_SHOW_MENU
        && op!=SLINK_OP_CHOOSE_PARTY_MON && op!=SLINK_OP_SHOW_CHOICES) return;
    if (!m->session_epoch) { tp_ack(m,seq,0,SLINK_REASON_CLIENT_TOO_OLD);return; }
    if (op==SLINK_OP_ARM_PEER_INTERACT) {
        int ok=m->args[0]<16 && e->arm(e->context,m->args[0],m->args[1]);
        tp_ack(m,seq,ok,ok?0:2);return;
    }
    int needs_text=op==SLINK_OP_SHOW_MENU || (op==SLINK_OP_SHOW_CHOICES && m->args[0]);
    if (!e->safe(e->context) || (needs_text && !slink_carrier_eos(text,SLINK_CARRIER_TEXT_SIZE))
        || (op==SLINK_OP_SHOW_CHOICES && !slink_carrier_choices(choices))) {
        tp_ack(m,seq,0,2);return;
    }
    s->epoch=m->session_epoch;s->seq=seq;s->opcode=op;s->with_text=!!m->args[0];
    for (unsigned i=0;i<SLINK_CARRIER_TEXT_SIZE;i++) s->text[i]=text[i];
    for (unsigned i=0;i<SLINK_CARRIER_CHOICES_SIZE;i++) s->choices[i]=choices[i];
    if (!e->start(e->context,s)) { tp_ack(m,seq,0,2);return; }
    s->active=1;m->status=SLINK_ST_BUSY;m->opcode=0;
}
#endif
