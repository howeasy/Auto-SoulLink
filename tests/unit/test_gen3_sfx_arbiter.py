"""lua/sfx_arbiter.lua — one sound cue per frame, highest priority wins.

The arbiter is a pure module (no BizHawk globals), so lupa loads it directly. The route choice
(native PlaySE vs the Lua m4a poke) lives in the client's flush sink; it is mirrored here as a
tiny stub, plus source assertions that the client actually wires the real thing up that way.
"""

import re
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

REPO = Path(__file__).resolve().parents[2]
ARBITER = (REPO / "lua" / "sfx_arbiter.lua").as_posix()
CLIENT_SRC = (REPO / "lua" / "clients" / "gen3_frlge_client.lua").read_text(encoding="utf-8")

# The client's ranks, as bound after M.applyProfile (vanilla/CFRU ids; the RR profile overrides
# them, which is why the module itself never hard-codes numbers).
GAME_OVER, BOO, LINKED_KO = 26, 22, 16
RANKS = {GAME_OVER: 3, BOO: 2, LINKED_KO: 1}


class Frame:
    """An arbiter plus a recording sink."""

    def __init__(self, native=False):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        arb = self.lua.eval(f'dofile("{ARBITER}")').new(self.lua.table_from(RANKS))
        self.request = arb.request
        self.flush = arb.flush
        self.native = native
        self.played: list[tuple[str, int]] = []

    def run(self):
        """Flush through the client's route rule: native only for a cue the caller marked native_ok
        (the server's generic play_sound) AND when patched and out of battle."""
        self.flush(lambda s, native_ok: self.played.append(
            ("MB.play_se" if (native_ok and self.native) else "M.playSE", int(s))))
        return self.played


def test_terminal_batch_plays_only_game_over_direct_route():
    f = Frame()
    # [force_faint, play_sound 26, memorialize, game_over] → K, 26, G requested in that order.
    f.request(LINKED_KO)
    f.request(GAME_OVER)
    f.request(GAME_OVER)
    assert f.run() == [("M.playSE", GAME_OVER)]


def test_terminal_batch_plays_only_game_over_native_route():
    f = Frame(native=True)
    # [force_faint, play_sound 26, memorialize, game_over]: the server's 26 is native_ok, the
    # client cues are not. GAME_OVER wins and, being a client cue, takes the Lua poke even with
    # the patch present: a native sound queued behind the same-frame native memorialize would be
    # pumped next frame before the memorialize poll and overwrite its ack (Codex cx-e8acc8bc).
    f.request(LINKED_KO)
    f.request(GAME_OVER, True)   # the server's play_sound 26 (same id as SE_GAME_OVER by default)
    f.request(GAME_OVER)
    assert f.run() == [("M.playSE", GAME_OVER)]


def test_generic_server_sound_alone_takes_the_native_route_when_allowed():
    f = Frame(native=True)
    f.request(5, True)
    assert f.run() == [("MB.play_se", 5)]


def test_client_cue_never_takes_the_native_route():
    f = Frame(native=True)
    f.request(LINKED_KO)
    assert f.run() == [("M.playSE", LINKED_KO)]


def test_winner_keeps_its_own_route_flag_not_the_losers():
    f = Frame(native=True)
    f.request(5, True)          # generic server sound, native-capable
    f.request(LINKED_KO)        # outranks it; must NOT inherit native_ok
    assert f.run() == [("M.playSE", LINKED_KO)]


def test_only_the_server_play_sound_site_is_native_ok():
    # Every other request() in the client carries no flag.
    flagged = re.findall(r"M\.sfx\.request\([^)]*,\s*true\)", CLIENT_SRC)
    assert flagged == ["M.sfx.request(c.sound, true)"]


# ── mailbox ordering (Codex cx-c26a5baa finding 1) ──────────────────────────────────────────
# The real lua/mailbox.lua over a byte-array `memory` stub. The companion hook is simulated by
# hand: it consumes the opcode and writes the ack (patch/src/handlers.c:559-564 shape).

MAILBOX = (REPO / "lua" / "mailbox.lua").as_posix()
LUA_DIR = (REPO / "lua").as_posix()


class Mailbox:
    """mailbox.lua + memory stub + the client's flush sink (patched, out of battle)."""

    def __init__(self):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(
            f'package.path = "{LUA_DIR}/?.lua;" .. package.path\n'
            "local mem = {}\n"
            "memory = {\n"
            "  read_u8 = function(a) return mem[a] or 0 end,\n"
            "  write_u8 = function(a, v) mem[a] = v % 256 end,\n"
            "  read_u16_le = function(a) return (mem[a] or 0) + 256 * (mem[a+1] or 0) end,\n"
            "  write_u16_le = function(a, v) mem[a] = v % 256; mem[a+1] = (v // 256) % 256 end,\n"
            "  read_u32_le = function(a) return (mem[a] or 0) + 256 * (mem[a+1] or 0)"
            " + 65536 * (mem[a+2] or 0) + 16777216 * (mem[a+3] or 0) end,\n"
            "  write_u32_le = function(a, v) for i = 0, 3 do mem[a+i] = (v >> (8*i)) % 256 end end,\n"
            "}\n"
            "console = { log = function() end }\n"
            f'MB = dofile("{MAILBOX}")\n'
            'ARB = dofile("' + ARBITER + '").new({})\n'
            "played = {}\n"
            "function flush(native_ok_ctx)\n"
            "  ARB.flush(function(sound, native_ok)\n"
            "    if native_ok and not MB.busy() then MB.play_se(sound); played[#played+1] = 'MB'\n"
            "    else played[#played+1] = 'LUA' end\n"
            "  end)\n"
            "end\n"
            # the hook: consume the opcode, ack the seq with ST_OK (handlers.c shape)
            "function hook_consume()\n"
            "  local base = MB.BASE\n"
            "  local opc = memory.read_u16_le(base + 6)\n"                      # O_OPCODE
            "  if opc == 0 then return false end\n"
            "  memory.write_u16_le(base + 10, MB.ST_OK)\n"                      # O_STATUS
            "  memory.write_u16_le(base + 12, memory.read_u16_le(base + 8))\n"  # O_ACKSEQ = O_SEQ
            "  memory.write_u16_le(base + 6, 0)\n"
            "  return true\n"
            "end\n"
        )
        # sanity: the offsets above must be mailbox.lua's own (one multi-assignment line)
        m = re.search(r"local (O_SIG[^=]*)=\s*([0-9, ]+)", MAILBOX_SRC)
        assert m, "mailbox.lua offset line not found"
        offs = dict(zip([n.strip() for n in m.group(1).split(",")],
                        [int(v) for v in m.group(2).split(",")], strict=True))
        assert (offs["O_OPCODE"], offs["O_SEQ"], offs["O_STATUS"], offs["O_ACKSEQ"]) == (6, 8, 10, 12)

    def g(self, expr):
        return self.lua.eval(expr)


MAILBOX_SRC = (REPO / "lua" / "mailbox.lua").read_text(encoding="utf-8", errors="replace")


def test_deferred_server_sound_never_queues_behind_a_native_op():
    """Frame N: response [play_sound, memorialize]. The client posts the native memorialize during
    on_frame; the sound flushes at frame end. Frame N+1: MB.pump() runs BEFORE the memorialize
    poll. The memorialize receipt must survive (pre-arbiter the sound posted FIRST, so it did)."""
    m = Mailbox()
    m.lua.execute("seq_mem = MB.send(MB.OP_MEMORIALIZE or 26, {1, 2})")   # the native op
    assert m.g("MB.busy()") is True
    m.lua.execute("ARB.request(7, true)")                                   # server play_sound
    m.lua.execute("flush()")
    assert list(m.g("played").values()) == ["LUA"]                         # not queued behind it
    assert m.g("hook_consume()") is True                                    # patch completes it
    m.lua.execute("MB.pump()")                                              # frame N+1, before poll
    assert m.g("MB.poll(seq_mem)")[0] == m.g("MB.ST_OK")                    # receipt intact
    assert m.g("MB.busy()") is False


def test_control_a_sound_queued_behind_the_op_does_lose_the_receipt():
    """The failure the rule prevents (a76103a's flush did this): queue the sound behind the
    outstanding op; the pump next frame posts it before the poll and the op's ack is gone."""
    m = Mailbox()
    m.lua.execute("seq_mem = MB.send(MB.OP_MEMORIALIZE or 26, {1, 2}); MB.play_se(7)")  # queued
    assert m.g("hook_consume()") is True                                    # memorialize completes
    m.lua.execute("MB.pump()")                                              # posts the sound...
    assert m.g("MB.poll(seq_mem)") is None                                  # ...and the receipt is lost


def test_server_sound_takes_native_route_when_mailbox_is_idle():
    m = Mailbox()
    m.lua.execute("ARB.request(7, true)")
    m.lua.execute("flush()")
    assert list(m.g("played").values()) == ["MB"]
    assert m.g("MB.busy()") is True                                         # our own opcode, pending
    assert m.g("hook_consume()") is True
    assert m.g("MB.busy()") is False


def test_queued_outbox_counts_as_busy():
    m = Mailbox()
    m.lua.execute("s1 = MB.send(3, {}); s2 = MB.send(4, {})")               # second one queues
    assert m.g("hook_consume()") is True                                    # slot free, outbox has s2
    assert m.g("MB.busy()") is True
    m.lua.execute("ARB.request(7, true); flush()")
    assert list(m.g("played").values()) == ["LUA"]


def test_linked_ko_outranks_generic_play_sound():
    f = Frame()
    f.request(LINKED_KO)
    f.request(95)  # generic server play_sound, rank 0
    assert f.run() == [("M.playSE", LINKED_KO)]


def test_generic_play_sound_alone_still_plays():
    f = Frame()
    f.request(95)
    assert f.run() == [("M.playSE", 95)]


def test_whiteout_outranks_ko_but_loses_to_game_over():
    f = Frame()
    f.request(LINKED_KO)
    f.request(BOO)
    assert f.run() == [("M.playSE", BOO)]

    g = Frame()
    g.request(BOO)
    g.request(GAME_OVER)
    assert g.run() == [("M.playSE", GAME_OVER)]


def test_duplicate_same_frame_ko_coalesces():
    f = Frame()
    for _ in range(4):
        f.request(LINKED_KO)
    assert f.run() == [("M.playSE", LINKED_KO)]


def test_empty_frame_flushes_nothing():
    f = Frame()
    assert f.run() == []


def test_flush_clears_so_a_cue_never_repeats_next_frame():
    f = Frame()
    f.request(GAME_OVER)
    assert f.run() == [("M.playSE", GAME_OVER)]
    f.played.clear()
    assert f.run() == []
    f.request(LINKED_KO)
    f.played.clear()
    assert f.run() == [("M.playSE", LINKED_KO)]


def test_nil_request_is_ignored():
    f = Frame()
    f.request(None)
    assert f.run() == []


# ── client wiring (source assertions) ────────────────────────────────────────


def test_client_has_no_direct_playse_calls_left():
    assert "M.playSE(M.SE_" not in CLIENT_SRC
    # The only surviving M.playSE / MB.play_se call is the flush sink.
    assert CLIENT_SRC.count("M.playSE(") == 1
    assert CLIENT_SRC.count("MB.play_se(") == 1


def test_client_flush_uses_the_documented_route_rule():
    assert re.search(
        r"M\.sfx\.flush.*\n.*native_ok and native_sfx_enabled and patch_present\(\) and not"
        r" M\.isInBattle\(\)\n\s*and not MB\.busy\(\) then MB\.play_se\(sound\)\n\s*else"
        r" M\.playSE\(sound\) end",
        CLIENT_SRC,
    )


def test_deferred_ko_cue_is_suppressed_after_game_over():
    # The faint write still happens; only the cue is gated.
    assert "if not game_over_flag then M.sfx.request(M.SE_LINKED_KO) end" in CLIENT_SRC


def test_client_priority_table_uses_profile_constants_not_literals():
    table = CLIENT_SRC.split("require(\"sfx_arbiter\").new({", 1)[1].split("})", 1)[0]
    assert "[M.SE_GAME_OVER] = 3" in table
    assert "[M.SE_BOO]       = 2" in table
    assert "[M.SE_LINKED_KO] = 1" in table
