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
from tools import gen4_fixtures, gen4_synth_save as synth

SAVES = gen4_fixtures.lane_root() / "saves"
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


def _image(count: int = 1, pid: int = 0x0BADF00D, otid: int = 0x74C066C6, maxc: int = 6, box_pids=()) -> bytes:
    gen_size, pc_at, pc_size = 0xF628, 0xF700, 0x12310   # the spans the owner's saves use
    body = bytearray(gen_size)
    struct.pack_into("<HH", body, 0xB64, 17, 5)                  # Potion x5: the bag layout anchor
    struct.pack_into("<II", body, HGSS.party_off, maxc, count)
    for i in range(count):
        plain = bytearray(codec.PARTY_MON_SIZE)
        struct.pack_into("<I", plain, 0, pid + i)
        struct.pack_into("<HHI", plain, 8, 155, 0, otid)          # species, item, OTID
        struct.pack_into("<BxHH", plain, 0x8C, 5, 20, 20)        # level, HP, max HP
        off = HGSS.party_off + 8 + i * codec.PARTY_MON_SIZE
        body[off : off + codec.PARTY_MON_SIZE] = codec.encrypt_party(bytes(plain))
    bank = bytearray(codec.BANK_SIZE)
    bank[:gen_size] = _block(HGSS, bytes(body), gen_size, 0, 1)
    pc = bytearray(pc_size - HGSS.footer_size)
    for j, box_pid in enumerate(box_pids):                       # box 0, slots 0..: a non-empty mon each
        plain = bytearray(codec.BOX_MON_SIZE)
        struct.pack_into("<I", plain, 0, box_pid)
        struct.pack_into("<HHI", plain, 8, 155, 0, otid)
        at = HGSS.boxes_off + j * codec.BOX_MON_SIZE
        pc[at : at + codec.BOX_MON_SIZE] = codec.encrypt_box(bytes(plain))
    bank[pc_at : pc_at + pc_size] = _block(HGSS, bytes(pc), pc_size, 1, 1)
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


def test_lead_level_rom_stats_roundtrip_and_original(tmp_path):
    from tools import gen4_pins

    source = _owner("hgss")
    rom = gen4_pins.default_locations().roms["heartgold"]
    out, meta = synth.build_lead_level(source, "hgss", rom, 12, title="heartgold")
    before = codec.parse_save(source, "hgss").party()[0]
    after = codec.parse_save(out, "hgss").party()[0]
    assert after["level"] == 12 and after["exp"] == 973
    assert after["pid"] == before["pid"] and after["moves"] == before["moves"]
    assert after["ivs"] == before["ivs"] and after["evs"] == before["evs"]
    assert after["max_hp"] == 34 and after["stats"] == (15, 16, 23, 20, 20)
    assert after["hp"] == after["max_hp"]
    assert meta["kind"] == "lead_level" and meta["tail_policy"] == "ROM_RECOMPUTED"
    src = tmp_path / "original.SaveRAM"
    src.write_bytes(source)
    target = tmp_path / "lead12.SaveRAM"
    assert (
        synth.main(
            [
                "lead_level",
                "--profile",
                "hgss",
                "--title",
                "heartgold",
                "--rom",
                str(rom),
                "--src",
                str(src),
                "--out",
                str(target),
                "--level",
                "12",
            ]
        )
        == 0
    )
    assert src.read_bytes() == source and target.read_bytes() == out
    assert json.loads(Path(str(target) + ".synth.json").read_text()) == meta


def test_lead_level_logical_block_and_stats_controls_revert(tmp_path, monkeypatch):
    source = Path(synth.__file__).read_text()
    original = synth.build_lead_level
    test_lead_level_rom_stats_roundtrip_and_original(tmp_path)
    for old, new in [
        ("a, b = 8, 8 + 0x20", "a,b,_,_=codec.block_offsets(mon['pid'])"),
        ("stats[index + 1] * (110", "stats[index + 1] * (100"),
    ]:
        assert source.count(old) == 1
        scope = {"__file__": synth.__file__}
        exec(compile(source.replace(old, new), synth.__file__, "exec"), scope)
        monkeypatch.setattr(synth, "build_lead_level", scope["build_lead_level"])
        with pytest.raises(AssertionError):
            test_lead_level_rom_stats_roundtrip_and_original(tmp_path)
        monkeypatch.setattr(synth, "build_lead_level", original)
        test_lead_level_rom_stats_roundtrip_and_original(tmp_path)


@pytest.mark.parametrize("title", ["heartgold", "heartgold_hge", "soulsilver"])
def test_new_lead_scenarios_bind_synth_and_preserve_linkage(title):
    from tests.live import test_gen4_probe_gates as gate

    doc, save, _ = gate.load_scenario(
        f"data/gen4/scenarios/{title}_lead12.json", title, "baseline", committed=False
    )
    setup = gate.baseline_setup(doc, save)
    assert setup["setup"] == "SYNTH" and setup["sidecar_sha256"] == doc["save"]["sidecar_sha256"]
    original = json.loads((synth.ROOT / f"data/gen4/scenarios/{title}.json").read_text())
    assert (
        doc["row_i_scenario"] == original["row_i_scenario"]
        and doc["pc_case_scenario"] == original["pc_case_scenario"]
    )
    native = gen4_fixtures.lane_root() / original["save"]["path"]
    assert hashlib.sha256(native.read_bytes()).hexdigest() == original["save"]["sha256"]
    profile = "hge" if title == "heartgold_hge" else "hgss"
    before = codec.parse_save(native.read_bytes(), profile).party()[0]
    after = codec.parse_save(save.read_bytes(), profile).party()[0]
    assert after["level"] == 12 and after["exp"] == 973 and after["moves"] == before["moves"]
    assert (
        after["pid"] == before["pid"]
        and after["ivs"] == before["ivs"]
        and after["evs"] == before["evs"]
    )


def test_synth_baseline_requires_exact_scenario_disclosure(tmp_path):
    from tests.live import test_gen4_probe_gates as gate

    save = tmp_path / "source.SaveRAM"
    save.write_bytes(b"MODEL save")
    side = Path(str(save) + ".synth.json")
    side.write_text(
        json.dumps(
            {
                "src_sha1": "0" * 40,
                "out_sha1": hashlib.sha1(save.read_bytes()).hexdigest(),
                "new_pid": 1,
            }
        )
    )
    native = {"save": {"sha256": gate.digest(save)}}
    with pytest.raises(AssertionError):
        gate.baseline_setup(native, save)
    correct = {"save": {**native["save"], "sidecar_sha256": gate.digest(side)}}
    got = gate.baseline_setup(correct, save)
    assert got["setup"] == "SYNTH" and got["sidecar_sha256"] == gate.digest(side)
    wrong = {"save": {**correct["save"], "sidecar_sha256": "0" * 64}}
    with pytest.raises(AssertionError):
        gate.baseline_setup(wrong, save)
    assert gate.baseline_setup(correct, save) == got
    raw = side.read_bytes()
    side.unlink()
    with pytest.raises(AssertionError):
        gate.baseline_setup(correct, save)
    assert gate.baseline_setup(native, save) == {"setup": "NATIVE"}
    side.write_bytes(raw)
    assert gate.baseline_setup(correct, save) == got


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


@pytest.mark.parametrize("variant", ["hgss", "hge"])
@pytest.mark.parametrize("size", [0x5B0, 0x5B8])
def test_a_whole_bag_one_word_shift_is_refused(tmp_path, monkeypatch, variant, size):
    """Revert test: the Bag model moved by one slot either way must refuse, never write."""
    monkeypatch.setattr(synth, "PARTY_ARRAY_SIZE", size)
    src, out = tmp_path / "src.SaveRAM", tmp_path / "bag.SaveRAM"
    src.write_bytes(_owner(variant))
    assert _synth("bag", src, out, variant) == synth.REFUSED and not out.exists()


def test_the_hge_owner_save_holds_no_id_above_the_vanilla_range_in_the_checked_pockets():
    general = codec.parse_save(_owner("hge"), "hge").general
    lay = synth.bag_layout(codec.PROFILES["hge"])
    ids = [struct.unpack_from("<HH", general, off + 4 * i)[0]
           for name in synth.POCKET_CLASS["hge"] for off, n in [lay["pockets"][name]] for i in range(n)]
    assert max(ids) == 17 and all(i in (0, 17) for i in ids)     # only the Potion


def _hge_image(slots: dict) -> bytes:
    """The hge owner save with ``{(general offset): (id, qty)}`` written into its general block."""
    def mutate(body):
        for at, (iid, qty) in slots.items():
            struct.pack_into("<HH", body, at, iid, qty)
        return body
    return _reseal(_owner("hge"), "hge", mutate)


def test_hge_ids_are_classed_by_the_fork_item_data_not_accepted_for_being_new(tmp_path, capsys):
    lay = synth.bag_layout(codec.PROFILES["hge"])
    balls, med = lay["pockets"]["balls"][0], lay["pockets"]["medicine"][0]
    out = tmp_path / "out.SaveRAM"
    for name, slots in {
        "unknown id in the Balls pocket": {balls: (1000, 1)},        # an hge-only id, not a ball
        "hge ball in the Medicine pocket": {med + 4: (576, 1)},      # Dream Ball, hge fork class: balls
        "hge medicine in the Balls pocket": {balls: (1231, 1)},
    }.items():
        src = tmp_path / "src.SaveRAM"
        src.write_bytes(_hge_image(slots))
        assert _synth("bag", src, out, "hge") == synth.REFUSED, name
        assert "bag_layout_unverified" in capsys.readouterr().err and not out.exists()
    ok = tmp_path / "ok.SaveRAM"                                       # a correctly placed hge-only ball passes
    ok.write_bytes(_hge_image({balls: (576, 3)}))
    assert _synth("bag", ok, out, "hge") == synth.WRITTEN
    g = codec.parse_save(out.read_bytes(), "hge").general
    assert [struct.unpack_from("<HH", g, balls + 4 * i) for i in range(2)] == [(576, 3), (4, 10)]


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


def test_bag_adds_to_an_existing_pokeball_stack(tmp_path):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_bag_image({0: (3, 7), 1: (4, 5)}))
    assert _synth("bag", src, out) == synth.WRITTEN
    assert _balls(out.read_bytes())[:3] == [(3, 7), (4, 15), (0, 0)]


def test_bag_refuses_a_pocket_with_a_gap_before_an_item(tmp_path):
    """A real pocket is compacted (src/bag.c:284-292); a gap means the offset model is shifted."""
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_bag_image({0: (3, 7), 2: (4, 5)}))
    assert _synth("bag", src, out) == synth.REFUSED and not out.exists()


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


@pytest.mark.parametrize("variant", ["hgss", "hge"])
@pytest.mark.parametrize("pair", [("medicine", "balls"), ("medicine", "berries")])
def test_a_swapped_pocket_model_is_refused_not_written(tmp_path, monkeypatch, variant, pair):
    """Revert test: the offset model is checked against the saved bytes, not only read back."""
    order = list(synth.POCKETS)
    i, j = order.index(pair[0]), order.index(pair[1])
    order[i], order[j] = order[j], order[i]
    monkeypatch.setattr(synth, "POCKETS", tuple(order))
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_owner(variant))
    assert _synth("bag", src, out, variant) == synth.REFUSED and not out.exists()


def test_the_layout_check_needs_a_positive_anchor_and_a_classed_item(tmp_path, capsys):
    out = tmp_path / "out.SaveRAM"
    bare = tmp_path / "bare.SaveRAM"          # a Potion-less bag: nothing to confirm the offsets against
    bare.write_bytes(_reseal(_image(), "hgss", lambda b: b[:0xB64] + bytes(4) + b[0xB68:]))
    assert _synth("bag", bare, out) == synth.REFUSED and "bag_layout_unverified" in capsys.readouterr().err
    wrong = tmp_path / "wrong.SaveRAM"        # a Potion where the Balls pocket should be
    wrong.write_bytes(_bag_image({0: (17, 5)}))
    assert _synth("bag", wrong, out) == synth.REFUSED and "bag_layout_unverified" in capsys.readouterr().err
    assert not out.exists()


def test_egg1_cycles_are_bounded_by_the_species_egg_cycles(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    assert _synth("egg1", src, tmp_path / "o.SaveRAM", "hgss", "--cycles", "11") == synth.REFUSED
    assert _synth("egg1", src, tmp_path / "o.SaveRAM", "hgss", "--cycles", "10") == synth.WRITTEN


def test_bag_and_egg_refuse_an_output_under_the_bizhawk_root(tmp_path, monkeypatch):
    root = tmp_path / "Bizhawk"
    (root / "NDS").mkdir(parents=True)
    monkeypatch.setattr(synth, "BIZHAWK_ROOT", root)
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    for kind in ("bag", "egg1"):
        assert _synth(kind, src, root / "NDS" / f"{kind}.SaveRAM") == synth.REFUSED


# ---------------------------------------------------------------------------
# party6 / species (G2 producer plan section 4)
# ---------------------------------------------------------------------------
def _raw_party(image: bytes, variant: str) -> list:
    """The stored (encrypted) 0xEC party records, read at the profile offset, not through the tool."""
    s = codec.parse_save(image, variant)
    off = s.profile.party_off + 8
    return [s.general[off + i * codec.PARTY_MON_SIZE : off + (i + 1) * codec.PARTY_MON_SIZE] for i in range(6)]


def _species_run(src: Path, out: Path, species, variant: str = "hgss") -> int:
    return synth.main(["species", str(species), "--profile", variant, "--src", str(src), "--out", str(out)])


def _assert_checksums_valid(image: bytes, variant: str, count: int) -> None:
    """Independent of the tool: decrypting a party record verifies its checksum, and a raw
    recompute over the stored blocks must equal the stored header checksum."""
    for raw in _raw_party(image, variant)[:count]:
        codec.decrypt_party(raw)                                   # raises Gen4CodecError on a bad checksum


def _assert_changed_within(src: bytes, out: bytes, variant: str, spans) -> None:
    """Like _assert_only_changed but with the tool tight spans (general-relative [lo, hi) list)."""
    s = codec.parse_save(src, variant)
    blk = s.blocks[(s.bank, 0)]
    crc = blk.start + blk.size - 2
    changed = [i for i, (x, y) in enumerate(zip(src, out, strict=True)) if x != y]
    assert changed and crc in changed, "the CRC must be re-stamped"
    assert all(i in (crc, crc + 1) or any(blk.start + lo <= i < blk.start + hi for lo, hi in spans) for i in changed)


def _tail(raw: bytes) -> bytes:
    """The decrypted 0x88..0xEC party tail of a stored record."""
    return codec.decrypt_party(raw)[codec.TAIL_OFF :]


def _assert_party6_contract(src: bytes, out: bytes, variant: str) -> None:
    a, b = codec.parse_save(src, variant), codec.parse_save(out, variant)
    assert (b.bank, b.counter) == (a.bank, a.counter)
    mons, was = b.party(), a.party()
    assert len(mons) == 6
    assert mons[:len(was)] == was                                  # decoded pre-existing mons unchanged
    raw_a, raw_b = _raw_party(src, variant), _raw_party(out, variant)
    assert raw_b[:len(was)] == raw_a[:len(was)]                    # ... and byte-identical, every slot
    assert len({m["pid"] for m in mons}) == 6 and len({m["key"] for m in mons}) == 6
    for m in mons[1:]:
        assert m["tail_plausible"] and not m["shiny"] and m["nickname"] == "SYNTH"
        assert (m["species"], m["level"], m["otid"], m["nature"], m["stats"], m["max_hp"]) == (
            was[0]["species"], was[0]["level"], was[0]["otid"], was[0]["nature"], was[0]["stats"], was[0]["max_hp"])
    _assert_checksums_valid(out, variant, 6)
    for raw in raw_b[len(was):]:
        assert _tail(raw) == _tail(raw_a[0])                       # the party tail is carried from slot 0 byte-exact
    n = a.profile.party_off
    assert struct.unpack_from("<II", b.general, n) == (6, 6)
    first = n + 8 + len(was) * codec.PARTY_MON_SIZE
    _assert_changed_within(src, out, variant, [(n + 4, n + 8), (first, n + 8 + 6 * codec.PARTY_MON_SIZE)])


@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_party6_fills_the_party_with_distinct_valid_clones(tmp_path, variant):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "p6.SaveRAM"
    src.write_bytes(_owner(variant))
    assert _synth("party6", src, out, variant) == synth.WRITTEN
    assert src.read_bytes() == _owner(variant)                     # the owner save is never modified
    _assert_party6_contract(src.read_bytes(), out.read_bytes(), variant)
    row = json.loads((tmp_path / "p6.SaveRAM.synth.json").read_text(encoding="utf-8"))
    mons = codec.parse_save(out.read_bytes(), variant).party()
    assert (row["kind"], row["profile"], row["slots"]) == ("party6", variant, [1, 2, 3, 4, 5])
    assert row["new_pids"] == [m["pid"] for m in mons[1:]] and row["note"] == synth.PARTY6_NOTE
    assert row["src_sha1"] == hashlib.sha1(src.read_bytes()).hexdigest()
    assert row["out_sha1"] == hashlib.sha1(out.read_bytes()).hexdigest()


def test_party6_is_deterministic_and_tops_up_a_partly_full_party(tmp_path):
    src, a, b = tmp_path / "src.SaveRAM", tmp_path / "a.SaveRAM", tmp_path / "b.SaveRAM"
    src.write_bytes(_image(count=3))
    assert _synth("party6", src, a) == synth.WRITTEN and _synth("party6", src, b) == synth.WRITTEN
    assert a.read_bytes() == b.read_bytes()
    before = codec.parse_save(src.read_bytes(), "hgss").party()
    after = codec.parse_save(a.read_bytes(), "hgss").party()
    assert after[:3] == before and len(after) == 6 and len({m["key"] for m in after}) == 6


def test_party6_refuses_a_full_party_and_an_empty_one(tmp_path, capsys):
    out = tmp_path / "out.SaveRAM"
    for count, why in ((6, "party_full"), (0, "no_party")):
        src = tmp_path / f"c{count}.SaveRAM"
        src.write_bytes(_image(count=count))
        assert _synth("party6", src, out) == synth.REFUSED and why in capsys.readouterr().err
        assert not out.exists() and not Path(str(out) + ".synth.json").exists()
    one, full = tmp_path / "one.SaveRAM", tmp_path / "again.SaveRAM"   # party6 of a party6 output is refused
    one.write_bytes(_image())
    assert _synth("party6", one, full) == synth.WRITTEN and _synth("party6", full, out) == synth.REFUSED
    assert not out.exists()


def test_party6_refuses_to_write_over_the_source(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    before = src.read_bytes()
    assert _synth("party6", src, src) == synth.REFUSED and src.read_bytes() == before


def test_a_corrupted_party_checksum_is_caught_by_the_independent_check(tmp_path):
    """Negative control for the checksum assertions: flip one stored-checksum bit in an output
    mon (and re-stamp the general CRC so only the mon is wrong) and the checks must fail."""
    src, out = tmp_path / "src.SaveRAM", tmp_path / "p6.SaveRAM"
    src.write_bytes(_image())
    assert _synth("party6", src, out) == synth.WRITTEN
    good = out.read_bytes()
    _assert_checksums_valid(good, "hgss", 6)
    at = HGSS.party_off + 8 + 3 * codec.PARTY_MON_SIZE + 6          # slot 3 stored checksum
    bad = _reseal(good, "hgss", lambda body: body[:at] + bytes([body[at] ^ 1]) + body[at + 1 :])
    with pytest.raises(codec.Gen4CodecError):
        _assert_checksums_valid(bad, "hgss", 6)
    with pytest.raises(codec.Gen4CodecError):
        _assert_party6_contract(src.read_bytes(), bad, "hgss")


@pytest.mark.parametrize("variant,species", [("hgss", 25), ("hgss", 493), ("hge", 25), ("hge", 1000)])
def test_species_rewrites_the_clone_to_a_valid_mon_of_that_species(tmp_path, variant, species):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "sp.SaveRAM"
    src.write_bytes(_owner(variant))
    assert _species_run(src, out, species, variant) == synth.WRITTEN
    assert src.read_bytes() == _owner(variant)
    a, b = codec.parse_save(src.read_bytes(), variant), codec.parse_save(out.read_bytes(), variant)
    was, mons = a.party(), b.party()
    assert (b.bank, b.counter) == (a.bank, a.counter) and len(mons) == 2
    assert mons[0] == was[0] and _raw_party(out.read_bytes(), variant)[0] == _raw_party(src.read_bytes(), variant)[0]
    mon = mons[1]
    assert (mon["species"], mon["nickname"], mon["shiny"], mon["tail_plausible"]) == (species, "SYNTH", False, True)
    assert mon["key"] != was[0]["key"] and mon["form"] == 0
    assert (mon["level"], mon["otid"], mon["nature"], mon["stats"]) == (
        was[0]["level"], was[0]["otid"], was[0]["nature"], was[0]["stats"])    # tail carried, not recomputed
    _assert_checksums_valid(out.read_bytes(), variant, 2)
    assert _tail(_raw_party(out.read_bytes(), variant)[1]) == _tail(_raw_party(src.read_bytes(), variant)[0])
    n = a.profile.party_off
    _assert_changed_within(src.read_bytes(), out.read_bytes(), variant,
                           [(n + 4, n + 8), (n + 8 + codec.PARTY_MON_SIZE, n + 8 + 2 * codec.PARTY_MON_SIZE)])
    row = json.loads((tmp_path / "sp.SaveRAM.synth.json").read_text(encoding="utf-8"))
    assert (row["kind"], row["species"], row["mode"], row["new_pid"]) == ("species", species, "clone", mon["pid"])
    assert row["tail_policy"] == synth.TAIL_POLICY and row["note"] == synth.SPECIES_NOTE
    assert row["src_sha1"] == hashlib.sha1(src.read_bytes()).hexdigest()
    assert row["out_sha1"] == hashlib.sha1(out.read_bytes()).hexdigest()


def test_species_on_a_party2_output_equals_species_on_the_source(tmp_path):
    """The in-place rewrite of a party2 clone yields the same slot-1 record as the one-step clone."""
    src, p2, one, two = (tmp_path / n for n in ("src.SaveRAM", "p2.SaveRAM", "one.SaveRAM", "two.SaveRAM"))
    src.write_bytes(_owner("hgss"))
    assert _run(src, p2) == synth.WRITTEN
    assert _species_run(src, one, 25) == synth.WRITTEN and _species_run(p2, two, 25) == synth.WRITTEN
    assert _raw_party(one.read_bytes(), "hgss")[1] == _raw_party(two.read_bytes(), "hgss")[1]
    assert json.loads((tmp_path / "two.SaveRAM.synth.json").read_text(encoding="utf-8"))["mode"] == "rewrite"
    again = tmp_path / "again.SaveRAM"                              # still a SYNTH clone, so it can be rewritten again
    assert _species_run(two, again, 152) == synth.WRITTEN
    assert codec.parse_save(again.read_bytes(), "hgss").party()[1]["species"] == 152


@pytest.mark.parametrize("variant,species", [("hgss", 0), ("hgss", 494), ("hgss", 495), ("hgss", 496), ("hgss", 1000),
                                             ("hge", 0), ("hge", 494), ("hge", 496), ("hge", 1314), ("hge", 1476),
                                             ("hgss", 65536), ("hgss", -1),
                                             ("hge", 1313), ("hge", 1475)])
def test_species_out_of_range_or_placeholder_is_refused(tmp_path, capsys, variant, species):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_image())
    assert _species_run(src, out, species, variant) == synth.REFUSED
    assert "bad_species" in capsys.readouterr().err
    assert not out.exists() and not Path(str(out) + ".synth.json").exists()


def test_the_species_range_follows_the_profile():
    assert synth.valid_species("hgss") == set(range(1, 494))       # Egg and Bad Egg are not species
    hge = synth.valid_species("hge")
    # hg-engine include/constants/species.h:1093-1096: MAX_MON_NUM = SPECIES_PECHARUNT = 1075 and the
    # mega/forme ids start at SPECIES_MEGA_START = 1076 (names.json marks each forme with a base key)
    assert max(hge) == 1075 and 1075 in hge and 1000 in hge
    assert not any(i in hge for i in (494, 495, 496, 1076, 1313, 1314, 1475, 1476))
    assert len(hge) == 1075 - (543 - 494 + 1)                      # minus Egg, Bad Egg and the placeholder gap 496..543


def test_species_refuses_a_real_second_mon_a_big_party_and_an_empty_one(tmp_path, capsys):
    out = tmp_path / "out.SaveRAM"
    for count, why in ((2, "slot1_unattested"), (6, "party_too_big"), (0, "no_party")):
        src = tmp_path / f"c{count}.SaveRAM"
        src.write_bytes(_image(count=count))                       # a count-2 slot 1 has no SYNTH nickname
        assert _species_run(src, out, 25) == synth.REFUSED and why in capsys.readouterr().err
        assert not out.exists()


def test_species_refuses_to_write_over_the_source(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_image())
    before = src.read_bytes()
    assert _species_run(src, src, 25) == synth.REFUSED and src.read_bytes() == before


# ---------------------------------------------------------------------------
# review fixes (OMP cx-82aea86c)
# ---------------------------------------------------------------------------
def test_synth_pid_keeps_the_template_nature_across_the_32_bit_wrap(monkeypatch):
    """F5: pid % 25 == template % 25 for every seed, including the seeds near 2**32 where the old
    modular add wrapped (seed 4294967275, template nature 24 gave pid 3)."""
    seeds = [0, 1, 24, 25, (1 << 32) - 1, (1 << 32) - 2, 4294967275, 4294967276, 4294967290, 4294967295]
    seeds += [(1 << 32) - 1 - 7 * i for i in range(60)] + [(i * 2654435761) % (1 << 32) for i in range(300)]
    for seed in seeds:
        monkeypatch.setattr(synth, "_seed", lambda kind, sha, seed=seed: seed)
        for nature in range(25):
            template = nature + 25 * 1000
            pid = synth.synth_pid("x", template, 0x74C066C6)
            assert pid % 25 == nature and 0 <= pid < 1 << 32 and pid != template, (seed, nature, pid)


def test_party6_avoids_pids_already_in_the_boxes(tmp_path, monkeypatch):
    """F6: a clone PID equal to a stored box mon key would be a duplicate identity."""
    monkeypatch.setattr(synth, "_seed", lambda kind, sha: 0x1000 + 25 * len(kind))  # image-independent
    out = tmp_path / "out.SaveRAM"
    plain = tmp_path / "plain.SaveRAM"
    plain.write_bytes(_image())
    assert _synth("party6", plain, out) == synth.WRITTEN
    want = [m["pid"] for m in codec.parse_save(out.read_bytes(), "hgss").party()[1:]]
    boxed = tmp_path / "boxed.SaveRAM"
    boxed.write_bytes(_image(box_pids=want[:3]))                  # boxes already hold three of the PIDs
    out2 = tmp_path / "out2.SaveRAM"
    assert _synth("party6", boxed, out2) == synth.WRITTEN
    got = codec.parse_save(out2.read_bytes(), "hgss")
    pids = [m["pid"] for m in got.party()]
    assert not set(pids[1:]) & set(want[:3]) and len(set(pids)) == 6
    boxes = {m["pid"] for b in got.boxes() for m in b["mons"].values()}
    assert boxes == set(want[:3]) and not boxes & set(pids)


def test_party6_and_species_refuse_a_party_max_below_six(tmp_path, capsys):
    """F7: PartyCore.maxCount is part of the contract; a smaller cap would make count 6 invalid."""
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    for maxc in (5, 1):
        src.write_bytes(_image(maxc=maxc))
        assert _synth("party6", src, out) == synth.REFUSED and "party_max" in capsys.readouterr().err
        assert _species_run(src, out, 25) == synth.REFUSED and "party_max" in capsys.readouterr().err
        assert not out.exists()


def test_the_outputs_keep_party_max_six(tmp_path):
    src, p6, sp = (tmp_path / n for n in ("src.SaveRAM", "p6.SaveRAM", "sp.SaveRAM"))
    src.write_bytes(_image())
    assert _synth("party6", src, p6) == synth.WRITTEN and _species_run(src, sp, 25) == synth.WRITTEN
    for path in (p6, sp):
        g = codec.parse_save(path.read_bytes(), "hgss").general
        assert struct.unpack_from("<I", g, HGSS.party_off)[0] == 6


def test_species_rewrite_needs_a_sidecar_attested_clone_not_just_the_nickname(tmp_path, capsys):
    """F8: the guard is the sidecar of the tool own output (matching out_sha1 and new_pid), not the
    player-editable nickname: a bare copy, an edited image and a wrong new_pid are all refused."""
    out = tmp_path / "out.SaveRAM"
    src, p2 = tmp_path / "src.SaveRAM", tmp_path / "p2.SaveRAM"
    src.write_bytes(_image())
    assert _run(src, p2) == synth.WRITTEN
    bare = tmp_path / "bare.SaveRAM"                              # a genuine clone, but nothing attests it
    bare.write_bytes(p2.read_bytes())
    assert _species_run(bare, out, 25) == synth.REFUSED and "slot1_unattested" in capsys.readouterr().err
    assert not out.exists()
    assert _species_run(p2, out, 25) == synth.WRITTEN             # the tool own output is accepted
    side = Path(str(p2) + ".synth.json")
    good = side.read_text(encoding="utf-8")
    edited = tmp_path / "edited.SaveRAM"                          # same bytes + one edit: the sidecar no longer attests it
    edited.write_bytes(_reseal(p2.read_bytes(), "hgss", lambda b: b[:0xB64] + struct.pack("<HH", 17, 6) + b[0xB68:]))
    Path(str(edited) + ".synth.json").write_text(good, encoding="utf-8")
    assert _species_run(edited, tmp_path / "o2.SaveRAM", 25) == synth.REFUSED
    row = json.loads(good)                                        # wrong new_pid for the slot-1 mon
    row["new_pid"] ^= 2
    side.write_text(json.dumps(row), encoding="utf-8")
    assert _species_run(p2, tmp_path / "o3.SaveRAM", 25) == synth.REFUSED
    assert "slot1_unattested" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# place (G2 producer plan section 4; research synth_place_save_layout.md, corrected against the owner saves)
# ---------------------------------------------------------------------------
# Offsets are written out here independently of the pack the tool reads (test_gen4_pack pins pack == these):
# general-block offsets measured/derived for the owner saves.
LOC_AT = {"hgss": 0x1234, "hge": 0x1424}           # FILE: Location (60,-1,x,y,1) x5 at +0/+0x14/+0x28/+0x3C/+0x50
OBJ_AT = {"hgss": 0x2348, "hge": 0x2CC0}           # FILE: entry 0 is the player; SavedMapObject stride 0x50
VARS_AT = {"hgss": 0xDE4, "hge": 0xFD4}            # 368 u16, then 364 flag bytes; LocalFieldData follows at +0x450
FLAGS_AT = {v: VARS_AT[v] + 0x2E0 for v in VARS_AT}
STATE_OFF = 0x70                                    # LocalFieldData + 0x6C PlayerSaveData {u16, u16, s32 state}
PLAYER_FIELDS = {"flags": 0, "movement": 9, "init_face": 0xC, "cur_face": 0xD, "next_face": 0xE, "map": 0x10,
                 "cur_x": 0x26, "cur_y": 0x28, "cur_z": 0x2A}


def _obj(variant: str, i: int) -> int:
    return OBJ_AT[variant] + 0x50 * i


def _read_player_object(general: bytes, variant: str, i: int = 0) -> dict:
    o = _obj(variant, i)
    return {"flags": struct.unpack_from("<I", general, o)[0], "movement": general[o + 9],
            "faces": tuple(general[o + 0xC : o + 0xF]), "map": struct.unpack_from("<H", general, o + 0x10)[0],
            "cur": struct.unpack_from("<hhh", general, o + 0x26)}


def _hermetic_place_image(state: int = 2, extra_player: bool = False, lone_follower: bool = False) -> bytes:
    """_image() plus the field data place needs: Location x5, a player + follower + NPC object list, flags/vars, a
    non-zero avatar state (the player is 'surfing')."""
    def mutate(body):
        for k in range(5):
            struct.pack_into("<5i", body, LOC_AT["hgss"] + 20 * k, 60, -1, 695, 397, 1)
        struct.pack_into("<i", body, LOC_AT["hgss"] + STATE_OFF, state)
        entries = [(0x2000E431, 255, 1, 1, 1, 695, 2, 397), (0x200CE661, 253, 48, 1, 1, 695, 2, 397),
                   (0xC061, 0, 0, 3, 60, 682, 2, 391), (0xC061, 1, 2, 2, 60, 683, 2, 399)]
        if lone_follower:
            entries = entries[1:]
        for i, (fl, oid, mv, face, mp, cx, cy, cz) in enumerate(entries):
            o = OBJ_AT["hgss"] + 0x50 * i
            struct.pack_into("<IIBB", body, o, fl, 0, oid, mv)
            body[o + 0xC : o + 0xF] = bytes([face]) * 3
            struct.pack_into("<H", body, o + 0x10, mp)
            struct.pack_into("<hhhhhh", body, o + 0x20, cx, 0, cz, cx, cy, cz)
            struct.pack_into("<i", body, o + 0x2C, cy << 15)
        if extra_player:
            o = OBJ_AT["hgss"] + 0x50 * 9
            struct.pack_into("<IIBB", body, o, 0x2000E431, 0, 255, 1)
            struct.pack_into("<hhhhhh", body, o + 0x20, 1, 0, 1, 1, 2, 1)
        for vid, value in ((0x4030, 155), (0x4035, 56150)):
            struct.pack_into("<H", body, VARS_AT["hgss"] + 2 * (vid - 0x4000), value)
        body[FLAGS_AT["hgss"] + 13] = 0x04
        return body
    return _reseal(_image(), "hgss", mutate)


def _place(src: Path, out: Path, variant: str = "hgss", *args: str) -> int:
    return synth.main(["place", "--profile", variant, "--src", str(src), "--out", str(out), *args])


GOOD = ("--map", "100", "--x", "700", "--y", "410", "--dir", "2", "--height", "2")  # a map change needs an explicit height (F1)


def _assert_place_written(a: bytes, b: bytes, variant: str, *, map_id=100, x=700, y=410, d=2, flags=None, vars_=None,
                          height=None) -> None:
    """Raw reads of every field the card says place writes, from the output, at the independent offsets."""
    ga, gb = codec.parse_save(a, variant), codec.parse_save(b, variant)
    assert (gb.bank, gb.counter) == (ga.bank, ga.counter)
    assert gb.party() == ga.party() and gb.player() == ga.player()      # the codec oracle: nothing else moved
    g, g0 = gb.general, ga.general
    for k in range(5):                                                   # Location x5, warpId -1
        assert struct.unpack_from("<5i", g, LOC_AT[variant] + 20 * k) == (map_id, -1, x, y, d)
    assert struct.unpack_from("<i", g, LOC_AT[variant] + STATE_OFF)[0] == 0          # avatar state: walking
    player = _read_player_object(g, variant)
    assert player["movement"] == 1 and player["flags"] & 1 and player["faces"] == (d, d, d)
    assert player["cur"][0] == x and player["cur"][2] == y
    before = _read_player_object(g0, variant)
    assert player["map"] == before["map"]                                # the player mapId is not the map id: untouched
    vec = struct.unpack_from("<i", g, _obj(variant, 0) + 0x2C)[0]
    vec0 = struct.unpack_from("<i", g0, _obj(variant, 0) + 0x2C)[0]
    if height is None:                                                   # same map, no --height: the source elevation is carried
        assert player["cur"][1] == before["cur"][1] and vec == vec0
    else:                                                                # restore only sets vecY from the save (map_object.c:494-496)
        assert player["cur"][1] == height and vec == height << 15
    actives = [i for i in range(64) if struct.unpack_from("<I", g, _obj(variant, i))[0] & 1]
    assert actives == [0]                                                # only the player is active
    for i in range(1, 64):                                               # the others keep every bit but ACTIVE
        assert struct.unpack_from("<I", g, _obj(variant, i))[0] == struct.unpack_from("<I", g0, _obj(variant, i))[0] & ~1
    for fid, value in (flags or {}).items():
        assert (g[FLAGS_AT[variant] + fid // 8] >> (fid % 8)) & 1 == value
    for vid, value in (vars_ or {}).items():
        assert struct.unpack_from("<H", g, VARS_AT[variant] + 2 * (vid - 0x4000))[0] == value


def _place_spans(variant: str, a: bytes, *, flags=(), vars_=(), height=False) -> list:
    """The tight general-relative spans place may touch, built from the independent constants."""
    g0 = codec.parse_save(a, variant).general
    o = _obj(variant, 0)
    spans = [(LOC_AT[variant], LOC_AT[variant] + 100), (LOC_AT[variant] + STATE_OFF, LOC_AT[variant] + STATE_OFF + 4),
             (o + 0xC, o + 0xF), (o + 0x26, o + 0x28), (o + 0x2A, o + 0x2C)]
    if height:
        spans += [(o + 0x28, o + 0x2A), (o + 0x2C, o + 0x30)]           # currentY and vecY
    spans += [(_obj(variant, i), _obj(variant, i) + 4) for i in range(1, 64) if struct.unpack_from("<I", g0, _obj(variant, i))[0] & 1]
    spans += [(FLAGS_AT[variant] + f // 8, FLAGS_AT[variant] + f // 8 + 1) for f in flags]
    spans += [(VARS_AT[variant] + 2 * (v - 0x4000), VARS_AT[variant] + 2 * (v - 0x4000) + 2) for v in vars_]
    return spans


@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_the_owner_saves_pin_the_place_layout(variant):
    """FILE: the entry-0 player object, the flag/var arrays and the avatar state sit where place assumes."""
    g = codec.parse_save(_owner(variant), variant).general
    loc = struct.unpack_from("<5i", g, LOC_AT[variant])
    player = _read_player_object(g, variant)
    assert player["movement"] == 1 and player["flags"] & 1 and (player["cur"][0], player["cur"][2]) == (loc[2], loc[3])
    assert [i for i in range(64) if struct.unpack_from("<I", g, _obj(variant, i))[0] & 1 and g[_obj(variant, i) + 9] == 1] == [0]
    assert struct.unpack_from("<H", g, VARS_AT[variant] + 2 * 0x30)[0] == 155            # VAR 0x4030, the same in HG/SS/hge
    assert g[FLAGS_AT[variant] + 13] == 0x04 and struct.unpack_from("<i", g, LOC_AT[variant] + STATE_OFF)[0] == 0
    assert VARS_AT[variant] + 0x44C + 4 == LOC_AT[variant]                               # vars+flags then the CRC close on Location


@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_place_writes_location_player_object_and_flags_on_the_owner_saves(tmp_path, variant):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "place.SaveRAM"
    src.write_bytes(_owner(variant))
    assert _place(src, out, variant, *GOOD, "--flag", "2000=1", "--flag", "0x7D1=1", "--var", "0x4040=3", "--var", "16500=65535") == synth.WRITTEN
    assert src.read_bytes() == _owner(variant)
    a, b = src.read_bytes(), out.read_bytes()
    _assert_place_written(a, b, variant, flags={2000: 1, 2001: 1}, vars_={0x4040: 3, 16500: 65535}, height=2)
    _assert_changed_within(a, b, variant, _place_spans(variant, a, flags=(2000, 2001), vars_=(0x4040, 16500), height=True))
    other = 1 - codec.parse_save(a, variant).bank
    assert b[other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE] == a[other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE]
    row = json.loads((tmp_path / "place.SaveRAM.synth.json").read_text(encoding="utf-8"))
    assert (row["kind"], row["profile"], row["map"], row["x"], row["y"], row["dir"]) == ("place", variant, 100, 700, 410, 2)
    assert row["src_sha1"] == hashlib.sha1(a).hexdigest() and row["out_sha1"] == hashlib.sha1(b).hexdigest()
    assert row["flags"] == {"2000": 1, "2001": 1} and row["vars"] == {"0x4040": 3, "0x4074": 65535}
    assert row["player_entry"] == 0 and row["layout"]["map_objects"]["general_off"] == OBJ_AT[variant]
    assert row["layout"]["map_objects"]["evidence_class"] == {"hgss": "SOURCE+FILE", "hge": "DERIVED+FILE"}[variant]
    assert row["bounds_verified"] is False and "no map dimensions" in row["bounds_note"]          # F7
    assert (row["height"], row["height_source"], row["vecY"]) == (2, "given", 2 << 15)


def test_place_clears_flags_height_and_the_follower_on_a_hermetic_save(tmp_path):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_hermetic_place_image())                        # state 2, a follower and two NPCs
    assert _place(src, out, "hgss", *GOOD, "--flag", "106=0", "--flag", "5=1", "--height", "7") == synth.WRITTEN
    a, b = src.read_bytes(), out.read_bytes()
    _assert_place_written(a, b, "hgss", flags={106: 0, 5: 1}, height=7)
    _assert_changed_within(a, b, "hgss", _place_spans("hgss", a, flags=(106, 5), height=True))
    g0, g = codec.parse_save(a, "hgss").general, codec.parse_save(b, "hgss").general
    assert struct.unpack_from("<i", g0, LOC_AT["hgss"] + STATE_OFF)[0] == 2 and struct.unpack_from("<i", g, LOC_AT["hgss"] + STATE_OFF)[0] == 0
    assert g0[FLAGS_AT["hgss"] + 13] == 0x04 and g[FLAGS_AT["hgss"] + 13] == 0   # a flag can be cleared
    assert json.loads((tmp_path / "out.SaveRAM.synth.json").read_text(encoding="utf-8"))["cleared_entries"] == [1, 2, 3]


def test_place_is_deterministic_and_leaves_unrelated_flags_alone(tmp_path):
    src, a, b = tmp_path / "src.SaveRAM", tmp_path / "a.SaveRAM", tmp_path / "b.SaveRAM"
    src.write_bytes(_hermetic_place_image())
    assert _place(src, a, "hgss", *GOOD) == synth.WRITTEN and _place(src, b, "hgss", *GOOD) == synth.WRITTEN
    assert a.read_bytes() == b.read_bytes()
    g0, g = codec.parse_save(src.read_bytes(), "hgss").general, codec.parse_save(a.read_bytes(), "hgss").general
    assert g[FLAGS_AT["hgss"] : FLAGS_AT["hgss"] + 364] == g0[FLAGS_AT["hgss"] : FLAGS_AT["hgss"] + 364]
    assert g[VARS_AT["hgss"] : VARS_AT["hgss"] + 0x2E0] == g0[VARS_AT["hgss"] : VARS_AT["hgss"] + 0x2E0]


BAD_PLACE_ARGS = [  # (override, reason code, message fragment): every case must hit ITS OWN refusal, not an earlier one
    ({"--map": "540"}, "bad_map", "not in the pack map table"), ({"--map": "-1"}, "bad_map", "not in the pack map table"),
    ({"--x": "-1"}, "bad_coord", "x/y must be"), ({"--x": "32768"}, "bad_coord", "x/y must be"),
    ({"--y": "40000"}, "bad_coord", "x/y must be"), ({"--dir": "4"}, "bad_dir", "--dir must be"),
    ({"--dir": "-1"}, "bad_dir", "--dir must be"), ({"--height": "40000"}, "bad_coord", "does not fit"),
    ({"--flag": ["0=1"]}, "bad_flag", "no-op"), ({"--flag": ["0x4000=1"]}, "bad_flag", "temp flag"),
    ({"--flag": ["0x4001=1"]}, "bad_flag", "temp flag"),
    ({"--flag": ["2912=1"]}, "bad_flag", "outside 1..2911"), ({"--flag": ["3000=1"]}, "bad_flag", "outside 1..2911"),
    ({"--flag": ["7=2"]}, "bad_flag", "must be 0 or 1"), ({"--flag": ["7=-1"]}, "bad_flag", "must be 0 or 1"),
    ({"--flag": ["abc"]}, "bad_place_arg", "ID=VALUE"), ({"--flag": ["5=1", "5=0"]}, "bad_place_arg", "two different values"),
    ({"--var": ["0x3FFF=1"]}, "bad_var", "outside 0x4000..0x416f"), ({"--var": ["0x4170=1"]}, "bad_var", "outside 0x4000..0x416f"),
    ({"--var": ["0x8000=1"]}, "bad_var", "outside 0x4000..0x416f"), ({"--var": ["0x4040=65536"]}, "bad_var", "must fit a u16"),
    ({"--var": ["0x4040=-1"]}, "bad_var", "must fit a u16"), ({"--var": ["nope"]}, "bad_place_arg", "ID=VALUE"),
    ({"--var": ["0x4040=1", "0x4040=2"]}, "bad_place_arg", "two different values"),
]


@pytest.mark.parametrize("bad,code,fragment", BAD_PLACE_ARGS,
                         ids=[next(iter(b[0])) + ":" + str(next(iter(b[0].values()))) for b in BAD_PLACE_ARGS])
def test_place_refuses_bad_arguments_with_the_specific_reason_and_writes_nothing(tmp_path, capsys, bad, code, fragment):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_hermetic_place_image())
    before = src.read_bytes()
    args = {"--map": "100", "--x": "700", "--y": "410", "--dir": "2", "--height": "2", **bad}
    argv = []
    for key, value in args.items():
        for item in value if isinstance(value, list) else [value]:
            argv += [key, item]
    assert _place(src, out, "hgss", *argv) == synth.REFUSED, bad
    err = capsys.readouterr().err
    assert f"'{code}'" in err and fragment in err, (bad, err)
    assert src.read_bytes() == before and not out.exists() and not Path(str(out) + ".synth.json").exists()


@pytest.mark.parametrize("variant", ["hgss", "hge"])
def test_place_accepts_the_last_real_flag_and_refuses_the_next_on_every_profile(tmp_path, variant):
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_owner(variant))
    assert _place(src, out, variant, *GOOD, "--flag", "2911=1") == synth.WRITTEN        # the last real flag
    assert _place(src, tmp_path / "o2.SaveRAM", variant, *GOOD, "--flag", "2912=1") == synth.REFUSED


def test_place_refuses_a_source_without_exactly_one_active_player_object(tmp_path, capsys):
    out = tmp_path / "out.SaveRAM"
    for name, image in (("no player", _hermetic_place_image(lone_follower=True)),
                        ("two players", _hermetic_place_image(extra_player=True)),
                        ("zeros", _reseal(_image(), "hgss", lambda b: b))):
        src = tmp_path / "src.SaveRAM"
        src.write_bytes(image)
        assert _place(src, out, "hgss", *GOOD) == synth.REFUSED, name
        assert "place_layout_unverified" in capsys.readouterr().err and not out.exists(), name


def test_place_refuses_when_the_player_object_does_not_sit_on_the_location(tmp_path, capsys):
    """A shifted offset model would find a movement==1 entry that is not the player: the Location cross-check refuses."""
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_reseal(_hermetic_place_image(), "hgss",
                            lambda b: b[: OBJ_AT["hgss"] + 0x26] + struct.pack("<h", 123) + b[OBJ_AT["hgss"] + 0x28 :]))
    assert _place(src, out, "hgss", *GOOD) == synth.REFUSED
    assert "place_layout_unverified" in capsys.readouterr().err and not out.exists()


def test_place_refuses_to_write_over_the_source_and_the_bizhawk_root(tmp_path, monkeypatch):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_hermetic_place_image())
    before = src.read_bytes()
    assert _place(src, src, "hgss", *GOOD) == synth.REFUSED and src.read_bytes() == before
    root = tmp_path / "Bizhawk"
    (root / "NDS").mkdir(parents=True)
    monkeypatch.setattr(synth, "BIZHAWK_ROOT", root)
    assert _place(src, root / "NDS" / "p.SaveRAM", "hgss", *GOOD) == synth.REFUSED


def test_the_platinum_profile_is_not_offered_for_place(tmp_path):
    src = tmp_path / "src.SaveRAM"
    src.write_bytes(_hermetic_place_image())
    with pytest.raises(SystemExit):
        _place(src, tmp_path / "out.SaveRAM", "pt", *GOOD)


def test_place_composes_with_party6_and_species(tmp_path):
    src, p6, both = (tmp_path / n for n in ("src.SaveRAM", "p6.SaveRAM", "both.SaveRAM"))
    src.write_bytes(_owner("hgss"))
    assert _synth("party6", src, p6) == synth.WRITTEN and _place(p6, both, "hgss", *GOOD) == synth.WRITTEN
    got = codec.parse_save(both.read_bytes(), "hgss")
    assert len(got.party()) == 6 and struct.unpack_from("<5i", got.general, LOC_AT["hgss"])[0] == 100


# ---------------------------------------------------------------------------
# place-pack fixes (OMP cx-3bab37d5 on 3f5f447d)
# ---------------------------------------------------------------------------
def test_place_across_maps_needs_an_explicit_height_and_writes_vecy_with_it(tmp_path, capsys):
    """F1: the game restores vecY from the save and never re-derives it (map_object.c:494-496, 502-512), so a map change with
    no known elevation is refused; with --height both currentY (+0x28) and vecY (+0x2C = height << 15) are written."""
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_hermetic_place_image())
    cross = ("--map", "100", "--x", "700", "--y", "410", "--dir", "2")
    assert _place(src, out, "hgss", *cross) == synth.REFUSED and "height_required" in capsys.readouterr().err
    assert not out.exists() and not Path(str(out) + ".synth.json").exists()
    assert _place(src, out, "hgss", *cross, "--height", "5") == synth.WRITTEN
    g = codec.parse_save(out.read_bytes(), "hgss").general
    o = _obj("hgss", 0)
    assert struct.unpack_from("<h", g, o + 0x28)[0] == 5 and struct.unpack_from("<i", g, o + 0x2C)[0] == 5 << 15 == 0x28000
    row = json.loads((tmp_path / "out.SaveRAM.synth.json").read_text(encoding="utf-8"))
    assert (row["height"], row["height_source"], row["vecY"]) == (5, "given", 0x28000) and "map_object.c:494-496" in row["height_note"]
    # the same map keeps the source elevation (currentY and vecY untouched) and says so
    same = ("--map", "60", "--x", "700", "--y", "410", "--dir", "2")
    out2 = tmp_path / "out2.SaveRAM"
    assert _place(src, out2, "hgss", *same) == synth.WRITTEN
    g0, g2 = codec.parse_save(src.read_bytes(), "hgss").general, codec.parse_save(out2.read_bytes(), "hgss").general
    assert g2[o + 0x28 : o + 0x2A] == g0[o + 0x28 : o + 0x2A] and g2[o + 0x2C : o + 0x30] == g0[o + 0x2C : o + 0x30]  # currentY, vecY
    assert json.loads((tmp_path / "out2.SaveRAM.synth.json").read_text(encoding="utf-8"))["height_source"] == "carried"


def test_the_height_to_vecy_relation_is_the_one_the_game_derives():
    """vecY = currentY * 8 * FX32_ONE = currentY << 15 (map_object.c:639-641: currentY = (vecY >> 3) / FX32_ONE); an fx32 << 12
    would put the object 8x too low.  FILE: every active owner object (currentY 2) holds vecY 0x10000."""
    for variant in ("hgss", "hge"):
        g = codec.parse_save(_owner(variant), variant).general
        rows = [(struct.unpack_from("<h", g, _obj(variant, i) + 0x28)[0], struct.unpack_from("<i", g, _obj(variant, i) + 0x2C)[0])
                for i in range(64) if struct.unpack_from("<I", g, _obj(variant, i))[0] & 1]
        assert rows and all(vec == cy << 15 and vec != cy << 12 for cy, vec in rows)


def test_place_reads_the_var_range_from_the_pack_not_module_constants(tmp_path, monkeypatch, capsys):
    """F8: vars.base_id / vars.count come from field_save, so a pack with a different range changes the refusal."""
    real = synth._field_save
    def shrunk(name):
        fs, loc = real(name)
        return {**fs, "vars": {**fs["vars"], "base_id": 0x4000, "count": 0x10}}, loc
    src, out = tmp_path / "src.SaveRAM", tmp_path / "out.SaveRAM"
    src.write_bytes(_hermetic_place_image())
    assert _place(src, out, "hgss", *GOOD, "--var", "0x4020=1") == synth.WRITTEN        # in the real range
    out.unlink()
    monkeypatch.setattr(synth, "_field_save", shrunk)
    assert _place(src, out, "hgss", *GOOD, "--var", "0x4020=1") == synth.REFUSED and "bad_var" in capsys.readouterr().err
    assert not out.exists()


def test_the_place_docstring_explains_the_five_locations_and_warp_id():
    doc = synth.__doc__
    assert "all five Locations" in doc and "warpId -1" in doc and "field_warp_tasks.c:150" in doc
    assert "src/location_backup.c" in doc and "vecY" in doc and "map_object.c:494-496" in doc
