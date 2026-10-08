"""POL-BATTLE: the Polished battle sites, the exploded/rival write windows, and their wiring.

What is proved here, in process, over the REAL overlay ROM (patch/dist/SLink-Polished.ups on the pinned
release) and a synthetic WRAM image laid out from data/polished/polishedcrystal.sym:

  * every battle PC is the byte sequence the generated pack claims (data/games/polished_crystal/
    engine_signals.json), read back out of the ROM here, not taken from the pack;
  * each site is reached only on the path it names -- trainer_ready is the trainer branch of InitEnemy,
    not its head; rival_swap_gate is SendInUserPkmn's ENEMY branch, whose sibling the player branch skips;
    wild_ready is the branch InitEnemy jumps to when wOtherTrainerClass reads 0;
  * Explode Mode writes ONLY when the server ordered it, ONLY for the player's own active battler, and
    writes the Polished EXPLOSION id (read from data/games/polished_crystal/moves.json, not hardcoded),
    move slot first, PP read-modify-write keeping the two PP-Up bits, party mirror, wCurPlayerMove LAST;
  * the Rival Team Swap writes only at the rival gate PC, only in a trainer battle, and never touches
    wMirrorHerbPendingBoosts (01:d284);
  * a wrong ROM byte at any battle PC registers nothing (all-or-nothing) and names the site.

What this CANNOT prove (no cartridge): that BizHawk's exec hook sees these PCs as instruction starts on a
running Polished ROM. The binder stays DEV_OVERLAY / physical_status OPEN, as it does for capture_party.
"""
from __future__ import annotations

import json
import re

import pytest

from server.adapters import polished_codec as pc
from tests.unit.test_polished_lua import PROFILE, REPO, ROOT, _real, _sym

lupa = pytest.importorskip("lupa")
LuaError = lupa.LuaError

# ── the battle PCs, each as the byte sequence the pack pins it by ────────────────────────────────
BATTLE_FAINT, COPYBACK_CALL = 0x44C8, 0x44CA          # ResolveFaints.no_fainted_mons +1 / +3
EXPLODE_HOLD = 0x416A                                   # call DetermineMoveOrder, inside BattleTurn
RIVAL_COMMIT, RIVAL_GATE, RIVAL_LAST = 0x47CC, 0x47DD, 0x480D   # SendInUserPkmn
PLAYER_BRANCH = 0x47D8                                  # ld hl, wPartyMon1 -- the branch that SKIPS the gate
WILD_READY, TRAINER_READY, INIT_ENEMY = 0x72BC, 0x7271, 0x7260
BATTLE_END = 0x72E0
HROMBANK = 0xFF87
MOVE_SLOT = 2                       # wCurMoveNum: the move index every explode write lands on
SYM = _sym()


def _flat(bank: int, addr: int) -> int:
    return addr if bank == 0 else bank * 0x4000 + (addr - 0x4000)


# The Lua rig: loads the generated packs and the three real modules off disk, registers the sites through
# the shared registry + GB binding, and records every write. `state` is the seam the test drives.
RIG = """
return function(rom, mem, with_writes, overrides)
    local root = ROOTDIR
    local json = dofile(root .. "/lua/json_codec.lua")
    local function readfile(path)
        local handle = assert(io.open(root .. "/" .. path, "rb"))
        local text = handle:read("*a")
        handle:close()
        return text
    end
    local function pack_of(path) return json.decode(readfile(path)) end
    local profile = pack_of("data/games/polished_crystal/profile.json").titles.polished
    local signals = pack_of("data/games/polished_crystal/engine_signals.json")
    local hold = pack_of("data/games/polished_crystal/write_checkpoint.json")

    local log = {hooks = {}, writes = {}, lines = {}, rom_override = {}}
    for offset, value in pairs(overrides or {}) do log.rom_override[offset] = value end
    local io = {frame = 0, pc = 0, mem = mem}
    local function rom_u8(a) return log.rom_override[a] or rom:byte(a + 1) end
    function io.read_u8(a, d)
        if d == "ROM" then return rom_u8(a) end
        if a < 0x4000 then return rom_u8(a) end
        if a < 0x8000 then return rom_u8((mem[HROMBANK] or 1) * 0x4000 + a - 0x4000) end
        return mem[a] or 0
    end
    function io.read_range(a, n, d) local out = {} for i = 1, n do out[i] = io.read_u8(a + i - 1, d) end return out end
    function io.write_u8(a, v, d)
        assert(d == "System Bus")
        mem[a] = v
        log.writes[#log.writes + 1] = {addr = a, value = v}
    end
    function io.bank_valid() return true end
    function io.domain_size(d) return d == "ROM" and #rom or 0x8000 end
    function io.framecount() return io.frame end
    function io.on_bus_exec(fn, addr, name)
        log.hooks[#log.hooks + 1] = {fn = fn, addr = addr, name = name}
        return #log.hooks
    end
    function io.unregister(handle) log.hooks[handle] = false return true end
    function io.register(name) if name == "PC" then return io.pc end return 0xDFF0 end

    local Signals, Registry, GB = dofile(root .. "/lua/gen2/signals.lua"), dofile(root .. "/lua/hook_registry.lua"),
                                  dofile(root .. "/lua/gb_hook_binding.lua")
    local Battle, Permit = dofile(root .. "/lua/gen2/polished_battle.lua"), dofile(root .. "/lua/write_permit.lua")

    local state = {explode_slot = nil, rival = nil, epoch = 1, authorized = true}
    local seams = {
        pending_explode = function() return state.explode_slot end,
        pending_rival = function() return state.rival end,
        exploded = function(slot) state.exploded = slot end,
        explode_refused = function(why) state.explode_why = tostring(why) end,
        rival_applied = function(mons) state.applied = #mons end,
        rival_refused = function(why) state.rival_why = tostring(why) end,
    }
    local policy = {
        authorize = function() return state.authorized == true end,
        pointer_stable = function() return true end,
        lifetime = {capture = function() return state.epoch end, valid = function(token) return token == state.epoch end},
        provenance = function() return {site = "MODEL polished battle window"} end,
    }
    local battle = Battle.compose({root = root, io = io, profile = profile, coords = COORDS,
                                   pack = signals, hold = hold, seams = seams,
                                   Permit = with_writes and Permit or nil, policy = with_writes and policy or nil,
                                   log = function(t) log.lines[#log.lines + 1] = t end})
    local binder, why = Signals.new_polished({
        title = "polished", qualification = "DEV_OVERLAY_SHA1", profile = profile, pack = signals, io = io,
        -- MODEL identities only: this standalone battle rig does not decode real party records.
        reads = {read_party = function() return {count=3, mons={
            {slot=0,is_egg=false,key="MODEL:0"}, {slot=1,is_egg=false,key="MODEL:1"},
            {slot=2,is_egg=false,key="MODEL:2"}}} end}, key_fn = function(mon) return mon and mon.key end,
        areas = {}, authority = {capture = function() return {generation = 1, operation = "op-1"} end,
                                 valid = function() return true end},
        Registry = Registry, GB = GB, owner = "SLink-gen2-polished", max_pending = 64,
        battle_sites = battle.sites, on_write_window = battle.on_write_window,
    })
    return {battle = battle, binder = binder, why = why, io = io, log = log, state = state, mem = mem}
end
"""

EXPLOSION = next(m["id"] for m in json.loads((REPO / "data/games/polished_crystal/moves.json").read_text(
    encoding="utf-8"))["moves"] if m["constant"] == "EXPLOSION")
MOVE_CONSTANTS = {m["constant"] for m in json.loads(
    (REPO / "data/games/polished_crystal/moves.json").read_text(encoding="utf-8"))["moves"]}


@pytest.fixture(scope="module")
def roms():
    return _real()


def _put(mem, label, data, offset=0):
    _, base = SYM[label]
    for i, value in enumerate(data):
        mem[base + offset + i] = value


def _rig(roms, *, with_writes=True, override=None):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    mem = {}
    # a battle in progress: 3 mons, slot 1 active, move 2 chosen (wBattlePlayerAction 0 == USEMOVE)
    _put(mem, "wPartyCount", [3])
    _put(mem, "wBattleMode", [1])            # wild
    _put(mem, "wLinkMode", [0])
    _put(mem, "wCurBattleMon", [1])
    _put(mem, "wCurMoveNum", [2])
    _put(mem, "wBattlePlayerAction", [0])
    _put(mem, "wBattleMonPP", [0xC5], 2)     # 3 PP Ups, 5 PP
    _put(mem, "wPartyMons", [0x87], 48 + 22 + 2)   # 2 PP Ups, 7 PP on the same move of slot 1
    _put(mem, "wBattleMonHP", [0x20, 0x00])   # little-endian
    _put(mem, "wBattleMonMaxHP", [0x50, 0x00])
    rig = lua.execute(RIG.replace("ROOTDIR", json.dumps(ROOT)).replace("COORDS", _coords_literal())
                      .replace("HROMBANK", str(HROMBANK)))(roms[1], lua.table_from(mem), with_writes,
                                                                 lua.table_from(override or {}))
    return lua, rig


def _coords() -> dict:
    body = (REPO / "lua/gen2/polished_writes.lua").read_text(encoding="utf-8")
    block = re.search(r"W\.COORDS = \{(.*?)\}", body, re.S).group(1)
    return {label: list(SYM[label]) for label in re.findall(r'"([^"]+)"', block)}


def _coords_literal() -> str:
    """A LUA table literal: this text is compiled, so JSON's `:` separators would not parse."""
    return "{" + ",".join(f'["{label}"]={{{row[0]},{row[1]}}}'
                          for label, row in _coords().items()) + "}"


def _binder_options(lua, pack=None):
    """The minimum new_polished options a refusal test needs. The GB binding is constructed before the
    battle rows are checked, so its io must be complete even where the refusal happens first."""
    signals = lua.eval(f'dofile("{ROOT}/lua/gen2/signals.lua")')
    io = lua.table(read_u8=lambda *a: 0, read_range=lambda *a: {}, register=lambda *a: 0,
                   framecount=lambda: 0, on_bus_exec=lambda *a: 1, unregister=lambda *a: True,
                   bank_valid=lambda *a: True)
    options = {"title": "polished", "qualification": "DEV_OVERLAY_SHA1",
               "profile": lua.table_from(PROFILE["titles"]["polished"], recursive=True),
               "pack": lua.table_from(pack if pack is not None else
                                      json.loads((REPO / "data/games/polished_crystal/engine_signals.json")
                                                 .read_text(encoding="utf-8")), recursive=True),
               "io": io, "reads": lua.table(read_party=lambda: None), "key_fn": lambda m: None,
               "authority": lua.table(capture=lambda: None, valid=lambda s: True),
               "Registry": lua.eval(f'dofile("{ROOT}/lua/hook_registry.lua")'),
               "GB": lua.eval(f'dofile("{ROOT}/lua/gb_hook_binding.lua")'), "owner": "x", "max_pending": 8}
    return signals, options


def _hooks(rig):
    return [h for h in rig.log.hooks.values() if h]


def _fire(rig, pc_, bank=0x0F):
    """Set the PC/bank the engine is at and run every hook registered there (gb_hook_binding re-checks both)."""
    fired = []
    rig.io.mem[HROMBANK] = bank
    rig.io.pc = pc_
    for hook in _hooks(rig):
        if hook.addr == pc_:
            fired.append(pc_)
            hook.fn()
    return fired


def _events(rig):
    binder = rig.binder
    return [event for batch in binder.drain(binder).values() for event in batch.events.values()]


def _writes(rig):
    return [(w.addr, w.value) for w in rig.log.writes.values()]


def _mon(species, *, hp=30, form=0, pp_ups=(0, 1, 2, 3)):
    return pc.encode_party_mon({
        "species_id": species, "gender": "male", "is_egg": False, "form": form, "shiny": False,
        "ability_slot": 0, "nature": 0, "held_item": 0, "moves": [1, 2, 3, 4], "ot_id": 0x1234, "exp": 1000,
        "evs": dict.fromkeys(pc.STAT_NAMES, 0), "dvs": dict.fromkeys(pc.STAT_NAMES, 15),
        "pp": [10, 20, 30, 5], "pp_ups": list(pp_ups), "happiness": 70, "pokerus": 0, "caught_data": 0,
        "caught_level": 5, "caught_location": 0, "level": 20, "status": 0, "unused": 0, "hp": hp, "max_hp": 50,
        "stats": dict.fromkeys(pc.STAT_NAMES[1:], 40)})


def _team(lua, count=3):
    return lua.table_from([{"record": list(_mon(25 + i)), "ot": [0x80 + i] + [0x53] * 10,
                            "nick": [0x90 + i] + [0x53] * 10} for i in range(count)], recursive=True)


# ── (1) the pack's PCs are the ROM's bytes ─────────────────────────────────────────────────────────

def test_every_battle_pc_is_the_bytes_the_pack_pins(roms):
    pack = json.loads((REPO / "data/games/polished_crystal/engine_signals.json").read_text(encoding="utf-8"))
    sites = pack["titles"]["polished_crystal"]["sites"]
    rom = roms[1]
    for name, pc_ in (("battle_faint", BATTLE_FAINT), ("explode_hold", EXPLODE_HOLD),
                      ("rival_swap_gate", RIVAL_GATE), ("battle_end", BATTLE_END),
                      ("wild_ready", WILD_READY), ("trainer_ready", TRAINER_READY)):
        site = sites[name]
        assert (site["bank"], site["addr"]) == (0x0F, pc_), name
        assert site["expected_hex"] == site["find_hex"] and site["find_hex"] is not None, name
        flat = _flat(site["bank"], site["addr"])
        assert rom[flat:flat + site["hex_len"]].hex().upper() == site["expected_hex"], name
        assert not any(s["start"] <= flat + site["hex_len"] - 1 and flat <= s["end"]
                       for s in pack["companion_overlay_spans"]), name


def test_the_battle_faint_boundary_and_the_call_that_consumes_it(roms):
    rom = roms[1]
    assert rom[_flat(0x0F, BATTLE_FAINT):_flat(0x0F, BATTLE_FAINT) + 2].hex() == "e0d1"       # ldh [$d1],a
    assert rom[_flat(0x0F, COPYBACK_CALL):_flat(0x0F, COPYBACK_CALL) + 3].hex() == "cdb034"  # call UpdateBattleMonInParty


def test_trainer_ready_is_the_trainer_branch_of_init_enemy_not_its_head(roms):
    """The capture_party lesson: a routine head fires on the wrong path. InitEnemy's `jr z, .wildmon`
    jumps OVER the trainer branch, so only the fall-through reaches trainer_ready -- and the wild branch
    is what the head does reach."""
    rom = roms[1]
    assert rom[_flat(0x0F, INIT_ENEMY):_flat(0x0F, INIT_ENEMY) + 2].hex() == "fa35"       # ld a,[wOtherTrainerClass]
    assert rom[_flat(0x0F, INIT_ENEMY) + 3:_flat(0x0F, INIT_ENEMY) + 4].hex() == "a7"       # and a
    jr_at = _flat(0x0F, INIT_ENEMY) + 4                                                  # jr z, .wildmon
    assert rom[jr_at] == 0x28 and rom[jr_at + 1] == WILD_READY - (INIT_ENEMY + 6)
    # the trainer branch it jumps over: ld [wTrainerClass],a / xor a / ld [wTempEnemyMonSpecies],a / farcall
    assert rom[_flat(0x0F, INIT_ENEMY) + 6:_flat(0x0F, INIT_ENEMY) + 12].hex() == "ea38d2afea2e"
    assert INIT_ENEMY + 6 < TRAINER_READY < WILD_READY                                        # the branch lies between


def test_rival_swap_gate_is_the_enemy_branch_that_the_player_branch_skips(roms):
    rom = roms[1]
    assert rom[_flat(0x0F, PLAYER_BRANCH):_flat(0x0F, PLAYER_BRANCH) + 3].hex() == "21d6dc"  # ld hl, wPartyMon1
    jr = _flat(0x0F, PLAYER_BRANCH) + 3
    assert rom[jr] == 0x28 and rom[jr + 1] == (RIVAL_GATE + 3) - (PLAYER_BRANCH + 5)        # jr +3 over the gate
    assert rom[_flat(0x0F, RIVAL_GATE):_flat(0x0F, RIVAL_GATE) + 3].hex() == "218bd2"         # ld hl, wOTPartyMon1Species
    assert RIVAL_GATE == PLAYER_BRANCH + 5


# ── (2) what is registered ───────────────────────────────────────────────────────────────────────

def test_only_the_named_battle_sites_are_registered(roms):
    _, rig = _rig(roms)
    assert rig.why is None, rig.why
    assert [(h.name, h.addr) for h in _hooks(rig)] == [
        ("SLink-gen2-polished:capture_party", 0x652B),
        ("SLink-gen2-polished:battle_faint", BATTLE_FAINT),
        ("SLink-gen2-polished:battle_end", BATTLE_END),
        ("SLink-gen2-polished:wild_ready", WILD_READY),
        ("SLink-gen2-polished:trainer_ready", TRAINER_READY),
        ("SLink-gen2-polished:explode_hold", EXPLODE_HOLD),
        ("SLink-gen2-polished:rival_swap_gate", RIVAL_GATE),
    ]
    status = rig.binder.status(rig.binder)
    assert list(status.registered_sites.values()) == ["capture_party", "battle_faint", "battle_end", "wild_ready",
                                                   "trainer_ready", "explode_hold", "rival_swap_gate"]
    assert (status.evidence_level, status.physical_status, status.runtime_authorized) == ("DEV_OVERLAY", "OPEN", False)


def test_a_wrong_rom_byte_at_any_battle_pc_registers_nothing(roms):
    _, rig = _rig(roms, override={_flat(0x0F, EXPLODE_HOLD): 0x00})
    assert _hooks(rig) == [] and "explode_hold" in str(rig.why)   # all-or-nothing; entry.lua degrades
    # ... and the binder itself refuses the row, naming the site: the PC must still be its own bytes
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    signals, options = _binder_options(lua)
    doctored = json.loads((REPO / "data/games/polished_crystal/engine_signals.json").read_text(encoding="utf-8"))
    doctored["titles"]["polished_crystal"]["sites"]["explode_hold"]["expected_hex"] = "CD3543"
    options["pack"] = lua.table_from(doctored, recursive=True)
    options["battle_sites"] = lua.table_from(["explode_hold"])
    options["on_write_window"] = lambda *a: None
    assert "byte sequence" in signals.new_polished(lua.table_from(options, recursive=False))[1]


def test_a_battle_site_absent_from_the_pack_is_refused_by_name():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    signals, options = _binder_options(lua)
    doctored = json.loads((REPO / "data/games/polished_crystal/engine_signals.json").read_text(encoding="utf-8"))
    del doctored["titles"]["polished_crystal"]["sites"]["rival_swap_gate"]
    options["pack"] = lua.table_from(doctored, recursive=True)
    options["battle_sites"] = lua.table_from(["rival_swap_gate"])
    assert "absent from the generated Polished engine-site pack" in signals.new_polished(
        lua.table_from(options, recursive=False))[1]


# ── (3) observations: the battle bracket ─────────────────────────────────────────────────────────

def test_the_three_battle_observations_carry_the_site_the_client_keys_on(roms):
    _, rig = _rig(roms)
    assert _fire(rig, TRAINER_READY) == [TRAINER_READY]
    assert _fire(rig, WILD_READY) == [WILD_READY]
    assert _fire(rig, BATTLE_END) == [BATTLE_END]
    events = _events(rig)
    assert [e.site_id for e in events] == ["trainer_ready", "wild_ready", "battle_end"]
    assert all(e.kind == "observation" and e.evidence_level == "DEV_OVERLAY" for e in events)


def test_a_wild_flee_fires_no_rival_swap_and_no_explode(roms):
    """A fleeing wild battle runs InitEnemy's wild branch, SendInUserPkmn's PLAYER branch (which skips the
    rival gate), and never reaches the turn-order call."""
    lua, rig = _rig(roms)
    rig.state.explode_slot, rig.state.rival = 1, _team(lua)     # both owed -- neither may fire
    _put(rig.mem, "wBattleMode", [1])
    assert _fire(rig, PLAYER_BRANCH) == []      # the player send-out branch: no site, and the rival gate
    assert _fire(rig, INIT_ENEMY) == []         # the routine head is NOT a site
    assert _fire(rig, BATTLE_FAINT) == [BATTLE_FAINT]
    assert _fire(rig, BATTLE_END) == [BATTLE_END]
    assert ("SLink-gen2-polished:rival_swap_gate", RIVAL_GATE) in {(h.name, h.addr) for h in _hooks(rig)}
    assert _writes(rig) == []
    assert [e.site_id for e in _events(rig)] == ["battle_faint", "battle_end"]


def test_the_battle_faint_observation_is_keyed_on_the_battle_struct(roms):
    _, rig = _rig(roms)
    _put(rig.mem, "wBattleMode", [1])
    _put(rig.mem, "wCurBattleMon", [2])
    _put(rig.mem, "wBattleMonHP", [0x00, 0x00])
    _put(rig.mem, "wBattleMonMaxHP", [0x50, 0x00])
    assert _fire(rig, BATTLE_FAINT) == [BATTLE_FAINT]
    event, faint = _events(rig)
    assert event.site_id == "battle_faint" and event.phase == "before_party_copyback"
    assert (event.battle.slot, event.battle.hp, event.battle.max_hp, event.battle.mode) == (2, 0, 80, 1)
    assert faint.kind == "faint" and faint.slot == 2 and faint.mon.key == "MODEL:2"
    assert faint.mon.is_egg is False
    # the boundary is not faint-only: a live battler reports the same site, and no write ever rides it
    _, rig2 = _rig(roms)
    _put(rig2.mem, "wBattleMode", [1])
    _put(rig2.mem, "wBattleMonHP", [0x20, 0x00])
    _fire(rig2, BATTLE_FAINT)
    (event,) = _events(rig2)
    assert event.battle.hp == 32 and _writes(rig2) == []
    assert event.kind == "observation"  # exactly one event above: no natural faint while alive


# ── (4) Explode Mode ──────────────────────────────────────────────────────────────────────────────

def test_the_polished_explosion_id_comes_from_the_move_table():
    assert EXPLOSION == 0x99                       # constants/move_constants.asm:161 `const EXPLOSION ; $99`
    assert "EXPLOSION" in MOVE_CONSTANTS
    assert "SELFDESTRUCT" not in MOVE_CONSTANTS    # Polished has no Selfdestruct: Explosion is the only self-KO


def test_the_explode_window_writes_the_move_the_pp_ups_the_mirror_and_the_choice_last(roms):
    lua, rig = _rig(roms)
    rig.state.explode_slot = 1
    assert _fire(rig, EXPLODE_HOLD) == [EXPLODE_HOLD]
    (event,) = _events(rig)
    assert event.site_id == "explode_hold" and event.write.reason == "battle_hold"
    assert (event.write.slot, event.write.move) == (1, EXPLOSION)
    battle_moves, battle_pp = SYM["wBattleMonMoves"][1], SYM["wBattleMonPP"][1]
    party = SYM["wPartyMons"][1] + 48                      # party slot 1
    assert _writes(rig) == [(battle_moves + MOVE_SLOT, EXPLOSION), (battle_pp + MOVE_SLOT, 0xC1),
                            (party + 2 + MOVE_SLOT, EXPLOSION), (party + 22 + MOVE_SLOT, 0x81),
                            (SYM["wCurPlayerMove"][1], EXPLOSION)]      # wCurPlayerMove LAST
    assert rig.state.exploded == 1


def test_nothing_is_written_when_the_server_ordered_no_explode(roms):
    _, rig = _rig(roms)
    assert _fire(rig, EXPLODE_HOLD) == [EXPLODE_HOLD]      # the site fires every turn ...
    assert _writes(rig) == [] and _events(rig) == []       # ... and publishes nothing


def test_an_explode_for_a_bench_mon_or_a_link_battle_is_refused(roms):
    lua, rig = _rig(roms)
    rig.state.explode_slot = 0                           # slot 0 is benched: wCurBattleMon reads 1
    _fire(rig, EXPLODE_HOLD)
    assert _writes(rig) == [] and "not the active battler" in str(rig.state.explode_why or "")
    _put(rig.mem, "wLinkMode", [1])                      # a link battle never writes
    rig.state.explode_slot, rig.state.explode_why = 1, None
    _fire(rig, EXPLODE_HOLD)
    assert _writes(rig) == [] and rig.state.explode_why == "not a solo battle"


def test_the_explode_window_refuses_a_context_taken_off_its_own_pc(roms):
    _, rig = _rig(roms)
    with pytest.raises(LuaError):
        rig.battle.on_write_window("explode_hold", {"bank": 0x0F, "pc": COPYBACK_CALL})


# ── (5) Rival Team Swap ───────────────────────────────────────────────────────────────────────────

def test_the_rival_gate_writes_the_partys_team_and_never_the_mirror_herb(roms):
    lua, rig = _rig(roms)
    _put(rig.mem, "wBattleMode", [2])                    # TRAINER_BATTLE
    _put(rig.mem, "wCurOTMon", [0])                      # committed at 0f:47cc, before the copy
    _put(rig.mem, "wCurPartyMon", [0])
    rig.state.rival = _team(lua, 3)
    herb = SYM["wMirrorHerbPendingBoosts"][1]
    before = rig.mem[herb] or 0
    assert _fire(rig, RIVAL_GATE) == [RIVAL_GATE]
    (event,) = _events(rig)
    assert event.site_id == "rival_swap_gate" and event.write.reason == "rival_swap"
    assert (event.write.count, event.write[1], event.write[3]) == (3, 25, 27)   # Species bytes, +0 each
    assert rig.mem[SYM["wOTPartyCount"][1]] == 3
    assert rig.state.applied == 3
    assert all(w.addr != herb for w in rig.log.writes.values())
    assert (rig.mem[herb] or 0) == before


def test_a_wild_battle_at_the_gate_writes_nothing(roms):
    lua, rig = _rig(roms)
    _put(rig.mem, "wBattleMode", [1])                    # wild: the writer's own TRAINER_BATTLE gate holds
    _put(rig.mem, "wCurOTMon", [0])
    _put(rig.mem, "wCurPartyMon", [0])
    rig.state.rival = _team(lua)
    _fire(rig, RIVAL_GATE)
    assert _writes(rig) == [] and _events(rig) == []
    assert "not a trainer battle" in str(rig.state.rival_why or "")


def test_the_rival_gate_is_the_only_pc_a_swap_may_be_attempted_at(roms):
    _, rig = _rig(roms)
    for pc_ in (PLAYER_BRANCH, RIVAL_COMMIT, RIVAL_LAST, INIT_ENEMY, BATTLE_FAINT):
        with pytest.raises(LuaError):
            rig.battle.on_write_window("rival_swap_gate", {"bank": 0x0F, "pc": pc_})


# ── (6) inert without a writer ────────────────────────────────────────────────────────────────────

def test_without_a_writer_the_windows_are_inert(roms):
    _, rig = _rig(roms, with_writes=False)
    assert rig.battle.writes is None and rig.battle.writes_enabled is False
    assert rig.battle.on_write_window("explode_hold", {"bank": 0x0F, "pc": EXPLODE_HOLD}) is None
    assert rig.battle.on_write_window("rival_swap_gate", {"bank": 0x0F, "pc": RIVAL_GATE}) is None
