"""card gen2-p4-w6: the pure halves of lua/tests/gen2_w6_gate.lua under lupa (writer verdict, Lua tagging), and
the static facts tests/live/test_gen2_w6_gate.w6_facts derives from the pinned overlay .sym."""
from __future__ import annotations

import pathlib
import sys

import lupa
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = (REPO / "lua" / "tests" / "gen2_w6_gate.lua").as_posix()
sys.path.insert(0, str(REPO))


def gate():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    return lua, lua.eval(f'dofile("{GATE}")')


def facts(lua):
    allow = lua.table_from([lua.table_from({"name": "bank", "bank": 0x75, "lo": 0x4000, "hi": 0x8000}),
                            lua.table_from({"name": "bridge", "bank": 0, "lo": 0x63, "hi": 0x7A}),
                            lua.table_from({"name": "entry", "bank": 4, "lo": 0x69DB, "hi": 0x69E7})])
    init = lua.table_from({"name": "Init WRAM0 clear", "entry": 0x17D, "lo": 0x1B1, "hi": 0x1B9})
    return lua.table_from({"allow": allow, "init": init})


def test_writer_verdict():
    lua, W = gate()
    f = facts(lua)
    # PC is reported AFTER the store: the writing instruction's last byte is PC - 1.
    assert W.classify(f, 0x4012, 0x75, 100, None) == ("allowed", "bank")
    assert W.classify(f, 0x4012, 0x74, 100, None)[0] == "violation"      # same PC, native bank
    assert W.classify(f, 0x0068, 0x33, 100, None) == ("allowed", "bridge")  # ROM0 ignores the shadow
    assert W.classify(f, 0x0063, 0, 100, None)[0] == "violation"          # store ended at $0062: header code
    assert W.classify(f, 0x007A, 0, 100, None) == ("allowed", "bridge")   # last bridge byte $0079
    assert W.classify(f, 0x69E7, 4, 100, None) == ("allowed", "entry")
    assert W.classify(f, 0x69E8, 4, 100, None)[0] == "violation"          # past the entry: native bank-4 code
    assert W.classify(f, 0x1B3, 1, 100, 90) == ("boot", "Init WRAM0 clear")
    assert W.classify(f, 0x1B3, 1, 100, 10) == ("violation", "Init WRAM0 clear outside boot/reset")
    assert W.classify(f, 0x1B3, 1, 100, None)[0] == "violation"


def test_observe_counts_and_lua_attribution():
    lua, W = gate()
    st = W.new(facts(lua))
    W.observe(st, 0xCFD8, 0x4013, 0x75, 5, False)
    W.observe(st, 0xCFD9, 0x0A00, 0x0F, 6, False)
    W.observe(st, 0xCFB3, 0x0290, 0x0F, 6, True)       # control byte: flagged, never a violation
    st.lua_depth = 1
    W.observe(st, 0xCFDA, 0x0A00, 0x0F, 7, False)      # inside a Lua store: the tag decides, not the PC
    assert (st.n_allowed, st.n_violations, st.lua_fired) == (1, 1, 1)
    assert st.writers["75:4013"] == 1 and st.violations[1].pc == 0x0A00
    assert (st.control.native_flagged, st.control.native_allowed) == (1, 0)


def test_region_verdict():
    """A SLink-owned native region: native writers are the game's; SLink code only if slink_allow names it."""
    lua, W = gate()
    f = facts(lua)
    closed = lua.table_from({"name": "wSpecialPhoneCallID", "slink_allow": lua.table_from([])})
    opened = lua.table_from({"name": "wSpecialPhoneCallID", "slink_allow": lua.table_from(["bank"])})
    assert W.classify_region(f, closed, 0x2A10, 0x24)[0] == "native"
    assert W.classify_region(f, closed, 0x4013, 0x75)[0] == "violation"
    assert W.classify_region(f, opened, 0x4013, 0x75) == ("slink", "bank")
    assert W.classify_region(f, opened, 0x0068, 0)[0] == "violation"     # the bridge is not the service bank


def test_lua_tag_and_span():
    lua, W = gate()
    client = lua.table_from(["@E:/x/lua/tests/test_gen2_scripted_gate.lua", "@E:\\x\\lua\\gen2\\panel.lua"])
    harness = lua.table_from(["@E:/x/lua/tests/gen2_panel_gate.lua", "@E:/x/lua/tests/gen2_w6_gate.lua"])
    assert W.lua_tag(client) == ("client", "lua/gen2/panel.lua")
    assert W.lua_tag(harness)[0] == "harness"
    st = W.new(facts(lua))
    W.lua_write(st, "harness", "x", 0xCFD8, 1, True)   # the control: kept apart, not a violation
    assert st.n_violations == 0 and st.control.lua_kind == "harness"
    W.lua_write(st, "harness", "x", 0xCFD8, 1, False)
    assert st.n_violations == 1
    span = lua.table_from({"lo": 0xCFD8, "hi": 0xD000})
    assert W.in_span(span, 0xCFFF, "System Bus") and not W.in_span(span, 0xD000, "System Bus")
    assert W.in_span(span, 0x0FD8, "WRAM") and not W.in_span(span, 0xCFD8, "ROM")


def test_w6_facts_are_the_pinned_overlay():
    """The allowlist names only SLink code; the span is the census span; Init's clear is where it was."""
    from tests.live.test_gen2_w6_gate import MAILBOX_SPANS, TITLES, w6_facts
    for title in TITLES:
        try:
            f = w6_facts(title)
        except Exception as exc:  # noqa: BLE001 - the pinned build is a local input
            pytest.skip(f"pinned build unavailable: {exc}")
        names = {r["name"] for r in f["allow"]}
        # data/script labels (SlinkSpecialPhoneCallList, SlinkTradeReceptionistScript) are never writer code
        # SlinkMainMenuBridge: TITLE-VERSION A's ROM0 SetUpMenu bridge (patch/gen2/src/version.asm)
        # SlinkTitleBridge: the titled overlays' ROM0 title-screen bridge (title-publish dc0a9c5b); the live gate
        # derives its allowlist from the symbol file, so it follows the build
        assert names == {"SLink service bank", "SlinkDelayFrameBridge", "SlinkResetSoundBridge",
                         "SlinkMainMenuBridge", "SlinkStartMenuEntry", "SlinkTitleBridge"}
        assert all(r["bank"] != 0 or r["hi"] <= 0x100 for r in f["allow"]), "a ROM0 range runs past the header"
        entry = next(r for r in f["allow"] if r["name"] == "SlinkStartMenuEntry")
        assert entry["bank"] == 4 and entry["hi"] - entry["lo"] == 12   # call FadeToMenu / farcall / ld a,6 / ret
        assert f["span"] == list(MAILBOX_SPANS[title])
        (phone,) = f["regions"]
        assert phone["hi"] - phone["lo"] == 2 and phone["wram_bank"] == 1 and phone["slink_allow"] == ["SLink service bank"]


# -- Gold's U1 leg: the disclosed SYNTH poisoned lead on the CURRENT drivers (sweep ffd54b44) ------------------------

def test_gold_u1_leg_runs_the_current_drivers_on_the_synth_poisoned_lead_with_a_pinned_clock():
    from tests.live import test_gen2_w6_gate as w6
    assert w6.U1_CHAIN_FOR["gold"] == "head" and w6.SYNTH_PSN_U1 == {"gold": "gold_synth_psn"}
    assert "gold" in w6.U1_CLOCK and ("gold", "u1") in __import__("tools.verify_gen2_release", fromlist=["x"]).W6_CLOCK_LEGS
    # Crystal and Silver keep their frozen chains (their natural hunts pass); only Gold changed
    assert w6.U1_CHAIN_FOR["crystal"] == "a882a763" and w6.U1_CHAIN_FOR["silver"] == "a7bf1773"
    assert set(w6.SYNTH_PSN_U1) == {"gold"}


def test_the_head_chain_resolves_to_an_exact_commit_and_supports_synth_facts():
    import inspect
    from tests.live import test_gen2_w6_gate as w6
    _, files, module = w6.frozen_u1("head")
    assert files and all(len(entry["ref"]) == 40 and entry["ref"] != "HEAD" for entry in files.values())
    assert "synth_psn" in inspect.signature(module.u1_facts).parameters, "the 09-24 chains predate the synth setup"
