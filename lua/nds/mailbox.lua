-- Shared NDS companion mailbox reader (ABI 3 arena, host side). Pure reader: no
-- emulator API, module loading, writes, clock, or retained transaction state.
--
-- SCOPE. This module decodes the six-scalar envelope and copies raw regions. The
-- opcode/seq/status/ack_seq/reason/args/result words are RAW: opcode/args are
-- host-owned, status/ack_seq/reason are ROM-owned, and binding them -- including the
-- u16 sequence wrap (C2_BEACON_SPEC.md:416-417) -- is the binder's job. capabilities
-- is INFORMATIONAL and never a liveness or acceptance gate here; caps_shared (bits
-- 0..6) and reserved_bits (bits 7..15) are reported so a binder can act on them, and
-- the title-private bits 16..31 are left whole for the title's own adapter.
--
-- COHERENCE. The envelope is sampled before AND after the payload copy and any
-- difference is refused as mailbox:changed. That is a SOFTWARE-VISIBLE consistency
-- check, not hardware ordering: it does not establish memory ordering and does not
-- eliminate ABA (a word can change and change back between the two samples). It also
-- says nothing about the copied bytes themselves -- only the six scalars are covered,
-- which is why a request in flight is bound by seq/ack_seq and not by this reader.
-- The mailbox has no revision counter; the witness region has one and is read by
-- lua/nds/native_witness.lua instead.
--
-- DOMAIN. Deliberately domain-agnostic: `io` is injected and the binder closes it
-- over the window the ROM and the host actually share. For Gen 4 that is BizHawk's
-- "Instruction TCM" domain and NEVER the ARM9 mirror of the same bytes
-- (C2_BEACON_SPEC.md:411-415). There is no domain argument, so the module cannot
-- silently pick the wrong window.
--
-- The title-private block at SLINK_GEN4_TITLE_OFFSET (beacon.h:38-39) is a Gen 4
-- concern. This module exports that region's base only (reserved_offset) and never
-- decodes it; a per-title adapter reads it with region().
--
-- Offsets/constants below were emitted by the host-C offsetof/sizeof probe in
-- tests/unit/test_nds_mailbox.py against the committed patch/src/nds/common/abi.h.
-- That test recompiles the probe and compares EVERY entry.
local M = {}
local L = {
    arena_size=0x1000,
    mailbox_offset=0x000, mailbox_size=80,
    witness_offset=0x050, witness_size=80,
    blob_offset=0x100, blob_size=600,
    text_offset=0x360, text_size=512,
    menu_offset=0x560, menu_size=384,
    info_offset=0x6E0, info_size=288,
    control_offset=0x800, control_size=0x600,
    reserved_offset=0xE00,
    mailbox_signature=0x00, mailbox_abi_version=0x04, mailbox_opcode=0x06,
    mailbox_seq=0x08, mailbox_status=0x0A, mailbox_ack_seq=0x0C, mailbox_reason=0x0E,
    mailbox_args=0x10, mailbox_result=0x30, mailbox_capabilities=0x40,
    mailbox_session_epoch=0x44, mailbox_producer_phase=0x48, mailbox_reserved=0x4C,
    signature=0x4B4E4C53, abi=3, phase_uncertain=5,
    caps_shared=0x7F, caps_reserved=0xFF80,
}

local function uint(v, maximum)
    return type(v)=="number" and v%1==0 and v>=0 and v<=maximum
end
local function plain(t) return type(t)=="table" and getmetatable(t)==nil end
local function callable(f) return type(f)=="function" or type(f)=="userdata" end
local function copy(t)
    local out={};for k,v in pairs(t) do out[k]=v end;return out
end
function M.layout() return copy(L) end

local function bytes(raw,n)
    local out={}
    if type(raw)=="string" then
        if #raw~=n then return nil end
        for i=1,n do out[i]=raw:byte(i) end
    elseif plain(raw) then
        local count=0
        for k,v in pairs(raw) do
            if not uint(k,n) or k==0 or not uint(v,255) then return nil end
            count=count+1;out[k]=v
        end
        if count~=n then return nil end
    else return nil end
    return out
end
local function word(raw,offset,width)
    local value=0
    for i=width,1,-1 do value=value*256+raw[offset+i] end
    return value
end

-- new(io, {base=<arena base address>, abi=3, layout=<optional compiled layout>}).
-- read_bytes(address,n) -> dense 1-based byte table or binary string; alternatively
-- read_u8/read_u16/read_u32. A missing wider read is composed from the byte reader and
-- a u32 callback is never substituted for a missing u16. An explicitly supplied layout
-- must match this ABI exactly, in both directions; it is copied, never retained.
function M.new(io,config)
    if not plain(io) or not plain(config) or not uint(config.base,0xFFFFFFFF)
        or config.base+L.arena_size>0x100000000 then return nil,"config:base" end
    if config.abi~=L.abi then return nil,"abi:unsupported" end
    local layout=config.layout or L
    if not plain(layout) then return nil,"config:layout" end
    for k,v in pairs(L) do if layout[k]~=v then return nil,"config:layout" end end
    for k in pairs(layout) do if L[k]==nil then return nil,"config:layout" end end
    layout=copy(layout)
    local input={}
    for _,name in ipairs({"read_bytes","read_u8","read_u16","read_u32"}) do
        if io[name]~=nil and not callable(io[name]) then return nil,"config:reader" end
        input[name]=io[name]
    end
    if not input.read_bytes and not input.read_u8 then return nil,"config:reader" end
    local base,abi=config.base,config.abi
    local function block(address,n)
        if input.read_bytes then
            local raw=bytes(input.read_bytes(address,n),n)
            if not raw then error("invalid byte reader output") end
            return raw
        end
        local raw={}
        for i=1,n do
            local value=input.read_u8(address+i-1)
            if not uint(value,255) then error("invalid byte") end
            raw[i]=value
        end
        return raw
    end
    local function scalar(address,width)
        local fn
        if width==2 then fn=input.read_u16 else fn=input.read_u32 end
        local value
        if fn then value=fn(address) else value=word(block(address,width),0,width) end
        if width==4 and type(value)=="number" and value%1==0 and value>=-0x80000000 and value<0 then
            value=value & 0xFFFFFFFF
        end
        if not uint(value,width==2 and 0xFFFF or 0xFFFFFFFF) then error("invalid scalar") end
        return value
    end
    local function envelope()
        local env={signature=scalar(base+layout.mailbox_signature,4),
            abi_version=scalar(base+layout.mailbox_abi_version,2),
            capabilities=scalar(base+layout.mailbox_capabilities,4),
            session_epoch=scalar(base+layout.mailbox_session_epoch,4),
            phase=scalar(base+layout.mailbox_producer_phase,4),
            reserved=scalar(base+layout.mailbox_reserved,4)}
        env.caps_shared=env.capabilities & layout.caps_shared
        env.reserved_bits=env.capabilities & layout.caps_reserved
        return env
    end
    local function identified(env)
        if env.signature~=layout.signature then return nil,"mailbox:signature" end
        if env.abi_version~=abi then return nil,"abi:mismatch" end
        return env,nil
    end
    local function sampled()
        local before=envelope()
        local ok,reason=identified(before)
        if not ok then return nil,reason end
        local payload=block(base+layout.mailbox_offset,layout.mailbox_size)
        local after=envelope()
        for k,v in pairs(after) do if before[k]~=v then return nil,"mailbox:changed" end end
        if not uint(after.phase,layout.phase_uncertain) then return nil,"mailbox:phase" end
        return {abi=abi,envelope=after,bytes=payload},nil
    end
    local reader={}
    -- One envelope sample, no payload copy. No coherence claim: a caller that needs
    -- one uses snapshot().
    function reader:header()
        local ok,env,reason=pcall(envelope)
        if not ok then return nil,"read:error" end
        env,reason=identified(env)
        if not env then return nil,reason end
        if not uint(env.phase,layout.phase_uncertain) then return nil,"mailbox:phase" end
        return env,nil
    end
    -- One coherent envelope sample: the six scalars before and after the mailbox
    -- payload copy, plus a private copy of those payload bytes.
    function reader:snapshot()
        local ok,snap,reason=pcall(sampled)
        if not ok then return nil,"read:error" end
        if not snap then return nil,reason or "read:invalid" end
        return snap,nil
    end
    -- An uninterpreted in-arena copy, for a per-title adapter's private region. The
    -- shared module never decodes what a caller asks for here.
    function reader:region(offset,length)
        if not uint(offset,L.arena_size) or not uint(length,L.arena_size)
            or length==0 or offset+length>L.arena_size then return nil,"region:range" end
        local ok,payload=pcall(block,base+offset,length)
        if not ok then return nil,"read:error" end
        return payload,nil
    end
    return reader,nil
end
return M
