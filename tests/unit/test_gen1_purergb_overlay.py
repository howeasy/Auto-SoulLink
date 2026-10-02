"""The SLink companion overlay for pureRGB (PLAN §6 M3 / §5.2 A4): the A4 save-ABI gate and the
artifact contract.

What is pinned here, from the committed data/purergb/*_slink.{sym,map}, data/purergb/
overlay_provenance.json, the *_overlay.json pack files and patch/dist/SLink-Pure*.ups:

  * every symbol inside wPartyDataStart..End, wMainDataStart..End, wBoxDataStart..End and
    wSpriteDataStart..End, every `s*` (SRAM) symbol and every derived struct size is EQUAL
    between the clean and the overlay .sym (A4 unit gate 1);
  * every RAM/SRAM section keeps its .map placement; the overlay adds exactly one, the 12-byte
    "SLink Mailbox" at $DEEA in the WRAMX bank-1 tail (A4 gate 2);
  * the overlay's ROMX sections live in bank $3F and nothing else does; ROM0 grows by at most
    the 1382 bytes that were free;
  * the UPS is CRC-bound to the locked pure ROM and reproduces the overlay sha1 (needs the built
    clean ROMs: skips otherwise), and provenance/lock/admission/profile agree on every hash;
  * the profile `trade` block, the sites and the checkpoint say what the .sym says.

The live half of A4 (a save made on one artifact CONTINUEd on the other) is an emulator gate
(tools/verify_gen1_release.py), not a unit test.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import struct
import sys
import types
import zlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch" / "tools"))

import apply_purergb_overlay as overlay  # noqa: E402
import gen1_foundation as F  # noqa: E402
from make_ups import ups_apply  # noqa: E402

DATA = REPO / "data" / "games" / "gen1_purergb"
SYMS = REPO / "data" / "purergb"
TITLES = ("purered", "pureblue", "puregreen")
ROM_KEY = {"purered": "pokered", "pureblue": "pokeblue", "puregreen": "pokegreen"}
LOCK = json.loads((REPO / "data" / "purergb_sources.lock.json").read_text(encoding="utf-8"))
PROVENANCE = json.loads((SYMS / "overlay_provenance.json").read_text(encoding="utf-8"))
ROM0_FREE_CLEAN = 1382  # docs/purergb/PLAN.md §11.2 A8: the Home tail at $3A9A
MAILBOX = 0xDEEA
MAILBOX_SIZE = 14  # ABI 3 + the two ROM-private SFX hold bytes (+12 flag, +13 frame stamp)
OVERLAY_BANK = 0x3F

SAVED_REGIONS = (("wPartyDataStart", "wPartyDataEnd"), ("wMainDataStart", "wMainDataEnd"),
                 ("wBoxDataStart", "wBoxDataEnd"), ("wSpriteDataStart", "wSpriteDataEnd"))
_SECTION = re.compile(r'^\tSECTION: \$([0-9a-f]{4})(?:-\$([0-9a-f]{4}))? \(\$([0-9a-f]{4}) bytes\) \["([^"]+)"\]')
_BANK = re.compile(r"^(ROM0|ROMX|VRAM|SRAM|WRAM0|WRAMX|OAM|HRAM) bank #(\d+):")
_SUMMARY = re.compile(r"^\t(ROM0|ROMX|SRAM|WRAM0|WRAMX|HRAM): (\d+) bytes used / (\d+) free")


def _json(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def _syms(title: str, kind: str) -> dict[str, tuple[int, int]]:
    return F.parse_sym(F.sym_path("purergb" if kind == "clean" else "purergb_overlay", title))


def _map(title: str, kind: str) -> tuple[dict, dict]:
    """({(space, bank, name): (start, end)}, {space: (used, free)}) from an rgblink .map."""
    name = f"{ROM_KEY[title]}.map" if kind == "clean" else f"{title}_slink.map"
    sections: dict = {}
    summary: dict = {}
    space = bank = None
    for line in (SYMS / name).read_text(encoding="utf-8", errors="replace").splitlines():
        if m := _SUMMARY.match(line):
            summary[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        elif m := _BANK.match(line):
            space, bank = m.group(1), int(m.group(2))
        elif m := _SECTION.match(line):
            start = int(m.group(1), 16)
            sections[(space, bank, m.group(4))] = (start, int(m.group(2), 16) if m.group(2) else start)
    assert sections and summary, name
    return sections, summary


def _clean_rom(title: str) -> bytes:
    try:
        return F.rom_path("purergb", title).read_bytes()
    except SystemExit as e:
        pytest.skip(f"pureRGB build not available: {e}")


def _overlay_rom(title: str) -> bytes:
    """The overlay ROM = the shipped UPS over the clean ROM (never a build tree)."""
    ups = REPO / PROVENANCE["outputs"][ROM_KEY[title]]["ups"]["file"]
    return ups_apply(_clean_rom(title), ups.read_bytes())


# ── A4 gate 1: saved-region symbols ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", TITLES)
def test_every_symbol_in_a_saved_region_is_where_the_clean_build_put_it(title):
    clean, over = _syms(title, "clean"), _syms(title, "overlay")
    ranges = []
    for lo, hi in SAVED_REGIONS:
        assert clean[lo] == over[lo] and clean[hi] == over[hi], (lo, hi)
        ranges.append((clean[lo][0], clean[lo][1], clean[hi][1]))
    inside = [n for n, (b, a) in clean.items() if any(b == rb and lo <= a < hi for rb, lo, hi in ranges)]
    assert len(inside) > 1000  # the party/main/box/sprite blocks carry most of WRAM
    moved = {n: (clean[n], over.get(n)) for n in inside if over.get(n) != clean[n]}
    assert not moved, f"{title}: saved-region symbols differ between clean and overlay: {moved}"


@pytest.mark.parametrize("title", TITLES)
def test_every_sram_symbol_and_struct_size_is_unchanged(title):
    clean, over = _syms(title, "clean"), _syms(title, "overlay")
    sram = [n for n in clean if n.startswith("s") and n[1:2].isupper()]
    assert "sBox1" in sram and "sMainData" in sram
    moved = {n: (clean[n], over.get(n)) for n in sram if over.get(n) != clean[n]}
    assert not moved, f"{title}: SRAM symbols differ: {moved}"
    cp, op = _json("profile")["titles"][title], _json("profile_overlay")["titles"][title]
    assert op["derived"] == cp["derived"]
    assert op["ram"] == cp["ram"]
    assert op["sram_bank"] == cp["sram_bank"]


# ── A4 gate 2: RAM/SRAM section placement ────────────────────────────────────────────────────

@pytest.mark.parametrize("title", TITLES)
def test_ram_and_sram_sections_keep_their_placement_and_the_mailbox_is_the_only_addition(title):
    cs, csum = _map(title, "clean")
    os_, osum = _map(title, "overlay")
    ram = lambda secs: {k: v for k, v in secs.items() if k[0] not in ("ROM0", "ROMX")}  # noqa: E731
    cr, orr = ram(cs), ram(os_)
    for key, rng in cr.items():
        assert orr.get(key) == rng, f"{title}: {key} moved {rng} -> {orr.get(key)}"
    added = set(orr) - set(cr)
    assert added == {("WRAMX", 1, overlay.MAILBOX_SECTION)}
    assert orr[("WRAMX", 1, overlay.MAILBOX_SECTION)] == (MAILBOX, MAILBOX + MAILBOX_SIZE - 1)
    assert orr[("WRAMX", 1, "Current Box Data")][1] == MAILBOX - 1
    assert orr[("WRAMX", 1, "Stack")][0] == 0xDF00
    for space in ("SRAM", "WRAM0", "HRAM"):
        assert osum[space] == csum[space], space
    assert osum["WRAMX"] == (csum["WRAMX"][0] + MAILBOX_SIZE, csum["WRAMX"][1] - MAILBOX_SIZE)


@pytest.mark.parametrize("title", TITLES)
def test_the_mailbox_symbols_are_the_abi_3_layout(title):
    over = _syms(title, "overlay")
    assert over["wSlinkMailbox"] == (1, MAILBOX)
    assert over["wSlinkMailboxEnd"] == (1, MAILBOX + MAILBOX_SIZE)
    layout = {"wSlinkBeacon": 0, "wSlinkAbi": 4, "wSlinkFrameCounter": 5, "wSlinkSfxRequest": 7,
              "wSlinkCaps": 8, "wSlinkPanelState": 9, "wSlinkPanelPage": 10, "wSlinkPanelPages": 11,
              "wSlinkSfxHold": 12, "wSlinkSfxHoldAt": 13}
    assert {n: over[n][1] - MAILBOX for n in layout} == layout
    assert over["wBoxDataEnd"] == (1, MAILBOX)
    assert over["wStack"][1] - 0xFF >= MAILBOX + MAILBOX_SIZE  # never under the stack


# ── ROM placement ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", TITLES)
def test_overlay_code_lives_in_bank_3f_plus_one_home_stub(title):
    cs, csum = _map(title, "clean")
    os_, osum = _map(title, "overlay")
    bank3f = {k[2] for k in os_ if k[0] == "ROMX" and k[1] == OVERLAY_BANK}
    assert bank3f == set(overlay.ROMX_SECTIONS)
    assert not [k for k in cs if k[0] == "ROMX" and k[1] == OVERLAY_BANK]
    slink = {k for k in os_ if k[2].startswith("SLink")}
    assert slink == {("ROMX", OVERLAY_BANK, s) for s in overlay.ROMX_SECTIONS} | {
        ("ROM0", 0, overlay.HOME_SECTION), ("WRAMX", 1, overlay.MAILBOX_SECTION)}
    assert set(os_) - set(cs) == slink  # no other new section anywhere
    grown = osum["ROM0"][0] - csum["ROM0"][0]
    assert 0 < grown <= ROM0_FREE_CLEAN and osum["ROM0"][1] == csum["ROM0"][1] - grown
    assert csum["ROM0"][1] == ROM0_FREE_CLEAN
    # the bank-$3F code is the seven vanilla modules + the APEX guard, well under a bank
    used = sum(hi - lo + 1 for (sp, b, _), (lo, hi) in os_.items() if sp == "ROMX" and b == OVERLAY_BANK)
    assert 3000 < used < 0x4000


@pytest.mark.parametrize("title", TITLES)
def test_every_call_in_the_overlay_sources_targets_home_or_bank_3f(title):
    """A `call X` from bank $3F reaches X only if X is in ROM0 or in bank $3F; anything else must
    be a farcall. The linker does not check this, so this does."""
    over = _syms(title, "overlay")
    near = re.compile(r"^\s*(?:call|jp)\s+(?:(?:nz|z|nc|c),\s*)?([A-Za-z_][\w.]*)\s*(?:;.*)?$")
    far = re.compile(r"^\s*(?:farcall|callfar|jpfar|farjp)\s+([A-Za-z_][\w.]*)")
    checked = 0
    for src in sorted(overlay.OVERLAY_SRC.glob("*.asm")):
        for line in src.read_text(encoding="utf-8").splitlines():
            if m := near.match(line):
                bank = over[m.group(1)][0]
                assert bank in (0, OVERLAY_BANK), f"{src.name}: near call into bank {bank:#x}: {line.strip()}"
                checked += 1
            elif m := far.match(line):
                assert m.group(1) in over, f"{src.name}: {line.strip()}"
                checked += 1
    assert checked > 100


def test_species_and_name_tables_are_derived_from_the_pack():
    table = (overlay.OVERLAY_SRC / "species_table.inc").read_text(encoding="utf-8")
    flags = [int(x) for line in table.splitlines() if line.startswith("\tdb ")
             for x in line[4:].split(",")]
    species = _json("species_index")["species"]
    assert flags == [0] + [1 if species[str(i)]["obtainable"] else 0 for i in range(1, 191)]
    # the name-glyph rule in trade_ui.asm against the charmap: every byte >= $7F except kana
    # and the cursor arrows is a literal a nickname may carry
    glyphs = _json("charmap")["glyphs"]
    literal = {b for b in range(0x7F, 0x100)
               if not any(0x3040 <= ord(ch) <= 0x30FF for ch in glyphs[str(b)]) and glyphs[str(b)] not in "▷▶▼"}
    rule = {i for i in range(256) if (0x7F <= i < 0xC0) or (0xE0 <= i < 0xEC) or i >= 0xEF}
    assert rule == literal
    assert "(i >= $7F && i < $C0) || (i >= $E0 && i < $EC) || (i >= $EF)" in \
        (overlay.OVERLAY_SRC / "trade_ui.asm").read_text(encoding="utf-8")


# ── artifacts: UPS, provenance, admission, profile ──────────────────────────────────────────

@pytest.mark.parametrize("title", TITLES)
def test_provenance_lock_and_admission_agree(title):
    out = PROVENANCE["outputs"][ROM_KEY[title]]
    lock = LOCK["outputs"][ROM_KEY[title]]
    assert PROVENANCE["source"] == LOCK["source"]
    assert PROVENANCE["toolchain"]["rgbds"]["version"] == LOCK["rgbds_version"]
    assert out["base_sha1"] == lock["sha1"] and out["sha1"] != lock["sha1"]
    assert out["title"] == lock["title"] and out["size"] == 0x100000
    for ext in ("sym", "map"):
        name = f"{title}_slink.{ext}"
        assert PROVENANCE["symbols"][name] == hashlib.sha256((SYMS / name).read_bytes()).hexdigest()
    ups = (REPO / out["ups"]["file"]).read_bytes()
    assert (len(ups), hashlib.sha256(ups).hexdigest()) == (out["ups"]["size"], out["ups"]["sha256"])
    # UPS trailer: source CRC32 = the clean pure ROM, target CRC32 = the overlay ROM
    src_crc, dst_crc = struct.unpack("<II", ups[-12:-4])
    assert f"{src_crc:08X}" == lock["crc32"] and f"{dst_crc:08X}" == out["crc32"]
    assert zlib.crc32(ups[:-4]) & 0xFFFFFFFF == struct.unpack("<I", ups[-4:])[0]
    row = _json("admission_overlay")[out["sha1"]]
    assert row["kind"] == "overlay" and row["title"] == title and row["base_sha1"] == lock["sha1"]
    assert (row["md5"], row["crc32"], row["header_crc"]) == (out["md5"], out["crc32"], out["header_crc"])
    assert _json("profile_overlay")["titles"][title]["rom_sha1"] == out["sha1"]
    assert _json("engine_signals_overlay")["titles"][title]["rom_sha1"] == out["sha1"]
    assert out["sha1"] not in _json("admission")  # a distinct artifact, never a clean row
    assert PROVENANCE["overlay"]["sources"] == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in overlay.OVERLAY_SRC.iterdir() if p.suffix in (".asm", ".inc", ".2bpp")}
    assert PROVENANCE["overlay"]["edits"] == len(overlay.EDITS)


@pytest.mark.parametrize("title", TITLES)
def test_the_ups_applies_to_the_pure_rom_and_reproduces_the_overlay(title):
    rom = _overlay_rom(title)
    out = PROVENANCE["outputs"][ROM_KEY[title]]
    assert hashlib.sha1(rom).hexdigest() == out["sha1"]
    over = _syms(title, "overlay")
    trade = _json("profile_overlay")["titles"][title]["trade"]
    for name, anchor in trade["anchors"].items():
        got = rom[anchor["flat"]:anchor["flat"] + len(anchor["expected_hex"]) // 2].hex().upper()
        assert got == anchor["expected_hex"], name
    assert rom[trade["receptionist_hook"]:trade["receptionist_hook"] + 7].hex().upper() == trade["dispatch_hex"]
    # the beacon is emitted as bytes, not through the charmap: "SLNK" = 53 4C 4E 4B
    hook = F.flat(*over["SlinkHook"])
    assert rom[hook:hook + 7] == bytes((0xF0, 0x70, 0xF5, 0x3E, 0x01, 0xE0, 0x70))  # rWBK save + select 1
    body = rom[hook:hook + 0x43]
    for byte in (0x53, 0x4C, 0x4E, 0x4B):
        assert bytes((0x3E, byte)) in body
    # every site's expected_hex is what the overlay ROM holds
    for kind, site in _json("engine_signals_overlay")["titles"][title]["sites"].items():
        n = len(site["expected_hex"]) // 2
        assert rom[site["rom_offset"]:site["rom_offset"] + n].hex().upper() == site["expected_hex"], kind


def test_the_clean_rom_is_untouched_by_the_overlay_build():
    build = json.loads((SYMS / "build_provenance.json").read_text(encoding="utf-8"))["roms"]
    for key, spec in LOCK["outputs"].items():
        assert build[key]["sha1"] == spec["sha1"]
        assert PROVENANCE["outputs"][key]["base_sha1"] == spec["sha1"]


# ── the pack files the client loads for an overlay artifact ─────────────────────────────────

@pytest.mark.parametrize("title", TITLES)
def test_profile_trade_block_matches_the_overlay_symbols(title):
    over = _syms(title, "overlay")
    t = _json("profile_overlay")["titles"][title]
    assert t["sym"] == f"{title}_slink.sym"
    trade = t["trade"]
    assert trade["abi"] == 3 and trade["mailbox"] == MAILBOX == over["wSlinkMailbox"][1]
    assert (trade["service"]["bank"], trade["service"]["addr"]) == over["SlinkTradeService"] == (OVERLAY_BANK, over["SlinkTradeService"][1])
    assert trade["receptionist_hook"] == over["TextScript_CableClubNPC"][1] < 0x4000
    lo, hi = over["SlinkReceptionist"][1] & 0xFF, over["SlinkReceptionist"][1] >> 8
    assert trade["dispatch_hex"] == f"21{lo:02X}{hi:02X}06{OVERLAY_BANK:02X}C7C9"
    a = trade["anchors"]
    assert a["foreground"]["addr"] == over["OverworldLoop"][1]
    assert a["start_menu_row"]["addr"] == over["StartMenuJumpTable"][1] + 14  # row 7, after CloseTextDisplay
    assert a["start_menu_row"]["expected_hex"] == f"{over['SlinkStartMenuEntry'][1] & 0xFF:02X}{over['SlinkStartMenuEntry'][1] >> 8:02X}"
    assert over["SlinkStartMenuEntry"][0] == 0  # the dispatcher `jp hl`s with bank 4 mapped
    assert (a["apex_guard"]["bank"], a["apex_guard"]["addr"]) == over["ItemUseMedicine.setDVs"]
    assert a["vblank"]["bank"] == 0 and over["VBlank"][1] < a["vblank"]["addr"] < over["DelayFrame"][1]
    # the two main-thread SFX sites: DelayFrame's tail `jp`s to the ROM0 stub, Joypad `call`s the other
    assert (a["delay_frame_tail"]["bank"], a["delay_frame_tail"]["addr"]) == over["DelayFrame.halt"]
    assert a["delay_frame_tail"]["expected_hex"].endswith(
        f"C3{over['SlinkDelayFrameTail'][1] & 0xFF:02X}{over['SlinkDelayFrameTail'][1] >> 8:02X}")
    assert (a["joypad"]["bank"], a["joypad"]["addr"]) == (0, over["Joypad"][1] + 15)
    assert over["SlinkDelayFrameTail"][0] == 0 and over["SlinkJoypadSite"][0] == 0
    assert over["SlinkSfxService"][0] == OVERLAY_BANK
    # the panel/service/receptionist entry points the Lua names are all in bank $3F
    for name in ("SlinkPanel", "SlinkHook", "SlinkForeground", "SlinkReceptionist", "SlinkTradeApply",
                 "SlinkPartnerPrompt", "SlinkApexGuard"):
        assert over[name][0] == OVERLAY_BANK, name


@pytest.mark.parametrize("title", TITLES)
def test_overlay_sites_keep_the_clean_kinds_points_and_ram_addresses(title):
    clean = _json("engine_signals")["titles"][title]
    over = _json("engine_signals_overlay")["titles"][title]
    syms = _syms(title, "overlay")
    assert set(over["sites"]) == set(clean["sites"])
    assert over["addresses"] == clean["addresses"]  # WRAM points never move (A4)
    for kind, site in clean["sites"].items():
        o = over["sites"][kind]
        assert (o["point"], o["symbol"], o["capture_offset"]) == (site["point"], site["symbol"], site["capture_offset"]), kind
        assert (o["bank"], o["address"]) == (syms[o["symbol"]][0], syms[o["symbol"]][1] + o["anchor_offset"]), kind
    # the APEX rows sit past the 14-byte guard prelude at .setDVs, HL again the DV pointer
    assert over["sites"]["apex_preflight"]["address"] == syms["ItemUseMedicine.setDVs"][1] + 14
    assert over["sites"]["apex_preflight"]["expected_hex"].startswith("2277E1E5CD")
    assert over["sites"]["apex_commit"]["address"] == syms["ItemUseMedicine.setDVs"][1] + 16
    assert over["symbols_sha256"] == hashlib.sha256((SYMS / f"{title}_slink.sym").read_bytes()).hexdigest()


@pytest.mark.parametrize("title", TITLES)
def test_overlay_checkpoint_keeps_the_clean_ram_and_the_delay_frame_return(title):
    clean = _json("write_checkpoint")[title]
    over = _json("write_checkpoint_overlay")[title]
    syms = _syms(title, "overlay")
    for key in ("BATTLE_FLAG_ADDR", "FONT_LOADED_ADDR", "JOY_IGNORE_ADDR"):
        assert over[key] == clean[key]
    cw, ow = clean["write_safe"], over["write_safe"]
    for key in ("version", "irq_vector", "delay_frame_rst", "delay_frame_bank", "wram_bank_register", "wram_banks",
                "link_state", "serial_status", "entering_cable_club", "stack_min", "stack_end", "vblank_flag"):
        assert ow[key] == cw[key], key
    assert ow["overworld_loop"] == syms["OverworldLoop"][1]
    assert ow["overworld_return"] == ow["overworld_loop"] + 1  # the DelayFrame caller is still the rst
    assert ow["overworld_loop_less_delay"] == ow["overworld_loop"] + 7  # past `farcall SlinkForeground`
    fg = syms["SlinkForeground"][1]
    assert ow["expected_hex"]["overworld_loop"].startswith(f"D706{OVERLAY_BANK:02X}21{fg & 0xFF:02X}{fg >> 8:02X}C7")
    assert ow["delay_frame_halt"] == syms["DelayFrame.halt"][1]


def test_the_apply_script_still_matches_the_pinned_source():
    try:
        root = F.source_root("purergb")
    except SystemExit as e:
        pytest.skip(str(e))
    assert overlay.check(root) == []


def test_admission_overlay_rows_are_the_three_overlay_titles_only():
    rows = _json("admission_overlay")
    assert {r["title"] for r in rows.values()} == set(TITLES)
    assert {r["kind"] for r in rows.values()} == {"overlay"}
    assert set(rows) == {PROVENANCE["outputs"][ROM_KEY[t]]["sha1"] for t in TITLES}
    assert not set(rows) & set(_json("admission"))


# ── the Lua client over an overlay artifact (lupa) ──────────────────────────────────────────

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the Gen 1 entry module")
sys.path.insert(0, str(REPO / "tests" / "unit"))
import test_gen1_purergb_client as pc  # noqa: E402  (PureWorld fakes + synth_rom over a pack)


class OverlayWorld(pc.PureWorld):
    """PureWorld with the overlay pack selected: kind "overlay", a synthetic cartridge carrying the
    overlay sites/checkpoint bytes, the receptionist dispatch and a live SLNK mailbox."""

    def __init__(self, monkeypatch, title="purered"):
        profile = _json("profile_overlay")["titles"]
        monkeypatch.setattr(pc, "PROFILE", profile)
        monkeypatch.setattr(pc, "SITES", _json("engine_signals_overlay")["titles"])
        monkeypatch.setattr(pc, "WS", _json("write_checkpoint_overlay"))
        monkeypatch.setattr(pc, "ADMISSION", _json("admission_overlay"))

        class KindedRuntime:  # the one deps table PureWorld builds says kind="clean"
            def __init__(self, **kw):
                self._rt = lupa.LuaRuntime(**kw)

            def __getattr__(self, name):
                return getattr(self._rt, name)

            def table(self, *a, **kw):
                if kw.get("kind") == "clean" and kw.get("pack") == "gen1_purergb":
                    kw["kind"] = "overlay"
                return self._rt.table(*a, **kw)
        monkeypatch.setattr(pc, "lupa", types.SimpleNamespace(LuaRuntime=KindedRuntime))
        super().__init__(title)


def test_an_overlay_cartridge_is_admitted_as_kind_overlay():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    E = lua.eval(f'dofile("{pc.ENTRY}")')
    json_mod = lua.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    for title in TITLES:
        sha = PROVENANCE["outputs"][ROM_KEY[title]]["sha1"]
        rom = _overlay_rom(title)
        admitted = E.admit(lua.table_from({"root": REPO.as_posix(), "json": json_mod, "rom_sha1": sha.upper(),
                                           "header": "POKEMON RED", "rom_size": len(rom),
                                           "read_rom_u8": lambda i, image=rom: image[int(i)]}))
        assert not isinstance(admitted, tuple), admitted
        copy_fields = lua.eval("function(value) local out={} for k,v in pairs(value) do out[k]=v end return out end")
        got = dict(copy_fields(admitted).items())
        assert (got["pack"], got["title"], got["kind"]) == ("gen1_purergb", title, "overlay")
        assert got["rom_type"] == {"purered": "PureRed", "pureblue": "PureBlue", "puregreen": "PureGreen"}[title]


def test_the_overlay_client_loads_the_trade_block_and_hellos_with_the_panel(monkeypatch):
    trade = _json("profile_overlay")["titles"]["purered"]["trade"]
    w = OverlayWorld(monkeypatch)
    rom = bytearray(w.rom)
    rom[trade["receptionist_hook"]:trade["receptionist_hook"] + 7] = bytes.fromhex(trade["dispatch_hex"])
    w.rom = bytes(rom)
    # the VBlank hook keeps the mailbox live: beacon, ABI 3, caps = panel
    w.bus[MAILBOX:MAILBOX + 4] = b"SLNK"
    w.bus[MAILBOX + 4], w.bus[MAILBOX + 8] = 3, 0x02
    w.client.start(w.client)
    w.overworld_safe()
    profile = w.parts.profile
    assert profile.trade.mailbox == MAILBOX and profile.trade.service.bank == OVERLAY_BANK
    assert w.client.trade_patch_present(w.client) is True
    assert w.client.trade_enabled is True
    svc = w.hooks["SLink-gen1-trade_service"]
    assert svc[1] == trade["service"]["addr"]  # the self-sliced service site is the overlay's
    assert w.client.artifact_kind == "overlay"
    rng = pc.random.Random(1)
    w.seed_party([pc._mon(rng, 0x99, nick="BULBA")])
    w.set_map(0x0C)
    w.connect()
    hello = w.events("hello")[0]
    assert hello["artifact_kind"] == "overlay" and hello["panel"] is True and hello["panel_abi"] == 3
    assert hello["rom_sha1"] == PROVENANCE["outputs"]["pokered"]["sha1"]
    # and the overlay sites are the ones armed
    assert w.hooks["SLink-gen1-apex_preflight"][1] == _json("engine_signals_overlay")["titles"]["purered"]["sites"]["apex_preflight"]["address"]
