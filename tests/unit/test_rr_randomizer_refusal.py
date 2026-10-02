"""RR-RAND-REFUSE -- owner ruling 37 (2026-09-27): randomized Radical Red is OUT of this
release. Randomized FireRed / LeafGreen / Emerald stay in (ruling 29).

Radical Red is a FireRed hack and carries FireRed's BPRE game code (lua/gen3/entry.lua:57-59),
so a scanner that only knows the header calls a Radical Red cartridge a *randomized FireRed* --
the one classification ruling 37 forbids, and the one a player reads in the Manager's picker.
Every path that can be handed a randomized Radical Red must therefore NAME Radical Red and
refuse; none may quietly accept the request, and none may crash.
"""
from __future__ import annotations

import hashlib

import pytest

from server import cartridges, manager, upr_pipeline
from server.server import _randomized_binding_error

pytest_plugins = ["tests.unit.manager_harness"]


# ── a Radical Red cartridge, without needing the 16 MiB ROM on disk ──────────────────────
def _gba(code: bytes) -> bytes:
    """A 16 MiB rev-0 GBA cartridge whose header names ``code`` -- what every Gen 3 title
    this pipeline scans looks like, at the size/gen3_title() gates on."""
    rom = bytearray(upr_pipeline.GEN3_ROM_SIZE)
    rom[0xAC:0xB0] = code
    return bytes(rom)


def _pinned_as(monkeypatch, rom: bytes) -> None:
    """Pin ``rom`` as the Radical Red `clean` artifact, the way the real RR pack pins its
    base build. The shipped pins are the hashes of 16 MiB ROMs SLink does not ship, so the
    test pins its own bytes through the same table the scanner reads."""
    sha1, md5 = hashlib.sha1(rom).hexdigest(), hashlib.md5(rom).hexdigest()
    monkeypatch.setattr(upr_pipeline, "_gen3_rr_artifacts", lambda: {
        "radical_red": {"clean": {"rom_sha1": sha1, "rom_md5": md5, "sites": {}}},
    })


def _named(info: dict) -> str:
    return f"{info.get('variant', '')} {info.get('title', '')}"


# ── the cart: named Radical Red, refused by name, never reported as a FireRed ────────────
def test_only_radical_red_is_refused_as_a_game():
    """Ruling 37 removed Radical Red and nothing else."""
    # the Emerald Expansion (gen3_exp) has no randomizer either, but that is not ruling 37
    assert set(manager.NON_RANDOMIZABLE_GAMES) - {"gen3_exp"} == {"gen3_rr"}
    assert set(manager.new_run_form()["randomizer_games"]) <= set(manager.GAME_FAMILY)
    assert {"gen3", "gen3_e", "gen1", "gen1_purergb"} <= set(manager.new_run_form()["randomizer_games"])


@pytest.mark.asyncio
async def test_a_firered_run_still_reaches_the_randomizer(manager_client, manager_dir):
    """The ruling removes Radical Red and nothing else: a FireRed / LeafGreen run's request
    still gets as far as the cartridge check, and is refused there for its own reason."""
    run = {"run_id": "run_g3", "name": "Kanto", "created_at": "2026-09-27T12:00:00",
           "tcp_port": 54321, "http_port": 8081, "status": "stopped", "pid": None,
           "game": "gen3"}
    manager._save_registry([run])
    (manager_dir / "run_g3").mkdir()

    response = await manager_client.post("/api/runs/run_g3/cartridges", json={
        "rom_a": "a.gba", "rom_b": "b.gba", "jar": "PokeRandoZX.jar", "randomize": True,
        "categories": ["wild"]})

    body = await response.json()
    assert response.status == 400
    assert "Randomized Radical Red is not supported" not in body["error"]


# ── the hello: a client that declares a randomized Radical Red is refused by name ─────────
