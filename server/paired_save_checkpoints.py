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
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "slink-paired-checkpoint-v1"
PLAYERS = ("a", "b")
WITNESS_KEYS = frozenset({"frame", "digest", "projection", "index", "operation_id"})


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


class PairedCheckpointStore:
    """Immutable checkpoints under `<directory>/checkpoints/<checkpoint_id>/`."""

    def __init__(self, directory, save_size=0x8000):
        self._checkpoints_dir = Path(directory) / "checkpoints"
        self._current_path = self._checkpoints_dir / "CURRENT"
        self.save_size = save_size

    def capture(self, players, rules, identity, contract_fingerprint, source_fingerprint,
                *, allow_same_batch=False):
        """Write one new immutable checkpoint and, only once it verifies, make it CURRENT."""
        witnesses = self._validate_players(players, allow_same_batch)
        if not isinstance(rules, bytes) or not rules:
            raise CheckpointError("rules snapshot must be non-empty bytes")
        if not isinstance(identity, bytes) or not identity:
            raise CheckpointError("identity export must be non-empty bytes")
        self._checkpoints_dir.mkdir(parents=True, exist_ok=True)
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
                "predecessor": predecessor["checkpoint_id"] if predecessor else None,
            }
            manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
            manifest_sha256 = self._write_verified(temp_dir / "manifest.json", manifest_bytes)
            os.replace(temp_dir, final_dir)
            renamed = True
            self._write_current(checkpoint_id, manifest_sha256)
        except Exception:
            shutil.rmtree(final_dir if renamed else temp_dir, ignore_errors=True)
            raise
        return manifest

    def current(self):
        pointer = self._read_current_pointer()
        if pointer is None:
            return None
        return self.load(pointer["checkpoint_id"]).manifest

    def load(self, checkpoint_id):
        """Re-validate every file's hash against the manifest before returning it."""
        checkpoint_dir = self._checkpoints_dir / checkpoint_id
        manifest_path = checkpoint_dir / "manifest.json"
        if not manifest_path.is_file():
            raise CheckpointError(f"checkpoint {checkpoint_id} has no manifest.json")
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        files = {}
        for player in PLAYERS:
            data = self._read_bytes(checkpoint_dir / f"{player}.sav")
            if hashlib.sha256(data).hexdigest() != manifest["players"][player]["save_sha256"]:
                raise CheckpointError(f"{player}.sav failed hash verification")
            files[player] = data
        for name, key in (("rules.json", "rules_sha256"), ("identity.json", "identity_sha256")):
            data = self._read_bytes(checkpoint_dir / name)
            if hashlib.sha256(data).hexdigest() != manifest[key]:
                raise CheckpointError(f"{name} failed hash verification")
            files[name.split(".")[0]] = data
        pointer = self._read_current_pointer()
        if pointer is not None and pointer["checkpoint_id"] == checkpoint_id \
                and hashlib.sha256(manifest_bytes).hexdigest() != pointer["manifest_sha256"]:
            raise CheckpointError("manifest.json does not match CURRENT")
        return Checkpoint(manifest=manifest, _files=files)

    def history(self):
        """Newest first, following `predecessor` pointers. A broken link stops the walk
        and records the error instead of raising — a torn history is data, not a crash."""
        pointer = self._read_current_pointer()
        if pointer is None:
            return []
        results, checkpoint_id, seen = [], pointer["checkpoint_id"], set()
        while checkpoint_id is not None and checkpoint_id not in seen:
            seen.add(checkpoint_id)
            try:
                manifest = self.load(checkpoint_id).manifest
            except CheckpointError as error:
                results.append({"checkpoint_id": checkpoint_id, "error": str(error)})
                break
            results.append(manifest)
            checkpoint_id = manifest["predecessor"]
        return results

    # -- internals --------------------------------------------------------------

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
            witnesses[player] = witness
        if not allow_same_batch and witnesses["a"]["operation_id"] == witnesses["b"]["operation_id"] \
                and witnesses["a"]["index"] == witnesses["b"]["index"]:
            raise CheckpointError("both players witnessed the same batch; pass allow_same_batch=True to override")
        return witnesses

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
        return json.loads(self._current_path.read_text(encoding="utf-8"))

    def _write_current(self, checkpoint_id, manifest_sha256):
        temp_path = self._checkpoints_dir / "CURRENT.tmp"
        temp_path.write_text(json.dumps({"checkpoint_id": checkpoint_id, "manifest_sha256": manifest_sha256}),
                              encoding="utf-8")
        os.replace(temp_path, self._current_path)
