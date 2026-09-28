"""A paused Gen 3 rival swap refuses once without staging native work."""

import pytest

from tests.unit.test_gen3_client import (
    battle_identity, mb_op, native_writes, pre_announced, ready_battle,
    trade_world, viable_blobs,
)


@pytest.fixture(autouse=True)
def _nonce(monkeypatch):
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")


def _paused_request(w, trainer_id, session, battle_id):
    writes_before = list(w.writes)
    native_before = list(native_writes(w))
    w.client.writes_enabled, w.client.gate_revoked = False, True
    w.command(cmd="replace_rival_team", trainer_id=trainer_id, n=1,
              blobs_hex=viable_blobs(w), session=session, battle_id=battle_id)
    w.step(3)
    (reply,) = w.events("rival_team_replaced")
    assert (reply["trainer_id"], reply["species_ids"], reply["error"]) == (
        trainer_id, [], "writes_paused"
    )
    assert w.writes == writes_before and native_writes(w) == native_before
    assert mb_op(w) == 0
    w.client.writes_enabled, w.client.gate_revoked = True, False
    w.step(3)
    assert len(w.events("rival_team_replaced")) == 1
    assert w.writes == writes_before and native_writes(w) == native_before
    assert mb_op(w) == 0


def test_preannounced_valid_identity_refuses_once_while_paused():
    w, _ = trade_world()
    announcement = pre_announced(w)
    _paused_request(w, 331, announcement["session"], announcement["battle_id"])


def test_in_battle_valid_identity_refuses_once_while_paused():
    w, _ = trade_world()
    ready_battle(w, 5)
    session, battle_id = battle_identity(w)
    _paused_request(w, 5, session, battle_id)
