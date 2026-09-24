# Gen 3 duo-row emulator time reduction (W24, card EMU-HALVE, 2026-09-24)

Static analysis only. No code changed, no emulator run. Sources: `tools/e2e_duo.py`
(SCENARIOS + orchestrate_*_gen3 runner halves), `lua/tests/duo/scenario_gen3_*.lua`,
`docs/protocol.md`, `server/server.py` debug endpoints, `tests/unit/populated_server.py`,
`tools/inject_full_mocks.py`, `tools/gen3_final_cut.py` (`build_plan`/`duo_budget`), and
receipts under `docs/gen3/probes/`.

## Method note on timing

`tools/e2e_duo.py` does not log per-row elapsed wall time anywhere (`grep -n elapsed
tools/e2e_duo.py` finds nothing; `self._started`/`self._launch_times` are set but never
printed at `"\n========== summary =========="`, `e2e_duo.py:6604`). All minute figures
below are **inferred from receipt file mtimes** under `docs/gen3/probes/` for rows that ran
back-to-back in the same lane on 2026-09-23/24 (only consecutive same-batch deltas are used;
gaps that span other work are discarded). Treat every number as ±50%. The single cheapest
fix in this whole report is instrumentation: **one line** (`elapsed = time.time() -
self._started` printed on the summary line) turns every future receipt into a real
measurement. Do this first; it is free and de-risks every other estimate here.

Observed bands (serial, single lane, one CPU core saturated per live EmuHawk instance —
see `docs/gen3/probes/overhead_fr_*throttled*.txt`, ~90-100% of a core per instance):
- **"light" duo rows** (park + wait + one debug-queued command, no real menu/battle work
  on the side under test): `boxsync_gen3` 3m22s, `reconnect_gen3` 2m43s, its wrong-save
  phase 1m37s (consecutive deltas, `duo_frlg_*_clean_2026-09-23.txt` mtimes 14:23:10 →
  14:26:32 → 14:29:15 → 14:30:52). Call it **2-4 min** per light row.
- **"heavy" duo rows** (a real wild/trainer battle plays out turn-by-turn so the engine's
  own Perish/faint logic fires): `linked_faint_active_gen3` alone took **~22-23 min**
  (14:15:10 batch → 15:37:50); `whiteout_gen3`+`deadzone_gen3` together took 19m36s
  (15:37:50 → 15:57:26), consistent with a much lighter `deadzone_gen3` (RNG catch walk,
  same family as `link_gen3`) plus a heavier multi-phase `whiteout_gen3`.
- RR "battery" rows (`docs/gen3/probes/rr_*_156a521f.txt`, `ph_*_cc6ec42a.txt`) write their
  receipts in one atomic batch at the end of a combined run, so no per-row delta is
  recoverable; batch-to-batch deltas suggest **~7-8 min/row average** including RR's own
  cold-boot cost (RR probes: `checkpoint_rr_companion_*`).
- Single EmuHawk boot to the overworld checkpoint is **5-6s of in-emulator time**
  (`fc_bootcheck_firered_party_town_d0a4bba5.txt`: `RESULT: PASS ... (6s)`), but the wall
  cost of one *instance* in a duo row (process spawn, BizHawk config write, ROM/SaveRAM
  staging, hello handshake, idle-hold until the peer catches up) is a larger, unlogged
  slice of the 2-4 min light-row total — no receipt isolates it, so no number is given here
  beyond "non-trivial"; the instrumentation fix above should capture it directly (log each
  `launch_instance`/hello timestamp, not just the row total).

## 1. Per-scenario classification

Gen 3 scenarios in `SCENARIOS` (games `gen3_frlg`/`gen3_rr`), with the code that drives
each side and whether that side's action is (i) real cartridge gameplay under test, or
(ii) a pure bystander that only needs to `hello` and hold a TCP connection open.

Existing reusable building blocks (no fake client exists inside `tools/e2e_duo.py` today,
but two non-emulator wire speakers already exist and prove the protocol needs nothing
ROM-derived beyond `hello` fields — `docs/protocol.md` §2.1: `rom_content`/`rom_sha1` are
only checked when a `rom_contract.json` is present):
- **`server/server.py` debug HTTP endpoints** (`/api/debug/inject_event`,
  `/api/debug/queue_command`, `/api/debug/set_area_state`, `/api/debug/set_pokeballs`)
  — already how `faint_cmd_gen3`'s A-side "faint" is produced
  (`orchestrate_faint_cmd_gen3`, `e2e_duo.py:5509`: *"nothing touches either cartridge but
  the clients"*). This is the existing fake-event mechanism; no wire client is needed for
  any row whose stimulus is already server-command-only.
- **`tests/unit/populated_server.py` + `tools/inject_full_mocks.py`** — an in-process
  asyncio TCP client that speaks the real `hello`/`tick`/`area_enter`/`capture`/`faint`
  JSON-lines wire format directly to `SLinkServer.handle_client`, no emulator involved.
  This is the template for a scripted fake *peer* usable inside a duo row (today it only
  runs against an in-process server in unit tests, not through `tools/e2e_duo.py`'s
  subprocess-launched server + real port).
- No wire-log replay tool exists that replays a captured `--wire-log` transcript back
  into a live server (the `--wire-log` capture in `tests/unit/test_e2e_duo_wire_log.py` is
  write-only, a golden transcript for diffing, not a player driver). `tools/gen3_shadow_diff.py`
  is a semantic diff over two capture files, also not a replay-as-a-peer tool.

| scenario | A's role | B's role | classification |
|---|---|---|---|
| `faint_cmd_gen3` | Parks on town fixture; its "faint" is injected via `/api/debug/inject_event` — **A's cartridge never does anything except hello + hold + save the resulting memorialize.** (`orchestrate_faint_cmd_gen3`) | Parks; receives `force_faint` propagated by the server, must apply it in-battle-free overworld and memorialize+save (real client persistence under test) | **(b) A → fake peer** for the negative check ("A never received force_faint"); A's own memorialize-save is the *same* Lua code path B already proves — low-risk cut, see risk note |
| `link_gen3` | Real RNG walk + catch on Route 1 (`ball_hunt: True`, `RNG_RETRY_FAMILIES`) | Same, independently, own catch | **(a) both real** — each side is independently the thing under test (the server-pairing check is incidental); this is a **time-sink**, not a fake-peer target — see §3 |
| `deadzone_gen3` | Real walk that dead-zones the area | Real later catch, retired by the dead zone | **(a) both real**, same reasoning as `link_gen3` |
| `reconnect_gen3` | **A's own EmuHawk is killed and relaunched** — the reconnect lifecycle itself is the behavior under test | Only stays connected/online throughout; no native write, no assertion on B beyond liveness (`e2e_duo.py:5724` docstring: *"B online throughout"*) | **(c) B → fake peer**, near-zero risk (B has no observable behavior in this row) |
| `boxsync_gen3` | Hand-deposits/withdraws at the PC (real menu nav) | Applies the **mirrored** `box_mon`/`party_mon` write to its own save (real native write under test) | **(a) both real** — B's mirror-write landing correctly in its own save *is* the point |
| `whiteout_gen3` | Boxes its half by hand, then whites out; A's post-save nurse-script negative control (`CONTROL_LIVE nurse`) | Boxes its half via mirrored write; `assert_whiteout_both_boxed` reads **both** real saves | **(a) both real** — shared box-state assertion needs both cartridges' actual `party_keys` |
| `trainer_bench_gen3` | Walks to a precise sight-line tile (cached-native savestate), parks, receives keyed `force_faint`; the **parked field state itself is under test** | Idles, never saves (`no_save: ("b",)`) | **(c) B → fake peer** |
| `active_end_gen3` | Parks with lead active (`READY_ACTIVE`), receives keyed `force_faint`, engine Perish-KOs it — A is the sole subject | Idles, never saves (comment: *"B idles and never saves"*) | **(c) B → fake peer** |
| `center_controls_gen3` | Walks to two Cable-Club refusal states (`CONTROL_LIVE cable_welcome_message`, `union_room_attendant`), receives keyed `box_mon`/`party_mon` — negative-control probes on A's native menu state | Only holds the link | **(c) B → fake peer** |
| `save_then_write_gen3` | Saves, parks at a specific START-menu cursor state (`WRITE_PROBE_READY`, `CONTROL_LIVE dialog_witness` — the whole point is a stale-`sSaveDialogCB` native regression), receives keyed writes | Only holds the link (`no_save: ("b",)`) | **(c) B → fake peer** |
| `linked_faint_active_gen3` (+ `_whiteout`/`_trainer`/`_clean`/`_lhammer`/`_mega`) | Real wild/trainer battle; the engine's own Perish-commit KO must fire naturally — **this natural engine event is the entire point of the row** | Parks at `READY_ACTIVE` in its own real battle, receives the P+H hand-off, engine-faints with no press — also genuinely under test | **(a) both real, no reduction** — the row exists specifically to prove the natural (not commanded) faint chain on both engines |
| `explode_gen3` (RR) | Real battle, natural faint of its lead | B parks `READY_ACTIVE`, receives `force_explode`, engine must *start* Explosion | **(a) both real, no reduction** |
| `rival_swap_gen3` (RR) | **Idles completely** — never produces any event, never asserted on | B fights a real battle; receives a dummy `replace_rival_team` (blocked-negative-control row) | **(b) A → fake peer**, strongest/lowest-risk case in the whole table — A has zero observable behavior by design |
| `native_absent_gen3` (RR) | Companion build must natively **stage** a queued `apply_trade` | Clean build must natively **refuse** the same op and write nothing | **(a) both real, no reduction** — the row's entire purpose is comparing the two ROMs' native responses |

## 2. G4 final-pass estimate

`tools/gen3_final_cut.py build_plan` (the actual G4 rows, not the RR battery) runs 19 duo
rows, all on `gen3_frlg`/`gen3_lgfr` (both cartridge orientations):
- §2-3: `faint_cmd_gen3`, `link_gen3`, `boxsync_gen3`, `reconnect_gen3`, `deadzone_gen3` — 5 rows, FR orientation only
- §4: `whiteout_gen3`, `center_controls_gen3` × {fr, lg} — 4 rows
- §5: `linked_faint_active_gen3`, `active_end_gen3`, `linked_faint_active_whiteout_gen3`, `linked_faint_active_trainer_gen3` × {fr, lg} — 8 rows
- §7: `save_then_write_gen3` × {fr, lg} — 2 rows

Of these, the rows whose non-tested side can become a fake peer under §1's classification:
`faint_cmd_gen3` (A), `active_end_gen3` (B) ×2, `center_controls_gen3` (B) ×2,
`save_then_write_gen3` (B) ×2, `trainer_bench_gen3` is not in this build_plan list (only
referenced via its own `active_faint_case`/`battle_window` module, not a separate G4 row)
— **7 of the 19 G4 rows** qualify. At 2-4 min observed for light rows, cutting one of two
EmuHawk instances removes roughly **half that row's EmuHawk-side wall time and CPU**
(server + one client's boot/idle-hold vs. two): call it **1-2 min wall and ~1 core-minute
of CPU per row**, so **~7-14 min wall and ~7 EmuHawk-instance-launches removed per G4 pass**
across those 7 rows. `linked_faint_active_gen3`/`_whiteout`/`_trainer` (the other 6 of the
8 §5 rows) get **no reduction** — both sides are genuinely under test — so the 19-row G4
pass's dominant cost (the heavy P+H battle rows, ~20+ min each × 6 = ~2 h of the pass) is
untouched by this technique; §3 below is where that time actually lives.

## 3. Other time sinks, ranked, with cheapest safe reduction

1. **Natural in-battle Perish/faint chains** (`linked_faint_active_gen3` family, `explode_gen3`)
   — ~20-25 min/row observed, the single biggest line item (6 rows × ~20 min = ~2 h of the
   G4 pass alone). Per §1, A/B cannot be faked here — the natural engine event *is* the
   behavior under test on both sides. Cheapest safe cut: a **cached-native savestate at
   the exact pre-KO turn** (SOURCE tier unchanged: state is a real save produced by a real
   run, MODEL is nothing, PHYSICAL is the emulator continuing from it) so the row skips the
   turns needed to grind HP down and starts one Perish-tick before the KO, the same
   discipline `tools/mkstates_gen3.py`/`mkstates_gen3_tutorials.py` already use for
   `slink_prebattle.State`/`slink_postbattle.State` (6-16s to *build* those states per
   `mkstates_gen3_*_2026-09-23.txt`). This keeps the actual faint natively engine-driven,
   only the setup is skipped — legal under the evidence rule in §4.
2. **RNG encounter/catch hunts** (`link_gen3`, `deadzone_gen3`, `ball_hunt: True` rows,
   `RNG_RETRY_FAMILIES`) — variable cost, worst case a whole-row retry
   (`run_scenario_with_rng_retry`). Cheapest reduction: none that preserves SOURCE tier for
   the catch mechanic itself (that's the thing under test), but the **walk-to-grass** portion
   is not: a cached-native savestate seeded one tile into the grass (same "encounter-free
   ground vs tall-grass" split as `tools/mkstates.py`'s Gen 1/2 town/battle split, noted in
   memory) removes the walk without touching the RNG catch itself.
3. **Boot/CONTINUE + fixture staging** — already cheap per receipt (5-6s in-emulator per
   `fc_bootcheck_*` row) but paid **twice per duo row** (both instances) and **again per
   orientation** (fr vs lg) and **again per RR/FRLG game**. Cheapest reduction: none of the
   §1 fake-peer rows touch this line item much since boot cost is roughly symmetric per
   instance; the real lever is **parallel lanes** (run the fr and lg orientations of the
   same §4/§5 row concurrently — they are already fully independent worktree-clean lanes
   per `item6_route_diff_*` receipts using `gen3-lane-clean`/`gen3-lane-master`), which is
   an orchestration change, not a savestate change, and halves *wall* time (not CPU) for
   any row currently run fr-then-lg serially.
4. **Tutorial/state builds** (`mkstates_gen3_tutorials.py`) — already cheap, 15-16s each
   per `tutorial_states_{fr,lg}_2026-09-23.txt`; not a real time sink, no action needed.
5. **Item 6's Gen 1/Gen 2 differential** (`item6_route_diff_*`) — the Gen 2 legacy duo
   dies at boot on **both** master and branch in ~7s (`item6_route_diff_master_2026-09-24.txt`:
   *"~7 s per scenario"*, boot never reaches the overworld). This is already cheap because
   it's broken, not because it's optimized — no time-saving action applies; it's a
   correctness bug (out of this card's scope) that happens to cost nothing today.
6. **Trainer route (`trainer_bench_gen3`/T2 walk)** — already cached-native per its own
   `SCENARIOS` comment (*"boots ... CACHED-NATIVE at (41,45) on map 1.0, one step west of
   Rick 102's sight line ... gen3_routes skips the T2 walk"*) — already done, cited here
   only because the card asked for it; no further action.
7. **`checkpoint_{firered,leafgreen}` probe wrapper rows (§6 item 3)** — 1800s budgeted,
   not decomposed in the receipts gathered here (they wrap the base + battle-window rows
   through `tools/gen3_probe_receipt.py`); no scenario-level fake-peer opportunity found
   since these re-run the same rows already covered above. Not separately estimated to
   avoid double-counting §2's numbers.

## 4. Evidence-tier compliance

Every proposal above keeps SOURCE (the ROM/decomp-derived facts), MODEL (the codec/derived
offsets), and PHYSICAL (the actual EmuHawk run) tiers distinct: a fake peer only ever
stands in for a **bystander** side that emits no game-state fact the oracle reads (§1's
(b)/(c) rows) — never for a side whose native write, native menu state, or natural engine
event is what the row's oracle asserts. Cached-native savestates (§3 items 1-2) move the
*setup* earlier, never replace the *behavior under test*, matching the `tools/mkstates_gen3*.py`
precedent already in this repo. No proposal here touches `linked_faint_active_*`,
`explode_gen3`, `native_absent_gen3`, `boxsync_gen3`, `whiteout_gen3`, `link_gen3`, or
`deadzone_gen3` — the rows where both sides are simultaneously the thing under test.
