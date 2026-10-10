"""Unit tests for the pureRGB build lock — no network, no build.

Checks that data/purergb_sources.lock.json, data/purergb/build_provenance.json and the
committed data/purergb/*.sym|*.map agree with each other and with the pins recorded in
docs/purergb/PLAN.md (see tools/build_purergb_syms.py for how they were produced)."""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))
from _build_tools_bootstrap import RGBDS_PINS  # noqa: E402
from build_purergb_syms import load_lock  # noqa: E402

LOCK_PATH = REPO_ROOT / "data" / "purergb_sources.lock.json"
PROVENANCE_PATH = REPO_ROOT / "data" / "purergb" / "build_provenance.json"

PINNED_SHA1 = {
    "pokered": "2e94d09c1e16a57eb079404c030f26fdeeac949d",
    "pokeblue": "d419fe244fa17196f7df46ddab47c840e7573652",
    "pokegreen": "fe4c63a67c8b28770916cc7b1788f9eeb04ccf02",
}
PINNED_COMMIT = "7e7a46535ca332ad24ecb02e326ea2f75e79ebb9"


def _provenance() -> dict:
    return json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))


def test_load_lock_matches_plan_pins():
    lock = load_lock()
    assert lock["source"]["commit"] == PINNED_COMMIT
    assert lock["rgbds_version"] == "v1.0.3"
    assert lock["w64devkit_version"] == "2.10.0"
    for key, sha1 in PINNED_SHA1.items():
        assert lock["outputs"][key]["sha1"] == sha1


def test_lock_matches_build_provenance():
    lock = load_lock()
    provenance = _provenance()
    assert provenance["schema"] == "purergb-build-provenance-v1"
    assert provenance["source"]["commit"] == lock["source"]["commit"]
    for key, spec in lock["outputs"].items():
        assert provenance["roms"][key]["sha1"] == spec["sha1"]


def test_committed_sym_and_map_match_provenance_hashes():
    provenance = _provenance()
    for name, expected_sha256 in provenance["symbols"].items():
        data = (REPO_ROOT / "data" / "purergb" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected_sha256, name


def test_bootstrap_has_both_rgbds_pins():
    assert RGBDS_PINS["v1.0.1"]["sha256"] == (
        "554187d717cca78136a81d167107ea15742e7f622797d0b339c0bfb7ab749097"
    )
    assert RGBDS_PINS["v1.0.3"]["sha256"] == (
        "b66c23cb6d073dd3866ea30ef1ca5164549e0dae9ebe771957aff25e2658b0e3"
    )


def _mock_pure_build(tmp_path, monkeypatch):
    import build_purergb_syms as pure

    repo = tmp_path / "source"
    published = tmp_path / "published"
    repo.mkdir()
    published.mkdir()
    outputs = {}
    for key in ("pokered", "pokeblue", "pokegreen"):
        raw = b"\0" * 0x160
        (repo / f"{key}.gbc").write_bytes(raw)
        outputs[key] = {"filename": f"{key}.gbc", "sha1": hashlib.sha1(raw).hexdigest()}
        for ext in ("sym", "map"):
            body = f"{key} {ext}\n".encode()
            (repo / f"{key}.{ext}").write_bytes(body)
            (published / f"{key}.{ext}").write_bytes(body)
    lock = {"rgbds_version": "v1.0.3", "w64devkit_version": "2.10.0", "outputs": outputs,
            "make_targets": [f"{key}.gbc" for key in outputs]}
    monkeypatch.setattr(pure, "load_lock", lambda: lock)
    monkeypatch.setattr(pure, "verify_source", lambda *args: repo)
    monkeypatch.setattr(pure, "OUT_DIR", published)
    monkeypatch.setattr(pure, "PROVENANCE_PATH", published / "provenance.json")
    return pure, repo, published, lock


@pytest.mark.parametrize("builder", ["clean", "overlay"], ids=["clean", "overlay"])
def test_pure_build_compiles_host_tools_before_rom_targets(tmp_path, monkeypatch, builder):
    import os

    import build_purergb_overlay as overlay
    pure, repo, _published, lock = _mock_pure_build(tmp_path, monkeypatch)
    calls = []
    devkit = tmp_path / "devkit"

    def fake_make(argv, **kwargs):
        calls.append(argv)
        assert kwargs["env"]["PATH"].split(os.pathsep)[:2] == [str(tmp_path / "rgbds"), str(devkit)]
        if "-C" not in argv:
            assert len(calls) == 2 and calls[0][1:3] == ["-C", "tools"], "tools must be built before ROMs"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pure.subprocess, "run", fake_make)
    if builder == "clean":
        assert pure.build_rom_syms(rgbds_bin=tmp_path / "rgbds", w64devkit_bin=devkit, check=True) == 0
    else:
        overlay.make(repo, tmp_path / "rgbds", devkit, lock)
    assert len(calls) == 2 and calls[0][1:3] == ["-C", "tools"]
    assert "-B" not in calls[1], "complete sym/map sets do not need a forced ROM rebuild"


@pytest.mark.parametrize("builder", ["clean", "overlay"], ids=["clean", "overlay"])
@pytest.mark.parametrize("missing", ["sym", "map"], ids=["missing-sym", "missing-map"])
def test_existing_pure_rom_is_relinked_when_a_sidecar_is_missing(tmp_path, monkeypatch, builder, missing):
    import build_purergb_overlay as overlay
    pure, repo, published, lock = _mock_pure_build(tmp_path, monkeypatch)
    roms = {key: (repo / spec["filename"]).read_bytes() for key, spec in lock["outputs"].items()}
    (repo / f"pokered.{missing}").unlink()
    commands = []

    def fake_make(argv, **kwargs):
        commands.append(argv)
        if "-C" not in argv:
            for key in lock["outputs"]:
                if not (repo / f"{key}.gbc").exists():
                    (repo / f"{key}.gbc").write_bytes(roms[key])
                    for ext in ("sym", "map"):
                        (repo / f"{key}.{ext}").write_bytes((published / f"{key}.{ext}").read_bytes())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pure.subprocess, "run", fake_make)
    if builder == "clean":
        assert pure.build_rom_syms(rgbds_bin=tmp_path / "rgbds", w64devkit_bin=tmp_path / "devkit", check=True) == 0
    else:
        overlay.make(repo, tmp_path / "rgbds", tmp_path / "devkit", lock)
    assert (repo / f"pokered.{missing}").is_file(), "a retained up-to-date ROM must not hide lost linker outputs"
    assert "-B" not in commands[-1]
    assert not pure.PROVENANCE_PATH.exists(), "--check must not publish provenance"


def test_recovered_pure_build_still_refuses_a_wrong_rom_sha1(tmp_path, monkeypatch):
    pure, repo, published, _lock = _mock_pure_build(tmp_path, monkeypatch)
    (repo / "pokered.sym").unlink()
    before = {p.name: p.read_bytes() for p in published.iterdir()}

    def fake_make(argv, **kwargs):
        if "-C" not in argv:
            (repo / "pokered.gbc").write_bytes(b"wrong ROM")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pure.subprocess, "run", fake_make)
    with pytest.raises(RuntimeError, match="sha1 .* != locked"):
        pure.build_rom_syms(rgbds_bin=tmp_path / "rgbds", w64devkit_bin=tmp_path / "devkit", check=True)
    assert {p.name: p.read_bytes() for p in published.iterdir()} == before


@pytest.mark.parametrize("builder", ["clean", "overlay"], ids=["clean", "overlay"])
def test_host_tools_failure_stops_before_any_rom_make(tmp_path, monkeypatch, builder):
    import build_purergb_overlay as overlay
    pure, repo, _published, lock = _mock_pure_build(tmp_path, monkeypatch)
    (repo / "pokered.sym").unlink()
    commands = []

    def fake_make(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=2, stdout="", stderr="host utility compile failed")

    monkeypatch.setattr(pure.subprocess, "run", fake_make)
    with pytest.raises(RuntimeError, match="make tools failed"):
        if builder == "clean":
            pure.build_rom_syms(rgbds_bin=tmp_path / "rgbds", w64devkit_bin=tmp_path / "devkit", check=True)
        else:
            overlay.make(repo, tmp_path / "rgbds", tmp_path / "devkit", lock)
    assert len(commands) == 1 and commands[0][1:3] == ["-C", "tools"]
    assert (repo / "pokered.gbc").is_file(), "a host-tools failure must leave the stale ROM intact"


@pytest.mark.parametrize("missing", [None, "sym", "map"], ids=["warm", "repair-sym", "repair-map"])
def test_overlay_provenance_keeps_its_canonical_rom_recipe_after_recovery(tmp_path, monkeypatch, missing):
    import build_purergb_overlay as overlay
    pure, repo, _published, lock = _mock_pure_build(tmp_path, monkeypatch)
    if missing:
        (repo / f"pokered.{missing}").unlink()
    calls = []

    def fake_make(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pure.subprocess, "run", fake_make)
    command = overlay.make(repo, tmp_path / "rgbds", tmp_path / "devkit", lock)
    committed = json.loads((REPO_ROOT / "data/purergb/overlay_provenance.json").read_text())["command"]
    assert command == committed, "host-tool preparation and link recovery must not create artifact provenance drift"
    assert calls[0][1:3] == ["-C", "tools"]
    assert "-B" not in calls[1]


@pytest.mark.parametrize("missing", ["sym", "map"], ids=["lost-sym", "lost-map"])
def test_relink_recovery_preserves_prebuilt_assets_without_png_sources(tmp_path, monkeypatch, missing):
    import build_purergb_overlay as overlay
    pure, repo, published, lock = _mock_pure_build(tmp_path, monkeypatch)
    (repo / f"pokered.{missing}").unlink()
    assets = {}
    for name in ("title_logo", "title_line"):
        path = repo / f"engine/slink/{name}.2bpp"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"prebuilt {name}".encode())
        assets[path] = path.read_bytes()
        assert not path.with_suffix(".png").exists()
    original_roms = {key: (repo / spec["filename"]).read_bytes() for key, spec in lock["outputs"].items()}
    calls = []

    def fake_make(argv, **kwargs):
        calls.append(argv)
        assert "-B" not in argv, "blanket forcing would regenerate prebuilt assets from missing PNGs"
        if "-C" in argv:
            assert all((repo / spec["filename"]).is_file() for spec in lock["outputs"].values())
        else:
            assert not (repo / "pokered.gbc").exists(), "invalidate only the stale link target"
            assert (repo / "pokeblue.gbc").read_bytes() == original_roms["pokeblue"]
            assert (repo / "pokegreen.gbc").read_bytes() == original_roms["pokegreen"]
            (repo / "pokered.gbc").write_bytes(original_roms["pokered"])
            for ext in ("sym", "map"):
                (repo / f"pokered.{ext}").write_bytes((published / f"pokered.{ext}").read_bytes())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pure.subprocess, "run", fake_make)
    command = overlay.make(repo, tmp_path / "rgbds", tmp_path / "devkit", lock)
    assert len(calls) == 2 and calls[0][1:3] == ["-C", "tools"]
    assert (repo / f"pokered.{missing}").read_bytes() == (published / f"pokered.{missing}").read_bytes()
    assert {path: path.read_bytes() for path in assets} == assets
    assert command == "make -j4 pokered.gbc pokeblue.gbc pokegreen.gbc"


@pytest.mark.parametrize("invalid", ["outside", "prebuilt-asset"], ids=["outside-checkout", "non-rom"])
def test_relink_refuses_invalid_targets_before_touching_any_file(tmp_path, monkeypatch, invalid):
    pure, repo, _published, lock = _mock_pure_build(tmp_path, monkeypatch)
    (repo / "pokered.sym").unlink()
    target = tmp_path / "outside.gbc" if invalid == "outside" else repo / "engine/slink/title_logo.2bpp"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"must stay untouched")
    lock["outputs"]["pokered"]["filename"] = str(target)
    monkeypatch.setattr(pure.subprocess, "run", lambda *args, **kw: pytest.fail("invalid target must fail before make"))
    with pytest.raises(RuntimeError, match="refusing to invalidate"):
        pure.make_roms(repo, tmp_path / "rgbds", tmp_path / "devkit", lock)
    assert target.read_bytes() == b"must stay untouched" and (repo / "pokered.gbc").is_file()
