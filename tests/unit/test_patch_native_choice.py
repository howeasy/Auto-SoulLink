"""Native chooser result boundary: waiting is distinct from a real cancellation."""
import os
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.parametrize("emerald",[False,True])
def test_native_choice_wait_selection_and_cancel(tmp_path,emerald):
    gcc=os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:pytest.skip("host C compiler required")
    source=tmp_path/"choice.c"
    prefix='#define SLINK_TARGET_CARRIER_CANCEL 0xffu\n' if emerald else ''
    source.write_text(prefix+r'''
#include "native_choice.h"
int main(void) {
 uint8_t result=99;
 if (slink_native_choice_result(SLINK_CHOICE_PENDING,&result)!=0 || result!=99) return 1;
 if (slink_native_choice_result(3,&result)!=1 || result!=3) return 2;
#ifdef SLINK_TARGET_CARRIER_CANCEL
 if (SLINK_CHOICE_PENDING!=0xffff || slink_native_choice_result(0xff,&result)!=1 || result!=7) return 3;
#else
 if (slink_native_choice_result(0xff,&result)!=0) return 3;
#endif
 if (slink_native_choice_result(0xffff,&result)!=0) return 4;
 return 0;
}
''')
    exe=tmp_path/"choice.exe"
    result=subprocess.run([gcc,"-std=c11","-Wall","-Werror","-I",str(ROOT/"patch/src/trade_targets"),str(source),"-o",str(exe)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert subprocess.run([str(exe)]).returncode==0
