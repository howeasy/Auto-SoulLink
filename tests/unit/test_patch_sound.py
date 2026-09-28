"""Native sound dispatch boundary; ACK is not an audible-output claim."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_native_sound_validates_id_epoch_and_ui_ownership(tmp_path):
    gcc=os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("set SLINK_HOST_GCC")
    source=tmp_path / "sound.c"
    source.write_text(r'''#include "sound_producer.h"
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
''')
    exe=tmp_path / "sound.exe"
    built=subprocess.run([gcc,"-std=c11","-Wall","-Werror","-I",str(ROOT / "patch/src/trade_targets"),
                          str(source),"-o",str(exe)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stderr
    assert subprocess.run([str(exe)],timeout=5).returncode==0


def test_existing_lua_native_sounds_toggle_controls_posting():
    # Shared client behavior on its established RR MODEL fixture; no FR admission claim.
    from tests.unit.test_gen3_native import World

    w=World()
    w.native.config(w.native,w.lua.table(native_sounds=False))
    assert w.native.play_sound(w.native,25) is True
    w.service()
    assert not w.output
    w.native.config(w.native,w.lua.table(native_sounds=True))
    w.native.play_sound(w.native,25)
    w.service()
    assert w.read(w.n["BASE"]+6,2)==19
    assert w.read(w.n["BASE"]+16,2)==25
