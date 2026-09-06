-- Validate wire shapes before a dispatcher changes a cache, queue, HUD or game.
-- Admission/operation envelopes and full Pokemon blobs have separate validators.
local M = {}
local keyed = {force_faint=true, force_explode=true, box_mon=true, party_mon=true, memorialize=true}
local text_commands = {hud_show=true, gui_prompt=true, msgbox=true}
local known = {replace_rival_team=true, play_sound=true, resolved_areas=true,
    unresolve_area=true, game_over=true, link_panel=true, rebuild_start=true, rebuild_done=true, noop=true}
for name in pairs(keyed) do known[name] = true end
for name in pairs(text_commands) do known[name] = true end

local Shape = require("command_validation")
local integer, text, array = Shape.integer, Shape.text, Shape.array

function M.validKey(key, species)
    return type(key)=="string" and #key==12 and key:sub(5,5)==":" and key:sub(10,10)==":"
        and (key:sub(1,4)..key:sub(6,9)..key:sub(11,12)):match("^[0-9A-F]+$")~=nil
        and type(species)=="table" and species[tonumber(key:sub(11,12),16)]~=nil
end

function M.validate(c, species, validate_stats)
    if type(c)~="table" or type(c.cmd)~="string" or not known[c.cmd] then
        return false,"unsupported command"
    end
    if keyed[c.cmd] and not M.validKey(c.key,species) then return false,"invalid Pokemon key" end
    if c.nickname~=nil and not text(c.nickname,128,true) then return false,"invalid nickname" end
    if c.text~=nil and not text(c.text,4096,true) then return false,"invalid text" end
    if text_commands[c.cmd] and c.text==nil then return false,"missing text" end
    for _,name in ipairs({"r","g","b"}) do
        if c[name]~=nil and not integer(c[name],0,255) then return false,"invalid color" end
    end
    if c.frames~=nil and not integer(c.frames,0,36000) then return false,"invalid display duration" end
    if c.cmd=="party_mon" and c.stats~=nil then
        local ok,reason=validate_stats(c.stats)
        if not ok then return false,reason end
    elseif c.cmd=="replace_rival_team" then
        if not array(c.blobs_hex,1,6,function(value) return text(value,132,false) and #value==132 and value:match("^%x+$") end) then
            return false,"invalid complete rival payload"
        end
    elseif c.cmd=="play_sound" and not integer(c.sound,0,65535) then
        return false,"invalid sound"
    elseif c.cmd=="resolved_areas" then
        if not array(c.areas,0,1024,function(value) return text(value,128,false) end) then return false,"invalid area list" end
    elseif c.cmd=="unresolve_area" and not text(c.area_id,128,false) then
        return false,"invalid area id"
    elseif c.cmd=="link_panel" then
        if not array(c.rows,0,512,function(value) return text(value,1024,true) end) then return false,"invalid panel rows" end
    end
    return true
end

function M.nack(c, reason, species)
    local name=type(c)=="table" and type(c.cmd)=="string" and c.cmd:sub(1,64) or "invalid"
    local events={box_mon="box_mon_failed",party_mon="sync_retrieve_failed",
        memorialize="memorialize_failed",replace_rival_team="rival_team_replaced"}
    local message={event=events[name] or "command_nack",command=name,ack="NACK",reason=reason}
    if type(c)=="table" and M.validKey(c.key,species) then message.key=c.key end
    if name=="replace_rival_team" then message.error=reason end
    return message
end

return M
