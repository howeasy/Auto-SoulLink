-- Explicit Game Boy ROM0/ROMX bus-exec binding. No title, register-name, bank-shadow
-- address or domain defaults. Shadow-bank/byte checks do not qualify a live core.
local GB = {}
local NULL_GUID = "00000000-0000-0000-0000-000000000000"
local function integer(v,low,high) return type(v)=="number" and v==math.floor(v) and v>=low and v<=high end
local function callable(v) return type(v)=="function" or type(v)=="userdata" end
local function copy(t)
    if type(t)~="table" then return t end
    assert(getmetatable(t)==nil,"plain site required")
    local out={};for k,v in pairs(t) do out[k]=copy(v) end;return out
end

local function read_bytes(io,address,expected,domain,label)
    local got=io.read_range(address,#expected,domain)
    assert(type(got)=="table" and getmetatable(got)==nil,label)
    for key,value in pairs(got) do
        assert(integer(key,1,#expected) and integer(value,0,255),label)
    end
    for i=1,#expected do assert(got[i]==expected[i],label) end
end

function GB.new(io,config)
    assert(type(io)=="table" and type(config)=="table","explicit GB io/config required")
    for _,name in ipairs({"read_u8","read_range","register","framecount","on_bus_exec","unregister"}) do
        assert(callable(io[name]),"GB io."..name.." required")
    end
    local c=copy(config)
    for _,name in ipairs({"bus_domain","rom_domain","bank_domain","pc_register","sp_register"}) do
        assert(type(c[name])=="string" and c[name]~="","explicit GB "..name.." required")
    end
    assert(integer(c.bank_address,0,65535),"explicit bank shadow address required")
    local self={}
    function self:validate(site)
        local out=copy(site)
        -- This contract observes one explicit bank-shadow byte; larger bank
        -- selectors need a separately specified binding, never truncation.
        assert(integer(out.bank,0,255) and integer(out.address,0,32767),"invalid GB bank/address")
        assert((out.address<0x4000 and out.bank==0) or (out.address>=0x4000 and out.bank>0),"GB bank/window mismatch")
        local encoded=out.expected_hex
        assert(type(encoded)=="string" and #encoded>0 and #encoded%2==0 and encoded:match("^[0-9a-fA-F]+$"),"invalid expected ROM bytes")
        out.expected={}
        for i=1,#encoded,2 do out.expected[#out.expected+1]=tonumber(encoded:sub(i,i+1),16) end
        local window_end=out.bank==0 and 0x4000 or 0x8000
        assert(out.address+#out.expected<=window_end,"ROM anchor crosses GB bank window")
        assert(integer(out.capture_offset,0,#out.expected-1),"capture PC must lie inside verified anchor")
        out.pc=out.address+out.capture_offset
        local flat=out.bank==0 and out.address or out.bank*0x4000+out.address-0x4000
        assert(out.rom_offset==flat,"GB ROM offset disagrees with bank/address")
        read_bytes(io,flat,out.expected,c.rom_domain,"engine sites differ from the ROM: "..tostring(out.id))
        return out
    end
    -- accept (optional): binder predicate run after the bank match and BEFORE the PC/byte
    -- assertions, so a hit the binder drops can never latch a PC/byte failure.
    function self:context(site,accept)
        if site.bank>0 then
            local bank=io.read_u8(c.bank_address,c.bank_domain)
            assert(integer(bank,0,255),"bank shadow unavailable")
            if bank~=site.bank then return nil end
        end
        if accept and not accept() then return nil end
        assert(io.register(c.pc_register)==site.pc,tostring(site.id)..": callback PC differs")
        read_bytes(io,site.address,site.expected,c.bus_domain,tostring(site.id)..": bank/bytes differ at fire time")
        local sp,frame=io.register(c.sp_register),io.framecount()
        assert(integer(sp,0,65535) and integer(frame,0,9007199254740991),"SP/frame unavailable")
        return {pc=site.pc,bank=site.bank,sp=sp,frame=frame}
    end
    function self:register(site,callback,name) return io.on_bus_exec(callback,site.pc,name,c.bus_domain) end
    function self:unregister(handle) return io.unregister(handle) end
    function self:valid_handle(handle)
        if integer(handle,1,9007199254740991) then return true end
        return type(handle)=="string" and handle~="" and handle:gsub("[{}]",""):lower()~=NULL_GUID
    end
    return self
end

return GB
