"""Cross-client structural invariants, enforced on every generation at once.

Both invariants here are things that were true of four clients and false of one or two, which
is the shape that survives review: nobody diffs five files, so the outlier just persists.

INVARIANT 1 — a frame CALLBACK, never a blocking loop.
`while true do on_frame(); emu.frameadvance() end` never returns, so anything that dofile()s
the client hangs forever. The two-instance duo harness has to do exactly that: it loads the
REAL production client and drives a scenario coroutine alongside it. Gen 1 was converted
during its live bring-up; Gen 2 was still blocking, which meant no Gen 2 E2E test was
possible at all. The pcall matters for the same reason — without it one bad read during a
screen transition kills the client rather than dropping a frame.

INVARIANT 2 — deferred sync commands must carry their payload fields through the queue.
`gen1_rby_client.lua` enqueued `{cmd = "party_mon", key = c.key}` and dropped `c.stats`, so
the executor's `cmd.stats` was ALWAYS nil and the server's mon_stats block never arrived. The
Gen 2 box struct carries no maxHP or stats at all, so this is not a degradation there — it is
the difference between a working withdraw and none.
"""
import glob
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLIENTS = sorted(glob.glob(os.path.join(REPO, "lua", "clients", "*_client.lua")))


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(src: str) -> str:
    """Drop --[[ ]] blocks and -- line comments, so prose about a pattern isn't a match."""
    src = re.sub(r"--\[\[.*?\]\]", "", src, flags=re.S)
    return re.sub(r"--[^\n]*", "", src)


def test_clients_exist():
    """Self-check: a bad glob would make every test below pass vacuously."""
    assert len(CLIENTS) >= 5, f"expected at least 5 clients, found {CLIENTS}"


@pytest.mark.parametrize("path", CLIENTS, ids=lambda p: os.path.basename(p))
def test_client_registers_a_frame_callback(path):
    src = _strip_comments(_src(path))
    assert "event.onframeend" in src, (
        f"{os.path.basename(path)} does not register event.onframeend. Anything that "
        f"dofile()s it — the duo harness does — will hang forever.")


@pytest.mark.parametrize("path", CLIENTS, ids=lambda p: os.path.basename(p))
def test_client_has_no_blocking_main_loop(path):
    """No top-level `while true` driving emu.frameadvance()."""
    src = _strip_comments(_src(path))
    # A blocking driver is a `while true` whose body advances the emulator.
    for m in re.finditer(r"while\s+true\s+do(.*?)\bend\b", src, flags=re.S):
        body = m.group(1)
        if "emu.frameadvance" in body:
            line = src[: m.start()].count("\n") + 1
            pytest.fail(
                f"{os.path.basename(path)}:{line} drives emu.frameadvance() from a "
                f"`while true` loop. Use event.onframeend so the client can be loaded by "
                f"the duo harness.")


@pytest.mark.parametrize("path", CLIENTS, ids=lambda p: os.path.basename(p))
def test_frame_handler_is_wrapped_in_pcall(path):
    """The registered handler must not let one bad read kill the client."""
    src = _strip_comments(_src(path))
    m = re.search(r"event\.onframeend\(\s*([A-Za-z_][A-Za-z0-9_.]*)", src)
    assert m, f"{os.path.basename(path)}: could not find the event.onframeend handler name"
    handler = m.group(1)
    body = re.search(
        rf"function\s+{re.escape(handler)}\s*\((.*?)\n(?:end|local function|function)",
        src, flags=re.S)
    assert body and "pcall" in body.group(1), (
        f"{os.path.basename(path)}: handler {handler}() is registered without a pcall, so a "
        f"single bad read during a screen transition kills the client outright")


# ── Invariant 2: deferred commands keep their payload ────────────────────────

# cmd name -> fields the executor reads off the queued table beyond cmd/key.
PAYLOAD_FIELDS = {"party_mon": ["stats"]}


# ── Invariant 3: the withdraw must be handed its cached stats ────────────────

GB_CLIENTS = [p for p in CLIENTS if "gen1" in os.path.basename(p) or "gen2" in os.path.basename(p)]


@pytest.mark.parametrize("path", GB_CLIENTS, ids=lambda p: os.path.basename(p))
def test_retrieve_is_called_with_cached_stats(path):
    """`M.retrieveBoxMon(key)` with no second argument cannot work.

    A Game Boy box struct drops the party-only tail — Gen 1 loses maxHP and the computed
    stats, Gen 2 loses those AND current HP. retrieveBoxMon refuses outright rather than
    improvise (handing back a mon with zeroed Attack is silent, permanent save corruption
    and the mon is already out of the box). So a one-argument call does not degrade party
    sync, it disables it: every withdraw fails. Gen 2 shipped exactly that.
    """
    src = _strip_comments(_src(path))
    calls = re.findall(r"M\.retrieveBoxMon\(([^)]*)\)", src)
    assert calls, f"{os.path.basename(path)} never calls M.retrieveBoxMon"
    for args in calls:
        assert "," in args, (
            f"{os.path.basename(path)} calls M.retrieveBoxMon({args.strip()}) with no stats "
            f"block — the withdraw will refuse every time")


@pytest.mark.parametrize("path", GB_CLIENTS, ids=lambda p: os.path.basename(p))
def test_deferred_writes_are_gated_on_the_overworld(path):
    """`not in_battle` is not a safe-state gate.

    It is also true in the PC box UI, the party menu and the naming screen, where the open
    UI holds its own copy of the data and writes it back over ours. isInOverworld() adds the
    per-generation "something else owns the game" address — wJoyIgnore/wFontLoaded in Gen 1,
    wScriptRunning in Gen 2 (measured, not chosen by name: wJoypadDisable reads 0 with a
    Crystal menu open, and wTextboxFlags is text-speed configuration).
    """
    src = _strip_comments(_src(path))
    m = re.search(r"if\s+writes_enabled\s+and\s+([^\n]*?)#pending_sync_cmds\s*>\s*0", src)
    assert m, f"{os.path.basename(path)}: could not find the pending_sync_cmds gate"
    guard = m.group(1)
    assert "isInOverworld" in guard, (
        f"{os.path.basename(path)} gates deferred writes on `{guard.strip()}` rather than "
        f"M.isInOverworld() — writes can land while a menu owns the data")


@pytest.mark.parametrize("path", CLIENTS, ids=lambda p: os.path.basename(p))
def test_deferred_enqueue_carries_payload_fields(path):
    """A queued command that drops a field silently disables whatever needed it."""
    src = _strip_comments(_src(path))
    problems = []
    for cmd_name, fields in PAYLOAD_FIELDS.items():
        # Find table constructors that enqueue this command.
        for m in re.finditer(rf"\{{\s*cmd\s*=\s*[\"']{cmd_name}[\"'](.*?)\}}", src, flags=re.S):
            literal = m.group(1)
            line = src[: m.start()].count("\n") + 1
            for field in fields:
                if f"{field} =" not in literal and f"{field}=" not in literal:
                    problems.append(
                        f"  {os.path.basename(path)}:{line} enqueues {cmd_name!r} without "
                        f"{field!r}; the executor reads cmd.{field} and will always see nil")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", GB_CLIENTS, ids=lambda p: os.path.basename(p))
def test_deferred_sync_executor_is_fault_contained(path):
    """A raise in the deferred executor does not lose one command — it wedges the client.

    The executor writes real party/box/SRAM memory. Unwrapped, an error escapes
    `on_frame`, so the `table.remove(pending_sync_cmds, 1)` at the bottom never runs,
    the same command re-raises on the next frame, and every step after it —
    trainer_battle_start, the `safe` event, send_tick, the F-keys, the HUD — stops
    for the rest of the session. `on_frame_safe`'s pcall keeps the process alive,
    which is precisely what makes it silent: the client stays connected and goes
    quiet. Gen 1 shipped this way; Gen 2 did not.
    """
    src = _strip_comments(_src(path))
    m = re.search(r"if\s+writes_enabled\s+and[^\n]*#pending_sync_cmds\s*>\s*0\s*then(.*?)"
                  r"if\s+handled\s+then\s+table\.remove", src, flags=re.S)
    assert m, f"{os.path.basename(path)}: could not find the deferred executor block"
    assert "pcall(" in m.group(1), (
        f"{os.path.basename(path)} runs the deferred sync executor without pcall — one "
        f"raise wedges the command queue and silences the client for the session")


@pytest.mark.parametrize("path", GB_CLIENTS, ids=lambda p: os.path.basename(p))
def test_command_dispatcher_is_fault_contained(path):
    """One malformed command must not abort the rest of the batch, or the frame.

    `replace_rival_team` runs hexToBytes over a server-supplied string before writing
    it into wEnemyMons, so the payload is not trusted input.
    """
    src = _strip_comments(_src(path))
    m = re.search(r"local function dispatch_commands\(cmds\)(.*?)\nend\n", src, flags=re.S)
    assert m, f"{os.path.basename(path)}: could not find dispatch_commands"
    assert "pcall(" in m.group(1), (
        f"{os.path.basename(path)} dispatches server commands without pcall")


def test_gen1_nacks_a_failed_sync_command_before_dropping_it():
    """Silence is worse than failure: a dropped command the server still believes is
    in flight desyncs the pair permanently. Gen 2 only logs-and-drops here."""
    src = _strip_comments(_src(
        [p for p in GB_CLIENTS if "gen1" in os.path.basename(p)][0]))
    m = re.search(r"if not exec_ok then(.*?)\n        end", src, flags=re.S)
    assert m, "gen1 client: no failure branch after the executor pcall"
    body = m.group(1)
    for evt in ("sync_retrieve_failed", "memorialize_failed"):
        assert evt in body, (
            f"the executor's error path does not emit {evt}; the server would keep the "
            f"command in flight forever")
