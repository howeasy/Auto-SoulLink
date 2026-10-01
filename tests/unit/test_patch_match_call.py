"""Match Call producer MODEL: ACK, delivery, UI ownership and epoch changes."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]


def test_call_delivery_is_not_ack_and_epoch_change_cannot_reuse_open_text(tmp_path):
    gcc=os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("set SLINK_HOST_GCC")
    source=tmp_path/"call.c"
    source.write_text(r'''#include "call_producer.h"
#include <string.h>
static uint32_t frame=10;static int safe,view,starts;
static int available(void *p) { (void)p;return 1; }
static int ready(void *p) { (void)p;return safe; }
static int start(void *p,const volatile SlinkCallRecordV2 *r) { (void)p;starts++;return r->event==1; }
static int poll(void *p) { (void)p;return view; }
static uint32_t clock_now(void *p) { (void)p;return frame; }
static void post(SlinkMailboxV2 *m,unsigned seq,unsigned event) { m->seq=seq;m->opcode=32;m->args[0]=event; }
int main(void) {
 SlinkCallProducer s={0};SlinkMailboxV2 m={0};SlinkCallWitnessV2 w={0};SlinkCallRecordV2 owned={0},input={0};
 SlinkCallEngine e={0,available,ready,start,poll,clock_now};
 memset(input.trainer,0xff,8);memset(input.caller_nick,0xff,11);memset(input.receiver_nick,0xff,11);
 input.event=1;input.has_names=1;input.trainer[0]=0xbb; /* absent mon IDs stay a generic call */
 m.session_epoch=7;post(&m,1,1);slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (m.status!=2 || w.phase!=SLINK_CALL_ARMED || starts || !w.revision || (w.revision&1)) return 1;
 input.trainer[0]=0xcc;
 if (owned.trainer[0]!=0xbb || w.delivered_frame) return 2;
 SlinkCallWitnessV2 armed=w;
 post(&m,1,2);slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (m.status!=3 || m.reason!=SLINK_REASON_IDENTITY || memcmp(&armed,&w,sizeof(w))) return 13;
 m.args[0]=1;
 safe=1;slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (starts!=1 || w.phase!=SLINK_CALL_ARMED) return 3;
 view=1;frame=20;slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (w.phase!=SLINK_CALL_DELIVERED || w.delivered_frame!=20) return 4;
 SlinkCallWitnessV2 before=w;SlinkCallRecordV2 old=owned;
 m.session_epoch=8;post(&m,2,1);slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (m.status!=3 || m.reason!=SLINK_REASON_CALL_BUSY || memcmp(&w,&before,sizeof(w)) || memcmp(&owned,&old,sizeof(old))) return 5;
 view=2;frame=30;slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (w.phase!=SLINK_CALL_COMPLETE || w.session_epoch!=7 || w.seq!=1 || w.delivered_frame!=20 || w.event!=1) return 6;
 post(&m,3,1);slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (w.phase!=SLINK_CALL_REFUSED || m.reason!=SLINK_REASON_CALL_COOLDOWN || starts!=1) return 7;
 frame=10820;safe=0;post(&m,4,1);slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (w.phase!=SLINK_CALL_ARMED || m.status!=2) return 8;
 m.session_epoch=9;slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (w.phase!=SLINK_CALL_EMPTY || (w.revision&1) || s.active || starts!=1) return 9;
 /* Malformed record refuses coherently before ACK and never starts UI. */
 input.event=2;post(&m,5,1);slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (m.status!=3 || w.phase!=SLINK_CALL_REFUSED || w.seq!=5 || !w.revision || (w.revision&1)) return 10;
 input.event=1;input.trainer[0]=0xfd;post(&m,6,1);slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (m.status!=3 || starts!=1) return 11;
 input.trainer[0]=0xbb;safe=1;view=0;post(&m,7,1);slink_call_service(&s,&m,&w,&owned,&input,&e);
 slink_call_service(&s,&m,&w,&owned,&input,&e);view=2;slink_call_service(&s,&m,&w,&owned,&input,&e);
 if (w.phase!=SLINK_CALL_REFUSED || w.delivered_frame || s.active) return 12;
 return 0;
}
''')
    exe=tmp_path/"call.exe"
    built=subprocess.run([gcc,"-std=c11","-Wall","-Werror","-I",str(ROOT/"patch/src/trade_targets"),str(source),"-o",str(exe)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stderr
    assert subprocess.run([str(exe)],timeout=5).returncode==0
