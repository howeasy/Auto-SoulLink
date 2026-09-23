"""Gen 3 PC moves through the public boxes API and the independent save codec."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]
LUA = ROOT / "lua" / "gen3"


class Cart:
    def __init__(self, title="firered"):
        self.title = title
        pack = "gen3_rr" if title == "radical_red" else "gen3_frlg"
        self.profile = copy.deepcopy(json.loads(
            (ROOT / "data" / "games" / pack / "profile.json").read_text()
        )["titles"][title])
        self.profile["rom"]["EXPERIENCE_TABLES_ADDR"] = {
            "firered": 0x08253AE4, "leafgreen": 0x08253AC0,
        }.get(title, 0x09000000)
        self.profile["rom"]["BATTLE_MOVES_ADDR"] = {
            "firered": 0x08250C04, "leafgreen": 0x08250BE0,
        }.get(title, 0x09001000)
        self.profile["rom"]["PP_UP_GET_MASK_ADDR"] = {
            "firered": 0x0825DEA1, "leafgreen": 0x0825DE81,
        }.get(title, 0x09002000)
        self.profile["derived"]["BATTLE_MOVE_ENTRY_SIZE"] = 12
        self.profile["derived"]["BATTLE_MOVE_PP_OFFSET"] = 4
        self.profile["derived"]["SHEDINJA_SPECIES_ID"] = 303
        self.bus: dict[int, int] = {}
        self.rom: dict[int, int] = {}
        self.written: list[tuple[int, int]] = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        runtime = self.lua
        self.p = runtime.table_from(self.profile, recursive=True)

        def read_u8(addr):
            return self.bus.get(int(addr), 0)

        def read_u32(addr):
            return sum(read_u8(int(addr) + i) << (8 * i) for i in range(4))

        def read_bytes(addr, length):
            return runtime.table(*[read_u8(int(addr) + i) for i in range(int(length))])

        def rom_read(offset, length):
            return runtime.table(*[self.rom.get(int(offset) + i, 0)
                                   for i in range(int(length))])

        def write_u8(addr, value, *_):
            self.bus[int(addr)] = int(value)
            self.written.append((int(addr), int(value)))

        self.io = runtime.table(read_u8=read_u8, read_u32=read_u32,
                                read_bytes=read_bytes, rom_read=rom_read)
        reads_mod = runtime.execute((LUA / "reads.lua").read_text(encoding="utf-8"))
        writes_mod = runtime.execute((LUA / "writes.lua").read_text(encoding="utf-8"))
        self.reads = reads_mod.new(self.p, self.io)
        self.writes = writes_mod.new(runtime.table(
            safety=runtime.table(snapshot=lambda *_: runtime.table(), check=lambda *_: True),
            frame=lambda: 7, io=runtime.table(write_u8=write_u8)))
        self.boxes = None
        box_file = LUA / "boxes.lua"
        if box_file.exists():
            boxes_mod = runtime.execute(box_file.read_text(encoding="utf-8"))
            self.boxes = boxes_mod.new(self.p, self.reads, runtime.table(
                read_bytes=read_bytes, rom_read=rom_read, writes=self.writes))
        ram = self.profile["ram"]
        if title != "radical_red":
            self.poke(ram["PSP_PTR_ADDR"], ram["POKEMON_STORAGE_BASE"].to_bytes(4, "little"))
        self.storage = ram["POKEMON_STORAGE_BASE"]
        self.party_base = ram["PARTY_BASE"]
        self.party_count = ram["PARTY_COUNT_ADDR"]

    def poke(self, addr, data):
        for i, value in enumerate(data):
            self.bus[addr + i] = value

    def raw(self, addr, length):
        return bytes(self.bus.get(addr + i, 0) for i in range(length))

    def box_addr(self, box, slot=0):
        d = self.profile["derived"]
        if self.title == "radical_red":
            return d["CFRU_BOX_BASES"][box] + slot * d["COMPRESSED_MON_SIZE"]
        return (self.storage + d["BOX_DATA_OFFSET"]
                + (box * d["MONS_PER_BOX"] + slot) * codec.BOX_MON_SIZE)

    def seed_rom(self, address, data):
        for i, value in enumerate(data):
            self.rom[address - 0x08000000 + i] = value

    def seed_vanilla_stats(self):
        self.seed_rom(0x080000AC, b"BPGE" if self.title == "leafgreen" else b"BPRE")
        base = bytearray(28)
        base[:6] = bytes([45, 49, 49, 45, 65, 65])  # Bulbasaur stat control
        base[0x13] = 0  # medium-fast growth
        code = "BPGE" if self.title == "leafgreen" else "BPRE"
        addr = self.profile["derived"]["BASESTATS_ADDR_BY_GAME_CODE"][code]
        self.seed_rom(addr + 28, base)  # species 1
        thresholds = (0, 1, 8, 27, 64, 125, 216)
        self.seed_rom(self.profile["rom"]["EXPERIENCE_TABLES_ADDR"], b"".join(
            n.to_bytes(4, "little") for n in thresholds
        ))

    def seed_rr_stats(self):
        base_addr = 0x09010000
        self.seed_rom(self.profile["rom"]["CFRU_BASESTATS_PTR"],
                      base_addr.to_bytes(4, "little"))
        base = bytearray(28)
        base[:6] = bytes([45, 49, 49, 45, 65, 65])
        base[0x13] = 0
        self.seed_rom(base_addr + 28, base)
        self.seed_rom(self.profile["rom"]["EXPERIENCE_TABLES_ADDR"], b"".join(
            n.to_bytes(4, "little") for n in (0, 1, 8, 27, 64, 125, 216)
        ))

    def seed_move_pp(self):
        self.seed_rom(self.profile["rom"]["BATTLE_MOVES_ADDR"] + 33 * 12 + 4, b"\x23")
        self.seed_rom(self.profile["rom"]["BATTLE_MOVES_ADDR"] + 4, b"\x23")  # RR move0 PP
        self.seed_rom(self.profile["rom"]["PP_UP_GET_MASK_ADDR"], b"\x03\x0c\x30\xc0")

    def put_party(self, records):
        self.poke(self.party_count, bytes([len(records)]))
        for slot, record in enumerate(records):
            self.poke(self.party_base + 100 * slot, record)

    def key(self, record):
        mon = codec.decode_party_mon(record, rr=self.title == "radical_red")
        return f"{mon['personality']:08X}:{mon['ot_id']:08X}"


def mon_bytes(personality, *, rr=False, pp=2):
    """Fixture-derived fields, then a Bulbasaur control with deterministic stats."""
    save = (ROOT / "tests" / "fixtures" / "gen3" / "rr_town.sav").read_bytes()
    first = codec.rr_party_from_save(save)[0]
    mon = copy.deepcopy(first)
    mon.update(personality=personality, ot_id=123, species=1, experience=125,
               hp=10, max_hp=19, level=5, attack=9, defense=9, speed=9,
               sp_attack=11, sp_defense=11, moves=[33, 0, 0, 0],
               pp=[pp, 0, 0, 0], pp_bonuses=1, status=0)
    mon["ivs"] = dict.fromkeys(mon["ivs"], 0)
    mon["evs"] = dict.fromkeys(mon["evs"], 0)
    return codec.encode_party_mon(mon, rr=rr)


def changed_mon(raw, *, rr=False, **fields):
    mon = codec.decode_party_mon(raw, rr=rr)
    mon.update(fields)
    return codec.encode_party_mon(mon, rr=rr)


def empty_party_record():
    return bytes(0x55) + b"\xFF" + bytes(100 - 0x56)  # pret ZeroMonData: MAIL_NONE


@pytest.mark.parametrize("operation", ["deposit", "memorialize"])
@pytest.mark.parametrize("unusable", ["fainted", "egg"])
def test_removing_the_last_alive_non_egg_is_refused(operation, unusable):
    cart = Cart()
    target, other = mon_bytes(50), mon_bytes(75)
    other = changed_mon(other, hp=0) if unusable == "fainted" else changed_mon(other, is_egg=1)
    cart.put_party([target, other])
    cart.seed_move_pp()
    assert getattr(cart.boxes, operation)(cart.boxes, cart.key(target), 0) == (None, "last party mon")
    assert cart.written == []


@pytest.mark.parametrize("operation", ["deposit", "memorialize"])
def test_validated_hint_selects_one_of_the_ninjask_shedinja_shared_keys(operation):
    cart = Cart()
    first = changed_mon(mon_bytes(50), species=302)
    second = changed_mon(mon_bytes(50), species=303)
    cart.put_party([first, second, mon_bytes(75)])
    cart.seed_move_pp()
    assert getattr(cart.boxes, operation)(cart.boxes, cart.key(first), 1) is True
    box = 0 if operation == "deposit" else cart.boxes.memorial_box
    assert codec.decode_box_mon(cart.raw(cart.box_addr(box), 80))["species"] == 303
    assert codec.decode_party_mon(cart.raw(cart.party_base, 100))["species"] == 302


def test_holding_mail_refuses_deposit_without_mutation():
    cart = Cart()
    target = changed_mon(mon_bytes(50), held_item=121)
    cart.put_party([target, mon_bytes(75)])
    cart.seed_move_pp()
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 0) == (None, "holding mail")
    assert cart.written == []


def test_deposit_refuses_the_last_party_mon_without_any_write():
    cart = Cart()
    record = mon_bytes(50)
    cart.put_party([record])
    assert cart.boxes is not None, "boxes.lua must implement the public seam"
    ok, reason = cart.boxes.deposit(cart.boxes, cart.key(record), 0)
    assert ok is None and reason == "last party mon"
    assert cart.written == []
    assert len(cart.writes.log) == 0


def test_deposit_restores_depleted_pp_and_preserves_the_other_box_fields():
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50, pp=2)
    cart.put_party([lead, target])
    # pret src/pokemon.c:3898-3902: Tackle base PP 35, one PP Up => 42.
    cart.seed_move_pp()
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    assert cart.raw(cart.party_count, 1) == b"\x01"
    assert cart.raw(cart.party_base, 100) == lead
    assert cart.raw(cart.party_base + 100, 100) == empty_party_record()
    expected = codec.decode_party_mon(target)
    expected["pp"] = [42, 0, 0, 0]
    boxed = cart.raw(cart.box_addr(0), 80)
    assert boxed == codec.encode_box_mon(expected)
    assert codec.decode_box_mon(boxed)["checksum_ok"] is True
    count = len(cart.written)
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    assert len(cart.written) == count
    assert {str(cart.writes.log[i].reason) for i in range(1, len(cart.writes.log) + 1)} == {
        "overworld"
    }


@pytest.mark.parametrize("permutation", range(24))
def test_pp_restore_uses_the_personality_substructure_permutation(permutation):
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(24 + permutation, pp=1)
    cart.put_party([lead, target])
    cart.seed_move_pp()
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    expected = codec.decode_party_mon(target)
    expected["pp"] = [42, 0, 0, 0]
    assert cart.raw(cart.box_addr(0), 80) == codec.encode_box_mon(expected)


def test_rr_deposit_uses_the_pack_scattered_compressed_box_layout():
    cart = Cart("radical_red")
    lead, target = mon_bytes(75, rr=True), mon_bytes(50, rr=True)
    cart.put_party([lead, target])
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    raw = cart.raw(cart.box_addr(0), 58)
    assert len(raw) == 58
    expanded = codec.expand_compressed_box_mon(raw)
    boxed = codec.decode_box_mon(expanded, rr=True)
    original = codec.decode_party_mon(target, rr=True)
    for field in ("personality", "ot_id", "species", "held_item", "experience",
                  "moves", "evs", "ivs", "nickname"):
        assert boxed[field] == original[field], field
    assert cart.raw(cart.party_count, 1) == b"\x01"
    assert cart.raw(cart.party_base, 100) == lead


def test_deposit_compacts_a_middle_party_slot_and_updates_the_count():
    cart = Cart()
    first, middle, last = mon_bytes(25), mon_bytes(50), mon_bytes(75)
    cart.put_party([first, middle, last])
    cart.seed_move_pp()
    assert cart.boxes.deposit(cart.boxes, cart.key(middle), 1) is True
    assert cart.raw(cart.party_count, 1) == b"\x02"
    assert cart.raw(cart.party_base, 100) == first
    assert cart.raw(cart.party_base + 100, 100) == last
    assert cart.raw(cart.party_base + 200, 100) == empty_party_record()


@pytest.mark.parametrize("offset", [4, 64, 124])
def test_vanilla_box_write_follows_the_live_storage_pointer(offset):
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    cart.seed_move_pp()
    cart.poke(cart.profile["ram"]["PSP_PTR_ADDR"],
              (cart.storage + offset).to_bytes(4, "little"))
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    live_box = cart.storage + offset + cart.profile["derived"]["BOX_DATA_OFFSET"]
    assert codec.decode_box_mon(cart.raw(live_box, 80))["species"] == 1
    assert cart.raw(cart.storage, 4) == bytes(4)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_vanilla_withdraw_recalculates_level_and_stats_from_rom(title):
    cart = Cart(title)
    cart.seed_vanilla_stats()
    lead, target = mon_bytes(75), mon_bytes(50, pp=2)
    cart.put_party([lead, target])
    cart.seed_move_pp()
    key = cart.key(target)
    assert cart.boxes.deposit(cart.boxes, key, 1) is True
    assert cart.boxes.withdraw(cart.boxes, key, cart.lua.table(level=99, maxHP=999), None) is True
    restored = cart.raw(cart.party_base + 100, 100)
    decoded = codec.decode_party_mon(restored)
    assert decoded["checksum_ok"] is True
    assert decoded["pp"] == [42, 0, 0, 0]
    assert (decoded["level"], decoded["hp"], decoded["max_hp"], decoded["status"],
            decoded["mail"]) == (5, 19, 19, 0, 0xFF)
    assert (decoded["attack"], decoded["defense"], decoded["speed"],
            decoded["sp_attack"], decoded["sp_defense"]) == (9, 9, 9, 11, 11)
    assert cart.raw(cart.box_addr(0), 80) == bytes(80)
    assert cart.raw(cart.party_count, 1) == b"\x02"
    count = len(cart.written)
    assert cart.boxes.withdraw(cart.boxes, key, None, None) is True
    assert len(cart.written) == count


def test_rr_withdraw_expands_record_and_requires_a_valid_stat_cache():
    cart = Cart("radical_red")
    lead, target = mon_bytes(75, rr=True), mon_bytes(50, rr=True)
    cart.put_party([lead, target])
    key = cart.key(target)
    assert cart.boxes.deposit(cart.boxes, key, 1) is True
    before = len(cart.written)
    ok, reason = cart.boxes.withdraw(cart.boxes, key, None, None)
    assert ok is None and reason == "missing stats"
    assert len(cart.written) == before
    ok, reason = cart.boxes.withdraw(cart.boxes, key, cart.lua.table(level=5, maxHP=19), None)
    assert ok is None and reason == "missing stats"
    assert len(cart.written) == before
    cached = cart.lua.table(level=5, maxHP=19, attack=9, defense=9, speed=9,
                            spAtk=11, spDef=11, pp1=7)
    cart.seed_move_pp()
    assert cart.boxes.withdraw(cart.boxes, key, cached, None) is True
    restored = codec.decode_party_mon(cart.raw(cart.party_base + 100, 100), rr=True)
    assert (restored["personality"], restored["species"], restored["level"],
            restored["hp"], restored["max_hp"], restored["pp"][0]) == (50, 1, 5, 19, 19, 42)
    assert restored["pp"][1:] == [35, 35, 35]
    assert cart.raw(cart.box_addr(0), 58) == bytes(58)


def test_rr_scan_reads_nonzero_growth_row_with_256_entries_above_level_100():
    cart = Cart("radical_red")
    cart.seed_rr_stats()
    cart.seed_rom(0x09010000 + 28 + cart.profile["derived"]["BASESTATS_GROWTH_RATE_OFFSET"], b"\x01")
    count = cart.profile["derived"]["EXPERIENCE_TABLE_ENTRY_COUNT"]
    assert count == 256 and cart.profile["derived"]["MAX_LEVEL"] == 250
    # Distinct synthetic row. Vanilla stride indexes zeros; a 100-level cap also fails.
    cart.seed_rom(cart.profile["rom"]["EXPERIENCE_TABLES_ADDR"] + count * 4,
                  b"".join((n * 10).to_bytes(4, "little") for n in range(count)))
    mon = codec.decode_party_mon(mon_bytes(50, rr=True), rr=True)
    mon["experience"] = 1250
    target = codec.encode_party_mon(mon, rr=True)
    cart.put_party([mon_bytes(75, rr=True), target])
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    assert cart.boxes.scan(cart.boxes)[1].level == 125


@pytest.mark.parametrize("cached_pp,rom_available,expected", [(None, True, 42), (0, True, 42),
                                                          (None, False, None), (7, False, None)])
def test_rr_pp_refills_from_rom_even_with_depleted_cache(cached_pp, rom_available, expected):
    cart = Cart("radical_red")
    target = mon_bytes(50, rr=True)
    cart.put_party([mon_bytes(75, rr=True), target])
    key = cart.key(target)
    assert cart.boxes.deposit(cart.boxes, key, 1) is True
    if rom_available:
        cart.seed_move_pp()
    stats = cart.lua.table(level=125, maxHP=231, attack=144, defense=145, speed=146,
                           spAtk=147, spDef=148, pp1=cached_pp)
    before = len(cart.written)
    result = cart.boxes.withdraw(cart.boxes, key, stats, None)
    if expected is None:
        assert result == (None, "PP unavailable")
        assert len(cart.written) == before
    else:
        assert result is True
        mon = codec.decode_party_mon(cart.raw(cart.party_base + 100, 100), rr=True)
        assert mon["pp"][0] == expected
        assert (mon["level"], mon["max_hp"], mon["attack"], mon["sp_defense"]) == (125, 231, 144, 148)


@pytest.mark.parametrize("title", ["firered", "radical_red"])
def test_memorialize_moves_the_target_from_party_and_is_idempotent(title):
    cart = Cart(title)
    rr = title == "radical_red"
    lead, target = mon_bytes(75, rr=rr), mon_bytes(50, rr=rr)
    cart.put_party([lead, target])
    if not rr:
        cart.seed_move_pp()
    key = cart.key(target)
    assert cart.boxes.memorialize(cart.boxes, key, 1) is True
    assert cart.raw(cart.party_count, 1) == b"\x01"
    assert cart.raw(cart.party_base, 100) == lead
    assert cart.raw(cart.party_base + 100, 100) == empty_party_record()
    size = 58 if rr else 80
    memorial = cart.raw(cart.box_addr(cart.boxes.memorial_box), size)
    assert memorial != bytes(size)
    decoded = codec.decode_box_mon(codec.expand_compressed_box_mon(memorial) if rr else memorial,
                                   rr=rr)
    assert decoded["personality"] == 50 and decoded["species"] == 1
    if not rr:
        assert decoded["pp"] == [42, 0, 0, 0]
        assert decoded["checksum_ok"] is True
    before = len(cart.written)
    assert cart.boxes.memorialize(cart.boxes, key, 1) is True
    assert len(cart.written) == before


def test_memorialize_moves_an_already_boxed_mon_without_touching_party():
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    cart.seed_move_pp()
    key = cart.key(target)
    assert cart.boxes.deposit(cart.boxes, key, 1) is True
    boxed = cart.raw(cart.box_addr(0), 80)
    assert cart.boxes.memorialize(cart.boxes, key, None) is True
    assert cart.raw(cart.box_addr(0), 80) == bytes(80)
    assert cart.raw(cart.box_addr(cart.boxes.memorial_box), 80) == boxed
    assert cart.raw(cart.party_base, 100) == lead
    assert cart.raw(cart.party_count, 1) == b"\x01"


def test_rr_box_to_memorial_preserves_the_compressed_record():
    cart = Cart("radical_red")
    lead, target = mon_bytes(75, rr=True), mon_bytes(50, rr=True)
    cart.put_party([lead, target])
    key = cart.key(target)
    assert cart.boxes.deposit(cart.boxes, key, 1) is True
    compressed = cart.raw(cart.box_addr(0), 58)
    assert cart.boxes.memorialize(cart.boxes, key, None) is True
    assert cart.raw(cart.box_addr(0), 58) == bytes(58)
    assert cart.raw(cart.box_addr(cart.boxes.memorial_box), 58) == compressed


def test_rr_native_executor_is_an_optional_injected_seam():
    cart = Cart("radical_red")
    calls = []
    native = cart.lua.table(
        deposit=lambda key, hint: calls.append(("deposit", key, hint)) or True,
        withdraw=lambda key, stats, nickname: calls.append(("withdraw", key, nickname)) or True,
        memorialize=lambda key, hint: calls.append(("memorialize", key, hint)) or True,
    )
    boxes_mod = cart.lua.execute((LUA / "boxes.lua").read_text(encoding="utf-8"))
    boxes = boxes_mod.new(cart.p, cart.reads, cart.lua.table(
        read_bytes=cart.io.read_bytes, rom_read=cart.io.rom_read,
        writes=cart.writes, native_executor=native,
    ))
    assert boxes.deposit(boxes, "one", 2) is True
    assert boxes.withdraw(boxes, "two", None, "name") is True
    assert boxes.memorialize(boxes, "three", 4) is True
    assert calls == [("deposit", "one", 2), ("withdraw", "two", "name"),
                     ("memorialize", "three", 4)]
    assert cart.written == []


@pytest.mark.parametrize("title", ["firered", "radical_red"])
def test_scan_reports_the_keyed_box_record_with_level_and_moves(title):
    cart = Cart(title)
    rr = title == "radical_red"
    if rr:
        cart.seed_rr_stats()
    else:
        cart.seed_vanilla_stats()
        cart.seed_move_pp()
    lead, target = mon_bytes(75, rr=rr), mon_bytes(50, rr=rr)
    cart.put_party([lead, target])
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    rows = list(cart.boxes.scan(cart.boxes).values())
    assert len(rows) == 1
    row = rows[0]
    assert (row.box, row.slot, row.key, row.species_id, row.level) == (
        0, 0, cart.key(target), 1, 5
    )
    assert row.moves[1] == 33
    assert str(row.nickname) == codec.decode_party_mon(target, rr=rr)["nickname"]


def test_duplicate_party_or_box_key_refuses_without_mutation():
    cart = Cart()
    repeated = mon_bytes(50)
    cart.put_party([repeated, repeated])
    ok, why = cart.boxes.deposit(cart.boxes, cart.key(repeated), None)
    assert (ok, why) == (None, "ambiguous duplicate key")
    assert cart.written == []

    cart = Cart()
    cart.put_party([mon_bytes(75)])
    raw = repeated[:80]
    cart.poke(cart.box_addr(0, 0), raw)
    cart.poke(cart.box_addr(0, 1), raw)
    ok, why = cart.boxes.withdraw(cart.boxes, cart.key(repeated), None, None)
    assert (ok, why) == (None, "ambiguous duplicate boxed key")
    assert cart.written == []


def test_full_party_and_last_party_memorial_have_exact_retry_reasons():
    cart = Cart()
    one = mon_bytes(50)
    cart.put_party([one])
    ok, why = cart.boxes.memorialize(cart.boxes, cart.key(one), 0)
    assert (ok, why) == (None, "last party mon")
    assert cart.written == []

    cart = Cart()
    mons = [mon_bytes(25 * (i + 1)) for i in range(6)]
    cart.put_party(mons)
    other = mon_bytes(200)
    cart.poke(cart.box_addr(0), other[:80])
    ok, why = cart.boxes.withdraw(cart.boxes, cart.key(other), None, None)
    assert (ok, why) == (None, "party full")
    assert cart.written == []


def test_boxes_cannot_use_an_armed_window_to_write_outside_its_ranges():
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    cart.seed_move_pp()
    rogue = cart.lua.eval("""function(real)
        return {
            arm=function(_, reason, allow) real:arm(reason, allow) end,
            write_bytes=function(_, _, bytes) real:write_bytes(0x01000000, bytes) end,
            disarm=function(_) real:disarm() end,
        }
    end""")(cart.writes)
    boxes_mod = cart.lua.execute((LUA / "boxes.lua").read_text(encoding="utf-8"))
    bad_boxes = boxes_mod.new(cart.p, cart.reads, cart.lua.table(
        read_bytes=cart.io.read_bytes, rom_read=cart.io.rom_read, writes=rogue
    ))
    with pytest.raises(lupa.LuaError, match="outside allow range"):
        bad_boxes.deposit(bad_boxes, cart.key(target), 1)
    assert cart.written == []
    assert len(cart.writes.log) == 0


def test_current_and_memorial_box_full_have_their_own_reasons():
    filler = mon_bytes(999)[:80]
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    for box in range(cart.boxes.memorial_box):
        for slot in range(30):
            cart.poke(cart.box_addr(box, slot), filler)
    ok, why = cart.boxes.deposit(cart.boxes, cart.key(target), 1)
    assert (ok, why) == (None, "current box full")
    assert cart.written == []

    cart = Cart()
    cart.put_party([lead, target])
    for slot in range(30):
        cart.poke(cart.box_addr(cart.boxes.memorial_box, slot), filler)
    ok, why = cart.boxes.memorialize(cart.boxes, cart.key(target), 1)
    assert (ok, why) == (None, "memorial box full")
    assert cart.written == []


def test_duplicate_key_in_party_and_box_is_not_guessed_away():
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    cart.poke(cart.box_addr(0), target[:80])
    ok, why = cart.boxes.deposit(cart.boxes, cart.key(target), 1)
    assert (ok, why) == (None, "ambiguous key exists in both party and box")
    assert cart.written == []


def test_deposit_uses_decrypted_species_not_only_has_species_flag_for_free_slot():
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    cart.seed_move_pp()
    occupied = bytearray(mon_bytes(999)[:80])
    occupied[0x13] &= ~2  # inconsistent header; secure species is still 1
    cart.poke(cart.box_addr(0, 0), occupied)
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    assert cart.raw(cart.box_addr(0, 0), 80) == occupied
    assert codec.decode_box_mon(cart.raw(cart.box_addr(0, 1), 80))["species"] == 1


def test_relocated_storage_pointer_outside_the_pack_window_refuses_before_write():
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    cart.poke(cart.profile["ram"]["PSP_PTR_ADDR"], (cart.storage + 128).to_bytes(4, "little"))
    ok, why = cart.boxes.deposit(cart.boxes, cart.key(target), 1)
    assert ok is None and "relocation window" in why
    assert cart.written == []


def test_pointer_move_after_arm_refuses_the_first_box_write():
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    cart.seed_move_pp()
    pointer = cart.profile["ram"]["PSP_PTR_ADDR"]

    def ptr():
        return int.from_bytes(cart.raw(pointer, 4), "little")

    def check(_, snapshot, reason, args=None):  # writes.lua passes the arm args through (C4-B2)
        return ptr() == snapshot.ptr, "storage pointer moved"

    writes_mod = cart.lua.execute((LUA / "writes.lua").read_text(encoding="utf-8"))
    guarded = writes_mod.new(cart.lua.table(
        safety=cart.lua.table(snapshot=lambda *_: cart.lua.table(ptr=ptr()), check=check),
        frame=lambda: 7,
        io=cart.lua.table(write_u8=lambda a, v, *_: cart.written.append((int(a), int(v))))
    ))

    def relocate():
        cart.poke(pointer, (cart.storage + 4).to_bytes(4, "little"))

    moving = cart.lua.eval("""function(real, move)
        return {
            arm=function(_, reason, allow) real:arm(reason, allow); move() end,
            write_bytes=function(_, addr, bytes) real:write_bytes(addr, bytes) end,
            disarm=function(_) real:disarm() end,
        }
    end""")(guarded, relocate)
    boxes_mod = cart.lua.execute((LUA / "boxes.lua").read_text(encoding="utf-8"))
    boxes = boxes_mod.new(cart.p, cart.reads, cart.lua.table(
        read_bytes=cart.io.read_bytes, rom_read=cart.io.rom_read, writes=moving
    ))
    with pytest.raises(lupa.LuaError, match="storage pointer moved"):
        boxes.deposit(boxes, cart.key(target), 1)
    assert cart.written == []
    assert len(guarded.log) == 0


def test_pointer_move_just_before_arm_cannot_bless_a_stale_box_plan():
    cart = Cart()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    cart.seed_move_pp()
    pointer = cart.profile["ram"]["PSP_PTR_ADDR"]

    def relocate():
        cart.poke(pointer, (cart.storage + 4).to_bytes(4, "little"))

    moving = cart.lua.eval("""function(real, move)
        return {
            arm=function(_, reason, allow) move(); real:arm(reason, allow) end,
            write_bytes=function(_, addr, bytes) real:write_bytes(addr, bytes) end,
            disarm=function(_) real:disarm() end,
        }
    end""")(cart.writes, relocate)
    boxes_mod = cart.lua.execute((LUA / "boxes.lua").read_text(encoding="utf-8"))
    boxes = boxes_mod.new(cart.p, cart.reads, cart.lua.table(
        read_bytes=cart.io.read_bytes, rom_read=cart.io.rom_read, writes=moving
    ))
    with pytest.raises(lupa.LuaError, match="storage pointer moved before box write"):
        boxes.deposit(boxes, cart.key(target), 1)
    assert cart.written == []
    assert len(cart.writes.log) == 0


def test_vanilla_roundtrip_projects_to_a_qualifying_synthetic_flash_save():
    cart = Cart()
    cart.seed_vanilla_stats()
    cart.seed_move_pp()
    lead, target = mon_bytes(75), mon_bytes(50)
    cart.put_party([lead, target])
    key = cart.key(target)
    assert cart.boxes.deposit(cart.boxes, key, 1) is True
    assert cart.boxes.withdraw(cart.boxes, key, None, None) is True
    assert cart.boxes.memorialize(cart.boxes, key, 1) is True

    sb1 = bytearray(codec.SAVEBLOCK1_SIZE)
    sb1[codec.SB1_PARTY_COUNT_OFFSET] = cart.raw(cart.party_count, 1)[0]
    sb1[codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + 600] = cart.raw(
        cart.party_base, 600
    )
    blocks = {"sb1": sb1, "sb2": bytes(codec.SAVEBLOCK2_SIZE),
              "storage": cart.raw(cart.storage, codec.STORAGE_SIZE)}
    image = bytearray(codec.FLASH_SIZE)
    layout = codec.slot_layout()
    for slot, counter in ((0, 2), (1, 1)):
        for entry in layout:
            section = blocks[entry["object"]][entry["offset"]:
                                                entry["offset"] + entry["size"]]
            sector = codec.write_sector(section, entry["id"], counter, layout)
            start = (slot * 14 + entry["id"]) * codec.SECTOR_SIZE
            image[start:start + codec.SECTOR_SIZE] = sector
    saved = bytes(image)
    assert codec.qualify_flash(saved) == (True, "ok")
    party = codec.party_from_save(saved)
    boxes = codec.boxes_from_save(saved)
    assert len(party) == 1 and party[0]["personality"] == 75
    assert boxes[cart.boxes.memorial_box][0]["personality"] == 50
    assert boxes[cart.boxes.memorial_box][0]["checksum_ok"] is True
    assert boxes[0][0]["has_species"] == 0


@pytest.mark.parametrize("species,hp", [(1, 177), (303, 1)])
def test_distinct_stats_nature_evs_ivs_all_pp_bonuses_and_shedinja(species, hp):
    cart = Cart()
    cart.seed_vanilla_stats()
    base = bytearray(28)
    base[:6] = bytes([70, 120, 65, 95, 110, 85])
    cart.seed_rom(cart.profile["rom"]["BASESTATS_ADDR"] + species * 28, base)
    cart.seed_rom(cart.profile["rom"]["EXPERIENCE_TABLES_ADDR"], b"".join(
        (n ** 3).to_bytes(4, "little") for n in range(101)))
    cart.seed_move_pp()
    for move, pp in ((45, 40), (85, 15), (153, 5)):
        cart.seed_rom(cart.profile["rom"]["BATTLE_MOVES_ADDR"] + move * 12 + 4, bytes([pp]))
    names = ("hp", "attack", "defense", "speed", "sp_attack", "sp_defense")
    target = changed_mon(mon_bytes(53), species=species, experience=125000,
                         moves=[33, 45, 85, 153], pp=[1, 2, 3, 4], pp_bonuses=0xE4,
                         ivs=dict(zip(names, [31, 7, 22, 19, 28, 3], strict=True)),
                         evs=dict(zip(names, [252, 80, 44, 156, 200, 12], strict=True)))
    cart.put_party([mon_bytes(75), target])
    key = cart.key(target)
    assert cart.boxes.deposit(cart.boxes, key, 1) is True
    assert cart.boxes.withdraw(cart.boxes, key, None, None) is True
    decoded = codec.decode_party_mon(cart.raw(cart.party_base + 100, 100))
    # Worked pret CalculateMonStats control: level50 Adamant (+Atk,-SpA).
    assert [decoded[k] for k in ("hp", "max_hp", "attack", "defense", "speed",
                                "sp_attack", "sp_defense")] == [hp, hp, 151, 86, 129, 138, 93]
    assert decoded["pp"] == [35, 48, 21, 8]
    assert decoded["checksum_ok"] is True and decoded["mail"] == 255


@pytest.mark.parametrize("title,maximum", [("firered", 100), ("radical_red", 250)])
def test_level_scan_stops_at_the_profile_cap(title, maximum):
    cart = Cart(title)
    rr = title == "radical_red"
    if rr:
        cart.seed_rr_stats()
    else:
        cart.seed_vanilla_stats()
        cart.seed_move_pp()
    count = cart.profile["derived"]["EXPERIENCE_TABLE_ENTRY_COUNT"]
    cart.seed_rom(cart.profile["rom"]["EXPERIENCE_TABLES_ADDR"], b"".join(
        n.to_bytes(4, "little") for n in range(count)))
    target = changed_mon(mon_bytes(50, rr=rr), rr=rr, experience=0xFFFFFFFF)
    cart.put_party([mon_bytes(75, rr=rr), target])
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    assert cart.boxes.scan(cart.boxes)[1].level == maximum


def test_rr_compression_keeps_growth_and_misc_bytes_and_expands_with_engine_flag():
    cart = Cart("radical_red")
    target = changed_mon(mon_bytes(50, rr=True), rr=True, experience=0x123456,
                         held_item=77, friendship=201, growth_filler=0xA5,
                         pokerus=0xD7, met_location=83, met_level=61, met_game=4,
                         pokeball=9, ot_gender=1, ability_num=1)
    cart.put_party([mon_bytes(75, rr=True), target])
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    compressed = cart.raw(cart.box_addr(0), 58)
    assert compressed[0x1C:0x27] == target[0x20:0x2B]
    assert compressed[0x32:0x3A] == target[0x44:0x4C]
    expanded = codec.expand_compressed_box_mon(compressed)
    assert expanded[0x4F] == 0x80
    assert expanded[0x44:0x4C] == target[0x44:0x4C]


@pytest.mark.parametrize("operation", ["deposit", "memorialize"])
def test_corrupt_zero_species_box_slot_is_occupied_and_never_overwritten(operation):
    cart = Cart()
    target = mon_bytes(50)
    cart.put_party([mon_bytes(75), target])
    cart.seed_move_pp()
    corrupt = bytearray(80)
    corrupt[0x1C] = 1
    box = 0 if operation == "deposit" else cart.boxes.memorial_box
    cart.poke(cart.box_addr(box), corrupt)
    assert getattr(cart.boxes, operation)(cart.boxes, cart.key(target), 1) is True
    assert cart.raw(cart.box_addr(box), 80) == corrupt
    assert codec.decode_box_mon(cart.raw(cart.box_addr(box, 1), 80))["personality"] == 50


@pytest.mark.parametrize("where", ["party", "box"])
def test_checksum_refusals_do_not_write(where):
    cart = Cart()
    target = bytearray(mon_bytes(50))
    target[0x1C] ^= 1
    if where == "party":
        cart.put_party([mon_bytes(75), bytes(target)])
        result = cart.boxes.deposit(cart.boxes, cart.key(bytes(target)), 1)
    else:
        cart.put_party([mon_bytes(75)])
        cart.poke(cart.box_addr(0), target[:80])
        result = cart.boxes.withdraw(cart.boxes, cart.key(bytes(target)), None, None)
    assert result == (None, where + " checksum invalid")
    assert cart.written == []


def test_missing_rom_pp_or_stats_returns_named_refusal_without_writes():
    cart = Cart()
    target = mon_bytes(50)
    cart.put_party([mon_bytes(75), target])
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) == (None, "PP unavailable")
    assert cart.written == []
    cart.put_party([mon_bytes(75)])
    cart.poke(cart.box_addr(0), target[:80])
    assert cart.boxes.withdraw(cart.boxes, cart.key(target), None, None) == (None, "stats unavailable")
    assert cart.written == []


def test_withdraw_reason_precedence_and_full_party_idempotence():
    cart = Cart()
    records = [mon_bytes(i * 25) for i in range(1, 7)]
    cart.put_party(records)
    assert cart.boxes.withdraw(cart.boxes, cart.key(records[0]), None, None) is True
    assert cart.boxes.withdraw(cart.boxes, "missing", None, None) == (None, "party full")
    cart.put_party(records[:1])
    assert cart.boxes.withdraw(cart.boxes, "missing", None, None) == (None, "key not boxed")
    assert cart.written == []


def test_allow_covers_only_planned_slots_and_one_count_byte():
    cart = Cart()
    target = mon_bytes(50)
    cart.put_party([mon_bytes(75), target])
    cart.seed_move_pp()
    arm = cart.writes.arm
    checked = []

    def checking_arm(self, reason, allow):
        assert allow(cart.party_base + 100, 100) is True
        assert allow(cart.box_addr(0), 80) is True
        assert allow(cart.party_count, 1) is True
        for addr, size in ((cart.party_base, 1), (cart.party_base + 200, 1),
                           (cart.box_addr(1), 1), (cart.party_count, 2), (cart.party_count + 1, 1)):
            assert allow(addr, size) is False
        checked.append(True)
        return arm(self, reason, allow)

    cart.writes.arm = checking_arm
    assert cart.boxes.deposit(cart.boxes, cart.key(target), 1) is True
    assert checked == [True]


def test_write_error_always_disarms_the_window():
    cart = Cart()
    target = mon_bytes(50)
    cart.put_party([mon_bytes(75), target])
    cart.seed_move_pp()
    actual = cart.writes.write_bytes

    def fail(*_):
        raise RuntimeError("injected write refusal")

    cart.writes.write_bytes = fail
    with pytest.raises((lupa.LuaError, RuntimeError), match="injected write refusal"):
        cart.boxes.deposit(cart.boxes, cart.key(target), 1)
    with pytest.raises(lupa.LuaError, match="no armed write window"):
        actual(cart.writes, cart.party_count, cart.lua.table(2))


def test_rr_binary_expander_refills_all_pp_slots_and_sets_the_ribbon_flag():
    path = ROOT / "patch/build/slink_RR.gba"
    if not path.exists():
        pytest.skip("local copyrighted RR ROM absent")
    rom = path.read_bytes()
    # CreateBoxMonFromCompressedMon: read ppBonuses, call CalculatePPWithBonus,
    # store +0x34+i, increment i and loop until four. The word is Thumb callable.
    assert rom[0x10B69D0:0x10B69E4].hex() == "074b317800f050fc2b0001353433e054042df0d1"
    assert int.from_bytes(rom[0x10B69F0:0x10B69F4], "little") == 0x0804101D
    assert rom[0x10B696A:0x10B6978].hex() == "220080234632517a5b420b435372"
