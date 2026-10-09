# Release inventory — making `gen2_polished` a shippable release title

Every place that must change for `gen2_polished` to ship like `pureRGB` / Gen 2.
Read-only inventory: this document changes nothing.

Branch at inventory time: `claude/gen2-polished`, HEAD `e256ba88`, working tree dirty
with **1 untracked** file (unread — **UNVERIFIED**).

**Headline: the Manager, the picker and the data packs are largely already there; the
patcher and the release verifier are not.** `server/manager.py` already carries a
`gen2_polished` row and five explicit refusals; `server/patcher.py`'s `TARGETS` has
**no** `gen2-polished` entry even though `patch/dist/SLink-Polished.ups` exists.

## 1. `tools/make_release.py` — shared, Gen 2 digest

`tools/make_release.py:192` `gen1_purergb`, `:208` `gen2_crystal`, `:244` `gen2_gold`
— a per-title dict of required receipts. Lines `:210-216` and `:236-242` list the
Crystal receipts, each named `crystal_*`.

**Current behaviour:** a release row is emitted per key in that dict; there is no
`gen2_polished` key.
**Minimal change:** add a `"gen2_polished"` entry listing the Polished receipts that
actually exist. `docs/polished/README.md:44-53` names the generated ones
(`engine_signals.json`, `write_checkpoint.json`, `profile.json`, the `.sym`, `free_space.txt`),
but **I did not read `receipts/` and do not know which Polished receipts are on disk —
UNVERIFIED.**
**Shared or Polished-only:** shared (stale Gen 2 digest is the content, not the code).

## 2. `server/patcher.py` `TARGETS` — Polished-only, absent

Slugs present (`server/patcher.py:123,133,143,158,168,178,194,204,214`): `rr`,
`rb-red`, `rb-blue`, `pure-red`, `pure-blue`, `pure-green`, `gen2-crystal`,
`gen2-gold`, `gen2-silver`.

**There is no `gen2-polished` slug**, while `patch/dist/SLink-Polished.ups` exists on
this branch. The Gen 2 entries carry `slug`/`label`/`patch`/`accept`/`out_name`/
`base_hint` (`:124-131`); the pureRGB entries add a stricter refusal (the memory note
records "fail-closed patcher + test" applied in `2c9b3119`).

**Minimal change:** add a `"gen2-polished"` target — `patch: "SLink-Polished.ups"`,
`.gbc` accept, an `out_name`, and a `base_hint`. **UNVERIFIED** whether the patcher
needs a Polished-specific `verify`/refusal hook (the pureRGB refusal is about
unverifiable dump identity, which may not apply to a released ROM with a known sha1).
**Polished-only.**

## 3. `tools/verify_gen2_release.py` — shared, and the largest item

- `:61` `TITLES = ("crystal", "gold", "silver")`
- `:65-66` receipt-name set (`crystal_town`, `gold_town`, …)
- `:133` iterates `TITLES`; `:210`, `:259` derive requirement ids from `TITLES`
- `:243` artifact set `("pokecrystal", "pokecrystal11", "pokegold", "pokesilver")`
- `:285` `DUO_PAIRS = (("crystal","crystal"), ("crystal","gold"), ("gold","silver"))`
- `:940` `POISON_SETUP_RECIPE` keyed on `(gold, gold_battle_errand)` / `(crystal, crystal_battle)`

**Current behaviour:** the verifier builds requirement graphs for exactly three vanilla
titles and three duo pairs. Polished is not a member of anything.
**Minimal change:** none is safe without deciding what a Polished "title" means to the
verifier — it is a *solo* title (no vanilla pairing), so `TITLES`, `DUO_PAIRS` and
`POISON_SETUP_RECIPE` all need Polished-specific handling rather than a row append.
**UNVERIFIED** the full requirement-id surface these drive.
**Shared** (stale Gen 2 digest).

## 4. `server/manager.py` — mostly **done**

Already present on this branch:

| site | line | what it says |
|---|---|---|
| game row | `:74` | `("gen2_polished", "Polished Crystal", ["polished_crystal"])` |
| `GAME_FAMILY` | `:94` | `"gen2_polished": "gen2_polished"` |
| `FAMILY_WORDS` | `:96` | `"gen2_polished": "Polished Crystal"` |
| Randomize refusal | none in `manager.py` now | the switch is `upr_pipeline.POLISHED_RANDOMIZER_ENABLED = True` (`:274`), read by `cartridges.py:133` and `manager.py` `handle_cartridges`; while it is False the refusal is *"Polished Crystal randomizing is not enabled in this build; turn Randomize off"*. Randomizer is enabled; allowed options are `upr_settings.POLISHED_OPTION_KEYS` (wild, starters, statics, trainers, trades) |
| explode clause | `:190` | `ok: False` — client not written yet |
| rival clause | `:200` | `ok: False` — needs a rewritten writer |
| picker/caps | `:210`, `:215` | `ok: False` |
| calculator | `:220` | `ok: False` — no Polished calc data |

**This is the fail-closed state working as intended.** The rows are *refusals*, so
nothing needs to be removed — only flipped when the underlying work lands.
**Minimal change:** flip each `ok` only with its blocker. **Polished-only.**

## 5. `server/static/*.js` — mostly **done**

- `server/static/randomizer.js:264` `familyLabel()` already maps
  `'gen2_polished' -> 'Polished Crystal'`
- `server/static/randomizer.js:288` picker already registers
  `add('Polished Crystal', function (r) { return r.clean && r.family === 'gen2_polished'; })`
- `server/static/calc-preview.js:14`, `:157` know `purergb` but **not** `gen2_polished`

**Minimal change:** the picker needs a *dex* entry only when the calculator gains
Polished data (manager `:220` refuses it). **Polished-only.**

## 6. `server/cartridges.py` — **UNVERIFIED**

A grep for `crystal|purergb|polished|GAME_FAMILY|ROM_DIRS` in `server/cartridges.py`
returned **nothing**, which means the terms I searched are not there by those names.
The project context describes `GAME_FAMILY` and `ROM_DIRS` as living there. Either the
file moved, the names differ, or it is not on this branch's working tree in the form I
expected. **I did not read the file** — treat this row as open and re-grep it.

## 7. `data/upr_jars.json` — do not edit; note only

Keys are free-text build labels mapping to a sha256; entries include
`"… 4.6.1-slink3, patches 0001-0009 …"` (`7064a77d…`) and later builds through
`patches 0001-0011` (`db24703b…`).

The branch has patches through **0019** (`git log`: *"UPR handler cut 4 (patch 0019)"*),
so **no entry in this file corresponds to the current fork**. The Manager runs only
jars pinned by sha256 here, so a Polished randomize path needs a new entry.
**Minimal change (not made, per instruction):** one new key for the 0017-0019 build and
its sha256, recorded by `--pin`. **UNVERIFIED** which of 0017-0019 is the shipping cut.

## 8. Tests that hardcode the title set — partially **UNVERIFIED**

`tests/unit/*.py` files that mention `crystal`: `companion_evidence.py`,
`test_build_gen2_companion.py`, `test_calc_names_multigen.py`, `test_calc_profile.py`,
`test_calc_trainer_sets.py`, `test_cartridges.py`, `test_client_invariants.py`,
`test_companion_required_gen2.py`, `test_conftest_junctioned_cache.py`,
`test_dashboard_js.py` (and more). `tests/fixtures/gen2/receipts/*` are vanilla receipt
fixtures with `cc`/`gs`/`cg` suffixes — those are **fixture data, not title sets**, and
should not change.

**UNVERIFIED:** which of those ten actually asserts a *title set* rather than a single
title. I listed filenames, not their contents.

## 9. Docs index — **already done**

`docs/polished/README.md` is an index with a generator table (`:44-53`) already naming
`tools/build_polished_syms.py`, `build_polished_companion.py`,
`gen_upr_polished_ini.py`, `gen_polished_script_sites.py`, `gen_polished_pack.py`,
`gen_polished_profile.py`, `gen_polished_engine_sites.py`. `:21` lists `HOOKS.md`.
**Minimal change:** add a `RELEASE.md` row. **Polished-only.**

## 10. The six things still refused for Polished, and the row that flips each

| # | refused | flag/row | flips when |
|---|---|---|---|
| 1 | Randomize (the UPR fork path) | `manager.py:113` | a Polished jar pinned in `data/upr_jars.json` **and** `PolishedCrystalRomHandler` lands |
| 2 | Explode Mode | `manager.py:190` (`OPTION_SUPPORT` explode) | the Polished explode writer is wired (`EXPLODE_RIVAL.md` §9.1 says SAFE at the `0f:416A` hold) |
| 3 | Rival Team Swap | `manager.py:200` | the rival-swap writer ships with the `0f:47dd` PC gate |
| 4 | Picker / cartridge caps | `manager.py:210`, `:215` | the client + server pre-check agree on a Polished pair |
| 5 | Calculator | `manager.py:220`; `calc-preview.js:14,157` | Polished calc data lands (new species, forms, abilities) |
| 6 | Patcher | `server/patcher.py` `TARGETS` | a `gen2-polished` target with `SLink-Polished.ups` exists |

A seventh, not a Manager flag: `tools/verify_gen2_release.py:61` `TITLES` — the release
verifier has no Polished title at all, so a Polished release is invisible to it.

## 11. Done vs open on this branch

**Done (from `git log`):** injectable mon-key builder (`b94db87e`); randomized
cartridge server-side + contract hooks (`a7493734`); C-ROMTABLES data-driven `rom.lua`
+ generated profile (`06ed56a2`); explode/rival writers as pure Lua modules, unwired
(`6600e6c3`); UPR handler cut 4 / patch 0019 (`a9ba758c`); docs index with the generator
table; Manager `gen2_polished` row and its five refusals; picker + familyLabel.

**Open:** patcher target; `verify_gen2_release.py` Polished membership;
`make_release.py` row; `upr_jars.json` 0017-0019 pin; `server/cartridges.py` (unread);
the ten candidate test files (unread); README `RELEASE.md` row.

## 12. Claims

```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/tools/make_release.py","line":192,"expect":"\"gen1_purergb\": ["},{"path":"F:/slink-work/wt/polished/tools/make_release.py","line":208,"expect":"\"gen2_crystal\": ["},{"path":"F:/slink-work/wt/polished/tools/make_release.py","line":244,"expect":"\"gen2_gold\": ["},{"path":"F:/slink-work/wt/polished/tools/make_release.py","line":210,"expect":"receipts/overlay/crystal.engine_sites.json"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":123,"expect":"\"rr\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":133,"expect":"\"rb-red\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":143,"expect":"\"rb-blue\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":158,"expect":"\"pure-red\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":168,"expect":"\"pure-blue\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":178,"expect":"\"pure-green\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":194,"expect":"\"gen2-crystal\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":204,"expect":"\"gen2-gold\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":214,"expect":"\"gen2-silver\": {"},{"path":"F:/slink-work/wt/polished/server/patcher.py","line":130,"expect":"\"out_name\":    \"Pokemon - Radical Red (SLink companion).gba\""},{"path":"F:/slink-work/wt/polished/tools/verify_gen2_release.py","line":61,"expect":"TITLES = (\"crystal\", \"gold\", \"silver\")"},{"path":"F:/slink-work/wt/polished/tools/verify_gen2_release.py","line":65,"expect":"\"crystal_town\", \"crystal_battle\""},{"path":"F:/slink-work/wt/polished/tools/verify_gen2_release.py","line":133,"expect":"for title in TITLES]"},{"path":"F:/slink-work/wt/polished/tools/verify_gen2_release.py","line":243,"expect":"\"pokecrystal\", \"pokecrystal11\", \"pokegold\", \"pokesilver\""},{"path":"F:/slink-work/wt/polished/tools/verify_gen2_release.py","line":285,"expect":"DUO_PAIRS = ((\"crystal\", \"crystal\"), (\"crystal\", \"gold\"), (\"gold\", \"silver\"))"},{"path":"F:/slink-work/wt/polished/tools/verify_gen2_release.py","line":940,"expect":"POISON_SETUP_RECIPE = {(\"gold\", \"gold_battle_errand\"): \"psn\""},{"path":"F:/slink-work/wt/polished/server/manager.py","line":74,"expect":"(\"gen2_polished\", \"Polished Crystal\", [\"polished_crystal\"])"},{"path":"F:/slink-work/wt/polished/server/manager.py","line":94,"expect":"\"gen2_polished\": \"gen2_polished\""},{"path":"F:/slink-work/wt/polished/server/manager.py","line":96,"expect":"\"gen2_polished\": \"Polished Crystal\""},{"path":"F:/slink-work/wt/polished/server/manager.py","line":113,"expect":"\"gen2_polished\": \"Polished Crystal randomizer support is coming via the UPR fork; turn Randomize off\""},{"path":"F:/slink-work/wt/polished/server/manager.py","line":220,"expect":"\"gen2_polished\": {\"ok\": False, \"why\": \"The calculator has no Polished Crystal data (new species, forms and abilities).\"}"},{"path":"F:/slink-work/wt/polished/server/static/randomizer.js","line":264,"expect":"f === 'gen2_polished' ? 'Polished Crystal'"},{"path":"F:/slink-work/wt/polished/server/static/randomizer.js","line":288,"expect":"add('Polished Crystal', function (r) { return r.clean && r.family === 'gen2_polished'; });"},{"path":"F:/slink-work/wt/polished/server/static/calc-preview.js","line":14,"expect":"'calc/data/purergb.js'"},{"path":"F:/slink-work/wt/polished/docs/polished/README.md","line":53,"expect":"tools/gen_polished_engine_sites.py --check"}]
```


---

## Coordinator correction (2026-10-04)

* **F1 is WRONG.** `server/patcher.py` already registers the target: `_register_polished` (`:229`) adds
  slug `polished-crystal` (`:238`, patch `SLink-Polished.ups`, base md5 of the v3.2.3 release, overlay md5
  read live from `data/polished/overlay_provenance.json`, fail-closed per target). It is added in
  commit 930ae329 and hardened in 2c9b3119. The OMP grepped for a `gen2-*` slug in the literal `TARGETS`
  dict and missed the function that appends to it. The recommendation "take F1 first" is retracted.
* **F2 stands** and is the real release gap: Polished is a solo title, so `verify_gen2_release.py`
  needs Polished-specific handling, not a `TITLES` append. Owner decision; do not edit it before then.
* **F5 stands:** jars 0017-0019 are unpinned (`data/upr_jars.json` is never edited by this lane; pin
  `fe3236241675da98258b46bad3c0d81f70034331bcf706dd088f7eeb5156c389` for 0019 only with the Gen 1/Gen 3
  lanes warned).
* The doc's CLAIMS block carries a stray `CLAIMS: ` prefix before the JSON; with it stripped all 29
  quotes verify, but the conclusions above are what matter.
