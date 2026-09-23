"""docs/protocol.md cites `file.py:<a>-<b>` for the code behind each row. Those numbers drift:
the file grows, the row keeps pointing at whatever moved into that range, and nothing notices
because the prose around it is still true. This test notices.

The rule (card C4-CITE):

  For every `<name>.py:<a>[-<b>]` citation on a line that also names, in backticks, one or more
  code symbols DEFINED in that file, the cited range must lie inside one of those symbols'
  spans (Python's own AST gives the spans; a three-line tolerance covers decorators and
  docstrings). Rows that name no such symbol -- field-name rows, for instance -- are skipped
  rather than guessed at.

It is deliberately not a link checker: it never asks whether the row's claim is true, only
whether the place it points at is still the place it names.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
DOC = _REPO / "docs" / "protocol.md"

CITATION = re.compile(r"([A-Za-z_][A-Za-z0-9_]*\.py):(\d+)(?:-(\d+))?")
BACKTICK = re.compile(r"`([^`\n]+)`")
TOLERANCE = 3

# The revision whose docs/protocol.md still carried the pre-sweep drift (the commit this test
# was written against). The falsifier below skips rather than fails if history has moved on.
_PRE_FIX_REV = "7e97cb40"   # the doc just before the C4-CITE sweep (pinned: HEAD~1 drifts)
# Citations the sweep rewrote that THIS checker can see. Its rule needs the row to name a code
# symbol, so the two rows the card started from (item 15/16, whose rows name wire fields rather
# than symbols) are skipped by design and cannot be used as the falsifier.
_KNOWN_DRIFTED = ("server.py:1095-1101", "state.py:900-918", "base.py:495-513")


def _resolve(name: str) -> Path | None:
    for candidate in (_REPO / "server" / name, _REPO / "server" / "adapters" / name,
                      _REPO / "tools" / name, _REPO / name):
        if candidate.exists():
            return candidate
    return None


def _spans(path: Path) -> dict[str, list[tuple[int, int]]]:
    """name -> [(first line, last line)] for every function, class and MODULE_CONSTANT."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    out: dict[str, list[tuple[int, int]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.setdefault(node.name, []).append((node.lineno, node.end_lineno or node.lineno))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", target.id):
                    out.setdefault(target.id, []).append((node.lineno, node.end_lineno or node.lineno))
    return out


def check_citations(text: str, repo: Path = _REPO) -> list[str]:
    """Every drifted citation, as a printable string. Empty == clean."""
    problems: list[str] = []
    span_cache: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in CITATION.finditer(line):
            name, start = match.group(1), int(match.group(2))
            end = int(match.group(3) or match.group(2))
            path = _resolve(name) if repo == _REPO else None
            if path is None:
                continue                                  # not a file in this repo: skip, never guess
            key = str(path)
            if key not in span_cache:
                span_cache[key] = _spans(path)
            spans = span_cache[key]
            named: list[tuple[str, int, int]] = []
            for token in BACKTICK.findall(line):
                token = token.strip("()")
                if re.fullmatch(r"_?[A-Za-z]\w*", token) and token in spans:
                    named.extend((token, s, e) for s, e in spans[token])
            if not named:
                continue                                  # no identifiable symbol: skip
            if any(s - TOLERANCE <= start and end <= e + TOLERANCE for _, s, e in named):
                continue
            where = ", ".join(f"{t} {s}-{e}" for t, s, e in sorted(set(named)))
            problems.append(f"docs/protocol.md:{lineno}: {name}:{start}-{end} is outside the "
                            f"span of the symbol the row names ({where})")
    return problems


def test_every_cited_range_lies_inside_the_symbol_its_row_names():
    problems = check_citations(DOC.read_text(encoding="utf-8"))
    assert not problems, "drifted citation(s):\n" + "\n".join(problems)


def test_the_checker_catches_the_pre_fix_document():
    """The falsifier: the same check run over the revision before the sweep must find drift.

    A checker that cannot fail is not a checker. If the pre-fix revision no longer contains
    those citations (history moved, the doc was rewritten), skip rather than pretend.
    """
    proc = subprocess.run(["git", "show", f"{_PRE_FIX_REV}:docs/protocol.md"],
                          cwd=_REPO, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0 or not any(c in proc.stdout for c in _KNOWN_DRIFTED):
        pytest.skip(f"{_PRE_FIX_REV}:docs/protocol.md no longer carries the item 15/16 drift")
    problems = check_citations(proc.stdout)
    assert problems, "the pre-fix document passed; the checker has no teeth"
    assert any(c in "\n".join(problems) for c in _KNOWN_DRIFTED), problems
