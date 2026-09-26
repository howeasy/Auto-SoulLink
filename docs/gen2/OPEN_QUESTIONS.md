# Gen 2 planning: open questions

> Corrected 2026-09-21 after Codex fact-check cx-5470791d; see docs/gen2/REVIEW_RECORD.md.

Every unresolved fact or owner decision, with the evidence that would close it. Facts are the
coordinator's job (a wayfinder ticket under `docs/gen2/wayfinder/issues/` where one exists);
decisions are the owner's. Nothing here is stated as fact anywhere else in `docs/gen2/`.

Read at worktree `claude/gen2-planning-kickoff-a18801` HEAD `4bf0f3b`, 2026-09-21.

## A. Owner decisions (HITL)

| # | Question | Default if unanswered | Evidence / ticket |
|---|---|---|---|
| A-1 | ~~Crystal revision~~ RULED 2026-09-21 (O-12): use whatever the local dump is; hashed at P1, the other revision is a recorded limit | — | ticket 19 resolved |
| A-2 | ~~Peer ghost timing~~ RULED (O-13): post-RC; design research now (R9) | — | ticket 17 |
| A-3 | ~~Trade extras~~ RULED (O-14): no Time Capsule; held items validated and carried; mail a recorded limit | — | tickets 13, 15 |
| A-4 | ~~Egg hatch~~ RULED (O-15): gift capture under `gift_daycare` with the hatchling's key | — | PLAN §5.14 |
| A-5 | ~~Gate cadence~~ RULED: same as pureRGB, owner signs every gate, one lane | — | `docs/purergb/PLAN.md:39-44` |
| A-8 | ~~Pairings~~ RULED (O-11 then O-16): every Gen 2 pairing admitted through one foundation `gen2_gsc`; C-6g encodes it | — | PLAN §5.9 |
| A-9 | ~~Base cut~~ RULED (O-20): cherry-pick `80261f3` + `959c578` + `910dbdd` onto master; drift watch against the Gen 3 branch tip at every gate signing (PLAN §5.9, §6.1) | — | PLAN §6 P0 |
| A-7 | ~~Roamers / contest~~ RULED (O-17, O-18): roaming legendaries are extra catches (standalone `legend_<species>` pairs, never consume or lock the map); the Bug-Catching Contest is its own capture zone `national_park_contest` | — | PLAN §5.14 |
| A-6 | ~~Manager family~~ RULED (O-16): one family; every Gen 2 pairing admitted (C↔G/S included, one shared foundation) | — | PLAN §5.9 |

## B. Facts still open (AFK research)

| # | Question | Closing evidence | Ticket / note |
|---|---|---|---|
| B-1 | ~~The overworld predicate and its anchors~~ **source candidate and predicate inputs located** (ticket 10: `OWPlayerInput` before `CheckAPressOW`, `events.asm:495`). Still OPEN, as the admitted title says: extraction of the anchors from the BUILT ROMs, and the positive / negative / liveness receipts for the strict predicate — all P3b live-gate evidence | built-ROM anchor extraction + live gate on the Crystal fixtures | `codex_checkpoint_and_linktrade.md` §A |
| B-2 | Reproducible pinned builds of the four Gen 2 ROMs and their `.sym` files (no Gen 2 `.sym` exists; `data/pret_syms.json` has no provenance) | lock file + build recipe producing sha1 == `roms.sha1`; CI lane | ticket 11; `rom_hashes.md` |
| B-3 | ~~The link-trade write routine~~ RESOLVED (ticket 13: `link.asm:1994-2044`). Still open: the two-sided takeover protocol and host SaveRAM durability after `SaveAfterLinkTrade` | ticket 15 design + P4 gate | `codex_checkpoint_and_linktrade.md` §B |
| B-4 | Free WRAM/SRAM and ROM space for a companion-patch mailbox, per title | survey with citations; a mailbox address that survives every overworld/battle union | ticket 14 |
| B-5 | Native trade entry: **source routines and the entry design are located** (`research/native_trade_entry.md`; commit sequence `AddTempmonToParty` → `EvolvePokemon` → `SaveAfterLinkTrade`, `codex_checkpoint_and_linktrade.md` §B). OPEN: the two-sided takeover protocol, the ABI windows it may run in, and host SaveRAM durability after `SaveAfterLinkTrade` — no live coverage yet | ticket 15 design + P4 gate | `native_trade_entry.md`; `codex_checkpoint_and_linktrade.md` §B |
| B-6 | Native sound: **the candidate source sites are located** (`research/sound_sites_and_peer_ghost.md`). The Gen 1 two-site pattern does NOT port: Gen 2 `Joypad` is a `reti` stub (`cx-02b0f4b5`), so there is no Joypad bridge; the surviving main-thread candidate is `DelayFrame`, with `GetJoypad` reached only conditionally from `HandleMapTimeAndJoypad` (Crystal `engine/overworld/events.asm:193-199`, Gold `:191-197`) and therefore not a universal service site. OPEN: the mailbox ABI, the qualified site set and whether the Gen 1 240-frame hold applies; no live coverage | cited sites + a live overworld/menu/battle coverage run | ticket 16; `sound_sites_and_peer_ghost.md` |
| B-7 | Peer ghost: **the design and its source anchors are located** (`research/peer_ghost_design.md`; the saved object arrays are Crystal `ram/wram.asm:2993-3378` copied by `SavePlayerData` at `engine/menus/save.asm:498-508`, Gold `ram/wram.asm:2397-2720` and `save.asm:396-406`). OPEN: spare-slot allocation, the sprite/palette load path, hook cost and the feasible/infeasible verdict; post-RC per O-13, no live coverage | allocation survey + feasibility verdict with citations | ticket 17; `peer_ghost_design.md` |
| B-8 | ~~BizHawk gamedb classification of Gold/Silver/Crystal~~ RESOLVED: the file is `Assets/gamedb/gamedb_gbc.txt` (not `gamedb_gbx.txt`); all four sha1s appear there with `System = GBC` and none appear in `gamedb_gb.txt` (`research/gamedb_and_encounters.md:24-38`). Still OPEN: the launcher / `ConsoleMode` receipts and the SaveRAM domain names per title, observed on a live load | launcher core-mode receipt + `memory.getmemorydomainlist()` per title | ticket 18; `bizhawk_gambatte_gbc.md` open q. 4 |
| B-9 | `emu.framecount()` equals the armed frame inside `on_bus_exec` under CGB mode (Gen 1 pin verified for DMG only) | a live probe on a Crystal battery save at G-fixture time; until then "unverified for GBC" | `bizhawk_gambatte_gbc.md` §3 |
| B-10 | `CartRAM` is exactly 0x8000 bytes bank-linear for MBC3 Gen 2 carts | `memory.getmemorydomainlist()` + size on a live Crystal load | `bizhawk_gambatte_gbc.md` open q. 1 |
| B-11 | ~~`CalcMonStats` / DV gender / shiny~~ RESOLVED (ticket 20). ~~`NUM_UNOWN` literal~~ RESOLVED: `DEF NUM_UNOWN EQU const_value - 1` = **26** (Crystal `constants/pokemon_constants.asm:313`, Gold `:308`). ~~`GENDER_F100` macro value~~ RESOLVED: `DEF GENDER_F100 EQU 100 percent - 1` (`constants/pokemon_data_constants.asm:40`, identical in both repos) with `DEF percent EQUS "* $ff / 100"` (`macros/data.asm:23`, both), so the value is `100 * $ff / 100 - 1` = **254**, the always-female ratio, and **255** is the genderless sentinel. Still open: the codec encoding of both and the physical gender/shiny controls | codec unit test + gender/shiny GAME control at P3b | `stat_control_and_fixture_budget.md` §A |
| B-12 | ~~Encounter generator inputs~~ RESOLVED (ticket 21). Still open: unchecked `_GOLD/_SILVER` splits in fish/swarm files and the encounter-rate assumptions in today's generator (verified at P2 by two-path equality) | P2 generator + equality test | `gamedb_and_encounters.md` §B, open questions |
| B-13 | `wTempWildMon` / `wIsInBattle` equivalents. **Declaration and mutation sites are known**: Crystal `ram/wram.asm:2720` (`wBattleMode::` with its 0/1/2 comment), set to `WILD_BATTLE` in `InitEnemyWildmon` (`engine/battle/core.asm:8183-8187`) and cleared with `wBattleType` / `wTempWildMonSpecies` in `CleanUpBattleRAM` (`:8294-8299`). OPEN: runtime validity and qualification — whether "`wBattleMode` zero = not in battle" holds at every read point the client uses | cited `OverworldLoop`-side check + a read-point census | `pret_gen2_symbols.md` open q. 1-2 |
| B-14 | Odd Egg entry point; whether gifts route through one `GivePokemon` or per-script `TryAddMonToParty` | cited labels | `pret_gen2_symbols.md` open q. 5-6 |
| B-15 | ~~JSON-only addresses need declaration lines~~ RESOLVED by OMP card gen2-A2 (`research/omp_symbol_lines.md`: 54/60 pinned in both clones; macro-emitted `wEnemyMonSpecies`/`sBoxCount`/`sBox1..14` cited at emitter + expansion). Corrections: the real label is `wGameTimerPaused` (`wram.asm:1832`); `wNewSoundID`/`wChannelSoundIDs`/`sPartyCount`/`sPartyMons` do NOT exist in Gen 2 (the old profile comments carry Gen 1 names); `sBackupGameData` is Crystal-only (Gold/Silver split the backup into three sections) | — | `omp_symbol_lines.md` |
| B-16 | ~~`sBox8..sBox14` literal SRAM bank numbers~~ **SOURCE-resolved**: `layout.link` assigns the banks directly — Crystal `layout.link:375-378` puts Boxes 1-7 in `SRAM $02` and Boxes 8-14 in `SRAM $03`; pokegold `layout.link:300-304` is the same, with "Backup Save 3" following in bank 3. The ticket-11 build `.map` is therefore a later verification of the assembled artifact, not the source of the fact | `layout.link` at both pins (done); `.map` as artifact verification at ticket 11 | `pret_gen2_symbols.md` cross-check; REVIEW_RECORD cx-3569f8d9 item 3 |
| B-17 | ~~pokegold line numbers / species list~~ RESOLVED by gen2-A2: all 15 routine labels exist in both repos; use the per-repo line table in `omp_symbol_lines.md:139-153` (only the listed `move_mon.asm` labels except `GivePoke` are line-identical; battle sites differ, e.g. `HandlePlayerMonFaint` C:2607/G:2506, `UpdateFaintedPlayerMon` C:2656/G:2551, `ExitBattle` C:8268/G:7965; never apply one repo-wide offset); `pokemon_constants.asm` species list identical (comment-only diff) | — | `omp_symbol_lines.md` |
| B-18 | ~~Release condition of the west-exit lock~~ RESOLVED by gen2-A2: the `setmapscene` is the last line of `ElmDirectionsScript` (`ElmsLab.asm:251-277`), reached only by `sjump ElmDirectionsScript` at the end of each starter-choice script (`:243`, after `givepoke`), so the release is gated on the starter CHOICE, not on leaving the lab | — | `omp_symbol_lines.md` finding 9 |
| B-19 | Archipelago Crystal: the pokecrystal fork commit the `basepatch.bsdiff4` is built from (no ASM source in the repo at any ref) | a source pointer from the APWorld author or a symbol dump from the patched ROM | `archipelago_crystal.md` open q. 1 |
| B-20 | ~~Whether the OMP address audit and the Codex site audit change any value the plan relies on~~ CLOSED, no longer pending: both notes are accepted and reconciled — Codex site audit gen2-C2 (`REVIEW_RECORD.md` `cx-8172d76c`; `research/codex_engine_site_audit.md`, three defects recorded as rewrite reasons, PROFILE_SYMBOL_CHECK 60/60) and OMP card gen2-A1 (`REVIEW_RECORD.md` `cx-1deb32f4`; `research/omp_address_audit.md`, 5/5 findings accepted, the two mismatches are the documented AP fork overrides, zero address changes against the R1 HEAD rebuild) | — (closed) | `REVIEW_RECORD.md` `cx-8172d76c`, `cx-1deb32f4` |
| B-21 | `stats_cache` timing on a player-driven Gen 2 PC deposit (Gen 1 reads the party tail before the deposit; the old Gen 2 client sends none, `gen2_crystal_client.lua:909-912`) | the P3b client design + a `pc_ops` receipt | `GEN2_STANDARD_COMPARISON.md` open questions |
| B-23 | Where the shared spine lives. Gen 2 follows the **approved integrated base** (O-20: master + `80261f3` + `959c578` + `910dbdd`) and its shared set; `SWEEP docs/FRAMEWORK.md` describes modules absent from it (`server/durable_runtime.py` etc. missing at `4bf0f3b`; `gen1/rc` superseded by the master rewrite) and is vocabulary only. OPEN: confirming that reading with the owner and recording the integrated commit plus the drift baseline at G0 | owner one-liner; the G0 ledger row for the integrated base (PLAN §5.9, §6.1) | `GEN2_BINDING_PLAN.md` §2 |
| B-24 | The MBC3+TIMER SaveRAM tail BizHawk appends (the committed `tests/fixtures/gen2/crystal_town.SaveRAM` is 32790 bytes = 0x8000 + 22; `tools/gen2_playthrough.py:67-71` records it as measured) needs the Gambatte `ISaveRam` citation so the save-witness slice is SOURCE, not a measurement | `Gambatte.ISaveRam.cs` at 2.11.1 (research lane R5), plus an authoritative RTC-tail format and normalisation contract — the measured length alone says neither what the 22 bytes mean nor how the witness normalises them | `GEN2_BINDING_PLAN.md` §7 Q4 |
| B-25 | Is the Gen 2 enemy party plaintext at a fixed address (as Gen 1's is, `patch/gen1/README.md:36-43`)? **Declarations and one staging site are known**: `wOTPartyCount` / `wOTPartyMons` are declared in `ram/wram.asm` (`pret_gen2_symbols.md` §1 lists `wOTPartyCount` 0xd280) and the link path stages the opponent into them by `CopyBytes` (Crystal `engine/link/link.asm:448-463`). OPEN: runtime validity and qualification — whether those bytes are plaintext and stable at the read points a rival swap would use in a non-link battle, which is what decides whether `patch/gen2/` is UI-only | read-point census at P2 + a live inspect on a trainer battle | `GEN2_BINDING_PLAN.md` §7 Q6 |
| B-22 | Whether gifts/statics route through one `GivePoke` (Codex site audit names `move_mon.asm:1619`) or per-script `TryAddMonToParty`; affects attribution (Gen 1 uses seven typed receipt kinds) | caller census at P2 | `codex_engine_site_audit.md` candidate table; `pret_gen2_symbols.md` open q. 6 |

## D. Stale Gen 1 docs found in passing (outside this lane's lease; routed, not fixed here)

| # | Finding | Where |
|---|---|---|
| D-1 | `docs/gen1_requirements.md:47,98` say 17 pinned sites; `data/games/gen1_rby/engine_signals.json` ships 18 per title | `GEN1_STANDARD_DIGEST.md` §5.1 |
| D-2 | `docs/gen1_gen2_runtime_checks.md:19-30` says 12 lanes; `tools/verify_gen1_release.py:98-211` defines 19 | §5.2 |
| D-3 | `docs/gen1_gen2_runtime_checks.md:56-60` still calls Yellow's fixtures LEGACY; `tools/gen1_fixtures.py:66` has `LEGACY = set()` | §5.3 |
| D-4 | `docs/protocol.md:522` names `tests/unit/test_protocol_conformance.py`, which does not exist (already recorded at `docs/gen1_requirements.md:38`) | §5.5 |

## C. Premises corrected already (do not reopen)

From Codex `cx-3569f8d9` (`REVIEW_RECORD.md`): the New Bark lock is SOURCE; boxes are outside
the checksum but a memorial in the ACTIVE box is overwritten by the game's own `SaveBox`;
`EraseBoxes` runs on first-save/overwrite paths; `HealParty` precedes the whiteout warp; a
transient LOSE in `wBattleResult` is not a whiteout; Gold and Silver differ in wild tables,
not only trainers.
