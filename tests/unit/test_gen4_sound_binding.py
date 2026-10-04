"""SOURCE + host-C MODEL for the real C3 sound.c game binding; never audible/PHYSICAL.

Compile the actual service and dispatcher against fake game boundaries, not a replacement
policy. The fake archive's player assignment is MODEL data, not a claim about an HG/SS/hge
SDAT. Every mutant compiles with -Werror and must fail a behavioral assertion.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_gen4_c2_beacon_source import file_scope_objects, span_literals
from tests.unit.test_gen4_sound_codes import CC_FLAGS, _gcc

ROOT = Path(__file__).resolve().parents[2]
GEN4 = ROOT / "patch/src/nds/gen4"
COMMON = ROOT / "patch/src/nds/common"
SOURCE = GEN4 / "sound.c"
PRET = Path(os.environ.get("SLINK_PRET_HGSS", "E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold"))

if os.name == "nt":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x8003)

GLOBAL = r"""
#ifndef FAKE_GLOBAL_H
#define FAKE_GLOBAL_H
#include <stdint.h>
#include <stddef.h>
typedef uint16_t u16;
typedef int BOOL;
struct NNSSndSeqPlayer;
typedef struct NNSSndHandle { struct NNSSndSeqPlayer *player; } NNSSndHandle;
#endif
"""

GAME_SOUND = r"""
#ifndef FAKE_GAME_SOUND_H
#define FAKE_GAME_SOUND_H
#include "global.h"
/* Exact enum order: pinned pret include/sound.h:15-25. Player ids are not this enum. */
enum SoundHandleNo { SND_HANDLE_FIELD, SND_HANDLE_PV, SND_HANDLE_ME,
 SND_HANDLE_SE_1, SND_HANDLE_SE_2, SND_HANDLE_SE_3, SND_HANDLE_SE_4,
 SND_HANDLE_BGM, SND_HANDLE_CHORUS, SND_HANDLE_MAX };
#define PLAYER_PV 0
#define PLAYER_FIELD 1
#define PLAYER_ME 2
#define PLAYER_SE_1 3
#define PLAYER_SE_2 4
#define PLAYER_SE_3 5
#define PLAYER_SE_4 6
#define PLAYER_BGM 7
BOOL GF_SndGetFadeTimer(void);
BOOL GF_SndGetAfterFadeDelayTimer(void);
enum SoundHandleNo GF_GetSndHandleByPlayerNo(int);
NNSSndHandle *GF_GetSoundHandle(int);
#endif
"""

DRIVER = r"""
#include "global.h"
#include <sound.h>
#include "sound_policy.h"
#include "dispatch.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

void Slink_NDS_Sound_LatchReady(SlinkGen4State *);
static SlinkGen4State state;
static SlinkMailboxV2 mailbox;
static NNSSndHandle handles[SND_HANDLE_MAX];
static int token, fade, delay, plays, last_se, lookups, mappings, handle_reads, last_handle;
static int bad_player, bad_handle, null_handle, ownership_violation;
static int owned_state_only(const SlinkGen4State *before);
static int mailbox_ack_only(const SlinkMailboxV2 *before);
/* Caller-selected MODEL-only reasons; not production assignments of the OPEN seam. */
void Slink_Gen4Sound_GetRefusalReasons(SlinkGen4SoundReasons *r)
{ r->not_ready=40u; r->hold_expired=41u; }
BOOL GF_SndGetFadeTimer(void) { return fade; }
BOOL GF_SndGetAfterFadeDelayTimer(void) { return delay; }
int GF_GetPlayerNoBySeq(int seq)
{
    lookups++;
    if (bad_player) return 255;
    if (seq==1501) return PLAYER_SE_2;
    if (seq==1536) return PLAYER_SE_4;
    return PLAYER_SE_1;
}
enum SoundHandleNo GF_GetSndHandleByPlayerNo(int p)
{
    mappings++;
    if (bad_handle) return (enum SoundHandleNo)SND_HANDLE_MAX;
    if (p==PLAYER_FIELD) return SND_HANDLE_FIELD;
    if (p==PLAYER_PV) return SND_HANDLE_PV;
    return (enum SoundHandleNo)p;
}
NNSSndHandle *GF_GetSoundHandle(int h)
{
    handle_reads++; last_handle=h;
    return null_handle ? NULL : &handles[h];
}
void PlaySE(u16 seq) { plays++; last_se=seq; }

#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
#define EPOCH 0x11223344u
static void setup(int ready)
{
    memset(&state,0xA5,sizeof state);
    memset(&state.sound,0,sizeof state.sound);
    state.magic=SLINK_GEN4_STATE_MAGIC; state.generation=EPOCH;
    memset(&mailbox,0xC3,sizeof mailbox);
    mailbox.opcode=0; mailbox.seq=7; mailbox.session_epoch=EPOCH;
    memset(handles,0,sizeof handles);
    fade=delay=plays=lookups=mappings=handle_reads=bad_player=bad_handle=null_handle=0;
    last_se=last_handle=-1; ownership_violation=0;
    if (ready) {
        SlinkGen4State before; memcpy(&before,&state,sizeof before);
        Slink_NDS_Sound_LatchReady(&state);
        if (!owned_state_only(&before)) ownership_violation=1;
    }
}
static void post(unsigned code)
{ mailbox.opcode=SLINK_OP_PLAY_SE; mailbox.args[0]=(uint8_t)code; mailbox.status=SLINK_ST_BUSY; }
static void visit(void)
{
    SlinkGen4State before; memcpy(&before,&state,sizeof before);
    SlinkMailboxV2 mbefore; memcpy(&mbefore,&mailbox,sizeof mbefore);
    Slink_NDS_Dispatch(&state,&mailbox);
    if (!owned_state_only(&before) || !mailbox_ack_only(&mbefore)) ownership_violation=1;
}
static int owned_state_only(const SlinkGen4State *before)
{
    const unsigned char *a=(const unsigned char *)before, *b=(const unsigned char *)&state;
    size_t lo=offsetof(SlinkGen4State,sound), hi=lo+sizeof state.sound;
    for (size_t i=0;i<sizeof state;i++) if ((i<lo || i>=hi) && a[i]!=b[i]) return 0;
    return 1;
}
static int mailbox_ack_only(const SlinkMailboxV2 *before)
{
    const unsigned char *a=(const unsigned char *)before, *b=(const unsigned char *)&mailbox;
    for (size_t i=0;i<sizeof mailbox;i++) {
        if (i>=offsetof(SlinkMailboxV2,opcode) && i<offsetof(SlinkMailboxV2,opcode)+2) continue;
        if (i>=offsetof(SlinkMailboxV2,status) && i<offsetof(SlinkMailboxV2,status)+2) continue;
        if (i>=offsetof(SlinkMailboxV2,ack_seq) && i<offsetof(SlinkMailboxV2,ack_seq)+2) continue;
        if (i>=offsetof(SlinkMailboxV2,reason) && i<offsetof(SlinkMailboxV2,reason)+2) continue;
        if (a[i]!=b[i]) return 0;
    }
    return 1;
}
int main(int argc,char **argv)
{
    unsigned mode=argc>1 ? (unsigned)strtoul(argv[1],NULL,10) : 0u;
    SlinkGen4State before;
    SlinkMailboxV2 mbefore;
    setup(1);
    if (mode>=1 && mode<=4) {
        post(mode); memcpy(&before,&state,sizeof before); memcpy(&mbefore,&mailbox,sizeof mbefore); visit();
        CHECK(owned_state_only(&before)); CHECK(mailbox_ack_only(&mbefore));
        CHECK(mailbox.opcode==0 && mailbox.ack_seq==7);
        if (mode==2) { CHECK(plays==0); CHECK(mailbox.status==SLINK_ST_FAIL && mailbox.reason==32); }
        else {
            unsigned se=mode==1 ? 1501u : mode==3 ? 1536u : 1500u;
            int h=mode==1 ? SND_HANDLE_SE_2 : mode==3 ? SND_HANDLE_SE_4 : SND_HANDLE_SE_1;
            CHECK(plays==1 && last_se==(int)se); CHECK(last_handle==h);
            CHECK(lookups==1 && mappings==1 && handle_reads==1);
            CHECK(mailbox.status==SLINK_ST_OK && mailbox.reason==0);
            visit(); CHECK(plays==1);
        }
    } else if (mode>=5 && mode<=7) {
        post(1); if (mode==5) fade=1; if (mode==6) delay=1;
        if (mode==7) handles[SND_HANDLE_SE_2].player=(struct NNSSndSeqPlayer *)&token;
        visit(); CHECK(plays==0 && mailbox.opcode==SLINK_OP_PLAY_SE && mailbox.status==SLINK_ST_BUSY);
        CHECK(state.sound.hold_visits==1);
        /* A different handle may be busy; only this request's resolved handle blocks. */
        fade=delay=0; handles[SND_HANDLE_SE_2].player=NULL;
        handles[SND_HANDLE_SE_1].player=(struct NNSSndSeqPlayer *)&token;
        visit(); CHECK(plays==1 && mailbox.status==SLINK_ST_OK);
    } else if (mode==8) {
        post(4); fade=1; for (unsigned i=0;i<239;i++) visit();
        CHECK(plays==0 && mailbox.opcode==SLINK_OP_PLAY_SE && state.sound.hold_visits==239);
        visit(); CHECK(plays==0 && mailbox.opcode==0 && mailbox.status==SLINK_ST_FAIL && mailbox.reason==41);
        fade=0; visit(); CHECK(plays==0);
    } else if (mode==9) {
        setup(0); post(1); visit(); CHECK(plays==0 && mailbox.status==SLINK_ST_FAIL && mailbox.reason==40);
        CHECK(state.sound.caps==0); Slink_NDS_Sound_LatchReady(&state);
        post(1); visit(); CHECK(plays==1 && mailbox.status==SLINK_ST_OK);
    } else if (mode==10 || mode==11) {
        post(1); mailbox.session_epoch=mode==10 ? 0u : EPOCH+1u;
        visit(); CHECK(plays==0 && mailbox.status==SLINK_ST_FAIL);
        CHECK(mailbox.reason==(mode==10 ? SLINK_REASON_CLIENT_TOO_OLD : SLINK_REASON_IDENTITY));
    } else if (mode==12) {
        post(1); fade=1; visit(); CHECK(state.sound.in_flight==1);
        memset(&state.sound,0,sizeof state.sound); /* new boot heap allocation, ITCM request survives */
        state.generation++; fade=0; visit(); CHECK(plays==0 && mailbox.status==SLINK_ST_FAIL && mailbox.reason==40);
        Slink_NDS_Sound_LatchReady(&state); post(1); visit();
        CHECK(plays==0 && mailbox.reason==SLINK_REASON_IDENTITY);
    } else if (mode==13) {
        mailbox.opcode=SLINK_OP_PLAY_FANFARE; memcpy(&before,&state,sizeof before); memcpy(&mbefore,&mailbox,sizeof mbefore); visit();
        CHECK(plays==0 && memcmp(&mbefore,&mailbox,sizeof mailbox)==0);
        CHECK(owned_state_only(&before));
    } else if (mode==14 || mode==15 || mode==16) {
        post(1); bad_player=mode==14; bad_handle=mode==15; null_handle=mode==16;
        visit(); CHECK(plays==0 && mailbox.opcode==SLINK_OP_PLAY_SE);
        CHECK(mode!=14 || mappings==0); CHECK(mode!=15 || handle_reads==0);
    } else if (mode==17) {
        post(1); state.magic=0; memcpy(&before,&state,sizeof before); memcpy(&mbefore,&mailbox,sizeof mbefore); visit();
        Slink_NDS_Sound_LatchReady(&state); CHECK(memcmp(&before,&state,sizeof state)==0);
        CHECK(memcmp(&mbefore,&mailbox,sizeof mailbox)==0 && plays==0);
        Slink_NDS_Sound_Service(NULL,&mailbox); Slink_NDS_Sound_Service(&state,NULL);
    } else if (mode==18) {
        post(0); visit(); CHECK(plays==0 && mailbox.status==SLINK_ST_FAIL && mailbox.reason==SLINK_REASON_BAD_ARGS);
    } else if (mode==19) {
        post(1); fade=1; visit(); mailbox.opcode=SLINK_OP_TRADE_STATUS;
        memcpy(&mbefore,&mailbox,sizeof mbefore); visit(); CHECK(state.sound.in_flight==0 && plays==0);
        CHECK(memcmp(&mbefore,&mailbox,sizeof mailbox)==0);
    } else return 2;
    CHECK(!ownership_violation);
    printf("OK %u\n",mode); return 0;
}
"""


def test_binding_source_exists_and_owns_no_static_storage_or_span_address():
    assert SOURCE.exists(), "C3 has no sound.c game binding"
    source = SOURCE.read_text(encoding="utf-8")
    assert file_scope_objects(source) == []
    assert span_literals(source) == []


def build(tmp, *, mutant=None):
    assert SOURCE.exists(), "C3 has no sound.c game binding"
    game = tmp / "fake_game"
    game.mkdir(parents=True)
    (game / "global.h").write_text(GLOBAL, encoding="utf-8")
    (game / "sound.h").write_text(GAME_SOUND, encoding="utf-8")
    (game / "unk_02005D10.h").write_text('#include "global.h"\nvoid PlaySE(u16);\n', encoding="utf-8")
    driver = tmp / "driver.c"
    driver.write_text(DRIVER, encoding="utf-8")
    source = SOURCE
    if mutant:
        old, new = mutant
        text = SOURCE.read_text(encoding="utf-8")
        assert text.count(old) == 1, "mutant anchor drifted"
        source = tmp / "mutant.c"
        source.write_text(text.replace(old, new), encoding="utf-8")
    exe = tmp / "binding.exe"
    result = subprocess.run([_gcc(), *CC_FLAGS, "-DSLINK_GEN4_SOUND", "-I", str(game),
                             "-I", str(GEN4), "-I", str(COMMON), str(source),
                             str(GEN4 / "dispatch.c"), str(driver), "-o", str(exe)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return exe


@pytest.fixture(scope="module")
def executable(tmp_path_factory):
    return build(tmp_path_factory.mktemp("gen4_sound_binding"))


SCENARIOS = {1: "success", 2: "failure_hole", 3: "boo", 4: "notify", 5: "fade",
             6: "after_fade", 7: "resolved_busy_handle", 8: "hold_expiry", 9: "not_ready",
             10: "zero_epoch", 11: "stale_epoch", 12: "boot_reset", 13: "foreign_fanfare",
             14: "bad_archive_player", 15: "bad_handle_index", 16: "null_handle",
             17: "invalid_state", 18: "invalid_code", 19: "superseded_hold"}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS.values())
def test_real_binding_and_dispatcher(executable, scenario):
    result = subprocess.run([str(executable), str(scenario)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"OK {scenario}"


MUTANTS = [
    (5, "return GF_SndGetFadeTimer() != 0;", "return 0;"),
    (6, "return GF_SndGetAfterFadeDelayTimer() != 0;", "return 0;"),
    (7, "return ((const volatile NNSSndHandle *)handle)->player != NULL;", "return 0;"),
    (1, "PlaySE((u16)se);", "PlaySE((u16)(se + 1u));"),
    (11, "&reasons, st->generation);", "&reasons, m->session_epoch);"),
    (1, "&reasons, st->generation);", "&reasons, st->generation); st->delta++;"),
]


@pytest.mark.parametrize("scenario,old,new", MUTANTS, ids=[SCENARIOS[m[0]] for m in MUTANTS])
def test_compiled_revert_controls_fail_behavior_not_compilation(tmp_path, scenario, old, new):
    exe = build(tmp_path, mutant=(old, new))  # must compile -Werror-clean first
    result = subprocess.run([str(exe), str(scenario)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "FAIL line" in result.stderr


def test_fake_game_contract_matches_the_pinned_declarations():
    # FILE, not a sound/ROM proof. Absence is explicit instead of silently borrowing a signature.
    if not PRET.exists():
        pytest.skip(f"pinned pret absent: {PRET}")
    header = (PRET / "include/sound.h").read_text(encoding="utf-8")
    for declaration in ("BOOL GF_SndGetFadeTimer(void);", "BOOL GF_SndGetAfterFadeDelayTimer(void);",
                        "enum SoundHandleNo GF_GetSndHandleByPlayerNo(int playerNo);",
                        "NNSSndHandle *GF_GetSoundHandle(int playerNo);"):
        assert declaration in header
    assert "void PlaySE(u16 sndseq);" in (PRET / "include/unk_02005D10.h").read_text(encoding="utf-8")
    assert "struct NNSSndSeqPlayer *player;" in (PRET / "lib/include/nnsys/snd/player.h").read_text(encoding="utf-8")
