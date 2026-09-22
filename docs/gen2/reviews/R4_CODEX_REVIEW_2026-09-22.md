# R4 review of c42061d, 0f2b3bc, c03c15f (Codex headless cx-6a1bf1e3, 2026-09-22)

Static, read-only review at e19af00 by a fresh headless Codex (non-author). Pins:
C = pokecrystal 7a7881d0, G = pokegold 656583c9. Coordinator verified 1 and 5 in the code.
The live Codex thread Gen2-Part2 is doing an adversarial second pass (verify/refute + uncovered areas).
Verdict: changes required for 0f2b3bc and c03c15f; c42061d accepted with finding 8 open.

| # | Sev | Status | Where | Finding |
|---|---|---|---|---|
| 1 | HIGH | CONFIRMED | tests/live/test_gen2_new_gates.py:222 | Whole-dict badge compare; RAW_BADGES (gen2_inspect_gate.lua:173) lacks raw_hex/evidence/snapshot_qualified that reads.lua:303-305,425 adds: correct readings always fail. |
| 2 | MED | CONFIRMED omission | tools/gen2_fixtures.py:114-145, :639-641 | Re-save allowlist omits phone timers wReceiveCallDelay_StartTime/_MinsRemaining, wTimeCyclesSinceLastCall (C wram.asm:2961-2963, G :2343-2345) that CheckPhoneCall updates before SAVE (C events.asm:463-466, time.asm:47-96,377-407; G events.asm:450-454, time.asm:33-82). |
| 3 | MED | CONFIRMED | tools/gen2_fixtures.py:121, :630-635 | wObjectFollow_Leader..wVariableSprites exemption includes wMapObjects script pointers/event flags, which CONTINUE does not reload (C setup_scripts.asm:167, home/map.asm:385-415; G home/map.asm:754-784): hides map-script corruption. |
| 4 | MED | CONFIRMED | lua/tests/gen2_inspect_gate.lua:196-221 | First decodable party + stable bytes is already true on the CONTINUE confirm screen (party loads first: C save.asm:596-601, intro_menu.asm:338-348,429-437; G save.asm:538-543, intro_menu.asm:251-260,313-321). |
| 5 | MED | CONFIRMED | lua/tests/gen2_inspect_gate.lua:331 | api.speed(6399) overrides the validated 100% (tools/run_gb_gate.py:290-291,329-330). |
| 6 | MED | CONFIRMED | tests/live/test_gen2_new_gates.py:203-206 | Wrong-fixture control compares the captured OT with itself; no binding to the qualification receipt, so an _ot2 swap passes. |
| 7 | MED | CONFIRMED | tests/live/test_gen2_new_gates.py:181-184; gen2_inspect_gate.lua:129,154 | Provenance fields recorded but not validated; party labelled System Bus but read from flat WRAM (GEN2_BINDING_PLAN.md:339 falsifier). |
| 8 | LOW | CONFIRMED rule mismatch; pack impact UNVERIFIED | tools/gen_gen2_area_map.py:251-252,270 | All $B0 side-wall collisions treated as unstandable; COLL_UP_WALL is land with directional masks (C collision_permissions.asm:182, home/map.asm:1511-1548, player_movement.asm:686-701). |

Plausible: a same-identity savestate at the same frame count evades the pre-hello discontinuity clear (lua/gen2/client.lua:715,722-725).
Checked correct: area-map diffs add only fishing_water (388/368/368 rows); permission-table refusal, header/dimension/pointer checks, quadrant order, block-zero; G/S window stack and C sScratch boot-zero; unconditional candidate frame dispatch (lua/gen2/run.lua:122-126); identity-change queue clear; PC/SP width; independent Python decoding; R-3 limitation stated honestly; missing prerequisites fail the gated lane.

Disposition: 1-7 -> fix card gen2-N10 (Opus). 8 -> generator follow-up (fishing stays OPEN meanwhile). Savestate case -> carry.

## Second pass: live Codex thread Gen2-Part2 (independent, static, e19af00)

3 HIGH, 3 MEDIUM, 1 LOW. Independently confirms findings 1 (badge dict), 3 (object exemption covers wMapObjects script pointers; C sym wMap1ObjectScript 01:d738, G/S 01:d45f), 4 (gate can settle on the CONTINUE confirm screen; rated HIGH here), 5 (speed 6399), 6 (fixture binding tautological; rated HIGH here, runner accepts any existing candidate, tools/run_gb_gate.py:297-301), 7 (party domain/range metadata) and 8 (side walls are directional, LOW, no pinned-map miscount established). Did not raise 2 (phone timers).
Additions: R-5g must also stay OPEN (two DV formulas are not GAME status-symbol evidence); JumpRoamMons rewrites active roamer map fields (C engine/overworld/wildmons.asm:672-700), irrelevant to the eight early fixtures but the allowlist is not exhaustive for late-game saves. Checked correct: c42061d pack diff, collision/quadrant math and refusals; G/S window stack; C sScratch zero-only; R3 delta covers both copies; unconditional frame_end (lua/gen2/run.lua:122-125); witness re-derivation; PYDEC independence; honest R-3 limitation.
Disposition: all folded into gen2-N10 (addendum: full-consumer, pre-confirm replay, wrong-save receipt, script-pointer mutant, speed wrapper, domain negative controls; no R-5g closure claim).

Correction (Gen2-Part2, coordinator-verified): finding 2 REFUTED. The phone timers are in the unsaved wMapStatus block (C ram/wram.asm:2907-2972; wReceiveCallDelay_StartTime 01:d466 precedes wPlayerData 01:d47b), and SavePlayerData copies only wPlayerData..End + wCurMapData (C save.asm:498-508; G :396-406). Dropped from N10.
