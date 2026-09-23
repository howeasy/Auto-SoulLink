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
    tap=function(btn) F.taps=F.taps+1; if F.on_tap then F.on_tap(btn) end end,
    advance=function() F.frame=F.frame+1; if F.on_frame then F.on_frame() end end,
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
    """The battle override signals during fight_through, before recovery runs."""
    lua, _, _ = machine
    ok, signal = lua.execute("""
        F.in_battle=true
        G.pred_ok=function(_,name)
            if name=='in_battle' then return not F.in_battle end
            return true
        end
        F.w8(D.ACTION_CURSOR_ADDR,0)
        F.w32(D.BATTLER_CTRL_ADDR,D.HANDLE_INPUT_CHOOSE_ACTION)
        F.on_tap=function(button)
            if button=='A' then F.w32(D.BATTLER_CTRL_ADDR,0) end
        end
        D.play.mash_a=function() F.place(5,4,7,4); F.in_battle=false; return true end
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
        mod.check_whiteout(fake.cp, 787, 12, 38)


@pytest.mark.parametrize("group,num,x,y", [(3, 2, 17, 26), (5, 4, 7, 4), (3, 1, 26, 28)])
def test_unknown_or_interior_heal_checkpoint_fails_named(machine, group, num, x, y):
    _, mod, fake = machine
    fake.heal(group, num, x, y)
    with pytest.raises(LuaError, match="whiteout_heal_unsupported"):
        mod.whiteout_destination(fake.cp)


def test_whiteout_target_is_frozen_before_battle_advances(machine):
    lua, _, _ = machine
    ok, why = lua.execute("""
        F.in_battle=true
        G.pred_ok=function(_,name)
            if name=='in_battle' then return not F.in_battle end
            return true
        end
        F.w8(D.ACTION_CURSOR_ADDR,0)
        F.w32(D.BATTLER_CTRL_ADDR,D.HANDLE_INPUT_CHOOSE_ACTION)
        F.on_tap=function(button)
            if button=='A' then F.w32(D.BATTLER_CTRL_ADDR,0) end
        end
        D.play.mash_a=function()
            F.heal(3,0,6,8); F.place(4,0,8,5); F.in_battle=false; return true
        end
        D.play.wait_scene_settled=function() return true end
        return pcall(D.play.handle_encounter,F.cp,nil,'Down',{map=787,x=12,y=38})
    """)
    assert not ok
    assert "whiteout_landing: destination_mismatch" in why


@pytest.mark.parametrize("own_battle", [False, True])
def test_unknown_heal_checkpoint_does_not_block_an_ordinary_battle(machine, own_battle):
    lua, mod, fake = machine
    fake.heal(3, 2, 17, 26)  # a later, valid checkpoint outside this route's known heals
    lua.execute("""
        D.play.mash_a=function() return true end
        D.play.wait_scene_settled=function() return true end
    """)
    if own_battle:
        assert mod.resolve_battle_and_check_whiteout(fake.cp, 160) is True
    else:
        mod.play.handle_encounter(fake.cp, None, "Down", lua.table(map=787, x=12, y=38))


def test_incidental_battle_resteers_remembered_pokemon_cursor_on_each_turn(machine):
    lua, mod, fake = machine
    lua.execute("""
        F.in_battle=true; F.cursor=2; F.stage='action'; F.actions=0; F.partyA=0
        F.w8(D.ACTION_CURSOR_ADDR,2)
        F.w32(D.BATTLER_CTRL_ADDR,D.HANDLE_INPUT_CHOOSE_ACTION)
        G.pred_ok=function(_,name)
            if name=='in_battle' then return not F.in_battle end
            return true
        end
        F.on_tap=function(button)
            if button=='Up' and F.stage=='action' then
                F.cursor=0; F.w8(D.ACTION_CURSOR_ADDR,0)
            elseif button=='A' then
                if F.stage=='action' then
                    if F.cursor==0 then
                        F.stage='move'; F.w32(D.BATTLER_CTRL_ADDR,0)
                    else
                        F.stage='party'; F.w32(D.BATTLER_CTRL_ADDR,0)
                    end
                elseif F.stage=='move' then
                    F.stage='animation'; F.actions=F.actions+1
                elseif F.stage=='animation' then
                    if F.actions>=2 then F.in_battle=false
                    else
                        F.stage='action'; F.cursor=2
                        F.w8(D.ACTION_CURSOR_ADDR,2)
                        F.w32(D.BATTLER_CTRL_ADDR,D.HANDLE_INPUT_CHOOSE_ACTION)
                    end
                elseif F.stage=='party' then F.partyA=F.partyA+1 end
            end
        end
    """)
    mod.play.handle_encounter(fake.cp, None, "Down", lua.table(map=787, x=12, y=38))
    assert fake.actions == 2
    assert fake.partyA == 0


@pytest.mark.parametrize("stray_popup", [False, True])
@pytest.mark.parametrize("egg_first", [False, True])
def test_forced_switch_selects_healthy_slot_from_run26_party_menu(machine, stray_popup, egg_first):
    lua, mod, fake = machine
    put_mon(fake, 0x02024284, 24)
    put_mon(fake, 0x02024284 + 100, 49)
    lua.execute("""
        F.in_battle=true; F.invalid=0; F.selected=-1; F.stage='party'; F.turns=0; F.stray_b=0
        F.w8(0x02024029,2)
        F.w16(0x02024284+0x56,0); F.w16(0x02024284+0x58,23)
        F.w16(0x02024284+100+0x56,17); F.w16(0x02024284+100+0x58,17)
        F.w32(0x030030F4,0x0811EBA1) -- CB2_UpdatePartyMenu | Thumb
        F.w8(0x0203B0A0+8,1)        -- PARTY_MENU_TYPE_IN_BATTLE
        F.w8(0x0203B0A0+9,0)        -- selected slot 0 (fainted)
        F.w8(0x0203B0A0+0xB,1)      -- PARTY_ACTION_SEND_OUT
        F.w32(0x03005090,0x081203B9) -- Task_ReturnToChooseMonAfterText | Thumb
        F.w8(0x03005090+4,1)
        G.pred_ok=function(_,name)
            if name=='in_battle' then return not F.in_battle end
            return true
        end
        F.on_tap=function(button)
            local task=F.r8(0x03005090) | F.r8(0x03005091)<<8
                       | F.r8(0x03005092)<<16 | F.r8(0x03005093)<<24
            if F.stage=='party' then
                if button=='A' and task==0x081203B9 then
                    F.w32(0x03005090,0x0811FB29) -- dismiss 'has no energy'
                elseif button=='Down' and task==0x0811FB29 then
                    F.w8(0x0203B0A0+9,1)
                    elseif button=='A' and task==0x0811FB29 then
                        F.w32(0x03005090,0x08122C5D) -- first A opens the popup, even on FNT
                    elseif button=='B' and task==0x08122C5D then
                        F.stray_b=F.stray_b+1; F.w32(0x03005090,0x0811FB29)
                    elseif button=='A' and task==0x08122C5D then
                        if F.r8(0x0203B0A0+9)==0 then
                            F.invalid=F.invalid+1; F.w32(0x03005090,0x081203B9)
                        else
                            F.selected=F.r8(0x0203B0A0+9)
                            F.stage='action'; F.w32(0x030030F4,0x08011101)
                            F.w32(0x03004FE0,D.HANDLE_INPUT_CHOOSE_ACTION)
                            F.w8(D.ACTION_CURSOR_ADDR,0)
                        end
                end
            elseif F.stage=='action' and button=='A' then
                F.stage='move'; F.w32(0x03004FE0,0)
            elseif F.stage=='move' and button=='A' then
                F.stage='animation'; F.turns=F.turns+1
            elseif F.stage=='animation' and button=='A' then F.in_battle=false end
        end
    """)
    if stray_popup:
        fake.w32(0x03005090, 0x08122C5D)
    if egg_first:
        fake.w16(0x02024284 + 0x56, 17)
        fake.w8(0x02024284 + 0x13, 6)  # has_species + isEgg header flag
    mod.play.handle_encounter(fake.cp, None, "Down", lua.table(map=787, x=12, y=38))
    assert fake.selected == 1 and fake.invalid == 0
    assert fake.stray_b == (1 if stray_popup else 0)
    assert fake.in_battle is False and fake.turns >= 1


def test_route1_faint_does_not_finish_on_counter_while_battle_open(machine):
    lua, mod, fake = machine
    lua.globals().savestate = lua.table(save=lambda *_: True)
    lua.execute("""
        F.in_battle=true
        F.w32(D.BATTLER_CTRL_ADDR,D.HANDLE_INPUT_CHOOSE_ACTION)
        F.w8(D.ACTION_CURSOR_ADDR,0)
        G.pred_ok=function(_,name)
            if name=='in_battle' then return not F.in_battle end
            return true
        end
        D.play.mash_a=function() F.w8(0x03004F90,1); return true end
        D.play.wait_scene_settled=function() return true end
        D.play.fight_through=function()
            F.w8(0x03004F90,1); F.in_battle=false; return true
        end
    """)
    leg(mod, "route1_faint").run(fake.cp)
    assert fake.in_battle is False
    assert any(str(fake.log[i]).startswith("fainted ") for i in range(1, len(fake.log) + 1))


def test_unknown_heal_checkpoint_never_reaches_nil_destination_comparison(machine):
    lua, mod, fake = machine
    fake.heal(3, 2, 17, 26)
    fake.place(5, 4, 7, 4)
    lua.execute("F.fail=nil; G.finish=function(_,message) F.fail=message end")
    mod.check_whiteout(fake.cp, 787, 12, 38)
    assert "whiteout_heal_unsupported" in fake.fail


@pytest.mark.parametrize("name", ["parcel_deliver", "route1_catch", "route1_faint"])
def test_second_whiteout_inside_recover_fails_by_name(machine, name):
    lua, mod, fake = machine
    fake.place(5, 4, 7, 4)
    lua.execute("D.play.follow=function() error({whiteout=true},0) end")
    with pytest.raises(LuaError, match="whiteout_during_recovery"):
        leg(mod, name).recover(fake.cp)


def test_recovery_rethrows_unrelated_error_unchanged(machine):
    lua, mod, fake = machine
    fake.place(5, 4, 7, 4)
    lua.execute("D.play.follow=function() error('source path failed',0) end")
    with pytest.raises(LuaError, match="source path failed"):
        leg(mod, "route1_faint").recover(fake.cp)


def test_forced_party_menu_rejects_no_living_replacement(machine):
    lua, mod, fake = machine
    fake.w8(0x02024029, 2)
    fake.w32(0x030030F4, 0x0811EBA1)
    fake.w8(0x0203B0A0 + 8, 1)
    fake.w8(0x0203B0A0 + 0xB, 1)
    lua.execute("G.pred_ok=function(_,name) return name~='in_battle' end")
    with pytest.raises(LuaError, match="forced_party_no_healthy_mon"):
        mod.play.fight_through(fake.cp)


def test_incidental_battle_refuses_a_fight_press_that_stays_on_action_menu(machine):
    lua, mod, fake = machine
    fake.w32(mod.BATTLER_CTRL_ADDR, mod.HANDLE_INPUT_CHOOSE_ACTION)
    fake.w8(mod.ACTION_CURSOR_ADDR, 0)
    lua.execute("G.pred_ok=function(_,name) return name~='in_battle' end")
    with pytest.raises(LuaError, match="FIGHT selection did not leave the action menu"):
        mod.play.fight_through(fake.cp)


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


@pytest.mark.parametrize("box_slot", [1, 30])
def test_pc_deposit_requires_target_in_box_zero_slot_zero(machine, box_slot):
    _, mod, fake = machine
    init_party(fake)
    before = mod.owned_snapshot("before")
    target = before.party.order[2]
    depart(fake, box=box_slot)
    after = mod.owned_snapshot("after")
    assert after.boxes[target].species == before.mons[target].species
    with pytest.raises(LuaError, match="deposit_readback"):
        mod.verify_pc_transfer("test", "deposit", before, after, target)


def test_pc_withdraw_rejects_same_pid_with_changed_species(machine):
    _, mod, fake = machine
    init_party(fake)
    depart(fake, box=0)
    mid = mod.owned_snapshot("mid")
    target = next(iter(mid.boxes))
    put_mon(fake, fake.storage + 4, 49, species=4)
    withdraw(fake)
    after = mod.owned_snapshot("after")
    assert target in after.mons and mid.boxes[target].species != after.mons[target].species
    with pytest.raises(LuaError, match="withdraw_species"):
        mod.verify_pc_transfer("test", "withdraw", mid, after, target)


def test_pc_failure_returns_before_accessing_missing_target(machine):
    lua, mod, fake = machine
    init_party(fake)
    depart(fake, box=0)
    before = mod.owned_snapshot("before")
    target = next(iter(before.boxes))
    put_mon(fake, 0x02024284 + 2 * 100, 100)
    fake.w8(0x02024029, 3)
    after = mod.owned_snapshot("after")
    lua.execute("F.fail=nil; G.finish=function(_,message) F.fail=message end")
    assert mod.verify_pc_transfer("test", "withdraw", before, after, target) is False
    assert "withdraw_target" in fake.fail


def test_nonraising_finish_stops_failed_starter_rival_and_pc_precondition(machine):
    lua, mod, fake = machine
    lua.execute("F.failures={}; G.finish=function(_,message) F.failures[#F.failures+1]=message end")
    assert mod.verify_starter() is False
    assert len(fake.failures) == 1 and "starter_species" in fake.failures[1]
    assert mod.verify_rival(fake.cp, 0) is False
    assert len(fake.failures) == 2 and "rival_outcome" in fake.failures[2]
    too_small = lua.table(party=lua.table(n=1), current_box=0, boxes=lua.table())
    assert mod.pc_deposit_target(too_small) is None
    assert len(fake.failures) == 3 and "pc_target" in fake.failures[3]


def test_nonraising_finish_stops_on_first_unrelated_box_change(machine):
    lua, mod, fake = machine
    init_party(fake)
    put_mon(fake, fake.storage + 4 + 80, 100)
    before = mod.owned_snapshot("before")
    target = before.party.order[2]
    depart(fake)
    fake.w8(fake.storage + 4 + 80 + 8, 1)
    after = mod.owned_snapshot("after")
    lua.execute("F.failures={}; G.finish=function(_,message) F.failures[#F.failures+1]=message end")
    assert mod.verify_pc_transfer("test", "release", before, after, target) is False
    assert len(fake.failures) == 1 and "unrelated_box_changed" in fake.failures[1]


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
    for name in ("open", "mode", "popup", "select", "release"):
        mod.PC[name] = lambda *_: True
    mod.PC.leave = lambda *_: depart(fake, box=0 if bad else None)
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
        F.place(3,19,12,37)   -- the grass origin the leg's first path starts from
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

    for name in ("open", "mode", "popup", "select", "box", "withdraw"):
        mod.PC[name] = lambda *_: True
    mod.PC.leave = leave
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


def test_run27b_which_pc_menu_retries_a_lost_press(machine):
    lua, mod, fake = machine
    lua.execute("""
        F.pc_a=0
        F.w32(0x03005090,0x0809CC99) -- Task_MultichoiceMenu_HandleInput
        F.w8(0x03005090+4,1)
        F.w8(0x0203ADE4+2,0) -- sMenu.cursorPos = Someone's PC
        F.w8(0x0203ADE4+4,3) -- four owner rows
        F.w16(0x020370D0,127) -- stale result is not a completed selection
        G.pred_ok=function(_,name)
            if name=='script_context_status' then return false end
            return true
        end
        F.on_tap=function(button)
            if button~='A' then return end
            F.pc_a=F.pc_a+1
            if F.pc_a==2 then F.w32(0x03005090,0); F.w16(0x020370D0,0) end
            if F.pc_a==4 then
                F.w32(0x03005090,0x0808C39D) -- Task_PCMainMenu
                F.w16(0x03005090+8,2); F.w16(0x03005090+10,0)
            end
        end
    """)
    assert mod.PC.open(fake.cp, "run27b") is True
    assert fake.pc_a == 4


def test_which_pc_wrong_row_and_permanently_lost_a_fail_named(machine):
    lua, mod, fake = machine
    fake.w32(0x03005090, 0x0809CC99)
    fake.w8(0x03005090 + 4, 1)
    fake.w8(0x0203ADE4 + 2, 1)
    fake.w8(0x0203ADE4 + 4, 3)
    with pytest.raises(LuaError, match="pc_which_pc_wrong_row"):
        mod.PC.open(fake.cp, "wrong")
    fake.w8(0x0203ADE4 + 2, 0)
    with pytest.raises(LuaError, match="pc_which_pc_choice_not_consumed"):
        mod.PC.open(fake.cp, "lost")


def test_pc_deposit_menu_cursor_popup_and_box_chooser_are_witnessed(machine):
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000; F.box_t=0
        F.w32(0x020397B0,F.pcstore)
        F.w32(0x03005090,0x0808C39D); F.w8(0x03005090+4,1)
        F.w16(0x03005090+8,2); F.w16(0x03005090+10,0)
        F.w8(0x0203ADE4+4,4) -- five storage rows
        F.on_tap=function(button)
            local task=memory.read_u32_le(0x03005090)
            if task==0x0808C39D then
                if button=='Down' then F.w16(0x03005090+10,1)
                elseif button=='A' then
                    F.w32(0x03005090,0x0808D2BD)
                    F.w8(F.pcstore,0); F.w8(F.pcstore+1,1)
                    F.w8(0x02039820,1); F.w8(0x02039821,0)
                end
            elseif task==0x0808D2BD then
                if button=='Down' then F.w8(0x02039821,1)
                elseif button=='A' then
                    F.w32(0x03005090,0x0808D879)
                    F.w8(F.pcstore,2); F.w8(0x0203ADE4+2,0); F.w8(0x0203ADE4+4,4)
                end
            elseif task==0x0808D879 and button=='A' then
                F.w32(0x03005090,0x0808DD89)
                F.w8(F.pcstore,1); F.w8(0x020397B6,0)
            elseif task==0x0808DD89 and button=='A' then
                F.w8(F.pcstore,2) -- commit starts; task returns after compaction
            end
        end
        F.on_frame=function()
            if memory.read_u32_le(0x03005090)==0x0808DD89 and F.r8(F.pcstore)==2 then
                F.box_t=F.box_t+1
                if F.box_t==3 then
                    F.w32(0x03005090,0x0808D2BD); F.w8(F.pcstore,0)
                end
            end
        end
    """)
    assert mod.PC.open(fake.cp, "deposit") is True
    assert mod.PC.mode("deposit", 1) is True
    assert mod.PC.popup("deposit", 1, 1, 0) is True
    assert mod.PC.select("deposit", 0x0808DD89) is True
    assert mod.PC.box("deposit") is True
    assert fake.box_t >= 3


def test_pc_storage_cursor_wrong_area_fails_before_press(machine):
    _, mod, fake = machine
    fake.w32(0x020397B0, 0x0202A000)
    fake.w32(0x03005090, 0x0808D2BD)
    fake.w8(0x03005090 + 4, 1)
    fake.w8(0x02039820, 0)
    with pytest.raises(LuaError, match="pc_storage_cursor_wrong_area"):
        mod.PC.cursor("wrong", 1, 1)


def test_pc_exit_closes_storage_then_cancels_owner_list(machine):
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000; F.field=false; F.b=0
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,0)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        G.pred_ok=function(_,name)
            if name=='script_context_status' or name=='field_controls_locked' then return F.field end
            return true
        end
        F.on_tap=function(button)
            if button=='B' then
                F.b=F.b+1
                if F.b==1 then F.w32(0x03005090,0) end -- storage closes
                if F.b==2 then
                    F.w32(0x03005090,0); F.w16(0x020370D0,127); F.field=true
                end
            elseif button=='A' and F.b==1 then
                F.w32(0x03005090,0x0809CC99)
                F.w8(0x0203ADE4+4,3) -- owner list returns
            end
        end
    """)
    assert mod.PC.leave(fake.cp, "exit") is True
    assert fake.b == 2 and fake.field is True


def test_pc_withdraw_and_release_follow_their_own_task_states(machine):
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000; F.t=0; F.release_as=0
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,0); F.w8(F.pcstore+1,0)
        F.w8(0x02039820,0); F.w8(0x02039821,0)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        F.on_tap=function(button)
            local task=memory.read_u32_le(0x03005090)
            if task==0x0808D2BD and button=='A' then
                F.w32(0x03005090,0x0808D879); F.w8(F.pcstore,2)
                F.w8(0x0203ADE4+2,0); F.w8(0x0203ADE4+4,4)
            elseif task==0x0808D879 then
                if button=='Down' then F.w8(0x0203ADE4+2,F.r8(0x0203ADE4+2)+1)
                elseif button=='A' then
                    if F.r8(F.pcstore+1)==0 then F.w32(0x03005090,0x0808DC9D)
                    else F.w32(0x03005090,0x0808DECD); F.w8(F.pcstore,1)
                         F.w8(0x0203ADE4+2,1) end
                end
            elseif task==0x0808DECD then
                if button=='Up' then F.w8(0x0203ADE4+2,0)
                elseif button=='A' then
                    F.release_as=F.release_as+1
                    if F.release_as==1 then F.w8(F.pcstore,4)
                    elseif F.release_as==2 then F.w8(F.pcstore,5)
                    else F.w32(0x03005090,0x0808D2BD); F.w8(F.pcstore,0) end
                end
            end
        end
        F.on_frame=function()
            if memory.read_u32_le(0x03005090)==0x0808DC9D then
                F.t=F.t+1
                if F.t==3 then F.w32(0x03005090,0x0808D2BD); F.w8(F.pcstore,0) end
            end
        end
    """)
    assert mod.PC.popup("withdraw", 0, 0, 0) is True
    assert mod.PC.select("withdraw", 0x0808DC9D) is True
    assert mod.PC.withdraw("withdraw") is True
    fake.w8(fake.pcstore + 1, 1)
    fake.w8(0x02039820, 1)
    fake.w8(0x02039821, 1)
    assert mod.PC.popup("release", 1, 1, 3) is True
    assert mod.PC.select("release", 0x0808DECD) is True
    assert mod.PC.release("release") is True
    assert fake.release_as == 3


def test_lost_party_select_press_fails_at_popup_stage(machine):
    _, mod, fake = machine
    fake.w32(0x020397B0, 0x0202A000)
    fake.w8(0x0202A000, 0)
    fake.w8(0x0202A001, 1)
    fake.w32(0x03005090, 0x0808D2BD)
    fake.w8(0x03005090 + 4, 1)
    fake.w8(0x02039820, 1)
    fake.w8(0x02039821, 1)
    with pytest.raises(LuaError, match="pc_storage_popup_missing"):
        mod.PC.popup("lost", 1, 1, 0)


def test_battle_mash_stops_before_party_menu_can_consume_another_a(machine):
    lua, mod, fake = machine
    lua.execute("""
        F.in_battle=true; F.stage='action'; F.badA=0
        F.w32(D.BATTLER_CTRL_ADDR,D.HANDLE_INPUT_CHOOSE_ACTION)
        F.w8(D.ACTION_CURSOR_ADDR,0)
        G.pred_ok=function(_,name)
            if name=='in_battle' then return not F.in_battle end
            return true
        end
        F.on_tap=function(button)
            if button~='A' then return end
            if F.stage=='action' then
                F.stage='move'; F.w32(D.BATTLER_CTRL_ADDR,0)
            elseif F.stage=='move' then F.stage='animation'
            elseif F.stage=='animation' then
                F.stage='party'; F.w32(0x030030F4,0x0811EBA1)
                F.w8(0x02024029,2); F.w8(0x0203B0A0+8,1)
                F.w8(0x0203B0A0+0xB,1)
            elseif F.stage=='party' then F.badA=F.badA+1 end
        end
    """)
    with pytest.raises(LuaError, match="forced_party_no_healthy_mon"):
        mod.play.fight_through(fake.cp)
    assert fake.badA == 0


@pytest.mark.parametrize("gate", ["battle", "settle", "field"])
def test_route1_faint_refuses_unsettled_terminal(machine, gate):
    lua, mod, fake = machine
    lua.globals().savestate = lua.table(save=lambda *_: True)
    lua.execute("""
        F.in_battle=true; F.field=true
        F.w32(D.BATTLER_CTRL_ADDR,D.HANDLE_INPUT_CHOOSE_ACTION)
        F.w8(D.ACTION_CURSOR_ADDR,0)
        G.pred_ok=function(_,name)
            if name=='in_battle' then return not F.in_battle end
            if name=='callback2' then return F.field end
            return true
        end
        D.play.fight_through=function()
            F.w8(0x03004F90,1)
            if F.gate~='battle' then F.in_battle=false end
            return true
        end
        D.play.wait_scene_settled=function() return F.gate~='settle' end
    """)
    fake.gate = gate
    if gate == "field":
        fake.field = False
    with pytest.raises(LuaError, match="battle_not_settled_after_faint"):
        leg(mod, "route1_faint").run(fake.cp)


def test_door_exit_is_judged_after_the_step_off_the_door(machine):
    # FR run 25b: the map changed while the player still stood on the Viridian mart door
    # (36,19); the exterior exit's scripted step lands on (36,20) a few frames later.
    lua, mod, fake = machine
    dest = mod.DEST["mart_exit"]
    lua.execute("""
        D.play.enter_warp=function() return true end
        F.place(3,1,36,19)
        local t0=F.frame
        F.on_frame=function() if F.frame>=t0+20 then F.place(3,1,36,20) end end
    """)
    mod.warp_to(fake.cp, "Down", 30, dest, "mart exit")
    lua.execute("F.on_frame=nil")


def test_lab_exit_verify_waits_for_the_step_off_the_door(machine):
    # FR run 25c: route1_catch calls verify_destination straight after enter_warp and read
    # the lab door (16,13); the exit step lands on (16,14).
    lua, mod, fake = machine
    lua.execute("""
        F.place(3,0,16,13)
        local t0=F.frame
        F.on_frame=function() if F.frame>=t0+30 then F.place(3,0,16,14) end end
    """)
    assert mod.verify_destination(fake.cp, "route1_catch lab exit", mod.DEST["lab_exit"])
    lua.execute("F.on_frame=nil")


@pytest.mark.parametrize("start,steps", [((12, 37), []), ((13, 38), ["Left", "Up"]),
                                         ((13, 37), ["Left"]), ((12, 38), ["Up"])])
def test_return_to_grass_origin_from_every_square_tile(machine, start, steps):
    # FR run 25d: route1_faint ended at (13,38); viridian_pc's path starts at (12,37).
    lua, mod, fake = machine
    fake.place(3, 19, *start)
    lua.execute("""
        F.steps={}
        D.play.step=function(cp,dir)
            F.steps[#F.steps+1]=dir
            local x,y=G.pos(cp)
            if dir=="Left" then x=x-1 else y=y-1 end
            F.place(3,19,x,y); return true
        end
    """)
    mod.return_to_grass_origin(fake.cp, "t")
    assert list(fake.steps.values()) == steps
    assert tuple(lua.eval("{G.pos(F.cp)}").values()) == (12, 37)


def test_return_to_grass_origin_refuses_off_square(machine):
    lua, mod, fake = machine
    fake.place(3, 19, 12, 30)
    with pytest.raises(LuaError, match="grass square"):
        mod.return_to_grass_origin(fake.cp, "t")


@pytest.mark.parametrize("start,first", [((12, 37), "Right"), ((13, 37), "Down"),
                                         ((13, 38), "Left"), ((12, 38), "Up")])
def test_grass_hunt_first_step_follows_the_tile(machine, start, first):
    # FR run 27: a hunt resumed from a savestate at (13,38) stepped Right, off the square.
    lua, mod, fake = machine
    fake.place(3, 19, *start)
    lua.execute("""
        F.dirs={}
        D.play.step=function(cp,dir) F.dirs[#F.dirs+1]=dir; error("stop", 0) end
    """)
    with pytest.raises(LuaError, match="stop"):
        mod.hunt_encounter(fake.cp, "t", 1)
    assert fake.dirs[1] == first


def test_viridian_pc_recovers_from_a_whiteout_into_its_own_center(machine):
    # FR run 28: the Route 1 walk whited out; the landing is Viridian Center 5.4 (7,4).
    lua, mod, fake = machine
    leg = next(g for g in mod.LEGS.values() if g.name == "viridian_pc_deposit_withdraw")
    fake.place(5, 4, 7, 4)
    leg.recover(fake.cp)                                  # the landing verifies
    fake.place(5, 4, 7, 8)
    with pytest.raises(LuaError, match="whiteout landing"):
        leg.recover(fake.cp)
    lua.execute("F.paths={}; D.play.follow=function(cp,name) F.paths[#F.paths+1]=name; error('stop',0) end")
    with pytest.raises(LuaError, match="stop"):
        leg.resume(fake.cp)
    assert fake.paths[1] == "center_heal_spot_to_pc"      # resume starts inside the Center


def test_pc_exit_answers_continue_box_with_b_not_a(machine):
    # FR run 28b: B in storage opens "Continue BOX operations?" (Task_OnBPressed, cursor on
    # YES); A there keeps the box open, and the old exit loop pressed A forever. pret
    # pokemon_storage_system_tasks.c:1988-2035: B on the prompt exits.
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000; F.field=false; F.stage='storage'; F.a_in_box=0
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,0)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        G.pred_ok=function(_,name)
            if name=='script_context_status' or name=='field_controls_locked' then return F.field end
            return true
        end
        F.on_tap=function(button)
            if F.stage=='storage' and button=='B' then
                F.stage='prompt'; F.w32(0x03005090,0x0808ECE5); F.w8(F.pcstore,2)
            elseif F.stage=='prompt' and button=='A' then
                F.a_in_box=F.a_in_box+1; F.stage='storage'; F.w32(0x03005090,0x0808D2BD); F.w8(F.pcstore,0)
            elseif F.stage=='prompt' and button=='B' then
                F.stage='script'; F.w32(0x03005090,0)
            elseif F.stage=='script' and button=='A' then
                F.stage='owner'; F.w32(0x03005090,0x0809CC99); F.w8(0x0203ADE4+4,3)
            elseif F.stage=='owner' and button=='B' then
                F.stage='field'; F.w32(0x03005090,0); F.w16(0x020370D0,127); F.field=true
            end
        end
    """)
    assert mod.PC.leave(fake.cp, "exit") is True
    assert fake.a_in_box == 0 and fake.stage == "field"
