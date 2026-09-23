-- lua/tests/gen3_title_syms.lua — per-title RAM/ROM addresses the scripted-play helpers need
-- (card C4-LG). FireRed and LeafGreen are the same pokefirered decomp built twice: every WRAM
-- data symbol below lands at the identical address in both .sym files (verified, not assumed —
-- see tests/unit/test_gen3_title_syms.py), but .text (code: task functions, CB2 callbacks)
-- shifts by a small fixed offset per title, because the two builds' data ahead of it in the
-- link order differ in size. Struct OFFSETS (not full addresses, e.g. "gSaveBlock1Ptr + 0x1C")
-- are NOT listed here: they come from a title-invariant struct layout (same pret header, same
-- source) and stay as plain Lua locals, cited in place, at each use site instead.
--
-- Each entry: { symbol = "<name in the .sym file>",
--   firered = <address>, leafgreen = <address>,   -- the FINAL value a caller should use
--   offset = <added to the symbol's own address before the result above, default 0>,
--   thumb = <true means the result above already has the Thumb bit (|1) applied, for a code
--            address used as a function-pointer VALUE (a task's .func, gMain.callback2, a
--            controller-func slot) rather than a jump target; default false>,
--   occurrence = <0-based index into every .sym line with this exact name, in ascending
--                 address order; default 0 — only needed for a name the object file reuses
--                 (sMenu: mon_markings.c's own unrelated sMenu sorts first; HandleInputChooseAction:
--                 one static copy per translation unit)> }
--
-- tests/unit/test_gen3_title_syms.py parses both data/gen3/pret/poke{firered,leafgreen}.sym and
-- asserts every firered/leafgreen value above equals (the Nth symbol address) + offset,
-- Thumb-bit included when thumb is set.

local M = {}

M.entries = {
    -- ── plaintext RAM observables (WRAM data — identical in both titles, verified) ───────────
    PARTY_COUNT_ADDR    = { symbol = "gPlayerPartyCount",       firered = 0x02024029, leafgreen = 0x02024029 },
    BATTLE_OUTCOME_ADDR = { symbol = "gBattleOutcome",          firered = 0x02023E8A, leafgreen = 0x02023E8A },
    BATTLE_RESULTS_ADDR = { symbol = "gBattleResults",          firered = 0x03004F90, leafgreen = 0x03004F90 },
    PARTY_BASE           = { symbol = "gPlayerParty",           firered = 0x02024284, leafgreen = 0x02024284 },
    BATTLER_CTRL_ADDR     = { symbol = "gBattlerControllerFuncs", firered = 0x03004FE0, leafgreen = 0x03004FE0 },
    ACTION_CURSOR_ADDR    = { symbol = "gActionSelectionCursor", firered = 0x02023FF8, leafgreen = 0x02023FF8 },
    OBJ_EVENTS_ADDR        = { symbol = "gObjectEvents",         firered = 0x02036E38, leafgreen = 0x02036E38 },
    GMAIN_CALLBACK2_ADDR   = { symbol = "gMain", offset = 0x04,  firered = 0x030030F4, leafgreen = 0x030030F4 },
    PARTY_MENU_ADDR        = { symbol = "gPartyMenu",            firered = 0x0203B0A0, leafgreen = 0x0203B0A0 },
    TASKS_BASE              = { symbol = "gTasks",                firered = 0x03005090, leafgreen = 0x03005090 },
    BAG_MENU_STATE_ADDR     = { symbol = "gBagMenuState",         firered = 0x0203ACFC, leafgreen = 0x0203ACFC },
    SPECIAL_VAR_ITEM_ID_ADDR = { symbol = "gSpecialVar_ItemId",   firered = 0x0203AD30, leafgreen = 0x0203AD30 },
    SAVEBLOCK2_PTR_ADDR       = { symbol = "gSaveBlock2Ptr",       firered = 0x0300500C, leafgreen = 0x0300500C },
    PC_RESULT                  = { symbol = "gSpecialVar_Result",   firered = 0x020370D0, leafgreen = 0x020370D0 },
    PC_CURSOR_AREA               = { symbol = "sCursorArea",         firered = 0x02039820, leafgreen = 0x02039820 },
    PC_CURSOR_POS                 = { symbol = "sCursorPosition",     firered = 0x02039821, leafgreen = 0x02039821 },
    PC_STORAGE_PTR                 = { symbol = "gStorage",            firered = 0x020397B0, leafgreen = 0x020397B0 },
    PC_DEPOSIT_BOX_ID               = { symbol = "sDepositBoxId",       firered = 0x020397B6, leafgreen = 0x020397B6 },
    SCRIPT_CONTEXT_STATUS_ADDR       = { symbol = "sGlobalScriptContextStatus",
                                          firered = 0x03000EA8, leafgreen = 0x03000EA8 },
    -- occurrence 1: pokemon_storage_system.c's sMenu. Occurrence 0 (0x020399C0) is
    -- mon_markings.c's unrelated sMenu pointer (the code at every use site already says so).
    PC_MENU_BASE = { symbol = "sMenu", occurrence = 1, firered = 0x0203ADE4, leafgreen = 0x0203ADE4 },

    -- ── code entry points used as function-POINTER VALUES (Thumb bit set; SHIFT per title) ───
    HANDLE_INPUT_CHOOSE_ACTION = { symbol = "HandleInputChooseAction", thumb = true,
                                    firered = 0x0802E439, leafgreen = 0x0802E439 },
    CB2_UPDATE_PARTY_MENU = { symbol = "CB2_UpdatePartyMenu", thumb = true,
                               firered = 0x0811EBA1, leafgreen = 0x0811EB79 },
    TASK_CHOOSE_MON = { symbol = "Task_HandleChooseMonInput", thumb = true,
                         firered = 0x0811FB29, leafgreen = 0x0811FB01 },
    TASK_RETURN_AFTER_TEXT = { symbol = "Task_ReturnToChooseMonAfterText", thumb = true,
                                firered = 0x081203B9, leafgreen = 0x08120391 },
    TASK_SELECTION_POPUP = { symbol = "Task_HandleSelectionMenuInput", thumb = true,
                              firered = 0x08122C5D, leafgreen = 0x08122C35 },
    CB2_BAG_MENU_RUN = { symbol = "CB2_BagMenuRun", thumb = true,
                          firered = 0x08107EE1, leafgreen = 0x08107EB9 },
    PC_MULTICHOICE = { symbol = "Task_MultichoiceMenu_HandleInput", thumb = true,
                        firered = 0x0809CC99, leafgreen = 0x0809CC6D },
    PC_MAIN_MENU = { symbol = "Task_PCMainMenu", thumb = true,
                      firered = 0x0808C39D, leafgreen = 0x0808C371 },
    PC_STORAGE_MAIN = { symbol = "Task_PokeStorageMain", thumb = true,
                         firered = 0x0808D2BD, leafgreen = 0x0808D291 },
    PC_ON_SELECTED = { symbol = "Task_OnSelectedMon", thumb = true,
                        firered = 0x0808D879, leafgreen = 0x0808D84D },
    PC_DEPOSIT_MENU = { symbol = "Task_DepositMenu", thumb = true,
                         firered = 0x0808DD89, leafgreen = 0x0808DD5D },
    PC_WITHDRAW_MON = { symbol = "Task_WithdrawMon", thumb = true,
                         firered = 0x0808DC9D, leafgreen = 0x0808DC71 },
    PC_RELEASE_MON = { symbol = "Task_ReleaseMon", thumb = true,
                        firered = 0x0808DECD, leafgreen = 0x0808DEA1 },
    PC_ON_B_PRESSED = { symbol = "Task_OnBPressed", thumb = true,
                         firered = 0x0808ECE5, leafgreen = 0x0808ECB9 },
}

local TITLES = { firered = true, leafgreen = true }

M.TITLES = TITLES

--- name -> address for `title`. Errors loudly (never a silent nil/0) for an unrecognized title
--- or a table entry missing that title's column — the "refuse by name" half of card C4-LG.
function M.for_title(title)
    if not TITLES[title] then
        error("gen3_title_syms: unknown title " .. tostring(title)
              .. " (want firered or leafgreen)", 0)
    end
    local out = {}
    for name, e in pairs(M.entries) do
        local addr = e[title]
        if not addr then
            error("gen3_title_syms: " .. name .. " (" .. e.symbol .. ") has no "
                  .. title .. " address", 0)
        end
        out[name] = addr
    end
    return out
end

return M
