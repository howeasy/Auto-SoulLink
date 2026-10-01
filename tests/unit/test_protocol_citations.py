"""docs/protocol.md cites `file.py:<a>-<b>` for the code behind each row. Those numbers drift:
the file grows, the row keeps pointing at whatever moved into that range, and nothing notices
because the prose around it is still true. This test notices, with four rules (cards C4-CITE,
C4-CITE2, C4-CITE3 and C4-CITE4).

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

Rule 4 -- snapshot fields. §4's tables name a wire field in the first cell (`ball_count`,
`blob_hex`, `pc_boxes`, `maxHP`). When such a row names exactly one such field and names no other
symbol defined in the cited file, its FIRST `server.py`/`state.py` citation must contain the field
string -- that column is supposed to point at the place the server consumes the field. Rows with
several citations are therefore judged once, on the one the row leans on; the rest of the row is
still rule 1's business. The field must also appear somewhere in the cited file: a file-wide
absence is not a drifted range (rule 2's discipline), so the row is skipped rather than guessed
at. Rows naming two fields (`hp`, `maxHP`) or a code symbol in the first cell (`_build_status_dict`,
the §4.5 builder rows) are skipped too -- measured against the pre-card document, that keeps the
judged set at the rows whose citation is answerable, and every one it finds is a real drift.

Rows no rule can judge -- several events, no symbol, no event, two citations, an incidental
mention -- are skipped, never guessed. `_INCIDENTAL` records the ones that are skipped for a
stated reason.

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
    ("hello", "server.py:1597-1604"):
        "the RETIRED seq-heuristic row; `hello` appears inside the narrative about the dropped "
        "first events, and the citation is the dup guard in handle_client",
    ("hello", "server.py:1098-1101"):  # the same row before the G4 master sync re-anchored it
        "the RETIRED seq-heuristic row, as pinned revisions spell it",
}

# The revisions this test is written against, pinned by sha (never HEAD~n).
PRE_SWEEP_REV = "7e97cb40"    # before the C4-CITE sweep: rule 1 has plenty to say
PRE_EVENT_REV = "062f812f"    # before C4-CITE2: rule 2's rows were still stale
PRE_COMMAND_REV = "cc807cf3"  # before C4-CITE3: rule 3's rows were still stale
PRE_FIELD_REV = "1729c72e"    # before C4-CITE4: the §4 field rows were still stale
PRE_FIELD_MULTI_REV = "65ebbac5"  # before C4-CITE5: the multi-citation §4 rows were still stale


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
    # A def nested inside a function is a local helper, not a name a row can cite: the calc
    # preview's `def status(mon)` must not turn every `status`-event row into a symbol row.
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
    nested = {id(n) for f in ast.walk(tree) if isinstance(f, funcs)
              for n in ast.walk(f) if n is not f and isinstance(n, (*funcs, ast.ClassDef))}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and id(node) not in nested:
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

    in_section_4 = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            in_section_4 = line.startswith("## 4.")
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

            # rule 4: a §4 snapshot-field row must cite a range that names the field. It judges
            # the row's FIRST server.py/state.py citation -- the one the row leans on -- so a row
            # carrying several citations is judged once, not once per citation.
            if in_section_4 and cites and cites[0].group(0) == match.group(0):
                field = _field_name(subject, spans, tokens)
                if field is not None:
                    if field in "\n".join(text_cache[str(path)]) and field not in window:
                        problems.append(
                            f"docs/protocol.md:{lineno}: {match.group(0)} does not contain the "
                            f"`{field}` field the row documents")
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


def _field_name(subject: str, spans: dict[str, list[tuple[int, int]]],
                tokens: list[str]) -> str | None:
    """The single wire field a §4 row's first cell names, or None when the row cannot be judged.

    None means: no name, several names (`hp`, `maxHP`), a first cell that names a code symbol
    rather than a field (the §4.5 builder rows), or another symbol of the cited file named
    elsewhere in the row (the row is about that symbol, not about the field). A field is spelled
    as a plain identifier in backticks: `stat_stages`, `ball_count`, `maxHP`.
    """
    names = [t for t in (s.strip("()") for s in BACKTICK.findall(subject)) if IDENT.fullmatch(t)]
    if len(names) != 1:
        return None
    name = names[0]
    if name in spans:
        return None
    if any(t != name and IDENT.fullmatch(t) and t in spans for t in tokens):
        return None
    return name


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


def test_the_command_rule_catches_the_pre_command_sweep_document(tmp_path, monkeypatch):
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
    # Keep this historical counterexample independent of today's line shifts:
    # its old, wrong range can otherwise happen to land on a new `seq` use.
    # Freeze the cited server alongside the already pinned document. The
    # checker and the exact expected bad range remain unchanged.
    source = subprocess.run(["git", "show", f"{PRE_COMMAND_REV}:server/server.py"], cwd=_REPO,
                            capture_output=True, text=True, encoding="utf-8")
    assert source.returncode == 0, f"{PRE_COMMAND_REV}:server/server.py unavailable"
    historical_server = tmp_path / "server.py"
    historical_server.write_text(source.stdout, encoding="utf-8")
    resolve = _resolve
    monkeypatch.setitem(globals(), "_resolve", lambda name: historical_server if name == "server.py" else resolve(name))
    problems = check_citations(text)
    assert problems, "the pre-command-sweep document passed; rule 3 has no teeth"
    assert any("server.py:2512-2523" in p and "seq" in p for p in problems), problems


def test_the_field_rule_catches_the_pre_field_sweep_document():
    """Falsifier for rule 4, pinned to the revision before C4-CITE4.

    Measured on that revision with rule 4 as it stands (it judges the first citation of
    multi-citation rows too, as of C4-CITE5): 30 of §4's 48 field rows are judged and all 30 are
    flagged -- 23 whose only server.py/state.py citation does not contain the field, plus the 7
    multi-citation rows C4-CITE5 re-anchored. The drift is not subtle: `server.py:3944-3948`
    (cited for the foe `species_id`/`level`/`active`) is the Twitch-bot startup, `4402` (box
    `slot`) is the backup listing, `3834-3859` (box `level`) is the bot config handlers, and
    `8019` (box `box`) is past the end of the file (5153 lines at that revision).
    """
    text = _doc_at(PRE_FIELD_REV)
    if text is None or "`server.py:3021-3022`" not in text:
        pytest.skip(f"{PRE_FIELD_REV}:docs/protocol.md unavailable or already re-anchored")
    problems = check_citations(text)
    assert problems, "the pre-field-sweep document passed; rule 4 has no teeth"
    assert any("server.py:3021-3022" in p and "`ball_count`" in p for p in problems), problems
    assert any("server.py:3944" in p and "`species_id`" in p for p in problems), problems


# ── C4-CITE6: every citation names a file that exists, within its line count ────────────────
#
# Rules 1-4 above only ever look at `server.py`/`state.py` citations (CITATION's own pattern),
# and only judge the ones a row's own backticked symbols/events/commands/fields let them judge.
# They have never looked at a `.lua` citation, or asked whether the *file itself* still exists --
# a citation naming a file that was deleted wholesale (the old Gen 3 client, `html_render.py`)
# slips through every one of them. This is the blunter, wider check: every `<path>.py:<a>[-<b>]`
# or `<path>.lua:<a>[-<b>]` citation anywhere in the doc must name a file this tree actually has,
# and its line range must fit inside that file. It does not ask whether the cited lines say what
# the row claims -- that is rules 1-4's job where they can reach, and a human's otherwise.
_ANY_CITATION = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|lua)):(\d+)(?:-(\d+))?")
_RESOLVE_DIRS = ("server", "lua", "tools", "tests")


def _resolve_any(path: str) -> tuple[Path | None, str | None]:
    """(file, error) for a bare-or-repo-relative `<path>.py|lua` citation; error is None on a
    clean resolve.

    A path containing "/" is repo-relative (the doc's other convention alongside bare
    basenames) and is checked directly under the repo root. A bare basename is resolved by
    searching _RESOLVE_DIRS for it: exactly one hit resolves it, zero hits is "no such file",
    and more than one is "ambiguous" -- the doc must spell an ambiguous basename out as a
    repo-relative path instead of trusting a search to pick the right one.
    """
    if "/" in path:
        candidate = _REPO / path
        return (candidate, None) if candidate.is_file() else (None, "no such file")
    hits = sorted({p for d in _RESOLVE_DIRS if (_REPO / d).is_dir()
                   for p in (_REPO / d).rglob(path)})
    if not hits:
        return None, "no such file"
    if len(hits) > 1:
        return None, f"ambiguous basename ({len(hits)} matches under {_RESOLVE_DIRS}) -- cite a repo-relative path"
    return hits[0], None



# A citation with no extension at all -- `gen3:1477` rather than `lua/gen3/client.lua:1477` --
# is invisible to _ANY_CITATION (which requires `.py`/`.lua`) and was how 85 citations into the
# deleted old Gen 3 client hid from this whole file for a full pass. `gen3:` was the only such
# prefix in the doc (checked by hand against every bare `<word>:<digit>` in it, including
# `gen1`/`gen2`/`server`/`state`/`client`/`connector`/`panel`/`boxes`/`native`/`reads`/`writes`/
# `entry`/`signals`/`deferred`/`session`/`hud`/`json` and a fully generic bare-word scan -- the
# only other matches were JSON field names in prose, `panel_abi:0`, `duration`/`choice`/`slot`,
# never a citation), so the check here is deliberately narrow rather than a generic bare-word
# scanner that would flag those field names too.
_BARE_GEN3 = re.compile(r"\bgen3:\d")


def check_all_citations_exist(text: str) -> list[str]:
    """Every `<path>.py|lua:<a>[-<b>]` citation whose file is missing, ambiguous, or whose line
    range runs past that file's own length, plus any bare `gen3:<digits>` shorthand (never a
    real path, always the deleted old client). Empty == every citation resolves."""
    problems: list[str] = []
    line_counts: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        if _BARE_GEN3.search(line):
            problems.append(
                f"docs/protocol.md:{lineno}: bare `gen3:` shorthand -- cite the real "
                f"lua/gen3/*.lua or lua/core/*.lua path instead")
        for m in _ANY_CITATION.finditer(line):
            path = m.group(1)
            end = int(m.group(3) or m.group(2))
            file, err = _resolve_any(path)
            if err:
                problems.append(f"docs/protocol.md:{lineno}: {m.group(0)} -- {err}")
                continue
            key = str(file)
            if key not in line_counts:
                line_counts[key] = len(file.read_text(encoding="utf-8", errors="replace").splitlines())
            if end > line_counts[key]:
                problems.append(
                    f"docs/protocol.md:{lineno}: {m.group(0)} -- {path} has only "
                    f"{line_counts[key]} lines")
    return problems


def test_every_citation_names_a_real_file_within_its_line_count():
    problems = check_all_citations_exist(DOC.read_text(encoding="utf-8"))
    assert not problems, "citation(s) naming a missing/ambiguous file or an out-of-range line:\n" + "\n".join(problems)


def test_the_existence_rule_catches_a_deleted_file_citation():
    """Falsifier for C4-CITE6, built fresh rather than pinned to a revision: the old Gen 3
    client (`lua/clients/gen3_frlge_client.lua`) was deleted wholesale at `addc9225`, so any
    citation of it is a real drift no line-range check could ever have caught. Proven on a
    SCRATCH copy of the doc text -- the real file on disk is never touched for this."""
    text = DOC.read_text(encoding="utf-8") + "\n\nscratch citation: `gen3_frlge_client.lua:10`\n"
    problems = check_all_citations_exist(text)
    assert any("gen3_frlge_client.lua:10" in p for p in problems), \
        "the deleted-file citation passed; C4-CITE6 has no teeth"


def test_the_bare_gen3_shorthand_is_rejected():
    """Falsifier for the bare-`gen3:` rule: 85 citations of exactly this shape (`gen3:1477`, no
    extension, no directory) pointed into the deleted old Gen 3 client and were invisible to
    _ANY_CITATION for a full pass of C4-CITE6, since that regex requires `.py`/`.lua`. Proven on
    a SCRATCH copy -- the real doc (already swept clean of every `gen3:` occurrence) is untouched."""
    text = DOC.read_text(encoding="utf-8") + "\n\nscratch citation: `gen3:1477`\n"
    problems = check_all_citations_exist(text)
    assert any("bare `gen3:`" in p for p in problems), \
        "the bare gen3: shorthand passed; the rule has no teeth"
    assert "gen3:" not in DOC.read_text(encoding="utf-8"), \
        "the real doc still has a bare gen3: citation -- the sweep was not actually completed"


def _sources_at(rev: str, dest: Path) -> bool:
    """Write server/ at `rev` under `dest`, so a pinned doc is judged against its own sources."""
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", rev, "server"], cwd=_REPO,
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ls.returncode != 0:
        return False
    for name in ls.stdout.split():
        if name.endswith(".py"):
            blob = subprocess.run(["git", "show", f"{rev}:{name}"], cwd=_REPO, capture_output=True)
            if blob.returncode != 0:
                return False
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            (dest / name).write_bytes(blob.stdout)
    return True


def test_the_field_rule_judges_the_first_citation_of_multi_citation_rows(tmp_path, monkeypatch):
    """Falsifier for the widening, pinned to the revision before C4-CITE5.

    At that revision the single-citation §4 rows were already re-anchored (C4-CITE4), so the only
    rows the widened rule can still see are the multi-citation ones: exactly 7, every one stale
    and every one reported once (the rule judges the row's first server.py/state.py citation, so
    a row with three citations does not produce three findings). The witnesses, read: `state.py:952`
    (for `maxHP`) is a `pass` in the save-loader's try; `state.py:964` (`hp`) is the bonus_keys
    restore; `state.py:2780`/`2778` (`level`/`slot`) are the pending_bonus and pending_memorials
    refs; `state.py:1033-1046` (`species_id`) is the identity-mismatch block; `server.py:3779`
    (`active`) is a docstring example; `server.py:3866` (`status_cond`) is a `pass`.
    """
    text = _doc_at(PRE_FIELD_MULTI_REV)
    if text is None or "`state.py:952`" not in text:
        pytest.skip(f"{PRE_FIELD_MULTI_REV}:docs/protocol.md unavailable or already re-anchored")
    # Judged against that revision's own sources: against today's, every later code move shifts
    # the single-citation rows too and the count stops meaning anything (it read 28 by 2026-09-25).
    if not _sources_at(PRE_FIELD_MULTI_REV, tmp_path):
        pytest.skip(f"{PRE_FIELD_MULTI_REV}:server/ unavailable")
    monkeypatch.setattr(sys.modules[__name__], "_REPO", tmp_path)
    problems = check_citations(text)
    field_problems = [p for p in problems if "field the row documents" in p]
    assert len(field_problems) == 7, problems
    assert all("field the row documents" in p or "outside the span" in p for p in problems), problems
    assert any("state.py:952" in p and "`maxHP`" in p for p in problems), problems
    assert any("server.py:3779" in p and "`active`" in p for p in problems), problems
    assert any("state.py:1033-1046" in p and "`species_id`" in p for p in problems), problems
