"""MODEL controls for the gen2_new duo driver (card gen2-H1): lua/tests/duo/duo_gen2_main.lua,
scenario_gen2_link.lua and gen2_route29_inputs.lua, under lupa, no emulator.

The whole per-instance driver runs against the scripted gate's synthetic cartridge (a QualifySim booted
through CONTINUE onto Route 29 grass, extended here with a Poke Ball catch) and a stand-in for the U3
production entry (a fake lua/gen2/run.lua in the temp root that exposes SLINK_GEN2_CLIENT/_PARTS and
ticks on event.onframeend, as the real one does). Passing here is authoring evidence only.

The happy path runs per title (Crystal, Gold, Silver: O-16 pairs any two); the title comes from
SLINK_GEN2_TITLE alone. Red controls: no engine capture event -> no CAUGHT and no PASS; the production client
never observes the native save -> no PASS; a candidate (non-production) graph -> no PASS; a client that
detected another title than SLINK_GEN2_TITLE -> no PASS; and the pure verdict refuses every missing,
duplicated or reordered marker.
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
                "lua/tests/duo/scenario_gen2_faint.lua", "lua/tests/duo/gen2_faint_inputs.lua",
                "lua/tests/test_gen2_scripted_gate.lua", "lua/tests/gen2_frame_align.lua", "lua/tests/gen2_walk.lua",
                "lua/gen2/wire.lua")
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
SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS = nil, nil
if SLINK_TEST_REFUSE then
    console.log("[SLink-gen2] crystal cartridge refused (production admission): unknown sha1")
    return
end
-- The production client's observable lifecycle, reduced: hello once live; every 60 frames a validation
-- (SLINK_TEST_LIVE, default always live) whose 5th failure pauses writes; a dead game drops the hello.
local client = {seq = 0, hello_sent = false, writes_enabled = true, gate_revoked = false, invalid = 0}
function client:send(event, fields)
    self.seq = self.seq + 1
    fields.event, fields.seq, fields.player = event, self.seq, "a"
    C.send(json.encode(fields))
end
function client:on_event(ev)
    if ev.kind == "capture" then self:send("capture", {key = ev.mon.key, area_id = ev.area_id}) end
end
client.deferred, client.settle = {}, {}
local BOX = {box_mon = true, party_mon = true, memorialize = true}
function client:handle_command(cmd)
    if BOX[cmd.cmd] then table.insert(self.deferred, cmd) end
end
function client:run_box(cmd)
    if cmd.cmd == "party_mon" then self:send("sync_retrieve_done", {key = cmd.key}) end
end
function client:frame_end()
    if #self.deferred > 0 and emu.framecount() % 30 == 0 then self:run_box(table.remove(self.deferred, 1)) end
    local live = SLINK_TEST_LIVE == nil or SLINK_TEST_LIVE()
    if not live then self.hello_sent = false end
    if emu.framecount() % 60 == 0 then
        if live then
            self.invalid = 0
            if self.gate_revoked then self.gate_revoked, self.writes_enabled = false, true end
        else
            self.invalid = self.invalid + 1
            if self.invalid >= 5 and self.writes_enabled then self.writes_enabled, self.gate_revoked = false, true end
        end
    end
    if live and not self.hello_sent then self.hello_sent = true; self:send("hello", {ot_id = 46401}) end
    local queue = SLINK_TEST_EVENTS or {}
    SLINK_TEST_EVENTS = {}
    for _, ev in ipairs(queue) do pcall(self.on_event, self, ev) end
    if self.hello_sent then   -- the server answers a hello
        local commands = SLINK_TEST_COMMANDS or {}
        SLINK_TEST_COMMANDS = {}
        for _, cmd in ipairs(commands) do self:handle_command(cmd) end
    end
end
SLINK_GEN2_CLIENT = client
local title = SLINK_TEST_CLIENT_TITLE or os.getenv("SLINK_GEN2_TITLE")
SLINK_GEN2_PARTS = {client = client, production_admitted = SLINK_TEST_ADMITTED, qualification = "TEST_STANDIN",
                    pack = "gen2_" .. title, title = title, profile = {rom_sha1 = "test"}, writes = {log = {}}}
event.onframeend(function() client:frame_end() end)
"""


class DuoSim(QualifySim):
    """CONTINUE onto Route 29 grass, walk, one wild battle caught with a Poke Ball (NO nickname), save."""

    def __init__(self, lua, title="crystal", *, emit_capture=True, client_save=True, link_reply=True):
        self.emit_capture, self.client_save, self.link_reply = emit_capture, client_save, link_reply
        self.frame_hooks, self.caught = [], False
        super().__init__(lua, title, "battle", where=grass_start(title))
        self.u1 = u1_facts(context(title), facts(title), "q-model")
        self.sites.update(self.u1["pack_ui"])
        lua.execute("function SLINK_TEST_PUSH(ev) SLINK_TEST_EVENTS = SLINK_TEST_EVENTS or {};"
                    " table.insert(SLINK_TEST_EVENTS, ev) end")
        lua.execute("function SLINK_TEST_CMD(c) SLINK_TEST_COMMANDS = SLINK_TEST_COMMANDS or {};"
                    " table.insert(SLINK_TEST_COMMANDS, c) end")

    def command(self, **cmd):
        self.lua.globals().SLINK_TEST_CMD(self.lua.table_from(cmd))

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

    # Per-battle seams (the clause sims override them): the foe, the expected BattleMenu choice, reactions.
    def next_foe(self):
        return 16, KEY

    def battle_choice(self, species):
        return "PACK"

    def on_fled(self, species):
        pass

    def on_caught(self, species, key):
        pass

    def catch_battle(self, species=16, key=KEY):
        self.put("wBattleMode", [1])
        self.put("wEnemyMonSpecies", [species])
        yield from self.wait(4)
        yield from self.text("Wild PIDGEY", "appeared!")
        choice = self.battle_choice(species)
        yield from self.menu("battle_menu", ["FIGHT", "<PK><MN>", "PACK", "RUN"], choice, columns=2,
                             grid=grid_as_python(battle_grid()))
        if choice == "RUN":
            yield from self.text("Got away safely!")
            yield from self.wait(4)
            self.put("wBattleMode", [0])
            self.on_fled(species)
            return
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
                       "mon": {"key": key, "species_id": species, "level": 3}})
        yield from self.wait(4)
        self.put("wBattleMode", [0])
        if self.link_reply:   # the partner already waits: the server links at once (state.py:1741)
            self.command(cmd="msgbox", text="PIDGEY and SENTRET linked!")
        self.on_caught(species, key)

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
                    steps = 0
                    yield from self.catch_battle(*self.next_foe())


def grass_start(title):
    """A Route 29 grass tile with a grass neighbour (the walk oscillates between them)."""
    area = facts(title)["maps"]["Route29"]
    w, h, grid = area["width"], area["height"], area["grid"]
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if grid[y * w + x] == 2 and grid[y * w + x - 1] == 2:
                return ("Route29", x, y)
    raise AssertionError("no Route 29 grass pair")


FAINT_UI = {"move_menu": "MoveSelectionScreen.interpret_joypad", "battle_party": "PartyMenuSelect",
            "battle_mon_menu": "BattleMonMenu"}


def run_driver(tmp_path, title="crystal", *, admitted=True, go=True, client_title=None, scenario="link",
               player="a", duo=None, go_text="GO", sim_class=None, setup=None, **sim_options):
    root = make_root(tmp_path, title)
    for rel in DRIVER_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    (root / "lua/connector.lua").write_text(FAKE_CONNECTOR, encoding="utf-8")
    (root / "lua/hud.lua").write_text(FAKE_HUD, encoding="utf-8")
    (root / "lua/gen2/run.lua").write_text(FAKE_RUN, encoding="utf-8")
    spec, env = qualify_env(root, title, "battle", "boot")
    sim = (sim_class or DuoSim)(LuaRuntime(unpack_returned_tuples=True), title, **sim_options)
    if scenario == "gen2_faint":   # the faint route's UI origins (U1d's u1_facts carries the same symbols)
        from tools.gen2_fixtures import _code_site
        sim.u1.setdefault("faint_ui", {kind: {k: v for k, v in _code_site(context(title), symbol).items()
                                              if k != "symbol_offset"} for kind, symbol in FAINT_UI.items()})
        sim.u1["prompts"].setdefault("next_mon", ["Use next"])
        sim.sites.update(sim.u1["faint_ui"])
    env["SLINK_GEN2_U1_FACTS"] = json.dumps(sim.u1)
    sim.install(env)
    result, go_file = root / "patch/build/e2e_link_a_result.txt", tmp_path / "go_a.txt"
    if go:
        go_file.write_text(go_text, encoding="utf-8")
    glob = sim.lua.globals()
    glob.SLINK_TEST_ADMITTED = admitted
    glob.SLINK_TEST_CLIENT_TITLE = client_title
    glob.SLINK_HOST, glob.SLINK_PORT, glob.SLINK_PLAYER = "127.0.0.1", 1, player
    glob.SLINK_DUO = sim.lua.table_from({
        "wt": str(root).replace("\\", "/"), "player": player, "scenario": scenario, "game": "gen2_new", "attempt": 1,
        "result": str(result).replace("\\", "/"), "partner_result": str(tmp_path / "b.txt").replace("\\", "/"),
        "go_file": str(go_file).replace("\\", "/"), "timeout_frames": 12000, "max_phase_frames": 3000,
        **(duo or {})})
    if setup:
        setup(sim, glob)
    with pytest.raises(LuaError, match="slink-duo-finished"):
        sim.lua.execute(f'dofile("{glob.SLINK_DUO.wt}/{MAIN}")')
    assert sim.exited
    text = result.read_text(encoding="utf-8")
    return text.strip().splitlines(), sim, env


def tag_json(lines, tag):
    rows = [json.loads(line[len(tag) + 1:]) for line in lines if line.startswith(tag + " ")]
    assert len(rows) == 1, (tag, rows)
    return rows[0]


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_link_happy_path_catches_reports_saves_and_passes(tmp_path, title):
    lines, sim, env = run_driver(tmp_path, title)
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
    assert receipt["case"] == f"{title}_battle" and receipt["title"] == title == receipt["client"]["title"]
    assert receipt["capture"]["site_id"] == "capture_party_finalized"
    assert receipt["harness_write_scopes"] == [] and sim.writes == []
    # Normal buttons only.
    assert all(set(row) <= {"Up", "Down", "Left", "Right", "A", "B", "Start", "Select"} for row in sim.inputs)


def test_save_witness_archives_its_exact_bytes_next_to_the_result(tmp_path):
    """G/S (and Crystal gfx) rewrite SRAM bank-0 scratch natively after a save, so the emulator's SaveRAM is
    mutable: SAVE_WITNESS.snapshot_path is an immutable copy of the witnessed bytes (Codex's H8 transport)."""
    lines, _, _ = run_driver(tmp_path)
    save = tag_json(lines, "SAVE_WITNESS")
    snap = Path(save["snapshot_path"])
    assert snap.name == "e2e_link_a_witness.SaveRAM" and snap.parent == tmp_path / "root/patch/build"
    raw = snap.read_bytes()
    assert len(raw) == save["saveram_bytes"] and hashlib.sha256(raw[:0x8000]).hexdigest() == save["cartram_sha256"]
    assert save["saveram_path"] != save["snapshot_path"]


def test_save_witness_never_overwrites_an_existing_snapshot(tmp_path):
    def stale(sim, glob):
        path = tmp_path / "root/patch/build/e2e_link_a_witness.SaveRAM"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old")
    lines, _, _ = run_driver(tmp_path, setup=stale)
    assert lines[-1].startswith("RESULT: FAIL") and "witness snapshot already exists" in lines[-1], lines[-1]
    assert (tmp_path / "root/patch/build/e2e_link_a_witness.SaveRAM").read_bytes() == b"old"


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


def test_a_client_on_another_title_is_refused_before_any_play(tmp_path):
    lines, sim, _ = run_driver(tmp_path, "gold", client_title="silver")
    assert lines[-1] == "RESULT: FAIL (client title silver differs from SLINK_GEN2_TITLE gold)"
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
    files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "lua/tests/duo").glob("*gen2*.lua"))
    assert "lua/tests/duo/duo_gen2_main.lua" in files and len(files) >= 5
    for rel in files:
        assert check((ROOT / rel).read_text(encoding="utf-8"), "@" + rel) == "ok", rel


# --- gen2_faint (card gen2-H1c) ------------------------------------------------------------------------

FAINT = ROOT / "lua/tests/duo/scenario_gen2_faint.lua"
FAINT_INPUTS = ROOT / "lua/tests/duo/gen2_faint_inputs.lua"


def test_client_marker_carries_the_registered_sites(tmp_path):
    lines, _, _ = run_driver(tmp_path)
    assert tag_json(lines, "CLIENT")["registered_sites"] == []   # the stand-in client composes no binder


def test_faint_a_refuses_before_any_input_without_a_registered_battle_faint(tmp_path):
    lines, sim, _ = run_driver(tmp_path, scenario="gen2_faint")
    assert lines[-1] == "RESULT: FAIL (production signals lack battle_faint)", lines[-5:]
    assert not sim.inputs


def faint_verdict(lines):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    link = lua.execute(SCENARIO.read_text(encoding="utf-8"))
    faint = lua.execute(FAINT.read_text(encoding="utf-8"))
    problems, receipt = faint.verdict(lua.table_from(lines), json_codec, link.verdict)
    return list(problems.values()), receipt


def faint_lines(player):
    j = json.dumps
    base = []
    for line in happy_lines()[:8]:   # through CAUGHT
        tag, body = line.split(" ", 1)
        if tag in ("DUO_GEN2", "CLIENT"):
            value = json.loads(body)
            value.update({"player": player, "scenario": "gen2_faint"} if tag == "DUO_GEN2" else
                         {"registered_sites": ["battle_end", "battle_faint", "capture_party"]})
            line = f"{tag} {j(value)}"
        base.append(line)
    link = "LINK_SAVE " + j({"frame": 1500, "saveram_path": "C:/x/e2e_gen2_faint_a_link_save.SaveRAM",
                             "saveram_bytes": 32790, "cartram_sha256": "ef" * 32, "cartram_bytes": 32768,
                             "gate_saves": 1, "client_saves": 1, "save_completed_frame": 1460, "key": KEY})
    final = "SAVE_WITNESS " + j({"frame": 4000, "save_completed_frame": 3900, "gate_saves": 2, "client_saves": 2,
                                 "cartram_sha256": "cd" * 32, "cartram_bytes": 32768, "saveram_path": "C:/x/y.SaveRAM",
                                 "saveram_bytes": 32790, "flushed_matches": True})
    if player == "a":
        middle = ["ENGINE_FAINT " + j({"frame": 3000, "site_id": "battle_faint", "cause": "battle", "key": KEY, "slot": 1}),
                  "FAINT_SENT " + j({"frame": 3001, "key": KEY, "seq": 20})]
    else:
        before = "00" * 48 + "10" + "00" * 31 + "0102" + "00" * 14 + "00" * 48 * 4
        after = "00" * 48 + "10" + "00" * 31 + "0000" + "00" * 14 + "00" * 48 * 4
        span = {"domain": "System Bus", "status": "written", "why": "overworld", "batch_size": 2}
        middle = ["RX force_faint key=" + KEY,
                  "PARTY_HP_WRITE " + j({"frame": 3200, "key": KEY, "slot": 1, "kind": "party_hp", "ok": True,
                                         "before_party_hex": before, "after_party_hex": after,
                                         "log": [dict(span, addr=0xDD0F, n=1, batch_index=1),
                                                 dict(span, addr=0xDD11, n=2, batch_index=2)],
                                         "checkpoint": {"pc": 27011, "sp": 0xC0FD, "hrom_bank": 37, "svbk": 1,
                                                        "sc": 0, "stack_hex": "4468", "anchor_hex": "cdf0",
                                                        "state": {"wMapStatus": 2}}}),
                  "BENCH_HP_STATUS 0000 00"]
    record = "00" * 32 + "0000" + "00" * 14   # 48 bytes: MON_STATUS 0x20 = 0, MON_HP 0x22 = 0
    middle += ["MEMORIAL_PREIMAGE " + j({"frame": 3300, "key": KEY, "slot": 1, "raw_hex": record,
                                         "ot_raw_hex": "80" * 11, "nickname_raw_hex": "81" * 11, "species_marker": 16}),
               "MEMORIAL_ACK " + j({"frame": 3301, "event": "memorialize_done", "key": KEY, "box": 13})]
    return base + [link] + middle + [final]


@pytest.mark.parametrize("player", ["a", "b"])
def test_faint_verdict_passes_each_complete_half(player):
    problems, receipt = faint_verdict(faint_lines(player))
    assert problems == [], problems
    assert receipt["schema"] == "gen2-duo-faint-v1" and receipt["key"] == KEY and receipt["player"] == player
    assert receipt["link_save"]["saveram_bytes"] == 32790


def faint_mutate(player, tag, **changes):
    out = []
    for line in faint_lines(player):
        if line.startswith(tag + " "):
            value = json.loads(line[len(tag) + 1:])
            value.update(changes)
            line = f"{tag} {json.dumps(value)}"
        out.append(line)
    return out


def drop(player, prefix):
    return [line for line in faint_lines(player) if not line.startswith(prefix)]


def swap(lines, a, b):
    lines = list(lines)
    lines[a], lines[b] = lines[b], lines[a]
    return lines


@pytest.mark.parametrize("lines,match", [
    (faint_mutate("a", "CLIENT", registered_sites=["battle_end"]), "lack battle_faint"),
    (faint_mutate("a", "ENGINE_FAINT", key="0000:0000:01"), "another mon"),
    (faint_mutate("a", "ENGINE_FAINT", site_id="poison_faint"), "not battle_faint"),
    (drop("a", "FAINT_SENT"), "missing FAINT_SENT"),
    (swap(faint_lines("a"), 9, 10), "faint sent before"),
    (faint_mutate("a", "SAVE_WITNESS", save_completed_frame=2999), "before the faint was sent"),
    (faint_mutate("a", "SAVE_WITNESS", gate_saves=1), "no native save after LINK_SAVE"),
    (drop("a", "LINK_SAVE"), "missing LINK_SAVE"),
    (faint_mutate("a", "LINK_SAVE", saveram_bytes=32768), "LINK_SAVE incomplete"),
    (faint_lines("a")[:-1] + [faint_lines("b")[10], faint_lines("a")[-1]], "party was written"),
    (drop("b", "RX force_faint"), "no RX force_faint"),
    ([x.replace("RX force_faint key=" + KEY, "RX force_faint key=0000:0000:01") for x in faint_lines("b")],
     "no RX force_faint"),
    (faint_mutate("b", "PARTY_HP_WRITE", ok=False), "write failed"),
    (faint_mutate("b", "PARTY_HP_WRITE", key="0000:0000:01"), "another mon"),
    (faint_mutate("b", "PARTY_HP_WRITE", log=[{"status": "written"}]), "two-span"),
    (swap(faint_lines("b"), 9, 10), "write precedes force_faint"),
    ([x.replace("BENCH_HP_STATUS 0000 00", "BENCH_HP_STATUS 0001 00") for x in faint_lines("b")], "HP 0000"),
    (drop("b", "BENCH_HP_STATUS"), "missing BENCH_HP_STATUS"),
    (faint_lines("b")[:-1] + [faint_lines("a")[9], faint_lines("b")[-1]], "own mon fainted"),
    (faint_mutate("b", "SAVE_WITNESS", save_completed_frame=3100), "before the write"),
    (drop("a", "MEMORIAL_PREIMAGE"), "missing MEMORIAL_PREIMAGE"),
    (drop("b", "MEMORIAL_ACK"), "no memorialize_done"),
    (faint_mutate("b", "MEMORIAL_ACK", event="memorialize_failed"), "no memorialize_done"),
    (faint_mutate("a", "MEMORIAL_ACK", box=12), "no memorialize_done"),
    (faint_mutate("a", "MEMORIAL_PREIMAGE", key="0000:0000:01"), "missing MEMORIAL_PREIMAGE"),
    (swap(faint_lines("b"), -3, -2), "memorial out of order"),
    (swap(faint_lines("a"), -2, -1), "memorial out of order"),
], ids=["no-site", "faint-other-key", "poison-site", "no-send", "send-first", "save-before-send", "no-new-save",
        "no-link-save", "short-link-save", "a-written", "no-rx", "rx-other-key", "write-failed", "write-other-key",
        "one-span", "write-first", "hp-left", "no-bench", "b-engine-faint", "save-before-write", "no-preimage",
        "no-ack", "ack-failed", "ack-other-box", "preimage-other-key", "ack-before-preimage", "save-before-ack"])
def test_faint_verdict_refuses_a_tampered_or_reordered_half(lines, match):
    problems, receipt = faint_verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


def bench(party_mon=None, preimage=None):
    """S.bench_record against a stand-in h: the live party (slot_of) or the captured pre-deposit record."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    faint = lua.execute(FAINT.read_text(encoding="utf-8"))
    h = lua.eval("""function(key, mon, pre)
        return {slot_of=function(k) if mon then return 1, mon end end, rec={preimage={[key]=pre}}}
    end""")(KEY, lua.table_from(party_mon) if party_mon else None, lua.table_from(preimage) if preimage else None)
    return faint.bench_record(h, KEY)


def test_bench_readback_reads_the_party_while_the_mon_is_there():
    assert bench({"hp": 0, "status": 0}) == (0, 0, "party")


def test_bench_readback_uses_the_memorial_preimage_once_the_mon_is_boxed():
    """A fast memorialize can box B's target before the readback (native box records carry no HP): the
    readback binds to the actual pre-deposit party record, MON_STATUS 0x20 / MON_HP 0x22 (big-endian)."""
    record = "00" * 32 + "08" + "00" + "0003" + "00" * 12
    assert bench(None, {"raw_hex": record}) == (3, 8, "memorial_preimage")
    assert bench(None, None)[0] is None


# --- gen2_faint_inputs.lua: the pure faint route (O15 input plan) --------------------------------------

def faint_driver(target=1):
    lua = LuaRuntime(unpack_returned_tuples=True)
    FI = lua.execute(FAINT_INPUTS.read_text(encoding="utf-8"))
    walk = lua.eval("{walk_direction=function() return 'Left' end}")
    return lua, FI.driver(walk, lua.table_from({}), lua.table_from({"target": target}))


def point(lua, **fields):
    base = {"battle_mode": 1, "active_slot": 0, "input_ready": True, "fainted": False,
            "party_hp": {0: 17, 1: 14}, "overworld_ready": False}
    base.update(fields)
    return lua.table_from(base, recursive=True)


def ui(kind, items=None, cursor=1, columns=1, **extra):
    out = {"kind": kind, **extra}
    if items:
        out.update(items={i + 1: v for i, v in enumerate(items)}, cursor=cursor, columns=columns)
    return out


def press(lua, driver, **fields):
    """One decision, then the 12-frame hold and its release frame; returns the pressed buttons and phase."""
    p = point(lua, **fields)
    buttons, phase = driver.step(p)
    assert buttons is not None, phase
    pressed = sorted(k for k, v in buttons.items() if v)
    for _ in range(12):
        driver.step(p)
    return pressed, phase


MENU = ["FIGHT", "<PK><MN>", "PACK", "RUN"]


def test_faint_route_switches_the_target_in_growls_says_yes_and_runs():
    lua, d = faint_driver()
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2)) == (["Right"], "battle")      # PKMN by cell
    assert press(lua, d, ui=ui("battle_menu", MENU, 2, 2))[0] == ["A"]
    assert press(lua, d, ui=ui("battle_party"), party_cursor=0)[0] == ["Down"]
    assert press(lua, d, ui=ui("battle_party"), party_cursor=1)[0] == ["A"]
    assert press(lua, d, ui=ui("battle_mon_menu", ["SWITCH", "STATS", "CANCEL"]))[0] == ["A"]
    assert press(lua, d, ui=ui("text"), active_slot=1)[0] == ["A"]
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), active_slot=1)[0] == ["A"]  # FIGHT
    assert press(lua, d, ui=ui("move_menu", ["TACKLE", "GROWL"]), active_slot=1)[0] == ["Down"]
    assert press(lua, d, ui=ui("move_menu", ["TACKLE", "GROWL"], 2), active_slot=1)[0] == ["A"]
    after = {"fainted": True, "active_slot": 1, "party_hp": {0: 17, 1: 0}}
    assert press(lua, d, ui=ui("yes_no", ["YES", "NO"], prompt="next_mon"), **after)[0] == ["A"]  # YES
    assert press(lua, d, ui=ui("battle_party"), party_cursor=1, **after)[0] == ["Up"]
    assert press(lua, d, ui=ui("battle_party"), party_cursor=0, **after)[0] == ["A"]
    after["active_slot"] = 0
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **after)[0] == ["Right"]     # toward RUN
    assert press(lua, d, ui=ui("battle_menu", MENU, 2, 2), **after)[0] == ["Down"]
    assert press(lua, d, ui=ui("battle_menu", MENU, 4, 2), **after)[0] == ["A"]
    del after["active_slot"]
    buttons, phase = d.step(point(lua, battle_mode=0, overworld_ready=True, **after))
    assert phase == "fainted" and not any(buttons.values())


def test_faint_route_flees_a_splash_only_foe_and_walks_on():
    lua, d = faint_driver()
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), foe_harmless=True)[0] == ["Right"]
    assert press(lua, d, ui=ui("battle_menu", MENU, 2, 2), foe_harmless=True)[0] == ["Down"]   # RUN, not PKMN
    buttons, phase = d.step(point(lua, battle_mode=0, overworld_ready=True))
    assert phase == "walk" and buttons["Left"]


def test_faint_route_refuses_a_zero_hp_target_without_the_engine_faint():
    lua, d = faint_driver()
    press(lua, d, ui=ui("text"))
    buttons, why = d.step(point(lua, battle_mode=0, overworld_ready=True, party_hp={0: 17, 1: 0}))
    assert buttons is None and "never observed" in why


def test_faint_route_switches_a_tackle_only_target_out_instead_of_attacking():
    """C<->G faint RED run 1 ("survived 3 battles"): a morning/day Route 29 catch (Pidgey/Sentret L2-3,
    pokecrystal data/wild/johto_grass.asm:1237-1254) knows only TACKLE (evos_attacks.asm:226, :2194), so the
    old fallback attacked and KO'd the foe. Pass the turn by switching instead (TryPlayerSwitch: the foe hits
    the incoming mon) and switch the target back in next turn; never FIGHT with it."""
    lua, d = faint_driver()
    on = {"active_slot": 1}
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **on)[0] == ["A"]              # FIGHT: moves unknown yet
    assert press(lua, d, ui=ui("move_menu", ["TACKLE"]), **on)[0] == ["B"]                # no passive move: back out
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **on)[0] == ["Right"]          # PKMN, not FIGHT
    assert press(lua, d, ui=ui("battle_party"), party_cursor=1, **on)[0] == ["Up"]        # the other living mon
    assert press(lua, d, ui=ui("battle_party"), party_cursor=0, **on)[0] == ["A"]
    assert press(lua, d, ui=ui("battle_mon_menu", ["SWITCH", "STATS", "CANCEL"]), **on)[0] == ["A"]
    back = {"active_slot": 0}
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **back)[0] == ["Right"]        # PKMN: target back in
    assert press(lua, d, ui=ui("battle_party"), party_cursor=0, **back)[0] == ["Down"]
    assert press(lua, d, ui=ui("battle_party"), party_cursor=1, **back)[0] == ["A"]
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **on)[0] == ["Right"]          # still no FIGHT


def test_faint_route_switches_out_once_the_passive_move_hits_zero_pp():
    """Silver U1 stall (frame 57680, battle_mode=1): a long fight can drain GROWL's 38 PP. Once it hits 0 the
    driver must not keep re-selecting it (the engine's "no PP left" refusal never advances the turn) -- it
    passes the turn by switching out instead, same as a target with no passive move at all."""
    lua, d = faint_driver()
    on = {"active_slot": 1}
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **on)[0] == ["A"]                       # FIGHT
    spent = ui("move_menu", ["TACKLE", "GROWL"], cursor=2, pp={1: 35, 2: 0})
    assert press(lua, d, ui=spent, **on)[0] == ["B"]                                                # GROWL is spent: back out
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **on)[0] == ["Right"]                    # PKMN, not FIGHT
    assert press(lua, d, ui=ui("battle_party"), party_cursor=1, **on)[0] == ["Up"]
    assert press(lua, d, ui=ui("battle_party"), party_cursor=0, **on)[0] == ["A"]
    assert press(lua, d, ui=ui("battle_mon_menu", ["SWITCH", "STATS", "CANCEL"]), **on)[0] == ["A"]


def test_faint_route_attacks_with_a_tackle_only_target_when_it_is_the_last_mon_standing():
    lua, d = faint_driver()
    last = {"active_slot": 1, "party_hp": {0: 0, 1: 9}}
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **last)[0] == ["A"]
    assert press(lua, d, ui=ui("move_menu", ["TACKLE"]), **last)[0] == ["A"]


def frame_align():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    return lua, lua.execute((ROOT / "lua/tests/gen2_frame_align.lua").read_text(encoding="utf-8"))


def test_every_leg_settles_a_stale_save_yes_no_before_its_driver_runs():
    """C<->G faint RED run 2 ("UI is not valid in phase walk: yes_no"): a leg that starts right after a save
    sees the save's overwrite yes_no as the newest UI (save_completed fires at _SaveGameData, then SavedTheGame
    idles 32 frames + text + SFX + 30 frames with no UI origin and no overworld tick, pokecrystal
    engine/menus/save.asm:241-264). F.play idles until the overworld tick is back or a battle is up."""
    lua, F = frame_align()
    FI = lua.execute(FAINT_INPUTS.read_text(encoding="utf-8"))
    walk = lua.eval("{walk_direction=function() return 'Left' end}")
    driver = FI.driver(walk, lua.table_from({}), lua.table_from({"target": 1}))
    stale = {"battle_mode": 0, "overworld_ready": False, "input_ready": True, "party_hp": {0: 17, 1: 14},
             "ui": {"kind": "yes_no", "prompt": "save_overwrite", "items": {1: "YES", 2: "NO"}, "cursor": 1,
                    "columns": 1}}
    back = {"battle_mode": 0, "overworld_ready": True, "party_hp": {0: 17, 1: 14}, "x": 1, "y": 1}
    points = lua.table_from([lua.table_from(p, recursive=True) for p in [stale] * 5 + [back]])
    seen = []
    # A host that runs one step per point and records (phase, pressed buttons); observe walks the same points.
    host, observe = lua.eval("""function(points, record)
        local i = 0
        return {run=function(spec, step)
            for frame = 1, #points do
                local buttons, phase = step(frame)
                record(phase, buttons)
            end
            return "done"
        end}, function() i = i + 1 return points[i] end
    end""")(points, lambda phase, buttons: seen.append((phase, sorted(k for k, v in buttons.items() if v))))
    diag = lua.table_from({"log": lambda line: None, "frame": lambda: 0, "screen": lambda: lua.table_from({}),
                           "where": lambda: "-", "trace": False})
    ok, outcome = F.play(host, lua.table_from({"terminal": driver.terminal}), driver, observe, diag)
    assert ok is True, outcome
    assert seen == [("settle", [])] * 5 + [("walk", ["Left"])]


def test_party_cursor_reads_the_source_geometry():
    lua = LuaRuntime(unpack_returned_tuples=True)
    FI = lua.execute(FAINT_INPUTS.read_text(encoding="utf-8"))
    rows = [[" "] * 20 for _ in range(18)]
    rows[3][0] = "▶"                  # screen row 3 (0-based) = 1 + 2*1: list entry 1
    as_lua = lambda r: lua.table_from([lua.table_from(row) for row in r])
    assert FI.party_cursor(as_lua(rows)) == 1
    rows[2][0] = "▶"
    assert FI.party_cursor(as_lua(rows)) is None   # two cursors / an odd row: refused


def test_move_list_reads_the_source_geometry_under_the_move_info_box():
    """The live U1d stall screen (2026-09-23): MoveInfoBox's border overwrote the move Textbox corner."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    FI = lua.execute(FAINT_INPUTS.read_text(encoding="utf-8"))
    screen = [" " * 20] * 12 + ["└─────────┘────────┐", "│   │▶SCRATCH      │", "│   │ LEER         │",
                                "│   │ -            │", "│   │ -            │", "└───└──────────────┘"]
    as_lua = lambda rows: lua.table_from([lua.table_from(list(r)) for r in rows])
    got = FI.move_list(as_lua(screen))
    assert list(got["items"].values()) == ["SCRATCH", "LEER"] and got["cursor"] == 1 and got["columns"] == 1
    screen[13], screen[14] = "│   │ SCRATCH      │", "│   │▶LEER         │"   # 1-based rows 14, 15
    assert FI.move_list(as_lua(screen))["cursor"] == 2
    screen[13] = "│   │▶SCRATCH      │"
    assert FI.move_list(as_lua(screen)) is None   # two cursors: refused


def repeat_write(**changes):
    """B's half with an O-24 repeat PARTY_HP_WRITE right after the first one."""
    lines = faint_lines("b")
    first = json.loads(lines[10][len("PARTY_HP_WRITE "):])
    again = dict(first, frame=first["frame"] + 90, before_party_hex=first["after_party_hex"])
    again.update(changes)
    return lines[:11] + ["PARTY_HP_WRITE " + json.dumps(again)] + lines[11:]


def test_faint_verdict_accepts_one_idempotent_repeat_write():
    problems, receipt = faint_verdict(repeat_write())
    assert problems == [] and receipt["write"]["frame"] == 3200, problems


@pytest.mark.parametrize("changes,match", [
    ({"after_party_hex": "11" * 288}, "not idempotent"),
    ({"before_party_hex": "22" * 288}, "not idempotent"),
    ({"ok": False}, "write failed"),
], ids=["changed-bytes", "other-preimage", "repeat-failed"])
def test_faint_verdict_refuses_a_non_idempotent_repeat(changes, match):
    problems, receipt = faint_verdict(repeat_write(**changes))
    assert receipt is None and any(match in p for p in problems), problems


def test_faint_verdict_refuses_a_third_write():
    lines = repeat_write()
    problems, receipt = faint_verdict(lines[:12] + [lines[11]] + lines[12:])
    assert receipt is None and any("3 PARTY_HP_WRITE" in p for p in problems), problems


# --- admit_wrong_rom (C-1, C-6g) -----------------------------------------------------------------------

ADMIT = ROOT / "lua/tests/duo/scenario_gen2_admit_wrong_rom.lua"
DRIVER_FILES += ("lua/tests/duo/scenario_gen2_admit_wrong_rom.lua",)


def refuse(sim, glob):
    glob.SLINK_TEST_REFUSE = True


def test_admit_wrong_rom_admitted_half_hellos_holds_saves_and_passes(tmp_path):
    lines, sim, _ = run_driver(tmp_path, scenario="admit_wrong_rom")
    assert lines[-1] == "RESULT: PASS (admitted and held)", "\n".join(lines[-20:])
    receipt = tag_json(lines, "RECEIPT")
    assert receipt["schema"] == "gen2-duo-admit-wrong-rom-v1" and receipt["expect_admission"] == "admitted"
    assert tag_json(lines, "HOLD")["hellos"] == 1 and sim.writes == []


def test_admit_wrong_rom_refused_half_is_silent_and_presses_nothing(tmp_path):
    lines, sim, _ = run_driver(tmp_path, scenario="admit_wrong_rom", player="b",
                               duo={"expect_admission": "refused"}, setup=refuse)
    assert lines[-1] == "RESULT: PASS (refused, silent, CartRAM unchanged)", "\n".join(lines)
    head = tag_json(lines, "DUO_GEN2")
    assert head["expect_admission"] == "refused" and head["rom_sha1"] == sim.facts["rom_sha1"].lower()
    assert "refused (production admission)" in tag_json(lines, "ADMISSION_REFUSED")["console"]
    assert tag_json(lines, "NO_TRAFFIC")["tx"] == 0
    cart = tag_json(lines, "CARTRAM_UNCHANGED")
    assert cart["before"] == cart["after"] == hashlib.sha256(sim.cart[:0x8000]).hexdigest()
    assert not any(line.startswith(("CLIENT", "BOOTED", "HELLO", "TX ")) for line in lines)
    assert all(not any(row.values()) for row in sim.inputs)   # idle frames only


def test_admit_wrong_rom_refused_half_fails_when_the_rom_is_admitted(tmp_path):
    lines, _, _ = run_driver(tmp_path, scenario="admit_wrong_rom", player="b", duo={"expect_admission": "refused"})
    assert lines[-1] == "RESULT: FAIL (the unadmitted ROM started a client)"


def test_admit_wrong_rom_refused_half_needs_the_go_file(tmp_path):
    lines, _, _ = run_driver(tmp_path, scenario="admit_wrong_rom", player="b", go=False,
                             duo={"expect_admission": "refused", "timeout_frames": 600}, setup=refuse)
    assert lines[-1].startswith("RESULT: FAIL") and "timeout" in lines[-1], lines[-1]


def admit_verdict(lines):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    problems, receipt = lua.execute(ADMIT.read_text(encoding="utf-8")).verdict(lua.table_from(lines), json_codec)
    return list(problems.values()), receipt


def refused_lines():
    j = json.dumps
    return ["DUO_GEN2 " + j({"player": "b", "scenario": "admit_wrong_rom", "attempt": 1, "title": "crystal",
                             "rom_sha1": "ab" * 20, "expect_admission": "refused"}),
            "ADMISSION_REFUSED " + j({"frame": 0, "rom_sha1": "ab" * 20, "client": False,
                                      "console": "[SLink-gen2] crystal cartridge refused (production admission): x"}),
            "NO_TRAFFIC " + j({"frame": 700, "frames": 600, "tx": 0}),
            "CARTRAM_UNCHANGED " + j({"before": "cd" * 32, "after": "cd" * 32})]


def admitted_lines():
    lines = [line for line in happy_lines() if not line.startswith(("ENGINE_CAPTURE", "CAPTURE_SENT", "CAUGHT"))]
    lines[0] = lines[0].replace('"scenario": "link"', '"scenario": "admit_wrong_rom"')
    return lines[:-1] + ["HOLD " + json.dumps({"frame": 1000, "frames": 600, "hellos": 1}), lines[-1]]


def test_admit_verdict_passes_each_complete_half():
    for lines, kind in ((refused_lines(), "refused"), (admitted_lines(), "admitted")):
        problems, receipt = admit_verdict(lines)
        assert problems == [] and receipt["expect_admission"] == kind, problems


@pytest.mark.parametrize("lines,match", [
    (refused_lines() + ['TX {"event":"hello"}'], "sent on the wire"),
    (refused_lines()[:1] + refused_lines()[2:], "missing ADMISSION_REFUSED"),
    ([x.replace('"tx": 0', '"tx": 3') for x in refused_lines()], "sent on the wire"),
    (refused_lines()[:3] + ["CARTRAM_UNCHANGED " + json.dumps({"before": "cd" * 32, "after": "ce" * 32})],
     "changed its CartRAM"),
    (refused_lines()[:1] + [refused_lines()[2], refused_lines()[1], refused_lines()[3]], "NO_TRAFFIC before"),
    (refused_lines() + [happy_lines()[4]], "printed HELLO"),
    ([x.replace('"console": "[SLink-gen2] crystal cartridge refused (production admission): x"', '"console": ""')
      for x in refused_lines()], "no refusal line"),
    (admitted_lines() + ["HELLO_AGAIN " + json.dumps({"frame": 1, "ot_id": 1, "n": 2})], "more than once"),
    ([x for x in admitted_lines() if not x.startswith("HOLD")], "missing HOLD"),
    (admitted_lines()[:-2] + [admitted_lines()[-1], admitted_lines()[-2]], "save witness before HOLD"),
], ids=["refused-tx", "no-refusal", "refused-count", "cart-changed", "quiet-first", "refused-hello", "no-console",
        "rehello", "no-hold", "save-first"])
def test_admit_verdict_refuses_a_tampered_half(lines, match):
    problems, receipt = admit_verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


# --- reconnect (C-2, D-14) -----------------------------------------------------------------------------

RECONNECT = ROOT / "lua/tests/duo/scenario_gen2_reconnect.lua"
DRIVER_FILES += ("lua/tests/duo/scenario_gen2_reconnect.lua",)


def mykey(lines):
    return next(line.split()[2] for line in lines if line.startswith("MYKEY 0 "))


def test_reconnect_initial_b_links_saves_and_stays_until_b_done(tmp_path):
    lines, _, _ = run_driver(tmp_path, scenario="reconnect", player="b", duo={"phase": "initial"},
                             go_text="GO\nB_DONE\n")
    assert lines[-1] == "RESULT: PASS (B remained online through both A relaunches)", "\n".join(lines[-20:])
    assert tag_json(lines, "RECONNECT_READY")["key"] == KEY
    stayed = tag_json(lines, "B_STAYED")
    assert (stayed["hellos"], stayed["force_faint"], stayed["box_mon"]) == (1, 0, 0)
    receipt = tag_json(lines, "RECEIPT")
    assert receipt["schema"] == "gen2-duo-reconnect-v1" and receipt["phase"] == "initial" and receipt["key"] == KEY


def test_reconnect_initial_a_waits_for_the_kill_and_never_passes(tmp_path):
    lines, _, _ = run_driver(tmp_path, scenario="reconnect", duo={"phase": "initial"})
    assert tag_json(lines, "RECONNECT_READY")["player"] == "a"
    assert lines[-1].startswith("RESULT: FAIL") and "timeout" in lines[-1], lines[-1]


def test_reconnect_same_save_relaunch_finds_the_linked_key(tmp_path):
    probe, _, _ = run_driver(tmp_path / "probe", scenario="reconnect",
                             duo={"phase": "same_save", "expected_key": "0000:0000:01"}, go_text="GO\nA_DONE_SAME")
    assert probe[-1] == "RESULT: FAIL (same-save relaunch lost the linked key)"
    key = mykey(probe)
    lines, sim, _ = run_driver(tmp_path / "run", scenario="reconnect",
                               duo={"phase": "same_save", "expected_key": key}, go_text="GO\nA_DONE_SAME")
    assert lines[-1] == "RESULT: PASS (same_save hello observed once)", "\n".join(lines[-20:])
    back = tag_json(lines, "RECONNECT_HELLO")
    assert back["linked"] is True and back["hellos"] == 1 and back["expected_key"] == key
    assert sim.writes == [] and not any(line.startswith("ENGINE_CAPTURE") for line in lines)


def wrong_hud(sim, glob):
    glob.SLINK_TEST_COMMANDS = sim.lua.table_from([sim.lua.table_from(
        {"cmd": "hud_show", "text": "[x] WRONG SAVE: slot A", "color": sim.lua.table_from([255, 0, 0]),
         "duration": 600})])


def test_reconnect_wrong_save_relaunch_sees_the_wrong_save_hud(tmp_path):
    lines, _, _ = run_driver(tmp_path, scenario="reconnect", duo={"phase": "wrong_save", "expected_key": KEY},
                             go_text="GO\nA_DONE_WRONG", setup=wrong_hud)
    assert lines[-1] == "RESULT: PASS (wrong_save hello observed once)", "\n".join(lines[-20:])
    assert tag_json(lines, "WRONG_SAVE_HUD")["text"] == "[x] WRONG SAVE: slot A"
    assert tag_json(lines, "RECONNECT_HELLO")["linked"] is False


def test_reconnect_wrong_save_without_the_hud_fails(tmp_path):
    lines, _, _ = run_driver(tmp_path, scenario="reconnect", duo={"phase": "wrong_save", "expected_key": KEY},
                             go_text="GO\nA_DONE_WRONG")
    assert lines[-1] == "RESULT: FAIL (wrong-save relaunch did not receive the WRONG SAVE hud)"


def test_reconnect_refuses_an_unknown_phase(tmp_path):
    lines, sim, _ = run_driver(tmp_path, scenario="reconnect")
    assert lines[-1] == "RESULT: FAIL (unknown reconnect phase nil)" and not sim.inputs


def reconnect_verdict(lines):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    link = lua.execute(SCENARIO.read_text(encoding="utf-8"))
    problems, receipt = lua.execute(RECONNECT.read_text(encoding="utf-8")).verdict(
        lua.table_from(lines), json_codec, link.verdict)
    return list(problems.values()), receipt


def initial_b_lines():
    j = json.dumps
    lines = [line.replace('"player": "a", "scenario": "link"', '"player": "b", "scenario": "reconnect"')
             for line in happy_lines()]
    return lines + ["RECONNECT_READY " + j({"frame": 1600, "phase": "initial", "player": "b", "key": KEY}),
                    "RX resolved_areas",
                    "B_STAYED " + j({"frame": 9000, "hellos": 1, "force_faint": 0, "box_mon": 0})]


def relaunch_lines(phase):
    j = json.dumps
    lines = [line.replace('"scenario": "link"', '"scenario": "reconnect"') for line in happy_lines()[:5]]
    lines.append("RECONNECT_HELLO " + j({"frame": 400, "phase": phase, "hellos": 1, "ot_id": 46401,
                                         "expected_key": KEY, "linked": phase == "same_save"}))
    if phase == "wrong_save":
        lines += ["RX hud_show", "RX_TEXT " + j({"frame": 401, "cmd": "hud_show", "text": "[x] WRONG SAVE: slot A"}),
                  "WRONG_SAVE_HUD " + j({"frame": 402, "text": "[x] WRONG SAVE: slot A"})]
    return lines


def test_reconnect_verdict_passes_each_complete_leg():
    for lines, phase in ((initial_b_lines(), "initial"), (relaunch_lines("same_save"), "same_save"),
                         (relaunch_lines("wrong_save"), "wrong_save")):
        problems, receipt = reconnect_verdict(lines)
        assert problems == [] and receipt["phase"] == phase and receipt["schema"] == "gen2-duo-reconnect-v1", problems


@pytest.mark.parametrize("lines,match", [
    (initial_b_lines()[:-1] + ["RX force_faint key=" + KEY, initial_b_lines()[-1]], "force_faint/box_mon"),
    (initial_b_lines() + ["HELLO_AGAIN " + json.dumps({"frame": 1, "ot_id": 46401, "n": 2})], "second hello"),
    ([x.replace('"hellos": 1, "force_faint"', '"hellos": 2, "force_faint"') for x in initial_b_lines()],
     "more than once"),
    ([x for x in initial_b_lines() if not x.startswith("B_STAYED")], "missing B_STAYED"),
    ([x.replace('"player": "b", "key": "' + KEY, '"player": "b", "key": "0000:0000:01') for x in initial_b_lines()],
     "another key"),
    ([x for x in initial_b_lines() if not x.startswith("SAVE_WITNESS")], "missing SAVE_WITNESS"),
    ([x.replace('"linked": true', '"linked": false') for x in relaunch_lines("same_save")], "lost the linked key"),
    (relaunch_lines("same_save") + ["RX box_mon key=" + KEY], "force_faint/box_mon"),
    (relaunch_lines("same_save") + ["HELLO_AGAIN " + json.dumps({"frame": 1, "ot_id": 1, "n": 2})], "second hello"),
    ([x for x in relaunch_lines("wrong_save") if not x.startswith("RX_TEXT")], "no WRONG SAVE hud"),
    ([x.replace('"linked": false', '"linked": true') for x in relaunch_lines("wrong_save")], "holds the linked key"),
    (relaunch_lines("wrong_save")[:1] + relaunch_lines("wrong_save")[2:], "missing CLIENT"),
], ids=["b-force-faint", "b-rehello", "b-count", "b-no-stay", "ready-key", "no-link-save", "same-lost",
        "same-box-mon", "same-rehello", "wrong-no-hud", "wrong-linked", "no-client"])
def test_reconnect_verdict_refuses_a_tampered_leg(lines, match):
    problems, receipt = reconnect_verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


# --- soft_reset (C-2 WRAM clear, R-4, W-6) -------------------------------------------------------------

SOFT_RESET = ROOT / "lua/tests/duo/scenario_gen2_soft_reset.lua"
DRIVER_FILES += ("lua/tests/duo/scenario_gen2_soft_reset.lua",)
CHORD = {"A", "B", "Select", "Start"}


class ResetSim(DuoSim):
    """UpdateJoypad's soft reset: all four buttons held -> Reset (DelayFrames 32) -> Init zero-fills WRAM ->
    the title again; CONTINUE reloads the same battery save. No battle on this route."""

    def __init__(self, lua, title="crystal", *, clear_delay=32, **kw):
        self.resets, self.clear_delay = 0, clear_delay
        super().__init__(lua, title, **kw)

    def game(self):
        while True:
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
            while True:
                self.fire("overworld_tick")
                got = yield
                if CHORD <= got.held:
                    self.resets += 1
                    yield from self.wait(self.clear_delay)
                    self.wram[:] = bytes(len(self.wram))
                    self.clear()
                    break
                if "Start" in got.edges:
                    yield from self.save()


def live_party(sim, glob):
    glob.SLINK_TEST_LIVE = lambda: sim.get("wPartyCount") > 0


def chord_gate(tmp_path):
    (tmp_path / "go_a.txt.chord").write_text("CHORD", encoding="utf-8")


def run_reset(tmp_path, *, gate=True, **kw):
    if gate:
        chord_gate(tmp_path)
    return run_driver(tmp_path, scenario="soft_reset", sim_class=ResetSim, setup=live_party,
                      duo={"timeout_frames": 20000}, **kw)


def test_soft_reset_a_resets_withholds_continues_rehellos_and_saves(tmp_path):
    lines, sim, _ = run_reset(tmp_path)
    assert lines[-1] == "RESULT: PASS (same-save soft reset: one re-hello, no writes in the cleared window)", \
        "\n".join(lines[-30:])
    assert sim.resets == 1 and sim.writes == []
    assert tag_json(lines, "RESET_SEEN")["delta"] == 33
    assert 240 <= tag_json(lines, "WRITES_PAUSED")["delta"] <= 300
    assert tag_json(lines, "REHELLO")["ot_id"] == tag_json(lines, "HELLO")["ot_id"]
    tags = [line.split(" ", 1)[0] for line in lines]
    order = [tags.index(t) for t in ("HELLO_AT_CHECKPOINT", "CHORD_GATE", "CHORD", "RESET_SEEN", "WRITES_PAUSED",
                                     "REBOOTED", "WRITES_RESUMED", "REHELLO", "NO_WRITES_IN_WINDOW", "SAVE_WITNESS",
                                     "RECEIPT")]
    assert order == sorted(order)
    chord = [row for row in sim.inputs if all(row.get(b) for b in CHORD)]
    assert len(chord) == 4 and all(set(row) <= {"Up", "Down", "Left", "Right", "A", "B", "Start", "Select"}
                                   for row in sim.inputs)


def test_soft_reset_a_waits_for_the_chord_gate(tmp_path):
    lines, sim, _ = run_reset(tmp_path, gate=False)
    assert lines[-1] == "RESULT: FAIL (chord gate never released)" and sim.resets == 0


def test_soft_reset_a_fails_when_the_chord_clears_nothing(tmp_path):
    lines, _, _ = run_reset(tmp_path, clear_delay=200)
    assert lines[-1] == "RESULT: FAIL (the soft reset chord did not clear WRAM)"


def test_soft_reset_b_idles_until_the_partner_rehellos(tmp_path):
    (tmp_path / "b.txt").write_text('REHELLO {"frame": 1}\n', encoding="utf-8")
    lines, sim, _ = run_driver(tmp_path, scenario="soft_reset", player="b", sim_class=ResetSim, setup=live_party)
    assert lines[-1] == "RESULT: PASS (idled at the checkpoint across the partner reset)", "\n".join(lines[-20:])
    assert tag_json(lines, "IDLE_PARTNER")["hellos"] == 1 and sim.resets == 0


def soft_verdict(lines):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    problems, receipt = lua.execute(SOFT_RESET.read_text(encoding="utf-8")).verdict(lua.table_from(lines), json_codec)
    return list(problems.values()), receipt


def soft_lines(player):
    j = json.dumps
    base = [line.replace('"player": "a", "scenario": "link"', f'"player": "{player}", "scenario": "soft_reset"')
            for line in happy_lines()[:5]]
    save = "SAVE_WITNESS " + j({"frame": 5000, "save_completed_frame": 4900, "gate_saves": 1, "client_saves": 1,
                                "cartram_sha256": "cd" * 32, "cartram_bytes": 32768, "saveram_path": "C:/x/y.SaveRAM",
                                "saveram_bytes": 32790, "flushed_matches": True})
    if player == "b":
        return base + ["IDLE_PARTNER " + j({"frame": 4000, "hellos": 1}), save]
    return base + [
        "HELLO_AT_CHECKPOINT " + j({"frame": 400, "ot_id": 46401, "hellos": 1, "writes_enabled": True}),
        "CHORD_GATE " + j({"frame": 410}),
        "CHORD " + j({"frame": 410, "frames": 4}),
        "RESET_SEEN " + j({"frame": 443, "delta": 33}),
        "HELLO_CLEARED " + j({"frame": 443, "delta": 0}),
        "WRITES_PAUSED " + j({"frame": 720, "delta": 277}),
        "HELLO_AGAIN " + j({"frame": 1400, "ot_id": 46401, "n": 2}),
        "REBOOTED " + j({"frame": 1420, "map_group": 24, "map_number": 3, "x": 10, "y": 10, "party_count": 1}),
        "WRITES_RESUMED " + j({"frame": 1440, "delta": 997}),
        "REHELLO " + j({"frame": 1441, "ot_id": 46401, "hellos": 2}),
        "NO_WRITES_IN_WINDOW " + j({"writes": 0}),
        save]


def soft_mutate(player, tag, **changes):
    out = []
    for line in soft_lines(player):
        if line.startswith(tag + " "):
            value = json.loads(line[len(tag) + 1:])
            value.update(changes)
            line = f"{tag} {json.dumps(value)}"
        out.append(line)
    return out


def test_soft_verdict_passes_each_complete_half():
    for player in ("a", "b"):
        problems, receipt = soft_verdict(soft_lines(player))
        assert problems == [] and receipt["schema"] == "gen2-duo-soft-reset-v1" and receipt["player"] == player, problems


def soft_drop(player, tag):
    return [line for line in soft_lines(player) if not line.startswith(tag + " ")]


@pytest.mark.parametrize("lines,match", [
    (soft_mutate("a", "RESET_SEEN", delta=12), "DelayFrames window"),
    (soft_mutate("a", "RESET_SEEN", delta=90), "DelayFrames window"),
    (soft_mutate("a", "HELLO_CLEARED", delta=400), "withdrawn too late"),
    (soft_mutate("a", "WRITES_PAUSED", delta=60), "MAX_INVALID window"),
    (soft_mutate("a", "REHELLO", ot_id=1), "another OT"),
    (soft_mutate("a", "HELLO_AGAIN", ot_id=1), "pre-reset OT"),
    (soft_mutate("a", "NO_WRITES_IN_WINDOW", writes=2), "write landed"),
    (soft_mutate("a", "HELLO_AT_CHECKPOINT", writes_enabled=False), "writes enabled"),
    (soft_mutate("a", "SAVE_WITNESS", save_completed_frame=1000), "before the re-hello"),
    (soft_drop("a", "HELLO_AGAIN"), "missing HELLO_AGAIN"),
    (soft_drop("a", "CHORD_GATE"), "missing CHORD_GATE"),
    (soft_drop("a", "REBOOTED"), "missing REBOOTED"),
    (soft_lines("a")[:10] + [soft_lines("a")[12], soft_lines("a")[10], soft_lines("a")[11]] + soft_lines("a")[13:],
     "REBOOTED before writes paused"),
    (soft_lines("a") + [happy_lines()[5]], "was caught"),
    (soft_lines("b")[:-1] + [soft_lines("a")[5], soft_lines("b")[-1]], "partner printed HELLO_AT_CHECKPOINT"),
    (soft_mutate("b", "IDLE_PARTNER", hellos=2), "more than once"),
    (soft_lines("b")[:-2] + [soft_lines("b")[-1], soft_lines("b")[-2]], "before IDLE_PARTNER"),
], ids=["reset-early", "reset-late", "hello-late", "pause-early", "rehello-ot", "again-ot", "writes", "not-enabled",
        "save-early", "no-again", "no-gate", "no-reboot", "reboot-before-pause", "caught", "b-chord", "b-rehello",
        "b-save-first"])
def test_soft_verdict_refuses_a_tampered_half(lines, match):
    problems, receipt = soft_verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


# --- the clause scenarios (wave B: type_clause, gender_clause, species_clause) ---------------------------

CLAUSE = ROOT / "lua/tests/duo/gen2_clause.lua"
DRIVER_FILES += ("lua/tests/duo/gen2_clause.lua", "lua/tests/duo/scenario_gen2_type_clause.lua",
                 "lua/tests/duo/scenario_gen2_gender_clause.lua", "lua/tests/duo/scenario_gen2_species_clause.lua")
RATTATA_KEY = "1A2B:B542:13"
LINKED_TEXT = "Pidgey and Rattata linked!"
class LaterLinkSim(DuoSim):
    """C<->G reconnect RED run 1's order: this side catches FIRST, the server boxes the pending catch
    (box_mon), and only when the partner catches does it link and withdraw it (msgbox + party_mon), here
    `link_after` frames after the catch (None: never)."""

    def __init__(self, lua, title="crystal", *, link_after=600, **kw):
        self.link_after, self.box_log = link_after, []
        super().__init__(lua, title, link_reply=False, **kw)

    def on_caught(self, species, key):
        self.command(cmd="box_mon", key=key)
        left = [self.link_after]

        def later():
            if left[0] is None:
                return
            left[0] -= 1
            if left[0] == 0:
                self.command(cmd="msgbox", text="HOPPIP and PIDGEY linked!")
                self.command(cmd="party_mon", key=key)
        self.frame_hooks.append(later)


def order(lines, *prefixes):
    return [next(i for i, line in enumerate(lines) if line.startswith(p)) for p in prefixes]


def test_reconnect_initial_saves_only_after_its_link_and_box_ops_settled(tmp_path):
    lines, _, _ = run_driver(tmp_path, scenario="reconnect", player="b", duo={"phase": "initial"},
                             go_text="GO\nB_DONE\n", sim_class=LaterLinkSim)
    assert lines[-1].startswith("RESULT: PASS"), "\n".join(lines[-20:])
    linked, withdrawn, saved, ready = order(lines, 'RX_TEXT {"cmd":"msgbox"', 'TX {"event":"sync_retrieve_done"',
                                            "SAVE_WITNESS", "RECONNECT_READY")
    assert linked < withdrawn < saved < ready


def test_link_never_saves_while_the_catch_is_unlinked(tmp_path):
    lines, _, _ = run_driver(tmp_path, sim_class=LaterLinkSim, link_after=None)
    assert lines[-1].startswith("RESULT: FAIL") and not any(line.startswith("SAVE_WITNESS") for line in lines)


def test_memorial_preimage_is_the_party_record_at_the_run_box_entry_once_per_key(tmp_path):
    probe, _, _ = run_driver(tmp_path / "probe")
    starter = mykey(probe)

    def memorialize_twice(sim, species, key):
        sim.command(cmd="memorialize", key=starter)
        sim.command(cmd="memorialize", key=starter)
    lines, sim, _ = run_driver(tmp_path / "run", sim_class=ClauseSim, link_reply=True, after_catch=memorialize_twice)
    rows = [json.loads(line[len("MEMORIAL_PREIMAGE "):]) for line in lines if line.startswith("MEMORIAL_PREIMAGE ")]
    assert len(rows) == 1, "\n".join(lines[-20:])
    row = rows[0]
    assert row["key"] == starter and row["slot"] == 0
    assert bytes.fromhex(row["raw_hex"]) == bytes(sim.wram[sim.offset("wPartyMon1"):sim.offset("wPartyMon1") + 48])
    assert row["species_marker"] == sim.get("wPartySpecies") and len(row["ot_raw_hex"]) == len(row["nickname_raw_hex"]) == 22


DECOMPS = ROOT / ".cache/gen2-build"


class ClauseSim(DuoSim):
    """DuoSim whose battles follow `foes` [(species, key), ...] (the last repeats), RUN from `dupe`, and whose
    server answers through after_catch(sim, species, key) / after_flee(sim, species)."""

    def __init__(self, lua, title="crystal", *, foes=((16, KEY),), dupe=None, after_catch=None, after_flee=None, **kw):
        self.foes, self.dupe, self.after_catch, self.after_flee, self.battles = list(foes), dupe, after_catch, after_flee, []
        kw.setdefault("link_reply", False)   # the clause server answers through after_catch/after_flee
        super().__init__(lua, title, **kw)

    def next_foe(self):
        return self.foes[min(len(self.battles), len(self.foes) - 1)]

    def battle_choice(self, species):
        self.battles.append(species)
        return "RUN" if species == self.dupe else "PACK"

    def on_fled(self, species):
        if self.after_flee:
            self.after_flee(self, species)

    def on_caught(self, species, key):
        if self.after_catch:
            self.after_catch(self, species, key)


def boo(sim, species, key):
    sim.command(cmd="play_sound", sound=22)


def linked(sim, species, key):
    sim.command(cmd="play_sound", sound=25)
    sim.command(cmd="msgbox", text=LINKED_TEXT)


def reroll_prompt(sim, species):
    sim.command(cmd="gui_prompt", text="Dupes clause: Pidgey -- reroll!")
    sim.command(cmd="unresolve_area", area_id="route_29")


def run_clause(tmp_path, scenario, **kw):
    return run_driver(tmp_path, scenario=scenario, sim_class=ClauseSim, **kw)


def test_type_clause_partner_rejected_half_saves_again_and_passes(tmp_path):
    lines, sim, _ = run_clause(tmp_path, "type_clause", after_catch=boo)
    assert lines[-1] == f"RESULT: PASS (type clause partner_rejected {KEY} (clause_observed))", "\n".join(lines[-30:])
    capture = tag_json(lines, "CLAUSE_CAPTURE")
    assert (capture["species_id"], capture["types"], capture["gender"]) == (16, ["Normal", "Flying"], "female")
    receipt = tag_json(lines, "RECEIPT")
    assert receipt["schema"] == "gen2-duo-type-clause-v1" and receipt["verdict"] == "partner_rejected"
    assert "RX play_sound sound=22" in lines and sim.writes == []
    assert tag_json(lines, "SAVE_WITNESS")["gate_saves"] >= 2   # the link save and the final one


def test_type_clause_a_pidgey_that_links_is_refused(tmp_path):
    lines, _, _ = run_clause(tmp_path, "type_clause", after_catch=linked)
    assert lines[-1].startswith("RESULT: FAIL") and "Pidgey shares a type with every Route 29 species" in lines[-1]


def test_type_clause_without_a_verdict_never_passes(tmp_path):
    lines, _, _ = run_clause(tmp_path, "type_clause")
    assert lines[-1].startswith("RESULT: FAIL") and "timeout" in lines[-1], lines[-1]
    assert not any(line.startswith("CLAUSE_VERDICT") for line in lines)


def test_gender_clause_linked_half_passes_unobserved(tmp_path):
    lines, _, _ = run_clause(tmp_path, "gender_clause", after_catch=linked)
    assert lines[-1] == f"RESULT: PASS (gender clause linked {KEY} (clause_unobserved))", "\n".join(lines[-30:])
    assert tag_json(lines, "RECEIPT")["path"] == "clause_unobserved"
    assert tag_json(lines, "RX_TEXT")["text"] == LINKED_TEXT


def test_species_clause_a_catches_pends_waits_for_the_link_and_saves(tmp_path):
    lines, _, _ = run_clause(tmp_path, "species_clause", after_catch=linked)
    assert lines[-1] == f"RESULT: PASS (A pending {KEY} linked)", "\n".join(lines[-30:])
    assert tag_json(lines, "PENDING_CAPTURE")["species_id"] == 16
    assert tag_json(lines, "RECEIPT")["role"] == "pending"


def run_reroll(tmp_path, foes, *, flee=reroll_prompt, **kw):
    return run_clause(tmp_path, "species_clause", player="b", go_text="GO\nA_PENDING species=16\n", foes=foes,
                      dupe=16, after_flee=flee, after_catch=linked, **kw)


def test_species_clause_b_runs_from_a_s_species_twice_then_catches_and_links(tmp_path):
    lines, sim, _ = run_reroll(tmp_path, [(16, KEY), (16, KEY), (19, RATTATA_KEY)])
    assert lines[-1] == f"RESULT: PASS (reroll_observed: B linked {RATTATA_KEY} after 2 reroll(s))", "\n".join(lines[-40:])
    assert sim.battles == [16, 16, 19]
    assert [json.loads(x.split(" ", 1)[1])["species_id"] for x in lines if x.startswith("ENCOUNTER ")] == [16, 16, 19]
    receipt = tag_json(lines, "RECEIPT")
    assert (receipt["role"], receipt["rerolls"], receipt["dupe_species"]) == ("reroller", 2, 16)
    assert all(set(row) <= {"Up", "Down", "Left", "Right", "A", "B", "Start", "Select"} for row in sim.inputs)


def test_species_clause_b_catches_a_first_non_duplicate_unobserved(tmp_path):
    lines, sim, _ = run_reroll(tmp_path, [(19, RATTATA_KEY)])
    assert lines[-1] == f"RESULT: PASS (reroll_unobserved: B linked {RATTATA_KEY} after 0 reroll(s))", "\n".join(lines[-30:])
    assert sim.battles == [19]


def test_species_clause_b_fails_a_run_with_no_dupes_prompt(tmp_path):
    lines, sim, _ = run_reroll(tmp_path, [(16, KEY), (19, RATTATA_KEY)], flee=None)
    assert lines[-1] == "RESULT: FAIL (no dupes-clause prompt for species 16 (A's))" and sim.battles == [16]


def test_species_clause_b_only_duplicates_is_an_rng_fail(tmp_path):
    lines, sim, _ = run_reroll(tmp_path, [(16, KEY)], duo={"timeout_frames": 60000})
    assert lines[-1] == "RESULT: FAIL (RNG: the species hunt met only duplicates within its battle budget)", lines[-1]
    assert sim.battles == [16] * 8


def test_species_clause_b_waits_for_a_pending(tmp_path):
    lines, sim, _ = run_clause(tmp_path, "species_clause", player="b", duo={"timeout_frames": 3000})
    assert lines[-1].startswith("RESULT: FAIL") and "timeout" in lines[-1] and sim.battles == []


# --- the reroll's two drivers, pure ---

ROUTE_INPUTS = ROOT / "lua/tests/duo/gen2_route29_inputs.lua"


def route_inputs(lua):
    return lua.execute(ROUTE_INPUTS.read_text(encoding="utf-8"))


def test_encounter_driver_walks_presses_through_the_intro_and_stops_at_the_menu_with_the_foe():
    lua = LuaRuntime(unpack_returned_tuples=True)
    walk = lua.eval("{walk_direction=function() return 'Left' end}")
    d = route_inputs(lua).encounter_driver(walk, lua.table_from({}))
    buttons, phase = d.step(point(lua, battle_mode=0, overworld_ready=True))
    assert dict(buttons) == {"Left": True} and phase == "walk"
    assert press(lua, d, ui=ui("text")) == (["A"], "battle")
    buttons, phase = d.step(point(lua, ui=ui("battle_menu", MENU, 1, 2), foe=19))
    assert phase == "encounter" and d.foe == 19 and not any(buttons.values())
    lua2 = LuaRuntime(unpack_returned_tuples=True)
    d2 = route_inputs(lua2).encounter_driver(lua2.eval("{}"), lua2.table_from({}))
    assert d2.step(point(lua2, ui=ui("battle_menu", MENU, 1, 2)))[1] == "wild battle menu without a foe species"
    assert d2.step(point(lua2, battle_mode=2))[1] == "not a wild battle"


def test_flee_driver_chooses_run_retries_cant_escape_and_ends_in_the_overworld():
    lua = LuaRuntime(unpack_returned_tuples=True)
    d = route_inputs(lua).flee_driver()
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2)) == (["Right"], "battle")
    assert press(lua, d, ui=ui("battle_menu", MENU, 2, 2)) == (["Down"], "battle")
    assert press(lua, d, ui=ui("battle_menu", MENU, 4, 2)) == (["A"], "battle")
    assert press(lua, d, ui=ui("text")) == (["A"], "battle")   # "Can't escape!"
    assert press(lua, d, ui=ui("battle_menu", MENU, 4, 2)) == (["A"], "battle")
    assert d.runs == 2
    assert d.step(point(lua, battle_mode=0, overworld_ready=True))[1] == "escaped"


def test_flee_driver_gives_up_after_max_runs():
    lua = LuaRuntime(unpack_returned_tuples=True)
    R = route_inputs(lua)
    d = R.flee_driver()
    for _ in range(R.MAX_RUNS):
        press(lua, d, ui=ui("battle_menu", MENU, 4, 2))
    assert d.step(point(lua, ui=ui("battle_menu", MENU, 4, 2)))[1] == f"could not escape in {R.MAX_RUNS} RUNs"


# --- the clause verdicts, pure ---

def clause_runtime(name):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    link = lua.execute(SCENARIO.read_text(encoding="utf-8"))
    path = (ROOT / f"lua/tests/duo/scenario_gen2_{name}.lua").as_posix()
    return lua, lua.execute(f'return dofile("{path}")'), json_codec, link


def clause_verdict(name, lines):
    lua, scenario, json_codec, link = clause_runtime(name)
    problems, receipt = scenario.verdict(lua.table_from(lines), json_codec, link.verdict)
    return list(problems.values()), receipt


def clause_lines(kind, verdict, *, ending="dead", species=16, key=KEY):
    def j(value):
        return json.dumps(value, ensure_ascii=False)
    types = {16: ["Normal", "Flying"], 19: ["Normal"], 161: ["Normal"], 163: ["Normal", "Flying"], 187: ["Grass", "Flying"]}
    base = [x.replace('"scenario": "link"', f'"scenario": "{kind}_clause"') for x in happy_lines()[:8]]
    base = [x.replace(KEY, key).replace('"species_id": 16', f'"species_id": {species}') for x in base]
    out = base + ["CLAUSE_CAPTURE " + j({"frame": 1600, "key": key, "species_id": species, "area_id": "route_29",
                                         "types": types[species], "gender": "female"})]
    if verdict == "rejected":
        prompt = "[x] Type clause: shared Normal" if kind == "type" else "[x] Gender clause: both are ♀"
        out += ["RX force_faint key=" + key, "RX memorialize key=" + key, "RX play_sound sound=26", "RX gui_prompt",
                "RX_TEXT " + j({"frame": 1700, "cmd": "gui_prompt", "text": prompt}),
                "RX unresolve_area area_id=route_29",
                "CLAUSE_VERDICT " + j({"frame": 1701, "verdict": "rejected"}),
                "PARTY_HP_WRITE " + j({"frame": 1750, "key": key, "slot": 1, "kind": "party_hp", "ok": True}),
                "MEMORIAL_ACK " + j({"frame": 1760, "event": "memorialize_failed" if ending == "dead" else "memorialize_done",
                                     "key": key, **({"reason": "Gen 2 box executor not composed"} if ending == "dead"
                                                    else {"box": 13})})]
        out.append("REJECTED_MON " + j({"frame": 1770, "key": key, "ending": "dead", "in_party": True, "slot": 1, "hp": 0,
                                        "status": 0} if ending == "dead" else
                                       {"frame": 1770, "key": key, "ending": "memorial", "box": 13, "in_party": False}))
    elif verdict == "partner_rejected":
        out += ["RX play_sound sound=22", "CLAUSE_VERDICT " + j({"frame": 1701, "verdict": "partner_rejected"})]
    else:
        out += ["RX play_sound sound=25", "RX msgbox", "RX_TEXT " + j({"frame": 1700, "cmd": "msgbox", "text": LINKED_TEXT}),
                "CLAUSE_VERDICT " + j({"frame": 1701, "verdict": "linked"})]
    return out + [happy_lines()[8]]


@pytest.mark.parametrize("kind,verdict,ending,species", [
    ("type", "rejected", "dead", 16), ("type", "rejected", "memorial", 16), ("type", "partner_rejected", "dead", 16),
    ("type", "linked", "dead", 187), ("type", "linked", "dead", 161), ("gender", "rejected", "dead", 16),
    ("gender", "rejected", "memorial", 19), ("gender", "linked", "dead", 16)])
def test_clause_verdict_passes_each_complete_ending(kind, verdict, ending, species):
    key = KEY[:-2] + f"{species:02X}"
    problems, receipt = clause_verdict(f"{kind}_clause", clause_lines(kind, verdict, ending=ending, species=species, key=key))
    assert problems == [] and receipt["verdict"] == verdict and receipt["clause"] == kind, problems
    assert receipt["ending"] == (ending if verdict == "rejected" else None)


def cl_replace(lines, old, new):
    out = [x.replace(old, new) for x in lines]
    assert out != lines, old
    return out


def cl_drop(lines, prefix):
    out = [x for x in lines if not x.startswith(prefix)]
    assert len(out) < len(lines), prefix
    return out


def cl_move(lines, prefix, before):
    row = next(x for x in lines if x.startswith(prefix))
    rest = [x for x in lines if x is not row]
    at = next(i for i, x in enumerate(rest) if x.startswith(before))
    return rest[:at] + [row] + rest[at:]


TREJ, TMEM, GREJ = clause_lines("type", "rejected"), clause_lines("type", "rejected", ending="memorial"), \
    clause_lines("gender", "rejected")


@pytest.mark.parametrize("name,lines,match", [
    ("type_clause", cl_replace(TREJ, "shared Normal", "shared Grass"), "a type the catch lacks: Grass"),
    ("type_clause", cl_replace(TREJ, "shared Normal", "shared "), "names no shared type"),
    ("type_clause", cl_drop(TREJ, "PARTY_HP_WRITE"), "no production PARTY_HP_WRITE"),
    ("type_clause", cl_replace(TREJ, '"ok": true', '"ok": false'), "no production PARTY_HP_WRITE"),
    ("type_clause", cl_drop(TREJ, "MEMORIAL_ACK"), "no MEMORIAL_ACK"),
    ("type_clause", cl_drop(TREJ, "RX memorialize"), "no memorialize"),
    ("type_clause", cl_drop(TREJ, "RX play_sound sound=26"), "no play_sound 26"),
    ("type_clause", cl_replace(TREJ, "area_id=route_29", "area_id=route_30"), "no unresolve_area"),
    ("type_clause", cl_drop(TREJ, "RX_TEXT"), "no [x] Type clause: prompt"),
    ("type_clause", cl_replace(TREJ, '"hp": 0', '"hp": 5'), "did not leave the mon dead"),
    ("type_clause", cl_replace(TREJ, '"in_party": true', '"in_party": false'), "did not leave the mon dead"),
    ("type_clause", cl_replace(TMEM, '"box": 13', '"box": 12'), "into sBox14"),
    ("type_clause", cl_replace(TMEM, '"in_party": false', '"in_party": true'), "into sBox14"),
    ("type_clause", cl_drop(TREJ, "REJECTED_MON"), "missing REJECTED_MON"),
    ("type_clause", cl_move(TREJ, "REJECTED_MON", "MEMORIAL_ACK"), "before the checkpoint replies"),
    ("type_clause", cl_move(TREJ, "SAVE_WITNESS", "REJECTED_MON"), "final save precedes"),
    ("type_clause", TREJ[:-1] + ["RX play_sound sound=22", TREJ[-1]], "also saw its partner's verdict"),
    ("type_clause", cl_move(TREJ, "CLAUSE_VERDICT", "RX force_faint"), "before its wire cause"),
    ("type_clause", cl_move(TREJ, "RX force_faint", "ENGINE_CAPTURE"), "before the capture was sent"),
    ("type_clause", cl_replace(TREJ, '"verdict": "rejected"', '"verdict": "linked"'), "has no wire cause"),
    ("type_clause", clause_lines("type", "partner_rejected") + ["RX force_faint key=" + KEY], "was rejected"),
    ("type_clause", cl_replace(TREJ, '"types": ["Normal", "Flying"]', '"types": ["Normal"]'), "types disagree"),
    ("type_clause", cl_replace(TREJ, '"gender": "female"', '"gender": "male"'), "gender disagrees"),
    ("type_clause", clause_lines("type", "linked", species=163, key=KEY[:-2] + "A3"), "Hoothoot shares a type"),
    ("gender_clause", cl_replace(GREJ, "both are ♀", "both are ♂"), "names the other gender"),
    ("gender_clause", cl_drop(clause_lines("gender", "linked"), "RX_TEXT"), "has no wire cause"),
], ids=lambda v: v if isinstance(v, str) and len(v) < 40 else None)
def test_clause_verdict_refuses_a_tampered_ending(name, lines, match):
    problems, receipt = clause_verdict(name, lines)
    assert receipt is None and any(match in p for p in problems), problems


def species_lines(player, encounters=((16, True), (19, False))):
    j = json.dumps
    if player == "a":
        base = [x.replace('"scenario": "link"', '"scenario": "species_clause"') for x in happy_lines()[:8]]
        return base + ["PENDING_CAPTURE " + j({"frame": 1600, "key": KEY, "species_id": 16, "area_id": "route_29"}),
                       "RX msgbox", "RX_TEXT " + j({"frame": 5000, "cmd": "msgbox", "text": LINKED_TEXT}),
                       "LINKED " + j({"frame": 5001, "text": LINKED_TEXT}), happy_lines()[8]]
    last_species = encounters[-1][0]
    key = KEY[:-2] + f"{last_species:02X}"
    head = [x.replace('"player": "a", "scenario": "link"', '"player": "b", "scenario": "species_clause"')
            for x in happy_lines()[:5]]
    out = head + ["A_PENDING " + j({"frame": 400, "species_id": 16})]
    for n, (species, dupe) in enumerate(encounters, 1):
        out.append("ENCOUNTER " + j({"frame": 500 * n, "n": n, "species_id": species, "dupe": dupe}))
        if dupe:
            prompt = "Dupes clause: Pidgey -- reroll!"
            out += ["RX gui_prompt", "RX_TEXT " + j({"frame": 500 * n + 1, "cmd": "gui_prompt", "text": prompt}),
                    "RX unresolve_area area_id=route_29",
                    "REROLL " + j({"frame": 500 * n + 2, "n": n, "species_id": species, "prompt": prompt})]
    catch = [x.replace(KEY, key).replace('"species_id": 16', f'"species_id": {last_species}') for x in happy_lines()[5:8]]
    return out + catch + ["RX msgbox", "RX_TEXT " + j({"frame": 5000, "cmd": "msgbox", "text": LINKED_TEXT}),
                          "LINKED " + j({"frame": 5001, "text": LINKED_TEXT}), happy_lines()[8]]


def test_species_verdict_passes_each_complete_half():
    for player, encounters, path in (("a", None, "pending"), ("b", ((16, True), (19, False)), "reroll_observed"),
                                     ("b", ((161, False),), "reroll_unobserved"),
                                     ("b", ((16, True), (16, True), (187, False)), "reroll_observed")):
        lines = species_lines(player) if encounters is None else species_lines(player, encounters)
        problems, receipt = clause_verdict("species_clause", lines)
        assert problems == [] and receipt["path"] == path, (player, encounters, problems)


def test_species_verdict_accepts_the_prompt_during_the_battle_intro():
    """C<->C species RED run 2 (physical order): the server rerolls on the first in_battle tick
    (state.py:1843-1930), so the prompt's RX lands during the intro text, before ENCOUNTER (printed at the
    BattleMenu). The window is the previous REROLL (or A_PENDING) .. this REROLL, the hunt's own cursor."""
    lines = species_lines("b", ((16, True), (16, True), (19, False)))
    for n in (1, 2):
        enc = next(i for i, x in enumerate(lines) if x.startswith("ENCOUNTER ") and f'"n": {n},' in x)
        rx = next(i for i, x in enumerate(lines) if i > enc and x.startswith("RX gui_prompt"))
        lines[enc:rx + 2] = lines[rx:rx + 2] + lines[enc:rx]
    problems, receipt = clause_verdict("species_clause", lines)
    assert problems == [] and receipt["rerolls"] == 2, problems
    # the second reroll's prompt is gone: the first battle's prompt cannot stand in for it
    second = [i for i, x in enumerate(lines) if x.startswith("RX_TEXT") and "reroll" in x][1]
    problems, receipt = clause_verdict("species_clause", lines[:second] + lines[second + 1:])
    assert receipt is None and any("behind REROLL 2" in p for p in problems), problems


SB = species_lines("b")


@pytest.mark.parametrize("lines,match", [
    (cl_drop(SB, "RX_TEXT {\"frame\": 501"), "no RX dupes-clause prompt behind REROLL 1"),
    (cl_drop(SB, "REROLL"), "no REROLL after duplicate encounter 1"),
    (species_lines("b", ((16, True), (16, False))), "the caught encounter is A's species"),
    (species_lines("b", ((19, False), (16, False))), "a non-duplicate encounter was not caught"),
    (cl_replace(SB, '"n": 2', '"n": 3'), "ENCOUNTER out of order"),
    (cl_replace(SB, '-- reroll!"}', '-- reroll?"}'), "REROLL names another prompt"),
    ([x.replace("Pidgey -- reroll!", "Rattata -- reroll!") if x.startswith("RX_TEXT") else x for x in SB],
     "no RX dupes-clause prompt behind REROLL 1"),
    (cl_drop(SB, "A_PENDING"), "missing A_PENDING"),
    (SB[:-1] + ["RX_TEXT " + json.dumps({"frame": 6000, "cmd": "msgbox", "text": "Route 29 is a dead zone!"}), SB[-1]],
     "dead zone"),
    (SB[:-1] + ["RX_TEXT " + json.dumps({"frame": 6000, "cmd": "gui_prompt", "text": "[x] Dup Pidgey"}), SB[-1]],
     "species-clause rejection prompt"),
    (SB[:-1] + ["RX force_faint key=" + KEY[:-2] + "13", SB[-1]], "force-fainted"),
    (cl_drop(SB, "LINKED"), "missing LINKED"),
    (cl_move(SB, "SAVE_WITNESS", "LINKED"), "final save precedes the link"),
    (species_lines("a") + ["ENCOUNTER " + json.dumps({"frame": 1, "n": 1, "species_id": 16, "dupe": True})],
     "the pending half printed ENCOUNTER"),
    (cl_replace(species_lines("a"), '"species_id": 16, "area_id"', '"species_id": 19, "area_id"'),
     "PENDING_CAPTURE names another catch"),
], ids=["no-prompt", "no-reroll", "caught-dupe", "ran-clean", "enc-order", "wrong-prompt", "rx-other-species", "no-a-pending",
        "dead-zone", "dup-prompt", "force-faint", "no-link", "save-first", "a-encounter", "a-pending-other"])
def test_species_verdict_refuses_a_tampered_half(lines, match):
    problems, receipt = clause_verdict("species_clause", lines)
    assert receipt is None and any(match in p for p in problems), problems


# --- the Route 29 facts against the decomps and the server adapter ---

def clause_facts():
    lua = LuaRuntime(unpack_returned_tuples=True)
    K = lua.execute(f'return dofile("{CLAUSE.as_posix()}")')
    return lua, K


def test_clause_species_facts_match_the_server_adapter():
    from server.adapters.gen2_gsc import Gen2GSCAdapter
    adapter, (_, K) = Gen2GSCAdapter("crystal"), clause_facts()
    for species, mon in K.SPECIES.items():
        types = [adapter.type_name(t) for t in dict.fromkeys(adapter.species_types(species))]
        assert (mon.name, list(mon.types.values())) == (adapter.species_name(species), types)
        assert adapter.evo_family(species) == species and adapter._species[species]["gender_ratio"] == K.GENDER_RATIO


def test_clause_gender_matches_the_server_rule_for_every_attack_and_speed_dv():
    from server.adapters.gen2_gsc import Gen2GSCAdapter
    adapter, (_, K) = Gen2GSCAdapter("crystal"), clause_facts()
    for attack in range(16):
        for speed in range(16):
            key = f"{attack:X}{(attack * 7) % 16:X}{speed:X}{(speed * 5) % 16:X}:B542:10"
            assert K.gender(key) == adapter.gender_from_key(key, 16), key
            assert K.gender(key) == ("female" if attack <= 7 else "male")


@pytest.mark.skipif(not DECOMPS.exists(), reason="pinned decomps not built (.cache/gen2-build)")
@pytest.mark.parametrize("repo,start", [("pokecrystal", 1237), ("pokegold", 1573)])
def test_clause_route29_species_are_exactly_the_decomp_grass_table(repo, start):
    _, K = clause_facts()
    lines = (DECOMPS / repo / "data/wild/johto_grass.asm").read_text(encoding="utf-8").splitlines()
    assert lines[start - 1].strip() == "def_grass_wildmons ROUTE_29"
    block = lines[start:lines.index("\tend_grass_wildmons", start)]
    names = {line.split(",")[1].strip() for line in block if line.strip().startswith("db ") and "percent" not in line}
    ours = {mon.name.upper() for mon in K.SPECIES.values()}
    assert names <= ours and (names == ours if repo == "pokecrystal" else ours - names == {"HOPPIP"})


# ── P4.3e: the native trade driver (lua/tests/duo/gen2_trade.lua + scenario_gen2_trade_*.lua), MODEL only ──────
# The composition override against the real entry.lua/run.lua and the published overlay bytes; the saved-image
# reader against the committed fixture and the codec; each case's verdict over a marker stream shaped exactly as
# the hooks print it (one PASS per case/side, and red controls for the orderings and evidence the oracle needs).
from tests.unit.test_gen2_entry import World  # noqa: E402

TRADE_LUA = ROOT / "lua/tests/duo/gen2_trade.lua"
TRADE_CASES = ("new", "evolve", "decline_new", "timeout", "reset_wait", "reset_commit", "refuse_item")
HAUNTER, GENGAR, FLOWER_MAIL = 0x5D, 0x5E, 0x9E   # pokegold constants/pokemon_constants.asm, item_constants.asm
TRADE_FILES = ("lua/tests/duo/gen2_trade.lua",) + tuple(f"lua/tests/duo/scenario_gen2_trade_{c}.lua" for c in TRADE_CASES)
TOKEN = [0x11, 0x22, 0x33, 0x44]
STACK = (0xDF03, 0xDFFF)   # gold/silver wStackBottom..wStackTop (data/gen2/gold_slink.sym)


def trade_lua():
    lua = LuaRuntime(unpack_returned_tuples=True)
    T = lua.eval("dofile")(TRADE_LUA.as_posix())
    J = lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix())
    return lua, T, J


def test_trade_driver_files_compile_under_lua54():
    lua = LuaRuntime(unpack_returned_tuples=True)
    check = lua.eval("function(s, n) local f, e = load(s, n) return e end")
    for path in TRADE_FILES + (MAIN,):
        assert check((ROOT / path).read_text(encoding="utf-8"), "@" + path) is None, path


def test_apply_wait_bound_is_the_overlay_source_equ():
    import re
    lua, T, _ = trade_lua()
    source = (ROOT / "patch/gen2/src/trade_service.asm").read_text(encoding="utf-8")
    assert int(re.search(r"DEF SLINK_TRADE_APPLY_FRAMES EQU (\d+)", source)[1]) == T.APPLY_WAIT


def test_trade_scenarios_name_their_case_and_share_one_harness():
    lua = LuaRuntime(unpack_returned_tuples=True)
    for case in TRADE_CASES:
        S = lua.eval("dofile")((ROOT / f"lua/tests/duo/scenario_gen2_trade_{case}.lua").as_posix())
        assert S.TRADE is True and S.CASE == case and S.RECEIPT_SCHEMA == "gen2-duo-trade-v1" and S.T.SCOPE == "HARNESS_ONLY_OVERLAY"


# ── the HARNESS_ONLY_OVERLAY composition override ──
def overlay_image(title):
    from patch.tools.make_ups import ups_apply
    prov = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_text())["outputs"]["poke" + title]
    source = "pokecrystal" if title == "crystal" else "pokegold"
    clean = (ROOT / f".cache/gen2-build/{source}/{prov['filename']}").read_bytes()
    return clean, ups_apply(clean, (ROOT / prov["ups"]["file"]).read_bytes())


def test_override_patches_each_entry_fragment_exactly_once_and_pins_the_published_overlays():
    lua, T, _ = trade_lua()
    text = (ROOT / "lua/gen2/entry.lua").read_text(encoding="utf-8")
    patched = T.patch_entry(text)
    assert isinstance(patched, str) and patched.startswith(T.PREFIX)
    for p in T.PATCHES.values():
        assert text.count(p["from"]) == 1 and patched.count(p["to"]) == 1 and p["from"] not in patched
    assert patched.count("\n") == text.count("\n")   # the prefix shares line 1: tracebacks keep their line numbers
    prov = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_text())["outputs"]
    pins = T.load_pins(ROOT.as_posix(), lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix()))
    assert dict(pins.items()) == {prov[a]["slink_title"]: prov[a]["sha1"] for a in ("pokecrystal", "pokegold", "pokesilver")}
    # the mail ids the verdict treats as plant-only are exactly every pack's mail_ids
    for title in ("crystal", "gold", "silver"):
        mail = json.loads((ROOT / f"data/games/gen2_{title}/items.json").read_text())["mail_ids"]
        assert sorted(k for k, _ in T.MAIL.items()) == sorted(mail)
    # red: a fragment that moved (production edited) refuses, never patches blindly
    broken, why = T.patch_entry(text.replace('candidate.row.kind == "clean"', 'candidate.row.kind=="clean"'))
    assert broken is None and "kind" in why
    doubled, why = T.patch_entry(text + "\n-- " + T.PATCHES[5]["from"])
    assert doubled is None and "twice" in why


class OverlayWorld(World):
    """World (test_gen2_entry.py) over the published overlay bytes, composing through the patched entry."""

    def __init__(self, title, image=None, patched=True):
        super().__init__(title)
        clean, overlay = overlay_image(title)
        self.image = overlay if image is None else image(clean, overlay)
        lua = self.lua
        T = lua.eval("dofile")(TRADE_LUA.as_posix())
        T.load_pins(ROOT.as_posix(), lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix()))
        self.T = T
        if patched:
            text = (ROOT / "lua/gen2/entry.lua").read_text(encoding="utf-8")
            chunk = lua.eval("function(t, n) return assert(load(t, n, 't', _G)) end")(T.patch_entry(text), "@entry")
            self.entry = chunk(T.harness())


@pytest.mark.parametrize("title", ["gold", "crystal"])
def test_patched_entry_admits_only_the_pinned_overlay_as_kind_overlay(title):
    world = OverlayWorld(title)
    decision = world.entry.admit(world.args())
    assert not isinstance(decision, tuple), decision
    assert (decision.title, decision.kind, decision.rom_sha1) == (title, "overlay", world.T.OVERLAY_SHA1[title])
    # red: the unpatched production entry refuses the same bytes: its catalog row is FUTURE (production unchanged)
    plain = OverlayWorld(title, patched=False)
    decision, reason = plain.entry.admit(plain.args())
    assert decision is None and "selection FUTURE is not admitted" in reason
    # red: the clean cartridge is not admitted by the harness catalog, and one flipped overlay byte is refused
    clean = OverlayWorld(title, image=lambda c, o: c)
    decision, reason = clean.entry.admit(clean.args())
    assert decision is None and "unknown artifact SHA-1" in reason
    tampered = OverlayWorld(title, image=lambda c, o: o[:-1] + bytes([o[-1] ^ 1]))
    decision, reason = tampered.entry.admit(tampered.args())
    assert decision is None and "unknown artifact SHA-1" in reason


def test_patched_production_graph_is_disclosed_overlay_kind_with_the_overlay_sha1():
    world = OverlayWorld("gold")
    lua = world.lua
    io = lua.eval("""function(base, frame)
        base.framecount = function() return frame end
        base.register = function() return 0 end
        base.on_bus_exec = function() return "h" end
        base.unregister = function() end
        return base end""")(world.io, 1)
    args = world.args()
    args.io = io
    args.net = lua.eval("{init=function() end, send=function() return true end, connected=function() return true end, pump=function() end}")
    args.hud = lua.eval("{show=function() end, render=function() end, sanitize=function(s) return s end}")
    args.player = "a"
    args.log = lua.eval("function() end")
    parts = world.entry.build(args)
    assert not isinstance(parts, tuple), parts
    client = parts.client
    assert parts.production_admitted is True and parts.qualification == "HARNESS_ONLY_OVERLAY"
    assert client.artifact_kind == "overlay" and client.rom_sha1 == world.T.OVERLAY_SHA1["gold"]
    assert client.trade is not None and parts.profile.rom_sha1 == world.profile["rom_sha1"]


# ── the saved-image reads the baseline prints, against the codec the oracle decodes with ──
@pytest.mark.parametrize("title,fixture", [("gold", "gold_battle_errand"), ("crystal", "crystal_battle")])
def test_saved_party_and_dex_equal_the_codec_decode(title, fixture):
    from server.adapters import gen2_codec as codec
    lua, T, _ = trade_lua()
    raw = (ROOT / f"tests/fixtures/gen2/{fixture}.SaveRAM").read_bytes()
    profile = lua.table_from(json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title],
                             recursive=True)
    layout = codec.for_foundation(title, root=ROOT)
    for copy in ("primary", "backup"):
        want = [{"species_marker": m["species_marker"], "blob_hex": codec.encode_party_blob(m, layout).hex()}
                for m in codec.decode_saved_party(raw[:0x8000], layout, copy_name=copy)["mons"]]
        got = T.saved_party(raw, profile, title, copy)
        assert [dict(r.items()) for r in got.values()] == want
    dex = T.saved_dex(raw, profile, title)
    for copy in ("primary", "backup"):
        for kind, sym in (("caught_hex", "wPokedexCaught"), ("seen_hex", "wPokedexSeen")):
            assert dex[copy][kind] == saved_bytes(raw, layout, sym, 32, copy).hex()


REGION_START = {"player": "wPlayerData", "player1": "wPlayerData1", "player2": "wPlayerData2",
                "player3": "wPlayerData3", "map": "wCurMapData", "pokemon": "wPokemonData"}


def saved_bytes(raw, layout, symbol, count, copy):
    """tools/gen2_trade_oracles._saved: the symbol inside its save region, primary or backup copy."""
    address = layout.addresses[symbol]
    for region in layout.regions:
        base = layout.addresses[REGION_START[region.name]]
        if base <= address and address + count <= base + region.length:
            offset = getattr(region, copy) + address - base
            return raw[offset:offset + count]
    raise AssertionError(symbol)


# ── the pure drivers ──
def test_travel_driver_answers_the_phone_runs_from_battles_and_faces_the_desk():
    lua, T, _ = trade_lua()
    PI = lua.eval("dofile")((ROOT / "lua/tests/gen2_poison_inputs.lua").as_posix())
    grid = [1] * (16 * 8)
    maps = lua.table_from({"Pokecenter2F": {"map_group": 20, "map_number": 1, "width": 16, "height": 8,
                                            "grid": lua.table_from(grid), "warps": lua.table()}}, recursive=True)
    legs = lua.table_from({"Pokecenter2F": {"kind": "stand"}}, recursive=True)
    drv = T.travel_driver(PI, maps, legs, lua.table_from({"x": 5, "y": 3}))
    steps = lua.table_from({"Up": True, "Down": True, "Left": True, "Right": True})

    def point(**kw):
        base = {"map_group": 20, "map_number": 1, "x": 5, "y": 5, "overworld_ready": True, "battle_mode": 0,
                "can_step": steps, "facing": "Down"}
        base.update(kw)
        return lua.table_from(base, recursive=True)
    buttons, phase = drv.step(point())
    assert dict(buttons.items()) == {"Up": True}
    buttons, _ = drv.step(point(overworld_ready=False, ui={"kind": "wait_button"}, input_ready=True))   # the phone
    assert dict(buttons.items()) == {"A": True}
    for _ in range(12):
        drv.step(point())
    buttons, _ = drv.step(point(x=5, y=3, facing="Left"))
    assert dict(buttons.items()) == {"Up": True}
    for _ in range(12):
        drv.step(point(x=5, y=3, facing="Left"))
    buttons, phase = drv.step(point(x=5, y=3, facing="Up"))
    assert phase == "at-desk" and dict(buttons.items()) == {}
    # red: a trainer battle or an unmapped yes/no on the way is refused, never guessed through
    drv2 = T.travel_driver(PI, maps, legs, lua.table_from({"x": 5, "y": 3}))
    buttons, why = drv2.step(point(ui={"kind": "yes_no", "prompt": "save_confirm"}, input_ready=True))
    assert buttons is None and "not valid while walking" in why


def visit(T, lua, **opts):
    table = {"role": "proposer", "slot": 1, "stand": {"x": 5, "y": 3}}
    table.update(opts)
    return T.visit_driver(lua.table_from(table, recursive=True))


def vpoint(lua, trade=None, **kw):
    base = {"x": 5, "y": 3, "facing": "Up", "overworld_ready": False, "battle_mode": 0,
            "trade": trade or {"entered": False, "exited": False, "waiting": False, "committing": False}}
    base.update(kw)
    return lua.table_from(base, recursive=True)


def drain(drv, point, frame):
    for i in range(1, 13):
        drv.step(point, frame + i)


def test_visit_driver_proposer_talks_selects_the_linked_slot_and_confirms():
    lua, T, _ = trade_lua()
    drv = visit(T, lua)
    b, _ = drv.step(vpoint(lua, overworld_ready=True), 100)
    assert dict(b.items()) == {"A": True}   # talk
    drain(drv, vpoint(lua, overworld_ready=True), 100)
    b, _ = drv.step(vpoint(lua, overworld_ready=True), 150)
    assert dict(b.items()) == {}             # no re-talk inside TALK_RETRY
    yes_no = lambda prompt, cursor: {"kind": "yes_no", "prompt": prompt, "items": ["YES", "NO"], "cursor": cursor, "columns": 1}
    for n, prompt in enumerate(("trade_intro", "must_save", "save_overwrite")):   # 9805ac1c: the forced save
        b, _ = drv.step(vpoint(lua, ui=yes_no(prompt, 1), input_ready=True), 200 + 20 * n)
        assert dict(b.items()) == {"A": True}, prompt
        drain(drv, vpoint(lua), 200 + 20 * n)
    b, _ = drv.step(vpoint(lua, ui={"kind": "prompt_button", "prompt": "save_overwrite_text"}, input_ready=True), 270)
    assert dict(b.items()) == {"A": True}
    drain(drv, vpoint(lua), 270)
    b, _ = drv.step(vpoint(lua, ui={"kind": "trade_party"}, input_ready=True, party_cursor=0), 300)
    assert dict(b.items()) == {"Down": True}
    drain(drv, vpoint(lua), 300)
    b, _ = drv.step(vpoint(lua, ui={"kind": "trade_party"}, input_ready=True, party_cursor=1), 400)
    assert dict(b.items()) == {"A": True}
    drain(drv, vpoint(lua), 400)
    b, _ = drv.step(vpoint(lua, ui=yes_no("slink_trade", 1), input_ready=True), 500)
    assert dict(b.items()) == {"A": True}
    drain(drv, vpoint(lua), 500)
    done = {"entered": True, "exited": True, "waiting": False, "committing": False}
    b, phase = drv.step(vpoint(lua, trade=done, overworld_ready=True), 600)
    assert phase == "visited"


def test_visit_driver_responder_holds_the_prompt_until_told_and_never_presses_b():
    lua, T, _ = trade_lua()
    gate = {"open": False}
    answers = []
    drv = visit(T, lua, role="responder", answer=lambda p: "NO" if gate["open"] else None,
                on_answer=lambda a: answers.append(a))
    prompt = {"kind": "yes_no", "prompt": "trade_offer", "items": ["YES", "NO"], "cursor": 1, "columns": 1}
    for f in range(10):
        b, phase = drv.step(vpoint(lua, ui=prompt, input_ready=True), f)
        assert dict(b.items()) == {} and phase == "hold"
    gate["open"] = True
    b, _ = drv.step(vpoint(lua, ui=prompt, input_ready=True), 20)
    assert dict(b.items()) == {"Down": True} and answers == ["NO"]
    # the accepting responder then makes the native forced save; a declining one never sees it
    yes = visit(T, lua, role="responder", answer=lambda p: "YES")
    ask = lambda prompt: vpoint(lua, ui={"kind": "yes_no", "prompt": prompt, "items": ["YES", "NO"], "cursor": 1,
                                         "columns": 1}, input_ready=True)
    for n, name in enumerate(("trade_offer", "trade_save", "save_overwrite")):
        b, _ = yes.step(ask(name), 100 + 20 * n)
        assert dict(b.items()) == {"A": True}, name
        drain(yes, vpoint(lua), 100 + 20 * n)
    drain(drv, vpoint(lua), 20)
    b, why = drv.step(ask("trade_save"), 300)
    assert b is None and "unmapped" in why          # the NO responder never reaches the save prompt
    b, why = visit(T, lua, role="responder", answer=lambda p: "YES").step(ask("slink_trade"), 1)
    assert b is None and "unmapped" in why          # the proposer-only confirm is refused on the responder
    # red: the responder never meets the party menu
    b, why = visit(T, lua, role="responder", answer=lambda p: "YES").step(
        vpoint(lua, ui={"kind": "trade_party"}, input_ready=True, party_cursor=0), 1)
    assert b is None and "responder" in why


def test_visit_driver_cancel_is_one_b_inside_the_held_wait_and_the_chord_is_four_frames():
    lua, T, _ = trade_lua()
    waiting = {"entered": True, "exited": False, "waiting": True, "committing": False, "wait_apply_frame": 10}
    drv = visit(T, lua, cancel=lambda p: True)
    b, _ = drv.step(vpoint(lua, trade=waiting), 50)
    assert dict(b.items()) == {"B": True}
    drain(drv, vpoint(lua, trade=waiting), 50)
    b, _ = drv.step(vpoint(lua, trade=waiting), 70)
    assert dict(b.items()) == {}             # one cancel only
    drv = visit(T, lua, chord=lambda p: True)
    frames = [dict(drv.step(vpoint(lua, trade=waiting), f)[0].items()) for f in range(4)]
    assert frames == [{"A": True, "B": True, "Select": True, "Start": True}] * 4
    assert drv.step(vpoint(lua, trade=waiting), 5)[1] == "visited"


# ── the verdict over each case's marker stream ──
def lease(cmd, gen, ack, result, slot, token=TOKEN):
    return (b"SLT1" + bytes([1, cmd, gen % 256, ack % 256, result, slot, 1, 0]) + bytes(token)).hex()


def blob(species, item=0):
    struct = bytes([species, item]) + bytes(46)
    return (struct + b"\x80" + bytes(10) + b"\x81" + bytes(10)).hex()


def site(name, bank=19, address=0x4000):
    return {"symbol": name, "bank": bank, "address": address}


def image(frame, name, kind=None):
    row = {"frame": frame, "snapshot_path": f"C:/b/{name}.SaveRAM", "snapshot_sha256": hashlib.sha256(name.encode()).hexdigest(),
           "cartram_sha256": hashlib.sha256((name + "c").encode()).hexdigest(), "snapshot_bytes": 0x8000 + 22,
           "cartram_bytes": 0x8000}
    if kind:
        row["kind"] = kind
    return row


def regs(**kw):
    out = {r: 0 for r in ("A", "F", "B", "C", "D", "E", "H", "L", "SP", "PC")}
    out.update(kw)
    return out


def stack_row(visited, native_end="SlinkTradePublishDone"):
    phases = []
    for i, name in enumerate(("wait", "trade_animation", "evolution_animation", "native_save")):
        if name in visited:
            lo, hi = visited[name]
            phases.append({"phase": name, "visited": True, "start": {"frame": lo, "site": site("S" + name)},
                           "end": {"frame": hi, "site": site(native_end if name == "native_save" else "E" + name)},
                           "samples": [{"frame": lo + 1, "stack_addr": 0xDFDE, "sp": 0xDFE0, "pc": 0x4100, "rom_bank": 19},
                                       {"frame": hi, "stack_addr": 0xDFC0, "sp": 0xDFC1, "pc": 0x0100, "rom_bank": 3}]})
        else:
            phases.append({"phase": name, "visited": False, "start": None, "end": None, "samples": []})
    events = [{"action": "arm", "address": a, "frame": 1100, "hook_id": f"w{a}"} for a in range(STACK[0], STACK[1] + 1)]
    low = {"frame": 1300, "stack_addr": 0xDFC0, "sp": 0xDFC1, "pc": 0x0100, "rom_bank": 3}
    return {"domain": "System Bus", "stack_bank": 1, "stack_start": STACK[0], "stack_end": STACK[1],
            "armed_count": STACK[1] - STACK[0] + 1, "hook_failures": 0, "phases": phases,
            "registration_events": events, "continuous": True, "registration_complete_before_first_phase": True,
            "coverage_started": {"frame": 1100, "site": "harness:trade_go"},
            "coverage_ended": {"frame": 9000, "site": "harness:before_report"},
            "global_low_water": low, "global_observations": 40, "global_minima": [low]}


def reload_leg(j, final_frame):
    final = image(final_frame, "final", "flush")
    j("RELOAD_CHORD", {"frame": final_frame + 200, "frames": 4})
    j("RELOADED", {"frame": final_frame + 3000, "map_group": 20, "map_number": 1, "x": 5, "y": 3, "party_count": 2})
    dex = {"caught_hex": "00" * 32, "seen_hex": "00" * 32}
    j("TRADE_RELOAD", {"frame": final_frame + 3010, "snapshot_sha256": final["snapshot_sha256"],
                       "cartram_sha256": final["cartram_sha256"], "party_keys": ["0000:0001:9B", KEY],
                       "dex": {"primary": dex, "backup": dex}})


def trade_stream(case, player, item=0):
    """The marker lines one side prints for `case`, shaped exactly as gen2_trade.lua's hooks print them."""
    own = HAUNTER if (case == "evolve" and player == "a") else (19 if player == "b" else 16)
    held = FLOWER_MAIL if (case == "refuse_item" and player == "a") else item
    party = [{"species_marker": 155, "blob_hex": blob(155)}, {"species_marker": own, "blob_hex": blob(own, held)}]
    partner_species = HAUNTER if (case == "evolve" and player == "b") else (16 if player == "b" else 19)
    partner = {"species_marker": partner_species, "blob_hex": blob(partner_species)}
    out = []

    def j(tag, value):
        out.append(tag + " " + json.dumps(value))
    j("DUO_GEN2", {"player": player, "scenario": "gen2_trade_" + case, "attempt": 1, "case": "gold_battle_errand",
                   "title": "gold", "rom_sha1": "d8b8a3600a465308c9953dfa04f0081c05bdcb94", "fixture_sha256": "f" * 64})
    j("CLIENT", {"qualification": "HARNESS_ONLY_OVERLAY", "production_admitted": True, "pack": "gen2_gold", "title": "gold",
                 "rom_sha1": "d8b8a3600a465308c9953dfa04f0081c05bdcb94", "registered_sites": []})
    out.append('TRADE_OVERRIDE {"schema":"gen2-duo-overlay-override-v1"}')
    j("TRADE_ADMISSION", {"admission_scope": "HARNESS_ONLY_OVERLAY", "overlay_sha1": "d563669ec3ac5029be9464d2301aa3be27a5f163",
                          "base_sha1": "d8b8a3600a465308c9953dfa04f0081c05bdcb94", "title": "gold",
                          "override_manifest_sha256": "a" * 64, "trade_manifest_sha256": "b" * 64, "run_id": "g2trade_x"})
    j("BOOTED", {"frame": 10, "map_group": 24, "map_number": 3, "x": 1, "y": 1, "party_count": 1})
    j("HELLO", {"frame": 20, "ot_id": 1})
    if case == "evolve" and player == "a":
        j("HARNESS_WRITE", {"frame": 400, "domain": "WRAM", "bank": 1, "address": 0xD117, "symbol": "wTempWildMonSpecies",
                            "wram_offset": 0x1117, "bytes_before": "10", "bytes_after": "%02x" % HAUNTER,
                            "purpose": "trade_evolve_species", "species": "HAUNTER", "evolves_to": "GENGAR"})
    j("ENGINE_CAPTURE", {"frame": 500, "site_id": "capture_party_finalized", "acquisition": "wild", "key": KEY,
                         "species_id": own})
    out.append("CAUGHT " + KEY)
    if case == "refuse_item" and player == "a":
        j("HARNESS_WRITE", {"frame": 900, "domain": "WRAM", "bank": 1, "address": 0xDA2B + 48, "symbol": "wPartyMon1Item",
                            "wram_offset": 0x1A5B, "bytes_before": "00", "bytes_after": "%02x" % FLOWER_MAIL,
                            "purpose": "d3_mail_item", "slot": 1, "item": "FLOWER_MAIL"})
    base = image(1000, "baseline", "native_save")
    base.update(slot=1, count=2, key=KEY, client_saves=1, party=party, dex={"primary": {"caught_hex": "00" * 32, "seen_hex": "00" * 32},
                                                            "backup": {"caught_hex": "00" * 32, "seen_hex": "00" * 32}})
    j("TRADE_BASELINE", base)
    j("TRADE_READY", {"frame": 1001, "snapshot_sha256": base["snapshot_sha256"], "slot": 1, "key": KEY})
    j("TRADE_GO", {"frame": 1100, "run_id": "g2trade_x"})
    plan = {"a": "proposer", "b": "responder"}[player]
    if case == "refuse_item" and player == "b":
        j("TRADE_FINAL", image(3000, "final", "flush"))
        j("TRADE_STACK", stack_row({}))
        return out
    role, gen = (0, 5) if plan == "proposer" else (1, 9)
    j("TRADE_ENTRY", {"frame": 1200, "role": role, "site": site("SlinkTradeEntry" if role == 0 else "SlinkTradePromptEntry")})
    if role == 0:
        j("TRADE_FORCED_SAVE", {**image(1200, "forced", "forced_native_save"), "capture_frame": 1200, "flush_frame": 1201,
                                "flushed_matches": True, "client_saves": 2, "save_completed_frame": 1150})
    if case == "refuse_item":
        before = {"frame": 1250, "site": site("SlinkTradeItemAllowed"), "registers": regs(A=held), "slot": 1,
                  "lease_hex": lease(1, 3, 3, 0, 0)}
        j("TRADE_EXIT", {"frame": 1260, "lease_hex": lease(0, 3, 3, 0, 0)})
        j("TRADE_CONTROL", {"kind": "d3", "before": before, "after": {"frame": 1260, "site": site("SlinkTradeExit"),
                                                                        "registers": regs(), "lease_hex": lease(0, 3, 3, 0, 0)}})
        j("TRADE_FINAL", image(3000, "final", "flush"))
        j("TRADE_STACK", stack_row({"wait": (1200, 1260)}))
        return out
    offer = {"frame": 1300, "site": site("SlinkTradeWaitAck"), "pc": 0x4343, "rom_bank": 19, "role": role, "slot": 1,
             "count": 2, "token": TOKEN, "generation": gen,
             "lease_hex": lease(2 if role == 0 else 3, gen, gen - 1, 0xFF, 1), **party[1]}
    if role == 1:
        offer.update(incoming_species_marker=partner["species_marker"], incoming_blob_hex=partner["blob_hex"])
    j("TRADE_OFFER", offer)
    answer = {"new": "YES", "evolve": "YES", "reset_commit": "YES"}.get(case, "NO")
    after = {"timeout": "TRADE_EXIT", "reset_wait": "REBOOTED"}.get(case)
    if role == 1:
        j("TRADE_ANSWER", {"frame": 1350, "answer": answer, "after": after})
        if answer == "YES":   # the accepting responder's forced save (Link_SaveGame), captured at PublishDone(0)
            j("TRADE_FORCED_SAVE", {**image(1355, "forced", "forced_native_save"), "capture_frame": 1355,
                                    "flush_frame": 1356, "flushed_matches": True, "client_saves": 2,
                                    "save_completed_frame": 1352})
    committed = case in ("new", "evolve", "reset_commit")
    recovered = case == "reset_commit" and player == "a"
    if role == 0 or committed:
        j("TRADE_WAIT_APPLY", {"frame": 1310 if role == 0 else 1360})
    if committed:
        anim = "TradeAnimation" if role == 0 else "TradeAnimationPlayer2"
        j("TRADE_APPLY_PICKUP", {"frame": 1400, "site": site("SlinkTradeApplyPickup"), "pc": 0x4237, "rom_bank": 19,
                                 "role": role, "slot": 1, "lease_hex": lease(5, gen + 1, gen, 0xFF, 1),
                                 "own_blob_hex": party[1]["blob_hex"], "incoming_species_marker": partner["species_marker"],
                                 "incoming_blob_hex": partner["blob_hex"]})
        j("TRADE_COMMIT_ENTRY", {"frame": 1401, "site": site("SlinkTradeCommit"), "slot": 1, "role": role,
                                 "lease_hex": lease(5, gen + 1, gen + 1, 0xFF, 1)})
        j("TRADE_NATIVE_CALL", {"frame": 1402, **site("RemoveMonFromPartyOrBox", 3, 0x603F)})
        spans = lambda names, slot: {"domain": "System Bus", "bank": 1, "spans": [
            {"symbol": names[0], "address": 0xDA2A + slot * 48, "hex": party[1]["blob_hex"][:96]},
            {"symbol": names[1], "address": 0xDB00 + slot * 11, "hex": party[1]["blob_hex"][96:118]},
            {"symbol": names[2], "address": 0xDB42 + slot * 11, "hex": party[1]["blob_hex"][118:]}]}
        j("TRADE_PRE_REMOVE", {"frame": 1402, "site": site("RemoveMonFromPartyOrBox", 3, 0x603F), "slot": 1,
                               "cur_party_mon": 1, "live": spans(("wPartyMon1", "wPartyMonOTs", "wPartyMonNicknames"), 1),
                               "frozen": spans(("wOTPartyMon1", "wOTPartyMonOTs", "wOTPartyMonNicknames"), 1)})
        j("TRADE_NATIVE_CALL", {"frame": 1410, **site(anim, 10, 0x4DEA)})
    if committed:
        for f, name in ((1900, "AddTempmonToParty"), (1901, "EvolvePokemon"), (1902, "SaveAfterLinkTrade")):
            j("TRADE_NATIVE_CALL", {"frame": f, **site(name, 3, 0x5A9C)})
        received = GENGAR if (case == "evolve" and player == "b") else partner_species
        out.append("TX " + json.dumps({"event": "trade_done", "token": "t1", "slot": 1,
                                       "new_key": "1A2B:B542:%02X" % received, "new_species": received}))
        j("TRADE_SAVE_RETURNED", {"frame": 1950, "site": site("SlinkTradeCommit.cleanup"), "registers": regs()})
        if recovered:
            native = image(1950, "native", "native_trade_save")
            native.update(capture_frame=1950, flush_frame=1951, save_entry_frame=1902, flushed_matches=False, client_saves=2)
            j("TRADE_NATIVE_SAVE", native)
            j("CHORD", {"frame": 1951, "frames": 4})
            j("TRADE_RESET_ENTRY", {"frame": 1953})
            j("RESET_SEEN", {"frame": 1990, "delta": 39})
            j("TRADE_CONTROL", {"kind": "reset_commit",
                                "commit": {"frame": 1401, "site": site("SlinkTradeCommit"), "slot": 1, "role": role,
                                           "lease_hex": lease(5, gen + 1, gen + 1, 0xFF, 1)},
                                "before": {"frame": 1953, "site": site("Reset", 0, 0x5B0), "registers": regs(),
                                           "lease_hex": lease(5, gen + 1, gen + 1, 0xFF, 1)},
                                "after": {"frame": 2600, "site": site("StartTitleScreen", 1, 0x624F), "registers": regs(),
                                          "lease_hex": "00" * 16}})
            j("REBOOTED", {"frame": 5000, "map_group": 20, "map_number": 1, "x": 5, "y": 3, "party_count": 2})
            j("TRADE_RECOVERED", {"frame": 8000, "text": "Traded PIDGEY for SENTRET!"})
            j("TRADE_FINAL", {**image(8100, "final", "flush"), "client_saves": 2})
            j("TRADE_STACK", stack_row({"wait": (1200, 1401), "trade_animation": (1410, 1900), "native_save": (1902, 1953)},
                                       native_end="Reset"))
            reload_leg(j, 8100)
            return out
        j("TRADE_DONE", {"frame": 2000, "lease_hex": lease(7, gen + 1, gen + 1, 0, 1), "result": 0})
        native = image(2000, "native", "native_trade_save")
        native.update(capture_frame=2000, flush_frame=2001, save_entry_frame=1902, flushed_matches=True, client_saves=2)
        j("TRADE_NATIVE_SAVE", native)
        j("TRADE_EXIT", {"frame": 2050, "lease_hex": lease(0, gen + 1, gen + 1, 0, 1)})
        j("TRADE_FINAL", {**image(2200, "final", "flush"), "client_saves": 2})
        phases = {"wait": (1200, 1401), "trade_animation": (1410, 1900), "native_save": (1902, 2000)}
        if case == "evolve" and player == "b":
            phases["evolution_animation"] = (1901, 1902)
        j("TRADE_STACK", stack_row(phases))
        reload_leg(j, 2200)
        return out
    if case == "decline_new" and player == "a":
        j("TRADE_CANCEL", {"frame": 1500, "button": "B"})
    if case == "reset_wait" and player == "a":
        j("CHORD", {"frame": 1600, "frames": 4})
        j("TRADE_RESET_ENTRY", {"frame": 1601})
        j("RESET_SEEN", {"frame": 1640, "delta": 40})
        if case == "reset_wait":
            j("TRADE_CONTROL", {"kind": "reset_wait",
                                "before": {"frame": 1601, "site": site("Reset", 0, 0x5B0), "registers": regs(),
                                           "lease_hex": lease(2, gen, gen, 0, 1)},
                                "after": {"frame": 2400, "site": site("StartTitleScreen", 1, 0x624F), "registers": regs(),
                                          "lease_hex": "00" * 16}})
        j("REBOOTED", {"frame": 3500, "map_group": 20, "map_number": 1, "x": 5, "y": 3, "party_count": 2})
        j("TRADE_FINAL", image(3600, "final", "flush"))
        j("TRADE_STACK", stack_row({"wait": (1200, 1601)}))
        return out
    exit_frame = 1310 + 3600 + 5 if (case == "timeout" and player == "a") else 1700
    j("TRADE_EXIT", {"frame": exit_frame, "lease_hex": lease(0, gen, gen, 1, 1)})
    if case == "timeout" and player == "a":
        j("TRADE_CONTROL", {"kind": "timeout",
                            "before": {"frame": 1311, "site": site("SlinkTradeWaitApply.wait"), "registers": regs(B=0x0E, C=0x10),
                                       "lease_hex": lease(2, gen, gen, 0, 1), "slot": 1},
                            "after": {"frame": exit_frame, "site": site("SlinkTradeExit"), "registers": regs(),
                                      "lease_hex": lease(0, gen, gen, 0, 1)}})
    if case == "decline_new" and player == "b":
        j("TRADE_CONTROL", {"kind": "decline",
                            "before": {"frame": 1355, "site": site("SlinkTradePublishDone"), "registers": regs(A=1),
                                       "lease_hex": lease(3, gen, gen, 0xFF, 1), "slot": 1},
                            "after": {"frame": 1700, "site": site("SlinkTradeExit"), "registers": regs(),
                                      "lease_hex": lease(8, gen, gen, 1, 1)}})
    j("TRADE_FINAL", image(3000, "final", "flush"))
    j("TRADE_STACK", stack_row({"wait": (1200, exit_frame)}))
    return out


def trade_verdict(lines, case, player):
    lua, T, J = trade_lua()
    problems, facts = T.verdict(lua.table_from(lines), J, case, player)
    return list(problems.values()), facts


@pytest.mark.parametrize("case", TRADE_CASES)
@pytest.mark.parametrize("player", ["a", "b"])
def test_trade_verdict_passes_each_case_stream(case, player):
    problems, facts = trade_verdict(trade_stream(case, player), case, player)
    assert problems == []
    assert facts.admission.admission_scope == "HARNESS_ONLY_OVERLAY"


def drop(lines, tag, nth=0):
    idx = [i for i, line in enumerate(lines) if line.startswith(tag + " ")][nth]
    return lines[:idx] + lines[idx + 1:]


def edit(lines, tag, fn, nth=0):
    idx = [i for i, line in enumerate(lines) if line.startswith(tag + " ")][nth]
    value = json.loads(lines[idx][len(tag) + 1:])
    fn(value)
    return lines[:idx] + [tag + " " + json.dumps(value)] + lines[idx + 1:]


def red(lines, case, player, fragment):
    problems, _ = trade_verdict(lines, case, player)
    assert any(fragment in p for p in problems), problems


def test_trade_verdict_red_controls_for_the_committed_side():
    s = trade_stream("new", "a")
    red(drop(s, "TRADE_NATIVE_SAVE"), "new", "a", "missing TRADE_NATIVE_SAVE")
    red(drop(s, "TRADE_NATIVE_CALL", 3), "new", "a", "native call")
    red(edit(s, "TRADE_NATIVE_CALL", lambda v: v.update(symbol="TradeAnimationPlayer2"), 1), "new", "a", "TradeAnimation")
    red(edit(s, "TRADE_DONE", lambda v: v.update(lease_hex=lease(7, 6, 6, 2, 1), result=2)), "new", "a", "DONE")
    red(edit(s, "TRADE_APPLY_PICKUP", lambda v: v.update(lease_hex=lease(5, 6, 5, 0xFF, 1, [9, 9, 9, 9]))), "new", "a",
        "APPLY pickup lease")
    red(edit(s, "TRADE_PRE_REMOVE", lambda v: v["frozen"]["spans"][0].update(hex="00" * 48)), "new", "a", "frozen")
    red(edit(s, "TRADE_NATIVE_SAVE", lambda v: v.update(frame=2001)), "new", "a", "DONE-instant")
    red(edit(s, "TRADE_OFFER", lambda v: v.update(blob_hex=blob(19))), "new", "a", "differs from the baseline")
    # main ruling: TRADE_FINAL is a flush of the native trade save; no ordinary save may run in between
    red(edit(s, "TRADE_FINAL", lambda v: v.update(kind="native_save")), "new", "a", "not a flush of the native")
    red(edit(s, "TRADE_FINAL", lambda v: v.update(client_saves=3)), "new", "a", "ordinary save ran between")
    final_at = [i for i, line in enumerate(s) if line.startswith("TRADE_FINAL ")][0]
    red(s[:final_at] + ['SAVE_WITNESS {"frame": 2100}'] + s[final_at:], "new", "a", "ordinary save ran between")
    red(drop(s, "TRADE_RELOAD"), "new", "a", "missing TRADE_RELOAD")
    red(edit(s, "TRADE_RELOAD", lambda v: v.update(snapshot_sha256="c" * 64)), "new", "a", "read back the TRADE_FINAL")
    red(edit(s, "TRADE_STACK", lambda v: v["phases"][3].update(visited=False, samples=[])), "new", "a", "native_save unvisited")
    red(edit(s, "TRADE_STACK", lambda v: v["phases"][0]["samples"][0].update(stack_addr=STACK[0] + 4, sp=STACK[0] + 5)),
        "new", "a", "margin")
    red(edit(s, "TRADE_STACK", lambda v: v.update(hook_failures=1)), "new", "a", "coverage incomplete")
    red(edit(s, "CLIENT", lambda v: v.update(qualification="PHYSICAL_RECEIPTED")), "new", "a", "HARNESS_ONLY_OVERLAY")
    # ordering: the baseline/ready/go handshake and nothing of the visit before the go
    go = [i for i, line in enumerate(s) if line.startswith("TRADE_GO ")][0]
    swapped = s[:go - 1] + [s[go], s[go - 1]] + s[go + 1:]
    red(swapped, "new", "a", "TRADE_GO before TRADE_READY")
    red(edit(s, "TRADE_GO", lambda v: v.update(run_id="other")), "new", "a", "run_id")
    entry = [i for i, line in enumerate(s) if line.startswith("TRADE_ENTRY ")][0]
    early = s[:go] + [s[entry]] + [line for i, line in enumerate(s[go:], go) if i != entry]
    red(early, "new", "a", "TRADE_ENTRY before TRADE_GO")
    red(s + ['TRADE_HOOK_ERROR {"text": "x"}'], "new", "a", "TRADE_HOOK_ERROR")


def test_trade_verdict_red_controls_for_the_negative_cases():
    # no mislabeled no-op: each negative case needs its trigger proven, and no native commit evidence
    red(drop(trade_stream("decline_new", "b"), "TRADE_CONTROL"), "decline_new", "b", "missing TRADE_CONTROL")
    red(edit(trade_stream("decline_new", "b"), "TRADE_CONTROL", lambda v: v["before"]["registers"].update(A=0)),
        "decline_new", "b", "PublishDone(1)")
    red(edit(trade_stream("timeout", "a"), "TRADE_CONTROL", lambda v: v["after"].update(frame=1500)),
        "timeout", "a", "timeout control")
    red(edit(trade_stream("reset_wait", "a"), "TRADE_CONTROL", lambda v: v["after"].update(lease_hex=lease(2, 5, 5, 0, 1))),
        "reset_wait", "a", "zeroed lease")
    red(edit(trade_stream("refuse_item", "a"), "TRADE_CONTROL", lambda v: v["before"]["registers"].update(A=0x01)),
        "refuse_item", "a", "D3 control")
    red(trade_stream("new", "a"), "decline_new", "a", "unexpected TRADE_APPLY_PICKUP")
    red(edit(trade_stream("timeout", "b"), "TRADE_ANSWER", lambda v: v.update(after=None)), "timeout", "b", "before the partner")
    red(edit(trade_stream("decline_new", "b"), "TRADE_ANSWER", lambda v: v.update(answer="YES")), "decline_new", "b", "answered YES")
    red(drop(trade_stream("decline_new", "a"), "TRADE_CANCEL"), "decline_new", "a", "missing TRADE_CANCEL")
    red(edit(trade_stream("decline_new", "a"), "TRADE_FINAL", lambda v: v.update(kind="native_save")), "decline_new", "a",
        "native save after the baseline")
    red(edit(trade_stream("decline_new", "a"), "TRADE_STACK", lambda v: v["phases"][1].update(
        visited=True, start={"frame": 1300, "site": site("x")}, end={"frame": 1400, "site": site("y")},
        samples=[{"frame": 1301, "stack_addr": 0xDFDE, "sp": 0xDFE0, "pc": 1, "rom_bank": 1}])), "decline_new", "a", "forbids")
    peer = trade_stream("refuse_item", "b")
    red(peer[:-2] + ['TRADE_ENTRY {"frame": 1200, "role": 1, "site": {"symbol": "SlinkTradePromptEntry", "bank": 19, "address": 1}}']
        + peer[-2:], "refuse_item", "b", "unexpected TRADE_ENTRY")
    # the uncertain branch: the commit was entered and the reset landed inside the animation, never a native save
    # reset_commit (main ruling): the reset lands after the native save returned and before DONE; the side is
    # committed by the server's watchdog + party evidence, never by a fabricated DONE
    rc = trade_stream("reset_commit", "a")
    red(drop(rc, "TRADE_RECOVERED"), "reset_commit", "a", "missing TRADE_RECOVERED")
    red(drop(rc, "TRADE_NATIVE_CALL", 4), "reset_commit", "a", "native call")
    red(rc[:-1] + ['TRADE_DONE {"frame": 1952, "lease_hex": "%s", "result": 0}' % lease(7, 6, 6, 0, 1)] + rc[-1:],
        "reset_commit", "a", "unexpected TRADE_DONE")
    red(edit(rc, "TRADE_FINAL", lambda v: v.update(kind="native_save")), "reset_commit", "a", "saved again")
    red(drop(rc, "TRADE_RELOAD"), "reset_commit", "a", "missing TRADE_RELOAD")
    red(edit(rc, "TRADE_NATIVE_SAVE", lambda v: v.update(frame=1990)), "reset_commit", "a", "save-returned")
    red(drop(rc, "TRADE_CONTROL"), "reset_commit", "a", "missing TRADE_CONTROL")
    red(edit(rc, "TRADE_CONTROL", lambda v: v["commit"].update(frame=1300)), "reset_commit", "a", "reset_commit control")


def test_trade_verdict_red_controls_for_continuous_stack_coverage():
    s = trade_stream("new", "a")
    red(edit(s, "TRADE_STACK", lambda v: v.update(continuous=False)), "new", "a", "continuous registration")
    red(edit(s, "TRADE_STACK", lambda v: v["registration_events"].pop()), "new", "a", "continuous registration")
    red(edit(s, "TRADE_STACK", lambda v: v["registration_events"][1].update(address=STACK[0])), "new", "a", "repeated")
    red(edit(s, "TRADE_STACK", lambda v: v["registration_events"][3].update(frame=1250)), "new", "a", "repeated")
    red(edit(s, "TRADE_STACK", lambda v: v.update(global_low_water={"frame": 1, "stack_addr": STACK[0] + 8,
                                                                    "sp": STACK[0] + 9, "pc": 1, "rom_bank": 1})),
        "new", "a", "32-byte margin")
    red(edit(s, "TRADE_STACK", lambda v: v.update(global_observations=0)), "new", "a", "32-byte margin")
    red(edit(s, "TRADE_STACK", lambda v: v["phases"][3]["end"].update(site=site("SlinkTradeWaitRelease"))), "new", "a",
        "successful DONE")


# ── the attachment itself: overlay hooks -> markers -> the same verdict (a simulated bus, no emulator) ──
TRADE_SIM = r"""
local T, SG, json, facts, profile, overlay_rom, dir = ...
local sim = {frame=100, bus={}, cart={}, regs={A=0, F=0, B=0, C=0, D=0, E=0, H=0, L=0, SP=0xDFE0, PC=0x4000},
             exec={}, writes={}, lines={}}
for i = 0, 0xFFFF do sim.bus[i] = 0 end
for i = 0, 0x7FFF do sim.cart[i] = (i * 7) % 251 end
console = {log=function() end}
event = {onmemorywrite=function(fn, addr, name) sim.writes[addr] = fn return "w" .. addr end}
local api = {}
local function wram(a) return a < 0x1000 and 0xC000 + a or 0xD000 + a - 0x1000 end   -- bank 1 only (the sim's WRAMX)
function api.read_u8(a, d)
    if d == "ROM" then return overlay_rom:byte(a + 1) end
    if d == "CartRAM" then return sim.cart[a] end
    if d == "WRAM" then return sim.bus[wram(a)] end
    return sim.bus[a]
end
function api.write_u8(a, v, d) assert(d == "WRAM", "harness writes are WRAM-domain only") sim.bus[wram(a)] = v end
function api.read_range(a, n, d) local out = {} for i = 1, n do out[i] = api.read_u8(a + i - 1, d) end return out end
function api.register(r) return sim.regs[r] end
function api.on_bus_exec(fn, addr, name) sim.exec[name:gsub("^SLink%-duo%-trade%-", "")] = fn return name end
function api.unregister(h) for a, _ in pairs(sim.writes) do if "w" .. a == h then sim.writes[a] = nil end end end
function api.framecount() return sim.frame end
function api.advance() sim.frame = sim.frame + 1 end
function api.domain_size(d) return d == "CartRAM" and 0x8000 or 0x10000 end
function api.saveram()
    local chars = {}
    for i = 0, 0x7FFF do chars[#chars + 1] = string.char(sim.cart[i]) end
    local f = assert(io.open(dir .. "/sim.SaveRAM", "wb"))
    f:write(table.concat(chars) .. string.rep("\0", 22))
    f:close()
end
local ctx = {api=api, trade_facts=facts, profile=profile, env={title="gold", dir=dir, saveram="sim.SaveRAM"},
             facts={maps={Route29={map_group=24, map_number=3}}}}
local function jlog(tag, v) sim.lines[#sim.lines + 1] = tag .. " " .. assert(json.encode(v)) end
local function log(s) sim.lines[#sim.lines + 1] = s end
local h = {root=".", rec={client_saves=1}, slot_of=function() return 1 end, lines=sim.lines}
local e = {h=h, ctx=ctx, SG=SG, F={}, api=api, D={player="a", result=dir .. "/sim_result.txt", trade_evidence_dir=dir,
                                              scenario="gen2_trade_new", trade_case="gen2_trade_new"}, host={}, case="new",
           gen2={handle_command=function() end}, parts={qualification="HARNESS_ONLY_OVERLAY"}, log=log, jlog=jlog, json=json}
T.running = {title="gold", overlay_sha1=facts.overlay_sha1, base_sha1=profile.rom_sha1}
T.manifest_text, T.manifest_sha256 = '{"schema":"gen2-duo-overlay-override-v1"}', string.rep("a", 64)
function sim.attach(player) e.D.player = player return T.attach(e) end
function sim.put(addr, bytes) for i, b in ipairs(bytes) do sim.bus[addr + i - 1] = b end end
function sim.fire(name)
    local s = facts.code[name]
    sim.bus[profile.hram.hROMBank] = s.bank
    sim.regs.PC = s.addr
    sim.exec[name]()
end
function sim.push(n)   -- n pushes below the current SP: the witness sees writes at SP-2..SP+1
    for i = 0, n - 1 do
        local a = sim.regs.SP - 2 - i
        sim.regs.SP = sim.regs.SP - 1
        if sim.writes[a] then sim.writes[a]() end
    end
    sim.regs.SP = sim.regs.SP + n
end
function sim.step() api.advance() end
function sim.final(trade, kind)
    trade.image("TRADE_FINAL", "trade_final", trade.flush(), {kind=kind, client_saves=sim.h.rec.client_saves})
end
sim.jlog, sim.h = jlog, h
return sim
"""


class TradeSim:
    def __init__(self, tmp_path, player, monkeypatch):
        from tools.gen2_trade_facts import trade_facts
        self.lua, self.T, self.J = trade_lua()
        self.facts = trade_facts("gold")
        self.profile = json.loads((ROOT / "data/games/gen2_gold/profile.json").read_text())["titles"]["gold"]
        _, overlay = overlay_image("gold")
        self.lua.execute("SLINK_GEN2_GATE_LIBRARY = true")
        SG = self.lua.eval("dofile")((ROOT / "lua/tests/test_gen2_scripted_gate.lua").as_posix())
        manifest = {"schema": "gen2-trade-lane-v1", "run_id": "g2trade_sim", "evidence_class": "HARNESS_ONLY_OVERLAY",
                    "players": {p: {"title": "gold", "artifact_kind": "overlay", "rom_sha1": self.facts["overlay_sha1"]}
                                for p in ("a", "b")}}
        path = tmp_path / "manifest.json"
        raw = json.dumps(manifest).encode()
        path.write_bytes(raw)
        monkeypatch.setenv("SLINK_GEN2_TRADE_MANIFEST", str(path))
        monkeypatch.setenv("SLINK_GEN2_TRADE_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
        self.sim = self.lua.execute(TRADE_SIM, self.T, SG, self.J, self.lua.table_from(self.facts, recursive=True),
                                    self.lua.table_from(self.profile, recursive=True), overlay, tmp_path.as_posix())
        head = trade_stream("new", player)[:9]   # DUO_GEN2 .. CAUGHT: the link half, unchanged by the trade
        for line in head:
            if not line.startswith("TRADE_"):
                self.sim.lines[len(self.sim.lines) + 1] = line
        self.trade = self.sim.attach(player)
        self.ram = {k: v["addr"] for k, v in self.facts["ram"].items()}

    def mon(self, species, item=0):
        return list(bytes.fromhex(blob(species, item)))

    def party(self, own):
        """Live party [starter, own] and the same party in both saved copies (the native save the baseline flushes)."""
        r, sim = self.ram, self.sim
        mons = [self.mon(155), own]
        sim.put(r["wPartyCount"], self.lua.table_from([2]))
        sim.put(r["wPartySpecies"], self.lua.table_from([155, own[0], 0xFF]))
        for slot, m in enumerate(mons):
            sim.put(r["wPartyMon1"] + slot * 48, self.lua.table_from(m[:48]))
            sim.put(r["wPartyMonOTs"] + slot * 11, self.lua.table_from(m[48:59]))
            sim.put(r["wPartyMonNicknames"] + slot * 11, self.lua.table_from(m[59:]))
        prof = self.lua.table_from(self.profile, recursive=True)
        for copy in ("primary", "backup"):
            def at(sym, off, data):
                base = self.T.saved_offset(prof, "gold", copy, sym, off + len(data)) + off
                for i, b in enumerate(data):
                    sim.cart[base + i] = b
            at("wPartyCount", 0, [2])
            at("wPartySpecies", 0, [155, own[0], 0xFF])
            for slot, m in enumerate(mons):
                at("wPartyMon1", slot * 48, m[:48])
                at("wPartyMonOTs", slot * 11, m[48:59])
                at("wPartyMonNicknames", slot * 11, m[59:])

    def lease(self, cmd, gen, ack, result, slot=1):
        self.sim.put(self.ram["wSlinkMailbox"] + 14, self.lua.table_from(list(bytes.fromhex(lease(cmd, gen, ack, result, slot)))))

    def ot(self, slot, m):
        r = self.ram
        self.sim.put(r["wOTPartyMon1"] + slot * 48, self.lua.table_from(m[:48]))
        self.sim.put(r["wOTPartyMonOTs"] + slot * 11, self.lua.table_from(m[48:59]))
        self.sim.put(r["wOTPartyMonNicknames"] + slot * 11, self.lua.table_from(m[59:]))
        if slot == 0:
            self.sim.put(r["wOTPartySpecies"], self.lua.table_from([m[0], 0xFF]))

    def frames(self, n, pushes=0):
        for _ in range(n):
            self.sim.step()
            if pushes:
                self.sim.push(pushes)

    def go(self):
        base = self.trade.baseline(KEY)
        self.sim.jlog("TRADE_READY", self.lua.table_from({"frame": self.sim.frame, "snapshot_sha256": base.snapshot_sha256,
                                                          "slot": 1, "key": KEY}))
        self.frames(5)
        self.sim.jlog("TRADE_GO", self.lua.table_from({"frame": self.sim.frame, "run_id": "g2trade_sim"}))
        self.trade.arm_stack()

    def finish(self, kind, reload=False):
        self.frames(3)
        self.sim.final(self.trade, kind)
        self.trade.stack()
        self.trade.release()
        lines = [self.sim.lines[i] for i in range(1, len(self.sim.lines) + 1)]
        if reload:   # the reload leg is the scenario's (S.reload, a live soft reset); the sim models its markers only
            final = json.loads(next(line for line in lines if line.startswith("TRADE_FINAL "))[12:])
            lines.append('RELOAD_CHORD {"frame": 9000, "frames": 4}')
            lines.append('RELOADED {"frame": 9500, "map_group": 20, "map_number": 1, "x": 5, "y": 3, "party_count": 2}')
            lines.append("TRADE_RELOAD " + json.dumps({"frame": 9510, "snapshot_sha256": final["snapshot_sha256"],
                         "cartram_sha256": final["cartram_sha256"], "party_keys": [KEY],
                         "dex": {"primary": {"caught_hex": "00" * 32, "seen_hex": "00" * 32},
                                 "backup": {"caught_hex": "00" * 32, "seen_hex": "00" * 32}}}))
        return lines


def test_attach_hooks_print_a_committed_proposer_visit_the_verdict_passes(tmp_path, monkeypatch):
    t = TradeSim(tmp_path, "a", monkeypatch)
    own = t.mon(16)
    t.party(own)
    t.go()
    sim = t.sim
    t.lease(1, 3, 3, 0, 0)
    sim.h.rec.client_saves, sim.h.rec.save_completed_frame = 2, sim.frame   # the forced pre-trade save
    sim.fire("SlinkTradeEntry")
    t.frames(4, pushes=6)
    t.lease(2, 5, 4, 0xFF)
    sim.fire("SlinkTradeWaitAck")
    t.lease(2, 5, 5, 0xFF)
    sim.fire("SlinkTradeWaitApply")
    t.frames(4, pushes=4)
    t.ot(1, own)                      # SlinkTradeSnapshot's frozen preimage
    partner = t.mon(161)
    t.ot(0, partner)                  # the host staged the partner's mon
    t.lease(5, 6, 5, 0xFF)
    sim.fire("SlinkTradeApplyPickup")
    sim.regs.A, sim.regs.B = 1, 0
    sim.fire("SlinkTradeCommit")
    sim.fire("RemoveMonFromPartyOrBox")
    sim.fire("TradeAnimation")
    t.frames(6, pushes=8)
    sim.fire("AddTempmonToParty")
    sim.fire("EvolvePokemon")
    sim.fire("SaveAfterLinkTrade")
    t.frames(6, pushes=5)
    sim.regs.B = 0
    sim.fire("SlinkTradeCommit.cleanup")
    sim.regs.A = 0
    sim.fire("SlinkTradePublishDone")
    t.lease(7, 6, 6, 0)
    sim.fire("SlinkTradeWaitRelease")
    t.frames(2)
    t.lease(0, 6, 6, 0)
    sim.fire("SlinkTradeExit")
    # the client's trade_done (duo_gen2_main.lua logs every TX): the received partner's key
    sim.lines[len(sim.lines) + 1] = "TX " + json.dumps({"event": "trade_done", "token": "t1", "slot": 1,
                                                         "new_key": "1A2B:B542:A1", "new_species": 161})
    lines = t.finish("flush", reload=True)
    problems, facts = trade_verdict(lines, "new", "a")
    assert problems == []
    native = json.loads(next(l for l in lines if l.startswith("TRADE_NATIVE_SAVE "))[18:])
    assert native["flushed_matches"] is True and native["snapshot_bytes"] == 0x8000 + 22
    stack = json.loads(next(l for l in lines if l.startswith("TRADE_STACK "))[12:])
    assert stack["armed_count"] == STACK[1] - STACK[0] + 1 and [p["visited"] for p in stack["phases"]] == [True, True, False, True]
    # red: the same run with a hook fault can never pass
    problems, _ = trade_verdict(lines + ['TRADE_HOOK_ERROR {"text": "x"}'], "new", "a")
    assert problems


def test_attach_hooks_prove_the_responder_decline_control(tmp_path, monkeypatch):
    t = TradeSim(tmp_path, "b", monkeypatch)
    own = t.mon(19)
    t.party(own)
    t.go()
    sim = t.sim
    t.ot(0, t.mon(16))
    t.lease(3, 9, 8, 0xFF)
    t.trade.state.control_kind = "decline"
    sim.fire("SlinkTradePromptEntry")
    sim.jlog("TRADE_ANSWER", t.lua.table_from({"frame": sim.frame, "answer": "NO"}))
    t.frames(4, pushes=5)
    t.lease(3, 9, 9, 0xFF)
    sim.regs.A = 1
    sim.fire("SlinkTradePublishDone")
    t.frames(3, pushes=2)
    t.lease(8, 9, 9, 1)
    sim.fire("SlinkTradeExit")
    lines = t.finish("flush")
    problems, _ = trade_verdict(lines, "decline_new", "b")
    assert problems == []
    # red: an accept (A=0) at the same site is not a decline trigger: no control, no PASS
    (tmp_path / "r").mkdir()
    t2 = TradeSim(tmp_path / "r", "b", monkeypatch)
    t2.party(own)
    t2.go()
    t2.ot(0, t2.mon(16))
    t2.lease(3, 9, 8, 0xFF)
    t2.trade.state.control_kind = "decline"
    t2.sim.fire("SlinkTradePromptEntry")
    t2.sim.jlog("TRADE_ANSWER", t2.lua.table_from({"frame": t2.sim.frame, "answer": "NO"}))
    t2.frames(4, pushes=5)
    t2.sim.regs.A = 0
    t2.sim.fire("SlinkTradePublishDone")
    t2.lease(8, 9, 9, 1)
    t2.sim.fire("SlinkTradeExit")
    problems, _ = trade_verdict(t2.finish("flush"), "decline_new", "b")
    assert any("TRADE_CONTROL" in p for p in problems)


# ── O-31: the disclosed harness writes (D3 mail item, trade-evolve wild species) ──
def test_o31_plants_are_derived_from_the_decomp_and_the_overlay_table():
    from tools.gen2_trade_facts import trade_facts
    for title in ("gold", "crystal"):
        plants = trade_facts(title)["plants"]
        assert plants == {"evolve_species": {"name": "HAUNTER", "id": HAUNTER}, "evolves_to": {"name": "GENGAR", "id": GENGAR},
                          "mail_item": {"name": "FLOWER_MAIL", "id": FLOWER_MAIL}}


def test_o31_undisclosed_or_misplaced_plants_are_refused():
    # the D3 mail item planted without its HARNESS_WRITE disclosure: refused, however native the refusal looked
    red(drop(trade_stream("refuse_item", "a"), "HARNESS_WRITE"), "refuse_item", "a", "missing HARNESS_WRITE")
    # a mail item in a case that plans no write (the baseline would carry an undisclosed plant)
    red(edit(trade_stream("decline_new", "a"), "TRADE_BASELINE",
             lambda v: v["party"][1].update(blob_hex=blob(16, FLOWER_MAIL))), "decline_new", "a", "undisclosed write")
    # a HARNESS_WRITE where the plan has none
    new = trade_stream("new", "a")
    red(new[:8] + [line for line in trade_stream("refuse_item", "a") if line.startswith("HARNESS_WRITE ")] + new[8:],
        "new", "a", "plans none")
    # the planted mail must come after the link catch and before the baseline
    rf = trade_stream("refuse_item", "a")
    at = [i for i, line in enumerate(rf) if line.startswith("HARNESS_WRITE ")][0]
    cap = [i for i, line in enumerate(rf) if line.startswith("ENGINE_CAPTURE ")][0]
    red(rf[:cap] + [rf[at]] + [line for i, line in enumerate(rf[cap:], cap) if i != at], "refuse_item", "a", "before the link")
    # the evolve plant: disclosed, before the catch, and the caught species must be the planted one
    ev = trade_stream("evolve", "a")
    red(drop(ev, "HARNESS_WRITE"), "evolve", "a", "missing HARNESS_WRITE")
    red(edit(ev, "ENGINE_CAPTURE", lambda v: v.update(species_id=16)), "evolve", "a", "not the disclosed planted species")
    red(edit(ev, "HARNESS_WRITE", lambda v: v.update(purpose="d3_mail_item")), "evolve", "a", "planned disclosed")


def test_evolve_case_needs_the_native_trade_evolution_and_the_server_rekey():
    b = trade_stream("evolve", "b")
    red(edit(b, "TRADE_STACK", lambda v: v["phases"][2].update(visited=False, start=None, end=None, samples=[])),
        "evolve", "b", "evolution_animation unvisited")
    tx = [i for i, line in enumerate(b) if line.startswith("TX ")][0]
    kept = b[:tx] + ["TX " + json.dumps({"event": "trade_done", "token": "t1", "slot": 1,
                                         "new_key": "1A2B:B542:%02X" % HAUNTER, "new_species": HAUNTER})] + b[tx + 1:]
    red(kept, "evolve", "b", "did not evolve natively")
    red(b[:tx] + b[tx + 1:], "evolve", "b", "no trade_done")
    # a non-evolving committed side never shows an evolution animation
    red(edit(trade_stream("new", "b"), "TRADE_STACK", lambda v: v["phases"].__setitem__(2, {
        "phase": "evolution_animation", "visited": True, "start": {"frame": 1901, "site": site("x")},
        "end": {"frame": 1902, "site": site("y")},
        "samples": [{"frame": 1901, "stack_addr": 0xDFDE, "sp": 0xDFE0, "pc": 1, "rom_bank": 1}]})), "new", "b", "forbids")


def test_attach_plants_are_disclosed_wram_writes_that_read_back(tmp_path, monkeypatch):
    t = TradeSim(tmp_path, "a", monkeypatch)
    lua, sim = t.lua, t.sim
    t.party(t.mon(16))
    row = t.trade.plant_mail(1)
    assert row.purpose == "d3_mail_item" and row.bytes_after == "9e" and row.domain == "WRAM"
    assert sim.bus[t.ram["wPartyMon1"] + 48 + 1] == FLOWER_MAIL
    # the species plant fires only at a Route 29 wild StartBattle, once
    r = t.ram
    t.trade.arm_species_plant()
    sim.put(r["wOtherTrainerClass"], lua.table_from([0]))
    sim.put(r["wBattleMode"], lua.table_from([1]))
    sim.put(r["wBattleType"], lua.table_from([0]))
    sim.put(r["wMapGroup"], lua.table_from([99]))
    sim.fire("StartBattle")
    lines = [sim.lines[i] for i in range(1, len(sim.lines) + 1)]
    assert sum(1 for line in lines if line.startswith("HARNESS_WRITE ")) == 1   # wrong map: no write
    sim.put(r["wMapGroup"], lua.table_from([24]))
    sim.put(r["wMapNumber"], lua.table_from([3]))
    sim.fire("StartBattle")
    sim.fire("StartBattle")
    writes = [json.loads(line[14:]) for i in range(1, len(sim.lines) + 1) if (line := sim.lines[i]).startswith("HARNESS_WRITE ")]
    assert [w["purpose"] for w in writes] == ["d3_mail_item", "trade_evolve_species"]
    assert writes[1]["bytes_after"] == "%02x" % HAUNTER and writes[1]["symbol"] == "wTempWildMonSpecies"


# --- DUO-WAVE-C: whiteout, pc_ops, changebox (roadmap rows 9-11) --------------------------------------

DRIVER_FILES += ("lua/tests/duo/scenario_gen2_whiteout.lua", "lua/tests/duo/scenario_gen2_pc_ops.lua",
                 "lua/tests/duo/scenario_gen2_changebox.lua", "lua/tests/gen2_pc_inputs.lua",
                 "lua/tests/gen2_poison_inputs.lua")
STARTER = "1111:B542:9E"
OTHER = "0000:0000:01"


def wave_c(name, lines):
    """The pure verdict of scenario_gen2_<name>.lua (whiteout/pc_ops: over the link verdict; changebox: its B half)."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    link = lua.execute(SCENARIO.read_text(encoding="utf-8"))
    s = lua.execute((ROOT / f"lua/tests/duo/scenario_gen2_{name}.lua").read_text(encoding="utf-8"))
    if name == "changebox":
        problems, detail = s.verdict(lua.table_from(lines), json_codec)
        return list(problems.values()), detail
    problems, receipt = s.verdict(lua.table_from(lines), json_codec, link.verdict)
    return list(problems.values()), receipt


def retag(lines, player, scenario, sites):
    out = []
    for line in lines:
        tag, body = line.split(" ", 1)
        if tag in ("DUO_GEN2", "CLIENT"):
            value = json.loads(body)
            value.update({"player": player, "scenario": scenario} if tag == "DUO_GEN2" else {"registered_sites": sites})
            line = f"{tag} {json.dumps(value)}"
        out.append(line)
    return out


def edit_tag(lines, tag, index=0, **changes):
    out, seen = [], 0
    for line in lines:
        if line.startswith(tag + " "):
            if seen == index:
                value = json.loads(line[len(tag) + 1:])
                value.update(changes)
                line = f"{tag} {json.dumps(value)}"
            seen += 1
        out.append(line)
    return out


def without(lines, prefix, index=None):
    """Drop every line starting with prefix, or only its index-th occurrence."""
    out, seen = [], 0
    for line in lines:
        if line.startswith(prefix):
            seen += 1
            if index is None or seen - 1 == index:
                continue
        out.append(line)
    return out


def move(lines, prefix, before_prefix):
    """Move the first line starting with prefix to just before the first line starting with before_prefix."""
    lines = list(lines)
    row = next(line for line in lines if line.startswith(prefix))
    lines.remove(row)
    at = next(i for i, line in enumerate(lines) if line.startswith(before_prefix))
    return lines[:at] + [row] + lines[at:]


WHITEOUT_SITES = ["battle_faint", "capture_party", "whiteout_before_heal"]


def whiteout_lines(write=False):
    j = json.dumps
    a = faint_lines("a")
    base = retag(a[:9], "a", "gen2_whiteout", WHITEOUT_SITES)   # through LINK_SAVE
    record = "00" * 32 + "0000" + "00" * 14
    middle = [
        "ENGINE_FAINT " + j({"frame": 2000, "site_id": "battle_faint", "cause": "battle", "key": STARTER, "slot": 0}),
        "FAINT_SENT " + j({"frame": 2001, "key": STARTER, "seq": 18}),
        "ENGINE_FAINT " + j({"frame": 3000, "site_id": "battle_faint", "cause": "battle", "key": KEY, "slot": 1}),
        "FAINT_SENT " + j({"frame": 3001, "key": KEY, "seq": 20}),
        "ENGINE_WHITEOUT " + j({"frame": 3050, "site_id": "whiteout_before_heal",
                                "party": [{"key": STARTER, "hp": 0}, {"key": KEY, "hp": 0}]}),
        "TX " + j({"event": "whiteout", "seq": 21}, separators=(",", ":")),
        "REVIVED " + j({"frame": 3060, "key": KEY, "slot": 1, "hp": 14}),
        "RX force_faint key=" + KEY]
    if write:
        middle.append("PARTY_HP_WRITE " + j({"frame": 3100, "key": KEY, "slot": 1, "kind": "party_hp", "ok": True}))
    middle += ["MEMORIAL_PREIMAGE " + j({"frame": 3300, "key": KEY, "slot": 1, "raw_hex": record,
                                         "ot_raw_hex": "80" * 11, "nickname_raw_hex": "81" * 11, "species_marker": 16}),
               "MEMORIAL_ACK " + j({"frame": 3301, "event": "memorialize_done", "key": KEY, "box": 13})]
    return base + middle + [a[-1]]


@pytest.mark.parametrize("write", [False, True], ids=["memorial-first", "repair-written"])
def test_whiteout_verdict_passes_either_repair_order(write):
    problems, receipt = wave_c("whiteout", whiteout_lines(write))
    assert problems == [], problems
    assert receipt["schema"] == "gen2-duo-whiteout-v1" and receipt["revived"]["hp"] == 14
    assert receipt["repair"]["outcome"] == ("written" if write else "memorial_first")


TX_WHITEOUT = "TX " + json.dumps({"event": "whiteout", "seq": 30}, separators=(",", ":"))


@pytest.mark.parametrize("lines,match", [
    (retag(whiteout_lines(), "a", "gen2_whiteout", ["battle_faint"]), "lack whiteout_before_heal"),
    (edit_tag(edit_tag(whiteout_lines(), "ENGINE_FAINT", 0, key=KEY), "ENGINE_FAINT", 1, key=STARTER), "did not faint last"),
    (without(whiteout_lines(), "ENGINE_FAINT", 0), "1 ENGINE_FAINT markers"),
    (edit_tag(whiteout_lines(), "ENGINE_WHITEOUT", party=[{"key": STARTER, "hp": 0}, {"key": KEY, "hp": 3}]), "had HP"),
    (edit_tag(whiteout_lines(), "ENGINE_WHITEOUT", party=[{"key": STARTER, "hp": 0}]), "not [starter, linked catch]"),
    (move(whiteout_lines(), "ENGINE_WHITEOUT", "ENGINE_FAINT"), "precedes the linked faint"),
    (without(whiteout_lines(), "TX "), "0 whiteout events"),
    (whiteout_lines()[:-1] + [TX_WHITEOUT, whiteout_lines()[-1]], "2 whiteout events"),
    (without(whiteout_lines(), "REVIVED"), "missing REVIVED"),
    (edit_tag(whiteout_lines(), "REVIVED", hp=0), "alive"),
    (without(whiteout_lines(), "RX force_faint"), "no O-24 force_faint"),
    (move(whiteout_lines(), "RX force_faint", "REVIVED"), "no O-24 force_faint"),
    (move(whiteout_lines(True), "PARTY_HP_WRITE", "RX force_faint"), "precedes the re-issued force_faint"),
    (edit_tag(whiteout_lines(True), "PARTY_HP_WRITE", key=OTHER), "hit another mon"),
    (without(whiteout_lines(), "MEMORIAL_ACK"), "no memorial"),
    (edit_tag(whiteout_lines(), "SAVE_WITNESS", gate_saves=1), "no native save after LINK_SAVE"),
], ids=["no-site", "catch-first", "one-faint", "pre-heal-hp", "short-party", "whiteout-first", "no-tx", "two-tx",
        "no-revived", "revived-dead", "no-repair", "repair-before-revive", "write-first", "write-other", "no-memorial",
        "no-new-save"])
def test_whiteout_verdict_refuses_a_tampered_or_reordered_half(lines, match):
    problems, receipt = wave_c("whiteout", lines)
    assert receipt is None and any(match in p for p in problems), problems


PC_SITES = ["pc_deposit_begin", "pc_deposit_complete", "pc_withdraw_begin", "pc_withdraw_complete",
            "pc_release_box_begin", "pc_release_box_complete"]


def pc_lines(player):
    j = json.dumps
    a = faint_lines(player)
    base = retag(a[:9], player, "gen2_pc_ops", PC_SITES if player == "a" else [])
    base.insert(8, "RX box_mon key=" + KEY)   # the link's own quarantine traffic, before LINK_SAVE: never counted
    if player == "a":
        def pc(frame, kind, **extra):
            return "ENGINE_PC " + j({"frame": frame, "kind": kind, "site_id": "x", "key": KEY, **extra})

        def tx(event):
            return "TX " + j({"event": event, "key": KEY, "seq": 1}, separators=(",", ":"))
        middle = [pc(2000, "party_to_box", box_index=0), tx("party_to_box"),
                  pc(2100, "box_to_party", box_index=0), tx("box_to_party"),
                  "PC_STATE " + j({"frame": 2200, "phase": "deposit-withdraw", "party_count": 2, "box_count": 0, "cur_box": 0}),
                  pc(2400, "party_to_box", box_index=0), tx("party_to_box"),
                  pc(2500, "pc_release", collection="box", box_index=0),
                  "PC_STATE " + j({"frame": 2600, "phase": "deposit-release", "party_count": 1, "box_count": 0, "cur_box": 0})]
    else:
        def partner(n, cmd, frame):
            party = cmd == "party_mon"
            return f"PC_PARTNER_{n} " + j({"frame": frame, "cmd": cmd, "key": KEY, "in_party": party,
                                           "party_count": 2 if party else 1, "box_count": 0 if party else 1, "cur_box": 0})
        middle = ["RX box_mon key=" + KEY, partner(1, "box_mon", 2050),
                  "RX party_mon key=" + KEY, partner(2, "party_mon", 2150),
                  "RX box_mon key=" + KEY, partner(3, "box_mon", 2450)]
    return base + middle + [a[-1]]


@pytest.mark.parametrize("player", ["a", "b"])
def test_pc_ops_verdict_passes_each_complete_half(player):
    problems, receipt = wave_c("pc_ops", pc_lines(player))
    assert problems == [], problems
    assert receipt["schema"] == "gen2-duo-pc-ops-v1" and receipt["player"] == player


TX_OWN = "TX " + json.dumps({"event": "party_to_box", "key": KEY}, separators=(",", ":"))


@pytest.mark.parametrize("lines,match", [
    (retag(pc_lines("a"), "a", "gen2_pc_ops", PC_SITES[:4]), "lack pc_release_box_begin"),
    (without(pc_lines("a"), "ENGINE_PC", 3), "3 ENGINE_PC"),
    (edit_tag(pc_lines("a"), "ENGINE_PC", 3, collection="party"), "pc_release/box"),
    (edit_tag(pc_lines("a"), "ENGINE_PC", 1, key=OTHER), "box_to_party for the linked key"),
    (without(pc_lines("a"), "TX ", 1), "not party_to_box, box_to_party"),
    (move(pc_lines("a"), "TX ", "ENGINE_PC"), "precedes its engine event"),
    (edit_tag(pc_lines("a"), "PC_STATE", 1, box_count=1), "box empty"),
    (pc_lines("a")[:-1] + ["RX force_faint key=" + KEY, pc_lines("a")[-1]], "death command"),
    (without(pc_lines("b"), "PC_PARTNER_3"), "missing PC_PARTNER_3"),
    (without(pc_lines("b"), "RX box_mon", 2), "no RX box_mon"),
    (edit_tag(pc_lines("b"), "PC_PARTNER_2", in_party=False), "PC_PARTNER_2 state differs"),
    (pc_lines("b")[:-1] + [TX_OWN, pc_lines("b")[-1]], "storage event of its own"),
    (move(without(pc_lines("b"), "RX box_mon", 0), "PC_PARTNER_1", "RX box_mon"), "precedes its command"),
], ids=["no-site", "no-release", "party-release", "withdraw-other-key", "no-withdraw-send", "send-first",
        "box-not-empty", "a-death", "b-missing-third", "b-no-third-rx", "b-not-in-party", "b-sent", "b-early"])
def test_pc_ops_verdict_refuses_a_tampered_or_reordered_half(lines, match):
    problems, receipt = wave_c("pc_ops", lines)
    assert receipt is None and any(match in p for p in problems), problems


def changebox_lines():
    j = json.dumps
    b = retag(faint_lines("b"), "b", "gen2_changebox", ["change_box_begin", "change_box_loaded"])

    def change(frame, old, new):
        return "ENGINE_PC " + j({"frame": frame, "kind": "box_change", "site_id": "change_box_loaded",
                                 "old_box": old, "new_box": new})
    return b[:-1] + [change(3400, 0, 13), "CHANGEBOX_TO " + j({"frame": 3450, "cur_box": 13, "box_count": 1}),
                     change(3500, 13, 0), "CHANGEBOX_BACK " + j({"frame": 3550, "cur_box": 0, "box_count": 0}), b[-1]]


def test_changebox_verdict_passes_the_round_trip_on_top_of_the_faint_b_half():
    problems, detail = wave_c("changebox", changebox_lines())
    assert problems == [] and detail["to"]["box_count"] == 1
    assert faint_verdict(changebox_lines())[0] == []   # the faint B half still holds under the extra markers


@pytest.mark.parametrize("lines,match", [
    (retag(changebox_lines(), "b", "gen2_changebox", []), "lack change_box_begin"),
    (edit_tag(changebox_lines(), "CHANGEBOX_TO", box_count=0), "did not list the memorial"),
    (edit_tag(changebox_lines(), "ENGINE_PC", 0, new_box=1), "box change 1 differs"),
    (without(changebox_lines(), "CHANGEBOX_BACK"), "once each"),
    (move(changebox_lines(), "SAVE_WITNESS", "CHANGEBOX_BACK"), "precedes the box change back"),
    (changebox_lines()[:-1] + ['TX {"event":"box_to_party"}', changebox_lines()[-1]], "not a transfer"),
], ids=["no-site", "memorial-unlisted", "wrong-box", "no-back", "save-first", "transfer"])
def test_changebox_verdict_refuses_a_tampered_round_trip(lines, match):
    problems, _ = wave_c("changebox", lines)
    assert any(match in p for p in problems), problems


@pytest.mark.parametrize("scenario,player,site", [
    ("gen2_whiteout", "a", "battle_faint"), ("gen2_pc_ops", "a", "pc_deposit_begin"),
    ("gen2_changebox", "b", "change_box_begin")])
def test_wave_c_halves_refuse_before_any_input_without_their_sites(tmp_path, scenario, player, site):
    lines, sim, _ = run_driver(tmp_path, scenario=scenario, player=player)
    assert lines[-1] == f"RESULT: FAIL (production signals lack {site})", lines[-5:]
    assert not sim.inputs


# --- DUO-WAVE-C: poison (roadmap row 12) --------------------------------------------------------------

DRIVER_FILES += ("lua/tests/duo/scenario_gen2_poison.lua",)


def poison_verdict(lines):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    link = lua.execute(SCENARIO.read_text(encoding="utf-8"))
    poison = lua.execute((ROOT / "lua/tests/duo/scenario_gen2_poison.lua").read_text(encoding="utf-8"))
    faint = poison.faint(str(ROOT).replace("\\", "/"))
    problems, receipt = faint.verdict(lua.table_from(lines), json_codec, link.verdict)
    return list(problems.values()), receipt


def poison_lines(player):
    sites = ["battle_end", "capture_party", "poison_faint"]
    lines = retag(faint_lines(player), player, "gen2_poison", sites)
    return edit_tag(lines, "ENGINE_FAINT", site_id="poison_faint", cause="poison") if player == "a" else lines


@pytest.mark.parametrize("player", ["a", "b"])
def test_poison_verdict_passes_each_complete_half(player):
    problems, receipt = poison_verdict(poison_lines(player))
    assert problems == [], problems
    assert receipt["schema"] == "gen2-duo-poison-v1" and receipt["player"] == player


@pytest.mark.parametrize("lines,match", [
    (edit_tag(poison_lines("a"), "ENGINE_FAINT", site_id="battle_faint", cause="battle"), "not poison_faint/poison"),
    (retag(poison_lines("a"), "a", "gen2_poison", ["battle_faint"]), "lack poison_faint"),
    (without(poison_lines("a"), "FAINT_SENT"), "missing FAINT_SENT"),
    (without(poison_lines("b"), "PARTY_HP_WRITE"), "missing PARTY_HP_WRITE"),
], ids=["battle-death", "no-site", "no-send", "b-no-write"])
def test_poison_verdict_refuses_a_battle_death_or_a_missing_propagation(lines, match):
    problems, receipt = poison_verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


def test_poison_a_refuses_before_any_input_without_a_registered_poison_faint(tmp_path):
    lines, sim, _ = run_driver(tmp_path, scenario="gen2_poison", player="a")
    assert lines[-1] == "RESULT: FAIL (production signals lack poison_faint)", lines[-5:]
    assert not sim.inputs


def test_forced_save_image_is_required_on_the_proposer_only():
    # coordinator ruling after 9805ac1c: the negative cases compare A's final against this image, byte-exact
    for case in ("decline_new", "timeout", "new"):
        red(drop(trade_stream(case, "a"), "TRADE_FORCED_SAVE"), case, "a", "missing TRADE_FORCED_SAVE")
    red(edit(trade_stream("timeout", "a"), "TRADE_FORCED_SAVE", lambda v: v.update(client_saves=1)), "timeout", "a",
        "successful pre-lease native save")
    red(edit(trade_stream("timeout", "a"), "TRADE_FORCED_SAVE", lambda v: v.update(frame=1199)), "timeout", "a",
        "captured at SlinkTradeEntry")
    # HARNESS: the accepting responder has one too (its Link_SaveGame), between its offer and the APPLY pickup
    red(drop(trade_stream("new", "b"), "TRADE_FORCED_SAVE"), "new", "b", "missing TRADE_FORCED_SAVE")
    red(edit(trade_stream("evolve", "b"), "TRADE_FORCED_SAVE", lambda v: v.update(frame=1500)), "evolve", "b",
        "between its offer and the APPLY pickup")
    declined = trade_stream("decline_new", "b")
    red(declined + [line for line in trade_stream("new", "b") if line.startswith("TRADE_FORCED_SAVE ")], "decline_new",
        "b", "unexpected TRADE_FORCED_SAVE")
