"""poison_new's Python half, off synthetic receipts, fixture bytes and a fake server.

The oracle's claims are the game-side trace (PSN bit, blackout flag, halved money, HealParty)
plus one server-side claim that matters: a whiteout with NO link must retire nothing, so the
receipt and events.json carry no memorial and no game_over. Each check removed has to fail its
own case here; the lane is where they run for real.
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


def _bcd3(value):
    """The game's three-byte BCD money, most significant byte first (wram.asm:1761)."""
    return bytes(int(f"{n:02d}", 16) for n in
                 ((value // 10000) % 100, (value // 100) % 100, value % 100))


MONEY_BASE = codec.SRAM_LAYOUT["sMainData"] + duo.SAVED_MONEY_DELTA


def _poison_receipts(starter):
    a_text = "\n".join([
        "POISON_IDLE a",
        "SAVE_WITNESS poison_new_a frames=8800",
    ])
    b_text = "\n".join([
        f"POISON_BASELINE key={starter} faint=0 whiteout=0 no_catch=0 signals=0",
        "POISON_PSN encounters=3 steps=41 status=08",
        "MONEY_BEFORE 3000",
        "POISON_FAINT_SITE frame=1234 slot=0",
        "SIGNAL_ORDER poison_faint->blackout ok faints=1 suffix=3",
        f"TX faint {starter}",
        "TX whiteout x1",
        "BLACKOUT_FLAG frame=1400 value=FF",
        "BLACKOUT_SITE map=0 x=5 y=6",
        "MONEY_AFTER 1500",
        "MONEY_HALVED before=3000 after=1500",
        f"PARTY_HEALED key={starter} hp=20",
        "SAVE_WITNESS poison_new_b frames=9000",
    ])
    return a_text, b_text


def _poison_stub(tmp_path, monkeypatch, *, hp=None, max_hp=None, status=0, money=1500,
                 party=None):
    a_sram, _a_rom = adm._fixture_save("red")
    b_sram, _b_rom = adm._fixture_save("blue")
    a_image = bytearray(a_sram)
    b_image = bytearray(b_sram)
    start = codec.SRAM_LAYOUT["sPartyData"]
    b_party = codec.decode_party(bytes(b_image)[start:start + codec.PARTY_LAYOUT["size"]])
    starter = codec.key(b_party[0])
    # The post-blackout cartridge: the lone starter back at full HP with no status, and the
    # money the blackout left.
    mon0 = start + codec.PARTY_LAYOUT["mons"]  # slot 0's struct, not the species list
    if hp is not None:
        b_image[mon0 + 1:mon0 + 3] = hp.to_bytes(2, "big")
    if max_hp is not None:
        b_image[mon0 + 34:mon0 + 36] = max_hp.to_bytes(2, "big")
    b_image[mon0 + 4] = status
    b_image[MONEY_BASE:MONEY_BASE + 3] = _bcd3(money)
    adm._seal_main(b_image)
    b_party = codec.decode_party(bytes(b_image)[start:start + codec.PARTY_LAYOUT["size"]])
    a_party = codec.decode_party(bytes(a_image)[start:start + codec.PARTY_LAYOUT["size"]])

    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "poison_new"
    run.emus = []
    run.cfg = dict(duo.SCENARIOS["poison_new"])
    run.gcfg = dict(duo.GAMES["gen1_new"])
    run.data_dir = str(tmp_path)
    run._boot_keys = {"a": codec.key(a_party[0]), "b": starter}
    run._pydec_note = lambda fact: None
    run._started = 0.0
    (tmp_path / "links.json").write_text(json.dumps({"links": []}), encoding="utf-8")
    (tmp_path / "events.json").write_text(json.dumps([
        {"ts": "2", "player": "b", "type": "whiteout", "text": "WHITED OUT!"},
        {"ts": "1", "player": "b", "type": "faint", "text": "STARTER fainted"},
    ]), encoding="utf-8")

    def saved(inst, **_kwargs):
        if inst == "a":
            return bytes(a_image), a_party, [], codec
        if party is not None:
            return bytes(b_image), party, [], codec
        return bytes(b_image), b_party, [], codec

    monkeypatch.setattr(run, "_saved_gen1_party", saved)
    results = dict(zip(("a", "b"), _poison_receipts(starter), strict=True))
    for inst, text in results.items():
        (tmp_path / f"e2e_poison_new_{inst}_result.txt").write_text(text, encoding="utf-8")
    monkeypatch.setattr(run, "_result_path",
                        lambda inst: str(tmp_path / f"e2e_poison_new_{inst}_result.txt"))
    return run, results, starter


def test_poison_oracle_reads_the_blackout(tmp_path, monkeypatch):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    run.assert_poison_new_saved(results)


@pytest.mark.parametrize(("old", "new", "message"), [
    ("status=08", "status=00", r"no PSN\s+bit"),
    ("MONEY_AFTER 1500", "MONEY_AFTER 1499", "halves it to 1500"),
    ("value=FF", "value=00", "BLACKOUT_FLAG"),
    ("slot=0", "slot=1", "poison faint site"),
    ("hp=20", "hp=0", "the blackout ends in HealParty"),
    ("SIGNAL_ORDER poison_faint->blackout ok", "SIGNAL_ORDER blackout->poison_faint ok",
     "signal order"),
    ("x=5 y=6", "x=6 y=5", "not Pallet Town"),
    ("POISON_PSN encounters=3 steps=41", "POISON_PSN encounters=0 steps=0", r"POISON_PSN"),
])
def test_poison_oracle_refuses_a_broken_b_receipt(tmp_path, monkeypatch, old, new, message):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    results["b"] = results["b"].replace(old, new, 1)
    with pytest.raises(RuntimeError, match=message):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_money_the_save_does_not_agree_with(tmp_path, monkeypatch):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch, money=1400)
    with pytest.raises(RuntimeError, match="saved money is 1400"):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_a_starter_that_was_not_healed_in_the_save(tmp_path, monkeypatch):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch, hp=3)
    with pytest.raises(RuntimeError, match="is at 3/"):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_a_saved_psn_status(tmp_path, monkeypatch):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch, status=0x08)
    with pytest.raises(RuntimeError, match=r"still carries status \$08"):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_a_run_marked_over(tmp_path, monkeypatch):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    results["b"] = results["b"].replace("SAVE_WITNESS poison_new_b",
                                        "GAME_OVER RX game_over\nSAVE_WITNESS poison_new_b")
    with pytest.raises(RuntimeError, match="told the run is over"):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_a_memorial_row(tmp_path, monkeypatch):
    """No link existed, so `_handle_whiteout` had nothing to retire — a memorialize row would
    mean a pair this scenario never formed was buried (server/state.py:2016-2043)."""
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    rows = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    rows.insert(0, {"ts": "3", "player": "b", "type": "memorialize", "text": "gave up"})
    (tmp_path / "events.json").write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(RuntimeError, match="memorialize row"):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_a_whiteout_older_than_the_faint(tmp_path, monkeypatch):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    (tmp_path / "events.json").write_text(json.dumps([
        {"ts": "2", "player": "b", "type": "faint", "text": "STARTER fainted"},
        {"ts": "1", "player": "b", "type": "whiteout", "text": "WHITED OUT!"},
    ]), encoding="utf-8")
    with pytest.raises(RuntimeError, match="older than the faint row"):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_a_second_faint_row(tmp_path, monkeypatch):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    rows = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    rows.insert(1, {"ts": "1b", "player": "b", "type": "faint", "text": "again"})
    (tmp_path / "events.json").write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(RuntimeError, match="expected one of each"):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_a_second_party_mon(tmp_path, monkeypatch):
    run, results, starter = _poison_stub(tmp_path, monkeypatch)
    real = run._saved_gen1_party
    monkeypatch.setattr(run, "_saved_gen1_party",
                        lambda inst, **kw: (real(inst, **kw)[0],
                                            real(inst, **kw)[1] + [adm._fake_mon("AAAA:1111:01")]
                                            if inst == "b" else real(inst, **kw)[1],
                                            *real(inst, **kw)[2:]) if inst == "b" else real(inst, **kw))
    with pytest.raises(RuntimeError, match="expected the lone starter"):
        run.assert_poison_new_saved(results)


# ── saved_money ─────────────────────────────────────────────────────────────

def test_saved_money_offset_is_the_pret_derivation():
    """sMainData + (wPlayerMoney - wMainDataStart): $D347-$D2F7 = $D346-$D2F6 = +$50, so the
    saved offset is $25A3 + $50 = $25F3 in all three titles (pokered.sym:19158,19167;
    pokeyellow.sym:22386,22395)."""
    assert duo.SAVED_MONEY_DELTA == 0x50
    assert MONEY_BASE == 0x25F3


@pytest.mark.parametrize(("value", "expected"), [
    (0, bytes.fromhex("000000")),
    (3000, bytes.fromhex("003000")),
    (12345, bytes.fromhex("012345")),
    (999999, bytes.fromhex("999999")),
])
def test_saved_money_round_trips_the_bcd_triplet(value, expected):
    image = bytearray(codec.SRAM_SIZE)
    image[MONEY_BASE:MONEY_BASE + 3] = _bcd3(value)
    assert bytes(image[MONEY_BASE:MONEY_BASE + 3]) == expected
    assert duo.saved_money(bytes(image)) == value


# ── the per-instance fixture mechanism ──────────────────────────────────────

@pytest.mark.parametrize(("target", "expected"), [
    ("battle", {"a": "battle", "b": "battle"}),
    ({"a": "town", "b": "battle"}, {"a": "town", "b": "battle"}),
])
def test_target_for_accepts_a_scalar_and_a_per_instance_dict(target, expected):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.cfg = {"target": target}
    assert {inst: run._target_for(inst) for inst in ("a", "b")} == expected


def test_target_defaults_to_town_when_the_scenario_declares_none():
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.cfg = {}
    assert run._target_for("b") == "town"


def test_the_per_instance_target_is_used_only_where_it_is_needed():
    """poison_new (A town, B battle) and rival_swap_new (both battle, spelled per instance
    because the fixture chain is a per-instance decision) are the users; everywhere else a dict
    target would be a deliberate act, so the set is pinned."""
    assert duo.SCENARIOS["poison_new"]["target"] == {"a": "town", "b": "battle"}
    assert duo.SCENARIOS["rival_swap_new"]["target"] == {"a": "battle", "b": "battle"}
    users = {name for name in duo.scenarios_for("gen1_new")
             if isinstance(duo.SCENARIOS[name].get("target"), dict)}
    assert users == {"poison_new", "rival_swap_new"}


def test_seed_instance_save_uses_the_per_instance_target(tmp_path, monkeypatch):
    """The launcher's own half of the mechanism: each instance is seeded from ITS fixture.

    `seed_saveram(title, target, dest_dir)` is called with the scenario's per-instance target —
    if this regressed to the scalar default, B would boot the town fixture and the walk to
    Viridian Forest could not happen at all.
    """
    import run_gb_gate  # noqa: PLC0415

    seeded = []

    def fake_seed(title, target, dest_dir):
        seeded.append((title, target, dest_dir))
        return f"{dest_dir}/{title}_{target}.SaveRAM"

    monkeypatch.setattr(run_gb_gate, "seed_saveram", fake_seed)
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.cfg = dict(duo.SCENARIOS["poison_new"])
    run.gcfg = dict(duo.GAMES["gen1_new"])
    run.data_dir = str(tmp_path)
    run._saveram_dir = lambda inst: str(tmp_path / f"saves_{inst}")
    for inst in ("a", "b"):
        run._seed_instance_save(inst)
    assert [(title, target) for title, target, _dest in seeded] == [
        ("red", "town"), ("blue", "battle")]
    assert [dest for _t, _g, dest in seeded] == [str(tmp_path / "saves_a"),
                                                str(tmp_path / "saves_b")]


def test_poison_oracle_refuses_an_orphan_memorialize_command(tmp_path, monkeypatch):
    """r2 finding 4: an orphan `memorialize` command leaves no events.json row — server.py:1945-1954
    logs the row only when a link's status transitions to memorial — so the receipt and the link
    table are where it shows."""
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    results["b"] += f"\nRX memorialize key={_starter}"
    with pytest.raises(RuntimeError, match="received a memorialize command"):
        run.assert_poison_new_saved(results)


def test_poison_oracle_refuses_a_link_table_that_is_not_empty(tmp_path, monkeypatch):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    (tmp_path / "links.json").write_text(json.dumps({"links": [
        {"area_id": "route_1", "status": "alive", "a": {"key": "AAAA:1111:01"},
         "b": {"key": "BBBB:2222:02"}}]}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="links.json carries 1 formed link"):
        run.assert_poison_new_saved(results)


@pytest.mark.parametrize("command", ["rebuild_start", "rebuild_done", "party_mon"])
def test_poison_oracle_refuses_an_orphan_rebuild_command(tmp_path, monkeypatch, command):
    """H-1c: with no link the server had nothing to rebuild or retrieve, and none of these
    commands produces an events.json row (server.py:1945-1954 logs only on a link transition),
    so the receipts are the only place they can show."""
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    results["b"] += f"\nRX {command} key={_starter}"
    with pytest.raises(RuntimeError, match=f"received a {command} command"):
        run.assert_poison_new_saved(results)


# ── H-2 (k): dead-zone records are not links ────────────────────────────────

_DEAD_ZONE_ROW = {"area_id": "route_1", "a": None, "b": None, "status": "dead",
                  "cause": "dead_zone", "encounter_a": None,
                  "encounter_b": {"key": "", "species": 16}, "initiating_player": "b"}


def test_poison_oracle_accepts_a_dead_zone_only_link_table(tmp_path, monkeypatch):
    """The lane's own table: b ran from an incidental Route 1 encounter and from the
    wrong-species first forest encounter, so two dead-zone records exist. They are area locks,
    not links, and the PYDEC note says how many were counted."""
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    notes = []
    run._pydec_note = notes.append
    (tmp_path / "links.json").write_text(json.dumps({"links": [
        dict(_DEAD_ZONE_ROW), dict(_DEAD_ZONE_ROW, area_id="viridian_forest")]}),
        encoding="utf-8")
    run.assert_poison_new_saved(results)
    assert any("2 dead-zone record(s)" in note for note in notes), notes


@pytest.mark.parametrize("row", [
    dict(_DEAD_ZONE_ROW, a={"key": "AAAA:1111:01"}),                 # a key on a side
    dict(_DEAD_ZONE_ROW, encounter_b={"key": "BBBB:2222:02"}),      # a key in an encounter
    {"area_id": "route_1", "a": None, "b": None, "status": "alive", "cause": ""},  # not a dead zone
])
def test_poison_oracle_refuses_a_formed_link(tmp_path, monkeypatch, row):
    run, results, _starter = _poison_stub(tmp_path, monkeypatch)
    (tmp_path / "links.json").write_text(json.dumps({"links": [row]}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="formed link"):
        run.assert_poison_new_saved(results)


def test_is_formed_link_classifies_both_shapes():
    assert not duo.is_formed_link(_DEAD_ZONE_ROW)
    assert duo.is_formed_link(dict(_DEAD_ZONE_ROW, a={"key": "AAAA:1111:01"}))
    assert duo.is_formed_link({"area_id": "route_1", "status": "alive", "cause": ""})
