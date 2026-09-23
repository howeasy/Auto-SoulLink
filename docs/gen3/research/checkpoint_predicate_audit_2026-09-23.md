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

## Persistent-task census (headless Codex cx-45b6df45, pret c75f3523)

Nine task functions persist during ordinary field control:
- the three field tasks (per-step callback, time-based events, weather main);
- the three Center 1F Union Room background tasks (rev 0);
- Task_RunPokemonLeagueLightingEffect (5923c4dd);
- inside the actual Union Room room only, Task_RunUnionRoom and Task_AnimateUnionRoomPlayers. These stay DENIED
  deliberately: they initiate link activities and write visibility flags.

League lighting is the only additional benign single-player hold, and it is now allowed on FR/LG.

Finite holds, not latches:
- the map-name popup, about 121 frames plus scrolling (~2.5 s);
- fanfares, doors, escalators, fishing, surf transitions, item-use chains (Itemfinder, Repel, VS Seeker) and cutscene
  tasks. Each destroys itself or runs under a lock.

Corrections to earlier claims:
- The existing per-step task CAN write save-block flags and variables (Icefall Cave STEP_CB_ICE, field_tasks.c:146,243).
  It is benign for bounded party/PC writes, but it is not save-read-only.
- ScriptMovement_MoveObjects is destroyed by release/releaseall, not by finishing its movement.

Not proven:
- absolute completeness (387 CreateTask sites reviewed; this is not a formal reachability proof);
- RFU exceptional states;
- RR.

Natural-play task snapshots would settle it: League rooms, Icefall Cave, Center 1F, the Union Room room, map-name
popups, and returning from item and field-move interactions.
