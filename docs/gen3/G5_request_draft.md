# Gen 3 (P5) Radical Red RC cutover gate request — G5 evidence assembly

**Status: G5 is not yet signable.** RR is live on the new client (lane 2): **12 qualification rows
PASS + 1 negative-control row PASS (`rival_swap_gen3`)**, all 13 rows in §2 (a fourteenth, the R5
mega row, is a named SKIP under a signed limit and is not part of that count). Still OPEN before
signing: RR clean coverage rows, the extracted-zip boot on RR, and the frozen-cut RR pass
(`gen3_final_cut.py --title rr`, checkpoint 18, `docs/gen3_resume.md`). The RR opcode gate port is
**26/26 PASS**. The rebuilt companion is pinned. Nothing here authorizes a release: ruling 22
(§8) holds G5 back until G4 is also done, and G4 is itself not yet signable
(`docs/gen3/G4_request_draft.md`).

This draft follows the shape of `docs/gen3/G3_request_draft.md` and
`docs/gen3/G4_request_draft.md`. Every claim is tagged **S** (source: a file/commit in this
repo), **M** (model: a unit suite or independent review), or **P** (physical: a receipt from a
real cartridge in BizHawk). Receipts live in `docs/gen3/probes/`; every commit named below is in
`git log --oneline`. Where this draft could not find a receipt for a claim, it says
`<<EVIDENCE?>>` instead of asserting it.

---

## 1. What G5 signs

From `docs/gen3/PLAN.md` §6 (the P5 row, "P5 RR native surface, RR cutover, deletion") and §14's
P5 row: G5 is the gate at which the **owner plays RR themselves** — the SOULLINK panel, the PC
trade NPC, the ghost walk, Explode, rival swap — and signs the companion build md5
(`docs/gen3/PLAN.md:207`). **S**

The gate-check cell for P5 (`docs/gen3/PLAN.md:306`) lists: nine RR receipts, **RR clean coverage
rows**, the write-sink guard over `native.lua`/`ghost.lua`, the md5 pins, and the **extracted-zip
boot on RR**. **The peer ghost is deferred post-RC** (owner ruling, `docs/gen3_resume.md` checkpoint
6; `docs/gen3/PLAN.md` §0/§10), so the ghost-walk row and `ghost.lua`'s write-sink guard are out of
scope for this cut — the gate-check cell predates that ruling. RR native text is likewise removed
from the RC (`docs/gen3/G4_request_draft.md` §6 ruling 6). What is unaffected by either deferral —
and this draft found no ruling dropping them — stays required and **OPEN**, with no receipt in
this tree:

- **RR clean-artifact coverage rows.** §2's 13 rows all run against the `gen3_rr`/`rr_battle2`
  companion fixture; none of them is a clean (no companion) RR artifact run. `docs/gen3/PLAN.md:207`'s
  P5 evidence cell lists this as its own item, distinct from the companion rows. `<<EVIDENCE?>>` —
  no clean-artifact RR receipt was found under `docs/gen3/probes/`.
- **The extracted release zip boots RR on the new client.** G4's item 5 (`docs/gen3/G4_request_draft.md`
  §2) proves this for FR only; no RR-specific zip-boot receipt was found. `<<EVIDENCE?>>`.

What remains from the gate-check list that *is* evidenced for this release is: the RR duo
scenario set (§2), the opcode gates (§3), the companion md5 (§7), and the write-sink guard over
`native.lua` (carried from G4's write-ownership guard, which is pack-neutral — `docs/gen3/G4_request_draft.md`
§4 "Write ownership"). **S**

G5 is the RR cutover gate. It signs RR *on the new client*, replacing the old Gen 3 client's RR
path. The old client is already deleted (tag `archive/gen3-old-client`, `docs/gen3/G4_request_draft.md`
§6 ruling 24) — RR has no fallback client to route to, which is one reason G5 must close before
any release (§8). **S**

---

## 2. RR duo scenario table

Thirteen rows: the six scenarios FRLG also runs, plus `native_absent_gen3` (RR-only, native trade
staging) and `rival_swap_gen3` (negative control), plus the five P+H/Explode+H rows — the same
mechanism as FR/LG's G4 rows, run here **on RR** for G5 parity (rulings 15-16, 19; not an
RR-exclusive mechanism, just RR's own qualification of it). `linked_faint_active_mega_gen3` (R5)
is a fourteenth row in the harness but is a **named SKIP, signed limit** (ruling 20, §6) — it is
not counted in the 13.

| # | Row | Verdict | Receipt | Cut |
|---|---|---|---|---|
| 1 | `faint_cmd_gen3` | **PASS** | `rr_faint_cmd_gen3_rr_as_a_156a521f.txt` | `156a521f` |
| 2 | `link_gen3` | **PASS** | `rr_link_gen3_rr_as_a_e99c3760.txt` | `e99c3760` |
| 3 | `boxsync_gen3` | **PASS** | `rr_boxsync_gen3_rr_as_a_6131930f.txt` | `6131930f` |
| 4 | `reconnect_gen3` (its `b` leg exercises the wrong-save refusal internally — the scenario has no separate `--wrong-save` CLI flag) | **PASS** | `rr_reconnect_gen3_rr_as_a_e99c3760.txt` | `e99c3760` |
| 5 | `deadzone_gen3` | **PASS** | `rr_deadzone_gen3_rr_as_a_e99c3760.txt` | `e99c3760` |
| 6 | `whiteout_gen3` (Center writes) | **PASS** | `rr_whiteout_gen3_rr_as_a_1321bbdb.txt` | `1321bbdb` |
| 7 | `native_absent_gen3` | **PASS** | `rr_native_absent_gen3_rr_as_a_e99c3760.txt` | `e99c3760` |
| 8 | `rival_swap_gen3` (negative control) | **PASS** | `rr_rival_swap_gen3_rr_as_a_156a521f.txt` | `156a521f` |
| 9 | `linked_faint_active_gen3` (P+H, wild) | **PASS** | `ph_linked_faint_active_gen3_rr_as_a_cc6ec42a.txt` | `cc6ec42a` |
| 10 | `linked_faint_active_clean_gen3` (P+H, clean artifact) | **PASS** | `ph_linked_faint_active_clean_gen3_rr_as_a_cc6ec42a.txt` | `cc6ec42a` |
| 11 | `linked_faint_active_lhammer_gen3` (P+H, L-hammer edge) | **PASS** | `ph_linked_faint_active_lhammer_gen3_rr_as_a_cc6ec42a.txt` | `cc6ec42a` |
| 12 | `linked_faint_active_whiteout_gen3` (P+H, whiteout variant) | **PASS** | `ph_linked_faint_active_whiteout_gen3_rr_as_a_410d9578.txt` (also PASS at `cc6ec42a`) | `410d9578` |
| 13 | `explode_gen3` (Explode+H) | **PASS** | `ph_explode_gen3_rr_as_a_410d9578.txt` (also PASS at `cc6ec42a`) | `410d9578` |
| — | `linked_faint_active_mega_gen3` (R5, mega) | **SKIP — signed limit** (ruling 20) | `ph_linked_faint_active_mega_gen3_rr_as_a_6d6227c6.txt`: `SIGNED LIMIT: owner ruling 20` | `6d6227c6` |

**12 qualification rows PASS + 1 negative-control row PASS (row 8, `rival_swap_gen3`).** Row 6
(`whiteout_gen3`) PASSed at `1321bbdb` after three fixes: an RR-only follower object locking the
field at the Center door (`eb03c21a`, live trace in `rr_whiteout_gen3_rr_as_a_eb03c21a.txt`); the
harness dereferencing RR's literal `pokemon_storage_base` (`9598a4e5`); and the negative control,
because RR's nurse (map 5.4 local 1, script `0x0904C64B`) is a silent quick-heal with no
multichoice, so on RR the hold is on the START menu (`field_controls_locked`, 600 frames,
attempted=0, bytes unchanged; `89caeb0e`/`74589e3f`/`1321bbdb`). OMP review cx-84088887 found the
`eb03c21a` recovery fail-open on transitions; its hardening lands before the frozen pass, and the
RR final pass re-runs the row. **P**

Earlier attempts at rows 9-13 (P+H/Explode+H) failed at cut `6d6227c6` on timeouts and carrier
bugs before the hand-off's dependencies landed — see `ph_linked_faint_active_whiteout_gen3_rr_as_a_{e9193bb2,64ad170a}.txt`
for the diagnosed carrier gaps (RR's `ACTION_CURSOR_ADDR` absence, then a FIGHT-press/action-menu
race) that were fixed before the `cc6ec42a`/`410d9578` PASS runs above. Those earlier files are
kept in the tree as the diagnostic record, not cited as passing evidence. **P**

---

## 3. RR opcode gates

**26/26 PASS**, live, `docs/gen3/probes/rr_gates_live_06724759_2026-09-24.txt` @ commit `0995a82e`
(card G5-GATES-LIVE), companion md5 `6cf77ba4a63634a0fd452be6f206bfc3` (matches §7). 12 further
cases are SKIPPED by design, not failing: 8 ghost-opcode gates (ghost is deferred post-RC, §1) and
3 native-text gates (native text is removed from the RC, §1), plus one empty `GAP` parameter case.
`forcemove` and `explode_route` (the `FORCE_MOVE_SLOT` semantics from `21df5314`) PASS in every run
recorded in that receipt, including a 400%-speed run. This is the reviewed `gen3_gatelib` port
(`2aad8e2a`..`dfd8a96d`, review R2 `docs/gen3/reviews/R2_GATELIB_REVIEW_2026-09-24.md` @
`2ebfdf1f`, ACCEPT-WITH-FIXES, fixed in `dfd8a96d`). **S**/**M**/**P**

---

## 4. P+H and Explode+H hand-off on RR

Rulings 16 and 19 (`docs/gen3/G4_request_draft.md` §6) apply to RR, not just FR/LG:

- **Ruling 16**: P hands off the battle controller on every title —
  `gBattlerControllerFuncs[0] = PlayerBufferExecCompleted` — so no A press is needed on RR either.
- **Ruling 19**: RR's `force_explode` commit plan ends in the **same** `battle.handoff` tail as P,
  so Explode fires immediately again without a press, matching the old RR client's behaviour, and
  protocol item 34 holds on RR. FR/LG Explode is untouched by this ruling.

Both are built in source alongside the FR/LG mechanism (`docs/gen3/PLAN.md`'s in-battle-faint row,
"RR P+H and RR Explode's own hand-off... built in source... but stay G5") and are now live-PASS:
rows 9-13 of §2 are the P+H family, and row 13 is Explode+H specifically
(`ph_explode_gen3_rr_as_a_410d9578.txt`, `RESULT: PASS (Explode+H: engine Explosion KO in battle
with no input (explode))`). The `rr_battle2` two-mon fixture these rows run against was built at
`80913bdf` and confirmed live at `rr_battle2_fixture_build_35de6679_2026-09-24.txt` (`RESULT: PASS
counter 3 -> 4 ... balls_after_catch=9`). **S**/**P**

---

## 5. CPU checkpoint: the IRQ-entry acceptance (ruling 23)

**Ruling 23** (`docs/gen3/G4_request_draft.md` §6 item 23, owner 2026-09-24): RR's CPU checkpoint
clause also accepts the BIOS IRQ entry taken from the System-mode halt, not only the halt itself.
With the client's per-frame exec hooks active, RR's frame ends land at the BIOS interrupt vector
(IRQ mode, R15 = `0x1C`) instead of the System-mode park the signed clause originally expected, so
without this acceptance `hello` never fires on RR. The clause admits IRQ-vector entry **only**
when the banked return address (`R14_irq`) lies inside the BIOS halt loop — an interrupt taken
from game code stays refused.

Live evidence:

- `docs/gen3/probes/rr_cpu_irq_bios_2026-09-24.txt` (card G5-RR-CPU-IRQ, W1): a dedicated probe
  script (no client) that reads `emu.getregisters()` before and after installing an
  `event.on_bus_exec` hook, on real hardware (BizHawk 2.11.1, mGBA core, ROM sha1
  `ea5352f8a3b9...`). With no hook: `R15=0x000001C4`, System mode, ARM (the halt loop), **24/25
  samples** (the 25th, one busy frame, is a different, non-parked PC and is refused as before, not
  evidence against the park). With the hook installed: `R15=0x0000001C`, IRQ mode, ARM,
  `R14_irq=0x000001C4`, **20/20 samples** — the banked return address points straight at the halt
  loop the no-hook run already found, confirming the IRQ-entry state is the same instant seen from
  the other side of the interrupt. **P**
- `docs/gen3/probes/rr_rows_hello_cpu_park_6d6227c6_2026-09-24.txt` @ `7d730a89` is the **diagnostic**
  receipt behind this ruling, not proof the fix works: it shows every RR P+H row FAILing *before*
  ruling 23 (`hello never sent... R15=0000001C CPSR=20000092... hello_ready=false "safety.lua:113:
  CPU outside parked checkpoint"`) — the finding that motivated admitting IRQ-vector entry.
- **The hello-after-admission proof** is
  `docs/gen3/probes/ph_linked_faint_active_whiteout_gen3_rr_as_a_e9193bb2.txt:5-8`, taken after the
  ruling-23 clause landed: `VERDICT: FAIL (instrument): the FIRST live RR hello on the new client
  (both sides, server log below) -- the ruling-23 cpu clause admits`, followed by both sides'
  server `hello` lines (`[b] hello rom=firered_rr area='route_1' party=1`, `[a] hello rom=firered_rr
  area='route_1' party=1`). The row itself still failed downstream (a scripted-driver crash on
  `ACTION_CURSOR_ADDR`, fixed by `64ad170a`, unrelated to the CPU clause), but hello firing on both
  sides is exactly the proof this section needs. **P**

---

## 6. Signed limits

- **R5, mega evolution during the forced faint in a trainer battle, is a signed G5 limit**
  (ruling 20, `docs/gen3/G4_request_draft.md` §6 item 20): no Mega Ring or stone holder is
  reachable by normal inputs early in RR, and the source shows the Perish path reads no mega
  state. The row stays in the tree as a named SKIP (§2, last row) rather than being deleted. **S**/**P**
- **The RR lag-frame lost-ball window is a signed limit** (ruling 17, `docs/gen3/G4_request_draft.md`
  §6 item 17). The probability is an **INFERRED estimate**, not a measured one — "roughly 1e-4 to
  1e-3 per commit, multiplied by the chance L was newly pressed on that exact frame"
  (`docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md:269-278`, §3.5, every row in its
  table tagged `INFERRED`), derived from the window size in `battle_lag_frame_census_design_2026-09-23.md`
  §1, not from a live trial count. This is the same class of limit as ruling 14 (the FR/LG
  action-menu lag-frame window) — real and observable, but with no harmful outcome, so no clause
  was added. The companion opcode that would close it (§5.6 of the RR scope research) is not
  built; the owner chose the limit over the opcode. **S**
- **`rival_swap_gen3` doubles as a negative control**, not just a passing scenario (§2 row 8): its
  `b` side asserts `RESULT: PASS (NEGATIVE CONTROL: identity-less dummy team refused with
  stale_battle_id (not qualified))` — a dummy team without the swap's battle-request id must be
  refused, proving the engine-owned-swap design (`docs/gen3/research/rival_swap_refresh_window.md`)
  actually gates on identity rather than passing anything through. **P**

---

## 7. Companion rebuild hashes

The admitted RR companion, rebuilt from current `patch/src` at commit `998666b6` (owner-approved,
`docs/gen3/G4_request_draft.md` §4):

| | Value |
|---|---|
| md5 | `6cf77ba4a63634a0fd452be6f206bfc3` |
| sha1 | `ea5352f8a3b9073f8ae20870ad12857925d442cd` |

Checked against the repo's own pins, not just the request draft's prose:

- `server/patcher.py:72`: `"patched_md5": "6cf77ba4a63634a0fd452be6f206bfc3"` — **matches**. **S**
- `patch/README.md:27`: "Result md5 should be `6cf77ba4a63634a0fd452be6f206bfc3`" — **matches**. **S**
- `docs/gen3/probes/rr_gates_live_06724759_2026-09-24.txt`: `6cf77ba4a63634a0fd452be6f206bfc3
  *patch/build/slink_RR.gba` (a measured checksum line, not a pasted pin) — **matches**. **P**
- `data/games/gen3_rr/engine_signals.json:576`: `"rom_sha1": "ea5352f8a3b9073f8ae20870ad12857925d442cd"`
  — **matches**, and this is the full-length pin; the probe receipts (e.g.
  `rr_cpu_irq_bios_2026-09-24.txt`, `ph_linked_faint_active_gen3_rr_as_a_6d6227c6.txt:34`) only ever
  print an 8-hex prefix (`ea5352f8a3b9...`, `(rom ea5352f8)`) and are not the source of the full
  value. **S**

Superseded pin (pre-rebuild, do not use): md5 `bf8e94a0…` / sha1 `b7d1e075…`
(`docs/gen3/G4_request_draft.md` §4, "The RR battle permit + the FORCE_MOVE_SLOT driver" row).

---

## 8. Ruling 22 — release gating

**Nothing is released until G4 and G5 are both done** (owner, 2026-09-24, quoted in
`docs/gen3/G4_request_draft.md` §6 ruling 22: "None of this is getting released until it's all
done."). This applies symmetrically to G5: no build ships the rebuilt RR companion (§7) paired
with the old client, because the old client no longer exists to pair it with (§1). The RR cutover
and the old-client deletion (C5-6, ruling 24) land before any release, and this draft is written
on that basis — it is an internal gate request, not a release request. **S**

---

## 9. What is still open before G5 can be signed

1. **`whiteout_gen3` on RR** (§2 row 6) — the Viridian Center exit stall. In live diagnosis now by
   another worker (checkpoint 17). This is the only failing row in the 13.
2. **The final-cut pass has no RR rows to run yet.** `tools/gen3_final_cut.py`'s `ORIENT` map
   (`:101`) is FR/LG only — `{"gen3_frlg": "fr_as_a", "gen3_lgfr": "lg_as_a"}`, no `gen3_rr` entry
   — so every PASS row above was taken on a lane cut by hand, not by the runner, and the runner
   cannot re-take them as written. This is not the same caveat G4's rows carry (those rows the
   runner already knows how to re-take); RR needs its own orientation and row set added to the
   runner first. Card **G5-RUNNER-RR** (an RR extension of `gen3_final_cut.py`) is being dispatched
   now to close this. `tools/gen3_final_cut.py`'s own rehearsal status (zip chain, probe_gates,
   bootcheck 8/8; `release_gate_quick` only 2629/0 at `2b926be1`, FAIL at the other two rehearsal
   cuts) is FR/LG-only evidence and does not speak to RR readiness (`docs/gen3/G4_request_draft.md`
   §1a).
3. **The RR save-extension freshness is proven live, not OPEN.** `docs/gen3/G4_request_draft.md`
   §5's "RR extension evidence... OPEN" describes the harness's *capability* (`check_gen3_witness`
   in `tools/e2e_duo.py:1184-1276`: without a live-RAM copy, `facts["extension"]` stays the string
   `"OPEN"`), not every RR receipt's outcome. When the driver supplies `ext_ram` (the live EWRAM
   copy taken inside the same save hook), the function upgrades that field to `"LIVE_RAM_MATCH"`
   once the saved sectors verify byte-equal to the live copy (`tools/e2e_duo.py:1268-1276`). Every
   RR row in §2 that saves does exactly that: e.g.
   `docs/gen3/probes/rr_faint_cmd_gen3_rr_as_a_156a521f.txt:23-24`,
   `SAVE_WITNESS_SHA256 inst=a ... extension_30_31=LIVE_RAM_MATCH` and the same for `inst=b`. This
   item is **not open** for the rows this draft cites; it stays a documented *capability* of the
   harness (falls back to OPEN when a scenario does not pass `ext_ram`), not a gap in the RR
   evidence above. **P**
4. **`rival_swap_gen3` is a harness control, not a qualification row.** Its scenario entry
   carries `control` (tools/e2e_duo.py, `rival_swap_gen3`): it qualifies the swap-refusal design
   (stale_battle_id), not a standalone "RR does X" claim. `explode_gen3` is NOT a control any
   more: its entry has no `control` key and the RR receipt
   (`rr_explode_gen3_rr_as_a_156a521f.txt`) shows B's `Explode+H: engine Explosion KO` PASS,
   the downstream witness the earlier NON-QUALIFYING label asked for. The block comment above
   the RR-only scenarios in tools/e2e_duo.py still describes the old control status; it is
   stale and is queued for correction after the final cut (editing it now would void carry).

---

## 10. How to verify this draft

- Every receipt path above exists under `docs/gen3/probes/`; every commit hash is in `git log
  --oneline`.
- The RR duo scenario definitions (timeouts, flags, fixture targets) are in `tools/e2e_duo.py`
  (search `"games": ("gen3_rr"` and the `linked_faint_active_*`/`explode_gen3`/`rival_swap_gen3`/
  `native_absent_gen3` entries).
- Rulings 15-24 are recorded, with the owner's own words where quoted, in
  `docs/gen3/G4_request_draft.md` §6 — this draft cross-references them rather than restating their
  text, per instruction.
- The companion hash cross-check (§7) was run against `server/patcher.py` and `patch/README.md`
  directly, not copied from another doc.
