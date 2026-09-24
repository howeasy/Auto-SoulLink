# C5-6 deletion plan: the five old Gen 3 files and their dependents

Static analysis only (research worker W10, card C5-6-PLAN). No code edited. Cut: this worktree's
HEAD at the time of writing (`git log -1` → `6d6227c6`; `tools/gen3_probe_receipt.py` had an
uncommitted, unrelated modification and `tools/gen3_final_cut.py` was untracked — neither touched
here). This document is the ordered, exact deletion plan for `docs/gen3/PLAN.md`'s card **C5-6**
(§14 P5 row, `docs/gen3/PLAN.md:306`), to execute **after** the G4 FR/LG release cut and **at**
G5 (RR cutover), per `docs/gen3/PLAN.md:207,306` and the HOLD noted in the assignment.

## 1. The five old files

Confirmed against `docs/gen3/PLAN.md:207` ("deletion of the five old files") and
`docs/gen3/PLAN.md:306` (C5-6's file list) and by reading each file:

| # | File | Lines | Role today |
|---|---|---|---|
| 1 | `lua/clients/gen3_frlge_client.lua` | 4559 | The OLD production Gen 3 client (dofiled by `lua/slink.lua:156` for any GBA cartridge `game_detect` resolves to `gen3_frlge`: RR until G5, plus Emerald/AP always — see §8). |
| 2 | `lua/memory_gba.lua` | 2168 | FRLG/RR memory-map constants and read/write helpers the old client requires. |
| 3 | `lua/mailbox.lua` | 549 | Client-side companion-patch EWRAM mailbox (ABI v1) the old client and several standalone probes `dofile`. |
| 4 | `lua/peer_ghost_npc.lua` | 206 | Old engine-driven peer-ghost driver, `pcall(require, "peer_ghost_npc")`'d by the old client only. |
| 5 | `lua/game_detect.lua`'s gen3 branch (NOT the whole file) | 2 of 79 lines | `lua/game_detect.lua:18` (`package.loaded["games.gen3_frlge"] = nil`) and `:29` (`"games.gen3_frlge",` in `_module_names`). The file itself stays — it is the live registry/dispatcher for Gen 2/4/5 too. **`docs/gen3/PLAN.md:207,306` literally says "`lua/game_detect.lua` (drop gen3)"**, confirming partial deletion, not file deletion. |

`lua/games/gen3_frlge.lua` (the GEN3 profile/detection module `game_detect` loads, 602 lines,
distinct from `lua/clients/gen3_frlge_client.lua`) is **not** one of the five and is not deleted
by this card — see the risk in §8.

Today (commit `21dfa6e7`, same day as this cut) already archived the OLD-driver *gate* files to
`lua/tests/archive/gen3_old_client/` and rebound the rest onto `gen3_gatelib.lua`/`native.lua`; no
`test_live_*`/`test_mailbox_*` gate file loads any of the five (enforced by
`tests/unit/test_gen3_gatelib.py:384-388`, the `OLD_LOAD` regex at `:371-372`). That leaves
non-gate dependents, generators, release wiring, and docs — this plan's actual scope.

## 2. Runtime (load-bearing) dependents — must be resolved before deletion or the tree fails to load

These `require`/`dofile`/`package.loaded` references execute at BizHawk load time. Deleting the
five files with any of these still in place throws immediately.

| file:line | Kind | References | Action | Replacement |
|---|---|---|---|---|
| `lua/slink.lua:156` | runtime (RR/Emerald/AP route table) | `gen3_frlge = "clients/gen3_frlge_client.lua"` | Remove the row once `game_detect` no longer resolves `gen3_frlge` for RR (§8 decides Emerald/AP) | `lua/gen3/run.lua` via the `gen3_rr` pack admission path already built in P4/P5 |
| `lua/game_detect.lua:18,29` | runtime (registry) | clears `package.loaded["games.gen3_frlge"]`; requires `games.gen3_frlge` | Remove both lines **only if** `lua/games/gen3_frlge.lua` is also retired (§8) | none — RR/vanilla FRLG both route around `game_detect` after P4/P5 |
| `lua/tests/duo/duo_main.lua:63` | runtime (E2E harness) | `dofile(D.wt .. "/lua/mailbox.lua")` | Retire the whole file (archive) once `tools/e2e_duo.py`'s `GAMES["gen3_rr"]` (old) row is dropped | `lua/tests/duo/duo_gen3_main.lua` (already the `gen3_rr_new` driver) |
| `lua/tests/duo/duo_main.lua:102` | runtime | `pcall(dofile, D.wt .. "/lua/clients/gen3_frlge_client.lua")` | same as above | same as above |
| `lua/tests/e2e_battlemsg_inject.lua:37` | runtime (standalone diagnostic, not in any gate manifest) | `pcall(dofile, WT .. "/lua/clients/gen3_frlge_client.lua")` | Delete or archive; superseded by `test_live_battlemsg.lua` (native `OP_SHOW_BATTLE_MESSAGE`, rebound in `21dfa6e7`) | `lua/tests/gen3_gatelib.lua` + `native.lua` |
| `lua/tests/mkstate.lua:28` | runtime (`tools/mkstates.py`'s save-state builder — production tooling, not disposable) | `dofile(WT .. "/lua/mailbox.lua")` for `MB.present()`/`MB.send()` | **Port** the specific primitives mkstate.lua calls (party filler via `OP_CREATE_MON`, presence check) onto `lua/gen3/native.lua`'s client-side queue before deleting `mailbox.lua` | `lua/gen3/native.lua` |
| `lua/tests/mkstate_gen3_rr_fill.lua:30` | runtime | `dofile(WT .. "/lua/mailbox.lua")` | same port as mkstate.lua | `lua/gen3/native.lua` |
| `lua/tests/probe_gen3_checkpoint.lua:681` | runtime (P3 exclusive file, `docs/gen3/PLAN.md:204`) | `dofile(wt .. "/lua/mailbox.lua")` for `present()/busy()` only | Frozen P3 probe, G3 already signed (`docs/gen3/PLAN.md:318`) — archive, do not port | n/a (historical) |
| `lua/tests/probe_gen3_frameend_pc.lua:33` | runtime (P1 exclusive file) | `require("memory_gba")` | Frozen P1 probe, G1 already signed — archive, do not port | n/a (historical) |
| `lua/tests/probe_colorphase.lua:8`, `probe_fit.lua:7`, `probe_infostyle.lua:11`, `probe_uibudget.lua:15`, `probe_uibudget3.lua:12`, `probe_winmap.lua:10`, `sprite_gallery.lua:17`, `visual_pcnpc.lua:9`, `_ref_screens.lua:6` | runtime (manual visual/UI probes, never in an automated gate list) | `dofile(WT .. "/lua/mailbox.lua")` | Archive alongside `duo_main.lua`; these are manually-run BizHawk scripts a human loads, not CI | none needed unless someone wants to keep running them against RR post-cutover, in which case port to `native.lua` |
| `lua/tests/test_1_memory.lua`, `test_2_force_faint.lua`, `test_3_server.lua` | runtime | `require("memory_gba")` | Named explicitly in `docs/gen3/PLAN.md:207` as "deleted or ported — list produced by grep, reviewed" | delete (superseded by `test_live_*` gates) unless a reviewer finds unique coverage |
| `lua/tests/test_battle_facility_flag_discovery.lua`, `test_bgm_audit.lua`, `test_faint_counter_gate.lua`, `test_force_explosion.lua`, `test_pid_freeze_validate.lua`, `test_post_eob_settle_discovery.lua`, `test_se_audit.lua`, `test_sound_playback.lua` | runtime | `require("memory_gba")` | Standalone discovery/diagnostic scripts, never in `tests/live/test_lua_gates.py`'s manifest — archive with a one-line reason each, same pattern as the `gen3_old_client` archive `README.md` | n/a (discoveries already folded into `docs/gen3_engine_sites.md`/`docs/gen3_write_checkpoint.md`) |
| `lua/tests/duo/duo_gb_main.lua`, `duo_gen1_main.lua` | none found | (checked — no reference) | no action | n/a |

`lua/tests/gen3_gatelib.lua:4` and `lua/tests/probe_gen3_hooks.lua:4` name `mailbox.lua`/
`memory_gba.lua` **only in prose comments** ("Replaces the old binding…"), not in a `require`/
`dofile` — confirmed by reading both files; no action needed beyond an optional comment refresh.

## 3. Generator / oracle dependents — read the old files' *source text* as ground truth

These Python files call `.read_text()` on one of the five and will raise `FileNotFoundError` the
instant the file is gone, even though nothing here executes Lua.

| file:line | What it reads | Why | Action |
|---|---|---|---|
| `tools/gen_gen3_profile.py:41-42,566-575` (`MAILBOX_SRC`, `GHOST_SRC`, `native_block()`) | `lua/mailbox.lua` (`MB.NAME = literal` regex, `MAILBOX_RE` at `:39`), `lua/peer_ghost_npc.lua` (`GHOST_RE` table at `:41-46`) | **This is the live generator for `data/games/gen3_rr/profile.json`'s `native` block** — the P2 gate `gen_gen3_profile.py --check` (exit condition "profile diff = 0", `docs/gen3/PLAN.md:224`) fails without these files | **BLOCKING.** Repoint `MAILBOX_SRC`/`GHOST_SRC` and both regex tables at `lua/gen3/native.lua`/`lua/gen3/ghost.lua` (C5-1/C5-2's new files) once their opcode/address constants exist there in a comparably regex-extractable form; re-run `--check` and confirm the same numeric values (only the `_src` citations may change) |
| `tests/unit/test_gen3_profile.py:556-563,597-601,623` | `.read_text()` on `lua/mailbox.lua` and `lua/peer_ghost_npc.lua` directly, and asserts `profile.json`'s `native._src` paths are `"lua/mailbox.lua"`/`"lua/peer_ghost_npc.lua"` | Cross-checks the generator above | **BLOCKING**, update in lockstep with the `gen_gen3_profile.py` repoint — new assertions expect `"lua/gen3/native.lua"`/`"lua/gen3/ghost.lua"` |
| `tests/unit/test_stat_stages.py:155-178` | `lua/memory_gba.lua` source, regex for `M.BATTLE_MON_STAT_STAGES_OFF` | Regression guard: the CFRU-vs-vanilla stat-stage offset (0x19, not 0x18) must never silently revert | **BLOCKING and a real gap**: `lua/gen3/reads.lua` has **no equivalent constant today** (`grep -rn "STAT_STAGE" lua/gen3/*.lua` returns nothing) — stat-stage reading has not been ported to the new client yet. Port the constant + its CFRU-vs-vanilla comment to `lua/gen3/reads.lua` (or wherever the new client reads battle stat stages) *before* deleting `memory_gba.lua`, then re-point this test |
| `tests/unit/test_gen3_lua_vs_codec.py:14` | `lua/memory_gba.lua` source | Confirms a documented row-swap (`lua/games/gen3_frlge.lua:342` / `lua/memory_gba.lua:570-572`) agrees with `server/adapters/gen3_codec.py`; the codec module's own docstring says it is "deliberately independent of `lua/memory_gba.lua`" (`server/adapters/gen3_codec.py:8`) | Purely a provenance cross-check with no runtime coupling — once `memory_gba.lua` is gone the citation is moot | **Delete this test file**, not port it |
| `tests/unit/test_gen3_old_client_outcomes.py` (whole file, `:21`) | `lua/memory_gba.lua` source | Own docstring: "Until 2026-09-23 lua/memory_gba.lua defaulted vanilla FRLG to CAUGHT=6/RAN=3…" — a regression test for an *old-client-only* defect that has already been fixed | Tests behavior that ceases to exist with the file | **Delete this test file** |
| `tests/unit/test_gen3_sfx_arbiter.py:17,94,99,136,138,147` | `lua/clients/gen3_frlge_client.lua` (`CLIENT_SRC`) and `lua/mailbox.lua` (`MAILBOX_SRC`) source, plus lupa-loads `mailbox.lua` live to simulate the real post()/pump() race the arbiter must not lose to | Validates `lua/sfx_arbiter.lua` (shared, `_LUA_ROOT`) against the *real* mailbox race, not a hand-rolled stub | **BLOCKING**: re-point at `lua/gen3/native.lua` and `lua/gen3/client.lua` for the rank constants (26/22/16) and the real post/pump race; `lua/sfx_arbiter.lua` itself only mentions "mailbox" in comments (confirmed — it is a pure module with no `require`), so the arbiter itself is unaffected |
| `tools/gen_gen3_write_checkpoint.py:634,650,798,804` | comment/string citations only (`SOUND_SOURCE_RR = "old client lua/memory_gba.lua:1945-1996…"` baked into generated `docs/gen3_write_checkpoint.md` prose) | Provenance strings only, not `.read_text()` on the old files | Non-blocking; update the citation strings to `lua/gen3/native.lua` once the sound path is fully native, otherwise leave as a historical citation |

## 4. Non-gate `lua/tests/*` diagnostics — per-file disposition (deliverable item 3)

Beyond the "runtime" table in §2 (which already covers every file that actually loads one of the
five), the assignment specifically calls out `lua/tests/README.md:91` and `mkstate.lua:254`.

- `lua/tests/README.md:80-99` is the "Companion-patch regression gates" table. It names
  `test_mailbox_ping.lua`, `test_mailbox_absent.lua`, `test_mailbox_battle.lua` as the beacon/ABI/
  liveness gates. **These three are already bound through `gen3_gatelib.lua`**, not the old
  `mailbox.lua` (confirmed: `test_gen3_gatelib.py:384-388`'s `gate_files()` glob includes
  `test_mailbox_*.lua` and asserts none of them load an old module). No file action needed; the
  README table itself is accurate and does not need a rewrite for this card, only a note once
  `duo_main.lua`'s row disappears (§6).
- `lua/tests/mkstate.lua:254` (`local CB2 = 0x030030F4` comment: "the same one peer_ghost_npc.lua
  gates on") is prose only at that line; the real coupling is `mkstate.lua:28`'s `dofile(...
  /lua/mailbox.lua)`, already in §2's table with its port requirement.

Final disposition table for every non-gate `lua/tests/*.lua` file touching one of the five
(supersedes a flat list — everything here is **archive** unless marked otherwise):

| File | Disposition | Reason |
|---|---|---|
| `test_1_memory.lua`, `test_2_force_faint.lua`, `test_3_server.lua` | delete | explicitly named in PLAN as reviewed-for-deletion; superseded by the `test_live_*` gate suite |
| `test_battle_facility_flag_discovery.lua`, `test_bgm_audit.lua`, `test_se_audit.lua`, `test_sound_discovery.lua`, `test_rr_discovery.lua`, `test_post_eob_settle_discovery.lua` | archive | one-shot discovery scripts; their findings are already captured in `docs/gen3_engine_sites.md`/`docs/gen3_write_checkpoint.md`/`docs/gen3/research/*` |
| `test_faint_counter_gate.lua`, `test_force_explosion.lua`, `test_pid_freeze_validate.lua`, `test_sound_playback.lua`, `test_memorialize_gate.lua` | archive | manual regression scripts for the OLD client's own defects/behavior, run by a human against `gen3_frlge_client.lua` specifically (`test_faint_counter_gate.lua:29`, `test_memorialize_gate.lua:20`); their equivalents already exist as `test_live_forcemove.lua`/`test_force_explosion.lua` (gated) and `test_live_memorialize.lua` |
| `probe_gen3_frameend_pc.lua`, `probe_gen3_checkpoint.lua`, `probe_gen3_hooks.lua` | keep, frozen | P1/P3 exclusive files; gates G1/G3 already signed against them (`docs/gen3/PLAN.md:316,318`) — they are historical evidence, not live tooling; leave in place even though `probe_gen3_checkpoint.lua:681` still `dofile`s `mailbox.lua` for a `present()/busy()` check that will start failing — **acceptable**, since re-running a signed P1/P3 probe after G5 is out of scope and nothing schedules it |
| `probe_colorphase.lua`, `probe_fit.lua`, `probe_infostyle.lua`, `probe_uibudget.lua`, `probe_uibudget3.lua`, `probe_winmap.lua`, `sprite_gallery.lua`, `visual_pcnpc.lua`, `_ref_screens.lua` | archive | manual visual-QA scripts, never in an automated manifest; archive with the `gen3_old_client` README pattern |
| `mkstate.lua`, `mkstate_gen3_rr_fill.lua` | **port, keep live** | production tooling (`tools/mkstates.py`); cannot be archived — see §2 |
| `duo_main.lua`, `e2e_battlemsg_inject.lua` | archive, tied to `tools/e2e_duo.py`'s `GAMES["gen3_rr"]` retirement (§6) | superseded by `duo_gen3_main.lua` |

## 5. Shared-code impact (deliverable item 4)

**`lua/memory_gba.lua` is Gen-3-only at runtime.** Two false leads worth recording so nobody
re-derives them under time pressure:

- `lua/gen1/client.lua:273,561` cite `memory_gba.lua:1963-1964` **in comments only** ("Gen 3's
  default SE_NUZLOCKE_START (memory_gba.lua:1963)") — parity notes for Gen 1's own SFX ids, not a
  `require`. Confirmed no `require("memory_gba")` anywhere in `lua/gen1/*`.
- `lua/memory_nds.lua:1100,1531` (Gen 4/5 NDS reader) cite `memory_gba.lua` in comments only, same
  pattern, no `require`.
- `lua/gen1/entry.lua:48,364` and `lua/gen1/panel.lua:9-151` reference **"mailbox"** repeatedly,
  but this is Gen 1's own, unrelated companion-patch mailbox concept at cartridge address
  `0xDEE2` (`lua/gen1/entry.lua:48`) — a same-named, independently-defined ABI, not
  `lua/mailbox.lua`. A naive grep for the word "mailbox" (rather than `mailbox\.lua`) produces
  false positives here; excluded from every table above.
- `server/adapters/base.py:287`, `server/state.py:1084`, `server/adapters/gen1_codec.py:615`,
  `server/adapters/gen3_frlge.py:350` cite `gen3_frlge_client.lua` **in Python comments only**
  (explaining why a piece of shared server logic exists) — no import, no runtime coupling. These
  are `server/` files under CLAUDE.md's adapter-isolation rule, so any edit to them (even a
  comment) should still go through `slink-adapter-guard` + the standing one-independent-review
  rule for shared `server/` diffs (`docs/gen3/PLAN.md:305`, card C3a's convention) — but nothing
  here is load-bearing, so it can be deferred past G5 without blocking the deletion.

Conclusion: none of the five files (nor `memory_gba.lua` specifically) has a real dependent
outside the Gen 3 lane. The Gen 1/Gen 2/Gen 4/Gen 5 clients are unaffected by deletion; only their
comments will carry stale line-number citations (cosmetic, matches the PLAN §11 risk "docs/
protocol.md citations rot").

## 6. Release manifest and duo-harness wiring

`tools/make_release.py` — `_LUA_ROOT` (currently lines 60-87 in this cut; PLAN's `:71,80-81`
citation is off by a line or two from drift, consistent with the Reconciliation log's own note
that such drift is "cosmetic, not material"):

| Line (this cut) | Entry | Action |
|---|---|---|
| `:71` | `"memory_gba.lua"` | remove |
| `:81` | `"mailbox.lua"` | remove |
| `:82` | `"peer_ghost_npc.lua"` | remove |
| `:68` | `"game_detect.lua"` | **keep** (shared registry, Gen 2/4/5 still use it) |
| `:145` (`_LUA_GAMES`) | `"gen3_frlge.lua"` | **keep, pending §8's ruling** |
| `:131` (`_LUA_CLIENTS`) | `"gen3_frlge_client.lua"` | remove |
| `:117` (`_LUA_GEN3`) | `"native.lua"` | already present (C5-1) |
| (new) | `"ghost.lua"` | add once C5-2 lands |

`tools/e2e_duo.py` — the old RR duo row and the new one currently coexist under different keys
(`GAMES["gen3_rr"]` → `lua/tests/duo/duo_main.lua`, the OLD client, savestate-based, at `:1830-1835`;
`GAMES["gen3_rr_new"]` → `lua/tests/duo/duo_gen3_main.lua`, the NEW client, battery-boot, at
`:1949-1966`). The comment at `:200` ("P5 extends each `games` tuple with `gen3_rr` without a
rename") refers to *scenario* `games` tuples (e.g. `"faint_cmd_gen3": {..., "games": ("gen3_frlg",
"gen3_rr_new")}`), not the `GAMES` dict row identity — those are two different namespaces in the
same file and easy to conflate.

| file:line | Action |
|---|---|
| `tools/e2e_duo.py:1830-1835` (`GAMES["gen3_rr"]`, old) | delete this dict entry |
| `tools/e2e_duo.py:1949-1966` (`GAMES["gen3_rr_new"]`) | rename the key to `"gen3_rr"` (drop `_new`), update its own internal `"game": "gen3_rr_new"` value too if scenario matching keys off it — grep `gen3_rr_new` after the rename to confirm zero survivors |
| `tools/e2e_duo.py:6518` (`ap.add_argument("--game", default="gen3_rr", ...)`) | default already correct post-rename; verify `choices=sorted(GAMES)` still resolves |
| `tools/e2e_duo.py:349,351,354,358` (four scenario `"games": ("gen3_rr",)` tuples — the OLD bare `faint`/`boxsync`-style scenarios) | these belong to the OLD scenario set (`docs/gen3/PLAN.md:200`: "the bare `faint`/`boxsync` belong to the old RR client") — delete alongside the old `GAMES["gen3_rr"]` row, since their driver (`duo_main.lua`) is retired |
| `tests/unit/test_e2e_duo_scenario_selection.py:70,89,118,149,161` | pinned to the OLD scenario set via `scenarios_for("gen3_rr")`; after the rename these assertions must match the NEW (nine-scenario, `gen3_rr_new`→`gen3_rr`) set — rewrite, don't just search-replace the string, since the scenario *contents* differ |

`tests/unit/test_client_acks.py:39`, `tests/unit/test_client_invariants.py:54`: both assert
`len(CLIENTS) >= 4` over a glob of `lua/clients/*_client.lua`. Deleting
`gen3_frlge_client.lua` drops the count to 3 (gen2/gen4/gen5). Lower both to `>= 3`, exactly as
`docs/gen3/PLAN.md:207` calls for. `tests/unit/test_client_upvalue_scope.py` has no such count
assertion (confirmed by grep) — no change needed there beyond it naturally running over one fewer
client.

## 7. Doc references (non-blocking, but rot without a pass)

Living docs that describe the old client as current architecture and need a rewrite pass at G5,
not merely a citation fix — `docs/REFERENCE.md` is the largest, with a full "RR Support"/GBA
memory-map section (`:142,190,214-215,929,1061,1064,1143,1169,1204-1288`) written entirely against
`memory_gba.lua`/`gen3_frlge_client.lua`; `lua/games/README.md:17,23,34,107,113` (directory tree +
the RR rival-swap helper description); `docs/gen3_requirements.md`, `docs/protocol.md`,
`docs/gen3_engine_sites.md`, `docs/gen3_write_checkpoint.md` (all already written to also describe
the new `lua/gen3/*` facts alongside the old citations per P2-P5 work — these need a citation
sweep, not a rewrite); `README.md`, `.github/copilot-instructions.md` (top-level project
descriptions listing the five Gen 3 clients).

Historical/dated snapshots — **do not update**, they are records of what was true at the time:
`docs/gen3/G2_report_2026-09-21.md`, `G3_request_draft.md`, `G4_request_draft.md`,
`docs/gen3/rollback_bundle.md`, `docs/gen3/shadow_ledger/*`, `docs/gen3/probes/*`,
`docs/gen3/reviews/R2_GATELIB_REVIEW_2026-09-24.md`, `docs/gen3/research/*.md` (including the
existing `p4_old_client_inventory.md`, a *behavior* inventory for the P4 FRLG port — a different
document from this one, already complete, out of scope here), `docs/gen3_resume.md`.

`data/games/gen3_rr/README.md:24-37` and `data/games/gen3_rr/profile.json`/`write_checkpoint.json`
(their embedded `_src` provenance strings) are **generated/generator-adjacent** — update in
lockstep with the `tools/gen_gen3_profile.py` repoint in §3, not by hand.

Unrelated false positives from a bare "mailbox" grep, already excluded above: `docs/purergb/*`,
`data/games/gen1_purergb/*`, `data/games/gen1_rby/*`, `patch/gen1/*`, `docs/gen1_*` — all Gen 1's
own mailbox concept.

## 8. Open risk requiring an owner ruling before deletion (not resolvable by grep)

`lua/game_detect.lua`'s gen3 branch and `lua/games/gen3_frlge.lua` are shared by **three**
things today: (a) RR routing through the old client (retired at G5 — fine to drop), (b) Emerald,
and (c) Archipelago FRLG. Per `docs/gen3/PLAN.md:235-236` (§10 "Deferred"), Emerald and AP FRLG
are **deferred, not cancelled** — both still route `game_detect → lua/clients/gen3_frlge_client.lua`
today (there is no other path for them; `lua/slink.lua`'s new-client branch only admits
`gen3_frlg`/`gen3_rr` packs by hash/anchor, `lua/slink.lua:85-89`). If C5-6 deletes
`gen3_frlge_client.lua` and drops the `game_detect` gen3 branch as PLAN row 207 literally says,
Emerald and AP FRLG lose their **only** code path — "deferred" becomes "removed" as a side effect,
which is a bigger claim than §10 makes. This needs an explicit owner ruling at or before G5: either
(1) confirm Emerald/AP are acceptable collateral removals, (2) keep `gen3_frlge_client.lua` alive
*specifically* for those two titles (partial deletion of the five, not full — contradicts "deletion
of the five old files" as written), or (3) build their minimal new-client equivalent first. Nothing
in the PLAN or its reconciliation log (`docs/gen3/PLAN.md:259-269`) addresses this fork explicitly.

## 9. Ordered execution steps

Each step names its exit gate; run `/slink-lua-check` and `pytest tests/unit -q` after every step
regardless (standing gates, not listed per-row for brevity).

1. **Owner ruling on §8** (Emerald/AP fate). Blocks steps 6 and 9.
2. **Port `mkstate.lua`/`mkstate_gen3_rr_fill.lua` off `mailbox.lua`** onto `lua/gen3/native.lua`'s
   client primitives. Gate: `python tools/mkstates.py` rebuilds all fixtures clean (the existing
   savestate-rot recovery path, per project memory) — a real emulator lane run, not a dry check.
3. **Port the stat-stage offset constant** into `lua/gen3/reads.lua` (§3 gap), then re-point
   `tests/unit/test_stat_stages.py:160,174` at it. Gate: `pytest tests/unit/test_stat_stages.py
   tests/unit/test_gen3_reads.py -q`.
4. **Repoint `tools/gen_gen3_profile.py`'s `MAILBOX_SRC`/`GHOST_SRC`/regex tables** at
   `lua/gen3/native.lua`/`lua/gen3/ghost.lua` (requires C5-1/C5-2 landed). Gate:
   `python tools/gen_gen3_profile.py --check` reports 0 diff in *values* (citations may change).
5. **Repoint `tests/unit/test_gen3_profile.py:556-563,597-623`** to match step 4's new `_src`
   paths; **repoint `tests/unit/test_gen3_sfx_arbiter.py`** at `lua/gen3/native.lua`/`client.lua`.
   Gate: `pytest tests/unit/test_gen3_profile.py tests/unit/test_gen3_sfx_arbiter.py -q`.
6. **RR cutover**: `lua/slink.lua:156`'s `gen3_frlge` route row and `lua/game_detect.lua:18,29`'s
   gen3 branch — apply per step 1's ruling. Gate: `python tools/e2e_duo.py --game gen3_rr_new
   --scenario all` (pre-rename) PASS on RR; a live FR↔LG↔RR sanity boot.
7. **Rename `GAMES["gen3_rr_new"]` → `"gen3_rr"`** in `tools/e2e_duo.py`, delete the old
   `GAMES["gen3_rr"]` row and its four legacy scenario tuples (`:349,351,354,358`); rewrite
   `tests/unit/test_e2e_duo_scenario_selection.py`'s `scenarios_for("gen3_rr")` expectations.
   Gate: `pytest tests/unit/test_e2e_duo_scenario_selection.py -q`; `python tools/e2e_duo.py
   --game gen3_rr --scenario all` PASS (now the new client under the old name).
8. **Delete/archive the non-gate `lua/tests/*` files** per §4's table (`git mv` to
   `lua/tests/archive/gen3_old_client/` with a one-line README reason each, matching the pattern
   `21dfa6e7` already set; true one-shot discovery scripts and `duo_main.lua`/
   `e2e_battlemsg_inject.lua` get archived here). Delete `test_gen3_lua_vs_codec.py` and
   `test_gen3_old_client_outcomes.py` outright (§3). Gate: `pytest tests/unit -q` full,
   `tests/live/test_lua_gates.py` gate-file count unchanged.
9. **Delete the five old files** (subject to step 1 for `gen3_frlge.lua`/`game_detect.lua`'s
   branch — `gen3_frlge_client.lua`, `memory_gba.lua`, `mailbox.lua`, `peer_ghost_npc.lua` are
   unconditional). `git rm` them.
10. **`tools/make_release.py`**: remove the four `_LUA_ROOT`/`_LUA_CLIENTS` entries (§6's table),
    add `ghost.lua` to `_LUA_GEN3`. Lower `test_client_acks.py:39` and
    `test_client_invariants.py:54` to `>= 3`. Gate: `pytest tests/unit/test_make_release_manifest.py
    tests/unit/test_client_acks.py tests/unit/test_client_invariants.py
    tests/unit/test_client_upvalue_scope.py -q`.
11. **Grep sweep — the closing falsifier**: `grep -rn "gen3_frlge_client\|memory_gba\|peer_ghost_npc\|mailbox\.lua" --include="*.lua" --include="*.py" .` (excluding
    `lua/tests/archive/gen3_old_client/` and this document itself) returns **zero** hits outside
    doc-only files still carrying historical citations (§7's "historical" list, explicitly allowed
    to remain stale). Any hit in a `.lua` or `.py` file is a blocker.
12. **Doc pass** (§7's "living docs" list): `docs/REFERENCE.md`, `lua/games/README.md`,
    `docs/gen3_requirements.md`, `docs/protocol.md`, `README.md`,
    `.github/copilot-instructions.md`. Not gated by an automated test; owner/reviewer read-through.
13. **Manifest closure + release lane**: `python tools/verify_gen3_release.py` (no `--quick`),
    extracted-zip boot check on FR and RR, full `tools/e2e_duo.py --game gen3_frlg --scenario all`
    and `--game gen3_rr --scenario all`. This is the existing G5/P6 gate machinery
    (`docs/gen3/PLAN.md:226-227`), not new — listed here only as the final confirmation that
    deletion did not regress it.

## 10. Dependent count vs. the plan's "52"

A flat grep for the four filename strings (`gen3_frlge_client`, `memory_gba`, `peer_ghost_npc`,
`mailbox`, word-bounded to `.lua` filenames, excluding `.git`/`.claude`/the `gen3_old_client`
archive) across `*.lua`/`*.py`/`*.md`/`*.json` returns **166 distinct files**, of which 4 are the
old files themselves — **162 files** touch at least one of them by name. That count is a ceiling,
not the PLAN's figure: it includes ~25 historical/dated snapshot docs (§7) that are deliberately
never updated, ~10 files that only match the word "mailbox" as Gen 1's own unrelated concept (§5),
and every doc/comment citation regardless of whether it is load-bearing.

Narrowing to what the PLAN's own count almost certainly meant — **files whose code (not prose)
must change or be removed for the deletion to be correct** — the tables in §2 (runtime, ~28
files), §3 (generators/oracles, 6 files), §6 (release manifest + duo harness, 7 files), and §4's
archive-worthy set already counted inside §2, gives:

- §2 runtime dependents: 24 distinct files (excluding the 5 files themselves and the 2
  already-frozen P1/P3 probes that need no action)
- §3 generator/oracle dependents: 6 distinct files
- §6 release manifest + duo harness: `make_release.py`, `e2e_duo.py`,
  `test_e2e_duo_scenario_selection.py`, `test_client_acks.py`, `test_client_invariants.py` = 5
  distinct files

**Total real (code-level) dependents found here: 35 files.** That is well under the PLAN's "52"
(`docs/gen3/PLAN.md:261`, Codex finding F10's count). Two explanations, not mutually exclusive:
(a) the PLAN's 52 was counted before `21dfa6e7` (today) archived six gate files and rebound the
rest, which removed a large chunk of gate-level dependents in one commit — the PLAN's count predates
that cleanup; (b) a per-*line* or per-*match* count (rather than per-file) would land much higher
than 35 and could plausibly reach 52 depending on what was counted as one "dependent." This
document could not locate the original methodology behind "52" in the reconciliation log beyond
the bare number, so the discrepancy is reported, not resolved.

## Final report

- **Dependent count**: 35 real code-level dependents found (§10), against the PLAN's cited 52 —
  likely explained by today's `21dfa6e7` gate-archival commit predating the PLAN's count, or a
  per-match vs per-file counting difference; not fully reconciled.
- **The five files**: `lua/clients/gen3_frlge_client.lua` (4559 lines), `lua/memory_gba.lua` (2168
  lines), `lua/mailbox.lua` (549 lines), `lua/peer_ghost_npc.lua` (206 lines), and
  `lua/game_detect.lua`'s two-line gen3 branch (`:18,29` — the file itself is shared and stays).
- **Top 5 risks**:
  1. **Emerald/AP orphaning** (§8): deleting `gen3_frlge_client.lua` and dropping `game_detect`'s
     gen3 branch removes the only code path Emerald and Archipelago FRLG have, though PLAN §10
     calls both merely "deferred." No owner ruling exists yet.
  2. **`tools/mkstates.py` production tooling** (§2): `mkstate.lua`/`mkstate_gen3_rr_fill.lua`
     `dofile` `mailbox.lua` directly and are not disposable diagnostics — this is the save-state
     rot recovery path from project memory. Must be ported, not archived, before deletion.
  3. **Stat-stage offset gap** (§3): the CFRU-vs-vanilla 0x19 regression guard
     (`test_stat_stages.py`) has no home in `lua/gen3/reads.lua` yet — the new client may not
     read stat stages at all today, a silent feature gap this deletion would otherwise paper over
     by deleting the test along with the file it reads.
  4. **`profile.json` provenance pipeline** (§3): `tools/gen_gen3_profile.py`'s `native` block
     generator is hard-wired to regex-extract `lua/mailbox.lua`/`lua/peer_ghost_npc.lua`'s literal
     syntax (`MB.NAME = ...`); repointing it at `native.lua`/`ghost.lua` requires those new files
     to carry their constants in a similarly regex-extractable shape, which is not guaranteed by
     C5-1/C5-2's cards as scoped.
  5. **`gen3_rr` naming collision in `tools/e2e_duo.py`** (§6): two `GAMES` dict rows
     (`"gen3_rr"` old, `"gen3_rr_new"` new) and duplicate-looking scenario tuples make it easy to
     edit the wrong one; the rename must be done as one atomic step with the old row's four
     legacy scenario tuples removed in the same commit, or `--game gen3_rr` silently keeps
     resolving to dead code.

Doc SHA: committed as `docs/gen3/research/c5_6_deletion_plan_2026-09-24.md` — see the commit this
report names below.
