# R5a — paired save checkpoint envelope

## Purpose

Two humans play one Soul Link run across two cartridges. When an emulator crashes past a
player's last in-game save, the only sound recovery is: both players roll back to the last
checkpoint where **both** saves and the shared rules state were captured **together**. A
checkpoint is captured prospectively (both players save in-game, then something archives
both save files + one immutable rules snapshot). This card builds the game-neutral envelope
only — capture/validate/publish/select — with no Gen 1 specifics beyond a default save size.

The witness seam that produces `players[x]["witness"]` and the Manager action that calls
`capture()` are R5b, not this card.

## Round history

- **Round 1** (`ad6583a`) rejected: an unlocked race between concurrent captures could leave
  `CURRENT` pointing at a checkpoint its own losing writer had just deleted; superseded
  manifests carried no trusted hash anchor; `load()` under-validated manifest shape; JSON/OS
  errors could leak past `CheckpointError`; the same-batch witness guard was overstated as
  proof of pairing.
- **Round 2** (`fd870b7`) accepted the lock and hash-chain designs, but independent review
  found two more read-path defects the round-2 test suite hadn't reached, plus two small
  robustness/API gaps. *(Round 2's report claimed "all seven findings are fixed" — that
  claim was premature; two of the seven fixes had a gap in their own edge cases, which round
  3 below closes.)*
- **Round 3** (this revision) fixes:
  1. `_validate_manifest_shape` checked individual fields with `.get()`, so a manifest
     missing `predecessor` entirely (not `null` — absent) passed shape validation, and
     `_walk_chain` then raised a raw `KeyError` reading `manifest["predecessor"]` instead of
     a `CheckpointError`/broken-entry.
  2. `current()` returned the newest manifest straight from the chain walk without verifying
     `a.sav`/`b.sav`/`rules.json`/`identity.json` against it — only `load()` did that.
  3. `_write_current`'s per-attempt temp file was never cleaned up if the write or the
     `os.replace` into `CURRENT` failed.
  4. R5b/N3 need somewhere to bind a transaction id, predecessor run id, or journal revision;
     added an optional `provenance` parameter.

## API

`server/paired_save_checkpoints.py`:

- `PairedCheckpointStore(directory, save_size=0x8000)`
- `.capture(players, rules, identity, contract_fingerprint, source_fingerprint, *, allow_same_batch=False, provenance=None) -> manifest dict`
- `.current() -> manifest dict | None` — verifies the newest checkpoint's archived files, same as `load()`
- `.load(checkpoint_id) -> Checkpoint` — `.save_bytes(player)`, `.rules_bytes()`, `.identity_bytes()`, `.provenance()`
- `.history() -> list[manifest]` — newest first, **metadata-only** (see Invariants)
- `CheckpointError` — every refusal and every integrity failure

On-disk layout under `<directory>/checkpoints/`:

```
checkpoints/
  CURRENT                       # {"checkpoint_id", "manifest_sha256"}
  .capture.lock                 # present only while a capture() holds it
  <checkpoint_id>/
    a.sav  b.sav                # exact bytes supplied by the caller
    rules.json                  # caller-serialized rules/memorial snapshot, stored verbatim
    identity.json                # caller-supplied known_keys/identity export, stored verbatim
    manifest.json                # written LAST
```

`manifest.json` top-level keys (all required, exact set — a manifest with any key missing or
extra fails shape validation): `schema` ("slink-paired-checkpoint-v1"), `checkpoint_id`,
`created_at`, `players.{a,b}.{witness, save_sha256, save_size}`, `rules_sha256`,
`identity_sha256`, `contract_fingerprint`, `source_fingerprint`, `predecessor`
(`{checkpoint_id, manifest_sha256}` or `null`), `provenance` (a JSON object of plain
scalars, `{}` by default).

## Invariants

- **Immutability.** Once a checkpoint directory is renamed into place, nothing under it is
  ever rewritten. A new capture always creates a new `checkpoint_id`.
- **Serialized publication.** `capture()` acquires an exclusive-create lock file
  (`checkpoints/.capture.lock`, `O_CREAT|O_EXCL`, bounded retry/timeout) before reading the
  predecessor pointer, and holds it through the `CURRENT` publish. `O_EXCL` is honored
  identically by POSIX and Windows, so this needed no `fcntl`/`msvcrt` split.
- **Atomic, verified publication.** Within the lock: write into a temp directory, fsync and
  read back every file (manifest last), `os.replace` the temp dir to its final name, and
  only then `os.replace` the `CURRENT` pointer (itself flushed+fsynced before its own
  replace, and its own temp file removed if that replace fails). Any exception before the
  `CURRENT` update removes whichever partial thing exists — the temp dir, or a
  promoted-but-unpublished final dir — and leaves the previous `CURRENT` untouched.
- **Hash-anchored history, not bare pointers.** Every manifest's `predecessor` carries the
  hash its author observed for that predecessor at capture time. `current()`, `load()` and
  `history()` all walk backward from a *single* read of `CURRENT`, verifying each hop's
  manifest bytes against the digest the hop *in front of it* recorded (`CURRENT` plays that
  role for the newest checkpoint) — so a superseded manifest edited after the fact is
  detected, and no caller re-reads a moving `CURRENT` mid-verification.
- **Manifest shape validation checks the complete top-level key set, not individual fields
  in isolation.** `_validate_manifest_shape` first requires `set(manifest) == TOP_LEVEL_KEYS`
  (round 3, finding 1) — a field that is entirely absent (as opposed to present and `null`)
  is now rejected at the shape-validation boundary as a `CheckpointError`/broken-entry,
  never surfacing as a raw `KeyError` from deeper code. Beyond that: schema, self-id, exact
  per-player key sets, `save_size` against both the configured size and the archived file's
  actual length, hex-digest shapes, non-empty fingerprints, witness value types
  (`frame`/`index` non-negative int; `digest`/`projection`/`operation_id` non-empty str), and
  `provenance` shape (below).
- **`load()` and `current()` verify archived file bytes; `history()` does not.**
  `load(checkpoint_id)` and, as of round 3, `current()` both call the same
  `_checkpoint_from_manifest` — every archived `a.sav`/`b.sav`/`rules.json`/`identity.json`
  is read and checked (length **and** hash) against the manifest before either returns.
  `history()` is metadata-only by design (its docstring says so): it verifies every
  manifest's own hash-chain integrity but never opens the archived files, so a corrupt
  `a.sav` does not break `history()` — only `load()`/`current()` would catch that.
- **Refusals are explicit.** Missing player, wrong/empty save size, a witness missing
  required keys or carrying wrong-typed values, empty rules/identity bytes, non-string/empty
  fingerprints, a path-unsafe `checkpoint_id`, malformed `provenance`, and both witnesses
  sharing `operation_id` + `index` (unless `allow_same_batch=True`) all raise
  `CheckpointError` with a message naming what failed.
- **Errors never leak past the module's own exception type.** Malformed JSON, `OSError`, and
  malformed-shape `KeyError`/`TypeError` from `CURRENT` or any manifest all surface as
  `CheckpointError`. `history()` reports a broken link (missing file, tampered hash,
  malformed shape — including a missing top-level field — or a detected predecessor cycle)
  as a trailing `{"checkpoint_id", "error"}` entry instead of raising; `load()`/`current()`
  raise for the same conditions since they promise one specific checkpoint back, not a
  best-effort list.
- **`provenance` rides through hash-verified, never interpreted.** A JSON object of
  `str -> (str | int | None)`, at most 32 keys, string values at most 512 characters. It is
  part of the manifest bytes like every other field, so tampering it is caught the same way
  tampering `source_fingerprint` is. `WITNESS_KEYS` was not widened for this — provenance is
  its own top-level field, unrelated to a player's witness record.
- **No game branching.** Nothing in the module names a game; `save_size` is the only
  per-game knob, defaulted to Gen 1's 0x8000 SaveRAM size.

## Durability (documented, not claimed beyond this)

`capture()` guarantees atomic visibility (a reader never sees a half-written checkpoint) and
cleanup of partial writes on any exception caught before `CURRENT` is published. It is **not**
a host-crash-durability guarantee: the `CURRENT` pointer's temp file is flushed and fsynced
before its `os.replace`, but the module never fsyncs a directory, so a power loss at exactly
the wrong instant could still lose a rename the OS had not yet committed to disk.

## Operational limits

Corrected here because round 2's report implied more than the code actually guarantees:

- **A stale `.capture.lock` is not auto-stolen.** If a writer crashes while holding it, every
  future `capture()` against that `directory` times out after `LOCK_TIMEOUT` (5s) with a
  `CheckpointError`. Recovery is manual: the operator confirms no writer is actually still
  running against that store, then removes only `checkpoints/.capture.lock`. There is no
  staleness heuristic (e.g. lock age, PID liveness) — adding one is future work, not present
  behavior.
- **A corrupt `CURRENT` fails closed.** Malformed JSON, a missing/extra key, or a
  non-hex-shaped `manifest_sha256` in `CURRENT` itself raises `CheckpointError` from
  `current()`/`load()`/`history()`'s very first step (`history()` reports it as the single
  broken entry rather than an empty list, since the root of the chain is unreadable). Nothing
  in this module repairs `CURRENT` automatically.
- **The `checkpoint_id` policy is "safe path component fully contained under `checkpoints/`",
  not a strict 32-hex-character format.** `capture()` always mints one with `secrets.token_hex(16)`
  (32 hex chars), but `_safe_checkpoint_dir` only rejects empty strings, `.`/`..`, any path
  separator, and any resolved path that escapes `checkpoints/` — it does not require hex, and
  nothing downstream assumes the id is hex-shaped.
- **Orphaned temp files are cleaned up only on a *caught* exception inside `capture()`/
  `_write_current`.** A hard crash (process killed, host power loss) between creating a temp
  file/directory and the matching cleanup can still leave one behind; nothing here scans for
  or reaps orphans left by a crash rather than a caught exception. That is consistent with
  the Durability section above — this module targets atomic visibility, not crash cleanup.
- **`load()` of an older checkpoint is O(depth from `CURRENT`), with no paging.** Reaching a
  checkpoint N hops behind `CURRENT` reads and hashes N manifests. `history()` has no
  cursor/limit either; it always walks to the end of the reachable chain (or the first
  broken link). Fine for the expected checkpoint cadence (occasional, human-paced saves);
  would need paging if checkpoints became frequent.

## The same-batch witness guard is a heuristic, not proof of pairing

`capture()` refuses two witnesses that share both `operation_id` and `index` by default
(`allow_same_batch=True` overrides it). This only catches the degenerate shape "one witness
batch was reused for both players' saves" — it is not evidence the two saves are actually the
paired ones a human intended. Real pairing is R5b's job (the witness seam that produces these
records in the first place).

## What R5b must supply

- Raw save bytes per player (exact archived file, any size the store is constructed with).
- A `witness` dict per player shaped like `gen1_engine_signal_runtime.SAVE_WITNESS` records:
  `frame`, `digest` (the existing sha256-of-uppercase-hex-CartRAM-text convention — this
  module treats it as an opaque string and never recomputes it), `projection`, `index`,
  `operation_id`.
- `rules` / `identity` as already-serialized bytes (e.g. from `StagedSoulLinkState.document()`
  or whatever public serialization the shared rules state exposes — this module does not
  invent a second format).
- `contract_fingerprint` / `source_fingerprint` as opaque non-empty strings for its own
  provenance needs.
- Optionally `provenance` (a transaction id, predecessor run id, journal revision, etc., as
  plain JSON scalars) if R5b/N3 wants that bound into the checkpoint and hash-verified.
- The Manager action that decides *when* to capture, wires it to two real save files, and
  establishes actual pairing (this module's same-batch check is not that).

## Disposition table (round 3)

| Finding | Fix | Test(s) |
|---|---|---|
| 1. `_validate_manifest_shape` used `.get("predecessor")`; a manifest missing the field entirely passed shape validation and `_walk_chain` raised a raw `KeyError` | `_validate_manifest_shape` now requires `set(manifest) == TOP_LEVEL_KEYS` before touching any individual field | `test_history_reports_missing_predecessor_field_as_broken_entry_not_keyerror` |
| 2. `current()` never verified `a.sav`/`b.sav`/`rules`/`identity` bytes, only `load()` did | `current()` now calls `_checkpoint_from_manifest` on the newest manifest before returning it; `history()`'s docstring now says explicitly it is metadata-only | `test_current_validates_archived_save_bytes`, `test_history_does_not_validate_archived_bytes` |
| 3. `_write_current`'s unique temp file was never removed if its write or `os.replace` failed | wrapped in `try/except Exception: remove the temp file; raise` | `test_write_current_failure_leaves_no_orphan_temp_file` |
| 4. R5b/N3 need a place to bind a transaction id / predecessor run id / journal revision | optional `provenance` parameter on `capture()` (default `{}`), stored verbatim under `manifest["provenance"]`, hash-bound, validated as `str -> (str\|int\|None)` with ≤32 keys and ≤512-char string values, exposed as `Checkpoint.provenance()`; `WITNESS_KEYS` untouched | `test_capture_with_provenance_round_trips_through_load`, `test_capture_defaults_provenance_to_empty_object`, `test_tampering_provenance_makes_load_raise`, `test_capture_refuses_malformed_provenance` (5 cases) |
| 5. Report overclaimed durability/ID-format/cleanup guarantees | Added the Operational limits section above; corrected the round-2 "all seven findings fixed" claim | n/a (documentation) |

### Round 1 + 2 disposition (unchanged, kept for history)

| Finding | Fix | Test(s) |
|---|---|---|
| Concurrent captures could leave `CURRENT` pointing at a checkpoint its own losing writer deletes | `checkpoints/.capture.lock` held from the predecessor read through the `CURRENT` publish; unique per-attempt `CURRENT.tmp-<token>` name | `test_concurrent_captures_never_leave_current_dangling`, `test_capture_times_out_when_lock_is_held` |
| Historical manifests had no trusted hash anchor once superseded | `predecessor` is `{checkpoint_id, manifest_sha256}`; `_walk_chain()` verifies each hop against the digest its successor recorded | `test_tampered_older_manifest_makes_load_raise_naming_manifest`, `test_load_of_current_checkpoint_detects_tamper_too` |
| `load()` failed open on shape (lying `save_size` + matching hash on a truncated file, `None` fingerprint, path-unsafe id) | full shape validation + length-and-hash file checks + `_safe_checkpoint_dir` | `test_load_rejects_archived_file_shorter_than_declared_size_even_with_matching_hash`, `test_capture_refuses_none_contract_fingerprint`, `test_load_refuses_path_traversal_checkpoint_id` |
| JSON/OSError/KeyError from `CURRENT` or a manifest could leak past `CheckpointError`; cycles uncaught | `(OSError, ValueError)` / `(KeyError, TypeError, AttributeError)` wrapping; `seen` set in `_walk_chain` | `test_malformed_current_pointer_raises_checkpoint_error`, `test_history_reports_truncated_manifest_as_broken_entry_not_raise`, `test_history_detects_predecessor_cycle` |
| Failure windows during capture could dangle `CURRENT` or leave partial dirs | try/except removes the temp dir or promoted-but-unpublished final dir on any exception | `test_capture_failure_after_b_sav_before_manifest_leaves_no_partial_dir`, `test_capture_failure_promoting_directory_leaves_current_and_dirs_clean`, `test_capture_failure_publishing_current_removes_promoted_directory` |
| Durability overclaimed | Docstring states atomic-visibility + caught-exception cleanup only | n/a (documentation) |
| Same-batch guard described as proof of pairing | Reworded as a duplicate-reference heuristic | n/a (documentation) |

## Test output

```
$ python -m pytest tests/unit/test_paired_save_checkpoints.py -q -o addopts= -p no:cacheprovider
........................................                                 [100%]
40 passed in 0.78s
```

`ruff check server/paired_save_checkpoints.py tests/unit/test_paired_save_checkpoints.py` — all checks passed.

## sha256

```
bd52a4ae49741a43843a57dc1595e75f2e18fd8d41ed8a0737f688d071b9e48c  server/paired_save_checkpoints.py
ad8375153e02ce650a96cc5e00be41f0109770b6db8e3e191912b36ff2d6a585  tests/unit/test_paired_save_checkpoints.py
```
