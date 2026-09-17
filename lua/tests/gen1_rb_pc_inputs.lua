-- Bill's PC by play for Pokemon Red/Blue: walk to the Viridian Center PC from anywhere inside
-- the Center, turn it on and run an operation list (deposit / withdraw / release / change box)
-- through the NATIVE menus with ordinary buttons. No game-state writes and no blind button
-- sequences: every screen is identified by its cursor geometry AND a tilemap glyph probe before
-- a button is pressed, and every menu is re-pulsed on the 16-frame cadence. Same shape as
-- gen1_rb_hunt_inputs.lua: new(expected, opts) -> step(handshake, status, point, frame) returns
-- buttons, phase; the caller owns frames. Terminal phase: "pc-done".
--
-- Tilemap probing reuses gen1_rb_center_inputs.lua's has_tiles/row (pass it as opts.center, the
-- way duo_gen1_main.lua:47 already holds it, or pass opts.root and this module dofiles it the
-- way gen1_scripted_play.lua:40 loads its siblings). Nothing is copied.
--
-- ENGINE FACTS, all verified against E:/Google Drive/SLink/.cache/pret/pokered. Every item the
-- A6 plan marked "†" is listed here with the line that proves it.
--
--  PC site. data/events/hidden_events.asm:154-156 lists VIRIDIAN_POKECENTER's hidden events as
--    `hidden_event 0, 4, PrintBenchGuyText` and `hidden_event 13, 3, OpenPokemonCenterPC,
--    SPRITE_FACING_UP`; the macro at :107-112 takes x first (it stores y first). Hidden-event
--    coordinates are the tile IN FRONT of the player, not the player's tile
--    (engine/overworld/hidden_events.asm:55-60 -> CheckIfCoordsInFrontOfPlayerMatch, :88-90),
--    and OpenPokemonCenterPC returns unless the player faces UP
--    (engine/events/hidden_events/pokecenter_pc.asm:1-4). So: stand on (13,4) facing UP and
--    press A. † VERIFIED.
--  Walk geometry. Derived from maps/ViridianPokecenter.blk (7x4 blocks = 14x8 coords) over
--    gfx/blocksets/pokecenter.bst with the walkable set Pokecenter_Coll = $11,$1a,$1c,$3c,$5e
--    (data/tilesets/collision_tile_ids.asm:18-20). The collision byte for a coordinate is the
--    BOTTOM-LEFT tile of its 2x2 half-block: engine/overworld/player_state.asm:260-295 reads the
--    tile in front of the player at screen (8,7)/(8,11)/(6,9)/(10,9) while the player's own
--    half-block occupies screen (8..9, 9..10). Known-positive control on the derived grid: it
--    marks (13,3) NOT walkable (the PC, matching the hidden event) and (11,2) walkable (the
--    counter gap the LINK_RECEPTIONIST stands in, data/maps/objects/ViridianPokecenter.asm),
--    and row y=4 walkable for x=1..13 -- which is the row gen1_rb_center_inputs.lua:15-16
--    already crosses live ({3,4} -> {11,4} -> {11,3}). Hence: get to row y=4 on the current
--    column, walk east to x=13, face UP. † VERIFIED.
--  PC main menu. engine/pokemon/bills_pc.asm:77-80 sets wTopMenuItemY=2, wTopMenuItemX=1;
--    wMaxMenuItem is 3 with the Pokedex (:29-30), 2 without it (:69-70), 4 after the Hall of
--    Fame (:56-57). Rows are placed at hlcoord 2,2 / 2,4 / 2,6 ... -> tilemap 42, 82, 122 ...
--    Item 0 is always Bill's/SOMEONE's PC (engine/menus/pc.asm:22-24,31-33,41-43). The "'s"
--    glyph is $BD and has_tiles cannot spell it, so the probe is "SOMEONE"/"BILL" at 42 only.
--    † VERIFIED.
--  Bill's PC menu. bills_pc.asm:129-137 sets wTopMenuItemY=2, wTopMenuItemX=1, wMaxMenuItem=4;
--    BillsPCMenuText (:341-347) places "WITHDRAW <PKMN>" at hlcoord 2,2 and one item every two
--    rows -> 42 / 82 / 122 / 162 / 202. Item ids: 0 WITHDRAW, 1 DEPOSIT, 2 RELEASE, 3 CHANGE
--    BOX, 4 SEE YA (:179-186); B exits (:174-175). All five offsets † VERIFIED.
--  Mon list. DisplayMonListMenu -> DisplayListMenuID (home/list_menu.asm:48-52) sets
--    wTopMenuItemY=4, wTopMenuItemX=5; PrintListMenuEntries (:364-365) places the first name at
--    hlcoord 6,4 and prints 4 of them two rows apart -> 86 / 126 / 166 / 206. The selected entry
--    is wListScrollOffset + wCurrentMenuItem (:100-104). Names are nicknames, so the tilemap
--    probe is "the cursor row holds letters", not a fixed string. † VERIFIED.
--  Deposit/withdraw sub-box. DisplayDepositWithdrawMenu (bills_pc.asm:382-407) draws
--    "DEPOSIT"/"WITHDRAW" at hlcoord 11,12 -> 251 and "STATS"/"CANCEL" at 11,14 / 11,16 ->
--    291 / 331, with wTopMenuItemY=12, wTopMenuItemX=10, wMaxMenuItem=2; item 0 is the
--    deposit/withdraw action. † VERIFIED (251).
--  Deposit. bills_pc.asm:207-254: refuses with CantDepositLastMonText when wPartyCount is 1 and
--    with BoxFullText at MONS_PER_BOX (20), else wMoveMonType = PARTY_TO_BOX (1,
--    constants/menu_constants.asm:60-61) -> MoveMon -> wRemoveMonFromBox = 0 -> RemovePokemon ->
--    MonWasStoredText "<nick> was / stored in Box N.". † VERIFIED.
--  Withdraw. :256-291: refuses with NoMonText (empty box) or CantTakeMonText (party of 6), else
--    wMoveMonType = BOX_TO_PARTY (0) -> MoveMon -> wRemoveMonFromBox = 1 -> RemovePokemon ->
--    MonIsTakenOutText "<nick> is / taken out." -- i.e. a withdraw ALSO ends in a from_box
--    RemovePokemon, which is why from_box alone cannot discriminate a release (A6 client note).
--  Release. :293-318: box list -> OnceReleasedText "... is / gone forever. OK?" -> YesNoChoice
--    -> wRemoveMonFromBox = 1 -> standalone RemovePokemon -> MonWasReleasedText "<nick> was /
--    released outside.". † VERIFIED.
--  Change box. ChangeBox (engine/menus/save.asm:358-402): WhenYouChangeBoxText "...data / will
--    be saved." + "Is that okay?" -> YesNoChoice -> DisplayChangeBoxMenu (:437-506) with
--    wMaxMenuItem=11, wTopMenuItemY=1, wTopMenuItemX=12 and BoxNames placed at hlcoord 13,1 with
--    BIT_SINGLE_SPACED_LINES, so "BOX n" sits at 20*n + 13 for n = 1..12 (33 .. 253) -- the
--    plan's "20r+13" read with a 1-BASED row. wCurrentMenuItem is preseeded with the current
--    box. Then old box WRAM->SRAM, new box SRAM->WRAM, SaveGameData. † VERIFIED.
--  YES/NO box. home/yes_no.asm:3-19 puts it at hlcoord 14,7 with b=8,c=15;
--    engine/menus/text_box.asm:206-224,266-276 sets wTopMenuItemY=8, wTopMenuItemX=15,
--    wMaxMenuItem=1 and places the strings one row below the corner -> "YES" at 176, "NO" at
--    216. Item 0 is YES. † VERIFIED (176/216).
--  wCurrentBoxNum. BOX_NUM_MASK = %01111111 and BIT_HAS_CHANGED_BOXES = 7
--    (constants/ram_constants.asm:51-52): bit 7 set means the SRAM boxes have been initialised,
--    the low 7 bits are the 0-based box. wMoveMonType and wRemoveMonFromBox are the SAME byte
--    ($cf95 in data/pret/pokered.sym:18688-18689).
-- The shared input shapes (idle/hold/tap/move): this file's own directory locates the module,
-- the way the sibling drivers are already loaded.
local function here() return (debug.getinfo(1, "S").source or ""):match("^@(.*[/\\])") or "" end
local C = dofile(here() .. "gen1_inputs_common.lua")
local idle, hold, tap, move = C.idle, C.hold, C.tap, C.move

local M = {}
local fmt = string.format

M.MAP_CENTER = 0x29        -- VIRIDIAN_POKECENTER, as gen1_rb_center_inputs.lua:5
M.STAND = {13, 4}          -- the tile to stand on, facing UP
M.FLOOR_Y = 4              -- the open floor row this module walks along

-- Tilemap offsets (20 * row + column) and the 0-based Bill's PC item ids.
M.OFF = {main = 42, withdraw = 42, deposit = 82, release = 122, changebox = 162, seeya = 202,
         sub_action = 251, sub_cancel = 331, yes = 176, no = 216,
         list = 86, list_step = 40, box = 33, box_last = 253, text1 = 281, text2 = 321}
-- Per-op screen expectations: `item` is the 0-based Bill's PC row, `done` the success text's
-- dialogue line. (SEE YA is item 4; this module leaves it by B, which is the same exit.)
M.OPS = {
    deposit     = {item = 1, list = true, sub = true, done = "stored in Box"},
    withdraw    = {item = 0, list = true, sub = true, done = "taken out."},
    release_box = {item = 2, list = true, done = "released outside."},
    changebox   = {item = 3, boxlist = true},
}
local OPS = M.OPS
-- Refusal texts -> named terminal failure phases (see the header citations).
local REFUSALS = {
    {"the last", M.OFF.text2, "deposit-refused-last-mon"},
    {"full of ", M.OFF.text2, "deposit-refused-box-full"},
    {"any more", M.OFF.text2, "withdraw-refused-party-full"},
    {"What? There are", M.OFF.text1, "pc-refused-empty-box"},
}
M.TERMINALS = {["pc-done"] = true, ["pc-stuck"] = true, ["pc-left-the-center"] = true,
               ["pc-op-unconfirmed"] = true}
for _, refusal in ipairs(REFUSALS) do M.TERMINALS[refusal[3]] = true end


-- Box bookkeeping the scripted point does not carry. party_count is already on the point;
-- gen1_rb_point_fields.lua has no box decoder to reuse, so the three bytes are read here.
function M.extend_point(point, rd, symbols)
    local raw = rd(assert(symbols.wCurrentBoxNum, "wCurrentBoxNum"))
    point.box_count = rd(assert(symbols.wBoxCount, "wBoxCount"))
    point.current_box_num = raw
    point.box_number = raw % 128 + 1      -- BOX_NUM_MASK, 1-based as the game prints it
    point.box_initialised = raw >= 128    -- BIT_HAS_CHANGED_BOXES
    point.move_mon_type = rd(assert(symbols.wMoveMonType, "wMoveMonType"))
    return point
end

-- expected: {player = "a"|"b"}. opts:
--   ops      {{"deposit", <1-based party slot>}, {"withdraw", <1-based box index>},
--             {"release_box", <1-based box index>}, {"changebox", 1..12}, ...}
--   rd       read_u8 on the System Bus;  symbols  the title's pret .sym table
--   center   the gen1_rb_center_inputs module (or opts.root to dofile it)
--   log      optional line sink, one line per op transition (never per frame)
--   max_frames  optional per-phase stall bound (default 5400)
function M.new(expected, opts)
    assert(expected and (expected.player == "a" or expected.player == "b"), "R/B route identity required")
    assert(opts and opts.rd and opts.symbols and type(opts.ops) == "table" and #opts.ops > 0,
           "pc driver needs ops/rd/symbols")
    local Center = opts.center or dofile(assert(opts.root, "pc driver needs opts.center or opts.root")
                                         .. "/lua/tests/gen1_rb_center_inputs.lua")
    local rd, S, log = opts.rd, opts.symbols, opts.log or function() end
    local TILE = assert(S.wTileMap, "wTileMap missing from the pret symbols")
    local function tiles(text, off) return Center.has_tiles(rd, TILE, text, off) end
    local function row(off, n) return Center.row(rd, TILE, off, n) end
    for i, op in ipairs(opts.ops) do
        assert(OPS[op[1]], "unknown PC op " .. tostring(op[1]))
        assert(type(op[2]) == "number" and op[2] >= 1, "PC op " .. i .. " needs a 1-based index")
        assert(op[1] ~= "changebox" or op[2] <= 12, "box number must be 1..12")
    end
    local self = {last_frame = -1, last_phase = nil, index = 1, entered = false, left = false,
                  confirmed = false, budget = 0, settled = 0, terminal = nil, ops = opts.ops}

    -- Screen classifiers: cursor geometry AND glyphs. Bill's menu is tested before the PC main
    -- menu because both sit at Y=2/X=1 and differ only at offset 42.
    local function bills_menu(p)
        return p.menu_y == 2 and p.menu_x == 1 and p.menu_max == 4
               and tiles("WITHDRAW", M.OFF.withdraw) and tiles("SEE YA", M.OFF.seeya)
    end
    local function main_menu(p)
        return p.menu_y == 2 and p.menu_x == 1 and p.menu_max >= 2 and p.menu_max <= 4
               and (tiles("SOMEONE", M.OFF.main) or tiles("BILL", M.OFF.main))
    end
    local function list_menu(p)
        return p.menu_y == 4 and p.menu_x == 5 and p.list_menu_id == 0
               and row(M.OFF.list + M.OFF.list_step * p.menu_index, 10):find("%a") ~= nil
    end
    local function sub_menu(p)
        return p.menu_y == 12 and p.menu_x == 10 and p.menu_max == 2
               and (tiles("DEPOSIT", M.OFF.sub_action) or tiles("WITHDRAW", M.OFF.sub_action))
               and tiles("CANCEL", M.OFF.sub_cancel)
    end
    local function yes_no(p)
        return p.menu_y == 8 and p.menu_x == 15 and p.menu_max == 1
               and tiles("YES", M.OFF.yes) and tiles("NO", M.OFF.no)
    end
    local function box_menu(p)
        return p.menu_y == 1 and p.menu_x == 12 and p.menu_max == 11
               and tiles("BOX", M.OFF.box) and tiles("BOX", M.OFF.box_last)
    end
    local function toward(current, target, frame)
        if current < target then return tap("Down", frame) end
        if current > target then return tap("Up", frame) end
        return nil
    end

    local function on_bills(p, frame)
        local op = self.ops[self.index]
        if self.entered and self.left then
            if not self.confirmed then return idle(), "pc-op-unconfirmed" end
            log(fmt("PC op %d %s(%d) done frame=%d party=%d box_count=%s box=%s",
                    self.index, op[1], op[2], frame, p.party_count,
                    tostring(p.box_count), tostring(p.box_number)))
            self.index, self.entered, self.left, self.confirmed = self.index + 1, false, false, false
            op = self.ops[self.index]
        end
        if not op then return tap("B", frame), "pc-see-ya" end
        local turn = toward(p.menu_index, OPS[op[1]].item, frame)
        if turn then return turn, "pc-menu-" .. op[1] end
        if not self.entered then
            log(fmt("PC op %d %s(%d) start frame=%d", self.index, op[1], op[2], frame))
            self.entered = true
        end
        return tap("A", frame), "pc-enter-" .. op[1]   -- re-pulsed until the next screen draws
    end

    local function decide(p, frame)
        -- Walk: row y=4 on the current column first (every column the player can occupy in this
        -- Center is walkable down to y=4), then east to x=13, then turn UP into the PC wall.
        if p.x ~= M.STAND[1] or p.y ~= M.STAND[2] then
            local b = idle()
            if p.y ~= M.FLOOR_Y then b[p.y > M.FLOOR_Y and "Up" or "Down"] = true
            else b[p.x < M.STAND[1] and "Right" or "Left"] = true end
            return b, "pc-walk"
        end
        if self.entered and not self.left and not bills_menu(p) then self.left = true end
        if bills_menu(p) then return on_bills(p, frame) end
        if main_menu(p) then
            if not self.ops[self.index] then return tap("B", frame), "pc-log-off" end
            local turn = toward(p.menu_index, 0, frame)      -- item 0 = SOMEONE's/BILL's PC
            if turn then return turn, "pc-main-move" end
            return tap("A", frame), "pc-main-open"
        end
        local op = self.ops[self.index]
        if list_menu(p) and op then
            local cur = (p.list_scroll_offset or 0) + p.menu_index
            local turn = toward(cur, op[2] - 1, frame)
            if turn then return turn, "pc-list-move" end
            return tap("A", frame), "pc-list-pick"
        end
        if sub_menu(p) then
            local turn = toward(p.menu_index, 0, frame)      -- item 0 = DEPOSIT / WITHDRAW
            if turn then return turn, "pc-sub-move" end
            return tap("A", frame), "pc-sub-confirm"
        end
        if yes_no(p) then
            local turn = toward(p.menu_index, 0, frame)      -- item 0 = YES
            if turn then return turn, "pc-yes-move" end
            return tap("A", frame), "pc-yes"
        end
        if box_menu(p) and op then
            local turn = toward(p.menu_index, op[2] - 1, frame)
            if turn then return turn, "pc-box-move" end
            self.confirmed = true                            -- CHANGE BOX has no success text
            return tap("A", frame), "pc-box-pick"
        end
        -- No PC screen: the overworld, or a dialogue box. Refusals end the route by name.
        for _, refusal in ipairs(REFUSALS) do
            if tiles(refusal[1], refusal[2]) then return idle(), refusal[3] end
        end
        -- The success line is drawn on row 16, then "taken out."/"released outside." scroll up
        -- to row 14 behind their `cont` continuation, so both rows are probed.
        local done = op and OPS[op[1]].done
        if done and (tiles(done, M.OFF.text2) or tiles(done, M.OFF.text1)) then self.confirmed = true end
        if not op then
            self.settled = self.settled + 1
            if self.settled >= 60 then return idle(), "pc-done" end
            return idle(), "pc-logging-off"
        end
        self.settled = 0
        if p.facing ~= "up" then return {Up = true}, "pc-face" end
        -- A on the cadence turns the PC on, and afterwards advances the result dialogue.
        return tap("A", frame), self.entered and "pc-text" or "pc-activate"
    end

    function self.step(handshake, status, point, frame)
        assert(type(frame) == "number" and frame > self.last_frame, "pc frame did not advance")
        self.last_frame = frame
        assert(point and type(point.map) == "number" and type(point.x) == "number"
               and type(point.y) == "number" and type(point.menu_y) == "number"
               and type(point.menu_index) == "number" and type(point.party_count) == "number",
               "complete read-only PC point required")
        if self.terminal then return idle(), self.terminal end
        if point.map ~= M.MAP_CENTER then
            self.terminal = "pc-left-the-center"
            log(fmt("PC left the Center map=%d (%d,%d)", point.map, point.x, point.y))
            return idle(), self.terminal
        end
        local buttons, phase = decide(point, frame)
        if phase ~= self.last_phase then self.last_phase, self.budget = phase, 0 end
        self.budget = self.budget + 1
        if self.budget > (opts.max_frames or 5400) then
            log(fmt("PC stuck in %s at (%d,%d) menu=%d/%d/%d row14=%s row16=%s",
                    tostring(phase), point.x, point.y, point.menu_y, point.menu_x, point.menu_index,
                    row(M.OFF.text1, 18), row(M.OFF.text2, 18)))
            self.terminal = "pc-stuck"
            return idle(), self.terminal
        end
        if M.TERMINALS[phase] then
            self.terminal = phase
            log("PC " .. phase .. fmt(" frame=%d op=%d", frame, self.index))
        end
        return buttons, phase
    end
    return self
end
return M
