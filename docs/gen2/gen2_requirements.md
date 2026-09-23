# Gen 2 release requirements (skeleton)

> Corrected 2026-09-21 after Codex fact-check cx-5470791d; see docs/gen2/REVIEW_RECORD.md.

This is the release contract for Pokémon Gold/Silver/Crystal (US), in the exact shape of
`docs/gen1_requirements.md` (read at worktree `claude/gen2-planning-kickoff-a18801` HEAD
`4bf0f3b`).

A row is **done** only when it satisfies the evidence obligations *that row declares*:

- rows with a P cell: a SOURCE proof (pret citation or generated-from-pret data) **and** a
  PHYSICAL proof (real cartridge in BizHawk, judged by an oracle that is not the code under test);
- **SOURCE-only** rows, whose P cell is `—` because no physical oracle applies (F-1, F-4, F-5, F-7g);
- **MODEL-only-by-design** rows, whose P cell is `—` because the obligation is a schema or
  by-construction property (C-0, C-4, D-13).

Satisfying a row's declared obligations is not the same as a qualified PHYSICAL behaviour claim:
only a filled P cell carries one, and closing a SOURCE-only or MODEL-only-by-design row asserts
nothing about behaviour on a cartridge. MODEL evidence (lupa/pytest against fakes) is recorded
but **never establishes physical behaviour** and never closes a row with a P cell
(`docs/gen1_requirements.md:3-7`). The runner will be `python tools/verify_gen2_release.py`;
a lane that did not run did not pass.

Nothing in the pre-rewrite Gen 2 code, data, fixtures, tests or docs counts as evidence
(brief rule 0.8; the Gen 1 sentence is `docs/gen1_requirements.md:9`).

**Skeleton status:** all evidence cells are unfilled `·` or not applicable `—`, except D-1's
P cell (`◐`, receipted per cell in `tests/gen2_release_requirements.json`). No cell is pre-filled. Row ids mirror Gen 1's so the comparison document can be read side by side;
Gen 2-only rows carry a `g` suffix.

## Pins (to be filled at G0/G1; values here are the candidates the plan proposes)

| What | Candidate value | Closing evidence |
|---|---|---|
| pret/pokecrystal | `7a7881d0d62e0ddbd82dcf10e7116807487ac651` (owner ruling O-5) | lock file + built sha1s (ticket 11) |
| pret/pokegold | `656583c939d30f920a316177311a502dd222b57c` (owner ruling O-5) | same |
| Archipelago Crystal | gerbiljames/Archipelago-Crystal `6.0.0-rc.1` = `0b11931c69134786369c0cd1ca7394104335aef5` (profile generation only, post-RC) | `docs/gen2/research/archipelago_crystal.md` |
| Clean ROM SHA-1 | Gold `d8b8a3600a465308c9953dfa04f0081c05bdcb94`, Silver `49b163f7e57702bc939d642a18f591de55d92dae`, Crystal 1.0 `f4cd194bdee0d04ca4eac29e09b8e4e9d818c133`, Crystal 1.1 `f2f52230b536214ef7c9924f483392993e226cfb` (`roms.sha1` at both pins, `docs/gen2/research/rom_hashes.md`) | local dumps hashed at P1; ADMITTED = Gold, Silver and the local dump's Crystal revision (O-12); admitted matrix at G1 |
| Emulator | BizHawk 2.11.1 (Gambatte core, `bdddf4a5…`, gambatte-core `d49b895`); CGB mode for all three titles (`ConsoleMode` pinned per ticket 18) | `docs/gen2/research/bizhawk_gambatte_gbc.md` |
| Frame alignment | `emu.framecount()` inside `on_bus_exec` equals the armed frame — **unverified for GBC** (B-9) | live probe at fixture time |
| Assembler | RGBDS (version to be pinned by ticket 11; Gen 1 pins v1.0.1 and pureRGB 1.0.3) | build lock |
| Base cut | master + cherry-picked `80261f3` + `959c578` + `910dbdd` (owner ruling O-20); the integrated commit and the drift baseline against the Gen 3 branch tip are recorded at G0 | G0 ledger row (PLAN §5.9, §6.1) |
| Wire contract | `docs/protocol.md` (unchanged; no unreviewed Gen 2 change relative to that integrated base — any Gen 2 addition is a protocol change with its own review) | |
| Engine sites | `docs/gen2/gen2_engine_sites.md` + `data/games/gen2_<title>/engine_signals.json` (to be created; ticket 12) | |

## Oracles (same vocabulary as Gen 1, `docs/gen1_requirements.md:26-32`)

- **ENGINE** — a `bus_exec` hook at a pret routine fired (or did not), expected bytes verified at load.
- **PYDEC** — `server/adapters/gen2_codec.py` decodes the same raw WRAM/SRAM bytes; Lua and Python must agree.
- **GAME** — the game itself: `TryLoadSaveFile` succeeds after our SRAM write; the party menu / PC tilemap shows the expected text.
- **SERVER** — `links.json` / server status read by pytest.
- **CONTROL** — a known-positive control: recompute a value two ways and require equality (`CalcMonStats` from DVs/stat-exp/base stats, ticket 20).

**Oracle-cell schema.** The Oracle cell holds only those five names, combined with `+` where a
row needs more than one, plus — where the row needs it — one trailing parenthetical
`(method: …)` or `(evidence layers: …)`. Nothing else goes in the cell; the requirement text
carries the detail. A row with no applicable physical oracle writes `—` in the Oracle cell and
names why in the same parenthetical: `— (MODEL-only by design)` for C-0/C-4/D-13, and
`— (SOURCE-only, P = —)` for the fact rows F-1/F-4/F-5/F-7g. Those two spellings are the schema
for a non-applicable physical oracle; `n/a` is not used.

## Status legend

`S` SOURCE, `M` MODEL, `P` PHYSICAL. `·` = not yet, `✓` = done with receipt path, `◐` = partial with the limit named in the row.

---

## F — Facts (no emulator)

| id | Requirement | SOURCE | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| F-1 | Every address in the generated profiles names a pret symbol; Crystal / Gold / Silver differ exactly where pret differs (Gold == Silver WRAM; Crystal shifted) | `tools/gen_gen2_profile.py --check` against the pinned `.sym` | — (SOURCE-only, P = —) | · | · | — |
| F-2 | Every hook site's expected bytes are present in each clean ROM at bank:addr | `engine_signals.json` + `tools/verify_gen2_rom_layout.py` | ENGINE (method: inspect gate on the running cartridge) | · | · | · |
| F-3 | Site table complete: battle start (wild/trainer), battle end + result, capture→party vs →box, player faint, poison faint, whiteout (`Script_Whiteout` before `HealParty`), evolution species publish, NPC trade, link trade, PC deposit/withdraw/release/box change (no `ChangeBox` symbol exists; real sites under S-6), map load, bag ball received, save, CONTINUE, New Game, soft reset, egg hatch | pret per row (ticket 12) | ENGINE + PYDEC/GAME (method: differential gate across titles) | · | · | · |
| F-4 | Wild/headbutt/rock-smash/fishing/roamer tables and base stats: Lua ROM reader == Python `gen2_rom_scan.py`, byte-equal, per title and time of day | two-path equality (ticket 21) | — (SOURCE-only, P = —) | · | · | — |
| F-5 | Evolution families, item ids, species id == national dex order from pret. The species list is the complete `const_def` block up to `DEF NUM_POKEMON` (Crystal `constants/pokemon_constants.asm:21-274`, Gold `:16-269`); `EGG` is a sentinel defined AFTER that list and outside it (C `:276`, G `:271`, behind a `const_skip`), so it is never a dex index. Item ids come from `constants/item_constants.asm` and the evolution families from `data/pokemon/evos_attacks.asm` via the generator, not from a line range (items: `pret_gen2_symbols.md` §8; species/dex: §12) | generators | — (SOURCE-only, P = —) | · | · | — |
| F-6 | Fixtures from scripted play: `<title>_town` (Elm's lab after the starter, encounter-free) and `<title>_battle` (Route 29 grass) for crystal/gold/silver, plus `crystal_{town,battle}_ot2` played under a second OT for the Crystal↔Crystal A/B pair and the wrong-save control (Gen 1 `town_ot2` fixture precedent, `tools/gen1_fixtures.py:46` `CHAINS["town_ot2"]`; second-OT refusal `:49-50`, `:310`); every save cold-boots → CONTINUE → re-saves → reloads with PYDEC/GAME agreement; each passes `VerifyChecksum`, loads with `TryLoadSaveFile`, PYDEC party matches the party-menu tilemap. **Owner-approved exception O-10 (2026-09-21):** Poké Balls are injected into the Ball pocket for the `battle` fixture because no ball exists before the Mr. Pokémon errand (the aide's grant is the earliest Poké Ball: Crystal `maps/ElmsLab.asm:498-508`, `giveitem POKE_BALL, 5` at `:504`; Gold `:455-465`, `:461`. No earlier source exists: the Cherrygrove mart stocks balls only after `EVENT_GAVE_MYSTERY_EGG_TO_ELM`, `maps/CherrygroveMart.asm:13-20` with `MartCherrygrove` vs `MartCherrygroveDex` at `data/items/marts.asm:40-54`, line-identical in both repos); the starter and the walk are played. On the limits list | pret load path Crystal `engine/menus/save.asm:596-640` (`TryLoadSaveFile:596`), Gold `TryLoadSaveFile:538+` | GAME + PYDEC | · | · | · |
| F-7g | Gold and Silver admission rows are distinct (wild tables differ: `data/wild/johto_grass.asm:341-364`), one shared profile | pret | — (SOURCE-only, P = —) | · | · | — |

## R — Reads (`lua/gen2/reads.lua`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| R-1 | Party/box/name decode == PYDEC on raw dumps from all three titles (48-byte party, 32-byte box struct, 20 per box, 14 boxes) | PYDEC | · | · | · |
| R-2 | Stats pass the known-positive control (`CalcMonStats`; Sp.Atk/Sp.Def from one Special stat-exp) | CONTROL | · | · | · |
| R-3 | Trainer class/id, badges (Johto+Kanto), held item byte, active box index | GAME | · | · | · |
| R-4 | Title screen never validates; soft reset pauses writes; hello waits for the overworld checkpoint or a running battle | GAME | · | · | · |
| R-5g | Gender and shininess derived from DVs match the game's own display | GAME | · | · | · |

## S — Signals (`lua/gen2/signals.lua`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| S-1 | Every site fires exactly at its routine; differential gate across the three titles | ENGINE | · | · | · |
| S-2 | Capture: party vs box decided at the `TryAddMonToParty` / `SendMonIntoBox` fork (`item_effects.asm:548-550`); ball consumption observed from the Ball pocket | ENGINE + PYDEC (method: bag result read back) | · | · | · |
| S-3 | Party full → successful box insertion, observed independently of `BATTLERESULT_BOX_FULL`. Line numbers differ per repo: Crystal `engine/items/item_effects.asm:609-618` (`.SendToPC:609`, `predef SendMonIntoBox:612`), flag set at `:623` only when `sBoxCount` reaches `MONS_PER_BOX` after insertion (`:619-624`); Gold `.SendToPC:607`, insertion `:610`, count check `:615-617`, flag `:619`. Controls: non-final slot and twentieth slot | ENGINE | · | · | · |
| S-4 | Player faint at `UpdateFaintedPlayerMon` (Crystal `engine/battle/core.asm:2656-2688`, Gold `engine/battle/core.asm:2551-2583`, each span = routine label through the `wBattleResult` store; routine ends C `:2693` / G `:2588` — never one repo-wide offset; Gold and Silver share `0f:50f4`, Crystal `0f:51aa`), poison faint at `DoPoisonStep` (`engine/events/poisonstep.asm:1` in both repos; G/S `14:4610`, C `14:45da`); faint-time party bytes captured before `HealParty` (`whiteout.asm:14`) | ENGINE | · | · | · |
| S-5 | Evolution and NPC trade emit `key_change` at the species-publication site | ENGINE + SERVER (method: wire receipt of `key_change`) | · | · | · |
| S-6 | PC deposit/withdraw/release/box change observed (no `ChangeBox` symbol exists: `_ChangeBox` C `engine/pokemon/bills_pc.asm:2224` / G `:2202`; menu `BillsPC_ChangeBoxMenu` `engine/pokemon/bills_pc_top.asm:226` both; save-path `ChangeBoxSaveGame` C `engine/menus/save.asm:39` / G `:40`; ticket 12's site table picks the site); release of a boxed linked mon logged (shared-protocol gap) | ENGINE | · | · | · |
| S-7 | Save witness taken at the success-only save boundary — completion of `_SaveGameData` (Crystal `engine/menus/save.asm:266-295`, Gold `:273-292`; completion = the routine's final `ret`, C `:295` / G `:292`, not the `SaveBackupChecksum` call at C `:281` / G `:288`), never an entry hook, which proves an attempt and not a save — with the raw CartRAM bytes as the durability witness (PLAN §5.6); CONTINUE vs New Game distinguished | ENGINE + SERVER | · | · | · |
| S-8 | Statics and gifts observed at their acquisition sites; egg HATCH published as a gift capture under `gift_daycare` with the hatchling's key (O-15), never at `GiveEgg` | ENGINE + SERVER (method: `gift_daycare` publication receipt) | · | · | · |
| S-9g | Roaming legendary (Raikou/Entei/Suicune) capture is an extra catch: standalone `legend_<species>` pair, the map's encounter neither consumed nor locked (O-17) | ENGINE + SERVER | · | · | · |
| S-10g | Bug-Catching Contest capture links under its own zone `national_park_contest` (O-18) | ENGINE + SERVER | · | · | · |

## W — Writes (`lua/gen2/writes.lua` + `lua/gen2_write_safety.lua`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| W-1 | One armed write gate; validate before the first byte; provenance log. The physical claim is temporal — *no byte leaves the gate unarmed or unvalidated* — so the oracle is the observed write-site/sink provenance during the run, with forbidden-state controls (an unarmed attempt and an out-of-bounds payload must be refused with nothing written), plus PYDEC over the resulting provenance records. Fake-IO tests are MODEL and stay MODEL; a final saved-party comparison is an end-state check and never closes the temporal claim | ENGINE + PYDEC (method: write-site/sink provenance with forbidden-state controls) | · | · | · |
| W-2 | In-battle `force_faint` lands at the battle-loop head; retry-at-tail only for party-full / last-party-mon | ENGINE + GAME | · | · | · |
| W-3 | Explode Mode (if the owner keeps it for Gen 2) | ENGINE | · | · | · |
| W-4 | Rival team swap (if kept) | GAME | · | · | · |
| W-5 | Memorial box write to Box 14 (`sBox14` flat `0x79E0`) never targets the ACTIVE box and survives the game's own `SaveBox` copyback inside `_SaveGameData` (Crystal `engine/menus/save.asm:266-295`, `call SaveBox` `:275`; Gold `:273-292`, `:282`) and a SAVE with Box 14 active | GAME + PYDEC | · | · | · |
| W-6 | Writes refused before the first SAVE and around New Game overwrite. Per repo: the game's own `SaveBox` copyback runs inside `_SaveGameData` (Crystal `engine/menus/save.asm:266-295`, `call SaveBox` at `:275`; Gold `:273-292`, `:282`). `wSavedAtLeastOnce` is *tested* at `HallOfFame_InitSaveIfNeeded` (Crystal `:470-475`) and *set* in `ErasePreviousSave` (Crystal `:360-375`, Gold `:333-345`), which is the New Game erase path; the ordinary overwrite prompt is `AskOverwriteSaveFile` (Crystal `:181-207`, Gold `:169-195`; its `call ErasePreviousSave` at C `:199` / G `:187`) | GAME | · | · | · |
| W-7 | Whiteout rebuild through the shared path; `HealParty` ordering respected | SERVER + PYDEC | · | · | · |

## C — Client and adapter (`lua/gen2/client.lua`, `server/adapters/gen2_gsc.py`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| C-0 | Protocol conformance (`docs/protocol.md` §9) on the production `Entry.build` graph under lupa. **MODEL-only obligation by design** (schema/world row, no P cell); each §9 assertion is nevertheless mapped in the coverage map to the live scenario that exercises it, or marked SOURCE/MODEL-only there. Method: schema tests on the production `Entry.build` graph | — (MODEL-only by design) | · | · | — |
| C-1 | Hello carries `rom_sha1`, `ot_id`, foundation/kind; admission refuses unknown sha1 | SERVER | · | · | · |
| C-2 | Reconnect same-save / wrong-save / WRAM clear behave as Gen 1 C-1/C-2 | SERVER | · | · | · |
| C-3 | HUD text through `hud.sanitize`; panel rows | GAME | · | · | · |
| C-4 | Fault injection (by construction). **MODEL-only obligation by design** | — (MODEL-only by design) | · | · | — |
| C-5 | Randomized admission (if UPR extends to Gen 2; else a recorded limit) | SERVER | · | · | · |
| C-6g | Pairing: every Gen 2 pairing admitted through one foundation `gen2_gsc` (O-16), every rom_type alias mapped, arrival order / reconnect / persisted run covered; a Gen 2 half never pairs with a Gen 1 or Gen 3 half; a rejected hello leaves state, cache and disk unchanged; no `game_id` branch | SERVER | · | · | · |

## D — Rules engine under Gen 2 (duo lane; `server/state.py` proven, not rewritten)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| D-1 | Encounter link on both sides, on the release duo matrix C↔C, G↔S and C↔G (O-16) (`tests/gen2_release_requirements.json`, lane `duo-link`: a missing pair, scenario, oracle or receipt is red). **P ◐:** C↔C `link` PASS, receipts `tests/fixtures/gen2/receipts/duo_link_cc_{a,b,pydec}_result.txt`; G↔S and C↔G OPEN until their receipts land | SERVER + PYDEC | · | · | ◐ |
| D-2 | Ball gate from the Ball pocket | SERVER | · | · | · |
| D-3 | Party/box sync + box change (`_ChangeBox` C `engine/pokemon/bills_pc.asm:2224` / G `:2202`; see S-6) | PYDEC | · | · | · |
| D-5 | Clauses (species / gender / type); shiny bonus pairs (Gen 2 has shinies) | SERVER | · | · | · |
| D-6 | Linked faint propagation (benched + active) | PYDEC | · | · | · |
| D-7 | Whiteout rebuild | PYDEC | · | · | · |
| D-11 | Rival swap / explode (if kept) | GAME | · | · | · |
| D-12 | Game-over HUD, or explicit recorded limit | GAME (method: transient overlay measurement) | · | · | · |
| D-13 | Key collision refusal: on an ambiguous key the resolver writes nothing on either lookup path and the colliding capture is refused. **MODEL-only obligation by design** — the obligation is the refusal-on-ambiguity behaviour, following the Gen 1 D-13 precedent (`docs/gen1_requirements.md:117`); no collision-rate figure is asserted as a Gen 2 fact | — (MODEL-only by design) | · | · | — |
| D-14 | Reconnect keeps links | SERVER | · | · | · |

## T — In-game trade (companion patch)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| T-1 | Receptionist / Trade Center entry at every Center (design per ticket 15) | GAME | · | · | · |
| T-2 | Partner answers the cartridge's own YES/NO; decline leaves both saves unchanged | GAME + PYDEC | · | · | · |
| T-3 | Trade applies to both saves; trade evolution handled; the held item is validated and carried with the mon (O-14), an invalid item is refused before commit, item readback on both halves | PYDEC | · | · | · |
| T-4 | Save reload after trade shows the traded mon: the reloaded record and its held item ARE the traded record (not merely a same-species mon) | GAME + PYDEC | · | · | · |

## N — Native panel and sound (companion patch)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| N-1 | START-menu SLINK panel rows (mailbox per ticket 14) | GAME | · | · | · |
| N-2 | Native sound codes at the qualified ticket-16 main-thread service site(s), with bounded overworld/menu/battle coverage and reset controls | GAME | · | · | · |
| N-3 | Peer ghost, **post-RC (O-13)** — P5 starts only after G6 (gate only if ticket 17 says feasible) | GAME | · | · | · |

## Not in this release (to be confirmed by the owner)

Archipelago Crystal beyond profile generation (O-8); peer ghost (post-RC, O-13); Time Capsule trades
and mail (O-14; held items ARE carried, T-3); `playthrough`/`deadzone`/`dupes` Gen 2 scenarios (closed
decision); the unselected Crystal revision (O-12: build-reproducibility evidence only, refused unless
separately admitted); non-US ROMs; Battle Tower; Mobile Adapter.

## Coverage map

`docs/gen2/gen2_coverage_map.md` (P2 deliverable) maps every row above and every `docs/protocol.md` §9
assertion to stimulus, artifact, controls, oracle, receipt marker and lane. Any UNMAPPED row blocks G2; zero UNMAPPED permits completeness sign-off, not physical closure (physical SAMPLE coverage stays OPEN until the owning lane runs).

## Recorded limits

O-10: the `battle` fixtures carry bag-injected Poké Balls (F-6); ball-acquisition itself is not a qualified path.

Otherwise empty until the first live lane runs. The Gen 1 limits list (`docs/gen1_requirements.md:161-189`)
is the template.
