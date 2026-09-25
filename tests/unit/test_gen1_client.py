"""C-0/C-4 (MODEL): the whole Gen 1 client, built by lua/gen1/entry.lua exactly as production
builds it, driven under lupa against a fake BizHawk and a fake server. Every line it sends is
checked against tests/unit/protocol_schema.py; every write is read back through the Python
codec; the real write-safety checkpoint and the real clean ROM are used.
"""
from __future__ import annotations

import json
import pathlib
import random
import re

import lupa
import pytest

from server.adapters import gen1_codec as codec
from tests.unit import protocol_schema as ps

REPO = pathlib.Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "games" / "gen1_rby"
PROFILE = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))["titles"]
SITES = json.loads((DATA / "engine_signals.json").read_text(encoding="utf-8"))["titles"]
WS = json.loads((DATA / "write_checkpoint.json").read_text(encoding="utf-8"))
DUMPS = {"red": "gen1_red.gb", "blue": "gen1_blue.gb", "yellow": "gen1_yellow.gbc"}
ENTRY = (REPO / "lua" / "gen1" / "entry.lua").as_posix()
CLIENT_LUA = (REPO / "lua" / "gen1" / "client.lua").read_text(encoding="utf-8")


def _client_const(name):
    """The rival-swap window bounds, read from the client so the budgets below cannot drift.

    Their VALUES are lower bounds derived from the engine's explicit delays and are expected to
    be retuned against the `RIVAL_WINDOW init_frames=N staged_frames=M` measurement; only the
    NAMES are pinned here.
    """
    m = re.search(rf"\b{name}\s*=\s*(\d+)", CLIENT_LUA)
    assert m, f"lua/gen1/client.lua carries no {name}"
    return int(m.group(1))


RIVAL_INIT_FRAMES = _client_const("RIVAL_INIT_FRAMES")
RIVAL_STAGED_FRAMES = _client_const("RIVAL_STAGED_FRAMES")


def _rom(title):
    path = REPO / "patch" / "build" / DUMPS[title]
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    return path.read_bytes()


class World:
    """Fake BizHawk + fake server. The ROM is the real clean dump; WRAM/CartRAM are bytearrays."""

    def __init__(self, title="red", player="a"):
        self.title, self.player = title, player
        self.ram = PROFILE[title]["ram"]
        self.d = PROFILE[title]["derived"]
        self.rom = _rom(title)
        self.bus = bytearray(0x10000)
        self.cart = bytearray(0x8000)
        self.regs = {"PC": 0, "SP": 0xDFF0, "H": 0, "L": 0, "F": 0}
        self.frame = 0
        self.hooks = {}
        self.next_hook = 1
        self.connected = False
        self.sent: list[dict] = []
        self.replies: list[str] = []
        self.hud: list[tuple] = []
        self.writes: list[tuple[int, int, str]] = []
        self.saveram_calls = 0
        self.logs: list[str] = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        L = self.lua
        io = L.table(
            read_u8=self._read_u8, read_range=self._read_range, write_u8=self._write_u8,
            on_bus_exec=self._on_bus_exec, unregister=lambda i: None,
            framecount=lambda: self.frame, register=lambda name: self.regs[str(name)],
            domains=lambda: L.table("System Bus", "ROM", "CartRAM"),
            saveram=self._saveram,
        )
        net = L.table(
            init=lambda h, p: None, connected=lambda: self.connected, pump=lambda: None,
            send=lambda line: self.sent.append(json.loads(str(line))),
            receive=lambda: self.replies.pop(0) if self.replies else None,
        )
        self.io, self.net = io, net
        hud = L.table(
            show=lambda *a: self.hud.append(("show",) + tuple(str(x) if isinstance(x, str) else x for x in a)),
            prompt=lambda *a: self.hud.append(("prompt",) + tuple(str(x) if isinstance(x, str) else x for x in a)),
            set_game_over=lambda: self.hud.append(("game_over",)),
            set_rebuilding=lambda t: self.hud.append(("rebuilding", str(t))),
            clear_rebuilding=lambda: self.hud.append(("rebuild_done",)),
            nuzlocke_start=lambda *a: self.hud.append(("nuzlocke_start",) + tuple(str(x) if isinstance(x, str) else x for x in a)),
        )
        Entry = L.eval(f'dofile("{ENTRY}")')
        deps = L.table(root=REPO.as_posix(), io=io, net=net, hud=hud, title=title, player=player,
                       rom_sha1="deadbeef", log=lambda t: self.logs.append(str(t)))
        self.client, self.parts = Entry.build(deps)
        self.client.start(self.client)
        self.overworld_safe()

    # -- BizHawk fakes ------------------------------------------------------------------
    def _dom(self, domain):
        return str(domain) if domain is not None else "System Bus"

    def _read_u8(self, addr, domain=None):
        addr, dom = int(addr), self._dom(domain)
        if dom == "ROM":
            return self.rom[addr]
        if dom == "CartRAM":
            return self.cart[addr]
        if addr < 0x8000:
            bank = self.bus[self.ram["hLoadedROMBank"]] or 1
            flat = addr if addr < 0x4000 else bank * 0x4000 + (addr - 0x4000)
            return self.rom[flat] if flat < len(self.rom) else 0
        return self.bus[addr]

    def _read_range(self, addr, length, domain=None):
        return self.lua.table(*[self._read_u8(int(addr) + i, domain) for i in range(int(length))])

    def _write_u8(self, addr, value, domain=None):
        addr, dom = int(addr), self._dom(domain)
        (self.cart if dom == "CartRAM" else self.bus)[addr] = int(value)
        self.writes.append((addr, int(value), dom))

    def _on_bus_exec(self, fn, addr, name, domain=None):
        hid = self.next_hook
        self.next_hook += 1
        self.hooks[str(name)] = (fn, int(addr))
        return hid

    def _saveram(self):
        self.saveram_calls += 1

    # -- game state helpers -------------------------------------------------------------
    def seed_party(self, mons, ot="RED"):
        r = self.ram
        self.bus[r["wPartyCount"]] = len(mons)
        for i in range(6):
            self.bus[r["wPartySpecies"] + i] = 0
        for i, m in enumerate(mons):
            self.bus[r["wPartySpecies"] + i] = m["species"]
            base = r["wPartyMons"] + i * 44
            self.bus[base:base + 44] = codec.encode_party_mon(m)
            self.bus[r["wPartyMonOT"] + i * 11:r["wPartyMonOT"] + i * 11 + 11] = codec.encode_name(ot)
            self.bus[r["wPartyMonNicks"] + i * 11:r["wPartyMonNicks"] + i * 11 + 11] = codec.encode_name(m.get("nick", "MON"))
        self.bus[r["wPartySpecies"] + len(mons)] = 0xFF
        self.bus[r["wPlayerID"]] = 0x12
        self.bus[r["wPlayerID"] + 1] = 0x34
        self.bus[r["wPlayerName"]:r["wPlayerName"] + 11] = codec.encode_name(ot)
        self.bus[r["wBoxSpecies"]] = 0xFF
        self.bus[r["wCurrentBoxNum"]] = 0  # boxes never initialised: SRAM boxes are garbage

    def give_poke_ball(self, quantity=1):
        r = self.ram
        self.bus[r["wNumBagItems"]] = 1
        self.bus[r["wBagItems"]], self.bus[r["wBagItems"] + 1] = 0x04, quantity  # POKE_BALL
        self.bus[r["wBagItems"] + 2] = 0xFF

    def party(self):
        r = self.ram
        return codec.decode_party(bytes(self.bus[r["wPartyCount"]:r["wPartyCount"] + 404]))

    def set_map(self, map_id, x=5, y=5):
        self.bus[self.ram["wCurMap"]] = map_id
        self.bus[self.ram["wXCoord"]], self.bus[self.ram["wYCoord"]] = x, y

    def overworld_safe(self):
        """Put the CPU where gen1_write_safety.check accepts: parked in DelayFrame from OverworldLoop."""
        ws = WS[self.title]["write_safe"]
        self.regs["PC"], self.regs["SP"] = ws["irq_vector"], 0xDFE0
        sp = self.regs["SP"]
        resume, caller = ws["delay_frame"] + 5, ws["overworld_loop"] + 3
        self.bus[sp], self.bus[sp + 1] = resume & 0xFF, resume >> 8
        self.bus[sp + 2], self.bus[sp + 3] = caller & 0xFF, caller >> 8
        self.bus[ws["vblank_flag"]] = 1
        self.bus[ws["link_state"]] = ws["link_none"]
        self.bus[ws["serial_status"]] = ws["disconnected_serial"]
        self.bus[ws["entering_cable_club"]] = 0
        self.bus[self.ram["wIsInBattle"]] = 0
        self.bus[self.ram["wJoyIgnore"]] = 0
        self.bus[self.ram["wFontLoaded"]] = 0

    def in_battle(self, opponent, species, level, active_slot=0):
        r = self.ram
        self.bus[r["wIsInBattle"]] = 1 if opponent < 200 else 2
        self.bus[r["wCurOpponent"]] = opponent
        self.bus[r["wEnemyMonSpecies2"]] = species
        self.bus[r["wCurEnemyLevel"]] = level
        self.bus[r["wEnemyMonSpecies"]] = species
        self.bus[r["wEnemyMonLevel"]] = level
        self.bus[r["wPlayerMonNumber"]] = active_slot
        self.bus[r["wBattleType"]] = 0
        p = self.party()[active_slot]
        self.bus[r["wBattleMonSpecies"]] = p["species"]
        self.bus[r["wBattleMonHP"]], self.bus[r["wBattleMonHP"] + 1] = p["hp"] >> 8, p["hp"] & 0xFF

    # -- driving --------------------------------------------------------------------------
    def fire(self, kind):
        site = SITES[self.title]["sites"][kind]
        self.bus[self.ram["hLoadedROMBank"]] = site["bank"]
        self.regs["PC"] = site["address"] + site.get("capture_offset", 0)
        fn, _ = self.hooks[f"SLink-gen1-{kind}"]
        fn()

    def step(self, n=1):
        for _ in range(n):
            self.frame += 1
            self.client.frame_end(self.client)

    def connect(self):
        self.connected = True
        self.step()

    def reply(self, *cmds):
        self.replies.append(json.dumps({"commands": list(cmds)}))

    def events(self, kind=None):
        out = [m for m in self.sent if kind is None or m["event"] == kind]
        return out

    def assert_all_conform(self):
        for m in self.sent:
            problems = ps.validate_event(m)
            assert not problems, (m, problems)


def _mon(rng, species, level=5, hp=None, nick="MON"):
    m = codec.decode_party_mon(bytes(rng.randrange(256) for _ in range(44)))
    m["species"], m["level"], m["status"] = species, level, 0
    m["max_hp"] = 20 + rng.randrange(20)
    m["hp"] = m["max_hp"] if hp is None else hp
    m["nick"] = nick
    return m


@pytest.fixture
def world():
    w = World("red")
    rng = random.Random(1)
    w.seed_party([_mon(rng, 0x99, nick="BULBA"), _mon(rng, 0xB1, nick="PIDGEY")])  # Bulbasaur, Pidgey
    w.set_map(0x0C)  # Route 1
    w.give_poke_ball()  # the battle fixture stands on Route 1 with ONE ball; the gate is open
    return w


# ── session ──────────────────────────────────────────────────────────────────────────────

def test_hello_on_connect_conforms_and_carries_identity(world):
    world.connect()
    hello = world.events("hello")
    assert len(hello) == 1
    h = hello[0]
    assert h["rom_type"] == "Red" and h["player"] == "a" and h["seq"] == 1
    assert h["ot_id"] == 0x1234 and h["trainer_name"] == "RED"
    assert h["area_id"] == "route_1" and h["loc_name"] == "Route 1"
    assert [e["species_id"] for e in h["party"]] == [0x99, 0xB1]
    assert all(len(e["blob_hex"]) == 66 * 2 for e in h["party"])
    assert h["party"][0]["key"] == codec.key(world.party()[0])
    world.assert_all_conform()


def test_tick_every_30_frames_and_area_enter_on_map_change(world):
    world.connect()
    world.step(30)
    assert len(world.events("tick")) >= 1
    tick = world.events("tick")[-1]
    assert tick["in_battle"] is False and tick["enemy_party"] == [] and tick["area_id"] == "route_1"
    world.set_map(0x00)  # Pallet Town
    world.step(30)
    assert world.events("area_enter")[-1]["area_id"] == "pallet_town"
    world.assert_all_conform()


def test_reconnect_sends_hello_again_and_seq_keeps_growing(world):
    world.connect()
    world.connected = False
    world.step(5)
    world.connected = True
    world.step(1)
    hellos = world.events("hello")
    assert len(hellos) == 2 and hellos[1]["seq"] > hellos[0]["seq"]


# ── signals → events ─────────────────────────────────────────────────────────────────────

def test_wild_capture_emits_one_capture_with_the_new_key_and_suppresses_no_catch(world):
    world.connect()
    world.in_battle(opponent=0xA5, species=0xA5, level=3)  # wild Rattata
    world.fire("wild_begin")
    world.step()
    # the engine adds the caught mon: AddPartyMon fires first, the party changes after
    world.bus[world.ram["wMonDataLocation"]] = 0
    world.fire("add_party_mon")
    world.step()
    rng = random.Random(2)
    party = world.party() + [_mon(rng, 0xA5, level=3, nick="RATTA")]
    world.seed_party(party)
    world.step(2)  # the struct must read complete on two consecutive frames (add_mon.asm:58-243)
    caps = world.events("capture")
    assert len(caps) == 1
    c = caps[0]
    assert c["species_id"] == 0xA5 and c["level"] == 3 and c["area_id"] == "route_1"
    assert c["gift"] is False and c["in_box"] is False and c["key"] == codec.key(world.party()[2])
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    assert world.events("no_catch") == []
    assert world.events("safe")  # first overworld frame after the battle
    world.assert_all_conform()


def test_wild_battle_without_capture_emits_no_catch_with_species(world):
    world.connect()
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.fire("wild_begin")
    world.step()
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    nc = world.events("no_catch")
    assert len(nc) == 1 and nc[0] == {"event": "no_catch", "player": "a", "seq": nc[0]["seq"],
                                      "area_id": "route_1", "species_id": 0xA5, "level": 3}
    # a second battle on the same, now resolved, area does not repeat it
    world.in_battle(opponent=0xA5, species=0xA5, level=4)
    world.fire("wild_begin")
    world.step()
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    assert len(world.events("no_catch")) == 1


def test_tower_ghost_battle_without_silph_scope_is_not_a_failed_encounter(world):
    """A Tower ghost cannot be fought or caught, so a battle there is no failed encounter.

    Without the Silph Scope in the bag the engine refuses the throw, so a wild battle ending
    on a Tower floor says nothing about the player failing to catch: the area must stay
    unresolved, or the run dead-zones the whole Tower (the old adapter did).
    """
    r = world.ram
    world.connect()
    world.set_map(0x8F)          # Pokemon Tower 2F; $8E-$94 all map to "pokemon_tower"
    world.step(30)
    assert world.events("tick")[-1]["area_id"] == "pokemon_tower", "the Tower map is unmapped"

    world.in_battle(opponent=0x5B, species=0x5B, level=20)   # wild Gastly
    world.fire("wild_begin")
    world.step()
    world.bus[r["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    assert world.events("no_catch") == [], "a Tower ghost was reported as a failed encounter"

    # With the Scope (item_constants.asm:84) the same battle IS a failed encounter -- which
    # also proves the ghost above left the area unresolved: a resolved area would swallow it.
    world.bus[r["wNumBagItems"]] = 1
    world.bus[r["wBagItems"]], world.bus[r["wBagItems"] + 1] = 0x48, 1
    world.bus[r["wBagItems"] + 2] = 0xFF
    world.in_battle(opponent=0x5B, species=0x5B, level=21)
    world.fire("wild_begin")
    world.step()
    world.bus[r["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    nc = world.events("no_catch")
    assert len(nc) == 1, f"the scoped battle produced {len(nc)} no_catch events"
    assert nc[0]["area_id"] == "pokemon_tower" and nc[0]["species_id"] == 0x5B
    world.assert_all_conform()


def test_static_encounter_gets_its_own_area_id_not_the_map(world):
    """Route 12's Snorlax is a scripted encounter: it must not consume the route's wild slot.

    The species list comes from data/games/gen1_rby/static_encounters.json ("23": SNORLAX),
    which tools/gen_gen1_statics.py reads out of the decomps; the client is handed it as
    `statics` (entry.lua will wire that in, the test sets it directly).
    """
    r = world.ram
    world.connect()
    world.client.statics = world.lua.table_from({"23": world.lua.table_from([0x84])})  # SNORLAX
    world.set_map(0x17)                 # ROUTE_12 (map_constants.asm:53)
    world.step(30)
    assert world.events("tick")[-1]["area_id"] == "route_12", "the route is unmapped"

    world.in_battle(opponent=0x84, species=0x84, level=30)   # the static Snorlax
    world.fire("wild_begin")
    world.step()
    world.bus[r["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    nc = world.events("no_catch")
    assert len(nc) == 1 and nc[0]["area_id"] == "static_23_143", nc

    # The same map with an ordinary wild mon still resolves the route's own area id, so the
    # static id is not swallowing the route.
    world.in_battle(opponent=0x24, species=0x24, level=3)    # wild Pidgey
    world.fire("wild_begin")
    world.step()
    world.bus[r["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    nc = world.events("no_catch")
    assert len(nc) == 2 and nc[-1]["area_id"] == "route_12", nc
    world.assert_all_conform()


def test_trainer_battle_start_is_sent_once_with_the_200_form_id(world):
    world.connect()
    world.in_battle(opponent=0xE1, species=0xB0, level=5)  # RIVAL1 = class 225
    world.fire("battle_begin")
    world.step()
    tb = world.events("trainer_battle_start")
    assert tb == [{"event": "trainer_battle_start", "player": "a", "seq": tb[0]["seq"], "trainer_id": 0xE1}]
    world.step(30)
    tick = world.events("tick")[-1]
    assert tick["in_battle"] is True and tick["is_trainer_battle"] is True and tick["trainer_id"] == 0xE1
    world.assert_all_conform()


def test_gift_mon_outside_battle_is_a_gift_capture_on_a_gift_area(world):
    world.connect()
    world.set_map(0x28)  # Oak's Lab
    world.step()
    world.bus[world.ram["wMonDataLocation"]] = 0
    world.fire("add_party_mon")
    world.step()
    rng = random.Random(3)
    world.seed_party(world.party() + [_mon(rng, 0xB0, level=5, nick="CHARM")])
    world.step(2)
    c = world.events("capture")[-1]
    assert c["gift"] is True and c["area_id"] == "gift_map_40"


def test_enemy_party_build_and_npc_trade_do_not_look_like_captures(world):
    world.connect()
    world.bus[world.ram["wMonDataLocation"]] = 0x01  # ReadTrainer building the enemy party
    world.fire("add_party_mon")
    world.step(3)
    assert world.events("capture") == []
    # NPC trade: the npc_trade signal owns the change and it becomes a key_change
    old = codec.key(world.party()[1])
    world.bus[world.ram["wWhichPokemon"]] = 1
    world.fire("npc_trade")
    world.bus[world.ram["wMonDataLocation"]] = 0x80
    world.fire("add_party_mon")
    world.step()
    rng = random.Random(4)
    party = world.party()
    party[1] = _mon(rng, 0x2D, level=10, nick="JYNX")  # last-slot trade: append restores slot 1
    world.seed_party(party)
    world.fire("npc_trade_done")
    world.step()
    kc = world.events("key_change")
    assert len(kc) == 1 and kc[0]["old_key"] == old and kc[0]["new_key"] == codec.key(world.party()[1])
    assert kc[0]["reason"] == "npc_trade" and kc[0]["new_species"] == 0x2D
    assert world.events("capture") == []
    world.assert_all_conform()


def test_faint_in_battle_names_the_active_slot_and_whiteout_when_none_alive(world):
    world.connect()
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=1)
    world.fire("wild_begin")
    world.step()
    # slot 1 faints: engine zeroes the party HP and calls RemoveFaintedPlayerMon
    party = world.party()
    party[1]["hp"] = 0
    world.seed_party(party)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=1)
    world.fire("battle_faint")
    world.step()
    f = world.events("faint")
    assert len(f) == 1 and f[0]["key"] == codec.key(party[1]) and f[0]["area_id"] == "route_1"
    assert world.events("whiteout") == []  # slot 0 still alive
    # now slot 0 faints too -> whiteout
    party = world.party()
    party[0]["hp"] = 0
    world.seed_party(party)
    world.bus[world.ram["wPlayerMonNumber"]] = 0
    world.fire("battle_faint")
    world.step()
    assert len(world.events("faint")) == 2 and len(world.events("whiteout")) == 1
    world.fire("blackout")
    world.step()
    assert len(world.events("whiteout")) == 1  # not repeated
    world.assert_all_conform()


def test_poison_faint_in_the_overworld_names_the_slot_from_wWhichPokemon(world):
    """S-4: ApplyOutOfBattlePoisonDamage.noBorrow fires once per mon the step's damage killed.

    At that site `wWhichPokemon` is the party slot and its HP bytes are already zero, so the
    faint carries the right key without any polling; two poison deaths in a row must produce
    two faints and exactly one whiteout, and neither may need a battle.
    """
    world.connect()
    party = world.party()
    party[1]["hp"] = 0            # the step's damage zeroed it
    world.seed_party(party)
    world.bus[world.ram["wWhichPokemon"]] = 1
    world.fire("poison_faint")
    world.step()
    f = world.events("faint")
    assert len(f) == 1 and f[0]["key"] == codec.key(party[1]) and f[0]["area_id"] == "route_1"
    assert world.events("whiteout") == []   # slot 0 alive
    # slot 0 faints from poison too -> whiteout exactly once
    party = world.party()
    party[0]["hp"] = 0
    world.seed_party(party)
    world.bus[world.ram["wWhichPokemon"]] = 0
    world.fire("poison_faint")
    world.step()
    assert len(world.events("faint")) == 2 and len(world.events("whiteout")) == 1
    world.assert_all_conform()


def test_pc_moves_come_from_the_movemon_signal_direction(world):
    world.connect()
    party = world.party()
    world.bus[world.ram["wMoveMonType"]] = 1  # PARTY_TO_BOX
    world.bus[world.ram["wWhichPokemon"]] = 1
    world.fire("move_mon")
    world.step()
    ptb = world.events("party_to_box")
    assert len(ptb) == 1 and ptb[0]["key"] == codec.key(party[1]) and ptb[0]["stats"]["maxHP"] == party[1]["max_hp"]
    world.assert_all_conform()


def test_save_witness_flushes_saveram(world):
    world.connect()
    world.fire("save_witness")
    world.step()
    assert world.saveram_calls == 1


# ── commands ─────────────────────────────────────────────────────────────────────────────

def test_bench_force_faint_is_deferred_to_the_overworld_checkpoint(world):
    world.connect()
    world.step(60)  # validation enables writes
    key = codec.key(world.party()[1])
    world.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"})
    world.regs["PC"] = 0x1234  # not at the checkpoint yet
    world.step(3)
    assert world.party()[1]["hp"] > 0
    world.overworld_safe()
    world.step()
    m = world.party()[1]
    assert m["hp"] == 0 and m["status"] == 0
    assert all(dom == "System Bus" for _, _, dom in world.writes)


def test_active_force_faint_waits_for_the_battle_loop_head(world):
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[0])
    world.reply({"cmd": "force_faint", "key": key})
    world.step(3)
    assert world.party()[0]["hp"] > 0, "no write until the engine judges HP"
    world.fire("battle_loop_head")
    assert world.bus[world.ram["wBattleMonHP"]] == 0 and world.bus[world.ram["wBattleMonHP"] + 1] == 0
    assert world.bus[world.ram["wPlayerSelectedMove"]] == 0xFF
    assert world.party()[0]["hp"] == 0


def _kod(world):
    return [h for h in world.hud if h[0] == "show" and "KO'd" in h[1]]


@pytest.mark.parametrize("cmd", ["force_faint", "force_explode"])
def test_benched_partner_faints_the_frame_the_command_arrives(world, cmd):
    """Live run 2026-09-22: a benched mon whose partner died stayed alive (and switchable)
    for the rest of the battle; then (owner 2026-09-22) even the loop-head write left the
    battle menu open to switching it in. The bench write lands on receipt."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    active_hp = world.party()[0]["hp"]
    key = codec.key(world.party()[1])
    world.reply({"cmd": cmd, "key": key, "nickname": "PIDGEY"})
    world.step()
    m = world.party()[1]
    assert m["hp"] == 0 and m["status"] == 0, "the bench mon dies before any loop head"
    assert world.party()[0]["hp"] == active_hp, "the active battler is untouched"
    assert world.bus[world.ram["wBattleMonMoves"]] != 0x99, "no EXPLOSION stamped on the wrong mon"
    assert len(_kod(world)) == 1
    n = len(world.writes)
    world.fire("battle_loop_head")
    assert len(world.writes) == n, "still dead on the bench: the loop head moves no byte"
    assert world.party()[1]["hp"] == 0 and world.party()[0]["hp"] == active_hp
    assert [h[1] for h in _kod(world)] == ["!! PIDGEY KO'd"], "one banner, not one per path"
    assert len(world.client.pending_battle_writes) == 0


def test_a_landed_bench_write_revived_before_the_loop_head_is_zeroed_again(world):
    """REVIVE works on a bench mon mid-battle (item_effects.asm:926-960): the queued entry
    re-zeroes it at the loop head, without a second banner."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[1])
    world.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"})
    world.step()
    hp = world.ram["wPartyMons"] + 44 + 1
    world.bus[hp], world.bus[hp + 1] = 0, 7
    world.fire("battle_loop_head")
    assert world.party()[1]["hp"] == 0
    assert len(_kod(world)) == 1


def test_a_landed_bench_write_whose_battle_ends_is_rezeroed_silently_at_the_checkpoint(world):
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[1])
    world.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"})
    world.step()
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.overworld_safe()
    world.step(2)
    assert world.party()[1]["hp"] == 0
    assert len(world.client.pending_battle_writes) == 0 and len(world.client.deferred) == 0
    assert len(_kod(world)) == 1


def test_a_landed_bench_write_switched_in_is_settled_by_the_active_path(world):
    """The race: the player picked the mon (HasMonFainted passed) before the write, and
    SwitchPlayerMon loaded it into wBattleMon afterwards -- the battle copy is live."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    mon = world.party()[1]
    key = codec.key(mon)
    world.reply({"cmd": "force_explode", "key": key, "nickname": "PIDGEY"})
    world.step()
    assert world.party()[1]["hp"] == 0
    r = world.ram
    world.bus[r["wPlayerMonNumber"]] = 1
    world.bus[r["wBattleMonSpecies"]] = mon["species"]
    world.bus[r["wBattleMonHP"]], world.bus[r["wBattleMonHP"] + 1] = 0, 9  # a live battle copy
    world.fire("battle_loop_head")
    assert world.bus[r["wBattleMonHP"]] == 0 and world.bus[r["wBattleMonHP"] + 1] == 0
    assert world.bus[r["wPlayerSelectedMove"]] == 0xFF
    assert world.bus[r["wBattleMonMoves"]] != 0x99, "already dead: it does not get to explode"
    assert len(_kod(world)) == 1
    assert len(world.client.pending_battle_writes) == 0


@pytest.mark.parametrize("battle_type,slot,cmd", [(1, 0, "force_faint"), (1, 1, "force_faint"),
                                                  (2, 0, "force_faint"), (2, 1, "force_explode")])
def test_special_battle_bench_death_lands_in_battle(world, battle_type, slot, cmd):
    """O-30 (owner: every faint lands in battle, link excepted). The old man tutorial (1) and a
    Safari battle (2) never send a player mon out: StartBattle takes .displaySafariZoneBattleMenu
    for any wBattleType != 0 and loops back to .checkAnyPartyAlive, never MainInBattleLoop
    (pokered core.asm:164-207). So the loop head never fires and EVERY party mon is bench,
    slot 0 included (wPlayerMonNumber is only InitBattleVariables' zero, init_battle_variables.asm:16).
    The write must land on receipt; the checkpoint only re-zeroes it quietly."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.bus[world.ram["wBattleType"]] = battle_type
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[slot])
    world.reply({"cmd": cmd, "key": key})
    world.step()
    assert world.party()[slot]["hp"] == 0, "lands in battle, on receipt"
    assert len(_kod(world)) == 1
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.overworld_safe()
    world.step(2)
    assert world.party()[slot]["hp"] == 0 and len(_kod(world)) == 1, "quiet backstop, no second banner"


def test_bench_write_in_a_link_battle_still_waits_for_the_checkpoint(world):
    """O-30's one exception: a link battle would desync the other Game Boy."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.bus[world.ram["wLinkState"]] = 4  # LINK_STATE_BATTLING
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[1])
    world.reply({"cmd": "force_faint", "key": key})
    world.step()
    assert world.party()[1]["hp"] > 0, "no write on receipt"
    world.fire("battle_loop_head")
    assert world.party()[1]["hp"] > 0, "nor at the loop head"
    world.bus[world.ram["wLinkState"]] = 0
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.overworld_safe()
    world.step(2)
    assert world.party()[1]["hp"] == 0, "the checkpoint lands it"


def test_a_battle_write_that_never_landed_is_applied_after_the_battle(world):
    """The battle ended before a loop head: the queued write must fall to the checkpoint,
    not sit in pending_battle_writes until some later battle."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[0])
    world.reply({"cmd": "force_explode", "key": key})
    world.step()
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.overworld_safe()
    world.step(2)
    assert world.party()[0]["hp"] == 0
    assert len(world.client.pending_battle_writes) == 0


@pytest.mark.parametrize("special", [False, True])
def test_a_battle_held_force_faint_keeps_its_place_ahead_of_the_later_memorialize(world, special):
    """The server queues force_faint then memorialize for one key (state.py _propagate_faint).
    In battle the faint is held in pending_battle_writes; the hand-over used to APPEND it behind
    the memorialize, which buried the live mon first and then dropped the faint ("key not in
    party"). Gen 3 684bbb7a, same shape. Two hand-over sites, one leg each:
    - plain: the ACTIVE battler, the battle ends before a loop head -> the battle_end flush;
    - special: a BENCH mon in a special battle (wBattleType 2) -> the loop-head fallback, which
      is the only path for it (the active-battler guard refuses a special battle and keeps the
      entry, so an active target would still hand over at battle_end -- review O14 F1)."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    slot = 1 if special else 0
    key = codec.key(world.party()[slot])
    world.reply({"cmd": "force_faint", "key": key}, {"cmd": "memorialize", "key": key})
    world.step()

    def queued():
        return [str(world.client.deferred[i]["cmd"]) for i in range(1, len(world.client.deferred) + 1)]

    if special:
        world.bus[world.ram["wBattleType"]] = 2
        world.fire("battle_loop_head")
        assert queued() == ["force_faint", "memorialize"], "loop-head fallback: " + str(queued())
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step()                                # the battle_end signal is handled on the frame
    assert queued() == ["force_faint", "memorialize"], queued()
    world.overworld_safe()
    world.step()                                # one command per frame: the faint lands first
    assert world.party()[slot]["hp"] == 0 and codec.key(world.party()[slot]) == key,         "the faint must land on the live mon before the memorialize moves it"
    world.step(3)
    assert not any("force_faint dropped" in line or "failed" in line for line in world.logs), world.logs
    assert len(world.events("memorialize_done")) == 1


def test_hello_waits_for_the_overworld_checkpoint_not_the_main_menu(world):
    # MainMenu -> TryLoadSaveFile: the save is in WRAM (party readable, wPlayerID set) before
    # the player chooses CONTINUE or NEW GAME, so a readable party is not "in the game"
    world.regs["PC"] = 0x1234  # not parked in OverworldLoop
    world.connect()
    world.step(90)
    assert world.events("hello") == []
    world.overworld_safe()
    world.step()
    assert len(world.events("hello")) == 1
    # a cleared WRAM (reset) makes the next live game a new session: hello again
    saved = bytes(world.bus)
    r = world.ram
    for a in range(r["wPartyCount"], r["wPartyCount"] + 8):
        world.bus[a] = 0
    world.bus[r["wPlayerID"]] = world.bus[r["wPlayerID"] + 1] = 0
    world.regs["PC"] = 0x1234
    world.step(60)
    world.bus[:] = saved  # CONTINUE reloaded the same save
    world.overworld_safe()
    world.step()
    hellos = world.events("hello")
    assert len(hellos) == 2 and hellos[1]["ot_id"] == hellos[0]["ot_id"]
    world.assert_all_conform()


def test_reconnect_inside_a_battle_hellos_without_waiting_for_the_checkpoint(world):
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.regs["PC"] = 0x1234
    world.connected = False
    world.step(2)
    world.connected = True
    world.step()
    assert len(world.events("hello")) == 2 and world.events("hello")[-1]["in_battle"] is True


def test_box_refusals_carry_the_box_module_reason(world):
    world.connect()
    world.step(60)
    world.reply({"cmd": "box_mon", "key": "0000:0000:99"})  # never in the party
    world.overworld_safe()
    world.step(2)
    failed = world.events("box_mon_failed")
    assert len(failed) == 1 and failed[0]["reason"] == "key not in party"


def test_deferred_force_faint_whose_mon_left_the_party_writes_nothing_and_says_so(world):
    world.connect()
    world.step(60)
    key = codec.key(world.party()[1])
    world.reply({"cmd": "force_faint", "key": key})
    world.regs["PC"] = 0x1234
    world.step(2)
    world.seed_party(world.party()[:1])  # the player deposited it before the checkpoint
    world.overworld_safe()
    world.step()
    assert [w for w in world.writes if w[2] == "System Bus"] == []
    assert any("dropped at the checkpoint" in line for line in world.logs)


def test_a_battle_write_queued_before_a_pause_still_lands_at_the_loop_head(world):
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[0])
    world.reply({"cmd": "force_faint", "key": key})
    world.step()
    # the party goes unreadable mid-battle for five validations (list/struct disagree)
    world.bus[world.ram["wPartyCount"]] = 3
    world.bus[world.ram["wPartySpecies"] + 2] = 0xA5
    world.bus[world.ram["wPartySpecies"] + 3] = 0xFF
    world.step(60 * 5)
    assert world.client.writes_enabled is False
    world.bus[world.ram["wPartyCount"]] = 2
    world.bus[world.ram["wPartySpecies"] + 2] = 0xFF
    world.step(60)
    assert world.client.writes_enabled is True
    world.fire("battle_loop_head")
    assert world.bus[world.ram["wBattleMonHP"]] == 0 and world.bus[world.ram["wBattleMonHP"] + 1] == 0
    assert world.party()[0]["hp"] == 0


def test_hud_commands_and_prompt_cancels(world):
    world.connect()
    world.reply({"cmd": "hud_show", "text": "[x] WRONG SAVE: slot A", "color": [255, 0, 0], "duration": 600},
                {"cmd": "msgbox", "text": "Hi"}, {"cmd": "game_over"},
                {"cmd": "rebuild_start", "text": "REBUILDING", "keys": []}, {"cmd": "rebuild_done"},
                {"cmd": "show_choices", "token": "t1", "options": ["Trade", "Say hey"], "text": "?"},
                {"cmd": "choose_mon", "token": "t2"}, {"cmd": "show_menu", "token": "t3", "text": "?"},
                {"cmd": "resolved_areas", "areas": ["route_2"]}, {"cmd": "config", "pc_trade_npc": True})
    world.step()
    kinds = [h[0] for h in world.hud]
    assert kinds == ["show", "prompt", "game_over", "rebuilding", "rebuild_done"]
    assert world.hud[0][2:5] == (255, 0, 0)
    replies = [(m["event"], m.get("choice", m.get("slot"))) for m in world.sent if m["event"] in ("menu_result", "mon_chosen")]
    assert replies == [("menu_result", 127), ("mon_chosen", 7), ("menu_result", 0)]
    world.assert_all_conform()


def test_malformed_and_unknown_commands_do_not_wedge_the_client(world):
    world.connect()
    world.replies.append("this is not json\n")
    world.reply({"cmd": "bogus"}, {"cmd": "force_faint"}, {"cmd": "noop"})
    world.step(2)
    world.step(30)
    assert world.events("tick"), "the client kept ticking"


def test_writes_pause_after_five_invalid_validations_and_the_queue_survives(world):
    world.connect()
    world.step(60)
    assert world.client.writes_enabled is True
    key = codec.key(world.party()[1])
    # the engine's own transient: AddPartyMon bumps the count and species list, then runs the
    # AskName prompt before the struct lands (engine/pokemon/add_mon.asm) -> list/struct disagree
    world.bus[world.ram["wPartyCount"]] = 3
    world.bus[world.ram["wPartySpecies"] + 2] = 0xA5
    world.bus[world.ram["wPartySpecies"] + 3] = 0xFF
    world.reply({"cmd": "force_faint", "key": key})
    world.regs["PC"] = 0x1234  # a prompt, not the checkpoint
    world.step(60 * 5)
    assert world.client.writes_enabled is False
    assert [c["key"] for c in world.client.deferred.values()] == [key]  # paused, not dropped
    world.bus[world.ram["wPartyCount"]] = 2
    world.bus[world.ram["wPartySpecies"] + 2] = 0xFF
    world.overworld_safe()
    world.step(60)
    assert world.client.writes_enabled is True  # a live game again
    assert world.party()[1]["hp"] == 0 and len(world.client.deferred) == 0


def test_hello_waits_for_a_live_game_after_the_init_wram_clear(world):
    # home/init.asm zero-fills WRAM: count 0 with no terminator and wPlayerID 0 until the main
    # menu's TryLoadSaveFile reloads the save
    saved = bytes(world.bus)
    r = world.ram
    for a in range(r["wPartyCount"], r["wPartyCount"] + 8):
        world.bus[a] = 0
    world.bus[r["wPlayerID"]] = world.bus[r["wPlayerID"] + 1] = 0
    world.connect()
    world.step(90)
    assert world.sent == []
    world.bus[:] = saved
    world.step(60)
    hello = world.events("hello")
    assert len(hello) == 1 and hello[0]["ot_id"] == 0x1234 and hello[0]["seq"] == 1
    world.assert_all_conform()


# ── in-game SLINK TRADE (companion patch receptionist) ───────────────────────────────────

def _patched_world():
    """A World whose ROM copy carries the receptionist dispatch hook, so the client enables trade."""
    w = World("red")
    rom = bytearray(w.rom)
    rom[0x29C3:0x29C3 + 5] = bytes([0x21, 0x00, 0x4C, 0x06, 0x3F])
    w.rom = bytes(rom)
    w.client.trade_enabled = False
    w.client.start(w.client)  # re-arm signals against the patched ROM (adds the service site)
    rng = random.Random(11)
    w.seed_party([_mon(rng, 0x99, nick="BULBA")])
    w.set_map(0x29)  # Viridian Pokemon Center
    w.connect()
    return w


def _overlay(w):
    base = w.ram["wSerialPartyMonsPatchList"]
    return bytes(w.bus[base:base + 16])


def _game_writes(w, cmd, gen, **fields):
    """The patched game's side of the lease: header + command + generation (+6 last)."""
    base = w.ram["wSerialPartyMonsPatchList"]
    w.bus[base:base + 4] = b"SLT1"
    w.bus[base + 4] = 1
    w.bus[base + 5] = cmd
    for off, val in fields.items():
        w.bus[base + int(off[1:])] = val
    w.bus[base + 6] = gen


def test_receptionist_query_and_offer_round_trip_through_the_server(world):
    w = _patched_world()
    assert w.client.trade_enabled is True
    _game_writes(w, 1, 5, _7=4)              # availability query, gen 5, ack stale
    w.step()
    assert w.events("trade_query"), "the client asked the server which slots are eligible"
    w.reply({"cmd": "trade_mask", "mask": 0b1})
    w.step()
    ov = _overlay(w)
    assert ov[10] == 1 and ov[11] == 0b1 and ov[7] == 5 and any(ov[12:16])
    token = ov[12:16]
    _game_writes(w, 2, 6, _7=5, _8=0xFF, _9=0)  # offer slot 0, gen 6
    w.step()
    assert w.events("trade_offer")[-1]["slot"] == 0
    w.reply({"cmd": "trade_offer_ack", "ok": True})
    w.step()
    ov = _overlay(w)
    assert ov[8] == 0 and ov[7] == 6 and ov[12:16] == token
    w.assert_all_conform()


def test_partner_prompt_and_apply_drive_the_lease_and_report_the_received_mon(world):
    w = _patched_world()
    rng = random.Random(12)
    incoming = _mon(rng, 0xB1, level=7, nick="PIDGEY")
    blob = codec.encode_party_mon(incoming) + codec.encode_name("BLUE") + codec.encode_name("PIDGEY")
    base = w.ram["wSerialPartyMonsPatchList"]
    # partner side: YES/NO prompt with the initiator's mon staged
    w.reply({"cmd": "show_menu", "token": "t7", "text": "Trade?", "slot": 0, "blob_hex": blob.hex().upper()})
    w.step()
    ov = _overlay(w)
    assert ov[:4] == b"SLT1" and ov[5] == 3 and ov[9] == 0, "prompt armed on the lease"
    staged = codec.decode_party_mon(bytes(w.bus[w.ram["wEnemyMons"]:w.ram["wEnemyMons"] + 44]))
    assert staged["species"] == 0xB1 and staged["level"] == 7
    gen = ov[6]
    w.bus[base + 5], w.bus[base + 8], w.bus[base + 7] = 7, 0, gen  # game: DONE, YES, ack
    w.step()
    mr = w.events("menu_result")[-1]
    assert mr == {"event": "menu_result", "player": "a", "seq": mr["seq"], "token": "t7", "choice": 1}
    assert _overlay(w)[5] == 8, "released after the answer"
    # apply on this side: the game swaps and the received mon lands LAST
    old_key = codec.key(w.party()[0])
    w.reply({"cmd": "apply_trade", "slot": 0, "blob_hex": blob.hex().upper(), "old_key": old_key,
             "token": "t8", "partner_name": "BLUE"})
    w.step()
    ov = _overlay(w)
    assert ov[5] == 5, "apply armed"
    gen = ov[6]
    # the native routine removes the offered mon through _RemovePokemon (the pinned site fires
    # mid-apply, from the party) and appends the incoming one; neither is a PC event
    w.seed_party([incoming])
    w.bus[w.ram["wRemoveMonFromBox"]] = 0
    w.bus[w.ram["wWhichPokemon"]] = 0
    w.fire("remove_pokemon")
    w.step()
    w.bus[base + 5], w.bus[base + 8], w.bus[base + 7] = 7, 0, gen
    w.step()
    td = w.events("trade_done")[-1]
    assert td["new_key"] == codec.key(w.party()[0]) and td["new_species"] == 0xB1 and td["token"] == "t8"
    assert _overlay(w)[5] == 8
    assert w.events("party_to_box") == [] and w.events("box_to_party") == []
    w.assert_all_conform()


@pytest.mark.parametrize("result", [1, 3])
def test_partner_prompt_decline_or_refused_save_is_a_clean_refusal(world, result):
    """Review 1b33bc31 BLOCKER-2 (Gen 1): a NO to the trade, a NO to the forced save
    (trade_prompt.asm, both DONE result 1) or an unavailable prompt (3) answers choice 0,
    releases the lease and leaves no trade state to apply or declare uncertain."""
    w = _patched_world()
    rng = random.Random(14)
    blob = (codec.encode_party_mon(_mon(rng, 0xB1, level=7, nick="PIDGEY")) +
            codec.encode_name("BLUE") + codec.encode_name("PIDGEY"))
    base = w.ram["wSerialPartyMonsPatchList"]
    w.reply({"cmd": "show_menu", "token": "t7", "text": "Trade?", "slot": 0, "blob_hex": blob.hex().upper()})
    w.step()
    gen = _overlay(w)[6]
    w.bus[base + 5], w.bus[base + 8], w.bus[base + 7] = 7, result, gen  # game: DONE, refusal, ack
    w.step()
    mr = w.events("menu_result")[-1]
    assert mr["token"] == "t7" and mr["choice"] == 0
    assert _overlay(w)[5] == 8, "released after the refusal"
    assert w.client.trade_state is None and len(w.client.trade_owed) == 0
    w.step(3)
    assert w.events("trade_done") == [] and len(w.events("menu_result")) == 1
    w.assert_all_conform()


def test_slink_trade_reports_trade_done_and_never_key_change(world):
    """S-5: a SLINK trade is neither an evolution nor an NPC trade, so it emits no `key_change`.

    The received mon lands in the last slot under a new key -- exactly the shape the evolution
    and in-game-trade migrations are built for, which is why the absence is asserted rather
    than assumed. One `trade_done` reports it; no migration event may appear beside it.
    """
    w = _patched_world()
    rng = random.Random(13)
    incoming = _mon(rng, 0xB1, level=7, nick="PIDGEY")
    blob = codec.encode_party_mon(incoming) + codec.encode_name("BLUE") + codec.encode_name("PIDGEY")
    base = w.ram["wSerialPartyMonsPatchList"]
    old_key = codec.key(w.party()[0])
    w.reply({"cmd": "apply_trade", "slot": 0, "blob_hex": blob.hex().upper(), "old_key": old_key,
             "token": "t9", "partner_name": "BLUE"})
    w.step()
    ov = _overlay(w)
    assert ov[5] == 5, "apply armed"
    gen = ov[6]
    w.seed_party([incoming])          # the native routine replaced our only mon
    w.bus[base + 5], w.bus[base + 8], w.bus[base + 7] = 7, 0, gen
    w.step()
    assert len(w.events("trade_done")) == 1
    assert w.events("trade_done")[-1]["new_species"] == 0xB1
    assert w.events("key_change") == []
    assert _overlay(w)[5] == 8
    w.assert_all_conform()


def test_gift_capture_waits_for_the_whole_struct_not_a_half_written_one(world):
    """ball_gate_new live receipts 2026-09-17 (both cartridges): _AddPartyMon runs the AskName
    prompt (add_mon.asm:45-52) and only then writes the struct in order species, DVs,
    moves, OT, exp, EVs, PP, level, stats (add_mon.asm:58-243). The client settled on a
    read taken between the DV write and the OT write: capture key 74C2:0000:99, level 0,
    while the party a moment later held 74C2:4190:99. The server linked the wrong key."""
    world.connect()
    world.set_map(0x28)  # Oak's Lab
    world.step()
    world.bus[world.ram["wMonDataLocation"]] = 0
    world.fire("add_party_mon")
    world.step()
    rng = random.Random(3)
    full = _mon(rng, 0xB0, level=5, nick="CHARM")
    half = dict(full)
    half.update(ot_id=0, level=0, hp=0, max_hp=0, exp=0)
    before = len(world.events("capture"))
    world.seed_party(world.party() + [half])
    world.step()
    assert len(world.events("capture")) == before, "a half-written struct must not be reported"
    world.seed_party(world.party()[:-1] + [full])
    world.step(3)
    caps = world.events("capture")[before:]
    assert [c["key"] for c in caps] == [codec.key(full)]
    assert caps[0]["level"] == 5 and caps[0]["gift"] is True


def test_no_catch_is_withheld_until_the_first_poke_ball():
    """D-2: no encounter resolves before the ball gate. ball_gate_new live receipt 2026-09-17:
    the parcel walk met a Route 1 wild with an EMPTY bag, RUN sent no_catch, and the server
    (which has no ball gate by design, test_state.py::test_server_processes_no_catch_regardless_
    of_pokeballs) dead-zoned Route 1 for both players before either owned a ball."""
    world = World("red")
    rng = random.Random(1)
    world.seed_party([_mon(rng, 0x99, nick="BULBA")])
    world.set_map(0x0C)  # Route 1, empty bag
    world.connect()
    assert world.events("hello")[0]["has_pokeballs"] is False
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.fire("wild_begin")
    world.step()
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    assert world.events("no_catch") == [], "a RUN with no balls is not a failed encounter"
    # the first ball arrives; the SAME area is still open and the next RUN does count
    world.give_poke_ball()
    # the pinned site's filter (signals.lua:31-39): HL == wNumBagItems, carry set, wCurItem a ball
    world.regs["H"], world.regs["L"] = world.ram["wNumBagItems"] // 256, world.ram["wNumBagItems"] % 256
    world.regs["F"] = 0x10
    world.bus[world.ram["wCurItem"]] = 0x04
    world.fire("bag_received")
    world.step(2)
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.fire("wild_begin")
    world.step()
    world.bus[world.ram["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    assert [e["area_id"] for e in world.events("no_catch")] == ["route_1"]


# ── the in-game link panel (A11) ───────────────────────────────────────────────────────────
# The cartridge patch owns the screen and asks; the client answers within a deadline it
# measures from the transition IT observed. Everything below drives the mailbox exactly as
# slink.asm does (states 0/1/2 at $DEEB, page wanted at $DEEC, page count at $DEED).
PANEL_MAILBOX, PANEL_ABI, PANEL_CAPS = 0xDEE2, 0xDEE6, 0xDEEA
PANEL_STATE, PANEL_PAGE, PANEL_PAGES = 0xDEEB, 0xDEEC, 0xDEED
TILEMAP, PANEL_TILES = 0xC3A0, 360
PANEL_ROWS = [f"ROW {i}" for i in range(26)]   # 26 rows = two pages of 18


def _patch_panel(world, state=0, abi=3):
    """What the companion patch's VBlank hook leaves in WRAM on a patched cartridge."""
    world.bus[PANEL_MAILBOX:PANEL_MAILBOX + 4] = b"SLNK"
    world.bus[PANEL_ABI] = abi
    world.bus[PANEL_CAPS] = 0x02      # SLINK_CAP_PANEL
    world.bus[PANEL_STATE] = state


def _tiles(text):
    """panel.lua's _tile_for over a row padded/truncated to 20 (see lua/gen1/panel.lua's _tile_for)."""
    out = []
    for ch in text.ljust(20)[:20]:
        b = ord(ch)
        if 65 <= b <= 90:
            out.append(0x80 + b - 65)
        elif 97 <= b <= 122:
            out.append(0xA0 + b - 97)
        elif 48 <= b <= 57:
            out.append(0xF6 + b - 48)
        else:
            out.append({47: 0xF3, 45: 0xE3}.get(b, 0x7F))
    return out


def _row(world, n):
    return list(world.bus[TILEMAP + n * 20:TILEMAP + n * 20 + 20])


def test_hello_reports_no_panel_on_a_plain_cartridge(world):
    world.connect()
    h = world.events("hello")[0]
    assert h["panel"] is False and h["panel_abi"] == 0
    world.assert_all_conform()


def test_hello_reports_the_panel_and_its_abi_on_a_patched_cartridge(world):
    _patch_panel(world)
    world.connect()
    h = world.events("hello")[0]
    assert h["panel"] is True and h["panel_abi"] == 3
    world.assert_all_conform()


def test_the_panel_paints_a_page_on_the_open_and_the_next_on_a_page_turn(world):
    _patch_panel(world, state=0)          # CLOSED
    world.connect()
    world.reply({"cmd": "link_panel", "rows": PANEL_ROWS})
    world.step()                          # rows are held; the panel is still closed
    assert _row(world, 0) == [0] * 20, "nothing is painted while the panel is closed"

    world.bus[PANEL_STATE] = 1            # the patch opens: CLOSED -> AWAIT
    world.step()
    assert _row(world, 0) == _tiles("ROW 0")
    assert _row(world, 17) == _tiles("ROW 17")
    assert world.bus[PANEL_PAGES] == 2, "26 rows is two pages"
    assert world.bus[PANEL_STATE] == 2, "the screen is handed back STAGED"

    world.bus[PANEL_PAGE] = 1             # A: the patch bumps the page and re-enters AWAIT
    world.bus[PANEL_STATE] = 1
    world.step()
    assert _row(world, 0) == _tiles("ROW 18")
    assert _row(world, 8) == _tiles(""), "page 2 has eight rows and ten blanks"
    assert world.bus[PANEL_STATE] == 2


def test_a_mailbox_already_awaiting_at_first_sight_is_never_painted(world):
    _patch_panel(world, state=1)          # the client attached mid-open: age unknown
    world.connect()
    world.reply({"cmd": "link_panel", "rows": PANEL_ROWS})
    world.step(2)
    assert _row(world, 0) == [0] * 20
    assert world.bus[PANEL_STATE] == 1, "the patch keeps its fallback for this open"
    # known-positive control: the same rows DO paint on the next observed open
    world.bus[PANEL_STATE] = 0
    world.step()
    world.bus[PANEL_STATE] = 1
    world.step()
    assert _row(world, 0) == _tiles("ROW 0")


def test_rows_arriving_past_the_deadline_are_held_for_the_next_open(world):
    _patch_panel(world, state=0)
    world.connect()
    world.bus[PANEL_STATE] = 1            # observed CLOSED -> AWAIT on this frame
    world.step()
    world.step(60)
    world.reply({"cmd": "link_panel", "rows": PANEL_ROWS})
    world.step()                          # frame 61 after the transition: held, not painted
    world.step()
    assert _row(world, 0) == [0] * 20, "a late reply must not paint over a revealed fallback"
    assert world.bus[PANEL_STATE] == 1

    world.bus[PANEL_STATE] = 0            # B closes; the next open gets the held rows
    world.step()
    world.bus[PANEL_STATE] = 1
    world.step()
    assert _row(world, 0) == _tiles("ROW 0")
    assert world.bus[PANEL_STATE] == 2


# ── native sound (slink.asm SlinkSfxService) ───────────────────────────────────────────────
# The client writes a SEMANTIC code to mailbox +7 and the ROM plays the bank's sound for it on
# the main thread; here the ROM is a bytearray, so "played" is modelled by clearing the byte.
SFX_REQUEST, CAP_SFX_AND_PANEL = 0xDEE9, 0x03


def _patch_sfx(world):
    _patch_panel(world)
    world.bus[PANEL_CAPS] = CAP_SFX_AND_PANEL


def _sfx_writes(world):
    return [v for a, v, d in world.writes if a == SFX_REQUEST and d == "System Bus"]


def test_hello_reports_the_sfx_capability_per_cartridge(world):
    _patch_panel(world)                   # panel-only caps ($02): a pre-sound ABI-3 build
    world.connect()
    assert world.events("hello")[0]["sfx"] is False
    world.assert_all_conform()


def test_play_sound_becomes_a_semantic_code_when_the_run_and_cartridge_allow_it(world):
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.step()
    assert world.events("hello")[0]["sfx"] is True
    world.reply({"cmd": "play_sound", "sound": 25})        # SE_SUCCESS -> code 1
    world.step()
    assert world.bus[SFX_REQUEST] == 1 and _sfx_writes(world) == [1]
    world.bus[SFX_REQUEST] = 0                             # the ROM played it
    world.reply({"cmd": "play_sound", "sound": 26})        # SE_FAILURE -> code 2
    world.step()
    world.bus[SFX_REQUEST] = 0
    world.reply({"cmd": "play_sound", "sound": 22})        # SE_BOO -> code 3
    world.step()
    world.bus[SFX_REQUEST] = 0
    world.reply({"cmd": "play_sound", "sound": 95})        # SE_SHINY -> success (never sent for Gen 1)
    world.step()
    assert _sfx_writes(world) == [1, 2, 3, 1]
    world.assert_all_conform()


def test_everyday_success_is_the_short_notify_blip_on_a_cartridge_that_has_it(world):
    """Owner 2026-09-22: the long fanfare stays for nuzlocke start / shiny (95); link formed,
    trade done and new encounter (25) get code 4 (SFX_START_MENU) when caps bit 2 says the
    ROM knows it. The test above (caps $03) keeps 25 -> 1 for an older cartridge."""
    _patch_sfx(world)
    world.bus[PANEL_CAPS] = CAP_SFX_AND_PANEL | 0x04
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.step()
    world.reply({"cmd": "play_sound", "sound": 25})
    world.step()
    world.bus[SFX_REQUEST] = 0
    world.reply({"cmd": "play_sound", "sound": 95})
    world.step()
    assert _sfx_writes(world) == [4, 1]


def test_play_sound_is_silent_without_the_run_option_or_the_capability(world):
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "play_sound", "sound": 25})        # config never said native_sounds
    world.step()
    assert _sfx_writes(world) == [] and world.bus[SFX_REQUEST] == 0
    world.reply({"cmd": "config", "native_sounds": False})
    world.reply({"cmd": "play_sound", "sound": 25})
    world.step()
    assert _sfx_writes(world) == []
    world.bus[PANEL_CAPS] = 0x02                           # a panel-only cartridge
    world.reply({"cmd": "config", "native_sounds": True})
    world.reply({"cmd": "play_sound", "sound": 25})
    world.step()
    assert _sfx_writes(world) == [], "no SFX capability bit, no write"
    world.assert_all_conform()


def test_an_unknown_sound_id_writes_nothing(world):
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.reply({"cmd": "play_sound", "sound": 16})        # SE_FAINT: Gen 3 client-local only
    world.step()
    assert _sfx_writes(world) == []


def test_a_request_the_rom_is_still_holding_is_never_overwritten(world):
    """The ROM clears +7 when it plays; while it HOLDS one (fade, busy channel) a second write
    would lose the first, so the client queues and posts one per frame once the byte is free."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.reply({"cmd": "play_sound", "sound": 25}, {"cmd": "play_sound", "sound": 26})
    world.step()
    assert world.bus[SFX_REQUEST] == 1 and _sfx_writes(world) == [1]
    world.step(3)
    assert _sfx_writes(world) == [1], "still held by the ROM: nothing posted over it"
    world.bus[SFX_REQUEST] = 0                             # the fade ended, the ROM played it
    world.step()
    assert world.bus[SFX_REQUEST] == 2 and _sfx_writes(world) == [1, 2]
    # a burst in ONE frame is coalesced per semantic code before it reaches the queue
    # (cx-3987357f); with only three codes the panel's overflow (SFX_QUEUE_MAX, newest
    # wins) is now reachable only across frames -- panel.lua keeps it for that case
    world.bus[SFX_REQUEST] = 0
    world.reply(*[{"cmd": "play_sound", "sound": s} for s in (25, 26, 22, 25, 26, 22)])
    world.step()
    posted = _sfx_writes(world)[2:]
    assert posted == [1]                                   # the first posts immediately
    drained = []
    for _ in range(6):
        world.bus[SFX_REQUEST] = 0
        world.step()
        drained = _sfx_writes(world)[3:]
    assert drained == [2, 3], drained
    world.assert_all_conform()


def test_a_queued_request_does_not_post_after_native_sounds_is_switched_off(world):
    """Codex review cx-5f7b86be: the option was checked only on admission, so a request queued
    behind a held one would still post after `config.native_sounds=false`."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.reply({"cmd": "play_sound", "sound": 25}, {"cmd": "play_sound", "sound": 26})
    world.step()
    assert _sfx_writes(world) == [1]                       # the second is queued behind the held one
    world.reply({"cmd": "config", "native_sounds": False})
    world.step()
    world.bus[SFX_REQUEST] = 0                             # the ROM played the first
    world.step(3)
    assert _sfx_writes(world) == [1], "the queued request was dropped with the option"
    world.assert_all_conform()


# ── local HUD/SFX moments (Gen 3 parity: gen3_frlge_client.lua's client-only cues) ────────

def test_nuzlocke_banner_not_shown_at_a_hello_that_already_has_balls(world):
    """gen3_frlge_client.lua:1921-1926: a hello snapshot with balls already in the bag is a
    resume, not the moment of acquisition -- log only, no banner (the `world` fixture starts
    with one Poke Ball already given)."""
    world.connect()
    assert world.events("hello")[0]["has_pokeballs"] is True
    assert not any(h[0] == "nuzlocke_start" for h in world.hud)
    assert any("nuzlocke ACTIVE (pokeballs already in bag at startup)" in ln for ln in world.logs)
    world.assert_all_conform()


def test_nuzlocke_banner_fires_once_on_the_first_bag_received():
    world = World("red")
    rng = random.Random(1)
    world.seed_party([_mon(rng, 0x99, nick="BULBA")])
    world.set_map(0x0C)  # empty bag
    world.connect()
    assert world.events("hello")[0]["has_pokeballs"] is False
    assert not any(h[0] == "nuzlocke_start" for h in world.hud)
    world.give_poke_ball()
    # signals.lua:31-39's filter: HL == wNumBagItems, carry set, wCurItem a ball
    world.regs["H"], world.regs["L"] = world.ram["wNumBagItems"] // 256, world.ram["wNumBagItems"] % 256
    world.regs["F"] = 0x10
    world.bus[world.ram["wCurItem"]] = 0x04
    world.fire("bag_received")
    world.step()
    starts = [h for h in world.hud if h[0] == "nuzlocke_start"]
    assert len(starts) == 1 and starts[0][1] == "Nuzlocke Start!"
    world.fire("bag_received")  # a second bag event must not repeat it
    world.step()
    assert len([h for h in world.hud if h[0] == "nuzlocke_start"]) == 1
    world.assert_all_conform()


def test_nuzlocke_start_requests_the_native_success_cue_when_available():
    world = World("red")
    rng = random.Random(1)
    world.seed_party([_mon(rng, 0x99, nick="BULBA")])
    world.set_map(0x0C)
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.step()
    world.give_poke_ball()
    world.regs["H"], world.regs["L"] = world.ram["wNumBagItems"] // 256, world.ram["wNumBagItems"] % 256
    world.regs["F"] = 0x10
    world.bus[world.ram["wCurItem"]] = 0x04
    world.fire("bag_received")
    world.step()
    assert _sfx_writes(world) == [1], "SE_SHINY -> SFX_SUCCESS"


def test_new_encounter_banner_on_wild_begin_in_an_unresolved_area(world):
    world.connect()
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.step()
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.fire("wild_begin")
    world.step()
    shows = [h for h in world.hud if h[0] == "show" and "NEW ENCOUNTER" in h[1]]
    assert len(shows) == 1
    assert shows[0][1] == "** NEW ENCOUNTER **\nRoute 1"
    assert shows[0][2:] == (255, 220, 60, 360)
    world.assert_all_conform()


def test_new_encounter_banner_withheld_without_balls_or_before_resolved_areas_is_seeded():
    # no Poke Balls yet
    w1 = World("red")
    w1.seed_party([_mon(random.Random(1), 0x99, nick="BULBA")])
    w1.set_map(0x0C)
    w1.connect()
    w1.reply({"cmd": "resolved_areas", "areas": []})
    w1.step()
    w1.in_battle(opponent=0xA5, species=0xA5, level=3)
    w1.fire("wild_begin")
    w1.step()
    assert not any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in w1.hud), "no balls yet"

    # resolved_areas never seeded from the server
    w2 = World("red")
    w2.seed_party([_mon(random.Random(1), 0x99, nick="BULBA")])
    w2.set_map(0x0C)
    w2.give_poke_ball()
    w2.connect()
    w2.in_battle(opponent=0xA5, species=0xA5, level=3)
    w2.fire("wild_begin")
    w2.step()
    assert not any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in w2.hud), "unseeded"


def test_new_encounter_banner_withheld_for_an_already_resolved_area(world):
    world.connect()
    world.reply({"cmd": "resolved_areas", "areas": ["route_1"]})
    world.step()
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.fire("wild_begin")
    world.step()
    assert not any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in world.hud)
    world.assert_all_conform()


def test_new_encounter_banner_on_area_enter_via_tick(world):
    world.connect()
    world.step(30)  # first tick only establishes last_area; nil -> set sends no event
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.set_map(0x0D)  # Route 2
    world.step(30)
    shows = [h for h in world.hud if h[0] == "show" and "NEW ENCOUNTER" in h[1]]
    assert len(shows) == 1
    assert shows[0][1] == "** NEW ENCOUNTER **\nRoute 2"
    assert shows[0][2:] == (255, 220, 60, 240)
    assert [e["area_id"] for e in world.events("area_enter") if e["area_id"] == "route_2"] == ["route_2"]
    world.assert_all_conform()


def test_kod_banner_on_a_bench_force_faint_is_text_only(world):
    """gen3_frlge_client.lua:760-800: the server already queues play_sound 26 to this player
    in the same turn (state.py:2073/2884) -- no local SFX alongside the banner."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.step(60)
    key = codec.key(world.party()[1])
    world.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"})
    world.overworld_safe()
    world.step()
    kod = [h for h in world.hud if h[0] == "show" and "KO'd" in h[1]]
    assert len(kod) == 1
    assert kod[0][1] == "!! PIDGEY KO'd"
    assert kod[0][2:] == (255, 80, 80, 360)
    assert _sfx_writes(world) == [], "no local SFX for a KO"
    world.assert_all_conform()


def test_kod_banner_on_an_active_battler_force_faint(world):
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[0])
    world.reply({"cmd": "force_faint", "key": key, "nickname": "BULBA"})
    world.step(3)
    world.fire("battle_loop_head")
    kod = [h for h in world.hud if h[0] == "show" and "KO'd" in h[1]]
    assert len(kod) == 1 and kod[0][1] == "!! BULBA KO'd"


def test_game_over_command_plays_a_local_failure_cue(world):
    """gen3_frlge_client.lua:1026-1027: the server's game_over command carries no play_sound
    of its own (server/state.py:2103, :3202) -- the client supplies it locally. This is the
    LONE case of the coalescing pair in test_terminal_linked_faint_batch_posts_the_failure_cue_
    once below: game_over with no accompanying play_sound this frame still posts its cue."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True}, {"cmd": "game_over"})
    world.step()
    assert _sfx_writes(world) == [2], "SE_FAILURE -> code 2, Gen 3's default SE_GAME_OVER"
    assert ("game_over",) in world.hud
    world.assert_all_conform()


def test_whiteout_plays_a_local_boo_cue_once(world):
    """gen3_frlge_client.lua:3804-3816: the client's own whiteout detection gets a local cue --
    the server's reply to `whiteout` never queues a play_sound (server/state.py _handle_whiteout)."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.step()
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=1)
    world.fire("wild_begin")
    world.step()
    party = world.party()
    party[1]["hp"] = 0
    world.seed_party(party)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=1)
    world.fire("battle_faint")
    world.step()
    assert _sfx_writes(world) == [], "one mon down, party not wiped yet"
    party = world.party()
    party[0]["hp"] = 0
    world.seed_party(party)
    world.bus[world.ram["wPlayerMonNumber"]] = 0
    world.fire("battle_faint")
    world.step()
    assert _sfx_writes(world) == [3], "SE_BOO -> code 3, once"
    world.fire("blackout")
    world.step()
    assert _sfx_writes(world) == [3], "not repeated"
    world.assert_all_conform()


def test_box_mon_and_party_mon_show_boxed_and_unboxed_banners(world):
    world.connect()
    world.step(60)
    key = codec.key(world.party()[0])  # BULBA
    stats = {"level": world.party()[0]["level"], "maxHP": world.party()[0]["max_hp"]}
    world.overworld_safe()
    world.reply({"cmd": "box_mon", "key": key})
    world.step(2)
    boxed = [h for h in world.hud if h[0] == "show" and "boxed" in h[1]]
    assert len(boxed) == 1
    assert boxed[0][1] == "↓ BULBA boxed"
    assert boxed[0][2:] == (100, 180, 255, 200)

    world.reply({"cmd": "party_mon", "key": key, "stats": stats, "nickname": "BULBA"})
    world.overworld_safe()
    world.step(2)
    unboxed = [h for h in world.hud if h[0] == "show" and "unboxed" in h[1]]
    assert len(unboxed) == 1
    assert unboxed[0][1] == "↑ BULBA unboxed"
    assert unboxed[0][2:] == (100, 255, 160, 200)
    world.assert_all_conform()


def test_box_mon_failure_shows_the_fail_banner(world):
    world.connect()
    world.step(60)
    world.reply({"cmd": "box_mon", "key": "0000:0000:99"})  # never in the party
    world.overworld_safe()
    world.step(2)
    failed = [h for h in world.hud if h[0] == "show" and "Box fail" in h[1]]
    assert len(failed) == 1
    assert failed[0][1] == "X Box fail: 0000:000"
    assert failed[0][2:] == (255, 80, 80, 240)
    world.assert_all_conform()


def test_memorialize_shows_the_buried_banner(world):
    world.connect()
    world.step(60)
    pidgey_key = codec.key(world.party()[1])
    world.overworld_safe()
    world.reply({"cmd": "memorialize", "key": pidgey_key})
    world.step(2)
    buried = [h for h in world.hud if h[0] == "show" and "buried" in h[1]]
    assert len(buried) == 1
    assert buried[0][1] == "† PIDGEY buried"
    assert buried[0][2:] == (255, 140, 40, 300)
    world.assert_all_conform()


def test_memorialize_failure_shows_the_fail_banner(world):
    world.connect()
    world.step(60)
    world.overworld_safe()
    world.reply({"cmd": "memorialize", "key": "0000:0000:99"})  # never in the party
    world.step(2)
    failed = [h for h in world.hud if h[0] == "show" and "Mem fail" in h[1]]
    assert len(failed) == 1
    assert failed[0][1] == "X Mem fail: 0000:000"
    assert failed[0][2:] == (255, 80, 80, 300)
    world.assert_all_conform()


# ── local HUD/SFX moments: adversarial-review regressions (cx-6bedd222) ───────────────────

def test_new_encounter_banner_withheld_for_a_static_encounter(world):
    """A scripted encounter (Route 12's Snorlax) resolves nothing about the route's own wild
    slot -- gen3_frlge_client.lua's own gate excludes it the same way."""
    world.connect()
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.client.statics = world.lua.table_from({"23": world.lua.table_from([0x84])})  # SNORLAX
    world.set_map(0x17)  # Route 12
    world.step(30)
    world.in_battle(opponent=0x84, species=0x84, level=30)
    world.fire("wild_begin")
    world.step()
    assert not any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in world.hud)
    world.assert_all_conform()


def test_new_encounter_banner_withheld_for_a_demonstration_battle(world):
    """Y-0: the old man's Weedle demo (BATTLE_TYPE_OLD_MAN) is not the player's own encounter."""
    world.connect()
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.step()
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.bus[world.ram["wBattleType"]] = 1  # BATTLE_TYPE_OLD_MAN
    world.fire("battle_begin")
    world.step()
    assert not any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in world.hud)
    world.assert_all_conform()


def test_new_encounter_banner_withheld_for_a_tower_ghost_without_the_scope(world):
    r = world.ram
    world.connect()
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.set_map(0x8F)  # Pokemon Tower 2F
    world.step(30)
    world.in_battle(opponent=0x5B, species=0x5B, level=20)
    world.fire("wild_begin")
    world.step()
    assert not any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in world.hud), "no Scope: not a real encounter"
    # control: WITH the Scope the same battle DOES flag a new encounter
    world.bus[r["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    world.bus[r["wNumBagItems"]] = 1
    world.bus[r["wBagItems"]], world.bus[r["wBagItems"] + 1] = 0x48, 1
    world.bus[r["wBagItems"] + 2] = 0xFF
    world.in_battle(opponent=0x5B, species=0x5B, level=21)
    world.fire("wild_begin")
    world.step()
    assert any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in world.hud), "Scope in hand: a real encounter"
    world.assert_all_conform()


def test_new_encounter_banner_withheld_returning_to_a_gift_area_with_no_wild_table(world):
    """cx-6bedd222: 'not gift_map_*' is not 'not a gift area' -- oaks_lab (map 40) is a real,
    non-gift-prefixed area_id the server lists in _GIFT_AREAS, but the client can only see
    that it has no wild table (self.wild_maps from rom.rom_content()), which is the same
    reason it must not banner."""
    world.connect()
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.step(30)
    world.set_map(0x28)  # Oak's Lab
    world.step(30)
    assert [e["area_id"] for e in world.events("area_enter") if e["area_id"] == "oaks_lab"] == ["oaks_lab"]
    assert not any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in world.hud)
    world.assert_all_conform()


def test_new_encounter_banner_on_area_enter_fires_once_not_again_while_staying(world):
    world.connect()
    world.step(30)  # first tick only establishes last_area; nil -> set sends no event
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.set_map(0x0D)  # Route 2: has a wild table
    world.step(30)
    shows = [h for h in world.hud if h[0] == "show" and "NEW ENCOUNTER" in h[1]]
    assert len(shows) == 1
    assert shows[0][1] == "** NEW ENCOUNTER **\nRoute 2"
    assert shows[0][2:] == (255, 220, 60, 240)
    world.step(60)  # staying put: no repeat
    assert len([h for h in world.hud if h[0] == "show" and "NEW ENCOUNTER" in h[1]]) == 1
    world.assert_all_conform()


def test_new_encounter_banner_withheld_for_a_map_change_mid_battle(world):
    world.connect()
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.step(30)
    world.in_battle(opponent=0xE1, species=0xB0, level=5)  # a trainer battle holds in_battle
    world.step()
    world.set_map(0x0D)  # Route 2, still "in battle" per wIsInBattle
    world.step(30)
    assert not any(h[0] == "show" and "NEW ENCOUNTER" in h[1] for h in world.hud)
    world.assert_all_conform()


def test_terminal_linked_faint_batch_posts_the_failure_cue_once(world):
    """state.py's partner batch on the last living pair lands force_faint + play_sound 26 +
    memorialize + game_over in ONE reply/frame; game_over's own local 26 must not double the
    cue panel.lua already queued for the force_faint (cx-6bedd222)."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.step(60)
    key = codec.key(world.party()[1])
    world.overworld_safe()
    world.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"},
                {"cmd": "play_sound", "sound": 26},
                {"cmd": "memorialize", "key": key},
                {"cmd": "game_over"})
    world.step()
    assert _sfx_writes(world) == [2], "one failure code, not two"
    world.assert_all_conform()


def test_same_frame_coalescing_is_a_set_not_the_last_code(world):
    """cx-3987357f: 26 -> 25 -> 26 in one reply posts failure ONCE and success once; the
    panel drains the queue as the ROM clears +7, so every distinct code still gets played."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.step(60)
    world.reply({"cmd": "play_sound", "sound": 26}, {"cmd": "play_sound", "sound": 25},
                {"cmd": "play_sound", "sound": 26})
    world.step()
    world.bus[SFX_REQUEST] = 0                             # the ROM played the first
    world.step(40)                                         # the panel posts the queued one
    world.bus[SFX_REQUEST] = 0
    world.step(40)
    assert _sfx_writes(world) == [2, 1], "failure once, success once, nothing queued twice"
    world.assert_all_conform()


def test_the_same_code_one_frame_later_is_a_new_cue(world):
    """The per-frame set must not swallow a genuine repeat on the next frame."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.step(60)
    world.reply({"cmd": "play_sound", "sound": 26})
    world.step()
    world.bus[SFX_REQUEST] = 0
    world.reply({"cmd": "play_sound", "sound": 26})
    world.step()
    assert _sfx_writes(world) == [2, 2]
    world.assert_all_conform()


def test_kod_banner_keeps_the_nickname_after_switching_out_before_the_loop_head(world):
    """cx-6bedd222: the active-battler-to-bench requeue in on_battle_loop_head dropped
    `w.nickname`, so a mon switched out before the write landed showed a key prefix instead."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[0])
    world.reply({"cmd": "force_faint", "key": key, "nickname": "BULBA"})
    world.step()
    # switched out before the loop head fires: find_party_slot's slot (0) no longer matches
    # the new active slot, so the write is requeued to the bench instead of landing here
    world.bus[world.ram["wPlayerMonNumber"]] = 1
    world.fire("battle_loop_head")
    world.overworld_safe()
    world.step()
    kod = [h for h in world.hud if h[0] == "show" and "KO'd" in h[1]]
    assert len(kod) == 1 and kod[0][1] == "!! BULBA KO'd", kod
    world.assert_all_conform()


def test_an_unmapped_sound_id_does_not_trip_the_unavailable_log(world):
    """cx-6bedd222: an id with no Gen 1 mapping must return early from request_sfx_local
    rather than falling into the 'unavailable' branch -- otherwise a later GENUINE
    unavailable case never logs, because the one-time flag was already spent on a non-event."""
    _patch_sfx(world)
    world.connect()
    world.reply({"cmd": "config", "native_sounds": True})
    world.reply({"cmd": "play_sound", "sound": 16})  # SE_FAINT: no Gen 1 mapping
    world.step()
    assert not any("native sounds off or no SFX-capable patch" in ln for ln in world.logs)
    world.bus[PANEL_CAPS] = 0x02  # now genuinely unavailable: no SFX capability bit
    world.reply({"cmd": "play_sound", "sound": 25})
    world.step()
    assert any("native sounds off or no SFX-capable patch" in ln for ln in world.logs)
    world.assert_all_conform()


def test_nuzlocke_banner_fires_on_the_send_tick_ball_count_edge():
    """The bag_received signal is the usual witness, but send_tick's own ball_count() edge
    must independently catch the transition too (e.g. a path bag_received does not cover)."""
    world = World("red")
    rng = random.Random(1)
    world.seed_party([_mon(rng, 0x99, nick="BULBA")])
    world.set_map(0x0C)
    world.connect()
    assert world.events("hello")[0]["has_pokeballs"] is False
    world.give_poke_ball()  # balls land in the bag without firing bag_received
    world.step(30)          # the next tick's ball_count() edge catches it
    starts = [h for h in world.hud if h[0] == "nuzlocke_start"]
    assert len(starts) == 1 and starts[0][1] == "Nuzlocke Start!"


def test_nuzlocke_banner_does_not_repeat_on_a_reconnect_hello(world):
    """A reconnect's second hello finds has_pokeballs already True -- not a fresh transition,
    so it must not re-banner (the `world` fixture already starts with one Poke Ball)."""
    world.connect()
    world.step(60)
    world.connected = False
    world.step(2)
    world.connected = True
    world.step()
    hellos = world.events("hello")
    assert len(hellos) == 2 and hellos[1]["has_pokeballs"] is True
    assert not any(h[0] == "nuzlocke_start" for h in world.hud)
    world.assert_all_conform()


def test_nuzlocke_announced_survives_a_soft_reset_and_does_not_refire():
    """One run, one banner: home/init.asm zero-fills WRAM on a reset and CONTINUE reloads the
    same save, but the latch is a client-session concept, not a save-file one -- it must not
    reset with the WRAM clear (unlike hello_sent/pending_change/retired_alias, which do)."""
    world = World("red")
    rng = random.Random(1)
    world.seed_party([_mon(rng, 0x99, nick="BULBA")])
    world.set_map(0x0C)
    world.connect()
    world.give_poke_ball()
    world.regs["H"], world.regs["L"] = world.ram["wNumBagItems"] // 256, world.ram["wNumBagItems"] % 256
    world.regs["F"] = 0x10
    world.bus[world.ram["wCurItem"]] = 0x04
    world.fire("bag_received")
    world.step()
    assert len([h for h in world.hud if h[0] == "nuzlocke_start"]) == 1
    assert world.client.nuzlocke_announced is True

    saved = bytes(world.bus)
    r = world.ram
    for a in range(r["wPartyCount"], r["wPartyCount"] + 8):
        world.bus[a] = 0
    world.bus[r["wPlayerID"]] = world.bus[r["wPlayerID"] + 1] = 0
    world.regs["PC"] = 0x1234
    world.step(60)
    world.bus[:] = saved  # CONTINUE reloaded the same save
    world.overworld_safe()
    world.step()
    assert world.client.nuzlocke_announced is True, "the latch survives the WRAM clear"
    world.fire("bag_received")  # a stray post-reload bag event must not re-fire it
    world.step()
    assert len([h for h in world.hud if h[0] == "nuzlocke_start"]) == 1


def test_retired_alias_refusal_at_the_checkpoint_shows_no_failure_banner(world):
    """The retired-alias refusal in run_deferred (a lost/ambiguous record) sends
    box_mon_failed/memorialize_failed straight to the server -- unlike the box-module failure
    paths above, it must not also show a HUD failure banner (cx-6bedd222 pin)."""
    world.connect()
    world.step(60)
    old_key = "0000:0000:99"
    new_key = codec.key(world.party()[0])
    world.client.retired_alias[old_key] = world.lua.table_from({
        "new_key": new_key,
        "evidence": world.lua.table_from({
            "nick": world.lua.table_from([0] * 11), "moves": world.lua.table_from([0] * 4),
        }),
    })
    world.overworld_safe()
    world.reply({"cmd": "memorialize", "key": old_key})
    world.step(2)
    assert [e["key"] for e in world.events("memorialize_failed")] == [old_key]
    assert not any(h[0] == "show" and "Mem fail" in h[1] for h in world.hud)
    world.assert_all_conform()


# ── the last client card: falsifying tests, written before the fixes ─────────────────────
# Each case below is RED against HEAD and names, in its own assertions, exactly what the
# implementer has to produce. Engine facts are pret pokered 405b624 / pokeyellow 0a08515.

def _box_mon(rng, species, level=5):
    """A 33-byte box record (macros/ram.asm:7-19); level lives in byte 3 for boxed mons."""
    m = codec.decode_party_mon(bytes(rng.randrange(256) for _ in range(33)), box=True)
    m["species"], m["box_level"], m["level"] = species, level, level
    return m


def _boxed(mon):
    """The box record `MoveMon` PARTY_TO_BOX writes: the party struct's first 33 bytes with the
    party level folded into byte 4 (add_mon.asm:409-427). Same DVs:OT:species, so the same key.
    """
    b = bytearray(codec.encode_party_mon(mon)[:33])
    b[3] = mon["level"]
    return codec.decode_party_mon(bytes(b), box=True)


def _fire_trade_service(w):
    """The cartridge reaching `SlinkTradeService`: the client pins that hook against the patched
    ROM itself (client.lua:1025-1036), so it is not a site `World.fire` can look up.
    """
    svc = w.client.trade.service_address()
    w.bus[w.ram["hLoadedROMBank"]] = int(svc["bank"])
    w.regs["PC"] = int(svc["addr"])
    w.hooks["SLink-gen1-trade_service"][0]()


def _withdrawn(rng, boxed, nick="BOXED"):
    """The party record Bill's WITHDRAW leaves behind: `MoveMon` BOX_TO_PARTY (bills_pc.asm:284)
    puts the mon in the PARTY before `RemovePokemon` clears the box slot (:285-287), so the same
    identity (DVs:OT:species, gen1_codec.key) is in the party when the removal fires.
    """
    m = _mon(rng, boxed["species"], level=boxed["level"], nick=nick)
    m["dvs"], m["ot_id"] = boxed["dvs"], boxed["ot_id"]
    return m


def _seed_active_box(world, mons, ot="RED", nick="BOXED"):
    """The open box's WRAM mirror (ram/wram.asm:2226-2248), the way seed_party does the party."""
    r, cap, stride = world.ram, world.d["box_capacity"], world.d["box_struct_size"]
    n = world.d["name_length"]
    world.bus[r["wBoxCount"]] = len(mons)
    for i in range(cap + 1):
        world.bus[r["wBoxSpecies"] + i] = 0
    for i, m in enumerate(mons):
        world.bus[r["wBoxSpecies"] + i] = m["species"]
        base = r["wBoxMons"] + i * stride
        world.bus[base:base + stride] = codec.encode_party_mon(m)
        world.bus[r["wBoxMonOT"] + i * n:r["wBoxMonOT"] + i * n + n] = codec.encode_name(ot)
        world.bus[r["wBoxMonNicks"] + i * n:r["wBoxMonNicks"] + i * n + n] = codec.encode_name(nick)
    world.bus[r["wBoxSpecies"] + len(mons)] = 0xFF


def _active_box_keys(world):
    """The open box's WRAM mirror read back (the inverse of _seed_active_box)."""
    r, stride = world.ram, world.d["box_struct_size"]
    out = []
    for i in range(world.bus[r["wBoxCount"]]):
        base = r["wBoxMons"] + i * stride
        out.append(codec.key(codec.decode_party_mon(bytes(world.bus[base:base + stride]), box=True)))
    return out


def _rival_blob(rng, species, level=9):
    """One 66-byte `replace_rival_team` blob: struct(44) + OT(11) + nick(11), as hex."""
    m = _mon(rng, species, level=level)
    return (codec.encode_party_mon(m) + codec.encode_name("BLUE") + codec.encode_name("MON")).hex().upper()


def test_a_refused_memorialize_goes_to_the_deferred_tail_so_a_queued_party_mon_runs_first(world):
    """A5: `memorialize` refuses the last party mon (boxes.lua:479) and client.lua:381 re-inserts
    the command at the HEAD of `deferred` (`table.insert(self.deferred, 1, cmd)`), which starves
    everything queued behind it -- including the rebuild `party_mon` that would make the memorial
    legal in the first place. Fix: append at the TAIL (`self.deferred[#self.deferred + 1] = cmd`),
    never "drop when party == 1" (a restore can arrive in a later reply). The server half of the
    ordering is already covered by test_state.py:1708-1735.
    """
    world.connect()
    world.step(60)                              # writes ENABLED
    world.seed_party(world.party()[:1])         # one mon: the memorialize can only be refused
    last = codec.key(world.party()[0])
    world.overworld_safe()
    world.reply({"cmd": "memorialize", "key": last},
                {"cmd": "party_mon", "key": "0000:0000:99", "stats": {"level": 5, "maxHP": 20}})
    world.step()                                # this frame drains the memorialize and refuses it
    queued = [str(world.client.deferred[i]["cmd"]) for i in (1, 2)]
    assert queued == ["party_mon", "memorialize"], f"a refused memorialize belongs at the tail, got {queued}"
    world.step()                                # one command per frame: now the party_mon
    assert [e["key"] for e in world.events("sync_retrieve_failed")] == ["0000:0000:99"], \
        "the party_mon queued behind the refused memorialize never ran"
    assert world.events("memorialize_failed") == [], "'last party mon' blocks, it does not NACK"
    world.assert_all_conform()


def test_party_to_box_keys_from_the_move_mon_snapshot_not_from_a_read_after_the_shift(world):
    """A6(1): the `move_mon` point must snapshot wPartyCount..+404 and the active box the way
    `battle_point` does (signals.lua:47-58), and the client must key from that snapshot.
    _MoveMon copies the mon and _RemovePokemon shifts every later slot down
    (engine/pokemon/add_mon.asm:365-413, remove_mon.asm:8-107), so by the time the client drains
    the signal the live party no longer holds the deposited mon: today client.lua:510-517 reads it
    live and reports the WRONG key for a non-last slot and NO event at all for the last slot.
    """
    r = world.ram
    world.connect()
    before = world.party()
    moved, stayed = before[0], before[1]
    world.bus[r["wMoveMonType"]] = 1            # PARTY_TO_BOX (menu_constants.asm:60-63)
    world.bus[r["wWhichPokemon"]] = 0
    world.fire("move_mon")
    world.seed_party(before[1:])                # the engine has already shifted slot 1 into slot 0
    world.step()
    ptb = world.events("party_to_box")
    assert len(ptb) == 1, ptb
    assert ptb[0]["key"] == codec.key(moved), "the DEPOSITED mon's key, not the one now in its slot"
    assert ptb[0]["key"] != codec.key(stayed)
    assert ptb[0]["stats"] == {"level": moved["level"], "maxHP": moved["max_hp"]}

    # the LAST slot: after the shift that slot does not exist, so a live read emits nothing at all
    world.seed_party(before)
    world.step()
    n = len(world.events("party_to_box"))
    world.bus[r["wWhichPokemon"]] = 1
    world.fire("move_mon")
    world.seed_party(before[:1])
    world.step()
    ptb = world.events("party_to_box")
    assert len(ptb) == n + 1, "a last-slot deposit still emits party_to_box"
    assert ptb[-1]["key"] == codec.key(stayed)
    world.assert_all_conform()


def test_a_standalone_box_removal_logs_a_release_marker_and_a_withdraw_does_not(world):
    """A6(2)/PC-1b: Bill's WITHDRAW also ends in wRemoveMonFromBox = 1 + RemovePokemon
    (bills_pc.asm:285-287, right after its BOX_TO_PARTY MoveMon at :284), so `from_box` alone is
    NOT the discriminator; the RELEASE is bills_pc.asm:310-312, which has no MoveMon at all. What
    separates them is an engine fact rather than a frame count: at this hook nothing has been
    removed yet (site offset 0 on `RemovePokemon`, home/move_mon.asm:20-21), so the key is in the
    BOX either way -- but the withdraw's MoveMon has already installed it in the PARTY and the
    release has not. The shared protocol has a release event (tests/unit/protocol_schema.py) and
    the server retires the linked pair on it, so a `party_to_box` for a key that was never in the
    party would be a lie. The client LOGS `RELEASE_SEEN key=<key> box=<index>` and sends
    `release{key}`; a WITHDRAW sends neither.
    """
    r = world.ram
    rng = random.Random(31)
    boxed = _box_mon(rng, 0xB0, level=6)                 # a Charmander in the open box
    _seed_active_box(world, [boxed])
    world.connect()

    # (a) WITHDRAW: MoveMon BOX_TO_PARTY and RemovePokemon(from_box=1) in ONE frame
    world.bus[r["wMoveMonType"]] = 0                     # BOX_TO_PARTY
    world.bus[r["wWhichPokemon"]] = 0
    world.fire("move_mon")
    world.seed_party(list(world.party()) + [_withdrawn(rng, boxed)])  # MoveMon ran before this
    _seed_active_box(world, [boxed])                     # the box slot is cleared only afterwards
    world.bus[r["wRemoveMonFromBox"]] = 1
    world.fire("remove_pokemon")
    world.step()
    assert [e["key"] for e in world.events("box_to_party")] == [codec.key(boxed)]
    assert world.events("party_to_box") == [], "a withdraw is not a deposit"
    assert [ln for ln in world.logs if "RELEASE_SEEN" in ln] == [], "a withdraw is not a release"

    # (b) RELEASE: a standalone box removal, no MoveMon and no party slot holding that key
    released = _box_mon(rng, 0x15, level=8)
    _seed_active_box(world, [released])
    world.step(3)
    n, nlog = len(world.sent), len(world.logs)
    world.bus[r["wRemoveMonFromBox"]] = 1
    world.bus[r["wWhichPokemon"]] = 0
    world.fire("remove_pokemon")
    world.step()
    marks = [ln for ln in world.logs[nlog:] if "RELEASE_SEEN" in ln]
    assert len(marks) == 1, marks
    assert f"RELEASE_SEEN key={codec.key(released)} box=0" in marks[0], marks[0]
    assert [(m["event"], m["key"]) for m in world.sent[n:] if m["event"] in ("party_to_box", "box_to_party", "release")] \
        == [("release", codec.key(released))], "O-35: a PC release sends release{key}; the server kills the partner"
    world.assert_all_conform()
def test_an_ambiguous_key_writes_nothing_on_either_lookup_path(world):
    """A8/D-13: the client has TWO key lookups -- `find_party_slot` takes the FIRST match
    (client.lua:216-221, used by force_faint/faint_party_slot and the box paths) and
    `on_battle_loop_head` takes the LAST (:621). One ambiguity-aware resolver must serve both:
    more than one matching slot returns nil + "ambiguous key", and force_faint/box/loop-head then
    log one line and skip (fail-closed, as boxes.lua:121-130 already refuses ambiguous
    duplicates). The server half exists (test_gen1_identity_and_collisions.py:72-128).
    Outbound ambiguity stays (emit_faint :422-425 reports the colliding key) -- D-13 is MODEL-only.
    """
    r = world.ram
    rng = random.Random(21)
    twin = _mon(rng, 0x99, nick="BULBA")
    other = dict(twin)
    other["nick"] = "CLONE"                     # same DVs + OT + species => the SAME identity key
    key = codec.key(twin)
    world.connect()
    world.step(60)

    # (a) the overworld checkpoint path
    world.seed_party([twin, other])
    assert codec.key(world.party()[0]) == codec.key(world.party()[1]) == key
    n = len(world.writes)
    world.reply({"cmd": "force_faint", "key": key})
    world.overworld_safe()
    world.step(2)
    assert world.writes[n:] == [], "an ambiguous key must not faint either candidate"
    assert world.party()[0]["hp"] > 0 and world.party()[1]["hp"] > 0
    amb = [ln for ln in world.logs if "ambiguous key" in ln and key in ln]
    assert len(amb) == 1, f"exactly one 'ambiguous key <key>' line on the checkpoint path: {amb}"

    # (b) the MainInBattleLoop hook path: the duplicate appears AFTER the command was queued
    world.seed_party([twin, _mon(rng, 0xB1, nick="PIDGEY")])
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    world.reply({"cmd": "force_faint", "key": key})
    world.step()
    assert len(world.client.pending_battle_writes) == 1, "queued for the loop head"
    world.seed_party([twin, other])
    hp_before = (world.bus[r["wBattleMonHP"]], world.bus[r["wBattleMonHP"] + 1])
    before = len(amb)
    world.fire("battle_loop_head")
    assert (world.bus[r["wBattleMonHP"]], world.bus[r["wBattleMonHP"] + 1]) == hp_before, \
        "the loop-head resolver must refuse an ambiguous key too"
    assert world.bus[r["wPlayerSelectedMove"]] != 0xFF
    assert world.party()[0]["hp"] > 0 and world.party()[1]["hp"] > 0
    amb = [ln for ln in world.logs if "ambiguous key" in ln and key in ln]
    assert len(amb) == before + 1, f"exactly one more line at the loop head: {amb}"

    # control (client.lua:564-566): a capture whose key the client already knows is never reported
    world.bus[r["wIsInBattle"]] = 0
    world.bus[r["wMonDataLocation"]] = 0
    world.fire("add_party_mon")
    world.step()
    newcomer = _mon(rng, 0x2D, level=8, nick="JYNX")
    world.seed_party([twin, other, newcomer])
    world.step(3)
    caps = world.events("capture")
    assert caps and caps[-1]["key"] == codec.key(newcomer), "the first sighting IS reported"
    world.bus[r["wMonDataLocation"]] = 0
    world.fire("add_party_mon")
    world.step()
    world.seed_party([twin, other, newcomer, dict(newcomer, nick="TWIN2")])
    world.step(3)
    assert len(world.events("capture")) == len(caps), "a key already known is never captured twice"
    world.assert_all_conform()


def test_a_demonstration_battle_type_emits_neither_capture_nor_no_catch(world):
    """Y-0: only the DEMONSTRATION battles are not the player's own encounter --
    BATTLE_TYPE_OLD_MAN (1) and Yellow's BATTLE_TYPE_PIKACHU (4)
    (constants/battle_constants.asm:43-46). Today the old-man Weedle demo dead-zones Viridian and
    Oak's Pikachu battle dead-zones Pallet Town. BATTLE_TYPE_SAFARI (2) IS a real encounter --
    item_effects.asm:130-137 spends the player's Safari Balls, :514-516 skips the catch only for
    the old man, :549-560 adds a Safari catch to the party/box -- so it keeps both semantics.
    `signals.lua:94-101` already captures `battle_type` in the point; gate client.lua's
    battle_begin/wild_begin handler on the explicit set {1, 4}.
    """
    r = world.ram
    world.connect()

    # (a) type 1, the old man's demo: nothing about Pallet Town was learned
    world.set_map(0x00)                                   # Pallet Town
    world.step()
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.bus[r["wBattleType"]] = 1
    world.fire("battle_begin")
    world.step()
    world.bus[r["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    assert world.events("no_catch") == [], "a demonstration battle is not a failed encounter"

    # (b) control: a type 2 battle on the SAME map does resolve it, which also proves (a) left
    # Pallet Town open -- a resolved area would have swallowed this one
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.bus[r["wBattleType"]] = 2                       # BATTLE_TYPE_SAFARI
    world.fire("battle_begin")
    world.step()
    world.bus[r["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    nc = world.events("no_catch")
    assert len(nc) == 1 and nc[0]["area_id"] == "pallet_town", nc

    # (c) type 4, Yellow's Pikachu demo: the mon Oak catches is not the player's capture
    world.set_map(0x0C)                                   # Route 1
    world.step()
    world.in_battle(opponent=0x54, species=0x54, level=5)
    world.bus[r["wBattleType"]] = 4
    world.fire("wild_begin")
    world.step()
    world.bus[r["wMonDataLocation"]] = 0
    world.fire("add_party_mon")
    world.step()
    rng = random.Random(51)
    demo = _mon(rng, 0x54, level=5, nick="PIKA")
    world.seed_party(world.party() + [demo])
    world.step(3)
    assert world.events("capture") == [], "a demonstration battle reports no capture"
    world.bus[r["wIsInBattle"]] = 0
    world.fire("battle_end")
    world.step(2)
    assert len(world.events("no_catch")) == 1, "and still no no_catch"

    # (d) control: a type 2 catch IS the player's -- Safari keeps capture semantics
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.bus[r["wBattleType"]] = 2
    world.fire("wild_begin")
    world.step()
    world.bus[r["wMonDataLocation"]] = 0
    world.fire("add_party_mon")
    world.step()
    caught = _mon(rng, 0xA5, level=3, nick="RATTA")
    world.seed_party(world.party() + [caught])
    world.step(3)
    caps = world.events("capture")
    assert [c["key"] for c in caps] == [codec.key(caught)], caps
    assert caps[0]["area_id"] == "route_1" and caps[0]["gift"] is False
    world.assert_all_conform()


def test_replace_rival_team_nacks_a_late_reply_and_writes_nothing(world):
    """A13: the swap is only safe between InitBattleCommon setting wEnemyMonPartyPos = $FF
    (engine/battle/core.asm:6689-6690) and EnemySendOutFirstMon clearing it (:1292,:1326) before
    LoadEnemyMonData (:1358). Refuse with `error = "late_reply"` once the byte has been staged and
    cleared again, or once RIVAL_INIT_FRAMES have passed since the `battle_begin` point recorded
    the frame without the party ever being staged.
    """
    r = world.ram
    pos = r["wEnemyMonPartyPos"]
    blobs = [_rival_blob(random.Random(41), 0x99)]
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xE1, species=0xB0, level=9)   # RIVAL1 = class 225
    world.bus[pos] = 0x00                                   # the transition has not staged it yet
    world.fire("battle_begin")
    world.step()
    world.bus[pos] = 0xFF                                   # InitBattleCommon reaches :6688
    world.step()

    # (1) the first mon is already out: wEnemyMonPartyPos is no longer $FF
    world.bus[pos] = 0
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") == "late_reply" and ev["species_ids"] == [], ev
    assert world.writes[n:] == [], "a reply after the send-out must not write a byte"

    # (2) a battle whose transition never staged the party at all: the init timeout refuses
    world.bus[pos] = 0x00
    world.fire("battle_begin")
    world.step(RIVAL_INIT_FRAMES + 20)
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") == "late_reply" and ev["species_ids"] == [], ev
    assert world.writes[n:] == [], "a reply past the init timeout must not write a byte"

    # control: a fresh battle_begin re-opens the window and the very same reply lands
    world.fire("battle_begin")
    world.bus[pos] = 0xFF
    world.step()
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") is None and ev["species_ids"] == [0x99], ev
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes.fromhex(blobs[0])[:44]
    world.assert_all_conform()


def test_a_bad_byte_in_the_third_blob_leaves_the_enemy_party_untouched(world):
    """A13/W-4: writes.lua:102-108 validates count, lengths and species for every mon before the
    first write, but the per-BYTE check lives in write_bytes (:60-63) and therefore runs once per
    CALL -- so a bad byte in the third blob is only caught after blobs one and two have already
    landed in wEnemyMons. Validate every byte of every blob (client.lua:315-328 decodes them)
    before the first byte moves.
    """
    r = world.ram
    rng = random.Random(42)
    blobs = [_rival_blob(rng, 0x99), _rival_blob(rng, 0xB0), _rival_blob(rng, 0xB1)]
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xE1, species=0xB0, level=9)
    world.bus[r["wEnemyMonPartyPos"]] = 0xFF
    world.fire("battle_begin")
    world.step()

    # `tonumber(pair, 16)` accepts a sign, so "-1" decodes to a NUMBER outside byte range: the
    # length and species checks all pass and write_bytes only refuses when it reaches mon 3.
    bad = blobs[:2] + [blobs[2][:38] + "-1" + blobs[2][40:]]
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": bad})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev["species_ids"] == [] and isinstance(ev.get("error"), str) and ev["error"], ev
    assert world.writes[n:] == [], "blobs one and two must not land before the third is validated"
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 3 * 44]) == bytes(3 * 44)

    # known-positive control: the same three blobs, unmangled, do land
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev["species_ids"] == [0x99, 0xB0, 0xB1] and ev.get("error") is None, ev
    assert world.writes[n:] != []
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes.fromhex(blobs[0])[:44]
    world.assert_all_conform()


def test_a_rival_reply_that_beats_the_engines_ff_is_held_until_the_flip(world):
    """A13 window, corrected. The `battle_begin` hook sits at InitBattleCommon
    (engine/battle/core.asm:6665, capture_offset 0), but `ld a, $ff / ld [wEnemyMonPartyPos], a`
    is at :6688-6689 -- AFTER `callfar ReadTrainer` (:6679) and AFTER the multi-frame
    `DoBattleTransitionAndInitBattleVariables` (:6680). A reply one frame after the hook therefore
    still reads the PREVIOUS battle's value (0x00 on a fresh boot) and was NACKed `late_reply`,
    which made the window unsatisfiable behind a long transition. HOLD such a reply and apply it
    at the frame the byte reads $FF.
    """
    r = world.ram
    pos = r["wEnemyMonPartyPos"]
    blobs = [_rival_blob(random.Random(41), 0x99)]
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xE1, species=0xB0, level=9)   # RIVAL1 = class 225
    world.bus[pos] = 0x00                                    # the transition is still running
    world.fire("battle_begin")
    world.step()

    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step(10)
    assert world.events("rival_team_replaced") == [], "the reply is held, not answered"
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes(44)

    world.bus[pos] = 0xFF                                    # InitBattleCommon reaches :6688
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") is None and ev["species_ids"] == [0x99], ev
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes.fromhex(blobs[0])[:44]
    world.assert_all_conform()


def test_a_held_rival_reply_whose_ff_never_comes_is_a_late_reply(world):
    """The belt on the same window: a held reply is bounded by RIVAL_INIT_FRAMES measured from
    `battle_begin`, so a transition that never stages the party answers `late_reply` and writes
    nothing.
    """
    r = world.ram
    blobs = [_rival_blob(random.Random(41), 0x99)]
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xE1, species=0xB0, level=9)
    world.bus[r["wEnemyMonPartyPos"]] = 0x00
    world.fire("battle_begin")
    world.step()
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step(RIVAL_INIT_FRAMES + 20)
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") == "late_reply" and ev["species_ids"] == [], ev
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes(44)
    world.assert_all_conform()


def test_a_rival_reply_that_beats_wisinbattle_is_parked_not_refused(world):
    """A13-r2 finding 1 (PRODUCTION). `battle_begin` is hooked at InitBattleCommon offset 0
    (data/games/gen1_rby/engine_signals.json:43-49) and `trainer_battle_start` is sent from that
    hook (client.lua:524), so the server's `replace_rival_team` comes back while pret is still
    inside `DoBattleTransitionAndInitBattleVariables` (engine/battle/core.asm:6680).
    `ld a, $2 / ld [wIsInBattle], a` is at :6691-6692 -- one instruction AFTER the staging at
    :6689-6690 -- so that reply legitimately reads wIsInBattle == 0. The `not_in_battle` guard
    ran BEFORE the parking branch and refused it; it must be parked instead, and a reply with no
    initializing battle behind it must still be refused.
    """
    r = world.ram
    pos = r["wEnemyMonPartyPos"]
    blobs = [_rival_blob(random.Random(41), 0x99)]
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xE1, species=0xB0, level=9)   # RIVAL1 = class 225
    world.bus[r["wIsInBattle"]] = 0                          # core.asm:6691 has NOT run yet
    world.bus[pos] = 0x00                                    # neither has :6689
    world.fire("battle_begin")
    world.step()

    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step(10)
    assert world.events("rival_team_replaced") == [], "the reply is parked, not refused"
    assert world.writes[n:] == [], "nothing may be written before the party is staged"

    world.bus[pos] = 0xFF                                    # InitBattleCommon reaches :6689
    world.bus[r["wIsInBattle"]] = 2                          # ... and :6691
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") is None and ev["species_ids"] == [0x99], ev
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes.fromhex(blobs[0])[:44]

    # the other half of the same guard: no battle in sight, so `not_in_battle` still stands
    world.bus[r["wIsInBattle"]] = 0
    world.bus[r["wCurOpponent"]] = 0
    world.step(RIVAL_INIT_FRAMES + RIVAL_STAGED_FRAMES + 10)
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") == "not_in_battle" and ev["species_ids"] == [], ev
    assert world.writes[n:] == [], "a reply with no battle behind it must not write a byte"
    world.assert_all_conform()


def test_a_rival_reply_outlives_the_longest_battle_transition(world):
    """A13-r2 finding 2 (PRODUCTION). The old single 120-frame window was measured from
    `battle_begin` but pret's transition alone outlasts it: the outward spiral is 120
    `DelayFrame`s (battle_transitions.asm:194-205) and the inward spiral 51 x
    `BattleTransition_TransferDelay3` = 153 (:213-260, :616-622), both behind an 8-frame prefix
    (:4,:9,:49 plus core.asm:6164) -- 128 and 161 frames before `ld [wEnemyMonPartyPos], a`
    (:6689-6690) even runs. A reply parked across that transition was answered `late_reply` and
    the swap could never land; past the send-out it must still be refused.
    """
    r = world.ram
    pos = r["wEnemyMonPartyPos"]
    blobs = [_rival_blob(random.Random(41), 0x99)]
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xE1, species=0xB0, level=9)
    world.bus[pos] = 0x00
    world.fire("battle_begin")
    world.step()

    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step(170)                       # past BOTH spirals (128 and 161), inside the init bound
    assert 161 < 170 < RIVAL_INIT_FRAMES, "the park has to outlast the inward spiral"
    assert world.events("rival_team_replaced") == [], "the reply is still parked at frame 170"
    world.bus[pos] = 0xFF                                    # the transition finally stages it
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") is None and ev["species_ids"] == [0x99], ev
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes.fromhex(blobs[0])[:44]

    # A13-r3: EXACTLY ONCE per battle. The identical reply again (a server retry, or one command
    # delivered twice) is acked and moves no byte -- a second write would race the engine for a
    # party that is already the partner's.
    world.bus[r["wEnemyMons"]] = 0xAA     # scribble: a second write would put the species back
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") == "already_applied" and ev["species_ids"] == [], ev
    assert world.writes[n:] == [], "the swap is applied exactly once per battle"
    assert world.bus[r["wEnemyMons"]] == 0xAA, "the second reply rewrote the enemy party"

    # past the send-out, in a battle that has NOT been swapped: still `late_reply`
    world.bus[pos] = 0x00
    world.fire("battle_begin")
    world.step()
    world.bus[pos] = 0xFF                                    # staged...
    world.step()
    world.bus[pos] = 0                                       # ...then EnemySendOutFirstMon (:1326)
    world.step()
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") == "late_reply" and ev["species_ids"] == [], ev
    assert world.writes[n:] == [], "a reply after the send-out must not write a byte"
    world.assert_all_conform()


def test_the_staged_write_window_expires_at_its_bound(world):
    """A13-r3/r4. `wEnemyMonPartyPos == $FF` is necessary but NOT sufficient. EnemySendOutFirstMon
    does not clear it on entry -- :1326 reads it to pick the slot, :1337-1341 reads that mon's HP,
    :1343-1348 its level and :1349-1357 its species, and only `LoadEnemyMonData` stores the new
    position at :6055 -- and nothing in that span waits for a frame, yet a BizHawk frame boundary
    is a PPU event rather than a code event, so a frame-end callback can land inside it and still
    read $FF. The send-out is not even the first party read: `DrawAllPokeballs`
    (common_text.asm:21-29 -> draw_hud_pokeball_gfx.asm:33-45, :69-95 reads every enemy mon's HP
    and status) comes first, then StartBattle's alive scan (core.asm:139-148).

    RIVAL_STAGED_FRAMES is therefore a maximum OBSERVATION AGE, not a lower bound: it shuts the
    window long before the engine can reach `DrawAllPokeballs`.
    """
    # The bound only does its job if it sits under the engine's own countable floor from the
    # staging to that first consumer. The silhouette slide alone (core.asm:70-84) is 72
    # iterations = at least 71 guaranteed inter-iteration frame crossings, before the 20-frame
    # DelayFrames that precedes DrawAllPokeballs (common_text.asm:22-27). A $FF the client sees
    # may itself be one frame stale, so the last permitted write lands at most
    # RIVAL_STAGED_FRAMES + 1 frames after the engine's store.
    assert RIVAL_STAGED_FRAMES + 1 < 71, (
        "RIVAL_STAGED_FRAMES must shut the window before DrawAllPokeballs can read the party")
    r = world.ram
    pos = r["wEnemyMonPartyPos"]
    blobs = [_rival_blob(random.Random(41), 0x99)]
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xE1, species=0xB0, level=9)

    # the LAST frame of the window is still accepted. The reply queued after step(k) is drained
    # on the NEXT frame_end, i.e. k+1 frames after the staging frame.
    world.bus[pos] = 0x00
    world.fire("battle_begin")
    world.step()
    world.bus[pos] = 0xFF
    world.step()                                             # staged on this frame
    world.step(RIVAL_STAGED_FRAMES - 1)
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") is None and ev["species_ids"] == [0x99], ev
    assert world.writes[n:] != [], "the last frame of the staged window still writes"
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes.fromhex(blobs[0])[:44]

    # one frame later, in an identical fresh battle, it is refused and nothing moves
    world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44] = bytes(44)
    world.bus[pos] = 0x00
    world.fire("battle_begin")
    world.step()
    world.bus[pos] = 0xFF
    world.step()
    world.step(RIVAL_STAGED_FRAMES)
    n = len(world.writes)
    world.reply({"cmd": "replace_rival_team", "trainer_id": 0xE1, "blobs_hex": blobs})
    world.step()
    ev = world.events("rival_team_replaced")[-1]
    assert ev.get("error") == "late_reply" and ev["species_ids"] == [], ev
    assert world.writes[n:] == [], "one frame past the staged window must not write a byte"
    assert bytes(world.bus[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == bytes(44)

    # A13-r3: the constants are lower bounds, so the lane has to record the REAL deltas. The
    # staging line goes out on the frame the byte flips to $FF; the full line when the engine
    # sends out. Both battles above staged two frames after their `battle_begin` signal.
    staged_lines = [ln for ln in world.logs if "RIVAL_WINDOW" in ln]
    assert staged_lines and all("init_frames=2" in ln for ln in staged_lines), staged_lines
    world.bus[pos] = 3                                       # EnemySendOutFirstMon picked slot 3
    world.step()
    full = [ln for ln in world.logs if "staged_frames=" in ln]
    assert len(full) == 1 and "init_frames=2" in full[0], world.logs
    assert f"staged_frames={RIVAL_STAGED_FRAMES + 2}" in full[0], full
    world.assert_all_conform()


def test_a_standalone_party_removal_keys_from_the_hooks_snapshot(world):
    """Both standalone `RemovePokemon(party)` callers -- the NPC in-game trade
    (engine/events/in_game_trades.asm:145) and the cable-club trade (engine/link/cable_club.asm:799)
    -- shift the rest of the party down inside _RemovePokemon, before the signal is drained.
    client.lua:589 read a LIVE party, so the release named the mon that shifted INTO the slot.
    """
    rng = random.Random(7)
    world.seed_party([_mon(rng, 0x99, nick="A"), _mon(rng, 0xB1, nick="B"), _mon(rng, 0xB0, nick="C")])
    world.connect()
    world.step(60)
    before = list(world.party())
    key_a, key_b = codec.key(before[0]), codec.key(before[1])
    world.bus[world.ram["wWhichPokemon"]] = 0
    world.bus[world.ram["wRemoveMonFromBox"]] = 0
    n = len(world.sent)
    world.fire("remove_pokemon")        # the point snapshots A,B,C
    world.seed_party(before[1:])        # _RemovePokemon shifted B,C down by drain time
    world.step()
    ptb = [m["key"] for m in world.sent[n:] if m["event"] == "party_to_box"]
    assert ptb == [key_a], (ptb, "B was", key_b)
    world.assert_all_conform()


def test_a_deposit_whose_two_hooks_drain_far_apart_sends_one_party_to_box(world):
    """`_MoveMon` (engine/pokemon/add_mon.asm:341+) runs two CopyData passes and
    `bills_pc.asm:232-235` calls RemovePokemon straight after it, but the two hooks can still
    drain in different frame_end batches (pc_ops_new, 2026-09-17), so the pairing cannot be a
    frame count: the DEPOSIT's MoveMon has already appended the mon to the BOX, and that is what
    says the party removal behind it is not a standalone one.
    """
    rng = random.Random(7)
    world.seed_party([_mon(rng, 0x99, nick="A"), _mon(rng, 0xB1, nick="B"), _mon(rng, 0xB0, nick="C")])
    world.connect()
    world.step(60)
    before = list(world.party())
    key_a = codec.key(before[0])
    r = world.ram
    world.bus[r["wMoveMonType"]] = 1        # PARTY_TO_BOX
    world.bus[r["wWhichPokemon"]] = 0
    n = len(world.sent)
    world.fire("move_mon")
    _seed_active_box(world, [_boxed(before[0])])   # MoveMon appended it to the box first
    world.step(4)                           # four frames between the hooks: past any age window
    world.bus[r["wRemoveMonFromBox"]] = 0
    world.fire("remove_pokemon")            # the party still holds it at this hook
    world.seed_party(before[1:])
    world.step()
    ptb = [m["key"] for m in world.sent[n:] if m["event"] == "party_to_box"]
    assert ptb == [key_a], (ptb, "B was", codec.key(before[1]))
    world.assert_all_conform()
def test_a_withdraw_is_not_a_release_however_far_apart_its_two_hooks_drain(world):
    """PC-1b (pc_ops_new, 2026-09-17): the withdraw's `move_mon` and `remove_pokemon` drained in
    DIFFERENT frame_end batches -- the receipt has the duo body's own `PARTY_COUNT 1 -> 2 @9088`
    line between `TX box_to_party` and `RELEASE_SEEN`, and both client lines are written inside
    one frame_end, so they cannot be split unless the two signals landed in different frames. The
    2-frame `moved_this_frame` window therefore expired and Bill's WITHDRAW was logged as a
    release (`RESULT: FAIL (a RELEASE_SEEN fired during the WITHDRAW)`). The discriminator may not
    be a frame count: the withdrawn key is in the party snapshot, a released key is in neither.
    """
    rng = random.Random(7)
    world.seed_party([_mon(rng, 0x99, nick="A"), _mon(rng, 0xB1, nick="B")])
    world.connect()
    world.step(60)
    r = world.ram
    boxed = _box_mon(rng, 0x15)
    _seed_active_box(world, [boxed, _box_mon(rng, 0x1D)])
    world.bus[r["wMoveMonType"]] = 0        # BOX_TO_PARTY
    world.bus[r["wWhichPokemon"]] = 0
    nlog = len(world.logs)
    world.fire("move_mon")
    world.seed_party(list(world.party()) + [_withdrawn(rng, boxed)])  # bills_pc.asm:284 ran first
    _seed_active_box(world, [boxed, _box_mon(random.Random(1), 0x1D)])
    world.step(4)                           # the two hooks drain four frames apart, well past any
    world.bus[r["wRemoveMonFromBox"]] = 1   # age window the old rule could have used
    world.fire("remove_pokemon")
    world.step()
    assert [line for line in world.logs[nlog:] if "RELEASE_SEEN" in line] == [],         "a withdraw is a withdraw however many frames separate its two hooks"
    assert [m["key"] for m in world.sent if m["event"] == "box_to_party"] == [codec.key(boxed)]
    assert [m for m in world.sent if m["event"] == "party_to_box"] == []
    world.assert_all_conform()
def test_a_removal_inside_an_npc_trade_keeps_the_pending_key_change(world):
    """`in_game_trades.asm:145` calls RemovePokemon between the `npc_trade` signal and the
    AddPartyMon that completes the trade. client.lua:593 overwrote the live `npc_trade`
    pending_change with a `rescan`, so the trade's key_change was never sent.
    """
    world.connect()
    world.step(60)
    old = codec.key(world.party()[1])
    world.bus[world.ram["wWhichPokemon"]] = 1
    world.fire("npc_trade")
    world.bus[world.ram["wRemoveMonFromBox"]] = 0
    world.fire("remove_pokemon")
    world.step()
    rng = random.Random(4)
    party = world.party()
    party[1] = _mon(rng, 0x2D, level=10, nick="JYNX")
    world.seed_party(party)
    world.fire("npc_trade_done")
    world.step()
    kc = world.events("key_change")
    assert len(kc) == 1 and kc[0]["old_key"] == old and kc[0]["reason"] == "npc_trade", kc
    assert kc[0]["new_key"] == codec.key(world.party()[1])
    world.assert_all_conform()


def test_a_server_box_round_trip_never_suppresses_the_players_own_deposit(world):
    """PC-1 (whiteout_new, 2026-09-17): the quarantine round trip -- `RX box_mon` to quarantine the
    capture, then `RX party_mon` to give it back -- marked the key as "written by us", and that
    mark (latched, and equally an aged one) suppressed the `party_to_box` of the player's OWN
    Bill's PC deposit of that key: the receipt shows `PC op 1 deposit(2) done frame=10834 party=1
    box_count=1` with no `TX party_to_box` anywhere. No server-ordered write can produce a storage
    signal to echo -- boxes.lua moves the bytes itself (io.write_bytes, boxes.lua:345-346,
    :455-456) and never calls _MoveMon -- so there is nothing to suppress and no mark at all.
    Deposit on the very next frame after the withdraw: any per-key suppression fails this.
    """
    world.connect()
    world.step(60)                                    # writes ENABLED
    before = list(world.party())
    key, stats = codec.key(before[0]), {"level": before[0]["level"], "maxHP": before[0]["max_hp"]}
    world.overworld_safe()
    world.reply({"cmd": "box_mon", "key": key})
    world.step(2)
    assert world.events("box_mon_failed") == [], world.events("box_mon_failed")
    assert key not in [codec.key(m) for m in world.party()], "the deposit must empty the party slot"
    assert key in _active_box_keys(world), "... and the mon must be IN the open box"

    world.reply({"cmd": "party_mon", "key": key, "stats": stats})
    world.overworld_safe()
    world.step(2)
    assert world.events("sync_retrieve_failed") == [], world.events("sync_retrieve_failed")
    assert [e["key"] for e in world.events("sync_retrieve_done")] == [key]
    party = world.party()
    slots = [i for i, m in enumerate(party) if codec.key(m) == key]
    assert slots and key not in _active_box_keys(world), "the withdraw must move it back"

    r, n = world.ram, len(world.sent)
    world.bus[r["wMoveMonType"]] = 1                  # PARTY_TO_BOX (menu_constants.asm:60-63)
    world.bus[r["wWhichPokemon"]] = slots[0]
    world.fire("move_mon")
    world.bus[r["wRemoveMonFromBox"]] = 0
    world.fire("remove_pokemon")                      # bills_pc.asm:230-235
    world.seed_party([m for m in party if codec.key(m) != key])
    world.step()
    ptb = [m["key"] for m in world.sent[n:] if m["event"] == "party_to_box"]
    assert ptb == [key], f"the player's deposit must send exactly one party_to_box for {key}; got {ptb}"
    world.assert_all_conform()


def test_a_trade_removal_is_suppressed_by_the_apply_state_across_the_whole_movie(world):
    """MODEL test: the lease is driven the way the cartridge drives it, because the one removal a
    client write really does cause is the trade's. `SlinkTradeService` picks the request up and
    restores the borrowed tile union before any native code runs (trade_service.asm:90-95, the
    pickup hook at trade_overlay.lua:190-196), then the apply removes the OUTGOING mon and only
    afterwards appends the received one (native_trade.asm:156-168; vanilla cable_club.asm:799-817).
    DONE is published a hundred-odd frames later (native_trade.asm:179-180,:204 ->
    trade_service.asm:106-113). Nothing keyed or aged spans that gap; the APPLY state does.
    Afterwards a genuine PC move of the RECEIVED mon must still report -- no mark is left on it.
    """
    w = _patched_world()
    rng = random.Random(21)
    outgoing = w.party()[0]
    incoming = _mon(rng, 0xB1, level=7, nick="PIDGEY")
    blob = codec.encode_party_mon(incoming) + codec.encode_name("BLUE") + codec.encode_name("PIDGEY")
    base = w.ram["wSerialPartyMonsPatchList"]
    w.reply({"cmd": "apply_trade", "slot": 0, "blob_hex": blob.hex().upper(),
             "old_key": codec.key(outgoing), "token": "t21", "partner_name": "BLUE"})
    w.step()
    armed = bytes(w.bus[base:base + 16])
    assert armed[5] == 5, "apply armed"

    _fire_trade_service(w)                       # the cartridge takes the request
    assert str(w.client.trade.phase) == "picked_up", "the pickup hook must run before the restore"
    backup = w.ram["wEnemyMons"] + w.d["battle_struct_size"]
    w.bus[base:base + 16] = bytes(w.bus[backup:backup + 16])   # service.asm:90-95 gives it back
    n = len(w.sent)

    w.bus[w.ram["wRemoveMonFromBox"]] = 0        # native_trade.asm:156-158: OURS goes first,
    w.bus[w.ram["wWhichPokemon"]] = 0            # with the party still holding it
    w.fire("remove_pokemon")
    w.seed_party([incoming])                     # :159-168 appends theirs afterwards
    w.step()
    w.step(120)                                  # DelayFrames 100, the trade movie and the save
    assert [m["event"] for m in w.sent[n:] if m["event"] in ("party_to_box", "box_to_party")] == [],         "the APPLY state owns the trade's removal"
    assert w.events("trade_done") == [], "DONE is published only at the end of the movie"

    done = bytearray(armed)                      # the retained stack copy goes back over the union
    done[5], done[8], done[7] = 7, 0, done[6]    # cmd DONE, result 0, ack generation LAST
    w.bus[base:base + 16] = bytes(done)
    w.step()
    assert len(w.events("trade_done")) == 1, w.events("trade_done")
    assert w.events("trade_done")[-1]["new_key"] == codec.key(incoming)
    assert [m["event"] for m in w.sent[n:] if m["event"] in ("party_to_box", "box_to_party")] == [],         "only trade_done comes out of an apply"

    # the received mon is now an ordinary party mon: depositing it reports like any other
    other = _mon(rng, 0x99, nick="BULBA")
    w.seed_party([incoming, other])
    w.step()
    r, n = w.ram, len(w.sent)
    w.bus[r["wMoveMonType"]] = 1
    w.bus[r["wWhichPokemon"]] = 0
    w.fire("move_mon")
    w.bus[r["wRemoveMonFromBox"]] = 0
    w.fire("remove_pokemon")
    w.seed_party([other])
    w.step()
    ptb = [m["key"] for m in w.sent[n:] if m["event"] == "party_to_box"]
    assert ptb == [codec.key(incoming)], f"one party_to_box for the traded-in mon; got {ptb}"
    w.assert_all_conform()


def _applying(w, token="t30"):
    """An armed APPLY the cartridge has picked up; returns the armed frame."""
    rng = random.Random(30)
    incoming = _mon(rng, 0xB1, level=7, nick="PIDGEY")
    blob = codec.encode_party_mon(incoming) + codec.encode_name("BLUE") + codec.encode_name("PIDGEY")
    w.reply({"cmd": "apply_trade", "slot": 0, "blob_hex": blob.hex().upper(),
             "old_key": codec.key(w.party()[0]), "token": token, "partner_name": "BLUE"})
    w.step()
    armed = _overlay(w)
    assert armed[5] == 5, "apply armed"
    _fire_trade_service(w)
    return armed, incoming


def _uncertain_done(w):
    return [(d["token"], d.get("uncertain"), "new_key" in d) for d in w.events("trade_done")]


def test_a_native_result_2_is_declared_uncertain_once_and_never_released():
    """native_trade.asm .unreachableAppendFailure (D=2): the append may or may not have happened.
    The side declares trade_done{token, uncertain} (no key claim) once; the lease is kept."""
    w = _patched_world()
    armed, _ = _applying(w)
    base = w.ram["wSerialPartyMonsPatchList"]
    done = bytearray(armed)
    done[5], done[8], done[7] = 7, 2, done[6]
    w.bus[base:base + 16] = bytes(done)
    w.step(5)
    assert _uncertain_done(w) == [("t30", True, False)]
    assert [d.get("after_reset") for d in w.events("trade_done")] == [True], \
        "MAJOR-5: the RAM party is no evidence; only the reloaded save (post-reset hello) is"
    assert _overlay(w)[5] == 7, "result 2 is never released"
    assert any("UNCERTAIN" in str(h) for h in w.hud)
    w.assert_all_conform()


def _reset_and_reload(w):
    """home/init.asm zero-fills WRAM (wPlayerID 0) until CONTINUE reloads the same save."""
    saved = bytes(w.bus)
    r = w.ram
    for a in range(r["wPartyCount"], r["wPartyCount"] + 8):
        w.bus[a] = 0
    w.bus[r["wPlayerID"]] = w.bus[r["wPlayerID"] + 1] = 0
    w.step(90)
    assert w.events("trade_done") == [], "nothing is declared before the post-reset hello"
    w.bus[:] = saved
    w.overworld_safe()
    w.step(60)
    assert len(w.events("hello")) == 2


def test_a_reset_after_the_commit_boundary_is_declared_uncertain_after_the_new_hello():
    """Mirror of Gen 2's SlinkTradeCommit latch (lua/gen2/client.lua trade_forget, ed7f87c6): the
    apply's first mutation is its RemovePokemon (native_trade.asm:156-158, after every .refused
    check). A reset after it may have saved the trade (SavePartyAndDexData) before DONE."""
    w = _patched_world()
    _applying(w)
    w.bus[w.ram["wRemoveMonFromBox"]] = 0
    w.bus[w.ram["wWhichPokemon"]] = 0
    w.fire("remove_pokemon")
    w.step()
    _reset_and_reload(w)
    assert _uncertain_done(w) == [("t30", True, False)]
    names = [m["event"] for m in w.sent]
    assert names.index("trade_done") > len(names) - 1 - names[::-1].index("hello"), "after the new hello"
    w.step(5)
    assert len(w.events("trade_done")) == 1
    assert w.client.trade_state is None
    assert any("UNCERTAIN" in str(h) for h in w.hud)
    w.assert_all_conform()


def test_a_reset_before_the_commit_boundary_reports_a_certain_nothing_changed():
    """Before the RemovePokemon nothing was mutated or saved, so the reset lost nothing: review m2 --
    say so after the new hello (a certain none) instead of leaving it to the 17-minute watchdog."""
    w = _patched_world()
    old_key = codec.key(w.party()[0])
    _applying(w)
    _reset_and_reload(w)
    w.step(5)
    assert [(d["token"], d["new_key"], d.get("uncertain")) for d in w.events("trade_done")] == [
        ("t30", old_key, None)]
    names = [m["event"] for m in w.sent]
    assert names.index("trade_done") > len(names) - 1 - names[::-1].index("hello"), "after the new hello"
    assert w.client.trade_state is None
    assert not any("UNCERTAIN" in str(h) for h in w.hud)
    w.assert_all_conform()


def test_an_undecodable_snapshot_classifies_nothing_and_says_which_half_was_missing(world):
    """A removal is classified by what the snapshot HOLDS, so an absence only means something when
    both collections decoded. A party that does not decode (client.lua:473-476 returns nil for a
    count that is not a byte or is over capacity -- and returns, rather than throwing, because the
    pcall in frame_end would otherwise swallow the whole signal) would make Bill's WITHDRAW look
    like a release. The client says so once and emits nothing; the signal is consumed, never
    re-classified from a later snapshot.
    """
    r = world.ram
    boxed = _box_mon(random.Random(41), 0xB0, level=6)
    _seed_active_box(world, [boxed])
    world.connect()
    world.step(60)
    nlog, n = len(world.logs), len(world.sent)
    world.bus[r["wPartyCount"]] = 0xFF           # party snapshot: undecodable, box still valid
    world.bus[r["wRemoveMonFromBox"]] = 1
    world.bus[r["wWhichPokemon"]] = 0
    world.fire("remove_pokemon")
    world.step()
    lines = world.logs[nlog:]
    assert [ln for ln in lines if "RELEASE_SEEN" in ln] == [], "an undecoded party is not evidence"
    assert [f"[SLink-gen1] STORAGE_CLASSIFICATION_UNAVAILABLE key={codec.key(boxed)} why=party-undecoded"] ==         [ln for ln in lines if "STORAGE_CLASSIFICATION_UNAVAILABLE" in ln], lines
    assert [m for m in world.sent[n:] if m["event"] in ("party_to_box", "box_to_party")] == []
    world.step(3)                                # and it is not retried from a later snapshot
    assert [ln for ln in world.logs[nlog:] if "STORAGE_CLASSIFICATION_UNAVAILABLE" in ln] ==         [ln for ln in lines if "STORAGE_CLASSIFICATION_UNAVAILABLE" in ln]
    world.assert_all_conform()


@pytest.mark.parametrize("title", ["red", "blue", "yellow"])
@pytest.mark.parametrize("boxed", [False, True])
@pytest.mark.parametrize("end_same_frame", [False, True])
def test_acquisition_survives_long_naming(title, boxed, end_same_frame):
    """AskName precedes the record write in both native acquisition routines."""
    w = World(title)
    rng = random.Random(81)
    mons = [_mon(rng, 0x99) for _ in range(6 if boxed else 1)]
    w.seed_party(mons)
    w.give_poke_ball()
    w.set_map(12)
    w.connect()
    w.in_battle(0xA5, 0xA5, 5)
    w.fire("battle_begin")
    w.step()
    w.fire("capture_box" if boxed else "add_party_mon")
    w.step(2100)  # 35 seconds of user-controlled naming, after the entry signal
    assert w.events("capture") == []
    assert w.events("no_catch") == []
    caught = _mon(rng, 0xA5, nick="NAMED")
    if boxed:
        r = w.ram
        w.bus[r["wBoxCount"]] = 1
        w.bus[r["wBoxSpecies"]:r["wBoxSpecies"] + 2] = bytes([0xA5, 0xFF])
        blob = bytearray(codec.encode_party_mon(caught)[:33])
        blob[3] = caught["level"]
        w.bus[r["wBoxMons"]:r["wBoxMons"] + 33] = blob
        w.bus[r["wBoxMonOT"]:r["wBoxMonOT"] + 11] = codec.encode_name("RED")
        w.bus[r["wBoxMonNicks"]:r["wBoxMonNicks"] + 11] = codec.encode_name("NAMED")
    else:
        w.seed_party(mons + [caught])
    if not end_same_frame:
        w.step(3)
    w.bus[w.ram["wIsInBattle"]] = 0
    w.fire("battle_end")
    w.step(3)
    captures = w.events("capture")
    assert len(captures) == 1
    assert captures[0]["key"] == codec.key(caught)
    assert captures[0]["in_box"] == boxed
    assert captures[0]["area_id"] == "route_1"
    assert w.events("no_catch") == []
    w.assert_all_conform()


@pytest.mark.parametrize("title", ["red", "blue", "yellow"])
@pytest.mark.parametrize("result", [1, 2])
def test_uncaught_battle_still_reports_no_catch(title, result):
    w = World(title)
    w.seed_party([_mon(random.Random(82), 0x99)])
    w.give_poke_ball()
    w.set_map(12)
    w.connect()
    w.in_battle(0xA5, 0xA5, 5)
    w.fire("battle_begin")
    w.step(2100)
    w.bus[w.ram["wBattleResult"]] = result
    w.bus[w.ram["wIsInBattle"]] = 0
    w.fire("battle_end")
    w.step(3)
    assert len(w.events("no_catch")) == 1
    assert w.events("capture") == []


# Native PCs from pinned pret InGameTrade_DoTrade: RB :99/:145/:151,
# Yellow :90/:133/:139. Drive CPU positions rather than named hooks so
# this test detects a hook accidentally moved back before DisplayPartyMenu.
_NPC_PCS = {"red": (0x5C07, 0x5C74, 0x5C8A),
            "blue": (0x5C07, 0x5C74, 0x5C8A),
            "yellow": (0x5CA9, 0x5D0D, 0x5D1E)}


def _npc_cpu_point(w, stage):
    pc = _NPC_PCS[w.title][stage]
    w.bus[w.ram["hLoadedROMBank"]] = 0x1C
    w.regs["PC"] = pc
    for fn, address in w.hooks.values():
        if address == pc:
            fn()


@pytest.mark.parametrize("title", ["red", "blue", "yellow"])
@pytest.mark.parametrize("slot", [0, 1, 2])
@pytest.mark.parametrize("selection_frames", [2, 420])
def test_npc_trade_native_compaction_after_long_selection(title, slot, selection_frames):
    w = World(title)
    rng = random.Random(83)
    mons = [_mon(rng, s) for s in (0x99, 0xB1, 0xA5)]
    w.seed_party(mons)
    w.connect()
    # Stale wWhichPokemon at menu entry must not select the outgoing identity.
    w.bus[w.ram["wWhichPokemon"]] = (slot + 1) % 3
    _npc_cpu_point(w, 0)
    w.step(selection_frames)
    assert w.events("key_change") == []
    w.bus[w.ram["wWhichPokemon"]] = slot
    _npc_cpu_point(w, 1)  # actual selected slot, immediately before RemovePokemon
    w.bus[w.ram["wRemoveMonFromBox"]] = 0
    w.fire("remove_pokemon")
    survivors = mons[:slot] + mons[slot + 1:]
    w.seed_party(survivors)
    w.step(2)  # a frame can split remove and append
    assert w.events("key_change") == []
    w.bus[w.ram["wMonDataLocation"]] = 0x80
    w.fire("add_party_mon")
    incoming = _mon(rng, 0x2D, nick="LOLA")
    w.seed_party(survivors + [incoming])
    w.step(2)  # CopyDataToReceivedMon has not yet finalized the OT
    assert w.events("key_change") == []
    incoming["ot_id"] = 0x4567
    w.seed_party(survivors + [incoming])
    _npc_cpu_point(w, 2)  # after copy + optional native trade evolution
    w.step(3)
    changes = w.events("key_change")
    assert len(changes) == 1
    assert changes[0]["old_key"] == codec.key(mons[slot])
    assert changes[0]["new_key"] == codec.key(incoming)
    assert changes[0]["new_species"] == 0x2D
    assert changes[0]["new_nickname"] == "LOLA"
    assert w.events("capture") == []
    assert w.events("party_to_box") == []
    w.assert_all_conform()


@pytest.mark.parametrize("title", ["red", "blue", "yellow"])
@pytest.mark.parametrize("selection_frames", [2, 420])
def test_npc_trade_declined_menu_emits_nothing(title, selection_frames):
    w = World(title)
    rng = random.Random(84)
    mons = [_mon(rng, s) for s in (0x99, 0xB1, 0xA5)]
    w.seed_party(mons)
    w.connect()
    _npc_cpu_point(w, 0)
    w.step(selection_frames)
    # B returns via tradeFailed; neither mutation PC is executed. A later reorder
    # is not a completed trade and must not migrate any identity.
    w.seed_party(list(reversed(mons)))
    w.step(3)
    assert w.events("key_change") == []
    assert w.events("capture") == []
    assert w.events("party_to_box") == []


# ── evolution: the species-publish site (FIX-EVO) ────────────────────────────────────────
# Level-up evolutions enter Evolution_PartyMonLoop through `predef EvolutionAfterBattle`
# (end_of_battle.asm:42-45 -> data/predef_pointers.asm:55 -> 0E:6D1C) and never pass
# TryEvolvingMon (0E:6D0E), which only the stone/Rare Candy/trade callers use. The old entry
# hook therefore never fired for the commonest evolution of a run, and when it did fire the
# 300-frame budget sat BEFORE the animation. The hook is now the instant the new species is
# published (`ld a,[wLoadedMonSpecies] / ld [hl],a`, evos_moves.asm:229-233 R/B, :231-235 Y):
# the record is already rewritten, so there is nothing to wait for and nothing to cancel.

_EVOLVE_SITE_OFFSET = {"red": 423, "blue": 423, "yellow": 430}   # Evolution_PartyMonLoop + n


def _evolving_world(title, rng_seed=21):
    w = World(title)
    rng = random.Random(rng_seed)
    w.seed_party([_mon(rng, 0x99, level=16, nick="BULBA"),       # Bulbasaur
                  _mon(rng, 0x66, level=20, nick="EEVEE"),       # Eevee
                  _mon(rng, 0xB0, level=16, nick="CHAR")])       # Charmander
    w.set_map(0x0C)
    w.give_poke_ball()
    w.connect()
    return w


def _publish_species(w, slot, species, nick):
    """What the engine has done by the time the site runs: species byte and struct rewritten."""
    party = w.party()
    party[slot]["species"] = species
    for _i, m in enumerate(party):
        m["nick"] = m["nickname"]
    party[slot]["nick"] = nick
    w.seed_party(party)
    w.bus[w.ram["wWhichPokemon"]] = slot


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_level_up_evolution_key_change_from_the_species_publish_site(title):
    w = _evolving_world(title)
    old = codec.key(w.party()[0])
    prof = PROFILE[title]["rom"]
    _, pc = w.hooks["SLink-gen1-evolve"]
    assert pc != prof["TryEvolvingMon"]["addr"], "a level-up evolution never enters TryEvolvingMon"
    assert pc == prof["Evolution_PartyMonLoop"]["addr"] + _EVOLVE_SITE_OFFSET[title]
    site = SITES[title]["sites"]["evolve"]
    assert w.rom[site["rom_offset"]:site["rom_offset"] + 4] == bytes.fromhex("6B621801")
    assert w.rom[site["rom_offset"] - 2:site["rom_offset"]] == bytes.fromhex("77E5"), \
        "`ld [hl],a / push hl` -- the species byte is written immediately before the site"

    _publish_species(w, 0, 0x09, "BULBA")            # Ivysaur, in place, after a battle
    w.fire("evolve")
    w.step()
    kc = w.events("key_change")
    assert len(kc) == 1, kc
    assert kc[0]["old_key"] == old and kc[0]["new_key"] == codec.key(w.party()[0])
    assert kc[0]["reason"] == "evolution" and kc[0]["new_species"] == 0x09
    assert kc[0]["new_nickname"] == "BULBA"
    assert w.events("capture") == [], "an evolved mon is not a fresh acquisition"
    w.step(5)
    assert len(w.events("key_change")) == 1 and w.client.pending_change is None
    w.assert_all_conform()


def test_stone_evolution_of_a_non_lead_slot_migrates_that_slot_only(world):
    """ItemUseEvoStone -> TryEvolvingMon reaches the same loop; the slot is wWhichPokemon."""
    w = _evolving_world("red")
    keys = [codec.key(m) for m in w.party()]
    _publish_species(w, 1, 0x69, "EEVEE")            # Vaporeon (Water Stone)
    w.fire("evolve")
    w.step()
    kc = w.events("key_change")
    assert len(kc) == 1
    assert kc[0]["old_key"] == keys[1] and kc[0]["new_key"] == codec.key(w.party()[1])
    assert kc[0]["new_species"] == 0x69 and kc[0]["reason"] == "evolution"
    assert [codec.key(m) for m in w.party()][0::2] == keys[0::2], "the other slots are untouched"
    w.assert_all_conform()


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_cancelled_evolution_leaves_before_the_site_and_reports_nothing(title):
    """B during the animation: `EvolveMon` returns carry and `jp c, CancelledEvolution`
    (evos_moves.asm:135) leaves the loop iteration BEFORE the species publish, so the hook
    cannot fire and no pending change exists to expire. Pinned in the ROM: the jp sits between
    the loop start and the site, and its target is CancelledEvolution from the .sym file."""
    rom = _rom(title)
    prof = PROFILE[title]["rom"]
    sym = (REPO / "data" / "pret" / {"red": "pokered.sym", "blue": "pokeblue.sym",
                                      "yellow": "pokeyellow.sym"}[title]).read_text(encoding="utf-8")
    m = re.search(r"^0e:([0-9a-f]{4}) CancelledEvolution$", sym, re.M)
    assert m, "CancelledEvolution missing from the .sym"
    target = int(m.group(1), 16)
    loop = prof["Evolution_PartyMonLoop"]["flat"]
    site = SITES[title]["sites"]["evolve"]["rom_offset"]
    jp_c = bytes([0xDA, target & 0xFF, target >> 8])
    at = rom.find(jp_c, loop, site)
    assert loop < at < site, "the cancel branch must leave the loop before the species publish"

    w = _evolving_world(title)
    w.step(400)                                      # nothing fired, nothing pends, nothing expires
    assert w.events("key_change") == [] and w.client.pending_change is None
    w.assert_all_conform()


def test_two_party_mons_evolving_in_one_loop_report_two_key_changes(world):
    """Evolution_PartyMonLoop walks the whole party (evos_moves.asm:26-43): two eligible mons
    publish twice, possibly inside one frame. Each migration resolves its own old key."""
    w = _evolving_world("red")
    keys = [codec.key(m) for m in w.party()]
    _publish_species(w, 0, 0x09, "BULBA")            # Ivysaur
    w.fire("evolve")
    _publish_species(w, 2, 0xB2, "CHAR")             # Charmeleon, same frame
    w.fire("evolve")
    w.step()
    kc = w.events("key_change")
    assert [(c["old_key"], c["new_species"]) for c in kc] == [(keys[0], 0x09), (keys[2], 0xB2)]
    assert [c["new_key"] for c in kc] == [codec.key(w.party()[0]), codec.key(w.party()[2])]
    w.step(5)
    assert len(w.events("key_change")) == 2 and w.client.pending_change is None
    w.assert_all_conform()


# ── whiteout rebuild with a full party (FIX-WO) ──────────────────────────────────────────

def _six_dead_and_one_boxed(rng_seed=31):
    """After a whiteout: HealParty ran before the blackout site, so the six dead linked mons
    read as a full, healthy party; one alive linked half waits in the open box."""
    w = World("red")
    rng = random.Random(rng_seed)
    dead = [_mon(rng, s, level=12, nick=f"DEAD{i}")
            for i, s in enumerate((0x99, 0xB1, 0xA5, 0xB0, 0x54, 0x66))]
    boxed = _box_mon(rng, 0x1D, level=9)             # Pinsir, base stats inline on R/B/Y
    boxed["exp"] = 1000
    w.seed_party(dead)
    _seed_active_box(w, [boxed])
    w.set_map(0x0C)
    w.give_poke_ball()
    w.connect()
    w.step(60)                                       # writes ENABLED
    return w, [codec.key(m) for m in dead], codec.key(boxed)


def test_whiteout_rebuild_with_a_full_party_lets_the_memorializes_free_a_slot_first():
    """state.py:2020-2049 queues the rebuild's `party_mon` BEFORE the memorializes, and
    `sync_retrieve_failed` is final there (:341-362). With a full party the withdraw met
    boxes.lua:433 "party full" first, failed for good, and the last memorialize then re-queued
    itself forever ("last party mon", client.lua). The withdraw now waits at the tail behind
    the memorializes that free the slots, bounded, so the whole queue drains."""
    w, dead, boxed = _six_dead_and_one_boxed()
    w.overworld_safe()
    w.reply({"cmd": "party_mon", "key": boxed, "stats": {"level": 9, "maxHP": 30}},
            *[{"cmd": "memorialize", "key": k} for k in dead])
    for _ in range(20):
        w.overworld_safe()
        w.step()
    assert [e["key"] for e in w.events("sync_retrieve_done")] == [boxed]
    assert w.events("sync_retrieve_failed") == [], w.events("sync_retrieve_failed")
    assert sorted(e["key"] for e in w.events("memorialize_done")) == sorted(dead)
    assert w.events("memorialize_failed") == []
    assert len(w.client.deferred) == 0, "nothing may stay queued forever"
    assert [codec.key(m) for m in w.party()] == [boxed]
    assert boxed not in _active_box_keys(w)
    w.assert_all_conform()


def test_party_mon_into_a_genuinely_full_party_still_fails_after_a_bounded_requeue():
    """The bound: one turn per command queued behind it at the first refusal (here none), then
    the honest answer. Never a silent loop."""
    w, _, boxed = _six_dead_and_one_boxed(rng_seed=32)
    w.overworld_safe()
    w.reply({"cmd": "party_mon", "key": boxed, "stats": {"level": 9, "maxHP": 30}})
    for _ in range(4):
        w.overworld_safe()
        w.step()
    failed = w.events("sync_retrieve_failed")
    assert [(e["key"], e["reason"]) for e in failed] == [(boxed, "party full")]
    assert w.events("sync_retrieve_done") == [] and len(w.client.deferred) == 0
    assert len(w.party()) == 6 and boxed in _active_box_keys(w)
    w.assert_all_conform()


# ── FIX-EVO-2 (Codex cross-review of 7616d9f) ────────────────────────────────────────────

@pytest.mark.parametrize("title", sorted(DUMPS))
def test_stale_compacted_record_is_not_a_capture_once_its_key_has_been_retired(title):
    """Six mons; deposit slot 0 -> _RemovePokemon compacts (remove_mon.asm:59-107) and leaves
    the OLD physical slot-5 record intact; the mon now in slot 4 evolves and its old key is
    retired; then the SAME species is caught into the free sixth slot: AddPartyMon publishes
    count and species (add_mon.asm:11-27) BEFORE AskName, so the stale record passes the
    list/struct species check with an unknown key, level 20 and full HP. It must never be
    reported; the capture is the record that replaces it."""
    w = World(title)
    rng = random.Random(51)
    species = (0x99, 0xB1, 0xA5, 0xB0, 0x54, 0x7B)              # ... slot 5 = Caterpie L20
    mons = [_mon(rng, s, level=20, nick=f"M{i}") for i, s in enumerate(species)]
    w.seed_party(mons)
    w.set_map(0x0C)
    w.give_poke_ball()
    w.connect()
    w.step(60)
    r = w.ram
    stale = codec.key(mons[5])
    # Bill's PC deposit of slot 0: MoveMon, then the compaction. seed_party writes five records
    # and leaves physical slot 5 exactly as it was -- which is what the engine's shift does.
    w.bus[r["wMoveMonType"]], w.bus[r["wWhichPokemon"]] = 1, 0
    w.fire("move_mon")
    _seed_active_box(w, [_boxed(mons[0])])
    w.seed_party(mons[1:])
    w.step(3)
    assert [codec.key(m) for m in w.party()] == [codec.key(m) for m in mons[1:]]
    assert bytes(w.bus[r["wPartyMons"] + 5 * 44:r["wPartyMons"] + 6 * 44]) == codec.encode_party_mon(mons[5]), \
        "the model must keep the stale record the compaction leaves behind"
    # the mon now in slot 4 (the old slot 5) evolves: its key is retired
    _publish_species(w, 4, 0x7C, "M5")                          # Metapod
    w.fire("evolve")
    w.step(2)
    kc = w.events("key_change")
    assert len(kc) == 1 and kc[0]["old_key"] == stale and kc[0]["new_key"] == codec.key(w.party()[4])
    n = len(w.events("capture"))
    # a wild Caterpie is caught: AddPartyMon entry, then what it publishes before AskName
    w.in_battle(0x7B, 0x7B, 4)
    w.fire("wild_begin")
    w.step()
    w.bus[r["wMonDataLocation"]], w.bus[r["wCurPartySpecies"]] = 0, 0x7B
    w.fire("add_party_mon")                                     # wPartyCount reads 5 here
    w.bus[r["wPartyCount"]] = 6
    w.bus[r["wPartySpecies"] + 5], w.bus[r["wPartySpecies"] + 6] = 0x7B, 0xFF
    w.bus[r["wPartyMonOT"] + 55:r["wPartyMonOT"] + 66] = codec.encode_name("RED")
    w.step(600)                                                 # the player is on the naming screen
    assert w.events("capture")[n:] == [], "the stale level-20 record was reported as the catch"
    assert w.events("no_catch") == []
    caught = _mon(rng, 0x7B, level=4, nick="CATER")
    base = r["wPartyMons"] + 5 * 44
    w.bus[base:base + 44] = codec.encode_party_mon(caught)
    w.bus[r["wPartyMonNicks"] + 55:r["wPartyMonNicks"] + 66] = codec.encode_name("CATER")
    w.step(3)
    caps = w.events("capture")[n:]
    assert len(caps) == 1 and caps[0]["key"] == codec.key(caught) and caps[0]["level"] == 4
    assert caps[0]["nickname"] == "CATER" and caps[0]["area_id"] == "route_1"
    w.bus[r["wIsInBattle"]] = 0
    w.fire("battle_end")
    w.step(3)
    assert w.events("no_catch") == [] and len(w.events("capture")) == n + 1
    w.assert_all_conform()


def test_evolution_old_key_ignores_a_boxed_mon_with_the_same_prefix(world):
    """known_keys holds the PC too. A boxed Charmander with the party Bulbasaur's DVs and OT
    (the two starters of a duo run) must not make the old key ambiguous: the candidate pool is
    the party as last read before the site fired."""
    w = world
    bulba = w.party()[0]
    boxed = _box_mon(random.Random(61), 0xB0, level=6)
    boxed["dvs"], boxed["ot_id"] = dict(bulba["dvs"]), bulba["ot_id"]
    assert codec.key(boxed)[:10] == codec.key(bulba)[:10]
    _seed_active_box(w, [boxed])
    w.connect()                                                 # hello rescans the box: both known
    w.step(3)
    assert codec.key(boxed) in [str(k) for k in w.client.known_keys]
    old = codec.key(bulba)
    _publish_species(w, 0, 0x09, "BULBA")                       # Ivysaur
    w.fire("evolve")
    w.step()
    kc = w.events("key_change")
    assert len(kc) == 1, [ln for ln in w.logs if "evolution" in ln]
    assert kc[0]["old_key"] == old and kc[0]["new_key"] == codec.key(w.party()[0]) and kc[0]["new_species"] == 0x09
    assert [ln for ln in w.logs if "ambiguous old key" in ln] == []
    w.assert_all_conform()


def test_evolution_old_key_is_the_vanished_one_of_two_same_prefix_party_mons():
    w = World("red")
    rng = random.Random(62)
    bulba, charm = _mon(rng, 0x99, level=16, nick="BULBA"), _mon(rng, 0xB0, level=16, nick="CHAR")
    charm["dvs"], charm["ot_id"] = dict(bulba["dvs"]), bulba["ot_id"]
    w.seed_party([bulba, charm])
    w.set_map(0x0C)
    w.give_poke_ball()
    w.connect()
    w.step(3)
    keys = [codec.key(m) for m in w.party()]
    assert keys[0][:10] == keys[1][:10]
    _publish_species(w, 0, 0x09, "BULBA")
    w.fire("evolve")
    w.step()
    kc = w.events("key_change")
    assert len(kc) == 1 and kc[0]["old_key"] == keys[0] and kc[0]["new_key"] == codec.key(w.party()[0])
    assert keys[1] in [str(k) for k in w.client.known_keys], "the sibling that did not evolve stays known"
    w.assert_all_conform()


def test_evolution_with_no_prior_party_member_is_refused_and_logged(world):
    """A genuine zero-candidate case: the record in the slot was never a party member on any
    read before the site fired. No guess, one log line, nothing on the wire."""
    w = world
    w.connect()
    w.step(3)
    stranger = _mon(random.Random(63), 0x09, level=16, nick="WHO")
    party = w.party()
    for m in party:
        m["nick"] = m["nickname"]
    party[1] = stranger
    w.seed_party(party)                                         # no engine signal for this change
    w.bus[w.ram["wWhichPokemon"]] = 1
    w.fire("evolve")
    w.step()
    assert w.events("key_change") == []
    assert [ln for ln in w.logs if "old key unknown" in ln], w.logs[-5:]
    w.assert_all_conform()


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_identical_reacquisition_into_the_stale_slot_is_reported_at_battle_end(title):
    """FIX-EVO-3 (Codex cx-00b23e13 on da2cf11): the freshness witness must not be a
    permanent veto. Same sequence as the stale-slot pin, but the re-caught mon's 44 bytes are
    IDENTICAL to the stale record (only the nickname, outside the struct, differs). During
    naming nothing may go out; at battle_end the engine has returned from AddPartyMon, so the
    record in the target slot is the catch: exactly one capture, no no_catch, nothing pending."""
    w = World(title)
    rng = random.Random(71)
    species = (0x99, 0xB1, 0xA5, 0xB0, 0x54, 0x7B)
    mons = [_mon(rng, s, level=20, nick=f"M{i}") for i, s in enumerate(species)]
    w.seed_party(mons)
    w.set_map(0x0C)
    w.give_poke_ball()
    w.connect()
    w.step(60)
    r = w.ram
    stale = codec.key(mons[5])
    w.bus[r["wMoveMonType"]], w.bus[r["wWhichPokemon"]] = 1, 0
    w.fire("move_mon")
    _seed_active_box(w, [_boxed(mons[0])])
    w.seed_party(mons[1:])
    w.step(3)
    _publish_species(w, 4, 0x7C, "M5")
    w.fire("evolve")
    w.step(2)
    assert [c["old_key"] for c in w.events("key_change")] == [stale]
    n = len(w.events("capture"))
    w.in_battle(0x7B, 0x7B, 20)
    w.fire("wild_begin")
    w.step()
    w.bus[r["wMonDataLocation"]], w.bus[r["wCurPartySpecies"]] = 0, 0x7B
    w.fire("add_party_mon")
    w.bus[r["wPartyCount"]] = 6
    w.bus[r["wPartySpecies"] + 5], w.bus[r["wPartySpecies"] + 6] = 0x7B, 0xFF
    w.bus[r["wPartyMonOT"] + 55:r["wPartyMonOT"] + 66] = codec.encode_name("RED")
    w.step(600)                                                 # naming screen
    assert w.events("capture")[n:] == []
    # the engine writes the record: byte-for-byte the stale one, a new nickname beside it
    base = r["wPartyMons"] + 5 * 44
    w.bus[base:base + 44] = codec.encode_party_mon(mons[5])
    w.bus[r["wPartyMonNicks"] + 55:r["wPartyMonNicks"] + 66] = codec.encode_name("CATER2")
    w.step(300)                                                 # still naming: bytes-equal, no capture yet
    assert w.events("capture")[n:] == []
    w.bus[r["wIsInBattle"]] = 0
    w.fire("battle_end")
    w.step(3)
    caps = w.events("capture")[n:]
    assert len(caps) == 1, caps
    assert caps[0]["key"] == stale == codec.key(w.party()[5]) and caps[0]["nickname"] == "CATER2"
    assert caps[0]["level"] == 20 and caps[0]["area_id"] == "route_1" and caps[0]["in_box"] is False
    assert w.events("no_catch") == []
    w.step(5)
    assert w.client.pending_change is None and len(w.events("capture")) == n + 1
    w.assert_all_conform()


# ── A1 acknowledged key_change, row 10 discriminator, Live 2 spurious battle_begin ───────

def test_key_change_keeps_the_old_key_as_an_alias_until_the_ack(world):
    world.connect()
    old = codec.key(world.party()[0])
    world.bus[world.ram["wWhichPokemon"]] = 0
    party = world.party()
    party[0]["species"] = 0x09                  # the site fires after the species is published
    world.seed_party(party)
    world.fire("evolve")
    world.step()
    new = codec.key(world.party()[0])
    assert world.events("key_change")[-1]["new_key"] == new
    known = set(world.client.known_keys.keys())
    assert old in known and new in known, "both keys stay known until the server answers"
    world.reply({"cmd": "key_change_ack", "old_key": old, "new_key": new})
    world.step()
    known = set(world.client.known_keys.keys())
    assert old not in known and new in known
    assert not any("unknown command" in line for line in world.logs)


def test_key_change_rejected_is_handled_not_logged_as_unknown(world):
    world.connect()
    old = codec.key(world.party()[0])
    world.bus[world.ram["wWhichPokemon"]] = 0
    world.fire("evolve")
    world.step()
    party = world.party()
    party[0]["species"] = 0x09
    world.seed_party(party)
    world.step()
    world.reply({"cmd": "key_change_rejected", "old_key": old, "new_key": codec.key(world.party()[0]),
                 "reason": "collision"})
    world.step()
    assert world.client.key_alias is None
    assert any("REFUSED" in str(h[1]) for h in world.hud)
    assert not any("unknown command" in line for line in world.logs)


def test_an_in_battle_add_with_location_80_and_no_pending_trade_is_a_capture(world):
    """Row 10: $80 is not the NPC-trade discriminator (Bill's Garden uses it for a wild catch)."""
    world.connect()
    world.in_battle(opponent=0x54, species=0x54, level=25)
    world.fire("wild_begin")
    world.step()
    world.bus[world.ram["wMonDataLocation"]] = 0x80
    world.fire("add_party_mon")
    world.step()
    rng = random.Random(21)
    world.seed_party(world.party() + [_mon(rng, 0x54, level=25, nick="PIKA")])
    world.step(2)
    assert [c["species_id"] for c in world.events("capture")] == [0x54]


def test_a_battle_begin_with_no_opponent_stages_nothing(world):
    """Live 2: InitBattleCommon fires once with wCurOpponent == 0 after the starter pick."""
    world.connect()
    world.bus[world.ram["wCurOpponent"]] = 0
    world.fire("battle_begin")
    world.step()
    assert world.client.battle is None and world.events("trainer_battle_start") == []


def _hello_model_rom(title):
    """Only pinned code/checkpoint slices, for MODEL scheduling controls, not a ROM receipt."""
    image = bytearray(0x100000)
    for site in SITES[title]["sites"].values():
        for anchor in (site, site.get("prelude")):
            if anchor:
                raw = bytes.fromhex(anchor["expected_hex"])
                start = anchor["rom_offset"]
                image[start:start + len(raw)] = raw
    checkpoint = WS[title]["write_safe"]
    if "expected_hex" in checkpoint:
        anchors = {checkpoint[key]: bytes.fromhex(value)
                   for key, value in checkpoint["expected_hex"].items()}
    else:
        # SM83 JP/CALL and the vanilla DelayFrame loop; these only establish the
        # injected checkpoint predicate for this scheduling model, not ROM evidence.
        def transfer(opcode, target):
            return bytes((opcode, target & 255, target >> 8))
        low = checkpoint["vblank_flag"] & 255
        anchors = {
            checkpoint["irq_vector"]: transfer(0xC3, checkpoint["vblank_entry"]),
            checkpoint["delay_frame"]: bytes((0x3E, 1, 0xE0, low, 0x76, 0xF0, low, 0xA7)),
            checkpoint["overworld_loop"]: transfer(0xCD, checkpoint["delay_frame"]),
            checkpoint["overworld_loop_less_delay"]: transfer(0xCD, checkpoint["delay_frame"]),
        }
    for start, raw in anchors.items():
        image[start:start + len(raw)] = raw
    return bytes(image)


def _hello_model_world(monkeypatch):
    monkeypatch.setitem(globals(), "_rom", _hello_model_rom)
    world = World("red")
    world.seed_party([_mon(random.Random(81), 0x99, nick="BULBA")])
    world.set_map(0x0C)
    return world


def test_model_hello_refuses_failed_queue_then_retries_through_actual_entry(monkeypatch):
    world = _hello_model_world(monkeypatch)
    send = world.net.send
    world.net.send = lambda _line: False
    world.connect()
    assert world.events("hello") == []
    assert world.client.hello_sent is False
    world.net.send = send
    world.step()
    assert len(world.events("hello")) == 1 and world.client.hello_sent is True


def test_model_hello_identity_change_rehellos_and_clears_old_identity_aliases(monkeypatch):
    world = _hello_model_world(monkeypatch)
    world.connect()
    world.client.retired_alias.old = world.lua.table()
    world.client.key_alias = world.lua.table()
    world.bus[world.ram["wPlayerID"]:world.ram["wPlayerID"] + 2] = b"\x43\x21"
    world.step()
    assert [packet["ot_id"] for packet in world.events("hello")] == [0x1234, 0x4321]
    assert len(world.client.retired_alias) == 0 and world.client.key_alias is None


def test_model_hello_missing_required_save_version_stays_held(monkeypatch):
    world = _hello_model_world(monkeypatch)
    world.parts.profile.derived.game_internal_version = 7
    world.connect()
    assert world.events("hello") == [] and world.client.hello_sent is False


def test_model_hello_late_unreadable_party_does_not_send_an_empty_snapshot(monkeypatch):
    world = _hello_model_world(monkeypatch)
    original = world._read_u8
    count_reads = 0

    def read(address, domain=None):
        nonlocal count_reads
        if int(address) == world.ram["wPartyCount"] and domain != "ROM":
            count_reads += 1
            if count_reads == 2:
                return 255
        return original(address, domain)

    monkeypatch.setattr(world, "_read_u8", read)
    world.io.read_u8 = read
    world.connect()
    assert world.events("hello") == [] and world.client.hello_sent is False
    world.step()
    assert len(world.events("hello")) == 1


def test_model_hello_changed_identity_during_payload_build_is_not_queued(monkeypatch):
    world = _hello_model_world(monkeypatch)
    original = world._read_u8
    changed = False

    def read(address, domain=None):
        nonlocal changed
        result = original(address, domain)
        if not changed and int(address) == world.ram["wPlayerName"] and domain != "ROM":
            changed = True
            world.bus[world.ram["wPlayerID"]:world.ram["wPlayerID"] + 2] = b"\x43\x21"
        return result

    monkeypatch.setattr(world, "_read_u8", read)
    world.io.read_u8 = read
    world.connect()
    assert world.events("hello") == [] and world.client.hello_sent is False
    world.step()
    assert [packet["ot_id"] for packet in world.events("hello")] == [0x4321]


def test_model_hello_menu_hold_reconnect_battle_and_reset_remain_supported(monkeypatch):
    world = _hello_model_world(monkeypatch)
    world.regs["PC"] = 0x1234
    world.connect()
    assert world.events("hello") == []
    world.overworld_safe()
    world.step()
    assert len(world.events("hello")) == 1
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.regs["PC"] = 0x1234
    world.connected = False
    world.step()
    world.connected = True
    world.step()
    assert len(world.events("hello")) == 2
    assert world.events("hello")[-1]["in_battle"] is True
    world.client.hello_session.invalidate(world.client.hello_session, "save_reset")
    world.step()
    assert len(world.events("hello")) == 3


def test_a_deferred_backing_withdraw_settles_only_after_the_save_witness(world):
    """gen1-box-durability (mirror of gen2 699930b6): party_mon asks boxes.lua to defer a non-current
    box removal; the client acks at once and re-runs party_mon (the replay = the settle) only at the
    first checkpoint after save_witness."""
    calls = []

    def withdraw(_self, key, stats=None, base=None, nickname=None, opts=None):
        calls.append((key, bool(opts and opts["defer_backing"])))
        return (True, "backing removal deferred to the save witness") if len(calls) == 1 else True
    world.client.boxes = world.lua.table_from({"withdraw": withdraw})
    world.connect()
    world.step(60)
    world.overworld_safe()
    world.reply({"cmd": "party_mon", "key": "ABCD:0001:99"})
    world.step(2)
    assert calls == [("ABCD:0001:99", True)]
    assert [m["key"] for m in world.events("sync_retrieve_done")] == ["ABCD:0001:99"]
    world.overworld_safe()
    world.step(5)
    assert len(calls) == 1                     # no settle before the native save
    world.fire("save_witness")
    world.overworld_safe()
    world.step(2)
    assert calls == [("ABCD:0001:99", True), ("ABCD:0001:99", False)]


# ── MAJOR-1 (review e9d5e136): the prepare round ─────────────────────────────────────────────────

def test_a_patched_cartridge_declares_and_answers_the_prepare_round():
    w = _patched_world()
    assert w.events("hello")[0].get("trade_prepare") is True
    old_key = codec.key(w.party()[0])
    w.reply({"cmd": "apply_prepare", "token": "t40", "slot": 0, "old_key": old_key},
            {"cmd": "apply_prepare", "token": "t41", "slot": 0, "old_key": "0000:0000:01"})
    w.step()
    assert [(m["token"], m["ok"]) for m in w.events("apply_ready")] == [("t40", True), ("t41", False)]
    assert _overlay(w)[5] != 5, "a prepare arms nothing"
    w.assert_all_conform()


def test_an_unpatched_cartridge_declares_no_prepare_round(world):
    world.connect()
    world.step(3)
    assert world.events("hello")[0].get("trade_prepare") is False


# ── MAJOR-4 (review e9d5e136): an armed APPLY is withdrawn on the server's word ──────────────────

def test_a_withdrawn_unpicked_apply_restores_the_union_and_reports_nothing_changed():
    """The Gen 1 service picks APPLY up on any overworld frame (SlinkForeground): an APPLY left armed
    past the server's settle could commit after a rollback (review probe P3)."""
    w = _patched_world()
    base = w.ram["wSerialPartyMonsPatchList"]
    preimage = _overlay(w)
    old_key = codec.key(w.party()[0])
    rng = random.Random(31)
    incoming = _mon(rng, 0xB1, level=7, nick="PIDGEY")
    blob = codec.encode_party_mon(incoming) + codec.encode_name("BLUE") + codec.encode_name("PIDGEY")
    w.reply({"cmd": "apply_trade", "slot": 0, "blob_hex": blob.hex().upper(), "old_key": old_key,
             "token": "t50", "partner_name": "BLUE"})
    w.step()
    assert _overlay(w)[5] == 5
    w.reply({"cmd": "withdraw_trade", "token": "t50"})
    w.step()
    assert _overlay(w) == preimage, "the borrowed union is given back untouched"
    assert [(d["token"], d["new_key"]) for d in w.events("trade_done")] == [("t50", old_key)]
    assert w.client.trade_state is None
    w.assert_all_conform()


def test_a_withdraw_past_the_commit_boundary_declares_uncertain():
    w = _patched_world()
    _applying(w, token="t51")
    w.bus[w.ram["wRemoveMonFromBox"]] = 0
    w.bus[w.ram["wWhichPokemon"]] = 0
    w.fire("remove_pokemon")
    w.step()
    w.reply({"cmd": "withdraw_trade", "token": "t51"})
    w.step(2)
    assert _uncertain_done(w) == [("t51", True, False)]


def test_a_complete_box_scan_is_stamped_with_a_generation(world):
    """KEY-SCOPE-5: `pc_boxes` is a complete census only with `pc_boxes_generation`, bumped after
    each successful full rescan and never on a failed one (the server fails a key_change closed
    on a missing or stale census)."""
    def reconnect():
        world.connected = False
        world.step(5)
        world.connected = True
        world.step(1)
        return world.events("hello")[-1]

    world.connect()
    assert world.events("hello")[-1].get("pc_boxes_generation") == 1
    world.step(30)
    assert world.events("tick")[-1].get("pc_boxes_generation") == 1
    world.bus[world.ram["wBoxCount"]] = 0xFF          # the active box reads malformed: the scan fails
    assert reconnect().get("pc_boxes_generation") == 1
    world.bus[world.ram["wBoxCount"]] = 0
    assert reconnect().get("pc_boxes_generation") == 2
    world.assert_all_conform()
