-- lua/hud.lua — Shared BizHawk HUD overlay module.
-- Provides message queue, center-screen prompts, and game-over banner.
-- Usage:
--   local HUD = dofile(SLINK_ROOT .. "lua/hud.lua")
--   HUD.init({screen_w=240, screen_h=160})  -- GBA
--   HUD.show("Hello!", 255, 255, 0, 180)
--   HUD.render()  -- call every frame

local fmt = string.format
local remove = table.remove

local H = {}

-- ── Configuration (set via init) ────────────────────────────────────────────
local cfg = {
    screen_w   = 240,   -- screen width
    screen_h   = 160,   -- screen height
    hud_x      = 3,     -- HUD bar left edge
    hud_y      = 146,   -- HUD bar top (near bottom of screen)
    hud_right  = 237,   -- HUD bar right edge
    prompt_y   = 44,    -- center prompt Y position
    prompt_h   = 14,    -- center prompt height
    gameover_y = 60,    -- game-over banner top
    font_size  = 10,    -- text font size
}

function H.init(opts)
    if not opts then return end
    for k, v in pairs(opts) do cfg[k] = v end
    -- Derive defaults if not explicitly set
    if not opts.hud_right then
        cfg.hud_right = cfg.screen_w - 3
    end
    if not opts.prompt_y then
        cfg.prompt_y = math.floor(cfg.screen_h * 0.275)
    end
    if not opts.prompt_h then
        cfg.prompt_h = 14
    end
    if not opts.gameover_y then
        cfg.gameover_y = math.floor(cfg.screen_h * 0.375)
    end
end

-- ── HUD message bar (bottom of screen, queued) ──────────────────────────────
local hud_queue = {}
local hud_visible = false

function H.show(text, r, g, b, duration_frames)
    hud_queue[#hud_queue + 1] = {
        text   = text,
        color  = fmt("#%02X%02X%02X", r or 255, g or 255, b or 255),
        frames = duration_frames or 240,
    }
end

local function render_hud()
    if #hud_queue == 0 then
        if hud_visible then
            gui.drawBox(cfg.hud_x - 2, cfg.hud_y - 2,
                        cfg.hud_right, cfg.hud_y + cfg.font_size,
                        0x00000000, 0x00000000)
            hud_visible = false
        end
        return
    end
    local msg = hud_queue[1]
    gui.drawBox(cfg.hud_x - 2, cfg.hud_y - 2,
                cfg.hud_right, cfg.hud_y + cfg.font_size,
                0xFF000000, 0xBB000000)
    gui.drawText(cfg.hud_x, cfg.hud_y, msg.text, msg.color,
                 nil, cfg.font_size, "Courier New", "Bold")
    hud_visible = true
    msg.frames = msg.frames - 1
    if msg.frames <= 0 then remove(hud_queue, 1) end
end

-- ── Center-screen prompt (prominent banner, auto-dismiss) ───────────────────
local prompt_queue = {}
local prompt_visible = false

function H.prompt(text, r, g, b, duration_frames)
    prompt_queue[#prompt_queue + 1] = {
        text   = text,
        color  = fmt("#%02X%02X%02X", r or 255, g or 255, b or 255),
        frames = duration_frames or 300,
    }
end

local function render_prompt()
    local py = cfg.prompt_y
    local py2 = py + cfg.prompt_h
    if #prompt_queue == 0 then
        if prompt_visible then
            gui.drawBox(1, py, cfg.screen_w - 1, py2, 0x00000000, 0x00000000)
            prompt_visible = false
        end
        return
    end
    local p = prompt_queue[1]
    gui.drawBox(1, py, cfg.screen_w - 1, py2, 0xFF000000, 0xCC000000)
    gui.drawText(4, py + 1, p.text, p.color, nil, cfg.font_size, "Courier New", "Bold")
    prompt_visible = true
    p.frames = p.frames - 1
    if p.frames <= 0 then remove(prompt_queue, 1) end
end

-- ── Game-over persistent overlay ────────────────────────────────────────────
local game_over = false

function H.set_game_over()
    game_over = true
end

function H.is_game_over()
    return game_over
end

local function render_game_over()
    if not game_over then return end
    local gy = cfg.gameover_y
    gui.drawBox(0, gy, cfg.screen_w, gy + 24, 0xFFBB0000, 0xDD990000)
    gui.drawText(8, gy + 4, "GAME OVER - SOUL LINK", "#FFFFFF",
                 nil, cfg.font_size + 2, "Courier New", "Bold")
end

-- ── Rebuild (post-whiteout) persistent banner ───────────────────────────────
-- Shown while the server is auto-restoring alive PC mons after a whiteout.
-- Blue palette to differentiate from red game_over; game_over overdraws if both
-- happen to be set (render order below).
local rebuild_text = nil

function H.set_rebuilding(text)
    rebuild_text = text or "REBUILDING TEAM"
end

function H.clear_rebuilding()
    rebuild_text = nil
end

function H.is_rebuilding()
    return rebuild_text ~= nil
end

local function render_rebuilding()
    if not rebuild_text or game_over then return end
    local ry = cfg.gameover_y
    gui.drawBox(0, ry, cfg.screen_w, ry + 14, 0xFF0066AA, 0xDD003388)
    gui.drawText(4, ry + 2, rebuild_text, "#FFFFFF",
                 nil, cfg.font_size, "Courier New", "Bold")
end

-- ── Master render (call once per frame, after all game logic) ───────────────
function H.render()
    render_prompt()
    render_hud()
    render_rebuilding()
    render_game_over()
end

-- ── Utility ─────────────────────────────────────────────────────────────────
function H.clear()
    hud_queue = {}
    prompt_queue = {}
    hud_visible = false
    prompt_visible = false
    rebuild_text = nil
end

return H
