-- Backward-compatible memorial policy over the generation-owned image executor.
local M={}
function M.new(options)
    return require("gen1_held_save_image").new(options,{
        command="memorialize",intent="rby-memorial-intent-v1",delta="rby-memorial-delta-v1",
        receipt="rby-memorial-receipt-v1",save_phase="memorial_save",repair_phase="memorial_repair",
        observe="memorial_observe"})
end
return M
