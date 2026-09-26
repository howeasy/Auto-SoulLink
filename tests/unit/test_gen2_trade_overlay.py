"""SOURCE/MODEL guards for the two-byte receptionist binding."""

import subprocess
from pathlib import Path

import pytest

from tests.unit.test_gen2_companion_abi import rgbds, pinned_repo
from tools import build_gen2_companion as build

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_receptionist_section_assembles_with_external_map_symbols(tmp_path, title):
    pinned = pinned_repo("pokecrystal" if title == "crystal" else "pokegold")
    source = tmp_path / "script.asm"
    source.write_text(("" if title == "crystal" else f"DEF _{title.upper()} EQU 1\n")
                      + f'INCLUDE "{pinned.as_posix()}/includes.asm"\n'
                      + f'INCLUDE "{(ROOT / "patch/gen2/src/trade_receptionist.asm").as_posix()}"\n')
    # Map labels deliberately remain external, as they do in the real main.o.
    result = subprocess.run([rgbds("rgbasm"), "-I", str(pinned) + "/", "-o", str(tmp_path / "script.o"), str(source)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("repo", ["pokecrystal", "pokegold"])
def test_trade_pointer_source_is_exactly_one_word(tmp_path, repo):
    source = ROOT / ".cache/gen2-build" / repo / "maps/Pokecenter2F.asm"
    original = source.read_text(encoding="utf-8")
    path = tmp_path / "maps/Pokecenter2F.asm"
    path.parent.mkdir()
    path.write_text(original, encoding="utf-8")
    found, patched = build._trade_receptionist_text(tmp_path)
    assert found == path
    assert patched.count("SlinkTradeReceptionistScript") == 1
    assert patched.replace("SlinkTradeReceptionistScript", "LinkReceptionistScript_Trade") == original
    for changed in (original.replace("LinkReceptionistScript_Trade, -1", "Missing, -1"),
                    original + next(line for line in original.splitlines(True)
                                    if "LinkReceptionistScript_Trade, -1" in line)):
        path.write_text(changed, encoding="utf-8")
        with pytest.raises(RuntimeError, match="receptionist"):
            build._trade_receptionist_text(tmp_path)


def test_trade_overlay_refuses_partial_family(tmp_path):
    (tmp_path / "slink.asm").write_text("; service\n")
    (tmp_path / "trade_items.asm").write_text("; item guard\n")
    with pytest.raises(RuntimeError, match="trade overlay requires"):
        build.overlay_plan("pokecrystal", tmp_path)


@pytest.mark.parametrize("repo", ["pokecrystal", "pokegold"])
def test_trade_exports_only_append_linker_metadata(tmp_path, repo):
    originals = {}
    files = ["maps/Pokecenter2F.asm", "engine/overworld/events.asm", "engine/menus/save.asm"]
    if repo == "pokecrystal":
        files.append("mobile/mobile_41.asm")  # BackupGSBallFlag (review 1b33bc31 NIT-2)
    for relative in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        original = (ROOT / ".cache/gen2-build" / repo / relative).read_text(encoding="utf-8")
        originals[path] = original.rstrip("\n")
        path.write_text(original, encoding="utf-8")
    edits = build.trade_export_text(tmp_path, repo)
    for path, text in edits:
        original = originals[path]
        assert text.startswith(original + "\n\nEXPORT ")
        assert len(text[len(original):].strip().splitlines()) == 1
        path.write_text(text, encoding="utf-8")
    assert build.trade_export_text(tmp_path, repo) == edits


def test_trade_trampoline_cannot_shift_existing_map_symbols(tmp_path):
    old, new = tmp_path / "old.sym", tmp_path / "new.sym"
    old.write_text("64:73b3 Pokecenter2F_MapEvents_End\n")
    new.write_text("64:73b5 Pokecenter2F_MapEvents_End\n")
    with pytest.raises(RuntimeError, match="original symbol moved"):
        build.verify_symbol_scope(old, new, panel=False)


@pytest.mark.parametrize("repo,bank,address,target", [("pokecrystal", 0x64, 0x73b1, 0x689d),
                                                    ("pokegold", 0x5c, 0x545b, 0x4d6f)])
@pytest.mark.parametrize("fault", [None, "pointer", "adjacent", "bank", "base"])
def test_linked_trade_hook_changes_only_script_word(tmp_path, repo, bank, address, target, fault):
    offset = bank * 0x4000 + address - 0x4000
    base = bytearray(0x200000)
    base[offset:offset + 2] = target.to_bytes(2, "little")
    overlay = bytearray(base)
    overlay[offset:offset + 2] = (0x7a00).to_bytes(2, "little")
    sym = tmp_path / "probe.sym"
    sym.write_text(f"{bank if fault != 'bank' else bank + 1:02x}:7a00 SlinkTradeReceptionistScript\n")
    if fault == "pointer":
        overlay[offset] ^= 1
    elif fault == "adjacent":
        overlay[offset + 2] ^= 1
    elif fault == "base":
        base[offset] ^= 1
    if fault:
        with pytest.raises(RuntimeError, match="receptionist"):
            build.verify_trade_hook(bytes(base), bytes(overlay), sym, repo)
    else:
        build.verify_trade_hook(bytes(base), bytes(overlay), sym, repo)
