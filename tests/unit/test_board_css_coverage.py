"""Classes the board template emits must have a rule: a class with none renders as bare text
(the save-failed banner read like prose until this test existed)."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "server" / "static"
CSS = (STATIC / "board.css").read_text(encoding="utf-8") + (STATIC / "slink.css").read_text(encoding="utf-8")


def test_board_classes_have_rules():
    for sel in (".save-warn", ".mk-warn", ".mk-conn", ".mk-conn.wrong_game", ".mk-conn.identity",
                ".mk-conn.disconnected", ".lock-rules", ".badge-lock", ".mt-Fairy", r".mt-\?\?\?"):
        assert sel in CSS, sel


# ── chips: one notched shape, defined once ─────────────────────────────────────────────
_CHIPS = (".badge-lock", ".mk-pill", ".mk-tab", ".mk-gchip", ".mk-tag", ".patcher-game")
_ALL_CSS = CSS + (STATIC / "patcher.css").read_text(encoding="utf-8") + "".join(
    p.read_text(encoding="utf-8") for p in (STATIC / "themes").glob("*.css"))


def _rules(css: str):
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        yield [s.strip() for s in sel.split(",")], body


def test_every_chip_is_notched_by_one_shared_rule():
    shape = [sels for sels, body in _rules(CSS) if "clip-path" in body and "--chip-notch" in body]
    assert len(shape) == 1 and set(_CHIPS) <= set(shape[0]), shape
    # no chip rule anywhere brings the oval (or any radius) back
    for sels, body in _rules(_ALL_CSS):
        if any(s in _CHIPS for s in sels) and "border-radius" in body:
            assert re.search(r"border-radius:\s*0\s*;", body), (sels, body)
    # round things stay round
    assert re.search(r"\.mk-dot \{[^}]*border-radius: 50%", CSS)


def test_clipped_interactive_chips_keep_a_focus_ring_inside_the_shape():
    for chip in (".mk-tab", ".mk-gchip"):
        rings = [body for sels, body in _rules(CSS) if f"{chip}:focus-visible" in sels]
        assert rings and all("outline-offset: -" in b for b in rings), (chip, rings)
