# Gen 1 as the standard: row-by-row comparison with the current Gen 2 code

> Corrected 2026-09-21 after Codex fact-check cx-10a9cf49 (17 wrong cells, 3 overstatements,
> stale items); see docs/gen2/REVIEW_RECORD.md.

Written 2026-09-21 in worktree `gen2-planning-kickoff-a18801` at HEAD `4bf0f3b`, from a
read-only survey of the Gen 1 rewrite (`lua/gen1/*`, `docs/gen1_requirements.md`,
`docs/gen1_engine_sites.md`, `docs/protocol.md`) and of every Gen 2 artefact in the tree
(`lua/clients/gen2_crystal_client.lua`, `lua/games/gen2_crystal.lua`, `lua/memory_gb.lua`,
`server/adapters/gen2_crystal.py`, the Gen 2 tests, the four research notes). No code changed.

**Evidence rule, applied throughout.** Gen 1 cells carry the class the row actually reached in
`docs/gen1_requirements.md` (`S` SOURCE, `M` MODEL, `P` PHYSICAL) with the row id. Existing Gen 2
code is a **hypothesis, not evidence**: a Gen 2 cell reads `MODEL` only where a unit or live test
in this tree exercises the mechanism, and `none` otherwise. The Gen 2 live gates
(`tests/live/test_gen2_gates.py:43-48`) and duo scenarios (`tests/e2e/test_duo_gen2.py:50`) are
recorded as **"PHYSICAL on the old client, not admissible for the rewrite"**: the fixture is
staged rather than played (`lua/tests/gen2_playthrough.lua:283-298` writes a level-5 Totodile
straight into `wPartyMon1` "rather than driving Elm's lab"), and no oracle independent of the
client judged the result — there is no Gen 2 analogue of PYDEC, so the client is both the
instrument and the witness. **MODEL never closes a row** (`docs/gen1_requirements.md:5-7`).

## 0. Summary

1. Gen 2 has no engine signals at all. Every event is a WRAM diff on a frame callback
   (`gen2_crystal_client.lua:801-978`); Gen 1's whole detection layer is `bus_exec` at pinned
   pret routines with expected bytes verified at load (`lua/gen1/signals.lua:1-18`).
2. Gen 2 has no admission, and its identity is **inferred, not reported**. The hello carries no
   `ot_id`, no `rom_sha1` and no `rom_content` (`gen2_crystal_client.lua:539-568`), so the server
   falls back to the OT parsed out of the first party key (`server/state.py:989-1015`;
   `Gen2CrystalAdapter.parse_ot_id`, `server/adapters/gen2_crystal.py:286-294`) and **does** reject
   a different OT as `WRONG SAVE`. What is missing is reliability, not the mechanism: the fallback
   is absent for an empty party and wrong under an in-game trade, a party reorder or two saves that
   share an OT. Admission itself is the real gap — `Gen2CrystalAdapter` never overrides
   `rom_content_fingerprint` (`server/adapters/base.py:403-415`), so randomized-cartridge admission
   cannot happen at all.
3. Gen 2 has no write-safety checkpoint. `force_faint` is executed the frame it arrives
   (`gen2_crystal_client.lua:256-267`) and writes party HP only (`lua/memory_gb.lua:833-837`) —
   no status clear, no battle-struct write, so the Gen 1 W-2 lesson written in that very file
   (`lua/memory_gb.lua:812-832`) is unapplied to Gen 2.
4. Four events the server's rules depend on are absent or under-filled: no `battle_end`/result,
   no `trainer_battle_start`, no party-full `capture{in_box}`, and `no_catch` with no
   `species_id` (`gen2_crystal_client.lua:964-972`) — which makes the **failed-encounter reroll
   path** inert (`server/state.py:1922+`). Capture-time duplicate checking still runs, because the
   old client does send `species_id` on a capture (`:646-654`; `server/state.py:1527-1538+`).
5. Every native feature the owner wants in RC1 (O-4) is missing: no trade, no panel, no sound
   (`SFX_DISPATCH_ADDR = nil`, `lua/games/gen2_crystal.lua:228`). The peer ghost is **not** an RC1
   item — O-13 puts it after RC with design research now (`docs/gen2/REVIEW_RECORD.md:24`).
6. There is no Gen 2 Python codec twin, no requirements ledger, no release runner, no fixture
   grown from play, and no unit test of the client's event logic at all.
7. What Gen 2 got right is real and should be re-proved, not re-derived: the split Special, the
   32-byte box struct and its stats-cache consequence, the `wScriptRunning` safe-state
   measurement, the Apricorn ball ids, the memorial-box deferral.

## 1. The two engines

| Fact | Gen 1 | Gen 2 | Cite |
|---|---|---|---|
| Party struct | 44 B, OT/nick in parallel arrays (blob 44+11+11 = 66 B) | **48 B** (held item, happiness, pokerus, caught data, split Special), OT/nick still parallel (blob 48+11+11 = 70 B) | `lua/memory_gb.lua:672-677`; `research/pret_gen2_symbols.md:25-43`; `server/adapters/gen2_crystal.py:160-167` |
| Box struct | first 33 B of the party struct (carries HP + status) | **32 B**, ends at `MON_LEVEL` +31; `MON_STATUS` is +32 and `MON_HP` +34, both **outside** the box record | `research/pret_gen2_symbols.md:36-41` |
| Consequence | a boxed Gen 1 memorial can read HP0000/status00 (`docs/gen1_requirements.md:79`) | a Gen 2 memorial record **cannot express "dead"** at all. Cached stats are **not** the only withdrawal path: the game's own box-to-party transfer calls `CalcMonStats` (`engine/pokemon/move_mon.asm:654-672`, both repos), so stats are recoverable from level + DVs + stat exp. The old client's refusal without its `stats_cache` is an **old-client limitation, not a Gen 2 fact** | `lua/memory_gb.lua:698-726`; `gen2_crystal_client.lua:1282-1296`, `:1344-1348`; `engine/pokemon/move_mon.asm:654-672` |
| Boxes | 12 × 20, per-box + all-box SRAM checksums the client recomputes | **14 × 20**, `BOX_LENGTH` 0x450, **no per-box checksum the client must recompute** — the main and backup `SaveChecksum` ranges cover `sGameData..sGameDataEnd` and exclude the backing-box records. That is a statement about those two ranges only; it does **not** mean Gold's entire bank 3 is unchecksummed, and the backup-save spans that share bank 3 in Gold are a separate question (`layout.link:298-306`) | `lua/gen1/boxes.lua:26,168-199`; `research/pret_gen2_symbols.md:72-76`; `pokegold/layout.link:298-306` |
| Memorial box | Box 12 = `box_count - 1` (`sBox12`) | Box 14 = index 13, flat CartRAM `0x79E0` (`sBox14 = $A000 + 6*$450 = $B9E0`, bank 3) | `lua/gen1/boxes.lua:476`; `gen2_crystal_client.lua:700`; `lua/memory_gb.lua:1413`; `docs/gen2/REVIEW_RECORD.md:39`; `research/pret_gen2_symbols.md:70` |
| Save hazard | `EmptyAllSRAMBoxes`; the rewrite does **not** wait for the game — `lua/gen1/boxes.lua:487-493` calls `ensure_boxes_initialised`, which writes the banks, the per-bank and whole checksums and the initialised flag itself (`:239-264`), subject to the two-write tear window recorded at `docs/gen1_requirements.md:188` | `_SaveGameData → SaveBox` copies the **active** `sBox` over its backing slot; the erasure path is `ErasePreviousSave → EraseBoxes` (`engine/menus/save.asm:360-366`), reached from `AskOverwriteSaveFile` (`:181-199`) and from `HallOfFame_InitSaveIfNeeded` (`:470-475`). Only the latter tests `wSavedAtLeastOnce`; that is not a universal guard on the erase | `lua/gen1/boxes.lua:239-264,487-493`; `docs/gen1_gen2_runtime_checks.md:147-151`; `pokecrystal/engine/menus/save.asm:181-199,360-366,470-475`; `docs/gen2/REVIEW_RECORD.md:38,41` |
| Special | one stat | **split** Sp.Atk +0x2C / Sp.Def +0x2E | `lua/games/gen2_crystal.lua:144-148`; `research/pret_gen2_symbols.md:42` |
| Held items | none | present, +0x01, forwarded on capture and in party snapshots. Owner ruling **O-14**: held items are carried across a SLink trade (mail is a recorded limit, Time Capsule is out) | `lua/games/gen2_crystal.lua:136`; `gen2_crystal_client.lua:433-435,657-660`; `docs/gen2/REVIEW_RECORD.md:25` |
| Species ids | internal index ≠ dex; needs `internal_to_natdex` | **id == National Dex order**, 1..251 contiguous, `MEW` 0x97 → `CHIKORITA` 0x98 | `docs/gen1_requirements.md:50` (F-5); `research/pret_gen2_symbols.md:191`; `lua/games/gen2_crystal.lua:20-25` |
| Map addressing | 1 byte `wCurMap` | 2 bytes `wMapGroup`:`wMapNumber`, composite `g*256+n` | `lua/games/gen2_crystal.lua:595-610` |
| Console mode | DMG | Crystal is **CGB-only** (`rgbfix -C`); Gold/Silver dual-mode and BizHawk `Auto` boots them CGB. WRAM is banked — SVBK `$FF70`, and **many profiled `$Dxxx` values require the intended WRAMX bank; each symbol's bank must be determined from the pinned build, not assumed**. Plenty of Gen 2 WRAM is WRAM0 (`pokecrystal/ram/wram.asm:1,9,112,199,301,311` are all `WRAM0` sections), and the banking differs between titles: Gold's `wBattleResult` sits in `$Cxxx` (`pokegold/ram/wram.asm:1875`, inside a `WRAM0` section) while Crystal's is in `WRAMX` (`pokecrystal/ram/wram.asm:2394`, section `"More WRAM 1", WRAMX` at `:2329`) | `research/rom_hashes.md:82-86`; `research/bizhawk_gambatte_gbc.md:159-195`; `gen2_crystal_client.lua:1056-1066` |
| SRAM in BizHawk | 4 banks, flat `CartRAM` = every bank concatenated, `rambanks * 0x2000` = 0x8000 total (†derived, not observed live) | same core, same fact | `research/bizhawk_gambatte_gbc.md:60-82` |
| Clean ROM sha1 | Red/Blue/Yellow pinned in `data/pret_rom_syms.json` | Gold `d8b8a360…`, Silver `49b163f7…`, Crystal 1.0 `f4cd194b…`, Crystal 1.1 `f2f52230…` — **present in pret's `roms.sha1`, absent from this repo's data** | `docs/gen1_requirements.md:20`; `research/rom_hashes.md:52-98,108-129` |
| `bus_exec` availability | proven pattern | Gambatte implements `IDebuggable` for GBC too; unscoped hooks get the raw CPU address, scoped `"ROM"`/`"SRAM"`/`"WRAM"` get bank-resolved ones. Frame alignment inside the hook is †unverified for CGB | `research/bizhawk_gambatte_gbc.md:91-136,138-157` |

## 2. Row by row

Evidence-class key: `S` SOURCE, `M` MODEL, `P` PHYSICAL, `·` none. Where a row cites more than one
requirement id, each id carries its own `S/M/P` triple — a paired row never lends its grade to the
other id.

The Gen 2 evidence column **caps at `M` by construction**, and anything that only ever passed on the
old client lives in the separate "Historical run" column so a `P` label can never be machine-read as
a `P` cell. `—` in that column means there is no historical run to record.

| # | Behaviour | Gen 1 mechanism + class | Gen 2 evidence (admissible for the rewrite: MODEL at most) | Historical run (old client, inadmissible) | Gap |
|---|---|---|---|---|---|
| 1 | **Admission (sha1, anchors)** | `Entry.sha1` over the running ROM, matched case-insensitively against every pack's admission table; randomized artifacts admitted by engine-site **anchors** instead; `admitted_by` is `"sha1"` or `"anchors"` (`lua/gen1/entry.lua:89-228`). Server side: `rom_content_fingerprint` compared to the run contract (`docs/gen1_requirements.md:96`). **S✓ M✓ P✓ (C-5, X-5)** | ROM **title string only** — `PM_CRYSTAL`/`AP_CRYSTAL`/`POKEMON_GLD`/`POKEMON_SLV`, plus `title:find("CRYSTAL")` as a catch-all (`lua/games/gen2_crystal.lua:540-556`). No hash anywhere; `Gen2CrystalAdapter` inherits `rom_content_fingerprint → None`, which the server treats as "admit" (`server/adapters/base.py:403-415`; `docs/protocol.md:101`). **·** | — | Total. Any Crystal-titled ROM, randomized or corrupt, is admitted. The clean sha1s exist upstream (`research/rom_hashes.md:52-98`) and are simply not in the repo. |
| 2 | **Hello identity (`ot_id`)** | `ot_id = reads.read_player_id()` on every hello, plus `rom_sha1` and `rom_content` (`lua/gen1/client.lua:1513-1535`, `:151`); a different OT ⇒ `WRONG SAVE`, zero mutation. **M✓ P✓ (C-1)** | The hello has **no `ot_id`, no `rom_sha1`, no `rom_content`** (`gen2_crystal_client.lua:539-568`). `M.readPlayerId` exists and is never called (`lua/memory_gb.lua:765`). Identity is therefore **inferred from the lead mon**: the server falls back to the OT parsed out of the first party key and rejects a different OT as `WRONG SAVE` (`server/state.py:989-1015`; `Gen2CrystalAdapter.parse_ot_id`, `server/adapters/gen2_crystal.py:286-294`; `docs/protocol.md:106`). **·** (the adapter's `parse_ot_id` itself is M: `tests/unit/test_gen2_adapter.py:114-127`) | — | Wrong-save rejection is **possible but unreliable**, not absent: it is unreachable before the first mon (empty party ⇒ no OT at all), it moves with the lead slot under a party reorder, an in-game-trade mon in the lead slot reports the *wrong* trainer (the exact Gen 1 bug `server/state.py:985-988` records), and two saves sharing an OT are indistinguishable. The admission half — no `rom_sha1`, no `rom_content`, no `rom_content_fingerprint` — is the part that is missing outright. |
| 3 | **Overworld write checkpoint** | CPU parked in `DelayFrame` from `OverworldLoop`, idle; `writes.lua` refuses any byte outside an armed window (`lua/gen1/writes.lua:1-8`). **S✓ M✓ P✓ (W-7, X-6)** | `M.isInOverworld()` = not in battle ∧ `wScriptRunning == 0` (`lua/memory_gb.lua:634-639`; `lua/games/gen2_crystal.lua:83-93`). Claimed as "measured, not guessed", but the claim rests on a **profile comment** (`lua/games/gen2_crystal.lua:83-93`) and a **probe script** (`lua/tests/probe_gen2_safestate.lua`) — there is no committed receipt behind it, so the measurement itself is **†unverified**. It gates box/party/memorialize only (`gen2_crystal_client.lua:1258`). **M** via `lua/tests/probe_gen2_safestate.lua` (a probe, not an assertion) | — | No CPU-state predicate, no "no byte lands outside the window" invariant, and `force_faint` bypasses the gate entirely (row 10/11). |
| 4 | **Wild battle start** | `InitWildBattle+5` / `_InitBattleCommon` bus-exec with species and level staged; `wild_begin` kind (`lua/gen1/signals.lua:141-143`; `docs/gen1_engine_sites.md:198`). **S✓ M✓ P✓ (S-2)** | `wBattleMode` poll, 1-frame debounce, `battle_is_wild = M.isWildBattle()` (`gen2_crystal_client.lua:1162-1178`; `lua/memory_gb.lua:608-619`). No wire event — the battle only shows up inside the next `tick` (`:599-611`). **·** | — | No `species_id`/`level` latch at battle start, so the server's dupes-at-encounter prompt (`docs/protocol.md:166`, tick row) has nothing to read. |
| 5 | **Trainer battle start** | The **installed** site is `engine_signals.json sites.battle_begin` = `InitBattleCommon`, `capture_offset 0` (`lua/gen1/signals.lua:141` binds `S.KINDS.battle_begin`); `InitBattleCommon+$46` is a research candidate, not what ships. `wCurOpponent` = class + 200; `trainer_battle_start{trainer_id}` drives `replace_rival_team` (`docs/protocol.md:166`). **W-4 S✓ M✓ P✓; D-11 S· M✓ P✓** (`docs/gen1_requirements.md:82,115`) | **Not implemented, and the client says so** — "NOT YET IMPLEMENTED (Gen 1 has them): trainer_battle_start / rival_team_replaced … none of which are in the profile yet and none of which should be guessed from their Gen 1 offsets" (`gen2_crystal_client.lua:40-43`). Trainer class/id are read for *display* only (`:556-564`). **·** | — | Rival Team Swap is unreachable on Gen 2. |
| 6 | **Battle end + result** | `EndOfBattle` with `wBattleResult` decoded (0 win/flee, 1 player faint, 2 run **or** capture) (`docs/gen1_engine_sites.md:198`, §3a/§3c; `lua/gen1/signals.lua:143`). **F-3 S✓ M· P◐** (`docs/gen1_requirements.md:48` — the battle-end leg has a receipt, the S-1 differential gate over the whole site table does not). The "throw latch" is **historical wording**: there is no throw site in the installed 18 (`engine_signals.json`), and the current client derives capture-vs-run from its own battle state (`lua/gen1/client.lua:978-997`) | `wBattleMode` returns to 0; the client sets `post_battle_frames = 15` and a `pending_safe` flag (`gen2_crystal_client.lua:1189-1194`), emits `safe` on the first overworld frame (`:1427-1436`), and **never reads `wBattleResult`**. **·** | — | No win/lose/draw on the wire. Per `docs/gen2/REVIEW_RECORD.md:42`, a **transient LOSE** in `wBattleResult` is not a whiteout, so a future Gen 2 reader must not treat the bit as one. |
| 7 | **Capture → party** | The **vanilla** pack pins a single **entry** site, `engine_signals.json sites.add_party_mon` = `AddPartyMon` `capture_offset 0` — there is no begin/end pair here. `lua/gen1/signals.lua:175-180` *defines* typed `capture_party_begin`/`_end` and `capture_box_begin`/`_end` kinds, but those are bound by other packs; the kinds must not be merged across foundations. Settling is done by the client's readiness predicate, not by a pairing: a witness veto that only applies while `not acquisition_complete` (`lua/gen1/client.lua:1271-1273`) plus the same **candidate key** on two consecutive frames with a non-zero level (`:1294-1295`). **S-2 S✓ M✓ P✓** (`docs/gen1_requirements.md:67`) | New key in the party diff; `is_gift = not in_battle` (`gen2_crystal_client.lua:829-835`, `:637-675`). Carries species/level/hp/maxHP/nickname/held item/`is_egg`. **·** | — | Gen 2's naming screen has the same window Gen 1 was bitten by (`docs/gen1_requirements.md:67`, the `850f9f5` fix) and no two-frame stability check exists here. `area_id` comes from `last_area_id`, not the latched `battle_area_id` (`:643`). Owner policy the rewrite must encode: eggs hatch as **gift captures under `gift_daycare`** (O-15), roamers are a standalone **`legend_<species>`** pair that never consumes or locks the map (O-17), and the Bug Contest is its own capture zone **`national_park_contest`** (O-18) — `docs/gen2/REVIEW_RECORD.md:26,28,29`. |
| 8 | **Capture → box (party full)** | One **entry** site, `engine_signals.json sites.capture_box` = `SendNewMonToBox` `capture_offset 0` — again not a begin/end pair (the `capture_box_begin`/`_end` kinds at `lua/gen1/signals.lua:178-180` belong to other packs). The caught mon is inserted at box index **0**, not appended (`docs/gen1_engine_sites.md:198` §3b). Box readiness is the same predicate minus the maxHP clause — a box record has no party maxHP to wait on (`lua/gen1/client.lua:1294`). **S-3 S✓ M· P·** (`docs/gen1_requirements.md:68`; M and P are on the limits list, `:167`) | `scan_current_box()` runs in the post-battle grace window and **only seeds `all_known_keys`** — it emits nothing (`gen2_crystal_client.lua:680-697`, called at `:838-840`). No `capture{in_box:true}` is ever sent. **·** | — | A party-full catch is invisible to the server on Gen 2. `in_box` is required by `docs/protocol.md:166` (capture row) to stop a redundant `box_mon`. |
| 9 | **Ball gate / bag ball count** | `bag_received` bus-exec at `AddItemToInventory_` with destination, success flag and ball-id filter; consumption observed from the bag by owner-approved amendment (`lua/gen1/signals.lua:57`; `docs/gen1_requirements.md:67`). **S-2 S✓ M✓ P✓; D-2 S· M✓ P✓** (`docs/gen1_requirements.md:67,106` — D-2 has no SOURCE cell of its own) | Polled bag read every frame, `hasPokeballs()`/`countPokeballs()` over a 12-entry ball pocket (`gen2_crystal_client.lua:1227-1232`; `lua/memory_gb.lua:572-601`). The ball id list is **derived from pret's BALL pocket**, with `LIGHT_BALL` deliberately excluded and the old wrong Apricorn ids documented (`lua/games/gen2_crystal.lua:28-53`). **M** (`tests/unit/test_gen2_ball_items.py`) | — | No receipt hook, so no "the gate opened at this instant" evidence; a poll cannot distinguish "received" from "already had". Closest Gen 1 analogue, and the cheapest row to port. |
| 10 | **In-battle `force_faint`** | Write `wBattleMonHP = 0` **and** `wPlayerSelectedMove = $FF` at `MainInBattleLoop+0`, behind `active_faint_guard` (in-battle, battle type, link state, member match, Transform) with a silent demotion to the checkpoint queue on a miss (`lua/gen1/writes.lua:36-49`; `lua/gen1/signals.lua:110-112`; `lua/gen1/client.lua:754-756`). **W-2 S✓ M✓ P✓; D-6 S✓ M✓ P✓** (`docs/gen1_requirements.md:80,110`) | `M.forceFaint(slot)` writes **party HP only** (`lua/memory_gb.lua:833-837`) and is dispatched the frame the command arrives, with no safe-state gate and no retry (`gen2_crystal_client.lua:256-267`). The file's own comment block, four lines above the function, explains why a party-only write is overwritten at the top of the next turn (`lua/memory_gb.lua:812-832`). **M** (`lua/tests/test_gen2_force_faint.lua`, single-instance) | — | A Gen 2 active battler survives its partner's death. The engine's own faint decision is at `HandlePlayerMonFaint` (`research/pret_gen2_symbols.md:94`), which is the site a rewrite must pin. |
| 11 | **Benched `force_faint`** | HP `0000` **and status `00`** at the write-safe checkpoint (`docs/gen1_requirements.md:79`). **W-1 S✓ M✓ P✓** (`docs/gen1_requirements.md:79`) | HP only, immediately, status untouched (`lua/memory_gb.lua:833-837`). **M** (same Lua gate) | — | Status is at party +0x20 (`research/pret_gen2_symbols.md:38`) and is left as-is; a poisoned corpse keeps its PSN pill. |
| 12 | **Poison faint** | `ApplyOutOfBattlePoisonDamage.noBorrow+4`, `wWhichPokemon` names the slot, HP already zeroed (`lua/gen1/signals.lua:96-100`). **S✓ M✓ P◐ (S-4)** | Only the generic party diff sees it, and only if `nuzlocke_active` (`gen2_crystal_client.lua:842-874`, `:753-761`). **·** | — | The Gen 2 site exists and is pinned in research: `DoPoisonStep::` at `engine/events/poisonstep.asm:1`, called from `engine/overworld/events.asm:912` (`research/pret_gen2_symbols.md:105`). |
| 13 | **Whiteout + rebuild** | Client detects all-zero party after a real faint, emits `whiteout` exactly once; blackout site captures faint-time bytes before `HealParty`; server plans `party_mon` + `rebuild_start`/`rebuild_done` (`lua/gen1/signals.lua:108`; `lua/gen1/client.lua:605-618`; `docs/protocol.md:209-220`). **D-7 S· M✓ P✓** (`docs/gen1_requirements.md:111` — D-7 has no SOURCE cell); **S-4 S✓ M✓ P◐**, its byte-capture-vs-`HealParty` ordering still open (`:69`) | All-HP-0 scan with a `whiteout_sent` latch reset at each battle start (`gen2_crystal_client.lua:785-798`, `:1176`). `rebuild_start`/`rebuild_done` set a HUD banner only (`:353-360`). The `party_mon` executor waits out an all-fainted party for up to 300 frames rather than refusing — a Gen 1 lesson carried across verbatim (`:1310-1343`). **M** — the exercising artefact is `lua/tests/test_gen2_force_faint.lua` (its whiteout leg); no pytest touches this path, so if that driver is dropped the cell falls to **·** | — | No blackout site, so faint-time party bytes are lost: Gen 2's `Script_Whiteout` calls `HealParty` **before** `WarpToSpawnPoint` (`docs/gen2/REVIEW_RECORD.md:42`). The whiteout site to pin is `Script_Whiteout` entry. |
| 14 | **Evolution `key_change`** | Pinned at the post-write species-publication site, with a freshness witness on the slot about to be written (`lua/gen1/signals.lua:230`; `docs/gen1_requirements.md:38`, FIX-EVO/FIX-EVO-2/FIX-EVO-3). **S-5 S✓ M✓ P·** (`docs/gen1_requirements.md:70` — the row's PHYSICAL cell is `·`; the evolution-gate receipts at `:38` are the FIX-EVO fix record, not an S-5 P cell) | Same slot, different key, DV:OTID prefix unchanged, key not already known (`gen2_crystal_client.lua:816-827`, `:764-782`). **·** | — | Prefix-invariance is exactly the ambiguity Gen 1's cross-review found (boxed DV:OT-prefix collisions, `docs/gen1_requirements.md:38`). No `reason` field is sent, so the server defaults it to `nature_change` (`docs/protocol.md:166`, key_change row). |
| 15 | **NPC (in-game) trade `key_change`** | `key_change{reason:"npc_trade"}` from tracked outgoing mon at `RemovePokemon` + appended recipient (`docs/gen1_requirements.md:70`, FIX-NPC). **S-5 S✓ M✓ P·; D-10 S· M✓ P·** (`docs/gen1_requirements.md:70,114`, both on the limits list) | Nothing typed. What the old client actually does: the **outgoing disappearance is generally unreported**, because `party_to_box` is only sent after the key is found again by re-scanning the *active* box (`gen2_crystal_client.lua:899-911`) — a traded-away mon is in no box, so nothing is sent; and the **incoming mon is misclassified as a gift**, since `is_gift = not in_battle` (`:829-834`). **·** | — | Site is pinned in research: `NPCTrade::` at `engine/events/npc_trade.asm:1`, mon written at `:135-250` (`research/pret_gen2_symbols.md:109`). |
| 16 | **PC deposit / withdraw / release / ChangeBox + `stats_cache`** | `move_mon` / `remove_pokemon` bus-exec kinds snapshotting the whole party **and** the whole box, with `wMoveMonType` and `wRemoveMonFromBox` disambiguating deposit / withdraw / release (`lua/gen1/signals.lua:189-219`); a boxed RELEASE is deliberately not on the wire (`docs/protocol.md:203-208`). **S✓ M✓ P✓ (S-6, D-9, W-5 ChangeBox)** | 3-frame debounced party diff, with deposit confirmed by re-scanning the active box (`gen2_crystal_client.lua:876-961`). `stats_cache` is sent **only** on a server-driven `box_mon`, read before the deposit (`:1286-1296`); a player's own PC deposit sends `party_to_box` with no stats (`:909-912`). `getCurrentBoxNum` exists but is used only for the memorial guard (`:1255-1256`; `lua/memory_gb.lua:642-645`). **Withdrawal debounce defect**, recorded explicitly: the deposit path carries an `or deposit_debounce[key]` clause precisely because `prev_party` is overwritten each frame, so a key is only "new/gone" on one frame (`:886-897`); the **withdraw** path at `:932-948` has no such clause — `withdraw_debounce` only increments while `not was_in_prev`, reaches 1 and stops, and with `DEBOUNCE_FRAMES = 3` (`:634`) `box_to_party` can never fire. **·** for withdraw; **M** elsewhere in the row | duo `boxsync` scenario (`tests/e2e/test_duo_gen2.py:5-29,50`) — PHYSICAL on the old client, **not admissible** | A `ChangeBox` swaps the whole active box out from under the diff: keys vanish and reappear with no PC involvement, and the in-box confirmation at `:899-908` reads the wrong box. A release is silently dropped by that same guard (matching Gen 1's recorded gap by accident, not by design). `box_mon_failed` is **never sent** — the give-up and missing-key paths only log and show a HUD banner (`:1300-1306`), and a raised executor error is swallowed with no ACK (`:1411-1416`), which `docs/protocol.md:166` marks as a MUST for a new client. |
| 17 | **Memorial box write** | Box 12 (`box_count - 1`), refuse when party ≤ 1, refuse a full box with `memorialize_failed`, recompute the game's per-box and all-box checksums, and — rather than waiting for the game to initialise the boxes — **initialise them itself**: `lua/gen1/boxes.lua:487-493` calls `ensure_boxes_initialised`, which writes every bank, seals the per-bank and whole checksums and sets the durable flag (`:239-264`), with the two-write tear window recorded at `docs/gen1_requirements.md:188`. **W-5 S✓ M✓ P✓; D-8 S✓ M✓ P✓** (`docs/gen1_requirements.md:83,112`); full-box refusal MODEL by amendment | `depositMemorialMon` writes the 32-byte struct + OT + nickname into the flat CartRAM block at `0x79E0`, bumps the count and the `0xFF` terminator, then compacts the party (`lua/memory_gb.lua:1407-1497`). Party ≤ 1 and full-box both refuse, correctly and without the box fallback (`:1424-1445`). No checksum work — **correct**, Gen 2 boxes sit outside `SaveChecksum` (`research/pret_gen2_symbols.md:76`). Deferred while Box 14 is the active box (`gen2_crystal_client.lua:1251-1256`). **M** | duo `memorialize` scenario (`tests/e2e/test_duo_gen2.py:5-29,50`) — PHYSICAL on the old client, **not admissible** | Two unhandled hazards from the fact-check: `EraseBoxes` runs on the first save when `wSavedAtLeastOnce == 0` (`docs/gen2/REVIEW_RECORD.md:41`), and the copy-back direction of `SaveBox` needs a negative control across a SAVE (`:38`). And the box struct has no HP or status field (`research/pret_gen2_symbols.md:36-41`), so a Gen 2 memorial record cannot itself say "dead" — the Gen 1 oracle (`Box 12 … HP0000/status00`, `docs/gen1_requirements.md:79`) has no Gen 2 equivalent. |
| 18 | **`no_catch` / dead zone / species clause** | `no_catch{area_id, species_id, level}`, withheld until the first ball. "Latched against the throw site" is **historical**: no throw site exists in the installed 18 (`engine_signals.json`; the ball-side site is `bag_received`), and the current client emits `no_catch` from its own battle state — wild ∧ not demo ∧ not captured ∧ not acquiring ∧ area unresolved ∧ Tower-ghost/Silph-Scope guard ∧ ball gate (`lua/gen1/client.lua:978-997`). **S-2 S✓ M✓ P✓; D-3 S✓ M✓ P✓** (one ordering sub-clause still ◐); **D-4 S· M✓ P✓** (`docs/gen1_requirements.md:67,107,108`) | `no_catch` on grace expiry with **`area_id` only** — no `species_id`, no `level` (`gen2_crystal_client.lua:964-972`). Gift areas and resolved areas are filtered locally. **·** | — | `docs/protocol.md:166` (no_catch row): "`species_id`/`level` MUST be sent: without `species_id` the reroll can never fire and a legitimate dupe encounter dead-zones the area." The clause is **not wholly inert**, though: capture-time duplicate checking runs whenever `cap_species` is present (`server/state.py:1527-1538+`) and the old client does send `species_id` on a capture (`gen2_crystal_client.lua:646-654`). What is dead is the **failed-encounter reroll path** (`server/state.py:1922+`), which reads `species_id` off `no_catch`. `tests/e2e/test_duo_gen2.py:24-29` states the clause is covered by Gen 1 instead. |
| 19 | **Native trade** | Cable Club receptionist at every Center + Indigo via companion patch, native menus, partner answers the cartridge's own YES/NO, decline path proven (`docs/gen1_requirements.md:124-128`). **T-1 S✓ M✓ P✓; T-2 S✓ M✓ P✓; T-3 S· M· P✓; T-4 S· M· P✓** (`docs/gen1_requirements.md:124-127`) — T-3/T-4 are receipt-only rows with no SOURCE or MODEL cell, and their **trade-evolution and save-reload sub-claims are excluded** as recorded limits (`:171-172`). **T-5 MODEL by construction** | Nothing. No patch, no receptionist, no trade FSM participation. **·** | — | Owner ruling O-4 makes this RC-gated (`docs/gen2/REVIEW_RECORD.md:18`). The "link-trade write routine unlocated" blocker is **superseded**: `research/codex_checkpoint_and_linktrade.md` locates the whole chain — `LinkTrade` → `AddTempmonToParty` (Crystal `engine/link/link.asm:1994`, Gold `:1824`) → `EvolvePokemon` (C `:1998`, G `:1828`) → `SaveAfterLinkTrade` (C `:2044`, G `:1874`). What is still unproven is a *complete serial takeover*, not the writer. |
| 20 | **START-menu panel** | ABI-3 mailbox, staged generations, three BG transfers, wrap, timeout, canary; 144-scenario matrix (`docs/gen1_requirements.md:124`, T-1 prerequisites). **S✓ M✓ P✓** | Nothing (`lua/gen1/panel.lua` has no Gen 2 counterpart). **·** | — | RC-gated by O-4. |
| 21 | **Native sound** | Semantic codes at the companion mailbox, per-bank ids, two main-thread sites, stamped hold (shipped on master). **Not PHYSICAL by a ledger closure**: the only sound row in the ledger is **C-6, MODEL-only** (S `—`, M `✓`, P `—`, `docs/gen1_requirements.md:97`), and the closest live receipt — T-1's patch gate — records `caps=0x02`, i.e. panel advertised and **SFX deliberately not** (`:124`). Treat as shipped-on-master, evidence class **M** | `SFX_DISPATCH_ADDR = nil`, and the profile documents *why*: the previous value `0xC2BD` was `wCryTracks`, not `wMusicID` (`0xC29D`), "exactly the shape of the Gen 1 SFX bug". **The profile's `sfx_ids` are NOT correct**, contrary to its own comment: at both clones `constants/sfx_constants.asm:5,45,97,159` give `SFX_CAUGHT_MON=$02`, `SFX_FAINT=$2A`, `SFX_SHINE=$5E`, `SFX_GET_BADGE=$9C`, whereas the profile uses `$44`/`$46`/`$B5`/`$4A` — which are `SFX_DOUBLESLAP`, `SFX_JUMP_KICK`, `SFX_SWEET_SCENT_2` and `SFX_SUBMISSION` (`pokecrystal/constants/sfx_constants.asm:71,73,184,77`) — and `$39` for "SFX_NO", which is `SFX_WING_ATTACK` (`:60`). `M.playSfx` is a guarded no-op (`lua/games/gen2_crystal.lua:210-239`; `lua/memory_gb.lua:1335-1366`). **·**, deliberately | — | Leaving it off was the right call, but the *ids must be regenerated*, not reused. The profile's own "to enable: set this to `0xC29D`" recipe is **withdrawn**: `lua/memory_gb.lua:1335-1340` writes a single byte, while the engine arbitrates SFX by priority in `PlaySFX` (`home/audio.asm:180-218`) and initialises channels in `_PlaySFX` (`audio/engine.asm:2472+`) — a raw byte poke into `wMusicID` is not that call. RC-gated by O-4. |
| 22 | **Peer ghost** | Gen 3 only today; Gen 1 has it reserved and disabled | Nothing | — | **Post-RC by owner ruling O-13** ("make peer ghost after RC, research now"), with the design lane already dispatched — `docs/gen2/research/peer_ghost_design.md`, `docs/gen2/REVIEW_RECORD.md:24`. Not an open question about *whether*; the open part is the Gen 2 object-event binding, and two source facts constrain it: the object-event block lies **inside the saved `wPlayerData` span** (C `ram/wram.asm:2993-3378` vs `engine/menus/save.asm:498-508`; G `:2397-2720` / `:396-406`), so a ghost written there is persisted by an ordinary save; and `GetJoypad` is reached only when map events are on (`engine/overworld/events.asm:193-199`; G `:191-197`). |
| 23 | **Soft reset / reconnect / wrong save / WRAM clear** | Hello waits for the overworld checkpoint or a running battle; soft reset pauses writes and keeps the queue; five consecutive validation failures pause the gate; reconnect re-hellos with the link intact (`docs/gen1_requirements.md:60,84,92-93`). **W-6 S— M✓ P✓; C-1 S· M✓ P✓; C-2 S· M✓ P✓; D-14 S· M✓ P✓; R-4 S· M✓ P·** (`docs/gen1_requirements.md:84,92,93,118,60`) | `validateROM()` every 60 frames; 5 consecutive failures reset `game_valid`, `initialized`, `writes_enabled`, `nuzlocke_active` and the battle latches (`gen2_crystal_client.lua:1084-1104`; `lua/memory_gb.lua:841-873`). The pending sync queue is **not** cleared and not explicitly preserved — it simply stops draining. Reconnect re-seeds `all_known_keys` from the party and the active box, then hellos (`:1106-1139`). **·** | — | Validation is party-count + map-group-range + `wPlayerID != 0`, no checkpoint predicate, no live-game test, and (row 2) no identity on the hello — so the wrong-save leg rests entirely on the server's lead-mon OT fallback (`server/state.py:989-1015`) and inherits every one of its failure modes rather than being absent. `hasPokeballs()` at connect re-opens the gate (`:1112-1114`) — Gen 1's C-6 latch survives a soft reset; Gen 2's does not. |
| 24 | **HUD sanitize** | `hud.lua` `sanitize()` folds `GLYPH_MAP` glyphs to ASCII; all on-screen text routes through it | **Already correct by sharing**: Gen 2 calls the same `HUD.show`/`HUD.prompt`, which sanitize on entry (`lua/hud.lua:69,86,259-260,285-286,333,359`; `gen2_crystal_client.lua:216-220`). GBC geometry is passed explicitly (160×144, 8 px font). **M** | — | None. Keep as-is; the only Gen 2 risk is the 22-char HUD bar budget the client already shortens for (`:1179-1188`). |
| 25 | **Fixtures** | Each `.SaveRAM` grown from **scripted play** and re-qualified against the game's own checksums, `TryLoadSaveFile == 2`, and a PYDEC party match; town fixtures on encounter-free ground, battle fixtures in grass (`docs/gen1_requirements.md:51`, F-6). **S✓ M✓ P✓** | One `town` fixture, **staged not played**: `lua/tests/gen2_playthrough.lua:283-298` writes a level-5 Totodile into slot 0 — "The fixture needs 'a party with >= 1 mon'; it does not need the story beat that produced one." No grass fixture, because New Bark's west exit is locked until Elm's script runs (`docs/gen1_gen2_runtime_checks.md:205-210`). **·** | — | F-6 is not met. The lock is **SOURCE**, not folklore: scene-conditioned `coord_event` at (1,8)/(1,9), released by `setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP` from `ElmsLab.asm` (`docs/gen2/REVIEW_RECORD.md:37`; `research/pret_gen2_symbols.md:180-187`). A played fixture must drive Elm's script. |
| 26 | **Live gates** | **19 lanes** (`tools/verify_gen1_release.py:98-211`), a skip is a failure; six inspect cases (3 titles × town/battle) with Lua-on-hardware vs Python-on-the-same-bytes, plus three scripted New Game runs (`docs/gen1_gen2_runtime_checks.md:26-40`). **P** | Two gates, one cartridge, one fixture: `test_gen2_memory_gate.lua` and `test_gen2_writes_gate.lua` (`tests/live/test_gen2_gates.py:43-48`). Both skip silently when EmuHawk, the dump or the fixture is missing (`:61-67`). Gold, Silver and AP Crystal have no dumps and are stated rather than skipped (`:13-18`). **·** for the rewrite | both gates pass on the old client (`tests/live/test_gen2_gates.py:43-48`) — PHYSICAL on the old client, **not admissible** | No Lua-vs-Python differential (no codec, row 30), no scripted New Game, no lane runner, and a skip is not a failure. |
| 27 | **Duo scenarios + oracles** | 18 `gen1_new` scenarios with **PYDEC** (Python decodes the flushed cartridge) and **SERVER** (`links.json` read by pytest, never by the client) oracles; every PYDEC qualify runs the stat-recompute control first (`docs/gen1_requirements.md:38,58`). **P** | Three scenarios — `faint`, `boxsync`, `memorialize` — two Crystal instances against one dump, enabled by per-instance `saveram_dir` (`tests/e2e/test_duo_gen2.py:5-29,50`). The verdict is the runner's own `returncode` over client-side RESULT lines (`:78-79`). **·** for the rewrite | three scenarios pass on the old client — PHYSICAL on the old client, **not admissible** | No oracle independent of the client. **Same-cartridge pairing is not a Gen 2 exclusive**: Gen 1 already records Red×2 receipts under D-1 and D-3 (`docs/gen1_requirements.md:105,107`), so the Red↔Blue "constraint" was never a constraint. Per-instance `saveram_dir` is a **harness mechanism** (`tests/e2e/test_duo_gen2.py:5-10`), not a generational property; what the source confirms is only that BizHawk names SaveRAM from the gamedb entry keyed on the ROM's SHA-1, not the launch path (`research/bizhawk_gambatte_gbc.md:197-229`). Owner ruling **O-16** admits every Gen 2 pairing under one family — C↔C, G↔S, G↔G, S↔S and C↔G/S (`docs/gen2/REVIEW_RECORD.md:27`, superseding O-11's C-only clause). |
| 28 | **Release runner + ledger** | `docs/gen1_requirements.md` — **63 requirement-id rows** (F 6, R 4, S 8, W 7, C 7, D 14, T 5, X 12; `:46-149`) plus a limits list — driven by `python tools/verify_gen1_release.py`; "a lane that did not run did not pass" (`docs/gen1_requirements.md:5-7`) | Partly exists now: `docs/gen2/gen2_requirements.md` **has been written** in this worktree. Still missing: `tests/gen2_release_requirements.json` and `tools/verify_gen2_release.py` (`tools/` has `gen2_playthrough.py` and three generators). **·** | — | Owner ruling O-6 commissions all three under a separate tag (`docs/gen2/REVIEW_RECORD.md:20`). |
| 29 | **Gold / Silver / AP admission** | Yellow is a first-class profile with its own −1 WRAM shift and its own sites; Archipelago is profile generation only, on the limits list (`docs/gen1_requirements.md:46,155`) | Gold and Silver get **full duplicated profiles**, address-checked against pret by `tools/verify_profile_addresses.py`, with no dumps to run (`lua/games/gen2_crystal.lua:252-469`; `docs/gen1_gen2_runtime_checks.md:174-177`). AP Crystal inherits vanilla Crystal with **five proven overrides** and an explicit `ap_addresses_unverified = true` (`:472-514`). **M** (`tests/unit/test_gen2_ap_addresses.py`) | — | Honest, and better-documented than Gen 1's equivalent. But the fact-check refutes "only trainer data differs": G/S **wild tables differ** (`data/wild/johto_grass.asm:341-364`), so Gold and Silver need separate encounter/area packs and separate admission rows (`docs/gen2/REVIEW_RECORD.md:40`). |
| 30 | **Python codec twin** | `server/adapters/gen1_codec.py` decodes the same raw WRAM/SRAM bytes as the Lua reader; **PYDEC** is the oracle behind R-1, R-2, W-5, D-8, D-9 and every duo run (`docs/gen1_requirements.md:30,57-58`). **P** | **None.** `server/adapters/` has `gen1_codec.py` and `gen1_rom_scan.py` and no Gen 2 counterpart. **·** | — | This is the single highest-leverage missing piece: without it no Gen 2 row can ever be judged by anything other than the client under test, which is exactly why the existing live/duo passes are inadmissible. |
| 31 | **Shared JSON codec** | `lua/json_codec.lua`, verified as an inherited asset (`docs/gen1_requirements.md:159`) | The Gen 2 client hand-rolls both halves: a `json_encode` closure (`gen2_crystal_client.lua:108-140`) and a **regex command parser** that pattern-matches each field out of the reply (`:143-196`). **·** | — | Reuse `lua/json_codec.lua`. The regex parser is also where new command fields go missing silently — `stats` had to be added by hand (`:161-178`). |
| 32 | **Composition root / entry** | `lua/gen1/entry.lua` is a composition root: admission, pack selection, injected `io`, expected-bytes verification at load, refusal to start on mismatch; `lua/gen1/run.lua` is the thin BizHawk shell (`docs/gen1_gen2_runtime_checks.md:6-11`; `research/bizhawk_gambatte_gbc.md:231-253`) | One 1484-line script that does detection, profile init, JSON, HUD, dispatch, diffing and the frame loop, with module loading by `package.path` string-munging and `package.loaded[…] = nil` (`gen2_crystal_client.lua:79-101`). No injected `io`, so nothing can be driven under lupa — which is why there is no `tests/unit/test_gen2_client.py`. **·** | — | Ruling O-3 ("Gen 1 is canonical") means `lua/gen2/{client,signals,writes,boxes,reads,entry}.lua` mirroring `lua/gen1/*`, with the same injected-`io` boundary. |
| 33 | **Explode Mode / rival swap** | Explode: all four move/PP slots + party mirror at the battle-loop head, active-battler only (`docs/gen1_requirements.md:81`). **W-3 S✓ M✓ P✓; D-11 S· M✓ P✓** (`docs/gen1_requirements.md:81,115`) | Not implemented; the client names both as missing (`gen2_crystal_client.lua:40-43`), and `lua/memory_gb.lua:647-670` keeps only the Gen 1 explanatory comments with the functions themselves removed. **·** | — | Needs Crystal's selected-move and active-slot addresses, which no profile declares. |

**Counts.** 33 rows. Gen 1 row counts are per-row summaries only — where a row cites several
requirement ids, the **per-id grades in the cell are authoritative** and they do not all agree
(F-3, S-3, S-5, D-7, D-10, T-3, T-4 in particular).

Gen 2: **nine** cells carry a MODEL label (rows 3, 9, 10, 11, 13, 16, 17, 24, 29), **two** carry a
historical-live note in the new right-hand column (rows 26, 27), and the remaining **22** carry
nothing. Row 24 (HUD sanitize) is already met by sharing Gen 1's module. Standing rule for the
rewrite: **every MODEL label must name the test that exercises it** — a label with no named test
is a `·`.

## 3. What the Gen 2 code got right, to keep as a hypothesis and re-prove

1. **The 32-byte box struct and its consequence.** The client and `memory_gb` both understand
   that a Gen 2 box record carries no HP, maxHP or stats, and that `retrieveBoxMon` must refuse
   rather than write a zero-stat mon (`gen2_crystal_client.lua:33-38,310-318,1282-1296`). Re-prove
   with a codec twin reading the flushed SaveRAM. **Correction:** `stats_cache` is *not* "the only
   way a deposited mon can ever be withdrawn" — the game's own box-to-party transfer recomputes
   the stats via `CalcMonStats` (`engine/pokemon/move_mon.asm:654-672`, both repos), so a rewrite
   can recompute from level + DVs + stat exp. The old client's refusal without its cache is an
   old-client limitation, not a Gen 2 fact.
2. **The split Special.** `spdef_offset = 0x2E` is a real address, not Gen 1's alias
   (`lua/games/gen2_crystal.lua:144-148`), and the fixture writer calls out the trap
   (`lua/tests/gen2_playthrough.lua:290-294`).
3. **The safe-state predicate was reasoned about rather than guessed** — but the "measured" claim
   is **†unverified**. `wScriptRunning` was chosen after a probe reportedly rejected
   `wJoypadDisable` (00 in both states) and `wTextboxFlags` (text-speed config), and the only
   evidence for that is a profile comment (`lua/games/gen2_crystal.lua:83-93`) and a probe script
   (`lua/tests/probe_gen2_safestate.lua`) — no committed receipt. Keep the probe, treat the
   conclusion as a hypothesis, and re-prove it against a CPU-state checkpoint.
4. **The ball-id list is derived from pret's BALL pocket**, with the failure mode of the old
   wrong list written down: Apricorn balls read as none, so the gate never opened
   (`lua/games/gen2_crystal.lua:28-53`).
5. **Native sound was left off on purpose** rather than shipped as a guess
   (`lua/games/gen2_crystal.lua:210-239`). That judgement is the standard — but only the
   judgement: the `sfx_ids` table it left behind is wrong on every entry (row 21), so the data
   must be regenerated from `constants/sfx_constants.asm`, not inherited.
6. **Three sync branches report back — not "every sync path".** The acknowledging branches are
   `sync_retrieve_done`/`_failed` (`gen2_crystal_client.lua:1353-1360`),
   `memorialize_done`/`_failed` (`:1386-1392`) and the "already boxed / gone" `memorialize_done`
   (`:1406-1407`); the bug that left a Gen 2 pair stuck in `pending_memorials` forever is fixed
   and its reasoning is recorded. But the `box_mon` give-up and missing-key paths only log and
   show a HUD banner (`:1300-1306`), and the executor's `pcall` swallows a raised error with no
   ACK at all (`:1411-1416`). The missing `box_mon_failed` defect stands (row 16).
7. **The memorial box is deferred while it is the active box** (`:1251-1256`), which is the
   correct half of the `SaveBox` hazard.
8. **Per-instance `saveram_dir` lets one cartridge pair with itself**
   (`tests/e2e/test_duo_gen2.py:5-10`), source-confirmed at
   `research/bizhawk_gambatte_gbc.md:197-229`. Keep the mechanism — but it is a **harness
   mechanism, not a Gen 2 advantage**: Gen 1 already runs Red×2 under D-1 and D-3
   (`docs/gen1_requirements.md:105,107`).
9. **AP Crystal is flagged unverified with the five provable overrides recorded**
   (`lua/games/gen2_crystal.lua:472-514`) instead of inheriting vanilla silently.

## 4. What must change for Gen 2 to meet the Gen 1 standard

In dependency order.

1. **Build the Python codec twin** (`server/adapters/gen2_codec.py`). Nothing else can be judged
   until an oracle exists that is not the client. It is the precondition for every PHYSICAL cell,
   and it is what makes the existing live/duo passes inadmissible today.
2. **Pin the engine sites and generate them.** A `docs/gen2_engine_sites.md` + a generated
   `data/games/gen2_crystal/engine_signals.json` with expected bytes per clean ROM, verified at
   load the way `lua/gen1/entry.lua:187-191` does. Sites already located by research:
   `PokeBallEffect` party/box fork (`item_effects.asm:548-550,556,612`), `TryAddMonToParty`
   (`move_mon.asm:3`), `SendMonIntoBox` (`move_mon.asm:942`), `HandlePlayerMonFaint`
   (`engine/battle/core.asm:2607`), `LostBattle` (`engine/battle/core.asm:2915`),
   `Script_Whiteout` (pre-`HealParty`), `DoPoisonStep` (`poisonstep.asm:1`), `NPCTrade::`
   (`npc_trade.asm:1`), `GiveEgg` (`move_mon.asm:1121`) — `research/pret_gen2_symbols.md:94-116`;
   `docs/gen2/REVIEW_RECORD.md:42`. The link-trade chain is **located too**: `LinkTrade` →
   `AddTempmonToParty` (C `engine/link/link.asm:1994`, G `:1824`) → `EvolvePokemon` (C `:1998`,
   G `:1828`) → `SaveAfterLinkTrade` (C `:2044`, G `:1874`), per
   `research/codex_checkpoint_and_linktrade.md`.
3. **Add admission, and make identity reported instead of inferred.** Clean sha1s from
   `research/rom_hashes.md:52-98` into a `data/games/gen2_crystal/admission.json`, an
   `Entry`-shaped sha1 + anchors path, and `rom_content_fingerprint` on the adapter. Identity is
   not absent today — the server infers it from the lead mon's OT (`server/state.py:989-1015`) —
   so the work is to put a real `ot_id` (plus `rom_sha1` / `rom_content`) on the hello and stop
   depending on a fallback that breaks on an empty party, a reorder or a traded-in lead mon. The
   Crystal-revision question is **closed**: O-12, "we can use whatever the local dump is", hashed
   at P1, with the other revision a recorded limit (`docs/gen2/REVIEW_RECORD.md:23`).
4. **Add the write-safety layer.** A CPU-state checkpoint, an armed-window rule enforced in a
   `lua/gen2/writes.lua`, the `MainInBattleLoop` equivalent for the active battler (HP **and**
   the cannot-move byte), status zeroing on a bench faint, and the queue-pause/NACK semantics of
   W-6 including `box_mon_failed`.
5. **Fill the four missing events**: `battle_end` with `wBattleResult` decoded (remembering that
   a transient LOSE is not a whiteout, `docs/gen2/REVIEW_RECORD.md:42`),
   `trainer_battle_start{trainer_id}`, `capture{in_box:true}` for the party-full catch, and
   `species_id`/`level` on `no_catch` so the **failed-encounter reroll path**
   (`server/state.py:1922+`) stops being inert — capture-time duplicate checking already works.
6. **Harden the SRAM box path**: `EraseBoxes` is reached from `ErasePreviousSave`
   (`engine/menus/save.asm:360-366`) via **two** callers — `AskOverwriteSaveFile` (`:181-199`) and
   `HallOfFame_InitSaveIfNeeded` (`:470-475`) — and only the latter tests `wSavedAtLeastOnce`, so
   that flag is not a universal guard and the rewrite must cover the overwrite path too; a negative
   control across a SAVE with Box 14 active, and an explicit decision about how a memorial is
   marked dead when the box struct has neither HP nor status.
7. **Grow a played fixture.** Drive Elm's lab so the west exit unlocks, then a grass fixture, then
   `--qualify` against the game's own primary/backup checksums — F-6 for Gen 2.
8. **Restructure into `lua/gen2/{entry,client,signals,reads,writes,boxes}.lua`** with the injected
   `io` boundary, reusing `lua/json_codec.lua` and `lua/hud.lua`, so the client can be unit-tested
   under lupa at all (ruling O-3).
9. **Split Gold and Silver data packs** — the wild tables differ (`docs/gen2/REVIEW_RECORD.md:40`)
   — and give each its own admission row.
10. **Finish the ledger and write the runner.** `docs/gen2/gen2_requirements.md` now exists in
    this worktree; still to come are `tests/gen2_release_requirements.json` and
    `tools/verify_gen2_release.py` (ruling O-6), with the
    same "a lane that did not run did not pass" rule, and the same oracle vocabulary (ENGINE /
    PYDEC / GAME / SERVER / CONTROL) once the codec exists.
11. **Native trade, panel and sound are RC-gated** (ruling O-4); the peer ghost is **post-RC**
    (O-13). Sound is still the cheapest, but it is **not** a one-address change: the profile's
    `sfx_ids` are wrong on every entry and must be regenerated (`SFX_CAUGHT_MON=$02`,
    `SFX_FAINT=$2A`, `SFX_SHINE=$5E`, `SFX_GET_BADGE=$9C` at
    `constants/sfx_constants.asm:5,45,97,159` in both clones, against the profile's
    `$44`/`$46`/`$B5`/`$4A`/`$39`), and dispatch must go through the engine's own arbitration —
    `PlaySFX` (`home/audio.asm:180-218`) into `_PlaySFX` channel init (`audio/engine.asm:2472+`) —
    rather than the single byte write at `lua/memory_gb.lua:1335-1340`. Trade is **not** blocked on
    locating the writer (found: `LinkTrade` → `AddTempmonToParty` → `EvolvePokemon` →
    `SaveAfterLinkTrade`, C `engine/link/link.asm:1994,1998,2044` / G `:1824,1828,1874`); it is
    blocked on proving a complete serial takeover.

## Open questions

- ~~Which Crystal revision the project targets.~~ Closed by owner ruling **O-12**: "we can use
  whatever the local dump is"; hashed at P1, the other revision a recorded limit
  (`docs/gen2/REVIEW_RECORD.md:23`).
- ~~The Gen 2 link-trade mon-exchange routine is unlocated.~~ Superseded: the chain is `LinkTrade`
  → `AddTempmonToParty` → `EvolvePokemon` → `SaveAfterLinkTrade`, Crystal
  `engine/link/link.asm:1994,1998,2044` and Gold `:1824,1828,1874`
  (`research/codex_checkpoint_and_linktrade.md`). What remains open is whether a **complete serial
  takeover** is achievable, not where the writer is.
- ~~Whether a peer ghost is feasible on Gen 2 at all.~~ Reframed by **O-13**: build it after RC,
  research now (`docs/gen2/REVIEW_RECORD.md:24`; `research/peer_ghost_design.md`).
- Whether `emu.framecount()` inside `event.on_bus_exec` equals the armed frame in **CGB** mode.
  The pin (`docs/gen1_requirements.md:21`) is a DMG finding; nothing in the BizHawk/Gambatte
  source contradicts or extends it for CGB (`research/bizhawk_gambatte_gbc.md:138-157,262-265`).
- Whether BizHawk's `CartRAM` domain for a live Gen 2 cartridge is exactly 0x8000 bytes — derived
  from `rambanks * 0x2000`, never observed (`research/bizhawk_gambatte_gbc.md:257-261`).
- ~~The literal SRAM bank index for `sBox8..sBox14`.~~ Answered from the linker script: **bank 3**
  in both titles — `pokecrystal/layout.link:375-378` and `pokegold/layout.link:300-304` both put
  `"Boxes 8-14"` under `SRAM $03`. What the flat `0x79E0` derivation still assumes is bank-linear
  CartRAM (`docs/gen2/REVIEW_RECORD.md:39`), which is the remaining unobserved part.
- ~~Whether Gold/Silver load as `game.System == "GBC"` in BizHawk.~~ Resolved against the gamedb:
  all four sha1s appear in `gamedb_gbc.txt` with `System = GBC` and status `G`, and none appear in
  `gamedb_gb.txt` (`research/gamedb_and_encounters.md:24-38`).
- What "in the overworld, no script running" is in pret terms. The code's `wScriptRunning` choice
  is a live measurement; no source line combining `wScriptRunning`/`wScriptFlags` into a
  safe-to-act predicate was found (`research/pret_gen2_symbols.md:147,261`).
- Whether `data/pret_syms.json`'s Gen 2 addresses correspond to the pinned shas: the file carries
  no `rom_sha1`, and `tools/build_pret_syms.py` resets each cache to `origin/HEAD`
  (`research/pret_gen2_symbols.md:10,272`; `research/rom_hashes.md:108-129`). Every address in
  `lua/games/gen2_crystal.lua` inherits that uncertainty for symbols the HEAD rebuild did not
  cover.
- Whether Gen 2 static and gift encounters route through a shared `GivePokemon`; no such routine
  was found (`research/pret_gen2_symbols.md:117,264`). Affects how gifts and statics are
  attributed, which Gen 1 solves with seven typed receipt kinds.
- ~~Which AP Crystal release to pin.~~ Resolved by the owner 2026-09-21: `6.0.0-rc.1`
  (`research/archipelago_crystal.md` "Delta from what the project had"; `REVIEW_RECORD.md` round 2).
- Whether the exact `stats_cache` timing Gen 1 uses (read the party tail *before* the deposit) is
  reachable on a player-driven Gen 2 PC deposit, which today sends no stats at all
  (`gen2_crystal_client.lua:909-912`).
