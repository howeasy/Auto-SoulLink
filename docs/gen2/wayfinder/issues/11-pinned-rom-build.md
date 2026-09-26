# Reproducible pinned ROM builds and .sym files for Gen 2

Type: task
Status: resolved (2026-09-26; was open)
Blocked by: none

## Question

Gen 1's SOURCE evidence rests on `data/pret_sources.lock.json` + `tools/build_pret_syms.py` producing ROMs whose sha1 match `roms.sha1`, and `.sym` files the profile generators read. No Gen 2 `.sym` exists under `.cache/pret/` and the JSON symbol table has no provenance (docs/gen2/research/pret_gen2_symbols.md:10-11, rom_hashes.md). Define the build recipe (RGBDS version, targets pokecrystal.gbc / pokecrystal11.gbc / pokegold.gbc / pokesilver.gbc, expected sha1s f4cd194b.., f2f52230.., d8b8a360.., 49b163f7..) and the lock-file extension so a CI lane can prove it, mirroring pureRGB P1/G1 (docs/purergb/PLAN.md:49). Blocks every `expected_hex` site pin.

## Answer

Built (implementation ticket [`docs/gen2/issues/04-p1-source-build.md`](../../issues/04-p1-source-build.md)):
`data/gen2_sources.lock.json` + `tools/build_gen2_syms.py` produce `data/gen2/{pokecrystal,pokecrystal11,pokegold,pokesilver}.{sym,map}`; the four built sha1s
(`f4cd194b...`, `f2f52230...`, `d8b8a360...`, `49b163f7...`) match this ticket's expectations exactly and
are recorded in `data/games/gen2_{crystal,gold,silver}/admission.json` (gate G1, ADMITTED for the
selected revisions). CI reproduction is `.github/workflows/gen2-syms.yml`. This closes the
`expected_hex` site-pin dependency for ticket 12.
