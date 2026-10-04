"""Polished randomizer forms + overlay signature (fork patches 0020-0021, docs/polished/FORMS.md).

Owner ruling 2026-10-04: variant forms (forms_index.json, records 292..337) are their own mons and in the pool,
cosmetic forms are the species. The pipeline side checked here: the overlay is recognised by the SLink service's
own bytes at $7E:4000 (not by any non-$FF byte there), a real fork ini line (with its trailing comment) admits the
overlay, and the content check refuses an output whose changed species sites hold anything but a plain species or
a variant form. Each test names the mutation that turns it red.

ROM-backed tests reuse tests/unit/test_upr_polished_pipeline.py `roms` (absent skips, a wrong sha1 fails).
"""
from __future__ import annotations

import zipfile

import pytest

from server import upr_pipeline as P
from server.adapters import polished_rom_scan as S
from server.adapters.gen2_rom_scan import RomScanError
from tests.unit.test_upr_polished_pipeline import roms  # noqa: F401 -- a fixture

SERVICE = slice(0x1F8000, 0x1F8010)


def test_the_overlay_needs_the_service_bytes_not_any_byte_in_bank_7e(roms):  # noqa: F811
    """RED CONTROL: widen _is_slink_polished_overlay back to `any(b != 0xFF for b in rom[0x1F8000:0x1FC000])`."""
    release, overlay = roms
    assert P._is_slink_polished_overlay(overlay) and not P._is_slink_polished_overlay(release)
    stray = bytearray(release)
    stray[0x70:0x77], stray[0xDA8:0xDAF] = overlay[0x70:0x77], overlay[0xDA8:0xDAF]
    stray[0x1F9234] = 0x00                                     # one stray byte in bank $7E
    assert not P._is_slink_polished_overlay(bytes(stray))
    stray[SERVICE] = overlay[SERVICE]                          # positive control: the service prologue
    assert P._is_slink_polished_overlay(bytes(stray))
    stray[0x1F800F] ^= 0x01
    assert not P._is_slink_polished_overlay(bytes(stray))


def test_a_real_fork_ini_line_admits_the_overlay(roms, tmp_path):  # noqa: F811
    """The fork's overlay section line carries a trailing comment (patch 0019's ini).
    RED CONTROL: restore the `^CRCInHeader=-1\\s*$` anchor in jar_supports_polished."""
    _release, overlay = roms
    for line, ok in (("CRCInHeader=-1                 // not pinned: matched by structure", True),
                     ("CRCInHeader=-12", False)):
        jar = tmp_path / f"fork{ok}.jar"
        with zipfile.ZipFile(jar, "w") as zf:
            zf.writestr("com/dabomstew/pkrandom/config/polished_offsets.ini",
                        "[Polished Crystal (U) 3.2.3]\nCRCInHeader=0xA36C\n"
                        f"[Polished Crystal SLink overlay (U) 3.2.3]\n{line}\n")
        assert P.jar_supports_polished(str(jar), overlay) is ok, line


def test_placeable_is_plain_or_variant_never_cosmetic():
    assert S.placeable(19, 0) and S.placeable(19, 1) and S.placeable(288, 1)
    assert S.placeable(19, 2) and S.placeable(130, 21) and S.placeable(288, 2)     # Alolan Rattata, Red Gyarados
    assert not S.placeable(129, 5) and not S.placeable(201, 3)                      # Magikarp pattern, Unown C
    assert not S.placeable(16, 2) and not S.placeable(255, 0) and not S.placeable(256, 0) and not S.placeable(292, 0)


def _wild_slot0() -> int:
    return S.offsets()["JohtoGrassWildMonsOffset"] + 6       # map (2), rates (3), level, then the dp


@pytest.mark.parametrize("lo, hi, ok", [(19, 2, True),       # Alolan Rattata: a variant, placeable
                                        (0x20, 0x22, True),  # Dudunsparce three-segment (species 288, bit 8 set)
                                        (129, 5, False),     # a Magikarp pattern: cosmetic, never written
                                        (16, 2, False)])     # Pidgey has no form 2
def test_the_content_check_takes_variants_and_refuses_cosmetic_forms(roms, tmp_path, lo, hi, ok):  # noqa: F811
    """RED CONTROL: make polished_rom_scan.placeable return True -> the refusal rows pass through."""
    _release, overlay = roms
    out = bytearray(overlay)
    out[_wild_slot0()], out[_wild_slot0() + 1] = lo, hi
    src, dst = tmp_path / "overlay.gbc", tmp_path / "out.gbc"
    src.write_bytes(overlay)
    dst.write_bytes(bytes(out))
    if ok:
        P._check_content_polished(str(src), str(dst))
    else:
        with pytest.raises(P.UprPipelineError, match="no Polished site may hold"):
            P._check_content_polished(str(src), str(dst))


def test_placed_resolves_variants_to_their_records(roms):  # noqa: F811
    _release, overlay = roms
    placed = S.Rom(overlay).placed()
    variants = {(sp, f, eff) for _w, sp, f, eff in placed if eff != sp}
    assert (215, 4, 332) in variants and (128, 2, 335) in variants      # Hisuian Sneasel, Paldean Fire Tauros
    assert all(292 <= eff <= 337 for _sp, _f, eff in variants)
    assert any(f > 1 and eff == sp for _w, sp, f, eff in placed)       # cosmetic sites keep the species id
    assert len(S.Rom(overlay).trainer_mons()) == 2652


def test_a_script_site_may_change_form_only_to_a_placeable_mon(roms):  # noqa: F811
    """RED CONTROL: drop the `not placeable(species, form)` refusal in polished_rom_scan.scripted_mons."""
    _release, overlay = roms
    at = next(s["offset"] for s in S.script_sites() if s["source"] == "maps/UnionCaveB2F.asm:44")
    moltres = bytearray(overlay)
    moltres[at], moltres[at + 1] = 146, 3                          # Galarian Moltres: a variant
    assert next(m for m in S.Rom(bytes(moltres), pinned=False).scripted_mons()
                if m["source"] == "maps/UnionCaveB2F.asm:44")["form"] == 3
    lapras = bytearray(overlay)
    lapras[at + 1] = 2                                             # Lapras has no form 2
    with pytest.raises(RomScanError, match="no placeable mon"):
        S.Rom(bytes(lapras), pinned=False).scripted_mons()
