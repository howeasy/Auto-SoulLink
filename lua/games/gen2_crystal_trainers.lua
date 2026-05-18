--[[
  lua/games/gen2_crystal_trainers.lua — Gen 2 Crystal trainer class + named lookup.

  Source: pret/pokecrystal constants/trainer_constants.asm + data/trainers/.
  Class IDs are 1-based raw values stored in wOtherTrainerClass.
--]]

local M = {}

M.CLASS_NAMES = {
    [0] = "Nobody",
    [1] = "Leader",        -- Falkner
    [2] = "Leader",        -- Whitney
    [3] = "Leader",        -- Bugsy
    [4] = "Leader",        -- Morty
    [5] = "Leader",        -- Pryce
    [6] = "Leader",        -- Jasmine
    [7] = "Leader",        -- Chuck
    [8] = "Leader",        -- Clair
    [9] = "Rival",         -- Rival 1
    [10] = "Pokémon Prof.",-- Oak
    [11] = "Elite Four",   -- Will
    [12] = "Cal",          -- Stadium
    [13] = "Elite Four",   -- Bruno
    [14] = "Elite Four",   -- Karen
    [15] = "Rocket Boss",  -- Koga in G/S; Crystal Koga is a leader
    [16] = "Champion",     -- Lance
    [17] = "Leader",       -- Brock
    [18] = "Leader",       -- Misty
    [19] = "Leader",       -- Lt. Surge
    [20] = "Scientist",
    [21] = "Leader",       -- Erika
    [22] = "Youngster",
    [23] = "Schoolboy",
    [24] = "Bird Keeper",
    [25] = "Lass",
    [26] = "Leader",       -- Janine
    [27] = "Cooltrainer ♂", [28] = "Cooltrainer ♀",
    [29] = "Beauty",
    [30] = "Pokémaniac",
    [31] = "Rocket Grunt",
    [32] = "Gentleman",
    [33] = "Skier",
    [34] = "Teacher",
    [35] = "Leader",       -- Sabrina
    [36] = "Bug Catcher",
    [37] = "Fisher",
    [38] = "Swimmer ♂", [39] = "Swimmer ♀",
    [40] = "Sailor", [41] = "Super Nerd",
    [42] = "Rival",
    [43] = "Guitarist",
    [44] = "Hiker",
    [45] = "Biker",
    [46] = "Leader",       -- Blaine
    [47] = "Burglar", [48] = "Firebreather", [49] = "Juggler",
    [50] = "Blackbelt",
    [51] = "Executive",
    [52] = "Psychic",
    [53] = "Picnicker", [54] = "Camper",
    [55] = "Executive",
    [56] = "Sage", [57] = "Medium", [58] = "Boarder",
    [59] = "Poké Fan ♂",
    [60] = "Kimono Girl",
    [61] = "Twins",
    [62] = "Poké Fan ♀",
    [63] = "PKMN Trainer",  -- Red (Mt. Silver)
    [64] = "PKMN Trainer",  -- Blue (Viridian Gym)
    [65] = "Officer",
    [66] = "Rocket Grunt",
    [67] = "Mystery Man",
}

M.NAMED = {
    [1]  = {"Falkner"},
    [2]  = {"Whitney"},
    [3]  = {"Bugsy"},
    [4]  = {"Morty"},
    [5]  = {"Pryce"},
    [6]  = {"Jasmine"},
    [7]  = {"Chuck"},
    [8]  = {"Clair"},
    [10] = {"Prof. Oak"},
    [11] = {"Will"},
    [13] = {"Bruno"},
    [14] = {"Karen"},
    [15] = {"Koga"},
    [16] = {"Lance"},
    [17] = {"Brock"},
    [18] = {"Misty"},
    [19] = {"Lt. Surge"},
    [21] = {"Erika"},
    [26] = {"Janine"},
    [35] = {"Sabrina"},
    [46] = {"Blaine"},
    [63] = {"Red"},
    [64] = {"Blue"},
}

function M.resolve(class_id, trainer_id)
    local class_name = M.CLASS_NAMES[class_id] or ""
    local named = M.NAMED[class_id]
    local trainer_name = (named and named[trainer_id]) or ""
    return class_name, trainer_name
end

return M
