/* C3 game binding: policy decisions stay in sound_policy.h; no private storage here.
 * Called only by C2's main-queue fan-out (dispatch.c:34-35), never an IRQ/vblank hook.
 *
 * Include order is intentional: <sound.h> is the GAME header. Its include directory
 * must precede patch/src/nds/gen4 in this translation unit's search path. The quoted
 * sound.h inside sound_policy.h resolves beside that policy and is the CARD interface.
 * global.h supplies the pinned game's u16/BOOL/NNSSndHandle types.
 */
#include "global.h"
#include <sound.h>
#include "unk_02005D10.h"

#include "sound_policy.h"

/* ASM_EXTERN: pinned pret asm/unk_02004A44.s:1501-1518 consumes seq in r0 and
 * returns the archive's player byte (or 0xff) in r0. No C header declares it at
 * ad7a3afa. This binding calls only with a u16 SE id (PlaySE's own path,
 * asm/unk_02005D10.s:413-428), so the int register interface covers its proven range.
 * It is the real game symbol, not a compile-time player/channel guess.
 */
extern int GF_GetPlayerNoBySeq(int seq);

/* OPEN: C3 spec assigns no numeric reason to pre-InitSoundData or hold expiry.
 * sound_policy.h:77-81 deliberately makes these caller supplied. The integration
 * owner must define this symbol and fill BOTH fields; there are no guessed defaults.
 * The host model's values are test data, not production reason assignments.
 */
extern void Slink_Gen4Sound_GetRefusalReasons(SlinkGen4SoundReasons *out);

static int Slink_Gen4Sound_Fade(void *context)
{
    (void)context;
    /* include/sound.h:38; asm/unk_02005D10.s:311-318; sound.c:229-230. */
    return GF_SndGetFadeTimer() != 0;
}

static int Slink_Gen4Sound_AfterFade(void *context)
{
    (void)context;
    /* include/sound.h:39; asm/unk_02004A44.s:2184-2188; sound.c:231-232.
     * Keep the spec's second guard; its gameplay necessity remains Q5 INFERRED. */
    return GF_SndGetAfterFadeDelayTimer() != 0;
}

static int Slink_Gen4Sound_Busy(void *context, uint16_t se)
{
    int player;
    enum SoundHandleNo number;
    NNSSndHandle *handle;

    (void)context;
    /* Same two lookups as PlaySE: asm/unk_02005D10.s:413-428. The archive, not
     * this module, picks the player. Validate BEFORE the game's default assert
     * in sound.c:426-449; constants/sndseq.h:2502-2509 names the accepted players. */
    player = GF_GetPlayerNoBySeq((int)se);
    switch (player) {
    case PLAYER_FIELD:
    case PLAYER_PV:
    case PLAYER_ME:
    case PLAYER_SE_1:
    case PLAYER_SE_2:
    case PLAYER_SE_3:
    case PLAYER_SE_4:
    case PLAYER_BGM:
        break;
    default:
        return 1; /* unreadable/absent archive entry: hold, never assert or play */
    }
    number = GF_GetSndHandleByPlayerNo(player);
    if ((unsigned)number >= (unsigned)SND_HANDLE_MAX) {
        return 1;
    }
    /* include/sound.h:66; sound.c:416-424 returns the handle, not its player.
     * This avoids re-declaring SND_WORK or naming a RAM address/struct offset. */
    handle = GF_GetSoundHandle((int)number);
    if (handle == NULL) {
        return 1;
    }
    /* lib/include/nnsys/snd/player.h:4-6: the sole field is player. On ARM9 it
     * is word zero, the exact busy guard in lib/asm/nnsys.s:23991-23994.
     * Read the typed field instead of aliasing a pointer object through u32*. */
    return ((const volatile NNSSndHandle *)handle)->player != NULL;
}

static void Slink_Gen4Sound_Play(void *context, uint16_t se)
{
    (void)context;
    /* include/unk_02005D10.h:6, asm/unk_02005D10.s:413-428. ACK means handed
     * to PlaySE, not heard; native priority/output is a PHYSICAL question. */
    PlaySE((u16)se);
}

/* OPEN integration hook: call ONLY AFTER InitSoundData has returned, with C2's
 * OWN heap state (pret sound.c:82-98, main.c:66). C6 wires the approved wrapper/
 * hge .org vehicle; this card neither invents a state lookup nor patches the fork.
 * Fresh boot allocations clear readiness; do not latch on ordinary Sound_Stop. */
void Slink_NDS_Sound_LatchReady(SlinkGen4State *st)
{
    if (st == NULL || st->magic != SLINK_GEN4_STATE_MAGIC) {
        return;
    }
    slink_gen4_sound_latch_ready(&st->sound);
}

void Slink_NDS_Sound_Service(SlinkGen4State *st, volatile SlinkMailboxV2 *m)
{
    SlinkGen4SoundEngine engine;
    SlinkGen4SoundReasons reasons;

    if (st == NULL || st->magic != SLINK_GEN4_STATE_MAGIC || m == NULL) {
        return;
    }
    Slink_Gen4Sound_GetRefusalReasons(&reasons);
    engine.context = NULL;
    engine.fade = Slink_Gen4Sound_Fade;
    engine.after_fade_delay = Slink_Gen4Sound_AfterFade;
    engine.se_busy = Slink_Gen4Sound_Busy;
    engine.play_se = Slink_Gen4Sound_Play;

    /* beacon.c:248-252,270: C2's configured session generation, NOT the untrusted
     * host session_epoch. Policy owns layout/reset, code table, hold bound and
     * shared ACK writes; only st->sound may be changed in the heap state. */
    (void)slink_gen4_sound_step(m, &st->sound, &engine, &reasons, st->generation);
}
