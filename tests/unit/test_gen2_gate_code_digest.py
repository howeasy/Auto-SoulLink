"""CODE-DIGEST runner half for the client-path live gates: every receipt a gate runner writes goes through
tests/live/test_gen2_new_gates.stamped (a top-level "code_digest", tools/gen2_code_digest.run_stamp). No emulator."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.live import test_gen2_new_gates as live
from tools import gen2_code_digest

LIVE = Path(__file__).resolve().parents[2] / "tests/live"
RUNNERS = ("frame_align", "write_windows", "panel_gate", "sfx_gate", "w6_gate", "phone_gate", "sp_lowwater_gate",
           "u1g")


def _is_stamped(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "stamped"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "live")


def receipt_writes(source):
    """(function, stamped?) for every `<path>.write_text(json.dumps(X, ...))` whose path names a receipt."""
    out = []
    for func in (n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)):
        stamped_names = {t.id for n in ast.walk(func) if isinstance(n, ast.Assign) and _is_stamped(n.value)
                         for t in n.targets if isinstance(t, ast.Name)}
        for call in (n for n in ast.walk(func) if isinstance(n, ast.Call)):
            if not (isinstance(call.func, ast.Attribute) and call.func.attr == "write_text" and call.args):
                continue
            target = ast.unparse(call.func.value)
            dumped = call.args[0]
            while isinstance(dumped, ast.BinOp):   # json.dumps(...) + "\n"
                dumped = dumped.left
            if not (isinstance(dumped, ast.Call) and ast.unparse(dumped.func) == "json.dumps"):
                continue
            if not any(word in target for word in ("RECEIPTS", "receipt_path", "receipt_file", "receipts/", "path")) or "RUNS" in target:
                continue
            value = dumped.args[0]
            out.append((func.name, _is_stamped(value) or (isinstance(value, ast.Name) and value.id in stamped_names)))
    return out


@pytest.mark.parametrize("runner", RUNNERS)
def test_every_gate_receipt_write_carries_the_code_stamp(runner):
    writes = receipt_writes((LIVE / f"test_gen2_{runner}.py").read_text(encoding="utf-8"))
    assert writes, f"{runner}: no receipt write found"
    assert all(ok for _, ok in writes), [name for name, ok in writes if not ok]


def test_stamped_claims_only_its_own_session(monkeypatch):
    stamp = {"schema": "gen2-code-digest-v1", "digest": "d" * 64, "commit": "c" * 40, "scope": [], "dirty": []}
    monkeypatch.setattr(live, "_CODE_STAMP", dict(stamp))
    assert live.stamped({"a": 1}) == {"a": 1, "code_digest": stamp}
    assert gen2_code_digest.stamp_verdict(live.stamped({})["code_digest"], "d" * 64) is None
    ours, other = {"x": 1, "code_digest": stamp}, {"x": 1, "code_digest": dict(stamp, digest="e" * 64)}
    assert live.stamped(ours, base=ours)["code_digest"] == stamp
    assert "code_digest" not in live.stamped(other, base=other)          # another run's evidence: no claim
    assert "code_digest" not in live.stamped({"x": 1}, base={"x": 1})    # an unstamped base: no claim
