"""C-5 randomized input of tools/gen2_duo_oracles.py (RANDOMIZED, default None): a rand_overlay side is accepted only at
its own contract sha1 on the overlay binding, and the NPC-trade read finds the row by request + OT (trades=given)."""
from __future__ import annotations

import hashlib
import json

import pytest

from tools import gen2_duo_oracles as oracles


@pytest.fixture
def randomized(tmp_path, monkeypatch):
    roms = tmp_path / "roms"
    roms.mkdir()
    shas = {}
    for side in ("a", "b"):
        raw = bytearray(0x200000)
        raw[0] = ord(side)
        (roms / f"{side}.gbc").write_bytes(raw)
        shas[side] = hashlib.sha1(raw).hexdigest()
    (tmp_path / "rom_contract.json").write_text(json.dumps({"players": {s: {"rom_sha1": h} for s, h in shas.items()}}))
    monkeypatch.setattr(oracles, "RANDOMIZED", oracles.randomized_from_run(tmp_path))
    return shas


def _markers(sha, kind="rand_overlay"):
    binding = oracles._executed_identity("crystal", "overlay")[1]
    client = {"artifact_kind": kind, "title": "crystal", "rom_sha1": sha, "qualification": "PHYSICAL_RECEIPTED",
              "production_admitted": True, "binding_sha256": binding}
    return client, {"artifact_kind": "overlay", "binding_sha256": binding}


def test_unrandomized_run_refuses_a_rand_overlay_client():
    assert oracles.RANDOMIZED is None
    with pytest.raises(RuntimeError, match="no randomized contract"):
        oracles._client_artifact("a", *_markers("1" * 40))


def test_a_side_is_pinned_to_its_own_contract_sha1(randomized):
    assert oracles._client_artifact("a", *_markers(randomized["a"])) == ("overlay", randomized["a"])
    with pytest.raises(RuntimeError, match="not its contract cartridge"):
        oracles._client_artifact("a", *_markers(randomized["b"]))   # the partner's cart


def test_a_contract_that_does_not_match_its_rom_refuses(tmp_path, randomized):
    run = oracles.RANDOMIZED["roms"]["a"].parent.parent
    (run / "roms" / "a.gbc").write_bytes(b"\x00" * 16)
    with pytest.raises(RuntimeError, match="differs from its contract"):
        oracles.randomized_from_run(run)


def test_npc_trade_row_is_found_by_request_and_ot(randomized):
    sym = (oracles.REPO_ROOT / "data/gen2/crystal_slink.sym").read_text(encoding="utf-8")
    bank, addr = next(line.split()[0].split(":") for line in sym.splitlines() if line.endswith(" NPCTrades"))
    base = int(bank, 16) * 0x4000 + int(addr, 16) - 0x4000
    path = oracles.RANDOMIZED["roms"]["a"]
    raw = bytearray(path.read_bytes())
    raw[base + 32 + 1], raw[base + 32 + 2] = oracles.BELLSPROUT, 200          # Kyle's row: request kept, given random
    raw[base + 32 + 17:base + 32 + 19] = oracles.KYLE_OT.to_bytes(2, "little")
    path.write_bytes(raw)
    assert oracles._randomized_npc_trade("a", "crystal", oracles.BELLSPROUT, oracles.KYLE_OT) == (200, oracles.KYLE_OT)
    raw[base + 32 + 1] = 1                                                    # given_and_requested: request changed
    path.write_bytes(raw)
    with pytest.raises(RuntimeError, match="trades=given required"):
        oracles._randomized_npc_trade("a", "crystal", oracles.BELLSPROUT, oracles.KYLE_OT)
