"""Card U1G: a qualified direct gift (lua/gen2/signals.lua gift_event -> lua/gen2/client.lua publish_capture) reaches
the server as capture{gift=true, area_id=<gifts.json row area>}. The server trusts the flag: both sides' gifts in
the same area link in that area's gift namespace, and a gift never counts as proof the player owns Poke Balls (server/state.py
_handle_capture)."""
from __future__ import annotations

from server.adapters.gen2_gsc import Gen2GSCAdapter
from server.state import AreaStatus, SoulLinkState


def test_direct_gifts_on_both_sides_link_in_their_area_without_claiming_balls(tmp_path):
    st = SoulLinkState(data_dir=str(tmp_path), adapter=Gen2GSCAdapter(rom_type="Crystal"))
    before = dict(st.pokeballs_obtained)
    for player, key in (("a", "5AAA:1234:85"), ("b", "6BBB:4321:85")):
        st.handle_event(player, {"event": "capture", "key": key, "area_id": "goldenrod_city", "species_id": 133,
                                 "level": 20, "gift": True, "in_box": False})
    # the server keys a gift link under the area's gift namespace: the ordinary area stays unconsumed
    assert st.area_states == {"gift_goldenrod_city": AreaStatus.LINKED}
    assert [(e.a.key, e.b.key) for e in st.links] == [("5AAA:1234:85", "6BBB:4321:85")]
    assert dict(st.pokeballs_obtained) == before
