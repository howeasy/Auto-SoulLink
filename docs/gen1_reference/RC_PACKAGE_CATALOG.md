# Gen 1 RC package catalog

This is the **static reference** for the package IDs in [RC_MASTER_GUIDE.md](RC_MASTER_GUIDE.md). It defines proposed work boundaries and exit receipts; it does **not** grant implementation authority, report current status, or create a second queue. A coordinator checks the master guide and an exact card's source/falsifier before assigning it. Read the assigned card and its named prerequisites; load other sections only when their dependencies fire. Literal requirement IDs remain in [the manifest](../../tests/gen1_release_requirements.json).

## Small packages: policy, native selection and recovery

Each row is a separately claimable card. `Files` are the initial exclusive surface, not permission to change other shared modules. `Done` always includes a reviewed diff, targeted positive/refusal checks, exact receipt path/level, and a guide update; a physical claim needs original-engine bytes, not a mocked result.

| ID and owner | Entry; exclusive files | Done/required proof |
| --- | --- | --- |
| P0 integrator | Now; manifest, runner, pinned inputs, environment only | Verify 388/224/164 and eight prerequisites: three legal R/B/Y ROMs, pinned EmuHawk, UPR ZX JAR, Java, Archipelago `pokemon_rb.apworld` and LuaSocket DLL. Identify symlink-privilege/conditional skip sites and real final-run machine budget. No re-pin/full gate now. |
| P0b coordinator, each new agent type | ClaudEx or another runtime exposes a new agent type; no product files | Prove a read-only onboarding handshake: agent receives the universal README, returns its type/session/host, confirms card/base HEAD/files and capability limits, and coordinator records acknowledgment/release. If delivery or permission cannot be verified, that type remains research-only. No assumption about a future ClaudEx schema or model brand. |
| P1 owner/integrator | Before final freeze; existing 173.0 test threshold vs accepted 172.930 window | Record one explicit active-3× acceptance rule and its floor/variance oracle; 1×/quiet and byte/ACK/hold checks unchanged. Old failure stays failed. No speculative 5× work. |
| P2a owner | Before D0b clean idle resume | Approve or refuse a **clean, no-pending-command** same-run re-enrollment using last source/file/lease high-water; explicitly forbid converting this into post-COMMIT replay authority. |
| P2b owner | Before replaced-process forward code R3/R4 | Choose visible animation replay and controlled re-enrollment after a partial native trade (or accept a permanent hold and resulting unmet recovery goal). Saved-but-unwitnessed, rollback and unknown high-water default to HOLD. |
| N0 host-path owner | B3 fresh selected source; `server/bizhawk_launch.py`, `tools/launch_bizhawk.py`, separate host gate | Downloaded bundle `launch.json`/`launcher.lua` plus admitted ROM actually start through product CLI for both players, with private config/SaveRAM, process lease and held/enrollment receipts. Existing `prepare` preflight alone does not pass. |
| N1 native UI owner | Valid **same-admission** party at original receptionist; `gen1_receptionist_runtime.py`, `gen1_native_observation.py` and one selected scenario | Nonnull same-frame party checkpoint, original query/ACK, eligible linked mask, no original fallback or unowned frames. Human input may supply the route; no fabricated first-admission save. |
| N2 native trade owner | N1; `gen1_native_execution.py`, `lua/gen1_native_runtime.lua`, executors, selected Y/Y then R/B | Both original hooks/animations, bounded grant→consume→terminal hold/release, paired prepared/full-save/COMMIT receipts and verified on-disk SaveRAM images; wrong/late command stays held. This is **not** proved today. |
| N3 integrator | N0–N2 | Retain bounded selected Y/Y+R/B proof and review 1×/accepted 3×, refusals and queue on final source. Do **not** claim the existing `trade.paired-native-client-integration`/`trade.native-ui-to-animation` umbrellas: their descriptions demand **all nine ordered pairs** and converge at T19/F0. |
| R0 native classifier owner | Current rev-4 [11-row design](NATIVE_RECOVERY_CLASSIFIER_2026-09-12.md); new pure classifier, no actuator/shared runtime edit | Pure typed class/refusal decision for every row from supplied exact evidence; unknown/rollback/partial evidence HOLD, no byte-shape-only forward inference. This does **not** persist or authorize action. |
| R0b held-evidence owner | R0; `gen1_native_reattach_runtime.py` and owned readback/lease/file adapters | Capture and durably bind source-pinned overlay+party/SaveRAM/file/lease-revision/host high-water under a current held owner. An absent/stale field refuses. The existing reattach summary alone lacks R/S/file evidence for rows 3–8. |
| R1 native same-process rebind owner | R0b; `gen1_client_entry.lua`, `gen1_native_progress.py`, `gen1_native_windows.py` under **one** file handoff | A restarted Lua client in the **same emulator PID** gets fresh context/physical nonces. Prove an explicit old/new admission and lease/window high-water lineage before any fresh grant; mismatched epoch/rollback HOLD. No forward step yet. |
| R2a native same-process owner | R1+N2; `gen1_native_execution.py`, one client-loss scenario | Client lost with emulator alive at routine prefix 2 resumes under **new bounded windows** and the same logical command, without a second RemovePokemon/AddEnemyMon; exact hook/file readback. Persist the classifier decision and its evidence digest atomically before forward action. |
| R2b native same-process owner | R2a; `gen1_trade_recovery.py`, `gen1_native_reattach_runtime.py`, server-restart/one-sided scenarios | Before-arm, mid-routine, DONE-unreleased, one-sided applied/verified/released and server restart: **decidable classes forward-complete** once with selected physical receipts. Unknown/rollback remains named HOLD and is not a passed `trade.{red,blue,yellow}.recovery` row. |
| R3 owner-policy integrator | P2b+R2b | Specify cross-process lease supersession, old/new host lineage and when visible replay is allowed. No code until the decision is written. |
| R4a replacement evidence owner | R3+N2; source-pinned CONTINUE and native lease readers | Fresh process boot/READ/save/file witness bound to old run and exact B/A image; wrong process/epoch and missing lease HOLD. No forward window yet. |
| R4b replacement lineage owner | R4a; reenrollment component + `gen1_native_windows.py`/native lease store under one writer | Persist old/new physical/process lineage, lease supersession and monotonic window high-water. A stale, rolled-back or competing process cannot spend a grant. |
| R4c replacement physical owner | R4b; selected reboot fault scenarios | Process-kill Y/Y and R/B, equal/non-equal B/A, partial routine/save, witnessed/unwitnessed save, wrong epoch/rollback; decidable cases forward-complete with one surviving logical effect and no second physical party swap, otherwise named HOLD. Permanent HOLD on ordinary process loss is **not** completion of the owner's recovery goal. |

## Small packages: C storage and D ordinary play

C remains planned until owner go-ahead. The parked `codex/gen1-storage-sync-runtime` branch is **modeled-only and old-base**; re-review each exact diff, never cherry-pick it wholesale. [Pinned Yellow Bill's PC assembly](../../.cache/pret/pokeyellow/engine/pokemon/bills_pc.asm) and [Gen 1 storage policy](../../server/gen1_storage_runtime.py) are source/implementation anchors, not live proof.

| ID and owner | Entry; exclusive files | Done/required proof |
| --- | --- | --- |
| C1 storage owner | Go-ahead; `server/gen1_whiteout.py` **and** `gen1_faint_runtime.py` under one assigned owner; `state.py` only by separate Root handoff | Distinct source/registry-bound IDs and durable phase/peer command for every collateral linked death; 2–6 linked pairs, mixed party, battle/poison, replay and HUD atomically. Current whiteout rejects a second linked death. |
| C2 storage owner | C1; `gen1_storage_runtime.py`, `gen1_storage_policy.py`, `gen1_memorial_runtime.py` serialized | Re-review the **parked model branch's proposed** six-member memorial-before-rebuild and `rebuild_holds` design against current RC/HUD code; establish ordered survivors, full party/Box12 overflow and both saved ACKs. Specifically falsify legacy `rebuild_pending`, changed/dead survivor, replay and rollback-to-old-binary cases before selecting a migration/hold policy. These are not current RC capabilities. Physical receipt is D15/D16. |
| C3 PC owner | C2; `gen1_storage_runtime.py` and held storage executor after file handoff | Model source-qualified Bill's PC choice/confirmation and movement→two held reads→writes→both ACK or bounded inverse, with exact non-target bytes and capacity refusals. Selected-run file/choice receipt is D14 after D0/N0. |
| C4 Yellow owner | C3 interface; `lua/games/gen1_rby.lua`, `lua/memory_gb.lua`, `server/gen1_storage.py` with exact file handoff | Source-model Yellow starter Pikachu's **normal following deposit allowed** with happiness/mood effect, **sleeping/disabled following deposit refused**, plus release-menu confirmation/refusal and partner-refused undo without non-target write; the live original-engine `memory.yellow.pc-restrictions` row is a separate D0/N0 receipt. |
| C5 reconnect owner | B/C shared-file handoff + C3; `gen1_client_entry.lua`/`gen1_service_continuity.py` and review `gen1_held_faint.lua`/`gen1_runtime.py` before ownership transfer | Model mid-write disconnect and one-of-two saved ACK under held current context, same FIFO, single-use permit, no duplicate write or premature free frame. Selected-run epoch rotation, both file receipts/replay and bounded queues are D17 after D0/N0. |
| D0 campaign interface owner | N0, after go-ahead; one small checked Manager scenario/receipt module, exact browser bridge boundary recorded before work | A thin reusable selected-run observation/reporting interface, **not** an automated Pallet-to-Cable-Club adventure. Accept normal human/game inputs, record source/ROM/host, full bytes, ACK/queues and physical files; one first title/pair receipt freezes the interface. C/D/E scenario agents then use it without editing its core. |
| D0b clean same-run resume owner | P2a+D0; `server/gen1_service_continuity.py` and `lua/gen1_client_entry.lua` under Root handoff, clean idle only | A checked run saved in-game at an acknowledged idle checkpoint, exited cleanly, relaunched via its own bundle and re-admitted with fresh owned context, current source/file/lease high-water and no pending trade/write. Wrong/older SaveRAM or epoch HOLD. This is **not** R4 post-COMMIT process-loss recovery; deep D/T human routes must not assume it already exists. |

For D rows, `gameplay.{r,b,y}.suffix` expands to the three literal `red/blue/yellow` manifest IDs. **Dispatch one title subcard at a time**, e.g. `D9-blue` owns only `gameplay.blue.encounters` and its own scenario file. Each literal ID needs **two** fastest-text settings (six axis receipts across the three subcards), not necessarily six launches. Group compatible axes in one honest run; one-time grants may need separate fresh admitted runs when the text option cannot be revisited. Reaching Safari/Game Corner/late statics by normal human play is real time, not a free fixture; D0b owns clean multi-session continuity. No synthetic party, map flag, battle HP or save writes. A title's negative/refusal oracle and real selected-run source/ACK/file receipt are mandatory. `D0` is the shared interface; one row becomes PROVED only after its three title subcards are done.

Campaign route work is **source planning**, not a generic gameplay autopilot: map the one-time story beats and encounter/PC sites from the pinned pret assembly, then group each title's normal and fastest-text observations into the fewest legitimate admitted runs. Some one-time beats require a second fresh run; later maps require hours of real play and D0b clean resume. Record that labor before scheduling the live lane. If normal human inputs become the critical bottleneck, the owner may authorize one narrowly scoped, source-pinned button script with **no** RAM/state/save/CPU staging; that would be a separate reviewed card, not an assumption or a way to bypass admission.

| ID (3 IDs unless noted) | Prerequisite; scenario owner and exact exit |
| --- | --- |
| D1 `ball-gate` | D0; first source-qualified Poké Balls activates linked clauses at the exact event, not retroactively. |
| D2 `capture-ordering` | D1; original species/level/area, no-catch source, party receipt and linked identity ordering match both ROMs. |
| D3 `duplicates` | D2; complete duplicate/colliding family (including distinct Hitmons where applicable), refusal and untouched save/queue. |
| D4 `clauses` | D1; species/area/dupes outcome matches one `SoulLinkState` decision on both sides. |
| D5 `dead-zones` | D4; retirement/memorial of forbidden encounter with no accidental link. |
| D6 `safari` | D0; safari encounter/ball source and no-catch refusal from original ROM. |
| D7 `statics` | D0; exact static site/ordinal, no double grant. |
| D8 `ghosts` | D0; ghost/revealed-site negative outcome without fabricated capture. |
| D9 `encounters` | D0/D0b for deep routes; every grass/water area and actual Old/Good/Super Rod encounter by title, exact method/source classification and untouched no-catch. |
| D10 `grants` | D0; exhaustive typed grant registry, exactly one bounded-frame source predicate, ambiguous source HALT without mutation, partner linkage/retirement. |
| D11 `game-corner` | D10/D0b; successful purchases consume exactly one persisted ordinal; cancelled, failed, insufficient-coins, TM and duplicate transactions consume none. Player-choice species clauses still apply. |
| D12 `npc-exchanges` | D0; original NPC exchange input/output and linked identity disposition. |
| D13 `yellow-retirement` | D0; mixed-title Yellow Bulbasaur/Charmander/Squirtle permanent auto-retirement in party/current box, no link; **not** Pikachu PC/follower restrictions (C4). |
| D14 `full-storage` | C3/C4+D0/N0; full boxes and grant-current-box delivery, checked both-player PC/storage, refusal and both saved ACK/file receipts. |
| D15 `faint-whiteout-rebuild` | C1/C2+D0; active and benched HP, real blackout, exact collateral death IDs, paired commands and ordered rebuild. |
| D16 `memorial-overflow` | C2+D0/D0b; actual 20-slot archive, initialized bit, capacity/Box12 refusal, memorial-before-rebuild and reset persistence. |
| D17 `reconnect` | C5+D0/D0b; active obligation across admission-epoch rotation, durable replay, bounded queues, both file receipts and no duplicate effect. |
| D18 `evolution` | D0; actual evolution keeps its linked identity with collision check, source/level and bounded partner outcome (family/Hitmon clause matrix belongs to D3). |
| D19 `rival-swap` | D0; opponent class+200 trainer signal, full replacement payload validated **before first write**, and original checked paired team result. |
| D20 `explode` | D0; all four active moves **and PP slots** replaced, original battle execution in authorized slot, ≤30-frame eligible heartbeat/≤64-frame window, exact faint/death receipt. |

D21–D25 are the **five separate production duo umbrellas** `duo.red.blue`, `duo.blue.yellow`, `duo.yellow.red`, `duo.red.red`, `duo.yellow.yellow`. Each owner uses the frozen D0 interface, after relevant D/C axes, to prove paired ordinary play, both speeds, no queue growth, real HUD draw/erase/reload and one saved-file reconciliation. The registered `*.existing-core-scenarios` legacy-duo rows are component evidence, not these five umbrellas. D26/D27 separately prove `manager.blue.blue.same-hash` and `manager.yellow.yellow.same-hash` via actual N0 product launch and private SaveRAM/process isolation (including reset/reload and a cross-write sentinel). Two title agents can prepare those scenarios in parallel; live slots serialize.

## Small packages: E artifact/browser and native trade matrix

E has one writer for the UPR/companion producer and one writer for the browser adapter; category research and title scenario files can be parallel. The existing pinned JAR/integration semantic scans, Chromium download/hash checks, and controlled native trade fixtures are bounded evidence, **not** final artifact boot/selected trade. E1–E9 each denote one category × three titles (three literal `upr.{r,b,y}.suffix` IDs); dispatch `E1-red` etc as title subcards on distinct scenario files. Any actual change to common `server/gen1_upr_policy.py`/`gen1_upr_scan.py`/`gen1_upr_pipeline.py` has **one serialized producer writer**. Done per title: pinned settings/seed, forbidden-domain scan, structural injection, final SHA, admitted/booted actual companion; a category row becomes PROVED only after three title subcards. Categories:

| Card | Manifest suffix | Card | Manifest suffix | Card | Manifest suffix |
| --- | --- | --- | --- | --- | --- |
| E1 | `wild-species` | E2 | `scripted-grants-statics` | E3 | `starters` |
| E4 | `trainer-parties-levels` | E5 | `tm-assignment` | E6 | `field-hidden-items` |
| E7 | `evolution-methods` | E8 | `fastest-text` | E9 | `combined` |

| ID | Entry; exclusive files | Done/required proof |
| --- | --- | --- |
| E10 `browser.{r,b,y}.clean-ups` | D0/N0; `tests/browser/gen1_patcher.cjs` and separate output bridge | Genuine Chromium clean ROM download/hash/no-upload/refusal then exact downloaded file **boot**, admitted title and content pin. |
| E11 `browser.{r,b,y}.randomized-injector` | E1–E9+E10; same browser owner serialized | Approved UPR browser output and its actual final boot/hash/selected admission, not just a DOM/download assertion. |
| E12 `patch.{r,b,y}.capabilities` | Companion build owner; `tools/build_gen1_companion.py`, `server/gen1_patcher_targets.py` | Final artifact independently matches bank-qualified source manifest: R/B panel+trade, Yellow trade-only, all SFX false unless separately proved. |
| E13 `panel.red.matrix`/`panel.blue.matrix` | E12; `patch/gen1/src/trade_ui.asm` + panel scenario | Original START panel three blank transfers, stable generation/reveal/ACK/restore from final downloaded/Manager artifact. No Yellow panel. |
| E14 `sfx.red.gate`/`sfx.blue.gate` | E12; capability/route source only | Truthful safe-disabled SFX with panel/trade unaffected, or a separately owner-authorized proved-on hook; no optional SFX implementation inferred. |

The 55 empty trade requirements are **18 suffix cards × three titles plus one global card**. `T-suffix` denotes the literal `trade.red.suffix`, `trade.blue.suffix` and `trade.yellow.suffix`; dispatch one title subcard such as `T4-yellow` with a distinct assigned case file, then mark the row PROVED after all three. The odd `yellow-pikachu` suffix exists under all title prefixes and cannot be omitted. No scenario agent edits shared native runtime/patch files without handoff. Existing standalone fixtures may be lower-level oracles, but selected original-ROM read/ACK/physical refusal is required for the production claim. T1/T3 and other late-map scenarios need human gameplay time and D0b clean resume (or a continuously admitted run); no 55 new engines or worktrees.

| Card suffix | Entry; one physical exit |
| --- | --- |
| T1 `every-receptionist` | N1; original object dispatch at every required Center/Indigo site, availability and no accidental fallback. |
| T2 `cable-club` | N1; unavailable SLink path returns to unmodified original Cable Club without write. |
| T3 `directions-maps` | N2; either player initiates, supported maps and held query context. |
| T4 `busy-queued` | N2; partner busy in battle/menu queues the offer and releases its prompt only in a verified safe state; no overlapping native owner. |
| T5 `offer-lifecycle` | N2; offer, decline, **pre-COMMIT five-minute expiry**, cancel, simultaneous/stale token and exact closure. |
| T6 `counts-slots` | N2; party 1–6 and every legal slot including middle removal/append, ineligible refusal. |
| T7 `blob-fidelity` | N2; complete 66-byte HP/status/moves/PP-Up/experience/stat-exp/DVs/OT/name/trainer fields and no non-target mutation. |
| T8 `dex-persistence` | N2/D0b; Seen+Owned and SavePartyAndDexData, immediate source save/reset readback and exact file receipt. |
| T9 `evolutions` | N2/E1–E9 where randomized; four vanilla trade-evolution species plus admitted UPR methods, DV/OTID, learning and recipient ROM result. |
| T10 `yellow-pikachu` | N2; Yellow trade happiness/follower outcome in each required title pairing, not a generic PC restriction (C4 owns that). |
| T11 `canonical-physical` | N2; original Remove/Add/hooks/animation/SaveRAM on each title. |
| T12 `recovery` | R2b/R4c; named fault matrix and **one-sided verified forward completion** on decidable classes; unknown/rollback HOLD is honest but does not pass this row. |
| T13 `duplicates` | R2b/N2; replay/duplicate operation cannot make second surviving logical trade. |
| T14 `durability` | R2b/N2; both file flushes/ACKs, restart readback and no premature migration. |
| T15 `malformed` | N2; malformed query/slot/receipt refuses with zero unauthorized write. |
| T16 `capability-refusal` | N2/E12; ABI-2/codec mismatch and mixed-capability/title/profile/host matrix refuses while held. |
| T17 `foreground-overlay` | N2; versioned serial patch-list first-16 overlay, staged enemy-party blob and clear **before Cable Club**, including reset/map. |
| T18 `browser-artifact-trade` | E10/E11+N2; actual browser-downloaded clean/randomized artifact performs selected trade/file closure. |

T19 is the one global `trade.vanilla-animation-both-peers`: after T1–T18's reusable selected path, prove both physical animation and saved result for all **nine ordered pairs**. The existing 18 ordered HELLO contract rows are already registered but do not prove these physical trades. Live matrix scheduling is one lane; do not launch nine pairs concurrently.

## Freeze, RC, human release, and project handoff

| Card | Entry; one owner | Done |
| --- | --- | --- |
| F0 proof audit | All product/scenario cards; integrator reviews the 388 IDs | Reconcile 13 fixture-trade and seven legacy-duo registrations with honest assertion bases; register only actually collected selected tests (including selected-fresh) in explicit check argv, no empty automated row or phantom test. **Budget durations of every newly registered live file against the current 4 h live-gates cap** before freeze. Source-diff review by affected file, not 7,180 separate imagined defects. |
| F1 environment | May start read-only now; integrator/host owner | Eight prerequisites hash-admitted and symlink/conditional imports/legal ROM present. One **zero-skip** dry unit+integration census on the final machine before freeze; repair environmental skips rather than hide them. No repeated all-day reruns. |
| F2 freeze/pins | F0+F1 and all implementation merges; integrator only | Lock source **and manifest**, re-pin each affected proof hash once, review diff and no pending agent writers. Any later source/manifest edit invalidates affected proofs. |
| F3 inventory | F2; integrator only | `--write-inventory` collection-only succeeds without drift; review exact node inventory. No claim of execution. |
| F4 automation | F3; one exclusive machine, integrator only | One non-quick full 15-check run. `automation.json` says `automation_passed: true`, all 387 automated rows pass, no skips/xfails/deselection/drift. Manifest currently caps `live-gates` at 4 h and `duo-pairs` at 12 h; verify budgets before this machine-day and do not add overlapping live jobs. Failed run is diagnosed at one changed source/oracle/policy cut, then freeze renewed; never relabel it. |
| H0 `human.two-player` | F4, two distinct people | Staged ordinary two-player session notes and zero defects, bound by hash to that automation report; `--complete-human` produces `human-verdict.json` with `release_passed: true`. Defects require a fix, new automation and new session. |
| H1 ship | H0 and owner decision | Review actual artifact/browser bundle, master merge/tag/distribution and a short installed-startup smoke. Keep `gen1/rc` and evidence recoverable; do not infer a deployment from the human verdict. |
