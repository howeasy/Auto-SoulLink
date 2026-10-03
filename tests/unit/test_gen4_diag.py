"""MODEL replays for the non-qualifying Gen 4 diagnostic driver; never an emulator."""

from pathlib import Path

import lupa
import pytest

from tools import gen4_diag as d


def publish_runtime_to_host(lane, monkeypatch, title, command):
    """Generated Lua output -> real collect() -> diagnostic.json; no emulator."""
    import json

    class Exited:
        pid = 991

        def poll(self):
            return 0

        def wait(self, timeout):
            return 0

    cfg = {
        "schema": "gen4-diagnostic-v1",
        "source_head": "MODEL",
        "qualified": False,
        "title": title,
        "command": command,
        "requested_rate": 300,
    }
    with monkeypatch.context() as patch:
        patch.setattr(d.subprocess, "Popen", lambda *a, **k: Exited())
        patch.setattr(d.g4, "kill_our_emuhawk", lambda lane: None)
        patch.setattr(d, "verify_after", lambda c: None)
        patch.setattr(d, "service_bridge", lambda *a: None)
        code = d.collect(cfg, lane, ["MODEL-owned"], planner=None, timeout=600)
    return code, json.loads((lane / "diagnostic.json").read_text())


def test_generated_fight_actual_pack_leg_publishes_identity_pp_and_hp(tmp_path, monkeypatch):
    import json
    import struct

    from tests.unit.test_gen4_battle_faint_model import BASE, CTX, World

    (tmp_path / "observation.json").unlink(missing_ok=True)
    title = json.loads((d.REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"][
        "heartgold"
    ]
    recipe = d.fight_recipe(title, "fight_until_enemy_faints")
    assert {k: v for k, v in recipe.items() if k != "name"} == title["route_legs"][
        "fight_until_enemy_faints"
    ]
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "artifact": title,
                "lane": str(tmp_path),
                "command": "fight",
                "recipe": recipe,
                "state_path": "MODEL",
                "requested_rate": 300,
            }
        )
    )
    w = World(ehp=17)
    b = title["profile"]["battle"]
    for side, sp, level in [(0, 155, 5), (1, 19, 4)]:
        mon = CTX + b["mons_off"] + side * b["mon_size"]
        w.w16(mon + b["species_off"], sp)
        w.m[mon + b["level_off"] - BASE] = level
        w.w32(mon + b["moves_off"], 33 | (45 << 16))
        w.w32(mon + b["moves_off"] + 4, 0)
        w.w32(mon + b["pp_off"], 35 | (40 << 8))
    r = lupa.LuaRuntime(unpack_returned_tuples=True)

    def advance():
        r.globals().frame += 1
        elapsed = r.globals().frame - 7616
        if elapsed in (780, 1560, 2340, 3120):
            w.m[CTX + b["mons_off"] + b["pp_off"] - BASE] -= 1
        if elapsed == 3280:
            w.w32(CTX + b["mons_off"] + b["mon_size"] + b["hp_off"], 0)

    r.globals().ROOT = d.REPO.as_posix()
    r.globals().CONFIG = cfg.as_posix()
    r.globals().READ = lambda a, bus: struct.unpack_from("<I", w.m, a - BASE)[0]
    r.globals().ADVANCE = advance
    r.execute("""
      frame=7616
      local old=os.getenv
      os.getenv=function(k) if k=="SLINK_ROOT" then return ROOT elseif k=="G4_DIAG_CONFIG" then return CONFIG end; return old(k) end
      memory={read_u32_le=READ}; emu={framecount=function() return frame end,frameadvance=ADVANCE,limitframerate=function() end}
      joypad={set=function() end}; savestate={load=function() end}; client={speedmode=function() end,exit=function() end}
    """)
    r.execute(d.LUA)
    code, doc = publish_runtime_to_host(tmp_path, monkeypatch, "heartgold", "fight")
    assert code == 0, doc
    o = doc["observation"]
    assert o["initial"]["our_hp"] == 20 and o["initial"]["enemy_hp"] == 17
    assert o["ready_sample"]["our_species"] == 155 and o["ready_sample"]["enemy_species"] == 19
    assert o["ready_sample"]["our_level"] == 5 and o["ready_sample"]["enemy_level"] == 4
    assert o["ready_sample"]["our_moves"] == [33, 45, 0, 0] and o["ready_sample"]["our_pp"] == [
        35,
        40,
        0,
        0,
    ]
    assert [x["ordinal"] for x in o["pp_deltas"]] == [1, 2, 3, 4]
    assert all(x["slot"] == 1 and x["move_id"] == 33 for x in o["pp_deltas"])
    assert o["recipes"][0]["frames_used"] == 3280


@pytest.mark.parametrize("content", ["", "{broken"])
def test_dead_process_invalid_result_fails_immediately(tmp_path, monkeypatch, content):
    import json

    (tmp_path / "observation.json").write_text(content)

    class Exited:
        pid = 991

        def poll(self):
            return 1

        def wait(self, timeout):
            return 1

    calls = [0]
    sleeps = []

    def now():
        calls[0] += 1
        return calls[0] / 10

    monkeypatch.setattr(d.time, "monotonic", now)
    monkeypatch.setattr(d.time, "sleep", lambda n: sleeps.append(n))
    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: Exited())
    monkeypatch.setattr(d.g4, "kill_our_emuhawk", lambda lane: None)
    monkeypatch.setattr(d, "service_bridge", lambda *a: None)
    monkeypatch.setattr(d, "verify_after", lambda c: None)
    assert (
        d.collect(
            {"qualified": False, "source_head": "MODEL", "requested_rate": 300},
            tmp_path,
            ["MODEL"],
            planner=None,
            timeout=600,
        )
        == 1
    )
    doc = json.loads((tmp_path / "diagnostic.json").read_text())
    assert "invalid diagnostic result after emulator exit" in doc["reason"] and calls[0] < 10
    assert not sleeps and doc["ownership"]["exited"]


def test_killed_emulator_unflushed_rate_uses_lua_witness(tmp_path):
    import json

    before = json.loads(
        (d.REPO / "tests/fixtures/gen4/diag_config_autosave_before.json").read_text()
    )
    path = tmp_path / "bizhawk.ini"
    path.write_text(json.dumps(before))
    cfg = {
        "requested_rate": 300,
        "emulator_config": {
            "path": str(path),
            "before_sha256": d.sha256(path),
            "expected_settings": d.emulator_settings(before, 300),
        },
        "observed_applied_rate": 300,
    }
    audit = d.emulator_config_audit(cfg)
    assert (
        audit["flush_status"] == "UNFLUSHED"
        and audit["settings_valid"]
        and audit["rate_source"] == "Lua applied_rate"
    )
    cfg["observed_applied_rate"] = 100
    assert not d.emulator_config_audit(cfg)["settings_valid"]
    cfg["observed_applied_rate"] = 300
    assert d.emulator_config_audit(cfg)["settings_valid"]
    path.write_text(json.dumps({**before, "Unthrottled": not before["Unthrottled"]}))
    assert not d.emulator_config_audit(cfg)["settings_valid"]
    path.write_text(json.dumps(before))
    assert d.emulator_config_audit(cfg)["settings_valid"]


def test_collect_audits_unflushed_settings_with_terminal_lua_rate(tmp_path, monkeypatch):
    import json

    before = json.loads(
        (d.REPO / "tests/fixtures/gen4/diag_config_autosave_before.json").read_text()
    )
    path = tmp_path / "bizhawk.ini"
    path.write_text(json.dumps(before))
    (tmp_path / "observation.json").write_text(
        json.dumps(
            {
                "terminal": True,
                "qualified": False,
                "status": "OBSERVED",
                "applied_rate": 300,
            }
        )
    )
    cfg = {
        "qualified": False,
        "source_head": "MODEL",
        "requested_rate": 300,
        "title": "heartgold",
        "originals": {},
        "generated_paths": {},
        "hashes": {"driver": d.sha256(d.__file__)},
        "frozen_surface": {},
        "rom_sha1": "MODEL",
        "emulator_config": {
            "path": str(path),
            "before_sha256": d.sha256(path),
            "expected_settings": d.emulator_settings(before, 300),
        },
    }

    class Exited:
        pid = 991

        def poll(self):
            return 1  # ended abnormally after terminal publication

        def wait(self, timeout):
            return 1

    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: Exited())
    monkeypatch.setattr(
        d.subprocess, "check_output", lambda cmd, **kw: "MODEL" if "rev-parse" in cmd else ""
    )
    monkeypatch.setattr(d.evidence, "snapshot", lambda *a, **kw: {})
    monkeypatch.setattr(d.evidence, "bind", lambda *a, **kw: None)
    monkeypatch.setattr(d.g4, "kill_our_emuhawk", lambda lane: None)
    monkeypatch.setattr(d, "service_bridge", lambda *a: None)
    assert d.collect(cfg, tmp_path, ["MODEL-owned"], planner=None, timeout=600) == 0
    doc = json.loads((tmp_path / "diagnostic.json").read_text())
    assert doc["inputs_unchanged"] and doc["emulator_config_audit"]["settings_valid"]
    assert doc["emulator_config_audit"]["flush_status"] == "UNFLUSHED"
    assert doc["emulator_config_audit"]["applied_rate"] == 300
    path.write_text(json.dumps({**before, "Unthrottled": not before["Unthrottled"]}))
    assert not d.emulator_config_audit(cfg)["settings_valid"]
    assert d.collect(cfg, tmp_path, ["MODEL-owned"], planner=None, timeout=600) == 1
    path.write_text(json.dumps(before))
    assert d.emulator_config_audit(cfg)["settings_valid"]
    assert d.collect(cfg, tmp_path, ["MODEL-owned"], planner=None, timeout=600) == 0


@pytest.mark.parametrize("title_name", ["heartgold_hge", "soulsilver"])
def test_generated_settle_physical_scale_uses_native_executor_and_publishes(
    tmp_path, monkeypatch, title_name
):
    """Actual pack + captured route -> native executor -> real codec -> collect().

    Frame totals/route are PHYSICAL replay inputs. RAM, movement timing and pin
    delays are MODEL choices, not settlement measurements or qualification.
    """
    import json
    import struct

    (tmp_path / "observation.json").unlink(missing_ok=True)
    fixture = json.loads((d.REPO / "tests/fixtures/gen4/diag_live_scale.json").read_text())["runs"][
        title_name
    ]
    pack = d.evidence.PACKS[title_name]
    title = json.loads((d.REPO / "data/games" / pack / "profile.json").read_text())["titles"][
        title_name
    ]
    sites = [{**title["sites"][i], "id": i} for i in fixture["site_ids"]]
    route = fixture["bridge_response"]["route"]
    route["title"] = title_name
    config = tmp_path / "config.json"
    response = tmp_path / "response.json"
    response.write_text(json.dumps({"id": 1, "route": route}))
    config.write_text(
        json.dumps(
            {
                "artifact": title,
                "command": "settle",
                "requested_rate": 300,
                "lane": str(tmp_path),
                "sites": sites,
                "bridge_request": str(tmp_path / "request.json"),
                "bridge_response": str(response),
            }
        )
    )
    base = 0x02000000
    ram = bytearray(0x400000)
    fs, sub, man, bs, ctx, loc = (
        0x02300000,
        0x02310000,
        0x02320000,
        0x02330000,
        0x02340000,
        0x02360000,
    )

    def w(a, v):
        struct.pack_into("<I", ram, a - base, v)

    f = title["profile"]["probe_field"]
    b = title["profile"]["battle"]
    w(fs, sub)
    w(fs + f["live"], 1)
    w(sub + f["field_app"], 0x02370000)
    w(fs + 0x20, loc)
    position = dict(route["start"])

    def sync():
        for key in ["map", "x", "y", "dir"]:
            w(loc + title["profile"]["location"][key + "_off"], position[key])

    sync()
    total = fixture["frames"]
    wild = total - 900
    table = title["overlay_table"]
    r = lupa.LuaRuntime(unpack_returned_tuples=True)
    held = set()
    r.globals().ROOT = d.REPO.as_posix()
    r.globals().CONFIG = config.as_posix()

    def advance():
        frame = int(r.globals().frame) + 1
        r.globals().frame = frame
        if frame == 120:
            w(title["symbols"]["sFieldSysPtr"]["address"], fs)
        if 120 < frame < wild and frame % 12 == 0:
            for key, (dx, dy, direction) in {
                "Left": (-1, 0, 2),
                "Right": (1, 0, 3),
                "Up": (0, -1, 0),
                "Down": (0, 1, 1),
            }.items():
                if key in held:
                    position["x"] += dx
                    position["y"] += dy
                    position["dir"] = direction
                    if position["x"] <= 666:
                        position["map"] = 33
                    sync()
                    break
        held.clear()
        for slot, overlay in enumerate(sorted({s["overlay_id"] for s in sites})):
            start = 70 if overlay == 129 else wild - 11
            w(table["address"] + slot * 8, overlay)
            w(table["address"] + slot * 8 + 4, int(frame >= start))
        if frame == wild:
            w(sub + 4, man)
            w(man + 0xC, 12)
            w(man + 0x1C, bs)
            w(bs + 0x30, ctx)
            w(ctx + b["mons_off"], 155)
            w(ctx + b["mons_off"] + b["mon_size"], 16 if title_name == "heartgold_hge" else 161)
        if frame == total:
            mon = ctx + b["mons_off"] + b["mon_size"]
            ram[mon + b["level_off"] - base] = 2 if title_name == "heartgold_hge" else 3
            w(mon + b["hp_off"], 13)
            w(mon + b["max_hp_off"], 13)

    def read(a, bus=None):
        return struct.unpack_from("<I", ram, a - base)[0]

    def raw(a, n, bus=None):
        site = next(s for s in sites if s["address"] == a)
        landed = 82 if site["overlay_id"] == 129 else wild + 9
        frame = int(r.globals().frame)
        pin = bytes.fromhex(site["register_hex"])
        # MODEL: reused overlay RAM/BSS may change every frame while still
        # failing the FULL pin. Policy needs every match decision, not an
        # unbounded dump of unrelated mismatched byte values.
        value = pin if frame >= landed else bytes((frame+i) & 255 for i in range(n))
        if frame < landed and value == pin:
            value = value[:-1] + bytes([value[-1] ^ 1])
        return r.table_from(list(value))

    def buttons(t):
        held.clear()
        held.update(k for k, v in t.items() if v)

    def save(path):
        Path(path).write_bytes(b"MODEL diagnostic-produced state")

    r.globals().READ = read
    r.globals().RAW = raw
    r.globals().ADVANCE = advance
    r.globals().BUTTONS = buttons
    r.globals().SAVE = save
    r.execute("""
      frame=1; local old=os.getenv
      os.getenv=function(k) if k=="SLINK_ROOT" then return ROOT elseif k=="G4_DIAG_CONFIG" then return CONFIG end; return old(k) end
      memory={read_u32_le=READ,read_u16_le=function(a,b) return READ(a,b)&0xFFFF end,
          read_u8=function(a,b) return READ(a,b)&0xFF end,read_bytes_as_array=RAW}
      emu={framecount=function() return frame end,frameadvance=ADVANCE,limitframerate=function() end}
      joypad={set=BUTTONS}; client={speedmode=function() end,exit=function() end,screenshot=function() end}
      savestate={save=SAVE}
    """)
    r.execute(d.LUA)
    code, doc = publish_runtime_to_host(tmp_path, monkeypatch, title_name, "settle")
    assert code == 0, doc
    o = doc["observation"]
    assert o["status"] == "OBSERVED" and o["bridge"][0]["status"] == "BATTLE", o
    trace = o["settle"]
    assert trace["encoding"] == "site-state-rle-v1"
    assert max(s["last_frame"] for s in trace["samples"]) == total
    assert sum(s["frames"] for s in trace["samples"]) == total * len(sites)
    assert len(trace["samples"]) < 40 and len((tmp_path / "observation.json").read_bytes()) < 30000
    assert all(s["locations"] for s in trace["samples"] if s["resident"])
    assert any(s['pin_bytes_varied'] and s['frames']>1000 for s in trace['samples'])
    assert sorted(e["delta"] for e in trace["epochs"]) == sorted(
        12 if s["overlay_id"] == 129 else 20 for s in sites
    )
    assert doc["outputs"] and doc["ownership"]["exited"]


def test_publication_encode_failure_is_named_atomic_fail(tmp_path):
    (tmp_path / "observation.json").unlink(missing_ok=True)
    r = api()
    r.globals().OUT = (tmp_path / "observation.json").as_posix()
    r.globals().ROOT = d.REPO.as_posix()
    r.execute("""
      local json=dofile(ROOT.."/lua/json_codec.lua")
      local enormous={terminal=true,qualified=false,status="OBSERVED",applied_rate=300,reason="raw first reason",values={}}
      for i=1,11127*4 do enormous.values[i]={frame=i,site="x",resident=true,pin="aabb",pin_matches=true} end
      assert(DIAG.publish(json,enormous,OUT)==false)
      local f=assert(io.open(OUT,"rb")); PUBLISHED=assert(json.decode(f:read("a"))); f:close()
      assert(PUBLISHED.status=="FAIL" and PUBLISHED.qualified==false and PUBLISHED.terminal==true)
      assert(PUBLISHED.reason:match("^raw first reason;") and PUBLISHED.reason:match("diagnostic encode failed"))
      assert(PUBLISHED.applied_rate==300)
    """)
    assert not (tmp_path / "observation.json.tmp").exists()


def test_missing_fight_name_control_red_revert(tmp_path, monkeypatch):
    original = d.fight_recipe
    test_generated_fight_actual_pack_leg_publishes_identity_pp_and_hp(tmp_path, monkeypatch)
    monkeypatch.setattr(d, "fight_recipe", lambda title, name: dict(title["route_legs"][name]))
    with pytest.raises(AssertionError):
        test_generated_fight_actual_pack_leg_publishes_identity_pp_and_hp(tmp_path, monkeypatch)
    monkeypatch.setattr(d, "fight_recipe", original)
    test_generated_fight_actual_pack_leg_publishes_identity_pp_and_hp(tmp_path, monkeypatch)


@pytest.mark.parametrize("title_name", ["heartgold_hge", "soulsilver"])
def test_uncompressed_settle_scale_control_red_revert(tmp_path, monkeypatch, title_name):
    original = d.LUA
    test_generated_settle_physical_scale_uses_native_executor_and_publishes(
        tmp_path, monkeypatch, title_name
    )
    monkeypatch.setattr(
        d,
        "LUA",
        original.replace(
            "if span and span.last_frame+1==frame", "if false and span and span.last_frame+1==frame"
        ),
    )
    with pytest.raises(AssertionError):
        test_generated_settle_physical_scale_uses_native_executor_and_publishes(
            tmp_path, monkeypatch, title_name
        )
    monkeypatch.setattr(d, "LUA", original)
    test_generated_settle_physical_scale_uses_native_executor_and_publishes(
        tmp_path, monkeypatch, title_name
    )


def test_encode_before_open_control_red_revert(tmp_path, monkeypatch):
    original = d.LUA
    test_publication_encode_failure_is_named_atomic_fail(tmp_path)
    bad = 'function D.publish(json,result,path)\n    local f=assert(io.open(path,"w")); f:write(assert(json.encode(result))); f:close(); return true\nend\n'
    a = original.index("function D.publish(")
    b = original.index("if G4_DIAG_TEST then", a)
    monkeypatch.setattr(d, "LUA", original[:a] + bad + original[b:])
    with pytest.raises(lupa.LuaError):
        test_publication_encode_failure_is_named_atomic_fail(tmp_path)
    assert (tmp_path / "observation.json").read_bytes() == b""
    monkeypatch.setattr(d, "LUA", original)
    test_publication_encode_failure_is_named_atomic_fail(tmp_path)


def test_dead_result_fast_failure_control_red_revert(tmp_path, monkeypatch):
    original = d.collect
    source = Path(d.__file__).read_text()
    old = 'if proc.poll() is not None:\n                        raise RuntimeError(f"invalid diagnostic result after emulator exit: {exc}") from exc'
    assert source.count(old) == 1
    namespace = {"__file__": d.__file__}
    exec(compile(source.replace(old, "continue"), d.__file__, "exec"), namespace)
    namespace["verify_after"] = lambda c: None
    namespace["service_bridge"] = lambda *a: None
    test_dead_process_invalid_result_fails_immediately(tmp_path, monkeypatch, "")
    monkeypatch.setattr(d, "collect", namespace["collect"])
    with pytest.raises(AssertionError):
        test_dead_process_invalid_result_fails_immediately(tmp_path, monkeypatch, "")
    monkeypatch.setattr(d, "collect", original)
    test_dead_process_invalid_result_fails_immediately(tmp_path, monkeypatch, "")


def test_unflushed_config_control_red_revert(tmp_path, monkeypatch):
    original = d.emulator_config_audit
    source = Path(d.__file__).read_text()
    namespace = {"__file__": d.__file__}
    exec(
        compile(
            source.replace("unflushed=after==item['before_sha256']", "unflushed=False"),
            d.__file__,
            "exec",
        ),
        namespace,
    )
    test_killed_emulator_unflushed_rate_uses_lua_witness(tmp_path)
    monkeypatch.setattr(d, "emulator_config_audit", namespace["emulator_config_audit"])
    with pytest.raises(AssertionError):
        test_killed_emulator_unflushed_rate_uses_lua_witness(tmp_path)
    monkeypatch.setattr(d, "emulator_config_audit", original)
    test_killed_emulator_unflushed_rate_uses_lua_witness(tmp_path)
def api():
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().G4_DIAG_TEST = True
    runtime.globals().SLINK_GEN4_PROBE_TEST = True
    runtime.globals().PROBE = runtime.execute((d.REPO / "lua/tests/probe_gen4_hooks.lua").read_text())
    runtime.globals().DIAG = runtime.execute(d.LUA)
    return runtime


def test_fight_uses_exact_frozen_recipe_and_does_not_invent_turns():
    r = api()
    r.execute('''
      buttons={}; frame=0
      local title={profile={battle={}},symbols={x={address=4}},phase_cases={}}
      local leg={name="model",max_frames=5,steps={{press={"A"},hold_frames=2,then_wait_frames=3}},
        ["until"]={symbol="x",deref={},offset=0,value=1}}
      result=DIAG.fight(PROBE,title,leg,function() return frame==5 and 1 or 0 end,
        function(b) frame=frame+1; buttons[#buttons+1]=b.A==true end,function() return frame end)
      assert(frame==5 and #buttons==5 and buttons[1] and buttons[2] and not buttons[3]
        and not buttons[4] and not buttons[5])
      assert(leg.max_frames==5 and leg.steps[1].hold_frames==2 and leg.steps[1].then_wait_frames==3)
      assert(result.recipes[1].outcome=="until_met" and result.recipes[1].frames_used==5)
      assert(result.rng.status=="INCONCLUSIVE" and result.turn_count_available==false)
    ''')


def test_driver_is_outside_every_qualification_surface():
    from tools import gen4_evidence as e
    for kind in e.SCRIPTS:
        for title in e.PACKS:
            paths = e.dependencies(kind, title)
            assert "tools/gen4_diag.py" not in paths
            assert "tests/unit/test_gen4_diag.py" not in paths
    assert Path(d.__file__).resolve() == d.REPO / "tools/gen4_diag.py"


def test_boundary_readiness_gate_does_not_arm_an_unready_site():
    r = api()
    r.globals().REGISTRY = r.execute((d.REPO / "lua/hook_registry.lua").read_text())
    r.execute('''
      local site={id="site",image="ov12",overlay_id=12,address=20,extent=4,register_hex="aabbccdd"}
      local pin="00000000"; local frame=0; local armed=0
      local settle={current={},samples={}}
      local ready=DIAG.boundary_ready(PROBE,{site},function() return pin end,function() return true end,
        function() return frame end,settle,{max_frames=16,measured_max=11,margin=5},{site={}})
      local composite=PROBE.composite(REGISTRY,{validate=function(s) return s end,
        register=function() armed=armed+1; return "handle" end,unregister=function() return true end,
        capture=function() return nil end})
      local monitor=PROBE.phase_monitor(composite,"battle_close",{site},"site",
        function() return true end,ready,function() return frame end)
      monitor.before(); monitor.after(); assert(armed==0)
      pin="aabbccdd"; frame=9; monitor.before(); monitor.after(); assert(armed==1)
      monitor.finish(); assert(composite:live_handles()==0)
    ''')


def test_settle_is_uncensored_and_first_resident_sample_is_left_censored():
    r = api()
    r.execute('''
      local sites={{id="late",overlay_id=12,register_hex="aabb",address=20,extent=2}}
      local trace=DIAG.settle_trace(sites); local active=false; local pin="0000"
      local function sample(f) DIAG.settle_sample(trace,sites,function() return active end,
        function() return pin end,f) end
      sample(0); active=true; sample(1)
      for f=2,20 do sample(f) end
      pin="aabb"; sample(21)
      assert(#trace.samples==3 and trace.samples[2].frames==20 and trace.epochs[1].delta==20)
      assert(trace.epochs[1].status=="SETTLED" and trace.epochs[1].active_frame==1)
      local first=DIAG.settle_trace(sites)
      DIAG.settle_sample(first,sites,function() return true end,function() return "aabb" end,0)
      assert(first.epochs[1].status=="LEFT_CENSORED" and first.epochs[1].delta==nil)
      assert(DIAG.settle_verdict(first)=="OBSERVED_CENSORED" and DIAG.settle_verdict(trace)=="OBSERVED")
    ''')


def test_attach_resident_is_reported_censored_without_a_measured_delta():
    r = api()
    r.execute('''
      local sites={{id="boot",overlay_id=129,register_hex="aabb",address=20,extent=2}}
      local trace=DIAG.settle_trace(sites)
      DIAG.settle_sample(trace,sites,function() return true end,function() return "aabb" end,0)
      local status,facts=DIAG.settle_verdict(trace)
      assert(status=="OBSERVED_CENSORED" and facts.left_censored==true)
      assert(trace.epochs[1].left_censored==true and trace.epochs[1].delta==nil)
      local cold=DIAG.settle_trace(sites)
      DIAG.settle_sample(cold,sites,function() return false end,function() return "0000" end,0)
      DIAG.settle_sample(cold,sites,function() return true end,function() return "aabb" end,1)
      local complete,uncensored=DIAG.settle_verdict(cold)
      assert(complete=="OBSERVED" and uncensored.left_censored==false and cold.epochs[1].delta==0)
    ''')


def test_recorded_rate_is_the_rate_applied_to_the_client():
    r = api()
    r.execute('''
      local calls={}; local applied
      local rate=DIAG.apply_rate({limitframerate=function(on) calls[#calls+1]=on end},
        {speedmode=function(value) applied=value end},300)
      assert(calls[1]==true and applied==300 and rate==applied)
    ''')


def test_fight_reports_named_table_errors_without_pointer_text():
    r = api()
    r.execute('''
      local title={profile={battle={}},symbols={x={address=4}},phase_cases={}}
      local leg={name="model",max_frames=1,steps={{press={"A"},hold_frames=1,then_wait_frames=0}},
        ["until"]={symbol="x",deref={},offset=0,value=1}}
      local function fail(value)
        return DIAG.fight(PROBE,title,leg,function() return 0 end,function() error(value,0) end,function() return 0 end)
      end
      local opened=fail({open="missing predicate source"})
      assert(opened.status=="OPEN" and opened.reason=="missing predicate source")
      local fault=fail({check="invalid site mode"})
      assert(fault.status=="FAIL" and fault.reason=="invalid site mode")
      local unknown=fail({anything=3})
      assert(unknown.status=="FAIL" and not unknown.reason:match("table: 0x"))
    ''')


def test_pp_deltas_are_ordinals_with_battler_and_move_identity():
    r = api()
    r.execute('''
      local out={pp_deltas={}}; local a={our_species=155,our_moves={33,43,0,0},our_pp={35,40,0,0},
        enemy_species=19,enemy_moves={33,39,0,0},enemy_pp={35,30,0,0},enemy_hp=17}
      local b={our_species=155,our_moves={33,43,0,0},our_pp={35,39,0,0},
        enemy_species=19,enemy_moves={33,39,0,0},enemy_pp={34,30,0,0},enemy_hp=13}
      DIAG.pp_delta(out,a,b,90)
      assert(#out.pp_deltas==2 and out.pp_deltas[1].slot==2 and out.pp_deltas[1].move_id==43)
      assert(out.pp_deltas[1].ordinal==1 and out.pp_deltas[1].battler=="our")
      assert(out.pp_deltas[2].slot==1 and out.pp_deltas[2].battler=="enemy")
      assert(out.pp_deltas[1].turn==nil)
      assert(#out.hp_changes==1 and out.hp_changes[1].before==17 and out.hp_changes[1].after==13
        and out.hp_changes[1].cause=="UNMEASURED")
    ''')


def test_boundary_preserves_callback_vs_post_advance_frame_parity():
    r = api()
    r.globals().REGISTRY = r.execute((d.REPO / "lua/hook_registry.lua").read_text())
    r.execute('''
      frame=7; wanted=true; callback=nil
      local site={id="exit",address=20,mode="thumb",fire_hex="01000000"}
      local binding={validate=function(s) return s end,register=function(s,cb) callback=cb; return "guid" end,
        unregister=function() return true end,capture=function(s)
          return {id=s.id,frame=frame,step_id=state.step_id} end}
      local composite=PROBE.composite(REGISTRY,binding)
      monitor,state=PROBE.phase_monitor(composite,"battle_close",{site},"exit",
        function() return wanted end,function() return true end,function() return frame end)
      monitor.before(); callback(20,1,0); wanted=false; frame=frame+1; monitor.after()
      monitor.before(); monitor.after(); monitor.finish()
      local b=state.close_boundaries[1]
      assert(b.producer_frames[1]==7 and b.fall_frame==8 and b.frame==8)
      assert(b.producer_steps[1]==b.fall_step_id and b.pending==1 and state.seen[1]==7)
      assert(#state.seen==1 and state.second_drain==0 and composite:live_handles()==0)
      result=DIAG.boundary_result(state,{7},{1},composite)
      assert(result.status=="OBSERVED" and result.frame_parity.callback_minus_fall==-1)
    ''')


@pytest.mark.parametrize("mode", ["timeout", "error"])
def test_owned_process_cleanup_and_error_publication(tmp_path, monkeypatch, mode):
    import json
    class Process:
        pid = 412
        stopped = False
        def poll(self): return 0 if self.stopped else None
        def terminate(self): self.stopped = True
        def wait(self, timeout):
            if not self.stopped:
                raise d.subprocess.TimeoutExpired("model", timeout)
            return 0
    proc = Process()
    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(d.g4, "kill_our_emuhawk", lambda lane: None)
    monkeypatch.setattr(d, "verify_after", lambda config: None)
    def service(*args):
        if mode == "error":
            raise ValueError("model planner error")
    monkeypatch.setattr(d, "service_bridge", service)
    cfg = {"qualified": False, "hashes": {}, "source_head": "model"}
    verdict = d.collect(cfg, tmp_path, ["owned-emulator", "--config="+str(tmp_path / "config.ini")],
                        planner=None, timeout=0 if mode == "timeout" else 2)
    out = json.loads((tmp_path / "diagnostic.json").read_text())
    assert proc.stopped and out["ownership"]["pid"] == 412
    assert out["ownership"]["exited"] and out["qualified"] is False
    assert verdict == 1 and out["status"] == "FAIL"
    assert ("timeout" if mode == "timeout" else "model planner error") in out["reason"]


@pytest.mark.parametrize("original,replacement,test", [
    ("pcall(M.play_recipe,leg,function(buttons)", "pcall(M.play_recipe,leg,function(buttons) buttons.A=not buttons.A;",
     test_fight_uses_exact_frozen_recipe_and_does_not_invent_turns),
    ("left_censored=censored", "left_censored=false",
     test_settle_is_uncensored_and_first_resident_sample_is_left_censored),
    ("local active=resident(s.overlay_id)==true", "if frame>16 then return end; local active=resident(s.overlay_id)==true",
     test_settle_is_uncensored_and_first_resident_sample_is_left_censored),
    ("callback_minus_fall=f-b.fall_frame", "callback_minus_fall=0",
     test_boundary_preserves_callback_vs_post_advance_frame_parity),
    ("return M.phase_sites_ready(sites,bytes,resident,frame(),settle,policy,image_pins,wanted)", "return true",
     test_boundary_readiness_gate_does_not_arm_an_unready_site),
    ('return facts.left_censored and "OBSERVED_CENSORED" or "OBSERVED",facts', 'return "OBSERVED",facts',
     test_attach_resident_is_reported_censored_without_a_measured_delta),
    ("client.speedmode(rate)", "client.speedmode(100)", test_recorded_rate_is_the_rate_applied_to_the_client),
    ('if type(why)=="table" then', 'if false then', test_fight_reports_named_table_errors_without_pointer_text),
])
def test_lua_controls_red_and_revert(monkeypatch, original, replacement, test):
    source = d.LUA
    assert source.count(original) == 1
    test()
    monkeypatch.setattr(d, "LUA", source.replace(original, replacement))
    with pytest.raises((AssertionError, lupa.LuaError)):
        test()
    monkeypatch.setattr(d, "LUA", source)
    test()


@pytest.mark.parametrize("reverse", [False, True])
def test_generated_boundary_script_runs_real_monitor_with_frame_end_increment(tmp_path, monkeypatch, reverse):
    """Execute the entire generated runtime, not just its pure helper functions."""
    import json
    import struct
    (tmp_path/'observation.json').unlink(missing_ok=True)

    from tests.unit.test_gen4_battle_faint_model import BASE, SUB0, World
    title = json.loads((d.REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"]["heartgold"]
    case = next(c for c in title["phase_cases"] if c["name"] == "battle_close")
    producer = title["sites"][case["producer_site"]]
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"lane": tmp_path.as_posix(), "artifact": title, "command": "boundary",
                                 "phase_case": case, "state_path": "model", "requested_rate": 300,
                                 "phase_settle": {"max_frames": 16, "measured_max": 11, "margin": 5},
                                 "phase_image_pins": {case["producer_site"]: {}},
                                 "producer_word": int(producer["fire_hex"], 16)}))
    world = World()
    r = lupa.LuaRuntime(unpack_returned_tuples=True)
    r.globals().CONFIG = config.as_posix()
    r.globals().ROOT = d.REPO.as_posix()
    r.globals().PIN = producer["register_hex"]
    r.globals().SITE = producer["address"]
    r.globals().WORD = int(producer["fire_hex"], 16)
    r.globals().PC = producer["address"] + 4
    r.globals().REVERSE = reverse
    r.globals().READ = lambda a, bus: struct.unpack_from("<I", world.m, a - BASE)[0]
    r.globals().FALL = lambda: world.w32(SUB0 + 4, 0)
    r.execute('''
      local original=os.getenv
      os.getenv=function(key) if key=="SLINK_ROOT" then return ROOT elseif key=="G4_DIAG_CONFIG" then return CONFIG end; return original(key) end
      frame=7616; callbacks={}; order={}
      memory={read_u32_le=READ,read_bytes_as_array=function(a,n)
        assert(a==SITE); local bytes={}; for i=1,n do bytes[i]=tonumber(PIN:sub(i*2-1,i*2),16) end; return bytes end}
      event={on_bus_exec=function(cb,a,name,bus) callbacks[name]=cb; return name end,
        unregisterbyid=function(h) callbacks[h]=nil; return true end}
      emu={limitframerate=function(on) assert(on) end,framecount=function() return frame end,getregister=function() return PC end,
        frameadvance=function()
          if frame==7616+197 then
            local names={}; for name in pairs(callbacks) do names[#names+1]=name end; table.sort(names)
            for n=1,#names do local i=REVERSE and #names+1-n or n; order[#order+1]=names[i]; callbacks[names[i]](SITE,WORD,0) end
            FALL()
          end
          frame=frame+1
        end}
      joypad={set=function() end}; savestate={load=function() end}; client={exit=function() end,speedmode=function(v) APPLIED=v end}
    ''')
    r.execute(d.LUA)
    observed = json.loads((tmp_path / "observation.json").read_text())
    assert observed["status"] == "OBSERVED", observed
    assert observed["frame_parity"]["callback_minus_fall"] == -1
    assert observed["retained"] == 0 and observed["state"]["pending_at_close"] == 1
    assert observed["qualified"] is False
    assert observed["applied_rate"] == r.globals().APPLIED == 300
    assert r.globals().order[1].startswith("g4probe" if reverse else "g4diag")
    code,doc=publish_runtime_to_host(tmp_path,monkeypatch,"heartgold","boundary")
    assert code==0 and doc['observation']['frame_parity']['advance_token']==198
    assert doc['observation']['state']['seen_steps']==[198]


@pytest.mark.parametrize("reverse", [False, True])
def test_opposite_order_token_control_red_revert(tmp_path, monkeypatch, reverse):
    source = d.LUA
    needle = "oracle_steps[#oracle_steps+1]=state.step_id"
    assert source.count(needle) == 1
    test_generated_boundary_script_runs_real_monitor_with_frame_end_increment(tmp_path, monkeypatch, reverse)
    monkeypatch.setattr(d, "LUA", source.replace(needle, needle+"+1"))
    with pytest.raises(AssertionError):
        test_generated_boundary_script_runs_real_monitor_with_frame_end_increment(tmp_path, monkeypatch, reverse)
    monkeypatch.setattr(d, "LUA", source)
    test_generated_boundary_script_runs_real_monitor_with_frame_end_increment(tmp_path, monkeypatch, reverse)


@pytest.mark.parametrize("mode", ["timeout", "error"])
def test_cleanup_control_red_and_revert(tmp_path, monkeypatch, mode):
    source = Path(d.__file__).read_text()
    assert source.count("proc.terminate()") == 1
    namespace = {"__file__": d.__file__}
    exec(compile(source.replace("proc.terminate()", "pass # removed terminate control"), d.__file__, "exec"), namespace)
    original = d.collect
    test_owned_process_cleanup_and_error_publication(tmp_path, monkeypatch, mode)
    monkeypatch.setattr(d, "collect", namespace["collect"])
    with pytest.raises(AssertionError):
        test_owned_process_cleanup_and_error_publication(tmp_path, monkeypatch, mode)
    monkeypatch.setattr(d, "collect", original)
    test_owned_process_cleanup_and_error_publication(tmp_path, monkeypatch, mode)


def model_collect(tmp_path, monkeypatch, *, qualified=False):
    import json
    class Process:
        pid = 413
        def poll(self): return 0
        def wait(self, timeout): return 0
    state = tmp_path / "native_battle_settled.State"
    state.write_bytes(b"model native state")
    (tmp_path / "native_resync.State").write_bytes(b"model resync state")
    input_state = tmp_path / "start.State"
    input_state.write_bytes(b"copied input")
    (tmp_path / "observation.json").write_text(json.dumps({"terminal": True, "qualified": qualified,
                                                        "status": "OBSERVED", "applied_rate": 300}))
    cfg = {"schema": "gen4-diagnostic-v1", "qualified": False, "source_head": "MODEL", "command": "settle",
           "title": "heartgold", "rom_sha1": d.gen4_pins.ROM_SPECS["heartgold"][0],
           "requested_rate": 300, "hashes": {"driver": "model"}, "state_path": str(input_state)}
    with monkeypatch.context() as patch:
        patch.setattr(d.subprocess, "Popen", lambda *a, **k: Process())
        patch.setattr(d.g4, "kill_our_emuhawk", lambda lane: None)
        patch.setattr(d, "verify_after", lambda config: None)
        patch.setattr(d, "service_bridge", lambda *a: None)
        result = d.collect(cfg, tmp_path, ["model-owned"], planner=None, timeout=2)
    return result, json.loads((tmp_path / "diagnostic.json").read_text()), state


def test_every_output_state_has_diagnostic_provenance_and_reviewed_hash(tmp_path, monkeypatch):
    code, doc, state = model_collect(tmp_path, monkeypatch)
    assert code == 0
    assert set(doc["outputs"]) == {"native_battle_settled.State", "native_resync.State"}
    for name, entry in doc["outputs"].items():
        assert entry["producer"] == "tools/gen4_diag.py" and entry["qualified"] is False
        assert entry["sha256"] == d.sha256(tmp_path / name)
        assert entry["setup"] == "DIAGNOSTIC_PRODUCED"
    assert doc["states"]["start.State"]["setup"] == "RETAINED_INPUT_COPY"
    assert d.check_state_manifest(state, tmp_path / "diagnostic.json", d.sha256(state))["qualified"] is False
    with pytest.raises(AssertionError, match="state hash"):
        d.check_state_manifest(state, tmp_path / "diagnostic.json", "0" * 64)
    assert d.check_state_manifest(state, tmp_path / "diagnostic.json", d.sha256(state))["sha256"] == d.sha256(state)


def test_output_state_provenance_control_red_revert(tmp_path, monkeypatch):
    source = Path(d.__file__).read_text()
    needle = '"producer": "tools/gen4_diag.py", "qualified": False, "sha256"'
    assert source.count(needle) == 1
    namespace = {"__file__": d.__file__}
    exec(compile(source.replace(needle, '"producer": "unknown", "qualified": False, "sha256"'), d.__file__, "exec"), namespace)
    namespace["verify_after"] = lambda config: None
    namespace["service_bridge"] = lambda *a: None
    original = d.collect
    test_every_output_state_has_diagnostic_provenance_and_reviewed_hash(tmp_path, monkeypatch)
    monkeypatch.setattr(d, "collect", namespace["collect"])
    with pytest.raises(AssertionError):
        test_every_output_state_has_diagnostic_provenance_and_reviewed_hash(tmp_path, monkeypatch)
    monkeypatch.setattr(d, "collect", original)
    test_every_output_state_has_diagnostic_provenance_and_reviewed_hash(tmp_path, monkeypatch)


def test_collect_rejects_raw_qualification_claim(tmp_path, monkeypatch):
    code, doc, _ = model_collect(tmp_path, monkeypatch, qualified=True)
    assert code == 1 and doc["status"] == "FAIL"
    assert "claimed qualification" in doc["reason"] and doc["qualified"] is False


def test_collect_rejects_config_qualification_before_popen(tmp_path, monkeypatch):
    import json
    started = []
    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: started.append(True))
    monkeypatch.setattr(d, "verify_after", lambda config: None)
    code = d.collect({"qualified": True, "source_head": "MODEL"}, tmp_path, ["model-owned"], planner=None, timeout=2)
    doc = json.loads((tmp_path / "diagnostic.json").read_text())
    assert code == 1 and not started and "config claimed qualification" in doc["reason"]


def test_collect_artifact_is_stale_for_real_receipt_consumers_even_without_flag(tmp_path, monkeypatch):
    from tools import gen4_evidence as e, gen4_routes as routes
    code, doc, _ = model_collect(tmp_path, monkeypatch)
    assert code == 0
    surface = e.snapshot("probe", "heartgold", committed=False)
    doc["qualified"] = True  # Shape, not this flag, prevents promotion.
    path = tmp_path / "diagnostic.json"
    import json
    path.write_text(json.dumps(doc))
    with pytest.raises(e.StaleEvidenceError, match="module_sha256"):
        e.bind(doc, surface, title="heartgold", rom_sha1=doc["rom_sha1"])
    assert routes.verify_receipt(path, "route")[0] == "STALE"


def test_runbook_uses_reviewed_state_manifest_and_correct_censoring_class():
    text = (d.REPO / "data/gen4/scenarios/README.md").read_text()
    assert "OBSERVED_CENSORED" in text
    assert "G4_SS_ONE_SHA256" in text and "G4_SS_TWO_SHA256" in text
    assert "check_state_manifest(state," in text
    assert "First observed residency is\nLEFT_CENSORED" not in text
    assert "be witnessed uncensored" not in text


@pytest.mark.parametrize("replacement", ["First observed residency is\nLEFT_CENSORED", "be witnessed uncensored"])
def test_runbook_censoring_control_red_revert(monkeypatch, replacement):
    path = d.REPO / "data/gen4/scenarios/README.md"
    source = path.read_text()
    original = Path.read_text
    test_runbook_uses_reviewed_state_manifest_and_correct_censoring_class()
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", lambda p, *a, **k: source+"\n"+replacement if p==path else original(p, *a, **k))
        with pytest.raises(AssertionError):
            test_runbook_uses_reviewed_state_manifest_and_correct_censoring_class()
    test_runbook_uses_reviewed_state_manifest_and_correct_censoring_class()


def test_observed_config_autosave_keeps_immutable_inputs_strict(tmp_path, monkeypatch):
    import json
    # Minimal committed copies of the PHYSICAL b809 D3 config (lane d3-hg-1003033806): the audited keys plus
    # every key EmuHawk rewrote, so the replay is hermetic.
    fixtures = Path(__file__).resolve().parents[1] / 'fixtures' / 'gen4'
    before = json.loads((fixtures / 'diag_config_autosave_before.json').read_text(encoding='utf-8'))
    after = json.loads((fixtures / 'diag_config_autosave_after.json').read_text(encoding='utf-8'))
    config = tmp_path / 'bizhawk.ini'
    config.write_text(json.dumps(before))
    source = tmp_path / 'diagnostic.lua'
    source.write_text('immutable script')
    diag = tmp_path / 'diagnostic-config.json'
    diag.write_text('immutable input')
    state = tmp_path / 'start.State'
    state.write_bytes(b'immutable state')
    rom = tmp_path / 'rom.nds'
    rom.write_bytes(b'immutable staged ROM')
    cfg = {'source_head':'MODEL','requested_rate':300,'originals':{},'hashes':{'driver':d.sha256(d.__file__)},
           'generated_paths':{str(p):d.sha256(p) for p in [source,diag,state,rom]},
           'emulator_config':{'path':str(config),'before_sha256':d.sha256(config),
                              'expected_settings':d.emulator_settings(before,300)},
           'frozen_surface':{},'title':'heartgold','rom_sha1':'x'}
    monkeypatch.setattr(d.subprocess,'check_output',lambda cmd,**kw:'MODEL' if 'rev-parse' in cmd else '')
    monkeypatch.setattr(d.evidence,'snapshot',lambda *a,**k:{})
    monkeypatch.setattr(d.evidence,'bind',lambda *a,**k:None)
    config.write_text(json.dumps(after))
    audit=d.verify_after(cfg)
    assert audit['before_sha256']!=audit['after_sha256'] and audit['settings_valid']
    for path in [source,diag,state,rom]:
        original=path.read_bytes()
        path.write_bytes(original+b'!')
        with pytest.raises(AssertionError,match='generated diagnostic input changed'):
            d.verify_after(cfg)
        path.write_bytes(original)
        assert d.verify_after(cfg)['settings_valid']
    bad={**after,'SpeedPercent':800}
    config.write_text(json.dumps(bad))
    with pytest.raises(AssertionError,match='emulator settings changed'):
        d.verify_after(cfg)
    config.write_text(json.dumps(after))
    assert d.verify_after(cfg)['settings_valid']


def test_observed_frame_one_attach_records_uncensored_delay():
    r=api()
    r.execute('''
      local sites={{id="cold",overlay_id=12,address=20,extent=2,register_hex="aabb"}}
      local trace=DIAG.begin_settle(sites,function() return false end,function() return "0000" end,1)
      assert(trace.attach_frame==1)
      DIAG.settle_sample(trace,sites,function() return true end,function() return "0000" end,10)
      DIAG.settle_sample(trace,sites,function() return true end,function() return "aabb" end,12)
      assert(trace.epochs[1].delta==2 and not trace.epochs[1].left_censored)
      assert(DIAG.settle_verdict(trace)=="OBSERVED")
      local loaded=DIAG.begin_settle(sites,function() return true end,function() return "aabb" end,1)
      assert(loaded.epochs[1].left_censored and loaded.epochs[1].delta==nil)
      local bytes_first=DIAG.begin_settle(sites,function() return false end,function() return "aabb" end,1)
      DIAG.settle_sample(bytes_first,sites,function() return true end,function() return "aabb" end,2)
      assert(bytes_first.epochs[1].left_censored and bytes_first.epochs[1].delta==nil)
    ''')


def test_initial_hp_zero_waits_bounded_and_refusal_keeps_values():
    r=api()
    r.execute('''
      local frame=0
      local function sample() return {our_hp=frame<9 and 0 or 20,enemy_hp=frame<9 and 0 or 17,value_available=true} end
      local ready=DIAG.wait_battle(sample,function() return true end,function(b)
        assert(next(b)==nil); frame=frame+1 end,function() return frame end,900)
      assert(ready.status=="READY" and ready.frames_used==9 and ready.initial.our_hp==0)
      assert(ready.last.our_hp==20 and ready.last.enemy_hp==17)
      frame=0
      local dead=DIAG.wait_battle(function() return {our_hp=0,enemy_hp=17} end,
        function() return true end,function() frame=frame+1 end,function() return frame end,900)
      assert(dead.status=="FAIL" and dead.frames_used==900 and dead.initial.our_hp==0 and dead.last.enemy_hp==17)
      assert(dead.reason:match("our_hp=0") and dead.reason:match("enemy_hp=17"))
    ''')


def test_raw_failure_stays_first_when_audit_fails():
    out={"status":"FAIL","reason":"state is not a live settled battle; our_hp=0"}
    d.record_failure(out,"post-run identity verification: generated Lua changed")
    assert out["reason"].startswith("state is not a live settled battle; our_hp=0;")
    assert out["audit_errors"]==["post-run identity verification: generated Lua changed"]


def test_old_byte_config_check_is_red_then_semantic_check_reverts(tmp_path, monkeypatch):
    original=d.verify_after
    def old_check(config):
        value=original(config)
        assert d.sha256(config["emulator_config"]["path"])==config["emulator_config"]["before_sha256"],"old mutable-byte check"
        return value
    test_observed_config_autosave_keeps_immutable_inputs_strict(tmp_path,monkeypatch)
    monkeypatch.setattr(d,"verify_after",old_check)
    with pytest.raises(AssertionError,match="old mutable-byte check"):
        test_observed_config_autosave_keeps_immutable_inputs_strict(tmp_path,monkeypatch)
    monkeypatch.setattr(d,"verify_after",original)
    test_observed_config_autosave_keeps_immutable_inputs_strict(tmp_path,monkeypatch)


@pytest.mark.parametrize("old,new,test",[
    ("for i=0,limit do","for i=0,0 do",test_initial_hp_zero_waits_bounded_and_refusal_keeps_values),
])
def test_live_instrument_controls_red_revert(monkeypatch,old,new,test):
    source=d.LUA
    test()
    assert source.count(old)==1
    monkeypatch.setattr(d,"LUA",source.replace(old,new))
    with pytest.raises((AssertionError,lupa.LuaError)):
        test()
    monkeypatch.setattr(d,"LUA",source)
    test()


def test_frame_one_runtime_reaches_native_bridge_then_settle(tmp_path):
    import json
    title=json.loads((d.REPO/'data/games/gen4_hgss/profile.json').read_text())['titles']['heartgold']
    site={**title['sites']['battle_faint_cmd'],'id':'battle_faint_cmd'}
    config=tmp_path/'cfg.json'
    config.write_text(json.dumps({'artifact':title,'lane':str(tmp_path),'command':'settle','requested_rate':300,
       'sites':[site],'bridge_request':str(tmp_path/'request.json'),'bridge_response':str(tmp_path/'response.json')}))
    (tmp_path/'response.json').write_text(json.dumps({'id':1,'route':{}}))
    r=lupa.LuaRuntime(unpack_returned_tuples=True)
    f=title['profile']['probe_field']
    fs=0x02300000
    sub=0x02310000
    values={title['symbols']['sFieldSysPtr']['address']:fs,fs+f['sub']:sub,fs+f['live']:1,sub+f['field_app']:0x02320000}
    table=title['overlay_table']['address']
    r.globals().READ=lambda a,bus: (12 if a==table else 1 if a==table+4 and r.globals().ACTIVE else values.get(a,0))
    r.globals().PIN=site['register_hex']
    r.globals().CONFIG=config.as_posix()
    r.globals().ROOT=d.REPO.as_posix()
    r.execute('''
      frame=1;ACTIVE=false
      local oldget=os.getenv
      os.getenv=function(k) if k=="SLINK_ROOT" then return ROOT elseif k=="G4_DIAG_CONFIG" then return CONFIG end; return oldget(k) end
      local oldfile=dofile
      dofile=function(path)
        if path:match("gen4_route_play.lua$") then return {position=function() return {map=1,x=1,y=1,dir=0} end,
          run=function(ctx) ACTIVE=true;LANDED=frame+4;for i=1,5 do ctx.step({}) end
            error({route_result={status="BATTLE",detail="model natural wild launch",lines={"RESULT BATTLE settled"}}},0) end} end
        return oldfile(path)
      end
      memory={read_u32_le=READ,read_bytes_as_array=function(a,n)
        local t={};for i=1,n do t[i]=LANDED and frame>=LANDED and tonumber(PIN:sub(i*2-1,i*2),16) or 0 end;return t end}
      emu={limitframerate=function() end,framecount=function() return frame end,frameadvance=function() frame=frame+1 end}
      joypad={set=function() end};client={speedmode=function() end,exit=function() end};savestate={}
    ''')
    r.execute(d.LUA)
    doc=json.loads((tmp_path/'observation.json').read_text())
    assert doc['status']=='OBSERVED' and doc['attach_frame']==1 and len(doc['bridge'])==1,doc
    assert doc['settle']['epochs'][0]['delta']==3 and doc['left_censored'] is False


def test_first_failure_overwrite_control_red_revert(monkeypatch):
    original=d.record_failure
    test_raw_failure_stays_first_when_audit_fails()
    monkeypatch.setattr(d,"record_failure",lambda out,message:out.update(status="FAIL",reason=message))
    with pytest.raises(AssertionError):
        test_raw_failure_stays_first_when_audit_fails()
    monkeypatch.setattr(d,"record_failure",original)
    test_raw_failure_stays_first_when_audit_fails()


@pytest.mark.parametrize("kind",['Unthrottled','TraceArm9Thumb','TraceArm9Arm','NDS_core','Firmware','NDS_Base','NDS_ROM','NDS_Cheats'])
def test_expanded_config_keys_mutations_refuse_and_revert(tmp_path,kind):
    import copy
    import json
    before=json.loads((d.REPO/'tests/fixtures/gen4/diag_config_autosave_before.json').read_text())
    after=json.loads((d.REPO/'tests/fixtures/gen4/diag_config_autosave_after.json').read_text())
    # These are the new key categories; the old projection ignores every one.
    assert 'Unthrottled' in before and 'CoreSettings' in before
    path=tmp_path/'bizhawk.ini'
    path.write_text(json.dumps(after))
    cfg={'requested_rate':300,'emulator_config':{'path':str(path),'before_sha256':'before',
         'expected_settings':d.emulator_settings(before,300)}}
    assert d.emulator_config_audit(cfg)['settings_valid']
    bad=copy.deepcopy(after)
    if kind=='Unthrottled':
        bad[kind]=not bad[kind]
    elif kind.startswith('TraceArm9'):
        bad['CoreSettings'][d.g4.NDS_CORE][kind]=not bad['CoreSettings'][d.g4.NDS_CORE].get(kind,False)
    elif kind=='NDS_core':
        bad['CoreSettings'][d.g4.NDS_CORE]['unrecognised_new_core_setting']=True
    else:
        system='Global_NULL' if kind=='Firmware' else 'NDS'
        type_={'Firmware':'Firmware','NDS_Base':'Base','NDS_ROM':'ROM','NDS_Cheats':'Cheats'}[kind]
        item=next(x for x in bad['PathEntries']['Paths'] if x['System']==system and x['Type']==type_)
        item['Path']='changed'
    path.write_text(json.dumps(bad))
    assert not d.emulator_config_audit(cfg)['settings_valid'],kind
    path.write_text(json.dumps(after))
    assert d.emulator_config_audit(cfg)['settings_valid']


@pytest.mark.parametrize("region_id",[1,2])
def test_region_one_at_attach_then_main_region_stays_censored(region_id):
    r=api()
    r.globals().START_REGION=region_id
    r.execute('''
      local t={address=100,regions=3,per_region=8,entry_size=8,id_off=0,active_off=4}
      local region=START_REGION
      local function read(a)
        local start=t.address+region*t.per_region*t.entry_size
        return a==start and 12 or a==start+4 and 1 or 0
      end
      local function any(id) return DIAG.any_region_resident(t,read,id) end
      local sites={{id="loaded",overlay_id=12,address=20,extent=2,register_hex="aabb"}}
      local trace=DIAG.begin_settle(sites,function() return region==0 end,function() return "0000" end,1,any)
      region=0
      DIAG.settle_sample(trace,sites,function() return true end,function() return "aabb" end,9)
      assert(trace.epochs[1].left_censored and trace.epochs[1].delta==nil)
      assert(DIAG.settle_verdict(trace)=="OBSERVED_CENSORED")
    ''')


@pytest.mark.parametrize("region_id",[1,2])
def test_any_region_censoring_control_red_revert(monkeypatch,region_id):
    source=d.LUA
    start=source.index('function D.any_region_resident(')
    end=source.index('function D.begin_settle(',start)
    old=source[start:end]
    assert source.count(old)==1
    test_region_one_at_attach_then_main_region_stays_censored(region_id)
    monkeypatch.setattr(d,'LUA',source.replace(old,old.replace('for region=0,t.regions-1 do','for region=0,0 do')))
    with pytest.raises((AssertionError,lupa.LuaError)):
        test_region_one_at_attach_then_main_region_stays_censored(region_id)
    monkeypatch.setattr(d,'LUA',source)
    test_region_one_at_attach_then_main_region_stays_censored(region_id)


def test_bom_config_audit_reader_red_revert(tmp_path,monkeypatch):
    import json
    settings=json.loads((d.REPO/'tests/fixtures/gen4/diag_config_autosave_after.json').read_text())
    path=tmp_path/'bizhawk.ini'
    path.write_text(json.dumps(settings),encoding='utf-8-sig')
    cfg={'requested_rate':300,'emulator_config':{'path':str(path),'before_sha256':'before',
        'expected_settings':d.emulator_settings(settings,300)}}
    assert d.emulator_config_audit(cfg)['settings_valid']
    original=Path.read_text
    with monkeypatch.context() as patch:
        patch.setattr(Path,'read_text',lambda p,*a,**k:original(p) if p==path else original(p,*a,**k))
        with pytest.raises(json.JSONDecodeError):
            d.emulator_config_audit(cfg)
    assert d.emulator_config_audit(cfg)['settings_valid']
