"""T2 producer admission falsifiers; no ROM or emulator needed."""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("companion_build", ROOT / "patch/tools/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_firered_refuses_rr_mailbox_allocator_overlap():
    with pytest.raises(ValueError, match="overlap.*__malloc_av_"):
        build.validate_arena("firered", 0x0203F800, 0x800)


def test_wrong_base_and_detour_refused_before_compile():
    with pytest.raises(ValueError, match="base ROM"):
        build.validate_base("firered", bytes(0x1000000))
    with pytest.raises(ValueError, match="detour"):
        build.validate_detour(bytes(0x1000), 0x0800051A, bytes.fromhex("3bf1a9f9"))


def test_unqualified_target_cannot_publish_a_payload():
    for target in ("firered", "leafgreen", "emerald"):
        with pytest.raises(ValueError, match="not qualified"):
            build.require_ready(target)


def test_abi_success_requires_native_post_save(tmp_path):
    gcc = os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not gcc:
        pytest.skip("host C compiler absent; set SLINK_HOST_GCC")
    source = tmp_path / "abi.c"
    source.write_text('''#include "abi.h"
int main(void) {
    SlinkTradeWitnessV2 w = {0};
    w.visit_flags = SLINK_VISIT_ACCEPTED | SLINK_PRE_SAVE_CONSENT;
    w.final_result = SLINK_TRADE_COMMITTED;
    w.save_status = SLINK_SAVE_OK;
    w.milestones = (1u << SLINK_PRE_SAVE_OK) | (1u << SLINK_COMMIT_ENTERED)
                 | (1u << SLINK_SCENE_EVOLUTION_DONE);
    if (slink_trade_success_is_durable(&w)) return 1;
    w.milestones |= (1u << SLINK_POST_SAVE_OK);
    if (!slink_trade_success_is_durable(&w)) return 2;
    w.save_status = SLINK_SAVE_FAILED;
    if (slink_trade_success_is_durable(&w)) return 3;
    return 0;
}
''')
    exe = tmp_path / "abi.exe"
    compiled = subprocess.run([gcc, "-std=c11", "-Wall", "-Werror", "-I",
                               str(ROOT / "patch/src/trade_targets"), str(source), "-o", str(exe)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    assert subprocess.run([str(exe)], timeout=5).returncode == 0
