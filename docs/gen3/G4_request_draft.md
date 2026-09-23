# Gen 3 (P4) FRLG RC cutover gate request — G4 evidence assembly

**Ready to request G4 owner review.** The new Gen 3 client has a live FR↔LG duo PASS on the
faint-propagation scenario (`docs/gen3/probes/duo_frlg_faint_cmd_gen3_2026-09-23.txt`, PASS with
both sides' `SAVE_WITNESS_SHA256` matching and counter deltas 4→5 / 3→4) and the FR/FR control on
the same scenario (`duo_fr_faint_cmd_gen3_2026-09-23.txt`). Both are the *first* live runs on the
new client, and the FR↔LG one was taken on a tree that also carried uncommitted C5-10/C5-11a
edits, so it is **not yet citable**: §4 makes the clean re-run the first owed item. What G4 signs
is therefore not signed here — the rest of the FRLG scenario set, the battle/native/sound probe
rows, the release-zip boot, the Gen 1/Gen 2 re-runs after the `slink.lua` route change and the
frozen rollback bundle are all still owed (§4), and the limits of §5 are carried forward.

Every claim below is tagged **S** (source: a file/commit in this repo), **M** (model: a unit-level
suite or an independent review), or **P** (physical: a receipt from a real cartridge in BizHawk).

---

## 1. What G4 signs

From `docs/gen3/PLAN.md:204` (§6 P4 row: "New client + FRLG cutover", vanilla RC) and §14's P4
row, G4 is the gate at which the **owner runs a live FireRed↔LeafGreen duo from the Run Manager**
— link, faint propagation, dead zone, box sync, save/reload — and signs it. **S**

The gate check the owner sees, per `docs/gen3/PLAN.md:224` and §14: **S**

1. the conformance suite green;
2. duo receipts that carry `SAVE_WITNESS_SHA256` **and** a counter delta;
3. the FR and LG coverage rows closed;
4. the extracted release zip booting FR on the new client;
5. the rollback bundle frozen (`docs/gen3/PLAN.md` §9: the previous release bundle — old client +
   `SLink-RR.ups` — frozen as an artifact, because a route flag alone is not a rollback once saves
   have been mutated). **S** — note the §9 text still names the *previous* companion md5
   (`8dcffce7…`), while the shipped UPS has produced `bf8e94a0…` since G0
   (`docs/gen3/PLAN.md:313`); the frozen bundle must be cut from the current pre-G4 artifact, not
   from that stale line. **S**

G4 is a cutover gate, not RC approval and not G5 (the RR cutover, whose patch rebuild is its own
card). **S**

---

## 2. PHYSICAL evidence held

| # | Receipt | What it proves | Tag |
|---|---|---|---|
| 1 | `docs/gen3/probes/duo_fr_faint_cmd_gen3_2026-09-23.txt` — FR/FR `faint_cmd_gen3` PASS, client HEAD `78908fe8` + harness fix `c8020f61`, fixtures `firered_party_town{,_b}.sav` (`03276561`) | A's injected faint becomes a `force_faint` for B through the **overworld checkpoint**; both sides memorialize to box 14 and save; `SAVE_WITNESS_SHA256` site == file on both (a: `9e3a3a74…`, b: `8351c72e…`), counter 4→5, 14/14 sectors, RTC-normalized; PYDEC asserted the scenario facts | **P** |
| 2 | `docs/gen3/probes/duo_frlg_faint_cmd_gen3_2026-09-23.txt` — **FR A ↔ LG B** `faint_cmd_gen3` PASS at `2121e9ef`, LG fixture `0978a5be`; B's client admitted `title=leafgreen` | the same chain across two *different* cartridges: LG's `force_faint` lands on B (key `F6B6A64D:1C600D89`), both memorialize and save (a 4→5, b 3→4), hook dump == flushed battery on both, PYDEC PASS | **P**, with the **dirty-cut caveat**: the receipt's own header says the tree also carried uncommitted C5-10/C5-11a edits, and it must be re-run on a clean cut before G4 cites it (`24c6ba9a` exists precisely to record that) |
| 3 | `tests/fixtures/gen3/wire/faint_cmd_gen3_{a,b}_gen3_new.jsonl` | the wire goldens from a live *new-client* run; the conformance suite passes on them (item 45a's checker is silent until ids appear, which is expected) | **P** |
| 4 | `docs/gen3/probes/duo_frlg_faint_cmd_gen3_2026-09-23.txt` (line `[duo] wire log: …`) vs `duo_fr_faint_cmd_gen3_2026-09-23.txt` (same field) | the FR/FR receipt's wire logs are named `*_old_client.jsonl` although the run was the new client (`[client] [SLink-gen3] gen3_frlg/firered (clean by hash)` in its own log) — a labelling defect in the receipt, not a client mix-up | **P** |

What these two receipts do **not** cover: any scenario other than faint propagation, any battle-
interior hold (`linked_faint_active_gen3`), any LG-side catch/link/deadzone/boxsync/whiteout/
reconnect, any Manager-driven run (both were harness runs, not the Manager's UI), and any release
zip. All of those are §4 items.

---

## 3. MODEL evidence

| Area | Evidence | Tag |
|---|---|---|
| Unit suites | `python -m pytest tests/unit -q -p no:randomly` → **5434 passed, 1 failed, 297 skipped**; the single failure is `tests/unit/test_gen1_trade_patch.py::test_defs_match_committed_red_and_blue_symbols_and_pret_tables`, which needs `.cache/pret/pokered` and is environment-only in a worktree | **M** |
| Gen 3 suites | the Gen 3 gate set (client, native, entry, safety, writes ownership, protocol conformance, profile, checkpoint, fixtures, patch sources) is green; `python tools/lua_syntax_check.py` → 233 Lua files parse; `ruff` clean on every touched file | **M** |
| Conformance | `tests/unit/test_protocol_conformance.py` (53 passed) over the `gen3_new` goldens, with the doc-sync meta-tests that keep `docs/protocol.md` §9 and `conformance_map.py` in step | **M** |
| Write ownership | `tests/unit/test_gen3_write_ownership.py` + the static leak test and the intercepted-sink run required by `docs/gen3/PLAN.md:169` ("write ownership is not proven by `writes.log` alone") | **M** |
| Duo harness | `tests/unit/test_e2e_duo_*.py` (~440 tests) incl. the strictness rounds `50d580c9` / `32e0e469` / `2cace0a9` | **M** |
| Independent reviews (Codex, "Review Gen 3 Part 2") | ACCEPT: `writes.lua`, `deferred.lua`, `identity.lua`, the Entry binding, `native.lua`, `core/session.lua` (REV6); `client.lua` quiet-timer; the trade lifecycle at `78908fe8` (REV7, with the receipt caveat since closed by C5-7's per-job dispatch receipt); the duo harness REV4 ACCEPT at `2cace0a9` — narrow: receipt order, RR move-0 PP, duplicate party key, with the RR extension and the explode/rival controls left OPEN/NON-QUALIFYING (`RC_MASTER_GUIDE.md`, row `gen3-P4-C4-6d`). REJECT-then-fixed: `boxes.lua` (Opus review, fixed `d1d4fcec`); the client core (REV2/REV3, fixed `aa062f61`/`690e1c63`/`f3575ff5`) | **M** |
| Open review at this writing | `gen3-REV2-C5-10-11` is queued ("re-review identity + opcode split") and `gen3-REV-C5-10`'s fixes are folded into the uncommitted C5-11a tree; neither is a G4 input | **S** |

---

## 4. What is still OWED before asking — ordered lane checklist

Everything here runs on the emulator lane, one at a time (`PLAN.md` §14: "one emulator lane").
Commands are the ones the receipts themselves used. **S**

1. **Clean re-run of the FR↔LG faint propagation** (the receipt names a dirty cut):
   `git status` clean at a committed cut, then
   `python tools/e2e_duo.py --game gen3_frlg --scenario faint_cmd_gen3 --wire-log`
   Expected: `faint_cmd_gen3: a=PASS b=PASS`, two `SAVE_WITNESS_SHA256 … match=true` lines with
   counter deltas, `PYDEC: PASS`, `EXIT=0`. Refresh the two `gen3_new` goldens from this run.
2. **The remaining FRLG scenarios**, one invocation each (the set `--scenario all` would run for
   this game, from `python tools/e2e_duo.py --game gen3_frlg --list`):
   `link_gen3`, `deadzone_gen3`, `boxsync_gen3`, `whiteout_gen3`, `reconnect_gen3`
   (plus its fail-closed leg `--wrong-save <second-OT FR flash save>`), and
   `linked_faint_active_gen3` — the **in-battle** faint the owner requires on vanilla with RR
   parity (`docs/gen3_resume.md`, checkpoint 10 rulings). Each needs its own PASS receipt with
   witness hashes and counter deltas; `--wire-log` for the ones whose wire shape is new.
2a. **Writes inside a Pokemon Center (owner ruling 2026-09-23; 5ecfae3b, Codex REV-center-tasks-1 ACCEPT
   as SOURCE/MODEL only).** This widens the G3-signed task allow-list, so it needs its own PHYSICAL
   receipt on FR and LG (RR at G5), kept separate from the G3 signature:
   (1) pin ROM/pack/source hashes and fixture; stand in an identified Center 1F reached naturally; log map,
   coordinates, frame, the FULL active task list, RFU/received-player state, callback/script/fade predicates,
   parked CPU and the pointer snapshot;
   (2) deliver a real queued SLink mutation while the Union Room background set is present, and show the
   overworld arm and the writes landing INSIDE the Center before leaving (whiteout_gen3's rebuild is the
   natural carrier); independently read the keyed party/PC result; a PASS after walking out does not count;
   (3) save normally: fresh save-hook witness + counter, flushed battery / PYDEC readback of the affected
   slot, no unrelated record changed, no duplicate event or ACK;
   (4) negative controls: move toward an RFU/Union Room/cable session (nurse, 2F attendant, Union Room
   entry and return) and show the newly refused task or predicate by name with ZERO mutation while blocked.
   Record 2F/Union Room locations explicitly. Limit: BizHawk has no wireless adapter, so partner detection
   is proven from source only;
   (5) the existing field/battle/menu/IRQ negative controls must still hold.
   Keep the transitive-audit manifest (the C4-UR closure list and callback roots) as audit evidence.
3. **The FRLG-relevant probe rows** — the battle/native/sound rows that need battle savestates
   (13+ rows, per `docs/gen3_resume.md`'s checkpoint-10 next-actions item 2):
   `python tools/run_gate.py lua/tests/probe_gen3_checkpoint.lua --rom patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba`
   with `SLINK_CHECKPOINT_ROWS=<row>` narrowing per row, on both FR clean and (once it exists)
   the LG clean artifact. Negative rows must name an expected clause (C3-24).
4. **Cold-boot admission** of the FRLG artifacts on the final cut:
   `python tools/gen3_fixtures.py boot-check --rom patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba --saveram-name "Pokemon - FireRed Version (USA).SaveRAM" --fixture tests/fixtures/gen3/firered_party_battle.sav`
   (`--saveram-name` is REQUIRED: without it the battery name is derived from the staged ROM name, which BizHawk
   does not use, and the boot sees an erased battery; rehearsal 2026-09-23)
   (and the same for the LG fixtures, with `--title leafgreen --saveram-name "Pokemon - LeafGreen Version (USA).SaveRAM"`).
   Expected: `BOOT-CHECK PASS … counter=<a>-><b> party=[…]`, 14/14 sectors.
5. **The extracted release zip boots FR on the new client**: build the zip
   (`python tools/make_release.py`), extract it to a clean directory, load the shipped
   `slink.lua`/`slink_gen3.lua` in BizHawk against a FireRed ROM, and confirm the new client
   (not the old one) admits the title, connects and reaches the field. This is the item that
   proves the `lua/slink.lua` route change is correct *in the shipped layout*, not in the repo.
6. **Gen 1 and Gen 2 lanes re-run after the `slink.lua` route change** (the GBA branch moved; the
   GB/GBC branches were touched by the same file): `SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py`,
   `SLINK_E2E=1 pytest tests/e2e/test_duo_gen1.py`, and the Gen 2 pair
   (`tests/live/test_gen2_gates.py`, `tests/e2e/test_duo_gen2.py`). Any red here is a G4 blocker,
   because it would mean the cutover broke a shipped generation.
7. **Freeze the rollback bundle** (`PLAN.md` §9): archive the current pre-G4 release bundle — the
   old Gen 3 client + the shipped `SLink-RR.ups` with its recorded md5 — as a named artifact, with
   the md5 taken from `server/patcher.py` at the frozen cut rather than from the stale §9 line.
8. **The owner's own Manager run** (the thing G4 actually signs): two BizHawk instances, the FR↔LG
   pair, launched from the Manager's run page, exercising link, faint propagation, dead zone, box
   sync and save/reload by hand. The lane items above exist so that this run is the *confirmation*,
   not the first contact.

---

## 5. Limits carried forward (not signed by G4)

| Limit | Why it is not a G4 row | Tag |
|---|---|---|
| The seven OPEN signal kinds and the four PARTIAL checklist rows from G3 | unchanged since G3 signed them as limits (`docs/gen3/PLAN.md:316`); the FRLG-relevant subset is §4 item 3, the rest stay OPEN | **S** |
| **LG clean and RR clean artifacts** | G3 carried them as deferred; LG now has fixtures and one duo receipt (`0978a5be`, `fc0e45b2`), RR clean has none | **S** |
| `explode_gen3` and `rival_swap_gen3` | labelled **NON-QUALIFYING controls** (`2cace0a9`): their witnesses sit at action-start / an unverified RR offset, so they cannot qualify a row | **S** |
| The RR extension evidence | OPEN in the harness (`2cace0a9`); the RR save extension is compared to a live-RAM copy or reported OPEN | **S** |
| The RR cutover, the patch rebuild, `patch/dist/SLink-RR.ups`, `server/patcher.py`'s md5, the companion re-pin | **G5**, not G4 (`docs/gen3/PLAN.md:205`); the uncommitted C5-10/C5-11a work (rival-swap identity + `OP_RIVAL_SWAP`) is explicitly *not* on the faint path and not part of this gate | **S** |
| Archipelago FRLG, RR native text, the peer ghost | removed from this RC by owner ruling (`PLAN.md` §0, `docs/gen3/TODO.md`) | **S** |
| Gen 4/Gen 5 (HGSS/Pt/BW) | out of this release entirely | **S** |

---

## 6. Owner decisions G4 relies on

1. **FRLG vanilla is the RC**, RR comes under the same standard alongside P4 but flips at G5; every
   P4 card is pack-neutral (`docs/gen3/PLAN.md:17`, owner ruling 2026-09-23). **S**
2. **In-battle faint must work on vanilla, with RR parity** — this is why
   `linked_faint_active_gen3` is a required lane item (§4 item 2), not an optional one. **S**
3. **Old RR client addresses are trusted evidence** for RR pack fields, recorded as
   "old-client RR profile (production-tested)", never over a ROM-derived value (`PLAN.md:17`). **S**
4. **The companion artifact is what the shipped UPS produces** (md5 `bf8e94a0…`), and the
   `codex/rr-foundation` branch is archived rather than merged (G0 record, `PLAN.md:313`). **S**
5. **Peer ghost removed from the RC**; **RR native text removed/disabled**; **Archipelago FRLG
   deferred post-RC** (`PLAN.md` §0; `docs/gen3/TODO.md:6-32`). **S**
6. **Two-reviewer precedent at G6** is kept (G0). **S**
7. **Rival swap gets a wire request id and a patch-side consumption-time window check** (owner
   ruling recorded at `122d003e`, `PLAN.md` §0), and the additive opcode does **not** bump the
   mailbox ABI (C5-8d, coordinator-accepted). Neither is a G4 item; both are G5. **S**
8. **The LG intro is the same engine as FR's** (owner, 2026-09-23): LG fixtures were built through
   the FireRed scripted path with pret-sym RAM witnesses replacing frame counts (`0978a5be`). **S**

---

## 7. How to verify this draft

- Every receipt path above exists under `docs/gen3/probes/`; every commit hash is in
  `git log --oneline 10cd25f9..HEAD` (65 commits at the time of writing).
- The scenario names and the FR↔LG pairing come from `tools/e2e_duo.py` itself
  (`--list` output; the pairing is the `"b": ("leafgreen", "leafgreen_party_{target}")` row).
- The review verdicts come from the RC ledger's `gen3-P4*` / `gen3-REV*` rows
  (`C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md`), not from this draft's prose.
- Nothing in §4 is claimed as done; §2's two receipts are the only PHYSICAL rows, and one of them
  is explicitly marked as needing a clean re-run.
