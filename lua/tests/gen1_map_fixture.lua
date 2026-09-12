-- Test-only source-derived map entry. CONTINUE normally reuses cached map
-- state; clear its reuse flag once so the cartridge loads the prepared map.
local M={}
function M.start(fixture,name)
    local self={loads=0}
    if not fixture then function self:close()end;return self end
    local a=fixture.ram
    local id=event.on_bus_exec(function()
        if self.loads==0 and memory.read_u8(a.wCurMap,"System Bus")==fixture.map_id then
            memory.write_u8(a.wCurMapTileset,bit.band(memory.read_u8(a.wCurMapTileset,"System Bus"),0x7f),"System Bus")
            self.loads=self.loads+1
        end
    end,fixture.rom.LoadMapHeader.address,name.."-map-fixture","System Bus")
    function self:close()event.unregisterbyid(id)end
    return self
end
return M
