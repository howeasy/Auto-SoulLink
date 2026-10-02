"""Cross-card consistency: the NDS record lengths and ABI constants live in three copies (C bindings in
patch/src/nds/common/record_binding.h, Python tools/nds_pkm45.py, Lua lua/nds/pkm45_crypto.lua) and must
agree. A host-C program prints the C values from the REAL headers; the Python and Lua sides are driven
against them. Absent host gcc skips by name (SLINK_REQUIRE_HOST_CC=1 hard-fails); revert controls mutate a
temp copy of the headers and show the same comparison goes red.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import lupa
import pytest

from tools import nds_pkm45 as oracle

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "patch/src/nds/common"
LUA_MODULE = ROOT / "lua/nds/pkm45_crypto.lua"
CC_FLAGS = ["-std=c11", "-Wall", "-Werror"]
BINDINGS = ("gen3_pk3", "gen4_pk4", "gen5_pk5")
EXPECTED = {  # PK45 binding -> (stored_len, party_len, effective trade stage len)
    "gen4_pk4": (oracle.STORED_SIZE, oracle.PARTY_LEN_GEN4, oracle.PARTY_LEN_GEN4),
    "gen5_pk5": (oracle.STORED_SIZE, oracle.PARTY_LEN_GEN5, oracle.PARTY_LEN_GEN5),
}
PINNED_CAPS = {
    "SLINK_CAP_DURABLE_TRADE": 1,
    "SLINK_CAP_INFO_PANEL": 2,
    "SLINK_CAP_NATIVE_SOUND": 4,
    "SLINK_CAP_EXPLODE": 8,
    "SLINK_CAP_RIVAL_SWAP": 16,
    "SLINK_CAP_BATTLE_CALC": 32,
    "SLINK_CAP_MATCH_CALL": 64,
}


# ponytail: gcc discovery copied from test_nds_common_producers.py rather than importing its internals.
def _find_gcc():
    for cand in (os.environ.get("SLINK_HOST_GCC"), shutil.which("gcc")):
        if cand:
            return cand
    bases = [ROOT]
    git = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if git.returncode == 0 and git.stdout.strip():
        bases.append((ROOT / git.stdout.strip()).resolve().parent)
    for base in bases:
        for pattern in ("*/bin/gcc.exe", "*/*/bin/gcc.exe"):
            for gcc in sorted((base / ".cache" / "build-tools").glob(pattern)):
                if (gcc.parent.parent / "libexec").is_dir():  # a bare bin/ shim has no cc1
                    return str(gcc)
    return None


def _gcc():
    gcc = _find_gcc()
    if not gcc:
        reason = (
            "no host C compiler (set SLINK_HOST_GCC, put gcc on PATH, or provide "
            ".cache/build-tools/*/bin/gcc.exe); NDS cross-card C probe did NOT run"
        )
        if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return gcc


def _cap_names(header_dir: Path) -> list[str]:
    return re.findall(
        r"^\s*(SLINK_CAP_\w+)\s*=", (header_dir / "abi.h").read_text(encoding="utf-8"), re.M
    )


def _c_values(tmp: Path, include: Path) -> dict:
    """Compile and run a probe against the headers in `include`; returns what C says."""
    prints = [
        f'    printf("bind {n} %u %u %u %u\\n", slink_binding_{n}.stored_len, slink_binding_{n}.party_len,'
        f" slink_binding_{n}.trade_stage_len, slink_binding_stage_len(&slink_binding_{n}, SLINK_STAGE_OP_TRADE));"
        for n in BINDINGS
    ]
    prints += [f'    printf("cap {c} %u\\n", (unsigned){c});' for c in _cap_names(include)]
    src = (
        '#include <stdio.h>\n#include "record_binding.h"\nint main(void) {\n'
        '    printf("abi %u\\n", (unsigned)SLINK_ABI_VERSION);\n'
        + "\n".join(prints)
        + "\n    return 0;\n}\n"
    )
    (tmp / "probe.c").write_text(src)
    exe = tmp / "probe.exe"
    done = subprocess.run(
        [_gcc(), *CC_FLAGS, "-I", str(include), str(tmp / "probe.c"), "-o", str(exe)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    vals = {"binds": {}, "caps": {}}
    for line in out.stdout.splitlines():
        kind, *rest = line.split()
        if kind == "abi":
            vals["abi"] = int(rest[0])
        elif kind == "bind":
            vals["binds"][rest[0]] = tuple(int(x) for x in rest[1:])
        else:
            vals["caps"][rest[0]] = int(rest[1])
    return vals


def _mismatches(c: dict) -> list[str]:
    """Every way the C values disagree with the Python oracle and the pinned vocabulary."""
    bad = []
    for name, (stored, party, stage) in EXPECTED.items():
        got = c["binds"].get(name)
        if got is None or (got[0], got[1], got[3]) != (stored, party, stage):
            bad.append(f"{name}: C {got} != oracle {(stored, party, stage)}")
        elif got[2] not in (
            0,
            party,
        ):  # raw trade_stage_len: 0 means party_len, or explicitly party_len
            bad.append(f"{name}: trade_stage_len {got[2]}")
    if c["abi"] != 3:
        bad.append(f"ABI version {c['abi']} != 3")
    if c["caps"] != PINNED_CAPS:
        bad.append(f"capability vocabulary {c['caps']} != pinned")
    return bad


@pytest.fixture(scope="module")
def c_real(tmp_path_factory):
    return _c_values(tmp_path_factory.mktemp("xcard"), COMMON)


def test_host_c_matches_python_oracle_and_pinned_vocabulary(c_real):
    assert c_real["binds"]["gen3_pk3"][:2] == (80, 100)  # Gen 3 is not a PK45 record
    assert _mismatches(c_real) == []
    assert (oracle.STORED_SIZE, oracle.PARTY_LEN_GEN4, oracle.PARTY_LEN_GEN5) == (0x88, 0xEC, 0xDC)


# ------------------------------------------------------------------------------- Lua length acceptance


def _lua():
    lua = lupa.LuaRuntime()
    return lua.eval("function(s) return assert(load(s, '=pkm45'))() end")(
        LUA_MODULE.read_text(encoding="utf-8")
    )


def _accepts(result) -> bool:
    """decrypt_* returns (record, info) on success and (nil, reason) on failure."""
    rec = result[0] if isinstance(result, tuple) else result
    return rec is not None


def test_lua_accepts_exactly_the_c_lengths(c_real):
    m = _lua()
    stored = c_real["binds"]["gen4_pk4"][0]
    assert c_real["binds"]["gen5_pk5"][0] == stored
    enc = oracle.encrypt_stored(bytes((i * 37 + 11) & 0xFF for i in range(stored)))
    assert _accepts(m.decrypt_stored(enc))
    assert not _accepts(m.decrypt_stored(enc[:-1])) and not _accepts(m.decrypt_stored(enc + b"\0"))
    for name in ("gen4_pk4", "gen5_pk5"):
        party = c_real["binds"][name][1]
        penc = oracle.encrypt_party(bytes((i * 29 + 5) & 0xFF for i in range(party)), party)
        assert _accepts(m.decrypt_party(penc, party)), name
        # the party length is a Lua parameter: the C length is accepted, any other one refused
        assert not _accepts(m.decrypt_party(penc, party + 2)), name
        assert not _accepts(m.decrypt_party(penc, party - 2)), name
        assert not _accepts(m.decrypt_party(penc[:-2], party)), name
    # the Lua-side stored constant is the same literal the C bindings carry
    assert "local HEADER, BLOCK, BODY_END = 8, 0x20, 0x88" in LUA_MODULE.read_text(encoding="utf-8")


def test_lua_block_order_equals_oracle_for_every_row():
    m = _lua()
    for row in range(32):
        pid = row << 13
        assert tuple(m.block_order(pid).values()) == oracle.block_order(pid)


def test_oracle_rows_are_generated_not_copied():
    assert "itertools.permutations" in (ROOT / "tools/nds_pkm45.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------- ABI text and doc tripwire


def test_abi_version_text_and_reader_rule_are_documented():
    abi = (COMMON / "abi.h").read_text(encoding="utf-8")
    readme = (COMMON / "README.md").read_text(encoding="utf-8")
    assert re.search(r"#define SLINK_ABI_VERSION 3u\b", abi)
    for text in (abi, readme):
        assert "READER RULE" in text and "ABI >= 3" in text and "save_status == 2" in text


def test_readme_does_not_claim_abi_version_2_for_nds():
    abi = (COMMON / "abi.h").read_text(encoding="utf-8")
    readme = (COMMON / "README.md").read_text(encoding="utf-8")
    assert "SLINK_ABI_VERSION 3u" in abi
    assert "ABI version 2" not in readme


# ------------------------------------------------------------------------------- revert controls


def _mutated(tmp: Path, old: str, new: str, fname: str) -> Path:
    inc = tmp / "inc"
    shutil.copytree(COMMON, inc)
    p = inc / fname
    text = p.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return inc


@pytest.mark.parametrize(
    "old,new,fname",
    [
        (
            "0x88, 0xEC, SLINK_MAX_RECORD, 0, 5, 0x0C",
            "0x88, 0xED, SLINK_MAX_RECORD, 0, 5, 0x0C",
            "record_binding.h",
        ),
        (
            "0x88, 0xDC, SLINK_MAX_RECORD, 0, 0, 0x0C",
            "0x84, 0xDC, SLINK_MAX_RECORD, 0, 0, 0x0C",
            "record_binding.h",
        ),
        ("SLINK_CAP_MATCH_CALL = 1u << 6", "SLINK_CAP_MATCH_CALL = 1u << 7", "abi.h"),
    ],
)
def test_revert_control_mutated_header_goes_red(tmp_path, old, new, fname):
    assert _mismatches(_c_values(tmp_path, _mutated(tmp_path, old, new, fname))), (
        "comparison cannot fail"
    )


def test_revert_control_unmutated_copy_stays_green(tmp_path):
    inc = tmp_path / "inc"
    shutil.copytree(COMMON, inc)
    assert _mismatches(_c_values(tmp_path, inc)) == []
