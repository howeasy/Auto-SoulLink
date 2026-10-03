"""Toolchain falsifiers for the shared NDS companion ABI (card NDS-8).

abi.h must build in two toolchains: host gcc (plain C11) and mwccarm 2.0/sp2p2,
which has no <stdint.h> and parses C11 _Static_assert as a declaration. compat.h
owns that one difference, so the MWERKS branch is walked here on host gcc with
-D__MWERKS__ and a POISONED <stdint.h>: if the branch ever falls back to the host
header, the stub fires and the compile fails. That is the proof, not the exit code.

A green compile only proves nothing is missing. The assert macro is therefore
falsified by mutation: a copy of abi.h with one condition made FALSE must fail
under -D__MWERKS__, while the unmutated copy of the same bytes compiles under the
same flags. The control is what keeps the falsifier non-vacuous (an unrelated
breakage would otherwise "pass" the mutant test).

Compiler discovery mirrors tests/unit/test_nds_common_producers.py; absence skips
with a named reason unless SLINK_REQUIRE_HOST_CC=1, so an all-skip run cannot be
mistaken for an all-pass run.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "patch/src/nds/common"
CC_FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
# One assert per ABI invariant; pinned so adding or dropping one is deliberate.
ABI_ASSERT_COUNT = 27
STDINT_MARKER = "SLINK_ABI_COMPAT_STDINT_WAS_INCLUDED"
# gcc >= 9 names the array in that diagnostic, older gcc does not; either way the only
# negative-size array in the translation unit is one this macro created.
NEGATIVE_ARRAY = re.compile(r"size of array '?slink_static_assert_\d+'? is negative"
                            r"|size of array is negative")


def _find_gcc():
    """env SLINK_HOST_GCC, PATH, then <repo>/.cache/build-tools (worktree safe)."""
    for cand in (os.environ.get("SLINK_HOST_GCC"), shutil.which("gcc")):
        if cand:
            return cand
    bases = [ROOT]
    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
                         capture_output=True, text=True, timeout=30)
    if git.returncode == 0 and git.stdout.strip():
        bases.append((ROOT / git.stdout.strip()).resolve().parent)
    for base in bases:
        tools = base / ".cache" / "build-tools"
        for pattern in ("*/bin/gcc.exe", "*/*/bin/gcc.exe"):
            for gcc in sorted(tools.glob(pattern)):
                if (gcc.parent.parent / "libexec").is_dir():  # a bare bin/ shim has no cc1
                    return str(gcc)
    return None


def _gcc():
    gcc = _find_gcc()
    if not gcc:
        reason = ("no host C compiler (set SLINK_HOST_GCC, put gcc on PATH, or provide "
                  ".cache/build-tools/*/bin/gcc.exe); NDS ABI compat falsifiers did NOT run")
        if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return gcc


def test_host_c_compiler_is_discoverable():
    """All-skipped must be distinguishable from all-passed."""
    done = subprocess.run([_gcc(), "--version"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr


def _compile(tmp, name, source, includes=(COMMON,), defines=()):
    src = tmp / f"{name}.c"
    src.write_text(source)
    cmd = [_gcc(), *CC_FLAGS, *defines]
    for inc in includes:
        cmd += ["-I", str(inc)]
    cmd += [str(src), "-o", str(tmp / f"{name}.exe")]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def _ok(tmp, name, source, **kw):
    done = _compile(tmp, name, source, **kw)
    assert done.returncode == 0, done.stderr
    return tmp / f"{name}.exe"


def _run(exe):
    done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stdout + done.stderr + f" exit={done.returncode}"
    return done.stdout


def _poisoned_stdint(tmp):
    """An include dir whose <stdint.h> aborts: any TU that opens it fails loudly."""
    stub = tmp / "nostdint"
    stub.mkdir(exist_ok=True)
    (stub / "stdint.h").write_text(f'#error "{STDINT_MARKER}"\n')
    return stub


def _compile_pair(tmp, name, abi_text):
    """Compile a TU that includes a COPY of abi.h, with compat.h copied beside it so the
    quoted relative include resolves without writing anything into the source tree."""
    sub = tmp / f"{name}_inc"
    sub.mkdir(exist_ok=True)
    (sub / "abi.h").write_text(abi_text)
    (sub / "compat.h").write_text((COMMON / "compat.h").read_text())
    tu = f'#include "{name}_inc/abi.h"\nint main(void) {{ return 0; }}\n'
    return _compile(tmp, name, tu, includes=(_poisoned_stdint(tmp),), defines=("-D__MWERKS__",))


# --------------------------------------------------------------------------- (a) plain C11

ABI_LAYOUT_C = r'''#include <stdio.h>
#include "abi.h"
#define P(n) printf(#n "=%lu\n", (unsigned long)(n))
int main(void) {
  P(SLINK_TITLE_OFFSET); P(SLINK_TITLE_SIZE);
  P(SLINK_RESERVED_OFFSET); P(SLINK_ARENA_SIZE);
  P(sizeof(SlinkMailboxV2)); P(sizeof(SlinkTradeWitnessV2)); P(sizeof(SlinkInfoV2));
  return 0;
}
'''


def test_abi_compiles_and_the_title_region_sits_where_the_ruling_says(tmp_path):
    out = dict(line.split("=") for line in _run(_ok(tmp_path, "layout", ABI_LAYOUT_C)).split())
    assert out == {
        "SLINK_TITLE_OFFSET": "3584",          # 0xE00
        "SLINK_TITLE_SIZE": "64",              # 0x40
        "SLINK_RESERVED_OFFSET": "3584",       # 0xE00
        "SLINK_ARENA_SIZE": "4096",            # 0x1000
        "sizeof(SlinkMailboxV2)": "80",        # 0x50
        "sizeof(SlinkTradeWitnessV2)": "80",   # 0x50
        "sizeof(SlinkInfoV2)": "288",          # 0x120
    }
    title, size = int(out["SLINK_TITLE_OFFSET"]), int(out["SLINK_TITLE_SIZE"])
    assert title == int(out["SLINK_RESERVED_OFFSET"])   # the first bytes of the reserved region
    assert title + size == 0xE40                       # and it ends exactly where the free tail starts
    assert title + size <= int(out["SLINK_ARENA_SIZE"])


def test_abi_asserts_go_through_the_compat_macro_only():
    """Every invariant survives, spelled SLINK_STATIC_ASSERT, so mwccarm never meets a C11
    _Static_assert. Both counts are pinned: the macro may not creep back into abi.h."""
    code = re.sub(r"/\*.*?\*/", "", (COMMON / "abi.h").read_text(), flags=re.S)
    assert "_Static_assert(" not in code
    assert code.count("SLINK_STATIC_ASSERT(") == ABI_ASSERT_COUNT


INCLUDERS_C = r'''#include "record_binding.h"
#include "trade_producer.h"
#include "panel_producer.h"
#include "sound_producer.h"
int main(void)
{
    const SlinkRecordBinding *b[3];
    SlinkTradeProducer tp;
    SlinkPanelProducer pp;
    int ok = 0, i;
    b[0] = &slink_binding_gen3_pk3;
    b[1] = &slink_binding_gen4_pk4;
    b[2] = &slink_binding_gen5_pk5;
    for (i = 0; i < 3; i++) ok += slink_binding_ok(b[i]);
    ok += (int)sizeof(tp) + (int)sizeof(pp);
    return ok > 0 ? 0 : 1;
}
'''


def test_every_includer_of_abi_h_still_compiles(tmp_path):
    """abi.h changed its includes and every assert spelling; nothing else about it moved, so
    the four headers that include it must still build clean and still expose their API."""
    _run(_ok(tmp_path, "includers", INCLUDERS_C))


# --------------------------------------------------------------------------- (b) mwccarm path

MWERCKS_C = r'''#include "abi.h"
int main(void) { return 0; }
'''


def test_stddef_alone_does_not_open_stdint(tmp_path):
    """Premise of the proof below: <stddef.h> must NOT drag in <stdint.h>, otherwise a red
    MWERKS test could be the host libc's doing rather than abi.h's."""
    done = _compile(tmp_path, "stddef", "#include <stddef.h>\nint main(void) { return 0; }\n",
                    includes=(_poisoned_stdint(tmp_path),))
    assert done.returncode == 0, done.stderr
    assert STDINT_MARKER not in done.stderr


def test_mwcc_path_compiles_without_ever_touching_stdint(tmp_path):
    stub = _poisoned_stdint(tmp_path)
    done = _compile(tmp_path, "mwerks", MWERCKS_C, includes=(stub, COMMON), defines=("-D__MWERKS__",))
    assert STDINT_MARKER not in done.stderr, "the MWERKS branch included <stdint.h>"
    assert done.returncode == 0, done.stderr


MWERCKS_TYPES_C = r'''#include "abi.h"
_Static_assert(sizeof(uint8_t) == 1u, "u8 width");
_Static_assert(sizeof(uint16_t) == 2u, "u16 width");
_Static_assert(sizeof(uint32_t) == 4u, "u32 width");
_Static_assert(sizeof(int32_t) == 4u, "s32 width");
/* compat.h spells uint32_t as nitro u32 (unsigned long) where long is 32 bits and as
 * unsigned int on a host whose long is wider, which is how this branch is walked
 * off-target. Both are 32-bit unsigned; the ABI layouts need the width. */
_Static_assert(_Generic((uint32_t)0u, unsigned int: 1, unsigned long: 1, default: 0) == 1,
               "uint32_t must be a 32-bit unsigned type");
_Static_assert(_Generic((uint16_t)0u, unsigned short: 1, default: 0) == 1, "u16 spelling");
int main(void) { return 0; }
'''


def test_mwcc_path_types_keep_the_nitro_widths(tmp_path):
    _ok(tmp_path, "mwerks_types", MWERCKS_TYPES_C,
        includes=(_poisoned_stdint(tmp_path), COMMON), defines=("-D__MWERKS__",))


def test_the_fallback_assert_rejects_a_false_condition_under_mwcc(tmp_path):
    abi = (COMMON / "abi.h").read_text()
    needle = "sizeof(SlinkMailboxV2) == 0x50"
    assert abi.count(needle) == 1, "the mutated condition must be unique or the test is vacuous"
    mutant = abi.replace(needle, "sizeof(SlinkMailboxV2) == 0x51")

    control = _compile_pair(tmp_path, "control", abi)
    assert control.returncode == 0, control.stderr  # the byte-identical copy builds: sound before mutation

    mutated = _compile_pair(tmp_path, "mutant", mutant)
    assert mutated.returncode != 0, "a false SLINK_STATIC_ASSERT compiled clean under -D__MWERKS__"
    assert STDINT_MARKER not in mutated.stderr
    assert NEGATIVE_ARRAY.search(mutated.stderr), mutated.stderr  # the FAILURE came from the assert
