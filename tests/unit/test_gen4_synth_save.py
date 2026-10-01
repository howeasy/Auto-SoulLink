"""Falsifiers for tools/gen4_synth_save.py, the disclosed O-33 SYNTH setup for Gen 4.

The owner-save legs follow tests/TESTING.md: an ABSENT save skips with a reason naming it, a
PRESENT save whose content contradicts the expectations FAILS.  The refusals run on a
hermetic image built here from the footer description, so they are covered without owner
files.  Owner saves are read-only and every output is written under tmp_path.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from server.adapters import gen4_codec as codec
from tools import gen4_synth_save as synth

SAVES = Path("C:/slink/g4/saves")
OWNER = {"hgss": "hg_base_26310.SaveRAM", "hge": "hge_a_OOO_630.SaveRAM"}
HGSS = codec.PROFILES["hgss"]


# ---------------------------------------------------------------------------
# A hermetic battery image: bank 0 blank 0xff, bank 1 a valid general + PC block, one party
# mon.  Built from the footer description (include/save.h:33-39), not through the codec.
# ---------------------------------------------------------------------------
def _footer(profile, count, size, slot, crc) -> bytes:
    return struct.pack(profile.footer_fmt, count, size, codec.SAVE_CHUNK_MAGIC, slot, crc)


def _block(profile, body: bytes, size: int, slot: int, count: int) -> bytes:
    data = bytes(body[: size - profile.footer_size]).ljust(size - profile.footer_size, b"\0")
    return data + _footer(profile, count, size, slot, codec.crc16_ccitt(data))


def _image(count: int = 1, pid: int = 0x0BADF00D, otid: int = 0x74C066C6) -> bytes:
    gen_size, pc_at, pc_size = 0xF628, 0xF700, 0x12310   # the spans the owner's saves use
    body = bytearray(gen_size)
    struct.pack_into("<II", body, HGSS.party_off, 6, count)
    for i in range(count):
        plain = bytearray(codec.PARTY_MON_SIZE)
        struct.pack_into("<I", plain, 0, pid + i)
        struct.pack_into("<HHI", plain, 8, 155, 0, otid)          # species, item, OTID
        struct.pack_into("<BxHH", plain, 0x8C, 5, 20, 20)        # level, HP, max HP
        off = HGSS.party_off + 8 + i * codec.PARTY_MON_SIZE
        body[off : off + codec.PARTY_MON_SIZE] = codec.encrypt_party(bytes(plain))
    bank = bytearray(codec.BANK_SIZE)
    bank[:gen_size] = _block(HGSS, bytes(body), gen_size, 0, 1)
    bank[pc_at : pc_at + pc_size] = _block(HGSS, b"", pc_size, 1, 1)
    return b"\xff" * codec.BANK_SIZE + bytes(bank)


def _reseal(image: bytes, variant: str, mutate) -> bytes:
    """Apply ``mutate(block body)`` and re-stamp the newest general block's footer CRC."""
    profile = codec.PROFILES[variant]
    block = codec.parse_save(image, variant).blocks[(1, 0)]
    foot = block.start + block.size - profile.footer_size
    data = mutate(bytearray(image[block.start:foot]))
    out = bytearray(image)
    out[block.start : foot] = data
    fields = list(struct.unpack_from(profile.footer_fmt, out, foot))
    fields[profile.footer_fields.index("crc")] = codec.crc16_ccitt(bytes(data))
    out[foot : foot + profile.footer_size] = struct.pack(profile.footer_fmt, *fields)
    return bytes(out)


def _run(src: Path, out: Path, variant: str = "hgss") -> int:
    return synth.main(["party2", "--profile", variant, "--src", str(src), "--out", str(out)])


def _owner(variant: str) -> bytes:
    path = SAVES / OWNER[variant]
    if not path.is_file():
        pytest.skip(f"absent input save: {path}")
    return path.read_bytes()


def _assert_clone_contract(src: bytes, out: bytes, variant: str) -> None:
    """The card's verification, re-decoded with the codec rather than the tool's own check."""
    a, b = codec.parse_save(src, variant), codec.parse_save(out, variant)
    assert b.bank == a.bank and b.counter == a.counter
    assert len(a.party()) == 1 and len(b.party()) == 2
    template, clone = b.party()[0], b.party()[1]
    assert template == a.party()[0]                       # the source mon is not rewritten
    assert clone["tail_plausible"] and clone["key"] != template["key"]
    assert (clone["species"], clone["level"], clone["otid"]) == (
        template["species"], template["level"], template["otid"])
    # the clone is a same-nature, non-shiny, distinctly named copy
    assert (clone["nature"], clone["shiny"], clone["nickname"]) == (template["nature"], False, "SYNTH")
    assert (clone["stats"], clone["max_hp"]) == (template["stats"], template["max_hp"])
    other = 1 - b.bank
    assert out[other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE] == src[
        other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE
    ]
    pc = b.blocks[(b.bank, 1)]
    assert out[pc.start : pc.start + pc.size] == src[pc.start : pc.start + pc.size]
    # only the two CRC bytes of the newest bank's general footer move; count/size/magic/slot stay
    profile = b.profile
    foot = b.blocks[(b.bank, 0)].start + b.blocks[(b.bank, 0)].size - profile.footer_size
    assert out[foot : foot + profile.footer_size - 2] == src[foot : foot + profile.footer_size - 2]
    assert struct.unpack_from("<H", out, foot + profile.footer_size - 2)[0] != struct.unpack_from(
        "<H", src, foot + profile.footer_size - 2)[0]


# ---------------------------------------------------------------------------
# The written image (owner saves, read-only, skipped by name when absent)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_party2_writes_a_second_mon_the_game_can_deposit(tmp_path, variant):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_owner(variant))
    out = tmp_path / "party2.SaveRAM"
    assert _run(src, out, variant) == synth.WRITTEN
    assert src.read_bytes() == _owner(variant)           # the owner save is never modified
    _assert_clone_contract(src.read_bytes(), out.read_bytes(), variant)


@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_sidecar_records_both_hashes_and_the_clone_identity(tmp_path, variant):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_owner(variant))
    out = tmp_path / "party2.SaveRAM"
    assert _run(src, out, variant) == synth.WRITTEN
    row = json.loads((tmp_path / "party2.SaveRAM.synth.json").read_text(encoding="utf-8"))
    assert row["schema"] == "gen4-synth-v1" and row["kind"] == "party2" and row["profile"] == variant
    assert row["src_sha1"] == hashlib.sha1(src.read_bytes()).hexdigest()
    assert row["out_sha1"] == hashlib.sha1(out.read_bytes()).hexdigest()
    assert row["bank"] == codec.parse_save(src.read_bytes(), variant).bank
    assert row["new_pid"] == codec.parse_save(out.read_bytes(), variant).party()[1]["pid"]
    assert row["otid"] == codec.parse_save(out.read_bytes(), variant).party()[1]["otid"]
    assert row["note"] == synth.NOTE


def test_the_clone_is_deterministic_in_the_source_image(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_owner("hgss"))
    first, second = tmp_path / "a.SaveRAM", tmp_path / "b.SaveRAM"
    assert _run(src, first) == synth.WRITTEN and _run(src, second) == synth.WRITTEN
    assert first.read_bytes() == second.read_bytes()


# ---------------------------------------------------------------------------
# Refusals (hermetic image, so they are covered without owner files)
# ---------------------------------------------------------------------------
def test_refuses_to_write_over_the_source(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    before = src.read_bytes()
    assert _run(src, src) == synth.REFUSED
    assert src.read_bytes() == before
    assert not (tmp_path / "src.SaveRAM.synth.json").exists()


def test_refuses_a_source_that_already_has_two_mons(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    once = tmp_path / "once.SaveRAM"
    assert _run(src, once) == synth.WRITTEN
    twice = tmp_path / "twice.SaveRAM"
    assert _run(once, twice) == synth.REFUSED
    assert not twice.exists() and not (tmp_path / "twice.SaveRAM.synth.json").exists()


def test_refuses_a_source_whose_newest_bank_fails_its_crc(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_reseal(_image(), "hgss", lambda body: bytes(body[:0x100]) + b"\x40" + bytes(body[0x101:])))
    out = tmp_path / "out.SaveRAM"
    assert _run(src, out) == synth.REFUSED
    assert not out.exists()


def test_refuses_a_source_whose_party_record_does_not_decode(tmp_path):
    """A CRC-clean bank whose party record is corrupt must still refuse: no_save is not enough."""
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_reseal(_image(), "hgss", lambda body: bytes(body[:0xA0]) + b"\x40" + bytes(body[0xA1:])))
    out = tmp_path / "out.SaveRAM"
    assert _run(src, out) == synth.REFUSED
    assert not out.exists()


def test_refuses_a_source_with_no_usable_bank(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(bytes(codec.SAVE_SIZE))
    out = tmp_path / "out.SaveRAM"
    assert _run(src, out) == synth.REFUSED
    assert not out.exists()


def test_refuses_an_output_under_the_bizhawk_save_root(tmp_path, monkeypatch):
    root = tmp_path / "Bizhawk"
    (root / "NDS" / "SaveRAM").mkdir(parents=True)
    monkeypatch.setattr(synth, "BIZHAWK_ROOT", root)
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    inside = root / "NDS" / "SaveRAM" / "party2.SaveRAM"
    assert _run(src, inside) == synth.REFUSED
    assert not inside.exists()
    outside = tmp_path / "party2.SaveRAM"          # a sibling is not "under" the root
    assert _run(src, outside) == synth.WRITTEN


def test_an_absent_source_exits_two(tmp_path, capsys):
    assert _run(tmp_path / "nope.SaveRAM", tmp_path / "out.SaveRAM") == synth.ABSENT
    assert "absent source save" in capsys.readouterr().err


def test_the_bind_only_platinum_profile_is_not_offered(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    with pytest.raises(SystemExit):
        _run(src, tmp_path / "out.SaveRAM", "pt")
    assert not (tmp_path / "out.SaveRAM").exists()
