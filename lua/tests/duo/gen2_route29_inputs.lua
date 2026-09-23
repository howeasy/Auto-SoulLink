--[[
  lua/tests/duo/gen2_route29_inputs.lua -- the gen2_new duo's Route 29 route (card gen2-H1).

  Normal buttons only, from a warm crystal_battle(_ot2) arrival on Route 29 grass:
    walk    one held direction per frame between grass tiles (a walk step is 8 frames; the
            direction is re-decided every frame, never a 12-frame press)
    battle  BattleMenu PACK -> the Ball pocket -> POKe BALL -> USE, A through battle text, NO to the
            nickname (_AskGiveNicknameText, item_effects.asm:574-581), until the engine capture
    report  (still phase "battle") the overworld is held back until the driver has printed CAUGHT,
            i.e. until the client sent the capture it observed; the save cannot start earlier
    save    START -> SAVE -> YES -> (overwrite text) -> YES, the native _SaveGameData completion
  The point -> buttons driver IS the U1 gate's (lua/tests/gen2_frame_align.lua F.driver, proven live
  PHYSICAL on this fixture): 12-frame menu HOLD + one release frame, per-frame walk holds. The UI read
  is the shared scripted gate's observer (qualified UI origins, the N17 battle-menu grid); this file only
  adds the Ball-pocket UI kinds and the catch-nickname prompt (SLINK_GEN2_U1_FACTS, produced by
  tests/live/test_gen2_frame_align.u1_facts) and feeds the engine-capture count in as probe_hits.
--]]
local R = {}
R.PACK_KINDS = {"pack_items", "pack_balls", "pack_key", "pack_tmhm", "item_submenu"}

-- Before SG.hooks(ctx): the pack-UI origins join the watched UI origins, the item submenu reads as a
-- menu and the catch-nickname prompt classifies (the U1 gate's in-memory preparation, same facts).
function R.prepare(ctx, SG, u1)
    for _, kind in ipairs(R.PACK_KINDS) do
        ctx.facts.ui_origins[kind] = assert(u1.pack_ui[kind], "SLINK_GEN2_U1_FACTS lacks " .. kind)
    end
    SG.MENU_KINDS.item_submenu = true
    local prompts = {}
    for _, source in ipairs({ctx.obs.prompts, ctx.prompts, u1.prompts}) do
        for k, v in pairs(source) do prompts[k] = v end
    end
    assert(prompts.catch_nickname, "SLINK_GEN2_U1_FACTS lacks the catch_nickname prompt")
    ctx.prompts = prompts
end

-- opts.captures() -> engine capture events the production client received (capture_party_finalized);
-- opts.reported() -> true once CAUGHT was printed. Returns driver, observe, host spec.
function R.new(ctx, SG, F, opts)
    local driver = F.driver(ctx.facts.maps.Route29)
    local base = SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        point.probe_hits = {capture_party=opts.captures()}
        if point.ui and point.ui.kind == "pack_balls" then point.ball_cursor = F.ball_cursor(SG.screen(ctx)) end
        -- The report gate: a finished catch stays in phase "battle" (F.driver idles while the overworld
        -- is not ready) until the capture went out on the wire.
        if driver.phase == "battle" and point.overworld_ready and opts.captures() >= 1 and not opts.reported() then
            point.overworld_ready = false
        end
        return point
    end
    local budget = F.BUDGET
    local spec = {name="duo-gen2-link", terminal=driver.terminal, terminal_idle=true,
                  max_frames=opts.max_frames or budget.max_frames,
                  max_phase_frames=math.min(opts.max_phase_frames or budget.max_phase_frames,
                                            opts.max_frames or budget.max_frames),
                  settle_frames=budget.settle_frames}
    return driver, observe, spec
end

return R
