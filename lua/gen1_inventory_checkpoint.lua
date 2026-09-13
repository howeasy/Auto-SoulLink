-- Inventory and optional native party evidence captured under one writer hold.
-- The first returns retain the inventory/dirty-vector interface; native evidence
-- travels with its full point, never through a mutable slot or an unheld reread.
local JSON=require("json_codec")
local Observation=require("gen1_initial_observation")
local Fingerprint=require("gen1_inventory_fingerprint")
local Receipts=require("gen1_command_receipts")
local M={}
function M.new(options)
    local memory,variant=assert(options.memory),assert(options.variant)
    local holds,host=assert(options.holds),assert(options.host)
    local owned,source_owned=assert(options.owned),assert(options.source_owned)
    local frame_of=options.frame or function()return emu.framecount()end
    local self={}
    local function capture(full,previous,force,expected_frame)
        if not memory.isPartyWriteSafe()then return nil,previous,false end
        local reason=full and "full inventory checkpoint"or "inventory fingerprint checkpoint"
        assert(holds:set("writer",true,reason))
        local ok,point,fingerprint,dirty,party,frame=pcall(function()
            local frame=frame_of()
            local current,changed=previous,true
            if not full then
                source_owned()
                current=Fingerprint.capture(memory,variant)
                changed=previous~=false and(force or not previous or not Fingerprint.same(previous,current))
            end
            local point=changed and Observation.capture({owned=owned,host=host,memory=memory,variant=variant})or nil
            local party=point and options.native and Receipts.party_snapshot(memory,variant)or nil
            if not full then source_owned()end
            assert(frame_of()==frame,full and "inventory checkpoint frame changed"or "inventory fingerprint frame changed")
            return point,current,changed,party,frame
        end)
        assert(holds:set("writer",false,reason.." complete"))
        if not ok then error(point,0)end
        local native=nil
        if point and options.native then
            native=JSON.null
            if party and (expected_frame==nil or frame==expected_frame) and frame_of()==frame then
                native={schema="rby-native-observation-v1",party=party}
            end
        end
        return point,fingerprint,dirty,native
    end
    function self:inventory(frame)
        local point,_,_,native=capture(true,nil,nil,frame)
        return point,native
    end
    function self:checkpoint(previous,force,frame)return capture(false,previous,force,frame)end
    return self
end
return M
