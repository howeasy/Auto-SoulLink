"""tools/stamp_release.py: the plan, the version-only guarantee and the shipped-version record."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import stamp_release as sr  # noqa: E402


@pytest.fixture
def roms(tmp_path):
    for name in (*sr.GEN3_ROMS.values(), *(dump for dump, _ in sr.RB_DUMPS.values())):
        (tmp_path / name).write_bytes(b"")
    return [tmp_path]


@pytest.mark.parametrize("good", ["dev", "v0.3.0", "v10.20.30", "v0.3.0-dev"])
def test_good_versions(good):
    assert sr.check_version(good) == good


@pytest.mark.parametrize("bad", ["0.3.0", "v1.2", "v0.3.0-rc1", "v100.200.300-dev", "", "DEV", "v1.2.3 "])
def test_bad_versions_stop_the_tool(bad):
    with pytest.raises(SystemExit):
        sr.check_version(bad)


def test_every_family_is_stamped_with_the_version_and_in_dependency_order(roms):
    steps = sr.plan("v0.3.0", sr.FAMILIES, roms, promote=True)
    by_family = {f: [s for s in steps if s.family == f] for f in sr.FAMILIES}
    assert all(by_family[f] for f in sr.FAMILIES)
    builds = [s for s in steps if s.name.startswith("build ")]
    assert len(builds) == 7                                                    # RB, pureRGB, Gen 2, FR, LG, Emerald, RR
    assert all(s.argv[s.argv.index("--version") + 1] == "v0.3.0" for s in builds)
    pure = [s.name for s in by_family["pure"]]
    assert pure[0] == "build pureRGB overlay" and pure[-1] == "randomizer jar entries"      # the jar follows the regenerated entries
    assert pure.index("UPR entries") < pure.index("randomizer jar entries")
    gen2 = by_family["gen2"]
    assert gen2[0].argv[1] == "tools/build_gen2_companion.py" and "--promote-overlays" in gen2[-1].argv
    assert [s.name for s in by_family["rb"]][-1] == "pins (md5, canonical)"


def test_gen2_promotion_follows_the_rows_and_families_can_be_selected(roms, monkeypatch):
    monkeypatch.setattr(sr, "gen2_overlays_admitted", lambda: False)
    steps = sr.plan("dev", ("gen2",), roms)
    assert {s.family for s in steps} == {"gen2"} and not any("--promote-overlays" in s.argv for s in steps)     # rows BUILT: nothing to re-issue
    assert any("--promote-overlays" in s.argv for s in sr.plan("dev", ("gen2",), roms, promote=True))
    monkeypatch.setattr(sr, "gen2_overlays_admitted", lambda: True)
    assert any("--promote-overlays" in s.argv for s in sr.plan("dev", ("gen2",), roms))                      # rows ADMITTED: the grant is re-issued
    assert not any("--promote-overlays" in s.argv for s in sr.plan("dev", ("gen2",), roms, promote=False))


def test_a_missing_clean_rom_is_named(tmp_path):
    with pytest.raises(SystemExit, match="Pokemon - FireRed"):
        sr.plan("dev", ("gen3",), [tmp_path])


def test_identity_drift_names_exactly_the_moved_records():
    before = {"pure:pokered": "a" * 40, "gen2:pokegold": "b" * 40, "companion_pins:rb-red": "c" * 40, "companion_pins:rr": "d" * 40}
    after = dict(before)
    assert sr.identity_drift(before, after, sr.FAMILIES) == []
    after["gen2:pokegold"] = "e" * 40
    del after["pure:pokered"]
    drift = sr.identity_drift(before, after, sr.FAMILIES)
    assert [d.split(":")[0] for d in drift] == ["gen2", "pure"]
    assert sr.identity_drift(before, after, ("rb",)) == []                    # families that were not stamped are not judged
    assert sr.identity_drift(before, {**before, "companion_pins:rr": "0" * 40}, ("gen3",))[0].startswith("companion_pins:rr")


def test_md5_tables_follow_the_new_pins(tmp_path, monkeypatch):
    doc = tmp_path / "patch" / "README.md"
    doc.parent.mkdir()
    doc.write_text("| `SLink-RB-Red.ups` | base | `" + "1" * 32 + "` |\nother " + "2" * 32 + "\n", encoding="utf-8")
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setattr(sr, "README_TABLES", ("patch/README.md",))
    assert sr.update_md5_tables({"rb-red": "1" * 32}, {"rb-red": "3" * 32}) == ["patch/README.md"]
    text = doc.read_text(encoding="utf-8")
    assert "3" * 32 in text and "1" * 32 not in text and "2" * 32 in text
    assert sr.update_md5_tables({"rb-red": "3" * 32}, {"rb-red": "3" * 32}) == []           # nothing to do when unchanged


def test_the_version_file_binds_the_shipped_bytes(tmp_path, monkeypatch):
    dist = tmp_path / "patch" / "dist"
    dist.mkdir(parents=True)
    (dist / "SLink-RR.ups").write_bytes(b"rr")
    monkeypatch.setattr(sr, "DIST", dist)
    monkeypatch.setattr(sr, "VERSION_FILE", dist / "companion_version.json")
    doc = sr.write_version_file("v0.3.0", ("rb",))
    assert doc["version"] == "mixed" or doc["families"] == {"rb": "v0.3.0"}
    doc = sr.write_version_file("v0.3.0", sr.FAMILIES)
    assert doc["version"] == "v0.3.0" and set(doc["families"]) == set(sr.FAMILIES)
    import hashlib
    assert doc["files"] == {"SLink-RR.ups": hashlib.sha256(b"rr").hexdigest()}
    assert json.loads((dist / "companion_version.json").read_text(encoding="utf-8"))["schema"] == sr.SCHEMA


def test_the_shared_jar_is_only_installed_when_asked(roms):
    names = [s.name for s in sr.plan("dev", ("pure",), roms)]
    assert names[-1] == "randomizer jar entries"
    assert "randomizer jar entries" not in [s.name for s in sr.plan("dev", ("pure",), roms, jar=False)]


def test_plan_needs_no_clean_roms():
    steps = sr.plan("dev", sr.FAMILIES, [])
    assert any("<rom-dir>" in a for s in steps for a in s.argv)
