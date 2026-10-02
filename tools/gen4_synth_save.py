#!/usr/bin/env python3
"""Disclosed SYNTH setup (O-33) for the Gen 4 test rows: ``party2``, ``bag`` and ``egg1``.

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

``bag`` and ``egg1`` (added for the G2 producer plan) follow the same safety pattern:

    python tools/gen4_synth_save.py bag  --profile hgss --src <battery> --out <path> [--count 10]
    python tools/gen4_synth_save.py egg1 --profile hgss --src <battery> --out <path> [--species 172] [--cycles 1]

* ``bag`` puts N Poke Balls into the Balls pocket (pret ``include/bag_types_def.h:46-55``; the
  array is ``round4(sizeof)+4`` bytes at general+0x644, see ``BAGS``).  It follows
  ``Pocket_GetItemSlotForAdd`` (src/bag.c:108-130): add to the existing stack, else the first
  empty slot, never overwrite, refuse a full pocket;
* ``egg1`` appends one egg after the last party mon (only when the party has fewer than 6)
  built the way ``ScrCmd_GiveEgg`` -> ``SetEggStats`` (src/get_egg.c:561-590) builds one; the
  hatch counter is the friendship byte (``HandleDaycareStep``, src/get_egg.c:763-809).

In every kind the verifier also proves that no byte outside the intended span (plus the two
CRC bytes of the newest general footer) differs from the source.

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
BAG_NOTE = "SYNTH setup: Poke Balls added to the Balls pocket for a native catch test"
EGG_NOTE = "SYNTH setup: one egg appended to the party for a native hatch test"
EGG_KIND = "egg1"
SIDECAR_SUFFIX = ".synth.json"
BIZHAWK_ROOT = Path("E:/Howard/Bizhawk")  # the owner's live emulator saves are never an output
PROFILES = ("hgss", "hge")
WRITTEN, REFUSED, ABSENT = 0, 1, 2
CLONE_SLOT = 1

# --- bag -------------------------------------------------------------------------------
ITEM_POKE_BALL = 4  # pret include/constants/items.h:273; hg-engine include/constants/item.h:10
BAG_SLOT_QUANTITY_MAX = 999  # pret include/constants/items.h:43
# Bag = {ItemSlot items[], keyItems[], TMsHMs[], mail[], medicine[], berries[], balls[],
# battleItems[]; u16 registered[2]}, ItemSlot = {u16 id, u16 quantity}
# (pret include/bag_types_def.h:46-55, include/item.h:13-16; hg-engine include/bag.h:41-50).
POCKETS = ("items", "keyItems", "TMsHMs", "mail", "medicine", "berries", "balls", "battleItems")
# Slot counts.  hgss: pret include/constants/items.h:34-41.  hge: include/constants/item.h:2870-2880
# (ITEM_POCKET_EXPANSION on, include/config.h:53; NUM_MEGA_STONES 48, item.h:2700): items
# 165+32+48, keyItems 50+42, balls 24+2.  FILE: the owner hge save's expanded general block is
# exactly 0x1F0 bytes (= (32+48+2+42)*4) after the vanilla one at the Location array
# (profile file_cross_check 0x1424 vs 0x1234), and Potion sits in medicine slot 0 at
# general+0xB64 (hgss) / +0xD4C (hge) in both owner saves.
BAG_SLOTS = {
    "hgss": {"items": 165, "keyItems": 50, "TMsHMs": 101, "mail": 12, "medicine": 40, "berries": 64, "balls": 24, "battleItems": 30},
    "hge": {"items": 245, "keyItems": 92, "TMsHMs": 101, "mail": 12, "medicine": 40, "berries": 64, "balls": 26, "battleItems": 30},
}
# The Bag array follows Party in the general block: each save array is round4(sizeof)+4 bytes
# (src/save.c:733-741 GetSaveChunkSizePlusCRC, SaveData_InitSubstructs) and sizeof(Party) =
# {max,count} 8 + 6 * 0xEC + PartyExtra 6 * PERFORMANCE_MAX(5) = 0x5AE -> 0x5B4, so
# bag = party_off + 0x5B4 = 0x644 (include/pokemon_types_def.h:316-327).  No per-array CRC
# is maintained for the bag (SaveSubstruct_UpdateCRC has no SAVE_BAG caller in src/).
PARTY_ARRAY_SIZE = 0x5B4

# --- egg -------------------------------------------------------------------------------
# One entry per supported species: base stats HP/Atk/Def/Spe/SpA/SpD and gender ratio and
# abilities from files/poketool/personal/personal.json, level-1 moves (id, PP) from
# wotbl.narc / waza_tbl.narc (all pret ad7a3afa; level-1 exp is 0 for both growth rates, growtbl.csv).
EGG_SPECIES = {
    172: {"name": "Pichu", "base": (20, 40, 15, 60, 35, 35), "ratio": 127, "abilities": (9, 0),
              "moves": ((84, 30), (204, 20)), "egg_cycles": 10},
    175: {"name": "Togepi", "base": (35, 20, 65, 20, 40, 65), "ratio": 31, "abilities": (55, 32),
              "moves": ((45, 40), (204, 20)), "egg_cycles": 10},
}
BALL_POKE = 4  # pret include/constants/balls.h:9
METLOC_DAY_CARE_COUPLE = 2000  # include/constants/map_sections.h:240 = sub_02017FE4(MAPSECTYPE_GIFT, 0)
EGG_NAME = "Egg"  # files/msgdata/msg/msg_0237.gmm index 494 (SPECIES_EGG); mixed case, not "EGG"
MAX_PARTY = 6


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


def _seed(kind: str, src_sha1: str) -> int:
    return int.from_bytes(hashlib.sha1(f"{kind}:{src_sha1}".encode()).digest()[:4], "little")


def synth_pid(src_sha1: str, template_pid: int, otid: int) -> int:
    """A deterministic clone PID: same nature (pid % 25) as the template, never shiny, never equal."""
    seed = _seed(KIND, src_sha1)
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


def _seal(image: bytes, save, edit) -> bytes:
    """Apply ``edit(body)`` to the newest general block and re-stamp ONLY its footer CRC.

    A Block's ``size`` includes its footer, but the footer CRC covers only the bytes from the
    block start up to the footer -- the same span codec._scan_bank validates."""
    p = save.profile
    block = save.blocks[(save.bank, 0)]
    foot = block.start + block.size - p.footer_size
    data = bytearray(image[block.start:foot])
    edit(data)
    out = bytearray(image)
    out[block.start:foot] = data
    fields = list(struct.unpack_from(p.footer_fmt, out, foot))
    fields[p.footer_fields.index("crc")] = codec.crc16_ccitt(bytes(data))
    out[foot : foot + p.footer_size] = struct.pack(p.footer_fmt, *fields)
    return bytes(out)


def _only_changed(src: bytes, out: bytes, save, spans) -> None:
    """Every differing byte must lie in ``spans`` (general-block-relative) or be the CRC field."""
    p = save.profile
    block = save.blocks[(save.bank, 0)]
    foot = block.start + block.size - p.footer_size
    allowed = [(block.start + a, block.start + b) for a, b in spans] + [(foot + p.footer_size - 2, foot + p.footer_size)]
    if len(src) != len(out):
        raise Refusal("verify", "image size changed")
    for i, (a, b) in enumerate(zip(src, out, strict=True)):
        if a != b and not any(lo <= i < hi for lo, hi in allowed):
            raise Refusal("verify", f"byte {i:#x} changed outside the intended span")


def _row(kind: str, note: str, src: bytes, out: bytes, save, **extra) -> dict:
    return {
        "schema": SCHEMA,
        "kind": kind,
        "src_sha1": hashlib.sha1(src).hexdigest(),
        "out_sha1": hashlib.sha1(out).hexdigest(),
        "profile": save.profile.name,
        "bank": save.bank,
        "note": note,
        **extra,
    }


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

    off = p.party_off + 8  # {u32 max, u32 count} then Pokemon[6]

    def edit(data: bytearray) -> None:
        record = _clone(bytes(data[off : off + codec.PARTY_MON_SIZE]), p, pid)
        data[off + CLONE_SLOT * codec.PARTY_MON_SIZE : off + (CLONE_SLOT + 1) * codec.PARTY_MON_SIZE] = record
        struct.pack_into("<I", data, p.party_off + 4, CLONE_SLOT + 1)

    out = _seal(image, save, edit)
    _verify(image, out, p, save.bank)
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


# ---------------------------------------------------------------------------
# bag: N Poke Balls in the Balls pocket
# ---------------------------------------------------------------------------
def bag_layout(profile) -> dict:
    """General-block offsets of the Bag array and the Balls pocket, or a named refusal."""
    slots = BAG_SLOTS.get(profile.name)
    if slots is None or profile.party_off is None:
        raise Refusal("bag_layout_unknown", f"no source-derived Bag layout for profile {profile.name!r}")
    base = profile.party_off + PARTY_ARRAY_SIZE
    offs, at = {}, base
    for pocket in POCKETS:
        offs[pocket] = at
        at += 4 * slots[pocket]
    return {"bag_off": base, "balls_off": offs["balls"], "balls_slots": slots["balls"], "end": at + 4}


def build_bag(image: bytes, profile, count: int = 10) -> tuple[bytes, dict]:
    if not 1 <= count <= BAG_SLOT_QUANTITY_MAX:
        raise Refusal("bad_count", f"--count must be 1..{BAG_SLOT_QUANTITY_MAX}, got {count}")
    save = codec.parse_save(image, profile)
    lay = bag_layout(save.profile)
    party = save.party()  # a corrupt party refuses here, like party2
    block = save.blocks[(save.bank, 0)]
    if lay["end"] > block.size - save.profile.footer_size:
        raise Refusal("bag_layout", "the Bag array would run past the general block")
    slots = [struct.unpack_from("<HH", save.general, lay["balls_off"] + 4 * i) for i in range(lay["balls_slots"])]
    if any(q > BAG_SLOT_QUANTITY_MAX for _, q in slots):
        raise Refusal("pocket_implausible", "a Balls slot holds a quantity > 999: the pocket offset is wrong")
    # Pocket_GetItemSlotForAdd (src/bag.c:108-130): the existing stack wins (and refuses when
    # it would overflow); otherwise the FIRST empty slot (id == 0 and quantity == 0).
    stack = next((i for i, (iid, _) in enumerate(slots) if iid == ITEM_POKE_BALL), None)
    if stack is not None:
        if slots[stack][1] + count > BAG_SLOT_QUANTITY_MAX:
            raise Refusal("stack_full", f"Poke Ball stack {slots[stack][1]} + {count} exceeds {BAG_SLOT_QUANTITY_MAX}")
        slot = stack
    else:
        slot = next((i for i, (iid, q) in enumerate(slots) if iid == 0 and q == 0), None)
        if slot is None:
            raise Refusal("no_free_slot", f"all {lay['balls_slots']} Balls pocket slots are occupied by other items")
    before = slots[slot]
    after = (ITEM_POKE_BALL, before[1] + count)
    at = lay["balls_off"] + 4 * slot

    def edit(data: bytearray) -> None:
        struct.pack_into("<HH", data, at, *after)

    out = _seal(image, save, edit)
    _verify_bag(image, out, save, party, at, after)
    return out, _row("bag", BAG_NOTE, image, out, save, slot=slot, general_off=at, before=list(before),
                     after=list(after), item=ITEM_POKE_BALL, count=count)


def _verify_bag(src: bytes, out: bytes, save, party, at: int, after) -> None:
    got = codec.parse_save(out, save.profile)
    if got.bank != save.bank or got.counter != save.counter or got.party() != party:
        raise Refusal("verify", "bank, save counter or party changed")
    if struct.unpack_from("<HH", got.general, at) != tuple(after):
        raise Refusal("verify", "the Balls slot does not read back as written")
    _only_changed(src, out, save, [(at, at + 4)])


# ---------------------------------------------------------------------------
# egg1: one egg after the last party mon
# ---------------------------------------------------------------------------
def egg_pid(src_sha1: str, otid: int, taken: set) -> int:
    """Deterministic egg PID: neutral nature (pid % 25 in 0,6,12,18,24 keeps the level-1 stats
    free of the nature factor), not shiny for ``otid``, not already in the party."""
    pid = _seed(EGG_KIND, src_sha1)
    for _ in range(256):
        if pid % 25 % 6 == 0 and pid not in taken and not _shiny(pid, otid):
            return pid
        pid = (pid + 1) % (1 << 32)
    raise Refusal("no_egg_pid", "no neutral non-shiny PID in 256 candidates")


def _egg_stats(row: dict, ivs, level: int = 1) -> tuple[int, ...]:
    """src/pokemon.c:314-390 CalcMonStats at EVs 0 and a neutral nature: (HP, Atk, Def, Spe, SpA, SpD)."""
    hp, *rest = row["base"]
    return ((2 * hp + ivs[0]) * level // 100 + level + 10,
            *((2 * b + iv) * level // 100 + 5 for b, iv in zip(rest, ivs[1:], strict=True)))


def _egg_record(row: dict, species: int, pid: int, ivs, cycles: int, player: dict, template_plain: bytes) -> bytes:
    """The plaintext 0xEC egg record as ``ScrCmd_GiveEgg``/``SetEggStats`` leaves it.

    CreateMon(species, level 1, random IVs, random PID, OT_ID_PLAYER_ID) (src/pokemon.c:168-256),
    then SetEggStats (src/get_egg.c:561-590): ball BALL_POKE, friendship := egg cycles, met
    level 0, IS_EGG, nickname = the species name of SPECIES_EGG, and MonSetTrainerMemo(strat 3)
    (src/trainer_memo.c:753-757): egg location/date set, met location/date cleared, OT id /
    gender / name from the PlayerProfile.  The egg location is sub_02017FE4(MAPSECTYPE_GIFT, 0) =
    2000; LocationIsDiamondPearlCompatible(2000) is true (asm/unk_02017FAC.s:69-88) so both the
    DP and the PtHGSS location words hold 2000 (src/pokemon.c:1275-1284).
    """
    a, b, c, d = (codec.HEADER_SIZE + i * codec.BLOCK_SIZE for i in range(4))
    plain = bytearray(codec.PARTY_MON_SIZE)
    struct.pack_into("<I", plain, 0, pid)
    # block A
    ability = row["abilities"][1] if row["abilities"][1] and pid & 1 else row["abilities"][0]
    struct.pack_into("<HHII", plain, a, species, 0, player["id"], 0)  # species, item, OTID, exp (level 1 = 0)
    struct.pack_into("<4B", plain, a + 0x0C, cycles, ability, 0, player["language"])
    # block B
    moves = [m for m, _ in row["moves"]]
    struct.pack_into("<4H", plain, b, *moves, *([0] * (4 - len(moves))))
    plain[b + 8 : b + 8 + len(moves)] = bytes(pp for _, pp in row["moves"])
    # isEgg (bit 30), hasNickname (bit 31) stays 0: SetEggStats writes NICKNAME_STRING, not the flag
    struct.pack_into("<I", plain, b + 0x10, sum(iv << (5 * i) for i, iv in enumerate(ivs)) | 1 << 30)
    gender = 1 if row["ratio"] > pid & 0xFF else 0  # GetGenderBySpeciesAndPersonality (src/pokemon.c:2094-2112)
    plain[b + 0x18] = gender << 1  # fatefulEncounter 0, form 0
    struct.pack_into("<HH", plain, b + 0x1C, METLOC_DAY_CARE_COUPLE, 0)  # EggLocation_PtHGSS, MetLocation_PtHGSS
    # block C
    struct.pack_into("<11H", plain, c, *codec.encode_name(EGG_NAME, 11))
    plain[c + 0x17] = player["version"]  # gGameVersion
    # block D
    struct.pack_into("<8H", plain, d, *player["name_raw"])
    plain[d + 0x10 : d + 0x13] = template_plain[d + 0x13 : d + 0x16]  # egg date = the save's own date (template met date)
    struct.pack_into("<HH", plain, d + 0x16, METLOC_DAY_CARE_COUPLE, 0)  # EggLocation_DP, MetLocation_DP
    plain[d + 0x1B] = BALL_POKE
    plain[d + 0x1C] = player["gender"] << 7  # metLevel 0 | otGender
    plain[d + 0x1E] = BALL_POKE  # HGSS_Pokeball
    # party tail: status 0, level 1, capsule 0, HP == max HP, then the stats; the mail/capsule
    # remainder (0x98..) is the template's own Mail_Init output, written by the same game
    hp, atk, dfn, spe, spa, spd = _egg_stats(row, ivs)
    struct.pack_into("<IBBHHHHHHH", plain, codec.TAIL_OFF, 0, 1, 0, hp, hp, atk, dfn, spe, spa, spd)
    plain[codec.TAIL_OFF + 0x10 :] = template_plain[codec.TAIL_OFF + 0x10 :]
    return bytes(plain)


def build_egg1(image: bytes, profile, species: int = 172, cycles: int = 1) -> tuple[bytes, dict]:
    row = EGG_SPECIES.get(species)
    if row is None:
        raise Refusal("bad_species", f"--species must be one of {sorted(EGG_SPECIES)}")
    if not 0 <= cycles <= 255:
        raise Refusal("bad_cycles", "--cycles must fit the friendship byte (0..255)")
    save = codec.parse_save(image, profile)
    p = save.profile
    party = save.party()
    if not party:
        raise Refusal("no_party", "the source party is empty; no template for the tail and the profile")
    if len(party) >= MAX_PARTY:
        raise Refusal("party_full", f"party already holds {len(party)} mons; no slot after the last one")
    player = save.player()
    src_sha1 = hashlib.sha1(image).hexdigest()
    pid = egg_pid(src_sha1, player["id"], {m["pid"] for m in party})
    seed = _seed(EGG_KIND + "-iv", src_sha1)
    ivs = tuple((seed >> (5 * i)) & 31 for i in range(6))
    mon_off = p.party_off + 8 + len(party) * codec.PARTY_MON_SIZE
    spans = [(mon_off, mon_off + codec.PARTY_MON_SIZE), (p.party_off + 4, p.party_off + 8)]

    def edit(data: bytearray) -> None:
        template = codec.decrypt_party(bytes(data[p.party_off + 8 : p.party_off + 8 + codec.PARTY_MON_SIZE]))
        plain = _egg_record(row, species, pid, ivs, cycles, player, template)
        data[mon_off : mon_off + codec.PARTY_MON_SIZE] = codec.encrypt_party(plain)
        struct.pack_into("<I", data, p.party_off + 4, len(party) + 1)

    out = _seal(image, save, edit)
    _verify_egg(image, out, save, party, species, cycles, player, pid, ivs, spans)
    return out, _row("egg1", EGG_NOTE, image, out, save, species=species, new_pid=pid, otid=player["id"],
                     cycles=cycles, slot=len(party), ivs=list(ivs))


def _verify_egg(src, out, save, party, species, cycles, player, pid, ivs, spans) -> None:
    got = codec.parse_save(out, save.profile)
    mons = got.party()
    if got.bank != save.bank or got.counter != save.counter or mons[:-1] != party or len(mons) != len(party) + 1:
        raise Refusal("verify", "bank, save counter or the existing party changed")
    egg = mons[-1]
    hp = _egg_stats(EGG_SPECIES[species], ivs)[0]
    want = {"species": species, "is_egg": True, "has_nickname": False, "nickname": EGG_NAME, "friendship": cycles,
                "otid": player["id"], "ot_name": player["name"], "pid": pid, "ball": BALL_POKE, "level": 1, "shiny": False,
                "met_level": 0, "egg_location": METLOC_DAY_CARE_COUPLE, "met_location": 0, "ivs": ivs, "held_item": 0,
                "origin_game": player["version"], "language": player["language"], "ot_gender": player["gender"],
                "tail_plausible": True, "hp": hp, "max_hp": hp}
    bad = {k: (egg[k], v) for k, v in want.items() if egg[k] != v}
    if bad or egg["key"] in {m["key"] for m in party}:
        raise Refusal("verify", f"the egg does not read back as built: {bad}")
    _only_changed(src, out, save, spans)


BUILDERS = {
    "party2": lambda image, a: build_party2(image, a.profile),
    "bag": lambda image, a: build_bag(image, a.profile, a.count),
    "egg1": lambda image, a: build_egg1(image, a.profile, a.species, a.cycles),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disclosed SYNTH setup for Gen 4 battery saves (O-33).")
    sub = parser.add_subparsers(dest="command", required=True)
    for kind, help_ in (("party2", "clone party mon 0 into party slot 1"),
                        ("bag", "put Poke Balls into the Balls pocket"),
                        ("egg1", "append one egg to the party")):
        cmd = sub.add_parser(kind, help=help_)
        cmd.add_argument("--profile", required=True, choices=PROFILES)
        cmd.add_argument("--src", required=True, type=Path, help="battery save to read (never modified)")
        cmd.add_argument("--out", required=True, type=Path, help="new battery save to write")
        if kind == "bag":
            cmd.add_argument("--count", type=int, default=10, help="Poke Balls to add (default 10)")
        if kind == "egg1":
            cmd.add_argument("--species", type=int, default=172, help=f"one of {sorted(EGG_SPECIES)} (default 172 Pichu)")
            cmd.add_argument("--cycles", type=int, default=1, help="egg cycles left in the friendship byte (default 1)")
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
        out_image, row = BUILDERS[args.command](image, args)
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
