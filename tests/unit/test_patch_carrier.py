"""RR-compatible carrier op results, owned buffers, and deliberate NPC interaction."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("opcode,result", [(17,1),(17,0),(20,0),(20,5),(20,7),(22,0),(22,127)])
def test_carrier_owns_ui_and_preserves_rr_result_semantics(tmp_path, opcode, result):
    gcc = os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("set SLINK_HOST_GCC")
    source = tmp_path / "carrier.c"
    source.write_text(r'''#include "carrier_producer.h"
#include <string.h>
static int safe=1,starts,done,arms;
static const SlinkCarrierProducer *owned;
static int field(void *c) { (void)c;return safe; }
static int start(void *c,const SlinkCarrierProducer *s) { (void)c;starts++;owned=s;return 1; }
static int poll(void *c,uint8_t *v) { (void)c;*v=RESULT;return done; }
static int arm(void *c,uint8_t oe,uint8_t enabled) { (void)c;(void)oe;(void)enabled;arms++;return 1; }
int main(void) {
  SlinkMailboxV2 m={0};SlinkCarrierProducer s={0};
  SlinkCarrierEngine e={0,field,start,poll,arm};
  uint8_t text[256],menu[112];memset(text,0xff,sizeof(text));memset(menu,0xff,sizeof(menu));
  text[0]=0xbb;menu[0]=2;menu[1]=0xbc;menu[2]=0xff;menu[3]=0xbd;
  m.session_epoch=7;m.seq=1;m.opcode=OPCODE;m.args[0]=1;
  slink_carrier_service(&s,&m,text,menu,&e);
  if (starts!=1 || !s.active || m.status!=SLINK_ST_BUSY || m.opcode || m.ack_seq==1) return 1;
  text[0]=0xcc;menu[1]=0xdd;
  if (owned->text[0]!=0xbb || owned->choices[1]!=0xbc) return 2;
  done=1;slink_carrier_service(&s,&m,text,menu,&e);
  if (s.active || m.status!=SLINK_ST_OK || m.ack_seq!=1 || m.result[0]!=RESULT) return 3;
  /* Validation must run before entering a lockall script. */
  done=0;m.opcode=22;m.seq=2;memset(menu,0,112);menu[0]=9;
  slink_carrier_service(&s,&m,text,menu,&e);
  if (starts!=1 || s.active || m.status!=SLINK_ST_FAIL) return 4;
  menu[0]=2;m.opcode=22;m.seq=3;
  slink_carrier_service(&s,&m,text,menu,&e);
  if (starts!=1 || s.active) return 5;
  safe=0;m.opcode=20;m.seq=4;
  slink_carrier_service(&s,&m,text,menu,&e);
  if (starts!=1 || s.active) return 6;
  safe=1;m.opcode=20;m.seq=5;
  slink_carrier_service(&s,&m,text,menu,&e);
  m.session_epoch=8;m.seq=6;m.opcode=17;
  slink_carrier_service(&s,&m,text,menu,&e);
  if (!s.active || starts!=2 || m.status!=SLINK_ST_FAIL) return 7;
  done=1;slink_carrier_service(&s,&m,text,menu,&e);
  if (s.active || m.ack_seq!=6 || m.status!=SLINK_ST_FAIL) return 8;
  m.opcode=13;m.seq=7;m.args[0]=16;
  slink_carrier_service(&s,&m,text,menu,&e);
  if (arms) return 9;
  m.opcode=13;m.seq=8;m.args[0]=3;
  slink_carrier_service(&s,&m,text,menu,&e);
  if (arms!=1 || m.status!=SLINK_ST_OK) return 10;
  if (!slink_carrier_interaction(1,1,1,1,10,10,2,10,9)) return 11;
  if (slink_carrier_interaction(0,1,1,1,10,10,2,10,9)
      || slink_carrier_interaction(1,0,1,1,10,10,2,10,9)
      || slink_carrier_interaction(1,1,0,1,10,10,2,10,9)
      || slink_carrier_interaction(1,1,1,0,10,10,2,10,9)
      || slink_carrier_interaction(1,1,1,1,10,10,1,10,9)) return 12;
  return 0;
}
''')
    exe = tmp_path / "carrier.exe"
    compiled = subprocess.run([gcc,"-std=c11","-Wall","-Werror",f"-DOPCODE={opcode}",
                               f"-DRESULT={result}","-I",str(ROOT / "patch/src/trade_targets"),
                               str(source),"-o",str(exe)],capture_output=True,text=True,timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    assert subprocess.run([str(exe)],timeout=5).returncode == 0
