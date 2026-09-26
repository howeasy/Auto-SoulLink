# OMP wave-A pre-live review (card gen2-O-wavea), 2026-09-23

Peer review for task `cx-91fc7de4` (peer omp, orchestrator claude). READ-ONLY: this file is the only
thing written; not committed.

Reviewed revisions (the working tree is being edited live; these are the exact files read):

| file | sha256[0:16] | mtime |
|---|---|---|
| tools/e2e_duo.py | `2aecd6ce2acda2fa` | 2026-09-23 18:32 |
| tools/gen2_duo_oracles.py | `c4b4bfdf148c5a72` | 2026-09-23 18:24 |
| lua/tests/duo/duo_gen2_main.lua | `5c7e392c4b52232d` | 2026-09-23 18:13 |
| lua/tests/duo/scenario_gen2_admit_wrong_rom.lua | `3fe39c84aaede1f4` | 2026-09-23 17:50 |
| lua/tests/duo/scenario_gen2_reconnect.lua | `9295b9ca2b7cbaaa` | 2026-09-23 17:53 |
| lua/tests/duo/scenario_gen2_soft_reset.lua | `ff3bab3ea6b972e1` | 2026-09-23 17:57 |
| lua/tests/duo/gen2_faint_inputs.lua | `6fdb7595a66bc726` | 2026-09-23 16:41 |
| lua/tests/gen2_frame_align.lua | `0fae78c0c39c6308` | 2026-09-23 16:36 |

Pins: pokecrystal `7a7881d`, pokegold `656583c` (`.cache/gen2-build/...`). All five card commits
(`d1567fc1`, `c58b55fb`, `33d03063`, `2dc959d0`, `e998aa4b`) and the race fix `9fffb78c` are ancestors
of HEAD `234240f4` (`git merge-base --is-ancestor`).

---

## SUMMARY

The three wave-A drivers and Codex's lanes are sound in shape, and the H7 `admit_wrong_rom`
after-snapshot race is **already fixed at HEAD** (`9fffb78c`: the after snapshot may follow a normal
client exit). Neither `reconnect` nor `soft_reset` has that shape — their snapshots are taken mid-run
behind explicit connected-waits, and the soft-reset oracle exempts the after label from the
connected check. The walk-phase hazard the card suspected is **not the phone**: Crystal and Gold/Silver
share one phone implementation, a random ring needs ≥20 RTC minutes plus a non-empty caller pool, and
the only early phone interrupt is the story call on Route 30. The real walk-phase killer on the C↔G
faint path is the **stale UI context at a save→walk leg boundary** — the exact class the U1d gate hit
and fixed with a settle phase, which the duo faint driver does not have — with the shared Route 29
catching-tutorial `yesorno` as the second, story-driven candidate.

## FINDINGS

### F1 — Q3: the admit race is real and closed; reconnect/soft_reset do not share it (no action)

- The H7 failure mode is exactly as reported: `assert_gen2_admit_wrong_rom` evaluates
  `after=self._gen2_admit_snapshot()` at oracle time (`tools/e2e_duo.py:1692`), i.e. after
  `wait_results()` returned for both clients (`tools/e2e_duo.py:4631-4637`), and a closed socket flips
  `connected` to False in the reader's `finally` (`server/server.py:1471-1484`).
- Fixed at HEAD by `9fffb78c`: the admitted row's connected check is now
  `(label == "after" or active.get("connected") is True)` (`tools/gen2_duo_oracles.py:736`), and the
  remaining admission requirements are pinned by `test_wrong_rom_admission_accepts_terminal_disconnect`
  and `test_wrong_rom_terminal_disconnect_keeps_admission_requirements`
  (`tests/unit/test_gen2_duo_oracles.py:1010-1030`). The after snapshot's other checks stay durable:
  `admitted in live` still holds because the server keeps the `connected_players` key with
  `connected: False` (`server/server.py:1480-1484`), and `players[x].admission` comes from
  `self.admission` (`server/server.py:348`, `:2433-2435`), untouched by a disconnect.
- **reconnect** takes all five snapshots inside `_orchestrate_gen2_reconnect`, each behind a
  connected-wait: `initial` (`tools/e2e_duo.py:1795`), `disconnected` after
  `not A.connected and B.connected` (`:1796-1800`), `before_wrong` while A is disconnected (`:1803`),
  and `same_save`/`wrong_save` after `reconciled()` requires both A and B connected (`:1806-1815`).
  B is still online at every one of those points because the runner appends `B_DONE` only after both
  relaunches (`tools/e2e_duo.py:1825`), and the oracle's `players["b"].connected is True` check
  (`tools/gen2_duo_oracles.py:910`) is therefore satisfied by construction. No race.
- **soft_reset** takes its after snapshot mid-run, right after the same-OT rehello is on the server
  (`tools/e2e_duo.py:1741-1749`), and the oracle deliberately exempts the after label:
  `(label != "before" or player.get("connected") is True)` (`tools/gen2_duo_oracles.py:1025`). No race.

### F2 — Q4 (HIGH): the C↔G walk-phase `yes_no` is a leg-boundary stale UI, not a phone call

The failing leg is the FI driver (`lua/tests/duo/gen2_faint_inputs.lua`), whose refusal message is
"UI is not valid in phase " .. phase .. ": " .. kind (`:157-158`); the route29 driver's message differs
("UI is not valid while walking", `lua/tests/duo/gen2_route29_inputs.lua:136`), so the observed
`yes_no` pins FI. Mechanism:

1. The link/save leg's driver ends on the **save counter**, not on the overworld:
   `if self.phase == "save" and save_counter and point.save_success_counter > save_counter then
   self.phase = self.terminal` (`lua/tests/gen2_frame_align.lua:225-228`). The counter fires at the
   final `ret` of `_SaveGameData`, before "Saved the game." is printed.
2. At that instant the newest UI origin is still the save's `yes_no` (`save_overwrite`,
   `lua/tests/gen2_frame_align.lua:250-253`); no overworld tick has fired since, so the observer
   reports `ui = {kind="yes_no", prompt="save_overwrite"}`.
3. The duo faint driver starts the FI leg right after the partner marker
   (`lua/tests/duo/scenario_gen2_faint.lua:88-91`: `h.wait(partner_has("LINK_SAVE"))` then
   `h.sacrifice(...)`), with **no settle phase** — so FI's first step is in phase `walk` with that
   stale UI and refuses.
4. This is the identical bug the U1d gate already hit and fixed, in its own words: "the stale yes_no
   context reached FI's walk phase" (`lua/tests/gen2_frame_align.lua:648-651`), where the fix is a
   `settle` wrapper that idles until `point.overworld_ready`. The duo faint driver never got it.
   (If the partner's marker arrives a little later, the stale context becomes the save text's
   `prompt_button` and the lane dies with that kind instead — the class is the same.)

Second, story-driven candidate on the same path: the **Route 29 catching-tutorial scene scripts ask a
yes/no** — `Route29Tutorial1` (`pokecrystal/maps/Route29.asm:47`) and `Route29Tutorial2` (`:72`), and
the repeat-talk path `CatchingTutorialDudeScript` (`:115`); the file is line-identical in pokegold. If
the fixture's Route 29 scene is not `SCENE_ROUTE29_NOOP` (or the tutorial was declined during the
fixture play), an ordinary walk can raise that box.

### F3 — Q4: the phone is not a Crystal-only hazard (facts, both pins)

- One shared implementation: `CheckPhoneCall` (C `engine/phone/phone.asm:109-149`, G `:109-155`),
  same gates (not standing on an entrance, timer due, a 50 % roll, map phone service, an available
  caller), same delay table `.ReceiveCallDelays db 20,10,5,3` (C `engine/overworld/time.asm:16-45`,
  G `:12-41`), same contacts with Mom's caller-time 0 (C `data/phone/phone_contacts.asm:12`,
  G `:12`) — so Mom is never a random caller and a random ring cannot fire before ~20 RTC minutes
  since the map load (`InitCallReceiveDelay`, called from `StartMap`: C `events.asm:98-107`).
- The only early phone interrupt on the corridor is the story special call: `specialphonecall
  SPECIALCALL_ROBBED` set in Mr. Pokémon's house (C `maps/MrPokemonsHouse.asm:129`), fired on the
  first counted step outside (Route 30, `CheckSpecialPhoneCall` C `phone.asm:242-287`). Mom's callee
  script is the only phone script with `yesorno` (C `engine/phone/scripts/mom.asm:84,90,96,103,140`;
  G `:92,98,104,111,148`).
- Net: no Crystal-only phone hazard on a Route 29 walk; the Crystal/Gold differences the scout found
  (Route 30 trainer sight/placement, a Crystal-only Antidote ball) are outside the faint lane's path.

### F4 — Q2: marker audit — what is independent and what is self-reported

Independent anchors (sound):
- `RESET_SEEN` reads raw `wPlayerID`/`wPartyCount` through the gate's symbol reader in their profile
  banks (`lua/tests/duo/duo_gen2_main.lua:382-386`; `profile.json:1149/921` with
  `ram_bank: wPlayerID 1, wPartyCount 1`, `:1976/1748`; `ctx.sym` at
  `lua/tests/test_gen2_scripted_gate.lua:309-314`) — not a client self-report.
- `SAVE_WITNESS` requires the gate's own `save_completed` hook count ≥ 1 **and** the client's ≥ 1, plus
  CartRAM digest == file (`lua/tests/duo/duo_gen2_main.lua:425-440`).
- The refused half: `run.lua`'s console refusal line + no client + `tx == 0` + CartRAM digest
  unchanged + the pinned Crystal-1.1 hash (`scenario_gen2_admit_wrong_rom.lua:76-96`;
  `tools/gen2_duo_oracles.py:683-698`).
- `WRONG_SAVE_HUD` is a server→client command and the oracle also requires `identity_error`
  (`tools/gen2_duo_oracles.py:945-950`).

Self-reported (MEDIUM): the soft-reset "writes paused / hello waits" claim rests on the production
client's own flags and permit log — `WRITES_PAUSED` = `c.gate_revoked and not c.writes_enabled`,
`HELLO_CLEARED` = `c.hello_sent ~= true` (`scenario_gen2_soft_reset.lua:99-107`), and
`NO_WRITES_IN_WINDOW` counts rows the *client's* writer appended
(`lua/tests/duo/duo_gen2_main.lua:389`; `scenario_gen2_soft_reset.lua:124`). The oracle ties them to
the independent RAM clear by ordering and windows (`tools/gen2_duo_oracles.py:1040-1055`), but no
write is *attempted* in the window, so W-6's "refused" half is not exercised — a write that bypassed
the writer would not be caught. What is proven is "no write observed", not "writes were refused".

### F5 — Q1: input plan vs the pinned decomps (all pass)

- Soft-reset chord `{A,B,Select,Start}` (`scenario_gen2_soft_reset.lua:45`) matches
  `and PAD_BUTTONS / cp PAD_BUTTONS / jp z, Reset` (C `home/joypad.asm:99-102`; same in pokegold).
  `Reset` sets the joypad-disable bit then `ld c, 32 / call DelayFrames / jr Init`
  (C `home/init.asm:13-19`) — the clear lands ~32+ frames after the chord, matching
  `RESET_DELTA = {30,60}` and the oracle's window.
- What is cleared: Crystal clears WRAM0 + WRAMX bank 1; `wPlayerID` (`$D47B`) and `wPartyCount`
  (`$DCD7`) are both bank 1, so the driver's zero-check is valid; Gold/Silver clear `$C000-$DFFF`.
  SRAM is not erased (only Crystal's 32-byte `sScratch` wipe).
- The main menu's default cursor is the top entry in both titles (`MenuHeader` default-option byte,
  `_InitVerticalMenuCursor` → row 1); the qualify driver chooses CONTINUE **by label**
  (`lua/tests/gen2_qualify.lua:97-100`), so the default cannot matter; Crystal's extra MOBILE entries
  are unreachable. NEW GAME has no erase confirmation in either title (the erase prompts are the
  hidden title `Up+B+Select` and the save-overwrite), so the CONTINUE-only path is safe, and the
  soft-reset chord cannot trigger the title delete (it is released long before the title screen
  appears).

### F6 — LOW: reconnect's same-save seed comparison includes the RTC trailer

`_reconnect_need(seed == initial_raw ...)` (`tools/gen2_duo_oracles.py:891`) compares the full
32 790-byte file, while the project's own rule says the trailer is outside equality
(`tools/gen2_duo_oracles.py:107`: "22-byte RTC trailer, outside the equality (P3b.7 plan)"). The
initial leg's emulator is terminated after the leg; if BizHawk rewrites the trailer at exit, this
false-FAILs. Compare `seed[:CARTRAM_BYTES] == initial_raw[:CARTRAM_BYTES]`.

### F7 — LOW: no test pins the runner's reconnect snapshot ordering

The reconnect oracle requires B connected in all five snapshots (`tools/gen2_duo_oracles.py:910`); the
safety comes entirely from the orchestration taking them mid-run. A future reordering (snapshot after
teardown) would false-FAIL with no unit test to catch it. The admit/soft_reset cases now have
terminal-disconnect tests; reconnect's invariant deserves one too (or at least an in-code comment,
the way the Gen 1 `soft_reset_new` block documents its H-6 reasoning, `tools/e2e_duo.py:4300-4320`).

## DISAGREEMENTS

1. The card frames the walk-phase risk as "a phone call or a stray YES/NO … Crystal-only". My facts
   say the phone cannot fire early and is title-neutral; the actionable hazards are the stale UI at
   the save→walk boundary (F2) and the shared Route 29 tutorial yes/no. If the coordinator lands on
   "phone", the fix would be aimed at the wrong site.
2. The card implies reconnect/soft_reset might share the H7 shape. They do not (F1); the only fix
   needed there is the one already committed (`9fffb78c`).

## UNKNOWN / UNVERIFIED

- Which of F2's two mechanisms produced the observed Crystal-A failure. Settle it from the failing
  lane's receipt (`patch/build/e2e_gen2_faint_*`, with `SLINK_GEN2_TRACE=1` the observer prints
  `ui=<kind> age=<n>` per 30 frames) or from the fixture's Route 29 scene/`EVENT_LEARNED_TO_CATCH_POKEMON`
  state. The failing receipt is not in this worktree.
- The fixture's exact scene/event state on Route 29 (whether the tutorial can re-fire).
- The reviewed tree is moving (tools/e2e_duo.py mtime 18:32 while this review ran); line numbers are
  for the hashes above.
- I did not run any test: an emulator lane (LIVE2) is live and the runbook forbids test runs during a
  lane.

## RECOMMENDATION

1. Add the gate's settle wrapper to the duo faint driver before the FI leg (mirror
   `lua/tests/gen2_frame_align.lua:648-660`: idle until `point.overworld_ready`). Do the same for any
   future leg that starts after a save (`h.encounter`/`h.flee` in the clause lanes have the same
   shape).
2. Make the Route 29 tutorial non-repeatable for the lanes: assert in the fixture facts (or the lane
   preflight) that `EVENT_LEARNED_TO_CATCH_POKEMON` is set / the scene is NOOP; if that cannot be
   guaranteed, teach the walk phase to answer the tutorial `yesorno` (NO) and continue instead of
   refusing.
3. Keep the admit after-snapshot exemption; do not copy it to reconnect (there B-online is the
   scenario's claim) — instead pin the ordering with a comment/test (F7).
4. Compare reconnect's same-save seed on `[:CARTRAM_BYTES]` only (F6).
5. If the owner wants W-6's "refused" half rather than "not observed", add an attempted-write control
   in the cleared window.

## TESTS / VERIFICATION

- Existing, should stay green: `pytest tests/unit/test_gen2_duo_oracles.py -k "wrong_rom or reconnect
  or soft_reset"`; `tests/unit/test_gen2_duo_driver.py` (the drivers' pure verdicts).
- Add: (a) a pure driver test that FI's walk phase refuses a stale `yes_no` unless a settle phase
  precedes it; (b) a runner-ordering test (or an explicit invariant comment plus an assertion) that
  reconnect's five snapshots are taken before the corresponding teardown; (c) a fixture-facts test
  that the battle fixtures' Route 29 scene/event flags make the tutorial non-repeating.
- Live: rerun the C↔G `gen2_faint` lane with `SLINK_GEN2_TRACE=1` and read the UI kind/age at the
  failing frame — that discriminates F2's two mechanisms in one run.
