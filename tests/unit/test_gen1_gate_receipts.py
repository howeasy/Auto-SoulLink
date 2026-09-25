"""tests/live/test_gen1_gates.py's receipt-capture split (GEN1-GATE-REWRITES-RECEIPTS, post-RC): running the
live-gates lane must never overwrite the committed tests/fixtures/gen1/receipts/test_gen1_sfx_gate_*_result.txt,
which carry a `# lane HEAD=... git-status=clean` and `# cmd:` provenance header. No emulator: the gate itself
needs EmuHawk, so this covers the capture helper and its opt-in gate alone.
"""
from __future__ import annotations

import inspect
import re

from tests.live import test_gen1_gates as gates

CMD = "tools/run_gb_gate.py lua/tests/test_gen1_sfx_gate.lua --rom red_patched --target town --timeout 600"


def test_receipt_header_matches_the_committed_format():
    header = gates.receipt_header(CMD)
    lines = header.splitlines()
    assert len(lines) == 2 and header.endswith("\n")
    assert re.match(r"^# lane HEAD=[0-9a-f]{40} git-status=(clean|dirty) at=.+$", lines[0])
    assert lines[1] == f"# cmd: {CMD}"


def test_capture_receipt_writes_the_stamped_header_over_the_text(tmp_path):
    kept = tmp_path / "result.txt"
    gates.capture_receipt(str(kept), CMD, "[test_gen1_sfx_gate] title=red\n")
    text = kept.read_text(encoding="utf-8")
    assert text.startswith("# lane HEAD=")
    assert text.endswith(f"# cmd: {CMD}\n[test_gen1_sfx_gate] title=red\n")


def test_the_sfx_matrix_gate_only_captures_a_receipt_when_explicitly_asked():
    """A plain SLINK_LIVE=1 run must not touch the committed receipt copy: capture is gated behind
    SLINK_GEN1_CAPTURE_RECEIPTS=1, never unconditional (the same trap as the Gen 2 attestation, 44f6fb97)."""
    source = inspect.getsource(gates.test_gen1_sfx_matrix)
    assert 'os.environ.get("SLINK_GEN1_CAPTURE_RECEIPTS") == "1"' in source
    assert "capture_receipt(kept, cmd, text)" in source
