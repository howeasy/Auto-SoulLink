# XG1 request: expansion reference build facts (draft, 2026-09-27)

- **Branch:** `claude/gen3-exp-x23` (worktree `C:/slink-wt/g3-exp`), base integration `4fa041bf`.
  Local only: not pushed or merged.
- **Plan:** `docs/gen3_emerald/PLAN.md` X1 row ("Build + facts" → **XG1** facts signed).
  **Ledger:** `docs/gen3_emerald/REQUIREMENTS.md` rows XF-2, XF-3.
- **Frozen cut:** ``7c550558` (code); receipts were taken at the cuts each receipt's IDENTITY line names`. The X1 facts themselves were generated on branch `claude/gen3-emerald-x1`
  (merged into the lane before `4fa041bf`); this draft re-runs their falsifiers on this cut with every
  input present and adds the X2/X3 facts the live runs needed.

## 1 What XG1 signs

On the pinned reference build (pokeemerald-expansion `expansion/1.17.0` = `e8bd1cd7`, ROM sha1
`28877d733492299599f2b8fff50493109d72653c`, XG0-signed), you sign that these are the build's own
facts, generated and falsified, never hand-typed:

- **Compiler facts** (`data/games/gen3_exp/28877d73/facts.json`, `layout.json`): struct sizes, field
  offsets, bitfield masks and constants from the `offsetof` probe (`tools/expansion_offsets.c`),
  compiled with the ROM's own Makefile pipeline and pinned compiler, cross-checked against the
  build's `.sym`/`.elf`, the GF header and the RHH header.
- **Data pack** (`data.json`): species (count == RHH `numSpecies` 1573), names, types, abilities,
  national dex, evolution families, moves, items, abilities, extracted through the GF/RHH table
  pointers; the same extractor on vanilla Emerald reproduces pret (CONTROL).
- **Pack files** generated from those facts and the build symbols: `profile.json` (every address
  resolves in the build's `.sym`), `engine_signals.json` (18 sites pinned: bytes at their ROM
  offsets, unique, capture offsets on instruction boundaries), `write_checkpoint.json` (anchors,
  predicates, task census, battle clauses), `area_map.json` + `gen3_exp_{areas,locations}.lua`.
- **Harness facts** (new at X3, `harness_facts.json`): the second compiler probe
  `tools/expansion_harness_offsets.c` (BagPosition/BagMenu, the SaveBlock1/2 fields the fixture
  seed writes, HealLocation, the PC main-menu enum verbatim, OW_WHITEOUT_CUTSCENE) and the whiteout
  respawn table derived from `src/data/heal_locations.json`, checked against the ROM's own arrays.

**XG1 does NOT sign:** runtime admission or routing (the pack stays unadmitted and unrouted); any
write-safety claim (XG3); the X2 decoders (XG2); the three OPEN engine sites (§5); gift/static
census; wild encounter tables.

## 1a Status

| Commit | What |
|---|---|
| (x1 lane, merged) | compiler facts, data pack, pack generation, extractor CONTROL |
| `be2c2fa7` | profile carries the reads.lua/codec layout keys (from facts bitfields) |
| `16127a9d`, `957d5ac5` | write_checkpoint cpu block from live census (XG3 evidence, §2 note) |
| `1df28d00`, `2c86c679`, `c77a790f` | harness_facts.json: compiler probe + whiteout respawn table |
| `53210955` | profile gains BATTLE_MON_HP_OFF (facts BattlePokemon.hp) |

## 2 Per-item status

| id | Claim | SOURCE | MODEL | PHYSICAL | Evidence |
|---|---|---|---|---|---|
| XF-1 | reproducible build | ✓ (XG0) | — | — | `docs/gen3_emerald/XG0_request.md` |
| XF-2 | struct offsets from the offsetof probe, consistent with `.map/.sym/.elf` sizes | ✓ | ✓ | ◐ | `tests/unit/test_gen_expansion_facts.py` (reference object, ROM/sym/elf cross-checks), `probes/x1_probe_2026-09-26.txt`; used live by every X3 run |
| XF-3 | data pack: species == RHH numSpecies; names/types/abilities/natDex/families; moves; items; CONTROL on vanilla Emerald | ✓ | ✓ | — | `tests/unit/test_extract_expansion_data.py` (vanilla CONTROL ran: `SLINK_EMERALD_ROM` + pret checkout) |
| XF-4 | profile addresses resolve in the build `.sym`; sites pinned; checkpoint anchors match the ROM | ✓ | ✓ | ✓ | `tests/unit/test_gen3_exp_pack.py`; live: `probes/hooks_exp_2026-09-27.txt` (probe a/b/c/d/e/g PASS) |
| XF-5 | harness facts (compiler) + whiteout respawn table (source, == ROM arrays) | ✓ | ✓ | ✓ | `tests/unit/test_gen3_fixture_exp.py`; live: whiteout landed on the table's tile (`probes/duo_x3_whiteout_*`) |

MODEL run on this cut, every input present (`SLINK_EXPANSION_SRC`, the reference artifacts, the
x1 probe object, the owner's Emerald ROM and pret checkout):
`pytest tests/unit/test_gen_expansion_facts.py test_extract_expansion_data.py test_build_expansion.py
test_gen3_exp_pack.py test_extract_expansion_config.py` → **134 passed, 6 skipped**. The skips: two
XG0 build-output directories (`linux1`/`linux2`, signed at XG0) and four XC0 config tests that read a
checkout at a fixed other-worktree path (`em-x1/.cache/expansion-src`, not touched).

## 3 Defects found and fixed (facts)

- The profile carried `NICKNAME11_FIELD`/`NICKNAME12_FIELD` in the compiler's shape, which no
  decoder read; reads.lua and the codec never got the masks from the pack (`be2c2fa7`, red first).
- Live X3 runs found five facts the generated packs did not yet carry, each now compiler- or
  source-derived and falsified by test: the PC main-menu option order (`OW_PC_MOVE_ORDER`: MOVE 0 /
  DEPOSIT 1 / WITHDRAW 2, `2c86c679`), the whiteout respawn map (`OW_WHITEOUT_CUTSCENE` ≥ GEN_4,
  `c77a790f`), the save site's save-type register (R4, not R5, `27bd720f`), the BattlePokemon
  geometry in the harness and reads.lua (140 bytes, hp +42, `d7a9a1a3`, `53210955`), and the two
  CPU idles (`16127a9d`, `957d5ac5`).

## 4 MODEL evidence

- Full unit suite on this cut: `12427 passed, 4366 skipped, exit 0 (`pytest tests/unit`, at `7c550558`, 10:41; plus a B007-only test lint fix committed after)`.
- `python tools/gen_gen3_profile.py --check` and `--expansion 28877d73 --check`: current.
  `gen_gen3_write_checkpoint.py --check` (FR/LG unchanged) and `--expansion 28877d73 --check`,
  `gen_gen3_engine_signals.py --expansion 28877d73 --check`, `gen_gen3_title_syms_exp.py --check`,
  `gen_expansion_harness_facts.py --check`: current. `git diff 4fa041bf -- data/games/gen3_frlg
  data/games/gen3_rr data/games/gen3_emerald` is empty.

## 5 Limits carried forward (not signed by XG1)

- **Engine sites OPEN:** `pc_deposit`, `pc_release_begin`, `pc_release` — `TryStorePartyMonInBox`
  and `ReleaseMon` are inlined in this build (facts `unresolved_engine_sites`). Box sync still
  passed live (`probes/duo_x3_boxsync_*`: the deposit/withdraw reported through the remaining sites
  and the party diff), but no site-level receipt exists for those three kinds. `hatch` is not pinned.
- **Gift/static census:** `write_checkpoint.json gift_areas` is empty (the client logs "every area
  treated as a gift area", which only affects the HUD banner/no_catch hint); the server's gift rule is
  the adapter's `gift_` prefix. No expansion statics/fixed-gift policy is extracted.
- **Encounter tables:** `encounter_table()` returns None for the reference build (recorded limit,
  PLAN X2). Trainer panels exist since XC4.
- **Battle hand-off:** `write_checkpoint.json battle.commit_hold` stays OPEN (struct Volatiles and the
  new controller ABI); XG3.
- XC0 config falsifiers were not re-run here (fixed other-worktree path).

## 6 Owner decisions

1. Sign XG1 as the facts of the reference build listed in §1, with the §5 limits.
2. Accept the second compiler probe (`tools/expansion_harness_offsets.c` → `harness_facts.json`) as
   the source of harness-only facts (same pipeline, same compiler, run on `hgbox`), rather than
   growing `facts.json` (which would re-hash every downstream pack).

## 7 How to verify this draft

```sh
source C:/slink-wt/g3-env.sh
export SLINK_EMERALD_ROM="E:/Google Drive/SLink/Pokemon - Emerald Version (USA, Europe).gba"
export SLINK_POKEEMERALD="E:/Google Drive/SLink/.cache/pret/pokeemerald"
python tools/build_expansion.py --check          # artifacts == receipt == lock
python -m pytest -q tests/unit/test_gen_expansion_facts.py tests/unit/test_extract_expansion_data.py \
  tests/unit/test_gen3_exp_pack.py tests/unit/test_gen3_fixture_exp.py
python tools/gen_gen3_profile.py --check && python tools/gen_gen3_profile.py --expansion 28877d73 --check
python tools/gen_expansion_harness_facts.py --check
```
(`.cache/expansion-src` → `SLINK_EXPANSION_SRC` and `.cache/x1-probe/probe.o` from `hgbox` make the
source/object-bound tests run instead of skipping.)

## 8 Pending (owner wrap-up 2026-09-27; no new live runs started)

- Re-run faint_cmd_gen3 and boxsync_gen3 at the final cut (their PASS receipts predate the CPU-clause
  and reads-geometry commits `957d5ac5`/`53210955`); then one frozen-cut set of all four rows.
- Coordinator's headless reviews of this lane; XG2 draft: `docs/gen3_emerald/XG2_request_draft.md`.
- XG3: P+H for struct Volatiles (hold fallback today), observer receipts per site kind, the three OPEN
  PC sites, gift/static census, `gen3_final_cut.py --title exp`.
