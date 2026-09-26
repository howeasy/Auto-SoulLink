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
    return FS
end

function S.run(h)
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
