"""PHYSICAL lane for card gen2-U2: the Gen 2 write checkpoint + write windows on the running cartridge.

    SLINK_LIVE=1 pytest tests/live/test_gen2_write_windows.py -q -p no:randomly

Per title (Crystal first, then Gold) three EmuHawk launches of lua/tests/gen2_write_windows.lua:
  town    <title>_town: an idle-hold party write (lua/gen2/writes.lua) and a current-box deposit into the
          authoritative sBox copy in CartRAM (lua/gen2/boxes.lua), START menu / Elm's script text box /
          native SAVE (wGameLogicPaused) / lab exit warp windows, the flushed SaveRAM.
  reload  that flushed SaveRAM, cold-booted through CONTINUE: the written bytes must be there.
  battle  <title>_battle: a Route 29 wild battle window, a refused party-only write to the active slot.
This file re-derives every verdict from the gate's printed observations and the flushed SaveRAM bytes
(raw offsets from the pinned .sym, never the PYDEC codec), then writes the PHYSICAL receipt that
lua/gen2_write_safety.lua's check() requires (M.qualified), and re-checks it through that Lua:

    tests/fixtures/gen2/receipts/<title>.write_window.json

Silver has no run of its own: its checkpoint rows are identical to Gold's, so the Gold receipt covers it
(M.RECEIPT_TITLE) exactly while those rows stay identical. Skipped without EmuHawk, the pinned build or
a qualified fixture (the release runner counts a skip as a failure).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from tests.live import test_gen2_new_gates as live  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_write_windows.lua"
TITLES = ("crystal", "gold")
OBSERVE = 30
RECEIPT_SCHEMA = "gen2-write-window-receipt-v1"
CART_RAM_BYTES = 0x8000
TOWN_WINDOWS = {"start_menu": (OBSERVE, None), "script_text": (OBSERVE, {"wScriptRunning", "wScriptFlags"}),
                "mid_warp": (1, {"wMapStatus"})}
SAVE_WINDOW = {"save_paused": (1, {"wGameLogicPaused"})}
BATTLE_WINDOWS = {"battle": (OBSERVE, {"wBattleMode"})}


def receipt_path(title: str, *, repo: Path = REPO) -> Path:
    return repo / "tests/fixtures/gen2/receipts" / f"{title}.write_window.json"


def sram_flat(bank: int, address: int) -> int:
    """CartRAM offset of an SRAM bank:address (8 KiB banks at $A000)."""
    assert 0xA000 <= address < 0xC000, address
    return bank * 0x2000 + address - 0xA000


def verify_windows(windows: dict, required: dict) -> None:
    """Every required window was observed, held no accepted checkpoint hold, refused the party write by
    ownership without changing a byte, and (where named) failed on its stated predicate."""
    for name, (frames, symbols) in required.items():
        w = windows.get(name)
        assert w is not None and w["frames"] >= frames, (name, "window not observed", w)
        assert w["accepted"] == 0, (name, "accepted checkpoint hold inside the window", w)
        write = w.get("write")
        assert isinstance(write, dict) and write["refused"] is True and "ownership refused" in write["reason"] \
            and write["party_unchanged"] is True, (name, "party write not refused by ownership", write)
        if symbols:
            assert symbols & set(w["failing"]), (name, "stated predicate did not refuse", w["failing"])


def verify_town(text: str, profile: dict, cartram: bytes, party_hp_flat: int) -> dict:
    """The town run: the idle-hold writes, every window, and the flushed SaveRAM carrying the written
    party HP (sPokemonData) and the deposit in BOTH the active sBox and its native SaveBox backing slot."""
    assert "RESULT: PASS" in text.splitlines()[-1], text[-2000:]
    write, windows = live.tag_json(text, "U2_WRITE"), live.tag_json(text, "U2_WINDOWS")
    save = live.tag_json(text, "U2_SAVE")
    party, box = write["party"], write["box"]
    before = int(party["before_hex"], 16)
    assert int(party["written_hex"], 16) == before - 1 and party["readback_hex"] == party["written_hex"], party
    assert party["address"] == profile["ram"]["wPartyMon1HP"] and party["offset"] == profile["constants"]["MON_HP"]
    derived = profile["derived"]
    assert box["owner"] == "active" and box["flat"] == derived["active_box_flat"], box
    assert box["length"] == derived["active_box_copy_length"] and box["readback_hex"] == box["after_hex"], box
    assert box["count_after"] == box["count_before"] + 1, box
    assert box["backing_flat"] == profile["storage_boxes"][box["current_box"]]["flat"], box
    verify_windows(windows, TOWN_WINDOWS)
    if "save_paused" in windows:
        verify_windows(windows, SAVE_WINDOW)
    save_window = "refused" if "save_paused" in windows else "MODEL_ONLY"
    # PYDEC-independent persistence: raw offsets in the flushed file.
    cart = cartram[:CART_RAM_BYTES]
    assert len(cart) == CART_RAM_BYTES and hashlib.sha256(cart).hexdigest() == save["cartram_sha256"], \
        "flushed SaveRAM differs from the post-save CartRAM the gate hashed"
    assert cart[party_hp_flat:party_hp_flat + 2].hex() == party["written_hex"], "party HP not saved"
    after = bytes.fromhex(box["after_hex"])
    active, backing = box["flat"], box["backing_flat"]
    assert cart[active:active + len(after)] == after, "active sBox lost the deposit across the native save"
    assert cart[backing:backing + len(after)] == after, "native SaveBox did not copy the external sBox write"
    bus = box["bus"]
    return {"write": write, "windows": windows, "save_window": save_window,
            "start_menu_predicates_pass": windows["start_menu"]["failing"] == [],
            "sram_closed_bus_view": {"address": bus["address"], "bus": bus["value"], "cartram": bus["cartram_value"]},
            "cartram": {"visible": True, "survived_native_save": True}}


def verify_reload(text: str, profile: dict, town: dict) -> None:
    """The cold reload of the town run's save: party HP and the deposit are back through CONTINUE."""
    assert "RESULT: PASS" in text.splitlines()[-1], text[-2000:]
    dump = live.tag_json(text, "DUMP")
    party, box = town["write"]["party"], town["write"]["box"]
    ram = profile["ram"]
    offset = (ram["wPartyMon1HP"] - ram["wPartyCount"]) * 2
    assert dump["party"]["address"] == ram["wPartyCount"], dump["party"]
    assert dump["party"]["hex"][offset:offset + 4] == party["written_hex"], "party HP did not survive the reload"
    cart = bytes.fromhex(dump["cartram"]["hex"])
    after = bytes.fromhex(box["after_hex"])
    assert cart[box["flat"]:box["flat"] + len(after)] == after, "deposit did not survive the reload (LoadBox)"


def verify_battle(text: str) -> dict:
    assert "RESULT: PASS" in text.splitlines()[-1], text[-2000:]
    windows = live.tag_json(text, "U2_WINDOWS")
    verify_windows(windows, BATTLE_WINDOWS)
    write = windows["battle"]["write"]
    assert write["faint_refused"] is True and "active faint timing is not qualified" in write["faint_reason"], write
    model = live.tag_json(text, "U2_BATTLE_MODEL")
    assert model["active_slot"] == write["slot"], model
    return {"windows": windows, "model": model}


def build_receipt(title: str, pack: dict, town: dict, battle: dict, *, fixtures: dict) -> dict:
    """The PHYSICAL receipt lua/gen2_write_safety.lua M.qualified accepts: the exact checkpoint rows
    proved, each control's verdict, the save-window verdict and the save/reload persistence proof."""
    return {"schema": RECEIPT_SCHEMA, "evidence_level": "PHYSICAL", "result": "PASS", "title": title,
            "rom_sha1": pack["source"]["rom_sha1"], "pack_commit": pack["source"]["commit"],
            "checkpoint": pack["titles"][title]["primary"],
            "controls": {"idle_party_write": "authorized", "idle_box_write": "authorized",
                         "start_menu": "refused", "script_text": "refused", "mid_warp": "refused",
                         "battle_party_write": "refused"},
            "mechanisms": {"start_menu": "anchor OWPlayerInput not reached (the 15 predicates "
                           + ("all pass)" if town["start_menu_predicates_pass"] else "do not all pass)"),
                           "script_text": sorted(town["windows"]["script_text"]["failing"]),
                           "mid_warp": sorted(town["windows"]["mid_warp"]["failing"]),
                           "battle_party_write": sorted(battle["windows"]["battle"]["failing"]),
                           "battle_active_ko": "MODEL: must target wBattleMonHP (UpdateBattleMonInParty)"},
            "save_window": town["save_window"], "persisted": True,
            "cartram_external_write": {**town["cartram"], "survived_cold_reload": True,
                                       "sram_closed_bus_view": town["sram_closed_bus_view"]},
            "fixtures": fixtures, "input_mode": "normal_buttons", "harness_write_scopes": ["TEST-ONLY"]}


def lua_qualified(pack: dict, title: str, receipt: dict):
    """lua/gen2_write_safety.lua M.qualified on the receipt, through lupa (the production check)."""
    from lupa.lua54 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")((REPO / "lua/gen2_write_safety.lua").as_posix())
    result = module.qualified(lua.table_from(pack, recursive=True), title, lua.table_from(receipt, recursive=True))
    return result if isinstance(result, tuple) else (result, None)


# --- the live gate ------------------------------------------------------------------------------


def _run(spec, fixture: Path, staged: bytes, mode: str, lane: str):
    from run_gb_gate import run_gate
    env = live.inspect_env(spec, staged)
    env["SLINK_GEN2_U2"] = json.dumps({"mode": mode})
    directory = REPO / ".cache/gen2-fixtures/u2-write-windows" / lane
    passed, path, text = run_gate(GATE, rom_key=spec.title, target=spec.target, timeout=1500,
                                  saveram_dir=str(directory), fixture_path=str(fixture), speed_percent=300,
                                  env_overrides=env)
    assert passed, f"{lane} FAILED; result {path}: {text[-3000:]}"
    return directory, text


@pytest.mark.parametrize("title", TITLES)
def test_write_windows(title, emuhawk):  # noqa: F811 - pytest fixture
    from tools import gen2_fixtures, gen2_source_data
    town_spec, battle_spec = gen2_fixtures.BY_NAME[f"{title}_town"], gen2_fixtures.BY_NAME[f"{title}_battle"]
    for spec in (town_spec, battle_spec):
        reason = (live.rom_missing_reason(spec.title) or live.fixture_missing_reason(spec.name)
                  or live.receipt_missing_reason(spec.name))
        if reason:
            pytest.skip(reason)
    fixtures, staged = {}, {}
    for spec in (town_spec, battle_spec):
        path = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
        staged[spec.name] = path.read_bytes()
        live.qualified_identity(spec.name, staged[spec.name])   # the staged bytes are the qualified candidate
        fixtures[spec.name] = hashlib.sha256(staged[spec.name]).hexdigest()
    profile = json.loads((REPO / f"data/games/gen2_{title}/profile.json").read_text(encoding="utf-8"))["titles"][title]
    pack = json.loads((REPO / f"data/games/gen2_{title}/write_checkpoint.json").read_text(encoding="utf-8"))
    ctx = gen2_source_data.load_context(title, root=REPO)
    pokemon = ctx.symbols["sPokemonData"]
    hp_flat = sram_flat(pokemon.bank, pokemon.address) + profile["ram"]["wPartyMon1HP"] - profile["ram"]["wPokemonData"]

    town_fixture = REPO / "tests/fixtures/gen2" / f"{town_spec.name}.SaveRAM"
    directory, text = _run(town_spec, town_fixture, staged[town_spec.name], "town", f"{title}_town")
    from run_gb_gate import describe_gen2
    saved = directory / describe_gen2(title)["saveram_name"]
    town = verify_town(text, profile, saved.read_bytes(), hp_flat)

    candidate = REPO / ".cache/gen2-fixtures/u2-write-windows" / f"{title}_town.reload_candidate.SaveRAM"
    shutil.copyfile(saved, candidate)
    _, text = _run(town_spec, candidate, candidate.read_bytes(), "reload", f"{title}_town_reload")
    verify_reload(text, profile, town)

    battle_fixture = REPO / "tests/fixtures/gen2" / f"{battle_spec.name}.SaveRAM"
    _, text = _run(battle_spec, battle_fixture, staged[battle_spec.name], "battle", f"{title}_battle")
    battle = verify_battle(text)
    for spec in (town_spec, battle_spec):
        assert (REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM").read_bytes() == staged[spec.name], \
            f"{spec.name} changed while the gates ran"

    receipt = build_receipt(title, pack, town, battle, fixtures=fixtures)
    accepted, why = lua_qualified(pack, title, receipt)
    assert accepted is True, why
    receipt_path(title).write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def emuhawk():
    from gen1_playthrough import EMUHAWK
    if not os.path.exists(EMUHAWK):
        pytest.skip(f"EmuHawk not found at {EMUHAWK}")
    return EMUHAWK
