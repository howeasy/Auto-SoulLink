"""MODEL controls for lua/tests/test_gen2_scripted_gate.lua (no emulator, no live gate).

The gate runs under lupa against a synthetic cartridge: BizHawk globals are stubbed over a fake
WRAM/HRAM/CartRAM, the real ROM bytes (so code-site anchors verify), a joypad capture, a frame
counter and a temp SaveRAM directory. The synthetic game walks the source route facts and shows the
source UI states; passing here is authoring evidence only, never PHYSICAL evidence.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from lupa import LuaError, LuaRuntime

from tools import gen2_fixtures as g, run_gb_gate
from tools.gen2_source_data import load_context

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "lua/tests/test_gen2_scripted_gate.lua"
EXTRA_RAM = ("wTilemap", "wObjectStructs", "wTileUp", "wTileDown", "wTileLeft", "wTileRight",
             "wPokegearFlags", "wEventFlags", "wPlayersHouse1FSceneID", "wElmsLabSceneID", "wNewBarkTownSceneID")
_CACHE = {}


def cached(key, build):
    if key not in _CACHE:
        _CACHE[key] = build()
    return _CACHE[key]


def facts(title):
    return cached(("facts", title), lambda: g.route_facts(title, ROOT))


def context(title):
    return cached(("ctx", title), lambda: load_context(title, root=ROOT))


def rom(title):
    ctx = context(title)
    return cached(("rom", title), lambda: (ctx.source_dir / ctx.lock["outputs"][ctx.artifact]["filename"]).read_bytes())


def profile_wrapper(title, drop=()):
    """The generated profile plus the observer symbols, taken from the same pinned source symbols."""
    wrapper = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text(encoding="utf-8"))
    selected = wrapper["titles"][title]
    for name in EXTRA_RAM:
        symbol = context(title).symbol(name)
        selected["ram"].setdefault(name, symbol.address)
        selected["ram_bank"].setdefault(name, symbol.bank)
    for name in drop:
        selected["ram"].pop(name, None)
        selected["hram"].pop(name, None)
    return wrapper


def charmap(title):
    return cached(("charmap", title), lambda: dict(LuaRuntime().execute(
        (ROOT / f"data/games/gen2_{title}/charmap.lua").read_text(encoding="utf-8"))["encoding"]))


class Input:
    def __init__(self, held, edges):
        self.held, self.edges = held, edges


class Sim:
    """A synthetic Gen 2 cartridge that follows the route facts and shows source UI states."""

    def __init__(self, lua, title, target, identity="default", *, cart_domain=0x8000, file_bytes=0x8000 + 22,
                 wild_battle=True):
        self.lua, self.title, self.target, self.identity = lua, title, target, identity
        self.facts, self.rom = facts(title), rom(title)
        self.prof = profile_wrapper(title)["titles"][title]
        self.enc = charmap(title)
        self.cart_domain, self.file_bytes, self.wild_battle = cart_domain, file_bytes, wild_battle
        self.wram, self.hram, self.cart = bytearray(0x8000), bytearray(0x80), bytearray(cart_domain)
        self.frame, self.pc, self.held, self.next_held = 0, 0, set(), set()
        self.hooks, self.inputs, self.writes, self.exited = {}, [], [], False
        self.saveram_path = None
        self.hram[self.prof["hram"]["hCGB"] - 0xFF80] = 1
        self.map, self.x, self.y, self.facing = None, 0, 0, "Down"
        self.sites = {kind: site for kind, site in self.facts["ui_origins"].items()}
        self.sites.update(overworld_tick=self.facts["observer"]["overworld_tick"],
                          save_completed=self.facts["observer"]["save_completed"])
        self.clear()
        self.gen = self.game()
        next(self.gen)

    # --- memory -------------------------------------------------------------------------------
    def offset(self, name, delta=0):
        address, bank = self.prof["ram"][name] + delta, self.prof["ram_bank"][name]
        return address - 0xC000 if address < 0xD000 else bank * 0x1000 + address - 0xD000

    def put(self, name, data, delta=0):
        at = self.offset(name, delta)
        self.wram[at:at + len(data)] = bytes(data)

    def get(self, name, delta=0):
        return self.wram[self.offset(name, delta)]

    def read_u8(self, address, domain):
        if domain == "System Bus":
            if address < 0x4000:
                return self.rom[address]
            if address < 0x8000:
                return self.rom[self.hram[self.prof["hram"]["hROMBank"] - 0xFF80] * 0x4000 + address - 0x4000]
            if 0xFF80 <= address < 0x10000:
                return self.hram[address - 0xFF80]
            raise AssertionError(f"unexpected System Bus read ${address:X}")
        return {"ROM": self.rom, "WRAM": self.wram, "CartRAM": self.cart}[domain][address]

    def read_range(self, address, length, domain):
        return self.lua.table_from([self.read_u8(address + i, domain) for i in range(length)])

    def write_u8(self, address, value, domain):
        assert domain == "WRAM", domain
        self.writes.append((address, value))
        self.wram[address] = value

    def domain_size(self, domain):
        return {"ROM": len(self.rom), "WRAM": len(self.wram), "CartRAM": len(self.cart)}[domain]

    # --- emulator ------------------------------------------------------------------------------
    def set_buttons(self, buttons):
        pressed = dict(buttons)
        self.inputs.append(pressed)
        self.next_held = {key for key, value in pressed.items() if value}

    def advance(self):
        edges = self.next_held - self.held
        self.held = self.next_held
        self.gen.send(Input(self.held, edges))
        self.frame += 1

    def on_exec(self, fn, address, name, domain):
        assert domain == "System Bus"
        self.hooks.setdefault(address, []).append(fn)
        return f"{{{len(self.hooks):08d}-0000-0000-0000-000000000001}}"

    def fire(self, kind):
        site = self.sites[kind]
        self.run_at(site["bank"], site["addr"])

    def run_at(self, bank, address):
        self.hram[self.prof["hram"]["hROMBank"] - 0xFF80] = bank or 1
        self.pc = address
        for fn in self.hooks.get(address, []):
            fn(address, 0, 0)

    def execute(self, *labels):
        """The ROM's own control flow through these source labels: a hook sees only the PCs executed."""
        for label in labels:
            self.run_at(*context(self.title).symbol(label))

    def saveram(self):
        data = bytes(self.cart[:0x8000]) + bytes(range(22))
        Path(self.saveram_path).write_bytes(data[:self.file_bytes])

    def install(self, env):
        lua, glob = self.lua, self.lua.globals()
        self.saveram_path = str(Path(env["SLINK_GEN2_SAVERAM_DIR"]) / env["SLINK_GEN2_SAVERAM_NAME"])
        glob.memory = lua.table_from({"read_u8": self.read_u8, "read_bytes_as_array": self.read_range,
                                      "write_u8": self.write_u8, "getmemorydomainsize": self.domain_size})
        glob.emu = lua.table_from({"frameadvance": self.advance, "framecount": lambda: self.frame,
                                   "getregister": lambda name: {"PC": self.pc, "SP": 0xDFF0}[name],
                                   "getsystemid": lambda: "GBC"})
        glob.joypad = lua.table_from({"set": self.set_buttons})
        glob.event = lua.table_from({"onmemoryexecute": self.on_exec, "unregisterbyid": lambda handle: True})
        glob.gameinfo = lua.table_from({"getromhash": lambda: self.facts["rom_sha1"].upper()})
        glob.client = lua.table_from({"speedmode": lambda p: None, "saveram": self.saveram,
                                      "exit": lambda: setattr(self, "exited", True)})
        glob.console = lua.table_from({"log": lambda s: None})
        glob.os.getenv = lambda name: env.get(name)

    # --- screen --------------------------------------------------------------------------------
    def clear(self):
        self.rows = [[" "] * 20 for _ in range(18)]
        self.draw()

    def draw(self):
        self.put("wTilemap", [self.enc[cell] for row in self.rows for cell in row])

    @staticmethod
    def tokens(text):
        found, i = [], 0
        while i < len(text):
            end = text.index(">", i) + 1 if text[i] == "<" else i + 1
            found.append(text[i:end])
            i = end
        return found

    def text_at(self, x, y, text):
        for n, token in enumerate(self.tokens(text)):
            self.rows[y][x + n] = token

    def box(self, x0, y0, x1, y1):
        for x in range(x0 + 1, x1):
            self.rows[y0][x] = self.rows[y1][x] = "─"
        for y in range(y0 + 1, y1):
            self.rows[y][x0] = self.rows[y][x1] = "│"
        self.rows[y0][x0], self.rows[y0][x1], self.rows[y1][x0], self.rows[y1][x1] = "┌", "┐", "└", "┘"

    def textbox(self, *lines):
        self.box(0, 12, 19, 17)
        for n, line in enumerate(lines):
            self.text_at(1, 14 + 2 * n, line)

    # --- UI stages -----------------------------------------------------------------------------
    def wait(self, frames):
        for _ in range(frames):
            yield

    def until(self, button, kind=None):
        while True:
            if kind:
                self.fire(kind)
            got = yield
            if button in got.edges:
                return

    def text(self, *lines, kind="prompt_button"):
        """A source text wait: PromptButton/JoyWaitAorB loop once per frame until A (home/joypad.asm:292-421)."""
        self.clear()
        self.textbox(*lines)
        self.draw()
        yield from self.wait(3)
        yield from self.until("A", kind)
        self.clear()

    def menu(self, kind, items, expect, *, columns=1, at=(0, 0), lines=(), via=None):
        self.clear()
        if lines:
            self.textbox(*lines)
        x0, y0 = at
        width = max(len(self.tokens(item)) for item in items) + 2
        rows = (len(items) + columns - 1) // columns
        x1, y1 = x0 + 1 + columns * width, y0 + 2 * rows
        self.box(x0, y0, x1, y1)
        cursor = 0

        def render():
            for index, item in enumerate(items):
                x, y = x0 + 1 + (index % columns) * width, y0 + 1 + 2 * (index // columns)
                self.rows[y][x] = "▶" if index == cursor else " "
                self.text_at(x + 1, y, item)
            self.draw()

        render()
        yield from self.wait(2)
        if via:
            self.execute(*via)
        else:
            self.fire(kind)
        while True:
            got = yield
            moves = {"Up": -columns, "Down": columns, "Left": -1, "Right": 1}
            for button, delta in moves.items():
                if button in got.edges and 0 <= cursor + delta < len(items):
                    cursor += delta
                    render()
            if "A" in got.edges:
                assert items[cursor] == expect, f"{kind}: chose {items[cursor]!r}, expected {expect!r}"
                self.clear()
                return

    def yes_no(self, *lines, answer="YES", via=("YesNoBox", "PlaceYesNoBox", "_YesNoBox")):
        """YesNoBox falls through PlaceYesNoBox's `jr _YesNoBox` (C home/menu.asm:418-428, G :382-392).
        `lines` are the two textbox rows the ROM leaves on screen under the box."""
        yield from self.menu("yes_no", ["YES", "NO"], answer, at=(13, 6), lines=lines, via=via)

    def save_yes_no(self, *lines):
        """SaveTheGame_yesorno enters at PlaceYesNoBox, never YesNoBox (C engine/menus/save.asm:209-214, G :197-202)."""
        yield from self.yes_no(*lines, via=("PlaceYesNoBox", "_YesNoBox"))

    # --- game ----------------------------------------------------------------------------------
    def warp_to(self, name, destination):
        return next(w for w in self.facts["maps"][name]["warps"] if w["destination"] == destination)

    def tile(self, x, y):
        area = self.facts["maps"][self.map]
        if not (0 <= x < area["width"] and 0 <= y < area["height"]):
            return 0
        if (x, y) in self.objects():
            return 0
        return area["grid"][y * area["width"] + x]

    def objects(self):
        if self.map != "ElmsLab":
            return []
        found = self.facts["maps"]["ElmsLab"]["objects"]
        return [(found[n]["x"], found[n]["y"]) for n in ("ProfElmScript", "CyndaquilPokeBallScript",
                                                         "TotodilePokeBallScript", "ChikoritaPokeBallScript")]

    def sync(self):
        area = self.facts["maps"][self.map]
        obs = self.facts["observer"]
        self.put("wMapGroup", [area["map_group"], area["map_number"], self.y, self.x])
        passable, blocked = obs["passable_collision"][0], 0xFF
        for name, (dx, dy) in {"wTileUp": (0, -1), "wTileDown": (0, 1), "wTileLeft": (-1, 0),
                               "wTileRight": (1, 0)}.items():
            self.put(name, [passable if self.tile(self.x + dx, self.y + dy) else blocked])
        o = obs["object"]
        structs = bytearray(o["length"] * o["count"])
        structs[o["sprite"]], structs[o["direction"]] = 1, obs["facing"][self.facing]
        # mid_step: live a6 showed the player struct already at its destination while wXCoord/wYCoord lag
        ahead = getattr(self, "mid_step", (0, 0))
        structs[o["map_x"]], structs[o["map_y"]] = self.x + 4 + ahead[0], self.y + 4 + ahead[1]
        for index, (x, y) in enumerate(self.objects(), 1):
            base = index * o["length"]
            structs[base + o["sprite"]], structs[base + o["map_x"]], structs[base + o["map_y"]] = 2, x + 4, y + 4
        self.put("wObjectStructs", structs)

    def scene(self, name, value):
        self.put(self.facts["observer"]["scene_symbols"][name], [value])

    def enter(self, name, x, y):
        self.map, self.x, self.y = name, x, y
        self.sync()
        yield from self.wait(6)   # map load: no overworld input tick

    def teleport(self, warp):
        destination = next(name for name, area in self.facts["maps"].items()
                            if area["map_const"] == warp["destination"])
        arrival = self.facts["maps"][destination]["warps"][warp["warp"] - 1]
        yield from self.enter(destination, arrival["x"], arrival["y"])
        yield from self.on_entry()

    def on_entry(self):
        scenes = self.facts["maps"]
        if self.map == "PlayersHouse1F" and self.get(self.facts["observer"]["scene_symbols"]["PlayersHouse1F"]) == 0 \
                and not scenes["PlayersHouse1F"]["coord_events"]:
            yield from self.mom()
        if self.map == "ElmsLab" and self.get(self.facts["observer"]["scene_symbols"]["ElmsLab"]) == 0:
            yield from self.elm()

    def mom(self):
        # MeetMomScript (C maps/PlayersHouse1F.asm:35-81): promptbuttons, the weekday picker, waitbutton.
        yield from self.text("ELM, next door, is")
        obs = self.facts["observer"]
        self.put("wPokegearFlags", [1 << obs["pokegear_obtained_bit"]])
        self.scene("PlayersHouse1F", self.facts["maps"]["PlayersHouse1F"]["scenes"]["SCENE_PLAYERSHOUSE1F_NOOP"])
        yield from self.text("#MON GEAR, or")
        yield from self.text("What day is it?", kind="day_picker")
        yield from self.yes_no("SUNDAY, is it?")
        yield from self.yes_no("Is it Daylight", "Saving Time now?")
        yield from self.yes_no("is that OK?")
        yield from self.yes_no("know how to use", "the PHONE?")
        yield from self.text("Hurry up, baby!", kind="wait_button")

    def elm(self):
        yield from self.text("There you are!")
        if self.title == "crystal":
            yield from self.yes_no("that I recently", "caught.")
        yield from self.text("Go on. Pick one!", kind="wait_button")
        elm = self.facts["maps"]["ElmsLab"]["objects"]["ProfElmScript"]
        self.x, self.y = elm["x"], elm["y"] + 1
        self.scene("ElmsLab", self.facts["maps"]["ElmsLab"]["scenes"]["SCENE_ELMSLAB_CANT_LEAVE"])
        self.sync()

    def starter(self):
        yield from self.yes_no("TOTODILE, the", "water #MON?")
        yield from self.text("received TOTODILE!")
        starter = self.facts["starter"]
        mon = bytearray(48)
        mon[0], mon[31] = starter["species"], starter["level"]
        self.put("wPartyCount", [1, starter["species"], 0xFF] + [0] * 5 + list(mon))
        # GiveANickname_YesNo prints _CaughtAskNicknameText (C engine/pokemon/caught_data.asm:154-157,
        # G caught_nickname.asm:123-126): its `cont "received?"` waits in PromptButton, then TextScroll x2
        # (C home/text.asm:520-526,581-611) wipes "Give a nickname to" before the YesNoBox.
        yield from self.text("Give a nickname to", "the TOTODILE you")
        yield from self.yes_no("the TOTODILE you", "received?", answer="NO")
        event = self.facts["observer"]["got_starter_event"]
        self.put("wEventFlags", [self.get("wEventFlags", event // 8) | 1 << event % 8], event // 8)
        self.scene("NewBarkTown", self.facts["maps"]["NewBarkTown"]["scenes"]["SCENE_NEWBARKTOWN_NOOP"])
        yield from self.text("ELM: If a wild")

    def save(self):
        items = ["POKéMON", "PACK", "POKéGEAR", "CHRIS", "SAVE", "OPTION", "EXIT"]
        yield from self.menu("start_menu", items, "SAVE", at=(8, 0))
        yield from self.save_yes_no("Would you like to", "save the game?")
        yield from self.wait(4)   # wSaveFileExists == 0: AskOverwriteSaveFile erases, no text (save.asm:181-184)
        for i in range(0x8000):
            self.cart[i] = (i * 7 + self.frame) & 0xFF
        self.put("wSavedAtLeastOnce", [1])
        self.fire("save_completed")
        yield from self.wait(4)

    def battle(self):
        self.put("wBattleMode", [1])
        yield from self.wait(4)
        yield from self.menu("battle_menu", ["FIGHT", "<PK><MN>", "PACK", "RUN"], "RUN", columns=2, at=(4, 12))
        yield from self.text("Got away safely!")
        self.put("wBattleMode", [0])

    def game(self):
        yield from self.wait(20)
        self.clear()
        yield from self.until("Start", "title")
        yield from self.wait(2)
        yield from self.menu("main_menu", ["NEW GAME", "OPTION"], "NEW GAME")
        if self.title == "crystal":
            yield from self.menu("gender", ["Boy", "Girl"], "Boy")
        yield from self.text("Hello!")
        yield from self.until("A", "clock_hour")
        yield from self.yes_no("What?")
        yield from self.until("A", "clock_minute")
        yield from self.yes_no("Whoa!")
        names = ["NEW NAME", "CHRIS", "MAT", "ALLAN", "JON"]
        yield from self.menu("name_choices", names, names[2 if self.identity == "ot2" else 1])
        yield from self.text("Your very own")
        self.put("wPartyCount", [0, 0xFF])
        self.put("wNumBalls", [0, 0xFF])
        yield from self.enter("PlayersHouse2F", 3, 3)
        grass_seen = False
        while True:
            self.fire("overworld_tick")
            got = yield
            if "Start" in got.edges:
                yield from self.save()
                continue
            ball = self.facts["maps"]["ElmsLab"]["objects"]["TotodilePokeBallScript"]
            if ("A" in got.edges and self.map == "ElmsLab" and self.facing == "Up"
                    and (self.x, self.y) == (ball["x"], ball["y"] + 1) and self.get("wPartyCount") == 0):
                yield from self.starter()
                continue
            held = [d for d in ("Up", "Down", "Left", "Right") if d in got.held]
            if not held:
                continue
            direction = held[0]
            self.facing = direction
            area = self.facts["maps"][self.map]
            here = next((w for w in area["warps"] if (w["x"], w["y"]) == (self.x, self.y)), None)
            if here and here["carpet"] == direction:
                yield from self.teleport(here)
                continue
            if self.map == "NewBarkTown" and self.x == 0 and direction == "Left":
                yield from self.enter("Route29", self.facts["maps"]["Route29"]["width"] - 1, self.y)
                continue
            dx, dy = {"Up": (0, -1), "Down": (0, 1), "Left": (-1, 0), "Right": (1, 0)}[direction]
            if self.tile(self.x + dx, self.y + dy):
                self.x, self.y = self.x + dx, self.y + dy
            self.sync()
            warp = next((w for w in area["warps"] if (w["x"], w["y"]) == (self.x, self.y) and not w["carpet"]), None)
            if warp and (dx or dy):
                yield from self.teleport(warp)
                continue
            if (self.map == "PlayersHouse1F" and self.get(self.facts["observer"]["scene_symbols"]["PlayersHouse1F"]) == 0
                    and any((c["x"], c["y"]) == (self.x, self.y) for c in area["coord_events"])):
                yield from self.mom()
            if self.map == "Route29" and self.tile(self.x, self.y) == 2 and not grass_seen and self.wild_battle:
                grass_seen = True
                yield from self.battle()


# --- harness ---------------------------------------------------------------------------------------

GATE_MODULES = ("lua/json_codec.lua", "lua/write_permit.lua", "lua/scripted_inputs.lua", "lua/gb_hook_binding.lua",
                "lua/gen2/reads.lua", "lua/tests/gen2_scripted_play.lua", "lua/tests/gen2_qualify.lua")


def make_root(tmp_path, title, drop=()):
    root = tmp_path / "root"
    for rel in GATE_MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    pack = root / f"data/games/gen2_{title}"
    pack.mkdir(parents=True)
    shutil.copy(ROOT / f"data/games/gen2_{title}/charmap.lua", pack / "charmap.lua")
    (pack / "profile.json").write_text(json.dumps(profile_wrapper(title, drop)), encoding="utf-8")
    (root / "patch/build").mkdir(parents=True)
    return root


def make_env(root, title, target, identity="default", **case_changes):
    spec = g.BY_NAME[f"{title}_{target}" + ("_ot2" if identity == "ot2" else "")]
    case = {**vars(spec), "attempt_id": "model-1", "max_frames": 20000, "max_phase_frames": 8000, "settle_frames": 30}
    case.update(case_changes)
    saves = root / ".cache/gen2-fixtures/model-1" / spec.name / "saveram"
    saves.mkdir(parents=True)
    descriptor = run_gb_gate.describe_gen2(title + "_cold")
    return spec, {"SLINK_ROOT": str(root).replace("\\", "/"), "SLINK_GEN2_FIXTURE_CASE": json.dumps(case),
                  "SLINK_GEN2_ROUTE_FACTS": json.dumps(facts(title)), "SLINK_GEN2_TITLE": title,
                  "SLINK_GEN2_ROM_SHA1": descriptor["rom_sha1"], "SLINK_GEN2_CORE_MODE": "CGB", "SLINK_GEN2_COLD": "1",
                  "SLINK_GEN2_SAVERAM_DIR": str(saves).replace("\\", "/"),
                  "SLINK_GEN2_SAVERAM_NAME": descriptor["saveram_name"]}


def run(root, env, sim):
    sim.install(env)
    with pytest.raises(LuaError, match="slink-gate-finished"):
        sim.lua.execute(GATE.read_text(encoding="utf-8"))
    assert sim.exited
    text = (root / "patch/build/test_gen2_scripted_gate_result.txt").read_text(encoding="utf-8")
    return text.strip().splitlines()[-1], text


def receipt_path(env, spec):
    return Path(env["SLINK_GEN2_SAVERAM_DIR"]) / f"{spec.name}.played.json"


def library(sim, env):
    sim.install(env)
    sim.lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    gate = sim.lua.execute(GATE.read_text(encoding="utf-8"))
    return gate, gate.context(gate.bizhawk(), sim.lua.globals().os.getenv)


def ball_span(sim):
    lo = sim.offset("wNumBalls")
    return lo, lo + 2 + 2 * sim.prof["derived"]["ball_capacity"]


# --- positive controls ----------------------------------------------------------------------------

@pytest.mark.parametrize("title,target,identity", [("crystal", "town", "default"), ("crystal", "battle", "default"),
                                                   ("gold", "battle", "default"), ("silver", "town", "default"),
                                                   ("crystal", "town", "ot2")])
def test_synthetic_route_completes_and_the_receipt_qualifies(tmp_path, title, target, identity):
    root = make_root(tmp_path, title)
    spec, env = make_env(root, title, target, identity)
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), title, target, identity)
    verdict, text = run(root, env, sim)
    assert verdict.startswith("RESULT: PASS"), text
    receipt = json.loads(receipt_path(env, spec).read_text(encoding="utf-8"))
    saved = (Path(env["SLINK_GEN2_SAVERAM_DIR"]) / env["SLINK_GEN2_SAVERAM_NAME"]).read_bytes()
    assert len(saved) == g.SAVERAM_BYTES
    g.validate_played_receipt(receipt, spec, facts(title), {"cartram_sha256": hashlib.sha256(g.cart_ram(saved)).hexdigest()})
    assert receipt["natural_ball_acquisition"] is False and receipt["qualified"] is False
    # Normal buttons only, and the only memory writes are the O-10 Ball-pocket span on battle cases.
    assert all(set(row) <= set(g_buttons()) and all(type(v) is bool for v in row.values()) for row in sim.inputs)
    lo, hi = ball_span(sim)
    if target == "battle":
        assert receipt["harness_write_scopes"] == ["O-10:BallPocket"] and sim.writes
        assert all(lo <= address < hi for address, _ in sim.writes)
        assert "o10-balls" in [row["phase"] for row in receipt["phases"]]
    else:
        assert receipt["harness_write_scopes"] == [] and sim.writes == []


def g_buttons():
    return ("Up", "Down", "Left", "Right", "A", "B", "Start", "Select")


def test_lua_sha256_matches_hashlib():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    gate = lua.execute(GATE.read_text(encoding="utf-8"))
    for data in (b"", b"abc", bytes(range(256)) * 3, bytes(55), bytes(64)):
        assert gate.sha256(lambda i, d=data: d[i], len(data)) == hashlib.sha256(data).hexdigest()


# --- refusals --------------------------------------------------------------------------------------

@pytest.mark.parametrize("change,match", [
    (lambda env: env.pop("SLINK_GEN2_ROUTE_FACTS"), "missing environment SLINK_GEN2_ROUTE_FACTS"),
    (lambda env: env.update(SLINK_GEN2_FIXTURE_CASE="{"), "malformed SLINK_GEN2_FIXTURE_CASE"),
    (lambda env: env.update(SLINK_GEN2_TITLE="gold"), "differs from the selected"),
    (lambda env: env.update(SLINK_GEN2_COLD="0"), "cold boot"),
    (lambda env: env.update(SLINK_GEN2_CORE_MODE="DMG"), "CGB core"),
    (lambda env: env.update(SLINK_GEN2_ROUTE_FACTS=json.dumps({**facts("crystal"), "observer": None})), "observer"),
])
def test_bad_environment_refuses_before_any_input(tmp_path, change, match):
    root = make_root(tmp_path, "crystal")
    spec, env = make_env(root, "crystal", "town")
    change(env)
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    verdict, _ = run(root, env, sim)
    assert verdict.startswith("RESULT: FAIL") and match in verdict
    assert sim.inputs == [] and not receipt_path(env, spec).exists()


@pytest.mark.parametrize("drop", ["wTilemap", "wEventFlags", "hCGB", "wElmsLabSceneID", "wSaveFileExists"])
def test_missing_profile_fact_refuses(tmp_path, drop):
    root = make_root(tmp_path, "crystal", drop=(drop,))
    spec, env = make_env(root, "crystal", "town")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    verdict, _ = run(root, env, sim)
    assert verdict.startswith("RESULT: FAIL") and "profile facts missing" in verdict and drop in verdict
    assert sim.inputs == [] and not receipt_path(env, spec).exists()


def test_a_non_empty_save_lane_refuses_new_game(tmp_path):
    """TryLoadSaveData found a save (wSaveFileExists != 0): the cold route refuses before NEW GAME."""
    root = make_root(tmp_path, "gold")
    spec, env = make_env(root, "gold", "town")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "gold", "town")
    sim.put("wSaveFileExists", [1])
    verdict, _ = run(root, env, sim)
    assert verdict.startswith("RESULT: FAIL") and "empty isolated save lane" in verdict
    assert not any(row.get("A") for row in sim.inputs) and not receipt_path(env, spec).exists()


def test_wait_loops_are_ready_only_while_they_fire_and_once_origins_persist(tmp_path):
    """A wait loop (PromptButton, InitClock, WaitPressAorB_BlinkCursor) that stopped firing was answered:
    shown, never re-pulsed. A once-origin (StartTitleScreen) keeps its context, ready after the settle frames."""
    root = make_root(tmp_path, "crystal")
    _, env = make_env(root, "crystal", "town")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    sim.gen = sim.wait(10 ** 6)   # frames advance; only the fires below reach the hooks
    next(sim.gen)
    gate, ctx = library(sim, env)
    gate.hooks(ctx)
    observe = gate.observer(ctx)

    def look():
        value = observe()
        return value["ui"]["kind"] if value["ui"] else None, value["input_ready"], value["overworld_ready"]

    for _ in range(9):
        sim.fire("prompt_button")
        sim.advance()
    assert look() == ("prompt_button", True, False)
    sim.advance()
    sim.advance()
    sim.advance()
    assert look() == ("prompt_button", False, False)
    sim.fire("prompt_button")   # the next para's wait resumes the same context
    sim.advance()
    assert look() == ("prompt_button", True, False)
    for _ in range(9):   # InitClock .SetHourLoop is a per-frame loop too: answered means not ready
        sim.fire("clock_hour")
        sim.advance()
    assert look() == ("clock_hour", True, False)
    for _ in range(3):
        sim.advance()
    assert look() == ("clock_hour", False, False)
    for _ in range(9):   # WaitPressAorB_BlinkCursor .loop spins several times per frame
        sim.fire("text")
        sim.fire("text")
        sim.advance()
    assert look() == ("text", True, False)
    for _ in range(3):
        sim.advance()
    assert look() == ("text", False, False)
    sim.fire("title")   # a once-origin: StartTitleScreen runs once and its context persists
    for _ in range(9):
        sim.advance()
    assert look() == ("title", True, False)
    ctx.state.ui.consumed = sim.frame   # answered: the title drops its first press, so it re-pulses
    for _ in range(16):
        sim.advance()
    assert look() == ("title", True, False)
    ctx.state.ui.kind, ctx.state.ui.consumed = "continue_confirm", sim.frame   # a map-load confirm never does
    for _ in range(40):
        sim.advance()
    assert look() == ("continue_confirm", False, False)
    ctx.state.ui.kind = "title"
    sim.fire("overworld_tick")
    sim.advance()
    assert look() == (None, None, True)


def test_npc_positions_do_not_shift_while_the_player_struct_is_mid_step(tmp_path):
    """Object struct coords are map coords + 4 (player_object.asm RefreshPlayerCoords, map_objects.asm spawns).
    Mid-step the player struct already holds its destination while wXCoord/wYCoord lag (live attempt
    n2-crystal-town-a6): a player-relative offset shifted every NPC one tile and put Mom on her own trigger."""
    root = make_root(tmp_path, "crystal")
    _, env = make_env(root, "crystal", "town")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    sim.gen = sim.wait(10 ** 6)
    next(sim.gen)
    gate, ctx = library(sim, env)
    gate.hooks(ctx)
    observe = gate.observer(ctx)
    sim.map, sim.x, sim.y = "ElmsLab", 4, 6
    want = sorted(sim.objects())
    for ahead in ((0, 0), (-1, 0), (1, 0), (0, 1), (0, -1)):
        sim.mid_step = ahead
        sim.sync()
        blocked = observe()["blocked"]
        assert sorted((b["x"], b["y"]) for b in blocked.values()) == want, ahead


@pytest.mark.parametrize("title", ["crystal", "gold"])
def test_prompts_classify_the_rows_the_rom_leaves_after_a_cont_scroll(title):
    """`cont` = PromptButton, then TextScroll x2 (C home/text.asm:502-526,581-611): at the box only the last two
    rows remain. The overwrite box is save_overwrite (its first line is gone), the `cont` wait before it is
    save_overwrite_text, and the nickname box keeps "received?" but never "Give a nickname to"."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    gate = lua.execute(GATE.read_text(encoding="utf-8"))

    def classify(prompts, *rows):
        table = lua.table_from([lua.table_from(list(row)) for row in rows])
        return gate.classify_prompt(table, lua.table_from({k: lua.table_from(v) for k, v in prompts.items()}))

    qualify, route = qfacts(title)["prompts"], facts(title)["observer"]["prompts"]
    assert classify(qualify, "There is already a", "save file. Is it") == "save_overwrite_text"
    assert classify(qualify, "save file. Is it", "OK to overwrite?") == "save_overwrite"
    assert classify(qualify, "Would you like to", "save the game?") == "save_confirm"
    assert classify(route, "the TOTODILE you", "received?") == "nickname"
    assert classify(route, "Give a nickname to", "the TOTODILE you") is None   # the wait, not the box


def test_timeout_writes_failed_and_no_success_receipt(tmp_path):
    root = make_root(tmp_path, "crystal")
    spec, env = make_env(root, "crystal", "town", max_frames=300, max_phase_frames=300)
    receipt_path(env, spec).write_text("{\"stale\": true}")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    verdict, _ = run(root, env, sim)
    assert verdict.startswith("RESULT: FAIL") and "route failed" in verdict
    assert not receipt_path(env, spec).exists()


def test_town_case_refuses_any_write_scope(tmp_path):
    root = make_root(tmp_path, "crystal")
    _, env = make_env(root, "crystal", "town")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    gate, ctx = library(sim, env)
    sim.put("wNumBalls", [0, 0xFF])
    handler = gate.o10_handler(ctx)
    f = facts("crystal")
    request = sim.lua.table_from({"kind": "o10-ball-pocket", "exception": "O-10", "natural_acquisition": False,
                                  "attempt_id": "model-1", "facts_fingerprint": f["fingerprint"],
                                  "bank": f["balls"]["bank"], "expected": sim.lua.table(),
                                  "writes": sim.lua.table_from([sim.lua.table_from(
                                      {"address": f["balls"]["count_address"], "value": 1})])})
    with pytest.raises(LuaError, match="town fixture refuses every harness write"):
        handler(request)
    assert sim.writes == [] and len(ctx.scopes) == 0
    # The independent validator refuses a town receipt that records any staging scope.
    spec = g.BY_NAME["crystal_town"]
    receipt = {"schema": "gen2-played-route-v1", "case": spec.name, "facts_fingerprint": f["fingerprint"],
               "cartram_sha256": "0" * 64, "rom_sha1": f["rom_sha1"], "core_mode": "CGB", "speed_percent": 300,
               "input_mode": "normal_buttons", "harness_write_scopes": ["O-10:BallPocket"],
               "phases": [{"phase": p, "frame": n} for n, p in enumerate(
                   ["new-game", "leave-bedroom", "mom", "to-elm", "starter", "native-save", "route-saved"])]}
    with pytest.raises(ValueError, match="unauthorized or unrecorded fixture staging"):
        g.validate_played_receipt(receipt, spec, f, {"cartram_sha256": "0" * 64})


@pytest.mark.parametrize("where", ["past_terminator", "before_count", "mixed"])
def test_battle_write_outside_the_ball_pocket_span_is_refused(tmp_path, where):
    root = make_root(tmp_path, "crystal")
    _, env = make_env(root, "crystal", "battle")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "battle")
    gate, ctx = library(sim, env)
    sim.put("wNumBalls", [0, 0xFF])
    handler = gate.o10_handler(ctx)
    f = facts("crystal")
    base, capacity = f["balls"]["count_address"], f["balls"]["capacity"]
    outside = {"past_terminator": [(base + 2 + 2 * capacity, 1)], "before_count": [(base - 1, 1)],
               "mixed": [(base + 1, f["balls"]["item"]), (base + 2 + 2 * capacity, 0)]}[where]
    writes = [sim.lua.table_from({"address": a, "value": v}) for a, v in outside]
    request = sim.lua.table_from({"kind": "o10-ball-pocket", "exception": "O-10", "natural_acquisition": False,
                                  "attempt_id": "model-1", "facts_fingerprint": f["fingerprint"],
                                  "bank": f["balls"]["bank"], "expected": sim.lua.table(),
                                  "writes": sim.lua.table_from(writes)})
    before = bytes(sim.wram)
    with pytest.raises(LuaError, match="write refused"):
        handler(request)
    assert bytes(sim.wram) == before and sim.writes == [] and len(ctx.scopes) == 0


def test_hash_covers_cartram_only_never_the_rtc_trailer(tmp_path):
    root = make_root(tmp_path, "crystal")
    spec, env = make_env(root, "crystal", "town")
    # A CartRAM domain that also exposes the 22 trailer bytes must still hash exactly 32768 bytes.
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town", cart_domain=g.SAVERAM_BYTES)
    verdict, text = run(root, env, sim)
    assert verdict.startswith("RESULT: PASS"), text
    receipt = json.loads(receipt_path(env, spec).read_text(encoding="utf-8"))
    saved = (Path(env["SLINK_GEN2_SAVERAM_DIR"]) / env["SLINK_GEN2_SAVERAM_NAME"]).read_bytes()
    assert receipt["cartram_sha256"] == hashlib.sha256(saved[:0x8000]).hexdigest()
    whole = hashlib.sha256(saved).hexdigest()
    assert receipt["cartram_sha256"] != whole
    inspection = {"cartram_sha256": hashlib.sha256(g.cart_ram(saved)).hexdigest()}
    with pytest.raises(ValueError, match="byte/source binding"):
        g.validate_played_receipt({**receipt, "cartram_sha256": whole}, spec, facts("crystal"), inspection)


def test_flushed_saveram_without_the_rtc_trailer_refuses(tmp_path):
    root = make_root(tmp_path, "crystal")
    spec, env = make_env(root, "crystal", "town")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town", file_bytes=0x8000)
    verdict, _ = run(root, env, sim)
    assert verdict.startswith("RESULT: FAIL") and "flushed SaveRAM is 32768 bytes" in verdict
    assert not receipt_path(env, spec).exists()


def test_non_button_input_is_refused(tmp_path):
    root = make_root(tmp_path, "crystal")
    _, env = make_env(root, "crystal", "town")
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    gate, ctx = library(sim, env)
    step = gate.button_step(ctx)
    for bad in ({"Power": True}, {"P1 A": True}, {"A": 1}):
        with pytest.raises(LuaError, match="non-button input refused"):
            step(sim.lua.table_from(bad))
    assert sim.inputs == [] and sim.frame == 0
    step(sim.lua.table_from({"A": True}))
    assert sim.inputs == [{"A": True}] and sim.frame == 1


# --- qualification mode (warm boot -> CONTINUE -> overworld -> START/SAVE) ------------------------

def qfacts(title):
    return cached(("qfacts", title), lambda: g.qualify_facts(title, ROOT))


class QualifySim(Sim):
    """A synthetic cartridge booted from a battery save: title -> CONTINUE -> the saved map (-> SAVE)."""

    def __init__(self, lua, title, target, *, rtc_reset=False, other_player=False, where=("ElmsLab", 4, 3)):
        self.qf, self.rtc_reset, self.other_player, self.where = qfacts(title), rtc_reset, other_player, where
        super().__init__(lua, title, target)
        self.sites.update(self.qf["ui_origins"])
        self.sites.update(self.qf["sites"])
        self.cart[:] = bytes((i * 13 + 5) & 0xFF for i in range(len(self.cart)))
        self.booted = bytes(self.cart[:0x8000])

    def load(self):
        """TryLoadSaveFile: the party comes back into WRAM (the synthetic battery holds it)."""
        starter = self.facts["starter"]
        mon = bytearray(48)
        mon[0], mon[31] = starter["species"], starter["level"]
        self.put("wPartyCount", [1, starter["species"], 0xFF] + [0] * 5 + list(mon))
        self.put("wNumBalls", [0, 0xFF])

    def party_hex(self):
        ram = self.prof["ram"]
        start = self.offset("wPartyCount")
        return bytes(self.wram[start:start + ram["wPartyMonNicknamesEnd"] - ram["wPartyCount"]]).hex()

    def save(self):
        items = ["POKéMON", "PACK", "POKéGEAR", "CHRIS", "SAVE", "OPTION", "EXIT"]
        yield from self.menu("start_menu", items, "SAVE", at=(8, 0))
        yield from self.save_yes_no("Would you like to", "save the game?")
        if not self.other_player:
            self.fire("same_save_file")
        # _AlreadyASaveFileText / _AnotherSaveFileText `cont` (C data/text/common_3.asm:202-212, G common_2.asm:
        # 1289-1299) places <_CONT> (C home/text.asm:231,528-539) -> _ContText -> PromptButton (:502-512): a text wait.
        yield from self.text("There is another" if self.other_player else "There is already a", "save file. Is it")
        yield from self.save_yes_no("save file. Is it", "OK to overwrite?")   # first line scrolled off
        yield from self.wait(4)
        self.cart[0x1F10] ^= 0x5A   # a native re-save moves sStackTop
        self.fire("save_completed")
        yield from self.wait(4)

    def game(self):
        yield from self.wait(20)
        self.clear()
        yield from self.until("Start", "title")
        yield from self.wait(2)
        yield from self.menu("main_menu", ["CONTINUE", "NEW GAME", "OPTION"], "CONTINUE")
        self.fire("continue")
        self.load()
        yield from self.wait(20)
        self.fire("continue_confirm")
        yield from self.until("A")
        self.fire("continue_loaded")
        self.fire("restart_clock" if self.rtc_reset else "rtc_ok")
        yield from self.wait(20)
        self.fire("finish_continue")
        yield from self.enter(*self.where)
        while True:
            self.fire("overworld_tick")
            got = yield
            if "Start" in got.edges:
                yield from self.save()


def qualify_env(root, title, target, stage, **changes):
    spec, env = make_env(root, title, target)
    descriptor = run_gb_gate.describe_gen2(title)
    env.update(SLINK_GEN2_COLD="0", SLINK_GEN2_SAVERAM_NAME=descriptor["saveram_name"],
               SLINK_GEN2_QUALIFY=json.dumps({"stage": stage, "stage_fingerprint": "ab" * 32, "facts": qfacts(title)}))
    env.update(changes)
    return spec, env


def witness_path(env, spec, stage):
    return Path(env["SLINK_GEN2_SAVERAM_DIR"]) / f"{spec.name}.{stage}.witness.json"


@pytest.mark.parametrize("title,stage", [("crystal", "boot"), ("gold", "reload"), ("silver", "boot")])
def test_qualification_boot_writes_a_game_witness_of_the_loaded_checkpoint(tmp_path, title, stage):
    root = make_root(tmp_path, title)
    spec, env = qualify_env(root, title, "town", stage)
    sim = QualifySim(LuaRuntime(unpack_returned_tuples=True), title, "town")
    verdict, text = run(root, env, sim)
    assert verdict.startswith("RESULT: PASS"), text
    game = json.loads(witness_path(env, spec, stage).read_text(encoding="utf-8"))
    lab = facts(title)["maps"]["ElmsLab"]
    assert game["schema"] == "gen2-fixture-game-witness-v1" and game["stage"] == stage and game["case"] == spec.name
    assert game["stage_fingerprint"] == "ab" * 32 and game["speed_percent"] == 100 and game["observer"] == "independent_GAME"
    assert game["cartram_sha256"] == hashlib.sha256(sim.booted).hexdigest()
    assert game["location"] == [lab["map_group"], lab["map_number"]] and game["position"] == [4, 3]
    assert game["party_raw_hex"] == sim.party_hex() and game["save_success_counter"] == 0
    assert game["continue_selected"] is game["rtc_validated"] is game["native_load_completed"] is True
    assert "resave_cartram_sha256" not in game and game["harness_write_scopes"] == []
    assert [row["phase"] for row in game["phases"]] == ["title", "continue", "loaded"]
    # Normal buttons only and no memory write of any kind.
    assert sim.writes == [] and all(set(row) <= set(g_buttons()) for row in sim.inputs)
    # The witness satisfies the independent validator it is written for.
    inspection = {"cartram_sha256": game["cartram_sha256"], "party_raw_hex": game["party_raw_hex"],
                  "location": tuple(game["location"]), "position": tuple(game["position"])}
    context = SimpleNamespace(fixture=spec.name, provenance={"rom_sha1": facts(title)["rom_sha1"]})
    g.validate_game_witness(game, context, inspection, stage, "ab" * 32)


def test_qualification_resave_saves_natively_and_flushes_the_cartram(tmp_path):
    root = make_root(tmp_path, "crystal")
    spec, env = qualify_env(root, "crystal", "battle", "resave")
    sim = QualifySim(LuaRuntime(unpack_returned_tuples=True), "crystal", "battle", where=("Route29", 10, 10))
    verdict, text = run(root, env, sim)
    assert verdict.startswith("RESULT: PASS"), text
    game = json.loads(witness_path(env, spec, "resave").read_text(encoding="utf-8"))
    flushed = (Path(env["SLINK_GEN2_SAVERAM_DIR"]) / env["SLINK_GEN2_SAVERAM_NAME"]).read_bytes()
    assert len(flushed) == g.SAVERAM_BYTES
    assert game["resave_cartram_sha256"] == hashlib.sha256(flushed[:0x8000]).hexdigest() != game["cartram_sha256"]
    assert game["cartram_sha256"] == hashlib.sha256(sim.booted).hexdigest()
    assert game["save_success_counter"] == 1 and game["site_hits"]["same_save_file"] == 1
    assert [row["phase"] for row in game["phases"]] == ["title", "continue", "save", "resaved"]
    assert sim.writes == []


@pytest.mark.parametrize("sim_changes,match", [
    ({"rtc_reset": True}, "RestartClock ran"),
    ({"other_player": True}, "same-player branch"),
])
def test_qualification_refuses_an_rtc_reset_or_another_players_save(tmp_path, sim_changes, match):
    root = make_root(tmp_path, "crystal")
    spec, env = qualify_env(root, "crystal", "town", "resave")
    witness_path(env, spec, "resave").write_text("{\"stale\": true}")
    sim = QualifySim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town", **sim_changes)
    verdict, _ = run(root, env, sim)
    assert verdict.startswith("RESULT: FAIL") and match in verdict
    assert not witness_path(env, spec, "resave").exists()


BAD_BINDINGS = {
    "cold": lambda: {"SLINK_GEN2_COLD": "1"},
    "stage": lambda: {"SLINK_GEN2_QUALIFY": json.dumps({"stage": "replay", "stage_fingerprint": "ab" * 32})},
    "foreign": lambda: {"SLINK_GEN2_QUALIFY": json.dumps({"stage": "boot", "stage_fingerprint": "ab" * 32,
                                                          "facts": {**qfacts("gold"), "title": "crystal"}})},
}


@pytest.mark.parametrize("bad,match", [("cold", "warm descriptor"), ("stage", "stage binding"),
                                       ("foreign", "differ from the selected")])
def test_qualification_bad_binding_refuses_before_any_input(tmp_path, bad, match):
    root = make_root(tmp_path, "crystal")
    spec, env = qualify_env(root, "crystal", "town", "boot", **BAD_BINDINGS[bad]())
    sim = QualifySim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    verdict, _ = run(root, env, sim)
    assert verdict.startswith("RESULT: FAIL") and match in verdict
    assert sim.inputs == [] and not witness_path(env, spec, "boot").exists()


# --- runner binding --------------------------------------------------------------------------------

def test_gate_script_binding_declares_its_terminal_result_path():
    assert (ROOT / g.GATE_SCRIPT).is_file()
    assert Path(run_gb_gate._result_path_for(g.GATE_SCRIPT)).name == "test_gen2_scripted_gate_result.txt"
