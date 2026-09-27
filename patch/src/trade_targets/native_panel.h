/* FR native window/task/script binding, composed only into private candidates. */
#ifndef SLINK_NATIVE_PANEL_H
#define SLINK_NATIVE_PANEL_H
#include "panel_producer.h"
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int16_t s16;
typedef int8_t s8;
#define NP_INFO ((volatile SlinkInfoV2 *)(NT_BASE+SLINK_INFO_OFFSET))
#define NP_STATE ((SlinkPanelProducer *)(NT_BASE+0xA00u))
#define NP_RUNTIME ((volatile uint32_t *)(NT_BASE+0x940u))
#define SI (&NP_STATE->snapshot)
_Static_assert(0xA00u+sizeof(SlinkPanelProducer)<=SLINK_CALL_WITNESS_OFFSET,"panel/call overlap");
#define FU(c) (u8)(0xBBu+((c)-'A'))
#define FL(c) (u8)(0xD5u+((c)-'a'))
#define FSP 0x00u
#define FEOS 0xFFu
#define FONT_SMALL 0u
#ifdef SLINK_TARGET_PANEL_FONT_NORMAL
#define FONT_NORMAL SLINK_TARGET_PANEL_FONT_NORMAL
#else
#define FONT_NORMAL 2u
#endif
#define INFO_ROWS SLINK_INFO_MAX_LINES
#define INFO_PAGE_SLOT SLINK_INFO_PAGE_SLOT
#define INFO_PITCH 13u
static const u8 sFrEmpty[]={0xff};
static const u8 sColBody[]={1,2,3},sColTitle[]={1,8,9},sColAlert[]={1,4,5};
#define GetStringWidth ((u16(*)(u8,const u8 *,s16))(SLINK_TARGET_PANEL_WIDTH|1u))
#define SetStandardWindowBorderStyle ((void(*)(u8,u8))(SLINK_TARGET_PANEL_BORDER|1u))
#define AddTextPrinterParameterized4 ((void(*)(u8,u8,u8,u8,u8,u8,const u8 *,s8,const u8 *))(SLINK_TARGET_PANEL_PRINT|1u))
#define FillWindowPixelRect ((void(*)(u8,u8,u16,u16,u16,u16))(SLINK_TARGET_PANEL_RECT|1u))
#define CopyWindowToVram ((void(*)(u8,u8))(SLINK_TARGET_PANEL_COPY|1u))
#define Menu_InitCursor ((void(*)(u8,u8,u8,u8,u8,u8,u8))(SLINK_TARGET_PANEL_CURSOR|1u))
#define CreateTask ((u8(*)(void *,u8))(SLINK_TARGET_PANEL_CREATE_TASK|1u))
#define ScheduleBgCopyTilemapToVram ((void(*)(u8))(SLINK_TARGET_PANEL_BG_COPY|1u))
#define TASK_MULTICHOICE_INPUT SLINK_TARGET_PANEL_INPUT_TASK
#define gTasks SLINK_TARGET_PANEL_TASKS
static int np_task_available(void)
{
    for (unsigned i=0;i<16;i++) if (!NT_READ8(gTasks+i*0x28u+4u)) return 1;
    return 0;
}
static u8 CreateWindowFromRect(u8 left,u8 top,u8 width,u8 height)
{
    /* script_menu.c's template, with AddWindow failure checked BEFORE tilemap. */
    struct { u8 bg,x,y,w,h,palette;u16 base; } template={0,left+1,top+1,width,height,15,
#ifdef SLINK_TARGET_PANEL_WINDOW_BASE
        SLINK_TARGET_PANEL_WINDOW_BASE
#else
        0x38
#endif
    };
    u8 win=((u8(*)(const void *))(SLINK_TARGET_PANEL_ADD_WINDOW|1u))(&template);
    if (win!=0xffu) ((void(*)(u8))(SLINK_TARGET_PANEL_PUT_TILEMAP|1u))(win);
    return win;
}
#include "panel_render.h"
/* Builder preserves the original nine entries, appending a tenth. */
#ifdef SLINK_TARGET_PANEL_STOCK_ACTIONS
__attribute__((used)) const uint32_t slink_panel_actions[2*(SLINK_TARGET_PANEL_STOCK_ACTIONS+1)]={0};
#else
__attribute__((used)) const uint32_t slink_panel_actions[20]={0};
#endif
__attribute__((used)) const uint32_t slink_panel_descriptions[10]={0};
__attribute__((used)) const u8 slink_panel_label[]={FU('S'),FU('O'),FU('U'),FU('L'),FU('L'),FU('I'),FU('N'),FU('K'),FEOS};
__attribute__((used)) const u8 slink_panel_description[]={FU('V'),FL('i'),FL('e'),FL('w'),FSP,FU('S'),FL('o'),FL('u'),FL('l'),FSP,FU('L'),FL('i'),FL('n'),FL('k'),FEOS};
__attribute__((used)) u8 slink_panel_menu_callback(void)
{
    NP_RUNTIME[1]=1;NP_RUNTIME[2]=0;
    return ((u8(*)(void))(SLINK_TARGET_PANEL_EXIT|1u))();
}
__attribute__((used)) void slink_panel_normal_menu(void)
{
    u8 (*flag)(u16)=(u8(*)(u16))(SLINK_TARGET_PANEL_FLAG_GET|1u);
    void (*append)(u8)=(void(*)(u8))(SLINK_TARGET_PANEL_APPEND|1u);
    if (flag(SLINK_TARGET_PANEL_DEX_FLAG)==1) append(0);
    if (flag(SLINK_TARGET_PANEL_PARTY_FLAG)==1) append(1);
    append(2);
#ifdef SLINK_TARGET_PANEL_NAV_FLAG
    if (flag(SLINK_TARGET_PANEL_NAV_FLAG)==1) append(3);
    append(4);append(5);append(6);
#else
    append(3);append(4);append(5);
#endif
    if (!NP_STATE->active && (NT_STATE->phase==TP_IDLE || NT_STATE->phase==TP_DONE)
        && slink_panel_valid(NP_INFO,NT_MB->session_epoch))
#ifdef SLINK_TARGET_PANEL_STOCK_ACTIONS
        append(SLINK_TARGET_PANEL_STOCK_ACTIONS);
    append(SLINK_TARGET_PANEL_EXIT_ACTION);
#else
        append(9);
    append(6);
#endif
}
static int np_safe(void *unused)
{
    return !nc_owned() && !ncall_owned() && nt_safe(unused) && (NT_STATE->phase==TP_IDLE || NT_STATE->phase==TP_DONE)
        && np_task_available();
}
static int np_start(void *unused,const SlinkInfoV2 *snapshot)
{
    (void)snapshot;
    if (!np_safe(unused)) return 0;
    uint32_t fn=(uint32_t)show_info_entry|1u;
    NT_SCRIPT[0]=0x69;NT_SCRIPT[1]=0x23; /* lockall/callnative */
    for (unsigned n=0;n<4;n++) NT_SCRIPT[2+n]=(uint8_t)(fn>>(8*n));
    NT_SCRIPT[6]=0x27;NT_SCRIPT[7]=0x6B;NT_SCRIPT[8]=0x02; /* waitstate/releaseall/end */
    NT_READ16(SLINK_TARGET_SPECIAL_RESULT)=0xFFFF;
    NT_READ8(SLINK_TARGET_PANEL_DELAY)=2; /* ignore launching button for two task ticks */
    NP_RUNTIME[0]=1;
    ((NtSetup)(SLINK_TARGET_SCRIPT_SETUP|1u))((const uint8_t *)NT_SCRIPT);
    return 1;
}
static int np_poll(void *unused,uint8_t *result)
{
    if (NP_RUNTIME[0]==3) { /* allocation failure after script began */
        ((NtVoid)(SLINK_TARGET_PANEL_SCRIPT_ENABLE|1u))();
        NP_RUNTIME[0]=4;return 0;
    }
    if (NP_RUNTIME[0]>=2 && nt_safe(unused)) {
        *result=NP_RUNTIME[0]==4?0xFF:(uint8_t)NT_READ16(SLINK_TARGET_SPECIAL_RESULT);
        NP_RUNTIME[0]=0;return 2;
    }
    return NP_RUNTIME[0]==2?1:0;
}
static const SlinkPanelEngine np_engine={0,np_safe,np_start,np_poll};
static void slink_native_panel_service(void)
{
    int menu=0;
    if (NP_RUNTIME[1] && nt_safe(0)) {
        if (!NP_RUNTIME[2]) {
            ((void(*)(u8,s8))(SLINK_TARGET_PANEL_FADE|1u))(0,0);
            NP_RUNTIME[2]=1;
        } else if (!NT_MB->opcode) { NP_RUNTIME[1]=0;menu=1; }
    }
    slink_panel_service(NP_STATE,NT_MB,NP_INFO,&np_engine,menu);
}
#endif
