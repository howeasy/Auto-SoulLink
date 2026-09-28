"""Native panel lifecycle through the mailbox and display engine boundary."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_panel_ack_is_not_drawn_and_text_is_owned_until_close(tmp_path):
    gcc = os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("set SLINK_HOST_GCC")
    source = tmp_path / "panel.c"
    source.write_text(r'''#include "panel_producer.h"
#include <string.h>
static int safe=1, starts, status;
static const SlinkInfoV2 *owned;
static int can_open(void *p) { (void)p;return safe; }
static int start(void *p,const SlinkInfoV2 *i) { (void)p;starts++;owned=i;return 1; }
static int poll(void *p,uint8_t *result) { (void)p;*result=0x7f;return status; }
int main(void) {
  SlinkPanelProducer s={0};SlinkMailboxV2 m={0};SlinkInfoV2 i={0};
  SlinkPanelEngine e={0,can_open,start,poll};
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
  i.text[0][31]=0xff;m.seq=i.request_seq=4;m.opcode=SLINK_OP_SHOW_INFO;safe=0;
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
''')
    exe = tmp_path / "panel.exe"
    result = subprocess.run([gcc, "-std=c11", "-Wall", "-Werror", "-I",
                             str(ROOT / "patch/src/trade_targets"), str(source), "-o", str(exe)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(exe)], timeout=5)
    assert result.returncode == 0
