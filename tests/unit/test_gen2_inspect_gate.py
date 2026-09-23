"""MODEL/SOURCE unit and lupa coverage for the P3b.3a live inspect gate -- no emulator, no
cartridge. Two things are exercised:

  1. lua/tests/gen2_inspect_gate.lua under lupa: its pure functions over a fake `api`, and the WHOLE
     gate (top-level wrapper included) on tests/unit/test_gen2_scripted_gate.py's synthetic
     cartridge (QualifySim: title -> CONTINUE -> confirmation -> the saved map). That proves the
     checkpoint needs the source-qualified CONTINUE arrival, not just decodable party bytes, that the
     wrapper keeps the runner's speed, and that the printed capture carries its frame/domain/ranges.
  2. tests/live/test_gen2_new_gates.py's importable verifier: the COMPLETE gate output is fed through
     verify_capture (the actual live consumer), and each binding -- badges, capture provenance, same
     bytes, decode frame, the qualification-receipt identity -- is shown to refuse its falsifier.

Passing here is authoring/MODEL evidence only, never PHYSICAL evidence -- see
tests/live/test_gen2_new_gates.py for the cartridge lane this gate is meant to run under.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from lupa.lua54 import LuaError, LuaRuntime

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from run_gb_gate import describe_gen2  # noqa: E402

from server.adapters import gen2_codec as codec  # noqa: E402
from tests.live import test_gen2_new_gates as live  # noqa: E402
from tests.unit.test_gen2_scripted_gate import QualifySim, context, make_root, qualify_env  # noqa: E402
from tools import fixture_qualification as qualification  # noqa: E402

GATE = REPO / "lua/tests/gen2_inspect_gate.lua"
TITLE = "crystal"
ROM_SHA1 = describe_gen2(TITLE)["rom_sha1"]
RESULT = "patch/build/gen2_inspect_gate_result.txt"
# The pinned rgbds symbol artifact per title, as the gate's own G.SYM_ARTIFACT resolves.
SYM_ARTIFACT = {"crystal": "pokecrystal", "gold": "pokegold", "silver": "pokesilver"}


def profile_wrapper(title=TITLE):
    return json.loads((REPO / f"data/games/gen2_{title}/profile.json").read_text(encoding="utf-8"))


def profile_row(title=TITLE):
    return profile_wrapper(title)["titles"][title]


# =================================================================================================
# Part 1a: pure gate functions with a fake BizHawk `api`
# =================================================================================================


def wram_offset(addr, bank):
    return addr - 0xC000 if addr < 0xD000 else bank * 0x1000 + addr - 0xD000


class FakeApi:
    """A fake BizHawk: a flat WRAM bytearray (8 banks x 4KiB, matching the real domain size), a
    flat CartRAM bytearray and a frame counter."""

    def __init__(self, lua, *, cart_size=0x8000):
        self.lua = lua
        self.bus = bytearray(0x8000)
        self.cart = bytearray(cart_size)
        self.frame = 0

    def table(self):
        return self.lua.table(read_range=self.read_range, domain_size=self.domain_size,
                              framecount=lambda: self.frame)

    def read_range(self, addr, n, domain):
        addr, n = int(addr), int(n)
        source = self.bus if str(domain) == "WRAM" else self.cart if str(domain) == "CartRAM" else None
        assert source is not None, f"unexpected domain {domain!r}"
        return self.lua.table_from(list(source[addr:addr + n]))

    def domain_size(self, domain):
        return {"WRAM": len(self.bus), "CartRAM": len(self.cart)}[str(domain)]


def put(bus_or_cart, profile, symbol, data, *, cart=False):
    addr = profile["ram"][symbol]
    if cart:
        bank = profile["sram_bank"][symbol]
        flat = bank * 0x2000 + addr - 0xA000
        bus_or_cart[flat:flat + len(data)] = data
        return flat
    bank = profile["ram_bank"][symbol]
    offset = wram_offset(addr, bank)
    bus_or_cart[offset:offset + len(data)] = data
    return offset


def _fresh_party_record(species_id=158, ot_id=0x1234, level=5):
    """A minimal but structurally valid 48-byte party record: enough non-zero DV/level/HP fields
    that decoding produces a real record rather than an all-zero degenerate one."""
    record = bytearray(48)
    record[0] = species_id            # MON_SPECIES
    record[1] = 0                     # MON_ITEM
    record[2:6] = bytes((1, 2, 3, 4))  # MON_MOVES
    record[6:8] = ot_id.to_bytes(2, "big")  # MON_OT_ID
    record[8:11] = (135).to_bytes(3, "big")  # MON_EXP
    record[21:23] = (0x2AAA).to_bytes(2, "big")  # MON_DVS: shiny-and-female-leaning vector
    record[31] = level                 # MON_LEVEL
    record[34:36] = (20).to_bytes(2, "big")   # MON_HP
    record[36:38] = (20).to_bytes(2, "big")   # MON_MAXHP
    for at in range(38, 48, 2):
        record[at:at + 2] = (10).to_bytes(2, "big")  # MON_ATK..MON_SDF
    return bytes(record)


def place_one_mon_party(bus, profile, *, species_id=158, ot_id=0x1234):
    put(bus, profile, "wPartyCount", bytes([1]))
    put(bus, profile, "wPartySpecies", bytes([species_id, 255]))
    put(bus, profile, "wPartyMons", _fresh_party_record(species_id=species_id, ot_id=ot_id))
    put(bus, profile, "wPartyMonOTs", bytes([0x80] + [0xAA] * 10))
    put(bus, profile, "wPartyMonNicknames", bytes([0x81] + [0xBB] * 10))


def place_all_boxes_empty(cart, profile):
    """count=0, terminator immediately after; the rest of the (zeroed) boxes is unused."""
    put(cart, profile, "sBox", bytes([0, 255]), cart=True)
    for entry in profile["storage_boxes"]:
        flat = entry["bank"] * 0x2000 + entry["addr"] - 0xA000
        cart[flat:flat + 2] = bytes([0, 255])


@pytest.fixture
def gate():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    module = lua.eval("dofile")(GATE.as_posix())
    return lua, module


def test_wram_offset_matches_pan_docs_bank_windows(gate):
    _lua, G = gate
    assert G.wram_offset(0, 0xC000, 1) == 0
    assert G.wram_offset(0, 0xCFFF, 1) == 0xFFF
    assert G.wram_offset(1, 0xD000, 1) == 0x1000
    assert G.wram_offset(7, 0xDFFF, 1) == 0x7FFF
    with pytest.raises(LuaError):
        G.wram_offset(0, 0xD000, 1)  # bank 0 does not cover the switchable window
    for bank, addr, n in ((0, 0xC000, 1), (0, 0xCFFF, 1), (1, 0xD000, 1), (7, 0xDFFF, 1), (3, 0xD123, 0x40)):
        assert live.wram_offset(bank, addr, n) == G.wram_offset(bank, addr, n)
    with pytest.raises(AssertionError):
        live.wram_offset(0, 0xD000, 1)


def test_io_binding_reads_the_right_wram_bank_and_cartram_passthrough(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    place_one_mon_party(api.bus, profile_row())
    api.cart[100] = 0x42
    io_ = G.io(api.table(), profile)
    party_addr = profile_row()["ram"]["wPartyCount"]
    assert io_.read_range(party_addr, 1, "System Bus")[1] == 1  # party count we placed
    assert io_.read_range(100, 1, "CartRAM")[1] == 0x42
    assert io_.bank_valid(profile_row()["ram_bank"]["wPartyCount"], party_addr, 1) is True
    assert io_.bank_valid(99, party_addr, 1) is False
    with pytest.raises(LuaError):
        io_.read_range(0xC001, 1, "System Bus")  # not a profile symbol address


def test_dump_records_the_physical_domain_offset_and_logical_address(gate):
    """R4 #7: the party is read from flat WRAM at a recorded offset; the bus address/bank ride along."""
    lua, G = gate
    row = profile_row()
    profile = lua.table_from(row, recursive=True)
    api = FakeApi(lua)
    place_one_mon_party(api.bus, row)
    api.cart[0x7FFF] = 0x99
    api.frame = 77
    dump = G.dump(api.table(), profile)
    address, bank = row["ram"]["wPartyCount"], row["ram_bank"]["wPartyCount"]
    length = row["ram"]["wPartyMonNicknamesEnd"] - address
    assert dump.frame == 77
    assert (dump.party.domain, dump.party.bus_domain, dump.party.bank, dump.party.address, dump.party.length) == (
        "WRAM", "System Bus", bank, address, length)
    assert dump.party.offset == wram_offset(address, bank)
    assert dump.party.hex == bytes(api.bus[dump.party.offset:dump.party.offset + length]).hex()
    assert (dump.cartram.domain, dump.cartram.address, dump.cartram.length) == ("CartRAM", 0, 0x8000)
    assert dump.cartram.hex[-2:] == "99"


def test_raw_fields_reads_badges_boxnum_and_battle_independently(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    row = profile_row()
    put(api.bus, row, "wJohtoBadges", bytes([0x03]))
    put(api.bus, row, "wKantoBadges", bytes([0x00]))
    put(api.bus, row, "wCurBox", bytes([5]))
    put(api.bus, row, "wBattleMode", bytes([2]))
    put(api.bus, row, "wOtherTrainerClass", bytes([9]))
    put(api.bus, row, "wOtherTrainerID", bytes([1]))
    raw = G.raw_fields(profile, G.io(api.table(), profile))
    assert raw.badges.johto == 3 and raw.badges.kanto == 0
    assert raw.boxnum == 5
    assert raw.battle.mode == 2 and raw.battle.trainer_class == 9 and raw.battle.trainer_id == 1


def test_raw_fields_omits_trainer_fields_outside_battle(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    row = profile_row()
    put(api.bus, row, "wJohtoBadges", bytes([0, 0]))
    put(api.bus, row, "wCurBox", bytes([0]))
    put(api.bus, row, "wBattleMode", bytes([0]))
    raw = G.raw_fields(profile, G.io(api.table(), profile))
    assert raw.battle.mode == 0
    assert raw.battle.trainer_class is None


@pytest.mark.parametrize("dv_word,ratio,gender,shiny", [
    (0x2AAA, 31, "male", True),       # attack=2 (bit1 set), def/spd/spc=10 -> shiny; combined=42>31 -> male
    (0x0000, 31, "female", False),    # all-zero DVs: not shiny; combined=0<=31 -> female
    (0x0000, 255, "genderless", False),
    (0x0000, 254, "female", False),
    (0x0000, 0, "male", False),
])
def test_gender_and_shiny_matches_source_formula(gate, dv_word, ratio, gender, shiny):
    _lua, G = gate
    assert tuple(G.gender_and_shiny(dv_word, ratio)) == (gender, shiny)


# =================================================================================================
# Part 1b: the whole gate on the synthetic cartridge (QualifySim)
# =================================================================================================


class InspectSim(QualifySim):
    """QualifySim booted from a structurally valid save: one decodable party mon (loaded at CONTINUE,
    before the confirmation, as TryLoadSaveFile does), empty boxes, set badges. `confirm=False` keeps
    the game on the CONTINUE confirmation screen forever, with the party decodable from the very first
    frame (title and menus included): valid, stable party bytes, never the overworld."""

    def __init__(self, lua, title=TITLE, *, confirm=True, johto=0x03, card_id_col=5):
        self.confirm, self.johto = confirm, johto
        self.card_id_col = card_id_col
        self.player_id = 0x0034          # 5 digits with a leading zero: "00052"
        self.player_name = "GOLD"
        super().__init__(lua, title, "town")
        self.cart[:] = bytes(len(self.cart))
        place_all_boxes_empty(self.cart, self.prof)
        self.booted = bytes(self.cart[:0x8000])
        self.speeds = []

    def load(self):
        place_one_mon_party(self.wram, self.prof)
        self.put("wJohtoBadges", [self.johto, 0])
        self.put("wCurBox", [0])
        self.put("wNumBalls", [0, 0xFF])
        # Trainer Card sources: wPlayerID is a 2-byte word, wPlayerName an '@'-terminated name.
        self.put("wPlayerID", [self.player_id >> 8 & 0xFF, self.player_id & 0xFF])
        self.put("wPlayerName", [self.enc[c] for c in self.player_name] + [self.enc["@"]] + [0] * 10)

    def site(self, label):
        """A source label's (bank, address) from the same rgbds symbol artifact the gate parses."""
        symbol = context(self.title).symbol(label)
        return symbol.bank, symbol.address

    def lead_mon(self):
        species_id = self.get("wPartySpecies")
        dv_word = int.from_bytes(self.wram[self.offset("wPartyMons", 21):self.offset("wPartyMons", 23)], "big")
        return species_id, dv_word

    # --- scripted display screens (the gate's normal-button navigation) ---------------------------

    def start_menu_flow(self):
        """START menu: the gate picks the Status entry (the player's name) or #MON, and B exits."""
        while True:
            items = ["#DEX", "#MON", "PACK", self.player_name, "SAVE", "OPTION", "EXIT"]
            chosen = yield from self.menu_select("start_menu", items, at=(8, 0))
            if chosen == self.player_name:
                yield from self.card_screen()
                continue
            if chosen == "#MON":
                yield from self.party_flow()
                continue
            self.clear()
            return                      # EXIT, or a B press

    def menu_select(self, kind, items, at=(0, 0)):
        """A boxed vertical menu (▶ cursor + borders, so the gate's parse_menu sees it) that returns
        the chosen label on A, or "EXIT" on B. Unlike Sim.menu it does not assert the choice."""
        self.clear()
        x0, y0 = at
        width = max(len(self.tokens(item)) for item in items) + 2
        x1, y1 = x0 + 1 + width, y0 + 2 * len(items)
        self.box(x0, y0, x1, y1)
        cursor = 0

        def render():
            for index, item in enumerate(items):
                x, y = x0 + 1, y0 + 1 + 2 * index
                self.rows[y][x] = "▶" if index == cursor else " "
                self.text_at(x + 1, y, item)
            self.draw()

        render()
        yield from self.wait(2)
        if kind and kind in self.sites:
            self.fire(kind)
        while True:
            got = yield
            for button, delta in (("Up", -1), ("Down", 1)):
                if button in got.edges and 0 <= cursor + delta < len(items):
                    cursor += delta
                    render()
            if "A" in got.edges:
                self.clear()
                return items[cursor]
            if "B" in got.edges:
                self.clear()
                return "EXIT"

    def card_screen(self):
        """Trainer Card page 1: the head cells TrainerCard_PrintTopHalfOfCard writes (name at (7,2),
        the 5-digit wPlayerID at (5,4)). TrainerCard_Page1_Joypad runs once per frame until B."""
        self.clear()
        self.text_at(7, 2, self.player_name)
        self.text_at(self.card_id_col, 4, "".join(str(self.player_id // 10 ** (4 - i) % 10) for i in range(5)))
        self.draw()
        bank, address = self.site("TrainerCard_Page1_Joypad")
        while True:
            self.run_at(bank, address)
            got = yield
            if "B" in got.edges:
                self.clear()
                return

    def party_flow(self):
        """#MON: the party menu (no ▶ tile), then the mon submenu (STATS default), then STATS."""
        selected = yield from self.party_menu()
        if selected != "select":
            return
        choice = yield from self.menu_select("mon_submenu", ["STATS", "SWITCH", "CANCEL"], at=(6, 6))
        if choice == "STATS":
            yield from self.stats_screen()

    def party_menu(self):
        self.clear()
        for index in range(self.get("wPartyCount")):
            self.text_at(1, 1 + 2 * index, "PARTY MON")
        self.textbox("Choose a POKéMON.")
        self.draw()
        while True:
            got = yield
            if "A" in got.edges:
                self.clear()
                return "select"
            if "B" in got.edges:
                self.clear()
                return "cancel"

    def draw_stats(self, page):
        """The stats-screen head cells PlaceGenderChar/PlaceShinyIcon write, plus the GREEN page's
        item line. A genderless or non-shiny mon leaves the blank cell (ClearTilemap's ' ')."""
        self.clear()
        species_id, dv_word = self.lead_mon()
        ratio = json.loads((REPO / f"data/games/gen2_{self.title}/species_index.json")
                           .read_text(encoding="utf-8"))["species"][str(species_id)]["gender_ratio"]
        gender, shiny = live.gender_and_shiny(dv_word, ratio)
        if gender in ("male", "female"):
            self.rows[0][18] = "♂" if gender == "male" else "♀"
        if shiny:
            self.rows[0][19] = "⁂"
        if page == "green":
            self.text_at(0, 8, "ITEM")
            self.text_at(8, 8, "---")
        self.draw()

    def stats_screen(self):
        """MonStatsJoypad runs once per frame; RIGHT/A advance the page (A quits on the BLUE page)."""
        order = {"pink": "green", "green": "blue", "blue": "pink"}
        page = "pink"
        self.draw_stats(page)
        bank, address = self.site("MonStatsJoypad")
        while True:
            self.run_at(bank, address)
            got = yield
            if "B" in got.edges:
                self.clear()
                return
            if "Right" in got.edges:
                page = order[page]
                self.draw_stats(page)
            elif "A" in got.edges:
                if page == "blue":      # the BLUE page's A exits (engine/pokemon/stats_screen.asm:382-386)
                    self.clear()
                    return
                page = order[page]
                self.draw_stats(page)

    def save(self):
        yield from self.start_menu_flow()

    def game(self):
        if self.confirm:
            yield from super().game()
            return
        self.load()
        yield from self.wait(20)
        self.clear()
        yield from self.until("Start", "title")
        yield from self.wait(2)
        yield from self.menu("main_menu", ["CONTINUE", "NEW GAME", "OPTION"], "CONTINUE")
        self.fire("continue")
        yield from self.wait(20)
        while True:   # the confirmation never accepts: no Check1Pass, no FinishContinueFunction
            self.fire("continue_confirm")
            yield

    def install(self, env):
        super().install(env)
        glob = self.lua.globals()
        glob.client = self.lua.table_from({"speedmode": self.speeds.append, "saveram": self.saveram,
                                           "exit": lambda: setattr(self, "exited", True)})


def inspect_root(tmp_path, title=TITLE):
    root = make_root(tmp_path, title)
    for rel in ("lua/tests/test_gen2_scripted_gate.lua", f"data/games/gen2_{title}/species_index.json",
                f"data/games/gen2_{title}/item_names.json", f"data/gen2/{SYM_ARTIFACT[title]}.sym"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    return root


def inspect_env(root, title=TITLE, stage="boot", **case_changes):
    spec, env = qualify_env(root, title, "town", stage)
    if case_changes:
        case = json.loads(env["SLINK_GEN2_FIXTURE_CASE"])
        case.update(case_changes)
        env["SLINK_GEN2_FIXTURE_CASE"] = json.dumps(case)
    return spec, env


def run_top_level(root, env, sim):
    """The gate exactly as EmuHawk runs it: the top-level wrapper, not the library entry point."""
    sim.install(env)
    with pytest.raises(LuaError, match="slink-gate-finished"):
        sim.lua.execute(GATE.read_text(encoding="utf-8"))
    assert sim.exited
    return (root / RESULT).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def passing_run(tmp_path_factory):
    root = inspect_root(tmp_path_factory.mktemp("inspect"))
    _spec, env = inspect_env(root)
    sim = InspectSim(LuaRuntime(unpack_returned_tuples=True))
    text = run_top_level(root, env, sim)
    return text, sim


def test_gate_reaches_a_qualified_checkpoint_and_the_live_verifier_accepts_its_complete_output(passing_run):
    """Addendum (a): the COMPLETE printed output through the actual live consumer."""
    text, _sim = passing_run
    assert text.strip().splitlines()[-1].startswith("RESULT: PASS"), text
    assert "CHECKPOINT reached" in text
    py_party = live.verify_capture(text, profile_wrapper(), TITLE)
    assert live.identity_matches(py_party, 0x1234)
    badges = live.tag_json(text, "BADGES_LUA")
    assert {"raw_hex", "evidence", "snapshot_qualified"} <= set(badges)   # reads.lua's full shape


def test_wrapper_keeps_the_runners_speed(passing_run):
    """R4 #5 / addendum (e): run_gb_gate writes SpeedPercent=100; the gate must not override it."""
    _text, sim = passing_run
    assert sim.speeds == []


def test_valid_party_on_the_continue_confirmation_screen_never_reaches_the_checkpoint(tmp_path):
    """R4 #4 / addendum (b): the party is already decodable before CONTINUE is confirmed
    (C engine/menus/intro_menu.asm:338-348,429-442; G :251-260,313-326)."""
    root = inspect_root(tmp_path)
    _spec, env = inspect_env(root, max_frames=3000, max_phase_frames=600)
    sim = InspectSim(LuaRuntime(unpack_returned_tuples=True), confirm=False)
    text = run_top_level(root, env, sim)
    assert text.strip().splitlines()[-1].startswith("RESULT: FAIL"), text
    assert "CHECKPOINT reached" not in text and "DUMP " not in text
    assert "no qualified overworld arrival" in text


def test_a_non_boot_qualification_binding_refuses_before_any_input(tmp_path):
    root = inspect_root(tmp_path)
    _spec, env = inspect_env(root, stage="resave")
    sim = InspectSim(LuaRuntime(unpack_returned_tuples=True))
    text = run_top_level(root, env, sim)
    assert "bad environment" in text.strip().splitlines()[-1] and sim.inputs == []


def test_a_wrong_rom_binding_refuses_before_any_input(tmp_path):
    root = inspect_root(tmp_path)
    _spec, env = inspect_env(root)
    env["SLINK_GEN2_ROM_SHA1"] = "0" * 40
    sim = InspectSim(LuaRuntime(unpack_returned_tuples=True))
    text = run_top_level(root, env, sim)
    assert "bad environment" in text.strip().splitlines()[-1] and sim.inputs == []


# =================================================================================================
# Part 2: tests/live/test_gen2_new_gates.py's verifier -- each binding refuses its falsifier
# =================================================================================================


def retag(text, tag, change):
    """Rewrite the first `TAG <json>` line through `change(value) -> value`."""
    lines = text.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith(tag + " "))
    lines[at] = tag + " " + json.dumps(change(json.loads(lines[at][len(tag) + 1:])))
    return "\n".join(lines) + "\n"


def _flip_hex(value, at):
    raw = bytearray(bytes.fromhex(value))
    raw[at] ^= 0x01
    return raw.hex()


def _set(path, value):
    def change(obj):
        target = obj
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value(target[path[-1]]) if callable(value) else value
        return obj
    return change


def test_one_badge_byte_mismatch_fails_the_verifier(passing_run):
    text, _sim = passing_run
    for tag, field in (("RAW_BADGES", "kanto"), ("BADGES_LUA", "johto")):
        with pytest.raises(AssertionError, match="badge"):
            live.verify_capture(retag(text, tag, _set([field], lambda v: v ^ 1)), profile_wrapper(), TITLE)


@pytest.mark.parametrize("tag,change,match", [
    ("DUMP", _set(["party", "domain"], "System Bus"), "party capture provenance"),
    ("DUMP", _set(["party", "offset"], lambda v: v + 1), "party capture provenance"),
    ("DUMP", _set(["party", "bank"], lambda v: v + 1), "party capture provenance"),
    ("DUMP", _set(["party", "address"], lambda v: v + 1), "party capture provenance"),
    ("DUMP", _set(["party", "length"], lambda v: v - 1), "party capture provenance"),
    ("DUMP", _set(["party", "bus_domain"], "WRAM"), "party capture provenance"),
    ("DUMP", _set(["cartram", "address"], 1), "CartRAM capture provenance"),
    ("DUMP", _set(["cartram", "length"], 0x4000), "CartRAM capture provenance"),
    ("DUMP", _set(["cartram", "domain"], "SRAM"), "CartRAM capture provenance"),
    ("DUMP", _set(["frame"], 0), "capture frame"),
    ("DECODE_FRAME", lambda frame: frame + 1, "capture frame"),
    # A capture from another frame: the bytes PYDEC decodes are not the bytes Lua decoded.
    ("DUMP", _set(["party", "hex"], lambda v: _flip_hex(v, 40)), "other bytes"),
    ("DUMP", _set(["cartram", "hex"], lambda v: _flip_hex(v, _real_layout().active_box[0] + 100)), "other bytes"),
    ("BOX_LUA_3", _set(["bank"], lambda v: v ^ 1), "another CartRAM range"),
])
def test_capture_metadata_and_same_bytes_bindings_refuse(passing_run, tag, change, match):
    """R4 #7 / addendum (f): domain, range, length, frame and same-capture falsifiers."""
    text, _sim = passing_run
    with pytest.raises(AssertionError, match=match):
        live.verify_capture(retag(text, tag, change), profile_wrapper(), TITLE)


def test_a_checkpoint_that_was_not_reached_fails_the_verifier(passing_run):
    text, _sim = passing_run
    with pytest.raises(AssertionError, match="checkpoint"):
        live.verify_capture(text.replace("CHECKPOINT reached", "CHECKPOINT not reached"), profile_wrapper(), TITLE)


def test_compare_badges_uses_the_declared_fields_of_a_complete_reads_lua_record():
    """R4 #1: reads.lua adds raw_hex/evidence/snapshot_qualified; RAW_BADGES has johto/kanto only."""
    lua_record = {"johto": 3, "kanto": 0, "raw_hex": "0300", "evidence": "RAW_RAM_ONLY", "snapshot_qualified": False}
    live.compare_badges(lua_record, {"johto": 3, "kanto": 0}, where="control")
    with pytest.raises(AssertionError, match="kanto"):
        live.compare_badges(lua_record, {"johto": 3, "kanto": 1}, where="mismatch")
    with pytest.raises(AssertionError, match="raw_hex"):
        live.compare_badges({**lua_record, "raw_hex": "0301"}, {"johto": 3, "kanto": 0}, where="raw")


def _real_layout():
    return codec.Gen2Layout.from_profile(profile_wrapper(), TITLE)


def _one_mon_collection(layout, *, species_id=158, ot_id=0x1234, mutate_byte=None):
    record = bytearray(_fresh_party_record(species_id=species_id, ot_id=ot_id))
    if mutate_byte is not None:
        offset, xor = mutate_byte
        record[offset] ^= xor
    body = bytearray(layout.addresses["wPartyMonNicknamesEnd"] - layout.addresses["wPartyCount"])
    body[0], body[1], body[2] = 1, species_id, 255
    records = layout.addresses["wPartyMon1"] - layout.addresses["wPartyCount"]
    ots = layout.addresses["wPartyMonOTs"] - layout.addresses["wPartyCount"]
    nicks = layout.addresses["wPartyMonNicknames"] - layout.addresses["wPartyCount"]
    body[records:records + 48] = record
    body[ots:ots + 11] = bytes([0x80] + [0xAA] * 10)
    body[nicks:nicks + 11] = bytes([0x81] + [0xBB] * 10)
    return codec.decode_party(bytes(body), layout)


def _as_lua_shaped(py_collection):
    """What json.loads(the gate's own line) would hand the comparator: a plain dict."""
    return json.loads(json.dumps(py_collection))


def test_compare_collection_agrees_on_an_identical_decode():
    collection = _one_mon_collection(_real_layout())
    live.compare_collection(_as_lua_shaped(collection), collection, where="identity control")


def test_compare_collection_fails_on_a_single_mutated_byte():
    layout = _real_layout()
    baseline = _one_mon_collection(layout)
    mutated = _one_mon_collection(layout, mutate_byte=(7, 0xFF))  # inside MON_OT_ID
    with pytest.raises(AssertionError):
        live.compare_collection(_as_lua_shaped(baseline), mutated, where="mutated-byte control")


def test_compare_collection_fails_on_a_mismatched_count():
    collection = _one_mon_collection(_real_layout())
    lua_shaped = _as_lua_shaped(collection)
    lua_shaped["count"], lua_shaped["mons"] = 0, []
    with pytest.raises(AssertionError, match="count disagrees"):
        live.compare_collection(lua_shaped, collection, where="count control")


# --- R4 #6 / addendum (c): the expected identity comes from the fixture's qualification receipt ---

RECEIPT_ROM_SHA1 = hashlib.sha1(b"rom").hexdigest()
RECEIPT_ROUTE_FACTS = {"fingerprint": hashlib.sha256(b"route fingerprint").hexdigest()}
RECEIPT_ROUTE_FACTS_BYTES = json.dumps(RECEIPT_ROUTE_FACTS, sort_keys=True).encode()


@pytest.fixture
def receipt_source_facts(monkeypatch):
    """A synthetic source authority independent of the receipt under test."""
    def context(title, root):
        assert title == "crystal"
        return SimpleNamespace(source_record=lambda: {"rom_sha1": RECEIPT_ROM_SHA1})

    def facts(title, root):
        assert title == "crystal"
        return RECEIPT_ROUTE_FACTS

    monkeypatch.setattr(live.gen2_source_data, "load_context", context)
    monkeypatch.setattr(live.gen2_fixtures, "route_facts", facts)


def write_receipt(repo, name, data, player_id, *, report=None, row=None, stage=None,
                  provenance=None):
    path = repo / live.RECEIPTS / f"{name}.qualification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for role, content in {"fixture": data, "profile": b"profile", "rom": b"rom",
                          "route_facts": RECEIPT_ROUTE_FACTS_BYTES,
                          "played_receipt": b"played receipt"}.items():
        inputs[role] = repo / f"{name}.{role}"
        inputs[role].write_bytes(content)
    outputs = {}
    for role, content in {"boot:game_witness": b"boot witness", "resave:fixture": data,
                          "resave:save_witness": b"save witness",
                          "resave:reload_witness": b"reload witness"}.items():
        outputs[role] = repo / f"{name}.{role.replace(':', '.')}"
        outputs[role].write_bytes(content)

    def callback(context):
        evidence = {"oracle": "model control"}
        if context.stage == "qualify":
            evidence.update({"player_id": str(player_id), **(stage or {})})
        stage_outputs = {role.split(":", 1)[1]: output for role, output in outputs.items()
                         if role.startswith(context.stage + ":")}
        return qualification.StageReceipt(context.stage, context.fingerprint, "PASS",
                                          evidence=evidence, outputs=stage_outputs)

    source = {"title": "crystal", "rom_sha1": RECEIPT_ROM_SHA1,
              "scope": "candidate fixture",
              "route_facts_sha256": hashlib.sha256(RECEIPT_ROUTE_FACTS_BYTES).hexdigest()}
    source.update(provenance or {})
    case = qualification.FixtureCase(name, inputs, source)
    body = qualification.qualify_fixtures([case], dict.fromkeys(qualification.FULL_CHAIN, callback),
                                          scope="full", attempt_id=f"test-{name}")
    assert body["passed"] is True
    body["fixtures"][0].update(row or {})
    body.update(report or {})
    path.write_text(json.dumps(body), encoding="utf-8")


TOWN, OT2 = b"crystal_town bytes" * 8, b"crystal_town_ot2 bytes" * 8


def test_qualified_identity_binds_the_staged_bytes_and_the_receipts_ot(tmp_path, receipt_source_facts):
    write_receipt(tmp_path, "crystal_town", TOWN, 0x1234)
    write_receipt(tmp_path, "crystal_town_ot2", OT2, 0x5678)
    assert live.qualified_identity("crystal_town", TOWN, repo=tmp_path) == 0x1234
    assert live.qualified_identity("crystal_town_ot2", OT2, repo=tmp_path) == 0x5678
    # crystal_town's file copied under the crystal_town_ot2 name: refused by the receipt's hash.
    with pytest.raises(AssertionError, match="differ from the qualified candidate"):
        live.qualified_identity("crystal_town_ot2", TOWN, repo=tmp_path)
    # A capture of the town save checked against the ot2 receipt's identity is refused too.
    town_capture = _one_mon_collection(_real_layout(), ot_id=0x1234)
    assert live.identity_matches(town_capture, live.qualified_identity("crystal_town", TOWN, repo=tmp_path))
    assert not live.identity_matches(town_capture, live.qualified_identity("crystal_town_ot2", OT2, repo=tmp_path))


@pytest.mark.parametrize("missing", qualification.FULL_CHAIN)
def test_qualified_identity_refuses_missing_full_chain_stage(tmp_path, receipt_source_facts, missing):
    write_receipt(tmp_path, "crystal_town", TOWN, 0x1234)
    path = tmp_path / live.RECEIPTS / "crystal_town.qualification.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["fixtures"][0]["stages"] = [stage for stage in report["fixtures"][0]["stages"]
                                     if stage["stage"] != missing]
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(AssertionError, match="full-chain"):
        live.qualified_identity("crystal_town", TOWN, repo=tmp_path)


@pytest.mark.parametrize("change,match", [
    (_set(["required_stages"], ["qualify"]), "full-chain"),
    (_set(["errors"], ["late error"]), "errors"),
    (_set(["fixtures", 0, "problems"], ["failed oracle"]), "problems"),
    (_set(["fixtures", 0, "stages", 1, "problems"], ["failed boot"]), "problem-free"),
    (_set(["fixtures", 0, "stages", 1, "fingerprint"], "0" * 64), "fingerprint"),
    (_set(["fixtures", 0, "provenance", "title"], "gold"), "fixture title"),
    (_set(["fixtures", 0, "artifacts", "resave:fixture", "sha256"], "0" * 64), "artifact provenance"),
])
def test_qualified_identity_refuses_broken_full_chain_provenance(tmp_path, receipt_source_facts,
                                                                 change, match):
    write_receipt(tmp_path, "crystal_town", TOWN, 0x1234)
    path = tmp_path / live.RECEIPTS / "crystal_town.qualification.json"
    report = change(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(AssertionError, match=match):
        live.qualified_identity("crystal_town", TOWN, repo=tmp_path)


@pytest.mark.parametrize("changes,match", [
    ({"report": {"passed": False}}, "passed full-chain"),
    ({"report": {"scope": "static"}}, "passed full-chain"),
    ({"report": {"schema": "other"}}, "passed full-chain"),
    ({"row": {"passed": False}}, "single passed row"),
    ({"row": {"name": "crystal_battle"}}, "single passed row"),
    ({"row": {"stages": []}}, "full-chain"),
    ({"stage": {"player_id": "0x1234"}}, "no qualified player ID"),
])
def test_qualified_identity_refuses_an_unqualified_or_misbound_receipt(tmp_path, receipt_source_facts,
                                                                       changes, match):
    write_receipt(tmp_path, "crystal_town", TOWN, 0x1234, **changes)
    with pytest.raises(AssertionError, match=match):
        live.qualified_identity("crystal_town", TOWN, repo=tmp_path)


@pytest.mark.parametrize("provenance,match", [
    ({"title": "gold"}, "fixture title"),
    ({"scope": "static fixture"}, "scope"),
    ({"rom_sha1": "0" * 40}, "ROM SHA-1"),
    ({"route_facts_sha256": "0" * 64}, "route facts"),
])
def test_qualified_identity_refuses_re_signed_wrong_source_values(
        tmp_path, receipt_source_facts, provenance, match):
    # The runner signs these wrong values into every stage fingerprint; shape and chain checks pass.
    write_receipt(tmp_path, "crystal_town", TOWN, 0x1234, provenance=provenance)
    with pytest.raises(AssertionError, match=match):
        live.qualified_identity("crystal_town", TOWN, repo=tmp_path)


@pytest.mark.parametrize("change,match", [
    (_set(["fixtures", 0], None), "single passed row"),
    (_set(["fixtures", 0, "stages", 1], None), "full-chain"),
])
def test_qualified_identity_refuses_non_object_rows_and_stages(
        tmp_path, receipt_source_facts, change, match):
    write_receipt(tmp_path, "crystal_town", TOWN, 0x1234)
    path = tmp_path / live.RECEIPTS / "crystal_town.qualification.json"
    report = change(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(AssertionError, match=match):
        live.qualified_identity("crystal_town", TOWN, repo=tmp_path)


@pytest.mark.parametrize("change,match", [
    (_set(["fixtures", 0, "stages"], lambda stages: list(reversed(stages))), "full-chain"),
    (_set(["fixtures", 0, "stages"], lambda stages: [stages[0], stages[0], *stages[2:]]),
     "full-chain"),
    (_set(["fixtures", 0, "stages", 1, "status"], "FAIL"), "problem-free"),
    (_set(["fixtures", 0, "stages", 1, "status"], "SKIP"), "problem-free"),
])
def test_qualified_identity_refuses_broken_chain_order_or_status(
        tmp_path, receipt_source_facts, change, match):
    write_receipt(tmp_path, "crystal_town", TOWN, 0x1234)
    path = tmp_path / live.RECEIPTS / "crystal_town.qualification.json"
    report = change(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(AssertionError, match=match):
        live.qualified_identity("crystal_town", TOWN, repo=tmp_path)


def test_identity_matches_refuses_the_wrong_fixtures_own_ot():
    layout = _real_layout()
    town = _one_mon_collection(layout, ot_id=0x1234)
    ot2 = _one_mon_collection(layout, ot_id=0x5678)
    assert live.identity_matches(town, 0x1234)
    assert not live.identity_matches(town, 0x5678)
    assert not live.identity_matches(ot2, 0x1234)


def test_gender_and_shiny_matches_the_lua_reimplementation(gate):
    _lua, G = gate
    for dv_word, ratio in ((0x2AAA, 31), (0x0000, 31), (0x0000, 255), (0x0000, 254), (0x0000, 0), (0xF000, 200)):
        assert tuple(G.gender_and_shiny(dv_word, ratio)) == live.gender_and_shiny(dv_word, ratio), (dv_word, ratio)


def test_tag_json_parses_the_gates_own_line_shape():
    text = "  [ok] something\nDUMP {\"frame\": 5, \"party\": {\"domain\": \"WRAM\"}}\nRESULT: PASS x (0 checks failed)\n"
    assert live.tag_json(text, "DUMP") == {"frame": 5, "party": {"domain": "WRAM"}}
    with pytest.raises(AssertionError, match="no 'MISSING' line"):
        live.tag_json(text, "MISSING")


def test_missing_inputs_are_never_silent(tmp_path):
    assert "crystal_town.SaveRAM" in live.fixture_missing_reason("crystal_town", repo=tmp_path)
    assert "crystal_town.qualification.json" in live.receipt_missing_reason("crystal_town", repo=tmp_path)
    assert "crystal" in live.rom_missing_reason("crystal", repo=tmp_path)


def test_inspect_env_binds_the_boot_stage_to_the_staged_bytes():
    spec = live.FIXTURES[0]
    env = live.inspect_env(spec, TOWN)
    qualify = json.loads(env["SLINK_GEN2_QUALIFY"])
    assert qualify["stage"] == "boot" and qualify["stage_fingerprint"] == hashlib.sha256(TOWN).hexdigest()
    assert json.loads(env["SLINK_GEN2_FIXTURE_CASE"])["name"] == spec.name
    assert qualify["facts"]["route_facts_fingerprint"] == json.loads(env["SLINK_GEN2_ROUTE_FACTS"])["fingerprint"]
