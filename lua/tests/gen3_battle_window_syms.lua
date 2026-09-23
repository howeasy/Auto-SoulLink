-- lua/tests/gen3_battle_window_syms.lua -- the FR/LG addresses the G4 2b battle-window rows
-- (gen3_battle_window_rows.lua) need that neither data/games/gen3_frlg/write_checkpoint.json nor
-- gen3_title_syms.lua already carries. Same entry shape as gen3_title_syms.lua, plus:
--   object = "<src/*.o>": the symbol is the ONE spelling of that name inside that object's .text
--            span in the title's linker map. The four controllers each define a static
--            HandleInputChooseAction / HandleChooseActionAfterDma3, so "the first same-named
--            symbol" is never a witness (plan g4_2b_matrix_plan_2026-09-23.md §1 sources line).
-- M.objects: [lo, hi) of each battle controller object's .text, from poke{firered,leafgreen}.map.
-- tests/unit/test_gen3_battle_window_rows.py proves every value against data/gen3/pret/*.sym/.map
-- (pret/pokefirered c75f3523). FR/LG only: the matrix admits no other title.

local M = {}

M.entries = {
    -- ── WRAM data (identical in FR/LG) ────────────────────────────────────────────────────────
    TRAINER_OPPONENT_A_ADDR    = { symbol = "gTrainerBattleOpponent_A", firered = 0x020386AE, leafgreen = 0x020386AE },
    BATTLER_PARTY_INDEXES_ADDR = { symbol = "gBattlerPartyIndexes",     firered = 0x02023BCE, leafgreen = 0x02023BCE },
    CHOSEN_ACTION_ADDR         = { symbol = "gChosenActionByBattler",   firered = 0x02023D7C, leafgreen = 0x02023D7C },
    -- u8 gBattleBufferB[4][0x200]: battler 0's controller return values start at the base
    BATTLE_BUFFER_B_ADDR       = { symbol = "gBattleBufferB",           firered = 0x020233C4, leafgreen = 0x020233C4 },

    -- ── code, as function-pointer VALUES (Thumb bit set) ─────────────────────────────────────
    CB2_RUN_SUMMARY_SCREEN = { symbol = "CB2_RunPokemonSummaryScreen", thumb = true,
                               firered = 0x08137EE9, leafgreen = 0x08137EC1 },
    PLAYER_ACTION_AFTER_DMA3 = { symbol = "HandleChooseActionAfterDma3", thumb = true,
                                 object = "src/battle_controller_player.o",
                                 firered = 0x08032B95, leafgreen = 0x08032B95 },
    PLAYER_BUFFER_RUN_COMMAND = { symbol = "PlayerBufferRunCommand", thumb = true,
                                  object = "src/battle_controller_player.o",
                                  firered = 0x0802E3B5, leafgreen = 0x0802E3B5 },
    PLAYER_CHOOSE_TARGET = { symbol = "HandleInputChooseTarget", thumb = true,
                             object = "src/battle_controller_player.o",
                             firered = 0x0802E675, leafgreen = 0x0802E675 },
    OLDMAN_INPUT_CHOOSE_ACTION = { symbol = "HandleInputChooseAction", thumb = true,
                                   object = "src/battle_controller_oak_old_man.o",
                                   firered = 0x080E763D, leafgreen = 0x080E7615 },
    POKEDUDE_INPUT_CHOOSE_ACTION = { symbol = "HandleInputChooseAction", thumb = true,
                                     object = "src/battle_controller_pokedude.o",
                                     firered = 0x08156141, leafgreen = 0x0815611D },
}

M.objects = {
    player      = { object = "src/battle_controller_player.o",
                    firered = {0x0802E310, 0x08033DB8}, leafgreen = {0x0802E310, 0x08033DB8} },
    opponent    = { object = "src/battle_controller_opponent.o",
                    firered = {0x08035A78, 0x08039188}, leafgreen = {0x08035A78, 0x08039188} },
    safari      = { object = "src/battle_controller_safari.o",
                    firered = {0x080DD534, 0x080DE0B4}, leafgreen = {0x080DD50C, 0x080DE08C} },
    oak_old_man = { object = "src/battle_controller_oak_old_man.o",
                    firered = {0x080E75AC, 0x080EB658}, leafgreen = {0x080E7584, 0x080EB630} },
    pokedude    = { object = "src/battle_controller_pokedude.o",
                    firered = {0x081560A0, 0x0815A008}, leafgreen = {0x0815607C, 0x08159FE4} },
}

--- name -> address, plus `spans` = {short object name -> {lo, hi}} for `title`.
function M.for_title(title)
    if title ~= "firered" and title ~= "leafgreen" then
        error("gen3_battle_window_syms: unsupported title " .. tostring(title), 0)
    end
    local out = { spans = {} }
    for name, e in pairs(M.entries) do out[name] = e[title] end
    for name, o in pairs(M.objects) do out.spans[name] = o[title] end
    return out
end

return M
