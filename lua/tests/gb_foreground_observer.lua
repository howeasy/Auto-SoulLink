-- Read-only, bank-qualified foreground observations for Game Boy gates.
-- No register writes, memory writes, frame advancement or execution authority.
local M={}
function M.new(options)
    local self={active=false,released=false,counts={},entries={},hooks={}}
    local names={"A","F","B","C","D","E","H","L","SP"}
    local function bank()return memory.read_u8(options.bank_address,"System Bus")end
    local function registers()
        local out={};for _,name in ipairs(names)do out[name]=emu.getregister(name)end
        out.bank=bank();return out
    end
    local function hook(address,fn)
        self.hooks[#self.hooks+1]=event.on_bus_exec(fn,address,options.name.."-"..#self.hooks,"System Bus")
    end
    hook(options.bridge_entry,function()
        if self.active and not self.before and emu.getregister("F")>=128 then self.before=registers()end
    end)
    for _,address in ipairs(options.return_addresses)do
        hook(address,function()
            if self.released and not self.after then self.after=registers();self.active=false end
        end)
    end
    for name,routine in pairs(options.routines)do
        hook(routine.address,function()
            if self.active and(routine.bank==0 or bank()==routine.bank)then
                self.counts[name]=(self.counts[name]or 0)+1
                if not self.entries[name]then self.entries[name]=registers()end
            end
        end)
    end
    function self:start()
        assert(not self.active,"foreground observation already active")
        self.active=true;self.released=false;self.before=nil;self.after=nil;self.counts={};self.entries={}
    end
    function self:release()self.released=true end
    function self:close()for _,id in ipairs(self.hooks)do event.unregisterbyid(id)end end
    return self
end
return M
