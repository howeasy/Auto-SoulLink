"""Ordinary evolution through actual saved/frame/source/identity/storage handlers."""

import copy
import secrets

import pytest

from server import event_reference
from server.gen1_evolution_runtime import COMPONENT, decode_receipts, verify_journal
from server.gen1_full_save import SYMBOLS
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol_journal import JournalError
from tests.unit.test_gen1_atomic_frame_settlement import starters
from tests.unit.test_gen1_capture_receipt import party_bytes
from tests.unit.test_gen1_evolution_receipt import receipt as evolution_receipt
from tests.unit.test_gen1_frame_acquisitions import checkpoint, commit, party_blobs
from tests.unit.test_gen1_grant_receipt import receipt as grant_receipt
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_storage_runtime import complete_storage


def paired_eevees(runtime):
    starters(runtime)
    for player in ("a", "b"):
        variant = runtime.contract["players"][player]["variant"]
        raw = grant_receipt(
            variant,
            "grant:eevee:0",
            existing=1,
            boxed_before=0,
            ot_id="0000",
            dv=0x3100 + ord(player),
        )
        raw.update(
            context_generation=player * 32,
            physical_instance=("1" if player == "a" else "2") * 32,
            final_sha1=runtime.contract["players"][player]["final_rom_sha1"],
        )
        before = [item["blob"] for item in runtime.state().rules.partner_blobs[player]]
        added = party_blobs(raw["return"]["point"]["party_hex"])[-1]
        raw["call"]["point"]["party_hex"] = party_bytes(before).hex().upper()
        raw["return"]["point"]["party_hex"] = party_bytes(before + [added]).hex().upper()
        raw["call"]["frame"] = 120
        raw["return"]["frame"] = 130
        point = checkpoint(runtime, player, [], 140, party=raw["return"]["point"]["party_hex"])
        row = {"kind": "grant", "receipt": raw}
        commit(runtime, player, [row], point=point, after=140)
        complete_storage(runtime)
    return next(link for link in runtime.state().rules.links if link.area_id != "oaks_lab")


def evolution(runtime, player="a", *, outcome="evolved", frame=150):
    point = checkpoint(runtime, player, [], frame + 30)
    physical = getattr(runtime, "test_storage_physical", {}).get(player, point["source"])
    point["source"] = copy.deepcopy(physical)
    variant = physical["variant"]
    party = party_blobs(physical["fields"]["party"])
    slot = next(i for i, blob in enumerate(party) if blob[0] == 102)  # Eevee internal index
    raw = evolution_receipt(
        variant, party=party, slot=slot, blob=party[slot], outcome=outcome, frame=frame
    )
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]
    main = bytes.fromhex(physical["fields"]["main"])
    for witness in ("before", "after"):
        raw[witness]["point"]["box_hex"] = physical["fields"]["box"]
        raw[witness]["point"]["current_box"] = main[
            symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]
        ]
        raw[witness]["point"]["map_id"] = main[symbols["wCurMap"] - symbols["wMainDataStart"]]
    before = bytes.fromhex(raw["before"]["point"]["dex_hex"])
    after = bytes.fromhex(raw["after"]["point"]["dex_hex"])
    raw["before"]["point"]["dex_hex"] = main[:38].hex().upper()
    raw["after"]["point"]["dex_hex"] = (
        bytes(old | (a & ~b) for old, a, b in zip(main[:38], after, before, strict=True))
        .hex()
        .upper()
    )
    raw.update(
        context_generation=player * 32,
        physical_instance=("1" if player == "a" else "2") * 32,
        final_sha1=runtime.contract["players"][player]["final_rom_sha1"],
    )
    point["source"]["fields"]["party"] = raw["after"]["point"]["party_hex"]
    point["source"]["fields"]["main"] = (
        raw["after"]["point"]["dex_hex"] + physical["fields"]["main"][76:]
    )
    return {"kind": "evolution", "receipt": raw}, point


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue")])
@pytest.mark.parametrize("sparse", [False, True])
def test_evolution_preserves_member_link_area_and_ordinals_through_real_frame_and_reopen(
    tmp_path, variants, sparse
):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        pair = paired_eevees(runtime)
        area = pair.area_id
        old = pair.a.key
        peer = copy.deepcopy(pair.b)
        before = runtime.state().document()
        identities = before["identities"]
        ordinals = copy.deepcopy(before["components"]["gen1-acquisition-ordinals"])
        row, point = evolution(runtime)
        operation, message, _ = commit(runtime, "a", [row], after=180, point=point, sparse=sparse)
        state = runtime.state()
        entry = state.document()["components"][COMPONENT]["a"]
        result = entry["settled"][-1]
        new = result["fact"]["incoming"]["key"]
        pair = state.rules.find_link("a", new)
        assert (
            pair
            and pair.area_id == area
            and pair.b == peer
            and state.rules.find_link("a", old) is None
        )
        assert old not in state.rules.party_keys["a"] and new in state.rules.party_keys["a"]
        assert state.document()["identities"]["acquisitions"] == identities["acquisitions"]
        assert set(state.document()["identities"]["members"]) == set(identities["members"])
        assert state.document()["identities"]["links"] == identities["links"]
        assert state.document()["components"]["gen1-acquisition-ordinals"] == ordinals
        assert entry["frame_origin"] == event_reference.make("a", operation, message)
        if sparse:
            # Source completion migrates while overworld inventory is absent.
            assert (
                state.document()["components"]["gen1-inventory-observations"]["a"]["observation"][
                    "frame"
                ]
                == 140
            )
            point["frame"] = 190
            commit(runtime, "a", [], after=190, point=point)
        snapshot = runtime.journal.snapshot()
        from server.gen1_frame_journal import returned

        assert returned(runtime, "a", operation, message, settle_observations=True)[
            "evolution_digest"
        ]
        assert runtime.journal.snapshot() == snapshot
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        verify_journal(reopened.journal, reopened.state())
    finally:
        reopened.close()


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


def test_cancelled_level_evolution_records_source_but_creates_no_migration(tmp_path):
    from server.gen1_party_codec import PartyCodec
    from tests.unit.test_gen1_party_codec import make_blob

    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        starters(runtime)
        before = runtime.state().document()
        point = checkpoint(runtime, "a", [], 150)
        previous = party_blobs(point["source"]["fields"]["party"])[0]
        blob = bytearray(
            make_blob(
                PartyCodec("red"),
                species=previous[0],
                level=16,
                otid=0,
                dv=int.from_bytes(previous[27:29], "big"),
            )
        )
        blob[44:66] = previous[44:66]
        raw = evolution_receipt(
            "red", party=[bytes(blob)], blob=bytes(blob), outcome="cancelled", frame=120
        )
        raw["before"]["point"]["box_hex"] = raw["after"]["point"]["box_hex"] = point["source"][
            "fields"
        ]["box"]
        point["source"]["fields"]["party"] = raw["after"]["point"]["party_hex"]
        commit(runtime, "a", [{"kind": "evolution", "receipt": raw}], point=point, after=150)
        after = runtime.state().document()
        entry = after["components"][COMPONENT]["a"]["settled"][0]
        assert entry["rule"] == "cancelled" and entry["migration_id"] is None
        assert after["identities"] == before["identities"]
        assert after["rules"]["core"]["links"] == before["rules"]["core"]["links"]
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["incoming", "collision", "duplicate_after_first_migration"])
def test_bad_evolution_publication_rolls_back_the_whole_frame_identity_and_rules(tmp_path, fault):
    from server.gen1_frame_journal import returned
    from tests.unit.test_gen1_atomic_frame_settlement import window
    from tests.unit.test_gen1_capture_receipt import box_bytes
    from tests.unit.test_gen1_frame_acquisitions import message

    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        paired_eevees(runtime)
        row, point = evolution(runtime)
        raw = row["receipt"]
        slot = raw["before"]["point"]["slot"]
        if fault == "incoming":
            changed = bytearray.fromhex(raw["after"]["point"]["party_hex"])
            changed[8 + 44 * slot + 27] ^= 1
            raw["after"]["point"]["party_hex"] = changed.hex().upper()
        elif fault == "collision":
            incoming = party_blobs(raw["after"]["point"]["party_hex"])[slot]
            box = box_bytes([incoming[:33] + incoming[44:]]).hex().upper()
            raw["before"]["point"]["box_hex"] = raw["after"]["point"]["box_hex"] = box
        window(runtime, "a", frames=60)
        before = runtime.journal.snapshot()
        rows = [row, row] if fault == "duplicate_after_first_migration" else [row]
        with pytest.raises(JournalError):
            returned(
                runtime,
                "a",
                secrets.token_hex(16),
                message(runtime, "a", rows, after=180, point=point),
                settle_observations=True,
            )
        assert runtime.journal.snapshot() == before
        assert COMPONENT not in runtime.state().document()["components"]
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
            "a", "e" * 32, {"event": "frame_complete", "bundle": {"acquisitions": rows}}
        )
        facts = decode_receipts(rows, initial, reference)
        assert (
            len(facts) == 1
            and facts[0]["source_ref"]["index"] == 1
            and facts[0]["source_ref"]["event"] == reference
        )
    finally:
        runtime.close()
