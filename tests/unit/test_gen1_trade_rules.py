"""TradeCoordinator policy binding to complete production Gen1 rule documents."""
import copy
from dataclasses import asdict

import pytest

from server.adapters import get_adapter
from server.gen1_staged_state import StagedGen1State
from server.gen1_trade_rules import Gen1TradeRules
from server.identity_registry import IdentityWitness, MigrationWitness
from server.protocol_journal import JournalError
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_trade_coordinator import Run


def snapshot(mon, context):
    return {"schema": "gen1-party-readback-v1", "variant": "yellow", "save_id": context.save_identity.ot_id,
        "save_name": context.save_identity.trainer_name, "party_count": 1, "party": [mon.raw.hex().upper()],
        "species_list": [mon.species_index, 255], "battle_flag": 0, "active_slot": None, "battle_hp": None}


@pytest.fixture
def setup(tmp_path, request):
    run = Run(tmp_path, ("yellow", "yellow"), identical=True, evolution=getattr(request, "param", False))
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type="yellow"))
    state.rom_type = "yellow"
    state.player_identity = {p: asdict(context.save_identity) for p, context in run.contexts.items()}
    observations, halves = {}, {}
    for p in ("a", "b"):
        mon = run.policy.rules[p].codec.validate_blob(bytes.fromhex(run.original["rules"]["parties"][p][0]))
        observations[p] = snapshot(mon, run.contexts[p])
        halves[p] = MonInfo(mon.key, mon.level, mon.species_id, p.upper())
        state.party_keys[p] = {mon.key}
        state.party_size[p] = 1
        state._ingest_party_blobs(p, [{"slot": 0, "key": mon.key, "level": mon.level,
            "species_id": mon.species_id, "blob_hex": mon.raw.hex()}])
    entry = LinkEntry("oaks_lab", halves["a"], halves["b"], LinkStatus.ALIVE)
    state.links.append(entry)
    state._index_entry(entry)
    state.area_states = {"oaks_lab": AreaStatus.LINKED, "route_2": AreaStatus.DEAD_ZONE}
    state.rival_team_swap = True
    document = StagedGen1State.from_live(state, {"retired_pairs": []}).document()
    from server.identity_registry import IdentityRegistry
    registry = IdentityRegistry.restore(run.original["identities"], run_id=run.journal.run_id)
    binding = Gen1TradeRules(run.policy.rules, data_dir=tmp_path)
    yield run, binding, document, registry, observations
    run.journal.close()


def proposal(data, document=None, observations=None):
    run, binding, original, registry, snapshots = data
    key = original["core"]["links"][0]["a"]["key"]
    return binding.proposal(document or original, registry, player="a", key=key, contexts=run.contexts,
        snapshots=observations or snapshots)


@pytest.mark.parametrize("change", ["boxed", "dead", "memorial", "disabled", "pending_write", "save", "moved_blob"])
def test_ineligible_or_changed_party_cannot_become_a_trade(setup, change):
    run, binding, original, registry, observations = setup
    document, snapshots = copy.deepcopy(original), copy.deepcopy(observations)
    key = document["core"]["links"][0]["a"]["key"]
    if change == "boxed":
        document["runtime"]["party_keys"]["a"] = []
    elif change == "dead":
        document["core"]["links"][0]["status"] = "dead"
    elif change == "memorial":
        document["core"]["pending_memorials"]["a"] = [key]
    elif change == "disabled":
        document["core"]["rules"]["pc_trade_npc"] = False
    elif change == "pending_write":
        document["runtime"]["queued_commands"]["a"] = [{"cmd": "force_faint", "key": key}]
    elif change == "save":
        snapshots["a"]["save_id"] = "FFFF"
    else:
        raw = bytearray.fromhex(snapshots["a"]["party"][0])
        raw[1:3] = (1).to_bytes(2, "big")
        snapshots["a"]["party"][0] = raw.hex().upper()
    before = copy.deepcopy(document)
    with pytest.raises(JournalError):
        proposal(setup, document, snapshots)
    assert document == before and setup[2] == original


def finalization(data):
    run, _, _, _, observations = data
    prepared = proposal(data).document()
    migrations = []
    applied = {}
    for p in ("a", "b"):
        peer = "b" if p == "a" else "a"
        sender = prepared["participants"][peer]
        raw = bytes.fromhex(observations[peer]["party"][0])
        mon = run.policy.rules[p].codec.validate_blob(run.policy.rules[p].outcomes(raw)[0].blob)
        migrations.append(MigrationWitness(sender["member_id"], run.contexts[peer], sender["key"], sender["evidence_digest"],
            IdentityWitness(run.contexts[p], mon.key, mon.sha256, 1)))
        applied[p] = {"after": {"party": snapshot(mon, run.contexts[p])}}
    return {"phase": "both_verified", "verified": {"a": {}, "b": {}}, "applied": applied, "proposal": prepared}, migrations


def test_full_rule_finalization_is_detached_preserves_unrelated_rules_and_swaps_scoped_halves(setup):
    _, binding, document, _, _ = setup
    before = copy.deepcopy(document)
    trade, migrations = finalization(setup)
    after = binding.finalize(document, trade, migrations)
    assert document == before
    assert after["core"]["links"][0]["a"]["nickname"] == "B"
    assert after["core"]["links"][0]["b"]["nickname"] == "A"
    assert after["core"]["rules"] == before["core"]["rules"]
    assert after["core"]["area_states"] == before["core"]["area_states"]
    assert after["memorial"] == before["memorial"]
    assert after["runtime"]["queued_commands"] == {"a": [], "b": []}
    assert len(after["core"]["mon_stats"]) == 2  # even though the raw keys are equal


@pytest.mark.parametrize("setup", [True], indirect=True)
def test_trade_evolution_updates_full_rule_keys_species_stats_and_blob_cache(setup):
    run, binding, document, _, _ = setup
    trade, migrations = finalization(setup)
    result = binding.finalize(document, trade, migrations)
    restored = StagedGen1State.restore(result, data_dir=binding.data_dir)
    for witness in migrations:
        player = witness.after.context.player
        half = getattr(restored.links[0], player)
        blob = restored.partner_blobs[player][-1]["blob"]
        mon = run.policy.rules[player].codec.validate_blob(blob)
        assert half.key == mon.key == witness.after.key
        assert half.species == mon.species_id and half.level == mon.level
        assert restored.stats_for(player, half.key)["maxHP"] == mon.max_hp
        assert half.key in restored.party_keys[player]
        assert restored.find_link(player, trade["proposal"]["participants"][player]["key"]) is None


@pytest.mark.parametrize("change", ["unverified", "missing_migration", "stale_link", "bad_after"])
def test_finalize_refuses_incomplete_or_stale_results_without_changing_rules(setup, change):
    _, binding, document, _, _ = setup
    trade, migrations = finalization(setup)
    document = copy.deepcopy(document)
    if change == "unverified":
        trade["phase"] = "both_applied"
    elif change == "missing_migration":
        migrations.pop()
    elif change == "stale_link":
        document["core"]["links"][0]["status"] = "dead"
    else:
        trade["applied"]["a"]["after"]["party"]["party_count"] = 2
    before = copy.deepcopy(document)
    with pytest.raises(JournalError):
        binding.finalize(document, trade, migrations)
    assert document == before
