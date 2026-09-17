"""C-0/C-4 (MODEL): the whole Gen 1 client, built by lua/gen1/entry.lua exactly as production
builds it, driven under lupa against a fake BizHawk and a fake server. Every line it sends is
checked against tests/unit/protocol_schema.py; every write is read back through the Python
codec; the real write-safety checkpoint and the real clean ROM are used.
"""
from __future__ import annotations

import json
import pathlib
import random

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
        hud = L.table(
            show=lambda *a: self.hud.append(("show",) + tuple(str(x) if isinstance(x, str) else x for x in a)),
            prompt=lambda *a: self.hud.append(("prompt",) + tuple(str(x) if isinstance(x, str) else x for x in a)),
            set_game_over=lambda: self.hud.append(("game_over",)),
            set_rebuilding=lambda t: self.hud.append(("rebuilding", str(t))),
            clear_rebuilding=lambda: self.hud.append(("rebuild_done",)),
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
    party[1] = _mon(rng, 0x2D, level=10, nick="JYNX")  # received mon lands in the same slot for this model
    world.seed_party(party)
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


def test_evolution_emits_key_change_with_reason(world):
    world.connect()
    old = codec.key(world.party()[0])
    world.bus[world.ram["wWhichPokemon"]] = 0
    world.fire("evolve")
    world.step()
    party = world.party()
    party[0]["species"] = 0x09  # Ivysaur
    world.seed_party(party)
    world.step()
    kc = world.events("key_change")
    assert kc[-1]["old_key"] == old and kc[-1]["new_key"] == codec.key(world.party()[0])
    assert kc[-1]["reason"] == "evolution" and kc[-1]["new_species"] == 0x09


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
    assert not world.client.sync_written[key]
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
    """panel.lua's _tile_for over a row padded/truncated to 20 (memory_gb.lua:1555-1568)."""
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
