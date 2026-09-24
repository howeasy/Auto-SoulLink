"""Card DUO-WAVE-D, gen2_ball_gate (D-2): MODEL controls, no emulator.

- lua/tests/gen2_scripted_play.lua `case.resume` / `case.natural_balls`: the errand leg from a warm town fixture
  (mid-chain, empty Ball pocket) with no O-10 staging;
- lua/tests/duo/gen2_ball_gate_inputs.lua: the two legs around the pre-Ball encounter (pre: lab -> Route 29 grass,
  post: errand + the aide's Balls -> Route 29 grass, the wild battle handed over unanswered);
- lua/tests/duo/scenario_gen2_ball_gate.lua S.verdict over the marker lines;
- tools/gen2_duo_oracles.ball_gate_oracle over synthetic saves and server state.
Facts: docs/gen2/reviews/DUO_WAVE_D_FACTS_2026-09-24.md.
"""
from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path

import pytest
from lupa import LuaError, LuaRuntime

from server.adapters import gen2_codec as codec
from tools import gen2_duo_oracles as oracles, gen2_fixtures as g
from tools.gen2_fixtures import _saved_field

ROOT = Path(__file__).resolve().parents[2]
PLAY = ROOT / "lua/tests/gen2_scripted_play.lua"
INPUTS = ROOT / "lua/tests/duo/gen2_ball_gate_inputs.lua"
SCENARIO = ROOT / "lua/tests/duo/scenario_gen2_ball_gate.lua"
LINK = ROOT / "lua/tests/duo/scenario_gen2_link.lua"
ALL = {"Up": True, "Down": True, "Left": True, "Right": True}
TITLE = "crystal"


@functools.cache
def errand_facts():
    return g.route_facts(TITLE, errand=True)


class Leg:
    """One pure driver (scripted play or a ball-gate leg) fed synthetic points."""

    def __init__(self, mode=None, **case_fields):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.P = self.lua.execute(PLAY.read_text(encoding="utf-8"))
        self.facts = errand_facts()
        case = {"name": "crystal_town", "title": TITLE, "target": "town", "identity": "default",
                "title_idle_frames": 0, "attempt_id": "unit-1"}
        case.update(case_fields)
        lf, lc = self.lua.table_from(self.facts, recursive=True), self.lua.table_from(case)
        if mode is None:
            self.driver = self.P.new(lf, lc)
        else:
            B = self.lua.execute(INPUTS.read_text(encoding="utf-8"))
            self.driver = B.driver(self.P, lf, lc, mode)
        self.frame = 0

    def point(self, map_name, balls=0, **fields):
        m = self.facts["maps"][map_name]
        items = {1: {"id": self.facts["balls"]["item"], "quantity": balls}} if balls else {}
        base = {"title": TITLE, "rom_sha1": self.facts["rom_sha1"], "core_mode": "CGB", "attempt_id": "unit-1",
                "facts_fingerprint": self.facts["fingerprint"], "overworld_ready": True, "battle_mode": 0,
                "party_count": 1, "starter_species": self.facts["starter"]["species"], "starter_level": 5,
                "got_starter": True, "pokegear_obtained": True, "save_success_counter": 0,
                "new_bark_scene": self.facts["maps"]["NewBarkTown"]["scenes"]["SCENE_NEWBARKTOWN_NOOP"],
                "ball_pocket": {"count": 1 if balls else 0, "items": items, "terminator": 255},
                "map_group": m["map_group"], "map_number": m["map_number"], "can_step": ALL, "facing": "Down",
                "got_egg": False, "gave_egg": False}
        base.update(fields)
        return self.lua.table_from(base, recursive=True)

    def raw(self, map_name, **fields):
        self.frame += 1
        return self.driver.step(self.point(map_name, **fields), self.frame)

    def step(self, map_name, **fields):
        out = self.raw(map_name, **fields)
        buttons, phase = out[0], out[1]
        assert buttons is not None, phase
        request = out[2] if len(out) > 2 else None
        return sorted(k for k, v in buttons.items() if v), phase, request


def grass_tile(facts, map_name="Route29"):
    m = facts["maps"][map_name]
    for index, tile in enumerate(m["grid"]):
        if tile == 2:
            return index % m["width"], index // m["width"]
    raise AssertionError("no grass")


def street_tile(facts, map_name="Route29"):
    """A walkable non-grass tile with a grass tile somewhere reachable (the east entrance row)."""
    return 59, 8


# --- scripted play: resume + natural Balls ---------------------------------------------------------

def test_a_town_case_with_natural_balls_runs_the_errand_from_the_lab_without_staging():
    leg = Leg(target="battle", resume=True, natural_balls=True)
    buttons, phase, request = leg.step("ElmsLab", x=5, y=3)
    assert phase == "leave-elm" and request is None


def test_without_natural_balls_the_empty_pocket_still_asks_for_o10():
    leg = Leg(target="battle", resume=True)
    buttons, phase, request = leg.step("ElmsLab", x=5, y=3)
    assert phase == "o10-balls" and request["kind"] == "o10-ball-pocket"


def test_without_resume_a_mid_chain_start_is_refused():
    leg = Leg(target="battle", natural_balls=True)
    out = leg.raw("ElmsLab", x=5, y=3)
    assert out[0] is None and "bedroom" in out[1]


def test_natural_balls_needs_the_errand_facts():
    lua = LuaRuntime(unpack_returned_tuples=True)
    P = lua.execute(PLAY.read_text(encoding="utf-8"))
    case = {"name": "crystal_town", "title": TITLE, "target": "battle", "identity": "default",
            "title_idle_frames": 0, "attempt_id": "unit-1", "resume": True, "natural_balls": True}
    with pytest.raises(LuaError, match="errand"):
        P.new(lua.table_from(g.route_facts(TITLE), recursive=True), lua.table_from(case))


# --- the two ball-gate legs ------------------------------------------------------------------------

def test_pre_leg_walks_route29_to_the_grass_instead_of_heading_west():
    leg = Leg("pre")
    x, y = street_tile(leg.facts)
    buttons, phase, _ = leg.step("Route29", x=x, y=y)
    assert phase == "pre-walk" and len(buttons) == 1


def test_pre_leg_ends_on_grass_and_on_a_battle():
    leg = Leg("pre")
    x, y = grass_tile(leg.facts)
    assert leg.step("Route29", x=x, y=y)[:2] == ([], "pre-grass")
    leg = Leg("pre")
    battle = {"overworld_ready": False, "battle_mode": 1}
    assert leg.step("Route29", x=59, y=8, **battle)[:2] == ([], "pre-grass")


def test_pre_leg_leaves_the_lab_through_the_scripted_play():
    leg = Leg("pre")
    assert leg.step("ElmsLab", x=5, y=3)[1] == "leave-elm"


def test_pre_leg_refuses_balls_before_the_errand():
    leg = Leg("pre")
    out = leg.raw("Route29", x=59, y=8, balls=10)
    assert out[0] is None and "Ball" in out[1]


def test_post_leg_runs_the_errand_from_route29_then_stops_on_grass_with_balls():
    leg = Leg("post")
    x, y = grass_tile(leg.facts)
    assert leg.step("Route29", x=x, y=y)[1] == "errand-west"          # before the egg: westward errand
    done = {"got_egg": True, "gave_egg": True, "balls": 5}
    assert leg.step("Route29", x=x, y=y, **done)[:2] == ([], "post-grass")


def test_post_leg_hands_a_post_ball_wild_battle_over_instead_of_running():
    leg = Leg("post")
    menu = {"kind": "battle_menu", "origin": "BattleMenu", "items": {1: "FIGHT", 2: "<PK><MN>", 3: "PACK", 4: "RUN"},
            "cursor": 1, "columns": 2}
    done = {"got_egg": True, "gave_egg": True, "balls": 5, "overworld_ready": False, "input_ready": True,
            "battle_mode": 1, "ui": menu}
    assert leg.step("Route29", x=59, y=8, **done)[:2] == ([], "post-grass")


def test_post_leg_still_runs_from_a_pre_ball_errand_battle():
    leg = Leg("post")
    menu = {"kind": "battle_menu", "origin": "BattleMenu", "items": {1: "FIGHT", 2: "<PK><MN>", 3: "PACK", 4: "RUN"},
            "cursor": 4, "columns": 2}
    wild = {"overworld_ready": False, "input_ready": True, "battle_mode": 1, "ui": menu}
    assert leg.step("Route30", x=7, y=40, **wild)[0] == ["A"]          # RUN is under the cursor


def test_post_leg_refuses_route29_after_the_errand_without_balls():
    leg = Leg("post")
    out = leg.raw("Route29", x=59, y=8, got_egg=True, gave_egg=True)
    assert out[0] is None and "natural Balls" in out[1]


def test_post_leg_refuses_more_than_the_aides_five():
    leg = Leg("post")
    out = leg.raw("Route29", x=59, y=8, got_egg=True, gave_egg=True, balls=15)
    assert out[0] is None and "natural Balls" in out[1]


# --- the scenario verdict ----------------------------------------------------------------------------

STARTER = "1111:B542:9E"
KEY = "1A2B:B542:10"


def happy_lines():
    j = json.dumps
    return [
        "DUO_GEN2 " + j({"player": "a", "scenario": "ball_gate", "attempt": 1, "case": "crystal_town",
                         "title": "crystal", "rom_sha1": "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133",
                         "fixture_sha256": "ab" * 32}),
        "CLIENT " + j({"qualification": "PRODUCTION", "production_admitted": True, "pack": "gen2_crystal",
                       "title": "crystal", "rom_sha1": "x"}),
        "BOOTED " + j({"frame": 300, "map_group": 24, "map_number": 5, "x": 5, "y": 3, "party_count": 1}),
        "MYKEY 0 " + STARTER,
        "HELLO " + j({"frame": 310, "ot_id": 46401, "has_pokeballs": False, "ball_count": 0}),
        "BALL_PRE " + j({"frame": 2000, "foe": 16, "area_id": "route_29", "has_pokeballs": False, "ball_count": 0}),
        'TX {"event":"faint","key":"' + STARTER + '","area_id":"cherrygrove_city"}',
        "ENGINE_FAINT " + j({"frame": 9000, "site_id": "battle_faint", "cause": "battle", "key": STARTER, "slot": 0}),
        "FAINT_SENT " + j({"frame": 9010, "key": STARTER, "seq": 4}),
        "BALL_FLIP " + j({"frame": 20000, "has_pokeballs": True, "ball_count": 5, "gave_egg": True}),
        "ENGINE_CAPTURE " + j({"frame": 21000, "site_id": "capture_party_finalized", "acquisition": "wild",
                               "area_id": "route_29", "destination": "party", "slot": 1, "key": KEY,
                               "species_id": 16, "level": 3}),
        "CAPTURE_SENT " + j({"frame": 21000, "key": KEY, "seq": 7}),
        "CAUGHT " + KEY,
        "SAVE_WITNESS " + j({"frame": 22000, "save_completed_frame": 21900, "gate_saves": 1, "client_saves": 1,
                             "cartram_sha256": "cd" * 32, "cartram_bytes": 32768, "saveram_path": "C:/x/y.SaveRAM",
                             "saveram_bytes": 32790, "flushed_matches": True}),
    ]


def verdict(lines):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    S = lua.execute(SCENARIO.read_text(encoding="utf-8"))
    link = lua.execute(LINK.read_text(encoding="utf-8"))
    problems, receipt = S.verdict(lua.table_from(lines), json_codec, link.verdict)
    return list(problems.values()), receipt


def edit(tag, **changes):
    out = []
    for line in happy_lines():
        if line.startswith(tag + " "):
            value = json.loads(line[len(tag) + 1:])
            value.update(changes)
            line = f"{tag} {json.dumps(value)}"
        out.append(line)
    return out


def insert_before(tag, line):
    out = []
    for row in happy_lines():
        if row.startswith(tag + " "):
            out.append(line)
        out.append(row)
    return out


def test_verdict_passes_the_complete_sequence():
    problems, receipt = verdict(happy_lines())
    assert problems == [] and receipt["schema"] == "gen2-duo-ball-gate-v1" and receipt["key"] == KEY
    assert receipt["pre_ball"]["foe"] == 16 and receipt["flip"]["ball_count"] == 5


@pytest.mark.parametrize("tag", ["BALL_PRE", "BALL_FLIP", "ENGINE_FAINT", "FAINT_SENT"])
def test_verdict_needs_every_ball_marker(tag):
    problems, receipt = verdict([line for line in happy_lines() if not line.startswith(tag + " ")])
    assert problems and receipt is None


@pytest.mark.parametrize("lines,match", [
    (edit("HELLO", has_pokeballs=True), "hello"),
    (edit("HELLO", ball_count=10), "hello"),
    (edit("BALL_PRE", has_pokeballs=True), "pre-Ball encounter"),
    (edit("BALL_PRE", area_id="route_30"), "pre-Ball encounter"),
    (edit("BALL_FLIP", ball_count=15), "flip"),
    (edit("BALL_FLIP", has_pokeballs=False), "flip"),
    (edit("ENGINE_FAINT", site_id="poison_faint"), "pre-Ball faint"),
    (edit("ENGINE_FAINT", key=KEY), "pre-Ball faint"),
    (edit("FAINT_SENT", key=KEY), "pre-Ball faint"),
    (insert_before("BALL_FLIP", 'TX {"event":"no_catch","area_id":"route_29"}'), "before the first Ball"),
    (insert_before("BALL_FLIP", 'TX {"event":"capture","key":"' + KEY + '"}'), "before the first Ball"),
    (happy_lines() + ["RX force_faint key=" + STARTER], "death command"),
    (happy_lines() + ["RX memorialize key=" + STARTER], "death command"),
    (edit("ENGINE_FAINT", frame=20001), "pre-Ball faint"),
], ids=["hello-balls", "hello-count", "pre-balls", "pre-area", "flip-o10", "flip-false", "faint-site",
        "faint-key", "faint-send-key", "early-no-catch", "early-capture", "force-faint", "memorialize",
        "faint-after-flip"])
def test_verdict_refuses(lines, match):
    problems, receipt = verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


def test_verdict_refuses_a_reordered_flip():
    lines = happy_lines()
    pre = next(i for i, line in enumerate(lines) if line.startswith("BALL_PRE "))
    flip = next(i for i, line in enumerate(lines) if line.startswith("BALL_FLIP "))
    lines[pre], lines[flip] = lines[flip], lines[pre]
    problems, receipt = verdict(lines)
    assert receipt is None and problems


# --- the oracle ------------------------------------------------------------------------------------

TOWN = {"a": ("crystal_town", "crystal"), "b": ("crystal_town_ot2", "crystal")}


def _poke(layout, cart, symbol, data):
    from tests.unit.test_gen2_duo_oracles import _poke as poke, _region_and_offset
    region, offset = _region_and_offset(layout, symbol)
    poke(cart, region, offset, data)


def natural_capture(layout, case, *, species, balls, ot_id):
    """The town fixture plus one caught mon and a natural Ball pocket [(POKE_BALL, balls)]."""
    from tests.unit.test_gen2_duo_oracles import build_capture
    save, mon = build_capture(layout, ROOT / f"tests/fixtures/gen2/{case}.SaveRAM", ot_id=ot_id, species=species,
                              ball_delta=0)
    cart = bytearray(save[:oracles.CARTRAM_BYTES])
    pocket = [] if balls is None else [(oracles.POKE_BALL, balls)]
    _poke(layout, cart, "wNumBalls", bytes([len(pocket)]))
    _poke(layout, cart, "wBalls", bytes([b for row in pocket for b in row] + [255]))
    for copy_name in ("primary", "backup"):
        checksum = codec.sav_checksum(bytes(cart), layout, copy_name)
        off = layout.checksum_offsets[copy_name]
        cart[off:off + 2] = checksum.to_bytes(2, "little")
    return bytes(cart) + save[oracles.CARTRAM_BYTES:], mon


def starter_key(layout, case):
    raw = (ROOT / f"tests/fixtures/gen2/{case}.SaveRAM").read_bytes()[:oracles.CARTRAM_BYTES]
    return codec.key(codec.decode_saved_party(raw, layout, copy_name="primary")["mons"][0])


def hello_ot(case):
    return int.from_bytes(_saved_field((ROOT / f"tests/fixtures/gen2/{case}.SaveRAM").read_bytes()[:oracles.CARTRAM_BYTES],
                                       codec.for_foundation("crystal"), "wPlayerID", 2), "big")


def marker_text(path, cart, *, case, title, key, species, level, ot_id, starter, pre=None, flip=None):
    j = json.dumps
    duo = {"player": "a", "scenario": "ball_gate", "attempt": 1, "case": case, "title": title,
           "rom_sha1": "deadbeef" * 5,
           "fixture_sha256": hashlib.sha256((ROOT / f"tests/fixtures/gen2/{case}.SaveRAM").read_bytes()).hexdigest()}
    witness = {"frame": 22000, "save_completed_frame": 21900, "gate_saves": 1, "client_saves": 1,
               "cartram_sha256": hashlib.sha256(cart).hexdigest(), "cartram_bytes": len(cart),
               "saveram_path": str(path), "saveram_bytes": len(cart) + 22, "flushed_matches": True}
    client = {"qualification": "PASS", "production_admitted": True, "pack": f"gen2_{title}", "title": title,
              "rom_sha1": "deadbeef" * 5}
    lines = [f"DUO_GEN2 {j(duo)}", f"CLIENT {j(client)}",
             f"HELLO {j({'frame': 310, 'ot_id': ot_id, 'has_pokeballs': False, 'ball_count': 0})}",
             "BALL_PRE " + j(pre or {"frame": 2000, "foe": 16, "area_id": "route_29", "has_pokeballs": False,
                                     "ball_count": 0}),
             "ENGINE_FAINT " + j({"frame": 9000, "site_id": "battle_faint", "cause": "battle", "key": starter,
                                  "slot": 0}),
             "FAINT_SENT " + j({"frame": 9010, "key": starter, "seq": 4}),
             "BALL_FLIP " + j(flip or {"frame": 20000, "has_pokeballs": True, "ball_count": 5, "gave_egg": True}),
             "ENGINE_CAPTURE " + j({"frame": 21000, "site_id": "capture_party_finalized", "acquisition": "wild",
                                    "area_id": "route_29", "destination": "party", "slot": 1, "key": key,
                                    "species_id": species, "level": level}),
             f"CAUGHT {key}", f"SAVE_WITNESS {j(witness)}", f"RESULT: PASS (caught {key})"]
    return "\n".join(lines)


@pytest.fixture
def ball_case(tmp_path):
    layout = codec.for_foundation("crystal")
    results, decoded, starters = {}, {}, {}
    for inst, species, balls in (("a", 16, 4), ("b", 19, 3)):
        case, title = TOWN[inst]
        ot_id = hello_ot(case)
        save, mon = natural_capture(layout, case, species=species, balls=balls, ot_id=ot_id)
        path = tmp_path / f"{inst}.SaveRAM"
        path.write_bytes(save)
        starters[inst] = starter_key(layout, case)
        results[inst] = marker_text(path, save[:oracles.CARTRAM_BYTES], case=case, title=title, key=codec.key(mon),
                                    species=species, level=mon["level"], ot_id=ot_id, starter=starters[inst])
        decoded[inst] = {"key": codec.key(mon), "species": species, "level": mon["level"]}
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "links.json").write_text(json.dumps({
        "links": [{"area_id": "route_29", "status": "alive", "a": decoded["a"], "b": decoded["b"]}],
        "area_states": {"route_29": "linked"}, "pokeballs_obtained": {"a": True, "b": True}}), encoding="utf-8")
    log = "".join(f"INFO [{inst}] faint key={starters[inst]} area='cherrygrove_city'\n" for inst in ("a", "b"))
    (data / "slink.log").write_text(log, encoding="utf-8")
    return results, data, decoded, starters, tmp_path


def run_oracle(ball_case):
    results, data, *_ = ball_case
    return oracles.ball_gate_oracle(results, data_dir=str(data))


def test_ball_gate_oracle_passes(ball_case):
    facts = []
    results, data, *_ = ball_case
    assert oracles.ball_gate_oracle(results, data_dir=str(data), on_verified=facts.append) is None
    assert facts and facts[0]["area"] == "route_29" and facts[0]["status"] == "alive"


def _rewrite_links(data, **changes):
    doc = json.loads((data / "links.json").read_text(encoding="utf-8"))
    doc.update(changes)
    (data / "links.json").write_text(json.dumps(doc), encoding="utf-8")


def test_oracle_refuses_a_closed_server_gate(ball_case):
    _rewrite_links(ball_case[1], pokeballs_obtained={"a": True, "b": False})
    with pytest.raises(RuntimeError, match="pokeballs_obtained"):
        run_oracle(ball_case)


def test_oracle_refuses_a_second_link(ball_case):
    doc = json.loads((ball_case[1] / "links.json").read_text(encoding="utf-8"))
    doc["links"].append({"area_id": "route_30", "status": "dead", "a": {"key": "x"}, "b": {"key": "y"}})
    (ball_case[1] / "links.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeError, match="one link"):
        run_oracle(ball_case)


def test_oracle_refuses_a_missing_server_faint(ball_case):
    log = ball_case[1] / "slink.log"
    log.write_text(log.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="faint"):
        run_oracle(ball_case)


def test_oracle_refuses_a_death_command(ball_case):
    log = ball_case[1] / "slink.log"
    log.write_text(log.read_text(encoding="utf-8") + "INFO [a] faint → force_faint b:X\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="death command"):
        run_oracle(ball_case)


def test_oracle_refuses_a_battle_fixture_start(ball_case):
    results = dict(ball_case[0])
    results["a"] = results["a"].replace('"case": "crystal_town"', '"case": "crystal_battle"')
    with pytest.raises(RuntimeError):
        oracles.ball_gate_oracle(results, data_dir=str(ball_case[1]))


def test_oracle_refuses_an_o10_sized_pocket(ball_case, tmp_path):
    layout = codec.for_foundation("crystal")
    results, data, decoded, starters, _ = ball_case
    case, title = TOWN["a"]
    ot_id = hello_ot(case)
    save, mon = natural_capture(layout, case, species=16, balls=14, ot_id=ot_id)
    path = tmp_path / "a14.SaveRAM"
    path.write_bytes(save)
    results = dict(results)
    results["a"] = marker_text(path, save[:oracles.CARTRAM_BYTES], case=case, title=title, key=codec.key(mon),
                               species=16, level=mon["level"], ot_id=ot_id, starter=starters["a"])
    with pytest.raises(RuntimeError, match="natural"):
        oracles.ball_gate_oracle(results, data_dir=str(data))


def test_oracle_refuses_a_faint_of_another_key(ball_case):
    results = dict(ball_case[0])
    starter = ball_case[3]["a"]
    results["a"] = results["a"].replace('"key": "' + starter + '", "slot": 0', '"key": "0000:0000:01", "slot": 0')
    with pytest.raises(RuntimeError, match="starter"):
        oracles.ball_gate_oracle(results, data_dir=str(ball_case[1]))


# --- the shared gate admits a town case with errand facts only for the ball gate ------------------------------

def gate_inputs(**case_changes):
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().SLINK_GEN2_GATE_LIBRARY = True
    G = runtime.execute((ROOT / "lua/tests/test_gen2_scripted_gate.lua").read_text(encoding="utf-8"))
    json_codec = runtime.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    facts = errand_facts()
    case = {**vars(g.BY_NAME["crystal_town"]), "attempt_id": "model-1", "max_frames": 20000,
            "max_phase_frames": 8000, "settle_frames": 30}
    case.update(case_changes)
    env = {"SLINK_ROOT": str(ROOT), "SLINK_GEN2_TITLE": TITLE, "SLINK_GEN2_ROM_SHA1": facts["rom_sha1"],
           "SLINK_GEN2_CORE_MODE": "CGB", "SLINK_GEN2_COLD": "1", "SLINK_GEN2_SAVERAM_DIR": "x",
           "SLINK_GEN2_SAVERAM_NAME": "x.SaveRAM", "SLINK_GEN2_FIXTURE_CASE": json.dumps(case),
           "SLINK_GEN2_ROUTE_FACTS": json.dumps(facts)}
    return G.inputs(lambda name: env.get(name), json_codec)


def test_the_gate_admits_the_ball_gate_town_case_with_errand_facts():
    assert gate_inputs(ball_gate=True).case.name == "crystal_town"


def test_the_gate_still_refuses_errand_facts_on_a_plain_town_case():
    with pytest.raises(LuaError, match="fixture case name mismatch|errand ends as a battle fixture"):
        gate_inputs()
