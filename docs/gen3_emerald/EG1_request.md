# EG0 + EG1 request: Emerald pins and SOURCE facts (SIGNED 2026-09-25 by owner delegation)

Branch `claude/gen3-emerald` (worktree `.claude/worktrees/gen3-emerald`), base Gen 3 `5f050857`
(frozen cut `a2985d5a` + the item-table fix). Local only: not pushed, not merged. Plan:
`docs/gen3_emerald/PLAN.md`. Ledger: `docs/gen3_emerald/REQUIREMENTS.md`.

## 1 What EG0 + EG1 sign

**EG0 (pins).** You sign:
- the Emerald ROM;
- the pret commit;
- the published `.sym` (the table below).

**EG1 (packs as pinned facts only).** You sign that the `gen3_emerald` pack's data is generated from pinned sources and cross-checked by independent controls:
- profile and engine sites;
- write checkpoint;
- area map and statics;
- codec save layout;
- title symbols;
- move/item facts.

EG1 also signs that the six battery fixtures qualify and boot on the real cartridge.

**EG1 does NOT sign** (all later gates):
- site *semantics* or live firing (EG2);
- the checkpoint as PHYSICAL (EG2);
- admission, routing or server changes (EG3/EG4);
- any Soul Link behaviour on Emerald (EG4).

Emerald stays refused by name (ruling 24) until EG4.

## 1a Status at the milestone

- **Commits** (`git log 5f050857..HEAD`): 17 commits, `50c1e88e`…`8ee5869f` (the request doc is the next commit).

  Most of the volume is the pinned `.sym` (73k lines) and generated data.
- **Full unit suite** at `bd62bf93`: 6757 passed, 793 skipped, 1 failed, 5 errors. All 6 are environment-only:
  - the RR harness test (the main checkout's `slink_RR.gba` is not the pinned `ea5352f8…` build);
  - the Gen 1 trade-patch tests (no `.cache/pret/pokered` in this worktree; same known environment issue as the Gen 3 resume note).

  No Emerald or Gen 3 test fails.
- **FR/LG/RR byte identity** after every shared-tool edit:
  - profile generator `--check`: current;
  - engine-signals generator: FR 21 / LG 21 / RR 19 / RR-companion 19 pinned, unchanged;
  - write-checkpoint generator: `gen3_frlg` and `gen3_rr` current;
  - area map: FRLG output identical.

## 2 Per-item status (REQUIREMENTS.md rows)

| Row | Status | Evidence |
|---|---|---|
| EF-1 `.sym` | S ✓ (changed approach, see §6 decision 2) | pret's published `pokeemerald.sym` from the symbols branch `dba968c6` (source `c65e93f2`), sha256 `a0a13478…`; `data/gen3/pret/pokeemerald_provenance.json`; every consumed symbol re-proven by ROM anchors |
| EF-2 FRLG/RR identity | S ✓ | §1a |
| EF-3 profile | S ✓ M ✓ | `5acd99b1`+`bd62bf93`: 25 ram / 14 rom / 44 derived, every field `_src`-cited; HEADER control (GF header at 0x100); `gBattleTypeFlags` 457-ref literal-pool control; the old stub's 24 values all agree (stub correct, only incomplete) |
| EF-4 sites | S ✓ | 21/21 kinds PINNED on BPEE, 0 OPEN; capture offsets re-derived where FR's do not transfer; a 21-entry capstone capture-instruction table with ±2 mutation checks |
| EF-5 checkpoint | S ✓ (census PENDING E2 at signing; captured in E2, `docs/gen3_emerald/probes/census_emerald_overworld_2026-09-25.txt`) | `1401df8d`+`5d0a4bd7`: player-controller span derived from the `.sym` (123 functions, `.gcc2_compiled.` bounds, 13 gaps of 2), save-dialog renames, FR-only league task excluded, **`Task_MuddySlope` allowed** (§6 decision 4), 47-name forbidden inventory, SetUpFieldTasks floor guard |
| EF-6 save layout | S ✓ M ✓ | `60d207a9`+`f7e2d52f`: SB2 0xF2C / SB1 0x3D88 / party +0x234/+0x238, all 14 section triples pinned ROM-free, GF-header control fails on a wrong ROM, calc lane's `decode_party_mon` contract pinned |
| EF-7 areas | S ✓ M ✓ | `81bb74e3`+`9538d3a4`: 116 wild maps → 67 areas per the §0 defaults; never a Kanto name; MAPSEC collision guard; areas.lua == area_map.json |
| EF-8 statics | S ✓ | 21 entries, each species/battle-or-give line checked against its pret citation. The Fortree/Lilycove/Sootopolis Kecleon only cry or flee (recorded limit); the two Route 119 Devon Scope Kecleon are added |
| EF-9 moves/items | S ✓ | `f3f56f54`: 355 moves identical **except MOVE_NATURE_POWER accuracy 0 (FRLG) vs 95 (Emerald)**, pinned as a known difference, so Emerald needs a one-entry move overlay (E3); items 0-374 identical, Emerald-only 375/376 |
| EF-10 fixtures | M ✓ P ✓ (SYNTH, disclosed) | `20aba5a5`+`8ee5869f`: six fixtures, each with 5 SYNTH Poké Balls, (town Oldale / battle Route 102 grass / trainer before Youngster Calvin, each with a `_b` side); `qualify` 6/6; **PHYSICAL boot-check 6/6** (cold boot → CONTINUE → re-save → reload); receipts `docs/gen3_emerald/probes/fixtures_2026-09-25{,b}.txt`; seed and fixture sha256s pinned in the tests |
| E2-SYMS title syms | S ✓ | `60d207a9`: 41 emerald addresses, 7 explicit nils, 3 renames, `sMenu` occurrence 2 |

## 3 Defects found and fixed during E1

- **The plan's rev 1 claimed the old Emerald stub had a wrong `BATTLE_TYPE_ADDR`.** A worker had mis-converted the number and I didn't trace it to the file. The stub is correct (15/15 RAM addresses match the `.sym`). Corrected in `29671d2a`.
- **Three statics Kecleon were not encounters** (review cx-cc142a2d, verified in pret). Fixed in `9538d3a4`.
- **The area test rewrote the FRLG data files in place.** Fixed in `cf05e86b`, mutation-checked.
- **The FR fixture glob qualified Emerald saves with the FR layout.** Fixed in `20aba5a5`. My own follow-up briefly broke it, and `50c0eb51` restored it.
- **The FR/LG/RR generator `--check` needed the Emerald ROM.** Decoupled in `bd62bf93`.
- **Emerald fixtures had an empty ball pocket**, which would block every faint/party-sync scenario. Fixed in `8ee5869f`.

## 4 Independent reviews

Headless OMP, one per commit. Every finding was checked by the coordinator before acceptance, and several OMP claims were rejected:

| Review | Result |
|---|---|
| cx-cc142a2d (areas) | 8 accepted |
| cx-b9d33a79 (profile/sites) | 7 accepted, 2 rejected: the `map_load` "off by one" was OMP misreading the bytes (capstone: `fn+0x14` is the `bl`); the badge-byte arithmetic was correct as written |
| cx-73b96095 (codec/syms) | 12 accepted |
| cx-19463bba (checkpoint) | 6 accepted |
| cx-ba59a7fa (fixtures) | 7 accepted; the ball pocket was fixed in `8ee5869f` |
| cx-8f7dfa4f (plan citations) | its stub value was itself wrong |
| cx-84f064cb (calc sets) | its "tree is not faithful Emerald" claim was false: Roxanne/Wallace/Brandon are correct Emerald |

OMP cannot execute code here. The coordinator ran every OMP-written change before committing it.

## 5 Limits carried forward (not signed by EG1)

**Carried to E2:**
- **Badges:** `SB1_BADGE_BYTE_OFFSET` is null. Emerald's badge flags 0x867–0x86E straddle a byte, so `reads.lua` and PYDEC need a flag-id read.
- **Day rollover:** `Task_RunTimeBasedEvents` writes party Pokérus and save-block fields on a real-time-clock day rollover. It is synchronous within one frame; whether that frame needs a guard is an E2 decision.
- **frame_control:** Emerald's `CallCallbacks` has no help or save-failed gate and runs only when `!HandleLinkConnection()`. This is a client precondition.
- **Union Room:** the Emerald callee audit of the Union Room background tasks is †UNVERIFIED; the Oldale Center is its E2 positive.

**Carried to E3:**
- **Sound ids:** `SE_SONG_HEADERS` ids differ by title, so the server needs a per-title sound map.
- **Move overlay:** Nature Power (one entry).
- **Codec API:** refusals and a comment (review cx-73b96095 M5-M8, M11).
- **Checkpoint generator:** portability F6-F9.
- **Fixture minors:** B2, B5, B6, B9–B12; `boot-check --rom` has no checkout-root fallback; Emerald `_launch` exports the FR/LG checkpoint path.

**Not a gate item:**
- **Workstation state, not a code defect:** the main checkout's RR companion ROM hash differs from the pin, and this worktree has no pokered/pret cache for Gen 1.

## 6 Owner decisions

All five ACCEPTED as recommended: owner 2026-09-25: "Do what you think is best. Lets go to the next major checkpoint" (delegated; coordinator took the recommended option on each).


1. **EG0 pins:**
   - ROM `Pokemon - Emerald Version (USA, Europe).gba`, sha1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7` (= pret `rom.sha1`);
   - pret/pokeemerald `c65e93f20a5275ab03b07d6f6411096a82a60ffd`;
   - BizHawk 2.11.1 (unchanged Gen 3 pins).
2. **Accept pret's published `.sym` as the Emerald symbol source** instead of our own CI build. Our own build would need a push (owner authority) and a Linux toolchain, since the local Windows build lacks libpng. The only `.map` consumer is replaced by a `.sym`-derived span that is independently bounded and tested.
3. **Accept the disclosed O-33 SYNTH fixture setup.** The committed files are the game's own re-save. The README lists every field that stays synthetic (dex, bag/balls, flags, vars, money, trainer).
4. **Accept `Task_MuddySlope` on the Emerald overworld allow-list.** `SetUpFieldTasks` creates it on every field load, it only reads the player location, and a guard test pins this.
5. **Sign EG1.**

## 7 How to verify

```
git -C .claude/worktrees/gen3-emerald log --oneline 5f050857..HEAD
python -m pytest tests/unit -q -k "emerald or gen3_profile or engine_sites or fixture or codec or title_syms or checkpoint"
python tools/gen_gen3_profile.py --check
python tools/gen3_fixtures.py qualify --title emerald tests/fixtures/gen3/emerald_*.sav
python tools/gen3_fixtures.py boot-check --title emerald tests/fixtures/gen3/emerald_town.sav
```
