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
-- emerald (card E2-SYMS) DOES have its own pret .sym (pokeemerald is a separate decomp, not a
-- patched FR ROM like radical_red), so every `emerald` value below IS verified against
-- data/gen3/pret/pokeemerald.sym, the same way firered/leafgreen are. An entry with no Emerald
-- equivalent (a genuinely FR/LG-only concept, or an architecture the pokeemerald source rebuilt
-- differently -- e.g. the START menu's gMenuCallback design replacing Task_StartMenuHandleInput's
-- gTasks-based one) is `emerald = nil`, with a comment citing the pret source that shows there is
-- no 1:1 symbol, exactly like the `firered`/`leafgreen`-only entries already do for radical_red.
-- A handful of entries are RENAMED rather than absent in Emerald (SendMonToPC-style: same
-- function, new name) -- gStorage/sStorage, Task_MultichoiceMenu_HandleInput/
-- Task_HandleMultichoiceInput, Task_YesNoMenu_HandleInput/Task_HandleYesNoInput -- so those carry
-- an `emerald_symbol` override (see below). One entry (PC_MENU_BASE's `sMenu`) also needs an
-- `emerald_occurrence` override: pokeemerald's link order gives sMenu one more static hit than
-- FR/LG's, so the Nth-occurrence index shifts even though the symbol name didn't change.
--
-- Each entry: { symbol = "<name in the .sym file>",
--   firered = <address>, leafgreen = <address>,   -- the FINAL value a caller should use
--   radical_red = <address>,                       -- optional; see above
--   rr_source = "<citation>",                       -- required whenever radical_red is set
--   emerald = <address> or nil,                     -- optional; see above (verified against .sym)
--   emerald_symbol = "<name>",                      -- optional override of `symbol`, when Emerald
--                                                    -- renamed the function/variable
--   emerald_occurrence = <n>,                        -- optional override of `occurrence`, when
--                                                    -- Emerald's link order changed which hit is Nth
--   offset = <added to the symbol's own address before the result above, default 0>,
--   thumb = <true means the result above already has the Thumb bit (|1) applied, for a code
--            address used as a function-pointer VALUE (a task's .func, gMain.callback2, a
--            controller-func slot) rather than a jump target; default false>,
--   occurrence = <0-based index into every .sym line with this exact name, in ascending
--                 address order; default 0 — only needed for a name the object file reuses
--                 (sMenu: mon_markings.c's own unrelated sMenu sorts first; HandleInputChooseAction:
--                 one static copy per translation unit)> }
--
-- tests/unit/test_gen3_title_syms.py parses data/gen3/pret/poke{firered,leafgreen,emerald}.sym and
-- asserts every firered/leafgreen/emerald value above equals (the Nth symbol address) + offset,
-- Thumb-bit included when thumb is set (radical_red is checked by rr_source presence only, since
-- there is no .sym file to check it against). The Nth symbol/occurrence for emerald uses
-- emerald_symbol/emerald_occurrence when present, else falls back to symbol/occurrence.

local M = {}

local RR_OLD_CLIENT = "old-client RR (production-tested): lua/games/gen3_frlge.lua:"
local RR_DUO_PRECEDENT = "old-client RR (production-tested): lua/tests/probe_gen3_rr_bag.lua:29 "
                       .. "(duo-precedent constant from scenario_explode.lua)"
local RR_PC_MENU_MD = "docs/gen3/research/rr_pc_menu.md:"
-- G5-RR-BATTERY-2: the harness words proven by FR-referrer retention (every FR literal-pool word
-- holding the value is still at the same ROM address in RR, clean and companion) -- the
-- evidence, hashes and derivation command live in the note, not here.
-- The hand-off pair has no FR literal to keep (FR reaches ExecCompleted by bl): its RR proof is
-- the CFRU action menu's own pool word and the ExecCompleted hook (parity scope §3.2).
local RR_HANDOFF = "docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md §3.2 (LDR@0x090A9EFE = "
                   .. "0x0802E33D; the ExecCompleted hook 0x0904459A stores 0x0802E3B5)"
local RR_HARNESS = "docs/gen3/research/rr_harness_syms_2026-09-24.md (FR referrers kept in RR; "
                   .. "tools/research/rr_harness_syms.py --check)"

M.entries = {
    -- ── plaintext RAM observables (WRAM data — identical in FR/LG, verified) ─────────────────
    PARTY_COUNT_ADDR    = { symbol = "gPlayerPartyCount",       firered = 0x02024029, leafgreen = 0x02024029,
                             radical_red = 0x02024029, rr_source = RR_OLD_CLIENT .. "207",
                             emerald = 0x020244E9 },
    BATTLE_OUTCOME_ADDR = { symbol = "gBattleOutcome",          firered = 0x02023E8A, leafgreen = 0x02023E8A,
                             radical_red = 0x02023E8A, rr_source = RR_OLD_CLIENT .. "215",
                             emerald = 0x0202433A },
    BATTLE_RESULTS_ADDR = { symbol = "gBattleResults",          firered = 0x03004F90, leafgreen = 0x03004F90,
                             radical_red = 0x03004F90, rr_source = RR_OLD_CLIENT .. "384 (\"preserved "
                                                                 .. "verbatim by CFRU\")",
                             emerald = 0x03005D10 },
    PARTY_BASE           = { symbol = "gPlayerParty",           firered = 0x02024284, leafgreen = 0x02024284,
                              radical_red = 0x02024284, rr_source = RR_OLD_CLIENT .. "208",
                             emerald = 0x020244EC },
    BATTLER_CTRL_ADDR     = { symbol = "gBattlerControllerFuncs", firered = 0x03004FE0, leafgreen = 0x03004FE0,
                               radical_red = 0x03004FE0, rr_source = RR_DUO_PRECEDENT,
                             emerald = 0x03005D60 },
    -- ACTION_CURSOR_ADDR (gActionSelectionCursor): proven for RR from the bytes (G5-RR-CPU-IRQ):
    -- CFRU's action menu (0x090A9EA0) loads 0x02023FF8 (LDR@0x090A9ED8, 0x090A9FE2, 0x090AA00C,
    -- 0x090AA026, 0x090AA078; fact in tools/research/rr_active_faint.py), indexes it by
    -- gActiveBattler (ldrb r0,[r6,r3] @0x090A9F1A), and on A switches on it (cmp #3; case_uqi
    -- @0x090A9F20), case 0 emitting B_ACTION_USE_MOVE -- FR's 0 FIGHT / 1 BAG / 2 PKMN / 3 RUN.
    ACTION_CURSOR_ADDR    = { symbol = "gActionSelectionCursor", firered = 0x02023FF8, leafgreen = 0x02023FF8,
                              radical_red = 0x02023FF8,
                              rr_source = "docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md "
                                  .. "§3.1 (CFRU action menu) + ROM LDR@0x090A9ED8 = 0x02023FF8",
                             emerald = 0x020244AC },
    -- OBJ_EVENTS_ADDR (gObjectEvents): no RR citation found (no ROM anchor, no old-client use, not
    -- in rr_pc_menu.md). ABSENT.
    OBJ_EVENTS_ADDR        = { symbol = "gObjectEvents",         firered = 0x02036E38, leafgreen = 0x02036E38,
                             emerald = 0x02037350 },
    GMAIN_CALLBACK2_ADDR   = { symbol = "gMain", offset = 0x04,  firered = 0x030030F4, leafgreen = 0x030030F4,
                                radical_red = 0x030030F4, rr_source = RR_PC_MENU_MD .. "63 (\"gMain.callback2 "
                                                                   .. "u32 030030F4\")",
                             emerald = 0x030022C4 },
    -- The in-battle party menu on RR: the note (RR_HARNESS) has the evidence (G5-RR-ORACLES).
    PARTY_MENU_ADDR        = { symbol = "gPartyMenu",            firered = 0x0203B0A0, leafgreen = 0x0203B0A0,
                               radical_red = 0x0203B0A0, rr_source = RR_HARNESS,
                             emerald = 0x0203CEC8 },
    TASKS_BASE              = { symbol = "gTasks",                firered = 0x03005090, leafgreen = 0x03005090,
                                 radical_red = 0x03005090, rr_source = RR_OLD_CLIENT .. "372, cross-checked "
                                                                    .. "by " .. RR_PC_MENU_MD .. "36 (RR ROM "
                                                                    .. "literal at ShowPokemonStorageSystemPC's "
                                                                    .. "constructor)",
                             emerald = 0x03005E00 },
    -- BAG_MENU_STATE_ADDR/SPECIAL_VAR_ITEM_ID_ADDR: CFRU replaces the bag UI entirely
    -- (probe_gen3_rr_bag.lua's own header: "the FR driver's Right -> B_ACTION_USE_ITEM toggle
    -- does not carry over"), so the FR gBagMenuState-based flow does not apply at all. ABSENT.
    -- emerald = nil: not a rename. pokeemerald src/item_menu.c#L546 has "EWRAM_DATA struct BagMenu
    -- *gBagMenu = 0" -- a differently-named, differently-typed (heap pointer, not the FR/LG plain
    -- struct BagStruct gBagMenuState instance) global. No 1:1 address a caller could substitute.
    BAG_MENU_STATE_ADDR     = { symbol = "gBagMenuState",         firered = 0x0203ACFC, leafgreen = 0x0203ACFC,
        radical_red = 0x0203ACFC, rr_source = RR_HARNESS, emerald = nil },
    SPECIAL_VAR_ITEM_ID_ADDR = { symbol = "gSpecialVar_ItemId",   firered = 0x0203AD30, leafgreen = 0x0203AD30,
        radical_red = 0x0203AD30, rr_source = RR_HARNESS,
                             emerald = 0x0203CE7C },
    SAVEBLOCK2_PTR_ADDR       = { symbol = "gSaveBlock2Ptr",       firered = 0x0300500C, leafgreen = 0x0300500C,
                                   -- DIFFERS from FR/LG: CFRU relocated gSaveBlock2Ptr.
                                   radical_red = 0x03003838, rr_source = RR_OLD_CLIENT .. "265 (SB2_PTR_ADDR)",
                             emerald = 0x03005D90 },
    -- PC_RESULT/PC_CURSOR_AREA/PC_CURSOR_POS/PC_STORAGE_PTR/PC_DEPOSIT_BOX_ID/PC_MENU_BASE: the
    -- PC's box BACKEND is CFRU's own (25 compressed boxes), but rr_pc_menu.md:65's "candidate RR
    -- instrumentation, not fully rebound" is closed by the harness note (RR_HARNESS): every FR
    -- code site that loads each of these words is still at the same ROM address in RR -- the
    -- storage UI that reads them is FR's (gStorage: all 339 FR sites kept). The harness still
    -- guesses no gStorage structure offset beyond the ones those kept sites use.
    PC_RESULT                  = { symbol = "gSpecialVar_Result",   firered = 0x020370D0, leafgreen = 0x020370D0,
        radical_red = 0x020370D0, rr_source = RR_HARNESS,
                             emerald = 0x020375F0 },
    PC_CURSOR_AREA               = { symbol = "sCursorArea",         firered = 0x02039820, leafgreen = 0x02039820,
        radical_red = 0x02039820, rr_source = RR_HARNESS,
                             emerald = 0x02039D78 },
    PC_CURSOR_POS                 = { symbol = "sCursorPosition",     firered = 0x02039821, leafgreen = 0x02039821,
        radical_red = 0x02039821, rr_source = RR_HARNESS,
                             emerald = 0x02039D79 },
    -- emerald renames gStorage -> sStorage (pret pokeemerald src/pokemon_storage_system.c#L564:
    -- "EWRAM_DATA static struct PokemonStorageSystemData *sStorage = NULL", the same UI struct
    -- FR/LG expose as the global gStorage).
    PC_STORAGE_PTR                 = { symbol = "gStorage",            firered = 0x020397B0, leafgreen = 0x020397B0,
        radical_red = 0x020397B0, rr_source = RR_HARNESS,
                             emerald_symbol = "sStorage", emerald = 0x02039D08 },
    PC_DEPOSIT_BOX_ID               = { symbol = "sDepositBoxId",       firered = 0x020397B6, leafgreen = 0x020397B6,
        radical_red = 0x020397B6, rr_source = RR_HARNESS,
                             emerald = 0x02039D0E },
    SCRIPT_CONTEXT_STATUS_ADDR       = { symbol = "sGlobalScriptContextStatus",
                                          firered = 0x03000EA8, leafgreen = 0x03000EA8,
                                          radical_red = 0x03000EA8, rr_source = RR_PC_MENU_MD .. "64 (RR "
                                                                             .. "checkpoint predicate)",
                             emerald = 0x03000E38 },
    -- occurrence 1: pokemon_storage_system.c's sMenu. Occurrence 0 (0x020399C0) is
    -- mon_markings.c's unrelated sMenu pointer (the code at every use site already says so).
    -- Emerald has a THIRD static "sMenu" pret doesn't have in FR/LG (src/use_pokeblock.c#L172,
    -- a pointer, alongside mon_markings.c's and menu.c's), so ascending-address occurrence shifts:
    -- data/gen3/pret/pokeemerald.sym has sMenu at 0x0203A124 (4B), 0x0203BCAC (4B), 0x0203CD90
    -- (0xC bytes) -- only the last is menu.c's struct Menu (size 0xC, matching FR/LG's occurrence-1
    -- symbol exactly), so emerald_occurrence = 2.
    PC_MENU_BASE = { symbol = "sMenu", occurrence = 1, firered = 0x0203ADE4, leafgreen = 0x0203ADE4,
        radical_red = 0x0203ADE4, rr_source = RR_HARNESS,
                             emerald_occurrence = 2, emerald = 0x0203CD90 },

    -- ── code entry points used as function-POINTER VALUES (Thumb bit set; SHIFT per title) ───
    HANDLE_INPUT_CHOOSE_ACTION = { symbol = "HandleInputChooseAction", thumb = true,
                                    firered = 0x0802E439, leafgreen = 0x0802E439,
                                    radical_red = 0x0802E439, rr_source = RR_DUO_PRECEDENT,
                             emerald = 0x08057589 },
    -- PC_MULTICHOICE/PC_STORAGE_MAIN/PC_ON_SELECTED/PC_RELEASE_MON/PC_ON_B_PRESSED: no ROM
    -- anchor, no old-client use, not in rr_pc_menu.md. ABSENT.
    -- (The four party-menu words below carry RR values: see the party-menu note above.)
    -- Battle-controller / bag / PC words on RR: the note (RR_HARNESS) has the evidence.
    CB2_UPDATE_PARTY_MENU = { symbol = "CB2_UpdatePartyMenu", thumb = true,
                               firered = 0x0811EBA1, leafgreen = 0x0811EB79,
                               radical_red = 0x0811EBA1, rr_source = RR_HARNESS,
                             emerald = 0x081B01B1 },
    TASK_CHOOSE_MON = { symbol = "Task_HandleChooseMonInput", thumb = true,
                         firered = 0x0811FB29, leafgreen = 0x0811FB01,
                         radical_red = 0x0811FB29, rr_source = RR_HARNESS,
                             emerald = 0x081B1371 },
    TASK_RETURN_AFTER_TEXT = { symbol = "Task_ReturnToChooseMonAfterText", thumb = true,
                                firered = 0x081203B9, leafgreen = 0x08120391,
                                radical_red = 0x081203B9, rr_source = RR_HARNESS,
                             emerald = 0x081B1C1D },
    TASK_SELECTION_POPUP = { symbol = "Task_HandleSelectionMenuInput", thumb = true,
                              firered = 0x08122C5D, leafgreen = 0x08122C35,
                              radical_red = 0x08122C5D, rr_source = RR_HARNESS,
                             emerald = 0x081B3731 },
    CB2_BAG_MENU_RUN = { symbol = "CB2_BagMenuRun", thumb = true,
                          firered = 0x08107EE1, leafgreen = 0x08107EB9,
                          radical_red = 0x08107EE1, rr_source = RR_HARNESS,
                             emerald = 0x081AAD5D },
    -- The bag's input gates (pret src/item_menu.c:1044-1049): Task_BagMenu_HandleInput reads
    -- no press while the palette fade or Task_AnimateWin0v runs. Verified against both .sym
    -- files (pokefirered.sym:10212/10205, pokeleafgreen.sym:10214/10207). No RR value: ABSENT.
    TASK_BAG_MENU_HANDLE_INPUT = { symbol = "Task_BagMenu_HandleInput", thumb = true,
                                    firered = 0x08108F0D, leafgreen = 0x08108EE5,
                                    radical_red = 0x08108F0D, rr_source = RR_HARNESS,
                             emerald = 0x081ABD29 },
    -- emerald = nil: no equivalent. pret pokeemerald src/item_menu.c's bag pocket-switch scroll
    -- (tPocketSwitchState/tPocketSwitchTimer/tPocketSwitchDir, :665-667) runs inline in the main
    -- bag task instead of spawning a separate sub-task the way FR/LG's Task_AnimateWin0v does --
    -- grepping src/item_menu.c for Win0/AnimateWin finds nothing.
    TASK_ANIMATE_WIN0V = { symbol = "Task_AnimateWin0v", thumb = true,
                            firered = 0x08108CFD, leafgreen = 0x08108CD5,
                            radical_red = 0x08108CFD, rr_source = RR_HARNESS, emerald = nil },
    -- card E2-CATCH-LEG: Emerald's own battle-bag ball throw. The mirror image of
    -- BAG_MENU_STATE_ADDR/TASK_BAG_MENU_HANDLE_INPUT's `emerald = nil` above -- these three are
    -- genuinely Emerald-only (firered = leafgreen = nil), a real architecture split, not a rename.
    -- docs/gen3_emerald/research/battle_bag_ball_throw_2026-09-25.md is the spot-checked research
    -- note; every address here was independently re-verified against pokeemerald.sym for this card.
    -- firered/leafgreen = nil: pret pokefirered/pokeleafgreen have no `gBagPosition` global at all
    -- (grep of both .sym files: zero hits) -- FR/LG's bag position is gBagMenuState
    -- (BAG_MENU_STATE_ADDR above), a differently-typed static struct, not this one renamed.
    BAG_POSITION_ADDR = { symbol = "gBagPosition", firered = nil, leafgreen = nil,
                           emerald = 0x0203CE58 },
    -- struct BagMenu *gBagMenu (include/item_menu.h:61-86): a heap pointer, unlike FR/LG's own
    -- gBagMenuState (a static struct instance, not a pointer) -- see BAG_MENU_STATE_ADDR's own
    -- comment. firered/leafgreen = nil: no symbol of this name in either .sym file.
    BAG_MENU_PTR_ADDR = { symbol = "gBagMenu", firered = nil, leafgreen = nil,
                          emerald = 0x0203CE54 },
    -- src/item_menu.c:1679-1688 (Task_ItemContext_Normal picks Task_ItemContext_SingleRow when
    -- contextMenuNumItems <= 2 -- the in-battle USE/CANCEL popup, sContextMenuItems_BattleUse,
    -- always has exactly 2). One hit in pokeemerald.sym. firered/leafgreen = nil: grep of both
    -- .sym files finds no symbol of this name -- FR/LG's context-menu task, if any, is not chased
    -- down by this card (out of lease scope; the FR ball-throw precedent, throw_pokeball_from_bag,
    -- never asserts a task func before its confirm A, only Emerald's helper does).
    TASK_ITEM_CONTEXT_SINGLE_ROW = { symbol = "Task_ItemContext_SingleRow", thumb = true,
                                     firered = nil, leafgreen = nil, emerald = 0x081ACC05 },
    -- BattleMainCB2 (src/battle_main.c:4413): the in-battle main callback2, resumed once the bag
    -- closes and the chosen action (the ball throw) commits. Exists identically in all three pret
    -- trees (verified against every .sym file, not a title-only concept like the three above).
    BATTLE_MAIN_CB2 = { symbol = "BattleMainCB2", thumb = true,
                        firered = 0x08011101, leafgreen = 0x08011101,
                        emerald = 0x08038421 },
    -- gLastUsedItem (src/battle_util.c:318-322 HandleAction_UseItem): set from the battle buffer
    -- before dispatching to gBattlescriptsForBallThrow -- the throw-committed witness, paired with
    -- "no bag task left" (BATTLE_MAIN_CB2 above) per the research note's step 8.
    LAST_USED_ITEM_ADDR = { symbol = "gLastUsedItem", firered = 0x02023D68, leafgreen = 0x02023D68,
                            emerald = 0x02024208 },
    ACTIVE_BATTLER_ADDR = { symbol = "gActiveBattler", firered = 0x02023BC4, leafgreen = 0x02023BC4,
                            radical_red = 0x02023BC4, rr_source = RR_HARNESS,
                             emerald = 0x02024064 },
    PLAYER_BUFFER_EXEC_COMPLETED = { symbol = "PlayerBufferExecCompleted", thumb = true,
                                     firered = 0x0802E33D, leafgreen = 0x0802E33D,
                                     radical_red = 0x0802E33D, rr_source = RR_HANDOFF,
                             emerald = 0x0805748D },
    PLAYER_BUFFER_RUN_COMMAND = { symbol = "PlayerBufferRunCommand", thumb = true,
                                  firered = 0x0802E3B5, leafgreen = 0x0802E3B5,
                                  radical_red = 0x0802E3B5, rr_source = RR_HANDOFF,
                             emerald = 0x08057505 },
    HANDLE_INPUT_CHOOSE_MOVE = { symbol = "HandleInputChooseMove", thumb = true,
                                 firered = 0x0802EA11, leafgreen = 0x0802EA11,
                                 radical_red = 0x0802EA11, rr_source = RR_HARNESS,
                             emerald = 0x08057BFD },
    MOVE_CURSOR_ADDR = { symbol = "gMoveSelectionCursor", firered = 0x02023FFC, leafgreen = 0x02023FFC,
                         radical_red = 0x02023FFC, rr_source = RR_HARNESS,
                             emerald = 0x020244B0 },
    -- emerald renames Task_MultichoiceMenu_HandleInput -> Task_HandleMultichoiceInput
    -- (pret pokeemerald src/menu.c; same generic multichoice-menu input handler).
    PC_MULTICHOICE = { symbol = "Task_MultichoiceMenu_HandleInput", thumb = true,
                        firered = 0x0809CC99, leafgreen = 0x0809CC6D,
        radical_red = 0x0809CC99, rr_source = RR_HARNESS,
                             emerald_symbol = "Task_HandleMultichoiceInput", emerald = 0x080E2059 },
    -- pret ROM address unchanged in RR (rr_pc_menu.md:29,36: only two 8-byte windows patched
    -- inside the function body; the function itself was not relocated).
    PC_MAIN_MENU = { symbol = "Task_PCMainMenu", thumb = true,
                      firered = 0x0808C39D, leafgreen = 0x0808C371,
                      radical_red = 0x0808C39D, rr_source = RR_PC_MENU_MD .. "29,36",
                             emerald = 0x080C7269 },
    PC_STORAGE_MAIN = { symbol = "Task_PokeStorageMain", thumb = true,
                         firered = 0x0808D2BD, leafgreen = 0x0808D291,
        radical_red = 0x0808D2BD, rr_source = RR_HARNESS,
                             emerald = 0x080C82AD },
    PC_ON_SELECTED = { symbol = "Task_OnSelectedMon", thumb = true,
                        firered = 0x0808D879, leafgreen = 0x0808D84D,
        radical_red = 0x0808D879, rr_source = RR_HARNESS,
                             emerald = 0x080C8865 },
    -- pret ROM address unchanged in RR (rr_pc_menu.md:29: "retained ... byte-for-byte in direct
    -- comparisons against FireRed").
    PC_DEPOSIT_MENU = { symbol = "Task_DepositMenu", thumb = true,
                         firered = 0x0808DD89, leafgreen = 0x0808DD5D,
                         radical_red = 0x0808DD89, rr_source = RR_PC_MENU_MD .. "29",
                             emerald = 0x080C8D79 },
    -- pret ROM address unchanged in RR (rr_pc_menu.md:80 coordinator census: Task_WithdrawMon
    -- starts at the same 0x0808DC9C as FR's .sym).
    PC_WITHDRAW_MON = { symbol = "Task_WithdrawMon", thumb = true,
                         firered = 0x0808DC9D, leafgreen = 0x0808DC71,
                         radical_red = 0x0808DC9D, rr_source = RR_PC_MENU_MD .. "80",
                             emerald = 0x080C8C91 },
    PC_RELEASE_MON = { symbol = "Task_ReleaseMon", thumb = true,
                        firered = 0x0808DECD, leafgreen = 0x0808DEA1,
        radical_red = 0x0808DECD, rr_source = RR_HARNESS,
                             emerald = 0x080C8EB5 },
    PC_ON_B_PRESSED = { symbol = "Task_OnBPressed", thumb = true,
                         firered = 0x0808ECE5, leafgreen = 0x0808ECB9,
        radical_red = 0x0808ECE5, rr_source = RR_HARNESS,
                             emerald = 0x080C9D1D },

    -- ── witnesses for the scripted NEW GAME intro (card C4-LGF2, coordinator steer) ───────────
    -- Replace gen3_fr_newgame_inputs.lua's old fixed-frame-count waits (tuned once on FR,
    -- silently wrong on LG -- same screens, different elapsed frames) with RAM witnesses, the
    -- same "wait for the engine's own task/callback2, never a frame guess" shape c1507b7d
    -- already established for the START-menu SAVE row. No RR citation: Radical Red is not
    -- driven by this script (its fixture is an imported real save, gen3_fr_newgame_inputs.lua's
    -- own header). ABSENT for radical_red.
    -- emerald = nil: FR/LG-only concept, like Task_RunPokemonLeagueLightingEffect. Emerald's
    -- intro is Birch's speech, not Oak's -- pret pokeemerald has no Task_OakSpeech_* at all; its
    -- nearest analog is Task_NewGameBirchSpeech_ProcessNameYesNoMenu (src/starter_choose.c), a
    -- differently-shaped flow this table does not attempt to bridge.
    TASK_OAKSPEECH_GENDER_INPUT = { symbol = "Task_OakSpeech_HandleGenderInput", thumb = true,
                                     firered = 0x0812FFA5, leafgreen = 0x0812FF7D, emerald = nil },
    -- CB2_NamingScreen (DoNamingScreen's own run callback): reused for BOTH the player-name and
    -- rival-name screens in the intro -- there is no separate constant per screen, so the
    -- caller tells them apart by ORDER (first activation = player, second = rival), not by
    -- address.
    CB2_NAMING_SCREEN = { symbol = "CB2_NamingScreen", thumb = true,
                          firered = 0x0809FB71, leafgreen = 0x0809FB45,
                             emerald = 0x080E4F59 },
    -- Task_YesNoMenu_HandleInput: the generic Yes/No confirm task every ScriptMenu_YesNo box
    -- uses (src/script_menu.c), including the starter-nickname decline this same file's
    -- "starter" leg drives. One address serves every Yes/No box in the game; which box is open
    -- is not disambiguated by this witness alone (callers know from their own leg context).
    -- The START menu's input chain (src/start_menu.c): the window exists from DoDrawStartMenu
    -- step 2, but input is read only once Task_StartMenuHandleInput (created AFTER the draw) has
    -- set sStartMenuCallback = StartCB_HandleInput (:376-392); the SAVE row's A moves that callback
    -- to StartCB_Save1, then StartCB_Save2 while the dialog runs (:433, :568-573). sStartMenuCallback
    -- is never reset either, so these are read against the live task. ABSENT on radical_red (CFRU
    -- rebuilds the START menu; gen3_boot_check.save_via_menu keeps its older witness there).
    -- All four emerald = nil: pret pokeemerald's start menu is a different architecture, not a
    -- rename. src/start_menu.c polls a `gMenuCallback` bool8(*)(void) FUNCTION-POINTER VARIABLE
    -- instead of a persistent gTasks entry -- HandleStartMenuInput (static) sets
    -- gMenuCallback = StartMenuSaveCallback on the SAVE row (:616), which sets
    -- gMenuCallback = SaveStartCallback (:726), which sets gMenuCallback = SaveCallback
    -- (:812), which polls RunSaveCallback() and resets
    -- gMenuCallback = HandleStartMenuInput when done (:593-851). There is no Task_ func slot to
    -- wait on the FR/LG way, and no 1:1 StartCB_Save1/StartCB_Save2 split.
    TASK_START_MENU_HANDLE_INPUT = { symbol = "Task_StartMenuHandleInput", thumb = true,
                                     firered = 0x0806F1F1, leafgreen = 0x0806F1F1, emerald = nil },
    START_CB_HANDLE_INPUT = { symbol = "StartCB_HandleInput", thumb = true,
                              firered = 0x0806F281, leafgreen = 0x0806F281, emerald = nil },
    START_CB_SAVE1 = { symbol = "StartCB_Save1", thumb = true, firered = 0x0806F5A5, leafgreen = 0x0806F5A5,
                       emerald = nil },
    START_CB_SAVE2 = { symbol = "StartCB_Save2", thumb = true, firered = 0x0806F5C9, leafgreen = 0x0806F5C9,
                       emerald = nil },
    -- emerald renames Task_YesNoMenu_HandleInput -> Task_HandleYesNoInput
    -- (pret pokeemerald src/script_menu.c#L28,224; same generic Yes/No confirm task).
    TASK_YES_NO_MENU = { symbol = "Task_YesNoMenu_HandleInput", thumb = true,
                         firered = 0x0809CE55, leafgreen = 0x0809CE29,
        radical_red = 0x0809CE55, rr_source = RR_HARNESS,
                             emerald_symbol = "Task_HandleYesNoInput", emerald = 0x080E215D },
}

local TITLES = { firered = true, leafgreen = true, radical_red = true, emerald = true }
-- Generated per-build harness facts; keep every hand-authored column above unchanged.
local EXP_TITLE = "emerald_expansion_28877d73"
local module_dir = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or ""
TITLES[EXP_TITLE] = true

M.TITLES = TITLES

--- name -> address for `title`, for every entry that HAS one. Errors loudly (never a silent
--- nil/0) only for an unrecognized title. A recognized title missing one entry's column is not
--- an error: that entry is simply omitted from the result, so a caller reading a plain Lua field
--- (S.FOO) gets nil and fails wherever it actually tries to use FOO -- never at module load, and
--- never with a wrong number silently standing in (card C4-LG2: radical_red has several entries
--- nobody has proven yet; see the ABSENT notes above each one).
function M.for_title(title)
    if title == EXP_TITLE then
        local generated = dofile(module_dir .. "gen3_title_syms_exp_28877d73.lua")
        assert(generated.title == title, "expansion harness title mismatch")
        local out = {}
        for name, entry in pairs(generated.entries) do
            if entry.address then out[name] = entry.address end
        end
        return out
    end
    if not TITLES[title] then
        error("gen3_title_syms: unknown title " .. tostring(title)
              .. " (want firered, leafgreen, radical_red or emerald)", 0)
    end
    local out = {}
    for name, e in pairs(M.entries) do
        local addr = e[title]
        if addr then out[name] = addr end
    end
    return out
end

return M
