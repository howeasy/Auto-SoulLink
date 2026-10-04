/* Gen 4 (HG/SS) companion C3: native sound codes -- the INTERFACE.
 * Card C3 -- docs/gen4/companion/C3_SOUND_SPEC.md, whose DECISION BLOCK (its lines
 * 1-24) is binding and overrides the body; every citation below is to the body.
 *
 * This header is DATA ONLY: the code table, the named refusal reason, the title-private
 * capability bit, the hold bound, and the ONE function the dispatcher calls. The decision
 * logic lives in sound_policy.h behind an engine seam, so the whole of C3's behaviour is
 * provable on a host C compiler with no game call and no ROM
 * (tests/unit/test_gen4_sound_codes.py).
 *
 * The ROM body (sound.c) is a thin binding of five game calls to the seam: nothing in this
 * header is a placeholder, and nothing here may be re-derived by a per-card module -- the
 * code table has exactly one definition and it is here.
 *
 * C3 does NOT use the shared sound_producer.h (C3_SOUND_SPEC.md:131-143): it takes a native
 * song id and a song_count bound, and it acks on the same visit so it cannot hold. It reuses
 * tp_ack only, from trade_producer.h.
 *
 * Types are <stdint.h> (via abi.h) so this header compiles unchanged under a host C compiler.
 * Build include paths: -I patch/src/nds/common -I patch/src/nds/gen4.
 */
#ifndef SLINK_GEN4_SOUND_H
#define SLINK_GEN4_SOUND_H

#include "beacon.h"

/* ---------------------------------------------------------------- the opcode C3 owns
 * SLINK_OP_PLAY_SE (19) and nothing else. SLINK_OP_PLAY_FANFARE (9) exists in the ABI and
 * the shared producer accepts it, but C3 leaves that arm unwired (C3_SOUND_SPEC.md:90), so
 * opcode 9 is a FOREIGN opcode here: no ack, no consumption, no hold. The spec never says
 * what a posted fanfare should do on Gen 4 -- §1 OUT only records that the arm is unwired --
 * so this card does not decide it and leaves such a request untouched for whoever owns it.
 * The dispatch seam is the same shape as C4/C5's (dispatch.h): the service and the
 * (state, mailbox) pair.
 */
#define SLINK_GEN4_SOUND_OPCODE SLINK_OP_PLAY_SE

/* ---------------------------------------------------------------- the semantic codes
 * The shared four-integer set, unchanged from GB (lua/gb_panel.lua:23,
 * patch/gb/slink_abi.inc:14). The TRANSPORT differs (NDS has one u16 opcode slot,
 * abi.h:150, where GB has a dedicated request byte), which is what drives the hold.
 */
#define SLINK_GEN4_SOUND_CODE_SUCCESS 1u
#define SLINK_GEN4_SOUND_CODE_FAILURE 2u /* UNWIRED -- see the hole below            */
#define SLINK_GEN4_SOUND_CODE_BOO 3u
#define SLINK_GEN4_SOUND_CODE_NOTIFY 4u
#define SLINK_GEN4_SOUND_CODE_MAX 4u /* an out-of-range code is consumed unplayed  */

/* ---------------------------------------------------------------- THE HOLE at index 2
 * There is deliberately NO SLINK_GEN4_SE_FAILURE macro. Code 2 (FAILURE) has no SE id and
 * does not get one until the owner rules it (DECISIONS_2026-10-02_companion.md:16;
 * FEATURE_BAR.md:175,262). SEQ_SE_DP_DECIDE2 (1694, include/constants/sndseq.h:692) is
 * NOT used as a stand-in: C3_SOUND_SPEC.md:81-84 records it as a substitution that needs an
 * owner ruling which does not exist, and §1 OUT forbids "improving" the table without a
 * listen test. A placeholder here is the exact failure the ruling exists to prevent, so the
 * hole is a hole: sound_policy.h's classifier refuses index 2 with the named reason below.
 *
 * The three wired ids, from the pinned pret (ad7a3afa), are the code table:
 *   1 SUCCESS -> SEQ_SE_DP_DECIDE     1501  include/constants/sndseq.h:499
 *   3 BOO     -> SEQ_SE_DP_WALL_HIT  1536  include/constants/sndseq.h:534  (PROVISIONAL, Q4)
 *   4 NOTIFY  -> SEQ_SE_DP_SELECT    1500  include/constants/sndseq.h:498
 */
#define SLINK_GEN4_SE_SUCCESS 1501u
#define SLINK_GEN4_SE_BOO 1536u     /* provisional: no C caller, needs the C3 listen test (Q4) */
#define SLINK_GEN4_SE_NOTIFY 1500u

/* ---------------------------------------------------------------- the hold bound
 * Gen 2's SLINK_SFX_MAX_HOLD EQU 240, ported one-for-one (patch/gen2/src/sfx.asm:6,
 * C3_SOUND_SPEC.md:257). It is a bound on SERVICE VISITS, never a deadline:
 * gSystem.frameCounter is zeroed every outer loop iteration (pret src/main.c:124) and is
 * forbidden as any kind of clock (C2_BEACON_SPEC.md:4); gSystem.vblankCounter is C2's clock
 * and C3 does not touch it. The Gen 2 caveat travels verbatim: "this is a 240-visit bound,
 * not a wall-clock/frame guarantee" (sfx.asm:1-5).
 */
#define SLINK_GEN4_SOUND_MAX_HOLD_VISITS 240u

/* ---------------------------------------------------------------- D-C3-2: the named reason
 * Title-private reason codes are 32..63; 16..31 are reserved for future shared reasons
 * (ABI owner, Gen 5, 2026-10-02; C3_SOUND_SPEC.md:17-20). 32 = SOUND_CODE_REFUSED is
 * decoded only by the Gen 4 adapter, so a host can tell "this build has no FAILURE sound"
 * apart from a generic bad-arguments refusal (F5). No abi.h edit: cite the ruling.
 *
 * The OTHER reasons C3 writes are the shared vocabulary and are pinned by falsifiers, not
 * invented: SLINK_REASON_BAD_ARGS (2) for a code outside 1..4 (F4), SLINK_REASON_CLIENT_TOO_OLD
 * (13) for a zero epoch and SLINK_REASON_IDENTITY (12) for a mismatch -- the identical gate
 * sound_producer.h:18-19 uses (C3_SOUND_SPEC.md:272-275).
 *
 * Two refusal reasons the spec does NOT name -- "sound not initialised yet" and "the hold
 * expired" -- are NOT defined here. They are caller-supplied (SlinkGen4SoundReasons) so this
 * card cannot quietly invent a code: see sound_policy.h.
 */
#define SLINK_GEN4_REASON_SOUND_CODE_REFUSED 32u /* SOUND_CODE_REFUSED: title-private 32..63 */

/* ---------------------------------------------------------------- D-C3-1: the NOTIFY gate
 * capabilities is ROM-owned (FEATURE_BAR.md:258). The shared vocabulary stops at bit 6
 * (abi.h:88-96) and bits 16..31 are title-private (ABI owner, 2026-10-02), so NOTIFY is
 * gated on the title-private bit 16, declared HERE as C3_SOUND_SPEC.md:436-440 rules, with
 * no abi.h edit. C3 sets the shared SLINK_CAP_NATIVE_SOUND (bit 2) too
 * (C3_SOUND_SPEC.md:450-453).
 *
 * This constant is C3's CONTRIBUTION, not the published word. The beacon composes that
 * one per visit out of SLINK_GEN4_CAPABILITIES (zero at C2) plus the contribution word
 * of every COMPILED-IN card, and it composes AFTER the fan-out (beacon.h,
 * Slink_NDS_PublishCaps). C3 therefore writes the contribution -- from its own readiness,
 * in slink_gen4_sound_step() and slink_gen4_sound_latch_ready() (sound_policy.h) -- and
 * never writes m->capabilities: the beacon is the single writer and stamps last, so a
 * bit set there would be erased later in the same visit. A host still proves liveness
 * from signature + abi_version alone and must not gate on this word
 * (C2_BEACON_SPEC.md:436-442).
 */
#define SLINK_GEN4_CAP_SE_NOTIFY (1u << 16)
#define SLINK_GEN4_SOUND_CAPABILITIES (SLINK_CAP_NATIVE_SOUND | SLINK_GEN4_CAP_SE_NOTIFY)

/* ---------------------------------------------------------------- the dispatch seam
 * The signature the C2 dispatcher already calls from its SLINK_GEN4_SOUND arm, and
 * the only place a producer is ever named outside dispatch.c. A production module takes the
 * state block and the mailbox, never a region pointer: the arena base is reached through
 * beacon.h's single fail-closed accessor, so no card can address the span by literal.
 */
void Slink_NDS_Sound_Service(SlinkGen4State *st, volatile SlinkMailboxV2 *m);

#endif /* SLINK_GEN4_SOUND_H */