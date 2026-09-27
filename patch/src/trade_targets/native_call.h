/* Emerald incoming Match Call, using the engine's field-message owner. */
#ifndef SLINK_NATIVE_CALL_H
#define SLINK_NATIVE_CALL_H
#include "call_producer.h"
#include "call_text.h"
#define NCall_STATE ((SlinkCallProducer *)(NT_BASE+0xE80u))
#define NCall_RUNTIME ((volatile uint32_t *)(NT_BASE+0xE90u))
#define NCall_TEXT ((uint8_t *)(NT_BASE+0xF00u))
#define NCall_RECORD ((volatile SlinkCallRecordV2 *)(NT_BASE+SLINK_CALL_RECORD_OFFSET))
#define NCall_WITNESS ((volatile SlinkCallWitnessV2 *)(NT_BASE+SLINK_CALL_WITNESS_OFFSET))
_Static_assert(0xE80u+sizeof(SlinkCallProducer)<=0xE90u,"call state/runtime overlap");
_Static_assert(0xF00u+256u<=SLINK_ARENA_SIZE,"call text/arena overlap");
static int ncall_owned(void) { return NCall_STATE->ui_owned; }
static unsigned ncall_free_tasks(void)
{
    unsigned free=0;
    for (unsigned i=0;i<16;i++) if (!NT_READ8(gTasks+i*0x28u+4u)) free++;
    return free;
}
static int ncall_available(void *unused)
{
    (void)unused;
    u8 (*flag)(u16)=(u8(*)(u16))(SLINK_TARGET_PANEL_FLAG_GET|1u);
    return flag(SLINK_TARGET_PANEL_NAV_FLAG) && flag(SLINK_TARGET_CALL_UNLOCK_FLAG);
}
static int ncall_safe(void *unused)
{
    return nt_safe(unused) && !nc_owned() && !NP_STATE->active
        && (NT_STATE->phase==TP_IDLE || NT_STATE->phase==TP_DONE)
        && !((u8(*)(void))(SLINK_TARGET_CALL_MODE|1u))()
        && !((u32(*)(void))(SLINK_TARGET_CALL_ACTIVE|1u))()
        && ncall_free_tasks()>=3;
}
static void ncall_show(void)
{
    /* Recheck task capacity inside the script: watcher, call task, icon task.
     * On failure waitmessage sees HIDDEN and the script still releases locks. */
    NCall_RUNTIME[0]=3;
    if (ncall_free_tasks()>=3 && ((u8(*)(const u8 *))(SLINK_TARGET_CALL_SHOW|1u))(NCall_TEXT))
        NCall_RUNTIME[0]=2;
}
static int ncall_start(void *unused,const volatile SlinkCallRecordV2 *r)
{
    if (!ncall_safe(unused) || !ncall_available(unused)) return 0;
    if (!slink_call_text(NCall_TEXT,256,r,(const u8 *)SLINK_TARGET_CALL_SPECIES_NAMES,SLINK_TARGET_MAX_SPECIES)) return 0;
    unsigned i=0;
    NT_SCRIPT[i++]=0x69; /* lockall */
    NT_SCRIPT[i++]=0x23;nc_script_word(&i,(uint32_t)ncall_show|1u);
    NT_SCRIPT[i++]=0x66; /* waitmessage: field-message watcher owns its completion */
    NT_SCRIPT[i++]=0x6b;NT_SCRIPT[i++]=0x02;
    NCall_RUNTIME[0]=1;
    ((NtSetup)(SLINK_TARGET_SCRIPT_SETUP|1u))((const u8 *)NT_SCRIPT);
    return 1;
}
static int ncall_poll(void *unused)
{
    if (NCall_RUNTIME[0]==1) return 0;
    for (unsigned i=0;i<16;i++) {
        uint32_t p=gTasks+i*0x28u;
        if (NT_READ8(p+4) && NT_READ32(p)==(SLINK_TARGET_CALL_TASK|1u)) {
            /* State 5 means the intro ended and PrintIntro started gStringVar4.
             * Creation or slide-in alone is not delivery of the actual call. */
            unsigned state=NT_READ16(p+8);
            return state==5?1:0;
        }
    }
    if (nt_safe(unused) && !((u8(*)(void))(SLINK_TARGET_CALL_MODE|1u))()) return 2;
    return 0;
}
static const SlinkCallEngine ncall_engine={0,ncall_available,ncall_safe,ncall_start,ncall_poll,nt_frame};
static void slink_native_call_service(void)
{
    slink_call_service(NCall_STATE,NT_MB,NCall_WITNESS,NCall_RECORD,
        (const volatile SlinkCallRecordV2 *)(NT_BASE+SLINK_TEXT_OFFSET),&ncall_engine);
}
#endif
