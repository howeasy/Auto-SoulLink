"""The acknowledged `key_change` contract (docs/purergb/PLAN.md §5.2 A1/A2/A3, §11.2 O2).

`_handle_key_change` is validate -> accept | reject -> mutate.  Every event is answered in the
same reply by `key_change_ack{migrated}` or `key_change_rejected{reason}`; a rejection mutates
nothing and retires the old key's pair `cause="identity_lost"` (owner decision U5).  The
presentation caches in server.py migrate only after acceptance.  A hello for another game, or
another artifact kind, is refused as MIXED GAMES; a contract `rom_sha1` is compared.
"""
from __future__ import annotations

import asyncio
import copy
import json

import pytest

from server.adapters.gen1_rby import Gen1Adapter
from server.server import SLinkServer
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState

OLD, NEW, OTHER = "AAAA:30B8:10", "FFFF:30B8:10", "CCDD:7B0B:10"


@pytest.fixture
def st(tmp_path):
    return SoulLinkState(data_dir=str(tmp_path), adapter=Gen1Adapter())


def _link(st, a_key=OLD, b_key=OTHER, status=LinkStatus.ALIVE, area="route_1") -> LinkEntry:
    entry = LinkEntry(area_id=area, a=MonInfo(key=a_key, level=5), b=MonInfo(key=b_key, level=7),
                      status=status)
    st.links.append(entry)
    st._index_entry(entry)
    if status == LinkStatus.ALIVE:
        st.party_keys["a"].add(a_key)
        st.party_keys["b"].add(b_key)
    st.pokeballs_obtained = {"a": True, "b": True}
    st.party_size = {"a": 2, "b": 2}
    return entry


def _change(st, old=OLD, new=NEW, player="a", **extra) -> list[dict]:
    return st.handle_event(player, {"event": "key_change", "old_key": old, "new_key": new, **extra})


def _one(cmds, name) -> dict:
    hits = [c for c in cmds if c.get("cmd") == name]
    assert len(hits) == 1, (name, cmds)
    return hits[0]


def _snapshot(st) -> dict:
    return copy.deepcopy({
        "links": [(e.a.key if e.a else None, e.b.key if e.b else None, e.status.value)
                  for e in st.links],
        "index": sorted(st._key_index),
        "party_keys": {p: sorted(v) for p, v in st.party_keys.items()},
        "mon_stats": st.mon_stats, "bonus_keys": {p: sorted(v) for p, v in st.bonus_keys.items()},
        "pending_memorials": {p: sorted(v) for p, v in st.pending_memorials.items()},
        "pending_captures": {a: {p: m.key for p, m in ps.items()} for a, ps in st.pending_captures.items()},
        "partner_blobs": {p: [b.get("key") for b in v] for p, v in st.partner_blobs.items()},
        "rebuild_pending": st.rebuild_pending,
        # the watchdog ages every pending trade on every event; only its keys matter here
        "pending_trade": {k: v for k, v in (st.pending_trade or {}).items() if k != "age"},
    })


# ── acknowledgement ──────────────────────────────────────────────────────────────────────

def test_an_accepted_change_is_acked_in_the_same_reply(st):
    _link(st)
    ack = _one(_change(st), "key_change_ack")
    assert ack == {"cmd": "key_change_ack", "old_key": OLD, "new_key": NEW, "migrated": True}
    assert st.links[0].a.key == NEW and NEW in st._key_index and OLD not in st._key_index
    assert not any(c["cmd"] == "key_change_rejected" for c in st.queued_commands["a"])


def test_a_replay_acks_without_mutating(st):
    """The client resends after a reconnect: the migration already happened."""
    _link(st)
    _change(st)
    before = _snapshot(st)
    ack = _one(_change(st), "key_change_ack")
    assert ack["migrated"] is False
    assert _snapshot(st) == before


def test_an_unknown_old_key_acks_migrated_false(st):
    """Gen 3 nature change on a mon the server never tracked: nothing to do, still answered."""
    before = _snapshot(st)
    ack = _one(_change(st, old="1234:5678:01", new="9ABC:5678:01"), "key_change_ack")
    assert ack["migrated"] is False
    assert _snapshot(st) == before


def test_a_party_only_mon_still_migrates_as_before(st):
    """The vanilla Gen 3 case: unlinked, but in party_keys — migrated and acked."""
    st.party_keys["a"].add(OLD)
    ack = _one(_change(st), "key_change_ack")
    assert ack["migrated"] is True
    assert NEW in st.party_keys["a"] and OLD not in st.party_keys["a"]


# ── collision preflight ──────────────────────────────────────────────────────────────────

def test_a_collision_with_a_live_link_rejects_and_retires_the_pair(st):
    entry = _link(st)
    other = _link(st, a_key=NEW, b_key="EEFF:7B0B:11", area="route_2")
    cmds = _change(st)
    rej = _one(cmds, "key_change_rejected")
    assert rej["old_key"] == OLD and rej["new_key"] == NEW and "route_2" in rej["reason"]
    assert not any(c["cmd"] == "key_change_ack" for c in cmds)
    # Nothing migrated: the colliding link is untouched, the old key still indexes ours.
    assert st._key_index[NEW] is other and st._key_index[OLD] is entry
    assert entry.a.key == OLD
    # U5: the pair is retired identity_lost, the partner force-fainted, both memorialized.
    assert entry.status == LinkStatus.DEAD and entry.cause == "identity_lost"
    assert st.queued_death_cmd("b", OTHER) == "force_faint"
    assert OTHER in st.pending_memorials["b"] and OLD in st.pending_memorials["a"]
    assert any(c["cmd"] == "memorialize" and c["key"] == OLD for c in cmds)
    assert other.status == LinkStatus.ALIVE


def test_identity_lost_is_never_an_explosion(st):
    """Explode mode turns battle faints into force_explode; a rejected key change is not a
    battle and the partner's client must not be told to explode."""
    st.explode_mode = True
    _link(st)
    _link(st, a_key=NEW, b_key="EEFF:7B0B:11", area="route_2")
    _change(st)
    assert st.queued_death_cmd("b", OTHER) == "force_faint"


@pytest.mark.parametrize("structure", (
    "party_keys", "pending_captures", "bonus_keys", "pending_bonus", "partner_blobs",
    "rebuild_pending", "pending_trade", "queued_commands", "sync_inflight", "presentation",
))
def test_a_key_that_is_load_bearing_anywhere_rejects_with_structures_untouched(st, structure):
    _link(st)
    seen = {"presentation": False}
    if structure == "party_keys":
        st.party_keys["b"].add(NEW)
    elif structure == "pending_captures":
        st.pending_captures["route_9"] = {"b": MonInfo(key=NEW, level=3)}
    elif structure == "bonus_keys":
        st.bonus_keys["b"].add(NEW)
    elif structure == "pending_bonus":
        st.pending_bonus["b"].append(NEW)
    elif structure == "partner_blobs":
        st.partner_blobs["b"] = [{"slot": 0, "key": NEW, "blob": b"\0" * 66, "species_id": 1, "level": 1}]
    elif structure == "rebuild_pending":
        st.rebuild_pending["b"] = {"queued_keys": [NEW], "queued_partner_keys": [], "restored_keys": set()}
    elif structure == "pending_trade":
        st.pending_trade = {"phase": "menu", "initiator": "b", "token": "t1", "reprompts": 0, "age": 0,
                            "a_key": "1111:2222:33", "b_key": NEW}
    elif structure == "queued_commands":
        st.queued_commands["b"].append({"cmd": "box_mon", "key": NEW})
    elif structure == "sync_inflight":
        st.sync_inflight["b"][(NEW, "party_mon")] = 3
    elif structure == "presentation":
        def hook(key):
            seen["presentation"] = key == NEW
            return key == NEW
        st.presentation_key_in_use = hook
    before = _snapshot(st)
    cmds = _change(st)
    rej = _one(cmds, "key_change_rejected")
    after = _snapshot(st)
    # The only mutation is the identity_lost retire of our own pair.
    assert after["index"] == before["index"]
    assert after["links"][0][:2] == before["links"][0][:2]
    assert after["links"][0][2] == "dead"
    for k in ("mon_stats", "bonus_keys", "pending_captures", "partner_blobs", "rebuild_pending",
              "pending_trade"):
        assert after[k] == before[k], k
    assert structure in rej["reason"] or (structure == "presentation" and seen["presentation"])


def test_a_dead_key_hit_is_accepted_and_logged(st, caplog):
    """A buried key is reusable by design (test_gen1_identity_and_collisions); the existing
    KEY COLLISION log from _index_entry is the only trace."""
    _link(st)
    _link(st, a_key=NEW, b_key="EEFF:7B0B:11", status=LinkStatus.MEMORIAL, area="route_2")
    with caplog.at_level("ERROR"):
        ack = _one(_change(st), "key_change_ack")
    assert ack["migrated"] is True
    assert st._key_index[NEW] is st.links[0] and st.links[0].a.key == NEW
    assert any("KEY COLLISION" in r.message for r in caplog.records)


def test_mon_stats_alone_is_a_cache_not_a_collision(st):
    """mon_stats is never pruned, so every buried key lives there forever; treating it as
    load-bearing would turn the reusable-buried-key rule into a pair kill."""
    _link(st)
    st.mon_stats[NEW] = {"level": 99}
    st.mon_stats[OLD] = {"level": 5}
    assert _one(_change(st), "key_change_ack")["migrated"] is True
    assert st.mon_stats[NEW] == {"level": 5}


# ── every structure migrates ──────────────────────────────────────────────────────────────

def test_every_structure_in_the_census_migrates(st):
    entry = _link(st)
    entry.encounter_a = MonInfo(key=OLD, species=1)
    st.mon_stats[OLD] = {"level": 5}
    st.bonus_keys["a"].add(OLD)
    st.pending_memorials["a"].add(OLD)
    st.pending_bonus["b"].append(OLD)
    st.partner_blobs["a"] = [{"slot": 0, "key": OLD, "blob": b"\0" * 66, "species_id": 1, "level": 1}]
    st.rebuild_pending["a"] = {"queued_keys": [OLD], "queued_partner_keys": [], "restored_keys": {OLD}}
    st.pending_trade = {"phase": "menu", "initiator": "a", "token": "t1", "reprompts": 0, "age": 0,
                        "a_key": OLD, "b_key": OTHER}
    st.queued_commands["a"].append({"cmd": "apply_trade", "slot": 0, "blob_hex": "00", "old_key": OLD, "token": "t1"})
    st.sync_inflight["a"][(OLD, "party_mon")] = 2
    cmds = _change(st, new_species=2, new_nickname="EVO")
    assert _one(cmds, "key_change_ack")["migrated"] is True
    assert entry.a.key == NEW and entry.a.species == 2 and entry.a.nickname == "EVO"
    assert entry.encounter_a.key == NEW
    assert st._key_index[NEW] is entry and OLD not in st._key_index
    assert st.party_keys["a"] == {NEW}
    assert st.mon_stats == {NEW: {"level": 5}}
    assert st.bonus_keys["a"] == {NEW}
    assert st.pending_memorials["a"] == {NEW}
    assert list(st.pending_bonus["b"]) == [NEW]
    assert st.partner_blobs["a"][0]["key"] == NEW
    assert st.rebuild_pending["a"] == {"queued_keys": [NEW], "queued_partner_keys": [], "restored_keys": {NEW}}
    assert st.pending_trade["a_key"] == NEW and st.pending_trade["b_key"] == OTHER
    assert _one(cmds, "apply_trade")["old_key"] == NEW
    assert (NEW, "party_mon") in st.sync_inflight["a"] and (OLD, "party_mon") not in st.sync_inflight["a"]


# ── A2: a transformation never revives ────────────────────────────────────────────────────

def test_a_change_on_a_buried_link_requeues_the_death_under_the_new_key(st):
    _link(st, status=LinkStatus.DEAD)
    cmds = _change(st)
    assert _one(cmds, "key_change_ack")["migrated"] is True
    assert _one(cmds, "force_faint")["key"] == NEW
    assert _one(cmds, "memorialize")["key"] == NEW
    assert NEW in st.pending_memorials["a"]


def test_the_requeued_death_is_deduped_against_a_pending_one(st):
    _link(st, status=LinkStatus.DEAD)
    st.queued_commands["a"].append({"cmd": "force_faint", "key": OLD})
    cmds = _change(st)
    assert len([c for c in cmds if c["cmd"] == "force_faint"]) == 1
    assert _one(cmds, "force_faint")["key"] == NEW


def test_a_change_on_a_live_link_queues_no_death(st):
    _link(st)
    cmds = _change(st)
    assert not any(c["cmd"] in ("force_faint", "force_explode", "memorialize") for c in cmds)


# ── server.py: presentation migrates only after acceptance ────────────────────────────────

def _server(tmp_path) -> SLinkServer:
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.adapter = srv.adapter = Gen1Adapter(variant="red")
    return srv


def test_presentation_caches_migrate_after_acceptance(tmp_path):
    srv = _server(tmp_path)
    _link(srv.state)
    srv.party_details["a"][OLD] = {"nickname": "PIKA", "level": 5}
    srv._mon_cache[OLD] = {"species_id": 25}
    srv.pc_boxes["a"] = [{"box": 0, "slot": 0, "key": OLD, "species_id": 25}]
    cmds = srv._dispatch("a", {"event": "key_change", "old_key": OLD, "new_key": NEW})
    assert any(c["cmd"] == "key_change_ack" for c in cmds)
    assert srv.party_details["a"] == {NEW: {"nickname": "PIKA", "level": 5}}
    assert srv._mon_cache == {NEW: {"species_id": 25}}
    assert srv.pc_boxes["a"][0]["key"] == NEW


def test_presentation_caches_stay_put_on_rejection(tmp_path):
    srv = _server(tmp_path)
    _link(srv.state)
    _link(srv.state, a_key=NEW, b_key="EEFF:7B0B:11", area="route_2")
    srv.party_details["a"][OLD] = {"nickname": "PIKA", "level": 5}
    srv._mon_cache[OLD] = {"species_id": 25}
    cmds = srv._dispatch("a", {"event": "key_change", "old_key": OLD, "new_key": NEW})
    assert any(c["cmd"] == "key_change_rejected" for c in cmds)
    assert OLD in srv.party_details["a"] and NEW not in srv.party_details["a"]
    assert OLD in srv._mon_cache and NEW not in srv._mon_cache


def test_a_live_presentation_key_is_a_collision_but_the_memorial_box_is_not(tmp_path):
    srv = _server(tmp_path)
    mem = srv.adapter.memorial_box_index
    srv.pc_boxes["b"] = [{"box": mem, "slot": 0, "key": NEW}]
    assert srv._presentation_key_in_use(NEW) is False, "a buried key in the memorial box is reusable"
    srv.pc_boxes["b"] = [{"box": 0, "slot": 0, "key": NEW}]
    assert srv._presentation_key_in_use(NEW) is True
    srv.pc_boxes["b"] = []
    srv.party_details["b"][NEW] = {"level": 1}
    assert srv._presentation_key_in_use(NEW) is True
    # The state consults it through the adapter-neutral hook.
    _link(srv.state)
    cmds = srv._dispatch("a", {"event": "key_change", "old_key": OLD, "new_key": NEW})
    assert "presentation" in _one(cmds, "key_change_rejected")["reason"]


# ── A3: mixed games / mixed kinds / contract sha1 ─────────────────────────────────────────

async def _session(srv):
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    port = tcp.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)

    async def send(msg):
        w.write((json.dumps(msg) + "\n").encode())
        await w.drain()
        return json.loads(await asyncio.wait_for(r.readline(), 3))

    async def close():
        w.close()
        tcp.close()
        await tcp.wait_closed()
    return send, close


def _mixed(reply) -> bool:
    return any(c.get("cmd") == "hud_show" and "MIXED GAMES" in c.get("text", "") for c in reply["commands"])


@pytest.mark.asyncio
async def test_a_second_game_hello_is_refused(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send({"event": "hello", "player": "a", "rom_type": "red", "trainer_name": "Alice",
                            "ot_id": "30B8", "has_pokeballs": True, "party": []})
        assert not _mixed(reply) and srv.state.rom_type == "red"
        reply = await send({"event": "hello", "player": "b", "rom_type": "firered", "trainer_name": "Bob",
                            "ot_id": "7B0B", "has_pokeballs": True, "party": []})
        assert _mixed(reply)
        assert "Mixed games" in srv.state.identity_error["b"]
        assert srv.adapter.game_id == "gen1_rby"
        await send({"event": "area_enter", "player": "b", "area_id": "route_1"})
        assert "route_1" not in srv.state.area_states, "nothing else gets through while refused"
        # A conforming hello clears it.
        reply = await send({"event": "hello", "player": "b", "rom_type": "blue", "trainer_name": "Bob",
                            "ot_id": "7B0B", "has_pokeballs": True, "party": []})
        assert not _mixed(reply) and not srv.state.identity_error.get("b")
    finally:
        await close()


@pytest.mark.asyncio
async def test_a_second_artifact_kind_is_refused_and_the_default_kind_pairs(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send({"event": "hello", "player": "a", "rom_type": "red", "trainer_name": "Alice",
                    "ot_id": "30B8", "has_pokeballs": True, "party": [], "artifact_kind": "overlay"})
        assert srv.state.artifact_kind == "overlay"
        reply = await send({"event": "hello", "player": "b", "rom_type": "blue", "trainer_name": "Bob",
                            "ot_id": "7B0B", "has_pokeballs": True, "party": []})
        assert _mixed(reply) and "artifact kinds" in srv.state.identity_error["b"]
        reply = await send({"event": "hello", "player": "b", "rom_type": "blue", "trainer_name": "Bob",
                            "ot_id": "7B0B", "has_pokeballs": True, "party": [], "artifact_kind": "overlay"})
        assert not _mixed(reply)
    finally:
        await close()


@pytest.mark.asyncio
async def test_vanilla_pairs_without_artifact_kind_are_unchanged(tmp_path):
    """Gen 3 clients never send artifact_kind: both default to clean and pair as before."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        for pid, ot in (("a", 1), ("b", 2)):
            reply = await send({"event": "hello", "player": pid, "rom_type": "firered",
                                "trainer_name": pid.upper(), "ot_id": str(ot), "has_pokeballs": True,
                                "party": []})
            assert not _mixed(reply)
        assert srv.state.artifact_kind == "clean" and not srv.state.identity_error
    finally:
        await close()


def test_the_committed_artifact_kind_survives_a_restart(tmp_path):
    st = SoulLinkState(data_dir=str(tmp_path))
    st.artifact_kind = "rand"
    st._save()
    assert SoulLinkState.load(data_dir=str(tmp_path)).artifact_kind == "rand"


class TestContractSha1:
    """`rom_contract.json` records each player's full-ROM sha1; a client reporting a
    different one is refused before the table fingerprint is even looked at."""

    def _srv(self, tmp_path, want="a" * 40):
        srv = SLinkServer(data_dir=str(tmp_path))
        srv._rom_contract = {"upr_version": "x", "categories": [],
                             "players": {"a": {"fingerprint": "f" * 64, "rom_sha1": want}}}
        return srv

    def test_a_mismatching_sha1_is_rejected(self, tmp_path):
        v = self._srv(tmp_path)._decide_admission("a", {"rom_sha1": "b" * 40, "rom_content": {}})
        assert v["state"] == "rejected" and "sha1" in v["reason"]

    def test_the_comparison_is_case_insensitive(self, tmp_path):
        """BizHawk reports an uppercase hash; the Manager stores lowercase."""
        v = self._srv(tmp_path)._decide_admission("a", {"rom_sha1": "A" * 40})
        assert "sha1" not in v["reason"]

    def test_a_client_that_reports_no_sha1_falls_through_to_the_fingerprint(self, tmp_path):
        v = self._srv(tmp_path)._decide_admission("a", {})
        assert v["state"] == "rejected" and "did not report its cartridge" in v["reason"]

    def test_a_contract_without_a_sha1_is_unchanged(self, tmp_path):
        v = self._srv(tmp_path, want="")._decide_admission("a", {"rom_sha1": "b" * 40})
        assert "sha1" not in v["reason"]

    def test_no_contract_still_admits_everyone(self, tmp_path):
        srv = SLinkServer(data_dir=str(tmp_path))
        assert srv._decide_admission("a", {"rom_sha1": "b" * 40})["state"] == "admitted"
