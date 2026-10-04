--[[
  lua/tests/duo/gen2_c5_refused.lua -- the C-5 refused-at-hello duo half (docs/gen2/C5_RUNBOOK.md; G-c, G-i).

  Both halves boot a Manager-randomized companion cart (tools/c5_runner.py stages it), and the production client admits
  it locally as rand_overlay. The SERVER then decides each hello: G-c (gen2_c5_wrong_rom) admits A and refuses B,
  because B's contract names another cartridge; G-i (gen2_c5_no_contract) refuses both, because the run has no
  rom_contract.json. The refusal itself is server state, judged by the lane oracle (gen2_duo_oracles.c5_refused_oracle,
  with the exact reason text). This half proves the client side: it helloed, and a refused hello delivered no command
  (the server answers it with one {"cmd":"noop","refused":"admission"}, which duo_gen2_main never logs as RX).

  SLINK_C5_EXPECT = "admitted" | "refused" (the runner sets it per instance).
  MARKER CONTRACT: DUO_GEN2, CLIENT, BOOTED, HELLO, SERVER_VERDICT {frame, expect, hellos, rx, rx_cmds}, SAVE_WITNESS,
  RECEIPT {schema "gen2-duo-c5-refused-v1", expect, hellos, rx}; RESULT: PASS|FAIL last.
  go-file: the runner writes it once every admitted half's hello is admitted AND every refused half's is rejected.
--]]
local M = {}
M.SCHEMA = "gen2-duo-c5-refused-v1"
-- ponytail: live bounds, not measured; raise if a lane needs longer.
M.HELLO_FRAMES = 3600
M.GO_FRAMES = 54000
M.HOLD_FRAMES = 600
M.SETTLE_FRAMES = 120

function M.new()
    local S = {}
    S.JSON_TAGS = {DUO_GEN2=true, CLIENT=true, BOOTED=true, HELLO=true, SERVER_VERDICT=true, SAVE_WITNESS=true}

    function S.verdict(lines, json, expect)
        local problems, seen = {}, {}
        local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
        for _, line in ipairs(lines) do
            local tag, body = tostring(line):match("^([%u%d_]+) (.*)$")
            if tag and S.JSON_TAGS[tag] then
                local value = json.decode(body)
                if need(type(value) == "table", "malformed " .. tag .. " marker") then
                    seen[tag] = seen[tag] or {}
                    table.insert(seen[tag], value)
                end
            end
        end
        for _, tag in ipairs({"DUO_GEN2", "CLIENT", "SERVER_VERDICT", "SAVE_WITNESS"}) do
            need(seen[tag] ~= nil and #seen[tag] == 1, "expected one " .. tag .. " marker")
        end
        local client, verdict = (seen.CLIENT or {})[1] or {}, (seen.SERVER_VERDICT or {})[1] or {}
        need(client.artifact_kind == "rand_overlay" and client.production_admitted == true,
             "the production client did not admit the randomized cart as rand_overlay")
        need(seen.HELLO ~= nil and #seen.HELLO >= 1, "the client never helloed")
        need(verdict.expect == expect, "SERVER_VERDICT names another expectation")
        if expect == "refused" then
            need(verdict.rx == 0, "a refused hello delivered " .. tostring(verdict.rx) .. " command(s)")
        else
            need((verdict.rx or 0) >= 1, "an admitted hello delivered no command")
        end
        return problems, {schema=M.SCHEMA, expect=expect, hellos=verdict.hellos, rx=verdict.rx}
    end

    function S.run(h)
        local expect = os.getenv("SLINK_C5_EXPECT") or ""
        if expect ~= "admitted" and expect ~= "refused" then return false, "SLINK_C5_EXPECT must be admitted or refused" end
        h.jitter()
        local arrived, why = h.arrive()
        if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
        h.party()
        if not h.wait(function() return h.sent.hello ~= nil end, M.HELLO_FRAMES) then return false, "the client never sent hello" end
        if not h.wait(h.go, M.GO_FRAMES) then return false, "no go-file" end
        h.frames(M.HOLD_FRAMES)
        local cmds = {}
        for _, row in ipairs(h.rec.rx) do cmds[#cmds + 1] = tostring(row.cmd) end
        h.jlog("SERVER_VERDICT", {frame=h.frame(), expect=expect, hellos=#h.rec.hellos, rx=#h.rec.rx,
                                  rx_cmds=h.json.array(cmds)})
        local saved, save_why = h.save()
        if not saved then return false, "save failed: " .. tostring(save_why) end
        local witnessed, witness_why = h.witness()
        if not witnessed then return false, "save witness: " .. tostring(witness_why) end
        h.frames(M.SETTLE_FRAMES)
        local problems, receipt = S.verdict(h.lines, h.json, expect)
        if #problems > 0 then return false, table.concat(problems, "; ") end
        receipt.title, receipt.rom_sha1 = h.parts.title, h.parts.runtime_rom_sha1   -- the executed identity (jlog pins it)
        h.jlog("RECEIPT", receipt)
        return true, expect
    end
    return S
end

return M
