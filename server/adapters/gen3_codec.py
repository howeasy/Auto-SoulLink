"""Independent Gen 3 (FR/LG) record and flash-save oracle, derived from pret.

Hand-derived from pret/pokefirered at commit
``c75f352304d529f6ba92d4f74b9cf8b5c3810788`` (every citation below is a
``file#Lstart-Lend`` range at that immutable commit) and, for the CFRU/RR
divergence, from the SOURCE note ``docs/gen3/research/flash_save.md``.

This module is deliberately independent of ``lua/memory_gba.lua``: it is the
Python side of the ``reads == PYDEC`` differential (PLAN §5.7), so it must
*agree* with the Lua decoders without sharing code, constants or bugs with
them.  It reads no JSON profile and touches no emulator.

Decoding preserves raw record values; it does not certify a legal Pokemon.
Names are English FR font tokens; unknown glyph bytes use reversible
``<$XX>`` tokens, and the raw name bytes are returned alongside the decoded
string so that ``encode(decode(x)) == x`` byte-for-byte on real records.

Base URL for every citation:
https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/

The Radical Red 4.1 layout at the end of this module is no longer upstream
CFRU hearsay: ``RR_CHUNK_TABLE`` and the box/parasite/extension addresses were
read out of the admitted RR ROM and cross-checked against a real RR battery
save (``docs/gen3/research/rr_save_layout.md``).  What that note still lists as
†UNVERIFIED -- no fixture carries a boxed mon, and the extension sectors 30/31
are unauthenticated and not slot-rotated -- is carried as a docstring caveat on
``rr_boxes_from_save`` and as a refusal when 30/31 are erased.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Record geometry -- include/pokemon.h#L105-L141 (BoxPokemon, Pokemon),
# include/pokemon.h#L8-L103 (the four substructs and their union).
# POKEMON_NAME_LENGTH=10, PLAYER_NAME_LENGTH=7 (include/constants/global.h).
# ---------------------------------------------------------------------------
BOX_MON_SIZE = 80           # sizeof(struct BoxPokemon): 0x20 header + 4*12
PARTY_MON_SIZE = 100        # sizeof(struct Pokemon): BoxPokemon + 20
COMPRESSED_MON_SIZE = 0x3A  # CFRU CompressedPokemon, flash_save.md §3
SUBSTRUCT_SIZE = 12         # NUM_SUBSTRUCT_BYTES, include/pokemon.h#L87-L94
SECURE_OFFSET = 0x20        # struct BoxPokemon.secure
SECURE_SIZE = 4 * SUBSTRUCT_SIZE
NICKNAME_LEN = 10
OT_NAME_LEN = 7
NAME_EOS = 0xFF             # charmap.txt#L156 ("'$' = FF")

_OFF_PERSONALITY, _OFF_OTID = 0x00, 0x04
_OFF_NICKNAME, _OFF_LANGUAGE, _OFF_FLAGS = 0x08, 0x12, 0x13
_OFF_OT_NAME, _OFF_MARKINGS = 0x14, 0x1B
_OFF_CHECKSUM, _OFF_UNKNOWN = 0x1C, 0x1E
# Party-only tail, include/pokemon.h#L128-L141.
_PARTY_TAIL = (
    ("status", 0x50, 4), ("level", 0x54, 1), ("mail", 0x55, 1),
    ("hp", 0x56, 2), ("max_hp", 0x58, 2), ("attack", 0x5A, 2),
    ("defense", 0x5C, 2), ("speed", 0x5E, 2), ("sp_attack", 0x60, 2),
    ("sp_defense", 0x62, 2),
)

# src/pokemon.c#L2846-L2890 (SUBSTRUCT_CASE table inside GetSubstruct).
# Entry [personality % 24] = (position of Growth, Attacks, EVs, Misc).
SUBSTRUCT_ORDER = (
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2),
    (0, 2, 3, 1), (0, 3, 2, 1), (1, 0, 2, 3), (1, 0, 3, 2),
    (2, 0, 1, 3), (3, 0, 1, 2), (2, 0, 3, 1), (3, 0, 2, 1),
    (1, 2, 0, 3), (1, 3, 0, 2), (2, 1, 0, 3), (3, 1, 0, 2),
    (2, 3, 0, 1), (3, 2, 0, 1), (1, 2, 3, 0), (1, 3, 2, 0),
    (2, 1, 3, 0), (3, 1, 2, 0), (2, 3, 1, 0), (3, 2, 1, 0),
)
# CFRU stores the substructs in fixed order and does not encrypt them
# (flash_save.md §3; lua/games/gen3_frlge.lua:342 CFRU_NO_ENCRYPT = true,
# lua/memory_gba.lua:570-572).
_FIXED_ORDER = (0, 1, 2, 3)

# ---------------------------------------------------------------------------
# FR English charmap -- charmap.txt#L1-L156 at the pinned commit.
# Letters/digits are contiguous runs, so they are built rather than typed:
# 'A'=BB (#L94), 'Z'=D4 (#L119), 'a'=D5 (#L120), 'z'=EE (#L145),
# '0'=A1 (#L67), '9'=AA (#L76).
# ---------------------------------------------------------------------------
FR_CHARMAP: dict[int, str] = {0x00: " "}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    FR_CHARMAP[0xBB + _i] = _c
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    FR_CHARMAP[0xD5 + _i] = _c
for _i in range(10):
    FR_CHARMAP[0xA1 + _i] = str(_i)
FR_CHARMAP.update({
    # charmap.txt#L2-L42: accented Latin used by the EU character set.
    0x01: "À", 0x02: "Á", 0x03: "Â", 0x04: "Ç", 0x05: "È", 0x06: "É",
    0x07: "Ê", 0x08: "Ë", 0x09: "Ì", 0x0B: "Î", 0x0C: "Ï", 0x0D: "Ò",
    0x0E: "Ó", 0x0F: "Ô", 0x10: "Œ", 0x11: "Ù", 0x12: "Ú", 0x13: "Û",
    0x14: "Ñ", 0x15: "ß", 0x16: "à", 0x17: "á", 0x19: "ç", 0x1A: "è",
    0x1B: "é", 0x1C: "ê", 0x1D: "ë", 0x1E: "ì", 0x20: "î", 0x21: "ï",
    0x22: "ò", 0x23: "ó", 0x24: "ô", 0x25: "œ", 0x26: "ù", 0x27: "ú",
    0x28: "û", 0x29: "ñ", 0x2A: "º", 0x2B: "ª",
    # charmap.txt#L43-L56.
    0x2D: "&", 0x2E: "+", 0x35: "=", 0x36: ";", 0x51: "¿", 0x52: "¡",
    0x5A: "Í", 0x5B: "%", 0x5C: "(", 0x5D: ")",
    # charmap.txt#L57-L65.
    0x68: "â", 0x6F: "í", 0x85: "<", 0x86: ">",
    # charmap.txt#L77-L93: punctuation.  0xB3/0xB4 are the curly quotes and
    # 0xB4 doubles as the apostrophe; the encoder pins ' -> 0xB4 (#L88-L89).
    0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xAF: "·", 0xB0: "…",
    0xB1: "“", 0xB2: "”", 0xB3: "‘", 0xB4: "’", 0xB5: "♂", 0xB6: "♀",
    0xB7: "¥", 0xB8: ",", 0xB9: "×", 0xBA: "/",
    # charmap.txt#L146-L153.
    0xEF: "▶", 0xF0: ":", 0xF1: "Ä", 0xF2: "Ö", 0xF3: "Ü", 0xF4: "ä",
    0xF5: "ö", 0xF6: "ü",
})
_FR_ENCODE = {text: byte for byte, text in FR_CHARMAP.items()}
_FR_ENCODE["'"] = 0xB4   # charmap.txt#L89: '\'' = B4
_FR_ENCODE["’"] = 0xB4   # 0xB3/0xB4 both render as an apostrophe; pin 0xB4.


def decode_name(raw: bytes) -> str:
    """Decode an FR font string, stopping at the 0xFF terminator."""
    out = []
    for byte in raw:
        if byte == NAME_EOS:
            break
        out.append(FR_CHARMAP.get(byte, f"<${byte:02X}>"))
    return "".join(out)


def encode_name(name: str, size: int) -> bytes:
    """Encode an FR font string into ``size`` bytes, 0xFF terminated/padded."""
    out = bytearray()
    i = 0
    while i < len(name):
        if name[i] == "<" and name[i:i + 2] == "<$" and name[i + 4:i + 5] == ">":
            out.append(int(name[i + 2:i + 4], 16))
            i += 5
            continue
        try:
            out.append(_FR_ENCODE[name[i]])
        except KeyError:
            raise ValueError(f"character {name[i]!r} is not in the FR charmap") from None
        i += 1
    if len(out) > size:
        raise ValueError(f"name {name!r} does not fit in {size} bytes")
    return bytes(out) + bytes([NAME_EOS]) * (size - len(out))


# ---------------------------------------------------------------------------
# Substructure crypto -- src/pokemon.c#L2797-L2812 (EncryptBoxMon /
# DecryptBoxMon: XOR every 32-bit word of ``secure`` with personality then
# otId) and src/pokemon.c#L2069-L2091 (CalculateBoxMonChecksum: the u16 sum of
# all 24 decrypted halfwords).
# ---------------------------------------------------------------------------
def _xor_words(blob: bytes, key: int) -> bytes:
    out = bytearray(len(blob))
    for i in range(0, len(blob), 4):
        word = int.from_bytes(blob[i:i + 4], "little") ^ key
        out[i:i + 4] = word.to_bytes(4, "little")
    return bytes(out)


def secure_checksum(plain: bytes) -> int:
    """u16 sum of the 24 halfwords of the decrypted 48-byte secure block."""
    total = 0
    for i in range(0, SECURE_SIZE, 2):
        total += int.from_bytes(plain[i:i + 2], "little")
    return total & 0xFFFF


def _u(blob: bytes, off: int, size: int) -> int:
    return int.from_bytes(blob[off:off + size], "little")


def _substruct_positions(personality: int, rr: bool) -> tuple[int, ...]:
    return _FIXED_ORDER if rr else SUBSTRUCT_ORDER[personality % 24]


def _decode_secure(plain_by_type: list[bytes]) -> dict:
    """Decode the four substructs, already put back in Growth/Attacks/EVs/Misc
    order.  Field maps: include/pokemon.h#L8-L85."""
    g, a, e, m = plain_by_type
    ivs = _u(m, 4, 4)
    met = _u(m, 2, 2)
    return {
        "species": _u(g, 0, 2),
        "held_item": _u(g, 2, 2),
        "experience": _u(g, 4, 4),
        "pp_bonuses": g[8],
        "friendship": g[9],
        "growth_filler": _u(g, 10, 2),
        "moves": [_u(a, i * 2, 2) for i in range(4)],
        "pp": list(a[8:12]),
        "evs": {
            "hp": e[0], "attack": e[1], "defense": e[2],
            "speed": e[3], "sp_attack": e[4], "sp_defense": e[5],
        },
        "contest": list(e[6:12]),
        "pokerus": m[0],
        "met_location": m[1],
        "met_level": met & 0x7F,
        "met_game": (met >> 7) & 0x0F,
        "pokeball": (met >> 11) & 0x0F,
        "ot_gender": (met >> 15) & 1,
        "ivs": {
            "hp": ivs & 0x1F, "attack": (ivs >> 5) & 0x1F,
            "defense": (ivs >> 10) & 0x1F, "speed": (ivs >> 15) & 0x1F,
            "sp_attack": (ivs >> 20) & 0x1F, "sp_defense": (ivs >> 25) & 0x1F,
        },
        "is_egg": (ivs >> 30) & 1,
        "ability_num": (ivs >> 31) & 1,
        "ribbons": _u(m, 8, 4),
    }


def _encode_secure(d: dict) -> list[bytes]:
    """Inverse of :func:`_decode_secure`; returns the four 12-byte substructs
    in Growth/Attacks/EVs/Misc order."""
    ev, iv = d["evs"], d["ivs"]
    growth = (
        d["species"].to_bytes(2, "little") + d["held_item"].to_bytes(2, "little")
        + d["experience"].to_bytes(4, "little")
        + bytes([d["pp_bonuses"], d["friendship"]])
        + d.get("growth_filler", 0).to_bytes(2, "little")
    )
    attacks = b"".join(m.to_bytes(2, "little") for m in d["moves"]) + bytes(d["pp"])
    evs = bytes([ev["hp"], ev["attack"], ev["defense"], ev["speed"],
                 ev["sp_attack"], ev["sp_defense"]]) + bytes(d["contest"])
    met = (d["met_level"] & 0x7F) | ((d["met_game"] & 0xF) << 7) \
        | ((d["pokeball"] & 0xF) << 11) | ((d["ot_gender"] & 1) << 15)
    packed = (
        (iv["hp"] & 0x1F) | ((iv["attack"] & 0x1F) << 5)
        | ((iv["defense"] & 0x1F) << 10) | ((iv["speed"] & 0x1F) << 15)
        | ((iv["sp_attack"] & 0x1F) << 20) | ((iv["sp_defense"] & 0x1F) << 25)
        | ((d["is_egg"] & 1) << 30) | ((d["ability_num"] & 1) << 31)
    )
    misc = (bytes([d["pokerus"], d["met_location"]]) + met.to_bytes(2, "little")
            + packed.to_bytes(4, "little") + d["ribbons"].to_bytes(4, "little"))
    return [growth, attacks, evs, misc]


def _decode_mon(raw: bytes, rr: bool, party: bool) -> dict:
    want = PARTY_MON_SIZE if party else BOX_MON_SIZE
    if len(raw) != want:
        raise ValueError(f"expected {want} bytes, got {len(raw)}")
    personality, ot_id = _u(raw, _OFF_PERSONALITY, 4), _u(raw, _OFF_OTID, 4)
    secure = raw[SECURE_OFFSET:SECURE_OFFSET + SECURE_SIZE]
    plain = secure if rr else _xor_words(secure, personality ^ ot_id)
    pos = _substruct_positions(personality, rr)
    ordered = [plain[p * SUBSTRUCT_SIZE:(p + 1) * SUBSTRUCT_SIZE] for p in pos]

    flags = raw[_OFF_FLAGS]
    stored_checksum = _u(raw, _OFF_CHECKSUM, 2)
    nick = raw[_OFF_NICKNAME:_OFF_NICKNAME + NICKNAME_LEN]
    ot = raw[_OFF_OT_NAME:_OFF_OT_NAME + OT_NAME_LEN]
    mon = {
        "personality": personality,
        "ot_id": ot_id,
        "nickname": decode_name(nick),
        "nickname_raw": bytes(nick),
        "language": raw[_OFF_LANGUAGE],
        "is_bad_egg": flags & 1,
        "has_species": (flags >> 1) & 1,
        "is_egg_flag": (flags >> 2) & 1,
        "block_box_rs": (flags >> 3) & 1,
        "flags_unused": (flags >> 4) & 0x0F,
        "ot_name": decode_name(ot),
        "ot_name_raw": bytes(ot),
        "markings": raw[_OFF_MARKINGS],
        "checksum": stored_checksum,
        "unknown": _u(raw, _OFF_UNKNOWN, 2),
    }
    mon.update(_decode_secure(ordered))
    # CFRU never validates the BoxPokemon checksum, and its reconstruction
    # leaves the field zero (flash_save.md §3; lua/memory_gba.lua:1075-1083),
    # so there is nothing to check in rr mode.
    mon["checksum_ok"] = None if rr else (secure_checksum(plain) == stored_checksum)
    if party:
        for name, off, size in _PARTY_TAIL:
            mon[name] = _u(raw, off, size)
    return mon


def _encode_mon(d: dict, rr: bool, party: bool) -> bytes:
    raw = bytearray(PARTY_MON_SIZE if party else BOX_MON_SIZE)
    personality, ot_id = d["personality"], d["ot_id"]
    raw[_OFF_PERSONALITY:_OFF_PERSONALITY + 4] = personality.to_bytes(4, "little")
    raw[_OFF_OTID:_OFF_OTID + 4] = ot_id.to_bytes(4, "little")
    nick = d.get("nickname_raw") or encode_name(d["nickname"], NICKNAME_LEN)
    ot = d.get("ot_name_raw") or encode_name(d["ot_name"], OT_NAME_LEN)
    raw[_OFF_NICKNAME:_OFF_NICKNAME + NICKNAME_LEN] = nick
    raw[_OFF_LANGUAGE] = d["language"]
    raw[_OFF_FLAGS] = (
        (d["is_bad_egg"] & 1) | ((d["has_species"] & 1) << 1)
        | ((d["is_egg_flag"] & 1) << 2) | ((d["block_box_rs"] & 1) << 3)
        | ((d.get("flags_unused", 0) & 0x0F) << 4)
    )
    raw[_OFF_OT_NAME:_OFF_OT_NAME + OT_NAME_LEN] = ot
    raw[_OFF_MARKINGS] = d["markings"]
    raw[_OFF_UNKNOWN:_OFF_UNKNOWN + 2] = d.get("unknown", 0).to_bytes(2, "little")

    by_type = _encode_secure(d)
    plain = bytearray(SECURE_SIZE)
    for type_index, position in enumerate(_substruct_positions(personality, rr)):
        plain[position * SUBSTRUCT_SIZE:(position + 1) * SUBSTRUCT_SIZE] = \
            by_type[type_index]
    if rr:
        checksum = d.get("checksum", 0)
        secure = bytes(plain)
    else:
        checksum = secure_checksum(plain)
        secure = _xor_words(bytes(plain), personality ^ ot_id)
    raw[_OFF_CHECKSUM:_OFF_CHECKSUM + 2] = checksum.to_bytes(2, "little")
    raw[SECURE_OFFSET:SECURE_OFFSET + SECURE_SIZE] = secure
    if party:
        for name, off, size in _PARTY_TAIL:
            raw[off:off + size] = d[name].to_bytes(size, "little")
    return bytes(raw)


def decode_party_mon(raw: bytes, rr: bool = False) -> dict:
    return _decode_mon(raw, rr, party=True)


def encode_party_mon(mon: dict, rr: bool = False) -> bytes:
    return _encode_mon(mon, rr, party=True)


def decode_box_mon(raw: bytes, rr: bool = False) -> dict:
    return _decode_mon(raw, rr, party=False)


def encode_box_mon(mon: dict, rr: bool = False) -> bytes:
    return _encode_mon(mon, rr, party=False)


# ---------------------------------------------------------------------------
# CFRU CompressedPokemon (58 bytes) -> BoxPokemon (80 bytes).
# Field map mirrors CFRU's CreateBoxMonFromCompressedMon as transcribed in
# lua/memory_gba.lua:1037-1104 (and flash_save.md §3 / CFRU
# include/new/pokemon_storage_system.h#L16-L57):
#   +0x00..0x1B header copied verbatim; checksum/unknown left ZERO
#   +0x1C..0x26 (11 B) -> Growth substruct at +0x20, pad byte +0x2B = 0
#   +0x27..0x2B        -> four 10-bit moves -> u16 at +0x2C/+0x2E/+0x30/+0x32
#                         (PP at +0x34..0x37 is not stored, left zero)
#   +0x2C..0x31 (6 B)  -> EVs at +0x38 (contest bytes at +0x3E left zero)
#   +0x32..0x39 (8 B)  -> Misc head at +0x44 (ribbons at +0x4C left zero)
# ---------------------------------------------------------------------------
def expand_compressed_box_mon(raw: bytes) -> bytes:
    if len(raw) != COMPRESSED_MON_SIZE:
        raise ValueError(f"expected {COMPRESSED_MON_SIZE} bytes, got {len(raw)}")
    out = bytearray(BOX_MON_SIZE)
    out[0x00:0x1C] = raw[0x00:0x1C]
    out[0x20:0x2B] = raw[0x1C:0x27]
    packed = int.from_bytes(raw[0x27:0x2C], "little")
    for i in range(4):
        move = (packed >> (10 * i)) & 0x3FF
        out[0x2C + i * 2:0x2E + i * 2] = move.to_bytes(2, "little")
    out[0x38:0x3E] = raw[0x2C:0x32]
    out[0x44:0x4C] = raw[0x32:0x3A]
    return bytes(out)


# ---------------------------------------------------------------------------
# Flash layout -- include/save.h#L6-L74 and src/save.c#L43-L78, #L133-L194,
# #L423-L464, #L466-L582, #L614-L628.
# ---------------------------------------------------------------------------
SECTOR_DATA_SIZE = 3968      # include/save.h#L8
SECTOR_FOOTER_SIZE = 128     # include/save.h#L9
SECTOR_SIZE = 0x1000         # include/save.h#L10
SECTORS_COUNT = 32           # include/save.h#L30
NUM_SECTORS_PER_SLOT = 14    # include/save.h#L24
NUM_SAVE_SLOTS = 2           # include/save.h#L12
SECTOR_SIGNATURE = 0x08012025  # include/save.h#L15
FLASH_SIZE = SECTORS_COUNT * SECTOR_SIZE   # 0x20000
RTC_SUFFIX_SIZE = 16         # flash_save.md §2 (mGBA savedata.h#L91-L95)

# Footer offsets, derived from struct SaveSector (include/save.h#L63-L71):
# data[3968], unused[128-12], u16 id, u16 checksum, u32 signature, u32 counter.
OFF_SECTOR_ID = 0x0FF4
OFF_SECTOR_CHECKSUM = 0x0FF6
OFF_SECTOR_SIGNATURE = 0x0FF8
OFF_SECTOR_COUNTER = 0x0FFC

SAVEBLOCK2_SIZE = 0x0F24     # include/global.h#L359 ("size: 0xF24")
SAVEBLOCK1_SIZE = 0x3D68     # include/global.h#L822 ("size: 0x3D68")
# struct PokemonStorage ends at boxWallpapers[14] starting 0x83C2:
# include/pokemon_storage_system.h#L44-L50.
STORAGE_SIZE = 0x83D0
BOX_DATA_OFFSET = 0x0004     # boxes[] after u8 currentBox, aligned to 4
BOXES_PER_STORE = 14         # TOTAL_BOXES_COUNT, pokemon_storage_system.h#L7
MONS_PER_BOX = 30            # IN_BOX_COUNT, pokemon_storage_system.h#L8-L10
BOX_NAMES_OFFSET = 0x8344    # pokemon_storage_system.h#L48

CHUNK_SIZE_VANILLA = SECTOR_DATA_SIZE   # 0xF80, src/save.c#L43-L48
# †UNVERIFIED for Radical Red 4.1: this is the UPSTREAM CFRU chunk capacity
# (flash_save.md §3, CFRU src/save.c#L17-L48).  CFRU additionally appends a
# "parasite" payload after the chunk checksum in IDs 0/4/13 and repurposes
# physical sectors 30/31; neither is modelled here.
CHUNK_SIZE_CFRU = 0x0FF0

_OBJECTS = (
    ("sb2", SAVEBLOCK2_SIZE, 0, 0),
    ("sb1", SAVEBLOCK1_SIZE, 1, 4),
    ("storage", STORAGE_SIZE, 5, 13),
)


def slot_layout(chunk_size: int = CHUNK_SIZE_VANILLA) -> list[dict]:
    """The 14 logical sections, via the SAVEBLOCK_CHUNK macro
    (src/save.c#L43-L72): offset = chunkNum * chunk_size, size =
    min(sizeof(object) - offset, chunk_size).  The same macro with
    chunk_size=0xFF0 reproduces CFRU's literal table (flash_save.md §3)."""
    layout = []
    for name, total, first_id, last_id in _OBJECTS:
        for chunk in range(last_id - first_id + 1):
            offset = chunk * chunk_size
            size = min(total - offset, chunk_size) if total >= offset else 0
            layout.append({"id": first_id + chunk, "object": name,
                           "offset": offset, "size": size})
    return layout


def sector_checksum(data: bytes, size: int) -> int:
    """src/save.c#L614-L628: wrapping u32 sum of size/4 little-endian words,
    folded to u16 as ``(sum >> 16) + sum``.  ``size`` is the SECTION's chunk
    size, never the whole sector."""
    total = 0
    for i in range(size // 4):
        total = (total + int.from_bytes(data[i * 4:i * 4 + 4], "little")) & 0xFFFFFFFF
    return ((total >> 16) + total) & 0xFFFF


def split_rtc(image: bytes) -> tuple[bytes, bytes]:
    """Split a BizHawk ``.SaveRAM`` into (flash body, optional RTC suffix).

    The 16-byte suffix is OPTIONAL mGBA RTC state, present only for real-time
    configurations (flash_save.md §2) -- never subtract it unconditionally.
    Any other length is refused rather than guessed."""
    if len(image) == FLASH_SIZE:
        return image, b""
    if len(image) == FLASH_SIZE + RTC_SUFFIX_SIZE:
        return image[:FLASH_SIZE], image[FLASH_SIZE:]
    raise ValueError(
        f"unsupported save length 0x{len(image):X}; expected 0x{FLASH_SIZE:X} "
        f"or 0x{FLASH_SIZE + RTC_SUFFIX_SIZE:X}")


def read_sector(body: bytes, index: int, layout: list[dict]) -> dict:
    base = index * SECTOR_SIZE
    raw = body[base:base + SECTOR_SIZE]
    sid = int.from_bytes(raw[OFF_SECTOR_ID:OFF_SECTOR_ID + 2], "little")
    checksum = int.from_bytes(raw[OFF_SECTOR_CHECKSUM:OFF_SECTOR_CHECKSUM + 2], "little")
    signature = int.from_bytes(raw[OFF_SECTOR_SIGNATURE:OFF_SECTOR_SIGNATURE + 4], "little")
    counter = int.from_bytes(raw[OFF_SECTOR_COUNTER:OFF_SECTOR_COUNTER + 4], "little")
    known = sid < NUM_SECTORS_PER_SLOT
    ok = False
    if signature == SECTOR_SIGNATURE and known:
        ok = checksum == sector_checksum(raw, layout[sid]["size"])
    return {"index": index, "id": sid, "checksum": checksum,
            "signature": signature, "counter": counter,
            "signature_ok": signature == SECTOR_SIGNATURE,
            "id_known": known, "checksum_ok": ok,
            "data": raw[:SECTOR_DATA_SIZE]}


def write_sector(data: bytes, sector_id: int, counter: int,
                 layout: list[dict]) -> bytes:
    """Build one flash sector the way HandleWriteSector does
    (src/save.c#L167-L195): zeroed buffer, chunk copied in, footer written,
    checksum over the chunk SIZE only."""
    size = layout[sector_id]["size"]
    raw = bytearray(SECTOR_SIZE)
    raw[:size] = data[:size].ljust(size, b"\x00")
    raw[OFF_SECTOR_ID:OFF_SECTOR_ID + 2] = sector_id.to_bytes(2, "little")
    raw[OFF_SECTOR_CHECKSUM:OFF_SECTOR_CHECKSUM + 2] = \
        sector_checksum(bytes(raw), size).to_bytes(2, "little")
    raw[OFF_SECTOR_SIGNATURE:OFF_SECTOR_SIGNATURE + 4] = \
        SECTOR_SIGNATURE.to_bytes(4, "little")
    raw[OFF_SECTOR_COUNTER:OFF_SECTOR_COUNTER + 4] = counter.to_bytes(4, "little")
    return bytes(raw)


_STATUS_EMPTY, _STATUS_OK, _STATUS_INVALID, _STATUS_ERROR = 0, 1, 2, 0xFF
STATUS_NAMES = {_STATUS_EMPTY: "EMPTY", _STATUS_OK: "OK",
                _STATUS_INVALID: "INVALID", _STATUS_ERROR: "ERROR"}


def _scan_slot(sectors: list[dict]) -> tuple[int, int]:
    """One half of GetSaveValidStatus (src/save.c#L478-L532): returns
    (status, candidate counter).  The counter is overwritten by every accepted
    sector, exactly as upstream does -- it does NOT require agreement."""
    valid_bits, signature_valid, counter = 0, False, 0
    for sector in sectors:
        if sector["signature_ok"]:
            signature_valid = True
            if sector["checksum_ok"]:
                counter = sector["counter"]
                valid_bits |= 1 << sector["id"]
    if not signature_valid:
        return _STATUS_EMPTY, counter
    all_bits = (1 << NUM_SECTORS_PER_SLOT) - 1
    return (_STATUS_OK if valid_bits == all_bits else _STATUS_ERROR), counter


def _select_slot(s1: int, c1: int, s2: int, c2: int) -> tuple[int, int]:
    """src/save.c#L534-L582.  Returns (status, gSaveCounter).  The explicit
    wrap case treats the 0xFFFFFFFF/0 pair by comparing counter+1 modulo
    2**32, so 0 wins over 0xFFFFFFFF."""
    if s1 == _STATUS_OK and s2 == _STATUS_OK:
        if (c1 == 0xFFFFFFFF and c2 == 0) or (c1 == 0 and c2 == 0xFFFFFFFF):
            chosen = c2 if ((c1 + 1) & 0xFFFFFFFF) < ((c2 + 1) & 0xFFFFFFFF) else c1
        else:
            chosen = c2 if c1 < c2 else c1
        return _STATUS_OK, chosen
    if s1 == _STATUS_OK:
        return (_STATUS_ERROR if s2 == _STATUS_ERROR else _STATUS_OK), c1
    if s2 == _STATUS_OK:
        return (_STATUS_ERROR if s1 == _STATUS_ERROR else _STATUS_OK), c2
    if s1 == _STATUS_EMPTY and s2 == _STATUS_EMPTY:
        return _STATUS_EMPTY, 0
    return _STATUS_INVALID, 0


def parse_flash(image: bytes, cfru: bool = False) -> dict:
    """Loader-style recovery: mirrors GetSaveValidStatus + CopySaveSlotData.

    Like the game, this accepts a partially valid image and copies whatever
    sections check out.  Use :func:`qualify_flash` for the strict witness
    test."""
    layout = slot_layout(CHUNK_SIZE_CFRU if cfru else CHUNK_SIZE_VANILLA)
    body, rtc = split_rtc(image)
    sectors = [read_sector(body, i, layout) for i in range(SECTORS_COUNT)]
    s1, c1 = _scan_slot(sectors[:NUM_SECTORS_PER_SLOT])
    s2, c2 = _scan_slot(sectors[NUM_SECTORS_PER_SLOT:NUM_SECTORS_PER_SLOT * 2])
    status, counter = _select_slot(s1, c1, s2, c2)

    slot = counter % NUM_SAVE_SLOTS
    base = NUM_SECTORS_PER_SLOT * slot
    blocks = {"sb2": bytearray(SAVEBLOCK2_SIZE),
              "sb1": bytearray(SAVEBLOCK1_SIZE),
              "storage": bytearray(STORAGE_SIZE)}
    rotation = None
    for i in range(NUM_SECTORS_PER_SLOT):   # src/save.c#L440-L464
        sector = sectors[base + i]
        if sector["id"] == 0:
            rotation = i
        if not sector["id_known"] or not sector["signature_ok"] \
                or not sector["checksum_ok"]:
            continue
        entry = layout[sector["id"]]
        start = entry["offset"]
        # Slice from the sector body, not from sector["data"]: a CFRU chunk is
        # 0xFF0 bytes, longer than the vanilla 0xF80 data area, and truncating
        # it would silently drop 0x70 bytes per section.  Identical for vanilla.
        chunk_start = (base + i) * SECTOR_SIZE
        blocks[entry["object"]][start:start + entry["size"]] = \
            body[chunk_start:chunk_start + entry["size"]]
    return {
        "slot": slot, "counter": counter, "status": status,
        "status_name": STATUS_NAMES.get(status, str(status)),
        "slot_status": (s1, s2), "slot_counters": (c1, c2),
        "rotation": rotation, "sectors": sectors, "rtc": rtc,
        "sb1": bytes(blocks["sb1"]), "sb2": bytes(blocks["sb2"]),
        "storage": bytes(blocks["storage"]),
    }


def qualify_flash(image: bytes, cfru: bool = False) -> tuple[bool, str]:
    """STRICT qualification, deliberately stronger than the game's loader
    (flash_save.md §1 [RECOMMENDATION]): the selected slot must carry exactly
    one copy of each of the 14 ids, with valid signature and checksum, all at
    the SAME counter.  A recovered older slot is playable but is not a witness
    that the intended save completed."""
    try:
        parsed = parse_flash(image, cfru=cfru)
    except ValueError as exc:
        return False, str(exc)
    base = NUM_SECTORS_PER_SLOT * parsed["slot"]
    chosen = parsed["sectors"][base:base + NUM_SECTORS_PER_SLOT]
    seen: list[int] = []
    for sector in chosen:
        if not sector["signature_ok"]:
            return False, f"sector {sector['index']} has no valid signature"
        if not sector["id_known"]:
            return False, f"sector {sector['index']} has out-of-range id {sector['id']}"
        if not sector["checksum_ok"]:
            return False, f"sector {sector['index']} (id {sector['id']}) bad checksum"
        seen.append(sector["id"])
    if len(set(seen)) != NUM_SECTORS_PER_SLOT:
        duplicated = sorted({i for i in seen if seen.count(i) > 1})
        missing = sorted(set(range(NUM_SECTORS_PER_SLOT)) - set(seen))
        return False, f"duplicate section ids {duplicated}, missing {missing}"
    counters = {sector["counter"] for sector in chosen}
    if len(counters) != 1:
        return False, f"torn save: mixed counters {sorted(counters)}"
    if parsed["status"] != _STATUS_OK:
        return False, f"save status {parsed['status_name']}"
    if counters != {parsed["counter"]}:
        return False, (f"selected counter {parsed['counter']} is not the "
                       f"slot's counter {counters.pop()}")
    return True, "ok"


# ---------------------------------------------------------------------------
# Save-level extraction.
# SaveBlock1.playerPartyCount is +0x34 and playerParty +0x38
# (include/global.h#L772-L773).
# ---------------------------------------------------------------------------
SB1_PARTY_COUNT_OFFSET = 0x34
SB1_PARTY_OFFSET = 0x38
PARTY_CAPACITY = 6

_RR_SAVE_REFUSAL = (
    "the vanilla FR/LG extractors do not handle Radical Red: RR's chunk table "
    "is CFRU's 0xFF0 one and its 25 boxes live in four non-contiguous EWRAM "
    "regions (docs/gen3/research/flash_save.md §3 called this UNVERIFIED; it "
    "is now pinned in docs/gen3/research/rr_save_layout.md). Use "
    "rr_party_from_save() / rr_boxes_from_save() instead."
)


def party_from_save(image: bytes, rr: bool = False) -> list[dict]:
    """Decode the saved party out of a flash image (vanilla FR/LG only)."""
    if rr:
        raise NotImplementedError(_RR_SAVE_REFUSAL)
    sb1 = parse_flash(image)["sb1"]
    count = min(sb1[SB1_PARTY_COUNT_OFFSET], PARTY_CAPACITY)
    out = []
    for slot in range(count):
        start = SB1_PARTY_OFFSET + slot * PARTY_MON_SIZE
        out.append(decode_party_mon(sb1[start:start + PARTY_MON_SIZE]))
    return out


def boxes_from_save(image: bytes, rr: bool = False) -> list[list[dict]]:
    """Decode all 14 x 30 boxed mons out of a flash image (vanilla FR/LG)."""
    if rr:
        raise NotImplementedError(_RR_SAVE_REFUSAL)
    storage = parse_flash(image)["storage"]
    boxes = []
    for box in range(BOXES_PER_STORE):
        slots = []
        for slot in range(MONS_PER_BOX):
            start = BOX_DATA_OFFSET + (box * MONS_PER_BOX + slot) * BOX_MON_SIZE
            slots.append(decode_box_mon(storage[start:start + BOX_MON_SIZE]))
        boxes.append(slots)
    return boxes


# ---------------------------------------------------------------------------
# Radical Red 4.1 save layout.
#
# Everything below is read out of the admitted RR ROM (and cross-checked
# against a real RR battery save) by gen3-P2-C2-8; the receipts, the verbatim
# tables and the remaining †UNVERIFIED list are in
# docs/gen3/research/rr_save_layout.md.  ROM file offsets are quoted; the GBA
# address is 0x08000000 + offset.  Both `Pokemon - Radical Red.gba` and
# `patch/build/slink_RR.gba` carry these tables byte-identically.
# ---------------------------------------------------------------------------

# ROM 0x1148BF0 (0x09148BF0): 14 entries of {u16 object-relative offset,
# u16 size}.  Verbatim, in section-id order.  rr_save_layout.md §1.
RR_CHUNK_TABLE = (
    (0x0000, 0x0F24),                                    # id 0   SaveBlock2
    (0x0000, 0x0FF0), (0x0FF0, 0x0FF0),                  # id 1-2 SaveBlock1
    (0x1FE0, 0x0FF0), (0x2FD0, 0x0D98),                  # id 3-4 SaveBlock1
    (0x0000, 0x0FF0), (0x0FF0, 0x0FF0), (0x1FE0, 0x0FF0),
    (0x2FD0, 0x0FF0), (0x3FC0, 0x0FF0), (0x4FB0, 0x0FF0),
    (0x5FA0, 0x0FF0), (0x6F90, 0x0FF0), (0x7F80, 0x0450),  # id 5-13 storage
)

# Literal pool at ROM 0x4C08C.  rr_save_layout.md §2.
RR_SAVEBLOCK2_ADDR = 0x02024588
RR_SAVEBLOCK1_ADDR = 0x0202552C
RR_STORAGE_ADDR = 0x02029314
# Literal pools at ROM 0x10B8C98 / 0x10B8DEC.  The extension is the contiguous
# range written verbatim into PHYSICAL sectors 30 and 31 (0xFF0 each, zeroed
# buffer, NO section footer, NO checksum, NO signature).  rr_save_layout.md §4-5.
RR_PARASITE_ADDR = 0x0203B174
RR_PARASITE_SIZE = 0x0EC4
RR_EXT_ADDR = 0x0203C038
RR_EXT_SECTORS = (30, 31)
RR_EXT_SIZE = len(RR_EXT_SECTORS) * CHUNK_SIZE_CFRU
# Parasite piece per section id, from the dispatcher at ROM 0x10B8D30; each
# piece runs from the chunk size to 0x0FEF and is NOT checksummed.
RR_PARASITE_PIECES = {0: 0x00CC, 4: 0x0258, 13: 0x0BA0}

RR_BOXES_PER_STORE = 25
RR_BOX_STRIDE = MONS_PER_BOX * COMPRESSED_MON_SIZE   # 0x6CC
# ROM 0x1148930 (0x09148930): the 25 live box addresses, byte-identical to
# data/games/gen3_rr/profile.json CFRU_BOX_BASES.
RR_BOX_BASES = (
    0x02029318, 0x020299E4, 0x0202A0B0, 0x0202A77C, 0x0202AE48,
    0x0202B514, 0x0202BBE0, 0x0202C2AC, 0x0202C978, 0x0202D044,
    0x0202D710, 0x0202DDDC, 0x0202E4A8, 0x0202EB74, 0x0202F240,
    0x0202F90C, 0x0202FFD8, 0x020306A4, 0x02030D70,   # 1-19: storage +0x0004
    0x0203CB44, 0x0203D210, 0x0203D8DC,               # 20-22: sectors 30/31
    0x02027434, 0x02027B00,                           # 23-24: SaveBlock1
    0x02024638,                                       # 25:    SaveBlock2
)

_RR_EXT_ERASED = (
    "physical sectors 30/31 are erased (all 0xFF): Radical Red keeps boxes "
    "20-22 there, so this image cannot yield a complete 25-box read "
    "(docs/gen3/research/rr_save_layout.md §5)."
)


def rr_slot_layout() -> list[dict]:
    """RR's 14 sections.  Identical to ``slot_layout(CHUNK_SIZE_CFRU)``; this
    name exists so callers do not have to know that RR == the CFRU macro."""
    return slot_layout(CHUNK_SIZE_CFRU)


def _rr_regions(image: bytes) -> list[tuple[int, bytes]]:
    """The save as (RAM base, bytes) spans: the three reconstructed save
    objects plus the unauthenticated extension.  rr_save_layout.md §2, §5."""
    body, _ = split_rtc(image)
    parsed = parse_flash(image, cfru=True)
    ext = b"".join(
        body[s * SECTOR_SIZE:s * SECTOR_SIZE + CHUNK_SIZE_CFRU]
        for s in RR_EXT_SECTORS)
    if ext.count(0xFF) == len(ext):
        raise ValueError(_RR_EXT_ERASED)
    return [
        (RR_SAVEBLOCK2_ADDR, parsed["sb2"]),
        (RR_SAVEBLOCK1_ADDR, parsed["sb1"]),
        (RR_STORAGE_ADDR, parsed["storage"]),
        (RR_EXT_ADDR, ext),
    ]


def _rr_read(regions: list[tuple[int, bytes]], addr: int, size: int) -> bytes:
    for base, blob in regions:
        if base <= addr and addr + size <= base + len(blob):
            return blob[addr - base:addr - base + size]
    raise ValueError(
        f"RAM 0x{addr:08X}+0x{size:X} is not inside any saved RR region")


def rr_party_from_save(image: bytes) -> list[dict]:
    """Decode the saved party out of a Radical Red flash image.

    RR keeps the vanilla SaveBlock1 party shadow -- count at +0x34, 100-byte
    records at +0x38 -- but with CFRU's unencrypted, fixed-order substructs
    and a zero BoxPokemon checksum.  rr_save_layout.md §6."""
    sb1 = parse_flash(image, cfru=True)["sb1"]
    count = min(sb1[SB1_PARTY_COUNT_OFFSET], PARTY_CAPACITY)
    return [decode_party_mon(
        sb1[SB1_PARTY_OFFSET + slot * PARTY_MON_SIZE:
            SB1_PARTY_OFFSET + (slot + 1) * PARTY_MON_SIZE], rr=True)
        for slot in range(count)]


def rr_boxes_from_save(image: bytes) -> list[list[dict]]:
    """Decode all 25 x 30 boxed mons out of a Radical Red flash image.

    25 boxes of 30 compressed 0x3A records do not fit PokemonStorage, so RR
    scatters them: 1-19 at storage+0x0004, 20-22 into the extension written to
    physical sectors 30/31, 23-24 into SaveBlock1 and 25 into SaveBlock2
    (rr_save_layout.md §3).  Box 20 straddles the 30->31 boundary, which is why
    the extension is read as one contiguous blob.

    †UNVERIFIED caveat (rr_save_layout.md §7): the extension carries no
    signature, checksum or counter and is NOT part of the rotating two-slot
    scheme, so boxes 20-22 always come from the most recent write even when the
    rotating slot recovered was the older one.  An erased extension raises."""
    regions = _rr_regions(image)
    boxes = []
    for base in RR_BOX_BASES:
        raw = _rr_read(regions, base, RR_BOX_STRIDE)
        boxes.append([
            decode_box_mon(expand_compressed_box_mon(
                raw[slot * COMPRESSED_MON_SIZE:
                    (slot + 1) * COMPRESSED_MON_SIZE]), rr=True)
            for slot in range(MONS_PER_BOX)])
    return boxes
