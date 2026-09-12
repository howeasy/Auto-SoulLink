-- Non-linked retirement uses the existing held image/repair/file executor.
local M={}
function M.new(options)
    local writer=require("gen1_held_save_image").new(options,{
        command="acquisition_retire",intent="rby-retirement-intent-v1",delta="rby-retirement-delta-v1",
        receipt="rby-retirement-receipt-v1",save_phase="retirement_save",repair_phase="retirement_repair",
        observe="retirement_observe"})
    local receipt=writer.receipt
    writer.receipt=function(body,...)
        local value=receipt(body,...)
        if body.cmd=="retirement_observe"then value.schema="rby-retirement-observation-v1"end
        return value
    end
    return writer
end
return M
