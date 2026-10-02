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


# ---------------------------------------------------------------------------
# bag / egg1 (G2 producer plan): the owner saves are read-only, outputs under tmp_path
# ---------------------------------------------------------------------------
# Independent of the tool: general-block offset of the Balls pocket, from the pret layout
# (items 165, key 50, TMs 101, mail 12, medicine 40, berries 64 slots after the Bag at 0x644;
# hge expands items/key/balls, hg-engine include/constants/item.h:2870-2880).
BALLS_AT = {"hgss": 0x644 + 4 * (165 + 50 + 101 + 12 + 40 + 64), "hge": 0x644 + 4 * (245 + 92 + 101 + 12 + 40 + 64)}
MEDICINE_AT = {"hgss": 0xB64, "hge": 0xD4C}  # FILE: Potion x5 in medicine slot 0 of both owner saves


def _synth(kind: str, src: Path, out: Path, variant: str = "hgss", *extra: str) -> int:
    return synth.main([kind, "--profile", variant, "--src", str(src), "--out", str(out), *extra])


def _assert_only_changed(src: bytes, out: bytes, variant: str, lo: int, hi: int) -> None:
    """Only general-relative bytes [lo, hi) and the newest general footer CRC may differ."""
    s = codec.parse_save(src, variant)
    blk = s.blocks[(s.bank, 0)]
    crc = blk.start + blk.size - 2
    changed = [i for i, (x, y) in enumerate(zip(src, out, strict=True)) if x != y]
    assert changed and crc in changed, "the CRC must be re-stamped"
    assert all(i in (crc, crc + 1) or blk.start + lo <= i < blk.start + hi for i in changed)


@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_the_owner_save_pins_the_bag_layout_the_tool_assumes(variant):
    """FILE evidence for the Bag offset: Potion x5 is medicine slot 0 and the Balls pocket is empty."""
    general = codec.parse_save(_owner(variant), variant).general
    assert struct.unpack_from("<HH", general, MEDICINE_AT[variant]) == (17, 5)  # ITEM_POTION
    n = 24 if variant == "hgss" else 26
    assert all(struct.unpack_from("<HH", general, BALLS_AT[variant] + 4 * i) == (0, 0) for i in range(n))


@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_bag_puts_ten_pokeballs_in_the_first_balls_slot(tmp_path, variant):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "bag.SaveRAM"
    src.write_bytes(_owner(variant))
    assert _synth("bag", src, out, variant) == synth.WRITTEN
    a, b = src.read_bytes(), out.read_bytes()
    assert a == _owner(variant)                                  # the owner save is never modified
    ga, gb = codec.parse_save(a, variant), codec.parse_save(b, variant)
    assert struct.unpack_from("<HH", gb.general, BALLS_AT[variant]) == (4, 10)   # ITEM_POKE_BALL x10
    assert (gb.bank, gb.counter) == (ga.bank, ga.counter) and gb.party() == ga.party()
    assert gb.party()[0]["tail_plausible"]
    other = 1 - gb.bank
    assert b[other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE] == a[
        other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE]
    pc = gb.blocks[(gb.bank, 1)]
    assert b[pc.start : pc.start + pc.size] == a[pc.start : pc.start + pc.size]
    _assert_only_changed(a, b, variant, BALLS_AT[variant], BALLS_AT[variant] + 4)
    row = json.loads((tmp_path / "bag.SaveRAM.synth.json").read_text(encoding="utf-8"))
    assert (row["kind"], row["profile"], row["item"], row["count"]) == ("bag", variant, 4, 10)
    assert row["src_sha1"] == hashlib.sha1(a).hexdigest() and row["out_sha1"] == hashlib.sha1(b).hexdigest()
    assert row["general_off"] == BALLS_AT[variant] and row["before"] == [0, 0] and row["after"] == [4, 10]


def test_a_wrong_bag_offset_would_fail_the_layout_assertion(tmp_path, monkeypatch):
    """Revert test: shift the Party array size by one word and the independent offset check trips."""
    monkeypatch.setattr(synth, "PARTY_ARRAY_SIZE", 0x5B0)
    src, out = tmp_path / "src.SaveRAM", tmp_path / "bag.SaveRAM"
    src.write_bytes(_owner("hgss"))
    assert _synth("bag", src, out) == synth.WRITTEN
    got = codec.parse_save(out.read_bytes(), "hgss").general
    assert struct.unpack_from("<HH", got, BALLS_AT["hgss"]) != (4, 10)


def _bag_image(slots: dict) -> bytes:
    def mutate(body):
        for i, (iid, qty) in slots.items():
            struct.pack_into("<HH", body, BALLS_AT["hgss"] + 4 * i, iid, qty)
        return body
    return _reseal(_image(), "hgss", mutate)


def _balls(image: bytes) -> list:
    g = codec.parse_save(image, "hgss").general
    return [struct.unpack_from("<HH", g, BALLS_AT["hgss"] + 4 * i) for i in range(24)]


def test_bag_never_overwrites_a_slot_and_uses_the_first_empty_one(tmp_path):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_bag_image({0: (3, 7), 1: (2, 1)}))          # Great Ball, Ultra Ball
    assert _synth("bag", src, out, "hgss", "--count", "3") == synth.WRITTEN
    assert _balls(out.read_bytes())[:4] == [(3, 7), (2, 1), (4, 3), (0, 0)]


def test_bag_adds_to_an_existing_pokeball_stack_even_past_an_empty_slot(tmp_path):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_bag_image({0: (3, 7), 2: (4, 5)}))          # an empty slot 1 sits before the stack
    assert _synth("bag", src, out) == synth.WRITTEN
    assert _balls(out.read_bytes())[:3] == [(3, 7), (0, 0), (4, 15)]


def test_bag_refuses_a_full_pocket_and_a_stack_overflow(tmp_path):
    out = tmp_path / "out.SaveRAM"
    full = tmp_path / "full.SaveRAM"
    full.write_bytes(_bag_image(dict.fromkeys(range(24), (3, 1))))   # every slot a Great Ball
    assert _synth("bag", full, out) == synth.REFUSED and not out.exists()
    stack = tmp_path / "stack.SaveRAM"
    stack.write_bytes(_bag_image({0: (4, 995)}))
    assert _synth("bag", stack, out) == synth.REFUSED and not out.exists()
    assert _synth("bag", stack, out, "hgss", "--count", "4") == synth.WRITTEN   # 999 is allowed
    assert _balls(out.read_bytes())[0] == (4, 999)


@pytest.mark.parametrize("count", ["0", "1000"])
def test_bag_refuses_an_out_of_range_count(tmp_path, count):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    assert _synth("bag", src, tmp_path / "out.SaveRAM", "hgss", "--count", count) == synth.REFUSED


@pytest.mark.parametrize("kind", ["bag", "egg1"])
def test_bag_and_egg_refuse_to_write_over_the_source(tmp_path, kind):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    before = src.read_bytes()
    assert _synth(kind, src, src) == synth.REFUSED
    assert src.read_bytes() == before and not (tmp_path / "src.SaveRAM.synth.json").exists()


@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_egg1_appends_a_valid_egg_after_the_last_mon(tmp_path, variant):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "egg.SaveRAM"
    src.write_bytes(_owner(variant))
    assert _synth("egg1", src, out, variant) == synth.WRITTEN
    a, b = src.read_bytes(), out.read_bytes()
    assert a == _owner(variant)
    ga, gb = codec.parse_save(a, variant), codec.parse_save(b, variant)
    assert (gb.bank, gb.counter) == (ga.bank, ga.counter)
    assert len(ga.party()) == 1 and len(gb.party()) == 2
    assert gb.party()[0] == ga.party()[0]                        # the first mon is not rewritten
    egg, player = gb.party()[1], ga.player()
    assert egg["is_egg"] and egg["tail_plausible"] and not egg["shiny"] and not egg["has_nickname"]
    assert egg["key"] != gb.party()[0]["key"] and egg["otid"] == player["id"] and egg["ot_name"] == player["name"]
    assert (egg["species"], egg["nickname"], egg["friendship"], egg["level"]) == (172, "Egg", 1, 1)
    assert (egg["hp"], egg["max_hp"]) == (11, 11) and egg["ball"] == 4 and egg["met_level"] == 0
    assert (egg["egg_location"], egg["met_location"], egg["origin_game"]) == (2000, 0, player["version"])
    assert egg["moves"][:2] == (84, 204) and egg["nature"] % 6 == 0
    # the other bank and the PC block are byte-identical; only the new slot, the count and the CRC move
    other = 1 - gb.bank
    assert b[other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE] == a[
        other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE]
    pc = gb.blocks[(gb.bank, 1)]
    assert b[pc.start : pc.start + pc.size] == a[pc.start : pc.start + pc.size]
    _assert_only_changed(a, b, variant, 0x94, 0x90 + 8 + 2 * codec.PARTY_MON_SIZE)
    row = json.loads((tmp_path / "egg.SaveRAM.synth.json").read_text(encoding="utf-8"))
    assert (row["kind"], row["new_pid"], row["otid"], row["slot"]) == ("egg1", egg["pid"], egg["otid"], 1)
    assert row["src_sha1"] == hashlib.sha1(a).hexdigest() and row["out_sha1"] == hashlib.sha1(b).hexdigest()


def test_egg1_is_deterministic_and_honours_species_and_cycles(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_owner("hgss"))
    one, two, togepi = (tmp_path / n for n in ("a.SaveRAM", "b.SaveRAM", "t.SaveRAM"))
    assert _synth("egg1", src, one) == synth.WRITTEN and _synth("egg1", src, two) == synth.WRITTEN
    assert one.read_bytes() == two.read_bytes()
    assert _synth("egg1", src, togepi, "hgss", "--species", "175", "--cycles", "0") == synth.WRITTEN
    egg = codec.parse_save(togepi.read_bytes(), "hgss").party()[1]
    assert (egg["species"], egg["friendship"], egg["is_egg"], egg["tail_plausible"]) == (175, 0, True, True)
    assert egg["ability"] in (55, 32) and egg["moves"][:2] == (45, 204)


def test_bag_then_egg_compose(tmp_path):
    src, bag, both = (tmp_path / n for n in ("src.SaveRAM", "bag.SaveRAM", "both.SaveRAM"))
    src.write_bytes(_owner("hgss"))
    assert _synth("bag", src, bag) == synth.WRITTEN and _synth("egg1", bag, both) == synth.WRITTEN
    got = codec.parse_save(both.read_bytes(), "hgss")
    assert struct.unpack_from("<HH", got.general, BALLS_AT["hgss"]) == (4, 10)
    assert got.party()[1]["is_egg"]


def test_egg1_refuses_a_full_party_an_empty_party_and_bad_args(tmp_path):
    out = tmp_path / "out.SaveRAM"
    full = tmp_path / "full.SaveRAM"
    full.write_bytes(_image(count=6))
    assert _synth("egg1", full, out) == synth.REFUSED and not out.exists()
    empty = tmp_path / "empty.SaveRAM"
    empty.write_bytes(_image(count=0))
    assert _synth("egg1", empty, out) == synth.REFUSED and not out.exists()
    one = tmp_path / "one.SaveRAM"
    one.write_bytes(_image())
    assert _synth("egg1", one, out, "hgss", "--species", "25") == synth.REFUSED
    assert _synth("egg1", one, out, "hgss", "--cycles", "256") == synth.REFUSED
    assert not out.exists()


def test_bag_and_egg_refuse_an_output_under_the_bizhawk_root(tmp_path, monkeypatch):
    root = tmp_path / "Bizhawk"
    (root / "NDS").mkdir(parents=True)
    monkeypatch.setattr(synth, "BIZHAWK_ROOT", root)
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    for kind in ("bag", "egg1"):
        assert _synth(kind, src, root / "NDS" / f"{kind}.SaveRAM") == synth.REFUSED
