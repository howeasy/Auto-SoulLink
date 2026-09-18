-- A read-only Gen 1 main-thread checkpoint. This does not grant admission or
-- transaction ownership, validate a write's payload, or run cartridge code.
--
-- Two checkpoint shapes, both from the pack's write_checkpoint.json:
--   gen1-main-loop-v1          vanilla R/B/Y: `call DelayFrame` at both overworld loops,
--                              [SP] == DelayFrame+5, [SP+2] in {OverworldLoop+3, LessDelay+3}
--   gen1-main-loop-purergb-v1  pureRGB (PLAN §4 row 12, A5, Live 1): `rst _DelayFrame` at
--                              OverworldLoop only, [SP] == delay_frame_resume (halt+1),
--                              [SP+2] == overworld_return, wDelayFrameBank == 0 and the CPU's
--                              WRAM BANK register in wram_banks; the ROM anchors are the
--                              generator-sliced `expected_hex` bytes.
-- The WRAM predicates (battle/joypad/font/link/serial/Cable Club) are shared.
local M = {}
M.VERSION = "gen1-main-loop-v1"
M.VERSION_PURERGB = "gen1-main-loop-purergb-v1"

local function hex_bytes(hex)
    local out = {}
    for i = 1, #hex, 2 do out[#out + 1] = tonumber(hex:sub(i, i + 1), 16) end
    return out
end

function M.check(profile, io)
    local ok, safe, reason = pcall(function()
        local p = profile and profile.write_safe
        local pure = type(p) == "table" and p.version == M.VERSION_PURERGB
        if type(p) ~= "table" or (p.version ~= M.VERSION and not pure) then
            return false, "no verified main-loop profile"
        end
        local domains = {}
        for _, domain in pairs(io.domains()) do domains[domain] = true end
        if not domains.ROM or not domains["System Bus"] then
            return false, "ROM and System Bus domains are required"
        end
        local function byte(address, domain)
            if type(address) ~= "number" or address % 1 ~= 0 or address < 0 or address > 65535 then
                error("invalid checkpoint address")
            end
            local value = io.read_u8(address, domain or "System Bus")
            if type(value) ~= "number" or value % 1 ~= 0 or value < 0 or value > 255 then
                error("unavailable checkpoint byte")
            end
            return value
        end
        local function rom_matches(address, bytes)
            for i, value in ipairs(bytes) do
                if byte(address + i - 1, "ROM") ~= value then return false end
            end
            return true
        end
        local function instruction(opcode, target)
            return {opcode, target % 256, math.floor(target / 256)}
        end
        -- Verify on every attempt, including after reset or a ROM reload. A cached
        -- positive must never survive a changed ROM. These anchors are ROM0 only.
        if pure then
            local x = assert(p.expected_hex, "expected_hex required")
            if not rom_matches(p.irq_vector, hex_bytes(x.irq_vector))
                or not rom_matches(p.delay_frame_halt, hex_bytes(x.delay_frame_halt))
                or not rom_matches(p.delay_frame_rst, hex_bytes(x.delay_frame_rst))
                or not rom_matches(p.overworld_loop, hex_bytes(x.overworld_loop)) then
                return false, "cartridge checkpoint instructions differ"
            end
        elseif not rom_matches(p.irq_vector, instruction(0xC3, p.vblank_entry))
            or not rom_matches(p.delay_frame, {0x3E, 1, 0xE0, p.vblank_flag % 256,
                0x76, 0xF0, p.vblank_flag % 256, 0xA7})
            or not rom_matches(p.overworld_loop, instruction(0xCD, p.delay_frame))
            or not rom_matches(p.overworld_loop_less_delay, instruction(0xCD, p.delay_frame)) then
            return false, "cartridge checkpoint instructions differ"
        end
        if byte(profile.BATTLE_FLAG_ADDR) ~= 0 or byte(profile.JOY_IGNORE_ADDR) ~= 0
            or byte(profile.FONT_LOADED_ADDR) % 2 ~= 0 then
            return false, "battle, script or text owns the game"
        end
        if byte(p.link_state) ~= p.link_none or byte(p.serial_status) ~= p.disconnected_serial
            or byte(p.entering_cable_club) ~= 0 or (p.printer_open and byte(p.printer_open) ~= 0) then
            return false, "serial, Cable Club or printer owns the game"
        end
        local pc, sp = io.register("PC"), io.register("SP")
        if pc ~= p.irq_vector or type(sp) ~= "number" or sp % 1 ~= 0
            or sp < p.stack_min or sp + 3 > p.stack_end then
            return false, "CPU is outside the verified checkpoint"
        end
        -- The CPU pushes its return address little-endian. Pokemon fields use
        -- a different byte order. Read exactly two words; never scan the stack.
        local resume = byte(sp) + 256 * byte(sp + 1)
        local caller = byte(sp + 2) + 256 * byte(sp + 3)
        if pure then
            if resume ~= p.delay_frame_resume or caller ~= p.overworld_return
                or byte(p.vblank_flag) ~= 1 then
                return false, "main thread is not waiting in the overworld loop"
            end
            -- wDelayFrameBank is the ROM bank DelayFrame will restore; 0 means the overworld
            -- loop itself parked here. The WRAM bank register must map bank 1 at $Dxxx.
            local allowed = {}
            for _, b in ipairs(p.wram_banks or {}) do allowed[b] = true end
            if byte(p.delay_frame_bank) ~= 0 or not allowed[io.register("WRAM BANK")] then
                return false, "DelayFrame bank or WRAM bank outside the checkpoint"
            end
        elseif resume ~= p.delay_frame + 5
            or (caller ~= p.overworld_loop + 3 and caller ~= p.overworld_loop_less_delay + 3)
            or byte(p.vblank_flag) ~= 1 then
            return false, "main thread is not waiting in the overworld loop"
        end
        return true, "verified overworld checkpoint"
    end)
    if not ok then return false, "checkpoint evidence unavailable: " .. tostring(safe) end
    return safe, reason
end

return M
