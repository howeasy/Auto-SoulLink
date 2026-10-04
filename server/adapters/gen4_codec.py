"""Independent Gen 4 (HeartGold/SoulSilver, hg-engine, Platinum bind-only) record and flash-save oracle.

Hand-derived from pret/pokeheartgold at ``ad7a3afa`` (the checkout at
``E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold``); every citation is a
``file:lines`` range in that tree.  hg-engine facts come from
``docs/gen4/research/hg_engine.md`` (fork ``fc5175764``), the Platinum footer/PC facts
from ``docs/gen4/research/platinum_bind.md`` (pret/pokeplatinum ``c248fb3f``) and the
measurements from ``docs/gen4/research/{pk4_and_save,offline_measurements}.md``.

This module is deliberately independent of ``lua/memory_nds.lua``: it is the Python side
of the ``reads == PYDEC`` differential (PLAN section 5), so it must *agree* with the Lua
decoders without sharing code, constants or bugs with them.  It touches no emulator and
reads no JSON profile; the three variants are the :data:`PROFILES` table below.

Sources, by topic:

* record layout            ``include/pokemon_types_def.h:50-217`` (blocks A-D, party tail)
* checksum                 ``src/pokemon.c:3941-3950`` (u16 sum of the 64 words of the 4 blocks)
* block shuffle            ``src/pokemon.c:3951-3986`` (``GetSubstruct``; table ported verbatim,
                           rows 24-31 duplicate rows 0-7)
* PRNG / XOR               ``src/math_util.c:150-157`` (``seed*0x41C64E6D+0x6073``, out ``seed>>16``)
* seeds                    ``src/pokemon.c:61-62`` (blocks: checksum; party tail: personality)
* ball / met-location      ``src/pokemon.c:818-838``
* locks (plaintext flags)  ``src/pokemon.c:122-143``
* flash banks/footer/CRC   ``src/save.c:309-528``, ``include/save.h:18,33-39``,
                           ``src/math_util.c:159-167`` (CRC-16-CCITT, poly 0x1021, init 0xFFFF,
                           MSB-first -- matched on the owner's real save)
* PC storage               ``include/pokemon_storage_system.h:12-28``
* player profile           ``include/player_data.h:12-32`` (offsets confirmed on a real save)
* text                     ``charmap.txt`` at the pokeheartgold root (Version 2021.08.17)

Decoding preserves raw record values and refuses (never silently decodes) a record whose
checksum fails or that is held in the plaintext "locked" representation.  The party tail has
no checksum, so a wrong-seed tail is flagged through ``tail_plausible`` instead.

Not decoded: the hg-engine nature/IV-override/ability-slot word (block B +0x1A) and the
hidden-ability bit (block B +0x19 bit 6).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Record geometry -- include/pokemon_types_def.h:155-162 (BoxPokemon, 0x88),
# :212-217 (Pokemon, 0xEC), :201-215 (party tail 0x88..0xEB).
# ---------------------------------------------------------------------------
BOX_MON_SIZE = 0x88
PARTY_MON_SIZE = 0xEC
BLOCK_SIZE = 0x20
HEADER_SIZE = 8
TAIL_OFF = 0x88

# src/pokemon.c:3951-3986.  Row = (pid & 0x3E000) >> 13; column = logical block A..D;
# value = byte offset of that block inside the (shuffled) stored data.  Rows 24-31 repeat
# rows 0-7, so a table missing them would raise IndexError for pid bits 13-17 >= 24.
_SHUFFLE = (
    (0x00, 0x20, 0x40, 0x60), (0x00, 0x20, 0x60, 0x40), (0x00, 0x40, 0x20, 0x60),
    (0x00, 0x60, 0x20, 0x40), (0x00, 0x40, 0x60, 0x20), (0x00, 0x60, 0x40, 0x20),
    (0x20, 0x00, 0x40, 0x60), (0x20, 0x00, 0x60, 0x40), (0x40, 0x00, 0x20, 0x60),
    (0x60, 0x00, 0x20, 0x40), (0x40, 0x00, 0x60, 0x20), (0x60, 0x00, 0x40, 0x20),
    (0x20, 0x40, 0x00, 0x60), (0x20, 0x60, 0x00, 0x40), (0x40, 0x20, 0x00, 0x60),
    (0x60, 0x20, 0x00, 0x40), (0x40, 0x60, 0x00, 0x20), (0x60, 0x40, 0x00, 0x20),
    (0x20, 0x40, 0x60, 0x00), (0x20, 0x60, 0x40, 0x00), (0x40, 0x20, 0x60, 0x00),
    (0x60, 0x20, 0x40, 0x00), (0x40, 0x60, 0x20, 0x00), (0x60, 0x40, 0x20, 0x00),
    (0x00, 0x20, 0x40, 0x60), (0x00, 0x20, 0x60, 0x40), (0x00, 0x40, 0x20, 0x60),
    (0x00, 0x60, 0x20, 0x40), (0x00, 0x40, 0x60, 0x20), (0x00, 0x60, 0x40, 0x20),
    (0x20, 0x00, 0x40, 0x60), (0x20, 0x00, 0x60, 0x40),
)

VERSION_HEARTGOLD = 7   # include/config.h:9
VERSION_SOULSILVER = 8  # include/config.h:10
METLOC_FARAWAY_PLACE = 3002  # include/constants/map_sections.h:258
NO_NAME = 0xFFFF  # EOS


class Gen4CodecError(ValueError):
    """A record or save the codec refuses; ``reason`` is a short stable token."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Text -- charmap.txt.  0x0121..0x01E2 is one contiguous run in the file; the string below
# lists it in code order (digits, A-Z, a-z, accents, punctuation, symbols).
# ---------------------------------------------------------------------------
_LATIN_RUN = (
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞß"
    "àáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ"
    "ŒœŞşªº¹²³$¡¿!?,.…·/‘’“”„《》()♂♀+-*#=&~:;♠♣♥♦★◉●■▲◆@♪%☀☁☂☃☺♚♛☹↗↘☽ ⁴₧₦ "
)
_CHARMAP: dict[int, str] = {0x0121 + i: ch for i, ch in enumerate(_LATIN_RUN)}
_CHARMAP.update({0x0001: "　", 0x01E8: "°", 0x01E9: "_", 0x01EA: "＿"})
_CHARMAP_REV = {ch: code for code, ch in _CHARMAP.items()}


def decode_name(words) -> str:
    """Decode u16 Gen 4 text up to the 0xFFFF terminator; unknown codes become ``<$XXXX>``."""
    out = []
    for w in words:
        if w == NO_NAME:
            break
        out.append(_CHARMAP.get(w, f"<${w:04X}>"))
    return "".join(out)


def encode_name(name: str, size: int) -> tuple[int, ...]:
    """Encode to exactly ``size`` u16 words, 0xFFFF terminated and padded (StringFillEOS)."""
    words: list[int] = []
    i = 0
    while i < len(name):
        if name.startswith("<$", i) and name[i + 6 : i + 7] == ">":
            words.append(int(name[i + 2 : i + 6], 16))
            i += 7
            continue
        try:
            words.append(_CHARMAP_REV[name[i]])
        except KeyError:
            raise Gen4CodecError("charmap", f"{name[i]!r} is not in the Gen 4 charmap") from None
        i += 1
    if len(words) >= size:
        raise Gen4CodecError("name_too_long", f"{name!r} does not fit in {size} words")
    return tuple(words) + (NO_NAME,) * (size - len(words))


# ---------------------------------------------------------------------------
# Variants as data.  No game_id branching beyond this table.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Profile:
    name: str
    exp_bits: int                  # exp field width in block A +0x08
    ability_msb: bool              # hge: abilityMSB = bit 31 of block A +0x08
    footer_fmt: str                # struct format of the flash footer (little endian)
    footer_fields: tuple           # names, in order; must include count/size/magic and a slot field
    slot_field: str                # which field says "general" (0) vs "PC" (1)
    party_off: int | None          # general-block offset of Party{maxCount,curCount,mons}
    party_off_verified: bool       # FILE-confirmed on a populated mon?
    box_count: int | None
    boxes_off: int | None          # PC-block offset of box 0
    box_stride: int | None
    cur_box_off: int | None
    modified_off: int | None       # per-box modified flag word; None = no such flag (Pt)
    names_off: int | None
    names_stride: int | None       # bytes per box name (20 u16)
    player_off: int | None         # general-block offset of PlayerProfile
    notes: str = ""
    block_align: int = 0x100       # HGSS PC block starts 0x100-aligned; Pt's starts at 0xCF2C

    @property
    def footer_size(self) -> int:
        return struct.calcsize(self.footer_fmt)

    @property
    def magic_off(self) -> int:
        return 4 * self.footer_fields.index("magic")


SAVE_CHUNK_MAGIC = 0x20060623  # include/save.h:18
_HGSS_FOOTER = ("<IIIHH", ("count", "size", "magic", "slot", "crc"))  # include/save.h:33-39
# include/savedata.h:8-15 in pokeplatinum; layout and the CRC span (size - 0x14) FILE-checked
# on the owner's Pt save 2026-10-01.
_PT_FOOTER = ("<IIIIBxH", ("count", "block_counter", "size", "magic", "slot", "crc"))

PROFILES: dict[str, Profile] = {
    "hgss": Profile(
        "hgss", 32, False, *_HGSS_FOOTER, slot_field="slot",
        party_off=0x90, party_off_verified=True,
        box_count=18, boxes_off=0x0, box_stride=0x1000,        # 30*0x88 + 16 pad
        cur_box_off=0x12000, modified_off=0x12004, names_off=0x12008, names_stride=0x28,
        player_off=0x60,
        notes="pk4_and_save.md; verified on the owner's HG save",
    ),
    "hge": Profile(
        "hge", 21, True, *_HGSS_FOOTER, slot_field="slot",
        party_off=0x90, party_off_verified=True,    # FILE: owner hge save 13d56589 (Cyndaquil)
        box_count=30, boxes_off=0x0, box_stride=0x1000,
        cur_box_off=0x1E000, modified_off=0x1E004,  # PHYSICAL (C1-10): RAM flag set by deposit, cleared after SAVE and on load; the saved battery keeps 1
        names_off=0x1E008, names_stride=0x28,       # names: FILE ("Box 1".."Box 30")
        player_off=0x60,                            # FILE: name/id/money decode at +0x64
        notes="hg_engine.md section 3; offline_measurements.md",
    ),
    "pt": Profile(
        "pt", 32, False, *_PT_FOOTER, slot_field="slot",
        party_off=0x98, party_off_verified=True,    # FILE: owner's Pt save (Turtwig at +0xA0)
        box_count=18, boxes_off=4, box_stride=0xFF0,  # {u32 currentBoxID; boxMons[18][30]}
        cur_box_off=0, modified_off=None,           # no per-box modified flag (fullSaveRequired)
        names_off=None, names_stride=None,
        player_off=0x64,                            # FILE: OT name at +0x68, id at +0x78
        notes="platinum_bind.md; bind-only; party/player/footer FILE-checked on a real Pt save",
        block_align=4,  # FILE: owner's Pt save, PC block at bank+0xCF2C
    ),
}


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def _lcg_xor(data: bytes, seed: int) -> bytes:
    """XOR each u16 with the next LCG output (src/math_util.c:150-157); symmetric."""
    out = bytearray(len(data))
    for i in range(0, len(data), 2):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        out[i : i + 2] = struct.pack("<H", struct.unpack_from("<H", data, i)[0] ^ (seed >> 16))
    return bytes(out)


def checksum(blocks: bytes) -> int:
    """u16 sum of the 64 u16 words of the four blocks (src/pokemon.c:3941-3950)."""
    return sum(struct.unpack(f"<{len(blocks) // 2}H", blocks)) & 0xFFFF


def block_offsets(pid: int) -> tuple[int, int, int, int]:
    """Stored byte offset (inside the 0x80 data) of logical block A, B, C, D."""
    return _SHUFFLE[(pid & 0x3E000) >> 13]


def _unshuffle(stored: bytes, pid: int) -> bytes:
    return b"".join(stored[o : o + BLOCK_SIZE] for o in block_offsets(pid))


def _shuffle(logical: bytes, pid: int) -> bytes:
    stored = bytearray(4 * BLOCK_SIZE)
    for which, o in enumerate(block_offsets(pid)):
        stored[o : o + BLOCK_SIZE] = logical[which * BLOCK_SIZE : (which + 1) * BLOCK_SIZE]
    return bytes(stored)


def decrypt_box(raw: bytes) -> bytes:
    """Encrypted 0x88 record -> plaintext 0x88 with blocks in logical A,B,C,D order.

    Refuses a checksum mismatch and a record stored in the plaintext/locked representation.
    The header (pid, flags, checksum) is kept as stored."""
    if len(raw) != BOX_MON_SIZE:
        raise Gen4CodecError("size", f"expected {BOX_MON_SIZE} bytes, got {len(raw)}")
    pid, flags, stored_sum = struct.unpack_from("<IHH", raw, 0)
    if flags & 0x3:  # partyDecrypted / boxDecrypted (include/pokemon_types_def.h:155-162)
        raise Gen4CodecError("locked", "record is held in the plaintext representation")
    stored = _lcg_xor(raw[HEADER_SIZE:], stored_sum)
    if checksum(stored) != stored_sum:
        raise Gen4CodecError("checksum", f"stored {stored_sum:04X} != computed {checksum(stored):04X}")
    return raw[:HEADER_SIZE] + _unshuffle(stored, pid)


def encrypt_box(plain: bytes) -> bytes:
    """Inverse of :func:`decrypt_box`; recomputes the checksum from the plaintext blocks."""
    if len(plain) != BOX_MON_SIZE:
        raise Gen4CodecError("size", f"expected {BOX_MON_SIZE} bytes, got {len(plain)}")
    pid, flags = struct.unpack_from("<IH", plain, 0)
    stored = _shuffle(plain[HEADER_SIZE:], pid)
    csum = checksum(stored)
    return struct.pack("<IHH", pid, flags, csum) + _lcg_xor(stored, csum)


def decrypt_party(raw: bytes) -> bytes:
    """Encrypted 0xEC party record -> plaintext (blocks logical, tail decrypted with the PID seed)."""
    if len(raw) != PARTY_MON_SIZE:
        raise Gen4CodecError("size", f"expected {PARTY_MON_SIZE} bytes, got {len(raw)}")
    return decrypt_box(raw[:BOX_MON_SIZE]) + _lcg_xor(raw[TAIL_OFF:], struct.unpack_from("<I", raw, 0)[0])


def encrypt_party(plain: bytes) -> bytes:
    if len(plain) != PARTY_MON_SIZE:
        raise Gen4CodecError("size", f"expected {PARTY_MON_SIZE} bytes, got {len(plain)}")
    return encrypt_box(plain[:BOX_MON_SIZE]) + _lcg_xor(plain[TAIL_OFF:], struct.unpack_from("<I", plain, 0)[0])


# ---------------------------------------------------------------------------
# Field decode (plaintext -> dict)
# ---------------------------------------------------------------------------
def mon_key(pid: int, otid: int) -> str:
    return f"{pid:08X}:{otid:08X}"


def _words(plain: bytes, off: int, n: int) -> tuple[int, ...]:
    return struct.unpack_from(f"<{n}H", plain, off)


def decode_plain(plain: bytes, profile: Profile) -> dict:
    """Decode a plaintext record (0x88 or 0xEC) from :func:`decrypt_box`/:func:`decrypt_party`."""
    a, b, c, d = (HEADER_SIZE + i * BLOCK_SIZE for i in range(4))
    pid, flags, csum = struct.unpack_from("<IHH", plain, 0)
    species, item, otid, expword = struct.unpack_from("<HHII", plain, a)
    friendship, ability8, markings, language = struct.unpack_from("<4B", plain, a + 0x0C)
    ability = ability8 | ((expword >> 31) << 8 if profile.ability_msb else 0)
    exp = expword & ((1 << profile.exp_bits) - 1)
    ivword = struct.unpack_from("<I", plain, b + 0x10)[0]
    fateful_gender_form = plain[b + 0x18]
    origin = plain[c + 0x17]
    ball = plain[d + 0x1B]
    if origin in (VERSION_HEARTGOLD, VERSION_SOULSILVER) and plain[d + 0x1E]:
        ball = plain[d + 0x1E]
    egg_dp, met_dp = _words(plain, d + 0x16, 2)
    egg_ph, met_ph = _words(plain, b + 0x1C, 2)
    mon = {
        "pid": pid, "flags": flags, "checksum": csum, "otid": otid,
        "tid": otid & 0xFFFF, "sid": otid >> 16, "key": mon_key(pid, otid),
        "species": species, "held_item": item, "exp": exp, "ability": ability,
        "friendship": friendship, "markings": markings, "language": language,
        "evs": tuple(plain[a + 0x10 : a + 0x16]),
        "moves": _words(plain, b, 4), "pp": tuple(plain[b + 8 : b + 12]),
        "pp_ups": tuple(plain[b + 12 : b + 16]),
        "ivs": tuple((ivword >> (5 * i)) & 31 for i in range(6)),  # hp atk def spe spa spd
        "is_egg": bool(ivword >> 30 & 1), "has_nickname": bool(ivword >> 31 & 1),
        "fateful": fateful_gender_form & 1, "gender": (fateful_gender_form >> 1) & 3,
        "form": fateful_gender_form >> 3,
        "nickname_raw": _words(plain, c, 11), "nickname": decode_name(_words(plain, c, 11)),
        "origin_game": origin, "ot_name_raw": _words(plain, d, 8),
        "ot_name": decode_name(_words(plain, d, 8)),
        "ball": ball, "met_level": plain[d + 0x1C] & 0x7F, "ot_gender": plain[d + 0x1C] >> 7,
        # src/pokemon.c:818-830: the DP location wins unless it is "faraway place"
        "egg_location": egg_dp if egg_dp != METLOC_FARAWAY_PLACE or egg_ph == 0 else egg_ph,
        "met_location": met_dp if met_dp != METLOC_FARAWAY_PLACE or met_ph == 0 else met_ph,
        "nature": pid % 25,
        "shiny": ((otid >> 16) ^ (otid & 0xFFFF) ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8,
    }
    if len(plain) == PARTY_MON_SIZE:
        status, level, capsule, hp, max_hp, atk, dfn, spe, spa, spd = struct.unpack_from(
            "<IBBHHHHHHH", plain, TAIL_OFF)
        mon.update(status=status, level=level, capsule=capsule, hp=hp, max_hp=max_hp,
                   stats=(atk, dfn, spe, spa, spd),
                   # no checksum covers the tail; a wrong seed shows up as nonsense here
                   tail_plausible=1 <= level <= 100 and 0 < max_hp < 1000 and hp <= max_hp)
    return mon


def decode_box_mon(raw: bytes, profile: Profile) -> dict:
    return decode_plain(decrypt_box(raw), profile)


def decode_party_mon(raw: bytes, profile: Profile) -> dict:
    return decode_plain(decrypt_party(raw), profile)


def is_empty_slot(raw: bytes) -> bool:
    """A never-used box slot is all zero; a cleared one decrypts to species 0."""
    if not any(raw[:BOX_MON_SIZE]):
        return True
    try:
        return struct.unpack_from("<H", decrypt_box(raw[:BOX_MON_SIZE]), HEADER_SIZE)[0] == 0
    except Gen4CodecError:
        return False


# ---------------------------------------------------------------------------
# Flash save -- src/save.c:309-528
# ---------------------------------------------------------------------------
SAVE_SIZE = 0x80000
BANK_SIZE = 0x40000


def _crc_table() -> tuple[int, ...]:
    tab = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
        tab.append(c)
    return tuple(tab)


_CRC_TAB = _crc_table()


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    c = init
    for x in data:
        c = ((c << 8) & 0xFFFF) ^ _CRC_TAB[(c >> 8) ^ x]
    return c


def counter_newer(a: int, b: int) -> int:
    """SaveCounterCompare (src/save.c:378-388): +1 if ``a`` is newer, -1 if older, 0 if equal.

    The u32 wrap is special-cased exactly like the game: -1 vs 0 -> -1, 0 vs -1 -> +1."""
    if a == 0xFFFFFFFF and b == 0:
        return -1
    if a == 0 and b == 0xFFFFFFFF:
        return 1
    return (a > b) - (a < b)


@dataclass
class Block:
    """One footer-validated block of a bank (general = slot 0, PC = slot 1)."""

    bank: int
    slot: int
    state: str                  # "valid" | "absent" | "torn" | "duplicate"
    start: int = 0              # absolute file offset
    size: int = 0
    count: int = 0
    reason: str = ""


def _scan_bank(image: bytes, bank: int, profile: Profile) -> dict[int, Block]:
    base = bank * BANK_SIZE
    fsize = profile.footer_size
    valid: dict[int, list[Block]] = {0: [], 1: []}
    torn: dict[int, list[Block]] = {0: [], 1: []}
    magic = struct.pack("<I", SAVE_CHUNK_MAGIC)
    pos = image.find(magic, base, base + BANK_SIZE)
    while pos != -1:
        foot = pos - profile.magic_off
        if pos % 4 == 0 and foot >= base and foot + fsize <= base + BANK_SIZE:
            f = dict(zip(profile.footer_fields, struct.unpack_from(profile.footer_fmt, image, foot),
                         strict=True))
            slot, size = f[profile.slot_field], f["size"]
            start = foot + fsize - size
            if slot in (0, 1) and size > fsize:
                blk = Block(bank, slot, "torn", start, size, f["count"])
                if start < base or (slot == 0 and start != base) or start % profile.block_align:
                    blk.reason = "geometry"
                elif crc16_ccitt(image[start : foot]) != f["crc"]:
                    blk.reason = "crc"
                else:
                    blk.state = "valid"
                (valid if blk.state == "valid" else torn)[slot].append(blk)
        pos = image.find(magic, pos + 1, base + BANK_SIZE)
    out = {}
    for slot in (0, 1):
        if len(valid[slot]) > 1:
            out[slot] = Block(bank, slot, "duplicate", reason="two valid footers claim this slot")
        elif valid[slot]:
            out[slot] = valid[slot][0]
        elif torn[slot]:
            t = torn[slot][0]
            out[slot] = Block(bank, slot, "torn", t.start, t.size, t.count, t.reason)
        else:
            out[slot] = Block(bank, slot, "absent")
    return out


@dataclass
class Gen4Save:
    profile: Profile
    bank: int
    counter: int
    general: bytes
    pc: bytes
    blocks: dict                 # {(bank, slot): Block} for every bank, for diagnostics
    fallback: str = ""           # non-empty: the newest bank was refused and this reason was recorded
    notes: list = field(default_factory=list)

    def party(self) -> list[dict]:
        p = self.profile
        if p.party_off is None:
            raise Gen4CodecError("party_offset_unknown", f"{p.name} has no known party offset")
        maxc, cur = struct.unpack_from("<II", self.general, p.party_off)
        if maxc != 6 or cur > 6:
            raise Gen4CodecError("party_header", f"max={maxc} cur={cur} at general+{p.party_off:#x}")
        base = p.party_off + 8
        return [decode_party_mon(self.general[base + i * PARTY_MON_SIZE : base + (i + 1) * PARTY_MON_SIZE], p)
                for i in range(cur)]

    def pc_meta(self) -> dict:
        p = self.profile
        meta: dict = {"box_count": p.box_count}
        if p.cur_box_off is not None:
            meta["cur_box"] = struct.unpack_from("<I", self.pc, p.cur_box_off)[0]
        if p.modified_off is not None:
            meta["modified"] = struct.unpack_from("<I", self.pc, p.modified_off)[0]
        return meta

    def box_name(self, i: int) -> str | None:
        p = self.profile
        if p.names_off is None:
            return None
        return decode_name(_words(self.pc, p.names_off + i * p.names_stride, 20))

    def boxes(self) -> list[dict]:
        """``[{"name", "mons": {slot: mon}}]`` for every box; empty slots are omitted."""
        p = self.profile
        out = []
        for i in range(p.box_count):
            mons = {}
            for j in range(30):
                off = p.boxes_off + i * p.box_stride + j * BOX_MON_SIZE
                raw = self.pc[off : off + BOX_MON_SIZE]
                if is_empty_slot(raw):
                    continue
                try:
                    mons[j] = decode_box_mon(raw, p)
                except Gen4CodecError as exc:
                    raise Gen4CodecError(exc.reason, f"box {i} slot {j}: {exc}") from None
            out.append({"name": self.box_name(i), "mons": mons})
        return out

    def player(self) -> dict:
        p = self.profile
        if p.player_off is None:
            raise Gen4CodecError("player_offset_unknown", f"{p.name} has no known PlayerProfile offset")
        o = p.player_off + 4  # skip Options (u32); player_data.h:29-32
        name = _words(self.general, o, 8)
        pid_, money, gender, language, johto, avatar, version, flags, _dummy, kanto = struct.unpack_from(
            "<IIBBBBBBBB", self.general, o + 0x10)
        return {"name": decode_name(name), "name_raw": name, "id": pid_, "tid": pid_ & 0xFFFF,
                "sid": pid_ >> 16, "money": money, "gender": gender, "language": language,
                "johto_badges": johto, "kanto_badges": kanto, "avatar": avatar, "version": version,
                "game_clear": flags & 1, "nat_dex": flags >> 1 & 1}


def parse_save(image: bytes, profile: Profile | str) -> Gen4Save:
    """Select the newest coherent bank of a 0x80000 battery file or refuse with a named reason.

    A bank is *usable* when its general and PC blocks both validate (footer size/slot/magic and
    CRC-16) and carry the same counter.  The newest usable bank by the wrap-aware counter wins; a
    newer but unusable bank (torn, disagreeing, ambiguous) is recorded in ``fallback`` and the
    older usable one is returned, like the game's SLOT_FAIL path.  Two usable banks with equal
    counters are refused as ambiguous."""
    if isinstance(profile, str):
        profile = PROFILES[profile]
    if len(image) != SAVE_SIZE:
        raise Gen4CodecError("size", f"expected {SAVE_SIZE:#x} bytes, got {len(image):#x}")
    banks = [_scan_bank(image, b, profile) for b in (0, 1)]
    blocks = {(b, s): blk for b in (0, 1) for s, blk in banks[b].items()}
    usable, why = {}, {}
    for b in (0, 1):
        g, p = banks[b][0], banks[b][1]
        if g.state == p.state == "absent":
            why[b] = "absent"
        elif g.state != "valid" or p.state != "valid":
            bad = g if g.state != "valid" else p
            why[b] = f"{bad.state}:{'general' if bad.slot == 0 else 'pc'}" + (f":{bad.reason}" if bad.reason else "")
        elif g.count != p.count:
            why[b] = f"general_pc_disagree:{g.count}!={p.count}"
        else:
            usable[b] = g.count
    if not usable:
        if all(v == "absent" for v in why.values()):
            raise Gen4CodecError("no_save", "no footer found in either bank")
        raise Gen4CodecError("no_usable_bank", f"bank0={why[0]} bank1={why[1]}")
    if len(usable) == 2:
        cmp = counter_newer(usable[0], usable[1])
        if cmp == 0:
            raise Gen4CodecError("ambiguous", f"both banks carry counter {usable[0]}")
        pick = 0 if cmp > 0 else 1
    else:
        pick = next(iter(usable))
    fb = ""
    other = 1 - pick
    if other in why and why[other] != "absent":
        fb = f"bank{other}: {why[other]}"
    g, p = banks[pick][0], banks[pick][1]
    # general/pc are the whole chunks INCLUDING their footer (as laid out in RAM); a writer must
    # CRC only [start, start + size - footer_size) -- see tools/gen4_synth_save.py
    return Gen4Save(profile, pick, usable[pick], image[g.start : g.start + g.size],
                    image[p.start : p.start + p.size], blocks, fb)
