"""Explicit, bounded binary values for shared JSON state and operation documents."""
import hashlib
import re

ENCODING = "hex-bytes-v1"
MAX_BYTES = 512 * 1024  # one MiB hex string, matching the shared JSON bound


class BinaryCodecError(ValueError):
    pass


def encode_bytes(value, *, expected_size=None):
    if not isinstance(value, bytes) or len(value) > MAX_BYTES:
        raise BinaryCodecError("a bounded bytes value is required")
    if expected_size is not None and (type(expected_size) is not int or len(value) != expected_size):
        raise BinaryCodecError("binary value differs from the expected layout size")
    return {"encoding": ENCODING, "byte_length": len(value), "hex": value.hex(),
            "sha256": hashlib.sha256(value).hexdigest()}


def decode_bytes(value, *, expected_size=None):
    if not isinstance(value, dict) or set(value) != {"encoding", "byte_length", "hex", "sha256"}:
        raise BinaryCodecError("invalid typed binary value")
    size = value["byte_length"]
    if value["encoding"] != ENCODING or type(size) is not int or not 0 <= size <= MAX_BYTES:
        raise BinaryCodecError("invalid binary encoding or length")
    if not isinstance(value["hex"], str) or len(value["hex"]) != size * 2 or not re.fullmatch(r"[0-9a-f]*", value["hex"]):
        raise BinaryCodecError("binary hex is not canonical or has the wrong length")
    raw = bytes.fromhex(value["hex"])
    encoded = encode_bytes(raw, expected_size=expected_size)
    if encoded != value:
        raise BinaryCodecError("binary checksum or representation differs")
    return raw
