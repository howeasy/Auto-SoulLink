#!/usr/bin/env python3
"""Disclosed SYNTH setup (O-33): a second party mon for the Gen 4 PC/deposit rows.

Every owner save holds one party mon, and Gen 4 refuses to deposit the last one ("You can't
leave the party empty"), so the SETUP is synthesized and everything after it runs natively:
the game deposits party slot 1 into a box and writes the box itself.

    python tools/gen4_synth_save.py party2 --profile hgss --src <battery> --out <path>

The battery is read with ``server/adapters.gen4_codec.py`` (the PYDEC oracle, deliberately
independent of the Lua reader) and a NEW 0x80000 image is written:

* party mon 0 is decrypted, given a deterministic clone PID (sha1 of the source image plus
  the kind, adjusted to the original's ``pid % 25`` nature so the stored tail stats stay
  consistent with a recalculation, and stepped to a non-shiny value for that mon's own
  OTID) plus the nickname ``SYNTH``, then re-encrypted: block checksum recomputed from the
  plaintext blocks and the party tail re-keyed by the new PID (src/pokemon.c:61-62,
  3941-3986);
* the clone is stored at party slot 1 and the party count becomes 2 (general+0x90 holds
  ``{u32 max, u32 count, Pokemon[6]}``; the pack records the FILE-confirmed offsets);
* only the newest bank's general-block footer CRC is recomputed (src/save.c:309-528,
  include/save.h:33-39), so the game loads the same bank with the same save counter: the PC
  block, the other bank and every other byte are copied verbatim.

Nothing is written until the new image re-decodes through the codec as two mons whose clone
keeps the original's species, level, OTID and nature, has a distinct identity, is not shiny
and has a plausible tail.  A sidecar ``<out>.synth.json`` records both hashes, so an oracle
can tell a synthesized setup from a played save.  Exit codes: 0 written, 1 refused/failed,
2 source absent.  ``pt`` is refused: the Platinum profile is bind-only here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script from tools/
    sys.path.insert(0, str(ROOT))

from server.adapters import gen4_codec as codec  # noqa: E402

SCHEMA = "gen4-synth-v1"
KIND = "party2"
NOTE = "SYNTH setup: second party mon cloned for a native deposit test"
NICKNAME = "SYNTH"
SIDECAR_SUFFIX = ".synth.json"
BIZHAWK_ROOT = Path("E:/Howard/Bizhawk")  # the owner's live emulator saves are never an output
PROFILES = ("hgss", "hge")
WRITTEN, REFUSED, ABSENT = 0, 1, 2
CLONE_SLOT = 1


class Refusal(Exception):
    """A condition under which no file is written; the message names what would change."""


def _norm(path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _under(path, root) -> bool:
    return Path(path).is_relative_to(root)


def check_paths(src, out) -> None:
    """Refuse an output that would overwrite the source or land in the emulator's save tree."""
    s, o = _norm(src), _norm(out)
    if s == o:
        raise Refusal(f"--out is --src ({out}); the source save is read-only")
    if _under(Path(o), Path(_norm(BIZHAWK_ROOT))):
        raise Refusal(f"--out is under the BizHawk save root {BIZHAWK_ROOT}")


def _shiny(pid: int, otid: int) -> bool:
    """The gen4_codec decode rule (src/pokemon.c: FindShiny): PID and OTID must disagree by >= 8."""
    return ((otid >> 16) ^ (otid & 0xFFFF) ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8


def synth_pid(src_sha1: str, template_pid: int, otid: int) -> int:
    """A deterministic clone PID: same nature (pid % 25) as the template, never shiny, never equal."""
    seed = int.from_bytes(hashlib.sha1(f"{KIND}:{src_sha1}".encode()).digest()[:4], "little")
    pid = (seed + (template_pid % 25) - (seed % 25)) % (1 << 32)  # +25 keeps the nature
    for _ in range(256):
        if pid != template_pid and not _shiny(pid, otid):
            return pid
        pid = (pid + 25) % (1 << 32)
    raise Refusal("no_clone_pid", "no non-shiny clone PID in 256 candidates")


def _clone(raw: bytes, profile, pid: int) -> bytes:
    """Decrypted party record -> re-encrypted clone with ``pid`` and the SYNTH nickname.

    Every other field is carried over verbatim, so the record's stored tail (level, HP and
    the six stats) stays the record the game itself wrote.
    """
    plain = bytearray(codec.decrypt_party(raw))
    struct.pack_into("<I", plain, 0, pid)
    nick = codec.HEADER_SIZE + 2 * codec.BLOCK_SIZE  # block C holds 11 u16 nickname words
    struct.pack_into("<11H", plain, nick, *codec.encode_name(NICKNAME, 11))
    # hasNickname is bit 31 of the block-B IV word; without it the game shows the OT name.
    ivs_at = codec.HEADER_SIZE + codec.BLOCK_SIZE + 0x10
    struct.pack_into("<I", plain, ivs_at, struct.unpack_from("<I", plain, ivs_at)[0] | 1 << 31)
    return codec.encrypt_party(bytes(plain))  # recomputes the block checksum, re-keys the tail


def _same_mon(a: dict, b: dict) -> bool:
    return (a["species"], a["level"], a["otid"], a["nature"], a["max_hp"], a["stats"]) == (
        b["species"], b["level"], b["otid"], b["nature"], b["max_hp"], b["stats"])


def build_party2(image: bytes, profile) -> tuple[bytes, dict]:
    """Source image -> (new image, disclosure row). Refuses rather than writing a bad image."""
    save = codec.parse_save(image, profile)
    p = save.profile
    mons = save.party()
    if len(mons) > 1:
        raise Refusal("party_not_single", f"party count is {len(mons)}; this tool only adds a second mon")
    if not mons:
        raise Refusal("no_party", "the source party is empty; there is nothing to clone")
    template = mons[0]
    src_sha1 = hashlib.sha1(image).hexdigest()
    pid = synth_pid(src_sha1, template["pid"], template["otid"])

    # A Block's ``size`` includes its footer, but the footer CRC covers only the bytes from
    # the block start up to the footer -- the same span codec._scan_bank validates.
    block = save.blocks[(save.bank, 0)]
    foot = block.start + block.size - p.footer_size
    data = bytearray(image[block.start:foot])
    off = p.party_off + 8  # {u32 max, u32 count} then Pokemon[6]
    record = _clone(bytes(data[off : off + codec.PARTY_MON_SIZE]), p, pid)
    data[off + CLONE_SLOT * codec.PARTY_MON_SIZE : off + (CLONE_SLOT + 1) * codec.PARTY_MON_SIZE] = record
    struct.pack_into("<I", data, p.party_off + 4, CLONE_SLOT + 1)

    out = bytearray(image)
    out[block.start:foot] = data
    fields = list(struct.unpack_from(p.footer_fmt, out, foot))
    fields[p.footer_fields.index("crc")] = codec.crc16_ccitt(bytes(data))
    out[foot : foot + p.footer_size] = struct.pack(p.footer_fmt, *fields)
    _verify(image, bytes(out), p, save.bank)
    row = {
        "schema": SCHEMA,
        "kind": KIND,
        "src_sha1": src_sha1,
        "out_sha1": hashlib.sha1(bytes(out)).hexdigest(),
        "profile": p.name,
        "bank": save.bank,
        "new_pid": pid,
        "otid": template["otid"],
        "note": NOTE,
    }
    return bytes(out), row


def _verify(src: bytes, out: bytes, profile, bank: int) -> None:
    """Re-decode the image that is about to be written; anything short of the contract refuses."""
    save = codec.parse_save(out, profile)
    mons = save.party()
    if save.bank != bank or len(mons) != 2:
        raise Refusal("verify", f"bank {save.bank} / {len(mons)} mons, expected bank {bank} / 2 mons")
    clone, template = mons[1], mons[0]
    if not (clone["tail_plausible"] and not clone["shiny"] and clone["key"] != template["key"]):
        raise Refusal("verify", f"clone decodes as {clone['key']} shiny={clone['shiny']}")
    if not _same_mon(clone, template):
        raise Refusal("verify", "the clone is not the template mon with the same species/level/OTID")
    if clone["nickname"] != NICKNAME:
        raise Refusal("verify", f"clone nickname is {clone['nickname']!r}")
    other = 1 - bank
    if out[other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE] != src[
        other * codec.BANK_SIZE : (other + 1) * codec.BANK_SIZE
    ]:
        raise Refusal("verify", "the other bank was modified")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disclosed SYNTH setup for Gen 4 battery saves (O-33).")
    sub = parser.add_subparsers(dest="command", required=True)
    party2 = sub.add_parser("party2", help="clone party mon 0 into party slot 1")
    party2.add_argument("--profile", required=True, choices=PROFILES)
    party2.add_argument("--src", required=True, type=Path, help="battery save to read (never modified)")
    party2.add_argument("--out", required=True, type=Path, help="new battery save to write")
    args = parser.parse_args(argv)
    try:
        try:
            image = args.src.read_bytes()
        except FileNotFoundError:
            print(f"absent source save: {args.src}", file=sys.stderr)
            return ABSENT
        except OSError as exc:
            raise Refusal(f"source unreadable: {exc}") from None
        check_paths(args.src, args.out)
        out_image, row = build_party2(image, args.profile)
        try:
            args.out.write_bytes(out_image)
        except OSError as exc:
            raise Refusal(f"could not write {args.out}: {exc}") from None
        sidecar = Path(str(args.out) + SIDECAR_SUFFIX)
        sidecar.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    except (Refusal, codec.Gen4CodecError) as exc:
        print(f"refuse: {exc}", file=sys.stderr)
        return REFUSED
    print(json.dumps(row, indent=2, sort_keys=True))
    return WRITTEN


if __name__ == "__main__":
    sys.exit(main())
