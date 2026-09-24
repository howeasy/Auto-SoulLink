"""W-5: Python-codec and pret checksum controls over every boxed write."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

from server.adapters import gen1_codec as oracle

ROOT = Path(__file__).resolve().parents[2]
PROFILE = json.loads((ROOT / "data/games/gen1_rby/profile.json").read_text(encoding="utf-8"))["titles"]
BASE = {"hp": 45, "attack": 49, "defense": 49, "speed": 45, "special": 65,
        "growth_rate": 3}  # pret/data/pokemon/base_stats/bulbasaur.asm:3,14


def test_box_module_has_no_direct_memory_writes_or_embedded_wram_addresses():
    source = (ROOT / "lua/gen1/boxes.lua").read_text(encoding="utf-8")
    code = re.sub(r"--[^\n]*", "", source)
    assert "memory." not in code and "io.write_u8" not in code
    assert not re.search(r"0x(?:[cCdD][0-9a-fA-F]{3})", code)


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Suppress the repo's disk-writing autouse fixture in this pure suite."""
    yield


def _mon(species=153, ot_id=0x1234, *, level=12, dvs=0xABCD, stat_exp=None, hp=None):
    stat_exp = stat_exp or {"hp": 0, "atk": 16, "def": 625, "spd": 1000, "spc": 65535}
    blob = bytearray(44)
    blob[0], blob[3], blob[33] = species, level, level
    blob[12:14] = ot_id.to_bytes(2, "big")
    blob[14:17] = (oracle.exp_for_level(BASE["growth_rate"], level) + 1).to_bytes(3, "big")
    blob[27:29] = dvs.to_bytes(2, "big")
    blob[8:12], blob[29:33] = bytes((1, 2, 3, 4)), bytes((0x41, 0x7F, 0x85, 0xFF))
    for index, name in enumerate(("hp", "atk", "def", "spd", "spc")):
        blob[17 + index * 2:19 + index * 2] = stat_exp[name].to_bytes(2, "big")
    decoded = oracle.decode_party_mon(blob)
    stats = oracle.recompute_stats(decoded, BASE)
    blob[1:3] = (hp if hp is not None else stats["max_hp"] - 1).to_bytes(2, "big")
    for index, name in enumerate(("max_hp", "atk", "def", "spd", "spc")):
        blob[34 + index * 2:36 + index * 2] = stats[name].to_bytes(2, "big")
    assert oracle.encode_party_mon(oracle.decode_party_mon(blob)) == blob
    return {"blob": bytes(blob), "ot": oracle.encode_name("TRAINER"),
            "nick": oracle.encode_name("BULBA")}


def _collection(entries, *, box=False):
    layout = oracle.BOX_LAYOUT if box else oracle.PARTY_LAYOUT
    size = oracle.BOX_MON_SIZE if box else oracle.PARTY_MON_SIZE
    result = bytearray(layout["size"])
    result[0], result[1 + len(entries)] = len(entries), 255
    for i, item in enumerate(entries):
        blob = bytearray(item["blob"][:size])
        if box:
            blob[3] = item["blob"][33]  # add_mon.asm:421-427
        result[1 + i] = blob[0]
        result[layout["mons"] + i * size:layout["mons"] + (i + 1) * size] = blob
        for name, field in (("ot", "ot_names"), ("nick", "nicknames")):
            start = layout[field] + i * oracle.NAME_SIZE
            result[start:start + oracle.NAME_SIZE] = item[name]
    return bytes(result)


def _cart_offset(title, index):
    profile = PROFILE[title]
    derived, ram = profile["derived"], profile["ram"]
    slot = index % derived["sram_boxes_per_bank"]
    bank_slot = index // derived["sram_boxes_per_bank"]
    bank = derived["sram_box_banks"][bank_slot]
    anchor = "sBox1" if bank_slot == 0 else "sBox7"
    return bank * 0x2000 + ram[anchor] - 0xA000 + slot * derived["sram_box_stride"]


def _seal_all(title, cart):
    for bank in PROFILE[title]["derived"]["sram_box_banks"]:
        start = bank * 0x2000
        end = start + 6 * oracle.BOX_SIZE
        cart[end] = oracle.sav_checksum(cart[start:end])
        for slot in range(6):
            first = start + slot * oracle.BOX_SIZE
            cart[end + 1 + slot] = oracle.sav_checksum(cart[first:first + oracle.BOX_SIZE])


def _seed(title, party, active=(), saved=None, *, initialized=True, current=0):
    ram = PROFILE[title]["ram"]
    wram = bytearray(65536)
    cart = bytearray(32768)
    p = _collection(party)
    b = _collection(active, box=True)
    wram[ram["wPartyCount"]:ram["wPartyCount"] + len(p)] = p
    wram[ram["wBoxCount"]:ram["wBoxCount"] + len(b)] = b
    wram[ram["wCurrentBoxNum"]] = current + (128 if initialized else 0)
    if initialized:
        for index in range(12):
            entries = (saved or {}).get(index, ())
            raw = _collection(entries, box=True)
            start = _cart_offset(title, index)
            cart[start:start + len(raw)] = raw
        _seal_all(title, cart)
    return wram, cart


def _runtime(title, wram, cart, charmap=None):
    rt = LuaRuntime(unpack_returned_tuples=True)
    load = rt.eval("dofile")
    json_module = load((ROOT / "lua/json_codec.lua").as_posix())
    profile = json_module.decode((ROOT / "data/games/gen1_rby/profile.json").read_text(
        encoding="utf-8"))["titles"][title]
    if charmap:
        profile.charmap = load((ROOT / charmap).as_posix())
    reads_module = load((ROOT / "lua/gen1/reads.lua").as_posix())
    scanner_module = load((ROOT / "lua/token_scanner.lua").as_posix())
    writes_module = load((ROOT / "lua/gen1/writes.lua").as_posix())
    boxes_module = load((ROOT / "lua/gen1/boxes.lua").as_posix())
    calls = {"wram": [], "cart": []}

    def read_range(addr, n):
        assert 0 <= addr <= len(wram) and 0 <= n <= len(wram) - addr
        return rt.table_from(list(wram[addr:addr + n]))

    def write_u8(addr, value, domain):
        assert domain == "System Bus" and 0 <= addr < len(wram)
        wram[addr] = value

    permit = load((ROOT / "lua/write_permit.lua").as_posix())
    gate = writes_module.new(profile, rt.table_from({"write_u8": write_u8}), permit)

    def write_cart(offset, blob):
        data = bytes(blob[i] for i in range(1, len(blob) + 1))
        assert 0 <= offset <= len(cart) and len(data) <= len(cart) - offset
        cart[offset:offset + len(data)] = data
        calls["cart"].append((offset, len(data)))

    def write_wram(addr, blob):
        gate.write_bytes(gate, addr, blob)
        calls["wram"].append((addr, len(blob)))

    def read_cart(offset):
        assert 0 <= offset < len(cart)
        return cart[offset]

    make_read_io = rt.eval("function(u, range) return {"
                           "read_u8=function(a) return u(a) end,"
                           "read_range=function(a,n) return range(a,n) end} end")
    read_io = make_read_io(lambda addr: wram[addr], read_range)
    reader = reads_module.new(profile, read_io, scanner_module)
    make_box_io = rt.eval("function(range, cart, w, wc, gate) return {"
                          "read_range=function(a,n) return range(a,n) end,"
                          "read_cart=function(o) return cart(o) end,"
                          "write_bytes=function(a,b) return w(a,b) end,"
                          "write_cart_bytes=function(o,b) "
                          "assert(gate.armed,'CartRAM write refused: not armed');"
                          "return wc(o,b) end} end")
    box_io = make_box_io(read_range, read_cart, write_wram, write_cart, gate)
    boxes = boxes_module.new(profile, reader, box_io)
    return rt, reader, boxes, gate, calls


def _bytes(rt, raw):
    return rt.table_from(list(raw))


def _party(title, wram):
    start = PROFILE[title]["ram"]["wPartyCount"]
    return oracle.decode_party(wram[start:start + oracle.PARTY_LAYOUT["size"]])


def _active(title, wram):
    start = PROFILE[title]["ram"]["wBoxCount"]
    return oracle.decode_box(wram[start:start + oracle.BOX_SIZE])


def _saved(title, cart, index):
    start = _cart_offset(title, index)
    return oracle.decode_box(cart[start:start + oracle.BOX_SIZE])


def _changed(before, after):
    return {i for i, (old, new) in enumerate(zip(before, after, strict=True)) if old != new}


def _in_range(changes, start, length):
    assert all(start <= i < start + length for i in changes)


@pytest.mark.parametrize("title", ("red", "blue", "yellow"))
def test_deposit_current_box_shifts_all_arrays_and_never_touches_cart(title):
    mons = [_mon(ot_id=1), _mon(ot_id=2), _mon(ot_id=3)]
    wram, cart = _seed(title, mons, active=[_mon(ot_id=9)])
    _, reader, boxes, gate, calls = _runtime(title, wram, cart)
    key = oracle.key(oracle.decode_party_mon(mons[1]["blob"]))
    before_wram, before_cart = wram[:], cart[:]
    with pytest.raises(LuaError, match="not armed|no armed"):
        boxes.box_mon(key)
    assert wram == before_wram and cart == before_cart
    gate.arm(gate, "overworld")
    assert boxes.box_mon(key) is True
    assert [m["ot_id"] for m in _party(title, wram)] == [1, 3]
    boxed = _active(title, wram)
    assert [m["ot_id"] for m in boxed] == [9, 2]
    assert boxed[1]["box_level"] == 12
    assert boxed[1]["ot_name_bytes"] == mons[1]["ot"]
    assert boxed[1]["nickname_bytes"] == mons[1]["nick"]
    assert cart == before_cart and calls["cart"] == []
    party_start = PROFILE[title]["ram"]["wPartyCount"]
    box_start = PROFILE[title]["ram"]["wBoxCount"]
    assert all(party_start <= i < party_start + oracle.PARTY_LAYOUT["size"] or
               box_start <= i < box_start + oracle.BOX_SIZE
               for i in _changed(before_wram, wram))
    _in_range(calls["wram"][0][0:1], PROFILE[title]["ram"]["wBoxCount"], oracle.BOX_SIZE)
    assert calls["wram"] == [(PROFILE[title]["ram"]["wBoxCount"], oracle.BOX_SIZE),
                             (PROFILE[title]["ram"]["wPartyCount"], oracle.PARTY_LAYOUT["size"])]
    previous = (wram[:], cart[:], list(calls["wram"]))
    assert boxes.box_mon(key) is True
    assert (wram, cart, calls["wram"]) == previous
    assert reader.key(reader.read_party()[1]) == oracle.key(_party(title, wram)[0])


@pytest.mark.parametrize("title", ("red", "blue", "yellow"))
def test_memorial_noncurrent_repairs_game_checksums(title):
    dead = _mon(ot_id=101, hp=0)
    keep = _mon(ot_id=102)
    wram, cart = _seed(title, [dead, keep], current=0)
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    key = oracle.key(oracle.decode_party_mon(dead["blob"]))
    before_wram, before_cart = wram[:], cart[:]
    with pytest.raises(LuaError, match="CartRAM write refused"):
        boxes.memorialize(key)
    assert wram == before_wram and cart == before_cart
    gate.arm(gate, "overworld")
    assert boxes.memorialize(key) is True
    assert len(_party(title, wram)) == 1
    assert [m["ot_id"] for m in _saved(title, cart, 11)] == [101]
    report = oracle.verify_boxes(cart)
    assert report["boxes"][12]["valid"] and report["banks"][3]["valid"]
    assert all(box["valid"] for box in report["boxes"].values())
    assert all(bank["valid"] for bank in report["banks"].values())
    assert not _changed(before_cart[:0x6000], cart[:0x6000])
    _in_range(_changed(before_cart, cart), 3 * 0x2000, 6 * oracle.BOX_SIZE + 7)
    _in_range(_changed(before_wram, wram), PROFILE[title]["ram"]["wPartyCount"],
              oracle.PARTY_LAYOUT["size"])
    assert calls["cart"] == [(3 * 0x2000, 6 * oracle.BOX_SIZE + 7)]
    prior = (wram[:], cart[:], {name: list(log) for name, log in calls.items()})
    assert boxes.memorialize(key) is True
    assert (wram, cart, calls) == prior


@pytest.mark.parametrize("title", ("red", "blue", "yellow"))
def test_first_change_initialisation_exact_bytes_and_idempotence(title):
    wram, cart = _seed(title, [_mon(ot_id=1), _mon(ot_id=2)], initialized=False)
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    before_wram, before_cart = wram[:], cart[:]
    gate.arm(gate, "overworld")
    assert boxes.ensure_boxes_initialised() is True
    assert wram[PROFILE[title]["ram"]["wCurrentBoxNum"]] == 128
    assert _changed(before_wram, wram) == {PROFILE[title]["ram"]["wCurrentBoxNum"]}
    report = oracle.verify_boxes(cart)
    assert report["initialized"]  # ChangeBox must not erase an SRAM memorial after reset
    assert all(box["valid"] and box["count"] == 0 for box in report["boxes"].values())
    assert all(bank["valid"] for bank in report["banks"].values())
    # SaveMainData's compacted WRAM->SRAM offset: sMainData +
    # (wCurrentBoxNum - wMainDataStart), save.asm:208-240; not wPlayerName-relative.
    ram, banks = PROFILE[title]["ram"], PROFILE[title]["sram_bank"]
    saved_flag = (banks["sMainData"] * 0x2000 + ram["sMainData"] - 0xA000
                  + ram["wCurrentBoxNum"] - ram["wMainDataStart"])
    main_start = banks["sPlayerName"] * 0x2000 + ram["sPlayerName"] - 0xA000
    main_checksum = (banks["sMainDataCheckSum"] * 0x2000
                     + ram["sMainDataCheckSum"] - 0xA000)
    assert cart[saved_flag] == 128 and oracle.verify_bank1(cart)
    assert cart[main_checksum] == oracle.sav_checksum(cart[main_start:main_checksum])
    assert all(
        box["valid"] and not box["populated"] for box in report["boxes"].values()
    )
    # EmptySRAMBox changes only count and first species, preserving all tail
    # bytes; all other changed bytes must be its 14 checksum cells.
    expected = set()
    for index in range(12):
        assert _saved(title, cart, index) == []
        expected.add(_cart_offset(title, index) + 1)
    for bank in (2, 3):
        expected.update(range(bank * 0x2000 + 6 * oracle.BOX_SIZE,
                              bank * 0x2000 + 6 * oracle.BOX_SIZE + 7))
    expected.update((saved_flag, main_checksum))
    assert _changed(before_cart, cart) <= expected
    assert len(calls["cart"]) == 4 and len(calls["wram"]) == 1  # two banks + checksum + flag
    snapshot = (wram[:], cart[:], {name: list(log) for name, log in calls.items()})
    assert boxes.ensure_boxes_initialised() is True
    assert (wram, cart, calls) == snapshot


def test_initialisation_preserves_arbitrary_tail_bytes():
    title = "red"
    wram, cart = _seed(title, [_mon(ot_id=1), _mon(ot_id=2)], initialized=False)
    rng = random.Random(1955)
    for bank in (2, 3):
        start = bank * 0x2000
        cart[start:start + 6 * oracle.BOX_SIZE + 7] = rng.randbytes(6 * oracle.BOX_SIZE + 7)
    old = cart[:]
    _, _, boxes, gate, _ = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    assert boxes.ensure_boxes_initialised() is True
    touched = set()
    for index in range(12):
        first = _cart_offset(title, index)
        touched.update((first, first + 1))
        assert cart[first:first + 2] == b"\x00\xff"
    for bank in (2, 3):
        first_checksum = bank * 0x2000 + 6 * oracle.BOX_SIZE
        touched.update(range(first_checksum, first_checksum + 7))
    touched.update((oracle._CURRENT_BOX, oracle.SRAM_LAYOUT["sMainDataCheckSum"]))
    assert _changed(old, cart) <= touched
    assert all(box["valid"] for box in oracle.verify_boxes(cart)["boxes"].values())
    assert oracle.verify_bank1(cart)


def test_initialization_flag_is_durable_before_the_next_game_save():
    title = "red"
    wram, cart = _seed(title, [_mon(ot_id=1)], initialized=False)
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    assert boxes.ensure_boxes_initialised() is True
    assert cart[oracle._CURRENT_BOX] & oracle._BOX_INITIALIZED
    assert oracle.verify_bank1(cart)
    assert oracle.verify_boxes(cart)["initialized"]
    assert any(offset <= oracle._CURRENT_BOX < offset + size for offset, size in calls["cart"])
    corrupted = bytearray(cart)
    corrupted[oracle._CURRENT_BOX] &= ~oracle._BOX_INITIALIZED
    assert not oracle.verify_bank1(corrupted), "the game's checksum must detect a torn flag write"


def test_withdraw_200_random_rebuilt_stat_vectors_and_checksums():
    title = "red"
    wram, cart = _seed(title, [_mon(ot_id=1)])
    rt, reader, boxes, gate, _ = _runtime(title, wram, cart)
    rng = random.Random(2369)
    gate.arm(gate, "overworld")
    for _ in range(200):
        stat_exp = {name: rng.randrange(65536) for name in ("hp", "atk", "def", "spd", "spc")}
        original = _mon(ot_id=rng.randrange(2, 65536), level=rng.randrange(5, 101),
                        dvs=rng.randrange(65536), stat_exp=stat_exp)
        party = _collection([_mon(ot_id=1)])
        wram[PROFILE[title]["ram"]["wPartyCount"]:
             PROFILE[title]["ram"]["wPartyCount"] + len(party)] = party
        saved = _collection([original], box=True)
        offset = _cart_offset(title, 11)
        cart[offset:offset + len(saved)] = saved
        _seal_all(title, cart)
        key = oracle.key(oracle.decode_party_mon(original["blob"]))
        wrong_stats = rt.table_from({"level": 1, "maxHP": 1, "attack": 1})
        assert boxes.party_mon(key, rt.table_from(BASE), None, wrong_stats) is True
        now = _party(title, wram)
        assert len(now) == 2 and _saved(title, cart, 11) == []
        expected = oracle.decode_party_mon(original["blob"])
        level = oracle.level_from_exp(BASE["growth_rate"], expected["exp"])
        expected["level"] = level
        rebuilt = oracle.recompute_stats(expected, BASE)
        assert {name: now[1][name] for name in rebuilt} == rebuilt
        assert now[1]["level"] == level and now[1]["hp"] == expected["hp"]
        assert now[1]["nickname_bytes"] == original["nick"]
        report = oracle.verify_boxes(cart)
        assert report["boxes"][12]["valid"] and report["banks"][3]["valid"]
        assert boxes.party_mon(key, rt.table_from(BASE)) is True
        assert reader.key(reader.read_party()[2]) == oracle.key(now[1])


@pytest.mark.parametrize("growth_rate", range(6))
def test_withdraw_recomputes_each_pret_growth_curve(growth_rate):
    title = "blue"
    level = 37
    source = _mon(ot_id=300 + growth_rate, level=level)
    blob = bytearray(source["blob"])
    blob[14:17] = (oracle.exp_for_level(growth_rate, level) + 1).to_bytes(3, "big")
    source["blob"] = bytes(blob)
    wram, cart = _seed(title, [_mon(ot_id=1)], saved={11: [source]})
    rt, _, boxes, gate, _ = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    base = {**BASE, "growth_rate": growth_rate}
    key = oracle.key(oracle.decode_party_mon(source["blob"]))
    assert boxes.party_mon(key, rt.table_from(base)) is True
    result = _party(title, wram)[1]
    assert result["level"] == oracle.level_from_exp(growth_rate, result["exp"]) == level
    assert {name: result[name] for name in ("max_hp", "atk", "def", "spd", "spc")} == (
        oracle.recompute_stats(result, base)
    )
    report = oracle.verify_boxes(cart)
    assert report["boxes"][12]["valid"] and report["banks"][3]["valid"]


def test_round_trip_and_refusals():
    title = "yellow"
    a, b = _mon(ot_id=1), _mon(ot_id=2)
    wram, cart = _seed(title, [a, b])
    rt, _, boxes, gate, calls = _runtime(title, wram, cart)
    key = oracle.key(oracle.decode_party_mon(a["blob"]))
    gate.arm(gate, "overworld")
    before = a["blob"]
    assert boxes.box_mon(key) is True
    assert boxes.party_mon(key, rt.table_from(BASE)) is True
    assert oracle.encode_party_mon(_party(title, wram)[1]) == before
    assert len(_active(title, wram)) == 0
    assert oracle.verify_boxes(cart)["banks"][2]["valid"]
    assert boxes.party_mon(key, rt.table_from(BASE)) is True
    assert boxes.box_mon("FFFF:FFFF:FF")[0] is None

    wram, cart = _seed(title, [_mon(ot_id=i) for i in range(1, 7)],
                       saved={11: [_mon(ot_id=99)]})
    _, _, boxes, gate, _ = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    src_key = oracle.key(oracle.decode_party_mon(_mon(ot_id=99)["blob"]))
    prior = (wram[:], cart[:])
    assert boxes.party_mon(src_key, BASE)[0] is None
    assert (wram, cart) == prior
    assert boxes.party_mon("FFFF:FFFF:FF", BASE)[0] is None

    wram, cart = _seed(title, [_mon(ot_id=1), _mon(ot_id=2)])
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    old = (wram[:], cart[:])
    got, reason = boxes.party_mon("FFFF:FFFF:FF", BASE)
    assert got is None and reason == "key not boxed"
    assert (wram, cart) == old and calls == {"wram": [], "cart": []}


def test_memorial_last_mon_and_full_box_refuse_without_writes():
    title = "red"
    dead = _mon(ot_id=999, hp=0)
    key = oracle.key(oracle.decode_party_mon(dead["blob"]))
    wram, cart = _seed(title, [dead], initialized=False)
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    old = (wram[:], cart[:])
    got, reason = boxes.memorialize(key)
    assert got is None and "last party mon" in reason
    assert (wram, cart) == old and not calls["cart"] and not calls["wram"]

    got, reason = boxes.box_mon(key)
    assert got is None and "last party mon" in reason
    assert (wram, cart) == old and not calls["cart"] and not calls["wram"]

    full = [_mon(ot_id=i) for i in range(20, 40)]
    wram, cart = _seed(title, [dead, _mon(ot_id=1000)], saved={11: full})
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    old = (wram[:], cart[:])
    got, reason = boxes.memorialize(key)
    assert got is None and reason == "memorial box full"
    assert (wram, cart) == old and not calls["cart"] and not calls["wram"]


@pytest.mark.parametrize("where", ["active", "saved", "memorial_bank"])
def test_memorial_of_a_boxed_dead_key_moves_it_into_the_memorial_box(where):
    """BOX-MEMORIAL (O-35, mirror of Gen 2): a box release kills a partner that is usually boxed too, and
    any partner can die while in the PC. Its memorialize moves the box record into sBox12; the party (one
    mon here: a boxed memorial never needs a second one) is never touched."""
    title = "red"
    dead, lead = _mon(ot_id=55, hp=0), _mon(ot_id=56)
    source = {"active": None, "saved": 4, "memorial_bank": 8}[where]
    if source is None:
        wram, cart = _seed(title, [lead], active=[dead])
    else:
        wram, cart = _seed(title, [lead], saved={source: [dead]})
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    key = oracle.key(oracle.decode_party_mon(dead["blob"]))
    party = wram[PROFILE[title]["ram"]["wPartyCount"]:][:oracle.PARTY_LAYOUT["size"]]
    got = boxes.memorialize(key)
    assert got is True if source is not None else got[0] is True   # a current-box source waits for a save
    assert [m["ot_id"] for m in _saved(title, cart, 11)] == [55]
    assert (_active(title, wram) if source is None else _saved(title, cart, source)) == []
    assert wram[PROFILE[title]["ram"]["wPartyCount"]:][:oracle.PARTY_LAYOUT["size"]] == party
    assert all(box["valid"] for box in oracle.verify_boxes(cart)["boxes"].values())
    assert all(bank["valid"] for bank in oracle.verify_boxes(cart)["banks"].values())
    prior = (wram[:], cart[:])
    assert boxes.memorialize(key) is True
    assert (wram, cart) == prior, "idempotent"


def test_memorial_of_a_boxed_key_in_an_uninitialised_pc_initialises_the_saved_boxes_first():
    title = "red"
    dead = _mon(ot_id=55, hp=0)
    wram, cart = _seed(title, [_mon(ot_id=56)], active=[dead], initialized=False)
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    got = boxes.memorialize(oracle.key(oracle.decode_party_mon(dead["blob"])))
    assert got[0] is True and "native save" in got[1]                 # the WRAM source removal waits for a save
    assert _active(title, wram) == [] and [m["ot_id"] for m in _saved(title, cart, 11)] == [55]
    assert all(bank["valid"] for bank in oracle.verify_boxes(cart)["banks"].values())


def test_memorial_of_a_boxed_key_finishes_after_a_reset_between_its_two_writes():
    title = "red"
    dead = _mon(ot_id=55, hp=0)
    wram, cart = _seed(title, [_mon(ot_id=56)], saved={4: [dead], 11: [dead]})
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    assert boxes.memorialize(oracle.key(oracle.decode_party_mon(dead["blob"]))) is True
    assert _saved(title, cart, 4) == [] and [m["ot_id"] for m in _saved(title, cart, 11)] == [55]
    assert all(box["valid"] for box in oracle.verify_boxes(cart)["boxes"].values())


# ── BOX-MEMORIAL-2 (OMP review of 57e292dc) ────────────────────────────────────────────────────────────
# The current box is WRAM (wBoxData), durable only when a native save copies it to SRAM; a saved box
# (a bank slot) is durable at once. A removal must never become durable before its copy.
class _Durable:
    """A red World whose current box reverts to its last saved image on a reset (LoadSAV)."""

    def __init__(self, party, active=(), saved=None, current=0):
        self.title = "red"
        self.wram, self.cart = _seed(self.title, party, active=active, saved=saved, current=current)
        _, _, self.boxes, gate, _ = _runtime(self.title, self.wram, self.cart)
        gate.arm(gate, "overworld")
        self.current = current
        self.save()

    def _span(self):
        start = PROFILE[self.title]["ram"]["wBoxCount"]
        return start, oracle.BOX_SIZE

    def save(self):
        a, n = self._span()
        self.image = bytes(self.wram[a:a + n])

    def reset(self):
        a, n = self._span()
        self.wram[a:a + n] = self.image

    def durable(self, ot):
        out = []
        for index in range(12):
            box = oracle.decode_box(self.image) if index == self.current else _saved(self.title, self.cart, index)
            out += [index for m in box if m["ot_id"] == ot]
        return out


@pytest.mark.parametrize("current,source", [(0, 4), (0, 0), (11, 4)],
                         ids=["backing_to_backing", "active_to_backing", "backing_to_active"])
def test_a_boxed_memorial_is_never_lost_and_ends_with_one_durable_copy(current, source):
    dead = _mon(ot_id=55, hp=0)
    w = _Durable([_mon(ot_id=56)], active=[dead] if source == current else (),
                 saved=None if source == current else {source: [dead]}, current=current)
    key = oracle.key(oracle.decode_party_mon(dead["blob"]))
    got = w.boxes.memorialize(key)
    assert got is True or got[0] is True
    w.reset()                                                 # power off before any native save
    assert len(w.durable(55)) >= 1, "a reset never loses the mon"
    for _ in range(4):                                        # the server re-sends; the client settles per save
        got = w.boxes.memorialize(key)
        if got is True:
            break
        w.save()
        got = w.boxes.settle_memorial(key)
        if got is True:
            break
    w.save()
    assert w.durable(55) == [11], "exactly one durable copy, in the memorial box"


@pytest.mark.parametrize("current,source", [(0, 0), (11, 4)], ids=["active_source", "active_memorial"])
def test_a_boxed_memorial_touching_the_current_box_is_not_done_until_a_native_save(current, source):
    dead = _mon(ot_id=55, hp=0)
    w = _Durable([_mon(ot_id=56)], active=[dead] if source == current else (),
                 saved=None if source == current else {source: [dead]}, current=current)
    got = w.boxes.memorialize(oracle.key(oracle.decode_party_mon(dead["blob"])))
    assert got[0] is True and "native save" in got[1]
    if current == 11:
        assert [m["ot_id"] for m in _saved("red", w.cart, source)] == [55], "the durable source stays"


@pytest.mark.parametrize("field", ["nick", "box_level"])
def test_a_boxed_memorial_never_removes_a_different_record_that_shares_the_key(field):
    """same_transfer (party->box) skips BoxLevel and the nickname; box->box must compare every byte."""
    dead = _mon(ot_id=55, hp=0)
    other = dict(dead)
    if field == "nick":
        other["nick"] = oracle.encode_name("OTHER")
    else:
        blob = bytearray(dead["blob"])
        blob[33] = (blob[33] % 99) + 1                        # the party level byte becomes BoxLevel (byte 4)
        other["blob"] = bytes(blob)
    wram, cart = _seed("red", [_mon(ot_id=56)], saved={4: [dead], 11: [other]})
    _, _, boxes, gate, calls = _runtime("red", wram, cart)
    gate.arm(gate, "overworld")
    before = (wram[:], cart[:])
    got, reason = boxes.memorialize(oracle.key(oracle.decode_party_mon(dead["blob"])))
    assert got is None and "both box and memorial" in reason
    assert (wram, cart) == before and calls["cart"] == []


def test_memorial_current_box_uses_wram_mirror_only():
    title = "yellow"
    dead = _mon(ot_id=42, hp=0)
    wram, cart = _seed(title, [dead, _mon(ot_id=43)], current=11, initialized=False)
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    before_cart = cart[:]
    key = oracle.key(oracle.decode_party_mon(dead["blob"]))
    assert boxes.memorialize(key) is True
    assert [mon["ot_id"] for mon in _active(title, wram)] == [42]
    assert cart == before_cart and calls["cart"] == []
    assert wram[PROFILE[title]["ram"]["wCurrentBoxNum"]] == 11


def test_corrupt_saved_bank_is_not_recertified_by_a_write():
    title = "red"
    dead = _mon(ot_id=42, hp=0)
    wram, cart = _seed(title, [dead, _mon(ot_id=43)])
    cart[3 * 0x2000 + oracle.BOX_SIZE * 5 + 13] ^= 1
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    old = (wram[:], cart[:])
    got, reason = boxes.memorialize(oracle.key(oracle.decode_party_mon(dead["blob"])))
    assert got is None and "checksums invalid" in reason
    assert (wram, cart) == old and calls == {"wram": [], "cart": []}


def test_replay_finishes_interrupted_deposit_with_matching_bytes():
    title = "red"
    moved, keep = _mon(ot_id=91), _mon(ot_id=92)
    wram, cart = _seed(title, [moved, keep], active=[moved])
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    key = oracle.key(oracle.decode_party_mon(moved["blob"]))
    assert boxes.box_mon(key) is True
    assert [mon["ot_id"] for mon in _party(title, wram)] == [92]
    assert [mon["ot_id"] for mon in _active(title, wram)] == [91]
    assert calls["cart"] == []
    assert calls["wram"] == [(PROFILE[title]["ram"]["wPartyCount"],
                             oracle.PARTY_LAYOUT["size"])]


def test_replay_finishes_interrupted_withdraw_and_memorial():
    title = "blue"
    moved, keep = _mon(ot_id=93), _mon(ot_id=94)
    key = oracle.key(oracle.decode_party_mon(moved["blob"]))
    wram, cart = _seed(title, [keep, moved], saved={11: [moved]})
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    assert boxes.party_mon(key, None) is True  # no stat rebuild: already in party
    assert [mon["ot_id"] for mon in _party(title, wram)] == [94, 93]
    assert _saved(title, cart, 11) == []
    assert calls["wram"] == [] and len(calls["cart"]) == 1
    assert oracle.verify_boxes(cart)["boxes"][12]["valid"]

    moved = _mon(ot_id=95, hp=0)
    key = oracle.key(oracle.decode_party_mon(moved["blob"]))
    wram, cart = _seed(title, [moved, keep], saved={11: [moved]})
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    before_cart = cart[:]
    assert boxes.memorialize(key) is True
    assert [mon["ot_id"] for mon in _party(title, wram)] == [94]
    assert cart == before_cart and calls["cart"] == []
    assert len(calls["wram"]) == 1


def test_replay_refuses_matching_key_with_different_struct():
    title = "yellow"
    moved, keep = _mon(ot_id=96), _mon(ot_id=97)
    other = dict(moved)
    blob = bytearray(moved["blob"])
    blob[1] ^= 1  # same DVs/OT/species key, different physical HP bytes
    other["blob"] = bytes(blob)
    wram, cart = _seed(title, [moved, keep], active=[other])
    _, _, boxes, gate, calls = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    old = (wram[:], cart[:])
    key = oracle.key(oracle.decode_party_mon(moved["blob"]))
    got, reason = boxes.box_mon(key)
    assert got is None and "ambiguous" in reason
    assert (wram, cart) == old and calls == {"wram": [], "cart": []}


def test_client_colon_aliases_preserve_command_results():
    title = "red"
    moved, keep = _mon(ot_id=333, hp=0), _mon(ot_id=334)
    wram, cart = _seed(title, [moved, keep])
    rt, _, boxes, gate, _ = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    key = oracle.key(oracle.decode_party_mon(moved["blob"]))
    assert boxes.deposit(boxes, key) is True
    assert len(_active(title, wram)) == 1
    assert boxes.withdraw(boxes, key, rt.table_from({"maxHP": 1}), rt.table_from(BASE),
                          "BULBA") is True
    assert len(_party(title, wram)) == 2
    assert boxes.memorialize(boxes, key) is True
    assert [mon["ot_id"] for mon in _saved(title, cart, 11)] == [333]


def test_nickname_override_uses_english_charmap_not_cached_stats():
    title = "blue"
    boxed = _mon(ot_id=233)
    wram, cart = _seed(title, [_mon(ot_id=1)], saved={11: [boxed]})
    rt, _, boxes, gate, _ = _runtime(title, wram, cart)
    gate.arm(gate, "overworld")
    key = oracle.key(oracle.decode_party_mon(boxed["blob"]))
    assert boxes.party_mon(key, rt.table_from(BASE), "NIDORAN♂", rt.table_from({"maxHP": 1}))
    assert _party(title, wram)[1]["nickname"] == "NIDORAN♂"
    assert _party(title, wram)[1]["nickname_bytes"] == oracle.encode_name("NIDORAN♂")


# The receptionist's SlinkTradeUIValidName (patch/gen1/purergb/overlay/trade_ui.asm) only
# accepts these literal glyph bytes in a party nickname.
_LITERAL_GLYPHS = set(range(0x7F, 0xC0)) | set(range(0xE0, 0xEC)) | set(range(0xEF, 0x100))


def test_pure_nickname_override_writes_only_literal_glyphs():
    """Live run 2026-09-22: "Rockman" re-encoded greedily as R-o-c-k-m + $34 (pureRGB's
    "an" text-compression code), so SLINK TRADE said "Party data cannot be read"."""
    title = "blue"
    boxed = _mon(ot_id=233)
    wram, cart = _seed(title, [_mon(ot_id=1)], saved={11: [boxed]})
    rt, _, boxes, gate, _ = _runtime(title, wram, cart, "data/games/gen1_purergb/charmap.lua")
    gate.arm(gate, "overworld")
    key = oracle.key(oracle.decode_party_mon(boxed["blob"]))
    assert boxes.party_mon(key, rt.table_from(BASE), "Rockman", rt.table_from({"maxHP": 1}))
    nick = bytes(_party(title, wram)[1]["nickname_bytes"])
    body = nick[:nick.index(0x50)]
    assert len(body) == 7 and set(body) <= _LITERAL_GLYPHS, nick.hex()


# ── gen1-box-durability (mirror of gen2-box-durability, OMP BOX review F1) ─────────────────────────────
# A reset before a native SAVE reloads the SAVED party and current box (WRAM, from sGameData/sCurBoxData,
# pret engine/menus/save.asm LoadSAV); every other saved box keeps whatever SLink wrote into its bank
# (write_target -> write_cart_bytes). Every intermediate state must be a duplicate, never a loss.
class _Crash:
    def __init__(self, title, party, saved):
        self.title = title
        self.wram, self.cart = _seed(title, party, saved=saved)
        self.rt, self.reader, self.boxes, self.gate, _ = _runtime(title, self.wram, self.cart)
        self.gate.arm(self.gate, "overworld")
        self.save()

    def _spans(self):
        ram = PROFILE[self.title]["ram"]
        return ((ram["wPartyCount"], oracle.PARTY_LAYOUT["size"]), (ram["wBoxCount"], oracle.BOX_SIZE))

    def save(self):
        self.saved = [bytes(self.wram[a:a + n]) for a, n in self._spans()]

    def reset(self):
        for (a, n), raw in zip(self._spans(), self.saved):
            self.wram[a:a + n] = raw

    def copies(self, ot_id):
        n = sum(1 for m in _party(self.title, self.wram) if m["ot_id"] == ot_id)
        n += sum(1 for m in _active(self.title, self.wram) if m["ot_id"] == ot_id)
        for index in range(1, 12):   # box 0 is current (WRAM); the rest live in their banks
            n += sum(1 for m in _saved(self.title, self.cart, index) if m["ot_id"] == ot_id)
        return n

    def withdraw(self, key, defer):
        opts = self.rt.table_from({"defer_backing": defer})
        result = self.boxes.party_mon(key, self.rt.table_from(BASE), None, None, opts)
        return result if isinstance(result, tuple) else (result, None)


def _crash(ot_id=77):
    boxed = _mon(ot_id=ot_id)
    world = _Crash("red", [_mon(ot_id=1)], {5: [boxed]})
    return world, oracle.key(oracle.decode_party_mon(boxed["blob"]))


def test_gen1_backing_withdraw_defers_the_box_removal_until_the_save_witness():
    world, key = _crash()
    ok, note = world.withdraw(key, True)
    assert ok is True and "deferred" in note
    assert world.copies(77) == 2                         # a duplicate until the save, never a loss
    world.reset()
    assert world.copies(77) == 1                         # reset before the save: back in the box only
    assert world.boxes.party_mon(key, world.rt.table_from(BASE)) is True    # a clean retry

    world, key = _crash()
    world.withdraw(key, True)
    world.save()                                         # the native save persisted the party
    assert world.boxes.party_mon(key, None) is True      # the settle: replay drops the box copy
    assert world.copies(77) == 1 and _saved("red", world.cart, 5) == []
    assert all(box["valid"] for box in oracle.verify_boxes(world.cart)["boxes"].values())
    world.reset()
    assert world.copies(77) == 1


def test_gen1_immediate_backing_withdraw_is_the_loss_the_deferral_prevents():
    """Known-positive control: the old order removes the durable copy before the party is saved."""
    world, key = _crash()
    assert world.withdraw(key, False)[0] is True
    world.reset()
    assert world.copies(77) == 0


def test_gen1_memorial_of_an_unsettled_withdraw_removes_its_box_source():
    world, key = _crash()
    world.withdraw(key, True)
    assert world.boxes.memorialize(key) is True
    assert world.copies(77) == 1 and _saved("red", world.cart, 5) == []
    assert [m["ot_id"] for m in _saved("red", world.cart, 11)] == [77]   # sBox12, the memorial
    world.reset()
    assert world.copies(77) >= 1


def test_gen1_memorial_source_in_the_memorial_bank_keeps_both_writes():
    """The source box shares bank 3 with sBox12: its removal must not restore the pre-memorial bank."""
    boxed = _mon(ot_id=78)
    world = _Crash("red", [_mon(ot_id=1)], {8: [boxed]})
    key = oracle.key(oracle.decode_party_mon(boxed["blob"]))
    world.withdraw(key, True)
    assert world.boxes.memorialize(key) is True
    assert _saved("red", world.cart, 8) == [] and [m["ot_id"] for m in _saved("red", world.cart, 11)] == [78]
    assert all(box["valid"] for box in oracle.verify_boxes(world.cart)["boxes"].values())
