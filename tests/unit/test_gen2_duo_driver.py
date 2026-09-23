"""MODEL controls for the gen2_new duo driver (card gen2-H1): lua/tests/duo/duo_gen2_main.lua,
scenario_gen2_link.lua and gen2_route29_inputs.lua, under lupa, no emulator.

The whole per-instance driver runs against the scripted gate's synthetic cartridge (a QualifySim booted
through CONTINUE onto Route 29 grass, extended here with a Poke Ball catch) and a stand-in for the U3
production entry (a fake lua/gen2/run.lua in the temp root that exposes SLINK_GEN2_CLIENT/_PARTS and
ticks on event.onframeend, as the real one does). Passing here is authoring evidence only.

Red controls: no engine capture event -> no CAUGHT and no PASS; the production client never observes the
native save -> no PASS; a candidate (non-production) graph -> no PASS; and the pure verdict refuses every
missing, duplicated or reordered marker.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from lupa import LuaError, LuaRuntime

from tests.live.test_gen2_frame_align import u1_facts
from tests.unit.test_gen2_scripted_gate import (
    QualifySim,
    battle_grid,
    context,
    facts,
    grid_as_python,
    make_root,
    menu_screen,
    qualify_env,
)

ROOT = Path(__file__).resolve().parents[2]
MAIN = "lua/tests/duo/duo_gen2_main.lua"
SCENARIO = ROOT / "lua/tests/duo/scenario_gen2_link.lua"
DRIVER_FILES = (MAIN, "lua/tests/duo/scenario_gen2_link.lua", "lua/tests/duo/gen2_route29_inputs.lua",
                "lua/tests/test_gen2_scripted_gate.lua", "lua/tests/gen2_frame_align.lua", "lua/gen2/wire.lua")
KEY = "1A2B:B542:10"
FAKE_CONNECTOR = """local M = {}
function M.init() end
function M.send(line) end
function M.connected() return true end
function M.pump() end
return M
"""
FAKE_HUD = "return {init=function() end, render=function() end, show=function() end}\n"
# The U3 production entry's observable contract, standing in until U3 lands: globals + onframeend ticking.
FAKE_RUN = """local ROOT = os.getenv("SLINK_ROOT")
local C = require("connector")
local json = dofile(ROOT .. "/lua/json_codec.lua")
local client = {seq = 0}
function client:send(event, fields)
    self.seq = self.seq + 1
    fields.event, fields.seq, fields.player = event, self.seq, "a"
    C.send(json.encode(fields))
end
function client:on_event(ev)
    if ev.kind == "capture" then self:send("capture", {key = ev.mon.key, area_id = ev.area_id}) end
end
function client:handle_command(cmd) end
function client:frame_end()
    if not self.hello then self.hello = true; self:send("hello", {ot_id = 46401}) end
    local queue = SLINK_TEST_EVENTS or {}
    SLINK_TEST_EVENTS = {}
    for _, ev in ipairs(queue) do pcall(self.on_event, self, ev) end
end
SLINK_GEN2_CLIENT = client
SLINK_GEN2_PARTS = {client = client, production_admitted = SLINK_TEST_ADMITTED, qualification = "TEST_STANDIN",
                    pack = "gen2_crystal", title = "crystal", profile = {rom_sha1 = "test"}}
event.onframeend(function() client:frame_end() end)
"""


class DuoSim(QualifySim):
    """CONTINUE onto Route 29 grass, walk, one wild battle caught with a Poke Ball (NO nickname), save."""

    def __init__(self, lua, *, emit_capture=True, client_save=True):
        self.emit_capture, self.client_save = emit_capture, client_save
        self.frame_hooks, self.caught = [], False
        super().__init__(lua, "crystal", "battle", where=grass_start())
        self.u1 = u1_facts(context("crystal"), facts("crystal"), "q-model")
        self.sites.update(self.u1["pack_ui"])
        lua.execute("function SLINK_TEST_PUSH(ev) SLINK_TEST_EVENTS = SLINK_TEST_EVENTS or {};"
                    " table.insert(SLINK_TEST_EVENTS, ev) end")

    def push(self, event):
        self.lua.globals().SLINK_TEST_PUSH(self.lua.table_from(event, recursive=True))

    def fire(self, kind):
        super().fire(kind)
        if kind == "save_completed" and self.client_save:
            self.push({"kind": "observation", "site_id": "save_completed"})

    def advance(self):
        super().advance()
        for fn in self.frame_hooks:
            fn()

    def install(self, env):
        super().install(env)
        self.lua.globals().event.onframeend = lambda fn: self.frame_hooks.append(fn)
        self.lua.globals().event.onexit = lambda fn: None

    def pocket(self, kind, button, items=None):
        self.clear()
        if items:
            menu_screen(self.rows, items, 0, x0=7, y0=1, box=(7, 1, 19, 11))
        self.draw()
        yield from self.wait(2)
        self.fire(kind)
        while True:
            got = yield
            if button in got.edges:
                self.clear()
                return

    def catch_battle(self):
        self.put("wBattleMode", [1])
        yield from self.wait(4)
        yield from self.text("Wild PIDGEY", "appeared!")
        yield from self.menu("battle_menu", ["FIGHT", "<PK><MN>", "PACK", "RUN"], "PACK", columns=2,
                             grid=grid_as_python(battle_grid()))
        yield from self.pocket("pack_items", "Right")
        yield from self.pocket("pack_balls", "A", ["POKé BALL", "CANCEL"])
        yield from self.menu("item_submenu", ["USE", "QUIT"], "USE", at=(12, 8))
        yield from self.text("Gotcha! PIDGEY", "was caught!")
        count = self.get("wPartyCount")
        self.put("wPartyCount", [count + 1])
        yield from self.yes_no("Give a nickname to", "PIDGEY?", answer="NO")
        self.caught = True
        if self.emit_capture:   # the binder's capture event at capture_party_finalized
            self.push({"kind": "capture", "site_id": "capture_party_finalized", "acquisition": "wild",
                       "area_id": "route_29", "destination": "party", "slot": count + 1,
                       "mon": {"key": KEY, "species_id": 16, "level": 3}})
        yield from self.wait(4)
        self.put("wBattleMode", [0])

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
        steps = 0
        while True:
            self.fire("overworld_tick")
            got = yield
            if "Start" in got.edges:
                yield from self.save()
                continue
            held = [d for d in ("Up", "Down", "Left", "Right") if d in got.held]
            if not held or self.caught:
                continue
            self.facing = held[0]
            dx, dy = {"Up": (0, -1), "Down": (0, 1), "Left": (-1, 0), "Right": (1, 0)}[held[0]]
            if self.tile(self.x + dx, self.y + dy):
                self.x, self.y = self.x + dx, self.y + dy
            self.sync()
            if self.tile(self.x, self.y) == 2:
                steps += 1
                if steps >= 3:
                    yield from self.catch_battle()


def grass_start():
    """A Route 29 grass tile with a grass neighbour (the walk oscillates between them)."""
    area = facts("crystal")["maps"]["Route29"]
    w, h, grid = area["width"], area["height"], area["grid"]
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if grid[y * w + x] == 2 and grid[y * w + x - 1] == 2:
                return ("Route29", x, y)
    raise AssertionError("no Route 29 grass pair")


def run_driver(tmp_path, *, admitted=True, go=True, **sim_options):
    root = make_root(tmp_path, "crystal")
    for rel in DRIVER_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    (root / "lua/connector.lua").write_text(FAKE_CONNECTOR, encoding="utf-8")
    (root / "lua/hud.lua").write_text(FAKE_HUD, encoding="utf-8")
    (root / "lua/gen2/run.lua").write_text(FAKE_RUN, encoding="utf-8")
    spec, env = qualify_env(root, "crystal", "battle", "boot")
    sim = DuoSim(LuaRuntime(unpack_returned_tuples=True), **sim_options)
    env["SLINK_GEN2_U1_FACTS"] = json.dumps(sim.u1)
    sim.install(env)
    result, go_file = root / "patch/build/e2e_link_a_result.txt", tmp_path / "go_a.txt"
    if go:
        go_file.write_text("GO", encoding="utf-8")
    glob = sim.lua.globals()
    glob.SLINK_TEST_ADMITTED = admitted
    glob.SLINK_HOST, glob.SLINK_PORT, glob.SLINK_PLAYER = "127.0.0.1", 1, "a"
    glob.SLINK_DUO = sim.lua.table_from({
        "wt": str(root).replace("\\", "/"), "player": "a", "scenario": "link", "game": "gen2_new", "attempt": 1,
        "result": str(result).replace("\\", "/"), "partner_result": str(tmp_path / "b.txt").replace("\\", "/"),
        "go_file": str(go_file).replace("\\", "/"), "timeout_frames": 12000, "max_phase_frames": 3000})
    with pytest.raises(LuaError, match="slink-duo-finished"):
        sim.lua.execute(f'dofile("{glob.SLINK_DUO.wt}/{MAIN}")')
    assert sim.exited
    text = result.read_text(encoding="utf-8")
    return text.strip().splitlines(), sim, env


def tag_json(lines, tag):
    rows = [json.loads(line[len(tag) + 1:]) for line in lines if line.startswith(tag + " ")]
    assert len(rows) == 1, (tag, rows)
    return rows[0]


def test_link_happy_path_catches_reports_saves_and_passes(tmp_path):
    lines, sim, env = run_driver(tmp_path)
    assert lines[-1] == f"RESULT: PASS (caught {KEY})", "\n".join(lines[-40:])
    tags = [line.split(" ", 1)[0] for line in lines]
    # HELLO may precede BOOTED (the client says hello whenever its checkpoint allows); the rest is ordered.
    order = [tags.index(t) for t in ("DUO_GEN2", "CLIENT", "BOOTED", "ENGINE_CAPTURE", "CAPTURE_SENT",
                                     "CAUGHT", "SAVE_WITNESS", "RECEIPT")]
    assert order == sorted(order)
    save = tag_json(lines, "SAVE_WITNESS")
    flushed = Path(save["saveram_path"]).read_bytes()
    assert save["cartram_sha256"] == hashlib.sha256(flushed[:0x8000]).hexdigest() == hashlib.sha256(sim.cart[:0x8000]).hexdigest()
    assert save["saveram_bytes"] == len(flushed) == 0x8000 + 22 and save["gate_saves"] >= 1 and save["client_saves"] >= 1
    receipt = tag_json(lines, "RECEIPT")
    assert receipt["schema"] == "gen2-duo-link-v1" and receipt["key"] == KEY and receipt["player"] == "a"
    assert receipt["case"] == "crystal_battle" and receipt["capture"]["site_id"] == "capture_party_finalized"
    assert receipt["harness_write_scopes"] == [] and sim.writes == []
    # Normal buttons only.
    assert all(set(row) <= {"Up", "Down", "Left", "Right", "A", "B", "Start", "Select"} for row in sim.inputs)


def test_no_engine_capture_prints_no_caught_and_no_pass(tmp_path):
    lines, _, _ = run_driver(tmp_path, emit_capture=False)
    assert lines[-1].startswith("RESULT: FAIL") and "without a catch" in lines[-1], lines[-1]
    assert not any(line.startswith(("CAUGHT", "SAVE_WITNESS", "RECEIPT")) for line in lines)


def test_no_client_save_observation_is_no_pass(tmp_path):
    lines, _, _ = run_driver(tmp_path, client_save=False)
    assert lines[-1].startswith("RESULT: FAIL") and "never observed save_completed" in lines[-1], lines[-1]
    assert any(line.startswith("CAUGHT ") for line in lines)
    assert not any(line.startswith(("SAVE_WITNESS", "RECEIPT")) for line in lines)


def test_a_candidate_graph_is_refused_before_any_play(tmp_path):
    lines, sim, _ = run_driver(tmp_path, admitted=False)
    assert lines[-1] == "RESULT: FAIL (client is not the production graph)"
    assert not sim.inputs


# --- the pure verdict over marker lines --------------------------------------------------------------

def verdict_runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    return lua, lua.execute(SCENARIO.read_text(encoding="utf-8")), json_codec


def happy_lines():
    j = json.dumps
    return [
        "DUO_GEN2 " + j({"player": "a", "scenario": "link", "attempt": 1, "case": "crystal_battle", "title": "crystal",
                         "rom_sha1": "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133", "fixture_sha256": "ab" * 32}),
        "CLIENT " + j({"qualification": "PRODUCTION", "production_admitted": True, "pack": "gen2_crystal",
                       "title": "crystal", "rom_sha1": "x"}),
        "BOOTED " + j({"frame": 300, "map_group": 24, "map_number": 3, "x": 10, "y": 10, "party_count": 1}),
        "MYKEY 0 1111:B542:9E",
        "HELLO " + j({"frame": 310, "ot_id": 46401}),
        "ENGINE_CAPTURE " + j({"frame": 900, "site_id": "capture_party_finalized", "acquisition": "wild",
                               "area_id": "route_29", "destination": "party", "slot": 2, "key": KEY,
                               "species_id": 16, "level": 3}),
        "CAPTURE_SENT " + j({"frame": 900, "key": KEY, "seq": 7}),
        "CAUGHT " + KEY,
        "SAVE_WITNESS " + j({"frame": 1500, "save_completed_frame": 1460, "gate_saves": 1, "client_saves": 1,
                             "cartram_sha256": "cd" * 32, "cartram_bytes": 32768, "saveram_path": "C:/x/y.SaveRAM",
                             "saveram_bytes": 32790, "flushed_matches": True}),
    ]


def verdict(lines):
    lua, scenario, json_codec = verdict_runtime()
    problems, receipt = scenario.verdict(lua.table_from(lines), json_codec)
    return list(problems.values()), receipt


def test_verdict_passes_the_complete_marker_sequence():
    problems, receipt = verdict(happy_lines())
    assert problems == [] and receipt["key"] == KEY and receipt["schema"] == "gen2-duo-link-v1"


@pytest.mark.parametrize("tag", ["DUO_GEN2", "CLIENT", "BOOTED", "HELLO", "ENGINE_CAPTURE", "CAPTURE_SENT",
                                 "CAUGHT", "SAVE_WITNESS"])
def test_verdict_fails_on_any_missing_marker(tag):
    problems, receipt = verdict([line for line in happy_lines() if not line.startswith(tag + " ")])
    assert problems and receipt is None


def mutate(tag, **changes):
    out = []
    for line in happy_lines():
        if line.startswith(tag + " "):
            value = json.loads(line[len(tag) + 1:])
            value.update(changes)
            line = f"{tag} {json.dumps(value)}"
        out.append(line)
    return out


@pytest.mark.parametrize("lines,match", [
    (mutate("CLIENT", production_admitted=False), "production graph"),
    (mutate("ENGINE_CAPTURE", site_id="capture_box_finalized"), "wild party catch"),
    (mutate("CAPTURE_SENT", key="0000:0000:01"), "no capture event sent"),
    (mutate("CAPTURE_SENT", frame=899), "sent before the engine capture"),
    (mutate("SAVE_WITNESS", gate_saves=0), "save_completed site never fired"),
    (mutate("SAVE_WITNESS", client_saves=0), "never observed save_completed"),
    (mutate("SAVE_WITNESS", flushed_matches=False), "save witness incomplete"),
    (mutate("SAVE_WITNESS", save_completed_frame=800), "before the capture was sent"),
    (happy_lines()[:7] + [happy_lines()[8], happy_lines()[7]], "save witness printed before CAUGHT"),
    (happy_lines()[:5] + ["CAUGHT " + KEY] + happy_lines()[5:7] + happy_lines()[8:], "CAUGHT printed before"),
    (happy_lines() + [happy_lines()[5]], "2 ENGINE_CAPTURE markers"),
    (happy_lines() + ["RESULT: PASS (x)"], "RESULT line precedes"),
], ids=["candidate", "box-site", "other-key", "early-send", "no-gate-save", "no-client-save", "torn-flush",
        "save-before-send", "save-before-caught", "caught-first", "two-captures", "prior-result"])
def test_verdict_refuses_a_tampered_or_reordered_sequence(lines, match):
    problems, receipt = verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


def test_driver_files_are_lua_syntax_clean():
    check = LuaRuntime().execute("return function(s, n) local f, e = load(s, n); return f and 'ok' or e end")
    for rel in ("lua/tests/duo/duo_gen2_main.lua", "lua/tests/duo/scenario_gen2_link.lua",
                "lua/tests/duo/gen2_route29_inputs.lua"):
        assert check((ROOT / rel).read_text(encoding="utf-8"), "@" + rel) == "ok", rel
