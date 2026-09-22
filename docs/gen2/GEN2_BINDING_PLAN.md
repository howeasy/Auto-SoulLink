# Gen 2 binding plan: Crystal, Gold and Silver onto the shared framework

Editorial reconciliation: planning source cut `9c7e7acfef1a5c2e1dc7111e8dfdb0c71610b043`, using
`docs/gen2/PLAN.md` §0, §4-§6 and `OPEN_QUESTIONS.md`, with owner rulings and review returns in
`REVIEW_RECORD.md`. Latest owner rulings override historical annex text. No new source research or
runtime qualification is claimed; all gates remain unsigned.

Historical citation baseline: worktree `gen2-planning-kickoff-a18801`, HEAD `4bf0f3b` for §§0-4 and
§§6-8, and `555de91` for the §5 rewrite and its related amendments. Unmarked implementation
`file:line` citations and size estimates refer to that baseline, not a fresh source audit.
`SWEEP path:line` is the Gen 1 sweep worktree `gen1-rby-code-sweep-8d06e2` (HEAD
`011e72b`), which is where `docs/FRAMEWORK.md` and the 37 `docs/shared-*.md` contracts live —
they are **not** in this tree. Research citations are `docs/gen2/research/<file>.md:line`; pret
citations are `pokecrystal@7a7881d …` / `pokegold@656583c …` as the research notes pinned them.

Companion to the Gen 3 plan (`SWEEP docs/gen1_reference/GEN3_BINDING_PLAN.md`, 399 lines), which
this mirrors in shape. The difference is the mandate: Gen 3 is a **port** of a live client onto
shared modules; Gen 2 is a **rewrite** (O-3), so the question "which shared module does Gen 2
bind" is asked of a client that does not exist yet, and the existing Gen 2 code is a hypothesis
about the cartridge, never a design input.

Scope: this is a plan, not a spec and not implementation. It answers three questions — what Gen 2
binds, what Gen 2 owns, and why each game-specific thing has to be game-specific. It closes no
row of any release ledger.

---

## 0. Owner decisions this plan is built on

| # | Ruling | Cite | What this plan does with it |
|---|---|---|---|
| O-1 | "This will lead into implementation" | `docs/gen2/REVIEW_RECORD.md:15` | Every section ends in something a spec can consume: a module list, a binding table, an ordered step with a falsifier |
| O-2 | "Include GSC. Crystal is most important but all should be done" | `docs/gen2/REVIEW_RECORD.md:16` | Gold and Silver are full admission packs, all three packs are P2 products signed at G2, Crystal only the first increment (§5 P2.5), not a variant flag |
| O-3 | "Trash Gen2 code once we replace it. Gen1 is canonical" | `docs/gen2/REVIEW_RECORD.md:17` | §1 follows PLAN §4's REMOVE/REPLACE split; §3 uses Gen 1's module boundaries with O-19's bounded shared mechanisms, not whole-module copies; existing Gen 2 code is historical inventory only |
| O-4 | "All native feature should exist in first RC" | `docs/gen2/REVIEW_RECORD.md:18` | Native trade, START-menu panel and native sound are RC work at P4 (§5 P4.1-P4.3), not a phase 2 |
| O-5 | "Move to fresh upstream HEAD" | `docs/gen2/REVIEW_RECORD.md:19` | pret pins `pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651`, `pokegold@656583c939d30f920a316177311a502dd222b57c`; AP pin `6.0.0-rc.1` = `0b11931c` (`docs/gen2/research/archipelago_crystal.md:369-373`) |
| O-6 | "Gen2 new ledger" | `docs/gen2/REVIEW_RECORD.md:20` | `docs/gen2/gen2_requirements.md` + `tests/gen2_release_requirements.json` + `tools/verify_gen2_release.py`, mirroring `tools/verify_gen1_release.py` |
| O-7 | Matt Pocock skills setup, local-markdown tracker | `docs/gen2/REVIEW_RECORD.md:21` | The step list in §5 is the ticket source; `docs/agents/issue-tracker.md` holds them |
| O-10 / round 2 | Scripted fixtures; Poké Balls may be injected for tests | `docs/gen2/PLAN.md` §0, §5.7, §8 | Eight newly played and qualified saves at P3b.2; the starter and walk stay played; the legacy fixture is no evidence |
| O-12 | Use the local Crystal dump's revision | `docs/gen2/REVIEW_RECORD.md` O-12; `OPEN_QUESTIONS.md` A-1 | Hash at P1; admit that revision only; the other is build evidence and a recorded limit |
| O-13 / AP ruling | Peer ghost and Archipelago are post-RC | `docs/gen2/PLAN.md` §0; `REVIEW_RECORD.md` O-13 and round 2 | P5 starts after G6; AP remains documented backlog, unadmitted and excluded from ticketing |
| O-14 / O-15 / O-17 / O-18 | Trade extras and acquisition policies settled | `docs/gen2/PLAN.md` §0 | Held items carried and validated; Time Capsule/mail limits; hatch = `gift_daycare`, roamer = `legend_<species>`, contest = `national_park_contest` |
| O-16 | One family; every Gen 2 pairing | `docs/gen2/REVIEW_RECORD.md` O-16 | One `gen2_gsc` foundation; C↔C and G↔S representative lanes plus a C↔G `link` receipt |
| O-19 / O-20 | Share bounded mechanisms; use the approved integrated base with drift watch | `docs/gen2/REVIEW_RECORD.md` O-19/O-20; `PLAN.md` §5.15, §5.9 | Existing shared modules first, extraction cards for copied mechanisms; G0 records master + `80261f3` + `959c578` + `910dbdd`, then drift is checked at every gate |

Round-1 fact check `cx-3569f8d9` accepted 6/6 premises (`docs/gen2/REVIEW_RECORD.md:44`); its six
rows are cited individually in §4.

---

## 1. Historical starting inventory and current cutover disposition

The sizes and implementation descriptions below are **historical inventory**, not evidence of
correctness or a current measured census. The cutover dispositions follow PLAN §4; P3b.8 verifies
the exact paths and replacement hashes before removal. The Gen 2 client was "forked
from the (since-retired) legacy Gen 1 client" (`lua/clients/gen2_crystal_client.lua:5`) — the
ancestor the Gen 1 rewrite replaced.

| File | Lines | What it is | Fate at cutover |
|---|---:|---|---|
| `lua/clients/gen2_crystal_client.lua` | 1484 | monolithic client, own event loop, own dispatcher | DELETE (replaced by `lua/gen2/*`) |
| `lua/games/gen2_crystal.lua` | 612 | detection, memory profile, ball ids, area resolution | DELETE (profile becomes a generated pack) |
| `lua/games/gen2_crystal_trainers.lua` | 164 | trainer table in Lua | DELETE (becomes `data/games/gen2_crystal/trainers.json`) |
| `lua/gen2_crystal_areas.lua` | 133 | area table at the `lua/` root, not under `games/` | DELETE (pack file) |
| `lua/gen2_crystal_locations.lua` | 90 | location names at the `lua/` root | DELETE (pack file) |
| `lua/slink_gen2.lua` | 18 | hard-coded host/port launcher that `dofile`s the client | **REMOVE** at cutover (§5 P3b.8); the Gen 2 route lives in `lua/slink.lua` instead. PLAN §5.11b (`docs/gen2/PLAN.md:148`) rules out a Gen 2 shim, so it is neither rewritten nor re-pointed; §5 P3b.6 owns the route and §5 P3b.8 executes the removal |
| `server/adapters/gen2_crystal.py` | 416 | `Gen2CrystalAdapter(GameAdapter)` (`:135`) | DELETE → `server/adapters/gen2_gsc.py` |
| `data/games/gen2_crystal/` | 8 files | `area_map`, `encounter_tables`, `gender_ratios`, `item_names`, `moves`, `species_types`, `trainers` | REGENERATE as three packs (§3) |
| `lua/tests/gen2_playthrough.lua` + `lua/tests/{probe_,test_}gen2_*.lua` | 15 files (PLAN §4's explicit inventory) | legacy fixture driver, probes and gates | REMOVE the 15 named legacy paths; new P3b drivers are separate files |
| `tests/unit/test_gen2_{adapter,ap_addresses,ball_items}.py` | 914 / 112 / 130 | adapter unit tests | REPLACE `test_gen2_adapter.py` in place; REMOVE `test_gen2_{ap_addresses,ball_items}.py` |
| `tests/e2e/test_duo_gen2.py`, `tests/live/test_gen2_gates.py` | 79 / 72 | duo + live harness entries | REMOVE; successors are `test_duo_gen2_new.py` / `test_gen2_new_gates.py` |
| `tools/gen_gen2_{area_map,encounters,trainers}.py` | 84 / 396 / 193 | three generators | KEEP the pattern, extend to the full `tools/gen_gen2_*.py` set (§3) |
| `tools/gen2_playthrough.py` | 216 | legacy fixture builder | REMOVE; P3b.2 uses `tools/gen2_fixtures.py` and scripted route modules |
| `tests/fixtures/gen2/crystal_town.SaveRAM` | — | legacy Gen 2 fixture, no rewrite evidence | REPLACE at the same path with P3b.2's played and qualified save; never unlink the validated replacement (§5 P3b.8) |
| `lua/memory_gb.lua` | 1499 | legacy combined GB game-memory helper | REMOVE under PLAN §4; new Gen 2 reads bind generated profiles and bounded shared mechanisms |

Registry rows that survive the delete because runs persist their `rom_type`
(`server/adapters/__init__.py:54-57`): `"Crystal"/"crystal"/"Gold"/"gold"/"Silver"/"silver"/"Crystal (AP)"/"crystal_ap"`
all map to `gen2_crystal` (`:63-66`). The new adapter registers under a new `game_id` and these
eight rows re-point to it; deleting them would orphan existing runs (`:56-57`).

Two facts about the old code that the rewrite must not inherit:

- Gold and Silver are routed to a **Crystal** adapter (`server/adapters/__init__.py:64-65`) and a
  module whose display name is "Crystal / Gold / Silver" (`lua/games/gen2_crystal.lua:13`). Codex
  refuted the premise that underwrites this: wild tables differ between Gold and Silver
  (`pokegold@656583c data/wild/johto_grass.asm:341-364`, `docs/gen2/REVIEW_RECORD.md:40`).
- The registry comment records that Gold, Silver and Crystal (AP) were *missing* from
  `_ROM_TYPE_TO_GAME_ID` and the failure was silent — "every Gen 2 claim that did not come from a
  Crystal run rested on that" (`server/adapters/__init__.py:59-62`). Treat every non-Crystal Gen 2
  claim in the tree as unproven.

The Gen 2 client is also missing features Gen 1 has: "NOT YET IMPLEMENTED (Gen 1 has them):
trainer_battle_start / rival_team_replaced" (`lua/clients/gen2_crystal_client.lua:40`).

---

## 2. Shared modules Gen 2 binds

**Historical baseline, not an instruction to freeze the shared surface.** The shared
spine described by `SWEEP docs/FRAMEWORK.md` (91 module rows, `:262`) — the durable runtime,
protocol journal, staged state, trade coordinator, identity registry, held-write permit, command
executor, observation stream, `platform_saveram` and `platform_execution` — **is not in this tree.**
`server/` at `4bf0f3b` holds 23 Python modules and none of those; `lua/` holds 20 top-level files
and none of those. The Gen 1 rewrite that landed on master binds none of them either:
`lua/gen1/entry.lua:302-308` `dofile`s only `lua/json_codec.lua` and its own siblings, and
`lua/gen1/run.lua:14-16` adds only `connector` and `hud`.

The approved implementation base is master + `80261f3` + `959c578` + `910dbdd` (O-20); G0 must verify
and record it with the drift baseline. The archived spine is vocabulary, not an implementation
dependency (`OPEN_QUESTIONS.md` B-23). Gen 2 binds the existing shared set below and PLAN §5.15's
bounded mechanisms; O-19 supersedes any historical implication that no extraction is allowed.
Shared client lifecycle, queues, reconnect, transport, state and presentation reuse those
mechanisms. Game facts, signal handlers and game policies remain Gen 2 inputs; a Gen 1 twin is
not permission to clone its generic lifecycle.

| Module | Contract | How Gen 1 binds it | How Gen 2 binds it | Game fact the adapter supplies |
|---|---|---|---|---|
| `server/state.py` `SoulLinkState` | the Soul Link rule engine; `handle_event` `:273`, `_handle_capture` `:1252`, `_handle_faint` `:1740`, `_handle_no_catch` `:1877`, `_handle_whiteout` `:2028`, `_handle_party_to_box` `:2112`, `_handle_box_to_party` `:2160`, `_handle_key_change` `:2542`, `_propagate_faint` `:2863`, `_handle_memorialize_done` `:2949`, `_handle_trainer_battle_start` `:3084` | through the wire, via the adapter at `server/server.py:416-430` | identically; **no new handler, no `game_id` branch** | every clause input via the adapter (`docs/protocol.md:432-452`) |
| `server/adapters/base.py` | `GameRulesAdapter` `:64`, `GamePresentationAdapter` `:325`, `GameAdapter` `:582`; inert defaults incl. `rival_trainer_ids` `:204`, `party_blob_size` `:220`, `supports_explode_mode` `:282`, `set_artifact_kind` `:297`, `native_trade_ui` `:308`, `rom_content_fingerprint` `:403`, `mons_per_box` `:518`, `memorial_box_index` `:529` | `Gen1Adapter(GameAdapter)` `server/adapters/gen1_rby.py:265`; `Gen1PureRGBAdapter(Gen1Adapter)` `gen1_purergb.py:66` | `Gen2GSCAdapter(GameAdapter)` in `server/adapters/gen2_gsc.py` | all of §3's adapter column |
| `server/adapters/base.py:559` `gb_status_token` | shared GB status decode (the SLP/PSN/BRN/FRZ/PAR bit layout GB games share) | `gen1_rby.py:356-358` | same helper, unchanged — Gen 2's status byte is the same GB layout | none; this existing helper is reused alongside the bounded §5.15 mechanisms |
| `server/adapters/__init__.py` | registry + `rom_type` routing `:96-101`, `variant_label` `:104-106` | `:130-136` registers `gen1_rby`, `gen1_purergb` | one `register_adapter("gen2_gsc", …)`; the eight legacy Gen 2 `rom_type` rows re-point | `rom_type` strings the client sends in HELLO |
| `server/pokemon_data.py` | species/type/key helpers | `gen1_rby.py:14` imports it | same import | nothing; Gen 2 species are NatDex 1..251 already (`pokecrystal@7a7881d constants/pokemon_constants.asm:171-174,273-274`) |
| `server/server.py` | TCP framing, admission `_decide_admission` `:513`, adapter switch `:416-430`, panel gate `:592-598`, `_build_link_panel` `:1381` | Gen 1 answers `rom_content_fingerprint` (`gen1_rby.py:472`) and `supports_info_panel` (`:360`) | same two hooks; a Gen 2 fingerprint closes admission | ROM sha1 / artifact kind |
| `lua/connector.lua` | newline-JSON TCP, `init/send/receive/pump/connected` | `lua/gen1/run.lua:15`, injected as `deps.net` (`lua/gen1/entry.lua:371`) | injected identically by `lua/gen2/run.lua` | none |
| `lua/json_codec.lua` | bounded JSON codec | `lua/gen1/entry.lua:303`, `lua/gen1/run.lua:31` | identical `dofile` | none |
| `lua/hud.lua` | overlay + the canonical `sanitize` ASCII fold | `lua/gen1/run.lua:16`; sanitizer handed to the panel at `lua/gen1/entry.lua:366` | identical; **all** Gen 2 on-screen text routes through it | Gen 2's own native glyph encoding stays in `lua/gen2/panel.lua` |
| `lua/sfx_arbiter.lua` | one sound cue per frame, priority ranks, `native_ok` routing (`:1-14`, `A.new(ranks)` `:27`) | the Gen 1 client passes its own SE constants (`:20`: "Pass the caller's own SE constants … never literals") | same, with Gen 2 SE constants | the sound id table |
| `lua/slink.lua` | universal entry; Gen 1 route `:64-75`, `_CLIENT_MAP` `:86-91`, dispatch `:93-99` | `:69-71` `dofile`s `gen1/entry.lua` then `gen1/run.lua` before the registry | Gen 2 detect-then-`lua/gen2/run.lua` route before `game_detect`, per PLAN §5.11b; no launcher shim | `Entry.detect_title` equivalent |
| `lua/game_detect.lua` | registry/priority dispatch over `lua/games/*` | bypassed for Gen 1 (`lua/slink.lua:83-85`: no `gen1_rby` row, "a row here could only ever mis-fire") | **bypassed the same way**; Gen 2 detection moves into `lua/gen2/entry.lua` | header title + sha1 |
| `lua/memory_gb.lua` (1499) | platform memory profile for GB, "Gen 1 and Gen 2" by its own header | **unbound** by the Gen 1 rewrite — `lua/gen1/entry.lua` never loads it | **do not bind.** Gen 2 reads come from `lua/gen2/reads.lua` over a generated profile, as Gen 1 does | — |
| `tools/release_lanes.py` at `910dbdd` | shared fail-closed release-runner core in the approved base | `tools/verify_gen1_release.py` binds the core at that cut | `tools/verify_gen2_release.py` binds the same core at P2.7; no second core | Gen 2 lane registrations and manifest |

Not bound, deliberately: `lua/mailbox.lua` and `lua/peer_ghost_npc.lua` are the Gen 3 EWRAM
endpoint and the Gen 3 object-event ghost (`SWEEP docs/FRAMEWORK.md:251-252`), not shared despite
unprefixed names. `lua/memory_gba.lua`, `lua/memory_nds.lua` are other platforms.

The wire contract Gen 2 must satisfy is `docs/protocol.md` §3-§6, and the twenty Gen 3-isms at
`docs/protocol.md:491-516` are the checklist: Gen 2 must re-encode `stat_stages` to the 0-12/6-neutral
form (`:502`), split PP-Ups out of the PP byte (`:503`), send `ot_id` in HELLO or override
`parse_ot_id` (`:504`), override `party_blob_size` (`:505`), send `species_id` always (`:500`), send
`key_change{…reason:"evolution"}` because a Gen 2 key embeds species (`:515`), and send `panel`/
`panel_abi` if it wants a native panel with a nonzero width (`:507`). The historical protocol says
"Gen 2 has no binding" for `play_sound` (`:497`); P3a.2 records the Gen 2 binding and P4.2 qualifies
it using the Gen 2 SE table in `panel.lua` and the shared `lua/sfx_arbiter.lua`.

---

## 3. Gen 2-owned modules

The rewrite follows Gen 1's composition boundaries, with thin binders over reusable mechanisms.
The Gen 1 twin column is reading context, not a copying instruction. The "why game-specific"
column identifies the facts and policies that stay in Gen 2; PLAN §5.15 controls extraction of
bounded shared mechanisms, including generic lifecycle, queues, reconnect and presentation.

### 3a. `lua/gen2/*`

Read with the PLAN §5.15 per-candidate verdicts (`docs/gen2/PLAN.md:151-161`): the **5.15 verdict**
column says whether the file is a *thin binder* over an extracted mechanism or a *per-game
implementation*. A binder row still owns every game fact the card takes as a required input.

| File | Owns | Why it is game-specific | Gen 1 twin | 5.15 verdict |
|---|---|---|---|---|
| `entry.lua` | composition root: `PACKS`, `PACK_FILES`, `admission_table`, `anchor_matches`, `admit`, `build`, `detect_title`, `bizhawk_deps` | three packs (`gen2_crystal`, `gen2_gold`, `gen2_silver`) and three ADMITTED titles — Gold, Silver and the local dump's Crystal revision only (O-12, §4 row 12); the `rom_type` table (`Crystal`/`Gold`/`Silver`) | `lua/gen1/entry.lua:44,58,133,197,229,300,394,403` | thin binder over 5.15d (`Entry.admit` decision framework); per-game: catalog, anchors, packs, title detection |
| `run.lua` | thin BizHawk bootstrap composing io, shared transport/HUD and the client | all three titles pin CGB mode (PLAN §5.10); Gen 2 pack and memory bindings | `lua/gen1/run.lua:1-16` | game binder; reuse shared transport, presentation and bounded lifecycle mechanisms, with no private copies or wrappers (5.15j) |
| `client.lua` | Gen 2 signal handlers and game policies composed over injected shared parts | signal interpretation, write eligibility and native trade facts are Gen 2's | `lua/gen1/client.lua:135` (`Client.new`), `:909` `on_signal`, `:480` `handle_command`, `:716` `run_deferred`, `:1498` `send_hello` | game handlers/policies only; shared lifecycle, queues, reconnect, dispatch and presentation use bounded shared mechanisms under 5.15; the server trade FSM stays shared |
| `reads.lua` | pure WRAM/SRAM decoders over the generated profile + Gen 2 charmap | 48-byte party / 32-byte box structs, held item at +1, Sp.Atk/Sp.Def split (§4) | `lua/gen1/reads.lua:1-4` | per-game implementation (struct layout); binds 5.15g only for charmap token scanning |
| `signals.lua` | bus-exec hooks at pret CPU sites → typed signals; load-time `expected_hex` check | the P2.2 source-derived site table and bank register: faint at `UpdateFaintedPlayerMon`, whiteout at the CPU site before `HealParty`, hatch capture at hatch rather than `GiveEgg`; script labels are never bus-exec sites | `lua/gen1/signals.lua:1-16` | thin binder over 5.15a (hook registry core + `gb_*` platform binding); per-game: the site table |
| `writes.lua` | every byte the client writes, behind an armed window; validate-before-first-byte | Gen 2 party/battle struct offsets; no `wPlayerSelectedMove`-equivalent proven | `lua/gen1/writes.lua:1-16` | thin binder over 5.15b (permit + validated write); per-game: GB bank policy, faint/explode builders |
| `boxes.lua` | PC and memorial box moves through the armed cart-write gate | 14 boxes × 20 mons across two SRAM `SECTION`s, `BOX_LENGTH` 0x450, no per-box checksum but a `SaveBox` copyback hazard (§4) | `lua/gen1/boxes.lua:1-11` | per-game implementation — 5.15e is KEEP-PER-GEN; binds only `gb_*` bank:address→flat and the validated-span executor |
| `rom.lua` | the ROM tables the client reads from the cartridge (base stats, and whatever the randomizer story needs) | Gen 2 base-stat record layout and its own table addresses | `lua/gen1/rom.lua:1-11` | per-game implementation (read-only, P2; paired with `server/adapters/gen2_rom_scan.py` for F-4 two-path equality) |
| `panel.lua` | Gen 2 panel/mailbox bindings, capability values and SFX requests | Gen 2's own qualified mailbox address, tilemap address, SE table and charmap | `lua/gen1/panel.lua:16,19,24-25,45-48` | thin binder over 5.15f (`gb_*` panel core, versioned); shared ownership, pagination, queue/consumption and rendering mechanisms; per-game values are required inputs |
| `trade_overlay.lua` | foreground native trade over the borrowed serial/map storage; token-qualified completion | Gen 2's own lease magic and its own receptionist ABI | `lua/gen1/trade_overlay.lua:5-7` | per-game implementation (lease magic, receptionist ABI); the FSM is shared via `native_trade_ui()` |
| **`lua/gen2_write_safety.lua`** (at the `lua/` root, **not** inside `lua/gen2/`) | the read-only main-thread write checkpoint: the per-game state/ownership predicate over the generated `write_checkpoint.json` | Gen 2's own overworld anchor and predicate bytes; the Gen 1 checkpoint names `gen1-main-loop-v1`/`-purergb-v1` explicitly (`lua/gen1_write_safety.lua:14-15`) | `lua/gen1_write_safety.lua:1-15` (Gen 1 mirror; §7 Q8 settled — keep the root placement) | thin binder over 5.15c (`gb_checkpoint` evaluator: anchor re-verification, bounded stack reads, caller/resume predicates) **plus** a per-game implementation of the state/ownership predicate, which §6 keeps per game |
| ~~`sound.lua`~~ | **not a planned file** (settled, PLAN §5.12): `lua/gen2/panel.lua` supplies the SE code table, capability and request binding; generic queue/consumption uses the shared panel mechanism | — | arbitration is the already-shared `lua/sfx_arbiter.lua` | not a file; the SE table is a per-game required input to 5.15f and to `lua/sfx_arbiter.lua` |

### 3b. `server/adapters/*`

| File | Owns | Why game-specific | Gen 1 twin | 5.15 verdict |
|---|---|---|---|---|
| `gen2_gsc.py` | `Gen2GSCAdapter(GameAdapter)`: gift/static/daycare areas, `evo_family`, `species_types`, `gender_from_key`, `is_shiny`, `party_blob_size`, `memorial_box_index`, `mons_per_box`, `rival_trainer_ids`, `native_trade_ui`, `supports_info_panel`, `info_panel_width`, `rom_content_fingerprint`, `gym_badge_slugs` | every value is a Gen 2 cartridge fact; the base defaults are inert on purpose (`server/adapters/base.py:204,220,282,308,403,518,529`) | `server/adapters/gen1_rby.py:265` | per-game implementation (adapter data; the shared compatibility machinery it feeds is P3a) |
| `gen2_codec.py` | the independent byte oracle: `decode_party_mon`/`encode_party_mon`, `decode_box`, `key`, `sav_checksum`, `verify_bank1`, `verify_boxes`, `calc_stat`, `exp_for_level`, `level_from_exp`, and a `Gen2Layout`/`for_foundation` seam for GS vs Crystal vs AP | it is derived from pret, not from SLink decoders, and it is the differential oracle the Lua reads are tested against | `server/adapters/gen1_codec.py:1-13,457,483,606,611,647,669,705,779,941` | per-game implementation — 5.15g extracts the **orchestration** (token scanning, fixture enumeration, report aggregation), never the oracle |
| `gen2_rom_scan.py` | the Python half of the two-path ROM reader: wild / headbutt / rock-smash / fishing / roamer tables and base stats, read independently of `lua/gen2/rom.lua` | Gen 2 table addresses and record layout; the equality is the evidence (F-4) | `server/adapters/gen1_rom_scan.py` | per-game implementation (P2.4) |

Gold and Silver do **not** get a second adapter class the way pureRGB did
(`server/adapters/gen1_purergb.py:66`): they share Gen 2's rules and differ only in data
(`docs/gen2/REVIEW_RECORD.md:40`). One class, three packs. If a rule ever diverges, subclass then —
not before.

### 3c. `data/games/gen2_{crystal,gold,silver}/` and generators

Artefact kinds follow `data/games/gen1_rby/` (16 files) and `data/games/gen1_purergb/` (23): the
kinds are `profile.json`, `engine_signals.json`, `write_checkpoint.json`, `area_map.json`,
`static_encounters.json`, `encounter_tables.json`, `species_index.json`, `evolutions.json`,
`gifts.json`, `moves.json`, `trainers.json`, `map_names.json`, `items.json`, `charmap.lua`,
`admission.json` — and the `_overlay` siblings for a companion-patched artifact
(`lua/gen1/entry.lua:58-83`, `Entry.pack_file` `:163-167`, `Entry.BASE_KIND` `:162`).

Generators mirror `tools/gen_gen1_*.py` (14 today: `admission_profiles`, `area_map`, `charmap`,
`encounters`, `engine_signals`, `evos`, `gifts`, `items`, `map_names`, `profile`, `species`,
`statics`, `trainers`, `write_checkpoint`) as `tools/gen_gen2_*.py`; three already exist
(`tools/gen_gen2_{area_map,encounters,trainers}.py`) and keep their names.

Every pack file must be named literally in `Entry.PACK_FILES`, because the release manifest derives
what to ship from those literals — "a pack file must be named here or a player never gets it"
(`lua/gen1/entry.lua:55-57`).

### 3d. `patch/gen2/`

Mirrors `patch/gen1/`: `src/*.asm`, `tools/{build,inject,manifest}.py`, `dist/`, `README.md`. The
Gen 1 patch is one manifest of 15 spans, Red and Blue byte-identical (`patch/gen1/README.md:20`),
carrying the START-menu SLINK row and panel plus the Cable Club SLINK TRADE receptionist
(`:22-29`), with sound consumed on the main thread at **two** sites — the `DelayFrame` bridge and
`Joypad`'s `call _Joypad` — because a menu spins in `HandleMenuInput_` and never reaches DelayFrame
(`patch/gen1/README.md:47-56`). This is historical Gen 1 rationale, not a Gen 2 site recommendation.
PLAN §5.12 and OPEN_QUESTIONS B-6 govern Gen 2: `Joypad` is a `reti` stub, `GetJoypad` is conditional,
and `DelayFrame` alone has no universal-service proof. Ticket 16 must qualify main-thread service
separately for movement, idle START menu, text, battle and transitions, with the P4.2 ABI and controls.

Gen 1's patch buys "zero additional rules" (`patch/gen1/README.md:42`) because the Gen 1 enemy party
is plaintext. Whether that holds for Gen 2 is §7 Q6.

---

## 4. The Gen 2 facts that force deviations from Gen 1

| # | Gen 2 fact | Cite | Gen 1 precedent | Deviation |
|---|---|---|---|---|
| 1 | Party struct 48 bytes (`PARTYMON_STRUCT_LENGTH` 0x30), box struct 32 (`BOXMON_STRUCT_LENGTH` 0x20) | `pokecrystal@7a7881d constants/pokemon_data_constants.asm:101,113`; `docs/gen2/research/pret_gen2_symbols.md:37,43` | 44 / 33 (`server/adapters/gen1_codec.py:35`) | `gen2_codec` field table is its own; `party_blob_size` = 48+11+11 = 70, vs Gen 1's 44+11+11 = 66 (`server/adapters/gen1_rby.py:335-337`) |
| 2 | Held item at struct offset 1 | `pokecrystal@7a7881d constants/pokemon_data_constants.asm:78`; research `:26` | Gen 1 has none | party snapshots carry a held item; the wire `party` entry grows a field `docs/protocol.md:223` |
| 3 | Special split into Sp.Atk / Sp.Def (`MON_STATS` = ATK/DEF/SPD/SAT/SDF, 5×`rw`) | `pokecrystal@7a7881d constants/pokemon_data_constants.asm:106-112`; research `:42` | one `spc` (`server/adapters/gen1_codec.py:31,33`) | `calc_stat`/stat-experience arithmetic is a Gen 2 twin, not a reuse; `stat_stage_labels` must expose the Gen 2 slot set (`server/adapters/base.py` default at `:507`) |
| 4 | 14 boxes × 20 mons; `BOX_LENGTH` 0x450 | `pokecrystal@7a7881d constants/pokemon_data_constants.asm:138,141,142`; research `:72-74` | 12 boxes × 20 (`server/adapters/gen1_codec.py:36`) | `mons_per_box` 20 (same), `memorial_box_index` 13 vs Gen 1's 11 (`server/adapters/gen1_rby.py:490-492`) |
| 5 | Boxes 1-7 occupy SRAM bank 2 and Boxes 8-14 bank 3; `layout.link` assigns them directly | `OPEN_QUESTIONS.md` B-16: `pokecrystal@7a7881d layout.link:375-378`; `pokegold@656583c layout.link:300-304` | Gen 1 box banks are literal in the codec (`gen1_codec.py:70` `box_banks`) | **SOURCE-resolved**, including the Box 14 flat-offset derivation `0x79E0`; the built `.map` verifies the artifact, not a missing source fact. Live `CartRAM` size/bank-linear binding remains †UNVERIFIED (B-10), closed by §5 P3b.5 |
| 6 | No per-box checksum — but `_SaveGameData` → `SaveBox` copies the active `sBox` over the `wCurBox` backing slot | `pokecrystal@7a7881d engine/menus/save.asm:266-281,521-524,874-973`; PLAN §5.5 | Gen 1 has per-box and all-box checksums (`gen1_codec.py:70-71`, `verify_boxes` `:669`) | no per-box checksum arithmetic; whole-save validation remains required. Refuse the memorial backing-slot write while `wCurBox == 13`, and re-assert after the next `_SaveGameData`. Ordinary current-box deposit/withdraw must succeed under the active-shadow/backing-store contract (P3b.5 positive control) |
| 7 | `ErasePreviousSave` → `EraseBoxes` clears all boxes; reached from `AskOverwriteSaveFile` `.erase` and from `HallOfFame_InitSaveIfNeeded` when `wSavedAtLeastOnce` == 0 | `pokecrystal@7a7881d engine/menus/save.asm:360-366,181-199,470-475,1038-1077`; `docs/gen2/REVIEW_RECORD.md:41` | Gen 1's `EmptyAllSRAMBoxes` first-save rule | the write checkpoint refuses memorial/box writes before the first SAVE and around New Game overwrite — a checkpoint *predicate*, not just an SP shape |
| 8 | Crystal is CGB-only (`rgbfix -C`); Gold/Silver are dual-mode (header 0x143 = 0x80) | `pokecrystal@7a7881d Makefile:169` via `docs/gen2/research/rom_hashes.md:82-86`; `docs/gen2/research/bizhawk_gambatte_gbc.md:159-180` | Gen 1 is DMG; `lua/gen1/entry.lua:274-292` `bank_safe_io` reroutes `$D000-$DFFF` through flat WRAM "bank 1 at 0x1000 in DMG mode too" (`:293-294`) | in CGB mode WRAM banking is live, so `bank_safe_io`'s Gen 1 assumption does not transfer. `Gambatte.IDebuggable.cs` bank-adjusts `0xD000-0xDFFF` "only in CGB (non-DMG-compat) mode" (`docs/gen2/research/bizhawk_gambatte_gbc.md:123`). Gen 2 reads `$D000+` through `System Bus` and lets the core resolve the bank |
| 9 | `wBattleResult` is a bitfield, not an enum; `BATTLERESULT_BITMASK` masks win/lose/draw before OR-ing flags like `BATTLERESULT_CAUGHT_CELEBI` / `BATTLERESULT_BOX_FULL` | `pokecrystal@7a7881d engine/battle/core.asm:2977-2980`, `engine/items/item_effects.asm:545,622-623`; research `:88` | Gen 1 has no equivalent cell | never compare `wBattleResult` for equality; mask first. A transient LOSE is not a whiteout (`docs/gen2/REVIEW_RECORD.md:42`) |
| 10 | `Script_Whiteout` calls `HealParty` **before** `WarpToSpawnPoint` | `pokecrystal@7a7881d engine/events/whiteout.asm:14,20`; `docs/gen2/REVIEW_RECORD.md:42` | Gen 1 signal S-4, same shape | faint-time party bytes are captured at the faint site, never after; the whiteout signal is armed at the **CPU site reached from `Script_Whiteout` before `HealParty`**, never at the script-bytecode label — `on_bus_exec` is never armed on a script label (5.3, `docs/gen2/PLAN.md:140`) |
| 11 | Gold and Silver share one WRAM/SRAM layout (no `_GOLD`/`_SILVER` branch in `ram/*.asm`) but differ in wild tables | `pokegold@656583c ram/wram.asm` (zero `_SILVER` matches, research `:215`); `data/wild/johto_grass.asm:341-364` via `docs/gen2/REVIEW_RECORD.md:40` | pureRGB is a whole second foundation with its own profile | **one profile, two data packs, two admission rows.** Not a variant flag, not a second adapter class |
| 12 | Crystal has two revisions: V1.0 `f4cd194bdee0d04ca4eac29e09b8e4e9d818c133`, V1.1 `f2f52230b536214ef7c9924f483392993e226cfb` | `docs/gen2/research/rom_hashes.md:77,90` | Gen 1's three titles each have one hash in `profile.json` (`lua/gen1/entry.lua:133-149`) | **admission carries exactly one Crystal row: the local dump's revision** (O-12, `docs/gen2/PLAN.md:32`; §5 P1.3). The other revision is built for reproducibility evidence only and is refused by admission unless separately admitted (`docs/gen2/gen2_requirements.md:139-142`). Gold `d8b8a3600a465308c9953dfa04f0081c05bdcb94`, Silver `49b163f7e57702bc939d642a18f591de55d92dae` (`rom_hashes.md:53,69`) |
| 13 | Cartridge is MBC3+TIMER+RAM+BATTERY — an RTC in the battery image | `pokecrystal@7a7881d Makefile:169` / `pokegold@656583c Makefile:190` via `docs/gen2/research/rom_hashes.md:62-63,83`; RTC lives in SRAM Bank 0 (`pokecrystal@7a7881d ram/sram.asm:6-56`, research `:156`) | Gen 1 is MBC3-less, SRAM `0x8000` flat, no RTC (`server/adapters/gen1_codec.py:73`) | the SaveRAM file is not just the 4×0x2000 SRAM image. The exact tail size BizHawk appends is **uncited** — §7 Q4 |
| 14 | BizHawk names the SaveRAM file from the gamedb entry (ROM content hash), not the launch path | `docs/gen2/research/bizhawk_gambatte_gbc.md:197-230` (confirmed against BizHawk 2.11.1 `src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs:233-244` (`research/bizhawk_gambatte_gbc.md:208-214`), BizHawk 2.11.1 `src/BizHawk.Emulation.Common/Database/Database.cs:270-307` (`research/bizhawk_gambatte_gbc.md:215-222`; not in any local tree)) | Gen 1's duo harness already works around it | two Gen 2 instances of one cartridge collide on one file; the duo harness needs a per-instance `saveram_dir` override, and a same-title pairing (Crystal/Crystal) is the risky case |
| 15 | Gen 2 internal species id == National Dex 1..251, contiguous | `pokecrystal@7a7881d constants/pokemon_constants.asm:171-174,223,273-274`; research `:191` | Gen 1 needs `PokedexOrder` from the cartridge (`lua/gen1/rom.lua:3`) | `to_national_dex` is identity; `lua/gen2/rom.lua` needs no dex-order table, only base stats. This is the one place Gen 2 is *simpler* |
| 16 | The New Bark west exit is locked by a map **scene** variable, not an event flag: `coord_event 1,8` / `1,9` → `SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU`, released by `setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP` in Elm's Lab | `pokecrystal@7a7881d maps/NewBarkTown.asm:8,292-293`, `maps/ElmsLab.asm:277`; `docs/gen2/research/pret_gen2_symbols.md:182-187`; `docs/gen2/REVIEW_RECORD.md:37` | Gen 1 fixtures reach Route 1 grass directly | **any grass fixture must run Elm's script first.** The lock is source, not a comment |

---

## 5. Binding steps, in order

This section is the **phase decomposition of `docs/gen2/PLAN.md` §6**, not a second plan. Every
substep sits inside exactly one PLAN phase; its exclusive files are a subset of that phase's PLAN §6
lease (`docs/gen2/PLAN.md:169-176`), or an explicitly named §5.15 extraction-card lease, which is a
*separate* lease inside the same phase; and it starts only after its phase's gate is signed
(`docs/gen2/PLAN.md:35-40`). Source cut for every substep: pret `pokecrystal@7a7881d` /
`pokegold@656583c` (O-5, `docs/gen2/REVIEW_RECORD.md:19`) on the base cut master + `80261f3` +
`959c578` + `910dbdd` (O-20, `docs/gen2/PLAN.md:25`). The format mirrors PLAN §6's own columns.

Four rules apply to every substep and are not repeated per row:

1. **`lua/gen2/*` never authorises an edit to a root shared module or to `lua/gen1/*`.** Where a
   substep binds an extracted mechanism, the §5.15 card is named and its shared file(s) **plus** its
   Gen 1 consumer file(s) are that card's own lease, with the Gen 1 rebind and the Gen 1 regression
   lanes listed in 5.15a-j (`docs/gen2/PLAN.md:153-162`). Sharing source never transfers Gen 1
   evidence to Gen 2 (`:152`).
2. One writer per shared file; `slink-adapter-guard` on every `server/` diff; one independent review
   (`docs/gen2/PLAN.md:38-39`).
3. **MODEL never closes a row** (`docs/gen2/gen2_requirements.md:5-9`), and an ENGINE site firing never
   closes a behaviour or persistence row: behaviour closes on its duo/live receipt, persistence on a
   save-witness + reload receipt.
4. **No pre-rewrite Gen 2 byte, fixture, test or doc is evidence** (`docs/gen2/gen2_requirements.md:11-12`);
   the legacy contents of `tests/fixtures/gen2/crystal_town.SaveRAM` are an input to nothing and are
   replaced by P3b.2's qualified save; its validated replacement path remains at cutover (PLAN §4).

This section replaces the eleven-step list of the earlier revision, which was written before PLAN §6
existed and contradicted it in eighteen places (Codex `cx-ec7d3f33`, accepted 18/18,
`docs/gen2/REVIEW_RECORD.md`). Where a sentence here withdraws an earlier one, it says so.

### P0 — Precondition (gate **G0**; phase lease `docs/gen2/PLAN.md:169`)

| Substep | Prereq | Exclusive files | 5.15 card(s) | First falsifier | Exit evidence | Requirement rows | Review | Lane |
|---|---|---|---|---|---|---|---|---|
| **P0.1** Base cut + drift-watch baseline | plan approved (Codex rounds, `docs/gen2/REVIEW_RECORD.md:105-114`) | the implementation worktree; `docs/gen2/PLAN.md` §6.1 row G0 | none: phase obligation | `git merge-base` does not prove the cut is master + the three cherry-picks → G0 refused | the three commits present; Gen 1 regression lanes green on that cut; Gen 3 branch tip sha recorded as the drift baseline (`docs/gen2/PLAN.md:146`) | none: phase obligation (G0) | Codex confirms the cut | coordinator |
| **P0.2** Spec + tickets | P0.1 | `docs/gen2/spec.md`, `docs/gen2/issues/*` | none: phase obligation | a §5 substep with no ticket, or a ticket with no substep → the register row fails | every substep below is a ticket; Archipelago is **excluded from ticketing** | none: phase obligation (G0) | owner at G0 | coordinator |
| **P0.3** Gate ledger + register rows | P0.1 | `docs/gen2/PLAN.md` §6.1 (`:184-195`), guide/register rows | none: phase obligation | a gate signed with an empty Evidence or Drift-watch cell → the ledger check fails | §6.1 created with G0..G6; G0 signed | none: phase obligation (G0) | owner | coordinator |

*Notes.* The cut in P0.1 is not a fact until `git merge-base` proves it; every citation below is read
at that cut. Ticketing covers P0-P6 and P5; Archipelago is deliberately absent from it.

### P1 — Build recipe and admitted-artifact matrix (gate **G1**; phase lease `docs/gen2/PLAN.md:170`)

| Substep | Prereq | Exclusive files | 5.15 card(s) | First falsifier | Exit evidence | Requirement rows | Review | Lane |
|---|---|---|---|---|---|---|---|---|
| **P1.1** Source lock + reproducible builds | **G0 signed** | `data/gen2_sources.lock.json`, `tools/build_gen2_syms.py`, `data/gen2/*.sym\|.map`, `tests/unit/test_gen2_build.py`; `tools/build_pret_syms.py` only to add a pin check | none: per-game (the lock pins two pret repos, an RGBDS version and four Gen 2 ROM hashes) | a build at the wrong sha or RGBDS version yields a different ROM sha1 and the lock test goes red — red today, nothing records the sha (`docs/gen2/research/pret_gen2_symbols.md:6`) | four ROMs built with sha1 == `roms.sha1`; committed `.sym`/`.map` sha256 == lock; **`data/pret_syms.json` is not a Gen 2 input** (5.1, `docs/gen2/PLAN.md:138`), asserted by a test that fails if any `tools/gen_gen2_*.py` reads it | F-1 (SOURCE half); Pins rows pokecrystal / pokegold / Assembler | OMP: lock vs `roms.sha1` vs built output | Codex + OMP |
| **P1.2** CI lane | P1.1 | `.github/workflows/gen2-syms.yml` | none: per-game | CI green while a local `.sym` hash differs from the lock → the job must fail | a green CI run the owner opens at G1 | none: phase obligation (G1) | OMP | Codex |
| **P1.3** Admitted-artifact matrix | P1.1; local Crystal dump hashed | `data/games/gen2_{crystal,gold,silver}/admission.json` (**matrix rows only**; data packs are P2.5) | none at this phase: per-game catalog. The `Entry.admit` framework (5.15d) is bound at P3b.3 | a BUILT/ADMITTED row without a hash, or a PLANNED row carrying one → the unit pin test red | ADMITTED = Gold, Silver and **the local dump's Crystal revision only** (O-12, `docs/gen2/PLAN.md:32`); the other revision is build-reproducibility evidence, **refused unless separately admitted** (`docs/gen2/gen2_requirements.md:139-142`); overlay + ghost rows PLANNED, no hash | F-7g, C-1 (SOURCE halves); Pins row "Clean ROM SHA-1" | owner at G1 | Codex + OMP |
| **P1.4** Linker-slack report | P1.1 | the `.map` slack report emitted by `tools/build_gen2_syms.py`; the G1 ledger row | none: per-game | a candidate free-WRAM span that any `.map` symbol overlaps → rejected | a candidate always-mapped free-WRAM list per title as ticket-14 input; **no mailbox is selected here** (`docs/gen2/PLAN.md:260`) | none: phase obligation (input to N-1/N-2) | Codex | OMP |

*Notes.* Four ROMs are built for reproducibility, three are ADMITTED: the unadmitted Crystal revision
may never be used as evidence for a behaviour row. P1.4's slack report is an input, not a decision — the
mailbox is chosen at P4.1 under ticket 14, or P4 stops for an owner decision.

### P2 — Data packs, generators, coverage map, read-only readers (gate **G2**; phase lease `docs/gen2/PLAN.md:171`)

| Substep | Prereq | Exclusive files | 5.15 card(s) | First falsifier | Exit evidence | Requirement rows | Review | Lane |
|---|---|---|---|---|---|---|---|---|
| **P2.1** Profile + static fact generators | **G1 signed** | `tools/gen_gen2_{profile,species,evos,items,charmap,map_names}.py`, their `data/games/gen2_*/` outputs, `tests/unit/test_gen2_{profile,species,evos}.py`; `tools/verify_profile_addresses.py` Gen 2 rows deleted | none: per-game (addresses, species table, charmap are cartridge facts; 5.15g shares only the scanning orchestration, bound at P3b.1) | one address moved in the lock → `tools/gen_gen2_profile.py --check` red | every profile address names a pret symbol at the pinned `.sym`; Crystal differs from Gold==Silver exactly where pret differs (5.2, `docs/gen2/PLAN.md:139`); species id == national dex | F-1, F-5 | OMP address audit rerun | Opus subagent |
| **P2.2** Engine-site table + `engine_signals.json` (SOURCE pins) | P2.1 | `tools/gen_gen2_engine_signals.py`, `data/games/gen2_*/engine_signals.json`, `docs/gen2/gen2_engine_sites.md`, `tests/unit/test_gen2_engine_sites.py` | none here: per-game fact set. The hook **registry** is 5.15a, bound at P3b.4 | one `expected_hex` byte edited → `tools/verify_gen2_rom_layout.py` red; a row whose address resolves to a **script-bytecode label** must be refused by the generator, not merely absent | every `expected_hex` at its `rom_offset` in every admitted ROM; whiteout pinned at the **CPU site reached from `Script_Whiteout` before `HealParty`** (`engine/events/whiteout.asm:14`; 5.3, `docs/gen2/PLAN.md:140`); capture at the `TryAddMonToParty`/`SendMonIntoBox` fork; faint at `UpdateFaintedPlayerMon` with `wCurBattleMon`; per-repo line tables, never one repo-wide offset (`research/omp_symbol_lines.md:139-153`) | F-2, F-3 (SOURCE halves) | Codex ADVERSARIAL_REVIEW of the site table | Opus subagent + Codex |
| **P2.3** Write-checkpoint pack (SOURCE) | P2.1 | `tools/gen_gen2_write_checkpoint.py`, `data/games/gen2_*/write_checkpoint.json`, `tests/unit/test_gen2_write_checkpoint.py` | none here: per-game (anchors and the state/ownership **predicate** stay per game, 5.15c + §6). The `gb_checkpoint` evaluator is bound at P3b.5 | an anchor byte edited → layout check red; a single-byte predicate accepted → red (`research/codex_checkpoint_and_linktrade.md` §A) | anchor 1 = `OWPlayerInput` immediately before `call CheckAPressOW` (`pokecrystal@7a7881d engine/overworld/events.asm:495` / `pokegold@656583c engine/overworld/events.asm:483`), caller-bound; predicate names `wScriptRunning`/`wScriptFlags`/`wMapEventStatus`/`wJoypadDisable`/`wBattleMode` + the `wSavedAtLeastOnce` refusal (§4 row 7). Liveness and negative controls are PHYSICAL, at P3b.5 | W-6, R-4 (SOURCE halves) | Codex | Opus subagent |
| **P2.4** Two-path ROM readers | P2.1 | `server/adapters/gen2_rom_scan.py`, a **read-only** `lua/gen2/rom.lua`, `tools/verify_gen2_rom_layout.py`, `tests/unit/test_gen2_rom_tables.py` | none: per-game (Gen 2 base-stat record layout and table addresses; species id == NatDex means no `PokedexOrder`, §4 row 15) | a deliberate one-byte divergence between the Lua reader and the Python scanner → the equality test red; red today, neither file exists | Lua reader == Python scanner byte-for-byte per title **and per time-of-day table**, over wild / headbutt / rock-smash / fishing / roamer tables and base stats | F-4 | Codex | Sonnet |
| **P2.5** Per-title data packs — **all three titles** | P2.1, P2.4 | `tools/gen_gen2_{area_map,encounters,statics,trainers,admission}.py`, `data/games/gen2_{crystal,gold,silver}/{area_map,encounters,statics,trainers,gifts}.json`, `tests/unit/test_gen2_{encounters,admission}.py` | none: per-game (wild tables, area ids, acquisition zones are cartridge facts) | an encounter test that distinguishes Gold from Silver — the wild tables differ (`pokegold@656583c data/wild/johto_grass.asm:341-364`), so one shared pack must fail it | **all three title packs exist and are signed at G2** (O-2, `docs/gen2/PLAN.md:17`): Crystal is the first increment inside this substep, Gold and Silver follow **before the gate**, neither waits for P3b. Acquisition rulings land as pack/adapter facts: egg hatch → `gift_daycare` (O-15), roamer → standalone `legend_<species>`, never consuming or locking the map's encounter (O-17), Bug-Catching Contest → zone `national_park_contest` (O-18) (`docs/gen2/PLAN.md:28,31`); time of day never splits an area (5.2) | F-7g; S-8, S-9g, S-10g, D-1 (SOURCE halves) | Codex | Opus subagent |
| **P2.6** Coverage map + validator | P2.2, P2.5 | `docs/gen2/gen2_coverage_map.md`, `tests/unit/test_gen2_coverage_map.py` | **5.15h coverage-map validator — CREATE as a neutral shared module, first consumer Gen 2** (`docs/gen2/PLAN.md:160`). Card lease: `tools/coverage_map.py` + `docs/shared-coverage-map.md`, `tests/unit/test_gen2_coverage_map.py`. **Disposition, stated explicitly: this is a CREATE, not an extraction from Gen 1.** There is no Gen 1 coverage map at this cut, so there is **no Gen 1 rebind, no Gen 1 consumer file and no Gen 1 regression lane** in this card — nothing to re-point and nothing whose evidence could be disturbed. Gen 2 is the first consumer; the card ships its own contract tests (missing row, stale artifact, absent receipt, wrong layer, MODEL-only exemption invented by the validator) written so that **a second binder runs them unchanged** — no Gen 2 path, id scheme or manifest shape in the contract; per-gen manifests hold branches, exceptions, the artifact matrix and oracle semantics. **Gen 3 binds it at its own P2**, and that binding is the card's first re-use proof, not a Gen 2 exit condition. Separate from lane execution (`tools/release_lanes.py`) and from permission to close a row | one ledger row with no stimulus/oracle → `test_gen2_coverage_map.py` red; a validator that invents a MODEL-only exemption → red | every `gen2_requirements.md` row and every `docs/protocol.md` §9 assertion mapped to stimulus, artifact, positive + refusal control, oracle, receipt marker, owning lane; **zero UNMAPPED** (G2 is never physical coverage, `docs/gen2/PLAN.md:171`); command-executor tests separated from natural-engine tests; C-0/C-4/D-13 marked MODEL-only; the **C↔G `link` receipt** is a row here, closed physically at P3b.7 | C-0, C-4, D-13 (mapping halves); every other row gains its map entry | Codex ADVERSARIAL_REVIEW of the coverage map | Opus subagent |
| **P2.7** Release-runner skeleton | P2.6 | `tools/verify_gen2_release.py` (skeleton), lane registrations, pre-runner check names | none — **bind, do not clone**: the runner core is the shared `tools/release_lanes.py` from `910dbdd` in the base cut (`docs/gen2/PLAN.md:146`); Gen 2 adds no second core | an unexplained skip, an xpass or a deselection yields a green verdict → red (`docs/shared_runtime.md:60`) | lanes `unit`, `rom-layout`, `lua-parse`, `profile-generated-<title>`, `fixtures`, `patch-build`, `live-gates`, `live-new-gates`, `duo-pairs` registered and failing closed while empty; the imported runner's failure behaviour verified (`docs/gen2/REVIEW_RECORD.md:111-114`) | none: phase obligation (G2); the vehicle by which every row later closes | Codex | Sonnet |

*Notes.* **Gold and Silver are P2 products, signed at G2**, not a step after Crystal; Crystal is only
the first increment inside P2.5. The old §5's "one step owns `rom.lua` and the codec together" is
withdrawn: `lua/gen2/rom.lua` + `server/adapters/gen2_rom_scan.py` are P2 **read-only** two-path readers
closing F-4 (`docs/gen2/PLAN.md:171`), while the codec and the WRAM/SRAM decoders are P3b consumers.
Nothing in P2 is physical; G2 signs the packs as the game-fact contract and reads zero UNMAPPED, never
physical coverage.

### P3a — Shared pairing change (gate **G3a**; phase lease `docs/gen2/PLAN.md:172`)

| Substep | Prereq | Exclusive files | 5.15 card(s) | First falsifier | Exit evidence | Requirement rows | Review | Lane |
|---|---|---|---|---|---|---|---|---|
| **P3a.1** Foundation rows + pairing matrix | **G2 signed**; the Gen 3 shared cut pinned at G0; drift watch clean | `server/adapters/__init__.py` (`_ROM_TYPE_TO_FOUNDATION` rows + registry tests), `tests/unit/test_gen2_pairing_matrix.py`; `server/adapters/base.py` / `server/server.py` only if the pinned cut lacks the hook | none: this **is** the shared-lifecycle change (5.9, `docs/gen2/PLAN.md:146`); the machinery stays generic, the permitted relation stays adapter data, no `game_id` branch (§6) | a Gen 2 half paired with a **Gen 1 or Gen 3** half admitted → red; a title-cased alias falling back to the shared `game_id` foundation → red; a rejected hello that changed `links.json` or a cache → red | **every Gen 2 `rom_type` spelling — `Crystal`/`crystal`, `Gold`/`gold`, `Silver`/`silver` (`server/adapters/__init__.py:63-66`) — maps to ONE foundation `gen2_gsc`, so every Gen 2 pairing is admitted**: G↔S, G↔G, S↔S, C↔C, C↔G, C↔S (O-16, `docs/gen2/PLAN.md:24`; `docs/gen2/gen2_requirements.md:104`). Gen 2 never pairs with Gen 1 or Gen 3. Alias × arrival-order matrix, reconnect, persisted run, unknown/contradictory hello each tested; `crystal_ap` not admitted (O-8) | C-6g (SOURCE + MODEL halves; PHYSICAL at P3b.7) | isolated reviewer (not the author) + `slink-adapter-guard` | Opus + Codex REVIEW |
| **P3a.2** Protocol schema rows | P3a.1 | `tests/unit/test_protocol_schema.py`, `tests/unit/protocol_schema.py`, `docs/protocol.md` Gen 2 rows | none: shared contract, no new module | a Gen 2 hello without `foundation`/`artifact_kind` accepted by the schema → red | every Gen 3-ism at `docs/protocol.md:491-516` carries an explicit Gen 2 answer, including the held-item field (§4 row 2) and the `play_sound` binding (`:497`); Gen 1 + Gen 3 unit suites green | C-0 (schema half) | isolated reviewer | Opus |

*Notes.* P3a may find the hook already present at the pinned cut; the gate then records "no shared
change: hook present at cut `<sha>`" with the pairing-matrix tests green (`docs/gen2/PLAN.md:172`). The
drift watch against the Gen 3 branch tip runs at this gate signing as at every other (`:146`).

### P3b — Client, adapter, codec, fixtures, harness (gate **G3**, internal milestone; phase lease `docs/gen2/PLAN.md:173`)

| Substep | Prereq | Exclusive files | 5.15 card(s) | First falsifier | Exit evidence | Requirement rows | Review | Lane |
|---|---|---|---|---|---|---|---|---|
| **P3b.1** `gen2_codec.py` — the independent byte oracle | **G2 signed** (G3a where it applies); tickets 10, 13, 20, 22 resolved | `server/adapters/gen2_codec.py`, `tests/unit/test_gen2_codec.py` | **5.15g charmap decoder + fixture qualifier → EXTRACT the orchestration, not the oracle** (`docs/gen2/PLAN.md:159`). Card lease: `server/gb_charmap.py` / `lua/gb_charmap_scan.lua` (bounded byte-token scanning over an injected table) + the fixture-enumeration/report-aggregation half used at P3b.2; Gen 1 consumers `server/adapters/gen1_codec.py:19-35,525-534`, `tools/gen1_fixtures.py:90-145`. Field/size/name facts stay per game; **production parsing is never folded into the PYDEC oracle** | the CONTROL: `CalcMonStats` recomputed two ways from DVs / stat-exp / base stats must agree, and a deliberately wrong Sp.Def derivation must fail it (ticket 20; 5.6, `docs/gen2/PLAN.md:143`). Red today: no Gen 2 decoder exists | party (48 B), box (32 B), names, 14×20 boxes across banks 2-3; **both** save layouts validated (Crystal primary + backup; Gold/Silver primary + five backup spans); GAME-style recovery modelled separately from strict witness validation | R-1 (MODEL half), R-2, F-6 (qualifier half) | Codex | Sonnet |
| **P3b.2** Fixtures from scripted play — eight saves | **P3b.1** (the codec must exist before a save can be qualified) | `tools/gen2_fixtures.py`, `lua/tests/gen2_scripted_play_*.lua` route modules, `tests/fixtures/gen2/{crystal,gold,silver}_{town,battle}.SaveRAM`, `tests/fixtures/gen2/crystal_{town,battle}_ot2.SaveRAM`, `tests/fixtures/gen2/receipts/**`, `tests/unit/test_gen2_fixtures.py` | **5.15j harness bind, do not clone** (`docs/gen2/PLAN.md:162`). Card lease: the bounded input-step runner, timeout and evidence capture extracted from `lua/tests/gen1_scripted_play.lua:1-6`, plus `tools/run_gb_gate.py:76-151` (`:241+` keeps process/save setup); Gen 1 consumers `lua/tests/gen1_scripted_play.lua`, `tools/gen1_fixtures.py`. **The Gen 2 Elm chain never inherits a Gen 1 state oracle.** 5.15g's fixture-enumeration half binds here | a fixture that fails `VerifyChecksum`, or does not survive cold boot → CONTINUE → re-save → reload with PYDEC/GAME agreement → red; red today, no played Gen 2 fixture exists (`docs/gen2/PLAN.md:100`) | the driver plays New Game → naming → Mom → Elm's lab → starter (town save **inside the lab**, encounter-free) → Route 29 grass (battle save) for all three titles, RAM-reactive, plus the Crystal `_ot2` pair under a second OT (`docs/gen2/PLAN.md:212-218`). **Poké Ball injection into the Ball pocket is the single staging exception** (O-10, `:33`), asserted by a bag read before any capture scenario; the Mr. Pokémon errand is not driven; the west-exit lock is released by the starter CHOICE (`ElmsLab.asm:243,251-277`, `docs/gen2/OPEN_QUESTIONS.md:44`). Eight saves, each cold-boot → CONTINUE → re-save → reload qualified | F-6; S-7 (SOURCE + MODEL halves) | Codex | Sonnet + coordinator (emulator lane) |
| **P3b.3** `entry.lua` + `reads.lua` | P3b.2 | `lua/gen2/entry.lua`, `lua/gen2/reads.lua`, `tests/unit/test_gen2_{entry,reads}.py` | **5.15d `Entry.admit` → EXTRACT the decision framework, not the policy** (`docs/gen2/PLAN.md:156`). Card lease: `lua/admission.lua` (actual-byte hash recomputation, candidate evaluation, unique-match requirement, explicit refusal, immutable result) + `docs/shared-admission.md`; Gen 1 consumer `lua/gen1/entry.lua:229-266`. Injected: candidate catalog (P1.3), ROM acquisition, required anchor sets, permitted admission modes. **Unknown-hash fallback defaults OFF** — Gen 2 does not inherit randomized admission from `lua/gen1/entry.lua:243-246`. Pack files stay per game, named literally in `Entry.PACK_FILES` (`:55-57`) | the differential: `lua/gen2/reads.lua` decoding a P3b.2 fixture against `gen2_codec.decode_party`/`decode_box`, byte for byte — red before either exists; plus an unknown sha1 admitted → red | `Entry.admit` resolves each admitted hash to exactly one `(pack, title, kind)` and **refuses the unadmitted Crystal revision** (P1.3); the differential passes on the 48/32-byte structs, the held-item field and the Sp.Atk/Sp.Def split (§4 rows 1-3) | R-1 (differential half; the PHYSICAL half is P3b.3a), C-1; C-5 **conditional** | Codex | Opus |
| **P3b.3a** Live inspect gate — reads qualified on the RUNNING cartridge | P3b.3 | `tests/live/test_gen2_new_gates.py` (inspect rows), `tests/unit/test_gen2_reads.py` (dump-replay cases), `tests/fixtures/gen2/receipts/**` (inspect receipts) | none: per-game evidence. It **consumes** 5.15g's scanning orchestration and 5.15e's receipt transport; it extracts nothing | a decoder run against a dump taken at a **different** frame, or from a different memory domain, still passes → the gate is not an oracle and is red; a title with no dump of its own → red | **R-1:** for every admitted title, one **same-frame raw WRAM/SRAM dump on the running cartridge** (frame number, memory domain and byte ranges recorded in the receipt), decoded by `lua/gen2/reads.lua` and, independently, by `server/adapters/gen2_codec.py` from the same bytes, with byte-for-byte equality of party, box and names — fixture-only agreement never closes R-1. **R-3:** an explicit GAME control per field — trainer class/id read back against the battle's own trainer display, badges against the Trainer Card (Johto **and** Kanto), the held item against the party menu's item line, the active box index against the PC's own box header. **R-5g:** gender and shininess derived from DVs checked against the game's own display (gender symbol in the status screen, the shiny palette/animation), on a mon of each outcome. Checkpoint reached, negative controls and liveness are P3b.5's | R-1 (PHYSICAL), R-3, R-5g | Codex | Opus + coordinator (emulator lane) |
| **P3b.4** `signals.lua` — the runtime hook binder | P3b.3; **the frame-alignment probe passes first** (5.13, `docs/gen2/PLAN.md:151`; B-9) | `lua/gen2/signals.lua`, `tests/unit/test_gen2_signals.py`, the signal rows of `tests/live/test_gen2_new_gates.py` | **5.15a bus-exec hook registry → EXTRACT (neutral core + platform binding)** (`docs/gen2/PLAN.md:153`). Card lease: `lua/hook_registry.lua` (all-site load validation, owned registration handles, bounded ordered queue, callback error latch, drain/status/close, transactional cleanup, unique owner namespaces) + `lua/gb_hook_binding.lua` (`hLoadedROMBank` filtering, PC/SP names, `PC == site`, System Bus/ROM mapping) + `docs/shared-hook-registry.md`; Gen 1 consumers `lua/gen1/signals.lua:326-396`, `lua/gen1/entry.lua`. Gen 1 lanes rebound green: live-new-gates, duo-pairs, inspect-purergb, duo-pairs-purergb | load-time `expected_hex` refusal: one deliberately wrong pack byte must refuse to start (`lua/gen1/signals.lua:6-9`); **an arm on a script-bytecode address must be refused by the binder**, not merely absent from the pack | the **engine-sequence proof per title**: every site fires exactly at its routine on the running cartridge with the bank check live (5.11, `docs/gen2/PLAN.md:149`), differential across the three titles; capture party-vs-box at the `TryAddMonToParty`/`SendMonIntoBox` fork; box insertion observed independently of `BATTLERESULT_BOX_FULL` with non-final and twentieth-slot controls; faint at `UpdateFaintedPlayerMon`, poison at `DoPoisonStep`, faint-time party bytes captured **before** `HealParty`; `wBattleResult` masked, never compared for equality (§4 row 9); hatch published as a `gift_daycare` capture, **never at `GiveEgg`** (O-15); roamer and contest captures observed in their zones. Firing closes the ENGINE obligation only | F-2, F-3 (PHYSICAL); S-1, S-2, S-3, S-4, S-5, S-6, S-7, S-8, S-9g, S-10g | Codex ADVERSARIAL_REVIEW | Opus + coordinator (emulator lane) |
| **P3b.5** `writes.lua`, `boxes.lua`, `lua/gen2_write_safety.lua` | P3b.4 | `lua/gen2/writes.lua`, `lua/gen2/boxes.lua`, **`lua/gen2_write_safety.lua`** (at the `lua/` root, the Gen 1 mirror — §7 Q8 settled; **not** `lua/gen2/write_safety.lua`), `tests/unit/test_gen2_{writes,boxes}.py` | three cards, each its own lease. **5.15b armed write gate → EXTRACT (permit + validated write, policies injected)** (`:154`): `lua/write_permit.lua` + `docs/shared-write-permit.md` (scoped permit, interval narrowing, full payload validation before the first byte, provenance, guaranteed disarm on every error), Gen 1 consumer `lua/gen1/writes.lua:59-85`; injected domain / bounds / mapped-bank / lifetime; per game the GB `$D000-$DFFF` policy and the faint/explode builders. **5.15c checkpoint runner → EXTRACT-GB-ONLY** (`:155`): `lua/gb_checkpoint.lua` + `docs/shared-gb-checkpoint.md` (re-verify anchors per attempt, bounded little-endian stack reads, caller/resume predicates, unavailable-input refusal), Gen 1 consumer `lua/gen1_write_safety.lua:54-105`; Gen 2 inherits no `DelayFrame+5`, no two-word stack, no font/link flags, and **the state/ownership predicate stays per game** in `lua/gen2_write_safety.lua` over the P2.3 pack. **5.15e box writer → KEEP-PER-GEN, two pieces split** (`:157`): `lua/gb_sram_addr.lua` (bank:address → flat) and, only if both clients need it, a neutral validated-span executor behind the permit; Gen 1 consumer `lua/gen1/boxes.lua:6-7,26-29,164-258` | the box-write gate refuses (a) any write outside an armed window; (b) **a memorial backing write while `wCurBox == 13`** — the refusal is scoped to Box 14, the memorial target, because the game's own `SaveBox` copies the active `sBox` over that backing slot (§4 row 6; PLAN §5.5, `docs/gen2/PLAN.md:142`); (c) any box write while `wSavedAtLeastOnce` == 0 (§4 row 7). **Positive control, equally required:** an ordinary deposit to and withdrawal from the CURRENT box succeeds and follows the source-derived active-shadow / backing-store ownership contract — a gate that refuses ordinary PC traffic is as red as one that permits the memorial hazard. All four red before the modules exist | Box 14 flat offset read back from a live `CartRAM` listing, closing §4 row 5's †UNVERIFIED and B-10; a negative control across an in-game SAVE with Box 14 active; the checkpoint's live negative controls (textbox, START menu, battle, warp fade, Elm's scene) **and** a liveness check that ordinary idle play still passes (5.4, `docs/gen2/PLAN.md:141`); `force_faint` at the battle-loop head, retry-at-tail only for party-full / last-party-mon | W-1, W-2, W-5, W-6, R-4; W-3, W-4 **conditional** | Codex | Opus + coordinator (emulator lane) |
| **P3b.6** `client.lua`, `run.lua`, launcher route, `gen2_gsc.py` | P3b.5 | `lua/gen2/client.lua`, `lua/gen2/run.lua`, **`lua/slink.lua`'s Gen 2 route** — the PLAN P3b lease's `lua/slink.lua` route, dispatching to `lua/gen2/run.lua` as the Gen 1 branch does (`lua/slink.lua:69-71`). **`lua/slink_gen2.lua` is not re-pointed, not rewritten and not leased**: PLAN §5.11b (`docs/gen2/PLAN.md:148`) rules out a Gen 2 shim, so the only route is `lua/slink.lua` → `lua/gen2/run.lua`; the legacy shim goes on the PLAN §4 cutover list, not into this substep, `server/adapters/gen2_gsc.py`, `server/adapters/__init__.py` re-point of the eight legacy `rom_type` rows, `server/manager.py` GAMES rows, `tests/unit/test_gen2_{client,adapter}.py` | Gen 2 signal handlers and game/write policies **consume** the P3b.3-P3b.5 cards; shared lifecycle, queues, reconnect, dispatch and presentation reuse bounded shared mechanisms under §5.15, with separate extraction-card leases where needed. The server trade FSM remains shared. `lua/game_detect.lua` stays bypassed as for Gen 1 (`lua/slink.lua:83-85`) | the lupa client test **on the production `Entry.build` graph**: hello before the checkpoint → red; a write outside the armed gate → red; codec vs Lua decode disagreement on a fixture → red; two C↔C halves carrying the identical FULL mon key → the identity test refuses (`tests/unit/test_gen1_identity_and_collisions.py:97-100`). Conformance units against a fake server: stat stages re-encoded (`docs/protocol.md:502`), PP-Ups split (`:503`), `ot_id` in HELLO (`:504`), a 70-byte blob accepted by `_ingest_party_blobs` (`:505`), `key_change` on evolution (`:515`) | the client runs on the **production `Entry.build` graph**, not a harness graph; `server/state.py` `handle_event` bound unchanged with **no new handler and no `game_id` branch** (§6); `hud.sanitize` on every on-screen string; gender/shininess derived from DVs match the game's own display | R-4, C-0, C-2 (MODEL half), C-3 (HUD half), C-4, D-12, D-13 | Codex ADVERSARIAL_REVIEW of the frozen client + limited-context Fable reviewer | Opus |
| **P3b.7** Duo lanes and oracles | P3b.6 | `tools/e2e_duo.py` Gen 2 rows + oracles, `tools/run_gb_gate.py` Gen 2 rows, `tests/e2e/test_duo_gen2_new.py`, `tests/live/test_gen2_new_gates.py`, `tools/verify_gen2_release.py` (lanes filled), `tests/gen2_release_requirements.json`, `docs/gen2/gen2_requirements.md` cells | **5.15i duo oracle/witness orchestration → EXTRACT** (`docs/gen2/PLAN.md:161`). Card lease: the descriptor-driven pipeline replacing the `scenario_family == 'gen1_new'` hardcoding at `tools/e2e_duo.py:4134-4153`, with required witness + post-result oracle stages and injected per-game validators, failing on any absent required stage for **every** migrated family; Gen 1 consumer: the `gen1_new` rows of `tools/e2e_duo.py`. **5.15e receipt transport** (`:157`): the generic attempt/artifact/frame/blob receipt transport (`lua/gen1/signals.lua:103+`, `lua/gen1/client.lua:1237-1238`, `tools/e2e_duo.py:4040+`); the successful-save site, save kind, checksums/recovery and the durable-delta oracle stay per game | a `gen2_new` scenario registered **without** a post-result oracle must raise; a verdict taken from the client's own RESULT line → red (`docs/shared_runtime.md:59`; `docs/gen2/PLAN.md:101`) | `gen2_new` duos green on **C↔C and G↔S**, plus the one **C↔G `link`** scenario proving cross-title admission (O-16): `link`, `ball_gate`, `boxed_capture`, `linked_faint_bench`, `linked_faint_active`, `poison`, `whiteout`, `pc_ops` (incl. release), `changebox`, `species_clause`, `gender_clause`, `type_clause`, `shiny_bonus`, `reconnect` (same-save / wrong-save / WRAM clear), `soft_reset`, `evolution`, `npc_trade`, `gift`, `egg_hatch`, `admit_wrong_rom`; **acquisition consumption controls**: a roamer catch does not consume or lock the map's encounter, a contest catch links under `national_park_contest`, a hatch consumes as a `gift_daycare` capture. Same-cartridge C↔C keeps per-instance `saveram_dir` (§4 row 14). D-12 requires a GAME transient overlay measurement or an explicit owner-signed recorded limit; the Gen 1 MODEL limit is not inherited. Save-contract gates: witness at the success-only boundary; cold-boot recovery controls (bad primary/good backup, inverse, both bad) | C-2, C-6g (PHYSICAL), D-1, D-2, D-3, D-5, D-6, D-7, D-12, D-14, W-5, W-7, F-6 (per-lane re-qualification), S-2/S-3/S-5/S-6/S-7/S-8/S-9g/S-10g (behaviour halves); D-11 **conditional** | Codex + non-author reviewer | Sonnet (harness) + coordinator (emulator lane) |
| **P3b.8** Packaging, cutover census, deletion | P3b.7 | `tools/make_release.py` manifest rows, `tests/unit/test_make_release_manifest.py`, the extracted-bundle boot test, the PLAN §4 deletion list | none: per-game (manifest rows name Gen 2 pack files literally) | a pack file missing from the manifest → `test_make_release_manifest.py` red; the extracted bundle fails to boot an admitted title → red; **any validated REPLACE path unlinked, absent, or present at an unexpected hash → red** | packaging exists **before** the census; the PLAN §4 cutover inventory is executed **split into REMOVE and REPLACE** exactly as PLAN §4 lists it (`docs/gen2/PLAN.md:126`). **REPLACE (same path, regenerated content)** — `tests/fixtures/gen2/crystal_town.SaveRAM` (played, P3b.2), `tests/unit/test_gen2_adapter.py` (new adapter tests, P3b.6), `data/games/gen2_crystal/*` (regenerated packs, P2): the old content is replaced and the new content validated at its expected hash, asserted per entry. **The validated same-path replacement is never unlinked**; only REMOVE entries are deleted, and every REPLACE path is still present at that hash on the post-deletion tree. **REMOVE (path goes away)** — the old client, `lua/memory_gb.lua`, the `lua/games/gen2_crystal*.lua` modules, the root `lua/gen2_crystal_{areas,locations}.lua`, all 15 legacy Lua probe/test scripts explicitly named in PLAN §4 (including `lua/tests/gen2_playthrough.lua`; not the new P3b drivers), `tools/gen2_playthrough.py`, `server/adapters/gen2_crystal.py` (its successor `gen2_gsc.py` is a different path, so this is a removal, not a replacement), `tests/unit/test_gen2_{ap_addresses,ball_items}.py`, `tests/live/test_gen2_gates.py`, `tests/e2e/test_duo_gen2.py`, the Gen 2 rows of `tools/verify_profile_addresses.py`, and — as PLAN §4 and §5.11b explicitly require — `lua/slink_gen2.lua`. Reference/import/launcher/test census of both sets; the real distribution rebuilt and its extracted contents booted per admitted title and pairing; previous runnable bundle + per-attempt save copies frozen (§9a, `docs/gen2/PLAN.md:240-247`); then, **on the post-deletion tree**, the extracted-bundle boot **and** the eight-fixture qualification are re-run, and `tools/verify_gen2_release.py --quick` is green with the unit suite | none: phase obligation (G3 cutover); it protects every row already closed | Codex | coordinator + Sonnet |

*Notes.* The order inside P3b is load-bearing: oracle → fixtures → readers → **live inspect** → signals
→ writes → client → duos → cutover. P3b.3a is the reads qualification and is where R-1 becomes physical:
a fixture differential is a MODEL result and closes nothing on its own. **No read or write gate runs before the eight fixtures exist and qualify**, and
no fixture is qualified by anything but the codec. Each extraction card inside the phase is a separate
lease carrying its own Gen 1 rebind with the Gen 1 lanes green; a `lua/gen2/*` ticket never edits
`lua/gen1/*` or a root shared module. The deletion of the old Gen 2 code is the last act of the phase,
after packaging exists and the census passes.

### P4 — Companion overlay: panel, sound, native trade (gate **G4**, first RC-eligible; phase lease `docs/gen2/PLAN.md:174`)

| Substep | Prereq | Exclusive files | 5.15 card(s) | First falsifier | Exit evidence | Requirement rows | Review | Lane |
|---|---|---|---|---|---|---|---|---|
| **P4.1** Mailbox + START-menu panel | **G3 signed** and **tickets 14, 15, 16 resolved** (`docs/gen2/PLAN.md:174`). **No bank placement is assumed**: the mailbox is whatever ticket 14 establishes with an explicit banking/ownership/lifecycle contract and complete writer exclusion, or P4 stops for an owner decision (`:259`; the `sScratch` fallback is withdrawn, `docs/gen2/REVIEW_RECORD.md:110-112`) | `patch/gen2/**` (panel sources), `tools/build_gen2_companion.py`, `patch/dist/SLink-{Gold,Silver,Crystal}.ups`, `data/gen2/*_slink.sym\|map`, overlay rows in the admitted-artifact matrix + overlay blocks in `data/games/gen2_*/{profile,engine_signals,write_checkpoint,admission}.json`, `server/patcher.py` TARGETS rows, `lua/gen2/panel.lua`, `tests/unit/test_gen2_overlay.py` | **5.15f ABI-3 panel/mailbox → EXTRACT-GB-ONLY with explicit versioning** (`docs/gen2/PLAN.md:158`). Card lease: `lua/gb_panel.lua` + `docs/shared-gb-panel.md` (AWAIT observation, bounded write ownership, sanitized pagination, publish-before-STAGED, timeout/consumption rules, GB tile renderer); Gen 1 consumer `lua/gen1/panel.lua:98-124,170-216,220+`. **Required inputs, never defaults**: mailbox address, SLNK/offset/capability/state values, SE mapping, tile geometry, page/deadline limits, charmap; ABI version/capability negotiation mandatory | the capability probe must read ABSENT on an unpatched cartridge and refuse to paint (`lua/gen1/panel.lua:8-10`); a panel request without its transient receipt → red | saved-region symbol equality clean↔overlay; RAM/SRAM `.map` placement equality; live clean↔overlay save round trip; the SLINK row opens the panel; UPS byte-reproducible; GBC fade stress | N-1; C-3 (panel-row half) | non-author reviewer (asm by Codex → Opus reviews, and vice versa) | Codex (asm) + Opus (Lua) |
| **P4.2** Native sound | P4.1 (same manifest, same mailbox) | the sound sources under `patch/gen2/src/`, the SE table and `request_sfx` **inside `lua/gen2/panel.lua`** (**no `lua/gen2/sound.lua`** — settled, `docs/gen2/PLAN.md:150`), the sound rows of `tests/live/test_gen2_trade_gates.py` | none: per-game. `lua/sfx_arbiter.lua` is already shared and is bound directly with Gen 2's own SE constants, never literals (`lua/sfx_arbiter.lua:20`); no wrapper (5.15j) | a sound request that sits unplayed past its deadline at any qualified service site → red (Gen 1 measured 300 frames on the DelayFrame bridge alone, `patch/gen1/README.md:52-55`) | the ticket-16 service sites qualified **separately** for movement, idle START menu, text, battle and transitions, with a caller/context ABI, bank/register preservation, busy/request-consumption semantics and reset controls; an IRQ may signal a request, game-code execution there needs its own proof (5.12, `docs/gen2/PLAN.md:150`). Closes `docs/protocol.md:497` | N-2 | non-author reviewer | Codex (asm) + Opus (Lua) |
| **P4.3** SLINK TRADE receptionist + trade overlay | P4.1 | `patch/gen2/src/trade_*.asm`, `lua/gen2/trade_overlay.lua`, **`lua/gen2/client.lua` (trade phases only)**, **`tests/unit/test_gen2_client.py` (trade cases only)**, `tests/live/test_gen2_trade_gates.py`, `tests/unit/test_gen2_overlay.py` trade rows | none: per-game (Gen 2's own lease magic and receptionist ABI). The trade FSM is `server/state.py:554-800`, bound through `native_trade_ui()` (`server/adapters/base.py:308`); **no Gen 2 branch in the FSM** (§6) | a stale token must not complete a trade (`lua/gen1/trade_overlay.lua:5-7`); **an invalid held item must be refused before commit** (the refused-invalid control) | the takeover covers the receptionist wait, payload/patch/mail exchange, confirmation, both animations, post-trade sync and the save acknowledgment — never a one-byte connection bypass — over the SOURCE sequence `LinkTrade` → `AddTempmonToParty` (`engine/link/link.asm:1994`) → `EvolvePokemon` (`:1998`) → `SaveAfterLinkTrade` (`:2044`) (5.12, `docs/gen2/PLAN.md:150`). **Held items validated, carried and read back on both halves** (O-14, T-3); Time Capsule and mail are the only recorded limits (`docs/gen2/gen2_requirements.md:139-142`). `trade_new` / `trade_decline_new` / timeout / reset duos on overlay pairings (C↔C, G↔S); decline leaves both saves unchanged; trade persistence witness = `SaveAfterLinkTrade` **plus** the following scenario save, which it never substitutes for; save reload after trade shows the traded mon | T-1, T-2, T-3, T-4 | non-author reviewer | Codex (asm) + Opus (Lua) |
| **P4.4** Reopened receipts + matrix promotion | P4.1-P4.3 | the overlay rows of the admitted-artifact matrix; the §6.1 ledger row for G4 | none: phase obligation | an overlay row promoted to ADMITTED while a reopened receipt is still open → red | **the overlay reopens build, admission, site, checkpoint and natural-rules receipts on the patched build**; a receipt is shared with the clean build only on byte/offset **and** reachability-context equivalence (`docs/gen2/PLAN.md:174`, §9a `:239-246`); only then do overlay rows carry real hashes and become ADMITTED | none: phase obligation (G4); it re-closes F-2/F-3/W-6/C-1 on the patched artifact | frozen-source evaluator | coordinator |

*Notes.* Every P4 substep reopens receipts on the patched build; nothing inherits a clean-build
receipt without byte/offset **and** reachability-context equivalence. Tickets 14, 15 and 16 are
prerequisites of the phase, not deliverables inside it.

### P6 — Manager, UI and release (gate **G6**; phase lease `docs/gen2/PLAN.md:176`)

| Substep | Prereq | Exclusive files | 5.15 card(s) | First falsifier | Exit evidence | Requirement rows | Review | Lane |
|---|---|---|---|---|---|---|---|---|
| **P6.1** Manager family + cartridge picker | **G4 signed** (P6's only prerequisite, `docs/gen2/PLAN.md:176`) | `server/manager.py` / templates Gen 2 rows, `tools/gen_ui_capabilities.py` output | none: per-game rows in shared UI | the picker offers an unadmitted artifact → red | one run family "Gold · Silver · Crystal" (O-16, `docs/gen2/PLAN.md:30`); the Manager UI leg verified in the browser | none: phase obligation (G6) | frozen-source evaluator | Sonnet |
| **P6.2** Docs + release notes | P6.1 | `README.md` / `docs/REFERENCE.md` Gen 2 blocks, `docs/release_notes.md`, `tools/make_release.py` (later release changes only; the manifest rows landed at P3b.8) | none: phase obligation | a recorded limit missing from the notes (O-10 ball injection, Time Capsule, mail, the unadmitted Crystal revision) → the limits check red | the limits list and the "Not in this release" list match `docs/gen2/gen2_requirements.md:137-152` | none: phase obligation (G6) | owner | coordinator |
| **P6.3** Full release verdict | P6.2 | the frozen cut; the §6.1 ledger row for G6 | none: the verdict runs on the shared `tools/release_lanes.py` core bound at P2.7 | any skip, xpass, deselection or a `--quick` flag still yields success → red | `tools/verify_gen2_release.py` **without `--quick`**, zero skips, every matrix artifact covered; extracted-bundle boot per admitted title; Manager leg verified; two-person attestation. **Closure is read per row against that row's own declared evidence layers, not against a uniform S+M+P:** a SOURCE-only row (F-1, F-4, F-5, F-7g — the ledger prints `—` in its P column) closes on SOURCE + MODEL; a MODEL-only-by-design row (C-0, C-4, D-13) closes on MODEL with its by-design note; a conditional row (W-3, W-4, C-5, D-11) evaluates APPLICABILITY first: a disabled or deferred row (conditional W-3/W-4/C-5/D-11 without an enabling ruling; post-RC N-3 before its own gate) receives its signed disposition with no behaviour-pass claim; an ENABLED conditional row requires its declared evidence layers on the recorded-limits list; D-12 requires a GAME transient overlay receipt or an explicit owner-signed recorded limit, with no behaviour-pass claim for the limit; every other applicable row REQUIRES a PHYSICAL receipt. The verdict is **zero unclosed REQUIRED physical obligations** — a row may not be closed by promoting a MODEL result, and a recorded limit must be quoted, not implied | the whole ledger: this is where every row's verdict is read | frozen-source evaluator | coordinator + Sonnet |

*Notes.* P6 depends on G4 only (`docs/gen2/PLAN.md:176`). If the ghost runs at all it runs after the
release, on the shipped overlay.

### Post-RC: P5 — peer ghost (gate **G5**, after G6; phase lease `docs/gen2/PLAN.md:175`)

| Substep | Prereq | Exclusive files | 5.15 card(s) | First falsifier | Exit evidence | Requirement rows | Review | Lane |
|---|---|---|---|---|---|---|---|---|
| **P5.1** Design sign-off + save-exclusion lifecycle | **G6 shipped** + ticket 14's mailbox + the R9 design (`docs/gen2/research/peer_ghost_design.md`) signed by the owner | the decision section of `docs/gen2/research/peer_ghost_design.md`; ghost rows (PLANNED) in the admitted-artifact matrix | none: per-game. `lua/peer_ghost_npc.lua` is the **Gen 3** object-event ghost, not shared (§2), so nothing ports | a design without an explicit save-exclusion/restore lifecycle → refused: `wObjectStructs`/`wMapObjects` lie **inside** `wPlayerData` and `_SaveGameData` copies the whole block to `sPlayerData`, so an injected ghost **can** enter the save, and CONTINUE uses `LoadMapAttributes_SkipObjects` (5.12, `docs/gen2/PLAN.md:150`) | the lifecycle, the engine's own free-struct predicate (`FindFirstEmptyObjectStruct` tests byte 0 == 0, `home/map_objects.asm:420-435`) and Gold's Chris-only sprite table are answered in the design | N-3 (SOURCE half) | non-author reviewer | Opus |
| **P5.2** Ghost implementation | P5.1 | `patch/gen2/src/ghost*.asm`, `lua/gen2/ghost.lua`, `tests/unit/test_gen2_ghost.py` | none: per-game (new ASM against Gen 2's object-event engine) | the ghost object leaks into the wild-encounter or collision path → red | unit coverage of the lifecycle; the ghost overlay added to the matrix as PLANNED | N-3 (MODEL half) | non-author reviewer | Opus |
| **P5.3** Live ghost gate | P5.2 | `tests/live/test_gen2_ghost_gates.py`; the ghost matrix rows | none: per-game | a ghost frame without its transient receipt → red | live ghost gate on both pairings (position 1:1, sprite/palette, suspend in battle) with transient receipts; the P4.4 reopened receipts re-run on the ghost overlay | N-3 (PHYSICAL) | non-author reviewer | Opus + coordinator (emulator lane) |

### FUTURE BACKLOG: Archipelago Crystal `6.0.0-rc.1`

**Post-RC (O-8), excluded from ticketing.** Not a phase, not a substep, no gate, no requirement row
(`docs/gen2/gen2_requirements.md:137-142`; `docs/gen2/PLAN.md:23`). Recorded so nobody infers otherwise:
the pin is `gerbiljames/Archipelago-Crystal@0b11931c`, world path `worlds/pokemon_crystal_prerelease/`,
suffix `.apcrystalpre` (`docs/gen2/research/archipelago_crystal.md:369-373`); the AP ROM is 2 MB and its
header reads `AP_CRYSTAL` (`:206-224`), so admission would be a distinct `Entry.PACKS` kind, not a
Crystal row. The base patch's ASM source is not public — only compiled `basepatch.bsdiff4` /
`basepatch11.bsdiff4` are checked in (`:278-283`) — so whether party, box or `sBox` structures move from
vanilla cannot be answered from source (`:407-414`); a profile would have to be derived by diffing a
patched ROM. `crystal_ap` is not admitted in the RC.

### 5.A Self-check — every substep against the PLAN §6 phase lease

Column 2 is read off that substep's own *Exclusive files* cell above; column 3 names the literal PLAN §6
lease clause (or the extraction-card lease) that contains it. No row is marked by assertion.

| Substep | Files, from the row body | Lease clause that contains them | Requirement rows |
|---|---|---|---|
| **P0.1** | the implementation worktree; PLAN §6.1 row G0 | P0: `docs/gen2/PLAN.md` §6.1 ledger — the worktree is the phase exit evidence, not a repo file | — phase (G0) |
| **P0.2** | `docs/gen2/spec.md`, `docs/gen2/issues/*` | P0: “`docs/gen2/spec.md`, `docs/gen2/issues/*` (from `/to-spec`, `/to-tickets`)” | — phase (G0) |
| **P0.3** | PLAN §6.1 (`:184-195`), guide/register rows | P0: “§6.1 ledger, guide/register rows” | — phase (G0) |
| **P1.1** | `data/gen2_sources.lock.json`, `tools/build_gen2_syms.py`, `data/gen2/*.sym\|.map`, `tests/unit/test_gen2_build.py`, `tools/build_pret_syms.py` pin check | P1: the same five entries, verbatim | F-1(S), Pins |
| **P1.2** | `.github/workflows/gen2-syms.yml` | P1: “`.github/workflows/gen2-syms.yml`” | — phase (G1) |
| **P1.3** | `data/games/gen2_*/admission.json` (matrix rows only) | P1: “`data/games/gen2_*/admission.json` (matrix only)” | F-7g, C-1(S), Pins |
| **P1.4** | the `.map` slack report from `tools/build_gen2_syms.py`; the G1 ledger row | P1: the builder is leased; the linker-slack report is named in P1 exit evidence | — phase (G1) |
| **P2.1** | `tools/gen_gen2_{profile,species,evos,items,charmap,map_names}.py`, their `data/games/gen2_*/` outputs, `tests/unit/test_gen2_{profile,species,evos}.py`, `tools/verify_profile_addresses.py` Gen 2 rows | P2: “`data/games/gen2_{crystal,gold,silver}/*`, `tools/gen_gen2_*.py`, `tests/unit/test_gen2_{profile,…,species,evos,…}.py`; `verify_profile_addresses.py` Gen 2 rows deleted” | F-1, F-5 |
| **P2.2** | `tools/gen_gen2_engine_signals.py`, `data/games/gen2_*/engine_signals.json`, `docs/gen2/gen2_engine_sites.md`, `tests/unit/test_gen2_engine_sites.py` | P2: `tools/gen_gen2_*.py`, `data/games/gen2_*/*`, “`docs/gen2/gen2_engine_sites.md`”, `test_gen2_engine_sites.py` | F-2(S), F-3(S) |
| **P2.3** | `tools/gen_gen2_write_checkpoint.py`, `data/games/gen2_*/write_checkpoint.json`, `tests/unit/test_gen2_write_checkpoint.py` | P2: `tools/gen_gen2_*.py`, `data/games/gen2_*/*`, `test_gen2_write_checkpoint.py` | W-6(S), R-4(S) |
| **P2.4** | `server/adapters/gen2_rom_scan.py`, read-only `lua/gen2/rom.lua`, `tools/verify_gen2_rom_layout.py`, `tests/unit/test_gen2_rom_tables.py` | P2: “`server/adapters/gen2_rom_scan.py` + a read-only `lua/gen2/rom.lua` (the two-path readers move here from P3b)”, `verify_gen2_rom_layout.py`, `test_gen2_rom_tables.py` | F-4 |
| **P2.5** | `tools/gen_gen2_{area_map,encounters,statics,trainers,admission}.py`, the per-title pack files, `tests/unit/test_gen2_{encounters,admission}.py` | P2: `data/games/gen2_{crystal,gold,silver}/*`, `tools/gen_gen2_*.py`, `test_gen2_{encounters,admission}.py` | F-7g, S-8(S), S-9g(S), S-10g(S), D-1(S) |
| **P2.6** | `docs/gen2/gen2_coverage_map.md`, `tests/unit/test_gen2_coverage_map.py` | P2: “**`docs/gen2/gen2_coverage_map.md`**”, `test_gen2_coverage_map.py`. Plus the 5.15h **CREATE** lease: `tools/coverage_map.py`, `docs/shared-coverage-map.md` — no Gen 1 consumer file | C-0, C-4, D-13 (mapping) |
| **P2.7** | `tools/verify_gen2_release.py` skeleton, lane registrations, pre-runner check names | P2: “`tools/verify_gen2_release.py` skeleton built on … `tools/release_lanes.py`, lanes registered, pre-runner checks named” | — phase (G2) |
| **P3a.1** | `server/adapters/__init__.py` foundation rows + registry tests, `tests/unit/test_gen2_pairing_matrix.py`; `base.py` / `server.py` only if the pinned cut lacks the hook | P3a: the same entries, verbatim (`base.py` gated on a `pairing_kind` override becoming necessary) | C-6g |
| **P3a.2** | `tests/unit/test_protocol_schema.py`, `tests/unit/protocol_schema.py`, `docs/protocol.md` Gen 2 rows | P3a: the same three entries | C-0 |
| **P3b.1** | `server/adapters/gen2_codec.py`, `tests/unit/test_gen2_codec.py` | P3b: “`server/adapters/{gen2_gsc,gen2_codec}.py`”, `tests/unit/test_gen2_codec.py`. Plus the 5.15g card lease (`server/gb_charmap.py` + its Gen 1 consumers) | R-1(M), R-2, F-6 |
| **P3b.2** | `tools/gen2_fixtures.py`, `lua/tests/gen2_scripted_play_*.lua`, the eight `.SaveRAM` fixtures, `tests/fixtures/gen2/receipts/**`, `tests/unit/test_gen2_fixtures.py` | P3b: `tools/gen2_fixtures.py`, “`lua/tests/gen2_*.lua` drivers”, the eight fixtures, `tests/fixtures/gen2/receipts/**`, `tests/unit/test_gen2_fixtures.py`. Plus the 5.15j harness lease | F-6, S-7 |
| **P3b.3** | `lua/gen2/entry.lua`, `lua/gen2/reads.lua`, `tests/unit/test_gen2_{entry,reads}.py` | P3b: “`lua/gen2/*` (except `rom.lua` from P2)”, `tests/unit/test_gen2_{entry,reads}.py`. Plus the 5.15d admission lease | R-1 (differential), C-1, C-5† |
| **P3b.3a** | `tests/live/test_gen2_new_gates.py` inspect rows, `tests/unit/test_gen2_reads.py` dump-replay cases, `tests/fixtures/gen2/receipts/**` | P3b: `tests/live/test_gen2_new_gates.py`, `tests/unit/test_gen2_reads.py`, `tests/fixtures/gen2/receipts/**` | R-1(P), R-3, R-5g |
| **P3b.4** | `lua/gen2/signals.lua`, `tests/unit/test_gen2_signals.py`, the signal rows of `tests/live/test_gen2_new_gates.py` | P3b: `lua/gen2/*`, `tests/unit/test_gen2_signals.py`, `tests/live/test_gen2_new_gates.py`. Plus the 5.15a registry lease | F-2, F-3, S-1..S-8, S-9g, S-10g |
| **P3b.5** | `lua/gen2/writes.lua`, `lua/gen2/boxes.lua`, `lua/gen2_write_safety.lua`, `tests/unit/test_gen2_{writes,boxes}.py` | P3b: “`lua/gen2/*` …, `lua/gen2_write_safety.lua`”, `tests/unit/test_gen2_{writes,boxes}.py`. Plus the 5.15b / 5.15c / 5.15e leases | W-1, W-2, W-5, W-6, R-4, W-3†, W-4† |
| **P3b.6** | `lua/gen2/client.lua`, `lua/gen2/run.lua`, the `lua/slink.lua` Gen 2 route, `server/adapters/gen2_gsc.py`, `server/adapters/__init__.py` re-point, `server/manager.py` GAMES rows, `tests/unit/test_gen2_{client,adapter}.py` | P3b: “`lua/gen2/*`, `lua/slink.lua` route, `server/adapters/{gen2_gsc,gen2_codec}.py`, `server/adapters/__init__.py`, `server/manager.py` GAMES rows”, `tests/unit/test_gen2_{client,adapter}.py`. **`lua/slink_gen2.lua` is deliberately absent** (PLAN §5.11b, `docs/gen2/PLAN.md:148`) | R-4, C-0, C-2(M), C-3(HUD), C-4, D-12, D-13 |
| **P3b.7** | `tools/e2e_duo.py` Gen 2 rows + oracles, `tools/run_gb_gate.py` rows, `tests/e2e/test_duo_gen2_new.py`, `tests/live/test_gen2_new_gates.py`, `tools/verify_gen2_release.py` lanes, `tests/gen2_release_requirements.json`, `docs/gen2/gen2_requirements.md` cells | P3b: the same entries, verbatim. Plus the 5.15i / 5.15e leases | C-2, C-6g(P), D-1..D-7, D-12, D-14, S-2/3/5/6/7/8/9g/10g, W-5, W-7, F-6, D-11† |
| **P3b.8** | `tools/make_release.py` manifest rows, `tests/unit/test_make_release_manifest.py`, the extracted-bundle boot test, the PLAN §4 cutover list (REMOVE + REPLACE) | P3b: “`tools/make_release.py` manifest rows + `tests/unit/test_make_release_manifest.py` + the extracted-bundle boot test …; the deletion list of §4” | — phase (G3) |
| **P4.1** | `patch/gen2/**`, `tools/build_gen2_companion.py`, the three UPS artifacts, `data/gen2/*_slink.sym\|map`, overlay matrix rows + overlay pack blocks, `server/patcher.py` TARGETS, `lua/gen2/panel.lua`, `tests/unit/test_gen2_overlay.py` | P4: the same entries, verbatim. Plus the 5.15f `gb_panel` lease | N-1, C-3 |
| **P4.2** | the sound sources under `patch/gen2/src/`, the SE table and `request_sfx` in `lua/gen2/panel.lua`, the sound rows of `tests/live/test_gen2_trade_gates.py` | P4: `patch/gen2/**`, “`lua/gen2/{trade_overlay,panel}.lua` (sound lives in `panel.lua` + `lua/sfx_arbiter.lua`)”, `tests/live/test_gen2_trade_gates.py` | N-2 |
| **P4.3** | `patch/gen2/src/trade_*.asm`, `lua/gen2/trade_overlay.lua`, `lua/gen2/client.lua` (trade phases only), `tests/unit/test_gen2_client.py` (trade cases only), `tests/live/test_gen2_trade_gates.py`, `tests/unit/test_gen2_overlay.py` trade rows | P4: `patch/gen2/**`, `lua/gen2/{trade_overlay,panel}.lua`, **`lua/gen2/client.lua` trade phases** and **`tests/unit/test_gen2_client.py` trade cases**, `tests/live/test_gen2_trade_gates.py`, `tests/unit/test_gen2_overlay.py` | T-1, T-2, T-3, T-4 |
| **P4.4** | the overlay rows of the admitted-artifact matrix; the §6.1 ledger row for G4 | P4: “overlay rows in the admitted-artifact matrix”; the ledger is the coordinator artifact created at P0.3 | — phase (G4) |
| **P6.1** | `server/manager.py` / templates Gen 2 rows, `tools/gen_ui_capabilities.py` output | P6: the same two entries | — phase (G6) |
| **P6.2** | `README.md` / `docs/REFERENCE.md` Gen 2 blocks, `docs/release_notes.md`, `tools/make_release.py` (later release changes only) | P6: the same three entries, verbatim | — phase (G6) |
| **P6.3** | the frozen cut; the §6.1 ledger row for G6 | P6: the phase runs the release verdict over the frozen cut; no new file is written | the whole ledger, by declared layers |
| **P5.1** | the decision section of `docs/gen2/research/peer_ghost_design.md`; PLANNED ghost rows in the matrix | P5: the `peer_ghost_design.md` decision section; “ghost overlay rows in the matrix” | N-3(S) |
| **P5.2** | `patch/gen2/src/ghost*.asm`, `lua/gen2/ghost.lua`, `tests/unit/test_gen2_ghost.py` | P5: the same three entries, verbatim | N-3(M) |
| **P5.3** | `tests/live/test_gen2_ghost_gates.py`; the ghost matrix rows | P5: “`tests/live/test_gen2_ghost_gates.py`”, “ghost overlay rows in the matrix” | N-3(P) |

**Substeps with files outside their lease: 0** — 35 substeps († = conditional row). Three of them own no
repository file at all (P0.1 the worktree, P4.4 and P6.3 the ledger and the verdict) and say so rather than
claim a lease membership.
### 5.B Self-check — every requirement row against a substep

Read off the *Requirement rows* cells above, then checked back against every row id in
`docs/gen2/gen2_requirements.md`. Column 3 is the row's **declared evidence layers**, which is what P6.3
closes against — a SOURCE-only row is not left open for want of a PHYSICAL receipt it never declared.

| Row | Substep(s) | Declared layers |
|---|---|---|
| F-1 | P1.1, P2.1 | SOURCE-only row — P column `—` |
| F-2 | P2.2 (S), P3b.4 (P), P4.4 (overlay re-close) | SOURCE + PHYSICAL |
| F-3 | P2.2 (S), P3b.4 (P) | SOURCE + PHYSICAL |
| F-4 | P2.4 | SOURCE-only row — P column `—` |
| F-5 | P2.1 | SOURCE-only row — P column `—` |
| F-6 | P3b.1 (qualifier), P3b.2, P3b.7 (per-lane re-qualification), P3b.8 (post-deletion re-run) | SOURCE + PHYSICAL |
| F-7g | P1.3, P2.5 | SOURCE-only row — P column `—` |
| R-1 | P3b.1 (MODEL), P3b.3 (differential), **P3b.3a (PHYSICAL: same-frame running-cartridge dump, every admitted title)** | PHYSICAL required |
| R-2 | P3b.1 | CONTROL |
| R-3 | P3b.3a | PHYSICAL required — a GAME control per field |
| R-4 | P2.3 (S), P3b.5, P3b.6 | PHYSICAL required |
| R-5g | P3b.3a | PHYSICAL required — gender symbol, shiny palette |
| S-1 | P3b.4 | PHYSICAL required |
| S-2 | P3b.4 (ENGINE), P3b.7 (`ball_gate`) | PHYSICAL required |
| S-3 | P3b.4 (ENGINE), P3b.7 (`boxed_capture`) | PHYSICAL required |
| S-4 | P3b.4 | PHYSICAL required |
| S-5 | P3b.4 (ENGINE), P3b.7 (`evolution`, `npc_trade`) | PHYSICAL required |
| S-6 | P3b.4 (ENGINE), P3b.7 (`pc_ops`, `changebox`) | PHYSICAL required |
| S-7 | P3b.2, P3b.4 (ENGINE), P3b.7 (save witness + reload) | PHYSICAL required |
| S-8 | P2.5 (S), P3b.4, P3b.7 (`gift`, `egg_hatch`) | hatch = `gift_daycare` (O-15) |
| S-9g | P2.5 (S), P3b.4, P3b.7 (non-consumption control) | roamer = extra catch (O-17) |
| S-10g | P2.5 (S), P3b.4, P3b.7 (contest zone link) | zone `national_park_contest` (O-18) |
| W-1 | P3b.5 | PHYSICAL required |
| W-2 | P3b.5, P3b.7 (`linked_faint_active`) | PHYSICAL required |
| W-3 | P3b.5 | **conditional** — Explode Mode only if kept (default no) |
| W-4 | P3b.5 | **conditional** — rival team swap; also depends on B-25 |
| W-5 | P3b.5 (Box 14 refusal + current-box positive control), P3b.7 (memorial across a SAVE) | PHYSICAL required |
| W-6 | P2.3 (S), P3b.5 | PHYSICAL required |
| W-7 | P3b.5, P3b.7 (`whiteout`) | PHYSICAL required |
| C-0 | P2.6 (map), P3a.2 (schema), P3b.6 | MODEL-only by design — P column `—` |
| C-1 | P1.3 (S), P3b.3, P3b.7 (`admit_wrong_rom`) | PHYSICAL required |
| C-2 | P3b.6 (MODEL), P3b.7 (`reconnect`) | PHYSICAL required |
| C-3 | P3b.6 (HUD), P4.1 (panel rows) | PHYSICAL required |
| C-4 | P2.6, P3b.6 | MODEL-only by design — P column `—` |
| C-5 | P3b.3 | **conditional** — UPR on Gen 2, else a recorded limit |
| C-6g | P3a.1, P3b.7 (C↔C, G↔S and the C↔G receipt) | PHYSICAL required; every pairing admitted (O-16) |
| D-1 | P2.5 (S), P3b.7 | PHYSICAL required |
| D-2 | P3b.7 (`ball_gate`) | PHYSICAL required |
| D-3 | P3b.7 (`pc_ops`, `changebox`) | PHYSICAL required |
| D-5 | P3b.7 (clauses, `shiny_bonus`) | PHYSICAL required |
| D-6 | P3b.7 (`linked_faint_bench`, `linked_faint_active`) | PHYSICAL required |
| D-7 | P3b.7 (`whiteout`) | PHYSICAL required |
| D-11 | P3b.7 | **conditional** — rival swap / explode if kept |
| D-12 | P3b.6 (MODEL), P3b.7 (GAME/transient) | GAME transient overlay measurement required, or an explicit owner-signed recorded limit; no inherited Gen 1 MODEL closure |
| D-13 | P2.6, P3b.6 | MODEL-only by design — P column `—` |
| D-14 | P3b.7 (`reconnect`) | PHYSICAL required |
| T-1 | P4.3 | PHYSICAL required |
| T-2 | P4.3 | PHYSICAL required |
| T-3 | P4.3 | PHYSICAL required — item validated, carried, read back; invalid refused (O-14) |
| T-4 | P4.3 | PHYSICAL required |
| N-1 | P4.1 | PHYSICAL required |
| N-2 | P4.2 | PHYSICAL required |
| N-3 | P5.1, P5.2, P5.3 | PHYSICAL required; post-RC (O-13) |

**Requirement rows without a substep: 0** — 53 rows (F 7, R 5, S 10, W 7, C 7, D 10, T 4, N 3):
4 SOURCE-only (F-1, F-4, F-5, F-7g), 3 MODEL-only by design (C-0, C-4, D-13), 4 conditional (W-3, W-4,
C-5, D-11), and the REQUIRED-physical count is derived from applicability at each gate: 41 at the first G6 (N-3 is post-RC and becomes required only for the later ghost artifact/gate; disabled conditional rows carry their signed disposition instead), so P6.3 never demands a row the release deliberately excludes.

D-12 is included in that physical count unless the owner signs its explicit recorded limit; such a
limit changes the required count, never the three MODEL-only exemptions or the 53 mapped IDs.
---

## 6. What must not move into the shared layer

The adapter isolation rules are enforced by `.claude/agents/slink-adapter-guard.md`. Applied to
Gen 2:

1. **No `game_id` branch** in `server/server.py`, `server/state.py`, `server/adapters/base.py` or
   `server/pokemon_data.py`. A Gen 2 need becomes an adapter method with an inert default, as
   `supports_explode_mode` (`server/adapters/base.py:282`), `native_trade_ui` (`:308`) and
   `memorial_box_index` (`:529`) already are.
2. Adapters are leaf modules: `server/adapters/gen2_gsc.py` must not import `server.server`, and
   loads its own data from `data/games/gen2_*/`.
3. Game-specific data lives under `data/games/gen2_<title>/`, never at the `lua/` root — which is
   where `lua/gen2_crystal_areas.lua` and `lua/gen2_crystal_locations.lua` sit today (§1).
4. Lua clients live under `lua/gen2/`, as Gen 1's do; game modules never under `lua/games/` for a
   rewritten generation (`lua/slink.lua:83-85` explains why Gen 1 has no `game_detect` row).

Specifically staying inside Gen 2 and out of every shared module:

- Every address: the profile's WRAM/SRAM map, `sBox1`..`sBox14`, `wBattleResult`, `wCurBox`,
  `wPartyMons`, the mailbox address, the tilemap address, the engine-site table.
- Every layout fact: the 48/32-byte structs, the held-item field, the Sp.Atk/Sp.Def split, the
  `BOX_LENGTH` 0x450 box record, the Gen 2 charmap.
- Every policy value: `party_blob_size` 70, `memorial_box_index` 13, `mons_per_box` 20, the gift
  and daycare area sets, `rival_trainer_ids`, the SE code table, the 16 Johto+Kanto badges.
- The write checkpoint **state/ownership predicate**, including the `wSavedAtLeastOnce` refusal (§4
  row 7). Only the predicate is per game: the reusable anchor re-verification and stack evaluation
  move under `gb_checkpoint` per 5.15c (`docs/gen2/PLAN.md:154`; §5 P3b.5). The no-`game_id`, data,
  layout and policy boundaries in this section are unchanged by the extraction rule.

And in the other direction: Gen 2 must not give itself a private rule where the engine has one
(the `SoulLinkState` handlers listed in §2), and must not copy a Gen 1 adapter value into a Gen 2
module — Gen 1's memorial box 11 (`server/adapters/gen1_rby.py:490-492`) is the cautionary example;
Gen 2's 13 comes from its own `memorial_box_index`.

The same boundary applies inside the Lua client: shared lifecycle, deferred queues, reconnect,
transport and presentation reuse bounded shared mechanisms under PLAN §5.15. Only the game facts,
signal handlers and game policies stay in Gen 2. The `client.lua` filename is not a blanket
exception to O-19; extraction/rebind work needs its own exact lease and independent review.

`server/adapters/base.py:559` `gb_status_token` is an existing shared byte-level helper Gen 2 should
bind rather than re-derive: it is the GB status layout both generations share, already used by Gen 1
at `server/adapters/gen1_rby.py:356-358`.

---

## 7. Settled decisions and remaining evidence (original Q numbers retained)

1. **Crystal revision — CLOSED, O-12 / A-1.** Use the local dump's revision, hashed at P1.
   The other revision is build-reproducibility evidence only and a recorded admission limit.
   The historical recommendation to admit both and infer V1.0 from the old fixture is withdrawn.
2. **Duo pairing — CLOSED, O-16 / A-8.** Every Gen 2 pairing uses one `gen2_gsc` foundation:
   G↔S, G↔G, S↔S, C↔C, C↔G and C↔S. Representative lanes are C↔C and G↔S plus one C↔G `link`
   receipt. Gen 2 never pairs with Gen 1/3; same-cartridge pairs use per-instance `saveram_dir`.
3. **Fixtures — SETTLED, PLAN §5.7 / §8.** P3b.2 builds eight saves through
   `tools/gen2_fixtures.py` and scripted routes: town + Route 29 battle for all titles and the
   second-OT Crystal pair. Starter choice releases the New Bark lock (B-18). O-10 permits bag
   balls only; starter and walk stay played. Neither extending the legacy builder nor using its
   old save is the plan; the qualified same-path replacement is preserved at cutover.
4. **RTC tail — OPEN, B-24.** The old save's 32790-byte length measures a 22-byte tail; this is
   historical measurement, not rewrite evidence. The Gambatte `ISaveRam` source citation,
   authoritative tail format and normalization contract remain required; length alone cannot
   define the save-witness slice. Live domain verification is separately B-10.
5. **Sound file — SETTLED, PLAN §5.12.** No `lua/gen2/sound.lua`. The Gen 2 SE table and request
   binding live in `panel.lua`, with shared panel/queue mechanisms and `lua/sfx_arbiter.lua`.
   Ticket 16 still owes the qualified service sites and ABI; no site is selected by this annex.
6. **Enemy-party validity — OPEN, B-25.** Declarations and a link staging site are known;
   non-link-battle read-point validity and live inspection remain unqualified. Do not infer a
   correctness or UI-only verdict from declarations. Native features remain required at G4 (O-4).
7. **Peer ghost — timing CLOSED, O-13 / A-2.** P5 starts only after G6, conditional on ticket 17
   feasibility and owner-signed design. B-7's allocation, sprite/palette, hook cost and save-exclusion
   lifecycle remain open; saved object arrays make a save-free ghost assumption invalid.
8. **Write-safety placement — SETTLED, PLAN §6 P3b / §5.15c.** Keep
   `lua/gen2_write_safety.lua` at the root as the game predicate binder over `gb_checkpoint`.
   Moving either generation's file for tidy-up is outside this plan.

These statuses follow `OPEN_QUESTIONS.md` and the latest rulings in PLAN §0 / REVIEW_RECORD;
they do not reopen owner decisions or sign an implementation gate.

---

## 8. Historical sizing rationale, not implementation targets

The initial estimate used 4,566 lines of Lua under `lua/gen1/` plus 111 in
`lua/gen1_write_safety.lua`, and an adapter/codec of 493 + 975 lines. The table is retained only
as historical planning rationale from before O-19's extraction rule. Its estimates are not a
current census, a copying budget or authority to duplicate shared mechanisms. P2's actual site
and coverage counts and the bounded extraction cards replace those assumptions (PLAN §6).

| Concern | Gen 1 twin | Lines | Gen 2 estimate | Why it differs |
|---|---|---:|---:|---|
| composition root, packs, admission | `lua/gen1/entry.lua` | 423 | 420-480 | current contract is three title packs, one admitted Crystal revision, and the shared admission framework |
| BizHawk bootstrap | `lua/gen1/run.lua` | 82 | 90-110 | CGB system-id gate and no DMG `bank_safe_io` shortcut (§4 row 8) |
| client state machine | `lua/gen1/client.lua` | 1861 | 1700-1900 | historical whole-client estimate; generic lifecycle, queues and reconnect are shared, game handlers/policies remain Gen 2 |
| pure decoders | `lua/gen1/reads.lua` | 328 | 340-400 | 48/32 structs, held item, Sp.Atk/Sp.Def |
| engine signals | `lua/gen1/signals.lua` | 415 | 400-500 | comparable site count; `wBattleResult` masking adds a little (§4 row 9) |
| writes | `lua/gen1/writes.lua` | 200 | 200-260 | the `wSavedAtLeastOnce` refusal (§4 row 7) |
| boxes | `lua/gen1/boxes.lua` | 539 | 400-500 | **smaller**: no checksum arithmetic. **Larger**: the active-box / SaveBox-copyback guard (§4 row 6) |
| ROM tables | `lua/gen1/rom.lua` | 232 | 120-180 | **smaller**: no `PokedexOrder`, species id == NatDex (§4 row 15) |
| native panel | `lua/gen1/panel.lua` | 280 | 280-340 | same shape; the SE table and capability bits move with it |
| native trade overlay | `lua/gen1/trade_overlay.lua` | 206 | 200-260 | same shape |
| write checkpoint | `lua/gen1_write_safety.lua` | 111 | 130-180 | one more predicate |
| **Lua total** | | **4,677** | **4,300-5,100** | |
| server adapter | `server/adapters/gen1_rby.py` | 493 | 450-550 | one class for three titles |
| byte oracle | `server/adapters/gen1_codec.py` | 975 | 900-1,100 | no per-box checksum; whole-save checksums/recovery still required; Gen 2's five-stat layout |
| companion patch ASM | `patch/gen1/src/*.asm` | 1,761 | 1,500-2,000 | panel + receptionist + sound, all re-derived |
| data packs | `data/games/gen1_rby/` (16 files) + `gen1_purergb/` (23) | — | 3 × ~15 files | generated, not written |

The historical subtotal 1,484 + 612 + 164 + 133 + 90 + 416 = 2,899 lines was not a complete
deletion census. PLAN §4 enumerates 15 legacy Lua probe/test scripts and distinguishes REMOVE
from same-path REPLACE. No current size multiplier is asserted; shared extraction changes the
distribution of code between Gen 2 binders and reusable modules.

---

## Fact-question reconciliation (original numbers retained)

This replaces the initial unresolved list; it is an index into `OPEN_QUESTIONS.md`, not a second
fact ledger. SOURCE resolution never supplies MODEL or PHYSICAL qualification.

1. **B-16 SOURCE-resolved.** Both pinned `layout.link` files assign SRAM banks 2/3 directly
   (§4 row 5). The build `.map` verifies the artifact; live domain binding is still B-10.
2. **B-10 OPEN.** The live `CartRAM` domain size and bank-linear binding need P3b.5's receipt.
3. **B-9 OPEN.** CGB `on_bus_exec` / `emu.framecount()` alignment needs the first live probe,
   before the signal gate; Gen 1's DMG receipt is not Gen 2 evidence.
4. **B-8 SOURCE-resolved, PHYSICAL open.** All four hashes are in `gamedb_gbc.txt` as GBC.
   PLAN §5.10 pins CGB explicitly; per-title launcher/core-mode and memory-domain receipts remain.
5. **B-24 OPEN.** The 22-byte tail is historical measurement only; source format and witness
   normalization remain open (§7 Q4).
6. **Whiteout source direction accepted.** PLAN §5.3 uses the CPU site reached from
   `Script_Whiteout` before `HealParty`; P2.2 derives its built-ROM pin and P3b.4 qualifies the
   natural sequence. A script-bytecode label is never an executable hook.
7. **B-3 routine SOURCE-resolved.** Ticket 13 locates `LinkTrade` → `AddTempmonToParty` →
   `EvolvePokemon` → `SaveAfterLinkTrade`. B-3/B-5 leave two-sided takeover, ABI windows and host
   SaveRAM durability open for P4; no receipt is supplied by locating the routine.
8. **B-14/B-22 OPEN.** Odd Egg and gift/static caller attribution require the P2 caller census;
   hatch policy is already settled by O-15, not an open design choice.
9. **B-13 declarations/mutations known, runtime validity OPEN.** `wBattleMode` and its mutation
   sites are located; validity at every consuming read point remains to be qualified.
10. **B-15 declarations resolved.** gen2-A2 located the profile declarations; the old
    "JSON-only" wording is historical. Trainer class/id still require P3b.3a's explicit GAME
    control and the source-qualified trainer-start site; declaration lookup is not runtime proof.
11. **B-25 OPEN at the read points.** Enemy-party declarations/link staging are known; non-link
    battle validity remains open (§7 Q6).
12. **B-20 CLOSED: both reviews returned and were reconciled.** `REVIEW_RECORD.md` records
    `cx-8172d76c` (gen2-C2: boxed-catch, withdrawal-debounce and egg-marker rewrite reasons;
    historical PROFILE_SYMBOL_CHECK 60/60) and `cx-1deb32f4` (gen2-A1: 5/5 findings accepted,
    two documented AP overrides and zero address changes against the HEAD rebuild). Existing
    binding-plan reviews `cx-2a7de2fa` / `cx-3c7fffe9` approved spec/ticket consumption only.
    This editorial cut still needs an independent review; no returned review signs a release gate.
