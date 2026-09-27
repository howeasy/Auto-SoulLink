"""gen3_emerald pack (E1-PACK): SOURCE pins plus HEADER / literal-pool / stub controls.

None of this is an emulator receipt. The ROM-backed tests skip when the owner's BPEE is absent.
"""
import hashlib
import json
import re
import struct
from pathlib import Path

import pytest
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data/games/gen3_emerald"
ROM = Path("E:/Google Drive/SLink/Pokemon - Emerald Version (USA, Europe).gba")
ROM_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"
PRET = Path("E:/Google Drive/SLink/.cache/pret/pokeemerald")
# the 22 FR site kinds, including native hatch (same vocabulary; own Emerald pins)
KINDS = {"frame_control", "battle_begin", "battle_end", "faint", "capture_wild", "mon_given",
         "pc_move", "whiteout", "map_load", "evolve_species_store", "trade_evolve_species_store",
         "trade_begin", "trade_done", "save", "poison_hp_before", "poison_faint", "pc_deposit",
         "pc_withdraw", "pc_box_place", "pc_release_begin", "pc_release", "hatch"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def emerald() -> dict:
    return _json(PACK / "profile.json")["titles"]["emerald"]


@pytest.fixture(scope="module")
def rom() -> bytes:
    if not ROM.is_file():
        pytest.skip(f"local copyrighted ROMs absent: {ROM}")
    data = ROM.read_bytes()
    assert hashlib.sha1(data).hexdigest() == ROM_SHA1
    return data


# E2-ENTRY+BADGE: Emerald's badges straddle a SaveBlock1.flags byte (FLAG_BADGE01_GET =
# SYSTEM_FLAGS+7 = 0x867, pret include/constants/flags.h:1359), which FR/LG's shared
# SB1_BADGE_BYTE_OFFSET byte cannot express; BADGE_FIRST_FLAG is the one derived field that
# is genuinely Emerald-only, carrying the flag id lua/gen3/reads.lua and
# tools/gen3_reads_pydec.py derive each badge bit from (SB1_BADGE_BYTE_OFFSET stays null).
# EMERALD-RIVAL also publishes playerGender here; other packs leave that optional fact absent.
EMERALD_ONLY_DERIVED = {"BADGE_FIRST_FLAG", "SB2_PLAYER_GENDER_OFFSET"}


def test_profile_has_the_firered_key_set_and_provenance(emerald):
    firered = _json(ROOT / "data/games/gen3_frlg/profile.json")["titles"]["firered"]
    for section in ("ram", "rom", "derived"):
        only = EMERALD_ONLY_DERIVED if section == "derived" else set()
        assert set(emerald[section]) - only == set(firered[section]), section
        assert only <= set(emerald[section]), f"{section}: Emerald-only keys missing: {only - set(emerald[section])}"
        for key in emerald[section]:
            field = f"{section}.{key}"  # SE_SONG_HEADERS cites per id: rom.SE_SONG_HEADERS.<id>
            assert any(s == field or s.startswith(field + ".") for s in emerald["_src"]), field
    assert emerald["rom_thumb"] == firered["rom_thumb"]
    assert (emerald["admitted"], emerald["variant"], emerald["rom_sha1"]) == (True, "emerald", ROM_SHA1)


def test_profile_regenerates_byte_identical():
    from tools import gen_gen3_profile as gen

    assert gen.render(gen.build_emerald()) == (PACK / "profile.json").read_text(encoding="utf-8")


def test_profile_agrees_with_every_value_the_old_stub_carries(emerald):
    """The original Lua Emerald literals are an independent source, never copied."""
    text = (ROOT / "lua/games/gen3_frlge.lua").read_text(encoding="utf-8")
    body = re.search(r"^GEN3\.profiles\.emerald = \{(.*?)^\}", text, re.M | re.S).group(1)
    literals = re.findall(r'^\s+([A-Z][A-Z0-9_]*)\s*=\s*(0x[0-9A-Fa-f]+|\d+|"[^"]*")\s*,',
                          body, re.M)
    checked = 0
    for key, literal in literals:
        value = literal[1:-1] if literal.startswith('"') else int(literal, 0)
        sections = [s for s in ("ram", "rom", "derived") if key in emerald[s]]
        assert len(sections) == 1, key
        assert emerald[sections[0]][key] == value, (sections[0], key)
        checked += 1
    assert checked == 15 + 1 + 8  # 15 RAM, BASESTATS_ADDR, 8 derived


def test_gf_header_control(rom, emerald):
    """pret src/rom_header_gf.c:18-94 at 0x08000100: the ROM's own save-layout API."""
    head = rom[0x100:0x204]

    def u32(off: int) -> int:
        return struct.unpack_from("<I", head, off)[0]

    # known-positive control: this really is the GF header of pokemon emerald
    assert (u32(0x00), head[0x08:0x1F]) == (3, b"pokemon emerald version")
    d, r = emerald["derived"], emerald["rom"]
    assert u32(0x50) == d["SB1_FLAGS_OFFSET"] == 0x1270    # flagsOffset
    assert u32(0x54) == d["SB1_VARS_OFFSET"] == 0x139C     # varsOffset
    assert (u32(0x88), u32(0x8C)) == (0xF2C, 0x3D88)       # saveBlock2Size, saveBlock1Size
    assert u32(0x9C) == d["SB2_OT_ID_OFFSET"]              # trainerIdOffset
    assert u32(0xA0) == d["SB2_NAME_OFFSET"]               # playerNameOffset
    assert u32(0xBC) == r["BASESTATS_ADDR"]                # speciesInfo
    assert u32(0xCC) == r["BATTLE_MOVES_ADDR"]             # moves
    assert head[0xE6] == d["SB1_BALL_POCKET_COUNT"]        # bagCountPokeballs


def test_battle_type_literal_pool_control(rom, emerald):
    addr = emerald["ram"]["BATTLE_TYPE_ADDR"]
    assert addr == 0x02022FEC
    assert rom.count(struct.pack("<I", addr)) == 457
    # the probe's negative control: one page up is never referenced
    assert rom.count(struct.pack("<I", addr + 0x1000)) == 0


def test_box_data_offset_cross_checks_pret_boxnames(emerald):
    """BOX_DATA_OFFSET + BOXES_PER_STORE * MONS_PER_BOX * sizeof(BoxPokemon) must land exactly on
    the boxNames field, cross-checked against pret's own offset comment on struct PokemonStorage
    (include/pokemon_storage_system.h), independent of the derived-value citation text."""
    if not PRET.is_dir():
        pytest.skip(f"pokeemerald not cloned: {PRET}")
    text = (PRET / "include/pokemon_storage_system.h").read_text(encoding="utf-8")
    m = re.search(r"/\*(0x[0-9A-Fa-f]+)\*/\s*u8 boxNames", text)
    assert m, "pret pokemon_storage_system.h: boxNames offset comment not found"
    box_names_offset = int(m[1], 16)
    d = emerald["derived"]
    box_pokemon_size = 80  # sizeof(struct BoxPokemon); lua/gen3/reads.lua:20 (R.BOX_MON_SIZE)
    assert (d["BOX_DATA_OFFSET"] + d["BOXES_PER_STORE"] * d["MONS_PER_BOX"] * box_pokemon_size
            == box_names_offset == 0x8344)


def test_every_site_is_at_its_rom_offset_inside_its_function(rom):
    document = _json(PACK / "engine_signals.json")
    assert (document["pack"], document["live_verified"]) == ("gen3_emerald", False)
    artifact = document["titles"]["emerald"]["artifacts"]["clean"]
    assert artifact["rom_sha1"] == ROM_SHA1
    assert set(artifact["sites"]) == KINDS
    for kind, site in artifact["sites"].items():
        data = bytes.fromhex(site["expected_hex"])
        assert 8 <= len(data) <= 16, kind
        assert rom[site["rom_offset"]:site["rom_offset"] + len(data)] == data, kind
        assert rom.count(data) == 1, kind
        assert site["address"] == 0x08000000 + site["rom_offset"], kind
        assert site["address"] % 2 == site["capture_offset"] % 2 == 0, kind
        assert site["mode"] == "thumb" and site["point"], kind
        fn = site["function"]
        hook = site["address"] + site["capture_offset"]
        assert fn["address"] + fn["capture_offset"] == hook, kind
        assert fn["address"] <= hook < fn["address"] + fn["size"], kind
        ctx = site["context"]
        assert ctx["rom_offset"] == fn["address"] - 0x08000000, kind
        assert rom[ctx["rom_offset"]:ctx["rom_offset"] + len(ctx["expected_hex"]) // 2].hex().upper() \
            == ctx["expected_hex"], kind
    assert "UNVERIFIED" not in json.dumps(document)


def test_engine_signals_regenerate_byte_identical(rom):
    from tools import gen_gen3_engine_signals as gen

    pack, inventory = gen.build_emerald(rom)
    assert json.dumps(pack, indent=2, sort_keys=True) + "\n" == \
        (PACK / "engine_signals.json").read_text(encoding="utf-8")
    assert gen.document_emerald(inventory) == gen.EMERALD_DOC.read_text(encoding="utf-8")


def test_resolver_refuses_a_corrupted_entry(rom):
    from tools import gen_gen3_engine_signals as gen

    function, *_ = gen.EMERALD_BINDINGS["faint"]
    at = gen.emerald_symbols()[0][function]["address"] - 0x08000000
    bad = rom[:at] + bytes([rom[at] ^ 0xFF]) + rom[at + 1:]
    assert gen.emerald_resolve("faint", bad)["status"] == "UNVERIFIED"
    assert gen.emerald_resolve("faint", rom)["status"] == "PINNED"


# (mnemonic, capstone operand string, callee symbol name or None). Decoded once, by hand, from
# the pinned expected_hex bytes at each site's own capture point (Capstone 5.0.7 Thumb, the same
# disassembler patch/tools/disasm.py already uses on these ROMs). When the mnemonic is "bl" the
# target is additionally cross-checked against the callee's own .sym address (pokeemerald.sym),
# never a bare literal, so a pret symbol move repins this table instead of silently drifting.
CAPTURE_INSTRUCTIONS = {
    "hatch": ("add", "sp, #0x14", None),
    "frame_control": ("push", "{r4, lr}", None),
    "battle_begin": ("push", "{lr}", None),
    "battle_end": ("bl", "#0x8000540", "SetMainCallback2"),
    "faint": ("ldrb", "r0, [r7]", None),
    "capture_wild": ("lsls", "r0, r0, #0x18", None),
    "mon_given": ("pop", "{r4, r5, r6}", None),
    "pc_move": ("pop", "{r3}", None),
    "whiteout": ("bl", "#0x8000540", "SetMainCallback2"),
    "map_load": ("bl", "#0x8000540", "SetMainCallback2"),
    "evolve_species_store": ("mov", "r0, sb", None),
    "trade_evolve_species_store": ("mov", "r0, sb", None),
    "trade_begin": ("push", "{r4, r5, r6, r7, lr}", None),
    "trade_done": ("add", "sp, #4", None),
    "save": ("pop", "{r4, r5}", None),
    "poison_hp_before": ("str", "r0, [sp]", None),
    "poison_faint": ("adds", "r7, #1", None),
    "pc_deposit": ("pop", "{r4, r5, r6}", None),
    "pc_withdraw": ("b", "#0x80ce0d8", None),
    "pc_box_place": ("pop", "{r4, r5, r6, r7}", None),
    "pc_release_begin": ("push", "{lr}", None),
    "pc_release": ("bl", "#0x80ceb40", "TryRefreshDisplayMon"),
}


def _decode_capture(site: dict):
    """Decode the Thumb instruction at a site's own capture point, from its pinned expected_hex
    alone -- no ROM read needed, since expected_hex is already proven equal to the ROM bytes at
    rom_offset by test_every_site_is_at_its_rom_offset_inside_its_function."""
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    data = bytes.fromhex(site["expected_hex"])
    capture_addr = site["address"] + site["capture_offset"]
    return next((i for i in md.disasm(data, site["address"]) if i.address == capture_addr), None)


def test_capture_instruction_matches_its_kind():
    """Every capture_offset must land on the exact instruction its contract describes. A slipped
    capture_offset (wrong byte inside the anchor) decodes to a different instruction and turns
    this red; see test_capture_instruction_mutation_check for the +-2 falsifier."""
    from tools import gen_gen3_engine_signals as gen

    document = _json(PACK / "engine_signals.json")
    sites = document["titles"]["emerald"]["artifacts"]["clean"]["sites"]
    assert set(CAPTURE_INSTRUCTIONS) == KINDS == set(sites)
    symbols, _ = gen.emerald_symbols()
    for kind, (mnemonic, op_str, callee) in CAPTURE_INSTRUCTIONS.items():
        hit = _decode_capture(sites[kind])
        assert hit is not None, kind
        assert (hit.mnemonic, hit.op_str) == (mnemonic, op_str), (kind, hit.mnemonic, hit.op_str)
        if callee is not None:
            assert mnemonic == "bl", kind
            target = int(hit.op_str.lstrip("#"), 16)
            assert target == symbols[callee]["address"] & ~1, (kind, callee, hex(target))


@pytest.mark.parametrize("kind", sorted(CAPTURE_INSTRUCTIONS))
def test_capture_instruction_mutation_check(kind):
    """A capture_offset nudged +-2 must decode to a different (mnemonic, operand) pair than the
    pinned one (or fall silent) for at least one direction -- proof the assertion above actually
    depends on the exact capture_offset, not just on the anchor bytes being present."""
    document = _json(PACK / "engine_signals.json")
    site = document["titles"]["emerald"]["artifacts"]["clean"]["sites"][kind]
    expected = CAPTURE_INSTRUCTIONS[kind][:2]
    data = bytes.fromhex(site["expected_hex"])
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    tried = 0
    for delta in (2, -2):
        offset = site["capture_offset"] + delta
        if not 0 <= offset < len(data):
            continue
        tried += 1
        addr = site["address"] + offset
        hit = next((i for i in md.disasm(data, site["address"]) if i.address == addr), None)
        assert hit is None or (hit.mnemonic, hit.op_str) != expected, (kind, delta)
    assert tried, kind  # both directions out of bounds would make this check vacuous


def test_pret_citations_carry_their_identifier(emerald):
    """Every `pret/pokeemerald@<sha>:path:lines (ident` in _src names lines that contain ident."""
    if not PRET.is_dir():
        pytest.skip(f"pokeemerald not cloned: {PRET}")
    cite = re.compile(r"pret/pokeemerald@[0-9a-f]{40}:([\w/.]+):(\d+)(?:-(\d+))? \(([^;)]+)")
    checked = 0
    for key, where in emerald["_src"].items():
        for path, lo, hi, ident in cite.findall(where):
            lines = (PRET / path).read_text(encoding="utf-8").splitlines()[int(lo) - 1:int(hi or lo)]
            assert ident.split("|")[0] in "\n".join(lines), (key, path, lo, ident)
            checked += 1
    assert checked >= 50


# EMERALD_SYM's own two citation shapes (tools/gen_gen3_profile.py build_emerald()):
#   "data/gen3/pret/pokeemerald.sym:LINE (SYMBOL...)"          -- EMERALD_SYM_ADDR / combined rows
#   "data/gen3/pret/pokeemerald.sym:LINE SYMBOL 0xHEX bytes..." -- EMERALD_SYM_SIZED rows
_SYM_CITE = re.compile(r"^data/gen3/pret/pokeemerald\.sym:\d+[ (]")
_PRET_CITE = re.compile(r"pret/pokeemerald@[0-9a-f]{40}:([\w/.]+):(\d+)(?:-(\d+))? \(([^;)]+)")


def test_every_src_entry_parses_as_a_pret_or_sym_citation(emerald):
    """No `_src` value may silently fail to parse: every entry is either a .sym citation, a pret
    source citation, or the one documented cross-reference (checked by name, not skipped)."""
    checked = 0
    for key, where in emerald["_src"].items():
        if key == "derived.BASESTATS_ADDR_BY_GAME_CODE":
            # not a fresh pret/.sym fact: a pointer to another key this same dict already cites
            assert where == "rom.BASESTATS_ADDR under game code BPEE", (key, where)
            assert "rom.BASESTATS_ADDR" in emerald["_src"], key
            continue
        assert _SYM_CITE.match(where) or _PRET_CITE.search(where), (key, where)
        checked += 1
    assert checked == len(emerald["_src"]) - 1


# key -> pret #define identifier its derived value must equal (OUTCOME_*, *_MASK,
# B_ACTION_NOTHING_FAINTED, MAX_LEVEL, PARTY_CAPACITY: cheap, single-#define constants)
CHEAP_KEYS = {"OUTCOME_WON", "OUTCOME_LOST", "OUTCOME_DREW", "OUTCOME_RAN", "OUTCOME_CAUGHT",
              "BATTLE_TYPE_DOUBLE_MASK", "BATTLE_TYPE_LINK_MASK", "BATTLE_TYPE_TRAINER_MASK",
              "B_ACTION_NOTHING_FAINTED", "MAX_LEVEL", "PARTY_CAPACITY"}
_DEFINE = re.compile(r"#define\s+(\w+)\s+(\(1\s*<<\s*(\d+)\)|0x[0-9A-Fa-f]+|\d+)")


def test_cheap_derived_constants_equal_the_pret_define(emerald):
    """For the plain single-#define constants, evaluate the cited pret #define directly and
    compare -- stronger than just checking the identifier text is present on the cited line."""
    if not PRET.is_dir():
        pytest.skip(f"pokeemerald not cloned: {PRET}")
    assert set(emerald["derived"]) >= CHEAP_KEYS
    for key in CHEAP_KEYS:
        where = emerald["_src"][f"derived.{key}"]
        m = _PRET_CITE.search(where)
        assert m, (key, where)
        path, _lo, _hi, ident = m.groups()
        text = (PRET / path).read_text(encoding="utf-8")
        define = next((d for d in _DEFINE.finditer(text) if d[1] == ident), None)
        assert define, (key, ident, path)
        value = (1 << int(define[3])) if define[3] else int(define[2], 0)
        assert emerald["derived"][key] == value, (key, ident, value, emerald["derived"][key])


def test_engine_site_sources_cite_a_real_pret_range():
    """Extend the citation check to the 21 engine-site `source` URLs: each must parse to a real
    pret file/line range, and the site's own function must actually be defined at or before the
    cited end line (catches a source citation pointing at the wrong file or function)."""
    if not PRET.is_dir():
        pytest.skip(f"pokeemerald not cloned: {PRET}")
    from tools import gen_gen3_engine_signals as gen

    document = _json(PACK / "engine_signals.json")
    sites = document["titles"]["emerald"]["artifacts"]["clean"]["sites"]
    assert set(sites) == KINDS
    pattern = re.compile(re.escape(gen.EMERALD_PRET) + r"([\w/.]+)#L(\d+)(?:-L(\d+))?$")
    for kind, site in sites.items():
        m = pattern.match(site["source"])
        assert m, (kind, site["source"])
        path, lo, hi = m.groups()
        lo, hi = int(lo), int(hi or lo)
        lines = (PRET / path).read_text(encoding="utf-8").splitlines()
        assert hi <= len(lines), (kind, path, hi, len(lines))
        function = gen.EMERALD_BINDINGS[kind][0]
        decl = re.compile(r"\b" + re.escape(function) + r"\s*\(")
        starts = [n for n, line in enumerate(lines, 1) if decl.search(line)]
        assert starts, (kind, function, path)
        assert any(s <= hi for s in starts), (kind, function, path, hi, starts)
