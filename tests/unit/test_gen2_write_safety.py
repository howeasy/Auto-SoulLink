"""Gen 2 checkpoint over held synthetic observations: inspect_candidate is never authority; check()
authorizes only behind a PHYSICAL write-window receipt (card U2). Also the live U2 verifiers
(tests/live/test_gen2_write_windows.py) against synthetic gate output, and the gate's pure helpers."""

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

    def check(self, receipt=None):
        binder = self.binder(receipt)
        return binder.check(binder)

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


# --- card U2: the PHYSICAL write-window receipt gate --------------------------------------------

TOWN = {"start_menu_predicates_pass": True, "save_window": "refused",
        "windows": {"script_text": {"failing": ["wScriptMode", "wScriptRunning"]},
                    "mid_warp": {"failing": ["hMapEntryMethod", "wMapStatus"]}},
        "cartram": {"visible": True, "survived_native_save": True},
        "sram_closed_bus_view": {"address": 0xAD10, "bus": 0xFF, "cartram": 0}}
BATTLE = {"windows": {"battle": {"failing": ["wBattleMode"]}}}


def receipt_for(title):
    """A receipt shaped by the live lane's own builder, for the title whose run may authorize `title`."""
    owner = {"crystal": "crystal", "gold": "gold", "silver": "gold"}[title]
    pack = json.loads((ROOT / f"data/games/gen2_{owner}/write_checkpoint.json").read_text())
    return u2.build_receipt(owner, pack, TOWN, BATTLE, fixtures={f"{owner}_town": "0" * 64})


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_physical_receipt_authorizes_only_the_held_idle_frame(title):
    candidate = Candidate(title)
    receipt = receipt_for(title)
    assert candidate.check()[0] is False
    accepted, why = candidate.check(receipt)
    assert accepted is True, why
    assert candidate.inspect().runtime_authorized is False
    candidate.registers["PC"] += 1   # not the held checkpoint instruction
    assert candidate.check(receipt)[0] is False


def test_silver_follows_gold_only_while_the_rows_are_identical():
    gold = json.loads((ROOT / "data/games/gen2_gold/write_checkpoint.json").read_text())["titles"]["gold"]
    silver = json.loads((ROOT / "data/games/gen2_silver/write_checkpoint.json").read_text())["titles"]["silver"]
    assert gold == silver
    candidate = Candidate("silver")
    candidate.primary["state_predicates"][0]["reason"] = "drifted"
    accepted, why = candidate.check(receipt_for("silver"))
    assert accepted is False and "other checkpoint rows" in why


@pytest.mark.parametrize("symbol", ["wMapStatus", "wScriptRunning", "wScriptFlags", "wGameLogicPaused",
                                    "wBattleMode", "hMapEntryMethod", "wLinkMode", "wSavedAtLeastOnce"])
def test_receipt_authority_still_refuses_every_unsafe_predicate(symbol):
    candidate = Candidate()
    condition = next(row for row in candidate.primary["state_predicates"] if row["symbol"] == symbol)
    candidate.memory["System Bus", condition["address"]] ^= condition["mask"]
    accepted, why = candidate.check(receipt_for("crystal"))
    assert accepted is False and symbol in why


def _fault(receipt, fault):
    if fault == "schema":
        receipt["schema"] = "gen2-engine-site-receipt-v1"
    elif fault == "model":
        receipt["evidence_level"] = "MODEL"
    elif fault == "failed":
        receipt["result"] = "FAIL"
    elif fault == "rom":
        receipt["rom_sha1"] = "0" * 40
    elif fault == "rows":
        receipt["checkpoint"]["state_predicates"][0]["value"] ^= 1
    elif fault == "control":
        receipt["controls"]["start_menu"] = "authorized"
    elif fault == "missing_control":
        del receipt["controls"]["mid_warp"]
    elif fault == "save_window":
        del receipt["save_window"]
    elif fault == "persisted":
        receipt["persisted"] = False
    return receipt


@pytest.mark.parametrize("fault", ["schema", "model", "failed", "rom", "rows", "control", "missing_control",
                                   "save_window", "persisted"])
def test_receipt_binding_refuses(fault):
    candidate = Candidate()
    accepted, why = candidate.check(_fault(receipt_for("crystal"), fault))
    assert accepted is False and "receipt" in why


def test_a_gold_receipt_never_authorizes_crystal():
    candidate = Candidate("crystal")
    accepted, why = candidate.check(receipt_for("gold"))
    assert accepted is False and "another title" in why


def test_failing_predicates_lists_every_refusal_in_pack_order():
    candidate = Candidate()
    rows = candidate.primary["state_predicates"]
    for row in (rows[4], rows[1]):
        candidate.memory["System Bus", row["address"]] ^= row["mask"]
    failed = candidate.module.failing_predicates(candidate.lua.table_from(candidate.primary, recursive=True),
                                                 candidate.read)
    assert list(failed.values()) == [rows[1]["symbol"], rows[4]["symbol"]]


# --- the live lane's verifiers against synthetic gate output ------------------------------------

PROFILE = json.loads((ROOT / "data/games/gen2_crystal/profile.json").read_text())["titles"]["crystal"]


def _window(frames=30, failing=(), accepted=0, **write):
    body = {"slot": 0, "refused": True, "reason": "write ownership refused", "party_unchanged": True, **write}
    return {"frames": frames, "accepted": accepted, "failing": list(failing), "write": body}


def town_output(flip=None, **changes):
    derived = PROFILE["derived"]
    flat, length = derived["active_box_flat"], derived["active_box_copy_length"]
    after = bytes([1, 25, 255]) + bytes(length - 3)
    cart = bytearray(u2.CART_RAM_BYTES)
    backing = PROFILE["storage_boxes"][0]["flat"]
    cart[flat:flat + length] = after
    cart[backing:backing + length] = after
    hp_flat = 0x2000 + 0x100
    cart[hp_flat:hp_flat + 2] = bytes([0, 19])
    write = {"frame": 10, "party": {"slot": 0, "offset": 34, "address": PROFILE["ram"]["wPartyMon1HP"], "bank": 1,
                                    "before_hex": "0014", "written_hex": "0013", "readback_hex": "0013"},
             "box": {"current_box": 0, "saved_at_least_once": 1, "flat": flat, "length": length,
                     "backing_flat": backing, "owner": "active", "count_before": 0, "count_after": 1,
                     "after_hex": after.hex(), "readback_hex": after.hex(),
                     "bus": {"address": 0xAD10, "value": 255, "cartram_value": 0}}}
    windows = {"start_menu": _window(), "script_text": _window(failing=["wScriptMode", "wScriptRunning"]),
               "save_paused": _window(frames=90, failing=["wGameLogicPaused"]),
               "mid_warp": _window(frames=40, failing=["hMapEntryMethod", "wMapStatus"])}
    for key, value in changes.items():
        name, field = key.split("__")
        if name == "write":
            box = field in ("after_hex", "owner")
            write["box" if box else "party"][field] = value
            if field == "after_hex":
                write["box"]["readback_hex"] = value
            if field == "written_hex":
                write["party"]["readback_hex"] = value
        elif field in ("refused", "reason"):
            windows[name]["write"][field] = value
        else:
            windows[name][field] = value
    if flip is not None:
        cart[flip] ^= 1   # a flushed file whose own hash the gate recorded, but without the written byte
    save = {"cartram_sha256": hashlib.sha256(bytes(cart)).hexdigest()}
    text = "\n".join(["U2_WRITE " + json.dumps(write), "U2_WINDOWS " + json.dumps(windows),
                      "U2_SAVE " + json.dumps(save), "RESULT: PASS u2 (0 checks failed)"])
    return text, bytes(cart), hp_flat


def test_town_verifier_accepts_the_contract_and_builds_a_qualified_receipt():
    text, cart, hp_flat = town_output()
    town = u2.verify_town(text, PROFILE, cart, hp_flat)
    assert town["save_window"] == "refused" and town["start_menu_predicates_pass"] is True
    battle_windows = {"battle": _window(failing=["wBattleMode"], faint_refused=True,
                                        faint_reason="active faint timing is not qualified")}
    battle_text = "\n".join(["U2_WINDOWS " + json.dumps(battle_windows),
                             "U2_BATTLE_MODEL " + json.dumps({"active_slot": 0}), "RESULT: PASS"])
    battle = u2.verify_battle(battle_text)
    pack = json.loads((ROOT / "data/games/gen2_crystal/write_checkpoint.json").read_text())
    receipt = u2.build_receipt("crystal", pack, town, battle, fixtures={})
    accepted, why = u2.lua_qualified(pack, "crystal", receipt)
    assert accepted is True, why
    assert Candidate().check(receipt)[0] is True


@pytest.mark.parametrize("change", [
    {"start_menu__accepted": 1},                      # an accepted hold inside the START menu
    {"script_text__failing": ["wMapStatus"]},         # the script window refused by the wrong predicate
    {"mid_warp__refused": False},                     # a party write went through mid-warp
    {"start_menu__reason": "write refused: mapped-bank policy"},   # refused, but not by ownership
    {"save_paused__accepted": 2},
    {"write__written_hex": "0012"},                   # not HP-1
    {"write__owner": "backing"},                      # current-box write to the non-authoritative copy
    {"write__after_hex": "00"},                       # the save did not carry the deposit
])
def test_town_verifier_refuses_each_falsifier(change):
    text, cart, hp_flat = town_output(**change)
    with pytest.raises(AssertionError):
        u2.verify_town(text, PROFILE, cart, hp_flat)


@pytest.mark.parametrize("flip, why", [(0x2101, "party HP not saved"),
                                        (0x4000, "native SaveBox did not copy"),
                                        (None, "flushed SaveRAM differs")])
def test_town_verifier_refuses_an_unsaved_party_write_a_missing_backing_copy_or_another_file(flip, why):
    assert PROFILE["storage_boxes"][0]["flat"] == 0x4000
    text, cart, hp_flat = town_output(flip=flip)
    if flip is None:
        cart = cart[:-1] + bytes([cart[-1] ^ 1])
    with pytest.raises(AssertionError, match=why):
        u2.verify_town(text, PROFILE, cart, hp_flat)


def test_battle_verifier_needs_the_active_faint_refusal():
    windows = {"battle": _window(failing=["wBattleMode"], faint_refused=False, faint_reason="written")}
    text = "\n".join(["U2_WINDOWS " + json.dumps(windows), "U2_BATTLE_MODEL " + json.dumps({"active_slot": 0}),
                      "RESULT: PASS"])
    with pytest.raises(AssertionError):
        u2.verify_battle(text)


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
        on a WRAM0 stack, Elm's script text, a native save (wGameLogicPaused, SaveBox, sPokemonData),
        the lab exit warp (wMapStatus != MAPSTATUS_HANDLE) and one Route 29 wild battle."""

        def __init__(self, lua, title="crystal", mode="town"):
            self.mode = mode
            self.primary = json.loads((ROOT / f"data/games/gen2_{title}/write_checkpoint.json")
                                      .read_text())["titles"][title]["primary"]
            self.sp = self.primary["caller_stack"]["minimum_sp"] + 0x10
            super().__init__(lua, title)
            self.where = ("Route29", 53, 12) if mode == "battle" else ("ElmsLab", 5, 3)
            self.carry = None   # (party wram slice, cart) a reload boots with
            self.leak_menu = self.silent_script = self.in_menu = False   # falsifier switches

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
                party, cart = self.carry
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
                    items = ["#DEX", "#MON", "PACK", self.player_name, "SAVE", "OPTION", "EXIT"]
                    self.in_menu = True
                    chosen = yield from self.menu_select("start_menu", items, at=(8, 0))
                    self.in_menu = False
                    if chosen == "SAVE":
                        yield from self.native_save()
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


def run_u2(tmp_path, mode, *, title="crystal", carry=None, **switches):
    U2Sim, inspect_root, qualify_env = _sim_classes()
    root = inspect_root(tmp_path / mode, title)
    for rel in GATE_FILES + (f"data/games/gen2_{title}/write_checkpoint.json",):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes((ROOT / rel).read_bytes())
    spec, env = qualify_env(root, title, "battle" if mode == "battle" else "town", "boot")
    env["SLINK_GEN2_U2"] = json.dumps({"mode": mode})
    sim = U2Sim(LuaRuntime(unpack_returned_tuples=True), title, mode)
    sim.carry = carry
    for name, value in switches.items():
        setattr(sim, name, value)
    sim.install(env)
    from lupa.lua54 import LuaError
    with pytest.raises(LuaError, match="slink-gate-finished"):
        sim.lua.execute((ROOT / "lua/tests/gen2_write_windows.lua").read_text(encoding="utf-8"))
    text = (root / "patch/build/gen2_write_windows_result.txt").read_text(encoding="utf-8")
    return sim, text


@pytest.fixture(scope="module")
def town_run(tmp_path_factory):
    return run_u2(tmp_path_factory.mktemp("u2"), "town")


def test_whole_gate_town_mode_on_the_synthetic_cartridge(town_run, tmp_path):
    sim, text = town_run
    assert text.strip().splitlines()[-1].startswith("RESULT: PASS"), text[-3000:]
    from tests.unit.test_gen2_scripted_gate import context
    pokemon = context("crystal").symbol("sPokemonData")
    hp_flat = u2.sram_flat(pokemon.bank, pokemon.address) + PROFILE["ram"]["wPartyMon1HP"] - PROFILE["ram"]["wPokemonData"]
    town = u2.verify_town(text, PROFILE, Path(sim.saveram_path).read_bytes(), hp_flat)
    assert town["save_window"] == "refused" and town["start_menu_predicates_pass"] is True
    # Every harness byte went through a permit inside an accepted hold: party HP (System Bus) + one sBox span.
    domains = {domain for domain, _, _ in sim.writes}
    assert domains == {"System Bus", "CartRAM"}
    flat = PROFILE["derived"]["active_box_flat"]
    assert all(flat <= address < flat + 1102 for domain, address, _ in sim.writes if domain == "CartRAM")
    assert [address for domain, address, _ in sim.writes if domain == "System Bus"] == \
        [PROFILE["ram"]["wPartyMon1HP"], PROFILE["ram"]["wPartyMon1HP"] + 1]
    # The cold reload of that save: CONTINUE, liveness, the written bytes back.
    start = sim.offset("wPartyCount")
    carry = (bytes(sim.wram[start:start + PROFILE["ram"]["wPartyMonNicknamesEnd"] - PROFILE["ram"]["wPartyCount"]]),
             Path(sim.saveram_path).read_bytes()[:u2.CART_RAM_BYTES])
    _, reload_text = run_u2(tmp_path, "reload", carry=carry)
    u2.verify_reload(reload_text, PROFILE, town)


def test_whole_gate_battle_mode_on_the_synthetic_cartridge(tmp_path):
    sim, text = run_u2(tmp_path, "battle")
    assert text.strip().splitlines()[-1].startswith("RESULT: PASS"), text[-3000:]
    battle = u2.verify_battle(text)
    assert battle["model"]["active_slot"] == 0 and sim.writes == []


@pytest.mark.parametrize("switch, failed", [
    ("leak_menu", "start_menu: no accepted checkpoint hold inside the window"),
    ("silent_script", "script_text: the stated predicate refuses the window"),
])
def test_whole_gate_fails_when_a_window_is_not_refused_by_its_stated_mechanism(tmp_path, switch, failed):
    _, text = run_u2(tmp_path, "town", **{switch: True})
    assert text.strip().splitlines()[-1].startswith("RESULT: FAIL"), text[-2000:]
    assert f"[FAIL] {failed}" in text
