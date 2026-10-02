# Gen 4 resume note

## Checkpoint 5 (2026-10-01, end of the owner-timeboxed session)

- **Worktree/branch:** `.claude/worktrees/gen4-support-framework-dfd5e2` on `claude/gen4-support-framework-dfd5e2`. It merged master `ea9c8a07` at `9033a7be`, and nothing has gone to master or been pushed. A master landing needs its own owner yes. `server/adapters/gen4_codec.py` is `server/**`, so ping Gen 2 at landing.
- **Gates:**
  - **G0** is SIGNED: `docs/gen4/reviews/G0_SIGNATURE_2026-10-01.md`.
  - **G1** is PROVISIONALLY SIGNED (owner: "Consider all signatures signed for now"), recorded in `docs/gen4/reviews/G1_SIGNATURE_2026-10-01.md`. Its open rows are carried as work and were not converted to PASS.
  - The session then worked toward **G2**.
- **Owner rulings and standing rules** are all in `docs/gen4/reviews/DECISIONS_2026-10-01.md`:
  - **D7 latency:** the faint lands at the end of the current turn, using the normal faint animation (the cmd-11 + FAINTED-bit seam; on hge, cmd 9).
  - **Performance:** real play must hold 1x continuously. 1x is the native NDS 59.8261 fps plus host jitter. The design uses zero steady-state exec hooks, polls everything, and arms one on-demand hook for the D7 write.
  - **SYNTH setup** is allowed for any row, provided it is disclosed (sidecar hash) and the behaviour under test runs natively.
  - Up to two concurrent functional emulator lanes are allowed. PERF needs a quiet machine.
- **Owner saves** (backed up in `C:/slink/g4/saves/`):

  | Save | Trainer, TID |
  |---|---|
  | HG base | 26310 |
  | SS | DDDD, 25944 |
  | Pt | TTT, 44361 |
  | hge A | OOO, 630 |
  | hge B | JIII, 31846 |

  D3, D4 and D15 are met. The hge ROM copies are `E:/Google Drive/SLink/hg-engine.nds` and `hg-engine-b.nds` (main checkout root, gitignored; both byte-identical to the pin `cb2dc435`, two names only so BizHawk keeps two saves). The pinned build is also at `.cache/gen4/hge/build-fc5175764983/test.nds`.

### PHYSICAL evidence on this branch

| Item | HG | SS | hge | Commit / receipts |
|---|---|---|---|---|
| Row o, in-battle linked faint, one-mon whiteout | PASS | n/a | PASS | `a15b7d74`, `0f75c938`, regression `ae0995dc` |
| Row o, 2-mon replacement path (SYNTH party2) | PASS | n/a | PASS | `de7fc1b2`, hardening `7a234174`; PASS runs `C:/slink/g4/faint2/heartgold_seam_turnend_p2_201327`, `heartgold_seam_ufce_bit_p2_201242`, `_201440`, `heartgold_hge_seam_turnend_p2_201400`, `heartgold_hge_seam_ufce_bit_p2_201513` (`_201013`/`_201104` were OPEN pre-fix attempts) |
| PC deposit, native SAVE, cold reload (row i box leg, G2 fixtures) | PASS | PASS | PASS | `02705ce5`, `01dd2bb3`, hardening `8db9c26f` |
| Dirty-flag offset (HG 0x12004, hge 0x1E004) | measured | measured | measured | RAM: set by deposit, 0 after SAVE and load. The saved battery keeps 1 (`f426a76b`). |
| Wild capture (SYNTH bag) | PASS | PASS | PASS | `6676a13b`, `2a43bfb6`, `76ec3bac`; `C:/slink/g4/catch/catch_203302`, `catch_hge/catch_203823`, `catch_ss/catch_204123` |
| Egg hatch (SYNTH egg1) | PASS | PASS | PASS | `8db9c26f`, `76ec3bac`; `C:/slink/g4/hatch`, `hatch_hge`, `hatch_ss` |
| 1x performance | 0-hook rows met the rule. The 1-hook row had p99 +2.2 ms, accepted under the G1 signature. | n/a | same | These receipts are refused by the hardened validator (`8b5047c2`), so they need a re-run at the current cut. |
| G1 rows a, c–e, g, h | PASS in the `baseline` case of `C:/slink/g4/probe/shakedown-hg-ac0d70aa43` (cut `abf2b72c`); j–l passed only on the earlier cut `C:/slink/g4/probe/heartgold-0cc5b0ee2c21` | | | All of a–n need a re-run at the landing cut, on HG and hge. |

### Committed G2 client modules

These are offline and lupa-tested, with independent OMP reviews reconciled:

| Module | What it does |
|---|---|
| `lua/nds/hook_binding.lua`, `lua/nds/phase_signals.lua` | Default cap of 1 hook, plus on-demand `request()` |
| `lua/gen4/pk4.lua` | Record format, with torn-read and plausibility guards |
| `lua/gen4/reads.lua` | Zero-hook battle chain, double-read |
| `lua/gen4/poll_events.lua` | Wire events by polling; whiteout = the LOSE latch |
| `lua/gen4/safety.lua` | Checkpoint predicate |
| `lua/gen4/entry.lua` | Hash admission plus anchor floor |

Supporting tools and data:
- Packs: `data/games/gen4_*/profile.json`. They hold battle, enums, route_legs, phase_cases, diagnostic sites and admission anchors.
- G2 data: area map, encounters, trainers, acquisition (HGSS + hge) and names. The hge acquisition proves script bytecode and source-level dispatch (`34efe45f`).
- `tools/gen4_synth_save.py`, with kinds party2, bag and egg1. The bag writer refuses an unverified layout: it checks pocket classes (vanilla from pret, hge from the fork) and contiguity (`36f9cec3`, `8637544c`).
- `tools/gen4_routes.py`, with targets battle, pc and hatch and the Pokégear errand, for HG, SS and hge.
- The producer plan, with its G2 checklist: `docs/gen4/G2_PRODUCER_PLAN.md`.

### Next actions

1. Commit or reconcile anything listed under "In flight at stop" below.
2. Re-run gen4-PERF at the current cut:
   - Set `SLINK_GEN4_<TITLE>_SAVE` and the `_STATE` env vars.
   - Run on a quiet machine, so the run is not concurrent with Gen 3 duo runs.
   - Row f stays OPEN until a bundle binds the current HEAD.
3. **G1 rows a–n.** The HG shakedown at `abf2b72c` (`C:/slink/g4/probe/shakedown-hg-ac0d70aa43`) PASSed a, c, d, e, g and h in its `baseline` case. `patched-rom` (j: ROM hash differs) and `rtc-unpinned` (c: unpinned core settings) are targeted control reds (OMP cx-9265e740). `no-buttons` l FAILs with "buttons-only CONTINUE failed". `party-write` FAILs every row because its CONTINUE never reached the overworld: that is the PC-facing boot defect fixed in `c5cca903`, NOT a control. The wrapper does not yet assert expected control reds. g PASSes in every case. and `profile.rtc` has landed (`5e232930`). Two gaps in the C1-1 gate wrapper (`tests/live/test_gen4_probe_gates.py`) block a full pass:
   - It does not bridge the route tool's legs (`gen4_routes:battle_settled` and the PC legs). Without that, rows b, m and n cannot run.
   - FIXED in `c5cca903` (Codex): the SYNTH identity check now accepts the clone in the party OR the boxes. The same commit stops the probe boot pulsing A/Start once the field is live; a PC-facing save used to open the PC.

   - **Boxed persistence retry at `bf58a7c8`** (Codex, `C:/slink/g4/probe/shakedown-hg-ac0d70aa43/boxed-fix/observation.json` plus a per-case `receipt.txt`):
     - **Boot fix PHYSICAL:** HG reached the overworld (`overworld=true`, boot_frame 1024) in all 5 cases: party-write, no-write, box-write, box-no-dirty and cold-reload.
     - **All four native SAVE traces** ran idle → active 2..7 → idle, with `Save_WriteManFinish` hit once; the newer banks decode coherently.
     - **Row i is a measured FAIL of its oracle premise.** A box write persists across SAVE and reload **even without the dirty flag**: original 70, target 71, with dirty 71, without dirty also 71. The party leg behaves as expected (written 19, no-write 20, cold reload 19).
       - Decide next session whether row i should require the dirty flag at all. A native SAVE appears to write the whole PC regardless.
       - No rerun of the unchanged row i, and no threshold relaxation.
     - **Row c, measured discrepancy:** on PC-derived input, the first residency changes land 2 frames after the pinned `HandleLoadOverlay` causes (id0 at f222 vs 220, id38 at f231 vs 229). `census_ok` allows 0..1. Native-stock baseline c PASSes. Decide whether the tolerance should be 2, from this measurement, not by guess.
   - HG only so far. SS and hge are UNRUN under the HG-only lane grant.

   After the route-leg bridge, run a–n on HG and hge at the landing cut.
4. G2 remainder, per `docs/gen4/G2_PRODUCER_PLAN.md`:
   - The client card: `lua/gen4/client.lua` composing lua/core, with key_change / D11 wiring and the gift_area classifier. Build from the OMP design in `docs/gen4/reviews/CLIENT_DESIGN_PROPOSAL_2026-10-01.md` (steps 0–6, each with a falsifier). N2 is SETTLED (OMP cx-de3446b7, coordinator-verified): a client-side completion latch with no `lua/core` change. The armed hook is a one-frame lease that each `battle_write` call renews, and an unrenewed frame disarms it in `pre_pump`. That covers the core paths that hold or retire an entry without asking the driver (`session.lua:182-192`). See the proposal doc's "N2 research" section.
   - The priority order for the rest is in `G2_PRODUCER_PLAN.md` §6a.
   - SYNTH `place` and `species` kinds for statics and gifts.
5. **Standing rule, the receipt-binding class** (flagged by three OMP reviews: cx-97ce7f50, cx-33981fc1, cx-9661fc31):
   - Already DONE: consumers bind at consumption. That covers `committed_cut` in `test_gen4_probe_gates.py` (`a11d87a0`); faint `consume_receipt` with modules and ROM (`52136900`, `b2784f1b`); and route/catch `verify_receipt` by kind, full module set, script and ROM (`abf2b72c`, `1bbc1f88`).
   - Re-run the lanes at the landing HEAD.
   - **Refinement (OMP cx-50ff7abe):** bind the *evidence surface*, not the repository position. Hash the probe's full dependency set, mirroring `committed_modules()` in `tests/live/test_gen4_perf.py`: `lua/json_codec.lua`, `lua/hook_registry.lua`, `lua/gen4/*`, `lua/nds/*` and the packs it reads. Refuse when any of those changed. `source_head` becomes informational, so a docs-only commit no longer stales receipts while a dependency edit does. Apply this to every consumer: `committed_cut` in `test_gen4_probe_gates.py`, `consume_receipt` in `test_gen4_battle_faint.py`, and `verify_receipt` in `tools/gen4_routes.py`.
   - Catch judge branch tests are done (`abf2b72c`).
   - Receipts on disk from before `1bbc1f88` / `b2784f1b` now read STALE by design: they lack the module sets and the kind binding (some, such as `catch_203302`, already carry title and rom_sha1). That covers `C:/slink/g4/route_pc*`, `catch*`, `hatch*` and `faint*`. Treat them as superseded behaviour evidence until the landing re-run.
   - Tidy-up: hoist `from tools import gen4_pins` to module scope in `tools/gen4_routes.py` (two module identities coexist; OMP cx-421a1f56 N1).
6. **Small pack fixes:** DONE in `49ca5e35`: Pt has its own rtc caveat, the ARM9 byte provenance is labelled and the battle evidence cites its owning structs. Follow-up (OMP cx-b6e028df P5): also pin `VSyncThrottle`/`SuperHawkThrottle` false in `PACE_1X`, if receipts are to claim "clock throttled" exactly.
7. Owner items:
   - Ruling 35: the server force-faints a traded-in mon that breaks an enabled clause. Present it at G2.
   - A separate session asked whether Gen 4 will require a ROM companion patch. No Gen 4 patch exists, and requiring one is an owner decision.

### Workers and peers

- **Codex:** the "Gen4 Worker" thread. An off-task status line was seen once, but the OMP review found no off-task content in its work.
- **OMP:** live peers 27808, 39632 and 5212. **Never** use the Gen 3 SLink-RR* peers.
- **Sonnet subagents:** up to 3.
- **Ledger:** the sole guide is `C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md` (the gen4-* cards).

### In flight at stop

(filled at wrap-up)
