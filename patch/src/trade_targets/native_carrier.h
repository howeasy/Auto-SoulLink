/* RR carrier UX/opcodes, vanilla FR engine bindings. Candidate-only. */
#ifndef SLINK_NATIVE_CARRIER_H
#define SLINK_NATIVE_CARRIER_H
#include "carrier_producer.h"
#define NC_STATE ((SlinkCarrierProducer *)(NT_BASE+0xB40u))
#define NC_RUNTIME ((volatile uint32_t *)(NT_BASE+0x960u))
#define NC_CONTROL ((volatile SlinkControlV2 *)(NT_BASE+SLINK_CONTROL_OFFSET))
typedef struct {
    uint32_t epoch;
    uint8_t initialized,oe,map_g,map_n,armed,talk_oe,talk_local,talk_g,talk_n;
} SlinkCarrierNpc;
#define NC_NPC ((SlinkCarrierNpc *)(NT_BASE+0xCE0u))
_Static_assert(0xA00u+sizeof(SlinkPanelProducer)<=0xB40u,"panel/carrier overlap");
_Static_assert(0xB40u+sizeof(SlinkCarrierProducer)<=0xCE0u,"carrier/NPC overlap");
_Static_assert(0xCE0u+sizeof(SlinkCarrierNpc)<=SLINK_CALL_WITNESS_OFFSET,"NPC/call overlap");
static int nc_owned(void) { return NC_STATE->active; }
static uint32_t nc_object(unsigned slot) { return SLINK_TARGET_CARRIER_OBJECTS+slot*SLINK_TARGET_CARRIER_STRIDE; }
static int nc_bound(unsigned slot,unsigned local,unsigned g,unsigned n)
{
    if (slot>=16) return 0;
    uint32_t p=nc_object(slot);
    return (NT_READ8(p)&1) && NT_READ8(p+8)==local && NT_READ8(p+9)==n && NT_READ8(p+10)==g;
}
static void nc_remove_npc(void)
{
    unsigned oe=NC_NPC->oe;
    if (nc_bound(oe,SLINK_TARGET_CARRIER_LOCAL_ID,NC_NPC->map_g,NC_NPC->map_n))
        ((void(*)(void *))(SLINK_TARGET_CARRIER_REMOVE|1u))((void *)nc_object(oe));
    if (NC_NPC->talk_oe==oe && NC_NPC->talk_local==SLINK_TARGET_CARRIER_LOCAL_ID) NC_NPC->armed=0;
    NC_NPC->oe=0xff;
}
static int nc_arm(void *unused,uint8_t oe,uint8_t enabled)
{
    (void)unused;
    if (oe>=16 || NC_CONTROL->session_epoch!=NT_MB->session_epoch) return 0;
    uint32_t p=nc_object(oe);
    if (enabled && !(NT_READ8(p)&1)) return 0;
    NC_NPC->talk_oe=oe;NC_NPC->armed=!!enabled;
    NC_NPC->talk_local=NT_READ8(p+8);NC_NPC->talk_n=NT_READ8(p+9);NC_NPC->talk_g=NT_READ8(p+10);
    if (enabled) NC_CONTROL->pi_count=0; /* existing OP13 re-arm convention */
    return 1;
}
static int nc_safe(void *unused)
{
    return nt_safe(unused) && !NP_STATE->active && !ncall_owned() && np_task_available()
        && (NT_STATE->phase==TP_IDLE || NT_STATE->phase==TP_DONE);
}
static void nc_choose_party(void)
{
#ifdef SLINK_TARGET_CARRIER_CHOOSE_NO_ARGS
    ((NtVoid)(SLINK_TARGET_CARRIER_CHOOSE|1u))();
#else
    ((void(*)(uint8_t))(SLINK_TARGET_CARRIER_CHOOSE|1u))(SLINK_TARGET_CARRIER_CHOOSE_TYPE);
#endif
}
static void nc_choices_entry(void)
{
    if (!np_task_available()) { NC_RUNTIME[0]=3;return; }
    const uint8_t *options[8];unsigned count=NC_STATE->choices[0],pos=1;
    unsigned width=0;
    for (unsigned i=0;i<count;i++) {
        options[i]=NC_STATE->choices+pos;
        unsigned pixels=GetStringWidth(FONT_NORMAL,options[i],0);
        if (pixels>width) width=pixels;
        while (pos<SLINK_CARRIER_CHOICES_SIZE && NC_STATE->choices[pos]!=0xffu) pos++;
        pos++;
    }
    static const uint8_t heights[]={1,2,4,6,7,9,11,13,14};
    width=(width+9)/8+1;if (width>27) width=27;
    unsigned height=heights[count];
    while (width*height>352 && width>8) width--;
    uint8_t win=CreateWindowFromRect(1,1,(uint8_t)width,(uint8_t)height);
    if (win==0xffu) { NC_RUNTIME[0]=3;return; }
    SetStandardWindowBorderStyle(win,0);
    for (unsigned i=0;i<count;i++)
        AddTextPrinterParameterized4(win,FONT_NORMAL,8,(uint8_t)(14*i+2),0,0,sColBody,0xff,options[i]);
    CopyWindowToVram(win,2);Menu_InitCursor(win,FONT_NORMAL,0,2,14,(uint8_t)count,0);
    uint8_t task=CreateTask((void *)(TASK_MULTICHOICE_INPUT|1u),80);
    volatile int16_t *d=(volatile int16_t *)(gTasks+(uint32_t)task*0x28u+8u);
    d[4]=0;d[5]=count>3;d[6]=win;d[7]=0;
    ScheduleBgCopyTilemapToVram(0);
}
static void nc_script_word(unsigned *i,uint32_t word)
{
    for (unsigned n=0;n<4;n++) NT_SCRIPT[(*i)++]=(uint8_t)(word>>(8*n));
}
static int nc_start(void *unused,const SlinkCarrierProducer *s)
{
    if (!nc_safe(unused)) return 0;
    unsigned i=0;
    NC_RUNTIME[0]=1;NC_RUNTIME[1]=0;
    NT_READ16(SLINK_TARGET_SPECIAL_RESULT)=0xffff;
    if (s->opcode==SLINK_OP_CHOOSE_PARTY_MON) {
        nc_remove_npc();
        NT_READ16(SLINK_TARGET_TRADE_TABLE_VAR)=0xff;
        NT_SCRIPT[i++]=0x23;nc_script_word(&i,(uint32_t)nc_choose_party|1u);
        NT_SCRIPT[i++]=0x27;NT_SCRIPT[i++]=0x02;
    } else {
        NT_SCRIPT[i++]=0x69; /* lockall */
        if (s->opcode==SLINK_OP_SHOW_MENU || s->with_text) {
            NT_SCRIPT[i++]=0x0f;NT_SCRIPT[i++]=0;nc_script_word(&i,(uint32_t)s->text);
            NT_SCRIPT[i++]=0x09;NT_SCRIPT[i++]=s->opcode==SLINK_OP_SHOW_MENU?5:4;
        }
        if (s->opcode==SLINK_OP_SHOW_CHOICES) {
            NT_READ8(SLINK_TARGET_PANEL_DELAY)=2;
            NT_SCRIPT[i++]=0x23;nc_script_word(&i,(uint32_t)nc_choices_entry|1u);
            NT_SCRIPT[i++]=0x27;
            if (s->with_text) NT_SCRIPT[i++]=0x68; /* closemessage */
        }
        NT_SCRIPT[i++]=0x6b;NT_SCRIPT[i++]=0x02;
    }
    ((NtSetup)(SLINK_TARGET_SCRIPT_SETUP|1u))((const uint8_t *)NT_SCRIPT);
    return 1;
}
static int nc_poll(void *unused,uint8_t *result)
{
    if (NC_RUNTIME[0]==3) {
        ((NtVoid)(SLINK_TARGET_PANEL_SCRIPT_ENABLE|1u))();NC_RUNTIME[0]=4;return 0;
    }
    if (!nt_safe(unused)) { NC_RUNTIME[1]=1;return 0; }
    if (NC_RUNTIME[0]==4) return -1;
    if (!NC_RUNTIME[1]) return 0;
    uint16_t value=NT_READ16(NC_STATE->opcode==SLINK_OP_CHOOSE_PARTY_MON
        ? SLINK_TARGET_TRADE_TABLE_VAR:SLINK_TARGET_SPECIAL_RESULT);
#ifdef SLINK_TARGET_CARRIER_CANCEL
    if (NC_STATE->opcode==SLINK_OP_CHOOSE_PARTY_MON && value==SLINK_TARGET_CARRIER_CANCEL) value=7;
#endif
    if (value==0xffff || value==0xff) return 0;
    if (NC_STATE->opcode==SLINK_OP_CHOOSE_PARTY_MON && !(value<6 || value==7)) return -1;
    if (NC_STATE->opcode==SLINK_OP_SHOW_MENU && value>1) return -1;
    if (NC_STATE->opcode==SLINK_OP_SHOW_CHOICES && !(value<NC_STATE->choices[0] || value==127)) return -1;
    *result=(uint8_t)value;return 1;
}
static const SlinkCarrierEngine nc_engine={0,nc_safe,nc_start,nc_poll,nc_arm};
static void nc_drive_npc(void)
{
    if (!NC_NPC->initialized) { NC_NPC->oe=0xff;NC_NPC->armed=0;NC_NPC->initialized=1; }
    if (NC_NPC->epoch!=NT_MB->session_epoch) { NC_NPC->epoch=NT_MB->session_epoch;NC_NPC->armed=0; }
    if (NT_READ32(SLINK_TARGET_GMAIN+4u)!=SLINK_TARGET_FIELD_CALLBACK) return;
    if (NT_MB->opcode==SLINK_OP_TRADE_SCENE && nt_safe(0)) nc_remove_npc();
    if (!nt_safe(0) || nc_owned() || NP_STATE->active || ncall_owned()) return;
    unsigned player=NT_READ8(SLINK_TARGET_CARRIER_AVATAR+5u);
    if (player>=16 || !(NT_READ8(nc_object(player))&1)) return;
    uint32_t p=nc_object(player);
    unsigned g=NT_READ8(p+10),n=NT_READ8(p+9),key=(g<<8)|n;
    int configured=NT_MB->session_epoch && NC_CONTROL->session_epoch==NT_MB->session_epoch;
    if (NC_NPC->oe!=0xff && (g!=NC_NPC->map_g || n!=NC_NPC->map_n || !configured || !NC_CONTROL->tn_enable)) nc_remove_npc();
    int center=0;
    for (unsigned j=0;j<sizeof(slink_target_pokecenters)/sizeof(slink_target_pokecenters[0]);j++)
        if (key==slink_target_pokecenters[j]) center=1;
    if (!center && NC_NPC->oe!=0xff) nc_remove_npc();
    int trade_free=NT_STATE->phase==TP_IDLE || NT_STATE->phase==TP_DONE;
    if (configured && NC_CONTROL->tn_enable && center && trade_free) {
        if (NC_NPC->oe!=0xff && !nc_bound(NC_NPC->oe,SLINK_TARGET_CARRIER_LOCAL_ID,g,n)) {
            NC_NPC->oe=0xff;NC_NPC->armed=0;
        }
        if (NC_NPC->oe==0xff) {
            int oe=((int(*)(uint8_t,uint8_t,uint8_t,int16_t,int16_t,uint8_t))(SLINK_TARGET_CARRIER_SPAWN|1u))(
                SLINK_TARGET_CARRIER_GFX,SLINK_TARGET_CARRIER_MOVEMENT,SLINK_TARGET_CARRIER_LOCAL_ID,
                SLINK_TARGET_CARRIER_X,SLINK_TARGET_CARRIER_Y,3);
            if (oe>=0 && oe<16) {
                NC_NPC->oe=(uint8_t)oe;NC_NPC->map_g=g;NC_NPC->map_n=n;
                NT_READ8(nc_object(oe)+0x19)=0x11; /* same bounded engine wander as RR */
            }
        }
        if (NC_NPC->oe!=0xff) {
            NC_NPC->talk_oe=NC_NPC->oe;NC_NPC->talk_local=SLINK_TARGET_CARRIER_LOCAL_ID;
            NC_NPC->talk_g=g;NC_NPC->talk_n=n;NC_NPC->armed=1;
        }
    }
    if (!configured || !trade_free || !NC_NPC->armed
        || !nc_bound(NC_NPC->talk_oe,NC_NPC->talk_local,NC_NPC->talk_g,NC_NPC->talk_n)) return;
    uint32_t target=nc_object(NC_NPC->talk_oe);
    if (slink_carrier_interaction(1,NT_READ16(SLINK_TARGET_GMAIN+SLINK_TARGET_CARRIER_NEW_KEYS)&1,
        NT_READ8(p)&0x80,1,(int16_t)NT_READ16(p+0x10),(int16_t)NT_READ16(p+0x12),NT_READ8(p+0x18)&15,
        (int16_t)NT_READ16(target+0x10),(int16_t)NT_READ16(target+0x12))) {
        NC_CONTROL->pi_count++;
        NT_READ16(SLINK_TARGET_GMAIN+SLINK_TARGET_CARRIER_NEW_KEYS)&=(uint16_t)~1u;
    }
}
static void slink_native_carrier_service(void)
{
    nc_drive_npc();
    slink_carrier_service(NC_STATE,NT_MB,(const volatile uint8_t *)(NT_BASE+SLINK_TEXT_OFFSET),
        (const volatile uint8_t *)(NT_BASE+SLINK_MENU_OFFSET),&nc_engine);
}
#endif
