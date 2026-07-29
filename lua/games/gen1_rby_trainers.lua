--[[
  lua/games/gen1_rby_trainers.lua — Gen 1 trainer class + named-trainer lookup.

  Used by gen1_rby_client.lua to set opponent_class / opponent_name in
  trainer-battle events without requiring a server-side adapter call.

  Source: pret/pokered constants/trainer_constants.asm + data/trainers/parties.asm.
  Class IDs as stored in wTrainerClass = OPP_ID_OFFSET (200) + const_id.
  Mirrors data/games/gen1_rby/trainers.json.
--]]

local M = {}

-- ENGINEER ($0C) was missing, which shifted EVERY class from 212 upward down by one:
-- BROCK ($22) resolved to "Misty", MISTY to "Lt. Surge", and so on for every gym leader,
-- Elite Four member and rival. LANCE ($2F -> 247) fell off the end entirely.
-- Verified one-for-one against pret/pokered constants/trainer_constants.asm ($00-$2F).
M.CLASS_NAMES = {
    [200] = "Nobody",
    [201] = "Youngster",     [202] = "Bug Catcher",   [203] = "Lass",
    [204] = "Sailor",        [205] = "Jr. Trainer ♂", [206] = "Jr. Trainer ♀",
    [207] = "Pokémaniac",    [208] = "Super Nerd",    [209] = "Hiker",
    [210] = "Biker",         [211] = "Burglar",       [212] = "Engineer",
    [213] = "Juggler",       [214] = "Fisher",        [215] = "Swimmer",
    [216] = "Cue Ball",      [217] = "Gambler",       [218] = "Beauty",
    [219] = "Psychic",       [220] = "Rocker",        [221] = "Juggler",
    [222] = "Tamer",         [223] = "Bird Keeper",   [224] = "Blackbelt",
    [225] = "Rival",         [226] = "Prof. Oak",     [227] = "Chief",
    [228] = "Scientist",     [229] = "Giovanni",      [230] = "Rocket Grunt",
    [231] = "Cooltrainer ♂", [232] = "Cooltrainer ♀", [233] = "Bruno",
    [234] = "Brock",         [235] = "Misty",         [236] = "Lt. Surge",
    [237] = "Erika",         [238] = "Koga",          [239] = "Blaine",
    [240] = "Sabrina",       [241] = "Gentleman",     [242] = "Rival",
    [243] = "Rival",         [244] = "Lorelei",       [245] = "Channeler",
    [246] = "Agatha",        [247] = "Lance",
}

-- RIVAL1 / RIVAL2 / RIVAL3 in OPP space ($19/$2A/$2B + 200). Kept next to the table it
-- is derived from so the two cannot drift; Gen1Adapter.rival_trainer_ids() returns these.
M.RIVAL_CLASS_IDS = {225, 242, 243}

-- For singleton classes (gym leaders, elite four), the class name IS the
-- character name. For Rival/Giovanni/etc., expand by trainer_id within class.
-- Shifted +1 with CLASS_NAMES above (the ENGINEER insertion at 212). Every id here
-- was one too low, so e.g. Giovanni's names hung off SCIENTIST and Lance's off AGATHA.
M.NAMED = {
    [225] = {"Blue", "Blue", "Blue"},                       -- RIVAL1, early rivals
    [226] = {"Prof. Oak"},
    [229] = {"Giovanni", "Giovanni", "Giovanni"},           -- 3 fights
    [233] = {"Bruno"},
    [234] = {"Brock"},
    [235] = {"Misty"},
    [236] = {"Lt. Surge"},
    [237] = {"Erika"},
    [238] = {"Koga"},
    [239] = {"Blaine"},
    [240] = {"Sabrina"},
    [242] = {"Blue", "Blue", "Blue"},                       -- RIVAL2
    [243] = {"Blue", "Blue", "Blue", "Blue", "Blue"},       -- RIVAL3, Champion
    [244] = {"Lorelei"},
    [246] = {"Agatha"},
    [247] = {"Lance"},
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
