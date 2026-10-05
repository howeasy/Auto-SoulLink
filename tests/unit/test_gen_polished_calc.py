"""tests/unit/test_gen_polished_calc.py -- Polished Crystal's damage-calculator dataset.

Covers the four things that can silently be wrong with a calculator dataset:

1. the generated file is exactly what its generator produces (determinism + `--check` freshness);
2. every id the server can send reaches a row in the dataset -- all 289 species and all 46 variant
   BaseData records the wire hands over as an EFFECTIVE species id (292..337);
3. the data is Polished's, not the calc's gen 3 dex it replaces -- Alolan Rattata is Dark/Normal
   with its own base stats, plain Rattata is Normal, the type chart carries a Fairy type and the
   Dark/Steel pairings Polished changed;
4. the damage the dataset feeds comes out where the cartridge's own arithmetic says it should,
   with the arithmetic written out (see test_hand_computed_damage_matches_the_cartridge).

`docs/polished/CALC.md` is the prose half: what is modelled, what is approximated, what is
unverified. Anything this file cannot check is listed there rather than assumed here.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

pytest_plugins = ["tests.unit.manager_harness"]

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

PACK = ROOT / "data" / "games" / "polished_crystal"
DATASET = ROOT / "calc" / "src" / "calc" / "data" / "polished.js"
POLISHED_SRC = Path(os.environ.get("POLISHED_SRC")
                    or Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache" / "polished" / "src")

needs_source = pytest.mark.skipif(
    not (POLISHED_SRC / "constants" / "type_constants.asm").is_file(),
    reason=f"pinned polishedcrystal checkout missing ({POLISHED_SRC})")


def _pack(name: str) -> dict:
    return json.loads((PACK / f"{name}.json").read_text(encoding="utf-8"))


def to_id(name: str) -> str:
    """The calc's own id scheme (calc/calc/src/util.ts toID), which is what every lookup uses."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _bs(base_stats: dict) -> dict:
    """The pack's six base stats in the calc's SpeciesData.bs shape."""
    return {"hp": base_stats["hp"], "at": base_stats["attack"], "df": base_stats["defense"],
            "sa": base_stats["special_attack"], "sd": base_stats["special_defense"],
            "sp": base_stats["speed"]}


@pytest.fixture(scope="module")
def adapter():
    from server.adapters.gen2_polished import Gen2PolishedAdapter

    return Gen2PolishedAdapter()


def _dataset_text() -> str:
    if not DATASET.is_file():
        pytest.fail(f"{DATASET} is missing -- run `python tools/gen_polished_calc.py`")
    return DATASET.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dataset() -> dict:
    """The generated file's tables, parsed back out of the JavaScript.

    Parsed rather than imported because the file is a page-side CommonJS module, not a Python one.
    This is the same "read what the browser will read" discipline tests/unit/test_calc_purergb.py
    uses on purergb.ts.
    """
    text = _dataset_text()

    def block(name: str) -> dict:
        match = re.search(rf"var {name} = \{{(.*?)\n\}};", text, re.S)
        assert match, f"{DATASET.name}: no {name} table"
        return json.loads("{" + match.group(1) + "}")

    return {"species": block("POLISHED_SPECIES"), "moves": block("POLISHED_MOVES"),
            "types": block("POLISHED_TYPE_CHART")}


# ── 1. the generator ─────────────────────────────────────────────────────────────────────────

@needs_source
def test_the_committed_dataset_is_exactly_what_the_generator_produces():
    """Red control: hand-edit one byte of calc/src/calc/data/polished.js.

    Also asserts determinism directly -- two builds of the same packs must be byte-identical, so a
    dict iteration order or a set ever creeping into the output fails here rather than on the next
    unrelated diff.
    """
    from tools import gen_polished_calc as gen

    first = gen.generate(POLISHED_SRC)
    assert first == gen.generate(POLISHED_SRC)
    assert DATASET.is_file(), f"{DATASET} is missing -- run `python tools/gen_polished_calc.py`"
    with DATASET.open(encoding="utf-8", newline="") as stream:
        assert stream.read() == first, f"{DATASET.name} is stale -- rerun tools/gen_polished_calc.py"


@needs_source
def test_check_mode_passes_on_a_fresh_tree_and_fails_on_a_stale_one(monkeypatch):
    """`--check` is the gate the tool's own docstring promises; neither leg may be decorative."""
    from tools import gen_polished_calc as gen

    monkeypatch.setattr(sys, "argv", ["gen_polished_calc.py", "--check"])
    assert gen.main() == 0

    monkeypatch.setattr(gen, "generate", lambda *_a, **_k: _dataset_text() + "// drift\n")
    assert gen.main() == 1


def test_the_adapter_and_the_generator_agree_on_the_species_spelling():
    """The server and the dataset must spell a species the same way.

    server/adapters/gen2_polished.py's CALC_SPECIES_FIXUPS is a hand copy of the generator's
    SPECIES_FIXUPS; if either drifts, the calc silently falls back to the vanilla gen 3 dex for
    that species and nobody finds out until the damage is wrong.
    """
    from server.adapters.gen2_polished import CALC_SPECIES_FIXUPS
    from tools.gen_polished_calc import SPECIES_FIXUPS

    assert CALC_SPECIES_FIXUPS == SPECIES_FIXUPS


# ── 2. the id round-trip ──────────────────────────────────────────────────────────────────────

def test_every_species_and_variant_the_wire_can_send_has_a_dataset_row(dataset, adapter):
    """Both halves of the wire, checked against the dataset the page loads.

    A plain species carries its 9-bit id; a variant form carries its BaseData RECORD index as the
    effective id (lua/gen2/polished.lua `effective()`/common(), server/adapters/gen2_polished.py
    decode_party_blob). Both must land on a key the calc resolves by toID().
    """
    index = _pack("species_index")
    forms = json.loads((PACK / "forms_index.json").read_text(encoding="utf-8"))
    keys = {to_id(key) for key in dataset["species"]}

    for sid in sorted(index["species"], key=int):
        assert to_id(adapter.calc_species(int(sid))) in keys, sid
    for row in forms["variant_forms"]:
        assert to_id(adapter.calc_species(row["record_index"])) in keys, row

    assert len(dataset["species"]) == index["constants"]["NUM_POKEMON"] + forms["counts"]["variant_records"]


def test_a_variant_keys_by_base_and_form_and_a_cosmetic_form_folds_into_its_base(dataset, adapter):
    """Owner ruling 2026-10-04: a regional form is a different mon, a cosmetic form is the same
    one. So the dataset carries "<base>-<form>" rows for variants and nothing extra for Unown
    letters / Magikarp patterns -- which is what keeps 46 variants from becoming 148 rows.
    """
    from server.adapters import polished_codec

    assert adapter.calc_species(19) == "Rattata"
    assert adapter.calc_species(295) == "Rattata-Alolan"

    cosmetic = next(row for row in _pack("species_index")["forms"]
                    if row["kind"] == "cosmetic" and row["species"] == 201)
    assert polished_codec.effective_species(cosmetic["species"], cosmetic["form"]) == 201, \
        "a cosmetic form must never reach the wire as its own species id"
    assert adapter.calc_species(201) == "Unown"

    keys = {to_id(key) for key in dataset["species"]}
    assert "rattataalolan" in keys and "rattata" in keys
    assert not any(key.startswith("unown") and key != "unown" for key in keys)


# ── 3. it is Polished's data, not the calc's gen 3 dex it replaces ───────────────────────────

def test_alolan_rattata_is_dark_normal_with_its_own_stats_while_rattata_is_plain(dataset, adapter):
    """The card's headline case.

    Polished's Alolan Rattata is Dark/Normal (data/games/polished_crystal/species_index.json, the
    ALOLAN_FORM row) with the SAME 30/56/35/72/25/35 stats as plain Normal Rattata, as in gen 7.
    They must still be two rows -- one row would let a type chart read the wrong mon's types.
    """
    index = _pack("species_index")
    alolan = next(row for row in index["forms"]
                  if row.get("kind") == "variant" and row["ext"] == 295)
    plain = index["species"]["19"]

    assert plain["types"] == ["NORMAL", "NORMAL"]      # the pack repeats a mono-type's slot ...
    assert alolan["types"] == ["DARK", "NORMAL"]
    # Alolan Rattata's stats equal plain Rattata's in the source (as in gen 7): only the types differ.
    assert plain["base_stats"] == alolan["base_stats"]

    assert dataset["species"]["Rattata"]["types"] == ["Normal"]   # ... the dataset must not (gen3.ts squares a repeat)
    assert dataset["species"]["Rattata"]["bs"] == _bs(plain["base_stats"])
    assert dataset["species"]["Rattata-Alolan"]["types"] == ["Dark", "Normal"]
    assert dataset["species"]["Rattata-Alolan"]["bs"] == {"hp": 30, "at": 56, "df": 35,
                                                          "sa": 25, "sd": 35, "sp": 72}
    assert dataset["species"]["Rattata"]["types"] != dataset["species"]["Rattata-Alolan"]["types"]


def test_no_species_repeats_a_type_slot(dataset):
    """gen3.ts multiplies BOTH defender type slots (equal types only skip its precedence swap),
    so a mono-type mon stored as [T, T] takes every hit squared (probe: Karate
    Chop into Rattata would read 4x, not 2x). The pack stores [T, T]; the dataset must not."""
    for name, row in dataset["species"].items():
        assert row["types"] and len(set(row["types"])) == len(row["types"]), f"{name}: {row['types']}"


def test_the_type_chart_is_polisheds_own_not_the_calcs_gen3_chart(dataset):
    """Fairy exists in Polished (constants/type_constants.asm:25 `const FAIRY ; 11`) and in no
    gen 3 chart, and Polished drops the Steel resistances to Dark and Ghost that every other
    generation carries. Both would resolve against the vanilla chart if the swap were missing.
    """
    chart = dataset["types"]
    assert set(chart) == {"Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost",
                          "Steel", "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon",
                          "Dark", "Fairy", "???"}
    assert chart["Fairy"]["Dragon"] == 2
    assert chart["Dragon"]["Fairy"] == 0
    assert chart["Steel"]["Fairy"] == 2
    assert chart["Fairy"]["Steel"] == 0.5
    assert chart["Fairy"]["Fire"] == 0.5
    assert chart["Fairy"]["Fighting"] == 2
    assert chart["Dark"]["Steel"] == 1, "no Dark->Steel row in type_matchups.asm: Polished dropped it"
    assert chart["Steel"]["Dark"] == 1, "and the Ghost/Dark pairing the other way"
    assert chart["Fighting"]["Fairy"] == 0.5
    assert chart["???"]["Dark"] == 1
    assert chart["Fairy"]["Fairy"] == 1, "no FAIRY,FAIRY row in type_matchups.asm"


def test_every_move_carries_polisheds_own_split(dataset):
    """`category` is not cosmetic at gen 3: calc/calc/src/move.ts:127 derives Physical/Special from
    the move's TYPE when the data omits it (that is how gen 1/2 work), so a Psychic-type Physical
    move would be read as Special and the move would attack the wrong stat.
    """
    moves = _pack("moves")["moves"]
    assert moves, "the pack has no moves"
    for move in moves:
        row = dataset["moves"].get(move["name"])
        assert row is not None, f"move {move['id']} {move['name']} has no dataset row"
        assert row["category"] == move["split"], move["name"]
        assert row["type"] in dataset["types"], (move["name"], row["type"])
    assert len(dataset["moves"]) == len(moves)


def test_every_move_and_species_id_is_unique_once_reduced_to_a_calc_id(dataset):
    """toID() is the calc's lookup key, so two names reducing to one id are two entries the
    calculator cannot tell apart -- the same failure mode as pureRGB's Night Shade / Sonic Boom.
    """
    for kind in ("species", "moves"):
        ids = [to_id(key) for key in dataset[kind]]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        assert not duplicated, (kind, duplicated)


def test_the_dataset_lists_every_held_item_the_adapter_would_send(dataset, adapter):
    """Items are listed, not installed (CALC.md §4), but the list must still cover the inventory
    the server can hand the calc -- a held item missing from it would be invisible.
    """
    from tools.gen_polished_calc import abilities, held_items, load_pack

    text = _dataset_text()
    names = json.loads(re.search(r"var POLISHED_ITEMS = (\[.*?\]);", text, re.S).group(1))
    for item_id in range(1, 255):
        if adapter.is_valid_held_item(item_id):
            assert adapter.item_name(item_id) in names, (item_id, adapter.item_name(item_id))
    assert names == held_items(load_pack("items"))

    ability_names = json.loads(re.search(r"var POLISHED_ABILITIES = (\[.*?\]);", text, re.S).group(1))
    assert ability_names == abilities(load_pack("species_index"))
    assert "Overgrow" in ability_names and "Gluttony" in ability_names


# ── 4. the damage, computed by hand from the cartridge's own source ─────────────────────────

def _cartridge_stat(base: int, dv: int, ev: int, level: int) -> int:
    """CalcPkmnStatC without its nature pass (a neutral nature multiplies by 10/10).

    engine/pokemon/mon_stats.asm:763-836 -- pokecrystal's own formula with EVs in the stat-exp
    slot: de = (base + DV) * 2 + 1 + floor(EV/4); stat = floor(de * level / 100) + STAT_MIN_NORMAL
    (5, constants/battle_constants.asm:81). NOT the modern 2*base + IV one, which is exactly why
    calc_stats() hands the engine IV = 2*DV + 1 (DV 0 -> 1, DV 15 -> 31, still inside 0..31).
    """
    return ((base + dv) * 2 + 1 + ev // 4) * level // 100 + 5


def _cartridge_max_hp(base: int, dv: int, ev: int, level: int) -> int:
    """CalcPkmnStatC's HP branch: the same quotient, plus the level, plus STAT_MIN_HP 10."""
    return ((base + dv) * 2 + 1 + ev // 4) * level // 100 + level + 10


def test_hand_computed_damage_matches_the_cartridge():
    """Bulbasaur L50, Acrobatics (55 BP, Flying, Physical) into Bulbasaur L50.
    Both mons: every DV 15, every EV 0, neutral nature, no item, no ability, no status, no boosts,
    no weather, no critical.

    Stats -- engine/pokemon/mon_stats.asm CalcPkmnStatC (pokecrystal's formula with EVs in the
    stat-exp slot):
        Attack  = floor(((49 + 15) * 2 + 1 + 0) * 50 / 100) + 5 = floor(64.5) + 5 = 69
        Defense = 69 (same formula)
        Max HP  = floor(((45 + 15) * 2 + 1 + 0) * 50 / 100) + 50 + 10 = 60 + 60 = 120

    Damage -- engine/battle/effect_commands.asm:
        DamagePass1  floor((2*50)/5) + 2                 = 22
        DamagePass2  22 * 55 * 69                         = 83490
        DamagePass3  83490 / 69 / 50                     = 24
        DamagePass4  24 + 2                              = 26
        BattleCommand_stab: no STAB (Flying vs Grass/Poison). Flying->Grass is 2 and
        Flying->Poison is 1 (data/types/type_matchups.asm:71-72), so 26 * $20 / $10 = 52.
        BattleCommand_damagevariation: floor(52 * r / 100), r in 85..100 -> 44..52.

    The same chain through calc/calc/src/mechanics/gen3.ts's calculateADV: baseDamage
    floor(floor(22 * 69 * 55) / 69) / 50 = 24, +2 = 26, no STAB, x2 -> 52, then
    `for (i = 85; i <= 100; i++) result.damage[i-85] = max(1, floor(52 * i / 100))`. Identical --
    which is the whole reason Polished runs at calc gen 3 and not gen 2, whose roll is 217..255/255
    and whose crit is x2 while the cartridge's crit is x1.5 (docs/polished/CALC.md §4).
    """
    assert (_cartridge_stat(49, 15, 0, 50), _cartridge_stat(49, 15, 0, 50)) == (69, 69)
    assert _cartridge_stat(65, 15, 0, 50) == 85        # SpA / SpD, the modern split
    assert _cartridge_max_hp(45, 15, 0, 50) == 120

    attack = _cartridge_stat(49, 15, 0, 50)
    defense = _cartridge_stat(49, 15, 0, 50)
    base = (2 * 50) // 5 + 2                           # DamagePass1
    base = base * 55 * attack                          # DamagePass2
    base = base // defense // 50                       # DamagePass3
    assert base == 24
    base += 2                                          # DamagePass4
    assert base == 26
    assert base * 0x20 // 0x10 == 52                   # BattleCommand_stab: 26 * 32 / 16 = 52 (2x)
    rolls = [max(1, 52 * r // 100) for r in range(85, 101)]
    assert (rolls[0], rolls[-1]) == (44, 52)


def test_calc_stats_round_trips_a_real_party_blob(adapter):
    """The player's mon reaches the calc through the 70-byte party blob the client sends
    (lua/gen2/polished.lua P.party_entry). Decoded values must be the cartridge's own arithmetic:
    every DV 15, every EV 0, neutral nature, level 50, species 1 (Bulbasaur).
    """
    from server.adapters import polished_codec

    dvs = dict.fromkeys(("hp", "attack", "defense", "speed", "special_attack", "special_defense"), 15)
    blob = polished_codec.encode_party_blob(_blob_mon(dvs)).hex()
    stats = adapter.calc_stats({"blob_hex": blob, "level": 50})

    assert stats is not None
    # DV 15 -> IV 31: the encoding that makes the calc's 2*base + IV reproduce Crystal's
    # 2*(base + DV) + 1 (see calc_stats' docstring).
    assert stats["ivs"] == {"hp": 31, "atk": 31, "df": 31, "spa": 31, "spd": 31, "spe": 31}
    assert stats["evs"] == {"hp": 0, "atk": 0, "df": 0, "spa": 0, "spd": 0, "spe": 0}
    assert stats["stats"] == {"hp": _cartridge_max_hp(45, 15, 0, 50),
                              "atk": _cartridge_stat(49, 15, 0, 50),
                              "df": _cartridge_stat(49, 15, 0, 50),
                              "spa": _cartridge_stat(65, 15, 0, 50),
                              "spd": _cartridge_stat(65, 15, 0, 50),
                              "spe": _cartridge_stat(45, 15, 0, 50)}


def test_calc_stats_refuses_anything_it_cannot_decode(adapter):
    """Untrusted client input: a missing, short or malformed blob must return None, never raise."""
    for detail in ({}, {"blob_hex": ""}, {"blob_hex": "zz"}, {"blob_hex": "00" * 140, "level": 50},
                   {"blob_hex": "00" * 140, "level": 0}, {"blob_hex": "00" * 140}):
        assert adapter.calc_stats(detail) is None, detail


def _blob_mon(dvs: dict) -> dict:
    from server.adapters import polished_codec

    return {
        "species_id": 1, "form": 0, "gender": "male", "is_egg": False, "shiny": False,
        "ability_slot": 0, "nature": 0, "held_item": 0, "moves": [0, 0, 0, 0], "ot_id": 0x1234,
        "exp": 100000, "evs": dict.fromkeys(dvs, 0), "dvs": dvs, "level": 50,
        "hp": 100, "max_hp": 112, "pp": [10, 10, 10, 10], "pp_ups": [0, 0, 0, 0],
        "happiness": 70, "pokerus": 0, "caught_data": 0, "caught_level": 5,
        "caught_location": 0, "status": 0, "unused": 0,
        "stats": {"attack": 69, "defense": 69, "speed": 65,
                  "special_attack": 85, "special_defense": 85},
        "ot_raw_hex": "00" * polished_codec.NAME_SIZE,
        "nickname_raw_hex": "00" * polished_codec.NICKNAME_SIZE,
    }


# ── 5. the option the Manager offers ──────────────────────────────────────────────────────────

def test_the_managers_battle_calc_row_and_the_adapter_agree(adapter):
    """The Manager's table is hand-written; the adapter is the truth. A run must not be offered a
    calculator the adapter has nothing for, or refused one it has.
    """
    from server.manager import option_support

    assert option_support("battle_calc", ["polished_crystal"])["ok"] is True
    assert adapter.calc_profile() == {"name": "Polished Crystal", "gen": 3, "dex": "polished"}
    assert adapter.supports_abilities() is False, "the wire carries no ability slot; see CALC.md §4"


def test_the_page_loads_the_dataset_in_the_same_place_the_preview_does():
    """The preview's engine list and the full page's script list must agree, or the board and the
    full calculator load different engines. Same shape as test_calc_preview.py's own check.
    """
    preview = (ROOT / "server" / "static" / "calc-preview.js").read_text(encoding="utf-8")
    engine = re.findall(r"'([^']+)'", re.search(r"var ENGINE\s*=\s*\[(.*?)\];", preview, re.S).group(1))
    assert "calc/data/purergb.js" in engine, "the preview's engine list no longer parses"
    assert "calc/data/polished.js" in engine
    for page in ("normal", "hardcore"):
        template = (ROOT / "calc" / "src" / f"{page}.template.html").read_text(encoding="utf-8")
        scripts = re.findall(r'src="\./(calc/[^"?]+)\?', template)
        assert scripts, page
        assert scripts == engine, page

    bridge = (ROOT / "calc" / "src" / "js" / "slink_bridge.js").read_text(encoding="utf-8")
    assert "calc.usePolished(_dex === 'polished')" in bridge, "the full page never selects the dex"
    assert "window.calc.usePolished(c.dex === 'polished')" in preview, "nor the board preview"


@pytest.mark.asyncio
async def test_the_real_manager_serves_the_dataset_on_every_path_the_page_asks_for(manager_client, manager_dir):
    """The board preview asks /calc/calc/data/polished.js; the full page, wrapped under a run, asks
    /runs/<id>/calc/calc/data/polished.js. Both must be the committed file (calc/src wins over
    calc/dist, server/calc_files.py), served as JavaScript -- a 404 here is a calculator that
    silently shows nothing for Polished."""
    from tests.unit.test_manager_pages import _stopped_run
    _stopped_run(manager_dir)
    want = DATASET.read_bytes()
    for path in ("/calc/calc/data/polished.js", "/runs/run_1/calc/calc/data/polished.js"):
        resp = await manager_client.get(path)
        assert resp.status == 200, path
        assert "javascript" in resp.headers["Content-Type"], path
        assert await resp.read() == want, path


# ── 5. the engine itself ─────────────────────────────────────────────────────────────────────

def test_the_engines_gen3_roll_is_the_cartridges_85_to_100():
    """effect_commands.asm:1894 rolls 85 + BattleRandomRange(16) over 100. calculateADV's loop is
    the only place the calculator quantises the roll, so a one-character edit to it is a silent
    wrong-damage bug; this fails on it without needing a build."""
    gen3 = (ROOT / "calc" / "calc" / "src" / "mechanics" / "gen3.ts").read_text(encoding="utf-8")
    assert re.search(r"for \(let i = 85; i <= 100; i\+\+\) \{\s*result\.damage\[i - 85\] = "
                     r"Math\.max\(1, Math\.floor\(\(baseDamage \* i\) / 100\)\);", gen3),         "gen3.ts no longer rolls 85..100 over 100: Polished's damage variation is not what the calc shows"


_ENGINE_PROBE = r"""
const fs = require('fs'), vm = require('vm');
const enginePaths = JSON.parse(process.argv[1]);
const win = {}; win.window = win; win.calc = win.exports = {}; win.require = () => win.exports;
win.__createBinding = (o, m, k) => { o[k] = m[k]; };
const ctx = vm.createContext(win);
for (const f of enginePaths) vm.runInContext(
  // calc/build's cpdir() strips these hoisted `exports.X = void 0;` lines from every served file.
  fs.readFileSync(f, 'utf8').replace(/^exports.* = void 0;$/gm, ''), ctx, { filename: f });
const E = win.exports; E.usePolished(true);
const gen = win.calc.Generations.get(3);
const all = v => ({ hp: v, at: v, df: v, sa: v, sd: v, sp: v });
const mk = (n, o) => new win.calc.Pokemon(gen, n, Object.assign({ level: 50, nature: 'Hardy', ivs: all(31), evs: all(0) }, o));
const a = mk('Bulbasaur'), d = mk('Bulbasaur');
const hit = (mv, dn) => win.calc.calculate(gen, a, mk(dn), new win.calc.Move(gen, mv), new win.calc.Field()).damage;
const out = { atk: a.stats.atk, def: a.stats.def, hp: d.maxHP(), acrobatics: hit('Acrobatics', 'Bulbasaur'),
  ratTypes: mk('Rattata').types, dragonIntoFairy: hit('Dragon Claw', 'Clefairy') };
E.usePolished(false);
out.vanillaBulbasaur = new win.calc.Pokemon(gen, 'Bulbasaur', { level: 50 }).types;
console.log(JSON.stringify(out));
"""


def test_the_built_engine_with_polished_installed_matches_the_hand_computed_damage():
    """Runs the compiled calc (calc/calc/dist, from `npm run compile`) plus polished.js through
    the page's own load order, in node, and holds the numbers test_hand_computed_damage derives
    by hand: Bulbasaur L50 DV15 (IV 31 on the wire) Acrobatics into Bulbasaur L50 = 44..52."""
    import shutil
    import subprocess
    node = shutil.which("node")
    built = ROOT / "calc" / "calc" / "dist"
    if not node:
        pytest.skip("node is not installed")
    if not (built / "index.js").is_file():
        pytest.skip("calc/calc/dist not built - run `npm run compile` in calc/calc first")
    preview = (ROOT / "server" / "static" / "calc-preview.js").read_text(encoding="utf-8")
    engine = re.findall(r"'([^']+)'", re.search(r"var ENGINE\s*=\s*\[(.*?)\];", preview, re.S).group(1))
    paths = [str(DATASET if f == "calc/data/polished.js" else built / f.removeprefix("calc/")) for f in engine]
    done = subprocess.run([node, "-e", _ENGINE_PROBE, json.dumps(paths)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    assert (got["atk"], got["def"], got["hp"]) == (69, 69, 120)
    assert got["acrobatics"] == [max(1, 52 * r // 100) for r in range(85, 101)]   # 44 .. 52
    assert got["ratTypes"] == ["Normal"]
    assert got["dragonIntoFairy"] == 0
    assert got["vanillaBulbasaur"] == ["Grass", "Poison"], "usePolished(false) must restore vanilla"
