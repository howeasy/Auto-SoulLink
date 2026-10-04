"""Run the real board preview and its compiled engine against all occupied move slots.

Node/compiled calculator prerequisites follow test_calc_bundle.py. These are MODEL
replays; they do not stage game data or claim emulator qualification.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

HARNESS = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const root = process.argv[1], cases = JSON.parse(process.argv[2]);
let payload = cases[0];
const div = {style: {}, innerHTML: '', getAttribute: k => (
  {'data-in-battle': payload.in_battle === false ? null : '1',
   'data-calc': JSON.stringify(payload)}[k] || null)};
const ctx = {console, location: {pathname: '/'}}; ctx.window = ctx;
ctx.document = {
  querySelector: () => div,
  getElementById: id => id === 'calc-preview-a' ? div : null,
  createElement: () => ({}),
  head: {appendChild(s) {
    const file = path.join(root, 'calc/dist', s.src.replace('/calc/', ''));
    vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
    s.onload();
  }},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root, 'server/static/calc-preview.js'), 'utf8'), ctx);
const calculate = ctx.calc.calculate;
ctx.calc.calculate = function(gen, attacker, defender, move, field) {
  if (move.name === payload.fail_move) throw new Error('forced calculation failure');
  return calculate(gen, attacker, defender, move, field);
};
const output = [];
for (payload of cases) {
  ctx._slinkCalcRender();
  const gen = ctx.calc.Generations.get(payload.gen);
  const attacker = new ctx.calc.Pokemon(gen, payload.player_species, {level: payload.player_level});
  const defender = new ctx.calc.Pokemon(gen, payload.enemy_species, {level: payload.enemy_level});
  const reference = payload.player_moves.filter(Boolean).map(name => {
    try {
      const move = new ctx.calc.Move(gen, name);
      const result = calculate(gen, attacker, defender, move, new ctx.calc.Field());
      return {name, category: move.category, range: result.range(), maxHP: defender.maxHP()};
    } catch (e) { return {name, error: e.message}; }
  });
  output.push({html: div.innerHTML, display: div.style.display, reference});
}
console.log(JSON.stringify(output));
"""


class Rows(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag == "td":
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag == "td":
            self.row.append(self.cell)
            self.cell = None
        if tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = None


def replay(*cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not found on PATH")
    src = (REPO / "server/static/calc-preview.js").read_text(encoding="utf-8")
    paths = re.findall(r"'(calc/[^']+|js/data/sets/[^']+)'", src)
    missing = [p for p in paths if not (REPO / "calc/dist" / p).is_file()]
    if missing:
        pytest.skip(f"calc/dist not built - missing {missing[0]} - run npm run build in calc/")
    result = subprocess.run([node, "-e", HARNESS, str(REPO), json.dumps(cases)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def matchup(gen=1, dex="purergb", moves=None, enemy="Raticate"):
    return {"gen": gen, "dex": dex, "player_species": "Pikachu", "player_level": 50,
            "player_moves": moves or ["Thunderbolt", "Quick Attack", "Body Slam", "Mega Punch"],
            "enemy_species": enemy, "enemy_level": 50}


@pytest.mark.parametrize("gen,dex", [(1, "purergb"), (3, "vanilla")])
def test_four_damaging_slots_match_real_engine(gen, dex):
    c = matchup(gen, dex)
    out = replay(c)[0]
    rows = Rows(out["html"]).rows
    assert [r[0] for r in rows] == c["player_moves"]
    for row, ref in zip(rows, out["reference"], strict=True):
        lo, hi = [round(n / ref["maxHP"] * 100, 1) for n in ref["range"]]
        assert [float(n) for n in row[1].removesuffix("%").split("–")] == [lo, hi]
    assert out["display"] == ""


@pytest.mark.parametrize("gen,dex", [(1, "purergb"), (3, "vanilla")])
def test_one_damaging_move_keeps_other_three_status_slots(gen, dex):
    c = matchup(gen, dex, ["Thunderbolt", "Growl", "Thunder Wave", "Tail Whip"])
    out = replay(c)[0]
    rows = Rows(out["html"]).rows
    assert [r[0] for r in rows] == c["player_moves"], rows
    assert [r[1] for r in rows[1:]] == ["Status"] * 3
    assert [r[2] for r in rows[1:]] == [""] * 3


def test_status_only_moves_keep_the_preview_visible():
    c = matchup(moves=["Growl", "Thunder Wave", "Tail Whip", "Agility"])
    out = replay(c)[0]
    rows = Rows(out["html"]).rows
    assert [r[0] for r in rows] == c["player_moves"]
    assert [r[1:] for r in rows] == [["Status", ""]] * 4
    assert out["display"] == ""


@pytest.mark.parametrize("gen,dex", [(1, "purergb"), (3, "vanilla")])
def test_immunity_status_and_empty_slot_are_distinct(gen, dex):
    c = matchup(gen, dex, ["Thunderbolt", "Quick Attack", "Growl", ""], enemy="Gengar")
    out = replay(c)[0]
    rows = Rows(out["html"]).rows
    assert [r[0] for r in rows] == c["player_moves"][:3], rows
    assert rows[1][1:] == ["0–0%", ""]
    assert rows[2][1:] == ["Status", ""]


def test_unsupported_move_stays_visible_as_unavailable():
    c = matchup(moves=["Thunderbolt", "Not a Move", "Growl", "Quick Attack"])
    out = replay(c)[0]
    rows = Rows(out["html"]).rows
    assert [r[0] for r in rows] == c["player_moves"], rows
    assert rows[1][1:] == ["Unavailable", ""]


def test_engine_error_does_not_hide_valid_slot_or_claim_zero_damage():
    c = {**matchup(), "fail_move": "Body Slam"}
    rows = Rows(replay(c)[0]["html"]).rows
    assert [r[0] for r in rows] == c["player_moves"]
    assert rows[2][1:] == ["Unavailable", ""]
    assert "%" in rows[0][1] and "%" in rows[1][1] and "%" in rows[3][1]


def test_poll_replaces_four_slot_rows_without_stale_status_or_zero_damage():
    cases = [matchup(moves=["Thunderbolt", "Growl", "Thunder Wave", "Tail Whip"]),
             matchup(3, "vanilla", ["Thunderbolt", "Quick Attack", "Growl", ""], "Gengar"),
             matchup()]
    for c, out in zip(cases, replay(*cases), strict=True):
        assert [r[0] for r in Rows(out["html"]).rows] == list(filter(None, c["player_moves"]))


def test_battle_exit_hides_and_reentry_refreshes_all_move_rows():
    cases = [matchup(moves=["Growl", "Thunder Wave", "Tail Whip", "Agility"]),
             {**matchup(), "in_battle": False}, matchup()]
    out = replay(*cases)
    assert out[0]["display"] == "" and out[1]["display"] == "none"
    assert out[2]["display"] == ""
    assert [r[0] for r in Rows(out[2]["html"]).rows] == cases[2]["player_moves"]


@pytest.mark.asyncio
async def test_purergb_wire_move_ids_reach_rendered_board_and_all_four_rows(tmp_path):
    """Real adapter -> _calc_preview -> HTML attribute -> real JS/engine replay."""
    from aiohttp.test_utils import TestClient, TestServer

    from server.adapters.gen1_purergb import Gen1PureRGBAdapter
    from server.server import SLinkServer, build_app
    from tests.unit.populated_server import populate

    srv = SLinkServer(data_dir=str(tmp_path))
    close = await populate(srv, "gen1")
    adapter = srv._player_adapters["b"] = Gen1PureRGBAdapter(
        rom_type="PureRed", artifact_kind="rand_overlay")
    names = ["Thunderbolt", "Growl", "Thunder Wave", "Tail Whip"]
    move_ids = [next(i for i in range(1, 256) if adapter.move_name(i) == name) for name in names]
    def species_id(name):
        return next(i for i in range(1, 256) if adapter.calc_species(i) == name)

    active = next(d for d in srv.party_details["b"].values() if d.get("active"))
    active.update(species_id=species_id("Pikachu"), moves=move_ids, level=50)
    foe = srv.battle_state["b"]["enemy_party"][0]
    foe.update(species_id=species_id("Raticate"), level=50)
    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    try:
        body = await (await client.get("/")).text()
    finally:
        await client.close()
        await close()

    class Board(HTMLParser):
        calc = None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if a.get("id") == "calc-preview-b":
                self.calc = json.loads(a["data-calc"])

    board = Board()
    board.feed(body)
    assert board.calc is not None, "PureRGB battle missing rendered preview"
    assert board.calc["gen"] == 1 and board.calc["dex"] == "purergb"
    assert board.calc["player_moves"] == names
    rows = Rows(replay(board.calc)[0]["html"]).rows
    assert [r[0] for r in rows] == names
    assert [r[1] for r in rows[1:]] == ["Status"] * 3
