/* Gen 4 (HG/SS) companion C4: the info-panel POLICY -- every decision, no game call.
 * Card C4 -- docs/gen4/companion/C4_PANEL_SPEC.md (decision block lines 1-18 bind) and
 * docs/gen4/companion/C4_FACTS.md for the facts this header leans on.
 *
 * Header-only, C11, NO file-scope object: every function is `static inline` and every
 * table is a macro (patch/src/nds/gen4/README.md:57-59 -- a static would move 0x021E5900
 * and with it every overlay address and every pinned hook site). The shared
 * `static const` record bindings arrive through panel_producer.h's own include chain
 * (panel_producer.h:9 -> trade_producer.h:21 -> record_binding.h:156-181); this card adds
 * none.
 *
 * WHY A SEAM: everything the policy is allowed to know about the game is the call table
 * below, bound by patch/src/nds/gen4/panel.c. Nothing here names an address, includes a
 * pret header or reads a global, so the whole lifecycle -- refuse-unless-safe, refuse-unless
 * the menu is open, validate, snapshot, one panel in flight, draw/close handshake, the
 * A/close result rule -- is exercised on a host gcc by
 * tests/unit/test_gen4_panel_policy.py. That is the MODEL half of C4 falsifiers F6, F7, F8
 * and F9. The PHYSICAL half (F3 the drawn glyphs, F4 the leak, F5 the field reload) is not a
 * test and is not claimed here.
 *
 * THE SHAPE OF A VISIT, in order. The order is load-bearing, not stylistic:
 *
 *   0. the layout stamp. A mismatch resets rather than reinterprets: re-initialising is
 *      the only safe reading of bytes whose layout is not the one this card knows
 *      (the same rule as C3's sound layout, sound_policy.h:96-110).
 *   1. the both-ends gate, INSIDE the shared producer's safe() (panel_producer.h:49):
 *      the fade must be finished AND the START menu must be the launching context. This
 *      is falsifier F9 read from the ROM side; the host's other half is the capability
 *      check (C4_PANEL_SPEC.md:537). The un-posted open additionally requires menu_open,
 *      which the shared service takes as its own argument (panel_producer.h:34, :47), so
 *      the menu gate is passed twice on purpose: dropping either one still blocks the open.
 *   2. payload validation, in the shared producer, UNCHANGED (slink_panel_valid,
 *      panel_producer.h:22-32): epoch nonzero and equal to the mailbox's, request_seq
 *      nonzero, enable, 1 <= lines <= SLINK_INFO_MAX_LINES, and a terminator unit in every
 *      row below `lines` plus row SLINK_INFO_PAGE_SLOT. A refusal is acked FAIL with
 *      SLINK_REASON_BAD_ARGS (panel_producer.h:51) -- the reason F8 pins, so this card
 *      adds no epoch gate of its own and no second reason vocabulary. (Deliberate.)
 *   3. the snapshot. The producer copies the whole SlinkInfoV2 out of the host's region
 *      (panel_producer.h:54-56) and starts from the copy, so the drawn text is immune to
 *      a host rewrite; a rewrite that changes request_seq or session_epoch is likewise
 *      ignored by the drain (panel_producer.h:39-40). Both are tested, not assumed.
 *   4. one panel in flight: while the producer is active no new start is taken, and a
 *      posted request in that window is acked FAIL/BAD_ARGS (panel_producer.h:49-52).
 *   5. the A/close result rule (panel.h: SLINK_GEN4_PANEL_RESULT_*), which is the app's
 *      only free choice and is Gen 2's no-wrap rule (patch/gen2/src/panel.asm:57-69,
 *      C4_PANEL_SPEC.md:7-11).
 */
#ifndef SLINK_GEN4_PANEL_POLICY_H
#define SLINK_GEN4_PANEL_POLICY_H

#include "panel.h"
#include "panel_producer.h"

/* ---------------------------------------------------------------- what a visit concluded */
enum SlinkGen4PanelOutcome {
    SLINK_PANEL_IDLE = 0, /* nothing published, nothing live: no state, no ack        */
    SLINK_PANEL_DRAINED,  /* a panel was live and still is: poll ran, no new start    */
    SLINK_PANEL_STARTED,  /* a validated snapshot started the app on this visit       */
    SLINK_PANEL_CLOSED,   /* the live panel closed on this visit                      */
    SLINK_PANEL_REFUSED   /* a published request was refused and acked FAIL/BAD_ARGS  */
};

/* ---------------------------------------------------------------- the engine seam
 * Three of the five are the shared producer's own three (context/text/safe/start/poll,
 * panel_producer.h:10-16); the first three below are the safe() body, split so that each
 * fact is its own binding and each is separately falsifiable. panel.c binds them to:
 *
 *   fade_finished  IsPaletteFadeFinished() != 0  (include/unk_0200FA24.h:11). This is the
 *                  trainer card's own precondition, verbatim: the START menu begins a
 *                  palette fade and only then launches the app (C4_FACTS.md, fact Q8:
 *                  start_menu.c:1096-1098, :705-714, asm/overlay_01_021E5900.s:1237-1276).
 *   menu_open      the START menu is the context that is launching an app. UNVERIFIED as a
 *                  single engine predicate -- there is no "start menu is open" flag in the
 *                  traced chain -- so it is a seam, never a guess.
 *   app_running    a child app is already resident (FieldSystem_LaunchApplication asserts
 *                  unk0->unk4 == NULL, field_system.c:128). Optional: NULL means "no such
 *                  guard exists in this build", the same convention C3 uses for its
 *                  optional seams (sound_policy.h:70-73).
 *   start          start the panel app on a snapshot the producer has already copied.
 *                  Returns 0 to refuse, which the producer acks FAIL/BAD_ARGS
 *                  (panel_producer.h:57-59).
 *   poll           0 opening, 1 drawn, 2 closed, writing the app's result byte on 2
 *                  (panel_producer.h:15). The app builds that byte with
 *                  slink_gen4_panel_result() below.
 *
 * text is the record binding's own SlinkTextSpec. For Gen 4 that is exactly
 * `slink_binding_gen4_pk4.text` = { 2, SLINK_CHARSET_GEN4, 0xFFFFu }
 * (record_binding.h:165-171); the panel passes it through rather than restating it, because
 * a second copy is a second thing that can drift. C4_FACTS.md records that the charset
 * member is never consulted by the validator.
 *
 * A NULL member that IS part of the gate reads as NOT safe (fail closed): an absent gate is
 * not an open door.
 */
typedef struct {
    void *context;
    const SlinkTextSpec *text;
    int (*fade_finished)(void *);
    int (*menu_open)(void *);
    int (*app_running)(void *);
    int (*start)(void *, const SlinkInfoV2 *);
    int (*poll)(void *, uint8_t *);
} SlinkGen4PanelEngine;

/* ---------------------------------------------------------------- the per-card sub-struct
 * Byte-for-byte the shape of beacon.h's SlinkGen4StatePanel: the layout stamp, then the
 * shared producer BY VALUE, because the state block is where a producer lives and a second
 * copy would be a second, stale transaction (beacon.h). Declared here rather than included
 * so this card does not depend on SlinkGen4State; the parity -- the struct's size and the
 * producer's offset -- is pinned by the host test. `caps` is this card's contribution to
 * the published word and this header is its only writer (panel.h).
 */
typedef struct {
    uint32_t layout;
    SlinkPanelProducer producer;
    uint32_t caps;
} SlinkGen4PanelState;

/* Zero a producer. Byte-wise because SlinkInfoV2's header is host-owned: reinterpreting it
 * is exactly what the layout reset must not do (access through uint8_t/char is legal). */
static inline void slink_gen4_panel_clear(SlinkPanelProducer *p)
{
    uint8_t *bytes = (uint8_t *)p;
    for (unsigned n = 0; n < sizeof *p; n++) bytes[n] = 0u;
    p->active = 0u;
}

static inline void slink_gen4_panel_layout(SlinkGen4PanelState *s)
{
    /* A zeroed block (fresh allocation, C2's zero-fill) means "this card has never run"; a
     * mismatch means "written by another layout". Both are reset, never reinterpreted: the
     * reset preserves nothing, and a reset card advertises nothing until it proves ready
     * again (the C3 rule, sound_policy.h:96-111). */
    if (s->layout != SLINK_GEN4_PANEL_LAYOUT) {
        s->layout = SLINK_GEN4_PANEL_LAYOUT;
        s->caps = 0u;
        slink_gen4_panel_clear(&s->producer);
    }
}

/* ---------------------------------------------------------------- the both-ends gate
 * Reached only from the shared producer, immediately before a start (panel_producer.h:49),
 * and it is the whole of falsifier F9's ROM half. Order matters only for diagnostics: any
 * false answer refuses identically.
 */
static inline int slink_gen4_panel_safe(void *context)
{
    const SlinkGen4PanelEngine *e = (const SlinkGen4PanelEngine *)context;
    if (!e) return 0;
    if (!e->fade_finished || !e->fade_finished(e->context)) return 0;
    if (!e->menu_open || !e->menu_open(e->context)) return 0;
    if (e->app_running && e->app_running(e->context)) return 0;
    return 1;
}

/* Bind the shared engine the producer takes (panel_producer.h:33-34). The shared context is
 * the SEAM, not the caller's context: the shared safe() receives one pointer and the gates
 * need all three predicates, while start/poll still get the caller's own context. */
static inline void slink_gen4_panel_bind(SlinkPanelEngine *out, const SlinkGen4PanelEngine *e)
{
    out->context = (void *)(uintptr_t)e;
    out->text = e->text;
    out->safe = slink_gen4_panel_safe;
    out->start = e->start;
    out->poll = e->poll;
}

/* ---------------------------------------------------------------- the A/close rule
 * Gen 2's, verbatim (patch/gen2/src/panel.asm:57-69): A with a FURTHER page advances and
 * reports 0; everything else -- B, A on the last page, a zero page count, and the page
 * counter carrying out of 255 -- closes and reports 0x7F. The wrap is why `next` is computed
 * in `unsigned`: page 255 must close, not wrap to page 0. */
static inline uint8_t slink_gen4_panel_result(int is_a, uint8_t page, uint8_t pages)
{
    unsigned next = (unsigned)page + 1u;
    return (uint8_t)((is_a && next < (unsigned)pages) ? SLINK_GEN4_PANEL_RESULT_MORE
                                                      : SLINK_GEN4_PANEL_RESULT_CLOSE);
}

/* ---------------------------------------------------------------- one service visit
 * Pure with respect to the game: it reads the mailbox and the info region, writes the state
 * block and the mailbox's ack fields through the shared producer, and calls at most two
 * engine functions (start, poll -- and poll only while a panel is live). No address, no
 * allocation, no game header. Returns what the visit concluded, for panel.c and for tests. */
static inline int slink_gen4_panel_step(SlinkGen4PanelState *s, volatile SlinkMailboxV2 *m,
                                       volatile SlinkInfoV2 *i, const SlinkGen4PanelEngine *e)
{
    SlinkPanelEngine engine;
    uint16_t ack_before;
    uint16_t status_before;
    uint16_t closed_before;
    int was_active;

    if (!s || !m || !i || !e) {
        return SLINK_PANEL_REFUSED; /* fail closed: a null argument is never a request */
    }

    slink_gen4_panel_layout(s);

    /* C4's contribution to the published word, rebuilt on EVERY visit -- so a card that
     * stops advertising loses the bit in that same visit, which is what the beacon's
     * compose-after-the-fan-out rule requires (beacon.h, Slink_NDS_PublishCaps). This
     * header never writes m->capabilities: the beacon is the single writer and stamps last
     * (the C3 rule, sound_policy.h:209-211). The Service existing IS the build-time proof
     * that the row and the overlay are in this image (dispatch.c:41-43,
     * C4_PANEL_SPEC.md:151-156), so there is no readiness predicate to read here. */
    s->caps = (uint32_t)SLINK_GEN4_PANEL_CAPABILITIES;

    /* tp_ack writes status on every ack (trade_producer.h:93-104), so an unchanged
     * (status, ack_seq) pair means this visit acked nothing at all. That is how a refusal
     * is told from a quiet visit without teaching this card a second reason vocabulary. */
    status_before = m->status;
    ack_before = m->ack_seq;
    was_active = s->producer.active;
    closed_before = i->closed_seq;

    slink_gen4_panel_bind(&engine, e);
    slink_panel_service(&s->producer, m, i, &engine,
                        (e->menu_open && e->menu_open(e->context)) ? 1 : 0);

    if (!was_active && s->producer.active) return SLINK_PANEL_STARTED;
    if (was_active && !s->producer.active) return SLINK_PANEL_CLOSED;
    if (m->ack_seq != ack_before || m->status != status_before) return SLINK_PANEL_REFUSED;
    /* A close and the NEXT start can land in the SAME visit: the producer's drain branch
     * clears `active` (panel_producer.h:44) and control then falls through to the
     * take-a-request branch, which starts again if the host left the payload staged. That is
     * the shared producer's contract and this card does not change it -- it is why the HOST
     * must clear enable or bump request_seq after a close (pinned by the host test). Tell it
     * apart from an ordinary drain by the published close, not by `active`. */
    if (was_active && s->producer.active && i->closed_seq != closed_before) {
        return SLINK_PANEL_CLOSED;
    }
    return was_active ? SLINK_PANEL_DRAINED : SLINK_PANEL_IDLE;
}

#endif /* SLINK_GEN4_PANEL_POLICY_H */