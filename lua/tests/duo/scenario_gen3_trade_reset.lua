-- RR durable native trade reset/reload. Reuses scenario_gen3_trade's real NPC/menu driver.
-- Initial phase exits CLEANLY through duo_gen3_main's normal client.exit after a named
-- partial marker: no forged trade_done, no TRADED, no runner SAVE. Reload phase boots
-- the SAME battery (runner seed=false) and waits for production after_reset evidence.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
local JSON = dofile(ROOT .. "/lua/json_codec.lua")
local Flow = dofile(ROOT .. "/lua/tests/duo/gen3_rr_reset_flow.lua")
local Witness = dofile(ROOT .. "/lua/tests/duo/gen3_rr_reset_witness.lua")
local Trade = dofile(ROOT .. "/lua/tests/duo/scenario_gen3_trade.lua")
local f = assert(io.open(ROOT .. "/data/games/gen3_rr/profile.json", "rb"))
local N = assert(JSON.decode(f:read("a")).native)
f:close()
local TRADE_BASE = assert(N.TRADE_BASE)
local SAVE_COUNTER = 0x03005390 -- RR CFRU gSaveCounter, trade_journal.lua RELOAD_LAYOUTS.firered_rr

local function bus()
    return {
        u8=function(addr) return memory.read_u8(addr, "System Bus") end,
        u16=function(addr) return memory.read_u16_le(addr, "System Bus") end,
        u32=function(addr) return memory.read_u32_le(addr, "System Bus") end,
    }
end

local function witness_file(ctx, label)
    local path, n = ctx.D.result:gsub("_result%.txt$", "_" .. label .. "_native_witness.bin")
    assert(n == 1, "phase receipt has no _result.txt suffix")
    local out = assert(io.open(path, "wb"))
    for i = 0, 0x4F do out:write(string.char(memory.read_u8(TRADE_BASE + 0x50 + i, "System Bus"))) end
    out:flush(); out:close()
    return path
end

local function partner_key(ctx)
    local file = assert(io.open(ctx.D.go_file, "r"))
    local found
    for line in file:lines() do found = line:match("^PARTNER (%S+)$") or found end
    file:close()
    return found
end

return function(ctx)
    if not ctx.rr then return false, "RR reset carrier requires the durable RR companion" end
    local domain = ctx.G.flash_domain()
    if not domain then return false, "RR flash domain unavailable" end
    local mem = bus()
    local function counter()
        local ram = mem.u32(SAVE_COUNTER)
        local flash = ctx.G.save_counter(domain)
        return ram == flash and flash or nil
    end

    if ctx.phase == "rr_reset_reload" then
        return Flow.reload(ctx, {
            counter=counter, expected_counter=ctx.D.expected_counter,
            require_after_reset=ctx.D.reset_case == "commit" and ctx.player == "a",
            token=ctx.D.expected_token,
        })
    end
    if ctx.phase ~= "initial" then return false, "unexpected RR reset phase " .. tostring(ctx.phase) end
    local old_key = ctx.linked()
    local partner = partner_key(ctx)
    local before = counter()
    if not old_key or not partner or not before or before < 0 then
        return false, "RR reset initial battery/keys unavailable"
    end

    local function apply()
        if ctx.received("apply_trade") ~= 1 then return nil end
        return ctx.rx_after(0, function(command) return command.cmd == "apply_trade" end)
    end
    local function probe()
        if ctx.sent("trade_done") > 0 then return nil end
        local command = apply()
        if not command or type(command.token) ~= "string" or command.token == "" then return nil end
        local now = mem.u32(SAVE_COUNTER)
        local report = Witness.sample(mem, TRADE_BASE, old_key, before, now)
        if not report or counter() ~= now then return nil end
        report.token, report.side, report.frame = command.token, ctx.player, emu.framecount()
        report.witness_path = witness_file(ctx, "commit")
        return report
    end
    local function success(report)
        local command = apply()
        if not command or command.token ~= report.token or report.new_key ~= partner then return nil end
        local now = mem.u32(SAVE_COUNTER)
        local proof = Witness.success(mem, TRADE_BASE, old_key, partner, before, now)
        if not proof or counter() ~= now then return nil end
        proof.token, proof.side, proof.frame = report.token, ctx.player, emu.framecount()
        proof.witness_path = witness_file(ctx, "success")
        return proof
    end
    local commit = ctx.D.reset_case == "commit"
    if not commit and ctx.D.reset_case ~= "success" then return false, "unknown RR reset case" end
    return Flow.initial(ctx, {
        trade_driver=Trade,
        interrupt=commit and ctx.player == "a",
        stop_before_manual_save=not commit or ctx.player == "b",
        probe=probe, validate_success=success,
    })
end
