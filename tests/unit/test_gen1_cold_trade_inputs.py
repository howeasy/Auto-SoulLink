"""Source-shaped input planner tests; no emulator state mutation APIs exist here."""

from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def route(variant='yellow', initiator=True):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.globals().variant = variant
    lua.globals().initiator = initiator
    lua.execute('''
        Driver=dofile(root..'/lua/tests/gen1_cold_trade_inputs.lua')
        driver=Driver.new({variant=variant,initiator=initiator,max_frames=1000})
        point={frame=100,map=0x26,x=3,y=6,battle=0,joy_ignore=0,party_count=0,
            naming_screen=1,safe=true,starter=false,menu={}}
        progress={enrolled=true,bootstrap=true,saved=true,linked=false,both_at_center=false}
        function tick()point.frame=point.frame+1;return driver:buttons(point,progress)end
    ''')
    return lua


def test_handshake_gates_inputs_and_polling_does_not_advance_route_time():
    lua = route()
    lua.execute('''
        progress.saved=false
        local buttons,phase=driver:buttons(point,progress)
        assert(phase=='waiting_enrollment'and not buttons.Right)
        progress.saved=true;buttons,phase=driver:buttons(point,progress)
        assert(phase=='bedroom_stairs'and buttons.Right)
        for _=1,100 do local current=driver:buttons(point,progress);assert(current.Right)end
        assert(#driver:status().transitions==1)
    ''')


@pytest.mark.parametrize('variant,x', [('red', 6), ('blue', 6), ('yellow', 7)])
def test_native_starter_selection_turns_toward_source_ball_then_pulses_a(variant, x):
    lua = route(variant)
    lua.globals().point['map'] = 0x28
    lua.globals().point['x'] = x
    lua.globals().point['y'] = 4
    lua.execute('''
        local buttons,phase=driver:buttons(point,progress)
        assert(phase=='choose_starter'and buttons.Up)
        point.frame=112;buttons=driver:buttons(point,progress);assert(buttons.A and not buttons.Up)
    ''')


def test_yellow_starter_route_uses_south_aisle_before_crossing_table():
    lua = route()
    lua.execute('''
        point.map=0x28;point.x=5;point.y=3
        local buttons=driver:buttons(point,progress);assert(buttons.Down and not buttons.Right)
        point.y=4;buttons=tick();assert(buttons.Right)
        point.x=7;buttons=tick();assert(buttons.Up)
    ''')


def test_nickname_decline_and_preball_rival_use_real_menu_buttons_only():
    lua = route()
    lua.execute('''
        point.map=0x28;point.party_count=1;point.naming_screen=2;point.safe=false
        point.menu={top_x=15,top_y=8,maximum=1,index=0};point.frame=112
        local buttons,phase=driver:buttons(point,progress)
        assert(phase=='starter_nickname'and buttons.B and not buttons.A)
        point.frame=128;point.battle=2;point.starter=true
        buttons,phase=driver:buttons(point,progress)
        assert(phase=='rival_battle'and buttons.A)
    ''')


def test_wild_run_menu_uses_observed_column_and_row():
    lua = route()
    lua.execute('''
        point.map=0x0c;point.battle=1;point.menu={top_y=14,top_x=9,maximum=1,index=0}
        local buttons=driver:buttons(point,progress);assert(buttons.Right)
        point.menu.top_x=15;buttons=tick();assert(buttons.Down)
        point.menu.index=1;point.frame=112;buttons=driver:buttons(point,progress);assert(buttons.A)
    ''')


@pytest.mark.parametrize('initiator', [False, True])
def test_center_staging_waits_for_pair_and_only_initiator_interacts(initiator):
    lua = route(initiator=initiator)
    lua.execute('''
        point.map=0x29;point.x=3;point.y=7;point.starter=true;point.party_count=1
        local buttons=driver:buttons(point,progress);assert(buttons.Up)
        point.y=6;tick();point.x=11;tick();point.y=3;tick();tick()
        assert(driver:status().center_ready and driver:status().phase=='center_ready')
        progress.linked=true;progress.both_at_center=true
        buttons=driver:buttons(point,progress)
        assert(buttons.Up==initiator)
        point.frame=128;buttons=driver:buttons(point,progress);assert(buttons.A==initiator)
        progress.native_borrowed=true;buttons=driver:buttons(point,progress);assert(buttons.A and not buttons.Up)
    ''')


def test_unknown_map_and_exhausted_frame_budget_refuse_without_fabricating_progress():
    lua = route()
    lua.execute('driver:buttons(point,progress);point.frame=1200')
    with pytest.raises(LuaError, match='budget'):
        lua.execute('driver:buttons(point,progress)')
    lua = route()
    lua.globals().point['map'] = 0x99
    with pytest.raises(LuaError, match='unplanned map'):
        lua.execute('driver:buttons(point,progress)')


def test_driver_can_execute_without_any_memory_or_emulator_api():
    lua = route()
    lua.execute('''
        assert(memory==nil and emu==nil and joypad==nil)
        for i=1,80 do point.frame=100+i;driver:buttons(point,progress)end
        assert(point.map==0x26 and point.x==3 and point.y==6 and point.party_count==0)
    ''')


def test_warp_map_change_cannot_seed_navigation_from_unsettled_coordinates():
    lua = route()
    lua.execute('''
        point.map=0x29;point.x=23;point.y=25;point.safe=false
        driver:buttons(point,progress)
        point.safe=true;point.x=3;point.y=7;local buttons=tick()
        assert(buttons.Up and not buttons.Right and not buttons.Left)
    ''')


def test_unsafe_cpu_boundary_alone_does_not_mash_a_into_furniture():
    lua = route()
    lua.execute('''
        point.safe=false;point.frame=112
        local buttons,phase=driver:buttons(point,progress)
        assert(phase=='waiting_world_boundary'and not buttons.A)
        point.text_active=true;point.frame=128
        buttons,phase=driver:buttons(point,progress)
        assert(phase=='script_text'and buttons.A)
    ''')


def test_yellow_oak_tutorial_never_selects_run_or_an_item():
    lua = route()
    lua.execute('''
        point.map=0;point.battle=1;point.battle_type=4;point.frame=112
        point.menu={top_y=14,top_x=9,maximum=1,index=0}
        local buttons,phase=driver:buttons(point,progress)
        assert(phase=='oak_tutorial'and buttons.A and not buttons.Right and not buttons.Down)
    ''')
