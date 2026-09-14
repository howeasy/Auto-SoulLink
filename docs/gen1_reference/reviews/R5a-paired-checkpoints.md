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

## API

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
  <checkpoint_id>/
    a.sav  b.sav                # exact bytes supplied by the caller
    rules.json                  # caller-serialized rules/memorial snapshot, stored verbatim
    identity.json                # caller-supplied known_keys/identity export, stored verbatim
    manifest.json                # written LAST
```

`manifest.json`: `schema` ("slink-paired-checkpoint-v1"), `checkpoint_id`, `created_at`,
`players.{a,b}.{witness, save_sha256, save_size}`, `rules_sha256`, `identity_sha256`,
`contract_fingerprint`, `source_fingerprint`, `predecessor` (previous checkpoint_id or null).

## Invariants

- **Immutability.** Once a checkpoint directory is renamed into place, nothing under it is
  ever rewritten. A new capture always creates a new `checkpoint_id`.
- **Atomic publication.** `capture()` writes into a temp directory, fsyncs and reads back
  every file (including `manifest.json`, written last), `os.replace`s the temp dir to its
  final name, and only then `os.replace`s the `CURRENT` pointer. Any exception before the
  `CURRENT` update removes whatever partial directory exists (temp or renamed-but-uncommitted)
  and leaves the previous `CURRENT` untouched — verified by `test_failure_before_current_update_leaves_current_untouched`,
  which makes the first `os.replace` fail and asserts exactly one checkpoint directory survives.
- **Read-time integrity.** `load()` recomputes the sha256 of every file against the manifest's
  declared hash, and — only when the checkpoint is the current one — the manifest's own hash
  against `CURRENT`. Any mismatch raises `CheckpointError` naming the offending file
  (`test_tampered_save_file_makes_load_raise_naming_it`).
- **Refusals are explicit, not silent coercion**: missing player, wrong/empty save size,
  a witness missing `frame`/`digest`/`projection`/`index`/`operation_id`, empty rules/identity
  bytes, and both witnesses sharing `operation_id` **and** `index` (one batch can't witness two
  players' saves) unless the caller passes `allow_same_batch=True`.
- **No game branching.** Nothing in the module names a game; `save_size` is the only
  per-game knob, defaulted to Gen 1's 0x8000 SaveRAM size.

## What R5b must supply

- Raw save bytes per player (exact archived file, any size the store is constructed with).
- A `witness` dict per player shaped like `gen1_engine_signal_runtime.SAVE_WITNESS` records:
  `frame`, `digest` (the existing sha256-of-uppercase-hex-CartRAM-text convention — this
  module treats it as an opaque string and never recomputes it), `projection`, `index`,
  `operation_id`.
- `rules` / `identity` as already-serialized bytes (e.g. from `StagedSoulLinkState.document()`
  or whatever public serialization the shared rules state exposes — this module does not
  invent a second format).
- `contract_fingerprint` / `source_fingerprint` as opaque strings for its own provenance needs.
- The Manager action that decides *when* to capture and wires it to two real save files.

## Test output

```
$ python -m pytest tests/unit/test_paired_save_checkpoints.py -q -o addopts= -p no:cacheprovider
...............                                                          [100%]
15 passed in 0.36s
```

`ruff check server/paired_save_checkpoints.py tests/unit/test_paired_save_checkpoints.py` — all checks passed.

## sha256

```
fb56b072648d9df6f3674e1ad5c8b1a52e441f274600ab5ecf2195307e80fb9c  server/paired_save_checkpoints.py
de7b913962bd49897a28c1d09ecfbe05f8d48993a816f493012215fd9d9c2c02  tests/unit/test_paired_save_checkpoints.py
```
