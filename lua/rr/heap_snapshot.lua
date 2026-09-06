-- Read-only RR game-heap observations. Does not reserve memory or prove ownership.
local Heap = {}
local ROOT, SIZE = 0x03000A38, 0x03000A3C
function Heap.read(io, frame, max_blocks)
    max_blocks=max_blocks or 512
    if type(max_blocks)~="number" or max_blocks%1~=0 or max_blocks<1 or max_blocks>16384 then
        return nil,"invalid_block_budget"
    end
    local ok,result,reason=pcall(function()
        local first=frame()
        if type(first)~="number" or first%1~=0 or first<0 then return nil,"invalid_frame" end
        local root,size=io.read_u32_le(ROOT),io.read_u32_le(SIZE)
        if root%4~=0 or size%4~=0 or size<16 or root<0x02000000 or root+size>0x02040000 then
            return nil,"uninitialized_or_invalid_extent"
        end
        local finish=root+size
        local out={root=root,size=size,frame=first,free_bytes=0,largest_free=0,allocated_bytes=0,
            blocks={},header_bytes=0,capacity_proof=false,ownership_proof=false}
        local address,previous=root,root
        for _=1,max_blocks do
            if address%4~=0 or address<root or address+16>finish then return nil,"invalid_header_address" end
            local flag,magic=io.read_u16_le(address),io.read_u16_le(address+2)
            local bytes,prev,next_block=io.read_u32_le(address+4),io.read_u32_le(address+8),io.read_u32_le(address+12)
            if magic~=0xA3A3 or (flag~=0 and flag~=1) then return nil,"invalid_header" end
            if bytes%4~=0 or address+16+bytes>finish then return nil,"invalid_block_extent" end
            if prev~=previous then return nil,"invalid_previous_link" end
            local expected=address+16+bytes
            if next_block~=(expected==finish and root or expected) then return nil,"invalid_next_link" end
            out.blocks[#out.blocks+1]={address=address,size=bytes,allocated=flag==1}
            out.header_bytes=out.header_bytes+16
            if flag==0 then
                out.free_bytes=out.free_bytes+bytes;out.largest_free=math.max(out.largest_free,bytes)
            else out.allocated_bytes=out.allocated_bytes+bytes end
            if next_block==root then
                if expected~=finish then return nil,"premature_ring_end" end
                if frame()~=first or io.read_u32_le(ROOT)~=root or io.read_u32_le(SIZE)~=size then
                    return nil,"context_changed"
                end
                out.block_count=#out.blocks
                return out
            end
            previous,address=address,next_block
        end
        return nil,"block_budget_exceeded"
    end)
    if not ok then return nil,"read_failed" end
    return result,reason
end
return Heap
