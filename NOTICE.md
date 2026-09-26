# Third-party notices

SLink's own code is MIT ([LICENSE](LICENSE)). This file lists everything in the repository that
is not, because the boundaries matter if you redistribute.

## GPL-3.0 — `patch/upr/`

`patch/upr/*.patch` are patches against **[Universal Pokémon Randomizer ZX](https://github.com/Ajarmar/universal-pokemon-randomizer-zx)**,
which is licensed **GPL-3.0**. Those patches are a derivative work of it and are offered under
**GPL-3.0**, not MIT. Applying them produces a modified UPR ZX, which is also GPL-3.0.

This does not make the rest of SLink GPL. The patches live in their own directory and are
distributed alongside SLink rather than combined with it (GPL-3.0 §5, aggregation); SLink itself
never links against UPR — `server/upr_pipeline.py` runs the built jar as a separate process. The
built jar is **not** distributed here: it is gitignored at `.cache/slink-upr/PokeRandoZX.jar` and
is produced locally by `tools/build_upr_fork.py --bootstrap`.

If you redistribute a built fork jar, you are distributing GPL-3.0 software and must offer its
complete corresponding source.

## MIT — `calc/`

`calc/` is a fork of the **[Smogon damage calculator](https://github.com/smogon/damage-calc)**,
MIT, © 2013-2024 Honko and other contributors. The upstream licence is retained verbatim at
`calc/LICENSE`. Our changes (multi-generation dex support, the live party bridge, the SLink set
data) are MIT as well.

## Vendored JavaScript — `server/static/vendor/`

Bundled locally rather than loaded from a CDN, because OBS browser sources cache CDN assets
unpredictably. Versions are tracked in [`server/static/vendor/VERSIONS.md`](server/static/vendor/VERSIONS.md).

| File | Project | Licence |
|---|---|---|
| `htmx.min.js` | [htmx](https://htmx.org/) 2.0.3 | BSD-2-Clause (Zero-Clause upstream) |
| `idiomorph-ext.min.js` | [idiomorph](https://github.com/bigskysoftware/idiomorph) 0.7.3 | BSD-2-Clause |
| `alpine.min.js` | [Alpine.js](https://alpinejs.dev/) 3.14.1 | MIT |
| `overlay-helpers.js` | First-party | MIT (this repository) |

`lua/x64/socket-windows-5-4.dll` is a build of **[LuaSocket](https://github.com/lunarmodules/luasocket)**, MIT.

## Reference material, not redistributed code

Addresses, symbol tables and generated data packs under `data/` are derived from the
**[pret](https://github.com/pret)** disassembly projects (`pokered`, `pokeyellow`, `pokecrystal`,
`pokegold`, `pokefirered`) and from **[Complete-Fire-Red-Upgrade](https://github.com/Skeli789/Complete-Fire-Red-Upgrade)**.
Their sources are pinned by commit in `data/pret_sources.lock.json` and fetched into gitignored
caches; no pret source is vendored here.

**[pureRGB](https://github.com/Vortyne/pureRGB)** support is generated from that project's pinned
source in the same way. `patch/dist/SLink-Pure*.ups` are patches authored here; they apply to a
pureRGB build you produce yourself.

## What is NOT in this repository

**No ROMs and no savestates.** No `.gb`, `.gbc`, `.gba`, `.nds` or `.State` file is tracked. You
supply your own dumps of games you own.

The committed `.SaveRAM` and `.sav` files under `tests/` are **battery saves** — 32 KB (GB/GBC) or
128 KB (GBA) of cartridge save data, containing no game code. See
[`tests/fixtures/README.md`](tests/fixtures/README.md).

Pokémon is a trademark of Nintendo, Creatures Inc. and GAME FREAK Inc. This project is an
unaffiliated fan tool and is not endorsed by them.
