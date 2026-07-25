"""Every run-registry key the manager stores must actually reach the server CLI.

`verbose` was in every registry entry from the first release but no code path ever passed
`--verbose` through, so a per-run DEBUG log was silently impossible from the manager UI.
This test is the general guard: a registry key that the spawn command ignores is a bug.
"""
import asyncio

import pytest

import server.manager as manager


def _captured_spawn_cmd(run: dict) -> list:
    """Run manager._spawn_run with the subprocess swapped for a capture stub."""
    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)

        class P:
            pid = 4242
        return P()

    real = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = fake_exec
    try:
        asyncio.run(manager._spawn_run(run, "127.0.0.1"))
    finally:
        asyncio.create_subprocess_exec = real
    return captured["cmd"]


@pytest.fixture(autouse=True)
def _manager_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))


BASE = {"run_id": "r1", "tcp_port": 1, "http_port": 2}


def test_verbose_off_by_default():
    assert "--verbose" not in _captured_spawn_cmd(dict(BASE))


def test_verbose_reaches_the_server_cli():
    assert "--verbose" in _captured_spawn_cmd(dict(BASE, verbose=True))


@pytest.mark.parametrize("key,flag", [
    ("species_lock", "--species-clause"),
    ("gender_lock", "--gender-clause"),
    ("type_lock", "--type-clause"),
    ("explode_mode", "--explode-mode"),
    ("rival_team_swap", "--rival-team-swap"),
    ("overworld_presence", "--overworld-presence"),
    ("native_messages", "--native-messages"),
    ("native_sounds", "--native-sounds"),
    ("verbose", "--verbose"),
])
def test_every_opt_in_registry_key_reaches_the_cli(key, flag):
    assert flag in _captured_spawn_cmd(dict(BASE, **{key: True}))


@pytest.mark.parametrize("key,flag", [
    ("battle_calc", "--no-battle-calc"),
    ("pc_trade_npc", "--no-pc-trade-npc"),
])
def test_default_on_keys_use_inverse_flags(key, flag):
    assert flag not in _captured_spawn_cmd(dict(BASE))              # default ON → no flag
    assert flag in _captured_spawn_cmd(dict(BASE, **{key: False}))  # turned off → --no-*
