/* Gen 4 (HG/SS) companion beacon: arena placement, liveness, the title-private
 * block and the capability word. Card C2 -- docs/gen4/companion/C2_BEACON_SPEC.md.
 * Its DECISION BLOCK (that file's lines 1-19) is binding and overrides the body;
 * every citation below is to the body.
 *
 * NOT a capability/admission claim. The shared ABI is used UNMODIFIED
 * (C2_BEACON_SPEC.md:47-57): no field is added, moved or resized, so
 * patch/src/nds/common/abi.h stays byte-identical and every static assert at
 * abi.h:261-286 still holds.
 *
 * Types are <stdint.h> (abi.h already pulls it in) so this header compiles
 * unchanged under a host C compiler for the MODEL tests. Only beacon.c uses the
 * game's u32/u8 vocabulary.
 *
 * Build include paths: -I patch/src/nds/common -I patch/src/nds/gen4.
 */
#ifndef SLINK_GEN4_BEACON_H
#define SLINK_GEN4_BEACON_H

#include "abi.h"
/* The per-card state sub-structs below hold the SHARED producers by value, which is what
 * sizes them: the state block is where a producer lives, so a second copy would be a
 * second, stale transaction. Both are header-only and host-compilable, and both are
 * already the ROM's own translation units (C4 wraps slink_panel_service, C5 wraps
 * slink_trade_service), so this adds no new dependency to the build. */
#include "panel_producer.h"
#include "trade_producer.h"

/* ---------------------------------------------------------------- the span accessor (ONE)
 * Every ABI region is "arena base + an abi.h offset" (C2_BEACON_SPEC.md:89-100), so C3,
 * C4 and C5 all need the base -- and all of them need the census check that comes with it.
 * It is exported once here instead of re-derived three times: no card may re-implement
 * Slink_NDS_SpanBase(), and no card may name a span address at all.
 *
 * Slink_NDS_SpanBase() is the RULE and is host-testable with a fake arena value.
 * Slink_NDS_ArenaBase() is beacon.c's binding of it to the linker symbol the census
 * anchors on. It returns 0 to mean REFUSE, which is the only fail signal a caller needs:
 * nothing is stamped, nothing is written, and the host reads no beacon -- the correct
 * reading of "not live".
 *
 * The absolute span base is absent from the source on purpose: the C1 census's W2 row
 * FAILs a build whose source carries a 7-8 hex-digit literal inside the span
 * (tools/gen4_mailbox_census.py:83,188-197,217), and these headers are compiled into the
 * tree that census scans. The census value and the arena->span delta live in beacon.c for
 * the same reason; the numbers themselves are in README.md, which the census does not scan
 * (SCAN_EXT, gen4_mailbox_census.py:85).
 */
static inline uint32_t Slink_NDS_SpanBase(uint32_t arena_lo, uint32_t census_arena_lo,
                                          uint32_t delta)
{
    if (arena_lo != census_arena_lo) {
        return 0u; /* the arena moved: there is no span, so there is no base to hand out */
    }
    return arena_lo + delta;
}

uint32_t Slink_NDS_ArenaBase(void);

/* ---------------------------------------------------------------- title-private block
 * D-C2-1 (ABI owner, Gen 5, 2026-10-02; C2_BEACON_SPEC.md:6-12) RULES: Gen 4 may use
 * ONLY the first 64 bytes of the ABI's reserved region as title-private, ROM-written /
 * host-read PUBLISHED state, on these terms:
 *   - shared code never touches it;
 *   - the title versions it itself (own magic/version/size in its first bytes);
 *   - it is NOT covered by the witness revision protocol, so publish-last and
 *     coherent-snapshot rules are the title's own, and the host treats the block as
 *     untrusted-until-valid;
 *   - it never carries rules or write permission;
 *   - everything past 64 bytes stays free.
 * abi.h carries no SLINK_TITLE_OFFSET/SLINK_TITLE_SIZE yet (the ruling asks the ABI
 * owner to add them; cite the ruling until then -- C2_BEACON_SPEC.md:12). The block
 * is therefore derived from the ABI's own SLINK_RESERVED_OFFSET / SLINK_ARENA_SIZE,
 * so a change to either shared constant cannot silently move it.
 */
#define SLINK_GEN4_TITLE_OFFSET (SLINK_RESERVED_OFFSET)
#define SLINK_GEN4_TITLE_SIZE 0x40u

#define SLINK_GEN4_TITLE_MAGIC 0x34474C53u /* "SLG4" little-endian */
#define SLINK_GEN4_TITLE_VERSION 1u

/* Layout. The versioned header comes first (the ruling requires it), then the
 * published payload, then zero headroom. Every field is re-stamped on every service
 * visit, so a host write into one is transient and always observable -- the Gen 2
 * "header repair" rule (C2_BEACON_SPEC.md:242-244), falsifier 3 (:528). The host
 * therefore validates magic/version/size before believing any payload byte. */
typedef struct {
    uint32_t magic;         /* +0x00 title magic; 0 elsewhere                    */
    uint16_t version;       /* +0x04 layout version                             */
    uint16_t size;          /* +0x06 sizeof(SlinkGen4Title)                     */
    uint32_t cookie;        /* +0x08 published per-boot cookie (ROM writes)     */
    uint32_t identity;      /* +0x0C published PlayerProfile.id                 */
    uint32_t delta;         /* +0x10 published engine-clock delta               */
    uint32_t generation;    /* +0x14 published session epoch (mirror of 0x4C)   */
    uint32_t registrations; /* +0x18 published Slink_NDS_Register() count       */
    uint8_t reserved[36];   /* +0x1C .. +0x40 stays zero (C3-C5 headroom)       */
} SlinkGen4Title;

/* Field offsets, for the host reader and for the publisher's own assert. */
#define SLINK_GEN4_TITLE_COOKIE_FIELD 8u
#define SLINK_GEN4_TITLE_IDENTITY_FIELD 12u
#define SLINK_GEN4_TITLE_DELTA_FIELD 16u
#define SLINK_GEN4_TITLE_GENERATION_FIELD 20u
#define SLINK_GEN4_TITLE_REGISTRATIONS_FIELD 24u

/* C89-safe compile-time size check (the ROM compiler is not required to be C11). */
typedef char slink_gen4_title_size_check[
    (sizeof(SlinkGen4Title) == SLINK_GEN4_TITLE_SIZE) ? 1 : -1];

/* ---------------------------------------------------------------- capabilities
 * capabilities is ROM-owned (FEATURE_BAR.md:258; C2_BEACON_SPEC.md:429-431). Bits
 * 0..6 are the shared vocabulary (abi.h:88-96); bits 16..31 are title-private (ABI
 * owner, 2026-10-02; C3_SOUND_SPEC.md:17-19); bits 7..15 are reserved for future
 * shared caps and a title never sets them.
 *
 * The advertised set at C2 is ZERO (C2_BEACON_SPEC.md:432-435): no card may set a
 * bit ahead of its own. The shared enum has no beacon/liveness member, so the host
 * proves C2 from signature + abi_version alone and must NOT gate liveness on a
 * capability bit (C2_BEACON_SPEC.md:436-442).
 */
#define SLINK_GEN4_CAP_MASK_TITLE 0xFFFF0000u
#define SLINK_GEN4_CAPABILITIES 0u

/* ---------------------------------------------------------------- session state
 * Every mutable byte of this module lives in the service SysTask's own heap data
 * block, allocated inside Slink_NDS_Register() in NitroMain and destroyed by
 * OS_ResetSystem (C2_BEACON_SPEC.md:5, :272-301). NOT in DTCM -- that arena is the
 * launcher stack (lib/NitroSDK/src/os/os_thread.c:24-26) -- and NOT in the title
 * window: the block is ROM-private by construction, so the host can never see it and
 * it needs no D-C2-1 carve-out (C2_BEACON_SPEC.md:298-299).
 *
 * Consequently there is NO file-scope object anywhere in this directory: a static
 * .bss symbol would move 0x021E5900 and with it every overlay address and every pinned
 * hook site (C2_BEACON_SPEC.md:303-308; FEATURE_BAR.md:140-145).
 */
/* ---------------------------------------------------------------- per-card state
 * FIXED, versioned, and OWNED BY EXACTLY ONE CARD each. Three cards appending loose
 * fields to one struct is a serialization hazard: the allocation size changes silently
 * with every card, no offset is pinned, and two cards can end up writing the same word.
 * So each card gets a named sub-struct with its own layout word:
 *
 *   sound  C3  patch/src/nds/gen4/sound.h + sound_policy.h
 *   panel  C4  patch/src/nds/gen4/panel.h
 *   trade  C5  patch/src/nds/gen4/trade.h + trade_policy.h
 *
 * The layout word is stamped by the OWNING card on first use and never by C2: a zeroed
 * sub-struct means "this card has never run", and a mismatch means "these bytes are not
 * the layout this card knows". Both are fail-closed resets, never a reinterpretation.
 * C2's only obligation is to hand over ZEROED bytes, which it does at allocation --
 * OS_AllocFromArenaLo returns arena memory, not cleared memory, so Slink_NDS_Register()
 * zeroes the whole block before the first latch.
 *
 * No card may declare a second producer storage: panel and trade embed the SHARED
 * producers by value (panel_producer.h, trade_producer.h), which is what sizes them.
 */
#define SLINK_GEN4_STATE_SOUND_LAYOUT 1u
#define SLINK_GEN4_STATE_PANEL_LAYOUT 1u
#define SLINK_GEN4_STATE_TRADE_LAYOUT 1u

/* C3. Sized from C3_SOUND_SPEC.md:527-532's ROM-private table: the pending code, the
 * hold-at visit counter, the hold-blocked latch and the sound-ready bit. The latch and the
 * ready bit are separate because the latch is discarded-and-remembered while readiness is
 * what the policy gates on (sound_policy.h). */
typedef struct {
    uint32_t layout;       /* SLINK_GEN4_STATE_SOUND_LAYOUT, stamped by C3              */
    uint32_t hold_visits;  /* saturating service-visit hold counter (sfx.asm:77-83)     */
    uint8_t pending_code;  /* the semantic code held for playback                        */
    uint8_t in_flight;     /* one sound request held across visits                       */
    uint8_t ready;         /* InitSoundData has run: the sound system exists             */
    uint8_t blocked;       /* a request was refused pre-InitSoundData                   */
} SlinkGen4StateSound;

/* C4. The shared panel producer, by value: the snapshot it draws from and its active
 * flag (panel_producer.h). */
typedef struct {
    uint32_t layout; /* SLINK_GEN4_STATE_PANEL_LAYOUT, stamped by C4 */
    SlinkPanelProducer producer;
} SlinkGen4StatePanel;

/* C5. The shared trade producer, by value: phase, sequences, both identities and the two
 * native-binding buffers (trade_producer.h:50-60). */
typedef struct {
    uint32_t layout; /* SLINK_GEN4_STATE_TRADE_LAYOUT, stamped by C5 */
    SlinkTradeProducer producer;
} SlinkGen4StateTrade;

typedef struct {
    uint32_t magic;         /* SLINK_GEN4_STATE_MAGIC: this block is ours and live */
    uint32_t generation;    /* session epoch: registration + every identity change */
    uint32_t cookie;        /* private cookie, re-minted on every generation change */
    uint32_t identity;      /* last accepted save identity                        */
    uint32_t clock_sample;  /* last gSystem.vblankCounter sample                 */
    uint32_t delta;         /* accumulated engine-clock delta                    */
    uint32_t registrations; /* Slink_NDS_Register() calls, seeded across boots    */
    uint32_t prev_cookie;   /* previous session's published cookie (mix input)   */
    /* Per-card state, one fixed versioned sub-struct each, written only by its owner.
     * The decision block (C2_BEACON_SPEC.md:5) puts all of it in this block -- never in
 * the title window, never in the ABI, never in DTCM. */
    SlinkGen4StateSound sound;
    SlinkGen4StatePanel panel;
    SlinkGen4StateTrade trade;
} SlinkGen4State;

/* C89-safe compile-time checks (the ROM compiler is not required to be C11).
   - the sound block is 12 bytes, so a stray field cannot be added without this firing;
   - every sub-struct starts word-aligned: the producers contain word loads and _Alignas
     members, and a byte-aligned base would make that a build error. */
typedef char slink_gen4_state_sound_size_check[(sizeof(SlinkGen4StateSound) == 12u) ? 1 : -1];
typedef char slink_gen4_state_substructs_aligned_check[
    ((offsetof(SlinkGen4State, sound) % 4u) == 0u && (offsetof(SlinkGen4State, panel) % 4u) == 0u
     && (offsetof(SlinkGen4State, trade) % 4u) == 0u) ? 1 : -1];
typedef char slink_gen4_state_block_aligned_check[((sizeof(SlinkGen4State) % 4u) == 0u) ? 1 : -1];

#define SLINK_GEN4_STATE_MAGIC 0x4C4B5347u /* "GSKL" little-endian */

/* ---------------------------------------------------------------- entry point
 * Called once per boot from NitroMain, after InitSystemForTheGame() (which creates
 * gSystem.mainTaskQueue -- pret src/system.c:123-126) and before the first
 * RegisterMainOverlay at pret src/main.c:77 (C2_BEACON_SPEC.md:15-19). Latched per
 * boot: a second call finds this module's own service task on gSystem.mainTaskQueue
 * and is a no-op. The queue is rebuilt by every NitroMain, so the latch cannot
 * outlive a reset; the published title block (ITCM arena, survives a soft reset) is
 * deliberately NOT consulted for it.
 */
void Slink_NDS_Register(void);

#endif /* SLINK_GEN4_BEACON_H */