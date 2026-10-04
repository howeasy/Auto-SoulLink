/* Native sound dispatch boundary; ACK is not an audible-output claim.
 * NDS lift of trade_targets/sound_producer.h: logic unchanged (song ids are u16
 * and there is no record or text, so no binding is needed). */
#ifndef SLINK_NDS_SOUND_PRODUCER_H
#define SLINK_NDS_SOUND_PRODUCER_H
#include "trade_producer.h"
typedef struct {
    void *context;
    uint16_t song_count;
    int (*effect)(void *,uint16_t);
    int (*fanfare)(void *,uint16_t);
} SlinkSoundEngine;
static inline void slink_sound_service(volatile SlinkMailboxV2 *m,const SlinkSoundEngine *e,int owned,
                                       uint32_t configured_epoch)
{
    uint16_t op=m->opcode,seq=m->seq;
    unsigned song;
    int ok;
    if (op!=SLINK_OP_PLAY_SE && op!=SLINK_OP_PLAY_FANFARE) return;
    if (!m->session_epoch) { tp_ack(m,seq,0,SLINK_REASON_CLIENT_TOO_OLD);return; }
    if (m->session_epoch!=configured_epoch) { tp_ack(m,seq,0,SLINK_REASON_IDENTITY);return; }
    song=(unsigned)m->args[0] | ((unsigned)m->args[1]<<8);
    if (owned || song>=e->song_count) { tp_ack(m,seq,0,2);return; }
    ok=op==SLINK_OP_PLAY_SE?e->effect(e->context,(uint16_t)song):e->fanfare(e->context,(uint16_t)song);
    tp_ack(m,seq,ok,ok?0:2);
}
#endif
