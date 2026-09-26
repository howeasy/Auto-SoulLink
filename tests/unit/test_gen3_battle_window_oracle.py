"""Synthetic raw receipts + real codec/flash images, never an emulator."""
from copy import deepcopy

import pytest

from server.adapters import gen3_codec as codec
from tests.unit.test_gen3_codec import _mon
from tests.unit.test_gen3_flash_layout import _image, _write_half
from tools import gen3_battle_window_oracle as oracle

KEY = "00000002:12345678"
ACTIVE = "ab" * 0x58


def blocks(party, boxed=False):
    data = {"sb1": bytearray(codec.SAVEBLOCK1_SIZE), "sb2": bytearray(codec.SAVEBLOCK2_SIZE),
            "storage": bytearray(codec.STORAGE_SIZE)}
    data["sb1"][codec.SB1_PARTY_COUNT_OFFSET] = len(party)
    for slot, mon in enumerate(party):
        at = codec.SB1_PARTY_OFFSET + slot * codec.PARTY_MON_SIZE
        data["sb1"][at:at + codec.PARTY_MON_SIZE] = codec.encode_party_mon(mon)
    if boxed:
        at = codec.BOX_DATA_OFFSET
        data["storage"][at:at + codec.BOX_MON_SIZE] = codec.encode_box_mon(party[-1])
    return data


def example(case="trainer_bench", *, boxed=False, healed=False):
    party = [_mon(1), _mon(2)]
    for mon in party:
        mon["ot_id"], mon["hp"] = 0x12345678, 20
    slot = 1 if case == "trainer_bench" else 0
    key = KEY if slot == 1 else "00000001:12345678"
    fixture = _image((1, blocks(party)), (2, blocks(party)))
    after = deepcopy(party)
    after[slot]["hp"] = 20 if healed else 0
    saved = bytearray(fixture)
    _write_half(saved, 3, blocks(after, boxed))
    ready = (f"READY_BATTLE_WINDOW {case} {key} slot={slot} frame=10 trainer={102 if slot else 0} "
             f"samples=1 active_hex={ACTIVE} in_battle=1 target_hp=20")
    landed = (f"BATTLE_WINDOW_LANDED {case} {key} slot={slot} frame={11 if slot else 200} "
              f"reason={'battle_faint' if slot else 'overworld'} "
              f"address=0x{0x02024284 + slot * 100 + 0x56:08X} len=2 hp=0 "
              f"samples={2 if slot else 123} active_hex={ACTIVE} in_battle={1 if slot else 0} "
              "target_hp=0 trainer_id=102")
    exit_line = f"BATTLE_WINDOW_EXIT {case} {key} frame={20 if slot else 200} outcome={1 if slot else 4}"
    lines = [ready, f"RX force_faint key={key}"]
    if slot:
        lines.insert(0, "PREP_LEVEL before=9 after=13 floor=13 hp=full status=none")
        lines += [landed, exit_line]
    else:
        lines += [f"BATTLE_WINDOW_HELD active_end {key} frames=120 attempted=0",
                  f"BATTLE_WINDOW_EXIT_INPUT active_end {key}", exit_line, landed]
    lines += ["SAVE_WITNESS_DUMP path=patch/build/a.bin bytes=131072 saves=1 frame=300 counter=3",
              f"BATTLE_WINDOW_SAVED {case} {key} slot={slot} hp=0", "WRITES 1", "RESULT: PASS (carrier)"]
    return {"case": case, "key": key, "receipts": {"a": "\n".join(lines) + "\n",
                                                   "b": "WRITES 0\nRESULT: PASS (idle)\n"},
            "fixture": fixture, "witness": bytes(saved), "flushed": bytes(saved),
            "peer_fixture": fixture, "peer_flushed": fixture}


@pytest.mark.parametrize("fault", ["stale_ack", "missing_ready", "late_landed", "boxed_copy",
                                   "healed", "wrong_trainer", "zero_samples"])
def test_first_falsifiers(fault):
    args = example(boxed=fault == "boxed_copy", healed=fault == "healed")
    text = args["receipts"]["a"]
    if fault == "stale_ack":
        text = f'TX sync_retrieve_done {KEY} {{}}\n' + text
    elif fault == "missing_ready":
        text = "\n".join(line for line in text.splitlines() if not line.startswith("READY_"))
    elif fault == "late_landed":
        lines = text.splitlines()
        lines[3], lines[4] = lines[4], lines[3]
        text = "\n".join(lines)
    elif fault == "wrong_trainer":
        text = text.replace("trainer=102", "trainer=330")
    elif fault == "zero_samples":
        text = text.replace("samples=2", "samples=1")
    args["receipts"]["a"] = text
    with pytest.raises(RuntimeError):
        oracle.verify(**args)


def test_complete_receipt_and_independent_save_pass():
    facts = oracle.verify(**example())
    assert facts["witness"]["counter"] == (2, 3)
    assert facts["witness"]["site"] == facts["witness"]["file"]
    assert facts["observed_samples"] > 0
    assert facts["active_unchanged"] is True


def test_active_end_is_no_longer_a_battle_window_case():
    """A2 moved to the P+H carrier (e2e_duo assert_active_end_gen3_saved): the old held-until-
    RUN receipt must not verify here any more."""
    assert set(oracle.CASES) == {"trainer_bench"}
    with pytest.raises(RuntimeError, match="unknown battle-window case"):
        oracle.verify(**example("active_end"))


@pytest.mark.parametrize("case,old,new", [
    ("trainer_bench", "outcome=1", "outcome=2"),
    ("trainer_bench", "trainer_id=102", "trainer_id=330"),
    ("trainer_bench", "len=2", "len=100"),
    ("trainer_bench", "0x0202433E", "0x020242DA"),
    ("trainer_bench", "floor=13", "floor=8"),
    ("trainer_bench", "status=none", "status=poison"),
    ("trainer_bench", "counter=3", "counter=2"),
    ("trainer_bench", "saves=1", "saves=2"),
])
def test_receipt_fields_are_evidence_not_labels(case, old, new):
    args = example(case)
    assert old in args["receipts"]["a"]
    args["receipts"]["a"] = args["receipts"]["a"].replace(old, new)
    with pytest.raises(RuntimeError):
        oracle.verify(**args)


def test_active_record_comparison_uses_both_complete_records():
    args = example()
    lines = args["receipts"]["a"].splitlines()
    lines[3] = lines[3].replace(ACTIVE, "cd" * 0x58)
    args["receipts"]["a"] = "\n".join(lines)
    with pytest.raises(RuntimeError, match="active record changed"):
        oracle.verify(**args)


@pytest.mark.parametrize("line", ["RX force_faint key=OTHER", "SAVE_WITNESS_DUMP path=old",
                                  "BATTLE_WINDOW_HELD other", "TX stats_cache OTHER {}"])
def test_idle_peer_is_not_another_subject(line):
    args = example()
    args["receipts"]["b"] = line + "\n" + args["receipts"]["b"]
    with pytest.raises(RuntimeError):
        oracle.verify(**args)


@pytest.mark.parametrize("which", ["witness", "flushed", "peer_flushed"])
def test_image_integrity_is_checked_from_bytes(which):
    args = example()
    image = bytearray(args[which])
    image[-1] ^= 1
    args[which] = bytes(image)
    with pytest.raises(RuntimeError):
        oracle.verify(**args)


def test_old_hook_image_is_not_a_new_save_even_with_a_fresh_marker():
    args = example()
    args["witness"] = args["flushed"] = args["fixture"]
    with pytest.raises(RuntimeError):
        oracle.verify(**args)


def loss_receipts():
    args = example()
    lines = [line for line in args["receipts"]["a"].splitlines()
             if not line.startswith(("SAVE_WITNESS", "BATTLE_WINDOW_SAVED", "RESULT:"))]
    lines = [line.replace("outcome=1", "outcome=2") for line in lines]
    lines.append("RESULT: FAIL (T2_RNG_LOSS: lead fainted to Rick after the SLink write landed)")
    return {"a": "\n".join(lines), "b": "RESULT: FAIL (battle-window partner did not PASS)"}


def test_post_write_rng_loss_earns_only_one_retry_and_never_passes():
    receipts = loss_receipts()
    for attempt, retry in [(1, True), (2, False), (3, False)]:
        result = oracle.classify_failure(case="trainer_bench", key=KEY, receipts=receipts, attempt=attempt)
        assert result["status"] == "NOT_SUBJECT" and result["retry"] is retry
        args = example()
        args["receipts"] = receipts
        with pytest.raises(oracle.NotSubject) as caught:
            oracle.verify(**args, attempt=attempt)
        assert caught.value.retry is retry


def test_preparation_failure_does_not_earn_rng_retry():
    receipts = loss_receipts()
    receipts["a"] = "RESULT: FAIL (T2_RNG_LOSS: preparation failed)"
    assert oracle.classify_failure(case="trainer_bench", key=KEY, receipts=receipts) is None


@pytest.mark.parametrize("kind", ["moved", "duplicate"])
def test_final_decode_requires_exactly_one_target_in_original_slot(kind):
    args = example()
    party = codec.party_from_save(args["flushed"], rr=False)
    party = list(reversed(party)) if kind == "moved" else [party[1], party[1]]
    saved = bytearray(args["fixture"])
    _write_half(saved, 3, blocks(party))
    args["witness"] = args["flushed"] = bytes(saved)
    with pytest.raises(RuntimeError, match="missing/duplicated/moved"):
        oracle.verify(**args)


def test_uses_callers_receipt_collector(monkeypatch):
    from tools import e2e_duo

    consumed = []
    monkeypatch.setattr(e2e_duo, "_CONSUMED_MARKERS", consumed)
    oracle.verify(**example(), helpers=e2e_duo)
    assert any("READY_BATTLE_WINDOW" in line for _, line in consumed)
    assert any("BATTLE_WINDOW_SAVED" in line for _, line in consumed)
