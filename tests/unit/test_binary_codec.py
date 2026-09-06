import copy
import json

import pytest

from server.binary_codec import MAX_BYTES, BinaryCodecError, decode_bytes, encode_bytes


@pytest.mark.parametrize("size", [0, 66, 100, 136, 220, 236, 32768])
def test_binary_values_roundtrip_through_real_json_with_explicit_layout_size(size):
    raw = bytes(i % 256 for i in range(size))
    encoded = encode_bytes(raw, expected_size=size)
    assert decode_bytes(json.loads(json.dumps(encoded)), expected_size=size) == raw


@pytest.mark.parametrize("field,value", [("encoding", "unknown"), ("byte_length", True), ("byte_length", 2),
                                       ("hex", "00aaBB"), ("hex", "00 aa bb"), ("sha256", "0" * 64)])
def test_wrong_representation_checksum_or_length_is_rejected(field, value):
    encoded = encode_bytes(bytes.fromhex("00aabb"))
    changed = copy.deepcopy(encoded)
    changed[field] = value
    with pytest.raises(BinaryCodecError):
        decode_bytes(changed)


def test_layout_mismatch_and_implicit_string_conversion_are_rejected():
    with pytest.raises(BinaryCodecError):
        encode_bytes("00")
    with pytest.raises(BinaryCodecError):
        encode_bytes(b"a", expected_size=2)
    with pytest.raises(BinaryCodecError):
        decode_bytes(encode_bytes(b"ab"), expected_size=1)
    with pytest.raises(BinaryCodecError):
        encode_bytes(b"a" * (MAX_BYTES + 1))
