"""Execute the actual portable producer against deterministic engine boundaries."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("save_result,omit_commit,control", [
    (0,0,0),(1,0,0),(1,1,0),(1,0,1),(1,0,2),(1,0,3),(1,0,4),
])
def test_scene_return_cannot_report_success_before_native_save(tmp_path, save_result, omit_commit, control):
    gcc = os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("host C compiler absent; set SLINK_HOST_GCC")
    source = tmp_path / "producer.c"
    source.write_text(r'''#include "trade_producer.h"
#include <string.h>
_Static_assert(offsetof(SlinkTradeProducer,incoming)%4==0,"native Pokemon staging must be word aligned");
static int pre_done, scene_done, save_ok, saves, starts, old_present=1;
static uint32_t frame;
static int safe(void *p) { (void)p; return 1; }
static int locate(void *p,uint32_t pid,uint32_t ot) { (void)p; return old_present && pid==11 && ot==22 ? 0 : -1; }
static int validate(void *p,const uint8_t *b) { (void)p; return b[0]==33; }
static int pre_start(void *p) { (void)p; return 1; }
static int pre_poll(void *p) { (void)p; return pre_done; }
static int scene_start(void *p,unsigned slot,const uint8_t *b) { (void)p;(void)slot;(void)b;starts++;return 1; }
static int scene_poll(void *p) { (void)p;return scene_done; }
static int save(void *p) { (void)p;saves++;return save_ok; }
static int received(void *p,unsigned slot,uint32_t *pid,uint32_t *ot) { (void)p;(void)slot;*pid=33;*ot=44;return 1; }
static uint32_t clock_frame(void *p) { (void)p;return ++frame; }
static void word(uint8_t *p,uint32_t v) { memcpy(p,&v,4); }
int main(void) {
  SlinkTradeProducer state={0}; SlinkMailboxV2 m={0}; SlinkTradeWitnessV2 w={0}; uint8_t blob[100]={0};
  SlinkTradeEngine e={0,safe,locate,validate,pre_start,pre_poll,scene_start,scene_poll,save,received,clock_frame};
  m.session_epoch=7;m.seq=1;m.opcode=SLINK_OP_TRADE_PREPARE;
  word(m.args+4,11);word(m.args+8,22);word(m.args+12,8);m.args[16]=9;
  word(blob,33);word(blob+4,44);
  slink_trade_service(&state,&m,&w,blob,&e);
  if (w.visit_flags!=SLINK_VISIT_ACCEPTED || w.milestones) return 1;
  pre_done=CONTROL==1?-1:1;slink_trade_service(&state,&m,&w,blob,&e);
  if (CONTROL==1) {
    if (w.final_result!=SLINK_TRADE_UNCHANGED || starts || saves) return 9;
    return 0;
  }
  if (!(w.milestones&(1u<<SLINK_PRE_SAVE_OK)) || m.opcode) return 2;
  m.seq=2;m.opcode=SLINK_OP_TRADE_SCENE;
  SlinkTradeWitnessV2 before=w;
  if (CONTROL==2) m.args[16]++;
  if (CONTROL==3) m.session_epoch++;
  slink_trade_service(&state,&m,&w,blob,&e);
  if (CONTROL==2 || CONTROL==3) {
    if (starts || saves || memcmp(&before,&w,sizeof(w))) return 10;
    return 0;
  }
  if (starts!=1 || w.milestones&(1u<<SLINK_COMMIT_ENTERED)) return 3;
  if (CONTROL==4) {
    old_present=0;
    if (slink_trade_commit_entered(&state,&w,0,&e)) return 11;
    scene_done=1;slink_trade_service(&state,&m,&w,blob,&e);
    if (w.final_result!=SLINK_TRADE_UNCHANGED || saves || !state.cancel_scene) return 12;
    return 0;
  }
  if (!OMIT_COMMIT && !slink_trade_commit_entered(&state,&w,0,&e)) return 4;
  scene_done=1;save_ok=SAVE_RESULT;slink_trade_service(&state,&m,&w,blob,&e);
  if (SAVE_RESULT && !OMIT_COMMIT) {
    if (saves!=1 || w.final_result!=SLINK_TRADE_COMMITTED || m.status!=SLINK_ST_OK) return 5;
    if (!slink_trade_success_is_durable(&w,1,2)) return 6;
    if (w.received_pid!=33 || w.received_otid!=44) return 7;
  } else {
    if (saves!=(OMIT_COMMIT?0:1) || w.final_result!=SLINK_TRADE_UNCERTAIN) return 5;
    if (w.milestones&(1u<<SLINK_POST_SAVE_OK) || m.status==SLINK_ST_OK) return 6;
    if (slink_trade_success_is_durable(&w,1,2)) return 7;
  }
  /* Uncertain is sticky: repeating an APPLY cannot run another scene or save. */
  m.seq=3;m.opcode=SLINK_OP_TRADE_SCENE;
  slink_trade_service(&state,&m,&w,blob,&e);
  if (starts!=1 || saves!=(OMIT_COMMIT?0:1)) return 8;
  return 0;
}
''')
    exe = tmp_path / "producer.exe"
    result = subprocess.run([gcc,"-std=c11","-Wall","-Werror",f"-DSAVE_RESULT={save_result}",
                             f"-DOMIT_COMMIT={omit_commit}",f"-DCONTROL={control}","-I",
                             str(ROOT / "patch/src/trade_targets"),str(source),"-o",str(exe)],
                            capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr + f" exit={result.returncode}"
