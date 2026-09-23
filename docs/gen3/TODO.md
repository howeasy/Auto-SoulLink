# Gen 3 — post-RC TODO

Work the owner moved out of the Gen 3 RC. None of it is an RC requirement or a gate item. Each
entry returns as its own card on the new client after the RC ships.

## Native text (RR companion)

Owner ruling 2026-09-23. Notifications drawn in the ROM's own text boxes instead of the Lua HUD:
- `OP_SHOW_MESSAGE` (8): the overworld field message box, text pre-written through `MB.write_message` (`lua/mailbox.lua:91`).
- `OP_SHOW_BATTLE_MESSAGE` (23): themed text in the battle move-info window (`lua/mailbox.lua:204`).

In the old client this path is `try_native_box` and `native_messages` (`lua/clients/gen3_frlge_client.lua:435-476, 550, 719-1014`). The server default is already messages OFF (Lua HUD).

- **RC behaviour:** every Gen 3 notification and prompt goes through `lua/hud.lua`, as on FRLG vanilla. `native.lua` (P5) ports the mailbox ABI, trade, info panel, explode and rival swap. It does not port the message opcodes.
- **Post-RC card:**
  - Port the message opcodes into `native.lua` behind the same capability branch.
  - Charset: the native box uses the FR charset, not `hud.sanitize`.
  - Keep the Lua HUD as the fallback when the box can't open (script running, not overworld).
  - Confirm the shown/refused result byte (old client `:550`).
  - Add a GAME oracle that reads the text back from the box.

## Peer ghost (RR)

Owner ruling 2026-09-22 (PLAN §0/§10). No `ghost.lua` and no `ghost` duo scenario in the RC, and N-2 is out; the RR duo set is eight. Design notes are in memory: `project_peer_ghost_feature`, `reference_peer_ghost_clone_techniques`.

## Archipelago FRLG

Owner ruling 2026-09-23 (PLAN §0/§10). `firered_ap` stays unadmitted. The old client's " AP" ROM name-suffix check (8e125fe/897fefc3) has never been checked against a real AP-patched dump. That check comes back together with the AP pack, kind and gates.
