# Gen 1 Game Data (Red/Blue/Yellow)

Data files for Gen 1 Pokémon games (Game Boy / Game Boy Color).

## Status

🟡 **Partially verified.** The mechanisms are proven against running cartridges; a playthrough
is not. Every profile address is checked against the pret decomp .sym output by
[tools/verify_profile_addresses.py](../../../tools/verify_profile_addresses.py), and on top of
that:

```bash
SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -q   # 8 gates: memory + writes x RBY, patch x 2
SLINK_E2E=1 pytest tests/e2e/test_duo_gen1.py -q       # 5 scenarios, two emulators, real server
```

The duo E2E runs **Red as player A and Blue as player B** and proves faint propagation,
party->box sync, memorialize to Box 12, the rival-team write and Explode Mode. Fixtures are
battery saves (`tests/fixtures/gen1/*.SaveRAM`) built from a cold boot by
[tools/gen1_playthrough.py](../../../tools/gen1_playthrough.py); unlike the Gen 3 `.State` files
they are not BizHawk-version-locked, so they never go stale.

**What that does NOT cover.** Every duo pair is injected through `/api/inject_link` and the
Nuzlocke gate is force-set, so encounter linking, the dead zone, whiteout and the three clauses
have no live evidence. No live test has ever caught a Pokemon, changed maps, or let the battle
engine execute a turn; both duo battles are staged by poking `wIsInBattle`. **0 of the 39
encounter areas** in `encounter_tables.json` are ever visited — every test sits in Pallet Town.
`retrieveBoxMon` (the withdraw half of party sync) has never run on a cartridge, and the
Archipelago variants have never been launched. See
[docs/gen1_gen2_runtime_checks.md](../../../docs/gen1_gen2_runtime_checks.md).

## Files

- `area_map.json` — Map ID → `{area_id, display name}` source (86 entries; all three games share IDs). Generates the `.lua` lookup tables.
- `gen1_rby_areas.lua` — Generated Map ID → encounter area_id lookup (from `area_map.json`)
- `gen1_rby_locations.lua` — Generated Map ID → display name lookup
- `moves.json` — 165 moves: name, type, power, accuracy, pp, split
- `trainers.json` — `classes` (class_id → class name) + `named_trainers` (gym leaders, E4, rivals)
- `encounter_tables.json` — Wild encounter slots, keyed **by game version first**
  (`red` / `blue` / `yellow`), then by area_id. 39 areas each. Red and Blue differ in 25 of
  those areas and Yellow differs from Red in 36, so they cannot share one table — the
  generator honours pokered's `IF DEF(_RED)` / `IF DEF(_BLUE)` blocks and reads Yellow from
  pokeyellow. Regenerate with `python tools/gen_gen1_encounters.py`, which refuses to write
  unless every method block sums to 100% with no zero-rate species.
- `species_index.json` — Internal species index ↔ National dex map

## Sources

- [pret/pokered](https://github.com/pret/pokered) — Red/Blue decompilation
- [pret/pokeyellow](https://github.com/pret/pokeyellow) — Yellow decompilation
- Archipelago: [Alchav's pokered fork](https://github.com/Alchav/pokered) (branch
  `pokemon-archipelago`) for Red/Blue; no Yellow AP world upstream. Detected by decoding the
  seed name at **ROM offset `0x5F22`** (`Title_Seed`) from the flat `ROM` domain — it is in
  bank 1, so a System Bus read would return whichever bank is mapped. Detection tests
  "does this decode as Gen 1 text", never a specific string: the shipped basepatch holds the
  placeholder `(NOT RANDOMIZED)` and a generated multiworld overwrites it with the real seed.
  **AP relocates WRAM.** The fork adds ~121 lines of tracking variables, moving 861 of the
  2171 symbols shared with vanilla — `wCurMap` +216, `wEnemyMons` −18, the PC box block +11.
  `M.PROFILES.red_ap` therefore overrides 11 addresses and inherits the rest; those overrides
  are verified against the `alchav_pokered` entry in `data/pret_syms.json`.

## Notes

- Mon identity: composite key `DDDD:TTTT:II` (DVs + OT ID + internal species index). Evolution changes the species byte → key changes → `key_change` event migrates it.
- Shiny: not applicable (no shiny mechanic in Gen 1).
- Platform: Game Boy — Gambatte core in BizHawk. Memory domain: "System Bus".
- Variants: `red` / `blue` / `yellow` (vanilla), `red_ap` / `blue_ap` (Archipelago).
- Stat stages: Atk/Def/Spd/Spc/Acc/Eva (6 bytes; Special is unified in Gen 1). Client normalizes Gen 1's 1..13 (neutral 7) encoding to Gen 3's 0..12 (neutral 6) so the existing renderer works as-is. Special mirrors into both SAtk and SDef slots for display.
- Moves: 4 move IDs at party_struct +0x08; 4 PP bytes at +0x1D. PP is **packed**, not raw:
  pret/pokered defines `PP_UP_MASK %11000000` / `PP_MASK %00111111`, so the low 6 bits are
  current PP and the top 2 are the PP-Up count — same encoding as Gen 2 (`pp_encoding = "ppup_packed"`).
- Badges: 8 badges tracked via bitfield at wObtainedBadges.
- Memorial box: Box 12 (via `M.depositMemorialMon`; falls back to `depositPartyMon` if Box 12
  is full). **The deposit claims the SRAM box banks first.** `ChangeBox` empties every SRAM box
  the first time the player opens the box menu (`bit BIT_HAS_CHANGED_BOXES` / `call z,
  EmptyAllSRAMBoxes`, save.asm:366), which would erase the memorial; `M.protectSramBoxes()`
  performs that one-time init itself and sets the bit so the game's wipe never runs. Box-bank
  checksums are recomputed for consistency, but vanilla never reads them.
- Sound: **requires the companion patch.** Gen 1 has no RAM-writable sound trigger —
  `wNewSoundID` is `PlaySound`'s internal scratch, not a polled mailbox — so unpatched Red/Blue,
  Yellow and AP builds are silent and `playSfx` is a no-op. Ids are bank-relative; the defaults
  use only the 64 SFX that resolve identically in all three audio banks.
- **Rival Team Swap and Explode Mode need no ROM patch.** Gen 3 required the companion
  patch for the swap because `gEnemyParty` is encrypted and checksummed; Gen 1's enemy party
  is plaintext at a fixed address, so `M.writeEnemyParty` is a byte copy over
  `wEnemyPartyCount` (`0xD89C`) → species list → `wEnemyMons` → `wEnemyMonOT` → `wEnemyMonNicks`,
  a contiguous 0x194-byte block. Rivals are identified by CLASS: RIVAL1/2/3 = `$19`/`$2A`/`$2B`
  + `OPP_ID_OFFSET(200)` = **225 / 242 / 243**, read from `wCurOpponent`.
  Per `LoadEnemyMonData`, a trainer mon takes species, HP, status, moves and level from the
  structs we write, but its **stats and DVs are recomputed with fixed trainer DVs** — so a
  swapped team fights at the partner's levels with their moves and HP, not as byte-perfect
  clones. Explode Mode writes Explosion (move 153) into the active battler's move slot 0 and
  `wPlayerSelectedMove`; the active slot comes from `wPlayerMonNumber` (`0xCC2F`), never
  assumed to be slot 0.
  Timing of both writes was derived from pret source and then measured on hardware by
  `lua/tests/probe_gen1_{rivalswap,explode}.lua`: the swap must land **before the first
  send-out** (`LoadEnemyMonData` re-derives the active mon from the party arrays), so the
  client writes on `trainer_battle_start`, gated on three stable frames of `wIsInBattle == 2`.
  Both are exercised end-to-end by the `rivalswap` and `explode_g1` duo scenarios.
- Sprites: Gen 1 Red/Blue transparent sprites from PokeAPI with pixelated rendering and edge crop.
