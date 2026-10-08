"""Polished Crystal title wordmark (patch/polished/src/title.asm, docs/polished/TITLE.md): ROM-bytes evidence.

The committed UPS is applied to the pinned v3.2.3 release ROM and the BUILT bytes are read back:

* the hook: `call EnableLCD` at 35:40eb (flat 0xD40EB, clean `cd da 24`) now calls SlinkTitleBridge, and the bridge
  is `farcall SlinkTitleBand` (rst $10 + dwb) then `jp EnableLCD`;
* the band: SlinkTitleBand copies exactly the generated Crystal art (patch/gen2/src/title_logo_crystal.2bpp) to
  vTiles2 at SLINK_TITLE_FIRST_TILE, the two generated row tables to wTilemap (6,10)/(6,11), and palette 6 to the
  attribute map (6..14, 10..11) in VRAM bank 1;
* the entrance shear: TitleScreenEntrance's two immediates read 88 lines / 44 pairs (clean 80 / 40);
* the free tile ids: TitleLogoGFX, LZ-decompressed out of the clean ROM (a model of home/decompress.asm,
  checked against the clean build's own logo_version.2bpp when that build is cached), is 154 tiles from vTiles1, so it reaches
  vTiles2 ids $00-$19 and the band's run lies in the free $1A-$7E;
* every byte outside the overlay's spans equals the clean ROM (build_polished_companion.verify_overlay, the same
  whole-ROM confinement the builder runs), and the two title routines differ only in their operands.

Red controls: one corrupted tile byte, a hook that still calls EnableLCD, and an extra changed byte in _TitleScreen
must each be refused by the same checks.

Absent input skips (no cached release ROM); present-but-wrong input fails.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch" / "tools"))

import build_polished_companion as pc  # noqa: E402
from build_gen2_companion import _symbols  # noqa: E402
from make_ups import ups_apply  # noqa: E402

RELEASE_ROM = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
CLEAN_SYM = REPO / "data/polished/polishedcrystal.sym"
OVERLAY_SYM = REPO / "data/polished/polished_slink.sym"
UPS = REPO / "patch/dist/SLink-Polished.ups"
ART = REPO / "patch/gen2/src/title_logo_crystal.2bpp"
ROWS = REPO / "patch/gen2/src/title_rows_crystal.inc"
SRC = REPO / "patch/polished/src/title.asm"

HOOK = 0xD40EB                      # 35:40eb, docs/polished/TITLE.md 2.2
VTILES1, VTILES2 = 0x8800, 0x9000
WTILEMAP_W, BGMAP0, BGMAP_W = 20, 0x9800, 32


@pytest.fixture(scope="module")
def env():
    if not RELEASE_ROM.is_file():
        pytest.skip(f"pinned Polished release ROM not cached at {RELEASE_ROM}")
    base = RELEASE_ROM.read_bytes()
    data = ups_apply(base, UPS.read_bytes())
    return {"base": base, "data": bytes(data), "old": _symbols(CLEAN_SYM), "new": _symbols(OVERLAY_SYM)}


def flat(sym: dict, name: str) -> int:
    return pc._flat(*sym[name])


def le(v: int) -> bytes:
    return v.to_bytes(2, "little")


def art_rows() -> tuple[int, int, list[bytes]]:
    text = ROWS.read_text(encoding="utf-8")
    n = int(re.search(r"SLINK_TITLE_LOGO_TILES EQU (\d+)", text).group(1))
    first = int(re.search(r"SLINK_TITLE_FIRST_TILE EQU \$([0-9A-F]{2})", text).group(1), 16)
    rows = [bytes(int(v[1:], 16) for v in line.split("db ", 1)[1].split(","))
            for line in text.splitlines() if line.strip().startswith("db ")]
    return n, first, rows


def lz_decompress(rom: bytes, at: int) -> bytes:
    """Polished's _Decompress (home/decompress.asm), modelled instruction-for-instruction where it differs from
    pokecrystal: an LZ_LONG command keeps ONE high length bit (`and b` after the rlca walk: b = ccc0000l),
    LZ_REPEAT writes its byte once before the n-byte .fill, and LZ_ALTERNATE writes its two bytes and then repeats
    n more from its own start ("chases its own tail")."""
    out = bytearray()
    while True:
        b = rom[at]
        at += 1
        cmd = b >> 5
        if cmd == 7:
            if b == 0xFF:
                return bytes(out)
            cmd = (b >> 2) & 7
            n = (((b & 1) << 8) | rom[at]) + 1
            at += 1
        else:
            n = (b & 0x1F) + 1
        if cmd == 0:
            out += rom[at:at + n]
            at += n
        elif cmd == 1:                       # .lz_iterate writes the byte once, then .fill writes it n more times
            out += bytes([rom[at]]) * (n + 1)
            at += 1
        elif cmd == 3:
            out += bytes(n)
        else:
            if cmd == 2:
                src = len(out)
                out += rom[at:at + 2]
                at += 2
                cmd = 4
            else:
                o = rom[at]
                at += 1
                if o & 0x80:
                    src = len(out) - (o & 0x7F) - 1
                else:
                    src = (o << 8) | rom[at]
                    at += 1
            for k in range(n):
                if cmd == 4:
                    out.append(out[src + k])
                elif cmd == 5:
                    out.append(int(f"{out[src + k]:08b}"[::-1], 2))
                else:
                    out.append(out[src - k])


# ------------------------------------------------------------------ checks (each raises AssertionError on a bad ROM)

def check_hook(e: dict, data: bytes) -> None:
    old, new, base = e["old"], e["new"], e["base"]
    assert base[HOOK:HOOK + 3] == b"\xcd" + le(old["EnableLCD"][1]) == bytes.fromhex("cdda24"), "clean hook site moved"
    bridge = new["SlinkTitleBridge"]
    assert bridge[0] == 0, "the title bridge must be ROM0"
    assert data[HOOK:HOOK + 3] == b"\xcd" + le(bridge[1]), f"hook reads {data[HOOK:HOOK + 3].hex()}"
    band = new["SlinkTitleBand"]
    at = bridge[1]
    # farcall SlinkTitleBand = rst FarCall ($10 -> d7) + dwb addr, bank; then jp EnableLCD
    want = b"\xd7" + le(band[1]) + bytes([band[0]]) + b"\xc3" + le(old["EnableLCD"][1])
    assert data[at:at + len(want)] == want, data[at:at + len(want)].hex()
    assert new["SlinkTitleBridgeEnd"][1] - at == len(want)
    assert base[at:at + len(want)] == b"\xff" * len(want), "the bridge is not in a free ($FF) ROM0 gap"


def check_band(e: dict, data: bytes) -> None:
    new = e["new"]
    n, first, rows = art_rows()
    art = ART.read_bytes()
    assert len(art) == n * 16 and len(rows) == 2 and all(len(r) == 9 for r in rows)
    tiles = flat(new, "SlinkTitleTiles")
    assert data[tiles:tiles + len(art)] == art, "the band's tile data is not the generated Crystal art"
    assert new["SlinkTitleTilesEnd"][1] - new["SlinkTitleTiles"][1] == len(art)
    band = flat(new, "SlinkTitleBand")
    code = data[band:tiles]
    row0, row1 = flat(new, "SlinkTitleLogoRow0"), flat(new, "SlinkTitleLogoRow1")
    assert (data[row0:row0 + 9], data[row1:row1 + 9]) == tuple(rows), "the row tables are not the generated rows"
    assert rows[0] + rows[1] == bytes(range(first, first + n)), "the Crystal band is 18 distinct, contiguous ids"
    wtilemap = e["old"]["wTilemap"][1]
    attr = lambda x, y: BGMAP0 + y * BGMAP_W + x  # noqa: E731
    want = (b"\x21" + le(new["SlinkTitleTiles"][1]) + b"\x11" + le(VTILES2 + first * 16) + b"\x01" + le(n * 16) + b"\xe7"
            + b"\x21" + le(0x4000 + row0 % 0x4000) + b"\x11" + le(wtilemap + 10 * WTILEMAP_W + 6) + b"\x01" + le(9) + b"\xe7"
            + b"\x21" + le(0x4000 + row1 % 0x4000) + b"\x11" + le(wtilemap + 11 * WTILEMAP_W + 6) + b"\x01" + le(9) + b"\xe7"
            + b"\x3e\x01\xe0\x4f"                                                       # ld a,1 / ldh [rVBK],a
            + b"\x21" + le(attr(6, 10)) + b"\x01" + le(9) + b"\x3e\x06\xef"             # palette 6, rst ByteFill
            + b"\x21" + le(attr(6, 11)) + b"\x01" + le(9) + b"\x3e\x06\xef"
            + b"\xaf\xe0\x4f\xc9")                                                       # xor a / ldh [rVBK],a / ret
    assert code[:len(want)] == want, f"band code {code[:len(want)].hex()}\n want {want.hex()}"


def check_entrance(e: dict, data: bytes) -> None:
    base, old = e["base"], e["old"]
    lo, hi = pc._routine(old, "TitleScreenEntrance")
    ly = old["wLYOverrides"][1]
    tail = b"\x21" + le(ly + 1) + b"\x22\x23\x05\x20"
    for clean, built in ((b"\x01\x50\x00", b"\x01\x58\x00"), (b"\x06\x28" + tail, b"\x06\x2c" + tail)):
        assert base[lo:hi].count(clean) == 1, clean.hex()
        assert data[lo:hi].count(built) == 1 and data[lo:hi].find(built) == base[lo:hi].find(clean), built.hex()
    assert old["wLYOverridesEnd"][1] - ly == 144 >= 88


def check_confined(e: dict, data: bytes) -> None:
    base, old, new = e["base"], e["old"], e["new"]
    pc.verify_overlay(base, data, old, new)          # raises RuntimeError on any byte outside the intended spans
    for routine, changed in (("_TitleScreen", [HOOK + 1, HOOK + 2]),):
        lo, hi = pc._routine(old, routine)
        diffs = [lo + i for i in range(hi - lo) if base[lo + i] != data[lo + i]]
        assert diffs == changed, (routine, [hex(d) for d in diffs])
    lo, hi = pc._routine(old, "TitleScreenEntrance")
    assert sum(base[lo + i] != data[lo + i] for i in range(hi - lo)) == 2
    # the title's own graphics (bank $23) are untouched
    gfx_lo, gfx_hi = flat(old, "TitleSuicuneGFX"), flat(old, "TitleScreenPalettes") + 16 * 8
    assert base[gfx_lo:gfx_hi] == data[gfx_lo:gfx_hi]


# ------------------------------------------------------------------ the tests

def test_the_hook_calls_the_rom0_bridge_which_farcalls_the_band_then_enables_the_lcd(env):
    check_hook(env, env["data"])


def test_the_band_writes_the_generated_art_rows_and_palette_6(env):
    check_band(env, env["data"])


def test_the_logo_entrance_shear_is_widened_to_the_band(env):
    check_entrance(env, env["data"])


def test_every_byte_outside_the_overlay_spans_is_the_clean_rom(env):
    check_confined(env, env["data"])


def test_the_band_tile_ids_are_free_on_the_title_screen(env):
    """The title's BG tiles come from the ROM: TitleLogoGFX decompresses from vTiles1 ($8800, id $80) through vTiles2,
    and the logo/copyright/FAITHFUL ids it draws stop at the last tile it wrote. Suicune is VRAM bank 1 only."""
    base, old = env["base"], env["old"]
    logo = lz_decompress(base, flat(old, "TitleLogoGFX"))
    crystal = lz_decompress(base, flat(old, "TitleCrystalGFX"))
    suicune = lz_decompress(base, flat(old, "TitleSuicuneGFX"))
    assert (len(logo), len(crystal), len(suicune)) == (2464, 960, 4096)
    clean_build = RELEASE_ROM.parents[1] / "companion-clean" / "gfx" / "title" / "logo_version.2bpp"
    if clean_build.is_file():                      # positive control for the decoder: the build's own .2bpp
        assert logo == clean_build.read_bytes()
    last_logo_id = (len(logo) // 16 - 1 - 128) & 0xFF      # ids $80..$FF then $00..
    assert last_logo_id == 0x19
    n, first, _rows = art_rows()
    assert first > last_logo_id and first + n <= 0x7F, (hex(first), n)     # and never the ' ' clear tile $7F
    # the source's own guards say the same
    text = SRC.read_text(encoding="utf-8")
    assert "ASSERT SLINK_TITLE_FIRST_TILE >= $1A" in text and "+ SLINK_TITLE_LOGO_TILES <= $7F" in text


def test_red_control_a_corrupted_tile_byte_is_refused(env):
    data = bytearray(env["data"])
    data[flat(env["new"], "SlinkTitleTiles") + 5] ^= 0x01
    with pytest.raises(AssertionError, match="tile data"):
        check_band(env, bytes(data))


def test_red_control_a_hook_left_on_enable_lcd_is_refused(env):
    data = bytearray(env["data"])
    data[HOOK + 1:HOOK + 3] = le(env["old"]["EnableLCD"][1])
    with pytest.raises(AssertionError, match="hook reads"):
        check_hook(env, bytes(data))


def test_red_control_an_extra_changed_byte_in_the_title_routine_is_refused(env):
    data = bytearray(env["data"])
    data[HOOK + 3] ^= 0xFF                               # the instruction after the hooked call
    with pytest.raises((RuntimeError, AssertionError)):
        check_confined(env, bytes(data))
    data = bytearray(env["data"])
    data[HOOK + 1:HOOK + 3] = le(env["old"]["EnableLCD"][1])
    with pytest.raises(RuntimeError, match="call EnableLCD"):
        pc.verify_overlay(env["base"], bytes(data), env["old"], env["new"])
