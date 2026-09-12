"""Actual Gen1 rule/server paths with equal and crossed per-player raw keys."""
import asyncio
import copy
import json

import pytest

from server.adapters import get_adapter
from server.gen1_staged_state import StagedGen1State
from server.player_keys import AmbiguousPhysicalKey
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_gen1_sessions import contract, hello, server

SHARED, A_ONLY, B_ONLY = "AABB:1234:54", "AAAA:1234:99", "BBBB:1234:B0"


def state(tmp_path, variant="yellow"):
    value = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type=variant))
    value.rom_type = variant
    value.pokeballs_obtained = {"a": True, "b": True}
    return value


def add(value, area, a, b):
    pair = LinkEntry(area, MonInfo(a, 5, 25, "ALPHA"), MonInfo(b, 17, 25, "BETA"), LinkStatus.ALIVE)
    value.links.append(pair)
    value._index_entry(pair)
    value.party_keys["a"].add(a)
    value.party_keys["b"].add(b)
    return pair


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("fainter", ["a", "b"])
def test_identical_halves_keep_their_own_stats_through_save_death_and_reopen(tmp_path, variant, fainter):
    value = state(tmp_path, variant)
    pair = add(value, "oaks_lab", SHARED, SHARED)
    value.cache_stats("a", SHARED, {"level": 12, "moves": [1, 2], "maxHP": 40})
    value.cache_stats("b", SHARED, {"level": 29, "moves": [3, 4], "maxHP": 80})
    value._save()
    restored = SoulLinkState.load(data_dir=str(tmp_path))
    assert restored.player_scoped_keys
    assert restored.find_link("a", SHARED) is restored.find_link("b", SHARED)
    assert restored.stats_for("a", SHARED)["moves"] == [1, 2]
    assert restored.stats_for("b", SHARED)["moves"] == [3, 4]
    restored._handle_faint(fainter, {"key": SHARED})
    pair = restored.links[0]
    assert pair.status == LinkStatus.DEAD and (pair.a.level, pair.b.level) == (12, 29)
    peer = "b" if fainter == "a" else "a"
    assert restored.queued_death_cmd(peer, SHARED) == "force_faint"
    assert restored.queued_death_cmd(fainter, SHARED) is None
    assert all(SHARED in restored.pending_memorials[p] for p in ("a", "b"))


@pytest.mark.parametrize("fainter", ["a", "b"])
def test_crossed_raw_keys_kill_only_the_actors_link(tmp_path, fainter):
    value = state(tmp_path)
    first = add(value, "route_1", SHARED, B_ONLY)
    second = add(value, "route_2", A_ONLY, SHARED)
    assert SHARED not in value._key_index  # the unscoped legacy projection is ambiguous
    assert value.find_link("a", SHARED) is first
    assert value.find_link("b", SHARED) is second
    value._handle_faint(fainter, {"key": SHARED})
    assert first.status == (LinkStatus.DEAD if fainter == "a" else LinkStatus.ALIVE)
    assert second.status == (LinkStatus.DEAD if fainter == "b" else LinkStatus.ALIVE)
    peer = "b" if fainter == "a" else "a"
    target = B_ONLY if fainter == "a" else A_ONLY
    assert value.queued_death_cmd(peer, target) == "force_faint"
    assert value.queued_death_cmd(peer, SHARED) is None


def test_evolution_moves_only_one_players_key_stats_and_bonus_reference(tmp_path):
    value = state(tmp_path)
    pair = add(value, "oaks_lab", SHARED, SHARED)
    value.cache_stats("a", SHARED, {"level": 12})
    value.cache_stats("b", SHARED, {"level": 29})
    value.pending_bonus["a"].append(SHARED)
    value.pending_bonus["b"].append(SHARED)
    new_key = SHARED[:-2]+"55"
    value._handle_key_change("a", {"old_key": SHARED, "new_key": new_key, "reason": "evolution"})
    assert pair.a.key == new_key and pair.b.key == SHARED
    assert value.find_link("a", SHARED) is None and value.find_link("b", SHARED) is pair
    assert value.stats_for("a", new_key)["level"] == 12 and value.stats_for("b", SHARED)["level"] == 29
    assert list(value.pending_bonus["a"]) == [SHARED]
    assert list(value.pending_bonus["b"]) == [new_key]


def test_same_save_capture_or_key_change_collision_has_no_rule_or_command_effect(tmp_path):
    value = state(tmp_path)
    add(value, "route_1", SHARED, B_ONLY)
    add(value, "route_2", A_ONLY, "CCCC:1234:B0")
    before = StagedGen1State.from_live(value, {"retired_pairs": []}).document()
    with pytest.raises(AmbiguousPhysicalKey):
        value._handle_capture("a", {"area_id": "route_3", "key": SHARED, "species_id": 25})
    with pytest.raises(ValueError, match="collides"):
        value._handle_key_change("a", {"old_key": A_ONLY, "new_key": SHARED})
    assert StagedGen1State.from_live(value, {"retired_pairs": []}).document() == before


def test_ambiguous_legacy_cache_is_not_copied_to_both_players(tmp_path):
    value = state(tmp_path)
    add(value, "oaks_lab", SHARED, SHARED)
    value.mon_stats[SHARED] = {"level": 99, "moves": [99]}
    assert value.stats_for("a", SHARED) is None and value.stats_for("b", SHARED) is None
    value.cache_stats("b", SHARED, {"level": 12})
    assert value.stats_for("a", SHARED) is None and value.stats_for("b", SHARED) == {"level": 12}


def test_ambiguous_loaded_gen1_run_raises_instead_of_returning_partial_state(tmp_path):
    value = state(tmp_path)
    add(value, "route_1", SHARED, B_ONLY)
    doc = value.to_document()
    duplicate = copy.deepcopy(doc["links"][0])
    duplicate["area_id"] = "route_2"
    doc["links"].append(duplicate)
    (tmp_path/"links.json").write_text(json.dumps(doc))
    with pytest.raises(AmbiguousPhysicalKey):
        SoulLinkState.load(data_dir=str(tmp_path))


def test_yellow_yellow_real_tcp_capture_and_faint_keep_equal_keys_player_scoped(tmp_path):
    async def scenario():
        spec = contract("yellow", "yellow")
        srv = server(tmp_path, spec)
        listener = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
        port = listener.sockets[0].getsockname()[1]
        connections, replies = {}, {}

        async def send(player, message):
            reader, writer = connections[player]
            writer.write((json.dumps(message)+"\n").encode())
            await writer.drain()
            return json.loads(await asyncio.wait_for(reader.readline(), 3))

        try:
            for player in ("a", "b"):
                connections[player] = await asyncio.open_connection("127.0.0.1", port)
                replies[player] = await send(player, hello(spec, player, ot_id="1234", trainer_name="SAME", has_pokeballs=True))
                assert replies[player]["ack"] == "ACK"
            def envelope(player, seq, **payload):
                session = srv._gen1_sessions.sessions[player]
                return {"protocol": replies[player]["protocol"], "player": player,
                    "admission_epoch": replies[player]["admission_epoch"], "session_id": replies[player]["session_id"],
                    "seq": seq, "operation_id": session.nonce+":"+str(seq), **payload}
            for player, level in (("a", 12), ("b", 29)):
                result = await send(player, envelope(player, 1, event="capture", area_id="oaks_lab", key=SHARED,
                    species_id=25, nickname=player.upper(), level=level, maxHP=level+20, gift=True))
                assert result["ack"] == "ACK"
            assert len(srv.state.links) == 1 and srv.state.links[0].status == LinkStatus.ALIVE
            pair = srv.state.links[0]
            assert pair.a.nickname == "A" and pair.b.nickname == "B"
            assert srv.state.stats_for("a", SHARED)["level"] == 12
            assert srv.state.stats_for("b", SHARED)["level"] == 29
            result = await send("a", envelope("a", 2, event="faint", key=SHARED))
            assert result["ack"] == "ACK" and pair.status == LinkStatus.DEAD
            assert pair.a.level == 12 and pair.b.level == 29
            assert srv.state.queued_death_cmd("b", SHARED) == "force_faint"
        finally:
            for _, writer in connections.values():
                writer.close()
                await writer.wait_closed()
            listener.close()
            await listener.wait_closed()
    asyncio.run(scenario())


def test_gen3_retains_legacy_key_collision_policy(tmp_path):
    value = SoulLinkState(data_dir=str(tmp_path))
    assert not value.player_scoped_keys
    assert value._check_link_violation(MonInfo(SHARED), MonInfo(SHARED)) is not None
