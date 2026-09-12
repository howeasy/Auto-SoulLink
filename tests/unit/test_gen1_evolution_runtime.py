"""Ordinary evolution through the private standalone handler and its decoder.

The compound-frame route (evolution rows settled inside a frame bundle) retired with the
frame-credit loop; observation batches refuse evolution rows fail-closed until P10 section 5
wires them, so only the unframed handler and the decoder are exercised here.
"""

import secrets

from server import event_reference
from server.gen1_evolution_runtime import COMPONENT, decode_receipts
from server.gen1_run_config import create_runtime
from tests.unit.observation_fixture import party_blobs, starters
from tests.unit.test_gen1_evolution_receipt import receipt as evolution_receipt
from tests.unit.test_gen1_sessions import contract


def test_pending_acquisition_evolution_keeps_its_area_identity_and_unusable_mask(tmp_path):
    """Private unframed source handlers isolate pending rule preservation before disposition."""
    from server.gen1_evolution_runtime import EVENT, SCHEMA, record
    from tests.unit.test_gen1_acquisition_runtime import (
        checkpoint as stable,
        enroll,
        grant,
        observe,
    )

    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        owner, initial, first = enroll(runtime, "a")
        enroll(runtime, "b")
        grant_row = grant(runtime, "a", "grant:eevee:0")
        observe(runtime, "a", [grant_row], 1)
        party_hex = grant_row["receipt"]["return"]["point"]["party_hex"]
        stable(runtime, "a", owner, initial, first, party_hex, frame=140)
        observe(runtime, "a", [], 2)
        old = runtime.state().document()
        birth = old["components"]["gen1-acquisition-settlement"]["a"]["settled"][0]
        area = birth["area"]
        key = birth["fact"]["key"]
        assert key not in runtime.state().rules.party_keys["a"]
        party = party_blobs(party_hex)
        raw = evolution_receipt("red", party=party, blob=party[0], frame=150)
        message = {
            "event": EVENT,
            "payload": {
                "schema": SCHEMA,
                "sequence": 1,
                "receipts": [{"kind": "evolution", "receipt": raw}],
            },
        }
        record(runtime, "a", secrets.token_hex(16), message)
        state = runtime.state()
        entry = state.document()["components"][COMPONENT]["a"]["settled"][0]
        assert (
            entry["rule"] == "pending_capture"
            and entry["area"] == area
            and entry["member_id"] == birth["member_id"]
        )
        assert state.rules.pending_captures[area]["a"].key == entry["fact"]["incoming"]["key"]
        assert not state.rules.party_keys["a"] and not state.rules.links
        assert (
            state.document()["components"]["gen1-acquisition-ordinals"]
            == old["components"]["gen1-acquisition-ordinals"]
        )
        assert state.document()["identities"]["acquisitions"] == old["identities"]["acquisitions"]
    finally:
        runtime.close()


def test_mixed_source_decode_preserves_the_original_evolution_row_index(tmp_path):
    from tests.unit.test_gen1_wild_encounter import row as wild_row

    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        starters(runtime)
        initial = runtime.state().document()["components"]["gen1-initial-observations"]["a"]
        evo = evolution_receipt("red", species=153, level=16)
        rows = [wild_row(runtime, "a", "begin", 120), {"kind": "evolution", "receipt": evo}]
        reference = event_reference.make(
            "a", "e" * 32, {"event": "observation", "acquisitions": rows}
        )
        facts = decode_receipts(rows, initial, reference)
        assert (
            len(facts) == 1
            and facts[0]["source_ref"]["index"] == 1
            and facts[0]["source_ref"]["event"] == reference
        )
    finally:
        runtime.close()
