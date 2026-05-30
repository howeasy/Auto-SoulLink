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

-- Glyph sanitization -----------------------------------------------------------
-- The HUD draws via gui.drawText (GDI+, .NET FontFamily; SLink passes "Courier
-- New"). The font has the glyphs; the problem is that BizHawk's Lua marshals
-- strings byte-by-byte and mangles multibyte UTF-8, so anything >= U+0080 (star,
-- gender signs, em dash, ellipsis, accented letters) reaches the overlay as a
-- tofu box / mojibake. Long-standing limitation -- see TASEmulators/BizHawk
-- issues #190 (kana/Unicode) and #3235 (shape chars not marshalled through Lua).
--
-- What BizHawk renders, by API (test notes):
--   * gui.drawText  - GDI+ real fonts. RELIABLE range: printable ASCII
--                     U+0020-U+007E. Single-byte Latin-1 (U+00A0-U+00FF) and
--                     other Courier New glyphs MAY render but are font/version
--                     dependent -- VERIFY in BizHawk before adding one to the
--                     keep-list below; do not assume from the font alone.
--   * gui.text      - fast, fixed style, no font control. ASCII only in practice.
--   * gui.pixelText - bitmap fonts "fceux"/"gens" only; ASCII only.
--
-- So we fold the symbols we actually use down to readable ASCII at this single
-- choke point, then strip any remaining high bytes so nothing un-drawable slips
-- through. Keys are raw UTF-8 byte sequences written with decimal escapes, which
-- parse on both Lua 5.1 (older BizHawk) and 5.4 (BizHawk 2.9+) -- unlike \u{}
-- (5.3+ only).
local GLYPH_MAP = {
    ["\226\152\133"] = "*",    -- U+2605 black star
    ["\226\152\134"] = "*",    -- U+2606 white star
    ["\226\156\168"] = "*",    -- U+2728 sparkles
    ["\226\156\166"] = "*",    -- U+2726 black four-pointed star
    ["\226\152\160"] = "X",    -- U+2620 skull and crossbones
    ["\226\154\160"] = "!",    -- U+26A0 warning sign
    ["\226\153\130"] = "M",    -- U+2642 male sign
    ["\226\153\128"] = "F",    -- U+2640 female sign
    ["\226\134\148"] = "<>",   -- U+2194 left-right arrow
    ["\226\134\146"] = ">",    -- U+2192 rightwards arrow
    ["\226\134\144"] = "<",    -- U+2190 leftwards arrow
    ["\226\134\147"] = "v",    -- U+2193 down arrow (deposited)
    ["\226\134\145"] = "^",    -- U+2191 up arrow (retrieved)
    ["\226\128\160"] = "+",    -- U+2020 dagger (memorialized)
    ["\226\128\148"] = "-",    -- U+2014 em dash
    ["\226\128\147"] = "-",    -- U+2013 en dash
    ["\226\128\166"] = "...",  -- U+2026 horizontal ellipsis
    ["\226\128\152"] = "'",    -- U+2018 left single quote
    ["\226\128\153"] = "'",    -- U+2019 right single quote
    ["\226\128\156"] = '"',    -- U+201C left double quote
    ["\226\128\157"] = '"',    -- U+201D right double quote
    ["\195\169"]     = "e",    -- U+00E9 e-acute (Pokemon, Flabebe)
    ["\195\168"]     = "e",    -- U+00E8 e-grave
    ["\195\161"]     = "a",    -- U+00E1 a-acute
    ["\195\173"]     = "i",    -- U+00ED i-acute
    ["\195\179"]     = "o",    -- U+00F3 o-acute
    ["\195\186"]     = "u",    -- U+00FA u-acute
    ["\195\177"]     = "n",    -- U+00F1 n-tilde
}

-- Fold known glyphs to ASCII, then drop any remaining bytes >= 0x80.
local function sanitize(s)
    if type(s) ~= "string" or s == "" then return s end
    for utf8_seq, ascii in pairs(GLYPH_MAP) do
        s = s:gsub(utf8_seq, ascii)
    end
    s = s:gsub("[\128-\255]", "")
    return s
end

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
    -- Empirical Courier New Bold advance per font size, used by the safety-net
    -- truncate in H.show / H.prompt to prevent text from bleeding past the dark
    -- backdrop. GBC clients override to 7 (font_size=8); GBA/NDS default 8.
    char_width = 8,
}

-- Truncate `text` so it fits within the bottom HUD bar at the current font.
-- Reserves 3 chars for "..." when truncation occurs. Returns the original
-- string when it already fits.
local function fit_hud(text)
    if type(text) ~= "string" then return text end
    local max_chars = math.floor((cfg.hud_right - cfg.hud_x) / cfg.char_width)
    if #text <= max_chars then return text end
    return text:sub(1, math.max(0, max_chars - 3)) .. "..."
end

-- Same as fit_hud but for the center prompt (full screen width minus 8px).
local function fit_prompt(text)
    if type(text) ~= "string" then return text end
    local max_chars = math.floor((cfg.screen_w - 8) / cfg.char_width)
    if #text <= max_chars then return text end
    return text:sub(1, math.max(0, max_chars - 3)) .. "..."
end

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
    text = fit_hud(sanitize(text))
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
    gui.drawText(cfg.hud_x, cfg.hud_y - 1, msg.text, msg.color,
                 nil, cfg.font_size, "Courier New", "Bold")
    hud_visible = true
    msg.frames = msg.frames - 1
    if msg.frames <= 0 then remove(hud_queue, 1) end
end

-- ── Center-screen prompt (prominent banner, auto-dismiss) ───────────────────
local prompt_queue = {}
local prompt_visible = false

function H.prompt(text, r, g, b, duration_frames)
    text = fit_prompt(sanitize(text))
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
    gui.drawText(8, gy + 4, "GAME OVER!", "#FFFFFF",
                 nil, cfg.font_size + 2, "Courier New", "Bold")
end

-- ── Rebuild (post-whiteout) persistent banner ───────────────────────────────
-- Shown while the server is auto-restoring alive PC mons after a whiteout.
-- Blue palette to differentiate from red game_over; game_over overdraws if both
-- happen to be set (render order below).
local rebuild_text = nil

function H.set_rebuilding(text)
    rebuild_text = sanitize(text or "REBUILDING TEAM")
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

-- ── Nuzlocke-start transient banner ─────────────────────────────────────────
-- Blue celebratory banner shown the moment the player first picks up Pokéballs.
-- Auto-dismisses; a later rebuild/game_over banner overdraws if both collide.
local nuzlocke_start_text    = nil
local nuzlocke_start_frames  = 0
local nuzlocke_start_visible = false

function H.nuzlocke_start(text, duration_frames)
    nuzlocke_start_text   = sanitize(text or "Nuzlocke Start!")
    nuzlocke_start_frames = duration_frames or 180
end

function H.is_nuzlocke_start()
    return nuzlocke_start_text ~= nil
end

local function render_nuzlocke_start()
    -- When inactive (text cleared or game_over overdrawing): if we painted
    -- the banner last frame, paint a transparent box over the same region
    -- once to erase it. BizHawk's gui surface persists last-painted pixels
    -- until something overdraws them, so without this the banner stays
    -- on-screen until the next map transition repaints the area.
    if not nuzlocke_start_text or game_over then
        if nuzlocke_start_visible then
            local ny = cfg.gameover_y
            gui.drawBox(0, ny, cfg.screen_w, ny + 24, 0x00000000, 0x00000000)
            nuzlocke_start_visible = false
        end
        return
    end
    local ny = cfg.gameover_y
    gui.drawBox(0, ny, cfg.screen_w, ny + 24, 0xFF0066AA, 0xDD003388)
    gui.drawText(8, ny + 4, nuzlocke_start_text, "#FFFFFF",
                 nil, cfg.font_size + 2, "Courier New", "Bold")
    nuzlocke_start_visible = true
    nuzlocke_start_frames = nuzlocke_start_frames - 1
    if nuzlocke_start_frames <= 0 then nuzlocke_start_text = nil end
end

-- ── Master render (call once per frame, after all game logic) ───────────────
function H.render()
    render_prompt()
    render_hud()
    render_nuzlocke_start()
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
    nuzlocke_start_text = nil
    nuzlocke_start_frames = 0
    nuzlocke_start_visible = false
end

return H
