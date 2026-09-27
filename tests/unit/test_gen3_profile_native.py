"""C5-6: tools/gen_gen3_profile.py's native (companion) block must not depend on
archive/gen3-old-client:lua/mailbox.lua or archive/gen3-old-client:lua/peer_ghost_npc.lua -- C5-6 deletes both files. It is generated from
patch/src/handlers.c instead (docs/gen3/research/c5_6_deletion_plan_2026-09-24.md risk 4).

This runs native_block() against a REPO that carries ONLY patch/src/handlers.c (no lua/ dir
at all), so a regression that reintroduces a read of either deleted Lua file fails loudly
with FileNotFoundError instead of silently passing because the real checkout still has them.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest

from tools import gen_gen3_profile as g

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = REPO / "patch" / "src" / "handlers.c"


def _isolated_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A REPO subset containing only patch/src/handlers.c -- notably NOT archive/gen3-old-client:lua/mailbox.lua or
    archive/gen3-old-client:lua/peer_ghost_npc.lua, which this generator must no longer read."""
    dest = tmp_path / "patch" / "src" / "handlers.c"
    dest.parent.mkdir(parents=True)
    dest.write_text(HANDLERS.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_native_block_does_not_need_the_deleted_lua_files(monkeypatch, tmp_path) -> None:
    isolated = _isolated_repo(tmp_path)
    assert not (isolated / "lua").exists()  # the scrape targets C5-6 deletes are simply absent
    monkeypatch.setattr(g, "REPO", isolated)
    got = g.native_block()
    monkeypatch.undo()
    want = g.native_block()  # the real checkout, same handlers.c content -> byte-identical
    assert got == want
    assert got["BASE"] == 0x0203F800 and got["OP_RIVAL_SWAP"] == 28  # not an empty/trivial dict
    for where in got["_src"].values():
        assert where.startswith("patch/src/handlers.c:")


def test_native_block_fails_loudly_without_handlers_c(monkeypatch, tmp_path) -> None:
    """No fallback to some other source: an absent patch/src/handlers.c must not silently
    produce a partial or empty native block."""
    monkeypatch.setattr(g, "REPO", tmp_path)  # no patch/src/handlers.c under here at all
    with pytest.raises(FileNotFoundError):
        g.native_block()


def test_native_block_matches_committed_profile() -> None:
    """The committed data/games/gen3_rr/profile.json's native block (minus _src, which is a
    file:line citation and so is allowed to move) must already equal a fresh generation --
    i.e. nobody hand-edited profile.json out of step with the generator."""
    import json

    profile = json.loads((REPO / "data/games/gen3_rr/profile.json").read_text(encoding="utf-8"))
    committed = dict(profile["native"])
    committed.pop("_src")
    fresh = g.native_block()
    fresh.pop("_src")
    assert committed == fresh


def test_v2_abi_is_read_from_shared_header():
    abi = g.native_abi()
    c = abi["constants"]
    assert c["SLINK_ABI_VERSION"] == 2
    assert c["SLINK_OP_TRADE_PREPARE"] == 29
    assert c["SLINK_OP_MATCH_CALL"] == 32
    assert c["SLINK_SUCCESS_MILESTONES"] == 31
    fields = abi["structs"]["SlinkMailboxV2"]["fields"]
    assert fields["ack_seq"] == {"offset": 0x0C, "width": 2, "count": 1}
    assert fields["reason"] == {"offset": 0x0E, "width": 2, "count": 1}
    assert fields["args"] == {"offset": 0x10, "width": 1, "count": 32}
    assert fields["result"] == {"offset": 0x30, "width": 1, "count": 16}
    assert fields["capabilities"] == {"offset": 0x40, "width": 4, "count": 1}
    assert fields["session_epoch"] == {"offset": 0x44, "width": 4, "count": 1}
    assert abi["structs"]["SlinkMailboxV2"]["size"] == 0x50
    assert abi["structs"]["SlinkTradeWitnessV2"]["fields"]["milestone_seq"] == {
        "offset": 0x20, "width": 2, "count": 5}
    assert abi["structs"]["SlinkCallRecordV2"]["size"] == 36
    assert abi["structs"]["SlinkCallWitnessV2"]["size"] == 32
    assert abi["structs"]["SlinkInfoV2"]["size"] == 288
    assert abi["structs"]["SlinkInfoV2"]["fields"]["text"]["offset"] == 32
    assert {name: c[name] for name in ("SLINK_REASON_UNCERTAIN", "SLINK_REASON_IDENTITY",
                                     "SLINK_REASON_CLIENT_TOO_OLD")} == {
        "SLINK_REASON_UNCERTAIN": 11, "SLINK_REASON_IDENTITY": 12, "SLINK_REASON_CLIENT_TOO_OLD": 13}


def test_unqualified_v2_targets_emit_no_native_binding():
    for title in ("firered", "leafgreen", "emerald", "radical_red"):
        assert g.native_block(title) is None


def test_v2_header_parser_refuses_unknown_field_types(monkeypatch, tmp_path):
    path = tmp_path / "patch/src/trade_targets/abi.h"
    path.parent.mkdir(parents=True)
    source = (REPO / "patch/src/trade_targets/abi.h").read_text()
    path.write_text(source.replace("uint32_t session_epoch;", "void *session_epoch;", 1))
    monkeypatch.setattr(g, "REPO", tmp_path)
    with pytest.raises(ValueError, match="unsupported ABI declaration"):
        g.native_abi()


@pytest.mark.parametrize("declaration", ["SLINK_OP_PING = 1", "SLINK_REASON_IDENTITY = 12"])
def test_v2_header_parser_refuses_implicit_enum_rows(monkeypatch, tmp_path, declaration):
    path = tmp_path / g.ABI_SRC
    path.parent.mkdir(parents=True)
    source = (REPO / g.ABI_SRC).read_text()
    path.write_text(source.replace(declaration, declaration.split(" = ")[0], 1))
    monkeypatch.setattr(g, "REPO", tmp_path)
    with pytest.raises(ValueError, match="unsupported ABI enum declaration"):
        g.native_abi()


@pytest.mark.parametrize("options", [[], ["--check"], ["--expansion", g.EXPANSION_BUILD]])
def test_main_reports_missing_input_without_a_traceback_or_partial_profiles(monkeypatch, tmp_path, capsys, options):
    monkeypatch.setattr(g, "REPO", tmp_path)
    monkeypatch.setattr(g.sys, "argv", ["gen_gen3_profile.py", *options])
    assert g.main() == 1
    stderr = capsys.readouterr().err
    assert stderr.strip() and "Traceback" not in stderr
    assert list(tmp_path.rglob("profile.json")) == []


def test_python_v2_layout_matches_host_c_sizeof_and_offsetof(tmp_path):
    compiler = os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not compiler:
        pytest.skip("host C compiler unavailable")
    abi = g.native_abi()
    expected, statements = {}, []
    for name, layout in abi["structs"].items():
        expected[name] = layout["size"]
        statements.append(f'printf("{name}=%zu\\n", sizeof({name}));')
        for field, descriptor in layout["fields"].items():
            expected[f"{name}.{field}"] = descriptor["offset"]
            statements.append(f'printf("{name}.{field}=%zu\\n", offsetof({name}, {field}));')
    source, executable = tmp_path / "abi_layout.c", tmp_path / "abi_layout.exe"
    source.write_text('#include "abi.h"\n#include <stdio.h>\nint main(void) {\n'
                      + "\n".join(statements) + "\nreturn 0;\n}\n")
    subprocess.run([compiler, "-std=c11", "-I", str((REPO / g.ABI_SRC).parent),
                    str(source), "-o", str(executable)], check=True, capture_output=True, text=True)
    run = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
    actual = {name: int(value) for name, value in (line.split("=") for line in run.stdout.splitlines())}
    assert actual == expected


def test_legacy_emerald_stub_is_absent_from_frlg_pack():
    profile = json.loads((REPO / "data/games/gen3_frlg/profile.json").read_text())
    assert "emerald" not in profile["titles"]
