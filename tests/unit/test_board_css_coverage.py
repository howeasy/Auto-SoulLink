"""Classes the board template emits must have a rule: a class with none renders as bare text
(the save-failed banner read like prose until this test existed)."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "server" / "static"
CSS = (STATIC / "board.css").read_text(encoding="utf-8") + (STATIC / "slink.css").read_text(encoding="utf-8")


def test_board_classes_have_rules():
    for sel in (".save-warn", ".mk-warn", ".mk-conn", ".mk-conn.wrong_game", ".mk-conn.identity",
                ".mk-conn.disconnected", ".lock-rules", ".badge-lock", ".mt-Fairy", r".mt-\?\?\?"):
        assert sel in CSS, sel
