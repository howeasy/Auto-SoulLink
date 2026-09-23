"""Gen 2 client rules (P3b): lupa on the real Entry.build_candidate graph with emulator stubs.

The graph is SOURCE/MODEL (signals.new_model, an injected checkpoint); nothing here is a
PHYSICAL receipt. Every falsifier runs twice: on the shipped sources, where the rule holds,
and on a deliberately broken variant (a textual mutation of one module, swapped in through
Lua's dofile), where the same assertion must fail. A mutation whose anchor text is missing
fails loudly, so a variant cannot silently stop testing anything.
"""

import json
import sys
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server.adapters import gen2_codec  # noqa: E402
from server.adapters.gen2_gsc import Gen2GSCAdapter  # noqa: E402

EMULATOR = r"""
return function(rom, shadow_addr)
    local mem = {["System Bus"] = {}, CartRAM = {}}
    local emu = {bank = 1, shadow = 1, wram_bank = 1, frame = 1, callbacks = {}, writes = {},
                 -- BizHawk 2.11.1 Gambatte emu.getregister: singles and bank names, no pairs (PLAN A15)
                 regs = {PC = 0, SP = 0xC020, A = 0, B = 0, C = 0, D = 0, E = 0, F = 0, H = 0, L = 0,
                         ["ROM0 BANK"] = 0, ["ROMX BANK"] = 1, ["VRAM BANK"] = 0, ["SRAM BANK"] = 0,
                         ["WRAM BANK"] = 1}}
    local io = {model_only = true, cart_ram_linear = true}
    function io.read_u8(a, d)
        d = d or "System Bus"
        if d == "ROM" then return rom:byte(a + 1) or 0 end
        if d == "System Bus" and a < 0x8000 then
            local flat = a < 0x4000 and a or emu.bank * 0x4000 + a - 0x4000
            return rom:byte(flat + 1) or 0
        end
        if d == "System Bus" and a == shadow_addr then return emu.shadow end
        return mem[d][a] or 0
    end
    function io.read_range(a, n, d)
        local out = {}
        for i = 1, n do out[i] = io.read_u8(a + i - 1, d) end
        return out
    end
    function io.write_u8(a, v, d)
        emu.writes[#emu.writes + 1] = {a, v, d}
        mem[d or "System Bus"][a] = v
    end
    function io.bank_valid(bank, a, n)
        if a < 0x4000 then return bank == 0 and a + n <= 0x4000 end
        if a < 0x8000 then return bank == emu.bank and a + n <= 0x8000 end
        if a >= 0xC000 and a < 0xD000 then return bank == 0 and a + n <= 0xD000 end
        if a >= 0xD000 and a < 0xE000 then return bank == emu.wram_bank and a + n <= 0xE000 end
        return bank == 0 and a >= 0xFF80 and a + n <= 0xFFFF
    end
    function io.stack_valid(sp, n) return sp >= 0xC000 and sp + n <= 0xD000 end
    function io.domain_size(d)
        if d == "ROM" then return #rom end
        return d == "CartRAM" and 0x8000 or 0x10000
    end
    function io.register(name)
        local value = emu.regs[name]
        if value == nil then error("BizHawk 2.11.1 emu.getregister has no " .. tostring(name) .. " (singles only)") end
        return value
    end
    function io.framecount() return emu.frame end
    function io.on_bus_exec(fn, addr, name) emu.callbacks[name] = {fn = fn, addr = addr}; return name end
    function io.unregister(name) emu.callbacks[name] = nil; return true end
    function emu.poke(d, a, bytes) for i = 1, #bytes do mem[d][a + i - 1] = bytes[i] end end
    function emu.fire(bank, addr)
        emu.regs.PC, emu.bank, emu.shadow = addr, bank, bank
        local hit = 0
        for _, cb in pairs(emu.callbacks) do
            if cb.addr == addr then hit = hit + 1; cb.fn() end
        end
        return hit
    end
    local net = {sent = {}, inbox = {}, up = true}
    function net.send(line) net.sent[#net.sent + 1] = line end
    function net.receive() return table.remove(net.inbox, 1) end
    function net.pump() end
    function net.connected() return net.up end
    local hud = {shown = {}}
    local function rec(kind) return function(text) hud.shown[#hud.shown + 1] = kind .. ":" .. tostring(text) end end
    hud.show, hud.prompt, hud.nuzlocke_start = rec("show"), rec("prompt"), rec("nuzlocke")
    hud.set_rebuilding, hud.set_game_over, hud.clear_rebuilding = rec("rebuild"), rec("game_over"), rec("rebuild_done")
    hud.sanitize = function(s) return s end
    local logs = {}
    return emu, io, net, hud, logs, function(t) logs[#logs + 1] = t end
end
"""

MUTATE = r"""
return function(swaps)
    local real = dofile
    dofile = function(path)
        for suffix, source in pairs(swaps) do
            if path:sub(-#suffix) == suffix then return assert(load(source, "@" .. path))() end
        end
        return real(path)
    end
end
"""

POLICY = r"""
return function(owner)
    return {authorize = function(op, req) return owner(op, req.slot) end,
            pointer_stable = function() return true end,
            lifetime = {capture = function() return 1 end, valid = function() return true end},
            provenance = function() return {site = "test_gen2_client"} end}
end
"""


def mon(species=25, ot=0x1234, dvs=0x2AAA, nickname=0x81, hp=30, egg=False):
    return {"species": species, "ot": ot, "dvs": dvs, "nickname": nickname, "hp": hp, "egg": egg}


def collection(mons, capacity, stride):
    record_start = capacity + 2
    ot_start = record_start + capacity * stride
    nick_start = ot_start + capacity * 11
    raw = bytearray(nick_start + capacity * 11)
    raw[0] = len(mons)
    raw[len(mons) + 1] = 255
    for i, m in enumerate(mons):
        raw[i + 1] = 253 if m["egg"] else m["species"]
        start = record_start + i * stride
        raw[start] = m["species"]
        raw[start + 6:start + 8] = m["ot"].to_bytes(2, "big")
        raw[start + 21:start + 23] = m["dvs"].to_bytes(2, "big")
        raw[start + 31] = 20
        if stride == 48:
            raw[start + 34:start + 36] = m["hp"].to_bytes(2, "big")
            raw[start + 36:start + 38] = (50).to_bytes(2, "big")
        raw[ot_start + i * 11:ot_start + i * 11 + 2] = bytes([0x80, 0x50])
        raw[nick_start + i * 11:nick_start + i * 11 + 2] = bytes([m["nickname"], 0x50])
    return raw


def codec_key(m):
    return gen2_codec.key({"dv_word": m["dvs"], "ot_id": m["ot"], "species_id": m["species"]})


OPEN = r"""
return function(files)
    local real = io.open
    io.open = function(path, mode)
        for suffix, text in pairs(files) do
            if path:sub(-#suffix) == suffix then
                if text == false then return nil, "missing test input" end
                return {read = function() return text end, close = function() end}
            end
        end
        return real(path, mode)
    end
end
"""


CHECKPOINT = {t: json.loads((ROOT / f"data/games/gen2_{t}/write_checkpoint.json").read_text())["titles"][t]
              for t in ("crystal", "gold", "silver")}


class Refused(Exception):
    """Entry.build refused the production graph (the Lua reason is the message)."""


class World:
    def __init__(self, title="crystal", swaps=None, production=False, files=None):
        self.title = title
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        if swaps:
            self.lua.execute(MUTATE)(self.lua.table_from(swaps))
        if files:
            self.lua.execute(OPEN)(self.lua.table_from(files))
        self.production = production
        self.profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
        self.sites = json.loads((ROOT / f"data/games/gen2_{title}/engine_signals.json").read_text())["titles"][title]["sites"]
        self.points = {n: pt for s in self.sites.values() for n, pt in s["point_symbols"].items()}
        repo = "pokecrystal" if title == "crystal" else "pokegold"
        rom = (ROOT / f".cache/gen2-build/{repo}/{self.profile['artifact']}.gbc").read_bytes()
        self.emu, self.io, self.net, self.hud, self.logs, log = self.lua.execute(EMULATOR)(
            rom, self.profile["ram"]["hROMBank"])
        self.checkpoint_ok = False
        self.owned = lambda op, slot: True
        self.covered = {"party_hp", "box_deposit", "party_collection", "box_withdraw", "backing_box"}
        checkpoint = self.lua.eval("function(f, c) return {check=function() return f() end, "
                                   "covers=function(_, kind) return c(kind) end} end")(
            lambda: (self.checkpoint_ok, "stub checkpoint"), lambda kind: kind in self.covered)
        entry = self.lua.eval("dofile")((ROOT / "lua/gen2/entry.lua").as_posix())
        if production:
            # Live-shaped IO: not model_only, with the domain list the checkpoint evaluator needs.
            self.io.model_only = False
            self.io.domains = self.lua.eval('function() return {"ROM", "System Bus", "CartRAM"} end')
            args = self.lua.table(root=ROOT.as_posix(), title=title, io=self.io, net=self.net, hud=self.hud,
                                  player="a", log=log, rom_size=len(rom),
                                  read_rom_u8=self.lua.eval("function(io) return function(a) return io.read_u8(a, 'ROM') end end")(self.io))
            result = entry.build(args)
        else:
            args = self.lua.table(root=ROOT.as_posix(), title=title, io=self.io, candidate_only=True,
                                  write_policy=self.lua.execute(POLICY)(lambda op, slot: self.owned(op, slot)),
                                  net=self.net, hud=self.hud, player="a", checkpoint=checkpoint, log=log)
            result = entry.build_candidate(args)
        parts = result[0] if isinstance(result, tuple) else result
        if production and parts is None:
            raise Refused(result[1])
        assert parts is not None, result
        self.parts, self.client = parts, parts.client
        # A saved game standing in the overworld: one party mon, one ball, box 1 empty.
        self.field("wPlayerID", 0x1234, 2)
        self.party([mon()])
        self.box([])
        for row in self.profile["storage_boxes"]:   # EraseBoxes: every backing box empty and terminated
            self.emu.poke("CartRAM", row["flat"], self.lua.table_from([0, 255]))
        self.ram("wNumBalls", [1, 1, 5, 255])
        self.field("wMapGroup", 24)
        self.field("wMapNumber", 3)
        for name in ("wBattleMode", "wBattleType", "wBattleScriptFlags", "wCurBox", "wCurPartyMon",
                     "wCurBattleMon", "wLinkMode"):
            self.field(name, 0)
        self.client.start(self.client)

    # ── memory ──
    def ram(self, name, data):
        self.emu.poke("System Bus", self.profile["ram"][name], self.lua.table_from(list(data)))

    def field(self, name, value, width=1):
        address = self.points[name]["addr"] if name in self.points else self.profile["ram"][name]
        data = value.to_bytes(width, "big") if width == 2 and name == "wPlayerID" else \
            bytes((value >> (8 * i)) & 255 for i in range(width))
        self.emu.poke("System Bus", address, self.lua.table_from(list(data)))

    def party(self, mons):
        self.ram("wPartyCount", collection(mons, 6, 48))

    def box(self, mons):
        self.emu.poke("CartRAM", self.profile["derived"]["active_box_flat"],
                      self.lua.table_from(list(collection(mons, 20, 32))))

    def hp_of(self, slot):
        base = self.profile["ram"]["wPartyMon1"] + slot * 48
        return self.io.read_u8(base + 34) * 256 + self.io.read_u8(base + 35), self.io.read_u8(base + 32)

    # ── engine ──
    def fire(self, site_id):
        site = self.sites[site_id]
        assert self.emu.fire(site["bank"], site["addr"]) > 0, site_id

    def frames(self, n=1):
        for _ in range(n):
            self.emu.frame += 1
            self.client.frame_end(self.client)

    def reply(self, *commands):
        self.net.inbox[len(self.net.inbox) + 1] = json.dumps({"commands": list(commands)})

    # ── observations ──
    def sent(self, event=None):
        lines = [json.loads(line) for line in self.net.sent.values()]
        return [m for m in lines if event is None or m["event"] == event]

    def shown(self):
        return list(self.hud.shown.values())

    def written(self):
        return [tuple(w.values()) for w in self.emu.writes.values()]

    def hold(self, **broken):
        """Production: the CPU reaches the pack checkpoint PC in a held idle frame (every pack
        predicate, caller word and bank shadow as the U2 PHYSICAL gate accepted them); `broken`
        overrides predicate values. The PC leaves the checkpoint again before frame end."""
        primary = CHECKPOINT[self.title]["primary"]
        for condition in primary["state_predicates"]:
            value = broken.get(condition["symbol"], condition["value"])
            self.emu.poke("System Bus", condition["address"], self.lua.table_from([value]))
        sp = primary["caller_stack"]["minimum_sp"] + 16
        for word in primary["caller_stack"]["required_words"]:
            self.emu.poke("System Bus", sp + word["offset_from_sp"],
                          self.lua.table_from([word["value"] & 255, word["value"] >> 8]))
        self.emu.regs.SP = sp
        hit = self.emu.fire(primary["execution_before"]["bank"], primary["execution_before"]["pc"])
        self.emu.regs.PC = 0
        return hit

    def hello(self):
        if self.production:
            self.hold()
            self.frames(1)
        self.checkpoint_ok = True
        self.frames(2)
        hellos = self.sent("hello")
        assert len(hellos) == 1, self.logs.values()
        return hellos[0]


def mutant(path, *pairs):
    source = (ROOT / path).read_text(encoding="utf-8")
    for old, new in pairs:
        assert source.count(old) == 1, f"mutation anchor drifted in {path}: {old!r}"
        source = source.replace(old, new)
    return {path: source}


def falsify(check, swaps):
    """The rule holds on the shipped sources and fails on the broken variant."""
    check(World())
    with pytest.raises(AssertionError):
        check(World(swaps=swaps))


# ── falsifiers ──────────────────────────────────────────────────────────────────────────
def test_no_hello_before_the_checkpoint():
    def check(world):
        world.frames(120)
        assert world.sent("hello") == []
        world.hello()

    falsify(check, mutant("lua/gen2/client.lua", ("if battle.mode == 0 and not (self.checkpoint_held or safety.check(PARTY_HP)) then",
                                                  "if false then")))


def test_no_write_outside_the_armed_gate():
    def check(world):
        world.party([mon(), mon(species=172, dvs=0x3AAA)])
        world.hello()
        world.checkpoint_ok = False
        world.reply({"cmd": "force_faint", "key": codec_key(mon(species=172, dvs=0x3AAA))})
        world.frames(130)
        assert world.written() == []
        assert not any("KO'd" in text for text in world.shown())

    falsify(check, mutant("lua/gen2/client.lua", ("local safe = safety.check(PARTY_HP)", "local safe = true")))


def test_the_permit_itself_refuses_an_unarmed_write():
    world = World()
    ok, err = world.lua.eval("function(w) return pcall(function() return w:faint_party_slot(0, {mode=0, link_mode=0}) end) end")(
        world.parts.writes)
    assert ok is False and "no armed write window" in err and world.written() == []


def test_an_unhatched_egg_never_reaches_the_wire():
    def check(world):
        first, second = mon(), mon(species=172, dvs=0x3AAA)
        world.party([first, mon(species=175, dvs=0x4AAA, egg=True), second])
        world.box([mon(species=176, dvs=0x5AAA, egg=True), mon(species=133, dvs=0x6AAA)])
        hello = world.hello()
        assert [(e["slot"], e["key"]) for e in hello["party"]] == [(0, codec_key(first)), (2, codec_key(second))]
        assert [(e["box"], e["slot"], e["species_id"]) for e in hello["pc_boxes"]] == [(0, 1, 133)]
        world.frames(30)
        tick = world.sent("tick")[-1]
        assert [e["slot"] for e in tick["party"]] == [0, 2]

    # With only the client filter gone the wire refusal fails the hello closed; with both
    # gone the egg is on the wire. Either way the rule's assertion is what goes red.
    client_only = mutant("lua/gen2/client.lua", ("            if not m.is_egg then\n                local e, why = wire.party_entry",
                                                 "            if true then\n                local e, why = wire.party_entry"))
    falsify(check, client_only)
    falsify(check, {**client_only, **mutant("lua/gen2/wire.lua", ("    if mon.is_egg then return", "    if false then return"))})


def test_no_capture_without_its_acquisition_latch():
    def check(world):
        world.hello()
        world.field("wBattleMode", 1)
        world.party([mon(), mon(species=19, dvs=0x7AAA)])
        world.fire("capture_party_finalized")  # the final-name site alone: no insertion latch
        world.frames(1)
        assert world.sent("capture") == []

    # broken binder: the party final is accepted with no insertion latch behind it
    falsify(check, mutant("lua/gen2/signals.lua",
                          ('if not found then return false,"required prior success/identity unavailable" end',
                           'if not found then return name == "capture_party_finalized" end'),
                          ('local before = assert(latches[rule.prior],"prior acquisition lost")',
                           "local before = latches[rule.prior] or receiver(STARTS[rule.prior],site)")))


def test_no_faint_without_its_signal_latch():
    def check(world):
        world.hello()
        world.field("wBattleMode", 1)
        world.party([mon(hp=0)])  # HP 0 alone, no UpdateFaintedPlayerMon
        world.frames(40)
        assert world.sent("faint") == []

    falsify(check, mutant("lua/gen2/client.lua", (
        "if #self.faint_latches == 0 then return end",
        "if #self.faint_latches == 0 then self.faint_latches = {{key = mon_key(current_party().mons[1]), frame = self.frame}} end")))


def test_lua_key_agrees_with_the_python_codec_on_the_same_record():
    def check(world):
        starter, caught = mon(species=155, ot=0x0BCD, dvs=0xFEDC), mon(species=19, ot=0x0BCD, dvs=0x1357)
        world.party([starter])
        hello = world.hello()
        assert hello["party"][0]["key"] == codec_key(starter)
        world.field("wBattleMode", 1)
        world.party([starter, caught])
        world.fire("capture_party")
        world.fire("capture_party_finalized")
        world.frames(1)
        assert [c["key"] for c in world.sent("capture")] == [codec_key(caught)]

    falsify(check, mutant("lua/gen2/wire.lua", ('string.format("%04X:%04X:%02X", mon.dv_word, mon.ot_id, mon.species_id)',
                                                'string.format("%04X:%04X:%02X", mon.ot_id, mon.dv_word, mon.species_id)')))


def test_an_active_slot_forced_faint_is_never_reported_as_success():
    def check(world):
        active, bench = mon(), mon(species=172, dvs=0x3AAA)
        world.party([active, bench])
        world.hello()
        world.field("wBattleMode", 1)  # the stub checkpoint ignores the battle: writes.lua must not
        world.reply({"cmd": "force_faint", "key": codec_key(active), "nickname": "PIKA"})
        world.frames(130)
        assert world.hp_of(0) == (30, 0) and world.written() == []
        assert not any("KO'd" in text for text in world.shown())
        assert any(text.startswith("show:KO held") for text in world.shown())
        assert any("active faint" in line for line in world.logs.values())

    falsify(check, mutant("lua/gen2/client.lua", ("        if ok then\n            hud.show(\"!! \"",
                                                  "        if true then\n            hud.show(\"!! \"")))


def test_a_reset_leaves_no_stale_latch():
    def check(world):
        world.hello()
        world.field("wBattleMode", 1)
        world.fire("battle_faint")  # copy-back not landed: the latch waits for HP 0
        world.party([mon(), mon(species=19, dvs=0x7AAA)])
        world.fire("capture_party")  # insertion latch, never finalized
        world.frames(1)
        world.fire("soft_reset")
        world.frames(1)
        world.field("wBattleMode", 0)
        world.party([mon(hp=0), mon(species=19, dvs=0x7AAA)])  # the reloaded save
        world.fire("capture_party_finalized")
        world.frames(40)
        assert world.sent("faint") == [] and world.sent("capture") == []

    falsify(check, mutant("lua/gen2/client.lua", (
        "self.faint_latches, self.battle, self.pending_rescan = {}, nil, false",
        "self.battle, self.pending_rescan = nil, false")))


# ── positive controls ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_one_hello_with_the_protocol_party_shape(title):
    world = World(title)
    hello = world.hello()
    world.frames(90)
    assert len(world.sent("hello")) == 1
    assert hello["rom_type"] == title.capitalize() and hello["foundation"] == "gen2_gsc"
    assert hello["ot_id"] == 0x1234 and hello["has_pokeballs"] is True and hello["ball_count"] == 5
    (entry,) = hello["party"]
    assert set(entry) >= {"key", "slot", "species_id", "level", "hp", "maxHP", "status_cond", "moves",
                          "pp", "pp_ups", "held_item_id", "active", "blob_hex"}
    assert (entry["slot"], entry["key"], entry["level"], entry["hp"], entry["maxHP"]) == (0, codec_key(mon()), 20, 30, 50)
    adapter = Gen2GSCAdapter(title)
    assert adapter.validate_party_blob(entry["blob_hex"], key=entry["key"], species_marker=entry["species_id"])
    assert "rom_content" not in hello and hello["panel"] is False and hello["sfx"] is False


def test_a_capture_carries_key_area_and_in_box():
    world = World()
    world.hello()
    world.field("wBattleMode", 1)
    caught = mon(species=19, dvs=0x7AAA)
    world.fire("wild_ready")
    world.party([mon(), caught])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    world.frames(1)
    boxed = mon(species=161, dvs=0x8AAA)
    world.box([boxed])
    world.fire("capture_box")
    world.fire("capture_box_finalized")
    world.fire("battle_end")  # same frame: the boundary must not discard the finalized capture
    world.frames(1)
    captures = world.sent("capture")
    assert [(c["key"], c["area_id"], c["in_box"], c["gift"]) for c in captures] == [
        (codec_key(caught), "route_29", False, False), (codec_key(boxed), "route_29", True, False)]
    assert world.sent("no_catch") == []


def test_a_bench_faint_is_written_through_the_permit():
    world = World()
    active, bench = mon(), mon(species=172, dvs=0x3AAA)
    world.party([active, bench])
    world.hello()
    world.frames(60)  # a live validation enables writes
    world.reply({"cmd": "force_faint", "key": codec_key(bench), "nickname": "PICHU"})
    world.frames(2)
    assert world.hp_of(1) == (0, 0) and world.hp_of(0) == (30, 0)
    receipts = [dict(r.items()) for r in world.parts.writes.log.values()]
    assert [(r["why"], r["status"], r["n"]) for r in receipts] == [("overworld", "written", 1), ("overworld", "written", 2)]
    assert "show:!! PICHU KO'd" in world.shown()


def test_a_hatched_egg_is_published_as_a_gift_daycare_capture():
    world = World()
    egg = mon(species=175, dvs=0x4AAA, egg=True)
    world.party([mon(), egg])
    assert [e["slot"] for e in world.hello()["party"]] == [0]
    world.field("wCurPartyMon", 1)
    world.party([mon(), dict(egg, egg=False)])  # the hatch publishes the species marker
    world.fire("hatch_species")
    hatched = dict(egg, egg=False, ot=0x1234, nickname=0x83)
    world.party([mon(), hatched])
    world.fire("hatch_finalized")
    world.frames(1)
    (capture,) = world.sent("capture")
    assert (capture["key"], capture["area_id"], capture["gift"], capture["in_box"]) == (
        codec_key(hatched), "gift_daycare", True, False)


@pytest.mark.parametrize("kind", ["roamer", "contest"])
def test_roamer_and_contest_link_under_the_adapter_namespaces(kind):
    world = World()
    world.hello()
    adapter = Gen2GSCAdapter("crystal")
    world.field("wBattleMode", 1)
    if kind == "roamer":
        raikou = mon(species=243, dvs=0x9AAA)
        world.field("wBattleType", 5)
        world.field("wCurPartySpecies", 243)
        world.party([mon(), raikou])
        world.fire("capture_party")
        world.fire("capture_party_finalized")
        expected = adapter.gift_link_area("legend_243", acquisition="roamer", species_id=243)
    else:
        world.box([mon(species=123, dvs=0x9AAA)])
        world.fire("contest_box_inserted")
        world.box([mon(species=123, dvs=0x9AAA, nickname=0x84)])
        world.fire("contest_box_finalized")
        expected = adapter.gift_link_area("national_park_contest", acquisition="contest", species_id=123)
    world.frames(1)
    (capture,) = world.sent("capture")
    assert capture["area_id"] == expected == {"roamer": "legend_243", "contest": "national_park_contest"}[kind]


@pytest.mark.parametrize("boundary", ["battle_end", "soft_reset"])
def test_a_capture_finalized_in_the_boundary_frame_is_published(boundary):
    world = World()
    world.hello()
    world.field("wBattleMode", 1)
    caught = mon(species=19, dvs=0x7AAA)
    world.fire("wild_ready")
    world.party([mon(), caught])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    world.fire(boundary)  # nothing drained between the capture and the boundary
    world.frames(1)
    assert [c["key"] for c in world.sent("capture")] == [codec_key(caught)]
    assert world.sent("no_catch") == []


def test_a_refused_catch_is_logged_once_and_later_signals_still_flow():
    world = World()
    world.hello()
    world.field("wBattleMode", 1)
    world.field("wBattleScriptFlags", 128)  # a scripted/static battle
    world.party([mon(), mon(species=243, dvs=0x7AAA)])
    for _ in range(2):
        world.fire("capture_party")
        world.fire("capture_party_finalized")
        world.frames(1)
    assert world.sent("capture") == []
    assert len([line for line in world.logs.values() if "scripted/static" in line]) == 1
    world.field("wBattleScriptFlags", 0)
    caught = mon(species=19, dvs=0x8AAA)
    world.party([mon(), mon(species=243, dvs=0x7AAA), caught])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    world.frames(1)
    assert [c["key"] for c in world.sent("capture")] == [codec_key(caught)]
    assert not any("STOPPED" in text for text in world.shown())


def test_a_faint_follows_the_fainting_record_not_its_slot():
    world = World()
    lead, pichu = mon(), mon(species=172, dvs=0x3AAA)
    world.party([lead, pichu])
    world.hello()
    world.field("wBattleMode", 1)
    world.field("wCurBattleMon", 1)
    world.fire("battle_faint")  # copy-back not landed yet
    world.frames(1)
    assert world.sent("faint") == []
    world.party([dict(pichu, hp=0), lead])  # the record moved before its HP 0 landed
    world.frames(1)
    assert [f["key"] for f in world.sent("faint")] == [codec_key(pichu)]


def test_each_poison_faint_carries_its_own_record():
    world = World()
    first, second, survivor = mon(hp=0), mon(species=172, dvs=0x3AAA, hp=0), mon(species=19, dvs=0x7AAA)
    world.party([first, second, survivor])
    world.hello()
    for slot in (0, 1):  # one DoPoisonStep pass, one site hit per fainting mon
        world.field("wCurPartyMon", slot)
        world.fire("poison_faint")
    world.frames(1)
    assert sorted(f["key"] for f in world.sent("faint")) == sorted([codec_key(first), codec_key(second)])


def test_an_evolution_publishes_key_change_and_a_cancelled_one_nothing():
    world = World()
    pikachu, bulbasaur = mon(), mon(species=1, dvs=0x3AAA)
    world.party([pikachu, bulbasaur])
    world.hello()
    # Slot 0 was B-cancelled: CancelEvolution returns to the master loop before the
    # species-list store, so no site fires and the record is unchanged.
    world.frames(5)
    assert world.sent("key_change") == []
    ivysaur = dict(bulbasaur, species=2)
    world.party([pikachu, ivysaur])
    world.field("wCurPartyMon", 1)
    species_list = world.profile["ram"]["wPartySpecies"] + 1
    world.emu.regs["A"], world.emu.regs["H"], world.emu.regs["L"] = 2, species_list >> 8, species_list & 255
    world.fire("evolution_species_published")
    world.frames(1)
    (change,) = world.sent("key_change")
    assert (change["old_key"], change["new_key"], change["reason"], change["new_species"]) == (
        codec_key(bulbasaur), codec_key(ivysaur), "evolution", 2)


# ── N3 review findings ──────────────────────────────────────────────────────────────────
def evolve_slot_one(world):
    """Bulbasaur in slot 1 evolves; A and H/L are set as BizHawk exposes them (singles)."""
    bulbasaur = mon(species=1, dvs=0x3AAA)
    world.party([mon(), bulbasaur])
    world.hello()
    world.party([mon(), dict(bulbasaur, species=2)])
    world.field("wCurPartyMon", 1)
    species_list = world.profile["ram"]["wPartySpecies"] + 1
    world.emu.regs["A"], world.emu.regs["H"], world.emu.regs["L"] = 2, species_list >> 8, species_list & 255
    world.fire("evolution_species_published")
    world.frames(1)


def test_the_evolution_hl_guard_reads_bizhawk_single_registers():
    def check(world):
        evolve_slot_one(world)
        assert [c["new_species"] for c in world.sent("key_change")] == [2]
        assert not any("STOPPED" in text for text in world.shown())

    # the pre-N3 binder asked the emulator for the pair "HL", which BizHawk does not have
    falsify(check, mutant("lua/gen2/signals.lua", (
        "if pair then return register(pair[1])*256+register(pair[2]) end", "")))


def test_a_failed_deposit_does_not_swallow_the_next_one():
    def check(world):
        lead, pichu = mon(), mon(species=172, dvs=0x3AAA)
        world.party([lead, pichu])
        world.hello()
        world.field("wCurPartyMon", 1)
        world.fire("pc_deposit_begin")  # .BoxFull: the completion site is skipped
        world.frames(1)
        world.fire("pc_deposit_begin")  # box changed, same mon deposited again
        world.party([lead])
        world.box([pichu])
        world.fire("pc_deposit_complete")
        world.frames(1)
        assert [m["key"] for m in world.sent("party_to_box")] == [codec_key(pichu)]

    falsify(check, mutant("lua/gen2/signals.lua", ("if latches[name] and SUPERSEDES[name] then", "if false then")))


def wild_battle(world):
    world.hello()
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.frames(1)
    world.field("wBattleMode", 1)
    world.fire("wild_ready")


def end_battle(world):
    world.fire("battle_end")
    world.field("wBattleMode", 0)
    world.frames(1)


def test_a_refused_capture_never_becomes_a_no_catch():
    def check(world):
        wild_battle(world)
        world.party([mon(), mon()])  # caught record identical to the lead: the binder refuses
        world.fire("capture_party")
        world.fire("capture_party_finalized")
        world.frames(1)
        end_battle(world)
        assert world.sent("capture") == [] and world.sent("no_catch") == []
        assert any("no_catch withheld, route_29 stays open" in line for line in world.logs.values())
        assert "show:CATCH NOT REPORTED - SEE LOG" in world.shown()

    falsify(check, mutant("lua/gen2/client.lua", (
        "if b.capture_refused or ev.refused_acquisitions ~= b.refused_base then", "if false then")))


def test_the_new_encounter_banner_puts_the_area_on_its_own_line():
    world = World()
    wild_battle(world)
    world.frames(1)
    banners = [s for s in world.shown() if "NEW ENCOUNTER" in s]
    assert len(banners) == 1 and banners[0].startswith("show:** NEW ENCOUNTER **\n")
    assert banners[0] != "show:** NEW ENCOUNTER **\n"


def test_a_missed_throw_still_ends_as_no_catch():
    world = World()
    wild_battle(world)
    world.fire("capture_party_finalized")  # the ball missed: same RET, no insertion
    world.frames(1)
    end_battle(world)
    assert [n["area_id"] for n in world.sent("no_catch")] == ["route_29"]


def test_no_event_reaches_the_server_before_the_hello():
    def check(world):
        world.party([mon(hp=0), mon(species=172, dvs=0x3AAA)])
        world.frames(120)
        world.field("wCurPartyMon", 0)
        world.fire("poison_faint")
        world.frames(1)
        assert world.sent() == []
        world.hello()
        assert [m["event"] for m in world.sent()][:2] == ["hello", "faint"]
        assert world.sent("faint")[0]["key"] == codec_key(mon(hp=0))

    falsify(check, mutant("lua/gen2/client.lua", (
        'if event ~= "hello" and not (self.hello_session and self.hello_session:status().ready) then',
        "if false then")))


def test_held_messages_do_not_follow_an_identity_change():
    """R3-4 A: a faint held for save A (OT 0x1234) never reaches save B's (OT 0x5678) session."""
    def check(world):
        world.party([mon(hp=0), mon(species=172, dvs=0x3AAA)])
        world.field("wCurPartyMon", 0)
        world.fire("poison_faint")
        world.frames(1)
        assert world.sent() == []
        world.field("wPlayerID", 0x5678, 2)  # another save, no frame-counter jump
        world.party([mon(ot=0x5678), mon(species=172, dvs=0x3AAA, ot=0x5678)])
        hello = world.hello()
        assert hello["ot_id"] == 0x5678 and [m["event"] for m in world.sent()] == ["hello"]

    falsify(check, mutant("lua/gen2/client.lua", ('drop_held("identity change")', "")))


@pytest.mark.parametrize("jump", [-60, 600])
def test_held_messages_do_not_replay_after_a_savestate_load(jump):
    """R3-4 B: a savestate load (the frame counter steps other than +1, back or forward) drops them."""
    def check(world):
        world.frames(100)  # the counter must stay nonnegative after the rewind
        world.party([mon(hp=0), mon(species=172, dvs=0x3AAA)])
        world.field("wCurPartyMon", 0)
        world.fire("poison_faint")
        world.frames(1)
        world.emu.frame += jump
        world.party([mon(), mon(species=172, dvs=0x3AAA)])  # the loaded state has no faint
        world.hello()
        assert [m["event"] for m in world.sent()] == ["hello"]

    falsify(check, mutant("lua/gen2/client.lua", ('self:abandon_timeline("savestate load")', "")))


def test_a_full_pre_hello_queue_is_shown_on_the_hud_once():
    """R3-7: the 65th held message is lost; the player sees it, once per filled queue."""
    def check(world):
        for n in range(66):
            world.client.send("faint", world.lua.table(key=f"k{n}"))
        assert world.sent() == []
        assert sum("SLINK EVENTS LOST" in text for text in world.shown()) == 1

    falsify(check, mutant("lua/gen2/client.lua", ('hud.show("SLINK EVENTS LOST - SEE LOG", 255, 64, 64, 600)', "")))


def test_a_reset_drops_messages_held_before_the_hello():
    world = World()
    world.party([mon(hp=0), mon(species=172, dvs=0x3AAA)])
    world.fire("poison_faint")
    world.frames(1)
    world.fire("soft_reset")
    world.frames(1)
    world.party([mon(), mon(species=172, dvs=0x3AAA)])  # the reloaded save
    world.hello()
    assert [m["event"] for m in world.sent()] == ["hello"]


# ── R4 S2: a savestate load/rewind abandons the timeline; a natural boundary does not ────────────
def _pump_fails_once(world):
    calls = {"n": 0}

    def pump():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("socket pump failed")
    world.net.pump = pump


@pytest.mark.parametrize("jump", [-60, 600])
def test_a_capture_queued_before_a_rewind_is_never_published(jump):
    """A pump error leaves a finalized capture queued in the binder; the player then loads a state."""
    def check(world):
        world.hello()
        world.frames(100)
        world.field("wBattleMode", 1)
        world.fire("wild_ready")
        world.party([mon(), mon(species=19, dvs=0x7AAA)])
        world.fire("capture_party")
        world.fire("capture_party_finalized")
        _pump_fails_once(world)
        with pytest.raises(Exception, match="socket pump failed"):
            world.frames(1)
        world.emu.frame += jump
        world.field("wBattleMode", 0)
        world.party([mon()])  # the loaded state never caught anything
        world.frames(3)
        assert world.sent("capture") == [] and world.sent("no_catch") == []

    falsify(check, mutant("lua/gen2/signals.lua", ("        count = count+#service:drain()\n",
                                                   "        for _,b in ipairs(service:drain()) do carried[#carried+1] = b end\n")))


def test_pending_faint_and_acquisition_latches_do_not_survive_a_rewind():
    def check(world):
        world.hello()
        world.frames(100)
        world.field("wBattleMode", 1)
        world.fire("battle_faint")  # copy-back not landed: the faint latch waits for HP 0
        world.party([mon(), mon(species=19, dvs=0x7AAA)])
        world.fire("capture_party")  # insertion latch, never finalized on this timeline
        world.frames(1)
        world.emu.frame -= 60
        world.frames(1)
        world.party([mon(hp=0), mon(species=19, dvs=0x7AAA)])  # the resumed timeline
        world.fire("capture_party_finalized")
        world.frames(40)
        assert world.sent("faint") == [] and world.sent("capture") == []

    falsify(check, mutant("lua/gen2/client.lua", (
        "        if self.signals then self.signals:abandon(why) end\n"
        "        self.faint_latches, self.deferred = {}, {}\n"
        "        self.battle, self.pending_safe, self.pending_rescan = nil, false, true\n", "")))


def test_rewind_cancels_a_deferred_faint_from_the_abandoned_timeline():
    world = World()
    lead, bench = mon(), mon(species=172, dvs=0x3AAA)
    world.party([lead, bench])
    world.hello()
    world.frames(60)  # a live validation arms the model writer
    world.checkpoint_ok = False
    world.reply({"cmd": "force_faint", "key": codec_key(bench), "nickname": "PICHU"})
    world.frames(1)
    assert world.hp_of(1) == (30, 0) and world.written() == []

    world.emu.frame -= 60  # load an earlier frame with the same party key
    world.checkpoint_ok = True
    world.frames(1)
    assert world.hp_of(1) == (30, 0) and world.written() == []


def test_a_write_refused_after_the_gate_is_logged_and_consumed():
    """When the checkpoint gate (safety.check) passes but the write itself refuses,
    the refusal is logged once, no bytes are written, and the deferred command is
    consumed (not re-queued). This pins current behavior—benign in production because
    the gate and the write re-check run in the same frame (OMP review O13)."""
    world = World()
    lead, bench = mon(), mon(species=172, dvs=0x3AAA)
    world.party([lead, bench])
    world.hello()
    world.frames(60)  # a live validation arms the model writer
    world.checkpoint_ok = True  # gate passes
    world.owned = lambda op, slot: False  # but the write refuses
    world.reply({"cmd": "force_faint", "key": codec_key(bench), "nickname": "PICHU"})
    world.frames(1)  # run_deferred is called; the gate passes but arm() refuses
    # The command is consumed, even though the write was refused.
    assert len(world.client.deferred) == 0
    assert world.written() == []
    # The refusal is logged.
    assert any("refused by the write gate" in line for line in world.logs.values())
    # The HUD shows the refusal message.
    assert any("KO refused" in text for text in world.shown())


def test_rewind_cancels_a_safe_reply_from_the_abandoned_battle():
    world = World()
    world.hello()
    world.frames(100)
    world.field("wBattleMode", 1)
    world.fire("battle_end")
    world.frames(1)  # battle_end queued a safe reply, but the old battle still reads as active
    assert world.sent("safe") == []

    world.emu.frame -= 60
    world.field("wBattleMode", 0)  # the loaded state is back in the overworld
    world.frames(1)
    assert world.sent("safe") == []


def test_rewind_discards_old_key_alias_before_a_delayed_faint_command():
    def check(world):
        old = mon(species=1, dvs=0x3AAA)
        new = dict(old, species=2)
        evolve_slot_one(world)
        world.frames(60)
        world.reply({"cmd": "key_change_rejected", "old_key": codec_key(old),
                     "new_key": codec_key(new), "reason": "collision"})
        world.frames(1)
        world.emu.frame -= 60
        world.frames(1)  # the loaded state retains the evolved mon but not the old key's alias
        world.reply({"cmd": "force_faint", "key": codec_key(old)})
        world.frames(1)
        assert world.hp_of(1) == (30, 0) and world.written() == []

    falsify(check, mutant("lua/gen2/client.lua", (
        "        -- A delayed retirement may be lost after rewinding a key change; retaining its alias could faint another record.\n"
        "        self.key_alias, self.retired_alias = nil, {}\n",
        "        -- A delayed retirement may be lost after rewinding a key change; retaining its alias could faint another record.\n")))


def test_rewind_refreshes_box_snapshot_before_the_next_tick():
    def check(world):
        old, new = mon(species=133, dvs=0x4AAA), mon(species=172, dvs=0x5AAA)
        world.box([old])
        assert [e["key"] for e in world.hello()["pc_boxes"]] == [codec_key(old)]
        world.frames(100)
        world.emu.frame -= 60
        world.box([new])  # the restored cartridge has a different active-box record
        world.frames(31)
        assert [e["key"] for e in world.sent("tick")[-1]["pc_boxes"]] == [codec_key(new)]

    falsify(check, mutant("lua/gen2/client.lua", (
        "        self.battle, self.pending_safe, self.pending_rescan = nil, false, true\n",
        "        self.battle, self.pending_safe, self.pending_rescan = nil, false, false\n")))


# ── N12b: a scripted static finalizes at the wild capture sites; the static pack names it ─────
def static_battle(world, group, number, battle_type, flags=128):
    world.hello()
    world.field("wBattleMode", 1)
    world.field("wMapGroup", group)
    world.field("wMapNumber", number)
    world.field("wBattleType", battle_type)
    world.field("wBattleScriptFlags", flags)  # Script_loadwildmon writes bit 7


def static_party_catch(world, group, number, species, battle_type, flags=128):
    static_battle(world, group, number, battle_type, flags)
    world.party([mon(), mon(species=species, dvs=0x7AAA)])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    world.frames(1)
    return [(c["key"], c["area_id"], c["gift"]) for c in world.sent("capture")]


@pytest.mark.parametrize("title,group,number,species,battle_type,flags,area", [
    ("crystal", 3, 4, 245, 12, 128, "legend_245"),  # Tin Tower Suicune, SUICUNE (O-21)
    ("crystal", 9, 6, 130, 7, 128, "static_lake_of_rage_130"),  # red Gyarados, FORCESHINY
    ("crystal", 10, 3, 185, 0, 128, "static_route_36_185"),  # Sudowoodo, NORMAL
    ("crystal", 3, 49, 100, 9, 128, "static_team_rocket_base_b1f_100"),  # Rocket B1F Voltorb trap, TRAP
    ("crystal", 12, 3, 143, 10, 128, "static_vermilion_city_143"),  # Snorlax, FORCEITEM
    ("crystal", 3, 52, 251, 11, 128, "static_ilex_forest_251"),  # Celebi, CelebiEvent_SetBattleType
    ("crystal", 3, 39, 131, 0, 128, "static_union_cave_b2f_131"),  # Lapras, NORMAL
    ("gold", 15, 12, 250, 10, 128, "static_tin_tower_roof_250"),  # Gold's Ho-Oh beside its unselected Silver twin
    ("crystal", 24, 3, 19, 0, 0, "route_29"),  # control: a natural wild Rattata is unchanged
])
def test_a_scripted_static_capture_is_published_under_its_pack_area(title, group, number, species,
                                                                    battle_type, flags, area):
    world = World(title)
    assert static_party_catch(world, group, number, species, battle_type, flags) == [
        (codec_key(mon(species=species, dvs=0x7AAA)), area, False)]
    # Gen 1 canon (O-3), pack-owned since gen2-static-canon: a static is its own gift area
    # (static_<lowercase map constant>_<species>, or its O-21 legend namespace), never the
    # route's ordinary area -- and keyed by the map CONSTANT, so the same static in Crystal,
    # Gold and Silver is one area for a pair (O-16)
    adapter = Gen2GSCAdapter(title)
    assert adapter.is_gift_area(area) == bool(flags) and (not flags or adapter.gift_link_area(area) == area)


@pytest.mark.parametrize("title,group,number,species,battle_type", [
    ("crystal", 24, 3, 19, 3),  # Route 29 catching tutorial
    ("crystal", 9, 6, 245, 12),  # no static row for this map/species
    ("crystal", 9, 6, 130, 0),  # the red Gyarados row is FORCESHINY, not NORMAL
    ("gold", 3, 14, 244, 0),  # Gold's source_unused Burned Tower Entei
])
def test_an_unqualified_scripted_static_stays_refused(title, group, number, species, battle_type):
    world = World(title)
    assert static_party_catch(world, group, number, species, battle_type) == []
    assert any("scripted/static" in line for line in world.logs.values())


def test_an_unselected_version_row_alone_never_publishes():
    world = World("gold")
    for row in world.parts.data.statics.encounters.values():
        if row.script == "TinTowerHoOh":  # leave only the selected:false Silver twin
            row.applicability.selected = False
    assert static_party_catch(world, 15, 12, 250, 10) == []


@pytest.mark.parametrize("prior", [20, 19])
def test_a_box_full_static_never_claims_the_mon_already_first_in_the_box(prior):
    world = World()
    static_battle(world, 3, 50, 0)  # a B2F Electrode
    world.party([mon(dvs=0x1000 + n) for n in range(6)])  # party full: .SendToPC
    old = [mon(species=101, dvs=0x2000 + n) for n in range(prior)]
    caught = mon(species=101, dvs=0x7AAA)
    world.ram("wEnemyMonDVs", [0x7A, 0xAA])
    # SendMonIntoBox .full leaves the box untouched; otherwise the new record is first
    world.box(old if prior == 20 else [caught, *old])
    world.fire("capture_box")
    world.fire("capture_box_finalized")
    world.frames(1)
    captures = [(c["key"], c["area_id"], c["in_box"]) for c in world.sent("capture")]
    assert captures == ([] if prior == 20 else [(codec_key(caught), "static_team_rocket_base_b2f_101", True)])


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_the_adapter_accepts_every_static_area_the_binder_can_publish(title):
    """The zone rule of lua/gen2/signals.lua final_event over every publishable pack row:
    the binder publishes the row's own static_area_id (gen2-static-canon), and the adapter's
    membership set must accept exactly those -- no id is recomputed on either side."""
    adapter = Gen2GSCAdapter(title)
    rows = json.loads((ROOT / f"data/games/gen2_{title}/static_encounters.json").read_text())["encounters"]
    published = {row["static_area_id"] for row in rows
                 if row["applicability"]["selected"] and not row["source_unused"]
                 and row["kind"] != "tutorial"}
    assert published, "the pack must publish at least one static area"
    for zone in published:
        assert adapter.is_gift_area(zone) and adapter.gift_link_area(zone) == zone, (title, zone)
    # The retired group*256+number shape is refused outright, gift-shaped or not.
    assert not adapter.is_gift_area(f"static_{rows[0]['map_group'] * 256 + rows[0]['map_number']}_{rows[0]['species']}")


# ── production graph (card U3): Entry.build over the admitted Crystal and its PHYSICAL receipts ─────
RECEIPTS = ROOT / "tests/fixtures/gen2/receipts"


def production(title="crystal", swaps=None, files=None):
    return World(title, swaps=swaps, production=True, files=files)


def falsify_production(check, swaps):
    """The rule holds on the shipped production graph and fails on the broken variant."""
    check(production())
    with pytest.raises(AssertionError):
        check(production(swaps=swaps))


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_production_registers_exactly_the_u1_proven_sites_and_the_u2_kinds(title):
    world = production(title)
    parts = world.parts
    assert parts.production_admitted is True and parts.qualification == "PHYSICAL_RECEIPTED"
    assert parts.title == title and parts.data.admission.gate.state == "ADMITTED"
    proven = json.loads((RECEIPTS / f"{title}.engine_sites.json").read_text())["proven"]
    status = world.client.signals.status(world.client.signals)
    assert status.evidence_level == "PHYSICAL" and status.runtime_authorized is True
    assert sorted(status.registered_sites.values()) == sorted(proven)
    assert sorted(parts.write_scope.kinds.keys()) == ["backing_box", "box_deposit", "box_withdraw", "party_collection", "party_hp"]
    pc = CHECKPOINT[title]["primary"]["execution_before"]["pc"]
    assert world.emu.callbacks["SLink-gen2-checkpoint"].addr == pc
    assert len(world.hello()["party"]) == 1  # the title's own checkpoint hold arms the hello
    world.client.stop(world.client)
    assert world.emu.callbacks["SLink-gen2-checkpoint"] is None


def test_production_no_hello_before_an_accepted_checkpoint_hold():
    def check(world):
        world.frames(120)
        assert world.sent("hello") == []
        assert world.hold(wScriptRunning=1) == 1  # a script frame at the PC: the predicate refuses
        world.frames(2)
        assert world.sent("hello") == []
        world.hold()
        world.frames(1)
        assert len(world.sent("hello")) == 1

    falsify_production(check, mutant("lua/gen2/client.lua", (
        "if battle.mode == 0 and not (self.checkpoint_held or safety.check(PARTY_HP)) then", "if false then")))


def test_production_refuses_an_unarmed_or_unheld_write():
    def check(world):
        attempt = world.lua.eval("""function(w, arm) return pcall(function()
            if arm then w:arm('overworld') end
            return w:faint_party_slot(0, {mode=0, link_mode=0}) end) end""")
        ok, err = attempt(world.parts.writes, False)
        assert ok is False and "no armed write window" in err
        result = attempt(world.parts.writes, True)  # armed, but the CPU is not held at the checkpoint
        world.parts.writes.disarm(world.parts.writes)
        assert isinstance(result, tuple) and result[0] is False and "ownership refused" in result[1]
        assert world.written() == []

    falsify_production(check, mutant("lua/gen2/entry.lua", (
        "return kind ~= nil and checkpoint:check(kind) == true", "return true")))


def test_production_bench_faint_lands_only_inside_the_checkpoint_hold():
    world = production()
    bench = mon(species=172, dvs=0x3AAA)
    world.party([mon(), bench])
    world.hello()
    world.frames(60)  # a live validation enables writes
    world.reply({"cmd": "force_faint", "key": codec_key(bench), "nickname": "PICHU"})
    world.frames(130)
    assert world.written() == [] and world.hp_of(1) == (30, 0)
    world.hold()
    assert world.hp_of(1) == (0, 0) and world.hp_of(0) == (30, 0)
    receipts = [dict(r.items()) for r in world.parts.writes.log.values()]
    assert {r["site"] for r in receipts} == {"lua/gen2/entry.lua production"}
    assert "show:!! PICHU KO'd" in world.shown()


def test_production_box_mon_lands_only_inside_the_checkpoint_hold():
    world = production()
    lead, pichu = mon(), mon(species=172, dvs=0x3AAA)
    world.party([lead, pichu])
    world.hello()
    world.frames(60)
    world.reply({"cmd": "box_mon", "key": codec_key(pichu)})
    world.frames(130)
    assert world.written() == [] and world.sent("box_mon_failed") == []
    world.hold()
    assert world.sent("box_mon_failed") == [] and [m["key"] for m in world.sent("stats_cache")] == [codec_key(pichu)]
    flat = world.profile["derived"]["active_box_flat"]
    assert [world.io.read_u8(flat + i, "CartRAM") for i in range(3)] == [1, 172, 255]
    assert world.io.read_u8(world.profile["ram"]["wPartyCount"]) == 1
    receipts = {r["site"] for r in world.parts.writes.log.values()}
    assert receipts == {"lua/gen2/entry.lua production"}


def test_production_refuses_what_the_receipts_do_not_cover():
    """A receipt without its box runs (the pre-BOX schema) proves only party_hp + box_deposit: every box
    command NACKs at the hold with the missing kind, and no byte moves."""
    receipt = json.loads((ROOT / "data/games/gen2_crystal/receipts/crystal.write_window.json").read_text())
    for mode in ("boxes", "boxes_reset", "boxes_reload"):
        del receipt["runs"][mode]
    world = production(files={"/receipts/crystal.write_window.json": json.dumps(receipt)})
    active = mon()
    world.party([active, mon(species=172, dvs=0x3AAA)])
    world.hello()
    world.frames(60)
    world.reply({"cmd": "box_mon", "key": codec_key(active)})
    world.field("wBattleMode", 1)
    world.reply({"cmd": "force_faint", "key": codec_key(active), "nickname": "PIKA"})
    world.frames(2)
    assert world.sent("box_mon_failed") == []            # box commands wait for the checkpoint hold
    world.field("wBattleMode", 0)
    world.hold()
    (nack,) = world.sent("box_mon_failed")
    assert "unproven write kind party_collection" in nack["reason"]
    assert any(text.startswith("show:KO held") for text in world.shown()) and world.written() == []


def test_production_key_agrees_with_the_python_codec_on_the_same_record():
    def check(world):
        starter, caught = mon(species=155, ot=0x0BCD, dvs=0xFEDC), mon(species=19, ot=0x0BCD, dvs=0x1357)
        world.party([starter])
        assert world.hello()["party"][0]["key"] == codec_key(starter)
        world.field("wBattleMode", 1)
        world.fire("wild_ready")
        world.party([starter, caught])
        world.fire("capture_party")
        world.fire("capture_party_finalized")
        world.frames(1)
        assert [c["key"] for c in world.sent("capture")] == [codec_key(caught)]

    falsify_production(check, mutant("lua/gen2/wire.lua", (
        'string.format("%04X:%04X:%02X", mon.dv_word, mon.ot_id, mon.species_id)',
        'string.format("%04X:%04X:%02X", mon.ot_id, mon.dv_word, mon.species_id)')))


@pytest.mark.parametrize("title,name,other", [
    ("silver", "silver.engine_sites.json", "gold.engine_sites.json"),  # U1 is per title
    ("gold", "gold.engine_sites.json", "silver.engine_sites.json"),
    ("crystal", "crystal.write_window.json", "gold.write_window.json"),  # only Silver follows Gold's U2
])
def test_each_title_admits_only_with_its_own_receipts(title, name, other):
    with pytest.raises(Refused, match="PHYSICAL proof refused"):
        production(title, files={f"/receipts/{name}": (RECEIPTS / other).read_text()})


@pytest.mark.parametrize("name,path,value", [
    ("crystal.engine_sites.json", ("evidence_level",), "MODEL"),
    ("crystal.write_window.json", ("runs", "town", "evidence_level"), "MODEL"),
    ("crystal_battle.qualification.json", ("fixtures", 0, "artifacts", "fixture", "sha256"), "0" * 64),
])
def test_a_forged_or_model_receipt_refuses_production(name, path, value):
    receipt = json.loads((ROOT / "data/games/gen2_crystal/receipts" / name).read_text())
    node = receipt
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(Refused, match="PHYSICAL proof refused"):
        production(files={f"/receipts/{name}": json.dumps(receipt)})


RUN_HOST = r"""
return function(rom, root, pc_log)
    local frames, callbacks = {}, {}
    memory = {
        read_u8 = function(a, d) if d == "ROM" then return rom:byte(a + 1) or 0 end return 0 end,
        write_u8 = function() end,
        getmemorydomainsize = function(d) return d == "ROM" and #rom or 0x10000 end,
        getmemorydomainlist = function() return {"ROM", "System Bus", "CartRAM"} end,
    }
    emu = {framecount = function() return 1 end, getregister = function() return 0 end}
    event = {
        onframeend = function(fn) frames[#frames + 1] = fn end,
        onexit = function() end,
        on_bus_exec = function(fn, addr, name) callbacks[name] = addr; return name end,
        unregisterbyid = function() return true end,
    }
    console = {log = function(t) pc_log[#pc_log + 1] = t end}
    package.loaded.connector = {init = function() end, send = function() end, receive = function() end,
                                pump = function() end, connected = function() return false end}
    package.loaded.hud = {init = function() end, render = function() end, show = function() end}
    SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS = "stale", "stale"
    dofile(root .. "/lua/gen2/run.lua")
    return frames, callbacks
end
"""


@pytest.mark.parametrize("title,artifact", [("crystal", None), ("gold", None), ("silver", None),
                                            ("crystal", "pokecrystal11")])
def test_run_lua_exposes_the_production_client_only_for_an_admitted_cartridge(title, artifact):
    """The H1 duo driver's contract: SLINK_GEN2_CLIENT / SLINK_GEN2_PARTS (production_admitted),
    the client's own onframeend tick; nil for a refused cartridge (Crystal 1.1 is BUILD_ONLY)."""
    profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
    repo = "pokecrystal" if title == "crystal" else "pokegold"
    rom = (ROOT / f".cache/gen2-build/{repo}/{artifact or profile['artifact']}.gbc").read_bytes()
    lua = LuaRuntime(unpack_returned_tuples=True)
    logs = lua.table()
    frames, callbacks = lua.execute(RUN_HOST)(rom, ROOT.as_posix(), logs)
    g = lua.globals()
    if artifact is None:
        assert g.SLINK_GEN2_PARTS.production_admitted is True
        assert g.SLINK_GEN2_PARTS.qualification == "PHYSICAL_RECEIPTED" and g.SLINK_GEN2_PARTS.title == title
        assert lua.eval("rawequal")(g.SLINK_GEN2_PARTS.client, g.SLINK_GEN2_CLIENT) and len(frames) == 1
        assert callbacks["SLink-gen2-checkpoint"] == CHECKPOINT[title]["primary"]["execution_before"]["pc"]
        assert any("PRODUCTION" in line for line in logs.values())
    else:
        assert g.SLINK_GEN2_CLIENT is None and g.SLINK_GEN2_PARTS is None and len(frames) == 0
        assert any("refused" in line and "BUILD_ONLY" in line for line in logs.values())


# ── card BOX: box_mon / party_mon / memorialize through the composed executor (MODEL candidate) ───────
BOX_KINDS = {"party_hp", "box_deposit", "party_collection", "box_withdraw", "backing_box"}


def box_world(party, box=(), covered=BOX_KINDS):
    world = World()
    world.covered = set(covered)
    world.field("wSavedAtLeastOnce", 1)
    world.party(list(party))
    world.box(list(box))
    world.hello()
    world.frames(60)   # a live validation enables writes
    world.checkpoint_ok = False
    return world


def storage(world, index):
    flat = world.profile["storage_boxes"][index]["flat"]
    return [world.io.read_u8(flat + i, "CartRAM") for i in range(1102)]


def active(world):
    flat = world.profile["derived"]["active_box_flat"]
    return [world.io.read_u8(flat + i, "CartRAM") for i in range(1102)]


def party_count(world):
    return world.io.read_u8(world.profile["ram"]["wPartyCount"])


def test_box_mon_deposits_at_the_checkpoint_after_stats_cache():
    lead, pichu = mon(), mon(species=172, dvs=0x3AAA)
    world = box_world([lead, pichu])
    world.reply({"cmd": "box_mon", "key": codec_key(pichu)})
    world.frames(1)
    assert party_count(world) == 2 and world.sent("stats_cache") == []   # nothing outside the checkpoint
    world.checkpoint_ok = True
    world.frames(1)
    (cache,) = world.sent("stats_cache")
    assert cache["key"] == codec_key(pichu) and world.sent("box_mon_failed") == []
    assert party_count(world) == 1 and active(world)[0:3] == [1, 172, 255]
    world.frames(30)
    assert [e["key"] for e in world.sent("tick")[-1]["pc_boxes"]] == [codec_key(pichu)]


def test_party_mon_withdraws_and_acks_sync_retrieve_done():
    lead, boxed = mon(), mon(species=19, dvs=0x7AAA)
    world = box_world([lead], [boxed])
    world.checkpoint_ok = True
    world.reply({"cmd": "party_mon", "key": codec_key(boxed)})
    world.frames(2)
    assert [m["key"] for m in world.sent("sync_retrieve_done")] == [codec_key(boxed)]
    assert party_count(world) == 2 and active(world)[0] == 0


def test_memorialize_moves_the_mon_into_box_14_and_acks_with_the_box():
    lead, dead = mon(), mon(species=19, dvs=0x7AAA, hp=0)
    world = box_world([lead, dead])
    world.checkpoint_ok = True
    world.reply({"cmd": "memorialize", "key": codec_key(dead)})
    world.frames(2)
    (done,) = world.sent("memorialize_done")
    assert done["key"] == codec_key(dead) and done["box"] == 13
    assert storage(world, 13)[0:3] == [1, 19, 255] and party_count(world) == 1


def test_a_whiteout_rebuild_party_mon_waits_behind_the_memorial_that_frees_a_slot():
    """Gen 1 A5/rebuild rule: party full -> tail requeue (bounded); the memorialize queued after it frees
    the slot, then the retry lands. sync_retrieve_failed would be final at the server (state.py)."""
    six = [mon(species=20 + i, dvs=0x1000 * (i + 1)) for i in range(6)]
    boxed = mon(species=19, dvs=0x7AAA)
    world = box_world(six, [boxed])
    world.checkpoint_ok = True
    world.reply({"cmd": "party_mon", "key": codec_key(boxed)}, {"cmd": "memorialize", "key": codec_key(six[5])})
    world.frames(4)
    assert world.sent("sync_retrieve_failed") == []
    events = [m["event"] for m in world.sent() if m["event"] in ("memorialize_done", "sync_retrieve_done")]
    assert events == ["memorialize_done", "sync_retrieve_done"]


def test_a_genuinely_full_party_still_fails_the_retrieve():
    six = [mon(species=20 + i, dvs=0x1000 * (i + 1)) for i in range(6)]
    boxed = mon(species=19, dvs=0x7AAA)
    world = box_world(six, [boxed])
    world.checkpoint_ok = True
    world.reply({"cmd": "party_mon", "key": codec_key(boxed)})
    world.frames(5)
    (nack,) = world.sent("sync_retrieve_failed")
    assert nack["key"] == codec_key(boxed) and "party full" in nack["reason"]


def test_the_last_party_mon_memorial_waits_for_the_rebuild_or_drops_after_game_over():
    lead, boxed = mon(hp=0), mon(species=19, dvs=0x7AAA)
    world = box_world([lead], [boxed])
    world.checkpoint_ok = True
    world.reply({"cmd": "memorialize", "key": codec_key(lead)}, {"cmd": "party_mon", "key": codec_key(boxed)})
    world.frames(4)
    events = [m["event"] for m in world.sent() if m["event"] in ("memorialize_done", "sync_retrieve_done",
                                                                  "memorialize_failed")]
    assert events == ["sync_retrieve_done", "memorialize_done"]
    world = box_world([lead])
    world.checkpoint_ok = True
    world.reply({"cmd": "game_over"}, {"cmd": "memorialize", "key": codec_key(lead)})
    world.frames(4)
    assert world.sent("memorialize_done") == [] and world.sent("memorialize_failed") == []
    assert party_count(world) == 1


@pytest.mark.parametrize("cmd,nack", [("box_mon", "box_mon_failed"), ("party_mon", "sync_retrieve_failed"),
                                      ("memorialize", "memorialize_failed")])
def test_an_unproven_write_kind_is_nacked_with_the_kind_and_writes_nothing(cmd, nack):
    lead, other = mon(), mon(species=19, dvs=0x7AAA)
    world = box_world([lead] if cmd == "party_mon" else [lead, other], [other] if cmd == "party_mon" else [],
                      covered={"party_hp", "box_deposit"})
    world.checkpoint_ok = True
    world.reply({"cmd": cmd, "key": codec_key(other)})
    world.frames(2)
    (refusal,) = world.sent(nack)
    assert refusal["key"] == codec_key(other) and "party_collection" in refusal["reason"]
    assert world.written() == []


def test_one_hello_across_a_battle_whose_animations_switch_the_wram_bank():
    """gen2-hello-flap (LIVE2 C<->C reconnect: HELLO_AGAIN every 30-80 frames in a wild battle). Battle
    animations select SVBK = BANK(wBGPals1) = 5 (C engine/battle_anims/anim_commands.asm:1413,
    bg_effects.asm:2562,2589); a frame-end read then finds WRAMX unmapped. That is no identity change."""
    def check(world):
        world.hello()
        generation = world.client.hello_session.status(world.client.hello_session).generation
        world.field("wBattleMode", 1)
        for _ in range(4):
            world.emu.wram_bank = 5
            world.frames(1)
            world.emu.wram_bank = 1
            world.frames(3)
        assert len(world.sent("hello")) == 1
        assert world.client.hello_session.status(world.client.hello_session).generation == generation
        world.field("wPlayerID", 0x4321, 2)   # a real identity change still re-hellos
        world.frames(2)
        assert len(world.sent("hello")) == 2

    falsify(check, mutant("lua/gen2/client.lua", (
        "if io.bank_valid(profile.ram_bank.wPlayerID, profile.ram.wPlayerID, 1) ~= true then return end", "")))
