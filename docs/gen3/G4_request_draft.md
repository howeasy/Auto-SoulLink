# Gen 3 (P4) FRLG RC cutover gate request — G4 evidence assembly

**Status: G4 is not yet signable.** §2 is the current per-item state: items 1, 2, 3 and 4 carry
citable receipts, item 2a is **PASS on both titles** (the 1F write and the 2F
controls on FR-as-A and LG-as-A, both archived; LG 2F at clean cut `10e4a702`), and 2b's nine probe rows plus `A1` are
**DONE live on FR+LG**; what remains open or rehearsal-only is 2b's T2/A2 carriers (wired, not yet run),
4, 5, 6, 7 and 8. §3 is the product defect this cut also has to requalify — the stale-`sSaveDialogCB`
and `gLinkCallback` clauses that held every overworld write after a save or a cancelled link — fixed
in C4-SAVE (`5923c4dd` + `0e7f89e7`), with the harness follow-up C4-6t (`10e4a702`), and **proven live on
both titles** by `save_then_write_gen3` (two saves, a keyed write landing on an idle field, PYDEC PASS;
receipts @ `0c2f384a`); the rows §3.2 still marks owed are the remainder. **All five** scope decisions are settled with
the owner (§6 items 10–14): (a)–(d) as recorded, and (e) — the in-battle lag-frame window — as a **limit for the RC with
no clause added** (`docs/gen3/research/battle_lag_frame_census_design_2026-09-23.md` @ `7f004813`: the only commit that
can straddle a frame end while the tuple reads parked is the action-menu commit, which records the action type alone —
`src/battle_controller_player.c:238` — so the switch target, move and item are chosen later under controllers the permit
refuses; a bench faint there cannot become a switch into the fainted mon, and a forced commit there simply wins, which is
Explode Mode's intended outcome; RR's `battle_commit` is already held at `a1bbc686`).

**Remaining lane work, recomputed 2026-09-23 after the 2b probe rows landed.** The 2b advanced rows are no longer a run
cost — the nine probe rows and `A1` are DONE live on both titles at `f58c8dd5` / `c13cf7c7` — so what is left is:
(a) **4 launches** for the T2/A2 duo carriers once 2B-INTEGRATE-DUO registers them; (b) the **final-cut re-takes** the
runbook enumerates (`docs/gen3/G4_final_cut_runbook.md` @ `23b27065`: item 4's eight cold boots, item 5's pinned zip +
boot, §3.2's rows 1/3/6/9 and the 2a pair, plus the optional item-1/2 regression re-runs the receipt audit calls
sensible); and (c) **item 6's route-differential** (34 invocations as written, or the split ruling's cheaper form).
The draft's last figure (**28–38** without item 6, i.e. **62–72** with it as written) minus the **7 launches now spent** —
the five qualification duos at `c13cf7c7` (rows 1/3/6/9 + `A1`) and the two bw-row probes at `f58c8dd5` — leaves **about
21–31 launches without item 6**; with item 6 as written (34) it would be 55–65, but ruling (a) replaces those with the
route-differential above. The status file's own base figure (**22–29** / **56–63**) predates both adjustments. Excluded
either way:
RNG retries, any rewind-crash loss (§5), and D1–D5/N3/U3 (signed limits under (d)). It rises if the owner opts into the
optional re-runs or changes item 6.

Reconciled against `docs/gen3/G4_status_2026-09-23.md` (Codex REV-g4-draft-1 at `cc807cf3`) and
`docs/gen3/probes/RECEIPT_AUDIT_2026-09-23.md` (Codex REV-receipt-audit-1). Receipts live in
`docs/gen3/probes/`; every commit named below is in `git log --oneline`.

Every claim is tagged **S** (source: a file/commit in this repo), **M** (model: a unit-level suite
or an independent review), or **P** (physical: a receipt from a real cartridge in BizHawk).

---

## 1. What G4 signs

From `docs/gen3/PLAN.md:206` (§6 P4 row: "New client + FRLG cutover", vanilla RC) and §14's P4
row, G4 is the gate at which the **owner runs a live FireRed↔LeafGreen duo from the Run Manager**
— link, faint propagation, dead zone, box sync, save/reload — and signs it. **S**

The gate check the owner sees, per the P4 row's gate-check cell `docs/gen3/PLAN.md:305` (`:297` defines "Gate check" = the receipt set the owner sees): **S**

1. the conformance suite green (65 tests, §4);
2. duo receipts that carry `SAVE_WITNESS_SHA256` **and** a counter delta;
3. the FR and LG coverage rows closed;
4. the extracted release zip booting FR on the new client;
5. the rollback bundle frozen (`docs/gen3/PLAN.md` §9 (`:229-231`): the previous release bundle — old client +
   `SLink-RR.ups` — frozen as an artifact, because a route flag alone is not a rollback once saves
   have been mutated). **S** — the frozen record is `docs/gen3/rollback_bundle.md` (`2cd9f993`);
   it pins master `7957c24c`, the old client's blob shas, and the companion md5 **measured from the
   shipped artifact**: `bf8e94a0…` from applying `patch/dist/SLink-RR.ups` (md5 `84082ec3…`) to the
   clean base `8529f3a4…`. `PLAN.md` §9's `8dcffce7…` (`:231`) and `server/patcher.py`'s master pin are both
   stale against that artifact; the measured apply is the number to freeze. **S**

G4 is a cutover gate, not RC approval and not G5 (the RR cutover, whose patch rebuild is its own
card). **S**

---

## 2. Per-item status

Status vocabulary: **DONE** = a citable receipt exists (its cut named); **REHEARSED** = a receipt
exists but must be re-taken on the frozen final cut; **OPEN** = not started or incomplete;
**BLOCKED** = cannot run with current hardware/fixtures.

| Item | Status | Evidence (receipt @ commit; cut) | Still owed |
|---|---|---|---|
| **1** FR↔LG faint on a clean cut | **DONE** | `duo_frlg_faint_cmd_gen3_clean_2026-09-23b.txt` @ `8deddf23`, cut `d199da32`: `faint_cmd_gen3: a=PASS b=PASS` | nothing; caveat: the receipt proves an *injected-event overworld* faint, not a natural battle faint (audit) **P** |
| **2** the seven FRLG scenarios | **DONE at their cuts** | link + boxsync @ `d074bda2` (cut `d199da32`); reconnect + wrong-save @ `60a9ce18` (cut `fb255a05`, `source=fb255a05`); deadzone + whiteout @ `ac1a5490` (cut `059da756`); `linked_faint_active_gen3` @ `4ec51ed0` (cut `eaa96787`) — `a=PASS b=PASS`, with `SAVE_WITNESS_SHA256 match=true` and counter deltas on each saving side (reconnect's A does not save) | nothing owed as a gate row: a final frozen-cut re-run of faint/link/boxsync/reconnect is OPTIONAL regression evidence per `RECEIPT_AUDIT_2026-09-23.md` **P** |
| **2a** writes inside a Pokémon Center | **DONE on both titles** | 1F write — `center_receipt_whiteout_fr_as_a_2026-09-23.txt` (FR-as-A) and `center_receipt_whiteout_lg_as_a_2026-09-23.txt` (LG-as-A) @ `5a8064f3`, cut `fb255a05`: `whiteout_gen3: a=PASS b=PASS`, "the write landed in the Center", `CONTROL_LIVE nurse map=5.4 at=(7,4)`, `CONTROL_REFUSED nurse box_mon clause=field_controls_locked attempted=0 writes=0 bytes=unchanged`, witness match + counters, PYDEC PASS. 2F controls — `center_controls_fr_as_a_2026-09-23.txt` (FR-as-A, port 55634) @ `3fefbee7`, cut `f5d92327`: `center_controls_gen3: a=PASS b=PASS`, each control's keyed probe refused with a named clause then released and settled, `PYDEC: PASS asserted scenario facts`; `center_controls_lg_as_a_2026-09-23.txt` (LG-as-A) @ `0c2f384a`, clean cut `10e4a702`, rewind off: `center_controls_gen3: a=PASS b=PASS`, same three controls, witness match `saves=1 counter=4->5`, PYDEC PASS. `5923c4dd` + `0e7f89e7` are ancestors of both cuts, so both halves are post-fix | nothing for the gate row. The Union-Room entry/return row stays the (b) case, unreachable while `IsWirelessAdapterConnected` is observed false **P** |
| **2b** in-battle faint window | **probe rows DONE live on FR+LG; T2/A2 OPEN pending live runs** (`docs/gen3/research/g4_2b_matrix_plan_2026-09-23.md` @ `082b33a9`) | `checkpoint_{fr,lg}_clean_2b_rows_2026-09-23.txt` @ `f58c8dd5`, lane `fbfae6fa`: **N1, N4, N5, N6, N7** (the `P.press` game-read JOY_NEW edge fix, `fbfae6fa`), **N8** (a real catch, `ball_delta=-1`), **N9, U1, U2** all PASS on both titles; the header records `tracked_clean=False` with the coordinator's note (a lane checkout lost 22 tracked `tests/unit/*.py` files mid-run; restored, and the final cut re-takes on a verified-clean lane). **A1** (the FR active hold) DONE: `linked_faint_active_fr_forced_b261d045_2026-09-23.txt` @ `c13cf7c7` (`b: RESULT: PASS (held while active; HP 0 in battle once switched out)`), the LG half at `4ec51ed0`. **T2** (Rick 102, Lv13 prep per OMP's Monte Carlo) and **A2** are wired by Codex under **2B-INTEGRATE-DUO**, still in flight | T2/A2 live runs (**4** launches; `python tools/e2e_duo.py --game gen3_frlg --scenario trainer_bench_gen3` / `active_end_gen3` are the placeholders, receipt names and PASS lines to be pinned by that card). The D1–D5 doubles rows, N3 the target menu and U3 Safari are **signed limits** under ruling (d) in §6, so no invocation is owed for them **S**/**P** |
| **3** FRLG probe rows | **DONE on both titles** — the four C4-PROBE2 rows, and since `f58c8dd5` the full probe with the nine 2b rows (27 PASS + 4 not-selected SKIP per title at `f58c8dd5`; the earlier `03ab26e7` receipts were 18 PASS + 4 SKIP); `battle_link` stays the (b) limit | `docs/gen3/probes/checkpoint_fr_clean_c4probe2_2026-09-23.txt` and `checkpoint_lg_clean_c4probe2_2026-09-23.txt` @ `03ab26e7`, lane `gen3-lane-clean` @ `b0511ff2`: **22 probe rows per title: 18 PASS and 4 SKIP (not selected for the clean artifact: `pc_menu`, `battle_link`, `native_idle_field`, `native_idle_battle`), 0 FAIL**, ending `RESULT: PASS all checkpoint controls` (FR :62, LG :61). New rows there: `battle_input_trainer` (the Route 22 early rival; a trainer battle parked at the action menu, flags `0xC` = TRAINER/IS_MASTER), `battle_faint_prompt` (Tail Whip until the lead faints, then the forced send-out prompt `ctrl == WaitForMonSelection`), LG `script_running` (`slink_script.State`, the woman at Viridian (20,12)) and LG `battle_commit_state3`. **Full probe (item 3 + 2b together):** `checkpoint_{fr,lg}_clean_2b_rows_2026-09-23.txt` @ `f58c8dd5`, lane `fbfae6fa` — **27 rows per title PASS** (31 `PROBE …` lines each, incl. the same four not-selected SKIPs), ending `RESULT: PASS all checkpoint controls`, header `tracked_clean=False` with the coordinator's note (see the 2b row). Code: `6bc722bd` / `a256450e` / `b0511ff2` / `fbfae6fa` / `f58c8dd5` | nothing owed as a row: the C4-PROBE2 rows stay covered by the full-probe receipts, and REV-PROBE2-SAVEROWS reported — its fixes landed at `b261d045` (rows 1/3/6/9 re-taken there, §3.2) |
| **4** cold-boot admission | **REHEARSED** | `bootcheck_frlg_rehearsal_keys_2026-09-23.txt` @ `3327720c`, lane cut `fb255a05`: **8/8 PASS** (FR and LG × town/battle × a/b) with the PID:OTID key oracle, counters advancing, 14/14 sectors | re-take on the frozen final cut **P** |
| **5** extracted release zip boots FR on the new client | **REHEARSED** | the zip-boot rehearsal and its correction @ `c8f0c804` (which also lands `tools/check_release_zip.py`, the standing hygiene gate: every member's blob equal to its `git show <rev>:<path>`, no dev-only paths, the 23-file FRLG closure present) | rebuild a **pinned** zip from the final cut, run `python tools/check_release_zip.py <zip> --rev <cut>`, boot it, and record the rev beside the artifact **P** |
| **6** Gen 1 / Gen 2 lanes after the `slink.lua` route change | **BLOCKED as written** | Gen 2 route boot DONE @ `cc807cf3` (`gen2_route_boot_crystal_2026-09-23.txt`); the legacy Gen 2 duo and the Gen 1 SFX town gate are **red on master too**, i.e. **baseline-differential**: they predate this branch's route change, so a red there is not evidence the cutover broke a generation — only a *delta against the master baseline* is | decision (a): integrate the Gen 1 fixes from the Gen 2 branch (`44bf25d6` SFX gate, `3941198c` Gen 1 ordering) or accept route-differential evidence. As written the item is 34 invocations **S**/**P** | Feasibility now measured (`docs/gen3/research/item6_integration_feasibility_2026-09-23.md` @ `21234c4f`): `44bf25d6` applies cleanly (3 files, 0 conflicts, test-fixture-only, and its dependency `f6229e77` is already on this branch); `3941198c` **conflicts in `lua/gen1/client.lua`** (the sibling test file applies clean) and is real convergence work, not a port — Gen 3's copy has structurally diverged. Recommendation there: **split decision (a)**. **S**/**M**
| **7** rollback bundle freeze | **OPEN (definition)** | the frozen record exists: `docs/gen3/rollback_bundle.md` @ `2cd9f993` (cut master `7957c24c`, old-client blob shas, the measured companion md5, the rollback procedure and its checklist) | decision (c): does that SHA + manifest count as the freeze, or must a named archive be built and hashed? **S** |
| **8** owner's own Manager run | **OPEN** | — | two BizHawk instances, the FR↔LG pair, launched from the Manager's run page, exercising link, faint propagation, dead zone, box sync and save/reload by hand. The rows above exist so this run is the confirmation, not the first contact **S** |

What the OPEN rows still need, in lane order (one emulator lane at a time, `PLAN.md:23`/`:297`): the
Union-Room row (2a, a recorded limit); the 2b **T2/A2 carrier runs only** — the nine probe rows and `A1`
are DONE live (`f58c8dd5`, `c13cf7c7`) and D1–D5/N3/U3 are signed limits under (d); the final boot-check (4)
and the pinned zip (5); for (2) only the optional frozen-cut re-runs remain, the reconnect wrong-save
having been re-taken at `fb255a05`. **Item 3 is done twice over** (18 PASS + 4 not-selected SKIP per
title at `03ab26e7`, then the full 27-row probe at `f58c8dd5`); its independent review
REV-PROBE2-SAVEROWS reported and its fixes landed at `b261d045`. The checkpoint change carries its own
rows, §3.2 — ten, of which rows 1, 3, 6 and 9 are **DONE live on both titles at `b261d045`**
(`c13cf7c7`; earlier passes at `24d6cf6a` and lane `0feb9383`), row 6 closed as its limit form; the
estimate in the header folds in those runs. Estimates live in
`docs/gen3/G4_status_2026-09-23.md`. **S**

---

## 3. The stale-save / link product defect and its fix (C4-SAVE)

Two clauses in the G3-signed checkpoint predicate tested engine pointers the game never clears, so
each held **every** overworld SLink write for the rest of a session:

- **`save_dialog_cb == 0`.** `sSaveDialogCB` is assigned by every save-dialog step
  (`start_menu.c:608-842`) and never reset, so after the player's first save it rests on
  `SaveDialogCB_ReturnSuccess`. Live LG evidence on an idle field:
  `STALE_SAVE_DIALOG save_dialog_cb=0x0806F9E1:SaveDialogCB_ReturnSuccess(no save dialog task)`,
  with 404 holds logged in that run (`0e7f89e7`'s message). **P**
- **`gLinkCallback == 0`.** `gLinkCallback` survives `CloseLink` after a no-partner Cable Club link
  (`link.c:394/419-426`), so writes stayed held after a cancelled link (live FR `center_controls`
  r9, `5923c4dd`). **P**

What landed: `0e7f89e7` (C4-SAVE part 2) drops the `save_dialog_cb` key from
`lua/gen3/safety.lua`'s required list (**one line**) and moves the pointer into a pack `witnesses`
block the checkpoint never evaluates — read by `gen3_boot_check` (`M.pred` falls back to it) and by
the probe's dialog row; a mid-save world is still refused by the named clauses (the START-menu task
allow-list, `field_controls_locked`, `task50_save_game` + script lock + `CONTEXT_WAITING`), while
the finished-save world is admitted. `5923c4dd` (part 1) makes `link_callback` read `sLinkOpen`
(set only by `InitLink` via `OpenLink`'s cable branch; cleared by `CloseLink` including the error
path) and allows `Task_RunPokemonLeagueLightingEffect` on FR/LG (`field_specials.c:2133-2185`,
palettes only; RR is gated on `InitLink`/`OpenLink`/`CloseLink`/`LinkMain2` staying byte-identical).
Both commits touch `data/games/gen3_{frlg,rr}/write_checkpoint.json`; 10 falsifiers were red on the
old packs. **S**

This is a **change to the G3-signed predicate**, so it is re-qualified rather than assumed.
`docs/gen3/research/checkpoint_predicate_audit_2026-09-23.md` carries the independent audit
(read-only headless Codex; pret pin `c75f3523`, SLink `328e5ab8`), the persistent-task census, and
Codex's adversarial review of the fix at `0e7f89e7` (`160c2508`): **runtime fixes RETAINED, no
unsafe write frame found** in any vanilla save or link path — START save (both overwrite/replace
prompts, cancel, success and error text, the unlock-to-destroy interval), Cable Club/script save,
flash-failure recovery, Hall of Fame, `Task_LinkFullSave` and its minigame callers, post-link-battle
and trade incremental saves, Mystery Gift, chat, e-reader, erase-save — and on link, cable callbacks
run only behind `sLinkOpen`, with wireless relying on the other exclusions
(`gReceivedRemoteLinkPlayers` can clear before RFU teardown completes, so it is not a universal
teardown witness). Two things it does **not** close: the probe's dialog row is rejected as a witness
(after an earlier save it can pass on a different START submenu) and is routed to C4-6t together
with the save helper's second-save detection; and RR is not qualified (`HandleSavingData` and
`RunSaveFailedScreen` differ from FR). **S**/**M**

C4-6t landed at `10e4a702`: the probe's dialog row and the save helper now use one START-menu save
witness (`gen3_boot_check.start_menu_witness`: wait for `Task_StartMenuHandleInput` with the menu
callback on `StartCB_HandleInput`, then require *this* A press to move it onto
`StartCB_Save1`/`StartCB_Save2` under the live task — `start_menu.c:376-392` draws the window before
input is read, which is why the old helper's second-save A was dropped); RR keeps a
pointer-must-move fallback. It also forces BizHawk rewind off in every generated run config (§5).
Falsifiers red on the parent. **S**

### 3.1 Physical evidence so far

| Row | State | Receipt |
|---|---|---|
| **A keyed write LANDS after an in-game save, then a second save (FR-as-A and LG-as-A)** | **PASS on both titles.** FR: `WRITE_LANDED box_mon 263620B6:99DE0D8A map=3.1 at=(24,39)` after the first save, second save witnessed, `SAVE_WITNESS_SHA256 match=true saves=2 counter=4->6`. LG: `WRITE_LANDED box_mon F6B6A64D:1C600D89` at the same spot, `match=true saves=2 counter=3->5`. Both on an idle field with every predicate zero (`field_controls_locked=0x0`, `link_callback=0x0`, `script_status=2`), `PYDEC: PASS asserted scenario facts`, attempt 1 of 1, no emulator fault (rewind off). Supersedes the earlier partial LG run (`save_then_write_lg_as_a_partial_2026-09-23.txt` @ `3fefbee7`, whose second save failed in the harness) | `save_then_write_{fr,lg}_as_a_2026-09-23.txt` @ `0c2f384a`, clean cut `10e4a702`; wire goldens `save_then_write_gen3_{a,b}_gen3_new.jsonl` **P** |
| **FR Center controls (2F): welcome message, cable-link wait, Union Room attendant** | **PASS.** Each control's `CONTROL_LIVE` is source-pinned (`adapter_connected=false` observed) and each keyed probe is `CONTROL_REFUSED` with a named clause, then `CONTROL_RELEASED`/`CONTROL_SETTLED` — the cable-link row on the **new** clause (`link_callback=0x1`, i.e. refused while `sLinkOpen` was set, landed after the cancel), the other two on `field_controls_locked` — and `PYDEC: PASS asserted scenario facts` | `center_controls_fr_as_a_2026-09-23.txt` @ `3fefbee7`, cut `f5d92327` **P** |
| **LG-as-A Center controls (same clauses)** | **PASS.** `center_controls_gen3: a=PASS b=PASS` — the cable menu, the cable link wait and the Union Room attendant each held a keyed probe and each landed once released; `adapter_connected=false` observed; witness `match=true saves=1 counter=4->5`; `PYDEC: PASS asserted scenario facts`; post-fix | `center_controls_lg_as_a_2026-09-23.txt` @ `0c2f384a`, clean cut `10e4a702` **P** |

### 3.2 Physical rows still owed for this change

Codex's review lists them; each is marked **runnable** on this machine as the harness stands, or a
**recorded limit** with its reason, so a limit can be signed instead of quietly left open.

| # | Row | Runnable or recorded limit |
|---|---|---|
| 1 | START save: first and repeated saves, both overwrite prompts, cancel, success dismissal | **DONE live on both titles** — first and repeated saves are the §3.1 `saves=2` PASS; the overwrite prompts, cancel and dismissal were implemented as driver steps — **IMPLEMENTED** at `c9e2b695` (`beee4ff`'s design): a `SAVE_DISMISSAL <tag> by=a_press or timeout delay=N` line read from `sSaveDialogDelay` (`scenario_gen3_save_then_write.lua:44-48`) distinguishes the two dismissals; the different-file prompt is a **recorded limit** — `start_menu.c:731` is an OR, so the fixture's one valid save always takes the same-file overwrite prompt and `gDifferentSaveFile` can never be true here — **live: PASS on both titles**, re-taken after the review fixes at `b261d045` (`c13cf7c7`; first pass at lane `0feb9383`, see the results block below) |
| 2 | START save: error/recovery (flash failure) | **recorded limit** — needs a forced flash failure the harness cannot inject; statically covered by the audit ("the task persists") |
| 3 | script / Cable Club save | **runnable** — `center_controls_gen3`'s own save is the Cable Club's (`EventScript_AskSaveGame`); it needs its own witness row — **IMPLEMENTED** at `c9e2b695` as the `cable_save` control (the runner queues its probe at `CONTROL_LIVE`) — **DONE live on both titles** (`24d6cf6a`; re-taken at `b261d045`/`c13cf7c7`): refused `clause=field_controls_locked` at 600 frames, then released and settled |
| 4 | Hall of Fame | **recorded limit** — needs the Elite Four; unreachable from the town fixture |
| 5 | link incremental saves (`Task_LinkFullSave`, post-link-battle, trade) | **recorded limit** — needs a real link battle, i.e. the same hardware limit as decision (b) |
| 6 | cable: open before exchange, null callback while open, established, cancel, disconnect, then resumed writes | **CLOSED as its limit form** (re-taken at `b261d045`, `c13cf7c7`) — cancel → resumed writes is the FR PASS above; *open before exchange* is a **recorded limit** (`link.c:373` then `:394`, no frame boundary) and the *null callback while open* window is **logged its limit form live** (`24d6cf6a`, re-taken at `b261d045`) (`CABLE_CALLBACK_NULL limit=no-cable-partner`, `scenario_gen3_center_controls.lua:188`), because the callbacks are cleared only after a partner connects (`link.c:746-757`; the linkup task returns while `playerCount < 2`, `cable_club.c:208-214`) |
| 7 | wireless background / exchange / teardown | **recorded limit** — no adapter: both Center receipts observe `adapter_connected=false` (`IsWirelessAdapterConnected`'s VAR_RESULT) |
| 8 | League rooms: admission, plus refusal in scripts, save and battle | **recorded limit on hardware, static proof in the audit** — `Task_RunPokemonLeagueLightingEffect` persists in the Elite Four rooms (PROVEN on FR/LG, inferred for RR); the rooms are unreachable from the town fixture |
| 9 | a previously-saved fixture with the START cursor on another submenu, where the dialog witness must stay false | **DONE live on both titles** (re-taken at `b261d045`/`c13cf7c7`; first pass at lane `0feb9383`) — the C4-6t witness (`10e4a702`) has unit falsifiers for exactly this — **IMPLEMENTED** at `c9e2b695`: the row-9 refusal line forbids `save_dialog_cb`, and the driver gained seven `start_menu` statics in SYMS plus a read-only `ctx.peek` — **live: PASS on both titles** at `b261d045`/`c13cf7c7` (first pass at lane `0feb9383`) |
| 10 | positive recovery writes with readback | **DONE** — §3.1's `save_then_write_gen3` on both titles (keyed write landed, PYDEC PASS) |

The four rows above are implemented by **`c9e2b695`** (design `beee4ff`,
`docs/gen3/research/c4_save_rows_design_2026-09-23.md`), with **14 falsifiers red on its parent**
(the commit's own count; the diff adds 12 new test functions, some parametrized). **The live runs are
IN FLIGHT** (`save_then_write_gen3` and `center_controls_gen3`, FR-as-A and LG-as-A, lane `03ab26e7`):

**Live results (lane `03ab26e7`, clean):**

- **Rows 1, 3, 6 and 9 — re-taken on both titles at `b261d045` (`c13cf7c7`).**
  `save_then_write_{fr,lg}_as_a_b261d045_2026-09-23.txt` and `center_controls_{fr,lg}_as_a_b261d045_2026-09-23.txt`:
  `a=PASS b=PASS`, PYDEC PASS, witness `match=true` on both titles — the same four rows after
  REV-PROBE2-SAVEROWS's fixes (`b261d045`: row 6 judged field by field, a flash-counter guard, chain lows).
  Row 6 stays closed as its **limit form** (`CABLE_CALLBACK_NULL limit=no-cable-partner`: no partner ever
  connects, so the null-callback window cannot be produced here). **P**
- **Rows 3 + 6 — DONE.** `center_controls_gen3` **PASS on FR-as-A and LG-as-A** @ `24d6cf6a`, receipts
  `docs/gen3/probes/center_controls_{fr,lg}_as_a_c4saverows_2026-09-23.txt` (`RESULT: PASS (the cable menu,
  the Cable Club save prompt, the cable link wait and the Union Room attendant each held a keyed probe; each
  landed once released)` on both titles). Row 3: `CONTROL_REFUSED cable_save … clause=field_controls_locked
  held_frames=600 attempted=0 writes=0 bytes=unchanged` (`:29`) — the save prompt refuses on the lock, not on
  a save-dialog clause. Row 6 logged its **limit form**, as predicted: `CABLE_CALLBACK_NULL
  limit=no-cable-partner open_frames=601 null_frames=0 callback=0x0800A721:LinkCB_RequestPlayerDataExchange`
  (`:33`) — no window exists because no partner ever connects.
- **Rows 1 + 9 — PASS on both titles.** `save_then_write_{fr,lg}_as_a_c4saverows_2026-09-23.txt`, clean lane
  `0feb9383` (`source=0feb9383`), `save_then_write_gen3: a=PASS b=PASS`, `PYDEC: PASS asserted scenario facts`,
  witness `match=true`. Markers: `SAVE_DISMISSAL by=a_press` for both saves, `DIALOG_WITNESS_FALSE` off SAVE,
  the probe refused at the overwrite prompt and the redrawn menu (600 frames, `attempted=0`), then
  `SAVE_CANCEL_WRITE_FRAME … field_free=true start_menu_task=false` (FR frame 5686, LG 5536). The first run at
  `03ab26e7` failed PYDEC only on an oracle ordering bug — the client applies the write on the first free frame,
  inside that frame's pump, before the scenario could log `SAVE_CANCEL_FIELD_FREE` — fixed at `0feb9383` by
  ordering the landing on the write's own frame (falsifier red on `c9e2b695`). **P**


---

## 4. MODEL evidence

| Area | Evidence | Tag |
|---|---|---|
| Unit suites | `python -m pytest tests/unit -q -p no:randomly --deselect tests/unit/test_gen1_trade_patch.py::test_defs_match_committed_red_and_blue_symbols_and_pret_tables` → **5671 passed, 300 skipped, 1 deselected, 0 failed** at the `3327720c` tree (measured with the concurrent workers' uncommitted edits in place). The deselected test needs `.cache/pret/pokered` and is environment-only in a worktree, which is why it is deselected rather than reported as a failure | **M** |
| Gen 3 suites | the Gen 3 gate set (client, native, entry, safety, writes ownership, profile, checkpoint, fixtures, patch sources) is green at `3327720c`; `python tools/lua_syntax_check.py` → 235 Lua files parse; `ruff` clean on every touched file | **M** |
| Conformance | `tests/unit/test_protocol_conformance.py` → **65 passed** over the `gen3_new` goldens, with the doc-sync meta-tests that keep `docs/protocol.md` §9 and `conformance_map.py` in step; the citation-drift rules (three of them now) run in `tests/unit/test_protocol_citations.py` with sha-pinned falsifiers | **M** |
| Write ownership | `tests/unit/test_gen3_write_ownership.py` + the static leak test and the intercepted-sink run required by `docs/gen3/PLAN.md:171` ("write ownership is not proven by `writes.log` alone") | **M** |
| Duo harness | `tests/unit/test_e2e_duo_*.py` (386 tests across the eleven files) incl. the strictness rounds `50d580c9` / `32e0e469` / `2cace0a9`, and the C4-6n provenance work (`fb255a05`: full markers, rename-safe dirty check) | **M** |
| Release-zip hygiene | `tools/check_release_zip.py` @ `c8f0c804`: blob equality per member, no dev-only paths, the FRLG closure present | **M** |
| Independent reviews (Codex, "Review Gen 3 Part 2") | ACCEPT: `writes.lua`, `deferred.lua`, `identity.lua`, the Entry binding, `native.lua`, `core/session.lua` (REV6); `client.lua` quiet-timer; the trade lifecycle at `78908fe8` (REV7, with the receipt caveat since closed by C5-7's per-job dispatch receipt); the duo harness REV4 ACCEPT at `2cace0a9` — narrow: receipt order, RR move-0 PP, duplicate party key, with the RR extension and the explode/rival controls left OPEN/NON-QUALIFYING (`RC_MASTER_GUIDE.md`, row `gen3-P4-C4-6d`). REJECT-then-fixed: `boxes.lua` (Opus review, fixed `d1d4fcec`); the client core (REV2/REV3, fixed `aa062f61`/`690e1c63`/`f3575ff5`) | **M** |
| The C5 stack | **committed** as `2dc1b750` (C5-10/10b/11a/11b/11c/11d: battle identity, patch-enforced window, fail-closed session counter), and its run/client/entry and session-counter changes are part of the tested G4 cut: `2dc1b750` is an ancestor of both `d199da32` and `fb255a05`, so the scenario receipts carry it. Only RR native-feature and patch qualification stays at G5 | **S** |
| **The battle clause set is required, both ways** | `safety.lua`'s `battle()` validates the `gen3-battle-v1` block before it evaluates anything (`a1bbc686`): a missing, duplicated, unknown or malformed clause (compare outside `eq`/`eq_rom`/`eq_symbol`/`nonzero`, or an `eq` without an `expect`) refuses as `{"pack"}`, and the generator raises `SystemExit` on a dropped battle clause instead of writing a weaker block. The RR pack additionally carries `battle.commit_hold`, so `battle_commit` on RR is refused by the named clause `battle_commit_hold` (CFRU's parked controller stays live after `comm = 3`; an L press runs `RemoveBagItem 0x090AA114`) | **S**/**M** |
| **The RR battle permit + the FORCE_MOVE_SLOT driver (G5 items)** | The RR parked-menu permit was UNSAFE (`765beb48`: CFRU keeps the exec bit set while the menu is parked) and is fixed in `97082a62` (parked-menu permit = `exec_flags_input == 1` + a ROM-pool controller pin) with the clause-set work in `a1bbc686`. `FORCE_MOVE_SLOT` is **source-only**: `15a274ec` (0-based comm enum — the menu parks at 1, the move menu at 2 — comm 3 instead of 4, and the `PlayerBufferExecCompleted` hand-back) plus `21df5314` (the second action-menu spelling `0x090A9EA1`, a link-battle guard, a PP-zero refusal at the gate, the `target` staging bound, and ADDRESSES.md stating that the menu's own Disable/Encore/Taunt/Choice checks are overridden by contract). The companion ROM rebuild, `patch/dist/SLink-RR.ups` and the patcher/tool hash re-pins need the owner (`patch/src/ADDRESSES.md`'s rebuild note). RR's flash-writer caller census is `76bc4486` (17 PROVEN / 1 INFERRED / 1 OPEN) | **S**/**M** |
| **The LG frame-end CPU census** | `168fde14` + `b21a3431`: the first LeafGreen overworld frame-end census (`docs/gen3/probes/census_lg_overworld_2026-09-23.txt`) — 1675/1800 frame ends inside `WaitForVBlank`'s LG range `[0x08000890,0x080008BF]` with mode `0x1F`, T=1, the other 125 on the BIOS IRQ vector and refused by the clause on purpose — is now pinned in the pack's `leafgreen` cpu block (`census` + `observed_pc 0x080008AC`) by the same generator path FR uses, with the pack/test/generator equality asserted (`tests/unit/test_gen3_write_checkpoint.py`). The FR and gen3_rr packs are byte-identical after the regeneration | **S**/**P** |
| Receipt `clause=` names before `13b11907` | not comparable on that field: C4-ORDER (`dc855dda`, `13b11907`) made the checkpoint's first-failure reason deterministic (priority = `lua/gen3/safety.lua`'s fixed `predicates` list) and made a pack predicate outside that list refuse the whole check. On a frame where several clauses fail, older receipts may name a different one (the FR receipt's `clause=link_callback` was recorded where `field_controls_locked` also failed). Diff receipts across that boundary on the clause name only with this in mind; the *set* was and is complete | **S** |

---

## 5. Limits carried forward (not signed by G4)

| Limit | Why it is not a G4 row | Tag |
|---|---|---|
| The seven OPEN signal kinds and the four PARTIAL checklist rows from G3 | unchanged since G3 signed them as limits (`docs/gen3/PLAN.md:318`, the G3 signature row); the FRLG-relevant subset is §2 item 3, the rest stay OPEN | **S** |
| **RR clean artifact** | G3 carried it as deferred and it still has no duo receipt; **LG clean now exists** — fixtures (`0978a5be`, `fc0e45b2`), boot-check 8/8 @ `3327720c` and the FR-as-A and LG-as-A Center receipts @ `5a8064f3` | **S** |
| `explode_gen3` and `rival_swap_gen3` | labelled **NON-QUALIFYING controls** (`2cace0a9`): their witnesses sit at action-start / an unverified RR offset, so they cannot qualify a row | **S** |
| The RR extension evidence | OPEN in the harness (`2cace0a9`); the RR save extension is compared to a live-RAM copy or reported OPEN | **S** |
| The RR cutover, the patch rebuild, `patch/dist/SLink-RR.ups`, `server/patcher.py`'s pin, the companion re-pin, **and the three landed RR fixes** — the parked-menu battle permit (`97082a62` + `a1bbc686`), the source-only `FORCE_MOVE_SLOT` (`15a274ec` + `21df5314`, companion rebuild needed) and the flash-writer caller census (`76bc4486`), all in §4 | **G5**, not G4 (`docs/gen3/PLAN.md:207`, the P5 row). The C5 stack (`2dc1b750`) is on the tested cut (see §4); only RR native-feature and patch qualification stays at G5 | **S** |
| Archipelago FRLG, RR native text, the peer ghost | removed from this RC by owner ruling (`PLAN.md` §0, `docs/gen3/TODO.md`) | **S** |
| **The C4-SAVE checkpoint change on RR** | FR/LG only: the audit finds RR's `HandleSavingData` and `RunSaveFailedScreen` differ from FR, and the four gated link bodies being byte-identical is the generator's gate, not a proof. RR re-qualification is G5, with RR's parked-battle tuple (`docs/gen3/research/checkpoint_predicate_audit_2026-09-23.md` finding 2) | **S**/**M** |
| **BizHawk's rewind capture crashes the mGBA lanes** | environment, not product: `MainForm.CaptureRewind` → `ZwinderBuffer.Capture` → `MGBAHawk.SaveStateBinary` → `BizInvokeProxyLibmGA.BizStartGetState` threw `System.AccessViolationException` and killed **both** instances of run 61569 (`patch/build/duo_61569_{a,b}.out`). C4-6t disables it in every generated run config (`Rewind.Enabled = false`; BizHawk's own default is `true`, so a config that omits the key would still rewind). **Any EmuHawk launched with the machine's base `E:/Howard/Bizhawk/config.ini` still rewinds** — the fix is per-copy, not machine-wide, and that is worth telling the owner. Runs lost this way are not in the estimate | **P**/**S** |
| Gen 4/Gen 5 (HGSS/Pt/BW) | out of this release entirely | **S** |

---

## 6. Owner decisions

### Settled (recorded; not reopened here)

1. **Center writes are in scope and need their own PHYSICAL receipt on FR and LG** (owner ruling
   2026-09-23; `5ecfae3b`, Codex REV-center-tasks-1 ACCEPT as SOURCE/MODEL). The receipts at
   `5a8064f3` are the 1F half of it and `3fefbee7` (`center_controls_fr_as_a_2026-09-23.txt`) plus `0c2f384a`
   (`center_controls_lg_as_a_2026-09-23.txt`) are the 2F half — PASS on both titles. **S**/**P**
2. **In-battle faint must work on vanilla, with RR parity** (`PLAN.md:16`) — that is why `linked_faint_active_gen3`
   is a required row (now PASS at `4ec51ed0`) and why 2b's matrix is owed rather than optional. **S**/**P**
3. **The generations converge after G4**: the Gen 1 SFX gate (`44bf25d6`) and the Gen 1 ordering
   fix (`3941198c`) live on the Gen 2 branch and are not this cut's work. What is *open* is only how
   item 6 records that (decision (a) below). **S**
4. **FRLG vanilla is the RC**, RR flips at G5; every P4 card is pack-neutral (`PLAN.md:17`, the RR-under-the-new-standard row). **S**
5. **The companion artifact is what the shipped UPS produces** (`bf8e94a0…`, §1 item 5) and the
   `codex/rr-foundation` branch is archived rather than merged (`PLAN.md:315`, the G0 row's archive-tag decision). **S**
6. **Peer ghost removed from the RC; RR native text removed/disabled; Archipelago FRLG deferred
   post-RC** (`PLAN.md` §0; `docs/gen3/TODO.md:6-32`). **S**
7. **Two-reviewer precedent at G6** is kept. **S**
8. **Rival swap gets a wire request id and a patch-side consumption-time window check** (`122d003e`,
   `PLAN.md` §0); the additive opcode does not bump the mailbox ABI (C5-8d). G5, not G4. **S**
9. **The LG intro is the same engine as FR's** (owner, 2026-09-23): LG fixtures were built through
   the FireRed scripted path with pret-sym RAM witnesses replacing frame counts (`0978a5be`). **S**

10. **Item 6 is split** (owner, 2026-09-23, decision (a)): take `44bf25d6` (the Gen 1 SFX-gate stale test expectation; applies cleanly, test files only) into this cut; judge the Gen 1 command-ordering case and the legacy Gen 2 failure by route-differential evidence against master's baseline, and leave `3941198c` to the post-G4 convergence card (`docs/gen3/research/item6_integration_feasibility_2026-09-23.md`, `21234c4f`). **S**
11. **The rollback freeze is the SHA + manifest** (owner, 2026-09-23, decision (c)): `docs/gen3/rollback_bundle.md` @ `2cd9f993` is the frozen rollback; no separate archive is built. **S**
12. **Doubles, the target menu and Safari are signed as current-fixture limits** (owner, 2026-09-23, decision (d)): 2b rows D1-D5, N3 and U3 are recorded G4 limits; every other 2b row still runs. **S**

13. **The cartridge's own link features are signed as limits** (owner, 2026-09-23, decision (b)): the real in-game link battle (`battle_link`) and Union Room entry/return are recorded G4 limits. SLink never uses the game's link cable or a wireless adapter — its trades and link events go through the SLink server (`docs/protocol.md` §6) — so these rows only test that SLink stays hands-off if a player uses the cartridge's own Cable Club link battle or Union Room, which cannot be produced here (no cable partner; `IsWirelessAdapterConnected` observed false). The 2F Cable Club controls that do run here stay PASS (`c13cf7c7`). **S**

14. **The in-battle lag-frame window is a signed limit, no clause added** (owner, 2026-09-23, decision (e)): the window is real and observable (a frame end can land between the action-menu choice reaching `gBattleBufferB` and `PlayerBufferExecCompleted`), but it has no harmful outcome on FR/LG. The action-menu commit records only the action *type* (pret `battle_controller_player.c:238`); the switch target, move and item are chosen later under controllers the permit refuses, so a bench faint in the window cannot produce a switch into the fainted mon, and a forced commit there simply wins (Explode Mode's intended result). The RR L-throw exception is already closed by `battle_commit_hold` (`a1bbc686`). Analysis: `docs/gen3/research/battle_lag_frame_census_design_2026-09-23.md` (`9ffa8c6d`, coordinator notes incl. `7f004813`). The owner asked for a small check if one fit; after the trace there is nothing for it to guard. **S**/**M**

All five owner scope decisions (a)–(e) are settled and recorded above.

15. **Mechanism P, active faint in battle** (owner, 2026-09-23, "A"): when a linked partner dies while our linked mon is the active battler on FR/LG singles, the mon faints in battle through the engine's own Perish KO (`docs/gen3/research/active_faint_in_battle_scope_2026-09-23.md`; built `1b3943e3`/`39bcc4f8`/`66595498`). Explode Mode is not changed. RR gets the same behaviour (owner: "RR is meant to have parity"; G5, `docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md`). **S**
16. **P hands off the battle controller on every title** (owner, 2026-09-24): the plan ends by setting `gBattlerControllerFuncs[0] = PlayerBufferExecCompleted`, so no A press is needed on FR, LG or RR (RR scope §3.2, §5.1). **S**
17. **The RR lag-frame lost-ball window is a signed limit** (owner, 2026-09-24): about 1e-4 to 1e-3 per commit, and only when L is newly pressed on that exact frame (RR scope §3.5). This is the same class as ruling 14. The companion opcode (§5.6) is not built. **S**
18. **The DREW edge is accepted** (owner, 2026-09-24): if our last usable mon takes the Perish KO on the same turn that the foe's last mon faints at end of turn, the engine scores a draw and we white out through the normal Center heal and rebuild (active-faint scope §2.1). P is not held on the last mon. **S**

---

## 7. How to verify this draft

- Every receipt path above exists under `docs/gen3/probes/`; every commit hash is in
  `git log --oneline`: the scenario receipts land at `8deddf23`, `d074bda2`, `4ec51ed0`, `059da756`, `ac1a5490`, `fb255a05`, `5a8064f3`, `60a9ce18`, `3327720c`, `3fefbee7` (FR Center controls + the partial LG save-then-write, cut `f5d92327`), `0c2f384a` (save-then-write FR+LG and LG Center controls, clean cut `10e4a702`), `5923c4dd` / `0e7f89e7` / `160c2508` (C4-SAVE and its adversarial review), `10e4a702` (C4-6t) and `b56c3b50` (the persistent-task census); the C4-SAVE-ROWS chain is `beee4ff` (design), `c9e2b695` (implementation, 14 falsifiers red on its parent) and `24d6cf6a` (rows 3+6 live); the item-3 probe chain is `6bc722bd`/`a256450e`/`b0511ff2` with the receipts at `03ab26e7`; C4-ORDER is `dc855dda`+`13b11907`; the 2b plan is `082b33a9` and the item-6 feasibility `21234c4f`.
- The final-cut re-take plan is `docs/gen3/G4_final_cut_runbook.md` @ `23b27065` — one invocation per G4
  item, with the receipt it produces, the PASS line to look for and the approximate wall-clock — and the receipt
  plumbing it depends on is `tools/gen3_bw_hashes.py` + `tools/gen3_probe_receipt.py` @ `587453bf` (the bw-hash
  producer closes runbook §12 item 2, the receipt wrapper item 3), reviewed with fixes at `e8497461`.
- The per-item status and the open decisions are Codex's reconciliation
  (`docs/gen3/G4_status_2026-09-23.md`) plus the receipts that landed after it (`5a8064f3`,
  `60a9ce18`, `3327720c`); where this draft disagrees it says so rather than quietly restating.
- The scenario names and the FR↔LG pairing come from `tools/e2e_duo.py` itself (`--list` output;
  the pairing is the `"b": ("leafgreen", "leafgreen_party_{target}")` row).
- The review verdicts come from the RC ledger's `gen3-P4*` / `gen3-REV*` rows
  (`C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md`), not from this draft's prose. §3's audit,
  census and adversarial review are `docs/gen3/research/checkpoint_predicate_audit_2026-09-23.md`
  (magi `cx-7e8b52f4`, `cx-45b6df45`, `cx-3e10776a`), likewise read in full rather than paraphrased.
