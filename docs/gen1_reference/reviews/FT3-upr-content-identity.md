# FT-3 — stable content identity for reproduced-UPR prepared pairs

## Bug

`server/gen1_prepared_cartridges.py` (reproduced-UPR path, `PreparedCartridges.__init__`)
built `content_profile_hash` by hashing the raw per-player `generation` record straight from
`server/upr_runner.py:134-140`. That record contains `"output": str(output)` — an **absolute
path** to the run's own `randomized.gbc`, unique to whatever directory the pair was prepared
into. Two Manager runs prepared from byte-identical ROM bytes + settings + seeds therefore got
two different `content_profile_hash` values, so the runtime contract
(`server/gen1_admission.py:cartridge_metadata`) differed between them, and a resumed run was
refused at `server/gen1_run_config.py:132-133` ("resumed run must use the predecessor cartridge
pair") even though the cartridges were identical. Canonical companion pairs
(`_init_canonical`) are unaffected — their hash comes from the installed catalog
(`companion_profiles()[variant]["content_profile_hash"]`), never from a run-local record.

## Before / after hashed inputs

Both before and after hash exactly `{"semantic_profile": ..., "manifest_sha256": ...,
"generation": ...}`; only the `generation` sub-object's shape changed.

**Before** (`server/gen1_prepared_cartridges.py:172-174`, old):
```python
"content_profile_hash": digest({
    "semantic_profile": expected["semantic_profile"],
    "manifest_sha256": expected["manifest_sha256"],
    "generation": run})   # run = upr_runner's raw per-player record, includes "output": <abs path>
```

**After** (`content_identity()` helper, `server/gen1_prepared_cartridges.py:34-45`):
```python
def content_identity(semantic_profile, manifest_sha256, generation):
    return digest({"semantic_profile": semantic_profile, "manifest_sha256": manifest_sha256,
        "generation": {k: v for k, v in generation.items() if k != "output"}})
```
Call site: `"content_profile_hash": content_identity(expected["semantic_profile"],
expected["manifest_sha256"], run)`.

Every other field of `generation` still participates: `schema`, `status`, `source_commit`,
`generation` (int), `jar_sha256`, `bridge_sha256`, `settings_sha256`, `gen1_policy_sha256`,
`source_sha256`, `source_sha1`, `seed`, `custom_names`, `effective_settings_string`,
`log_sha256`, `output_sha256`, `output_sha1`, `size`. Only the absolute `output` path is
dropped — content identity still turns on settings, seed and the actual produced bytes
(`output_sha256`/`output_sha1`/`size`), just not on where those bytes happened to be written.

## Other absolute-path leak candidates checked

- `expected["semantic_profile"]` (= `before["profile"]` from `gen1_upr_scan.scan_generated` /
  `scan_candidate`, `server/gen1_companion_patch.py:39`) — a structural/semantic scan of ROM
  bytes (species, addresses, starters, etc.). No filesystem paths. Not touched.
- `expected["manifest_sha256"]` (= `digest(manifest)`, `server/gen1_prepared_cartridges.py:164`)
  — `manifest` is `expected["manifest"]` (a deep copy of the installed catalog's companion
  manifest) with `manifest["output"]` set to `entry["rom"]`, which is the **relative**,
  directory-scoped path (`f"final/{player}/{rom_name}"`, validated by `path()` to stay inside
  `self.directory`) — not the absolute UPR output path. No change needed.
- `preparation_root` (`expected.update(..., preparation_root=str(self.directory))`,
  line 164) is an absolute path, but it was never part of the three hashed keys
  (`semantic_profile` / `manifest_sha256` / `generation`) — it only feeds the
  `canonical_json(expected) != canonical_json(report)` provenance comparison a few lines below,
  which is correct to keep location-sensitive (per the task) and was left untouched.

So `generation["output"]` was the only leak; it is now the only field excluded.

## TDD

Red test written first (`tests/unit/test_gen1_prepared_cartridges.py`, new file — no existing
unit test exercised the `reproduced_upr` PreparedCartridges path directly; the closest,
`tests/unit/test_manager_prepared_gen1.py`, mocks `PreparedCartridges`/`prepare_pair` entirely
and never constructs a real reproduced pair). Per the card, this factors the hashed-view
construction into a small pure helper (`content_identity`) and unit-tests the helper directly
instead of driving a real Java/UPR run:

- `test_content_identity_ignores_the_absolute_output_path` — same recipe, two different
  absolute `output` paths (`C:\runs\run_1\...` vs `E:\other\run_2\...`) → equal digest. **Red**
  before the fix existed (`ImportError: cannot import name 'content_identity'`); confirmed the
  import failure first, then implemented, then green.
- `test_content_identity_changes_with_settings_sha256`
- `test_content_identity_changes_with_seed`
- `test_content_identity_changes_with_output_sha256`
- `test_content_identity_changes_with_semantic_profile_or_manifest_hash`

## Pytest output

```
$ python -m pytest tests/unit/test_gen1_prepared_cartridges.py -q -o addopts= -p no:cacheprovider
.....
5 passed in 0.26s

$ python -m pytest tests/unit/test_gen1_prepared_metadata.py tests/unit/test_gen1_companion_admission.py tests/unit/test_manager_prepared_gen1.py -q -o addopts= -p no:cacheprovider
.....................................................
53 passed in 2.60s

$ python -m pytest tests/unit -q -o addopts= -p no:cacheprovider -k "prepared or admission or upr"
........................................................................ [ 20%]
........................................................................ [ 41%]
........................................................................ [ 61%]
........................................................................ [ 82%]
..............................................................          [100%]
350 passed, 7736 deselected in 23.90s
```

## ruff

```
$ ruff check server/gen1_prepared_cartridges.py tests/unit/test_gen1_prepared_cartridges.py
```
`tests/unit/test_gen1_prepared_cartridges.py`: all checks passed. `server/gen1_prepared_cartridges.py`
reports 38 pre-existing findings (import-sort at the top of the file, and dense
`stmt;stmt`/`if cond: raise` one-liners throughout the file's existing style) — all at line
numbers outside my diff (lines 12, 55, 72-233 in the untouched surrounding code). The lines I
added (34-45, and the `content_identity(...)` call site) introduce zero new findings; confirmed
by diffing `ruff check`'s reported line numbers against `git diff` hunks.

## Diff hash

`sha256(git diff -- server/gen1_prepared_cartridges.py tests/unit/test_gen1_prepared_cartridges.py)`:

```
fb44583659088dd15ed3282104f4309463e377fe8ba0aef69a4a2a7fb0c71d83
```
