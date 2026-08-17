# Gen 1 / Gen 2 runtime verification

**Both are automated now.** Gen 2 executed against a cartridge for the first time; before
that its only evidence was a green `pytest`, which is exactly the evidence Gen 1 had while
its client was crashing on the first `box_mon` it received.

This file used to be a 30–60 minute manual checklist that nobody had ever executed — which
is precisely why that crash shipped. Everything it asked a human to click through is now a
test.

## Gen 1 — run these

```bash
pytest tests/unit/ -q                                    # 1595 passed, 5 skipped; no emulator
python tools/verify_profile_addresses.py                 # every address vs pret decomps
SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -q     # 18: 4 gates x 3 cartridges, + patched + AP
SLINK_E2E=1 pytest tests/e2e/test_duo_gen1.py -q         # 18: 9 scenarios x Red/Blue and Yellow/Red
```

| Old manual step | Now |
|---|---|
| 1. Memorialize routing (is it really Box 12?) | `test_duo_gen1.py::memorialize` — asserts the corpse leaves the party AND lands in the memorial box, and that `memorialize_done` is acked |
| 2. Egg-gift classification | still manual for Gen 2; not applicable to Gen 1 (no eggs) |
| 3. Status page rendering | party/enemy/moves/PP/stat-stage reads covered by `test_gen1_memory_gate.lua`; the HTML itself is unit-tested |
| 4. Archipelago variant detection | `tests/unit/test_gen1_archipelago.py` — runs the real Lua against bytes measured from the actual AP basepatch, in **both** directions (AP detected, vanilla NOT misdetected) |
| 5. SFX dispatch | still open — see below |
| 6. Encounter overlay | per-variant tables are generated from pret and asserted in `test_gen1_adapter.py` |
| 7. Gen 3 regression | `/slink-test 3`, run before every change |

## What the automation covers that the checklist never could

The live gates boot a committed battery fixture (`tests/fixtures/gen1/*.SaveRAM`, built by
`tools/gen1_playthrough.py`) and assert against a **running** game: mon keys, PP-Up masking,
the nuzlocke bag gate, `force_faint`, the box round-trip, the 404-byte rival-team write, and
the companion-patch beacon.

The duo E2E runs two emulators and a real server — Red as player A, Blue as player B — and
proves the actual rules: a faint on one machine killing the linked mon on the other, a
deposit auto-boxing the partner's half, a dead pair buried in Box 12, the rival fighting you
with the partner's live team, and Explode Mode coercing Explosion.

Unlike the Gen 3 gates, none of this uses savestates, so nothing goes stale when BizHawk is
upgraded — a `.SaveRAM` is plain SRAM.

## Gen 2 — run these

```bash
pytest tests/unit/ -q                                    # same suite; Gen 2 needs no emulator either
python tools/verify_profile_addresses.py                 # Crystal + Gold/Silver vs pret decomps
SLINK_LIVE=1 pytest tests/live/test_gen2_gates.py -q     # 2 gates, Crystal only
SLINK_E2E=1 pytest tests/e2e/test_duo_gen2.py -q         # 3 duo scenarios, two Crystal instances
```

`--scenario all` is filtered by `--game` and names what it drops, so `--game gen2 --scenario
all` runs exactly the three above. It did not always: the per-scenario `games` key sat in the
runner declared, documented and read by nothing but `tests/e2e/test_duo.py`, so `all` expanded
to the whole table and launched Gen 3-only scenarios against a Game Boy, where they died on a
savestate no GB fixture has. `scenarios_for()` is now the single source of truth for that
question and `tests/unit/test_e2e_duo_scenario_selection.py` pins it. To see the selection
without booting anything:

```bash
python tools/e2e_duo.py --game gen2 --list
```

**Crystal only, and stated rather than silently skipped.** Gold, Silver and Archipelago
Crystal have no dumps here, and a live matrix entry that skips reads exactly like one that
passes. Their addresses are still pret-checked statically; the AP fork has no public repo, so
only five of its addresses are provable and its profile stays flagged unverified.

The two gates run against `tests/fixtures/gen2/crystal_town.SaveRAM` (rebuild with
`python tools/gen2_playthrough.py`), whose contents are known exactly because the
bootstrapper wrote them. The read gate's assertions are deliberately **Gen 2-specific** —
the held-item byte, the map *group*, the Sp.Atk/Sp.Def split, 14 boxes — because a Gen
1-shaped read of a Gen 2 cartridge still returns plausible-looking bytes. The writes gate
mutates a live cartridge: `force_faint`, deposit, withdraw, memorial burial.

The duo E2E runs **two Crystal instances against one dump**, which Gen 1 could not do:
BizHawk names its SaveRAM file from the gamedb entry (ROM hash, not launch path), so two
instances of one cartridge resolve to a single file and stamp on each other. Gen 1 dodged
that by pairing Red with Blue — a constraint on what can be tested together, not a fix.
Per-instance `saveram_dir` is the fix, and it is the only reason a same-cartridge pairing
exists at all.

Three scenarios pass, both sides: `faint`, `boxsync`, `memorialize` — the last burying the
pair in Box 14 (`MEMORIAL_BOX_INDEX` 13, flat CartRAM `0x79E0`), which sits outside Gen 2's
save checksum, so unlike Gen 1 there is no `EmptyAllSRAMBoxes` to defend against and
`M.protectSramBoxes()` correctly no-ops.

`playthrough`, `deadzone` and `dupes` do **not** run on Gen 2, and that is a decision, not an
omission — see "Still open" below.

## Closed since

**SFX dispatch.** Resolved, and the earlier note here was wrong. `wNewSoundID` (`0xC0EE`) is
*not* a sound hook — `PlaySound` takes the id in register `a` and only uses that address as
internal scratch (pokered `home/audio.asm:140`), and nothing in the game loop polls it.
**Gen 1 has no RAM-writable sound trigger at all**, so no choice of address would ever have
worked. The id has to reach a `call`.

The companion patch now provides one: a request byte at mailbox+7, consumed each VBlank at a
point where the game has already switched to `wAudioROMBank` and run `Audio1_UpdateMusic`
(`home/vblank.asm:53-71`). Ids are bank-relative in Gen 1, so the defaults are drawn from the
64 SFX that resolve identically in all three audio banks — a capture or faint fired
mid-battle cannot play the wrong sound. Proven live: `test_gen1_patch_gate.lua` asserts
`wChannelSoundIDs` changes, not merely that the request byte cleared.

Unpatched cartridges and Yellow stay silent by design, and `M.detectCompanionPatch()` gates
on the beacon so that is a clean no-op rather than a stray write.

**Memorial-box SRAM.** Resolved, and the risk was real but not the one recorded here. The
box-bank checksums are **write-only** in vanilla — every reference in the decomp is a store
or a range length, nothing ever reads or compares them — so a stale checksum could not have
reported the save as damaged. SLink recomputes them anyway to keep SRAM self-consistent.

The actual hazard was next door. `ChangeBox` opens with

```
bit BIT_HAS_CHANGED_BOXES, [hl]   ; hl = wCurrentBoxNum, bit 7
call z, EmptyAllSRAMBoxes         ; if so, empty ALL boxes in SRAM
```

(`engine/menus/save.asm:366`, and identically in pokeyellow and Alchav's AP fork). The first
time a player ever picks "CHANGE BOX", the game marks every SRAM box empty as a one-time
init — **including box 12**. Any run that memorialised before the player first opened the box
menu would have lost every buried pair, silently.

`M.protectSramBoxes()` performs that init itself and sets the bit, so the game's wipe can
never fire. Covered by `tests/unit/test_gen1_sram_boxes.py` (8 tests, all mutation-checked)
and by the live writes gate on all three cartridges, which additionally reads the actual
instruction bytes at the `ChangeBox` branch to confirm the game behaviour it defends against.

## Still open

- **A Gen 2 playthrough — deliberately not bought.** Gen 2's fixture parks indoors, because
  New Bark Town's west exit is script-locked until Elm hands over a starter; there is no grass
  fixture and so no `playthrough`, `deadzone` or `dupes`. Those three prove encounter linking,
  the dead zone and the species clause — all enforced **server-side and
  generation-independently**, and all three already run on Gen 1. A Gen 2 grass fixture would
  buy a second copy of coverage that exists, at the cost of driving Elm's whole intro script.
  What it would *not* buy is anything Gen 2-specific: the parts that differ per-cartridge —
  the 32-byte box struct, the split Special, the unchecksummed box banks — are exactly what
  the writes gate and `boxsync` already cover.

  Note Gen 2's SRAM box layout and checksums differ from Gen 1's, so `sram_box_layout` is
  deliberately absent from its profiles and the `EmptyAllSRAMBoxes` guard above does not run —
  the writes gate proves the memorial survives without it.
- **A Gen 1 playthrough.** The gates and duo scenarios prove mechanisms, not play. Concretely, with
  numbers, so nobody has to re-derive this:

  | Never exercised live | Why it matters |
  |---|---|
  | Dead zone, whiteout, all three clauses | still injected. **Encounter linking and the ball gate are now covered** by the `playthrough` scenario, which injects nothing |
  | `area_enter` — **1 of 39** encounter areas | the playthrough resolves `route_1` from the real map, but never crosses a boundary, so no map *transition* is validated |
  | ~~Any real wild encounter or capture~~ | **COVERED.** The playthrough loads the `battle` fixture, hunts, and catches — the `*_battle.SaveRAM` files are no longer dead weight |
  | `party_mon` / `retrieveBoxMon` | the withdraw half of party sync has **never executed on a cartridge** |
  | A battle turn | both duo battles are staged by poking `wIsInBattle`; the engine never consumes our enemy-party or Explosion writes |
  | Evolution / `key_change` | Gen 1 keys embed species, so every evolution rewrites the key |
  | `red_ap` / `blue_ap` | never launched under an emulator; the AP profile relocates exactly the addresses the box and rival writes target |

  Most live box/enemy assertions are also **self-referential** — SLink writes bytes and reads
  them back through the same profile constants — so a uniformly wrong base address would still
  pass. The exceptions, which do discriminate, are the box-level check (differential: level 9
  vs 5), the Poké Ball count, the `ChangeBox` ROM-byte read, and the SFX channel check.
