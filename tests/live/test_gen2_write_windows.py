"""PHYSICAL lane for card gen2-U2: the Gen 2 write checkpoint + write windows on the running cartridge.

    SLINK_LIVE=1 pytest tests/live/test_gen2_write_windows.py -q -p no:randomly

Per title (Crystal first, then Gold) three EmuHawk launches of lua/tests/gen2_write_windows.lua:
  town    <title>_town: an idle-hold party write (lua/gen2/writes.lua) and a current-box deposit into the
          authoritative sBox copy in CartRAM (lua/gen2/boxes.lua), START menu / Elm's script text box /
          native SAVE (wGameLogicPaused, required) / lab exit warp windows, the flushed SaveRAM kept by
          the gate as <fixture>.u2_saved.SaveRAM (saved_image).
  reload  that post-save image, cold-booted through CONTINUE: the written bytes must be there.
  battle  <title>_battle: a Route 29 wild battle window, a refused party-only write to the active slot.
Each run prints its own record (U2_RUN; evidence_level is the gate's, never stamped here). This file
re-derives liveness (phases + MEASURED PC/hROMBank at accepted holds) and persistence (raw offsets from the
pinned .sym, never the profile or the PYDEC codec; the staged fixture bytes must differ before the save),
assembles the receipt from the three run records, and runs lua/gen2_write_safety.lua's own M.qualified
(every control recomputed from the raw records) and M.bind_fixture_qualification against
tests/fixtures/gen2/receipts/<fixture>.qualification.json:

    tests/fixtures/gen2/receipts/<title>.write_window.json

Silver has no run of its own: its checkpoint rows are identical to Gold's, so the Gold receipt (Gold's
pinned ROM) covers it exactly while those rows stay identical. Skipped without EmuHawk, the pinned build or
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
RECEIPT_SCHEMA = "gen2-write-window-receipt-v2"
# The pack physical.required_controls this receipt covers; every other one stays OPEN (M.qualified scope).
COVERED_CONTROLS = ["idle reacquisition", "warp/Continue"]
CART_RAM_BYTES = 0x8000
# Independent re-derivation of idle reacquisition: the second phase of each pair was entered only after
# a NEW accepted hold (the gate driver's order; lua/gen2_write_safety.lua M.REACQUIRE mirrors it).
REACQUIRE = {"town": [("idle", "start_menu"), ("face", "talk"), ("to_save", "save"), ("post_save", "exit"),
                      ("post_warp", "done")],
             "reload": [("idle", "done")],
             "battle": [("idle", "walk"), ("post_battle", "done")],
             "boxes": [("idle", "walk"), ("post_save", "ops")],
             "boxes_reset": [("idle", "ops"), ("post_save", "done")],
             "boxes_reload": [("idle", "done")]}


def receipt_path(title: str, *, repo: Path = REPO) -> Path:
    return repo / "tests/fixtures/gen2/receipts" / f"{title}.write_window.json"


def sram_flat(bank: int, address: int) -> int:
    """CartRAM offset of an SRAM bank:address (8 KiB banks at $A000)."""
    assert 0xA000 <= address < 0xC000, address
    return bank * 0x2000 + address - 0xA000


def offsets(symbols, current_box: int) -> dict:
    """Raw persistence offsets from the pinned .sym alone: the saved party HP (sPokemonData image of
    wPartyMon1HP), the active sBox copy and the current box's backing slot sBox<n>."""
    s = symbols
    backing = s[f"sBox{current_box + 1}"]
    return {"party_hp": sram_flat(s["sPokemonData"].bank, s["sPokemonData"].address)
            + s["wPartyMon1HP"].address - s["wPokemonData"].address,
            "dump_party_hp": s["wPartyMon1HP"].address - s["wPartyCount"].address,
            "active": sram_flat(s["sBox"].bank, s["sBox"].address),
            "length": s["sBoxEnd"].address - s["sBox"].address,
            "backing": sram_flat(backing.bank, backing.address)}


def saved_image(directory: Path, fixture: str) -> Path:
    """The post-save SaveRAM image the town gate flushed, digest-checked and kept (lua/tests/
    gen2_write_windows.lua U.saved_path). Never the lane's SaveRAM file: the gate keeps playing after the
    save and Gold/Silver keep the window stack and sScratch in SRAM (tools/gen2_fixtures.py
    SCRATCH_WRITES), so the menu close, the overworld and EmuHawk's exit-time flush rewrite that file."""
    return directory / f"{fixture}.u2_saved.SaveRAM"


def run_record(text: str) -> dict:
    assert "RESULT: PASS" in text.splitlines()[-1], text[-2000:]
    run = live.tag_json(text, "U2_RUN")
    assert run["result"] == "PASS", run["result"]
    return run


def verify_liveness(run: dict, primary: dict) -> None:
    """Accepted holds at the MEASURED checkpoint PC/hROMBank, and a fresh one after every window."""
    pc, bank = primary["execution_before"]["pc"], primary["execution_before"]["bank"]
    hits = run["liveness"]["hits"]
    assert run["liveness"]["accepted"] >= 1 and hits, "no accepted checkpoint hold"
    assert all((hit["pc"], hit["bank"]) == (pc, bank) for hit in hits), ("accepted off the checkpoint", hits)
    at: dict = {}
    for entry in run["phases"]:
        at.setdefault(entry["phase"], entry["accepted"])
    for before, after in REACQUIRE[run["mode"]]:
        assert before in at and after in at and at[after] > at[before], \
            (f"no fresh accepted hold between {before} and {after}", at)


def verify_town(text: str, primary: dict, symbols, cartram: bytes, staged: bytes) -> dict:
    """The town run: the idle-hold writes and the flushed SaveRAM carrying the written party HP and the
    deposit in BOTH the active sBox and its backing slot, which the staged fixture did not hold yet."""
    run = run_record(text)
    verify_liveness(run, primary)
    party, box = run["write"]["party"], run["write"]["box"]
    off = offsets(symbols, box["current_box"])
    assert (box["flat"], box["length"], box["backing_flat"]) == (off["active"], off["length"], off["backing"]), \
        ("profile box offsets disagree with the pinned .sym", box, off)
    written, after = bytes.fromhex(party["written_hex"]), bytes.fromhex(box["after_hex"])
    hp, active, backing, n = off["party_hp"], off["active"], off["backing"], off["length"]
    assert staged[hp:hp + 2] != written, "saved party HP already held the written value before the run"
    assert staged[active:active + n] != after, "active sBox already held the deposit before the run"
    assert staged[backing:backing + n] != after, "backing box slot already held the deposit before the run"
    cart = cartram[:CART_RAM_BYTES]
    assert len(cart) == CART_RAM_BYTES and hashlib.sha256(cart).hexdigest() == run["save"]["cartram_sha256"], \
        "flushed SaveRAM differs from the post-save CartRAM the gate hashed"
    assert cart[hp:hp + 2] == written, "party HP not saved"
    assert cart[active:active + n] == after, "active sBox lost the deposit across the native save"
    assert cart[backing:backing + n] == after, "native SaveBox did not copy the external sBox write"
    return run


def verify_reload(text: str, primary: dict, symbols, town: dict, candidate: bytes) -> dict:
    """The cold reload of the town run's flushed save. CONTINUE runs LoadBox (TryLoadSaveFile, C
    engine/menus/save.asm:596-601; G :543), which copies the current box's backing slot sBox<n> over the
    active sBox: the active copy after the reload therefore proves the backing slot carried the deposit
    through the save and the cold boot, and the backing check proves nothing overwrote it since. Both are
    read from the CartRAM the game loaded and ran on (its boot hash taken before the first frame)."""
    run = run_record(text)
    verify_liveness(run, primary)
    assert run["fixture_sha256"] == hashlib.sha256(candidate).hexdigest(), "reload ran on another file"
    assert run["boot_cartram_sha256"] == hashlib.sha256(candidate[:CART_RAM_BYTES]).hexdigest() \
        == town["save"]["cartram_sha256"], "reload did not cold-boot the town run's flushed CartRAM"
    party, box = town["write"]["party"], town["write"]["box"]
    off = offsets(symbols, box["current_box"])
    dump = live.tag_json(text, "DUMP")
    assert dump["party"]["address"] == symbols["wPartyCount"].address, dump["party"]
    at = off["dump_party_hp"] * 2
    assert dump["party"]["hex"][at:at + 4] == party["written_hex"], "party HP did not survive the reload"
    cart, after, n = bytes.fromhex(dump["cartram"]["hex"]), bytes.fromhex(box["after_hex"]), off["length"]
    assert cart[off["active"]:off["active"] + n] == after, "active sBox lost the deposit across the reload"
    assert cart[off["backing"]:off["backing"] + n] == after, "backing box slot lost the deposit across the reload"
    return run


def verify_battle(text: str, primary: dict) -> dict:
    run = run_record(text)
    verify_liveness(run, primary)
    write = run["windows"]["battle"]["write"]
    assert write["faint_refused"] is True and "active faint timing is not qualified" in write["faint_reason"], write
    assert run["battle_model"]["active_slot"] == write["slot"], run["battle_model"]
    return run


def build_receipt(title: str, pack: dict, runs: dict) -> dict:
    """The receipt M.qualified checks: the pack binding, the exact checkpoint rows and the three gate run
    records as printed (their evidence_level is the gate's own), plus the covered controls."""
    return {"schema": RECEIPT_SCHEMA, "title": title, "rom_sha1": pack["source"]["rom_sha1"],
            "pack_commit": pack["source"]["commit"], "checkpoint": pack["titles"][title]["primary"],
            "runs": runs, "covered_controls": list(COVERED_CONTROLS)}


def _module():
    from lupa.lua54 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.eval("dofile")((REPO / "lua/gen2_write_safety.lua").as_posix())


def lua_qualified(pack: dict, title: str, receipt: dict):
    """lua/gen2_write_safety.lua M.qualified (the production check): (scope dict, None) or (None, why)."""
    lua, module = _module()
    result = module.qualified(lua.table_from(pack, recursive=True), title, lua.table_from(receipt, recursive=True))
    scope, why = result if isinstance(result, tuple) else (result, None)
    if scope is None:
        return None, why
    return {"kinds": sorted(scope.kinds.keys()), "covered": list(scope.covered.values()),
            "uncovered": list(scope.uncovered.values())}, None


def lua_bind(receipt: dict, reports: dict):
    """lua/gen2_write_safety.lua M.bind_fixture_qualification: (True, None) or (None, why)."""
    lua, module = _module()
    result = module.bind_fixture_qualification(lua.table_from(receipt, recursive=True),
                                               lua.table_from(reports, recursive=True))
    return result if isinstance(result, tuple) else (result, None)


# --- the live gate ------------------------------------------------------------------------------


def _run(spec, fixture: Path, staged: bytes, mode: str, lane: str, qualification_attempt_id: str,
         extra_env: dict | None = None):
    from run_gb_gate import run_gate
    env = live.inspect_env(spec, staged)
    env.update(extra_env or {})
    case = json.loads(env["SLINK_GEN2_FIXTURE_CASE"])
    case["attempt_id"] = f"u2-{lane}"   # one attempt id per run (M.qualified requires them distinct)
    env["SLINK_GEN2_FIXTURE_CASE"] = json.dumps(case)
    env["SLINK_GEN2_U2"] = json.dumps({"mode": mode, "qualification_attempt_id": qualification_attempt_id})
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
    staged, reports = {}, {}
    for spec in (town_spec, battle_spec):
        staged[spec.name] = (REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM").read_bytes()
        live.qualified_identity(spec.name, staged[spec.name])   # the staged bytes are the qualified candidate
        reports[spec.name] = json.loads((REPO / live.RECEIPTS / f"{spec.name}.qualification.json")
                                        .read_text(encoding="utf-8"))
    pack = json.loads((REPO / f"data/games/gen2_{title}/write_checkpoint.json").read_text(encoding="utf-8"))
    primary = pack["titles"][title]["primary"]
    symbols = gen2_source_data.load_context(title, root=REPO).symbols
    town_q = reports[town_spec.name]["attempt_id"]

    town_fixture = REPO / "tests/fixtures/gen2" / f"{town_spec.name}.SaveRAM"
    directory, text = _run(town_spec, town_fixture, staged[town_spec.name], "town", f"{title}_town", town_q)
    saved = saved_image(directory, town_spec.name)
    town = verify_town(text, primary, symbols, saved.read_bytes(), staged[town_spec.name])

    candidate = REPO / ".cache/gen2-fixtures/u2-write-windows" / f"{title}_town.reload_candidate.SaveRAM"
    shutil.copyfile(saved, candidate)
    _, text = _run(town_spec, candidate, candidate.read_bytes(), "reload", f"{title}_town_reload", town_q)
    reload = verify_reload(text, primary, symbols, town, candidate.read_bytes())

    battle_fixture = REPO / "tests/fixtures/gen2" / f"{battle_spec.name}.SaveRAM"
    _, text = _run(battle_spec, battle_fixture, staged[battle_spec.name], "battle", f"{title}_battle",
                   reports[battle_spec.name]["attempt_id"])
    battle = verify_battle(text, primary)
    for spec in (town_spec, battle_spec):
        assert (REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM").read_bytes() == staged[spec.name], \
            f"{spec.name} changed while the gates ran"

    receipt = build_receipt(title, pack, {"town": town, "reload": reload, "battle": battle})
    scope, why = lua_qualified(pack, title, receipt)
    assert scope is not None, why
    bound, why = lua_bind(receipt, reports)
    assert bound is True, why
    if title == "gold":
        silver = json.loads((REPO / "data/games/gen2_silver/write_checkpoint.json").read_text(encoding="utf-8"))
        assert lua_qualified(silver, "silver", receipt)[0] is not None
    receipt_path(title).write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{title}: write kinds {scope['kinds']}; covered {scope['covered']}; OPEN {scope['uncovered']}")


# --- card BOX: the box runs (boxes, boxes_reset, boxes_reload), added to the committed receipt ------------
# lua/tests/gen2_write_windows.lua U.box_main: two scripted catches + native saves, the PRODUCTION executor
# (lua/gen2/boxes.lua) at accepted holds, an UNSAVED flush (the reset-before-save control image), its cold
# boot + completing ops + a native save, and that save's cold boot. Offsets below come from the pinned .sym.
PARTY_BLOCK, BOX_COPY = 428, 1102


def box_offsets(symbols, current_box: int) -> dict:
    s = symbols
    flat = lambda name: sram_flat(s[name].bank, s[name].address)   # noqa: E731
    return {"party": flat("sPokemonData") + s["wPartyCount"].address - s["wPokemonData"].address,
            "active": flat("sBox"), "backing": flat(f"sBox{current_box + 1}"), "memorial": flat("sBox14"),
            "length": s["sBoxEnd"].address - s["sBox"].address}


def reset_image(directory: Path, fixture: str) -> Path:
    return directory / f"{fixture}.u2_reset.SaveRAM"


def _image(cart: bytes, off: dict) -> dict:
    """party / active / backing / memorial hex of one CartRAM image, from the .sym offsets alone."""
    n = off["length"]
    return {"party_hex": cart[off["party"]:off["party"] + PARTY_BLOCK].hex(),
            "active_hex": cart[off["active"]:off["active"] + n].hex(),
            "backing_hex": cart[off["backing"]:off["backing"] + n].hex(),
            "memorial_hex": cart[off["memorial"]:off["memorial"] + n].hex()}


def _bound_layout(run: dict, symbols) -> dict:
    off = box_offsets(symbols, run["layout"]["current_box"])
    assert off["length"] == BOX_COPY, off
    assert (run["layout"]["active_flat"], run["layout"]["memorial_flat"]) == (off["active"], off["memorial"]), \
        ("run layout disagrees with the pinned .sym", run["layout"], off)
    return off


def _hashed(image: bytes, digest: str) -> bytes:
    cart = image[:CART_RAM_BYTES]
    assert len(cart) == CART_RAM_BYTES and hashlib.sha256(cart).hexdigest() == digest, "flushed image differs"
    return cart


def verify_boxes(text: str, primary: dict, symbols, saved: bytes, reset: bytes) -> dict:
    """Two catches saved natively; four ops; the unsaved flush holds the active and backing edits in SRAM while
    the saved party (sPokemonData) and the backing slot of the current box are the pre-op bytes."""
    run = run_record(text)
    verify_liveness(run, primary)
    off, ops = _bound_layout(run, symbols), run["ops"]
    saved_img = _image(_hashed(saved, run["save"]["cartram_sha256"]), off)
    assert saved_img["party_hex"] == ops[0]["party_before_hex"] and saved_img["party_hex"][:2] == "03", \
        "the native save does not hold the lead and both catches"
    reset_img = _image(_hashed(reset, run["reset"]["cartram_sha256"]), off)
    assert reset_img["party_hex"] == saved_img["party_hex"], "the unsaved flush changed the saved party"
    assert reset_img["active_hex"] == ops[3]["changed"][0]["after_hex"], "the active edit is not in SRAM"
    assert reset_img["backing_hex"] == ops[0]["changed"][0]["before_hex"], "the backing slot was written"
    assert reset_img["memorial_hex"] == ops[2]["changed"][0]["after_hex"], "the memorial edit is not in sBox14"
    return run


def verify_boxes_reset(text: str, primary: dict, symbols, boxes: dict, candidate: bytes, saved: bytes) -> dict:
    """The reset control (the unsaved image cold-booted) and the completing ops' native save."""
    run = run_record(text)
    verify_liveness(run, primary)
    assert run["fixture_sha256"] == hashlib.sha256(candidate).hexdigest(), "reset ran on another file"
    assert run["boot_cartram_sha256"] == hashlib.sha256(candidate[:CART_RAM_BYTES]).hexdigest() \
        == boxes["reset"]["cartram_sha256"], "reset did not cold-boot the unsaved flush"
    off, a, b, k = _bound_layout(run, symbols), boxes["ops"], run["ops"], run["control"]
    assert k["party_hex"] == a[0]["party_before_hex"], "reset: the party is not the saved one"
    assert k["active_hex"] == k["backing_hex"] == a[0]["changed"][0]["before_hex"], "reset: the active edit survived"
    assert k["memorial_hex"] == a[2]["changed"][0]["after_hex"], "reset: the backing edit was lost"
    img = _image(_hashed(saved, run["save"]["cartram_sha256"]), off)
    assert img["party_hex"] == b[2]["party_after_hex"], "party not saved"
    assert img["active_hex"] == img["backing_hex"] == b[2]["changed"][0]["after_hex"], "SaveBox did not copy the deposit"
    assert img["memorial_hex"] == b[1]["changed"][0]["after_hex"], "sBox14 lost the withdraw"
    return run


def verify_boxes_reload(text: str, primary: dict, symbols, reset: dict, candidate: bytes) -> dict:
    run = run_record(text)
    verify_liveness(run, primary)
    assert run["boot_cartram_sha256"] == hashlib.sha256(candidate[:CART_RAM_BYTES]).hexdigest() \
        == reset["save"]["cartram_sha256"], "reload did not cold-boot the reset run's save"
    off, b, keep = _bound_layout(run, symbols), reset["ops"], run["persist"]
    assert keep == {"party_hex": b[2]["party_after_hex"], "active_hex": b[2]["changed"][0]["after_hex"],
                    "backing_hex": b[2]["changed"][0]["after_hex"], "memorial_hex": b[1]["changed"][0]["after_hex"]}, \
        "the reload lacks the saved bytes"
    cart = bytes.fromhex(live.tag_json(text, "DUMP")["cartram"]["hex"])
    assert _image(cart, off) == keep, "the dumped CartRAM (sPokemonData, sBox, backing, sBox14) disagrees"
    return run


@pytest.mark.parametrize("title", TITLES)
def test_box_runs(title, emuhawk):  # noqa: F811 - pytest fixture
    """Adds runs boxes/boxes_reset/boxes_reload to the committed <title>.write_window.json and re-qualifies it."""
    from tools import gen2_fixtures, gen2_source_data
    from tests.live.test_gen2_frame_align import u1_facts
    spec = gen2_fixtures.BY_NAME[f"{title}_battle"]
    reason = (live.rom_missing_reason(spec.title) or live.fixture_missing_reason(spec.name)
              or live.receipt_missing_reason(spec.name))
    if reason:
        pytest.skip(reason)
    receipt = json.loads(receipt_path(title).read_text(encoding="utf-8"))
    for mode in ("boxes", "boxes_reset", "boxes_reload"):
        receipt["runs"].pop(mode, None)
    fixture = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
    staged = fixture.read_bytes()
    live.qualified_identity(spec.name, staged)
    report = json.loads((REPO / live.RECEIPTS / f"{spec.name}.qualification.json").read_text(encoding="utf-8"))
    pack = json.loads((REPO / f"data/games/gen2_{title}/write_checkpoint.json").read_text(encoding="utf-8"))
    primary = pack["titles"][title]["primary"]
    ctx = gen2_source_data.load_context(title, root=REPO)
    q = report["attempt_id"]
    facts = {"SLINK_GEN2_U1_FACTS": json.dumps(u1_facts(ctx, gen2_fixtures.route_facts(title, REPO), q))}

    directory, text = _run(spec, fixture, staged, "boxes", f"{title}_boxes", q, facts)
    boxes = verify_boxes(text, primary, ctx.symbols, saved_image(directory, spec.name).read_bytes(),
                         reset_image(directory, spec.name).read_bytes())
    candidate = REPO / ".cache/gen2-fixtures/u2-write-windows" / f"{title}_battle.reset_candidate.SaveRAM"
    shutil.copyfile(reset_image(directory, spec.name), candidate)
    directory, text = _run(spec, candidate, candidate.read_bytes(), "boxes_reset", f"{title}_boxes_reset", q)
    reset = verify_boxes_reset(text, primary, ctx.symbols, boxes, candidate.read_bytes(),
                               saved_image(directory, spec.name).read_bytes())
    candidate = REPO / ".cache/gen2-fixtures/u2-write-windows" / f"{title}_battle.box_reload_candidate.SaveRAM"
    shutil.copyfile(saved_image(directory, spec.name), candidate)
    _, text = _run(spec, candidate, candidate.read_bytes(), "boxes_reload", f"{title}_boxes_reload", q)
    reload = verify_boxes_reload(text, primary, ctx.symbols, reset, candidate.read_bytes())
    assert fixture.read_bytes() == staged, f"{spec.name} changed while the gates ran"

    receipt["runs"].update({"boxes": boxes, "boxes_reset": reset, "boxes_reload": reload})
    scope, why = lua_qualified(pack, title, receipt)
    assert scope is not None, why
    assert set(scope["kinds"]) >= {"party_collection", "box_withdraw", "backing_box"}, scope
    reports = {name: json.loads((REPO / live.RECEIPTS / f"{name}.qualification.json").read_text(encoding="utf-8"))
               for name in (f"{title}_town", f"{title}_battle")}
    bound, why = lua_bind(receipt, reports)
    assert bound is True, why
    if title == "gold":
        silver = json.loads((REPO / "data/games/gen2_silver/write_checkpoint.json").read_text(encoding="utf-8"))
        assert lua_qualified(silver, "silver", receipt)[0] is not None
    receipt_path(title).write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{title}: write kinds {scope['kinds']}")


@pytest.fixture(scope="module")
def emuhawk():
    from gen1_playthrough import EMUHAWK
    if not os.path.exists(EMUHAWK):
        pytest.skip(f"EmuHawk not found at {EMUHAWK}")
    return EMUHAWK
