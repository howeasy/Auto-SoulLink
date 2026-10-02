"""NDS bus-exec binding: residency drop, pins, fire-word latch, unsigned normalisation.

Fake io/event objects; the real pack rows (data/games/gen4_hgss) supply sites and the overlay table.
"""
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "ARM9 System Bus"
PACK = json.loads((ROOT / "data/games/gen4_hgss/profile.json").read_text("utf-8"))["titles"]["heartgold"]

WORLD = """
local DOMAIN, TABLE = ...
local st={mem={},pc=0,frame=7,regs={},serial=0,fail_remove=false,bad_register=nil}
local function b(a) return st.mem[a] or 0 end
local io={
    read_u32=function(a,d) assert(d==DOMAIN,'domain') return b(a)|b(a+1)<<8|b(a+2)<<16|b(a+3)<<24 end,
    read_range=function(a,n,d) assert(d==DOMAIN,'domain') local t={} for i=1,n do t[i]=b(a+i-1) end return t end,
    register=function(n) assert(n=='ARM9 r15','register name') return st.pc end,
    framecount=function() return st.frame end,
    on_bus_exec=function(fn,a,name,d)
        assert(d==DOMAIN,'domain')
        st.serial=st.serial+1
        if name==st.bad_register then return '00000000-0000-0000-0000-000000000000' end
        local id='{g-'..st.serial..'}'
        st.regs[id]={fn=fn,address=a,name=name}
        return id
    end,
    unregister=function(id)
        if st.fail_remove then return false end
        st.regs[id]=nil
        return true
    end,
}
function st.put(a,hex) for i=1,#hex,2 do st.mem[a+(i-1)//2]=tonumber(hex:sub(i,i+1),16) end end
function st.put_u32(a,v) for i=0,3 do st.mem[a+i]=(v>>(8*i))&255 end end
-- sOverlayRegions[MAIN][slot] = {id, active}
function st.slot(slot,id,active) st.put_u32(TABLE.address+slot*8,id); st.put_u32(TABLE.address+slot*8+4,active) end
function st.count() local n=0 for _ in pairs(st.regs) do n=n+1 end return n end
function st.fire(address,val)
    local ids={} for id,r in pairs(st.regs) do if r.address==address then ids[#ids+1]=id end end
    table.sort(ids)
    for _,id in ipairs(ids) do st.regs[id].fn(address,val,0) end
end
st.io=io
return st
"""


def to_lua(lua, value):
    if isinstance(value, dict):
        return lua.table_from({k: to_lua(lua, v) for k, v in value.items() if v is not None})
    if isinstance(value, list):
        return lua.table_from([to_lua(lua, v) for v in value])
    return value


class Env:
    def __init__(self, cfg=None):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.table = to_lua(self.lua, PACK["overlay_table"])
        self.st = self.lua.execute(WORLD, DOMAIN, self.table)
        self.NDS = self.lua.eval("dofile")((ROOT / "lua/nds/hook_binding.lua").as_posix())
        self.cfg = to_lua(self.lua, {
            "bus_domain": DOMAIN, "pc_register": "ARM9 r15", "pc_offset": {"thumb": 4, "arm": 8},
            "overlay_table": PACK["overlay_table"], "overlays": PACK["overlays"], **(cfg or {})})
        self.binding = self.NDS.new(self.st.io, self.cfg)

    def site(self, name):
        site = to_lua(self.lua, {**PACK["sites"][name], "id": name})
        return site

    def load(self, *names):
        """Put the pack's registration bytes in the fake memory."""
        for n in names:
            s = PACK["sites"][n]
            self.st.put(s["address"], s["register_hex"])

    def resident(self, *ovys):
        for slot in range(8):
            self.st.slot(slot, 0, 0)
        for slot, ovy in enumerate(ovys):
            self.st.slot(slot, ovy, 1)

    def hit(self, site, val, pc=None, accept=None, address=None):
        """Register through the binding, fire once; return (context, error)."""
        out = self.lua.eval("{}")
        binding = self.binding

        def callback(addr, v, flags):
            try:
                out["ctx"] = binding.context(binding, site, accept)
            except LuaError as e:
                out["err"] = str(e)

        self.st.pc = site["pc"] if pc is None else pc
        handle = binding.register(binding, site, callback, "t:" + site["id"])
        self.st.fire(site["address"] if address is None else site["address"], val)
        binding.unregister(binding, handle)
        return out["ctx"], out["err"]


def test_real_pack_site_fires_with_owning_overlay_resident():
    env = Env()
    env.load("battle_start_ov12")
    env.resident(12)
    site = env.binding.validate(env.binding, env.site("battle_start_ov12"))
    assert site["pc"] == site["address"] + 4 and site["fire"] == 0xB092B5F8
    ctx, err = env.hit(site, 0xB092B5F8)
    assert err is None and ctx["pc"] == site["pc"] and ctx["word"] == 0xB092B5F8 and ctx["frame"] == 7


def test_wrong_overlay_hit_is_dropped_even_with_foreign_bytes():
    env = Env()
    env.load("battle_start_ov12")
    env.resident(12)
    site = env.binding.validate(env.binding, env.site("battle_start_ov12"))
    env.resident(13)  # ov13 now owns the shared RAM; its code is not the site's fire word
    ctx, err = env.hit(site, 0x12345678, pc=0)
    assert ctx is None and err is None
    env.resident()  # nothing resident
    assert env.hit(site, 0x12345678)[1] is None


def test_active_overlay_fire_word_mismatch_latches_never_drops():
    env = Env()
    env.load("battle_start_ov12")
    env.resident(12)
    site = env.binding.validate(env.binding, env.site("battle_start_ov12"))
    ctx, err = env.hit(site, 0x12345678)
    assert ctx is None and "fire word differs" in err
    ctx, err = env.hit(site, 0xB092B5F8, pc=site["pc"] + 2)
    assert ctx is None and "callback PC differs" in err


def test_negative_signed_callback_word_is_normalised_to_unsigned():
    env = Env()
    env.load("battle_start_ov12")
    env.resident(12)
    site = env.binding.validate(env.binding, env.site("battle_start_ov12"))
    signed = 0xB092B5F8 - (1 << 32)
    assert signed < 0
    ctx, err = env.hit(site, signed)
    assert err is None and ctx["word"] == 0xB092B5F8
    assert "u32" in env.hit(site, 1 << 33)[1]


def test_static_arm9_pin_mismatch_refused_at_validation():
    env = Env()
    env.load("party_add_mon")
    s = PACK["sites"]["party_add_mon"]
    env.st.put(s["address"] + 9, "ff")  # byte outside the 4-byte fire word: only the full pin sees it
    with pytest.raises(LuaError, match="full registration pin mismatch"):
        env.binding.validate(env.binding, env.site("party_add_mon"))
    env.load("party_add_mon")
    prepared = env.binding.validate(env.binding, env.site("party_add_mon"))
    assert prepared["image"] == "arm9"
    ctx, err = env.hit(prepared, int(s["fire_hex"], 16))  # static: no residency gate
    assert err is None and ctx["overlay_id"] is None


def test_overlay_site_refuses_until_resident_and_full_pin_matches():
    env = Env()
    env.resident()  # ov12 absent: bytes are another overlay's, nothing to compare
    env.st.put(PACK["sites"]["battle_start_ov12"]["address"], "00" * 16)
    with pytest.raises(LuaError, match="nds-refused:not_resident:battle_start_ov12"):
        env.binding.validate(env.binding, env.site("battle_start_ov12"))
    env.resident(12)  # resident with the wrong bytes: refused before arming
    with pytest.raises(LuaError, match="nds-refused:pin_mismatch:battle_start_ov12"):
        env.binding.validate(env.binding, env.site("battle_start_ov12"))
    env.load("battle_start_ov12")
    env.binding.validate(env.binding, env.site("battle_start_ov12"))


def test_residency_reader_needs_active_and_id():
    env = Env()
    env.resident()
    env.st.slot(5, 12, 0)  # id present, inactive
    assert env.NDS.resident(env.st.io, env.table, 12, DOMAIN) is False
    env.st.slot(6, 12, 1)
    assert env.NDS.resident(env.st.io, env.table, 12, DOMAIN) is True
    assert env.NDS.resident(env.st.io, env.table, 13, DOMAIN) is False


@pytest.mark.parametrize("field,value,message", [
    ("fire_hex", "b092b5f9", "pin disagreement"),
    ("register_hex", "f8b592b0", "full registration extent"),
    ("address", PACK["sites"]["battle_start_ov12"]["address"] + 0x200000, "outside its overlay"),
    ("image", "ov13", "declared overlay identity"),
    ("mode", "arm", "alignment"),
    ("phase", "", "phase"),
])
def test_validation_refuses_bad_descriptors(field, value, message):
    env = Env()
    env.load("battle_start_ov12")
    env.resident()
    row = {**PACK["sites"]["battle_start_ov12"], "id": "x", field: value}
    if field == "mode":
        row["address"] += 2
    with pytest.raises(LuaError, match=message):
        env.binding.validate(env.binding, to_lua(env.lua, row))


def test_accept_filter_runs_before_pc_and_a_throwing_accept_is_a_counted_drop():
    env = Env()
    env.load("battle_start_ov12")
    env.resident(12)
    site = env.binding.validate(env.binding, env.site("battle_start_ov12"))
    never = env.lua.eval("function() return false end")
    assert env.hit(site, 0, pc=0, accept=never) == (None, None)  # filter drop beats PC/word asserts
    boom = env.lua.eval("function() error('nope') end")
    assert env.hit(site, 0, accept=boom) == (None, None)
    status = env.binding.status(env.binding)
    assert status["accept_errors"] == 1 and "nope" in status["accept_error"]


def test_register_uses_site_address_domain_and_context_requires_a_callback():
    env = Env()
    env.load("battle_start_ov12")
    env.resident(12)
    site = env.binding.validate(env.binding, env.site("battle_start_ov12"))
    handle = env.binding.register(env.binding, site, env.lua.eval("function() end"), "n")
    reg = env.st.regs[handle]
    assert reg["address"] == site["address"] and reg["name"] == "n"
    assert env.binding.valid_handle(env.binding, handle) is True
    assert env.binding.valid_handle(env.binding, "{00000000-0000-0000-0000-000000000000}") is False
    with pytest.raises(LuaError, match="outside a bus-exec callback"):
        env.binding.context(env.binding, site, None)


@pytest.mark.parametrize("drop", ["bus_domain", "pc_register", "pc_offset", "overlay_table", "overlays"])
def test_no_defaults_every_fact_is_explicit(drop):
    env = Env()
    cfg = to_lua(env.lua, {"bus_domain": DOMAIN, "pc_register": "ARM9 r15", "pc_offset": {"thumb": 4, "arm": 8},
                           "overlay_table": PACK["overlay_table"], "overlays": PACK["overlays"]})
    cfg[drop] = None
    with pytest.raises(LuaError, match="explicit"):
        env.NDS.new(env.st.io, cfg)


def test_strategy_covers_all_regions_and_epoch_is_only_the_current_main_view():
    env = Env()
    strategy = env.lua.eval("""function(fn)
        for i=1,20 do local name,value=debug.getupvalue(fn,i)
            if name=='strategy' then return value end
        end
        error('private strategy missing')
    end""")(env.binding.resident)
    env.st.slot(9, 12, 1)  # region 1, not MAIN
    rows = strategy.entries(env.st.io.read_u32)
    assert len(rows) == 24 and rows[10]["region"] == 1 and rows[10]["active"] is True
    assert strategy.resident(12) is False and strategy.resident(-1) is False
    with pytest.raises(LuaError, match="overlay id"):
        env.binding.resident(env.binding, -1)  # preserve the public API's malformed-ID hard fault
    before = strategy.epoch()
    assert strategy.epoch() == before
    env.st.slot(7, 12, 1)
    assert strategy.epoch() != before and strategy.resident(12) is True
    env.st.slot(7, 0, 0)
    assert strategy.epoch() == before  # explicitly NOT a persistent reset identity


def test_arm_refuses_epoch_change_between_decision_and_contract_check():
    env = Env()
    env.load("battle_start_ov12")
    env.resident(12)
    original = env.st.io.read_u32
    count = 0
    def changing(address, domain):
        nonlocal count
        count += 1
        if count == 17:  # after the first bounded MAIN fold, before may_arm's fold
            env.st.slot(7, 33, 1)
        return original(address, domain)
    env.st.io.read_u32 = changing
    with pytest.raises(LuaError, match="nds-refused:stale_epoch"):
        env.binding.validate(env.binding, env.site("battle_start_ov12"))
    env.st.io.read_u32 = original
    assert env.binding.validate(env.binding, env.site("battle_start_ov12"))


def test_accept_and_residency_precede_full_pin_read_and_each_fire_reads_once():
    env = Env()
    env.load("battle_start_ov12")
    env.resident(12)
    site = env.binding.validate(env.binding, env.site("battle_start_ov12"))
    original, reads = env.st.io.read_range, []
    def read(*args):
        reads.append(args)
        return original(*args)
    env.st.io.read_range = read
    env.st.put(site["address"] + 9, "ff")
    assert env.hit(site, 0, accept=env.lua.eval("function() return false end")) == (None, None)
    assert reads == []
    env.resident(13)
    assert env.hit(site, 0) == (None, None) and reads == []
    env.resident(12)
    assert "pin_mismatch" in env.hit(site, site["fire"])[1] and len(reads) == 1
    env.load("battle_start_ov12")
    assert env.hit(site, site["fire"])[1] is None and len(reads) == 2


def _binding_mutant(env, old, new):
    path = ROOT / "lua/nds/hook_binding.lua"
    source = path.read_text()
    assert source.count(old) == 1
    module = env.lua.eval("function(s,p) return assert(load(s,'@'..p))() end")(source.replace(old, new), path.as_posix())
    return module.new(env.st.io, env.cfg)


@pytest.mark.parametrize("guard", ["fire", "static"])
def test_revert_full_pin_guards_accepts_corruption(guard):
    env = Env()
    name = "battle_start_ov12" if guard == "fire" else "party_add_mon"
    env.load(name)
    env.resident(12)
    site = env.binding.validate(env.binding, env.site(name))
    old, new = (("local allowed,reason=RC.may_fire(strategy,site,site_confirmed)", "local allowed,reason=true,nil")
                if guard == "fire" else
                ('assert(site_confirmed(out),"full registration pin mismatch: "..out.id)', 'assert(true)'))
    good = env.binding
    env.binding = _binding_mutant(env, old, new)
    env.st.put(site["address"] + 9, "ff")
    if guard == "fire":
        assert env.hit(site, site["fire"])[0] is not None  # mutant falsely accepts
        env.binding = good
        assert "pin_mismatch" in env.hit(site, site["fire"])[1]
    else:
        assert env.binding.validate(env.binding, env.site(name))
        with pytest.raises(LuaError, match="full registration pin mismatch"):
            good.validate(good, env.site(name))
    env.load(name)
    assert good.validate(good, env.site(name))
