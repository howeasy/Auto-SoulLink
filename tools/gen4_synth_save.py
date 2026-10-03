#!/usr/bin/env python3
"""Disclosed SYNTH setup (O-33) for the Gen 4 test rows: ``party2``, ``bag``, ``egg1``, ``party6``, ``species``, ``place``, ``lead_level``.

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

``party6`` and ``species`` (G2 producer plan section 4) reuse the party2 clone:

    python tools/gen4_synth_save.py party6  --profile hgss --src <battery> --out <path>
    python tools/gen4_synth_save.py species 25 --profile hgss --src <battery> --out <path>

* ``party6`` clones party slot 0 into every free slot up to 6 (each with its own deterministic
  non-shiny PID of the template's nature, the SYNTH nickname, count 6).  A save with 6 mons or
  none is refused; existing mons are never rewritten.  For the "party full -> caught mon goes to
  the PC" case;
* ``species <id>`` makes party slot 1 a SYNTH clone of slot 0 with that species id (from a
  one-mon source, exactly ``party2`` + the species; from a two-mon source whose slot 1 is a
  SYNTH clone, an in-place rewrite).  The id must be a real species of the profile
  (``data/games/gen4_<profile>/names.json`` non-placeholder: hgss 1..493, hge 1..1475 minus
  holes).  The block checksum is recomputed over the new plaintext (shuffle is by PID, which
  stays) and the form bits are cleared.  STAT LIMITATION: the repo holds no HGSS/hge base-stat
  table (``pokemon_data`` has types only), so the party tail (level, HP, five stats) and the
  exp/ability/moves/gender are CARRIED from the template, not recomputed for the new species:
  they are plausible and nature-consistent for the template, not the species' base stats.  The
  tail is repaired natively on the intended routes (pinned pret tree pokeheartgold ad7a3afa,
  E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold): the mon an NPC trade hands back is
  built and re-levelled by ``CalcMonLevelAndStats`` (src/npc_trade.c:232), and a deposit ->
  withdraw round trip recalculates through ``CopyBoxPokemonToPokemon`` (src/pokemon.c:3245).  The
  trade itself only reads the species, level and OTID.  ``tail_policy`` in the sidecar records this.
  ``species`` rewrites an existing slot 1 only when the source sidecar attests it (``out_sha1`` of
  the image and ``new_pid`` of the mon), because the nickname is player-editable.  Clone PIDs also
  avoid every PID already stored in the boxes.

``place`` (G2 producer plan section 4, research docs/gen4/research/synth_place_save_layout.md) puts the
player at a map position and sets story flags / vars so a story-gated site can be exercised natively:

    python tools/gen4_synth_save.py place --profile hgss --src <battery> --out <path> --map 192 --x 10 --y 20 --dir 1 \
        [--flag 2000=1 ...] [--var 0x4040=3 ...] [--height H]

A Location-only write is NOT coherent (CONTINUE restores the saved map objects wholesale and re-attaches the avatar to
the saved ``movement == 1`` object at its OLD coordinates, src/save_local_field_data.c:133-151, src/map_object.c:413-425,
src/player_avatar.c:169-180), so the tool writes, in the newest general block only:

* all five Locations of LocalFieldData (current, entrance, previous, dynamicWarp, specialSpawn; src/save_local_field_data.c:13-19)
  with warpId -1: the game's own fresh-state Locations (src/location_backup.c:10-24) and its warp-less spawns (src/scrcmd_c.c:4101)
  use -1 for "no warp event", and ``FieldTask`` only dereferences a warp when ``warpId != -1`` (src/field_warp_tasks.c:150), so
  every Location the game can resume from means "stand at x,y", not "arrive through warp N";
* the single active ``movement == 1`` SavedMapObject (the player): currentX/currentZ = x/y (Location.y is the north-south
  tile, the object's Z), initial/current/next facing = dir;
* the elevation: the restore copies savedObject->vecY into the object (src/map_object.c:494-496) and
  ``MapObject_ConvertXZToPositionVec`` recomputes only x and z (:520-535); ``sub_0205EAF0`` only creates the object's SysTask
  (:600-610) and ``sub_0205EFB4`` only touches flags and callbacks (:816-828), so nothing re-derives Y after the restore.  A
  place onto a DIFFERENT map than the source Location is therefore REFUSED (``height_required``) unless ``--height H`` is
  given; with it BOTH currentY (+0x28) and vecY (+0x2C, fx32 = H * 8 * 0x1000 = H << 15, from currentY = (vecY >> 3) / FX32_ONE,
  :639-641; the owner saves hold currentY 2 with vecY 0x10000) are written.  A same-map place keeps the source currentY/vecY
  (correct only where the destination tile has the same height; the sidecar says ``height_source: carried``);
* MAPOBJECTFLAG_ACTIVE cleared on every other saved object (the follower; NPCs are rebuilt from the map's events);
* PlayerSaveData.state = 0 (walking);
* the requested flags / vars (flag 0, temp flags >= 0x4000, ids >= NUM_FLAGS and vars outside 0x4000..0x416F are refused).

Offsets come from the pack (``profile.field_save``, generator tools/gen_gen4_pack.py) with an evidence class each:
vars/flags SOURCE+FILE (hgss) or DERIVED+FILE (hge), map objects FILE, player state SOURCE.  CORRECTION to the research:
the SavedMapObject offsets there (+0x8 facing, +0xC mapId, +0x1C.. coordinates) are the LocalMapObject ones; the saved
struct (include/map_object.h:6-33) has currentFacing +0xD, mapId +0x10, currentX/Y/Z +0x26/+0x28/+0x2A, and the list is
not at 0x12B8 (Pokedex/Daycare/PalPad/Misc sit between) but at 0x2348 (hgss) / 0x2CC0 (hge), measured on the owner saves.
The player entry own mapId is 1 on map 60 in every owner save (the object is KEEP, src/map_object.c:158), so it is
NOT written.  Map bounds are NOT checked (the pack holds no map dimensions): the sidecar records ``bounds_verified: false``.
Positive anchors: exactly one active ``movement == 1`` entry whose currentX/currentZ equal the source
Location.  Only the sector footer CRC is re-sealed (no per-array CRC).  OFFLINE: where the avatar lands is a physical card.

``lead_level`` (O-33) levels only the healthy base-form lead, preserving its
identity, IV/EV and moves. Base stats and growth EXP are read from the pinned
ROM a/0/0/2 and a/0/0/3, with the personal/growth member hashes in the sidecar.
The PID nature stat modifier and party HP/stat tail are recalculated; unknown
hg-engine nature/IV overrides refuse. The source remains read-only. Level12 is
an authored fixture, not PHYSICAL proof that a native battle is won.

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
# The offset model is only trusted after the bytes agree with it: every non-empty slot of these
# pockets must hold an item of that pocket's class, and at least one must (a positive anchor, so
# an all-empty read proves nothing).  Classes = the fieldPocket column of pret
# files/itemtool/itemdata/item_data.csv joined to include/constants/items.h by item name.
POCKET_CLASS = {
    "hgss": {
        "medicine": ((17, 54),),                # Potion .. Sacred Ash
        "balls": ((1, 16), (492, 500)),         # Master..Cherish, Fast..Park
        "berries": ((149, 212),),
        "mail": ((137, 148),),
    },
    # hge: the same join over hg-engine data/itemdata/itemdata.c (.fieldPocket per [ITEM_*]) and
    # include/constants/item.h; its additions (Pixie Plate-era items, Dream/Beast Ball, ...) are
    # classed too, so no id is accepted merely for being "new".
    "hge": {
        "medicine": ((17, 54), (134, 134), (591, 591), (645, 645), (708, 709), (852, 852), (903, 903),
                     (1231, 1251), (1257, 1257), (1606, 1606), (2684, 2684)),
        "balls": ((1, 16), (492, 500), (576, 576), (851, 851)),
        "berries": ((149, 212), (686, 686), (2651, 2683)),
        "mail": ((137, 148),),
    },
}

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


def synth_pid(src_sha1: str, template_pid: int, otid: int, kind: str = KIND, taken=()) -> int:
    """A deterministic clone PID: same nature (pid % 25) as the template, never shiny, never equal
    to the template or any PID in ``taken``.

    Candidates are ``25 * j + nature`` with ``j`` stepping (mod the count that fits in 32 bits),
    so the nature survives the wrap that a plain ``+ 25`` mod 2**32 would break."""
    nature, seed = template_pid % 25, _seed(kind, src_sha1)
    slots = ((1 << 32) - 1 - nature) // 25 + 1  # j in 0..slots-1 keeps 25 * j + nature below 2**32
    for i in range(256):
        pid = 25 * ((seed // 25 + i) % slots) + nature
        if pid != template_pid and pid not in taken and not _shiny(pid, otid):
            return pid
    raise Refusal("no_clone_pid", "no non-shiny clone PID in 256 candidates")


def _clone(raw: bytes, profile, pid: int, species: int | None = None) -> bytes:
    """Decrypted party record -> re-encrypted clone with ``pid`` and the SYNTH nickname.

    ``species`` (optional) rewrites block A's species and clears the form bits; the checksum is
    recomputed by encrypt_party.  The tail is NOT recomputed (see the module docstring).

    Every other field is carried over verbatim, so the record's stored tail (level, HP and
    the six stats) stays the record the game itself wrote.
    """
    plain = bytearray(codec.decrypt_party(raw))
    struct.pack_into("<I", plain, 0, pid)
    if species is not None:
        struct.pack_into("<H", plain, codec.HEADER_SIZE, species)
        plain[codec.HEADER_SIZE + codec.BLOCK_SIZE + 0x18] &= 0x07  # form lives in the top 5 bits
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


def build_lead_level(
    image: bytes, profile, rom_path, level=12, *, title=None
) -> tuple[bytes, dict]:
    """O-33 lead-only setup; ROM personal/growth facts, original identity and moves.

    SOURCE: pokemon.c:314-390,1898-1913,1991-2013; personal.h layout (stats
    0..5, growth 0x13), a/0/0/2 personal and a/0/0/3 growtbl in the pinned ROM.
    Only the lead record and newest general footer CRC change.
    """
    import ndspy.narc
    import ndspy.rom

    from tools import gen4_pins

    title = title or ("heartgold_hge" if profile == "hge" else "heartgold")
    if title not in gen4_pins.ROM_SPECS or (title == "heartgold_hge") != (profile == "hge"):
        raise Refusal("lead_level title/profile mismatch")
    rom_path = Path(rom_path)
    if not rom_path.is_file():
        raise Refusal(f"lead_level ROM absent: {rom_path}")
    raw_rom = rom_path.read_bytes()
    if hashlib.sha1(raw_rom).hexdigest() != gen4_pins.ROM_SPECS[title][0]:
        raise Refusal("lead_level wrong ROM")
    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 100:
        raise Refusal("lead_level level outside 1..100")
    save, party = _party_mons(image, profile)
    mon = party[0]
    if (
        not mon["tail_plausible"]
        or mon["is_egg"]
        or mon["form"]
        or mon["hp"] == 0
        or level <= mon["level"]
    ):
        raise Refusal("lead_level requires healthy base-form lead and increased level")
    at = save.profile.party_off + 8
    plain = bytearray(codec.decrypt_party(_raw_slots(image, save, 1)[0]))
    a, b = 8, 8 + 0x20  # decrypt_party returns LOGICAL A/B/C/D, not stored PID order
    # Codec does not decode hg-engine nature/IV overrides. Never carry an
    # unknown override into a purported recalculation; these inputs have none.
    if profile == "hge" and struct.unpack_from("<H", plain, b + 0x1A)[0] & 0xFFFE:
        raise Refusal("lead_level unsupported hge nature/IV override")
    rom = ndspy.rom.NintendoDSRom(raw_rom)
    personal = ndspy.narc.NARC(rom.getFileByName("a/0/0/2"))
    growth = ndspy.narc.NARC(rom.getFileByName("a/0/0/3"))
    if not 0 < mon["species"] < len(personal.files):
        raise Refusal("lead_level species absent from personal table")
    row = personal.files[mon["species"]]
    if len(row) != 44 or row[0] == 0 or row[0x13] >= len(growth.files):
        raise Refusal("lead_level invalid personal entry")
    table = growth.files[row[0x13]]
    if len(table) != 404:
        raise Refusal("lead_level invalid growth table")
    exp = struct.unpack_from("<I", table, level * 4)[0]
    base = list(row[:6])
    ivs = mon["ivs"]
    evs = mon["evs"]
    nature = mon["nature"]
    stats = [
        ((2 * base[i] + ivs[i] + evs[i] // 4) * level) // 100 + (level + 10 if i == 0 else 5)
        for i in range(6)
    ]
    if mon["species"] == 292:
        stats[0] = 1  # SOURCE pokemon.c:355-360 Shedinja special case
    up, down = nature // 5, nature % 5
    for index in range(5):
        if up != down:
            stats[index + 1] = (
                stats[index + 1] * (110 if index == up else 90 if index == down else 100) // 100
            )
    hp = min(stats[0], mon["hp"] + stats[0] - mon["max_hp"])
    plain[codec.TAIL_OFF + 4] = level
    struct.pack_into("<7H", plain, codec.TAIL_OFF + 6, hp, *stats)
    old_exp = struct.unpack_from("<I", plain, a + 8)[0]
    mask = (1 << save.profile.exp_bits) - 1
    if exp > mask:
        raise Refusal("lead_level exp exceeds profile field")
    struct.pack_into("<I", plain, a + 8, (old_exp & ~mask) | exp)
    record = codec.encrypt_party(bytes(plain))

    def edit(body):
        body[at : at + codec.PARTY_MON_SIZE] = record

    out = _seal(image, save, edit)
    _only_changed(image, out, save, [(at, at + codec.PARTY_MON_SIZE)])
    decoded = codec.parse_save(out, profile)
    got = decoded.party()[0]
    assert (
        got["level"] == level
        and got["exp"] == exp
        and got["max_hp"] == stats[0]
        and tuple(got["stats"]) == tuple(stats[1:])
    )
    assert (
        got["moves"] == mon["moves"]
        and got["pid"] == mon["pid"]
        and got["ivs"] == mon["ivs"]
        and got["evs"] == mon["evs"]
    )
    meta = _row(
        "lead_level",
        "SYNTH O-33 setup: lead level/stats recomputed; hooks/routes remain native",
        image,
        out,
        save,
        new_pid=mon["pid"],
        title=title,
        level_before=mon["level"],
        level_after=level,
        lead_species=mon["species"],
        tail_policy="ROM_RECOMPUTED",
        rom_sha1=hashlib.sha1(raw_rom).hexdigest(),
        personal_sha256=hashlib.sha256(row).hexdigest(),
        growth_sha256=hashlib.sha256(table).hexdigest(),
        personal_member=mon["species"],
        growth_member=row[0x13],
        base_stats=base,
        ivs=list(ivs),
        evs=list(evs),
        nature=nature,
        exp_after=exp,
        hp_after=hp,
        stats_after=stats,
        moves=list(mon["moves"]),
        moves_policy="UNCHANGED",
    )
    return out, meta


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
    """General-block offsets of the Bag array and the Balls pocket, or a named refusal.

    Invariant: any mode that writes the Bag must call ``check_bag_layout`` on the source first;
    these offsets are a model, not a measurement."""
    slots = BAG_SLOTS.get(profile.name)
    if slots is None or profile.party_off is None:
        raise Refusal("bag_layout_unknown", f"no source-derived Bag layout for profile {profile.name!r}")
    base = profile.party_off + PARTY_ARRAY_SIZE
    offs, at = {}, base
    for pocket in POCKETS:
        offs[pocket] = at
        at += 4 * slots[pocket]
    return {"bag_off": base, "balls_off": offs["balls"], "balls_slots": slots["balls"], "end": at + 4,
            "pockets": {name: (offs[name], slots[name]) for name in POCKETS}}


def check_bag_layout(general: bytes, profile, lay: dict) -> int:
    """Refuse (``bag_layout_unverified``) unless the saved bytes agree with the modelled pocket
    offsets; returns the number of positively classified slots.

    A swapped or shifted pocket model reads another pocket's items here, which are outside the
    class (a Potion is not a ball), so it refuses instead of writing at a wrong offset."""
    anchors = 0
    classes = POCKET_CLASS.get(profile.name)
    if classes is None:
        raise Refusal("bag_layout_unknown", f"no source-derived pocket classes for profile {profile.name!r}")
    for name, ranges in classes.items():
        off, n = lay["pockets"][name]
        gap = None
        for i in range(n):
            iid, qty = struct.unpack_from("<HH", general, off + 4 * i)
            if qty == 0 and iid == 0:
                gap = i if gap is None else gap
                continue
            # A real pocket is compacted to its front (PocketCompaction, src/bag.c:284-292, run after
            # every take; adds use the first empty slot), so an item after an empty slot means the
            # pocket is being read at a shifted offset.
            if gap is not None:
                raise Refusal("bag_layout_unverified", f"{name} slot {i} is occupied after empty slot {gap}")
            if not (any(lo <= iid <= hi for lo, hi in ranges) and 1 <= qty <= BAG_SLOT_QUANTITY_MAX):
                raise Refusal("bag_layout_unverified", f"{name} slot {i} holds item {iid} x{qty}: not that pocket's class")
            anchors += 1
    if not anchors:
        raise Refusal("bag_layout_unverified", "no medicine/ball/berry/mail item to confirm the pocket offsets against")
    return anchors


def build_bag(image: bytes, profile, count: int = 10) -> tuple[bytes, dict]:
    if not 1 <= count <= BAG_SLOT_QUANTITY_MAX:
        raise Refusal("bad_count", f"--count must be 1..{BAG_SLOT_QUANTITY_MAX}, got {count}")
    save = codec.parse_save(image, profile)
    lay = bag_layout(save.profile)
    party = save.party()  # a corrupt party refuses here, like party2
    block = save.blocks[(save.bank, 0)]
    if lay["end"] > block.size - save.profile.footer_size:
        raise Refusal("bag_layout", "the Bag array would run past the general block")
    check_bag_layout(save.general, save.profile, lay)
    slots = [struct.unpack_from("<HH", save.general, lay["balls_off"] + 4 * i) for i in range(lay["balls_slots"])]
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
    if not 0 <= cycles <= row["egg_cycles"]:  # SetEggStats starts the counter at BASE_EGG_CYCLES
        raise Refusal("bad_cycles", f"--cycles must be 0..{row['egg_cycles']} (the species' egg cycles)")
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


# ---------------------------------------------------------------------------
# party6 / species: more clones of party slot 0
# ---------------------------------------------------------------------------
PARTY6_NOTE = "SYNTH setup: party filled to 6 with clones of slot 0 for a native party-full catch test"
SPECIES_NOTE = "SYNTH setup: party slot 1 is a clone of slot 0 rewritten to the species an NPC trade asks for"
TAIL_POLICY = "carried from the template; not recomputed (no base-stat table for this profile)"


# Highest base species id.  hgss: Arceus 493 is the last vanilla species (Egg 494, Bad Egg 495 follow).
# hge: include/constants/species.h:1093 MAX_MON_NUM = SPECIES_PECHARUNT = 1075, and the mega/forme ids
# start at SPECIES_MEGA_START = 1076 (:1096); names.json marks every forme row with a ``base`` key.
MAX_SPECIES = {"hgss": 493, "hge": 1075}


def valid_species(profile_name: str) -> set:
    """Real BASE species ids of the profile: non-placeholder rows of the generated names pack that
    are not formes (no ``base`` key) and not above the profile MAX_MON_NUM."""
    names = json.loads((ROOT / "data" / "games" / f"gen4_{profile_name}" / "names.json").read_text(encoding="utf-8"))
    top = MAX_SPECIES[profile_name]
    return {int(k) for k, v in names["species"].items()
            if not v.get("placeholder") and "base" not in v and 0 < int(k) <= top}


def _party_mons(image: bytes, profile):
    save = codec.parse_save(image, profile)
    maxc = struct.unpack_from("<I", save.general, save.profile.party_off)[0]
    if maxc < MAX_PARTY:
        raise Refusal("party_max", f"PartyCore.maxCount is {maxc}; a 6-mon party needs {MAX_PARTY}")
    mons = save.party()
    if not mons:
        raise Refusal("no_party", "the source party is empty; there is nothing to clone")
    return save, mons


def _raw_slots(image: bytes, save, n: int) -> list:
    base = save.profile.party_off + 8
    general = codec.parse_save(image, save.profile).general
    return [general[base + i * codec.PARTY_MON_SIZE : base + (i + 1) * codec.PARTY_MON_SIZE] for i in range(n)]


def _box_pids(save) -> set:
    return {m["pid"] for box in save.boxes() for m in box["mons"].values()}


def _verify_clones(src, out, save, party, first: int, count: int, species, spans) -> None:
    """Re-decode: mons[:first] untouched, mons[first:count] are SYNTH clones of slot 0 (with
    ``species`` when given), all keys distinct, nothing outside ``spans`` changed."""
    got = codec.parse_save(out, save.profile)
    mons = got.party()
    if struct.unpack_from("<I", got.general, got.profile.party_off)[0] != MAX_PARTY:
        raise Refusal("verify", "PartyCore.maxCount is not 6")
    if got.bank != save.bank or got.counter != save.counter or len(mons) != count or mons[:first] != party[:first]:
        raise Refusal("verify", "bank, save counter, party count or the untouched mons changed")
    if _raw_slots(out, got, first) != _raw_slots(src, save, first):
        raise Refusal("verify", "an existing party slot is not byte-identical")
    template = mons[0]
    for mon in mons[first:]:
        same = _same_mon(mon, template) if species is None else (
            (mon["level"], mon["otid"], mon["nature"], mon["max_hp"], mon["stats"]) == (
                template["level"], template["otid"], template["nature"], template["max_hp"], template["stats"])
            and mon["species"] == species)
        if not (mon["tail_plausible"] and not mon["shiny"] and mon["nickname"] == NICKNAME and same):
            raise Refusal("verify", f"clone {mon['key']} does not read back as a SYNTH clone")
    if len({m["key"] for m in mons}) != count:
        raise Refusal("verify", "party keys are not distinct")
    _only_changed(src, out, save, spans)


def build_party6(image: bytes, profile) -> tuple[bytes, dict]:
    save, party = _party_mons(image, profile)
    p = save.profile
    if len(party) >= MAX_PARTY:
        raise Refusal("party_full", f"party already holds {len(party)} mons; nothing to fill")
    template = party[0]
    src_sha1 = hashlib.sha1(image).hexdigest()
    taken, pids = {m["pid"] for m in party} | _box_pids(save), {}
    for slot in range(len(party), MAX_PARTY):
        pids[slot] = synth_pid(src_sha1, template["pid"], template["otid"], f"party6:{slot}", taken)
        taken.add(pids[slot])
    off = p.party_off + 8

    def edit(data: bytearray) -> None:
        record = bytes(data[off : off + codec.PARTY_MON_SIZE])
        for slot, pid in pids.items():
            at = off + slot * codec.PARTY_MON_SIZE
            data[at : at + codec.PARTY_MON_SIZE] = _clone(record, p, pid)
        struct.pack_into("<I", data, p.party_off + 4, MAX_PARTY)

    out = _seal(image, save, edit)
    spans = [(p.party_off + 4, p.party_off + 8), (off + len(party) * codec.PARTY_MON_SIZE, off + MAX_PARTY * codec.PARTY_MON_SIZE)]
    _verify_clones(image, out, save, party, len(party), MAX_PARTY, None, spans)
    return out, _row("party6", PARTY6_NOTE, image, out, save, new_pids=list(pids.values()), slots=list(pids),
                     otid=template["otid"])


def _load_sidecar(src: Path) -> dict | None:
    try:
        return json.loads(Path(str(src) + SIDECAR_SUFFIX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_species(image: bytes, profile, species: int, sidecar: dict | None = None) -> tuple[bytes, dict]:
    """``sidecar`` = the ``<src>.synth.json`` of the source image: it attests that a slot-1 mon is this
    tool own clone (matching ``out_sha1`` of the image and ``new_pid`` of the mon).  The nickname is
    editable by the player, so it is not the guard."""
    save, party = _party_mons(image, profile)
    p = save.profile
    if species not in valid_species(p.name):
        raise Refusal("bad_species", f"species {species} is not a real {p.name} species id")
    if len(party) > 2:
        raise Refusal("party_too_big", f"party count is {len(party)}; this tool only touches slot 1")
    if len(party) == 2 and not (
            sidecar and sidecar.get("kind") in ("party2", "species") and sidecar.get("schema") == SCHEMA
            and sidecar.get("out_sha1") == hashlib.sha1(image).hexdigest() and sidecar.get("new_pid") == party[1]["pid"]):
        raise Refusal("slot1_unattested", "party slot 1 is not attested as a SYNTH clone by the source sidecar "
                      "(out_sha1 + new_pid); refusing to rewrite a mon this tool did not make")
    template = party[0]
    src_sha1 = hashlib.sha1(image).hexdigest()
    rewrite = len(party) == 2
    pid = party[1]["pid"] if rewrite else synth_pid(
        src_sha1, template["pid"], template["otid"], taken={m["pid"] for m in party} | _box_pids(save))
    off = p.party_off + 8
    at = off + CLONE_SLOT * codec.PARTY_MON_SIZE

    def edit(data: bytearray) -> None:
        source = at if rewrite else off  # a clone of slot 0, or slot 1 itself when it already is one
        data[at : at + codec.PARTY_MON_SIZE] = _clone(bytes(data[source : source + codec.PARTY_MON_SIZE]), p, pid, species)
        struct.pack_into("<I", data, p.party_off + 4, CLONE_SLOT + 1)

    out = _seal(image, save, edit)
    spans = [(p.party_off + 4, p.party_off + 8), (at, at + codec.PARTY_MON_SIZE)]
    _verify_clones(image, out, save, party, CLONE_SLOT, CLONE_SLOT + 1, species, spans)
    return out, _row("species", SPECIES_NOTE, image, out, save, species=species, new_pid=pid, otid=template["otid"],
                     slot=CLONE_SLOT, mode="rewrite" if rewrite else "clone", tail_policy=TAIL_POLICY)


# ---------------------------------------------------------------------------
# place: Location + player map object + flags / vars
# ---------------------------------------------------------------------------
PLACE_NOTE = "SYNTH setup: player placed on a map with story flags/vars set for a native story-gated test"
LOCATION_ARRAY_SPAN = 5 * 20            # current, entrance, previous, dynamicWarp, specialSpawn (src/save_local_field_data.c:13-19)
DIRECTIONS = (0, 1, 2, 3)               # DIR_NORTH/SOUTH/WEST/EAST (include/constants/global_fieldmap.h:5-8)
MAX_TILE = 0x7FFF                       # SavedMapObject coordinates are s16


def _field_save(profile_name: str) -> tuple[dict, int]:
    """(profile.field_save, general offset of the Location array) from the generated pack."""
    pack = json.loads((ROOT / "data" / "games" / f"gen4_{profile_name}" / "profile.json").read_text(encoding="utf-8"))
    for title in pack["titles"].values():
        prof = title["profile"]
        if "field_save" in prof:
            return prof["field_save"], prof["location"]["file_cross_check"]["general_off_of_array"]
    raise Refusal("place_layout_unknown", f"profile {profile_name!r} has no field_save layout in its pack")


def valid_maps() -> set:
    """Map header ids the pack knows (hgss area_map.json; hge keeps the vanilla ids, hge-only maps are not listed)."""
    maps = json.loads((ROOT / "data" / "games" / "gen4_hgss" / "area_map.json").read_text(encoding="utf-8"))["maps"]
    return {int(k) for k in maps}


def _pairs(items, what: str) -> dict:
    out = {}
    for item in items or ():
        try:
            key, value = str(item).split("=", 1)
            key, value = int(key, 0), int(value, 0)
        except ValueError:
            raise Refusal("bad_place_arg", f"--{what} {item!r} is not ID=VALUE") from None
        if out.get(key, value) != value:
            raise Refusal("bad_place_arg", f"--{what} {key:#x} is given two different values")
        out[key] = value
    return out


def check_place_args(map_id, x, y, direction, flags: dict, vars_: dict, height, fs: dict, source_map: int) -> None:
    nflags, vbase, vcount = fs["flags"]["count"], fs["vars"]["base_id"], fs["vars"]["count"]
    if map_id not in valid_maps():
        raise Refusal("bad_map", f"map id {map_id} is not in the pack map table")
    if map_id != source_map and height is None:
        raise Refusal("height_required", f"map {map_id} differs from the source map {source_map}: the game restores the saved "
                      "vecY and never re-derives it (src/map_object.c:494-496), so pass --height for the destination elevation")
    if not (0 <= x <= MAX_TILE and 0 <= y <= MAX_TILE):
        raise Refusal("bad_coord", f"x/y must be 0..{MAX_TILE}, got {x},{y}")
    if direction not in DIRECTIONS:
        raise Refusal("bad_dir", f"--dir must be one of {DIRECTIONS} (north south west east), got {direction}")
    if height is not None and not -0x8000 <= height <= MAX_TILE:
        raise Refusal("bad_coord", f"--height {height} does not fit an s16")
    for fid, value in flags.items():
        if fid == 0:
            raise Refusal("bad_flag", "flag id 0 is a no-op in the game (src/save_vars_flags.c:45-54)")
        if fid >= 0x4000:
            raise Refusal("bad_flag", f"flag {fid:#x} is a RAM-only temp flag (>= 0x4000); it is never saved")
        if not 0 < fid < nflags:
            raise Refusal("bad_flag", f"flag {fid} is outside 1..{nflags - 1}")
        if value not in (0, 1):
            raise Refusal("bad_flag", f"flag {fid} value must be 0 or 1, got {value}")
    for vid, value in vars_.items():
        if not vbase <= vid < vbase + vcount:
            raise Refusal("bad_var", f"var {vid:#x} is outside {vbase:#x}..{vbase + vcount - 1:#x}")
        if not 0 <= value <= 0xFFFF:
            raise Refusal("bad_var", f"var {vid:#x} value must fit a u16, got {value}")


def build_place(image: bytes, profile, map_id: int, x: int, y: int, direction: int, flags=(), vars_=(),
                height: int | None = None) -> tuple[bytes, dict]:
    flags, vars_ = _pairs(flags, "flag"), _pairs(vars_, "var")
    save = codec.parse_save(image, profile)
    p = save.profile
    fs, loc_off = _field_save(p.name)
    party = save.party()
    g = save.general
    mo, F = fs["map_objects"], fs["map_objects"]["fields"]
    state_at = loc_off + fs["player_state"]["state_off_in_local_field"]
    if mo["general_off"] + mo["count"] * mo["stride"] > len(g) or fs["flags"]["general_off"] + fs["flags"]["bytes"] > len(g):
        raise Refusal("place_layout", "the field_save layout runs past the general block")

    def entry(i: int) -> int:
        return mo["general_off"] + i * mo["stride"]

    active = [i for i in range(mo["count"])
              if struct.unpack_from("<I", g, entry(i) + F["flags"])[0] & mo["active_mask"]]
    players = [i for i in active if g[entry(i) + F["movement"]] == 1]
    if len(players) != 1:
        raise Refusal("place_layout_unverified", f"{len(players)} active movement==1 map objects (need exactly one: the player)")
    pl = players[0]
    here = struct.unpack_from("<5i", g, loc_off)
    cx = struct.unpack_from("<h", g, entry(pl) + F["currentX"])[0]
    cz = struct.unpack_from("<h", g, entry(pl) + F["currentZ"])[0]
    if (cx, cz) != (here[2], here[3]):
        raise Refusal("place_layout_unverified", f"player object at ({cx},{cz}) != Location ({here[2]},{here[3]}): offsets are wrong")
    check_place_args(map_id, x, y, direction, flags, vars_, height, fs, here[0])
    others = [i for i in active if i != pl]
    state_before = struct.unpack_from("<i", g, state_at)[0]
    o = entry(pl)
    fb = fs["flags"]["general_off"]
    vb, vbase = fs["vars"]["general_off"], fs["vars"]["base_id"]
    vec = None if height is None else height << fs["map_objects"]["height_to_vecY_shift"]  # fx32: currentY * 8 * FX32_ONE

    spans = [(loc_off, loc_off + LOCATION_ARRAY_SPAN), (state_at, state_at + 4),
             (o + F["initialFacing"], o + F["currentFacing"] + 2),  # initial, current, next facing
             (o + F["currentX"], o + F["currentX"] + 2), (o + F["currentZ"], o + F["currentZ"] + 2)]
    if height is not None:
        spans += [(o + F["currentY"], o + F["currentY"] + 2), (o + F["vecY"], o + F["vecY"] + 4)]
    spans += [(entry(i) + F["flags"], entry(i) + F["flags"] + 4) for i in others]
    spans += [(fb + fid // 8, fb + fid // 8 + 1) for fid in flags]
    spans += [(vb + 2 * (vid - vbase), vb + 2 * (vid - vbase) + 2) for vid in vars_]

    def edit(data: bytearray) -> None:
        for k in range(5):
            struct.pack_into("<5i", data, loc_off + 20 * k, map_id, -1, x, y, direction)
        struct.pack_into("<i", data, state_at, 0)
        data[o + F["initialFacing"] : o + F["currentFacing"] + 2] = bytes([direction]) * 3
        struct.pack_into("<h", data, o + F["currentX"], x)
        struct.pack_into("<h", data, o + F["currentZ"], y)
        if height is not None:
            struct.pack_into("<h", data, o + F["currentY"], height)
            struct.pack_into("<i", data, o + F["vecY"], vec)
        for i in others:
            at = entry(i) + F["flags"]
            struct.pack_into("<I", data, at, struct.unpack_from("<I", data, at)[0] & ~mo["active_mask"])
        for fid, value in flags.items():
            data[fb + fid // 8] = (data[fb + fid // 8] & ~(1 << fid % 8) & 0xFF) | (value << fid % 8)
        for vid, value in vars_.items():
            struct.pack_into("<H", data, vb + 2 * (vid - vbase), value)

    out = _seal(image, save, edit)
    want = {"loc": (map_id, -1, x, y, direction), "pl": pl, "x": x, "z": y, "dir": direction,
            "height": height, "vecY": vec, "flags": flags, "vars": vars_, "state_at": state_at}
    _verify_place(image, out, save, party, fs, loc_off, want, spans)
    layout = {k: {"general_off": fs[k]["general_off"], "evidence_class": fs[k]["evidence_class"]}
              for k in ("vars", "flags", "map_objects")}
    layout["player_state"] = {"general_off": state_at, "evidence_class": fs["player_state"]["evidence_class"]}
    cy = struct.unpack_from("<h", g, o + F["currentY"])[0] if height is None else height
    return out, _row("place", PLACE_NOTE, image, out, save, map=map_id, x=x, y=y, dir=direction, height=cy, vecY=(
                         struct.unpack_from("<i", g, o + F["vecY"])[0] if vec is None else vec),
                     height_source="given" if height is not None else "carried",
                     height_note="vecY is restored from the save and never re-derived (src/map_object.c:494-496, 502-512, 520-535); "
                                 "vecY = currentY << 15 (:639-641); carried = the source elevation, valid only on the same map",
                     bounds_verified=False,
                     bounds_note="no map dimensions in the pack: x/y are range-checked as s16 only, not against the map size",
                     flags={str(k): v for k, v in sorted(flags.items())}, vars={f"{k:#x}": v for k, v in sorted(vars_.items())},
                     player_entry=pl, cleared_entries=others, location_before=list(here), state_before=state_before,
                     layout=layout, coherence="Location x5 + player map object + other objects inactive + player state 0")


def _verify_place(src, out, save, party, fs, loc_off, want, spans) -> None:
    """Raw re-read of every written field from the output image, independent of the writer arithmetic."""
    got = codec.parse_save(out, save.profile)
    if got.bank != save.bank or got.counter != save.counter or got.party() != party:
        raise Refusal("verify", "bank, save counter or party changed")
    g, mo, F = got.general, fs["map_objects"], fs["map_objects"]["fields"]
    if any(struct.unpack_from("<5i", g, loc_off + 20 * k) != want["loc"] for k in range(5)):
        raise Refusal("verify", "a Location does not read back as written")
    if struct.unpack_from("<i", g, want["state_at"])[0] != 0:
        raise Refusal("verify", "player state is not 0")
    at = [mo["general_off"] + i * mo["stride"] for i in range(mo["count"])]
    active = [i for i, a in enumerate(at) if struct.unpack_from("<I", g, a + F["flags"])[0] & mo["active_mask"]]
    pl = want["pl"]
    o = at[pl]
    if active != [pl] or g[o + F["movement"]] != 1:
        raise Refusal("verify", f"active objects {active}, expected only the player entry {pl}")
    if (struct.unpack_from("<h", g, o + F["currentX"])[0], struct.unpack_from("<h", g, o + F["currentZ"])[0]) != (want["x"], want["z"]):
        raise Refusal("verify", "player object coordinates do not read back")
    if tuple(g[o + F["initialFacing"] : o + F["currentFacing"] + 2]) != (want["dir"],) * 3:
        raise Refusal("verify", "player object facing does not read back")
    g0 = codec.parse_save(src, save.profile).general
    if want["height"] is not None:
        if (struct.unpack_from("<h", g, o + F["currentY"])[0], struct.unpack_from("<i", g, o + F["vecY"])[0]) != (want["height"], want["vecY"]):
            raise Refusal("verify", "player object currentY / vecY do not read back")
    elif g[o + F["currentY"] : o + F["currentY"] + 2] != g0[o + F["currentY"] : o + F["currentY"] + 2] or (
            g[o + F["vecY"] : o + F["vecY"] + 4] != g0[o + F["vecY"] : o + F["vecY"] + 4]):
        raise Refusal("verify", "the carried elevation (currentY / vecY) changed")
    for fid, value in want["flags"].items():
        if (g[fs["flags"]["general_off"] + fid // 8] >> fid % 8) & 1 != value:
            raise Refusal("verify", f"flag {fid} does not read back")
    for vid, value in want["vars"].items():
        if struct.unpack_from("<H", g, fs["vars"]["general_off"] + 2 * (vid - fs["vars"]["base_id"]))[0] != value:
            raise Refusal("verify", f"var {vid:#x} does not read back")
    _only_changed(src, out, save, spans)


BUILDERS = {
    "lead_level": lambda image,a: build_lead_level(image,a.profile,a.rom,a.level,title=a.title),
    "party2": lambda image, a: build_party2(image, a.profile),
    "bag": lambda image, a: build_bag(image, a.profile, a.count),
    "egg1": lambda image, a: build_egg1(image, a.profile, a.species, a.cycles),
    "party6": lambda image, a: build_party6(image, a.profile),
    "place": lambda image, a: build_place(image, a.profile, a.map_id, a.x, a.y, a.direction, a.flag, a.var, a.height),
    "species": lambda image, a: build_species(image, a.profile, a.species_id, _load_sidecar(a.src)),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disclosed SYNTH setup for Gen 4 battery saves (O-33).")
    sub = parser.add_subparsers(dest="command", required=True)
    for kind, help_ in (("party2", "clone party mon 0 into party slot 1"),
                        ("bag", "put Poke Balls into the Balls pocket"),
                        ("egg1", "append one egg to the party"),
                        ("party6", "fill the party to 6 with clones of slot 0"),
                        ("species", "make party slot 1 a clone of slot 0 with the given species id"),
                        ("place", "place the player on a map and set story flags / vars"),
                        ("lead_level", "level the lead using ROM stats/growth; preserve moves and identity")):
        cmd = sub.add_parser(kind, help=help_)
        cmd.add_argument("--profile", required=True, choices=PROFILES)
        cmd.add_argument("--src", required=True, type=Path, help="battery save to read (never modified)")
        cmd.add_argument("--out", required=True, type=Path, help="new battery save to write")
        if kind=="lead_level":
            cmd.add_argument("--rom",required=True,type=Path)
            cmd.add_argument("--title",required=True,choices=['heartgold','heartgold_hge','soulsilver'])
            cmd.add_argument("--level",type=int,default=12)
        if kind == "bag":
            cmd.add_argument("--count", type=int, default=10, help="Poke Balls to add (default 10)")
        if kind == "place":
            cmd.add_argument("--map", dest="map_id", required=True, type=int, help="map header id")
            cmd.add_argument("--x", required=True, type=int, help="tile x")
            cmd.add_argument("--y", required=True, type=int, help="tile y (Location.y, the north-south tile)")
            cmd.add_argument("--dir", dest="direction", required=True, type=int, help="0 north, 1 south, 2 west, 3 east")
            cmd.add_argument("--flag", action="append", metavar="N=0|1", help="save flag (repeatable)")
            cmd.add_argument("--var", action="append", metavar="0x40xx=V", help="save var (repeatable)")
            cmd.add_argument("--height", type=int, help="object currentY; omitted = carried from the source")
        if kind == "species":
            cmd.add_argument("species_id", metavar="ID", type=int, help="species id (profile range, see names.json)")
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
