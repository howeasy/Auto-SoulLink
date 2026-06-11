-- probe_fit.lua — visual check of the client-side native-battle-text truncation: the untruncated
-- 30-char message clipped at the window edge ("…Squirtle linke|"); the fitted one must end ".."
-- inside the window. Renders the FITTED text at the action menu and screenshots.
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT   = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local MB   = dofile(WT .. "/lua/mailbox.lua")

pcall(function() client.speedmode(400) end)
pcall(savestate.load, SDIR .. "/slink_actionmenu.State"); emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")

-- same logic as gen3_frlge_client.lua fit_battle_text
local MAXC = 28
local function fit(text)
    local out = {}
    for line in (text .. "\n"):gmatch("([^\n]*)\n") do
        local fitted = line
        if #fitted > MAXC then fitted = fitted:sub(1, MAXC - 2) .. ".." end
        out[#out + 1] = fitted
    end
    return table.concat(out, "\n")
end

MB.show_battle_message(fit("Bulbasaur and Squirtle linked!"), 300, 0x0D, 5)
for _ = 1, 30 do emu.frameadvance() end
pcall(function() client.screenshot(WT .. "/patch/build/fit_truncated.png") end)
client.exit()
