--[[
  lua/tests/test_gen1_sfx_gate.lua — the native-sound state matrix on the patched cartridge.

  patch/gen1/src/slink.asm's SlinkSfxService plays a semantic request (mailbox +7: 1 success,
  2 failure, 3 boo) on the MAIN THREAD from the DelayFrame bridge, resolving it against the
  audio bank loaded at play time, and HOLDS it while a music fade runs or the SFX channels are
  busy. test_gen1_patch_gate.lua proves the quiet-overworld case; this gate proves the cases
  the ABI-2 VBlank build got wrong, each asserting the EXACT id that lands on CHAN5:

  town fixture (Oak's Lab, audio bank $1F):
    A. the shipped client turns a `play_sound 25` reply into the request (config native_sounds);
    B. busy channel: a second request is held while the first still owns CHAN5, then plays;
    C. the START menu (the bridge fires from the menu's own DelayFrame loop);
    D. fade + bank change: walking out of the lab into Pallet Town fades the lab music
       ($1F -> $02); a request written during the fade is held and plays after it, in $02.
  battle fixture (Route 1 grass):
    E. a real wild battle (bank $08): success is LEVEL_UP $86, failure is TINK $8C — the
       battle-bank row, not the overworld one;
    F. RUN, then a request written during the battle-end fade is held across the bank change
       and plays as the $02 row's GET_ITEM_2 $89 — the id it would NOT have been in $08.

  The runner selects the half by the fixture's map: --target town or --target battle.
  Normal buttons only; the only bytes written are the client's own mailbox slot.
  Result file: patch/build/test_gen1_sfx_gate_result.txt
--]]
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_sfx_gate")
local fmt = string.format
local ram, json = t.parts.profile.ram, t.parts.json
local Panel = dofile(t.ROOT .. "/lua/gen1/panel.lua")
local Center = dofile(t.ROOT .. "/lua/tests/gen1_rb_center_inputs.lua")
local MAILBOX = t.parts.profile.trade and t.parts.profile.trade.mailbox or Panel.MAILBOX
local SFX_REQUEST = MAILBOX + 7
local CAPS = MAILBOX + (Panel.CAPS - Panel.MAILBOX)
local CHANNEL_SOUND_IDS = t.facts.COMPANION.channel_sound_ids_addr
local CHAN5 = CHANNEL_SOUND_IDS + 4
local AUDIO_ROM_BANK = t.facts.COMPANION.audio_rom_bank_addr
local FADE = t.facts.COMPANION.audio_fade_out_control_addr
local CADENCE = t.facts.TUNING.input_cadence
local MAP = t.facts.MAP
local CAP_SFX = 0x01
-- slink.asm SlinkSfxService table, per audio bank: (header address - SFX_Headers_N) / 3.
local TABLE = {
    [0x02] = { 0x89, 0xA5, 0x8C },   -- GET_ITEM_2, DENIED, TINK
    [0x08] = { 0x86, 0x8C, 0x8C },   -- LEVEL_UP, TINK, TINK
    [0x1F] = { 0x89, 0xA5, 0x8C },   -- GET_ITEM_2, DENIED, TINK
}

local function read(addr) return memory.read_u8(addr, "System Bus") end
local function at(symbol) return read(assert(ram[symbol], symbol .. " missing from profile")) end
local function write(addr, value) t.deps.write_u8(addr, value) end
local function step(buttons)
    t.step(buttons or {})
    t.client:frame_end()          -- the shipped client runs every frame, as in production
end
local function channels()
    return fmt("%d/%d/%d/%d", read(CHANNEL_SOUND_IDS + 4), read(CHANNEL_SOUND_IDS + 5),
               read(CHANNEL_SOUND_IDS + 6), read(CHANNEL_SOUND_IDS + 7))
end
local function quiet()
    return read(CHAN5) == 0 and read(CHANNEL_SOUND_IDS + 5) == 0 and read(CHANNEL_SOUND_IDS + 7) == 0
end
-- Quiet = no SFX on CHAN5/6/8, no request pending AND no music fade running: the CONTINUE
-- boot fades the title music into the map's, and that fade can still be running when the
-- first case starts (measured: 205 = MUSIC_OAKS_LAB in wAudioFadeOutControl for the whole
-- window, the request correctly held the entire time).
local function wait_quiet(limit, buttons)
    for _ = 1, limit or 300 do
        if quiet() and read(SFX_REQUEST) == 0 and read(FADE) == 0 then return true end
        step(buttons)
    end
    return false
end
-- Write a code and watch up to `limit` frames for the ROM to consume it; returns the frame it
-- was consumed on and the CHAN5 id read that frame (the id the engine accepted).
local function request(code, limit)
    write(SFX_REQUEST, code)
    for f = 1, limit or 10 do
        step(nil)
        if read(SFX_REQUEST) == 0 then return f, read(CHAN5) end
    end
    return nil, read(CHAN5)
end
local function row(offset, n)
    local out = {}
    for i = 0, n - 1 do
        local b = read(ram.wTileMap + offset + i)
        if b >= 0x80 and b <= 0x99 then out[#out + 1] = string.char(65 + b - 0x80)
        elseif b == 0x7F then out[#out + 1] = " " else out[#out + 1] = "·" end
    end
    return table.concat(out)
end
local function reply(command)
    t.replies[#t.replies + 1] = assert(json.encode({ commands = { command } }))
end

-- Watch for a music fade while stepping with `buttons()`; write `code` on the first frame
-- wAudioFadeOutControl reads nonzero; require the request to stay HELD for the fade's whole
-- length, then to play the `expect_bank` row's id within 10 frames of the fade clearing.
local function fade_case(label, code, expect_bank, buttons, limit)
    local seen, held, written_at, played_at, bank_during = false, 0, nil, nil, nil
    local id_after, bank_after, consumed_early = nil, nil, false
    for f = 1, limit do
        local fading = read(FADE) ~= 0
        if fading and not seen then
            seen, written_at, bank_during = true, f, read(AUDIO_ROM_BANK)
            write(SFX_REQUEST, code)
        elseif seen and fading then
            held = held + 1
            if read(SFX_REQUEST) ~= code then consumed_early = true end
        elseif seen and not fading then
            -- the fade ended: the next main-thread tick must play it
            for g = 1, 10 do
                step(nil)
                if read(SFX_REQUEST) == 0 then played_at, id_after, bank_after = g, read(CHAN5), read(AUDIO_ROM_BANK) break end
            end
            break
        end
        step(buttons and buttons() or nil)
    end
    t.check(label .. ": the probe observed the fade (wAudioFadeOutControl != 0)", seen,
            fmt("never nonzero in %d frames — the case is not proven, not passed", limit))
    if not seen then return end
    t.check(label .. ": the request stayed held for the whole fade", held >= 5 and not consumed_early,
            fmt("held %d frames, consumed_early=%s (written frame %d, bank $%02X during)",
                held, tostring(consumed_early), written_at, bank_during))
    local want = TABLE[expect_bank] and TABLE[expect_bank][code]
    t.check(fmt("%s: played after the fade in bank $%02X as $%02X", label, expect_bank, want or 0),
            played_at ~= nil and bank_after == expect_bank and id_after == want,
            fmt("played_at=%s bank=$%02X CHAN5=$%02X channels %s (bank during the fade $%02X)",
                tostring(played_at), bank_after or 0, id_after or 0, channels(), bank_during))
end

-- ── common: capability, client online ─────────────────────────────────────────────────
t.check("the cartridge advertises SFX", read(CAPS) & CAP_SFX ~= 0, fmt("caps=0x%02X", read(CAPS)))
t.client:start()
t.online = true
step(nil)                                  -- loopback hello
reply({ cmd = "config", native_sounds = true })
step(nil)

local map = at("wCurMap")
if map == MAP.OAKS_LAB then
    -- ── A. through the shipped client ─────────────────────────────────────────────────
    local bank = read(AUDIO_ROM_BANK)
    t.check("the lab fixture stands in audio bank $1F", bank == 0x1F, fmt("wAudioROMBank=$%02X", bank))
    t.check("the SFX channels are quiet before the matrix", wait_quiet(), channels())
    reply({ cmd = "play_sound", sound = 25 })
    local wrote, played = nil, nil
    for f = 1, 20 do
        step(nil)
        if wrote == nil and read(SFX_REQUEST) == 1 then wrote = f end
        if wrote and read(SFX_REQUEST) == 0 then played = read(CHAN5) break end
    end
    if wrote == nil and played == nil then
        -- the write and the play can land inside one frame from Lua's point of view
        played = read(CHAN5)
    end
    t.check("A: the client turned play_sound 25 into request code 1 and the ROM played $89",
            played == 0x89, fmt("wrote_at=%s CHAN5=$%02X channels %s", tostring(wrote), played or 0, channels()))
    t.check("A: quiet again", wait_quiet(), channels())

    -- ── B. busy channel: the second request is held until the first finishes ─────────
    write(SFX_REQUEST, 1)
    step(nil); step(nil)
    local first = read(CHAN5)
    write(SFX_REQUEST, 2)
    local held, consumed_early = 0, false
    while read(CHAN5) == 0x89 and held < 400 do
        if read(SFX_REQUEST) ~= 2 then consumed_early = true end
        held = held + 1
        step(nil)
    end
    local at2, id2 = nil, nil
    for g = 1, 10 do
        step(nil)
        if read(SFX_REQUEST) == 0 then at2, id2 = g, read(CHAN5) break end
    end
    t.check("B: the first request played ($89 on CHAN5)", first == 0x89, fmt("CHAN5=$%02X", first))
    -- GET_ITEM_2 owns CHAN5 for ~180 frames; the hold ceiling (240) must outlast it, or the
    -- second request is played into a busy channel and the engine drops it (measured with a
    -- 120-frame ceiling: consumed at 120, nothing played).
    t.check("B: the second request was held while CHAN5 was busy, then played $A5",
            held >= 5 and not consumed_early and at2 ~= nil and id2 == 0xA5,
            fmt("held=%d consumed_early=%s played_at=%s CHAN5=$%02X channels %s",
                held, tostring(consumed_early), tostring(at2), id2 or 0, channels()))
    t.check("B: quiet again", wait_quiet(), channels())

    -- ── C. START menu open ────────────────────────────────────────────────────────────
    t.hold("Start", 10)
    t.idle(30)
    local menu_open = false
    for r = 0, 17 do if row(r * 20, 20):find("EXIT", 1, true) then menu_open = true end end
    t.check("C: the START menu is open (EXIT row on screen)", menu_open, fmt("wTextBoxID=%d", at("wTextBoxID")))
    t.check("C: quiet before the menu request (START_MENU's own blip finished)", wait_quiet(), channels())
    local at3, id3 = request(1, 10)
    t.check("C: a request with the START menu open plays $89 on CHAN5", at3 ~= nil and id3 == 0x89,
            fmt("played_at=%s CHAN5=$%02X channels %s", tostring(at3), id3 or 0, channels()))
    t.check("C: quiet again", wait_quiet(), channels())
    t.hold("B", 10)
    t.idle(30)

    -- ── D. lab door: fade + bank change $1F -> $02 ────────────────────────────────────
    local route = Center.new({
        read = read, ram = ram, row = row, frame = function() return t.frame end,
        log = t.log, check = t.check, start = "lab",
        invariant = function(label, ok, detail) if not ok then t.check(label, ok, detail) end end,
        menu_addr = Center.menu_symbols(t.ROOT, t.title),
    })
    Center.with_facts(t.facts)
    local walking = true
    fade_case("D: lab door", 2, 0x02, function()
        if walking and at("wCurMap") == MAP.PALLET_TOWN then walking = false end
        if not walking then return nil end
        local buttons = route.step()
        return buttons
    end, 1500)
    t.check("D: the player reached Pallet Town", at("wCurMap") == MAP.PALLET_TOWN,
            fmt("map=%d (%d,%d)", at("wCurMap"), at("wXCoord"), at("wYCoord")))
    t.check("D: quiet again", wait_quiet(), channels())

elseif map == MAP.ROUTE_1 then
    -- ── E. a real wild battle, audio bank $08 ────────────────────────────────────────
    local entered = false
    local dir = "Up"
    for f = 1, 3000 do
        if at("wIsInBattle") ~= 0 then entered = true break end
        if f % 32 == 0 then dir = dir == "Up" and "Down" or "Up" end
        step({ [dir] = true })
    end
    t.check("E: a wild battle started in the Route 1 grass", entered and at("wIsInBattle") == 1,
            fmt("wIsInBattle=%d map=%d (%d,%d)", at("wIsInBattle"), at("wCurMap"), at("wXCoord"), at("wYCoord")))
    local menu = false
    for f = 1, 1500 do
        if at("wTextBoxID") == t.facts.MENU.BATTLE.template and row(281, 18):find("FIGHT", 1, true) then
            menu = true break
        end
        step(f % CADENCE < 2 and { A = true } or nil)
    end
    t.check("E: the battle menu is drawn", menu, fmt("wTextBoxID=%d row=%s", at("wTextBoxID"), row(281, 18)))
    local bank = read(AUDIO_ROM_BANK)
    t.check("E: the battle runs in audio bank $08", bank == 0x08, fmt("wAudioROMBank=$%02X", bank))
    t.check("E: quiet before the battle requests", wait_quiet(), channels())
    local at1, id1 = request(1, 10)
    t.check("E: code 1 in battle plays LEVEL_UP $86 (the $08 row, not $89)", at1 ~= nil and id1 == 0x86,
            fmt("played_at=%s CHAN5=$%02X channels %s", tostring(at1), id1 or 0, channels()))
    t.check("E: quiet again", wait_quiet(), channels())
    local at2, id2 = request(2, 10)
    t.check("E: code 2 in battle plays TINK $8C (no buzzer in the battle bank)", at2 ~= nil and id2 == 0x8C,
            fmt("played_at=%s CHAN5=$%02X channels %s", tostring(at2), id2 or 0, channels()))
    t.check("E: quiet again", wait_quiet(), channels())

    -- ── F. RUN, then the battle-end fade: held in $08, played in $02 ─────────────────
    local menu_addr = Center.menu_symbols(t.ROOT, t.title)
    local attempts = 0
    local function run_buttons()
        if at("wIsInBattle") == 0 then return nil end
        if at("wTextBoxID") == t.facts.MENU.BATTLE.template and row(281, 18):find("FIGHT", 1, true) then
            local mx = read(menu_addr.wTopMenuItemX)
            if mx == t.facts.MENU.BATTLE.left_x then return t.frame % CADENCE < 2 and { Right = true } or nil end
            if at("wCurrentMenuItem") == 0 then return t.frame % CADENCE < 2 and { Down = true } or nil end
            if t.frame % CADENCE < 2 then attempts = attempts + 1; return { A = true } end
            return nil
        end
        return t.frame % CADENCE < 2 and { A = true } or nil
    end
    fade_case("F: battle-end", 1, 0x02, run_buttons, 3000)
    t.check("F: the battle ended by RUN", at("wIsInBattle") == 0 and at("wBattleResult") == 2 and attempts < 12,
            fmt("wIsInBattle=%d result=%d attempts=%d", at("wIsInBattle"), at("wBattleResult"), attempts))
    t.check("F: quiet again", wait_quiet(), channels())
else
    t.check("the fixture stands in Oak's Lab or on Route 1", false, fmt("map=%d", map))
end

-- ── the game still plays ─────────────────────────────────────────────────────────────
local X, Y = assert(ram.wXCoord), assert(ram.wYCoord)
local x0, y0 = read(X), read(Y)
local function moved() return read(X) ~= x0 or read(Y) ~= y0 end
t.hold("Left", 30, moved)
if not moved() then t.hold("Right", 30, moved) end
if not moved() then t.hold("Down", 30, moved) end
t.check("the player can still walk after the matrix", moved(),
        fmt("(%d,%d) -> (%d,%d)", x0, y0, read(X), read(Y)))
for _, line in ipairs(t.sent) do t.lines[#t.lines + 1] = "SENT " .. line end
t.finish(fmt("title=%s map=%d", t.title, at("wCurMap")))
