-- Probe: run the PRODUCTION Gen 1 launcher path (lua/slink.lua -> lua/gen1/run.lua) inside a gate
-- harness and record what it logs (or the error it raises) for the loaded cartridge.
local ROOT = (SLINK_ROOT or os.getenv("SLINK_ROOT"))
local OUT = ROOT .. "/patch/build/probe_gen1_run_entry_result.txt"
local lines = {}
local function flush() local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end end
local orig = console.log
console.log = function(...) local p = {} for i = 1, select("#", ...) do p[i] = tostring(select(i, ...)) end; lines[#lines + 1] = table.concat(p, "\t"); flush(); orig(...) end
console.log("PROBE rom=" .. tostring(gameinfo.getromhash()) .. " sys=" .. tostring(emu.getsystemid()))
local ok, err = pcall(function() dofile(ROOT .. "/lua/gen1/run.lua") end)
console.log("RUN_LUA ok=" .. tostring(ok) .. " err=" .. tostring(err))
for _ = 1, 600 do emu.frameadvance() end
console.log("RESULT: " .. (ok and "PASS" or "FAIL") .. " probe_gen1_run_entry")
flush()
client.exit()
