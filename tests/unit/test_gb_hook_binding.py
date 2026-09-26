"""Explicit GB bank/PC/domain binding; no game event semantics."""
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def setup():
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")((ROOT / "lua/gb_hook_binding.lua").as_posix())
    state, io, config, site = lua.eval("""function()
        local state={bank=2,pc=0x4101,sp=0xdffe,frame=18,bad_rom=false,bad_bus=false}
        local io={
            read_u8=function(a,d) assert(a==0xff80 and d=='bus');return state.bank end,
            read_range=function(a,n,d)
                assert(n==2)
                assert((d=='rom' and a==0x8100) or (d=='bus' and a==0x4100))
                return {0x3e,(d=='rom' and state.bad_rom or d=='bus' and state.bad_bus) and 2 or 1}
            end,
            register=function(n) return n=='PC' and state.pc or state.sp end,
            framecount=function() return state.frame end,
            on_bus_exec=function(fn,a,name,d) state.registration={fn=fn,address=a,name=name,domain=d};return 'real-id' end,
            unregister=function(id) state.removed=id;return true end,
        }
        return state,io,{bus_domain='bus',rom_domain='rom',bank_domain='bus',bank_address=0xff80,
                        pc_register='PC',sp_register='SP'},
                       {id='sample',bank=2,address=0x4100,capture_offset=1,rom_offset=0x8100,expected_hex='3E01'}
    end""")()
    return lua, module, state, io, config, site


def test_explicit_binding_checks_both_domains_and_registers_the_validated_pc():
    lua, module, state, io, config, site = setup()
    binding = module.new(io, config)
    prepared = binding.validate(binding, site)
    context = binding.context(binding, prepared)
    assert (context.pc, context.bank, context.sp, context.frame) == (0x4101, 2, 0xDFFE, 18)
    assert binding.register(binding, prepared, lua.eval("function() end"), "owner:sample") == "real-id"
    assert state.registration.address == 0x4101 and state.registration.domain == "bus"


def test_wrong_bank_is_dropped_but_wrong_pc_or_live_bytes_are_errors():
    _lua, module, state, io, config, site = setup()
    binding = module.new(io, config)
    prepared = binding.validate(binding, site)
    state.bank = 3
    assert binding.context(binding, prepared) is None
    state.bank, state.pc = 2, 0x4102
    with pytest.raises(LuaError, match="callback PC differs"):
        binding.context(binding, prepared)
    state.pc, state.bad_bus = 0x4101, True
    with pytest.raises(LuaError, match="bank/bytes"):
        binding.context(binding, prepared)


@pytest.mark.parametrize("field,value", [("rom_offset", 0x4100), ("address", 0x8100),
                                         ("capture_offset", 2), ("expected_hex", "0G"), ("bank", 0),
                                         ("bank", 256)])
def test_malformed_or_contradictory_site_refuses(field, value):
    _lua, module, _state, io, config, site = setup()
    binding = module.new(io, config)
    site[field] = value
    with pytest.raises(LuaError):
        binding.validate(binding, site)


def test_no_config_defaults_and_zero_guid_is_not_a_handle():
    _lua, module, state, io, config, site = setup()
    config.bank_address = None
    with pytest.raises(LuaError):
        module.new(io, config)
    _lua, module, state, io, config, site = setup()
    binding = module.new(io, config)
    for invalid in (False, 0, "", "{00000000-0000-0000-0000-000000000000}"):
        assert binding.valid_handle(binding, invalid) is False
    state.bad_rom = True
    with pytest.raises(LuaError, match="ROM"):
        binding.validate(binding, site)


def test_accept_runs_after_the_bank_match_and_before_the_pc_and_byte_checks():
    lua, module, state, io, config, site = setup()
    binding = module.new(io, config)
    prepared = binding.validate(binding, site)
    calls = []
    reject = lambda: calls.append("accept") or False
    state.bank = 3
    assert binding.context(binding, prepared, reject) is None and calls == []
    state.bank, state.pc = 2, 0x4102
    assert binding.context(binding, prepared, reject) is None and calls == ["accept"]
    with pytest.raises(LuaError, match="callback PC differs"):
        binding.context(binding, prepared, lambda: True)


def test_a_throwing_accept_drops_that_hit_records_the_error_and_later_hits_still_run():
    lua, module, state, io, config, site = setup()
    binding = module.new(io, config)
    prepared = binding.validate(binding, site)
    assert binding.status(binding).accept_errors == 0
    boom = lua.eval("function() error('F register unavailable') end")
    assert binding.context(binding, prepared, boom) is None
    status = binding.status(binding)
    assert status.accept_errors == 1 and "F register unavailable" in status.accept_error
    context = binding.context(binding, prepared, lambda: True)
    assert context.pc == 0x4101
