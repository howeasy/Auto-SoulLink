# gen2-A1 — Gen 2 profile addresses vs pret symbols (mechanical audit)

**Scope.** Measure agreement only. Nothing here decides which side is right; the
coordinator reconciles against pret source. `lua/games/gen2_crystal.lua`, the verifier and
`data/pret_syms.json` were not modified.

Inputs: `lua/games/gen2_crystal.lua` (612 lines), `data/pret_syms.json` (1223175 bytes, mtime 2026-09-21 14:26:22 (epoch 1790015182.451)),
`tools/verify_profile_addresses.py` (365 lines). Four profile blocks audited:
`crystal` (lua:59-238), `gold` (lua:240-379), `silver` (lua:381-491), `crystal_ap`
(lua:521-536).

**Terms.** *covered* = the verifier holds a non-`None` `PROFILE_TO_PRET` mapping for that
`(variant, field)`, i.e. it compares an address. Fields mapped to `None` are `SKIP`ped and
are counted as uncovered, as are fields absent from `PROFILE_TO_PRET` entirely.

## Verifier output

### `python tools/verify_profile_addresses.py --json`  — exit 0

```json
[
  {
    "variant": "crystal",
    "field": "PARTY_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 56535,
    "pret_addr": 56535,
    "pret_symbol": "wPartyCount",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "PARTY_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 56536,
    "pret_addr": 56536,
    "pret_symbol": "wPartySpecies",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "PARTY_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 56543,
    "pret_addr": 56543,
    "pret_symbol": "wPartyMon1",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "PARTY_OT_NAMES_ADDR",
    "severity": "OK",
    "profile_addr": 56831,
    "pret_addr": 56831,
    "pret_symbol": "wPartyMonOTs",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "PARTY_NICKS_ADDR",
    "severity": "OK",
    "profile_addr": 56897,
    "pret_addr": 56897,
    "pret_symbol": "wPartyMonNicknames",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 53888,
    "pret_addr": 53888,
    "pret_symbol": "wOTPartyCount",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 53896,
    "pret_addr": 53896,
    "pret_symbol": "wOTPartyMon1",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BOX_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 44304,
    "pret_addr": 44304,
    "pret_symbol": "sBoxCount",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "CURRENT_BOX_NUM_ADDR",
    "severity": "OK",
    "profile_addr": 56178,
    "pret_addr": 56178,
    "pret_symbol": "wCurBox",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "JOY_IGNORE_ADDR",
    "severity": "OK",
    "profile_addr": 54328,
    "pret_addr": 54328,
    "pret_symbol": "wScriptRunning",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BOX_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 44305,
    "pret_addr": 44305,
    "pret_symbol": "sBoxSpecies",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BOX_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 44326,
    "pret_addr": 44326,
    "pret_symbol": "sBoxMons",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BOX_OT_NAMES_ADDR",
    "severity": "OK",
    "profile_addr": 44966,
    "pret_addr": 44966,
    "pret_symbol": "sBoxMonOTs",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BOX_NICKS_ADDR",
    "severity": "OK",
    "profile_addr": 45186,
    "pret_addr": 45186,
    "pret_symbol": "sBoxMonNicknames",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BAG_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 55511,
    "pret_addr": 55511,
    "pret_symbol": "wNumBalls",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BAG_ITEMS_ADDR",
    "severity": "OK",
    "profile_addr": 55512,
    "pret_addr": 55512,
    "pret_symbol": "wBalls",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BATTLE_FLAG_ADDR",
    "severity": "OK",
    "profile_addr": 53805,
    "pret_addr": 53805,
    "pret_symbol": "wBattleMode",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_MON_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 53766,
    "pret_addr": 53766,
    "pret_symbol": "wEnemyMon",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_MON_HP_ADDR",
    "severity": "OK",
    "profile_addr": 53782,
    "pret_addr": 53782,
    "pret_symbol": "wEnemyMonHP",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_MON_LEVEL_ADDR",
    "severity": "OK",
    "profile_addr": 53779,
    "pret_addr": 53779,
    "pret_symbol": "wEnemyMonLevel",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_MON_MAXHP_ADDR",
    "severity": "OK",
    "profile_addr": 53784,
    "pret_addr": 53784,
    "pret_symbol": "wEnemyMonMaxHP",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_SPECIES_LIST_ADDR",
    "severity": "OK",
    "profile_addr": 53889,
    "pret_addr": 53889,
    "pret_symbol": "wOTPartySpecies",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "MAP_GROUP_ADDR",
    "severity": "OK",
    "profile_addr": 56501,
    "pret_addr": 56501,
    "pret_symbol": "wMapGroup",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "MAP_NUMBER_ADDR",
    "severity": "OK",
    "profile_addr": 56502,
    "pret_addr": 56502,
    "pret_symbol": "wMapNumber",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "PLAYER_ID_ADDR",
    "severity": "OK",
    "profile_addr": 54395,
    "pret_addr": 54395,
    "pret_symbol": "wPlayerID",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "PLAYER_NAME_ADDR",
    "severity": "OK",
    "profile_addr": 54397,
    "pret_addr": 54397,
    "pret_symbol": "wPlayerName",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "BADGES_ADDR",
    "severity": "OK",
    "profile_addr": 55383,
    "pret_addr": 55383,
    "pret_symbol": "wJohtoBadges",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "KANTO_BADGES_ADDR",
    "severity": "OK",
    "profile_addr": 55384,
    "pret_addr": 55384,
    "pret_symbol": "wKantoBadges",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "species_offset",
    "severity": "SKIP",
    "profile_addr": 0,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "held_item_offset",
    "severity": "SKIP",
    "profile_addr": 1,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "otid_offset",
    "severity": "SKIP",
    "profile_addr": 6,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "dv_offset_1",
    "severity": "SKIP",
    "profile_addr": 21,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "dv_offset_2",
    "severity": "SKIP",
    "profile_addr": 22,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "level_offset",
    "severity": "SKIP",
    "profile_addr": 31,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "hp_offset",
    "severity": "SKIP",
    "profile_addr": 34,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "maxhp_offset",
    "severity": "SKIP",
    "profile_addr": 36,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "status_offset",
    "severity": "SKIP",
    "profile_addr": 32,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "stats_offset",
    "severity": "SKIP",
    "profile_addr": 38,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "spdef_offset",
    "severity": "SKIP",
    "profile_addr": 46,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "enemy_status_offset",
    "severity": "SKIP",
    "profile_addr": 14,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "box_species_offset",
    "severity": "SKIP",
    "profile_addr": 0,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "box_held_item_offset",
    "severity": "SKIP",
    "profile_addr": 1,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "box_otid_offset",
    "severity": "SKIP",
    "profile_addr": 6,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "box_dv_offset_1",
    "severity": "SKIP",
    "profile_addr": 21,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "box_dv_offset_2",
    "severity": "SKIP",
    "profile_addr": 22,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "box_level_offset",
    "severity": "SKIP",
    "profile_addr": 31,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "is_egg_species",
    "severity": "SKIP",
    "profile_addr": 253,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "PLAYER_STAT_STAGES_ADDR",
    "severity": "OK",
    "profile_addr": 50892,
    "pret_addr": 50892,
    "pret_symbol": "wPlayerStatLevels",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_STAT_STAGES_ADDR",
    "severity": "OK",
    "profile_addr": 50900,
    "pret_addr": 50900,
    "pret_symbol": "wEnemyStatLevels",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "moves_offset",
    "severity": "SKIP",
    "profile_addr": 2,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "pp_offset",
    "severity": "SKIP",
    "profile_addr": 23,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "ENEMY_BATTLE_MOVES_ADDR",
    "severity": "OK",
    "profile_addr": 53768,
    "pret_addr": 53768,
    "pret_symbol": "wEnemyMonMoves",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "ENEMY_BATTLE_PP_ADDR",
    "severity": "OK",
    "profile_addr": 53774,
    "pret_addr": 53774,
    "pret_symbol": "wEnemyMonPP",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "TRAINER_CLASS_ADDR",
    "severity": "OK",
    "profile_addr": 53807,
    "pret_addr": 53807,
    "pret_symbol": "wOtherTrainerClass",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "TRAINER_ID_ADDR",
    "severity": "OK",
    "profile_addr": 53809,
    "pret_addr": 53809,
    "pret_symbol": "wOtherTrainerID",
    "note": ""
  },
  {
    "variant": "crystal",
    "field": "capture",
    "severity": "SKIP",
    "profile_addr": 68,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "gift",
    "severity": "SKIP",
    "profile_addr": 68,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "faint",
    "severity": "SKIP",
    "profile_addr": 70,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "whiteout",
    "severity": "SKIP",
    "profile_addr": 70,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "no_catch",
    "severity": "SKIP",
    "profile_addr": 57,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "success",
    "severity": "SKIP",
    "profile_addr": 74,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "failure",
    "severity": "SKIP",
    "profile_addr": 57,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "boo",
    "severity": "SKIP",
    "profile_addr": 57,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "crystal",
    "field": "shiny",
    "severity": "SKIP",
    "profile_addr": 181,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "PARTY_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 55842,
    "pret_addr": 55842,
    "pret_symbol": "wPartyCount",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "PARTY_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 55843,
    "pret_addr": 55843,
    "pret_symbol": "wPartySpecies",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "PARTY_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 55850,
    "pret_addr": 55850,
    "pret_symbol": "wPartyMon1",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "PARTY_OT_NAMES_ADDR",
    "severity": "OK",
    "profile_addr": 56138,
    "pret_addr": 56138,
    "pret_symbol": "wPartyMonOTs",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "PARTY_NICKS_ADDR",
    "severity": "OK",
    "profile_addr": 56204,
    "pret_addr": 56204,
    "pret_symbol": "wPartyMonNicknames",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 56661,
    "pret_addr": 56661,
    "pret_symbol": "wOTPartyCount",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_SPECIES_LIST_ADDR",
    "severity": "OK",
    "profile_addr": 56662,
    "pret_addr": 56662,
    "pret_symbol": "wOTPartySpecies",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 56669,
    "pret_addr": 56669,
    "pret_symbol": "wOTPartyMon1",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BOX_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 44396,
    "pret_addr": 44396,
    "pret_symbol": "sBoxCount",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "CURRENT_BOX_NUM_ADDR",
    "severity": "OK",
    "profile_addr": 55484,
    "pret_addr": 55484,
    "pret_symbol": "wCurBox",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "JOY_IGNORE_ADDR",
    "severity": "OK",
    "profile_addr": 53599,
    "pret_addr": 53599,
    "pret_symbol": "wScriptRunning",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BOX_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 44397,
    "pret_addr": 44397,
    "pret_symbol": "sBoxSpecies",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BOX_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 44418,
    "pret_addr": 44418,
    "pret_symbol": "sBoxMons",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BOX_OT_NAMES_ADDR",
    "severity": "OK",
    "profile_addr": 45058,
    "pret_addr": 45058,
    "pret_symbol": "sBoxMonOTs",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BOX_NICKS_ADDR",
    "severity": "OK",
    "profile_addr": 45278,
    "pret_addr": 45278,
    "pret_symbol": "sBoxMonNicknames",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BAG_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 54780,
    "pret_addr": 54780,
    "pret_symbol": "wNumBalls",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BAG_ITEMS_ADDR",
    "severity": "OK",
    "profile_addr": 54781,
    "pret_addr": 54781,
    "pret_symbol": "wBalls",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BATTLE_FLAG_ADDR",
    "severity": "OK",
    "profile_addr": 53526,
    "pret_addr": 53526,
    "pret_symbol": "wBattleMode",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_MON_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 53487,
    "pret_addr": 53487,
    "pret_symbol": "wEnemyMon",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_MON_HP_ADDR",
    "severity": "OK",
    "profile_addr": 53503,
    "pret_addr": 53503,
    "pret_symbol": "wEnemyMonHP",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_MON_LEVEL_ADDR",
    "severity": "OK",
    "profile_addr": 53500,
    "pret_addr": 53500,
    "pret_symbol": "wEnemyMonLevel",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_MON_MAXHP_ADDR",
    "severity": "OK",
    "profile_addr": 53505,
    "pret_addr": 53505,
    "pret_symbol": "wEnemyMonMaxHP",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "MAP_GROUP_ADDR",
    "severity": "OK",
    "profile_addr": 55808,
    "pret_addr": 55808,
    "pret_symbol": "wMapGroup",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "MAP_NUMBER_ADDR",
    "severity": "OK",
    "profile_addr": 55809,
    "pret_addr": 55809,
    "pret_symbol": "wMapNumber",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "PLAYER_ID_ADDR",
    "severity": "OK",
    "profile_addr": 53665,
    "pret_addr": 53665,
    "pret_symbol": "wPlayerID",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "PLAYER_NAME_ADDR",
    "severity": "OK",
    "profile_addr": 53667,
    "pret_addr": 53667,
    "pret_symbol": "wPlayerName",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "BADGES_ADDR",
    "severity": "OK",
    "profile_addr": 54652,
    "pret_addr": 54652,
    "pret_symbol": "wJohtoBadges",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "KANTO_BADGES_ADDR",
    "severity": "OK",
    "profile_addr": 54653,
    "pret_addr": 54653,
    "pret_symbol": "wKantoBadges",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "species_offset",
    "severity": "SKIP",
    "profile_addr": 0,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "held_item_offset",
    "severity": "SKIP",
    "profile_addr": 1,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "otid_offset",
    "severity": "SKIP",
    "profile_addr": 6,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "dv_offset_1",
    "severity": "SKIP",
    "profile_addr": 21,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "dv_offset_2",
    "severity": "SKIP",
    "profile_addr": 22,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "level_offset",
    "severity": "SKIP",
    "profile_addr": 31,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "hp_offset",
    "severity": "SKIP",
    "profile_addr": 34,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "maxhp_offset",
    "severity": "SKIP",
    "profile_addr": 36,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "status_offset",
    "severity": "SKIP",
    "profile_addr": 32,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "stats_offset",
    "severity": "SKIP",
    "profile_addr": 38,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "spdef_offset",
    "severity": "SKIP",
    "profile_addr": 46,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "enemy_status_offset",
    "severity": "SKIP",
    "profile_addr": 14,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "box_species_offset",
    "severity": "SKIP",
    "profile_addr": 0,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "box_held_item_offset",
    "severity": "SKIP",
    "profile_addr": 1,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "box_otid_offset",
    "severity": "SKIP",
    "profile_addr": 6,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "box_dv_offset_1",
    "severity": "SKIP",
    "profile_addr": 21,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "box_dv_offset_2",
    "severity": "SKIP",
    "profile_addr": 22,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "box_level_offset",
    "severity": "SKIP",
    "profile_addr": 31,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "is_egg_species",
    "severity": "SKIP",
    "profile_addr": 253,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "PLAYER_STAT_STAGES_ADDR",
    "severity": "OK",
    "profile_addr": 52138,
    "pret_addr": 52138,
    "pret_symbol": "wPlayerStatLevels",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_STAT_STAGES_ADDR",
    "severity": "OK",
    "profile_addr": 52146,
    "pret_addr": 52146,
    "pret_symbol": "wEnemyStatLevels",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "moves_offset",
    "severity": "SKIP",
    "profile_addr": 2,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "pp_offset",
    "severity": "SKIP",
    "profile_addr": 23,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "gold",
    "field": "ENEMY_BATTLE_MOVES_ADDR",
    "severity": "OK",
    "profile_addr": 53489,
    "pret_addr": 53489,
    "pret_symbol": "wEnemyMonMoves",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "ENEMY_BATTLE_PP_ADDR",
    "severity": "OK",
    "profile_addr": 53495,
    "pret_addr": 53495,
    "pret_symbol": "wEnemyMonPP",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "TRAINER_CLASS_ADDR",
    "severity": "OK",
    "profile_addr": 53528,
    "pret_addr": 53528,
    "pret_symbol": "wOtherTrainerClass",
    "note": ""
  },
  {
    "variant": "gold",
    "field": "TRAINER_ID_ADDR",
    "severity": "OK",
    "profile_addr": 53531,
    "pret_addr": 53531,
    "pret_symbol": "wOtherTrainerID",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "PARTY_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 55842,
    "pret_addr": 55842,
    "pret_symbol": "wPartyCount",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "PARTY_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 55843,
    "pret_addr": 55843,
    "pret_symbol": "wPartySpecies",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "PARTY_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 55850,
    "pret_addr": 55850,
    "pret_symbol": "wPartyMon1",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "PARTY_OT_NAMES_ADDR",
    "severity": "OK",
    "profile_addr": 56138,
    "pret_addr": 56138,
    "pret_symbol": "wPartyMonOTs",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "PARTY_NICKS_ADDR",
    "severity": "OK",
    "profile_addr": 56204,
    "pret_addr": 56204,
    "pret_symbol": "wPartyMonNicknames",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 56661,
    "pret_addr": 56661,
    "pret_symbol": "wOTPartyCount",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_SPECIES_LIST_ADDR",
    "severity": "OK",
    "profile_addr": 56662,
    "pret_addr": 56662,
    "pret_symbol": "wOTPartySpecies",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 56669,
    "pret_addr": 56669,
    "pret_symbol": "wOTPartyMon1",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BOX_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 44396,
    "pret_addr": 44396,
    "pret_symbol": "sBoxCount",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "CURRENT_BOX_NUM_ADDR",
    "severity": "OK",
    "profile_addr": 55484,
    "pret_addr": 55484,
    "pret_symbol": "wCurBox",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "JOY_IGNORE_ADDR",
    "severity": "OK",
    "profile_addr": 53599,
    "pret_addr": 53599,
    "pret_symbol": "wScriptRunning",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BOX_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 44397,
    "pret_addr": 44397,
    "pret_symbol": "sBoxSpecies",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BOX_BASE_ADDR",
    "severity": "OK",
    "profile_addr": 44418,
    "pret_addr": 44418,
    "pret_symbol": "sBoxMons",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BOX_OT_NAMES_ADDR",
    "severity": "OK",
    "profile_addr": 45058,
    "pret_addr": 45058,
    "pret_symbol": "sBoxMonOTs",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BOX_NICKS_ADDR",
    "severity": "OK",
    "profile_addr": 45278,
    "pret_addr": 45278,
    "pret_symbol": "sBoxMonNicknames",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BAG_COUNT_ADDR",
    "severity": "OK",
    "profile_addr": 54780,
    "pret_addr": 54780,
    "pret_symbol": "wNumBalls",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BAG_ITEMS_ADDR",
    "severity": "OK",
    "profile_addr": 54781,
    "pret_addr": 54781,
    "pret_symbol": "wBalls",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BATTLE_FLAG_ADDR",
    "severity": "OK",
    "profile_addr": 53526,
    "pret_addr": 53526,
    "pret_symbol": "wBattleMode",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_MON_SPECIES_ADDR",
    "severity": "OK",
    "profile_addr": 53487,
    "pret_addr": 53487,
    "pret_symbol": "wEnemyMon",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_MON_HP_ADDR",
    "severity": "OK",
    "profile_addr": 53503,
    "pret_addr": 53503,
    "pret_symbol": "wEnemyMonHP",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_MON_LEVEL_ADDR",
    "severity": "OK",
    "profile_addr": 53500,
    "pret_addr": 53500,
    "pret_symbol": "wEnemyMonLevel",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_MON_MAXHP_ADDR",
    "severity": "OK",
    "profile_addr": 53505,
    "pret_addr": 53505,
    "pret_symbol": "wEnemyMonMaxHP",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "MAP_GROUP_ADDR",
    "severity": "OK",
    "profile_addr": 55808,
    "pret_addr": 55808,
    "pret_symbol": "wMapGroup",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "MAP_NUMBER_ADDR",
    "severity": "OK",
    "profile_addr": 55809,
    "pret_addr": 55809,
    "pret_symbol": "wMapNumber",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "PLAYER_ID_ADDR",
    "severity": "OK",
    "profile_addr": 53665,
    "pret_addr": 53665,
    "pret_symbol": "wPlayerID",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "PLAYER_NAME_ADDR",
    "severity": "OK",
    "profile_addr": 53667,
    "pret_addr": 53667,
    "pret_symbol": "wPlayerName",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "BADGES_ADDR",
    "severity": "OK",
    "profile_addr": 54652,
    "pret_addr": 54652,
    "pret_symbol": "wJohtoBadges",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "KANTO_BADGES_ADDR",
    "severity": "OK",
    "profile_addr": 54653,
    "pret_addr": 54653,
    "pret_symbol": "wKantoBadges",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "species_offset",
    "severity": "SKIP",
    "profile_addr": 0,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "held_item_offset",
    "severity": "SKIP",
    "profile_addr": 1,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "otid_offset",
    "severity": "SKIP",
    "profile_addr": 6,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "dv_offset_1",
    "severity": "SKIP",
    "profile_addr": 21,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "dv_offset_2",
    "severity": "SKIP",
    "profile_addr": 22,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "level_offset",
    "severity": "SKIP",
    "profile_addr": 31,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "hp_offset",
    "severity": "SKIP",
    "profile_addr": 34,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "maxhp_offset",
    "severity": "SKIP",
    "profile_addr": 36,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "status_offset",
    "severity": "SKIP",
    "profile_addr": 32,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "stats_offset",
    "severity": "SKIP",
    "profile_addr": 38,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "spdef_offset",
    "severity": "SKIP",
    "profile_addr": 46,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "enemy_status_offset",
    "severity": "SKIP",
    "profile_addr": 14,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "box_species_offset",
    "severity": "SKIP",
    "profile_addr": 0,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "box_held_item_offset",
    "severity": "SKIP",
    "profile_addr": 1,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "box_otid_offset",
    "severity": "SKIP",
    "profile_addr": 6,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "box_dv_offset_1",
    "severity": "SKIP",
    "profile_addr": 21,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "box_dv_offset_2",
    "severity": "SKIP",
    "profile_addr": 22,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "box_level_offset",
    "severity": "SKIP",
    "profile_addr": 31,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "is_egg_species",
    "severity": "SKIP",
    "profile_addr": 253,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "PLAYER_STAT_STAGES_ADDR",
    "severity": "OK",
    "profile_addr": 52138,
    "pret_addr": 52138,
    "pret_symbol": "wPlayerStatLevels",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_STAT_STAGES_ADDR",
    "severity": "OK",
    "profile_addr": 52146,
    "pret_addr": 52146,
    "pret_symbol": "wEnemyStatLevels",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "moves_offset",
    "severity": "SKIP",
    "profile_addr": 2,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "pp_offset",
    "severity": "SKIP",
    "profile_addr": 23,
    "pret_addr": null,
    "pret_symbol": null,
    "note": "no pret symbol (offset / constant)"
  },
  {
    "variant": "silver",
    "field": "ENEMY_BATTLE_MOVES_ADDR",
    "severity": "OK",
    "profile_addr": 53489,
    "pret_addr": 53489,
    "pret_symbol": "wEnemyMonMoves",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "ENEMY_BATTLE_PP_ADDR",
    "severity": "OK",
    "profile_addr": 53495,
    "pret_addr": 53495,
    "pret_symbol": "wEnemyMonPP",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "TRAINER_CLASS_ADDR",
    "severity": "OK",
    "profile_addr": 53528,
    "pret_addr": 53528,
    "pret_symbol": "wOtherTrainerClass",
    "note": ""
  },
  {
    "variant": "silver",
    "field": "TRAINER_ID_ADDR",
    "severity": "OK",
    "profile_addr": 53531,
    "pret_addr": 53531,
    "pret_symbol": "wOtherTrainerID",
    "note": ""
  }
]
```

### `python tools/verify_profile_addresses.py --verbose`  — exit 0

```text
[OK]   crystal  PARTY_COUNT_ADDR                 profile=0xDCD7  pret=0xDCD7  wPartyCount               
[OK]   crystal  PARTY_SPECIES_ADDR               profile=0xDCD8  pret=0xDCD8  wPartySpecies             
[OK]   crystal  PARTY_BASE_ADDR                  profile=0xDCDF  pret=0xDCDF  wPartyMon1                
[OK]   crystal  PARTY_OT_NAMES_ADDR              profile=0xDDFF  pret=0xDDFF  wPartyMonOTs              
[OK]   crystal  PARTY_NICKS_ADDR                 profile=0xDE41  pret=0xDE41  wPartyMonNicknames        
[OK]   crystal  ENEMY_COUNT_ADDR                 profile=0xD280  pret=0xD280  wOTPartyCount             
[OK]   crystal  ENEMY_BASE_ADDR                  profile=0xD288  pret=0xD288  wOTPartyMon1              
[OK]   crystal  BOX_COUNT_ADDR                   profile=0xAD10  pret=0xAD10  sBoxCount                 
[OK]   crystal  CURRENT_BOX_NUM_ADDR             profile=0xDB72  pret=0xDB72  wCurBox                   
[OK]   crystal  JOY_IGNORE_ADDR                  profile=0xD438  pret=0xD438  wScriptRunning            
[OK]   crystal  BOX_SPECIES_ADDR                 profile=0xAD11  pret=0xAD11  sBoxSpecies               
[OK]   crystal  BOX_BASE_ADDR                    profile=0xAD26  pret=0xAD26  sBoxMons                  
[OK]   crystal  BOX_OT_NAMES_ADDR                profile=0xAFA6  pret=0xAFA6  sBoxMonOTs                
[OK]   crystal  BOX_NICKS_ADDR                   profile=0xB082  pret=0xB082  sBoxMonNicknames          
[OK]   crystal  BAG_COUNT_ADDR                   profile=0xD8D7  pret=0xD8D7  wNumBalls                 
[OK]   crystal  BAG_ITEMS_ADDR                   profile=0xD8D8  pret=0xD8D8  wBalls                    
[OK]   crystal  BATTLE_FLAG_ADDR                 profile=0xD22D  pret=0xD22D  wBattleMode               
[OK]   crystal  ENEMY_MON_SPECIES_ADDR           profile=0xD206  pret=0xD206  wEnemyMon                 
[OK]   crystal  ENEMY_MON_HP_ADDR                profile=0xD216  pret=0xD216  wEnemyMonHP               
[OK]   crystal  ENEMY_MON_LEVEL_ADDR             profile=0xD213  pret=0xD213  wEnemyMonLevel            
[OK]   crystal  ENEMY_MON_MAXHP_ADDR             profile=0xD218  pret=0xD218  wEnemyMonMaxHP            
[OK]   crystal  ENEMY_SPECIES_LIST_ADDR          profile=0xD281  pret=0xD281  wOTPartySpecies           
[OK]   crystal  MAP_GROUP_ADDR                   profile=0xDCB5  pret=0xDCB5  wMapGroup                 
[OK]   crystal  MAP_NUMBER_ADDR                  profile=0xDCB6  pret=0xDCB6  wMapNumber                
[OK]   crystal  PLAYER_ID_ADDR                   profile=0xD47B  pret=0xD47B  wPlayerID                 
[OK]   crystal  PLAYER_NAME_ADDR                 profile=0xD47D  pret=0xD47D  wPlayerName               
[OK]   crystal  BADGES_ADDR                      profile=0xD857  pret=0xD857  wJohtoBadges              
[OK]   crystal  KANTO_BADGES_ADDR                profile=0xD858  pret=0xD858  wKantoBadges              
[SKIP] crystal  species_offset                   profile=0x0000  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  held_item_offset                 profile=0x0001  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  otid_offset                      profile=0x0006  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  dv_offset_1                      profile=0x0015  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  dv_offset_2                      profile=0x0016  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  level_offset                     profile=0x001F  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  hp_offset                        profile=0x0022  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  maxhp_offset                     profile=0x0024  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  status_offset                    profile=0x0020  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  stats_offset                     profile=0x0026  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  spdef_offset                     profile=0x002E  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  enemy_status_offset              profile=0x000E  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  box_species_offset               profile=0x0000  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  box_held_item_offset             profile=0x0001  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  box_otid_offset                  profile=0x0006  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  box_dv_offset_1                  profile=0x0015  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  box_dv_offset_2                  profile=0x0016  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  box_level_offset                 profile=0x001F  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  is_egg_species                   profile=0x00FD  pret=----                            no pret symbol (offset / constant)
[OK]   crystal  PLAYER_STAT_STAGES_ADDR          profile=0xC6CC  pret=0xC6CC  wPlayerStatLevels         
[OK]   crystal  ENEMY_STAT_STAGES_ADDR           profile=0xC6D4  pret=0xC6D4  wEnemyStatLevels          
[SKIP] crystal  moves_offset                     profile=0x0002  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  pp_offset                        profile=0x0017  pret=----                            no pret symbol (offset / constant)
[OK]   crystal  ENEMY_BATTLE_MOVES_ADDR          profile=0xD208  pret=0xD208  wEnemyMonMoves            
[OK]   crystal  ENEMY_BATTLE_PP_ADDR             profile=0xD20E  pret=0xD20E  wEnemyMonPP               
[OK]   crystal  TRAINER_CLASS_ADDR               profile=0xD22F  pret=0xD22F  wOtherTrainerClass        
[OK]   crystal  TRAINER_ID_ADDR                  profile=0xD231  pret=0xD231  wOtherTrainerID           
[SKIP] crystal  capture                          profile=0x0044  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  gift                             profile=0x0044  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  faint                            profile=0x0046  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  whiteout                         profile=0x0046  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  no_catch                         profile=0x0039  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  success                          profile=0x004A  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  failure                          profile=0x0039  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  boo                              profile=0x0039  pret=----                            no pret symbol (offset / constant)
[SKIP] crystal  shiny                            profile=0x00B5  pret=----                            no pret symbol (offset / constant)
[OK]   gold     PARTY_COUNT_ADDR                 profile=0xDA22  pret=0xDA22  wPartyCount               
[OK]   gold     PARTY_SPECIES_ADDR               profile=0xDA23  pret=0xDA23  wPartySpecies             
[OK]   gold     PARTY_BASE_ADDR                  profile=0xDA2A  pret=0xDA2A  wPartyMon1                
[OK]   gold     PARTY_OT_NAMES_ADDR              profile=0xDB4A  pret=0xDB4A  wPartyMonOTs              
[OK]   gold     PARTY_NICKS_ADDR                 profile=0xDB8C  pret=0xDB8C  wPartyMonNicknames        
[OK]   gold     ENEMY_COUNT_ADDR                 profile=0xDD55  pret=0xDD55  wOTPartyCount             
[OK]   gold     ENEMY_SPECIES_LIST_ADDR          profile=0xDD56  pret=0xDD56  wOTPartySpecies           
[OK]   gold     ENEMY_BASE_ADDR                  profile=0xDD5D  pret=0xDD5D  wOTPartyMon1              
[OK]   gold     BOX_COUNT_ADDR                   profile=0xAD6C  pret=0xAD6C  sBoxCount                 
[OK]   gold     CURRENT_BOX_NUM_ADDR             profile=0xD8BC  pret=0xD8BC  wCurBox                   
[OK]   gold     JOY_IGNORE_ADDR                  profile=0xD15F  pret=0xD15F  wScriptRunning            
[OK]   gold     BOX_SPECIES_ADDR                 profile=0xAD6D  pret=0xAD6D  sBoxSpecies               
[OK]   gold     BOX_BASE_ADDR                    profile=0xAD82  pret=0xAD82  sBoxMons                  
[OK]   gold     BOX_OT_NAMES_ADDR                profile=0xB002  pret=0xB002  sBoxMonOTs                
[OK]   gold     BOX_NICKS_ADDR                   profile=0xB0DE  pret=0xB0DE  sBoxMonNicknames          
[OK]   gold     BAG_COUNT_ADDR                   profile=0xD5FC  pret=0xD5FC  wNumBalls                 
[OK]   gold     BAG_ITEMS_ADDR                   profile=0xD5FD  pret=0xD5FD  wBalls                    
[OK]   gold     BATTLE_FLAG_ADDR                 profile=0xD116  pret=0xD116  wBattleMode               
[OK]   gold     ENEMY_MON_SPECIES_ADDR           profile=0xD0EF  pret=0xD0EF  wEnemyMon                 
[OK]   gold     ENEMY_MON_HP_ADDR                profile=0xD0FF  pret=0xD0FF  wEnemyMonHP               
[OK]   gold     ENEMY_MON_LEVEL_ADDR             profile=0xD0FC  pret=0xD0FC  wEnemyMonLevel            
[OK]   gold     ENEMY_MON_MAXHP_ADDR             profile=0xD101  pret=0xD101  wEnemyMonMaxHP            
[OK]   gold     MAP_GROUP_ADDR                   profile=0xDA00  pret=0xDA00  wMapGroup                 
[OK]   gold     MAP_NUMBER_ADDR                  profile=0xDA01  pret=0xDA01  wMapNumber                
[OK]   gold     PLAYER_ID_ADDR                   profile=0xD1A1  pret=0xD1A1  wPlayerID                 
[OK]   gold     PLAYER_NAME_ADDR                 profile=0xD1A3  pret=0xD1A3  wPlayerName               
[OK]   gold     BADGES_ADDR                      profile=0xD57C  pret=0xD57C  wJohtoBadges              
[OK]   gold     KANTO_BADGES_ADDR                profile=0xD57D  pret=0xD57D  wKantoBadges              
[SKIP] gold     species_offset                   profile=0x0000  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     held_item_offset                 profile=0x0001  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     otid_offset                      profile=0x0006  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     dv_offset_1                      profile=0x0015  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     dv_offset_2                      profile=0x0016  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     level_offset                     profile=0x001F  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     hp_offset                        profile=0x0022  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     maxhp_offset                     profile=0x0024  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     status_offset                    profile=0x0020  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     stats_offset                     profile=0x0026  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     spdef_offset                     profile=0x002E  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     enemy_status_offset              profile=0x000E  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     box_species_offset               profile=0x0000  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     box_held_item_offset             profile=0x0001  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     box_otid_offset                  profile=0x0006  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     box_dv_offset_1                  profile=0x0015  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     box_dv_offset_2                  profile=0x0016  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     box_level_offset                 profile=0x001F  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     is_egg_species                   profile=0x00FD  pret=----                            no pret symbol (offset / constant)
[OK]   gold     PLAYER_STAT_STAGES_ADDR          profile=0xCBAA  pret=0xCBAA  wPlayerStatLevels         
[OK]   gold     ENEMY_STAT_STAGES_ADDR           profile=0xCBB2  pret=0xCBB2  wEnemyStatLevels          
[SKIP] gold     moves_offset                     profile=0x0002  pret=----                            no pret symbol (offset / constant)
[SKIP] gold     pp_offset                        profile=0x0017  pret=----                            no pret symbol (offset / constant)
[OK]   gold     ENEMY_BATTLE_MOVES_ADDR          profile=0xD0F1  pret=0xD0F1  wEnemyMonMoves            
[OK]   gold     ENEMY_BATTLE_PP_ADDR             profile=0xD0F7  pret=0xD0F7  wEnemyMonPP               
[OK]   gold     TRAINER_CLASS_ADDR               profile=0xD118  pret=0xD118  wOtherTrainerClass        
[OK]   gold     TRAINER_ID_ADDR                  profile=0xD11B  pret=0xD11B  wOtherTrainerID           
[OK]   silver   PARTY_COUNT_ADDR                 profile=0xDA22  pret=0xDA22  wPartyCount               
[OK]   silver   PARTY_SPECIES_ADDR               profile=0xDA23  pret=0xDA23  wPartySpecies             
[OK]   silver   PARTY_BASE_ADDR                  profile=0xDA2A  pret=0xDA2A  wPartyMon1                
[OK]   silver   PARTY_OT_NAMES_ADDR              profile=0xDB4A  pret=0xDB4A  wPartyMonOTs              
[OK]   silver   PARTY_NICKS_ADDR                 profile=0xDB8C  pret=0xDB8C  wPartyMonNicknames        
[OK]   silver   ENEMY_COUNT_ADDR                 profile=0xDD55  pret=0xDD55  wOTPartyCount             
[OK]   silver   ENEMY_SPECIES_LIST_ADDR          profile=0xDD56  pret=0xDD56  wOTPartySpecies           
[OK]   silver   ENEMY_BASE_ADDR                  profile=0xDD5D  pret=0xDD5D  wOTPartyMon1              
[OK]   silver   BOX_COUNT_ADDR                   profile=0xAD6C  pret=0xAD6C  sBoxCount                 
[OK]   silver   CURRENT_BOX_NUM_ADDR             profile=0xD8BC  pret=0xD8BC  wCurBox                   
[OK]   silver   JOY_IGNORE_ADDR                  profile=0xD15F  pret=0xD15F  wScriptRunning            
[OK]   silver   BOX_SPECIES_ADDR                 profile=0xAD6D  pret=0xAD6D  sBoxSpecies               
[OK]   silver   BOX_BASE_ADDR                    profile=0xAD82  pret=0xAD82  sBoxMons                  
[OK]   silver   BOX_OT_NAMES_ADDR                profile=0xB002  pret=0xB002  sBoxMonOTs                
[OK]   silver   BOX_NICKS_ADDR                   profile=0xB0DE  pret=0xB0DE  sBoxMonNicknames          
[OK]   silver   BAG_COUNT_ADDR                   profile=0xD5FC  pret=0xD5FC  wNumBalls                 
[OK]   silver   BAG_ITEMS_ADDR                   profile=0xD5FD  pret=0xD5FD  wBalls                    
[OK]   silver   BATTLE_FLAG_ADDR                 profile=0xD116  pret=0xD116  wBattleMode               
[OK]   silver   ENEMY_MON_SPECIES_ADDR           profile=0xD0EF  pret=0xD0EF  wEnemyMon                 
[OK]   silver   ENEMY_MON_HP_ADDR                profile=0xD0FF  pret=0xD0FF  wEnemyMonHP               
[OK]   silver   ENEMY_MON_LEVEL_ADDR             profile=0xD0FC  pret=0xD0FC  wEnemyMonLevel            
[OK]   silver   ENEMY_MON_MAXHP_ADDR             profile=0xD101  pret=0xD101  wEnemyMonMaxHP            
[OK]   silver   MAP_GROUP_ADDR                   profile=0xDA00  pret=0xDA00  wMapGroup                 
[OK]   silver   MAP_NUMBER_ADDR                  profile=0xDA01  pret=0xDA01  wMapNumber                
[OK]   silver   PLAYER_ID_ADDR                   profile=0xD1A1  pret=0xD1A1  wPlayerID                 
[OK]   silver   PLAYER_NAME_ADDR                 profile=0xD1A3  pret=0xD1A3  wPlayerName               
[OK]   silver   BADGES_ADDR                      profile=0xD57C  pret=0xD57C  wJohtoBadges              
[OK]   silver   KANTO_BADGES_ADDR                profile=0xD57D  pret=0xD57D  wKantoBadges              
[SKIP] silver   species_offset                   profile=0x0000  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   held_item_offset                 profile=0x0001  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   otid_offset                      profile=0x0006  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   dv_offset_1                      profile=0x0015  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   dv_offset_2                      profile=0x0016  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   level_offset                     profile=0x001F  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   hp_offset                        profile=0x0022  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   maxhp_offset                     profile=0x0024  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   status_offset                    profile=0x0020  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   stats_offset                     profile=0x0026  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   spdef_offset                     profile=0x002E  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   enemy_status_offset              profile=0x000E  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   box_species_offset               profile=0x0000  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   box_held_item_offset             profile=0x0001  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   box_otid_offset                  profile=0x0006  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   box_dv_offset_1                  profile=0x0015  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   box_dv_offset_2                  profile=0x0016  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   box_level_offset                 profile=0x001F  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   is_egg_species                   profile=0x00FD  pret=----                            no pret symbol (offset / constant)
[OK]   silver   PLAYER_STAT_STAGES_ADDR          profile=0xCBAA  pret=0xCBAA  wPlayerStatLevels         
[OK]   silver   ENEMY_STAT_STAGES_ADDR           profile=0xCBB2  pret=0xCBB2  wEnemyStatLevels          
[SKIP] silver   moves_offset                     profile=0x0002  pret=----                            no pret symbol (offset / constant)
[SKIP] silver   pp_offset                        profile=0x0017  pret=----                            no pret symbol (offset / constant)
[OK]   silver   ENEMY_BATTLE_MOVES_ADDR          profile=0xD0F1  pret=0xD0F1  wEnemyMonMoves            
[OK]   silver   ENEMY_BATTLE_PP_ADDR             profile=0xD0F7  pret=0xD0F7  wEnemyMonPP               
[OK]   silver   TRAINER_CLASS_ADDR               profile=0xD118  pret=0xD118  wOtherTrainerClass        
[OK]   silver   TRAINER_ID_ADDR                  profile=0xD11B  pret=0xD11B  wOtherTrainerID           

Summary: 102 ok / 0 fail / 0 warn / 72 skip
```

## Independent extraction (script + table)

Ran as `python -c <script>` from the worktree root, exit 0. It does not import the
verifier's parser; it imports only `PROFILE_TO_PRET` to classify coverage.

```python
"""Throwaway audit (gen2-A1): every hex-valued field in each Gen 2 profile block,
against data/pret_syms.json.  Run from the repo root:  python - <this file>
Not committed, not imported.

The "symbol" column is the pret symbol the field's OWN LINE comment names -- the first
token on that line's comment matching pret's wFoo / sFoo convention.  A field whose line
has no such comment is NO_SYMBOL_IN_COMMENT, which means "this method cannot see a named
symbol", NOT "no symbol exists".
"""
import importlib.util
import json
import pathlib
import re
from collections import Counter

LUA = pathlib.Path("lua/games/gen2_crystal.lua")
SYMS = pathlib.Path("data/pret_syms.json")
VERIFIER = pathlib.Path("tools/verify_profile_addresses.py")

text = LUA.read_text(encoding="utf-8")
syms = json.loads(SYMS.read_text(encoding="utf-8"))


def match_brace(s, i):
    """Index of the '}' matching s[i] == '{', ignoring braces inside -- comments."""
    depth = 0
    n = len(s)
    while i < n:
        if s[i:i + 2] == "--":
            nl = s.find("\n", i)
            i = n if nl < 0 else nl
            continue
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def find_block(pattern):
    m = re.search(pattern, text)
    j = text.find("{", m.end() - 1)
    return j, match_brace(text, j)


BLOCKS = {
    "crystal":    find_block(r"\n    crystal = \{"),
    "gold":       find_block(r"\n    gold = \{"),
    "silver":     find_block(r"\n    silver = \{"),
    # crystal_ap is NOT inside M.PROFILES = { } -- it is a setmetatable() call after it.
    "crystal_ap": find_block(r"M\.PROFILES\.crystal_ap = setmetatable\(\{"),
}

FIELD_LINE = re.compile(r"^([ \t]*)(\w+)[ \t]*=[ \t]*(0x[0-9A-Fa-f]+)(.*)$")
SYM_TOKEN = re.compile(r"^([ws][A-Z][A-Za-z0-9_]*)\b")

REPO_OF = {"crystal": "pokecrystal", "crystal_ap": "pokecrystal",
           "gold": "pokegold", "silver": "pokegold"}


def fields(start, end):
    """Hex-valued fields in the block body, with the symbol its own line comment names."""
    body = text[start + 1:end]
    out, depth = [], 0
    for line in body.split("\n"):
        cut = line.find("--")
        code = line if cut < 0 else line[:cut]
        m = FIELD_LINE.match(line)
        if m:
            symbol = None
            ci = m.group(4).find("--")
            if ci >= 0:
                tok = m.group(4)[ci + 2:].strip().split()
                if tok and SYM_TOKEN.match(tok[0]):
                    symbol = SYM_TOKEN.match(tok[0]).group(1)
            out.append((m.group(2), int(m.group(3), 16), symbol, depth))
        depth += code.count("{") - code.count("}")
    return out


spec = importlib.util.spec_from_file_location("vp", VERIFIER)
vp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vp)

rows = []
for variant, (a, b) in BLOCKS.items():
    table = syms[REPO_OF[variant]]
    for field, value, symbol, depth in fields(a, b):
        if symbol is None:
            verdict, pret = "NO_SYMBOL_IN_COMMENT", None
        elif symbol not in table:
            verdict, pret = "SYMBOL_NOT_IN_JSON", None
        else:
            pret = table[symbol]
            verdict = "MATCH" if pret == value else "MISMATCH"
        mapping = vp.PROFILE_TO_PRET.get((variant, field), "ABSENT")
        covered = bool(mapping) and mapping != "ABSENT" and mapping is not None
        rows.append((variant, field, value, symbol, pret, verdict, depth, covered))

print(f"{'profile':<11}{'field':<26}{'lua':<9}{'symbol in comment':<23}"
      f"{'pret_syms.json':<16}{'verdict':<22}covered")
for variant, field, value, symbol, pret, verdict, depth, covered in rows:
    prets = f"0x{pret:04X}" if pret is not None else "-"
    print(f"{variant:<11}{field:<26}0x{value:04X}   {(symbol or '-'):<20}{prets:<16}"
          f"{verdict:<22}{'yes' if covered else 'no'}")

counts = Counter(r[5] for r in rows)
print()
print(f"TOTAL fields={len(rows)}  covered={sum(r[7] for r in rows)}  "
      f"uncovered={sum(not r[7] for r in rows)}")
print("verdicts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
for variant in BLOCKS:
    v = [r for r in rows if r[0] == variant]
    print(f"  {variant:<11} fields={len(v):<4} covered={sum(r[7] for r in v):<4} "
          f"match={sum(r[5] == 'MATCH' for r in v):<4} "
          f"mismatch={sum(r[5] == 'MISMATCH' for r in v)}")
```

```text

```

Field-inventory cross-check: the verifier extracted 174 hex fields across `crystal`/
`gold`/`silver` (102 `OK` + 72 `SKIP`); this script extracted the same 174 plus the 5
fields of `crystal_ap` = 179.

## Uncovered fields

77 of 179 fields carry no address comparison. All 72 uncovered fields in `crystal`/
`gold`/`silver` are **explicit** `None` entries in `PROFILE_TO_PRET` (verifier `SKIP`) —
the three vanilla profiles contain **zero** unmapped hex fields (0 `WARN` in both runs).
The remaining 5 are the whole `crystal_ap` block, which the verifier never reaches.

| profile | field | lua value | step-2 verdict | verifier status |
|---|---|---|---|---|
| crystal | species_offset | 0x0000 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | held_item_offset | 0x0001 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | otid_offset | 0x0006 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | dv_offset_1 | 0x0015 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | dv_offset_2 | 0x0016 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | level_offset | 0x001F | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | hp_offset | 0x0022 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | maxhp_offset | 0x0024 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | status_offset | 0x0020 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | stats_offset | 0x0026 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | spdef_offset | 0x002E | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | enemy_status_offset | 0x000E | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | box_species_offset | 0x0000 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | box_held_item_offset | 0x0001 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | box_otid_offset | 0x0006 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | box_dv_offset_1 | 0x0015 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | box_dv_offset_2 | 0x0016 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | box_level_offset | 0x001F | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | is_egg_species | 0x00FD | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | moves_offset | 0x0002 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | pp_offset | 0x0017 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal | capture | 0x0044 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| crystal | gift | 0x0044 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| crystal | faint | 0x0046 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| crystal | whiteout | 0x0046 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| crystal | no_catch | 0x0039 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| crystal | success | 0x004A | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| crystal | failure | 0x0039 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| crystal | boo | 0x0039 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| crystal | shiny | 0x00B5 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP); nested table |
| gold | species_offset | 0x0000 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | held_item_offset | 0x0001 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | otid_offset | 0x0006 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | dv_offset_1 | 0x0015 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | dv_offset_2 | 0x0016 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | level_offset | 0x001F | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | hp_offset | 0x0022 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | maxhp_offset | 0x0024 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | status_offset | 0x0020 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | stats_offset | 0x0026 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | spdef_offset | 0x002E | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | enemy_status_offset | 0x000E | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | box_species_offset | 0x0000 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | box_held_item_offset | 0x0001 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | box_otid_offset | 0x0006 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | box_dv_offset_1 | 0x0015 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | box_dv_offset_2 | 0x0016 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | box_level_offset | 0x001F | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | is_egg_species | 0x00FD | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | moves_offset | 0x0002 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| gold | pp_offset | 0x0017 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | species_offset | 0x0000 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | held_item_offset | 0x0001 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | otid_offset | 0x0006 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | dv_offset_1 | 0x0015 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | dv_offset_2 | 0x0016 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | level_offset | 0x001F | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | hp_offset | 0x0022 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | maxhp_offset | 0x0024 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | status_offset | 0x0020 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | stats_offset | 0x0026 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | spdef_offset | 0x002E | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | enemy_status_offset | 0x000E | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | box_species_offset | 0x0000 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | box_held_item_offset | 0x0001 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | box_otid_offset | 0x0006 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | box_dv_offset_1 | 0x0015 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | box_dv_offset_2 | 0x0016 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | box_level_offset | 0x001F | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | is_egg_species | 0x00FD | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | moves_offset | 0x0002 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| silver | pp_offset | 0x0017 | NO_SYMBOL_IN_COMMENT | PROFILE_TO_PRET = None (SKIP) |
| crystal_ap | MAP_GROUP_ADDR | 0xDCC0 | MISMATCH | not in PROFILE_TO_PRET (block never parsed) |
| crystal_ap | MAP_NUMBER_ADDR | 0xDCC1 | MISMATCH | not in PROFILE_TO_PRET (block never parsed) |
| crystal_ap | wMapEventStatus | 0xD437 | NO_SYMBOL_IN_COMMENT | not in PROFILE_TO_PRET (block never parsed); nested table |
| crystal_ap | wStatusFlags | 0xD827 | NO_SYMBOL_IN_COMMENT | not in PROFILE_TO_PRET (block never parsed); nested table |
| crystal_ap | wEventFlags | 0xDA8F | NO_SYMBOL_IN_COMMENT | not in PROFILE_TO_PRET (block never parsed); nested table |

Structural notes (findings, not verdicts):

- The verifier's `_extract_variant_addresses()` walks only inside `M.PROFILES = { ... }`
  and breaks at depth 0 (verify_profile_addresses.py:143-199). `crystal_ap` is defined
  **after** that block as `M.PROFILES.crystal_ap = setmetatable({...})`
  (gen2_crystal.lua:521), so it is invisible: neither `OK`, `SKIP` nor `WARN` — no row at
  all. `PROFILE_TO_PRET` likewise has no `crystal_ap` keys.
- `PROFILE_TO_PRET` maps `SFX_DISPATCH_ADDR` → `wMusicID` for all three vanilla variants
  (verify_profile_addresses.py:230), with a comment saying a skipped-by-default field is
  how Gen 2 shipped `0xC2BD`. That mapping is dead: the profile value is `nil`
  (gen2_crystal.lua:203), so the hex-only extractor never sees the field and the row the
  comment describes does not exist in either run above.
- `sfx_ids` (9 nested hex fields in `crystal`) and `ap_known_addresses` (3 nested hex
  fields in `crystal_ap`) are SFX ids and fork addresses respectively, not WRAM
  addresses; the 9 `sfx_ids` are `SKIP`ped by the verifier, the 3 `ap_known_addresses`
  are not seen at all.

## Mismatches

Two, both in `crystal_ap`, both against vanilla `pokecrystal` values — i.e. the
deliberate fork overrides documented at gen2_crystal.lua:497-520, not drift.

| profile | field | lua value | symbol named in comment | pokecrystal value | delta |
|---|---|---|---|---|---|
| crystal_ap | MAP_GROUP_ADDR | 0xDCC0 | wMapGroup | 0xDCB5 | +11 |
| crystal_ap | MAP_NUMBER_ADDR | 0xDCC1 | wMapNumber | 0xDCB6 | +11 |

Every other compared field agrees. Of the 179 fields, 102 are compared by the verifier
and all 102 are `OK`; of the 11 fields whose own line comment names a pret symbol, all 11
are `MATCH` (4 in `crystal`, 7 in `gold`, 0 in `silver` — the `silver` block duplicates
`gold`'s values without copying its inline symbol comments). 166 fields carry no inline
symbol, which is a limit of the same-line-comment method, **not** evidence that no symbol
exists — `MAP_GROUP_ADDR` in `crystal` names `wMapGroup` on its line, the identical field
in `gold` names nothing.

## Provenance

- `data/pret_syms.json`: 1223175 bytes, mtime 2026-09-21 14:26:22 (epoch 1790015182.451).
  Shape is flat `{repo: {symbol: int}}`; top keys `['pokered', 'pokeyellow', 'alchav_pokered', 'pokecrystal', 'pokegold']`; symbol counts
  `{'pokered': 2653, 'pokeyellow': 3005, 'alchav_pokered': 2461, 'pokecrystal': 15454, 'pokegold': 12574}`.
- **No `rom_sha1` exists in `data/pret_syms.json`** (`'rom_sha1' in json == False`;
  `grep -c rom_sha1 data/pret_syms.json` → 0). The brief's stated input does not hold for
  this file.
- `rom_sha1` is written by `tools/build_pret_syms.py` into its *other* artifact,
  `data/pret_rom_syms.json` (1556501 bytes, mtime 2026-09-21 14:26:22 (epoch 1790015182.448)), whose top keys are
  `['pokered', 'pokeblue', 'pokeyellow']` — **no `pokecrystal` and no `pokegold` entry**. Values present:
  `pokered` = `ea9bcae617fdf159b045185467ae58b2e4a48b9a`; `pokeblue` = `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2`; `pokeyellow` = `cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1`.
  So neither repo this audit checks can be tied to a ROM revision from the committed
  data; the two artifacts also share a build timestamp, so this is one build, not two.
- Both verifier runs exited 0 (`Summary: 102 ok / 0 fail / 0 warn / 72 skip`).
- `git status --short` restricted to the lease: `?? docs/gen2/research/` (this file only;
  the worktree's other 3 untracked files are pre-existing `docs/agents/*.md`).
- Environment: `python` = 3.12.10, cwd = the worktree root.

DONE gen2-A1: 179 fields, 102 covered by verifier, 2 mismatches, 77 uncovered
