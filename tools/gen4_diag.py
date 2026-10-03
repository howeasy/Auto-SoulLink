"""Non-qualifying, read-only-in-game Gen 4 diagnostics. Slot grant required to run.

This committed host driver is deliberately outside gen4_evidence.dependencies.
Generated scripts reuse the frozen probe API, not harness function overrides.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools import (  # noqa: E402
    gen4_evidence as evidence,
    gen4_fixtures as g4,
    gen4_pins,
    gen4_routes,
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def service_bridge(config, planner, seen):
    request = Path(config["bridge_request"])
    if not request.is_file():
        return seen
    try:
        pending = json.loads(request.read_text())
    except json.JSONDecodeError:
        return seen
    if pending["id"] == seen:
        return seen
    try:
        answer = {"id": pending["id"], "route": planner.plan(pending)}
    except (FileNotFoundError, gen4_routes.RomAbsent) as exc:
        answer = {"id": pending["id"], "open": str(exc)}
    except ValueError as exc:
        answer = {"id": pending["id"], "error": str(exc)}
    target = Path(config["bridge_response"])
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(answer))
    os.replace(temp, target)
    return pending["id"]


def verify_after(config):
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip() == config["source_head"], "source cut moved"
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip(), "dirty source"
    for path, expected in config["originals"].items():
        assert sha256(Path(path)) == expected, f"original input changed: {path}"
    assert sha256(Path(__file__)) == config["hashes"]["driver"], "driver changed during run"
    for path, expected in config["generated_paths"].items():
        assert sha256(Path(path)) == expected, f"generated diagnostic input changed: {path}"
    evidence.bind(config["frozen_surface"], evidence.snapshot("probe", config["title"]),
                  title=config["title"], rom_sha1=config["rom_sha1"])


def collect(config, lane, command, *, planner, timeout):
    """Own one Popen handle; publish diagnostic even on timeout/planner/cleanup error."""
    out = {**config, "qualified": False, "level": "SOURCE", "status": "FAIL",
           "ownership": {"pid": None, "command": command, "lane": lane.as_posix(), "exited": True, "started": False}}
    proc = None
    try:
        proc = subprocess.Popen(command, cwd=lane, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env={**os.environ, **config.get("launch_env", {})},
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        out["ownership"] = {"pid": proc.pid, "command": command, "lane": lane.as_posix(),
                            "popen_at_utc": datetime.datetime.now(datetime.UTC).isoformat(), "exited": False, "started": True}
        out["level"] = "PHYSICAL"
        raw = lane / "observation.json"
        deadline, seen = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            seen = service_bridge(config, planner, seen)
            if raw.is_file():
                try:
                    observed = json.loads(raw.read_text())
                except json.JSONDecodeError:
                    continue
                assert observed.get("terminal") is True, "non-terminal diagnostic"
                assert observed.get("qualified") is False, "diagnostic claimed qualification"
                out.update(observation=observed, status=observed["status"], reason=observed.get("reason", ""))
                out["outputs"] = {p.name: sha256(p) for p in lane.glob("*_battle_settled.State")}
                break
            if proc.poll() is not None:
                raise RuntimeError(f"emulator exited before diagnostic: {proc.poll()}")
            time.sleep(0.1)
        else:
            raise TimeoutError("diagnostic host timeout; no complete observation")
    except Exception as exc:
        out.update(status="FAIL", reason=str(exc))
    finally:
        if proc is not None:
            try:
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=5)
                g4.kill_our_emuhawk(lane)
                out["ownership"].update(exited=proc.poll() is not None, exit_code=proc.poll())
            except Exception as exc:
                out.update(status="FAIL", reason=f"cleanup unconfirmed: {exc}")
        try:
            verify_after(config)
            out["inputs_unchanged"] = True
        except Exception as exc:
            out.update(status="FAIL", reason=f"post-run identity verification: {exc}", inputs_unchanged=False)
        (lane / "diagnostic.json").write_text(json.dumps(out, indent=2))
    return 0 if out["status"] == "OBSERVED" else 2 if out["status"] == "OPEN" else 1

LUA = r'''
local D={}
function D.pp_delta(result,previous,current,frame)
    if not previous then return end
    result.hp_changes=result.hp_changes or {}
    for _,side in ipairs({"our","enemy"}) do
        local before,after=previous[side.."_hp"],current[side.."_hp"]
        if before and after and before~=after then
            result.hp_changes[#result.hp_changes+1]={frame=frame,battler=side,before=before,after=after,
                battle_active=current.battle_active,cause="UNMEASURED"}
        end
        local old,new=previous[side.."_pp"],current[side.."_pp"]
        if old and new and previous[side.."_species"]==current[side.."_species"] then
            for slot=1,4 do
                if new[slot]<old[slot] then
                    result.pp_deltas[#result.pp_deltas+1]={ordinal=#result.pp_deltas+1,
                        frame=frame,battler=side,slot=slot,move_id=current[side.."_moves"][slot],
                        species=current[side.."_species"],before=old[slot],after=new[slot],
                        ambiguous=old[slot]-new[slot]~=1,our_hp=current.our_hp,enemy_hp=current.enemy_hp}
                end
            end
        end
    end
end
function D.settle_trace(sites)
    local trace={samples={},epochs={},current={},sites={}}
    for _,s in ipairs(sites) do trace.sites[#trace.sites+1]=s.id end
    return trace
end
function D.settle_sample(trace,sites,resident,bytes,frame)
    for _,s in ipairs(sites) do
        local active=resident(s.overlay_id)==true
        local pin=bytes(s.address,s.extent)
        local matched=pin==s.register_hex
        local prior=trace.current[s.id]
        trace.samples[#trace.samples+1]={site=s.id,frame=frame,resident=active,
            pin=pin,pin_matches=matched}
        if active and (not prior or not prior.active) then
            local epoch={site=s.id,active_frame=frame,status=prior and "WAITING" or "LEFT_CENSORED",
                left_censored=prior==nil}
            trace.epochs[#trace.epochs+1]=epoch
            prior={epoch=epoch}
        elseif not active and prior and prior.active and prior.epoch.status=="WAITING" then
            prior.epoch.status="UNLOADED_BEFORE_PIN"
        end
        prior=prior or {}
        if active and matched and not prior.epoch.pin_frame then
            prior.epoch.pin_frame=frame
            if not prior.epoch.left_censored then
                prior.epoch.delta=frame-prior.epoch.active_frame; prior.epoch.status="SETTLED"
            end
        end
        prior.active=active; prior.pin_matches=matched; trace.current[s.id]=prior
    end
end
function D.settle_verdict(trace)
    for _,id in ipairs(trace.sites) do
        if not trace.current[id] or not trace.current[id].active or not trace.current[id].pin_matches then return "OPEN" end
        local witnessed=false
        for _,e in ipairs(trace.epochs) do
            if e.site==id and e.status=="SETTLED" then witnessed=true end
            if e.site==id and (e.status=="WAITING" or e.status=="UNLOADED_BEFORE_PIN") then return "OPEN" end
        end
        if not witnessed then return "OPEN" end
    end
    return "OBSERVED"
end
function D.fight(M,title,leg,read,step,frame)
    local result={recipes={},pp_deltas={},hp_changes={},start_frame=frame(),turn_count_available=false,
        rng={status="INCONCLUSIVE",reason="No pinned miss/critical/damage-cause witness in the pack"}}
    local previous=M.recipe_sample(title,read,leg)
    local ok,why=pcall(M.play_recipe,leg,function(buttons)
        step(buttons)
        local current=M.recipe_sample(title,read,leg)
        D.pp_delta(result,previous,current,frame()); previous=current
    end,function(p) return M.predicate(title,read,p) end,
        function() local s=M.recipe_sample(title,read,leg); s.emulator_frame=frame(); return s end,result.recipes)
    result.status=ok and "OBSERVED" or "FAIL"; result.reason=ok and "" or tostring(why)
    result.final=previous; result.final_frame=frame()
    return result
end
function D.boundary_result(state,oracle,oracle_steps,composite)
    local result={status="OPEN",reason="no closing-frame event/pending witness",state=state,oracle_frames=oracle,oracle_steps=oracle_steps,
        retained=composite:live_handles(),frame_parity={status="OPEN"}}
    if composite.failure or result.retained~=0 or state.second_drain~=0 then
        result.status="FAIL"; result.reason="boundary cleanup/composite fault: "..tostring(composite.failure); return result
    end
    for _,b in ipairs(state.close_boundaries) do
        for i,f in ipairs(b.producer_frames) do
            local observed,delivered=0,0
            for j,v in ipairs(oracle) do if v==f and oracle_steps[j]==b.producer_steps[i] then observed=observed+1 end end
            for j,v in ipairs(state.seen) do if v==f and state.seen_steps[j]==b.producer_steps[i] then delivered=delivered+1 end end
            if b.predicate_before~=true or b.predicate_after~=false or b.pending<1
                or b.producer_steps[i]~=b.fall_step_id or observed~=1 or delivered~=1 then
                result.status="FAIL"; result.reason="closing token/queue/delivery mismatch"; return result
            end
            result.status="OBSERVED"; result.reason=""; result.frame_parity={status="OBSERVED",
                callback_minus_fall=f-b.fall_frame,callback_frame=f,fall_frame=b.fall_frame,
                close_frame=b.frame,advance_token=b.fall_step_id}
        end
    end
    return result
end
if G4_DIAG_TEST then return D end
local root=assert(os.getenv("SLINK_ROOT"))
local json=dofile(root.."/lua/json_codec.lua")
local function read_json(path)
    local f=assert(io.open(path,"rb")); local v=assert(json.decode(f:read("a"))); f:close()
    local function strip(t)
        for k,x in pairs(t) do if x==json.null then t[k]=nil elseif type(x)=="table" then strip(x) end end
    end
    strip(v); return v
end
local cfg=read_json(assert(os.getenv("G4_DIAG_CONFIG")))
local title=cfg.artifact; local result={}
SLINK_GEN4_PROBE_TEST=true
local M=dofile(root.."/lua/tests/probe_gen4_hooks.lua")
SLINK_GEN4_PROBE_TEST=nil
local BUS="ARM9 System Bus"
local function read(a) return memory.read_u32_le(a,BUS)&0xFFFFFFFF end
local function bytes(a,n)
    local raw=memory.read_bytes_as_array(a,n,BUS); local t={}
    for i=1,n do t[i]=string.format("%02x",raw[i]) end; return table.concat(t)
end
local function resident(id) return M.resident(title,read,id) end
local handles={}; local monitor,composite; local callback_error
local function register(site,cb,name)
    M.validate_site(title,site,bytes,resident)
    local h=event.on_bus_exec(function(a,v,flags)
        local ok,why=pcall(cb,a,v,flags)
        if not ok then callback_error=tostring(why) end
    end,site.address,name,BUS)
    assert(M.valid_handle(h),"registration failed: "..name); handles[h]=true; return h
end
local function remove(h)
    local ok,value=pcall(event.unregisterbyid,h)
    assert(ok and value~=false,"unregister failed: "..h); handles[h]=nil; return true
end
local function step(buttons)
    if monitor then monitor.before() end
    joypad.set(buttons or {}); emu.frameadvance()
    if cfg.command=="settle" then D.settle_sample(result.settle,cfg.sites,resident,bytes,emu.framecount()) end
    if monitor then monitor.after() end
    assert(not callback_error,callback_error)
end
local function idle_field()
    local p=title.profile.probe_field
    local fs=read(title.symbols.sFieldSysPtr.address); if fs==0 then return false end
    local sub=read(fs+p.sub)
    return sub~=0 and read(fs+p.task)==0 and read(fs+p.live)~=0 and read(sub+p.launched_app)==0
        and read(sub+p.field_app)~=0 and read(sub+p.paused)==0
end
local function bridge()
    SLINK_GEN4_ROUTE_LIBRARY=true
    local driver=dofile(root.."/lua/tests/gen4_route_play.lua"); SLINK_GEN4_ROUTE_LIBRARY=nil
    result.bridge={}
    for attempt=1,12 do
        local request={id=attempt,leg="gen4_routes:battle_settled",position=driver.position(title)}
        local f=assert(io.open(cfg.bridge_request,"w")); f:write(assert(json.encode(request))); f:close()
        local reply
        for _=1,12000 do
            local input=io.open(cfg.bridge_response,"rb")
            if input then
                local value=json.decode(input:read("a")); input:close()
                if value and value.id==attempt then reply=value; break end
            end
            step({})
        end
        assert(reply,"bridge host response timeout")
        if reply.open then error({open=reply.open},0) end
        assert(not reply.error,reply.error)
        local context={route=reply.route,title=title,step=step,
            env={G4_REPO=root,G4_LANE=cfg.lane,G4_TAG="bridge-"..attempt}}
        local ok,why=pcall(driver.run,context)
        assert(not ok and type(why)=="table" and why.route_result,"native executor failed: "..tostring(why))
        local value=why.route_result
        local log=assert(io.open(cfg.lane.."/bridge-"..attempt..".log","w"))
        log:write(table.concat(value.lines or context.lines or {},"\n"),"\n"); log:close()
        result.bridge[#result.bridge+1]={status=value.status,detail=value.detail,lines=context.lines,request=request,route=reply.route}
        if value.status=="BATTLE" then return end
        assert(value.status=="RESYNC","native bridge failed: "..tostring(value.detail))
    end
    error("native bridge resync bound (12)")
end
local function run()
    if cfg.state_path then savestate.load(cfg.state_path) end
    if cfg.command=="fight" then
        local predicate
        for _,c in ipairs(title.phase_cases) do if c.name=="battle" then predicate=c.predicate end end
        assert(M.predicate(title,read,assert(predicate)),"state is not in battle")
        local initial=M.recipe_sample(title,read,cfg.recipe)
        assert(initial.enemy_hp and initial.enemy_hp>0 and initial.our_hp and initial.our_hp>0,"state is not a live settled battle")
        result=D.fight(M,title,cfg.recipe,read,step,emu.framecount); result.initial=initial
    elseif cfg.command=="settle" then
        result.settle=D.settle_trace(cfg.sites)
        result.attach_frame=emu.framecount()
        D.settle_sample(result.settle,cfg.sites,resident,bytes,emu.framecount())
        if result.attach_frame~=0 then
            result.status="OPEN"; result.reason="LEFT_CENSORED: diagnostic attached after first emulated frame"; return
        end
        result.boot=M.boot("bridge",3000,idle_field,function()
            local fs=read(title.symbols.sFieldSysPtr.address)
            return fs~=0 and read(fs+title.profile.probe_field.live)~=0
        end,step,emu.framecount)
        assert(result.boot.overworld,"native CONTINUE did not reach field")
        bridge()
        local start=emu.framecount()
        repeat
            local all=true
            for _,s in ipairs(cfg.sites) do
                if not resident(s.overlay_id) or bytes(s.address,s.extent)~=s.register_hex then all=false end
            end
            if all then break end
            step({})
        until emu.framecount()-start>=24000
        result.status=D.settle_verdict(result.settle)
        result.reason=result.status=="OPEN" and "unwitnessed/censored/unsettled site; not a measured zero or policy" or ""
    else
        local case=cfg.phase_case
        assert(M.close_boundary_required(case),"not a boundary case")
        local active=function() return M.predicate(title,read,case.predicate) end
        assert(active(),"state is not active battle_close")
        local producer=title.sites[case.producer_site]; producer.id=case.producer_site
        local state; local oracle,oracle_steps={},{}
        register(producer,function(a,v)
            if active() then
                assert(bytes(producer.address,producer.extent)==producer.register_hex,"observer pin fault")
                assert((a&0xFFFFFFFF)==producer.address and (v&0xFFFFFFFF)==cfg.producer_word,"observer site word")
                assert((emu.getregister("ARM9 r15")&0xFFFFFFFF)==producer.address+(producer.mode=="thumb" and 4 or 8),"observer PC")
                oracle[#oracle+1]=emu.framecount(); oracle_steps[#oracle_steps+1]=state.step_id
            end
        end,"g4diag.oracle")
        local binding={validate=function(s) M.validate_site(title,s,bytes,resident); return s end,
            register=register,unregister=remove,capture=function(s,a,v,flags)
                local e=M.capture(s,a,v,flags,emu.getregister("ARM9 r15"),resident)
                if e then M.validate_site(title,s,bytes,resident); e.frame=emu.framecount(); e.step_id=state.step_id end
                return e
            end}
        composite=M.composite(dofile(root.."/lua/hook_registry.lua"),binding)
        monitor,state=M.phase_monitor(composite,case.name,{producer},case.producer_site,active,
            function(wanted) if wanted then M.validate_site(title,producer,bytes,resident) end; return true end,emu.framecount)
        result.boundary_state=state; result.oracle_frames=oracle; result.oracle_steps=oracle_steps
        for _,name in ipairs({"run_from_wild","exit_battle_to_overworld"}) do
            M.play_recipe(title.route_legs[name],step,function(p) return M.predicate(title,read,p) end)
        end
        monitor.finish(); monitor=nil
        result=D.boundary_result(state,oracle,oracle_steps,composite)
    end
end
local ok,why=pcall(run)
if not ok then
    result.status=type(why)=="table" and why.open and "OPEN" or "FAIL"
    result.reason=type(why)=="table" and why.open or tostring(why)
end
if monitor then local done,err=pcall(monitor.finish); if not done then result.status="FAIL"; result.reason=tostring(err) end end
for h in pairs(handles) do local done,err=pcall(remove,h); if not done then result.status="FAIL"; result.reason=tostring(err) end end
if next(handles) then result.status="FAIL"; result.reason="retained diagnostic hooks" end
result.terminal=true; result.qualified=false; result.callback_error=callback_error
local f=assert(io.open(cfg.lane.."/observation.json","w")); f:write(assert(json.encode(result))); f:close()
pcall(client.exit)
'''


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("fight", "settle", "boundary"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--title", choices=tuple(evidence.PACKS), required=True)
        cmd.add_argument("--scenario", required=True)
        cmd.add_argument("--lane", required=True)
        cmd.add_argument("--source-cut", default=os.environ.get("G4_FROZEN"))
        cmd.add_argument("--timeout", type=int, default=600 if name == "settle" else 300)
        if name == "settle":
            cmd.add_argument("--cold-boot", action="store_true", required=True)
            cmd.add_argument("--errand", choices=["pokegear"], default="pokegear")
            cmd.add_argument("--target", choices=["battle_settled"], default="battle_settled")
            cmd.add_argument("--images", nargs="+", required=True)
        else:
            cmd.add_argument("--state", type=Path, required=True)
            cmd.add_argument("--state-sha256", required=True)
            if name == "fight":
                cmd.add_argument("--recipe", choices=["fight_until_enemy_faints"], default="fight_until_enemy_faints")
            else:
                cmd.add_argument("--phase-case", choices=["battle_close"], default="battle_close")
    return ap


def prepare(args):
    """No emulator: validate the committed inventory, then create one fresh private lane."""
    from tests.live.test_gen4_probe_gates import load_scenario
    if args.timeout <= 0:
        raise ValueError("timeout must be positive")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    assert args.source_cut == head, "explicit --source-cut/G4_FROZEN must match HEAD"
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip(), "dirty source"
    blob = subprocess.check_output(["git", "show", f"{head}:tools/gen4_diag.py"], cwd=REPO)
    assert blob.replace(b"\r\n", b"\n") == Path(__file__).read_bytes().replace(b"\r\n", b"\n"), "uncommitted driver"
    doc, save, scenario_sha = load_scenario(args.scenario, args.title, "baseline")
    profile = REPO / "data/games" / evidence.PACKS[args.title] / "profile.json"
    title = json.loads(profile.read_text())["titles"][args.title]
    rom_src = gen4_pins.default_locations().roms[args.title]
    if not rom_src.is_file():
        raise g4.RomAbsent(f"OPEN ROM absent: {rom_src}")
    assert g4.sha1_of(rom_src) == title["rom"]["sha1"] == gen4_pins.ROM_SPECS[args.title][0], "wrong ROM"
    cut = evidence.snapshot("probe", args.title)
    cut["rom_sha1"] = title["rom"]["sha1"]
    cfg = {"schema": "gen4-diagnostic-v1", "qualified": False, "command": args.command, "title": args.title,
           "source_head": head, "frozen_surface": cut, "rom_sha1": cut["rom_sha1"],
           "scenario_path": args.scenario, "scenario_sha256": scenario_sha, "scenario": doc,
           "save_sha256": sha256(save), "state_sha256": None, "artifact": title, "requested_rate": 300,
           "originals": {str(REPO / args.scenario): scenario_sha, str(save): sha256(save), str(rom_src): sha256(rom_src)}}
    if args.command != "settle":
        if not args.state.is_file():
            raise g4.RomAbsent(f"OPEN state absent: {args.state}")
        assert sha256(args.state) == args.state_sha256, "wrong state hash"
        assert args.state.read_bytes()[:4] == b"PK\x03\x04", "not a BizHawk state"
        cfg["state_sha256"] = args.state_sha256
        cfg["originals"][str(args.state)] = args.state_sha256
        if args.command == "fight":
            cfg["recipe"] = title["route_legs"][args.recipe]
        else:
            cfg["phase_case"] = next(c for c in title["phase_cases"] if c["name"] == args.phase_case)
            producer = title["sites"][cfg["phase_case"]["producer_site"]]
            # fire_hex is the formatted decoded LE u32; register_hex spells ROM bytes.
            cfg["producer_word"] = int(producer["fire_hex"], 16)
    else:
        ids = sorted({s for c in title["phase_cases"] for s in c["sites"]})
        cfg["sites"] = [{**title["sites"][i], "id": i} for i in ids if title["sites"][i]["image"] in args.images]
        assert cfg["sites"] and set(args.images) == {s["image"] for s in cfg["sites"]}, "image has no selected phase pins"
        cfg["errand"] = args.errand
    lane = g4.lane_dir(args.lane)
    lane.mkdir(parents=True, exist_ok=False)
    cfg["lane"] = lane.as_posix()
    cfg["bridge_request"], cfg["bridge_response"] = (lane / "bridge-request.json").as_posix(), (lane / "bridge-response.json").as_posix()
    rom = g4.stage_rom(rom_src, lane)
    battery = g4.stage_save(save, lane, cfg["rom_sha1"], rom_basename=rom.name)
    bizhawk = lane / "bizhawk.ini"
    g4.write_nds_run_config(g4.BIZHAWK_CONFIG, bizhawk, initial_time="2010-01-01T12:00:00",
                            lane_saveram_dir=battery.parent, saveram_name_hint=battery.name)
    lua = lane / "diagnostic.lua"
    lua.write_text(LUA, encoding="utf-8")
    if args.command != "settle":
        state = lane / "start.State"
        shutil.copyfile(args.state, state)
        cfg["state_path"] = state.as_posix()
    cfg["hashes"] = {"driver": sha256(Path(__file__)), "generated_lua": sha256(lua), "bizhawk_config": sha256(bizhawk),
                     "rom_sha256": sha256(rom), "profile": sha256(profile)}
    config = lane / "diagnostic-config.json"
    config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    # Hash outside the config to avoid a self-referential digest.
    cfg["hashes"]["diagnostic_config"] = sha256(config)
    cfg["generated_paths"] = {str(lua): sha256(lua), str(bizhawk): sha256(bizhawk), str(config): sha256(config)}
    emulator = Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe"))
    if not emulator.is_file():
        raise g4.RomAbsent(f"OPEN EmuHawk absent: {emulator}")
    command = [str(emulator), f"--config={bizhawk.as_posix()}", f"--lua={lua.as_posix()}", rom.as_posix()]
    game = {"heartgold": "HG", "soulsilver": "SS", "heartgold_hge": "hge"}[args.title]
    return cfg, lane, command, gen4_routes.BridgePlanner(rom_src, game), config


def main(argv=None):
    import pytest  # The reused committed scenario loader reports absent input with pytest.skip.
    args = parser().parse_args(argv)
    if os.environ.get("SLINK_LIVE") != "1":
        print("OPEN: SLINK_LIVE=1 plus coordinator slot grant required; no emulator started")
        return 2
    try:
        cfg, lane, command, planner, config = prepare(args)
        # Popen env uses absolute paths; do not modify the caller's global environment.
        cfg["launch_env"] = {"SLINK_ROOT": REPO.as_posix(), "G4_DIAG_CONFIG": config.as_posix()}
        verdict = collect(cfg, lane, command, planner=planner, timeout=args.timeout)
        print(lane / "diagnostic.json")
        return verdict
    except (FileNotFoundError, g4.RomAbsent, pytest.skip.Exception) as exc:
        print(f"OPEN: {exc}")
        return 2
    except (AssertionError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
