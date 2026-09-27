"""Opt-in T2 heap diagnostic runner. Never launched by pytest collection.

python tests/unit/test_patch_arena_probe.py positive|negative|exhaustion|census
The isolated controls exercise allocation/overwrite/exhaustion. Census uses a
non-stress reservation ROM and disclosed full-party/full-box O-33 seed, observes
named native scenes, then verifies a LATER MANUAL save. It does not implement or
qualify the production save-before-DONE trade protocol or any companion feature.

Build the corresponding ROM first:
python patch/tools/build.py --target firered --arena-probe census --rom <clean-FR>
Set SLINK_ARMGCC to the existing compiler bin directory. No UPS is published.
Run/state/save/config/ROM receipts live in patch/build/arena-firered-<mode>/.
SLINK_STATE_DIR is forced there, checked before launch and guarded in Lua.

Last measured full-party census (2026-09-26): battle-party 0x185C4 used of
0x1B000; level evolution 0x147BC; trade/evolution 0x12590; full-box PC 0x10018.
These are observed managed-heap peaks, not universal upper bounds. The source
inventory of direct gHeap users and future producer allocations remains a gate.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


CENSUS_LUA = r'''
  local G = dofile(os.getenv("SLINK_ROOT") .. "/lua/tests/gen3_boot_check.lua")
  local S = dofile(os.getenv("SLINK_ROOT") .. "/lua/tests/gen3_title_syms.lua").for_title("firered")
  local cp = G.checkpoint()
  local phase, peaks = "boot", {}
  local function sample()
    if rd(0x0201B000) ~= 0x32505241 or rd(0x03000A3C) ~= 0x1B000 then return end
    local address, free, largest, seen = 0x02000000, 0, 0, {}
    repeat
      assert(not seen[address], "heap free-list cycle")
      seen[address] = true
      local size = rd(address + 4)
      assert(address >= 0x02000000 and address + 16 + size <= 0x0201B000, "heap block outside clamp")
      assert(memory.read_u16_le(address+2,"System Bus") == 0xA3A3, "heap magic")
      if memory.read_u16_le(address,"System Bus") == 0 then free=free+size; largest=math.max(largest,size) end
      address = rd(address+12)
    until address == 0x02000000
    local old = peaks[phase] or {used=0, largest=0x1B000, samples=0}
    old.used=math.max(old.used,0x1B000-free); old.largest=math.min(old.largest,largest)
    old.samples=old.samples+1; peaks[phase]=old
  end
  assert(event.on_bus_exec(sample,0x080029F8,"T2-owned-alloc-return"), "allocation hook unavailable")
  local advance = G.advance
  G.advance = function() advance(); assert(not exhausted,"native allocator assertion during scene") end
  assert(G.boot_to_field(cp,9000), "fixture did not cold-boot into field")
  local function wait_for(fn)
    for i=1,600 do if fn() then return end; G.idle(1) end
    log(string.format("CENSUS_WAIT phase=%s cb2=%X startcb=%X items=%d",phase,rd(S.GMAIN_CALLBACK2_ADDR),rd(0x020370F0),memory.read_u8(0x020370F5,"System Bus")))
    error("scene did not reach named callback: " .. phase)
  end
  local function start_action(action)
    local ready=assert(G.start_menu_witness("firered"))
    for attempt=1,5 do
      wait_for(function() return G.pred_ok(cp,"field_controls_locked") end)
      G.tap("Start",3,0)
      for frame=1,120 do if ready() then break end; G.idle(1) end
      if ready() then break end
      assert(memory.read_u8(0x0203ABE0,"System Bus")==0xFF,"menu opened but not ready")
    end
    wait_for(ready)
    local count = memory.read_u8(0x020370F5,"System Bus")
    assert(count>0 and count<=9,"start menu count")
    local target
    for i=0,count-1 do if memory.read_u8(0x020370F6+i,"System Bus")==action then target=i end end
    assert(target,"required start action absent")
    for i=1,12 do
      if memory.read_u8(0x020370F4,"System Bus")==target then break end
      G.tap("Down")
    end
    assert(memory.read_u8(0x020370F4,"System Bus")==target,"start selection")
    G.tap("A")
  end
  local function close_scene()
    for i=1,10 do
      G.tap("B");G.idle(30)
      if G.pred_ok(cp,"callback2") and G.pred_ok(cp,"field_controls_locked")
         and G.pred_ok(cp,"script_context_status")
         and memory.read_u8(0x0203ABE0,"System Bus")==0xFF then return end
    end
    error("scene failed to return to field")
  end
  phase="pokedex";start_action(0)
  wait_for(function() return rd(S.GMAIN_CALLBACK2_ADDR)==0x081024D5 end)
  G.idle(120);close_scene()
  phase="bag";start_action(2)
  wait_for(function() return rd(S.GMAIN_CALLBACK2_ADDR)==S.CB2_BAG_MENU_RUN end)
  G.idle(120);close_scene()
  phase="summary";start_action(1)
  wait_for(function() return rd(S.GMAIN_CALLBACK2_ADDR)==S.CB2_UPDATE_PARTY_MENU end)
  G.idle(60);G.tap("A");G.idle(60);G.tap("A")
  wait_for(function() return rd(S.GMAIN_CALLBACK2_ADDR)==0x08137EE9 end)
  G.idle(120);close_scene()
  phase="pc_full_boxes"
  local SP = dofile(os.getenv("SLINK_ROOT") .. "/lua/tests/gen3_scripted_play.lua")
  SP.follow(cp,"route1_edge_to_pokecenter_door","T2 census")
  SP.warp_to(cp,"Up",30,SP.DEST.center,"T2 census Center")
  SP.follow(cp,"pokecenter_entrance_to_pc","T2 census PC")
  G.tap("Up",2,13)
  assert(SP.PC.open(cp,"T2 census"),"PC did not open")
  assert(SP.PC.mode("T2 census",2),"PC move mode did not open")
  G.idle(120);close_scene()
  phase="level_evolution"
  local evolution_seen = false
  assert(event.on_bus_exec(function()
    assert(emu.getregister("R0")==S.PARTY_BASE and emu.getregister("R1")==8,"wrong evolution target")
    evolution_seen=true;log("NATIVE_EVOLUTION entry=080CDDF4 target=Wartortle")
  end,0x080CDDF4,"T2-owned-evolution"),"evolution hook registration failed")
  start_action(2)
  wait_for(function() return rd(S.GMAIN_CALLBACK2_ADDR)==S.CB2_BAG_MENU_RUN end)
  G.idle(60)
  assert(memory.read_u16_le(S.BAG_MENU_STATE_ADDR+6,"System Bus")==0,"not Items pocket")
  assert(memory.read_u16_le(S.BAG_MENU_STATE_ADDR+8,"System Bus")==0
      and memory.read_u16_le(S.BAG_MENU_STATE_ADDR+14,"System Bus")==0,"not first item")
  G.tap("A");G.idle(60);G.tap("A")
  wait_for(function() return rd(S.GMAIN_CALLBACK2_ADDR)==S.CB2_UPDATE_PARTY_MENU end)
  G.idle(60);G.tap("A")
  for frame=1,6000 do
    if evolution_seen and rd(S.GMAIN_CALLBACK2_ADDR)==S.CB2_UPDATE_PARTY_MENU then break end
    if frame%16==0 then joypad.set({A=true}) else joypad.set({}) end
    G.advance()
  end
  assert(evolution_seen,"native level evolution never entered")
  close_scene()
  phase="battle_party"
  local original = SP.PATHS.pokecenter_entrance_to_pc
  local reverse, opposite = {}, {Up="Down",Down="Up",Left="Right",Right="Left"}
  for i=#original.dirs,1,-1 do reverse[#reverse+1]=opposite[original.dirs[i]] end
  SP.PATHS.t2_pc_exit={map=original.map,from=original.to,to=original.from,dirs=reverse}
  SP.follow(cp,"t2_pc_exit","T2 battle census")
  SP.warp_to(cp,"Down",30,SP.DEST.center_exit,"T2 exit Center")
  SP.follow(cp,"pokecenter_door_to_route1_edge","T2 battle census")
  SP.warp_to(cp,"Down",30,SP.DEST.route1_north,"T2 Route1")
  SP.follow(cp,"route1_north_to_south_edge","T2 battle census")
  SP.follow(cp,"route1_south_to_grass_spot","T2 battle census")
  SP.hunt_encounter(cp,"T2 battle census",80)
  assert(SP.in_battle(cp),"no native encounter reached")
  assert(G.mash(2400,function() return rd(S.BATTLER_CTRL_ADDR)==S.HANDLE_INPUT_CHOOSE_ACTION end),"battle action menu unavailable")
  G.tap("Down")
  assert(memory.read_u8(S.ACTION_CURSOR_ADDR,"System Bus")==2,"not Pokemon action")
  G.tap("A")
  wait_for(function() return rd(S.GMAIN_CALLBACK2_ADDR)==S.CB2_UPDATE_PARTY_MENU end)
  log("NATIVE_BATTLE_PARTY_MENU entered")
  G.idle(120)
  for attempt=1,6 do
    G.tap("B");G.idle(30)
    if rd(S.GMAIN_CALLBACK2_ADDR)~=S.CB2_UPDATE_PARTY_MENU then break end
  end
  assert(G.mash(2400,function() return rd(S.BATTLER_CTRL_ADDR)==S.HANDLE_INPUT_CHOOSE_ACTION end),"battle action menu did not return")
  for i=1,4 do
    local cursor=memory.read_u8(S.ACTION_CURSOR_ADDR,"System Bus")
    if cursor==3 then break end
    G.tap(cursor<2 and "Down" or "Right")
  end
  assert(memory.read_u8(S.ACTION_CURSOR_ADDR,"System Bus")==3,"not Run action")
  G.tap("A")
  assert(G.mash(2400,function() return not SP.in_battle(cp) and G.pred_ok(cp,"callback2") end),"battle escape did not return to field")
  phase="trade_evolution"
  local trade_evo=false
  assert(event.on_bus_exec(function()
    assert(emu.getregister("R1")==68,"wrong trade evolution species")
    trade_evo=true;log("NATIVE_TRADE_EVOLUTION target=Machamp")
  end,0x080CE540,"T2-owned-trade-evolution"),"trade evolution hook unavailable")
  local file=assert(io.open(os.getenv("T2_INCOMING"),"rb"));local bytes=file:read("a");file:close()
  assert(#bytes==100,"incoming record size")
  for i=1,100 do memory.write_u8(0x0201B400+i-1,bytes:byte(i),"System Bus") end
  memory.write_u32_le(0x0201B040,1,"System Bus") -- diagnostic request, NOT protocol APPLY
  for frame=1,9000 do
    if rd(0x0201B044)==3 and G.pred_ok(cp,"field_controls_locked") then break end
    if frame%16==0 then joypad.set({A=true}) else joypad.set({}) end
    G.advance()
  end
  assert(rd(0x0201B044)==3 and trade_evo,"native scene/evolution did not complete")
  log("DIAGNOSTIC_TRADE_SCENE_RETURNED (not durable DONE)")
  phase="save"
  local domain = assert(G.flash_domain())
  local saved, before, after, reason = G.save_via_menu(cp,domain)
  assert(saved,reason);log(string.format("NATIVE_SAVE before=%d after=%d",before,after))
  for _,name in ipairs({"boot","pokedex","bag","summary","pc_full_boxes","level_evolution","battle_party","trade_evolution","save"}) do
    local p=assert(peaks[name],"no allocation evidence for "..name)
    log(string.format("PEAK scene=%s used=%X bound=1B000 min_largest_free=%X samples=%d",name,p.used,p.largest,p.samples))
    if 0x1B000-p.used <= 1024 then log("NEAR_BOUND: report before choosing reservation size") end
  end
  for i=0,15 do assert(rd(0x0201BF00+4*i)==0xC0DEC0DE,"scene canary clobbered") end
'''


def full_box_seed():
    """O-33: full boxes + level-15 Squirtle/Rare Candy; unchanged location/identity.

    FR species_info Squirtle stats and medium-slow experience; evolution.h:7
    evolves at16. Native Rare Candy/evolution run in-game, not in this helper.
    """
    from server.adapters import gen3_codec as codec

    original = (ROOT / "tests/fixtures/gen3/firered_party_town.sav").read_bytes()
    parsed = codec.parse_flash(original)
    mon = codec.party_from_save(original)[0]
    assert mon["species"] == 7
    storage = bytearray(parsed["storage"])
    for i in range(420):
        boxed = {**mon, "personality": 0x100000 + i}
        record = codec.encode_box_mon(boxed)
        offset = codec.BOX_DATA_OFFSET + i * codec.BOX_MON_SIZE
        storage[offset:offset + codec.BOX_MON_SIZE] = record
    image = bytearray(original)
    sb1 = bytearray(parsed["sb1"])
    lead = dict(mon, level=15, experience=2035)
    base_stats = {"hp":44,"attack":48,"defense":65,"speed":43,"sp_attack":50,"sp_defense":64}
    nature = mon["personality"] % 25
    for index, (name, base_stat) in enumerate(base_stats.items()):
        value = ((2*base_stat + mon["ivs"][name] + mon["evs"][name]//4)*15)//100
        if name == "hp":
            lead["hp"] = lead["max_hp"] = value + 25
        else:
            value += 5
            if nature//5 != nature%5:
                if index-1 == nature//5:
                    value = value*110//100
                elif index-1 == nature%5:
                    value = value*90//100
            lead[name] = value
    sb1[0x38:0x38+100] = codec.encode_party_mon(lead)
    # Full party stresses the native in-battle chooser, not merely two icons.
    # Additional mons are disclosed clones with distinct PIDs/species; native
    # party/evolution behaviour is still exercised by the lead only.
    rest = codec.party_from_save(original)[1]
    sb1[0x34] = 6
    for slot, species in enumerate((16,19,1,4,25),1):
        member = {**rest,"personality":0x200000+slot,"species":species}
        sb1[0x38+slot*100:0x38+(slot+1)*100] = codec.encode_party_mon(member)
    key = int.from_bytes(parsed["sb2"][0xF20:0xF24],"little") & 0xFFFF
    struct.pack_into("<HH",sb1,0x310,68,1 ^ key)
    layout = codec.slot_layout()
    for physical in range(parsed["slot"] * 14, (parsed["slot"] + 1) * 14):
        sector = parsed["sectors"][physical]
        entry = layout[sector["id"]]
        if entry["object"] in ("storage", "sb1"):
            body = storage if entry["object"] == "storage" else sb1
            chunk = body[entry["offset"]:entry["offset"] + entry["size"]]
            image[physical * 4096:(physical + 1) * 4096] = codec.write_sector(
                chunk, sector["id"], parsed["counter"], layout)
    result = bytes(image)
    assert codec.qualify_flash(result)[0]
    assert sum(bool(mon["species"]) for box in codec.boxes_from_save(result) for mon in box) == 420
    return result


def run_probe(mode, census=False):
    sys.path.insert(0, str(ROOT))
    from tools.gen1_playthrough import disable_rewind

    private_dirs = {"panel":".cache/p", "carrier":".cache/c", "sound":".cache/s"}
    base = ROOT / private_dirs[mode] if mode in private_dirs else ROOT / "patch/build" / f"arena-firered-{mode}"
    assert base.resolve().is_relative_to(ROOT.resolve())
    state_dir = (base / "states").resolve()
    if not state_dir.is_relative_to(ROOT.resolve()):
        raise ValueError(f"state directory outside owned worktree refused: {state_dir}")
    state_dir.mkdir(parents=True, exist_ok=True)
    emulator = Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe"))
    config_source = Path(os.environ.get("SLINK_BIZHAWK_CONFIG", "E:/Howard/Bizhawk/config.ini"))
    config = json.loads(config_source.read_text(encoding="utf-8-sig"))
    seeded = census or mode in ("trade", "panel", "carrier", "sound")
    seed = (ROOT / "tests/fixtures/gen3/firered_party_town.sav").read_bytes() if mode in private_dirs else (full_box_seed() if seeded else None)
    if seed:
        (base / "seed.sav").write_bytes(seed)
        print(f"seed mode={mode}; sha256={hashlib.sha256(seed).hexdigest()}", flush=True)
        from server.adapters import gen3_codec as codec
        incoming = codec.party_from_save(seed)[0]
        incoming.update(species=67, personality=0x13572468, ot_id=0x78563412,
                        nickname_raw=codec.encode_name("AAAAAAAAAA",10),
                        ot_name_raw=codec.encode_name("PEER",7), held_item=0)
        (base / "incoming.bin").write_bytes(codec.encode_party_mon(incoming))
    frontend = base / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    for entry in config["PathEntries"]["Paths"]:
        if entry["Type"] == "Firmware":
            entry["Path"] = str(config_source.parent / "Firmware")
        else:
            entry["Path"] = str(frontend / entry["System"] / entry["Type"].replace("/", "_"))
            if seeded and entry["System"] == "GBA" and entry["Type"] == "Save RAM":
                Path(entry["Path"]).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(base / "seed.sav", Path(entry["Path"]) / "probe.SaveRAM")
    disable_rewind(config)
    config["AutoLoadLastSaveSlot"] = False
    config["AutoSaveLastSaveSlot"] = False
    config_path = base / "config.ini"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    result = base / "result.txt"
    result.unlink(missing_ok=True)
    script = base / "probe.lua"
    script.write_text('''local out = assert(io.open("''' + result.as_posix() + '''", "w"))
local function log(s) out:write(s .. "\\n"); out:flush() end
local original_save = savestate.save
savestate.save = function(path)
  local prefix = assert(os.getenv("SLINK_STATE_DIR")):gsub("\\\\","/"):lower() .. "/"
  local normalized = path:gsub("\\\\","/"):lower()
  assert(normalized:sub(1,#prefix)==prefix and not normalized:find("..",1,true),
         "savestate outside owned state directory refused")
  return original_save(path)
end
local original_print = print
print = function(s) log("HELPER: " .. tostring(s)); original_print(s) end
local original_log = console.log
console.log = function(s) log("HELPER: " .. tostring(s)); original_log(s) end
local function rd(a) return memory.read_u32_le(a, "System Bus") end
client.speedmode(1000)
local ok, why = pcall(function()
  local exhausted = false
  local hook = event.on_bus_exec(function()
    local line, lr = emu.getregister("R1"), emu.getregister("R14")
    if line == 174 and lr == 0x080029F7 then
      log(string.format("EXHAUSTION_DETECTED native=081E3B14 line=%d lr=%X heap_size=%X", line, lr, rd(0x03000A3C)))
      exhausted = true
    end
  end, 0x081E3B14, "T2-arena-owned-assert")
  assert(hook, "allocator assertion hook registration failed")
  local found = false
  for frame = 1, 1800 do
    emu.frameadvance()
    if exhausted then
      assert(rd(0x0201B004) == 3 and rd(0x03000A3C) == 0x1B000, "unexpected allocator exhaustion")
      found = true
      break
    end
    if rd(0x0201B000) == 0x32505241 then
      local mode, requested, actual = rd(0x0201B004), rd(0x0201B008), rd(0x0201B00C)
      local allocated, intact = rd(0x0201B010), rd(0x0201B014)
      log(string.format("NATIVE_ALLOCATOR frame=%d mode=%d requested=%X actual=%X allocated=%d canary=%d", frame, mode, requested, actual, allocated, intact))
      assert(requested == 0x1C000, "wrong original heap size")
      if mode == 1 or mode == 4 then
        assert(actual == 0x1B000 and intact == 1, "reservation failed")
        assert(allocated == (mode==1 and 1 or 0), "wrong diagnostic allocation mode")
        if mode==1 then assert(rd(0x0201B018) + rd(0x0201B01C) <= 0x0201B000, "allocation reached reservation") end
        for tick = 1, 600 do
          emu.frameadvance()
          for i = 0, 15 do assert(rd(0x0201BF00 + 4*i) == 0xC0DEC0DE, "boot canary clobbered") end
        end
        log("BOOT_CANARY frames=600 words=16 unchanged")
      else
        assert(mode == 2 and actual == 0x1C000 and allocated == 1 and intact == 0, "negative control did not detect allocator overwrite")
      end
      found = true
      break
    end
  end
  if not found then
    log(string.format("DEBUG marker=%X hook=%X heap=%X size=%X", rd(0x0201B000), rd(0x08002B80), rd(0x03000A38), rd(0x03000A3C)))
    client.screenshot("''' + (base / "failure.png").as_posix() + '''")
  end
  assert(found, "native probe never completed")
''' + (CENSUS_LUA if census else "") + '''
end)
log("SCOPE: allocator boundary; census when requested covers only named scenes; title lifecycle unqualified")
if not ok then client.screenshot("''' + (base / "failure.png").as_posix() + '''") end
log("RESULT: " .. (ok and "PASS" or "FAIL") .. " " .. tostring(why or ""))
out:close()
client.exit()
''', encoding="utf-8")
    if mode in ("trade", "panel", "carrier", "sound"):
        from tests.unit.test_patch_carrier_live import CARRIER_LUA
        from tests.unit.test_patch_panel_live import PANEL_LUA
        from tests.unit.test_patch_sound_live import SOUND_LUA
        from tests.unit.test_patch_trade_live import TRADE_LUA

        text = script.read_text(encoding="utf-8")
        begin = text.index("  local found = false")
        end = text.index("\nend)\nlog(\"SCOPE:",begin)
        text = text[:begin] + ({"trade":TRADE_LUA,"panel":PANEL_LUA,"carrier":CARRIER_LUA,"sound":SOUND_LUA}[mode]) + text[end:]
        if mode == "panel":
            text = text.replace("SCOPE: allocator boundary; census when requested covers only named scenes; title lifecycle unqualified",
                                "SCOPE: FR native START panel; replayed payload; no server/duo/save qualification")
        if mode == "carrier":
            text = text.replace("SCOPE: allocator boundary; census when requested covers only named scenes; title lifecycle unqualified",
                                "SCOPE: FR native carrier; replayed server payload; no duo qualification")
        if mode == "sound":
            text = text.replace("SCOPE: allocator boundary; census when requested covers only named scenes; title lifecycle unqualified",
                                "SCOPE: FR sound native calls/player state; no audible-output qualification")
        script.write_text(text,encoding="utf-8")
    cmd = [str(emulator), f"--config={config_path.relative_to(ROOT).as_posix()}",
           f"--lua={script.relative_to(ROOT).as_posix()}", (base / "probe.gba").relative_to(ROOT).as_posix()]
    started = time.monotonic()
    env = {**os.environ, "SLINK_ROOT": ROOT.as_posix(), "SLINK_GEN3_TITLE": "firered",
           "SLINK_GEN3_CHECKPOINT": str(ROOT / "data/games/gen3_frlg/write_checkpoint.json"),
           "T2_INCOMING": str(base / "incoming.bin"),
           "T2_RELOAD_PARTY": str(base / "reload_party.bin"),
           "SLINK_STATE_DIR": state_dir.as_posix(),
           "SLINK_GEN3_PLAY_STATES_DIR": state_dir.as_posix()}
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"owned EmuHawk PID={proc.pid}, mode={mode}, state_dir={state_dir}", flush=True)
    (base / "run_receipt.json").write_text(json.dumps({
        "pid":proc.pid,"mode":mode,"state_dir":str(state_dir),"config":str(config_path),
        "script_sha256":hashlib.sha256(script.read_bytes()).hexdigest(),
        "rom_sha1":hashlib.sha1((base/"probe.gba").read_bytes()).hexdigest(),
        "seed_sha256":hashlib.sha256(seed).hexdigest() if seed else None,
    },indent=2)+"\n",encoding="utf-8")
    try:
        while proc.poll() is None and time.monotonic() - started < 120:
            if result.exists() and "RESULT:" in result.read_text():
                break
            time.sleep(1)
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
            proc.wait(timeout=15)
    text = result.read_text() if result.exists() else "FAIL: no result"
    print(text)
    passed = any(line.startswith("RESULT: PASS") for line in text.splitlines())
    if seeded and passed and mode not in private_dirs:
        sys.path.insert(0, str(ROOT))
        from tools.gen3_fixtures import boot_check_verdict, qualify_one

        before = qualify_one((base / "seed.sav").read_bytes(), rr=False)
        seed_counter = before["counter"]
        saved = frontend / "GBA/Save RAM/probe.SaveRAM"
        after = qualify_one(saved.read_bytes(), rr=False)
        # Named native trade receipt after the earlier level-up evolution.
        fail_save = mode=="trade" and os.environ.get("T2_FAIL_POST_SAVE")=="1"
        if not fail_save:
            before["party"][0] = {**before["party"][0], "species": 68, "level": 15,
                                  "key": "13572468:78563412"}
        if mode == "trade" and not fail_save:
            # Native PREPARE and post-trade save, never a manual third save.
            before["counter"] += 1
        passed, problems = boot_check_verdict(before, after)
        if mode == "trade":
            raw = (base/"reload_party.bin").read_bytes()
            decoded = codec.decode_party_mon(raw[:100])
            original=codec.party_from_save((base/"seed.sav").read_bytes())[0]
            wanted=(original["species"],original["personality"],original["ot_id"]) if fail_save else (68,0x13572468,0x78563412)
            if (decoded["species"],decoded["personality"],decoded["ot_id"]) != wanted:
                problems.append("post-reset RAM decode differs from expected received evolution")
                passed=False
        (base / "census_receipt.json").write_text(json.dumps({
            "scope": "private FR native trade producer probe; title qualification OPEN" if mode=="trade"
                     else "FR listed diagnostic scenes only; production trade lifecycle remains OPEN",
            "before_counter": seed_counter, "after_counter": after["counter"],
            "pydec_pass": passed, "problems": problems, "native_output": text,
            "state_dir": str(state_dir),
        }, indent=2) + "\n", encoding="utf-8")
        print(f"PYDEC save/party verification: {passed}, problems={problems}")
        if mode == "trade":
            archive = base / "runs" / ("post-save-failure" if fail_save else "success")
            archive.mkdir(parents=True,exist_ok=True)
            for name in ("receipt.json","run_receipt.json","census_receipt.json","result.txt",
                         "reload_party.bin","seed.sav","incoming.bin","probe.lua","config.ini"):
                shutil.copyfile(base/name,archive/name)
            shutil.copyfile(saved,archive/"native.SaveRAM")
        if not passed:
            return 1
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("positive", "negative", "exhaustion", "census"))
    parser.add_argument("--census", action="store_true", help="cold-boot fixture; Pokedex/bag/summary/save heap sample")
    args = parser.parse_args()
    if args.census and args.mode != "census":
        parser.error("--census requires non-stress census ROM, never allocator-control ROM")
    raise SystemExit(run_probe(args.mode, args.census or args.mode == "census"))
