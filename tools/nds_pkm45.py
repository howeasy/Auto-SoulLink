"""Independent Python oracle for the shared Gen 4 / Gen 5 stored-Pokemon cipher.

Mirrors the API of lua/nds/pkm45_crypto.lua (the in-game side) without sharing code or tables:
the 24 block orders are GENERATED from itertools.permutations, not copied, so a typo in either
side's literal table shows up as a disagreement. The PK4 and PK5 stored records are the same
0x88-byte cipher (cartridge-verified for BW/B2W2, see tests/unit/test_nds_pkm45.py).

Record = u32 PID | u16 flags | u16 checksum | 0x80 bytes (blocks A-D, shuffled, XOR-encrypted by an
LCRNG seeded with the checksum) [| party tail, XOR-encrypted, seeded with the PID]. The party length is
a parameter (Gen 4 0xEC, Gen 5 0xDC). Plain form: header kept, blocks in logical order, tail decrypted.
Errors raise :class:`PkmError` with the Lua module's reason tokens.

Flags word (+0x04): bit 2 (bad egg) is a legitimate stored state, reported as ``info["bad_egg"]`` and preserved
by encrypt. Bits 0-1 are the game's own "decrypted" marker (docs/gen5/research/rom_code_anchors.md:66,214:
Decrypt sets them and XORs without reordering the blocks, Encrypt clears them); a record carrying them is
refused ("locked") unless ``allow_decrypted=True``, which takes body and tail as already XOR-plain (blocks
still shuffled), reports ``info["decrypted"]`` and ``info["checksum_ok"]`` and does not enforce the checksum.
encrypt always clears bits 0-1.
"""

from __future__ import annotations

import itertools
import struct

STORED_SIZE = 0x88
HEADER = 8
BLOCK = 0x20
LCG_MUL, LCG_ADD = 0x41C64E6D, 0x6073
PARTY_LEN_GEN4, PARTY_LEN_GEN5 = 0xEC, 0xDC


class PkmError(ValueError):
    """``reason`` is one of size | locked | checksum | party_len."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _build_rows() -> tuple[tuple[int, ...], ...]:
    """Row r = lexicographic r-th permutation of ABCD as the STORED sequence; the entry for logical
    block L is its stored byte offset (position in the sequence x 0x20). 24 rows; the games use 32
    (rows 24-31 repeat 0-7)."""
    rows = []
    for seq in itertools.permutations(range(4)):
        rows.append(tuple(seq.index(logical) * BLOCK for logical in range(4)))
    return tuple(rows)


_ROWS = _build_rows()
# 32-row form exactly as the cartridge stores it (128 bytes, one byte per entry).
GAME_TABLE = bytes(b for r in range(32) for b in _ROWS[r % 24])


def shuffle_row(pid: int) -> int:
    return (pid >> 13) & 31


def block_order(pid: int) -> tuple[int, int, int, int]:
    """Stored byte offset (inside the 0x80 body) of logical block A, B, C, D."""
    return _ROWS[shuffle_row(pid) % 24]


def checksum(body: bytes) -> int:
    if len(body) % 2:
        raise PkmError("size")  # same as the Lua module: an odd length is refused, not truncated
    return sum(struct.unpack(f"<{len(body) // 2}H", body)) & 0xFFFF


def _xor(data: bytes, seed: int) -> bytes:
    out = bytearray(len(data))
    for i in range(0, len(data), 2):
        seed = (seed * LCG_MUL + LCG_ADD) & 0xFFFFFFFF
        out[i : i + 2] = struct.pack("<H", struct.unpack_from("<H", data, i)[0] ^ (seed >> 16))
    return bytes(out)


def decrypt_stored(raw: bytes, allow_decrypted: bool = False) -> tuple[bytes, dict]:
    if len(raw) != STORED_SIZE:
        raise PkmError("size")
    pid, flags, stored_sum = struct.unpack_from("<IHH", raw, 0)
    decrypted = bool(flags & 0x3)
    if decrypted and not allow_decrypted:
        raise PkmError("locked")
    body = raw[HEADER:] if decrypted else _xor(raw[HEADER:], stored_sum)
    checksum_ok = checksum(body) == stored_sum
    if not checksum_ok and not decrypted:
        raise PkmError("checksum")
    order = block_order(pid)
    logical = b"".join(body[o : o + BLOCK] for o in order)
    info = {
        "pid": pid, "flags": flags, "checksum": stored_sum, "checksum_ok": checksum_ok,
        "row": shuffle_row(pid), "order": list(order), "bad_egg": bool(flags & 0x4), "decrypted": decrypted,
    }
    return raw[:HEADER] + logical, info


def encrypt_stored(plain: bytes) -> bytes:
    if len(plain) != STORED_SIZE:
        raise PkmError("size")
    pid, flags = struct.unpack_from("<IH", plain, 0)
    stored = bytearray(4 * BLOCK)
    for which, o in enumerate(block_order(pid)):
        stored[o : o + BLOCK] = plain[HEADER + which * BLOCK : HEADER + (which + 1) * BLOCK]
    csum = checksum(bytes(stored))
    return struct.pack("<IHH", pid, flags & 0xFFFC, csum) + _xor(bytes(stored), csum)


def _check_party_len(party_len: int) -> None:
    if not (isinstance(party_len, int) and party_len > STORED_SIZE and (party_len - STORED_SIZE) % 2 == 0):
        raise PkmError("party_len")


def decrypt_party(raw: bytes, party_len: int, allow_decrypted: bool = False) -> tuple[bytes, dict]:
    _check_party_len(party_len)
    if len(raw) != party_len:
        raise PkmError("size")
    head, info = decrypt_stored(raw[:STORED_SIZE], allow_decrypted)
    tail = raw[STORED_SIZE:] if info["decrypted"] else _xor(raw[STORED_SIZE:], info["pid"])
    return head + tail, info


def encrypt_party(plain: bytes, party_len: int) -> bytes:
    _check_party_len(party_len)
    if len(plain) != party_len:
        raise PkmError("size")
    pid = struct.unpack_from("<I", plain, 0)[0]
    return encrypt_stored(plain[:STORED_SIZE]) + _xor(plain[STORED_SIZE:], pid)


# Identity (plain record only): PID header word, TID/SID at +0x0C/+0x0E of logical block A.
def pid(plain: bytes) -> int:
    return struct.unpack_from("<I", plain, 0)[0]


def tid(plain: bytes) -> int:
    return struct.unpack_from("<H", plain, 0x0C)[0]


def sid(plain: bytes) -> int:
    return struct.unpack_from("<H", plain, 0x0E)[0]


def otid(plain: bytes) -> int:
    return struct.unpack_from("<I", plain, 0x0C)[0]


def mon_key(plain: bytes) -> str:
    return f"{pid(plain):08X}:{otid(plain):08X}"
