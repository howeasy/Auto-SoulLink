"""The rival_swap_new oracle, off synthetic receipts, fixture bytes and a fake server.

The swap's evidence is the client's own byte-comparison against the command's blobs plus the
server's log (the ack is logged, not ring-buffered) and the outcome-keyed link branch. Each
check removed has to fail its own case here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

import e2e_duo as duo  # noqa: E402
import test_e2e_duo_admission as adm  # noqa: E402

from server.adapters import gen1_codec as codec  # noqa: E402


def _receipt_a(within=12, blobs=2, match=2, sendout=("19", "19"), outcome="win",
               tx_count=1, opponent=225, mismatch=False):
    rows = [
        "RIVAL_EVENTS byte164=83 first=1 wants=1",
        f"RIVAL_BATTLE_BEGIN frame=4000 opponent={opponent}",
        'TX {"event":"trainer_battle_start","player":"a","seq":40,"trainer_id":225}',
    ]
    for index in range(tx_count - 1):
        rows.append(f'TX {{"event":"trainer_battle_start","player":"a","seq":4{index + 1},'
                    f'"trainer_id":225}}')
    rows += [
        f"RX replace_rival_team n={blobs}",
        f"RIVAL_TEAM_REPLACED frame={4000 + within} within={within}",
    ]
    if mismatch:
        rows.append("ENEMY_MONS_MISMATCH slot=1")
    else:
        rows.append(f"ENEMY_MONS_MATCH slots={match}")
    rows += [
        "[SLink-gen1] RIVAL_WINDOW init_frames=12 staged_frames=7",
        f"ENEMY_SENDOUT species={sendout[0]} expected={sendout[1]}",
        f"RIVAL_RESULT {outcome}",
        "RIVAL_DONE",
        "SAVE_WITNESS rival_swap_new_a frames=9000",
    ]
    return "\n".join(rows)


_B_TEXT = "\n".join([
    "RIVAL_IDLE b",
    "SAVE_WITNESS rival_swap_new_b frames=8800",
])


def _stub(tmp_path, monkeypatch, *, a_text=None, outcome="win", link=None, ack="[19, 16]",
          ack_line=True, is_rival=True, b_party=2, party_has_catch=True):
    a_sram, a_rom = adm._fixture_save("red")
    b_sram, b_rom = adm._fixture_save("blue")
    a_image, b_image = bytearray(a_sram), bytearray(b_sram)
    key_a = adm._add_caught_to_party(a_image, a_rom)
    key_b = adm._add_caught_to_party(b_image, b_rom)
    start = codec.SRAM_LAYOUT["sPartyData"]
    parties = {inst: codec.decode_party(bytes(image)[start:start + codec.PARTY_LAYOUT["size"]])
               for inst, image in (("a", a_image), ("b", b_image))}
    if not party_has_catch:
        parties["a"] = parties["a"][:1]

    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "rival_swap_new"
    run.emus = []
    run.cfg = dict(duo.SCENARIOS["rival_swap_new"])
    run.gcfg = dict(duo.GAMES["gen1_new"])
    run.data_dir = str(tmp_path)
    run._pydec_note = lambda fact: None
    run._boot_keys = {"a": codec.key(parties["a"][0]), "b": codec.key(parties["b"][0])}
    run._link_keys = {"a": key_a, "b": key_b}
    default_link = {"area_id": "route_1", "status": "alive", "cause": "",
                    "a": {"key": key_a}, "b": {"key": key_b}}
    if outcome == "loss":
        default_link = {"area_id": "route_1", "status": "memorial", "cause": "whiteout",
                        "a": {"key": key_a}, "b": {"key": key_b}}
    run._links_json = lambda: [link or default_link]
    run._status = lambda: {"players": {"b": {"party_keys": [f"K{i}" for i in range(b_party)]}}}

    def saved(inst, **_kwargs):
        image = bytes(a_image if inst == "a" else b_image)
        return image, parties[inst], [], codec

    monkeypatch.setattr(run, "_saved_gen1_party", saved)
    lines = []
    if is_rival:
        lines.append("[a] trainer_battle_start trainer_id=225 is_rival=True")
    else:
        lines.append("[a] trainer_battle_start trainer_id=225 is_rival=False")
    if ack_line:
        lines.append(f"[a] rival_team_replaced ack trainer_id=225 species={ack}")
    (tmp_path / "slink.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run, {"a": a_text if a_text is not None else _receipt_a(outcome=outcome),
                 "b": _B_TEXT}


def test_rival_swap_oracle_reads_a_won_swap(tmp_path, monkeypatch):
    run, results = _stub(tmp_path, monkeypatch)
    run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_reads_a_lost_swap(tmp_path, monkeypatch):
    """A loss is an ordinary trainer loss with a blackout: the whited-out pair is retired with
    cause whiteout, so the saved-party checks do not apply."""
    run, results = _stub(tmp_path, monkeypatch, outcome="loss",
                         a_text=_receipt_a(outcome="loss"))
    run.assert_rival_swap_new_saved(results)


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"opponent": 226}, "not Rival1's 225"),
    ({"tx_count": 2}, "trainer_battle_start line"),
    ({"within": -1}, "late reply, not a swap"),   # a reply older than the window's own origin
    ({"mismatch": True}, "ENEMY_MONS_MISMATCH"),
    ({"sendout": ("16", "19")}, "not the partner's slot-1"),
    ({"match": 1}, "compare covered 1 slot"),
])
def test_rival_swap_oracle_refuses_a_broken_a_receipt(tmp_path, monkeypatch, kwargs, message):
    run, results = _stub(tmp_path, monkeypatch, a_text=_receipt_a(**kwargs))
    with pytest.raises(RuntimeError, match=message):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_refuses_a_missing_server_ack(tmp_path, monkeypatch):
    run, results = _stub(tmp_path, monkeypatch, ack_line=False)
    with pytest.raises(RuntimeError, match="no rival_team_replaced ack"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_refuses_a_trigger_that_was_not_a_rival(tmp_path, monkeypatch):
    run, results = _stub(tmp_path, monkeypatch, is_rival=False)
    with pytest.raises(RuntimeError, match="never saw A's 225 as a rival"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_refuses_a_blob_count_that_is_not_bs_party(tmp_path, monkeypatch):
    """The command mirrors the PARTNER's current party, so its blob count has to equal B's
    party size as the server sees it."""
    run, results = _stub(tmp_path, monkeypatch, b_party=3)
    with pytest.raises(RuntimeError, match="B's party holds 3"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_refuses_an_ack_that_reads_back_fewer_species(tmp_path, monkeypatch):
    run, results = _stub(tmp_path, monkeypatch, ack="[19]")
    with pytest.raises(RuntimeError, match="read back 1 species for 2"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_refuses_a_dead_pair_after_a_win(tmp_path, monkeypatch):
    run, results = _stub(tmp_path, monkeypatch,
                         link={"area_id": "route_1", "status": "dead", "cause": "battle",
                               "a": {"key": "AAAA:1111:01"}, "b": {"key": "BBBB:2222:02"}})
    with pytest.raises(RuntimeError, match="has to stay alive"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_refuses_a_party_that_lost_the_catch(tmp_path, monkeypatch):
    run, results = _stub(tmp_path, monkeypatch, party_has_catch=False)
    with pytest.raises(RuntimeError, match="expected starter \\+"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_reads_the_window_constants_from_the_client(tmp_path, monkeypatch):
    """A13-r3 replaced RIVAL_SWAP_FRAMES=120 with RIVAL_INIT_FRAMES/RIVAL_STAGED_FRAMES; the
    oracle reads them from the client by name, so a changed constant moves the bound with it."""
    run, results = _stub(tmp_path, monkeypatch, a_text=_receipt_a(within=240))
    run.assert_rival_swap_new_saved(results)          # exactly at the constant passes
    run, results = _stub(tmp_path, monkeypatch, a_text=_receipt_a(within=241))
    with pytest.raises(RuntimeError, match="RIVAL_INIT_FRAMES=240"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_refuses_a_duplicate_apply(tmp_path, monkeypatch):
    """One replacement per battle: an already_applied ack means the command was delivered
    twice, which the client refuses to write again."""
    run, results = _stub(tmp_path, monkeypatch)
    results["a"] += ('\nTX {"event":"rival_team_replaced","player":"a","trainer_id":225,'
                     '"species_ids":[],"error":"already_applied"}')
    with pytest.raises(RuntimeError, match="already_applied"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_oracle_refuses_a_missing_window_line(tmp_path, monkeypatch):
    run, results = _stub(tmp_path, monkeypatch)
    results["a"] = "\n".join(line for line in results["a"].splitlines()
                             if "RIVAL_WINDOW" not in line)
    with pytest.raises(RuntimeError, match="no RIVAL_WINDOW line"):
        run.assert_rival_swap_new_saved(results)


def test_rival_swap_registry_shape():
    entry = duo.SCENARIOS["rival_swap_new"]
    assert entry["flags"] == ["--rival-team-swap"]
    assert entry["target"] == {"a": "battle", "b": "battle"}
    assert entry["no_setup"] is True and entry["oracle"] == "assert_rival_swap_new_saved"
    assert callable(getattr(duo.DuoRun, "assert_rival_swap_new_saved", None))
