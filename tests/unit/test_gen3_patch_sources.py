"""C5-11b source-level gates: the patch handler must COMPILE, and the session counter must work.

Two independent checks, both of which caught real defects on this card:

1. `lua/gen3/run.lua`'s session counter. It is extracted from the shipped file by the markers
   around it (not re-implemented here), so the test exercises the real code, and driven through
   an injected open/remove/rename over a fake filesystem with Windows or POSIX rename semantics --
   which is why the helper takes them. Concurrency is tested by running two Lua runtimes (two
   emulator processes) over ONE filesystem, one of them paused on a thread at a named point: that
   is how Codex executed the C5-11c lock race, and a sequential "interleaving" cannot show it. The
   path assertion is C5-11b's regression: the counter used to live under `patch/build/`, which a
   player's release does not have.

2. `patch/src/handlers.c` must pass a syntax-only compile. C5-11a's `stage_enemy_party` was
   defined INSIDE `slink_hook` (C has no nested functions) and nothing in the unit suite noticed,
   because there was no compiler on the host -- the toolchain turned out to be vendored in the
   ROOT checkout (`patch/vendor/armgcc/...`), which a worktree does not carry, so this test
   SKIPS there. A skip is not a pass: run it from the root checkout (or set $SLINK_ARMGCC) before
   trusting a patch-source change.
"""
from __future__ import annotations

import glob
import os
import pathlib
import shutil
import subprocess
import threading

import lupa
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RUN_LUA = REPO / "lua" / "gen3" / "run.lua"
HANDLERS_C = REPO / "patch" / "src" / "handlers.c"


# ── 1. the session counter (lua/gen3/run.lua) ───────────────────────────────────────────────

ENOENT, EACCES, EEXIST = 2, 13, 17
ROOT = "/install"
BATON, BORN = f"{ROOT}/slink_gen3_session.baton", f"{ROOT}/slink_gen3_session.born"
# the C5-11b/c file name, seeded alongside the baton by the item-2 falsifiers so they model "an
# existing counter" for the pre-C5-11d helper too (that is how their red was shown)
LEGACY = f"{ROOT}/slink_gen3_session.counter"


def _counter_chunk() -> str:
    """The counter block from the shipped file, delimited by its own markers. The block is kept
    self-contained on purpose so this extraction is mechanical, and `return next_session_counter`
    makes it callable from the test."""
    src = RUN_LUA.read_text(encoding="utf-8")
    start = src.index("-- >>> session counter")
    start = src.index("\n", start) + 1
    end = src.index("-- <<< session counter <<<")
    return src[start:end] + "\nreturn next_session_counter\n"


class _Inode:
    """A file's content plus its faults. Faults live on the FILE, so they follow it through a
    rename -- the baton is read under the name its holder gave it."""

    def __init__(self, text="", read_open_failures=0):
        self.text, self.read_open_failures = text, read_open_failures


class _FS:
    """One install directory shared by every Lua runtime in a test (= every emulator process on
    the install). rename() follows the OS: a missing source is ENOENT on both, an existing
    destination is REPLACED on POSIX and REFUSED on Windows."""

    def __init__(self, windows=False, files=None):
        self.windows = windows
        self.files = {k: _Inode(v) if isinstance(v, str) else v for k, v in (files or {}).items()}
        self.fail: set[str] = set()          # "write" / "flush" / "close": every handle reports it
        self.deny: set[str] = set()          # paths whose open AND rename fail with EACCES
        self.opened: list[str] = []

    def text(self, path):
        return self.files[path].text if path in self.files else None

    def api(self, on_read=None, on_open_miss=None):
        """(open, remove, rename) as one process sees them; the hooks let a test pause it."""
        fs = self

        class Handle:
            def __init__(self, inode, mode):
                self.inode, self.mode, self.buf = inode, mode, ""

            def read(self, _how):
                if on_read:
                    on_read(self.inode.text)
                return self.inode.text

            def write(self, text):
                if "write" in fs.fail:
                    return None
                self.buf += str(text)
                return self

            def flush(self):
                return None if "flush" in fs.fail else True

            def close(self):
                if "close" in fs.fail:
                    return None
                if self.mode.startswith("a"):
                    self.inode.text += self.buf      # one O_APPEND write at the then-current end
                elif self.mode.startswith("w"):
                    self.inode.text = self.buf
                return True

        def open_(path, mode):
            path, mode = str(path), str(mode)
            fs.opened.append(path)
            if path in fs.deny:
                return None, f"{path}: Permission denied", EACCES
            inode = fs.files.get(path)
            if mode.startswith("r"):
                if inode is None:
                    if on_open_miss:
                        on_open_miss(path)
                    return None, f"{path}: No such file or directory", ENOENT
                if inode.read_open_failures:
                    inode.read_open_failures -= 1
                    return None, f"{path}: Permission denied", EACCES
                return Handle(inode, mode)
            if inode is None or mode.startswith("w"):
                inode = fs.files[path] = _Inode()    # "w" truncates at open, like fopen
            return Handle(inode, mode)

        def remove(path):
            return fs.files.pop(str(path), None) is not None or (None, "No such file", ENOENT)

        def rename(src, dst):
            src, dst = str(src), str(dst)
            if src in fs.deny or dst in fs.deny:
                return None, f"{src}: Permission denied", EACCES
            if src not in fs.files:
                return None, f"{src}: No such file or directory", ENOENT
            if fs.windows and dst in fs.files:
                return None, f"{dst}: File exists", EEXIST
            fs.files[dst] = fs.files.pop(src)
            return True

        return open_, remove, rename


def _counter():
    """A fresh Lua runtime holding the extracted helper: one runtime = one emulator process."""
    return lupa.LuaRuntime(unpack_returned_tuples=True).execute(_counter_chunk())


def _no_spin():
    return None


def _allocate(fs, fn=None, **hooks):
    open_, remove, rename = fs.api(**hooks)
    return (fn or _counter())(ROOT, open_, remove, _no_spin, rename, fs.windows)


OS = pytest.mark.parametrize("windows", [True, False], ids=["windows", "posix"])


@OS
def test_the_counter_increments_and_writes_at_the_install_root(windows):
    fs = _FS(windows)
    assert [_allocate(fs) for _ in range(3)] == [1, 2, 3]
    assert fs.text(BATON) == "3"
    assert set(fs.files) == {BATON, BORN}, "a clean allocation leaves only the baton and the record"
    assert all(p.startswith(f"{ROOT}/") for p in fs.opened)
    assert not any("patch" in p or "build" in p for p in fs.opened), (
        "the counter must not live under patch/build/: a player's release has no such directory, "
        "so run.lua would fail closed on every real install")


def _run_paused(fs, pause_when, then):
    """Codex REV3's executed interleaving, generalised: process A runs in its own Lua runtime on a
    thread and is PAUSED at the point `pause_when` names; `then()` runs to completion meanwhile
    (process B, on another runtime over the same filesystem); A resumes. Returns (A, then())."""
    paused, resume, out = threading.Event(), threading.Event(), {}

    def pause():
        if not paused.is_set():
            paused.set()
            assert resume.wait(10), "process A was never resumed"

    def run_a():
        try:
            out["a"] = _allocate(fs, **pause_when(pause))
        except BaseException as exc:          # surfaced below, never swallowed
            out["error"] = exc

    thread = threading.Thread(target=run_a, daemon=True)
    thread.start()
    assert paused.wait(10), f"process A never reached its pause point ({out.get('error')!r})"
    b = then()
    resume.set()
    thread.join(10)
    assert not thread.is_alive() and "error" not in out, out.get("error")
    return out["a"], b


@OS
def test_c511d_codex_interleaving_two_processes_never_get_the_same_value(windows):
    """Codex REV3 BLOCKER, the executed interleaving: A takes the lock, reads counter 9 and
    PAUSES; B runs a whole allocation (on the old helper: overwrote A's lock, read 9, wrote 10,
    returned 10); A resumes. The old helper returned 10 to BOTH. Whatever B gets, it must not be
    A's value -- here the baton is in A's hands, so B waits and fails closed."""
    fs = _FS(windows, {BATON: "9", BORN: "first-run\n", LEGACY: "9"})

    def at_nine(pause):
        return {"on_read": lambda text: pause() if text == "9" else None}

    a, b = _run_paused(fs, at_nine, lambda: _allocate(fs))
    got = [v for v in (a, b) if v is not None]
    assert len(got) == len(set(got)), f"both processes were handed {got[0]}"
    assert a == 10 and b is None
    assert fs.text(BATON) == "10"


@OS
def test_c511d_the_first_ever_race_creates_exactly_one_baton(windows):
    """The Linux argument, executed: A sees BOTH the baton and the birth record absent and pauses
    before it claims the birth; B runs a whole first allocation (wins the birth, creates the baton,
    takes 1); A resumes. On POSIX rename would replace, so only the append-log's first line keeps
    A from creating a SECOND baton at 0 (and taking 1 again); on Windows the refusing rename does."""
    fs = _FS(windows)

    def at_birth_check(pause):
        return {"on_open_miss": lambda path: pause() if path == BORN else None}

    a, b = _run_paused(fs, at_birth_check, lambda: _allocate(fs))
    assert (a, b) == (2, 1)
    assert fs.text(BATON) == "2"


# ── MAJOR 2: nothing but a positively established first creation may initialise ──────────────

def test_c511d_an_existing_counter_whose_read_open_fails_fails_closed():
    """Codex REV3 MAJOR 2, first half: the old helper ignored WHY open("r") failed and counted
    from 0, so a transient EACCES on an existing counter handed out 1 again."""
    fs = _FS(False, {BATON: _Inode("7", 1), LEGACY: _Inode("7", 1), BORN: "x\n"})
    assert _allocate(fs) is None
    assert fs.text(BATON) == "7", "the baton is put back untouched"
    assert _allocate(fs) == 8, "and the next allocation continues from it"


def test_c511d_an_existing_empty_counter_fails_closed():
    """Codex REV3 MAJOR 2, second half: the old helper took an existing EMPTY file for a first
    creation and handed out 1."""
    fs = _FS(False, {BATON: "", LEGACY: "", BORN: "x\n"})
    assert _allocate(fs) is None
    assert fs.text(BATON) == "", "left as found, never rewritten to a restart value"


def test_c511d_a_missing_baton_after_the_birth_is_held_never_recreated():
    """After the birth record exists a missing baton means another process holds it (or one died
    holding it): wait, then fail closed. Recreating it would be the reset."""
    fs = _FS(False, {BORN: "x\n"})
    assert _allocate(fs) is None
    assert BATON not in fs.files


@pytest.mark.parametrize("denied", [BORN, BATON], ids=["birth_record", "baton"])
def test_c511d_a_non_enoent_failure_never_initialises(denied):
    """Only ENOENT on both files is a first creation: an EACCES on either one is not evidence that
    nothing exists, so nothing is created."""
    fs = _FS(False)
    fs.deny.add(denied)
    assert _allocate(fs) is None
    assert BATON not in fs.files


@pytest.mark.parametrize("bad", ["not-a-number", "1.5", "-3", " 7", str(2 ** 32 - 1), str(2 ** 32)])
def test_a_malformed_counter_fails_closed_and_is_left_as_found(bad):
    """C5-11c MAJOR 5, kept: a corrupt value is a reason to refuse, never a reset."""
    fs = _FS(False, {BATON: bad, BORN: "x\n"})
    assert _allocate(fs) is None, bad
    assert fs.text(BATON) == bad


@pytest.mark.parametrize("fault", ["write", "flush", "close"])
def test_a_failed_publish_fails_closed_and_keeps_the_counter(fault):
    """A write, flush or close that does not report success fails closed; the taken baton was
    never truncated, so it is put back with its old value and the next allocation continues."""
    fs = _FS(False, {BATON: "5", BORN: "x\n"})
    fs.fail.add(fault)
    assert _allocate(fs) is None
    fs.fail.clear()
    assert fs.text(BATON) == "5"
    assert _allocate(fs) == 6


def test_an_unwritable_install_root_fails_closed():
    """No counter -> no seed -> the client mints no identity and declares no capability."""
    fs = _FS(False)
    fs.fail.update({"write", "close"})
    assert _allocate(fs) is None
    assert BATON not in fs.files


def test_run_lua_still_uses_the_counter_and_fails_closed_without_a_seed():
    """The call site, not just the helper: the seed must be built from the counter, and it must
    be absent when the counter is nil."""
    src = RUN_LUA.read_text(encoding="utf-8")
    assert "local session_counter = next_session_counter(ROOT)" in src
    assert "if session_counter then" in src
    assert "local battle_nonce_seed = nil" in src


# ── 2. the patch handler must compile ───────────────────────────────────────────────────────

def _find_armgcc() -> str | None:
    """The same search patch/tools/build.py uses: $SLINK_ARMGCC, then the vendored toolchain
    (root checkout only), then PATH."""
    env = os.environ.get("SLINK_ARMGCC")   # a bin DIR, as patch/tools/build.py:_toolchain_dir reads it
    if env:
        for name in ("arm-none-eabi-gcc.exe", "arm-none-eabi-gcc"):
            if (pathlib.Path(env) / name).exists():
                return str(pathlib.Path(env) / name)
    for pattern in ("armgcc/*/bin/arm-none-eabi-gcc.exe", "armgcc/*/bin/arm-none-eabi-gcc"):
        hits = sorted(glob.glob(str(REPO / "patch" / "vendor" / pattern)))
        if hits:
            return hits[-1]
    return shutil.which("arm-none-eabi-gcc")


def test_the_patch_handler_passes_a_syntax_only_compile():
    """C5-11b: `stage_enemy_party` was defined inside `slink_hook` and only the compiler caught
    it. Flags mirror patch/tools/build.py's CFLAGS; -Wall with zero warnings is the baseline
    HEAD's handlers.c also meets."""
    compiler = _find_armgcc()
    if not compiler:
        pytest.skip("arm-none-eabi-gcc not found (vendored under patch/vendor in the ROOT "
                    "checkout, or set $SLINK_ARMGCC): the patch sources are UNCOMPILED here")
    proc = subprocess.run(
        [compiler, "-mcpu=arm7tdmi", "-mthumb", "-ffreestanding", "-Os", "-fsyntax-only", "-Wall",
         "src/handlers.c"],
        cwd=str(REPO / "patch"), capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "warning:" not in (proc.stderr or ""), proc.stderr


def test_only_slink_hook_lands_in_the_entry_section():
    """C5-11c BLOCKER 1: `.text.entry` is KEEP()ed at CODE_BASE by patch/src/slink.ld:12 and
    build.py verifies `slink_hook == CODE_BASE`, so the section may contain slink_hook and nothing
    else. The `__attribute__((section(".text.entry")))` had been left stranded above
    `stage_enemy_party` when the helper moved to file scope, which would have put the helper at
    CODE_BASE (or failed the build). Compiles to ASSEMBLY (-S) and reads the section, because a
    syntax-only pass cannot see placement."""
    compiler = _find_armgcc()
    if not compiler:
        pytest.skip("arm-none-eabi-gcc not found (vendored under patch/vendor in the ROOT "
                    "checkout, or set $SLINK_ARMGCC): section placement is UNCHECKED here")
    proc = subprocess.run(
        [compiler, "-mcpu=arm7tdmi", "-mthumb", "-ffreestanding", "-Os", "-S", "-o", "-",
         "src/handlers.c"],
        cwd=str(REPO / "patch"), capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    asm = proc.stdout
    sections = [chunk for chunk in asm.split("\t.section\t") if chunk]
    entry = [c for c in sections if c.startswith('.text.entry')]
    assert len(entry) == 1, f"expected exactly one .text.entry section, got {len(entry)}"
    # Functions in that section, by GCC's own `.type NAME, %function` lines: the section also
    # carries read-only data objects (sSoulLinkLabel/Desc), which do not affect the entry point.
    funcs = set()
    for line in entry[0].splitlines():
        line = line.strip()
        if line.startswith(".type") and line.endswith("%function"):
            funcs.add(line.split()[1].rstrip(","))
    assert funcs == {"slink_hook"}, (
        f".text.entry must hold slink_hook alone (build.py verifies it lands at CODE_BASE); "
        f"found {sorted(funcs)}")


def test_the_window_reads_comm0_as_a_byte():
    """C5-11c MAJOR 4: the contract is `gBattleCommunication[0] < 15`. Reading 16 bits pulls
    comm[1] (the per-battler request index) into the comparison, so a battle whose comm[1] is
    nonzero would be refused even with a valid comm0. The width is the whole finding, so this is a
    source assertion: the runtime falsifier (nonzero comm1, valid comm0 -> admitted) needs the
    patch on a cartridge."""
    src = HANDLERS_C.read_text(encoding="utf-8")
    rival = src[src.index("case OP_RIVAL_SWAP:"):]
    rival = rival[:rival.index("case OP_SET_ENEMY_PARTY:")]
    assert "R8(RV_BATTLE_COMM) >= RV_MULTIUSE_SETUP_DONE" in rival
    assert "R16(RV_BATTLE_COMM)" not in rival and "R32(RV_BATTLE_COMM)" not in rival


def test_the_rival_opcode_is_file_scope_in_the_handler():
    """The specific defect this test exists for: no function may be defined inside slink_hook."""
    src = HANDLERS_C.read_text(encoding="utf-8")
    hook_start = src.index("void slink_hook(void)")
    hook_end = src.index("\nstatic ", hook_start + 1) if "\nstatic " in src[hook_start:] else len(src)
    body = src[hook_start:hook_start + hook_end]
    assert "static void stage_enemy_party" not in body, "stage_enemy_party must be at file scope"
    assert src.index("static void stage_enemy_party") < hook_start


@OS
def test_a_slow_holder_is_waited_out_not_failed_closed(windows):
    """T5 native_trade_firered 2026-09-27 (OMP cx-6616a9f2): two EmuHawks launch 0.1 s apart on
    one install; the holder took longer than the old 100 x 5 ms bound, so B got nil, never bound a
    trade session and silently never advertised trade. A holder that publishes after 150 spins
    (0.75 s at the default 5 ms) must still hand B the next value."""
    fs = _FS(windows, {BORN: "first-run\n"})          # baton absent = held by A right now
    spins = []

    def slow_holder():
        spins.append(1)
        if len(spins) == 150:
            fs.files[BATON] = _Inode("41")            # A publishes its n+1

    open_, remove, rename = fs.api()
    assert _counter()(ROOT, open_, remove, slow_holder, rename, fs.windows) == 42


@OS
def test_first_birth_waits_for_a_slow_publisher(windows):
    """The permanent birth record can appear before the new baton. A second emulator that
    starts during that gap must survive more than the old five-second/1000-spin bound."""
    fs = _FS(windows, {BORN: "first-run\n"})
    spins = []

    def publish_after_slow_first_start():
        spins.append(1)
        if len(spins) == 1500:
            fs.files[BATON] = _Inode("1")

    open_, remove, rename = fs.api()
    assert _counter()(ROOT, open_, remove, publish_after_slow_first_start,
                      rename, fs.windows) == 2
    assert fs.text(BATON) == "2"


def test_birth_winner_retries_a_transient_baton_publish_failure():
    """Only the recorded birth winner may retry publishing the initial generation."""
    fs = _FS(True)
    open_, remove, rename = fs.api()
    failed = []

    def transient_rename(src, dst):
        if dst == BATON and ".new." in src and not failed:
            failed.append(True)
            return None, "temporarily busy", EACCES
        return rename(src, dst)

    assert _counter()(ROOT, open_, remove, _no_spin, transient_rename, True) == 1
    assert failed and fs.text(BATON) == "1"
    assert _allocate(fs) == 2


def test_first_birth_winner_publishes_after_the_loser_waits_past_old_bound():
    """Two live Lua runtimes: A owns .born but pauses before .baton, then B waits >1000 spins."""
    fs = _FS(True)
    born, resume, finished = threading.Event(), threading.Event(), threading.Event()
    out = {}
    open_a, remove_a, rename_a_raw = fs.api()

    def rename_a(src, dst):
        result = rename_a_raw(src, dst)
        if dst == BORN and result is True:
            born.set()
            assert resume.wait(5)
        return result

    def run_a():
        try:
            out["a"] = _counter()(ROOT, open_a, remove_a, _no_spin, rename_a, True)
        finally:
            finished.set()

    thread = threading.Thread(target=run_a, daemon=True)
    thread.start()
    assert born.wait(5)
    spins = []

    def wait_then_release_winner():
        spins.append(1)
        if len(spins) == 1500:
            resume.set()
            assert finished.wait(5)

    open_b, remove_b, rename_b = fs.api()
    b = _counter()(ROOT, open_b, remove_b, wait_then_release_winner, rename_b, True)
    thread.join(5)
    assert not thread.is_alive()
    assert (out["a"], b) == (1, 2)
    assert fs.text(BATON) == "2"
