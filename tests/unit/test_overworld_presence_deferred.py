"""Overworld Presence is deferred post-RC (owner ruling 2026-09-22; docs/gen3/TODO.md).

The rewritten Gen 3 client never drives the peer ghost (`ghost_pos` is a no-op), but the flag
still reached `lua/gen3/native.lua`'s `config`, which disables the Pokemon Center trade NPC
while presence is on: a run with the toggle on had no ghost AND no trade entry point. The
server now forces the flag off (like native_messages), and the Manager greys it out.
"""
import json

from server import manager
from server.state import SoulLinkState


def test_constructor_flag_is_ignored(tmp_path):
    assert SoulLinkState(data_dir=str(tmp_path), overworld_presence=True).overworld_presence is False


def test_saved_rule_is_ignored(tmp_path):
    s = SoulLinkState(data_dir=str(tmp_path))
    s._save()
    path = tmp_path / "links.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("rules", {})["overworld_presence"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert SoulLinkState.load(data_dir=str(tmp_path), overworld_presence=True).overworld_presence is False


def test_manager_offers_it_to_no_game():
    cap = manager.OPTION_SUPPORT["overworld_presence"]
    assert cap["all"] is False
    assert not any(isinstance(v, dict) and v.get("ok") for v in cap.values())
