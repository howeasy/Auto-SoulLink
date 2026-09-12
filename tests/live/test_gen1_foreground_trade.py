"""Actual main-loop trade entry; the coordinator/receptionist remain unbound."""
import copy
import json
import os
from pathlib import Path

import pytest

from server.gen1_native_trade_receipts import verify_native_trade_receipt
from server.gen1_party_codec import PartyCodec
from server.gen1_trade_result import TradeResultRules
from server.protocol_journal import JournalError
from tests.live.test_gen1_native_trade import trade_cases
from tools.build_gen1_native_trade import build
from tools.run_gb_gate import run_gate

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required")]


def verify_durable_result(result, artifact, confirmed_command=None):
    assert result["journal_reopened"]
    saved = json.loads(Path(result["command_journal_path"]).read_text())
    state = saved["document"]["payload"]
    entry = confirmed_command if confirmed_command is not None else state["inbox"][0]
    receipt = entry["receipt"]["native"] if confirmed_command is not None else entry["receipt"]
    if confirmed_command is not None:
        assert state["version"] == "slink-client-journal-v2" and not state["outbox"] and not state["inbox"]
        assert state["command_floor"] >= entry["command_sequence"]
        assert state["observation"]["gen1_native_applied"]["command_id"] == entry["command_id"]
    assert receipt == result["durable_receipt"] and entry["outcome"] == "ACK"
    rules = TradeResultRules.from_rom(artifact["variant"], (ROOT/artifact["output"]).read_bytes(), expected_sha1=artifact["final_sha1"])
    verified = verify_native_trade_receipt(entry, receipt, rules=rules, boxed_keys=())
    assert verified.command_id == entry["command_id"] and not verified.save_file_verified
    # Replayable/equal party bytes alone must not bypass native or command proof.
    for field, value in (("counts", {}), ("command_id", "f"*32), ("prepared_digest", "f"*64),
                         ("context_generation", "f"*32), ("save_file_verified", True)):
        wrong = copy.deepcopy(receipt)
        wrong[field] = value
        with pytest.raises(JournalError):
            verify_native_trade_receipt(entry, wrong, rules=rules, boxed_keys=())
    return verified


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_trade_enters_from_real_delayframe_and_preserves_borrowed_scratch_and_caller(variant):
    artifact = build(variant, foreground=True)
    case = next(row for row in trade_cases(variant) if row["id"] == "evolve-dex93")
    (ROOT / f".cache/foreground-trade-{variant}.json").write_text(json.dumps(case), encoding="utf-8")
    output = ROOT / f".cache/foreground-trade-result-{variant}.json"
    output.unlink(missing_ok=True)
    passed, path, log = run_gate("lua/tests/test_gen1_foreground_trade_gate.lua",
                                  rom_key=variant+"_foreground_trade", timeout=90, quiet=True)
    assert passed, f"{path}\n{log[-7000:]}"
    result = json.loads(output.read_text())
    verify_durable_result(result, artifact)
    assert result["final_sha1"] == artifact["final_sha1"]
    assert not result["direct_cpu_redirect"] and not result["runtime_ready"]
    assert result["union_restored"] and result["counts"]["service"] == 1 and result["frames"] > 2000
    codec = PartyCodec(variant)
    after = codec.validate_party([bytes.fromhex(raw) for raw in result["party"]])
    assert [mon.raw.hex().upper() for mon in after[:-1]] == [raw for slot, raw in enumerate(case["party"]) if slot != case["slot"]]
    incoming = codec.validate_blob(bytes.fromhex(case["incoming"]))
    assert after[-1].key == incoming.key[:-2] + f'{case["evolved_species"]:02X}'
    assert after[-1].moves == incoming.moves and after[-1].pp == incoming.pp
    assert after[-1].nickname == incoming.nickname and after[-1].ot_name == incoming.ot_name


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_identical_party_bytes_still_execute_original_animation_before_completion(variant):
    artifact = build(variant, foreground=True)
    case = next(row for row in trade_cases(variant) if row["id"] == "identical-transfer-count1-slot0")
    (ROOT / f".cache/foreground-trade-{variant}.json").write_text(json.dumps(case), encoding="utf-8")
    output = ROOT / f".cache/foreground-trade-result-{variant}.json"
    output.unlink(missing_ok=True)
    passed, path, log = run_gate("lua/tests/test_gen1_foreground_trade_gate.lua",
                                 rom_key=variant + "_foreground_trade", timeout=90, quiet=True)
    assert passed, f"{path}\n{log[-7000:]}"
    result = json.loads(output.read_text())
    verify_durable_result(result, artifact)
    assert result["final_sha1"] == artifact["final_sha1"]
    assert result["party"] == case["party"]
    assert result["counts"]["InternalClockTradeAnim"] == 1 and result["counts"]["SavePartyAndDexData"] == 1
    assert result["counts"]["service"] == 1 and result["frames"] > 2000
    assert result["union_restored"] and not result["direct_cpu_redirect"]
    assert not result["runtime_ready"]
    (ROOT / f".cache/foreground-identical-party-{variant}.json").write_text(json.dumps(result, indent=2) + "\n")


@pytest.mark.parametrize("fault", ["reload_after_arm", "stale_context_after_arm", "receipt_store_failure"])
def test_durable_native_interruption_never_reapplies_an_ambiguous_trade(fault):
    artifact = build("yellow", foreground=True)
    case = next(row for row in trade_cases("yellow") if row["id"] == "identical-transfer-count1-slot0")
    case["client_fault"] = fault
    spec = ROOT / f".cache/native-client-{fault}-input.json"
    output = ROOT / f".cache/native-client-{fault}-result.json"
    spec.write_text(json.dumps(case), encoding="utf-8")
    output.unlink(missing_ok=True)
    passed, path, log = run_gate("lua/tests/test_gen1_foreground_trade_gate.lua",
        rom_key="yellow_foreground_trade", timeout=90, quiet=True,
        extra_env={"SLINK_NATIVE_SPEC": str(spec), "SLINK_NATIVE_RESULT": str(output)})
    assert passed, f"{path}\n{log[-7000:]}"
    result = json.loads(output.read_text())
    assert result["fault"] == fault and result["final_sha1"] == artifact["final_sha1"]
    if fault == "receipt_store_failure":
        verify_durable_result(result, artifact)
        assert result["counts"]["service"] == result["counts"]["InternalClockTradeAnim"] == 1
    else:
        assert result["recovery_required"] and not result["receipt"]
        assert result["additional_writes"] == result["native_frames"] == 0
