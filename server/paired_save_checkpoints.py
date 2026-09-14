"""Game-neutral envelope for a "complete paired save checkpoint".

Two humans play one Soul Link run across two cartridges. When an emulator crashes past a
player's last in-game save, the only sound recovery is: both players roll back to the last
checkpoint where BOTH saves and the shared rules state were captured together. A checkpoint
is captured prospectively — both players save in-game, then something (a later card, R5b,
supplies the Gen 1 witness seam and the Manager action) archives both save files plus one
immutable rules/memorial snapshot through `capture()`.

This module owns only the envelope: immutable on-disk storage, atomic publication, and
integrity verification on read. It has no opinion on which game produced the bytes, how a
save was witnessed, or how rules are serialized — the caller supplies raw bytes and an
opaque `witness` record per player (the shape used elsewhere: frame, digest, projection,
index, operation_id — see server/gen1_engine_signal_runtime.py's SAVE_WITNESS component).
A caller may also attach `provenance` (a small JSON object of plain scalars — e.g. a
transaction id, predecessor run id, or journal revision) that rides through hash-verified
but is never interpreted here.

Trust chain: each manifest records its predecessor as {checkpoint_id, manifest_sha256} —
not a bare id — so an older, superseded manifest can't be edited undetected. `load()`,
`current()` and `history()` all verify a checkpoint's manifest hash against the digest its
*successor* recorded (CURRENT plays that role for the newest checkpoint), walking the chain
from CURRENT rather than trusting a bare file on disk.

Durability: `capture()` guarantees atomic visibility (a reader never sees a half-written
checkpoint) and cleanup of partial writes on any exception raised before CURRENT is
published. It is NOT a host-crash-durability guarantee — the CURRENT pointer's temp file is
flushed and fsynced before its rename, but this module never fsyncs a directory, so a power
loss at exactly the wrong instant could still lose a rename the OS had not yet committed.
Concurrent `capture()` calls (same process or not, provided they share `directory`) are
serialized by an exclusive-create lock file, held from the predecessor read through the
CURRENT publish; a crash while holding it leaves a stale lock file needing manual removal.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "slink-paired-checkpoint-v1"
PLAYERS = ("a", "b")
WITNESS_KEYS = frozenset({"frame", "digest", "projection", "index", "operation_id"})
TOP_LEVEL_KEYS = frozenset({"schema", "checkpoint_id", "created_at", "players", "rules_sha256",
                            "identity_sha256", "contract_fingerprint", "source_fingerprint",
                            "predecessor", "provenance"})
HEX64 = re.compile(r"[0-9a-f]{64}")
LOCK_NAME = ".capture.lock"
LOCK_TIMEOUT = 5.0
LOCK_POLL = 0.01
PROVENANCE_MAX_KEYS = 32
PROVENANCE_MAX_STR = 512


class CheckpointError(Exception):
    """A checkpoint could not be captured, verified, or read back intact."""


@dataclass(frozen=True)
class Checkpoint:
    manifest: dict
    _files: dict  # {"a": bytes, "b": bytes, "rules": bytes, "identity": bytes}

    def save_bytes(self, player):
        return self._files[player]

    def rules_bytes(self):
        return self._files["rules"]

    def identity_bytes(self):
        return self._files["identity"]

    def provenance(self):
        return self.manifest["provenance"]


@contextlib.contextmanager
def _capture_lock(path, timeout, poll):
    """Exclusive-create lock file: O_EXCL is honored identically on POSIX and Windows,
    the boring cross-platform choice over fcntl/msvcrt. ponytail: a crash while held
    leaves a stale lock (see module docstring on durability) — not solved here."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise CheckpointError("timed out waiting for the capture lock") from None
            time.sleep(poll)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)


def _nonneg_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _nonempty_str(value):
    return isinstance(value, str) and bool(value)


def _validate_witness_values(component, witness):
    for key in ("frame", "index"):
        if not _nonneg_int(witness[key]):
            raise CheckpointError(f"{component} witness {key} must be a nonnegative int")
    for key in ("digest", "projection", "operation_id"):
        if not _nonempty_str(witness[key]):
            raise CheckpointError(f"{component} witness {key} must be a non-empty string")


def _validate_provenance(component, provenance):
    """R5b/N3 bind a transaction id, predecessor run id, or journal revision here. Kept to
    plain JSON scalars and a bounded size — it is stored and hash-verified like everything
    else, never interpreted."""
    if not isinstance(provenance, dict) or len(provenance) > PROVENANCE_MAX_KEYS:
        raise CheckpointError(f"{component} provenance must be a JSON object with at most {PROVENANCE_MAX_KEYS} keys")
    for key, value in provenance.items():
        if not _nonempty_str(key):
            raise CheckpointError(f"{component} provenance keys must be non-empty strings")
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise CheckpointError(f"{component} provenance value for {key!r} must be str, int, or null")
        if isinstance(value, str) and len(value) > PROVENANCE_MAX_STR:
            raise CheckpointError(f"{component} provenance value for {key!r} exceeds {PROVENANCE_MAX_STR} characters")


class PairedCheckpointStore:
    """Immutable checkpoints under `<directory>/checkpoints/<checkpoint_id>/`."""

    def __init__(self, directory, save_size=0x8000):
        self._checkpoints_dir = Path(directory) / "checkpoints"
        self._current_path = self._checkpoints_dir / "CURRENT"
        self.save_size = save_size

    def capture(self, players, rules, identity, contract_fingerprint, source_fingerprint,
                *, allow_same_batch=False, provenance=None):
        """Write one new immutable checkpoint and, only once it verifies, make it CURRENT."""
        witnesses = self._validate_players(players, allow_same_batch)
        if not isinstance(rules, bytes) or not rules:
            raise CheckpointError("rules snapshot must be non-empty bytes")
        if not isinstance(identity, bytes) or not identity:
            raise CheckpointError("identity export must be non-empty bytes")
        if not _nonempty_str(contract_fingerprint):
            raise CheckpointError("contract_fingerprint must be a non-empty string")
        if not _nonempty_str(source_fingerprint):
            raise CheckpointError("source_fingerprint must be a non-empty string")
        provenance = {} if provenance is None else provenance
        _validate_provenance("capture", provenance)
        self._checkpoints_dir.mkdir(parents=True, exist_ok=True)
        with _capture_lock(str(self._checkpoints_dir / LOCK_NAME), timeout=LOCK_TIMEOUT, poll=LOCK_POLL):
            # Held from here through the CURRENT publish below: the predecessor read and
            # the publish must never straddle another capture's, or CURRENT can end up
            # naming a checkpoint a losing writer's cleanup then deletes (the R5a-round-1 bug).
            predecessor = self._read_current_pointer()
            checkpoint_id = secrets.token_hex(16)
            temp_dir = self._checkpoints_dir / f".tmp-{checkpoint_id}"
            final_dir = self._checkpoints_dir / checkpoint_id
            temp_dir.mkdir()
            renamed = False
            try:
                manifest = {
                    "schema": SCHEMA, "checkpoint_id": checkpoint_id,
                    "created_at": datetime.now(UTC).isoformat(),
                    "players": {
                        player: {
                            "witness": {key: witnesses[player][key] for key in WITNESS_KEYS},
                            "save_sha256": self._write_verified(temp_dir / f"{player}.sav", players[player]["save"]),
                            "save_size": len(players[player]["save"]),
                        } for player in PLAYERS
                    },
                    "rules_sha256": self._write_verified(temp_dir / "rules.json", rules),
                    "identity_sha256": self._write_verified(temp_dir / "identity.json", identity),
                    "contract_fingerprint": contract_fingerprint,
                    "source_fingerprint": source_fingerprint,
                    "predecessor": predecessor,
                    "provenance": dict(provenance),
                }
                manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
                manifest_sha256 = self._write_verified(temp_dir / "manifest.json", manifest_bytes)
                os.replace(temp_dir, final_dir)
                renamed = True
                self._write_current(checkpoint_id, manifest_sha256)
            except Exception:
                # Whichever half-finished thing exists (temp dir, or a promoted-but-
                # unpublished final dir) is discarded; CURRENT still names the old one.
                shutil.rmtree(final_dir if renamed else temp_dir, ignore_errors=True)
                raise
            return manifest

    def current(self):
        """The newest manifest, with its archived a.sav/b.sav/rules/identity bytes verified
        the same way `load()` verifies them (not just the manifest's own hash)."""
        for checkpoint_id, manifest, _bytes, error in self._walk_chain():
            if error:
                raise CheckpointError(f"CURRENT checkpoint {checkpoint_id} failed verification: {error}")
            self._checkpoint_from_manifest(manifest)  # raises naming the file if any archive is bad
            return manifest
        return None

    def load(self, checkpoint_id):
        """Verify checkpoint_id's manifest against the digest its successor (or CURRENT,
        for the newest) recorded, then verify every archived file against that manifest."""
        self._safe_checkpoint_dir(checkpoint_id)
        for candidate, manifest, _bytes, error in self._walk_chain():
            if error:
                raise CheckpointError(f"checkpoint {candidate} failed verification: {error}")
            if candidate == checkpoint_id:
                return self._checkpoint_from_manifest(manifest)
        raise CheckpointError(f"checkpoint {checkpoint_id} is not reachable from CURRENT")

    def history(self):
        """Newest first, following the CURRENT-anchored, hash-verified predecessor chain.
        Metadata-only: it verifies every manifest's own bytes but, unlike `load()`/`current()`,
        does NOT open or hash a.sav/b.sav/rules.json/identity.json — a manifest can be trusted
        from this list alone, an archived file cannot. A broken link (missing/tampered/
        malformed manifest, or a cycle) stops the walk and is recorded as an error entry
        instead of raised — a torn history is data, not a crash."""
        results = []
        for checkpoint_id, manifest, _bytes, error in self._walk_chain():
            if error:
                results.append({"checkpoint_id": checkpoint_id, "error": error})
                break
            results.append(manifest)
        return results

    # -- internals --------------------------------------------------------------

    def _walk_chain(self):
        """Yield (checkpoint_id, manifest, manifest_bytes, error) from CURRENT backward.
        Reads the CURRENT pointer exactly once; every subsequent hop is verified against
        the digest carried by the hop before it, never by re-reading a moving pointer."""
        pointer = self._read_current_pointer()
        if pointer is None:
            return
        trusted_id, trusted_hash, seen = pointer["checkpoint_id"], pointer["manifest_sha256"], set()
        while True:
            if trusted_id in seen:
                yield trusted_id, None, None, "predecessor cycle detected"
                return
            seen.add(trusted_id)
            try:
                manifest_bytes, manifest = self._read_manifest_raw(trusted_id)
            except CheckpointError as error:
                yield trusted_id, None, None, str(error)
                return
            if hashlib.sha256(manifest_bytes).hexdigest() != trusted_hash:
                yield trusted_id, None, None, "manifest.json failed hash verification"
                return
            yield trusted_id, manifest, manifest_bytes, None
            predecessor = manifest["predecessor"]
            if predecessor is None:
                return
            trusted_id, trusted_hash = predecessor["checkpoint_id"], predecessor["manifest_sha256"]

    def _validate_players(self, players, allow_same_batch):
        if not isinstance(players, dict) or set(players) != {"a", "b"}:
            raise CheckpointError("both players are required")
        witnesses = {}
        for player in PLAYERS:
            entry = players[player]
            if not isinstance(entry, dict) or "save" not in entry or "witness" not in entry:
                raise CheckpointError(f"player {player} is missing save or witness")
            save = entry["save"]
            if not isinstance(save, (bytes, bytearray)) or len(save) != self.save_size:
                raise CheckpointError(f"player {player} save must be exactly {self.save_size} bytes")
            witness = entry["witness"]
            if not isinstance(witness, dict) or not set(witness) >= WITNESS_KEYS:
                raise CheckpointError(f"player {player} witness is missing required keys")
            _validate_witness_values(f"player {player}", witness)
            witnesses[player] = witness
        if not allow_same_batch and witnesses["a"]["operation_id"] == witnesses["b"]["operation_id"] \
                and witnesses["a"]["index"] == witnesses["b"]["index"]:
            # ponytail: a duplicate-reference heuristic, NOT proof the two saves are actually
            # paired — it only refuses the degenerate "one batch witnessed both players" shape.
            # R5b (the real witness seam) owns pairing.
            raise CheckpointError("both players witnessed the same batch; pass allow_same_batch=True to override")
        return witnesses

    def _safe_checkpoint_dir(self, checkpoint_id):
        if not isinstance(checkpoint_id, str) or not checkpoint_id or checkpoint_id in (".", "..") \
                or "/" in checkpoint_id or "\\" in checkpoint_id:
            raise CheckpointError(f"invalid checkpoint id: {checkpoint_id!r}")
        base = self._checkpoints_dir.resolve()
        directory = (base / checkpoint_id).resolve()
        if directory.parent != base:
            raise CheckpointError(f"invalid checkpoint id: {checkpoint_id!r}")
        return base / checkpoint_id

    def _read_manifest_raw(self, checkpoint_id):
        checkpoint_dir = self._safe_checkpoint_dir(checkpoint_id)
        manifest_path = checkpoint_dir / "manifest.json"
        try:
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
        except (OSError, ValueError) as error:
            raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json could not be read: {error}") from error
        try:
            self._validate_manifest_shape(checkpoint_id, manifest)
        except (KeyError, TypeError, AttributeError) as error:
            raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json has an invalid shape: {error}") from error
        return manifest_bytes, manifest

    def _validate_manifest_shape(self, checkpoint_id, manifest):
        if not isinstance(manifest, dict) or set(manifest) != TOP_LEVEL_KEYS:
            raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json is missing or has extra top-level fields")
        if manifest["schema"] != SCHEMA or manifest["checkpoint_id"] != checkpoint_id:
            raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json has an invalid schema or self-id")
        if not _nonempty_str(manifest.get("created_at")):
            raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json is missing created_at")
        players = manifest.get("players")
        if not isinstance(players, dict) or set(players) != {"a", "b"}:
            raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json has invalid players")
        for player in PLAYERS:
            entry = players[player]
            if not isinstance(entry, dict) or set(entry) != {"witness", "save_sha256", "save_size"}:
                raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json player {player} entry is invalid")
            if entry["save_size"] != self.save_size:
                raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json player {player} save_size does not match the configured size")
            if not isinstance(entry["save_sha256"], str) or not HEX64.fullmatch(entry["save_sha256"]):
                raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json player {player} save_sha256 is invalid")
            witness = entry["witness"]
            if not isinstance(witness, dict) or set(witness) != WITNESS_KEYS:
                raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json player {player} witness is invalid")
            _validate_witness_values(f"checkpoint {checkpoint_id} player {player}", witness)
        for field in ("rules_sha256", "identity_sha256"):
            value = manifest.get(field)
            if not isinstance(value, str) or not HEX64.fullmatch(value):
                raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json {field} is invalid")
        for field in ("contract_fingerprint", "source_fingerprint"):
            if not _nonempty_str(manifest.get(field)):
                raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json {field} must be a non-empty string")
        predecessor = manifest["predecessor"]
        if predecessor is not None and (not isinstance(predecessor, dict) or set(predecessor) != {"checkpoint_id", "manifest_sha256"}
                or not _nonempty_str(predecessor["checkpoint_id"])
                or not isinstance(predecessor["manifest_sha256"], str) or not HEX64.fullmatch(predecessor["manifest_sha256"])):
            raise CheckpointError(f"checkpoint {checkpoint_id} manifest.json predecessor is invalid")
        _validate_provenance(f"checkpoint {checkpoint_id} manifest.json", manifest["provenance"])

    def _checkpoint_from_manifest(self, manifest):
        checkpoint_dir = self._safe_checkpoint_dir(manifest["checkpoint_id"])
        files = {}
        for player in PLAYERS:
            entry = manifest["players"][player]
            data = self._read_bytes(checkpoint_dir / f"{player}.sav")
            if len(data) != entry["save_size"] or hashlib.sha256(data).hexdigest() != entry["save_sha256"]:
                raise CheckpointError(f"{player}.sav failed hash verification")
            files[player] = data
        for name, key in (("rules.json", "rules_sha256"), ("identity.json", "identity_sha256")):
            data = self._read_bytes(checkpoint_dir / name)
            if not data or hashlib.sha256(data).hexdigest() != manifest[key]:
                raise CheckpointError(f"{name} failed hash verification")
            files[name.split(".")[0]] = data
        return Checkpoint(manifest=manifest, _files=files)

    def _write_verified(self, path, data):
        with open(path, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if path.read_bytes() != data:
            raise CheckpointError(f"{path.name} failed read-back verification")
        return hashlib.sha256(data).hexdigest()

    def _read_bytes(self, path):
        try:
            return path.read_bytes()
        except OSError as error:
            raise CheckpointError(f"{path.name} could not be read: {error}") from error

    def _read_current_pointer(self):
        if not self._current_path.exists():
            return None
        try:
            pointer = json.loads(self._current_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CheckpointError(f"CURRENT could not be read: {error}") from error
        if not isinstance(pointer, dict) or set(pointer) != {"checkpoint_id", "manifest_sha256"} \
                or not _nonempty_str(pointer["checkpoint_id"]) \
                or not isinstance(pointer["manifest_sha256"], str) or not HEX64.fullmatch(pointer["manifest_sha256"]):
            raise CheckpointError("CURRENT has an invalid pointer")
        return pointer

    def _write_current(self, checkpoint_id, manifest_sha256):
        # A unique name per attempt: belt-and-suspenders alongside the capture lock, so a
        # stale temp file left by an aborted capture can never collide with this one's.
        temp_path = self._checkpoints_dir / f".CURRENT.tmp-{secrets.token_hex(8)}"
        payload = json.dumps({"checkpoint_id": checkpoint_id, "manifest_sha256": manifest_sha256}).encode("utf-8")
        try:
            with open(temp_path, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())  # best-effort: see module docstring on durability
            os.replace(temp_path, self._current_path)
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(temp_path)
            raise
