--[[
  lua/tests/duo/scenario_gen2_poison.lua -- the gen2_new `poison` scenario (S-4 poison half, D-7). Gen 1 reference:
  poison_new (duo_gen1_main.lua). The overworld poison leg: lua/tests/gen2_poison_inputs.lua (PI, opts.target).

  scenario_gen2_faint.lua with A's death moved from battle to the overworld. Both halves play the `link` scenario
  and save it (LINK_SAVE), then:
    A  waits for B's LINK_SAVE, travels to its title's POISON_STING source (C/S: Route 30 wild Weedle; G on
       gold_battle_errand: Bug Catcher Wade, Route 31, with the Cherrygrove heal), gets the LINKED catch poisoned
       (PI opts.target = its party slot), and walks the park tiles until DoPoisonStep faints it (the production
       binder's poison_faint event -> `faint` -> the server kills the pair, force_faint to B, memorialize to
       both). The leg stops on the park tile (never back in the grass) and A saves natively.
    B  is scenario_gen2_faint.lua's B half unchanged: idle in the overworld, so the death lands on the bench at
       the checkpoint (O-30: a B in battle would take it at the battle hold instead).
  MARKER CONTRACT: exactly scenario_gen2_faint.lua's, with A's ENGINE_FAINT {site_id "poison_faint", cause "poison"}
  and CLIENT.registered_sites holding poison_faint; RECEIPT {schema "gen2-duo-poison-v1"}.
  Opt-in G/S hardening conditions the starter after CONTINUE and before the link catch. These harness-only
  writes are SYNTH_SETUP disclosures, not engine evidence; the poison, propagation and native-save oracles
  are unchanged. The receipt records SYNTH_setup_then_normal_buttons and the actual disclosed write scopes.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-poison-v1"
S.FAINT_INPUTS = true    -- PI drives battles with FI's move/party readers
S.POISON_INPUTS = true
S.FAINT = "lua/tests/duo/scenario_gen2_faint.lua"
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.ENGINE = {site_id="poison_faint", cause="poison"}

-- scenario_gen2_faint.lua bound to the poison death
function S.faint(root)
    local FS = dofile(root .. "/" .. S.FAINT)
    FS.ENGINE, FS.RECEIPT_SCHEMA = S.ENGINE, S.RECEIPT_SCHEMA
    local verdict = FS.verdict
    function FS.verdict(lines, json, link_verdict)
        local problems, receipt = verdict(lines, json, link_verdict)
        if receipt == nil then return problems, nil end
        local hardened = false
        for _, line in ipairs(lines) do
            local body = tostring(line):match("^DUO_GEN2 (.*)$")
            if body then hardened = json.decode(body).gs_harden == true end
        end
        if not hardened then return problems, receipt end
        local disclosures = {}
        for _, line in ipairs(lines) do
            local body = tostring(line):match("^SYNTH_SETUP (.*)$")
            if body then
                local row = json.decode(body)
                local function hex(value)
                    return type(value) == "string" and #value > 0 and #value % 2 == 0 and value:match("^%x+$") ~= nil
                end
                if type(row) ~= "table" or type(row.purpose) ~= "string" or type(row.symbol) ~= "string"
                   or type(row.domain) ~= "string" or type(row.frame) ~= "number" or type(row.address) ~= "number"
                   or not hex(row.bytes_before) or not hex(row.bytes_after) or #row.bytes_before ~= #row.bytes_after then
                    problems[#problems + 1] = "incomplete SYNTH_SETUP disclosure"
                else disclosures[#disclosures + 1] = row end
            end
        end
        if #disclosures == 0 then problems[#problems + 1] = "missing SYNTH_SETUP disclosure" end
        if #problems > 0 then return problems, nil end
        receipt.gs_harden = true
        receipt.input_mode = "SYNTH_setup_then_normal_buttons"
        receipt.harness_write_scopes = json.array(disclosures)
        receipt.synth_disclosure = json.array(disclosures)
        return problems, receipt
    end
    return FS
end

function S.run(h)
    if h.gs_harden == true then
        -- Shared faint prelude owns the arrival/catch sequence for BOTH players. Override only its
        -- arrival seam here: conditioning before CONTINUE would be overwritten by loading the save.
        local original = h
        h = setmetatable({arrive=function(...)
            local arrived, why = original.arrive(...)
            if not arrived then return false, why end
            if not original.gs_setup or type(original.gs_setup.condition_starter) ~= "function" then
                return false, "G/S poison starter setup unavailable"
            end
            local conditioned, setup_why = original.gs_setup.condition_starter()
            if not conditioned then return false, "G/S poison starter setup: " .. tostring(setup_why) end
            return true
        end}, {__index=original})
    end
    local FS = S.faint(h.root)
    if h.player == "b" then return FS.run(h) end
    local link = dofile(h.root .. "/" .. S.LINK)
    for _, site in ipairs({S.ENGINE.site_id}) do
        local found = false
        for _, v in ipairs(h.registered) do found = found or v == site end
        if not found then return false, "production signals lack " .. site end
    end
    local key, why = FS.link_prelude(h)
    if not key then return false, why end
    if not FS.await_partner_link(h) then return false, "B never printed LINK_SAVE" end
    local slot = h.slot_of(key)
    if slot == nil then return false, "the linked mon left the party" end
    local ok, poison_why = h.poison({target=slot, fainted=function()
        local f = h.rec.faint_keys[key]
        return f ~= nil and f.site_id == S.ENGINE.site_id
    end})
    if not ok then return false, "poison route failed: " .. tostring(poison_why) end
    if not h.wait(function() return h.rec.faint_sent ~= nil and h.rec.faint_sent.key == key end, FS.SEND_FRAMES) then
        return false, "the client never sent faint for the poison faint"
    end
    return FS.close(h, key, function(lines, json) return FS.verdict(lines, json, link.verdict) end,
                    "poisoned to death: " .. key)
end

return S
