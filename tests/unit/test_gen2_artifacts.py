"""Artifact execution views: public generation and Lua admission boundaries."""

import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def _data():
    return {
        "sites": {"titles": {"crystal": {"sites": {"capture": {"expected_hex": "aa"}}}}},
        "checkpoint": {"titles": {"crystal": {"primary": {"anchors": {}}}}},
        "profile": {"titles": {"crystal": {"rom_sha1": "a" * 40}}},
        "area_map": {"257": {"source": {"header_flat": 32, "header_hex": "dd"}}},
    }


def _binding():
    return {"schema": "gen2-overlay-binding-v1", "title": "crystal", "kind": "overlay",
            "rom_sha1": "b" * 40, "base_sha1": "a" * 40, "ups_sha256": "c" * 64,
            "sym_sha256": "d" * 64, "map_sha256": "e" * 64,
            "sites": {"capture": {"expected_hex": "bb"}},
            "checkpoint": {"primary": {"anchors": {}}},
            "header_anchors": [{"offset": 16, "hex": "cc"}],
            "profile_rom": {"BaseData": {"bank": 1, "addr": 16384, "flat": 16384}}}


def _view(tmp_path, row, binding=None, *, newline="\n"):
    if binding is not None:
        path = tmp_path / "data/games/gen2_crystal/overlay/binding.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(binding, sort_keys=True, indent=2) + "\n").replace("\n", newline).encode()
        path.write_bytes(raw)
        row.setdefault("binding_sha256", hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest())
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")((ROOT / "lua/gen2/artifact.lua").as_posix())
    codec = lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix())
    result = module.view(tmp_path.as_posix(), codec, lua.table_from(_data(), recursive=True),
                         "crystal", lua.table_from(row, recursive=True))
    return result if isinstance(result, tuple) else (result, None)


def test_clean_view_keeps_the_existing_facts(tmp_path):
    view, why = _view(tmp_path, {"kind": "clean", "sha1": "a" * 40})
    assert why is None and view.kind == "clean"
    assert view.rom_sha1 == "a" * 40 and view.base_sha1 == "a" * 40
    assert view.sites.capture.expected_hex == "aa" and view.binding_sha256 is None
    assert view.anchors[1].offset == 32 and view.anchors[1].hex == "dd"


def test_verified_overlay_view_selects_its_own_executed_bytes(tmp_path):
    view, why = _view(tmp_path, {"kind": "overlay", "sha1": "b" * 40, "base_sha1": "a" * 40},
                      _binding())
    assert why is None, why
    assert view.kind == "overlay" and view.rom_sha1 == "b" * 40
    assert view.sites.capture.expected_hex == "bb"
    assert view.anchors[1].offset == 16 and view.profile_rom.BaseData.flat == 16384


@pytest.mark.parametrize("change,reason", [
    ({"binding_sha256": "0" * 64}, "sha256 differs"),
    ({"sha1": "f" * 40}, "ROM/base sha1 differs"),
    ({"base_sha1": "f" * 40}, "ROM/base sha1 differs"),
])
def test_overlay_view_refuses_a_binding_not_owned_by_the_row(tmp_path, change, reason):
    row = {"kind": "overlay", "sha1": "b" * 40, "base_sha1": "a" * 40, **change}
    view, why = _view(tmp_path, row, _binding())
    assert view is None and reason in why


def test_overlay_view_never_falls_back_when_sidecar_is_missing(tmp_path):
    view, why = _view(tmp_path, {"kind": "overlay", "sha1": "b" * 40,
                               "base_sha1": "a" * 40, "binding_sha256": "0" * 64})
    assert view is None and "sidecar missing" in why


def test_overlay_digest_is_the_canonical_lf_binding_on_windows(tmp_path):
    view, why = _view(tmp_path, {"kind": "overlay", "sha1": "b" * 40,
                               "base_sha1": "a" * 40}, _binding(), newline="\r\n")
    assert why is None and view.sites.capture.expected_hex == "bb"


def test_overlay_source_context_reconstructs_the_published_gold_rom():
    image = ROOT / ".cache/gen2-build/pokegold/pokegold.gbc"
    if not image.exists():
        pytest.skip("locked pokegold.gbc input absent")
    from tools.gen2_source_data import load_overlay_context

    ctx = load_overlay_context("gold", root=ROOT)
    assert hashlib.sha1(ctx.rom).hexdigest() == "69067c4bcd74b2c567a02164896948f3a14e6d4a"
    assert ctx.symbol("wPartyMon1") == ctx.base.symbol("wPartyMon1")
    assert ctx.source_record() == ctx.base.source_record()


@pytest.mark.parametrize("raw", [b"", b"abc", bytes(range(256)), b"x" * 65537],
                         ids=["empty", "abc", "binary", "large"])
def test_shared_sha256_hashes_actual_bytes(raw):
    lua = LuaRuntime(unpack_returned_tuples=True)
    admission = lua.eval("dofile")((ROOT / "lua/admission.lua").as_posix())
    assert admission.sha256 is not None, "shared admission SHA-256 is not implemented"
    reader = lua.eval("function(read) return function(i) return read(i) end end")(
        lambda i: raw[int(i)])
    assert admission.sha256(reader, len(raw)) == hashlib.sha256(raw).hexdigest()


def test_gold_binding_generation_is_deterministic_and_resolves_execution_bytes():
    if not (ROOT / ".cache/gen2-build/pokegold/pokegold.gbc").is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from tools import gen2_artifacts

    binding = gen2_artifacts.generate_binding("gold", root=ROOT)
    assert binding["rom_sha1"] == "69067c4bcd74b2c567a02164896948f3a14e6d4a"
    assert binding["base_sha1"] == "d8b8a3600a465308c9953dfa04f0081c05bdcb94"
    assert binding["sites"]["battle_faint"]["symbol"] == "UpdateFaintedPlayerMon"
    assert gen2_artifacts.render(binding) == gen2_artifacts.render(
        gen2_artifacts.generate_binding("gold", root=ROOT))


@pytest.mark.parametrize("kind", ["site", "header"])
def test_a_new_publication_cannot_repin_unexplained_execution_bytes(monkeypatch, kind):
    if not (ROOT / ".cache/gen2-build/pokegold/pokegold.gbc").is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from patch.tools.make_ups import ups_create
    from tools.gen2_artifacts import generate_binding
    from tools.gen2_source_data import load_overlay_context

    ctx = load_overlay_context("gold", root=ROOT)
    directory = ROOT / "data/games/gen2_gold"
    if kind == "site":
        pack = json.loads((directory / "engine_signals.json").read_text())
        address = pack["titles"]["gold"]["sites"]["battle_faint"]["rom_offset"]
    else:
        # The header's byte 6 is outside the area generator's scalar checks.
        # The artifact boundary still must refuse it rather than adopt a new pin.
        areas = json.loads((directory / "area_map.json").read_text())
        address = areas["257"]["source"]["header_flat"] + 6
    image = bytearray(ctx.rom)
    image[address] ^= 1
    ups = ups_create(ctx.base.rom, bytes(image))
    publication = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_bytes())
    out = publication["outputs"]["pokegold"]
    out["sha1"] = hashlib.sha1(image).hexdigest()
    out["ups"]["sha256"] = hashlib.sha256(ups).hexdigest()
    provenance_path = (ROOT / "data/gen2/overlay_provenance.json").resolve()
    ups_path = (ROOT / out["ups"]["file"]).resolve()
    original = Path.read_bytes

    def supplied(path):
        if path.resolve() == provenance_path:
            return json.dumps(publication).encode()
        if path.resolve() == ups_path:
            return ups
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", supplied)
    with pytest.raises(ValueError, match="unexplained"):
        generate_binding("gold", root=ROOT)


@pytest.mark.parametrize("ext", ["sym", "map"])
def test_present_overlay_symbols_or_map_with_wrong_hash_are_not_skipped(monkeypatch, ext):
    if not (ROOT / ".cache/gen2-build/pokegold/pokegold.gbc").is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from tools.gen2_source_data import load_overlay_context

    target = (ROOT / f"data/gen2/gold_slink.{ext}").resolve()
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"tampered"
                        if path.resolve() == target else original(path))
    with pytest.raises(ValueError, match="differs from pinned"):
        load_overlay_context("gold", root=ROOT)


def test_overlay_cannot_switch_base_facts_even_if_row_and_binding_agree(tmp_path):
    binding = _binding()
    binding["base_sha1"] = "f" * 40
    view, why = _view(tmp_path, {"kind": "overlay", "sha1": "b" * 40,
                               "base_sha1": "f" * 40}, binding)
    assert view is None and "base differs from clean facts" in why


def test_check_mode_accepts_published_bytes_and_refuses_a_stale_binding(monkeypatch, capsys):
    if not (ROOT / ".cache/gen2-build/pokegold/pokegold.gbc").is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from tools.gen2_artifacts import main

    assert main(["--root", str(ROOT), "--title", "gold", "--check"]) == 0
    target = (ROOT / "data/games/gen2_gold/overlay/binding.json").resolve()
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"tampered"
                        if path.resolve() == target else original(path))
    assert main(["--root", str(ROOT), "--title", "gold", "--check"]) == 1
    assert "binding missing or stale" in capsys.readouterr().err


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_published_sidecar_loads_through_the_actual_lua_view(title):
    directory = ROOT / f"data/games/gen2_{title}"
    raw = (directory / "overlay/binding.json").read_bytes().replace(b"\r\n", b"\n")
    binding = json.loads(raw)
    data = {name: json.loads((directory / f"{file}.json").read_text()) for name, file in (
        ("sites", "engine_signals"), ("checkpoint", "write_checkpoint"),
        ("profile", "profile"), ("area_map", "area_map"))}
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")((ROOT / "lua/gen2/artifact.lua").as_posix())
    codec = lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix())
    view = module.view(ROOT.as_posix(), codec, lua.table_from(data, recursive=True), title,
                       lua.table_from({"kind": "overlay", "sha1": binding["rom_sha1"],
                                       "base_sha1": binding["base_sha1"],
                                       "binding_sha256": hashlib.sha256(raw).hexdigest()}))
    assert not isinstance(view, tuple), view
    assert len(view.anchors) == {"crystal": 388, "gold": 368, "silver": 368}[title]
    assert view.checkpoint.primary.execution_before.pc == data["checkpoint"]["titles"][title]["primary"]["execution_before"]["pc"]
