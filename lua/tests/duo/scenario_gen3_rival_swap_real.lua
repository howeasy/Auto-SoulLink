-- scenario_gen3_rival_swap_real.lua — rival_swap_real_gen3 (RR only, card G5-RR-RIVAL).
--
-- The QUALIFYING Rival Team Swap row (owner ruling 25): a REAL rival battle, the server's own
-- auto-queued replace_rival_team (--rival-team-swap), the native OP_RIVAL_SWAP, and the enemy
-- party read back. A boots rr_rival.sav (CACHED-NATIVE: lua/tests/gen3_rr_battle_fixture.lua
-- `rival` leg, standing on Route 22 (34,6), VAR_MAP_SCENE_ROUTE22 == 1) and takes ONE step Left
-- onto the early-rival coord event (33,6) -- RR's 0x081682AB -> trainerbattle 9, gTrainers
-- 0x149..0x14B by VAR_STARTER_MON. Only normal inputs: Left, then A for the script's text, B in
-- the battle intro. B idles; its party (rr_battle2_b.sav) is what the server stages.
--
-- Receipt lines the oracle (tools/e2e_duo.py assert_rival_swap_real_gen3_saved) reads:
--   RIVAL_PRE map=G.N at=(x,y) var4054=v
--   RIVAL_CMD trainer_id=.. n=.. session=.. battle_id=.. source=..   + RIVAL_BLOB <i> <hex>
--   RIVAL_T <frame> <field>=<value>       transitions only (battle main func, comm0, opponent,
--                                          in_battle, the announcement/command/reply counts)
--   ENEMY_COUNT <n> / ENEMY_SLOT <i> <hex> / BATTLE_MON1 species=.. pid=.. / TRAINER_OPPONENT_A <id>
local RIVAL_STEP = { 3, 41, 34, 6 }
local VAR_ROUTE22 = 0x4054
local BATTLE_MAIN_FUNC = 0x03004F84     -- rival_swap_refresh_window.md §8 witness
local BATTLE_COMM0 = 0x02023E82         -- ram.BATTLE_COMM_ADDR

return function(ctx)
    local fmt = ctx.fmt
    if ctx.player == "b" then
        if not ctx.wait_go(nil, 300) then return false, "no go-file" end
        if not ctx.wait_until(ctx.partner_done, 900, "A's result") then return false, "A never finished" end
        return true, "idle (B's party is the swap source)"
    end

    local JSON = dofile(ctx.D.wt .. "/lua/json_codec.lua")
    local pf = assert(io.open(ctx.D.wt .. "/data/games/gen3_rr/profile.json", "rb"))
    local ram = assert(JSON.decode(pf:read("a"))).titles.radical_red.ram
    pf:close()
    local u8 = function(a) return memory.read_u8(a, "System Bus") end
    local u16 = function(a) return memory.read_u16_le(a, "System Bus") end
    local u32 = function(a) return memory.read_u32_le(a, "System Bus") end
    local function hex(addr, n)
        local t = {}
        for i = 0, n - 1 do t[#t + 1] = string.format("%02X", u8(addr + i)) end
        return table.concat(t)
    end

    if not ctx.wait_go() then return false, "no go-file" end
    local g, n = ctx.G.map(ctx.cp)
    local x, y = ctx.G.pos(ctx.cp)
    local var = ctx.game_var(VAR_ROUTE22)
    ctx.log(fmt("RIVAL_PRE map=%d.%d at=(%d,%d) var4054=%s", g, n, x, y, tostring(var)))
    if g ~= RIVAL_STEP[1] or n ~= RIVAL_STEP[2] or x ~= RIVAL_STEP[3] or y ~= RIVAL_STEP[4] or var ~= 1 then
        return false, "not at Route 22 (34,6) with VAR_MAP_SCENE_ROUTE22 == 1 (fixture rr_rival.sav)"
    end

    -- the command as it reached the client (the harness's own RX line names only the cmd)
    local session, inner = ctx.session, ctx.session.handle_command
    session.handle_command = function(self, cmd)
        if type(cmd) == "table" and cmd.cmd == "replace_rival_team" then
            ctx.log(fmt("RIVAL_CMD trainer_id=%s n=%s session=%s battle_id=%s source=%s frame=%d",
                        tostring(cmd.trainer_id), tostring(cmd.n), tostring(cmd.session),
                        tostring(cmd.battle_id), tostring(cmd.source), emu.framecount()))
            for i, h in ipairs(cmd.blobs_hex or {}) do ctx.log(fmt("RIVAL_BLOB %d %s", i - 1, h)) end
        end
        return inner(self, cmd)
    end

    -- one step Left onto the coord event (a short tap only turns; the player already faces Left)
    for _ = 1, 60 do
        local nx = select(1, ctx.G.pos(ctx.cp))
        if nx ~= RIVAL_STEP[3] or not ctx.on_field() then break end
        joypad.set({ Left = true })
        emu.frameadvance()
    end
    joypad.set({})

    -- drive the script (A) and the battle intro (B) to the first action menu, stamping transitions
    local last, tick = {}, 0
    local function stamp()
        local now = { main = fmt("0x%08X", u32(BATTLE_MAIN_FUNC)), comm0 = u8(BATTLE_COMM0),
                      opp = u16(ram.TRAINER_OPPONENT_ADDR), in_battle = tostring(ctx.in_battle()),
                      tbs = ctx.sent("trainer_battle_start"), cmd = ctx.received("replace_rival_team"),
                      reply = ctx.sent("rival_team_replaced") }
        for _, k in ipairs({ "main", "comm0", "opp", "in_battle", "tbs", "cmd", "reply" }) do
            if last[k] ~= now[k] then ctx.log(fmt("RIVAL_T %d %s=%s", emu.framecount(), k, tostring(now[k]))) end
        end
        last = now
        return now
    end
    local menu = false
    for _ = 1, 6000 do
        local now = stamp()
        if ctx.action_menu_up() then
            menu = true
            if now.reply > 0 then break end
            joypad.set({})
        else
            tick = tick + 1
            local btn = ctx.in_battle() and "B" or "A"
            joypad.set(tick % 16 == 0 and { [btn] = true } or {})
        end
        emu.frameadvance()
    end
    joypad.set({})
    if not menu then return false, "never reached the rival battle's action menu" end
    if ctx.sent("rival_team_replaced") == 0 then
        ctx.wait_sent("rival_team_replaced", nil, 60)
        stamp()
    end

    local count = u8(ram.ENEMY_COUNT_ADDR)
    ctx.log(fmt("ENEMY_COUNT %d", count))
    for i = 0, math.min(count, 6) - 1 do ctx.log(fmt("ENEMY_SLOT %d %s", i, hex(ram.ENEMY_BASE + i * 100, 100))) end
    local mon1 = ram.BATTLE_MONS_ADDR + 0x58
    ctx.log(fmt("BATTLE_MON1 species=%d pid=%08X", u16(mon1), u32(mon1 + 0x48)))
    ctx.log(fmt("TRAINER_OPPONENT_A %d", u16(ram.TRAINER_OPPONENT_ADDR)))
    local reply = ctx.last_sent("rival_team_replaced")
    if not reply then return false, "no rival_team_replaced reply" end
    if reply.error then
        return false, fmt("rival_team_replaced error=%s reason=%s", tostring(reply.error), tostring(reply.reason))
    end
    return true, fmt("rival %s swapped: %d enemy mon(s)", tostring(reply.trainer_id), count)
end
