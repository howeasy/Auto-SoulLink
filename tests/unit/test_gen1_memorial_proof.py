"""An ACK requires the exact dead key in memorial storage, never mere absence."""
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
KEY = "AABB:1234:99"


def runtime(variant="red"):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""bus = {}; cart = {}; writes = 0; print = function() end
        local function pick(d) return d == "CartRAM" and cart or bus end
        memory = {
            getmemorydomainlist = function() return {"System Bus", "CartRAM"} end,
            read_u8 = function(a,d) return pick(d)[a] or 0 end,
            write_u8 = function(a,v,d) writes = writes + 1; pick(d)[a] = v end,
            read_u16_le = function(a,d) return (pick(d)[a] or 0) + (pick(d)[a+1] or 0)*256 end,
            write_u16_le = function(a,v,d) writes = writes + 1; pick(d)[a] = v%256; pick(d)[a+1] = math.floor(v/256) end,
        }
    """)
    mem = lua.execute((ROOT / "lua/memory_gb.lua").read_text(encoding="utf-8"))
    game = lua.execute((ROOT / "lua/games/gen1_rby.lua").read_text(encoding="utf-8"))
    mem.initProfile(game, variant)
    bus, cart = lua.globals().bus, lua.globals().cart
    bus[int(mem.CURRENT_BOX_NUM_ADDR)] = 128
    bus[int(mem.PARTY_COUNT_ADDR)], bus[int(mem.PARTY_SPECIES_ADDR)] = 0, 255
    bus[int(mem.BOX_COUNT_ADDR)], bus[int(mem.BOX_SPECIES_ADDR)] = 0, 255
    for bank in (2, 3):
        for slot in range(6):
            cart[bank * 8192 + slot * 1122] = 0
            cart[bank * 8192 + slot * 1122 + 1] = 255
    bus[int(mem.PLAYER_ID_ADDR)], bus[int(mem.PLAYER_ID_ADDR) + 1] = 0x12, 0x34
    save_storage(lua, mem)
    return lua, mem


def checksum(lua, mem):
    cart, layout = lua.globals().cart, mem.profile.sram_box_layout
    start, length = int(layout.main_save_start), int(layout.main_save_len)
    cart[int(layout.main_checksum_offset)] = (255 - sum(cart[start + i] or 0 for i in range(length))) % 256


def save_storage(lua, mem):
    bus, cart, layout = lua.globals().bus, lua.globals().cart, mem.profile.sram_box_layout
    cart[int(layout.main_save_start)] = 0x80
    for i in (0, 1):
        cart[int(layout.saved_player_id_offset) + i] = bus[int(mem.PLAYER_ID_ADDR) + i] or 0
    cart[int(layout.saved_box_flag_offset)] = bus[int(mem.CURRENT_BOX_NUM_ADDR)] or 0
    for item in layout.save_party_dex_ranges.values():
        for i in range(int(item.len)):
            cart[int(item.dst) + i] = bus[int(item.src) + i] or 0
    checksum(lua, mem)


def saved_range(mem, source):
    return next(r for r in mem.profile.sram_box_layout.save_party_dex_ranges.values() if int(r.src) == int(source))


def mon(table, count_addr, species_addr, base, *, key=KEY, slot=0, stride=33, hp=0):
    dvs, otid, species = key.split(":")
    data = {0: int(species, 16), 1: hp // 256, 2: hp % 256, 12: int(otid[:2], 16),
            13: int(otid[2:], 16), 27: int(dvs[:2], 16), 28: int(dvs[2:], 16)}
    for offset in range(stride):
        table[base + slot * stride + offset] = data.get(offset, 0)
    table[count_addr] = slot + 1
    table[species_addr + slot] = int(species, 16)
    table[species_addr + slot + 1] = 255


def grave(lua, **kwargs):
    mon(lua.globals().cart, 0x75EA, 0x75EB, 0x7600, **kwargs)


def verify_readonly(lua, mem, key=KEY):
    before = dict(lua.globals().bus), dict(lua.globals().cart), lua.globals().writes
    result = mem.verifyMemorialKey(key)
    assert (dict(lua.globals().bus), dict(lua.globals().cart), lua.globals().writes) == before
    return result


@pytest.mark.parametrize("variant", ["red", "blue", "yellow", "red_ap", "blue_ap"])
def test_exact_unique_dead_grave_is_verified_without_writes(variant):
    lua, mem = runtime(variant)
    grave(lua)
    assert verify_readonly(lua, mem) is True


@pytest.mark.parametrize("defect", ["missing", "ordinary_box_only", "alive", "duplicate_grave",
    "bad_count", "bad_species", "bad_terminator", "party_collision", "current_box_collision",
    "inactive_box_collision", "uninitialized", "invalid_current", "wrong_key"])
def test_missing_or_ambiguous_grave_never_verifies(defect):
    lua, mem = runtime()
    bus, cart = lua.globals().bus, lua.globals().cart
    if defect not in {"missing", "ordinary_box_only"}:
        grave(lua)
    if defect in {"ordinary_box_only", "current_box_collision"}:
        mon(bus, int(mem.BOX_COUNT_ADDR), int(mem.BOX_SPECIES_ADDR), int(mem.BOX_BASE_ADDR))
    elif defect == "alive":
        cart[0x7602] = 1
    elif defect == "duplicate_grave":
        grave(lua, slot=1)
    elif defect == "bad_count":
        cart[0x75EA] = 21
    elif defect == "bad_species":
        cart[0x75EB] = 0xB1
    elif defect == "bad_terminator":
        cart[0x75EC] = 0
    elif defect == "party_collision":
        mon(bus, int(mem.PARTY_COUNT_ADDR), int(mem.PARTY_SPECIES_ADDR), int(mem.PARTY_BASE_ADDR), stride=44)
    elif defect == "inactive_box_collision":
        box = 0x4000 + 1122
        mon(cart, box, box + 1, box + 22)
    elif defect == "uninitialized":
        bus[int(mem.CURRENT_BOX_NUM_ADDR)] = 0
    elif defect == "invalid_current":
        bus[int(mem.CURRENT_BOX_NUM_ADDR)] = 140
    result = verify_readonly(lua, mem, "AABB:1234:B1" if defect == "wrong_key" else KEY)
    assert result[0] is False and result[1]


def test_active_memorial_is_read_from_wram_and_its_empty_sram_slot_is_ignored():
    lua, mem = runtime()
    bus, cart = lua.globals().bus, lua.globals().cart
    bus[int(mem.CURRENT_BOX_NUM_ADDR)] = 139
    mon(bus, int(mem.BOX_COUNT_ADDR), int(mem.BOX_SPECIES_ADDR), int(mem.BOX_BASE_ADDR))
    save_storage(lua, mem)
    cart[0x75EA] = 99  # Deliberately invalid stale bytes in the inactive SRAM slot.
    assert verify_readonly(lua, mem) is True


@pytest.mark.parametrize("defect,reason", [
    ("identity", "player identity"), ("checksum", "checksum"),
    ("saved_init_clear", "not persisted"), ("saved_index", "current box differs"),
    ("saved_party_key", "saved party still contains"),
    ("saved_box_key", "saved ordinary box duplicates"),
    ("active_not_saved", "active memorial key is not saved"),
])
def test_receipt_requires_a_durable_nonduplicated_saved_poststate(defect, reason):
    lua, mem = runtime()
    grave(lua)
    bus, cart, layout = lua.globals().bus, lua.globals().cart, mem.profile.sram_box_layout
    if defect == "identity":
        cart[int(layout.saved_player_id_offset) + 1] = 0x35
    elif defect == "saved_init_clear":
        cart[int(layout.saved_box_flag_offset)] = 0
    elif defect == "saved_index":
        cart[int(layout.saved_box_flag_offset)] = 129
    elif defect == "saved_party_key":
        item = saved_range(mem, mem.PARTY_COUNT_ADDR)
        mon(cart, int(item.dst), int(item.dst) + int(mem.PARTY_SPECIES_ADDR) - int(item.src),
            int(item.dst) + int(mem.PARTY_BASE_ADDR) - int(item.src), stride=44)
    elif defect == "saved_box_key":
        item = saved_range(mem, mem.BOX_COUNT_ADDR)
        mon(cart, int(item.dst), int(item.dst) + int(mem.BOX_SPECIES_ADDR) - int(item.src),
            int(item.dst) + int(mem.BOX_BASE_ADDR) - int(item.src))
    elif defect == "active_not_saved":
        bus[int(mem.CURRENT_BOX_NUM_ADDR)] = 139
        mon(bus, int(mem.BOX_COUNT_ADDR), int(mem.BOX_SPECIES_ADDR), int(mem.BOX_BASE_ADDR))
        cart[int(layout.saved_box_flag_offset)] = 139
    checksum(lua, mem)
    if defect == "checksum":
        address = int(layout.main_checksum_offset)
        cart[address] = (cart[address] + 1) % 256
    result = verify_readonly(lua, mem)
    assert result[0] is False and reason in result[1], result


def _client_memorial_handler(lua):
    """Execute the actual deferred handler with only its external effects stubbed."""
    source = (ROOT / "lua/clients/gen1_rby_client.lua").read_text(encoding="utf-8")
    start = source.index('        elseif cmd.cmd == "memorialize" then')
    end = source.index("        end)\n", start)
    handler = source[start:end].replace('elseif cmd.cmd == "memorialize" then', 'if cmd.cmd == "memorialize" then', 1)
    return lua.execute("""return function(M, cmd)
        local ok, err
        local sent, sync_written_keys = {}, {}
        local console = {log = function() end}
        local function send(message) sent[#sent+1] = message end
        local function hud_show() end
        local function nick_label(key) return key end
        local function keep_queued() return false end
        local fmt = string.format
    """ + handler + "\nreturn sent, sync_written_keys end")


@pytest.mark.parametrize("verified", [False, True])
def test_absent_party_client_ack_is_conditioned_on_actual_memorial_proof(verified):
    lua = LuaRuntime(unpack_returned_tuples=True)
    mem = lua.eval("""function(verified)
        return {getPartyCount=function() return 0 end,
            verifyMemorialKey=function(key)
                assert(key == 'AABB:1234:99')
                return verified, 'exact key not present in memorial'
            end}
    end""")(verified)
    sent, suppressed = _client_memorial_handler(lua)(mem, lua.table_from({"cmd": "memorialize", "key": KEY}))
    assert len(sent) == 1
    assert sent[1].event == ("memorialize_done" if verified else "memorialize_failed")
    assert suppressed[KEY] is (True if verified else None)
    if not verified:
        assert sent[1].reason == "exact key not present in memorial"


def test_successful_deposit_return_still_requires_physical_key_proof_before_ack():
    lua = LuaRuntime(unpack_returned_tuples=True)
    mem = lua.eval("""{
        getPartyCount=function() return 2 end,
        readPartySlot=function(slot) if slot==0 then return {key='AABB:1234:99'} end end,
        depositMemorialMon=function() return true end,
        verifyMemorialKey=function() return false, 'wrong physical poststate' end
    }""")
    sent, suppressed = _client_memorial_handler(lua)(mem, lua.table_from({"cmd": "memorialize", "key": KEY}))
    assert sent[1].event == "memorialize_failed"
    assert sent[1].reason == "wrong physical poststate"
    assert suppressed[KEY] is None


@pytest.mark.parametrize("generation", [1, 2])
@pytest.mark.parametrize("exact", [False, True])
def test_shared_duo_scenario_requires_the_exact_key_for_each_generation(generation, exact):
    lua = LuaRuntime(unpack_returned_tuples=True)
    run = lua.execute((ROOT / "lua/tests/duo/scenario_gb_memorialize.lua").read_text(encoding="utf-8"))
    context = lua.eval("""function(generation, exact)
        return {
            log=function() end, wait_go=function() return true end,
            slot_key=function() return 'AABB:1234:99' end, party_count=function() return 2 end,
            frames=function() end, write_hp=function() end, find_slot_by_key=function() return nil end,
            wait_until=function(predicate) return predicate() end, wait_partner_done=function() return true end,
            M={GENERATION=generation, getBoxCount=function() return 0 end,
                getMemorialBoxCount=function() return 1 end,
                verifyMemorialKey=function(key) return exact and key=='AABB:1234:99' end,
                readMemorialBoxSlot=function() return {key=exact and 'AABB:1234:99' or 'FFFF:1234:99'} end}
        }
    end""")(generation, exact)
    result = run(context)
    assert result[0] is exact
