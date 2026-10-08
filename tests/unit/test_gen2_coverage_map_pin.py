"""Coverage protocol pins: raw-byte hashing and byte-preserving scratch updates."""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from tools import coverage_map, gen2_coverage_map_pin as pin

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not pin.PROTOCOL.is_file() or not pin.MAP.is_file(),
                                reason="protocol.md or Gen 2 coverage map absent")


def run(*args):
    return subprocess.run([sys.executable, str(ROOT / "tools/gen2_coverage_map_pin.py"), *args],
                          capture_output=True, text=True)


def test_current_tree_is_current_without_writing():
    before = pin.MAP.read_bytes()
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "STALE" not in result.stdout
    for occurrence in pin.pins(before):
        assert f"CURRENT | {pin.MAP}:{occurrence.line} | {occurrence.value}" in result.stdout
    assert pin.MAP.read_bytes() == before


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
def test_changed_protocol_repin_changes_only_hash_literals(tmp_path, eol):
    protocol = tmp_path / "protocol.md"
    mapping = tmp_path / "coverage.md"
    source = pin.PROTOCOL.read_bytes()
    # One byte only, outside the lane's normative section.
    protocol.write_bytes(source.replace(b"#", b"!", 1))
    assert sum(a != b for a, b in zip(source, protocol.read_bytes(), strict=True)) == 1
    before = pin.MAP.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", eol)
    mapping.write_bytes(before)
    args = ("--protocol", str(protocol), "--map", str(mapping))
    stale = run(*args, "--check")
    assert stale.returncode == 1, stale.stdout + stale.stderr
    assert "STALE |" in stale.stdout
    assert mapping.read_bytes() == before
    written = run(*args, "--write")
    assert written.returncode == 0, written.stdout + written.stderr
    assert f"--- {mapping}" in written.stdout and f"+++ {mapping} (updated)" in written.stdout
    assert "After write:\nCURRENT |" in written.stdout
    after = mapping.read_bytes()
    digest = hashlib.sha256(protocol.read_bytes()).hexdigest().encode("ascii")
    cursor = 0
    for occurrence in pin.pins(before):
        assert before[cursor:occurrence.start] == after[cursor:occurrence.start]
        assert after[occurrence.start:occurrence.end] == digest
        cursor = occurrence.end
    assert before[cursor:] == after[cursor:]
    assert len(before) == len(after)
    current = run(*args)
    assert current.returncode == 0 and "STALE" not in current.stdout
    assert f"protocol SHA256 (raw bytes): {digest.decode('ascii')}" in current.stdout
    # Writing already-current pins is a byte-for-byte no-op.
    assert run(*args, "--write").returncode == 0
    assert mapping.read_bytes() == after


def test_lane_hash_matches_cli_and_crlf_is_not_normalised(tmp_path, monkeypatch, capsys):
    captured = []
    validate = coverage_map.validate_coverage

    def capture(*args, **kwargs):
        captured.append(kwargs["inputs"]["protocol"])
        return validate(*args, **kwargs)

    monkeypatch.setattr(coverage_map, "validate_coverage", capture)
    raw = pin.PROTOCOL.read_bytes().replace(b"\r\n", b"\n")
    for label, data in (("lf", raw), ("crlf", raw.replace(b"\n", b"\r\n"))):
        protocol = tmp_path / f"{label}.md"
        protocol.write_bytes(data)
        # Execute the lane's real read_bytes/hash path. Full map policy is not
        # under test here; validate_coverage still runs, without faking a pass.
        coverage_map.main([
            "--map", str(pin.MAP),
            "--requirements", str(ROOT / "docs/gen2/gen2_requirements.md"),
            "--protocol", str(protocol), "--protocol-section", "9",
            "--protocol-layers", "SOURCE", "PHYSICAL",
            "--artifact-policy", str(ROOT / "data/gen2_sources.lock.json"),
            "--artifact-collection", "outputs", "--artifact-digest-field", "sha1",
            "--artifact-id", "pokecrystal", "--artifact-id", "pokegold",
            "--artifact-id", "pokesilver",
        ])
        assert len(captured) == (1 if label == "lf" else 2), capsys.readouterr()
        result = run("--protocol", str(protocol))
        assert result.returncode in (0, 1), result.stdout + result.stderr
        assert f"protocol SHA256 (raw bytes): {captured[-1]}" in result.stdout
        assert captured[-1] == hashlib.sha256(data).hexdigest()
    assert captured[0] != captured[1], "lane unexpectedly normalised CRLF"


def test_missing_pin_refuses_write_without_changing_map(tmp_path):
    mapping = tmp_path / "incomplete.md"
    before = b'| protocol | ' + b"0" * 64 + b' |\r\n'
    mapping.write_bytes(before)
    result = run("--map", str(mapping), "--write")
    assert result.returncode == 2 and "both a protocol table pin" in result.stdout
    assert mapping.read_bytes() == before
