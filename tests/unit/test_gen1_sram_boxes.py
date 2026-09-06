"""The Gen 1 SRAM box-bank guard, executed as real Lua against a simulated CartRAM.

WHY THIS EXISTS. pokered's `ChangeBox` opens with

    bit BIT_HAS_CHANGED_BOXES, [hl]   ; hl = wCurrentBoxNum, bit 7
    call z, EmptyAllSRAMBoxes         ; if so, empty ALL boxes in SRAM

(`engine/menus/save.asm:366`; identical at pokeyellow:351 and Alchav's AP fork:354). The
first time a player ever picks "CHANGE BOX", the game marks every SRAM box empty as a
one-time init — **including box 12, which is where SLink buries memorialised mons**. A run
that memorialised before the player first opened the box menu would silently lose every
buried pair, and nothing in the unit suite or the live gates would have noticed.

`M.protectSramBoxes()` performs that init itself and then sets the bit, so the game's wipe
can never fire. These tests drive the REAL `lua/memory_gb.lua` under lupa with a fake
`memory` table, because the bug class here is behavioural, not structural — a Python
reimplementation of the logic would prove nothing about the shipped Lua.
"""
import os

import pytest

lupa = pytest.importorskip("lupa")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BOX_LEN = 1122           # wBoxDataEnd - wBoxDataStart
PER_BANK = 6
BANK_SIZE = 0x2000
CK_OFFSET = 0x1A4C       # sBank2AllBoxesChecksum - (bank base)
BOX12 = 0x75EA           # bank 3, slot 5
CURRENT_BOX_NUM = 0xD5A0
CHANGED_BIT = 0x80


def make_runtime(*, changed_boxes_set: bool, generation: int = 1):
    """Load the real memory_gb.lua with a fake BizHawk `memory` API.

    CartRAM and System Bus are separate dicts, exactly as the real domains are separate —
    conflating them would let a System Bus write silently satisfy a CartRAM assertion.
    """
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("cartram = {}; sysbus = {}; writes = {}; print = function() end")
    lua.execute(f"sysbus[{CURRENT_BOX_NUM}] = {CHANGED_BIT if changed_boxes_set else 0}")
    lua.execute("""
        local function pick(domain)
            if domain == "CartRAM" then return cartram else return sysbus end
        end
        memory = {
            getmemorydomainlist = function() return {"System Bus", "CartRAM"} end,
            read_u8  = function(a, d) return pick(d)[a] or 0 end,
            write_u8 = function(a, v, d) writes[#writes+1] = {a=a,v=v,d=d}; pick(d)[a] = v % 256 end,
            read_u16_le = function(a, d) local t = pick(d)
                                         return (t[a] or 0) + (t[a+1] or 0) * 256 end,
            write_u16_le = function(a, v, d) local t = pick(d)
                                             t[a] = v % 256; t[a+1] = math.floor(v/256) % 256 end,
        }
    """)
    path = os.path.join(REPO, "lua", "memory_gb.lua").replace("\\", "/")
    M = lua.eval(f'dofile("{path}")')

    profile = lua.table_from({
        "sram_box_layout": lua.table_from({
            "box_len": BOX_LEN, "boxes_per_bank": PER_BANK,
            "banks": lua.table_from([2, 3]),
            "checksum_offset": CK_OFFSET,
            "changed_boxes_addr": CURRENT_BOX_NUM, "changed_boxes_bit": CHANGED_BIT,
            "main_save_start": 0x2598, "main_save_len": 3979,
            "main_checksum_offset": 0x3523, "saved_box_flag_offset": 0x284C,
            "player_id_addr": 0xD359, "saved_player_id_offset": 0x2605,
        }),
    }) if generation == 1 else lua.table_from({})
    M.profile = profile
    M.GENERATION = generation
    saved_flag = CHANGED_BIT if changed_boxes_set else 0
    lua.execute(f"""sysbus[0xD359] = 0x12; sysbus[0xD35A] = 0x34
        cartram[0x2605] = 0x12; cartram[0x2606] = 0x34
        cartram[0x2598] = 0x80
        cartram[0x284C] = {saved_flag}; cartram[0x3523] = {(255 - saved_flag - 0xC6) % 256}
    """)
    return lua, M


def cartram(lua):
    return lua.globals().cartram


def box_offset(box_1indexed: int) -> int:
    bank = 2 if box_1indexed <= PER_BANK else 3
    idx = (box_1indexed - 1) % PER_BANK
    return bank * BANK_SIZE + idx * BOX_LEN


def test_box12_offset_matches_pret():
    """The memorial offset the client uses really is sBox12.

    sBox12 = 0xB5EA (data/pret_syms.json) → CartRAM 3*0x2000 + (0xB5EA-0xA000) = 0x75EA.
    """
    assert box_offset(12) == BOX12


def test_protect_marks_every_box_empty_and_sets_the_bit():
    lua, M = make_runtime(changed_boxes_set=False)
    assert M.protectSramBoxes() is True

    ram = cartram(lua)
    for box in range(1, 13):
        off = box_offset(box)
        assert ram[off] == 0, f"box {box} count not zeroed"
        assert ram[off + 1] == 0xFF, f"box {box} missing 0xFF terminator"

    flag = lua.eval(f"sysbus[{CURRENT_BOX_NUM}]")
    assert flag & CHANGED_BIT, "BIT_HAS_CHANGED_BOXES not set — the game would still wipe"
    assert flag & 0x7F == 0, "the active box index must not be disturbed"


def test_protect_is_idempotent():
    """The second memorial must NOT re-run the wipe, or it erases the first one.

    This is the assertion that would fail if someone 'simplified' the guard by dropping the
    bit check — and it is the exact failure the whole fix exists to prevent.
    """
    lua, M = make_runtime(changed_boxes_set=False)
    M.protectSramBoxes()

    # Simulate a memorialised mon sitting in box 12.
    lua.execute(f"cartram[{BOX12}] = 1; cartram[{BOX12 + 1}] = 0x99")

    assert M.protectSramBoxes() is False, "second call must be a no-op"
    ram = cartram(lua)
    assert ram[BOX12] == 1, "the buried mon's count was wiped by a repeat init"
    assert ram[BOX12 + 1] == 0x99, "the buried mon's species was wiped by a repeat init"


def test_protect_skips_when_player_already_changed_boxes():
    """Bit already set means the game ran its own init and may hold real player mons."""
    lua, M = make_runtime(changed_boxes_set=True)
    lua.execute(f"cartram[{box_offset(3)}] = 7")      # player has 7 mons in box 3
    assert M.protectSramBoxes() is False
    assert cartram(lua)[box_offset(3)] == 7, "clobbered the player's own box"


def test_no_op_without_the_profile_key():
    """Gen 2 shares memory_gb.lua and has a different SRAM layout — it must not run any of this."""
    lua, M = make_runtime(changed_boxes_set=False, generation=2)
    before = dict(cartram(lua))
    assert M.protectSramBoxes() is False
    M.refreshSramBoxChecksums(True)
    assert dict(cartram(lua)) == before, "touched CartRAM for a profile with no sram_box_layout"


def _calc_checksum(data) -> int:
    """pokered CalcCheckSum (save.asm:297): complement of the 8-bit running sum."""
    d = 0
    for b in data:
        d = (d + b) & 0xFF
    return (~d) & 0xFF


@pytest.mark.parametrize("bank", [2, 3])
def test_checksums_match_pokereds_algorithm(bank):
    lua, M = make_runtime(changed_boxes_set=False)
    M.protectSramBoxes()
    # Scatter some content so a checksum of all-zeros can't accidentally pass.
    lua.execute(f"""
        for i = 0, 200 do cartram[{bank * BANK_SIZE} + i * 7] = (i * 13) % 256 end
    """)
    M.refreshSramBoxChecksums(True)

    ram = cartram(lua)
    base = bank * BANK_SIZE

    def byte(off):
        return ram[off] or 0

    all_boxes = _calc_checksum(byte(base + i) for i in range(PER_BANK * BOX_LEN))
    assert byte(base + CK_OFFSET) == all_boxes, f"sBank{bank}AllBoxesChecksum wrong"

    for i in range(PER_BANK):
        expect = _calc_checksum(byte(base + i * BOX_LEN + j) for j in range(BOX_LEN))
        assert byte(base + CK_OFFSET + 1 + i) == expect, f"individual checksum {i} wrong"


def test_all_five_variants_declare_the_layout():
    """red, blue, yellow, red_ap, blue_ap must every one carry sram_box_layout.

    blue aliases red and blue_ap inherits red_ap through a metatable, so this also guards
    against someone breaking that inheritance.
    """
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("print = function() end")
    path = os.path.join(REPO, "lua", "games", "gen1_rby.lua").replace("\\", "/")
    G = lua.eval(f'dofile("{path}")')
    for variant in ("red", "blue", "yellow", "red_ap", "blue_ap"):
        prof = G.PROFILES[variant]
        layout = prof.sram_box_layout
        assert layout is not None, f"{variant} has no sram_box_layout"
        assert layout.changed_boxes_addr == prof.CURRENT_BOX_NUM_ADDR, (
            f"{variant}: the guard must use that variant's own wCurrentBoxNum "
            f"({layout.changed_boxes_addr:#x} != {prof.CURRENT_BOX_NUM_ADDR:#x})")


def test_initialized_flag_and_main_checksum_survive_reset_reload():
    lua, M = make_runtime(changed_boxes_set=False)
    # The last saved box is 3 while the live box is 5; do not rewrite save identity.
    lua.execute(f"sysbus[{CURRENT_BOX_NUM}] = 5; cartram[0x284C] = 3; cartram[0x3523] = 54")
    assert M.protectSramBoxes() is True
    ram = cartram(lua)
    assert ram[0x284C] == 0x83
    assert ram[0x3523] == _calc_checksum((ram[a] or 0) for a in range(0x2598, 0x3523))
    lua.execute(f"cartram[{BOX12}] = 1; cartram[{BOX12 + 1}] = 0x99")
    # Reset loads the flag from main save. The first-ChangeBox wipe must stay disabled.
    lua.execute(f"sysbus[{CURRENT_BOX_NUM}] = cartram[0x284C]")
    assert M.protectSramBoxes() is False
    assert ram[BOX12] == 1


@pytest.mark.parametrize("mode", ["invalid_live", "invalid_saved", "bad_checksum", "state_conflict", "wrong_player", "no_player"])
def test_bad_save_evidence_never_mutates_memory(mode):
    lua, M = make_runtime(changed_boxes_set=False)
    if mode == "invalid_live":
        lua.execute(f"sysbus[{CURRENT_BOX_NUM}] = 12")
    elif mode == "invalid_saved":
        lua.execute("cartram[0x284C] = 12; cartram[0x3523] = 45")
    elif mode == "bad_checksum":
        lua.execute("cartram[0x3523] = 0")
    elif mode == "state_conflict":
        lua.execute("cartram[0x284C] = 128; cartram[0x3523] = 185")
    elif mode == "wrong_player":
        lua.execute("cartram[0x2605] = 0x56; cartram[0x2606] = 0x78; cartram[0x3523] = 177")
    else:
        lua.execute("sysbus[0xD359] = 0; sysbus[0xD35A] = 0")
    before = dict(lua.globals().sysbus), dict(cartram(lua))
    assert M.protectSramBoxes()[0] is False
    assert (dict(lua.globals().sysbus), dict(cartram(lua))) == before


def test_matching_zero_player_id_is_valid_with_saved_name_and_checksum():
    lua, M = make_runtime(changed_boxes_set=False)
    lua.execute("sysbus[0xD359] = 0; sysbus[0xD35A] = 0; cartram[0x2605] = 0; cartram[0x2606] = 0")
    ram = cartram(lua)
    ram[0x3523] = _calc_checksum((ram[a] or 0) for a in range(0x2598, 0x3523))
    assert M.protectSramBoxes() is True


def test_valid_checksum_without_saved_name_is_not_a_save():
    lua, M = make_runtime(changed_boxes_set=False)
    ram = cartram(lua)
    ram[0x2598] = 0
    ram[0x3523] = _calc_checksum((ram[a] or 0) for a in range(0x2598, 0x3523))
    before = dict(lua.globals().sysbus), dict(ram)
    result = M.protectSramBoxes()
    assert result[0] is False and "saved player name" in result[1]
    assert (dict(lua.globals().sysbus), dict(ram)) == before


def _memorial_runtime(changed_boxes_set=False):
    lua, M = make_runtime(changed_boxes_set=changed_boxes_set)
    gamepath = os.path.join(REPO, "lua/games/gen1_rby.lua").replace("\\", "/")
    game = lua.eval(f'dofile("{gamepath}")')
    M.initProfile(game, "red")
    lua.execute(f"""sysbus[{int(M.PARTY_COUNT_ADDR)}] = 2
        sysbus[{int(M.PARTY_BASE_ADDR)}] = 0x99
        sysbus[{int(M.PARTY_BASE_ADDR) + 44}] = 0xB1
        sysbus[{int(M.PARTY_BASE_ADDR) + 33}] = 5
        sysbus[{int(M.PARTY_BASE_ADDR) + 44 + 33}] = 5
        sysbus[{int(M.PARTY_SPECIES_ADDR)}] = 0x99
        sysbus[{int(M.PARTY_SPECIES_ADDR) + 1}] = 0xB1
        sysbus[{int(M.PARTY_SPECIES_ADDR) + 2}] = 255
        sysbus[{int(M.BOX_SPECIES_ADDR)}] = 255
        cartram[{BOX12 + 1}] = 255
    """)
    return lua, M


@pytest.mark.parametrize("mode", ["last_mon", "invalid_slot", "full", "invalid_count", "active_memorial", "hidden_live_mon", "unreserved_nonempty"])
def test_memorial_refusal_does_not_initialize_or_mutate(mode):
    lua, M = _memorial_runtime(changed_boxes_set=mode not in {"last_mon", "invalid_slot"})
    slot = 0
    if mode == "last_mon":
        lua.execute(f"sysbus[{int(M.PARTY_COUNT_ADDR)}] = 1")
    elif mode == "invalid_slot":
        slot = 9
    elif mode == "full":
        lua.execute(f"cartram[{BOX12}] = 20")
    elif mode == "invalid_count":
        lua.execute(f"cartram[{BOX12}] = 21")
    elif mode == "active_memorial":
        lua.execute(f"sysbus[{CURRENT_BOX_NUM}] = 139")
    elif mode == "unreserved_nonempty":
        lua.execute(f"cartram[{BOX12}] = 1")
    else:
        # Count says empty, but the final structure is a live Pokemon.
        base = BOX12 + 22 + 19 * 33
        lua.execute(f"cartram[{base}] = 0x99; cartram[{base + 2}] = 10")
    before = dict(lua.globals().sysbus), dict(cartram(lua))
    assert M.depositMemorialMon(slot)[0] is False
    assert (dict(lua.globals().sysbus), dict(cartram(lua))) == before


def test_first_memorial_persists_init_before_grave_data_and_reserves_empty_box():
    lua, M = _memorial_runtime()
    lua.execute("writes = {}")
    assert M.depositMemorialMon(0) is True
    writes = list(lua.globals().writes.values())
    save_checksum = next(i for i, w in enumerate(writes) if w.a == 0x3523 and w.d == "CartRAM")
    grave = next(i for i, w in enumerate(writes) if w.a == BOX12 + 22 and w.d == "CartRAM")
    assert save_checksum < grave
    assert cartram(lua)[BOX12] == 1
    assert cartram(lua)[0x284C] == 128


def test_memorial_also_saves_an_earlier_unsaved_ordinary_deposit():
    lua, M = _memorial_runtime()
    bus, cart = lua.globals().sysbus, cartram(lua)
    bus[int(M.PARTY_COUNT_ADDR)] = 3
    bus[int(M.PARTY_BASE_ADDR) + 88] = 0xA5
    bus[int(M.PARTY_BASE_ADDR) + 88 + 33] = 5
    bus[int(M.PARTY_SPECIES_ADDR) + 2], bus[int(M.PARTY_SPECIES_ADDR) + 3] = 0xA5, 255
    bus[int(M.BOX_SPECIES_ADDR)] = 255
    # Establish a canonical-shaped saved A/B/C plus empty current box.
    ranges = list(M.profile.sram_box_layout.save_party_dex_ranges.values())
    for item in ranges:
        for i in range(int(item.len)):
            cart[int(item.dst) + i] = bus[int(item.src) + i] or 0
    cart[0x3523] = _calc_checksum((cart[a] or 0) for a in range(0x2598, 0x3523))
    assert M.depositPartyMon(0) is True  # A now exists only in the dirty WRAM box.
    assert M.depositMemorialMon(1) is True  # C removed, B remains.
    saved_box = int(ranges[0].dst)
    saved_party = int(ranges[1].dst)
    assert cart[saved_box] == 1 and cart[saved_box + 1] == 0x99
    assert cart[saved_party] == 1 and cart[saved_party + 1] == 0xB1
    assert cart[BOX12] == 1 and cart[BOX12 + 1] == 0xA5
    assert cart[0x3523] == _calc_checksum((cart[a] or 0) for a in range(0x2598, 0x3523))


@pytest.mark.parametrize("offset", [2, 27])
def test_memorial_revalidates_contents_even_after_a_cached_reservation(offset):
    lua, M = _memorial_runtime()
    assert M.depositMemorialMon(0) is True
    # Prepare another dead slot, then inject a live mon into the reserved box.
    bus, cart = lua.globals().sysbus, cartram(lua)
    bus[int(M.PARTY_COUNT_ADDR)] = 2
    bus[int(M.PARTY_BASE_ADDR) + 44] = 0x99
    bus[int(M.PARTY_BASE_ADDR) + 44 + 33] = 5
    bus[int(M.PARTY_SPECIES_ADDR) + 1], bus[int(M.PARTY_SPECIES_ADDR) + 2] = 0x99, 255
    cart[BOX12 + 22 + offset] = 1
    before = dict(bus), dict(cart)
    assert M.depositMemorialMon(1)[0] is False
    assert (dict(bus), dict(cart)) == before


def test_memorial_refreshes_box_level_from_party_level():
    lua, M = _memorial_runtime()
    bus = lua.globals().sysbus
    bus[int(M.PARTY_BASE_ADDR) + int(M.BOX_LEVEL_OFFSET)] = 2
    bus[int(M.PARTY_BASE_ADDR) + int(M.LEVEL_OFFSET)] = 17
    assert M.depositMemorialMon(0) is True
    assert cartram(lua)[BOX12 + 22 + int(M.BOX_LEVEL_OFFSET)] == 17


@pytest.mark.parametrize("level", [0, 101])
def test_memorial_refuses_invalid_level_before_any_write(level):
    lua, M = _memorial_runtime()
    lua.globals().sysbus[int(M.PARTY_BASE_ADDR) + int(M.LEVEL_OFFSET)] = level
    before = dict(lua.globals().sysbus), dict(cartram(lua))
    assert M.depositMemorialMon(0)[0] is False
    assert (dict(lua.globals().sysbus), dict(cartram(lua))) == before


def test_verified_memorial_fingerprint_is_updated_after_each_success():
    lua, M = _memorial_runtime()
    bus = lua.globals().sysbus
    bus[int(M.PARTY_COUNT_ADDR)] = 3
    bus[int(M.PARTY_BASE_ADDR) + 88] = 0xA5
    bus[int(M.PARTY_BASE_ADDR) + 88 + 33] = 5
    bus[int(M.PARTY_SPECIES_ADDR) + 2], bus[int(M.PARTY_SPECIES_ADDR) + 3] = 0xA5, 255
    assert M.depositMemorialMon(0) is True
    fingerprint_summary = lua.eval("function(m) for _,v in pairs(m._memorial_reservations) do return #v, string.byte(v,1) end end")
    first = fingerprint_summary(M)
    assert first == (1122, 1)
    assert M.depositMemorialMon(1) is True
    assert cartram(lua)[BOX12] == 2
    assert fingerprint_summary(M) == (1122, 2)
