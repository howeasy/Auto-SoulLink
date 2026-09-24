"""BURIAL-VISIBLE: a GB client whose boxed burial waits on an in-game SAVE says so on its tick
(`awaiting_save`); the pair board shows it on that player's card. No emulator."""
from __future__ import annotations

from server.adapters.gen2_gsc import Gen2GSCAdapter
from server.state import SoulLinkState


def test_the_tick_flag_is_kept_per_player_and_cleared_by_the_next_tick(tmp_path):
    st = SoulLinkState(data_dir=str(tmp_path), adapter=Gen2GSCAdapter(rom_type="Crystal"))
    assert st.awaiting_save == {"a": False, "b": False}
    st.handle_event("a", {"event": "tick", "party": [], "awaiting_save": True})
    assert st.awaiting_save == {"a": True, "b": False}
    st.handle_event("a", {"event": "tick", "party": []})           # a client that does not send it: unchanged
    assert st.awaiting_save["a"] is True
    st.handle_event("a", {"event": "tick", "party": [], "awaiting_save": False})
    assert st.awaiting_save["a"] is False


def test_an_accepted_hello_resets_it_so_a_restarted_client_cannot_leave_it_stuck(tmp_path):
    st = SoulLinkState(data_dir=str(tmp_path), adapter=Gen2GSCAdapter(rom_type="Crystal"))
    st.handle_event("a", {"event": "tick", "party": [], "awaiting_save": True})
    st.handle_event("a", {"event": "hello", "party": [], "ot_id": "1111", "trainer_name": "A"})
    assert st.awaiting_save["a"] is False


def test_the_board_shows_awaiting_save_on_that_players_card():
    source = open("server/templates/_board.html", encoding="utf-8").read()
    assert "p.awaiting_save" in source and "SAVE" in source
