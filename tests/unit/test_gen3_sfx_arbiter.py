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
        r" M\.isInBattle\(\) then MB\.play_se\(sound\)\n\s*else M\.playSE\(sound\) end",
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
