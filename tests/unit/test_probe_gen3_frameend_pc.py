"""The census must identify the loaded cartridge before interpreting its RAM."""

from pathlib import Path

import pytest
from lupa import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "lua/tests/probe_gen3_frameend_pc.lua").read_text(encoding="utf-8")
FR_SHA1 = "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"
RR_SHA1 = "964f951a0fdaf209e4ea1344883ef0d557bb3a80"
FR_MD5 = "e26ee0d44e809351c8ce2d73c7400cdd"


def load_census(monkeypatch, rom_hash, requested_title=None):
    if requested_title is None:
        monkeypatch.delenv("SLINK_GEN3_TITLE", raising=False)
    else:
        monkeypatch.setenv("SLINK_GEN3_TITLE", requested_title)
    monkeypatch.delenv("SLINK_STATE", raising=False)
    lua = LuaRuntime(unpack_returned_tuples=True)
    logs = []
    profiles = []
    lua.globals().SLINK_ROOT = ROOT.as_posix()
    lua.globals().console = lua.table(log=lambda s: logs.append(str(s)))
    lua.globals().gameinfo = lua.table(getromhash=lambda: rom_hash)
    lua.globals().event = lua.table(onframeend=lambda callback: None)
    lua.globals().client = lua.table(exit=lambda: None)
    lua.globals().memory = lua.table(read_u8=lambda *_: 0, read_u16_le=lambda *_: 0,
                                     read_u32_le=lambda *_: 0)
    lua.globals().emu = lua.table(frameadvance=lambda: None)
    lua.globals().savestate = lua.table(load=lambda *_: None)
    # The old detector deliberately lies: it called an FR cartridge RR in the
    # 2026-09-21 census. The revised probe must never consult it.
    lua.globals().record_profile = lambda name: profiles.append(str(name))
    lua.execute("""
        package.loaded['memory_gba']={applyProfile=function(_,name) record_profile(name) end}
        package.loaded['game_detect']={detect=function()
            return {variant='radical_red',profile={},game_id='gen3_frlge'}
        end}
    """)
    lua.execute(SOURCE)
    return logs, profiles


def test_hash_pins_firered_despite_old_detector(monkeypatch):
    logs, profiles = load_census(monkeypatch, FR_SHA1, "firered")
    assert profiles == ["vanilla"]
    assert any(f"title=firered sha1={FR_SHA1}" in line for line in logs)
    assert not any("variant=radical_red" in line for line in logs)


def test_hash_selects_rr_without_title_override(monkeypatch):
    logs, profiles = load_census(monkeypatch, RR_SHA1)
    assert profiles == ["radical_red"]
    assert any(f"title=radical_red sha1={RR_SHA1}" in line for line in logs)


@pytest.mark.parametrize("rom_hash", [RR_SHA1, "0" * 40])
def test_title_mismatch_or_unknown_cartridge_is_refused(monkeypatch, rom_hash):
    with pytest.raises(LuaError, match="title mismatch|unadmitted Gen 3 ROM"):
        load_census(monkeypatch, rom_hash, "firered")


def test_md5_admission_still_records_pinned_sha1(monkeypatch):
    logs, profiles = load_census(monkeypatch, FR_MD5.upper(), "firered")
    assert profiles == ["vanilla"]
    assert any(f"title=firered sha1={FR_SHA1}" in line for line in logs)
