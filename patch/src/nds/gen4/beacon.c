/* Gen 4 (HG/SS) companion beacon -- card C2. Placement, liveness, capability word,
 * reset latch and the producer fan-out. Spec: docs/gen4/companion/C2_BEACON_SPEC.md,
 * whose DECISION BLOCK (its lines 1-19) is binding and overrides the body.
 *
 * Shape:
 *   Slink_NDS_Register()  once per boot, from NitroMain -- the ONLY integration point
 *   Slink_NDS_Service()   the per-visit body, run as a main-queue SysTask
 *   Slink_NDS_Dispatch()  every producer, every visit (dispatch.c)
 *
 * There is NO file-scope object in this file. Every mutable byte lives in the service
 * SysTask's heap data block (beacon.h / C2_BEACON_SPEC.md:5, :272-301): no static
 * .bss (that would move 0x021E5900 and every pinned overlay address), no DTCM (that
 * arena is the launcher stack).
 *
 * Build include paths: -I patch/src/nds/common -I patch/src/nds/gen4.
 */

#include "global.h"
#include "sys_task_api.h"
#include "system.h"
#include "save.h"
#include "player_data.h"

#include <nitro/os/arena.h>
#include <nitro/os/tick.h>

#include "beacon.h"
#include "dispatch.h"

/* ---------------------------------------------------------------------------
 * Arena placement.
 *
 * The mailbox is the 4 KiB ITCM-arena-tail span accepted by the C1 census
 * (C2_BEACON_SPEC.md:63-88; tools/gen4_mailbox_census.py:44,120-124). The span base
 * is C1's ACCEPTED ADDRESS per artifact and is NOT written here as a literal: the
 * census's W2 row FAILs any build whose source carries a 7-8 hex-digit literal inside
 * the span (gen4_mailbox_census.py:83,188-197,217), and this file is compiled into
 * the tree the census scans. The base is therefore derived from the linker symbol the
 * census anchors on (W1 requires it in nm, gen4_mailbox_census.py:136-155) plus a
 * fixed delta; the absolute numbers live in this directory's README.md, which the
 * census does not scan (SCAN_EXT, gen4_mailbox_census.py:85).
 *
 * Same idiom as the SDK's own arena code, which reads that symbol by casting it
 * (lib/NitroSDK/src/os/os_arena.c:12-13).
 */
extern void SDK_SECTION_ARENA_ITCM_START(void);

/* Linker value at the pinned pret build (C1 W1: it equals the end of the .itcm
 * autoload, gen4_mailbox_census.py:152-154). */
#define SLINK_GEN4_ARENA_START 0x01FF8620u
/* arena start -> accepted span start. */
#define SLINK_GEN4_ARENA_DELTA 0x65E0u

/* C89-safe compile-time checks (the ROM compiler is not required to be C11). */
typedef char slink_gen4_span_fits_itcm[
    (SLINK_GEN4_ARENA_DELTA + SLINK_ARENA_SIZE <= 0x8000u) ? 1 : -1];
/* No card may set a bit outside the shared vocabulary (0..6) and the title-private
 * range (16..31); bits 7..15 are reserved for future shared caps (C2_BEACON_SPEC.md:6-12). */
typedef char slink_gen4_caps_in_range[
    ((SLINK_GEN4_CAPABILITIES & ~(0x7Fu | SLINK_GEN4_CAP_MASK_TITLE)) == 0u) ? 1 : -1];

/* Lower runs first: SysTaskQueue_InsertTaskCore walks from the head and inserts ahead
 * of the first strictly-higher priority (pret src/sys_task.c:124-133). Game tasks
 * use 0 and 1000+ (src/battle/battle_hp_bar.c:949, :1685). 0 puts the beacon at the
 * head of the frame. */
#define SLINK_GEN4_TASK_PRIORITY 0u

/* ---------------------------------------------------------------------------
 * The cookie mix. §8 Q7 leaves the mixer open and calls OS_GetTick "available";
 * the decision is cheap to revisit. A cookie's job is to CHANGE across a reset, not to
 * be unpredictable: the host only ever reads it, and every field is re-stamped each
 * visit. Generation plus the previous session's published cookie are therefore the
 * load-bearing inputs; OS_GetTick is nearly zero this early in NitroMain and only
 * decorrelates two registrations in the same generation. Never zero: zero means
 * "no cookie published".
 */
#define SLINK_GEN4_COOKIE_SALT 0x5E1C0DEu

static u32 Slink_NDS_ArenaLo(void)
{
    return (u32)SDK_SECTION_ARENA_ITCM_START;
}

static u32 Slink_NDS_Base(void)
{
    return Slink_NDS_ArenaLo() + SLINK_GEN4_ARENA_DELTA;
}

static volatile SlinkMailboxV2 *Slink_NDS_Mailbox(void)
{
    return (volatile SlinkMailboxV2 *)(void *)Slink_NDS_Base();
}

static volatile SlinkGen4Title *Slink_NDS_Title(void)
{
    return (volatile SlinkGen4Title *)(void *)(Slink_NDS_Base() + SLINK_GEN4_TITLE_OFFSET);
}

static volatile SlinkTradeWitnessV2 *Slink_NDS_Witness(void)
{
    return (volatile SlinkTradeWitnessV2 *)(void *)(Slink_NDS_Base() + SLINK_WITNESS_OFFSET);
}

static void Slink_NDS_Zero(volatile u8 *p, u32 n)
{
    while (n-- != 0) {
        *p++ = 0;
    }
}

static u32 Slink_NDS_Mix(u32 generation, u32 prev_cookie)
{
    OSTick tick = OS_GetTick();
    u32 v = (u32)tick;
    v ^= (u32)((u32)(tick >> 32) * 0x9E3779B9u);
    v ^= generation * 0x85EBCA6Bu;
    v ^= prev_cookie * 0xC2B2AE35u;
    v ^= SLINK_GEN4_COOKIE_SALT;
    if (v == 0) {
        v = 1u;
    }
    return v;
}

/* ---------------------------------------------------------------------------
 * The session identity, one u32 per tick: the player profile id, the HG/SS analogue
 * of the OT id the server already locks on (C2_BEACON_SPEC.md:338-365).
 *
 * SaveData_Get() asserts if the save has not been created yet (pret src/save.c:124),
 * so the ORDER matters: registration happens at main.c:51 but SaveData_New() runs at
 * main.c:64, and this is only reached from the queue, which first drains at
 * main.c:111 -- strictly after :64. Until a save is loaded the profile lives in the
 * cleared dynamic region (src/save.c:75, :116), so the id reads 0 and that zero is
 * itself a legitimate "no profile yet" value.
 */
static u32 Slink_NDS_SaveIdentity(void)
{
    SaveData *sd = SaveData_Get();                       /* include/save.h:93 */
    PlayerProfile *profile = Save_PlayerData_GetProfile(sd); /* include/player_data.h:36 */
    return (u32)profile->id;                             /* include/player_data.h:14 */
}

/* ---------------------------------------------------------------------------
 * The reset latch (C2_BEACON_SPEC.md:367-380). One uninterrupted block: the epoch
 * moves, the cookie is re-minted, every host-owned request field is cleared so a new
 * session never honours the previous session's intent, and the witness is zeroed
 * because only a producer may fill it (at C2 nothing does).
 *
 * session_epoch is host-owned (abi.h:156) yet is cleared here: abi.h:156 says "zero
 * unarmed, reset clears", and C2_BEACON_SPEC.md:170 lists it as a host-owned request
 * field the registration clears. §4.4's enumeration omits it; leaving it would let a
 * stale epoch survive a soft reset and read as armed.
 *
 * status/ack_seq are NOT stamped on a normal tick. They are set here and by whichever
 * producer acks (tp_ack, trade_producer.h:93-104); a per-tick stamp would erase a
 * producer's OK/FAIL, and C3 holds status at BUSY across visits
 * (C2_BEACON_SPEC.md:249-252; C3_SOUND_SPEC.md:146-148).
 */
static void Slink_NDS_Latch(SlinkGen4State *st, u32 generation, u32 registrations, u32 identity, u32 now)
{
    volatile SlinkMailboxV2 *m = Slink_NDS_Mailbox();

    st->generation = generation;
    st->registrations = registrations;
    st->cookie = Slink_NDS_Mix(generation, st->prev_cookie);
    st->identity = identity;
    st->delta = 0;
    st->clock_sample = now;

    m->opcode = 0;
    m->seq = 0;
    m->session_epoch = 0;
    m->ack_seq = 0;
    m->status = SLINK_ST_BUSY;
    Slink_NDS_Zero(m->args, (u32)sizeof m->args);
    Slink_NDS_Zero(m->result, (u32)sizeof m->result);
    m->producer_phase = SLINK_PHASE_IDLE;
    Slink_NDS_Zero((volatile u8 *)Slink_NDS_Witness(), (u32)sizeof(SlinkTradeWitnessV2));
}

/* Publish last, so a host that samples mid-visit sees a valid header over a stale
 * payload rather than a valid header over a torn one. The block is outside the witness
 * revision protocol, so this ordering is the title's own (D-C2-1). */
static void Slink_NDS_Publish(SlinkGen4State *st)
{
    volatile SlinkGen4Title *t = Slink_NDS_Title();

    t->cookie = st->cookie;
    t->identity = st->identity;
    t->delta = st->delta;
    t->generation = st->generation;
    t->registrations = st->registrations;
    t->size = (uint16_t)sizeof(SlinkGen4Title);
    t->version = (uint16_t)SLINK_GEN4_TITLE_VERSION;
    t->magic = SLINK_GEN4_TITLE_MAGIC;
}

/* ---------------------------------------------------------------------------
 * The per-visit body.
 *
 * gSystem.vblankCounter, never gSystem.frameCounter: frameCounter is zeroed every
 * outer loop iteration (pret src/main.c:124) and is forbidden as a liveness clock
 * (C2_BEACON_SPEC.md:4, :382-391). The delta is therefore a magnitude signal only --
 * "advanced at all within N polls", never "advanced by exactly N"
 * (C2_BEACON_SPEC.md:394-407).
 *
 * The two state steps (clock, identity) run BEFORE the publish block so a generation
 * change is visible on the same visit, as §4.4 requires ("in one uninterrupted block:
 * generation += 1, republish cookie and identity"). Every mailbox field is re-stamped
 * on every visit, so running them first changes nothing else.
 *
 * The signature is pret's, not the spec's: SysTaskFunc is void (*)(SysTask *, void *)
 * (include/sys_task.h:8). The draft's one-argument form would be a cast, not a match.
 */
static void Slink_NDS_Service(SysTask *task, void *data)
{
    SlinkGen4State *st = (SlinkGen4State *)data;
    volatile SlinkMailboxV2 *m = Slink_NDS_Mailbox();
    u32 now;
    u32 identity;

    (void)task;

    if (st == NULL || st->magic != SLINK_GEN4_STATE_MAGIC) {
        return; /* not our block, or freed under us: stamp nothing */
    }

    now = gSystem.vblankCounter;
    st->delta += (u32)(now - st->clock_sample);
    st->clock_sample = now;

    identity = Slink_NDS_SaveIdentity();
    if (identity != st->identity) {
        /* D-C2-4: the epoch is a SESSION epoch, not a boot counter -- New Game never
         * re-enters NitroMain, so a boot-only counter cannot go stale-detect it
         * (C2_BEACON_SPEC.md:326-336). The Oak chain moves the id more than once, so
         * this fires in a burst; the host's K-stable-polls rule is sized for it. */
        Slink_NDS_Latch(st, st->generation + 1u, st->registrations, identity, now);
    }

    /* Header repair (C2_BEACON_SPEC.md:242-244): re-stamp the ROM-owned header only.
     * It never clears host requests, panel state, holds or lease bytes. */
    m->signature = SLINK_SIGNATURE;
    m->abi_version = (uint16_t)SLINK_ABI_VERSION;
    m->capabilities = SLINK_GEN4_CAPABILITIES;
    m->reserved = st->generation; /* the session epoch, zero bytes added to the ABI */
#if !defined(SLINK_GEN4_TRADE)
    /* At C2 there is no transaction, so IDLE is the truth and is re-stamped every
     * visit. When the trade module lands it owns this field and brackets its own state
     * machine with it on every call (trade_producer.h:310-317), which restamps it
     * whatever the phase -- so this arm is dropped, never fought. */
    m->producer_phase = SLINK_PHASE_IDLE;
#endif
    /* session_epoch is host-owned: read for liveness, never written outside the latch. */

    Slink_NDS_Publish(st);

    /* Every producer, every visit, no opcode pre-route (C2_BEACON_SPEC.md:6-12;
     * C3_SOUND_SPEC.md:150-162; C5_TRADE_SPEC.md:22-30). */
    Slink_NDS_Dispatch(st, m);

}

/* ---------------------------------------------------------------------------
 * Per-boot registration latch: walk the main queue for our own task. The queue and its
 * list are rebuilt every boot, so this cannot be stale across a reset (see the
 * Registration note below). SysTask/SysTaskQueue: pret include/sys_task.h:10-33.
 */
static BOOL Slink_NDS_AlreadyQueued(void)
{
    SysTaskQueue *q = gSystem.mainTaskQueue;
    SysTask *it;

    if (q == NULL) {
        return FALSE;
    }
    for (it = q->headSentinel.next; it != &q->headSentinel; it = it->next) {
        if (it->func == Slink_NDS_Service) {
            return TRUE;
        }
    }
    return FALSE;
}

/* ---------------------------------------------------------------------------
 * Registration. The ONE integration point in the pinned pret tree:
 *
 *   src/main.c, immediately after InitSystemForTheGame() (src/main.c:51) and before
 *   the FIRST RegisterMainOverlay (src/main.c:77).
 *
 * InitSystemForTheGame creates gSystem.mainTaskQueue (src/system.c:123-126), so the
 * task exists before any overlay can run, and the drain at src/main.c:111 is outside
 * every app, which is what makes the tick app-independent (C2_BEACON_SPEC.md:529).
 * A soft reset re-runs NitroMain (DoSoftReset -> OS_ResetSystem, src/main.c:101-105,
 * :180-185), so the block is rebuilt and the epoch moves.
 *
 * Latched per boot, with no static storage and no state that outlives a reset: the
 * latch is "is Slink_NDS_Service already on gSystem.mainTaskQueue". That queue is
 * rebuilt by InitSystemForTheGame on every boot (src/system.c:123, via
 * SysTaskQueue_PlacementNew -> SysTaskQueue_Init, src/sys_task.c:56-80, which resets
 * the list to the empty sentinel), so a task from a previous boot is unreachable.
 *
 * The published title block must NOT decide this. It lives in the ITCM arena, which a
 * soft reset does not clear (the same fact the generation seed below relies on), so
 * after a soft reset it still reads "valid, nonzero delta" from the previous boot; a
 * latch on it would return early and never create the service task: a dead beacon
 * after every soft reset.
 */
void Slink_NDS_Register(void)
{
    SlinkGen4State *st;
    volatile SlinkGen4Title *t;
    SysTask *task;
    u32 generation;
    u32 registrations;
    u32 prev_cookie;
    u32 identity;

    if (Slink_NDS_ArenaLo() != SLINK_GEN4_ARENA_START) {
        /* Fail closed and say nothing: the arena moved, so the accepted span is not
         * where the host reads it. Leaving the arena untouched keeps every pinned
         * address intact and the host reads no beacon, which is the correct reading
         * of "not live". The C1 census W1 row is what must catch this first. */
        return;
    }

    if (Slink_NDS_AlreadyQueued()) {
        return; /* this boot is already being serviced */
    }

    t = Slink_NDS_Title();

    /* OS_ARENA_MAIN, never OS_ARENA_ITCM: the census W2 row FAILs any
     * OS_AllocFromArena*(..., OS_ARENA_ITCM) (gen4_mailbox_census.py:79,209-210) and
     * the MAIN arena is where every other boot-time allocation comes from
     * (src/heap.c:49-56; src/system.c:123-126). */
    st = (SlinkGen4State *)OS_AllocFromArenaLo(OS_ARENA_MAIN, (u32)sizeof(SlinkGen4State), 4);
    if (st == NULL) {
        return;
    }

    /* The arena survives a soft reset (only a hard reset zeroes ITCM, census W3:
     * gen4_mailbox_census.py:380-381), which is exactly why the cookie has to be
     * re-minted from a heap block. The published block is what carries the epoch
     * across that reset; if its header does not validate, the arena is not ours
     * (fresh hard boot, or a foreign writer) and the epoch restarts at one. */
    if (t->magic == SLINK_GEN4_TITLE_MAGIC && t->version == (uint16_t)SLINK_GEN4_TITLE_VERSION
        && t->size == (uint16_t)sizeof(SlinkGen4Title)) {
        generation = t->generation + 1u;
        registrations = t->registrations + 1u;
        prev_cookie = t->cookie;
    } else {
        generation = 1u;
        registrations = 1u;
        prev_cookie = 0u;
    }

    st->magic = 0;
    st->prev_cookie = prev_cookie;
    /* The save is not built yet at main.c:51, so the identity is latched on the first
     * visit instead; seeding it from the published value keeps a soft reset from
     * manufacturing a second epoch change. */
    identity = (prev_cookie != 0u) ? t->identity : 0u;
    Slink_NDS_Latch(st, generation, registrations, identity, gSystem.vblankCounter);
    st->magic = SLINK_GEN4_STATE_MAGIC;

    task = SysTask_CreateOnMainQueue(Slink_NDS_Service, st, SLINK_GEN4_TASK_PRIORITY);
    if (task == NULL) {
        /* The main queue is full (SysTaskQueue limit 160, src/system.c:123). Stamping
         * nothing is better than a beacon with no producer behind it. */
        st->magic = 0;
        return;
    }

    /* Publish before the first visit so the host has a valid block to validate from
     * its very first poll. */
    Slink_NDS_Publish(st);
}