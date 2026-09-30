"""Consumption-time W1 refusals must leave the enemy party untouched."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("control",range(21))
def test_rival_window_and_complete_team_validation_precede_mutation(tmp_path,control):
    gcc=os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("set SLINK_HOST_GCC")
    source=tmp_path/"rival.c"
    source.write_text(r'''#include "rival_producer.h"
#include <string.h>
static SlinkRivalWindow window={0x101,0x201,8,102,1,1};
static uint8_t blob[600],enemy[600];
static int views,writes;
static void read_window(void *p,SlinkRivalWindow *out) {
  (void)p;*out=window;if (CONTROL==12 && views++) out->stage=15;
}
static int validate(void *p,uint8_t *mon) { (void)p;if (CONTROL==17) blob[0]=99;return mon[0]; }
static void replace(void *p,const uint8_t *data,unsigned count) {
  (void)p;writes++;memcpy(enemy,data,count*100);memset(enemy+count*100,0,600-count*100);
}
int main(void) {
  SlinkMailboxV2 m={0};SlinkRivalEngine e={0,0x101,0x201,read_window,validate,replace};
  memset(enemy,0xa5,sizeof(enemy));blob[0]=blob[100]=2;
  m.opcode=28;m.seq=1;m.session_epoch=7;m.args[0]=2;m.args[1]=102;
  if (CONTROL==1) window.stage=15;
  if (CONTROL==2) window.callback=0x999;
  if (CONTROL==3) window.main_func=0x999;
  if (CONTROL==4) window.flags|=2;
  if (CONTROL==5) window.trainer=99;
  if (CONTROL==6) window.flags=0;
  if (CONTROL==7) window.in_battle=0;
  if (CONTROL==8) m.args[0]=0;
  if (CONTROL==9) blob[100]=0;
  if (CONTROL==10) blob[0]=blob[100]=1;
  if (CONTROL==11) { window.flags|=1;blob[100]=1; }
  if (CONTROL==13) m.session_epoch=8;
  if (CONTROL==14) m.session_epoch=0;
  if (CONTROL==15) m.args[0]=7;
  if (CONTROL==16) window.flags|=1;
  if (CONTROL==18) blob[0]=1;
  if (CONTROL==19) window.stage=14;
  if (CONTROL==20) window.stage=0;
  slink_rival_service(&m,blob,&e,7);
  if (CONTROL==0 || CONTROL>=16) {
    if (writes!=1 || m.status!=2 || enemy[0]!=(CONTROL==18?1:2) || enemy[100]!=2 || enemy[200]!=0) return 1;
  } else {
    if (writes || m.status!=3) return 2;
    for (unsigned i=0;i<600;i++) if (enemy[i]!=0xa5) return 3;
    unsigned reason=(CONTROL==8 || CONTROL==9 || CONTROL==15)?2:
      (CONTROL==10 || CONTROL==11)?SLINK_REASON_SLOTS_UNVIABLE:
      CONTROL==13?SLINK_REASON_IDENTITY:CONTROL==14?SLINK_REASON_CLIENT_TOO_OLD:SLINK_REASON_WINDOW_CLOSED;
    if (m.reason!=reason) return 4;
  }
  if (m.opcode || m.ack_seq!=1) return 5;
  m.opcode=29;slink_rival_service(&m,blob,&e,7);
  if (m.opcode!=29) return 6;
  return 0;
}
''')
    exe=tmp_path/"rival.exe"
    compiled=subprocess.run([gcc,"-std=c11","-Wall","-Werror",f"-DCONTROL={control}","-I",
                             str(ROOT/"patch/src/trade_targets"),str(source),"-o",str(exe)],
                            capture_output=True,text=True,timeout=30)
    assert compiled.returncode==0,compiled.stderr
    assert subprocess.run([str(exe)],timeout=5).returncode==0
