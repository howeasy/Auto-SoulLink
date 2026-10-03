-- R4 observation only: inspect the ACTUAL production hello retained by the duo
-- harness, never manufacture one or replace admission/ROM-content functions.
local M = {}
function M.observe(ctx)
    local hello = ctx.last_sent("hello")
    local want = (ctx.phase == "mixed_kind" or ctx.phase == "companion_partner") and "companion" or "rand"
    if not hello or hello.artifact_kind ~= want then
        return false, "randomized hello kind: wanted " .. want
    end
    if type(hello.rom_sha1) ~= "string" or #hello.rom_sha1 ~= 40 then
        return false, "hello lacks cartridge SHA-1"
    end
    if want == "rand" and (type(hello.rom_content) ~= "table"
        or type(hello.rom_content.tables) ~= "table") then
        return false, "hello lacks cartridge tables"
    end
    local json = dofile(ctx.D.wt .. "/lua/json_codec.lua")
    -- duo_gen3_main's ordinary TX hello is truncated to 200 characters. This
    -- complete marker lets PYDEC compare the bytes actually sent with the file.
    ctx.log("RAND_HELLO " .. assert(json.encode(hello)))
    ctx.log("RAND_SYNTH clean-derived fixture on randomized cartridge phase=" .. ctx.phase)
    return true
end
return M
