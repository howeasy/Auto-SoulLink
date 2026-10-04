"""C0 pin falsifiers use synthetic files; no game data or emulator is needed."""

import hashlib
import json

from tools import gen4_pins as pins


def _sha(data: bytes, name: str) -> str:
    return hashlib.new(name, data).hexdigest()


def _world(tmp_path):
    roms = {}
    rom_specs = {}
    for key, header, foundation in (
        ("heartgold", "IPKE", "gen4_hgss"),
        ("soulsilver", "IPGE", "gen4_hgss"),
        ("heartgold_hge", "IPKE", "gen4_hge"),
        ("platinum", "CPUE", "gen4_pt"),
    ):
        data = bytearray((key + "-synthetic-reference").encode() + bytes(100))
        data[12:16] = header.encode("ascii")
        path = tmp_path / f"{key}.nds"
        path.write_bytes(data)
        roms[key] = path
        rom_specs[key] = (_sha(data, "sha1"), header, foundation)

    assets = {}
    maps = {}
    for key in pins.MAP_SPECS:
        data = (key + " synthetic map").encode("ascii")
        path = tmp_path / key
        path.write_bytes(data)
        assets[key] = path
        maps[key] = (_sha(data, "sha256"), len(data), "a" * 40)
    for key in ("bizhawk_config_observed", "gen4_pins_tool"):
        path = tmp_path / key
        path.write_bytes((key + " contents").encode("ascii"))
        assets[key] = path
    sources = {}
    commits = {}
    for key in pins.SOURCE_COMMITS:
        path = tmp_path / key
        path.mkdir()
        sources[key] = path
        commits[key] = "b" * 40

    loc = pins.Locations(roms, assets, sources)

    def observe(*, source_commits=commits, source_reader=None):
        return pins.collect(
            loc,
            rom_specs=rom_specs,
            map_specs=maps,
            source_commits=source_commits,
            host_assets=("bizhawk_config_observed", "gen4_pins_tool"),
            source_reader=source_reader or (lambda _path: ("b" * 40, True)),
        )

    return loc, observe


def _lock(observed):
    return {key: observed[key] for key in ("schema_version", "artifacts", "assets", "sources", "pending")}


def test_synthetic_reference_and_direct_artifact_schema(tmp_path):
    _, observe = _world(tmp_path)
    baseline = observe()
    assert pins.check(baseline, _lock(baseline))["status"] == "PASS"
    assert baseline["artifacts"]["heartgold"]["sha1"] == _sha(
        (tmp_path / "heartgold.nds").read_bytes(), "sha1"
    )
    assert baseline["artifacts"]["heartgold_hge"]["admission"] == "RECORDED_NOT_ADMITTED"
    assert baseline["assets"]["bizhawk_config_observed"]["qualification"] == "OBSERVED_ONLY_NOT_RUN_CONFIG"
    assert baseline["pending"]["hge_duo_owner_saves"]["gate"] == "G4"


def test_one_byte_rom_mutation_is_fail_not_repin(tmp_path):
    loc, observe = _world(tmp_path)
    lock = _lock(observe())
    data = bytearray(loc.roms["heartgold"].read_bytes())
    data[-1] ^= 1
    loc.roms["heartgold"].write_bytes(data)
    result = pins.check(observe(), lock)
    assert result["status"] == "FAIL"
    assert any(i["id"] == "heartgold" and i["kind"] == "FAIL" for i in result["issues"])


def test_missing_required_rom_is_open_and_nonpassing(tmp_path):
    loc, observe = _world(tmp_path)
    lock = _lock(observe())
    loc.roms["soulsilver"].unlink()
    result = pins.check(observe(), lock)
    assert result["status"] == "OPEN"
    assert any(i["id"] == "soulsilver" and i["kind"] == "OPEN" for i in result["issues"])


def test_missing_required_asset_is_open(tmp_path):
    loc, observe = _world(tmp_path)
    lock = _lock(observe())
    loc.assets["platinum_xmap"].unlink()
    result = pins.check(observe(), lock)
    assert result["status"] == "OPEN"
    assert any(i["id"] == "platinum_xmap" and i["kind"] == "OPEN" for i in result["issues"])


def test_wrong_header_source_commit_and_map_fail(tmp_path):
    loc, observe = _world(tmp_path)
    lock = _lock(observe())
    data = bytearray(loc.roms["platinum"].read_bytes())
    data[12:16] = b"XXXX"
    loc.roms["platinum"].write_bytes(data)
    loc.assets["platinum_xmap"].write_bytes(b"changed map")
    def wrong_head(path):
        return ("c" * 40 if path.name == "hg_engine_fork" else "b" * 40, True)
    result = pins.check(observe(source_reader=wrong_head), lock)
    assert result["status"] == "FAIL"
    assert {"platinum", "platinum_xmap", "hg_engine_fork"} <= {i["id"] for i in result["issues"] if i["kind"] == "FAIL"}


def test_tracked_dirty_source_fails(tmp_path):
    _, observe = _world(tmp_path)
    result = observe(source_reader=lambda _path: ("b" * 40, False))
    assert result["issues"]
    assert all(i["kind"] == "FAIL" for i in result["issues"])


def test_changed_tool_or_observed_config_invalidates_exact_lock(tmp_path):
    loc, observe = _world(tmp_path)
    lock = _lock(observe())
    loc.assets["gen4_pins_tool"].write_bytes(b"changed tool")
    loc.assets["bizhawk_config_observed"].write_bytes(b"changed config")
    result = pins.check(observe(), lock)
    assert result["status"] == "FAIL"
    assert {"gen4_pins_tool", "bizhawk_config_observed"} <= {i["id"] for i in result["issues"] if i["kind"] == "FAIL"}


def test_candidate_cli_does_not_write_wrong_present_input(tmp_path, monkeypatch):
    _, observe = _world(tmp_path)
    wrong = observe(source_reader=lambda _path: ("c" * 40, True))
    monkeypatch.setattr(pins, "collect", lambda _locations: wrong)
    candidate = tmp_path / "candidate.json"
    assert pins.main(["--candidate", str(candidate), "--json"]) == 1
    assert not candidate.exists()


def test_missing_g0_input_cli_exits_nonzero_open(tmp_path, monkeypatch, capsys):
    loc, observe = _world(tmp_path)
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock(observe())), encoding="utf-8")
    loc.roms["heartgold"].unlink()
    missing = observe()
    monkeypatch.setattr(pins, "collect", lambda _locations: missing)
    assert pins.main(["--lock", str(lock_path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "OPEN"


def test_malformed_and_duplicate_key_lock_fail_with_json_report(tmp_path, monkeypatch, capsys):
    _, observe = _world(tmp_path)
    baseline = observe()
    monkeypatch.setattr(pins, "collect", lambda _locations: baseline)
    lock_path = tmp_path / "lock.json"
    for content in ('[]', '{"schema_version":1,"schema_version":1}'):
        lock_path.write_text(content, encoding="utf-8")
        assert pins.main(["--lock", str(lock_path), "--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "FAIL"
        assert any(i["id"] == "lock" for i in report["issues"])
