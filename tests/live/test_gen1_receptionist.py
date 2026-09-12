"""Real existing receptionist objects, native input and unchanged pre-trade saves."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import pytest

from server.gen1_party_codec import PartyCodec
from tests.unit.test_gen1_party_codec import make_blob
from tools.build_gen1_native_trade import ROOT, build
from tools.gen1_receptionist_fixture import make_fixture, receptionist_maps
from tools.run_gb_gate import run_gate

pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required")]


def party(variant, count=3, *, fainted=None):
    codec = PartyCodec(variant)
    result = []
    for slot in range(count):
        raw = bytearray(make_blob(codec, dv=0x1000 + slot))
        raw[55:66] = bytes((0x92, 0x8B, 0x8E, 0x93, 0xF7 + slot)) + b"\x50" * 6  # SLOT1..6
        if slot == fainted:
            raw[1:3] = b"\0\0"
        result.append(codec.validate_blob(bytes(raw)).raw.hex().upper())
    return result


def interaction_cases(variant):
    rows = []
    for count in range(1, 7):
        for slot in range(count):
            rows.append({"id": f"count{count}-slot{slot}", "party": party(variant, count),
                         "mask": (1 << count) - 1, "menus": 2, "party_row": slot, "expected_slot": slot})
    base = {"party": party(variant), "mask": 5}
    rows += [
        {**base, "id": "filtered-slot", "menus": 2, "party_row": 1, "expected_slot": 2},
        {**base, "id": "held-opening-A", "menus": 2, "hold_open": True, "expected_slot": 0},
        {**base, "id": "delayed-availability", "menus": 2, "reply_delay": 20, "expected_slot": 0},
        {**base, "id": "cancel-option", "menus": 1, "choice": 2},
        {**base, "id": "cancel-main-B", "menus": 1, "cancel_menu": 1},
        {**base, "id": "cancel-party-B", "menus": 2, "cancel_menu": 2},
        {**base, "id": "no-linked-party", "mask": 0, "menus": 1},
        {**base, "id": "fainted-slot-filtered", "party": party(variant, fainted=0), "menus": 2, "expected_slot": 2},
        {**base, "id": "absent-slots-filtered", "mask": 0x3F, "menus": 2, "party_row": 2, "expected_slot": 2},
    ]
    return rows


def cable_cases(variant):
    base = {"party": party(variant), "mask": 5, "cable": True}
    return [
        {**base, "id": "choose-cable", "choice": 1, "menus": 1},
        *[{**base, "id": reply, "reply": reply, "menus": 0} for reply in
          ("disabled", "missing", "stale", "wrong-generation", "wrong-magic", "wrong-version", "wrong-state", "zero-token")],
        {**base, "id": "invalid-mask", "mask": 0x40, "menus": 0},
    ]

NOTICE_TEXT = {
    "noLinked": ("No linked POKéMON", "in your party."),
    "offerSent": ("Trade offer sent.", "Awaiting partner."),
    "offerRejected": ("Trade unavailable.", "Offer not sent."),
    "offerUnknown": ("Offer status is", "not confirmed."),
    "invalidParty": ("Party data cannot", "be read."),
    "selectionChanged": ("That POKéMON is", "not available."),
}


def offer_cases(variant):
    base = {"party": party(variant), "mask": 5, "menus": 2, "expected_slot": 0}
    return [
        {**base, "id": "offer-confirmed", "expected_notice": "offerSent", "expected_result": 0,
         "screenshot_notice": True},
        {**base, "id": "offer-delayed", "offer_delay": 100, "minimum_offer_frames": 100,
         "expected_notice": "offerSent", "expected_result": 0},
        {**base, "id": "offer-rejected", "offer_reply": "rejected",
         "expected_notice": "offerRejected", "expected_result": 1, "screenshot_notice": True},
        *[{**base, "id": "offer-" + kind, "offer_reply": kind,
           "expected_notice": "offerUnknown", "expected_result": 2, "screenshot_notice": kind == "missing",
           **({"minimum_offer_frames": 180} if kind in ("missing", "stale", "wrong-token") else {})}
          for kind in ("missing", "stale", "wrong-token", "wrong-generation", "wrong-magic", "wrong-version",
                       "wrong-state", "wrong-slot", "invalid-result", "unset-result")],
        {**base, "id": "offer-stale-token-then-current", "offer_reply": "wrong-token", "offer_repair_after": 40,
         "minimum_offer_frames": 40, "expected_notice": "offerSent", "expected_result": 0},
    ]


def invalid_party_cases(variant):
    base = {"party": party(variant), "mask": 5, "menus": 1, "expected_notice": "invalidParty"}
    cases = []
    for name, content in (("empty", b"\x50" * 11), ("unterminated", b"\x80" * 11),
                          ("text-control", b"\x4f\x50" + b"\x50" * 9),
                          ("invalid-glyph", b"\x60\x50" + b"\x50" * 9)):
        members = list(base["party"])
        raw = bytearray.fromhex(members[0])
        raw[55:66] = content
        members[0] = raw.hex().upper()
        cases.append({**base, "id": "nickname-" + name, "party": members})
    # A malformed unlinked name is never interpreted or displayed.
    members = list(base["party"])
    raw = bytearray.fromhex(members[1])
    raw[55:66] = b"\x4f" * 11
    members[1] = raw.hex().upper()
    cases.append({**base, "id": "unlinked-name-not-read", "party": members, "menus": 2,
                  "expected_slot": 2, "party_row": 1, "expected_notice": "offerSent"})
    for kind in ("fainted", "removed", "invalid-species"):
        cases.append({**base, "id": "selected-" + kind, "menus": 2, "party_row": 1,
                      "selection_mutation": kind, "expected_notice": "selectionChanged"})
    return cases


def run_receptionist(variant, map_name, cases, artifact, *, baseline=False):
    directory = Path(tempfile.mkdtemp(prefix=f"receptionist-{variant}-{map_name}-", dir=ROOT / ".cache"))
    fixture = make_fixture(variant, map_name, directory)
    output = directory / "observed.json"
    charmap = text_charmap(variant)
    notice_lines = {name: [bytes(charmap[char] for char in line).hex().upper() for line in lines]
                    for name, lines in NOTICE_TEXT.items()}
    assert all(len(lines[0]) <= 36 and len(lines[1]) <= 34 for lines in notice_lines.values())
    cases = [{**row, "token": list(hashlib.sha256(f"{variant}/{map_name}/{row['id']}".encode()).digest()[:4]),
              "expected_notice": row.get("expected_notice",
                  "offerSent" if "expected_slot" in row else ("noLinked" if row.get("mask") == 0 else None)),
              "expected_result": row.get("expected_result", 0 if "expected_slot" in row else None)}
             for row in cases]
    # Omit absent values: the Lua codec's JSON-null sentinel is deliberately truthy.
    cases = [{key: value for key, value in row.items() if value is not None} for row in cases]
    config = {"fixture": fixture, "manifest": artifact, "cases": cases, "baseline": baseline,
              "final_sha1": fixture["base_sha1"] if baseline else artifact["final_sha1"],
              "output": str(output).replace("\\", "/"), "screenshots": "filtered-slot", "notice_lines": notice_lines}
    path = directory / "input.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    passed, verdict, log = run_gate("lua/tests/test_gen1_receptionist_gate.lua",
        rom_key=variant if baseline else variant + "_receptionist_trade",
        timeout=75, quiet=True, fixture_override=fixture["fixture"],
        extra_env={"SLINK_RECEPTIONIST_INPUT": str(path)})
    (directory / "gate.txt").write_text(log, encoding="utf-8")
    assert passed, f"{directory}\n{verdict}\n{log[-7000:]}"
    observed = json.loads(output.read_text())
    assert observed["passed"] and observed["final_sha1"] == config["final_sha1"]
    assert not observed["direct_cpu_redirect"] and not observed["runtime_ready"]
    assert [row["id"] for row in observed["cases"]] == [row["id"] for row in cases]
    assert hashlib.sha256(Path(fixture["fixture"]).read_bytes()).hexdigest() == fixture["fixture_sha256"]
    observed["evidence"] = str(directory.relative_to(ROOT))
    return observed


def text_charmap(variant):
    source = "pokeyellow" if variant == "yellow" else "pokered"
    source_text = (ROOT / f".cache/pret/{source}/constants/charmap.asm").read_text(encoding="utf-8")
    return {char: int(value, 16) for char, value in
            re.findall(r'^\s*charmap\s+"([^"\n]+)",\s*\$([0-9a-fA-F]+)', source_text, re.M) if len(char) == 1}


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_offer_feedback_requires_matching_receipt_and_preserves_unknown_delivery(variant):
    artifact = build(variant, receptionist=True)
    observed = run_receptionist(variant, "ViridianPokecenter", offer_cases(variant), artifact)
    (ROOT / f".cache/receptionist-offer-feedback-{variant}.json").write_text(json.dumps(observed, indent=2) + "\n")


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_picker_refuses_unreadable_names_and_selection_drift_before_offer(variant):
    artifact = build(variant, receptionist=True)
    observed = run_receptionist(variant, "ViridianPokecenter", invalid_party_cases(variant), artifact)
    (ROOT / f".cache/receptionist-party-refusals-{variant}.json").write_text(json.dumps(observed, indent=2) + "\n")


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_receptionist_party_selection_counts_slots_cancellation_and_held_input(variant):
    artifact = build(variant, receptionist=True)
    observed = run_receptionist(variant, "ViridianPokecenter", interaction_cases(variant), artifact)
    (ROOT / f".cache/receptionist-interactions-{variant}.json").write_text(json.dumps(observed, indent=2) + "\n")


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_every_existing_receptionist_including_indigo_uses_native_object_dispatch(variant):
    artifact = build(variant, receptionist=True)
    observed = []
    for map_name in receptionist_maps(variant):
        rows = [{"id": "existing-object-offer", "party": party(variant), "mask": 5,
                 "menus": 2, "party_row": 1, "expected_slot": 2}]
        observed.append(run_receptionist(variant, map_name, rows, artifact))
    (ROOT / f".cache/receptionist-locations-{variant}.json").write_text(json.dumps(observed, indent=2) + "\n")


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_cable_club_matches_unpatched_cartridge_and_unavailable_replies_fall_back(variant):
    artifact = build(variant, receptionist=True)
    baseline = run_receptionist(variant, "ViridianPokecenter",
        [{"id": "unpatched-cable", "party": party(variant), "mask": 5, "menus": 0, "cable": True}],
        artifact, baseline=True)
    observed = run_receptionist(variant, "ViridianPokecenter", cable_cases(variant), artifact)
    original = baseline["cases"][0]
    assert original["cable_text"], "baseline must execute actual cartridge dialogue"
    for row in observed["cases"]:
        assert row["cable_text"] == original["cable_text"]
        assert row["calls"] == original["calls"]
    (ROOT / f".cache/receptionist-cable-{variant}.json").write_text(
        json.dumps({"baseline": baseline, "patched": observed}, indent=2) + "\n")
