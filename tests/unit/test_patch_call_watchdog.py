"""Phone start watchdog releases only with engine proof; visible UI remains owned."""
import os
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_stalled_call_start_is_bounded_without_releasing_a_live_ui(tmp_path):
    gcc=os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:pytest.skip("host C compiler required")
    source=tmp_path/"watchdog.c"
    source.write_text(r'''
#include "call_producer.h"
#include "native_call_state.h"
#include <string.h>
static unsigned now=10;static int view,release=1,cancels;
static int yes(void *p) { (void)p;return 1; }
static int start(void *p,const volatile SlinkCallRecordV2 *r) { (void)p;(void)r;return 1; }
static int poll(void *p) { (void)p;return view; }
static int cancel(void *p) { (void)p;cancels++;return release; }
static uint32_t frame(void *p) { (void)p;return now; }
int main(void) {
 SlinkCallProducer s={0};SlinkMailboxV2 m={0};SlinkCallWitnessV2 w={0};SlinkCallRecordV2 owned={0},r={0};
 SlinkCallEngine e={.available=yes,.safe=yes,.start=start,.poll=poll,.frame=frame,.cancel=cancel};
 memset(r.trainer,255,8);memset(r.caller_nick,255,11);memset(r.receiver_nick,255,11);r.event=1;
 m.session_epoch=7;m.seq=1;m.opcode=32;m.args[0]=1;
 slink_call_service(&s,&m,&w,&owned,&r,&e);slink_call_service(&s,&m,&w,&owned,&r,&e);
 now+=SLINK_CALL_START_TIMEOUT_FRAMES;
 slink_call_service(&s,&m,&w,&owned,&r,&e);
 if (s.active || s.ui_owned || w.phase!=SLINK_CALL_REFUSED || w.reason!=17 || w.delivered_frame || s.has_delivery || cancels!=1) return 1;
 m.seq=2;m.opcode=32;release=0;
 slink_call_service(&s,&m,&w,&owned,&r,&e);slink_call_service(&s,&m,&w,&owned,&r,&e);
 now+=SLINK_CALL_START_TIMEOUT_FRAMES;slink_call_service(&s,&m,&w,&owned,&r,&e);
 if (!s.active || !s.ui_owned || w.phase!=SLINK_CALL_ARMED) return 2;
 /* A service that first observes native slide-out still proves message entry. */
 for (int i=0;i<5;i++) if (slink_match_call_message_started(i)) return 3;
 if (!slink_match_call_message_started(5) || !slink_match_call_message_started(6) || !slink_match_call_message_started(7) || slink_match_call_message_started(8)) return 4;
 view=slink_match_call_message_started(6);slink_call_service(&s,&m,&w,&owned,&r,&e);
 if (w.phase!=SLINK_CALL_DELIVERED || !s.has_delivery) return 5;
 int before=cancels;now+=SLINK_CALL_START_TIMEOUT_FRAMES;view=0;slink_call_service(&s,&m,&w,&owned,&r,&e);
 if (!s.ui_owned || cancels!=before) return 6;
 view=2;slink_call_service(&s,&m,&w,&owned,&r,&e);
 if (s.ui_owned || w.phase!=SLINK_CALL_COMPLETE) return 7;
 m.seq=3;m.opcode=32;slink_call_service(&s,&m,&w,&owned,&r,&e);
 if (m.status!=3 || m.reason!=18) return 8;
 return 0;
}
''')
    exe=tmp_path/"watchdog.exe"
    built=subprocess.run([gcc,"-std=c11","-Wall","-Werror","-I",str(ROOT/"patch/src/trade_targets"),str(source),"-o",str(exe)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stderr
    assert subprocess.run([str(exe)],timeout=5).returncode==0
