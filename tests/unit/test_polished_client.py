"""Polished Crystal client composition (docs/polished/CLIENT.md milestone A: C-PACK + C-SIGNALS + C-COMPOSE).

lua/gen2/entry.lua compose_polished builds the real lua/gen2/client.lua over lua/gen2/polished.lua's reads and
P.wire, under Entry.admit_polished's DEV-GRADE authority (overlay sha1 only, never PHYSICAL_RECEIPTED). The proof
here is end to end and in process: the overlay ROM (patch/dist/SLink-Polished.ups on the pinned release), a WRAM
image laid out from data/polished/polished_slink.sym holding a party built with polished_codec.encode_party_mon,
the client's own hello line captured off its net and replayed into a real SLinkServer -> admitted, party decoded.
No engine-site hook and no write may happen anywhere on this path (no Polished receipts exist).
"""
from __future__ import annotations

import json
import random

import pytest

from server.adapters import polished_codec as pc
from tests.unit.test_gen2_signals import World
from tests.unit.test_mixed_foundations import _refused, _session
from tests.unit.test_polished_lua import (
    POLISHED,
    PROFILE,
    REPO,
    ROOT,
    _mon,
    _pair,
    _real,
    _sym,
    _with,
    load_variants,
)

lupa = pytest.importorskip("lupa")

SYM = _sym()
SPECIES = (25, 291, 1)  # 291: a 9-bit species (ext-species bit in the Form byte)
NAMES = (("KRIS", "PIKA"), ("KRIS", "MONKEY"), ("LYRA", "BULBA"))
OT_ID = 0x30B8

# The live IO run.lua supplies, as pure Lua over a ROM string and a System Bus table: every hook registration and
# every write is recorded (and must stay empty), the frame counter advances one per frame_end like onframeend.
HARNESS = """
return function(rom, mem)
    local log = {hooks={}, writes={}, sent={}, lines={}}
    local io = {frame=0}
    function io.read_u8(a, d) if d == "ROM" then return rom:byte(a + 1) end return mem[a] or 0 end
    function io.read_range(a, n, d) local out = {} for i = 1, n do out[i] = io.read_u8(a + i - 1, d) end return out end
    -- Record the ADDRESS and the VALUE, and land the byte in the image: a staged panel page is
    -- only checkable if the harness's WRAM is writable. Every other consumer of log.writes in
    -- this suite reads its length only.
    function io.write_u8(a, v, d) log.writes[#log.writes + 1] = {addr=a, value=v} mem[a] = v end
    function io.bank_valid() return true end
    function io.domain_size(d) return d == "ROM" and #rom or 0x8000 end
    function io.framecount() return io.frame end
    function io.on_bus_exec(fn, addr, name) log.hooks[#log.hooks + 1] = name return #log.hooks end
    function io.unregister() end
    function io.register() return 0 end
    local net = {connected=function() return true end, pump=function() end, receive=function() return nil end,
                 send=function(line) log.sent[#log.sent + 1] = line return true end}
    local hud = {show=function() end, nuzlocke_start=function() end, sanitize=function(s) return s end}
    local deps = {root=ROOTDIR, title="polished", io=io, net=net, hud=hud, player="a", rom_size=#rom,
                  read_rom_u8=function(a) return rom:byte(a + 1) end,
                  log=function(t) log.lines[#log.lines + 1] = t end}
    return deps, io, log
end
"""


def _mons():
    rng = random.Random(23)
    mons = [_mon(rng, species) for species in SPECIES]
    for mon in mons:
        mon["is_egg"] = False
    return mons


def _key(mon):
    """The planted mon's key from its generator fields (packed DV nibbles), independent of any decoder."""
    nibbles = [mon["dvs"][name] for name in pc.STAT_NAMES]
    dv_bytes = int("".join(f"{n:X}" for n in nibbles), 16)
    return pc.key(dict(mon, dv_bytes=dv_bytes))


def _memory(mons):
    """System Bus bytes at the overlay .sym's own addresses (not the profile's)."""
    mem = {}

    def put(label, data, offset=0):
        bank, base = SYM[label]
        for i, value in enumerate(data):
            mem[base + offset + i] = value

    put("wPartyCount", [len(mons)])
    for slot, (mon, (ot, nick)) in enumerate(zip(mons, NAMES, strict=True)):
        put("wPartyMons", pc.encode_party_mon(mon), slot * 48)
        put("wPartyMonOTs", pc.encode_text(ot, 8) + bytes(3), slot * 11)
        put("wPartyMonNicknames", pc.encode_text(nick, 11), slot * 11)
    put("wPlayerID", OT_ID.to_bytes(2, "big"))
    put("wPlayerName", pc.encode_text("KRIS", 11))
    put("wNumBalls", [1, 1, 5, 0xFF])  # one stack: 5 Poke Balls, then the terminator
    put("wJohtoBadges", [0x03, 0x00])
    put("wMapGroup", [24, 4, 5, 6])
    put("wMapStatus", [2])  # MAPSTATUS_HANDLE: the overworld loop is running (docs/polished/HELLO_GATE.md)
    # the companion's mailbox signature (patch/polished/src/slink.asm): 'SLNK', ABI 3 at +4, caps 0, cookie $A5 at +31
    put("wSlinkMailbox", [0x53, 0x4C, 0x4E, 0x4B, 3, 0, 0, 0, 0])
    put("wSlinkMailbox", [0xA5], 31)
    return mem


def _rig(lua, rom, mem):
    deps, io, log = lua.execute(HARNESS.replace("ROOTDIR", json.dumps(ROOT)))(rom, lua.table_from(mem))
    return deps, io, log


def _entry(lua):
    return lua.eval(f'dofile("{ROOT}/lua/gen2/entry.lua")')


def _run(io, client, frames):
    for _ in range(frames):
        io.frame += 1
        client.frame_end(client)


@pytest.fixture(scope="module")
def roms():
    return _real()


@pytest.fixture(scope="module")
def composed(roms):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    mons = _mons()
    deps, io, log = _rig(lua, roms[1], _memory(mons))
    parts, why = _pair(_entry(lua).build(deps))
    assert why is None, why
    return lua, mons, parts, io, log


def _hello(composed):
    lua, mons, parts, io, log = composed
    if not parts.client.hello_sent:
        parts.client.start(parts.client)
        _run(io, parts.client, 20)  # hello_unheld waits for a stable party (8 consecutive polls)
    hellos = [json.loads(line) for line in log.sent.values() if json.loads(line)["event"] == "hello"]
    assert len(hellos) == 1, list(log.lines.values())
    return hellos[0]


# ── (a) the overlay composes and its hello is admitted by the real server ────

def test_the_overlay_composes_a_dev_grade_client(composed):
    _, _, parts, _, _ = composed
    assert parts.client is not None and parts.title == "polished" and parts.pack == "polished_crystal"
    assert parts.qualification == "DEV_OVERLAY_SHA1" and parts.production_admitted is False
    assert parts.artifact_kind == "overlay" and parts.runtime_rom_sha1 == PROFILE["source"]["overlay_sha1"]
    assert parts.checkpoint is None and parts.client.rom_type == "polished_crystal"


def test_the_hello_carries_the_party_and_the_companion_evidence(composed):
    hello = _hello(composed)
    _, mons, _, _, _ = composed
    assert (hello["rom_type"], hello["foundation"], hello["artifact_kind"]) == ("polished_crystal", "gen2_polished", "overlay")
    assert hello["rom_sha1"] == PROFILE["source"]["overlay_sha1"]
    assert hello["companion_abi"] == 3 and hello["panel"] is False and hello["sfx"] is False
    assert (hello["ot_id"], hello["trainer_name"], hello["ball_count"], hello["badges"]) == (OT_ID, "KRIS", 5, 3)
    # the C-BOX census is composed read-only, but this WRAM image has no real save (no sSaveVersion/sChecksum
    # anchors), so it is not a COMPLETE census: pc_boxes stays [] with no generation
    assert hello["pc_boxes"] == [] and "pc_boxes_generation" not in hello
    assert (hello["area_id"], hello["loc_name"], hello["in_battle"]) == ("new_bark_town", "New Bark Town", False)
    party = hello["party"]
    assert [e["key"] for e in party] == [_key(m) for m in mons]
    assert [(e["species_id"], e["level"], e["slot"]) for e in party] == [(m["species_id"], m["level"], i)
                                                                      for i, m in enumerate(mons)]
    for entry, mon, (ot, nick) in zip(party, mons, NAMES, strict=True):
        assert len(entry["blob_hex"]) == 140
        assert entry["blob_hex"] == (pc.encode_party_mon(mon) + pc.encode_text(ot, 8) + bytes(3)
                                     + pc.encode_text(nick, 11)).hex()
        assert entry["nickname"] == nick


@pytest.mark.asyncio
async def test_the_real_server_admits_the_captured_hello(composed, tmp_path):
    from server.server import SLinkServer
    hello = _hello(composed)
    _, mons, _, _, _ = composed
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send(hello)
        assert not _refused(reply) and not srv.state.identity_error.get("a"), srv.state.identity_error
        assert srv.is_admitted("a") and srv.state.rom_type == "polished_crystal"
        assert srv.state.artifact_kind == "overlay" and srv.adapter.game_id == "gen2_polished"
        keys = [_key(m) for m in mons]
        assert set(srv.state.party_keys["a"]) == set(keys)
        details = srv.party_details["a"]
        assert [(details[k]["species_id"], details[k]["level"]) for k in keys] == [(m["species_id"], m["level"])
                                                                                for m in mons]
        assert details[keys[1]]["species_id"] == 291
        for entry, mon in zip(hello["party"], mons, strict=True):
            decoded = srv.adapter.decode_party_blob(entry["blob_hex"])
            assert pc.key(decoded) == _key(mon) and decoded["species_id"] == mon["species_id"]
    finally:
        await close()


# ── (d) nothing is hooked, nothing is written ────────────────────────────────

def test_no_hook_and_no_write_on_the_whole_path(composed):
    _hello(composed)
    lua, _, parts, io, log = composed
    _run(io, parts.client, 60)  # a tick, a validate, a box rescan
    # C-WRITE r2: the composition also hooks the overworld HOLD site (25:51BF, SLink-gen2-checkpoint);
# the hook registers nothing on its own and writes nothing without a command.
    # C-EXPLODE: the composition also hooks the battle hold (0f:416A, SLink-gen2-battle-hold): the explode PC hold, nothing written on its own.
    # the default rival set (RIVAL0/1/2, owner 2026-10-08) registers the native rival gate hook; it still writes nothing
    assert set(log.hooks.values()) <= {'SLink-gen2-polished:capture_party', 'SLink-gen2-polished:battle_faint', 'SLink-gen2-checkpoint', 'SLink-gen2-battle-hold',
        'SLink-gen2-polished:rival_swap_gate'} and len(log.writes) == 0
    ticks = [json.loads(line) for line in log.sent.values() if json.loads(line)["event"] == "tick"]
    assert ticks and ticks[-1]["party"] == _hello(composed)["party"]
    parts.client.stop(parts.client)
    # C-WRITE r2: the composition also hooks the overworld HOLD site (25:51BF, SLink-gen2-checkpoint);
# the hook registers nothing on its own and writes nothing without a command.
    # C-EXPLODE: the composition also hooks the battle hold (0f:416A, SLink-gen2-battle-hold): the explode PC hold, nothing written on its own.
    assert set(log.hooks.values()) <= {'SLink-gen2-polished:capture_party', 'SLink-gen2-polished:battle_faint', 'SLink-gen2-checkpoint', 'SLink-gen2-battle-hold',
        'SLink-gen2-polished:rival_swap_gate'}


def test_the_production_signals_gate_refuses_polished():
    """Signals.new (the only path that registers engine-site hooks in production) has no Polished receipt path;
    the model binder refuses the Polished SOURCE_CANDIDATE pack by name, before any registration."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    signals = lua.eval(f'dofile("{ROOT}/lua/gen2/signals.lua")')
    data = lambda name: lua.table_from(  # noqa: E731
        json.loads((REPO / f"data/games/polished_crystal/{name}.json").read_text(encoding="utf-8")), recursive=True)
    hooks = []
    io = lua.table(model_only=True, bank_valid=lambda *a: True,
                   on_bus_exec=lambda fn, addr, name, d=None: hooks.append(name))
    authority = lua.table(kind="MODEL_PROBE", allow_model_registration=True, capture=lambda: 1, valid=lambda s: True)
    key_fn = load_variants(lua, lua.eval(f'dofile("{ROOT}/lua/gen2/polished.lua")')).mon_key
    options = lua.table(title="polished", profile=data("profile"), pack=data("engine_signals"), io=io,
                        authority=authority, key_fn=key_fn, runtime_qualification=lua.table())
    binder, why = signals.new(options)
    assert binder is None and "OPEN for polished" in why
    binder, why = signals.new_model(options)[:2]
    assert binder is None and "engine-site schemas required" in why
    assert hooks == []


# ── (b) the clean release and a random ROM compose nothing ───────────────────

def test_the_clean_release_and_a_random_rom_get_no_client(roms):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    random_rom = bytearray(random.Random(9).randbytes(len(roms[0])))
    random_rom[0x134:0x13E] = b"PKPCRYSTAL"
    for rom, expect in ((roms[0], "companion patch"), (bytes(random_rom), "unknown artifact SHA-1")):
        deps, io, log = _rig(lua, rom, _memory(_mons()))
        parts, why = _pair(_entry(lua).build(deps))
        assert parts is None and expect in why
        # C-WRITE r2: the composition also hooks the overworld HOLD site (25:51BF, SLink-gen2-checkpoint);
# the hook registers nothing on its own and writes nothing without a command.
        # C-EXPLODE: the composition also hooks the battle hold (0f:416A, SLink-gen2-battle-hold): the explode PC hold, nothing written on its own.
        assert set(log.hooks.values()) <= {'SLink-gen2-polished:capture_party', 'SLink-gen2-checkpoint', 'SLink-gen2-battle-hold'} and len(log.writes) == 0


# ── C-SIGNALS: the binder's title facts come from the profile ────────────────

def _relabelled(num_boxes=None, area_types=None, key_fn=True, overrides=POLISHED[:1]):
    """The model World's binder with its profile/pack re-titled "polished" (only the facts under test changed)."""
    world = World()
    lua = world.lua
    reads = world.reads
    world.reads = lua.eval("""function(reads, over)
        return setmetatable({read_party=function()
            local party, why = reads.read_party()
            if party then for i, mon in ipairs(party.mons) do for k, v in pairs(over[i] or {}) do mon[k] = v end end end
            return party, why
        end}, {__index=reads})
    end""")(reads, lua.table_from([lua.table_from(o) for o in overrides]))
    options = world.options
    profile, pack = json.loads(json.dumps(world.profile)), json.loads(json.dumps(world.pack))
    title = profile["titles"].pop("crystal")
    if num_boxes is not None:
        title["constants"]["NUM_BOXES"] = num_boxes
    if area_types is not None:
        title["derived"]["area_battle_types"] = area_types
    profile["titles"]["polished"], pack["titles"]["polished"] = title, pack["titles"].pop("crystal")
    fields = {"title": "polished", "profile": lua.table_from(profile, recursive=True),
              "pack": lua.table_from(pack, recursive=True)}
    if key_fn:
        fields["key_fn"] = load_variants(lua, lua.eval(f'dofile("{ROOT}/lua/gen2/polished.lua")')).mon_key
    world.options = lambda: _with(options(), **fields)
    return world


def test_the_polished_title_binds_only_with_its_key_builder():
    assert _relabelled(num_boxes=20).bind() is not None
    world = _relabelled(key_fn=False)
    assert "selected Gen 2 title required" in world.module.new_model(world.options())[1]


def _box_refusal(world, requested):
    binder = world.bind()
    world.reg["DE"] = requested
    world.fire("change_box_begin")
    world.events(binder)
    return binder.status(binder).refusals["change_box_begin"]


@pytest.mark.parametrize("make,last", [(lambda: _relabelled(num_boxes=20), 19), (World, 13)], ids=["polished", "vanilla"])
def test_the_box_change_bound_is_the_profile_num_boxes(make, last):
    assert _box_refusal(make(), last) is None
    assert "box-change context unavailable" in _box_refusal(make(), last + 1)


def _wild_capture(world, battle_type):
    binder = world.bind()
    world.field("wBattleType", battle_type)
    world.fire("capture_party")
    world.events(binder)
    world.party([world.mon(nickname=0x82)])
    world.fire("capture_party_finalized")
    return [event for event in world.events(binder) if event.kind == "capture"]


@pytest.mark.parametrize("make,resolving,refused", [
    (lambda: _relabelled(area_types=[0, 3, 4]), (0, 3, 4), (8,)),  # Polished: NORMAL, FISH, TREE (GHOST 8 is not)
    (World, (0, 4, 8), (3,)),                                     # vanilla: NORMAL, FISH 4, TREE 8
], ids=["polished", "vanilla"])
def test_the_area_battle_types_are_the_profile_set(make, resolving, refused):
    for battle_type in resolving:
        (event,) = _wild_capture(make(), battle_type)
        assert event.acquisition == "wild"
    for battle_type in refused:
        assert _wild_capture(make(), battle_type) == []

