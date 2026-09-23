# Gen 2 duo scenario roadmap (worker SCN, 2026-09-23)

The `duo-pairs` lane of `tools/verify_gen2_release.py` is UNIMPLEMENTED. It lists the P3b.7 scenarios
beyond `link`. This file gives one row per scenario: what the scenario closes, which Gen 1 scenario it
copies, what Gen 2 must have first, and who owns each part. Rows are ordered by how soon they can run.

Pinned at `3a64b0e3` (`codex/gen2-foundation`). Game facts come from the pinned decomps only:
`.cache/gen2-build/pokecrystal` 7a7881d and `.cache/gen2-build/pokegold` 656583c.

## Terms

- **Proven sites**: the engine sites a PHYSICAL receipt admits to the production binder
  (`lua/gen2/signals.lua` `qualified_sites`). Today these are `wild_ready`, `capture_party`,
  `capture_party_finalized`, `battle_end`, `save_completed` and `battle_faint`. Every other site in
  `data/games/gen2_*/engine_signals.json` is registered only after its own U1-style live receipt.
- **Box writer**: `lua/gen2/boxes.lua` box/memorial writes. Worker BOX is writing it now. Until it
  lands, the client NACKs `box_mon`, `memorialize` and the other box commands (`BOX_NACK`,
  `lua/gen2/client.lua`).
- **Party write**: the only admitted write is `writes.lua faint_party_slot` at the overworld
  checkpoint, PHYSICAL since `gen2_faint`. No in-battle write window is qualified yet.
- **Owners**: the driver (`lua/tests/duo/scenario_gen2_*.lua`, `duo_gen2_main.lua`) is Claude/SCN. The
  lane and the oracle (`tools/e2e_duo.py`, `tools/gen2_duo_oracles.py`, `tests/e2e/test_duo_gen2_new.py`)
  are Codex (Gen2-Part2). New game facts (route, map and event facts from the decomp) are OMP. New
  engine-site receipts are the U1 gate owner (Codex/coordinator). Fixtures are `tools/gen2_fixtures.py`
  (Codex).
- **Gen 1 reference**: the `gen1_new` rows of `tools/e2e_duo.py` `SCENARIOS`, their bodies in
  `lua/tests/duo/duo_gen1_main.lua` (`scenarios.<name>`) and their oracles (`DuoRun.assert_<name>_saved`
  in `tools/e2e_duo.py`).

## Roadmap

`Wave` is the parallelism class. Every scenario in the same wave can run at the same time: each one is its
own emulator pair with its own SaveRAM dirs and server. A later wave waits only on the prerequisite named
in its row, never on an earlier wave's receipt.

| # | Scenario | Closes (release ids) | Gen 1 reference | Gen 2 prerequisites | Owners | Wave |
|---|---|---|---|---|---|---|
| 0 | `gen2_faint` (done) | D-6 (bench half), W-1, W-6 (overworld) | `linked_faint_bench_new` | none left (H1c driver + H5 lane/oracle committed) | done | done |
| 1 | `reconnect` | C-2 (same-save / wrong-save), D-14, C-6g (reconnect / persisted run) | `reconnect_new` (`duo_gen1_main.lua` `scenarios.reconnect_new`, `assert_reconnect_new` / `assert_reconnect_saved`) | **no new site, no box writer.** Uses proven capture + save only. Lane: kill A after the link save, relaunch A on the flushed save (`phase=same_save`), then on another-OT battle save (`phase=wrong_save`; `crystal_battle_ot2` is the qualified other-OT save, F-6). Needs a qualify `stage_fingerprint` for each staged relaunch save | driver SCN (this card); lane + oracle Codex | **A** |
| 2 | `soft_reset` | C-2 (WRAM clear), R-4 (reset pauses writes, hello waits), W-6 (no write on the cleared window) | `soft_reset_new` (`scenarios.soft_reset_new`, `assert_soft_reset_saved`) | **no new site, no box writer.** The client already detects the WRAM clear through `validate()` (`player.ot_id == 0` means boundary, then MAX_INVALID pauses writes). Game facts, both repos: `UpdateJoypad` resets on `hJoypadDown & PAD_BUTTONS == PAD_BUTTONS` in the same VBlank (C `home/joypad.asm:98-102`, G `:99-102`), with no 16-poll countdown as in Gen 1. `Reset` waits `DelayFrames 32`, then `jr Init`. Crystal's `Init` clears WRAM0 and WRAMX bank 1 (C `home/init.asm:1-19,66-75,93,186-189`). Gold/Silver's `Init` clears the $C000-$DFFF span directly (G `home/init.asm:1-14,58-67`). *Optional upgrade:* a PHYSICAL `soft_reset` site receipt (`Reset` C `00:0150`, G/S `00:05b0`) would give the coverage map's independent ENGINE occurrence | driver SCN (this card); lane + oracle Codex; site receipt U1 owner (optional) | **A** |
| 3 | `admit_wrong_rom` | C-1 (admission refuses unknown sha1), C-6g (a rejected hello leaves state unchanged) | `admit_randomized_new` (`scenarios.admit_randomized_new`, `assert_admit_randomized_new/_saved`) | **no new site, no box writer.** Refused half runs `.cache/gen2-build/pokecrystal/pokecrystal11.gbc` (Crystal 1.1, built but not selected; `run.lua` refuses by sha1). Admitted half runs the normal battle fixture. Further refusal inputs from the coverage map (altered anchor, unknown hash, AP or randomized) are more lane rows over the same driver | driver SCN (this card); lane + oracle Codex | **A** |
| 4 | `type_clause` | D-5 (type) | `type_clause_new` | Capture sites are proven. The rejected half gets `force_faint` (party write, proven), then `memorialize`, which needs the **box writer**, or the driver accepts the current NACK the way `SCENARIO_END_STATUS` accepts `memorial`. Route 29 grass is not all one type, so the verdict can be "no clause", unlike Gen 1 Route 1. **Facts (OMP):** Route 29 per-title/per-time species and types (C/G `data/wild/johto_grass.asm`), so the lane knows when a shared type is guaranteed or must retry | driver SCN; lane + oracle Codex; facts OMP; box writer BOX | **B** (after box writer, or now with the NACK ending) |
| 5 | `species_clause` | D-5 (species) | `species_clause_new` | Same as `type_clause`, plus a battle **RUN** input: `gen2_route29_inputs.lua` only catches. A new `gen2_*_inputs.lua` needs RUN over the proven `BATTLE_MENU_GRID`, with no new site (`battle_end` is proven). Needs the Route 29 family facts (OMP) | driver SCN; lane + oracle Codex; facts OMP; box writer BOX | **B** |
| 6 | `gender_clause` | D-5 (gender) | none (Gen 1 has no gender); server `--gender-clause` | Same as `type_clause`. **Facts (OMP):** gender ratio per Route 29 species (base stats `GENDER_*`) and the DV-derived gender rule (R-5g) | driver SCN; lane + oracle Codex; facts OMP; box writer BOX | **B** |
| 7 | `linked_faint_active` (the rest of "faints") | D-6 (active), W-2 | `linked_faint_active_new`, `linked_faint_bench_battle_new` | **New write window:** an in-battle `force_faint` at the battle-loop head (W-2). `writes.lua` refuses `faint_active_battler` until a U2-style PHYSICAL window receipt exists. A memorial ending needs the **box writer** | window proof U2 owner; driver SCN; lane + oracle Codex; box writer BOX | **C** |
| 8 | `boxed_capture` | S-2, S-3, D-3 (box half) | none as a duo (Gen 1 S-3 was a live gate) | **Sites:** `capture_box`, `capture_box_finalized` PHYSICAL. **Box writer** (server `box_mon` quarantine). **New fixture:** a party-full battle save (6 mons), plus a 19-in-box control for the twentieth slot (S-3) | site receipt U1 owner; fixture Codex; driver SCN; lane + oracle Codex; box writer BOX | **C** |
| 9 | `pc_ops` | S-6, D-3, W-5 (listing) | `pc_ops_new` | **Sites:** `pc_deposit_*`, `pc_withdraw_*`, `pc_release_*` PHYSICAL. **Box writer.** **Facts (OMP):** walk Route 29 to Cherrygrove Pokemon Center (warp, PC tile and Bill's PC menu, C `engine/pokemon/bills_pc_top.asm`, G same) | site receipt U1 owner; facts OMP; driver SCN; lane + oracle Codex; box writer BOX | **C** |
| 10 | `changebox` | S-6, D-3 (box change), W-5 | `changebox_new` | **Sites:** `change_box_begin`, `change_box_loaded`. **Box writer** (Box 14 memorial listed). **Facts:** the same PC route as `pc_ops` and the `BillsPC_ChangeBoxMenu` rows (`bills_pc_top.asm:226`) | as `pc_ops` | **C** (with `pc_ops`) |
| 11 | `whiteout` | D-7, W-7 | `whiteout_new` | **Sites:** `whiteout_before_heal` (before `HealParty`, `whiteout.asm:14`) and the PC deposit sites (both halves box their catch first). **Box writer** (the rebuild moves boxed mons). **Facts (OMP):** a lossable wild fight near Route 29, like the faint route | site receipts U1 owner; facts OMP; driver SCN; lane + oracle Codex; box writer BOX | **D** (after `pc_ops`) |
| 12 | `poison` | S-4 (poison half), D-7 | `poison_new` | **Site:** `poison_faint` (`DoPoisonStep`, G/S `14:4610`, C `14:45da`) PHYSICAL, then `whiteout_before_heal`. **Facts (OMP):** the nearest natural poison source per title (a poisoning wild species/move reachable from Route 29/30) and its walk. **Fixture:** probably a new save next to that source | site receipts U1 owner; facts OMP; fixture Codex; driver SCN; lane + oracle Codex | **D** |
| 13 | `evolution` | S-5 (evolution), D-1 (key_change) | none as a duo (`test_gen1_evolution_gate.lua` is a live gate) | **Site:** `evolution_species_published` PHYSICAL. **New fixture:** a party mon one level short of a level evolution on a grass save (for example an early Caterpie/Weedle line on the facts' route). **Facts (OMP):** which mon and level (`data/pokemon/evos_attacks.asm`) | site receipt U1 owner; facts OMP; fixture Codex; driver SCN; lane + oracle Codex | **D** |
| 14 | `npc_trade` | S-5 (NPC trade), D-1 (key_change) | none (Gen 1 had no NPC-trade duo) | **Sites:** `npc_trade_begin`, `npc_trade_finalized`. **New fixture:** a save next to the first in-game trader with the requested species in the party. **Facts (OMP):** trader map/NPC and the requested and offered species per title (`data/events/npc_trades.asm`, both repos) | site receipts U1 owner; facts OMP; fixture Codex; driver SCN; lane + oracle Codex | **E** |
| 15 | `gift` | S-8 (gifts) | `ball_gate_new` (the starter gift pair) | **Sites:** `gift_begin`, `gift_party_finalized`, and `new_game` for a cold start. **Route:** the starter pick is already played by the fixture chain (`tools/gen2_fixtures.py`, town = Elm's lab after the starter), so a cold-boot lane replays it. **Facts:** the existing scripted route facts | site receipts U1 owner; lane (cold boot) Codex; driver SCN | **D** |
| 16 | `ball_gate` | D-2 | `ball_gate_new` | Needs everything `gift` needs, plus **site** `bag_ball_received` and a **long new route**: Elm's lab, Mr. Pokemon, back to Elm, then the aide's `giveitem POKE_BALL, 5` (C `maps/ElmsLab.asm:498-508`, G `:455-465`). O-10 injects balls because no earlier ball exists. **Facts (OMP):** that route, including the Route 29/30 walk and the rival fight | site receipts U1 owner; facts OMP; driver SCN; lane + oracle Codex | **E** (after `gift`) |
| 17 | `egg_hatch` | S-8 (hatch as `gift_daycare`, O-15) | none (Gen 2 only) | **Sites:** `hatch_species`, `hatch_finalized`. **New fixture:** an egg a few steps from hatching (the Mystery Egg follows the `ball_gate` errand; a Day-Care egg is later). **Facts (OMP):** the egg-cycle step count and the egg source per title | site receipts U1 owner; facts OMP; fixture Codex; driver SCN; lane + oracle Codex | **E** |
| 18 | `shiny_bonus` | D-5 (shiny bonus pairs) | none (Gen 1 has no shinies); server shiny clause (`state.py` `bonus_keys`) | Natural shinies are 1/8192, and the harness never writes DVs. The only fixed shiny is Crystal's Lake of Rage red Gyarados, a static encounter. It needs a **new fixture** at Lake of Rage, a PHYSICAL **static-acquisition site** (`script_wild_staged` plus its finalize), and **facts** for that encounter. The other choice is an **owner-signed recorded limit** | owner decision first; then fixture Codex, facts OMP, site U1 owner, driver SCN | **F** (owner decision) |

`D-12` (game-over HUD) and `W-5` (memorial survives `SaveBox`) are measured inside the box-writer
waves (C/D). They are not separate scenarios here.

## Runnable now (wave A)

`reconnect`, `soft_reset` and `admit_wrong_rom` need no new engine site, no box writer and no new
fixture. Their drivers follow in this card (`lua/tests/duo/scenario_gen2_{reconnect,soft_reset,admit_wrong_rom}.lua`),
each with a marker contract in its header. All three can run in parallel as soon as Codex registers the
lanes. `type_clause`, `species_clause` and `gender_clause` are the next cheapest (wave B). Their capture
path is proven. They wait only on the box writer, or on an owner/Codex ruling that a memorialize NACK
ending is acceptable, and on the Route 29 species facts.
