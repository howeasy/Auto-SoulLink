-- Gen 2 fixture qualification driver. Pure point -> buttons/phase, the twin of gen2_scripted_play.lua:
-- no emulator globals, file IO, frame loops or memory writes. lua/tests/test_gen2_scripted_gate.lua
-- (SLINK_GEN2_QUALIFY) injects the observer and the shared lua/scripted_inputs.lua host.
--
--   boot / reload  title -> CONTINUE -> ConfirmContinue (A) -> the overworld          terminal "loaded"
--   resave         the same, then START -> SAVE -> YES ("save the game?") -> YES ("OK to overwrite?",
--                  same-player branch only) -> the native save completion           terminal "resaved"
--
-- Source: Continue/.Check1Pass/.Check2Pass/ConfirmContinue/Continue_CheckRTC_RestartClock/
-- FinishContinueFunction C engine/menus/intro_menu.asm:338-477, G :251-357. SaveMenu and
-- AskOverwriteSaveFile(.yoursavefile) C engine/menus/save.asm:1-19,181-203, G :1-19,169-191.
-- StartMenu_Save leaves the menu after a successful save (engine/menus/start_menu.asm:431-442).
-- Reaching a terminal is never qualification: tools/gen2_fixtures.py judges the GAME witness.
local Q = {}
local TERMINAL = {boot="loaded", reload="loaded", resave="resaved"}
local SITES = {"continue", "continue_loaded", "rtc_ok", "restart_clock", "finish_continue",
               "same_save_file", "erase_save"}

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

function Q.new(facts, qfacts, case)
    assert(type(facts) == "table" and facts.schema == "gen2-scripted-route-facts-v1", "source route facts required")
    assert(type(qfacts) == "table" and qfacts.schema == "gen2-qualify-facts-v1" and qfacts.title == facts.title
        and qfacts.route_facts_fingerprint == facts.fingerprint, "qualification facts differ from the route facts")
    assert(type(case) == "table" and case.title == facts.title and TERMINAL[case.stage] ~= nil,
        "selected qualification stage required")
    assert(type(case.attempt_id) == "string" and #case.attempt_id > 0, "attempt identity required")
    assert(type(case.stage_fingerprint) == "string" and case.stage_fingerprint:match("^%x+$")
        and #case.stage_fingerprint == 64, "stage fingerprint required")
    local self = {terminal=TERMINAL[case.stage], phase="title", qualified=false}
    local release, continued, loaded, save_counter = false, false, false, nil

    local function press(button)
        release = true
        return {[button]=true}, self.phase
    end
    local function choose(ui, wanted)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= 1 then
            return nil, "source menu geometry unavailable"
        end
        local target = nil
        for index, label in ipairs(ui.items) do
            if type(label) ~= "string" then return nil, "invalid menu label" end
            if string.upper(label) == wanted then
                if target then return nil, "ambiguous menu label" end
                target = index
            end
        end
        if not target then return nil, "required native menu item missing: " .. wanted end
        if target == ui.cursor then return press("A") end
        return press(target > ui.cursor and "Down" or "Up")
    end

    function self.step(point, frame)
        if type(point) ~= "table" or point.title ~= case.title or point.rom_sha1 ~= facts.rom_sha1
           or point.core_mode ~= "CGB" or point.attempt_id ~= case.attempt_id
           or point.facts_fingerprint ~= facts.fingerprint or point.stage_fingerprint ~= case.stage_fingerprint
           or not integer(frame, 0, math.huge) then
            return nil, "missing or foreign source-bound CGB observation"
        end
        local hits = point.hits
        if type(hits) ~= "table" then return nil, "code-site hit counts missing" end
        for _, id in ipairs(SITES) do
            if not integer(hits[id], 0, math.huge) then return nil, "code-site hit count missing: " .. id end
        end
        if hits.restart_clock > 0 then return nil, "RestartClock ran: the saved RTC was not accepted" end
        if hits.erase_save > 0 then return nil, "ErasePreviousSave ran: the save was treated as another file" end
        if release then release = false; return {}, self.phase end
        if self.phase == self.terminal then return {}, self.phase end
        if loaded and save_counter ~= nil and integer(point.save_success_counter, 0, math.huge)
           and point.save_success_counter > save_counter then
            self.phase = self.terminal
            return {}, self.phase
        end
        if point.ui ~= nil then
            local ui = point.ui
            local origin = type(ui) == "table" and (facts.ui_origins[ui.kind] or qfacts.ui_origins[ui.kind])
            if not origin or ui.origin ~= origin.symbol then return nil, "unmapped or unbound native UI state" end
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "title" then
                if continued then return nil, "unexpected reset to the title screen" end
                return press("Start")
            end
            if ui.kind == "main_menu" then
                if continued then return nil, "unexpected reset to main menu" end
                self.phase = "continue"
                return choose(ui, "CONTINUE")
            end
            if ui.kind == "continue_confirm" and not loaded then
                -- A continues, B backs out (ConfirmContinue); a missed A is re-pulsed by the gate cadence.
                continued = true
                self.phase = "continue"
                return press("A")
            end
            if case.stage == "resave" and loaded then
                if ui.kind == "start_menu" then self.phase = "save"; return choose(ui, "SAVE") end
                if ui.kind == "yes_no" and self.phase == "save" then
                    if ui.prompt == "save_confirm" then return choose(ui, "YES") end
                    if ui.prompt == "save_overwrite" then
                        if hits.same_save_file < 1 then return nil, "overwrite prompt is not the same-player branch" end
                        return choose(ui, "YES")
                    end
                    return nil, "unmapped yes/no prompt"
                end
            end
            return nil, "UI is not valid for qualification: " .. tostring(ui.kind)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        if point.battle_mode ~= 0 then return nil, "unexpected battle during qualification" end
        if not loaded then
            if not continued or hits.continue < 1 or hits.continue_loaded < 1 or hits.rtc_ok < 1
               or hits.finish_continue < 1 then
                return nil, "overworld reached without the native CONTINUE path"
            end
            loaded = true
            self.phase = "loaded"
            if case.stage ~= "resave" then return {}, self.phase end
        end
        self.phase = "save"
        if not integer(point.save_success_counter, 0, math.huge) then return nil, "native successful-save witness missing" end
        if save_counter == nil then save_counter = point.save_success_counter end
        return press("Start")
    end
    return self
end

function Q.run(host, observe, facts, qfacts, case, on_phase)
    assert(type(host) == "table" and type(host.run) == "function", "shared scripted-input host required")
    assert(type(observe) == "function", "qualified source-bound game observer required")
    local driver = Q.new(facts, qfacts, case)
    return host.run({name=case.name, terminal=driver.terminal, max_frames=case.max_frames,
        max_phase_frames=case.max_phase_frames, settle_frames=case.settle_frames, terminal_idle=true},
        function(frame)
            local point = observe()
            local buttons, phase = driver.step(point, frame)
            if buttons == nil then error(phase, 0) end
            return buttons, phase, point
        end, on_phase)
end

return Q
