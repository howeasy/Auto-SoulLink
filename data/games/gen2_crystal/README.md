# Gen 2 data pack: Crystal

One of three per-title packs (`data/games/gen2_crystal`, `gen2_gold`, `gen2_silver`) that
`server/adapters/gen2_gsc.py` reads for Crystal, Gold and Silver alike, with
`server/adapters/gen2_codec.py` (save and party structs) and `server/adapters/gen2_rom_scan.py`.
The legacy `gen2_crystal` *adapter* this directory was once named after was removed at P3b.8
(`server/adapters/__init__.py`); the directory name now just names the title.

**The data files here are inside the Gen 2 CODE_DIGEST** (`tools/gen2_code_digest.py`): editing any
`.json`/`.lua` here makes every Gen 2 receipt stale until the next evidence sweep. Prose files
(`.md`/`.txt`/`.rst`, like this README) are excluded.

## Status

Current Gen 2 evidence and verdicts: `python tools/verify_gen2_release.py --list` and
`docs/gen2/PLAN.md`. The companion overlays are BUILT, not ADMITTED, until the owner's G4.

## Files

Generated from the pinned decomp (pret/pokecrystal; `data/gen2_sources.lock.json`) by
`tools/gen_gen2_<name>.py`; each generator's `--check` verifies the committed file.

- `profile.json`: RAM/SRAM symbols and constants for this title (`gen_gen2_profile.py`)
- `admission.json`: admitted artifact rows (clean and overlay) (`gen_gen2_admission.py`)
- `engine_signals.json`, `write_checkpoint.json`: engine sites and write windows the client arms
- `species_index.json`, `moves.json`, `items.json`, `evolutions.json`, `trainers.json`
- `area_map.json`, `map_names.json`, `encounter_tables.json` (Morn/Day/Nite), `static_encounters.json`, `gifts.json`
- `charmap.lua`: the text charmap the Lua client uses
- `receipts/`: shipped qualification, engine-site, write-window and O-33 synth receipts the client re-validates at load

## Notes

- Mon identity key: `gen2_codec.key()`.
- Memorial box: the last box, `NUM_BOXES - 1` (`gen2_gsc.py`, `memorial_box_index`).
- Test inputs: an absent `.cache/gen2-build` clone is a named skip; see `tests/TESTING.md`.
