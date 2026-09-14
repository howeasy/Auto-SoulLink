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

## Round 1 diff hash (candidate 1b38696, superseded by round 2 below)

`sha256(git diff -- server/gen1_prepared_cartridges.py tests/unit/test_gen1_prepared_cartridges.py)`
at the time of the round-1 candidate:

```
fb44583659088dd15ed3282104f4309463e377fe8ba0aef69a4a2a7fb0c71d83
```

## Round 2 — REJECT: the defect persisted through a second field

Independent review of candidate 1b38696 found that dropping `generation["output"]` was not
enough. `run_pinned` (`server/upr_runner.py:69-141`) resolves custom names through
`selected_custom_names` (`server/upr_runner.py:56-66`):

```python
def selected_custom_names(jar, *, override=None, source_directory=None):
    if override is not None:
        path = Path(override).resolve()
        return path.read_bytes(), {"kind": "explicit", "path": str(path)}
    for path in (...):
        if path.is_file():
            return path.read_bytes(), {"kind": "file", "path": str(path)}
    with zipfile.ZipFile(jar) as archive:
        return archive.read(name), {"kind": "jar-resource", "member": name}
```

and `run_pinned` puts that `selection` straight into the generation record unmodified
(`server/upr_runner.py:138`): `"custom_names": {"sha256": sha(names), "selection": names_source}`.
Whichever branch fires — `override` (an explicit path the Manager passed), or the "file"
fallback (an absolute path next to the jar or source) — `selection.path` is a **second
run-local absolute path**, present even when the Manager passed no `custom_names` override at
all (only the `jar-resource` branch, keyed on a ZIP member name, is location-free). So two
identical pairs prepared into two different run directories still produced two different
`content_profile_hash` values, and the round-1 fix did not close the bug it was meant to close.

The round-1 test fixture used `"selection": "default"` — a plain string, not the real nested
`{"kind": ..., "path": ...}` shape — so it could not exercise this field at all and passed
despite the defect.

### Round 2 fix

`content_identity` now also strips `custom_names.selection`, keeping only its content hash:

```python
def content_identity(semantic_profile,manifest_sha256,generation):
    return digest({"semantic_profile":semantic_profile,"manifest_sha256":manifest_sha256,
        "generation":{k:({"sha256":v["sha256"]} if k=="custom_names" else v)
            for k,v in generation.items() if k!="output"}})
```

`custom_names` is **not** dropped wholesale — its `sha256` (the actual byte content of the
custom-names file used) still participates, so a genuinely different custom-names file still
changes identity. Only `selection` (which branch resolved it, and from where) is provenance,
not content, and is dropped. The `canonical_json(expected) != canonical_json(report)`
provenance comparison in `PreparedCartridges.__init__` (unrelated to `content_identity`) still
compares the full, location-sensitive record and was not touched.

### TDD (round 2)

Fixture rebuilt to the real producer shape: `custom_names` is now
`{"sha256": ..., "selection": {"kind": "explicit", "path": <abs path>}}`, matching
`upr_runner.py:56-66,134-140` exactly, with the path configurable per call.

- `test_content_identity_ignores_the_custom_names_selection_path_even_with_output_too` — same
  bytes/settings/seed, **both** `output` and `custom_names.selection.path` differ between the
  two run directories → equal digest. **Red** against the round-1 fix (assertion failure,
  different digests: `90a77dff...` vs `e2022b69...`); confirmed first, then fixed, then green.
- `test_content_identity_ignores_the_absolute_output_path` — kept, still passes.
- `test_content_identity_changes_with_custom_names_sha256` — new: only the custom-names byte
  hash changes → different digest (custom_names is not dropped wholesale).
- `test_content_identity_changes_with_settings_sha256` — kept.
- `test_content_identity_changes_with_seed` — kept.
- `test_content_identity_changes_with_output_sha256` — kept.
- `test_content_identity_changes_with_semantic_profile_or_manifest_hash` — kept.

### Pytest output (round 2)

```
$ python -m pytest tests/unit/test_gen1_prepared_cartridges.py -q -o addopts= -p no:cacheprovider
.......
7 passed in 0.29s

$ python -m pytest tests/unit/test_gen1_prepared_cartridges.py tests/unit/test_gen1_prepared_metadata.py tests/unit/test_gen1_companion_admission.py tests/unit/test_manager_prepared_gen1.py -q -o addopts= -p no:cacheprovider
................................................................
64 passed in 2.80s
```

### ruff (round 2)

```
$ ruff check tests/unit/test_gen1_prepared_cartridges.py
All checks passed!
$ ruff check server/gen1_prepared_cartridges.py
```
`server/gen1_prepared_cartridges.py` reports the same 38 pre-existing findings as round 1 (now
at shifted line numbers, still all outside the `content_identity` helper at lines 34-49) —
zero new findings from this round's edit, confirmed by cross-checking every reported line
number against the `git diff` hunks.

## Round 2 diff hash (candidate c868282, superseded by round 3 below)

`sha256(git diff -- server/gen1_prepared_cartridges.py tests/unit/test_gen1_prepared_cartridges.py)`
at the time of the round-2 candidate (cumulative round 1 + round 2 against the pre-FT-3
baseline at HEAD 8467394):

```
5fd4a06db55dfe0367b14f54d8f2f268375946dfa2160e9b8123cd2a06cb3b62
```

## Round 3 — REJECT again: exclusion-list whack-a-mole, one more leak

Independent review of candidate c868282 found a third leak of the same shape: `generation`
still contained `log_sha256` — the hash of the raw UPR log, and that log embeds
`"Time elapsed: <ms>"` (`Randomizer.java:690`, passed through unmodified by
`tools/upr/SLinkRandomizer.java:58-65`). Two runs of the identical recipe (same ROM, settings,
seed, custom names) that merely took a different number of milliseconds inside UPR produced a
different `log_sha256`, and therefore a different `content_profile_hash` — the same class of
bug as rounds 1 and 2, just in a field neither round's exclusion list had reached yet.

Rounds 1 and 2 both fixed the specific leak found and missed the next one, because both
subtracted known-bad keys from the full record (`{k: v for k, v in generation.items() if k !=
...}`) instead of asserting what belongs. Per the coordinator's round-3 direction, this round
replaces the exclusion list with an explicit **allowlist** of content-bearing keys
(`CONTENT_IDENTITY_GENERATION_KEYS`, `server/gen1_prepared_cartridges.py:48-50`):

```python
CONTENT_IDENTITY_GENERATION_KEYS = frozenset({
    "schema", "source_commit", "generation", "jar_sha256", "bridge_sha256", "settings_sha256",
    "gen1_policy_sha256", "source_sha256", "source_sha1", "seed", "effective_settings_string",
    "output_sha256", "output_sha1", "size", "custom_names"})
```

`content_identity` now filters `generation` through membership in this set (and still projects
`custom_names` down to `{"sha256": ...}`, per round 2):

```python
def content_identity(semantic_profile, manifest_sha256, generation):
    return digest({"semantic_profile": semantic_profile, "manifest_sha256": manifest_sha256,
        "generation": {k: ({"sha256": v["sha256"]} if k == "custom_names" else v)
            for k, v in generation.items() if k in CONTENT_IDENTITY_GENERATION_KEYS}})
```

Excluded keys, documented in a comment directly above the constant
(`server/gen1_prepared_cartridges.py:34-47`), and why each is provenance/location rather than
content:

- **`output`** — absolute path to this run's own `randomized.gbc` (`run_pinned`,
  `upr_runner.py:140`). (Round 1.)
- **`custom_names.selection`** — the absolute path (or jar member) `selected_custom_names()`
  resolved (`upr_runner.py:56-66,138`), present even with no Manager override; `custom_names`
  keeps its content hash (`sha256`), only `selection` is dropped. (Round 2.)
- **`log_sha256`** — hash of the raw UPR log, which embeds wall-clock "Time elapsed"; not a
  property of the produced cartridge. (Round 3, this round.)
- **`status`** — `upr_runner.py`'s own pipeline-stage marker
  (`"produced_requires_semantic_scan"`), constant for every run at this point in the pipeline;
  never varies between two runs of the same recipe, but it is location/provenance-shaped
  metadata about the record itself rather than cartridge content, so it is excluded on the
  same principle rather than left in by accident.

Because this is now an allowlist, a key `upr_runner.py` adds to the generation record in the
future does **not** silently enter `content_identity` (and does not silently get excluded
either) — it requires a conscious decision to add it to `CONTENT_IDENTITY_GENERATION_KEYS`,
which `test_content_identity_generation_allowlist_is_exact` pins so that decision cannot be
skipped unnoticed.

The `canonical_json(expected) != canonical_json(report)` provenance comparison in
`PreparedCartridges.__init__` (unrelated to `content_identity`) still compares the full,
unfiltered record and was not touched in any round.

### TDD (round 3)

- `test_content_identity_ignores_log_sha256` — same recipe, only `log_sha256` differs → equal
  digest. **Red** against the round-2 fix (module still lacked `CONTENT_IDENTITY_GENERATION_KEYS`
  at all, so this and the allowlist test both started as `ImportError`); after adding the
  constant and switching the comprehension to the allowlist, both pass and the log-only
  difference stops changing the digest.
- `test_content_identity_generation_allowlist_is_exact` — asserts the exact 15-key allowlist
  set, so a future producer-record change to `upr_runner.py` must touch this test (and the
  allowlist) on purpose.
- All prior tests kept and still pass: `test_content_identity_ignores_the_absolute_output_path`,
  `test_content_identity_ignores_the_custom_names_selection_path_even_with_output_too`,
  `test_content_identity_changes_with_custom_names_sha256`,
  `test_content_identity_changes_with_settings_sha256`,
  `test_content_identity_changes_with_seed`,
  `test_content_identity_changes_with_output_sha256`,
  `test_content_identity_changes_with_semantic_profile_or_manifest_hash`.

### Pytest output (round 3)

```
$ python -m pytest tests/unit/test_gen1_prepared_cartridges.py -q -o addopts= -p no:cacheprovider
.........
9 passed in 0.27s

$ python -m pytest tests/unit/test_gen1_prepared_cartridges.py tests/unit/test_gen1_prepared_metadata.py tests/unit/test_gen1_companion_admission.py tests/unit/test_manager_prepared_gen1.py -q -o addopts= -p no:cacheprovider
..................................................................
66 passed in 2.68s
```

### ruff (round 3)

```
$ ruff check tests/unit/test_gen1_prepared_cartridges.py
All checks passed!
$ ruff check server/gen1_prepared_cartridges.py
```
`server/gen1_prepared_cartridges.py` reports the same 38 pre-existing findings as rounds 1-2
(shifted line numbers, all outside the allowlist constant and `content_identity` at lines
34-64) — zero new findings, confirmed by cross-checking every reported line number against the
`git diff` hunks.

## Compatibility cutover

This is a breaking identity change for **existing persisted UPR runtimes**: any prepared run
created before this fix — its `gen1_runtime.json` contract, its SQLite journal snapshot, its
Manager registry `cartridges` entry, and any launcher built from the old `contract()` — carries
a `content_profile_hash` computed from an older, leakier formula (round 2: leaks `log_sha256`;
round 1: also leaks `custom_names.selection`; before round 1: also leaks `output`). Reopening
such a run replays `PreparedCartridges(...)` fresh (`server/gen1_run_config.py:47`), which now
recomputes the new, corrected hash; that no longer equals the persisted `value["contract"]`, so
`read_bound_configuration` raises at `server/gen1_run_config.py:50-51` ("prepared Gen1 contract
differs from the committed runtime"), and `PreparedCartridges.validate_contract`
(`server/gen1_prepared_cartridges.py:242-244`) would likewise refuse it wherever else a stored
contract is checked against a re-derived one.

This is accepted, deliberately, for this fresh human session: it affects **only reproduced-UPR
runs that already exist on disk from before this fix** — start a new run and it is fine. There
is no migration path in this change and none is added; a pre-existing run that hits this is not
resumable and must be re-created. Canonical companion runs (`stage_canonical_pair` /
`_init_canonical`) are entirely unaffected — their `content_profile_hash` always comes from the
installed catalog (`companion_profiles()[variant]["content_profile_hash"]`), never from a
run-local `generation` record, so nothing about this fix changes their identity.

## Round 3 diff hash

`sha256(git diff -- server/gen1_prepared_cartridges.py tests/unit/test_gen1_prepared_cartridges.py)`
(cumulative diff against the pre-FT-3 baseline at HEAD 8467394, i.e. all three rounds together):

```
de913a5e5a89b8d6959fa70ae5e8fbcad9e996209aa79367c8826dceed87191e
```
