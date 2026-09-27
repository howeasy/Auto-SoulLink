"""Owner ruling 35: accept the NPC exchange, then retire only its violating pair."""

from copy import deepcopy
from pathlib import Path

import jinja2
import pytest

from server.server import SLinkServer
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo


TITLES = ("Red", "Blue", "Yellow", "PureRed", "Crystal", "Gold", "Silver",
          "firered", "leafgreen", "emerald", "firered_rr")


def _species(adapter, name):
    return next(i for i in range(1, 256) if adapter.species_name(i).casefold() == name.casefold())


def _key(adapter, number, species, ot):
    if adapter.game_id == "gen3_frlge":
        return f"{number:08X}:{ot:08X}"
    return f"{number:04X}:{ot:04X}:{species:02X}"


def _row(adapter, mon, **extra):
    return {"key": mon.key, "species_id": mon.species, "level": 10, "slot": 0,
            "hp": 20, "maxHP": 20, "blob_hex": bytes(adapter.party_blob_size()).hex(), **extra}


def _setup(tmp_path, title, *, other=False, species_lock=True, gender_lock=False, type_lock=False):
    srv = SLinkServer(data_dir=str(tmp_path), run_id="npc-clause-model", species_lock=species_lock,
                      gender_lock=gender_lock, type_lock=type_lock)
    srv._dispatch("a", {"event": "hello", "rom_type": title, "party": [], "ot_id": "1111"})
    adapter = srv.adapter
    ids = {name: _species(adapter, name) for name in ("Bulbasaur", "Charmander", "Charmeleon",
                                                    "Squirtle", "Pidgey", "Ponyta", "Pikachu", "Magnemite")}
    entry = LinkEntry(area_id="route_1", status=LinkStatus.ALIVE,
                      a=MonInfo(key=_key(adapter, 0xFFFF, ids["Bulbasaur"], 0x1111), species=ids["Bulbasaur"], level=10),
                      b=MonInfo(key=_key(adapter, 1, ids["Charmander"], 0x2222), species=ids["Charmander"], level=10))
    srv.state.links.append(entry)
    srv.state._index_entry(entry)
    srv.state.area_states[entry.area_id] = AreaStatus.LINKED
    boxes = {"a": [], "b": []}
    other_entry = None
    if other:
        other_entry = LinkEntry(area_id="route_2", status=LinkStatus.ALIVE,
                                a=MonInfo(key=_key(adapter, 3, ids["Pidgey"], 0x1111), species=ids["Pidgey"]),
                                b=MonInfo(key=_key(adapter, 4, ids["Squirtle"], 0x2222), species=ids["Squirtle"]))
        srv.state.links.append(other_entry)
        srv.state._index_entry(other_entry)
        srv.state.area_states[other_entry.area_id] = AreaStatus.LINKED
        for pid in ("a", "b"):
            boxes[pid] = [_row(adapter, getattr(other_entry, pid), box=0)]
    for pid in ("a", "b"):
        srv._dispatch(pid, {"event": "hello", "rom_type": title,
                            "ot_id": "1111" if pid == "a" else "2222", "has_pokeballs": True,
                            "party": [_row(adapter, getattr(entry, pid))],
                            "pc_boxes": boxes[pid], "pc_boxes_generation": 1})
    return srv, entry, other_entry, ids


def _exchange(srv, entry, species, *, player="a", reason="npc_trade", number=9):
    old_key = getattr(entry, player).key
    new_key = _key(srv.adapter, number, species, 0x9999)
    msg = {"event": "key_change", "reason": reason, "old_key": old_key,
           "new_key": new_key, "new_species": species, "new_nickname": "RECEIVED"}
    commands = srv._dispatch(player, msg)
    partner = "b" if player == "a" else "a"
    replies = {player: commands, partner: srv._dispatch(partner, {"event": "tick"})}
    return msg, replies


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("case,received", [("same_species", "Charmander"),
                                           ("same_family", "Charmeleon"),
                                           ("other_live_link", "Squirtle")])
def test_npc_trade_clause_retires_only_the_changed_pair(tmp_path, title, case, received):
    srv, entry, other, ids = _setup(tmp_path, title, other=case == "other_live_link")
    other_before = deepcopy(other)
    msg, replies = _exchange(srv, entry, ids[received])
    assert msg["_key_change_status"] == "migrated"
    assert entry.a.key == msg["new_key"] and entry.a.species == ids[received]
    assert srv.state.entry_for("a", msg["new_key"]) is entry
    assert srv.state.entry_for("a", msg["old_key"]) is None
    assert entry.status == LinkStatus.DEAD and entry.cause == "npc_trade_clause"
    assert entry.initiating_player == "a" and entry.killed_at
    assert other == other_before
    for pid in ("a", "b"):
        mon = getattr(entry, pid)
        death = next(i for i,c in enumerate(replies[pid]) if c["cmd"] == "force_faint" and c["key"] == mon.key)
        burial = next(i for i,c in enumerate(replies[pid]) if c["cmd"] == "memorialize" and c["key"] == mon.key)
        assert death < burial
        assert mon.key in srv.state.pending_memorials[pid]
        assert mon.key not in srv.state.party_keys[pid]
        if other:
            assert not any(c.get("key") == getattr(other, pid).key for c in replies[pid])
    assert replies["a"].index({"cmd": "key_change_ack", "old_key": msg["old_key"],
                               "new_key": msg["new_key"], "migrated": True}) < next(
        i for i,c in enumerate(replies["a"]) if c["cmd"] == "force_faint")
    assert srv.state.area_states[entry.area_id] == AreaStatus.LINKED
    assert not any(c["cmd"] in ("unresolve_area", "key_change_rejected") for cmds in replies.values() for c in cmds)
    assert not any(srv.state.retry_areas.values())


@pytest.mark.parametrize("title", TITLES)
def test_disabled_species_clause_preserves_a_conflicting_npc_exchange(tmp_path, title):
    srv, entry, _, ids = _setup(tmp_path, title, species_lock=False)
    msg, replies = _exchange(srv, entry, ids["Charmander"])
    assert msg["_key_change_status"] == "migrated" and entry.status == LinkStatus.ALIVE
    assert not any(c["cmd"] in ("force_faint", "memorialize") for cmds in replies.values() for c in cmds)


@pytest.mark.parametrize("title", TITLES)
def test_valid_mutation_does_not_collide_with_its_own_pair(tmp_path, title):
    srv, entry, _, ids = _setup(tmp_path, title)
    msg, replies = _exchange(srv, entry, ids["Ponyta"])
    assert msg["_key_change_status"] == "migrated" and entry.status == LinkStatus.ALIVE
    assert not any(c["cmd"] in ("force_faint", "memorialize", "key_change_rejected") for cmds in replies.values() for c in cmds)


@pytest.mark.parametrize("title", ("Red", "Crystal", "firered"))
def test_dead_other_pair_does_not_block_an_npc_family(tmp_path, title):
    srv, entry, other, ids = _setup(tmp_path, title, other=True)
    other.status = LinkStatus.DEAD
    msg, _ = _exchange(srv, entry, ids["Squirtle"])
    assert msg["_key_change_status"] == "migrated" and entry.status == LinkStatus.ALIVE


@pytest.mark.parametrize("title", ("Red", "Crystal", "firered"))
def test_same_player_duplicate_and_player_b_changes_are_checked(tmp_path, title):
    srv, entry, other, ids = _setup(tmp_path, title, other=True)
    msg, replies = _exchange(srv, entry, ids["Squirtle"], player="b")
    assert entry.b.key == msg["new_key"] and entry.status == LinkStatus.DEAD
    assert entry.initiating_player == "b" and entry.cause == "npc_trade_clause"
    assert other.status == LinkStatus.ALIVE
    for pid in ("a", "b"):
        assert any(c["cmd"] == "force_faint" and c["key"] == getattr(entry, pid).key for c in replies[pid])


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("enabled", [False, True])
def test_npc_type_clause_runs_only_when_enabled(tmp_path, title, enabled):
    srv, entry, _, ids = _setup(tmp_path, title, species_lock=False, type_lock=enabled)
    assert not set(srv.adapter.species_types(ids["Bulbasaur"])) & set(srv.adapter.species_types(ids["Charmander"]))
    assert set(srv.adapter.species_types(ids["Ponyta"])) & set(srv.adapter.species_types(ids["Charmander"]))
    _exchange(srv, entry, ids["Ponyta"])
    assert entry.status == (LinkStatus.DEAD if enabled else LinkStatus.ALIVE)


@pytest.mark.parametrize("title", ("Crystal", "Gold", "Silver", "firered", "leafgreen", "emerald", "firered_rr"))
@pytest.mark.parametrize("enabled", [False, True])
def test_npc_gender_clause_runs_only_when_enabled(tmp_path, title, enabled):
    srv, entry, _, ids = _setup(tmp_path, title, species_lock=False, gender_lock=enabled)
    assert srv.adapter.gender_from_key(entry.a.key, entry.a.species) == "male"
    assert srv.adapter.gender_from_key(entry.b.key, entry.b.species) == "female"
    incoming = _key(srv.adapter, 1, ids["Pikachu"], 0x9999)
    assert srv.adapter.gender_from_key(incoming, ids["Pikachu"]) == "female"
    _exchange(srv, entry, ids["Pikachu"], number=1)
    assert entry.status == (LinkStatus.DEAD if enabled else LinkStatus.ALIVE)


@pytest.mark.parametrize("title", ("Red", "PureRed", "Crystal", "firered"))
def test_unknown_or_genderless_gender_keeps_capture_time_exemption(tmp_path, title):
    srv, entry, _, ids = _setup(tmp_path, title, species_lock=False, gender_lock=True)
    incoming = _key(srv.adapter, 1, ids["Magnemite"], 0x9999)
    assert srv.adapter.gender_from_key(incoming, ids["Magnemite"]) in ("", "genderless")
    _exchange(srv, entry, ids["Magnemite"], number=1)
    assert entry.status == LinkStatus.ALIVE


@pytest.mark.parametrize("title", ("Red", "Crystal", "firered"))
def test_npc_clause_death_survives_reload_and_replay_does_not_retire_again(tmp_path, title):
    srv, entry, _, ids = _setup(tmp_path, title)
    msg, _ = _exchange(srv, entry, ids["Charmander"])
    killed_at = entry.killed_at
    commands = srv._dispatch("a", dict(msg))
    assert {"cmd": "key_change_ack", "old_key": msg["old_key"], "new_key": msg["new_key"], "migrated": False} in commands
    assert entry.killed_at == killed_at
    loaded = SLinkServer(data_dir=str(tmp_path))
    restored = loaded.state.entry_for("a", msg["new_key"])
    assert restored.status == LinkStatus.DEAD and restored.cause == "npc_trade_clause"
    assert restored.a.species == ids["Charmander"]


def test_npc_clause_has_a_named_memorial_cause(tmp_path):
    srv, _, _, ids = _setup(tmp_path, "firered")
    entry = srv.state.links[0]
    _exchange(srv, entry, ids["Charmander"])
    memorial = srv._build_status_dict()["killfeed"][0]
    assert memorial["cause"] == "npc_trade_clause"
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(__file__).resolve().parents[2] / "server/templates"),
                             autoescape=True, undefined=jinja2.ChainableUndefined)
    html = str(env.get_template("_macros.html").module.tombstone(memorial, 1))
    assert "NPC trade clause violation" in html
