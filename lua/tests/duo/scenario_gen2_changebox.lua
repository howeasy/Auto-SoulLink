--[[
  lua/tests/duo/scenario_gen2_changebox.lua -- the gen2_new `changebox` scenario (S-6 box change, W-5: the memorial
  survives SaveBox / ChangeBoxSaveGame). Gen 1 reference: changebox_new (duo_gen1_main.lua: deadzone, then CHANGE BOX
  into the memorial box and back).

  Both halves first play scenario_gen2_faint.lua unchanged up to the memorial: A's linked catch faints in battle,
  B's partner is force-fainted at the checkpoint, and both keys are memorialized into Box 14 (wCurBox 13). Then:
    A  saves natively (scenario_gen2_faint.lua's A half, identical).
    B  walks Route 29 -> Cherrygrove -> the #MON CENTER PC and CHANGEs BOX to BOX14 ("will be saved. OK?" YES:
       ChangeBoxSaveGame, SaveBox of BOX1, LoadBox of BOX14), leaves the PC and reads the active box (the memorial
       listed); a second session CHANGEs BOX back to BOX1 (SaveBox of BOX14 into its backing slot). B saves natively.

  MARKER CONTRACT (duo_gen2_main.lua prints them; JSON after the tag). Everything scenario_gen2_faint.lua lists, then
  for B only:
    ENGINE_PC {kind "box_change", site_id "change_box_loaded", old_box, new_box}   0 -> 13, then 13 -> 0
    CHANGEBOX_TO {frame, cur_box=13, box_count}      after session 1 (box_count >= 1: the memorial is listed)
    CHANGEBOX_BACK {frame, cur_box=0, box_count}     after session 2
    SAVE_WITNESS (after CHANGEBOX_BACK), RECEIPT {schema "gen2-duo-changebox-v1"}
  B sends no storage event (a box change is not a transfer).
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-changebox-v1"
S.FAINT_INPUTS = true
S.PC_INPUTS = true
S.FAINT = "lua/tests/duo/scenario_gen2_faint.lua"
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.MEMORIAL = 13          -- wCurBox of Box 14 (boxes.memorial_box)
S.SITES = {"change_box_begin", "change_box_loaded"}
S.JSON_TAGS = {ENGINE_PC=true, CHANGEBOX_TO=true, CHANGEBOX_BACK=true, SAVE_WITNESS=true, DUO_GEN2=true, CLIENT=true}

local function has(list, value)
    for _, v in ipairs(list or {}) do if v == value then return true end end
    return false
end

function S.run(h)
    local FS = dofile(h.root .. "/" .. S.FAINT)
    FS.RECEIPT_SCHEMA = S.RECEIPT_SCHEMA
    if h.player == "a" then return FS.run(h) end
    local link = dofile(h.root .. "/" .. S.LINK)
    for _, site in ipairs(S.SITES) do
        if not has(h.registered, site) then return false, "production signals lack " .. site end
    end
    local key, why = FS.link_prelude(h)
    if not key then return false, why end
    local ok, bench_why = FS.bench_half(h, key)
    if not ok then return false, bench_why end
    if not h.wait(function() return h.rec.memorial[key] ~= nil end, FS.MEMORIAL_FRAMES) then
        return false, "no memorialize ack for " .. key
    end
    if h.rec.memorial[key].event ~= "memorialize_done" then return false, "memorialize failed" end
    if not h.wait(h.box_idle, FS.MEMORIAL_FRAMES) then return false, "box commands still pending" end
    local function where(tag)
        local row = {frame=h.frame(), cur_box=h.sym("wCurBox")[1], box_count=h.box_count()}
        h.jlog(tag, row)
        return row
    end
    local went, go_why = h.pc({{op="change_box", box=S.MEMORIAL}})
    if not went then return false, "CHANGE BOX to BOX14: " .. tostring(go_why) end
    local at = where("CHANGEBOX_TO")
    if at.cur_box ~= S.MEMORIAL or at.box_count < 1 then return false, "BOX14 is not active with the memorial listed" end
    local back, back_why = h.pc({{op="change_box", box=0}})
    if not back then return false, "CHANGE BOX back to BOX1: " .. tostring(back_why) end
    if where("CHANGEBOX_BACK").cur_box ~= 0 then return false, "the current box is not BOX1" end
    local saved, save_why = h.save()
    if not saved then return false, "final save failed: " .. tostring(save_why) end
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(FS.SETTLE_FRAMES)
    local problems, receipt = FS.verdict(h.lines, h.json, link.verdict)
    local extra, detail = S.verdict(h.lines, h.json)
    for _, p in ipairs(extra) do problems[#problems + 1] = p end
    if #problems > 0 then return false, table.concat(problems, "; ") end
    receipt.changebox = detail
    h.jlog("RECEIPT", receipt)
    return true, "changed to BOX14 with the memorial listed and back to BOX1"
end

-- Pure (B's box-change half, on top of scenario_gen2_faint.lua's B verdict): lines -> problems, detail.
function S.verdict(lines, json)
    local problems, seen, tx = {}, {}, 0
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    for index, line in ipairs(lines) do
        line = tostring(line)
        local tag, body = line:match("^([%u%d_]+) (.*)$")
        if tag and S.JSON_TAGS[tag] then
            local value = json.decode(body)
            if need(type(value) == "table", "malformed " .. tag .. " marker") then
                seen[tag] = seen[tag] or {}
                table.insert(seen[tag], {at=index, value=value})
            end
        elseif tag == "TX" and (body:find('"event":"party_to_box"', 1, true) or body:find('"event":"box_to_party"', 1, true)) then
            tx = tx + 1
        end
    end
    local function rows(tag) return seen[tag] or {} end
    local client = rows("CLIENT")[1]
    for _, site in ipairs(S.SITES) do
        need(client ~= nil and has(client.value.registered_sites, site), "production signals lack " .. site)
    end
    need(tx == 0, "B sent a storage event; a box change is not a transfer")
    local changes = rows("ENGINE_PC")
    need(#changes == 2, string.format("%d ENGINE_PC markers (expected two box changes)", #changes))
    local to, back, save = rows("CHANGEBOX_TO")[1], rows("CHANGEBOX_BACK")[1], rows("SAVE_WITNESS")[1]
    need(#rows("CHANGEBOX_TO") == 1 and #rows("CHANGEBOX_BACK") == 1, "CHANGEBOX_TO/BACK must appear once each")
    local want = {{0, S.MEMORIAL}, {S.MEMORIAL, 0}}
    for i, c in ipairs(changes) do
        local v = c.value
        need(v.kind == "box_change" and v.site_id == "change_box_loaded" and want[i] ~= nil
             and v.old_box == want[i][1] and v.new_box == want[i][2], "box change " .. i .. " differs")
    end
    if to and back and changes[2] then
        need(changes[1].at < to.at and to.at < changes[2].at and changes[2].at < back.at, "box changes out of order")
        need(to.value.cur_box == S.MEMORIAL and type(to.value.box_count) == "number" and to.value.box_count >= 1,
             "BOX14 did not list the memorial")
        need(back.value.cur_box == 0, "the current box did not go back to BOX1")
        need(save ~= nil and save.at > back.at, "the final save precedes the box change back")
    end
    return problems, to and back and {to=to.value, back=back.value} or nil
end

return S
