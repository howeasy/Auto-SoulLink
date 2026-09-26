"""MODEL controls for the gen2_new `gen2_faint_active` duo scenario (roadmap row 7, linked_faint_active):
lua/tests/duo/scenario_gen2_faint_active.lua (the marker contract in its header), its duo_gen2_main.lua
hooks and the gen2_faint_inputs.lua hold/any_move/observed options, under lupa, no emulator.
Authoring evidence only; the PHYSICAL proof is the duo receipt.
"""
from __future__ import annotations

import json

import pytest
from lupa import LuaRuntime

from tests.unit import test_gen2_duo_driver as driver_module
from tests.unit.test_gen2_duo_driver import (
    FAINT,
    FAINT_INPUTS,
    KEY,
    MENU,
    ROOT,
    SCENARIO,
    faint_lines,
    point,
    run_driver,
    ui,
)

ACTIVE = ROOT / "lua/tests/duo/scenario_gen2_faint_active.lua"
j = json.dumps


def active_verdict(lines):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    link = lua.execute(SCENARIO.read_text(encoding="utf-8"))
    faint = lua.execute(FAINT.read_text(encoding="utf-8"))
    active = lua.execute(ACTIVE.read_text(encoding="utf-8"))
    problems, receipt = active.verdict(lua.table_from(lines), json_codec, link.verdict, faint.verdict)
    return list(problems.values()), receipt


def a_lines():
    lines = [x.replace('"scenario": "gen2_faint"', '"scenario": "gen2_faint_active"') for x in faint_lines("a")]
    at = next(i for i, x in enumerate(lines) if x.startswith("ENGINE_FAINT "))
    return lines[:at] + ["B_ACTIVE " + j({"frame": 2000})] + lines[at:]


def b_lines():
    base = faint_lines("b")
    head = base[:base.index(next(x for x in base if x.startswith("RX force_faint")))]   # through LINK_SAVE
    span = {"domain": "System Bus", "status": "written", "why": "battle_hold", "batch_size": 4}
    record = "00" * 32 + "0000" + "00" * 14
    return head + [
        "LINKED_ACTIVE " + j({"frame": 2000, "key": KEY, "slot": 1, "cur_battle_mon": 1, "battle_mon_species": 16,
                              "battle_mode": 1, "battle_type": 0, "link_mode": 0}),
        "RX force_faint key=" + KEY,
        "BATTLE_HOLD_WRITE " + j({"frame": 3000, "seq": 1, "key": KEY, "slot": 1, "active_slot": 1,
                                  "kind": "battle_faint", "ok": True, "pc": 0x4194, "hrom_bank": 15,
                                  "battle_hp_before_hex": "000c", "battle_hp_after_hex": "0000",
                                  "hp_before_hex": "000c", "hp_after_hex": "0000", "status_after_hex": "00",
                                  "action_before_hex": "00", "action_after_hex": "01",
                                  "log": [dict(span, batch_index=i) for i in range(1, 5)]}),
        "BATTLE_TRACE " + j({"seq": 2, "what": "faint", "frame": 3000}),
        "ENGINE_FAINT " + j({"frame": 3000, "site_id": "battle_faint", "cause": "battle", "key": KEY, "slot": 1}),
        "NEXT_MON " + j({"frame": 3100}),
        "REPLACED " + j({"frame": 3200, "active_slot": 0, "hp": 17}),
        "BATTLE_TRACE " + j({"seq": 3, "what": "enemy_turn", "frame": 3300}),
        "LINKED_HP_STATUS 0000 00",
        "MEMORIAL_PREIMAGE " + j({"frame": 3500, "key": KEY, "slot": 1, "raw_hex": record, "ot_raw_hex": "80" * 11,
                                  "nickname_raw_hex": "81" * 11, "species_marker": 16}),
        "MEMORIAL_ACK " + j({"frame": 3501, "event": "memorialize_done", "key": KEY, "box": 13}),
        base[-1],   # the final SAVE_WITNESS
    ]


def edit(lines, tag, **changes):
    out = []
    for line in lines:
        if line.startswith(tag + " "):
            value = json.loads(line[len(tag) + 1:])
            value.update(changes)
            line = f"{tag} {j(value)}"
        out.append(line)
    return out


def without(lines, prefix):
    return [x for x in lines if not x.startswith(prefix)]


def moved(lines, prefix, before):
    """`prefix`'s line re-inserted just before the first line starting with `before`."""
    line = next(x for x in lines if x.startswith(prefix))
    rest = [x for x in lines if x is not line]
    at = next(i for i, x in enumerate(rest) if x.startswith(before))
    return rest[:at] + [line] + rest[at:]


@pytest.mark.parametrize("player,lines", [("a", a_lines()), ("b", b_lines())])
def test_active_verdict_passes_each_complete_half(player, lines):
    problems, receipt = active_verdict(lines)
    assert problems == [], problems
    assert receipt["schema"] == "gen2-duo-faint-active-v1" and receipt["player"] == player and receipt["key"] == KEY


def test_b_receipt_carries_the_engine_order():
    _, receipt = active_verdict(b_lines())
    assert receipt["battle_write"]["action_after_hex"] == "01"
    assert dict(receipt["native_faint"].items()) == {"seq": 2, "what": "faint", "frame": 3000}
    assert receipt["replaced"]["active_slot"] == 0


def enemy_between():
    lines = b_lines()
    at = next(i for i, x in enumerate(lines) if x.startswith("BATTLE_TRACE "))
    lines = edit(lines, "BATTLE_TRACE", seq=3)
    return lines[:at] + ["BATTLE_TRACE " + j({"seq": 2, "what": "enemy_turn", "frame": 3000})] + lines[at:]


@pytest.mark.parametrize("lines,match", [
    (without(a_lines(), "B_ACTIVE"), "missing B_ACTIVE"),
    (moved(a_lines(), "B_ACTIVE", "LINK_SAVE"), "B_ACTIVE before LINK_SAVE"),
    (moved(a_lines(), "B_ACTIVE", "FAINT_SENT"), "did not wait for B_ACTIVE"),
    (without(a_lines(), "FAINT_SENT"), "missing FAINT_SENT"),
    (without(b_lines(), "LINKED_ACTIVE"), "missing LINKED_ACTIVE"),
    (edit(b_lines(), "LINKED_ACTIVE", cur_battle_mon=0), "not the linked catch as the active"),
    (edit(b_lines(), "LINKED_ACTIVE", link_mode=1), "not the linked catch as the active"),
    (edit(b_lines(), "LINKED_ACTIVE", battle_mon_species=19), "not the linked catch as the active"),
    (moved(b_lines(), "RX force_faint", "LINKED_ACTIVE"), "before LINKED_ACTIVE"),
    (without(b_lines(), "BATTLE_HOLD_WRITE"), "missing BATTLE_HOLD_WRITE"),
    (edit(b_lines(), "BATTLE_HOLD_WRITE", ok=False), "write failed"),
    (edit(b_lines(), "BATTLE_HOLD_WRITE", active_slot=0), "missed the active slot"),
    (edit(b_lines(), "BATTLE_HOLD_WRITE", battle_hp_after_hex="0003"), "did not zero"),
    (edit(b_lines(), "BATTLE_HOLD_WRITE", action_after_hex="00"), "not USEITEM"),
    (edit(b_lines(), "BATTLE_HOLD_WRITE", log=[]), "four-span"),
    (enemy_between(), "not HandlePlayerMonFaint"),
    (edit(b_lines(), "BATTLE_TRACE", frame=3001), "not in the write's frame"),
    (without(b_lines(), "BATTLE_TRACE"), "not HandlePlayerMonFaint"),
    (b_lines()[:-1] + ["BATTLE_TRACE " + j({"seq": 9, "what": "lost", "frame": 3400}), b_lines()[-1]], "whiteout"),
    (b_lines()[:-1] + ["FAINT_SENT " + j({"frame": 3000, "key": KEY, "seq": 30}), b_lines()[-1]], "commanded echo"),
    (moved(b_lines(), "ENGINE_FAINT", "BATTLE_HOLD_WRITE"), "not the commanded kill"),
    (without(b_lines(), "NEXT_MON"), "missing NEXT_MON"),
    (edit(b_lines(), "REPLACED", active_slot=1), "no living replacement"),
    (edit(b_lines(), "REPLACED", hp=0), "no living replacement"),
    ([x.replace("LINKED_HP_STATUS 0000 00", "LINKED_HP_STATUS 0005 00") for x in b_lines()], "HP 0000"),
    (without(b_lines(), "LINKED_HP_STATUS"), "missing LINKED_HP_STATUS"),
    (without(b_lines(), "MEMORIAL_ACK"), "no memorialize_done"),
    (moved(b_lines(), "MEMORIAL_PREIMAGE", "BATTLE_HOLD_WRITE"), "memorial out of order"),
    (edit(b_lines(), "SAVE_WITNESS", save_completed_frame=2900), "before the write"),
    (edit(b_lines(), "CLIENT", registered_sites=["battle_end"]), "lack battle_faint"),
], ids=["a-no-go", "a-go-early", "a-go-late", "a-no-send", "no-active", "active-other-slot", "active-link",
        "active-other-species", "rx-first", "no-write", "write-failed", "write-bench", "hp-left", "no-useitem",
        "no-spans", "foe-moved", "faint-later", "no-trace", "whiteout", "b-sent-faint", "faint-before-write",
        "no-next", "replaced-same", "replaced-dead", "readback-hp", "no-readback", "no-ack", "preimage-early",
        "save-before-write", "no-site"])
def test_active_verdict_refuses_a_tampered_or_reordered_half(lines, match):
    problems, receipt = active_verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


def test_the_active_scenario_needs_a_composed_battle_hold_before_any_input(tmp_path, monkeypatch):
    monkeypatch.setattr(driver_module, "DRIVER_FILES", driver_module.DRIVER_FILES + (ACTIVE.relative_to(ROOT).as_posix(),))
    lines, sim, _ = run_driver(tmp_path, scenario="gen2_faint_active", player="b")
    assert lines[-1] == "RESULT: FAIL (the production client composes no battle hold)", lines[-5:]
    assert not sim.inputs


# --- gen2_faint_inputs.lua: B's hold / any_move / observed options -------------------------------------

def driver(**opts):
    lua = LuaRuntime(unpack_returned_tuples=True)
    FI = lua.execute(FAINT_INPUTS.read_text(encoding="utf-8"))
    walk = lua.eval("{walk_direction=function() return 'Left' end}")
    return lua, FI.driver(walk, lua.table_from({}), lua.table_from({"target": 1, **opts}))


def step(lua, d, **fields):
    buttons, phase = d.step(point(lua, **fields))
    assert buttons is not None, phase
    pressed = sorted(k for k, v in buttons.items() if v)
    if pressed:
        for _ in range(12):
            d.step(point(lua, **fields))
    return pressed


def test_hold_idles_at_the_battle_menu_while_the_target_is_active_then_fights():
    held = {"on": True}
    lua, d = driver(hold=lambda *_: held["on"], any_move=True)
    on = {"active_slot": 1}
    assert step(lua, d, ui=ui("battle_menu", MENU, 2, 2)) == ["A"]            # the target is not out: PKMN
    for _ in range(50):
        assert step(lua, d, ui=ui("battle_menu", MENU, 1, 2), **on) == []  # held: no turn committed
    held["on"] = False
    assert step(lua, d, ui=ui("battle_menu", MENU, 1, 2), **on) == ["A"]   # FIGHT


def test_hold_never_blocks_the_switch_in():
    lua, d = driver(hold=lambda *_: True)
    assert step(lua, d, ui=ui("battle_menu", MENU, 1, 2)) == ["Right"]       # PKMN while the lead is out


def test_any_move_uses_a_tackle_only_target_instead_of_switching_out():
    """The write lands before DetermineMoveOrder, so B's committed move never runs; switching out would
    take the linked mon off the field."""
    lua, d = driver(any_move=True)
    on = {"active_slot": 1}
    assert step(lua, d, ui=ui("move_menu", ["TACKLE"]), **on) == ["A"]
    assert step(lua, d, ui=ui("move_menu", ["TACKLE", "GROWL"]), **on) == ["Down"]   # a status move first


def test_without_the_options_a_tackle_only_target_still_switches_out():
    lua, d = driver()
    assert step(lua, d, ui=ui("move_menu", ["TACKLE"]), active_slot=1) == ["B"]
