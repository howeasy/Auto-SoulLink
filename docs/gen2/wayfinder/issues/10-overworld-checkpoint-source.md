# Gen 2 overworld-safe checkpoint predicate from pret

Type: research
Status: resolved
Blocked by: none

## Question

What execution site and/or WRAM predicate in pokecrystal@7a7881d / pokegold@656583c establishes "in the overworld, no script running, joypad owned by the player" for a write checkpoint, with the same fail-closed shape as Gen 1's `data/games/gen1_rby/write_checkpoint.json` + `lua/gen1_write_safety.lua` (ROM anchors re-verified per call)? Candidates to read: `OverworldLoop`, `wScriptRunning`, `wScriptFlags`, `wScriptMode`, `wMapEventStatus`, `wJoypadDisable`, `wGameTimerPause`, `DelayFrame`/`Joypad` (also the native-sound sites Gen 1 used). Open question 3 of docs/gen2/research/pret_gen2_symbols.md.

## Answer

Resolved by Codex `cx-02b0f4b5` (`docs/gen2/research/codex_checkpoint_and_linktrade.md` §A), coordinator-verified against the HEAD clones. A single byte is insufficient. Anchor 1 = the synchronous main-thread input boundary in `OWPlayerInput` immediately before `call CheckAPressOW` (`pokecrystal@7a7881d engine/overworld/events.asm:495`; `pokegold@656583c :483`), caller-bound. Anchor 2 (conditional) = a Gen 1-shaped halted-frame checkpoint derived from the `DelayFrame` IRQ stack (four-word). Strict predicate set on `wScriptRunning`/`wScriptFlags`/`wMapEventStatus`/`wJoypadDisable`/`wBattleMode` (note `wGameTimerPaused` bit 0 means counting). Corrections to the ticket's premises: Gen 2 `Joypad` is a `reti` stub (`home/joypad.asm:1-6`), menus and text DO reach `DelayFrame`, `DoOverworldFunction` does not exist. LIVE GATE OPEN: liveness of the strict predicate under deferred scenes/menus/phone events, and the negative controls (textbox, START, battle, warp fade, Elm scene) are P3b exit evidence (PLAN §5.4, §6).
