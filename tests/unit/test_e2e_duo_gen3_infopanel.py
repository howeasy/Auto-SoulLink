"""infopanel_gen3 oracle: a known-positive and a known-negative
control for every assertion (each negative flips exactly one fact the positive holds)."""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(REPO, "tools"), REPO]
import e2e_duo as duo  # noqa: E402

from server.adapters import gen3_codec as codec  # noqa: E402

ROWS = ["DUO0|Treecko|6|22/22|38||", "|Treecko|6|22/22|38||", "DUO1|Mon|4|18/18|38||",
        "|Mon|4|18/18|38||", "Pairs alive|2/2", "Dead zones|0", "Badges|0/8"]


def _line(text):
    raw = b"\xfe".join(codec.encode_name(part, 32)[:-1].rstrip(b"\xff") for part in text.split("\n"))
    return (raw + b"\xff").ljust(32, b"\xff").hex().upper()


def _panel(rows=ROWS, closes=("A", "B"), opened=(3, 4), mutate=None):
    out = ["PANEL_ROWS " + json.dumps(rows)]
    for n in (1, 2):
        out.append(f"PANEL_OPEN {n} opened={opened[0]}->{opened[1]} drawn={opened[1]} sc2=1 lines=6 "
                   f"page=0 pages=2 vram=00000001->00000002")
        for i, row in enumerate(rows[:6]):
            hexed = _line(row.replace("|", "\n"))
            if mutate == (n, i):
                hexed = "BB" + hexed[2:]
            out.append(f"PANEL_LINE {n} {i} {hexed}")
        out.append(f"PANEL_SLOT7 {n} {_line('PAGE 1/2')}")
    out += [f"PANEL_CLOSED {n} button={b} sc2=0" for n, b in enumerate(closes, 1)]
    return "\n".join(out)


def test_panel_positive():
    assert duo.gen3_panel_problems(_panel(), 2) == []
    stale = 'PANEL_ROWS ["No linked pairs yet", "Pairs alive|0/0"]\n'
    assert duo.gen3_panel_problems(stale + _panel(), 2) == []            # the LAST payload counts
    late = _panel() + '\nPANEL_ROWS ["No linked pairs yet"]'
    assert duo.gen3_panel_problems(late, 2) == []                        # ...before the first open


def test_panel_negatives():
    assert duo.gen3_panel_problems(_panel(mutate=(1, 2)), 2)          # a drawn byte differs
    assert duo.gen3_panel_problems(_panel(closes=("A",)), 2)          # B never closed it
    assert duo.gen3_panel_problems(_panel(opened=(3, 3)), 2)          # the row never opened it
    assert duo.gen3_panel_problems(_panel(), 1)                       # rows vs links.json
    assert duo.gen3_panel_problems(_panel(rows=ROWS[:5]), 2)          # 1 page, header says 2
