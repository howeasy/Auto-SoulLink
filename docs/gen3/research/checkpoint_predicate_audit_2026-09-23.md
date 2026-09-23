# Gen 3 write-checkpoint predicate audit, 2026-09-23

Independent, read-only audit by headless Codex (magi cx-7e8b52f4). Pret pin c75f3523; SLink HEAD 328e5ab8.
ROMs: FR 41cb23d8, RR clean 964f951a, RR companion b7d1e075.

Trigger: two predicates test engine pointers the game never clears. They are being fixed as C4-SAVE:
- sSaveDialogCB stays on SaveDialogCB_ReturnSuccess after any save;
- gLinkCallback survives CloseLink after a no-partner cable link.

Findings:
1. **Task_RunPokemonLeagueLightingEffect** (field_specials.c:2133-2185) persists in the Elite Four rooms after the
   entrance script ends (LoreleisRoom/scripts.inc:43-48). It is not on the task allow-list, so every overworld write
   is held in those rooms before the battle. This is PROVEN for FR/LG. For RR the functions are byte-identical, but
   RunOnResumeMapScript differs, so it is strongly inferred only. It is routed to C4-SAVE.
2. RR's battle lifecycle cannot be qualified from pret. HandleTurnActionSelectionState, ReturnFromBattleToOverworld
   and SetUpBattleVars differ in the RR artifacts, so RR's parked battle tuple needs its own proof. This is a G5 item.
3. Retained battle state (gBattleOutcome, main func, controllers, battle mons) is scoped to the battle reasons and
   is not an overworld latch.
4. The native timeout poison (native.lua:395-403) is a deliberate uncertainty latch that is recovered by reset or
   beacon loss. Keep it.

Verified with a clear path (no latch found): callback1, callback2, script_context_status, field_controls_locked,
palette_fade_active, in_battle, gReceivedRemoteLinkPlayers, link_transferring, soft_reset_disabled, the six allowed
background tasks, the native opcode/status/panel handshake, the save/storage pointers, battle_outcome_open,
battle_main_func, battle_comm_0/commit_guard, FR/LG battle_exec_flags_input and battle_input_controller,
battle_not_link, battle_engine_loaded, and the sound clauses. The CPU parked clause is a current-state check.

Not exhaustively proven: other map-specific persistent tasks. The allow-list is a whitelist, so any persistent task
started by a map script that leaves the player in control would hold writes the same way. A census of such tasks is
a follow-up.
