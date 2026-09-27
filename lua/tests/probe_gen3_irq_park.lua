-- probe_gen3_irq_park.lua — where a frame ends once an exec hook is registered (X3, expansion).
--
-- The RR precedent (docs/gen3/probes/rr_cpu_irq_bios_2026-09-24.txt): a title that idles in a BIOS
-- halt ends its frames at the System-mode park with no hook, but on the BIOS IRQ vector entry
-- (R15 0x1C, mode 0x12) once any exec hook exists -- the client always has hooks. This probe
-- measures both for the title named by SLINK_GEN3_CHECKPOINT/SLINK_GEN3_TITLE: boot the per-run
-- battery to a free field (A only, gen3_boot_check helpers), sample FRAMES frame ends with no
-- hook, then register one exec hook on the client's frame_control site and sample FRAMES more.
-- Each sample: R15, CPSR mode/T, R14 (the current mode's bank). Also dumps the BIOS bytes of the
-- halt loops so the receipt can be compared with the RR one byte for byte.
-- Logs the two tallies only (no per-frame console output).
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
G.open("probe_gen3_irq_park")
pcall(client.speedmode, 6399)
local cp, title = G.checkpoint()
G.phase("start", "title=" .. tostring(title) .. " hash=" .. tostring(gameinfo.getromhash()))

local held = 0
for i = 1, 9000 do
    local free = G.pred_ok(cp, "callback2") and G.pred_ok(cp, "field_controls_locked")
    if free then held = held + 1; joypad.set({}) else held = 0; joypad.set(i % 16 == 8 and { A = true } or {}) end
    if held >= 120 then break end
    G.advance()
end
if held < 120 then G.shot("stuck"); G.finish(false, "never reached a free field") end

local bios = {}
for a = 0x1B4, 0x20F do bios[#bios + 1] = string.format("%02x", memory.read_u8(a, "BIOS")) end
G.log("BIOS 0x1B4..0x20F " .. table.concat(bios))

local FRAMES = 600
local function tally(tag)
    local counts = {}
    for _ = 1, FRAMES do
        joypad.set({})
        G.advance()
        local k = string.format("R15=%08X mode=%02X T=%d R14=%08X", emu.getregister("R15"),
            emu.getregister("CPSR") & 0x1F, (emu.getregister("CPSR") >> 5) & 1, emu.getregister("R14"))
        counts[k] = (counts[k] or 0) + 1
    end
    local rows = {}
    for k, c in pairs(counts) do rows[#rows + 1] = { k = k, c = c } end
    table.sort(rows, function(a, b) return a.c > b.c or (a.c == b.c and a.k < b.k) end)
    for i = 1, math.min(8, #rows) do G.log(string.format("%s %s x%d", tag, rows[i].k, rows[i].c)) end
    return rows[1]
end
local nohook = tally("NOHOOK")
local hits = 0
-- the client's own per-frame exec site (engine_signals frame_control address + capture_offset),
-- passed in by the runner; the checkpoint's AgbMainLoop anchor is entered only once per boot
local anchor = tonumber(assert(os.getenv("SLINK_PROBE_HOOK"), "SLINK_PROBE_HOOK unset"), 16)
local id = event.on_bus_exec(function() hits = hits + 1 end, anchor, "SLink-irq-park", "System Bus")
local hook = tally("HOOK")
pcall(event.unregisterbyid, id)
G.finish(hits > 0, string.format("anchor=%08X hook_hits=%d nohook_modal={%s} hook_modal={%s}",
    anchor, hits, nohook.k, hook.k))
