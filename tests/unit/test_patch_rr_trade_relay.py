"""RR-DURABLE: the shadow-mailbox relay runs the shared FR/LG trade producer for RR's ABI1
mailbox. Host-compiled against the real patch/src/trade_targets/trade_producer.h."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "patch" / "src"

PROGRAM = r'''#include "rr_trade_relay.h"
#include <string.h>
static int pre_done, scene_done, saves, commit_at_start = 1;
static SlinkTradeProducer state; static SlinkMailboxV2 shadow; static SlinkTradeWitnessV2 w;
static uint32_t mb[20]; static uint8_t blob[100];
static const SlinkTradeEngine *engine;
static int safe(void *p) { (void)p; return 1; }
static int locate(void *p,uint32_t pid,uint32_t ot) { (void)p; return pid==11 && ot==22 ? 0 : -1; }
static int validate(void *p,const uint8_t *b) { (void)p; return b[0]==33; }
static int pre_start(void *p) { (void)p; return 1; }
static int pre_poll(void *p) { (void)p; return pre_done; }
static int scene_start(void *p,unsigned slot,const uint8_t *b) {
  (void)p;(void)b;
  /* RR marks COMMIT_ENTERED at launch: the in-game scene cannot be cancelled afterwards. */
  return commit_at_start ? slink_trade_commit_entered(&state,&w,slot,engine) : 1;
}
static int scene_poll(void *p) { (void)p; return scene_done; }
static int save(void *p) { (void)p; saves++; return 1; }
static int received(void *p,unsigned slot,uint32_t *pid,uint32_t *ot) { (void)p;(void)slot;*pid=33;*ot=44;return 1; }
static uint32_t tick(void *p) { (void)p; static uint32_t f; return ++f; }
static void post(uint16_t seq, uint16_t op) { mb[2] = seq; mb[1] = 1u | ((uint32_t)op << 16); }
static uint16_t opcode(void) { return (uint16_t)(mb[1] >> 16); }
static uint16_t status(void) { return (uint16_t)(mb[2] >> 16); }
static uint16_t ack(void) { return (uint16_t)mb[3]; }
static int run(void) { return rr_trade_relay(mb,&shadow,&state,&w,blob,engine); }
int main(void) {
  SlinkTradeEngine e={0,safe,locate,validate,pre_start,pre_poll,scene_start,scene_poll,save,received,tick};
  engine=&e;
  for (int i=16;i<20;i++) mb[i]=0xA5A5A5A5u;          /* RR SwapState/GhostState live here */
  mb[0]=0x4B4E4C53u; shadow.session_epoch=7;
  uint8_t *args=(uint8_t *)&mb[4];
  args[4]=11; args[8]=22; args[12]=8; args[16]=9; blob[0]=33; blob[4]=44;
  post(1, SLINK_OP_TRADE_PREPARE);
  if (!run() || shadow.producer_phase!=SLINK_PHASE_PRE_SAVE || status()!=SLINK_ST_BUSY) return 1;
  if (shadow.capabilities!=SLINK_CAP_DURABLE_TRADE || mb[0]!=0x4B4E4C53u) return 2;
  if (CONTROL==1) {
    /* a v1 op posted while the producer polls: never the producer's, never acked by it */
    post(2, 19); pre_done=1;
    uint32_t before[20]; memcpy(before, mb, sizeof mb);
    if (run() || memcmp(before, mb, sizeof mb) || opcode()!=19) return 3;
    if (shadow.producer_phase!=SLINK_PHASE_READY) return 4;   /* the poll still ran */
    return 0;
  }
  pre_done=1;
  if (!run() || opcode() || status()!=SLINK_ST_OK || ack()!=1) return 5;
  if (shadow.producer_phase!=SLINK_PHASE_READY) return 6;
  if (CONTROL==2) commit_at_start=0;
  post(2, SLINK_OP_TRADE_SCENE);
  if (!run() || shadow.producer_phase!=SLINK_PHASE_SCENE) return 7;
  scene_done=1;
  if (!run() || opcode()) return 8;
  if (CONTROL==2) {
    /* without a commit marker a returned scene is never success */
    if (w.final_result!=SLINK_TRADE_UNCERTAIN || status()!=SLINK_ST_FAIL || saves) return 9;
    return 0;
  }
  if (w.final_result!=SLINK_TRADE_COMMITTED || w.milestones!=SLINK_SUCCESS_MILESTONES) return 10;
  if (status()!=SLINK_ST_OK || ack()!=2 || saves!=1 || w.save_status!=SLINK_SAVE_OK) return 11;
  if (!slink_trade_success_is_durable((const SlinkTradeWitnessV2 *)&w,1,2,33,44)) return 12;
  for (int i=16;i<20;i++) if (mb[i]!=0xA5A5A5A5u) return 13;
  return 0;
}
'''


@pytest.mark.parametrize("control", [0, 1, 2])
def test_rr_relay_runs_the_shared_producer_without_touching_v1_state(tmp_path, control):
    gcc = os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("host C compiler absent; set SLINK_HOST_GCC")
    source = tmp_path / "relay.c"
    source.write_text(PROGRAM)
    binary = tmp_path / "relay.exe"
    subprocess.run([gcc, "-std=c11", "-Wall", "-Werror", f"-DCONTROL={control}", "-I", str(SRC),
                    str(source), "-o", str(binary)], check=True, capture_output=True, text=True)
    result = subprocess.run([str(binary)], capture_output=True)
    assert result.returncode == 0, f"control {control} failed at check {result.returncode}"
