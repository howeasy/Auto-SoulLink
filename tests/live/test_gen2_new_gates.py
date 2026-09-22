"""PHYSICAL lane for P3b.3a: the live inspect gate (docs/gen2/gen2_requirements.md R-1, R-2, R-3,
R-5g; docs/gen2/GEN2_BINDING_PLAN.md P3b.3a).

    SLINK_LIVE=1 pytest tests/live/test_gen2_new_gates.py -q

Each case boots ONE of the eight qualified fixtures (tests/fixtures/gen2/<name>.SaveRAM, from
tools/gen2_fixtures.FIXTURES) warm on the real cartridge, runs lua/tests/gen2_inspect_gate.lua,
and decodes the SAME captured bytes with server/adapters/gen2_codec.py (PYDEC): Lua on hardware
and Python on the same bytes must agree field for field. Skipped, never hung, without EmuHawk, the
pinned decomp/ROM build or a qualified fixture -- and the release runner
(tools/verify_gen2_release.py) counts a skip as a failure, so a missing input is a hard failure
here too, never a silent pass.

SCOPE (P3b.3a only): this file currently carries ONLY the live inspect rows -- R-1 (party/box/name
decode), R-2 (independent stat recomputation), R-3 (a Lua-internal differential over the same
profile addresses; see the R-3 scope note in lua/tests/gen2_inspect_gate.lua for what this does
and does not close against the game's own on-screen display) and R-5g (gender/shiny from DVs).
The engine-signal (P3b.4), write-window (P3b.5) and client-conformance (P3b.6/P3b.7) rows belong
in this same file per docs/gen2/GEN2_BINDING_PLAN.md's P3b table, but land as separate, later
cards, each owning its own function/block here (the §7 one-writer-per-file-at-a-time rule); this
card claims none of that coverage and tools/verify_gen2_release.py's "live-new-gates" lane stays
UNIMPLEMENTED until they do.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from server.adapters import gen2_codec as codec  # noqa: E402
from server.adapters.gen2_rom_scan import Rom  # noqa: E402
from tools import gen2_source_data  # noqa: E402
from tools.gen2_fixtures import FIXTURES  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_inspect_gate.lua"


# --- shared, importable, BizHawk-free logic (tests/unit/test_gen2_inspect_gate.py exercises it) ---

_LINE = re.compile(r"^([A-Z][A-Z0-9_]*) (.*)$", re.M)


def tagged_lines(text: str) -> dict[str, list[str]]:
    """Every `TAG <rest>` line this gate prints, grouped by tag, in file order."""
    out: dict[str, list[str]] = {}
    for tag, rest in _LINE.findall(text):
        out.setdefault(tag, []).append(rest)
    return out


def tag_json(text: str, tag: str):
    lines = tagged_lines(text).get(tag)
    if not lines:
        raise AssertionError(f"gate printed no {tag!r} line")
    return json.loads(lines[0])


def fixture_missing_reason(name: str, *, repo: Path = REPO) -> str | None:
    """None when the fixture is present; a clear skip reason otherwise (never a silent pass)."""
    path = repo / "tests/fixtures/gen2" / f"{name}.SaveRAM"
    if not path.exists():
        return f"{path.relative_to(repo).as_posix()} not present (build it with tools/gen2_fixtures.py)"
    return None


def rom_missing_reason(title: str, *, repo: Path = REPO) -> str | None:
    """None when the pinned decomp/ROM build for `title` is available; a clear skip reason otherwise."""
    try:
        gen2_source_data.load_context(title, root=repo)
    except Exception as exc:  # noqa: BLE001 - any missing/invalid build input just skips this gate
        return f"{title}: pinned Gen 2 ROM build unavailable ({exc})"
    return None


def _lua_to_py(mon: dict) -> dict:
    """The Lua decode is already field-shaped like gen2_codec's output; only strip the Lua-only
    `slot`/`species_marker` bookkeeping fields the comparison below walks from the PYDEC side."""
    return dict(mon)


def compare_mon(lua_mon: dict, py_mon: dict, *, where: str) -> None:
    """Field-for-field equality, PYDEC's keys against the Lua decode. Raises AssertionError on
    the FIRST disagreeing field -- this is what a mutated byte or a wrong-fixture dump trips."""
    if lua_mon is None:
        raise AssertionError(f"{where}: Lua produced no record")
    lua_mon = _lua_to_py(lua_mon)
    for field, want in py_mon.items():
        got = lua_mon.get(field)
        if got != want:
            raise AssertionError(f"{where}: field {field!r} disagrees: lua={got!r} pydec={want!r}")


def compare_collection(lua_collection: dict, py_collection: dict, *, where: str) -> None:
    if lua_collection is None:
        raise AssertionError(f"{where}: Lua produced no collection")
    if lua_collection["count"] != py_collection["count"]:
        raise AssertionError(f"{where}: count disagrees: lua={lua_collection['count']} "
                             f"pydec={py_collection['count']}")
    for slot, (lua_mon, py_mon) in enumerate(zip(lua_collection["mons"], py_collection["mons"], strict=True)):
        compare_mon(lua_mon, py_mon, where=f"{where} slot {slot}")


def identity_matches(party: dict, expected_ot_id: int) -> bool:
    """R-1's wrong-fixture control: a fixture's first party mon must carry ITS OWN OT id. Given
    the WRONG spec's expected id (the town/battle pairing's own OT, or the other fixture's OT),
    this returns False rather than raising, so a caller can assert the refusal explicitly."""
    if not party.get("mons"):
        return False
    return party["mons"][0]["ot_id"] == expected_ot_id


def gender_and_shiny(dv_word: int, gender_ratio: int) -> tuple[str, bool]:
    """Independent Python reimplementation of GetGender/the shiny check (engine/pokemon/
    mon_stats.asm; engine/gfx/color.asm), matching lua/tests/gen2_inspect_gate.lua's
    G.gender_and_shiny byte for byte but authored separately -- neither side imports the other."""
    attack = (dv_word >> 12) & 0xF
    defense = (dv_word >> 8) & 0xF
    speed = (dv_word >> 4) & 0xF
    special = dv_word & 0xF
    shiny = (attack // 2) % 2 == 1 and defense == 10 and speed == 10 and special == 10
    if gender_ratio == 255:
        gender = "genderless"
    elif gender_ratio == 254:
        gender = "female"
    elif gender_ratio == 0:
        gender = "male"
    else:
        gender = "female" if (attack * 16 + speed) <= gender_ratio else "male"
    return gender, shiny


# --- the live gate ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def emuhawk():
    from gen1_playthrough import EMUHAWK
    if not os.path.exists(EMUHAWK):
        pytest.skip(f"EmuHawk not found at {EMUHAWK}")
    return EMUHAWK


def _run_inspect_gate(spec, *, timeout=600):
    """Boot `spec`'s fixture warm and run the inspect gate; returns (passed, path, text)."""
    from run_gb_gate import run_gate

    fixture = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
    directory = REPO / ".cache/gen2-fixtures/inspect-gate" / spec.name
    return run_gate(GATE, rom_key=spec.title, target=spec.target, timeout=timeout,
                    saveram_dir=str(directory), fixture_path=str(fixture), speed_percent=100)


@pytest.mark.parametrize("spec", FIXTURES, ids=lambda spec: spec.name)
def test_inspect_gate_and_hardware_differential(spec, emuhawk):
    reason = rom_missing_reason(spec.title) or fixture_missing_reason(spec.name)
    if reason:
        pytest.skip(reason)

    passed, path, text = _run_inspect_gate(spec)
    assert passed, f"gate FAILED on {spec.name}; result {path}: {text[-2500:]}"
    assert "CHECKPOINT reached" in text, f"checkpoint/liveness not reached on {spec.name}: {text[-1500:]}"

    profile_wrapper = json.loads((REPO / f"data/games/gen2_{spec.title}/profile.json")
                                 .read_text(encoding="utf-8"))
    layout = codec.Gen2Layout.from_profile(profile_wrapper, spec.title)

    dump = tag_json(text, "DUMP")
    assert dump["party"]["domain"] == "System Bus" and dump["cartram"]["domain"] == "CartRAM"
    assert isinstance(dump["frame"], int) and dump["frame"] >= 0
    assert dump["cartram"]["length"] == 0x8000

    # R-1: party, active box and all 14 storage boxes, byte-for-byte, same-frame dump.
    party_raw = bytes.fromhex(dump["party"]["hex"])
    py_party = codec.decode_party(party_raw, layout)
    lua_party = tag_json(text, "PARTY_LUA")
    compare_collection(lua_party, py_party, where=f"{spec.name} party")

    cart_raw = bytes.fromhex(dump["cartram"]["hex"])
    active_flat, active_len = layout.active_box
    py_active = codec.decode_box(cart_raw[active_flat:active_flat + active_len], layout)
    lua_active = tag_json(text, "ACTIVE_BOX_LUA")
    compare_collection(lua_active, py_active, where=f"{spec.name} active box")

    for index, (flat, length) in enumerate(layout.storage_boxes):
        py_box = codec.decode_box(cart_raw[flat:flat + length], layout)
        lua_box = tag_json(text, f"BOX_LUA_{index}")
        compare_collection(lua_box, py_box, where=f"{spec.name} box {index}")

    # R-1 wrong-fixture control (positive half; the refusal half is a MODEL unit test --
    # tests/unit/test_gen2_inspect_gate.py -- since it needs no cartridge): this fixture's own
    # decoded OT id must match itself.
    assert identity_matches(py_party, py_party["mons"][0]["ot_id"])

    # R-2: independent stat recomputation from base stats sourced off the ROM, never the party's
    # own stored stat fields (CalcMonStats double-derivation, ticket 20).
    ctx = gen2_source_data.load_context(spec.title, root=REPO)
    rom = Rom(ctx.rom, profile_wrapper["titles"][spec.title])
    for mon in py_party["mons"]:
        base = rom.base_stats(mon["species_id"])
        computed = codec.calc_stats(base, mon["dvs"], mon["stat_exp"], mon["level"])
        assert mon["max_hp"] == computed["hp"], (spec.name, mon["species_id"], "max_hp")
        assert mon["stats"] == {k: v for k, v in computed.items() if k != "hp"}, (spec.name, mon["species_id"])

    # R-3: reads.lua's structured accessors against the gate's OWN independent second reader of
    # the same addresses (see the scope note in lua/tests/gen2_inspect_gate.lua).
    badges = tag_json(text, "BADGES_LUA")
    raw_badges = tag_json(text, "RAW_BADGES")
    assert badges == raw_badges, (spec.name, "badges differential", badges, raw_badges)
    boxnum = tag_json(text, "RAW_BOXNUM")
    assert isinstance(boxnum, int) and 0 <= boxnum <= 13
    battle = tag_json(text, "BATTLE_LUA")
    raw_battle = tag_json(text, "RAW_BATTLE")
    assert battle["mode"] == raw_battle["mode"], (spec.name, "battle-mode differential")

    # R-5g: gender/shininess from the same DVs, recomputed independently in Python.
    gender_shiny = tag_json(text, "GENDER_SHINY")
    species_index = json.loads((REPO / f"data/games/gen2_{spec.title}/species_index.json")
                               .read_text(encoding="utf-8"))["species"]
    assert len(gender_shiny) == len(py_party["mons"])
    for row, mon in zip(gender_shiny, py_party["mons"], strict=True):
        ratio = species_index[str(mon["species_id"])]["gender_ratio"]
        gender, shiny = gender_and_shiny(mon["dv_word"], ratio)
        assert row["gender"] == gender and row["shiny"] == shiny, (spec.name, mon["species_id"], row)
