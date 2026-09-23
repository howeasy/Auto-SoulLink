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
    # FR run 28b: B in storage opens "Continue BOX operations?" (Task_OnBPressed). Its cursor
    # starts on NO, not YES -- ShowYesNoWindow(0) -> CreateYesNoMenu(..., initialCursorPos = 1)
    # then a 0-delta move (pokemon_storage_system_tasks.c:2595-2599; menu.c:323-334) -- so A
    # selects NO and B is MENU_B_PRESSED: BOTH exit (tasks.c:2016-2031), and only Down+A (YES)
    # stays in the box. The 28b loop was on the storage TOP MENU this exits to, not on the
    # prompt (run 28c's dump shows Task_PCMainMenu live across every stuck step). The assertion
    # is the real property either way: nothing may press A while a box menu owns input.
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
                -- FR run 28d: leaving the box lands on the storage main menu (state 2)
                F.stage='mainmenu'; F.w32(0x03005090,0x0808C39D); F.w16(0x03005090+8,2)
                F.w32(0x020397B0,0)
            elseif F.stage=='mainmenu' and button=='A' then
                F.a_in_box=F.a_in_box+1           -- A here would re-enter DEPOSIT
            elseif F.stage=='mainmenu' and button=='B' then
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


# ── C3-40: every remaining PC/exit stage check gets its own witness ───────────────────────────
# Finding 3 of cx-006e6f09 measured 19 PC stage checks and 5 exit checks whose deletion left the
# suite green. Each test below drives the real PC.* function through the fake RAM and asserts
# the ONE named failure that guard emits, so deleting the guard turns its test red (the
# before/after mutation matrix is the C3-40 receipt). The fakes supply RAM transitions only.


def test_pc_open_rejects_a_stale_result_without_the_choice_witness(machine):
    """VAR_RESULT can hold the PREVIOUS PC visit's row (127 = owner list already cancelled,
    pc.inc:20-37). It is written by Task_MultichoiceMenu_HandleInput, so it may only be read
    once that task is gone -- reading it while the menu is still up, or trusting it before the
    visit wrote it, accepts a PC the player never chose."""
    lua, mod, fake = machine
    lua.execute("""
        F.w32(0x03005090,0x0809CC99); F.w8(0x03005090+4,1) -- Task_MultichoiceMenu_HandleInput
        F.w8(0x0203ADE4+2,0); F.w8(0x0203ADE4+4,3)          -- row 0, four owner rows
        F.w16(0x020370D0,127)                               -- stale VAR_RESULT
        F.on_tap=function(button)
            if button~='A' then return end
            -- the choice is consumed; the top menu appears and no new VAR_RESULT was written
            F.w32(0x03005090,0x0808C39D); F.w16(0x03005090+8,2); F.w16(0x03005090+10,0)
        end
    """)
    with pytest.raises(LuaError, match="pc_which_pc_result_not_someones"):
        mod.PC.open(fake.cp, "stale-result")


@pytest.mark.parametrize("rows", [2, 6])
def test_pc_open_refuses_an_impossible_owner_row_count(machine, rows):
    """CreatePCMenuWindow offers three rows (no Pokedex), four (Pokedex obtained) or five (game
    clear) -- src/script_menu.c:1006-1034; the four-row case is the one a normal post-parcel run
    sees. Any other count means the menu being read is not this menu."""
    lua, mod, fake = machine
    fake.w32(0x03005090, 0x0809CC99)
    fake.w8(0x03005090 + 4, 1)
    fake.w8(0x0203ADE4 + 2, 0)
    fake.w8(0x0203ADE4 + 4, rows - 1)
    with pytest.raises(LuaError, match="pc_which_pc_wrong_row_count"):
        mod.PC.open(fake.cp, "row-count")


def test_pc_open_waits_for_the_storage_top_menu_to_accept_input(machine):
    """Task_PCMainMenu state 2 is HANDLE_INPUT (pokemon_storage_system_menu.c:230-264); a row
    read while the menu is still sliding in is a row the player cannot press yet."""
    lua, mod, fake = machine
    fake.w32(0x03005090, 0x0808C39D)
    fake.w8(0x03005090 + 4, 1)
    fake.w16(0x03005090 + 8, 1)      # still opening
    fake.w16(0x03005090 + 10, 0)
    with pytest.raises(LuaError, match="pc_storage_top_not_ready"):
        mod.PC.open(fake.cp, "top-not-ready")


def test_pc_open_refuses_a_resumed_top_menu_on_another_row(machine):
    """A resumed session can leave the top menu on the last used option (FieldTask_ReturnToPcMenu,
    pokemon_storage_system_menu.c:354-372); the leg's next step assumes WITHDRAW."""
    lua, mod, fake = machine
    fake.w32(0x03005090, 0x0808C39D)
    fake.w8(0x03005090 + 4, 1)
    fake.w16(0x03005090 + 8, 2)
    fake.w16(0x03005090 + 10, 1)     # parked on DEPOSIT
    with pytest.raises(LuaError, match="pc_storage_top_wrong_row"):
        mod.PC.open(fake.cp, "top-row")


def test_pc_mode_requires_the_five_row_storage_menu(machine):
    """The storage menu is WITHDRAW / DEPOSIT / MOVE POKeMON / MOVE ITEMS / SEE YA!
    (pokemon_storage_system_menu.c:37-43) -- five rows. A different count means the menu that is
    up belongs to another screen."""
    lua, mod, fake = machine
    fake.w32(0x03005090, 0x0808C39D)
    fake.w8(0x03005090 + 4, 1)
    fake.w16(0x03005090 + 8, 2)
    fake.w16(0x03005090 + 10, 1)
    fake.w8(0x0203ADE4 + 4, 3)       # four rows
    with pytest.raises(LuaError, match="pc_storage_top_wrong_row_count"):
        mod.PC.mode("deposit", 1)


def test_pc_mode_refuses_a_storage_entered_in_another_mode(machine):
    """gStorage->boxOption must be the row that was just chosen (OPTION_WITHDRAW 0 /
    OPTION_DEPOSIT 1, include/pokemon_storage_system_internal.h:17-24). Entering DEPOSIT while
    the storage is in MOVE MONS would drive the party-side popup for the wrong operation."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore)
        F.w32(0x03005090,0x0808C39D); F.w8(0x03005090+4,1)
        F.w16(0x03005090+8,2); F.w16(0x03005090+10,1)
        F.w8(0x0203ADE4+4,4)
        F.on_tap=function(button)
            if button=='A' then
                F.w32(0x03005090,0x0808D2BD); F.w8(F.pcstore,0); F.w8(F.pcstore+1,2)
            end
        end
    """)
    with pytest.raises(LuaError, match="pc_storage_mode_mismatch"):
        mod.PC.mode("deposit", 1)


def test_pc_mode_waits_for_the_storage_cursor_before_handing_over(machine):
    """Task_PokeStorageMain's state 0 is the box view ready for input. Returning before it
    arrives hands the next stage a menu that is still placing its cursor."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore)
        F.w32(0x03005090,0x0808C39D); F.w8(0x03005090+4,1)
        F.w16(0x03005090+8,2); F.w16(0x03005090+10,1)
        F.w8(0x0203ADE4+4,4)
        F.on_tap=function(button)
            if button=='A' then
                F.w32(0x03005090,0x0808D2BD); F.w8(F.pcstore,1); F.w8(F.pcstore+1,1)
            end
        end
    """)
    with pytest.raises(LuaError, match="pc_storage_cursor_not_ready"):
        mod.PC.mode("deposit", 1)


def test_pc_cursor_refuses_an_out_of_range_position(machine):
    """A box holds 30 mons and the party six; a position past that is not a storage cursor, and
    the guard runs before any press so a bad read cannot be walked around the box."""
    lua, mod, fake = machine
    fake.w32(0x020397B0, 0x0202A000)
    fake.w32(0x03005090, 0x0808D2BD)
    fake.w8(0x03005090 + 4, 1)
    fake.w8(0x02039820, 1)           # the party area the caller asked for
    fake.w8(0x02039821, 6)           # six is past the last party slot
    with pytest.raises(LuaError, match="pc_storage_cursor_invalid"):
        mod.PC.cursor("bad-cursor", 1, 3)


@pytest.mark.parametrize("maxc,cursor,row,stage", [(3, 0, 0, "wrong_row_count"),
                                                   (4, 4, 3, "wrong_row")])
def test_pc_popup_requires_five_rows_and_a_row_it_can_reach(machine, maxc, cursor, row, stage):
    """STORE / SUMMARY / MARK / RELEASE / CANCEL is five rows in both modes
    (SetMenuTextsForMon, pokemon_storage_system_data.c:1755-1805); a cursor already BELOW the
    wanted row means this read belongs to a different menu instance."""
    lua, mod, fake = machine
    lua.execute(f"""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,2); F.w8(F.pcstore+1,1)
        F.w8(0x02039820,1); F.w8(0x02039821,1)           -- the party-area storage cursor
        F.w8(0x0203ADE4+2,1); F.w8(0x0203ADE4+4,4)       -- the storage cursor's own menu
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        F.on_tap=function(button)
            if button~='A' then return end
            F.w32(0x03005090,0x0808D879)                 -- Task_OnSelectedMon: the popup opens
            F.w8(0x0203ADE4+2,{cursor}); F.w8(0x0203ADE4+4,{maxc})
        end
    """)
    with pytest.raises(LuaError, match="pc_storage_popup_" + stage):
        mod.PC.popup("popup", 1, 1, row)


def test_pc_popup_refuses_a_popup_opened_in_move_mons_mode(machine):
    """A party-area cursor serves the DEPOSIT popup (STORE / SUMMARY / MARK / RELEASE / CANCEL).
    boxOption is its own enum (OPTION_MOVE_MONS = 2, OPTION_MOVE_ITEMS = 3,
    include/pokemon_storage_system_internal.h:17-24), so a popup opened while the storage is
    moving mons is not the operation this stage drives. Comparing boxOption to the CURSOR_AREA
    value instead of the area's own option made this a coincidence of 0/1 (C3-40, finding 5)."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,2); F.w8(F.pcstore+1,2) -- MOVE MONS
        F.w8(0x02039820,1); F.w8(0x02039821,1)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
    """)
    with pytest.raises(LuaError, match="pc_storage_popup_wrong_mode"):
        mod.PC.popup("move-mons", 1, 1, 0)


def test_pc_box_chooser_must_start_on_the_deposit_box(machine):
    """CreateChooseBoxMenuSprites(sDepositBoxId) opens on the last confirmed box
    (pokemon_storage_system_tasks.c:1189-1222); on a fresh leg that is box 0, so anything else
    means the chooser on screen is not the one this leg opened, and its A would store into a box
    the oracle never snapshotted."""
    lua, mod, fake = machine
    fake.w32(0x020397B0, 0x0202A000)
    fake.w8(0x0202A000, 1)
    fake.w32(0x03005090, 0x0808DD89)      # Task_DepositMenu
    fake.w8(0x03005090 + 4, 1)
    fake.w8(0x020397B6, 1)                # sDepositBoxId: last confirmed box 1
    with pytest.raises(LuaError, match="pc_box_chooser_wrong_box"):
        mod.PC.box("box-chooser")


def test_pc_box_reports_a_full_destination_box(machine):
    """A full destination box makes TryStorePartyMonInBox fail and returns to box selection with
    an error (pokemon_storage_system_tasks.c:1201-1249); the leg must not read that as a
    deposit."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,1)
        F.w32(0x03005090,0x0808DD89); F.w8(0x03005090+4,1)
        F.w8(0x020397B6,0)
        F.on_tap=function(button)
            if button=='A' then F.w8(F.pcstore,4) end -- BOX_FULL error state
        end
    """)
    with pytest.raises(LuaError, match="pc_box_deposit_box_full"):
        mod.PC.box("box-full")


@pytest.mark.parametrize("start_cursor,honour_up,stage", [(2, False, "not_no"),
                                                          (1, False, "not_yes")])
def test_pc_release_confirmation_guards_its_cursor(machine, start_cursor, honour_up, stage):
    """Task_ReleaseMon shows ShowYesNoWindow(1): the cursor starts on NO and does not wrap
    (pokemon_storage_system_tasks.c:1255-1305,2595-2599). Release is the one prompt whose YES is
    reached with Up, so both readings are guarded -- a NO-default prompt confirmed with a bare A
    declines silently."""
    lua, mod, fake = machine
    lua.execute(f"""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,1); F.w8(F.pcstore+1,1)
        F.w32(0x03005090,0x0808DECD); F.w8(0x03005090+4,1)   -- Task_ReleaseMon
        F.w8(0x0203ADE4+2,{start_cursor}); F.w8(0x0203ADE4+4,1)
        F.on_tap=function(button)
            if button=='Up' and {str(honour_up).lower()} then F.w8(0x0203ADE4+2,0) end
        end
    """)
    with pytest.raises(LuaError, match="pc_release_confirmation_" + stage):
        mod.PC.release("release-cursor")


def test_pc_release_waits_for_both_trailing_messages(machine):
    """After ReleaseMon() the task walks MSG_WAS_RELEASED -> MSG_BYE_BYE before
    CompactPartySlots and the return to Task_PokeStorageMain (tasks.c:1307-1339): the release is
    not done while the bye message is still up."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,1); F.w8(F.pcstore+1,1)
        F.w32(0x03005090,0x0808DECD); F.w8(0x03005090+4,1)
        F.w8(0x0203ADE4+2,1); F.w8(0x0203ADE4+4,1)
        F.on_tap=function(button)
            if button=='Up' then F.w8(0x0203ADE4+2,0) end
            if button=='A' then F.w8(F.pcstore,4) end   -- confirmed; never reaches MSG_BYE_BYE
        end
    """)
    with pytest.raises(LuaError, match="pc_release_bye_message_missing"):
        mod.PC.release("release-bye")


def _exit_world(lua, owner=True, owner_maxc=3, cancel_result=True, field=True):
    """One exit loop, with one clause of the real sequence withheld per test case."""
    lua.execute(f"""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,0)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        F.field=false; F.b=0
        G.pred_ok=function(_,name)
            if name=='script_context_status' or name=='field_controls_locked' then return F.field end
            return true
        end
        F.on_tap=function(button)
            if button=='B' then
                F.b=F.b+1
                if F.b==1 then F.w32(0x03005090,0) end                 -- storage closes
                if F.b==2 then
                    F.w32(0x03005090,0)                                -- owner list cancelled
                    if {str(cancel_result).lower()} then F.w16(0x020370D0,127) end
                    if {str(field).lower()} then F.field=true end
                end
            end
        end
        F.on_frame=function()
            if {str(owner).lower()} and F.b==1 and memory.read_u32_le(0x03005090)==0 then
                F.w32(0x03005090,0x0809CC99); F.w8(0x0203ADE4+4,{owner_maxc})
            end
        end
    """)


@pytest.mark.parametrize("kwargs,stage", [
    ({"owner": False}, "exit_owner_list_missing"),
    ({"owner_maxc": 1}, "exit_owner_row_count"),
    ({"cancel_result": False}, "exit_owner_not_canceled"),
    ({"field": False}, "exit_not_field"),
])
def test_pc_exit_names_the_clause_it_failed(machine, kwargs, stage):
    """pc.inc:50-55 loops back to the PC main script after storage: the exit must reach the owner
    list (the multichoice pc.inc:20-25 opened), cancel it with VAR_RESULT 127, and only then be
    on the field with the script shutdown and the controls unlocked. Each clause has its own
    name, so a stuck exit says which one broke."""
    lua, mod, fake = machine
    _exit_world(lua, **kwargs)
    with pytest.raises(LuaError, match="pc_" + stage):
        mod.PC.leave(fake.cp, "exit-clause")


@pytest.mark.parametrize("task", [0x0808D2BD, 0x0808D879, 0x0808DD89,
                                  0x0808DC9D, 0x0808DECD])
def test_pc_exit_never_presses_a_while_any_storage_task_owns_input(machine, task):
    """Task_PokeStorageMain / Task_OnSelectedMon / Task_DepositMenu, and -- C3-40 finding 7 --
    Task_WithdrawMon (0x0808DC9D) and Task_ReleaseMon (0x0808DECD): while any of them is up, an
    A acts INSIDE the box (it picks the row under the cursor) instead of dismissing a message.
    The exit loop must wait them out; only the B/message-box branches may press."""
    lua, mod, fake = machine
    lua.execute(f"""
        F.pcstore=0x0202A000; F.field=false; F.a_in_box=0; F.t=0
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,1)          -- a storage task owns input
        F.w32(0x03005090,{task}); F.w8(0x03005090+4,1); F.w16(0x03005090+8,1)
        G.pred_ok=function(_,name)
            if name=='script_context_status' or name=='field_controls_locked' then return F.field end
            return true
        end
        F.on_tap=function(button)
            if button=='A' then F.a_in_box=F.a_in_box+1 end
            if button=='B' and memory.read_u32_le(0x03005090)==0x0809CC99 then
                F.w32(0x03005090,0); F.w16(0x020370D0,127); F.field=true
            end
        end
        F.on_frame=function()
            F.t=F.t+1
            if F.t==40 then F.w32(0x03005090,0x0809CC99); F.w8(0x0203ADE4+4,3) end
        end
    """)
    assert mod.PC.leave(fake.cp, "never-a") is True
    assert fake.a_in_box == 0, "the exit pressed A while a storage task owned input"


def test_route1_faint_stops_on_any_settled_faint_not_on_a_counter_increase(machine):
    """BattleStartClearSetData zeroes gBattleResults.playerFaintCounter at the start of EVERY
    battle (src/battle_main.c:2308), so a non-zero reading after a settled fight is evidence of a
    faint in that fight no matter what the value was before it. A resumed leg really can start
    with the counter already set -- that is the FR run 26 shape, a state saved while a battle was
    still resolving -- and the leg's own resume() documents taking it as evidence for exactly
    that reason. Comparing against a baseline sampled before the loop instead only ends the leg
    when the counter GROWS across the whole leg, which is the form C3-36 replaced. The fake
    therefore starts the leg with the counter already set and leaves it unchanged: the growth
    form would hunt all 20 encounters and fail."""
    lua, mod, fake = machine
    lua.globals().savestate = lua.table(save=lambda *_: True)
    lua.execute("""
        F.fights=0
        F.w8(0x03004F90,1)                        -- already non-zero when the leg starts
        F.place(3,19,12,37)                       -- on the pinned grass square
        D.play.step=function() return false,'in_battle' end
        D.play.fight_through=function() F.fights=F.fights+1; return true end
        D.play.in_battle=function() return false end
        D.play.wait_scene_settled=function() return true end
        D.play.on_field=function() return true end
    """)
    leg(mod, "route1_faint").run(fake.cp)
    assert fake.fights == 1, "a settled fight with the counter set must end the leg"


def test_route1_faint_reports_a_counter_that_never_advanced(machine):
    """The other half of the same contract: with no faint recorded the leg keeps hunting, and
    after the 20th encounter it names the risk instead of reporting a fake PASS (FR run 26)."""
    lua, mod, fake = machine
    lua.globals().savestate = lua.table(save=lambda *_: True)
    lua.execute("""
        F.fights=0
        F.place(3,19,12,37)
        D.play.step=function() return false,'in_battle' end
        D.play.fight_through=function() F.fights=F.fights+1; return true end
        D.play.in_battle=function() return false end
        D.play.wait_scene_settled=function() return true end
        D.play.on_field=function() return true end
    """)
    with pytest.raises(LuaError, match="playerFaintCounter never advanced"):
        leg(mod, "route1_faint").run(fake.cp)
    assert fake.fights == 20, "the leg must keep hunting until its encounter budget runs out"


# ── C3-41: the PC stage checks that fire when a witness never appears ─────────────────────────
# C3-40 witnessed what each guard does when the world misbehaves in a specific way; these are the
# remaining named failures whose trigger is a witness that never shows up or never advances. Each
# test puts the flow in front of the real PC.* function with exactly that missing witness and
# asserts the ONE name, so deleting the guard turns its test red (before/after matrix in the
# C3-41 receipt). No emulator, no ROM, no screenshots: fake RAM against the real functions.


def test_pc_open_reports_an_interaction_that_never_started(machine):
    """No menu and an IDLE script context: the A that was meant to boot the PC did nothing (the
    player was not facing the metatile, or a script owned the press). The retry loop's own
    witness -- the script context going busy -- is what says the interaction started."""
    lua, mod, fake = machine
    with pytest.raises(LuaError, match="pc_interaction_not_started"):
        mod.PC.open(fake.cp, "no-interaction")


def test_pc_open_reports_no_menu_after_the_retry_budget(machine):
    """The other side of the same loop: the script keeps looking busy for every retry and still
    no PC menu ever appears, so the loop runs out with nothing to drive."""
    lua, mod, fake = machine
    lua.execute("""
        G.pred_ok=function(_,name)
            if name=='script_context_status' then return false end
            return true
        end
    """)
    with pytest.raises(LuaError, match="pc_which_pc_menu_missing"):
        mod.PC.open(fake.cp, "no-menu")


def test_pc_open_reports_a_choice_consumed_without_the_top_menu(machine):
    """"Which PC should be accessed?" is consumed and the script moves on -- but no
    Task_PCMainMenu appears, so there is no storage menu to drive. read through VAR_RESULT zero
    (a real choice leaves 127 only on the owner-list cancel), then require the top menu."""
    lua, mod, fake = machine
    lua.execute("""
        F.w32(0x03005090,0x0809CC99); F.w8(0x03005090+4,1)   -- Task_MultichoiceMenu_HandleInput
        F.w8(0x0203ADE4+2,0); F.w8(0x0203ADE4+4,3)           -- row 0, four owner rows
        F.on_tap=function(button)
            if button=='A' then
                F.w32(0x03005090,0)                          -- the choice is consumed
                F.w16(0x020370D0,0)                          -- and this visit wrote row 0
            end
        end
    """)
    with pytest.raises(LuaError, match="pc_storage_top_menu_missing"):
        mod.PC.open(fake.cp, "no-top-menu")


@pytest.mark.parametrize("pointer,task", [(0x0202A000, None),
                                          (0x12345678, 0x0808DD89)])
def test_pc_box_reports_a_missing_chooser(machine, pointer, task):
    """Choose the destination box: either the deposit menu task (and so its box chooser) is not
    up at all, or gStorage is not a readable EWRAM pointer -- both leave the stage with nothing
    to choose in, and the guard covers both disjuncts."""
    lua, mod, fake = machine
    fake.w32(0x020397B0, pointer)
    if task is not None:
        fake.w32(0x03005090, task)
        fake.w8(0x03005090 + 4, 1)
    with pytest.raises(LuaError, match="pc_box_chooser_missing"):
        mod.PC.box("no-chooser")


def test_pc_box_reports_a_choice_that_handed_the_box_to_another_task(machine):
    """The chooser's A is accepted and then the deposit menu is GONE -- a different task owns the
    screen, so the box this leg chose is not the box on display. TryStorePartyMonInBox never
    fired, and returning success here would read someone else's box."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,1)
        F.w32(0x03005090,0x0808DD89); F.w8(0x03005090+4,1)   -- Task_DepositMenu, ready
        F.w8(0x020397B6,0)
        F.on_tap=function(button)
            if button=='A' then F.w32(0x03005090,0) end       -- the chooser disappears
        end
    """)
    with pytest.raises(LuaError, match="pc_box_deposit_wrong_task"):
        mod.PC.box("wrong-task")


def test_pc_box_reports_a_deposit_that_never_committed(machine):
    """The chooser stays up on box 0 and its A never moves anything: the leg retries a bounded
    number of times, then reports the deposit as not committed instead of walking away from a
    mon that is still in the party."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,1)
        F.w32(0x03005090,0x0808DD89); F.w8(0x03005090+4,1)
        F.w8(0x020397B6,0)
    """)
    with pytest.raises(LuaError, match="pc_box_deposit_not_committed"):
        mod.PC.box("no-commit")


def test_pc_mode_reports_storage_never_entered(machine):
    """A on DEPOSIT is accepted but Task_PokeStorageMain never appears while the top menu stays up
    and ready on the same row, so every retry sees the same menu. Entering the mode is the
    witness the whole stage rests on."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,0); F.w8(F.pcstore+1,1)
        F.w32(0x03005090,0x0808C39D); F.w8(0x03005090+4,1)
        F.w16(0x03005090+8,2); F.w16(0x03005090+10,1)  -- already on DEPOSIT, ready
        F.w8(0x0203ADE4+4,4)
    """)
    with pytest.raises(LuaError, match="pc_storage_mode_not_entered"):
        mod.PC.mode("no-storage", 1)


def test_pc_popup_reports_another_task_taking_over_the_popup(machine):
    """The A that opens the selected-mon popup is accepted, then the box task itself disappears
    and Task_OnSelectedMon never appears: something else owns the screen, so this stage must not
    keep pressing A into it."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,0); F.w8(F.pcstore+1,1)
        F.w8(0x02039820,1); F.w8(0x02039821,1)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        F.dropping=false; F.t=0
        F.on_tap=function(button)
            if button=='A' then F.dropping=true end
        end
        F.on_frame=function()
            if F.dropping then
                F.t=F.t+1
                if F.t==10 then F.w32(0x03005090,0) end   -- the box task goes away
            end
        end
    """)
    with pytest.raises(LuaError, match="pc_storage_popup_unexpected_task"):
        mod.PC.popup("took-over", 1, 1, 0)


def test_pc_select_reports_a_choice_that_started_the_wrong_task(machine):
    """Pressing A on the popup does leave Task_OnSelectedMon behind -- but starts some OTHER
    task instead of the one this stage asked for (WITHDRAW/DEPOSIT/RELEASE). The call must fail
    rather than report a transfer that never ran."""
    lua, mod, fake = machine
    lua.execute("""
        F.w32(0x03005090,0x0808D879); F.w8(0x03005090+4,1)   -- Task_OnSelectedMon
        F.on_tap=function(button)
            if button=='A' then F.w32(0x03005090,0x0808D2BD) end -- back to the box, not the asked task
        end
    """)
    with pytest.raises(LuaError, match="pc_storage_choice_wrong_task"):
        mod.PC.select("wrong-task", 0x0808DD89)


def test_pc_select_reports_a_choice_never_taken(machine):
    """The popup stays up through every bounded retry and the asked-for task never starts: the
    stage ends by naming the choice it could not take."""
    lua, mod, fake = machine
    fake.w32(0x03005090, 0x0808D879)
    fake.w8(0x03005090 + 4, 1)
    with pytest.raises(LuaError, match="pc_storage_choice_not_taken"):
        mod.PC.select("never-taken", 0x0808DD89)


def test_pc_cursor_reports_a_cursor_that_rolls_past_the_row(machine):
    """The cursor keeps MOVING (every press is accepted) but rolls around the box's occupied slots
    and never lands on the requested row: after the bounded search the stage must fail instead of
    selecting whatever row it happens to be on."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        F.w8(0x02039820,1); F.w8(0x02039821,0)
        F.on_tap=function(button)
            if button=='Down' then F.w8(0x02039821,(F.r8(0x02039821)+1)%4) end -- 0..3, never 4
        end
    """)
    with pytest.raises(LuaError, match="pc_storage_cursor_stalled"):
        mod.PC.cursor("rolling", 1, 4)


def test_pc_cursor_reports_a_cursor_that_never_moves(machine):
    """The stuck read: the position byte does not change on a press, so the wait for movement
    itself is the witness that fails -- the same name as the search's end, which is why the
    press COUNT is asserted too. One press and then the failure is the guard's whole point: a
    second press into a box whose cursor reads stale is input the driver must not send. With the
    wait removed the loop presses again (8 times before the same name), so the count is the only
    signature this guard has."""
    lua, mod, fake = machine
    lua.execute("""
        F.downs=0
        F.on_tap=function(button) if button=='Down' then F.downs=F.downs+1 end end
    """)
    fake.w32(0x020397B0, 0x0202A000)
    fake.w32(0x03005090, 0x0808D2BD)
    fake.w8(0x03005090 + 4, 1)
    fake.w8(0x02039820, 1)
    fake.w8(0x02039821, 0)
    with pytest.raises(LuaError, match="pc_storage_cursor_stalled"):
        mod.PC.cursor("stuck", 1, 3)
    assert fake.downs == 1, "a stuck cursor read must not be pressed at again"


def test_pc_popup_reports_a_popup_cursor_that_never_moves(machine):
    """The popup read never advances on a press, so the cursor wait is the witness that fails --
    the same name as the search's end, so the press COUNT is asserted as well: one Down and then
    the failure, where removing the wait presses 4 times into the popup before the same name."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000; F.downs=0
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,2); F.w8(F.pcstore+1,1)
        F.w8(0x02039820,1); F.w8(0x02039821,1)
        F.w8(0x0203ADE4+2,0); F.w8(0x0203ADE4+4,4)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        F.on_tap=function(button)
            if button=='A' then F.w32(0x03005090,0x0808D879) end
            if button=='Down' then F.downs=F.downs+1 end
        end
    """)
    with pytest.raises(LuaError, match="pc_storage_popup_cursor_stalled"):
        mod.PC.popup("stuck-popup", 1, 1, 3)
    assert fake.downs == 1, "a stuck popup cursor must not be pressed at again"


@pytest.mark.parametrize("pointer,task", [(0x0202A000, None),
                                          (0x12345678, 0x0808DECD)])
def test_pc_release_reports_a_missing_confirmation(machine, pointer, task):
    """Task_ReleaseMon (or a readable gStorage) is what the confirmation prompt lives in: with
    either one missing there is no yes/no box up, and reading a cursor out of a menu that is not
    there is how a release gets confirmed by accident."""
    lua, mod, fake = machine
    fake.w32(0x020397B0, pointer)
    if task is not None:
        fake.w32(0x03005090, task)
        fake.w8(0x03005090 + 4, 1)
    with pytest.raises(LuaError, match="pc_release_confirmation_missing"):
        mod.PC.release("no-confirmation")


# ── C3-42: the popup's row walk reaches every row, and the area -> option mapping is pinned ───


@pytest.mark.parametrize("row,presses", [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)])
def test_pc_popup_reaches_every_row_inside_its_budget(machine, row, presses):
    """STORE / SUMMARY / MARK / RELEASE / CANCEL is rows 0..4 and PC_MENU_MAX_CURSOR reads 4
    (SetMenuTextsForMon's shared tail, pokemon_storage_system_data.c:1755-1805). The walk tests
    the cursor BEFORE each Down, so a budget of maxCursor presses presses four times and never
    tests row 4: the popup sits on CANCEL while the leg reports pc_storage_popup_cursor_stalled,
    one press short (C3-41 finding 2; fixed in C3-42 by walking max_row + 1). Revert-tested: with
    the bound back at 4, the row-4 case fails with exactly that name and rows 0..3 still pass."""
    lua, mod, fake = machine
    lua.execute("""
        F.pcstore=0x0202A000; F.downs=0
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,0); F.w8(F.pcstore+1,1)
        F.w8(0x02039820,1); F.w8(0x02039821,1)              -- the party-area storage cursor
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)  -- Task_PokeStorageMain
        F.on_tap=function(button)
            if button=='A' then
                F.w32(0x03005090,0x0808D879)                -- Task_OnSelectedMon: the popup opens
                F.w8(F.pcstore,2)
                F.w8(0x0203ADE4+2,0); F.w8(0x0203ADE4+4,4)  -- on STORE, five rows
            end
            if button=='Down' then
                F.downs=F.downs+1
                F.w8(0x0203ADE4+2,F.r8(0x0203ADE4+2)+1)     -- one row per press
            end
        end
    """)
    assert mod.PC.popup("row-walk", 1, 1, row) is True
    assert fake.downs == presses, "each row is one press from the one above it"


@pytest.mark.parametrize("area,option,accepted", [
    (0, 0, True),   # CURSOR_AREA_IN_BOX   -> OPTION_WITHDRAW
    (1, 1, True),   # CURSOR_AREA_IN_PARTY -> OPTION_DEPOSIT
    (0, 1, False),  # a box-area popup does not offer the deposit option
    (1, 2, False),  # ... nor does a party-area popup offer OPTION_MOVE_MONS
    (2, 2, False),  # 2 is not a CURSOR_AREA value at all
])
def test_pc_popup_requires_the_option_its_cursor_area_implies(machine, area, option, accepted):
    """Two enums mapped, not compared: gStorage->boxOption is OPTION_WITHDRAW 0 / OPTION_DEPOSIT 1
    / OPTION_MOVE_MONS 2 (include/pokemon_storage_system_internal.h:17-24) while the cursor area is
    CURSOR_AREA_IN_BOX 0 / CURSOR_AREA_IN_PARTY 1 (:108-115) -- they merely share 0/1. The
    driver's PC_POPUP_OPTION encodes IN_BOX -> WITHDRAW and IN_PARTY -> DEPOSIT; it is a file-local
    table, so the mapping is pinned here through its observable effect: the two positive rows drive
    a real popup to completion, and the rest are refusals. Area 2 is included because pret defines
    no such area -- the lookup yields nil and must still fail BY NAME rather than compare against
    nothing."""
    lua, mod, fake = machine
    lua.execute(f"""
        F.pcstore=0x0202A000
        F.w32(0x020397B0,F.pcstore); F.w8(F.pcstore,0); F.w8(F.pcstore+1,{option})
        F.w8(0x02039820,{area}); F.w8(0x02039821,1)
        F.w32(0x03005090,0x0808D2BD); F.w8(0x03005090+4,1)
        F.on_tap=function(button)
            if button=='A' then
                F.w32(0x03005090,0x0808D879)
                F.w8(F.pcstore,2); F.w8(0x0203ADE4+2,0); F.w8(0x0203ADE4+4,4)
            end
        end
    """)
    if accepted:
        assert mod.PC.popup("mapped", area, 1, 0) is True
    else:
        with pytest.raises(LuaError, match="pc_storage_popup_wrong_mode"):
            mod.PC.popup("mismatched", area, 1, 0)
