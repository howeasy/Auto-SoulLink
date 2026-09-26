# EG3 request: E3, the Emerald shared server/client diff (2026-09-26)

**SIGNED 2026-09-26** by the owner in chat ("Signed. Lets go."): all five decisions in §6 accepted.

- **Branch:** `claude/gen3-emerald`, local only: not pushed, not on master. It contains master
  `1d02702f` (Gen 3 landed).
- **Cut for this request:** `ef99d9b8`, plus the review follow-ups in `7cf4a3c9`: the rebuild refusal is logged (state.py, guard CLEAN), derive-b uses the codec title normaliser, and a test that every pack maps every wire SE id.
- **Plan:** `docs/gen3_emerald/PLAN.md` (E3 row). **Ledger:** `docs/gen3_emerald/REQUIREMENTS.md`
  (EC-1..EC-4).

## 1 What EG3 signs

The E3 diff to shared code, the server and the Gen 3 client, as below. None of it lets an
Emerald cartridge reach the production client: the by-name refusal in `lua/slink.lua`,
`UNADMITTED_GAMES` gen3_e, and `gen3_emerald` absent from `Entry.ROUTED` all stay until EG4
(ruling 24).

| Area | Change | Files |
|---|---|---|
| Pairing | Foundation `emerald → gen3_emerald`: FR↔E and RR↔E are refused before adapter reselection, E↔E is admitted, label "Emerald" | `server/adapters/__init__.py` |
| Title data | Gen3Adapter keeps `rom_type`. Emerald gets: gift/fixed-gift sets from `statics.json` via the area map; no daycare area; items 375/376; `generation-iii/emerald` sprites; Nature Power 95; title-scoped display names; `area_pack` | `server/adapters/gen3_frlge.py`, `server/data/items/gen3_vanilla.py` |
| Shared server | `server.py` `_area_pack()` delegates the OBS/debug area catalog to the adapter. `state.py` also rebuilds the adapter on restore when its `rom_type` differs from the saved one | `server/server.py`, `server/state.py` |
| Gen 3 client | Game facts moved from literals to the pack: the committed battle state (`battle.commit_guard.value`), wire→title SE ids (`sound.se_ids`) and gift areas (`gift_areas.ids`). The FR/LG/RR packs carry today's values explicitly, and a missing field fails closed | `lua/gen3/client.lua`, `lua/gen3/entry.lua` (pass-through), `tools/gen_gen3_write_checkpoint.py`, `data/games/gen3_{frlg,rr,emerald}/write_checkpoint.json` |
| Emerald area map | Every `statics.json` map has a named area: 4 gift areas, and static maps in their MAPSEC area. The daycare row is fixed to 0:32 | `tools/gen_area_map.py`, `tools/gen_gen3_emerald_statics.py`, `data/games/gen3_emerald/*` |
| Codec | Named refusal of unknown titles and CFRU+Emerald combinations; rom_type aliases | `server/adapters/gen3_codec.py` |
| Docs | `docs/protocol.md` §8.2 (wire SE ids), plus 145 remapped citations | `docs/protocol.md` |

**EG3 does NOT sign:**
- admission or routing (EG4);
- Emerald duos, the P+H re-pin on Emerald hardware, or the final-cut runner (E4/E4b);
- trade (E5).

## 2 Exit evidence (PLAN E3 row + EC-1..EC-4)

| Item | Status | Evidence |
|---|---|---|
| FR↔E, RR↔E refused before adapter reselection; `links.json` bytes unchanged | ✓ M | `test_mixed_foundations.py::test_emerald_never_pairs_with_firered_or_rr` (4 arrival orders, `_snapshot` includes the raw `links.json` bytes) |
| E↔E admitted | ✓ M | `test_mixed_foundations.py::test_emerald_pairs_with_emerald` |
| Unknown-sha1 BPEE | ✓ M | Admitted by ANCHORS as `clean` when all 21 sites pin (`test_gen3_entry.py::test_admission_by_anchors_when_the_hash_is_unknown_for_emerald`). Admitted by HEADER as `named` when they don't (`test_gen3_emerald_server.py::test_an_unknown_bpee_cartridge_admits_as_the_named_kind`). The plan's wording named only the second path |
| Conformance World green on Emerald | ✓ M | `test_protocol_conformance.py::test_world_rows_on_emerald`: the per-artifact bodies on the Emerald cartridge, using a test-only admitted copy of the pack (Emerald stays unadmitted in the tree) |
| Capabilities fixture | ✓ M | `test_mockup_fixtures.py`; the Emerald row equals the generator's output |
| Manifest closure | ✓ M | `test_make_release_manifest.py::test_every_entry_pack_file_is_in_the_release_manifest` |
| slink-adapter-guard clean + independent review | ✓ | The guard was CLEAN on each shared diff: `bc2b6967` (server.py `_area_pack`), and `3b3ac9b5` (the state.py rebuild hunk; the verdict found no game literals, a getattr default that makes it opt-in, and no Gen 1/2/4/5 adapter with a public `rom_type`). OMP reviews, every finding verified: cx-daf0f544, cx-361cd02b, cx-7f5a9609, cx-15773cbb, cx-f0b9e13b (audit), and cx-6ecf4fc8 (the final diff: NO BLOCKER; it recommends signing the runtime diff; its three small items landed in `7cf4a3c9`) |
| EC-2 title data, incl. restart/rollback | ✓ M | `test_gen3_emerald_server.py`: restart and rollback keep the title adapter (emerald/firered/firered_rr), plus the items, sprites, Nature Power and area-catalog tests |
| EC-3 refusal/unadmitted until EG4 | ✓ (unchanged) | `test_gen3_emerald_entry.py`, `test_slink_route.py` |
| Gifts/statics link | ✓ M | The producer-coverage test (`test_gen3_emerald_areas.py`) and SoulLinkState end-to-end pairs (`test_gen3_emerald_server.py::test_a_fixed_gift_pairs_under_the_species_clause`: Beldum, Deoxys, FR Lapras), with the fossil control |
| Pack-driven client constants | ✓ M + P (FR/RR) | `test_gen3_emerald_client.py` (6 of 7 red on the old client) and `test_gen3_client.py`. PHYSICAL FR/LG/RR regression duos: `probes/duo_e3_regression_2026-09-26.txt` (at 752cf2e5) and `probes/duo_e3_final_2026-09-26.txt` (at ef99d9b8): FR/LG linked_faint_active + deadzone, RR faint_cmd + explode, all PASS |

## 3 Defects found and fixed in E3

Reviews and workers found each of these before they could ship:
- The Emerald linked faint would have been refused every frame (row 4 wrote FR's 3; Emerald needs 4).
- Every Emerald sound cue was refused (FR SE numbering).
- Emerald gifts and legendaries never linked: area "" was dropped by the server.
- A restart or rollback silently reverted an Emerald run to Kanto data.
- A missing Emerald pack file broke `import server.adapters` for every game.
- A fixed-gift clause bypass keyed on ids nothing produced.
- The codec raised a bare KeyError, and `qualify_flash` broke its tuple contract.

## 4 MODEL / PHYSICAL evidence

- Unit suite without Gen 2 at `ef99d9b8`: 7732 passed, 779 skipped. Environment-only failures:
  - Gen 2: no `.cache/gen2-build`;
  - `gen1_pure_lanes` / `gen1_trade_patch`: no built `gen1_red.gb` or pokered cache.
- Generators `--check` are current (profile, write_checkpoint). The FR/LG area map is
  byte-identical.
- PHYSICAL: the FR/LG/RR regression duos (above).

## 5 Limits and consequences

- **Gen 3 receipts move.** The FR/LG/RR `write_checkpoint.json` gained explicit fields, so every
  Gen 3 receipt that pins the pack hash (e.g. `tools/gen3_bw_hashes.py`) changes when this reaches
  master.
- **Gen 2 re-sweep.** `server/**` changed, so all Gen 2 receipts go stale (~2 h re-sweep). The
  merge to master must be batched with the Gen 2 lane.
- **SE map live coverage.** The wire→title map is not visible in the duo logs. It is covered by
  unit tests, the FR sfx tests unchanged plus the Emerald mapping tests, and goes live at E4 on
  Emerald.
- **Emerald client coverage.** The Emerald client runs only in tests (a test-only admitted pack
  copy) until EG4.
- **docs/protocol.md staleness, pre-existing on master and not ours:** 18 citations name the
  deleted `gen3_frlge_client.lua`, and the section-7 `state.py` rows were already off at
  `056f248f`. The remap carried them faithfully. Routed to the Gen 3 lane.

## 6 Owner decisions requested

1. Sign the shared diff in §1: server pairing and title data, the `state.py` restore rebuild, and
   the pack-driven Gen 3 client constants.
2. **Policy for static legendary areas:** a failed catch of Kyogre, Rayquaza and the rest
   dead-zones that area, as `navel_rock` and `birth_island` do on FR/LG. This follows the plan's
   "mirror FRLG" default, and OMP flagged it as a ruling, not a derivation. Mew and Deoxys still
   bypass clauses.
3. **Named gift areas:** gift maps are named areas in the pack (FR/LG `silph_co_7f` precedent);
   the unproduced `gift_<g>_<n>` scheme is dropped.
4. When this reaches master: batch with the Gen 2 lane (re-sweep) and tell the Gen 3 lane that
   the pack hashes moved.
5. Sign EG3. E4 then starts: Emerald duos and the P+H re-pin, toward EG4 admission.

## 7 How to verify

```
git -C .claude/worktrees/gen3-emerald log --oneline 9598ae35..ef99d9b8
python -m pytest tests/unit/test_mixed_foundations.py tests/unit/test_gen3_emerald_server.py tests/unit/test_gen3_emerald_client.py tests/unit/test_gen3_emerald_areas.py tests/unit/test_protocol_conformance.py tests/unit/test_gen3_codec_emerald.py -q
python tools/gen_gen3_write_checkpoint.py --check
python tools/e2e_duo.py --game gen3_frlg --scenario linked_faint_active_gen3
```
