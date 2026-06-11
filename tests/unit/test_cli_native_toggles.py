"""
Unit tests for the five native-enhancement toggles:

    --native-messages        (default OFF: Lua HUD overlay until the native path wins the A/B test)
    --native-sounds          (default OFF: Lua m4a path)
    --no-battle-calc         (battle_calc default ON: the bundled damage display shows unless disabled)
    --no-pc-trade-npc        (pc_trade_npc default ON: effective only while overworld presence is OFF)
    --native-battle-control  (default OFF: native explode/faint controller swap; EXPERIMENTAL after
                              a real-play softlock — the Variant-3 RAM path remains the fallback)

Mirrors tests/unit/test_cli_overworld_presence.py.  Unlike the opt-in run RULES
(explode/rival-swap/presence), these don't change soullink semantics — they pick the
patch path vs the Lua fallback, so the default-ON pair uses inverse (store_false) flags.

Run:
    pytest tests/unit/test_cli_native_toggles.py -v
"""

import subprocess
import sys

from server.state import SoulLinkState


def test_help_mentions_all_native_toggles():
    """Sanity: all five flags appear in the --help output."""
    res = subprocess.run(
        [sys.executable, "-m", "server.server", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert res.returncode == 0, f"--help failed: {res.stderr}"
    out = res.stdout + res.stderr
    assert "--native-messages" in out
    assert "--native-sounds" in out
    assert "--no-battle-calc" in out
    assert "--no-pc-trade-npc" in out
    assert "--native-battle-control" in out


def test_parser_shapes():
    """store_true for the default-OFF pair; store_false (inverse) for the default-ON pair."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-messages", action="store_true", dest="native_messages")
    parser.add_argument("--native-sounds", action="store_true", dest="native_sounds")
    parser.add_argument("--no-battle-calc", action="store_false", dest="battle_calc")
    parser.add_argument("--no-pc-trade-npc", action="store_false", dest="pc_trade_npc")
    parser.add_argument("--native-battle-control", action="store_true", dest="native_battle_control")
    args = parser.parse_args([])
    assert args.native_messages is False
    assert args.native_sounds is False
    assert args.battle_calc is True
    assert args.pc_trade_npc is True
    assert args.native_battle_control is False
    args = parser.parse_args(["--native-messages", "--native-sounds",
                              "--no-battle-calc", "--no-pc-trade-npc",
                              "--native-battle-control"])
    assert args.native_messages is True
    assert args.native_sounds is True
    assert args.battle_calc is False
    assert args.pc_trade_npc is False
    assert args.native_battle_control is True


def test_state_defaults():
    """SoulLinkState defaults: messages/sounds/battle-control OFF, battle_calc/pc_trade_npc ON."""
    s = SoulLinkState()
    assert s.native_messages is False
    assert s.native_sounds is False
    assert s.battle_calc is True
    assert s.pc_trade_npc is True
    assert s.native_battle_control is False


def test_state_non_default_constructs():
    """Non-default values thread through __init__ cleanly."""
    s = SoulLinkState(native_messages=True, native_sounds=True,
                      battle_calc=False, pc_trade_npc=False,
                      native_battle_control=True)
    assert s.native_messages is True
    assert s.native_sounds is True
    assert s.battle_calc is False
    assert s.pc_trade_npc is False
    assert s.native_battle_control is True


def test_toggles_round_trip_through_save_load(tmp_path, monkeypatch):
    """Non-default values persist via _save() and are restored by load()."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(data_dir=str(tmp_path), native_messages=True,
                          native_sounds=True, battle_calc=False, pc_trade_npc=False,
                          native_battle_control=True)
    state._save()
    reloaded = SoulLinkState.load(data_dir=str(tmp_path))
    assert reloaded.native_messages is True
    assert reloaded.native_sounds is True
    assert reloaded.battle_calc is False
    assert reloaded.pc_trade_npc is False
    assert reloaded.native_battle_control is True


def test_old_save_without_toggles_gets_defaults(tmp_path, monkeypatch):
    """A pre-toggle links.json (rules block without the new keys) loads with the defaults."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(data_dir=str(tmp_path))
    state._save()
    import json
    p = tmp_path / "links.json"
    data = json.loads(p.read_text())
    for k in ("native_messages", "native_sounds", "battle_calc", "pc_trade_npc",
              "native_battle_control"):
        data["rules"].pop(k, None)
    p.write_text(json.dumps(data))
    reloaded = SoulLinkState.load(data_dir=str(tmp_path))
    assert reloaded.native_messages is False
    assert reloaded.native_sounds is False
    assert reloaded.battle_calc is True
    assert reloaded.pc_trade_npc is True
    assert reloaded.native_battle_control is False


def test_hello_config_carries_native_toggles(tmp_path, monkeypatch):
    """The hello config command carries all five toggle fields for the Lua client."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState()
    cmds = state.handle_event("a", {"event": "hello", "party": []})
    config_cmd = [c for c in cmds if c.get("cmd") == "config"]
    assert len(config_cmd) == 1, "hello must include exactly one config command"
    cfg = config_cmd[0]
    assert cfg["native_messages"] is False
    assert cfg["native_sounds"] is False
    assert cfg["battle_calc"] is True
    assert cfg["pc_trade_npc"] is True
    assert cfg["native_battle_control"] is False

    state.native_messages = True
    state.native_sounds = True
    state.battle_calc = False
    state.pc_trade_npc = False
    state.native_battle_control = True
    cmds = state.handle_event("b", {"event": "hello", "party": []})
    cfg = [c for c in cmds if c.get("cmd") == "config"][0]
    assert cfg["native_messages"] is True
    assert cfg["native_sounds"] is True
    assert cfg["battle_calc"] is False
    assert cfg["pc_trade_npc"] is False
    assert cfg["native_battle_control"] is True


def _captured_spawn_cmd(run: dict) -> list:
    """Run manager._spawn_run with the subprocess swapped for a capture stub; return the cmd."""
    import asyncio
    import server.manager as manager

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


def test_manager_spawn_flags_defaults(tmp_path, monkeypatch):
    """Default run dict: no native-toggle flags at all (server defaults are correct)."""
    import server.manager as manager
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))
    cmd = _captured_spawn_cmd({"run_id": "r1", "tcp_port": 1, "http_port": 2})
    for flag in ("--native-messages", "--native-sounds", "--no-battle-calc", "--no-pc-trade-npc",
                 "--native-battle-control"):
        assert flag not in cmd


def test_manager_spawn_flags_non_default(tmp_path, monkeypatch):
    """Non-default run dict: every toggle materializes as its CLI flag."""
    import server.manager as manager
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))
    cmd = _captured_spawn_cmd({"run_id": "r2", "tcp_port": 1, "http_port": 2,
                               "native_messages": True, "native_sounds": True,
                               "battle_calc": False, "pc_trade_npc": False,
                               "native_battle_control": True})
    assert "--native-messages" in cmd
    assert "--native-sounds" in cmd
    assert "--no-battle-calc" in cmd
    assert "--no-pc-trade-npc" in cmd
    assert "--native-battle-control" in cmd
