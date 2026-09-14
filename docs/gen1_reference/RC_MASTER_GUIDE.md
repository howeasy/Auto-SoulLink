# Gen 1 Soul Link RC completion guide

This is the only current status, dispatch authority, and resume contract for Gen 1. The [universal entry](README.md) routes agents to the static package catalog, [worktree register](WORKTREE_REGISTER.md), or manifest **when their task needs them**. Historical handoffs are [archived](archive/2026-09-13-superseded/README.md); their old branch instructions are not active. The exact requirement IDs live in [tests/gen1_release_requirements.json](../../tests/gen1_release_requirements.json), not in a second spreadsheet.

## Product and finish line

The current RC product is a playable two-person **Red/Blue Soul Link** through the game: 1× at full FPS, the owner's accepted near-3× rate, correct paired acquisition/death/storage/evolution/PC behavior, native trade with both saved files, truthful interruption handling, and a usable Manager/bundle. **Owner moved Yellow-specific work to [post-RC TODO](POST_RC_YELLOW_TODO.md).** Preserve its existing support/evidence, but do not dispatch new Yellow work or use Yellow passes as R/B qualification. R/B companions have panel+trade; SFX remains disabled unless separately proved. No separate demo/polish project is authorized.

The finish line remains a frozen-source, non-quick release evaluator pass for the **approved R/B scope**, no skips/xfails/deselection or input drift in active checks, followed by the required two-person human attestation and owner shipping authority. **Gate scope alignment is pending:** the current machine-readable manifest/runner still encode the older full-RBY388-row/all-nine-pair contract. Do not claim a passing R/B release by ignoring its failures or relabeling Yellow rows passed. Preserve deferred Yellow obligations explicitly and review exact active/deferred IDs, shared-row descriptions, check inventory and hardcoded pair validation before changing the gate. Existing15-check/eight-prerequisite results remain historical until aligned; seven prerequisite hash pins plus Java presence is the existing P0 policy.

## Verified cut and current work ledger
<!-- AGENT_CHECKPOINT_START -->
```json
{
  "schema": 1,
  "updated_at_utc": "2026-09-14T08:24:49+00:00",
  "coordinator_session_id": "9a7ac120-04eb-489f-8fd1-c9ecb67b31a6",
  "source_head": "6931fdf",
  "live_lane": null,
  "next_action": "PAUSED BY OWNER 2026-09-14 (wrap-up). F0 speed gate PASS recorded; D4-CLAIM recorded; N1-1 frozen mid-TDD (owner stopped the worker; WIP left dirty, patches under .cache/n1-1-wip-*.patch). Next on resume: coordinator finishes N1-1 (red chain test -> bootstrap go-file feed), Codex review, integrate, re-pin source_cut, one live rb-native-trade-r1; then D4a per the claim.",
  "workers_note": "coordinator-authored two-line poller fix in tests/live/test_gen1_selected_rb_ball_gate.py:127,207 (test harness only; recorded here, no separate card)",
  "workers": [
    {
      "id": "battle-input",
      "owner": "integrated by coordinator (isolated Claude worker authored rounds 1-2)",
      "state": "done",
      "files": [
        "lua/tests/gen1_rb_ball_gate_inputs.lua",
        "tests/unit/test_gen1_selected_rb_ball_gate.py",
        "docs/gen1_reference/reviews/D1-RB-implementation-successor.md"
      ],
      "next_action": "None; integrated MODEL ONLY. R7 live run is the physical check.",
      "reuse_decision": "game-specific test driver (R/B lab route facts); 're-pulse until observed acceptance' stays local until the parcel module becomes a second consumer",
      "receipt": "docs/gen1_reference/reviews/D1-RB-implementation-successor.md",
      "independent_review_refs": [
        "Codex headless REVIEW cx-d02ec69d round 1: REJECT (enemy-first prompt stall) \u2014 resolved",
        "Codex headless REVIEW cx-f22e3dde round 2: ACCEPT-WITH-NOTES for one R7 attempt"
      ]
    },
    {
      "id": "r6-source-check",
      "owner": "contextual Codex peer Gen1-CodexPeer (task cx-ccffd08c, closed)",
      "state": "done",
      "files": [
        ".cache/pret/pokered/home/window.asm",
        ".cache/pret/pokered/engine/battle/core.asm",
        ".cache/pret/pokered/home/vblank.asm",
        ".cache/pret/pokered/engine/joypad.asm"
      ],
      "next_action": "None; reconciled 4 accepted / 2 nuances (b: last-VBlank pulse survives; d: index 2->1 also on B-cancel, wPlayerSelectedMove is the strict accept write).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (reconciliation paragraph)",
      "independent_review_refs": [
        "coordinator reconciliation against pokered 405b624 home/window.asm, engine/battle/core.asm:2620-2670, engine/joypad.asm"
      ]
    },
    {
      "id": "takeover-drift-check",
      "owner": "OMP live pid 47172 (deepseek-v4.1-flash; task cx-3c0b00ba, closed)",
      "state": "done",
      "files": [
        "docs/gen1_reference/reviews/R0-supplied-contract-successor.md",
        ".cache/current-cards-final.xml",
        "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md"
      ],
      "next_action": "None. XML 188/0/0/0; parcel hashes EQUAL; R0 working copy 88aec118... differs from the frozen supplied-input hash 4dadeb79... as expected (the dirty file is the correction candidate).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (TK-1 line)",
      "independent_review_refs": [
        "coordinator sha256sum cross-check at takeover (parcel Lua f2a3c0f6..., unit ae2ed205...)"
      ]
    },
    {
      "id": "shared-hud",
      "owner": "released (/root/rb_mute_sol)",
      "state": "done",
      "files": [
        "lua/hud.lua",
        "lua/gen1_hud_service.lua",
        "tests/unit/test_shared_hud_transients.py",
        "tests/unit/test_gen1_hud_client.py",
        "docs/gen1_reference/reviews/SHARED-HUD-successor.md"
      ],
      "next_action": "None; integrated at c647f91. Physical pixel-expiry proof remains an open limit, not a worker.",
      "reuse_decision": "shared: existing HUD serves GB/GBA clients; viewport parameters stay adapters",
      "receipt": "docs/gen1_reference/reviews/SHARED-HUD-successor.md",
      "independent_review_refs": [
        "coordinator-verified current-card peer review recorded in transition archive"
      ]
    },
    {
      "id": "orchestration-hooks",
      "owner": "released (/root/rc_hooks_sol)",
      "state": "blocked",
      "files": [
        "tools/agent_work_guard.py",
        "tools/install_agent_work_hooks.py",
        "tests/unit/test_agent_work_guard.py",
        "docs/agents/HOOKS_SETUP.md"
      ],
      "next_action": "Owner approves Codex native /hooks trust through the host UI; then verify one actual host event fires.",
      "reuse_decision": "shared: generic ledger/policy paths and Codex/Claude hook adapters",
      "receipt": "docs/agents/HOOKS_SETUP.md",
      "independent_review_refs": [
        "coordinator-verified current-card peer review recorded in transition archive"
      ],
      "blocked_reason": "Human-only native hook trust step; no bypass."
    },
    {
      "id": "parcel",
      "owner": "integrated into git by coordinator as part of D2 (candidate files now tracked; menu_kind contract under revision in D2-LUA)",
      "state": "done",
      "files": [
        "lua/tests/gen1_rb_parcel_inputs.lua",
        "tests/unit/test_gen1_rb_parcel_inputs.py",
        "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md"
      ],
      "next_action": "D2-LUA amends the menu_kind branch: 'unknown' idles; 12 existing model tests stay green plus red tests from the spec.",
      "reuse_decision": "game-specific adapter for pinned R/B routes; shared host and HUD reused",
      "receipt": "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md (12/12 modeled, hashes f2a3c0f6.../ae2ed205... at integration)",
      "independent_review_refs": [
        "prior coordinator source review recorded in the parcel report",
        "P-2b audit cx-a4e7afad (wCurItem trap, predicates)",
        "D2-LUA-SPEC cx-2b893131 (none-acts finding)"
      ]
    },
    {
      "id": "r7-prep",
      "owner": "Sonnet 5 worker (done)",
      "state": "done",
      "files": [
        ".cache/d1-rb-starter-rival-r6-summary.json",
        "tests/live/test_gen1_selected_rb_ball_gate.py",
        "tests/live/gen1_selected_scenario.py"
      ],
      "next_action": "None; invocation reconstructed (rb_starter_rival(owned, emulator, base_config, limit=180); 300% is SelectedRun default; summary self-written; console tee'd; preflight refuses existing owned root and self-checks hashes).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (R7 launch note)",
      "independent_review_refs": [
        "coordinator cross-checked against tests/live/gen1_selected_scenario.py:286,340-363,595-607 and test_gen1_selected_rb_ball_gate.py:56,132"
      ]
    },
    {
      "id": "e1-title-card",
      "owner": "Sonnet 5 worker (done)",
      "state": "done",
      "files": [
        "tests/gen1_release_requirements.json",
        "tools/verify_gen1_release.py"
      ],
      "next_action": "None; finding recorded. Next E card needs a nine-part claim: boot the browser-patched Red ROM through existing prepare/launch/SelectedRun (emulator lane), independent of BI-1/N2.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (E-1 line)",
      "independent_review_refs": [
        "coordinator spot-check: tools/verify_gen1_release.py:264 empty-proofs failure; RC_CHECKLIST.md:370,402"
      ]
    },
    {
      "id": "tk2-r7-launch-facts",
      "owner": "OMP live pid 47172 (done)",
      "state": "done",
      "files": [
        "tests/live/gen1_selected_scenario.py",
        "tests/live/test_gen1_selected_rb_ball_gate.py"
      ],
      "next_action": "None; six literal grep lines confirmed R7-PREP.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (R7 launch note)",
      "independent_review_refs": [
        "Sonnet R7-PREP and coordinator reading of gen1_selected_scenario.py:286,294,342,606"
      ]
    },
    {
      "id": "e2-claim-record",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-038bf6e4)",
      "state": "done",
      "files": [
        "tests/gen1_release_requirements.json",
        "tests/integration/test_gen1_browser_patcher.py",
        "server/bizhawk_launch.py"
      ],
      "next_action": "None. Claim record received; READY withheld: reapply-noop contract conflict (browser refuses reapply at tests/browser/gen1_patcher.cjs:46 / patcher.js:286 while the manifest case is a no-op) needs an owner decision; a new live gate must not use SelectedRun unchanged (hardcoded prepared ROM path, gen1_selected_scenario.py:404-444).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (E-2 line)",
      "independent_review_refs": [
        "coordinator spot-check of manifest row 4605-4622 proofs=[] and verify_gen1_release.py:259-265"
      ]
    },
    {
      "id": "p1-parcel-prereq",
      "owner": "Sonnet 5 worker (done)",
      "state": "done",
      "files": [
        "lua/tests/gen1_scripted_new_game.lua",
        "tests/live/gen1_scripted_host.py",
        "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md"
      ],
      "next_action": "None; 'raw menu producer' = route_point() lacking 14 fields (bag/money/event bits/mart script/menu cluster) + three hardcoded rb-starter-rival literals (gen1_scripted_new_game.lua:86, gen1_scripted_host.py:18,47-48, gen1_selected_scenario.py:304-306) + menu_kind derivation audit.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (P-1 line)",
      "independent_review_refs": [
        "coordinator cross-check against gen1_scripted_new_game.lua:51-65,86 and the parcel report L9/L18"
      ]
    },
    {
      "id": "p2a-point-fields",
      "owner": "integrated by coordinator (OMP authored)",
      "state": "done",
      "files": [
        "lua/tests/gen1_rb_point_fields.lua",
        "tests/unit/test_gen1_rb_point_fields.py",
        "lua/tests/gen1_scripted_new_game.lua"
      ],
      "next_action": "None; integrated MODEL ONLY. item_id stays raw wCurItem until D2-LUA derivation; list_scroll_offset/menu_watch_oob/font_loaded to be added in D2-LUA.",
      "reuse_decision": "game-specific R/B WRAM decoders in a small pure module; the shared scripted host only gains additive point fields",
      "receipt": "tests/unit/test_gen1_rb_point_fields.py (4 passed)",
      "independent_review_refs": [
        "Codex headless REVIEW cx-4754b1c0: ACCEPT-WITH-NOTES (CUT B) \u2014 event bits 35/56/57, BCD, bag layout, facing, symbols verified against pokered 405b624"
      ]
    },
    {
      "id": "p2b-menu-kind-audit",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-a4e7afad)",
      "state": "done",
      "files": [
        ".cache/pret/pokered/scripts/ViridianMart.asm",
        "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md"
      ],
      "next_action": "None; findings recorded in the guide P-2b line and folded into the P-2a-2/D2-LUA specs.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (P-2b line)",
      "independent_review_refs": [
        "coordinator verified home/list_menu.asm:417 wCurItem overwrite and data/items/marts.asm:4-5 inventory order"
      ]
    },
    {
      "id": "d2-claim-draft",
      "owner": "Sonnet 5 worker (done)",
      "state": "done",
      "files": [
        "tests/gen1_release_requirements.json",
        "tests/live/gen1_scripted_host.py",
        "tests/live/gen1_selected_scenario.py"
      ],
      "next_action": "None. Record accepted by coordinator: parcel module resumes in the same process after lab-loss-complete (map 0x28, oak_got_parcel false; gen1_rb_parcel_inputs.lua:125-128), terminal phase first-ball-readback (:99); chained rb-parcel route mode is the smallest plumbing; ball-gate rows gameplay.red/blue.ball-gate (manifest :2905/:3165, proofs=[]); server flips pokeballs_obtained per player from has_pokeballs (server/state.py:388-389).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (D2 line)",
      "independent_review_refs": [
        "coordinator cross-check of gen1_scripted_host.py:18,47-49,115 and gen1_selected_scenario.py:304-306,359,447-448,548-549"
      ]
    },
    {
      "id": "d2-host",
      "owner": "integrated by coordinator (Sonnet worker authored rounds 1-2)",
      "state": "done",
      "files": [
        "tests/live/gen1_scripted_host.py",
        "tests/live/gen1_selected_scenario.py",
        "tests/live/test_gen1_selected_rb_ball_gate.py",
        "tests/unit/test_gen1_scripted_route_modes.py"
      ],
      "next_action": "None; integrated MODEL ONLY. Note P3: add lua/tests/gen1_rb_point_fields.lua to SelectedRun source_files (gen1_selected_scenario.py:358-367) in D2-LUA.",
      "reuse_decision": "shared scripted-host infrastructure (route-mode plumbing, chaining contract); the parcel module and point fields stay R/B-specific",
      "independent_review_refs": [
        "Codex headless REVIEW cx-9297dfc8 round 1: REJECT (activation oracle, settlement wait)",
        "Codex headless REVIEW cx-4754b1c0 round 2: ACCEPT-WITH-NOTES (CUT A)"
      ],
      "receipt": "tests/unit/test_gen1_scripted_route_modes.py (9 passed) + docs/gen1_reference/RC_MASTER_GUIDE.md D2 rows"
    },
    {
      "id": "ft1-fastest-text",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-348939ba)",
      "state": "done",
      "files": [
        ".cache/pret/pokered/engine/menus/options.asm",
        "tools/verify_gen1_release.py"
      ],
      "next_action": "None; facts recorded in the guide FT-1 line.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (FT-1 line)",
      "independent_review_refs": [
        "coordinator cross-check against D1-RB-claim-successor.md:48 and server/upr_settings.py:269-280"
      ]
    },
    {
      "id": "ft2-claim-record",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-5cf6888a)",
      "state": "done",
      "files": [
        "server/gen1_upr_pipeline.py",
        "server/upr_settings.py",
        "tests/live/test_gen1_native_selected_fresh.py"
      ],
      "next_action": "None. READY withheld: needs owner scope decision (new Manager API branch) and D2's release of gen1_selected_scenario.py.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (FT-2 line)",
      "independent_review_refs": [
        "coordinator spot-check: server/manager.py allowed keys and clean_contract at :755-791; gen1_run_config.py:64-111 prepared_cartridges path"
      ]
    },
    {
      "id": "d2-lua-spec",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-2b893131)",
      "state": "done",
      "files": [
        "lua/tests/gen1_rb_parcel_inputs.lua",
        "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md"
      ],
      "next_action": "None; spec handed to D2-LUA. Its blocker (none != wait in the frozen parcel module) is resolved by an explicit 'unknown' idle kind + module amendment in D2-LUA.",
      "reuse_decision": "research/spec only; implementation follows as D2-LUA once P-2a releases the bootstrap",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (D2-LUA-SPEC line)",
      "independent_review_refs": [
        "coordinator read of gen1_rb_parcel_inputs.lua:91-95,101-123,196-198 confirming the none-acts behaviour"
      ]
    },
    {
      "id": "d2-lua",
      "owner": "integrated by coordinator (isolated Claude worker authored)",
      "state": "done",
      "files": [
        "lua/tests/gen1_scripted_new_game.lua",
        "lua/tests/gen1_rb_mart_signature.lua",
        "lua/tests/gen1_rb_parcel_inputs.lua",
        "lua/tests/gen1_rb_point_fields.lua",
        "tests/unit/test_gen1_rb_mart_signature.py",
        "tests/unit/test_gen1_scripted_chain.py",
        "tests/unit/test_gen1_rb_parcel_inputs.py",
        "tests/live/gen1_selected_scenario.py"
      ],
      "next_action": "None; integrated MODEL ONLY (82 model tests). Owner capped harness investment: coordinator review only for this test-only cut; the single rb-parcel live run is the real check.",
      "reuse_decision": "shared: chaining in the scripted host bootstrap; game-specific: Mart signature table, parcel module, R/B decoders",
      "receipt": "tests/unit/test_gen1_scripted_chain.py + test_gen1_rb_mart_signature.py + test_gen1_rb_parcel_inputs.py (82 passed incl. point fields/route modes)",
      "independent_review_refs": [
        "coordinator diff review 2026-09-14 (spec by Gen1-CodexPeer cx-2b893131; no second headless review by owner direction to cap harness spend)"
      ]
    },
    {
      "id": "p2a-tests",
      "owner": "OMP live pid 47172 (done; task cx-7b7c35bd)",
      "state": "done",
      "files": [
        "tests/unit/test_gen1_rb_point_fields.py"
      ],
      "next_action": "None; 7 passed, ruff clean, sha256 29d77bf91ca3b115ab46f59b705d74a1cddb82fc5160403653ce53bf836cbd20; committed with D2-LUA.",
      "reuse_decision": "test-only",
      "receipt": "tests/unit/test_gen1_rb_point_fields.py (7 passed)",
      "independent_review_refs": [
        "tests specified verbatim by the coordinator from review cx-4754b1c0 suggestions"
      ]
    },
    {
      "id": "d3-claim-draft",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-b9f3d938)",
      "state": "done",
      "files": [
        "server/state.py",
        "lua/games/gen1_rby.lua",
        "server/gen1_wild_encounter_runtime.py"
      ],
      "next_action": "None; record condensed into the guide D3 row. READY WAIT(D2-LUA integrated, D2 live activation receipts, D3-PATH).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (D3 claim row)",
      "independent_review_refs": [
        "coordinator spot-check of gen1_scripted_host.py ROUTE_MODULES and the observer composition in lua/gen1_acquisition_observers.lua"
      ]
    },
    {
      "id": "d3-path",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-0406d784)",
      "state": "done",
      "files": [
        ".cache/pret/pokered/maps/ViridianCity.blk",
        ".cache/pret/pokered/data/maps/objects/ViridianCity.asm"
      ],
      "next_action": "None; waypoints recorded in the guide D3 row for whenever D3 is resumed. D3 itself is PARKED by owner direction (harness spend capped).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (D3 row, D3-PATH waypoints)",
      "independent_review_refs": [
        "coordinator accepted as SOURCE-derived static terrain proof; live NPC positions unobserved"
      ]
    },
    {
      "id": "wb1-wild-assembly",
      "owner": "integrated by coordinator (isolated Claude worker authored)",
      "state": "done",
      "files": [
        "lua/gen1_acquisition_observers.lua",
        "lua/gen1_observation_loop.lua",
        "lua/gen1_client_entry.lua",
        "lua/gen1_wild_encounter_observer.lua",
        "tests/unit/test_gen1_observation_loop.py",
        "tests/unit/test_gen1_wild_assembly.py"
      ],
      "next_action": "None; integrated MODEL ONLY. The next rb-parcel live run (after P2A-1 releases the client Lua) is the physical check of the fixed capture/wild path.",
      "reuse_decision": "shared observer/loop lifecycle (production); the wild site data stays the Gen 1 adapter",
      "receipt": "tests/unit/test_gen1_wild_assembly.py (red replay) + 165 passed across loop/acquisition/native/inventory sets",
      "independent_review_refs": [
        "coordinator diff review: strict in_step equality consistent with BATTLE_FORCE_FAINT_WINDOW.md section 10 and instruction_executor.lua:38; live receipts show every engine signal one frame below its observation (8 samples, R7 + parcel r2)"
      ]
    },
    {
      "id": "p2a-claim",
      "owner": "Sonnet 5 worker (done)",
      "state": "done",
      "files": [
        "server/gen1_service_continuity.py",
        "docs/gen1_reference/reviews/D0b-save-witness-boundary-successor.md"
      ],
      "next_action": "None; record condensed into the guide P2a row. READY WAIT(WB-1 lane; RB SavePartyAndDexData ret offset).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (P2a claim row)",
      "independent_review_refs": [
        "coordinator spot-check of gen1_service_continuity.py:87-89 refusal and gen1_engine_signals.py:29"
      ]
    },
    {
      "id": "p2a-1",
      "owner": "integrated by coordinator (isolated Claude worker authored A+B; C not started by design)",
      "state": "done",
      "files": [
        "server/gen1_engine_signals.py",
        "server/gen1_engine_signal_runtime.py",
        "server/gen1_faint_runtime.py",
        "server/gen1_service_continuity.py",
        "server/gen1_runtime_admission.py",
        "server/protocol.py",
        "server/gen1_observation_runtime.py",
        "server/gen1_held_faint.py",
        "server/gen1_native_progress.py",
        "data/games/gen1_rby/engine_signals.json",
        "lua/gen1_engine_signals.lua",
        "tests/unit/test_gen1_engine_signals.py",
        "tests/unit/test_gen1_service_continuity.py"
      ],
      "next_action": "None; save witness + server checkpoint integrated MODEL ONLY. Resume admission (C) re-scoped to the run boundary (P2A-2).",
      "reuse_decision": "shared lifecycle/state in server modules (no game_id branches); Gen 1 facts only in data/games/gen1_rby and the engine-signal adapter; reuses gen1_full_save reader and the injected sha256",
      "receipt": "tests/unit/test_gen1_engine_signals*.py, test_gen1_engine_signal_runtime.py, test_gen1_service_continuity.py (98 passed in the set; full suite 7928/0 by the worker)",
      "independent_review_refs": [
        "coordinator re-ran the set + generator --check + lupa; site bytes match P2A-SITE (Gen1-CodexPeer cx-b5dce65a)"
      ]
    },
    {
      "id": "p2a-2-seams",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-a45bfe7d)",
      "state": "done",
      "files": [
        "server/manager.py",
        "server/gen1_run_config.py",
        "server/gen1_initial_observation.py"
      ],
      "next_action": "None; recorded in the guide P2A-2 seams row. Implementation slice dispatches after parcel r4 releases the lane.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (P2A-2 seams row)",
      "independent_review_refs": [
        "coordinator spot-check of gen1_initial_observation.py:155-163 guard and bizhawk_launch.py:73-104 ownership"
      ]
    },
    {
      "id": "p2a-2s",
      "owner": "integrated by coordinator (isolated Claude workers authored)",
      "state": "done",
      "files": [
        "server/gen1_run_resume.py",
        "server/manager.py",
        "server/gen1_run_config.py",
        "server/gen1_runtime_state.py",
        "server/gen1_runtime.py",
        "server/gen1_initial_observation.py",
        "server/gen1_faint_runtime.py",
        "server/gen1_wild_encounter_runtime.py",
        "tests/unit/test_gen1_run_resume.py",
        "tests/unit/test_gen1_resume_enrollment.py",
        "tests/integration/test_manager_gen1_resume.py"
      ],
      "next_action": "None; integrated MODEL ONLY. Known gap: identity registry not imported (P2A-3). Independent review after P2A-3, then one live resume check.",
      "reuse_decision": "shared lifecycle/state in server modules (typed SoulLinkState import, journal_reader); Gen 1 facts stay in adapters",
      "receipt": "tests/unit/test_gen1_run_resume.py, test_gen1_resume_enrollment.py, test_gen1_resume_client.py, tests/integration/test_manager_gen1_resume.py (27 + 23 new tests; full unit suite 7979/0 by both workers; coordinator re-ran 367 affected + 7 integration)",
      "independent_review_refs": [
        "coordinator checks only so far; Codex headless REVIEW scheduled after P2A-3 on the combined resume diff"
      ]
    },
    {
      "id": "p2a-2c",
      "owner": "integrated by coordinator (isolated Claude workers authored)",
      "state": "done",
      "files": [
        "lua/gen1_client_entry.lua",
        "lua/gen1_continue_observer.lua",
        "lua/gen1_initial_observation.lua",
        "server/bizhawk_launch.py",
        "server/runtime_launcher.py",
        "tools/launch_bizhawk.py",
        "server/gen1_launcher.py"
      ],
      "next_action": "None; integrated MODEL ONLY. Known gap: identity registry not imported (P2A-3). Independent review after P2A-3, then one live resume check.",
      "reuse_decision": "shared launcher/bundle/save-import infrastructure; CONTINUE site data stays Gen 1",
      "receipt": "tests/unit/test_gen1_run_resume.py, test_gen1_resume_enrollment.py, test_gen1_resume_client.py, tests/integration/test_manager_gen1_resume.py (27 + 23 new tests; full unit suite 7979/0 by both workers; coordinator re-ran 367 affected + 7 integration)",
      "independent_review_refs": [
        "coordinator checks only so far; Codex headless REVIEW scheduled after P2A-3 on the combined resume diff"
      ]
    },
    {
      "id": "p2a-3-4",
      "owner": "integrated by coordinator (isolated Claude workers authored)",
      "state": "done",
      "files": [
        "server/gen1_faint_runtime.py",
        "server/gen1_initial_observation.py",
        "server/gen1_run_config.py",
        "server/gen1_run_resume.py",
        "server/gen1_runtime_state.py",
        "server/identity_registry.py",
        "tests/unit/test_gen1_faint_runtime.py",
        "tests/unit/test_gen1_resume_enrollment.py",
        "tests/unit/test_gen1_run_resume.py"
      ],
      "next_action": "None; integrated MODEL ONLY (8006/0 full suite). P2A-5 closes the three launcher/service gaps before the live round-trip.",
      "reuse_decision": "shared identity/lifecycle in server modules",
      "receipt": "tests/unit/test_gen1_run_resume.py, test_gen1_resume_enrollment.py, test_gen1_faint_runtime.py, test_gen1_rb_save_inputs.py, test_gen1_scripted_chain.py, test_gen1_scripted_route_modes.py",
      "independent_review_refs": [
        "coordinator checks; Codex headless REVIEW of the whole resume diff scheduled after P2A-5"
      ]
    },
    {
      "id": "rs-1-resume-harness",
      "owner": "integrated by coordinator (isolated Claude workers authored)",
      "state": "done",
      "files": [
        "lua/tests/gen1_rb_save_inputs.lua",
        "lua/tests/gen1_scripted_new_game.lua",
        "tests/live/gen1_scripted_host.py",
        "tests/live/gen1_selected_scenario.py",
        "tests/live/test_gen1_selected_rb_resume.py",
        "tests/unit/test_gen1_rb_save_inputs.py",
        "tests/unit/test_gen1_scripted_route_modes.py",
        "tests/unit/test_gen1_scripted_chain.py"
      ],
      "next_action": "None; integrated MODEL ONLY (8006/0 full suite). P2A-5 closes the three launcher/service gaps before the live round-trip.",
      "reuse_decision": "shared scripted-host plumbing; the save driver and CONTINUE geometry are Gen 1 route facts",
      "receipt": "tests/unit/test_gen1_run_resume.py, test_gen1_resume_enrollment.py, test_gen1_faint_runtime.py, test_gen1_rb_save_inputs.py, test_gen1_scripted_chain.py, test_gen1_scripted_route_modes.py",
      "independent_review_refs": [
        "coordinator checks; Codex headless REVIEW of the whole resume diff scheduled after P2A-5"
      ]
    },
    {
      "id": "p2a-5",
      "owner": "integrated by coordinator (isolated Claude worker authored)",
      "state": "done",
      "files": [
        "server/manager.py",
        "server/gen1_runtime.py",
        "lua/gen1_engine_signals.lua",
        "tests/integration/test_manager_gen1_resume.py",
        "tests/unit/test_gen1_runtime_server.py",
        "tests/unit/test_gen1_engine_signals_client.py"
      ],
      "next_action": "None; integrated MODEL ONLY (8010/0). Review of the whole resume diff pending.",
      "reuse_decision": "shared Manager/runtime lifecycle; Gen 1 signal adapter for the flush hook",
      "receipt": "tests/integration/test_manager_gen1_resume.py, tests/unit/test_gen1_runtime_server.py, tests/unit/test_gen1_engine_signals_client.py (5 new tests; 81 in the re-run set)",
      "independent_review_refs": [
        "Codex headless REVIEW of 6075af1..a99d8b4 (in progress)"
      ]
    },
    {
      "id": "p2a-6",
      "owner": "integrated by coordinator (isolated Claude workers authored)",
      "state": "done",
      "files": [
        "server/gen1_run_resume.py",
        "server/manager.py",
        "tests/unit/test_gen1_run_resume.py",
        "tests/unit/test_gen1_resume_enrollment.py",
        "tests/integration/test_manager_gen1_resume.py"
      ],
      "next_action": "None; integrated at 2064c60 (8021/0). Round-2 review pending.",
      "reuse_decision": "shared",
      "receipt": "tests/unit/test_gen1_run_resume.py, test_gen1_resume_enrollment.py, tests/integration/test_manager_gen1_resume.py, test_gen1_continue_observer.py, test_gen1_resume_client.py, test_gen1_engine_signals_client.py (105 in the re-run set)",
      "independent_review_refs": [
        "Codex REVIEW cx-9559ab65 round 1 REJECT (7 findings) \u2014 all addressed",
        "round 2 headless REVIEW pending"
      ]
    },
    {
      "id": "p2a-6c",
      "owner": "integrated by coordinator (isolated Claude workers authored)",
      "state": "done",
      "files": [
        "lua/gen1_continue_observer.lua",
        "lua/gen1_client_entry.lua",
        "lua/gen1_initial_observation.lua",
        "lua/gen1_engine_signals.lua",
        "tests/unit/test_gen1_continue_observer.py",
        "tests/unit/test_gen1_resume_client.py",
        "tests/unit/test_gen1_engine_signals_client.py"
      ],
      "next_action": "None; integrated at 2064c60 (8021/0). Round-2 review pending.",
      "reuse_decision": "shared client lifecycle; Gen 1 site data unchanged",
      "receipt": "tests/unit/test_gen1_run_resume.py, test_gen1_resume_enrollment.py, tests/integration/test_manager_gen1_resume.py, test_gen1_continue_observer.py, test_gen1_resume_client.py, test_gen1_engine_signals_client.py (105 in the re-run set)",
      "independent_review_refs": [
        "Codex REVIEW cx-9559ab65 round 1 REJECT (7 findings) \u2014 all addressed",
        "round 2 headless REVIEW pending"
      ]
    },
    {
      "id": "p2a-7",
      "owner": "integrated by coordinator (isolated Claude worker authored)",
      "state": "done",
      "files": [
        "server/gen1_run_resume.py",
        "server/manager.py",
        "tests/unit/test_gen1_run_resume.py",
        "tests/integration/test_manager_gen1_resume.py"
      ],
      "next_action": "None; integrated (8029/0). Round-3 review pending.",
      "reuse_decision": "shared",
      "receipt": "tests/unit/test_gen1_run_resume.py, tests/integration/test_manager_gen1_resume.py (11 new tests)",
      "independent_review_refs": [
        "Codex REVIEW cx-f0798287 round 2 (2 majors) \u2014 addressed; round 3 pending"
      ]
    },
    {
      "id": "p2a-8",
      "owner": "integrated by coordinator (isolated Claude worker authored)",
      "state": "done",
      "files": [
        "server/manager.py",
        "server/gen1_run_resume.py",
        "tests/unit/test_gen1_run_resume.py",
        "tests/integration/test_manager_gen1_resume.py",
        "tests/unit/test_manager_http_hardening.py"
      ],
      "next_action": "None; integrated (8032/0). Round-4 review pending.",
      "reuse_decision": "shared",
      "receipt": "tests/integration/test_manager_gen1_resume.py (+88), tests/unit/test_gen1_run_resume.py, tests/unit/test_manager_http_hardening.py",
      "independent_review_refs": [
        "Codex REVIEW cx-03a237b0 round 3 \u2014 addressed; round 4 pending"
      ]
    },
    {
      "id": "p2a-9",
      "owner": "integrated by coordinator (isolated Claude worker authored)",
      "state": "done",
      "files": [
        "server/manager.py",
        "tests/integration/test_manager_gen1_resume.py",
        "tests/unit/test_manager_http_hardening.py"
      ],
      "next_action": "None; integrated at 8ab25a7 (232 manager/resume tests; suite 8029 + the 3 RS-2 mid-edit transients since green).",
      "reuse_decision": "shared",
      "receipt": "tests/integration/test_manager_gen1_resume.py (+7 reservation tests)",
      "independent_review_refs": [
        "Codex REVIEW cx-69ce8923 round 4 finding A \u2014 addressed; final MODEL gate after the live check"
      ]
    },
    {
      "id": "rs-2",
      "owner": "integrated by coordinator (harness worker authored)",
      "state": "done",
      "files": [
        "lua/tests/gen1_rb_save_inputs.lua",
        "tests/unit/test_gen1_rb_save_inputs.py"
      ],
      "next_action": "None; integrated at 0e3292e (13 driver models). Live re-run after P2A-9 lands and the pin is reset.",
      "reuse_decision": "Gen 1 route facts",
      "receipt": "tests/unit/test_gen1_rb_save_inputs.py (13 passed)",
      "independent_review_refs": [
        "coordinator re-ran 25 in the driver/chain sets + lupa; fact of record = live r1 observation (save_status 2 mid-battle)"
      ]
    },
    {
      "id": "bi-2",
      "owner": "integrated by coordinator (Claude worker authored)",
      "state": "done",
      "files": [
        "lua/tests/gen1_rb_ball_gate_inputs.lua",
        "tests/unit/test_gen1_selected_rb_ball_gate.py",
        "docs/gen1_reference/reviews/D1-RB-implementation-successor.md"
      ],
      "next_action": "None; integrated. Latent hardening noted (index==0 gate before open-fight) \u2014 apply only if a live receipt shows it.",
      "reuse_decision": "game-specific test driver",
      "receipt": "tests/unit/test_gen1_selected_rb_ball_gate.py (33 passed; .cache/bi2-model.xml)",
      "independent_review_refs": [
        "coordinator re-ran 33 + lupa; source candidates enumerated in D1-RB-implementation-successor.md"
      ]
    },
    {
      "id": "rs-3",
      "owner": "integrated by coordinator (harness worker authored)",
      "state": "done",
      "files": [
        "lua/tests/gen1_rb_save_inputs.lua",
        "lua/tests/gen1_scripted_new_game.lua",
        "tests/unit/test_gen1_rb_save_inputs.py",
        "tests/unit/test_gen1_scripted_chain.py"
      ],
      "next_action": "None; integrated. Fact of record: SLink's companion patch adds a SLINK START-menu row (patch/gen1/tools/manifest.py:114-130), so wMaxMenuItem is 7 without the Pokedex / 8 with; SAVE stays index 3 / 4.",
      "reuse_decision": "Gen 1 route facts",
      "receipt": "tests/unit/test_gen1_rb_save_inputs.py (18 passed)",
      "independent_review_refs": [
        "coordinator re-ran 45 in the driver/chain/route sets + lupa"
      ]
    },
    {
      "id": "p2a-10",
      "owner": "integrated by coordinator (isolated Claude worker authored)",
      "state": "done",
      "files": [
        "server/gen1_run_resume.py",
        "tests/unit/test_gen1_run_resume.py"
      ],
      "next_action": "None; integrated (37 audit tests; suite 8049/0).",
      "reuse_decision": "shared",
      "receipt": "tests/unit/test_gen1_run_resume.py (+9)",
      "independent_review_refs": [
        "allowlist cited from durable_runtime.py:101,165,212,219,434 and gen1_runtime.py:417-419; coordinator re-ran 37"
      ]
    },
    {
      "id": "p2a-11",
      "owner": "integrated by coordinator (isolated Claude worker authored)",
      "state": "done",
      "files": [
        "server/manager.py",
        "tests/integration/test_manager_gen1_resume.py"
      ],
      "next_action": "None; integrated at 79f04a3 (8056/0). Round-5 finding A closed; a final MODEL gate review of 597f5ba..79f04a3 can be requested if desired.",
      "reuse_decision": "shared",
      "receipt": "tests/integration/test_manager_gen1_resume.py (+4; 251 manager/resume tests)",
      "independent_review_refs": [
        "Codex REVIEW cx-aa100faf round 5 finding A \u2014 addressed"
      ]
    },
    {
      "id": "ui-1-resume-button",
      "owner": "integrated by coordinator (Sonnet worker authored)",
      "state": "done",
      "files": [
        "server/templates/manager.html",
        "tests/unit/test_manager_dashboard_resume.py"
      ],
      "next_action": "None; integrated at 6f1f2a1 (template only; registry fields already reach the page).",
      "reuse_decision": "shared presentation",
      "receipt": "tests/unit/test_manager_resume_ui.py (7 passed; 154 manager tests)",
      "independent_review_refs": [
        "coordinator re-ran 39 manager UI/hardening tests"
      ]
    },
    {
      "id": "n1-claim",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-d5079544)",
      "state": "done",
      "files": [
        "server/gen1_receptionist_runtime.py",
        "patch/gen1/src/trade_receptionist.asm"
      ],
      "next_action": "None; claim recorded in the guide N1 row. N1-PATH audit next; implementation after P2A-11 frees the harness/host files.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (N1 claim row)",
      "independent_review_refs": [
        "coordinator spot-check of gen1_trade_rules.py:29-72 (one-mon pair eligibility) and gen1_receptionist_runtime.py:86-115"
      ]
    },
    {
      "id": "n1-path",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-2a1b5ed2)",
      "state": "done",
      "files": [
        ".cache/pret/pokered/maps/ViridianPokecenter.blk",
        ".cache/pret/pokered/data/maps/objects/ViridianPokecenter.asm"
      ],
      "next_action": "None; tables recorded in the guide N1 row and handed to N1-1.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (N1-PATH row)",
      "independent_review_refs": [
        "coordinator accepted as SOURCE-derived static terrain; NPC occupancy dynamic"
      ]
    },
    {
      "id": "n1-1",
      "owner": "coordinator (worker a0b11382536ae868f stopped by the owner mid-TDD)",
      "state": "frozen",
      "blocked_reason": "owner wrap-up 2026-09-14; WIP uncommitted",
      "files": [
        "lua/tests/gen1_rb_native_trade_inputs.lua",
        "tests/unit/test_gen1_rb_native_trade_inputs.py",
        "tests/live/test_gen1_selected_rb_native_trade.py",
        "tests/live/gen1_scripted_host.py",
        "tests/live/gen1_selected_scenario.py",
        "lua/tests/gen1_scripted_new_game.lua",
        "tests/unit/test_gen1_scripted_route_modes.py",
        "tests/unit/test_gen1_scripted_chain.py"
      ],
      "next_action": "Resume: make tests/unit/test_gen1_scripted_chain.py::test_native_trade_chain_hands_off_twice_and_feeds_the_go_file_to_the_point[a,b] green (2 failed / 44 passed at freeze; lupa clean; new files sha256 9eafdd49 lua, 7bfa134d live, b8853d4b unit; patches .cache/n1-1-wip-{tracked,new1,new2,new3}.patch be8ea531/21551ded/79740670/2610f4e2), then Codex review, integrate, re-pin, one live rb-native-trade-r1.",
      "reuse_decision": "shared scripted-host chain (N entries); Gen 1 route facts and trade-UI geometry in the module"
    },
    {
      "id": "n1-ui",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-abf5641a)",
      "state": "done",
      "files": [
        "patch/gen1/src/trade_receptionist.asm",
        "patch/gen1/src/trade_ui.asm",
        "patch/gen1/src/trade_prompt.asm"
      ],
      "next_action": "None; forwarded to N1-1 and recorded in the guide N1-UI row.",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (N1-UI row)",
      "independent_review_refs": [
        "coordinator accepted as SOURCE-derived from the companion patch sources and trade_coordinator.py"
      ]
    },
    {
      "id": "f0-claim",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-d782d831)",
      "state": "done",
      "files": [
        "tests/live/test_gen1_bare_speed.py",
        "lua/tests/test_gen1_bare_speed_gate.lua"
      ],
      "next_action": "None; recorded READY as an execution-only card (coordinator runs the selected-native speed gate once after P2A-11 commits).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (F0 claim row)",
      "independent_review_refs": [
        "coordinator spot-check: ACTIVE_THREE_X_MIN_FPS in tests/live/test_gen1_free_service.py:43-54; RC_LANE_B_STATUS.md:25,29"
      ]
    },
    {
      "id": "d4-claim",
      "owner": "contextual Codex peer Gen1-CodexPeer (done; task cx-03b34366)",
      "state": "done",
      "files": [
        "server/gen1_faint_runtime.py",
        "lua/gen1_held_faint.lua"
      ],
      "next_action": "None; recorded in the guide D4 claim row (D4a terminal-propagation lane chosen as the first slice).",
      "reuse_decision": "research only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (D4 claim row)",
      "independent_review_refs": [
        "coordinator spot-check: gen1_memorial.py last-member refusal and gen1_faint_runtime.py pokeballs_obtained gate cited by the claim match the R7/parcel-r6 physical reports"
      ]
    },
    {
      "id": "f0-run",
      "owner": "coordinator slink-63 (execution-only)",
      "state": "done",
      "files": ["tests/live/test_gen1_native_selected_fresh.py (read-only; run once)"],
      "next_action": "None; PASS recorded in the F0 result row. No retune.",
      "reuse_decision": "execution only (criteria unchanged)",
      "receipt": ".cache/native-selected-fresh-q55jdxn0/summary.json sha256 ebc35bf7...c113; console .cache/f0-rb-6931fdf-r1-console.txt sha256 18dbaa14...7047 (1 passed in 47.49s)",
      "independent_review_refs": [
        "gate thresholds fixed before the run by F0 claim cx-d782d831; performance_failures=[] is the harness verdict"
      ]
    },
    {
      "id": "tk-5",
      "owner": "OMP live pid 47172 (done; task cx-259ea75b)",
      "state": "done",
      "files": ["ruff.toml (read-only; ruff check . reported)"],
      "next_action": "None; lint drift fact recorded (TK-5 row).",
      "reuse_decision": "fact check only",
      "receipt": "docs/gen1_reference/RC_MASTER_GUIDE.md#r6-diagnosis-and-next-action (TK-5 row)",
      "independent_review_refs": [
        "coordinator: three-line literal card, outputs copied verbatim; not re-run"
      ]
    }
  ]
}
```
<!-- AGENT_CHECKPOINT_END -->


Updated at the owner-authorized resume after R6; see machine checkpoint timestamp. This section is current; [past transition receipts](RC_SUCCESSOR_TRANSITIONS_2026-09-13.md) are history, not active grants.

- **Coordinator/integrator:** Claude Opus 5 session `9a7ac120-04eb-489f-8fd1-c9ecb67b31a6` (peer name `slink-63`), appointed by the owner's explicit resume authorization of 2026-09-13/14; the retired coordinator (Codex `01a09ae0-…`) is now the contextual peer `Gen1-p2` only. Roles, not providers, carry authority: the coordinator alone grants file/live ownership, reviews receipts and integrates; isolated workers implement bounded cards; independent reviewers never author the cut they review; OMP takes short bounded checks; the contextual peer supplies source support.
- **Canonical checkout:** `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, `gen1/rc`, HEAD `59b6b0b` at takeover (docs); reviewed code freeze `c647f9126e79909f2b5976beec65d7b3beedd737`; product core baseline `15727ec`. Verified at takeover: dirty state is exactly the four preserved candidates below; parcel Lua/unit hashes match their report; R6 receipts match the D1 physical report; no EmuHawk/pytest/Java process. Root master is not the RC checkout.
- **Current input authority:** unchanged — scripts and normal game buttons only; no Computer Use, no RAM/register/SaveRAM/savestate/CPU staging; read-only game-state inspection allowed; each live run needs the coordinator's sole-lane grant. Route tests request 300%; explicit 100% only for qualification.
- **Live state:** lane free. Proved live so far (controlled-scripted): lab checkpoint (R7), parcel/first ball/ball-gate (parcel r6), in-game save witness (r4), session resume (r5). Mute is DONE; Yellow-specific work deferred.
- **Dispatch:** fully specified cards may be ACTIVE conditional on the first matching Git/hash/scope acknowledgment; a mismatch means HOLD.

### R6 diagnosis and next action

**R6 root cause (SOURCE FACT for the game path; hypothesis for the driver until the red model test confirms it).** Both cartridges failed at the identical point (`Y12/X5/max3/index2`, Growl PP 40). The driver's `press()` fires on `frame%16<2`: `Down` is accepted inside frame `16k` (`HandleMenuInput_ .loop2` polls without `DelayFrame`), the next step already reads `wCurrentMenuItem==2`, and `press("A", 16k+1)` emits a one-frame `A` immediately after the cursor move. pokered is then in `SelectMenuItem_CursorDown → SelectMenuItem → HandleMenuInput_ .loop1 → PlaceMenuCursor → Delay3` (`home/window.asm:14-19`, `engine/battle/core.asm:2702-2709`); `_Joypad` is not called for ≥3 frames and `hJoyInput` is overwritten every VBlank (`home/vblank.asm:77-79`), so the pulse is dropped. The driver then idles 600 frames because it treated *emitted* as *accepted* (`gen1_rb_ball_gate_inputs.lua:110-123`). Attempt 5's repeated pulses used Growl (PP 39), which corroborates the mechanism. The game's own acceptance write is `wCurrentMenuItem` 2→1 (`core.asm:2624-2626`) followed by the PP drop.

**R6-SRC reconciliation (Gen1-CodexPeer, task cx-ccffd08c, 2026-09-14):** (a)(c)(e)(f) confirmed with citations. Nuance (b): a pulse sampled on the final delayed VBlank survives into the next poll (`home/vblank.asm:77-79`, `engine/joypad.asm:5-20`); R6's pulse was on the first post-Down frame, so it was still dropped. Nuance (d): `wCurrentMenuItem` is decremented before validation and on B-cancel too (`engine/battle/core.asm:2620-2626`); the strict accept write is `wPlayerSelectedMove` (`:2662-2670`) and PP decrements later (`:3117-3122`, `decrement_pp.asm:36-42`). The driver never presses B inside the move menu and asserts Growl PP>0 first, so the index-1 window is only reachable by real acceptance; PP drop plus the 600-frame bound remain the acceptance oracle. `wPlayerSelectedMove` is recorded as the stronger signal to adopt if R7 ever stalls at index 1.

| Item | Verified state / next owner action |
| --- | --- |
| UI-1 integrated | Dashboard: "Resume as a new run" disclosure on stopped, un-resumed runs (posts `/api/runs/gen1` with `resume_from`; 409 reasons shown verbatim), `resumed from`/`resumed by` badges, Start disabled on a resumed predecessor, `--resume-save` hint on the launcher panel. Template only; 7 string-presence tests. |
| F0 claim (FPS qualification) | Gen1-CodexPeer record. No manifest performance row exists; the contract lives in executable checks: `ACTIVE_THREE_X_MIN_FPS=173.0` (`tests/live/test_gen1_free_service.py:43-54`), targets 59.7275 @100% / 179.1825 @300%, 1× floor 59.130, quiet-3× floor 177.391; phase average AND every 600-frame window must clear; FrameSkip 0. Bare-speed is a negative control (no client) and cannot qualify the product. The product gate for the current client is `tests/live/test_gen1_native_selected_fresh.py::test_manager_selected_native_pair_free_runs_fresh_bedroom` (Manager companions + downloaded launcher + native runtime; N=3 active-3× windows per player). Last documented pass at `90853f5`: R/B a 173.203/173.906/173.543, b 173.860/173.456/173.513; the 0.070 miss was one Y/Y window (172.930) — R/B passed. No post-WB-1/P2A measurement exists; hook registration cost is not established as zero. **Coordinator decision:** READY as execution-only — one frozen R/B invocation after P2A-11 commits, all criteria unchanged, report min/median/max per player, a miss is recorded as FAIL and presented to the owner (no retune, no rerun). Receipt `.cache/native-selected-fresh-*/summary.json` (+ `performance_failures` / `harness-error.json` on failure). Bedroom workload only: save/resume/trade paths are not timed by it. |
| N1-UI | Companion trade UI (SOURCE): availability query sets no `wJoyIgnore`/`wTextBoxID`, ≤30 frames, overlay marker restored after (`trade_receptionist.asm:140-184,235-239`); main menu Y2/X1/max 2, rows SLINK TRADE/CABLE CLUB/CANCEL (`:270-298`, `trade_ui.asm:23-46`); party list "TRADE WHICH?" Y3/X1/max popcount(mask)−1, row 0 = first eligible physical slot, B cancels (`:300-390`); every notice ends in `prompt` (`:418-429`) — "Trade offer sent" is an accepted OFFER, not consent. Partner prompt waits for released A/B twice; Yes/No T=$14 Y8/X15 index 0 = YES; screen restored silently after (`trade_prompt.asm:77-99`). No-input gate = held/native_reattach/recovery + pending native/prompt/receptionist phases (`gen1_native_runtime.lua:339-353,446-448`); routine: 100-frame delay, `InternalClockTradeAnim`, `TryEvolvingMon`, `SavePartyAndDexData`, map restored in place (`native_trade.asm:158-204`); received mon in slot 0 on each side. Verifier: `components["gen1-receptionist"]`, journal namespace `paired-trade` (applied/verified per player, `link_committed` clears `active_trade`), reuse `test_gen1_paired_native_trade.py:76-145` assertions with the selected host's window policy. |
| N1-PATH | Verified x-first tables (pokered 405b624, decoded cell-by-cell): Mart exit `(3,7)` → city `(29,19)`; city `{29,20},{19,20},{19,26},{23,26},{23,25}` (door → Center `(3,7)`; never column 23 above row 26, wall at `(22,25)`); Center `{3,4},{11,4},{11,3}` then face Up (row 6 blocked at `(6,6)`/`(7,6)`); B waits at `(5,5)` via `{3,5},{5,5}`. Hazards: city walkers `(13,20)`/`(30,25)`; the Center gentleman walks column x10 and can occupy `(10,4)` — bounded wait, never blind A. Receptionist = object 4 at `(11,2)`, typed dispatch `script_cable_club_receptionist` intercepted by the companion; Center map script only tries the serial link and enables auto text boxes. Precondition: the Mart purchase UI must be closed first (parcel terminal fires inside it). |
| N1 claim (native trade, first slice) | Gen1-CodexPeer record. Rows served: `trade.{red,blue}.canonical-physical/.durability/.foreground-overlay/.blob-fidelity` (first selected-path transaction evidence; not full closure). **Starters are tradeable** — eligibility needs one ALIVE linked pair with both halves in party, `pc_trade_npc` enabled, no pending work (`server/gen1_trade_rules.py:29-72`; one-mon pair modelled at `tests/unit/test_gen1_trade_rules.py:24-47`); D3 catch NOT required. Nearest counter: Viridian Pokémon Center (city entrance (23,25), interior map $29, receptionist object 4 at (11,2), interact from (11,3) facing Up). Companion patch offers SLINK TRADE / CABLE CLUB / CANCEL after an availability query (`patch/gen1/src/trade_receptionist.asm:1-15,44-60,119-176,270-298`); only ONE player initiates (server refuses concurrent visits, `gen1_receptionist_runtime.py:95`), the partner consents through the native prompt (`trade_prompt.asm:77-99`). Native execution stays the production executor's owned transaction (`lua/gen1_native_trade_executor.lua:187-208`, `gen1_native_execution.py:87-111`); the verifier waits for both applied + file-verified results and logical migration (`gen1_native_policy.py:141-171`, `gen1_trade_rules.py:74-85`). HYPOTHESIS: `rb-native-trade` chain starter → parcel → receptionist module (A initiates, B waits at a safe cell), optional START→SAVE on both afterwards. Files: new `lua/tests/gen1_rb_native_trade_inputs.lua`, unit + live tests, host/scenario/bootstrap, report. Recovery rows: only 'before PREPARE' is now addressable by clean resume; before/after COMMIT and during animation/save remain open. (9) READY WAIT(N1-PATH audit; P2A-11 release of shared files). |
| P2A review round 5 | Codex `cx-aa100faf` on `c57de64..597f5ba`: B (lifecycle allowlist) and C (harness commits) resolved; A still MAJOR on the 120 s edge — timeout normalisation, stop and archive keep the old `starting_token`, so a slow spawn's final commit can write `running` over stopped/archived (`manager.py:346-352,501-522,771,785,748-750`), and an expired start's late failure overwrites a newer reservation (`:163-168,732-741`). REJECT (MODEL). P2A-11 dispatched: token cleared on every non-owner transition; token-gated failure cleanup. |
| **Resume round-trip attempt 5 — RESUME PASS (CONTROLLED-SCRIPTED)** | `rb-resume-checkpoint-observed` at `597f5ba`: save → clean stop → `resume_from` accepted → save files imported after digest verification → both clients CONTINUE-booted and enrolled (`gen1-resume.enrolled` digests = predecessor witnesses) → `oaks_lab` link ALIVE with species 1/4 carried across, identities re-minted, no activations/deaths, clean cleanup. First physical proof that a run survives a session boundary. Independently validated (TK-3, OMP): receipt hashes, status, lineage and links; coordinator matched the predecessor journal's `save_witness` digests (rev 341/531) to the resumed enrollment digests — both MATCH. Open (MODEL only): post-resume gameplay (inherited-pair faint, catch with inherited activation) and the refusal cases. Receipts summary `b70b0c78…`, resumed `c50bb01d…`, console `fa7ccf25…`; [D1 physical report](reviews/D1-RB-physical-successor.md). |
| **Resume round-trip attempt 4 — save phase PASS (CONTROLLED-SCRIPTED)** | Both players saved in-game via START→SAVE→YES; server-acked `save_witness` for both (A rev 558, B rev 588); SaveRAM flushed; clean stop — first physical proof of the P2A-1 witness. Resume creation was refused: the only post-witness event for A is `runtime_suspended` (the clean stop's lifecycle record), which the inverted P2A-7 rule counts as gameplay → false hold. P2A-10: allowlist lifecycle events from source. Summary `7b02af23…`, resumed `f571f0fc…`. |
| START menu fact | The companion patch (`patch/gen1/tools/manifest.py:114-130`) adds a **SLINK** row after EXIT: `wMaxMenuItem` is 7 without the Pokédex and 8 with (vanilla 6/7); SAVE remains index 3/4. Confirmed in the r3 cartridge bytes at DrawStartMenu (`$710B`). Any driver counting rows from `wMaxMenuItem` must use index+4 on companion cartridges; the save driver now walks to the tilemap-located SAVE row. |
| Resume round-trip attempt 3 | Battle passed (BI-2 hardening held); START menu opened on both cartridges but reported `wMaxMenuItem 7` where the driver expected 6 (no Pokédex yet per `draw_start_menu.asm:30-38`) → idle. RS-3: navigate to the SAVE row found by the tile scan, accept 6/7, publish `got_pokedex`. Not a product defect. Summary `99c8e01d…`. |
| Resume round-trip attempt 2 | HOLD before the save: A's starter-rival driver (8 prior passes) hit `unknown battle menu; refuse blind A` on an RNG-dependent retained-geometry state the assert did not record. BI-2: refusals name the point, bounded idle before refusing, candidate states from source. Not a product defect. Summary `e7cf6a05…646d`. |
| P2A-9 integrated | `starting_token`/`starting_at` reservation (120 s ceiling, `# ponytail:`) survives `_reconcile`/reads; stop/archive/delete refuse a live reservation; the final start commit requires the caller's own token and no `resumed_by`, otherwise kills what it spawned and returns 409. 232 manager/resume tests. Pin `94bfa26`. |
| Resume round-trip attempt 1 | HOLD before any save: the `rb-save` driver treated `wSaveFileStatus` as a fresh-cartridge/save oracle, but the byte is battle-animation scratch (`ram/wram.asm:1371-1385`) and read 2 during the rival battle. Driver terminal changes to confirmed-YES + menus closed (RS-2); the acked `gen1-save-witness` remains the proof. No product code implicated; resume phase not reached. Summary `aed95181…`. |
| P2A review round 4 | Codex `cx-69ce8923`: B/C/D resolved; **A not resolved (MAJOR, MODEL only):** `_reconcile` erases an active `starting` reservation on any read (`manager.py:486-488,523-527`), stop/archive overwrite it, and the final start commit is unconditional (`:893-903`), so a start paused at spawn can still overlap a resume. Not on the live path (harness posts `start=False`, `gen1_selected_scenario.py:191-194`): **LIVE go**. P2A-9 dispatched; live `rb_resume_roundtrip` running. |
| P2A-8 integrated | `handle_start` reserves `status="starting"` under the lock (409 if `resumed_by` set or already starting), spawns outside, commits `running`/reverts on failure; resume refuses `starting`/`running`; `_reconcile` normalises a stale `starting`; `shutil.rmtree(onerror=)` (3.11); `_pure_heartbeat` requires explicit `battle==0` and `trainer` null keys (native checkpoint may be absent); `_get`/`_active_stream_run` under the lock. 8032/0. |
| P2A review round 3 | Codex `cx-03a237b0`: (3) heartbeat rule works; minor — absent `trainer` treated as pure; (5) all handlers commit on fresh loads; minor — `_get()` saves unlocked; (7) resolved. **New majors:** `handle_start` reserves no state before spawning and ignores `resumed_by`, so a start paused at spawn can overlap a resume of the same predecessor (`manager.py:681-698`); `shutil.rmtree(onexc=)` is Python 3.12-only while the repo supports 3.11 (`manager.py:740,887`). Inventory-observation concern withdrawn (idle publications suppressed, `gen1_observation_loop.lua:89-104`). REJECT (MODEL), LIVE hold. P2A-8 dispatched. |
| P2A-7 integrated | Post-witness rule inverted: every committed event holds except a pure heartbeat (`observation` with no signals/inventory/acquisitions, battle 0, no trainer, no native checkpoint; absent optional fields count as not pure). Registry mutations serialised under `RunManager._registry_lock` via `_update_run` (spawn/slow work outside the lock, fresh reload before every save; the paused-spawn race is pinned by a test); refusal bodies carry fixed `reasons` + `details`; rmtree failures logged. 8029/0. |
| P2A review round 2 | Codex headless REVIEW `cx-f0798287` of `6075af1..aa40b43`: findings 1, 2, 4, 6 resolved; **3 partially (MAJOR)** — trainer-only / nonzero-battle observations and completed trades still pass `_gameplay_bearing` (`gen1_run_resume.py:88-94`; `lua/gen1_observation_loop.lua:103-123`; `trade_coordinator.py:490-498`); **5 partially (MAJOR)** — `handle_start` saves a stale registry after its await and can erase a concurrent resume's successor + `resumed_by` (`manager.py:660-675`); 7 minor (interpolated reasons). Safety axis re-confirmed intact; digest convention consistent across all five sites. REJECT (MODEL), LIVE hold. P2A-7 dispatched. |
| P2A-6/6C integrated | All seven round-1 findings addressed at `2064c60` (pin `aa40b43`): provenance-based inherited-identity verification (origin key/player from member history; evolution test), gameplay-bearing = non-empty signals/inventory/acquisitions, bounded event window refused on overflow, `resumed_by` written on the predecessor + status re-checked before registry save (single-use, race-checked), `_RUN_ID` validation + `MANAGER_DIR` containment + fixed-string 409 reasons (exception text to logging), continue observer retired after the acked initial observation (pre-ack hits still fail closed), flush outcome in `SLINK_RUNTIME_STATUS().engine_signals.last_flush` + console log (wire unchanged). 8021/0. |
| P2A review round 1 | Codex headless REVIEW `cx-9559ab65` of `6075af1..a99d8b4`: **REJECT (MODEL), LIVE hold**. Majors, all coordinator-accepted: continue observer stays armed after the receipt and rejects every later `SpecialEnterMap` hit — ordinary warps/Fly/blackout would kill the resumed client (`gen1_continue_observer.lua:49`, `gen1_client_entry.lua:503`, `home/overworld.asm:770,799`); inherited-identity verification compares the live key forever, breaking evolution (`gen1_run_resume.py:242-245` vs `gen1_evolution_runtime.py:199`); predecessors resumable repeatedly and status unchecked across the audit's await (`manager.py:786-824`); empty heartbeats (`acquisitions: []`) counted as gameplay → clean checkpoints refused (`gen1_run_resume.py:87`); audit silently ignores events past 4097 rows (`:149-152`). Minors: silent flush failure; `resume_from` containment/sanitised 409. TOCTOU concern withdrawn (`bizhawk_launch.py:124-136`). Fixes: P2A-6 (server) + P2A-6C (client). |
| P2A-5 integrated | `handle_launcher` passes the run's `resume` into `render_launcher`/`bundle`; `_service_release_ready` accepts, per player, either the new-game bootstrap + initial-save pair or `gen1-resume.enrolled[player]`; the client calls `client.saveram()` once after a `save_witness` (pcall-guarded, no-op in models). 8010/0. Live-harness `source_cut` re-pinned to `c8f5465` (`a99d8b4`). |
| RS-1 integrated (live resume harness) | `rb-save` chained driver from the lab overworld (START menu at Y2/X11, `wMaxMenuItem` 6 without Pokédex, SAVE = cursor index 3 per `home/start_menu.asm:60-74`; YES at the `$14` two-option box Y8/X1 index 0; terminal when `wSaveFileStatus==2` and `wFontLoaded` bit 0 clear), generic chain terminals in the bootstrap, `SelectedRun(resume_from=, resume_save=)` posting through the predecessor's Manager registry (registry id, `manager.py:786-788`), CONTINUE-safe boot inputs (asserts `wMaxMenuItem==2 && wSaveFileStatus==2 && index 0`, never Down), `rb_resume_roundtrip` live callable (status `rb-resume-checkpoint-observed`: both `gen1-resume.enrolled`, `oaks_lab` link ALIVE with the same species, `pokeballs_obtained` preserved, no death commands). Harness flushes SaveRAM via `client.saveram()` at the save terminal because EmuHawk is terminated, not closed. `source_cut` re-pinned `15727ec → b9658d7` (P2A-2 changed pinned product files). **Product gaps found (P2A-5):** (1) `manager.py:742-748 handle_launcher` never passes `resume` to `render_launcher`/`bundle`; (2) `gen1_runtime.py:235-247 _service_release_ready` requires `gen1-new-game-bootstrap` + `gen1-initial-save` that a resumed run never produces, so free service never releases; (3) nothing persists the witnessed save to `.SaveRAM` before an abrupt close. |
| P2A-3/4 integrated (identity import + refusals) | Audit exports `identities = {a:{known_keys}, b:{known_keys}}` only (no contexts/events/member ids); inside the resume enrollment transition, living keys (ALIVE link halves, pending captures, pending memorials) are reconciled against the presented party/box (refusals: inherited living member absent; presented key the predecessor never knew) and minted as fresh members under the NEW context via the registry's ordinary `acquire`; identity links recreated once both are enrolled. Red: an inherited-pair faint that previously refused (`faint rule pair differs from logical identity linkage`) now settles and queues the partner's `force_faint`. 7983/0 full suite. P2A-4 closes the residuals by refusal: no resume with pending captures/memorials; faint before partner enrollment guarded. |
| **P2A-2 integrated (resume at the run boundary)** | Server: `server/gen1_run_resume.py` audits a closed predecessor read-only (`read_journal`; refusals: missing witness, projection mismatch, pending commands, active trade, newer gameplay after the witness = HOLD, predecessor running, cartridge/contract mismatch, run over) and exports the typed rules via `StagedGen1State.restore(...).document()`; Manager `POST /api/runs/gen1` accepts `resume_from` (404 unknown / 409 with reasons), seeds the new runtime with the imported rules + `components["gen1-resume"]`, records `resume` in the registry, new `GET /api/runs/{id}`; `gen1_initial_observation.record()` requires, under a pending contract, the presented `cart_hex` projection digest (sha256 of the UPPERCASE HEX text of `[0x0498:0x8000]`, identical to the client formula) and a structurally valid `continue_witness`, lifts the established-history guard only for that player, journals the enrollment; inherited ball activation is a typed lineage fact effective from the player's initial observation frame (no forged signal). Client/launcher: `runtime_launcher.player_resume` → `launch.json.resume {from_run, required_digest, projection}`; `bizhawk_launch.prepare(resume_save=)` verifies the projection digest BEFORE copying the player's `.SaveRAM` into the new run's private directory with the ownership manifest (`tools/launch_bizhawk.py --resume-save`); the client builds the CONTINUE observer instead of the New Game bootstrap in resume mode, verifies the loaded save's digest at the `loaded` witness, and publishes `payload.continue_witness`. 50 new tests; full unit suite 7979/0. **Known gap (P2A-3):** the identity registry is not imported, so a linked death on an *inherited* pair would refuse settlement (`faint rule pair differs from logical identity linkage`); wild encounters, dead zones, clauses and the ball gate work from the imported rules. Dashboard affordance deferred. MODEL ONLY until the live resume check. |
| P2A-2 seams (resume at the run boundary) | Gen1-CodexPeer record. **Why it is the top feature:** today a run can only be played in one sitting — every relaunch is refused, so a full playthrough is impossible without it. Seams: Manager `resume_from` joins the strict key check before staging (`manager.py:763-776`); predecessor inspected read-only via `journal_reader.read_journal` (`:26-62`, never `open_runtime`); rules import via typed `SoulLinkState.from_document` / staged restore (`state.py:783-847`, `staged_state.py:74-145`), carrying links/area states/pending captures/mon stats/`pokeballs_obtained`/player identity/memorial (`rules.memorial.retired_pairs`) and NOT admissions, bindings, engine counters, cursors, commands, trades, observations, leases. **Blockers to design around:** `initial_observation.record` refuses any established history (`:155-161`) → needs a resume-specific transition; the earliest byte-level gate is right after `validate()` at `:163` (`sha256(bytes.fromhex(cart_hex)[0x498:0x8000])` vs the required witness digest); a matched digest must be paired with a witnessed **CONTINUE** (compose `gen1_continue_observer.lua`; the client currently builds the New Game bootstrap observer, `gen1_client_entry.lua:118`); inherited ball activation must be a typed lineage fact consumed by `gen1_wild_encounter_runtime.py:100-117` / `gen1_faint_runtime.py:132-155` (never a forged signal or frame 0); SaveRAM lives under `root/<journal-run-id>/<player>/SaveRAM` with an ownership manifest (`bizhawk_launch.py:73-104`) → an ownership chain or a verified copy; witness/rules alignment: refuse when a player's last committed observation revision exceeds its witness revision (owner policy: saved-but-unwitnessed → HOLD); "unchanged bundle" = reviewed source/dependency + cartridge identity, not ZIP equality. Proposed files: new `server/gen1_run_resume.py`, `manager.py`, `gen1_run_config.py`, `gen1_initial_observation.py`, `gen1_runtime_state.py`, `gen1_runtime.py`, `gen1_faint_runtime.py`, `gen1_wild_encounter_runtime.py`, `bizhawk_launch.py`, `tools/launch_bizhawk.py`, `lua/gen1_client_entry.lua`, new resume observer; unit/integration/live tests; dashboard affordance deferred (API + CLI first). Falsifiers: `resume_from` rejected today; imported core rejected by initial enrollment; prepare refuses a nonempty unowned SaveRAM. |
| **Parcel attempt 6 — D2 PASS (CONTROLLED-SCRIPTED)** | `rb-parcel-checkpoint-observed` at `c701e15`: one chained process per player from New Game to the first bought POKé BALL with the server's ball-gate activation recorded for BOTH players (committed engine records), starter link alive, no deaths, clean cleanup. Receipts summary `3bd2aff9…dd55`, console `a4164c08…cbcf`; full record in the [D1 physical report](reviews/D1-RB-physical-successor.md). Closes D2 for the `false` text axis; catches (D3), the tweaked text axis (FT-2) and later rows remain open. |
| Parcel attempt 5 | Oak's cutscene completed and the second trip to the Viridian Mart PROVED; BUY → POKé BALL accepted → quantity prompt reached, then `mart-unknown-wait` because `wTextBoxID` read 1 (not 0x0D) — the list/quantity routines never rewrite it. Item/quantity/confirm signatures now ignore `text_box` (geometry + oob + exit method); red test from the live point. Receipts summary `11e4371c…8afe`, console `ddf4892d…3ec8`. Attempt 6 is the changed run. |
| F0 result (speed gate, r1) | **PASS (PHYSICAL, controlled-scripted, bedroom workload only).** Pin `6931fdf`, `test_manager_selected_native_pair_free_runs_fresh_bedroom[variants1]` (R/B), 1 passed in 47.49 s, `performance_failures=[]`. Per player (phase average / windows): a 1x-active 59.96, 3x-active 176.88 [176.8, 176.8, 177.0], 1x-quiet 59.72, 3x-quiet 178.97; b 1x-active 59.96, 3x-active 176.96 [177.1, 176.7, 177.1], 1x-quiet 59.70, 3x-quiet 179.43. Floors: 59.130 / 173.0 / 177.391; min active-3x window 176.7 (+3.7 over the floor vs the +0.2-0.9 margin at `90853f5`); post-WB-1/P2A hook registration cost is not measurable at this resolution. Receipts `.cache/native-selected-fresh-q55jdxn0/` (summary `ebc35bf7...c113`), console `.cache/f0-rb-6931fdf-r1-console.txt` (`18dbaa14...7047`). Not timed: save/resume/trade paths. |
| D4 claim (linked death, first slice) | Gen1-CodexPeer record (cx-03b34366, SOURCE, read-only). Rows: `gameplay.{red,blue}.faint-whiteout-rebuild/.memorial-overflow/.explode` (each with both text variants); one A->B propagated faint closes none of them fully. Corrections: Gen 1 grave is physical BOX12 (index 11), not "Box 13"; `battle_faint` site `RemoveFaintedPlayerMon` bank 0F `$4741`; faint settlement ignores rows while `pokeballs_obtained` is false (`gen1_faint_runtime.py:152-155`), which is why R7 propagated nothing; "same round-trip" = atomic rule decision + command publication, physical HP0 needs admission+hold+permit (`:59-85,215-229`); partner safe() needs `isPartyWriteSafe` AND `physical_stop_verified` (`lua/gen1_held_faint.lua:33-51`) so B must be parked idle indoors; `memorial.expected` refuses `party_count<=1` (`gen1_memorial.py:35-58`). **Coordinator decision: D4a** - terminal propagation-only lane on the one-starter pair after a both-activated paired save + clean resume: A walks to Route 1 grass and loses naturally (Growl-only, bounded turns/PP, refuse on wrong move/escape/capture), B idle; PASS = pair DEAD, exactly one B `force_faint` with receipt-verified HP0, `run_over`/whiteout as source-derived, memorial recorded as expected HOLD (last-member refusal). D4b (complete memorial) needs a second usable party member per side (D3). Files: new `lua/tests/gen1_rb_linked_death_inputs.lua`, unit + live tests, host/scenario/bootstrap + route/chain tests, `reviews/D4-RB-linked-death-claim.md`; no production edits. Receipts `.cache/d4-rb-resume-faint-r1*` (+ role-swapped run). READY WAIT(N1-1 releases host/scenario/bootstrap; predecessor save pair with both activations). |
| TK-5 (lint drift) | OMP fact (cx-259ea75b): at `6931fdf` `ruff check .` reports **1744 findings, 129 auto-fixable** (tail of `--statistics`: E401x3, SIM102x3, C408x2, C420x2, F841x2, B017, C417, F811, SIM117, UP041). The `c5d70da` clean sweep was on master; `gen1/rc` has never been swept. Release-freeze item (F-wave), not RC gameplay; do not fix piecemeal inside feature cards. |
| Parcel attempt 4 | Parcel **delivered** to Oak on both cartridges (script 15); driver idled on a `wJoyIgnore == $FC` gate while the cutscene text runs with mask 0/$F0. Fix: tap A whenever unmasked and no scripted NPC walk; red model test. Receipts summary `de3e46fc…ae04`, console `b2411c4e…147f`. Attempt 5 is the changed run. |
| Parcel attempt 3 | **HOLD at Oak's handoff, but the WB-1 fix is PROVED live**: both cartridges crossed Route 1 grass with wild encounters (RUN sub-path) and no observer crash, received the parcel, returned to Oak, then idled — the driver waited for lab script 0 while the post-rival state is `SCRIPT_OAKSLAB_NOOP` (18); one-line fix, red model test. Receipts summary `7e401a9a…ed11`, console `3f4ef3cf…8659`. Attempt 4 is the changed run. |
| P2A-1 integrated (A+B) | `save_witness` engine signal at `SaveMenu.save` + 3 (anchor `0x772D`, `CD487821A5C4`, capture_offset 3; regenerated by `tools/gen_gen1_engine_signals.py` with source-text and ROM-byte asserts; Yellow site came for free from the same symbol, no branch) carrying `digest = sha256(hex(CartRAM[0x0498:0x8000]))`, `projection cartram-0498-8000-v1`, `save_file_status`. Server validates (`gen1_engine_signals.py` SAVE_PROJECTION; refuses bad digest/status/projection/extra keys) and records `components["gen1-save-witness"][player]` (latest wins) in `gen1_engine_signal_runtime.py`, audited by `verify_state`. 98 model tests. **Finding that re-scopes C:** `save_identity` at HELLO is only `{ot_id, trainer_name}`; the comparable presented bytes are `initial_observation.source.cart_hex` (server-side same projection). Admitting a relaunched emulator into the SAME runtime would require re-anchoring ~110 frame/identity comparisons across 33 modules (`emu.framecount()` restarts) plus the client's replaced-context refusal (`gen1_initial_observation.lua:70-75`) — 250–400 lines, ≥12 files. **Coordinator decision (vetoable):** implement resume at the RUN boundary instead (P2A-2): Manager `resume_from` creates a NEW run that imports the previous run's rules state and requires each player's presented `cart_hex` projection to equal that run's last acked `save_witness` digest; refuses otherwise. This honours the owner's P2a policy (both saved, files match acked checkpoints, no pending/trade, unchanged source) with a fresh frame line and no re-anchoring; it is the user-visible flow after a crash anyway. |
| WB-1 fixed | **Root cause (SOURCE + live receipts):** inside a bus-exec hook `emu.framecount()` returns the frame the step was armed at (= `state.frame`), one below the assembling tick's count (pinned in [BATTLE_FORCE_FAINT_WINDOW.md](BATTLE_FORCE_FAINT_WINDOW.md) §10; `instruction_executor.lua:38`; every live engine signal sits one frame below its observation — 8 samples over R7 and parcel r2; WB-1-FC confirmed from BizHawk 2.11.1 source: `Gambatte.cs:486-495` increments `Frame` after `gambatte_runfor`, `EventsLuaLibrary.cs:131-166` fires `on_bus_exec` before the instruction). `gen1_acquisition_observers.lua:132/:167` demanded `witness.frame > state.frame`, which excluded **every** hook-stamped witness that could exist; latent because no acquisition witness had ever reached the non-fast path live (all prior `acquisitions` were `[]`; the starter is an engine signal, not a grant receipt). The first capture would have crashed identically. Fix: strict `witness.frame == state.frame` (`in_step`), no other assert touched; test models that stamped fake witnesses with the tick's count were corrected. Red replay `tests/unit/test_gen1_wild_assembly.py`; 165 passed across the loop/acquisition/native/inventory sets. MODEL ONLY until the next parcel run. |
| Parcel route attempt 2 | **HOLD at `975ab9c` on a PRODUCTION defect** (`.cache/d1-rb-parcel-r2`, summary `6e47c087…774d`, console `4a659dfe…dcb2`): chain handoff again fine; player B crashed at its **first genuine wild encounter** (Route 1 southern grass) — `lua/gen1_acquisition_observers.lua:167: wild_begin completion lies outside returned physical step` via `gen1_client_entry.lua:631`. Never reachable before: R7 stayed in the lab and the starter is a gift (grant observer). A real player hits this on their first Route 1 encounter. WB-1 (isolated Claude worker): fast red replay in the loop model, then a root-cause lifecycle fix in the shared observer/loop modules; the step-window check is not to be loosened. |
| P2a claim (clean resume) | Sonnet record: rows `gameplay.{red,blue}.reconnect` ("durable reconnect replay, admission epochs, bounded queues"), `trade.{red,blue}.recovery`; no save-witness or re-enrollment mechanism exists (`gen1_continue_observer.lua` witnesses CONTINUE/load only; engine-signal sites `bag_received, battle_faint, poison_faint, starter_begin, starter_end`; unknown kinds refused `gen1_engine_signals.py:29`). Exact relaunch refusal: `gen1_service_continuity.py:87-89` (`service continuity admission differs from the initial physical identity`) plus three more gates (D0b correction "What stands"). HYPOTHESIS: (a) `save_witness` engine signal at `SavePartyAndDexData`'s trailing `ret` (RB `1c:780f` entry; exact `ret` offset underived — the Yellow analogue is proved in the D0b save-witness doc; must pair with `SaveGameData` entry or read `wSaveFileStatus` to exclude the cable-club partial save) carrying frame + SaveRAM hash; (b) server records/ACKs a per-player checkpoint; (c) re-enrollment admits a new `physical_instance` only when both players' last-acked hashes match the presented files, no pending ids, unchanged contract digest. Shared lifecycle files: `gen1_service_continuity.py`, `gen1_runtime.py`, `gen1_runtime_admission.py`, `protocol.py`, `gen1_engine_signals.py` + `data/games/gen1_rby/engine_signals.json`; adapter: the RB save site data. Falsifiers: unit refusal today; after: admit only on the policy, refuse one-unsaved / hash mismatch / pending / changed digest. Live check: kill one EmuHawk after both saved, relaunch the Manager bundle, observe admission. (9) **READY — coordinator decision 2026-09-14**; P2A-SITE (Gen1-CodexPeer) derived the narrow START-menu completion site `SaveMenu.save+3` = `1c:7730` (`21A5C4` after `CD4878` = `call SaveGameData`, `save.asm:165-170`), excluding Cable Club/Hall of Fame/ChangeBox saves that share `SavePartyAndDexData`'s RET (`1c:7847`); digest projection `CartRAM[0x0498:0x8000]` (sprite buffers excluded, `ram/sram.asm:1-49`). P2A-1 ACTIVE on an isolated Claude worker. |
| Parcel route | **Attempt 1 HOLD at `4bf3224`** (`.cache/d1-rb-parcel-r1`, summary `8712372c…953d`, console `425228a4…fb59`): **chain handoff PROVED live** on both cartridges (`lab-loss-complete` → parcel driver, frames 16305/16977, `chain_handoffs` recorded), then the parcel driver stalled at Pallet (9,2) pressing Up into a blocked tile — waypoint `{9,1}` in `pallet_north` is off the road column (`gen1_rb_parcel_inputs.lua:17`; the reviewed return path uses `(10,2)`); no stall detection. The Python poller also crashed on `PermissionError` mid-replace of `rb_route_progress.json` (latent in `rb_starter_rival` too) — fixed to tolerate `PermissionError`/`JSONDecodeError`. PT-1 decode (Gen1-CodexPeer): `(9,1)` is a tree (`PalletTown.blk[4]=$4F` → `overworld.bst[1278]=$3A`), columns 10–11 exit north, and the engine changes map only past the edge (`home/overworld.asm:622-635`) — so all four edge-terminated tables (`pallet_north`, `route_north`, `viridian_south`, `route_south`) now end one cell past the edge; model test `test_map_edges_keep_driving_until_the_engine_changes_map` is red on the old tables. Attempt 2 is the changed run. Clean cleanup. |
| Battle path | **R7 PASS (CONTROLLED-SCRIPTED)** at `57eabf7`: both cartridges reached `lab-loss-complete` (lab script 18, `battle_result 1`, healed HP 20/19, rival event set, Growl PP 15/24); ALIVE `oaks_lab` link, no death command queued, clean cleanup. Receipts `.cache/d1-rb-starter-rival-r7-summary.json` `12bd67af…f408`, console `a0a1016e…754d`; full record in [D1 physical report](reviews/D1-RB-physical-successor.md). Closes the D1 first checkpoint only; parcel/first ball/catches/fastest-text remain open; no manifest row closed. Lane released. Round-1 shape: Driver diff is four lines at `gen1_rb_ball_gate_inputs.lua:110-116`: while pending and the point is still the move menu with the cursor on Growl, re-pulse `A` on the 16-frame cadence; otherwise bounded idle as before. Coordinator re-ran 30 passed / 0 failed / 0 skipped, ruff clean, lupa ok; SHA256 Lua `b98f0dbed09f85ee713c53d7ec075e4d6900678f84b3c3465a37062b4695f52f`, test `13a76486d8526feb900bc7e23f7fc06f3e18fb0df2eac372bd1d2577e45e8b92`; receipt `.cache/bi1-model.xml`. Known ceiling (worker-noted): a button-gated prompt before the player's PP drop on an enemy-first turn would still hit the 600-frame bound; only R7 can show it. **R7 launch note (R7-PREP):** `asyncio.run(rb_starter_rival(r".cache\d1-rb-starter-rival-r7", emulator=r"E:\Howard\Bizhawk\EmuHawk.exe", base_config=r"E:\Howard\Bizhawk\config.ini", limit=180))` from the checkout with `PYTHONDONTWRITEBYTECODE=1`; 300% is the `SelectedRun` default (`gen1_selected_scenario.py:286`); the summary is self-written to `<owned>-summary.json` (`:606-607`), console must be tee'd to `.cache/d1-rb-starter-rival-r7-console.txt`; preflight (`:340-363`) refuses a pre-existing owned root and self-checks emulator/config/source hashes; PASS = final status `rb-starter-rival-checkpoint-observed` after clean cleanup (`:595-604`). Historical: RED established 2026-09-14 00:2x UTC: `test_r6_dropped_growl_pulse_is_repeated_until_observed_acceptance` fails at `tests/unit/test_gen1_selected_rb_ball_gate.py:141` (`assert buttons["A"]`) on the unchanged driver, 1 failed / 29 passed — the dropped-pulse mechanism is confirmed on the driver side. Green step: then re-pulse `A` on the 16-frame cadence while the cursor still sits on Growl with unchanged PP; index 2→1 with unchanged PP = accepted-not-executed (idle, no Down); PP drop → existing `awaiting_main_menu`; 600-frame bound from first emit. Independent review of the frozen diff precedes R7. |
| BI-1 integrated | Round 2 (isolated Claude worker): pending + not(Growl cursor) → `press("B")` on the cadence; `test_enemy_first_prompt_before_pp_drop_is_advanced_with_b` red on round 1, green now; 31 passed / 0 / 0, ruff, lupa; SHA256 Lua `7c000361e32a8de41f7fdd2f5a6ba907d5cc2ace3c1d4d5012fcad9930637e41`, test `ab5f163ba04992644552bc69da01ad028110cad32ba499b7be7b6cbd77e29966`. Codex re-review `cx-f22e3dde`: **ACCEPT-WITH-NOTES** — `ManualTextScroll` accepts A|B (`home/text.asm:209-217`, `home/joypad2.asm:55-92`); battle menu ignores B (`core.asm:2091,2124-2125`); no reachable harmful-B state at level 5; faint sets `wBattleResult=1` and cleanup clears `wIsInBattle` (`core.asm:1030-1044`, `end_of_battle.asm:27-50`); healing + rival event happen in lab script **12** (`scripts/OaksLab.asm:418-436`), 13/14 → 18 is exit dialogue. Open: the 600-frame total through the final KO dialogue is only establishable by R7. MODEL ONLY. |
| D2 claim (parcel route) | (1) `gameplay.red.ball-gate` / `gameplay.blue.ball-gate` (manifest `:2905`, `:3165`, `proofs=[]`, axes title + fastest_text). (2) Route mode pinned in three places: `gen1_scripted_new_game.lua:86,94,108`, `gen1_scripted_host.py:18,47-49,115`, `gen1_selected_scenario.py:304-306`. (3) Missing: no mode launches the parcel module; its terminal `first-ball-readback` (`gen1_rb_parcel_inputs.lua:99`) is unknown to the host; it expects to resume in the same process at map 0x28 with the parcel undelivered (`:125-128`) — exactly the starter-rival exit state. (4) HYPOTHESIS: chained `rb-parcel` mode (starter-rival driver → `lab-loss-complete` → parcel driver → `first-ball-readback`), no new fixture or launch. (5) Falsifier: unit model shows the host refuses `rb-parcel` today; lupa test that the wrapper hands over at `lab-loss-complete`. (6) Files: D2-HOST (Python: host, scenario, live callable, new unit test) now; D2-LUA (`gen1_scripted_new_game.lua` chaining + lupa test) after P-2a releases the file; depends on P-2a fields and P-2b `menu_kind` derivation. (7) Positive: `oak_got_parcel` true, `parcel_count` 0, `ball_count>0` with money debit, server `pokeballs_obtained[p]` true only for the buyer (`server/state.py:388-389`), link alive, no death commands; refusal: cancel leaves bag/money unchanged, no activation before the first ball readback, partner independent. Receipts `.cache/d1-rb-parcel-r1*`. (8) If the module cannot resume from the exit state: standalone mode with its own entry fixture (larger; not authorized yet). (9) **READY — coordinator decision 2026-09-14**, D2-HOST ACTIVE; D2-LUA WAIT(P-2a). |
| P-2b | `menu_kind` audit (Gen1-CodexPeer, pokered 405b624), SOURCE FACT: with M=(map 0x2A && `wViridianMartCurScript`==2) — **mart-choice** `wListMenuID`==2 && `wTextBoxID`==0x0E && Y1/X1/max2 (`home/text_script.asm:148-150`, `engine/menus/text_box.asm:151-175`; index 0=BUY,1=SELL,2=QUIT); **mart-item** L==2 && T==0x0D && Y4/X5/max2 (`engine/events/pokemart.asm:134-150`, `home/list_menu.asm:29-56`); **mart-quantity** same geometry, 1≤`wItemQuantity`≤99, `wMenuWatchMovingOutOfBounds`==0 vs 1 while listing (`list_menu.asm:41-48,98-99,197-245`); **mart-confirm** T==0x14 && Y8/X15/max1, `confirm_index` = live `wCurrentMenuItem` (0=YES) with `wMenuExitMethod`==0 excluding a completed answer (`text_box.asm:213-235,307-335`); **none** has no exact WRAM predicate — the complement is not proof of free movement. **Critical, coordinator-verified:** `wCurItem` is overwritten for every printed price (`home/list_menu.asm:417`, ends at BURN_HEAL for the Viridian list), so the frozen module's `item_id==4` check needs `item_id` derived from the Viridian inventory `POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL` (`data/items/marts.asm:4-5`) at `menu_index + wListScrollOffset` (`cc36`); expose `wMenuWatchMovingOutOfBounds` (`cc37`). Retention: T/L/Y/X/N/I persist after menus close; `wMenuExitMethod`/`wChosenMenuItem` are retained outcomes; `mart_script`==2 persists before and after delivery. Parcel delivery/Oak handoff use plain dialogue, no yes/no. |
| FT-2 claim (fastest-text axis) | Gen1-CodexPeer record. (2) Manager run creation accepts only `name,rom_a,rom_b,rules,start,native`, calls `clean_contract` unconditionally and stages the canonical pair (`server/manager.py:755-791`); there is **no HTTP seam for prepared UPR artifacts**; the lower `create_runtime(prepared_cartridges=…)` path exists (`gen1_run_config.py:64-111`) and `PreparedCartridges` replays seeds/settings/JAR and revalidates in place (`gen1_prepared_cartridges.py:111-177`, relocation-sensitive). `selected_manager` requires provenance `canonical_companion` (`test_gen1_native_selected_fresh.py:82-110`); the scripted host requires filenames `slink_(red|blue).gb` (`gen1_scripted_host.py:30-41`). (4) HYPOTHESIS: a bounded optional **UPR generation recipe on Manager run creation** (run-local `prepare_pair` → `PreparedCartridges` → existing `create_runtime`), SelectedRun accepting that recipe and publishing settings/provenance/final hashes plus the `$38D3` byte from the exact staged file; a byte-identical run-owned launch copy named `slink_<variant>.gb` avoids editing the host/drivers. **Coordinator decision 2026-09-14 (vetoable):** proceeds under the owner's existing C–E plan (E1 UPR producers) because the manifest already demands both `fastest_text` variants; bounded to an *optional* request key with the default clean/native path unchanged. (6) Proposed files: `server/manager.py`, `tests/live/test_gen1_native_selected_fresh.py`, `tests/live/gen1_selected_scenario.py` (after D2 releases it), new unit/integration/live tests, `reviews/FT2-UPR-SELECTED-claim.md`; pins JAR `380dc1e6…`, seeds a=123456789/b=987654321 fixed across FT0/FT8. Randomization rule: **all** `build_categories` categories disabled, only `currentMiscTweaks` 0/8 differs (`upr_settings.py:259-280`, `gen1_upr_policy.py:43-71`) — starters/trainers/wild randomization would break the drivers' species 1/4, trainer 225, Growl and Mart-order facts. (9) READY after D2-LUA releases `gen1_selected_scenario.py` and D3 is claimed; no owner input required. |
| FT-1 | `fastest_text` on the ball-gate rows is **declarative axis metadata** (no evaluator handling, `verify_gen1_release.py:259-294`) that the existing R/B claim ties to the **UPR Fastest Text tweak** — `build_categories(..., fastest_text=)` → `currentMiscTweaks` 0/8 (`server/upr_settings.py:269-280`, `gen1_upr_policy.py:53-54`), a `RET` at `PrintLetterDelay` $38D3 verified by the scanner (`gen1_upr_scan.py:307-313,353-355`; `upr_layout.json:501`). It is NOT the in-game FAST option (`wOptions` $D355, low bits FAST=1/MEDIUM=3/SLOW=5, default $03, `main_menu.asm:127-132,623-645`). R7 covers only `false`; no FAST/tweaked R/B gameplay receipt exists. Native FAST would be selectable by normal buttons (Down, A, Left, B from the fresh main menu, `main_menu.asm:44-90,468-505`) but closes a different claim. Letter pacing changes the elapsed frames inside the two 600-frame driver bounds and all wall-clock limits; `Delay3` and prompt gates are unaffected. Closer (FT-2, claim record in progress): feed reproduced `prepare_pair` artifacts (tweaks 0 and 8) through the selected scripted path with settings/final-hash/$38D3-byte receipts; do not edit the route drivers. |
| D3 claim (first catch + dead zone) | Gen1-CodexPeer record (SOURCE + read-only map decoding). (1) Rows: `gameplay.{red,blue}.ball-gate`, `.capture-ordering`, `.dead-zones` (all `proofs=[]`, both text axes); `.encounters` needs every area/rod, not closable by Route 1. (2) Capture truth is source-witnessed by the existing observers (`lua/gen1_capture_observer.lua:10-43`, `lua/gen1_wild_encounter_observer.lua:11-48`, composed in `gen1_acquisition_observers.lua:18-24`, drained by `gen1_observation_loop.lua:120-146`); the server settles via `gen1_acquisition_runtime.py:308-332` → `state.py:1568-1657` (ALIVE link, area LINKED; unpaired half may be quarantined so `party_count==2` is not mandatory); activation requires a validated `pokeballs_obtained` frame ≤ encounter frame (`gen1_wild_encounter_runtime.py:100-117`); `no_catch` resolves only after an ended, uncaught, eligible encounter (`:276-318`; guards `no_catch_rules.py:34-66`); legacy duo `H.throw`/`H.hunt` stage balls/HP (`lua/tests/duo/gen1_hunt.lua:104-120,253-319`) and are not selected-route evidence. (3) Missing: no chained module walks Route 1 grass, uses the real bag Ball (ITEM = left column row 1; identify the Ball entry, never slot 0 / raw `wCurItem`), and waits for witnessed acquisition; no refusal driver. (4) HYPOTHESIS: `rb-catch` = starter → parcel → new `lua/tests/gen1_rb_first_catch_inputs.lua` after `first-ball-readback`, gated on BOTH players' D2 activation receipts; Route 1 is map $0C, grass tile $52, first hunt cells (10,6)↔(11,6) (`Route1.blk` byte 35 = $0B; `overworld.bst` bytes 181/183 = $52); local terminal `first-catch-observed`, the live verifier selects the Route 1 ALIVE pair by area + member identities. Refusal = a SEPARATE fresh run: A catches and settles first, then B RUNs from its first eligible Route 1 battle → DEAD_ZONE + A's retirement obligation completed physically; swap roles for the other direction. (5) Falsifiers: host refuses `rb-catch`; lupa red cases (no action before paired grant, ITEM/Ball only, unknown context HOLD, broken-out ball not terminal, local success cannot assert a link); verifier red cases (wrong area/key, unACKed, pending peer, starter link mistaken for Route 1). (6) Files after D2 releases them: new catch module + unit + live test + report, host/scenario/bootstrap/route-modes test; raw symbols `wEnemyMonHP` $CFE6, `wBattleResult` $CF0B, `wCurEnemyLevel` $D127, `wPartyCount` $D163, `wIsInBattle` $D057, `wEnemyMonSpecies2` $CFD8, `wCapturedMonSpecies` $D11C (retained intermediate, not delivery proof), `wBoxCount` $DA80 (not `wNumInBox`). (7) Receipts `.cache/d1-rb-catch-r1*`, `-no-catch-b-r1*`, `-no-catch-a-r1*`. (8) Stop on insufficient balls/unexpected species/blocked approach/HOLD; no HP/ball/encounter writes, no savestate reuse of a resolved area. (9) READY WAIT(D2-LUA integrated, D2 live activation receipts). Open: collision-safe walk from the Mart exit (3,7) to (10,6) is unverified (D3-PATH). |
| D2-LUA-SPEC | Gen1-CodexPeer: chaining hunks for `wrapped_advance` (publish the handoff phase once, retain `chain_handoffs`, one `original_advance` per frame, unhook only at the last chain terminal), a diagnostic `mart_menu(raw)` signature function (choice/item/quantity/confirm from `text_box`/`list_menu_id`/geometry/`menu_watch_oob`/`list_scroll_offset`/`menu_exit_method`), two raw fields to add (`wListScrollOffset` $CC36, `wMenuWatchMovingOutOfBounds` $CC37), and a red-test list. **Finding:** the frozen parcel module treats `menu_kind=="none"` as *act* (`gen1_rb_parcel_inputs.lua:91-95,196-198`), so ambiguity must map to a distinct `"unknown"` kind that idles (bounded by the wrapper's 120000-frame and wall-clock limits), and `confirm_index`/`item_id` sentinels must not satisfy `==0`/`==4`. D2-LUA implements: chaining, `lua/tests/gen1_rb_mart_signature.lua` with `unknown`, `font_loaded` raw field, the parcel-module amendment, decoder hash in `source_files`. |
| P-1 | "Raw menu producer" = `route_point()` (`gen1_scripted_new_game.lua:51-65`) does not yet emit the parcel module's 14 extra fields (`wNumBagItems d31d`, `wBagItems d31e`, `wPlayerMoney d347`, two `wEventFlags d747` bits, `wViridianMartCurScript d60d`, `wSimulatedJoypadStatesIndex cd38`, menu cluster `wListMenuID cf94`/`wCurItem cf91`/`wItemQuantity cf96`/`wChosenMenuItem d12d`/`wMenuExitMethod d12e`), `menu_kind` has no raw-symbol derivation yet, and three literals pin the only route mode (`gen1_scripted_new_game.lua:86`, `tests/live/gen1_scripted_host.py:18,47-48`, `gen1_selected_scenario.py:304-306`). Shared: host loop/plan staging/enums; game-specific: `route_point()` fields and the parcel module. Not dispatched until the lab checkpoint passes. |
| BI-1 review round 1 | Codex headless REVIEW `cx-d02ec69d`: **REJECT** for R7. Source-derived and coordinator-verified: when the enemy outspeeds, `ExecuteEnemyMove` runs first and a KO is handled before the player's move (`engine/battle/core.asm:418-424`); enemy stat-fall `_FellText` (`data/text/text_3.asm:122-124`) and `_PlayerMonFaintedText` (`data/text/text_2.asm:882-885`) end in `prompt`, so an idle driver hits the 600-frame bound before any PP drop. Attempt 5 passed one Growl only because the enemy used a plain attack (`done`-terminated text). Minor: index decrement precedes validation (`:2620-2656`), so it is not an acceptance signal. Round 2 in progress: press B on the cadence while pending outside the Growl-cursor state. |
| TK-1 | OMP (deepseek-v4.1-flash): `.cache/current-cards-final.xml` tests=188 failures=0 errors=0 skipped=0; parcel Lua/unit hashes EQUAL to the report; R0 working copy `88aec118c2fd09c02012755ad06bc6b21fb15907a6bbe211c2878bfabf8f00cf` ≠ frozen supplied input `4dadeb79…` — expected, the dirty file is the correction candidate, not drift. |
| E-2 | Claim record for `browser.red.clean-ups` received (Gen1-CodexPeer). Source: `/patcher?game=rb-red` + `/companion/SLink-Red.ups` (`server/patcher.py:61-77,120-175`), in-browser UPS apply with base/final SHA checks (`server/static/patcher.js:275-325`), final SHA256 `26c1e987…94e7`. Case map: only `valid`/`wrong-rom` have real-browser assertions (`tests/browser/gen1_patcher.cjs:37-54`); five cases have component-only unit coverage; `header-protection`/`raw-download` have none in-browser. **Coordinator decision 2026-09-14 (vetoable):** `reapply-noop` is satisfied by the current behaviour — a *named* refusal that leaves the output byte-identical (the injector already names reapply a no-op, `tests/unit/test_gen1_injector.py:158-160`; the browser refuses at `cjs:46`/`patcher.js:286`). The E gate asserts unchanged bytes plus the named reason; no UX change. Hypothesis: bounded browser matrix + one new Red live boot gate feeding the exact downloaded file into `server/bizhawk_launch.py` prepare/launch (not `SelectedRun`, which hardcodes its prepared ROM path, `gen1_selected_scenario.py:404-444`); proposed exclusive files `tests/browser/gen1_patcher.cjs`, `tests/integration/test_gen1_browser_patcher.py`, new `tests/live/test_gen1_browser_red_boot.py`, `lua/tests/test_gen1_browser_red_boot.lua`, `tests/unit/test_gen1_browser_red_boot.py`, `reviews/E2-BROWSER-RED-successor.md`; coordinator-only: manifest proofs/live-gates argv, inventory. No Yellow edits; Blue needs its own cases/hash/boot. READY once the D2/D3 lane work is integrated; no owner input required. |
| E-1 | `browser.red.clean-ups` (stage patch-browser) has an empty `proofs` array → automatic evaluator failure (`tools/verify_gen1_release.py:264`); the stage is 40/42 missing (P0 report). The only registered browser proof (`patch.actual-browser-canonical-upr`, `tests/integration/test_gen1_browser_patcher.py:28,34`) is a Chrome download/hash/refusal matrix with no emulator boot; the R6 `downloads` block is evidence for the clean-bundle boot only. Gap: real EmuHawk boot of the browser-patched Red ROM; cheapest closer reuses `server/bizhawk_launch.py` prepare/launch or `SelectedRun`. Needs the emulator lane; independent of BI-1 and N2. Not dispatched until a nine-part claim exists. |
| Shared HUD | Integrated at c647f91; source/model passed. Physical pixel-expiry proof remains an open limit. |
| Checks | Independent full unit suite (OMP, TK-4) on HEAD `b87c349` + the P2A-11 edits (= `79f04a3`): **8056 passed, 0 failed** (782 s). Earlier: 188 current-card tests at the takeover. No fresh release-evaluator verdict. |
| Hooks | Installed and tested; Codex native `/hooks` trust and actual host firing remain human-only/unverified. BLOCKED, not worked. |
| Preserved dirty candidates | `R0-supplied-contract-successor.md` modified (+12/−9, unreconciled, no classifier grant); parcel Lua/unit/report untracked, 12/12 modeled, hashes match report, not integrated. No cleanup/reset. |
| Remaining RC | Source/model/physical/human levels stay separate. Full campaign/trade/artifact/performance/frozen evaluator and two-person attestation remain open. P2a approved, mechanisms absent; P2b unapproved. Gate scope alignment is a later bounded card, not a census. |
| Handoff | Previous TEMP handoff consumed at takeover; this guide remains sole authority. |

**Initial D1-RB implementation claim (historical scope; current checkpoint governs).** (1) gameplay.red.ball-gate and gameplay.blue.ball-gate: genuine starter/lab faint before activation, then parcel/cancel/first-ball player-local activation; actual catches and both fastest-text settings remain later full-row requirements. (2) Product15727ec, shared testa63d793; pinned pokered405b6246; accepted D1-RB source report d538b856abffe2fd37c97fc5d8d57ebe25aa53204fbe61f959d923138156b8ee; root verified both clean ROM hook bytes E1D1C1C178EA96CFC9 at52843, lab HealParty and inactive-faint guard. (3) Current script stops at first idle; no normal starter/rival/ball gameplay receipt. (4) Hypothesis: a scenario module supplies normal inputs on existing owned frames after coordinator audited paired enrollment, with context/hold refusal; no new production authority. (5) First falsifier is modeled refusal before handshake/while held/after changed context plus real route start; first live checkpoint both starter receipts and pre-ball lab loss with link ALIVE/no death or force_faint. (6) Sol alone: tests/live/test_gen1_selected_rb_ball_gate.py, lua/tests/gen1_rb_ball_gate_inputs.lua, tests/unit/test_gen1_selected_rb_ball_gate.py NEW; shared tests/live/gen1_scripted_host.py, lua/tests/gen1_scripted_new_game.lua, tests/live/gen1_selected_scenario.py, tests/live/test_gen1_selected_idle.py. Report reviews/D1-RB-implementation-successor.md and .cache/d1-rb-model.*. D0-RB PASS is prerequisite satisfied; no parallel writer on these files. (7) Positive and refusal modeled checks, focused Ruff; freeze first working starter/rival checkpoint promptly, then source review and separate sole live grant. Subsequent parcel readback/no activation, cancel unchanged bag/money, first ball retained exact ACK/source and partner independence are later same-admission checkpoints; do not call rows closed. (8) On source contradiction stop exact checkpoint, preserve evidence and request bounded coordinator correction; never stage game data or bypass holds. (9) READY and conditional ACTIVE now. No manifest/server/product changes. Default canonical R/B first; fastest-text artifact adapter and D2 catches are separate real gameplay follow-ups, not a demo detour.

R0 revision3 input is frozen at SHA256 `4dadeb79dd944abe23d069f0eb768a11f7a0c70316f08a441dbb03e40408477e`. Required corrections: equal-byte replacement must still match actual S/R to B; successful DONE must require result0 and permit S==B when B==A; supply a complete typed re-enrollment-witness representation or explicit unavailable refusal; scope image comparisons to actual protected regions, allowing only the precise bank0 sprite-workspace range already permitted by gen1_native_policy.py163–171 (not all bank0). Ordered native-save writes remain source-correct. Clarify F byte/hash/projection comparisons without claiming file presence from supplied hashes. P2b stays refused and no producer is implemented by this report. Root reviews the frozen correction before any pure-classifier grant.

### Accepted evidence and remaining limits

| Card | Result and source level |
| --- | --- |
| W0 / ARCH-1 / ARCH-2 | Mapping and architecture work complete; reuse [closeout](reviews/ARCHITECTURE_CLOSEOUT_2026-09-13.md). Architecture regression640 pass at19edbb2, MODEL only. Do not repeat the survey. |
| P0 / host | [Input preflight](reviews/P0-20260913-successor.md) passed with process-local configuration: seven hash pins plus Java presence; eight adjacent assemblies. Owner-authorized symlink fix yielded48/48 security-file tests, no skips. No global environment/pin changes. |
| MAT setup | Owner-approved CLAUDE.md / docs/agents configuration installed at6167e03/207b8da; this guide is sole tracker and labels do not grant work. |
| F1 | [Unit7815/7815](reviews/F1-unit-repaired.md) and [integration161/161](reviews/F1-integration-configured.md), zero errors/failures/skips, independently verified at source/testsa1714c5. Original failures and rejected fixture candidates remain retained. These predate D0 test additions and are not a current full release-evaluator verdict. |
| N0 actual CLI | Root discovery fix integrated15727ec,67 modeled cases and independent reviews. [Actual CLI startup/refusals](reviews/N0-CLI-physical-successor.md) and [fresh Y/Y R2 enrollment](reviews/N0-enrollment-r2-physical-successor.md) physically passed: owned hosts, initial saves/files, current service, empty queues and clean cleanup. No title/reset/cross-write/native-trade blanket claim. |
| D0-A / D0-S | Tracked SelectedRun + idle entry and scripted host/Lua driver integrated6283d58. Both review axes,19 complete modeled tests, Lua5.4 model and Ruff passed. [Scripted physical Y/Y idle](reviews/D0-S-physical-successor.md) exited0: both3500-frame button drivers stopped at frame3501, both32768-byte files matched their own prepared image, service current/queues empty, no cleanup errors. OMP receipt cross-check complete; source and physical evidence remain bounded to Y/Y. This is controlled-scripted selected-launcher evidence, distinct from product CLI. |
| Failed/interrupted diagnostics | [First N0 controller](reviews/N0-enrollment-physical-successor.md) remains HOLD for the invalid idle-observation oracle and resource-close error; [UI attempt](reviews/D0-A-autonomous-physical-successor.md) remains interrupted/HOLD. Neither is relabeled green. |
| R0 / recovery | [Pure-classifier readiness](reviews/R0-claim-check-successor.md) found no implementation; revision3 contract has the four blockers above. No actuator, persistence, rebind, new window or replay implementation is authorized. R0b evidence producers and R1/R2/R3/R4 remain separate. |
| D0b clean resume | P2a policy approved; [corrected research](reviews/D0b-correction-successor.md) and [save boundary](reviews/D0b-save-witness-boundary-successor.md) remain source evidence. Save-witness/file-permit/re-enrollment mechanisms are absent. `wSaveFileStatus==2` alone is not full-save provenance. |
| C1 | First model reproduced atomic collateral refusal; [source reachability](reviews/C1-reachability-successor.md) names preactivation Magikarp history. History-complete model execution was stopped by automatic safety review for possible cybersecurity risk; no workaround reassignment or implementation. |
| N1/N2, D/E/T, F/H | Same-admission receptionist/party and native trade, ordinary campaign axes, full title/artifact matrix, frozen evaluator and two-human session remain unproved. No release readiness. |

Preserved D0-S summary: `.cache/d0-s-scripted-summary.json`, SHA256 `ffa5cf5118affa9e598d726e26c42b042f4e80eae9c94ae63e08572ac22eaaab`; console `e0f2a9cd97c8b659143e6a78d8ad8f1041ec497f8f2fce53dd1fbb7cde6b2bf1`. Run `run_20260913_195515_9e4d11`, runtime `609393fa512a849ea3b5f2ae318baafb`. Both separate SaveRAM files hash `abdc79629f72608bc0936a334a9e4af0880dbedd05d19eaf1a3a4c93bca53ea6`; both were independently reread against prepared() from a checked snapshot. Normal observation counts0 are expected at unchanged idle; no ordinary-traffic/FPS proof follows.

D1-R/B gameplay is current priority. Broad R/B scope exclusion is paused after owner objected to its cost; retain shared coverage and existing Yellow evidence, defer new Yellow-specific work. Yellow's claim is deferred; E1 remains paused for gameplay priority. No manifest row was added/closed by D0. Preserve the legacy388-row inventory and evidence while explicitly aligning active R/B qualification; the old224/164 census is not a current R/B coverage count.

### Runtime pins and worktree safety

Use existing Python `C:/Users/howar/AppData/Local/Programs/Python/Python312/python.exe` (3.12.10). For assigned commands only: `SLINK_EMUHAWK=E:/Howard/Bizhawk/EmuHawk.exe`, `SLINK_UPR_JAR=E:/Google Drive/SLink/.cache/upr/PokeRandoZX.jar`, `PYTHONDONTWRITEBYTECODE=1`. Browser-specific overrides/receipts are in the configured integration report; no installation or global setting change is implied.

Use `git --no-optional-locks status --short`; no broad ignored-cache census. All Git mutations use `-c maintenance.auto=false -c gc.auto=0`. Parked speed-gate metadata was repaired and locked after an administrative incident; [receipt](reviews/SPEED_GATE_ADMIN_RECOVERY_2026-09-13.md). All18 registered worktrees are preserved. No parked working files/branches were moved, reset or deleted. `.cache` receipts are ignored and do not follow a fresh worktree automatically.

Full prior grants, source/test hashes, rejected candidates, process identities and transitions are retained in [the successor archive](RC_SUCCESSOR_TRANSITIONS_2026-09-13.md); prior worktree state in [the register archive](WORKTREE_REGISTER_TRANSITIONS_2026-09-13.md). Those archives grant no current ownership. The guide sections below remain the current evidence/dispatch/policy contract.

## What is fact, and what is a design

The cards below are a **map to investigate and complete**, not a claim that their proposed implementation will work. A manifest row establishes an obligation; source establishes current behavior; a unit model establishes only that model; an original-ROM run establishes only the path it actually exercised. The proposed file lists, route grouping, recovery algorithm, clean-resume mechanism, and future test interface are **design hypotheses** until falsified against current source and a bounded executable case. Agreement by several agents does not upgrade a hypothesis to evidence.

| Historical planning family | Established at code cut `df38453` (historical baseline; current results above supersede it) | Proposed or unproved at that old cut |
| --- | --- | --- |
| N0–N3 selected native | The [Manager host](../../server/bizhawk_launch.py) has a `prepare`/`launch` path; the [selected smoke](../../tests/live/test_gen1_native_selected_fresh.py) used `run_gate` around the downloaded script and passed only fresh-bedroom Y/Y and R/B. | Actual bundle CLI, nonnull party, receptionist, window consumption and paired saved trade remain unrun. First check N0's real CLI arguments/private SaveRAM and N1's continuously admitted original query. Do not infer N2 from source wiring. |
| R0–R4 recovery | [Reattach read](../../lua/gen1_native_reattach.lua) carries overlay/PC/SP/bank, a limited host record and lease **summary**; the [server](../../server/gen1_native_reattach_runtime.py) holds armed overlay, non-idle lease, pending native command or open trade. It does **not** infer which physical trade effects occurred from that summary. [Native progress](../../server/gen1_native_progress.py) binds old context/physical instance. | The 11-row classifier is design; complete held file/save evidence (R0b), new-client lineage (R1) and forward recovery (R2/R4) do not exist. First check each missing field/owner API and reproduce the current hold/refusal. A same PID or equal bytes alone is not rebind authority. |
| C1–C5 storage | [Whiteout](../../server/gen1_whiteout.py) currently rejects queued collateral `force_faint`; the parked C branch contains modeled rebuild work only. [Yellow client](../../lua/games/gen1_rby.lua) allows normally following starter Pikachu deposit and refuses the sleeping/disabled condition. | Collateral IDs, rebuilt saved-state migration, paired PC compensation and mid-write reconnect are proposed fixes. First falsify one exact two-link/one-sided saved case against current source; parked green model tests are not selected gameplay. |
| D0/D0b ordinary campaign | The manifest's 60 gameplay IDs and two text speeds are real. The legacy duo runner does not exercise the [checked selected entry](../../lua/gen1_client_entry.lua); [continuity](../../server/gen1_service_continuity.py) requires the original physical binding. | A thin scenario reporter and clean resumed run are **not implemented**. Before D0 code, prove a one-scenario reporting boundary using the current Manager outputs; before D0b code, specify the clean idle re-enrollment policy and show today's new-context refusal. Human route time is unmeasured. |
| E/T artifact and trade matrix | The 40 artifact/browser and 55 trade suffix IDs, existing UPR scans, browser download checks and standalone original-engine trade fixtures are real but bounded. | Per-title final-file boot and selected trade/negative receipts are unrun; category/route grouping is a scheduling proposal. First map the exact existing assertion and missing physical observation for one title card, then implement only the gap. |
| F/H qualification | The [release evaluator](../../tools/verify_gen1_release.py) really requires 15 checks, eight prerequisites, no skips/drift and later two-human attestation. | The final frozen non-quick run and human session have never passed on this cut. Their duration and environment failures remain unknown until preflight and execution. |

Before an integrator marks any **implementation** card READY, its claim record in this guide must contain: `(1)` literal requirement ID and user-visible behavior, `(2)` current code/pret/ROM citation with commit or hash, `(3)` observed failing or missing behavior, `(4)` proposed change clearly labeled hypothesis, `(5)` the cheapest old-code-failing check that could disprove it, `(6)` exact exclusive files/owner and dependencies, `(7)` positive **and refusal** exit evidence level/path, `(8)` what happens if the hypothesis fails, and `(9)` an explicit READY decision by the **integrator**, not the claimant. If one is missing, assign a **research-only** card first; no agent may self-approve implementation or edit this guide to authorize its own work. The integrator records the verified claim and decision here before parallel dispatch. This is how the plan survives compaction without becoming a pile of plausible-sounding instructions.

## Provider-neutral coordination contract

Roles, not agent brands, carry authority. The **owner** makes scope and replay-policy decisions. The **coordinator** (called “integrator” in some package cards) alone approves READY/ACTIVE, assigns exclusive paths, schedules the emulator, accepts merges, and updates this guide/register; these are one role, not two. An **implementer** changes only its assigned files. An **independent reviewer** checks the frozen diff and source without authoring that same cut. An **evidence runner** owns one granted live lane and returns exact receipts. One agent may fill multiple roles only when the card explicitly allows it; an author cannot self-review or self-approve. Any current or future agent type uses this contract.

The coordinator creates one durable assignment record **before** sending work through any transport:

```text
card_id / scope_and_required_IDs / authority_and_evidence_maturity
agent_type + session_or_task_id + host / role / coordinator
worktree + branch + base_commit + exact exclusive_files
verified_source_or_ROM_basis / hypothesis / first_falsifier
dependencies / positive_and_refusal_exit_receipts / live_lane_if_any
```

The receiving agent confirms the card, base HEAD and files before work. At a meaningful transition it returns `card_id`, identity/session, UTC, current branch/HEAD/dirty paths, commits/diff, checks with pass/fail/skips, evidence level and path/hash, source-versus-inference distinctions, unknowns, and one next owner/action. The coordinator verifies those against Git/source/receipts, records `PROVED` or `HOLD`, and commits the guide/register **in the same transition**. A missing acknowledgment leaves the card unclaimed; an agent losing contact does not silently transfer file ownership.

ClaudEx or any future message bridge is a **transport adapter**, not a source of authority. A socket write or queued-message ID does not prove the agent read the assignment; a model reply does not prove code or gameplay. Record opaque delivery IDs only for traceability. The durable claim is the guide entry plus verified branch/diff and runtime receipt, independent of which agent type or messaging system produced it. New agent types need read access to the guide/source and a way to return this record; lacking write or emulator capability limits them to review/research, not a workaround through another agent's permissions.

The same five steps apply to every agent type:

1. **Claim:** coordinator verifies branch/dirty state and dependencies, approves READY, reserves exact files and (if needed) a live lane; agent confirms the assignment before work. Done when this guide has one ACTIVE record with base HEAD and no overlapping writer.
2. **Change:** implementer checks pinned source/pret or actual runtime, demonstrates the smallest old-code failure, edits only assigned paths, and runs proportionate positive/refusal checks. Done when the diff and check results match the card, including shared Gen2/3 consumers where shared code changed.
3. **Review:** an independent reviewer reads the frozen diff and source; the coordinator resolves every finding against evidence. Done when the reviewed diff hash and accepted/rejected/open findings are recorded, not when a peer merely replies.
4. **Prove:** the evidence runner gets the sole emulator grant for a physical card and records run ID, title pair, source HEAD, launch path, SaveRAM roots, exact bytes/ACKs and evidence directory. Done when the requested positive and refusal receipts exist, or the card is HOLD with an exact failure; a fixture, aborted run or queued message is not a pass.
5. **Integrate:** coordinator checks Git and receipts, merges only reviewed files, updates this guide and [register](WORKTREE_REGISTER.md), releases file/live ownership and names one next card. Done when both records are committed and no two cards own the same files. An unexpected source result returns the card to research; it does not silently broaden the assignment.

## Dispatch rules and dependency graph

A package is one behavioral claim, preferably one to three production files and a bounded assertion/receipt. Split a proposed shared abstraction or whole route driver before coding. The coordinator records **authority** (`WAIT`, `READY`, `ACTIVE(owner,branch,files)`, `PROVED(receipt,commit)`, `HOLD(reason)`) separately from **evidence maturity** (`SOURCE FACT`, `MODEL ONLY`, `DESIGN`, `PHYSICAL RECEIPT`). Implementation READY requires the nine-part claim record. **Current granted cards and completed P0 are recorded above.** Other cards require their own claim; F1's unit/integration execution needs a separate command/output assignment. P0b is conditional on a new agent type; policy and implementation cards retain their stated owner/dependency gates. Only the explicit current assignments above are ACTIVE. Completed W0 findings and the actual fresh-session audit are in the [review record](reviews/RC_PLAN_REVIEW.md); reuse their source mapping.

A single integrator owns `gen1/rc`, shared runtime files, the manifest, and the one EmuHawk lane. Source/ROM research and test-scenario design may be parallel. Distinct agents may code in disjoint file sets/branches; `gen1_runtime.py`, `gen1_client_entry.lua`, `gen1_native_execution.py`, storage runtime, UPR pipeline, companion build, browser output bridge and D0 scenario core each have **one writer at a time** and an exact integrator-assigned file list. N native writer goes before C5/D0b on the overlapping client/runtime paths. A completed card is reviewed/merged before dependent code starts. Live runs queue separately; never overlap two EmuHawks with another measured job. An unchanged failure is diagnosed once, not rerun until source, oracle, or explicit policy changes. Official [Git worktree](https://git-scm.com/docs/git-worktree/2.42.1), [Claude worktree isolation](https://code.claude.com/docs/en/worktrees), and [small/stacked review](https://docs.github.com/en/pull-requests/get-started/about-pull-requests) guidance supports isolated edits and reviewable dependent cuts; it does **not** justify dozens of idle checkouts.

Dependency order (parallel braces are **offline** code/research, not concurrent emulators):

`P0 environment → independent offline forks {N0 bundle, R0 classifier, C1 storage source, D0 interface design, E artifact/browser source}`. N1 waits separately for the **same still-running Lua/emulator process** to reach the receptionist with its admitted source history; it does not require uninterrupted TCP and does not depend on C/E/R0. `N1 → N2 → T native trade matrix`. `R0 → R0b held evidence → R1 same-process new-client lineage → R2a/R2b forward recovery` (physical recovery needs N2). `D0 → ordinary D1–D20` independently of N2; deep repeatable D/T human routes also need `P2a → D0b` clean resume, while D14–D17 wait for their C code cards. E source work is independent; actual artifact-trade T18 joins E with N2. `P2b → R3 → R4a/R4b/R4c` replaced-process recovery; reviewed cuts converge at F frozen RC, then H human release.

C storage code can progress alongside native source work after owner go-ahead if it never edits B-owned runtime/client files; C5 reconnect waits for an integrator handoff. D and E scenario modules can be authored in parallel after D0/N0 file interfaces and the browser output-bridge paths are frozen. **Ordinary D1–D20 do not depend on native N2**: early axes may run continuously after D0; deeper one-time axes and repeated human sessions need D0b clean same-run resume. C physical D14–D17 need their C fixes plus D0, not a native trade. Trade T cards do depend on N2. A user-provided save/state is controlled-engine rehearsal only. N1 needs the party at the counter **without leaving the admitted process**; even this run's own SaveRAM after relaunch waits for explicit re-enrollment proof. No one resumes the stopped natural-walk harness on Claude's dirty B tree.

Dispatch waves (not dates): **W0 mapping DONE at this guide cut** — three read-only B/C/D/E audits and Claude adversarial review checked source/manifest arithmetic; do not redo that survey. P0/F1's environment/skip census remains a separate finite check. **W1 after owner go-ahead** — disjoint N0 host, R0 pure classifier, C1 whiteout, E1 UPR and E10 browser producers may each have an isolated writer; D0 interface owner may design beside them but N0/bundle file paths are frozen before D0 code. **W2 by independent gate** — after D0, ordinary early D axes and E artifact scenarios can start without N2; after C fixes, D14–D17; after N2, R2/T trade. D0b clean idle resume is an early continuity writer for deep repeatable routes, never concurrent with native/client edits. Each scenario agent owns a separate assigned file; shared C and native producers serialize. **W3 physical evidence** — integrate each cut, schedule one bounded original-engine title/pair run at a time; multiple agents prepare the next independent scenario offline, never two emulator lanes. **W4 freeze** — all writers stop, F0–F4 one integrator, then H0/H1. A wave is not permission to start a WAIT card; the integrator claims specific files first.

## Package catalog and dispatch

The [static package catalog](RC_PACKAGE_CATALOG.md) holds the P/N/R/C/D/E/T/F/H cards and manifest suffix mapping. The coordinator verifies one card's current source/falsifier and writes its ACTIVE record **here**. For a fresh session, provide a self-contained brief with explicit blockers and permitted outputs: [P0 input preflight](dispatch/P0-preflight.md) and [D0b design research](dispatch/D0b-research.md) are concrete prepared examples. Their status remains here; a brief cannot authorize itself. Later implementation briefs must include the agreed spec and exact exclusive files rather than ask an agent to infer them from a catalog row.

Use the [ask-matt skill routing assessment](reviews/RC_PLAN_REVIEW.md#ask-matt-routing-result) when preparing a new task type. It recommends `to-spec` for an accepted design, `to-tickets` for a self-contained slice with blockers, and `handoff` for changing agent/host, while retaining the current repository tracker and coordinator approval. Each fresh dispatch includes the canonical entry path, named coordinator/assignee, actual base HEAD, permitted commands and receipt destination. Agents may discover unprovided host facts; they must not guess policy or implementation authority.

## Owner decisions and failure policy

- **P2a policy approved by owner:** conservative clean same-run resume only after both players saved before either exits, both files match newly verified server-acknowledged save checkpoints, source/bundle unchanged, no pending commands/trade. Save-witness/file-permit/re-enrollment mechanisms remain unimplemented and gated by N0/D0 plus explicit claims. **P2b replaced-emulator partial-trade visible replay remains unapproved**, as does P-1 held-survivor save-only release. Saved-but-unwitnessed, rollback, wrong epoch, savestate invalidation and unknown high-water HOLD. Identical bytes or peer agreement do not authorize forward replay or a second RemovePokemon/AddEnemyMon.
- An imported battery save in a new Manager run and loading an external savestate into a running selected run are refused by design. A user-made receptionist save is **not** selected evidence on its own, even when it came from the same run: relaunch creates a new physical context and D0b/R4 re-enrollment is unproved. N1 today needs the same still-running Lua/emulator process at the counter; a recoverable TCP interruption is a separate checked question. Scripted normal inputs are now owner-authorized under bounded reviewed cards; they never authorize synthetic save, party, map, HP or CPU staging.
- The owner accepts current near-3× numbers but one strict post-merge 173.0 floor invocation failed by 0.070. F0/P1 must settle the final explicit threshold **without** lowering 1×, quiet 3×, frame-skip, byte/ACK, backlog, or hold criteria, and run the frozen gate once. Do not tune FPS endlessly or claim 5×.
- The owner authorized execution of the existing C–E plan; each implementation still requires its documented prerequisites, owner decisions and coordinator's complete claim/exclusive-file grant. A package with a missing choice or contradictory source becomes HOLD with exact evidence; independent packages continue.

## Resume and archive safety

Before compaction, break, or agent transfer, the coordinator records UTC, current HEAD/dirty paths, ACTIVE/HOLD cards, live processes, verified receipts and failures, owner decisions, and **one next owner/action** at the top of this guide; the successor checks Git and evidence before acting. Archived handoffs and `proposals/` are historical rationale, not an active queue. Other game/UI work remains outside this Gen 1 authority.

Before physically moving or removing a worktree, verify absolute paths, tracked/untracked/**ignored** receipts, branch history and task bindings. Historical clean checkouts are [archived in place](WORKTREE_REGISTER.md); dirty B/performance trees remain quarantine until a separate validated archival decision. Preserve recoverability, including branch and evidence paths.

## Sources and verification anchors

- Project contract and runner: [Gen 1 release requirements](../../tests/gen1_release_requirements.json), [release evaluator](../../tools/verify_gen1_release.py), [pret source pins](../../data/pret_sources.lock.json), [canonical companion profiles](../../server/gen1_cartridge_profiles.py). Counts/IDs above were read from the manifest at the documented cut, not inferred from registration status.
- Native/ordinary source: [client entry](../../lua/gen1_client_entry.lua), [observation loop](../../lua/gen1_observation_loop.lua), [receptionist authorization](../../server/gen1_receptionist_runtime.py), [native execution](../../server/gen1_native_execution.py), [storage](../../server/gen1_storage_runtime.py), [whiteout](../../server/gen1_whiteout.py), [recovery classifier design](NATIVE_RECOVERY_CLASSIFIER_2026-09-12.md). The local pinned pret trees under `.cache/pret` contain the original R/B/Y assembly; [trade receptionist patch](../../patch/gen1/src/trade_receptionist.asm) and [Yellow Bill's PC source](../../.cache/pret/pokeyellow/engine/pokemon/bills_pc.asm) settle corresponding game behavior. Source is not a live emulator receipt.
- Workflow sources (method only, accessed 2026-09-13): Git project, [`git-worktree` manual v2.42.1](https://git-scm.com/docs/git-worktree/2.42.1); Anthropic, [“Run parallel sessions with worktrees”](https://code.claude.com/docs/en/worktrees); GitHub Docs, [“About pull requests”](https://docs.github.com/en/pull-requests/get-started/about-pull-requests). These support isolated edits and reviewable dependent cuts, not release claims.
