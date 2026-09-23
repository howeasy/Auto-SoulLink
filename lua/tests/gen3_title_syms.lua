-- lua/tests/gen3_title_syms.lua — per-title RAM/ROM addresses the scripted-play helpers need
-- (card C4-LG, extended for radical_red by C4-LG2). FireRed and LeafGreen are the same
-- pokefirered decomp built twice: every WRAM data symbol below lands at the identical address in
-- both .sym files (verified, not assumed — see tests/unit/test_gen3_title_syms.py), but .text
-- (code: task functions, CB2 callbacks) shifts by a small fixed offset per title, because the two
-- builds' data ahead of it in the link order differ in size. Struct OFFSETS (not full addresses,
-- e.g. "gSaveBlock1Ptr + 0x1C") are NOT listed here: they come from a title-invariant struct
-- layout (same pret header, same source) and stay as plain Lua locals, cited in place, at each
-- use site instead.
--
-- radical_red has NO pret .sym of its own (RR is a hand-patched hack of the FR ROM, not a
-- separate pret source tree — pokefirered.sym is the only .sym file that ever describes it).
-- Every `radical_red` value below is therefore NOT verified against a .sym file; it is proven,
-- entry by entry, by a `rr_source` citation instead, to one of:
--   * a ROM byte anchor (tools/pin_gen3_site.py style, or a research note that read
--     patch/build/slink_RR.gba directly and compared bytes against FireRed's), or
--   * an old-client RR address already carrying live traffic ("old-client RR
--     (production-tested): file:line" — lua/games/gen3_frlge.lua's radical_red profile, or a
--     duo-precedent constant already read/written by a live RR run), or
--   * docs/gen3/research/rr_pc_menu.md, which cross-checked several PC task addresses against
--     the ROM directly.
-- An entry with NO radical_red value is left ABSENT on purpose: `M.for_title("radical_red")`
-- omits it from the returned table rather than guessing or erroring, so a helper that reads it
-- gets a plain nil (never a wrong number) and fails at the point it is actually used, not at
-- module load. test_gen3_title_syms.py asserts every radical_red entry carries an `rr_source`.
--
-- Each entry: { symbol = "<name in the .sym file>",
--   firered = <address>, leafgreen = <address>,   -- the FINAL value a caller should use
--   radical_red = <address>,                       -- optional; see above
--   rr_source = "<citation>",                       -- required whenever radical_red is set
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
-- Thumb-bit included when thumb is set (radical_red is checked by rr_source presence only, since
-- there is no .sym file to check it against).

local M = {}

local RR_OLD_CLIENT = "old-client RR (production-tested): lua/games/gen3_frlge.lua:"
local RR_DUO_PRECEDENT = "old-client RR (production-tested): lua/tests/probe_gen3_rr_bag.lua:29 "
                       .. "(duo-precedent constant from scenario_explode.lua)"
local RR_PC_MENU_MD = "docs/gen3/research/rr_pc_menu.md:"

M.entries = {
    -- ── plaintext RAM observables (WRAM data — identical in FR/LG, verified) ─────────────────
    PARTY_COUNT_ADDR    = { symbol = "gPlayerPartyCount",       firered = 0x02024029, leafgreen = 0x02024029,
                             radical_red = 0x02024029, rr_source = RR_OLD_CLIENT .. "207" },
    BATTLE_OUTCOME_ADDR = { symbol = "gBattleOutcome",          firered = 0x02023E8A, leafgreen = 0x02023E8A,
                             radical_red = 0x02023E8A, rr_source = RR_OLD_CLIENT .. "215" },
    BATTLE_RESULTS_ADDR = { symbol = "gBattleResults",          firered = 0x03004F90, leafgreen = 0x03004F90,
                             radical_red = 0x03004F90, rr_source = RR_OLD_CLIENT .. "384 (\"preserved "
                                                                 .. "verbatim by CFRU\")" },
    PARTY_BASE           = { symbol = "gPlayerParty",           firered = 0x02024284, leafgreen = 0x02024284,
                              radical_red = 0x02024284, rr_source = RR_OLD_CLIENT .. "208" },
    BATTLER_CTRL_ADDR     = { symbol = "gBattlerControllerFuncs", firered = 0x03004FE0, leafgreen = 0x03004FE0,
                               radical_red = 0x03004FE0, rr_source = RR_DUO_PRECEDENT },
    -- ACTION_CURSOR_ADDR (gActionSelectionCursor): NOT proven for RR. duo_gen3_main.lua's own
    -- comment (its separate SYMS table, ~:119-125) says reusing the FR .sym value for this one
    -- is "the best-supported available choice, not a confirmed fact" -- exactly the ABSENT case.
    ACTION_CURSOR_ADDR    = { symbol = "gActionSelectionCursor", firered = 0x02023FF8, leafgreen = 0x02023FF8 },
    -- OBJ_EVENTS_ADDR (gObjectEvents): no RR citation found (no ROM anchor, no old-client use, not
    -- in rr_pc_menu.md). ABSENT.
    OBJ_EVENTS_ADDR        = { symbol = "gObjectEvents",         firered = 0x02036E38, leafgreen = 0x02036E38 },
    GMAIN_CALLBACK2_ADDR   = { symbol = "gMain", offset = 0x04,  firered = 0x030030F4, leafgreen = 0x030030F4,
                                radical_red = 0x030030F4, rr_source = RR_PC_MENU_MD .. "63 (\"gMain.callback2 "
                                                                   .. "u32 030030F4\")" },
    -- PARTY_MENU_ADDR (gPartyMenu) / CB2_UPDATE_PARTY_MENU below: no RR citation. ABSENT.
    PARTY_MENU_ADDR        = { symbol = "gPartyMenu",            firered = 0x0203B0A0, leafgreen = 0x0203B0A0 },
    TASKS_BASE              = { symbol = "gTasks",                firered = 0x03005090, leafgreen = 0x03005090,
                                 radical_red = 0x03005090, rr_source = RR_OLD_CLIENT .. "372, cross-checked "
                                                                    .. "by " .. RR_PC_MENU_MD .. "36 (RR ROM "
                                                                    .. "literal at ShowPokemonStorageSystemPC's "
                                                                    .. "constructor)" },
    -- BAG_MENU_STATE_ADDR/SPECIAL_VAR_ITEM_ID_ADDR: CFRU replaces the bag UI entirely
    -- (probe_gen3_rr_bag.lua's own header: "the FR driver's Right -> B_ACTION_USE_ITEM toggle
    -- does not carry over"), so the FR gBagMenuState-based flow does not apply at all. ABSENT.
    BAG_MENU_STATE_ADDR     = { symbol = "gBagMenuState",         firered = 0x0203ACFC, leafgreen = 0x0203ACFC },
    SPECIAL_VAR_ITEM_ID_ADDR = { symbol = "gSpecialVar_ItemId",   firered = 0x0203AD30, leafgreen = 0x0203AD30 },
    SAVEBLOCK2_PTR_ADDR       = { symbol = "gSaveBlock2Ptr",       firered = 0x0300500C, leafgreen = 0x0300500C,
                                   -- DIFFERS from FR/LG: CFRU relocated gSaveBlock2Ptr.
                                   radical_red = 0x03003838, rr_source = RR_OLD_CLIENT .. "265 (SB2_PTR_ADDR)" },
    -- PC_RESULT/PC_CURSOR_AREA/PC_CURSOR_POS/PC_STORAGE_PTR/PC_DEPOSIT_BOX_ID/PC_MENU_BASE: the
    -- PC's storage backend is CFRU's own (25 compressed boxes via sPokemonBoxPtrs, not pret's
    -- gStorage), and rr_pc_menu.md:65 says explicitly: FR's sCursorArea/sCursorPosition/
    -- sDepositBoxId/gStorage are "candidate RR instrumentation, not fully rebound" and "do not
    -- guess a gStorage structure offset". ABSENT.
    PC_RESULT                  = { symbol = "gSpecialVar_Result",   firered = 0x020370D0, leafgreen = 0x020370D0 },
    PC_CURSOR_AREA               = { symbol = "sCursorArea",         firered = 0x02039820, leafgreen = 0x02039820 },
    PC_CURSOR_POS                 = { symbol = "sCursorPosition",     firered = 0x02039821, leafgreen = 0x02039821 },
    PC_STORAGE_PTR                 = { symbol = "gStorage",            firered = 0x020397B0, leafgreen = 0x020397B0 },
    PC_DEPOSIT_BOX_ID               = { symbol = "sDepositBoxId",       firered = 0x020397B6, leafgreen = 0x020397B6 },
    SCRIPT_CONTEXT_STATUS_ADDR       = { symbol = "sGlobalScriptContextStatus",
                                          firered = 0x03000EA8, leafgreen = 0x03000EA8,
                                          radical_red = 0x03000EA8, rr_source = RR_PC_MENU_MD .. "64 (RR "
                                                                             .. "checkpoint predicate)" },
    -- occurrence 1: pokemon_storage_system.c's sMenu. Occurrence 0 (0x020399C0) is
    -- mon_markings.c's unrelated sMenu pointer (the code at every use site already says so).
    -- No RR citation (see the PC_STORAGE_PTR block above). ABSENT.
    PC_MENU_BASE = { symbol = "sMenu", occurrence = 1, firered = 0x0203ADE4, leafgreen = 0x0203ADE4 },

    -- ── code entry points used as function-POINTER VALUES (Thumb bit set; SHIFT per title) ───
    HANDLE_INPUT_CHOOSE_ACTION = { symbol = "HandleInputChooseAction", thumb = true,
                                    firered = 0x0802E439, leafgreen = 0x0802E439,
                                    radical_red = 0x0802E439, rr_source = RR_DUO_PRECEDENT },
    -- CB2_UPDATE_PARTY_MENU/TASK_CHOOSE_MON/TASK_RETURN_AFTER_TEXT/TASK_SELECTION_POPUP/
    -- CB2_BAG_MENU_RUN/PC_MULTICHOICE/PC_STORAGE_MAIN/PC_ON_SELECTED/PC_RELEASE_MON/
    -- PC_ON_B_PRESSED: no ROM anchor, no old-client use, not in rr_pc_menu.md. ABSENT.
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
    -- The bag's input gates (pret src/item_menu.c:1044-1049): Task_BagMenu_HandleInput reads
    -- no press while the palette fade or Task_AnimateWin0v runs. Verified against both .sym
    -- files (pokefirered.sym:10212/10205, pokeleafgreen.sym:10214/10207). No RR value: ABSENT.
    TASK_BAG_MENU_HANDLE_INPUT = { symbol = "Task_BagMenu_HandleInput", thumb = true,
                                    firered = 0x08108F0D, leafgreen = 0x08108EE5 },
    TASK_ANIMATE_WIN0V = { symbol = "Task_AnimateWin0v", thumb = true,
                            firered = 0x08108CFD, leafgreen = 0x08108CD5 },
    PC_MULTICHOICE = { symbol = "Task_MultichoiceMenu_HandleInput", thumb = true,
                        firered = 0x0809CC99, leafgreen = 0x0809CC6D },
    -- pret ROM address unchanged in RR (rr_pc_menu.md:29,36: only two 8-byte windows patched
    -- inside the function body; the function itself was not relocated).
    PC_MAIN_MENU = { symbol = "Task_PCMainMenu", thumb = true,
                      firered = 0x0808C39D, leafgreen = 0x0808C371,
                      radical_red = 0x0808C39D, rr_source = RR_PC_MENU_MD .. "29,36" },
    PC_STORAGE_MAIN = { symbol = "Task_PokeStorageMain", thumb = true,
                         firered = 0x0808D2BD, leafgreen = 0x0808D291 },
    PC_ON_SELECTED = { symbol = "Task_OnSelectedMon", thumb = true,
                        firered = 0x0808D879, leafgreen = 0x0808D84D },
    -- pret ROM address unchanged in RR (rr_pc_menu.md:29: "retained ... byte-for-byte in direct
    -- comparisons against FireRed").
    PC_DEPOSIT_MENU = { symbol = "Task_DepositMenu", thumb = true,
                         firered = 0x0808DD89, leafgreen = 0x0808DD5D,
                         radical_red = 0x0808DD89, rr_source = RR_PC_MENU_MD .. "29" },
    -- pret ROM address unchanged in RR (rr_pc_menu.md:80 coordinator census: Task_WithdrawMon
    -- starts at the same 0x0808DC9C as FR's .sym).
    PC_WITHDRAW_MON = { symbol = "Task_WithdrawMon", thumb = true,
                         firered = 0x0808DC9D, leafgreen = 0x0808DC71,
                         radical_red = 0x0808DC9D, rr_source = RR_PC_MENU_MD .. "80" },
    PC_RELEASE_MON = { symbol = "Task_ReleaseMon", thumb = true,
                        firered = 0x0808DECD, leafgreen = 0x0808DEA1 },
    PC_ON_B_PRESSED = { symbol = "Task_OnBPressed", thumb = true,
                         firered = 0x0808ECE5, leafgreen = 0x0808ECB9 },

    -- ── witnesses for the scripted NEW GAME intro (card C4-LGF2, coordinator steer) ───────────
    -- Replace gen3_fr_newgame_inputs.lua's old fixed-frame-count waits (tuned once on FR,
    -- silently wrong on LG -- same screens, different elapsed frames) with RAM witnesses, the
    -- same "wait for the engine's own task/callback2, never a frame guess" shape c1507b7d
    -- already established for the START-menu SAVE row. No RR citation: Radical Red is not
    -- driven by this script (its fixture is an imported real save, gen3_fr_newgame_inputs.lua's
    -- own header). ABSENT for radical_red.
    TASK_OAKSPEECH_GENDER_INPUT = { symbol = "Task_OakSpeech_HandleGenderInput", thumb = true,
                                     firered = 0x0812FFA5, leafgreen = 0x0812FF7D },
    -- CB2_NamingScreen (DoNamingScreen's own run callback): reused for BOTH the player-name and
    -- rival-name screens in the intro -- there is no separate constant per screen, so the
    -- caller tells them apart by ORDER (first activation = player, second = rival), not by
    -- address.
    CB2_NAMING_SCREEN = { symbol = "CB2_NamingScreen", thumb = true,
                          firered = 0x0809FB71, leafgreen = 0x0809FB45 },
    -- Task_YesNoMenu_HandleInput: the generic Yes/No confirm task every ScriptMenu_YesNo box
    -- uses (src/script_menu.c), including the starter-nickname decline this same file's
    -- "starter" leg drives. One address serves every Yes/No box in the game; which box is open
    -- is not disambiguated by this witness alone (callers know from their own leg context).
    TASK_YES_NO_MENU = { symbol = "Task_YesNoMenu_HandleInput", thumb = true,
                         firered = 0x0809CE55, leafgreen = 0x0809CE29 },
}

local TITLES = { firered = true, leafgreen = true, radical_red = true }

M.TITLES = TITLES

--- name -> address for `title`, for every entry that HAS one. Errors loudly (never a silent
--- nil/0) only for an unrecognized title. A recognized title missing one entry's column is not
--- an error: that entry is simply omitted from the result, so a caller reading a plain Lua field
--- (S.FOO) gets nil and fails wherever it actually tries to use FOO -- never at module load, and
--- never with a wrong number silently standing in (card C4-LG2: radical_red has several entries
--- nobody has proven yet; see the ABSENT notes above each one).
function M.for_title(title)
    if not TITLES[title] then
        error("gen3_title_syms: unknown title " .. tostring(title)
              .. " (want firered, leafgreen or radical_red)", 0)
    end
    local out = {}
    for name, e in pairs(M.entries) do
        local addr = e[title]
        if addr then out[name] = addr end
    end
    return out
end

return M
