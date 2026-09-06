-- Explicitly selected RR4.1 readback binding. This does not admit a cartridge,
-- attest a loader, execute native code, or select the legacy client's runtime.
-- All dependencies are local trusted loader/host services, never wire payloads.
local Oracle = require("rr.withdrawal_oracle")
local Evidence = {}
local BASE = "679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f"
local REGIONS = {
    {name="builder",address=0x090B6924,size=208,sha256="a4f4c177a2085ccbf4f5aa0be343c4ee90ff6a190b5298fec9cbceae6788fcdf"},
    {name="entry",address=0x090B6A24,size=32,sha256="c828577b3991ca575b08189acbf098600404d1628b31ccc1aaa5806459b9c323"},
    {name="box_to_party",address=0x0803E774,size=188,sha256="d1d1c44acecb72bcf0241ff8755ab2b47251fcb0461ce77727bbb59746743954"},
    {name="stats",address=0x090788FC,size=844,sha256="3b301db4b56c5b93ed5eaef4159a0849c6be96e9dc5d1c1adf022c0d7d3f3732"},
    {name="pp",address=0x0804101C,size=72,sha256="ae8eda5db489bb8faa3d796f3172d291b97405ace81a70470002094eca8b54a0"},
    {name="nature_id",address=0x08042E9C,size=24,sha256="a95d66897b90ef10d1915a765ac38faa9def936e70da45b1d4f6b682d09fb76c"},
    {name="nature_math",address=0x08043698,size=96,sha256="e762b53eb37d8c914c5bc15b7c4c871e02219459fa97880fe52971a1e4928c67"},
    {name="frontier",address=0x0909AC9A,size=146,sha256="16c6be4a69348590be191dfa13d784f0eed97f88c400ecf14f9b5bad9b9d8ccd"},
    {name="accessors",address=0x0803FD44,size=1592,sha256="2846e95c5c21a32630afbf1b3a0dfd65d162b0be8882a1199d6b0339b0e3c340"},
    {name="stat_detour",address=0x0803E47C,size=8,sha256="1e8d1f9955945cf4238a174f4296bbaeef821c4bba438b9196dc366b928cfdf6"},
    {name="flags",address=0x090B8FB0,size=68,sha256="f1d0380ec303200f9ea7a61cf49b682a6b0f648efedcc918f7f12666512cfb4e"},
    {name="base_stats",address=0x097B98EC,size=38528,sha256="4161cb98162059a0e3a2b3a2057fdc7808be5cc96c5e217a7e4a53f771358a90"},
    {name="experience",address=0x0915514C,size=6144,sha256="290cf4597a284b268b9f1f3cb6250d044d54ebbf51390a5f43e3f1c5419452c5"},
    {name="moves",address=0x091521D0,size=12288,sha256="5c61c37a0567ccf73990b1bfb47dc0b2b0b1fe3ddc18821d3894c22fd159508c"},
    {name="natures",address=0x08252B48,size=125,sha256="1c7d07b7ce4be855b42c3dd74c42d7a2ab7acc22fac4c43837e4d0fd32afcb0c"},
}
local function hash(value,length)
    return type(value)=="string" and #value==length and value:match("^[0-9a-f]+$")~=nil
        and value~=string.rep("0",length)
end
local function same(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~="table" then return a==b end
    for key,value in pairs(a) do if not same(value,b[key]) then return false end end
    for key in pairs(b) do if a[key]==nil then return false end end
    return true
end
local function hex(raw)
    return (raw:gsub(".",function(byte) return string.format("%02x",byte:byte()) end))
end
local function unhex(value)
    assert(type(value)=="string" and #value==116 and value:match("^[0-9A-Fa-f]+$"),"invalid source58 evidence")
    return (value:gsub("..",function(pair) return string.char(tonumber(pair,16)) end))
end

-- revision comes from the locally validated immutable native manifest. Its
-- whole-ROM fingerprints are mandatory; matching the regions below alone is
-- not cartridge admission. io.verified_binding() must consult current local
-- admission/recovery state and return nil when its execution epoch is revoked.
function Evidence.new(io, revision)
    local ok,result=pcall(function()
        assert(type(io)=="table" and type(revision)=="table","withdrawal binding inputs required")
        for _,name in ipairs({"read_region","read_u8","sha256","getromhash","verified_binding"}) do
            assert(type(io[name])=="function","withdrawal host service unavailable: "..name)
        end
        assert(revision.base_rom_sha256==BASE and revision.abi==2,"unsupported withdrawal revision")
        local expected={}
        for _,name in ipairs({"rom_sha1","rom_sha256","build_id","layout_sha256"}) do
            assert(hash(revision[name],name=="rom_sha1" and 40 or 64),"missing withdrawal revision "..name)
            expected[name]=revision[name]
        end
        -- Copy all selected fields. Mutating the caller's manifest cannot retarget
        -- an already constructed participant.
        local function binding()
            local current=io.verified_binding()
            assert(type(current)=="table","withdrawal admission/recovery binding revoked")
            local out={}
            for name,value in pairs(expected) do
                assert(current[name]==value,"withdrawal local binding changed: "..name)
                out[name]=value
            end
            local loaded=io.getromhash()
            assert(type(loaded)=="string" and loaded:lower():gsub("^sha1:","")==expected.rom_sha1,
                "loaded withdrawal ROM changed")
            -- Same opaque host generation used by MB.set_context_generation;
            -- this is not a native wire sequence or a new numeric epoch counter.
            assert(hash(current.binding_digest,64) and type(current.context_generation)=="string"
                and #current.context_generation>=1 and #current.context_generation<=128,
                "unverified withdrawal context generation")
            out.binding_digest=current.binding_digest;out.context_generation=current.context_generation
            return out
        end
        local selected=binding()
        local tables={}
        for _,region in ipairs(REGIONS) do
            local raw=io.read_region(region.address,region.size)
            assert(type(raw)=="string" and #raw==region.size and io.sha256(raw)==region.sha256,
                "withdrawal ROM region mismatch: "..region.name)
            tables[region.name]=raw
        end
        assert(same(binding(),selected),"withdrawal binding changed during ROM evidence read")
        local function byte(address)
            local value=io.read_u8(address)
            assert(type(value)=="number" and value%1==0 and value>=0 and value<=255,
                "unreadable withdrawal mode flag")
            return value
        end
        local function context()
            local out=binding()
            -- Actual RR expanded flags, including frontier even in idle field.
            local difficulty=byte(0x0203B25A)
            assert((difficulty&0x18)==0 and (byte(0x0203B25B)&0x10)==0,"withdrawal requires Default Mode")
            assert((byte(0x0203B17C)&7)==0 and (byte(0x0203B17B)&4)==0,"withdrawal randomizer rejected")
            out.mode="default";out.minimal_grinding=(difficulty&4)~=0
            out.frontier_active=(byte(0x0203B17A)&1)~=0
            assert(not out.frontier_active,"frontier withdrawal context is not modeled")
            assert(same(binding(),selected),"withdrawal context epoch changed; rebuild binding")
            return out
        end
        local function derive(source_hex)
            local before=context()
            local raw=unhex(source_hex)
            local species=raw:byte(29)|(raw:byte(30)<<8)
            assert(species>=1 and species<=1375,"withdrawal species outside ROM domain")
            local base=tables.base_stats:sub(species*28+1,(species+1)*28)
            local growth=base:byte(20)
            assert(growth<=5,"withdrawal growth row outside ROM domain")
            local packed=0
            for index=0,4 do packed=packed|(raw:byte(0x28+index)<<(index*8)) end
            local pp={}
            for index=0,3 do
                local move=(packed>>(index*10))&1023
                pp[move]=tables.moves:byte(move*12+5)
            end
            local derived,reason=Oracle.derive(raw,{species_id=species,growth_rate=growth,base_stats=base,
                experience=tables.experience:sub(growth*1024+1,(growth+1)*1024),
                nature=tables.natures,move_pp=pp},before)
            assert(derived,reason)
            -- The engine can build level0/>100 bytes. They are not admitted as
            -- campaign withdrawal results, and must never be silently clamped.
            assert(derived.level>=1 and derived.level<=100,"withdrawal level outside campaign domain")
            assert(same(context(),before),"withdrawal mode or binding changed during preparation")
            local source_hash,party_hash=io.sha256(raw),io.sha256(derived.party_bytes)
            assert(hash(source_hash,64) and hash(party_hash,64),"withdrawal hash service failed")
            assert(same(context(),before),"withdrawal context changed while hashing evidence")
            return {schema="rr41-withdrawal-evidence-v1",source_sha256=source_hash,
                party_sha256=party_hash,expected_party=hex(derived.party_bytes),context=before}
        end
        local self={}
        function self.prepare(source_hex)
            local prepared,value=pcall(derive,source_hex)
            if not prepared then return nil,tostring(value) end
            return value
        end
        function self.verify(proof,source_hex)
            -- Re-derive from the persisted PRE-source and pinned immutable tables,
            -- never from the now-empty box or a mutated post-effect party slot.
            local prepared,value=pcall(derive,source_hex)
            if not prepared then return false,tostring(value) end
            if not same(proof,value) then return false,"withdrawal evidence/context differs from preparation" end
            return true
        end
        function self.check_context(proof)
            -- Cheap final readback boundary: no hashing or re-derivation. Local
            -- raw readers/binding services must be serialized and non-yielding.
            local checked,value=pcall(context)
            if not checked then return false,tostring(value) end
            if type(proof)~="table" or not same(proof.context,value) then
                return false,"withdrawal context changed during physical readback"
            end
            return true
        end
        return self
    end)
    if not ok then return nil,tostring(result) end
    return result
end
return Evidence
