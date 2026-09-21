"""PHYSICAL: a fully RANDOMIZED pureRGB cartridge plays as its OWN tables say.

    SLINK_LIVE=1 pytest tests/live/test_gen1_rand_gates.py -q -p no:randomly -rs

admit_randomized_new (tools/e2e_duo.py) proves a randomized pure ROM is admitted and links on
its first encounter; nothing checked in-game that the randomized starter and the rival's first
party are what the randomized ROM's tables hold. This randomizes PureRed once with the UPR fork
(wild + starters + trainers, the pure default spec, no tweaks), caches the artifact under
.cache/purergb-rand/ so reruns replay the same bytes and seed (the fork's CLI takes no seed
argument; the seed is read back from its log), decodes the OUTPUT ROM's starter immediates and
the RIVAL1 trainer records through the fork's own INI offsets, boots it cold in EmuHawk through
lua/tests/test_gen1_rand_lab_gate.lua (NEW GAME -> the ball at x=8 -> the rival battle) and
compares what the cartridge handed out. Skipped, never hung, without EmuHawk, the jar, Java or
the pinned PureRed build.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 1 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/test_gen1_rand_lab_gate.lua"
ROM_KEY = "purered_rand_cold"
RAND_DIR = os.path.join(REPO, ".cache", "purergb-rand")
CATEGORIES = {"wild", "starters", "trainers"}
# RIVAL1 is trainer class $18: wCurOpponent 221 - OPP_ID_OFFSET 197 (lua/tests/gen1_pure_facts.lua
# TRAINER; docs/purergb/PLAN.md A12). Its first three records are the lab battle's parties.
RIVAL1_CLASS = 0x18
OPP_RIVAL1 = 221
OPP_ID_OFFSET = 197
# StarterOffsets1/2/3 (data/purergb/upr_pure_entries.ini) are STARTER1/2/3 = the lab balls at
# x=6/7/8 (.cache/purergb data/maps/objects/OaksLab.asm:28-30; clean: Charmander/Squirtle/
# Bulbasaur). The gate's driver takes the ball at x=8.
BALL_X_TO_STARTER = {6: 1, 7: 2, 8: 3}
ROUTE_1 = 0x0C


@pytest.fixture(scope="module")
def emuhawk():
    import gen1_playthrough as play
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    return play.EMUHAWK


def _randomized_purered() -> str:
    """The randomized PureRed under .cache/purergb-rand/, built once and then replayed."""
    import gen1_playthrough as play

    from server.upr_pipeline import find_upr_jar, jar_is_fork, randomize
    from server.upr_settings import build_categories
    out = os.path.join(RAND_DIR, "purered_rand.gbc")
    if os.path.exists(out) and os.path.exists(out + ".log"):
        return out
    try:
        source = play.purergb_dump("purered")
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"purered cartridge dump not present ({exc})")
    jar = find_upr_jar()
    if not jar or not jar_is_fork(jar):
        pytest.skip("SLink UPR fork jar (PokeRandoZX.jar) not present -- tools/build_upr_fork.py")
    if not shutil.which("java"):
        pytest.skip("java not present on PATH")
    os.makedirs(RAND_DIR, exist_ok=True)
    settings = os.path.join(RAND_DIR, "settings.rnqs")
    with open(settings, "wb") as f:
        f.write(build_categories(CATEGORIES, fastest_text=False))
    randomize(jar, settings, source, out)
    return out


# ── decoding the OUTPUT ROM's tables (the fork's own INI offsets, not a vanilla reference) ──
def _starters(rom: bytes, entry: dict) -> dict[int, int]:
    """STARTER1/2/3 species: every offset of a group must agree, or the cartridge itself is
    inconsistent (the script's `ld` immediates and StarterToPartyID's `cp` immediates)."""
    out = {}
    for n in (1, 2, 3):
        values = {rom[o] for o in entry[f"StarterOffsets{n}"]}
        assert len(values) == 1, f"StarterOffsets{n} disagree in the output ROM: {sorted(values)}"
        out[n] = values.pop()
    return out


def _trainer_records(rom: bytes, entry: dict, cls: int) -> list[list[dict]]:
    """Every record of one trainer class as [{level, species}, ...], in ReadTrainer's own
    grammar (.cache/purergb engine/battle/read_trainer_party.asm): a leading $FF/$FE ($FE = alt
    palettes, bit 7 of each level byte) or $FD (+ one custom-moveset id byte) means per-mon
    (level, species) pairs; anything else is the shared level followed by species bytes."""
    table = entry["TrainerDataTableOffset"]
    bank = table // 0x4000
    ptr = rom[table + (cls - 1) * 2] | rom[table + (cls - 1) * 2 + 1] << 8
    off = bank * 0x4000 + (ptr - 0x4000)
    records = []
    for _ in range(entry["TrainerDataClassCounts"][cls]):
        tag = rom[off]
        mons = []
        if tag in (0xFF, 0xFE, 0xFD):
            off += 2 if tag == 0xFD else 1
            while rom[off] != 0:
                mons.append({"level": rom[off] & 0x7F, "species": rom[off + 1]})
                off += 2
        else:
            off += 1
            while rom[off] != 0:
                mons.append({"level": tag, "species": rom[off]})
                off += 1
        off += 1
        records.append(mons)
    return records


def test_randomized_pure_cartridge_plays_its_own_tables(emuhawk):
    from run_gb_gate import GENS, run_gate
    from upr_write_domain_diff import load_entry

    from server.adapters.gen1_rom_scan import identify, scan_wild
    from server.upr_pipeline import _parse_log

    out = _randomized_purered()
    with open(out, "rb") as f:
        rom = f.read()
    ident = identify(rom)
    assert ident["variant"] == "purered" and ident["kind"] == "rand", ident
    seed = _parse_log(out + ".log")["seed"]
    entry = load_entry("purered")
    starters = _starters(rom, entry)
    rival = _trainer_records(rom, entry, RIVAL1_CLASS)[:3]
    route1 = sorted({s["species_index"] for s in scan_wild(rom)[ROUTE_1]["grass"]["slots"]})
    tables = {"seed": seed, "sha1": ident["sha1"], "starters": starters, "rival1": rival, "route1_grass": route1}
    print("RAND_TABLES " + json.dumps(tables))
    assert all(rec for rec in rival), f"an empty RIVAL1 record in the output ROM: {rival}"

    # stage the artifact as the cold rom key's cartridge and play it
    _base, rom_rel, _save = GENS["gen1"]["patched"][ROM_KEY]
    shutil.copyfile(out, os.path.join(REPO, rom_rel))
    passed, path, text = run_gate(GATE, rom_key=ROM_KEY, target="town", timeout=900, quiet=True)
    assert passed, f"randomized lab gate FAILED; receipt {path}: {text[-2500:]}"
    m = re.search(r"^RAND_OBS (.*)$", text, re.M)
    assert m, f"gate printed no RAND_OBS line; receipt {path}"
    obs = json.loads(m.group(1))
    print("RAND_OBS " + json.dumps(obs))

    # the starter at the ball the driver took is the OUTPUT ROM's starter for that ball
    want_starter = starters[BALL_X_TO_STARTER[obs["ball_x"]]]
    assert obs["party_count"] == 1
    assert obs["starter"] == want_starter, (
        f"seed {seed}: the ball at x={obs['ball_x']} gave species {obs['starter']:#04x}, the ROM's "
        f"StarterOffsets{BALL_X_TO_STARTER[obs['ball_x']]} say {want_starter:#04x}")
    # the rival's party is the RIVAL1 record the engine picked (wTrainerNo), byte for byte
    assert obs["opponent"] == OPP_RIVAL1 and obs["opponent"] - OPP_ID_OFFSET == RIVAL1_CLASS, obs
    assert 1 <= obs["trainer_no"] <= 3, obs
    want_party = rival[obs["trainer_no"] - 1]
    got_party = [{"level": mon["level"], "species": mon["species"]} for mon in obs["enemy"]]
    assert got_party == want_party, (
        f"seed {seed}: RIVAL1 record {obs['trainer_no']} in the ROM is {want_party}, the cartridge "
        f"fielded {got_party}")
    # StarterToPartyID (.cache/purergb home/pokemon.asm:337-347): record 1 for STARTER1, 2 for
    # STARTER2, else 3 -- with the randomized immediates the rival's ball decides the record
    want_no = {starters[1]: 1, starters[2]: 2}.get(obs["rival_starter"], 3)
    assert obs["trainer_no"] == want_no, (
        f"seed {seed}: rival starter {obs['rival_starter']:#04x} -> record {want_no} by the ROM's "
        f"starters {starters}, engine picked {obs['trainer_no']}")
    # Route 1's first wild encounter is a species the OUTPUT ROM's Route 1 grass table holds
    w = re.search(r"^RAND_WILD (.*)$", text, re.M)
    assert w, f"gate reached no Route 1 wild battle: {re.search(r'^WILD_FAIL .*$', text, re.M)}; receipt {path}"
    wild = json.loads(w.group(1))
    assert wild["map"] == ROUTE_1 and wild["battle_type"] == 0, wild
    assert wild["species"] in route1, (
        f"seed {seed}: Route 1 grass gave species {wild['species']:#04x}, the ROM's table holds {route1}")
    print(f"RAND_RECEIPT seed={seed} starter={obs['starter']:#04x} rival_no={obs['trainer_no']} "
          f"party={got_party} wild={wild['species']:#04x}@({wild['x']},{wild['y']}) frame={wild['frame']} "
          f"receipt={path}")
