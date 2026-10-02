"""PHYSICAL lane for card U1G: one engine-site receipt RUN per O-33 synthetic setup fixture (tools/gen2_synth_fixtures.py),
merged into the title's receipt as a gen2-engine-site-receipt-v2 run list.

    SLINK_LIVE=1 pytest tests/live/test_gen2_u1g.py -q -p no:randomly -k "crystal and kyle"

Boots <title>_synth_<kind> warm through its base fixture's qualified CONTINUE path (the base's route/qualify facts, the
synthetic bytes as the stage fingerprint) and runs lua/tests/gen2_frame_align.lua in U1G mode
(lua/tests/gen2_u1g_inputs.lua). On PASS this file re-checks the printed run and writes it to
.cache/gen2-fixtures/u1g/<fixture>.run.json; once a title has all three runs they replace the synthetic runs in
tests/fixtures/gen2/receipts/<title>.engine_sites.json (the non-synthetic runs are kept).

OVERLAY (SLINK_GEN2_ARTIFACT=overlay, docs/gen2/OVERLAY_ADMISSION.md D4): the same legs boot <title>_overlay, the run files
go to .cache/gen2-fixtures/u1g-overlay and the union lands in tests/fixtures/gen2/receipts/overlay/<title>.engine_sites.json.
A union never mixes kinds or ROMs: merge() refuses a committed or new run that is not the staged artifact's own.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from tests.live import (  # noqa: E402
    test_gen2_frame_align as u1,
    test_gen2_new_gates as live,
)
from tests.live.test_gen2_new_gates import emuhawk  # noqa: E402,F401 - pytest fixture
from tools import (  # noqa: E402
    gen2_fixtures,
    gen2_synth_fixtures as synth,  # noqa: E402
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_frame_align.lua"
RUNS = REPO / ".cache/gen2-fixtures" / ("u1g-overlay" if live.KIND == "overlay" else "u1g")
KINDS = ("grass", "kyle", "bill")
CLAIMED = {"grass": ("hatch_species", "hatch_finalized", "evolution_species_published", "capture_box",
                     "capture_box_finalized"),
           "kyle": ("npc_trade_begin", "npc_trade_finalized"), "bill": ("gift_begin", "gift_party_finalized")}
# where each kind's whiteout lands and who is talked to (maps/*.asm; data/events/npc_trades.asm)
TALK = {"kyle": ("VioletCity", "VioletKylesHouse", "VIOLET_KYLES_HOUSE", "Kyle", "BELLSPROUT", "ONIX"),
        "bill": ("GoldenrodCity", "BillsFamilysHouse", "BILLS_FAMILYS_HOUSE", "BillScript", None, "EEVEE")}


def u1g_facts(ctx, kind, name) -> dict:
    areas = {row["map_const"]: row for row in gen2_fixtures.build_area_map(ctx).values()}
    by_name = {row["map_name"]: row for row in areas.values()}
    species = gen2_fixtures.const_block(ctx.read_source("constants/pokemon_constants.asm"), "CATERPIE")
    points = {}
    for site in gen2_fixtures.exec_sites(ctx.title, live.KIND, REPO).values():
        points.update({k: v for k, v in site["point_symbols"].items() if k in ("wPartyCount", "wPartySpecies", "sBoxCount")})
    effects = {"wPartyCount": {"addr": points["wPartyCount"]["addr"]},
               "wPartySpecies": {"addr": points["wPartySpecies"]["addr"]},
               "sBoxCount": {"addr": points["sBoxCount"]["addr"], "bank": points["sBoxCount"]["bank"]}}
    out = {"kind": kind, "effects": effects, "disclosure": f"tests/fixtures/gen2/{name}.synth.json"}

    def facts_map(map_name):
        m = gen2_fixtures._map_facts(ctx, by_name[map_name], areas)
        m["ledges"] = u1.ledges(ctx, map_name, m)
        return m

    if kind == "grass":
        out.update(maps={"Route29": facts_map("Route29")}, map="Route29", lead=species["CATERPIE"],
                   evolved=species["METAPOD"], egg=0xFD)   # EGG, constants/pokemon_constants.asm
        return out
    city, house, const, script, give, received = TALK[kind]
    maps = {n: facts_map(n) for n in ("ElmsLab", city, house)}
    door = next(w for w in maps[city]["warps"] if w["destination"] == const)
    npc = maps[house]["objects"][script]
    line = next(raw.strip() for raw in ctx.read_source(f"maps/{house}.asm").splitlines()
                if raw.strip().startswith("object_event") and raw.strip().split(",")[11].strip() == script)
    radius_y = int(line[13:].split(",")[5])
    out.update(maps=maps, start="ElmsLab", city=city, house=house, door={"x": door["x"], "y": door["y"]},
               npc={"x": npc["x"], "y_min": npc["y"] - radius_y, "y_max": npc["y"] + radius_y},
               received=species[received], give_slot=0)
    return out


def run_facts(ctx, spec, kind, name, qualification_attempt_id):
    facts = u1.u1_facts(ctx, gen2_fixtures.spec_route_facts(spec, REPO, kind=live.KIND), qualification_attempt_id)
    for key in ("pc", "poison", "evolution"):
        facts.pop(key, None)
    facts["u1g"] = u1g_facts(ctx, kind, name)
    return facts


def verify(text, title, kind, name, staged):
    run = live.tag_json(text, "RECEIPT")
    gen2_fixtures.check_run_identity(run, live.identity(title))   # the HASHED staged artifact, never the env
    assert run["fixture"] == name and run["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), run["fixture"]
    assert sorted(run["proven"]) == sorted(CLAIMED[kind]) and run["evidence_level"] == "PHYSICAL"
    disclosure = json.loads((REPO / f"tests/fixtures/gen2/{name}.synth.json").read_text(encoding="utf-8"))
    assert run["synth"] == disclosure and disclosure["sha256"] == run["fixture_sha256"]
    for e in run["effects"]:
        assert e["callback"] == e["hit_frame"] and run["arrival_frame"] <= e["arming_frame"] < e["hit_frame"], e
        assert e["before_hex"] == e["arming_hex"] != e["after_hex"], e
    decoy = live.tag_json(text, "DECOY")
    assert decoy["raw"] >= 1 and decoy["accepted"] == 0 and decoy["bank_rejects"] == decoy["raw"], decoy
    return run


def merge(title, kind=None, identity=None):
    """The title's receipt: its non-synthetic runs plus the three U1G runs, once all three exist.

    Per artifact (D4): the union is read from and written to this kind's receipt, and every kept and new run must be
    that artifact's own (gen2_fixtures.merge_engine_runs) -- a clean run never joins an overlay union or vice versa."""
    kind = kind or live.KIND
    identity = identity or live.identity(title, kind)
    names = [f"{title}_synth_{k}" for k in KINDS]
    if not all((RUNS / f"{n}.run.json").exists() for n in names):
        return None
    path = live.receipt_file(f"{title}.engine_sites.json", kind, repo=REPO)
    committed = json.loads(path.read_text(encoding="utf-8"))
    new = [json.loads((RUNS / f"{n}.run.json").read_text(encoding="utf-8")) for n in names]
    runs = gen2_fixtures.merge_engine_runs(committed, new, identity, synth.SYNTH_FIXTURES)
    # the kept non-synthetic runs came from test_gen2_frame_align: stamped only if earned on this same code
    receipt = live.stamped({"schema": "gen2-engine-site-receipt-v2", "title": title, "runs": runs}, base=committed)
    path.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("title", ("crystal", "gold", "silver"))
def test_u1g_run(emuhawk, title, kind):  # noqa: F811
    name = f"{title}_synth_{kind}"
    target, _ = synth.SYNTH_RECIPES[kind]
    spec = gen2_fixtures.BY_NAME[f"{title}_{target}"]
    fixture = REPO / "tests/fixtures/gen2" / f"{name}.SaveRAM"
    reason = live.rom_missing_reason(title) or live.receipt_missing_reason(spec.name)
    if reason or not fixture.exists():
        pytest.skip(reason or f"{fixture.name} missing")
    from run_gb_gate import run_gate

    staged = fixture.read_bytes()
    built, _ = synth.build_named(name)
    assert built == staged, "the committed synthetic fixture is not the builder's output"
    ctx = gen2_fixtures.exec_context(title, live.KIND, REPO)
    qualification = json.loads(live.receipt_file(f"{spec.name}.qualification.json").read_text(encoding="utf-8"))
    env = live.inspect_env(spec, staged)
    case = json.loads(env["SLINK_GEN2_FIXTURE_CASE"])
    case.update(synth=name, attempt_id="u1g-" + name)   # the shared gate names the case by its base fixture
    env["SLINK_GEN2_FIXTURE_CASE"] = json.dumps(case)
    env["SLINK_GEN2_U1_FACTS"] = json.dumps(run_facts(ctx, spec, kind, name, qualification["attempt_id"]))
    lane = REPO / ".cache/gen2-fixtures" / ("u1g-run-overlay" if live.KIND == "overlay" else "u1g-run")   # short path: BizHawk's SaveRAM MAX_PATH limit
    passed, path, text = run_gate(GATE, rom_key=live.rom_key(title), target=spec.target, timeout=1800,
                                  saveram_dir=str(lane / name), fixture_path=str(fixture),
                                  speed_percent=300,   # the highest speed run_gb_gate exposes for Gen 2 (O-36: EMU-SPEED card)
                                  env_overrides=env)
    assert passed, f"gate FAILED; result {path}: {text[-3000:]}"
    assert fixture.read_bytes() == staged, "fixture changed while the gate ran"
    run = verify(text, title, kind, name, staged)
    assert run["qualification_attempt_id"] == qualification["attempt_id"]
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{name}.run.json").write_text(json.dumps(run, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    merge(title)
