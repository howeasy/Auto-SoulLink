"""Gen 1 receptionist trade events over the existing game-neutral trade state."""

from __future__ import annotations

import pytest

from server.adapters.gen1_rby import Gen1Adapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState


def _linked(tmp_path, *, gen1=True):
    adapter = Gen1Adapter() if gen1 else Gen3Adapter()
    state = SoulLinkState(data_dir=str(tmp_path), adapter=adapter)
    a_key, b_key = (("ABCD:1234:99", "1234:5678:15") if gen1 else ("A:1", "B:2"))
    a_blob, b_blob = (bytes([0x99]) * 66, bytes([0x15]) * 66) if gen1 else (
        bytes([0xAA]) * 100, bytes([0xBB]) * 100)
    entry = LinkEntry(area_id="route_1",
                      a=MonInfo(key=a_key, species=153, level=12),
                      b=MonInfo(key=b_key, species=21, level=13),
                      status=LinkStatus.ALIVE)
    state.links.append(entry)
    state._index_entry(entry)
    state.party_keys["a"].add(a_key)
    state.party_keys["b"].add(b_key)
    state.party_size = {"a": 2, "b": 2}
    state.pokeballs_obtained = {"a": True, "b": True}
    state.partner_blobs["a"] = [{"slot": 2, "key": a_key, "blob": a_blob,
                                  "species_id": 153, "level": 12}]
    state.partner_blobs["b"] = [{"slot": 4, "key": b_key, "blob": b_blob,
                                  "species_id": 21, "level": 13}]
    state.player_identity["a"] = {"trainer_name": "Alice", "ot_id": "1234"}
    state.player_identity["b"] = {"trainer_name": "Bob", "ot_id": "5678"}
    return state, entry, a_blob, b_blob


def _cmd(commands, name):
    return next(command for command in commands if command.get("cmd") == name)


def test_query_mask_uses_own_eligible_slots_and_busy_is_zero(tmp_path):
    state, _entry, _a, _b = _linked(tmp_path)
    assert _cmd(state.handle_event("a", {"event": "trade_query"}), "trade_mask") == (
        {"cmd": "trade_mask", "mask": 1 << 2})
    assert _cmd(state.handle_event("b", {"event": "trade_query"}), "trade_mask") == (
        {"cmd": "trade_mask", "mask": 1 << 4})
    extra = LinkEntry(area_id="route_2", a=MonInfo(key="0001:1111:99"),
                      b=MonInfo(key="0002:2222:15"), status=LinkStatus.ALIVE)
    state.links.append(extra)
    state._index_entry(extra)
    state.party_keys["a"].add(extra.a.key)
    state.party_keys["b"].add(extra.b.key)
    state.partner_blobs["a"].append({"slot": 0, "key": extra.a.key, "blob": bytes(66)})
    state.partner_blobs["b"].append({"slot": 1, "key": extra.b.key, "blob": bytes(66)})
    assert _cmd(state.handle_event("a", {"event": "trade_query"}), "trade_mask")["mask"] == (
        (1 << 0) | (1 << 2))
    state.pending_trade = {"phase": "choosing", "initiator": "b", "token": "busy", "age": 0}
    assert _cmd(state.handle_event("a", {"event": "trade_query"}), "trade_mask")["mask"] == 0


def test_offer_confirms_without_gen3_action_menu_and_stages_partner_prompt(tmp_path):
    state, entry, a_blob, _b_blob = _linked(tmp_path)
    reply = state.handle_event("a", {"event": "trade_offer", "slot": 2})
    assert _cmd(reply, "trade_offer_ack") == {"cmd": "trade_offer_ack", "ok": True}
    assert not any(command["cmd"] in ("show_choices", "choose_mon") for command in reply)
    assert state.pending_trade and state.pending_trade["phase"] == "confirming"
    prompt = _cmd(state.handle_event("b", {"event": "tick"}), "show_menu")
    assert prompt["token"] == state.pending_trade["token"]
    assert prompt["slot"] == 4 and prompt["blob_hex"] == a_blob.hex()
    assert entry.a.key == "ABCD:1234:99" and entry.b.key == "1234:5678:15"

    reply_b = state.handle_event("b", {"event": "menu_result",
                                       "token": prompt["token"], "choice": 1})
    cmd_b = _cmd(reply_b, "apply_trade")
    assert cmd_b["slot"] == 4 and cmd_b["blob_hex"] == a_blob.hex()
    assert cmd_b["partner_name"] == "Alice"
    cmd_a = _cmd(state.handle_event("a", {"event": "tick"}), "apply_trade")
    assert cmd_a["slot"] == 2 and cmd_a["partner_name"] == "Bob"
    assert state.pending_trade["phase"] == "applying"


@pytest.mark.parametrize("which", ("initiator", "partner"))
def test_offer_refuses_incoming_key_collision_without_mutation(tmp_path, which):
    state, entry, _a, _b = _linked(tmp_path)
    if which == "initiator":
        state.party_keys["a"].add(entry.b.key)  # B's key would enter A's party
    else:
        state.party_keys["b"].add(entry.a.key)  # A's key would enter B's party
    before = list(state.links)
    reply = state.handle_event("a", {"event": "trade_offer", "slot": 2})
    assert _cmd(reply, "trade_offer_ack") == {"cmd": "trade_offer_ack", "ok": False}
    assert state.pending_trade is None and state.links == before
    assert not any(command["cmd"] in ("show_menu", "apply_trade") for command in reply)


def test_offer_refuses_unknown_slot_and_inflight_trade(tmp_path):
    state, _entry, _a, _b = _linked(tmp_path)
    for slot in (-1, 0, 6, "not a slot"):
        assert _cmd(state.handle_event("a", {"event": "trade_offer", "slot": slot}),
                    "trade_offer_ack")["ok"] is False
        assert state.pending_trade is None
    state.handle_event("a", {"event": "trade_offer", "slot": 2})
    old = state.pending_trade
    assert _cmd(state.handle_event("b", {"event": "trade_offer", "slot": 4}),
                "trade_offer_ack")["ok"] is False
    assert state.pending_trade is old


def test_late_gen1_collision_cancels_before_apply_commands(tmp_path):
    state, entry, _a, _b = _linked(tmp_path)
    state.handle_event("a", {"event": "trade_offer", "slot": 2})
    token = state.pending_trade["token"]
    state.party_keys["a"].add(entry.b.key)  # arrived while partner considered prompt
    reply = state.handle_event("b", {"event": "menu_result", "token": token, "choice": 1})
    assert state.pending_trade is None
    assert not any(command["cmd"] == "apply_trade" for command in reply)
    assert not any(command["cmd"] == "apply_trade" for command in state.handle_event(
        "a", {"event": "tick"}))


def test_gen3_trade_request_menu_pick_confirm_apply_shape_is_unchanged(tmp_path):
    state, _entry, a_blob, b_blob = _linked(tmp_path, gen1=False)
    choices = _cmd(state.handle_event("a", {"event": "trade_request"}), "show_choices")
    assert set(choices) == {"cmd", "token", "options", "text"}
    assert choices["options"] == ["Trade", "Say hey"]
    token = choices["token"]
    choose = _cmd(state.handle_event("a", {"event": "menu_result", "token": token,
                                            "choice": 0}), "choose_mon")
    assert choose == {"cmd": "choose_mon", "token": token}
    state.handle_event("a", {"event": "mon_chosen", "token": token, "slot": 2})
    prompt = _cmd(state.handle_event("b", {"event": "tick"}), "show_menu")
    assert set(prompt) == {"cmd", "token", "text"}
    reply_b = state.handle_event("b", {"event": "menu_result", "token": token,
                                       "choice": 1})
    b_cmd = _cmd(reply_b, "apply_trade")
    a_cmd = _cmd(state.handle_event("a", {"event": "tick"}), "apply_trade")
    assert b_cmd == {"cmd": "apply_trade", "slot": 4, "blob_hex": a_blob.hex(),
                     "old_key": "B:2", "token": token}
    assert a_cmd == {"cmd": "apply_trade", "slot": 2, "blob_hex": b_blob.hex(),
                     "old_key": "A:1", "token": token}
