"""describe_rom / family_of know the Emerald Expansion reference build, by exact sha1 only.

The 32 MiB build is not a 16 MiB revision-0 cartridge, so the stock Gen 3 gate refuses every
BPEE of that size. The one exception is the pinned reference ROM (the sha1 in the gen3_exp pack's
profile.json); any other 32 MiB BPEE-header file keeps the existing refusal.
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

from server import upr_pipeline as P

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ROM = os.path.join(ROOT, "patch", "build", "gen3_pokeemerald.gba")
PROFILE = os.path.join(ROOT, "data", "games", "gen3_exp", "28877d73", "profile.json")
REFUSAL = "Emerald header is not a supported 16 MiB revision-0 cartridge"


def _pin() -> str:
    with open(PROFILE, encoding="utf-8") as f:
        return json.load(f)["source"]["rom_sha1"]


def _bpee(size: int) -> bytes:
    rom = bytearray(size)
    rom[0xAC:0xB0] = b"BPEE"
    return bytes(rom)


def test_the_pinned_reference_rom_is_a_clean_expansion_cartridge():
    if not os.path.isfile(ROM):
        pytest.skip("patch/build/gen3_pokeemerald.gba is not built here")
    assert hashlib.sha1(open(ROM, "rb").read()).hexdigest() == _pin(), "the staged build is not the pinned one"
    info = P.describe_rom(ROM, jar_fork=False)       # no randomizer is involved, so no fork jar
    assert info["clean"] is True and info["kind"] == "clean"
    assert info["family"] == P.FAMILY_GEN3_EXP == "gen3_exp"
    assert info["variant"] == "Emerald Expansion"
    assert info["title"].startswith("Emerald Expansion")
    assert P.family_of({"a": ROM, "b": ROM}) == "gen3_exp"


def test_another_32mib_bpee_is_refused_with_the_existing_message(tmp_path):
    path = tmp_path / "other.gba"
    path.write_bytes(_bpee(32 << 20))
    assert hashlib.sha1(path.read_bytes()).hexdigest() != _pin()
    info = P.describe_rom(str(path), jar_fork=True)
    assert info["clean"] is False and info["title"] == REFUSAL
    assert "family" not in info


def test_a_one_bit_change_to_the_pinned_rom_is_refused(tmp_path):
    if not os.path.isfile(ROM):
        pytest.skip("patch/build/gen3_pokeemerald.gba is not built here")
    data = bytearray(open(ROM, "rb").read())
    data[0x200000] ^= 1
    path = tmp_path / "flipped.gba"
    path.write_bytes(bytes(data))
    info = P.describe_rom(str(path), jar_fork=True)
    assert info["clean"] is False and info["title"] == REFUSAL


def test_the_sixteen_mib_gates_are_unchanged():
    assert P.GEN3_ROM_SIZE == 16 << 20
    assert P.gen3_title(_bpee(32 << 20)) is None            # the stock gate never widens
    assert P.gen3_title(_bpee(16 << 20)) == "emerald"


def test_a_mixed_expansion_and_emerald_pair_is_refused(tmp_path):
    if not os.path.isfile(ROM):
        pytest.skip("patch/build/gen3_pokeemerald.gba is not built here")
    emerald = tmp_path / "emerald.gba"
    emerald.write_bytes(_bpee(16 << 20))
    with pytest.raises(P.UprPipelineError, match="different families"):
        P.family_of({"a": ROM, "b": str(emerald)})
