# Gen 1 standard digest (what "following Gen 1" means)

> Corrected 2026-09-21 after Codex fact-check cx-2c3f2d06 (6 wrong cells, 2 overstatements); see docs/gen2/REVIEW_RECORD.md.

_Read at worktree `gen2-planning-kickoff-a18801` HEAD `4bf0f3b`. Every claim carries `path:line`;
paths prefixed `SWEEP` are read-only in `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`.
Anything I could not cite is under §5, not asserted here._

This is the checklist Gen 2 is measured against: per lifecycle stage, what Gen 1 does and the Gen 1
artifact that implements or proves it. The three evidence classes stay distinct exactly as
`docs/gen1_requirements.md:2-7` defines them — **SOURCE** (pret citation or generated-from-pret data),
**MODEL** (lupa/pytest against fakes; recorded, never closes a row alone), **PHYSICAL** (real cartridge
in BizHawk, judged by an oracle that is not the code under test).

---

## 0. The contract in one table

| Item | What Gen 1 fixed | Citation |
|---|---|---|
| Release rule | a row is done only with SOURCE **and** PHYSICAL; MODEL is recorded but never closes a row; the runner is `python tools/verify_gen1_release.py`; "a lane that did not run did not pass" | `docs/gen1_requirements.md:2-7` |
| Nothing inherited | no pre-rewrite code, data, fixture, test or doc counts as evidence | `docs/gen1_requirements.md:9-11` |
| Pins | pret/pokered `405b6246…`, pret/pokeyellow `0a08515`, clean ROM SHA-1s per title, BizHawk 2.11.1 Gambatte (`emu.framecount()` inside `event.on_bus_exec` == the armed frame), RGBDS v1.0.1, wire contract = `docs/protocol.md`, sites = `docs/gen1_engine_sites.md` + `data/games/gen1_rby/engine_signals.json` | `docs/gen1_requirements.md:15-24` |
| Oracle ENGINE | a `bus_exec` hook at a pret routine fired (or did not), expected bytes verified at load | `docs/gen1_requirements.md:28` |
| Oracle PYDEC | `server/adapters/gen1_codec.py` decodes the same raw WRAM/SRAM bytes; Lua and Python must agree | `docs/gen1_requirements.md:29` |
| Oracle GAME | the game itself: `TryLoadSaveFile` returns 2 after our SRAM write; the party-menu tilemap shows `FNT`/level/HP; the Mart/PC/receptionist screen shows the expected text | `docs/gen1_requirements.md:30` |
| Oracle SERVER | `links.json` / server status, read by pytest, not by the client | `docs/gen1_requirements.md:31` |
| Oracle CONTROL | a known-positive control: recompute a value two ways and require equality (stat rebuild from DVs) | `docs/gen1_requirements.md:32` |
| Status legend | `S` SOURCE, `M` MODEL, `P` PHYSICAL; `·` not yet, `✓` done with receipt path, `◐` partial | `docs/gen1_requirements.md:36` |
| Runner, fail-closed | a skip reads like a pass, so a skip/xfail/xpass/deselect/error fails the lane; only named `ALLOWED_SKIPS` fragments are excused, and there are deliberately no Gen 1 *input* exceptions | `tools/verify_gen1_release.py:2-9`, `:59-86`, `:277-303`, `:345-349` |
| Lanes | 19 lanes, cheapest-and-most-diagnostic first; `--quick` stops before the emulator lanes and is explicitly "not a release verdict" | `tools/verify_gen1_release.py:98-211`, `:11-28`, `:350-357` |
| Lane → requirement map | each lane prints the requirement ids it is evidence for | `tools/verify_gen1_release.py:217-237` |
| Fixtures rule (F-6) | every committed `.SaveRAM` passes the game's own checksums, loads with `TryLoadSaveFile`==2, PYDEC party == party-menu tilemap; `town` on encounter-free tiles, `battle` in grass with `BIT_NO_BATTLES`; all built from scripted play | `docs/gen1_requirements.md:51` |
| Limits list | the owner-accepted out-of-scope text, verbatim, plus the "Not in this release" list | `docs/gen1_requirements.md:153-155`, `:161-189` |
| pureRGB second foundation | same evidence bar, own pack, own lanes; X-1..X-12 | `docs/gen1_requirements.md:132-151` |

**Recorded limits, the list itself** (`docs/gen1_requirements.md:167-189`): S-3 party-full→box; S-5/D-10
key migration (SOURCE+MODEL only); W-4/D-11 rival swap if A13 is skipped; D-13 key collision (1/65536 per
pair, outbound `emit_faint` still reports the colliding key); R-3 badges/PP-Ups and the rival's name; T-1
physical at one Center only; T-3/T-4 trade evolution + save reload; D-12 HUD game-over text (overlay, not
tilemap-readable); C-3 SPC stage chip; C-4 fault injection (MODEL by construction); F-3 evolution and
capture→box sites; bag REMOVAL observed by the bag read, not a hook; S-8 statics and fishing maps; W-5 full
memorial box; **S-6 release of a boxed linked mon is not propagated (a shared-protocol gap in every
generation)**; Yellow duo/trade/panel; AP variants; durable runtime / paired checkpoints; whiteout without
a rebuildable pair; Explode Mode on a benched target; `ChangeBox`'s own save carries no witness; the panel
patch keeps AWAIT after its 90-frame timeout; the two-write bank-1 window; two-human session. Plus the two
kept-in-full limits at `:188-189` (box writes touch the game's own SRAM structures; force-faint demotion
is silent).

---

## 1. Module shape

**Lua client (`lua/gen1/`), one owner per concern:**

| File | Owns | Cite |
|---|---|---|
| `run.lua` (83) | BizHawk entry only: io shape, LuaSocket transport, HUD, frame loop; header detect → `Entry.admit` → `Entry.build` → `event.onframeend` | `lua/gen1/run.lua:1-8`, `:22-36`, `:60-64`, `:77-83` |
| `entry.lua` (423) | composition root; pack table + the literal pack-file list the release manifest derives from; hash-first admission with a pure-Lua SHA-1 and an anchors fallback; banked-WRAM read rerouting | `lua/gen1/entry.lua:1-26`, `:44-83`, `:94-129`, `:229-266`, `:274-292`, `:300-380` |
| `reads.lua` (329) | pure profile-driven decoders: charmap, party/box records, key `DDDD:OOOO:SS`, bag, badges, map, battle, stat stages; no BizHawk globals | `lua/gen1/reads.lua:1-3`, `:42-62`, `:93-122`, `:216-219`, `:221-245`, `:273-294` |
| `signals.lua` (416) | JSON-site-driven `event.on_bus_exec` registration, load-time ROM-byte anchor check, per-kind filters and point snapshots, bounded queue, synchronous `on_fire` handlers | `lua/gen1/signals.lua:1-18`, `:41-51`, `:319-396` |
| `writes.lua` (201) | every byte written to the game, behind an armed window with an optional range predicate; validate-before-first-byte | `lua/gen1/writes.lua:1-8`, `:64-86`, `:91-186` |
| `boxes.lua` (540) | PC/memorial box mutation through injected armed byte IO: SRAM bank layout, box/bank checksums, stat rebuild on withdraw, nickname encode | `lua/gen1/boxes.lua:1-11`, `:147-203`, `:304-350`, `:352-414`, `:416-466`, `:468-526` |
| `rom.lua` (233) | the two cartridge tables the client needs (dex order, base stats) plus `rom_content()` for admission | `lua/gen1/rom.lua:1-20`, `:39-97`, `:121-227` |
| `panel.lua` (281) | the companion mailbox: capability bits, observed-transition arming, pre-rendered tile pages, the SFX request byte | `lua/gen1/panel.lua:1-10`, `:16-34`, `:99-104`, `:118-163`, `:177-258` |
| `trade_overlay.lua` (207) | the 16-byte foreground lease at `wSerialPartyMonsPatchList`; generation/token handshake, staging, DONE, RELEASE | `lua/gen1/trade_overlay.lua:1-7`, `:27-33`, `:70-118`, `:120-200` |
| `client.lua` (1862) | the state machine over all of the above: hello gating, the writes gate, deferred queue, signal→event mapping, trade, HUD moments | `lua/gen1/client.lua:1-18`, `:135-168`, `:1780-1852` |
| `lua/gen1_write_safety.lua` (112) | read-only checkpoint evidence, two shapes (`gen1-main-loop-v1`, `…-purergb-v1`); explicitly not admission or payload validation | `lua/gen1_write_safety.lua:1-15`, `:23-109` |

**Server side:** `server/adapters/gen1_rby.py:265-493` is the whole Gen 1 rules+presentation binding
(`game_id` `:279-281`, gift/static areas `:283-293`, `evo_family` `:295-302`, `gender_from_key` returns
`""` `:304-306`, `is_shiny` False `:312-314`, `parse_ot_id` = middle segment `:316-317`, `party_blob_size`
66 `:335-337`, `supports_explode_mode` True `:353-354`, `supports_info_panel`/`native_trade_ui` Red/Blue
only `:360-366`, `info_panel_width` 20 `:368-370`, `memorial_box_index` = `BOX_COUNT-1` `:490-493`).
`server/adapters/gen1_codec.py` is the PYDEC oracle: `decode_party_mon` `:457`, `encode_party_mon` `:483`,
`decode_party` `:596`, `decode_box` `:606`, `key` `:611`, `decode_bag` `:623`, `sav_checksum` `:647`,
`verify_bank1` `:656`, `verify_boxes` `:669`, `calc_stat` `:705`, `level_from_exp` `:739`,
`internal_to_natdex`/`natdex_to_internal` `:754`/`:764`, and the parametrised `Gen1Layout` `:779-941`
with `recompute_stats` `:963`. `server/adapters/gen1_purergb.py:66` subclasses `Gen1Adapter` and swaps
only data + artifact-kind policy (`set_artifact_kind` `:216-218`, `_is_overlay` `:220-221`).

**Shared modules a Gen 1 binding consumes** (`docs/shared_runtime.md:13-19`): `server/state.py` (the rule
engine), `server/server.py` (transport, admission, identity), `lua/connector.lua` (framing, reconnect,
`_send_queue` cleared on disconnect), `lua/hud.lua` (sanitizer + overlay lifecycle), `server/adapters/base.py`
(the game boundary). `lua/json_codec.lua` is shared with no game facts (`docs/shared_runtime.md:47`).
Everything under `lua/gen1/` is explicitly listed as *Gen 1 modules containing reusable mechanisms* —
not bindable as-is (`docs/shared_runtime.md:37-53`). The portability test is one question:
**can Gen 3 bind it without inheriting Gen 1 game facts?** (`docs/shared_runtime.md:7-9`).

**The "no game_id branch" rule** (SWEEP `docs/gen1_reference/GEN3_BINDING_PLAN.md:296-302`): no `is_rr`,
`is_emerald` or game-id checks in `server/server.py`, `server/state.py`, `server/adapters/base.py` or
`server/pokemon_data.py` — the fix is an adapter method with an inert default. Adapters are leaf modules
(no `import server.server`), load their own data from `data/games/<gen>/`; display goes through
`self.adapter.<method>()`. The `lua/clients/` + `lua/games/` split is HISTORICAL, from that same SWEEP
plan — the rewritten Gen 1 is `lua/gen1/{entry,run,client,reads,writes,boxes,signals,rom,panel,
trade_overlay}.lua` (this digest's own §1), and `lua/slink.lua:83-85` explicitly excludes a `gen1_rby`
row from the legacy `game_detect`/client-map table because the Gen 1 route returns earlier; adapter
isolation stays the current rule. Gen 1 discharged that isolation concretely: `native_trade_ui()` replaced
the six `game_id == "gen1_rby"` branches in the shared trade FSM (`docs/shared_runtime.md:35`).

---

## 2. Per lifecycle stage

### 2.1 Enrollment: admission + hello

- **Mechanism.** Foundation is decided by ROM sha1 first (`Entry.admit`, `lua/gen1/entry.lua:229-266`),
  falling back to *anchor* admission — every engine site's and checkpoint's `expected_hex` of exactly one
  admitted pack/title/kind must read as pinned (`:176-219`); the header only narrows candidates
  (`:382-401`). A recognised vanilla header with an unknown sha1 boots the vanilla pack as kind `named`
  and is then refused downstream by site verification if wrong (`lua/gen1/run.lua:37-54`).
  Hello waits for the overworld checkpoint **or** a running battle, never merely a readable party
  (`lua/gen1/client.lua:1790-1811`), because `MainMenu` runs `TryLoadSaveFile` before the CONTINUE/NEW GAME
  choice (`docs/gen1_engine_sites.md:310`, `:428-435`).
- **Sites.** `save_witness`, `add_party_mon`, `starter_begin/end` all carry `expected_hex`
  (`data/games/gen1_rby/engine_signals.json:26-120`); the load-time check refuses to start on a mismatch
  (`lua/gen1/signals.lua:326-337`).
- **Wire.** `hello` fields and the accepted-path effects: `docs/protocol.md:69-133`. Gen 1 sends
  `ot_id`, `rom_sha1`, `rom_content`, `panel`/`panel_abi`/`sfx`, `artifact_kind`, `foundation`
  (`lua/gen1/client.lua:1529-1541`). Admission order and the `[noop]`-with-no-state-adopted rejection:
  `docs/protocol.md:99-112`.
- **Rows.** F-1 (S✓ M✓), F-2 (S✓ M✓ P✓), C-5 randomized admission (S✓ M✓ P✓ from `admit_randomized_new`),
  C-1 identity lock (M✓ P✓), R-4 hello gating (M✓ only, P·) — `docs/gen1_requirements.md:46-47`, `:96`,
  `:92`, `:60`.
- **Oracle.** SERVER (`/api/status` admission + `events.json`) for C-5; SERVER (`links.json` unchanged)
  for C-1 (`docs/gen1_requirements.md:96`, `:92`).
- **Limits.** R-4's physical leg is open (`docs/gen1_gen2_runtime_checks.md:107`).

### 2.2 Encounter (wild and trainer start)

- **Mechanism.** `battle_begin` (trainer staging, `InitBattleCommon+0`) and `wild_begin`
  (`InitWildBattle+5`) become one `self.battle` record; a trainer counts only when
  `wCurOpponent >= derived.opp_id_offset` (`lua/gen1/client.lua:913-963`). Static encounters take their
  own `static_<map>_<dex>` area id from `static_encounters.json` (`:934-944`). Demonstration battle types
  (old man 1, Yellow Pikachu 4) resolve nothing (`:101-107`, `:981-982`).
- **Sites.** `battle_begin` `InitBattleCommon` and `wild_begin`, both with `expected_hex`
  (`data/games/gen1_rby/engine_signals.json:43-50`, site list at 18 kinds); the wild-start trap that
  `LoadEnemyMonData` has **not** run at `InitWildBattle+5` is documented at `docs/gen1_engine_sites.md:204`.
- **Wire.** `trainer_battle_start{trainer_id}` (`docs/protocol.md:183`); the wild species/level ride the
  tick and the later `capture`/`no_catch` (`docs/protocol.md:173`, `:176`, `:178`).
- **Rows.** S-1 lab sequence S✓ M✓ P✓ on R/B/Y; S-2 Route 1 encounter S✓ M✓ P✓
  (`docs/gen1_requirements.md:66-67`). F-3's "battle start, trainer/wild" receipts are mapped per
  mechanism at `docs/gen1_requirements.md:48`.
- **Oracle.** ENGINE sequence vs pret script order (`docs/gen1_requirements.md:66`); ENGINE + SERVER for S-2.
- **Limits.** Pokémon Tower ghosts without the Silph Scope are not failed encounters
  (`lua/gen1/client.lua:92-99`, `:986-989`; `docs/gen1_gen2_runtime_checks.md:139-141`).

### 2.3 Capture (party vs box, the ball gate)

- **Mechanism.** `add_party_mon` / `capture_box` arm a `pending_change{kind="acquire"}` with a **freshness
  witness** — the exact bytes of the one slot the engine is about to write (party slot `wPartyCount`, or box
  slot 0 because `SendNewMonToBox` inserts at the front) — so a stale compacted record cannot be reported as
  a catch (`lua/gen1/client.lua:1015-1046`). Settling requires level written, plus maxHP for party
  acquisitions only (not boxed mons), and the same candidate key on two consecutive frames — but only when
  the acquisition is NOT already complete; an acquisition-complete witness (battle_end, past `AddPartyMon`)
  overrides the stale-byte veto and accepts the slot on the readiness checks alone
  (`lua/gen1/client.lua:1267-1273`, `:1294`), because `_AddPartyMon` runs `AskName` before the struct exists
  (`lua/gen1/client.lua:1246-1316`; source fact `docs/gen1_engine_sites.md:214`, `:418-427`). Ball
  consumption is **observed from the bag**, not hooked (`docs/gen1_engine_sites.md:225`, `:282`);
  `no_catch` is withheld while `has_pokeballs` is false (`lua/gen1/client.lua:990-994`).
- **Sites.** `add_party_mon` (bank 0 — bank gate skipped), `capture_box` = `SendNewMonToBox`,
  `bag_received` = `AddItemToInventory_.done+8` with a carry+HL+ball-class filter
  (`data/games/gen1_rby/engine_signals.json:27-42`, `:82-89`; filter at `lua/gen1/signals.lua:57-71`).
- **Wire.** `capture{key, area_id, species_id, level, hp, maxHP, nickname, gift, in_box, stats}`
  (`docs/protocol.md:176`; emitted `lua/gen1/client.lua:1310-1313`).
- **Rows.** S-2 S✓ M✓ P✓; S-3 (party full → box) S✓ only — **capture→box is MODEL by recorded limit**;
  D-2 ball gate S· M✓ P✓ (`docs/gen1_requirements.md:67-68`, `:106`, `:174`).
- **Oracle.** ENGINE + SERVER (S-2); ENGINE + PYDEC(SRAM) is what S-3 still owes.
- **Limits.** S-3 and F-3's capture→box on the limits list (`docs/gen1_requirements.md:167`, `:174`).

### 2.4 Faint and linked death

- **Mechanism, killer side.** `battle_faint` (`RemoveFaintedPlayerMon`) and `poison_faint`
  (`ApplyOutOfBattlePoisonDamage.noBorrow`) both carry a **whole-party snapshot** taken inside the hook,
  because the live party is already stale (`lua/gen1/signals.lua:81-100`); the client decodes it and emits
  `faint`, then `whiteout` when nothing survives (`lua/gen1/client.lua:896-907`, `:1003-1010`).
- **Mechanism, victim side.** Two windows only. Benched/overworld: `faint_party_slot` writes HP `0000` +
  status `00` at the verified checkpoint (`lua/gen1/writes.lua:91-96`). Active battler: queued to
  `pending_battle_writes` and applied *inside* the `MainInBattleLoop` hook — `wBattleMonHP=0`,
  `wPlayerSelectedMove=$FF`, party mirror (`lua/gen1/client.lua:494-500`, `:1368-1403`;
  `lua/gen1/writes.lua:98-105`), behind `active_faint_guard` (`wIsInBattle∈{1,2}`, `wBattleType==0`,
  `wLinkState≠4`, slot match, Transform exception) (`lua/gen1/writes.lua:39-49`).
  A target that switches out is re-queued as a plain checkpoint faint (`lua/gen1/client.lua:1397-1400`).
- **Retry-at-tail.** A `memorialize` refused as "last party mon" goes to the **tail** of the deferred
  queue, not the head, because the `party_mon` that makes it legal is queued behind it
  (`lua/gen1/client.lua:805-811`); the same tail rule with a bounded budget covers a `party_mon` refused
  "party full" during a whiteout rebuild (`:782-795`).
- **Sites.** `battle_faint`, `poison_faint`, `battle_loop_head`
  (`data/games/gen1_rby/engine_signals.json` sites list; ordering facts at `docs/gen1_engine_sites.md:232-235`,
  window at `:327-330`).
- **Wire.** `faint{key, area_id}` → server `_propagate_faint` → partner `force_faint` (or `force_explode`)
  + `play_sound 26`, both `memorialize`, entry DEAD, game-over check (`docs/protocol.md:177`, `:319-320`, `:323`).
- **Rows.** W-1 bench S✓ M✓ P✓; W-2 active S✓ M✓ P✓; D-6 both windows P✓; S-4 poison/blackout ◐
  (`docs/gen1_requirements.md:79-80`, `:110`, `:69`).
- **Oracle.** GAME (`FNT` in the party menu; faint text; `wBattleResult`) + PYDEC
  (`docs/gen1_requirements.md:79-80`).
- **Limits.** The still-open S-4 sub-clause is *ordering*: no marker isolates
  faint-time-bytes-captured-before-`HealParty` (`docs/gen1_requirements.md:69`). Force-faint demotion is
  silent — a missed loop head moves to the checkpoint queue with no NACK (`:189`).

### 2.5 PC sync (deposit / withdraw / release / ChangeBox)

- **Mechanism.** `move_mon` and `remove_pokemon` each snapshot **both** collections inside the hook
  (`lua/gen1/signals.lua:190-215`), because `_MoveMon` copies and `_RemovePokemon` shifts before the client
  drains. Classification is *where the mon is*, never a frame age — a 2-frame window once misread Bill's
  WITHDRAW as a release (`lua/gen1/client.lua:1093-1137`). Writes go through `boxes.lua` destination-first —
  target box before party removal on deposit, party before box removal on withdraw
  (`lua/gen1/boxes.lua:347-348`, `:463-464`) — so a source copy survives an interruption between the
  completed destination write and the source removal; each mutation is still multi-byte and
  `docs/gen1_requirements.md:188` keeps a process-death/save-rejection window, so this is not a
  crash-atomic or power-loss guarantee. Withdraw **rebuilds** stats from base stats + DVs + stat exp
  and the level from exp, never zeros (`lua/gen1/boxes.lua:352-390`). A read/target against an
  uninitialised non-current box is refused (`lua/gen1/boxes.lua:213`), but `boxes.memorialize` calls
  `ensure_boxes_initialised` when needed (`:487-493`), which writes the initialised backing banks,
  checksum, saved flag and WRAM flag itself (`:239-264`) with the documented two-byte saved-flag/checksum
  tear window (`docs/gen1_requirements.md:188`). `lua/gen1/client.lua:291-297` is a read-cache condition
  (the box-cache rescan treats an uninitialised SRAM box as absent), not the mutation policy.
- **stats_cache timing.** Sent immediately before executing a `box_mon` deposit
  (`lua/gen1/client.lua:758-760`; contract `docs/protocol.md:140-142`, `:150`).
- **Sites.** `move_mon` (`MoveMon`, bank 0), `remove_pokemon`
  (`data/games/gen1_rby/engine_signals.json:98-105` and the site list).
- **Wire.** `party_to_box{key, stats}` / `box_to_party{key, area_id}` up; `box_mon` / `party_mon` down with
  `sync_retrieve_done` / `sync_retrieve_failed` / `box_mon_failed` acks
  (`docs/protocol.md:180-181`, `:186-188`, `:321-322`). Keyed-command in-flight lifetime:
  `docs/protocol.md:146-150`.
- **Rows.** S-6 S✓ M✓ P✓ (deposit/withdraw/release live; ChangeBox via `changebox_new`);
  D-9 PC sync both ways S✓ M✓ P✓; W-5 box writes + checksums S✓ M✓ P✓
  (`docs/gen1_requirements.md:71`, `:113`, `:83`).
- **Oracle.** ENGINE + PYDEC of the flushed SaveRAM; GAME for W-5 ("the save reloads, Bill's PC lists it").
- **Limits.** **RELEASE of a boxed linked mon is not on the wire at all** — the client logs
  `RELEASE_SEEN` and emits nothing; the pair stays ALIVE with a phantom boxed half. This is a shared-protocol
  gap in every generation (`docs/protocol.md:203-207`; `lua/gen1/client.lua:1113-1124`;
  `docs/gen1_requirements.md:177-179`). `ChangeBox`'s own save carries no witness (`:182`).

### 2.6 Memorial (Box 12)

- **Mechanism.** `boxes.memorialize` targets `box_count - 1` (sBox12, index 11), refuses when the party
  would empty, refuses a full memorial box, and is idempotent after a completed move
  (`lua/gen1/boxes.lua:468-526`). It initialises the SRAM box banks itself when needed, writing the durable
  saved bit-7 flag and the recomputed main checksum as **two bytes only** — a full image rewrite would be a
  tear window that rejects the save on boot (`lua/gen1/boxes.lua:174-195`, `:239-265`). Bank sealing
  recomputes six per-box checksums plus the whole-bank complement (`:164-172`).
- **First-save hazard.** The game's first `ChangeBox` runs `EmptyAllSRAMBoxes` and wipes every SRAM box, so
  any SRAM-box work must gate on `BIT_HAS_CHANGED_BOXES` (`docs/gen1_engine_sites.md:264`). Gen 1's answer
  is to refuse a read/target against an uninitialised non-current box (`lua/gen1/boxes.lua:213`) while
  letting `boxes.memorialize` initialise those banks itself when it needs them (`:487-493`, `:239-264`),
  closing the window without a blanket refusal (`docs/gen1_gen2_runtime_checks.md:147-151`).
- **Wire.** `memorialize{key}` → `memorialize_done{key, box}` / `memorialize_failed{key, reason}`;
  the client acks `box = box_count - 1` (`docs/protocol.md:189-190`, `:323`; `lua/gen1/client.lua:800-814`).
- **Rows.** W-5 S✓ M✓ P✓ except the full-box refusal (MODEL by owner-approved amendment);
  D-8 memorial into Box 12 on both sides S✓ M✓ P✓ (`docs/gen1_requirements.md:83`, `:112`).
- **Oracle.** GAME + PYDEC of the flushed cartridge.
- **Limits.** Full memorial box → `memorialize_failed` is MODEL (20 memorials are not driveable);
  the two-write bank-1 window (REVIEW-BOXES-1) (`docs/gen1_requirements.md:176-177`, `:188`).
  The memorial oracle must mask bit 7 of the boxed status byte — pokered's own
  `RemoveFaintedPlayerMon` leaves `0x80` there (`docs/gen1_requirements.md:38`, INSTRUMENT entry).

### 2.7 Trade (native companion patch)

- **Mechanism.** The receptionist and trade scene are a **ROM patch**, not a Lua simulation: one replaced
  text-script dispatch covers all 12 Centers + Indigo (`docs/gen1_requirements.md:124`). The host talks to
  it through a 16-byte foreground lease at `wSerialPartyMonsPatchList` with a `SLT1` magic, version,
  command, generation/ack pair and a 4-byte visit token; the host always publishes the generation byte
  **last** (`lua/gen1/trade_overlay.lua:5-7`, `:54-67`, `:80-94`, `:120-159`). Staging borrows enemy slot 0
  and backs up the clobbered union (`:139-148`). The client drives QUERY → OFFER → PROMPT → APPLY → DONE →
  RELEASE and re-arms on clobber (`lua/gen1/client.lua:1632-1751`). Decline is a native NO answered as
  `menu_result{choice:0}` (`:1699-1702`). Writes here happen **inside the lease**, not at the overworld
  checkpoint (`docs/gen1_gen2_runtime_checks.md:134-135`).
- **Key migration.** A SLINK trade emits **no** `key_change`; the evolution hook returns early while an
  apply is armed, and `trade_done` reports the final key of the last slot
  (`lua/gen1/client.lua:1164-1166`, `:1714-1724`). That matches the protocol's MUST NOT
  (`docs/protocol.md:412-416`).
- **Wire.** `trade_request` / `show_choices` / `choose_mon` / `show_menu` / `apply_trade` / `trade_done`
  and the whole phase table: `docs/protocol.md:371-420`.
- **Rows.** T-1 receptionist S✓ M✓ P✓ (one Center physical + shared dispatch by source); T-2
  eligible/ineligible S✓ M✓ P✓; T-3 partner YES/NO/B P✓ incl. decline; T-4 apply P✓; T-5 crash mid-trade
  MODEL by construction (`docs/gen1_requirements.md:124-128`).
- **Oracle.** GAME (tilemap) + SERVER + PYDEC of both flushed saves.
- **Limits.** T-1 physical at one Center only; T-3/T-4 trade evolution and save reload stay MODEL; a
  native append returning result 2 is **held, not recovered** (`TRADE UNCERTAIN - CHECK PARTY`, no release,
  no claim) — `docs/gen1_requirements.md:171-172`; `lua/gen1/client.lua:1704-1711`;
  `docs/gen1_gen2_runtime_checks.md:142-144`. Yellow has no trade path (`docs/gen1_requirements.md:179-180`).

### 2.8 Whiteout / rebuild

- **Mechanism.** The client emits the final `faint` and then `whiteout` itself, *before* the engine's
  blackout/heal path, because `HealParty` runs last and erases the evidence
  (`lua/gen1/client.lua:889-907`; ordering source `docs/gen1_engine_sites.md:235`). The `blackout` hook only
  supplies `whiteout` if it has not already been sent (`lua/gen1/client.lua:1009-1010`;
  `docs/protocol.md:209-211`). The server plans the rebuild from boxed alive pairs, queues `party_mon`s then
  `rebuild_start`, and finishes on `rebuild_done` (`docs/protocol.md:213-219`).
- **HealParty ordering.** `ResetStatusAndHalveMoneyOnBlackout` runs first and `HealParty` is tail-jumped
  into last; the latest blackout-unique site is `ResetStatusAndHalveMoneyOnBlackout+0`, which is what the
  `blackout` site pins (`docs/gen1_engine_sites.md:235`; `engine_signals.json` `blackout` symbol
  `ResetStatusAndHalveMoneyOnBlackout`, `data/games/gen1_rby/engine_signals.json:74-81`).
- **Rows.** D-7 whiteout → `rebuild_start`/`rebuild_done` S· M✓ P✓; S-4 `whiteout` exactly once P◐
  (`docs/gen1_requirements.md:111`, `:69`).
- **Oracle.** SERVER + PYDEC (both rebuilt saves decoded back).
- **Limits.** Blackout heal of a logically dead mon before the checkpoint is a known limit (D-7's own row);
  whiteout with no rebuildable pair is the proven game-over path (`docs/gen1_requirements.md:180-181`).

### 2.9 Evolution

- **Mechanism.** The hook is the **species-publish** point inside `Evolution_PartyMonLoop`, after
  `ld a,[wLoadedMonSpecies] / ld [hl],a` — every path (level-up via `EvolutionAfterBattle`, stone, Rare
  Candy, trade) runs that loop, and a cancelled evolution leaves before it
  (`lua/gen1/signals.lua:230-239`; `docs/gen1_engine_sites.md:242-247`). The old key is found by DVs+OT
  prefix among the keys that were party members on the **last read before the signal's frame**, refusing
  rather than guessing on zero or multiple matches (`lua/gen1/client.lua:833-855`, `:1150-1186`).
  Both keys stay known until the server acks (`key_alias`), with frozen record evidence
  (nickname bytes + move set) and a latched ambiguity flag (`lua/gen1/client.lua:376-416`, `:1173-1181`).
- **Wire.** `key_change{old_key, new_key, new_species, new_nickname, reason:"evolution"}`, answered by
  `key_change_ack` or `key_change_rejected` (`docs/protocol.md:182`, `:342-343`, `:515`); a rejection
  retires the pair `identity_lost` and the client keeps a `retired_alias` so the retirement commands find
  the record the cartridge physically holds (`lua/gen1/client.lua:532-547`, `:723-737`).
- **Rows.** S-5 S✓ M✓ P· ; D-10 key migration keeps the link M✓ only
  (`docs/gen1_requirements.md:70`, `:114`).
- **Oracle.** ENGINE + GAME (new species on screen).
- **Limits.** S-5/D-10 are SOURCE+MODEL only, on the limits list (`docs/gen1_requirements.md:167-168`).
  A rejected change whose record was edited, left the party or has an indistinguishable twin is **refused**
  with a `_failed` reply, never guessed (`lua/gen1/client.lua:384-393`, `:728-732`).
  Evolution gate receipts exist (`evolution_gate_{red,blue}_2026-09-20.txt`) but flipped no cell
  (`docs/gen1_requirements.md:38`, aa8a1df entry).

### 2.10 Gift and egg

- **Mechanism.** An acquisition with `in_battle == false` is a gift and links under
  `gift_map_<map id>` (`lua/gen1/client.lua:1306-1309`). The adapter recognises the `gift_` prefix plus a
  literal gift-area set derived from every `GivePokemon` script (`server/adapters/gen1_rby.py:218-232`,
  `:283-288`); fixed-species gifts bypass the clauses (`:290-293`,
  contract `docs/protocol.md:433-436`). There is no egg in Gen 1; `is_egg_pickup_area` is a declared,
  uncalled default (`docs/protocol.md:437`).
- **Rows.** S-8's gift leg is PHYSICAL (`docs/gen1_requirements.md:73`); the starter gift pair links on
  arrival by design (D-2, owner ruling — `docs/gen1_requirements.md:106`).
- **Limits.** Statics and fishing maps stay MODEL: neither is reachable before Mt. Moon / Vermilion and
  this release's route stops at Route 1 (owner-approved amendment, `docs/gen1_requirements.md:73`, `:175-176`).

### 2.11 Interruption and recovery

- **Soft reset / WRAM clear.** `home/init.asm` zero-fills WRAM0, so `wPartyCount` and `wPlayerID` read 0
  until the save returns (`docs/gen1_engine_sites.md:428-435`). The client treats `read_player_id() == 0`
  as end-of-session: `hello_sent` cleared, `pending_change` dropped, the panel cleared, **every identity
  alias dropped** (`lua/gen1/client.lua:332-347`). Writes **pause after 5 consecutive** failed validations
  and the queue is kept, never dropped (`lua/gen1/client.lua:19`, `:348-355`).
- **Reconnect / wrong save.** A hello whose OT differs gets only
  `hud_show "[x] WRONG SAVE: slot A"` and zero state mutation (`docs/protocol.md:107`); the connection is
  ignored until an accepted hello and every later event answers `noop` (`docs/protocol.md:49`, `:101`).
  `seq` is a per-connection local, so a restarting client is never mistaken for a duplicate
  (`docs/protocol.md:48`, `:50`). `lua/connector.lua` clears the unsent `_send_queue` on disconnect so a
  stale event cannot precede the next hello (`docs/protocol.md:39`).
- **Rows.** C-1 wrong save P✓; C-2 reconnect P✓; D-14 reconnect under the rules P✓; W-6 writes gate pauses
  P✓ (the 5-failure trigger count and the `box_mon_failed` NACK stay MODEL); R-4 P·
  (`docs/gen1_requirements.md:92-93`, `:118`, `:84`, `:60`).
- **Oracle.** SERVER + GAME; the PYDEC leg requires `links.json` byte-identical across the reset.

### 2.12 HUD and panel

- **Mechanism.** Every on-screen string goes through `hud.lua`'s exported `sanitize`, which is the one
  ASCII-folding policy for both the overlay and the native panel (`docs/shared_runtime.md:18`, `:48`);
  the panel injects it as a required dependency (`lua/gen1/panel.lua:89`, `:186-188`).
  The panel is capability-gated on the mailbox beacon + `CAP_PANEL` bit, never on an ABI number
  (`lua/gen1/panel.lua:118-124`); only an **observed** non-AWAIT→AWAIT transition arms a staging
  opportunity, with a 60-frame client deadline against the patch's 90
  (`lua/gen1/panel.lua:40-43`, `:235-247`); pages are pre-rendered outside the armed window and published
  tiles → page count → STAGED last (`:177-218`). The write window is narrowed to `wTileMap` plus three
  mailbox bytes (`:99-104`), and the cart-write door refuses the panel window outright
  (`lua/gen1/entry.lua:348-351`). Local HUD moments (nuzlocke banner, `** NEW ENCOUNTER **`, KO'd text,
  game-over/whiteout cue) mirror the Gen 3 client (`lua/gen1/client.lua:265-274`, `:945-961`, `:1552-1563`).
- **Wire.** `link_panel{rows}` is a payload, not permission to paint (`docs/protocol.md:347-357`).
- **Rows.** C-6 local HUD/SFX moments MODEL only — no live oracle can read a transient overlay back
  (`docs/gen1_requirements.md:97`); D-12 game-over HUD stays ◐ for the same reason (`:116`).
- **Limits.** HUD lifecycle notices are explicitly out of this release (`docs/gen1_requirements.md:155`).
  BizHawk exposes its Lua API as userdata, so guards must be presence checks through `pcall`
  (`docs/gen1_requirements.md:38`, HUD-5 entry).

### 2.13 Native sound

- **Mechanism.** The server speaks Gen 3 SE ids; the Gen 1 binding lives in the client.
  `SFX_CODE_FOR_GEN3_ID = {25→1, 26→2, 22→3, 95→1}` and the code is written to the mailbox `+7`
  request byte only when it reads 0 — the ROM clears it when it plays, and overwriting a held request
  would lose it (`lua/gen1/panel.lua:19`, `:31-33`, `:144-151`). Requests queue up to 4, oldest dropped,
  one per frame (`:34`, `:156-163`, `:220-229`). One gate covers server `play_sound` and every local
  moment, with same-frame coalescing per semantic code and `config.native_sounds` + `sfx_present()`
  required (`lua/gen1/client.lua:447-478`).
- **Sites.** Two main-thread service points; the SFX byte is serviced from `panel:service()`, called
  **first** each frame because the player is in the START menu with the checkpoint long behind them
  (`lua/gen1/client.lua:1782-1787`).
- **Wire.** `play_sound{sound:int}` with the Gen 1 mapping documented in the protocol itself
  (`docs/protocol.md:328`, `:497`).
- **Rows.** No dedicated row; capability is advertised per **cartridge** in the hello (`sfx`)
  (`lua/gen1/client.lua:1539`), and the companion gate pinned `caps=0x02` (panel advertised, SFX
  deliberately not) on the Blue patched cartridge (`docs/gen1_requirements.md:124`).

---

## 3. Harness

**Fixtures (the F-6 rule).** Two kinds per title, both from scripted play, never written byte-wise:
`town` = `lab,save` (Oak's Lab after the rival, encounter-free tiles) and `battle` =
`lab,parcel,route1,save` (Route 1 at (10,35), one Poké Ball in the bag) — `tools/gen1_fixtures.py:10-12`,
`:40`; rule text `docs/gen1_requirements.md:51`, `docs/gen1_gen2_runtime_checks.md:44-54`.
`--qualify` re-checks every committed save with no emulator: the game's own checksums, a decodable party,
and exp consistent with the level on the species' growth curve (`tools/gen1_fixtures.py:17-19`, `:90`,
`:160-193`). The `LEGACY` escape set is now empty (`tools/gen1_fixtures.py:66`), so no fixture hides behind
a blanket tolerance. 14 `.SaveRAM` files ship, including `*_town_ot2` for the wrong-save leg and six
pureRGB ones (`tests/fixtures/gen1/*.SaveRAM`, listed at HEAD `4bf0f3b`).
Qualification uses a *band*, not equality, for stored stats: `CalcStats` runs not only on a level change
but also at `AddPartyMon`, box withdrawal, evolution, and the vitamin/Rare Candy path, and stat exp can
grow between those events, hence the band rather than a single recompute (`tools/gen1_fixtures.py:134-145`;
`docs/gen1_requirements.md:38`, H-8 entry).

**Live gates.** `live-new-gates` boots the selected titles (`SLINK_GEN1_ROMS`, default red/blue/yellow —
`tools/verify_gen1_release.py:129-138`) against `town`/`battle` targets in EmuHawk, runs
`lua/tests/test_gen1_inspect_gate.lua`, and requires Lua-on-hardware and the Python codec to agree field
for field on the same dumped bytes; plus three scripted New Game runs with ordinary buttons
(`docs/gen1_gen2_runtime_checks.md:32-38`; `tests/live/test_gen1_new_gates.py:32-47`). The `_ot2` wrong-save
fixture and the six pureRGB fixtures are exercised by their own named lanes/scenarios
(`inspect-purergb` and its scenarios), not by this lane's default selection.
`live-gates` is the companion patch (VBlank hook, mailbox, START-menu row, panel on a randomized+injected
ROM) `:123-128`; `live-trade-gates` is the receptionist `:157-163`.
Driver rules that were learned the hard way: no `console.log` per frame; re-pulse native menus on the
16-frame cadence because `HandleMenuInput` polls one snapshot per loop; gate on the drawn FIGHT row, not
`wTextBoxID` (`docs/gen1_engine_sites.md:464-470`).

**Duo scenarios — the 18 `gen1_new` names** (`tools/e2e_duo.py:73-184`): `link_new`, `deadzone_new`,
`linked_faint_bench_new`, `linked_faint_active_new`, `reconnect_new`, `ball_gate_new`, `trade_new`,
`soft_reset_new`, `trade_decline_new`, `explode_new`, `pc_ops_new`, `changebox_new`, `whiteout_new`,
`type_clause_new`, `species_clause_new`, `poison_new`, `rival_swap_new`, `admit_randomized_new`.
`gen1_new` is **opt-in**: only runs that name it select it (`tools/e2e_duo.py:205-206`).
Every scenario names an `oracle`; a `gen1_new` scenario with **no** oracle entry FAILS rather than
fabricating a PYDEC PASS (`tools/e2e_duo.py:4137-4149`; contract `docs/shared_runtime.md:59`).
The save witness (S-7) runs for **every** `gen1_new` scenario before its own oracle
(`tools/e2e_duo.py:4148-4149`). RNG-class failures earn bounded whole-run retries; the attempt limits are a
partial summary — per-scenario, `ball_gate_new` is not retried (limit 1), `species_clause_new` allows 8,
`explode_new` and `poison_new` allow 4 each, and every other `gen1_new` scenario defaults to 3
(`tools/e2e_duo.py:402-417`). `retryable_gen1_rng` (`:359-392`) gates which of those attempts a CAUSE_RNG
failure may actually use: the first two attempts are allowed unconditionally, and later attempts are
allowed only for specific hunt-budget cases, subject to the result-class mix and the overall limit above
(`docs/gen1_requirements.md:38`, bf22342 entry).

**Receipts convention.** Committed under `tests/fixtures/gen1/receipts/`, three files per duo scenario —
`<name>_a_result.txt`, `<name>_b_result.txt`, `<name>_pydec_result.txt` — but that triplet is not the only
receipt kind: `git ls-tree -r --name-only 4bf0f3b -- tests/fixtures/gen1/receipts` gives **119** tracked
paths at HEAD `4bf0f3b` (96 `.txt`, 17 `.log`, 5 `.png`, 1 `.lua`).
They are cited by **marker text**, not line number, because a lane run regenerates them
(`docs/gen1_requirements.md:38`, a7ea4cf entry). A run whose receipts are not committed flips no cell
(`docs/gen1_requirements.md:38`, H-2 entry). `patch/build/…` paths are gitignored and are not receipts.

**Release runner lanes** (19, `tools/verify_gen1_release.py:98-211`): `unit`, `rom-layout`, `lua-parse`,
`profile-addresses`, `profile-generated`, `profile-generated-purergb`, `statics-generated`, `fixtures`,
`patch-build` (fast); `live-gates`, `live-new-gates`, `inspect-purergb`, `apex-purergb`,
`live-trade-gates`, `inspect-purergb-overlay`, `live-trade-gates-purergb`, `apex-refusal-purergb`,
`duo-pairs`, `duo-pairs-purergb` (slow, `_SLOW` at `:55-57`). "Give it the machine": the emulator lanes are
wall-clock sensitive and a competing unit run has been observed turning a 65-second scenario into a
1500-second timeout (`tools/verify_gen1_release.py:30-35`).

---

## 4. Gate format (the template Gen 2 phases must use)

From `docs/purergb/PLAN.md:46`, the phase table columns are exactly:

| Phase | Scope (plan §) | Exclusive files | Exit evidence (standing gates) | HUMAN GATE — what the owner sees and signs | Est. |

The standing rules that come with the format (`docs/purergb/PLAN.md:39-44`):

1. A phase starts only when the previous gate is **signed by the owner in chat**; the signature is recorded
   as `G<n>: <commit sha> — <evidence links>`. No implicit carry-over.
2. Gate evidence is the **standing gates only**: unit suite, `tools/lua_syntax_check.py`, `ruff`, and the
   affected `tools/verify_gen1_release.py --lane <name>` run. The one exception is a shared `server/`
   change, which additionally takes `slink-adapter-guard` plus one independent review.
3. Every gate hands the owner something **runnable or inspectable** — a CI run, a generated pack diff, a
   live duo, a playable ROM — never a status sentence.
4. A failed gate returns the phase to its worktree; the plan is amended, not the gate.
5. Each phase is a separate worktree; parallel phases get per-lane run-config/SaveRAM/port isolation.

`§13.1` is the gate ledger: one row per gate with `Gate | Signed | Tree | Evidence`, and the "Signed"
cell quotes the owner's chat ruling verbatim (`docs/purergb/PLAN.md:61-72`). What is explicitly *not*
human-gated: intermediate commits inside a phase, fixture regeneration, worker dispatch within claimed
files, re-running an unchanged-input gate. What is **always** gated: everything in the gate column, any
change to a closed owner decision, any push, and the release claim (`docs/purergb/PLAN.md:59`).

The per-generation *binding plan* shape Gen 2 should copy is
SWEEP `docs/gen1_reference/GEN3_BINDING_PLAN.md`: §1 what the generation has today (client size, adapter,
loop, existing gates), §2 ordered binding steps each naming **bound modules / replaced code / stays in the
adapter / gate that must keep passing / effort class / risk** (`:77-289`), §3 what must not move into the
shared layer (`:291-324`), §4 open owner decisions (`:326-355`), §5 client lines per concern with a
"goes to shared / adapter / split" column (`:357-399`). The behaviour comparison is a sibling document with
a verdict key of **match / exceeds / diverges / missing / n/a**, one row per feature
(SWEEP `docs/gen1_reference/GEN3_STANDARD_COMPARISON.md:112-140`). The release checklist renders the
manifest rather than restating it, with a summary-by-stage table (`Stage | Description | Registered |
Missing | Closure plan`) and `registered` explicitly *not* meaning passed
(SWEEP `docs/gen1_reference/RC_CHECKLIST.md:3-26`).

---

## 5. Open questions

1. **Site count drift.** `docs/gen1_requirements.md:47` and `:98` say "17 sites" / "17 pinned"; the shipped
   `data/games/gen1_rby/engine_signals.json` carries **18** per title
   (`add_party_mon, bag_received, battle_begin, battle_end, battle_faint, battle_loop_head, blackout,
   capture_box, evolve, move_mon, npc_trade, npc_trade_done, poison_faint, remove_pokemon, save_witness,
   starter_begin, starter_end, wild_begin`). I could not find the commit that added the 18th or a ledger
   note reconciling the count.
2. **Lane count drift.** `docs/gen1_gen2_runtime_checks.md:19-30` says 12 lanes;
   `tools/verify_gen1_release.py:98-211` defines 19 (pureRGB lanes added). The doc is stale.
3. **Fixture status drift.** `docs/gen1_gen2_runtime_checks.md:56-60` still calls Yellow's two fixtures
   LEGACY; `docs/gen1_requirements.md:51` and `tools/gen1_fixtures.py:66` (`LEGACY = set()`) say the set is
   empty and Yellow was rebuilt from scripted play. The doc is stale.
4. **RC_CHECKLIST read only partially.** I read its preamble and stage table
   (SWEEP `docs/gen1_reference/RC_CHECKLIST.md:1-40`) and its section headings; I did not read the 388
   requirement rows, so I make no claim about individual rows there. Note the two manifests disagree in
   kind: that 388-row manifest is the *RC-era* contract, while `docs/gen1_requirements.md` is the
   post-rewrite one — I could not find a document stating which supersedes which for Gen 2's purposes.
5. **Conformance checklist count.** `docs/protocol.md:520-598` numbers items 1..47 plus `38a`/`38b`,
   i.e. 49 assertions; the file states no total, and `tests/unit/test_protocol_conformance.py` named at
   `:522` does not exist (`docs/gen1_requirements.md:38` records that correction — the work lives in
   `test_protocol_schema.py` + `test_gen1_client.py`).
6. **No Gen 2 evidence read.** Everything above is Gen 1. `docs/gen1_gen2_runtime_checks.md:14` says the
   Gen 2 sections are unchanged; I did not read them (out of the brief's line range), so this digest says
   nothing about what Gen 2 has today.
7. **Egg / daycare.** Gen 1 has no egg; a `daycare_withdraw` site and client branch exist
   (`lua/gen1/signals.lua:222-229`, `lua/gen1/client.lua:1073-1078`, `:1348-1358`) but I found no
   requirement row and no committed receipt for them — they appear to be pureRGB-only (PLAN §4 row 24).
8. **`hud.lua` line citations** are taken from `docs/shared_runtime.md:18`, `:48`; I did not open
   `lua/hud.lua` itself, so the sanitize line range (`:68-86`) is second-hand.
