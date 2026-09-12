# Gen 3 Radical Red as the gameplay standard: comparison with the Gen 1 work

Status: assessment for the project owner and root (`codex:Gen1`), written 2026-09-10 by the
Claude peer from three read-only surveys of the sweep worktree (Gen 3 client and shared
engine; Gen 1 legacy client and RC runtime; the RC rule-settlement path). Every claim cites
`file:line` in `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`. No code
changed. The owner's premise, which this document adopts: Gen 3 Radical Red is the gameplay
standard, the goal is to make that standard durable, and future generations are adapters.

## 0. Summary

Three central misunderstandings, in order of cost:

1. **Two decision engines.** The RC does not make the Gen 3 standard durable; it re-expresses
   Gen 1's rules in a parallel layer that Gen 3 never runs. `SoulLinkState` is reused as a data
   model and a handful of primitives, but every settlement decision in a production Gen 1 run
   is made by `capture_rules`, `no_catch_rules`, `linked_death_rules`, `party_grant_rules`,
   `member_identity_rules` and eleven `gen1_*_runtime` modules, and `SoulLinkState.handle_event`
   is unreachable (`server/gen1_run_config.py:84-87` passes a `validate_event` that raises for
   every gameplay event; `server/gen1_runtime_state.py:187-202`). The two paths are mutually
   exclusive by construction (`server/server.py:2999-3000`). Section 1.
2. **Standard rules missing or refused in the RC.** Whiteout and rebuild: no implementation.
   Shiny bonus pairs: not implemented. Explode Mode: refused (`gen1_faint_runtime.py:126-127`).
   Rival Team Swap: never issued. `game_over`: never pushed. Dupes-at-encounter, clause retry
   and `memorialize_failed` handling: absent. In-battle faint: prototype only. Section 2 rows
   3, 4, 8, 10, 11.
3. **Semantic drift where the RC did re-implement a rule.** A link forms at the next stable
   inventory checkpoint, not at the catch. A clause violation halts the run with a recovery
   blocker instead of killing the offender and reopening the area. A dead zone opens a
   retirement job with a save receipt instead of an immediate faint. The memorial box is
   fixed at index 11 instead of adapter-chosen. Dashboard reset, restore, manual link and
   attempts editing are disabled. Section 1.2.

Two more things the reading established. The frame-credit execution model, already covered
in `EXECUTION_MODEL_PROPOSAL.md`, is the fourth divergence: Gen 3 free-runs on a frame-end
callback with no pause anywhere (`gen3_frlge_client.lua:4525`). And the standard itself has a
live regression: the Gen 3 native trade animation cannot run on a patched ROM since commit
`134f007`, so trades fall back to a silent swap after 1,800 frames (section 2, row 12).

Where the RC genuinely exceeds the standard, and the framework should keep it: memorials
verified against a full save image; ROM admission by complete hash; a durable journal that
survives a server restart (Gen 3 loses every queued command except memorials); native cable
trade with the original animation on all nine pairings; the in-game panel; source-anchored
capture receipts that cannot mis-attribute a catch. Those are the durable parts. The rules
layer is not.

## 1. The two engines

### 1.1 What is shared and what is not

| Layer | Gen 3 today | Gen 1 RC | Shared? |
| --- | --- | --- | --- |
| State types (`LinkEntry`, `MonInfo`, `AreaStatus`, `LinkStatus`, `to_document`) | `server/state.py` | `StagedGen1State` ⊂ `StagedSoulLinkState` ⊂ `SoulLinkState` (`gen1_staged_state.py:6`, `staged_state.py:47`) | Yes |
| Clause check | `_check_link_violation` (`state.py:2578`) | Same function via `capture_rules.py:54` | Yes |
| Capture settlement | `_handle_capture` (`state.py:1212`) | `capture_rules.record_clause_checked_acquisition` (`capture_rules.py:16-64`), a detached copy | No |
| No-catch / dead zone | `_handle_no_catch` (`state.py:1841`) | `no_catch_rules.record`, "follows `_handle_no_catch`" (`no_catch_rules.py:1-4`) | No |
| Faint propagation | `_propagate_faint` (`state.py:2685`) | `linked_death_rules.record_linked_death` (`linked_death_rules.py:39-64`) | No |
| Memorial completion | `_handle_memorialize_done` (`state.py:2822`) | `linked_death_rules.record_memorial_completion` | No |
| Key change (evolution, NPC trade) | `_handle_key_change` (`state.py:2475`) | `member_identity_rules.rekey` | No |
| Whiteout, rebuild, game over | `_handle_whiteout` (`state.py:1992-2074`), `_check_game_over` (`:3046`) | None; `update_run_over` flips a flag (`linked_death_rules.py:9-13`) | Missing |
| Shiny bonus pairs | `state.py:1231-1362` | Refusal guard only (`capture_rules.py:31`) | Missing |
| Command emission | Handlers append to `queued_commands` | Rule functions return one command and refuse to run if `queued_commands` is non-empty (`capture_rules.py:25`, `linked_death_rules.py:57`) | Incompatible |
| Persistence | `links.json` + `memorial.json` (`state.py:3081-3104`) | SQLite journal; `_save` writes no file (`staged_state.py:90-94`); creating a run refuses a directory with `links.json` (`gen1_run_config.py:107`) | No |
| Dashboard mutations | reset, restore, manual link, debug mutation, attempts edit | All return `available: False`; non-GET is 409 (`runtime_boundary.py:29-71`, `server.py:8624-8626`) | No |

### 1.2 What a Gen 3 player would notice if Gen 3 moved onto the RC rules as they are

- A catch links at the next stable inventory checkpoint, not the instant the second catch
  arrives (`gen1_acquisition_runtime.py:142-167,224-229` vs `state.py:1632-1636`).
- A clause violation no longer force-faints the offender, memorializes it and reopens the
  area (`state.py:1597-1630`); both halves stay pending and the run raises a recovery blocker
  (`capture_rules.py:55-58`, `gen1_acquisition_runtime.py:259-266`).
- A dead zone no longer force-faints the partner's pending catch immediately
  (`state.py:1977-1981`); it opens a retirement job that needs a physical save receipt
  (`gen1_wild_encounter_runtime.py:351-404`, `gen1_retirement_runtime.py:124-175`).
- A faint produces exactly one peer command, deferred to `pending_issue` if a storage job owns
  either party, and the pair is closed only by receipt-verified ACK, then paired memorial
  receipts (`gen1_faint_runtime.py:56-84,176-187,229-232`). Gen 3 queues faint, sound and
  both memorials in one turn (`state.py:2685-2727`).
- A failed memorialize blocks the death instead of counting as done (`state.py:2847-2872`
  has no RC equivalent).
- No whiteout, no rebuild, no shiny bonus pair, no Explode, no Rival Swap, no `game_over`.
- The memorial box is index 11 regardless of adapter (`gen1_memorial_policy.py:20`); Gen 3
  RR uses 24 (`adapters/gen3_frlge.py:584-587`).

Some of these are improvements in rigor (evidence before closure). None of them were decided
as changes to the standard, and Gen 3 does not get them. That is the definition of drift.

### 1.3 What "make the standard durable" should mean

One engine, wrapped, not two engines sharing a data model:

- `SoulLinkState` stays the only place a rule is decided. The one refactor the RC needs from
  it, "return the commands instead of appending to `queued_commands`" so a journal can commit
  rules and commands in one transaction, is applied once, to the shared methods, for every
  generation. The five parallel rule modules fold back into those methods or are deleted.
- The durable layer (journal, one-use held-write permits, receipt verification, recovery
  barrier, lease) wraps the engine. It decides when a decision is committed and what evidence
  closes a command. It does not decide the rule.
- A generation adapter supplies: detection (Gen 3: per-frame RAM diff plus patch events;
  Gen 1: engine-signal hooks and source receipts), the safe-state predicate, the write
  executors (force_faint including the in-battle path, box and party moves, memorialize,
  rival team, explode), ROM admission, and native UI capabilities. All of it feeds the same
  semantic events the engine already consumes: `capture`, `no_catch`, `faint`, `whiteout`,
  `party_to_box`, `box_to_party`, `key_change`, `trainer_battle_start`, `area_enter`.
- Where the RC's rigor is better than the standard (memorial save verification, hash
  admission, evidence before closure), it becomes the standard by changing the shared method
  and the Gen 3 adapter together, not by giving Gen 1 a private rule.

## 2. Row by row

Verdict key: **match** (same player-visible behaviour), **exceeds** (same behaviour with
stronger evidence or a real improvement), **diverges** (different behaviour), **missing**
(the standard does it, the RC does not), **n/a** (RR-only mechanism with no Gen 1 analogue).
"Legacy" is `lua/clients/gen1_rby_client.lua`, the client the duo E2E runs today; "RC" is the
durable runtime.

| # | Feature | Gen 3 RR today | Gen 1 legacy | Gen 1 RC | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | Encounter linking | Per-frame party diff; new key during or right after battle → `capture` (`gen3_frlge_client.lua:3588`); box catches resolved in a 90-frame grace (`:3969-4079`); server links the instant the second capture arrives (`state.py:1622-1681`); no safe-state gate on emission | Same shape: RAM diff, gift flag, box grace scan (`gen1_rby_client.lua:977-1004,1120-1126`); links immediately | Source receipt at the pinned `ItemUseBall` call and return with byte-shape proof of party vs box (`gen1_capture_receipt.py:1-21`); fact pending until a stable inventory checkpoint (`gen1_acquisition_runtime.py:1-13,224-232`); ordinal per pairing; delivery observer live-proven, settlement unit-only | **diverges** on timing (checkpoint vs instant); **exceeds** on attribution |
| 2 | Dead zone / no_catch | Emitted once when post-battle grace ends with no catch: fled, ran, KO'd or lost all count; carries species and level (`:4088-4105`); server creates DEAD_ZONE and force-faints the partner's pending catch immediately (`state.py:1976-1982`) | Same, with species and level read mid-battle (`gen1_rby_client.lua:1257-1276`) | `wild_begin`/`wild_end` receipts (`gen1_wild_encounter_receipt.py`), deferral while the peer is unsettled, then a retirement job with a save receipt (`gen1_retirement_runtime.py`); unit-only | **diverges** (retirement job vs immediate faint) |
| 3 | Faint propagation | Killer side: HP 1→0 diff, in battle debounced 3 frames or confirmed by faint counter / EvRing (`:3676-3797`). Partner side: benched or overworld immediate; active battler deferred to switch-out or battle end (`:781-798`, `:2543-2568`) | Killer side: RAM diff (`:1136-1163`). Partner side: immediate always; active mon mirrored into `wBattleMonHP` (unit-tested only, `test_gen1_force_faint_battle.py`) | Killer side: engine hooks at `RemoveFaintedPlayerMon` and poison (`gen1_engine_signals.py:24-33`), cause battle or poison. Partner side: one-use held permit at the overworld checkpoint only; refuses battle (`gen1_held_faint.lua:38-40`, `gen1_held_faint.py:71`); live-proven on 10 launcher cases. In-battle: prototype proven live on R/B/Y, unwired | **missing** in battle (benched case outright; active case only after battle); **exceeds** on killer-side evidence |
| 4 | Whiteout | Client detects all-zero party after a real faint (`:3807-3814`); server force-faints every living partner, plans an auto-rebuild from boxed pairs, else `run_over` + `game_over` to both (`state.py:1992-2074`) | `check_whiteout` (`:1069-1083`); duo scenario `whiteout` passes | **No implementation** in any `gen1_*` module; `update_run_over` sets a flag only | **missing** |
| 5 | Party / box sync | 5-frame buffered diffs → `party_to_box` / `box_to_party` (`:3706-3729,3599-3618`); server `box_mon` / `party_mon` (`state.py:2076,2124`); executed one per frame at `safe_now` = overworld, cooldowns, end-of-battle settled (`:2584-2589`); native ops via patch, Lua fallback | Debounced diffs; deferred `box_mon`/`party_mon` drained when `isPartyWriteSafe()` (`:1167-1245,1680-1700`) | `storage_observe` / `storage_apply` jobs: read both, paired writes, saved ACK, compensation (`gen1_storage_runtime.py`); quarantine, reserved box 11, grave-evict, linked co-location (`gen1_storage_policy.py:50-113`); unit-only | **match** on the rule, **diverges** on mechanism (two-phase jobs, reserved box, co-location), **exceeds** on evidence |
| 6 | Memorialize | Queued on death, dead zone, whiteout, clause rejection; box `BOXES_PER_STORE-1` = 24 on RR, "THE DEAD" (`gen3_frlge.lua:268`); each client acts on its own safe gate, pair is MEMORIAL when both report done (`state.py:2822`); a failed memorialize still counts | Deferred queue, box 11, `memorialize_done`/`failed` (`:1883-1930`) | Journal-owned preparation → compact delta → SaveRAM flush and readback → per-player ACK, full-image verification, chained grave reservation (`gen1_memorial_runtime.py`); live-proven on 7 cases incl. Y/Y | **exceeds** on evidence; **diverges** on fixed box index and no failure path |
| 7 | Nuzlocke gate | `hasPokeballs()` polled every 15 frames and on hello (`:4110-4117`); server sets `pokeballs_obtained` from hello, tick or any non-gift capture (`state.py:999,1226`) | Polled bag read (`memory_gb.lua:609`) | Engine signal `bag_received` at `AddItemToInventory_` with destination, success flag and ball id checks (`gen1_engine_signals.py:36-52`); live-proven | **match**, **exceeds** on evidence |
| 8 | Clauses and shiny bonus | Server-side `_check_link_violation`; violation → force_faint, memorialize, sound, `unresolve_area`, clause retry (`state.py:1597-1630`); `check_dupe_on_encounter` at wild-battle start; shiny clause always on with bonus pairs (`state.py:1231-1362`) | Same server code; shiny never fires because Gen 1 `is_shiny` is False | Same clause function, but the violation is returned and turned into a recovery blocker (`capture_rules.py:1-8`, `gen1_acquisition_runtime.py:258-265`); no `unresolve_area`, no clause retry, no dupes-on-encounter, no bonus pairs | **diverges** (halt vs kill-and-reopen); **missing** bonus pairs and encounter dupes |
| 9 | Gifts, statics, NPC trades, evolution | Gift = new key outside battle, linked under `gift_<area>` (`:3620-3648`); statics are ordinary captures in their map; NPC in-game trade has no path (reads as deposit plus gift capture); evolution is silent, key unchanged; `key_change` only for RR's Nature Changer (`:3397-3560`) | Two events: `capture{gift}` and `key_change` for NPC trade and evolution (`:1028-1067`) | Seven typed receipt kinds (`gen1_source_receipts.py:31`); statics pair under their own static id; Game Corner pairs per purchase ordinal; Yellow-only grants retire in mixed pairs; NPC exchange migrates identity; evolution has its own receipt (`gen1_acquisition_runtime.py:109-121,239-249`); all unit-only | **exceeds** on attribution (Gen 3 mis-reads an NPC trade); **diverges** on pairing rules Gen 3 does not have (per-purchase ordinals, static id) |
| 10 | Explode Mode | RR only; `force_explode` writes Explosion into all four battle move slots plus the menu-skip commit state, re-asserted per frame, 600-frame fallback to faint (`memory_gba.lua:1303`, `:2376-2430`); pure RAM writes, no patch | Works without a patch via `wPlayerSelectedMove` and four move slots (`memory_gb.lua:836-853`, client `:290-334`); duo `explode` scenario | **Refused** with "requires its qualified physical receipt binding" (`gen1_faint_runtime.py:126-127`), while run creation still accepts the option (`gen1_run_config.py:114`) | **missing** |
| 11 | Rival Team Swap | RR + patch; `trainer_battle_start` after 2 stable frames (`:2316-2341`); server checks rival ids and the run flag (`state.py:2957`); client requires the patch (`:806-860`) | Works without a patch: plaintext `wEnemyMons` byte copy (`:335-371`); duo `rivalswap` scenario | Never issued by any `gen1_*` module | **missing** |
| 12 | Native trade | RR + patch; initiated by talking to the peer ghost or the Center NPC; server-driven choose/confirm; `apply_trade` to both; `_commit_trade` swaps halves atomically after both report; linked halves only (`state.py:482-760`). **Regressed:** since `134f007` the staging step is inside the not-patched branch (`:2221-2241`), so on a patched ROM phase `pending` can only time out after 1,800 frames into the silent-swap fallback; no animation runs | None | Cable Club receptionist at every Center and Indigo, native menus, partner answers the cartridge's own YES/NO, both original animations, full 32 KiB saves verified before COMMIT (`RECEPTIONIST_TRADE_FLOW.md`, `RECEPTIONIST_SAVE_RUNTIME.md`); live on all nine pairings; not default, needs `ordinary_frames` | **exceeds** the standard as written; the standard as running is broken |
| 13 | In-game panel | RR + patch; server builds per-recipient rows (`server.py:2744`); 6 rows per page in EWRAM; A pages, B closes | Rows held until the patch says the screen is free (`:453-458,1372-1385`) | ABI-3 mailbox, staged generations, three BG transfers, wrap, timeout, canary (`PANEL_ABI3.md`); 144-scenario matrix; Yellow has no panel | **match** (R/B), **exceeds** on protocol rigor; Yellow n/a |
| 14 | Native messages and sounds | RR + patch; field box when safe, battle message window, `play_se` outside battle, Lua overlay fallback; both off by default | No-op sound; overlay messages | SFX will not ship (unsafe hook, `RC_NOTES.md:272`); messages off at run creation | **n/a** by decision; the reason is documented and sound |
| 15 | Overworld presence / peer ghost | RR + patch both sides; 30 Hz `ghost_pos`, engine object-event with the partner's own sprite and palette | Reserved, never emitted | Disabled at run creation | **n/a** (RR-only mechanism); note it is also the trade entry point on Gen 3 |
| 16 | Reconnect and recovery | Send queue replayed on reconnect; hello re-reconciles everything (`state.py:951`); **server restart loses all queued commands except memorials** (`queued_commands` is in-memory); savestate load invisible except patch beacon re-assert | Re-seeds keys and re-sends hello; ROM revalidation; no journal | SQLite journal per run, `RuntimeLease`, `RecoveryBarrier` with typed blockers, atomic frame reservations; same-core reconnect proven; reset/load/rewind matrix open | **exceeds**; the standard has a real durability hole here |
| 17 | Runtime model | Frame-end callback, free-running, no pause anywhere (`:4525`); one deferred command per frame; tick every 30 frames | Same shape | Held service, server-issued 60-frame/1000 ms credits, `step_one` per frame, bundle per range; pre-ball gate (`gen1_frame_control.py:51-54`); about 31 FPS | **diverges**; see `EXECUTION_MODEL_PROPOSAL.md` |
| 18 | ROM identity | Header code plus pointer plausibility (`gen3_frlge.lua:437`); no hashes client-side; `Gen3Adapter` has no fingerprint, so randomizer contracts are never enforced (`server.py:1763`, `base.py:360-372`) | Clean-only header detection | Complete canonical hashes, companion patch reproduces installed SHA-256 and reverses byte-for-byte, UPR provenance (`gen1_admission.py`, `gen1_companion_patch.py:11-28`); live-proven | **exceeds**; the standard cannot tell a modified ROM |
| 19 | Run creation | `POST /api/runs`, eleven booleans, no generation selector; `randomize` writes a contract that Gen 3 never checks | Same Manager | `POST /api/runs/gen1`, factory with per-player config and SaveRAM directories, lease, 28-file launcher closure (`manager.py:751-786`, `gen1_run_config.py:97-130`); Explode and presence options forced off | **exceeds** on isolation; **diverges** on options |

Counts: match 3, exceeds 9 (several rows carry two verdicts), diverges 8, missing 5, n/a 2.

## 3. What the RC got right that the standard lacks

These are the parts worth generalizing into the framework, in this order:

1. **Durable command journal.** Gen 3 loses queued commands on a server restart. The RC's
   journal, lease and recovery barrier fix a real hole. Framework.
2. **Evidence before closure for physical writes.** One-use permits, pre/post images,
   full-save verification for memorials. Framework, with the Gen 3 adapter supplying its
   own safe-state predicate and readback.
3. **Admission by complete hash.** Gen 3 admits any ROM that looks right. Framework, with
   per-generation profiles.
4. **Source-anchored capture attribution.** Gen 3 mis-reads an NPC trade as a deposit plus a
   gift and cannot distinguish a static from its map. The receipt kinds are the Gen 1
   adapter's detection method; the engine should accept either detection method through the
   same semantic events.
5. **Native cable trade with the original animation** and the **ABI-3 panel**. Gen 1
   adapter features, already live on all pairings.

## 4. What must change for the goal to hold

1. Fold the five parallel rule modules back into `SoulLinkState`, applying the
   "return commands" refactor to the shared methods once. Until then every Gen 1 rule fix
   drifts from Gen 3 and vice versa. This is the single largest correction.
2. Implement the missing standard rules in the shared engine path for Gen 1: whiteout and
   rebuild, shiny bonus pairs, Explode (the legacy mechanism works and is live-tested),
   Rival Team Swap (the legacy mechanism works), `game_over`, dupes-at-encounter, clause
   retry with `unresolve_area`, `memorialize_failed`.
3. Decide, as standard changes rather than Gen 1 privates, which of the RC's stricter
   semantics the product wants: link-at-checkpoint, halt-on-violation, retirement jobs,
   evidence-gated memorials, fixed memorial box, read-only dashboard. Each is either adopted
   for Gen 3 too or reverted for Gen 1.
4. Adopt the free-run loop as the framework's core loop (`EXECUTION_MODEL_PROPOSAL.md`), which
   also unblocks the in-battle faint wiring and the sixty single-player manifest rows.
5. Wire the in-battle faint (`BATTLE_FORCE_INTEGRATION.md`) so Gen 1 meets and then exceeds
   the standard's benched-immediate, active-at-switch-out behaviour.
6. Fix the standard's own regression first: the Gen 3 native trade scene
   (`gen3_frlge_client.lua:2221-2241`, lost gate `memory.read_u8(0x03000F9C) == 0 and not
   pending_ui`). A standard that is broken cannot be made durable.

## 5. Easy code wins queued for after this assessment

- Gen 3 trade staging gate restore (row 12); one conditional, verify with `test_live_tradescene.lua`.
- Client grant replay instead of a fatal error on a late grant reply
  (`gen1_frame_client.lua:309`, `COLD_ROUTE_FORENSICS_2026-09-10.md`).
- The five acquisition tests still asserting the pre-Sept-9 outcome
  (`test_gen1_acquisition_runtime.py:180` and the two in `test_gen1_frame_acquisitions.py`).
- `playwright` install so the four browser-patcher integration tests run.
- Memorial box index from the adapter instead of the fixed constant (`gen1_memorial_policy.py:20`).
- Refuse the `explode_mode` option at Gen 1 run creation until the binding exists, instead
  of accepting it and failing at the first death (`gen1_run_config.py:114`).
