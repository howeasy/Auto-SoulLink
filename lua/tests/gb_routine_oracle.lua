-- Test-only bank-qualified SM83 routine harness for an isolated cloned core.
-- Callers supply pinned symbols and scratch/stack addresses, then restore the
-- original core. This is never a production cartridge-call interface.
local M={}
function M.new(options)
    local symbols={}
    for line in io.lines(assert(options.symbols_path)) do
        local bank,address,name=line:match("^(%x+):(%x+) (%S+)$")
        if bank then symbols[name]={bank=tonumber(bank,16),address=tonumber(address,16)} end
    end
    local self={}
    function self.symbol(name)
        local symbol=assert(symbols[name],"missing source symbol "..name)
        return {bank=symbol.bank,address=symbol.address}
    end
    function self.address(name)return assert(symbols[name],"missing source symbol "..name).address end
    function self.read(address)return memory.read_u8(address,"System Bus")end
    function self.write(address,value)memory.write_u8(address,value,"System Bus")end
    function self.copy(dst,src,count)
        for i=0,count-1 do self.write(dst+i,self.read(src+i)) end
    end
    function self.invoke(name)
        local symbol=assert(symbols[name],"missing source routine "..name)
        local switch=self.address(options.bankswitch)
        local scratch,marker,stack=assert(options.scratch),assert(options.marker),assert(options.stack)
        local code={options.enable_interrupts and 0xFB or 0xF3,0x06,symbol.bank,0x21,symbol.address%256,math.floor(symbol.address/256),
            0xCD,switch%256,math.floor(switch/256),0x3E,0xA5,0xEA,marker%256,math.floor(marker/256),0x18,0xFE}
        self.write(marker,0)
        for i,byte in ipairs(code)do self.write(scratch+i-1,byte)end
        emu.setregister("SP",stack);emu.setregister("PC",scratch)
        for _=1,options.timeout_frames or 60 do
            options.step()
            for i,byte in ipairs(code)do
                assert(self.read(scratch+i-1)==byte,"oracle scratch overwritten by "..name)
            end
            if self.read(marker)==0xA5 then return end
        end
        error(name.." did not return")
    end
    return self
end
return M
