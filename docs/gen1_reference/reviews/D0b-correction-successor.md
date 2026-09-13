# D0b correction: seven premises re-checked against source

Card `D0b-correction-successor`, claudex task `cx-d6a5289b`. Author: Claude Gen1-Collab2 (transport `4ec907e2-58e4-4495-8aba-87fc96ff233c`, resumed `b4c6c3b4…`), host HOUNDOOM. Written **2026-09-13 14:04 UTC** on canonical `gen1/rc` at `51c339d` (coordinator docs; production source still `19edbb2`). Corrects [the frozen D0b report](D0b-design-20260913-successor.md), which stays unchanged. Research only: no source/test/schema/emulator execution or write, no commit, no guide edit. Labels as in the original: **FACT** (source at `19edbb2`, file:line), **PRET** (pinned pret), **MODEL**, **PHYSICAL**, **DESIGN**, **POLICY**. Status lives only in [the master guide](../RC_MASTER_GUIDE.md); H1/Slice A remain **HOLD** and nothing here revives them.

## What stands (accepted, unchanged)

No relaunched process resumes today; the four server-side gates in original §2a items 2–4 are correct as cited (`gen1_service_continuity.py:84-89,182-185`; `gen1_observation_runtime.py:121-125,132-133`; `gen1_held_faint.py:96-104`; `battle_force_authority.py:313-317`; `gen1_native_progress.py:55-68`). The immutable initial record (`gen1_initial_observation.py:165`) and the existing lineage seam `IdentityRegistry.bind_context`/`context_history` (`identity_registry.py:123-142,288-291`) are correct as cited. The TCP-reconnect versus restart distinction (original §1c) stands. P2a, N0 and D0 gate any implementation; the original's "no blocker for Slice A" sentence was wrong and is withdrawn (correction 7).

## The seven corrections

### 1. Product process ownership already exists (original §5 "competing old process", finding 7 of the reply)

**Wrong:** "nothing locks `game.sav`/`journal.json` between two EmuHawks", proposing a new Lua lease.
**FACT:** `tools/launch_bizhawk.py:38-45` resolves `home=<root>/<run_id>/<player>`, then `with RuntimeLease(home/'.process.lock')` wraps **both** `prepare()` and `launch(...).wait()`, so the product CLI holds an OS byte lock (`server/runtime_lease.py:13-29`: `msvcrt.locking(LK_NBLCK)` / `flock(LOCK_EX|LOCK_NB)`) for the whole emulator lifetime; a second CLI launch for the same run/player raises `another server owns this runtime, or its lease is unavailable`. MODEL: `tests/unit/test_runtime_lease.py:46,61,75` exercise two-handle exclusion, child-process exclusion and reacquisition after close.
**What the lock does not cover (FACT by construction, not a defect claim):** (a) a **bypass launch**: EmuHawk started directly on the prepared directory without the CLI, which is exactly what the live harness does (`run_gate` per [RC_PLAN_REVIEW](RC_PLAN_REVIEW.md) "Actual product launch was not exercised"); (b) **launcher death**: the lease is a handle owned by the Python launcher, released when that process exits (`runtime_lease.py:31-36`), while the EmuHawk child it spawned keeps running; a subsequent CLI launch then acquires the lease and starts a second EmuHawk on the same SaveRAM directory. Whether Gambatte/EmuHawk itself holds `game.sav` open is **unverified**.
**Cheapest falsifier:** host-level, no game claim: start the CLI for a run/player, kill only the Python launcher (leave EmuHawk), run the CLI again for the same manifest; observe whether the second acquires `.process.lock` and starts. A MODEL companion: none needed; the existing lease tests already cover the CLI-versus-CLI case.

### 2. The heartbeat does not carry a fresh full point (original §3 H1b, §6 Slice A guard)

**Wrong:** "at every heartbeat … `image(point) == cart_hex` is a pure comparison", assuming a full-save point is available each heartbeat.
**FACT:** `lua/gen1_observation_loop.lua:92-104`: on a heartbeat with `ctx.checkpoint` present (the free loop always constructs it, `gen1_client_entry.lua:412-413,430`), the loop calls `ctx.checkpoint(self.fingerprint, retry~=nil, frame)`; `lua/gen1_inventory_checkpoint.lua:15-32` captures a full point **only** when `Fingerprint.same(previous,current)` is false or a retry forces it. `lua/gen1_inventory_fingerprint.lua:15-27,29-39` covers WRAM `party/box/name`, `player_id`, `current_box` and the twelve CartRAM box records in banks 2–3 (`(2+index//6)*0x2000`). It reads **no** SRAM bank 1 (`sGameData` `0xA598..0xB523`, PRET `gen1_full_save.py:20-27`) and no `wMainData`/`wSpriteData`. Therefore an in-game save that changes no roster byte produces **no** `inventory` publication and the server never sees the post-save `cart_hex`. `ctx.inventory` (the unconditional full capture, `:44-47`) is used only when no `ctx.checkpoint` exists (`loop:100-104`), never in the free loop.
**Cheapest falsifier:** MODEL, pure function: build two fingerprints from a modeled memory that differ only in CartRAM bank 1 bytes (`sMainDataCheckSum` or `sPlayTime*` inside `sMainData`) and assert `Fingerprint.same()` is true; PHYSICAL companion: save in-game in the bedroom, wait two heartbeats, read `observation_diagnostics.inventory_publications` from the client status and assert it did not increase.

### 3. Full WRAM/SRAM equality is not an every-save witness (original §3 H1 file row and H1b)

**Wrong:** "`image(point) == cart_hex` detects an in-game save one heartbeat later".
**PRET:** `wPlayTimeFrames` (`0xDA45`) lies inside `wMainData` (`0xD2F7..0xDA80`, `data/pret_syms.json` pokered) and is incremented every VBlank while the game timer counts (`.cache/pret/pokered/home/vblank.asm:75` → `engine/play_time.asm:1-15`). `SaveMenu` waits 120 frames, the save SFX, then 30 more frames **after** `SaveGameData` (`.cache/pret/pokered/engine/menus/save.asm:167-181`). So by the first free frame after a save, `image(point)` (which projects current `wMainData`, `gen1_full_save.py:42-55`) already differs from SRAM in the play-time bytes; equality holds essentially never, not "one heartbeat later". The codebase already treats `main` as volatile: MODEL `tests/unit/test_gen1_service_continuity.py:144` ("later frame volatile main bytes do not replace inventory semantics").
**What is precisely missing (save witness):** there is no engine signal at `SaveGameData::` (`save.asm:290`) or on `SaveMenu` return (`data/games/gen1_rby/engine_signals.json` hooks `bag_received, battle_faint, poison_faint, starter_begin, starter_end` only), and per correction 2 no bank-1 SRAM coverage in the fingerprint. A witness would have to be one of: (i) a source-pinned `SaveGameData` hook row in the engine batch, or (ii) a bank-1 SRAM fingerprint region; both are DESIGN, neither is proposed here.
**Cheapest falsifier for the gap:** MODEL: feed `gen1_service_continuity`/`_inventory_semantics` two points identical except `wPlayTime*` and confirm semantics equality but byte inequality (already implied by `:144`); PRET reading alone settles that a full-image equality witness cannot exist.

### 4. No held file authority exists for the loop (original §3 H1 file row, §6 Slice A client item)

**Wrong:** "compose `platform_saveram.flush(image(point))` with the loop's current inventory point" as a one-call-site change.
**FACT:** `lua/platform_saveram.lua:6` asserts `options.authorize` is a function and `guard()` (`:66-72`) re-checks it before and after every flush. Every existing provider binds `authorize` to a **server-issued command identity**: `lua/gen1_held_save_image.lua:55-62` (`options.safe() and (constructing or options.permitted())`), `lua/gen1_native_runtime.lua:186-189` (`authorized("save", self.current.body, identity)` and lease phase `complete`), `:205-207` (`authorized("full_save_ready", …)`). The inventory checkpoint releases the writer hold before it returns the point (`lua/gen1_inventory_checkpoint.lua:31`), and the loop context (`gen1_client_entry.lua:414-449`) exposes `writer.service` only for **pending durable commands** (`writer_pending`, `:407-409`); it carries no file provider and no private authority. A flush from the loop would be an unpermitted physical write.
**What is precisely missing (held-file interface):** a server-scheduled durable command whose permit authorises exactly one `FlushSaveRAM` + readback at a held frame and whose receipt is the existing `slink-saveram-file-v1`, verified by `save_file_receipt.verify_file_image` against an expected image the server can compute. Today the only such command is `initial_save`, whose expected image is a WRAM projection valid only pre-starter (`gen1_initial_save.py:28-45`); for a later save the server holds no trustworthy expected image (correction 2/3), so even the command shape is unspecified. DESIGN, not proposed.
**Cheapest falsifier:** MODEL: on the real runtime, `command_ack` for an unknown `cmd` reaches `Gen1ReceiptPolicy` through `DurableRuntime._dispatch_semantic` (`gen1_runtime.py:452`) and is refused; and `platform_saveram.new{}` without `authorize` raises `private save-file authority required` (`:6`).

### 5. The relaunched client fails earlier than the report said (original §1b step 7, §2a gate 1, §2b client test)

**Wrong:** "the client sits in `held_service` deferring continuity with `free observation loop is not initialized`".
**FACT:** after HELLO is admitted, each tick runs `self.runtime:step()` then `self.observer:step(self.runtime:is_bound())` (`gen1_client_entry.lua:527-530`). `lua/gen1_initial_observation.lua:70-75` reads the persisted `initial_inventory` (full payload or compacted cursor) and asserts its `context_generation` equals the current `owned()` context: `initial inventory belongs to a replaced context; reconciliation required`. The assertion escapes the entry's `pcall`, so `phase="failed"`, the runtime is revoked and the lifecycle hold is set (`:532-537`); `M.run` then closes the service and re-raises (`:626-632`). The continuity deferral at `:287-288` is therefore never the observable state of a relaunch; the observable state is a **failed** entry with that reason. Consequence for the original §2b client test: assert `phase=="failed"` and that reason, not `continuity.reason`.
**Unverified ordering:** for a native launch, whether the queued `native_reattach` event (`:546-567`) is delivered before the first bound observer tick fails; it depends on the control/semantic cadence in `lua/durable_runtime.lua:447-497`. A MODEL run of the real entry (as `tests/unit/test_gen1_native_entry.py`) started twice on one storage root settles it.

### 6. The outbox replay loop is narrower than claimed and masked (original §2a "latent defect", finding 6)

**Wrong:** "a durable event left in the outbox at exit is replayed after the next HELLO … an unbounded loop with no discard path", stated for any leftover event.
**FACT:** `gen1_observation_runtime.record:90-92` returns the **committed** prior result before `typed()` and the context checks; `protocol_journal.event:310-320` matches on `(player, operation_id)` and the request digest. So an event whose server commit succeeded but whose ACK was lost replays to the same result under any admission. Only an event **never committed** server-side (client appended locally, server never received or refused it) still carries the old `physical_instance` into `:123` and is NACKed. And per correction 5 the relaunched entry fails at the first bound observer tick, so in the production free-service client that replay path is reached at most for the ticks before the observer runs and never becomes a standing loop. Status: **latent, masked, unproved**; not a present defect card.
**Cheapest falsifier:** MODEL with the real client pump (`tests/unit/test_gen1_native_reattach_integration.py:234` style): leave one locally-appended, server-unseen observation in the store, restart the entry with fresh nonces, and record which fails first, the observer assertion (`gen1_initial_observation.lua:74`) or the NACK/revoke (`lua/client_session.lua:77-79`).

### 7. Prerequisite gates cannot be waived by a research report

**Wrong:** original §6 "Blockers: none of P2a/N0/D0 for Slice A as a record (it grants nothing)".
**Correct:** the master guide's dependency order and nine-part claim apply to every implementation card; a record-only slice is still an implementation card touching two one-writer files (`gen1_runtime.py`, `gen1_observation_loop.lua`). The sentence is withdrawn. The guide already states that P-3 (savestate load) is refused by design, that bundle migration (P-2) may stay outside scope, and that a save-only release (P-1) is an additional authority change rather than part of P2a.

## Corrected boundary summary

| Claim | Level | Status after correction |
| --- | --- | --- |
| No resume today; four server gates; immutable initial record; `context_history` seam | FACT | stands |
| First observable client failure on relaunch is `initial inventory belongs to a replaced context` with `phase="failed"` | FACT (source), MODEL pending | corrected (5) |
| Product CLI holds `.process.lock` for the emulator lifetime; bypass and launcher-death are uncovered | FACT / unverified for EmuHawk's own file handling | corrected (1) |
| Heartbeat full point only on roster fingerprint change; bank-1 SRAM invisible | FACT | corrected (2) |
| Full-image equality cannot witness a save (play time) | PRET | corrected (3) |
| Every SaveRAM flush is command-permitted; loop has no file authority | FACT | corrected (4) |
| Outbox replay loop | latent, masked, unproved | downgraded (6) |
| Slice A free of P2a/N0/D0 | withdrawn | corrected (7) |
| Exit-time BizHawk flush byte-identical to an owned flush; `image(first held point after CONTINUE) == cart_hex` | unverified PHYSICAL | unchanged |

## Genuinely unresolved policy (two items)

- **P2a:** whether a clean same-run re-enrollment is wanted at all, and if so which witness standard the owner accepts before any design: a source-pinned `SaveGameData` engine hook plus a command-permitted file receipt (both currently absent, corrections 3–4), or nothing short of the same still-running process.
- **P-1:** whether a held survivor may ever receive a save-only release. This is a new authority, separate from P2a; the default is no.

## Next owner / action

Coordinator: verify the seven citations, obtain the independent review the card requires, and record the corrected boundary in the guide. No implementation, replay or file-authority grant follows from this report; H1/Slice A stay HOLD until P2a is decided and the two missing interfaces (save witness, held file permit) are specified and reviewed as their own cards.
