"""Host-C SOURCE/MODEL for C5 layout and the real trade binding; no PHYSICAL claim."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_gen4_sound_codes import CC_FLAGS, _gcc
from tests.unit.test_gen4_trade_policy import (
    HARNESS_C as POLICY_DRIVER,
    SCENARIOS as POLICY_SCENARIOS,
)

ROOT = Path(__file__).resolve().parents[2]
GEN4 = ROOT / "patch/src/nds/gen4"
COMMON = ROOT / "patch/src/nds/common"

if os.name == "nt":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x8003)


def compile_c(tmp, source, *, sources=(), includes=(), defines=()):
    tmp.mkdir(parents=True, exist_ok=True)
    driver = tmp / "driver.c"
    driver.write_text(source, encoding="utf-8")
    exe = tmp / "probe.exe"
    command = [_gcc(), *CC_FLAGS, *defines]
    for directory in (*includes, GEN4, COMMON):
        command += ["-I", str(directory)]
    command += [str(driver), *map(str, sources), "-o", str(exe)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return exe


LAYOUT_C = r'''
#include "beacon.h"
#include "trade.h"
#include <stdio.h>
#include <string.h>
static uint32_t frame(void *p) { (void)p; return 1; }
int main(void) {
    struct { uint32_t before; SlinkGen4State st; uint32_t after; } box;
    SlinkGen4TradeSeam seam;
    SlinkTradeWitnessV2 witness;
    SlinkRecordStageV1 stage;
    memset(&box,0,sizeof box); memset(&seam,0,sizeof seam);
    memset(&witness,0,sizeof witness); memset(&stage,0,sizeof stage);
    box.before=0x1234; box.after=0x5678; seam.frame=frame;
    box.st.trade.layout=1;
    if (Slink_Gen4TradeState_LayoutValid(&box.st.trade)) return 1;
    box.st.trade.layout=SLINK_GEN4_STATE_TRADE_LAYOUT;
    if (!Slink_Gen4TradeState_LayoutValid(&box.st.trade)) return 2;
    box.st.trade.seam=seam;
    if (!Slink_Gen4TradePolicy_Init(&box.st.trade.policy,&box.st.trade.seam,&witness,&stage,1)) return 3;
    if (box.before!=0x1234 || box.after!=0x5678) return 4;
    if (box.st.trade.policy.seam!=&box.st.trade.seam) return 5;
    if (box.st.trade.policy.engine.context!=&box.st.trade.policy) return 6;
    if (box.st.trade.policy.decoder_ctx.owner!=&box.st.trade.policy) return 7;
    box.st.trade.caps=SLINK_GEN4_TRADE_CAPABILITIES;
    if (box.st.trade.policy.magic!=SLINK_GEN4_TRADE_POLICY_MAGIC) return 8;
    Slink_Gen4TradePolicy_Service(&box.st.trade.policy,NULL);
    printf("%zu %zu %zu %zu %zu\n",sizeof(SlinkGen4StateTrade),sizeof(SlinkGen4TradePolicy),
           offsetof(SlinkGen4StateTrade,policy),offsetof(SlinkGen4StateTrade,seam),
           offsetof(SlinkGen4StateTrade,caps));
    return 0;
}
'''


def test_layout_recipe_typechecks_and_initialization_stays_inside_allocated_state(tmp_path):
    executable = compile_c(tmp_path, LAYOUT_C)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    size, policy_size, policy_off, seam_off, caps_off = map(int, result.stdout.split())
    assert policy_size > 556  # former producer-only allocation, independently measured before amendment
    assert policy_off + policy_size <= seam_off < caps_off < size
    assert policy_off % 4 == seam_off % 4 == 0


def test_declared_trade_recipe_uses_embedded_policy_and_persistent_seam():
    text = (GEN4 / "trade.h").read_text(encoding="utf-8")
    assert "Slink_Gen4TradePolicy_Init(&st->trade.policy, &st->trade.seam" in text
    assert "Slink_Gen4TradePolicy_Service(&st->trade.policy, m)" in text
    assert "Slink_Gen4Trade_CommitEntered(&st->trade.policy, slot)" in text
    assert "Slink_Gen4Trade_Commit(&st->trade.policy, slot)" in text


FAKE_GAME = r"""
#ifndef FAKE_GAME_H
#define FAKE_GAME_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef int BOOL;
#define TRUE 1
#define MON_DATA_OT_ID 7
/* Fake shapes match the exposed HGSS fields/sizes; this is NOT a PK4 cipher. */
typedef struct { u32 personality; u16 partyDecrypted:1, boxDecrypted:1, checksumFailed:1, unused:13;
 u16 checksum; u8 dataBlocks[128]; } BoxPokemon;
typedef struct { BoxPokemon box; u8 party[100]; } Pokemon;
typedef struct { int count; Pokemon mons[6]; u8 modifiers[6][5]; } Party;
typedef struct { Party party; } SaveData;
struct System { u32 vblankCounter; }; extern struct System gSystem;
Party *SaveArray_Party_Get(SaveData *);
int Party_GetCount(const Party *);
Pokemon *Party_GetMonByIndex(Party *,int);
void Party_SafeCopyMonToSlot_ResetAprijuiceModifiers(Party *,int,Pokemon *);
void MonDecryptSegment(void *,u32,u32);
u32 CalcMonChecksum(void *,u32);
u32 GetBoxMonData(BoxPokemon *,int,void *);
#endif
"""

NATIVE_STUBS = r"""
struct System gSystem;
static int native_pre, native_scene, native_begin, native_saves, native_commits;
static int native_safe=1, native_selected, native_start_calls;
static const uint8_t *native_handed;
static uint16_t native_handed_len;
SaveData *Slink_Gen4Trade_SaveData(void *ctx) { return (SaveData *)ctx; }
Party *SaveArray_Party_Get(SaveData *s) { return &s->party; }
int Party_GetCount(const Party *p) { return p->count; }
Pokemon *Party_GetMonByIndex(Party *p,int slot) { return &p->mons[slot]; }
void Party_SafeCopyMonToSlot_ResetAprijuiceModifiers(Party *p,int slot,Pokemon *record)
{ memcpy(&p->mons[slot],record,sizeof *record); memset(p->modifiers[slot],0,5); native_commits++; }
/* Test-only engine primitive: XOR, independent checksum constant. NOT a PK4 implementation. */
void MonDecryptSegment(void *data,u32 n,u32 key)
{ u8 *b=(u8 *)data; (void)key; for (u32 i=0;i<n;i++) b[i]^=0xA5; }
u32 CalcMonChecksum(void *data,u32 n) { (void)data; (void)n; return 0x5A; }
u32 GetBoxMonData(BoxPokemon *p,int attr,void *out)
{
    (void)attr; (void)out;
    return (u32)p->dataBlocks[4] | ((u32)p->dataBlocks[5]<<8) | ((u32)p->dataBlocks[6]<<16) | ((u32)p->dataBlocks[7]<<24);
}
int Slink_Gen4Trade_SelectedSlot(void *ctx,unsigned *out) { (void)ctx; *out=(unsigned)native_selected; return 1; }
int Slink_Gen4Trade_SafeField(void *ctx) { (void)ctx; return native_safe; }
int Slink_Gen4Trade_StartConsent(void *ctx) { (void)ctx; return 1; }
int Slink_Gen4Trade_PollConsent(void *ctx) { (void)ctx; return native_pre; }
int Slink_Gen4Trade_SceneStart(void *ctx,unsigned slot,const uint8_t *record,uint16_t len)
{ (void)ctx; (void)slot; native_start_calls++; native_handed=record; native_handed_len=len; return 1; }
int Slink_Gen4Trade_ScenePoll(void *ctx) { (void)ctx; return native_scene; }
int Slink_Gen4Trade_PostSaveBegin(void *ctx) { (void)ctx; native_begin++; return 1; }
int Slink_Gen4Trade_PostSavePoll(void *ctx) { (void)ctx; native_saves++; return SLINK_SAVEPOLL_OK; }
"""


def fake_game(tmp):
    directory = tmp / "game"
    directory.mkdir(parents=True)
    (directory / "global.h").write_text(FAKE_GAME, encoding="utf-8")
    for name in ("party.h", "pokemon.h", "system.h"):
        (directory / name).write_text('#include "global.h"\n', encoding="utf-8")
    return directory


def binding_driver():
    source = POLICY_DRIVER
    source = '#include "global.h"\n#include "dispatch.h"\n' + source
    source = source.replace('static SlinkGen4TradePolicy pol;',
                            'static SlinkGen4State bound_state;\n#define pol (bound_state.trade.policy)')
    source = source.replace('static SlinkGen4TradeSeam seam;', '#define seam (bound_state.trade.seam)')
    source = source.replace('memset(&pol, 0, sizeof pol);',
                            'memset(&bound_state,0,sizeof bound_state); bound_state.magic=SLINK_GEN4_STATE_MAGIC;')
    source = source.replace('Slink_Gen4TradePolicy_Init(&pol, &seam, &w, &stage, 1000000u)',
                            'Slink_NDS_Trade_Bind(&bound_state, &seam, &w, &stage, 1000000u)')
    source = source.replace('Slink_Gen4TradePolicy_Service(&pol, &m);', 'Slink_NDS_Dispatch(&bound_state, &m);')
    source = source.replace('Slink_Gen4Trade_CommitEntered(&pol,', 'Slink_NDS_Trade_CommitEntered(&bound_state,')
    source = source.replace('Slink_Gen4Trade_Commit(&pol,', 'Slink_NDS_Trade_Commit(&bound_state,')
    return source + NATIVE_STUBS


def build_binding(tmp, driver, *, mutant=None):
    game = fake_game(tmp)
    source = GEN4 / "trade.c"
    if mutant:
        old, new = mutant
        text = source.read_text(encoding="utf-8")
        assert text.count(old) == 1, "mutant anchor drifted"
        source = tmp / "mutant_trade.c"
        source.write_text(text.replace(old, new), encoding="utf-8")
    return compile_c(tmp, driver, sources=(source, GEN4 / "dispatch.c"),
                     includes=(game,), defines=("-DSLINK_GEN4_TRADE",))


@pytest.fixture(scope="module")
def binding_exe(tmp_path_factory):
    return build_binding(tmp_path_factory.mktemp("gen4_trade_binding"), binding_driver())


@pytest.mark.parametrize("name,scenario,variant", POLICY_SCENARIOS, ids=[r[0] for r in POLICY_SCENARIOS])
def test_real_binding_retains_all_policy_refusal_and_lifecycle_scenarios(binding_exe, name, scenario, variant):
    result = subprocess.run([str(binding_exe), str(scenario), str(variant)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, name + result.stdout + result.stderr


NATIVE_DRIVER = r"""
#include "global.h"
#include "trade.h"
#include "dispatch.h"
#include <stdio.h>
#include <stdlib.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#c); return 1; } } while(0)
""" + NATIVE_STUBS + r"""
static SlinkGen4State st;
static SlinkMailboxV2 mb;
static SlinkTradeWitnessV2 witness;
static SlinkRecordStageV1 stage;
static SaveData save;
static Pokemon incoming;
static void word(uint8_t *p,uint32_t n) { for (unsigned i=0;i<4;i++) p[i]=(uint8_t)(n>>(8*i)); }
static void encode(Pokemon *p,uint32_t pid,uint32_t ot)
{
    memset(p,0,sizeof *p); p->box.personality=pid; p->box.checksum=0x5A;
    word(&p->box.dataBlocks[4],ot); MonDecryptSegment(p->box.dataBlocks,128,0);
}
static int stable_other(const SlinkGen4State *old)
{
    size_t lo=offsetof(SlinkGen4State,trade), hi=lo+sizeof st.trade;
    const uint8_t *a=(const uint8_t *)old,*b=(const uint8_t *)&st;
    for(size_t i=0;i<sizeof st;i++) if((i<lo || i>=hi) && a[i]!=b[i]) return 0;
    return 1;
}
static int owned=1;
static void visit(void)
{
    SlinkGen4State old; memcpy(&old,&st,sizeof old);
    gSystem.vblankCounter++; Slink_NDS_Dispatch(&st,&mb);
    if(!stable_other(&old)) owned=0;
}
static int prepare(void)
{
    mb.session_epoch=7; mb.seq=1; mb.opcode=SLINK_OP_TRADE_PREPARE;
    mb.args[0]=0;word(mb.args+4,0x1234);word(mb.args+8,0x5678);word(mb.args+12,1);mb.args[16]=9;
    visit(); CHECK(mb.producer_phase==SLINK_PHASE_PRE_SAVE && native_begin==0 && native_commits==0);
    native_pre=2;visit();CHECK(native_begin==0 && native_commits==0);
    native_pre=1;visit();CHECK(mb.producer_phase==SLINK_PHASE_READY && native_begin==0);
    return 0;
}
int main(int argc,char **argv)
{
    int mode=argc>1 ? atoi(argv[1]) : 1;
    SlinkGen4State old;
    memset(&st,0xA5,sizeof st);memset(&st.trade,0,sizeof st.trade);st.magic=SLINK_GEN4_STATE_MAGIC;
    memset(&mb,0,sizeof mb);memset(&witness,0,sizeof witness);memset(&stage,0,sizeof stage);
    memset(&save,0,sizeof save);save.party.count=1;encode(&save.party.mons[0],0x1234,0x5678);
    memset(save.party.modifiers[0],0x33,5);encode(&incoming,0xAABB,0xCCDD);
    stage.layout_version=SLINK_NDS_STAGE_LAYOUT;stage.binding_id=SLINK_BIND_GEN4_PK4;
    stage.generation=4;stage.flags=SLINK_STAGE_RAW_ENCRYPTED;stage.stage_len=sizeof incoming;
    stage.claimed_pid=0xAABB;stage.claimed_otid=0xCCDD;memcpy((void *)stage.record,&incoming,sizeof incoming);
    CHECK(Slink_NDS_Trade_Init(&st,&save,&witness,&stage,100)==1);
    CHECK(st.trade.policy.seam==&st.trade.seam);
    if(mode==2) {
        st.trade.layout=1;memcpy(&old,&st,sizeof old);mb.opcode=SLINK_OP_TRADE_PREPARE;
        visit();CHECK(memcmp(&old,&st,sizeof st)==0);CHECK(mb.opcode==SLINK_OP_TRADE_PREPARE);
        CHECK(Slink_NDS_Trade_Init(&st,&save,&witness,&stage,100)==0);
        CHECK(Slink_NDS_Trade_CommitEntered(&st,0)==0 && Slink_NDS_Trade_Commit(&st,0)==0);
        return 0;
    }
    if(mode==4) {
        save.party.count=-1;
        mb.session_epoch=7;mb.seq=1;mb.opcode=SLINK_OP_TRADE_PREPARE;
        word(mb.args+4,0x1234);word(mb.args+8,0x5678);word(mb.args+12,1);mb.args[16]=9;
        visit();CHECK(mb.status==SLINK_ST_FAIL && native_commits==0);return 0;
    }
    if(prepare())return 1;
    if(mode==3) ((uint8_t *)(void *)stage.record)[6]^=1;
    if(mode==5) ((uint8_t *)(void *)stage.record)[4]|=1;
    mb.seq=2;mb.opcode=SLINK_OP_TRADE_SCENE;mb.args[0]=0;visit();
    if(mode==3 || mode==5) {
        CHECK(witness.final_result==SLINK_TRADE_UNCHANGED && native_start_calls==0);
        CHECK(native_commits==0 && native_begin==0 && owned);return 0;
    }
    CHECK(native_start_calls==1 && native_commits==0 && native_begin==0);
    CHECK(native_handed==(const uint8_t *)st.trade.policy.producer.scratch);
    CHECK(native_handed!=(const uint8_t *)st.trade.policy.producer.incoming && native_handed_len==sizeof incoming);
    CHECK(memcmp(native_handed,&incoming,sizeof incoming)==0);
    CHECK(Slink_NDS_Trade_Commit(&st,0)==0);CHECK(native_commits==0 && native_begin==0);
    CHECK(Slink_NDS_Trade_CommitEntered(&st,0)==1);CHECK(native_commits==0);
    CHECK(Slink_NDS_Trade_Commit(&st,0)==1);CHECK(native_commits==1 && native_begin==0);
    CHECK(memcmp(&save.party.mons[0],&incoming,sizeof incoming)==0);
    CHECK(memcmp(st.trade.policy.producer.incoming,&incoming,sizeof incoming)==0);
    for(unsigned i=0;i<5;i++)CHECK(save.party.modifiers[0][i]==0);
    CHECK(Slink_NDS_Trade_Commit(&st,0)==0);CHECK(native_commits==1);
    native_scene=1;mb.opcode=0;visit();
    CHECK(native_begin==1 && native_saves==1 && witness.final_result==SLINK_TRADE_COMMITTED);
    CHECK(witness.received_pid==0xAABB && witness.received_otid==0xCCDD);
    CHECK(owned);puts("OK native");return 0;
}
"""


@pytest.fixture(scope="module")
def native_exe(tmp_path_factory):
    return build_binding(tmp_path_factory.mktemp("gen4_trade_native"), NATIVE_DRIVER)


@pytest.mark.parametrize("mode", [1, 2, 3, 4, 5],
                         ids=["two_phase_save_only_after", "stale_layout_refused", "bad_checksum_refused",
                              "bad_party_count_refused", "decoded_stage_refused"])
def test_native_binding_over_fake_game_primitives(native_exe, mode):
    result = subprocess.run([str(native_exe), str(mode)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


BIND_MUTANTS = [
    (1, 'return Slink_Gen4Trade_StartConsent(context);',
     'Slink_Gen4Trade_PostSaveBegin(context); return Slink_Gen4Trade_StartConsent(context);'),
    (2, '&& Slink_Gen4TradeState_LayoutValid(&st->trade)', '&& 1'),
    (1, 'return Slink_Gen4Trade_Commit(&st->trade.policy, slot);',
     'return st->trade.seam.commit_party_slot(st->trade.seam.context, slot, st->trade.policy.producer.incoming, st->trade.policy.producer.incoming_len);'),
    (1, 'st->trade.caps = SLINK_GEN4_TRADE_CAPABILITIES;',
     'st->trade.caps = SLINK_GEN4_TRADE_CAPABILITIES; st->delta++;'),
]


@pytest.mark.parametrize("mode,old,new", BIND_MUTANTS,
                         ids=["pre_save_invented", "stale_layout_accepted", "marker_bypassed", "other_card_corrupted"])
def test_binding_mutants_are_compiler_clean_then_behaviorally_red(tmp_path, mode, old, new):
    exe = build_binding(tmp_path, NATIVE_DRIVER, mutant=(old, new))
    result = subprocess.run([str(exe), str(mode)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "FAIL line" in result.stderr



def test_native_game_symbols_and_checksum_guard_match_pinned_source():
    pret = Path(os.environ.get("SLINK_PRET_HGSS", "E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold"))
    if not pret.exists():
        pytest.skip(f"pinned pret absent: {pret}")
    party = (pret / "include/party.h").read_text(encoding="utf-8")
    for declaration in ("int Party_GetCount(const Party *party);",
                        "Pokemon *Party_GetMonByIndex(Party *party, int slot);",
                        "void Party_SafeCopyMonToSlot_ResetAprijuiceModifiers(Party *party, int slot, Pokemon *src);",
                        "Party *SaveArray_Party_Get(SaveData *saveData);"):
        assert declaration in party
    pokemon = (pret / "include/pokemon.h").read_text(encoding="utf-8")
    for declaration in ("void MonDecryptSegment(void *data, u32 size, u32 seed);",
                        "u32 CalcMonChecksum(void *_data, u32 size);",
                        "u32 GetBoxMonData(BoxPokemon *boxMon, int attr, void *ptr);"):
        assert declaration in pokemon
    code = (pret / "src/pokemon.c").read_text(encoding="utf-8")
    assert "#define DECRYPT_BOX(boxMon)" in code and "#define CHECKSUM(boxMon)" in code
    assert "GF_ASSERT(checksum == boxMon->checksum);" in code
    # The new verifier must refuse through the direct engine check, not use that asserting getter as its check.
    source = (GEN4 / "trade.c").read_text(encoding="utf-8")
    verify = source.split("static int Slink_Gen4Trade_Verify", 1)[1].split("static int Slink_Gen4Trade_Decode", 1)[0]
    assert "MonDecryptSegment" in verify and "CalcMonChecksum" in verify
    assert "GetMonData(" not in verify and "GetBoxMonData(" not in verify
