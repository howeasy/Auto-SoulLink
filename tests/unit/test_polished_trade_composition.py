"""C4 dev-only composition on the real write-path Rig; no client pump/hello capability.

Model I/O and native UI traps are disclosed: this does not qualify live BizHawk.
Fault injection removes/replaces the ROM reader after base graph construction,
so optional-trade refusal is measured independently of earlier whole-ROM admission.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.unit import (
    test_gen2_entry as vanilla,
    test_polished_trade_service as svc,
    test_polished_write_path as wp,
)

env = svc.env
ROOT = wp.REPO
ENTRY = ROOT / "lua/gen2/entry.lua"
SOURCE = ENTRY.read_text(encoding="utf-8")

INSTALL = r"""
return function(root, option, fault, source)
    local original = dofile
    C4 = {trade_loads=0, permits=0, policies={}}
    dofile = function(path)
        local module
        if path == root..'/lua/gen2/entry.lua' and source then
            module = assert(load(source,'@'..path))()
        else module = original(path) end
        if path:gsub('/gen2/%.%./','/') == root..'/lua/write_permit.lua' then
            local make = module.new
            module.new = function(policy)
                C4.permits=C4.permits+1; C4.policies[#C4.policies+1]=policy
                return make(policy)
            end
        elseif path == root..'/lua/gen2/polished.lua' then
            local load = module.load
            module.load = function(...)
                local profile,charmap,wrapper = load(...)
                if fault == 'family' then profile.overlay.trade=nil end
                if fault == 'partial' then profile.overlay.trade.staging.ot=nil end
                return profile,charmap,wrapper
            end
        elseif path == root..'/lua/gen2/polished_trade.lua' then
            C4.trade_loads=C4.trade_loads+1
            local compose=module.compose
            module.compose=function(spec)
                C4.trade_io=spec.io
                return compose(spec)
            end
        elseif path == root..'/lua/gen2/client.lua' then
            local new = module.new
            module.new=function(spec)
                local client=new(spec)
                C4.client_has_trade=spec.trade ~= nil
                if fault == 'reader' or fault == 'rom' then
                    C4.restore=C4.deps.io.read_u8
                    if fault == 'reader' then C4.deps.io.read_u8=nil
                    else C4.deps.io.read_u8=function(a,d)
                        local b=C4.restore(a,d)
                        if d == 'ROM' and a == 0 then return (b+1)%256 end
                        return b
                    end end
                end
                return client
            end
        elseif path == root..'/lua/gen2/entry.lua' then
            local build=module.build
            module.build=function(deps)
                deps.polished_trade_dev=option
                C4.deps=deps
                local graph,why=build(deps)
                if C4.restore then deps.io.read_u8=C4.restore end
                return graph,why
            end
        end
        return module
    end
end
"""


class Rig(wp.Rig):
    def __init__(self, option=None, fault=None, mutation=None):
        self.option, self.fault, self.mutation = option, fault, mutation
        super().__init__(wp.party(), sources={"install": True})

    def _patch(self, sources):
        source = SOURCE
        if self.mutation:
            before, after = self.mutation
            assert before in source
            source = source.replace(before, after)
        self.lua.execute(INSTALL)(str(ROOT).replace("\\", "/"), self.option, self.fault, source)

    @property
    def binder(self):
        return self.parts.dev_polished_trade


def graph_image(rig):
    # Canonical graph structure, including function bytecode and metatables.
    # Closure identity is intentionally excluded; each real Rig has fresh closures.
    return rig.lua.execute(r"""
        return function(value,root)
            local seen,serial={},0
            local function encode(v)
                local kind=type(v)
                if kind == 'function' then
                    local ok,bytes=pcall(string.dump,v,true)
                    if not ok then return 'native-function' end
                    return 'function:'..bytes:gsub('.',function(c) return string.format('%02x',c:byte()) end)
                end
                if kind ~= 'table' then return kind..':'..tostring(v) end
                if seen[v] then return 'ref:'..seen[v] end
                serial=serial+1; seen[v]=serial
                local keys={}; for k in pairs(v) do keys[#keys+1]=k end
                table.sort(keys,function(a,b) return type(a)..tostring(a)<type(b)..tostring(b) end)
                local rows={}
                for _,k in ipairs(keys) do rows[#rows+1]=encode(k)..'='..encode(v[k]) end
                if getmetatable(v) then rows[#rows+1]='meta='..encode(getmetatable(v)) end
                return '{'..table.concat(rows,';')..'}'
            end
            return encode(value)
        end
    """)(rig.parts, str(ROOT))


def hello_lines(rig):
    rig.frame(12)
    return [line for line in rig.log["sent"].values() if json.loads(line)["event"] == "hello"]


def test_absent_and_false_option_leave_graph_identical():
    absent, off = Rig(), Rig(False)
    assert absent.binder is None and off.binder is None
    assert graph_image(absent) == graph_image(off)
    for rig in (absent, off):
        assert rig.lua.globals().C4.trade_loads == 0
        assert not rig.lua.globals().C4.client_has_trade
    assert absent.lua.globals().C4.permits == off.lua.globals().C4.permits
    assert hello_lines(absent) == hello_lines(off)


def test_dev_only_parts_exposure_and_identical_hello():
    off, on = Rig(), Rig(True)
    assert on.binder is not None
    assert on.parts.production_admitted is False
    assert on.parts.qualification == off.parts.qualification == "DEV_OVERLAY_SHA1"
    assert on.binder.advertised(on.binder) is False
    assert not on.lua.globals().C4.client_has_trade
    assert on.lua.eval("rawequal")(on.lua.globals().C4.trade_io, on.io)
    left, right = hello_lines(off), hello_lines(on)
    assert left and left == right
    assert all(json.loads(line)["trade_prepare"] is False for line in right)
    assert on.writes() == off.writes() == []
    assert list(on.log['hooks'].values()) == list(off.log['hooks'].values())


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("family", "overlay.trade"),
        ("partial", "trade span missing: ot"),
        ("reader", "ROM reader"),
        ("rom", "ROM hash"),
    ],
    ids=["family", "partial", "reader", "rom"],
)
def test_optional_refusal_is_named_once(fault, reason):
    rig = Rig(True, fault=fault)
    assert rig.binder is None
    lines = [s for s in rig.log["lines"].values() if "dev trade" in s]
    assert len(lines) == 1 and reason in lines[0]
    rig.frame(12)
    assert len([s for s in rig.log["lines"].values() if "dev trade" in s]) == 1
    assert not rig.writes()


def test_vanilla_composition_source_unchanged():
    start = SOURCE.index("local function compose(deps, title, production, decision)")
    stop = SOURCE.index("function Entry.build_candidate(deps)")
    assert (
        hashlib.sha256(SOURCE[start:stop].encode()).hexdigest()
        == "badefd88c56709182eb44ae3f8a60a7149842d1193d6570e9edf08e682cb0f88"
    )


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"], ids=["crystal", "gold", "silver"])
def test_existing_vanilla_candidate_composition(title):
    profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_bytes())["titles"][
        title
    ]
    source = "pokecrystal" if title == "crystal" else "pokegold"
    rom = ROOT / f".cache/gen2-build/{source}/{profile['artifact']}.gbc"
    if not rom.is_file():
        pytest.skip(f"vanilla composition input absent: {rom}")
    vanilla.test_candidate_build_wires_existing_read_write_rom_modules_without_activation(title)


def test_composed_binder_answers_real_service_query(env):
    graph = Rig(True)
    binder = graph.binder
    assert binder is not None
    native = svc.Rig(env)
    before = len(graph.writes())

    def script(host):
        def read_frame():
            graph.io.frame = native.frame
            for i, v in enumerate(host.m.peek(native.lease, svc.LEASE_SIZE)):
                graph.mem[native.lease + i] = v

        def write_frame():
            host.m.poke(
                native.lease, bytes(graph.mem[native.lease + i] for i in range(svc.LEASE_SIZE))
            )

        while not host.query_pending():
            yield
        read_frame()
        query = binder.poll_query(binder)
        assert binder.answer_query(binder, query.gen, 4, graph.lua.table_from(svc.TOKEN)) is True
        write_frame()
        while True:
            read_frame()
            offer = binder.poll_offer(binder)
            if offer is not None:
                break
            yield
        assert binder.answer_offer(binder, offer.gen, False) is True
        write_frame()

    run = native.run(script)
    svc.common(native, run, "QOC")
    assert [w["addr"] - native.lease for w in graph.writes()[before:]] == [
        10,
        11,
        12,
        13,
        14,
        15,
        7,
        8,
        7,
    ]
    assert graph.lua.globals().C4.trade_io.framecount() == native.frame
    assert not graph.client.trade_live(graph.client)
    assert graph.sent("trade_query") == []


def test_absent_option_matches_pre_c4_graph():
    start = SOURCE.index('        local parts = {pack="polished_crystal"')
    end = SOURCE.index("        return parts", start) + len("        return parts")
    current = SOURCE[start:end]
    previous = current.split("        -- C4:")[0].replace(
        "local parts = {pack=", "return {pack=", 1
    )
    old, new = Rig(mutation=(current, previous)), Rig()
    assert graph_image(old) == graph_image(new)
    assert old.lua.globals().C4.permits == new.lua.globals().C4.permits
    assert hello_lines(old) == hello_lines(new)


def permit_intervals(rig, policy, domain, reason, end):
    rows = rig.lua.execute("""return function(policy,domain,reason,limit)
        local out,start={},nil
        for a=0,limit do
            local yes=a<limit and policy.domains[domain].bounds(a,1,reason) == true
            if yes and not start then start=a
            elseif not yes and start then out[#out+1]={start,a}; start=nil end
        end
        return out
    end""")(policy, domain, reason, end)
    return [tuple(row.values()) for row in rows.values()]


def test_permit_sets_are_exact_and_overworld_is_unchanged():
    off, on = Rig(), Rig(True)

    def overworld(rig):
        candidates = [
            p
            for p in rig.lua.globals().C4.policies.values()
            if p.domains.CartRAM is not None and p.domains.WRAM is not None
        ]
        assert len(candidates) == 1
        return candidates[0]

    old, new = overworld(off), overworld(on)
    for domain in ["System Bus", "CartRAM", "WRAM"]:
        limit = max(65536, max(b for _, b in wp.allowed()[domain])) + 1
        for reason in ["overworld", "party_collection", "box_deposit", "trade"]:
            assert permit_intervals(off, old, domain, reason, limit) == permit_intervals(
                on, new, domain, reason, limit
            )
    assert on.lua.globals().C4.permits == off.lua.globals().C4.permits + 1
    policy = on.lua.globals().C4.policies[on.lua.globals().C4.permits]
    assert list(policy.domains.keys()) == ["System Bus"]
    t = on.parts.profile.overlay.trade
    expected = [(t.lease.base, t.lease.base + t.lease.size)]
    expected += [(s.addr, s.addr + s.size) for s in t.staging.values()]
    # Some declared spans touch; compare the exact byte allowlist rather than
    # forcing adjacent records to remain separate intervals in the observation.
    expected_bytes = {a for start, end in expected for a in range(start, end)}
    got = permit_intervals(on, policy, "System Bus", "trade", 65536)
    assert {a for start, end in got for a in range(start, end)} == expected_bytes
    for s in t.snapshot.values():
        assert not any(a in expected_bytes for a in range(s.addr, s.addr + s.size))
    assert not any(
        a in expected_bytes for start, end in wp.allowed()["System Bus"] for a in range(start, end)
    )
    for start, end in expected:
        assert policy.domains["System Bus"].bounds(start, end - start, "trade") is True
        assert policy.domains["System Bus"].bounds(start, end - start + 1, "trade") is False


@pytest.mark.parametrize(
    "gate", ["flag", "family", "reader", "rom"], ids=["flag", "family", "reader", "rom"]
)
def test_composition_gate_mutants_are_caught(gate):
    changes = {
        "flag": ("if deps.polished_trade_dev == true then", "if true then"),
        "family": (
            'assert(profile.overlay.trade, "overlay.trade family missing")',
            "-- family check removed",
        ),
        "reader": (
            'assert(type(reader) == "function", "live ROM reader missing")',
            "reader = reader or deps.read_rom_u8; io_.read_u8 = reader",
        ),
        "rom": ("Admission.sha1(byte, size) == decision.rom_sha1", "true"),
    }
    rig = Rig(
        None if gate == "flag" else True,
        fault=None if gate == "flag" else gate,
        mutation=changes[gate],
    )
    with pytest.raises(AssertionError):
        if gate == "family":
            assert rig.lua.globals().C4.trade_loads == 0
        else:
            assert rig.binder is None
