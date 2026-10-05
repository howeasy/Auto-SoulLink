# Polished Crystal RC tracker

**One table of every Polished feature, derived from this tree, not from memory.** Written 2026-10-04.

Every row names a test file that exists on disk and a commit that exists in git. Anything I could not
confirm from the repository is marked **UNVERIFIED** with what would settle it. No emulator was run for
this table; "live evidence" means a run recorded in `docs/polished/LIVE_RESULTS.md`.

**Status vocabulary**

| status | meaning |
|---|---|
| **DONE-validated** | code is merged AND a test file exists on disk that exercises it |
| **DONE-unproven-live** | code is merged and tested, but never run on a real cartridge |
| **PARTIAL** | some of the feature exists; the row says what is missing |
| **NOT STARTED** | no implementing code found in this tree |

## Table of record

| feature | status | branch / commit | proving test file | live evidence |
|---|---|---|---|---|
| hello + admission (overlay) | DONE-unproven-live | `claude/gen2-integration`, overlay `43ee19f0` lineage | `tests/unit/test_polished_client.py`, `tests/unit/test_polished_companion.py` | `LIVE_RESULTS.md` Run 1 Stage 1, Run 2 Stage A (PASS) |
| hello + admission (**randomized** cartridge) | DONE-unproven-live | `43ee19f0` ancestry; `lua/gen2/polished.lua` `P.admit`, `P.RAND_ANCHORS` | `tests/unit/test_polished_rand_admission.py` | Run 3 (randomized cartridge, `pokegear.json` etc.) |
| title / version stamping on the title screen | **NOT DONE** (coordinator correction: the peer's row cited `c9f1ad14`, which is the Phone-card contact, and header `PKPCRYSTAL` admission is hello, not version stamping) | `claude/pol-title` is uncommitted and has never built green | `tests/unit/test_build_polished_syms_export.py` only | none |
| wild-catch detection | DONE-unproven-live | `claude/gen2-integration`; `lua/gen2/signals.lua` `S.new_polished` (site `capture_party` `03:652b`) | `tests/unit/test_polished_sites.py`, `tests/unit/test_polished_engine_sites.py` | Run 1 Stage 2 (PASS: 1 hit, bank 3, PC `$652b`) |
| forms identity (key + effective wire) | DONE-validated | **`43ee19f0`** "regional forms judged as distinct mons end to end" | **`tests/unit/test_polished_effective_wire.py`**, `tests/unit/test_gen_polished_forms.py` | **none** — see the Run-2 GAP note; the GAP is superseded by `43ee19f0` |
| box census (read-only) | DONE-unproven-live | `claude/gen2-integration`; `lua/gen2/polished_boxes.lua` | `tests/unit/test_polished_boxes_census.py`, `tests/unit/test_polished_boxes.py` | Run 1 Stage 3 (PARTIAL) + Run 2 Stage A (rescan fix PASS) |
| box census → **write** (memorial/insert) | PARTIAL — census reads; `move_to_memorial`/`insert_mon` exist but the composition refuses every write kind | `lua/gen2/entry.lua` `compose_polished` `safety` stub | `tests/unit/test_polished_boxes.py` | none |
| box_mon deposit | NOT STARTED | — | `test_polished_client.py` records `box_mon_failed` for Polished | Run 1 S2-a (refusal round trip) |
| party_mon withdraw | NOT STARTED | — | — | none |
| force_faint | NOT STARTED (no Polished write receipt at all: `compose_polished`'s `safety` returns false for every kind) | — | `tests/unit/test_polished_client.py` (`test_no_hook_and_no_write_on_the_whole_path`) | none |
| explode / rival team swap | PARTIAL — `lua/gen2/polished_writes.lua` has the writers; no client path arms them | `claude/pol-battle` `6e7a1b53` | `tests/unit/test_polished_battle_sites.py` | none |
| battle-sites binder (opt-in) | DONE-validated | `claude/pol-battle` `6e7a1b53` | `tests/unit/test_polished_battle_sites.py` | none |
| randomizer + UPR jar | DONE-unproven-live | `server/upr_pipeline.py` (`POLISHED_VARIANT`), `tools/gen_upr_polished_ini.py` | `tests/unit/test_upr_polished_pipeline.py`, `tests/gen_upr_polished_ini` | Run 3 Stage R1/R2 (Manager randomized cartridge) |
| Phone-card virtual SLink contact | DONE-unproven-live | `patch/polished/src/slink.asm` (`SlinkPhone_*`, ROM0 `$3F34`), `lua/gen2/phone.lua` | `tests/unit/test_polished_phone_entry.py`, `tests/unit/test_polished_companion.py` | Run 2 Stage C (Pokegear strip; the virtual contact itself **not** confirmed driven) |
| phone calls (in-game) | NOT STARTED | `SlinkPhone_CallGate` prints a stub text; no call transport | `tests/unit/test_polished_phone_entry.py` | none |
| panel pages | DONE-validated (code) | `claude/pol-panel` `5ed07382`; `lua/gen2/panel.lua` | `tests/unit/test_polished_panel.py` | none — the overlay advertises **caps 0** |
| sounds | DONE-validated (code) | `claude/pol-sounds` `ef7fdd60` | `tests/unit/test_polished_sounds.py` | none — companion patch path, not run on a cart |
| native trade (receptionist) | PARTIAL — **53-byte trademon codec DONE-validated** in both languages; no ROM service, no anchor | `claude/pol-trade` `06be5c99`; `server/adapters/polished_codec.py` `TRADEMON`, `lua/gen2/polished_trade.lua` | `tests/unit/test_polished_trade_codec.py` | none |
| trade lease / mailbox binder | NOT STARTED | `lua/gen2/polished_trade.lua` `compose()` returns `nil, why` without `profile.overlay.trade` | — | none |
| calculator | DONE-validated | `claude/pol-calc` `c32791fe` | `tests/unit/test_gen_polished_calc.py` | none |
| overlay build + byte guard | DONE-validated | `tools/build_polished_companion.py`; committed overlay `9c60bc8fb26ac13c52705b8086f8a5fb91d7bd93` | `tests/unit/test_polished_companion.py`, `tests/unit/test_polished_release_guards.py` | `python tools/build_polished_companion.py --check` → "reproduces every artifact" |
| ROM tables / ram doc / forms pack | DONE-validated | `tools/gen_polished_*.py` | `tests/unit/test_polished_rom_tables.py`, `test_polished_ram_doc.py`, `test_polished_forms_adapter.py`, `test_polished_area_map.py` | n/a (source-only) |
| C-5 randomized duo gate | PARTIAL — `--c5` reader exists, **not a LANE**, receipts not installed | `tools/verify_gen2_release.py` `c5_errors()` `:2368` | `tests/unit/test_verify_gen2_c5.py` | none |

## How to re-derive this table

```bash
git log --oneline --all -- <the feature's main source file>
git branch --contains <sha>            # which branch carries it
python -m pytest tests/unit/test_polished_*.py -q --collect-only | tail -1
```

## Known-stale text elsewhere in `docs/polished/`

Marked in place, not rewritten (the original wording is kept as history):

* `FORMS.md`, owner rulings — said `polished_codec.key` "today keeps form 0-4 as traits". `key_form`
  normalises cosmetic forms now (`server/adapters/polished_codec.py:82-85`).
* `LIVE_RESULTS.md`, the Alolan Persian GAP — superseded by `43ee19f0` and the effective-species wire.
* `PHONE.md`, `PHONE_SLOT.md`, `POKEGEAR_SLOT.md`, `TITLE.md` — said ROM0 has "351 bytes free at `$015f`".
  `$015f` is that **count**, not an address; the real gaps are `$0089-$00FF` and the part of `$3F34-$3FFF`
  after the phone bridge. `HOOKS.md:812-813` already carried the correction; the four files did not.
* `CLIENT.md` line 4 — quoted overlay sha1 `29ea04c2…` as current. It is correct **for the runs it
  describes**; the current committed overlay is `9c60bc8f…` and `pol-panel` / `pol-sounds` will move it
  again. Read the current value from `data/polished/overlay_provenance.json` `output.sha1`.

  **NOTE (2026-10-04):** the sha1 above is tree-local and moves with every `pol-*` merge. It was
  `29ea04c2…` when `LIVE_RESULTS.md` Runs 1-2 were recorded, `34942315…` on the `claude/pol-trade`
  worktree, and `9c60bc8f…` on `claude/pol-docs`. **Do not copy a sha1 between trees — read the file.**

## UNVERIFIED in this table

* **Every "live evidence" cell** is a claim about a *historical* run recorded in `LIVE_RESULTS.md`. None was
  re-run for this table and none is a receipt; `LIVE_RESULTS.md` states its runs are DEV evidence, not
  PHYSICAL receipts. Settled by re-running the harness.
* **Branch attributions** are from `git log -1` on each `claude/pol-*` tip. Whether a given commit is actually
  *merged* into `claude/gen2-integration` (as opposed to existing on a branch) was not checked per feature.
  Settled by `git branch --contains <sha> | grep gen2-integration` for each row.
* **`claude/pol-battle` / `pol-calc` / `pol-panel` / `pol-sounds` / `pol-trade` tips** are reported as they
  stand in this worktree. `pol-panel` and `pol-sounds` change the overlay sha1 when merged, so any overlay
  sha1 quoted against them is transient.
