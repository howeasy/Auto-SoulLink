# 36: Make the Gen 2 overlay survive a release stamp

Status: ready-for-agent

**Current status (2026-10-03): OPEN.** Gen 2 shipped unstamped (`dev`) in v0.3.0 because its overlay evidence is bound to exact bytes. Before the first Gen 2 stamp, every layer below must accept an earlier stamp of the same canonical build, the way Gen 1 (pureRGB) and Gen 3 do since `1e4dd98c`. Found by an OMP code sweep (`cx-f254e077`), checked at the source.

**What breaks today on a Gen 2 stamp:**

1. The client admits by exact sha1 only: `lua/gen2/entry.lua` `find_view` matches `row.sha1 == sha1` and the `hashes` callback returns `{row.sha1}`. A cartridge patched before the stamp gets "no overlay catalog row for the executed ROM". Mirror `lua/gen1/entry.lua` and `lua/gen3/entry.lua`, which index `equivalent_sha1s`.
2. The catalog generator drops the equivalents: `tools/gen_gen2_admission.py` writes `sha1`/`md5` for the overlay row and never copies `equivalent_sha1s` from `data/gen2/overlay_provenance.json` (which `tools/build_gen2_companion.py` already computes). Mirror `tools/gen_gen1_admission_profiles.py`.
3. The overlay receipts are bound to the exact `rom_sha1` and `binding_sha256` (`lua/gen2/signals.lua` receipt and `owned()` checks; `data/games/gen2_*/receipts/overlay/*.json`). Accept `{rom_sha1, *equivalent_sha1s}` and compare the binding by canonical identity; `tools/verify_gen2_release.py` already has that shape.
4. `tools/stamp_release.py`'s gen2 plan never regenerates `data/games/gen2_*/overlay/binding.json` (written by `tools/gen2_artifacts.py`), so `--promote-overlays` refuses the stamped bytes.

Lower priority from the same sweep: `server/upr_pipeline.py` `_gen2_clean_sha1s` recognises only SELECTED clean rows (Gen 2 never randomizes, so no player path today), and `tools/stamp_release.py` `identities()` does not read the admission catalogs, so a generator that stops writing a row is caught only by its exit code.

**Exit evidence:** a unit test that every `equivalent_sha1s` in each `data/games/gen2_*/admission.json` overlay row admits through `Entry.admit` as that row; a `stamp_release.plan()` test that the gen2 steps include the binding writer before the admission rows; then a real Gen 2 stamp followed by the Gen 2 evidence re-run.

**Shared-module decision:** reuse the equivalent-sha1 pattern already in the Gen 1 and Gen 3 entries; no new mechanism.
