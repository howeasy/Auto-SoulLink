"""C-SITES (docs/polished/CLIENT.md, milestone B): the composed Polished client sees ONE acquisition, a wild party catch.

lua/gen2/entry.lua compose_polished binds lua/gen2/signals.lua S.new_polished, which registers exactly one engine site:
capture_party = 03:652B (flat 0xE52B), the `rst FarCall SetCaughtData` after PokeBallEffect's three party CopyBytes
(data/games/polished_crystal/engine_signals.json). The proof is a synthetic WRAM image over the real overlay ROM plus an
exec-hook replay: the test walks the PCs a ball use passes through and fires whatever hook the client registered at
each, mutating WRAM in engine order (item_effects.asm: `inc [hl]` on wPartyCount BEFORE the record/OT/nickname copies).

What this cannot prove (no cartridge): that BizHawk's exec hook sees 0xE52B as an instruction start on a running
Polished ROM, and the frame alignment of the party write against the hit. The binder reports both in status().unproven
and stays DEV_OVERLAY / physical_status OPEN; signals.lua S.new still refuses Polished outright.
"""
from __future__ import annotations

import json
import random

import pytest

from server.adapters import polished_codec as pc
from tests.unit.test_mixed_foundations import _session
from tests.unit.test_polished_client import SYM, _entry, _key, _memory, _mons, _run
from tests.unit.test_polished_lua import PROFILE, REPO, ROOT, _mon, _pair, _real

lupa = pytest.importorskip("lupa")

SITE_PC, SITE_FLAT, HEAD_PC = 0x652B, 0xE52B, 0x63A0  # PokeBallEffect+0x18B; the routine head is NOT a site
SEND_TO_PC, RETURN_FROM_CAPTURE = 0x6590, 0x666D
HROMBANK = 0xFF87
HOOK = "SLink-gen2-polished:capture_party"

# test_polished_client.HARNESS, plus what an exec-hook replay needs: hooks keep their callback and PC, PC is a register
# the test sets, and a ROM byte may be overridden AFTER composition (the admission hash is taken at compose time).
HARNESS = """
return function(rom, mem)
    local log = {hooks={}, writes={}, sent={}, lines={}}
    local io = {frame=0, pc=0, rom_override={}, mem=mem}
    local function rom_u8(a) return io.rom_override[a] or rom:byte(a + 1) end
    function io.read_u8(a, d)
        if d == "ROM" then return rom_u8(a) end
        -- System Bus: ROM0 and the ROMX bank hROMBank selects, then the WRAM/HRAM image
        if a < 0x4000 then return rom_u8(a) end
        if a < 0x8000 then return rom_u8((mem[0xFF87] or 1) * 0x4000 + a - 0x4000) end
        return mem[a] or 0
    end
    function io.read_range(a, n, d) local out = {} for i = 1, n do out[i] = io.read_u8(a + i - 1, d) end return out end
    function io.write_u8(a, v, d) log.writes[#log.writes + 1] = a end
    function io.bank_valid() return true end
    function io.domain_size(d) return d == "ROM" and #rom or 0x8000 end
    function io.framecount() return io.frame end
    function io.on_bus_exec(fn, addr, name)
        log.hooks[#log.hooks + 1] = {fn=fn, addr=addr, name=name}
        return #log.hooks
    end
    function io.unregister(handle) log.hooks[handle] = false return true end
    function io.register(name) if name == "PC" then return io.pc end return 0xDFF0 end
    local net = {connected=function() return true end, pump=function() end, receive=function() return nil end,
                 send=function(line) log.sent[#log.sent + 1] = line return true end}
    local hud = {show=function() end, nuzlocke_start=function() end, sanitize=function(s) return s end}
    local deps = {root=ROOTDIR, title="polished", io=io, net=net, hud=hud, player="a", rom_size=#rom,
                  read_rom_u8=function(a) return rom:byte(a + 1) end,
                  log=function(t) log.lines[#log.lines + 1] = t end}
    return deps, io, log
end
"""


@pytest.fixture(scope="module")
def roms():
    return _real()


def _rig(roms, mons, override=None):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    mem = _memory(_mons())  # the client fixture's image (player, bag, map, mailbox), then the party under test
    _put(mem, "wPartyCount", [0])
    for slot, mon in enumerate(mons):
        _catch_to_party(mem, slot, mon, nick=f"MON{slot}")
    deps, io, log = lua.execute(HARNESS.replace("ROOTDIR", json.dumps(ROOT)))(roms[1], lua.table_from(mem))
    parts, why = _pair(_entry(lua).build(deps))
    assert why is None, why
    for flat, value in (override or {}).items():
        io.rom_override[flat] = value
    client = parts.client
    client.start(client)
    return lua, parts, io, log


def _hooks(log):
    return [h for h in log.hooks.values() if h]


def _put(io_mem, label, data, offset=0):
    _, base = SYM[label]
    for i, value in enumerate(data):
        io_mem[base + offset + i] = value


def _catch_to_party(mem, slot, mon, ot="KRIS", nick="NEWMON"):
    """PokeBallEffect's party insert, in engine order: count first, then the record, OT and nickname copies."""
    _put(mem, "wPartyCount", [slot + 1])
    _put(mem, "wPartyMons", pc.encode_party_mon(mon), slot * 48)
    _put(mem, "wPartyMonOTs", pc.encode_text(ot, 8) + bytes(3), slot * 11)
    _put(mem, "wPartyMonNicknames", pc.encode_text(nick, 11), slot * 11)


def _replay(io, log, trace, bank=3):
    """Step the PCs a ball use passes through; at each, run the step's WRAM effect, then fire any hook placed there.
    Returns the PCs at which a hook fired."""
    io.mem[HROMBANK] = bank
    fired = []
    for pc_, effect in trace:
        if effect:
            effect()
        io.pc = pc_
        for hook in _hooks(log):
            if hook.addr == pc_:
                fired.append(pc_)
                hook.fn()
    return fired


def _events(parts):
    binder = parts.client.signals
    return [ev for batch in binder.drain(binder).values() for ev in batch.events.values()]


def _new_mon(species=291):
    mon = _mon(random.Random(77), species)
    mon["is_egg"], mon["shiny"] = False, False  # a shiny takes the server's bonus path, not pending_captures
    return mon


# ── what is registered ───────────────────────────────────────────────────────

def test_exactly_one_hook_at_the_set_caught_data_farcall_never_the_routine_head(roms):
    _, parts, io, log = _rig(roms, _mons())
    hooks = _hooks(log)
    # C-WRITE r2: the WRITE hold is its own hook (25:51BF, the overworld frame wait), not an engine SITE - the
    # engine-site set stays exactly one (capture_party); the hold registers nothing and writes nothing on its own.
    assert [(h.name, h.addr) for h in hooks] == [(HOOK, SITE_PC), ("SLink-gen2-checkpoint", 0x51BF)]
    assert all(h.addr != HEAD_PC for h in hooks)
    st = parts.client.signals.status(parts.client.signals)
    assert list(st.registered_sites.values()) == ["capture_party"]
    assert (st.evidence_level, st.physical_status, st.runtime_authorized) == ("DEV_OVERLAY", "OPEN", False)
    assert len(st.unproven) == 2 and parts.qualification == "DEV_OVERLAY_SHA1" and parts.production_admitted is False
    assert roms[1][SITE_FLAT:SITE_FLAT + 7].hex().upper() == "D7084513FA09D1"  # the overlay ROM carries the anchor


# ── (a) positive: a party catch reaches the real server's pending_captures ───

def test_a_party_catch_from_zero_is_the_last_slot_and_carries_the_polished_key(roms):
    _, parts, io, log = _rig(roms, [])
    mem, mon = io.mem, _new_mon(291)
    fired = _replay(io, log, [(HEAD_PC, None), (0x6500, lambda: _catch_to_party(mem, 0, mon)), (SITE_PC, None),
                              (RETURN_FROM_CAPTURE, None)])
    (event,) = _events(parts)
    assert fired == [SITE_PC]
    assert (event.kind, event.acquisition, event.destination, event.slot) == ("capture", "wild", "party", 0)
    assert event.area_id == "new_bark_town" and event.mon.species_id == 291
    assert event.mon.key == _key(mon) and event.evidence_level == "DEV_OVERLAY"


@pytest.mark.asyncio
async def test_a_party_catch_is_emitted_and_the_real_server_pends_it(roms, tmp_path):
    from server.server import SLinkServer
    mons = _mons()
    _, parts, io, log = _rig(roms, mons)
    _run(io, parts.client, 20)
    sent = lambda: [json.loads(line) for line in log.sent.values()]  # noqa: E731
    (hello,) = [m for m in sent() if m["event"] == "hello"]
    mon = _new_mon(291)
    _replay(io, log, [(HEAD_PC, None), (0x6500, lambda: _catch_to_party(io.mem, 3, mon)), (SITE_PC, None)])
    _run(io, parts.client, 1)
    captures = [m for m in sent() if m["event"] == "capture"]
    assert len(captures) == 1, list(log.lines.values())
    capture = captures[0]
    assert capture["key"] == _key(mon) == pc.key(dict(mon, dv_bytes=int(capture["key"][:6], 16)))
    assert (capture["species_id"], capture["area_id"], capture["in_box"], capture["gift"]) == (291, "new_bark_town",
                                                                                          False, False)
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(hello)
        assert srv.is_admitted("a")
        await send(capture)
        pending = srv.state.pending_captures["new_bark_town"]["a"]
        assert pending.key == _key(mon) and pending.species == 291
    finally:
        await close()


# ── (b) negative: an escape never reaches the site; the head PC is not hooked ─

def test_an_escape_or_failed_catch_emits_nothing(roms):
    _, parts, io, log = _rig(roms, _mons())
    # the ball is used (head), shakes, breaks out: wBattleResult untouched, no party copy, no SetCaughtData
    assert _replay(io, log, [(HEAD_PC, None), (0x6400, None), (RETURN_FROM_CAPTURE, None)]) == []
    assert _events(parts) == []
    st = parts.client.signals.status(parts.client.signals)
    assert st.refused_acquisitions == 0 and len(st.refusals) == 0


# ── (c) a full party goes to .SendToPC: no party site fires ──────────────────

def test_a_full_party_catch_goes_to_the_box_and_fires_no_party_site(roms):
    mons = [_new_mon(s) for s in (1, 4, 7, 10, 13, 16)]
    for i, m in enumerate(mons):
        m["ot_id"] = i  # distinct keys
    _, parts, io, log = _rig(roms, mons)
    assert _replay(io, log, [(HEAD_PC, None), (SEND_TO_PC, None), (RETURN_FROM_CAPTURE, None)]) == []
    assert _events(parts) == []


def test_a_hit_with_another_bank_mapped_is_ignored(roms):
    _, parts, io, log = _rig(roms, _mons())
    _replay(io, log, [(SITE_PC, lambda: _catch_to_party(io.mem, 3, _new_mon()))], bank=4)
    assert _events(parts) == []


@pytest.mark.parametrize("label,value,why", [("wBattleType", 5, "specialized/static"),      # ROAMING
                                              ("wBattleScriptFlags", 0x80, "scripted/static")])  # loadwildmon/grotto
def test_a_specialized_or_scripted_catch_is_refused_not_guessed(roms, label, value, why):
    _, parts, io, log = _rig(roms, _mons())
    _put(io.mem, label, [value])
    _replay(io, log, [(SITE_PC, lambda: _catch_to_party(io.mem, 3, _new_mon()))])
    assert _events(parts) == []
    st = parts.client.signals.status(parts.client.signals)
    assert why in st.refusals["capture_party"] and st.refused_acquisitions == 1


# ── (d) wrong bytes at the site: refused, hello still flows, nothing registered ─

def test_an_anchor_mismatch_registers_nothing_but_the_client_still_says_hello(roms):
    _, parts, io, log = _rig(roms, _mons(), override={SITE_FLAT: 0x00})
    # the write hold still hooks (it is not an engine site and its bytes are untouched); no SIGNAL registers
    assert [h.name for h in _hooks(log)] == ["SLink-gen2-checkpoint"]
    assert any("Polished engine sites refused" in line and "differ from the ROM" in line for line in log.lines.values())
    _run(io, parts.client, 20)
    assert [json.loads(line)["event"] for line in log.sent.values()].count("hello") == 1
    _replay(io, log, [(SITE_PC, lambda: _catch_to_party(io.mem, 3, _new_mon()))])
    _run(io, parts.client, 1)
    assert "capture" not in [json.loads(line)["event"] for line in log.sent.values()]


def test_the_binder_refuses_the_old_head_row_and_a_missing_instruction_proof():
    """S.new_polished pins the re-pinned phase and the CPU instruction proof; S.new still refuses Polished."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    signals = lua.eval(f'dofile("{ROOT}/lua/gen2/signals.lua")')
    pack = json.loads((REPO / "data/games/polished_crystal/engine_signals.json").read_text(encoding="utf-8"))
    site = pack["titles"]["polished_crystal"]["sites"]["capture_party"]

    def refusal(**changes):
        doctored = json.loads(json.dumps(pack))
        doctored["titles"]["polished_crystal"]["sites"]["capture_party"].update(changes)
        for key in [k for k, v in changes.items() if v is None]:
            del doctored["titles"]["polished_crystal"]["sites"]["capture_party"][key]
        io = lua.table(bank_valid=lambda *a: True)
        options = lua.table(title="polished", qualification="DEV_OVERLAY_SHA1",
                            profile=lua.table_from(PROFILE["titles"]["polished"], recursive=True),
                            pack=lua.table_from(doctored, recursive=True), io=io, reads=lua.table(read_party=lambda: None),
                            key_fn=lambda m: None, authority=lua.table(capture=lambda: None, valid=lambda s: True))
        return signals.new_polished(options)[1]

    assert "re-pinned CPU source candidate" in refusal(phase="post_insert_pre_nickname")  # the old head row's phase
    assert "CPU instruction proof required" in refusal(instructions=None)
    assert "unsupported CPU instruction" in refusal(instructions=["db $D7"])
    assert "DEV_OVERLAY_SHA1" in signals.new_polished(lua.table(title="polished"))[1]
    assert site["phase"] == "post_insert_post_nickname_copy"
