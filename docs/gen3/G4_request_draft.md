# Gen 3 (P4) FRLG RC cutover gate request — G4 evidence assembly

**Status: G4 is not yet signable.** §2 is the current per-item state: items 1, 2 and 4 carry
citable receipts, item 2a is half-closed (Center writes PASS on both titles, the 2F controls are
failing under diagnosis), and 2b / 3 / 5 / 6 / 7 / 8 are open, blocked, or rehearsal-only. Three
scope decisions are open with the owner (§5); the remaining lane work is
`docs/gen3/G4_status_2026-09-23.md`'s estimate, recomputed 2026-09-23 after the three runs that have
completed since it was written (the two Center-as-A receipts and the stronger reconnect): about
**24–30** launches without item 6 and **58–64** with it as written, excluding RNG retries. It rises
if the owner opts into the optional re-runs or changes item 6.

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

1. the conformance suite green (65 tests, §3);
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
| **2a** writes inside a Pokémon Center | **OPEN** (half-closed) | `center_receipt_whiteout_fr_as_a_2026-09-23.txt` (FR-as-A) and `center_receipt_whiteout_lg_as_a_2026-09-23.txt` (LG-as-A) @ `5a8064f3`, cut `fb255a05`: `whiteout_gen3: a=PASS b=PASS`, "the write landed in the Center", `CONTROL_LIVE nurse map=5.4 at=(7,4)`, `CONTROL_REFUSED nurse box_mon clause=field_controls_locked attempted=0 writes=0 bytes=unchanged`, witness match + counters, PYDEC PASS — FR-as-A and LG-as-A both | the **2F controls** (`center_controls_gen3`) are under diagnosis with a fix live-testing now; the Union-Room entry/return row is the only (b) case here - unreachable while `IsWirelessAdapterConnected` is observed false **P** |
| **2b** in-battle faint window | **OPEN** | wild parked positive on both titles @ `059da756`; LG active hold to bench HP0 @ `4ec51ed0` | trainer positives, FR active hold, doubles (both slots, partner menu refusal, B-cancel reopen), the boundary negatives, and the Pokedude/old-man/Safari refusals; `battle_link` is the (b) case: a real link battle cannot be produced here **P** |
| **3** FRLG probe rows | **OPEN** | 16 FR / 14 LG rows PASS, lane `eaa96787`, landed by `059da756` (which also carries the hashed witness-factory fix), receipts `checkpoint_{fr,lg}_clean_frlg_rows_2026-09-23.txt` | `battle_input_trainer` and `battle_faint_prompt` are owed on both titles and are **not** closed by any hardware limit; LG also `script_running` and `battle_commit_state3`; `battle_link` is the (b) case; negative rows must name an expected clause (C3-24) **P** |
| **4** cold-boot admission | **REHEARSED** | `bootcheck_frlg_rehearsal_keys_2026-09-23.txt` @ `3327720c`, lane cut `fb255a05`: **8/8 PASS** (FR and LG × town/battle × a/b) with the PID:OTID key oracle, counters advancing, 14/14 sectors | re-take on the frozen final cut **P** |
| **5** extracted release zip boots FR on the new client | **REHEARSED** | the zip-boot rehearsal and its correction @ `c8f0c804` (which also lands `tools/check_release_zip.py`, the standing hygiene gate: every member's blob equal to its `git show <rev>:<path>`, no dev-only paths, the 23-file FRLG closure present) | rebuild a **pinned** zip from the final cut, run `python tools/check_release_zip.py <zip> --rev <cut>`, boot it, and record the rev beside the artifact **P** |
| **6** Gen 1 / Gen 2 lanes after the `slink.lua` route change | **BLOCKED as written** | Gen 2 route boot DONE @ `cc807cf3` (`gen2_route_boot_crystal_2026-09-23.txt`); the legacy Gen 2 duo and the Gen 1 SFX town gate are **red on master too**, i.e. **baseline-differential**: they predate this branch's route change, so a red there is not evidence the cutover broke a generation — only a *delta against the master baseline* is | decision (a): integrate the Gen 1 fixes from the Gen 2 branch (`44bf25d6` SFX gate, `3941198c` Gen 1 ordering) or accept route-differential evidence. As written the item is 34 invocations **S**/**P** |
| **7** rollback bundle freeze | **OPEN (definition)** | the frozen record exists: `docs/gen3/rollback_bundle.md` @ `2cd9f993` (cut master `7957c24c`, old-client blob shas, the measured companion md5, the rollback procedure and its checklist) | decision (c): does that SHA + manifest count as the freeze, or must a named archive be built and hashed? **S** |
| **8** owner's own Manager run | **OPEN** | — | two BizHawk instances, the FR↔LG pair, launched from the Manager's run page, exercising link, faint propagation, dead zone, box sync and save/reload by hand. The rows above exist so this run is the confirmation, not the first contact **S** |

What the OPEN rows still need, in lane order (one emulator lane at a time, `PLAN.md:23`/`:297`): the 2F
controls and the Union-Room row (2a); the 2b matrix; the five probe rows (3); the final boot-check
(4) and the pinned zip (5); for (2) only the optional frozen-cut re-runs remain, the reconnect
wrong-save having been re-taken at `fb255a05`. Estimates live in `docs/gen3/G4_status_2026-09-23.md`. **S**

---

## 3. MODEL evidence

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

---

## 4. Limits carried forward (not signed by G4)

| Limit | Why it is not a G4 row | Tag |
|---|---|---|
| The seven OPEN signal kinds and the four PARTIAL checklist rows from G3 | unchanged since G3 signed them as limits (`docs/gen3/PLAN.md:318`, the G3 signature row); the FRLG-relevant subset is §2 item 3, the rest stay OPEN | **S** |
| **RR clean artifact** | G3 carried it as deferred and it still has no duo receipt; **LG clean now exists** — fixtures (`0978a5be`, `fc0e45b2`), boot-check 8/8 @ `3327720c` and the FR-as-A and LG-as-A Center receipts @ `5a8064f3` | **S** |
| `explode_gen3` and `rival_swap_gen3` | labelled **NON-QUALIFYING controls** (`2cace0a9`): their witnesses sit at action-start / an unverified RR offset, so they cannot qualify a row | **S** |
| The RR extension evidence | OPEN in the harness (`2cace0a9`); the RR save extension is compared to a live-RAM copy or reported OPEN | **S** |
| The RR cutover, the patch rebuild, `patch/dist/SLink-RR.ups`, `server/patcher.py`'s pin, the companion re-pin | **G5**, not G4 (`docs/gen3/PLAN.md:207`, the P5 row). The C5 stack (`2dc1b750`) is on the tested cut (see §3); only RR native-feature and patch qualification stays at G5 | **S** |
| Archipelago FRLG, RR native text, the peer ghost | removed from this RC by owner ruling (`PLAN.md` §0, `docs/gen3/TODO.md`) | **S** |
| Gen 4/Gen 5 (HGSS/Pt/BW) | out of this release entirely | **S** |

---

## 5. Owner decisions

### Settled (recorded; not reopened here)

1. **Center writes are in scope and need their own PHYSICAL receipt on FR and LG** (owner ruling
   2026-09-23; `5ecfae3b`, Codex REV-center-tasks-1 ACCEPT as SOURCE/MODEL). The receipts at
   `5a8064f3` are the first half of it; the 2F controls are the half that is failing. **S**/**P**
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

### Open — the three scope decisions

| # | Decision | Options | Why it matters |
|---|---|---|---|
| **a** | Item 6: what to integrate, and what coverage / known defects to accept for the Gen 1 and Gen 2 lanes | the owner has all the estimates, probes and retries in front of them. (i) integrate the Gen 2 branch's fixes into this cut and re-run; or (ii) accept route-differential evidence - an agreed baseline (the same suites on master) and an agreed test subset, recording the failures that already exist there | the facts: the Gen 1 SFX town gate is a **stale test expectation**, fixed by `44bf25d6`; `3941198c` fixes a real Gen 1 **command-ordering** defect; **neither fixes the separate legacy Gen 2 battery-boot failure**. Route-differential evidence proves **no regression**, not full Gen 1/Gen 2 correctness. `PLAN.md:20` (`ca53e491`) settles timing only: the shared layers converge **after** G4 **S** |
| **b** | The two rows that cannot be produced here: the real link battle (`battle_link`) and Union-Room **entry/return** | (i) record them as limits naming the observed condition; or (ii) provide fixtures/hardware | entry/return is unreachable while `IsWirelessAdapterConnected` is observed false (`lua/tests/duo/scenario_gen3_center_controls.lua:32`). The 2F cable-menu, cable-link and no-adapter controls are **designed to run without an adapter and stay OPEN on their own** (under diagnosis; a fix is live-testing now). A recorded hardware limit does **not** close the trainer, faint or other probe rows **S** |
| **c** | Item 7: does the SHA + manifest count as the frozen rollback? | (i) yes — `docs/gen3/rollback_bundle.md` @ `2cd9f993` is the freeze; or (ii) no — build and hash a named archive from that record | the record exists and is citable; only the artifact archive is absent **S** |

---

## 6. How to verify this draft

- Every receipt path above exists under `docs/gen3/probes/`; every commit hash is in
  `git log --oneline`: the scenario receipts land at `8deddf23`, `d074bda2`, `4ec51ed0`, `059da756`, `ac1a5490`, `fb255a05`, `5a8064f3`, `60a9ce18`, `3327720c`.
- The per-item status and the open decisions are Codex's reconciliation
  (`docs/gen3/G4_status_2026-09-23.md`) plus the receipts that landed after it (`5a8064f3`,
  `60a9ce18`, `3327720c`); where this draft disagrees it says so rather than quietly restating.
- The scenario names and the FR↔LG pairing come from `tools/e2e_duo.py` itself (`--list` output;
  the pairing is the `"b": ("leafgreen", "leafgreen_party_{target}")` row).
- The review verdicts come from the RC ledger's `gen3-P4*` / `gen3-REV*` rows
  (`C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md`), not from this draft's prose.
