"""G2 live wild CAPTURE on HG (lua/tests/probe_gen4_catch.lua), SYNTH bag setup.

Offline: python -m pytest tests/live/test_gen4_catch.py -m 'not live' -q
Live (own lane <LANE_ROOT>/catch, one EmuHawk at a time, own PIDs only):
  SLINK_LIVE=1 python -m pytest tests/live/test_gen4_catch.py -m live -q -rs
Inputs: <LANE_ROOT>/saves/hg_base_26310_bag.SaveRAM (+ .synth.json, `tools/gen4_synth_save.py bag`) and the settled wild
battle state the C1-9 route tool leaves for it (`gen4_routes.py run --save <bag> --lane catch --tag catchhg`).
Oracle (independent of the probe's writes: it writes NOTHING): the game's result byte bs+0x2420 == 4, the live party
growing 1 -> 2 with the new key's PID equal to the foe's battleMons[1] PID, then a codec decode of the lane battery after
the native SAVE. Absent inputs skip by name; present-but-wrong fails."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.test_gen4_evidence import model_surface  # noqa: F401
from tools import gen4_evidence, gen4_fixtures as g4, gen4_pins

pytestmark = pytest.mark.usefixtures("model_surface")

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "lua/tests/probe_gen4_catch.lua"
# SLINK_GEN4_CATCH_GAME=hge runs the same probe on hg-engine (lane catch_hge, hge bag save, hge pack title). The UI code
# is byte-identical (pack ui_geometry code_identity) but hge's Balls pocket has 26 slots, so the keys are verified live.
GAME = os.environ.get("SLINK_GEN4_CATCH_GAME", "HG")
TITLES = {
    "HG": {
        "lane": g4.lane_root() / "catch",
        "bag": "hg_base_26310_bag",
        "title": "heartgold",
        "pack": "gen4_hgss",
        "codec": "hgss",
        "pin": "heartgold",
        "tag": "catchhg",
    },
    "SS": {
        "lane": g4.lane_root() / "catch_ss",
        "bag": "ss_bag",
        "title": "soulsilver",
        "pack": "gen4_hgss",
        "codec": "hgss",
        "pin": "soulsilver",
        "tag": "catchhg",
    },
    "hge": {
        "lane": g4.lane_root() / "catch_hge",
        "bag": "hge_bag",
        "title": "heartgold_hge",
        "pack": "gen4_hge",
        "codec": "hge",
        "pin": "heartgold_hge",
        "tag": "catchhg",
    },
}[GAME]
LANE_ROOT = TITLES["lane"]
BAG_SAVE = g4.lane_root() / "saves" / f"{TITLES['bag']}.SaveRAM"
EMUHAWK = Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe"))
INITIAL_TIME = "2010-01-01T12:00:00"
# Menu path from the settled FIGHT menu to a thrown ball. The first three keys are the pack's recipe
# (data/games/gen4_hgss/profile.json ui_geometry.battle_main_cursor / battle_paths: X wakes the cursor, Left, Left reaches
# column 0, Down is row 1 = BAG). The bag screen is NOT in the pack; its keys come from live screenshots (see EXPLORED).
WAKE_TO_BAG = [
    {"k": "X", "hold": 2, "wait": 20},
    {"k": "Left", "hold": 2, "wait": 6},
    {"k": "Left", "hold": 2, "wait": 6},
    {"k": "Down", "hold": 2, "wait": 6},
    {"k": "A", "hold": 2, "wait": 60},
]
THROW_KEYS = os.environ.get("SLINK_GEN4_CATCH_KEYS")


def digest(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def need(path: Path, name: str) -> Path:
    if not path.is_file():
        pytest.skip(f"OPEN {name}: absent input {path}")
    return path


def check_synth_bag(save: Path) -> dict:
    need(save, "SYNTH bag save")
    side = need(save.with_name(save.name + ".synth.json"), "SYNTH bag sidecar")
    row = json.loads(side.read_text(encoding="utf-8"))
    assert row.get("schema") == "gen4-synth-v1" and row.get("kind") == "bag", (
        f"{side}: not a bag sidecar"
    )
    assert row.get("out_sha1") == g4.sha1_of(save), f"{side} does not describe {save}"
    assert row.get("after") == [4, 10] and row.get("count") == 10, "sidecar is not 10 Poke Balls"
    return {"sidecar": side.as_posix(), "sidecar_sha256": digest(side), "out_sha1": row["out_sha1"]}


def settled_state() -> Path:
    hits = sorted(
        LANE_ROOT.glob(f"{TITLES['tag']}_leg*_battle_settled.State"),
        key=lambda q: q.stat().st_mtime,
    )
    if not hits:
        pytest.skip(f"OPEN settled wild battle state: none in {LANE_ROOT}")
    return hits[-1]


def route_pack():
    from tools import gen4_routes as routes

    return routes.pack_legs(GAME, routes.SAVE_LEGS)


def launch(mode: str, keys: list, *, tag: str, extra: dict | None = None, timeout: int = 600):
    need(EMUHAWK, "EmuHawk")
    synth = check_synth_bag(BAG_SAVE)
    state = settled_state()
    if GAME in ("hge", "SS"):
        from tools import gen4_routes as routes

        rom_src = routes.HGE_ROM if GAME == "hge" else routes.SS_ROM
    else:
        rom_src = gen4_pins.default_locations().roms["heartgold"]
    profile = REPO / f"data/games/{TITLES['pack']}/profile.json"
    lane = LANE_ROOT / f"{tag}_{time.strftime('%H%M%S')}"
    assert not lane.exists()
    lane.mkdir(parents=True)
    rom = g4.stage_rom(rom_src, lane)
    rom_sha1 = g4.sha1_of(rom)
    assert rom_sha1 == gen4_pins.ROM_SPECS[TITLES["pin"]][0]
    battery = g4.stage_save(BAG_SAVE, lane, rom_sha1, rom_basename=rom.name)
    g4.write_nds_run_config(
        g4.BIZHAWK_CONFIG,
        lane / "bizhawk.ini",
        initial_time=INITIAL_TIME,
        lane_saveram_dir=lane / "SaveRAM",
    )
    shutil.copyfile(state, lane / "start.State")
    prof = json.loads(profile.read_text(encoding="utf-8"))["titles"][TITLES["title"]]["profile"]
    cfg = {
        "mode": mode,
        "keys": keys,
        "state_path": (lane / "start.State").as_posix(),
        "shot_dir": lane.as_posix(),
        "pack": {"save": prof["save"], "battle": prof["battle"], "system": prof["system"]},
        "requested_rate": 300,
        "run_id": f"{lane.parent.name}/{lane.name}",
        "title": TITLES["title"],
        "rom_sha1": rom_sha1,
        "setup": "SYNTH",
        "synth": synth,
        "script_sha256": digest(SCRIPT),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        **(extra or {}),
    }
    from tools import gen4_routes as routes
    cfg["evidence_binding"] = routes.receipt_binding(SCRIPT, kind="catch", title=TITLES["title"])
    (lane / "probe.json").write_text(json.dumps(cfg), encoding="utf-8")
    out = lane / "receipt.txt"
    env = dict(
        os.environ,
        SLINK_ROOT=REPO.as_posix(),
        SLINK_GEN4_CATCH_CONFIG=(lane / "probe.json").as_posix(),
        SLINK_GEN4_CATCH_OUT=out.as_posix(),
    )
    cmd = [
        str(EMUHAWK),
        f"--config={(lane / 'bizhawk.ini').as_posix()}",
        f"--lua={SCRIPT.as_posix()}",
        rom.as_posix(),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=lane,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if out.is_file() and "RESULT:" in out.read_text(encoding="utf-8"):
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        assert out.is_file(), f"no receipt in {lane}; exit={proc.poll()}"
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=20)  # client.exit flushes the battery
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        g4.kill_our_emuhawk(lane)  # this lane's own PIDs only
    line = out.read_text(encoding="utf-8").splitlines()[0]
    m = re.fullmatch(r"CATCH (PASS|FAIL|OPEN) (\{.*\})", line)
    assert m, f"malformed receipt: {line[:200]}"
    return m.group(1), json.loads(m.group(2)), lane, battery, cfg


def decode_battery(path: Path):
    from server.adapters import gen4_codec as c

    pack = json.loads(
        (REPO / f"data/games/{TITLES['pack']}/profile.json").read_text(encoding="utf-8")
    )
    return c.parse_save(path.read_bytes(), TITLES["codec"]), pack


def judge(obs: dict, battery_party: list[dict]) -> tuple[str, str]:
    """PASS needs ALL independent witnesses; anything missing is OPEN with the reason; contradictions FAIL."""
    if obs.get("fatal"):
        return "FAIL", f"fatal: {obs['fatal']}"
    foe = obs["foe"]
    if obs.get("outcome_value") not in (None, 4) and obs.get("outcome_value") != 0:
        return "OPEN", f"battle ended with result byte {obs['outcome_value']}, not 4 (caught)"
    if obs.get("outcome_value") != 4:
        return "OPEN", f"no caught result byte within {obs.get('throw_count')} throws"
    if obs.get("party_before") != 1 or obs.get("party_after") != 2:
        return (
            "FAIL",
            f"live party {obs.get('party_before')} -> {obs.get('party_after')}, expected 1 -> 2",
        )
    new = [p for p in obs["pids_after"] if p not in obs["pids_before"]]
    if new != [foe["pid"]]:
        return "FAIL", f"new live party PID {new} != foe PID {foe['pid']}"
    if not obs.get("save") or obs.get("save_failed"):
        return "OPEN", f"native SAVE legs not completed ({obs.get('save_failed') or 'not run'})"
    if len(battery_party) != 2:
        return (
            "FAIL",
            f"lane battery decodes {len(battery_party)} party mons after the native SAVE, expected 2",
        )
    mon = battery_party[1]
    if mon["pid"] != foe["pid"] or mon["species"] != foe["species"]:
        return (
            "FAIL",
            f"battery mon {mon['pid']:#x}/{mon['species']} != foe {foe['pid']:#x}/{foe['species']}",
        )
    return (
        "PASS",
        "caught (result byte 4); live party 1->2 with the foe's PID; lane battery decodes the new mon after native SAVE",
    )


# ---------------------------------------------------------------- offline
def test_judge_requires_every_independent_witness():
    foe = {"pid": 0xABCD, "species": 16}
    base = {
        "foe": foe,
        "outcome_value": 4,
        "party_before": 1,
        "party_after": 2,
        "pids_before": [1],
        "pids_after": [1, 0xABCD],
        "save": [{"leg": "x"}],
        "throw_count": 2,
    }
    mon = [{"pid": 1, "species": 155}, {"pid": 0xABCD, "species": 16}]
    assert judge(base, mon)[0] == "PASS"
    assert judge({**base, "outcome_value": None}, mon)[0] == "OPEN"
    assert judge({**base, "outcome_value": 1}, mon)[0] == "OPEN"
    assert judge({**base, "party_after": 1}, mon)[0] == "FAIL"
    assert judge({**base, "pids_after": [1, 7]}, mon)[0] == "FAIL"
    assert judge({**base, "save": None}, mon)[0] == "OPEN"
    assert judge(base, mon[:1])[0] == "FAIL"
    assert judge(base, [mon[0], {"pid": 9, "species": 16}])[0] == "FAIL"
    assert judge({**base, "fatal": "x"}, mon)[0] == "FAIL"


def _mutant_judge(needle: str):
    """judge() with the ONE top-level `if` whose test contains `needle` removed (an AST mutation)."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(judge)))
    fn = tree.body[0]
    keep = [n for n in fn.body if not (isinstance(n, ast.If) and needle in ast.unparse(n.test))]
    assert len(keep) == len(fn.body) - 1, f"clause {needle!r} not found exactly once"
    fn.body = keep
    ns: dict = {}
    exec(compile(tree, "<mutant judge>", "exec"), ns)  # noqa: S102 - test-only mutation
    return ns["judge"]


_FOE = {"pid": 0xABCD, "species": 16}
_GOOD_OBS = {
    "foe": _FOE,
    "outcome_value": 4,
    "party_before": 1,
    "party_after": 2,
    "pids_before": [1],
    "pids_after": [1, 0xABCD],
    "save": [{"leg": "x"}],
    "throw_count": 2,
}
_GOOD_MON = [{"pid": 1, "species": 155}, {"pid": 0xABCD, "species": 16}]


@pytest.mark.parametrize(
    ("clause", "needle", "obs", "mons", "verdict"),
    [
        ("party 1->2", "party_before", {"party_after": 1}, _GOOD_MON, "FAIL"),
        ("PID delta", "new !=", {"pids_after": [1, 7]}, _GOOD_MON, "FAIL"),
        ("save legs", "obs.get('save')", {"save": None}, _GOOD_MON, "OPEN"),
        (
            "battery party size",
            "len(battery_party)",
            {},
            [*_GOOD_MON, {"pid": 5, "species": 1}],
            "FAIL",
        ),
        ("battery party size (one mon)", "len(battery_party)", {}, _GOOD_MON[:1], "FAIL"),
        (
            "battery pid/species",
            "mon['pid']",
            {},
            [_GOOD_MON[0], {"pid": 9, "species": 16}],
            "FAIL",
        ),
        (
            "battery species only",
            "mon['pid']",
            {},
            [_GOOD_MON[0], {"pid": 0xABCD, "species": 17}],
            "FAIL",
        ),
    ],
)
def test_judge_wrong_capture_branch_is_load_bearing(clause, needle, obs, mons, verdict):
    """Each wrong-capture clause refuses its case, and the judge WITHOUT that clause lets the same wrong
    capture through as PASS: the test goes red when the clause is removed."""
    wrong = {**_GOOD_OBS, **obs}
    assert judge(_GOOD_OBS, _GOOD_MON)[0] == "PASS"
    assert judge(wrong, mons)[0] == verdict, clause
    try:
        slipped = _mutant_judge(needle)(wrong, mons)[0] == "PASS"
    except (
        IndexError
    ):  # the clause also guards the slot-1 read: without it the judge crashes, not passes
        slipped = clause.endswith("(one mon)")
    assert slipped, f"{clause}: removing the clause no longer matters"


def _verdict_doc(**over):
    from tools import gen4_routes as routes

    doc = {
        **routes.receipt_binding(SCRIPT, kind="catch", title="heartgold"),
        "title": "heartgold",
        "rom_sha1": gen4_pins.ROM_SPECS["heartgold"][0],
        "verdict": "PASS",
        "battery_mon": {"key": "K", "pid": 1, "species": 16},
    }
    return {**doc, **over}


def test_verdict_receipt_is_bound_at_consumption(tmp_path):
    """verdict.json carries HEAD, the probe script + hash, every required module hash and the pinned ROM."""
    from tools import gen4_routes as routes

    doc = _verdict_doc()
    assert doc["script"] == "lua/tests/probe_gen4_catch.lua" and doc["script_sha256"] == digest(
        SCRIPT
    )
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert routes.verify_receipt(path, "catch", head=doc["source_head"])[0] == "PASS"
    assert routes.verify_receipt(path, "catch", head="0" * 40)[0] == "PASS"  # Docs-only HEAD movement.
    path.write_text(json.dumps(_verdict_doc(script_sha256="0" * 64)), encoding="utf-8")
    assert routes.verify_receipt(path, "catch", head=doc["source_head"])[0] == "STALE"


def test_a_route_receipt_does_not_pass_as_a_catch_verdict(tmp_path):
    from tools import gen4_routes as routes

    route_doc = {
        **routes.receipt_binding(),
        "title": "heartgold",
        "rom_sha1": gen4_pins.ROM_SPECS["heartgold"][0],
        "final_status": "PC_DEPOSIT",
        "before_save": {"bank": 0, "counter": 1, "keys": ["K"]},
        "battery": {"bank": 1, "counter": 2, "keys": ["K"]},
        "reload": {"witness": {"bank": 1, "counter": 2, "keys": ["K"]}},
    }
    path = tmp_path / "r.json"
    path.write_text(json.dumps(route_doc), encoding="utf-8")
    assert routes.verify_receipt(path, "route", head=route_doc["source_head"], want="PC_DEPOSIT")[0] == "PASS"
    assert (
        routes.verify_receipt(path, "catch", head=route_doc["source_head"])[0] == "STALE"
    )  # wrong script/kind


def test_synth_bag_sidecar_checked(tmp_path):
    with pytest.raises(pytest.skip.Exception):
        check_synth_bag(tmp_path / "x.SaveRAM")
    save = tmp_path / "x.SaveRAM"
    save.write_bytes(b"\1" * 8)
    side = save.with_name(save.name + ".synth.json")
    row = {
        "schema": "gen4-synth-v1",
        "kind": "bag",
        "out_sha1": g4.sha1_of(save),
        "after": [4, 10],
        "count": 10,
    }
    side.write_text(json.dumps(row), encoding="utf-8")
    assert check_synth_bag(save)["sidecar_sha256"] == digest(side)
    side.write_text(json.dumps({**row, "kind": "party2"}), encoding="utf-8")
    with pytest.raises(AssertionError):
        check_synth_bag(save)


def test_real_bag_save_if_present():
    if not BAG_SAVE.is_file():
        pytest.skip(f"OPEN bag save absent: {BAG_SAVE}")
    assert check_synth_bag(BAG_SAVE)["out_sha1"] == g4.sha1_of(BAG_SAVE)


def test_catch_lua_loads():
    lupa = pytest.importorskip("lupa")
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.globals().SLINK_GEN4_CATCH_TEST = True
    assert rt.execute(SCRIPT.read_text(encoding="utf-8")) is not None


live = pytest.mark.skipif(
    os.environ.get("SLINK_LIVE") != "1", reason="OPEN physical probe: SLINK_LIVE=1"
)


@pytest.mark.live
@live
def test_live_wild_capture():
    keys = json.loads(THROW_KEYS) if THROW_KEYS else None
    if not keys:
        pytest.skip("OPEN: bag navigation keys not derived yet (SLINK_GEN4_CATCH_KEYS)")
    save_legs = route_pack()
    status, payload, lane, battery, cfg = launch(
        "catch", keys, tag="catch", extra={"save_legs": save_legs, "wake_keys": WAKE_TO_BAG[:1]}
    )
    obs = payload["observation"]
    parsed, _ = decode_battery(battery)
    party = parsed.party()
    verdict, why = judge(obs, party)
    mon = party[1] if len(party) > 1 else {}
    summary = {
        k: mon.get(k)
        for k in (
            "key",
            "pid",
            "species",
            "level",
            "ability",
            "hidden_ability",
            "met_level",
            "met_location",
            "ball",
            "is_egg",
        )
    }
    modified = parsed.pc_meta().get("modified")
    if (
        GAME == "hge" and len(party) > 1
    ):  # the codec leaves hg-engine's hidden-ability bit (block B +0x19 bit 6) undecoded
        from server.adapters import gen4_codec as c

        off = parsed.profile.party_off + 8 + 1 * c.PARTY_MON_SIZE
        plain = c.decrypt_party(parsed.general[off : off + c.PARTY_MON_SIZE])
        summary["hidden_ability"] = (plain[c.HEADER_SIZE + c.BLOCK_SIZE + 0x19] >> 6) & 1
    from tools import gen4_routes as routes

    # bound at consumption: HEAD + the probe script + every module the verdict depended on
    binding = cfg["evidence_binding"]
    gen4_evidence.bind({**binding, "rom_sha1": payload["rom_sha1"]},
                       routes.receipt_binding(SCRIPT, kind="catch", title=TITLES["title"]),
                       title=TITLES["title"], rom_sha1=payload["rom_sha1"])
    (lane / "verdict.json").write_text(
        json.dumps(
            {
                **binding,
                "title": TITLES["title"],
                "rom_sha1": payload.get("rom_sha1"),
                "verdict": verdict,
                "reason": why,
                "game": GAME,
                "setup": "SYNTH",
                "synth": payload.get("synth"),
                "battery_sha1": g4.sha1_of(battery),
                "battery_party": len(party),
                "battery_mon": summary,
                "battery_modified": modified,
            },
            default=str,
        ),
        encoding="utf-8",
    )
    assert verdict != "FAIL", why
    if verdict == "OPEN":
        pytest.skip(f"OPEN {why} ({lane})")
