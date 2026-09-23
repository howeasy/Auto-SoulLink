"""C3-29: adversarial FR story/recovery/PC oracles against byte-addressed fake RAM.

MODEL evidence only. The real driver, record decoder and playlib execute; the fake
engine supplies RAM/input transitions. No emulator, ROM, screenshots or writes to RAM
by the driver are involved.
"""
import itertools
import struct
from pathlib import Path

import pytest
from lupa import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "lua/tests/gen3_scripted_play.lua"

HARNESS = r"""
F = {ram={}, frame=0, taps=0, log={}, sb1=0x02025734, sb2=0x02024EA4,
     storage=0x02029314}
function F.r8(a) return F.ram[a] or 0 end
function F.w8(a,v) F.ram[a]=v & 255 end
function F.w16(a,v) F.w8(a,v); F.w8(a+1,v >> 8) end
function F.w32(a,v) F.w16(a,v); F.w16(a+2,v >> 16) end
memory = {
    read_u8=F.r8,
    read_u16_le=function(a) return F.r8(a) | F.r8(a+1)<<8 end,
    read_u32_le=function(a)
        return F.r8(a) | F.r8(a+1)<<8 | F.r8(a+2)<<16 | F.r8(a+3)<<24
    end,
    read_s16_le=function(a)
        local v=F.r8(a) | F.r8(a+1)<<8
        return v >= 0x8000 and v-0x10000 or v
    end,
}
function F.place(group,num,x,y)
    F.w8(F.sb1+4,group); F.w8(F.sb1+5,num)
    F.w16(F.sb1,x); F.w16(F.sb1+2,y)
end
function F.heal(group,num,x,y)
    F.w8(F.sb1+0x1C,group); F.w8(F.sb1+0x1D,num)
    F.w8(F.sb1+0x1E,255); F.w16(F.sb1+0x20,x); F.w16(F.sb1+0x22,y)
end
function F.flag(id,on)
    local a=F.sb1+0xEE0+(id//8)
    F.w8(a, on and (F.r8(a) | 1<<(id%8)) or (F.r8(a) & ~(1<<(id%8))))
end
F.w32(0x03005008,F.sb1); F.w32(0x0300500C,F.sb2)
F.w32(0x03005010,F.storage)
F.cp={pointers={gSaveBlock1Ptr={address=0x03005008}}}
F.heal(3,1,26,27); F.place(3,19,12,38)
G = {
    map=function() return F.r8(F.sb1+4),F.r8(F.sb1+5) end,
    pos=function() return memory.read_s16_le(F.sb1),memory.read_s16_le(F.sb1+2) end,
    phase=function(tag,msg) F.log[#F.log+1]=tag..' '..tostring(msg) end,
    finish=function(ok,msg) if not ok then error(msg,0) end end,
    shot=function() end, idle=function() end,
    tap=function() F.taps=F.taps+1; if F.on_tap then F.on_tap() end end,
    advance=function() F.frame=F.frame+1 end,
    pred_ok=function() return true end,
}
joypad={set=function() end}
local real_dofile=dofile
function dofile(path)
    if path:match('/gen3_boot_check.lua$') then return G end
    return real_dofile(path)
end
"""


@pytest.fixture
def machine():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_ROOT = ROOT.as_posix()
    lua.execute(HARNESS)
    mod = lua.execute(f'return dofile("{SCRIPT.as_posix()}")')
    lua.globals().D = mod
    return lua, mod, lua.globals().F


def test_run24_walker_accepts_viridian_whiteout(machine):
    """The run-24 failure was in handle_encounter, before recover() was called."""
    lua, _, _ = machine
    ok, signal = lua.execute("""
        D.play.mash_a=function() F.place(5,4,7,4); return true end
        D.play.wait_scene_settled=function() return true end
        return pcall(D.play.handle_encounter,F.cp,nil,'Down',{map=787,x=12,y=38})
    """)
    assert not ok
    assert not isinstance(signal, str), f"expected whiteout recovery signal, got {signal}"
    assert signal.whiteout is True
    assert signal.map == 1284


def put_mon(fake, addr, pid, species=7, otid=0x12345678):
    """Independent pret BoxPokemon fixture: physical permutations, XOR, u16 sum."""
    order = list(itertools.permutations("GAEM"))[pid % 24]
    plain = bytearray(48)
    struct.pack_into("<H", plain, order.index("G") * 12, species)
    raw = bytearray(100)
    struct.pack_into("<II", raw, 0, pid, otid)
    raw[0x13] = 2
    struct.pack_into("<H", raw, 0x1C, species)
    for off in range(0, 48, 4):
        word = struct.unpack_from("<I", plain, off)[0] ^ pid ^ otid
        struct.pack_into("<I", raw, 0x20 + off, word)
    for off, value in enumerate(raw):
        fake.w8(addr + off, value)


def init_party(fake):
    fake.w8(0x02024029, 3)
    for slot, pid in enumerate((24, 49, 74)):
        put_mon(fake, 0x02024284 + slot * 100, pid)


def depart(fake, slot=1, box=None):
    addr = 0x02024284 + slot * 100
    if box is not None:
        box_addr = fake.storage + 4 + box * 80
        for off in range(80):
            fake.w8(box_addr + off, fake.r8(addr + off))
    count = fake.r8(0x02024029)
    for off in range((count - slot - 1) * 100):
        fake.w8(addr + off, fake.r8(addr + 100 + off))
    fake.w8(0x02024029, count - 1)


def withdraw(fake, box=0, clear=True):
    count = fake.r8(0x02024029)
    addr, boxed = 0x02024284 + count * 100, fake.storage + 4 + box * 80
    for off in range(80):
        fake.w8(addr + off, fake.r8(boxed + off))
        if clear:
            fake.w8(boxed + off, 0)
    fake.w8(0x02024029, count + 1)


@pytest.mark.parametrize("pid", range(24))
def test_starter_decrypts_every_permutation(machine, pid):
    _, mod, fake = machine
    fake.w8(0x02024029, 1)
    put_mon(fake, 0x02024284, pid)
    mod.verify_starter()


@pytest.mark.parametrize("bad", ["wrong_species", "empty", "slot1_only", "checksum", "egg"])
def test_starter_rejects_wrong_slot_or_record(machine, bad):
    _, mod, fake = machine
    fake.w8(0x02024029, 1)
    put_mon(fake, 0x02024284, 24, species=1 if bad == "wrong_species" else 7)
    if bad == "empty":
        fake.w8(0x02024029, 0)
    elif bad == "slot1_only":
        fake.w8(0x02024029, 2)
        put_mon(fake, 0x02024284, 24, species=4)
        put_mon(fake, 0x02024284 + 100, 49)
    elif bad == "checksum":
        fake.w16(0x02024284 + 0x1C, 123)
    elif bad == "egg":
        fake.w8(0x02024284 + 0x13, 3)
    with pytest.raises(LuaError, match="starter_species"):
        mod.verify_starter()


@pytest.mark.parametrize("outcome", [0, 1, 2, 3, 4, 7, 9])
def test_rival_accepts_only_win_or_loss(machine, outcome):
    _, mod, fake = machine
    fake.flag(0x258, True)
    fake.w16(fake.sb1 + 0x10AA, 4)
    if outcome in (1, 2):
        mod.verify_rival(fake.cp, outcome)
    else:
        with pytest.raises(LuaError, match="rival_outcome"):
            mod.verify_rival(fake.cp, outcome)


@pytest.mark.parametrize("flag,scene", [(False, 4), (True, 3), (True, 5)])
def test_rival_requires_script_terminal(machine, flag, scene):
    _, mod, fake = machine
    fake.flag(0x258, flag)
    fake.w16(fake.sb1 + 0x10AA, scene)
    with pytest.raises(LuaError, match="rival_terminal"):
        mod.verify_rival(fake.cp, 1)


@pytest.mark.parametrize("slot", [0, 7, 29])
def test_parcel_fetch_reads_key_pocket_and_xor_quantity(machine, slot):
    _, mod, fake = machine
    fake.w16(fake.sb2 + 0xF20, 0xBEEF)
    addr = fake.sb1 + 0x3B8 + slot * 4
    fake.w16(addr, 349)
    fake.w16(addr + 2, 0xBEEF)  # encrypted zero: nonzero raw quantity is NOT proof
    with pytest.raises(LuaError, match="parcel_fetch_missing"):
        mod.verify_parcel_fetched(fake.cp)
    fake.w16(addr + 2, 0xBEEE)
    assert mod.verify_parcel_fetched(fake.cp)


def test_parcel_fetch_rejects_wrong_pocket_and_bad_pointer(machine):
    _, mod, fake = machine
    fake.w16(fake.sb1 + 0x430, 349)
    fake.w16(fake.sb1 + 0x432, 1)
    with pytest.raises(LuaError, match="parcel_fetch_missing"):
        mod.verify_parcel_fetched(fake.cp)
    fake.w32(0x03005008, 0)
    with pytest.raises(LuaError, match="parcel_fetch_pointer"):
        mod.verify_parcel_fetched(fake.cp)


def test_oak_delivery_missing_parcel_blames_fetch_without_press(machine):
    _, mod, fake = machine
    with pytest.raises(LuaError, match="parcel_fetch_precondition: mart/parcel_fetch"):
        mod.start_oak_delivery(fake.cp, "deliver")
    assert fake.taps == 0


def test_oak_delivery_stops_on_removal_without_extra_press(machine):
    lua, mod, fake = machine
    fake.w16(fake.sb1 + 0x3B8, 349)
    lua.execute("F.on_tap=function() if F.taps==3 then F.w16(F.sb1+0x3B8,0) end end")
    mod.start_oak_delivery(fake.cp, "deliver")
    assert fake.taps == 3


def test_delivery_requires_last_scene_write(machine):
    _, mod, fake = machine
    fake.flag(0x829, True)
    fake.w16(fake.sb1 + 0x430, 4)
    fake.w16(fake.sb1 + 0x10AA, 5)
    with pytest.raises(LuaError, match="parcel_delivery_scene"):
        mod.verify_parcel_delivered(fake.cp, "deliver")
    fake.w16(fake.sb1 + 0x10AA, 6)
    mod.verify_parcel_delivered(fake.cp, "deliver")


@pytest.mark.parametrize("home", ["pallet", "viridian"])
def test_whiteout_projects_outdoor_checkpoint_to_exact_interior(machine, home):
    _, mod, fake = machine
    if home == "pallet":
        fake.heal(3, 0, 6, 8)
        expected = (4, 0, 8, 5)
    else:
        expected = (5, 4, 7, 4)
    dest = mod.whiteout_destination(fake.cp)
    assert (dest.group, dest.num, dest.x, dest.y) == expected
    fake.place(*expected)
    assert mod.verify_destination(fake.cp, "whiteout", dest)
    fake.place(expected[0], expected[1], expected[2] + 1, expected[3])
    with pytest.raises(LuaError, match="destination_mismatch"):
        mod.check_whiteout(fake.cp, 787, 12, 38, dest)


@pytest.mark.parametrize("group,num,x,y", [(3, 2, 17, 26), (5, 4, 7, 4), (3, 1, 26, 28)])
def test_unknown_or_interior_heal_checkpoint_fails_named(machine, group, num, x, y):
    _, mod, fake = machine
    fake.heal(group, num, x, y)
    with pytest.raises(LuaError, match="whiteout_heal_unsupported"):
        mod.whiteout_destination(fake.cp)


def test_whiteout_target_is_frozen_before_battle_advances(machine):
    lua, _, _ = machine
    ok, why = lua.execute("""
        D.play.mash_a=function()
            F.heal(3,0,6,8); F.place(4,0,8,5); return true
        end
        D.play.wait_scene_settled=function() return true end
        return pcall(D.play.handle_encounter,F.cp,nil,'Down',{map=787,x=12,y=38})
    """)
    assert not ok
    assert "whiteout_landing: destination_mismatch" in why


def test_heal_pointer_is_fresh_and_invalid_pointer_fails(machine):
    _, mod, fake = machine
    old = fake.sb1
    fake.sb1 = old + 4
    fake.w32(0x03005008, fake.sb1)
    fake.heal(3, 0, 6, 8)
    assert mod.whiteout_destination(fake.cp).group == 4
    fake.w32(0x03005008, 0)
    with pytest.raises(LuaError, match="whiteout_heal_pointer"):
        mod.whiteout_destination(fake.cp)


@pytest.mark.parametrize("name,expected", [
    # pret c75f352 map_groups.json, map.json warps/connections, and the exterior
    # exit's one WALK_NORMAL_DOWN in src/field_fadetransition.c:357.
    ("house_exit", (3, 0, 6, 8)), ("lab", (4, 3, 6, 12)),
    ("lab_exit", (3, 0, 16, 14)), ("route1_south", (3, 19, 12, 39)),
    ("route1_north", (3, 19, 12, 0)), ("pallet_north", (3, 0, 12, 0)),
    ("viridian_south", (3, 1, 24, 39)), ("mart", (5, 3, 4, 7)),
    ("mart_exit", (3, 1, 36, 20)), ("center", (5, 4, 7, 8)),
    ("center_exit", (3, 1, 26, 27)),
])
def test_every_warp_rejects_wrong_map_and_wrong_tile(machine, name, expected):
    lua, mod, fake = machine
    dest = mod.DEST[name]
    assert (dest.group, dest.num, dest.x, dest.y) == expected
    lua.execute("D.play.enter_warp=function() return true end")
    fake.place(dest.group, dest.num, dest.x, dest.y)
    mod.warp_to(fake.cp, "Up", 30, dest, name)
    for group, num, x, y in [
        (dest.group + 1, dest.num, dest.x, dest.y),
        (dest.group, dest.num + 1, dest.x, dest.y),
        (dest.group, dest.num, dest.x + 1, dest.y),
        (dest.group, dest.num, dest.x, dest.y + 1),
    ]:
        fake.place(group, num, x, y)
        with pytest.raises(LuaError, match="destination_mismatch"):
            mod.warp_to(fake.cp, "Up", 30, dest, name)


@pytest.mark.parametrize("op", ["deposit", "release"])
@pytest.mark.parametrize("bad", [False, True])
def test_pc_removal_is_bound_to_preselected_slot1_pid(machine, op, bad):
    _, mod, fake = machine
    init_party(fake)
    before = mod.owned_snapshot("before")
    target = before.party.order[2]
    depart(fake, slot=0 if bad else 1, box=0 if op == "deposit" else None)
    after = mod.owned_snapshot("after")
    if bad:
        with pytest.raises(LuaError, match="pc_target"):
            mod.verify_pc_transfer("test", op, before, after, target)
    else:
        mod.verify_pc_transfer("test", op, before, after, target)


def test_pc_deposit_without_boxed_target_and_release_disguised_as_deposit_fail(machine):
    _, mod, fake = machine
    init_party(fake)
    before = mod.owned_snapshot("before")
    target = before.party.order[2]
    depart(fake)
    after = mod.owned_snapshot("after")
    with pytest.raises(LuaError, match="deposit_readback"):
        mod.verify_pc_transfer("test", "deposit", before, after, target)
    # Add the removed identity in the final slot of the final box: scan all 420 records.
    put_mon(fake, fake.storage + 4 + 419 * 80, 49)
    after = mod.owned_snapshot("after")
    with pytest.raises(LuaError, match="release_deposited"):
        mod.verify_pc_transfer("test", "release", before, after, target)


def test_pc_withdraw_round_trip_checks_box_removal_and_party_survivors(machine):
    _, mod, fake = machine
    init_party(fake)
    before = mod.owned_snapshot("before")
    target = mod.pc_deposit_target(before)
    depart(fake, box=0)
    mid = mod.owned_snapshot("mid")
    mod.verify_pc_transfer("test", "deposit", before, mid, target)
    withdraw(fake)
    after = mod.owned_snapshot("after")
    mod.verify_pc_transfer("test", "withdraw", mid, after, target)
    fake.w8(0x02024284 + 8, 1)  # nickname mutation leaves secure checksum valid
    damaged = mod.owned_snapshot("damaged")
    with pytest.raises(LuaError, match="not byte-identical"):
        mod.verify_pc_transfer("test", "withdraw", mid, damaged, target)


def test_pc_withdraw_wrong_pid_fails_even_if_party_count_returns(machine):
    _, mod, fake = machine
    init_party(fake)
    put_mon(fake, fake.storage + 4 + 80, 100)
    before = mod.owned_snapshot("before")
    target = before.party.order[2]
    depart(fake, box=0)
    mid = mod.owned_snapshot("mid")
    withdraw(fake, box=1)
    after = mod.owned_snapshot("after")
    with pytest.raises(LuaError, match="withdraw_target"):
        mod.verify_pc_transfer("test", "withdraw", mid, after, target)


def test_pc_rejects_clones_corrupt_boxes_and_bad_storage_pointer(machine):
    _, mod, fake = machine
    init_party(fake)
    depart(fake, box=0)
    withdraw(fake, clear=False)
    with pytest.raises(LuaError, match="ambiguous_box_record"):
        mod.owned_snapshot("clone")
    fake.w8(0x02024029, 2)
    fake.w16(fake.storage + 4 + 0x1C, 0)
    with pytest.raises(LuaError, match="invalid_box_checksum"):
        mod.owned_snapshot("corrupt")
    fake.w32(0x03005010, fake.storage + 128)
    with pytest.raises(LuaError, match="unreadable_storage"):
        mod.owned_snapshot("pointer")


def test_pc_release_rejects_unrelated_box_changes(machine):
    _, mod, fake = machine
    init_party(fake)
    put_mon(fake, fake.storage + 4 + 80, 100)
    before = mod.owned_snapshot("before")
    depart(fake)
    fake.w8(fake.storage + 4 + 80 + 8, 1)
    after = mod.owned_snapshot("after")
    with pytest.raises(LuaError, match="unrelated_box_changed"):
        mod.verify_pc_transfer("test", "release", before, after, before.party.order[2])


@pytest.mark.parametrize("home", ["pallet", "viridian"])
@pytest.mark.parametrize("grass", [False, True])
def test_recovery_routes_both_heal_locations_to_resume_start(machine, home, grass):
    lua, mod, fake = machine
    if home == "pallet":
        fake.heal(3, 0, 6, 8)
        fake.place(4, 0, 8, 5)
        arrivals = [(3, 0, 6, 8)]
    else:
        fake.place(5, 4, 7, 4)
        arrivals = [(3, 1, 26, 27), (3, 19, 12, 0), (3, 0, 12, 0)]
    if grass:
        arrivals.append((3, 19, 12, 39))
    fake.arrivals = lua.table_from([lua.table_from(a) for a in arrivals])
    lua.execute("""
        F.warps=0
        D.play.follow=function(cp,name)
            local p=D.PATHS[name]
            local x,y=G.pos(cp)
            assert(x==p.from[1] and y==p.from[2], 'wrong recovery path origin: '..name)
            for _,dir in ipairs(p.dirs) do
                if dir=='Up' then y=y-1 elseif dir=='Down' then y=y+1
                elseif dir=='Left' then x=x-1 else x=x+1 end
            end
            assert(x==p.to[1] and y==p.to[2], 'wrong recovery path endpoint: '..name)
            local g,n=G.map(cp); F.place(g,n,x,y)
        end
        D.play.enter_warp=function()
            F.warps=F.warps+1
            F.place(table.unpack(F.arrivals[F.warps]))
            return true
        end
    """)
    if grass:
        mod.recover_to_route1_grass(fake.cp)
        expected = (3, 19, 12, 37)
    else:
        mod.recover_to_pallet_town(fake.cp)
        expected = (3, 0, 6, 9)
    assert lua.execute("return G.map(F.cp)") == expected[:2]
    assert lua.execute("return G.pos(F.cp)") == expected[2:]
    assert fake.warps == len(arrivals)


def leg(mod, name):
    return next(mod.LEGS[i] for i in range(1, len(mod.LEGS) + 1) if mod.LEGS[i].name == name)


@pytest.mark.parametrize("granted", [False, True])
def test_parcel_fetch_leg_executes_oracle_after_scene(machine, granted):
    lua, mod, fake = machine
    lua.execute("""
        F.warps=0
        D.play.follow=function() end
        D.play.enter_warp=function()
            F.warps=F.warps+1
            local a={{3,19,12,39},{3,1,24,39},{5,3,4,7}}
            F.place(table.unpack(a[F.warps])); return true
        end
        D.play.wait_scene_settled=function() return true end
    """)
    if granted:
        fake.w16(fake.sb1 + 0x3B8, 349)
        fake.w16(fake.sb1 + 0x3BA, 1)
        leg(mod, "parcel_fetch").run(fake.cp)
    else:
        with pytest.raises(LuaError, match="parcel_fetch_missing"):
            leg(mod, "parcel_fetch").run(fake.cp)


@pytest.mark.parametrize("outcome,flag", [(1, True), (2, True), (4, True), (1, False)])
def test_rival_leg_captures_outcome_before_postbattle_scene(machine, outcome, flag):
    lua, mod, fake = machine
    fake.w8(0x02023E8A, outcome)
    fake.flag(0x258, flag)
    fake.w16(fake.sb1 + 0x10AA, 4)
    lua.execute("""
        D.play.follow=function() end
        D.play.mash_a=function() return true end
        D.play.wait_scene_settled=function() F.w8(0x02023E8A,0); return true end
    """)
    if outcome in (1, 2) and flag:
        leg(mod, "rival_battle").run(fake.cp)
    else:
        with pytest.raises(LuaError, match="rival_outcome|rival_terminal"):
            leg(mod, "rival_battle").run(fake.cp)


@pytest.mark.parametrize("bad", [False, True])
def test_release_leg_uses_selected_pid_and_box_census(machine, bad):
    lua, mod, fake = machine
    init_party(fake)
    mod.play.leave_menu = lambda *_: depart(fake, box=0 if bad else None)
    if bad:
        with pytest.raises(LuaError, match="release_deposited"):
            leg(mod, "pc_release").run(fake.cp)
    else:
        leg(mod, "pc_release").run(fake.cp)


@pytest.mark.parametrize("bad", [False, True])
def test_deposit_withdraw_leg_uses_target_readback(machine, bad):
    lua, mod, fake = machine
    init_party(fake)
    lua.execute("""
        F.warps=0
        D.play.follow=function() end
        D.play.enter_warp=function()
            F.warps=F.warps+1
            if F.warps==1 then F.place(3,1,24,39) else F.place(5,4,7,8) end
            return true
        end
    """)
    calls = []

    def leave(*_):
        calls.append(True)
        if len(calls) == 1:
            depart(fake, slot=0 if bad else 1, box=0)
        else:
            withdraw(fake)

    mod.play.leave_menu = leave
    if bad:
        with pytest.raises(LuaError, match="pc_target"):
            leg(mod, "viridian_pc_deposit_withdraw").run(fake.cp)
        assert len(calls) == 1, "must stop before trying to withdraw the wrong deposited mon"
    else:
        leg(mod, "viridian_pc_deposit_withdraw").run(fake.cp)
        assert len(calls) == 2


def test_owned_snapshot_rereads_relocated_storage_pointer(machine):
    _, mod, fake = machine
    init_party(fake)
    put_mon(fake, fake.storage + 4, 100)
    first = mod.owned_snapshot("first")
    assert len(list(first.boxes)) == 1
    fake.storage += 124  # last valid aligned relocation offset, fresh zeroed box data
    fake.w32(0x03005010, fake.storage)
    assert not list(mod.owned_snapshot("relocated").boxes)


@pytest.mark.parametrize("bad", ["current_box", "occupied_slot"])
def test_pc_deposit_preconditions_bind_the_withdraw_cursor(machine, bad):
    _, mod, fake = machine
    init_party(fake)
    if bad == "current_box":
        fake.w8(fake.storage, 1)
    else:
        put_mon(fake, fake.storage + 4, 100)
    with pytest.raises(LuaError, match="pc_box_cursor|pc_box_slot"):
        mod.pc_deposit_target(mod.owned_snapshot("before"))
