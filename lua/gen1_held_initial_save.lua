-- Pre-starter image executor only: the owner supplies all runtime permission.
local M={}
function M.new(options)
    return require("gen1_held_save_image").new(options,{
        command="initial_save",intent="rby-initial-save-intent-v1",delta="rby-initial-save-delta-v1",
        receipt="rby-initial-save-receipt-v1",save_phase="initial_save_flush",repair_phase="initial_save_repair",
        unchanged_fields=true})
end
return M
