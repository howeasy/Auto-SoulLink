"""C89 conformance of the shared NDS companion headers (card NDS-9).

The NDS titles build with mwccarm 2.0/sp2p2, a C89-era compiler: no C11
_Static_assert, no C11 _Alignas, no <stdint.h>, and no tolerance for a
declaration that follows a statement or for a declaration in a for-loop head.
Every header under patch/src/nds/common has to survive that. Two independent
checks, because they fail for different reasons:

  (a) TEXTUAL, no compiler, always runs. No C11-only spelling may appear in any
      header in that directory except inside compat.h's own non-__MWERKS__ arm.
      Comments are stripped first (prose that NAMES a construct is not a
      violation) and the text is walked through a preprocessor-region stack, so
      "inside the C11 branch" means literally inside an #else/#elif arm rather
      than "after line N" - which keeps the rule true as the file is edited. The
      header set is discovered from the directory, so a new header is scanned
      without editing this file, and the discovered set is pinned so a rename
      cannot silently shrink coverage.

  (b) COMPILER, host gcc, -std=gnu89 -Wdeclaration-after-statement -Wall -Wextra
      -Werror -D__MWERKS__, skipped with a named reason unless SLINK_REQUIRE_HOST_CC=1.
      gnu89 (not -std=c89 -pedantic-errors) because mwccarm accepts `inline` and
      `long long` as extensions; Gen 4 measured the real pret mwccarm accepting
      `static inline` in these headers. gnu89 still rejects what mwccarm rejects
      here: for-loop-head declarations, and (with -Wdeclaration-after-statement)
      mixed declarations. No diagnostic is excused: a header either compiles clean
      or the test fails.

Transitive coverage is the point of (b): panel/sound include trade_producer,
which includes record_binding, which includes abi - so one shared violation
surfaces in four translation units and is pinned once, by file and line.

Compiler discovery mirrors tests/unit/test_nds_abi_compat.py::_find_gcc so the
two files cannot disagree about what the host compiler is.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "patch/src/nds/common"
COMPAT_NAME = "compat.h"
# Pinned: a header added or renamed without a decision here would otherwise make
# every check below silently cover less than it did.
EXPECTED_HEADERS = {
    "abi.h",
    "compat.h",
    "record_binding.h",
    "trade_producer.h",
    "panel_producer.h",
    "sound_producer.h",
}
# Spellings mwccarm 2.0/sp2p2 cannot parse. compat.h is the only file allowed to
# contain them, and only in its C11 (non-__MWERKS__) arm.
BANNED = ("_Static_assert(", "_Alignas", "<stdint.h>", "<stdbool.h>")

CC_FLAGS = ["-std=gnu89", "-Wdeclaration-after-statement", "-Wall", "-Wextra", "-Werror", "-fsyntax-only"]
DEFINES = ("-D__MWERKS__",)
STDINT_MARKER = "SLINK_C89_SCAN_STDINT_WAS_INCLUDED"


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")
_DIRECTIVE = re.compile(r"^\s*#\s*(ifdef|ifndef|if|elif|else|endif)\b")
_LOCATED = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^\s:]+):(?P<line>\d+):(?P<col>\d+):"
                      r"\s*(?:error|warning):\s*(?P<msg>.*)$")


def _find_gcc():
    """env SLINK_HOST_GCC, PATH, then <repo>/.cache/build-tools (worktree safe)."""
    for cand in (os.environ.get("SLINK_HOST_GCC"), shutil.which("gcc")):
        if cand:
            return cand
    bases = [ROOT]
    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
                         capture_output=True, text=True, timeout=30)
    if git.returncode == 0 and git.stdout.strip():
        bases.append((ROOT / git.stdout.strip()).resolve().parent)
    for base in bases:
        tools = base / ".cache" / "build-tools"
        for pattern in ("*/bin/gcc.exe", "*/*/bin/gcc.exe"):
            for gcc in sorted(tools.glob(pattern)):
                if (gcc.parent.parent / "libexec").is_dir():  # a bare bin/ shim has no cc1
                    return str(gcc)
    return None


def _gcc():
    gcc = _find_gcc()
    if not gcc:
        reason = ("no host C compiler (set SLINK_HOST_GCC, put gcc on PATH, or provide "
                  ".cache/build-tools/*/bin/gcc.exe); NDS C89 compile checks did NOT run")
        if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return gcc


# --------------------------------------------------------------------------- (a) textual

def _strip_comments(text):
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _regions(text):
    """(lineno, line, in_c11_arm) for every line of comment-stripped source.

    in_c11_arm is True when the line sits in the #else/#elif arm of some
    conditional - that is, a branch that is not the first one. That is exactly
    where a toolchain shim is allowed to spell the C11 spelling. A stack is used
    instead of a line-number range so the rule survives edits.
    """
    stack = []  # one entry per open conditional: True while inside its first arm
    for lineno, line in enumerate(text.splitlines(), 1):
        match = _DIRECTIVE.match(line)
        if match:
            kind = match.group(1)
            if kind in ("if", "ifdef", "ifndef"):
                stack.append(True)
            elif kind in ("elif", "else"):
                stack[-1] = False
            elif kind == "endif":
                stack.pop()
        yield lineno, line, any(not first for first in stack)


def _headers():
    found = {h.name for h in COMMON.glob("*.h")}
    assert found == EXPECTED_HEADERS, (
        "patch/src/nds/common header set changed "
        f"(found {sorted(found)}); add the new header to EXPECTED_HEADERS so it is "
        "scanned and compiled too, or explain the removal")
    return sorted(COMMON.glob("*.h"))


def _violations(path):
    out = []
    text = _strip_comments(path.read_text(encoding="utf-8"))
    for lineno, line, in_c11_arm in _regions(text):
        if in_c11_arm:
            continue
        for token in BANNED:
            if token in line:
                out.append(f"{path.name}:{lineno}: {token}")
    return out


def test_the_scanned_header_set_is_the_whole_shared_stack():
    """Coverage is a claim, so it is asserted rather than assumed."""
    assert [h.name for h in _headers()] == sorted(EXPECTED_HEADERS)


def test_no_c11_only_spelling_survives_outside_compat_hs_c11_branch():
    offenders = [f"{v} (C11-only; mwccarm 2.0/sp2p2 rejects it)"
                 for h in _headers() for v in _violations(h)]
    assert not offenders, "use SLINK_STATIC_ASSERT / SLINK_ALIGNAS from compat.h:\n  " + "\n  ".join(offenders)


def test_compat_h_spell_each_c11_token_exactly_once_and_only_in_its_c11_arm():
    text = _strip_comments((COMMON / COMPAT_NAME).read_text(encoding="utf-8"))
    in_arm = {t: [n for n, _line, c11 in _regions(text) if c11 and t in _line] for t in BANNED}
    assert in_arm["<stdbool.h>"] == [], (
        "the shim spells booleans as int; <stdbool.h> must never appear at all")
    assert in_arm["_Alignas"] == [], (
        "no alignment macro: word alignment is proved by offsetof static asserts in trade_producer.h")
    for token in ("_Static_assert(", "<stdint.h>"):
        assert len(in_arm[token]) == 1, (token, in_arm[token])
    defining_line = {
        "_Static_assert(": r"#\s*define\s+SLINK_STATIC_ASSERT\(cond,\s*msg\)\s*_Static_assert\(cond,\s*msg\)",
        "<stdint.h>": r"#\s*include\s*<stdint\.h>",
    }
    lines = text.splitlines()
    for token, pattern in defining_line.items():
        got = lines[in_arm[token][0] - 1]
        assert re.search(pattern, got), f"{token} sits on {got.strip()!r}, not on the line that defines it"


# --------------------------------------------------------------------------- (b) compiler

def test_host_c_compiler_is_discoverable():
    """All-skipped must stay distinguishable from all-passed."""
    done = subprocess.run([_gcc(), "--version"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr


def _poisoned_stdint(tmp):
    """An include dir whose <stdint.h> aborts: a TU that opens it fails loudly."""
    stub = tmp / "nostdint"
    stub.mkdir(exist_ok=True)
    (stub / "stdint.h").write_text(f'#error "{STDINT_MARKER}"\n')
    return stub


def _compile(tmp, header, stub):
    src = tmp / f"c89_{header[:-2]}.c"
    src.write_text(f'#include "{header}"\n', encoding="utf-8")
    cmd = [_gcc(), *CC_FLAGS, *DEFINES, "-I", str(stub), "-I", str(COMMON), str(src)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def _diagnostics(stderr):
    """(file, line, message) for every diagnostic; none is excused."""
    out = []
    for line in stderr.splitlines():
        if "error:" not in line and "warning:" not in line:
            continue
        match = _LOCATED.match(line)
        if not match:
            out.append(("<no location>", 0, line.strip()))
            continue
        name = re.split(r"[\\/]", match.group("file"))[-1]
        out.append((name, int(match.group("line")), match.group("msg").strip()))
    return out


def _compiled(tmp, stub, header):
    """Compile one header; return (raw stderr, diagnostics)."""
    done = _compile(tmp, header, stub)
    assert STDINT_MARKER not in done.stderr, (
        "the __MWERKS__ branch opened <stdint.h>, which mwccarm 2.0/sp2p2 does not have")
    return done.stderr, _diagnostics(done.stderr)


@pytest.mark.parametrize("header", sorted(EXPECTED_HEADERS))
def test_header_compiles_clean_under_the_mwcc_subset(tmp_path, header):
    stderr, diagnostics = _compiled(tmp_path, _poisoned_stdint(tmp_path), header)
    assert not diagnostics, (
        f"{header} has diagnostics under {' '.join(CC_FLAGS)} {' '.join(DEFINES)}:\n  "
        + "\n  ".join(f"{n}:{ln}: {msg}" for n, ln, msg in diagnostics) + "\n" + stderr)


def test_the_scan_catches_a_for_loop_head_declaration_and_a_mixed_declaration(tmp_path):
    """Control: the flags really reject the two constructs mwccarm rejects, so a clean run is evidence."""
    src = tmp_path / "bad.c"
    src.write_text("int f(int n) { int a = n; int b; for (int i = 0; i < n; i++) a += i; a++; int c = a; b = c; return b; }\n",
                   encoding="utf-8")
    done = subprocess.run([_gcc(), *CC_FLAGS, str(src)], capture_output=True, text=True, timeout=60)
    assert done.returncode != 0
    assert "initial declarations" in done.stderr and "mixed declarations" in done.stderr, done.stderr
