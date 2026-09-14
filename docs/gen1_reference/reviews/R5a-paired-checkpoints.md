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

## Round 2

Round 1 (candidate `ad6583a`) was rejected on independent review: an unlocked race between
concurrent captures could leave `CURRENT` pointing at a checkpoint its own losing writer had
just deleted; superseded manifests carried no trusted hash anchor once superseded, so an
older one could be edited undetected; `load()` under-validated manifest shape (a lying
`save_size` with a hash that matched a truncated file would pass); JSON/OS errors from
`CURRENT` or a manifest could leak past `CheckpointError`; and the same-batch witness guard
was overstated as proof of pairing rather than a duplicate-reference heuristic. All seven
findings are fixed below; see the disposition table.

## API (unchanged from round 1)

`server/paired_save_checkpoints.py`:

- `PairedCheckpointStore(directory, save_size=0x8000)`
- `.capture(players, rules, identity, contract_fingerprint, source_fingerprint, *, allow_same_batch=False) -> manifest dict`
- `.current() -> manifest dict | None`
- `.load(checkpoint_id) -> Checkpoint` — `.save_bytes(player)`, `.rules_bytes()`, `.identity_bytes()`
- `.history() -> list[manifest]` — newest first
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

`manifest.json`: `schema` ("slink-paired-checkpoint-v1"), `checkpoint_id`, `created_at`,
`players.{a,b}.{witness, save_sha256, save_size}`, `rules_sha256`, `identity_sha256`,
`contract_fingerprint`, `source_fingerprint`, and — **changed in round 2** — `predecessor`
as `{checkpoint_id, manifest_sha256}` (or `null`), not a bare id.

## Invariants

- **Immutability.** Once a checkpoint directory is renamed into place, nothing under it is
  ever rewritten. A new capture always creates a new `checkpoint_id`.
- **Serialized publication.** `capture()` acquires an exclusive-create lock file
  (`checkpoints/.capture.lock`, `O_CREAT|O_EXCL`, bounded retry/timeout) before reading the
  predecessor pointer, and holds it through the `CURRENT` publish. `O_EXCL` is honored
  identically by POSIX and Windows, so this needed no `fcntl`/`msvcrt` split. A crash while
  holding it leaves a stale lock file (documented, not solved — see Durability below).
- **Atomic, verified publication.** Within the lock: write into a temp directory, fsync and
  read back every file (manifest last), `os.replace` the temp dir to its final name, and
  only then `os.replace` the `CURRENT` pointer (itself flushed+fsynced before its own
  replace). Any exception before the `CURRENT` update removes whichever partial thing exists
  — the temp dir, or a promoted-but-unpublished final dir — and leaves the previous `CURRENT`
  untouched.
- **Hash-anchored history, not bare pointers.** Every manifest's `predecessor` carries the
  hash its author observed for that predecessor at capture time. `current()`, `load()` and
  `history()` all walk backward from a *single* read of `CURRENT`, verifying each hop's
  manifest bytes against the digest the hop *in front of it* recorded (`CURRENT` plays that
  role for the newest checkpoint) — so a superseded manifest edited after the fact is
  detected, and no caller re-reads a moving `CURRENT` mid-verification.
- **Read-time shape validation, not just hash matching.** `load()`/the chain walk check
  schema, self-id, exact key sets, `save_size` against both the configured size and the
  archived file's actual length, hex-digest shapes, non-empty fingerprints, and witness value
  types (`frame`/`index` non-negative int; `digest`/`projection`/`operation_id` non-empty
  str) — a hash that happens to match a truncated or lied-about file no longer passes.
- **Refusals are explicit.** Missing player, wrong/empty save size, a witness missing
  required keys or carrying wrong-typed values, empty rules/identity bytes, non-string/empty
  fingerprints, a path-unsafe `checkpoint_id`, and both witnesses sharing `operation_id` +
  `index` (unless `allow_same_batch=True`) all raise `CheckpointError` with a message naming
  what failed.
- **Errors never leak past the module's own exception type.** Malformed JSON, `OSError`, and
  malformed-shape `KeyError`/`TypeError` from `CURRENT` or any manifest all surface as
  `CheckpointError`. `history()` reports a broken link (missing file, tampered hash,
  malformed shape, or a detected predecessor cycle) as a trailing `{"checkpoint_id", "error"}`
  entry instead of raising; `load()`/`current()` raise for the same conditions since they
  promise one specific checkpoint back, not a best-effort list.
- **No game branching.** Nothing in the module names a game; `save_size` is the only
  per-game knob, defaulted to Gen 1's 0x8000 SaveRAM size.

## Durability (documented, not claimed beyond this)

`capture()` guarantees atomic visibility (a reader never sees a half-written checkpoint) and
cleanup of partial writes on any exception caught before `CURRENT` is published. It is **not**
a host-crash-durability guarantee: the `CURRENT` pointer's temp file is flushed and fsynced
before its `os.replace`, but the module never fsyncs a directory, so a power loss at exactly
the wrong instant could still lose a rename the OS had not yet committed to disk. This is
stated in the module docstring, not just here.

## The same-batch witness guard is a heuristic, not proof of pairing

`capture()` refuses two witnesses that share both `operation_id` and `index` by default
(`allow_same_batch=True` overrides it). This only catches the degenerate shape "one witness
batch was reused for both players' saves" — it is not evidence the two saves are actually the
paired ones a human intended. Real pairing is R5b's job (the witness seam that produces these
records in the first place); this module's docstring and the check's own comment now say so
explicitly instead of implying proof.

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
- The Manager action that decides *when* to capture, wires it to two real save files, and
  establishes actual pairing (this module's same-batch check is not that).

## Disposition table

| Finding | Fix | Test(s) |
|---|---|---|
| 1. Concurrent captures can leave `CURRENT` pointing at a checkpoint its own losing writer deletes | `checkpoints/.capture.lock` (`O_CREAT\|O_EXCL`, bounded retry/timeout) held from the predecessor read through the `CURRENT` publish; unique per-attempt `CURRENT.tmp-<token>` name | `test_concurrent_captures_never_leave_current_dangling`, `test_capture_times_out_when_lock_is_held` |
| 2. Historical manifests have no trusted hash anchor once superseded | `predecessor` is now `{checkpoint_id, manifest_sha256}`; `_walk_chain()` reads `CURRENT` once and verifies each hop against the digest its successor recorded | `test_tampered_older_manifest_makes_load_raise_naming_manifest`, `test_load_of_current_checkpoint_detects_tamper_too`, `test_second_capture_supersedes_and_records_predecessor` |
| 3. `load()` fails open on shape (lying `save_size` + matching hash on a truncated file, `None` fingerprint, path-unsafe id) | `_validate_manifest_shape` (schema/self-id/key-sets/hex shapes/witness value types) + `_checkpoint_from_manifest` (length **and** hash check) + `_safe_checkpoint_dir` (id format + resolved-path containment) + capture-time fingerprint type checks | `test_load_rejects_archived_file_shorter_than_declared_size_even_with_matching_hash`, `test_capture_refuses_none_contract_fingerprint`, `test_load_refuses_path_traversal_checkpoint_id`, plus the witness-value-type rows of `test_capture_refuses_malformed_players` |
| 4. JSON/OSError/KeyError from `CURRENT` or a manifest can leak past `CheckpointError`; `history()` must not raise on a broken/malformed entry; cycles must be caught | `_read_current_pointer`/`_read_manifest_raw` catch `(OSError, ValueError)`; shape validation catches `(KeyError, TypeError, AttributeError)`; `_walk_chain` tracks `seen` ids and yields a cycle error instead of looping | `test_malformed_current_pointer_raises_checkpoint_error`, `test_history_reports_truncated_manifest_as_broken_entry_not_raise`, `test_history_detects_predecessor_cycle` |
| 5. Failure windows (after b.sav/before manifest; directory promotion; `CURRENT` publish after promotion) must leave the old `CURRENT` readable with no dangling id | Existing try/except around the locked section removes the temp dir or the promoted-but-unpublished final dir on any exception (chose **removal**, not "ignored by history/current") | `test_capture_failure_after_b_sav_before_manifest_leaves_no_partial_dir`, `test_capture_failure_promoting_directory_leaves_current_and_dirs_clean`, `test_capture_failure_publishing_current_removes_promoted_directory` |
| 6. Durability overclaimed | Module docstring + this doc state the guarantee precisely: atomic visibility + caught-exception cleanup, pointer fsync is best-effort, no directory fsync | n/a (documentation; `_write_current` now does flush+fsync before its `os.replace`) |
| 7. Same-batch guard described as proof of pairing | Reworded as a duplicate-reference heuristic in both the code comment and this doc; R5b owns real pairing | n/a (documentation) |

## Test output

```
$ python -m pytest tests/unit/test_paired_save_checkpoints.py -q -o addopts= -p no:cacheprovider
............................                                             [100%]
28 passed in 0.66s
```

`ruff check server/paired_save_checkpoints.py tests/unit/test_paired_save_checkpoints.py` — all checks passed.

## sha256

```
b21019606d1a3c4dac8d2c534f576f588a2df2f0c8a10f505876319cf6fcb8ff  server/paired_save_checkpoints.py
ac1d54bbb42984ae0d43c8338e0fe7ea239ca4452b4604627c6a6ca768718e40  tests/unit/test_paired_save_checkpoints.py
```
