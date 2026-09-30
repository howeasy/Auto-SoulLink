"""Shiny row setup is disclosed; capture/pair/save must still be native."""
import json
from copy import deepcopy

import pytest

from server.adapters import gen3_codec as c
from server.pokemon_data import pid_otid_shiny
from tests.unit.test_e2e_duo_gen3 import STARTER


@pytest.mark.parametrize("game", ["gen3_frlg", "gen3_lgfr", "gen3_emerald", "gen3_rr"])
def test_shiny_native_row_dispatch_and_oracle_are_registered(game):
    from tools import e2e_duo as h
    assert h.scenario_applies("shiny_bonus_gen3", game)
    assert h.SCENARIOS["shiny_bonus_gen3"]["oracle"] == "assert_shiny_bonus_gen3_saved"
    assert callable(h.DuoRun.orchestrate_shiny_bonus_gen3)
    assert callable(h.DuoRun.assert_shiny_bonus_gen3_saved)


@pytest.mark.parametrize("rr", [False, True])
@pytest.mark.parametrize("pid", [0x12345678, 0xABCDEFFA, 0xFEDCBA98])
def test_shiny_setup_preserves_every_decoded_field_except_pid(rr, pid):
    from tools.gen3_shiny_rows import prepare_shiny
    raw = c.encode_party_mon(dict(STARTER, personality=pid), rr=rr)
    before = c.decode_party_mon(raw, rr=rr)
    after, manifest = prepare_shiny(raw, rr=rr, trainer_otid=before["ot_id"])
    decoded = c.decode_party_mon(after, rr=rr)
    assert pid_otid_shiny(decoded["personality"], decoded["ot_id"])
    assert decoded["personality"] != pid
    assert decoded["personality"] % 25 == pid % 25
    assert decoded["personality"] & 255 == pid & 255
    assert {k: v for k, v in decoded.items() if k != "personality"} == {
        k: v for k, v in before.items() if k != "personality"}
    changed = {i for i, (a, b) in enumerate(zip(raw, after, strict=True)) if a != b}
    assert changed <= set(range(4)) | (set() if rr else set(range(32, 80)))
    assert manifest["label"] == "SYNTH wild PID before native capture"
    assert bytes.fromhex(manifest["before"]) == raw and bytes.fromhex(manifest["after"]) == after


def test_shiny_setup_refuses_wrong_trainer_and_bad_checksum():
    from tools.gen3_shiny_rows import prepare_shiny
    raw = c.encode_party_mon(STARTER)
    with pytest.raises(ValueError, match="trainer"):
        prepare_shiny(raw, rr=False, trainer_otid=STARTER["ot_id"] ^ 1)
    corrupt = bytearray(raw)
    corrupt[32] ^= 1
    with pytest.raises(ValueError, match="record"):
        prepare_shiny(bytes(corrupt), rr=False, trainer_otid=STARTER["ot_id"])


@pytest.mark.parametrize("rr", [False, True])
@pytest.mark.parametrize("fault", [None, "stale", "wrong_species", "wrong_scenario", "replay"])
def test_lua_setup_uses_real_decoder_and_refuses_unrelated_or_stale_writes(rr, fault):
    from tests.unit.test_gen3_entry import World
    from tools.gen3_shiny_rows import prepare_shiny
    w = World("gen3_rr" if rr else "gen3_frlg", "radical_red" if rr else "firered")
    raw = c.encode_party_mon(STARTER, rr=rr)
    expected, packet = prepare_shiny(raw, rr=rr, trainer_otid=STARTER["ot_id"])
    base = w.profile["ram"]["ENEMY_BASE"]
    w.poke(base, raw)
    ctx = w.lua.table(reader=w.parts.reads, enemy_base=base,
                      D=w.lua.table(scenario="shiny_bonus_gen3"), wild_ready=lambda _: True)
    setup = w.lua.eval("dofile('lua/tests/duo/shiny_setup.lua')")
    writes = []
    def write(at, value):
        writes.append((at, value))
        w.poke(at, bytes([value]))
    if fault == "stale":
        w.poke(base, bytes([raw[0] ^ 1]))
    elif fault == "wrong_species":
        packet["after"] = c.encode_party_mon(dict(c.decode_party_mon(expected, rr=rr), species=19), rr=rr).hex()
    elif fault == "wrong_scenario":
        ctx.D.scenario = "link_gen3"
    elif fault == "replay":
        ctx.shiny_setup_applied = True
    result = setup.apply(ctx, w.lua.table_from(packet), w.io.read_u8, write)
    if fault:
        assert result[0] is None and writes == []
    else:
        assert result == packet["after_key"]
        assert bytes(w.bus[base+i] for i in range(100)) == expected
        assert len(writes) == 100


def _server_case():
    first = {"a": {"key": "11111111:ABCD1234", "area_id": "route_1"},
             "b": {"key": "22222222:DEADBEEF", "area_id": "route_1"}}
    second = {"a": {"key": "ABCD1234:ABCD1234", "area_id": "route_1"},
              "b": {"key": "33334444:DEADBEEF", "area_id": "route_1"}}
    initial = {"links": [{"area_id": "route_1", "status": "alive", "a": first["a"], "b": first["b"]}],
               "area_states": {"route_1": "linked"}, "bonus_keys": {"a": [], "b": []},
               "pending_bonus": {"a": [], "b": []}}
    pending = deepcopy(initial)
    pending["bonus_keys"]["a"] = [second["a"]["key"]]
    pending["pending_bonus"]["b"] = [second["a"]["key"]]
    final = deepcopy(initial)
    final["links"].append({"area_id": "_bonus_ABCD1234", "status": "alive",
                           "a": {**second["a"], "is_shiny": True}, "b": second["b"]})
    return initial, pending, final, first, second


def test_shiny_server_oracle_requires_entitlement_and_two_distinct_native_pairs():
    from tools.gen3_shiny_rows import server_problems
    case = _server_case()
    assert server_problems(*case, "route_1") == []
    for mutate in (
        lambda p, f: p["pending_bonus"]["b"].clear(),
        lambda p, f: f["pending_bonus"]["b"].append("ABCD1234:ABCD1234"),
        lambda p, f: f["links"][1].update(area_id="route_1"),
        lambda p, f: f["links"][1]["a"].update(is_shiny=False),
        lambda p, f: f["links"].append(deepcopy(f["links"][1])),
        lambda p, f: f["area_states"].update(route_1="unseen"),
        lambda p, f: f["links"][0]["a"].update(key="WRONG"),
    ):
        initial, pending, final, first, second = deepcopy(case)
        mutate(pending, final)
        assert server_problems(initial, pending, final, first, second, "route_1")


def _saved_case(monkeypatch, tmp_path):
    from tests.unit.test_e2e_duo_gen3 import PIDGEY, _fixture, _key, _mon, _oracle_stub, _saved
    from tools import gen3_shiny_rows as rules
    raw = c.encode_party_mon(_mon(0x1122AA44, species=16, level=3))
    prepared, packet = rules.prepare_shiny(raw, rr=False, trainer_otid=STARTER["ot_id"])
    native = {"a": [_mon(0x12121212, species=19, level=3), c.decode_party_mon(prepared)],
              "b": [_mon(0x34343434, species=16, level=3), _mon(0x56565656, species=19, level=3)]}
    def cap(m):
        return {"key": _key(m), "species_id": m["species"], "level": m["level"], "area_id": "route_1"}
    first = {i: cap(native[i][0]) for i in ("a", "b")}
    second = {i: cap(native[i][1]) for i in ("a", "b")}
    fixture = _fixture([STARTER, PIDGEY], balls=20)
    saved = {i: _saved(fixture, 3, [STARTER, PIDGEY, *native[i]], balls=18) for i in ("a", "b")}
    initial = {"links": [{"area_id": "route_1", "status": "alive", "a": first["a"], "b": first["b"]}],
               "area_states": {"route_1": "linked"}, "bonus_keys": {"a": [], "b": []},
               "pending_bonus": {"a": [], "b": []}}
    pending, final = deepcopy(initial), deepcopy(initial)
    pending["bonus_keys"]["a"] = [second["a"]["key"]]
    pending["pending_bonus"]["b"] = [second["a"]["key"]]
    final["links"].append({"area_id": "_bonus_"+second["a"]["key"][:8], "status": "alive",
                           "a": {**second["a"], "is_shiny": True}, "b": second["b"]})
    run, notes = _oracle_stub(monkeypatch, tmp_path, "shiny_bonus_gen3", saved, fixture, final["links"])
    run._shiny_first, run._shiny_second = first, second
    run._shiny_initial, run._shiny_pending, run._shiny_packet = initial, pending, packet
    run._reconnect_document = lambda: final
    results = {i: "".join("TX capture " + row["key"] + " " + json.dumps(row) + "\n" for row in (first[i], second[i]))
               + "THREW 1\nTHREW 1\n" for i in ("a", "b")}
    results["a"] += "SYNTH_SHINY_APPLIED " + json.dumps(packet) + "\n"
    return rules, run, results, saved, native, fixture, notes


def test_saved_shiny_oracle_requires_real_events_native_debit_and_unique_saved_records(monkeypatch, tmp_path):
    from tests.unit.test_e2e_duo_gen3 import PIDGEY, _saved
    rules, run, results, saved, native, fixture, notes = _saved_case(monkeypatch, tmp_path)
    rules.saved_oracle(run, results)
    assert any("shiny exception" in note for note in notes)
    with pytest.raises(RuntimeError, match="two production wild captures"):
        rules.saved_oracle(run, {**results, "b": results["b"].replace("TX capture", "FAKE capture", 1)})
    with pytest.raises(RuntimeError, match="quarantined"):
        rules.saved_oracle(run, {**results, "a": results["a"]+"RX box_mon key="+run._shiny_second["a"]["key"]+"\n"})
    saved["b"] = _saved(fixture, 3, [STARTER, PIDGEY, *native["b"]], balls=19)
    with pytest.raises(RuntimeError, match="Ball debit"):
        rules.saved_oracle(run, results)
    saved["b"] = _saved(fixture, 3, [STARTER, PIDGEY, native["b"][0]], balls=18)
    with pytest.raises(RuntimeError, match="saved ownership"):
        rules.saved_oracle(run, results)
