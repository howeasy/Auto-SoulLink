"""The wire contract of docs/protocol.md as data, plus two validators.

Used by client conformance tests (any generation): every line a client emits goes through
`validate_event`, every command a fake server hands it is built through `validate_command`.
test_protocol_schema.py pins this table to the server's own dispatch and command literals,
so the schema tracks server/state.py (the authority), not any one client.

Field types: "str", "int", "bool", "list", "dict", "key" (DDDD:OOOO:SS or PPPPPPPP:OOOOOOOO),
"hex" (even-length uppercase/lowercase hex), "num" (int or float), "battle_id" (a battle request
counter: int, never bool, never fractional, 1..2**32-1), "session" (a client-session nonce: hex
string, 1..16 chars). The last two are validated strictly and never coerced (card C5-10): a
boolean, fractional or out-of-range counter, or a malformed nonce, is a protocol violation.
"""
from __future__ import annotations

import re

KEY_RE = re.compile(r"^[0-9A-F]{4}:[0-9A-F]{4}:[0-9A-F]{2}$|^[0-9A-F]{8}:[0-9A-F]{8}$", re.I)
HEX_RE = re.compile(r"^(?:[0-9A-Fa-f]{2})*$")
# Fields that are meaningless alone (card C5-10): both present or both absent, never one. A
# half-identity is a protocol violation, not a legacy client.
PAIRED_FIELDS: tuple[tuple[str, str], ...] = (("session", "battle_id"),)
# A client-session nonce: hex, no separators, 1..16 chars (case-insensitive).
SESSION_RE = re.compile(r"^[0-9A-Fa-f]{1,16}$")

# event -> (required fields, optional fields); docs/protocol.md §3.2
EVENTS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "hello": ({"rom_type": "str", "party": "list"},
              {"game": "str", "player": "str", "ot_id": "int", "panel": "bool", "panel_abi": "int", "sfx": "bool",
               "patch": "bool",
               "version": "str", "client": "str", "badges": "int", "has_pokeballs": "bool",
               "trainer_name": "str", "pc_boxes": "list", "area_id": "str", "loc_name": "str",
               "rom_sha1": "str", "caps": "dict", "rom_content": "dict",
               "artifact_kind": "str", "foundation": "str",
               # card C5-10b capability declaration
               "battle_identity": "bool"}),
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
    # reason vocabulary (free text on the wire): KEY_CHANGE_REASONS
    "key_change": ({"old_key": "key", "new_key": "key"},
                   {"reason": "str", "new_species": "int", "new_nickname": "str"}),
    # battle_id is OPTIONAL on the wire (card C5-10): Gen 1/Gen 2/old Gen 3 clients never send
    # it; the new Gen 3 client always does and requires it back on replace_rival_team.
    "trainer_battle_start": ({"trainer_id": "int"}, {"battle_id": "battle_id", "session": "session"}),
    "rival_team_replaced": ({"trainer_id": "int", "species_ids": "list"}, {"error": "str"}),
    "stats_cache": ({"key": "key", "stats": "dict"}, {}),
    "sync_retrieve_done": ({"key": "key"}, {}),
    "sync_retrieve_failed": ({"key": "key"}, {}),
    "box_mon_failed": ({"key": "key"}, {"reason": "str"}),
    "memorialize_done": ({"key": "key"}, {"box": "int"}),
    "memorialize_failed": ({"key": "key"}, {"reason": "str"}),
    "trade_request": ({}, {}),
    # Gen 1 in-game receptionist (companion patch): the game asks which slots are eligible,
    # then offers one; the reply bytes must land within the receptionist's 30/180-frame waits
    "trade_query": ({}, {}),
    "trade_offer": ({"slot": "int"}, {}),
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

# docs/protocol.md §3.2: the `reason` values a client may send; unknown ones are still accepted
KEY_CHANGE_REASONS = ("nature_change", "evolution", "npc_trade", "trade_undo", "transform", "apex_chip")

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
    "replace_rival_team": ({"trainer_id": "int", "n": "int", "blobs_hex": "list"},
                           {"source": "str", "battle_id": "battle_id", "session": "session"}),
    "show_choices": ({"token": "str", "options": "list", "text": "str"}, {}),
    "show_menu": ({"token": "str", "text": "str"}, {"slot": "int", "blob_hex": "hex"}),
    "trade_mask": ({"mask": "int"}, {}),
    "trade_offer_ack": ({"ok": "bool"}, {}),
    "choose_mon": ({"token": "str"}, {}),
    "apply_trade": ({"slot": "int", "blob_hex": "hex", "old_key": "key", "token": "str"}, {"partner_name": "str"}),
    "ghost_pos": ({}, {}),
    "link_panel": ({"rows": "list"}, {}),
    # one-way replies to key_change (docs/protocol.md §5): no ACKS row, nothing to answer
    "key_change_ack": ({"old_key": "key", "new_key": "key", "migrated": "bool"}, {}),
    "key_change_rejected": ({"old_key": "key", "new_key": "key", "reason": "str"}, {}),
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
        return isinstance(value, str) and bool(KEY_RE.fullmatch(value))
    if kind == "hex":
        return isinstance(value, str) and bool(HEX_RE.fullmatch(value)) and len(value) > 0
    if kind == "battle_id":
        return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2 ** 32
    if kind == "session":
        return isinstance(value, str) and 0 < len(value) <= 16 and bool(SESSION_RE.fullmatch(value))
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
    for left, right in PAIRED_FIELDS:
        if (left in msg) != (right in msg):
            problems.append(f"{name}: {left!r} and {right!r} must both be present or both absent")
        elif left in msg and (msg[left] is None or msg[right] is None):
            # present-but-null is a violation, not "absent": None is a value the contract does
            # not allow (C5-11c minor)
            problems.append(f"{name}: {left!r}/{right!r} present but null")
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
