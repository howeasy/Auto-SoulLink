# First live play: source check of live-only assumptions (OMP Gen2-Base cx-1894d4b0, 2026-09-22)

Read-only source check of the crystal_town route before any emulator time. Pins: C = pokecrystal 7a7881d0, G = pokegold 656583c9.

- **F1 HIGH (coordinator-verified): the route cannot dismiss map-script text boxes.** The only "text" origin watched is
  WaitPressAorB_BlinkCursor (tools/gen2_fixtures.py:396; C home/joypad.asm:342). Script texts wait in PromptButton
  (home/joypad.asm:383-431) or WaitButton (:302-309), and OWPlayerInput does not run while a script runs
  (engine/overworld/events.asm:241-246), so the observer reports idle forever. First stall: Mom's
  `writetext ElmsLookingForYouText / promptbutton` (maps/PlayersHouse1F.asm:36-38). Same class: the weekday picker loop
  (engine/rtc/timeset.asm:420-423; only its confirm YesNoBox is watched), Elm's texts (maps/ElmsLab.asm:61-85), starter
  texts, ElmDirections waitbuttons, the Route 29 catch tutorial. Identical on Gold/Silver (shared home/ and scripting code).
- F2: the intro itself is covered (title, NEW GAME, gender, clock pickers + YesNoBox, Oak texts, NamePlayer), via the
  pre-first-tick stale-"text" path.
- F3 anchors HOLD (all single-row, glyphs present in the charmap). "OK to overwrite?" is not on the fresh route path
  (save.asm:182-186) but is on the resave path (:189-192), which handles it.
- F4 QUALIFY_BUDGET (30000/12000 at 100%) covers title -> CONTINUE -> overworld by source estimate (~3-4k frames);
  budgets_measured is still False.
- F5 SaveRAM -> CartRAM before the script: unverifiable from source but checked at run time (booted digest == candidate).
  Residual: the route's empty-lane precondition is vacuous (has_existing_save hardcoded false, test_gen2_scripted_gate.lua:428).
- D1/D2: unit tests model a text wait as a "text" observation instead of proving one fires; the day picker is not
  WaitPressAorB_BlinkCursor.

Disposition (next card, before the first live play): add origins for PromptButton, WaitButton and the weekday picker
(SetDayOfWeek .loop2 and the G/S equivalent), answered with A in lua/tests/gen2_scripted_play.lua; the qualify driver keeps
refusing them; a pure test that a script-state observation is handled or explicitly idles; make has_existing_save real
(wSaveFileExists or a CONTINUE item). No blind "press A when idle" fallback.
