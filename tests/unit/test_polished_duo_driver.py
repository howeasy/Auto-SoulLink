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


# ═══════════════════════════ --distinct-identities (two fixtures, two trainers) ═══════════════════════════
A_FIXTURE = Path("F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM")
B_FIXTURE = Path("F:/slink-work/lanes/pol-ident/B.SaveRAM")
B_SHA256 = "f5f19f5d2e3e26e343214722b5116e1aac0c71a1200882a4cc6f58259bc6ca8d"
A_KEYS = ["EFFFFF:D1C2:0A9:00", "DFFFFF:D1C2:087:00", "CFFFFF:D1C2:037:40", "BFFFFF:D1C2:022:00", "AFFFFF:D1C2:055:40"]
B_KEYS = [k.replace(":D1C2:", ":D1C3:") for k in A_KEYS]
FOREIGN_KEYS = [f"11111{i}:D1C2:001:00" for i in range(5)]       # a save that is nobody's fixture


def _ds():
    return duo._derive_save()


def synth_save(name="Aaaaaaa", player_id=0xD1C2, mons=((0x37, 0xCF), (0x22, 0xBF))) -> bytes:
    """A minimal VALID SaveRAM image (markers, version, both checksums, N party mons) built with derive_save's own
    geometry, so the key-derivation helper is tested without the (machine-local) real fixture."""
    ds = _ds()
    buf = bytearray(ds.SAVE_SIZE)
    buf[ds.VERSION_AT:ds.VERSION_AT + 2] = ds.SAVE_VERSION
    for c in ds.ALL_COPIES:
        buf[c.low_marker_at], buf[c.high_marker_at] = ds.LOW_MARKER, ds.HIGH_MARKER
        buf[c.at(ds.ID_OFF):c.at(ds.ID_OFF) + 2] = player_id.to_bytes(2, "big")
        buf[c.at(ds.NAME_OFF):c.at(ds.NAME_OFF) + 8] = ds.pc.encode_text(name, 8)
        buf[c.at(ds.COUNT_OFF)] = len(mons)
        for slot, (species, dv) in enumerate(mons):
            raw = bytearray(ds.pc.PARTY_SIZE)
            raw[0] = species
            raw[6:8] = player_id.to_bytes(2, "big")
            raw[17:20] = bytes([dv, 0xFF, 0xFF])
            raw[31] = 5
            at = c.mon_at(slot)
            buf[at:at + ds.pc.PARTY_SIZE] = raw
            buf[c.ot_at(slot):c.ot_at(slot) + 8] = ds.pc.encode_text(name, 8)
    ds._reseal(buf)
    return bytes(buf)


def synth_pair():
    a = synth_save()
    b, _ = _ds().derive_identity(a, name="Bbbbbbb", player_id=0xD1C3)
    return a, b


def test_fixture_identity_decodes_name_id_and_keys_from_the_bytes():
    a, b = synth_pair()
    ia, ib = duo.fixture_identity(a), duo.fixture_identity(b)
    assert (ia["name"], ia["player_id"], ia["keys"]) == ("Aaaaaaa", 0xD1C2, ["CFFFFF:D1C2:037:00", "BFFFFF:D1C2:022:00"])
    assert (ib["name"], ib["player_id"], ib["keys"]) == ("Bbbbbbb", 0xD1C3, ["CFFFFF:D1C3:037:00", "BFFFFF:D1C3:022:00"])
    assert ia["sha256"].startswith(ia["prefix"]) and len(ia["prefix"]) == 8 and ia["prefix"] != ib["prefix"]


def test_fixture_identity_refuses_what_it_cannot_read():
    a, _ = synth_pair()
    ds = _ds()
    with pytest.raises(duo.FixtureError, match="size"):
        duo.fixture_identity(a[:-1])
    bad_sum = bytearray(a)
    bad_sum[ds.MAIN.checksum_at] ^= 1
    with pytest.raises(duo.FixtureError, match="checksum"):
        duo.fixture_identity(bytes(bad_sum))
    bad_marker = bytearray(a)
    bad_marker[ds.MAIN.low_marker_at] = 0
    with pytest.raises(duo.FixtureError, match="marker"):
        duo.fixture_identity(bytes(bad_marker))
    split = bytearray(a)          # main re-owned and re-sealed, backup left alone: the two copies disagree
    split[ds.MAIN.at(ds.ID_OFF) + 1] ^= 1
    ds._reseal(split)
    with pytest.raises(duo.FixtureError, match="disagree"):
        duo.fixture_identity(bytes(split))


@pytest.mark.skipif(not A_FIXTURE.is_file(), reason="the original warp fixture is a machine-local lane artifact")
def test_original_fixture_keys_are_the_ones_the_live_run_reported():
    ident = duo.fixture_identity(A_FIXTURE.read_bytes())
    assert (ident["name"], ident["player_id"], ident["keys"]) == ("Aaaaaaa", 53698, A_KEYS)
    assert ident["prefix"] == "75c7a5dc"


@pytest.mark.skipif(not B_FIXTURE.is_file(), reason="the derived second save is a machine-local lane artifact")
def test_derived_fixture_keys_carry_the_new_ot_id():
    ident = duo.fixture_identity(B_FIXTURE.read_bytes())
    assert ident["sha256"] == B_SHA256        # present-but-wrong fails: this is the save the live run was written for
    assert (ident["name"], ident["player_id"], ident["keys"]) == ("Bbbbbbb", 53699, B_KEYS)


@pytest.mark.skipif(not (A_FIXTURE.is_file() and B_FIXTURE.is_file()), reason="needs both machine-local saves")
def test_real_fixtures_are_distinct_trainers():
    assert duo.distinct_refusals(duo.fixture_identity(A_FIXTURE.read_bytes()), duo.fixture_identity(B_FIXTURE.read_bytes())) == []


def test_resolve_fixtures_precedence():
    env = {"POL_FIXTURE": "/c/common", "POL_FIXTURE_A": "/c/a_env", "POL_FIXTURE_B": "/c/b_env"}
    assert duo.resolve_fixtures("/cli/a", None, env) == (Path("/cli/a"), Path("/c/b_env"))
    assert duo.resolve_fixtures(None, "/cli/b", env) == (Path("/c/a_env"), Path("/cli/b"))
    assert duo.resolve_fixtures(None, None, {"POL_FIXTURE": "/c/common"}) == (Path("/c/common"), Path("/c/common"))
    assert duo.resolve_fixtures(None, None, {}) == (Path(duo.DEFAULT_FIXTURE), Path(duo.DEFAULT_FIXTURE))


def test_distinct_refusals_name_every_shared_fact():
    a, b = synth_pair()
    ia, ib = duo.fixture_identity(a), duo.fixture_identity(b)
    assert duo.distinct_refusals(ia, ib) == []
    assert set(duo.distinct_refusals(ia, ia)) == {"fixtures_byte_identical", "player_id_shared", "player_name_shared",
                                                  "party_keys_overlap"}
    same_id, _ = _ds().derive_identity(a, name="Zzzzzzz", player_id=0xD1C2)     # new name, same ID: keys and ID collide
    assert set(duo.distinct_refusals(ia, duo.fixture_identity(same_id))) == {"player_id_shared", "party_keys_overlap"}
    same_name, _ = _ds().derive_identity(a, name="Aaaaaaa", player_id=0xD1C3)
    assert duo.distinct_refusals(ia, duo.fixture_identity(same_name)) == ["player_name_shared"]


def _args(distinct, fa=None, fb=None):
    return duo.parse_args((["--distinct-identities"] if distinct else [])
                          + (["--fixture-a", str(fa)] if fa else []) + (["--fixture-b", str(fb)] if fb else []))


def test_distinct_mode_refuses_to_start_on_identical_fixtures(tmp_path):
    a, b = synth_pair()
    fa, fa2, fb = tmp_path / "a.SaveRAM", tmp_path / "a_copy.SaveRAM", tmp_path / "b.SaveRAM"
    fa.write_bytes(a)
    fa2.write_bytes(a)
    fb.write_bytes(b)
    with pytest.raises(SystemExit, match="fixtures_byte_identical"):
        duo.plan_fixtures(_args(True, fa, fa2))
    with pytest.raises(SystemExit, match="fixtures_byte_identical"):
        duo.plan_fixtures(_args(True, fa, fa))
    fixtures, ident = duo.plan_fixtures(_args(True, fa, fb))
    assert (ident["a"]["name"], ident["b"]["name"]) == ("Aaaaaaa", "Bbbbbbb") and fixtures["b"] == fb
    # the default (single-fixture) mode is unchanged: identical fixtures are the smoke, recorded not refused
    _, same = duo.plan_fixtures(_args(False, fa, fa2))
    assert same["a"]["sha256"] == same["b"]["sha256"]


def test_distinct_mode_refuses_a_shared_player_id_or_name(tmp_path):
    a, _ = synth_pair()
    twin, _ = _ds().derive_identity(a, name="Bbbbbbb", player_id=0xD1C2)
    other, _ = _ds().derive_identity(a, name="Aaaaaaa", player_id=0xD1C3)
    paths = {}
    for n, data in (("a", a), ("twin", twin), ("other", other)):
        paths[n] = tmp_path / f"{n}.SaveRAM"
        paths[n].write_bytes(data)
    with pytest.raises(SystemExit, match="player_id_shared"):
        duo.plan_fixtures(_args(True, paths["a"], paths["twin"]))
    with pytest.raises(SystemExit, match="player_name_shared"):
        duo.plan_fixtures(_args(True, paths["a"], paths["other"]))


def test_unreadable_fixture_is_refused_not_guessed(tmp_path):
    bad = tmp_path / "junk.SaveRAM"
    bad.write_bytes(b"\0" * 100)
    good = tmp_path / "g.SaveRAM"
    good.write_bytes(synth_save())
    with pytest.raises(SystemExit, match="unreadable"):
        duo.plan_fixtures(_args(False, good, bad))
    with pytest.raises(SystemExit, match="unreadable"):
        duo.plan_fixtures(_args(False, good, tmp_path / "missing.SaveRAM"))


def test_each_side_stages_its_own_fixture_in_private_dirs(tmp_path):
    a, b = synth_pair()
    fa, fb = tmp_path / "a.SaveRAM", tmp_path / "b.SaveRAM"
    fa.write_bytes(a)
    fb.write_bytes(b)
    run = tmp_path / "run"
    pa, pb = duo.side_paths(run, "a"), duo.side_paths(run, "b")
    sha_a, sha_b = duo.stage_side(pa, b"ROM", fa), duo.stage_side(pb, b"ROM", fb)
    assert Path(pa["saveram"]).read_bytes() == a and Path(pb["saveram"]).read_bytes() == b
    assert sha_a == duo.fixture_identity(a)["sha256"] and sha_b == duo.fixture_identity(b)["sha256"] and sha_a != sha_b
    assert Path(pa["saveram"]).parent != Path(pb["saveram"]).parent and Path(pa["rom"]) != Path(pb["rom"])
    fa.write_bytes(b"changed after staging")      # the copy is private: the fixture is never what a side boots from
    assert Path(pa["saveram"]).read_bytes() == a


def test_hello_view_exposes_the_identity_the_server_holds():
    log = duo.parse_log("")
    rec = {"conn": 1, "msg": {"party": [{"key": "K1"}], "pc_boxes": [], "pc_boxes_generation": 3, "ot_id": 53699,
                              "trainer_name": "Bbbbbbb"}}
    h = duo.hello_view(rec, 0, "b", log, {"party_keys": ["K1"], "trainer_name": "Bbbbbbb", "admission": "admitted"})
    assert (h["ot_id"], h["trainer_name"], h["server_trainer_name"], h["identity_error"]) == (53699, "Bbbbbbb", "Bbbbbbb", "")
    h = duo.hello_view(rec, 0, "b", log, {"identity_error": "WRONG SAVE"})
    assert h["identity_error"] == "WRONG SAVE" and h["admission"] == "identity_error"


# ── the distinct-identities evaluator ──
EXP = {"a": {"keys": A_KEYS, "player_id": 53698, "name": "Aaaaaaa"}, "b": {"keys": B_KEYS, "player_id": 53699, "name": "Bbbbbbb"}}


def dside(role, port, reconnect=False):
    keys, ident = (A_KEYS, EXP["a"]) if role == "a" else (B_KEYS, EXP["b"])
    ids = {"party_keys": list(keys), "server_party_keys": list(keys[::-1]), "party_count": len(keys),
           "ot_id": ident["player_id"], "trainer_name": ident["name"], "server_trainer_name": ident["name"],
           "identity_error": ""}
    s = side(role, port, reconnect=reconnect, hello=hello(**ids))
    if reconnect:
        s["reconnect"] = hello(conn=3, **ids)
    else:
        s["final"] = {"trainer_name": ident["name"], "party_keys": list(keys), "identity_error": ""}
    return s


def dgood():
    return {"a": dside("a", 5001), "b": dside("b", 5002, reconnect=True)}


def test_distinct_good_case_passes():
    assert duo.evaluate_distinct(dgood(), SHA, EXP) == (True, [])


def _swap_in_a(h):      # make a hello/reconnect look like fixture a booted: keys, OT id, trainer, server trainer
    h.update(party_keys=list(A_KEYS), server_party_keys=list(A_KEYS), ot_id=53698, trainer_name="Aaaaaaa",
             server_trainer_name="Aaaaaaa")


def _b_boots_a(s):
    _swap_in_a(s["b"]["hello"])
    _swap_in_a(s["b"]["reconnect"])


def _both_b(s, **kw):
    for h in (s["b"]["hello"], s["b"]["reconnect"]):
        h.update(**kw)


def _a_shows(s, keys=None, name=None):
    """What a really shows (wire hello, server status, and the status read after b reconnected): keys and/or trainer name."""
    h, fin = s["a"]["hello"], s["a"]["final"]
    if keys is not None:
        h.update(party_keys=list(keys), server_party_keys=list(keys), party_count=len(keys))
        fin.update(party_keys=list(keys))
    if name is not None:
        h.update(trainer_name=name, server_trainer_name=name)
        fin.update(trainer_name=name)


def _reconnect_new_identity(s):
    s["b"]["reconnect"].update(ot_id=53700, trainer_name="Cccccc", server_trainer_name="Cccccc")


DDEFECTS = [
    ("b_booted_fixture_a", _b_boots_a,
     ["b/reconnect:booted_other_fixture", "b:booted_other_fixture", "identity:ot_id_shared", "identity:party_keys_identical",
      "identity:trainer_name_shared"]),
    ("same_keys_on_both_sides_only", lambda s: _both_b(s, party_keys=list(A_KEYS), server_party_keys=list(A_KEYS)),
     ["b/reconnect:booted_other_fixture", "b:booted_other_fixture", "identity:party_keys_identical"]),
    ("same_trainer_name", lambda s: _both_b(s, trainer_name="Aaaaaaa", server_trainer_name="Aaaaaaa"),
     ["b/reconnect:trainer_name_not_from_fixture", "b:trainer_name_not_from_fixture", "identity:trainer_name_shared"]),
    ("same_ot_id", lambda s: _both_b(s, ot_id=53698),
     ["b/reconnect:ot_id_not_from_fixture", "b:ot_id_not_from_fixture", "identity:ot_id_shared"]),
    ("identity_error_on_a", lambda s: s["a"]["hello"].update(identity_error="WRONG SAVE"), ["a:identity_error_present"]),
    ("identity_error_on_b_reconnect", lambda s: s["b"]["reconnect"].update(identity_error="WRONG SAVE"),
     ["b/reconnect:identity_error_present"]),
    ("a_keys_not_from_its_fixture", lambda s: _a_shows(s, keys=FOREIGN_KEYS),
     ["a:party_keys_not_from_fixture"]),
    ("a_ot_id_not_from_its_fixture", lambda s: s["a"]["hello"].update(ot_id=1), ["a:ot_id_not_from_fixture"]),
    ("a_name_not_from_its_fixture", lambda s: _a_shows(s, name="Zz"), ["a:trainer_name_not_from_fixture"]),
    ("server_name_differs_from_wire", lambda s: s["b"]["hello"].update(server_trainer_name="Other"),
     ["b:server_trainer_name_differs"]),
    ("key_sets_overlap_partially", lambda s: _a_shows(s, keys=[B_KEYS[0]] + A_KEYS[1:]),
     ["a:party_keys_not_from_fixture", "identity:party_keys_overlap"]),
    ("reconnect_changed_b_keys", lambda s: s["b"]["reconnect"].update(party_keys=B_KEYS[:4], party_count=4,
                                                                       server_party_keys=B_KEYS[:4]),
     ["b/reconnect:party_keys_not_from_fixture", "b:census_changed_after_reconnect"]),
    ("reconnect_changed_b_identity", _reconnect_new_identity,
     ["b/reconnect:ot_id_not_from_fixture", "b/reconnect:trainer_name_not_from_fixture", "b:identity_changed_after_reconnect"]),
    ("a_changed_while_b_reconnected", lambda s: s["a"]["final"].update(party_keys=A_KEYS[:3]),
     ["a:identity_changed_while_peer_reconnected"]),
    ("a_renamed_while_b_reconnected", lambda s: s["a"]["final"].update(trainer_name="Other"),
     ["a:identity_changed_while_peer_reconnected"]),
    ("a_final_identity_error", lambda s: s["a"]["final"].update(identity_error="WRONG SAVE"),
     ["a:final_identity_error_present"]),
    ("a_final_missing", lambda s: s["a"].pop("final"), ["a:final_identity_missing"]),
    ("hello_missing_stays_the_evaluators_reason", lambda s: s["a"].update(hello={"seen": False}), ["a:hello_missing"]),
    ("base_defect_still_caught", lambda s: s["b"].update(client_writes=1), ["b:write_observed"]),
]


@pytest.mark.parametrize("name,mutate,reasons", DDEFECTS, ids=[d[0] for d in DDEFECTS])
def test_distinct_single_defect_fails_with_its_own_reasons(name, mutate, reasons):
    sides = copy.deepcopy(dgood())
    mutate(sides)
    ok, got = duo.evaluate_distinct(sides, SHA, EXP)
    assert not ok
    assert sorted(got) == sorted(reasons), got


def test_distinct_expected_fixtures_must_themselves_be_distinct():
    same = {"a": EXP["a"], "b": EXP["a"]}
    ok, got = duo.evaluate_distinct(dgood(), SHA, same)
    assert not ok and "identity:expected_fixtures_not_distinct" in got
    assert duo.evaluate_identities(dgood(), {"a": EXP["a"]}) == ["identity:expected_missing"]
    assert duo.evaluate_identities({"a": dgood()["a"]}, EXP) == ["identity:expected_missing"]


def test_one_identity_on_both_sides_is_a_pass_only_in_the_single_fixture_mode():
    """The old mode is untouched: ONE identity on both sides passes `evaluate`, and exactly the distinct evaluator refuses it."""
    sides = dgood()
    _b_boots_a(sides)
    assert duo.evaluate(sides, SHA) == (True, [])
    assert duo.evaluate_distinct(sides, SHA, EXP)[0] is False


# red controls: neuter the evaluator in-process and show the defects would have PASSED, i.e. each check is load-bearing
IDENTITY_ONLY = [d for d in DDEFECTS if d[0] not in ("hello_missing_stays_the_evaluators_reason", "base_defect_still_caught",
                                                     "reconnect_changed_b_keys")]


def test_red_control_without_the_identity_layer_every_identity_defect_passes(monkeypatch):
    monkeypatch.setattr(duo, "evaluate_identities", lambda sides, expected: [])
    assert len(IDENTITY_ONLY) >= 10
    for name, mutate, _ in IDENTITY_ONLY:
        sides = copy.deepcopy(dgood())
        mutate(sides)
        assert duo.evaluate_distinct(sides, SHA, EXP) == (True, []), name


def test_red_control_without_the_per_side_check_only_the_cross_side_checks_remain(monkeypatch):
    monkeypatch.setattr(duo, "_identity_reasons", lambda tag, h, own, other: [])
    sides = copy.deepcopy(dgood())
    _b_boots_a(sides)
    ok, got = duo.evaluate_distinct(sides, SHA, EXP)
    assert not ok and not [r for r in got if "fixture" in r]          # the booted-the-wrong-file reasons are gone ...
    assert "identity:party_keys_identical" in got                    # ... but two sides showing one identity still fails
    sides = copy.deepcopy(dgood())
    _a_shows(sides, keys=FOREIGN_KEYS)                   # a booted a file that is nobody's fixture
    assert duo.evaluate_distinct(sides, SHA, EXP) == (True, [])        # ... which only the per-side check can see
