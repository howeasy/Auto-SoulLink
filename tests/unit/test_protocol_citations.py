"""docs/protocol.md cites `file.py:<a>-<b>` for the code behind each row. Those numbers drift:
the file grows, the row keeps pointing at whatever moved into that range, and nothing notices
because the prose around it is still true. This test notices, with two rules (cards C4-CITE and
C4-CITE2).

Rule 1 -- symbols. For every `<name>.py:<a>[-<b>]` citation on a line that also names, in
backticks, one or more code symbols DEFINED in that file, every line of the cited range must lie
inside one of those symbols' spans (Python's own AST gives the spans; a three-line tolerance
covers decorators and docstrings).

Rule 2 -- wire events. For a line whose subject (a table row's first cell, else the whole line)
names exactly one wire event from `tests/unit/protocol_schema.py:EVENTS`, and which carries
exactly one `server.py`/`state.py` citation, and which names no other symbol defined in that
file, the citation must contain the event string or lie inside a `_handle_<event>` handler.

Rule 3 -- commands and envelope fields. The same shape, one level down: when the subject names
exactly one command from `protocol_schema.COMMANDS` (including a command spelled inside a JSON
literal, `{"cmd":"noop"}`) or one envelope field (`event`, `player`, `seq`), and the line carries
exactly one `server.py`/`state.py` citation and names no other symbol, that string must be inside
the cited range. A row whose subject is a *description* rather than a name (a table's first cell
holding prose) is skipped, as are rows naming several commands.

Rows neither rule can judge -- several events, no symbol, no event, an incidental mention -- are
skipped, never guessed. `_INCIDENTAL` records the ones that are skipped for a stated reason.

It is deliberately not a link checker: it never asks whether the row's claim is true, only
whether the place it points at is still the place it names.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
DOC = _REPO / "docs" / "protocol.md"
sys.path.insert(0, str(_REPO / "tests" / "unit"))

import protocol_schema as schema  # noqa: E402

EVENTS = frozenset(schema.EVENTS)
COMMANDS = frozenset(schema.COMMANDS)
ENVELOPE_FIELDS = frozenset(schema.ENVELOPE)
CITATION = re.compile(r"([A-Za-z_][A-Za-z0-9_]*\.py):(\d+)(?:-(\d+))?")
BACKTICK = re.compile(r"`([^`\n]+)`")
IDENT = re.compile(r"_?[A-Za-z]\w*")
TOLERANCE = 3

# (event, citation) pairs the event rule skips with a reason. Keep this list short and argued:
# every entry is a row where the event name is mentioned in passing rather than being the row's
# subject, so no range could satisfy the rule.
_INCIDENTAL: dict[tuple[str, str], str] = {
    ("hello", "server.py:1098-1101"):
        "the RETIRED seq-heuristic row; `hello` appears inside the narrative about the dropped "
        "first events, and the citation is the dup guard in handle_client",
}

# The revisions this test is written against, pinned by sha (never HEAD~n).
PRE_SWEEP_REV = "7e97cb40"    # before the C4-CITE sweep: rule 1 has plenty to say
PRE_EVENT_REV = "062f812f"    # before C4-CITE2: rule 2's rows were still stale
PRE_COMMAND_REV = "cc807cf3"  # before this card: rule 3's rows were still stale


def _resolve(name: str) -> Path | None:
    for candidate in (_REPO / "server" / name, _REPO / "server" / "adapters" / name,
                      _REPO / "tools" / name, _REPO / name):
        if candidate.exists():
            return candidate
    return None


def _symbol_spans(path: Path) -> tuple[dict[str, list[tuple[int, int]]],
                                       dict[str, list[tuple[int, int]]]]:
    """(plain, attributes): plain maps a function/class/MODULE_CONSTANT name to its span;
    attributes maps a `self.<attr>` name to the span of its assignment.

    They are kept apart on purpose. An attribute name is usually also a *field* name on the wire
    (`party_keys`, `party_size`), and letting those tokens count as symbols would turn field rows
    into judged rows -- the one thing this checker must not do. Only a qualified token
    (`SoulLinkState.sync_inflight`) consults the attribute map.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    plain: dict[str, list[tuple[int, int]]] = {}
    attrs: dict[str, list[tuple[int, int]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            plain.setdefault(node.name, []).append((node.lineno, node.end_lineno or node.lineno))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            span = (node.lineno, node.end_lineno or node.lineno)
            for target in targets:
                if isinstance(target, ast.Name) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", target.id):
                    plain.setdefault(target.id, []).append(span)
                elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                        and target.value.id == "self":
                    attrs.setdefault(target.attr, []).append(span)
    return plain, attrs


def _covered(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    """True when the range sits inside one span, or inside the union of several (a row may cite
    a block that two adjacent methods make up)."""
    if any(s <= start and end <= e for s, e in spans):
        return True
    return all(any(s <= line <= e for s, e in spans) for line in (start, end))


def check_citations(text: str) -> list[str]:
    """Every drifted citation, as a printable string. Empty == clean."""
    problems: list[str] = []
    span_cache: dict[str, tuple[dict[str, list[tuple[int, int]]],
                               dict[str, list[tuple[int, int]]]]] = {}
    text_cache: dict[str, list[str]] = {}

    def spans_for(path: Path):
        if str(path) not in span_cache:
            span_cache[str(path)] = _symbol_spans(path)
            text_cache[str(path)] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return span_cache[str(path)]

    for lineno, line in enumerate(text.splitlines(), 1):
        is_row = line.startswith("|") and len(line.split("|")) > 2
        subject = line.split("|")[1] if is_row else line
        events = sorted({t for t in BACKTICK.findall(subject) if t in EVENTS})
        cites = [m for m in CITATION.finditer(line) if m.group(1) in ("server.py", "state.py")]
        tokens = [t.strip("()") for t in BACKTICK.findall(line)]

        for match in CITATION.finditer(line):
            name, start = match.group(1), int(match.group(2))
            end = int(match.group(3) or match.group(2))
            path = _resolve(name)
            if path is None:
                continue
            spans, attrs = spans_for(path)
            window = "\n".join(text_cache[str(path)][start - 1:end])

            # rule 1: the symbols this line names must cover the range. A qualified token
            # (`Class.attr`) consults the attribute map; a bare one never does.
            named = [(t, s, e) for t in tokens if IDENT.fullmatch(t) and t in spans
                     for s, e in spans[t]]
            named += [(t, s, e) for t in tokens if (q := re.fullmatch(r"[A-Z]\w*\.(\w+)", t))
                      and q.group(1) in attrs for s, e in attrs[q.group(1)]]
            if named:
                loose = [(s - TOLERANCE, e + TOLERANCE) for _, s, e in named]
                if not _covered(start, end, loose):
                    where = ", ".join(f"{t} {s}-{e}" for t, s, e in sorted(set(named)))
                    problems.append(
                        f"docs/protocol.md:{lineno}: {match.group(0)} is outside the span of the "
                        f"symbol the row names ({where})")
                continue

            # rules 2 and 3 both need the row to carry exactly this one citation
            if len(cites) != 1 or cites[0].group(0) != match.group(0):
                continue

            # rule 3: a pure command / envelope-field row must cite the string it names
            wanted = _subject_names(subject, spans, tokens)
            if wanted is not None:
                missing = [w for w in wanted if w not in window]
                if missing:
                    problems.append(
                        f"docs/protocol.md:{lineno}: {match.group(0)} does not contain the "
                        f"command/field(s) the row names ({', '.join(missing)})")
                continue

            # rule 2: a pure wire-event row must cite that event's handling
            if len(events) != 1:
                continue
            event = events[0]
            if (event, match.group(0)) in _INCIDENTAL:
                continue
            if event not in "\n".join(text_cache[str(path)]):
                continue
            handlers = spans.get(f"_handle_{event}") or spans.get("handle_" + event) or []
            if event in window or _covered(start, end, handlers):
                continue
            problems.append(
                f"docs/protocol.md:{lineno}: {match.group(0)} does not contain the `{event}` "
                f"event it documents (handlers: {handlers or 'none in this file'})")
    return problems


def _subject_names(subject: str, spans: dict[str, list[tuple[int, int]]],
                   tokens: list[str]) -> list[str] | None:
    """The commands/envelope fields the subject names, or None when the row cannot be judged.

    None means: no name, several names, or another symbol in the row (the row is about that
    symbol, not about the command). Commands may be spelled inside a JSON literal
    (`{"cmd":"noop"}`), which is how the envelope rows name them.
    """
    found: set[str] = set()
    for token in BACKTICK.findall(subject):
        if token in COMMANDS or token in ENVELOPE_FIELDS:
            found.add(token)
        for match in re.finditer(r'"cmd"\s*:\s*"([a-z_]+)"', token):
            if match.group(1) in COMMANDS:
                found.add(match.group(1))
    if len(found) != 1:
        return None
    name = next(iter(found))
    if any(t != name and IDENT.fullmatch(t) and t in spans for t in tokens):
        return None
    return [name]


def _doc_at(rev: str) -> str | None:
    proc = subprocess.run(["git", "show", f"{rev}:docs/protocol.md"], cwd=_REPO,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.stdout if proc.returncode == 0 else None


def test_every_cited_range_lies_inside_the_symbol_or_event_its_row_names():
    problems = check_citations(DOC.read_text(encoding="utf-8"))
    assert not problems, "drifted citation(s):\n" + "\n".join(problems)


def test_the_symbol_rule_catches_the_pre_sweep_document():
    """Falsifier for rule 1, pinned to the revision before the sweep.

    A checker that cannot fail is not a checker. If that revision is unavailable or no longer
    carries the drift, skip rather than pretend.
    """
    text = _doc_at(PRE_SWEEP_REV)
    if text is None or "server.py:1095-1101" not in text:
        pytest.skip(f"{PRE_SWEEP_REV}:docs/protocol.md unavailable or already swept")
    problems = check_citations(text)
    assert problems, "the pre-sweep document passed; rule 1 has no teeth"
    assert any("server.py:1095-1101" in p for p in problems), problems


def test_the_event_rule_catches_the_pre_event_sweep_document():
    """Falsifier for rule 2, pinned to the revision before this card.

    The rows this card re-anchored (hello, whiteout, party_to_box, box_to_party, the sync_retrieve
    pair, the memorialize pair, status, ghost_pos, peer_interact, rival_team_replaced) were all
    stale there, so rule 2 must report at least one of them.
    """
    text = _doc_at(PRE_EVENT_REV)
    if text is None or "state.py:945-950" not in text:
        pytest.skip(f"{PRE_EVENT_REV}:docs/protocol.md unavailable or already re-anchored")
    problems = check_citations(text)
    assert problems, "the pre-event-sweep document passed; rule 2 has no teeth"
    assert any("`hello`" in p for p in problems), problems


def test_the_command_rule_catches_the_pre_command_sweep_document():
    """Falsifier for rule 3, pinned to the revision before this card.

    The duplicate-`seq` row (`server.py:2512-2523`) is the one of the three known positives that
    rule 3 can see: it names `seq` in its subject cell. The other two -- the reply envelope and
    the malformed-JSON row -- spell their command inside a JSON literal in the *description*
    cell, which the narrow rule deliberately does not read (widening it to the description cell
    flagged 39 rows instead of 30, most of them rows citing a helper for a later clause). Those
    two were re-anchored by hand and are covered by the sweep test, not by this falsifier.
    """
    text = _doc_at(PRE_COMMAND_REV)
    if text is None or "server.py:2512-2523" not in text:
        pytest.skip(f"{PRE_COMMAND_REV}:docs/protocol.md unavailable or already re-anchored")
    problems = check_citations(text)
    assert problems, "the pre-command-sweep document passed; rule 3 has no teeth"
    assert any("server.py:2512-2523" in p and "seq" in p for p in problems), problems
