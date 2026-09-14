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
  "updated_at_utc": "2026-09-14T00:13:39+00:00",
  "coordinator_session_id": "9a7ac120-04eb-489f-8fd1-c9ecb67b31a6",
  "source_head": "c647f9126e79909f2b5976beec65d7b3beedd737",
  "live_lane": null,
  "next_action": "Dispatch BI-1 (R6 Growl acceptance fix, red model test first) to an isolated implementation worker; R6-SRC source fact-check to the contextual peer; TK-1 drift check to OMP. Integrate reviewed BI-1, then one R7 live run.",
  "workers": [
    {
      "id": "battle-input",
      "owner": "isolated implementation worker (BI-1; Codex headless delegate, pending acknowledgment)",
      "state": "ready",
      "files": [
        "lua/tests/gen1_rb_ball_gate_inputs.lua",
        "tests/unit/test_gen1_selected_rb_ball_gate.py",
        "docs/gen1_reference/reviews/D1-RB-implementation-successor.md"
      ],
      "next_action": "Red model test replaying R6 (Down accepted, A emitted next frame and dropped in HandleMenuInput_ Delay3, driver must re-pulse until wCurrentMenuItem 2->1 / PP drop), then the driver fix; report diff hash.",
      "reuse_decision": "game-specific test driver (R/B lab route facts); 're-pulse until observed acceptance' stays local until the parcel module becomes a second consumer",
      "receipt": "docs/gen1_reference/reviews/D1-RB-implementation-successor.md",
      "independent_review_refs": [
        "coordinator-verified current-card peer review recorded in transition archive"
      ]
    },
    {
      "id": "r6-source-check",
      "owner": "contextual Codex peer Gen1-p2 (read-only)",
      "state": "active",
      "files": [
        ".cache/pret/pokered/home/window.asm",
        ".cache/pret/pokered/engine/battle/core.asm",
        ".cache/pret/pokered/home/vblank.asm",
        ".cache/pret/pokered/engine/joypad.asm"
      ],
      "next_action": "Confirm/refute the Delay3 dead-window and wCurrentMenuItem acceptance facts against pokered 405b624 and BizHawk joypad.set per-frame semantics; no edits.",
      "reuse_decision": "research only"
    },
    {
      "id": "takeover-drift-check",
      "owner": "OMP live session pid 47172 (read-only)",
      "state": "active",
      "files": [
        "docs/gen1_reference/reviews/R0-supplied-contract-successor.md",
        ".cache/current-cards-final.xml",
        "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md"
      ],
      "next_action": "Report R0 working-copy hash vs frozen 4dadeb79..., current-cards-final.xml counts, parcel hashes vs report; three lines, then exit.",
      "reuse_decision": "research only"
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
      "owner": "released (/root/d1_rb_parcel_sol); files preserved untracked",
      "state": "frozen",
      "files": [
        "lua/tests/gen1_rb_parcel_inputs.lua",
        "tests/unit/test_gen1_rb_parcel_inputs.py",
        "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md"
      ],
      "next_action": "Wait for the R7 lab checkpoint PASS and a raw menu producer; then rebase/review for integration.",
      "reuse_decision": "game-specific adapter for pinned R/B routes; shared host and HUD reused",
      "receipt": "docs/gen1_reference/reviews/D1-RB-parcel-module-successor.md",
      "independent_review_refs": [
        "coordinator-verified current-card peer review recorded in transition archive"
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
- **Live state:** RESUMED. No emulator lane granted yet; R7 waits for the reviewed BI-1 fix. Mute is DONE; Yellow-specific work deferred.
- **Dispatch:** fully specified cards may be ACTIVE conditional on the first matching Git/hash/scope acknowledgment; a mismatch means HOLD.

### R6 diagnosis and next action

**R6 root cause (SOURCE FACT for the game path; hypothesis for the driver until the red model test confirms it).** Both cartridges failed at the identical point (`Y12/X5/max3/index2`, Growl PP 40). The driver's `press()` fires on `frame%16<2`: `Down` is accepted inside frame `16k` (`HandleMenuInput_ .loop2` polls without `DelayFrame`), the next step already reads `wCurrentMenuItem==2`, and `press("A", 16k+1)` emits a one-frame `A` immediately after the cursor move. pokered is then in `SelectMenuItem_CursorDown → SelectMenuItem → HandleMenuInput_ .loop1 → PlaceMenuCursor → Delay3` (`home/window.asm:14-19`, `engine/battle/core.asm:2702-2709`); `_Joypad` is not called for ≥3 frames and `hJoyInput` is overwritten every VBlank (`home/vblank.asm:77-79`), so the pulse is dropped. The driver then idles 600 frames because it treated *emitted* as *accepted* (`gen1_rb_ball_gate_inputs.lua:110-123`). Attempt 5's repeated pulses used Growl (PP 39), which corroborates the mechanism. The game's own acceptance write is `wCurrentMenuItem` 2→1 (`core.asm:2624-2626`) followed by the PP drop.

| Item | Verified state / next owner action |
| --- | --- |
| Battle path | BI-1 READY→ACTIVE on acknowledgment: red model test replaying the dropped pulse, then re-pulse `A` on the 16-frame cadence while the cursor still sits on Growl with unchanged PP; index 2→1 with unchanged PP = accepted-not-executed (idle, no Down); PP drop → existing `awaiting_main_menu`; 600-frame bound from first emit. Independent review of the frozen diff precedes R7. |
| Shared HUD | Integrated at c647f91; source/model passed. Physical pixel-expiry proof remains an open limit. |
| Checks | 188 current-card tests, no failure/error/skip; `.cache/current-cards-final.xml` `bc078899…ffa6`. No fresh release-evaluator verdict. |
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
