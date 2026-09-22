"""R-1 differential oracle: new Lua reads against pret-derived Python bytes."""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

from server.adapters import gen1_codec as oracle

ROOT = Path(__file__).resolve().parents[2]
READS = ROOT / "lua" / "gen1" / "reads.lua"
SCANNER = ROOT / "lua" / "token_scanner.lua"
JSON = ROOT / "lua" / "json_codec.lua"
PROFILE = ROOT / "data" / "games" / "gen1_rby" / "profile.json"


def test_source_has_no_literal_absolute_address():
    # Four-digit hex addresses belong to profile.ram. The Lua source may use
    # byte values such as $FF, but must not carry a hardcoded WRAM/SRAM address.
    source = re.sub(r"--[^\n]*", "", READS.read_text(encoding="utf-8"))
    assert not re.search(r"0x[0-9A-Fa-f]{4,}", source)


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Override the repo's disk-writing autouse fixture for this pure test."""
    yield


def _runtime(title: str, memory: bytearray | None = None):
    rt = LuaRuntime(unpack_returned_tuples=True)
    load = rt.eval("dofile")
    json_codec = load(JSON.as_posix())
    profile = json_codec.decode(PROFILE.read_text(encoding="utf-8"))["titles"][title]
    module = load(READS.as_posix())
    memory = memory if memory is not None else bytearray(65536)

    def read_range(addr, length):
        assert isinstance(addr, int) and isinstance(length, int)
        assert 0 <= addr <= len(memory) and 0 <= length <= len(memory) - addr
        return rt.table_from(list(memory[addr:addr + length]))

    # Wrap Python's bytearray callbacks in real Lua functions so the module's
    # injected-IO type check matches the production Lua adapter contract.
    make_io = rt.eval("function(u, range) return {"
                      "read_u8=function(addr) return u(addr) end,"
                      "read_range=function(addr,n) return range(addr,n) end} end")
    io = make_io(lambda addr: memory[addr], read_range)
    reader = module.new(profile, io, load(SCANNER.as_posix()))
    return rt, profile, module, reader, memory


def _py(value, null):
    if hasattr(value, "items") and value["__gen1_null"] is True:
        return None
    if hasattr(value, "items"):
        pairs = list(value.items())
        if not pairs or all(isinstance(k, int) for k, _ in pairs):
            assert sorted(k for k, _ in pairs) == list(range(1, len(pairs) + 1))
            return [_py(value[i], null) for i in range(1, len(pairs) + 1)]
        out = {k: _py(v, null) for k, v in pairs}
        for key in ("ot_name_bytes", "nickname_bytes"):
            if key in out:
                out[key] = bytes(out[key])
        return out
    return value


def _bytes(rt, b):
    return rt.table_from(list(b))


def _with_slots(mons):
    return [{**mon, "slot": slot} for slot, mon in enumerate(mons)]


def _block(capacity: int, box: bool, count: int, rng: random.Random) -> bytes:
    layout = oracle.BOX_LAYOUT if box else oracle.PARTY_LAYOUT
    size = oracle.BOX_MON_SIZE if box else oracle.PARTY_MON_SIZE
    b = bytearray(rng.randbytes(layout["size"]))
    b[0] = count
    b[1 + count] = 0xFF
    for slot in range(count):
        species = rng.randrange(1, 255)
        b[1 + slot] = species
        b[layout["mons"] + slot * size] = species
    assert count <= capacity
    return bytes(b)


def _write_collection(memory, profile, raw, *, box):
    ram = profile["ram"]
    layout = oracle.BOX_LAYOUT if box else oracle.PARTY_LAYOUT
    prefix = "wBox" if box else "wParty"
    for symbol, start, length in (
        (prefix + "Count", 0, 1),
        (prefix + "Species", 1, layout["mons"] - 1),
        (prefix + "Mons", layout["mons"], layout["ot_names"] - layout["mons"]),
        (prefix + "MonOT", layout["ot_names"], layout["nicknames"] - layout["ot_names"]),
        (prefix + "MonNicks", layout["nicknames"], layout["size"] - layout["nicknames"]),
    ):
        addr = ram[symbol]
        memory[addr:addr + length] = raw[start:start + length]


@pytest.mark.parametrize("title", ("red", "blue", "yellow"))
def test_record_and_name_differential(title):
    rt, _, module, r, _ = _runtime(title)
    rng = random.Random(915 + len(title))
    for box, size in ((False, 44), (True, 33)):
        for _ in range(2000):
            raw = rng.randbytes(size)
            got = _py(r.decode_party_mon(_bytes(rt, raw), box), module.NULL)
            assert got == oracle.decode_party_mon(raw, box=box)
            assert r.key(r.decode_party_mon(_bytes(rt, raw), box)) == oracle.key(got)
    for _ in range(2000):
        raw = rng.randbytes(11)
        assert r.decode_name(_bytes(rt, raw)) == oracle.decode_name(raw)
    for terminator_at in range(11):
        raw = bytearray(rng.randbytes(11))
        raw[terminator_at] = 0x50
        assert r.decode_name(_bytes(rt, raw)) == oracle.decode_name(raw)


@pytest.mark.parametrize("title", ("red", "blue", "yellow"))
def test_random_collections_and_town_save(title):
    rt, profile, module, r, memory = _runtime(title)
    rng = random.Random(2369 + len(title))
    for box, cap, read, decode in (
        (False, 6, r.read_party, oracle.decode_party),
        (True, 20, r.read_active_box, oracle.decode_box),
    ):
        for _ in range(200):
            raw = _block(cap, box, rng.randrange(cap + 1), rng)
            _write_collection(memory, profile, raw, box=box)
            assert _py(read(), module.NULL) == _with_slots(decode(raw))

    save = (ROOT / "tests" / "fixtures" / "gen1" / f"{title}_town.SaveRAM").read_bytes()
    assert len(save) == 32768
    ram, banks = profile["ram"], profile["sram_bank"]
    bank_size = len(save) // (profile["derived"]["sram_box_banks"][2] + 1)
    start = banks["sPartyData"] * bank_size + ram["sPartyData"] - ram["sBox1"]
    raw = save[start:start + oracle.PARTY_LAYOUT["size"]]
    assert len(raw) == oracle.PARTY_LAYOUT["size"]
    _write_collection(memory, profile, raw, box=False)
    got = _py(r.read_party(), module.NULL)
    assert got == _with_slots(oracle.decode_party(raw))
    for mon in got:
        assert r.key(r.decode_party_mon(_bytes(rt, oracle.encode_party_mon(mon)), False)) == (
            oracle.key(mon)
        )


@pytest.mark.parametrize("title", ("red", "blue", "yellow"))
def test_refusals_are_differential(title):
    rt, profile, _, r, memory = _runtime(title)
    rng = random.Random(808)
    valid = bytearray(_block(6, False, 1, rng))
    _write_collection(memory, profile, valid, box=False)
    assert isinstance(r.read_party(), type(rt.table_from([])))

    invalid = valid.copy()
    invalid[0] = 7
    _write_collection(memory, profile, invalid, box=False)
    got, reason = r.read_party()
    assert got is None and "capacity" in reason
    with pytest.raises(ValueError, match="capacity"):
        oracle.decode_party(invalid)

    invalid = valid.copy()
    invalid[2] = 0
    _write_collection(memory, profile, invalid, box=False)
    got, reason = r.read_party()
    assert got is None and "terminator" in reason
    with pytest.raises(ValueError, match="terminator"):
        oracle.decode_party(invalid)

    invalid = valid.copy()
    invalid[1] = 0
    invalid[oracle.PARTY_LAYOUT["mons"]] = 0
    _write_collection(memory, profile, invalid, box=False)
    got, reason = r.read_party()
    assert got is None and "invalid species" in reason
    with pytest.raises(ValueError, match="species 0 inside the count"):  # differential refusal
        oracle.decode_party(invalid)


@pytest.mark.parametrize("title", ("red", "blue", "yellow"))
def test_all_twelve_sram_boxes(title):
    rt, profile, module, r, _ = _runtime(title)
    rng = random.Random(1122)
    image = bytearray(32768)
    ram, derived = profile["ram"], profile["derived"]
    bank_size = len(image) // (derived["sram_box_banks"][2] + 1)
    expected = {}
    for index in range(12):
        count = 2 if index in (0, 11) else 0
        block = bytearray(_block(20, True, count, rng))
        for slot in range(count):
            start = oracle.BOX_LAYOUT["mons"] + slot * oracle.BOX_MON_SIZE
            mon = oracle.decode_party_mon(block[start:start + oracle.BOX_MON_SIZE], box=True)
            block[start:start + oracle.BOX_MON_SIZE] = oracle.encode_party_mon(mon)
            name = oracle.encode_name(f"BOX{index}S{slot}")
            ot = oracle.BOX_LAYOUT["ot_names"] + slot * oracle.NAME_SIZE
            nick = oracle.BOX_LAYOUT["nicknames"] + slot * oracle.NAME_SIZE
            block[ot:ot + oracle.NAME_SIZE] = name
            block[nick:nick + oracle.NAME_SIZE] = name
        bank_slot = index // derived["sram_boxes_per_bank"]
        bank = derived["sram_box_banks"][bank_slot + 1]
        anchor = "sBox1" if bank_slot == 0 else "sBox7"
        offset = (bank * bank_size + ram[anchor] - ram["sBox1"]
                  + index % derived["sram_boxes_per_bank"] * derived["sram_box_stride"])
        image[offset:offset + len(block)] = block
        expected[index] = _with_slots(oracle.decode_box(block))
    raw = _bytes(rt, image)
    for index in range(12):
        assert _py(r.read_sram_box(raw, index), module.NULL) == expected[index]
    for invalid in (-1, 12, 1.5):
        got, reason = r.read_sram_box(raw, invalid)
        assert got is None and "index" in reason


def _seed_ancillary(memory, profile):
    ram = profile["ram"]
    for symbol, values in {
        "wCurrentBoxNum": (0x8B,), "wNumBagItems": (2,),
        "wBagItems": (4, 7, 9, 3, 0xFF), "wObtainedBadges": (0xA5,),
        "wPlayerID": (0x12, 0x34), "wPlayerName": tuple(oracle.encode_name("RED")),
        "wPlayerMoney": (0x12, 0x34, 0x56),
        "wCurMap": (17,), "wXCoord": (21,), "wYCoord": (8,),
        "wIsInBattle": (2,), "wBattleType": (0,), "wCurOpponent": (202,),
        "wEnemyMonSpecies": (35,), "wEnemyMonLevel": (14,),
        "wEnemyMonHP": (1, 2), "wBattleMonHP": (3, 4),
        "wPlayerMonNumber": (5,), "wBattleResult": (1,), "wLinkState": (6,),
        "wSaveFileStatus": (2,), "wOptions": (0x4D,), "wStatusFlags4": (0x80,),
    }.items():
        address = ram[symbol]
        memory[address:address + len(values)] = bytes(values)
    for stem in ("wPlayerMon", "wEnemyMon"):
        for value, name in enumerate(("Attack", "Defense", "Speed", "Special",
                                      "Accuracy", "Evasion"), 4):
            memory[ram[stem + name + "Mod"]] = value


def _snapshot(r, null):
    return {
        "party": _py(r.read_party(), null), "box": _py(r.read_active_box(), null),
        "current": _py(r.read_current_box_num(), null),
        "bag": _py(r.read_bag(), null), "has_item": r.has_item(4),
        "badges": r.read_badges(), "player_id": r.read_player_id(),
        "player_name": r.read_player_name(), "money": r.read_money(),
        "map": _py(r.read_map(), null), "battle": _py(r.read_battle(), null),
        "player_stages": _py(r.read_stat_stages("player"), null),
        "enemy_stages": _py(r.read_stat_stages("enemy"), null),
        "save_status": r.read_save_file_status(), "options": r.read_options(),
        "flags": r.read_status_flags4(),
    }


@pytest.mark.parametrize("title", ("red", "blue", "yellow"))
def test_ancillary_reads_and_all_addresses_follow_shifted_profile(title):
    rt, profile, module, r, memory = _runtime(title)
    rng = random.Random(451)
    _write_collection(memory, profile, _block(6, False, 1, rng), box=False)
    _write_collection(memory, profile, _block(20, True, 1, rng), box=True)
    _seed_ancillary(memory, profile)
    original = _snapshot(r, module.NULL)
    assert original["current"] == {"raw": 139, "index": 11, "initialized": True}
    assert original["bag"] == {"items": [{"id": 4, "qty": 7}, {"id": 9, "qty": 3}]}
    assert original["badges"] == 0xA5 and original["player_id"] == 0x1234
    assert original["money"] == 123456 and original["map"] == {"map": 17, "x": 21, "y": 8}
    assert original["battle"]["is_trainer"]
    assert original["battle"]["trainer_class"] == 2
    assert original["battle"]["enemy_hp"] == 0x102
    assert original["battle"]["battle_mon_hp"] == 0x304
    assert r.has_item(4) and not r.has_item(255)
    assert original["player_stages"] == dict(zip(
        ("attack", "defense", "speed", "special", "accuracy", "evasion"),
        range(4, 10), strict=True,
    ))
    assert len(original["player_stages"]) == 6  # 7 is neutral, not a seventh modifier.

    # Every RAM symbol is moved, then only the moved image is populated. The
    # whole snapshot therefore proves each tested read uses profile addresses.
    shifted_memory = bytearray(65536)
    shift = 256
    shifted_memory[0xC000 + shift:0xE000 + shift] = memory[0xC000:0xE000]
    _, shifted_profile, shifted_module, shifted_r, _ = _runtime(title, shifted_memory)
    for key in list(shifted_profile["ram"].keys()):
        shifted_profile["ram"][key] += shift
    assert _snapshot(shifted_r, shifted_module.NULL) == original

    memory[profile["ram"]["wCurrentBoxNum"]] = 11
    assert _py(r.read_current_box_num(), module.NULL) == {
        "raw": 11, "index": 11, "initialized": False,
    }
    memory[profile["ram"]["wCurrentBoxNum"]] = 12
    got, reason = r.read_current_box_num()
    assert got is None and "outside" in reason
    memory[profile["ram"]["wCurrentBoxNum"]] = 0x8B
    memory[profile["ram"]["wBagItems"] + 1] = 0
    assert not r.has_item(4)
    memory[profile["ram"]["wBagItems"] + 1] = 7

    memory[profile["ram"]["wPlayerMoney"]] = 0xFA
    got, reason = r.read_money()
    assert got is None and "BCD" in reason
    memory[profile["ram"]["wPlayerMoney"]] = 0x12
    memory[profile["ram"]["wBagItems"] + 4] = 0
    got, reason = r.read_bag()
    assert got is None and "terminator" in reason
    assert r.has_item(4)[0] is None
    memory[profile["ram"]["wBagItems"] + 4] = 255
    memory[profile["ram"]["wCurOpponent"]] = 4
    battle = _py(r.read_battle(), module.NULL)
    assert not battle["is_trainer"] and battle["trainer_class"] is None
    got, reason = r.read_stat_stages("invalid")
    assert got is None and "side" in reason


# ── pureRGB profile (data/games/gen1_purergb): rows 6, 11 and the new accessors ──────────
PURE_PROFILE = ROOT / "data" / "games" / "gen1_purergb" / "profile.json"


def _pure_runtime(title="purered"):
    rt = LuaRuntime(unpack_returned_tuples=True)
    load = rt.eval("dofile")
    json_codec = load(JSON.as_posix())
    profile = json_codec.decode(PURE_PROFILE.read_text(encoding="utf-8"))["titles"][title]
    profile["charmap"] = load((PURE_PROFILE.parent / "charmap.lua").as_posix())  # as entry.lua does
    module = load(READS.as_posix())
    memory = bytearray(65536)
    make_io = rt.eval("function(u, range) return {"
                      "read_u8=function(addr) return u(addr) end,"
                      "read_range=function(addr,n) return range(addr,n) end} end")
    io = make_io(lambda addr: memory[addr],
                 lambda addr, n: rt.table_from(list(memory[addr:addr + n])))
    return rt, profile, module, module.new(profile, io, load(SCANNER.as_posix())), memory


def test_pure_bag_capacity_comes_from_derived_not_from_symbol_arithmetic():
    """wPlayerMoney precedes wBagItems on pureRGB: the vanilla formula would be negative."""
    rt, profile, module, r, memory = _pure_runtime()
    ram = profile["ram"]
    assert ram["wPlayerMoney"] < ram["wBagItems"]
    assert r.bag_capacity == profile["derived"]["bag_capacity"] == 30
    memory[ram["wNumBagItems"]] = 30
    for i in range(30):
        memory[ram["wBagItems"] + 2 * i], memory[ram["wBagItems"] + 2 * i + 1] = 4, i + 1
    memory[ram["wBagItems"] + 60] = 0xFF
    bag = _py(r.read_bag(), module.NULL)
    assert len(bag["items"]) == 30 and bag["items"][29] == {"id": 4, "qty": 30}


def test_pure_trainer_threshold_and_the_new_battle_fields():
    rt, profile, module, r, memory = _pure_runtime()
    ram = profile["ram"]
    memory[ram["wCurOpponent"]] = 199
    memory[ram["wSafariType"]] = 1
    memory[ram["wBattleFunctionalFlags"]] = 0x02
    battle = _py(r.read_battle(), module.NULL)
    assert battle["is_trainer"] and battle["trainer_class"] == 2
    assert battle["safari_type"] == 1 and battle["functional_flags"] == 2
    memory[ram["wCurOpponent"]] = 196
    assert not _py(r.read_battle(), module.NULL)["is_trainer"]
    # vanilla carries neither symbol, so neither field
    _, _, vmodule, vr, _ = _runtime("red")
    vb = _py(vr.read_battle(), vmodule.NULL)
    assert "safari_type" not in vb and "functional_flags" not in vb


def test_pure_daycare_and_game_version_accessors():
    rt, profile, module, r, memory = _pure_runtime()
    ram = profile["ram"]
    got, why = r.read_daycare_mon()
    assert got is None and "empty" in why
    memory[ram["wDayCareInUse"]] = 1
    mon = oracle.decode_party_mon(bytes(random.Random(3).randrange(256) for _ in range(44)))
    mon["species"] = 0x15
    memory[ram["wDayCareMon"]:ram["wDayCareMon"] + 44] = oracle.encode_party_mon(mon)
    assert _py(r.read_daycare_mon(), module.NULL)["species"] == 0x15
    memory[ram["wGameInternalVersion"]] = 7
    assert r.read_game_internal_version() == 7
    _, _, _, vr, _ = _runtime("red")
    assert vr.read_game_internal_version() is None
    assert vr.read_daycare_mon()[0] is None


def test_the_pack_charmap_drives_decode_name_when_present():
    rt, profile, module, r, memory = _pure_runtime()
    cm = r.charmap
    assert cm.terminator == 0x50 and cm.glyphs[0xE9] == "→"
    assert r.decode_name(rt.table_from([0x80, 0x9E, 0x50, 0x81])) == "A“"
    # without a pack charmap the vanilla table is the same object for every reader
    vrt, _, vmodule, vr, _ = _runtime("red")
    assert vr.decode_name(vrt.table_from([0x9E, 0x50])) == "["
    assert vmodule.charmap(None).glyphs[0x9E] == "["


@pytest.mark.parametrize("stream", [
    "{0x80, 0x50, false}",  # A terminator does not excuse malformed field bytes.
    "{[1]=0x80, [3]=0x81}",
    "{[1]=0x80, extra=0x81}",
    "{0x80, 256}",
])
def test_malformed_name_stream_refuses_without_partial_text(stream):
    rt, _, _, reader, _ = _runtime("red")
    result = reader.decode_name(rt.eval(stream))
    assert isinstance(result, tuple) and result[0] is None and isinstance(result[1], str)


def test_collection_propagates_invalid_name_after_terminator():
    rt, _, _, reader, _ = _runtime("red")
    raw = _bytes(rt, _block(20, True, 1, random.Random(882)))
    raw[oracle.BOX_LAYOUT["ot_names"] + 1] = 0x50
    raw[oracle.BOX_LAYOUT["ot_names"] + 2] = False
    result = reader.box_from_snapshot(raw)
    assert isinstance(result, tuple) and result[0] is None and "name" in result[1]


def test_scanner_dependency_is_required_without_implicit_loading():
    rt, profile, module, _, _ = _runtime("red")
    io = rt.eval("{read_u8=function() error('IO must not run') end, "
                 "read_range=function() error('IO must not run') end}")
    with pytest.raises(LuaError, match="Scanner required"):
        module.new(profile, io)


@pytest.mark.parametrize("title", ["purered", "pureblue", "puregreen"])
def test_pure_name_bytes_still_match_independent_python_oracle(title):
    rt, _, _, reader, _ = _pure_runtime(title)
    layout = oracle.for_foundation("gen1_purergb")
    for value in range(256):
        raw = bytes([value, 0x50, 0xff])
        assert reader.decode_name(_bytes(rt, raw)) == layout.decode_name(raw)


def test_gen1_alias_codes_and_unknown_spelling_remain_game_owned():
    rt, profile, module, _, _ = _runtime("red")
    profile.charmap = rt.eval('{terminator=0x50,glyphs={[1]="alias",[2]="alias",[0x50]="@"}}')
    io = rt.eval("{read_u8=function() return 0 end, read_range=function() return {} end}")
    reader = module.new(profile, io, rt.eval("dofile")(SCANNER.as_posix()))
    assert reader.charmap.codes["alias"] == 1
    assert reader.decode_name(rt.table_from([1, 2, 9, 0x50])) == "aliasalias<$09>"
