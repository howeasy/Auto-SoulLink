"""The wire contract of docs/protocol.md as data, plus two validators.

Used by client conformance tests (any generation): every line a client emits goes through
`validate_event`, every command a fake server hands it is built through `validate_command`.
test_protocol_schema.py pins this table to the server's own dispatch and command literals,
so the schema tracks server/state.py (the authority), not any one client.

Field types: "str", "int", "bool", "list", "dict", "key" (DDDD:OOOO:SS or PPPPPPPP:OOOOOOOO),
"hex" (even-length uppercase/lowercase hex), "num" (int or float).
"""
from __future__ import annotations

import re

KEY_RE = re.compile(r"^[0-9A-F]{4}:[0-9A-F]{4}:[0-9A-F]{2}$|^[0-9A-F]{8}:[0-9A-F]{8}$", re.I)
HEX_RE = re.compile(r"^(?:[0-9A-Fa-f]{2})*$")

# event -> (required fields, optional fields); docs/protocol.md §3.2
EVENTS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "hello": ({"rom_type": "str", "party": "list"},
              {"game": "str", "player": "str", "ot_id": "int", "panel": "bool", "patch": "bool",
               "version": "str", "client": "str", "badges": "int", "has_pokeballs": "bool",
               "trainer_name": "str", "pc_boxes": "list", "area_id": "str", "loc_name": "str",
               "rom_sha1": "str", "caps": "dict"}),
    "tick": ({}, {"has_pokeballs": "bool", "party": "list", "area_id": "str", "loc_name": "str",
                  "in_battle": "bool", "is_trainer_battle": "bool", "trainer_id": "int",
                  "opponent_name": "str", "opponent_class": "str", "enemy_party": "list",
                  "is_doubles": "bool", "pc_boxes": "list", "ball_count": "int", "badges": "int",
                  "kanto_badges": "int", "trainer_name": "str"}),
    "safe": ({}, {}),  # same optional set as tick; Gen 3 sends none
    "area_enter": ({"area_id": "str"}, {"loc_name": "str"}),
    "capture": ({"key": "key", "area_id": "str"},
                {"species_id": "int", "level": "int", "hp": "int", "maxHP": "int", "nickname": "str",
                 "held_item_id": "int", "is_egg": "bool", "gift": "bool", "in_box": "bool", "stats": "dict"}),
    "faint": ({"key": "key"}, {"area_id": "str"}),
    "no_catch": ({"area_id": "str"}, {"species_id": "int", "level": "int"}),
    "whiteout": ({}, {}),
    "party_to_box": ({"key": "key"}, {"stats": "dict"}),
    "box_to_party": ({"key": "key"}, {"area_id": "str", "nickname": "str"}),
    "key_change": ({"old_key": "key", "new_key": "key"},
                   {"reason": "str", "new_species": "int", "new_nickname": "str"}),
    "trainer_battle_start": ({"trainer_id": "int"}, {}),
    "rival_team_replaced": ({"trainer_id": "int", "species_ids": "list"}, {"error": "str"}),
    "stats_cache": ({"key": "key", "stats": "dict"}, {}),
    "sync_retrieve_done": ({"key": "key"}, {}),
    "sync_retrieve_failed": ({"key": "key"}, {}),
    "box_mon_failed": ({"key": "key"}, {"reason": "str"}),
    "memorialize_done": ({"key": "key"}, {"box": "int"}),
    "memorialize_failed": ({"key": "key"}, {"reason": "str"}),
    "trade_request": ({}, {}),
    "menu_result": ({"token": "str", "choice": "int"}, {}),
    "mon_chosen": ({"token": "str", "slot": "int"}, {}),
    "trade_done": ({"new_key": "key", "new_species": "int"}, {"token": "str", "slot": "int"}),
    "status": ({"badges": "int"}, {}),
    "ghost_pos": ({}, {}),  # ints only; relayed opaquely
    "peer_interact": ({}, {}),
}
# tick's optional set also applies to safe
EVENTS["safe"] = ({}, dict(EVENTS["tick"][1]))

ENVELOPE = {"event": "str", "player": "str", "seq": "int"}

# cmd -> (required fields, optional fields); docs/protocol.md §5
COMMANDS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "noop": ({}, {}),
    "force_faint": ({"key": "key"}, {"nickname": "str"}),
    "force_explode": ({"key": "key"}, {"nickname": "str"}),
    "box_mon": ({"key": "key"}, {}),
    "party_mon": ({"key": "key"}, {"nickname": "str", "stats": "dict"}),
    "memorialize": ({"key": "key"}, {}),
    "game_over": ({}, {}),
    "msgbox": ({"text": "str"}, {"fb": "str", "r": "int", "g": "int", "b": "int", "frames": "int"}),
    "gui_prompt": ({"text": "str"}, {"r": "int", "g": "int", "b": "int", "frames": "int"}),
    "hud_show": ({"text": "str"}, {"r": "int", "g": "int", "b": "int", "frames": "int",
                                   "color": "list", "duration": "int"}),
    "play_sound": ({"sound": "int"}, {}),
    "resolved_areas": ({"areas": "list"}, {}),
    "unresolve_area": ({"area_id": "str"}, {}),
    "config": ({}, {"overworld_presence": "bool", "native_messages": "bool", "native_sounds": "bool",
                    "battle_calc": "bool", "pc_trade_npc": "bool"}),
    "rebuild_start": ({"text": "str", "keys": "list"}, {}),
    "rebuild_done": ({}, {}),
    "replace_rival_team": ({"trainer_id": "int", "n": "int", "blobs_hex": "list"}, {"source": "str"}),
    "show_choices": ({"token": "str", "options": "list", "text": "str"}, {}),
    "show_menu": ({"token": "str", "text": "str"}, {}),
    "choose_mon": ({"token": "str"}, {}),
    "apply_trade": ({"slot": "int", "blob_hex": "hex", "old_key": "key", "token": "str"}, {}),
    "ghost_pos": ({}, {}),
    "link_panel": ({"rows": "list"}, {}),
}

# Which commands a client must answer, and with what (docs/protocol.md §5, §5.1).
ACKS = {
    "party_mon": ("sync_retrieve_done", "sync_retrieve_failed"),
    "box_mon": (None, "box_mon_failed"),
    "memorialize": ("memorialize_done", "memorialize_failed"),
    "replace_rival_team": ("rival_team_replaced", "rival_team_replaced"),
    "show_choices": ("menu_result", "menu_result"),
    "show_menu": ("menu_result", "menu_result"),
    "choose_mon": ("mon_chosen", "mon_chosen"),
    "apply_trade": ("trade_done", None),
}
PROMPT_CANCEL = {"show_choices": ("menu_result", "choice", 127),
                 "show_menu": ("menu_result", "choice", 0),
                 "choose_mon": ("mon_chosen", "slot", 7)}
DEFERRED = {"box_mon", "party_mon", "memorialize", "apply_trade"}


def _check_type(value, kind: str) -> bool:
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "num":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "list":
        return isinstance(value, list)
    if kind == "dict":
        return isinstance(value, dict)
    if kind == "key":
        return isinstance(value, str) and bool(KEY_RE.match(value))
    if kind == "hex":
        return isinstance(value, str) and bool(HEX_RE.match(value)) and len(value) > 0
    raise ValueError(kind)


def _validate(kind_word: str, name: str, table: dict, msg: dict, *, extra_ok: bool) -> list[str]:
    problems: list[str] = []
    if name not in table:
        return [f"unknown {kind_word} {name!r}"]
    required, optional = table[name]
    for field, ftype in required.items():
        if field not in msg:
            problems.append(f"{name}: missing required {field!r}")
        elif not _check_type(msg[field], ftype):
            problems.append(f"{name}: {field!r} should be {ftype}, got {msg[field]!r}")
    for field, ftype in optional.items():
        if field in msg and msg[field] is not None and not _check_type(msg[field], ftype):
            problems.append(f"{name}: {field!r} should be {ftype}, got {msg[field]!r}")
    if not extra_ok:
        known = set(required) | set(optional) | set(ENVELOPE) | {"cmd"}
        for field in msg:
            if field not in known:
                problems.append(f"{name}: unexpected field {field!r}")
    return problems


def validate_event(msg: dict, *, strict: bool = False) -> list[str]:
    """Problems with one client->server line (empty list = conforms). `strict` also rejects
    fields the contract does not list."""
    problems = []
    for field, ftype in ENVELOPE.items():
        if field not in msg:
            problems.append(f"envelope: missing {field!r}")
        elif not _check_type(msg[field], ftype):
            problems.append(f"envelope: {field!r} should be {ftype}")
    if msg.get("player") not in ("a", "b"):
        problems.append("envelope: player must be 'a' or 'b'")
    if problems:
        return problems
    return _validate("event", msg["event"], EVENTS, msg, extra_ok=not strict)


def validate_command(cmd: dict, *, strict: bool = False) -> list[str]:
    """Problems with one server->client command object (empty list = conforms)."""
    if not isinstance(cmd, dict) or "cmd" not in cmd or not isinstance(cmd["cmd"], str):
        return ["command: not an object with a string 'cmd'"]
    return _validate("command", cmd["cmd"], COMMANDS, cmd, extra_ok=not strict)


def validate_reply(line: dict) -> list[str]:
    """One server reply line: exactly `{"commands":[...]}` with at least one command."""
    if set(line) != {"commands"} or not isinstance(line["commands"], list) or not line["commands"]:
        return ["reply: must be {'commands': [non-empty list]}"]
    out: list[str] = []
    for c in line["commands"]:
        out += validate_command(c)
    return out
