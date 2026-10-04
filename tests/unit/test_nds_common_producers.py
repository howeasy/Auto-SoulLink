"""Host-C falsifiers for the shared NDS companion stack (patch/src/nds/common).

Mirrors tests/unit/test_patch_{targets,trade_producer,panel_producer,sound}.py:
the actual headers are compiled with -std=c11 -Wall -Werror and driven through
deterministic engine boundaries. Needs a host C compiler (SLINK_HOST_GCC, PATH,
or the repo's w64devkit); skips with a named reason when none exists.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "patch/src/nds/common"
GEN3 = ROOT / "patch/src/trade_targets"
CC_FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]


def _find_gcc():
    """env SLINK_HOST_GCC, PATH, then <repo common dir parent>/.cache/build-tools (worktree safe)."""
    for cand in (os.environ.get("SLINK_HOST_GCC"), shutil.which("gcc")):
        if cand:
            return cand
    bases = [ROOT]
    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
                         capture_output=True, text=True, timeout=30)
    if git.returncode == 0 and git.stdout.strip():
        bases.append((ROOT / git.stdout.strip()).resolve().parent)
    for base in bases:
        tools = base / ".cache" / "build-tools"
        for pattern in ("*/bin/gcc.exe", "*/*/bin/gcc.exe"):
            for gcc in sorted(tools.glob(pattern)):
                if (gcc.parent.parent / "libexec").is_dir():  # a bare bin/ shim has no cc1
                    return str(gcc)
    return None


def _gcc():
    gcc = _find_gcc()
    if not gcc:
        reason = ("no host C compiler (set SLINK_HOST_GCC, put gcc on PATH, or provide "
                  ".cache/build-tools/*/bin/gcc.exe); NDS producer falsifiers did NOT run")
        if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return gcc


def test_host_c_compiler_is_discoverable():
    """All-skipped must be distinguishable from all-passed: SLINK_REQUIRE_HOST_CC=1 makes absence a failure."""
    done = subprocess.run([_gcc(), "--version"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr


def _build(tmp, name, source, includes=(COMMON,), defines=()):
    src = tmp / f"{name}.c"
    src.write_text(source)
    exe = tmp / f"{name}.exe"
    cmd = [_gcc(), *CC_FLAGS, *defines]
    for inc in includes:
        cmd += ["-I", str(inc)]
    cmd += [str(src), "-o", str(exe)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return exe


def _run(exe, *args):
    done = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stdout + done.stderr + f" exit={done.returncode}"
    return done.stdout


# --------------------------------------------------------------------------- (a) Gen 3 scenarios

GEN3_TRADE_C = r'''#include "trade_producer.h"
#include <string.h>
_Static_assert(offsetof(SlinkTradeProducer,incoming)%4==0,"native Pokemon staging must be word aligned");
static int pre_done, scene_done, save_ok, saves, starts, old_present=1;
static uint32_t frame;
static int safe(void *p) { (void)p; return 1; }
static int locate(void *p,uint32_t pid,uint32_t ot) { (void)p; return old_present && pid==11 && ot==22 ? 0 : -1; }
static int pre_start(void *p) { (void)p; return 1; }
static int pre_poll(void *p) { (void)p; return pre_done; }
static int scene_start(void *p,unsigned slot,const uint8_t *b,uint16_t n) { (void)p;(void)slot;(void)b;(void)n;starts++;return 1; }
static int scene_poll(void *p) { (void)p;return scene_done; }
static volatile SlinkTradeWitnessV2 *observed;
static int save_begin(void *p) {
  (void)p;
  /* The save engine observes a committed, completed scene, never final success. */
  if (observed->milestones != 7 || observed->final_result != SLINK_TRADE_PENDING
      || !observed->revision || (observed->revision & 1)) return 0;
  saves++;return 1;
}
static int save_poll(void *p) { (void)p; return save_ok ? SLINK_SAVEPOLL_OK : SLINK_SAVEPOLL_FAIL; }
static int received(void *p,unsigned slot,uint32_t *pid,uint32_t *ot) { (void)p;(void)slot;*pid=33;*ot=44;return 1; }
static uint32_t clock_frame(void *p) { (void)p;return ++frame; }
static void word(uint8_t *p,uint32_t v) { memcpy(p,&v,4); }
int main(void) {
  SlinkTradeProducer state={0}; SlinkMailboxV2 m={0}; SlinkTradeWitnessV2 w={0};
  SlinkRecordStageV1 stage; const SlinkRecordBinding *b=&slink_binding_gen3_pk3;
  memset(&stage,0,sizeof stage);
  stage.layout_version=SLINK_NDS_STAGE_LAYOUT;stage.binding_id=b->id;stage.generation=3;
  stage.flags=SLINK_STAGE_RAW_ENCRYPTED;stage.stage_len=100;stage.claimed_pid=33;stage.claimed_otid=44;
  slink_trade_advertise(&m);
  if (m.signature != 0x4B4E4C53 || m.abi_version != 3 || m.capabilities != 1) return 20;
  m.capabilities |= SLINK_CAP_INFO_PANEL;
  slink_trade_advertise(&m);
  if (m.capabilities != 3) return 31;
  observed=&w;
  SlinkTradeEngine e;memset(&e,0,sizeof e);
  e.binding=b;e.save_timeout_frames=100000;e.pre_save_timeout_frames=0;e.safe_field=safe;e.locate=locate;e.start_pre_save=pre_start;e.poll_pre_save=pre_poll;
  e.start_scene=scene_start;e.poll_scene=scene_poll;e.post_save_begin=save_begin;e.post_save_poll=save_poll;
  e.received_key=received;e.frame=clock_frame;
  m.session_epoch=7;m.seq=1;m.opcode=SLINK_OP_TRADE_PREPARE;
  word(m.args+4,11);word(m.args+8,22);word(m.args+12,8);m.args[16]=9;
  word(stage.record,33);word(stage.record+4,44);
  slink_trade_service(&state,&m,&w,&stage,&e);
  if (m.producer_phase!=SLINK_PHASE_PRE_SAVE) return 24;
  if (w.visit_flags!=SLINK_VISIT_ACCEPTED || w.milestones) return 1;
  if (CONTROL==5) m.session_epoch++;
  pre_done=CONTROL==1?-1:1;slink_trade_service(&state,&m,&w,&stage,&e);
  if (CONTROL==1) {
    if (w.final_result!=SLINK_TRADE_UNCHANGED || starts || saves) return 9;
    return 0;
  }
  if (!(w.milestones&(1u<<SLINK_PRE_SAVE_OK)) || m.opcode) return 2;
  if (m.producer_phase!=SLINK_PHASE_READY) return 25;
  if (CONTROL==5) {
    if (w.session_epoch!=7 || m.session_epoch!=8) return 32;
    m.seq=2;m.opcode=SLINK_OP_TRADE_PREPARE;
    slink_trade_service(&state,&m,&w,&stage,&e);
    if (m.producer_phase!=SLINK_PHASE_READY || w.session_epoch!=7 || starts) return 33;
    return 0;
  }
  m.seq=2;m.opcode=SLINK_OP_TRADE_SCENE;
  SlinkTradeWitnessV2 before=w;
  if (CONTROL==2) m.args[16]++;
  if (CONTROL==3) m.session_epoch++;
  slink_trade_service(&state,&m,&w,&stage,&e);
  if (CONTROL==2 || CONTROL==3) {
    if (starts || saves || memcmp(&before,&w,sizeof(w))) return 10;
    return 0;
  }
  if (starts!=1 || w.milestones&(1u<<SLINK_COMMIT_ENTERED)) return 3;
  if (m.producer_phase!=SLINK_PHASE_SCENE) return 26;
  m.seq=3;m.opcode=SLINK_OP_TRADE_WITHDRAW;
  slink_trade_service(&state,&m,&w,&stage,&e);
  if (m.status!=SLINK_ST_FAIL || m.reason!=SLINK_REASON_WITHDRAW_TOO_LATE
      || w.final_result!=SLINK_TRADE_PENDING) return 23;
  m.seq=2;m.opcode=SLINK_OP_TRADE_SCENE;
  if (CONTROL==4) {
    old_present=0;
    if (slink_trade_commit_entered(&state,&w,0,&e)) return 11;
    scene_done=1;slink_trade_service(&state,&m,&w,&stage,&e);
    if (w.final_result!=SLINK_TRADE_UNCHANGED || saves || !state.cancel_scene) return 12;
    return 0;
  }
  if (!OMIT_COMMIT && !slink_trade_commit_entered(&state,&w,0,&e)) return 4;
  if (!OMIT_COMMIT && (w.milestones != 3 || w.milestone_seq[SLINK_COMMIT_ENTERED] != 2
      || !w.revision || (w.revision & 1))) return 21;
  scene_done=1;save_ok=SAVE_RESULT;slink_trade_service(&state,&m,&w,&stage,&e);
  if (SAVE_RESULT && !OMIT_COMMIT) {
    if (saves!=1 || w.final_result!=SLINK_TRADE_COMMITTED || m.status!=SLINK_ST_OK) return 5;
    if (!slink_trade_success_is_durable(&w,1,2,33,44)) return 6;
    if (w.received_pid!=33 || w.received_otid!=44) return 7;
    if (!(w.milestone_frame[SLINK_COMMIT_ENTERED] < w.milestone_frame[SLINK_SCENE_EVOLUTION_DONE]
        && w.milestone_frame[SLINK_SCENE_EVOLUTION_DONE] < w.milestone_frame[SLINK_POST_SAVE_OK]
        && w.milestone_frame[SLINK_POST_SAVE_OK] < w.milestone_frame[SLINK_FINAL_RESULT])) return 22;
  } else {
    if (saves!=(OMIT_COMMIT?0:1) || w.final_result!=SLINK_TRADE_UNCERTAIN) return 5;
    if (w.milestones&(1u<<SLINK_POST_SAVE_OK) || m.status==SLINK_ST_OK) return 6;
    if (slink_trade_success_is_durable(&w,1,2,33,44)) return 7;
  }
  /* Uncertain is sticky: repeating an APPLY cannot run another scene or save. */
  m.seq=3;m.opcode=SLINK_OP_TRADE_SCENE;
  slink_trade_service(&state,&m,&w,&stage,&e);
  if (starts!=1 || saves!=(OMIT_COMMIT?0:1)) return 8;
  if (m.producer_phase!=(SAVE_RESULT && !OMIT_COMMIT ? SLINK_PHASE_DONE : SLINK_PHASE_UNCERTAIN)) return 27;
  if (!SAVE_RESULT || OMIT_COMMIT) {
    SlinkTradeWitnessV2 terminal=w;
    m.session_epoch++;m.seq=4;m.opcode=SLINK_OP_TRADE_PREPARE;
    slink_trade_service(&state,&m,&w,&stage,&e);
    if (m.producer_phase!=SLINK_PHASE_UNCERTAIN || starts!=1
        || memcmp(&terminal,&w,sizeof(w))) return 28;
    /* Real reset clears volatile state; save reconciliation is external. */
    memset(&state,0,sizeof(state));memset(&m,0,sizeof(m));memset(&w,0,sizeof(w));
    slink_trade_service(&state,&m,&w,&stage,&e);
    if (m.producer_phase!=SLINK_PHASE_IDLE) return 29;
    m.session_epoch=9;m.seq=1;m.opcode=SLINK_OP_TRADE_PREPARE;
    word(m.args+4,11);word(m.args+8,22);word(m.args+12,10);m.args[16]=11;
    slink_trade_service(&state,&m,&w,&stage,&e);
    if (m.producer_phase!=SLINK_PHASE_PRE_SAVE || w.session_epoch!=9) return 30;
  }
  return 0;
}
'''


@pytest.mark.parametrize("save_result,omit_commit,control", [
    (0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 0, 1), (1, 0, 2), (1, 0, 3), (1, 0, 4), (1, 0, 5),
])
def test_gen3_scenarios_reproduce_under_the_gen3_binding(tmp_path, save_result, omit_commit, control):
    exe = _build(tmp_path, "gen3", GEN3_TRADE_C,
                 defines=[f"-DSAVE_RESULT={save_result}", f"-DOMIT_COMMIT={omit_commit}",
                          f"-DCONTROL={control}"])
    _run(exe)


GEN3_PANEL_C = r'''#include "panel_producer.h"
#include <string.h>
#ifdef W16
#define TERM_LAST(row) do { (row)[30]=0xff; (row)[31]=0xff; } while (0)
#define SPEC slink_binding_gen5_pk5.text
#else
#define TERM_LAST(row) do { (row)[31]=0xff; } while (0)
#define SPEC slink_binding_gen3_pk3.text
#endif
static int safe=1, starts, status;
static const SlinkInfoV2 *owned;
static int can_open(void *p) { (void)p;return safe; }
static int start(void *p,const SlinkInfoV2 *i) { (void)p;starts++;owned=i;return 1; }
static int poll(void *p,uint8_t *result) { (void)p;*result=0x7f;return status; }
int main(void) {
  SlinkPanelProducer s={0};SlinkMailboxV2 m={0};SlinkInfoV2 i={0};
  SlinkPanelEngine e={0,&SPEC,can_open,start,poll};
  m.session_epoch=i.session_epoch=7;m.seq=i.request_seq=1;
  m.opcode=SLINK_OP_SHOW_INFO;i.lines=1;i.enable=1;
  memset(i.text,0xff,sizeof(i.text));i.text[0][0]=0xbb;
  slink_panel_service(&s,&m,&i,&e,0);
  if (starts!=1 || m.status!=SLINK_ST_OK || m.ack_seq!=1 || i.state!=1 || i.drawn_seq) return 1;
  i.text[0][0]=0xcc;
  if (owned->text[0][0]!=0xbb) return 2;
  status=1;slink_panel_service(&s,&m,&i,&e,0);
  if (i.state!=2 || i.drawn_seq!=1 || i.closed_seq) return 3;
  m.seq=2;m.opcode=SLINK_OP_SHOW_INFO;
  slink_panel_service(&s,&m,&i,&e,0);
  if (starts!=1 || m.status!=SLINK_ST_FAIL || !s.active) return 4;
  status=2;slink_panel_service(&s,&m,&i,&e,0);
  if (s.active || i.state || i.closed_seq!=1 || i.result!=0x7f) return 5;
  /* Unterminated text is rejected before any engine lock or window. */
  i.request_seq=m.seq=3;m.opcode=SLINK_OP_SHOW_INFO;
  memset(i.text[0],0xbb,32);status=0;
  slink_panel_service(&s,&m,&i,&e,0);
  if (starts!=1 || m.status!=SLINK_ST_FAIL || s.active) return 6;
  TERM_LAST(i.text[0]);m.seq=i.request_seq=4;m.opcode=SLINK_OP_SHOW_INFO;safe=0;
  slink_panel_service(&s,&m,&i,&e,0);
  if (starts!=1 || s.active) return 7;
  safe=1;m.seq=i.request_seq=5;m.opcode=SLINK_OP_SHOW_INFO;
  slink_panel_service(&s,&m,&i,&e,0);
  i.session_epoch=m.session_epoch=8;i.state=1;i.drawn_seq=0;i.closed_seq=0;
  status=2;slink_panel_service(&s,&m,&i,&e,0);
  if (s.active || i.drawn_seq || i.closed_seq || i.state!=1) return 8;
  /* Menu opens current host stage, never consumes somebody else's mailbox. */
  i.state=0;status=0;m.opcode=SLINK_OP_TRADE_STATUS;m.seq=99;
  slink_panel_service(&s,&m,&i,&e,1);
  if (s.active || starts!=2 || m.opcode!=SLINK_OP_TRADE_STATUS) return 9;
  m.opcode=0;slink_panel_service(&s,&m,&i,&e,1);
  if (!s.active || starts!=3 || m.seq!=99 || m.opcode) return 10;
  return 0;
}
'''


@pytest.mark.parametrize("define", [[], ["-DW16"]], ids=["gen3-ff-8bit", "gen5-ffff-16bit"])
def test_panel_ack_is_not_drawn_and_text_is_owned_until_close(tmp_path, define):
    _run(_build(tmp_path, "panel", GEN3_PANEL_C, defines=define))


PANEL_TEXT_C = r'''#include "panel_producer.h"
#include <string.h>
#include <stdio.h>
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)
static int panel_ok(const SlinkTextSpec *t, const uint8_t *row0) {
  SlinkInfoV2 i; memset(&i,0xAB,sizeof i);
  i.session_epoch=7;i.request_seq=1;i.enable=1;i.lines=1;
  memset(i.text,0xFF,sizeof i.text);
  memcpy(i.text[0],row0,32);
  return slink_panel_valid(&i,7,t);
}
int main(void) {
  const SlinkTextSpec *g3=&slink_binding_gen3_pk3.text,*g4=&slink_binding_gen4_pk4.text,*g5=&slink_binding_gen5_pk5.text;
  CHECK(g3->width==1 && g3->terminator==0xFF && g3->charset==SLINK_CHARSET_GEN3);
  CHECK(g4->width==2 && g4->terminator==0xFFFF && g4->charset==SLINK_CHARSET_GEN4);
  CHECK(g5->width==2 && g5->terminator==0xFFFF && g5->charset==SLINK_CHARSET_GEN5);
  uint8_t row[32];
  /* 8-bit: a lone 0xFF terminates; 0xFFFF terminator absent in a Gen 3 row is irrelevant. */
  memset(row,0xBB,32);row[5]=0xFF;
  CHECK(panel_ok(g3,row)==1);
  /* the same row is NOT terminated for a 16-bit spec: (0xBB,0xFF) / (0xFF,0xBB) are not 0xFFFF */
  CHECK(panel_ok(g5,row)==0);
  memset(row,0xBB,32);row[5]=0xFF;row[6]=0xFF;       /* straddles units 2/3: units (BB,FF)(FF,BB) */
  CHECK(panel_ok(g5,row)==0);
  memset(row,0xBB,32);row[4]=0xFF;row[5]=0xFF;       /* aligned unit 2 */
  CHECK(panel_ok(g5,row)==1);
  memset(row,0x41,32);                                /* no terminator at all */
  CHECK(panel_ok(g3,row)==0 && panel_ok(g5,row)==0);
  memset(row,0x41,32);row[30]=0xFF;row[31]=0xFF;      /* terminator in the last unit only */
  CHECK(panel_ok(g5,row)==1);
  CHECK(slink_text_terminator_index(row,32,g5)==15);
  SlinkTextSpec bad={3,0,0xFF};
  CHECK(slink_text_terminator_index(row,32,&bad)==-1 && slink_text_terminator_index(row,32,0)==-1);
  /* Bounded copy: capacity INCLUDES the terminator unit, both widths. */
  uint8_t src[32],out[48];
  memset(src,0xBB,32);
  memset(out,0xCC,48);
  slink_copy_text_bounded(out,20,src,10,g3);
  CHECK(out[9]==0xBB && out[10]==0xFF && out[20]==0xCC);
  slink_copy_text_bounded(out,8,src,10,g3);
  CHECK(out[6]==0xBB && out[7]==0xFF);
  memset(out,0xCC,48);memset(src,0x41,32);
  slink_copy_text_bounded(out,12,src,32,g5);          /* 6 units cap: 5 chars + terminator */
  CHECK(out[8]==0x41 && out[9]==0x41 && out[10]==0xFF && out[11]==0xFF && out[12]==0xCC);
  memset(out,0xCC,48);
  src[4]=0xFF;src[5]=0xFF;                            /* source terminator at unit 2 */
  slink_copy_text_bounded(out,20,src,32,g5);
  CHECK(out[4]==0xFF && out[5]==0xFF && out[6]==0xCC);
  return 0;
}
'''


def test_panel_text_terminator_comes_from_the_binding(tmp_path):
    _run(_build(tmp_path, "paneltext", PANEL_TEXT_C))


SOUND_C = r'''#include "sound_producer.h"
static int effects,fanfare,last;
static int effect(void *p,uint16_t song) { (void)p;effects++;last=song;return 1; }
static int music(void *p,uint16_t song) { (void)p;fanfare++;last=song;return 1; }
int main(void) {
  SlinkMailboxV2 m={0};SlinkSoundEngine e={0,347,effect,music};
  m.session_epoch=7;m.seq=1;m.opcode=19;m.args[0]=25;
  slink_sound_service(&m,&e,0,7);
  if (effects!=1 || fanfare || last!=25 || m.status!=2 || m.ack_seq!=1 || m.opcode) return 1;
  m.seq=2;m.opcode=9;m.args[0]=0x2d;m.args[1]=1;
  slink_sound_service(&m,&e,0,7);
  if (effects!=1 || fanfare!=1 || last!=301 || m.status!=2 || m.ack_seq!=2) return 2;
  m.seq=3;m.opcode=19;m.args[0]=0x5b; /* ID347 is first outside table */
  slink_sound_service(&m,&e,0,7);
  if (effects!=1 || fanfare!=1 || m.status!=3) return 3;
  m.seq=4;m.opcode=19;m.args[0]=25;m.args[1]=0;m.session_epoch=0;
  slink_sound_service(&m,&e,0,7);
  if (effects!=1 || m.reason!=SLINK_REASON_CLIENT_TOO_OLD) return 4;
  m.seq=5;m.opcode=19;m.session_epoch=7;
  slink_sound_service(&m,&e,1,7);
  if (effects!=1 || m.status!=3) return 5;
  m.seq=6;m.opcode=19;m.session_epoch=8;
  slink_sound_service(&m,&e,0,7);
  if (effects!=1 || fanfare!=1 || m.status!=3 || m.reason!=SLINK_REASON_IDENTITY) return 7;
  m.opcode=29;slink_sound_service(&m,&e,0,7);
  if (m.opcode!=29 || effects!=1) return 6;
  return 0;
}
'''


def test_native_sound_validates_id_epoch_and_ui_ownership(tmp_path):
    _run(_build(tmp_path, "sound", SOUND_C))


# --------------------------------------------------------------------------- ABI parity + bindings

ABI_STRUCT_C = r'''#include <stdio.h>
#include "abi.h"
#define P(n) printf(#n "=%lu\n",(unsigned long)(n))
int main(void) {
  P(sizeof(SlinkMailboxV2));P(offsetof(SlinkMailboxV2,args));P(offsetof(SlinkMailboxV2,result));
  P(offsetof(SlinkMailboxV2,capabilities));P(offsetof(SlinkMailboxV2,session_epoch));P(offsetof(SlinkMailboxV2,producer_phase));
  P(sizeof(SlinkTradeWitnessV2));P(offsetof(SlinkTradeWitnessV2,revision));P(offsetof(SlinkTradeWitnessV2,milestones));
  P(offsetof(SlinkTradeWitnessV2,milestone_seq));P(offsetof(SlinkTradeWitnessV2,final_result));P(offsetof(SlinkTradeWitnessV2,milestone_frame));
  P(offsetof(SlinkTradeWitnessV2,old_pid));P(offsetof(SlinkTradeWitnessV2,received_otid));
  P(sizeof(SlinkInfoV2));P(offsetof(SlinkInfoV2,text));P(offsetof(SlinkInfoV2,closed_seq));P(sizeof(SlinkControlV2));
  @@BODY@@
  return 0;
}
'''


def _abi_names(path):
    text = _strip_comments(path.read_text())
    names = set(re.findall(r"#\s*define\s+(SLINK_[A-Z0-9_]+)\b", text))
    names |= set(re.findall(r"\b(SLINK_[A-Z0-9_]+)\s*=", text))
    return {n for n in names if not n.endswith("_H")}


def _abi_values(tmp, name, include, names):
    body = "\n  ".join(f"P({n});" for n in sorted(names))
    out = _run(_build(tmp, name, ABI_STRUCT_C.replace("@@BODY@@", body), includes=(include,)))
    return dict(line.split("=") for line in out.split())


# Names present in only one ABI header. Pinned so a new/removed name is a deliberate, reviewed change.
GEN3_ONLY = {
    "SLINK_CALL_COOLDOWN_FRAMES", "SLINK_CALL_RECORD_OFFSET", "SLINK_CALL_WITNESS_OFFSET",
    "SLINK_CALL_EMPTY", "SLINK_CALL_ARMED", "SLINK_CALL_DELIVERED", "SLINK_CALL_REFUSED",
    "SLINK_CALL_COMPLETE", "SLINK_REASON_CALL_BUSY", "SLINK_REASON_CALL_UNAVAILABLE",
    "SLINK_REASON_CALL_COOLDOWN",
}
NDS_ONLY = {
    "SLINK_MAX_RECORD", "SLINK_NDS_STAGE_LAYOUT", "SLINK_RESERVED_OFFSET", "SLINK_SAVE_PENDING",
    "SLINK_TITLE_OFFSET", "SLINK_TITLE_SIZE",
    "SLINK_SAVEPOLL_PENDING", "SLINK_SAVEPOLL_OK", "SLINK_SAVEPOLL_FAIL", "SLINK_STAGE_RAW_ENCRYPTED",
}
# Shared names whose VALUE deliberately differs. Anything else that drifts fails the identical-subset test.
DIVERGED = {"SLINK_ABI_VERSION": ("2", "3")}


def test_abi_identical_subset_covers_every_shared_name(tmp_path):
    # Struct layouts plus EVERY name defined by both headers (auto-collected, not curated) are identical,
    # except the explicit DIVERGED set; name sets that exist in only one header are pinned.
    gen3_names, nds_names = _abi_names(GEN3 / "abi.h"), _abi_names(COMMON / "abi.h")
    assert gen3_names - nds_names == GEN3_ONLY
    assert nds_names - gen3_names == NDS_ONLY
    shared = gen3_names & nds_names
    gen3 = _abi_values(tmp_path, "t3", GEN3, shared)
    nds = _abi_values(tmp_path, "tn", COMMON, shared)
    assert set(gen3) == set(nds) and len(shared) > 80
    drift = {k: (gen3[k], nds[k]) for k in gen3 if gen3[k] != nds[k]}
    assert drift == DIVERGED


DIVERGED_C = r'''#include <stdio.h>
#include "abi.h"
#define P(n) printf(#n "=%ld\n",(long)(n))
int main(void) {
  P(SLINK_ABI_VERSION);P(SLINK_SAVE_OK);P(SLINK_SAVE_PENDING);P(SLINK_SAVE_FAILED);
  P(SLINK_SAVEPOLL_PENDING);P(SLINK_SAVEPOLL_OK);P(SLINK_SAVEPOLL_FAIL);
  return 0;
}
'''


def test_abi_deliberately_diverged_subset(tmp_path):
    out = dict(line.split("=") for line in _run(_build(tmp_path, "div", DIVERGED_C)).split())
    assert out == {
        "SLINK_ABI_VERSION": "3", "SLINK_SAVE_OK": "1", "SLINK_SAVE_PENDING": "2",
        "SLINK_SAVE_FAILED": "255", "SLINK_SAVEPOLL_PENDING": "0", "SLINK_SAVEPOLL_OK": "1",
        "SLINK_SAVEPOLL_FAIL": "-1",
    }
    # the Gen 3 reader accepts save_status only as 1 or 255 with PRE_SAVE_OK set (lua/gen3/native.lua:631),
    # so the NDS PENDING value must stay outside that set and the version must differ
    assert out["SLINK_SAVE_PENDING"] not in ("1", "255")


def test_nds_and_gen3_abi_cannot_share_a_translation_unit(tmp_path):
    src = tmp_path / "both.c"
    src.write_text('#include "trade_targets/abi.h"\n#include "nds/common/abi.h"\nint main(void){return 0;}\n')
    done = subprocess.run([_gcc(), "-std=c11", "-I", str(ROOT / "patch/src"), str(src), "-o",
                           str(tmp_path / "both.exe")], capture_output=True, text=True, timeout=30)
    assert done.returncode != 0 and "must not share" in done.stderr


BINDINGS_C = r'''#include "record_binding.h"
#include <stdio.h>
#include <string.h>
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)
static int rd(void *p,const uint8_t *r,uint16_t n,uint16_t off,uint32_t *out) {
  (void)p; if ((unsigned)off+4>n) return 0;
  *out=slink_rb_le32(r+off)^0xFFFFFFFFu; return 1;
}
static int vf_ok(void *p,const uint8_t *r,uint16_t n) { (void)p;(void)r;(void)n; return 1; }
static int vf_bad(void *p,const uint8_t *r,uint16_t n) { (void)p;(void)r;(void)n; return 0; }
int main(void) {
  const SlinkRecordBinding *g3=&slink_binding_gen3_pk3,*g4=&slink_binding_gen4_pk4,*g5=&slink_binding_gen5_pk5;
  CHECK(slink_binding_ok(g3) && slink_binding_ok(g4) && slink_binding_ok(g5));
  CHECK(g3->id==SLINK_BIND_GEN3_PK3 && g3->stored_len==80 && g3->party_len==100 && g3->extra_len_per_slot==0);
  CHECK(!(g3->flags&SLINK_RB_OTID_DECODED) && !(g3->flags&SLINK_RB_COMMIT_MUTATES_INPUT));
  CHECK(g4->id==SLINK_BIND_GEN4_PK4 && g4->stored_len==0x88 && g4->party_len==0xEC && g4->extra_len_per_slot==5);
  CHECK((g4->flags&SLINK_RB_RAW_ENCRYPTED) && (g4->flags&SLINK_RB_OTID_DECODED) && g4->otid_logical_off==0x0C);
  CHECK(g4->flags&SLINK_RB_COMMIT_MUTATES_INPUT);
  CHECK(g5->id==SLINK_BIND_GEN5_PK5 && g5->stored_len==0x88 && g5->party_len==0xDC && g5->otid_logical_off==0x0C);
  CHECK(g3->max_len==SLINK_MAX_RECORD && g4->max_len==SLINK_MAX_RECORD && g5->party_len<=SLINK_MAX_RECORD);
  /* per-arm staging length: TRADE defaults to party_len, BOX is the stored prefix */
  CHECK(slink_binding_stage_len(g3,SLINK_STAGE_OP_TRADE)==100 && slink_binding_stage_len(g3,SLINK_STAGE_OP_BOX)==80);
  CHECK(slink_binding_stage_len(g4,SLINK_STAGE_OP_TRADE)==0xEC && slink_binding_stage_len(g4,SLINK_STAGE_OP_BOX)==0x88);
  CHECK(slink_binding_stage_len(g5,SLINK_STAGE_OP_TRADE)==0xDC && slink_binding_stage_len(g5,SLINK_STAGE_OP_BOX)==0x88);
  SlinkRecordBinding custom=*g5;custom.trade_stage_len=0x88;
  CHECK(slink_binding_ok(&custom) && slink_binding_stage_len(&custom,SLINK_STAGE_OP_TRADE)==0x88);
  /* PK3: plaintext PID +0 / OT +4, no decoder needed. */
  uint8_t rec[SLINK_MAX_RECORD];SlinkIdentity id;memset(rec,0,sizeof rec);
  rec[0]=0x78;rec[1]=0x56;rec[2]=0x34;rec[3]=0x12;rec[4]=1;rec[5]=2;rec[6]=3;rec[7]=0x80;
  CHECK(g3->identity(0,rec,100,&id) && id.pid==0x12345678u && id.otid==0x80030201u);
  CHECK(!g3->identity(0,rec,7,&id));
  CHECK(g3->validate(0,rec,100) && g3->validate(0,rec,80) && !g3->validate(0,rec,99) && !g3->validate(0,rec,101));
  /* PK4/PK5: OT lives in the decoded body; no decoder => fail closed. */
  SlinkDecoder d={0,rd,vf_ok},nover={0,rd,0},noread={0,0,vf_ok},badver={0,rd,vf_bad};
  rec[0x0C]=0x0F;rec[0x0D]=0xF0;rec[0x0E]=0xFF;rec[0x0F]=0xFF;
  CHECK(g4->identity(&d,rec,0xEC,&id) && id.pid==0x12345678u && id.otid==0x0FF0u);
  CHECK(g5->identity(&d,rec,0xDC,&id) && id.pid==0x12345678u && id.otid==0x0FF0u);
  CHECK(!g4->identity(0,rec,0xEC,&id) && !g5->identity(0,rec,0xDC,&id));
  CHECK(!g4->identity(&noread,rec,0xEC,&id));
  /* validate: exact record forms only, and FAIL CLOSED without a decoder or without verify */
  CHECK(g4->validate(&d,rec,0xEC) && g4->validate(&d,rec,0x88) && !g4->validate(&d,rec,0xDC) && !g4->validate(&d,rec,0x89));
  CHECK(g5->validate(&d,rec,0xDC) && g5->validate(&d,rec,0x88) && !g5->validate(&d,rec,0xEC) && !g5->validate(&d,rec,100));
  CHECK(!g4->validate(0,rec,0xEC) && !g5->validate(0,rec,0xDC));
  CHECK(!g4->validate(&nover,rec,0xEC) && !g5->validate(&nover,rec,0xDC));   /* read_u32 present, verify absent */
  CHECK(!g4->validate(&badver,rec,0xEC) && !g5->validate(&badver,rec,0xDC));
  SlinkIdentity a={1,2},b={1,2},c={1,3},e={4,2};
  CHECK(g4->same_identity(&a,&b) && !g4->same_identity(&a,&c) && !g4->same_identity(&a,&e));
  /* structural refusals */
  SlinkRecordBinding bad=*g5;bad.party_len=0;CHECK(!slink_binding_ok(&bad));
  bad=*g5;bad.max_len=SLINK_MAX_RECORD+1u;CHECK(!slink_binding_ok(&bad));
  bad=*g5;bad.stored_len=bad.party_len+1u;CHECK(!slink_binding_ok(&bad));
  bad=*g5;bad.trade_stage_len=SLINK_MAX_RECORD+1u;CHECK(!slink_binding_ok(&bad));
  bad=*g5;bad.validate=0;CHECK(!slink_binding_ok(&bad));
  bad=*g5;bad.text.width=3;CHECK(!slink_binding_ok(&bad));
  bad=*g5;bad.flags=SLINK_RB_OTID_DECODED;CHECK(!slink_binding_ok(&bad));
  CHECK(!slink_binding_ok(0));
  return 0;
}
'''


def test_reference_bindings(tmp_path):
    _run(_build(tmp_path, "bindings", BINDINGS_C))


# --------------------------------------------------------------------------- (b) PK4 / PK5 lifecycle

PK45_C = r'''#include "trade_producer.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)
#define OLD_PID 11u
#define OLD_OT 22u
#define NEW_PID 0xA1B2C3D4u
#define NEW_OT 0x8BADF00Du
enum { SP_PEND = SLINK_SAVEPOLL_PENDING, SP_OK = SLINK_SAVEPOLL_OK, SP_BAD = SLINK_SAVEPOLL_FAIL };
static const SlinkRecordBinding *B;
static SlinkRecordBinding custom;
static SlinkTradeProducer s; static SlinkMailboxV2 m; static SlinkTradeWitnessV2 w;
static SlinkRecordStageV1 stage; static SlinkTradeEngine e; static SlinkDecoder dec;
static uint8_t rec[SLINK_MAX_RECORD], last_rec[SLINK_MAX_RECORD];
static uint16_t last_len;
static int pre_result, scene_result, begin_result, script[16], script_n;
static int polls, begins, starts, old_present, safe_flag, verify_ok, decodes, misaligned, recv_ok, bad_begin_state, pre_polls;
static uint32_t recv_pid, recv_ot, frame, frame_step;
static int mutate_arg, start_ret;
static const uint8_t *arg_ptr;
static uint8_t entry_rec[2][SLINK_MAX_RECORD];

static int safe(void *p) { (void)p; return safe_flag; }
static int locate(void *p,uint32_t pid,uint32_t ot) { (void)p; return old_present && pid==OLD_PID && ot==OLD_OT ? 0 : -1; }
static int pre_start(void *p) { (void)p; return 1; }
static int pre_poll(void *p) { (void)p; pre_polls++; return pre_result; }
static int scene_start(void *p,unsigned slot,const uint8_t *r,uint16_t n) {
  (void)p;(void)slot;starts++;
  if (((uintptr_t)r & 3u) != 0) misaligned = 1;
  arg_ptr = r;
  last_len = n; memset(last_rec,0xCD,sizeof last_rec); memcpy(last_rec,r,n);
  if (starts <= 2) memcpy(entry_rec[starts-1],r,n);   /* what the engine saw on entry */
  if (mutate_arg) { uint8_t *scribble=(uint8_t *)r; for (unsigned k=0;k<n;k++) scribble[k]^=0xFFu; }
  return start_ret;
}
static int scene_poll(void *p) { (void)p; return scene_result; }
static int save_begin(void *p) {
  (void)p; begins++;
  /* the engine sees a committed+evolved scene and no final result yet */
  if (w.milestones != 7u || w.final_result != SLINK_TRADE_PENDING || (w.revision & 1u) || !w.revision) bad_begin_state = 1;
  return begin_result;
}
static int save_poll(void *p) { (void)p; int i = polls++; return script[i < script_n ? i : script_n - 1]; }
static int received(void *p,unsigned slot,uint32_t *pid,uint32_t *ot) { (void)p;(void)slot; if (!recv_ok) return 0; *pid=recv_pid;*ot=recv_ot;return 1; }
static uint32_t clk(void *p) { (void)p; frame += frame_step; return frame; }
static int ignore_pid(const SlinkIdentity *a,const SlinkIdentity *b) { return a->otid==b->otid; }
static unsigned SL(void) { return slink_binding_stage_len(B,SLINK_STAGE_OP_TRADE); }
static int dec_read(void *p,const uint8_t *r,uint16_t n,uint16_t off,uint32_t *out) {
  (void)p; decodes++;
  if ((unsigned)off + 4u > n) return 0;
  *out = 0; for (unsigned k = 0; k < 4; k++) *out |= (uint32_t)(r[off+k] ^ 0xA5u) << (8*k);
  return 1;
}
static int dec_verify(void *p,const uint8_t *r,uint16_t n) { (void)p;(void)n; return verify_ok && r[6]==0x5A; }
static void word(uint8_t *p,uint32_t v) { memcpy(p,&v,4); }

static void build(void) {
  unsigned n = B->party_len;
  memset(rec,0,sizeof rec);
  for (unsigned i = 0; i < n; i++) rec[i] = (uint8_t)(i*7u+3u);
  for (unsigned i = 0; i < 4; i++) { rec[i]=(uint8_t)(NEW_PID>>(8*i)); rec[0x0C+i]=(uint8_t)((NEW_OT>>(8*i))^0xA5u); }
  rec[6] = 0x5A;
  memset(&stage,0xEE,sizeof stage);
  stage.layout_version=SLINK_NDS_STAGE_LAYOUT;stage.binding_id=B->id;stage.generation=B->generation;
  stage.flags=SLINK_STAGE_RAW_ENCRYPTED;stage.stage_len=(uint16_t)SL();
  stage.claimed_pid=NEW_PID;stage.claimed_otid=NEW_OT;
  memcpy(stage.record,rec,SL());
}
static void reset(void) {
  memset(&s,0,sizeof s);memset(&m,0,sizeof m);memset(&w,0,sizeof w);memset(&e,0,sizeof e);
  memset(last_rec,0,sizeof last_rec);last_len=0;
  pre_result=0;scene_result=0;begin_result=1;script[0]=SP_OK;script_n=1;
  polls=begins=starts=decodes=misaligned=bad_begin_state=pre_polls=0;frame=0;frame_step=1;
  mutate_arg=0;start_ret=1;arg_ptr=0;memset(entry_rec,0,sizeof entry_rec);B=&BIND;
  old_present=1;safe_flag=1;verify_ok=1;recv_ok=1;recv_pid=NEW_PID;recv_ot=NEW_OT;
  dec.context=0;dec.read_u32=dec_read;dec.verify=dec_verify;
  e.save_timeout_frames=1000000u;e.pre_save_timeout_frames=0u;e.binding=B;e.decoder=&dec;e.safe_field=safe;e.locate=locate;e.start_pre_save=pre_start;e.poll_pre_save=pre_poll;
  e.start_scene=scene_start;e.poll_scene=scene_poll;e.post_save_begin=save_begin;e.post_save_poll=save_poll;
  e.received_key=received;e.frame=clk;
  build();
}
static void svc(void) { slink_trade_service(&s,&m,&w,&stage,&e); }
static void send_prepare(uint32_t epoch,uint16_t seq) {
  m.session_epoch=epoch;m.seq=seq;m.opcode=SLINK_OP_TRADE_PREPARE;
  word(m.args+4,OLD_PID);word(m.args+8,OLD_OT);word(m.args+12,8);m.args[16]=9;
}
static int prep(void) {
  send_prepare(7,1);svc();
  CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE && w.visit_flags==SLINK_VISIT_ACCEPTED && !w.milestones);
  pre_result=1;svc();
  CHECK(m.producer_phase==SLINK_PHASE_READY && m.status==SLINK_ST_OK && m.ack_seq==1 && !m.opcode);
  CHECK(w.milestones==(1u<<SLINK_PRE_SAVE_OK));
  return 0;
}
static void scene(uint16_t seq) { m.seq=seq;m.opcode=SLINK_OP_TRADE_SCENE;svc(); }
/* A save that is not finished must look unfinished on every observable. */
static int still_saving(void) {
  CHECK(m.producer_phase==SLINK_PHASE_SCENE && s.phase==TP_SCENE);
  CHECK(!(w.milestones&(1u<<SLINK_POST_SAVE_OK)) && !(w.milestones&(1u<<SLINK_FINAL_RESULT)));
  CHECK(w.final_result==SLINK_TRADE_PENDING && w.save_status==SLINK_SAVE_PENDING);
  CHECK(!slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
  return 0;
}
static int refused_unchanged(void) {
  CHECK(starts==0 && begins==0 && polls==0 && last_len==0);
  CHECK(w.final_result==SLINK_TRADE_UNCHANGED);
  CHECK(w.milestones==((1u<<SLINK_PRE_SAVE_OK)|(1u<<SLINK_FINAL_RESULT)));
  CHECK(m.status==SLINK_ST_FAIL && m.producer_phase==SLINK_PHASE_DONE);
  CHECK(!slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
  return 0;
}

static int sc_happy(void) {
  reset(); if (prep()) return 1;
  scene(2);
  CHECK(starts==1 && decodes>0 && !misaligned);
  /* full-record preservation: exactly party_len bytes, verbatim, nothing truncated at 100 */
  CHECK(last_len==SL() && memcmp(last_rec,rec,SL())==0);
  CHECK(s.incoming_len==SL() && memcmp(s.incoming,rec,SL())==0);
  for (unsigned i = SL(); i < SLINK_MAX_RECORD; i++) CHECK(s.incoming[i]==0);
  CHECK(m.producer_phase==SLINK_PHASE_SCENE && m.status==SLINK_ST_BUSY);
  CHECK(slink_trade_commit_entered(&s,&w,0,&e));
  CHECK(w.milestones==3u && w.milestone_seq[SLINK_COMMIT_ENTERED]==2);
  /* scene returns; native save is asynchronous: 6 PENDING polls, then OK */
  script_n=7;for (int i=0;i<6;i++) script[i]=SP_PEND;script[6]=SP_OK;
  scene_result=1;svc();
  CHECK(begins==1 && polls==1 && !bad_begin_state);
  CHECK(w.milestones==7u);               /* PRE_SAVE | COMMIT | EVOLUTION, nothing else */
  CHECK(m.status==SLINK_ST_BUSY);         /* the SCENE command is not acknowledged yet */
  if (still_saving()) return 1;
  svc();CHECK(polls==2);if (still_saving()) return 1;
  m.seq=3;m.opcode=SLINK_OP_TRADE_WITHDRAW;svc();   /* too late while saving */
  CHECK(m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_WITHDRAW_TOO_LATE && polls==3);
  if (still_saving()) return 1;
  m.seq=2;m.opcode=SLINK_OP_TRADE_SCENE;svc();      /* duplicate SCENE: silent, no restart */
  CHECK(starts==1 && begins==1 && polls==4 && m.opcode==SLINK_OP_TRADE_SCENE);
  m.seq=5;m.opcode=SLINK_OP_TRADE_SCENE;svc();      /* second SCENE: refused */
  CHECK(starts==1 && begins==1 && polls==5 && m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_IDENTITY);
  if (still_saving()) return 1;
  m.seq=2;m.opcode=0;svc();CHECK(polls==6);if (still_saving()) return 1;
  svc();                                             /* seventh poll: OK */
  CHECK(polls==7 && begins==1);
  CHECK(w.final_result==SLINK_TRADE_COMMITTED && w.save_status==SLINK_SAVE_OK && w.milestones==0x1Fu);
  CHECK(m.status==SLINK_ST_OK && m.ack_seq==2 && m.producer_phase==SLINK_PHASE_DONE);
  CHECK(slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
  CHECK(w.received_pid==NEW_PID && w.received_otid==NEW_OT);
  CHECK(w.milestone_frame[SLINK_COMMIT_ENTERED] < w.milestone_frame[SLINK_SCENE_EVOLUTION_DONE]
     && w.milestone_frame[SLINK_SCENE_EVOLUTION_DONE] < w.milestone_frame[SLINK_POST_SAVE_OK]
     && w.milestone_frame[SLINK_POST_SAVE_OK] < w.milestone_frame[SLINK_FINAL_RESULT]);
  CHECK(!(w.revision & 1u) && w.revision);
  /* duplicate SCENE after DONE is an idempotent ACK, never a second scene/save */
  m.seq=2;m.opcode=SLINK_OP_TRADE_SCENE;svc();
  CHECK(m.status==SLINK_ST_OK && starts==1 && begins==1);
  /* the finished visit's identity cannot be PREPAREd again */
  send_prepare(7,9);svc();
  CHECK(m.status==SLINK_ST_FAIL && m.reason==12 && m.producer_phase==SLINK_PHASE_DONE && starts==1);
  /* a NEW visit may begin after DONE */
  send_prepare(7,10);word(m.args+12,77);m.args[16]=3;svc();
  CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE && w.visit_id==77);
  return 0;
}

static int sc_refuse(int var) {
  reset(); if (prep()) return 1;
  switch (var) {
    case 0: stage.stage_len=(uint16_t)(SL()-1u); break;     /* truncated */
    case 1: stage.stage_len=100; break;                              /* the Gen 3 size */
    case 2: stage.stage_len=0; break;
    case 3: stage.stage_len=(uint16_t)(SL()+1u); break;     /* oversize by one */
    case 4: stage.stage_len=SLINK_MAX_RECORD; break;
    case 5: stage.stage_len=0xFFFF; break;
    case 6: stage.binding_id=(uint16_t)(B->id+1u); break;
    case 7: stage.generation=(uint8_t)(B->generation+1u); break;
    case 8: stage.flags=0; break;
    case 9: stage.layout_version=2; break;
    case 10: stage.claimed_otid+=1u; break;                          /* wrong identity: OT */
    case 11: stage.claimed_pid^=1u; break;                           /* wrong identity: PID */
    case 12: e.decoder=0; break;                                     /* identity fails closed */
    case 13: verify_ok=0; break;                                     /* engine integrity check */
    case 14: stage.record[0]^=1u; break;                             /* record PID != claim */
    case 15: stage.record[0x0C]^=1u; break;                          /* decoded OT != claim */
    case 16: stage.flags=SLINK_STAGE_RAW_ENCRYPTED|0x80u; break;      /* unknown flag bit */
    case 17: stage.flags=SLINK_STAGE_RAW_ENCRYPTED|0x02u; break;
    case 18: dec.verify=0; break;                                     /* decoder without verify: fail closed */
    default: return 2;
  }
  scene(2);
  return refused_unchanged();
}

static int sc_recv(int var) {
  reset(); if (prep()) return 1;
  scene(2);CHECK(starts==1);
  CHECK(slink_trade_commit_entered(&s,&w,0,&e));
  if (var==3) {                       /* relaxed same_identity (ignores PID): witness must publish OBSERVED */
    custom=*B;custom.same_identity=ignore_pid;B=&custom;e.binding=B;recv_pid^=0x01010101u;
    scene_result=1;svc();
    CHECK(w.final_result==SLINK_TRADE_COMMITTED && m.producer_phase==SLINK_PHASE_DONE);
    CHECK(w.received_pid==recv_pid && w.received_pid!=NEW_PID && w.received_otid==NEW_OT);
    CHECK(!slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
    CHECK(slink_trade_success_is_durable(&w,1,2,recv_pid,NEW_OT));
    return 0;
  }
  if (var==0) recv_ot^=1u; else if (var==1) recv_pid^=1u; else recv_ok=0;
  scene_result=1;svc();
  CHECK(begins==0 && polls==0);
  CHECK(w.final_result==SLINK_TRADE_UNCERTAIN && m.producer_phase==SLINK_PHASE_UNCERTAIN);
  CHECK(!(w.milestones&(1u<<SLINK_SCENE_EVOLUTION_DONE)) && !(w.milestones&(1u<<SLINK_POST_SAVE_OK)));
  CHECK(!slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT) && m.status!=SLINK_ST_OK);
  return 0;
}

static int sc_savefail(int var) {
  reset(); if (prep()) return 1;
  scene(2);CHECK(slink_trade_commit_entered(&s,&w,0,&e));
  switch (var) {
    case 0: script_n=3;script[0]=SP_PEND;script[1]=SP_PEND;script[2]=SP_BAD; break;
    case 1: begin_result=0; break;                                   /* save refused to start */
    case 2: script_n=1;script[0]=7; break;                           /* garbage poll: fail closed */
    case 3: script_n=1;script[0]=-5; break;
    case 4: script_n=1;script[0]=0x7FFF; break;
    case 5: script_n=1;script[0]=SP_PEND;e.save_timeout_frames=50;frame_step=0;frame=100; break; /* PENDING forever */
    default: return 2;
  }
  scene_result=1;svc();
  if (var==5) {                                      /* elapsed 0, 50 (== bound), then 51 (> bound) */
    if (still_saving()) return 1;
    frame=150;svc();if (still_saving()) return 1;
    frame=151;svc();
  }
  if (var==0) { if (still_saving()) return 1; svc(); if (still_saving()) return 1; svc(); }
  CHECK(w.final_result==SLINK_TRADE_UNCERTAIN && m.producer_phase==SLINK_PHASE_UNCERTAIN);
  CHECK(w.save_status==SLINK_SAVE_FAILED && !(w.milestones&(1u<<SLINK_POST_SAVE_OK)));
  CHECK(m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_UNCERTAIN);
  CHECK(!slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
  CHECK(var==1 ? polls==0 : polls>=1);
  /* sticky: no second scene, save or new visit until reset */
  int p0=polls,b0=begins,s0=starts;SlinkTradeWitnessV2 terminal=w;
  m.seq=3;m.opcode=SLINK_OP_TRADE_SCENE;svc();
  CHECK(starts==s0 && begins==b0 && polls==p0 && s.phase==TP_UNCERTAIN);
  send_prepare(9,4);svc();
  CHECK(m.producer_phase==SLINK_PHASE_UNCERTAIN && starts==s0 && memcmp(&terminal,&w,sizeof w)==0);
  return 0;
}

static int sc_forever(void) {
  reset(); if (prep()) return 1;
  scene(2);CHECK(slink_trade_commit_entered(&s,&w,0,&e));
  script_n=2;script[0]=SP_PEND;script[1]=SP_PEND;     /* PENDING forever */
  scene_result=1;svc();
  for (int i = 0; i < 1000; i++) { if (still_saving()) return 1; svc(); }
  CHECK(begins==1 && polls>=1000);
  script[1]=SP_OK;svc();
  CHECK(w.final_result==SLINK_TRADE_COMMITTED && slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
  return 0;
}

static int sc_stale(int var) {
  reset();
  if (var==3) {                       /* unarmed epoch at PREPARE */
    send_prepare(0,1);svc();
    CHECK(m.status==SLINK_ST_FAIL && m.reason==12 && m.producer_phase==SLINK_PHASE_IDLE && !w.session_epoch);
    return 0;
  }
  if (prep()) return 1;
  SlinkTradeWitnessV2 before=w;
  if (var==0) { m.session_epoch=8; scene(2); }
  else if (var==1) { m.session_epoch=0; scene(2); }
  else { send_prepare(8,2); svc(); }
  CHECK(starts==0 && begins==0 && polls==0 && memcmp(&before,&w,sizeof w)==0);
  CHECK(m.status==SLINK_ST_FAIL && m.reason==12 && m.producer_phase==SLINK_PHASE_READY && w.session_epoch==7);
  return 0;
}

static int sc_dup(void) {
  reset();
  send_prepare(7,1);svc();                       /* PRE_SAVE */
  CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE && m.status==SLINK_ST_BUSY);
  svc();                                          /* same seq re-delivered: silent */
  CHECK(m.opcode==SLINK_OP_TRADE_PREPARE && m.status==SLINK_ST_BUSY);
  send_prepare(7,2);svc();                        /* another PREPARE mid-visit: refused */
  CHECK(m.status==SLINK_ST_FAIL && m.reason==12 && m.producer_phase==SLINK_PHASE_PRE_SAVE && w.visit_id==8);
  pre_result=1;m.seq=1;m.opcode=0;svc();
  CHECK(m.producer_phase==SLINK_PHASE_READY);
  send_prepare(7,1);svc();                        /* same seq + identity in READY: idempotent ACK */
  CHECK(m.status==SLINK_ST_OK && m.producer_phase==SLINK_PHASE_READY);
  send_prepare(7,3);svc();                        /* different seq in READY: refused */
  CHECK(m.status==SLINK_ST_FAIL && m.reason==12 && m.producer_phase==SLINK_PHASE_READY);
  m.seq=4;m.opcode=SLINK_OP_TRADE_STATUS;svc();   /* STATUS is read-only */
  CHECK(m.status==SLINK_ST_OK && m.producer_phase==SLINK_PHASE_READY);
  m.seq=5;m.opcode=SLINK_OP_TRADE_WITHDRAW;svc(); /* withdraw while READY: UNCHANGED, DONE */
  CHECK(w.final_result==SLINK_TRADE_UNCHANGED && m.producer_phase==SLINK_PHASE_DONE && starts==0);
  m.seq=6;m.opcode=SLINK_OP_TRADE_SCENE;svc();    /* SCENE after DONE(UNCHANGED): refused */
  CHECK(m.status==SLINK_ST_FAIL && starts==0 && begins==0);
  return 0;
}

static int sc_badbinding(int var) {
  reset();
  custom=*B;
  switch (var) {
    case 0: custom.party_len=0; break;
    case 1: custom.max_len=SLINK_MAX_RECORD+1u; break;
    case 2: e.binding=0; break;
    case 3: custom.stored_len=(uint16_t)(custom.party_len+1u); break;
    case 4: e.save_timeout_frames=0; break;                          /* the watchdog bound is mandatory */
    default: return 2;
  }
  if (var!=2) e.binding=&custom;
  send_prepare(7,1);svc();
  CHECK(m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_BAD_ARGS && m.producer_phase==SLINK_PHASE_IDLE);
  CHECK(!w.session_epoch && !w.milestones);
  return 0;
}

static int sc_mutate(int var) {
  reset();
  if (var==1) { custom=*B;custom.flags&=(uint8_t)~SLINK_RB_COMMIT_MUTATES_INPUT;B=&custom;e.binding=B; }
  else CHECK(B->flags&SLINK_RB_COMMIT_MUTATES_INPUT);
  mutate_arg=1;start_ret=0;                         /* engine scribbles on its argument, then refuses */
  if (prep()) return 1;
  scene(2);
  CHECK(starts==1 && w.final_result==SLINK_TRADE_UNCHANGED);
  CHECK(memcmp(entry_rec[0],rec,SL())==0);
  if (var==1) {                                     /* control: without the flag the engine owns the stage copy */
    CHECK(arg_ptr==s.incoming && memcmp(s.incoming,rec,SL())!=0);
    return 0;
  }
  /* must-not-alias: the engine got a scratch copy; the staged copy and the host stage are untouched */
  CHECK(arg_ptr==s.scratch && arg_ptr!=s.incoming);
  CHECK(memcmp(s.incoming,rec,SL())==0 && memcmp(stage.record,rec,SL())==0);
  CHECK(memcmp(s.scratch,rec,SL())!=0);
  /* retry the whole visit: the engine again sees the ORIGINAL bytes */
  send_prepare(7,10);word(m.args+12,77);m.args[16]=3;svc();
  CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE);
  pre_result=1;svc();CHECK(m.producer_phase==SLINK_PHASE_READY);
  scene(11);
  CHECK(starts==2 && memcmp(entry_rec[1],rec,SL())==0 && memcmp(entry_rec[0],entry_rec[1],SL())==0);
  return 0;
}

static int sc_stagelen(int var) {
  reset();
  custom=*B;custom.trade_stage_len=custom.stored_len;B=&custom;e.binding=B;build();
  CHECK(SL()==0x88u);
  if (prep()) return 1;
  if (var==1) { stage.stage_len=B->party_len; scene(2); return refused_unchanged(); }  /* party-length stage for a 0x88 arm */
  scene(2);
  CHECK(starts==1 && last_len==0x88u && memcmp(last_rec,rec,0x88u)==0 && s.incoming_len==0x88u);
  for (unsigned i = 0x88u; i < SLINK_MAX_RECORD; i++) CHECK(s.incoming[i]==0);
  return 0;
}

/* The mailbox is shared with the sound and panel producers. A command that is not
 * ours must survive a trade visit completely untouched -- not acked, not cleared,
 * no status/reason/ack_seq invented -- while the polls still run, so an in-flight
 * save keeps advancing and the watchdog still fires. */
static int sc_foreign(int var) {
  static const uint16_t foreign_op[4] = { SLINK_OP_PLAY_SE, SLINK_OP_SHOW_INFO,
                                         SLINK_OP_PLAY_FANFARE, SLINK_OP_PLAY_SE };
  if (var<0 || var>3) return 2;
  uint16_t op = foreign_op[var];
  reset();
  if (var==3) {                        /* nothing of ours in flight at all */
    m.session_epoch=7;m.seq=4;m.opcode=op;m.args[0]=0x2d;m.args[1]=0;
    svc();
    CHECK(m.opcode==op && m.seq==4 && !m.ack_seq && !m.status && !m.reason);
    CHECK(m.producer_phase==SLINK_PHASE_IDLE && s.phase==TP_IDLE);
    svc();
    CHECK(m.opcode==op && m.seq==4 && !m.ack_seq && !m.status && !m.reason);
    return 0;
  }
  e.save_timeout_frames=50u;frame_step=0;frame=0;   /* deterministic watchdog timeline */
  if (prep()) return 1;
  scene(2);CHECK(starts==1);
  CHECK(slink_trade_commit_entered(&s,&w,0,&e));
  script_n=3;for (int i=0;i<3;i++) script[i]=SP_PEND;   /* this save never completes */
  scene_result=1;svc();
  CHECK(begins==1 && polls==1);
  if (still_saving()) return 1;
  uint16_t ack=m.ack_seq,st=m.status;      /* last ACK is the PREPARE's; SCENE is still BUSY */
  CHECK(ack==1 && st==SLINK_ST_BUSY && !m.reason && m.opcode==SLINK_OP_TRADE_SCENE);
  for (unsigned i=0;i<3u;i++) {            /* elapsed 10, 20, 30: inside the bound */
    frame=10u*(i+1u);m.seq=4;m.opcode=op;m.args[0]=0x2d;m.args[1]=0;svc();
    CHECK(m.opcode==op && m.seq==4 && m.ack_seq==ack && m.status==st && !m.reason);
    CHECK(m.args[0]==0x2d && !m.args[1]);
    CHECK(polls==(int)i+2 && s.phase==TP_SCENE && m.producer_phase==SLINK_PHASE_SCENE);
    if (still_saving()) return 1;
  }
  frame=50u;m.seq=4;m.opcode=op;svc();      /* elapsed == bound: still PENDING */
  CHECK(polls==5 && m.opcode==op && m.seq==4 && m.ack_seq==ack && m.status==st);
  if (still_saving()) return 1;
  frame=51u;m.seq=4;m.opcode=op;svc();      /* elapsed > bound: the native watchdog fires */
  CHECK(polls==6 && w.final_result==SLINK_TRADE_UNCERTAIN && w.save_status==SLINK_SAVE_FAILED);
  CHECK(!(w.milestones&(1u<<SLINK_POST_SAVE_OK)) && s.phase==TP_UNCERTAIN
      && m.producer_phase==SLINK_PHASE_UNCERTAIN);
  CHECK(!slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
  /* tp_ack cannot even see it: the finished save acks the SCENE sequence, not 4 */
  CHECK(m.opcode==op && m.seq==4 && m.ack_seq==ack && m.status==st && !m.reason);
  return 0;
}

/* The pre-save leg carries no frame bound of its own: a poll that returned neither
 * 1 (saved) nor negative (refused) parked the producer in TP_PRE_SAVE forever while
 * the host's own 6000-frame budget ran out. pre_save_timeout_frames bounds that wait;
 * 0 keeps the unbounded behaviour. Nothing is mutated before the save completes, so
 * the timeout ends the visit UNCHANGED, exactly like an engine refusal. */
static int sc_presave(int var) {
  reset();
  e.pre_save_timeout_frames=var==1 ? 0u : 50u;   /* 0 = no watchdog (pre-existing behaviour) */
  frame_step=0;frame=0;                          /* deterministic clock, set by hand */
  pre_result=var==2 ? 2 : 0;                     /* never completes: waiting, or consented */
  send_prepare(7,1);svc();
  CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE && s.phase==TP_PRE_SAVE && m.status==SLINK_ST_BUSY);
  CHECK(w.visit_flags==SLINK_VISIT_ACCEPTED && !w.milestones && w.final_result==SLINK_TRADE_PENDING);
  CHECK(!m.ack_seq && !m.reason && m.opcode==SLINK_OP_TRADE_PREPARE);
  CHECK(s.pre_save_start_frame==0u && pre_polls==0);
  for (unsigned elapsed=10; elapsed<=50u; elapsed+=10u) {
    frame=elapsed;svc();
    CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE && pre_polls==(int)(elapsed/10u));
    CHECK(!m.ack_seq && !m.reason && !w.milestones && w.save_status==0);
    if (var==2) CHECK(w.visit_flags==(SLINK_VISIT_ACCEPTED|SLINK_PRE_SAVE_CONSENT));
    else CHECK(w.visit_flags==SLINK_VISIT_ACCEPTED);
  }
  if (var==1) {        /* unbounded: waited out past the host's own 6000-frame trade budget */
    for (unsigned elapsed=1000u; elapsed<=6000u; elapsed+=1000u) { frame=elapsed;svc(); }
    CHECK(s.phase==TP_PRE_SAVE && m.producer_phase==SLINK_PHASE_PRE_SAVE);
    CHECK(pre_polls==11 && !m.ack_seq && !w.milestones && w.final_result==SLINK_TRADE_PENDING);
    return 0;
  }
  if (var==3) pre_result=1;   /* the save completes exactly when the bound is first exceeded */
  frame=51;svc();
  if (var==3) {        /* a save that lands past the bound is still a save: the poll result wins over the timeout */
    CHECK(m.producer_phase==SLINK_PHASE_READY && m.status==SLINK_ST_OK && m.ack_seq==1 && !m.opcode);
    CHECK(w.milestones==(1u<<SLINK_PRE_SAVE_OK) && w.final_result==SLINK_TRADE_PENDING);
    CHECK(w.save_status==SLINK_SAVE_OK && pre_polls==6 && starts==0 && begins==0);
    return 0;
  }
  /* the bound is exceeded with the save still unfinished: the whole visit is refused */
  CHECK(m.producer_phase==SLINK_PHASE_DONE && s.phase==TP_DONE && pre_polls==6);
  CHECK(w.final_result==SLINK_TRADE_UNCHANGED && w.milestones==(1u<<SLINK_FINAL_RESULT));
  CHECK(!(w.milestones&(1u<<SLINK_PRE_SAVE_OK)) && w.save_status==0);
  CHECK(m.status==SLINK_ST_FAIL && m.ack_seq==1 && !m.reason && !m.opcode);
  CHECK(starts==0 && begins==0 && polls==0 && last_len==0);
  CHECK(!slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
  /* the bound is armed per visit, not inherited: a new PREPARE stamps its own frame */
  send_prepare(7,10);word(m.args+12,77);m.args[16]=3;svc();
  CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE && s.pre_save_start_frame==51u);
  CHECK(w.final_result==SLINK_TRADE_PENDING && !w.milestones);
  frame=100u;svc();                       /* 49 frames into the new visit: inside its own bound */
  CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE && m.ack_seq==1 && !w.milestones);   /* ack_seq is still the previous visit's */
  frame=102u;svc();                       /* 51: the new visit's own bound expires */
  CHECK(m.producer_phase==SLINK_PHASE_DONE && w.final_result==SLINK_TRADE_UNCHANGED);
  CHECK(m.status==SLINK_ST_FAIL && m.ack_seq==10 && !m.opcode && pre_polls==8);
  return 0;
}

/* UNCERTAIN is terminal for the arena lifetime: no opcode clears it, the phase is never
 * re-published, and only arena reinitialisation (the reset) returns the producer to IDLE.
 * A PREPARE refused in UNCERTAIN names the phase (11), not the request (12). The verdict
 * is the WITNESS: TRADE_STATUS acks OK and zeroes m->reason, so the mailbox must never be
 * read as the record of what happened. */
static int sc_uncertain(void) {
  reset(); if (prep()) return 1;
  scene(2);CHECK(slink_trade_commit_entered(&s,&w,0,&e));
  begin_result=0;                                   /* the save never starts */
  scene_result=1;svc();
  CHECK(starts==1 && begins==1 && polls==0 && !bad_begin_state);
  CHECK(w.final_result==SLINK_TRADE_UNCERTAIN && w.save_status==SLINK_SAVE_FAILED
      && !(w.milestones&(1u<<SLINK_POST_SAVE_OK)));
  CHECK(m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_UNCERTAIN && m.ack_seq==2 && !m.opcode);
  CHECK(!slink_trade_success_is_durable(&w,1,2,NEW_PID,NEW_OT));
  CHECK(s.phase==TP_UNCERTAIN && m.producer_phase==SLINK_PHASE_UNCERTAIN);
  SlinkTradeWitnessV2 terminal=w;
  int st0=starts,bg0=begins,p0=polls;
  /* a fresh PREPARE on another epoch, visit and token: refused, and the refusal names the
   * terminal phase. Nothing engine-side moves and the witness is byte-identical. */
  send_prepare(9,4);svc();
  CHECK(m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_UNCERTAIN && m.ack_seq==4 && !m.opcode);
  CHECK(m.producer_phase==SLINK_PHASE_UNCERTAIN && s.phase==TP_UNCERTAIN && w.session_epoch==7u);
  CHECK(starts==st0 && begins==bg0 && polls==p0 && memcmp(&terminal,&w,sizeof w)==0);
  /* the same verdict on the witness's OWN identity: a retry is refused however it arrives */
  send_prepare(7,5);svc();
  CHECK(m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_UNCERTAIN && m.ack_seq==5 && !m.opcode);
  CHECK(m.producer_phase==SLINK_PHASE_UNCERTAIN && starts==st0 && begins==bg0 && polls==p0
      && memcmp(&terminal,&w,sizeof w)==0);
  /* the mailbox is back on the witness identity: WITHDRAW keeps its own reason, SCENE keeps IDENTITY */
  m.seq=6;m.opcode=SLINK_OP_TRADE_WITHDRAW;svc();
  CHECK(m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_WITHDRAW_TOO_LATE && m.ack_seq==6 && !m.opcode);
  m.seq=7;m.opcode=SLINK_OP_TRADE_SCENE;svc();
  CHECK(m.status==SLINK_ST_FAIL && m.reason==SLINK_REASON_IDENTITY && m.ack_seq==7 && !m.opcode);
  CHECK(m.producer_phase==SLINK_PHASE_UNCERTAIN && starts==st0 && begins==bg0 && polls==p0
      && memcmp(&terminal,&w,sizeof w)==0);
  /* STATUS is the read-only query: OK, and it erases m->reason. The mailbox reason is not
   * durable evidence; the witness is unchanged and still says UNCERTAIN. */
  m.seq=8;m.opcode=SLINK_OP_TRADE_STATUS;svc();
  CHECK(m.status==SLINK_ST_OK && !m.reason && m.ack_seq==8 && !m.opcode);
  CHECK(m.producer_phase==SLINK_PHASE_UNCERTAIN && s.phase==TP_UNCERTAIN && starts==st0
      && begins==bg0 && polls==p0 && memcmp(&terminal,&w,sizeof w)==0);
  /* the epoch bump above changed nothing; only the reset clears, and a fresh visit opens */
  memset(&s,0,sizeof s);memset(&m,0,sizeof m);memset(&w,0,sizeof w);
  svc();
  CHECK(m.producer_phase==SLINK_PHASE_IDLE && s.phase==TP_IDLE && starts==st0 && begins==bg0
      && polls==p0 && !w.milestones && !w.session_epoch
      && w.final_result==SLINK_TRADE_PENDING);
  send_prepare(9,1);svc();
  CHECK(m.producer_phase==SLINK_PHASE_PRE_SAVE && w.session_epoch==9u && w.visit_id==8u
      && w.final_result==SLINK_TRADE_PENDING && starts==st0);
  return 0;
}

int main(int argc,char **argv) {
  int sc=argc>1?atoi(argv[1]):1,var=argc>2?atoi(argv[2]):0;
  switch (sc) {
    case 1: return sc_happy();
    case 2: return sc_refuse(var);
    case 3: return sc_recv(var);
    case 4: return sc_savefail(var);
    case 5: return sc_forever();
    case 6: return sc_stale(var);
    case 7: return sc_dup();
    case 8: return sc_badbinding(var);
    case 9: return sc_mutate(var);
    case 10: return sc_stagelen(var);
    case 11: return sc_foreign(var);
    case 12: return sc_presave(var);
    case 13: return sc_uncertain();
  }
  return 99;
}
'''

BINDINGS = {"pk4": "slink_binding_gen4_pk4", "pk5": "slink_binding_gen5_pk5"}
SCENARIOS = (
    [("happy", 1, 0)]
    + [(f"refuse{v}", 2, v) for v in range(19)]
    + [(f"recv{v}", 3, v) for v in range(4)]
    + [(f"savefail{v}", 4, v) for v in range(6)]
    + [("pending-forever", 5, 0)]
    + [(f"stale{v}", 6, v) for v in range(4)]
    + [("duplicates", 7, 0)]
    + [(f"badbinding{v}", 8, v) for v in range(5)]
    + [(f"mutates-input{v}", 9, v) for v in range(2)]
    + [(f"stage-len-arm{v}", 10, v) for v in range(2)]
    + [(f"foreign-{n}", 11, v) for v, n in enumerate(
        ["play-se", "show-info", "play-fanfare", "play-se-idle"])]
    + [(f"presave-{n}", 12, v) for v, n in enumerate(
        ["wait-times-out", "no-watchdog", "consented-times-out", "completion-after-bound-wins"])]
    + [("uncertain-terminal", 13, 0)]
)


@pytest.fixture(scope="module")
def pk45(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pk45")
    return {k: _build(tmp, k, PK45_C, defines=[f"-DBIND={sym}"]) for k, sym in BINDINGS.items()}


@pytest.mark.parametrize("name,sc,var", SCENARIOS, ids=[s[0] for s in SCENARIOS])
@pytest.mark.parametrize("binding", sorted(BINDINGS))
def test_pk45_lifecycle(pk45, binding, name, sc, var):
    _run(pk45[binding], sc, var)


TP = "trade_producer.h"
# The mailbox-ownership gate in tp_service. Deleting it restores the unconditional
# tp_ack(m,seq,0,2) catch-all that consumed every opcode the trade producer does not own.
FOREIGN_GATE = ("    if (op!=SLINK_OP_TRADE_PREPARE && op!=SLINK_OP_TRADE_SCENE\n"
                "        && op!=SLINK_OP_TRADE_WITHDRAW && op!=SLINK_OP_TRADE_STATUS) return;")
# The PREPARE refusal's reason line (tp_service). Two mutants hang off it: one that clears
# the terminal phase on the way out, and the pre-fix answer that named the request instead.
UNCERTAIN_ACK = ("            tp_ack(m,seq,0,s->phase==TP_UNCERTAIN ? SLINK_REASON_UNCERTAIN"
                 " : SLINK_REASON_IDENTITY);")
UNCERTAIN_SELF_CLEAR = ("            if (s->phase==TP_UNCERTAIN) { s->phase=TP_IDLE; tp_ack(m,seq,0,SLINK_REASON_UNCERTAIN); }\n"
                        "            else tp_ack(m,seq,0,SLINK_REASON_IDENTITY);")
HARNESS = "<harness>"  # edit target is the PK45 scenario C source, not a header
MUTANTS = {
    "truncate-to-100": ((1, 0), [(TP, "i < len ? st->record[i] : 0", "i < 100 ? st->record[i] : 0")]),
    "pending-is-failure": ((1, 0), [(TP, "if (polled == SLINK_SAVEPOLL_PENDING) return;", "")]),
    "begin-is-success": ((1, 0), None),
    "garbage-poll-is-ok": ((4, 2), [(TP, "return SLINK_SAVEPOLL_FAIL;\n}", "return SLINK_SAVEPOLL_OK;\n}")]),
    "no-identity-claim-check": ((2, 10), [(TP, "if (!b->same_identity(&actual,&claimed)) return 0;", "(void)claimed;")]),
    "no-received-identity-check": ((3, 0), [(TP, "if (!e->binding->same_identity(&got,&s->incoming_id)) {",
                                             "(void)got; if (0) {")]),
    "no-save-watchdog": ((4, 5), [(TP, "(uint32_t)(e->frame(e->context) - s->save_start_frame) <= e->save_timeout_frames", "((void)s, 1)")]),
    "unknown-flag-accepted": ((2, 16), [(TP, "|| (flags & ~(unsigned)SLINK_STAGE_RAW_ENCRYPTED)", "")]),
    "no-scratch-copy": ((9, 0), [(TP, "handed = s->scratch;", "handed = s->incoming;")]),
    "witness-publishes-claim": ((3, 3), [(TP, "w->received_pid = s->received_id.pid; w->received_otid = s->received_id.otid;",
                                          "w->received_pid = s->incoming_id.pid; w->received_otid = s->incoming_id.otid;")]),
    "validate-open-without-verify": ((2, 18), [("record_binding.h", "if (!d || !d->verify) return 0;",
                                                "if (!d) return 0;\n    if (!d->verify) return 1;")]),
    # received_key is only an independent witness if it is NOT derived from the staging decoder: a received_key
    # that decodes the staged record (same dec_read at otid_logical_off) agrees with incoming_id by construction.
    "received-key-from-staging-decoder": ((3, 0), [(HARNESS, "static int received(void *p,unsigned slot,uint32_t *pid,uint32_t *ot) { (void)p;(void)slot; if (!recv_ok) return 0; *pid=recv_pid;*ot=recv_ot;return 1; }",
                                                    "static int dec_read(void *p,const uint8_t *r,uint16_t n,uint16_t off,uint32_t *out); "
                                                    "static int received(void *p,unsigned slot,uint32_t *pid,uint32_t *ot) { (void)p;(void)slot;(void)recv_pid;(void)recv_ot; uint32_t ot_; "
                                                    "  if (!recv_ok || !dec_read(0,last_rec,B->party_len,B->otid_logical_off,&ot_)) return 0; memcpy(pid,last_rec,4);*ot=ot_;return 1; }")]),
    # sound/panel opcodes posted while a trade save is in flight must survive the visit
    "ack-foreign-opcode": ((11, 0), [(TP, FOREIGN_GATE, "")]),
    # the pre-save leg had no frame bound: without it a poll that never saves and never refuses
    # parks the producer in TP_PRE_SAVE forever while the host's own budget expires.
    "no-pre-save-watchdog": ((12, 0), [(TP, "(uint32_t)(e->frame(e->context) - s->pre_save_start_frame) > e->pre_save_timeout_frames", "((void)s, 1)")]),
    # UNCERTAIN is terminal for the arena lifetime: no opcode may clear it, and the refusal
    # has to name the phase. The self-clearing mutant still answers 11, so it must go red on
    # the phase assertion, not the reason one.
    "native-self-clears-uncertain": ((13, 0), [(TP, UNCERTAIN_ACK, UNCERTAIN_SELF_CLEAR)]),
    "uncertain-refused-as-identity": ((13, 0), [(TP, UNCERTAIN_ACK,
                                                 "            tp_ack(m,seq,0,SLINK_REASON_IDENTITY);")]),
}


@pytest.mark.parametrize("mutation", sorted(MUTANTS))
def test_producer_falsifiers_fail_on_known_bad_mutants(tmp_path, mutation):
    """Revert-test the instrument: the scenario must go red on each seeded defect."""
    scenario, edits = MUTANTS[mutation]
    mutant = tmp_path / "common"
    shutil.copytree(COMMON, mutant)
    harness = PK45_C
    if mutation == "begin-is-success":  # initiating the save is recorded as success without polling
        path = mutant / TP
        text = path.read_text()
        pattern = re.compile(r"(if \(!e->post_save_begin\(e->context\)\).*?)tp_save_resolve\(s,m,w,tp_save_poll\(s,e\),e\);", re.S)
        assert pattern.search(text)
        path.write_text(pattern.sub(lambda hit: hit.group(1) + "tp_save_resolve(s,m,w,SLINK_SAVEPOLL_OK,e);", text, count=1))
    else:
        for name, needle, replacement in edits:
            if name == HARNESS:
                assert needle in harness, needle
                harness = harness.replace(needle, replacement)
                continue
            path = mutant / name
            text = path.read_text()
            assert needle in text, needle
            path.write_text(text.replace(needle, replacement))
    exe = _build(tmp_path, "mutant", harness, includes=(mutant,), defines=["-DBIND=slink_binding_gen5_pk5"])
    done = subprocess.run([str(exe), *map(str, scenario)], capture_output=True, text=True, timeout=10)
    assert done.returncode != 0 and "FAIL line" in done.stdout, f"mutant {mutation} was not detected: {done}"


# --------------------------------------------------------------------------- (c) source guards

HEADERS = ["abi.h", "compat.h", "record_binding.h", "trade_producer.h", "panel_producer.h", "sound_producer.h"]


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


@pytest.mark.parametrize("header", HEADERS)
def test_nds_headers_have_no_gba_addresses_and_do_not_include_gen3(header):
    code = _strip_comments((COMMON / header).read_text())
    assert not re.search(r"0x0[28][0-9A-Fa-f]{6}\b", code, re.I), "GBA ROM/EWRAM-style address literal"
    includes = re.findall(r'#\s*include\s*[<"]([^>"]+)[>"]', code)
    assert all("trade_targets" not in inc for inc in includes), includes
    allowed = {"stdint.h", "stddef.h", *HEADERS}
    assert set(includes) <= allowed, includes


def test_readme_exists_and_static_assert_blocks_are_pinned():
    assert (COMMON / "README.md").exists()
    # exact counts: adding or dropping an ABI/record invariant is a deliberate, reviewed change
    # compat.h is the only file allowed to spell the C11 form (one define, in its non-mwcc arm)
    raw = {h: _strip_comments((COMMON / h).read_text()).count("_Static_assert(") for h in HEADERS}
    assert raw == {h: (1 if h == "compat.h" else 0) for h in HEADERS}
    pinned = {"abi.h": 27, "compat.h": 2, "record_binding.h": 3, "trade_producer.h": 2, "panel_producer.h": 0, "sound_producer.h": 0}
    actual = {h: _strip_comments((COMMON / h).read_text()).count("SLINK_STATIC_ASSERT(") for h in pinned}
    assert actual == pinned


# --------------------------------------------------------------------------- (d) Gen 3 untouched

def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=30)


def test_gen3_sources_and_build_are_untouched():
    if _git("rev-parse", "--git-dir").returncode != 0:
        pytest.skip("not a git checkout; cannot diff Gen 3 sources")
    paths = ["patch/src/trade_targets", "patch/tools/build.py"]
    assert _git("diff", "--stat", "HEAD", "--", *paths).stdout.strip() == ""
    assert _git("diff", "--stat", "--cached", "--", *paths).stdout.strip() == ""
    assert _git("status", "--porcelain", "--", *paths).stdout.strip() == ""
    base = "735dea38"
    if _git("cat-file", "-e", f"{base}^{{commit}}").returncode == 0:
        assert _git("diff", "--stat", base, "--", *paths).stdout.strip() == ""
