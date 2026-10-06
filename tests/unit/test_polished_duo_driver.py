"""MODEL tests of the pure parts of tools/polished_live/duo.py (card C8): the two-side evaluator, the per-side
contract/path/env builders and the server-evidence parsers. No emulator, no server: the live run is the receipt."""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("polished_duo", REPO / "tools/polished_live/duo.py")
duo = importlib.util.module_from_spec(_spec)
sys.modules["polished_duo"] = duo
_spec.loader.exec_module(duo)

SHA = duo.INTEGRATED_SHA1
KEYS = ["EFFFFF:D1C2:0A9:00", "DFFFFF:D1C2:087:00", "CFFFFF:D1C2:037:40"]


def hello(**kw):
    h = {"seen": True, "conn": 1, "admission": "admitted", "adapter": duo.ADAPTER, "artifact_kind": duo.KIND,
         "rom_type": "polished_crystal", "rom_sha1": SHA, "party_keys": list(KEYS), "party_count": 3,
         "pc_boxes_generation": 2, "pc_boxes": ["3:AAAAAA:D1C2:019:00"], "server_party_keys": list(KEYS[::-1]),
         "server_pc_boxes_n": 1}
    h.update(kw)
    return h


def side(role, port, reconnect=False, **kw):
    s = {"player": role, "paths": {"rom": f"/l/{role}/rom.gbc", "saveram": f"/l/{role}/s.SaveRAM", "config": f"/l/{role}/c.ini"},
         "client_port": port, "hello": hello(), "reconnect": hello(conn=3) if reconnect else None,
         "continuous": None if reconnect else True, "client_writes": 0, "commands": {"noop": 5, "link_panel": 1},
         "exit_marker": True}
    s.update(kw)
    return s


def good():
    return {"a": side("a", 5001), "b": side("b", 5002, reconnect=True)}


def test_good_case_passes():
    assert duo.evaluate(good(), SHA) == (True, [])


def _edit(path_fn):
    def apply(sides):
        path_fn(sides)
        return sides
    return apply


# (id, mutator, the one reason it must produce)
DEFECTS = [
    ("hello_missing", lambda s: s["a"].update(hello={"seen": False}), "a:hello_missing"),
    ("hello_rejected", lambda s: s["b"]["hello"].update(admission="rejected"), "b:hello_rejected"),
    ("adapter_differs", lambda s: s["a"]["hello"].update(adapter="gen2_gsc"), "a:adapter_mismatch"),
    ("artifact_differs", lambda s: s["b"]["hello"].update(artifact_kind="clean"), "b:artifact_kind_mismatch"),
    ("sha_differs", lambda s: s["a"]["hello"].update(rom_sha1="0" * 40), "a:rom_sha1_mismatch"),
    ("party_empty", lambda s: s["a"]["hello"].update(party_keys=[], party_count=0), "a:party_empty"),
    ("party_count_wrong", lambda s: s["b"]["hello"].update(party_count=2), "b:party_incomplete"),
    ("party_not_on_server", lambda s: s["a"]["hello"].update(server_party_keys=KEYS[:2]), "a:party_incomplete"),
    ("box_no_generation", lambda s: s["a"]["hello"].update(pc_boxes_generation=None), "a:box_census_incomplete"),
    ("box_list_missing", lambda s: s["a"]["hello"].update(pc_boxes=None), "a:box_census_incomplete"),
    ("box_not_stored", lambda s: s["a"]["hello"].update(server_pc_boxes_n=0), "a:box_census_refused"),
    ("census_changed", lambda s: s["b"]["reconnect"].update(pc_boxes=[], server_pc_boxes_n=0), "b:census_changed_after_reconnect"),
    ("party_changed", lambda s: s["b"]["reconnect"].update(party_keys=KEYS[::-1]), "b:census_changed_after_reconnect"),
    ("reconnect_hello_rejected", lambda s: s["b"]["reconnect"].update(admission="rejected"), "b/reconnect:hello_rejected"),
    ("reconnect_hello_missing", lambda s: s["b"].update(reconnect={"seen": False}), "b/reconnect:hello_missing"),
    ("no_side_reconnected", lambda s: s["b"].update(reconnect=None, continuous=True), "reconnect_missing"),
    ("a_dropped", lambda s: s["a"].update(continuous=False), "a:disconnected_unexpectedly"),
    ("client_wrote", lambda s: s["a"].update(client_writes=1), "a:write_observed"),
    ("writes_unmeasured", lambda s: s["b"].update(client_writes=-1), "b:write_observed"),
    ("box_mon_sent", lambda s: s["b"]["commands"].update(box_mon=1), "b:command_observed:box_mon"),
    ("force_faint_sent", lambda s: s["a"]["commands"].update(force_faint=2), "a:command_observed:force_faint"),
    ("exit_marker_missing", lambda s: s["b"].update(exit_marker=False), "b:exit_marker_missing"),
    ("shared_rom", lambda s: s["b"]["paths"].update(rom="/l/a/rom.gbc"), "isolation:rom_shared"),
    ("shared_saveram", lambda s: s["b"]["paths"].update(saveram="/l/a/s.SaveRAM"), "isolation:saveram_shared"),
    ("shared_config", lambda s: s["b"]["paths"].update(config="/l/a/c.ini"), "isolation:config_shared"),
    ("shared_port", lambda s: s["b"].update(client_port=5001), "isolation:client_port_shared_or_unknown"),
    ("port_unknown", lambda s: s["a"].update(client_port=None), "isolation:client_port_shared_or_unknown"),
]


@pytest.mark.parametrize("name,mutate,reason", DEFECTS, ids=[d[0] for d in DEFECTS])
def test_single_defect_fails_with_its_own_reason(name, mutate, reason):
    sides = copy.deepcopy(good())
    mutate(sides)
    ok, reasons = duo.evaluate(sides, SHA)
    assert not ok
    assert reasons == [reason], reasons


def test_one_side_only_fails_closed():
    assert duo.evaluate({"a": good()["a"]}, SHA) == (False, ["sides_missing"])


def test_contract_binds_both_players_to_the_overlay():
    c = duo.contract_for(SHA)
    assert c["players"] == {"a": {"rom_sha1": SHA}, "b": {"rom_sha1": SHA}}


def test_paths_are_private_per_side_and_per_launch():
    a, b = duo.side_paths(Path("/lane/run"), "a"), duo.side_paths(Path("/lane/run"), "b")
    for k in ("rom", "saveram", "config", "run", "result", "sram_dir"):
        assert a[k] != b[k]
    assert a["rom"].endswith("/" + duo.ROM_NAME) and a["saveram"].endswith("/pol overlay.SaveRAM")
    assert Path(a["rom"]).stem.replace("_", " ") == Path(a["saveram"]).stem   # BizHawk's save-name rule
    again = duo.side_paths(Path("/lane/run"), "a", generation=2)
    assert (again["rom"], again["saveram"], again["config"]) == (a["rom"], a["saveram"], a["config"])
    assert again["run"] != a["run"]


def test_env_names_the_player_and_server():
    p = duo.side_paths(Path("/lane/run"), "b")
    env = duo.side_env(p, "b", "127.0.0.1", 4242)
    assert (env["SLINK_PLAYER"], env["DUO_ROLE"], env["SLINK_PORT"]) == ("b", "b", "4242")
    assert env["POL_OUT"] == p["result"] and env["POL_SYMS"].startswith(p["run"])


def _wire(*recs):
    return duo.parse_wire(list(recs))


def test_parse_wire_counts_hellos_commands_and_connections():
    w = _wire({"dir": "meta", "conn": 1, "msg": {"event": "_connect"}},
              {"dir": "c2s", "conn": 1, "msg": {"event": "hello", "party": []}},
              {"dir": "c2s", "conn": 1, "msg": {"event": "tick"}},
              {"dir": "s2c", "conn": 1, "msg": {"commands": [{"cmd": "noop"}, {"cmd": "box_mon"}]}},
              {"dir": "meta", "conn": 1, "msg": {"event": "_disconnect"}},
              {"dir": "c2s", "conn": 2, "raw": "x", "msg": None})
    assert (w["connects"], w["disconnects"], len(w["hellos"])) == (1, 1, 1)
    assert w["commands"] == {"noop": 1, "box_mon": 1}


def test_parse_log_and_hello_view():
    log = duo.parse_log("2026 [INFO] __main__: Client connected: ('127.0.0.1', 5001)\n"
                        "x [a] admission: admitted — cartridge sha1 matches the contract\n"
                        "x [a] route polished_crystal -> gen2_polished (production)\n"
                        "x Client connected: ('127.0.0.1', 5002)\n"
                        "x [b] admission: rejected — nope\n")
    assert log["ports"] == [5001, 5002] and log["admission"] == {"a": ["admitted"], "b": ["rejected"]}
    rec = {"conn": 1, "msg": {"party": [{"key": "K1"}], "pc_boxes": [{"box": 2, "key": "K9"}], "pc_boxes_generation": 3,
                              "artifact_kind": "overlay", "rom_sha1": SHA}}
    h = duo.hello_view(rec, 0, "a", log, {"party_keys": ["K1"], "pc_boxes": [{}], "admission": "admitted"})
    assert (h["admission"], h["adapter"], h["party_keys"], h["pc_boxes"], h["server_pc_boxes_n"]) == (
        "admitted", "gen2_polished", ["K1"], ["2:K9"], 1)
    assert duo.hello_view(None, 0, "a", log, {}) == {"seen": False}
    assert duo.hello_view(rec, 0, "b", log, {"admission": "rejected"})["admission"] == "rejected"
    # a reconnect logs no admission line: the status verdict carries it; an identity error overrides an "admitted"
    assert duo.hello_view(rec, 1, "a", log, {"admission": "admitted"})["admission"] == "admitted"
    assert duo.hello_view(rec, 1, "a", log, {"admission": "admitted", "identity_error": "WRONG SAVE"})["admission"] == "identity_error"
    assert duo.hello_view(rec, 1, "a", log, {})["admission"] == "none"
