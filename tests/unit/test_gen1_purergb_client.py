"""P3b (PLAN §6 M2-a/M2-b): the ONE Gen 1 Lua client on the pureRGB foundation.

The pack under test is data/games/gen1_purergb/ (profile, engine_signals, write_checkpoint,
admission, species_index, charmap.lua). No pureRGB ROM ships with the repo, so the cartridge is
SYNTHETIC: a 1 MiB image carrying every site's pinned bytes at its rom_offset, the checkpoint's
expected_hex anchors and a couple of 35-byte BaseStats records. That is exactly what signals.lua
and gen1_write_safety.lua verify against, so a pass here proves the client reads the pack, not
a memory of vanilla. WRAM is a synthetic image too, with a bank-2 aliasing mode for the flat
WRAM-domain read rule (PLAN §4 row 13).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import random
import re

import lupa
import pytest

from server.adapters import gen1_codec as codec

REPO = pathlib.Path(__file__).resolve().parents[2]
PURE = REPO / "data" / "games" / "gen1_purergb"
RBY = REPO / "data" / "games" / "gen1_rby"
PROFILE = json.loads((PURE / "profile.json").read_text(encoding="utf-8"))["titles"]
SITES = json.loads((PURE / "engine_signals.json").read_text(encoding="utf-8"))["titles"]
WS = json.loads((PURE / "write_checkpoint.json").read_text(encoding="utf-8"))
ADMISSION = json.loads((PURE / "admission.json").read_text(encoding="utf-8"))
SPECIES = json.loads((PURE / "species_index.json").read_text(encoding="utf-8"))
RBY_PROFILE = json.loads((RBY / "profile.json").read_text(encoding="utf-8"))["titles"]
ENTRY = (REPO / "lua" / "gen1" / "entry.lua").as_posix()
SIGNALS = (REPO / "lua" / "gen1" / "signals.lua").as_posix()
SAFETY = (REPO / "lua" / "gen1_write_safety.lua").as_posix()
ROM_SIZE = 0x100000
TITLE = "purered"
STRIDE = PROFILE[TITLE]["derived"]["base_stats_stride"]


def _place(rom: bytearray, offset: int, hexs: str) -> None:
    want = bytes.fromhex(hexs)
    for i, b in enumerate(want):  # overlapping sites must agree byte for byte
        assert rom[offset + i] in (0, b), f"synthetic ROM conflict at {offset + i:#x}"
        rom[offset + i] = b


def synth_rom(title: str = TITLE) -> bytes:
    """A cartridge whose pinned bytes are where the pack says; everything else zero."""
    rom = bytearray(ROM_SIZE)
    header = next(r["header_title"] for r in ADMISSION.values() if r["title"] == title)
    rom[0x134:0x134 + len(header)] = header.encode("ascii")
    for site in SITES[title]["sites"].values():
        _place(rom, site["rom_offset"], site["expected_hex"])
        if site.get("prelude"):
            _place(rom, site["prelude"]["rom_offset"], site["prelude"]["expected_hex"])
    ws = WS[title]["write_safe"]
    for key, hexs in ws["expected_hex"].items():
        _place(rom, ws[key], hexs)
    # two verified base-stats records at the 35-byte stride: dex 1 and dex 112 (Rhydon, internal 1)
    base = PROFILE[title]["rom"]["BaseStats"]["flat"]
    for dex in (1, 112):
        rec = bytearray(STRIDE)
        rec[0] = dex
        rec[1:6] = bytes([45, 49, 49, 45, 65]) if dex == 1 else bytes([105, 130, 120, 40, 45])
        rec[19] = 3  # GROWTH_MEDIUM_SLOW
        _place(rom, base + (dex - 1) * STRIDE, rec.hex())
    return bytes(rom)


class PureWorld:
    """Fake BizHawk + fake server over the pureRGB pack and the synthetic cartridge."""

    def __init__(self, title: str = TITLE, player: str = "a"):
        self.title, self.player = title, player
        self.ram = PROFILE[title]["ram"]
        self.d = PROFILE[title]["derived"]
        self.rom = synth_rom(title)
        self.bus = bytearray(0x10000)      # what the System Bus sees below $D000 and bank 1
        self.wram_bank2 = bytearray(0x1000)  # what the System Bus sees at $Dxxx while SVBK == 2
        self.cart = bytearray(0x8000)
        self.regs = {"PC": 0, "SP": 0xDFF0, "H": 0, "L": 0, "F": 0, "WRAM BANK": 1}
        self.frame = 0
        self.hooks = {}
        self.next_hook = 1
        self.connected = False
        self.sent: list[dict] = []
        self.replies: list[str] = []
        self.hud: list[tuple] = []
        self.writes: list[tuple[int, int, str]] = []
        self.set_registers: list[tuple[str, int]] = []
        self.logs: list[str] = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        L = self.lua
        io = L.table(
            read_u8=self._read_u8, read_range=self._read_range, write_u8=self._write_u8,
            on_bus_exec=self._on_bus_exec, unregister=lambda i: None,
            framecount=lambda: self.frame, register=lambda name: self.regs[str(name)],
            set_register=self._set_register,
            domains=lambda: L.table("System Bus", "ROM", "CartRAM", "WRAM"),
            saveram=lambda: None,
        )
        net = L.table(
            init=lambda h, p: None, connected=lambda: self.connected, pump=lambda: None,
            send=lambda line: self.sent.append(json.loads(str(line))),
            receive=lambda: self.replies.pop(0) if self.replies else None,
        )
        hud = L.table(
            show=lambda *a: self.hud.append(("show",) + tuple(str(x) if isinstance(x, str) else x for x in a)),
            prompt=lambda *a: self.hud.append(("prompt",) + tuple(a)),
            set_game_over=lambda: None, set_rebuilding=lambda t: None, clear_rebuilding=lambda: None,
            sanitize=lambda s: s,
        )
        Entry = L.eval(f'dofile("{ENTRY}")')
        deps = L.table(root=REPO.as_posix(), io=io, net=net, hud=hud, pack="gen1_purergb", title=title,
                       kind="clean", player=player, rom_sha1=PROFILE[title]["rom_sha1"],
                       log=lambda t: self.logs.append(str(t)))
        self.client, self.parts = Entry.build(deps)
        self.client.start(self.client)
        self.overworld_safe()

    # -- BizHawk fakes ------------------------------------------------------------------
    def _set_register(self, name, value):
        self.regs[str(name)] = int(value)
        self.set_registers.append((str(name), int(value)))

    def _read_u8(self, addr, domain=None):
        addr, dom = int(addr), str(domain) if domain is not None else "System Bus"
        if dom == "ROM":
            return self.rom[addr]
        if dom == "CartRAM":
            return self.cart[addr]
        if dom == "WRAM":  # flat: bank 0 at 0x0000, bank 1 at 0x1000, bank 2 at 0x2000
            if addr < 0x2000:
                return self.bus[0xC000 + addr]
            return self.wram_bank2[addr - 0x2000]
        if addr < 0x8000:
            bank = self.bus[self.ram["hLoadedROMBank"]] or 1
            flat = addr if addr < 0x4000 else bank * 0x4000 + (addr - 0x4000)
            return self.rom[flat] if flat < len(self.rom) else 0
        if 0xD000 <= addr <= 0xDFFF and self.regs["WRAM BANK"] == 2:
            return self.wram_bank2[addr - 0xD000]  # System Bus follows SVBK
        return self.bus[addr]

    def _read_range(self, addr, length, domain=None):
        return self.lua.table(*[self._read_u8(int(addr) + i, domain) for i in range(int(length))])

    def _write_u8(self, addr, value, domain=None):
        addr, dom = int(addr), str(domain) if domain is not None else "System Bus"
        (self.cart if dom == "CartRAM" else self.bus)[addr] = int(value)
        self.writes.append((addr, int(value), dom))

    def _on_bus_exec(self, fn, addr, name, domain=None):
        hid = self.next_hook
        self.next_hook += 1
        self.hooks[str(name)] = (fn, int(addr))
        return hid

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
        self.bus[r["wCurrentBoxNum"]] = 0

    def give_items(self, *pairs):
        r = self.ram
        self.bus[r["wNumBagItems"]] = len(pairs)
        for i, (item, qty) in enumerate(pairs):
            self.bus[r["wBagItems"] + 2 * i], self.bus[r["wBagItems"] + 2 * i + 1] = item, qty
        self.bus[r["wBagItems"] + 2 * len(pairs)] = 0xFF

    def party(self):
        r = self.ram
        return codec.decode_party(bytes(self.bus[r["wPartyCount"]:r["wPartyCount"] + 404]))

    def set_map(self, map_id, x=5, y=5):
        self.bus[self.ram["wCurMap"]] = map_id
        self.bus[self.ram["wXCoord"]], self.bus[self.ram["wYCoord"]] = x, y

    def overworld_safe(self):
        """The pure checkpoint (PLAN A5 / Live 1): PC at the IRQ vector, parked in DelayFrame's
        halt from OverworldLoop's `rst _DelayFrame`, wDelayFrameBank 0, WRAM bank 1."""
        ws = WS[self.title]["write_safe"]
        self.regs["PC"], self.regs["SP"], self.regs["WRAM BANK"] = ws["irq_vector"], 0xDFE0, 1
        sp = self.regs["SP"]
        resume, caller = ws["delay_frame_resume"], ws["overworld_return"]
        self.bus[sp], self.bus[sp + 1] = resume & 0xFF, resume >> 8
        self.bus[sp + 2], self.bus[sp + 3] = caller & 0xFF, caller >> 8
        self.bus[ws["vblank_flag"]] = 1
        self.bus[ws["delay_frame_bank"]] = 0
        self.bus[ws["link_state"]] = ws["link_none"]
        self.bus[ws["serial_status"]] = ws["disconnected_serial"]
        self.bus[ws["entering_cable_club"]] = 0
        self.bus[self.ram["wIsInBattle"]] = 0
        self.bus[self.ram["wJoyIgnore"]] = 0
        self.bus[self.ram["wFontLoaded"]] = 0

    def in_battle(self, opponent, species, level, active_slot=0):
        r = self.ram
        self.bus[r["wIsInBattle"]] = 1 if opponent < self.d["opp_id_offset"] else 2
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
    def fire(self, kind, wrong_bank=False):
        site = SITES[self.title]["sites"][kind]
        self.bus[self.ram["hLoadedROMBank"]] = site["bank"] + (1 if wrong_bank else 0)
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
        self.client.validate(self.client)  # the live-party validation that enables writes

    def reply(self, *cmds):
        self.replies.append(json.dumps({"commands": list(cmds)}))

    def events(self, kind=None):
        return [m for m in self.sent if kind is None or m["event"] == kind]

    def status(self):
        return dict(self.client.signals.status(self.client.signals).items())

    def known_keys(self):
        return set(self.client.known_keys.keys())


def _mon(rng, species, level=5, hp=None, nick="MON", dvs=None, ot_id=None):
    m = codec.decode_party_mon(bytes(rng.randrange(256) for _ in range(44)))
    m["species"], m["level"], m["status"] = species, level, 0
    m["max_hp"] = 20 + rng.randrange(20)
    m["hp"] = m["max_hp"] if hp is None else hp
    m["nick"] = nick
    if dvs is not None:
        m["dvs"] = {"raw": dvs, "atk": dvs >> 12, "def": (dvs >> 8) & 15, "spd": (dvs >> 4) & 15,
                    "spc": dvs & 15}
        m["dvs"]["hp"] = ((dvs >> 12) & 1) * 8 + ((dvs >> 8) & 1) * 4 + ((dvs >> 4) & 1) * 2 + (dvs & 1)
    if ot_id is not None:
        m["ot_id"] = ot_id
    return m


@pytest.fixture
def world():
    w = PureWorld()
    rng = random.Random(1)
    w.seed_party([_mon(rng, 0x99, nick="BULBA"), _mon(rng, 0xB1, nick="PIDGEY")])
    w.set_map(0x0C)
    w.give_items((0x04, 1))  # POKE_BALL
    return w


# ── foundation selection (row 1 / A3) ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def entry():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.eval(f'dofile("{ENTRY}")'), lua.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')


def _admit(entry, **kw):
    lua, E, json_mod = entry
    args = {"root": REPO.as_posix(), "json": json_mod, **kw}
    if "rom_bytes" in args:
        data = args.pop("rom_bytes")
        args["read_rom_u8"] = lambda i: data[int(i)]
        args["rom_size"] = len(data)
    got = E.admit(lua.table_from(args))
    if isinstance(got, tuple):
        return None, got[1]
    return dict(got.items()), None


@pytest.mark.parametrize("size", [0, 3, 55, 56, 63, 64, 65, 200, 1000])
def test_the_pure_lua_sha1_matches_hashlib(entry, size):
    """The rehash path hashes the whole ROM domain in Lua; it has to be a real SHA-1."""
    _, E, _ = entry
    data = bytes(random.Random(size).randrange(256) for _ in range(size))
    assert E.sha1(lambda i: data[int(i)], size) == hashlib.sha1(data).hexdigest()


@pytest.mark.parametrize("title", ["purered", "pureblue", "puregreen"])
def test_a_pure_sha1_selects_the_pure_pack_even_though_the_header_says_red(entry, title):
    sha = next(s for s, r in ADMISSION.items() if r["title"] == title)
    got, why = _admit(entry, rom_sha1=sha.upper(), header="POKEMON RED")  # BizHawk uppercases
    assert why is None, why
    assert got["pack"] == "gen1_purergb" and got["title"] == title and got["kind"] == "clean"
    assert got["rom_type"] == {"purered": "PureRed", "pureblue": "PureBlue", "puregreen": "PureGreen"}[title]
    assert got["rom_sha1"] == sha and got["rehashed"] is False


@pytest.mark.parametrize("title", ["red", "blue", "yellow"])
def test_a_vanilla_sha1_selects_the_vanilla_pack(entry, title):
    got, why = _admit(entry, rom_sha1=RBY_PROFILE[title]["rom_sha1"].upper(), header="POKEMON " + title.upper())
    assert why is None, why
    assert got["pack"] == "gen1_rby" and got["title"] == title and got["rom_type"] == title.capitalize()


def test_a_red_header_with_an_unknown_sha1_is_refused_with_the_pure_reason(entry):
    """The header collision: never fall back to vanilla Red because the header matched."""
    got, why = _admit(entry, rom_sha1="0" * 40, header="POKEMON RED")
    assert got is None
    assert "pureRGB" in why and "POKEMON RED" in why and "0" * 40 in why


def test_indatabase_forces_a_lua_rehash_of_the_rom_domain(entry):
    """BizHawk substitutes its database hash when it knows the ROM; the bytes decide."""
    image = bytes(random.Random(7).randrange(256) for _ in range(4096))
    real = hashlib.sha1(image).hexdigest()
    vanilla = RBY_PROFILE["red"]["rom_sha1"]
    # without the flag the (wrong) reported hash is trusted and admits vanilla Red
    got, _ = _admit(entry, rom_sha1=vanilla, indatabase=False, header="POKEMON RED", rom_bytes=image)
    assert got["pack"] == "gen1_rby" and got["rehashed"] is False
    # with it the bytes are hashed, the database hash ignored, and this image admits nothing
    got, why = _admit(entry, rom_sha1=vanilla, indatabase=True, header="POKEMON RED", rom_bytes=image)
    assert got is None and real in why


def test_an_unknown_reported_hash_is_rehashed_before_refusing(entry):
    image = bytes(random.Random(8).randrange(256) for _ in range(512))
    got, why = _admit(entry, rom_sha1="ffff", header="POKEMON CRYSTAL", rom_bytes=image)
    assert got is None and hashlib.sha1(image).hexdigest() in why and "pureRGB" not in why


# ── the pure client boots on the pack ────────────────────────────────────────────────────

def test_the_pure_client_registers_every_pack_site_and_hellos(world):
    assert set(world.hooks) == {f"SLink-gen1-{k}" for k in SITES[TITLE]["sites"]}
    assert world.client.signals.registered == len(SITES[TITLE]["sites"])
    world.connect()
    h = world.events("hello")
    assert len(h) == 1
    assert h[0]["rom_type"] == "PureRed" and h[0]["foundation"] == "gen1_purergb"
    assert h[0]["artifact_kind"] == "clean" and h[0]["rom_sha1"] == PROFILE[TITLE]["rom_sha1"]
    assert h[0]["panel"] is False, "a clean pureRGB cartridge has no companion mailbox"
    assert world.client.trade_enabled is False
    assert [e["species_id"] for e in h[0]["party"]] == [0x99, 0xB1]


def test_no_vanilla_receptionist_probe_on_a_pure_cartridge(world):
    """The $29C3 dispatch bytes on a pure ROM mean nothing; no trade block = no probe."""
    rom = bytearray(world.rom)
    rom[0x29C3:0x29C3 + 5] = bytes([0x21, 0x00, 0x4C, 0x06, 0x3F])
    world.rom = bytes(rom)
    assert world.client.trade_patch_present(world.client) is False
    assert world.client.trade is None


# ── profile-driven values (rows 6, 7, 11) ────────────────────────────────────────────────

def test_bag_snapshot_is_62_bytes_and_the_ball_set_is_the_profiles(world):
    r = world.ram
    world.give_items((0x08, 2), (0x05, 1), (0x04, 3), (0x06, 9))
    world.connect()
    assert world.events("hello")[0]["ball_count"] == 6, "items 5 and 8 are balls on pureRGB"
    # bag_received: HL == wNumBagItems, carry set, the item is a ball class
    world.regs["H"], world.regs["L"], world.regs["F"] = r["wNumBagItems"] >> 8, r["wNumBagItems"] & 0xFF, 0x10
    world.bus[r["wCurItem"]] = 0x08
    world.fire("bag_received")
    sig = list(world.client.signals.drain(world.client.signals).values())
    assert len(sig) == 1 and len(sig[0].point.bag) == 2 + 2 * world.d["bag_capacity"] == 62
    world.bus[r["wCurItem"]] = 0x06  # not a ball
    world.fire("bag_received")
    assert world.status()["pending"] == 0


def test_bag_capacity_is_the_profile_value_not_symbol_arithmetic(world):
    """wPlayerMoney precedes wBagItems on pureRGB: the old formula would go negative."""
    assert world.ram["wPlayerMoney"] < world.ram["wBagItems"]
    assert world.parts.reads.bag_capacity == 30
    items = [(0x04, i + 1) for i in range(30)]
    world.give_items(*items)
    bag = dict(world.parts.reads.read_bag().items())
    assert len(bag["items"]) == 30


def test_trainer_threshold_is_197(world):
    reads = world.parts.reads
    world.bus[world.ram["wCurOpponent"]] = 199
    b = dict(reads.read_battle().items())
    assert b["is_trainer"] is True and b["trainer_class"] == 2
    world.bus[world.ram["wCurOpponent"]] = 196
    b = dict(reads.read_battle().items())
    assert b["is_trainer"] is False


def test_trainer_battle_start_uses_the_profile_offset_and_ignores_a_zero_opponent(world):
    world.connect()
    # Live 2: InitBattleCommon fires once with wCurOpponent == 0 after the starter pick
    world.bus[world.ram["wCurOpponent"]] = 0
    world.fire("battle_begin")
    world.step()
    assert world.events("trainer_battle_start") == [] and world.client.battle is None
    world.in_battle(opponent=200, species=0x99, level=9)  # class 3 on pureRGB (200 - 197)
    world.fire("battle_begin")
    world.step()
    assert [e["trainer_id"] for e in world.events("trainer_battle_start")] == [200]


def test_no_404_or_42_literal_remains_in_signals():
    src = re.sub(r"--[^\n]*", "", (REPO / "lua" / "gen1" / "signals.lua").read_text(encoding="utf-8"))
    assert not re.search(r"\b404\b", src) and not re.search(r"\b42\b", src)
    csrc = re.sub(r"--[^\n]*", "", (REPO / "lua" / "gen1" / "client.lua").read_text(encoding="utf-8"))
    assert not re.search(r"\b0x29C3\b", csrc) and not re.search(r"\b0x8000\b", csrc)
    assert "for box = 0, 11 do" not in csrc


# ── flat WRAM reads (row 13) and the bank write gate ─────────────────────────────────────

def test_party_reads_survive_a_bank_2_window_through_the_flat_wram_domain(world):
    """System Bus follows SVBK; the pure client reads $Dxxx through the WRAM domain."""
    world.connect()
    world.regs["WRAM BANK"] = 2  # the palette-fade window: the bus shows bank 2 at $Dxxx
    party = world.parts.reads.read_party()
    assert party is not None and len(party) == 2
    world.step(30)
    assert world.events("tick") and len(world.events("tick")[-1]["party"]) == 2


def test_a_dxxx_write_is_refused_while_the_wram_bank_is_outside_0_1(world):
    world.connect()
    w = world.parts.writes
    w.arm(w, "overworld")
    world.regs["WRAM BANK"] = 2
    with pytest.raises(lupa.LuaError, match="WRAM BANK 2"):
        w.write_bytes(w, world.ram["wPartyMon1HP"], world.lua.table(0, 0))
    assert world.writes == []
    world.regs["WRAM BANK"] = 0
    w.write_bytes(w, world.ram["wPartyMon1HP"], world.lua.table(0, 0))
    assert len(world.writes) == 2
    w.disarm(w)


# ── checkpoint (row 12 / A5 / Live 1) ────────────────────────────────────────────────────

class Checkpoint:
    def __init__(self, title=TITLE):
        self.rom = synth_rom(title)
        self.bus = bytearray(0x10000)
        self.p = WS[title]["write_safe"]
        self.profile = dict(WS[title])
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.regs = {"PC": self.p["irq_vector"], "SP": 0xDFF0, "WRAM BANK": 1}
        self.io = self.lua.table(
            read_u8=lambda a, d=None: self.rom[int(a)] if str(d) == "ROM" else self.bus[int(a)],
            register=lambda name: self.regs[str(name)],
            domains=lambda: self.lua.table("System Bus", "ROM", "CartRAM"),
        )
        self.M = self.lua.eval(f'dofile("{SAFETY}")')
        sp = self.regs["SP"]
        self._word(sp, self.p["delay_frame_resume"])
        self._word(sp + 2, self.p["overworld_return"])
        self.bus[self.p["vblank_flag"]] = 1
        self.bus[self.p["serial_status"]] = self.p["disconnected_serial"]
        self.bus[self.p["delay_frame_bank"]] = 0

    def _word(self, addr, value):
        self.bus[addr], self.bus[addr + 1] = value % 256, (value // 256) % 256

    def check(self):
        return self.M.check(self.lua.table_from(self.profile, recursive=True), self.io)


@pytest.mark.parametrize("title", ["purered", "pureblue", "puregreen"])
def test_the_pure_checkpoint_accepts_the_parked_frame(title):
    ok, why = Checkpoint(title).check()
    assert ok is True and "verified" in why, why
    assert WS[title]["write_safe"]["version"] == "gen1-main-loop-purergb-v1"


def test_the_pure_checkpoint_refuses_each_broken_predicate():
    c = Checkpoint()
    c.regs["WRAM BANK"] = 2
    assert c.check() == (False, "DelayFrame bank or WRAM bank outside the checkpoint")
    c = Checkpoint()
    c.bus[c.p["delay_frame_bank"]] = 3
    assert c.check()[0] is False
    c = Checkpoint()
    c._word(c.regs["SP"] + 2, c.p["overworld_loop"] + 3)  # vanilla's +3 caller is wrong here
    ok, why = c.check()
    assert ok is False and "not waiting" in why
    c = Checkpoint()
    c._word(c.regs["SP"], c.p["delay_frame"] + 5)  # vanilla's resume offset
    assert c.check()[0] is False
    c = Checkpoint()
    rom = bytearray(c.rom)
    rom[c.p["delay_frame_halt"]] ^= 0xFF
    c.rom = bytes(rom)
    ok, why = c.check()
    assert ok is False and "instructions differ" in why
    c = Checkpoint()
    c.bus[c.profile["BATTLE_FLAG_ADDR"]] = 1
    assert "owns the game" in c.check()[1]


def test_the_vanilla_checkpoint_version_still_takes_the_vanilla_predicate():
    """Both versions live in one function; a v1 profile never reads the pure fields."""
    c = Checkpoint()
    c.profile = {**c.profile, "write_safe": {**c.p, "version": "gen1-main-loop-v1"}}
    ok, why = c.check()
    assert ok is False and "instructions differ" in why  # the pure ROM has no `call DelayFrame`
    c.profile = {**c.profile, "write_safe": {**c.p, "version": "gen1-main-loop-v3"}}
    assert c.check() == (False, "no verified main-loop profile")


# ── captures (row 10) ────────────────────────────────────────────────────────────────────

def test_bills_garden_capture_with_mon_data_location_80_is_a_capture(world):
    """wMonDataLocation == $80 is not the NPC-trade discriminator; wIsInBattle == 1 is."""
    world.connect()
    world.in_battle(opponent=0x54, species=0x54, level=25)  # wild Pikachu
    world.fire("wild_begin")
    world.step()
    world.bus[world.ram["wMonDataLocation"]] = 0x80
    world.fire("add_party_mon")
    world.step()
    rng = random.Random(2)
    world.seed_party(world.party() + [_mon(rng, 0x54, level=25, nick="PIKABLU")])
    world.step(2)
    caps = world.events("capture")
    assert len(caps) == 1 and caps[0]["species_id"] == 0x54 and caps[0]["gift"] is False


def test_a_trainer_battle_add_is_still_the_enemy_party_not_a_capture(world):
    world.connect()
    world.bus[world.ram["wIsInBattle"]] = 2
    world.bus[world.ram["wMonDataLocation"]] = 0x01
    world.fire("add_party_mon")
    world.step(3)
    assert world.events("capture") == [] and world.client.pending_change is None


def test_a_fled_wild_battle_is_a_failed_encounter_with_the_run_witness_logged(world):
    """Running from the first wild battle loses the area on both foundations (the deadzone rule,
    PLAN §2.3; deadzone_new drives exactly that). pureRGB's wBattleFunctionalFlags RUN bit is a
    witness in the log, never a reason to keep the area open."""
    world.connect()
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.fire("wild_begin")
    world.step()
    world.bus[world.ram["wIsInBattle"]] = 0
    world.bus[world.ram["wBattleFunctionalFlags"]] = 0x02  # bit 1: ran
    world.fire("battle_end")
    world.step(2)
    assert len(world.events("no_catch")) == 1
    assert any("ran" in line for line in world.logs)


def test_tick_carries_safari_type(world):
    world.connect()
    world.bus[world.ram["wSafariType"]] = 1
    world.in_battle(opponent=0xA5, species=0xA5, level=3)
    world.step(30)
    assert world.events("tick")[-1]["safari_type"] == 1


# ── APEX CHIP (A1 / Live 4) ──────────────────────────────────────────────────────────────

def _apex_fire(world, slot, dvs_at):
    """Both APEX hooks, the way the routine reaches them: preflight with HL at the DV bytes,
    then the engine stores $FFFF, then commit."""
    r = world.ram
    world.bus[r["wUsedItemOnWhichPokemon"]] = slot
    world.regs["H"], world.regs["L"] = dvs_at >> 8, dvs_at & 0xFF
    world.fire("apex_preflight")
    world.bus[dvs_at], world.bus[dvs_at + 1] = 0xFF, 0xFF
    world.regs["H"], world.regs["L"] = (dvs_at + 1) >> 8, (dvs_at + 1) & 0xFF
    world.fire("apex_commit")


def _dv_addr(world, slot):
    return world.ram["wPartyMons"] + slot * 44 + 27  # MON_DVS; HL at .setDVs names it (Live 4)


def test_apex_collision_restores_the_dvs_and_sends_no_key_change(world):
    """Two mons, same OT and species, one already at FFFF: the chip on the other would collide."""
    rng = random.Random(3)
    a = _mon(rng, 0x99, nick="ONE", dvs=0xFFFF, ot_id=0x1234)
    b = _mon(rng, 0x99, nick="TWO", dvs=0x1234, ot_id=0x1234)
    world.seed_party([a, b])
    world.connect()
    assert world.client.writes_enabled is True
    before = codec.key(world.party()[1])
    _apex_fire(world, 1, _dv_addr(world, 1))
    assert bytes(world.bus[_dv_addr(world, 1):_dv_addr(world, 1) + 2]) == bytes([0x12, 0x34])
    assert [w for w in world.writes if w[2] == "System Bus"] == [(_dv_addr(world, 1), 0x12, "System Bus"),
                                                                 (_dv_addr(world, 1) + 1, 0x34, "System Bus")]
    assert world.parts.writes.log[1].why == "apex_commit"
    assert any("APEX CHIP REFUSED" in str(h[1]) for h in world.hud)
    world.step(3)
    assert world.events("key_change") == [] and codec.key(world.party()[1]) == before


def test_apex_without_collision_sends_key_change_with_alias_until_ack(world):
    rng = random.Random(4)
    world.seed_party([_mon(rng, 0x99, nick="ONE", dvs=0x1234, ot_id=0x1234)])
    world.connect()
    old = codec.key(world.party()[0])
    _apex_fire(world, 0, _dv_addr(world, 0))
    assert [w for w in world.writes if w[2] == "System Bus"] == []
    world.step(2)
    kc = world.events("key_change")
    assert len(kc) == 1 and kc[0]["reason"] == "apex_chip" and kc[0]["old_key"] == old
    new = codec.key(world.party()[0])
    assert kc[0]["new_key"] == new and new.startswith("FFFF:")
    assert {old, new} <= world.known_keys(), "both keys stay known until the ack"
    world.reply({"cmd": "key_change_ack", "old_key": old, "new_key": new})
    world.step()
    assert old not in world.known_keys() and new in world.known_keys()
    assert world.client.key_alias is None


def test_apex_key_change_rejected_clears_the_alias_and_shows_the_reason(world):
    rng = random.Random(5)
    world.seed_party([_mon(rng, 0x99, nick="ONE", dvs=0x1234, ot_id=0x1234)])
    world.connect()
    old = codec.key(world.party()[0])
    _apex_fire(world, 0, _dv_addr(world, 0))
    world.step(2)
    world.reply({"cmd": "key_change_rejected", "old_key": old, "new_key": codec.key(world.party()[0]),
                 "reason": "collision"})
    world.step()
    assert world.client.key_alias is None
    assert any("REFUSED" in str(h[1]) and "collision" in str(h[1]) for h in world.hud)
    assert not any("unknown command" in line for line in world.logs)


def test_server_seeded_pending_keys_join_the_collision_set(world):
    rng = random.Random(6)
    world.seed_party([_mon(rng, 0x99, nick="ONE", dvs=0x1234, ot_id=0x1234)])
    world.connect()
    world.reply({"cmd": "pending_keys", "keys": ["FFFF:1234:99"]})
    world.step()
    _apex_fire(world, 0, _dv_addr(world, 0))
    assert bytes(world.bus[_dv_addr(world, 0):_dv_addr(world, 0) + 2]) == bytes([0x12, 0x34])
    world.step(3)
    assert world.events("key_change") == []


# ── transformations (A2) ─────────────────────────────────────────────────────────────────

def _transform(world, slot, new_species, new_max_hp):
    r = world.ram
    world.bus[r["wWhichPokemon"]] = slot
    world.bus[r["wCurPartySpecies"]] = new_species
    world.fire("transform")
    hp = r["wPartyMons"] + slot * 44 + (r["wPartyMon1HP"] - r["wPartyMon1"])
    # the engine: species byte, then HP := new max HP (hi at HL, lo at HL+1)
    world.bus[r["wPartyMons"] + slot * 44] = new_species
    world.bus[r["wPartySpecies"] + slot] = new_species
    world.bus[hp] = new_max_hp >> 8
    world.regs["H"], world.regs["L"] = (hp + 1) >> 8, (hp + 1) & 0xFF
    world.fire("transform_hp_lo")
    world.bus[hp + 1] = new_max_hp & 0xFF  # the store the callback precedes
    return hp


def test_a_dead_mon_transformed_is_zeroed_in_the_hook_and_again_at_the_checkpoint(world):
    rng = random.Random(9)
    world.seed_party([_mon(rng, 0x33, nick="DEAD", hp=0)])
    world.connect()
    old = codec.key(world.party()[0])
    hp = _transform(world, 0, 0xAC, 40)
    assert (hp, 0, "System Bus") in world.writes and (hp + 1, 0, "System Bus") in world.writes
    assert world.parts.writes.log[1].why == "transform"
    world.step(2)
    kc = world.events("key_change")
    assert len(kc) == 1 and kc[0]["reason"] == "transform" and kc[0]["old_key"] == old
    assert kc[0]["new_species"] == 0xAC
    # the checkpoint backstop: the deferred force_faint lands on the NEW key at the next safe frame
    world.bus[hp], world.bus[hp + 1] = 0, 40  # as if the low-byte store had won after all
    world.overworld_safe()
    world.step(2)
    assert world.party()[0]["hp"] == 0


def test_a_live_mon_transformed_keeps_its_hp_and_only_changes_key(world):
    rng = random.Random(10)
    world.seed_party([_mon(rng, 0x33, nick="LIVE", hp=17)])
    world.connect()
    _transform(world, 0, 0xAC, 40)
    assert [w for w in world.writes if w[2] == "System Bus"] == []
    world.step(4)
    assert [e["reason"] for e in world.events("key_change")] == ["transform"]
    assert world.party()[0]["hp"] == 40


def test_key_reconciliation_waits_while_the_link_is_active(world):
    rng = random.Random(11)
    world.seed_party([_mon(rng, 0x33, nick="LIVE", hp=17)])
    world.connect()
    world.bus[world.ram["wLinkState"]] = 4
    _transform(world, 0, 0xAC, 40)
    world.step(5)
    assert world.events("key_change") == []
    world.bus[world.ram["wLinkState"]] = 0
    world.step(2)
    assert len(world.events("key_change")) == 1


# ── NPC trade (row 25) and daycare (row 24) readbacks ────────────────────────────────────

def test_npc_trade_identity_comes_from_the_removal_and_the_last_slot(world):
    """The traded mon is slot 0 of two: RemovePokemon compacts, the received one is appended
    LAST, so a slot-0 readback would name the shifted-down survivor."""
    rng = random.Random(12)
    give, keep = _mon(rng, 0x99, nick="GIVE"), _mon(rng, 0xB1, nick="KEEP")
    world.seed_party([give, keep])
    world.connect()
    old = codec.key(world.party()[0])
    world.bus[world.ram["wWhichPokemon"]] = 0
    world.fire("npc_trade")          # +0: selection not made yet on pureRGB, must not bind
    world.step()
    assert world.client.pending_change is None
    world.fire("npc_trade_remove")
    world.fire("remove_pokemon")
    received = _mon(rng, 0x15, nick="RECV", ot_id=0xBEEF)
    world.seed_party([keep, received])
    world.bus[world.ram["wMonDataLocation"]] = 0x80
    world.fire("add_party_mon")
    world.fire("npc_trade_done")
    world.step(3)
    kc = world.events("key_change")
    assert len(kc) == 1 and kc[0]["old_key"] == old and kc[0]["reason"] == "npc_trade"
    assert kc[0]["new_key"] == codec.key(world.party()[1]) and kc[0]["new_species"] == 0x15
    assert world.events("capture") == [] and world.events("party_to_box") == []


def test_daycare_withdrawal_reads_wdaycaremon_and_the_appended_slot(world):
    rng = random.Random(13)
    boarded = _mon(rng, 0x15, nick="DAYC", ot_id=0x1234)
    r = world.ram
    world.bus[r["wDayCareMon"]:r["wDayCareMon"] + 44] = codec.encode_party_mon(boarded)
    world.bus[r["wDayCareInUse"]] = 1
    world.connect()
    world.bus[r["wMoveMonType"]] = 2  # DAYCARE_TO_PARTY
    world.fire("daycare_withdraw")
    world.fire("move_mon")
    world.seed_party(world.party() + [boarded])
    world.step(3)
    b2p = world.events("box_to_party")
    assert len(b2p) == 1 and b2p[0]["key"] == codec.key(world.party()[2])
    assert world.events("capture") == []
    mon = dict(world.parts.reads.read_daycare_mon().items())
    assert mon["species"] == 0x15


# ── signals: GUID sentinel and the bank check on every ROMX site ─────────────────────────

def _signals_harness(on_bus_exec_override=None):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    rom = synth_rom()
    bus: dict[int, int] = {}
    regs = {"PC": 0, "SP": 0xDFF0, "H": 0, "L": 0, "F": 0}
    hooks: dict[str, tuple] = {}

    def read_u8(addr, domain):
        addr = int(addr)
        if str(domain) == "ROM":
            return rom[addr]
        if addr < 0x8000:
            bank = bus.get(PROFILE[TITLE]["ram"]["hLoadedROMBank"], 1)
            flat = addr if addr < 0x4000 else bank * 0x4000 + (addr - 0x4000)
            return rom[flat] if flat < len(rom) else 0
        return bus.get(addr, 0)

    def on_bus_exec(fn, addr, name, domain):
        if on_bus_exec_override:
            return on_bus_exec_override(fn, addr, name)
        hooks[str(name)] = (fn, int(addr))
        return len(hooks)

    io = lua.table(read_u8=read_u8,
                   read_range=lambda a, n, d: lua.table(*[read_u8(int(a) + i, d) for i in range(int(n))]),
                   on_bus_exec=on_bus_exec, unregister=lambda i: None, framecount=lambda: 1,
                   register=lambda name: regs[str(name)])
    S = lua.eval(f'dofile("{SIGNALS}")')
    profile = lua.table_from(PROFILE[TITLE], recursive=True)
    sites = lua.table_from(SITES[TITLE]["sites"], recursive=True)
    return lua, S, profile, sites, io, bus, regs, hooks


def test_an_all_zero_guid_registration_is_a_failure():
    calls = {"n": 0}

    def override(fn, addr, name):
        calls["n"] += 1
        return "00000000-0000-0000-0000-000000000000" if calls["n"] == 3 else f"id-{calls['n']}"

    lua, S, profile, sites, io, *_ = _signals_harness(override)
    with pytest.raises(lupa.LuaError, match="engine signal registration failed"):
        S.new(profile, sites, io)


def test_every_romx_site_drops_a_hit_from_the_wrong_bank():
    lua, S, profile, sites, io, bus, regs, hooks = _signals_harness()
    svc = S.new(profile, sites, io)
    banked = [k for k, s in SITES[TITLE]["sites"].items() if s["bank"] > 0]
    assert len(banked) >= 30
    for kind in banked:
        site = SITES[TITLE]["sites"][kind]
        pc = site["address"] + site.get("capture_offset", 0)
        regs["PC"] = pc
        bus[PROFILE[TITLE]["ram"]["hLoadedROMBank"]] = site["bank"] + 1
        hooks[f"SLink-gen1-{kind}"][0]()
        assert dict(svc.status(svc).items())["pending"] == 0, f"{kind} fired from the wrong bank"
        bus[PROFILE[TITLE]["ram"]["hLoadedROMBank"]] = site["bank"]
        if kind == "bag_received":
            continue  # filtered on HL/carry/item; the bank check is what is under test
        hooks[f"SLink-gen1-{kind}"][0]()
        st = dict(svc.status(svc).items())
        assert st.get("failed") is None and st["pending"] == 1, f"{kind}: {st}"
        svc.drain(svc)
    assert svc.registered == len(SITES[TITLE]["sites"])


# ── rom.lua on the 35-byte stride and the species index ──────────────────────────────────

def test_base_stats_read_at_the_pack_stride_and_nondex_from_the_index(world):
    rom = world.parts.rom
    assert rom.stride == 35
    rec = dict(rom.base_stats_for(1).items())  # RHYDON, dex 112, BaseStats record
    assert rec["dex"] == 112 and rec["hp"] == 105 and rec["growth_rate"] == 3
    assert rom.natdex(1) == 112
    assert rom.natdex(0xB5) == 0, "MISSINGNO is the real dex 0 on pureRGB"
    missing = dict(rom.base_stats_for(0xB5).items())
    assert missing["hp"] == 255 and missing["growth_rate"] == 5 and missing["pack"] is True
    torched = dict(rom.base_stats_for(0x1F).items())  # spirit form: NonDex record, base dex 103
    assert rom.natdex(0x1F) == 103 and torched["hp"] == 95
    got, why = rom.base_stats(0)
    assert got is None and "out of range" in why


def test_the_pack_charmap_is_the_one_glyph_object(world):
    reads = world.parts.reads
    cm = reads.charmap
    assert cm.terminator == 0x50 and cm.glyphs[0xE9] == "→" and cm.glyphs[0x33] == "like"
    assert reads.decode_name(world.lua.table(0x80, 0x33, 0x50)) == "Alike"
    assert cm.codes["A"] == 0x80 and cm.codes["-"] == 0xE3
    assert world.lua.eval("function(a, b) return a == b end")(world.parts.profile.charmap, cm)


# ── hello gate on wGameInternalVersion (M2-b) ────────────────────────────────────────────

def test_hello_is_held_while_the_save_stamp_differs_from_the_pinned_version(world):
    """The updater saves before stamping: a mismatched stamp is not a live save yet. The pack
    has no derived.game_internal_version today, so the gate is exercised by injecting one."""
    world.parts.profile.derived.game_internal_version = 5
    world.bus[world.ram["wGameInternalVersion"]] = 3
    world.connected = True
    world.step(3)
    assert world.events("hello") == [] and any("hello held" in line for line in world.logs)
    world.bus[world.ram["wGameInternalVersion"]] = 5
    world.step()
    assert len(world.events("hello")) == 1


def test_a_pending_battle_write_lands_at_the_no_move_reentry_and_moves_pc_to_the_loop_head(world):
    """pureRGB's MOVE-menu cancel re-enters MainInBattleLoop.loopNoMoveSelected (below the HP
    check). The client writes the faint there and moves PC to the loop head's HP check so the
    engine faints the battler on this very re-entry (probe_gen1_loop_reentry, 2026-09-18)."""
    world.connect()
    world.step(60)
    world.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world.fire("wild_begin")
    world.step()
    key = codec.key(world.party()[0])
    world.reply({"cmd": "force_faint", "key": key})
    world.step(3)
    assert world.bus[world.ram["wBattleMonHP"]] != 0 or world.bus[world.ram["wBattleMonHP"] + 1] != 0
    world.fire("battle_loop_no_move")
    assert world.bus[world.ram["wBattleMonHP"]] == 0 and world.bus[world.ram["wBattleMonHP"] + 1] == 0
    assert world.bus[world.ram["wPlayerSelectedMove"]] == 0xFF
    head = SITES[world.title]["sites"]["battle_loop_head"]
    assert world.set_registers == [("PC", head["address"] + head.get("capture_offset", 0))]
    # nothing pending => the re-entry hook is inert and never touches PC
    world.fire("battle_loop_no_move")
    assert len(world.set_registers) == 1
