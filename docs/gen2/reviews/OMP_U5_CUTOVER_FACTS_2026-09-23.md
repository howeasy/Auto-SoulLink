# U5 Crystal cutover change list (OMP gen2-O11 cx-7724341a, 2026-09-23)

READ-ONLY source card at HEAD c6706803, recorded by the coordinator as the U5 implementation input.

1. `lua/slink.lua`: after the Gen 1 block (`:58-82`; its game_detect bypass is the early `return` at `:79`),
   add a TITLE-scoped Gen 2 block: GB/GBC/SGB sys probe; `local Entry = dofile(_dir.."gen2/entry.lua")`;
   `Entry.detect_title(...)`; `if title == "crystal" then dofile(_dir.."gen2/run.lua") return end`. Gold/Silver
   (still PENDING) and `AP_CRYSTAL` (O-8) keep the legacy `_CLIENT_MAP` route; `lua/slink_gen2.lua` is left alone
   (REMOVE at P3b.8). A PM_CRYSTAL cartridge with an unadmitted sha1 (rev 1.1, `pokecrystal11` BUILD_ONLY) is
   refused by `run.lua` with no fallback: the plan's intended fail-closed limit (GEN2_BINDING_PLAN.md:372, P6.2),
   accepted by the coordinator.
2. `server/adapters/__init__.py:70` only: `"Crystal": "gen2_gsc", "crystal": "gen2_gsc"`; `:71-73`
   (Gold/Silver/AP) stay legacy. The title binder already exists (U4 `09d4339`, U4b) — the P3b.7 plan's
   "re-pointing fails" premise is stale.
3. `tools/make_release.py`: land `lua/gen2/*` + `data/games/gen2_{crystal,gold,silver}/*` manifest rows in the SAME
   change: `tests/unit/test_make_release_manifest.py` roots its closure at `lua/slink.lua` and follows
   `entry.lua`'s literal pack paths (`entry.lua:16-59`), so it turns red the moment step 1 lands.
4. `server/manager.py`: NO change needed (gen2 family already listed `:66-67`; the launcher dofiles `slink.lua`
   `:475`; Gen 1 cartridge machinery already hidden for gen 2).
5. Tests pinning the legacy route (update): `test_gen1_launcher_route.py:123-127` (+ its harness only really
   executes gen1/entry.lua, `:26-60`), `test_gen2_pairing_matrix.py:88-93` and `:365-370`,
   `test_gen2_server_bind.py:75-79`, `test_rom_type_routing.py:41-43,55-70`. New: `test_gen2_launcher_route.py`
   (Crystal -> gen2/run.lua exactly once; Gold/Silver/AP_CRYSTAL -> legacy; GBA/NDS untouched; unpinned
   PM_CRYSTAL refused) and a persisted-run test: a run saved BEFORE the flip keeps `game_id="gen2_crystal"`
   (`state.py:905-913`) — assert it still works with the new client, and record the P3b.8 migration need
   (deleting `gen2_crystal.py` would make that path fall back to the Gen 3 default, `state.py:917-922`).
6. New vs legacy Crystal hellos are distinguishable (legacy sends `game_id`; new sends
   `foundation`/`artifact_kind`/`rom_sha1`), but nothing needs to branch on it after the row flip.
7. Open: a BizHawk version gate for Gen 2 (Gen 1 has one at `slink.lua:71-77`; none measured for Gen 2).
