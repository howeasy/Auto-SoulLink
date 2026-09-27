/* Native engine binding for the target header selected by the shared builder.
 * Private probe composition until every required target feature qualifies.
 * Target C/assembly entry bytes are pinned before the builder changes the ROM.
 */
#ifndef SLINK_NATIVE_TRADE_H
#define SLINK_NATIVE_TRADE_H
#include "trade_producer.h"
#define NT_BASE SLINK_TARGET_ARENA_CANDIDATE
#define NT_MB ((volatile SlinkMailboxV2 *)(NT_BASE + SLINK_MAILBOX_OFFSET))
#define NT_WITNESS ((volatile SlinkTradeWitnessV2 *)(NT_BASE + SLINK_WITNESS_OFFSET))
#define NT_STATE ((SlinkTradeProducer *)(NT_BASE + 0x820u))
#define NT_UI ((volatile uint32_t *)(NT_BASE + 0x8A0u))
#define NT_SCRIPT ((volatile uint8_t *)(NT_BASE + 0x900u))
#define NT_READ8(a) (*(volatile uint8_t *)(a))
#define NT_READ16(a) (*(volatile uint16_t *)(a))
#define NT_READ32(a) (*(volatile uint32_t *)(a))
typedef void (*NtVoid)(void);
typedef uint8_t (*NtBool)(void);
typedef uint32_t (*NtMonData)(void *, int, void *);
typedef void (*NtSetup)(const uint8_t *);
_Static_assert(0x820u + sizeof(SlinkTradeProducer) <= 0x8A0u, "trade state/UI overlap");
_Static_assert(0x910u <= SLINK_CALL_WITNESS_OFFSET, "script/phone overlap");

static int nt_safe(void *unused)
{
    (void)unused;
    return NT_READ32(SLINK_TARGET_GMAIN+4u)==SLINK_TARGET_FIELD_CALLBACK
        && !NT_READ8(SLINK_TARGET_FIELD_LOCK)
        && NT_READ8(SLINK_TARGET_SCRIPT_STATUS)==SLINK_TARGET_SCRIPT_IDLE
        && !NT_READ8(SLINK_TARGET_AVATAR_TRANSITION)
        && !(NT_READ8(SLINK_TARGET_PALETTE_ACTIVE)&0x80u)
        && !NT_READ8(SLINK_TARGET_REMOTE_LINK_PLAYERS) && !NT_READ8(SLINK_TARGET_LINK_TRANSFERRING)
        && !(NT_READ8(SLINK_TARGET_GMAIN+SLINK_TARGET_MAIN_BATTLE_OFFSET)&2u);
}
static int nt_locate(void *unused,uint32_t pid,uint32_t ot)
{
    (void)unused;
    unsigned count=NT_READ8(SLINK_TARGET_PLAYER_COUNT);
    if (!count || count>SLINK_TARGET_PARTY_SIZE) return -1;
    int found=-1;
    for (unsigned i=0;i<count;i++) {
        uint32_t mon=SLINK_TARGET_PLAYER_PARTY+SLINK_TARGET_MON_SIZE*i;
        if (NT_READ32(mon)==pid && NT_READ32(mon+4u)==ot) {
            if (found!=-1) return -1;
            found=(int)i;
        }
    }
    return found;
}
static int nt_incoming(void *unused,const uint8_t *record)
{
    (void)unused;
    NtMonData get=(NtMonData)(SLINK_TARGET_GET_MON_DATA|1u);
    /* GetMonData may mark a bad-checksum copy as Bad Egg; never validate on the
     * player's live record. The controller owns this staging copy. */
    unsigned species=get((void *)record,SLINK_TARGET_MON_DATA_SPECIES,0), item=get((void *)record,SLINK_TARGET_MON_DATA_ITEM,0);
    if (!species || species>SLINK_TARGET_MAX_SPECIES || get((void *)record,SLINK_TARGET_MON_DATA_BAD_EGG,0) || get((void *)record,SLINK_TARGET_MON_DATA_EGG,0)
        || record[SLINK_TARGET_MON_MAIL_OFFSET]!=0xFF || ((uint8_t(*)(uint16_t))(SLINK_TARGET_ITEM_IS_MAIL|1u))((uint16_t)item)) return 0;
    /* No incoming identity may already be in the recipient party, even if
     * duplicated (nt_locate deliberately returns -1 for duplicates). */
    unsigned count=NT_READ8(SLINK_TARGET_PLAYER_COUNT);
    if (!count || count>SLINK_TARGET_PARTY_SIZE) return 0;
    for (unsigned i=0;i<count;i++) {
        uint32_t p=SLINK_TARGET_PLAYER_PARTY+SLINK_TARGET_MON_SIZE*i;
        if (NT_READ32(p)==tp_word(record) && NT_READ32(p+4u)==tp_word(record+4)) return 0;
    }
    return 1;
}
static void nt_script_call(uint32_t address)
{
    NT_SCRIPT[0]=0x23;
    for (unsigned i=0;i<4;i++) NT_SCRIPT[i+1]=(uint8_t)((address|1u)>>(8*i));
    NT_SCRIPT[5]=0x27;NT_SCRIPT[6]=0x02;
    ((NtSetup)(SLINK_TARGET_SCRIPT_SETUP|1u))((const uint8_t *)NT_SCRIPT);
}
static int nt_pre_start(void *unused)
{
    if (!nt_safe(unused)) return 0;
    NT_READ16(SLINK_TARGET_SPECIAL_RESULT)=0xFFFF;
    NT_UI[0]=1;
    nt_script_call(SLINK_TARGET_ASK_SAVE);
    return 1;
}
static int nt_pre_poll(void *unused)
{
    uint32_t callback=NT_READ32(SLINK_TARGET_SAVE_DIALOG_PTR);
    if (NT_UI[0] && nt_safe(unused) && NT_READ16(SLINK_TARGET_SPECIAL_RESULT)!=0xFFFF) {
        NT_UI[0]=0;
        return NT_READ16(SLINK_TARGET_SPECIAL_RESULT)==1 ? 1 : -1;
    }
    if (callback==SLINK_TARGET_SAVE_PRINTING_CB || callback==SLINK_TARGET_SAVE_WRITING_CB) return 2;
    return 0;
}
static int nt_scene_start(void *unused,unsigned slot,const uint8_t *record)
{
    if (!nt_safe(unused)) return 0;
    for (unsigned i=0;i<SLINK_TARGET_MON_SIZE;i++) NT_READ8(SLINK_TARGET_ENEMY_PARTY+i)=record[i];
    NT_READ8(SLINK_TARGET_ENEMY_COUNT)=1;
    NT_READ16(SLINK_TARGET_TRADE_SLOT_VAR)=(uint16_t)slot;
    NT_READ16(SLINK_TARGET_TRADE_TABLE_VAR)=0;
    NT_UI[1]=1;
    nt_script_call(SLINK_TARGET_TRADE_SCENE);
    return 1;
}
static int nt_scene_poll(void *unused)
{
    if (NT_UI[1]==1 && NT_READ32(SLINK_TARGET_GMAIN+4u)!=SLINK_TARGET_FIELD_CALLBACK) NT_UI[1]=2;
    if (NT_UI[1]==2) {
        slink_copy_name_bounded((volatile uint8_t *)SLINK_TARGET_STR_VAR1,
            SLINK_TARGET_STR_VAR1_SIZE,NT_STATE->incoming+0x14,7);
        slink_copy_name_bounded((volatile uint8_t *)SLINK_TARGET_STR_VAR3,
            SLINK_TARGET_STR_VAR3_SIZE,NT_STATE->incoming+8,10);
        if (nt_safe(unused)) { NT_UI[1]=0;return 1; }
    }
    return 0;
}
static int nt_post_save(void *unused)
{
    if (!nt_safe(unused)) return 0;
#if defined(SLINK_NATIVE_TRADE_PROBE)
    if (NT_UI[2]==1) return 0; /* named private falsifier: no post-save occurred */
#endif
    ((NtVoid)(SLINK_TARGET_SAVE_MAP|1u))();
#ifdef SLINK_TARGET_SAVE_QUEST
    ((NtVoid)(SLINK_TARGET_SAVE_QUEST|1u))();
#endif
    return ((uint8_t(*)(uint8_t))(SLINK_TARGET_SAVE_NORMAL|1u))(0)==SLINK_SAVE_OK;
}
static int nt_received(void *unused,unsigned slot,uint32_t *pid,uint32_t *ot)
{
    (void)unused;
    if (slot>=NT_READ8(SLINK_TARGET_PLAYER_COUNT)) return 0;
    *pid=NT_READ32(SLINK_TARGET_PLAYER_PARTY+SLINK_TARGET_MON_SIZE*slot);
    *ot=NT_READ32(SLINK_TARGET_PLAYER_PARTY+SLINK_TARGET_MON_SIZE*slot+4u);
    return 1;
}
static uint32_t nt_frame(void *unused)
{
    (void)unused;
    return NT_READ32(SLINK_TARGET_GMAIN+SLINK_TARGET_MAIN_FRAME_OFFSET); /* Main.vblankCounter2, main.h:26 */
}
static const SlinkTradeEngine nt_engine={0,nt_safe,nt_locate,nt_incoming,nt_pre_start,
    nt_pre_poll,nt_scene_start,nt_scene_poll,nt_post_save,nt_received,nt_frame};

__attribute__((used,noinline)) int slink_native_before_swap(unsigned slot)
{
    return slink_trade_commit_entered(NT_STATE,NT_WITNESS,slot,&nt_engine);
}
__attribute__((used,noinline)) int slink_native_suppress_evolution(void)
{
    return NT_STATE->phase==TP_SCENE && NT_STATE->cancel_scene;
}

/* Eight overwritten bytes contain only register saves/moves, no PC-relative
 * operands. Entry veneers may clobber r3 (not an argument to either function).
 * Restore arguments/LR, replay those exact bytes, branch into original +8.
 * C function boundaries do not carry condition flags as input. */
__attribute__((naked,used)) void slink_native_trade_gate(void)
{
    __asm__ volatile(
        "push {r0-r4,lr}\n bl slink_native_before_swap\n cmp r0,#0\n beq 1f\n"
        "ldr r4,[sp,#20]\n mov lr,r4\n pop {r0-r4}\n add sp,#4\n"
        SLINK_TARGET_TRADE_GATE_ASM
        "1: ldr r4,[sp,#20]\n mov lr,r4\n pop {r0-r4}\n add sp,#4\n bx lr\n .align 2\n .ltorg\n");
}
__attribute__((naked,used)) void slink_native_evolution_gate(void)
{
    __asm__ volatile(
        "push {r0-r4,lr}\n bl slink_native_suppress_evolution\n cmp r0,#0\n bne 1f\n"
        "ldr r4,[sp,#20]\n mov lr,r4\n pop {r0-r4}\n add sp,#4\n"
        SLINK_TARGET_EVO_GATE_ASM
        "1: ldr r4,[sp,#20]\n mov lr,r4\n pop {r0-r4}\n add sp,#4\n movs r0,#0\n bx lr\n .align 2\n .ltorg\n");
}

__attribute__((section(".text.entry"),used)) void slink_native_heap(void *heap,uint32_t size)
{
    if ((uint32_t)heap==SLINK_TARGET_HEAP_BASE && size==SLINK_TARGET_HEAP_SIZE) size-=SLINK_TARGET_ARENA_SIZE;
    NT_READ32(SLINK_TARGET_HEAP_START_PTR)=(uint32_t)heap;
    NT_READ32(SLINK_TARGET_HEAP_SIZE_PTR)=size;
    ((void(*)(void *,uint32_t))(SLINK_TARGET_PUT_FIRST_HEADER|1u))(heap,size);
    /* Do not erase transaction state when save/menu code reinitializes gHeap. */
}
#if defined(SLINK_NATIVE_COMPANION)
static int nc_owned(void);
#ifdef SLINK_TARGET_CALL_FEATURE
static int ncall_owned(void);
#else
#define ncall_owned() 0
#endif
#include "native_panel.h"
#include "native_carrier.h"
#include "native_sound.h"
#include "native_rival.h"
#ifdef SLINK_TARGET_CALL_FEATURE
#include "native_call.h"
#endif
#endif
#ifdef SLINK_TARGET_FRAME_REPLAY_REQUIRED
__attribute__((used,noinline)) void slink_native_services(void)
#else
__attribute__((used)) void slink_native_frame(void)
#endif
{
#ifdef SLINK_TARGET_SAVE_FAILED_SCREEN
    if (((NtBool)(SLINK_TARGET_SAVE_FAILED_SCREEN|1u))() || ((NtBool)(SLINK_TARGET_HELP_CALLBACK|1u))()) return;
#endif
    if (NT_READ32(SLINK_TARGET_HEAP_SIZE_PTR)==SLINK_TARGET_HEAP_SIZE-SLINK_TARGET_ARENA_SIZE) {
#if defined(SLINK_NATIVE_TRADE_PROBE)
        NT_MB->signature=0x32505254u; /* TRP2 private fault-injection probe */
        NT_MB->abi_version=SLINK_ABI_VERSION;NT_MB->capabilities=0;
#elif SLINK_TARGET_READY || defined(SLINK_NATIVE_COMPANION)
        slink_trade_advertise(NT_MB);
#if defined(SLINK_NATIVE_COMPANION)
        NT_MB->capabilities |= SLINK_CAP_INFO_PANEL | SLINK_CAP_NATIVE_SOUND | SLINK_CAP_RIVAL_SWAP;
#endif
#else
        NT_MB->signature=SLINK_SIGNATURE;
        NT_MB->abi_version=SLINK_ABI_VERSION;NT_MB->capabilities=0;
#endif
#if defined(SLINK_NATIVE_COMPANION)
        slink_native_carrier_service();
        slink_native_panel_service();
        slink_native_sound_service();
        slink_native_rival_service();
#ifdef SLINK_TARGET_CALL_FEATURE
        NT_MB->capabilities |= SLINK_CAP_MATCH_CALL;
        slink_native_call_service();
#endif
#endif
        slink_trade_service(NT_STATE,NT_MB,NT_WITNESS,
            (const volatile uint8_t *)(NT_BASE+SLINK_BLOB_OFFSET),&nt_engine);
    }
#ifndef SLINK_TARGET_FRAME_REPLAY_REQUIRED
    volatile uint32_t *callbacks=(volatile uint32_t *)SLINK_TARGET_GMAIN;
    if (callbacks[0]) ((NtVoid)callbacks[0])();
    if (callbacks[1]) ((NtVoid)callbacks[1])();
#endif
}
#ifdef SLINK_TARGET_FRAME_REPLAY_REQUIRED
/* Preserve the original callback tail, including flags from relocated CMP.
 * Eight stack words keep the C service call aligned; the original prologue is
 * replayed only after returning from all producer stack allocations. */
__attribute__((naked,used)) void slink_native_frame(void)
{
    __asm__ volatile("push {r0-r6,lr}\n bl slink_native_services\n"
        "ldr r3,[sp,#28]\n mov lr,r3\n pop {r0-r6}\n add sp,#4\n"
        SLINK_TARGET_FRAME_REPLAY_ASM ".align 2\n .ltorg\n");
}
#endif
#endif
