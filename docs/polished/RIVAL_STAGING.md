# Rival gate measurement with SYNTH staging

Design only, 2026-10-07. No fixture, probe, production code, or live receipt is
changed by this card. Repository cut: `766935aaec752b0d1a2e3b1d88587b4e7c55bc7b`
(`claude/pol-docs3`). The owner instruction for this card authorizes the staged
measurement; `docs/gen2/REVIEW_RECORD.md:44` (O-33) permits disclosed synthetic
setup while requiring the behavior under test to run natively.

## 1. Encounter selection and evidence boundary

Use **Cherrygrove City, RIVAL0 trainer 3**, triggered at **(33,7), scene 1**.
The minimum save derivative changes only the Cherrygrove scene byte in both
copies and their checksums. Keep Route 29 (48,12), all objects, and the existing
five-mon party. Walk into Cherrygrove through the real map connection.
This minimizes edited state, not walking frames: it skips the entire
starter/Mr. Pokemon story prerequisite without manufacturing battle state.
There is no live proof yet that this candidate route completes.

References beginning `src/` below mean
`F:/slink-work/cache/polished/src/`; other references are relative to
`F:/slink-work/wt/pol-docs3/`. Read-only `git -c safe.directory=... rev-parse HEAD`
reported source commit `3fa43192379df5c3e7b09a08e4d5d79af4f02f42`, matching
`data/polished/overlay_provenance.json:4-8`. No source rebuild was performed.

* `src/maps/CherrygroveCity.asm:15-17`: scene 0 runs the guide; scene 1 runs
  rival triggers at (33,6) and (33,7). `src/data/maps/scenes.asm:25` maps this
  scene to `wCherrygroveCitySceneID`. Coordinate matching checks scene and
  player coordinates (`src/home/map.asm:1548-1573`).
* The south trigger moves the rival from (39,6) to (39,7), explicitly appears
  him, walks him five tiles left, and displays challenge text
  (`src/maps/CherrygroveCity.asm:27,88-108,244-250`).
* Branch selection checks TOTODILE, then CHIKORITA starter flags; neither set
  selects `loadtrainer RIVAL0, 3`, `BATTLETYPE_CANLOSE`, `startbattle`
  (`src/maps/CherrygroveCity.asm:100-129`). Trainer 3 fields level-4 RATTATA
  and level-5 TOTODILE holding ORAN_BERRY
  (`src/data/trainers/parties.asm:1085-1088`). Moves, generated stats, ability,
  and RNG-dependent attributes are not established here.
* `EVENT_RIVAL_CHERRYGROVE_CITY` is an object visibility bit, not a trigger
  prerequisite. It is already set in this fixture. Set bits mask objects
  (`src/engine/overworld/map_setup.asm:273-301`); the script's `appear` copies
  the object and clears its event bit natively
  (`src/engine/overworld/scripting.asm:1059-1074`). Do not clear it in setup.
* Natural story progression sets scene 1 at Mr. Pokemon's house
  (`src/maps/MrPokemonsHouse.asm:129-135`). That story is deliberately bypassed;
  this fixture must never be described as having played it.

**Earliest is not synonymous with simplest to stage.** The first Lyra fight
is earlier in ordinary progression: Elm's lab sets scene 6 after starter
selection (`src/maps/ElmsLab.asm:313-331`), and (4,6), scene 6 triggers it
(`:26,562-598`). LYRA1_1/2/3 field one level-5 Chikorita/Cyndaquil/Totodile
respectively (`src/data/trainers/parties.asm:1405-1415`). But the laboratory
sequence also places/moves Lyra; the default object is at (5,11)
(`src/maps/ElmsLab.asm:53,566`). A bare scene/position patch does not reproduce
that setup. Cherrygrove's first RIVAL0 encounter explicitly places and appears
the rival and needs only one scene edit per save copy. Azalea's later RIVAL1
branches are at `src/maps/AzaleaTown.asm:87,96,105`; no claim of complete
Azalea reachability is made. A global minimum-frame comparison is UNVERIFIED.

**Can the original fixture just walk there?** Map connectivity says yes to
the city: Route 29 west connects to Cherrygrove with offset 0
(`src/data/maps/attributes.asm:15-18,73-75`). But walking alone cannot trigger
this fight: the fixture's Cherrygrove scene is 0, so it selects the guide,
not the rival. The scene-only derivative makes the native walk sufficient
at the source level; live timing remains OPEN.

## 2. Exact minimum SaveRAM delta

Read directly in this card:

* Input: `F:/slink-work/lanes/pol-live/fixture/polished_overlay_warp.SaveRAM`.
  Length 32790; SHA256
  `75c7a5dc30126f746567202cfb39fe583dfa04eb226063560541f6cbd29f36b8`.
  This matches `docs/polished/LIVE_RESULTS.md:35-52`.
* Main/backup game-data regions are byte-identical and both have computed and
  stored sum `13E4`. PowerShell byte reads and an in-memory candidate calculation
  were used; no SaveRAM file was written.

Flat SRAM addressing is `bank * 0x2000 + address - 0xA000`.
`data/polished/polished_slink.sym:49361-49378` gives backup `00:B208`,
main `01:A008`, map-data main `01:A82E`, and checksum addresses.
`wPlayerData=01:D478` (`:66605`),
`wCherrygroveCitySceneID=01:D9F2` (`:67442`), so the scene offset within
player data is `D9F2-D478=057A`. SRAM copies reserve the same player/map/party
lengths (`src/ram/sram.asm:19-23,48-52`); load copies those blocks directly
(`src/engine/menus/save.asm:542-560`).

| Field | Main flat | Backup flat | Old -> new |
|---|---:|---:|---|
| Cherrygrove scene | `0x2582` | `0x1782` | `00 -> 01` |
| Checksum, little-endian | `0x2D0D..0x2D0E` | `0x1F0D..0x1F0E` | `E4 13 -> E5 13` |

**Backup displacement is `0xE00`, not `0x1000`.** For each copy independently,
sum unsigned bytes modulo 65536 over main `[0x2008,0x2B83)` or backup
`[0x1208,0x1D83)`, then store low byte followed by high byte at its checksum
address (`tools/polished_live/derive_save.py:80-82,110-115,196-199`). Do not
merely increment a stored checksum without validating the original and
recomputing the result. Expected actual diff is exactly four offsets:
`1782,1F0D,2582,2D0D`. The in-memory result's SHA256 is
`030c62ff898050d81d80dea19677e8520e2f707dae0c35f873d87e79cf7ac1ae`.
That digest is a builder expectation, not evidence of game acceptance.

Read-only preconditions (all checked against this input):

| State | Derivation and expected value; no edit |
|---|---|
| Map and position | `wCurMapData=DC9E`, `sMapData=A82E`; symbols `:67648,67660-67663`. Main `283C..283F`, backup `1A3C..1A3F` = `18 03 0C 30` (group 24, map 3, Y=12, X=48). Cherrygrove is group 26/map 4 (`src/constants/map_constants.asm:579-583`), reached natively. |
| Starter selection | `wEventFlags=DA5A` (`sym:67546`), main base `25EA`, backup `17EA`. Constants are zero-based from `src/constants/event_flags.asm:3`; Cyndaquil/Totodile/Chikorita are bits 28/29/30 (`:42-44`). Byte `25ED` / `17ED` is `00`: preserve it; neither branch predicate is set, so trainer ID must be 3. |
| Rival visibility | Event index `0x687`, derived by counting `const` entries through `src/constants/event_flags.asm:1832` (no intervening `const_next`). Byte `26BA` / `18BA` is `95`, mask `80` set. Preserve; native `appear` clears it. |
| Party | Count `285E` / `1A5E` = `05`; structs begin `2866` / `1A66`, 48 bytes each (`derive_save.py:15-18,55`). Preserve all structs, OT names and nicknames. Existing level-50 Crobat/Jolteon/Golduck/Nidoking/Dodrio setup is disclosed in `LIVE_RESULTS.md:45-47`; no stronger party is needed for a send-out measurement. |

MUST NOT edit: any other scene or event bit; identity; party, HP, PP, items,
stats or species; boxes; bag; map/object caches; current/previous map or spawn
fields; options; save version/phase/markers; RTC footer `[0x8000,32790)`;
battle mode/class/id, enemy party, selected indices, script/CPU state, ROM,
gate bytes or the eventual observed enemy record. `derive_identity` and
`held_item_variant` are separate builders (`derive_save.py:232-299`), not
prerequisites and not appropriate to compose into this derivative.

Read-only reproduction of the arithmetic, without Python or file output:

```powershell
$fixture = 'F:/slink-work/lanes/pol-live/fixture/polished_overlay_warp.SaveRAM'
$original = [IO.File]::ReadAllBytes($fixture)
$candidate = [byte[]]$original.Clone()
if ($original.Length -ne 32790) { throw 'unexpected save length' }
foreach ($offset in @(0x1782, 0x2582)) {
    if ($original[$offset] -ne 0) { throw 'unexpected original scene' }
    $candidate[$offset] = 1
}
foreach ($copy in @(@(0x1208,0x1D83,0x1F0D), @(0x2008,0x2B83,0x2D0D))) {
    $before = 0; $after = 0
    for ($i = $copy[0]; $i -lt $copy[1]; $i++) {
        $before += $original[$i]
        $after += $candidate[$i]
    }
    $stored = $original[$copy[2]] + 256 * $original[($copy[2] + 1)]
    if (($before -band 65535) -ne $stored) { throw 'original checksum invalid' }
    $candidate[$copy[2]] = $after -band 255
    $candidate[($copy[2] + 1)] = ($after -shr 8) -band 255
}
for ($i = 0; $i -lt $original.Length; $i++) {
    if ($original[$i] -ne $candidate[$i]) {
        '{0:X4}: {1:X2}->{2:X2}' -f $i,$original[$i],$candidate[$i]
    }
}
$hasher = [Security.Cryptography.SHA256]::Create()
[BitConverter]::ToString($hasher.ComputeHash($candidate)).Replace('-','').ToLower()
$hasher.Dispose()
```

The production builder must additionally enforce the input SHA256 above and
independently compare every output byte with the allowlist. This snippet
reproduces the calculation; it is not the complete builder or verifier.

Do not implement a four-byte direct map warp as a shortcut. CONTINUE uses
`LoadMapAttributes_SkipObjects` and `HandleContinueMap`
(`src/data/maps/setup_scripts.asm:188-210`); it does not run the connection's
object reload (`:88-107`). The fixture corruption investigation already
warns about bare position pokes (`LIVE_RESULTS.md:55-61`). A faster direct
city fixture needs its own complete object/cache derivation or disclosed
native setup-and-save builder; it is outside this minimum-edit recipe.

## 3. Native button route and calibration

Boot the private staged save, A pulses through title and CONTINUE, then idle
until normal Route 29 overworld at (48,12). D3 used 20 A pulses and 300 idle
frames (`LIVE_RESULTS.md:689-691`); this is a calibration seed, not a promise
that the new run has identical timing. No savestate, WRAM write, forced battle,
script invocation, or register change is part of the measurement.

Candidate walking route below uses only direction buttons. Counts are **tile
steps**, not frames. All endpoints except the last are Route 29 coordinates.
Release buttons between calibrated holds. At the final segment, four Left
steps reach Route 29 (0,7), the fifth crosses to Cherrygrove (39,7), and six
more reach (33,7); stop walking when the rival script takes control.

| Buttons | Steps | Endpoint | SYNTH calibration endpoint frame (2026-10-08) |
|---|---:|---|---:|
| Left | 4 | (44,12) | 510 |
| Down | 2 | (44,14) | 597 |
| Left | 6 | (38,14) | 844 |
| Down | 2 | (38,16) | 1965 |
| Left | 7 | (31,16) | 2252 |
| Up | 6 | (31,10) | 2499 |
| Right | 5 | (36,10) | 2706 |
| Up | 3 | (36,7) | 2833 |
| Left | 13 | (23,7) | 4403 |
| Up | 1 | (23,6) | 4450 |
| Left | 2 | (21,6) | 4537 |
| Up | 2 | (21,4) | 4624 |
| Left | 5 | (16,4) | 5867 |
| Down | 2 | (16,6) | 5954 |
| Left | 5 | (11,6) | 7196 |
| Down | 4 | (11,10) | 7363 |
| Left | 7 | (4,10) | 8683 |
| Up | 3 | (4,7) | 8810 |
| Left | 11 | Cherrygrove (33,7), rival trigger | 9258 |

Source geometry calculation: read the 270-byte `src/maps/Route29.ablk` and
220-byte `src/maps/CherrygroveCity.ablk`, with widths 30 and 20 blocks
(`src/constants/map_constants.asm:543,583`). At tile (x,y), block index is
`floor(y/2)*width+floor(x/2)`, quadrant `2*(y%2)+(x%2)`; the four collision
entries are in `src/data/tilesets/johto_traditional_collision.asm`, line
`block_id+1`. This agrees with `src/home/map.asm:1398-1419`. Both map headers
use JOHTO_TRADITIONAL (`src/data/maps/maps.asm:573,613`). A read-only PowerShell
grid search produced these 90 steps, restricting tiles to FLOOR/TALL_GRASS/
LONG_GRASS and excluding listed objects and the teacher/schoolboy movement
areas (`src/maps/Route29.asm:20-29`). A shorter terrain-only path crosses the
cut tree at (21,11); do not use it. Binary block offsets, rather than invented
line numbers, are the appropriate evidence for `.ablk` files.

**UNVERIFIED LIVE:** collision derivation is not a successful traversal.
Wild encounters interrupt this route. Use native battle-menu inputs to Run
(from the default Fight selection: Right, Down, A), confirm the overworld
return, and resume from the observed tile; actual cursor state/escape success
must be observed. Alternatively fight with the existing Tackle party using
native A selections. Do not count a held direction's elapsed frames as steps
during a battle. Use read-only position/battle-mode observations to calibrate
one bounded replay, then encode the successful replay in the probe's existing
`steps: [{frames,buttons}]` format (`rival_gate_probe.py:125-146`). After the
rival appears, release directions and use A/release pulses through challenge
text until native trainer send-out. Idle through gate/next/last recording;
winning the battle is not required for P0. An exact fixed-frame JSON route is
OPEN pending this calibration; do not advertise the table as a tested script.

## 4. Recorder, acceptance and red controls

`tools/polished_live/rival_gate_probe.lua:50-88` hooks bank 0F addresses
47DD (gate), 47E0 (next), 480D (last consumption). It records order/frame,
PC/SP, hROMBank at FF87, hook address, matched/qualified flags, battle mode,
trainer class/id, selected enemy/party indices, enemy party count, and six
gate/hook bytes. ROM bytes are read through the pinned ROM bank, not whichever
bank happens to occupy the bus. Wrong-bank rows are sampled up to 16 per site
with full counters; zero write/register-change counters and a completed final
are required (`:20-42,54-80,104-111`).

Current oracle rules (`rival_gate_probe.py:39-122`):

* At least one qualified gate, `PC==0x47DD`, `hROMBank==0x0F`, `matched=true`,
  `qualified=true`, `mode==2`, count 1..6 and
  `0<=cur_ot_mon==cur_party_mon<count`.
* Six decoded site bytes beginning `21 8B D2`; next/last callback PCs must
  match their own addresses when present. Release bytes read directly here at
  flat `0x3C7DD` are **`21 8B D2 FA 0C D1`**. Existing oracle pins only the first
  three, not all six; the run receipt must compare all six against its staged
  overlay and retain the ROM SHA1 (`:170-221`).
* Complete uncensored trace, consistent hook totals, no mutation, driver error,
  overflow, deadline, or incomplete recording (`:49-76,224-231`).
* Verdict priority is `PC_IS_NEXT_INSTRUCTION`, `PC_OTHER`, `NO_GATE_HIT`, then
  `FAIL` for other reasons, otherwise `PASS`. A zero-hit run is OPEN, never a
  positive PASS. Inspect every reason even when the headline is `NO_GATE_HIT`.

**Additional acceptance for this rival card:** class must be in
`{1B,1C,1D,1E,1F}` (RIVAL0/1/2, LYRA1/2;
`src/constants/trainer_constants.asm:95-127`); for this exact fixture require
**class `1B`, trainer ID `03`, enemy party count 2**. Trainer IDs are not
class constants and must not be tested against the five-class set. Require
an ordered gate -> next -> last witness for the initial enemy send-out and
matching trainer identity. Existing `evaluate` records but does not validate
class/id, and does not require next/last to exist. Its unit-test example even
uses class 9 (`tests/unit/test_polished_rival_gate_probe.py:25`). Therefore
the current generic probe PASS alone is insufficient for this card.

Red controls:

1. Run the original Route 29 fixture into an **observed wild battle** using
   native buttons and the same read-only hooks. Require no qualified gate;
   generic oracle verdict should be `NO_GATE_HIT` without other recording
   failures. Idle zero-hit is not a wild negative control. Establish wild
   mode independently; the current trace does not emit a general battle-mode
   timeline when no hooks fire. Source selection is the enemy-party path
   (`EXPLODE_RIVAL.md:449-480`); any qualified wild hit blocks acceptance.
2. Wrong-bank callbacks at CPU address 47DD must remain `matched=false`,
   `qualified=false`, counted but excluded. Offline replay with only such
   callbacks must return `NO_GATE_HIT`; never change the CPU bank to force a
   live control. Malformed bank/matched accounting must fail validation.
3. Negative oracle records: class outside the set, wrong ID for this fixture,
   absent next/last, wrong six-byte site, next-instruction PC, changed indices,
   overflow, missing final, mutation and late completion must not qualify.

P0 PASS proves callback-observed PC semantics at a native trainer send-out in
this staged encounter on the pinned emulator/ROM and the retained trace's
conditions. It proves neither rival-swap application nor post-copy consumption,
network reply timing, all five classes, six-mon parties, repeat-send-out safety,
rollback, 1x qualification, naturally played story progression, or release
readiness. `EXPLODE_RIVAL.md:604-607` keeps the client hook and consumed-write
proof as later P1/P4 work. The recorder runs at 400%
(`rival_gate_probe.lua:89`), so report that speed explicitly.


### Live card g2p-rival-live, 2026-10-08 (SYNTH; strict gate result FAIL)

Source cut `7f56228b5`; integrated UPS 3727 bytes; overlay SHA1
`877a477a7dfc70b775ca3f46461d67abebe07083`. No ROM rebuild, client/server,
WRAM setup, or rival swap was performed. Requested speed was **300%**, not
1x qualification (the earlier 400% description above is superseded for this card).
EmuHawk binary SHA256 `f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd`.

The existing `tools/polished_live/derive_rival_save.py` produced the section 2
hash exactly. Independent input/output comparison: 32790 bytes each; differences
only `1782:00->01`, `1F0D:E4->E5`, `2582:00->01`, `2D0D:E4->E5`; all 22 RTC
footer bytes preserved. This SYNTH staging skips story progression. Native
CONTINUE accepted the derivative and normal buttons traversed the source-derived
90-tile route. Section 3's added endpoint-frame column is the measured second
calibration; input frames during five wild battles are excluded from tile counts.
The driver used native A pulses to defeat those wild mons, not injected battle state.

All raw evidence is under `F:/slink-work/lanes/pol-rival-live/out/`:

| Receipt subdirectory | Evidence / result |
|---|---|
| `synth-xq6b4nrp/probe` | First calibration, PID 15176: retained FAIL. Reached city (33,7), but an old wild `last` callback prematurely satisfied the calibration stop. No rival completion claim. |
| `synth-i_xfq96x/probe` | Corrected fresh-witness calibration, PID 8372: recording completed, 10145 elapsed frames, no guest writes/CPU changes. Rival gate/next/last all frame **10085**, bank 0F, PCs **47DD/47E0/480D**, mode 2, class **1B**, ID **03**, count **2**, indices **0/0**, site `218bd2fa0cd1`. **Strict whole-run FAIL**: five earlier wild gate hits (frames 994,3030,4861,6191,7760). Route calibration succeeded; this is not a P0 PASS. |
| `synth-1agu9bbq/probe` | Independent original-fixture wild control, PID 33740: recording completed, 1379 elapsed frames, zero mutations. **FAIL**: qualified gate/next/last frame **780**, bank 0F, exact callback PCs, mode **1**, class/ID **0/0**, count **1**, indices **0/0**, **hBattleTurn=1**, same site bytes. |

Each directory contains `trace.json`, `result.txt`, `route.json` (exact timed
native buttons from boot), `calibration.json` (read-only position milestones),
`input.json`, `config.ini`, and symbols. `disclosure.json` binds source SHA256
`75c7a5dc30126f746567202cfb39fe583dfa04eb226063560541f6cbd29f36b8` and derivative
`030c62ff898050d81d80dea19677e8520e2f707dae0c35f873d87e79cf7ac1ae`.
`evidence-manifest.json` hashes the raw outputs. Corrected calibration trace SHA256:
`1ce96295ed630aa7fd58a7ba56e47a5a30bf9f6cb1c79ffe157abb18e62eb41c`;
its timed route SHA256 `c0dd9bced4e1a47843b6c2561639cd456487f73516d5d4225f150588d6c3ee7b`.
Wild trace SHA256 `1e53789331507f5e436d5e3e11504a7805ce4b4f0581a31c249f1ee34c67a5b9`.
The wild recorder additionally captured side/register diagnostics; calibration2
predates those added fields. Raw receipts were not rewritten/rejudged into PASS.
No fixed-route replay was run: the successful timed route is a calibration receipt,
not proof of deterministic reuse across RTC/RNG states.

**Source correction to the earlier wild-control premise:** the site is in
`SendInUserPkmn+149` (`data/polished/polished_slink.sym:10490-10497`). Although
`src/engine/battle/core.asm:37-45` skips the trainer send-out at that location for
wild battles and `:80-85` also calls the routine for player send-out, the separate
**wild enemy initialization** at `:8079-8086` explicitly sets WILD_BATTLE, calls
LoadEnemyWildmon, SetEnemyTurn, and SendInUserPkmn. `:1240-1245` selects the enemy
party pointer when hBattleTurn is nonzero. Thus the measured wild callback is
consistent with native source; it is not evidence that the probe manufactured a
trainer battle, nor merely a player-side callback. The claim that this raw site
has no qualified wild hits is FALSE on this cut. Enemy-side alone cannot fix it.

**Proposed next card, NOT implemented:** at the recorder callback's bank/PC
qualification in `tools/polished_live/rival_gate_probe.lua`, retain raw callbacks
but define a separate rival-operation predicate requiring hBattleTurn==1,
wBattleMode==2, rival class in 1B..1F, and the expected trainer ID/party identity
(1B/03/count2 for this fixture), with matching ordered next/last observations.
Add wild-enemy and player-side red tests before changing qualification; do not
reinterpret the current FAIL receipts as PASS. HL/F raw diagnostics have no
acceptance role; combined-register API validity was not established by this card.

Verification: `python -m pytest tests/unit/test_polished_derive_rival_save.py
 tests/unit/test_polished_rival_gate_probe.py -q --basetemp F:/slink-work/tmp/rival-live-final`
from the isolated worktree: **350 passed**. Ruff clean for the changed Python
runner/test. New executable Lua calibration tests cover observed endpoints,
1800-frame stall, total bound, and the stale-wild-witness mutant (red control).
Both original test files passed before calibration changes (**345 passed**).
All three owned emulator processes exited; no other PID was killed.
Open: revised predicate/oracle independent review, fixed-route replay, actual
swap application/consumption, all rival classes and physical 1x qualification.
No claim is made for the unrelated trade/faint test files, which were not run.

## 5. Risks and implementation prerequisites

* **Disclosure blocker:** CLI currently accepts only `--setup played`
  (`rival_gate_probe.py:149-152`), uses a `played-` lane prefix (`:238`), and
  prints played in headers/results (`:253,270`); Lua header also says PLAYED
  (`rival_gate_probe.lua:2`). Add explicit SYNTH fixture provenance before
  using it for this measurement. Do not relabel the derived fixture played
  merely because subsequent buttons and battle code are native.
* Native acceptance of the four-byte derivative, fixed-frame route, wild
  interruptions, encounter class/id, and gate witness are all UNVERIFIED.
  Builder/model checks close none of these live items.
* F3 dropped the 22-byte RTC footer for its own exact-32768-byte probe
  (`LIVE_RESULTS.md:704-706`). That is not part of this recipe. Preserve all
  32790 bytes except the four declared differences; do not reuse F3's
  truncated lane copy as the source.
* D3/F3 used older overlay `aecedbb2` (`LIVE_RESULTS.md:691,706`). Re-pin the
  actual current overlay/provenance and emulator in every receipt. Reusing
  their route knowledge is not reusing their qualification.
* The source party table was read, but exact native generated enemy struct,
  current overlay's full build equivalence to every source file, and complete
  emulator timing were not verified. Refuse drift rather than adapting offsets
  silently. Stop and retain the failed trace if the route does not land.

## 6. Ordered exclusive-file cards

Paths below are proposals for the coordinator's leases, not edits made here.
Each card has at most three exclusive files. Runtime scratch files require
their own bounded lane subcards; do not lease an unrestricted directory.

| Order / owner | Exclusive files | Deliverable / gate |
|---|---|---|
| B1 builder | `tools/polished_live/derive_rival_save.py`; `tests/unit/test_polished_derive_rival_save.py` | Pure scene-only derivation, pinned-input refusal, independently checked four-byte allowlist, both sums, full footer preservation, deterministic expected hash. No emulator. |
| B2 builder | `tools/polished_live/rival_gate_probe.py`; `tools/polished_live/rival_gate_probe.lua`; `tests/unit/test_polished_rival_gate_probe.py` | Explicit SYNTH setup mode/disclosure/hash, rival-card oracle distinct from generic callback probe, full six-byte comparison, initial ordered witness, read-only wild-mode evidence. Preserve mutation guards and wrong-bank accounting; all negative cases above. |
| B3 builder, after B1/B2 review | `<private lane>/rival_scene.SaveRAM`; `<private lane>/rival_scene.disclosure.json`; `<private lane>/rival_scene.verify.json` | Build and independently verify input/output hashes, exact byte diff and both checksum sums. SYNTH declaration includes builder/source pins; original fixture remains untouched. Coordinator supplies absolute private-lane paths. |
| L1 live worker, after B3 | `tools/polished_live/routes/rival_staged_route.json`; `<private lane>/calibration.trace.json`; `<private lane>/calibration.result.txt` | Bounded read-only calibration using native buttons; retain positions/modes and interruptions; freeze replay and hash. If it stalls, report the tile/blocking state instead of broadening setup writes. |
| L2 live worker, after L1 | `<fresh positive run>/input.json`; `<fresh positive run>/trace.json`; `<fresh positive run>/result.txt` | Clean boot of the immutable staged fixture; complete trainer witness and SYNTH receipt, only owned PID cleanup. |
| L3 live worker, after L2 | `<fresh wild control>/input.json`; `<fresh wild control>/trace.json`; `<fresh wild control>/result.txt` | Original fixture, observed native wild battle, no qualified gate, complete recording. |
| L4 coordinator | `docs/polished/LIVE_RESULTS.md`; `docs/polished/RIVAL_STAGING.md` | Reconcile positive/control/raw evidence; record narrow P0 verdict or OPEN, hashes, speed, remaining P1/P4 work. Commit authority remains with coordinator. |

The runner also stages ROM/config/private SaveRAM and may emit screenshots.
Before L1-L3, enumerate those actual output paths from the runner and allocate
additional preparation/evidence subcards of at most three files each; the
three named receipt files are not permission to overwrite other workers'
runtime artifacts. No live run is performed by this documentation card.
