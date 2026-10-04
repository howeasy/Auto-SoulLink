/* Gen 4 (HG/SS) companion C3: the sound POLICY -- every decision, no game call.
 * Card C3 -- docs/gen4/companion/C3_SOUND_SPEC.md (decision block lines 1-24 binds).
 *
 * Header-only, C11, no file-scope object: every function is static inline and the code
 * table is a switch, never a const array (a static const table is .rodata bytes in an
 * ARM9 image with no slack, and the C2 rule forbids a file-scope object outright --
 * beacon.h, "session state"; patch/src/nds/gen4/README.md:57-59).
 *
 * WHY A SEAM: everything the policy is allowed to know about the game is five calls that
 * sound.c binds to real engine functions. Nothing below names an address, reads a global,
 * or needs the pret headers, so the whole lifecycle -- map the code, refuse the hole, hold
 * across visits, saturate, consume, ack -- is exercised by tests/unit/test_gen4_sound_codes.py
 * on a host gcc with a fake engine. That is the MODEL half of falsifiers F4/F5/F6; the
 * PHYSICAL half (F1: an SE is audible, and which handle it lands on) is not a test and is
 * not claimed here (C3_SOUND_SPEC.md:487, §6 Q3).
 *
 * THE SHAPE OF A VISIT, in order. The order is load-bearing, not stylistic: Gen 2 checks
 * the reset latch BEFORE the empty/invalid path so "blocked" wins over "no request"
 * (patch/gen2/src/sfx.asm:34-36, C3_SOUND_SPEC.md:250).
 *
 *   0. stamp/validate this card's sub-struct layout (fail closed on a mismatch)
 *   1. sound-ready latch.  Not ready: EVERY request is consumed unplayed with the caller's
 *      not_ready reason -- refused, not held (C3_SOUND_SPEC.md:266-268: before
 *      InitSoundData there is no sound system at all, NNS_SndArcInit and GF_SndHandleInitAll
 *      are inside it, and GF_SoundDataInit has zeroed the handle array). The latch releases
 *      at the next visit after ready (§5 "hold-blocked latch").
 *   2. foreign opcode: return WITHOUT acking (F6: the dispatcher calls every producer every
 *      visit and each producer ignores opcodes it does not own; the shared trade producer
 *      does the same). A hold whose request is no longer published is abandoned here --
 *      never acked, because the slot is not ours any more.
 *   3. epoch gate, identical to sound_producer.h:18-19: zero -> CLIENT_TOO_OLD, mismatch ->
 *      IDENTITY. The mailbox is in ITCM, which survives a soft reset, so a request from the
 *      previous boot is still published at the first visit of the next one
 *      (C3_SOUND_SPEC.md:268-275).
 *   4. the code. Index 2 is the hole -> the title-private SOUND_CODE_REFUSED; anything
 *      outside 1..4 -> SLINK_REASON_BAD_ARGS. Both are CONSUMED unplayed, never queued
 *      (F4/F5; the Gen 2 shape is `cp SLINK_SFX_NOTIFY + 1 ; jr nc`, sfx.asm:40-41).
 *   5. one sound in flight. The hold counter saturates at 240 visits and the request is
 *      consumed exactly once, on play or on expiry (C3_SOUND_SPEC.md:253-256).
 *
 * Two refusals are named by the caller, not here: "not initialised yet" and "hold expired".
 * The spec pins the reason for every refusal it knows (F4 BAD_ARGS, F5 32, the epoch pair
 * from the shared producer) and names NONE for those two, so this card does not invent one.
 */
#ifndef SLINK_GEN4_SOUND_POLICY_H
#define SLINK_GEN4_SOUND_POLICY_H

#include "sound.h"
#include "trade_producer.h" /* tp_ack only -- C3 reuses the shared ack, nothing else */

/* ---------------------------------------------------------------- what a visit concluded */
enum SlinkGen4SoundOutcome {
    SLINK_SOUND_FOREIGN = 0, /* not our opcode: nothing acked, nothing held, nothing played */
    SLINK_SOUND_IDLE,        /* our slot is empty                                        */
    SLINK_SOUND_REFUSED,     /* consumed, FAIL + a named reason, nothing played           */
    SLINK_SOUND_HELD,        /* held across visits; the request is still published         */
    SLINK_SOUND_PLAYED       /* handed to PlaySE and acked OK                             */
};

/* ---------------------------------------------------------------- the engine seam
 * Five calls, all of them read-only or one-shot, all bound by sound.c:
 *   fade            GF_SndGetFadeTimer() != 0              include/sound.h:38
 *   after_fade_delay GF_SndGetAfterFadeDelayTimer() != 0   INFERRED, §6 Q5 -- keep it cheap
 *   se_busy         the seq's OWN handle word is nonzero.  The handle is resolved at runtime
 *                   by the game's own GF_GetSndHandleByPlayerNo(GF_GetPlayerNoBySeq(seq)),
 *                   because PlaySE derives it from the sound ARCHIVE, not from a constant
 *                   (C3_SOUND_SPEC.md:164-205); busy is one word, zero meaning idle
 *                   (lib/asm/nnsys.s:23988-23999). This seam is per SEQ, not per handle:
 *                   the ROM side does the resolving.
 *   play_se         PlaySE(seq). void, like the real call. SLINK_ST_OK means HANDED TO
 *                   PlaySE, never "audible" (C3_SOUND_SPEC.md:258; sound_producer.h:1).
 * A NULL seam member reads as "that guard does not exist here", so a host test can bind
 * only the two calls its scenario is about.
 */
typedef struct {
    void *context;
    int (*fade)(void *);
    int (*after_fade_delay)(void *);
    int (*se_busy)(void *, uint16_t se);
    void (*play_se)(void *, uint16_t se);
} SlinkGen4SoundEngine;

/* The two refusal reasons the spec does not name (see the header comment). The ROM service
 * supplies them; the policy never falls back to a guess of its own. */
typedef struct {
    uint16_t not_ready;   /* a request arrived before InitSoundData latched */
    uint16_t hold_expired;/* the 240-visit bound consumed the request unplayed */
} SlinkGen4SoundReasons;

/* ---------------------------------------------------------------- the per-card sub-struct
 * One visit's worth of helpers. They take the state sub-struct beacon.h allocates, never a
 * file-scope object, and they are the ONLY writer of that sub-struct.
 */
static inline void slink_gen4_sound_layout(SlinkGen4StateSound *s)
{
    /* A zeroed block (fresh allocation, C2's zero-fill) means "this card has never run";
     * a mismatch means "written by another layout". Both are reset, never reinterpreted:
     * re-initialising is the only safe reading of bytes whose layout is not the one this
     * card knows. The reset preserves nothing, which is why the InitSoundData latch goes
     * through slink_gen4_sound_latch_ready() below -- it stamps the layout first, so a
     * latch that fired before the first service visit is not wiped by it.
     */
    if (s->layout != SLINK_GEN4_STATE_SOUND_LAYOUT) {
        s->layout = SLINK_GEN4_STATE_SOUND_LAYOUT;
        s->hold_visits = 0u;
        s->pending_code = 0u;
        s->in_flight = 0u;
        s->ready = 0u;
        s->blocked = 0u;
    }
}

/* The InitSoundData latch (pret src/sound.c:82-98, called once per boot from src/main.c:66;
 * on hge the call site is 0x02000D12 and the vehicle is an armips .org -- §6 Q7). Called
 * from sound.c's latch, never from the policy.
 */
static inline void slink_gen4_sound_latch_ready(SlinkGen4StateSound *s)
{
    slink_gen4_sound_layout(s);
    s->ready = 1u;
}

static inline void slink_gen4_sound_release(SlinkGen4StateSound *s)
{
    s->in_flight = 0u;
    s->hold_visits = 0u;
    s->pending_code = 0u;
}

/* ---------------------------------------------------------------- the code table
 * Returns 1 and writes the SE id for a wired code, 0 for the hole at index 2, -1 for a code
 * outside 1..4. The switch is the whole table: there is no const array and no placeholder
 * for index 2 (C3_SOUND_SPEC.md:76-84, F5).
 */
static inline int slink_gen4_sound_se(uint8_t code, uint16_t *out_se)
{
    switch (code) {
    case SLINK_GEN4_SOUND_CODE_SUCCESS:
        *out_se = (uint16_t)SLINK_GEN4_SE_SUCCESS;
        return 1;
    case SLINK_GEN4_SOUND_CODE_BOO:
        *out_se = (uint16_t)SLINK_GEN4_SE_BOO;
        return 1;
    case SLINK_GEN4_SOUND_CODE_NOTIFY:
        *out_se = (uint16_t)SLINK_GEN4_SE_NOTIFY;
        return 1;
    case SLINK_GEN4_SOUND_CODE_FAILURE: return 0; /* the hole: refused, never a guess */
    default:
        break;
    }
    return -1; /* 0, 5, 255 ... : consumed unplayed with BAD_ARGS */
}

/* ---------------------------------------------------------------- the hold predicates
 * "No new audio during a fade, and never over a busy handle" -- Gen 2's fade guard
 * (sfx.asm:43-45) and its native-channel guard (:46-47) with the predicate sources the spec
 * names for Gen 4 (C3_SOUND_SPEC.md:251-253).
 */
static inline int slink_gen4_sound_blocked(const SlinkGen4SoundEngine *e, uint16_t se)
{
    if (e->fade != NULL && e->fade(e->context)) {
        return 1;
    }
    if (e->after_fade_delay != NULL && e->after_fade_delay(e->context)) {
        return 1;
    }
    if (e->se_busy != NULL && e->se_busy(e->context, se)) {
        return 1;
    }
    /* A NULL play_se is not an engine that happens to be quiet: it is no engine at all, so
     * the request is held to the bound and consumed by the caller's expiry reason rather
     * than acked OK for a call that never happened. */
    if (e->play_se == NULL) {
        return 1;
    }
    return 0;
}

/* ---------------------------------------------------------------- one service visit
 * Pure with respect to the game: it reads the mailbox and the state block, writes the state
 * block and the mailbox's ack fields through tp_ack, and calls at most one engine function
 * (play_se). Returns what the visit concluded, for the ROM service and for tests.
 */
static inline int slink_gen4_sound_step(volatile SlinkMailboxV2 *m, SlinkGen4StateSound *s,
                                        const SlinkGen4SoundEngine *e,
                                        const SlinkGen4SoundReasons *r,
                                        uint32_t configured_epoch)
{
    uint16_t seq;
    uint16_t se = 0u;
    uint8_t code;
    int class_;

    if (m == NULL || s == NULL || e == NULL || r == NULL) {
        return SLINK_SOUND_FOREIGN; /* fail closed: a null argument is never a request */
    }

    slink_gen4_sound_layout(s);
    seq = m->seq;

    /* 1. the sound-ready latch, before the empty/invalid path (sfx.asm:34-36) */
    if (s->ready == 0u) {
        s->blocked = 1u;
        if (m->opcode == SLINK_GEN4_SOUND_OPCODE) {
            slink_gen4_sound_release(s);
            tp_ack(m, seq, 0, r->not_ready);
            return SLINK_SOUND_REFUSED;
        }
        return SLINK_SOUND_IDLE;
    }
    if (s->blocked != 0u) {
        s->blocked = 0u; /* released at the next visit after sound is ready */
    }

    /* 2. not our opcode: no ack, and a hold whose request is gone is abandoned */
    if (m->opcode != SLINK_GEN4_SOUND_OPCODE) {
        if (s->in_flight != 0u) {
            slink_gen4_sound_release(s);
        }
        return (m->opcode == 0) ? SLINK_SOUND_IDLE : SLINK_SOUND_FOREIGN;
    }

    /* 3. the epoch gate -- the mailbox survives a soft reset, so this is load-bearing */
    if (m->session_epoch == 0u) {
        slink_gen4_sound_release(s);
        tp_ack(m, seq, 0, SLINK_REASON_CLIENT_TOO_OLD);
        return SLINK_SOUND_REFUSED;
    }
    if (m->session_epoch != configured_epoch) {
        slink_gen4_sound_release(s);
        tp_ack(m, seq, 0, SLINK_REASON_IDENTITY);
        return SLINK_SOUND_REFUSED;
    }

    /* 4. the code table: the hole and the out-of-range band are both consumed unplayed */
    code = m->args[0];
    class_ = slink_gen4_sound_se(code, &se);
    if (class_ <= 0) {
        uint16_t reason = (class_ == 0) ? (uint16_t)SLINK_GEN4_REASON_SOUND_CODE_REFUSED
                                        : (uint16_t)SLINK_REASON_BAD_ARGS;
        slink_gen4_sound_release(s);
        tp_ack(m, seq, 0, reason);
        return SLINK_SOUND_REFUSED;
    }

    /* 5. one sound in flight. The visit that first sees the request counts as visit 1, so
     * a request is held across at most MAX_HOLD_VISITS service visits and consumed on the
     * last of them. The increment saturates (sfx.asm:77-83): a corrupted age can never wrap
     * into a fresh hold, it expires instead. */
    s->pending_code = code;
    if (s->in_flight == 0u) {
        s->in_flight = 1u;
        s->hold_visits = 1u;
    } else if (s->hold_visits < SLINK_GEN4_SOUND_MAX_HOLD_VISITS) {
        s->hold_visits++;
    }

    if (slink_gen4_sound_blocked(e, se)) {
        if (s->hold_visits >= SLINK_GEN4_SOUND_MAX_HOLD_VISITS) {
            uint16_t reason = r->hold_expired;
            slink_gen4_sound_release(s);
            tp_ack(m, seq, 0, reason);
            return SLINK_SOUND_REFUSED;
        }
        return SLINK_SOUND_HELD;
    }

    slink_gen4_sound_release(s);
    e->play_se(e->context, se);
    tp_ack(m, seq, 1, 0);
    return SLINK_SOUND_PLAYED;
}

#endif /* SLINK_GEN4_SOUND_POLICY_H */