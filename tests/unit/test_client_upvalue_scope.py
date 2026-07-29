"""A client's dispatcher must not reference a local declared below it.

Lua resolves a name to a local only if the `local` statement appears *earlier* in the
enclosing chunk. Declare the queue after the function that uses it and the reference
silently binds to a nil GLOBAL instead — valid Lua, so `luac`/lupa parse it happily, and
the file passes every syntax gate we have.

Gen 1 shipped exactly that. `lua/clients/gen1_rby_client.lua` declared
`local pending_sync_cmds = {}` at line 334 while `dispatch_commands` (line 207) read it at
lines 246-282. All three deferred-command branches — box_mon, party_mon, memorialize — open
with `ipairs(pending_sync_cmds)`, so the first one the server sent raised
"attempt to index a nil value" out of the frame handler. Party sync and memorialize could
never have worked. The unit suite never saw it, because it exercises the Python adapter and
never loads the Lua; the syntax check never saw it, because it is a scoping bug, not a
parse error.

Cross-client rather than a Gen 1 regression test: the same mistake in any future client
would be just as silent, and only one of the five had it.
"""
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLIENT_DIR = os.path.join(REPO, "lua", "clients")

CLIENTS = sorted(f for f in os.listdir(CLIENT_DIR) if f.endswith("_client.lua"))

# Only column-0 `local` declarations are chunk-level, i.e. upvalue candidates. An indented
# `local` is block-scoped to some other function and can never be what a reference here binds
# to, so matching those produced a flood of false hits on names like `a`, `key`, `slot`.
_TOPLEVEL_LOCAL_RE = re.compile(r"^local\s+(?:function\s+)?([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)*)")
# Any `local` at any indentation — used to subtract the dispatcher's own locals.
_ANY_LOCAL_RE = re.compile(r"^\s*local\s+(?:function\s+)?([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)*)")


def _names(match):
    return [n.strip() for n in match.group(1).split(",")]


_STR_RE = re.compile(r'"[^"\n]*"|\'[^\'\n]*\'')


def _code_only(line):
    """Drop string literals then the trailing line comment.

    Without this, prose mentions of a helper ("settled in on_frame") count as references
    and every well-commented dispatcher fails.
    """
    return _STR_RE.sub('""', line).split("--", 1)[0]


def _lines(fn):
    with open(os.path.join(CLIENT_DIR, fn), encoding="utf-8") as f:
        return f.read().splitlines()


def _function_body(lines, name):
    """(start, end) line indices of `local function <name>`, end exclusive.

    The body is indented, so the terminating `end` is the first one at column 0.
    """
    start = next((i for i, ln in enumerate(lines)
                  if re.match(rf"^local function {name}\b", ln)), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].rstrip() == "end"), len(lines))
    return start, end


@pytest.mark.parametrize("client", CLIENTS)
def test_dispatcher_locals_are_declared_before_use(client):
    lines = _lines(client)
    span = _function_body(lines, "dispatch_commands")
    if span is None:
        pytest.skip(f"{client} has no top-level `local function dispatch_commands`")
    start, end = span
    body_lines = lines[start + 1:end]
    body = "\n".join(_code_only(ln) for ln in body_lines)

    # Names the dispatcher declares itself resolve to its own locals, not to anything later.
    own = {nm for ln in body_lines
           for m in [_ANY_LOCAL_RE.match(ln)] if m
           for nm in _names(m)}

    late = {}
    for i in range(end, len(lines)):
        m = _TOPLEVEL_LOCAL_RE.match(lines[i])
        if not m:
            continue
        for nm in _names(m):
            if nm not in own:
                late.setdefault(nm, i + 1)

    offenders = sorted(
        (nm, ln) for nm, ln in late.items()
        if re.search(rf"\b{re.escape(nm)}\b", body)
    )
    assert not offenders, (
        f"{client}: dispatch_commands (line {start + 1}) references "
        + ", ".join(f"`{nm}` declared later at line {ln}" for nm, ln in offenders)
        + ". Those bind to nil globals at runtime — move the declarations above the function."
    )


@pytest.mark.parametrize("client", CLIENTS)
def test_dispatcher_only_reads_fields_the_parser_extracts(client):
    """A command field the dispatcher guards on must actually be populated.

    `parse_command_list` builds each command table from an explicit field list. Guard a
    handler on a field that list omits and the handler is simply unreachable — no error,
    no log, it just never runs.

    Gen 1 and Gen 2 both shipped `elseif c.cmd == "play_sound" and c.sound then` while
    neither parser extracted `sound`, so every play_sound the server sent was silently
    dropped by two of the five clients.
    """
    lines = _lines(client)
    span = _function_body(lines, "dispatch_commands")
    if span is None:
        pytest.skip(f"{client} has no top-level `local function dispatch_commands`")
    start, end = span

    pspan = _function_body(lines, "parse_command_list")
    if pspan is None:
        pytest.skip(f"{client} has no top-level `local function parse_command_list`")
    parser = "\n".join(_code_only(ln) for ln in lines[pspan[0] + 1:pspan[1]])

    # Fields the parser puts on each command table: `name = ...` inside the constructor.
    built = set(re.findall(r"(\w+)\s*=", parser))

    # ANY use counts, not just guards. A guard (`and c.sound then`) makes the handler
    # unreachable; a forward (`{stats = c.stats}`) is quieter but was worse in practice —
    # Gen 4 and Gen 5 forwarded an unparsed `stats` into exec_party_mon, whose fallbacks
    # are `stats.level or 5` / `stats.maxHP or 1`, so every restored mon came back at
    # level 5 with 1 max HP.
    used = set()
    for ln in (_code_only(x) for x in lines[start + 1:end]):
        used.update(re.findall(r"\bc\.(\w+)", ln))

    missing = sorted(used - built)
    assert not missing, (
        f"{client}: dispatch_commands reads c.{{{', '.join(missing)}}} but "
        f"parse_command_list never sets {'it' if len(missing) == 1 else 'them'} — "
        "that field is always nil at runtime."
    )
