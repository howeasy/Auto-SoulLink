"""Native Match Call text must fit, preserve names, and fall back as Gen 2 does."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_call_text_named_generic_and_bounded(tmp_path):
    gcc = os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("set SLINK_HOST_GCC")
    source = tmp_path / "text.c"
    source.write_text(r'''
#include "call_text.h"
#include <string.h>
static const uint8_t names[412][11]={[1]={0xbb,0xff},[2]={0xbc,0xff}};
int main(void) {
 SlinkCallRecordV2 r={0};uint8_t out[258];
 memset(r.trainer,0xff,8);memset(r.caller_nick,0xff,11);memset(r.receiver_nick,0xff,11);
 r.event=1;r.has_names=1;r.trainer[0]=0xbd;r.caller_species=1;r.receiver_species=2;
 memset(out,0x55,sizeof(out));
 if (!slink_call_text(out,256,&r,&names[0][0],411)) return 1;
 if (out[0]!=0xbd || out[256]!=0x55 || out[257]!=0x55) return 2;
 if (!memchr(out,0xbc,256) || !memchr(out,0xbb,256)) return 3;
 r.caller_nick[0]=0xbe;
 slink_call_text(out,256,&r,&names[0][0],411);
 if (!memchr(out,0xbe,256)) return 4;
 r.receiver_species=0;
 slink_call_text(out,256,&r,&names[0][0],411);
 if (out[0]!=0xad) return 5; /* generic fallen starts ...Hello */
 r.event=2;slink_call_text(out,256,&r,&names[0][0],411);
 if (!memchr(out,0xbb+('D'-'A'),256)) return 6;
 r.event=3;r.has_names=0;
 if (!slink_call_text(out,256,&r,&names[0][0],411)) return 7;
 memset(out,0x55,sizeof(out));
 if (slink_call_text(out,8,&r,&names[0][0],411) || out[7]!=0xff || out[8]!=0x55) return 8;
 return 0;
}
''')
    exe = tmp_path / "text.exe"
    built = subprocess.run([gcc, "-std=c11", "-Wall", "-Werror", "-I",
                            str(ROOT / "patch/src/trade_targets"), str(source), "-o", str(exe)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(exe)], timeout=5).returncode == 0
