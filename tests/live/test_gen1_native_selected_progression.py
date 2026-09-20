"""First finite original-game progression on the checked Manager-selected native fresh run (Yellow/Yellow).

Same two emulator processes, run, launcher and private SaveRAM as the bedroom smoke
(tests/live/test_gen1_native_selected_fresh.py): after its 1x/3x windows the gate drives ordinary
joypad input only — bedroom -> Oak's Lab (Pikachu) -> forced rival battle -> Route 1 -> Viridian
Pokemon Center -> LINK RECEPTIONIST — and the experiment ends at the receptionist_entered ACK.
No trade, no CONTINUE, no bundle-launch claim (the emulator is launched by run_gate, as the smoke).
Research receipt: cx-fa4fad12.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

from server.gen1_inventory_observation import COMPONENT as INVENTORY_COMPONENT, record_key
from tests.live.test_gen1_free_service import journal_events
from tests.live.test_gen1_native_selected_fresh import selected_fresh_scenario
from tools.verify_canonical_sources import verify

PIKACHU = 0x54                       # Gen 1 internal species index (pret constants/pokemon_constants.asm)
STAGES = ("bedroom", "house", "oak", "starter", "rival", "exit_lab", "route1", "viridian", "pokecenter", "receptionist")
CAPS = {"bedroom": 1800, "house": 1800, "oak": 9000, "starter": 9000, "rival": 9000, "exit_lab": 3600,
        "route1": 6000, "viridian": 12000, "pokecenter": 9000, "receptionist": 6000}
TOTAL_CAP = sum(CAPS.values())       # 66,600 frames: ~18.5 min at 1x, ~6 min at the 3x walk speed
PROGRESSION_INPUT = {"speed": 300, "caps": CAPS}


def progression_checks(document, runtime, ready, arrived, run_directory, client_run_root):
    components = document["components"]
    # No trade claim, no death, both starters settled by the server (Yellow/Yellow: clause exempt).
    assert document["active_trade"] is None
    assert not components.get("gen1-trade", {}).get("transactions", {})
    assert not components.get("gen1-faint-settlement", {}).get("deaths", {})
    starters = components["gen1-starter-settlement"]
    assert set(starters["settled"]) == {"a", "b"}
    assert all(starters["settled"][p]["member_id"] for p in ("a", "b"))
    assert starters.get("rejection") is None
    assert set(components["gen1-native-reattach"]) == {"a", "b"}
    rows, snapshot = journal_events(run_directory / "runtime.sqlite3")
    for player in ("a", "b"):
        receipt = arrived[player]
        assert [stage["name"] for stage in receipt["stages"]] == list(STAGES)
        assert all(stage["how"] == "reached" and stage["frames"] <= CAPS[stage["name"]] for stage in receipt["stages"])
        assert receipt["events"] == {"got_starter": True, "battled_rival": True}
        assert receipt["battles"]["trainer"] >= 1                       # the lab rival battle happened
        assert receipt["party"] == {"count": 1, "species": PIKACHU, "level": receipt["party"]["level"], "hp": receipt["party"]["hp"]}
        assert receipt["party"]["hp"] > 0 and receipt["party"]["level"] >= 5
        assert receipt["map"] == 0x29 and (receipt["x"], receipt["y"]) == (11, 3)
        status = receipt["status"]
        assert status["phase"] == "free_service" and not status["runtime"]["failed"] and status["runtime"]["connected"]
        assert status["native_host"].get("failed") is None
        events = [row for row in rows if row[0] == player]
        entered = [row for row in events if row[2].get("event") == "receptionist_entered"]
        assert len(entered) == 1 and entered[0][3]["ack"] == "ACK"
        entry_party = entered[0][2]["payload"]["checkpoint"]["party"]
        assert entry_party["count"] == 1 if isinstance(entry_party, dict) and "count" in entry_party else True
        # The heartbeat inventory carried a NON-null same-frame native checkpoint once the party existed,
        # and the server's inventory history committed that point.
        observations = [row[2] for row in events if row[2].get("event") == "observation" and row[2]["inventory"] is not None]
        with_party = [row for row in observations if row.get("native_checkpoint") is not None]
        assert with_party, "no inventory point carried a native checkpoint after the starter"
        assert all(row["native_checkpoint"]["schema"] == "rby-native-observation-v1" for row in with_party)
        history = runtime.journal.record_history(INVENTORY_COMPONENT, record_key(player), limit=256)
        assert len(history) == len(observations)
        assert int(with_party[-1]["inventory"]["source"]["fields"]["party"][0:2], 16) == 1
        # Client side: the entry is acknowledged in the production LocalAppData journal.
        local = json.loads((client_run_root / player / "journal.json").read_text())["document"]["payload"]
        assert local["observation"]["receptionist_entry"]["phase"] == "acknowledged"
    assert snapshot["components"]["gen1-starter-settlement"] == starters


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="exclusive live emulator lane required")
def test_manager_selected_native_yellow_pair_reaches_the_viridian_receptionist(monkeypatch):
    assert not verify()["failures"]
    assert "SLINK_CLIENT_STORAGE_ROOT" not in os.environ, "use the production LocalAppData journal path"
    asyncio.run(selected_fresh_scenario(("yellow", "yellow"), monkeypatch, progression={
        "input": PROGRESSION_INPUT, "timeout": 1800, "wait_seconds": 1500,
        "checks": progression_checks, "keep_client_journals": True}))


# ---------------------------------------------------------------------------------------------
# Offline guards (no emulator): the gate's source facts and its read-only contract.

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "lua/tests/test_gen1_native_selected_fresh_gate.lua"


def pret_event_bits(game):
    """Re-derive event bit indices from pret constants/event_constants.asm (const_def/const/const_skip/const_next)."""
    path = ROOT / f".cache/pret/{game}/constants/event_constants.asm"
    if not path.is_file():
        pytest.skip(f"pret {game} sources are not checked out")
    index, bits = 0, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        words = line.strip().split()
        if not words:
            continue
        if words[0] == "const_def":
            index = int(words[1]) if len(words) > 1 else 0
        elif words[0] == "const_skip":
            index += int(words[1]) if len(words) > 1 else 1
        elif words[0] == "const_next":
            index = int(words[1])
        elif words[0] == "const":
            bits[words[1]] = index
            index += 1
    return bits


@pytest.mark.parametrize("game", ["pokeyellow", "pokered"])
def test_progression_event_bits_match_pret(game):
    bits = pret_event_bits(game)
    assert bits["EVENT_GOT_STARTER"] == 34 and bits["EVENT_BATTLED_RIVAL_IN_OAKS_LAB"] == 35
    assert "EVENT={GOT_STARTER=34,BATTLED_RIVAL=35}" in GATE.read_text(encoding="utf-8")


def test_progression_gate_is_joypad_only_and_dormant_without_input():
    source = GATE.read_text(encoding="utf-8")
    body = source[source.index("local prog=input.progression"):]
    # The only WRAM writes in the whole gate are the pre-existing restored perf probe (two lines).
    assert source.count("memory.write_u8") == 2 and "memory.write" not in body
    for forbidden in ("emu.setregister", "memory.writebyte", "savestate.", "client.reboot", "mainmemory.write"):
        assert forbidden not in source
    # Dormant without input.progression: the smoke's post-loop branch is untouched behind the flag.
    assert "elseif prog and reported and not P.done then" in source
    assert 'if prog then assert(t.variant=="yellow"' in source
    assert TOTAL_CAP == 66600
