"""Host-C SOURCE/MODEL for C5 layout and the real trade binding; no PHYSICAL claim."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.unit.test_gen4_sound_codes import CC_FLAGS, _gcc

ROOT = Path(__file__).resolve().parents[2]
GEN4 = ROOT / "patch/src/nds/gen4"
COMMON = ROOT / "patch/src/nds/common"

if os.name == "nt":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x8003)


def compile_c(tmp, source, *, sources=(), includes=(), defines=()):
    tmp.mkdir(parents=True, exist_ok=True)
    driver = tmp / "driver.c"
    driver.write_text(source, encoding="utf-8")
    exe = tmp / "probe.exe"
    command = [_gcc(), *CC_FLAGS, *defines]
    for directory in (*includes, GEN4, COMMON):
        command += ["-I", str(directory)]
    command += [str(driver), *map(str, sources), "-o", str(exe)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return exe


LAYOUT_C = r'''
#include "beacon.h"
#include "trade.h"
#include <stdio.h>
#include <string.h>
static uint32_t frame(void *p) { (void)p; return 1; }
int main(void) {
    struct { uint32_t before; SlinkGen4State st; uint32_t after; } box;
    SlinkGen4TradeSeam seam;
    SlinkTradeWitnessV2 witness;
    SlinkRecordStageV1 stage;
    memset(&box,0,sizeof box); memset(&seam,0,sizeof seam);
    memset(&witness,0,sizeof witness); memset(&stage,0,sizeof stage);
    box.before=0x1234; box.after=0x5678; seam.frame=frame;
    box.st.trade.layout=1;
    if (Slink_Gen4TradeState_LayoutValid(&box.st.trade)) return 1;
    box.st.trade.layout=SLINK_GEN4_STATE_TRADE_LAYOUT;
    if (!Slink_Gen4TradeState_LayoutValid(&box.st.trade)) return 2;
    box.st.trade.seam=seam;
    if (!Slink_Gen4TradePolicy_Init(&box.st.trade.policy,&box.st.trade.seam,&witness,&stage,1)) return 3;
    if (box.before!=0x1234 || box.after!=0x5678) return 4;
    if (box.st.trade.policy.seam!=&box.st.trade.seam) return 5;
    if (box.st.trade.policy.engine.context!=&box.st.trade.policy) return 6;
    if (box.st.trade.policy.decoder_ctx.owner!=&box.st.trade.policy) return 7;
    box.st.trade.caps=SLINK_GEN4_TRADE_CAPABILITIES;
    if (box.st.trade.policy.magic!=SLINK_GEN4_TRADE_POLICY_MAGIC) return 8;
    Slink_Gen4TradePolicy_Service(&box.st.trade.policy,NULL);
    printf("%zu %zu %zu %zu %zu\n",sizeof(SlinkGen4StateTrade),sizeof(SlinkGen4TradePolicy),
           offsetof(SlinkGen4StateTrade,policy),offsetof(SlinkGen4StateTrade,seam),
           offsetof(SlinkGen4StateTrade,caps));
    return 0;
}
'''


def test_layout_recipe_typechecks_and_initialization_stays_inside_allocated_state(tmp_path):
    executable = compile_c(tmp_path, LAYOUT_C)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    size, policy_size, policy_off, seam_off, caps_off = map(int, result.stdout.split())
    assert policy_size > 556  # former producer-only allocation, independently measured before amendment
    assert policy_off + policy_size <= seam_off < caps_off < size
    assert policy_off % 4 == seam_off % 4 == 0


def test_declared_trade_recipe_uses_embedded_policy_and_persistent_seam():
    text = (GEN4 / "trade.h").read_text(encoding="utf-8")
    assert "Slink_Gen4TradePolicy_Init(&st->trade.policy, &st->trade.seam" in text
    assert "Slink_Gen4TradePolicy_Service(&st->trade.policy, m)" in text
    assert "Slink_Gen4Trade_CommitEntered(&st->trade.policy, slot)" in text
    assert "Slink_Gen4Trade_Commit(&st->trade.policy, slot)" in text
