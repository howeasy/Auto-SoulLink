"""lua/gen4/run.lua: the composition root composes entry.admit_routed -> client.

Hermetic: run.lua is copied into a scratch tree next to the REAL lua/gen4/entry.lua (wrapped by a
recording shim) and the real pack profiles, with a STUB lua/gen4/client.lua, stub connector/hud
modules and stubbed BizHawk globals. No ROM, no emulator, no .cache.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import lupa
import pytest

from tests.unit.test_gen4_inputs import (  # the producer harness, shared by the wiring mutants
    BAG,
    assert_area_contract,
    bag_memory,
    lua_inputs,
)

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "lua/gen4/run.lua"
INPUTS = (ROOT / "lua/gen4/inputs.lua").read_text(encoding="utf-8")
HGE = json.loads((ROOT / "data/games/gen4_hge/profile.json").read_text(encoding="utf-8"))["titles"]["heartgold_hge"]
HEADER_COPY = 0x027FFE00  # the NDS boot copy of the cartridge header, now Client.PLATFORM's constant

ENTRY_SHIM = """
local E = dofile(ROOT_DIR .. "/lua/gen4/entry_real.lua")
local real = E.admit_routed
E.admit_routed = function(args) CALLS.admit_routed = (CALLS.admit_routed or 0) + 1; CALLS.admit_args = args; return real(args) end
return E
"""
CLIENT_STUB = """
local C = { PLATFORM = { bus_domain = "ARM9 System Bus", header_copy = HEADER_COPY } }
-- save_array models the one reader the real client hands out (client.lua session.save_array): an
-- array id in, a reader over ARRAY-relative offsets out, and a refusal by name for anything else.
local function save_array(_, id)
    CALLS.save_array_ids = CALLS.save_array_ids or {}
    CALLS.save_array_ids[#CALLS.save_array_ids + 1] = id
    if id ~= BAG_ARRAY_ID then return nil, "bad_array_id" end
    return function(off, len) return BAG_MEM[off] end
end
function C.new(p)
    CALLS.client_new = (CALLS.client_new or 0) + 1; CALLS.client_args = p
    if CLIENT_FAIL then return nil, CLIENT_FAIL end
    return { start = function() CALLS.started = true; if START_FAIL then error(START_FAIL, 0) end end,
             frame_end = function() CALLS.frames = (CALLS.frames or 0) + 1 end,
             stop = function() CALLS.stopped = true end,
             save_array = save_array }
end
return C
"""


def run_root(tmp: Path, text: str | None = None, *, rom_hash: str, header: str = "IPKE",
             client_fail: str | None = None, start_fail: str | None = None,
             stub_src: str | None = None, with_areas: bool = False, with_bag: bool = False,
             bag_mem: dict | None = None):
    """Run run.lua (or a mutated `text` of it) in a scratch tree; returns (lua globals, calls, hud log, console log).

    `stub_src` replaces the client stub (mutants); `with_areas` plants the hgss area data files in
    every scratch pack and `with_bag` the balls-pocket fact (BAG), which are the only ways the
    optional area / synthetic ball inputs can be planted in the scratch tree. Copied real
    profiles may already carry their generated bag fact.
    `bag_mem` is the array the stub's reader answers from, at the pack's own pocket offsets.
    """
    gen4 = tmp / "lua/gen4"
    gen4.mkdir(parents=True)
    (tmp / "lua/json_codec.lua").write_bytes((ROOT / "lua/json_codec.lua").read_bytes())
    shutil.copy(ROOT / "lua/gen4/entry.lua", gen4 / "entry_real.lua")
    shutil.copy(ROOT / "lua/gen4/inputs.lua", gen4 / "inputs.lua")
    (gen4 / "entry.lua").write_text(ENTRY_SHIM, encoding="utf-8")
    (gen4 / "client.lua").write_text(stub_src if stub_src is not None else CLIENT_STUB, encoding="utf-8")
    for pack in ("hgss", "hge", "pt"):
        d = tmp / f"data/games/gen4_{pack}"
        d.mkdir(parents=True)
        shutil.copy(ROOT / f"data/games/gen4_{pack}/profile.json", d / "profile.json")
        if with_areas:
            # the hgss files are the only ones that ship; planting them in every scratch pack is
            # what makes "the pack CAN supply this fact" testable for whichever pack admits
            for name in ("area_map.json", "locations.json"):
                shutil.copy(ROOT / f"data/games/gen4_hgss/{name}", d / name)
        if with_bag:
            # The mutation tests use a small synthetic pocket in place of the real profile's
            # generated geometry; ordinary composition tests keep the real profile fact.
            doc = json.loads((d / "profile.json").read_text(encoding="utf-8"))
            for title in doc["titles"].values():
                title.setdefault("profile", {})["bag"] = BAG
            (d / "profile.json").write_text(json.dumps(doc), encoding="utf-8")
    (gen4 / "run.lua").write_text(text if text is not None else RUN.read_text(encoding="utf-8"), encoding="utf-8")
    return _exec(tmp, gen4, rom_hash, header, client_fail, start_fail, bag_mem)


def _exec(tmp: Path, gen4: Path, rom_hash: str, header: str, client_fail, start_fail,
           bag_mem: dict | None = None):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.HEADER_COPY = HEADER_COPY
    head = header.encode()

    def mem(addr, domain):  # only the header copy is modelled; ARM9 anchors are never needed (hge = hash only)
        assert domain == "ARM9 System Bus"
        off = addr - HEADER_COPY - 0x0C  # the game code sits at header +0x0C
        return head[off] if 0 <= off < 4 else 0

    logs: list[str] = []
    g.ROOT_DIR = tmp.as_posix()
    g.CLIENT_FAIL, g.START_FAIL = client_fail, start_fail
    g.CALLS = lua.table()
    g.PYMEM, g.PYLOG, g.ROMHASH = mem, logs.append, rom_hash
    g.BAG_MEM, g.BAG_ARRAY_ID = lua.table_from(bag_mem or {}), BAG["array_id"]
    lua.execute("""
        package.path = ROOT_DIR .. "/lua/?.lua;" .. package.path
        local hud = { shown = {}, inits = 0 }
        function hud.init() hud.inits = hud.inits + 1 end
        function hud.show(text) hud.shown[#hud.shown + 1] = text end
        function hud.render() end
        local net = { inits = {} }
        function net.init(h, p) net.inits[#net.inits + 1] = { h, p } end
        package.loaded.hud, package.loaded.connector = hud, net
        HUD, NET = hud, net
        console = { log = PYLOG }
        gameinfo = { getromhash = function() return ROMHASH end }
        memory = { read_u8 = PYMEM, read_u16_le = PYMEM, read_u32_le = PYMEM }
        emu = { framecount = function() return 0 end, getregister = function() return 0 end }
        event = { on_bus_exec = function() end, unregisterbyid = function() end,
                  onframeend = function(f) FRAME_CB = f end, onexit = function(f) EXIT_CB = f end }
    """)
    lua.execute(f'dofile("{(gen4 / "run.lua").as_posix()}")')
    return g, g.CALLS, g.HUD, logs


def test_admitted_hge_builds_the_client_over_the_net_and_hud_seam(tmp_path):
    g, calls, hud, logs = run_root(tmp_path, rom_hash=HGE["rom"]["sha1"])
    assert calls.admit_routed == 1 and calls.client_new == 1 and calls.started
    p = calls.client_args
    assert g.rawequal(p.net, g.NET) and g.rawequal(p.hud, hud) and p.player == "a" and p.rom_hash == HGE["rom"]["sha1"]
    assert p.header_code == "IPKE" and p.root == tmp_path.as_posix()
    assert calls.admit_args.header_code == "IPKE" and calls.admit_args.rom_hash == HGE["rom"]["sha1"]
    assert list(g.NET.inits[1].values()) == ["127.0.0.1", 54321]
    assert list(hud.shown.values()) == [] and any("gen4_hge/heartgold_hge" in line for line in logs)
    # the frame loop and the exit hook are wired to the client
    g.FRAME_CB()
    g.EXIT_CB()
    assert calls.frames == 1 and calls.stopped and g.SLINK_GEN4_CLIENT is not None


def test_refused_admission_names_the_reason_and_never_builds_the_client(tmp_path):
    g, calls, hud, logs = run_root(tmp_path, rom_hash="00" * 16)
    assert calls.admit_routed == 1 and calls.client_new is None and calls.started is None
    assert any("refused" in line and "unpinned build" in line for line in logs)
    assert list(hud.shown.values()) == ["SLINK COULD NOT START - SEE LOG"]
    assert g.FRAME_CB is None and len(g.NET.inits) == 0


def test_a_wrong_header_is_refused_by_name(tmp_path):
    _, calls, _, logs = run_root(tmp_path, rom_hash=HGE["rom"]["sha1"], header="AAAA")
    assert calls.client_new is None and any("does not match the pinned" in line for line in logs)


@pytest.mark.parametrize("kw,needle", [({"client_fail": "no pack"}, "no pack"), ({"start_fail": "hooks"}, "hooks")])
def test_a_client_that_fails_to_build_or_start_is_refused_visibly(tmp_path, kw, needle):
    g, _, hud, logs = run_root(tmp_path, rom_hash=HGE["rom"]["sha1"], **kw)
    assert any("refused to start" in line and needle in line for line in logs)
    assert list(hud.shown.values()) == ["SLINK COULD NOT START - SEE LOG"] and g.FRAME_CB is None


def test_run_lua_names_no_hex_literal_at_all():
    """No address lives in run.lua any more: the header copy is Client.PLATFORM's, cited there."""
    code = "\n".join(re.sub(r"--.*", "", ln) for ln in RUN.read_text(encoding="utf-8").splitlines())
    assert re.findall(r"\b0[xX][0-9A-Fa-f]+\b", code) == []
    assert re.search(r"Client\.PLATFORM", code)
    for banned in ("heartgold", "soulsilver", "gen4_hg", "ov129", "overlay"):
        assert banned not in code.lower()


def test_the_header_copy_is_a_platform_fact_cited_in_the_client():
    """GBATEK: the header is loaded from ROM 0 to main RAM 0x027FFE00 on power-up."""
    client = (ROOT / "lua/gen4/client.lua").read_text(encoding="utf-8")
    # the citation is the comment block that heads the table, so the slice starts at that block
    plat = client[client.index("-- NDS platform facts") :]
    plat = plat[: plat.index("local TAG")]
    assert "header_copy = 0x027FFE00" in plat
    assert "GBATEK" in plat and "27FFE00h" in plat, "the platform fact must carry its citation"
    assert "hex literal" not in RUN.read_text(encoding="utf-8")


def test_a_platform_without_the_header_copy_is_refused_by_name(tmp_path):
    """Mutant: the platform table loses header_copy, so run.lua reads a nil address."""
    mutant = CLIENT_STUB.replace("header_copy = HEADER_COPY", "pc_register = 'ARM9 r15'")
    assert mutant != CLIENT_STUB
    _, calls, hud, logs = run_root(tmp_path, rom_hash=HGE["rom"]["sha1"], stub_src=mutant)
    # the header read raises, the header code is empty, and admission refuses by name
    assert calls.admit_routed == 1 and calls.client_new is None
    assert any("refused" in line for line in logs)
    assert list(hud.shown.values()) == ["SLINK COULD NOT START - SEE LOG"]


def test_run_lua_hands_the_client_the_producers_the_pack_can_supply(tmp_path):
    """The root wires the available area and real-profile bag producers into Client.new."""
    bag = HGE["profile"]["bag"]
    pocket = bag["balls_pocket_off"]
    memory = {pocket + bag["slot_fields"]["id"]["off"]: 4,
              pocket + bag["slot_fields"]["quantity"]["off"]: 1}
    _, calls, _, logs = run_root(tmp_path, rom_hash=HGE["rom"]["sha1"], with_areas=True,
                                bag_mem=memory)
    p = calls.client_args
    assert callable(p.area_of), "run.lua must pass the pack-built area producer"
    assert list(p.area_of(9, {})) == ["route_1", "Route 1"]
    assert list(p.area_of(0, {})) == [None, "Mystery Zone"]     # unmapped: no area, still a label
    assert list(p.area_of(9999, {})) == [None, None]
    # This scratch tree deliberately omits charmap.json, but keeps the real profile.bag.
    assert p.charmap is None
    assert any("input charmap unavailable" in line for line in logs)
    assert callable(p.has_pokeballs), "the generated bag fact must wire the ball producer"
    assert p.has_pokeballs() is True
    assert list(calls.save_array_ids.values()) == [bag["array_id"]]
    assert not any("input has_pokeballs unavailable" in line for line in logs)


def test_run_lua_hands_the_client_the_pack_gift_area_list(tmp_path):
    """The gift seam rides in the SAME area_map.json the area producer already needs, so a pack that
    can answer "which map am I on" can answer "is this area exempt from no_catch" -- and the list must
    be the pack's own: the ids this run asserts are the ones the committed file carries."""
    _, calls, _, logs = run_root(tmp_path, rom_hash=HGE["rom"]["sha1"], with_areas=True)
    p = calls.client_args
    ids = json.loads((ROOT / "data/games/gen4_hgss/area_map.json").read_text(encoding="utf-8"))["gift_areas"]["ids"]
    assert callable(p.gift_area), "run.lua must pass the pack-built gift-area producer"
    assert [a for a in ids if p.gift_area(a) is not True] == [], ids
    assert p.gift_area("route_1") is False and p.gift_area("") is False, "an unnamed area is not a gift area"
    assert not any("input gift_area unavailable" in line for line in logs)


def test_a_run_that_drops_the_gift_seam_goes_red(tmp_path):
    """Mutant: run.lua builds the gift producer and then never hands it to the client -- the exact
    defect that made the `gift_daycare` falsifier go red. The `callable` assertion above must catch it."""
    src = RUN.read_text(encoding="utf-8")
    mutant = src.replace("    gift_area = inputs.gift_area,\n", "")
    assert mutant != src
    _, calls, _, _ = run_root(tmp_path, mutant, rom_hash=HGE["rom"]["sha1"], with_areas=True)
    with pytest.raises(AssertionError):
        assert callable(calls.client_args.gift_area)


def test_run_lua_without_the_area_pack_files_refuses_the_area_input(tmp_path):
    """The profile alone carries no area map: the seams must be absent, not guessed. An absent
    gift_area means NO area is exempt from no_catch -- never every area, which would switch the
    dead-zone rule off for the whole run."""
    _, calls, _, logs = run_root(tmp_path, rom_hash=HGE["rom"]["sha1"])
    assert calls.client_new == 1 and calls.client_args.area_of is None and calls.client_args.gift_area is None
    assert any("input area_of unavailable" in line and "area_map.json" in line for line in logs)
    assert any("input gift_area unavailable" in line and "area_map.json" in line for line in logs)


def test_a_run_that_invents_an_area_when_the_pack_has_none_goes_red(tmp_path):
    """Mutant: the area producer fabricates an id instead of refusing."""
    mutant = INPUTS.replace("local area = maps[key]", "local area = maps[key] or 'route_1'")
    assert mutant != INPUTS
    assert_area_contract(lua_inputs(tmp_path / "real", areas=True))
    with pytest.raises(AssertionError):
        assert_area_contract(lua_inputs(tmp_path / "mut", src=mutant, areas=True))


def test_a_run_that_skips_admit_routed_goes_red(tmp_path):
    """Mutant: admit_routed replaced by an always-admit stub. The refusal contract must then fail."""
    src = RUN.read_text(encoding="utf-8")
    mutant = src.replace("Entry.admit_routed(", "(function() return { pack = 'gen4_hge', title = 'x', admitted_by = 'hash',"
                         " rom_hash = 'x' } end)(", 1)
    assert mutant != src
    _, calls, _, _ = run_root(tmp_path, mutant, rom_hash="00" * 16)
    assert calls.admit_routed is None
    assert calls.client_new == 1, "the mutant built a client for an unpinned ROM: test (b) must catch this"


def assert_bag_wiring(calls, logs):
    """The guard every ball-seam mutant must trip: the pack ships the fact, so the producer is built,
    it reaches the save through the CLIENT's reader, and it reads the pack's own pocket offsets."""
    p = calls.client_args
    assert callable(p.has_pokeballs), "the pack ships profile.bag, so the seam must be WIRED"
    assert p.has_pokeballs() is True, "the reader never reached the pack's balls pocket"
    assert list(calls.save_array_ids.values()) == [BAG["array_id"]], "the producer must ask for the bag array"
    assert not any("input has_pokeballs unavailable" in line for line in logs)


def test_run_lua_composes_the_ball_read_through_the_clients_own_save_array(tmp_path):
    """Inputs.build runs before Client.new, so run.lua binds the seam late; what matters is that the
    producer ends up reading through client:save_array, with no second copy of the read layer here."""
    _, calls, _, logs = run_root(tmp_path, rom_hash=HGE["rom"]["sha1"], with_bag=True,
                                 bag_mem=bag_memory([(4, 5)]))
    assert_bag_wiring(calls, logs)


def test_a_run_whose_save_seam_always_refuses_goes_red(tmp_path):
    """Mutant: run.lua's save_array refuses for every array. A refusal must read as UNKNOWN."""
    src = RUN.read_text(encoding="utf-8")
    mutant = src.replace("        return client:save_array(array_id)", '        return nil, "mutant: no reader"')
    assert mutant != src
    _, calls, _, logs = run_root(tmp_path, mutant, rom_hash=HGE["rom"]["sha1"], with_bag=True,
                                 bag_mem=bag_memory([(4, 5)]))
    value, why = calls.client_args.has_pokeballs()
    assert value is None and "mutant: no reader" in why, "an unreadable save must never read as false"
    with pytest.raises(AssertionError):
        assert_bag_wiring(calls, logs)
