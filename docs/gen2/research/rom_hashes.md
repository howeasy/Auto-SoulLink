# Clean ROM SHA-1s — Pokémon Gold, Silver, Crystal (US/English)

Retrieved 2026-09-21 unless noted.

## Pins

**PIN CHANGE (mid-task, from the coordinator):** the Gen 2 pret pins moved to upstream HEAD —
`pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651`,
`pokegold@656583c939d30f920a316177311a502dd222b57c`. The read-only HEAD clones checked below are
at `<scratchpad>/pret_head/{pokecrystal,pokegold}`. The originally-briefed cached checkouts
(`pokecrystal@3438c70`, `pokegold@e78abb8`) were checked in the same pass. **Both `roms.sha1`
files are byte-identical between the cached checkout and the HEAD clone, for both repos**
(`diff` exit 0 on both pairs — no ROM-hash-relevant commit landed between the two pins).

| Repo | Cached checkout HEAD | Upstream HEAD (new pin) | `roms.sha1` identical? |
|---|---|---|---|
| pokecrystal | `3438c7003a57fa2987fcb223d14b660761b33c64` | `7a7881d0d62e0ddbd82dcf10e7116807487ac651` | yes |
| pokegold | `e78abb8382a734fe325a16136fd779dbea9b0d47` | `656583c939d30f920a316177311a502dd222b57c` | yes |

(`git -C <checkout> rev-parse HEAD` and `git -C <pret_head clone> rev-parse HEAD`, run in this
pass, 2026-09-21.)

## `roms.sha1` verbatim (both pins agree — quoting the cached checkout paths; identical content
confirmed at both HEAD clones above)

`E:/Google Drive/SLink/.cache/pret/pokecrystal/roms.sha1` (all 6 lines):
```
1: f4cd194bdee0d04ca4eac29e09b8e4e9d818c133 *pokecrystal.gbc
2: f2f52230b536214ef7c9924f483392993e226cfb *pokecrystal11.gbc
3: a0fc810f1d4e124434f7be2c989ab5b5892ddf36 *pokecrystal_au.gbc
4: c60d57a24bbe8ecf7cba54ab3f90669f97bd330d *pokecrystal_debug.gbc
5: 391ae86b1d5a26db712ffe6c28bbf2a1f804c3c4 *pokecrystal11_debug.gbc
6: a25517f60ca0e887d39ec698aa56a0040532a4b3 *pokecrystal11.patch
```
`E:/Google Drive/SLink/.cache/pret/pokegold/roms.sha1` (all 6 lines):
```
1: d8b8a3600a465308c9953dfa04f0081c05bdcb94 *pokegold.gbc
2: 49b163f7e57702bc939d642a18f591de55d92dae *pokesilver.gbc
3: 53783c57378122805c5b4859d19e1a224f02a1ed *pokegold_debug.gbc
4: 4c2fafebdbc7551f4cd3f348bdd17e420b93b6e7 *pokesilver_debug.gbc
5: b8253b915ade89c784c71adfdb11cf60bc1f7b59 *pokegold.patch
6: a38c0dec807e8a9e3626a0ec0fdf96bfb795ef3a *pokesilver.patch
```
Same content re-quoted at the `pret_head` HEAD clones (identical, see diff result above).

## Per-title record

`pokegold.gbc`/`pokesilver.gbc`/`pokecrystal*.gbc` are the "release" ROM builds; `*_debug.gbc`
are debug builds; `*.patch` files are IPS/BPS-style patches for other regions, not ROMs. Only
the release-ROM rows are Gen 2 client targets.

### Pokémon Gold (US) — `pokegold.gbc`
- SHA-1: `d8b8a3600a465308c9953dfa04f0081c05bdcb94` (`pokegold/roms.sha1:1`, both pins)
- README name/hash line: "Pokemon - Gold Version (UE) [C][!].gbc `sha1:
  d8b8a3600a465308c9953dfa04f0081c05bdcb94`" — `pokegold/README.md:7` on GitHub `master`
  (https://github.com/pret/pokegold/blob/master/README.md, retrieved 2026-09-21). "(UE)" =
  USA/Europe (dual-region) GoodTools-style tag on the filename, not a claim about a second
  build; the repo produces one Gold ROM and one Silver ROM (no separate US-only variant listed).
- Internal cartridge title (`rgbfix -t`): `POKEMON_GLD`
  (`pokegold/Makefile:191`, `pokegold.gbc: RGBFIXFLAGS += -t POKEMON_GLD -i AAUE`, both pins;
  https://github.com/pret/pokegold/blob/master/Makefile). Region/game-code byte `-i AAUE`.
  Cart-type/RAM/battery flags shared with Silver/Crystal: `-k 01 -l 0x33 -m
  MBC3+TIMER+RAM+BATTERY -r 3 -p 0` (`pokegold/Makefile:190`).
- MD5/CRC32: not stated by `roms.sha1` or the README (SHA-1 only). †No revision split found —
  the README and `roms.sha1` list exactly one Gold build (plus its debug variant), no "1.0/1.1"
  distinction the way Crystal has (see below).

### Pokémon Silver (US) — `pokesilver.gbc`
- SHA-1: `49b163f7e57702bc939d642a18f591de55d92dae` (`pokegold/roms.sha1:2`, both pins)
- README line: "Pokemon - Silver Version (UE) [C][!].gbc `sha1:
  49b163f7e57702bc939d642a18f591de55d92dae`" — `pokegold/README.md:8`.
- Internal cartridge title: `POKEMON_SLV`, region byte `-i AAXE`
  (`pokegold/Makefile:192`, `pokesilver.gbc: RGBFIXFLAGS += -t POKEMON_SLV -i AAXE`).
- MD5/CRC32: not stated in-repo (SHA-1 only).

### Pokémon Crystal (US), revision 1.0 — `pokecrystal.gbc`
- SHA-1: `f4cd194bdee0d04ca4eac29e09b8e4e9d818c133` (`pokecrystal/roms.sha1:1`, both pins)
- README line: "Pokemon - Crystal Version (UE) (V1.0) [C][!].gbc `sha1:
  f4cd194bdee0d04ca4eac29e09b8e4e9d818c133`" — `pokecrystal/README.md:7`
  (https://github.com/pret/pokecrystal/blob/master/README.md, retrieved 2026-09-21). This is
  the revision `pokecrystal.gbc` (the repo's primary/default make target) builds.
- Internal cartridge title (`rgbfix -t`): `PM_CRYSTAL` (`pokecrystal/Makefile:169`,
  `RGBFIXFLAGS += -Cjv -t PM_CRYSTAL -k 01 -l 0x33 -m MBC3+TIMER+RAM+BATTERY -r 3 -p 0`, both
  pins; https://github.com/pret/pokecrystal/blob/master/Makefile). The `-C` flag (lowercase
  in `-Cjv`, capital C = "set the CGB-only flag") marks the cartridge CGB-only — no DMG mode,
  see `bizhawk_gambatte_gbc.md` §4 in this same directory.
- MD5/CRC32: not stated in-repo.

### Pokémon Crystal (US), revision 1.1 — `pokecrystal11.gbc`
- SHA-1: `f2f52230b536214ef7c9924f483392993e226cfb` (`pokecrystal/roms.sha1:2`, both pins)
- README line: "Pokemon - Crystal Version (UE) (V1.1) [C][!].gbc `sha1:
  f2f52230b536214ef7c9924f483392993e226cfb`" — `pokecrystal/README.md:8`. Built by the
  `pokecrystal11` make target (a separate object set per `pokecrystal/Makefile`'s
  `pokecrystal11_obj` rules), a secondary target alongside the repo's primary `pokecrystal.gbc`
  (V1.0) target.
- Also present, not requested but adjacent: Crystal (A) [Australian region] SHA-1
  `a0fc810f1d4e124434f7be2c989ab5b5892ddf36` (`pokecrystal/roms.sha1:3`,
  `pokecrystal/README.md:9`) — not US/English, listed only for completeness.

**Which revision does pret target?** Both — `pokecrystal.gbc` (V1.0) is the repo's un-suffixed,
primary build target (appears first in `roms.sha1` and the README, and is the name every other
doc in this repo uses when it says "Crystal" without a revision, e.g.
`docs/gen1_gen2_runtime_checks.md:179`'s `crystal_town.SaveRAM` fixture); `pokecrystal11.gbc`
(V1.1) is a secondary target the same Makefile also builds. Neither README nor `roms.sha1`
states which one a downstream consumer "should" prefer — that is a project decision, not a pret
fact (see Open questions).

## `data/pret_syms.json` — no `rom_sha1` field

The brief asked to check `data/pret_syms.json`'s `pokecrystal.rom_sha1` / `pokegold.rom_sha1`
keys. **Neither key, nor any `rom_sha1` key at all, exists anywhere in that file** — confirmed
with `python -c "import json; ... "` walking every key/value pair in
`data/pret_syms.json` (36159 lines) in this worktree: the only `rom_sha1`-bearing file in this
repo is a **different** file, `data/pret_rom_syms.json`, and it only has entries for
`pokered`, `pokeblue`, `pokeyellow` (each `{"rom_sha1": ..., "symbols": {...}}`) — no `pokegold`
or `pokecrystal` key exists in `pret_rom_syms.json` either. `data/pret_syms.json`'s top-level
keys are `pokered`, `pokeyellow`, `alchav_pokered`, `pokecrystal`, `pokegold`, and each of those
holds only address/symbol pairs (e.g. `pokecrystal.wSwitchMonFrom = 53740`), no ROM-identifying
data at all.

This matches (and is corroborated by) the sibling research note already in this directory,
`docs/gen2/research/pret_gen2_symbols.md:6`, which independently found the same absence: "No
`rom_sha1` key exists in the file ... `tools/build_pret_syms.py` resets each cache to
`origin/HEAD` (unpinned) before extracting symbols, so the JSON's values cannot be assumed to
come from the shas pinned above."

So: **the brief's premise (that `data/pret_syms.json` carries `pokecrystal.rom_sha1` /
`pokegold.rom_sha1`) does not hold against the file as it exists in this worktree.** There is
nothing to compare against `roms.sha1` from this file.

## Local ROM files

`E:\Google Drive\SLink\roms` does not exist — confirmed with a direct listing attempt
(`ls "E:/Google Drive/SLink/roms"` → "No such file or directory") and a directory listing of
`E:\Google Drive\SLink`'s top level, which has no `roms` entry (only `.cache`, `.claude`,
`.codex-worktrees`, `.git`, `.github`, `.pytest_cache`, `.ruff_cache`, `.venv`, `calc`, `data`,
`dist`, `docs`, `lua`, `patch`, `server`, `tests`, `tools`, `__pycache__`). A repo-wide
`find -iname "*rom*"` at depth 2 turned up only `.cache/purergb-roms-tmp`, `data/pret_rom_syms.json`,
and `tools/verify_gen1_rom_layout.py` — no directory of actual `.gbc`/`.gb` ROM files anywhere
under the worktree or the repo root. **No local Gold/Silver/Crystal ROM files were found to
hash**, so the "hash them if it takes under a minute" step is moot — there is nothing to hash.

## Open questions

- No MD5 or CRC32 for Gold/Silver/Crystal was found in `roms.sha1` or either README — both
  sources are SHA-1-only. A No-Intro/Datomatic cross-check (†SECONDARY, would need to reach the
  actual `.dat` file rather than a search-result summary) was not performed in this pass.
- Whether `pokecrystal.gbc` (V1.0) or `pokecrystal11.gbc` (V1.1) is the revision the Gen 2
  client/fixtures should target is a project decision pret's own docs do not make — flagging
  for the coordinator rather than guessing.
- The AP (Archipelago) Crystal fork's ROM hash was out of scope for this note (no public repo,
  per `docs/gen1_gen2_runtime_checks.md:175-177`) and was not investigated further here.
- `pret_gen2_symbols.md:7` (this directory) notes no `.sym` file exists for either Gen 2 title
  anywhere under `.cache/pret/` — a build was not performed in this pass either, so there is
  still no generated symbol file to cross-check ROM identity against beyond the `roms.sha1`
  hashes quoted above.
