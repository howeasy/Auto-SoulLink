#ifndef SLINK_NATIVE_SOUND_H
#define SLINK_NATIVE_SOUND_H
#include "sound_producer.h"
static int ns_effect(void *unused,uint16_t song)
{
    (void)unused;
    ((void(*)(uint16_t))(SLINK_TARGET_SOUND_SE|1u))(song);
    return 1; /* dispatched; PlaySE may suppress during native quest-log playback */
}
static int ns_fanfare(void *unused,uint16_t song)
{
    (void)unused;
    if (!np_task_available()) return 0;
    ((void(*)(uint16_t))(SLINK_TARGET_SOUND_FANFARE|1u))(song);
    return 1;
}
static const SlinkSoundEngine ns_engine={0,SLINK_TARGET_SOUND_COUNT,ns_effect,ns_fanfare};
static void slink_native_sound_service(void)
{
    int owned=nc_owned() || NP_STATE->active || NT_STATE->phase==TP_PRE_SAVE || NT_STATE->phase==TP_SCENE;
    slink_sound_service(NT_MB,&ns_engine,owned,NC_CONTROL->session_epoch);
}
#endif
