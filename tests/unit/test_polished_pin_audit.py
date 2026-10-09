"""Executable pin gate and scratch-only stale/receipt controls."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import polished_pin_audit as audit

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / audit.PROVENANCE).is_file(),
                                reason="Polished overlay provenance absent")


@pytest.fixture(scope="module")
def facts():
    return audit.Facts(ROOT)


def test_tree_has_no_stale_executable_pins():
    stale = [row for row in audit.audit(ROOT) if row.status == "STALE"]
    assert not stale, "\n".join(f"{r.file}:{r.line}: {r.kind} = {r.value}" for r in stale)


def old_sha():
    # Split so this negative control does not itself pin a retired executable ROM.
    return "57f039b6e80effff564e9" + "fa9ac483f40f095b990"


def test_old_sha_in_scratch_scanned_file_fails_cli(tmp_path):
    # Overlay pins now use overlay_pin; this scanned file still pins the base-ROM control.
    relative = Path("tools/polished_live/title_check.py")
    destination = tmp_path / relative
    destination.parent.mkdir(parents=True)
    current = json.loads((ROOT / audit.PROVENANCE).read_text())["base_sha1"]
    source = (ROOT / relative).read_text(encoding="utf-8")
    assert current in source
    destination.write_text(source, encoding="utf-8")
    command = [sys.executable, str(ROOT / "tools/polished_pin_audit.py"),
               "--root", str(ROOT), "--scan-root", str(tmp_path)]
    control = subprocess.run(command, capture_output=True, text=True)
    assert control.returncode == 0, control.stdout + control.stderr
    destination.write_text(source.replace(current, old_sha()), encoding="utf-8")
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 1, run.stdout + run.stderr
    line = source[:source.index(current)].count("\n") + 1
    assert f"STALE | {relative.as_posix()}:{line} | hash | {old_sha()}" in run.stdout


def test_receipt_old_sha_is_reported_without_failing(tmp_path, capsys):
    receipt = tmp_path / audit.RECEIPTS / "old.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"sha1": old_sha()}), encoding="utf-8")
    assert audit.main(["--root", str(ROOT), "--scan-root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "HISTORICAL-RECEIPT" in output and old_sha() in output


def test_count_tuple_span_size_and_symbol_identity(tmp_path, facts):
    old_count = next(n for n in facts.old_counts["companion_overlay_spans"]
                     if n != facts.counts["companion_overlay_spans"])
    symbol = next(name for name, values in facts.old_symbols.items()
                  if name in facts.symbols and values - {facts.symbols[name]})
    old_addr = next(iter(facts.old_symbols[symbol] - {facts.symbols[symbol]}))
    old_size = next(n for n in facts.old_sizes if n != facts.ups_size)
    path = tmp_path / "test_polished_probe.py"
    path.write_text(
        f'assert len(PACK["companion_overlay_spans"]) == {old_count}\n'
        f'assert (PACK["site_count"], PACK["resolved_count"], PACK["unresolved_count"]) == '
        f'{tuple(facts.counts[k] for k in audit.COUNTS)!r}\n'
        f'assert prov["output"]["ups"]["size"] == {old_size}\n'
        f'symbols = {{{symbol!r}: (0x7E, {old_addr})}}\n'
        f'current = {{"symbol": {symbol!r}, "bank": 126, "addr": {facts.symbols[symbol]}}}\n',
        encoding="utf-8")
    rows = audit.scan_python(path, path.name, facts)
    assert [(r.line, r.status) for r in rows] == [
        (1, "STALE"), (2, "CURRENT"), (2, "CURRENT"), (2, "CURRENT"),
        (3, "STALE"), (4, "STALE"), (5, "CURRENT")]


def test_unknown_hash_and_synthetic_address_are_not_stale(tmp_path, facts):
    path = tmp_path / "test_polished_probe.py"
    unknown = "f" * 40
    path.write_text(f'SHA = {unknown!r}\nSYMS = {{"SlinkService": (0x7E, 0x7fff)}}\n'
                    f'# retired comment: {old_sha()}\n', encoding="utf-8")
    rows = audit.scan_python(path, path.name, facts)
    assert [(r.line, r.status) for r in rows] == [(1, "UNCLASSIFIED"), (2, "UNCLASSIFIED")]


@pytest.mark.parametrize(("usage", "expected"), [
    ("", "FIXTURE-IDENTITY"),
    ('pytest.skip(f"measurement {IDENTITY}")', "FIXTURE-IDENTITY"),
    ("assert live_rom_sha1 == IDENTITY", "STALE"),
    ("admit(IDENTITY)", "STALE"),
    ("alias = IDENTITY", "STALE"),
])
def test_fixture_metadata_is_not_live_admission(tmp_path, facts, usage, expected):
    path = tmp_path / "test_polished_evidence.py"
    path.write_text(
        'fixture = ROOT / "tests" / "fixtures" / "polished" / "evidence.json"\n'
        f'checksum = {"a" * 64!r}\n'
        'def load():\n'
        '    raw = fixture.read_bytes()\n'
        '    got = hashlib.sha256(raw).hexdigest()\n'
        '    assert got == checksum\n'
        'def unrelated():\n'
        '    raw = b"not the fixture"\n'
        f'IDENTITY = {old_sha()!r}\n{usage}\n', encoding="utf-8")
    rows = audit.scan_python(path, path.name, facts)
    assert [(r.status, r.value) for r in rows if r.value == old_sha()] == [(expected, old_sha())]
