"""Canonical validation rejects missing or drifted evidence without skips."""
import hashlib
import json

import pytest

from tools import build_pret_syms as build, verify_canonical_sources as validator


def test_source_pin_rejects_commit_drift(monkeypatch, tmp_path):
    monkeypatch.setattr(build, "git_output", lambda *args: "a" * 40)
    with pytest.raises(RuntimeError, match="Source commit drift"):
        build.verify_source(tmp_path, "b" * 40)


def test_source_pin_rejects_dirty_source(monkeypatch, tmp_path):
    def output(repo, *args):
        return "a" * 40 if args[0] == "rev-parse" else " M ram/wram.asm"
    monkeypatch.setattr(build, "git_output", output)
    with pytest.raises(RuntimeError, match="Dirty canonical source"):
        build.verify_source(tmp_path, "a" * 40)


def test_existing_pin_never_resets_or_fetches_moving_head(monkeypatch, tmp_path):
    (tmp_path / "pokered").mkdir()
    pin = build.load_lock()["sources"]["pokered"]
    calls = []
    monkeypatch.setattr(build, "PRET_CACHE", tmp_path)
    monkeypatch.setattr(build, "verify_source", lambda *args: None)
    monkeypatch.setattr(build, "_git", lambda repo, *args: calls.append(args))
    build._clone_or_pull("pokered", pin["url"], update=True)
    assert calls == [("fetch", "--depth=1", pin["url"], pin["commit"])]


def test_ram_parser_keeps_source_hram_addresses(tmp_path):
    sym = tmp_path / "ram.sym"
    sym.write_text("00:ff80 hDMARoutine\n00:ff8a hSoftReset\n00:d163 wPartyCount\n01:7fff ROMLabel\n")
    assert build._parse_sym(sym) == {"hDMARoutine": 0xFF80, "hSoftReset": 0xFF8A, "wPartyCount": 0xD163}


def test_rom_parser_keeps_bank_qualification():
    assert build._parse_rom_sym("01:4567 One\n02:4567 Two\n00:d163 wPartyCount\n") == {
        "One": 0x014567, "Two": 0x024567}


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    """Tiny deterministic evidence model, independent of ROM/build dependencies."""
    for attr, value in {
        "REPO_ROOT": tmp_path, "PRET_CACHE": tmp_path / ".cache/pret",
        "LOCK_FILE": tmp_path / "data/pret_sources.lock.json",
        "PROVENANCE_FILE": tmp_path / "data/pret_build_provenance.json",
        "OUT_FILE": tmp_path / "data/pret_syms.json",
        "ROM_SYMS_OUT": tmp_path / "data/pret_rom_syms.json",
    }.items():
        monkeypatch.setattr(build, attr, value)
    monkeypatch.setattr(build, "verify_source", lambda *args: None)
    monkeypatch.setattr(build, "git_output", lambda *args: "tree")
    source = "pokered"
    commit = "a" * 40
    lock = {"schema_version": 1, "rgbds_version": "v1.0.1",
            "sources": {source: {"url": "https://example.invalid/source.git", "commit": commit}},
            "clean_roms": {}}
    text = "00:d163 wPartyCount\n00:ff8a hSoftReset\n00:0100 Entry\n"
    memory = {"wPartyCount": 0xD163, "hSoftReset": 0xFF8A}
    rom_symbols = {"Entry": 0x0100}
    raw_ram = tmp_path / f".cache/pret-build/{source}/{source}.sym"
    raw_ram.parent.mkdir(parents=True)
    raw_ram.write_text(text)
    provenance = {"schema_version": 1, "sources": {source: {
        "commit": commit, "tree": "tree",
        "raw_memory_symbols_path": raw_ram.relative_to(tmp_path).as_posix(),
        "raw_memory_symbols_sha256": build.sha256(raw_ram),
        "memory_symbols_sha256": build.symbols_digest(memory)}}, "roms": {}, "toolchain": {}}
    all_rom_symbols = {}
    source_dir = tmp_path / ".cache/pret" / source
    source_dir.mkdir(parents=True)
    roms_sha1 = []
    for name in ("pokered", "pokeblue", "pokeyellow"):
        data = name.encode()
        sha1 = hashlib.sha1(data).hexdigest()
        clean = tmp_path / f"{name}.gbc"
        clean.write_bytes(data)
        built = source_dir / f"{name}.gbc"
        built.write_bytes(data)
        sym = source_dir / f"{name}.sym"
        sym.write_text(text)
        lock["clean_roms"][name] = {"source": source, "filename": clean.name, "sha1": sha1}
        provenance["roms"][name] = {
            "source": source, "source_commit": commit, "build_mode": "full-local",
            "built_rom_path": built.relative_to(tmp_path).as_posix(), "built_rom_sha1": sha1,
            "clean_rom_sha1": sha1, "raw_symbols_path": sym.relative_to(tmp_path).as_posix(),
            "raw_symbols_sha256": build.sha256(sym), "rom_symbols_sha256": build.symbols_digest(rom_symbols),
            "memory_symbols_sha256": build.symbols_digest(memory)}
        all_rom_symbols[name] = {"rom_sha1": sha1, "symbols": rom_symbols}
        roms_sha1.append(f"{sha1} *{name}.gbc")
    (source_dir / "roms.sha1").write_text("\n".join(roms_sha1))
    for tool in ("rgbasm", "rgblink", "rgbfix", "rgbgfx", "make", "gcc", "sh"):
        path = tmp_path / ".cache/tools" / tool
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tool.encode())
        provenance["toolchain"][tool] = {"path": path.relative_to(tmp_path).as_posix(),
            "version": f"{tool} v1.0.1", "sha256": build.sha256(path)}
    build._write_json(build.LOCK_FILE, lock)
    build._write_json(build.OUT_FILE, {source: memory})
    build._write_json(build.ROM_SYMS_OUT, all_rom_symbols)
    provenance["source_lock_sha256"] = build.sha256(build.LOCK_FILE)
    provenance["artifacts"] = {"data/pret_syms.json": build.sha256(build.OUT_FILE),
                               "data/pret_rom_syms.json": build.sha256(build.ROM_SYMS_OUT)}
    build._write_json(build.PROVENANCE_FILE, provenance)
    assert validator.verify()["status"] == "pass"
    return tmp_path, provenance


@pytest.mark.parametrize("relative", ["pokered.gbc", ".cache/pret/pokered/pokeyellow.gbc",
    ".cache/pret/pokered/pokeblue.sym", ".cache/pret-build/pokered/pokered.sym",
    ".cache/tools/rgbasm", "data/pret_syms.json", "data/pret_sources.lock.json"])
def test_missing_evidence_fails_closed(evidence, relative):
    root, _ = evidence
    (root / relative).unlink()
    assert validator.main(["--rom-dir", str(root), "--json"]) == 1


@pytest.mark.parametrize("relative", ["pokeblue.gbc", ".cache/pret/pokered/pokered.gbc",
    ".cache/pret/pokered/pokeblue.sym", ".cache/pret-build/pokered/pokered.sym",
    ".cache/tools/rgblink"])
def test_byte_drift_fails_closed(evidence, relative):
    root, _ = evidence
    path = root / relative
    path.write_bytes(path.read_bytes() + b"corrupt")
    assert validator.verify()["status"] == "fail"


@pytest.mark.parametrize("mutation", ["source", "partial", "version", "missing_rom", "path"])
def test_false_provenance_is_rejected(evidence, mutation):
    _, metadata = evidence
    if mutation == "source":
        metadata["roms"]["pokered"]["source_commit"] = "b" * 40
    elif mutation == "partial":
        metadata["roms"]["pokered"]["build_mode"] = "ram-only"
    elif mutation == "version":
        metadata["toolchain"]["rgbasm"]["version"] = "rgbasm v1.0.2"
    elif mutation == "missing_rom":
        del metadata["roms"]["pokeyellow"]
    else:
        metadata["roms"]["pokered"]["raw_symbols_path"] = "../outside.sym"
    build._write_json(build.PROVENANCE_FILE, metadata)
    assert validator.verify()["status"] == "fail"


def test_generated_symbol_mutation_requires_source_agreement(evidence):
    _, metadata = evidence
    table = json.loads(build.OUT_FILE.read_text())
    table["pokered"]["wPartyCount"] += 1
    build._write_json(build.OUT_FILE, table)
    # Updating the artifact hash cannot disguise disagreement with raw symbols.
    metadata["artifacts"]["data/pret_syms.json"] = build.sha256(build.OUT_FILE)
    build._write_json(build.PROVENANCE_FILE, metadata)
    report = validator.verify()
    assert report["status"] == "fail"
    assert "source-derived memory symbols: pokered" in report["failures"]
