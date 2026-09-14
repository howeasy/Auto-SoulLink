"""F-2: every hook site the client will arm is really in the clean ROM, and every address the
site files carry agrees with the pret-generated profile.

The site JSONs came from gen1/rc; they are re-verified here rather than trusted. Two
independent derivations must agree: RC pinned bytes at a flat offset, the profile pins
symbols from the .sym files. Byte checks need the clean dumps in patch/build/ and skip
loudly without them (the release runner counts that skip as a failure, by design).
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "games" / "gen1_rby"
DUMPS = {"red": "gen1_red.gb", "blue": "gen1_blue.gb", "yellow": "gen1_yellow.gbc"}

PROFILE = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))["titles"]


def _load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def _rom(title: str) -> bytes:
    path = REPO / "patch" / "build" / DUMPS[title]
    if not path.exists():
        pytest.skip(f"{path.name} not present — copy the clean dump into patch/build/")
    data = path.read_bytes()
    assert hashlib.sha1(data).hexdigest() == PROFILE[title]["rom_sha1"], f"{title}: not the clean dump"
    return data


def _flat(bank: int, addr: int) -> int:
    return addr if addr < 0x4000 else bank * 0x4000 + (addr - 0x4000)


def _sites(title: str):
    """(file, site name, site dict) for every pinned execution site of a title."""
    for name in ("engine_signals", "continue_sites", "wild_encounter_sites"):
        for site, d in _load(name)["titles"][title]["sites"].items():
            yield name, site, d


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_pinned_bytes_are_in_the_clean_rom(title):
    rom = _rom(title)
    for name, site, d in _sites(title):
        want = bytes.fromhex(d["expected_hex"])
        assert rom[d["rom_offset"]:d["rom_offset"] + len(want)] == want, f"{name}:{site}"
        assert d["rom_offset"] == _flat(d["bank"], d["address"]), f"{name}:{site} bank/address vs offset"
        pre = d.get("prelude")
        if pre:
            want = bytes.fromhex(pre["expected_hex"])
            assert rom[pre["rom_offset"]:pre["rom_offset"] + len(want)] == want, f"{name}:{site} prelude"


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_site_files_agree_with_the_pret_profile(title):
    """Where a site file names a symbol the profile also has, the addresses must match."""
    prof = PROFILE[title]
    for name, site, d in _sites(title):
        sym = d["symbol"].split("+")[0]
        if sym in prof["rom"]:
            offset = int(d["symbol"].split("+")[1]) if "+" in d["symbol"] else 0
            assert prof["rom"][sym]["flat"] + offset == d["rom_offset"], f"{name}:{site} {d['symbol']}"
    for name in ("engine_signals", "continue_sites", "wild_encounter_sites"):
        t = _load(name)["titles"][title]
        assert t["clean_sha1"] == prof["rom_sha1"], name
        for sym, addr in t.get("addresses", {}).items():
            if sym in prof["ram"]:
                assert prof["ram"][sym] == addr, f"{name} {sym}"
    cont = _load("continue_sites")["titles"][title]
    assert cont["save_file_status"] == prof["ram"]["wSaveFileStatus"]
    assert cont["bank_address"] == prof["ram"]["hLoadedROMBank"]
    wc = _load("write_checkpoint")[title]
    assert wc["BATTLE_FLAG_ADDR"] == prof["ram"]["wIsInBattle"]
    assert wc["FONT_LOADED_ADDR"] == prof["ram"]["wFontLoaded"]
    assert wc["JOY_IGNORE_ADDR"] == prof["ram"]["wJoyIgnore"]
    assert wc["write_safe"]["delay_frame"] == prof["rom"]["DelayFrame"]["addr"]


def test_rc_sites_i_rely_on_are_where_the_plan_says():
    """The two design-critical sites, in the profile's own words."""
    rb, y = PROFILE["red"]["rom"], PROFILE["yellow"]["rom"]
    assert (rb["MainInBattleLoop"]["bank"], rb["MainInBattleLoop"]["addr"]) == (0x0F, 0x4233)
    assert (y["MainInBattleLoop"]["bank"], y["MainInBattleLoop"]["addr"]) == (0x0F, 0x4249)
    assert (rb["RemoveFaintedPlayerMon"]["bank"], rb["RemoveFaintedPlayerMon"]["addr"]) == (0x0F, 0x4741)
    assert (y["RemoveFaintedPlayerMon"]["bank"], y["RemoveFaintedPlayerMon"]["addr"]) == (0x0F, 0x475E)
    assert rb["DelayFrame"]["addr"] == 0x20AF and y["DelayFrame"]["addr"] == 0x1E64
