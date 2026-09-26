-- Gen 1 state/ownership policy over the shared GB checkpoint evaluator.
-- No admission, write permit, transaction ownership or cartridge execution occurs here.
local M = {}
M.VERSION = "gen1-main-loop-v1"
M.VERSION_PURERGB = "gen1-main-loop-purergb-v1"

-- Existing standalone gate scripts retain check(profile, io). Production Entry
-- injects this same shared dependency through new(); there is no private evaluator.
local module_dir = debug.getinfo(1, "S").source:match("^@(.+[/\\])[^/\\]+$")
local legacy_evaluator
local function shared()
    if not legacy_evaluator then legacy_evaluator = dofile(assert(module_dir) .. "gb_checkpoint.lua") end
    return legacy_evaluator
end
local function instruction(opcode, target)
    return string.format("%02X%02X%02X", opcode, target % 256, math.floor(target / 256))
end
local function check(profile, io, evaluator)
    local ok, safe, reason = pcall(function()
        local p = profile and profile.write_safe
        local pure = type(p) == "table" and p.version == M.VERSION_PURERGB
        if type(p) ~= "table" or (p.version ~= M.VERSION and not pure) then
            return false, "no verified main-loop profile"
        end
        local anchors = {}
        local function anchor(address, hex)
            anchors[#anchors + 1] = {domain = "ROM", address = address, expected_hex = hex}
        end
        if pure then
            local x = assert(p.expected_hex, "expected_hex required")
            anchor(p.irq_vector, x.irq_vector)
            anchor(p.delay_frame_halt, x.delay_frame_halt)
            anchor(p.delay_frame_rst, x.delay_frame_rst)
            anchor(p.overworld_loop, x.overworld_loop)
        else
            anchor(p.irq_vector, instruction(0xC3, p.vblank_entry))
            anchor(p.delay_frame, string.format("3E01E0%02X76F0%02XA7", p.vblank_flag % 256, p.vblank_flag % 256))
            anchor(p.overworld_loop, instruction(0xCD, p.delay_frame))
            anchor(p.overworld_loop_less_delay, instruction(0xCD, p.delay_frame))
        end
        local spec = {
            domains = {ROM = {first = 0, limit = 0x4000}, ["System Bus"] = {first = 0, limit = 0x10000}},
            anchors = anchors, pc = p.irq_vector,
            stack = {domain = "System Bus", minimum_sp = p.stack_min, exclusive_end = p.stack_end + 1,
                read_bytes = 4, words = {
                    {offset = 0, values = {pure and p.delay_frame_resume or p.delay_frame + 5}},
                    {offset = 2, values = pure and {p.overworld_return}
                        or {p.overworld_loop + 3, p.overworld_loop_less_delay + 3}},
                }},
        }
        local accepted, why = evaluator.check(spec, io, function(read, register)
            local function byte(address) return read(address, "System Bus") end
            if byte(profile.BATTLE_FLAG_ADDR) ~= 0 or byte(profile.JOY_IGNORE_ADDR) ~= 0
                or byte(profile.FONT_LOADED_ADDR) % 2 ~= 0 then
                return false, "battle, script or text owns the game"
            end
            if byte(p.link_state) ~= p.link_none or byte(p.serial_status) ~= p.disconnected_serial
                or byte(p.entering_cable_club) ~= 0 or (p.printer_open and byte(p.printer_open) ~= 0) then
                return false, "serial, Cable Club or printer owns the game"
            end
            if byte(p.vblank_flag) ~= 1 then return false, "main thread is not waiting in the overworld loop" end
            if pure then
                local allowed = {}
                for _, bank in ipairs(p.wram_banks or {}) do allowed[bank] = true end
                if byte(p.delay_frame_bank) ~= 0 or not allowed[register("WRAM BANK")] then
                    return false, "DelayFrame bank or WRAM bank outside the checkpoint"
                end
            end
            return true
        end)
        if why == "main-thread caller or resume differs" then why = "main thread is not waiting in the overworld loop" end
        if accepted then return true, "verified overworld checkpoint" end
        return false, why
    end)
    if not ok then return false, "checkpoint evidence unavailable: " .. tostring(safe) end
    return safe, reason
end
function M.new(evaluator)
    assert(type(evaluator) == "table" and type(evaluator.check) == "function", "shared GB evaluator required")
    return {check = function(profile, io) return check(profile, io, evaluator) end}
end
function M.check(profile, io)
    local ok, evaluator = pcall(shared)
    if not ok then return false, "checkpoint evidence unavailable: " .. tostring(evaluator) end
    return check(profile, io, evaluator)
end
return M
