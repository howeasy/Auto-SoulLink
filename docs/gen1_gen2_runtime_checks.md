# Gen 1 / Gen 2 runtime verification

**Gen 1 is automated. Gen 2 is not, yet.**

This file used to be a 30–60 minute manual checklist that nobody had ever executed — which
is precisely why Gen 1 shipped with a client that crashed on the first `box_mon` it
received. Everything it asked a human to click through is now a test.

## Gen 1 — run these

```bash
pytest tests/unit/ -q                                    # 1528, no emulator needed
python tools/verify_profile_addresses.py                 # every address vs pret decomps
SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -q     # 8 gates on real cartridges
SLINK_E2E=1 pytest tests/e2e/test_duo_gen1.py -q         # 12: 6 rules x Red/Blue and Yellow/Red
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

- **Gen 2.** Three fixes landed here as a side effect of the Gen 1 work — the `play_sound`
  handler was unreachable, `party_to_box` could never fire, and the shared `memory_gb.lua`
  gained profile-keyed box helpers — but Gen 2 still has no live coverage of its own. The
  Gen 1 harness generalises: it needs Crystal fixtures and a profile entry. Note Gen 2's SRAM
  box layout and checksums differ, so `sram_box_layout` is deliberately absent there and the
  guard above does not run.
- **A playthrough.** The gates and duo scenarios prove mechanisms, not play. Concretely, with
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
