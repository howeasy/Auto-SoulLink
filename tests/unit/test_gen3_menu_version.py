"""The patch version on the Gen 3 main menu (patch/src/trade_targets/native_menu.h): the charmap line build.py hands the payload,
the per-game bindings against the measured vanilla menus and the owner ROMs, the arena slot, and what the compiler makes of it.

Absent input skips; present-but-wrong input fails.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from patch.tools import gen3_title as g

ROOT = Path(__file__).resolve().parents[2]
TT = ROOT / "patch/src/trade_targets"
ROMS = {"firered": "Pokemon - FireRed Version (USA).gba", "leafgreen": "Pokemon - LeafGreen Version (USA).gba",
        "radical_red": "Pokemon - Radical Red.gba", "emerald": "Pokemon - Emerald Version (USA, Europe).gba"}
NATIVE = ("firered", "leafgreen", "emerald")                   # the ABI2 companions (native_trade.h); Radical Red is the handlers.c body
GAMES = tuple(ROMS)

spec = importlib.util.spec_from_file_location("companion_build", ROOT / "patch/tools/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def fixture(game: str) -> dict:
    return json.loads((ROOT / f"tests/fixtures/gen3/menu_{game}.json").read_text())


def owner_rom(game: str) -> bytes:
    root = os.environ.get("SLINK_GEN3_ROMS")
    if not root:
        pytest.skip("SLINK_GEN3_ROMS (the owner ROM directory) is required")
    path = Path(root) / ROMS[game]
    if not path.exists():
        pytest.skip(f"{path} is absent")
    return path.read_bytes()


def defines(path: Path, prefix: str) -> dict[str, int]:
    """`#define <prefix>NAME 0x...` -> {NAME: int}. The C sources are CRLF under autocrlf; read_text normalises."""
    return {k: int(v.rstrip("uU"), 0) for k, v in re.findall(rf"#define {prefix}(\w+) (0x[0-9A-Fa-f]+u?|\d+u?)\b", path.read_text())}


def bindings(game: str) -> dict[str, int]:
    """Every address / geometry value the menu service is built with, under one set of names."""
    if game == "radical_red":                                    # handlers.c spells them as literals: its body links no target header
        slm = defines(ROOT / "patch/src/handlers.c", "SLM_")
        return {**slm, "TASKS": slm["TASK0"], "TYPE_BOXED": slm["MENU_TYPE_BOXED"]}
    return {**defines(TT / f"{game}.h", "SLINK_TARGET_PANEL_"), **defines(TT / f"{game}.h", "SLINK_TARGET_MENU_")}


# ---- the line --------------------------------------------------------------------------------------------------------

def test_menu_line_is_soullink_plus_the_version_in_the_game_charmap():
    assert g.menu_text("dev") == "SoulLink dev"
    assert g.menu_text("v0.3.0") == "SoulLink v0.3.0"
    assert g.menu_text("v0.3.0-dev") == "SoulLink v0.3.0"              # a -dev suffix is dropped, like the Game Boy lines
    # S o u l L i n k <space> d e v <EOS>, hand-encoded from pret charmap.txt (A=BB, a=D5, 0=A1, '.'=AD, space=00, EOS=FF)
    assert g.menu_bytes("dev") == bytes.fromhex("cde3e9e0c6dde2df00d8d9eaff")
    assert g.menu_bytes("v1.2.3") == bytes.fromhex("cde3e9e0c6dde2df00eaa2ada3ada4ff")
    assert g.menu_bytes("v1.2.3-dev") == g.menu_bytes("v1.2.3")
    assert g.menu_define("v1.2.3") == "SLINK_MENU_TEXT=" + ",".join(f"0x{b:02X}" for b in g.menu_bytes("v1.2.3"))


@pytest.mark.parametrize("version", ["dev", "v0.1.0", "v10.20.30", "v100.20.30", "v0.1.0-dev"])
def test_every_shown_version_fits_the_ten_character_line(version):
    assert len(g.check_version(version)) <= g.MAX_VERSION_CHARS == 10
    data = g.menu_bytes(version)
    assert data[-1] == 0xFF and 0xFF not in data[:-1] and len(data) <= 20


@pytest.mark.parametrize("bad", ["", "1.2.3", "v1.2", "vx.y.z", "dev-dev", "v1.2.3\n", "DEV", " dev", "v100.200.30", "v100.200.300"])
def test_versions_the_menu_line_refuses(bad):
    with pytest.raises(ValueError, match="version"):
        g.check_version(bad)
    with pytest.raises(ValueError):
        g.menu_bytes(bad)


def test_the_encoder_has_no_entry_for_what_the_font_table_may_lack():
    with pytest.raises(ValueError, match="charmap"):
        g.charmap_bytes("SoulLink é")
    with pytest.raises(ValueError, match="charmap"):
        g.charmap_bytes("a-b")


def test_charmap_agrees_with_the_decomp_when_it_is_available():
    charmap = ROOT / "patch/vendor/pokefirered/charmap.txt"
    if not charmap.exists():
        pytest.skip("patch/vendor/pokefirered is not in this checkout (the vendored decomp lives in the root checkout)")
    table = {m.group(1): int(m.group(2), 16) for m in re.finditer(r"^'(.)'\s*=\s*([0-9A-Fa-f]{2})\s*$", charmap.read_text(), re.M)}
    for version in ("dev", "v0.1.2", "v10.20.30", "v3.4.5-dev"):
        text = g.menu_text(version)
        assert g.charmap_bytes(text) == bytes(table[ch] for ch in text), version
    assert g.charmap_bytes("AZaz09. ") == bytes(table[ch] for ch in "AZaz09. ")


@pytest.mark.parametrize("game,label", [("firered", "NEW GAME"), ("leafgreen", "NEW GAME"), ("emerald", "NEW GAME"),
                                        ("radical_red", "Continue")])
def test_charmap_agrees_with_the_games_own_menu_labels(game, label):
    """The encoder spells the menu's own labels exactly as the cartridge stores them (capitals, space, lower case)."""
    assert g.charmap_bytes(label) + b"\xff" in owner_rom(game), label


def test_default_define_is_the_dev_line():
    """native_menu.h compiles a 'SoulLink dev' line when build.py passes no define."""
    text = (TT / "native_menu.h").read_text()
    body = re.search(r"#define SLINK_MENU_TEXT (.*?)\n#endif", text, re.S).group(1).replace("\\", " ")
    out = bytearray()
    for token in (t.strip() for t in body.split(",")):
        m = re.fullmatch(r"SLM_([UL])\('(.)'\)", token)
        out.append(0xBB + ord(m.group(2)) - 65 if m and m.group(1) == "U" else 0xD5 + ord(m.group(2)) - 97 if m else int(token.rstrip("uU"), 0))
    assert bytes(out) == g.menu_bytes("dev")


# ---- the bindings: measured vanilla menus, then the ROMs ----------------------------------------------------------------------

NEEDED = ("CB2", "TASK_INPUT", "TASK_SELECT", "TYPE_BOXED", "REMOVE_WINDOW", "FILL", "LEFT", "TOP", "COLS", "BASE", "TEXT_Y",
          "MARGIN", "PLAIN_TEXT", "PLAIN_SHADOW")


@pytest.mark.parametrize("game", GAMES)
def test_every_game_binds_the_whole_menu(game):
    b = bindings(game)
    for key in NEEDED + ("ADD_WINDOW", "PUT_TILEMAP", "COPY", "PRINT", "WIDTH", "TASKS"):
        assert key in b, (game, key)
    assert b["CB2"] & 1 and b["TASK_INPUT"] & 1 and b["TASK_SELECT"] & 1                  # the Thumb-set pointers the game itself stores
    assert b["REMOVE_WINDOW"] & 1 == 0 and b["FILL"] & 1 == 0                              # raw: native_menu.h ORs the Thumb bit
    assert b["TYPE_BOXED"] == 2                                                             # tMenuType: Mystery Gift (Emerald: and Events)
    if game != "radical_red":
        assert set(build.target_spec(game)) >= {f"MENU_{k}" for k in NEEDED if k != "TYPE_BOXED"} | {"MENU_TYPE_BOXED"}


def test_fire_red_leaf_green_and_radical_red_run_the_same_menu():
    fr, lg, rr = bindings("firered"), bindings("leafgreen"), bindings("radical_red")
    for key in NEEDED + ("ADD_WINDOW", "PUT_TILEMAP", "COPY", "WIDTH", "TASKS"):
        assert fr[key] == lg[key] == rr[key], key
    # AddTextPrinterParameterized4 is the one engine entry that moved between FireRed and LeafGreen
    assert fr["PRINT"] == rr["PRINT"] == 0x0812E5A4 and lg["PRINT"] == 0x0812E57C


@pytest.mark.parametrize("game", GAMES)
def test_the_window_fits_the_measured_vanilla_menu_in_every_layout(game):
    b = bindings(game)
    left, top, cols, base = b["LEFT"], b["TOP"], b["COLS"], b["BASE"]
    tiles = cols * 2                                                                        # two 8 px rows
    assert left + cols <= 30 and top + 2 <= 20 and 1 <= cols <= 24
    layouts = fixture(game)["layouts"]
    assert {"continue", "mystery_gift"} <= set(layouts)
    for name, layout in layouts.items():
        cells = {layout["map_rows"][r][c] for r in range(top, top + 2) for c in range(left, left + cols)}
        # nothing of the vanilla menu is under the window, except the last box in the Mystery Gift layout, which it sits inside
        assert cells == ({"#"} if name == "mystery_gift" else {"."}), (game, name)
        assert base + tiles <= layout["tile_limit"]                                         # below the map entries that share the block
        for first, last in layout["used_tiles"]:
            assert not (base <= last and base + tiles - 1 >= first), (game, name, first, last)


@pytest.mark.parametrize("game", GAMES)
def test_the_text_colours_are_the_menus_own_palette_entries(game):
    b = bindings(game)
    for name, layout in fixture(game)["layouts"].items():
        pal = layout["pal15"]
        white, ink, light, black = pal[10], pal[11], pal[12], pal[14]
        assert (white, black) == ("7FFF", "0000"), (game, name)
        assert ink != light and ink not in (white, black), (game, name)
        # the no-box style: a visible colour over a different shadow colour, neither the transparent index 0
        assert b["PLAIN_TEXT"] and b["PLAIN_SHADOW"] and pal[b["PLAIN_TEXT"]] != pal[b["PLAIN_SHADOW"]], (game, name)


def test_the_plain_style_matches_each_games_backdrop():
    """FireRed's menu dims a dark lavender backdrop: white text with a black shadow. Emerald's backdrop is bright and only BG0 dims:
    the menu's own dark ink with its light shadow."""
    for game in ("firered", "leafgreen", "radical_red"):
        assert (bindings(game)["PLAIN_TEXT"], bindings(game)["PLAIN_SHADOW"]) == (10, 14), game
    assert (bindings("emerald")["PLAIN_TEXT"], bindings("emerald")["PLAIN_SHADOW"]) == (11, 12)


PROLOGUE = {"ADD_WINDOW": "f0b557464e46", "REMOVE_WINDOW": "f0b50006060e", "FILL": "30b581b00006", "PUT_TILEMAP": "10b587b00006",
            "COPY": "70b583b00006", "WIDTH": "f0b557464e46", "PRINT": "70b54e464546"}     # measured on the clean dumps


@pytest.mark.parametrize("game", GAMES)
def test_the_rom_holds_the_menu_functions_and_pointers_the_header_names(game):
    rom, b = owner_rom(game), bindings(game)
    for key, prologue in PROLOGUE.items():
        at = b[key] - 0x08000000
        assert rom[at:at + 6].hex() == prologue, (game, key, hex(b[key]))
    # the three menu code pointers are literals the menu's own functions store or load, and name real Thumb prologues
    region = (0x0802F000, 0x08031000) if game == "emerald" else (0x0800C000, 0x0800D400)
    words = {int.from_bytes(rom[a - 0x08000000:a - 0x08000000 + 4], "little") for a in range(region[0], region[1], 4)}
    for key in ("CB2", "TASK_INPUT", "TASK_SELECT"):
        assert b[key] in words, (game, key)
        entry = (b[key] & ~1) - 0x08000000
        assert rom[entry:entry + 2] in (b"\x00\xb5", b"\x10\xb5"), (game, key)          # push {lr} / push {r4,lr}


@pytest.mark.parametrize("game", GAMES)
def test_the_menu_task_is_gtasks_zero_and_its_data_zero_is_the_layout(game):
    """The gate reads gTasks[0].func and gTasks[0].data[0]; a task is func(4) + four header bytes + data[16]."""
    assert bindings(game)["TASKS"] in (0x03005090, 0x03005E00)
    text = (TT / "native_menu.h").read_text()
    assert "SLM_R16(SLM_TASK0 + 8u)" in text and "SLM_R8(SLM_TASK0 + 4u)" in text           # data[0] is the layout; +4 is isActive


# ---- the arena slot ----------------------------------------------------------------------------------------------------------

def test_the_state_byte_sits_in_free_arena_between_the_script_and_the_panel():
    text = (TT / "native_trade.h").read_text()
    assert re.search(r"#define SLM_STATE \(NT_BASE\+0x920u\)", text)
    assert "_Static_assert(0x910u <= 0x920u && 0x920u + 1u <= 0x940u" in text
    slots = {int(m, 16) for path in TT.glob("*.h") for m in re.findall(r"NT_BASE\s*\+\s*0x([0-9A-Fa-f]+)u", path.read_text())}
    slots |= {int(m, 16) for m in re.findall(r"#define SLINK_\w+_OFFSET 0x([0-9A-Fa-f]+)u", (TT / "abi.h").read_text())}
    assert {0x900, 0x940} <= slots                                                            # NT_SCRIPT and NP_RUNTIME bound the gap
    assert not [s for s in slots if 0x900 < s < 0x940 and s != 0x920] and 0x920 + 1 <= 0x1000


def test_radical_reds_state_byte_is_in_the_free_ewram_tail_after_the_durable_block():
    text = (ROOT / "patch/src/handlers.c").read_text()
    rt_base = int(re.search(r"#define RT_BASE\s+(0x[0-9A-Fa-f]+)u", text).group(1), 16)
    state = bindings("radical_red")["STATE"]
    # past RT_PRESAVE (ADDRESSES.md: the free tail starts at 0x0203FF61, test_live_ewramtail watches it to 0x0203FFFF)
    assert rt_base + 0x111 <= state < 0x02040000 and state >= 0x0203FF61
    assert "_Static_assert(RT_BASE + 0x111u <= SLM_STATE" in text


def test_the_frame_hooks_call_the_menu_service_once():
    native = (TT / "native_trade.h").read_text()
    assert native.count("slm_service();") == 1
    # inside the companion frame block, after the heap clamp check and before the trade service
    assert native.index("slink_native_rival_service();") < native.index("slm_service();") < native.index("slink_trade_service(NT_STATE")
    handlers = (ROOT / "patch/src/handlers.c").read_text()
    assert handlers.count("slm_service();") == 1 and '#include "trade_targets/native_menu.h"' in handlers


# ---- build.py ----------------------------------------------------------------------------------------------------------------

def test_build_py_hands_the_payload_the_menu_line_and_records_it():
    text = (ROOT / "patch/tools/build.py").read_text()
    assert text.count("gen3_title.menu_define(") == 2                                          # the native companions and RR's body
    assert 'menu = ["-D" + gen3_title.menu_define(version or gen3_title.DEFAULT_VERSION)] if trade_candidate else []' in text
    assert '"menu": {"version": version or gen3_title.DEFAULT_VERSION' in text and '"menu_version":receipt["menu"]["version"]' in text
    assert "title_version" not in text


@pytest.mark.parametrize("bad", ["1.2.3", "v100.200.300", "vx"])
def test_build_py_refuses_a_version_the_menu_cannot_show_before_touching_a_rom(bad, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["build.py", "--target", "firered", "--version", bad, "--rom", "does-not-exist.gba"])
    with pytest.raises(SystemExit) as exit_:
        build.main()
    assert exit_.value.code == 2


# ---- the compiler --------------------------------------------------------------------------------------------------------------

def _compile(tmp_path: Path, extra: list[str], version: str) -> tuple[bytes, str]:
    """handlers.c with build.py's own flags; returns the object's read-only data and its undefined symbols."""
    if build.GCCDIR is None:
        pytest.skip("arm-none-eabi-gcc not found (set $SLINK_ARMGCC or use the root checkout's patch/vendor)")
    obj = tmp_path / "payload.o"
    cc = subprocess.run([build.GCC, *build.CFLAGS, *extra, "-D" + g.menu_define(version), "-c", str(ROOT / "patch/src/handlers.c"),
                         "-o", str(obj)], capture_output=True, text=True, timeout=180)
    assert cc.returncode == 0, cc.stderr
    assert "native_menu.h" not in cc.stderr, cc.stderr                                          # no warning from the new header
    headers = subprocess.run([build._tool("arm-none-eabi-objdump"), "-h", str(obj)], capture_output=True, text=True, timeout=60).stdout
    rodata = b""
    for name in re.findall(r"^\s*\d+\s+(\.rodata\S*)\s", headers, re.M):                         # one dump per section: a relocatable
        part = tmp_path / "part.bin"                                                            # object puts them all at address 0
        cp = subprocess.run([build.OBJCOPY, f"--dump-section={name}={part}", str(obj), str(tmp_path / "unused.o")],
                            capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0, cp.stderr
        rodata += part.read_bytes()
    undefined = subprocess.run([build.NM, "-u", str(obj)], capture_output=True, text=True, timeout=60).stdout
    return rodata, undefined


@pytest.mark.parametrize("version", ["dev", "v0.3.0", "v10.20.30"])
@pytest.mark.parametrize("title", NATIVE)
def test_the_native_payload_compiles_with_the_menu_line_in_its_rodata(title, version, tmp_path):
    rodata, undefined = _compile(tmp_path, ["-DSLINK_NATIVE_COMPANION=1", "-include", str(TT / f"{title}.h")], version)
    assert rodata.count(g.menu_bytes(version)) == 1
    # the payload links no libc: a constant struct initialiser became a memcpy in this feature's first build
    assert "memcpy" not in undefined and "memset" not in undefined


@pytest.mark.parametrize("version", ["dev", "v0.3.0"])
def test_radical_reds_body_compiles_with_the_menu_line_and_no_libc_call(version, tmp_path):
    rodata, undefined = _compile(tmp_path, [], version)
    assert rodata.count(g.menu_bytes(version)) == 1
    assert "memcpy" not in undefined and "memset" not in undefined
