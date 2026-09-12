"""Multi-event checks of actual composed source handlers; no emulator or root hook mocks."""

import secrets

import pytest

from server.gen1_frame_journal import RETURNS, returned
from server.gen1_npc_exchange_runtime import verify_journal as verify_exchanges
from server.gen1_run_config import create_runtime
from server.protocol_journal import JournalError
from server.state import AreaStatus
from tests.unit.test_gen1_atomic_frame_settlement import frame, window
from tests.unit.test_gen1_engine_signal_runtime import payload as engine_payload
from tests.unit.test_gen1_faint_runtime import bag
from tests.unit.test_gen1_frame_acquisitions import checkpoint, commit, party_blobs, source, start
from tests.unit.test_gen1_frame_source_receipts import SNORLAX, battle_end, origin, settle, wild
from tests.unit.test_gen1_npc_exchange_runtime import exchange
from tests.unit.test_gen1_sessions import contract


@pytest.mark.parametrize("variants", [("red", "blue"), ("blue", "yellow"), ("yellow", "yellow")])
def test_failed_static_spends_its_own_area_without_spending_the_wild_route(tmp_path, variants):
    from server.gen1_static_receipt import DATA
    from server.protocol import digest

    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        start(runtime)
        static = DATA["titles"][variants[0]]["sites"][SNORLAX]
        operands = {
            "map_id": static["map_id"],
            "species_index": static["species"]["clean"][0],
            "level": static["level"]["values"][0],
            "cur_opponent": static["species"]["clean"][0],
        }
        rows = [
            origin(runtime, "a", arm=125, began=130),
            wild(runtime, "a", "begin", frame=130, **operands),
            battle_end(runtime, "a", frame=150, result=2),
            wild(runtime, "a", "end", frame=150, **operands),
        ]
        point = checkpoint(runtime, "a", [], 160)
        engine = engine_payload(runtime, "a", [], 1)
        engine["signals"] = [bag(variants[0])]
        window(runtime, "a", frames=60)
        message = frame(runtime, "a", point, engine)
        message["bundle"]["acquisitions"] = rows
        message["receipt"]["observations_digest"] = digest(message["bundle"])
        returned(runtime, "a", secrets.token_hex(16), message, settle_observations=True)
        from server.adapters.gen1_rby import _MAP_ID_TO_AREA

        state = runtime.state().rules
        assert state.area_states.get(SNORLAX) == AreaStatus.DEAD_ZONE
        assert (
            state.area_states.get(_MAP_ID_TO_AREA[static["map_id"]], AreaStatus.UNSEEN)
            == AreaStatus.UNSEEN
        )
    finally:
        runtime.close()


@pytest.mark.parametrize("sparse", [False, True], ids=["settled", "pending"])
def test_npc_exchange_reopen_audit_requires_the_earlier_consumed_call_window(tmp_path, sparse):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        start(runtime)
        gift = source(runtime, "a", "grant:game_corner_purchase:0", slot=0)
        settle(runtime, "a", [gift], after=140)
        party = party_blobs(gift["receipt"]["return"]["point"]["party_hex"])
        _, _, prior = commit(runtime, "a", [], after=180, sparse=True)
        commit(runtime, "a", [], after=220, sparse=True)
        outgoing = exchange(runtime, "a", party, slot=0, frames=(170, 175, 250), level=party[0][33])
        if sparse:
            point = checkpoint(
                runtime, "a", [], 260, party=outgoing["receipt"]["return"]["point"]["party_hex"]
            )
            commit(runtime, "a", [outgoing], after=260, sparse=True, point=point)
        else:
            settle(runtime, "a", [outgoing], after=260)
        stage = runtime.state()
        verify_exchanges(runtime.journal, stage)
        runtime.journal._db.execute(
            "DELETE FROM records WHERE namespace=? AND record_key=?",
            (RETURNS, prior["closed_frame_digest"][:32]),
        )
        with pytest.raises(JournalError):
            verify_exchanges(runtime.journal, stage)
    finally:
        runtime.close()
