#ifndef SLINK_NATIVE_RIVAL_H
#define SLINK_NATIVE_RIVAL_H
#include "rival_producer.h"
static void nr_window(void *unused,SlinkRivalWindow *w)
{
    (void)unused;
    w->callback=NT_READ32(SLINK_TARGET_GMAIN+4);
    w->main_func=NT_READ32(SLINK_TARGET_RIVAL_MAIN_FUNC);
    uint32_t flags=NT_READ32(SLINK_TARGET_RIVAL_FLAGS);
    w->flags=((flags&SLINK_TARGET_RIVAL_DOUBLE_MASK)?1u:0u)
        |((flags&SLINK_TARGET_RIVAL_LINK_MASK)?2u:0u)|((flags&SLINK_TARGET_RIVAL_TRAINER_MASK)?8u:0u);
    w->trainer=NT_READ16(SLINK_TARGET_RIVAL_TRAINER);
    w->stage=NT_READ8(SLINK_TARGET_RIVAL_COMM);
    w->in_battle=!!(NT_READ8(SLINK_TARGET_GMAIN+SLINK_TARGET_MAIN_BATTLE_OFFSET)&2u);
}
static int nr_validate(void *unused,uint8_t *record)
{
    (void)unused;
    NtMonData get=(NtMonData)(SLINK_TARGET_GET_MON_DATA|1u);
    unsigned species=get(record,SLINK_TARGET_MON_DATA_SPECIES,0);
    if (!species || species>SLINK_TARGET_MAX_SPECIES || get(record,SLINK_TARGET_MON_DATA_BAD_EGG,0)) return 0;
    return get(record,SLINK_TARGET_RIVAL_MON_HP,0)
        && get(record,SLINK_TARGET_RIVAL_SPECIES_OR_EGG,0)!=SLINK_TARGET_RIVAL_EGG_SPECIES
        && !get(record,SLINK_TARGET_MON_DATA_EGG,0)?2:1;
}
static void nr_replace(void *unused,const uint8_t *records,unsigned count)
{
    (void)unused;
    for (unsigned i=0;i<600;i++) NT_READ8(SLINK_TARGET_ENEMY_PARTY+i)=i<count*100?records[i]:0;
    NT_READ8(SLINK_TARGET_ENEMY_COUNT)=(uint8_t)count;
}
static const SlinkRivalEngine nr_engine={0,SLINK_TARGET_RIVAL_START|1u,SLINK_TARGET_RIVAL_DUMMY|1u,
                                       nr_window,nr_validate,nr_replace};
/* Release the 600-byte validation snapshot before the original game callbacks. */
__attribute__((noinline)) static void slink_native_rival_service(void)
{
    slink_rival_service(NT_MB,(const volatile uint8_t *)(NT_BASE+SLINK_BLOB_OFFSET),&nr_engine,NC_CONTROL->session_epoch);
}
#endif
