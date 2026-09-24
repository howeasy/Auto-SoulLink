"""Card DUO-WAVE-D: the four O-33 synthetic-setup duos (gen2_boxed_capture, gen2_gift, gen2_egg_hatch, gen2_npc_trade).
MODEL controls, no emulator: the committed setup bytes are the builder's output, the pure hatch leg and the U1G trade
driver's slot-2 terminal, the per-kind marker verdict (lua/tests/duo/gen2_synth_duo.lua) and the saved-state oracle
(tools/gen2_duo_oracles.synth_duo_oracle). Facts: docs/gen2/reviews/DUO_WAVE_D_FACTS_2026-09-24.md."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.adapters import gen2_codec as codec
from tools import gen2_duo_oracles as oracles, gen2_synth_fixtures as synth

ROOT = Path(__file__).resolve().parents[2]
DUO = ROOT / "lua/tests/duo/gen2_synth_duo.lua"
U1G = ROOT / "lua/tests/gen2_u1g_inputs.lua"
FIX = ROOT / "tests/fixtures/gen2"


# --- the setups ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", synth.DUO_FIXTURES)
def test_committed_setup_is_the_builders_output(name):
    raw, disclosure = synth.build_named(name)
    assert (FIX / f"{name}.SaveRAM").read_bytes() == raw
    assert json.loads((FIX / f"{name}.synth.json").read_text(encoding="utf-8")) == disclosure
    assert disclosure["base_fixture"].endswith("_ot2") == name.endswith("_ot2")


def test_trade_setup_whites_out_first_and_hatches_second():
    _, disclosure = synth.build_named("gold_synth_trade")
    fields = {f["symbol"]: f["new_hex"] for f in disclosure["fields"]}
    assert fields["wStepCount"] == "7e" and fields["wPoisonStepCount"] == "03"
    layout = codec.for_foundation("gold")
    raw, _ = synth.build_named("gold_synth_trade")
    party = codec.decode_saved_party(raw[:oracles.CARTRAM_BYTES], layout, copy_name="primary")["mons"]
    assert [m["is_egg"] for m in party] == [False, True] and party[1]["species_id"] == oracles.BELLSPROUT
    assert party[0]["hp"] == 1 and party[1]["hp"] == 0   # egg HP 0: CheckPlayerPartyForFitMon whites out


# --- the pure legs ---------------------------------------------------------------------------------------------------

def lua_module(path):
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.execute(path.read_text(encoding="utf-8"))


def point(lua, **fields):
    base = {"overworld_ready": True, "battle_mode": 0, "x": 5, "y": 3,
            "can_step": {"Up": False, "Down": True, "Left": True, "Right": True},
            "party": {"count": 2, "species": {1: 161, 2: 0xFD}}}
    base.update(fields)
    return lua.table_from(base, recursive=True)


def buttons(out):
    assert out[0] is not None, out[1]
    return sorted(k for k, v in out[0].items() if v), out[1]


def test_hatch_leg_steps_says_no_to_the_nickname_and_ends_without_an_egg():
    lua, M = lua_module(DUO)
    d = M.hatch_driver()
    assert buttons(d.step(point(lua))) == (["Down"], "step")
    nick = {"overworld_ready": False, "input_ready": True,
            "ui": {"kind": "yes_no", "prompt": "catch_nickname", "items": {1: "YES", 2: "NO"}, "cursor": 1}}
    assert buttons(d.step(point(lua, **nick)))[0] == ["Down"]
    for _ in range(12):
        d.step(point(lua, **nick))
    assert buttons(d.step(point(lua, **dict(nick, ui=dict(nick["ui"], cursor=2)))))[0] == ["A"]
    for _ in range(12):
        d.step(point(lua))
    done = point(lua, party={"count": 2, "species": {1: 161, 2: 16}})
    assert buttons(d.step(done)) == ([], "hatched")


def test_hatch_leg_refuses_an_unmapped_yes_no_and_a_battle():
    lua, M = lua_module(DUO)
    other = {"overworld_ready": False, "input_ready": True,
             "ui": {"kind": "yes_no", "prompt": "save_confirm", "items": {1: "YES", 2: "NO"}, "cursor": 1}}
    assert M.hatch_driver().step(point(lua, **other))[0] is None
    assert M.hatch_driver().step(point(lua, battle_mode=1))[0] is None


def test_u1g_kyle_driver_ends_on_the_traded_slot():
    lua, U = lua_module(U1G)
    facts = {"kind": "kyle", "maps": {}, "received": 95, "give_slot": 1}
    d = U.driver(lua.table_from({}), lua.table_from({}), lua.table_from(facts, recursive=True))
    assert buttons(d.step(point(lua, party={"count": 2, "species": {1: 161, 2: 95}}))) == ([], "done")
    d = U.driver(lua.table_from({}), lua.table_from({}), lua.table_from(dict(facts, give_slot=0), recursive=True))
    assert buttons(d.step(point(lua, party={"count": 2, "species": {1: 95, 2: 69}}))) == ([], "done")


# --- the verdict -----------------------------------------------------------------------------------------------------

KEY, ONIX_KEY = "5B72:B541:45", "5B72:BF1E:5F"
CAPTURE = {"full": ("capture_box_finalized", "wild", "box", "route_29"),
           "bill": ("gift_party_finalized", "gift", "party", "goldenrod_city"),
           "hatch": ("hatch_finalized", "egg_hatch", "party", "gift_daycare"),
           "trade": ("hatch_finalized", "egg_hatch", "party", "gift_daycare")}


def lines(kind):
    j = json.dumps
    site, acq, dest, area = CAPTURE[kind]
    out = ["DUO_GEN2 " + j({"player": "a", "scenario": "x", "attempt": 1, "case": "crystal_town", "title": "crystal",
                            "rom_sha1": "r", "fixture_sha256": "ab" * 32, "synth": f"crystal_synth_{kind}"}),
           "CLIENT " + j({"production_admitted": True, "title": "crystal"}),
           "BOOTED " + j({"frame": 1}), "HELLO " + j({"frame": 2, "ot_id": 46401}),
           "ENGINE_CAPTURE " + j({"frame": 10, "site_id": site, "acquisition": acq, "destination": dest,
                                  "area_id": area, "key": KEY, "species_id": 69}),
           "CAPTURE_SENT " + j({"frame": 10, "key": KEY, "seq": 3}),
           "RX msgbox", "RX_TEXT " + j({"frame": 20, "cmd": "msgbox", "text": "BELLSPROUT and BELLSPROUT linked!"})]
    if kind == "trade":
        out += ["ENGINE_KEY_CHANGE " + j({"frame": 30, "site_id": "npc_trade_finalized", "reason": "npc_trade",
                                          "old_key": KEY, "new_key": ONIX_KEY, "species_id": 95}),
                'TX {"event":"key_change","old_key":"' + KEY + '"}', "RX key_change_ack"]
    out.append("SAVE_WITNESS " + j({"frame": 40, "gate_saves": 1, "client_saves": 1, "flushed_matches": True}))
    return out


def verdict(kind, rows):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    lua.globals().SLINK_DUO = lua.table_from({"wt": str(ROOT)})
    S = lua.execute(DUO.read_text(encoding="utf-8")).new(kind)
    problems, receipt = S.verdict(lua.table_from(rows), json_codec)
    return list(problems.values()), receipt


@pytest.mark.parametrize("kind", sorted(CAPTURE))
def test_verdict_passes_each_kind(kind):
    problems, receipt = verdict(kind, lines(kind))
    assert problems == [] and receipt["key"] == (ONIX_KEY if kind == "trade" else KEY)
    assert receipt["synth"] == f"crystal_synth_{kind}"


@pytest.mark.parametrize("kind,edit,match", [
    ("full", lambda r: [x.replace('"box"', '"party"') for x in r], "no capture_box_finalized"),
    ("hatch", lambda r: [x.replace('"gift_daycare"', '"route_29"') for x in r], "area"),
    ("bill", lambda r: [x for x in r if not x.startswith("RX_TEXT")], "never announced the link"),
    ("trade", lambda r: [x for x in r if not x.startswith("ENGINE_KEY_CHANGE")], "no npc_trade key_change"),
    ("trade", lambda r: [x for x in r if x != "RX key_change_ack"], "not sent and acked"),
    ("hatch", lambda r: r[:-1] + ["RX force_faint key=" + KEY, r[-1]], "death command"),
    ("bill", lambda r: [x.replace(', "synth": "crystal_synth_bill"', "") for x in r], "synthetic"),
    ("hatch", lambda r: r + [r[4]], "two hatch_finalized"),
], ids=["box-not-party", "hatch-area", "gift-unlinked", "trade-no-change", "trade-no-ack", "death", "no-synth", "two"])
def test_verdict_refuses(kind, edit, match):
    problems, receipt = verdict(kind, edit(lines(kind)))
    assert receipt is None and any(match in p for p in problems), problems


# --- the oracle ------------------------------------------------------------------------------------------------------

def hatched_save(name, ot_title="crystal"):
    """The setup with its egg hatched natively (slot 2 a Pidgey, same DVs) - the model of the flushed save."""
    raw = (FIX / f"{name}.SaveRAM").read_bytes()
    edits = {"party": [dict(synth.DUO_RECIPES["hatch"][1]["party"][0]),
                       {"species": "PIDGEY", "level": 5, "moves": ["TACKLE"], "dvs": 0x5B72}]}
    out, _ = synth.build(ot_title, raw, edits, base_name=name)
    layout = codec.for_foundation(ot_title)
    mons = codec.decode_saved_party(out[:oracles.CARTRAM_BYTES], layout, copy_name="primary")["mons"]
    return out, codec.key(mons[1])


def oracle_text(inst, name, save_path, cart, key):
    j = json.dumps
    boot = (FIX / f"{name}.SaveRAM").read_bytes()
    duo = {"player": inst, "scenario": "gen2_egg_hatch", "attempt": 1,
           "case": synth.build_named(name)[1]["base_fixture"], "title": "crystal", "rom_sha1": "deadbeef" * 5,
           "fixture_sha256": hashlib.sha256(boot).hexdigest(), "synth": name}
    witness = {"frame": 50, "save_completed_frame": 49, "gate_saves": 1, "client_saves": 1,
               "cartram_sha256": hashlib.sha256(cart).hexdigest(), "cartram_bytes": len(cart),
               "saveram_path": str(save_path), "saveram_bytes": len(cart) + 22, "flushed_matches": True}
    rows = [f"DUO_GEN2 {j(duo)}", "CLIENT " + j({"title": "crystal", "rom_sha1": "deadbeef" * 5,
                                                   "production_admitted": True}),
            "ENGINE_CAPTURE " + j({"frame": 10, "site_id": "hatch_finalized", "acquisition": "egg_hatch",
                                   "destination": "party", "area_id": "gift_daycare", "key": key, "species_id": 16}),
            f"SAVE_WITNESS {j(witness)}", "RESULT: PASS (x)"]
    return "\n".join(rows)


@pytest.fixture
def hatch_case(tmp_path):
    results, boots, keys = {}, {}, {}
    for inst, name in (("a", "crystal_synth_hatch"), ("b", "crystal_synth_hatch_ot2")):
        save, key = hatched_save(name)
        path = tmp_path / f"{inst}.SaveRAM"
        path.write_bytes(save)
        results[inst] = oracle_text(inst, name, path, save[:oracles.CARTRAM_BYTES], key)
        boots[inst], keys[inst] = FIX / f"{name}.SaveRAM", key
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "links.json").write_text(json.dumps({"links": [{"area_id": "gift_daycare", "status": "alive",
                                                             "a": {"key": keys["a"]}, "b": {"key": keys["b"]}}]}))
    (data / "slink.log").write_text("INFO hello\n", encoding="utf-8")
    return results, data, boots, keys


def run(case, **changes):
    results, data, boots, _ = case
    return oracles.synth_duo_oracle(results, scenario="gen2_egg_hatch", data_dir=str(data), boot_saveram=boots,
                                    **changes)


def test_oracle_passes_a_hatch_pair(hatch_case):
    facts = []
    assert run(hatch_case, on_verified=facts.append) is None
    assert facts[0]["area"] == "gift_daycare" and facts[0]["a"] == hatch_case[3]["a"]


def test_oracle_refuses_a_link_on_another_key(hatch_case):
    _, data, _, keys = hatch_case
    (data / "links.json").write_text(json.dumps({"links": [{"area_id": "gift_daycare", "status": "alive",
                                                             "a": {"key": keys["b"]}, "b": {"key": keys["a"]}}]}))
    with pytest.raises(RuntimeError, match="links.json a.key"):
        run(hatch_case)


def test_oracle_refuses_a_boot_that_is_not_the_builders_output(hatch_case, tmp_path):
    results, data, boots, _ = hatch_case
    forged = tmp_path / "forged.SaveRAM"
    raw = bytearray(boots["a"].read_bytes())
    raw[-1] ^= 1   # the RTC trailer: the checksummed save still decodes, the bytes are not the builder's
    forged.write_bytes(bytes(raw))
    results = dict(results)
    results["a"] = results["a"].replace(hashlib.sha256(boots["a"].read_bytes()).hexdigest(),
                                        hashlib.sha256(bytes(raw)).hexdigest())
    with pytest.raises(RuntimeError, match="builder"):
        oracles.synth_duo_oracle(results, scenario="gen2_egg_hatch", data_dir=str(data),
                                 boot_saveram={"a": forged, "b": boots["b"]})


def test_oracle_refuses_a_death_command_in_the_server_log(hatch_case):
    (hatch_case[1] / "slink.log").write_text("INFO [a] faint → force_faint b:X\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="death command"):
        run(hatch_case)
