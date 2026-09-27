#ifndef SLINK_SOUND_PRODUCER_H
#define SLINK_SOUND_PRODUCER_H
#include "trade_producer.h"
typedef struct {
    void *context;
    uint16_t song_count;
    int (*effect)(void *,uint16_t);
    int (*fanfare)(void *,uint16_t);
} SlinkSoundEngine;
static inline void slink_sound_service(volatile SlinkMailboxV2 *m,const SlinkSoundEngine *e,int owned)
{
    uint16_t op=m->opcode,seq=m->seq;
    if (op!=SLINK_OP_PLAY_SE && op!=SLINK_OP_PLAY_FANFARE) return;
    if (!m->session_epoch) { tp_ack(m,seq,0,SLINK_REASON_CLIENT_TOO_OLD);return; }
    unsigned song=(unsigned)m->args[0] | ((unsigned)m->args[1]<<8);
    if (owned || song>=e->song_count) { tp_ack(m,seq,0,2);return; }
    int ok=op==SLINK_OP_PLAY_SE?e->effect(e->context,(uint16_t)song):e->fanfare(e->context,(uint16_t)song);
    tp_ack(m,seq,ok,ok?0:2);
}
#endif
