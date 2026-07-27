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
    lua.execute("cartram = {}; sysbus = {}; print = function() end")
    lua.execute(f"sysbus[{CURRENT_BOX_NUM}] = {CHANGED_BIT if changed_boxes_set else 0}")
    lua.execute("""
        local function pick(domain)
            if domain == "CartRAM" then return cartram else return sysbus end
        end
        memory = {
            getmemorydomainlist = function() return {"System Bus", "CartRAM"} end,
            read_u8  = function(a, d) return pick(d)[a] or 0 end,
            write_u8 = function(a, v, d) pick(d)[a] = v % 256 end,
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
        }),
    }) if generation == 1 else lua.table_from({})
    M.profile = profile
    M.GENERATION = generation
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
    assert M.protectSramBoxes() is False
    M.refreshSramBoxChecksums(True)
    assert len(dict(cartram(lua))) == 0, "touched CartRAM for a profile with no sram_box_layout"


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
    assert byte(base + CK_OFFSET) == all_boxes, "sBank{}AllBoxesChecksum wrong".format(bank)

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
