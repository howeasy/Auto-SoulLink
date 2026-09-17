# Gen 1 / Gen 2 runtime verification

**Gen 1 was rewritten, and this file now describes the rewrite.** The old Gen 1 sections — the
manual checklist's descendants, the pre-rewrite gate list, and the ABI-3 panel narrative — were
deleted with the code they described. The production launchers now load the new client too
(commit `ca17a26`): `lua/slink_gen1.lua` `dofile`s `lua/gen1/run.lua` directly, and the
universal `lua/slink.lua` routes any GB/GBC cartridge through `Entry.detect_title` to
`lua/gen1/run.lua` before it ever reaches the legacy `game_detect`/`_CLIENT_MAP` path. The new
client is `lua/gen1/run.lua` (BizHawk entry: io, transport, HUD, frame loop) over
`lua/gen1/entry.lua` (composition root), and the live gates load it directly. The old
`lua/clients/gen1_rby_client.lua` / `lua/games/gen1_rby.lua` client was retired in Track B
step 5 (P8-4) and no longer ships in the player ZIP or exists in the tree.

**The Gen 2 sections below are unchanged.**

## Gen 1 — run these

```bash
python tools/verify_gen1_release.py --quick      # the 8 fast lanes; no emulator
python tools/verify_gen1_release.py              # all 12 lanes, emulator lanes included
python tools/verify_gen1_release.py --lane live-new-gates    # only the physical lane
python tools/verify_gen1_release.py --list       # lanes + the requirement ids each serves
```

A lane that did not run did not pass: a skip is a failure in this runner, which is why a
missing ROM, jar or emulator fails the gate rather than shrinking it.

Twelve lanes: `unit`, `rom-layout`, `lua-parse`, `profile-addresses`, `profile-generated`,
`statics-generated`, `fixtures`, `patch-build` (fast) and `live-gates`, `live-new-gates`,
`live-trade-gates`, `duo-pairs` (slow, emulator). The two that carry the rewrite:

* **`live-new-gates`** (`SLINK_LIVE=1`) runs `tests/live/test_gen1_new_gates.py`: six inspect
  cases (3 titles × town/battle) that boot a committed battery save in EmuHawk and run
  `lua/tests/test_gen1_inspect_gate.lua` on the real cartridge, then decode the raw party bytes
  the gate dumped with the Python codec — Lua on hardware and Python on the same bytes must
  agree field for field — plus two scripted New Game runs (Red and Blue) driven by
  `lua/tests/test_gen1_scripted_gate.lua` with ordinary buttons.
* **`fixtures`** runs `python tools/gen1_fixtures.py --qualify`, which re-checks every committed
  battery save against the codec without an emulator.

## Gen 1 — the fixtures

`tests/fixtures/gen1/<rom>_{town,battle}.SaveRAM` — six files, 32 KiB of plain SRAM each:

| target | contents |
|---|---|
| `town` | Oak's Lab after the rival battle, on encounter-free tiles |
| `battle` | Route 1 at (10, 35), one Poké Ball in the bag |

They are built from **scripted play**, not written byte-wise: `tools/gen1_fixtures.py` drives a
cold cartridge through the `lab,save` / `lab,parcel,route1,save` chains and copies the SaveRAM
out only if `qualify()` accepts it (game checksums, a decodable party, exp consistent with the
level on the species' growth curve).

Current state (`python tools/gen1_fixtures.py --qualify`): Red and Blue, 4 OK — a real game
state each. **Yellow's two are LEGACY**: old tool-written bytes whose party mon has a level byte
with exp 0, which no game state produces. They are named individually in
`tools/gen1_fixtures.py` (`LEGACY`) so a regenerated fixture cannot hide behind a blanket
tolerance; Yellow needs its own scripted route or an owner-made save.

## Gen 1 — proven live

Exactly the rows of `docs/gen1_requirements.md` whose PHYSICAL column is ✓:

| id | what a cartridge proved |
|---|---|
| F-2 | every pinned hook site's expected bytes are present in the running ROM (inspect gate, 3 titles) |
| F-6 | the four R/B fixtures are real game states — scripted play, then `--qualify` |
| R-1 | Lua on hardware decodes the live party identically to the Python codec (inspect gate, 6/6) |
| S-1 | scripted NEW GAME → starter → rival on Red and Blue: the engine-signal sequence matches pret's script order; the starter is L5 with exp 135 |
| W-7 | `gen1_write_safety.check()` reaches the verified overworld checkpoint, idle, on all three titles |

## Gen 1 — not yet proven live

Everything else in the ledger. Rows whose PHYSICAL column is `·`:

| id | still open |
|---|---|
| F-3 | the differential gate over all 17 pinned sites |
| R-2 | stats leg ✓ MODEL (blocked level leg: see the Yellow fixtures above) |
| R-3 | trainer class/name, badges, PP-Ups, active box index |
| R-4 | title screen never validates; soft reset revokes writes |
| S-2 | wild encounter, capture, `no_catch`, ball detection |
| S-3 | party-full capture via `SendNewMonToBox` |
| S-4 | poison faint and blackout ordering |
| S-5 | evolution and NPC-trade `key_change` |
| S-6 | PC deposit / withdraw / release / `ChangeBox` |
| S-7 | save witness and CONTINUE |
| S-8 | `area_enter`, statics, gifts, fishing map ids |
| W-1 | benched `force_faint` at the checkpoint |
| W-2 | active-battler faint at the loop head |
| W-3 | `force_explode` across all four move slots |
| W-4 | `replace_rival_team` validation and atomicity |
| W-5 | box / memorial writes that survive a save reload |
| W-6 | gate revocation and every NACK path |
| C-1 | hello identity / wrong-save rejection |
| C-2 | reconnect mid-run |
| C-3 | dashboard rendering for Gen 1 |
| D-1 … D-14 | the whole duo lane: linking, the ball gate, the dead zone, the clauses, faint propagation, whiteout, memorial, PC sync, trade/evolution key migration, rival swap, game over, key non-uniqueness, reconnect |
| T-1 | ◐ panel gates pass on the trade-carrying build; **the receptionist menu has not been driven live** |
| T-2 … T-4 | offer eligibility, partner prompt, apply/evolution |

Rows the ledger marks `—` (F-1 addresses, F-4 ROM tables, F-5 families and dex order, C-0
protocol conformance, C-4 unwedgeable client, T-5 crash mid-trade) take no cartridge proof by
design. For the first five that is because SOURCE or MODEL evidence is what they call for; T-5
is different — its MODEL row is not written yet either, so the crash-mid-trade watchdog is open
work even though no physical proof is owed.

## Gen 1 — the three write windows

Every byte SLink writes to a cartridge lands in one of these, and nowhere else:

1. **The overworld checkpoint** — `lua/gen1_write_safety.lua` accepts the CPU only when parked
   in `DelayFrame` from `OverworldLoop` in the idle state; deferred box/party/memorial writes
   run one per frame from there.
2. **The `MainInBattleLoop` head** — the only site where an in-battle write is allowed
   (`wBattleMonHP=0` + `wPlayerSelectedMove=$FF`, and the Explode-mode coercion), behind its own
   guards.
3. **The trade lease** — the 16-byte lease the patched game hands the host at
   `wSerialPartyMonsPatchList`; the staged trade writes happen inside it, not at the checkpoint.

## Gen 1 — documented limits

* **Pokémon Tower ghosts are not failed encounters.** A wild battle on `$8E–$94` without the
  Silph Scope (`$48`) in the bag cannot be fought or caught, so the client suppresses `no_catch`
  for it instead of dead-zoning the whole Tower.
* **A trade whose native append returns 2 is held, not recovered.** The client shows
  `TRADE UNCERTAIN - CHECK PARTY`, keeps the lease and claims nothing; there is no paired
  recovery path (T-5).
* **Yellow's two fixtures are legacy bytes** (see above), so the physical lane's Yellow coverage
  is the `town`-shaped inspection only.
* Carried forward from the pre-rewrite client, because the Gen 2 note below refers to it: the
  rewrite does **not** run `M.protectSramBoxes()`'s one-time `EmptyAllSRAMBoxes` init. Instead
  `lua/gen1/boxes.lua` refuses to write SRAM boxes until the game has initialised them
  ("saved boxes not initialized"), so there is no window in which the game's first `ChangeBox`
  could wipe a burial.

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
