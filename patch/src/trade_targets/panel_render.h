/* Shared existing panel layout; engine calls are target-bound by native_panel.h. */
static const u8 sInfoTitle[] = { FU('S'), FL('o'), FL('u'), FL('l'), FSP,
                                 FU('L'), FL('i'), FL('n'), FL('k'), FEOS };

/* Copy a staged slot onto the stack, guaranteeing termination. Copying rather than repairing in
 * place keeps drawing IDEMPOTENT: re-opening the panel without restaging must render identically. */
static const u8 *slot_str(volatile u8 *src, u8 *buf)
{
    if (src[0] == 0xFF || src[0] == 0x00) return sFrEmpty;
    for (u8 i = 0; i < 32; i++) buf[i] = src[i];
    buf[31] = 0xFF;
    return (const u8 *)buf;
}

/* x for a right-aligned string in the 216px content area. GetStringWidth is pixel-exact for English
 * (the renderer and the measurer both skip letterSpacing outside Japanese mode), so this needs no
 * fudge factor. */
static u8 rx(const u8 *s)
{
    u32 w = GetStringWidth(FONT_SMALL, s, 0);
    return (u8)(w >= 216u ? 0u : 216u - w);
}

/* Split one staged slot into fields on 0xFE (what lua/mailbox.lua's fr_encode already emits for
 * "\n"). Copies to the caller's stack buffer first, so a redraw of the same stage is identical —
 * splitting in place would turn every field separator into a terminator and render name-only rows
 * the second time the panel opened. Returns the field count, which is how the row KIND is decided:
 * 1 = plain text, 2 = label/value, 5 = mon row. Self-describing, so no metadata byte is stored and
 * Lua can mix row kinds on one page without the patch knowing anything about the content. */
static u8 split_slot(volatile u8 *src, u8 *buf, const u8 *f[7])
{
    u8 i, k = 1;
    for (i = 0; i < 32; i++) buf[i] = src[i];
    buf[31] = 0xFF;
    for (i = 0; i < 7; i++) f[i] = sFrEmpty;
    f[0] = buf;
    for (i = 0; i < 32 && buf[i] != 0xFF; i++)
        if (buf[i] == 0xFE) { buf[i] = 0xFF; if (k < 7) f[k++] = &buf[i + 1]; }
    return k;
}

/* Decimal from FR digits (charmap 0xA1 = '0'). Written out rather than using a library atoi because
 * this blob has no libc, and deliberately without '/' or '%' on a runtime value — those emit a call
 * to __aeabi_uidiv, which does not exist here either. */
static u8 parse_u8(const u8 *s)
{
    u32 v = 0, n = 0;
    while (*s >= 0xA1u && *s <= 0xAAu && n < 3) { v = v * 10u + (u32)(*s - 0xA1u); s++; n++; }
    return (u8)(v > 255u ? 255u : v);
}

#define BAR_W 38u                          /* inner track width in px; Lua scales HP to 0..38 */
static const u8 sLvGlyph[] = { 0xF9, 0x05, 0xFF };   /* the engine's own "Lv" glyph (gText_Lv) */

/* Draw the bracket that ties a Soul Link PAIR's two rows together:
 *
 *     RT03 ┬ Bulbasaur  Lv12 [####--]   19/23     <- yours
 *          └ Squirtle   Lv11 [------]     FNT     <- your partner's
 *
 * Pairing is the whole point of this screen, and two adjacent rows sharing an area tag conveyed it
 * only by implication. The bracket is drawn rather than printed — three filled rectangles, no glyphs
 * — so it costs no charmap and lines up with the text exactly. Blue, matching the area tag it hangs
 * from. `y` is the FIRST row of the pair; the second is always y + INFO_PITCH. */
static void info_pair_bracket(u8 win, u8 y)
{
    u8 mid1 = (u8)(y + 6), mid2 = (u8)(y + INFO_PITCH + 6);
    FillWindowPixelRect(win, 0x88, 24, mid1, 1, (u16)(mid2 - mid1 + 1));   /* the stem */
    FillWindowPixelRect(win, 0x88, 24, mid1, 4, 1);                        /* tick into row 1 */
    FillWindowPixelRect(win, 0x88, 24, mid2, 4, 1);                        /* tick into row 2 */
}

/* One party-menu-style row: LABEL  Name  Lv## [====----]      cur/max
 * Modelled on the party menu because that is the screen every player already reads HP from. */
static void info_mon_row(u8 win, u8 y, const u8 *f[7])
{
    u8 bp = parse_u8(f[4]);
    if (bp > BAR_W) bp = BAR_W;
    /* Optional 6th field: the mon's STATE, because an empty bar alone is ambiguous. 'B' = boxed —
     * alive but not in the party, so it has no live HP and must NOT be coloured like a corpse.
     * Anything else (including no 6th field at all, which is what an older stager sends) keeps the
     * original rule: an empty bar means dead. Conflating boxed with dead would tell a player their
     * mon died when it did not, which is the one mistake this screen must never make. */
    u8 boxed = (f[5][0] == FU('B'));
    /* A dead mon is the one thing on this screen that must be unmissable, so it is the one thing
     * that gets the alert colour — on both the name and the HP text. */
    const u8 *col = (bp || boxed) ? sColBody : sColAlert;
    AddTextPrinterParameterized4(win, FONT_SMALL, 0,   y, 0, 0, sColTitle, 0xFF, f[0]);  /* area */
    AddTextPrinterParameterized4(win, FONT_SMALL, 30,  y, 0, 0, col,       0xFF, f[1]);  /* name */
    AddTextPrinterParameterized4(win, FONT_SMALL, 82,  y, 0, 0, sColBody,  0xFF, sLvGlyph);
    AddTextPrinterParameterized4(win, FONT_SMALL, 90,  y, 0, 0, sColBody,  0xFF, f[2]);  /* level */
    AddTextPrinterParameterized4(win, FONT_SMALL, rx(f[3]), y, 0, 0, col,  0xFF, f[3]);  /* cur/max */
    /* Bar: outline, then track, then fill. FillWindowPixelRect clips internally, but bp is clamped
     * above anyway so a bad stage can't push the fill into the HP-text column. */
    /* 7th field: a status token (PSN/PAR/SLP/BRN/FRZ/TOX), drawn in the gap between the bar and
     * the right-aligned HP text. Status is invisible from an HP bar, and a poisoned linked mon is
     * exactly what a player opens this screen to check. Alert-coloured because it is a warning. */
    AddTextPrinterParameterized4(win, FONT_SMALL, 152, y, 0, 0, sColAlert, 0xFF, f[6]);
    FillWindowPixelRect(win, 0x22, 108, (u16)(y + 3), 40, 7);
    FillWindowPixelRect(win, 0x11, 109, (u16)(y + 4), BAR_W, 5);
    if (bp && !boxed) {
        /* FRLG's own thresholds, >50% green / >20% yellow / else red — as two compares on the
         * pixel width, so there is still no division anywhere. */
        u8 c = (bp > 19u) ? 6u : (bp > 7u) ? 5u : 4u;
        FillWindowPixelRect(win, (u8)(c | (c << 4)), 109, (u16)(y + 4), bp, 5);
    }
}

static void show_info_entry(void)
{
    if (!np_task_available()) { NP_RUNTIME[0]=3;return; }
    u8 n = SI->lines;
    /* Clamp and repair, never bail. Everything below must reach CreateTask: we are a callnative
     * inside a lockall'd script whose `waitstate` is resolved ONLY by the input task created at the
     * end, so an early return leaves the player in a locked overworld with no window and no way
     * out. (show_choices_entry still has the original bailing shape and that latent softlock.) */
    if (n == 0) n = 1;
    if (n > INFO_ROWS) n = INFO_ROWS;

    /* 27x13, NOT 27x14. CreateWindowFromRect hardcodes baseBlock 0x38 and the field message-box
     * window sits at 0x198, so the budget is 352 tiles — 27x14 = 378 spends 26 tiles INTO the
     * msgbox. The shipped version had that bug; for run_choices(with_text) the msgbox it would
     * corrupt is a live one. 27x13 = 351 ends at 0x196, one tile clear. */
    u8 win = CreateWindowFromRect(1, 2, 27, 13);
    if (win==0xFF) { NP_RUNTIME[0]=3;return; }
    SetStandardWindowBorderStyle(win, 0);   /* draws the player's OPTIONS frame + PIXEL_FILL(1) */

    /* Header: title left, page indicator right — the layout every real RR info screen uses (the
     * Pokemon Info page puts its title top-left and its button hints top-right). */
    u8 pgbuf[32];
    const u8 *pg = slot_str(&SI->text[INFO_PAGE_SLOT][0], pgbuf);
    AddTextPrinterParameterized4(win, FONT_NORMAL, 0, 0, 0, 0, sColTitle, 0xFF, sInfoTitle);
    AddTextPrinterParameterized4(win, FONT_SMALL, rx(pg), 1, 0, 0, sColBody, 0xFF, pg);
    FillWindowPixelRect(win, 0x33, 0, 15, 216, 1);          /* hairline rule under the header */

    for (u8 i = 0; i < n; i++) {
        u8 buf[32];
        const u8 *f[7];
        u8 y  = (u8)(18 + INFO_PITCH * i);
        u8 nf = split_slot(&SI->text[i][0], buf, f);
        if (nf >= 5) {
            /* A row whose FIRST field is empty continues the pair above it — the slot then starts
             * with the 0xFE separator, so one byte read decides it. No extra field, no string
             * compare, and Lua keeps control of the grouping. */
            if (i + 1 < n && SI->text[i + 1][0] == 0xFE) info_pair_bracket(win, y);
            info_mon_row(win, y, f);
        } else if (nf == 2) {
            /* label/value, the trainer-card and OPTIONS grammar: label left, value right in the
             * accent colour. Blue rather than the save box's red, because on this screen red is
             * reserved for "this mon is dead". */
            AddTextPrinterParameterized4(win, FONT_SMALL, 0, y, 0, 0, sColBody, 0xFF, f[0]);
            AddTextPrinterParameterized4(win, FONT_SMALL, rx(f[1]), y, 0, 0, sColTitle, 0xFF, f[1]);
        } else {
            AddTextPrinterParameterized4(win, FONT_SMALL, 0, y, 0, 0, sColBody, 0xFF, f[0]);
        }
    }

    CopyWindowToVram(win, 2 /*COPYWIN_GFX*/);
    /* The cursor is NOT decorative — Task_MultichoiceMenu_HandleInput drives input through the
     * sMenu state this populates, so it is repointed, never dropped. Parking it beside the page
     * indicator makes it read as the "press A" affordance it actually is, instead of an arrow
     * selecting a body row that isn't selectable. */
    u8 cx = rx(pg);
    Menu_InitCursor(win, FONT_SMALL, (u8)(cx >= 10 ? cx - 10 : 0), 1, 13, 1, 0);
    u8 tid = CreateTask((void *)(TASK_MULTICHOICE_INPUT | 1u), 80);
    volatile s16 *d = (volatile s16 *)(gTasks + (u32)tid * 0x28u + 8u);
    d[4] = 0;      /* tIgnoreBPress: 0 so B closes too */
    d[5] = 0;      /* tWrapAround: one row, nowhere to wrap */
    d[6] = win;    /* tWindowId */
    d[7] = 0;      /* tMultichoiceId: benign id (no help description) */
    ScheduleBgCopyTilemapToVram(0);
    NP_RUNTIME[0]=2;   /* this open is handled (step 3's frame-hook path reads the difference) */
}
