# C0-3 hg-engine fresh build association, 2026-10-01

- **Tool:** `tools/gen4_hge_build.py --build` (owner decision D2: build via the key-based `hgbox` alias). It replicates the fork's `build-remote.sh` but writes outputs only to `.cache/gen4/hge/build-<commit12>/` and never into the fork's tracked `build_output/`.
- **Fork commit:** `fc517576498305ecb5f5e1de44681c6e3822361b`. Tracked files were clean before and after the build (`fork_clean_after: true`).
- **Fresh `test.nds` sha1:** `cb2dc435196d09c8c9209bf037240ed834f4cea1`. It equals the pinned hge build in `data/gen4_sources.lock.json`, so the check is **PASS**. The coordinator re-hashed the pulled file.
- **Exports:** `offsets.ini` and `build/rom_gen.ld` are byte-equal to the cached copies in `.cache/gen4/hge/`. `nm_all.txt` is equal after excluding absolute symbols; the raw `nm` output, which keeps about 31k absolute symbols, is stored in the build dir.
- **Manifest:** `.cache/gen4/hge/build-fc5175764983/manifest.json` (gitignored).
- **Limits:**
  - This was an incremental box build (as `build-remote.sh` does), using the box's existing `build/` and `rom.nds`. It is not a from-scratch reproducibility proof; `clean all` was deliberately not run.
  - The lock's `pending.hge_fresh_build_export_association` entry can now cite this receipt. The lock is unchanged here, because it is hash-bound by the C0 binding manifest.
- **Tests:** `tests/unit/test_gen4_hge_build.py`, 8 passed, with subprocess faked and controls revert-tested. Ruff is clean. Worker: Claude Sonnet subagent; verified by the coordinator.
