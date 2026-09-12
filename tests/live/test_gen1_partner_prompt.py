"""Partner's cartridge-native YES/NO prompt from a verified overworld checkpoint."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from server.gen1_party_codec import PartyCodec
from tests.live.test_gen1_receptionist import party, text_charmap
from tests.unit.test_gen1_party_codec import make_blob
from tools.build_gen1_native_trade import ROOT, build
from tools.gen1_receptionist_fixture import make_fixture
from tools.run_gb_gate import run_gate

pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required")]


def prompt_cases(variant):
    incoming = make_blob(PartyCodec(variant), otid=0xBEEF, dv=0x4321).hex().upper()
    base = {"answer": "yes", "result": 0, "party": party(variant), "slot": 1, "incoming": incoming}
    cases = [{"id": answer, "answer": answer, "result": result, "party": party(variant), "slot": 1,
              "incoming": incoming, "screenshot": True}
             for answer, result in (("yes", 0), ("no", 1), ("cancel", 1))]
    for count in range(1, 7):
        for slot in range(count):
            cases.append({**base, "id": f"count{count}-slot{slot}", "party": party(variant, count), "slot": slot})
    for button in ("A", "B"):
        cases.append({**base, "id": "held-" + button, "hold_open": button})
    cases.append({**base, "id": "selected-fainted", "party": party(variant, fainted=1), "result": 3})
    cases.append({**base, "id": "selected-absent", "slot": 3, "result": 3})
    raw = bytearray.fromhex(incoming)
    raw[55:66] = b"\x4f" * 11
    cases.append({**base, "id": "unreadable-incoming-name", "incoming": raw.hex().upper(), "result": 3})
    raw = bytearray.fromhex(incoming)
    raw[1:3] = b"\0\0"
    cases.append({**base, "id": "incoming-fainted", "incoming": raw.hex().upper(), "result": 3})
    members = list(base["party"])
    raw = bytearray.fromhex(members[1])
    raw[55:66] = b"\x80" * 11
    members[1] = raw.hex().upper()
    cases.append({**base, "id": "unreadable-selected-name", "party": members, "result": 3})
    fields = [("wIsInBattle", 1), ("wLinkState", 0x32), ("hSerialConnectionStatus", 2),
              ("wEnteringCableClub", 1), ("wEnemyPartyCount", 2)]
    if variant == "yellow":
        fields.append(("wPrinterConnectionOpen", 1))
    for field, value in fields:
        cases.append({**base, "id": "guard-" + field, "refusal": [{"field": field, "value": value}], "result": 3})
    charmap = text_charmap(variant)

    def encoded(text):
        return bytes(charmap[char] for char in text)

    def nickname(raw):
        return bytes.fromhex(raw)[55:66].split(b"\x50", 1)[0]

    for case in cases:
        if case["result"] != 3:
            case["question_lines"] = [
                (encoded("Trade ") + nickname(case["party"][case["slot"]])).hex().upper(),
                (encoded("for ") + nickname(case["incoming"]) + encoded("?")).hex().upper(),
            ]
    return cases


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("location", ["town", "ViridianPokecenter", "IndigoPlateauLobby"])
def test_partner_uses_native_yes_no_without_mutation_and_restores_overworld(variant, location):
    artifact = build(variant, receptionist=True)
    directory = Path(tempfile.mkdtemp(prefix=f"partner-prompt-{variant}-{location}-", dir=ROOT / ".cache"))
    cases = prompt_cases(variant)
    output = directory / "observed.json"
    config = {"variant": variant, "manifest": artifact, "cases": cases, "output": str(output).replace("\\", "/")}
    fixture = None
    if location != "town":
        config["fixture"] = make_fixture(variant, location, directory)
        fixture = config["fixture"]["fixture"]
    path = directory / "input.json"
    path.write_text(json.dumps(config, indent=2) + "\n")
    passed, verdict, log = run_gate("lua/tests/test_gen1_partner_prompt_gate.lua",
        rom_key=variant + "_receptionist_trade", timeout=75, quiet=True,
        fixture_override=fixture, extra_env={"SLINK_PARTNER_PROMPT_INPUT": str(path)})
    (directory / "gate.txt").write_text(log, encoding="utf-8")
    assert passed, f"{directory}\n{verdict}\n{log[-7000:]}"
    observed = json.loads(output.read_text())
    assert observed["passed"] and observed["final_sha1"] == artifact["final_sha1"]
    assert [row["id"] for row in observed["cases"]] == [row["id"] for row in cases]
    assert [row["result"] for row in observed["cases"]] == [row["result"] for row in cases]
    assert not observed["runtime_ready"] and not observed["direct_cpu_redirect"]
    observed["evidence"] = str(directory.relative_to(ROOT))
    (ROOT / f".cache/partner-prompt-{variant}-{location}.json").write_text(json.dumps(observed, indent=2) + "\n")
