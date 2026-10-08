"""MODEL oracle controls; no emulator. Forged traces must never become live evidence."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from tools.polished_live import explode_live as live
from tools.polished_live.faint_probe import read_symbols

ROOT = Path(__file__).resolve().parents[2]


def model(case):
    symbols = read_symbols(ROOT / "data/polished/polished_slink.sym")
    sites = {
        k: {"bank": 15, "addr": a, "bytes": "cd0000"}
        for k, a in [
            ("hold", 0x416A),
            ("faint", 0x44A0),
            ("copy_return", 0x44CD),
            ("selfdestruct", 0x5000),
        ]
    }
    return {
        "case": case,
        "target": {"key": "EFFFFF:D1C2:0A9:00", "slot": 2 if case == "bench-faint" else 0},
        "steps": [{"frames": 2, "buttons": ["A"]}, {"frames": 3, "buttons": []}],
        "provenance": {"MODEL": "not a live receipt"},
        "contract": {
            "symbols": symbols,
            "sites": sites,
            "geometry": {"moves": 2, "pp": 22, "status": 32, "hp": 34},
            "explosion": 153,
            "snapshot_sizes": {
                "WRAM": 32768,
                "CartRAM": 32768,
                "VRAM": 16384,
                "OAM": 160,
                "HRAM": 127,
            },
        },
    }


def image(config):
    out = {d: bytearray(n) for d, n in config["contract"]["snapshot_sizes"].items()}
    s = config["contract"]["symbols"]
    slot = config["target"]["slot"]

    def put(label, v, delta=0):
        row = s[label]
        domain = "HRAM" if row[1] >= 0xFF80 else "WRAM"
        at = row[1] - 0xFF80 + delta if domain == "HRAM" else live.flat(row, delta)
        out[domain][at] = v

    for name, v in [
        ("wBattleMode", 0 if config["case"] == "bench-faint" else 1),
        ("wCurBattleMon", 0),
        ("wBattlePlayerAction", 0),
        ("wMapStatus", 2),
        ("wScriptRunning", 0),
        ("wLinkMode", 0),
        ("hROMBank", 15),
        ("hBattleTurn", 0),
        ("wCurMoveNum", 1),
        ("wBattleMonStatus", 3),
        ("wBattleMonHP", 1),
        ("wWhichMonFaintedFirst", 0),
    ]:
        put(name, v)
    put("wPartyMons", 1, slot * 48 + 34)
    put("wPartyMons", 3, slot * 48 + 32)
    put("wBattleMonPP", 0xC3, 1)
    put("wPartyMons", 0x83, slot * 48 + 23)
    return out


def trace_for(case):
    c = model(case)
    s = c["contract"]["symbols"]
    slot = c["target"]["slot"]
    im = image(c)
    before = {d: b.hex() for d, b in im.items()}
    after = copy.deepcopy(im)

    def addr(label, d=0):
        return s[label][1] + d

    if case == "explode":
        plan = [
            (addr("wBattleMonMoves", 1), 153),
            (addr("wBattleMonPP", 1), 0xC1),
            (addr("wPartyMons", slot * 48 + 3), 153),
            (addr("wPartyMons", slot * 48 + 23), 0x81),
            (addr("wCurPlayerMove"), 153),
        ]
    else:
        party = [(addr("wPartyMons", slot * 48 + i), 0) for i in (32, 34, 35)]
        plan = (
            party
            if case == "bench-faint"
            else [
                (addr("wBattleMonStatus"), 0),
                *party,
                (addr("wBattleMonHP"), 0),
                (addr("wBattleMonHP", 1), 0),
                (addr("wWhichMonFaintedFirst"), 1),
            ]
        )
    for a, v in plan:
        after["WRAM"][live.flat((0 if a < 0xD000 else 1, a))] = v
    out = []

    def add(kind, **kw):
        e = {"ord": len(out) + 1, "frame": kw.pop("frame", 10), "kind": kind, **kw}
        out.append(e)
        return e

    add("begin", frame=0, provenance=c["provenance"], disclosure=live.DISCLOSURE)
    add("route", frame=0, step=1, frames=2, buttons=["A"])
    add("route", frame=2, step=2, frames=3, buttons=[])
    add(
        "command",
        cmd="force_explode" if case == "explode" else "force_faint",
        key=c["target"]["key"],
        slot=slot,
        mode=1,
    )
    if case == "bench-faint":
        hold_image = copy.deepcopy(im)
        hold_image["WRAM"][live.flat(s["wBattleMode"])] = 1
        hold_image = {d: b.hex() for d, b in hold_image.items()}
        add(
            "bench_hold",
            mode=1,
            active=0,
            pc=0x416A,
            bank=15,
            party_hp=256,
            writes=[],
            changed=False,
            before=hold_image,
            after=hold_image,
        )
    scope = add(
        "scope_begin",
        context="overworld" if case == "bench-faint" else "battle",
        key=c["target"]["key"],
    )
    if case == "bench-faint":
        add("hud", text="QUAL_TARGET KO'd", dead=True, fs_seq=20)
    op = add(
        "operation",
        scope_ord=scope["ord"],
        context=scope["context"],
        key=c["target"]["key"],
        before=before,
        after={d: b.hex() for d, b in after.items()},
        writes=[{"addr": a, "value": v, "domain": "System Bus"} for a, v in plan],
        mode=0 if case == "bench-faint" else 1,
        map_status=2,
        script=0,
        link=0,
        bank=15,
        turn=0,
        pc=0x416A,
        action=0,
        active=0,
        party_hp=256,
        attempt={"identity": "1:2", "epoch": 0, "visit": 1, "seq": 10, "generation": 1},
    )
    if case != "bench-faint":
        for name in (["selfdestruct"] if case == "explode" else []) + ["faint", "copy_return"]:
            site = c["contract"]["sites"][name]
            add(
                "native",
                site=name,
                bank=site["bank"],
                pc=site["addr"],
                bytes=site["bytes"],
                turn=0,
                slot=slot,
                key=c["target"]["key"],
                battle_hp=0,
                party_hp=0,
                fainted=True,
                move=153,
            )
        if case == "active-faint":
            add(
                "consumer",
                phase="after_party_copyback",
                battle={
                    "slot": slot,
                    "mode": 1,
                    "link_mode": 0,
                    "hp": 0,
                    "status": 0,
                    "fainted": True,
                },
                batch_generation=0,
                capture={**op["attempt"], "key": c["target"]["key"], "attempt_seq": 10, "seq": 11},
            )
    add(
        "wire",
        sent=True,
        message={"event": "tick", "party": [{"key": c["target"]["key"], "hp": 0}]},
    )
    if case != "bench-faint":
        add("hud", text="QUAL_TARGET KO'd", dead=True, fs_seq=20)
    add("final", completed=True, driver_errors=0, post_operation_writes=0)
    return c, out


def row(trace, kind):
    return next(e for e in trace if e["kind"] == kind)


@pytest.mark.parametrize("case", live.CASES, ids=live.CASES)
def test_three_model_scenarios(case):
    config, trace = trace_for(case)
    assert live.evaluate(trace, config) == (True, [])


@pytest.mark.parametrize(
    "bad",
    [
        "wrong_key",
        "wrong_command",
        "wrong_bank",
        "wrong_action",
        "wrong_active",
        "plan_order",
        "wrong_pp",
        "outside_cart",
        "outside_vram",
        "outside_oam",
        "empty_diff",
        "no_native",
        "wrong_native_key",
        "no_copy_hp",
        "no_native_fainted",
        "second_ko",
        "no_tick",
        "faint_echo",
        "route_time",
        "preimage_guard",
        "early_ko",
    ],
    ids=lambda x: x,
)
def test_explosion_false_pass_controls(bad):
    c, t = trace_for("explode")
    op = row(t, "operation")
    if bad == "wrong_key":
        op["key"] = "wrong"
    elif bad == "wrong_command":
        row(t, "command")["cmd"] = "force_faint"
    elif bad == "wrong_bank":
        op["bank"] = 14
    elif bad == "wrong_action":
        op["action"] = 1
    elif bad == "wrong_active":
        op["active"] = 2
    elif bad == "plan_order":
        op["writes"].reverse()
    elif bad == "wrong_pp":
        op["writes"][1]["value"] = 1
    elif bad.startswith("outside_"):
        domain = {"outside_cart": "CartRAM", "outside_vram": "VRAM", "outside_oam": "OAM"}[bad]
        im = bytearray.fromhex(op["after"][domain])
        im[0] = 1
        op["after"][domain] = im.hex()
    elif bad == "empty_diff":
        op["after"] = op["before"]
    elif bad == "no_native":
        row(t, "native")["site"] = "other"
    elif bad == "wrong_native_key":
        row(t, "native")["key"] = "wrong"
    elif bad == "no_copy_hp":
        next(e for e in t if e.get("site") == "copy_return")["party_hp"] = 1
    elif bad == "no_native_fainted":
        next(e for e in t if e.get("site") == "copy_return")["fainted"] = False
    elif bad == "second_ko":
        t.insert(-1, copy.deepcopy(row(t, "hud")))
    elif bad == "no_tick":
        row(t, "wire")["sent"] = False
    elif bad == "faint_echo":
        row(t, "wire")["message"]["event"] = "faint"
    elif bad == "route_time":
        next(e for e in t if e.get("step") == 2)["frame"] = 0
    elif bad == "preimage_guard":
        im = bytearray.fromhex(op["before"]["WRAM"])
        im[live.flat(c["contract"]["symbols"]["wBattleMode"])] = 0
        op["before"]["WRAM"] = im.hex()
    elif bad == "early_ko":
        t.insert(5, t.pop(-2))
    for i, e in enumerate(t):
        e["ord"] = i + 1
    assert live.evaluate(t, c)[0] is False, bad


@pytest.mark.parametrize(
    "bad",
    [
        "phase",
        "key",
        "epoch",
        "generation",
        "attempt_seq",
        "seq",
        "batch",
        "no_consumer",
        "native_fainted",
    ],
    ids=lambda x: x,
)
def test_plain_capture_controls(bad):
    c, t = trace_for("active-faint")
    e = row(t, "consumer")
    if bad == "phase":
        e["phase"] = "before_party_copyback"
    elif bad == "batch":
        e["batch_generation"] = 999
    elif bad == "native_fainted":
        e["battle"]["fainted"] = False
    elif bad == "no_consumer":
        e["kind"] = "wrong_bank"
    else:
        e["capture"][bad] = "bad"
    assert live.evaluate(t, c)[0] is False


@pytest.mark.parametrize(
    "bad",
    ["battle_write", "hidden_change", "active", "mode", "pc", "checkpoint", "no_hold", "late_hud"],
    ids=lambda x: x,
)
def test_bench_controls(bad):
    c, t = trace_for("bench-faint")
    h = row(t, "bench_hold")
    op = row(t, "operation")
    if bad == "battle_write":
        h["writes"] = [1]
    elif bad == "hidden_change":
        h["after"] = {**h["after"], "OAM": "ff" * 160}
    elif bad == "active":
        h["active"] = 2
    elif bad == "mode":
        h["mode"] = 0
    elif bad == "pc":
        h["pc"] = 0
    elif bad == "checkpoint":
        op["map_status"] = 0
    elif bad == "no_hold":
        h["kind"] = "wrong_bank"
    elif bad == "late_hud":
        t.insert(-1, t.pop(next(i for i, e in enumerate(t) if e["kind"] == "hud")))
    for i, e in enumerate(t):
        e["ord"] = i + 1
    assert live.evaluate(t, c)[0] is False


def test_dry_run_never_launches_or_creates_lane(monkeypatch, tmp_path, capsys):
    c, _ = trace_for("explode")
    monkeypatch.setattr(live, "prepare", lambda *a: (b"rom", b"save", c))
    monkeypatch.setattr(live.subprocess, "Popen", lambda *a, **k: pytest.fail("process launch"))
    lane = tmp_path / "never"
    assert live.main(["--case", "explode", "--dry-run", "--lane", str(lane)]) == 0
    assert not lane.exists() and json.loads(capsys.readouterr().out)["case"] == "explode"


def test_real_input_admission_and_pins():
    if not live.FIXTURE.exists():
        pytest.skip("absent input: " + str(live.FIXTURE))
    _, _, c = live.prepare("explode")
    assert c["contract"]["geometry"] == {"moves": 2, "pp": 22, "status": 32, "hp": 34}
    assert c["target"]["key"] == "EFFFFF:D1C2:0A9:00"
    assert c["provenance"]["rom_sha1"] == live.OVERLAY
    assert c["provenance"]["source_inputs"]["lua/gen2/client.lua"] == live.sha(
        (ROOT / "lua/gen2/client.lua").read_bytes()
    )


def test_lua_loads_and_mapping_guard_mutant_is_red():
    source = (ROOT / "tools/polished_live/explode_live.lua").read_text()

    def check(text):
        lua = LuaRuntime()
        lua.globals().POL_EXPLODE_UNIT_TEST = True
        m = lua.execute(text)
        read = lua.eval("function(a,d) if a==0xff70 then return 5 else return 15 end end")
        assert m.bank_valid(1, 0xD000, 1, read, 0xFF9F) is False
        assert m.bank_valid(5, 0xD000, 1, read, 0xFF9F) is True
        assert m.bank_valid(15, 0x416A, 3, read, 0xFF9F) is True
        assert m.bank_valid(14, 0x416A, 3, read, 0xFF9F) is False

    check(source)
    with pytest.raises(AssertionError):
        check(source.replace("return bank==(mapped==0 and 1 or mapped)", "return true"))


@pytest.mark.parametrize("case", live.CASES, ids=live.CASES)
def test_real_composed_client_write_log_agrees_with_independent_plan(case):
    from tests.unit import test_polished_explode_path as br, test_polished_faint_observer as obs
    from tests.unit.test_polished_write_path import key_of

    rig, mons = obs.build()
    config = model(case)
    config["target"] = {
        "slot": 1 if case == "bench-faint" else 0,
        "key": key_of(mons[1 if case == "bench-faint" else 0]),
    }

    def snap():
        out = {d: bytearray(n) for d, n in config["contract"]["snapshot_sizes"].items()}
        for a, v in rig.mem.items():
            if 0xC000 <= a < 0xE000:
                out["WRAM"][live.flat((0 if a < 0xD000 else 1, a))] = v
            elif 0xFF80 <= a < 0xFFFF:
                out["HRAM"][a - 0xFF80] = v
        return {d: b.hex() for d, b in out.items()}

    br.order(
        rig,
        "force_explode" if case == "explode" else "force_faint",
        mons,
        slot=config["target"]["slot"],
    )
    before = snap()
    br.at_hold(rig)
    if case == "bench-faint":
        assert not rig.writes() and rig.hp(1) > 0
        rig.put("wBattleMode", 0)
        rig.put("wMapStatus", 2)
        rig.put("wScriptRunning", 0)
        rig.put("hROMBank", 0x25)
        before = snap()
        rig.frame(3)
    writes = rig.writes()
    assert [(w["addr"], rig.mem[w["addr"]]) for w in writes] == live.expected_writes(config, before)
    after = snap()
    changed = {
        (d, i)
        for d in before
        for i, (a, b) in enumerate(
            zip(bytes.fromhex(before[d]), bytes.fromhex(after[d]), strict=True)
        )
        if a != b
    }
    allowed = {("WRAM", live.flat((0 if w["addr"] < 0xD000 else 1, w["addr"]))) for w in writes}
    assert changed and changed <= allowed


@pytest.mark.parametrize(
    "guard,case",
    [
        ("native", "explode"),
        ("scope", "explode"),
        ("clock", "active-faint"),
        ("duplicate", "explode"),
    ],
    ids=["native-site", "diff-scope", "capture-clock", "once-only"],
)
def test_oracle_source_copy_mutants_turn_the_same_false_pass_control_red(guard, case):
    source = (ROOT / "tools/polished_live/explode_live.py").read_text()
    config, trace = trace_for(case)
    if guard == "native":
        next(e for e in trace if e.get("site") == "copy_return")["fainted"] = False
        old = '(e["party_hp"] != 0 or not e["fainted"])'
        new = "False"
    elif guard == "scope":
        op = row(trace, "operation")
        im = bytearray.fromhex(op["after"]["OAM"])
        im[0] = 1
        op["after"]["OAM"] = im.hex()
        old = "any(x not in permitted for x in changed)"
        new = "False"
    elif guard == "clock":
        row(trace, "consumer")["batch_generation"] = 999
        old = 'consumer["batch_generation"] != attempt["epoch"]'
        new = "False"
    else:
        trace.insert(-1, copy.deepcopy(row(trace, "hud")))
        for i, e in enumerate(trace):
            e["ord"] = i + 1
        old = "len(hud) != 1"
        new = "len(hud) < 1"
    assert source.count(old) == 1 and live.evaluate(trace, config)[0] is False
    namespace = {
        "__file__": str(ROOT / "tools/polished_live/explode_live.py"),
        "__name__": "mutant",
    }
    exec(compile(source.replace(old, new), "<source-copy-mutant>", "exec"), namespace)
    assert namespace["evaluate"](trace, config)[0] is True, "mutant must disable the tested guard"


def test_source_pin_mismatch_refuses(tmp_path, monkeypatch):
    (tmp_path / "client.lua").write_text("wrong")
    monkeypatch.setattr(live, "REPO", tmp_path)
    with pytest.raises(ValueError, match="source changed: client.lua"):
        live.verify_sources({"provenance": {"source_inputs": {"client.lua": live.sha(b"right")}}})


@pytest.mark.parametrize(
    "bad",
    ["image", "order", "late_write", "consumer_fainted"],
    ids=["bench-image", "bench-before-command", "late-host-write", "plain-native-flag"],
)
def test_review_counterexamples_fail_closed(bad):
    c, t = trace_for("active-faint" if bad == "consumer_fainted" else "bench-faint")
    if bad == "image":
        e = row(t, "bench_hold")
        im = bytearray.fromhex(e["before"]["WRAM"])
        im[live.flat(c["contract"]["symbols"]["wBattleMode"])] = 0
        e["before"] = {**e["before"], "WRAM": im.hex()}
        e["after"] = e["before"]
    elif bad == "order":
        i = next(i for i, e in enumerate(t) if e["kind"] == "bench_hold")
        t.insert(3, t.pop(i))
        for i, e in enumerate(t):
            e["ord"] = i + 1
    elif bad == "late_write":
        row(t, "final")["post_operation_writes"] = 1
    else:
        row(t, "consumer")["battle"]["fainted"] = False
    assert live.evaluate(t, c)[0] is False


def test_real_native_faint_stack_runs_post_copy_observer_and_settles_once():
    from tests.unit import test_polished_faint_client as fc, test_polished_faint_e2e as e2e

    rig, _, ob = e2e.staged()
    e2e.native_resolve(rig)
    rig.frame(1)
    fc.tick(rig)
    assert ob.state == "done" and len(fc.ko(rig)) == 1
    assert rig.sent("faint") == []
    fc.tick(rig)
    assert len(fc.ko(rig)) == 1
