"""tests/live/test_gen1_gates.py's receipt-capture split (GEN1-GATE-REWRITES-RECEIPTS, post-RC): running the
live-gates lane must never overwrite the committed tests/fixtures/gen1/receipts/test_gen1_sfx_gate_*_result.txt,
which carry a `# lane HEAD=... git-status=clean` and `# cmd:` provenance header. No emulator: the gate itself
needs EmuHawk, so this drives the capture helpers behaviourally -- a faked gate outcome (passed/text) plus a
tmp receipt path -- rather than reading the test function's source (OMP cx-5176fe34).
"""
from __future__ import annotations

import re

from tests.live import test_gen1_gates as gates

CMD = "tools/run_gb_gate.py lua/tests/test_gen1_sfx_gate.lua --rom red_patched --target town --timeout 600"
HEAD = "a" * 40
TEXT = "[test_gen1_sfx_gate] title=red\n"
BEFORE = f"# lane HEAD={'0' * 40} git-status=clean at=2020-01-01T00:00:00\n# cmd: old\nold text\n"


def test_receipt_header_matches_the_committed_format():
    header = gates.receipt_header(HEAD, "clean", CMD)
    lines = header.splitlines()
    assert len(lines) == 2 and header.endswith("\n")
    assert re.match(rf"^# lane HEAD={HEAD} git-status=clean at=.+$", lines[0])
    assert lines[1] == f"# cmd: {CMD}"


def test_status_excluding_drops_only_lines_under_the_given_prefix(monkeypatch):
    """A capture written earlier in the SAME matrix (into tests/fixtures/gen1/receipts/) must not make a later
    case see a dirty tree and refuse to capture its own receipt -- but a genuinely dirty tree elsewhere still
    counts."""
    monkeypatch.setattr(gates, "_git",
                        lambda *a: " M server/state.py\n?? tests/fixtures/gen1/receipts/x_result.txt\n")
    assert gates._status_excluding("tests/fixtures/gen1/receipts/") == "dirty"
    monkeypatch.setattr(gates, "_git", lambda *a: "?? tests/fixtures/gen1/receipts/x_result.txt\n")
    assert gates._status_excluding("tests/fixtures/gen1/receipts/") == "clean"
    monkeypatch.setattr(gates, "_git", lambda *a: "")
    assert gates._status_excluding("tests/fixtures/gen1/receipts/") == "clean"


def test_atomic_write_leaves_no_partial_file(tmp_path):
    kept = tmp_path / "result.txt"
    gates._atomic_write(str(kept), "hello\n")
    assert kept.read_text(encoding="utf-8") == "hello\n"
    assert list(tmp_path.glob("*.tmp*")) == []   # no leftover .tmp<pid> sibling


def _kept(tmp_path):
    kept = tmp_path / "result.txt"
    kept.write_text(BEFORE, encoding="utf-8")
    return kept


def test_maybe_capture_receipt_is_a_noop_when_the_flag_is_absent(tmp_path, monkeypatch):
    kept = _kept(tmp_path)
    monkeypatch.delenv("SLINK_GEN1_CAPTURE_RECEIPTS", raising=False)
    wrote = gates.maybe_capture_receipt(str(kept), CMD, TEXT, passed=True, head_now=HEAD, head_before=HEAD,
                                        status_before="clean")
    assert wrote is False and kept.read_text(encoding="utf-8") == BEFORE


def test_maybe_capture_receipt_is_a_noop_when_the_flag_is_0(tmp_path, monkeypatch):
    kept = _kept(tmp_path)
    monkeypatch.setenv("SLINK_GEN1_CAPTURE_RECEIPTS", "0")
    wrote = gates.maybe_capture_receipt(str(kept), CMD, TEXT, passed=True, head_now=HEAD, head_before=HEAD,
                                        status_before="clean")
    assert wrote is False and kept.read_text(encoding="utf-8") == BEFORE


def test_maybe_capture_receipt_is_a_noop_when_the_gate_failed(tmp_path, monkeypatch):
    kept = _kept(tmp_path)
    monkeypatch.setenv("SLINK_GEN1_CAPTURE_RECEIPTS", "1")
    wrote = gates.maybe_capture_receipt(str(kept), CMD, TEXT, passed=False, head_now=HEAD, head_before=HEAD,
                                        status_before="clean")
    assert wrote is False and kept.read_text(encoding="utf-8") == BEFORE


def test_maybe_capture_receipt_is_a_noop_when_head_moved_mid_matrix(tmp_path, monkeypatch):
    kept = _kept(tmp_path)
    monkeypatch.setenv("SLINK_GEN1_CAPTURE_RECEIPTS", "1")
    wrote = gates.maybe_capture_receipt(str(kept), CMD, TEXT, passed=True, head_now="b" * 40, head_before=HEAD,
                                        status_before="clean")
    assert wrote is False and kept.read_text(encoding="utf-8") == BEFORE


def test_maybe_capture_receipt_writes_the_stamped_header_when_flagged_and_passed(tmp_path, monkeypatch):
    kept = _kept(tmp_path)
    monkeypatch.setenv("SLINK_GEN1_CAPTURE_RECEIPTS", "1")
    wrote = gates.maybe_capture_receipt(str(kept), CMD, TEXT, passed=True, head_now=HEAD, head_before=HEAD,
                                        status_before="clean")
    assert wrote is True
    text = kept.read_text(encoding="utf-8")
    assert text.startswith(f"# lane HEAD={HEAD} git-status=clean at=")
    assert text.endswith(f"# cmd: {CMD}\n{TEXT}")


def test_maybe_capture_receipt_creates_a_new_file_when_none_existed(tmp_path, monkeypatch):
    monkeypatch.setenv("SLINK_GEN1_CAPTURE_RECEIPTS", "1")
    kept = tmp_path / "new_result.txt"
    wrote = gates.maybe_capture_receipt(str(kept), CMD, TEXT, passed=True, head_now=HEAD, head_before=HEAD,
                                        status_before="clean")
    assert wrote is True and kept.exists()
