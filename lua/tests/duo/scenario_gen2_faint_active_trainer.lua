--[[
  lua/tests/duo/scenario_gen2_faint_active_trainer.lua -- the gen2_new `gen2_faint_active_trainer` scenario (O-30
  review MINOR-5, docs/gen2/reviews/REVIEW_O30_INBATTLE_FAINT_2026-09-24.md): gen2_faint_active with B's linked
  mon killed as the active battler of a TRAINER battle, so HandlePlayerMonFaint takes the trainer next-mon path
  (ForcePlayerMonChoice, no "Use next #MON?", C engine/battle/core.asm:2607-2654, 2695-2701) and the replacement
  fights a live turn after it. The wild "Use next?" path stays gen2_faint_active's.

  scenario_gen2_faint_active.lua with S.TRAINER (its header lists every marker change). B plays the link, saves,
  then walks Route 29 -> Cherrygrove -> Route 30 up the aisle until Youngster Joey (after the errand) or Mikey
  engages (duo_gen2_main.lua h.to_trainer). B needs an errand fixture on Crystal: before the errand the Route 30
  battle demo (EVENT_ROUTE_30_BATTLE clear) stands on the only aisle (C maps/Route30.asm:424-430, ElmsLab.asm:
  344-345). A is gen2_faint_active's A half unchanged. Every fixture is PLAYED; no O-33 synthetic setup: a
  CONTINUE keeps the saved map's object structs (C data/maps/setup_scripts.asm MapSetupScript_Continue,
  LoadMapAttributes_SkipObjects), so a save moved onto Route 30 would load no trainer at all.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-faint-active-trainer-v1"
S.FAINT_INPUTS = true
S.BATTLE_TRACE = true
S.TRAINER = true
S.ACTIVE = "lua/tests/duo/scenario_gen2_faint_active.lua"

-- scenario_gen2_faint_active.lua bound to the trainer battle
function S.active(root)
    local FA = dofile(root .. "/" .. S.ACTIVE)
    FA.TRAINER, FA.RECEIPT_SCHEMA = true, S.RECEIPT_SCHEMA
    return FA
end

function S.run(h) return S.active(h.root).run(h) end

return S
