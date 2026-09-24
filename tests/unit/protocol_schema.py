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

from server.adapters import foundation_for_rom_type

KEY_RE = re.compile(r"^[0-9A-F]{4}:[0-9A-F]{4}:[0-9A-F]{2}$|^[0-9A-F]{8}:[0-9A-F]{8}$", re.I)
HEX_RE = re.compile(r"^(?:[0-9A-Fa-f]{2})*$")

# event -> (required fields, optional fields); docs/protocol.md §3.2
EVENTS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "hello": ({"rom_type": "str", "party": "list"},
              {"game": "str", "player": "str", "ot_id": "int", "panel": "bool", "panel_abi": "int", "sfx": "bool",
               "patch": "bool",
               "version": "str", "client": "str", "badges": "int", "has_pokeballs": "bool",
               "trainer_name": "str", "pc_boxes": "list", "area_id": "str", "loc_name": "str",
               "rom_sha1": "str", "caps": "dict", "rom_content": "dict",
               "artifact_kind": "str", "foundation": "str", "trade_prepare": "bool"}),
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
    "trainer_battle_start": ({"trainer_id": "int"}, {}),
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
    "menu_result": ({"token": "str", "choice": "int"}, {"withdraw": "bool"}),
    # MAJOR-1 prepare round: the answer to apply_prepare (ok = this side can still take its APPLY)
    "apply_ready": ({"token": "str", "ok": "bool"}, {}),
    "mon_chosen": ({"token": "str", "slot": "int"}, {}),
    "trade_done": ({"new_key": "key", "new_species": "int"}, {"token": "str", "slot": "int", "uncertain": "bool"}),
    "status": ({"badges": "int"}, {}),
    "ghost_pos": ({}, {}),  # ints only; relayed opaquely
    "peer_interact": ({}, {}),
}
# trade_done{token, uncertain: true}: the side's native commit was entered but no DONE came
# (a reset, a result 2); its next party snapshot settles it (state.py _trade_evidence)
UNCERTAIN_TRADE_DONE = {"trade_done": ({"token": "str", "uncertain": "bool"}, {"slot": "int"})}
# tick's optional set also applies to safe
EVENTS["safe"] = ({}, dict(EVENTS["tick"][1]))

ENVELOPE = {"event": "str", "player": "str", "seq": "int"}

# docs/protocol.md §2.1/§2.2 step 1': the hello's pairing fields. The server DERIVES the
# foundation from rom_type (foundation_for_rom_type -- its own table, reused, not restated) and
# refuses a declared one that disagrees; a PRESENT artifact_kind must be one of these. Clients
# of a foundation in HELLO_DECLARES must also send both fields (their clients always do); Gen 3's
# reference client sends neither (§2.1), so it has no row. Data, not a game_id branch.
ARTIFACT_KINDS = ("clean", "overlay", "rand", "rand_overlay", "named", "companion")
HELLO_DECLARES = frozenset({
    "gen1_rby", "gen1_purergb",  # lua/gen1/client.lua:154, :1567; lua/gen1/entry.lua:395
    "gen2_gsc",                  # lua/gen2/client.lua:55, :614
})

# docs/protocol.md §3.2: the `reason` values a client may send; unknown ones are still accepted
KEY_CHANGE_REASONS = ("nature_change", "evolution", "npc_trade", "trade_undo", "transform", "apex_chip")

# cmd -> (required fields, optional fields); docs/protocol.md §5
COMMANDS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "noop": ({}, {}),
    # "phone": the O-29 tag (docs/protocol.md §5); only the Gen 2 client acts on it
    "force_faint": ({"key": "key"}, {"nickname": "str", "phone": "str"}),
    "force_explode": ({"key": "key"}, {"nickname": "str", "phone": "str"}),
    "box_mon": ({"key": "key"}, {}),
    "party_mon": ({"key": "key"}, {"nickname": "str", "stats": "dict"}),
    "memorialize": ({"key": "key"}, {}),
    "game_over": ({}, {}),
    "msgbox": ({"text": "str"}, {"fb": "str", "r": "int", "g": "int", "b": "int", "frames": "int",
                                 "phone": "str"}),
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
    "show_menu": ({"token": "str", "text": "str"}, {"slot": "int", "blob_hex": "hex"}),
    "trade_mask": ({"mask": "int"}, {}),
    "trade_offer_ack": ({"ok": "bool"}, {"token": "str"}),
    "choose_mon": ({"token": "str"}, {}),
    "apply_trade": ({"slot": "int", "blob_hex": "hex", "old_key": "key", "token": "str"}, {"partner_name": "str"}),
    "apply_prepare": ({"token": "str", "slot": "int", "old_key": "key"}, {}),
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
    "apply_prepare": ("apply_ready", "apply_ready"),
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
    table = EVENTS
    if msg["event"] == "trade_done" and msg.get("uncertain") is True:
        table = UNCERTAIN_TRADE_DONE           # a side that cannot vouch names no key
    problems = _validate("event", msg["event"], table, msg, extra_ok=not strict)
    return problems + _hello_pairing(msg) if msg["event"] == "hello" else problems


def _hello_pairing(msg: dict) -> list[str]:
    rom_type = msg.get("rom_type")
    derived = foundation_for_rom_type(rom_type) if isinstance(rom_type, str) else None
    if derived is None:
        return [f"hello: rom_type {rom_type!r} is not one the server routes"]
    problems = [f"hello: a {derived} client must declare {f!r}"
                for f in ("foundation", "artifact_kind") if derived in HELLO_DECLARES and f not in msg]
    if "foundation" in msg and msg["foundation"] != derived:
        problems.append(f"hello: foundation {msg['foundation']!r} but rom_type {rom_type!r} is {derived!r}")
    if "artifact_kind" in msg and msg["artifact_kind"] not in ARTIFACT_KINDS:
        problems.append(f"hello: artifact_kind {msg['artifact_kind']!r} not in {ARTIFACT_KINDS}")
    return problems


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
