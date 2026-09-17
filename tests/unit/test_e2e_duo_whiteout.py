"""whiteout_new's two Python halves, off synthetic receipts and fixture bytes.

The scenario itself runs only on the emulator lane, so these pins defend the two things the
lane cannot check cheaply: that the BOTH_BOXED gate reads the SERVER's own field (and refuses
when it is missing or still lists a half), and that the post-result oracle re-derives every
number it can instead of trusting the driver's pass/fail. A trivially-passing oracle would
leave the negative cases here unraised.

The saved-state reads are the real `gen1_codec` over real fixture bytes, seeded through the
same `_add_caught_to_party` the admission pins build their post-run images with. Only
`_saved_gen1_party` (the flush + `qualify()` step, which needs the lane's SaveRAM directory) is
stubbed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

import e2e_duo as duo  # noqa: E402
import test_e2e_duo_admission as adm  # noqa: E402

from server.adapters import gen1_codec as codec  # noqa: E402


def _whiteout_receipts(key_a, boot_a, key_b):
    """Both halves' receipts, in the order duo_gen1_main.lua writes them.

    A's run: deposit, the BOTH_BOXED ack, the fatal hunt (GROWL in slot 2, the starter KO'd by
    the wild foe), one whiteout, the blackout walk to Pallet Town, the halved money, then the
    rebuild's one party_mon and the closing pair of commands. B's: the same deposit and the
    mirrored rebuild, and none of A's blackout markers.
    """
    a_text = "\n".join([
        "PRE_WHITEOUT party=2 box_count=0",
        "AT_CENTER a",
        "DEPOSITED_FOR_REBUILD " + key_a,
        "PC_BOX_AFTER party=1 box=1 count=1",
        "BOTH_BOXED status=true",
        "MONEY_BEFORE 3000",
        "GROWL_SLOT move=2D pp=40",
        "GROWL turn 1 -> faint hp=19",
        "STARTER_KO frame=4010 key=" + boot_a,
        'TX {"event":"whiteout","player":"a","seq":45}',
        "RX rebuild_start text=REBUILDING: RATTATA",
        "BLACKED_OUT_TEXT frame=4200",
        "BLACKOUT_SITE map=0 x=5 y=6",
        "MONEY_AFTER 1500",
        "MONEY_HALVED before=3000 after=1500",
        "RX party_mon key=" + key_a,
        "REBUILD_PARTY_MON " + key_a,
        "SYNC_RETRIEVE_DONE " + key_a,
        "REBUILT party=2 box_count=0",
        "POST_REBUILD party=2 box_count=0",
        "RX rebuild_done",
        "REBUILD_DONE rebuild_start=1 rebuild_done=1",
        "SAVE_WITNESS whiteout_new_a frames=6100",
    ])
    b_text = "\n".join([
        "AT_CENTER b",
        "DEPOSITED_FOR_REBUILD " + key_b,
        "PC_BOX_AFTER party=1 box=1 count=1",
        "BOTH_BOXED status=true",
        "RX party_mon key=" + key_b,
        "REBUILD_PARTY_MON " + key_b,
        "SYNC_RETRIEVE_DONE " + key_b,
        "REBUILT party=2 box_count=0",
        "POST_REBUILD party=2 box_count=0",
        "SAVE_WITNESS whiteout_new_b frames=6200",
    ])
    return a_text, b_text


def _boxed_mon(image, key):
    """A 33-byte box mon whose `codec.key()` IS `key`, from the fixture's own slot-0 struct.

    Field offsets inside a box struct are the party struct's for everything before the stats
    section (gen1_codec._FIELDS: species@0, ot_id@12, DVs@27-28), so the template only needs
    those three overwritten; nothing here recomputes stats, and nothing in this oracle reads
    them.
    """
    dump, ot, species = key.split(":")
    template = image[codec.SRAM_LAYOUT["sPartyData"] + codec.PARTY_LAYOUT["mons"]:
                     codec.SRAM_LAYOUT["sPartyData"] + codec.PARTY_LAYOUT["mons"]
                     + codec.BOX_MON_SIZE]
    blob = bytearray(template)
    blob[codec.BOX_LAYOUT["species"]] = int(species, 16)
    blob[12:14] = int(ot, 16).to_bytes(2, "big")
    blob[27:29] = int(dump, 16).to_bytes(2, "big")
    return bytes(blob)


def _put_boxed_mon(image, key):
    """Write `key` into Box 1 AND its sCurBoxData mirror, as a box close leaves them."""
    layout = codec.BOX_LAYOUT
    start = codec.verify_boxes(image)["boxes"][1]["offset"]
    image[start] = 1
    image[start + layout["species"]] = int(key.split(":")[2], 16)
    image[start + layout["species"] + 1] = codec.SPECIES_END
    image[start + layout["mons"]:start + layout["mons"] + codec.BOX_MON_SIZE] = _boxed_mon(image, key)
    mirror = codec.SRAM_LAYOUT["sCurBoxData"]
    image[mirror:mirror + codec.BOX_SIZE] = image[start:start + codec.BOX_SIZE]


def _whiteout_stub(tmp_path, monkeypatch, box1_hint=False):
    """A DuoRun carrying the scenario's real fixture bytes and the server surfaces it reads.

    Both cartridges end the scenario with the starter plus the rebuilt half in the party and an
    empty active box, which is exactly the state `_add_caught_to_party` over the battle fixture
    produces (the fixture's Box 1 was never touched, so its `sCurBoxData` mirror is empty).
    `box1_hint` is the negative case: A's linked key is left sitting in the current box, in the
    SRAM image AND its mirror, so the oracle has to find it through its own decode.
    """
    a_sram, a_rom = adm._fixture_save("red")
    b_sram, b_rom = adm._fixture_save("blue")
    start = codec.SRAM_LAYOUT["sPartyData"]
    a_image = bytearray(a_sram)
    key_a = adm._add_caught_to_party(a_image, a_rom)
    b_image = bytearray(b_sram)
    key_b = adm._add_caught_to_party(b_image, b_rom)
    if box1_hint:
        _put_boxed_mon(a_image, key_a)
    a_party = codec.decode_party(bytes(a_image)[start:start + codec.PARTY_LAYOUT["size"]])
    b_party = codec.decode_party(bytes(b_image)[start:start + codec.PARTY_LAYOUT["size"]])

    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "whiteout_new"
    run.emus = []
    run.cfg = dict(duo.SCENARIOS["whiteout_new"])
    run.gcfg = dict(duo.GAMES["gen1_new"])
    run.data_dir = str(tmp_path)
    run.go_files = {inst: str(tmp_path / f"duo_go_whiteout_new_{inst}.txt")
                    for inst in ("a", "b")}
    run._boot_keys = {"a": codec.key(a_party[0]), "b": codec.key(b_party[0])}
    run._link_keys = {"a": key_a, "b": key_b}
    run._pydec_note = lambda fact: None
    run._raw_state = lambda: {"_live": {"party_keys": {"a": [], "b": []}}}
    (tmp_path / "links.json").write_text(json.dumps({
        "links": [{"area_id": "route_1", "status": "alive",
                   "a": {"key": key_a}, "b": {"key": key_b}}],
        "run_over": False}), encoding="utf-8")
    (tmp_path / "events.json").write_text(json.dumps([
        {"ts": "2026-09-17T12:00:00", "player": "a", "type": "whiteout",
         "text": "WHITED OUT! All party mons fainted", "area_id": "", "key": ""}]),
        encoding="utf-8")

    mirror = codec.SRAM_LAYOUT["sCurBoxData"]

    def saved(inst, **_kwargs):
        image = bytes(a_image if inst == "a" else b_image)
        party = a_party if inst == "a" else b_party
        return (image, party, codec.decode_box(image[mirror:mirror + codec.BOX_SIZE]), codec)

    monkeypatch.setattr(run, "_saved_gen1_party", saved)
    results = dict(zip(("a", "b"), _whiteout_receipts(key_a, run._boot_keys["a"], key_b),
                       strict=True))
    # `_artifact` compares the receipts' mtime against this, and a filesystem clock that rounds
    # the other way would make this run's own write look stale. Provenance is not what these
    # pins test (test_e2e_duo_admission.py pins the stale path), so the floor is disabled.
    run._started = 0.0
    for inst, text in results.items():
        (tmp_path / f"e2e_whiteout_new_{inst}_result.txt").write_text(text, encoding="utf-8")
    monkeypatch.setattr(run, "_result_path",
                        lambda inst: str(tmp_path / f"e2e_whiteout_new_{inst}_result.txt"))
    return run, results


def _fast_waits(run):
    """The gate's own budgets are minutes (the Lua gives the go-file 900 s); the pin only needs
    the failure path, so the scenario timeout — which both of the gate's waits read — is what
    gets shrunk. The module-level `wait_for` is no longer on this path: DuoRun.wait_for is."""
    run.cfg["timeout"] = 0.2


# ── the oracle ──────────────────────────────────────────────────────────────

def test_whiteout_oracle_reads_the_blackout_and_the_rebuild(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_money_that_was_not_halved(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("MONEY_AFTER 1500", "MONEY_AFTER 1499")
    with pytest.raises(RuntimeError, match=r"3000 -> 1499; the blackout halves it to 1500"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_second_whiteout(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace(
        'TX {"event":"whiteout","player":"a","seq":45}',
        'TX {"event":"whiteout","player":"a","seq":45}\n'
        'TX {"event":"whiteout","player":"a","seq":46}')
    with pytest.raises(RuntimeError, match="sent 2 whiteout"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_whiteout_from_b(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["b"] += '\nTX {"event":"whiteout","player":"b","seq":47}'
    with pytest.raises(RuntimeError, match="B sent a whiteout"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_the_starter_being_named_last_and_killed(
        tmp_path, monkeypatch):
    """The KO key has to be the boot starter: a linked half killed in its own battle means the
    deposit that makes the rebuild possible did not happen."""
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("STARTER_KO frame=4010 key=" + run._boot_keys["a"],
                                        "STARTER_KO frame=4010 key=" + run._link_keys["a"])
    with pytest.raises(RuntimeError, match="not the boot starter"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_blackout_site_that_is_not_pallet(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("BLACKOUT_SITE map=0 x=5 y=6",
                                        "BLACKOUT_SITE map=0 x=6 y=5")
    with pytest.raises(RuntimeError, match="not Pallet Town"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_missing_rebuild_start(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("RX rebuild_start text=REBUILDING: RATTATA\n", "")
    with pytest.raises(RuntimeError, match="rebuild_start x0 and rebuild_done x1"):
        run.assert_whiteout_new_saved(results)


@pytest.mark.parametrize("command", ["rebuild_start", "rebuild_done"])
def test_whiteout_oracle_refuses_a_rebuild_command_on_b(tmp_path, monkeypatch, command):
    """Only the whited-out half gets them (server/state.py:2418-2443, :2448-2462)."""
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["b"] += f"\nRX {command} text=rebuilding"
    with pytest.raises(RuntimeError, match="B received a rebuild command"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_game_over(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("SAVE_WITNESS whiteout_new_a",
                                        "GAME_OVER RX game_over\nSAVE_WITNESS whiteout_new_a")
    with pytest.raises(RuntimeError, match="told the run is over"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_run_marked_over(tmp_path, monkeypatch):
    """The durable half of the same claim: `run_over` rides in links.json (state.py:3089)."""
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    document = json.loads((tmp_path / "links.json").read_text(encoding="utf-8"))
    document["run_over"] = True
    (tmp_path / "links.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match="says the run is over"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_pair_that_died(tmp_path, monkeypatch):
    """The whiteout retires a link only when the whited-out half is still in party_keys; a dead
    route_1 entry means the rebuild had nothing to pull."""
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    document = json.loads((tmp_path / "links.json").read_text(encoding="utf-8"))
    document["links"][0]["status"] = "dead"
    (tmp_path / "links.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match="did not survive the whiteout"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_two_whiteout_rows(tmp_path, monkeypatch):
    """events.json is the server's own ring buffer of inbound events (server.py:1505-1516),
    newest-first — a second row means a second event was accepted."""
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    rows = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    rows.insert(0, dict(rows[0], ts="2026-09-17T12:00:01"))
    (tmp_path / "events.json").write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"carries 2 whiteout row\(s\)"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_saved_box_that_still_holds_the_key(tmp_path, monkeypatch):
    """A's linked key sitting in the current box, in the SRAM image and its sCurBoxData mirror:
    the oracle's own `decode_box` has to find it, not a stubbed box list."""
    run, results = _whiteout_stub(tmp_path, monkeypatch, box1_hint=True)
    with pytest.raises(RuntimeError, match="saved current box still holds"):
        run.assert_whiteout_new_saved(results)


def test_whiteout_oracle_refuses_a_party_without_the_rebuilt_half(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    real = run._saved_gen1_party

    def starter_only(inst, **kwargs):
        sram, party, box, codec_module = real(inst, **kwargs)
        return sram, party[:1], box, codec_module

    monkeypatch.setattr(run, "_saved_gen1_party", starter_only)
    with pytest.raises(RuntimeError, match="expected the starter plus the rebuilt"):
        run.assert_whiteout_new_saved(results)


# ── the BOTH_BOXED gate ─────────────────────────────────────────────────────

def test_orchestrate_runs_the_gate_between_the_link_and_the_blackout():
    """The branch itself: go -> assert_link_new -> the BOTH_BOXED gate, and not the generic
    `assert_real_link_formed` the else-arm would have picked for an unregistered name."""
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "whiteout_new"
    run.cfg = dict(duo.SCENARIOS["whiteout_new"])
    calls = []
    run.wait_keys = lambda: (["AAAA:1111:01"], ["BBBB:2222:02"])
    run.wait_connected = lambda: None
    run.go = lambda lines=None: calls.append("go")
    run.assert_link_new = lambda: calls.append("link")
    run.assert_whiteout_both_boxed = lambda: calls.append("boxed")
    run.assert_real_link_formed = lambda: calls.append("WRONG ARM")
    run.orchestrate()
    assert calls == ["go", "link", "boxed"]


def test_both_boxed_gate_releases_both_halves(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    monkeypatch.setattr(duo, "read_result", lambda scenario, inst: results[inst])
    run.assert_whiteout_both_boxed()
    for inst in ("a", "b"):
        assert "BOTH_BOXED" in Path(run.go_files[inst]).read_text(encoding="utf-8")


def test_both_boxed_gate_names_the_half_the_server_still_lists(tmp_path, monkeypatch):
    """The gate reads `state.party_keys` (server/state.py:2086), not the cartridges' snapshot —
    so a server that still lists A's key must hold both halves at the PC, and say which one."""
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    monkeypatch.setattr(duo, "read_result", lambda scenario, inst: results[inst])
    _fast_waits(run)
    run._raw_state = lambda: {"_live": {"party_keys": {"a": [run._link_keys["a"]], "b": []}}}
    with pytest.raises(RuntimeError, match="a: party_keys still lists"):
        run.assert_whiteout_both_boxed()
    assert not Path(run.go_files["a"]).exists(), "the go-file must not be released"


def test_both_boxed_gate_names_a_missing_field(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    monkeypatch.setattr(duo, "read_result", lambda scenario, inst: results[inst])
    _fast_waits(run)
    run._raw_state = lambda: {"_live": {"party_keys": {"b": []}}}
    with pytest.raises(RuntimeError, match="a: party_keys: the server published no such field"):
        run.assert_whiteout_both_boxed()


def test_both_boxed_gate_waits_for_the_deposit_marker(tmp_path, monkeypatch):
    run, results = _whiteout_stub(tmp_path, monkeypatch)
    results["b"] = results["b"].replace("DEPOSITED_FOR_REBUILD", "PC_BOX_AFTER party=1")
    monkeypatch.setattr(duo, "read_result", lambda scenario, inst: results[inst])
    _fast_waits(run)
    with pytest.raises(RuntimeError, match="the deposit never landed — b: no DEPOSITED_FOR_REBUILD"):
        run.assert_whiteout_both_boxed()
