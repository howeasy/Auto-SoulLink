-- Generation-neutral odd/even publication for an owned native page endpoint.
-- The binding supplies addresses, text formatting and physical ownership checks.
local M={}
function M.new(options)
    assert(type(options.page_rows)=="number" and options.page_rows%1==0 and options.page_rows>0
        and type(options.lease_frames)=="number" and options.lease_frames%1==0
        and options.lease_frames>=1 and options.lease_frames<=255,"bounded panel geometry/lease required")
    for _,name in ipairs({"read","write","available","paint"})do
        assert(type(options[name])=="function","panel binding callback required: "..name)
    end
    local r,w=options.read,options.write
    local self={generation=nil}
    function self:stage(rows)
        if not options.available() or r("state")~=1 then return false end
        assert(type(rows)=="table","panel rows required")
        local pages=math.max(1,math.ceil(#rows/options.page_rows))
        assert(pages<=255,"panel exceeds the native page-count bound")
        local page=r("page")
        assert(type(page)=="number" and page%1==0 and page>=0 and page<pages,"requested panel page is outside the payload")
        local prior=r("generation")
        assert(type(prior)=="number" and prior%1==0 and prior>=0 and prior<=255,"panel generation must be a byte")
        local odd=(prior+(prior%2==0 and 1 or 2))%256
        local even=(odd+1)%256
        w("generation",odd)
        w("transfers",0)
        w("pages",pages)
        options.paint(rows,page)
        if not options.available() or r("state")~=1 or r("page")~=page or r("generation")~=odd then
            return false -- retain odd/incomplete publication; native timeout owns closure
        end
        w("lease",options.lease_frames)
        w("generation",even)
        w("state",2)
        self.generation=even
        return true
    end
    function self:maintain(connected)
        if self.generation==nil or not options.available() or r("state")==0 then return false end
        if r("generation")~=self.generation then return false end
        w("lease",connected and options.lease_frames or 0)
        return true
    end
    return self
end
return M
