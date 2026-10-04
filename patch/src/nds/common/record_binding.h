/* Record bindings: everything the shared producers must know about ONE game's
 * Pokemon record, kept out of the lifecycle state machines. A binding is plain
 * const data plus three tiny ops; it holds no addresses and does no crypto.
 *
 * Raw-staged-encrypted contract: the HOST stages the engine at-rest
 * (encrypted, shuffled) bytes and the native commit primitive copies them
 * verbatim, so the ROM side needs no encryption and no checksum recomputation.
 * Evidence (Gen 4 coordinator, HGSS only): pret
 * Party_SafeCopyMonToSlot_ResetAprijuiceModifiers (src/party.c:97) raw-copies the
 * full 0xEC party record, and the box primitive takes the first 0x88 bytes (a
 * self-contained prefix). NOT verified: that the actual TRADE commit (pret
 * src/trade.c) is a raw party-form copy for HGSS, and anything about BW / B2W2.
 * Anything that must look INSIDE the record (the OT id lives in the decoded body)
 * goes through the SlinkDecoder the adapter supplies from the game's own decode
 * routines; the shared layer never authors a cipher (the PK45 cipher is extracted
 * once, elsewhere). Decoder-based bindings FAIL CLOSED: no decoder, or no verify
 * callback, means the record is refused.
 */
#ifndef SLINK_NDS_RECORD_BINDING_H
#define SLINK_NDS_RECORD_BINDING_H
#include "abi.h"

enum SlinkBindingId {
    SLINK_BIND_NONE = 0, SLINK_BIND_GEN3_PK3 = 3, SLINK_BIND_GEN4_PK4 = 4,
    SLINK_BIND_GEN5_PK5 = 5
};
enum SlinkCharset {
    SLINK_CHARSET_NONE = 0,
    SLINK_CHARSET_GEN3 = 1,   /* 8-bit, 0xFF terminated */
    SLINK_CHARSET_GEN4 = 2,   /* 16-bit game table, 0xFFFF terminated */
    SLINK_CHARSET_GEN5 = 3    /* UTF-16LE, 0xFFFF terminated */
};
enum SlinkBindingFlags {
    SLINK_RB_RAW_ENCRYPTED = 1u << 0, /* host stages at-rest bytes; no ROM-side crypto/checksum */
    SLINK_RB_OTID_DECODED = 1u << 1,  /* OT id is in the decoded body; identity needs a decoder */
    /* A native commit primitive for this binding MUTATES its input (PK4 box path:
     * PCStorage_PlaceMonInFirstEmptySlotInAnyBox calls RestoreBoxMonPP on it).
     * The producer then hands the engine a scratch COPY, never the stage buffer. */
    SLINK_RB_COMMIT_MUTATES_INPUT = 1u << 2
};
/* Which arm a staged record is for; each arm has its own exact staging length. */
enum SlinkStageOp { SLINK_STAGE_OP_TRADE = 0, SLINK_STAGE_OP_BOX = 1 };

typedef struct { uint8_t width; uint8_t charset; uint16_t terminator; } SlinkTextSpec;
typedef struct { uint32_t pid, otid; } SlinkIdentity;

/* Engine-supplied view into the DECODED record (game decode routines, not ours).
 * read_u32 reads a little-endian word at a LOGICAL (decoded) offset. verify is
 * optional: the engine's own integrity check (checksum) of the staged bytes. */
typedef struct {
    void *context;
    int (*read_u32)(void *context, const uint8_t *rec, uint16_t len,
                    uint16_t logical_off, uint32_t *out);
    int (*verify)(void *context, const uint8_t *rec, uint16_t len);
} SlinkDecoder;

typedef struct {
    uint16_t id;                 /* SlinkBindingId */
    uint8_t generation;          /* 3, 4 or 5 */
    uint8_t flags;               /* SlinkBindingFlags */
    uint16_t stored_len;         /* box / PC form */
    uint16_t party_len;          /* party form; also the exact trade staging length */
    uint16_t max_len;            /* bound on ANY length this binding accepts (<= SLINK_MAX_RECORD) */
    uint16_t trade_stage_len;    /* exact stage_len for the TRADE arm; 0 means party_len */
    uint8_t extra_len_per_slot;  /* INFORMATIONAL (PartyExtra, pret include/constants/pokemon.h:132,
                                  * PK4: 5 bytes per slot). Never staged, never read by a producer:
                                  * adapters/hosts use it to shift the per-slot extras array when a
                                  * slot is removed or compacted. The party commit primitive resets
                                  * the slot's extra itself. 0 = none. */
    uint16_t otid_logical_off;   /* OTID_DECODED bindings: logical offset of the OT word */
    SlinkTextSpec text;          /* terminator width/value + charset for panel/name text */
    int (*validate)(const SlinkDecoder *d, const uint8_t *rec, uint16_t len);
    int (*identity)(const SlinkDecoder *d, const uint8_t *rec, uint16_t len, SlinkIdentity *out);
    int (*same_identity)(const SlinkIdentity *a, const SlinkIdentity *b);
} SlinkRecordBinding;

static inline uint32_t slink_rb_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static inline int slink_rb_same_identity(const SlinkIdentity *a, const SlinkIdentity *b)
{
    return a->pid == b->pid && a->otid == b->otid;
}

/* The exact stage_len the binding declares for an op (BOX stages the stored prefix). */
static inline uint16_t slink_binding_stage_len(const SlinkRecordBinding *b, unsigned op)
{
    if (op == SLINK_STAGE_OP_BOX) return b->stored_len;
    return b->trade_stage_len ? b->trade_stage_len : b->party_len;
}

/* Structural sanity of a binding itself; producers refuse to start without it. */
static inline int slink_binding_ok(const SlinkRecordBinding *b)
{
    return b && b->id && b->party_len && b->stored_len && b->stored_len <= b->party_len
        && b->party_len <= b->max_len && b->max_len <= SLINK_MAX_RECORD
        && b->trade_stage_len <= b->max_len
        && (b->text.width == 1 || b->text.width == 2)
        && !((b->flags & SLINK_RB_OTID_DECODED) && !(b->flags & SLINK_RB_RAW_ENCRYPTED))
        && b->validate && b->identity && b->same_identity;
}

/* Reference ops. PK3: plaintext header, PID +0 and OT +4. */
static inline int slink_pk3_validate(const SlinkDecoder *d, const uint8_t *rec, uint16_t len)
{
    (void)d; (void)rec;
    return len == 80u || len == 100u;  /* the exact arm length is checked by the producer first */
}
static inline int slink_pk3_identity(const SlinkDecoder *d, const uint8_t *rec, uint16_t len,
                                     SlinkIdentity *out)
{
    (void)d;
    if (len < 8u) return 0;
    out->pid = slink_rb_le32(rec);
    out->otid = slink_rb_le32(rec + 4);
    return 1;
}
/* PK4/PK5: PID is plaintext at +0; the OT word is read through the decoder at the
 * binding's logical offset. Without a decoder identity FAILS CLOSED. */
static inline int slink_pk45_identity_at(const SlinkDecoder *d, const uint8_t *rec, uint16_t len,
                                         uint16_t otid_off, SlinkIdentity *out)
{
    if (!d || !d->read_u32 || len < 8u) return 0;
    out->pid = slink_rb_le32(rec);
    return d->read_u32(d->context, rec, len, otid_off, &out->otid) ? 1 : 0;
}
/* Valid record forms are the stored prefix or the full party form. Integrity is the
 * engine's own verify callback; an absent decoder or absent verify FAILS CLOSED. */
static inline int slink_pk45_validate_len(const SlinkDecoder *d, const uint8_t *rec, uint16_t len,
                                          uint16_t stored, uint16_t party)
{
    if (len != stored && len != party) return 0;
    if (!d || !d->verify) return 0;
    return d->verify(d->context, rec, len) ? 1 : 0;
}
static inline int slink_pk4_validate(const SlinkDecoder *d, const uint8_t *rec, uint16_t len)
{
    return slink_pk45_validate_len(d, rec, len, 0x88u, 0xECu);
}
static inline int slink_pk4_identity(const SlinkDecoder *d, const uint8_t *rec, uint16_t len,
                                     SlinkIdentity *out)
{
    return slink_pk45_identity_at(d, rec, len, 0x0Cu, out);
}
static inline int slink_pk5_validate(const SlinkDecoder *d, const uint8_t *rec, uint16_t len)
{
    return slink_pk45_validate_len(d, rec, len, 0x88u, 0xDCu);
}
static inline int slink_pk5_identity(const SlinkDecoder *d, const uint8_t *rec, uint16_t len,
                                     SlinkIdentity *out)
{
    return slink_pk45_identity_at(d, rec, len, 0x0Cu, out);
}

static const SlinkRecordBinding slink_binding_gen3_pk3 = {
    SLINK_BIND_GEN3_PK3, 3, SLINK_RB_RAW_ENCRYPTED, 80, 100, SLINK_MAX_RECORD, 0, 0, 0,
    { 1, SLINK_CHARSET_GEN3, 0xFFu },
    slink_pk3_validate, slink_pk3_identity, slink_rb_same_identity
};
/* PK4: the 0x0C OT offset is the shared PK45 plain layout (matches the Lua and Python
 * ciphers); the real received_key hook must be implemented INDEPENDENTLY of the
 * staging decoder, or the identity chain is a tautology (UNVERIFIED until an adapter
 * exists). */
static const SlinkRecordBinding slink_binding_gen4_pk4 = {
    SLINK_BIND_GEN4_PK4, 4,
    SLINK_RB_RAW_ENCRYPTED | SLINK_RB_OTID_DECODED | SLINK_RB_COMMIT_MUTATES_INPUT,
    0x88, 0xEC, SLINK_MAX_RECORD, 0, 5, 0x0C,
    { 2, SLINK_CHARSET_GEN4, 0xFFFFu },
    slink_pk4_validate, slink_pk4_identity, slink_rb_same_identity
};
/* PK5 raw-staging, the 0x0C OT offset and the conservative MUTATES_INPUT flag are
 * carried over from PK4 by analogy and are UNVERIFIED against a Gen 5 ROM;
 * extra_len_per_slot 0 is likewise unconfirmed. */
static const SlinkRecordBinding slink_binding_gen5_pk5 = {
    SLINK_BIND_GEN5_PK5, 5,
    SLINK_RB_RAW_ENCRYPTED | SLINK_RB_OTID_DECODED | SLINK_RB_COMMIT_MUTATES_INPUT,
    0x88, 0xDC, SLINK_MAX_RECORD, 0, 0, 0x0C,
    { 2, SLINK_CHARSET_GEN5, 0xFFFFu },
    slink_pk5_validate, slink_pk5_identity, slink_rb_same_identity
};

/* Index of the first terminator unit within `bytes` bytes of a text row, or -1 if
 * the row is unterminated (or the spec is invalid). Units are width bytes, LE. */
static inline int slink_text_terminator_index(const volatile uint8_t *row, uint32_t bytes,
                                              const SlinkTextSpec *t)
{
    uint32_t i, unit;
    if (!t || (t->width != 1 && t->width != 2)) return -1;
    for (i = 0; i + t->width <= bytes; i += t->width) {
        unit = row[i];
        if (t->width == 2) unit |= (uint32_t)row[i + 1] << 8;
        if (unit == t->terminator) return (int)(i >> (t->width - 1u)); /* width is 1 or 2 (checked above): shift, no divide helper */
    }
    return -1;
}

/* Bounded text copy: capacity_bytes INCLUDES the terminator unit. Stops at the
 * source bound, the destination bound or the source terminator; always writes a
 * terminator. Same invariant as Gen 3 slink_copy_name_bounded, width-aware. */
static inline void slink_copy_text_bounded(volatile uint8_t *dst, uint32_t capacity_bytes,
                                           const volatile uint8_t *src, uint32_t source_bytes,
                                           const SlinkTextSpec *t)
{
    uint32_t w, cap, n, i;
    if (!t || (t->width != 1 && t->width != 2)) return;
    w = t->width;
    cap = capacity_bytes >> (w - 1u); /* w is 1 or 2 (checked above): shift, no u32 divide helper on mwcc */
    n = source_bytes >> (w - 1u);
    i = 0;
    if (!cap) return;
    while (i < n && i + 1 < cap) {
        uint32_t unit = src[i * w];
        if (w == 2) unit |= (uint32_t)src[i * w + 1] << 8;
        if (unit == t->terminator) break;
        dst[i * w] = src[i * w];
        if (w == 2) dst[i * w + 1] = src[i * w + 1];
        i++;
    }
    dst[i * w] = (uint8_t)(t->terminator & 0xFFu);
    if (w == 2) dst[i * w + 1] = (uint8_t)(t->terminator >> 8);
}

SLINK_STATIC_ASSERT(sizeof(SlinkIdentity) == 8, "identity size");
SLINK_STATIC_ASSERT(SLINK_MAX_RECORD >= 0xECu, "largest reference party record must fit the stage");
SLINK_STATIC_ASSERT(SLINK_INFO_LINE_WIDTH % 2u == 0u, "info rows hold whole 16-bit units");
#endif
