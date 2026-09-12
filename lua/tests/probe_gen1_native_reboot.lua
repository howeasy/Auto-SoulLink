-- Observational probe (no forward action): boot the companion cartridge from the SaveRAM an
-- emulator process was killed on mid-trade, witness the CONTINUE boot path of that boot, and
-- record what the cartridge physically looks like at the first write-safe overworld frame.
-- Input: SLINK_NATIVE_REBOOT_INPUT = {directory, player, manifest, expected_party_blob_hex}.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local JSON=require("json_codec")
local function read(path)
    local f=io.open(path,"r");if not f then return nil end
    local value=assert(JSON.decode(f:read("*a")));f:close();return value
end
local input=assert(read(os.getenv("SLINK_NATIVE_REBOOT_INPUT")))
local manifest=input.manifest
local function publish(name,value)
    local path=input.directory.."/"..name.."-"..input.player..".json"
    local f=assert(io.open(path..".tmp","w"));f:write(assert(JSON.encode(value)));f:close()
    assert(os.rename(path..".tmp",path))
end
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
-- run_gb_gate.py locates the verdict file by this literal G.start(...) call.
local t=G.start("probe_gen1_native_reboot",{no_boot=true})   -- verdict file exists from here on
local mem=t.M
-- Boot witness: lua/gen1_continue_observer.lua on the source-pinned CONTINUE sites
-- (data/games/gen1_rby/continue_sites.json): TryLoadSaveFile entry/same-SP return with
-- wSaveFileStatus 2, then MainMenu.choseContinue -> MainMenu.pressedA -> SpecialEnterMap, in order.
-- The overworld is then proven by walking (G.prove_booted).
local function hex(address,count,domain)
    local out={}
    for i=0,count-1 do out[#out+1]=string.format("%02X",memory.read_u8(address+i,domain or "System Bus")) end
    return table.concat(out)
end
local ok,why=pcall(function()
    local Sites=require("gen1_continue_sites")
    local status_address=assert(Sites.titles[manifest.variant].save_file_status)
    local observer=require("gen1_continue_observer").new({variant=manifest.variant,final_sha1=manifest.final_sha1,
        owned=function()return {context_generation=string.rep("0",32),physical_instance=string.rep("0",32)} end,
        held=function()return true end})   -- read-only probe: no admission, no writer; publication is local
    local booted=G.prove_booted(mem,"gen1_rby",t.step,t.hold)
    t.check("booted into the overworld from the killed SaveRAM",booted,"frame "..t.frame)
    for _=1,180 do if mem.isPartyWriteSafe() then break end;t.step({}) end
    local Receipts=require("gen1_command_receipts")
    local party,party_error=Receipts.party_snapshot(mem,manifest.variant)
    t.check("party readback",party~=nil,party_error)
    local region=manifest.readback.save
    local overlay=hex(manifest.foreground.overlay,16)
    local backup=hex(manifest.foreground.backup,16)
    -- Raw images go out as hex; the harness hashes them (no .NET interop from the probe).
    local cart=hex(0,0x8000,"CartRAM");local wram=hex(0xC000,0x2000)
    local save_path=os.getenv("SLINK_GATE_SAVERAM")
    local sf=assert(io.open(save_path,"rb"));local file=sf:read("*a");sf:close()
    local file_hex={};for i=1,#file do file_hex[#file_hex+1]=string.format("%02X",file:byte(i)) end
    local save_file_status=memory.read_u8(status_address,"System Bus")
    local witness=observer.peek();local state=observer.status()
    t.check("ordered CONTINUE witness (load -> loaded status 2 -> chose -> pressed -> enter)",witness~=nil,state.failed)
    observer.close()
    publish("reboot",{
        frame=emu.framecount(),pc=emu.getregister("PC"),sp=emu.getregister("SP"),
        booted=booted,write_safe=mem.isPartyWriteSafe(),party=party or JSON.null,party_error=party_error or JSON.null,
        party_matches_expected_blob=party~=nil and party.party[1]==input.expected_party_blob_hex,
        overlay_hex=overlay,backup_hex=backup,
        save_region_hex=cart:sub(region.address*2+1,(region.address+region.length)*2),
        cart_hex=cart,wram_hex=wram,save_file_hex=table.concat(file_hex),save_file_bytes=#file,save_path=save_path,
        save_file_status=save_file_status,boot_witness=witness or JSON.null,observer_status=state})
end)
t.check("reboot observation recorded",ok,tostring(why))
t.finish("native reboot probe")
