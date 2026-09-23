"""PHYSICAL lane for P3b.3a: the live inspect gate (docs/gen2/gen2_requirements.md R-1, R-2, R-3,
R-5g; docs/gen2/GEN2_BINDING_PLAN.md P3b.3a).

    SLINK_LIVE=1 pytest tests/live/test_gen2_new_gates.py -q

Each case boots ONE of the eight qualified fixtures (tests/fixtures/gen2/<name>.SaveRAM, from
tools/gen2_fixtures.FIXTURES) warm on the real cartridge, runs lua/tests/gen2_inspect_gate.lua,
and decodes the SAME captured bytes with server/adapters/gen2_codec.py (PYDEC): Lua on hardware
and Python on the same bytes must agree field for field. Skipped, never hung, without EmuHawk, the
pinned decomp/ROM build, a qualified fixture or its qualification receipt -- and the release runner
(tools/verify_gen2_release.py) counts a skip as a failure, so a missing input is a hard failure
here too, never a silent pass.

Binding (R4 review): the staged fixture's sha256 and its expected OT come from its qualification
receipt (tests/fixtures/gen2/receipts/<name>.qualification.json, a passed full-chain
tools/fixture_qualification report), never from the capture itself; run_gb_gate accepts any
existing candidate file (tools/run_gb_gate.py:297-301), so a swapped file is refused HERE. The
capture's frame, physical domain/offset, logical address/bank and lengths are checked exactly, and
every Lua decode is bound to the captured bytes through its own raw_hex (verify_capture).

SCOPE (P3b.3a only): this file currently carries ONLY the live inspect rows -- R-1 (party/box/name
decode) and R-2 (independent stat recomputation). Its R-3 row is now the TILEMAP display half:
GAME_TRAINER_CARD reads the game's own rendered Trainer Card back through a title-keyed charmap and
against the captured wPlayerID/wPlayerName, so R-3's tilemap half is CLOSED here. R-3's badge half
stays OPEN -- Johto/Kanto badges are VRAM tiles animated as OAM, invisible to a wTilemap oracle, and
need an OAM/VRAM witness. R-5g's display half is likewise CLOSED by GAME_STATS_HEAD (the (18,0)
gender glyph and (19,0) shiny marker re-derived here from the same DVs); the DV-formula cross-check
(GENDER_SHINY) stays as its internal twin. The PC box header stays OUT OF SCOPE: Elm's lab has no PC.
The engine-signal (P3b.4), write-window (P3b.5) and client-conformance (P3b.6/P3b.7) rows belong
in this same file per docs/gen2/GEN2_BINDING_PLAN.md's P3b table, but land as separate, later
cards, each owning its own function/block here (the §7 one-writer-per-file-at-a-time rule); this
card claims none of that coverage and tools/verify_gen2_release.py's "live-new-gates" lane stays
UNIMPLEMENTED until they do.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from server.adapters import gen2_codec as codec  # noqa: E402
from server.adapters.gen2_rom_scan import Rom  # noqa: E402
from tools import fixture_qualification, gen2_fixtures, gen2_source_data  # noqa: E402
from tools.gen2_fixtures import FIXTURES  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_inspect_gate.lua"
RECEIPTS = "tests/fixtures/gen2/receipts"
CART_RAM_BYTES = 0x8000
BADGE_FIELDS = ("johto", "kanto")


# --- shared, importable, BizHawk-free logic (tests/unit/test_gen2_inspect_gate.py exercises it) ---

_LINE = re.compile(r"^([A-Z][A-Z0-9_]*) (.*)$", re.M)


def tagged_lines(text: str) -> dict[str, list[str]]:
    """Every `TAG <rest>` line this gate prints, grouped by tag, in file order."""
    out: dict[str, list[str]] = {}
    for tag, rest in _LINE.findall(text):
        out.setdefault(tag, []).append(rest)
    return out


def tag_json(text: str, tag: str):
    lines = tagged_lines(text).get(tag)
    if not lines:
        raise AssertionError(f"gate printed no {tag!r} line")
    return json.loads(lines[0])


def fixture_missing_reason(name: str, *, repo: Path = REPO) -> str | None:
    """None when the fixture is present; a clear skip reason otherwise (never a silent pass)."""
    path = repo / "tests/fixtures/gen2" / f"{name}.SaveRAM"
    if not path.exists():
        return f"{path.relative_to(repo).as_posix()} not present (build it with tools/gen2_fixtures.py)"
    return None


def receipt_missing_reason(name: str, *, repo: Path = REPO) -> str | None:
    path = repo / RECEIPTS / f"{name}.qualification.json"
    if not path.exists():
        return f"{path.relative_to(repo).as_posix()} not present (no qualification receipt for this fixture)"
    return None


def rom_missing_reason(title: str, *, repo: Path = REPO) -> str | None:
    """None when the pinned decomp/ROM build for `title` is available; a clear skip reason otherwise."""
    try:
        gen2_source_data.load_context(title, root=repo)
    except Exception as exc:  # noqa: BLE001 - any missing/invalid build input just skips this gate
        return f"{title}: pinned Gen 2 ROM build unavailable ({exc})"
    return None


def qualified_identity(name: str, fixture_bytes: bytes, *, repo: Path = REPO) -> int:
    """The expected OT of the STAGED bytes, from the fixture's own qualification receipt.

    The receipt must be a passed full-chain report whose row for `name` recorded exactly these bytes
    (artifacts.fixture.sha256) and whose independent PYDEC qualify stage recorded the player ID. A
    crystal_town file copied under the crystal_town_ot2 name fails the hash binding here."""
    path = repo / RECEIPTS / f"{name}.qualification.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    chain = fixture_qualification.FULL_CHAIN
    if (report.get("schema") != "fixture-qualification-v1" or report.get("scope") != "full"
            or report.get("passed") is not True or report.get("required_stages") != list(chain)
            or not isinstance(report.get("attempt_id"), str) or not report["attempt_id"]):
        raise AssertionError(f"{name}: receipt is not a passed full-chain qualification report")
    if report.get("errors") != []:
        raise AssertionError(f"{name}: qualification report has errors")
    rows = report.get("fixtures")
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or rows[0].get("name") != name or rows[0].get("passed") is not True):
        raise AssertionError(f"{name}: receipt has no single passed row for this fixture")
    row = rows[0]
    if row.get("problems") != []:
        raise AssertionError(f"{name}: qualification row has problems")
    provenance = row.get("provenance")
    if (not isinstance(provenance, dict)
            or set(provenance) != {"title", "rom_sha1", "scope", "route_facts_sha256"}
            or any(not isinstance(value, str) or not value for value in provenance.values())):
        raise AssertionError(f"{name}: fixture provenance is missing")
    spec = gen2_fixtures.BY_NAME.get(name)
    if spec is None or provenance["title"] != spec.title or provenance["scope"] != "candidate fixture":
        raise AssertionError(f"{name}: fixture title or scope differs from its source plan")
    source = gen2_source_data.load_context(spec.title, root=repo).source_record()
    if provenance["rom_sha1"] != source["rom_sha1"]:
        raise AssertionError(f"{name}: ROM SHA-1 differs from the pinned source")
    # qualify() records the hash of the complete route-facts dict (including its fingerprint).
    facts = gen2_fixtures.route_facts(spec.title, repo)
    if provenance["route_facts_sha256"] != gen2_fixtures._facts_sha256(facts):
        raise AssertionError(f"{name}: route facts differ from the pinned source")
    outputs = {"qualify": set(), "boot": {"boot:game_witness"},
               "resave": {"resave:fixture", "resave:save_witness", "resave:reload_witness"},
               "post_oracle": set()}
    inputs = {"fixture", "profile", "rom", "route_facts", "played_receipt"}
    artifacts = row.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != inputs | set().union(*outputs.values()):
        raise AssertionError(f"{name}: artifact provenance is incomplete")
    for record in artifacts.values():
        if (not isinstance(record, dict) or set(record) != {"path", "size", "sha256"}
                or not isinstance(record["path"], str) or not record["path"]
                or type(record["size"]) is not int or record["size"] < 0
                or not isinstance(record["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None):
            raise AssertionError(f"{name}: artifact provenance is malformed")
    recorded = artifacts["fixture"]["sha256"]
    if recorded != hashlib.sha256(fixture_bytes).hexdigest() or artifacts["fixture"]["size"] != len(fixture_bytes):
        raise AssertionError(f"{name}: staged fixture bytes differ from the qualified candidate "
                             f"(receipt sha256 {recorded})")
    stages = row.get("stages")
    if (not isinstance(stages, list) or len(stages) != len(chain)
            or any(not isinstance(stage, dict) for stage in stages)
            or [stage.get("stage") for stage in stages] != list(chain)):
        raise AssertionError(f"{name}: receipt has no complete ordered full-chain")
    snapshot = {role: artifacts[role] for role in inputs}
    previous = []
    for stage_name, stage in zip(chain, stages, strict=True):
        if (stage.get("status") != "PASS" or stage.get("problems") != []
                or not isinstance(stage.get("evidence"), dict) or not stage["evidence"]
                or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
                       for key, value in stage["evidence"].items())):
            raise AssertionError(f"{name}: {stage_name} stage is not a problem-free PASS")
        stage_outputs = stage.get("outputs", {})
        if not isinstance(stage_outputs, dict) or set(stage_outputs) != outputs[stage_name]:
            raise AssertionError(f"{name}: artifact provenance has missing stage outputs")
        # The runner hashes the current artifacts and every preceding receipt into each stage.
        fingerprint = hashlib.sha256(json.dumps({"attempt": report["attempt_id"], "fixture": name,
            "scope": "full", "chain": chain, "stage": stage_name, "provenance": provenance,
            "artifacts": snapshot, "previous": previous}, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        if stage.get("fingerprint") != fingerprint:
            raise AssertionError(f"{name}: {stage_name} stage fingerprint differs from its inputs")
        if any(artifacts[role] != record for role, record in stage_outputs.items()):
            raise AssertionError(f"{name}: artifact provenance differs from stage outputs")
        snapshot.update(stage_outputs)
        previous.append(stage)
    if snapshot != artifacts:
        raise AssertionError(f"{name}: artifact provenance is incomplete")
    player_id = stages[0]["evidence"].get("player_id")
    if not (isinstance(player_id, str) and player_id.isdigit() and int(player_id) <= 0xFFFF):
        raise AssertionError(f"{name}: receipt carries no qualified player ID")
    return int(player_id)


def _lua_to_py(mon: dict) -> dict:
    """The Lua decode is already field-shaped like gen2_codec's output; only strip the Lua-only
    `slot`/`species_marker` bookkeeping fields the comparison below walks from the PYDEC side."""
    return dict(mon)


def compare_mon(lua_mon: dict, py_mon: dict, *, where: str) -> None:
    """Field-for-field equality, PYDEC's keys against the Lua decode. Raises AssertionError on
    the FIRST disagreeing field -- this is what a mutated byte or a wrong-fixture dump trips."""
    if lua_mon is None:
        raise AssertionError(f"{where}: Lua produced no record")
    lua_mon = _lua_to_py(lua_mon)
    for field, want in py_mon.items():
        got = lua_mon.get(field)
        if got != want:
            raise AssertionError(f"{where}: field {field!r} disagrees: lua={got!r} pydec={want!r}")


def compare_collection(lua_collection: dict, py_collection: dict, *, where: str) -> None:
    """Count, the decoded bytes themselves (raw_hex: both decoders read the SAME capture) and every
    record field for field."""
    if lua_collection is None:
        raise AssertionError(f"{where}: Lua produced no collection")
    if lua_collection["count"] != py_collection["count"]:
        raise AssertionError(f"{where}: count disagrees: lua={lua_collection['count']} "
                             f"pydec={py_collection['count']}")
    if lua_collection.get("raw_hex") != py_collection["raw_hex"]:
        raise AssertionError(f"{where}: Lua decoded other bytes than the capture PYDEC decoded")
    for slot, (lua_mon, py_mon) in enumerate(zip(lua_collection["mons"], py_collection["mons"], strict=True)):
        compare_mon(lua_mon, py_mon, where=f"{where} slot {slot}")


def compare_badges(lua_badges: dict, raw_badges: dict, *, where: str) -> None:
    """The declared fields only (reads.lua adds raw_hex/evidence/snapshot_qualified), plus reads.lua's
    own raw_hex against the second reader's two bytes."""
    if not isinstance(lua_badges, dict) or not isinstance(raw_badges, dict):
        raise AssertionError(f"{where}: badge record missing")
    for field in BADGE_FIELDS:
        if type(raw_badges.get(field)) is not int or lua_badges.get(field) != raw_badges[field]:
            raise AssertionError(f"{where}: badge field {field!r} disagrees: lua={lua_badges.get(field)!r} "
                                 f"raw={raw_badges.get(field)!r}")
    if lua_badges.get("raw_hex") != "".join(f"{raw_badges[field]:02x}" for field in BADGE_FIELDS):
        raise AssertionError(f"{where}: badge raw_hex disagrees with the independent re-read")


def identity_matches(party: dict, expected_ot_id: int) -> bool:
    """R-1's wrong-fixture control: a fixture's first party mon must carry the OT its qualification
    receipt recorded (qualified_identity). Given another fixture's OT this returns False rather than
    raising, so a caller can assert the refusal explicitly."""
    if not party.get("mons"):
        return False
    return party["mons"][0]["ot_id"] == expected_ot_id


def gender_and_shiny(dv_word: int, gender_ratio: int) -> tuple[str, bool]:
    """Independent Python reimplementation of GetGender/the shiny check (engine/pokemon/
    mon_stats.asm; engine/gfx/color.asm), matching lua/tests/gen2_inspect_gate.lua's
    G.gender_and_shiny byte for byte but authored separately -- neither side imports the other.
    A formula cross-check only: R-5g needs the game's own display and stays OPEN."""
    attack = (dv_word >> 12) & 0xF
    defense = (dv_word >> 8) & 0xF
    speed = (dv_word >> 4) & 0xF
    special = dv_word & 0xF
    shiny = (attack // 2) % 2 == 1 and defense == 10 and speed == 10 and special == 10
    if gender_ratio == 255:
        gender = "genderless"
    elif gender_ratio == 254:
        gender = "female"
    elif gender_ratio == 0:
        gender = "male"
    else:
        gender = "female" if (attack * 16 + speed) <= gender_ratio else "male"
    return gender, shiny


def wram_offset(bank: int, address: int, length: int) -> int:
    """CGB flat WRAM domain offset of a named-bank range (Pan Docs; the gate's G.wram_offset twin)."""
    if bank == 0 and address >= 0xC000 and address + length <= 0xD000:
        return address - 0xC000
    if 1 <= bank <= 7 and address >= 0xD000 and address + length <= 0xE000:
        return bank * 0x1000 + address - 0xD000
    raise AssertionError(f"WRAM range ${address:X}+{length} outside its bank {bank} window")


# --- R-3/R-5g display oracle: the tiles the game writes into wTilemap ---------------------------
#
# A title-keyed byte -> glyph table for the only tiles the display oracle reads. Crystal values come
# from constants/charmap.asm:97,193,199,201-210; Gold/Silver values were RE-READ from
# pokegold/constants/charmap.asm (pret/pokegold backs both carts): the A-Z ($80-$99), a-z ($A0-$B9)
# and digit ($F6-$FF) runs, "♂" ($EF), "♀" ($F5), "⁂" ($3F), the blank ' ' ($7F), the '@' string
# terminator ($50) and '-' ($E3) are byte-for-byte identical across the three titles. Pinned here
# rather than read from data/games/gen2_<title>/charmap.lua so the decode is independent of the pack
# the gate itself loads.
_LETTERS = {0x80 + index: char for index, char in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
_LETTERS.update({0xA0 + index: char for index, char in enumerate("abcdefghijklmnopqrstuvwxyz")})
_DIGITS = {0xF6 + index: str(index) for index in range(10)}
CHARMAP: dict[str, dict[int, str]] = {
    title: {**_LETTERS, **_DIGITS, 0x7F: " ", 0x50: "@", 0xE3: "-", 0xEF: "♂", 0xF5: "♀", 0x3F: "⁂"}
    for title in ("crystal", "gold", "silver")
}
BLANK_BYTE = 0x7F
GENDER_BYTE = {"male": 0xEF, "female": 0xF5, "genderless": BLANK_BYTE}
SHINY_BYTE = 0x3F
# The stats GREEN page prints .Item at (0,8) and the name after it at (8,8) in Crystal
# (engine/pokemon/stats_screen.asm:726-733) but at (6,8) in Gold/Silver (:567-577). No item prints
# .ThreeDashes "---" (C :755-757, G :610-614).
ITEM_COLUMN = {"crystal": 8, "gold": 6, "silver": 6}
NO_ITEM_TEXT = "---"


def decode_cells(title: str, raw_hex: str) -> str:
    """The printable text of a run of wTilemap cell bytes, through the pinned title charmap."""
    glyphs = CHARMAP[title]
    out = []
    for byte in bytes.fromhex(raw_hex):
        if byte not in glyphs:
            raise AssertionError(f"{title}: tilemap byte ${byte:02X} has no pinned glyph")
        out.append(glyphs[byte])
    return "".join(out)


def decode_terminated(title: str, raw_hex: str) -> str:
    """A NUL-terminated RAM name's text up to the '@' ($50) tile, through the pinned title charmap."""
    glyphs = CHARMAP[title]
    out = []
    for byte in bytes.fromhex(raw_hex):
        if byte == 0x50:
            break
        if byte not in glyphs:
            raise AssertionError(f"{title}: name byte ${byte:02X} has no pinned glyph")
        out.append(glyphs[byte])
    return "".join(out)


def _normalize(text: str) -> str:
    return text.replace("é", "E").replace("É", "E").upper()


def verify_display(text: str, title: str, py_party: dict, species: dict) -> None:
    """R-3/R-5g display rows: the game's OWN rendered tilemap, decoded and re-derived here.

    Trainer Card: the (5,4) five digit tiles must render the captured wPlayerID zero-padded to five
    (wPlayerID is not in the party blob, so the gate's raw wPlayerID bytes ride on the line), and the
    (7,2) cells must render wPlayerName. Stats head: the (18,0) gender glyph and (19,0) shiny marker
    are re-derived from the lead mon's DVs and its species gender ratio -- a genderless or non-shiny
    mon must leave the blank tile -- and the GREEN page's item line must carry the game's no-item
    text. Each Lua-decoded field is also compared against this module's own decode of the raw bytes.
    """
    if not py_party.get("mons"):
        raise AssertionError(f"{title}: display oracle needs a party mon")
    lead = py_party["mons"][0]
    glyphs = CHARMAP[title]

    card = tag_json(text, "GAME_TRAINER_CARD")
    if type(card.get("frame")) is not int or card["frame"] < 1:
        raise AssertionError(f"{title}: trainer card frame missing or invalid: {card.get('frame')!r}")
    if card.get("blank_byte") != BLANK_BYTE:
        raise AssertionError(f"{title}: card blank tile {card.get('blank_byte')!r} != ${BLANK_BYTE:02X}")
    id_hex = card["id_digits_hex"]
    if len(id_hex) != 10:
        raise AssertionError(f"{title}: trainer card ID row is not five cells: {id_hex!r}")
    id_text = decode_cells(title, id_hex)
    expected_id = f"{int(card['player_id_hex'], 16):05d}"
    if len(card["player_id_hex"]) != 4:
        raise AssertionError(f"{title}: wPlayerID is not a 2-byte word: {card['player_id_hex']!r}")
    if id_text != expected_id:
        raise AssertionError(f"{title}: card ID digits {id_text!r} != wPlayerID {expected_id!r}")
    if card.get("id_text") != id_text or card.get("expected_id_text") != expected_id:
        raise AssertionError(f"{title}: card ID fields disagree with the Python decode: {card!r}")
    if (card.get("name_row"), card.get("name_col")) != (2, 7):
        raise AssertionError(f"{title}: card name is not at (7,2): {(card.get('name_col'), card.get('name_row'))!r}")
    expected_name = decode_terminated(title, card["player_name_hex"])
    name_text = decode_cells(title, card["name_bytes_hex"])
    if name_text != expected_name:
        raise AssertionError(f"{title}: card name {name_text!r} != wPlayerName {expected_name!r}")
    if card.get("name_text") != name_text or card.get("expected_name") != expected_name:
        raise AssertionError(f"{title}: card name fields disagree with the Python decode: {card!r}")
    if card.get("name_length") != len(name_text) or len(name_text) != len(expected_name):
        raise AssertionError(f"{title}: card name length {card.get('name_length')!r} != {len(expected_name)}")

    head = tag_json(text, "GAME_STATS_HEAD")
    if head.get("species_id") != lead["species_id"] or head.get("dv_word") != lead["dv_word"]:
        raise AssertionError(f"{title}: stats head is not the lead mon: {head!r}")
    gender, shiny = gender_and_shiny(lead["dv_word"], species[str(lead["species_id"])]["gender_ratio"])
    want_gender, want_shiny = GENDER_BYTE[gender], SHINY_BYTE if shiny else BLANK_BYTE
    if (head.get("gender"), bool(head.get("shiny"))) != (gender, shiny):
        raise AssertionError(f"{title}: stats head gender/shiny {head.get('gender')!r}/{head.get('shiny')!r} "
                             f"!= {gender}/{shiny}")
    if head.get("blank_byte") != BLANK_BYTE:
        raise AssertionError(f"{title}: stats blank tile {head.get('blank_byte')!r} != ${BLANK_BYTE:02X}")
    if head.get("gender_byte") != want_gender or head.get("gender_expected") != want_gender:
        raise AssertionError(f"{title}: (18,0) gender byte {head.get('gender_byte')!r} != ${want_gender:02X}")
    if head.get("shiny_byte") != want_shiny or head.get("shiny_expected") != want_shiny:
        raise AssertionError(f"{title}: (19,0) shiny byte {head.get('shiny_byte')!r} != ${want_shiny:02X}")

    item = tag_json(text, "GAME_STATS_ITEM")
    if item.get("held_item") != lead["held_item"]:
        raise AssertionError(f"{title}: item line is not the lead mon's: {item!r}")
    if (item.get("item_row"), item.get("item_col")) != (8, ITEM_COLUMN[title]):
        raise AssertionError(f"{title}: item is not at ({ITEM_COLUMN[title]},8): {item!r}")
    if item.get("label_text") != "ITEM":
        raise AssertionError(f"{title}: GREEN page (0,8) label {item.get('label_text')!r} != 'ITEM'")
    if lead["held_item"] == 0:
        if item.get("item_expected") != NO_ITEM_TEXT or item.get("item_text") != NO_ITEM_TEXT:
            raise AssertionError(f"{title}: no-item line {item.get('item_text')!r} != {NO_ITEM_TEXT!r}")
        if decode_cells(title, item["item_bytes_hex"]) != NO_ITEM_TEXT:
            raise AssertionError(f"{title}: no-item cells do not decode to {NO_ITEM_TEXT!r}")
    else:
        pack = json.loads((REPO / f"data/games/gen2_{title}/item_names.json").read_text(encoding="utf-8"))
        if not isinstance(pack.get(str(lead["held_item"])), str):
            raise AssertionError(f"{title}: item pack has no name for id {lead['held_item']}")
        if _normalize(item["item_text"]) != _normalize(pack[str(lead["held_item"])]):
            raise AssertionError(f"{title}: item text {item['item_text']!r} != pack {pack[str(lead['held_item'])]!r}")


def check_dump_provenance(dump: dict, profile: dict) -> None:
    """The capture receipt: exact frame type, physical domain/offset, logical address/bank, lengths
    and hex sizes (docs/gen2/GEN2_BINDING_PLAN.md:339 -- a dump from another domain, range or frame
    must not pass)."""
    frame = dump.get("frame")
    if type(frame) is not int or frame < 1:
        raise AssertionError(f"capture frame missing or invalid: {frame!r}")
    ram, banks = profile["ram"], profile["ram_bank"]
    address, bank = ram["wPartyCount"], banks["wPartyCount"]
    length = ram["wPartyMonNicknamesEnd"] - address
    want = {"domain": "WRAM", "offset": wram_offset(bank, address, length), "bus_domain": "System Bus",
            "bank": bank, "address": address, "length": length}
    party = dump.get("party") or {}
    got = {key: party.get(key) for key in want}
    if got != want:
        raise AssertionError(f"party capture provenance {got} != {want}")
    if not isinstance(party.get("hex"), str) or len(party["hex"]) != 2 * length:
        raise AssertionError("party capture length disagrees with its recorded range")
    want = {"domain": "CartRAM", "address": 0, "length": CART_RAM_BYTES}
    cart = dump.get("cartram") or {}
    got = {key: cart.get(key) for key in want}
    if got != want:
        raise AssertionError(f"CartRAM capture provenance {got} != {want}")
    if not isinstance(cart.get("hex"), str) or len(cart["hex"]) != 2 * CART_RAM_BYTES:
        raise AssertionError("CartRAM capture length disagrees with its recorded range")


def verify_capture(text: str, profile_wrapper: dict, title: str) -> dict:
    """The whole BizHawk-free verdict over the gate's COMPLETE printed output: checkpoint, capture
    receipt, decode frame, Lua/PYDEC equality on the same bytes, the R-3 differential, the R-5g
    formula cross-check and the R-3/R-5g display rows (verify_display). Returns the PYDEC party."""
    if tagged_lines(text).get("CHECKPOINT") != ["reached"]:
        raise AssertionError("checkpoint/liveness not reached")
    profile = profile_wrapper["titles"][title]
    layout = codec.Gen2Layout.from_profile(profile_wrapper, title)
    dump = tag_json(text, "DUMP")
    check_dump_provenance(dump, profile)
    if tag_json(text, "DECODE_FRAME") != dump["frame"]:
        raise AssertionError("Lua decodes were not taken at the capture frame")

    # R-1: party, active box and all 14 storage boxes, byte-for-byte, same capture.
    py_party = codec.decode_party(bytes.fromhex(dump["party"]["hex"]), layout)
    compare_collection(tag_json(text, "PARTY_LUA"), py_party, where=f"{title} party")
    cart_raw = bytes.fromhex(dump["cartram"]["hex"])
    boxes = [("ACTIVE_BOX_LUA", "active box", layout.active_box)] + [
        (f"BOX_LUA_{index}", f"box {index}", entry) for index, entry in enumerate(layout.storage_boxes)]
    for tag, where, (flat, length) in boxes:
        lua_box = tag_json(text, tag)
        if lua_box is None or lua_box.get("bank", -1) * 0x2000 + lua_box.get("address", 0) - 0xA000 != flat:
            raise AssertionError(f"{title} {where}: Lua read another CartRAM range than the layout's")
        compare_collection(lua_box, codec.decode_box(cart_raw[flat:flat + length], layout), where=f"{title} {where}")

    # R-3 (Lua-internal differential only; stays OPEN): reads.lua against the gate's second reader.
    compare_badges(tag_json(text, "BADGES_LUA"), tag_json(text, "RAW_BADGES"), where=f"{title} badges")
    boxnum = tag_json(text, "RAW_BOXNUM")
    if not (isinstance(boxnum, int) and 0 <= boxnum <= 13):
        raise AssertionError(f"{title}: current box outside 0..13: {boxnum!r}")
    if tag_json(text, "BATTLE_LUA")["mode"] != tag_json(text, "RAW_BATTLE")["mode"]:
        raise AssertionError(f"{title}: battle-mode differential")

    # R-5g formula cross-check (stays OPEN): gender/shininess from the same DVs, in Python.
    species = json.loads((REPO / f"data/games/gen2_{title}/species_index.json").read_text(encoding="utf-8"))["species"]
    rows = tag_json(text, "GENDER_SHINY")
    if len(rows) != len(py_party["mons"]):
        raise AssertionError(f"{title}: gender/shiny rows differ from the party")
    for row, mon in zip(rows, py_party["mons"], strict=True):
        gender, shiny = gender_and_shiny(mon["dv_word"], species[str(mon["species_id"])]["gender_ratio"])
        if (row["gender"], row["shiny"]) != (gender, shiny):
            raise AssertionError(f"{title}: gender/shiny cross-check disagrees on {mon['species_id']}: {row}")

    # R-3 tilemap / R-5g display halves: the game's own rendered screens, re-derived here.
    verify_display(text, title, py_party, species)
    return py_party


def inspect_env(spec, fixture_bytes: bytes, *, repo: Path = REPO) -> dict:
    """The fixture-qualification CONTINUE binding the gate arrives through (stage "boot"), bound to
    the staged bytes by the stage fingerprint."""
    facts = gen2_fixtures.route_facts(spec.title, repo)
    case = {**vars(spec), "title_idle_frames": 0, "attempt_id": "inspect-" + spec.name,
            **gen2_fixtures.QUALIFY_BUDGET}
    qualify = {"stage": "boot", "stage_fingerprint": hashlib.sha256(fixture_bytes).hexdigest(),
               "facts": gen2_fixtures.qualify_facts(spec.title, repo)}
    return {"SLINK_GEN2_FIXTURE_CASE": json.dumps(case), "SLINK_GEN2_ROUTE_FACTS": json.dumps(facts),
            "SLINK_GEN2_QUALIFY": json.dumps(qualify)}


# --- the live gate ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def emuhawk():
    from gen1_playthrough import EMUHAWK
    if not os.path.exists(EMUHAWK):
        pytest.skip(f"EmuHawk not found at {EMUHAWK}")
    return EMUHAWK


def _run_inspect_gate(spec, fixture: Path, fixture_bytes: bytes, *, timeout=600):
    """Boot `spec`'s fixture warm and run the inspect gate; returns (passed, path, text)."""
    from run_gb_gate import run_gate

    directory = REPO / ".cache/gen2-fixtures/inspect-gate" / spec.name
    return run_gate(GATE, rom_key=spec.title, target=spec.target, timeout=timeout,
                    saveram_dir=str(directory), fixture_path=str(fixture), speed_percent=100,
                    env_overrides=inspect_env(spec, fixture_bytes))


@pytest.mark.parametrize("spec", FIXTURES, ids=lambda spec: spec.name)
def test_inspect_gate_and_hardware_differential(spec, emuhawk):
    reason = rom_missing_reason(spec.title) or fixture_missing_reason(spec.name) or receipt_missing_reason(spec.name)
    if reason:
        pytest.skip(reason)

    fixture = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
    staged = fixture.read_bytes()
    # R-1 wrong-fixture control: identity and bytes come from the receipt, never from this capture.
    expected_ot = qualified_identity(spec.name, staged)

    passed, path, text = _run_inspect_gate(spec, fixture, staged)
    assert passed, f"gate FAILED on {spec.name}; result {path}: {text[-2500:]}"
    if fixture.read_bytes() != staged:
        raise AssertionError(f"{spec.name}: fixture changed while the gate ran")

    profile_wrapper = json.loads((REPO / f"data/games/gen2_{spec.title}/profile.json")
                                 .read_text(encoding="utf-8"))
    py_party = verify_capture(text, profile_wrapper, spec.title)
    assert identity_matches(py_party, expected_ot), (spec.name, "captured OT differs from the qualified fixture")

    # R-2: independent stat recomputation from base stats sourced off the ROM, never the party's
    # own stored stat fields (CalcMonStats double-derivation, ticket 20).
    ctx = gen2_source_data.load_context(spec.title, root=REPO)
    rom = Rom(ctx.rom, profile_wrapper["titles"][spec.title])
    for mon in py_party["mons"]:
        base = rom.base_stats(mon["species_id"])
        computed = codec.calc_stats(base, mon["dvs"], mon["stat_exp"], mon["level"])
        assert mon["max_hp"] == computed["hp"], (spec.name, mon["species_id"], "max_hp")
        assert mon["stats"] == {k: v for k, v in computed.items() if k != "hp"}, (spec.name, mon["species_id"])
