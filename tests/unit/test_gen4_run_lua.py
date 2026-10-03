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

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "lua/gen4/run.lua"
HGE = json.loads((ROOT / "data/games/gen4_hge/profile.json").read_text(encoding="utf-8"))["titles"]["heartgold_hge"]
HEADER_COPY = 0x027FFE00  # run.lua's one platform constant (the NDS boot copy of the cartridge header)

ENTRY_SHIM = """
local E = dofile(ROOT_DIR .. "/lua/gen4/entry_real.lua")
local real = E.admit_routed
E.admit_routed = function(args) CALLS.admit_routed = (CALLS.admit_routed or 0) + 1; CALLS.admit_args = args; return real(args) end
return E
"""
CLIENT_STUB = """
local C = { PLATFORM = { bus_domain = "ARM9 System Bus" } }
function C.new(p)
    CALLS.client_new = (CALLS.client_new or 0) + 1; CALLS.client_args = p
    if CLIENT_FAIL then return nil, CLIENT_FAIL end
    return { start = function() CALLS.started = true; if START_FAIL then error(START_FAIL, 0) end end,
             frame_end = function() CALLS.frames = (CALLS.frames or 0) + 1 end,
             stop = function() CALLS.stopped = true end }
end
return C
"""


def run_root(tmp: Path, text: str | None = None, *, rom_hash: str, header: str = "IPKE",
             client_fail: str | None = None, start_fail: str | None = None):
    """Run run.lua (or a mutated `text` of it) in a scratch tree; returns (lua globals, calls, hud log, console log)."""
    gen4 = tmp / "lua/gen4"
    gen4.mkdir(parents=True)
    (tmp / "lua/json_codec.lua").write_bytes((ROOT / "lua/json_codec.lua").read_bytes())
    shutil.copy(ROOT / "lua/gen4/entry.lua", gen4 / "entry_real.lua")
    (gen4 / "entry.lua").write_text(ENTRY_SHIM, encoding="utf-8")
    (gen4 / "client.lua").write_text(CLIENT_STUB, encoding="utf-8")
    for pack in ("hgss", "hge", "pt"):
        d = tmp / f"data/games/gen4_{pack}"
        d.mkdir(parents=True)
        shutil.copy(ROOT / f"data/games/gen4_{pack}/profile.json", d / "profile.json")
    (gen4 / "run.lua").write_text(text if text is not None else RUN.read_text(encoding="utf-8"), encoding="utf-8")

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
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


def test_run_lua_names_no_title_address():
    """Game facts stay in the pack/adapters: the only hex literal is the platform header-copy base."""
    code = "\n".join(re.sub(r"--.*", "", ln) for ln in RUN.read_text(encoding="utf-8").splitlines())
    literals = re.findall(r"\b0[xX][0-9A-Fa-f]{5,}\b", code)
    assert [x.lower() for x in literals] == ["0x027ffe00"]
    assert re.search(r"HEADER_COPY\s*=\s*0x027FFE00", code)
    for banned in ("heartgold", "soulsilver", "gen4_hg", "ov129", "overlay"):
        assert banned not in code.lower()


def test_a_run_that_skips_admit_routed_goes_red(tmp_path):
    """Mutant: admit_routed replaced by an always-admit stub. The refusal contract must then fail."""
    src = RUN.read_text(encoding="utf-8")
    mutant = src.replace("Entry.admit_routed(", "(function() return { pack = 'gen4_hge', title = 'x', admitted_by = 'hash',"
                         " rom_hash = 'x' } end)(", 1)
    assert mutant != src
    _, calls, _, _ = run_root(tmp_path, mutant, rom_hash="00" * 16)
    assert calls.admit_routed is None
    assert calls.client_new == 1, "the mutant built a client for an unpinned ROM: test (b) must catch this"
