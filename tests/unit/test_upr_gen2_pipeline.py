"""The Gen 2 randomizer pipeline (owner ruling 2026-10-03, C-5; docs/gen2/RANDOMIZER.md): Gold /
Silver / Crystal randomize the companion OVERLAY, so every output must keep the overlay, the SLink
sections and the header byte-identical (server/upr_gen2_write_domain.py) and the rule tables --
base stats, types, the evolution graph, the learnsets -- equal to the source's
(upr_pipeline._check_content_gen2). Each check is pinned red by a one-byte mutation.

The ROM-backed tests need the pinned pret builds under .cache/gen2-build/ (absent skips, a wrong
sha1 fails). No jar runs here: prepare_pair is driven with a stand-in for randomize().
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from patch.tools.make_ups import ups_apply
from server import upr_gen2_write_domain as W, upr_pipeline as P, upr_settings as U
from server.adapters.gen2_rom_scan import Rom, RomScanError

REPO = Path(__file__).resolve().parents[2]
CLEAN = {"crystal": "pokecrystal/pokecrystal.gbc", "gold": "pokegold/pokegold.gbc",
         "silver": "pokegold/pokesilver.gbc"}
# Crystal BaseData 14:5424 and EvosAttacksPointers 10:65B1 (data/gen2/crystal_slink.sym)
BASE = 0x14 * 0x4000 + (0x5424 - 0x4000)
EVOS = 0x10 * 0x4000 + (0x65B1 - 0x4000)


def _admitted(title: str, kind: str) -> str:
    rows = json.loads((REPO / "data" / "games" / f"gen2_{title}" / "admission.json").read_text())["artifacts"]
    return next(r["sha1"] for r in rows if r["kind"] == kind and r["selection"] == "SELECTED")


@pytest.fixture(scope="module")
def roms(tmp_path_factory):
    """title -> (clean bytes, overlay bytes), for the titles whose pinned build is present."""
    out = {}
    for title, rel in CLEAN.items():
        path = REPO / ".cache" / "gen2-build" / rel
        if not path.is_file():
            continue
        clean = path.read_bytes()
        assert hashlib.sha1(clean).hexdigest() == _admitted(title, "clean"), f"{path} is not the pinned clean build"
        overlay = ups_apply(clean, (REPO / "patch" / "dist" / f"SLink-{title.title()}.ups").read_bytes())
        assert hashlib.sha1(overlay).hexdigest() == _admitted(title, "overlay"), f"{title}: overlay is not the admitted one"
        out[title] = (clean, overlay)
    return out


def _need(roms, title="crystal"):
    if title not in roms:
        pytest.skip(f"pinned Gen 2 build absent: .cache/gen2-build/{CLEAN[title]}")
    return roms[title]


def _files(tmp_path, overlay: bytes, *flips: int) -> tuple[str, str]:
    """(source overlay path, output path) where the output is the overlay with ``flips`` XORed."""
    out = bytearray(overlay)
    for off in flips:
        out[off] ^= 0x01
    src, dst = tmp_path / "overlay.gbc", tmp_path / "out.gbc"
    src.write_bytes(overlay)
    dst.write_bytes(bytes(out))
    return str(src), str(dst)


# ── the unpinned reader ──────────────────────────────────────────────────────────────────
def test_the_pinned_reader_still_refuses_the_overlay_and_the_unpinned_one_reads_it(roms):
    clean, overlay = _need(roms)
    profile = json.loads((REPO / "data/games/gen2_crystal/profile.json").read_text())["titles"]["crystal"]
    with pytest.raises(RomScanError, match="SHA1"):
        Rom(overlay, profile)
    pinned, unpinned = Rom(clean, profile), Rom(overlay, profile, pinned=False)
    assert unpinned.base_stats(1) == pinned.base_stats(1)
    assert pinned.evos_attacks(1)["evolutions"] == [[1, 16, 2]]            # Bulbasaur -> Ivysaur at 16
    assert pinned.evos_attacks(236)["evolutions"] == [[5, 20, 2, 107], [5, 20, 1, 106], [5, 20, 3, 237]]
    assert all(unpinned.evos_attacks(s) == pinned.evos_attacks(s) for s in range(1, 252))


# ── the content check ────────────────────────────────────────────────────────────────────
def test_content_check_passes_an_unchanged_overlay(roms, tmp_path):
    _clean, overlay = _need(roms)
    assert P._check_content_gen2(*_files(tmp_path, overlay))["title"] == "crystal"


@pytest.mark.parametrize("field, offset", [("hp", 1), ("speed", 4), ("type1", 7), ("growth_rate", 22)])
def test_content_check_is_red_when_a_base_stat_byte_changes(roms, tmp_path, field, offset):
    _clean, overlay = _need(roms)
    with pytest.raises(P.UprPipelineError, match="base stats or types differ"):
        P._check_content_gen2(*_files(tmp_path, overlay, BASE + 32 * 24 + offset))     # Pikachu's record


def test_content_check_is_red_when_an_evolution_or_a_learnset_changes(roms, tmp_path):
    _clean, overlay = _need(roms)
    bulbasaur = 0x10 * 0x4000 + (int.from_bytes(overlay[EVOS:EVOS + 2], "little") - 0x4000)
    assert overlay[bulbasaur:bulbasaur + 6] == bytes([1, 16, 2, 0, 1, 33])
    with pytest.raises(P.UprPipelineError, match="evolution targets differ"):
        P._check_content_gen2(*_files(tmp_path, overlay, bulbasaur + 1))
    with pytest.raises(P.UprPipelineError, match="level-up movesets differ"):
        P._check_content_gen2(*_files(tmp_path, overlay, bulbasaur + 5))


def test_content_check_ignores_the_catch_rate_and_the_tm_bits(roms, tmp_path):
    """Negative control: the minimum-catch-rate and TM / tutor compatibility options rewrite these."""
    _clean, overlay = _need(roms)
    P._check_content_gen2(*_files(tmp_path, overlay, BASE + 9, BASE + 24, BASE + 31))


def test_content_check_refuses_an_unpinned_source(roms, tmp_path):
    _clean, overlay = _need(roms)
    src, out = _files(tmp_path, overlay, BASE + 9)
    with pytest.raises(P.UprPipelineError, match="not a pinned"):
        P._check_content_gen2(out, src)


# ── the write-domain audit ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", list(CLEAN))
def test_write_domain_is_red_on_an_overlay_slink_or_header_byte(roms, tmp_path, title):
    _clean, overlay = _need(roms, title)
    geo = W.geometry(title)
    span = next(a for a, _b in geo.spans if a not in W.HEADER)
    for off, what in ((span, "companion overlay"), (geo.slink[-1][0] + 2, "SLink section"),
                      (0x140, "cartridge header")):
        with pytest.raises(P.UprPipelineError, match=what):
            W.check_output(*_files(tmp_path, overlay, off), title)
    # a vanilla table byte nowhere near the overlay is UPR's business, not this audit's
    plain = next(i for i in range(0x50000, 0x60000) if i not in geo.touched_bytes)
    assert W.check_output(*_files(tmp_path, overlay, plain), title)["changed"] == 1


def test_write_domain_needs_the_pinned_overlay_as_its_source(roms, tmp_path):
    clean, _overlay = _need(roms)
    with pytest.raises(P.UprPipelineError, match="not the pinned crystal companion overlay"):
        W.check_output(*_files(tmp_path, clean, BASE + 9), "crystal")


# ── routing ──────────────────────────────────────────────────────────────────────────────
def test_randomize_never_runs_the_gen1_identify_on_gen2_and_needs_the_fork(tmp_path, monkeypatch):
    rom = bytes(range(256)) * 8192                                          # 2 MiB stand-in
    src, jar, settings = tmp_path / "in.gbc", tmp_path / "PokeRandoZX.jar", tmp_path / "s.rnqs"
    src.write_bytes(rom)
    jar.write_bytes(b"not a jar")
    settings.write_bytes(U.build_spec(U.default_spec(U.FAMILY_GEN2), family=U.FAMILY_GEN2))
    monkeypatch.setattr(P, "_gen2_sha1s", lambda kind: {hashlib.sha1(rom).hexdigest(): "crystal"} if kind == "overlay" else {})
    monkeypatch.setattr(P, "identify", lambda _rom: pytest.fail("Gen 1 identify() ran on a Gen 2 ROM"))
    monkeypatch.setattr(P, "_run_bounded", lambda *a: pytest.fail("Java started"))
    with pytest.raises(P.UprPipelineError, match="fork jar"):
        P.randomize(str(jar), str(settings), str(src), str(tmp_path / "out.gbc"), java=sys.executable)


def _drive_prepare_pair(roms, tmp_path, monkeypatch, flips):
    """prepare_pair over two Crystal overlays with randomize() replaced: player p's output is the
    overlay with flips[p] XORed. The Gen 1 checks must never run on Gen 2."""
    from server.adapters import gen1_rom_scan
    _clean, overlay = _need(roms)
    sources = {}
    for pid in "ab":
        (tmp_path / f"{pid}_companion.gbc").write_bytes(overlay)
        sources[pid] = str(tmp_path / f"{pid}_companion.gbc")
    settings = tmp_path / "settings.rnqs"
    settings.write_bytes(U.build_spec(dict(U.default_spec(U.FAMILY_GEN2), bw_exp=True), family=U.FAMILY_GEN2))
    string = settings.read_bytes()[8:].decode("ascii")

    def fake_randomize(jar, settings_path, source, output, java="java"):
        pid = Path(output).name[0]
        data = bytearray(Path(source).read_bytes())
        for off in flips[pid]:
            data[off] ^= 0x01
        Path(output).write_bytes(data)
        return {"seed": {"a": 11, "b": 22}[pid], "settings_string": string, "version": P.SUPPORTED_UPR_VERSION,
                "output": output, "log": output + ".log", "sha1": hashlib.sha1(data).hexdigest(),
                "source_sha1": hashlib.sha1(overlay).hexdigest(), "base_kind": "overlay"}

    monkeypatch.setattr(P, "randomize", fake_randomize)
    monkeypatch.setattr(P, "identify", lambda _rom: pytest.fail("Gen 1 identify() ran on a Gen 2 ROM"))
    monkeypatch.setattr(P, "_check_content", lambda *a: pytest.fail("Gen 1 _check_content ran on Gen 2"))
    monkeypatch.setattr(gen1_rom_scan, "fingerprint_rom", lambda _rom: pytest.fail("Gen 1 fingerprint ran on Gen 2"))
    return P.prepare_pair("fork.jar", str(settings), sources, str(tmp_path / "out"))


def test_prepare_pair_routes_gen2_to_its_own_checks(roms, tmp_path, monkeypatch):
    pair = _drive_prepare_pair(roms, tmp_path, monkeypatch, {"a": [BASE + 9], "b": [BASE + 32 + 9]})
    assert pair["family"] == U.FAMILY_GEN2 and "black / white experience" in pair["summary"]
    a, b = pair["players"]["a"], pair["players"]["b"]
    assert (a["seed"], b["seed"]) == (11, 22) and a["sha1"] != b["sha1"]
    for row in (a, b):
        assert row["fingerprint"] == "" and len(row["content_hash"]) == 64
        assert row["write_domain"]["changed"] == 1 and row["write_domain"]["ups_bytes"] == 9839


def test_prepare_pair_refuses_a_gen2_output_that_wrote_into_the_overlay(roms, tmp_path, monkeypatch):
    span = next(a for a, _b in W.geometry("crystal").spans if a not in W.HEADER)
    with pytest.raises(P.UprPipelineError, match="companion overlay"):
        _drive_prepare_pair(roms, tmp_path, monkeypatch, {"a": [BASE + 9], "b": [BASE + 9, span]})


def test_prepare_pair_refuses_a_gen2_output_whose_base_stats_moved(roms, tmp_path, monkeypatch):
    with pytest.raises(P.UprPipelineError, match="base stats or types differ"):
        _drive_prepare_pair(roms, tmp_path, monkeypatch, {"a": [BASE + 1], "b": [BASE + 9]})
