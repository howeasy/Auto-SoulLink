"""Player onboarding on the Manager: the player ZIP, the address players connect to, the
BizHawk minimum the setup text states, and the per-player connection state.

The pack is the release ZIP (`tools/make_release.py`, whose completeness
`test_make_release_manifest.py` pins) with this run's connection baked in, so the entry list
is compared against a plain release build rather than restated here.
"""
from __future__ import annotations

import io
import os
import re
import sys
import zipfile

import pytest

from server import board, manager

pytest_plugins = ["tests.unit.manager_harness"]

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import make_release  # noqa: E402

RUN = {"run_id": "run_1", "name": "Kanto Duo", "created_at": "2026-09-14T12:00:00",
       "tcp_port": 54322, "http_port": 8082, "status": "stopped", "pid": None, "game": "gen1"}


def _names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.namelist()


def _read(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read(name).decode("utf-8")


# ── 1. the player pack ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("player", ["a", "b"])
async def test_player_pack_is_the_release_plus_this_runs_launcher(manager_client, tmp_path, player):
    manager._save_registry([dict(RUN)])
    await manager_client.post("/api/settings/public-host", json={"host": "192.168.1.50"})
    resp = await manager_client.get(f"/api/runs/run_1/player-pack/{player}")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "application/zip"
    assert f"slink_Kanto_Duo_{player}.zip" in resp.headers["Content-Disposition"]
    data = await resp.read()

    prefix = f"SLink-player-Kanto_Duo_{player}/"
    names = _names(data)
    assert all(n.startswith(prefix) for n in names)
    base = make_release.build_release(version="base", out_dir=tmp_path, skip_generators=True)
    with zipfile.ZipFile(base) as zf:
        expected = {n.removeprefix("SLink-player-base/") for n in zf.namelist()}
    launcher = f"slink_Kanto_Duo_{player}.lua"
    assert {n.removeprefix(prefix) for n in names} == expected | {launcher}

    # The launcher at the pack root is the Manager's own, pointed at this run.
    src = _read(data, prefix + launcher)
    assert 'SLINK_HOST   = "192.168.1.50"' in src
    assert "SLINK_PORT   = 54322" in src
    assert f'SLINK_PLAYER = "{player}"' in src
    # The per-gen launchers inside lua/ carry the same values.
    gen1 = _read(data, prefix + "lua/slink_gen1.lua")
    assert re.search(r'^SLINK_HOST\s*=\s*"192\.168\.1\.50"', gen1, re.M)
    assert re.search(r"^SLINK_PORT\s*=\s*54322", gen1, re.M)
    assert re.search(rf'^SLINK_PLAYER\s*=\s*"{player}"', gen1, re.M)
    # The guide names the launcher that is already there and the address it uses.
    guide = _read(data, prefix + "PLAYER_SETUP.md")
    assert launcher in guide and "192.168.1.50:54322" in guide
    assert ":8080" not in guide


@pytest.mark.asyncio
async def test_player_pack_refuses_unknown_players_and_runs(manager_client):
    manager._save_registry([dict(RUN)])
    assert (await manager_client.get("/api/runs/run_1/player-pack/c")).status == 400
    assert (await manager_client.get("/api/runs/nope/player-pack/a")).status == 404


# ── 2. the address players connect to ────────────────────────────────────────

def test_advertised_host_resolution_order():
    lan = lambda: "192.168.1.50"  # noqa: E731
    # An address the host chose wins, even a loopback one.
    assert manager.advertised_host("10.0.0.7", "0.0.0.0", lan) == ("10.0.0.7", "set")
    assert manager.advertised_host("127.0.0.1", "0.0.0.0", lan) == ("127.0.0.1", "set")
    # A Manager bound to one address is reachable only there.
    assert manager.advertised_host("", "10.1.2.3", lan) == ("10.1.2.3", "bind")
    # Loopback-bound: nobody else can connect, and the page says so.
    assert manager.advertised_host("", "127.0.0.1", lan) == ("127.0.0.1", "loopback")
    assert manager.advertised_host("", "localhost", lan) == ("127.0.0.1", "loopback")
    # Wildcard: the LAN address, never loopback.
    assert manager.advertised_host("", "0.0.0.0", lan) == ("192.168.1.50", "lan")
    assert manager.advertised_host("", "::", lan) == ("192.168.1.50", "lan")
    # No network at all: loopback, flagged as such.
    assert manager.advertised_host("", "0.0.0.0", lambda: None) == ("127.0.0.1", "none")


def test_lan_address_is_never_loopback():
    ip = manager._lan_address()
    assert ip is None or not ip.startswith("127.")


@pytest.mark.asyncio
async def test_launcher_uses_the_advertised_host_not_the_request_host(manager_client):
    """The page opened as localhost used to hand player B a launcher pointing at 127.0.0.1."""
    manager._save_registry([dict(RUN)])
    ok = await manager_client.post("/api/settings/public-host", json={"host": "192.168.1.50"})
    assert (await ok.json())["host"] == "192.168.1.50"
    src = await (await manager_client.get("/api/runs/run_1/launcher/b")).text()
    assert 'SLINK_HOST   = "192.168.1.50"' in src
    # Persisted beside the registry, so a restart keeps it.
    assert manager._load_settings()["public_host"] == "192.168.1.50"


@pytest.mark.asyncio
async def test_public_host_setting_is_validated(manager_client):
    for bad in ("evil\"host", "a b", "x" * 300, "host/path"):
        resp = await manager_client.post("/api/settings/public-host", json={"host": bad})
        assert resp.status == 400, bad
    # Empty goes back to auto-detection.
    resp = await manager_client.post("/api/settings/public-host", json={"host": ""})
    assert resp.status == 200 and (await resp.json())["source"] != "set"


@pytest.mark.asyncio
async def test_run_page_shows_the_address_and_the_pack(manager_client):
    manager._save_registry([dict(RUN)])
    await manager_client.post("/api/settings/public-host", json={"host": "192.168.1.50"})
    body = await (await manager_client.get("/runs/run_1")).text()
    assert "192.168.1.50:54322" in body
    assert "/api/runs/run_1/player-pack/a" in body and "/api/runs/run_1/player-pack/b" in body
    assert "/api/settings/public-host" in body


# ── 3. the BizHawk minimum, from one place ───────────────────────────────────

@pytest.mark.parametrize("launcher", ["slink.lua", "slink_gen1.lua"])
def test_gen1_bizhawk_minimum_matches_the_lua_refusal(launcher):
    """Both Gen 1 entry points refuse below a version; the setup text states the same one."""
    with open(os.path.join(_REPO, "lua", launcher), encoding="utf-8") as f:
        src = f.read()
    floor = int(re.search(r"tonumber\(min\)\s*<\s*(\d+)", src).group(1))
    stated = make_release.BIZHAWK_MIN["Gen 1"]
    maj, mnr = (int(x) for x in stated.split("."))
    assert maj * 100 + mnr == floor
    assert f"install BizHawk {stated} or newer" in src


def test_setup_text_states_the_real_minimum():
    guide = make_release.player_setup_md()
    assert "2.9+" not in guide.replace(make_release.bizhawk_requirement(), "")
    assert make_release.bizhawk_requirement() in guide
    assert "2.11+ for Gen 1" in make_release.bizhawk_requirement()
    # decision 12: Gen 4/5 stay hidden
    assert "Gen 4" not in guide and "Gen 5" not in guide


@pytest.mark.asyncio
async def test_run_page_states_the_real_minimum(manager_client):
    manager._save_registry([dict(RUN)])
    body = await (await manager_client.get("/runs/run_1")).text()
    assert make_release.bizhawk_requirement() in body


# ── 4. connection states ─────────────────────────────────────────────────────

def _p(**kw):
    base = {"connected": False, "rom_type": "?", "last_seen_age": None, "last_seen_label": "—",
            "stale": False, "identity_error": "", "admission": "admitted", "admission_reason": ""}
    base.update(kw)
    return base


@pytest.mark.parametrize("live, player, slug", [
    (False, _p(), "stopped"),
    (False, _p(connected=True, rom_type="red"), "stopped"),
    (True, _p(), "waiting"),
    (True, _p(connected=True), "waiting"),                          # socket up, no hello yet
    (True, _p(connected=True, rom_type="red", last_seen_age=1), "ready"),
    (True, _p(connected=True, rom_type="red", identity_error="Mixed games: slot B runs gen3_frlge, "
              "this run is committed to gen1_rby"), "wrong_game"),
    (True, _p(connected=True, rom_type="red", identity_error="Mixed artifact kinds: slot B ..."),
     "wrong_game"),
    (True, _p(connected=True, identity_error="Unknown rom_type 'zzz' for slot A: ..."), "wrong_game"),
    (True, _p(connected=True, rom_type="red", admission="rejected",
              admission_reason="this is not the cartridge built for player a"), "wrong_game"),
    (True, _p(connected=True, rom_type="red", identity_error="Identity mismatch for slot A: ..."),
     "identity"),
    (True, _p(last_seen_age=130, last_seen_label="2m ago", rom_type="red"), "disconnected"),
    (True, _p(connected=True, rom_type="red", stale=True, last_seen_age=40,
              last_seen_label="40s ago"), "disconnected"),
])
def test_connection_state_mapping(live, player, slug):
    got = board.connection_state(player, live)
    assert got["slug"] == slug
    assert got["label"] and got["line"]


def test_disconnected_says_how_long_ago():
    got = board.connection_state(_p(last_seen_age=130, last_seen_label="2m ago"), True)
    assert "2m ago" in got["line"]


def test_wrong_game_carries_the_servers_reason():
    reason = "this is not the cartridge built for player a"
    got = board.connection_state(_p(connected=True, admission="rejected", admission_reason=reason), True)
    assert reason in got["line"]


def test_the_error_prefixes_the_mapping_reads_are_the_servers():
    """connection_state tells wrong-game from wrong-save by the server's own message text."""
    with open(os.path.join(_REPO, "server", "server.py"), encoding="utf-8") as f:
        src = f.read()
    for prefix in board._WRONG_GAME_ERRORS:
        assert f'f"{prefix}' in src or f'"{prefix}' in src, prefix


@pytest.mark.asyncio
async def test_board_shows_each_players_state(manager_client):
    manager._save_registry([dict(RUN)])
    body = await (await manager_client.get("/runs/run_1/board")).text()
    assert body.count("mk-conn stopped") == 2
