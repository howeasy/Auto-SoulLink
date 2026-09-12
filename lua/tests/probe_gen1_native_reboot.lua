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
-- Boot witness sites (pret, per title). TryLoadSaveFile runs from MainMenu BEFORE any choice (it
-- fills the CONTINUE preview), so its entry/same-SP return proves only that SaveRAM loaded with a
-- good checksum; MainMenu.choseContinue -> MainMenu.pressedA -> SpecialEnterMap is the selected
-- CONTINUE path. All four are recorded; the overworld is then proven by walking (Lib.prove_booted).
local SITES={"TryLoadSaveFile","MainMenu.choseContinue","MainMenu.pressedA","SpecialEnterMap"}
local witness={sites={},entries={},returns={},save_file_status=nil}
local function hex(address,count,domain)
    local out={}
    for i=0,count-1 do out[#out+1]=string.format("%02X",memory.read_u8(address+i,domain or "System Bus")) end
    return table.concat(out)
end
local ok,why=pcall(function()
    local source=manifest.variant=="yellow" and "pokeyellow" or "pokered"
    local target=manifest.variant=="blue" and "pokeblue" or source
    local symbols={}
    local f=assert(io.open(ROOT.."/.cache/pret/"..source.."/"..target..".sym","r"))
    for line in f:lines() do
        local bank,addr,name=line:match("^(%x+):(%x+) (%S+)$")
        if bank then symbols[name]={bank=tonumber(bank,16),addr=tonumber(addr,16)} end
    end
    f:close()
    local status=assert(symbols.wSaveFileStatus,"wSaveFileStatus symbol")
    local bank_reg=manifest.ram.hLoadedROMBank
    for _,name in ipairs(SITES) do
        local site=assert(symbols[name],name.." symbol");witness.sites[name]=site
        local return_hooks,pending={},0
        event.on_bus_exec(function()
            local bank=memory.read_u8(bank_reg,"System Bus")
            if site.bank~=0 and bank~=site.bank then return end
            local sp=emu.getregister("SP");local ret=memory.read_u8(sp,"System Bus")+256*memory.read_u8(sp+1,"System Bus")
            witness.entries[#witness.entries+1]={site=name,frame=emu.framecount(),pc=emu.getregister("PC"),sp=sp,return_address=ret,bank=bank}
            if name=="TryLoadSaveFile" then
                pending=pending+1
                -- The return address is the shared predef trampoline; count one return per entry, at the
                -- entry SP+2, so later predefs returning through the same site are not mistaken for it.
                if not return_hooks[ret] then
                    return_hooks[ret]=event.on_bus_exec(function()
                        if pending>0 and emu.getregister("SP")==sp+2 then
                            pending=pending-1
                            witness.returns[#witness.returns+1]={site=name,frame=emu.framecount(),pc=emu.getregister("PC"),sp=emu.getregister("SP"),
                                save_file_status=memory.read_u8(status.addr,"System Bus")}
                        end
                    end,ret,"probe-return-"..name.."-"..ret,"System Bus")
                end
            end
        end,site.addr,"probe-entry-"..name,"System Bus")
    end
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
    witness.save_file_status=memory.read_u8(status.addr,"System Bus")
    local seen={};for _,e in ipairs(witness.entries) do seen[e.site]=true end
    for _,name in ipairs(SITES) do t.check("boot witness "..name,seen[name]) end
    t.check("TryLoadSaveFile returned at the same SP",#witness.returns>=1)
    publish("reboot",{
        frame=emu.framecount(),pc=emu.getregister("PC"),sp=emu.getregister("SP"),
        booted=booted,write_safe=mem.isPartyWriteSafe(),party=party or JSON.null,party_error=party_error or JSON.null,
        party_matches_expected_blob=party~=nil and party.party[1]==input.expected_party_blob_hex,
        overlay_hex=overlay,backup_hex=backup,
        save_region_hex=cart:sub(region.address*2+1,(region.address+region.length)*2),
        cart_hex=cart,wram_hex=wram,save_file_hex=table.concat(file_hex),save_file_bytes=#file,save_path=save_path,
        boot_witness=witness})
end)
t.check("reboot observation recorded",ok,tostring(why))
t.finish("native reboot probe")
