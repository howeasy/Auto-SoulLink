/* The patch version on the Gen 3 main menu (the New Game / Continue screen), printed with the game's own font.
 *
 * Neither menu has a static BG asset to patch: the whole BG0 map is built at run time by windows. So the frame hook owns ONE
 * window on the free tiles of the menu, draws "SoulLink <version>" in it once and removes it when the menu is left:
 *   - the line is right-aligned on the two tile rows at SLM_TOP, in the last box column: the free band under the boxes in
 *     every layout but Mystery Gift (transparent pixels, text styled for each game's backdrop), the right half of the last
 *     box in that one (window filled like the box, the menu's own dark label ink), so it sits in the same place in all of them.
 *   - it is gated on gMain.callback2 == the menu AND the menu task (always gTasks[0], created right after ResetTasks) being
 *     active and idling in its input or its cursor-update function, all ROM pointers, so another ROM build or scene never matches.
 *   - the menu never rewrites BG0 once it idles (a cursor move only moves WIN0), so one draw per menu entry is enough.
 *
 * The includer defines, for its game (raw addresses; code addresses get the Thumb bit here, SLM_CB2 and the task functions
 * are the Thumb-set pointers the game itself stores):
 *   SLM_GMAIN_CB2 SLM_CB2 SLM_TASK0 SLM_TASK_INPUT SLM_TASK_SELECT SLM_MENU_TYPE_BOXED SLM_STATE
 *   SLM_ADD_WINDOW SLM_REMOVE_WINDOW SLM_PUT_TILEMAP SLM_COPY SLM_FILL SLM_PRINT SLM_WIDTH
 *   SLM_FONT SLM_LEFT SLM_TOP SLM_COLS SLM_BASE SLM_TEXT_Y SLM_MARGIN SLM_PLAIN_TEXT SLM_PLAIN_SHADOW
 * and may define SLINK_MENU_TEXT (the 0xFF-terminated charmap bytes; build.py passes the real one from --version). */
#ifndef SLINK_NATIVE_MENU_H
#define SLINK_NATIVE_MENU_H
#include <stdint.h>

#define SLM_U(c) (uint8_t)(0xBBu + ((c) - 'A'))
#define SLM_L(c) (uint8_t)(0xD5u + ((c) - 'a'))
#ifndef SLINK_MENU_TEXT
#define SLINK_MENU_TEXT SLM_U('S'), SLM_L('o'), SLM_L('u'), SLM_L('l'), SLM_U('L'), SLM_L('i'), SLM_L('n'), SLM_L('k'), \
    0x00u, SLM_L('d'), SLM_L('e'), SLM_L('v'), 0xFFu
#endif

#define SLM_R32(a) (*(volatile uint32_t *)(a))
#define SLM_R16(a) (*(volatile uint16_t *)(a))
#define SLM_R8(a) (*(volatile uint8_t *)(a))
#define SLM_ROWS 2u                    /* a 16 px line: the menu labels' own height */
#define SLM_PIXEL_FILL(c) ((uint8_t)((c) | ((c) << 4)))
#define SLM_COPYWIN_FULL 3u            /* tiles and tilemap */
#define SLM_FAILED 0xFFu

static const uint8_t slm_text[] = { SLINK_MENU_TEXT };
/* {background, text, shadow} palette-15 indices; 10/11/12 are the menu's own white / dark ink / light grey and 14 is black.
 * boxed: the menu's own label style. plain (no box behind it): FireRed's backdrop is a dark lavender the menu dims, so white
 * text with a black shadow; Emerald's is bright and only BG0 dims, so the menu's own dark ink with its light-grey shadow. */
static const uint8_t slm_plain[] = { 0, SLM_PLAIN_TEXT, SLM_PLAIN_SHADOW };
static const uint8_t slm_boxed[] = { 10, 11, 12 };
_Static_assert(sizeof(slm_text) >= 2 && sizeof(slm_text) <= 20, "menu line: 'SoulLink ' plus at most ten characters and the terminator");

/* SLM_STATE: 0 = nothing drawn, 1.. = our window id + 1, SLM_FAILED = AddWindow had no room (do not retry this entry). */
static void slm_draw(volatile uint8_t *state)
{
    struct { uint8_t bg, left, top, width, height, palette; uint16_t base; } window;    /* a WindowTemplate */
    int boxed = (int)SLM_R16(SLM_TASK0 + 8u) >= (int)SLM_MENU_TYPE_BOXED;      /* gTasks[0].data[0] = the menu's layout */
    uint8_t win;
    uint32_t width, x;
    /* field by field: a constant initialiser becomes a memcpy, and this payload links no libc */
    window.bg = 0; window.left = SLM_LEFT; window.top = SLM_TOP; window.width = SLM_COLS; window.height = SLM_ROWS;
    window.palette = 15; window.base = SLM_BASE;
    win = ((uint8_t (*)(const void *))(SLM_ADD_WINDOW | 1u))(&window);
    if (win == 0xFFu) { *state = SLM_FAILED; return; }
    ((void (*)(uint8_t, uint8_t))(SLM_FILL | 1u))(win, SLM_PIXEL_FILL(boxed ? 10u : 0u));
    width = ((uint16_t (*)(uint8_t, const uint8_t *, int16_t))(SLM_WIDTH | 1u))(SLM_FONT, slm_text, 0);
    x = width + SLM_MARGIN < SLM_COLS * 8u ? SLM_COLS * 8u - SLM_MARGIN - width : 0;    /* right-aligned; the engine clips the rest */
    ((void (*)(uint8_t, uint8_t, uint8_t, uint8_t, uint8_t, uint8_t, const uint8_t *, int8_t, const uint8_t *))
        (SLM_PRINT | 1u))(win, SLM_FONT, (uint8_t)x, SLM_TEXT_Y, 0, 0, boxed ? slm_boxed : slm_plain, -1, slm_text);
    ((void (*)(uint8_t))(SLM_PUT_TILEMAP | 1u))(win);
    ((void (*)(uint8_t, uint8_t))(SLM_COPY | 1u))(win, SLM_COPYWIN_FULL);
    *state = (uint8_t)(win + 1u);
}

static void slm_service(void)
{
    volatile uint8_t *state = (volatile uint8_t *)SLM_STATE;
    uint32_t func = SLM_R32(SLM_TASK0), in_menu_scene = SLM_R32(SLM_GMAIN_CB2) == SLM_CB2;
    if (in_menu_scene && SLM_R8(SLM_TASK0 + 4u) && (func == SLM_TASK_INPUT || func == SLM_TASK_SELECT)) {   /* +4 = isActive */
        if (!*state) slm_draw(state);
    } else if (*state) {
        /* The menu is fading out or being left. While its scene is still current the window is ours to free (the fade keeps
         * showing the VRAM it already holds); once the scene changed the next InitWindows owns everything, so only forget. */
        if (*state != SLM_FAILED && in_menu_scene) ((void (*)(uint8_t))(SLM_REMOVE_WINDOW | 1u))((uint8_t)(*state - 1u));
        *state = 0;
    }
}
#endif
