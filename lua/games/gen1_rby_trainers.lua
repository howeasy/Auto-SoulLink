--[[
  lua/games/gen1_rby_trainers.lua — Gen 1 trainer class + named-trainer lookup.

  Used by gen1_rby_client.lua to set opponent_class / opponent_name in
  trainer-battle events without requiring a server-side adapter call.

  Source: pret/pokered constants/trainer_constants.asm + data/trainers/parties.asm.
  Class IDs as stored in wTrainerClass = OPP_ID_OFFSET (200) + const_id.
  Mirrors data/games/gen1_rby/trainers.json.
--]]

local M = {}

M.CLASS_NAMES = {
    [200] = "Nobody",
    [201] = "Youngster",     [202] = "Bug Catcher",   [203] = "Lass",
    [204] = "Sailor",        [205] = "Jr. Trainer ♂", [206] = "Jr. Trainer ♀",
    [207] = "Pokémaniac",   [208] = "Super Nerd",    [209] = "Hiker",
    [210] = "Biker",         [211] = "Burglar",       [212] = "Juggler",
    [213] = "Fisher",        [214] = "Swimmer",       [215] = "Cue Ball",
    [216] = "Gambler",       [217] = "Beauty",        [218] = "Psychic",
    [219] = "Rocker",        [220] = "Juggler",       [221] = "Tamer",
    [222] = "Bird Keeper",   [223] = "Blackbelt",     [224] = "Rival",
    [225] = "Prof. Oak",     [226] = "Chief",         [227] = "Scientist",
    [228] = "Giovanni",      [229] = "Rocket Grunt",  [230] = "Cooltrainer ♂",
    [231] = "Cooltrainer ♀", [232] = "Bruno",     [233] = "Brock",
    [234] = "Misty",         [235] = "Lt. Surge",     [236] = "Erika",
    [237] = "Koga",          [238] = "Blaine",        [239] = "Sabrina",
    [240] = "Gentleman",     [241] = "Rival",         [242] = "Rival",
    [243] = "Lorelei",       [244] = "Channeler",     [245] = "Agatha",
    [246] = "Lance",
}

-- For singleton classes (gym leaders, elite four), the class name IS the
-- character name. For Rival/Giovanni/etc., expand by trainer_id within class.
M.NAMED = {
    [228] = {"Giovanni", "Giovanni", "Giovanni"},          -- 3 fights
    [232] = {"Bruno"},
    [233] = {"Brock"},
    [234] = {"Misty"},
    [235] = {"Lt. Surge"},
    [236] = {"Erika"},
    [237] = {"Koga"},
    [238] = {"Blaine"},
    [239] = {"Sabrina"},
    [224] = {"Blue", "Blue", "Blue"},                       -- early rivals
    [225] = {"Prof. Oak"},
    [241] = {"Blue", "Blue", "Blue"},
    [242] = {"Blue", "Blue", "Blue", "Blue", "Blue"},      -- Champion
    [243] = {"Lorelei"},
    [245] = {"Agatha"},
    [246] = {"Lance"},
}

function M.resolve(class_id, trainer_id)
    local class_name = M.CLASS_NAMES[class_id] or ""
    local named = M.NAMED[class_id]
    local trainer_name = (named and named[trainer_id]) or ""
    -- For gym leaders, drop the redundant class name when it equals the
    -- trainer name (e.g. class "Brock" + name "Brock" → class "Leader").
    if trainer_name ~= "" and class_name == trainer_name then
        class_name = "Leader"
    end
    return class_name, trainer_name
end

return M
