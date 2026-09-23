"""Gen 2 checkpoint over held synthetic observations: inspect_candidate is never authority; check(kind)
authorizes only behind a PHYSICAL write-window receipt and only for the write kinds it proved (cards U2,
U2b). The receipt gate recomputes every control from raw run records produced by the WHOLE gate on the
synthetic cartridge (MODEL evidence: relabelled PHYSICAL here only to exercise acceptance), plus the live
lane's Python re-derivations and the gate's pure helpers."""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.live import test_gen2_write_windows as u2  # noqa: E402


class Candidate:
    def __init__(self, title="crystal"):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.pack = json.loads((ROOT / f"data/games/gen2_{title}/write_checkpoint.json").read_text())
        self.data = self.pack["titles"][title]
        self.primary = self.data["primary"]
        self.memory, self.reads = {}, []
        self.epoch, self.admitted, self.unowned = 1, True, True
        self.rom_bank = self.primary["execution_before"]["bank"]
        self.wram_bank = 1
        self.registers = {"PC": self.primary["execution_before"]["pc"],
                          "SP": self.primary["caller_stack"]["minimum_sp"] + 16}
        for anchor in self.primary["anchors"].values():
            for offset, value in enumerate(bytes.fromhex(anchor["expected_hex"])):
                self.memory["ROM", anchor["rom_offset"] + offset] = value
                self.memory["System Bus", anchor["address"] + offset] = value
        for word in self.primary["caller_stack"]["required_words"]:
            address = self.registers["SP"] + word["offset_from_sp"]
            self.memory["System Bus", address] = word["value"] & 255
            self.memory["System Bus", address + 1] = word["value"] >> 8
        for condition in self.primary["state_predicates"]:
            self.memory["System Bus", condition["address"]] = condition["value"]
        owner = self.primary["ownership_requirements"]
        self.memory["System Bus", owner["rom_bank_shadow"]["address"]] = self.rom_bank
        self.memory["System Bus", owner["wram_bank_register"]["address"]] = 1
        self.memory["System Bus", owner["serial_control"]["address"]] = 0
        self.io = self.lua.table(read_u8=self.read, domains=lambda: self.lua.table("ROM", "System Bus"),
                                 domain_size=lambda _name: 0x200000,
                                 register=lambda name: self.registers.get(name))
        self.ownership = self.lua.table(
            capture=lambda: self.epoch, valid=lambda held: held == self.epoch,
            admitted=lambda selected, sha: self.admitted and selected == title and sha == self.pack["source"]["rom_sha1"],
            no_conflicting_owner=lambda: self.unowned, mapped_rom_bank=lambda: self.rom_bank,
            effective_wram_bank=lambda: self.wram_bank,
        )
        self.module = self.lua.eval("dofile")((ROOT / "lua/gen2_write_safety.lua").as_posix())
        self.evaluator = self.lua.eval("dofile")((ROOT / "lua/gb_checkpoint.lua").as_posix())
        self.title = title

    def read(self, address, domain):
        self.reads.append((domain, int(address)))
        return self.memory.get((domain, int(address)))

    def binder(self, receipt=None):
        return self.module.new(self.lua.table_from(self.pack, recursive=True), self.title,
                               self.io, self.evaluator, self.ownership,
                               None if receipt is None else self.lua.table_from(receipt, recursive=True))

    def check(self, receipt=None, kind="party_hp"):
        binder = self.binder(receipt)
        return binder.check(binder, kind)

    def inspect(self):
        binder = self.binder()
        return binder.inspect_candidate(binder)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_matching_source_candidate_never_grants_runtime_writes(title):
    candidate = Candidate(title)
    report = candidate.inspect()
    assert report.candidate_match is True, report.reason
    assert report.runtime_authorized is False and report.physical_status == "OPEN"
    binder = candidate.binder()
    assert binder.check(binder)[0] is False
    candidate.data["runtime_authorized"] = True
    assert candidate.inspect().candidate_match is False
    binder = candidate.binder()
    assert binder.check(binder)[0] is False


@pytest.mark.parametrize("symbol", ["wMapStatus", "wMapEventStatus", "wScriptRunning", "wScriptMode",
    "wScriptFlags", "wScriptStackSize", "wJoypadDisable", "wGameLogicPaused", "wInputType",
    "wBattleMode", "wStateFlags", "hMapEntryMethod", "wLinkMode", "hSerialConnectionStatus", "wSavedAtLeastOnce"])
def test_every_game_state_ownership_predicate_is_required(symbol):
    candidate = Candidate()
    condition = next(row for row in candidate.primary["state_predicates"] if row["symbol"] == symbol)
    candidate.memory["System Bus", condition["address"]] ^= condition["mask"]
    report = candidate.inspect()
    assert report.candidate_match is False and symbol in report.reason


@pytest.mark.parametrize("fault", ["rom", "mapped_anchor", "caller", "pc", "rom_bank", "wram_bank",
                                  "serial", "identity", "owner", "missing_predicate", "epoch"])
def test_stale_or_unavailable_same_hold_evidence_refuses(fault):
    candidate = Candidate()
    primary = candidate.primary
    if fault in ("rom", "mapped_anchor"):
        anchor = primary["anchors"]["ow_player_input"]
        key = ("ROM", anchor["rom_offset"]) if fault == "rom" else ("System Bus", anchor["address"])
        candidate.memory[key] ^= 1
    elif fault == "caller":
        candidate.memory["System Bus", candidate.registers["SP"]] ^= 1
    elif fault == "pc":
        candidate.registers["PC"] += 1
    elif fault == "rom_bank":
        candidate.rom_bank += 1
    elif fault == "wram_bank":
        candidate.wram_bank = 2
    elif fault == "serial":
        candidate.memory["System Bus", primary["ownership_requirements"]["serial_control"]["address"]] = 128
    elif fault == "identity":
        candidate.admitted = False
    elif fault == "owner":
        candidate.unowned = False
    elif fault == "missing_predicate":
        primary["state_predicates"].pop()
    else:
        def read_and_reset(address, domain):
            candidate.epoch += 1
            return candidate.read(address, domain)
        candidate.io.read_u8 = read_and_reset
    assert candidate.inspect().candidate_match is False


def test_no_gen1_irq_resume_or_two_word_stack_is_inherited():
    candidate = Candidate("gold")
    assert candidate.inspect().candidate_match is True
    stack_reads = [address for domain, address in candidate.reads
                   if domain == "System Bus" and candidate.registers["SP"] <= address < candidate.registers["SP"] + 4]
    assert stack_reads == [candidate.registers["SP"], candidate.registers["SP"] + 1]
    candidate.registers["PC"] = 0x40
    assert candidate.inspect().candidate_match is False


@pytest.mark.parametrize("shape", ["sparse", "named", "zero", "empty"])
def test_caller_word_conversion_never_silently_drops_malformed_entries(shape):
    candidate = Candidate()
    assert candidate.inspect().candidate_match is True
    word = candidate.primary["caller_stack"]["required_words"][0]
    wrong = {**word, "value": word["value"] ^ 1}
    words = {1: word, 3: wrong} if shape == "sparse" else (
        {1: word, "extra": wrong} if shape == "named" else ({0: wrong, 1: word} if shape == "zero" else {})
    )
    candidate.primary["caller_stack"]["required_words"] = words
    report = candidate.inspect()
    assert report.candidate_match is False and "caller words" in report.reason
    assert report.runtime_authorized is False


# --- the gate's pure helpers under lupa ---------------------------------------------------------

def gate():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("SLINK_GEN2_GATE_LIBRARY = true")
    return lua, lua.eval("dofile")((ROOT / "lua/tests/gen2_write_windows.lua").as_posix())


def test_window_for_names_each_negative_by_its_phase_and_state():
    lua, U = gate()

    def point(**kw):
        return lua.table_from({"battle_mode": 0, "game_paused": 0, "map_status": 2, **kw}, recursive=True)
    assert U.window_for("idle", point()) is None
    assert U.window_for("walk", point(battle_mode=1)) == "battle"
    assert U.window_for("save", point(game_paused=1)) == "save_paused"
    assert U.window_for("exit", point(map_status=1)) == "mid_warp"
    assert U.window_for("idle", point(map_status=1)) is None
    assert U.window_for("start_menu", point(ui={"kind": "start_menu"})) == "start_menu"
    assert U.window_for("talk", point(ui={"kind": "wait_button"})) == "script_text"
    assert U.window_for("face", point(ui={"kind": "text"})) is None


def test_driver_waits_for_the_idle_write_and_a_fresh_hold_before_each_negative():
    lua, U = gate()
    driver = U.driver("town", lua.table_from({}))

    def step(**kw):
        return driver.step(lua.table_from({"overworld_ready": True, "accepted": 0, "write_done": False,
                                           "window_frames": 0, **kw}, recursive=True))
    buttons, phase = step(accepted=3)
    assert phase == "idle" and len(buttons) == 0          # no START before the idle write landed
    buttons, phase = step(accepted=3, write_done=True)
    assert phase == "start_menu" and buttons["Start"] is True
    buttons, phase = step(write_error="refused")
    assert buttons is None and "idle hold write refused" in phase


def test_step_toward_routes_around_objects_on_the_source_grid():
    lua, U = gate()
    map_ = lua.table_from({"width": 3, "height": 3, "grid": [1] * 9, "warps": []}, recursive=True)
    point = lua.table_from({"x": 0, "y": 0, "can_step": {"Up": False, "Down": True, "Left": False, "Right": True},
                            "blocked": [{"x": 1, "y": 0}]}, recursive=True)
    assert U.step_toward(map_, point, lua.table_from({"x": 2, "y": 0})) == "Down"
    assert U.step_toward(map_, lua.table_from({"x": 2, "y": 0}), lua.table_from({"x": 2, "y": 0})) == "arrived"


# --- the WHOLE gate on a synthetic cartridge (MODEL; never PHYSICAL evidence) --------------------

def _sim_classes():
    """Imported lazily: the synthetic cartridge needs the pinned decomp build (as its home tests do)."""
    from tests.unit.test_gen2_inspect_gate import InspectSim, inspect_root
    from tests.unit.test_gen2_scripted_gate import context, qualify_env

    class U2Sim(InspectSim):
        """InspectSim plus the pieces the U2 gate touches: the checkpoint PC executed after every
        overworld tick, a System Bus view of WRAM/SVBK/serial (SRAM reads $FF: closed), the caller word
        on a WRAM0 stack, the START menu as the game runs it (CheckMenuOW -> CallScript sets
        wScriptRunning, PlayerEvents .ok sets wScriptMode, and the menu loop never returns to
        OWPlayerInput), Elm's script text, a native save (PauseGameLogic, SaveBox, sPokemonData),
        the lab exit warp (wMapStatus != MAPSTATUS_HANDLE) and one Route 29 wild battle."""

        def __init__(self, lua, title="crystal", mode="town"):
            self.mode = mode
            self.primary = json.loads((ROOT / f"data/games/gen2_{title}/write_checkpoint.json")
                                      .read_text())["titles"][title]["primary"]
            self.sp = self.primary["caller_stack"]["minimum_sp"] + 0x10
            super().__init__(lua, title)
            self.where = ("Route29", 53, 12) if mode == "battle" else ("ElmsLab", 5, 3)
            self.carry = None   # (party wram slice, cart, flushed file) a reload boots with
            # falsifier switches
            self.leak_menu = self.silent_menu = self.silent_script = self.no_pause = False
            self.in_menu = False

        def boot_with(self, carry):
            self.carry = carry
            self.cart[:len(carry[1])] = carry[1]   # the cold-booted file is in CartRAM before frame 1

        def bus(self, address):
            return address - 0xC000 if address < 0xD000 else 0x1000 + address - 0xD000

        def read_u8(self, address, domain):
            if domain == "System Bus":
                if 0xC000 <= address < 0xE000:
                    return self.wram[self.bus(address)]
                if 0xA000 <= address < 0xC000:
                    return 0xFF
                if address in (0xFF70, 0xFF02):
                    return {0xFF70: 1, 0xFF02: 0}[address]
            return super().read_u8(address, domain)

        def write_u8(self, address, value, domain):
            self.writes.append((str(domain), int(address), int(value)))
            if domain == "CartRAM":
                self.cart[address] = value
            elif domain == "System Bus":
                assert 0xC000 <= address < 0xE000, address
                self.wram[self.bus(address)] = value
            else:
                self.wram[address] = value

        def set_bus(self, symbol, value):
            row = next(r for r in self.primary["state_predicates"] if r["symbol"] == symbol)
            if row["address"] >= 0xFF80:
                self.hram[row["address"] - 0xFF80] = value
            else:
                self.wram[self.bus(row["address"])] = value

        def load(self):
            super().load()
            for row in self.primary["state_predicates"]:
                self.set_bus(row["symbol"], row["value"])
            word = self.primary["caller_stack"]["required_words"][0]["value"]
            self.wram[self.bus(self.sp):self.bus(self.sp) + 2] = bytes([word & 255, word >> 8])
            if self.carry:
                party, cart = self.carry[:2]
                start = self.offset("wPartyCount")
                self.wram[start:start + len(party)] = party
                self.cart[:] = cart

        def install(self, env):
            super().install(env)
            glob, lua = self.lua.globals(), self.lua
            glob.memory.getmemorydomainlist = lambda: lua.table_from(["ROM", "System Bus", "WRAM", "CartRAM"])
            glob.emu.getregister = lambda name: {"PC": self.pc, "SP": self.sp}[name]

        def overworld(self):
            self.fire("overworld_tick")
            self.run_at(self.primary["execution_before"]["bank"], self.primary["execution_before"]["pc"])

        def advance(self):
            if self.leak_menu and self.in_menu:   # falsifier: the checkpoint PC runs under the START menu
                self.run_at(self.primary["execution_before"]["bank"], self.primary["execution_before"]["pc"])
            super().advance()

        def start_menu(self):
            if not self.silent_menu:
                self.set_bus("wScriptRunning", 1)   # CallScript: PLAYEREVENT_MAPSCRIPT
                self.set_bus("wScriptMode", 1)      # EnableScriptMode: SCRIPT_READ
            items = ["#DEX", "#MON", "PACK", self.player_name, "SAVE", "OPTION", "EXIT"]
            self.in_menu = True
            chosen = yield from self.menu_select("start_menu", items, at=(8, 0))
            self.in_menu = False
            if chosen == "SAVE":
                yield from self.native_save()
            self.set_bus("wScriptRunning", 0)
            self.set_bus("wScriptMode", 0)

        def elm_talk(self):
            if not self.silent_script:
                self.set_bus("wScriptRunning", 1)
                self.set_bus("wScriptMode", 1)
            yield from self.text("MR.#MON lives a", kind="wait_button")
            self.set_bus("wScriptRunning", 0)
            self.set_bus("wScriptMode", 0)

        def native_save(self):
            yield from self.save_yes_no("Would you like to", "save the game?")
            self.fire("same_save_file")
            yield from self.text("There is already a", "save file. Is it")
            yield from self.save_yes_no("save file. Is it", "OK to overwrite?")
            if not self.no_pause:
                self.set_bus("wGameLogicPaused", 1)
            yield from self.wait(4)
            pokemon = context(self.title).symbol("sPokemonData")
            ram = self.prof["ram"]
            at = pokemon.bank * 0x2000 + pokemon.address - 0xA000 + ram["wPartyMon1HP"] - ram["wPokemonData"]
            hp = self.offset("wPartyMon1HP")
            self.cart[at:at + 2] = self.wram[hp:hp + 2]
            active = self.prof["derived"]["active_box_flat"]
            backing = self.prof["storage_boxes"][self.get("wCurBox")]["flat"]
            self.cart[backing:backing + 1102] = self.cart[active:active + 1102]   # SaveBox
            self.fire("save_completed")
            yield from self.wait(6)
            self.set_bus("wGameLogicPaused", 0)

        def teleport(self, warp):
            self.set_bus("wMapStatus", 1)
            self.set_bus("hMapEntryMethod", 1)
            yield from super().teleport(warp)
            self.set_bus("wMapStatus", 2)
            self.set_bus("hMapEntryMethod", 0)

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
            self.fire("rtc_ok")
            yield from self.wait(20)
            self.fire("finish_continue")
            yield from self.enter(*self.where)
            elm = self.facts["maps"]["ElmsLab"]["objects"]["ProfElmScript"]
            battled = False
            while True:
                self.overworld()
                got = yield
                if "Start" in got.edges:
                    yield from self.start_menu()
                    continue
                if ("A" in got.edges and self.map == "ElmsLab" and self.facing == "Up"
                        and (self.x, self.y - 1) == (elm["x"], elm["y"])):
                    yield from self.elm_talk()
                    continue
                held = [d for d in ("Up", "Down", "Left", "Right") if d in got.held]
                if not held:
                    continue
                direction = self.facing = held[0]
                area = self.facts["maps"][self.map]
                here = next((w for w in area["warps"] if (w["x"], w["y"]) == (self.x, self.y)), None)
                if here and here["carpet"] == direction:
                    yield from self.teleport(here)
                    continue
                dx, dy = {"Up": (0, -1), "Down": (0, 1), "Left": (-1, 0), "Right": (1, 0)}[direction]
                if self.tile(self.x + dx, self.y + dy):
                    self.x, self.y = self.x + dx, self.y + dy
                self.sync()
                if self.map == "Route29" and self.tile(self.x, self.y) == 2 and not battled:
                    battled = True
                    self.set_bus("wBattleMode", 1)
                    yield from self.battle()
                    self.set_bus("wBattleMode", 0)

    return U2Sim, inspect_root, qualify_env


GATE_FILES = ("lua/gen2_write_safety.lua", "lua/gb_checkpoint.lua", "lua/gen2/writes.lua", "lua/gen2/boxes.lua",
              "lua/tests/gen2_inspect_gate.lua", "lua/tests/gen2_write_windows.lua")
QUALIFICATION = {"town": "requal-town-sim", "battle": "requal-battle-sim"}
# The gate as a LIBRARY caller runs it: the same steps as its BizHawk entry, but the api is not that
# entry's own, so every run record it prints is MODEL.
LIBRARY_ENTRY = """
SLINK_GEN2_GATE_LIBRARY = true
local root = os.getenv("SLINK_ROOT")
local U = dofile(root .. "/lua/tests/gen2_write_windows.lua")
local IG = U.inspect_gate(root)
local SG = IG.scripted_gate(root)
local api = SG.bizhawk()
api.domains = function() return memory.getmemorydomainlist() end
U.main(api, os.getenv, SG, IG)
"""


def run_u2(tmp_path, mode, *, title="crystal", carry=None, **switches):
    U2Sim, inspect_root, qualify_env = _sim_classes()
    root = inspect_root(tmp_path / f"{title}-{mode}", title)
    for rel in GATE_FILES + (f"data/games/gen2_{title}/write_checkpoint.json",):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes((ROOT / rel).read_bytes())
    spec, env = qualify_env(root, title, "battle" if mode == "battle" else "town", "boot")
    case = json.loads(env["SLINK_GEN2_FIXTURE_CASE"])
    case["attempt_id"] = f"u2-{title}-{mode}"
    env["SLINK_GEN2_FIXTURE_CASE"] = json.dumps(case)
    env["SLINK_GEN2_U2"] = json.dumps({"mode": mode, "qualification_attempt_id":
                                       QUALIFICATION["battle" if mode == "battle" else "town"]})
    sim = U2Sim(LuaRuntime(unpack_returned_tuples=True), title, mode)
    if carry is not None:
        sim.boot_with(carry)
        q = json.loads(env["SLINK_GEN2_QUALIFY"])
        q["stage_fingerprint"] = hashlib.sha256(carry[2]).hexdigest()   # the reload candidate file
        env["SLINK_GEN2_QUALIFY"] = json.dumps(q)
    for name, value in switches.items():
        setattr(sim, name, value)
    sim.install(env)
    sim.lua.execute(LIBRARY_ENTRY)
    text = (root / "patch/build/gen2_write_windows_result.txt").read_text(encoding="utf-8")
    return sim, text


def _snapshot(sim):
    """The town gate's kept post-save image: the live lane's persistence evidence and reload candidate."""
    return u2.saved_image(Path(sim.saveram_path).parent, f"{sim.title}_town")


def _carry(sim):
    start = sim.offset("wPartyCount")
    saved = _snapshot(sim).read_bytes()
    return (bytes(sim.wram[start:start + PROFILE[sim.title]["ram"]["wPartyMonNicknamesEnd"]
                          - PROFILE[sim.title]["ram"]["wPartyCount"]]),
            saved[:u2.CART_RAM_BYTES], saved)


PROFILE = {t: json.loads((ROOT / f"data/games/gen2_{t}/profile.json").read_text())["titles"][t]
           for t in ("crystal", "gold")}


def pack_of(title):
    return json.loads((ROOT / f"data/games/gen2_{title}/write_checkpoint.json").read_text())


@pytest.fixture(scope="module")
def sim_runs(tmp_path_factory):
    """title -> the WHOLE gate's town/reload/battle runs on the synthetic cartridge, with the texts and the
    town sim (for the Python verifiers)."""
    out = {}
    for title in ("crystal", "gold"):
        tmp = tmp_path_factory.mktemp(f"u2-{title}")
        town_sim, town_text = run_u2(tmp, "town", title=title)
        carry = _carry(town_sim)
        reload_sim, reload_text = run_u2(tmp, "reload", title=title, carry=carry)
        _, battle_text = run_u2(tmp, "battle", title=title)
        texts = {"town": town_text, "reload": reload_text, "battle": battle_text}
        for mode, text in texts.items():
            assert text.strip().splitlines()[-1].startswith("RESULT: PASS"), (title, mode, text[-3000:])
        out[title] = {"texts": texts, "town_sim": town_sim, "candidate": carry[2],
                      "runs": {mode: live_tag(text, "U2_RUN") for mode, text in texts.items()}}
    return out


def live_tag(text, tag):
    from tests.live import test_gen2_new_gates as live
    return live.tag_json(text, tag)


def forged(sim_runs, title):
    """TEST FORGERY: the synthetic runs are MODEL; relabel them PHYSICAL only to exercise acceptance."""
    runs = copy.deepcopy(sim_runs[title]["runs"])
    for run in runs.values():
        assert run["evidence_level"] == "MODEL"
        run["evidence_level"] = "PHYSICAL"
    return runs


def receipt_for(sim_runs, title):
    """The receipt the live lane builds, for the title whose run may authorize `title`."""
    owner = {"crystal": "crystal", "gold": "gold", "silver": "gold"}[title]
    return u2.build_receipt(owner, pack_of(owner), forged(sim_runs, owner))


def reports_for(receipt):
    """Passed full-chain qualification reports recording exactly the runs' fixture bytes and attempts."""
    out = {}
    for mode in ("town", "battle"):
        run = receipt["runs"][mode]
        out[run["fixture"]] = {"schema": "fixture-qualification-v1", "passed": True, "errors": [],
                               "scope": "full", "required_stages": ["qualify", "boot", "resave", "post_oracle"],
                               "attempt_id": run["qualification_attempt_id"],
                               "fixtures": [{"name": run["fixture"], "passed": True,
                                             "artifacts": {"fixture": {"sha256": run["fixture_sha256"]}},
                                             "provenance": {"title": run["title"], "rom_sha1": run["rom_sha1"]}}]}
    return out


def test_the_synthetic_gate_prints_model_runs_that_never_authorize(sim_runs):
    """Finding 2: PHYSICAL comes only from the gate's own BizHawk entry; a library/lupa run is MODEL."""
    runs = sim_runs["crystal"]["runs"]
    assert {run["evidence_level"] for run in runs.values()} == {"MODEL"}
    receipt = u2.build_receipt("crystal", pack_of("crystal"), copy.deepcopy(runs))
    assert "evidence_level" not in receipt
    scope, why = u2.lua_qualified(pack_of("crystal"), "crystal", receipt)
    assert scope is None and "PHYSICAL" in why
    assert Candidate().check(receipt)[0] is False


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_physical_receipt_authorizes_only_proven_kinds_in_the_held_idle_frame(sim_runs, title):
    candidate = Candidate(title)
    receipt = receipt_for(sim_runs, title)
    assert candidate.check()[0] is False
    for kind in ("party_hp", "box_deposit"):
        accepted, why = candidate.check(receipt, kind)
        assert accepted is True, why
    for kind in (None, "faint", "box_other", "party_species"):   # finding 6: only the proven write kinds
        accepted, why = candidate.check(receipt, kind)
        assert accepted is False and "write kind not covered" in why
    assert candidate.inspect().runtime_authorized is False
    candidate.registers["PC"] += 1   # not the held checkpoint instruction
    assert candidate.check(receipt)[0] is False


def test_the_receipt_scope_names_every_pack_control_it_leaves_open(sim_runs):
    """Finding 6: covered controls are declared and bounded by the pack; the rest is reported OPEN."""
    pack = pack_of("crystal")
    scope, why = u2.lua_qualified(pack, "crystal", receipt_for(sim_runs, "crystal"))
    assert scope is not None, why
    required = pack["titles"]["crystal"]["physical"]["required_controls"]
    assert scope["kinds"] == ["box_deposit", "party_hp"]
    assert scope["covered"] == sorted(u2.COVERED_CONTROLS)
    assert scope["uncovered"] == [c for c in required if c not in u2.COVERED_CONTROLS]
    assert "START and nested menus" in scope["uncovered"] and "save/box-load/overwrite" in scope["uncovered"]
    assert pack["titles"]["crystal"]["physical"]["status"] == "OPEN"   # the pack stays SOURCE/OPEN


def test_silver_follows_gold_only_from_the_pinned_gold_rom_with_identical_rows(sim_runs):
    gold = json.loads((ROOT / "data/games/gen2_gold/write_checkpoint.json").read_text())["titles"]["gold"]
    silver = json.loads((ROOT / "data/games/gen2_silver/write_checkpoint.json").read_text())["titles"]["silver"]
    assert gold == silver
    assert pack_of("gold")["source"]["rom_sha1"] == "d8b8a3600a465308c9953dfa04f0081c05bdcb94"
    candidate = Candidate("silver")
    candidate.primary["state_predicates"][0]["reason"] = "drifted"
    accepted, why = candidate.check(receipt_for(sim_runs, "silver"))
    assert accepted is False and "other checkpoint rows" in why
    # Finding 3: a "gold" receipt from any ROM other than Gold's pinned one never covers Silver.
    receipt = receipt_for(sim_runs, "silver")
    receipt["rom_sha1"] = pack_of("silver")["source"]["rom_sha1"]
    for run in receipt["runs"].values():
        run["rom_sha1"] = receipt["rom_sha1"]
    accepted, why = Candidate("silver").check(receipt)
    assert accepted is False and "another title, ROM or pack" in why


def test_a_gold_receipt_never_authorizes_crystal(sim_runs):
    accepted, why = Candidate("crystal").check(receipt_for(sim_runs, "gold"))
    assert accepted is False and "another title" in why


def _set(receipt, path, value):
    node = receipt
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    last = keys[-1]
    if value is DELETE:
        del node[last]
    elif isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


DELETE = object()

# Binding faults (finding 1): each run is bound to title/ROM/pack/fixture/attempt/CGB/buttons/scopes.
BINDING_FAULTS = {
    "schema": ("schema", "gen2-write-window-receipt-v1", "PHYSICAL write-window receipt required"),
    "model_run": ("runs.battle.evidence_level", "MODEL", "battle run is not a passed PHYSICAL"),
    "failed_run": ("runs.reload.result", "FAIL", "reload run is not a passed PHYSICAL"),
    "rom": ("rom_sha1", "0" * 40, "another title, ROM or pack"),
    "run_rom": ("runs.town.rom_sha1", "0" * 40, "town run is not bound"),
    "pack_commit": ("pack_commit", "0" * 40, "another title, ROM or pack"),
    "run_pack_commit": ("runs.battle.pack_commit", "0" * 40, "battle run is not bound"),
    "rows": ("checkpoint.state_predicates.0.value", 3, "other checkpoint rows"),
    "fixture": ("runs.battle.fixture", "crystal_town", "battle run is not bound"),
    "core_mode": ("runs.town.core_mode", "DMG", "town run is not bound"),
    "input_mode": ("runs.town.input_mode", "poke", "town run is not bound"),
    "fixture_sha256": ("runs.battle.fixture_sha256", "no", "battle run is not bound"),
    "attempt_reused": ("runs.reload.attempt_id", "u2-crystal-town", "reload run is not bound"),
    "no_qualification_attempt": ("runs.battle.qualification_attempt_id", "", "battle run is not bound"),
    "extra_scope": ("runs.town.harness_write_scopes", ["u2-negative-start_menu", "u2-test-box-write",
                                                        "u2-test-party-write"], "town run wrote outside"),
    "battle_wrote": ("runs.battle.harness_write_scopes", ["u2-negative-battle-faint"], "battle run wrote outside"),
    "missing_scope": ("runs.town.harness_write_scopes", ["u2-test-party-write"], "town run wrote outside"),
    "overclaimed_control": ("covered_controls", ["idle reacquisition", "warp/Continue", "textbox"], "did not prove: textbox"),
    "reload_other_boot": ("runs.reload.boot_cartram_sha256", "0" * 64, "cold-boot"),
    "reload_same_file": ("runs.reload.fixture_sha256", None, "cold-boot"),   # None: the town fixture
    "reload_other_lineage": ("runs.reload.qualification_attempt_id", "requal-other", "cold-boot"),
    "reload_lost_hp": ("runs.reload.persist.party_hp_hex", "0000", "persistence proof"),
    "reload_lost_box": ("runs.reload.persist.active_box_hex", "00", "reload lacks"),
}


@pytest.mark.parametrize("fault", sorted(BINDING_FAULTS))
def test_receipt_binding_refuses(sim_runs, fault):
    receipt = receipt_for(sim_runs, "crystal")
    path, value, expected = BINDING_FAULTS[fault]
    if fault == "reload_same_file":
        value = receipt["runs"]["town"]["fixture_sha256"]
    _set(receipt, path, value)
    accepted, why = Candidate().check(receipt)
    assert accepted is False and expected in why, why


def _window(receipt, run, name):
    return receipt["runs"][run]["windows"][name]


# Control recomputation (findings 1, 4, 5, 8, 9): every verdict comes from the raw records.
def _control_fault(receipt, fault):
    town, battle = receipt["runs"]["town"], receipt["runs"]["battle"]
    start = _window(receipt, "town", "start_menu")
    if fault == "start_accepted":
        start["accepted"] = 1
    elif fault == "start_anchor_fired":         # refused by predicates, but the anchor ran in the menu
        start["raw"] = 1
    elif fault == "start_short":
        start["frames"] = 29
    elif fault == "start_not_script":           # the menu frames pass wScriptRunning/wScriptMode
        start["failing_sets"] = [{"symbols": ["wMapStatus"], "frames": start["frames"]}]
    elif fault == "start_frame_unexplained":    # one frame with no failing predicate at all
        start["failing_sets"][0]["frames"] -= 1
        start["failing_sets"].append({"symbols": [], "frames": 1})
    elif fault == "start_no_both_edges":
        start["both_edges"] = 0
    elif fault == "script_wrong_predicate":
        _window(receipt, "town", "script_text")["failing_sets"] = [
            {"symbols": ["wMapStatus"], "frames": _window(receipt, "town", "script_text")["frames"]}]
    elif fault == "warp_one_frame":
        warp = _window(receipt, "town", "mid_warp")
        warp["frames"], warp["both_edges"] = 1, 0
        warp["failing_sets"] = [{"symbols": ["wMapStatus"], "frames": 1}]
    elif fault == "save_unwitnessed":
        del town["windows"]["save_paused"]
    elif fault == "save_accepted":
        _window(receipt, "town", "save_paused")["accepted"] = 1
    elif fault == "write_changed_bytes":
        _window(receipt, "town", "mid_warp")["write"]["after_hex"] = "0001"
    elif fault == "write_went_through":
        _window(receipt, "town", "script_text")["write"]["refused"] = False
    elif fault == "battle_faint":
        _window(receipt, "battle", "battle")["write"]["faint_refused"] = False
    elif fault == "battle_accepted":
        _window(receipt, "battle", "battle")["accepted"] = 2
    elif fault == "hit_off_pc":
        town["liveness"]["hits"][0]["pc"] += 1
    elif fault == "hit_off_bank":
        battle["liveness"]["hits"][0]["bank"] ^= 1
    elif fault == "no_reacquire":
        entries = town["phases"]
        done = next(e for e in entries if e["phase"] == "done")
        done["accepted"] = next(e for e in entries if e["phase"] == "post_warp")["accepted"]
    elif fault == "party_not_minus_one":
        town["write"]["party"]["written_hex"] = town["write"]["party"]["readback_hex"] = "0000"
    elif fault == "box_count":
        box = town["write"]["box"]
        box["after_hex"] = box["readback_hex"] = box["before_hex"]
    elif fault == "backing_already_held":
        town["write"]["box"]["backing_before_hex"] = town["write"]["box"]["after_hex"]
    elif fault == "save_not_flushed":
        town["save"]["flushed"] = False
    elif fault == "start_one_edge":             # 30 frames, but only one of them open at both edges
        start["both_edges"] = 1
    elif fault == "phase_unnamed":              # U2b-review L1: threw "table index is nil"
        del town["phases"][0]["phase"]


CONTROL_FAULTS = {
    "start_accepted": "start_menu: no accepted checkpoint hold",
    "start_anchor_fired": "start_menu: the OWPlayerInput anchor fired",
    "start_short": "start_menu window not observed for 30",
    "start_not_script": "start_menu: the stated predicate",
    "start_frame_unexplained": "start_menu: the stated predicate",
    "start_no_both_edges": "start_menu: no accepted checkpoint hold",
    "script_wrong_predicate": "script_text: the stated predicate",
    "warp_one_frame": "mid_warp window not observed for 2",
    "save_unwitnessed": "save_paused window not observed",
    "save_accepted": "save_paused: no accepted checkpoint hold",
    "write_changed_bytes": "mid_warp: a party write attempt",
    "write_went_through": "script_text: a party write attempt",
    "battle_faint": "faint_party_slot refuses",
    "battle_accepted": "battle: no accepted checkpoint hold",
    "hit_off_pc": "town run: an accepted hold ran at a measured PC",
    "hit_off_bank": "battle run: an accepted hold ran at a measured PC",
    "no_reacquire": "between phases post_warp and done",
    "party_not_minus_one": "not a read-back HP-1",
    "box_count": "count+1 write",
    "backing_already_held": "backing box slot already held",
    "save_not_flushed": "native save not flushed",
    "start_one_edge": "start_menu: no accepted checkpoint hold",
    "phase_unnamed": "town run: a phase entry names no phase",
}


@pytest.mark.parametrize("fault", sorted(CONTROL_FAULTS))
def test_every_control_is_recomputed_from_the_raw_records(sim_runs, fault):
    receipt = receipt_for(sim_runs, "crystal")
    _control_fault(receipt, fault)
    scope, why = u2.lua_qualified(pack_of("crystal"), "crystal", receipt)
    assert scope is None and CONTROL_FAULTS[fault] in why, why


def test_a_malformed_receipt_refuses_with_a_reason_instead_of_raising(sim_runs):
    """U2b-review L1: M.new guards M.qualified, so a receipt that raises on access never escapes check()."""
    receipt = receipt_for(sim_runs, "crystal")
    del receipt["runs"]["town"]["phases"][0]["phase"]
    accepted, why = Candidate().check(receipt)
    assert accepted is False and "names no phase" in why, why
    c = Candidate()
    hostile = c.lua.eval('setmetatable({}, {__index=function() error("boom") end})')
    binder = c.module.new(c.lua.table_from(c.pack, recursive=True), "crystal", c.io, c.evaluator,
                          c.ownership, hostile)
    accepted, why = binder.check(binder, "party_hp")
    assert accepted is False and "malformed write-window receipt" in why and "boom" in why, why


def test_the_lua_full_chain_matches_fixture_qualification():
    sys.path.insert(0, str(ROOT / "tools"))
    import fixture_qualification
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")((ROOT / "lua/gen2_write_safety.lua").as_posix())
    assert tuple(module.FULL_CHAIN.values()) == fixture_qualification.FULL_CHAIN


def test_the_committed_crystal_receipt_still_qualifies_and_binds():
    """U2c keeps the receipt schema: the PHYSICAL Crystal receipt (6ba4527) passes M.qualified and
    M.bind_fixture_qualification against its fixtures' committed qualification reports."""
    receipts = ROOT / "tests/fixtures/gen2/receipts"
    receipt = json.loads((receipts / "crystal.write_window.json").read_text(encoding="utf-8"))
    assert {run["evidence_level"] for run in receipt["runs"].values()} == {"PHYSICAL"}
    scope, why = u2.lua_qualified(pack_of("crystal"), "crystal", receipt)
    assert scope is not None, why
    assert scope["kinds"] == ["box_deposit", "party_hp"]
    reports = {name: json.loads((receipts / f"{name}.qualification.json").read_text(encoding="utf-8"))
               for name in ("crystal_town", "crystal_battle")}
    bound, why = u2.lua_bind(receipt, reports)
    assert bound is True, why


def test_the_synthetic_runs_record_the_real_window_mechanisms(sim_runs):
    """Finding 4: the START menu is refused by wScriptRunning/wScriptMode on every frame and its anchor
    never runs; each window carries raw hits, both-edge frames and the attempted write's bytes."""
    runs = sim_runs["crystal"]["runs"]
    start = runs["town"]["windows"]["start_menu"]
    assert start["raw"] == 0 and start["accepted"] == 0 and start["both_edges"] == start["frames"] - 1
    assert all({"wScriptRunning", "wScriptMode"} <= set(s["symbols"]) for s in start["failing_sets"])
    assert sum(s["frames"] for s in start["failing_sets"]) == start["frames"]
    assert runs["town"]["windows"]["save_paused"]["frames"] >= 2
    for window in runs["town"]["windows"].values():
        assert window["write"]["refused"] is True and window["write"]["before_hex"] == window["write"]["after_hex"]
    assert runs["town"]["harness_write_scopes"] == ["u2-test-box-write", "u2-test-party-write"]
    assert runs["battle"]["harness_write_scopes"] == [] and runs["reload"]["harness_write_scopes"] == []


BIND_FAULTS = {"attempt": lambda r: r.update(attempt_id="requal-other"),
               "bytes": lambda r: r["fixtures"][0]["artifacts"]["fixture"].update(sha256="1" * 64),
               "failed": lambda r: r.update(passed=False),
               "errors": lambda r: r.update(errors=["x"]),
               "row": lambda r: r["fixtures"][0].update(name="crystal_town_ot2"),
               "rom": lambda r: r["fixtures"][0]["provenance"].update(rom_sha1="0" * 40),
               "scope": lambda r: r.update(scope="static"),
               "stages": lambda r: r.update(required_stages=["qualify", "boot"])}


@pytest.mark.parametrize("fault", [None, *sorted(BIND_FAULTS)])
def test_bind_fixture_qualification(sim_runs, fault):
    receipt = receipt_for(sim_runs, "crystal")
    reports = reports_for(receipt)
    if fault:
        BIND_FAULTS[fault](reports[receipt["runs"]["battle" if fault == "bytes" else "town"]["fixture"]])
    bound, why = u2.lua_bind(receipt, reports)
    assert (bound is True) if fault is None else (bound is None and why), why


# --- the live lane's Python re-derivations on the synthetic gate output --------------------------

def _symbols(title):
    from tests.unit.test_gen2_scripted_gate import context
    return context(title).symbols


def _town_inputs(sim_runs, title="crystal"):
    sim = sim_runs[title]["town_sim"]
    return (sim_runs[title]["texts"]["town"], pack_of(title)["titles"][title]["primary"], _symbols(title),
            _snapshot(sim).read_bytes(), bytes(sim.booted))


def test_persistence_is_checked_on_the_post_save_snapshot_not_the_exit_time_file(sim_runs):
    """U2c (Gold live failure): the gate keeps playing after the flush, and on Gold/Silver the menu close
    and overworld rewrite the SRAM window stack and sScratch, so EmuHawk's exit-time SaveRAM is not the
    post-save image. The gate keeps the flushed bytes; the wrapper verifies (and reloads) those."""
    text, primary, symbols, snapshot, staged = _town_inputs(sim_runs, "gold")
    sim = sim_runs["gold"]["town_sim"]
    run = live_tag(text, "U2_RUN")
    assert snapshot == Path(sim.saveram_path).read_bytes()   # the flushed file, byte for byte (RTC trailer too)
    assert len(snapshot) == u2.CART_RAM_BYTES + 22
    assert hashlib.sha256(snapshot[:u2.CART_RAM_BYTES]).hexdigest() == run["save"]["cartram_sha256"]
    exit_time = bytearray(snapshot)   # what the lane's SaveRAM holds after the post-save window close
    scratch = u2.sram_flat(symbols["sScratch"].bank, symbols["sScratch"].address)
    exit_time[scratch] ^= 0xFF
    with pytest.raises(AssertionError, match="flushed SaveRAM differs"):
        u2.verify_town(text, primary, symbols, bytes(exit_time), staged)   # the old wrapper's input
    assert u2.verify_town(text, primary, symbols, snapshot, staged)["mode"] == "town"
    tampered = bytearray(snapshot)
    tampered[scratch] ^= 1
    with pytest.raises(AssertionError, match="flushed SaveRAM differs"):
        u2.verify_town(text, primary, symbols, bytes(tampered), staged)
    assert sim_runs["gold"]["candidate"] == snapshot   # the reload cold-booted the snapshot


def test_python_verifiers_accept_the_synthetic_runs(sim_runs):
    text, primary, symbols, saved, staged = _town_inputs(sim_runs)
    town = u2.verify_town(text, primary, symbols, saved, staged)
    reload = u2.verify_reload(sim_runs["crystal"]["texts"]["reload"], primary, symbols, town,
                              sim_runs["crystal"]["candidate"])
    battle = u2.verify_battle(sim_runs["crystal"]["texts"]["battle"], primary)
    assert (town["mode"], reload["mode"], battle["mode"]) == ("town", "reload", "battle")


def test_python_persistence_offsets_come_from_the_pinned_sym(sim_runs):
    """Finding 7: sym-derived offsets agree with the profile's, and the staged bytes must differ."""
    symbols = _symbols("crystal")
    off = u2.offsets(symbols, 0)
    derived = PROFILE["crystal"]["derived"]
    assert (off["active"], off["length"], off["backing"]) == (derived["active_box_flat"],
                                                              derived["active_box_copy_length"],
                                                              PROFILE["crystal"]["storage_boxes"][0]["flat"])
    text, primary, symbols, saved, staged = _town_inputs(sim_runs)
    run = live_tag(text, "U2_RUN")
    after = bytes.fromhex(run["write"]["box"]["after_hex"])
    already = bytearray(staged)
    already[off["backing"]:off["backing"] + off["length"]] = after
    with pytest.raises(AssertionError, match="backing box slot already held"):
        u2.verify_town(text, primary, symbols, saved, bytes(already))
    already = bytearray(staged)
    already[off["party_hp"]:off["party_hp"] + 2] = bytes.fromhex(run["write"]["party"]["written_hex"])
    with pytest.raises(AssertionError, match="saved party HP already held"):
        u2.verify_town(text, primary, symbols, saved, bytes(already))


@pytest.mark.parametrize("flip, why", [("party_hp", "party HP not saved"),
                                        ("backing", "native SaveBox did not copy"),
                                        (None, "flushed SaveRAM differs")])
def test_town_verifier_refuses_an_unsaved_write_a_missing_backing_copy_or_another_file(sim_runs, flip, why):
    text, primary, symbols, saved, staged = _town_inputs(sim_runs)
    off = u2.offsets(symbols, 0)
    cart = bytearray(saved)
    run = live_tag(text, "U2_RUN")
    if flip is None:
        cart[5] ^= 1   # another file than the one the gate hashed
    else:
        cart[off[flip]] ^= 1   # a flushed file whose own hash the gate recorded, without the written byte
        run["save"]["cartram_sha256"] = hashlib.sha256(bytes(cart[:u2.CART_RAM_BYTES])).hexdigest()
    text = "U2_RUN " + json.dumps(run) + "\nRESULT: PASS u2 (0 checks failed)"
    with pytest.raises(AssertionError, match=why):
        u2.verify_town(text, primary, symbols, bytes(cart), staged)


@pytest.mark.parametrize("fault", ["hit_pc", "reacquire"])
def test_python_liveness_rederivation(sim_runs, fault):
    """Finding 8: liveness from the phases and the MEASURED PC/hROMBank, independently of Lua."""
    run = copy.deepcopy(sim_runs["crystal"]["runs"]["battle"])
    primary = pack_of("crystal")["titles"]["crystal"]["primary"]
    u2.verify_liveness(run, primary)
    if fault == "hit_pc":
        run["liveness"]["hits"][-1]["pc"] ^= 1
    else:
        for entry in run["phases"]:
            if entry["phase"] == "done":
                entry["accepted"] = next(e["accepted"] for e in run["phases"] if e["phase"] == "post_battle")
    with pytest.raises(AssertionError):
        u2.verify_liveness(run, primary)


def test_reload_verifier_needs_the_town_flush(sim_runs):
    text, primary, symbols, saved, staged = _town_inputs(sim_runs)
    town = u2.verify_town(text, primary, symbols, saved, staged)
    town["save"]["cartram_sha256"] = "0" * 64
    with pytest.raises(AssertionError, match="cold-boot"):
        u2.verify_reload(sim_runs["crystal"]["texts"]["reload"], primary, symbols, town,
                         sim_runs["crystal"]["candidate"])


# --- whole-gate falsifiers: the gate itself fails when a window lacks its real mechanism -----------

@pytest.mark.parametrize("switch, failed", [
    ("leak_menu", "start_menu: the OWPlayerInput anchor fired inside the window"),
    ("silent_menu", "start_menu: the stated predicate refuses every window frame"),
    ("silent_script", "script_text: the stated predicate refuses every window frame"),
    ("no_pause", "save_paused window not observed for 2 frames"),
])
def test_whole_gate_fails_when_a_window_is_not_refused_by_its_stated_mechanism(tmp_path, switch, failed):
    _, text = run_u2(tmp_path, "town", **{switch: True})
    assert text.strip().splitlines()[-1].startswith("RESULT: FAIL"), text[-2000:]
    assert f"[FAIL] run record proves the town controls  -- {failed}" in text
    assert live_tag(text, "U2_RUN")["result"] == "FAIL"


def test_whole_gate_writes_only_inside_accepted_holds(sim_runs):
    sim = sim_runs["crystal"]["town_sim"]
    domains = {domain for domain, _, _ in sim.writes}
    assert domains == {"System Bus", "CartRAM"}
    flat = PROFILE["crystal"]["derived"]["active_box_flat"]
    assert all(flat <= address < flat + 1102 for domain, address, _ in sim.writes if domain == "CartRAM")
    assert [address for domain, address, _ in sim.writes if domain == "System Bus"] == \
        [PROFILE["crystal"]["ram"]["wPartyMon1HP"], PROFILE["crystal"]["ram"]["wPartyMon1HP"] + 1]
