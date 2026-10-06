"""Polished box executor: EGG and MAIL refusals at the EXECUTOR level (lua/gen2/polished_overworld.lua
`O.boxes` deposit / withdraw), independent of the wire filters that keep eggs off the normal path.

  * deposit refuses an egg target, and mail on the removed slot or any LATER party slot (SwapPartyMons swaps
    sPartyMon1Mail, engine/pc/bills_pc.asm:289-297, and SLink never shifts that SRAM); mail on an EARLIER slot
    is fine and untouched
  * withdraw refuses a boxed EGG record and a boxed record holding MAIL (native Polished never lets a
    mail-holding mon into a box: bills_pc.asm:135-139 PCSWAP_HOLDING_MAIL; ItemIsMail is item >= FIRST_MAIL $F5)
  * every refusal writes ZERO bytes and leaves the party count/bytes alone; an ordinary mon still withdraws
  * RED CONTROL per guard: the guard is removed from the module source in process and its test goes red
"""
from __future__ import annotations

import json

import pytest

from tests.unit import test_polished_withdraw_path as twp
from tests.unit.test_polished_withdraw_path import boxed, boxed_mon, options, record_bytes, withdraw
from tests.unit.test_polished_write_path import (
    PARTY_MONS,
    REPO,
    SYM,
    Rig,
    _pair,
    key_of,
    party,
)

lupa = pytest.importorskip("lupa")

MAIL_IDS = json.loads((REPO / "data/games/polished_crystal/items.json").read_text(encoding="utf-8"))["mail_ids"]
FIRST_MAIL = 0xF5
assert min(MAIL_IDS) == FIRST_MAIL and max(MAIL_IDS) == 0xFE
OTS, NICKS = SYM["wPartyMonOTs"][1], SYM["wPartyMonNicknames"][1]

# the withdraw tests' mutant loader injects no `mail` table (the shared RED predates it): add it
RED_MAIL = twp.RED.replace("move_pp = MOVE_PPT})", "move_pp = MOVE_PPT, mail = MAIL_SET})")
assert RED_MAIL != twp.RED

# the exact guard text each red control removes (a mutation that does not apply fails loudly in twp.build)
EGG_DEPOSIT = "if m.key == key and not m.is_egg then"
MAIL_DEPOSIT = "if later.slot >= slot and mail[later.held_item] then"
EGG_WITHDRAW = "if found.is_egg then"
MAIL_WITHDRAW = "if mail[found.held_item] then"


def mutated(rig, monkeypatch, old, new):
    monkeypatch.setattr(twp, "RED", RED_MAIL)
    rig.lua.globals().MAIL_SET = rig.lua.table_from(dict.fromkeys(MAIL_IDS, True))
    return twp.build(rig, [(old, new)])


def raw_of(rig, boxes):
    return rig.lua.eval("function(t) local m = getmetatable(t) return m and m.__index or t end")(boxes)


def call(rig, boxes, name, key):
    """boxes.<name>('<key>') from inside Lua so the key is a real Lua string (as the client passes it)."""
    return rig.lua.eval(f"function(b, k) return b.{name}('' .. k) end")(raw_of(rig, boxes), key)


def deposit(rig, key, boxes=None):
    return call(rig, rig.overworld().boxes if boxes is None else boxes, "deposit", key)


def party_image(rig, n):
    """Every byte of the first `n` party slots: record, OT field, nickname, plus the count."""
    mem = rig.mem
    return ([mem[PARTY_MONS + i] for i in range(n * 48)], [mem[OTS + i] for i in range(n * 11)],
            [mem[NICKS + i] for i in range(n * 11)], rig.count())


def mail_party(item, slot):
    mons = party()
    mons[slot]["held_item"] = item
    return mons


# ── withdraw: a boxed EGG ──────────────────────────────────────────────────────────────────────────────────

def egg_rig():
    mons = party()
    mon = boxed_mon()
    mon["is_egg"] = True
    rig = Rig(mons)
    options(rig)
    boxed(rig, mon)
    return rig, mons, mon


def test_withdraw_refuses_a_boxed_egg():
    rig, mons, mon = egg_rig()
    before = party_image(rig, 3)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is None and "egg in the box" in why, (done, why)
    assert rig.writes() == [] and rig.count() == 3 and party_image(rig, 3) == before


def test_red_control_without_the_egg_guard_a_boxed_egg_is_not_refused_by_name(monkeypatch):
    rig, _, mon = egg_rig()
    path = mutated(rig, monkeypatch, EGG_WITHDRAW, "if false then")
    done, why = _pair(call(rig, path, "withdraw", key_of(mon)))
    assert not (done is None and "egg in the box" in str(why)), "the egg guard is not load-bearing"
    assert done is True or rig.writes(), (done, why)


# ── withdraw: a boxed MAIL holder ────────────────────────────────────────────────────────────────────────

def mail_rig(item):
    mons = party()
    mon = boxed_mon()
    mon["held_item"] = item
    rig = Rig(mons)
    options(rig)
    boxed(rig, mon)
    return rig, mons, mon


@pytest.mark.parametrize("item", [FIRST_MAIL, 0xFA, 0xFE])
def test_withdraw_refuses_a_boxed_mail_holder(item):
    rig, _, mon = mail_rig(item)
    assert item in MAIL_IDS
    before = party_image(rig, 3)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is None and "mail in the box" in why, (done, why)
    assert rig.writes() == [] and rig.count() == 3 and party_image(rig, 3) == before


def test_red_control_without_the_mail_guard_a_boxed_mail_holder_lands_without_its_mail(monkeypatch):
    rig, _, mon = mail_rig(FIRST_MAIL)
    path = mutated(rig, monkeypatch, MAIL_WITHDRAW, "if false then")
    done, why = _pair(call(rig, path, "withdraw", key_of(mon)))
    assert done is True, f"the mail guard is not load-bearing: {why}"
    assert rig.count() == 4


# ── withdraw: no over-refusal ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("item", [0, 1, FIRST_MAIL - 1])
def test_withdraw_still_lands_an_ordinary_non_egg_non_mail_mon(item):
    rig, mons, mon = mail_rig(item)
    assert item not in MAIL_IDS
    done, note = _pair(withdraw(rig, key_of(mon)))
    assert done is True, note
    assert rig.count() == 4 and len(rig.writes()) == 48 + 11 + 11 + 1 + 2


def test_red_control_a_blanket_mail_guard_would_over_refuse(monkeypatch):
    """The no-over-refusal tests bite: a guard that refuses every held item breaks the control."""
    rig, _, mon = mail_rig(FIRST_MAIL - 1)
    path = mutated(rig, monkeypatch, MAIL_WITHDRAW, "if found.held_item ~= 0 then")
    done, _ = _pair(call(rig, path, "withdraw", key_of(mon)))
    assert done is not True


# ── withdraw into a party that holds mail ──────────────────────────────────────────────────────────────────

def test_withdraw_appends_without_disturbing_an_earlier_mail_holder():
    mons = mail_party(FIRST_MAIL, 0)
    mon = boxed_mon()
    rig = Rig(mons)
    options(rig)
    boxed(rig, mon)
    before = party_image(rig, 3)
    done, note = _pair(withdraw(rig, key_of(mon)))
    assert done is True, note
    after = party_image(rig, 3)
    assert after[:3] == before[:3], "an earlier slot changed"
    assert after[3] == 4 and record_bytes(rig, 0)[1] == FIRST_MAIL
    records = [w["addr"] for w in rig.writes() if w["domain"] == "System Bus" and w["addr"] >= PARTY_MONS]
    assert min(records) == PARTY_MONS + 3 * 48, "a write landed below the appended slot"


# ── deposit ──────────────────────────────────────────────────────────────────────────────────────────────

def test_deposit_refuses_an_egg_target():
    mons = party()
    mons[1]["is_egg"] = True
    rig = Rig(mons)
    before = party_image(rig, 3)
    done, why = _pair(deposit(rig, key_of(mons[1])))
    assert done is None and "key not in party" in why, (done, why)
    assert rig.writes() == [] and party_image(rig, 3) == before


def test_red_control_without_the_egg_guard_an_egg_is_deposited(monkeypatch):
    mons = party()
    mons[1]["is_egg"] = True
    rig = Rig(mons)
    path = mutated(rig, monkeypatch, EGG_DEPOSIT, "if m.key == key then")
    done, why = _pair(call(rig, path, "deposit", key_of(mons[1])))
    assert done is True, f"the egg guard is not load-bearing: {why}"


@pytest.mark.parametrize("mail_slot,target,text", [(1, 1, "slot 1"), (2, 1, "slot 2"), (2, 0, "slot 2")])
def test_deposit_refuses_mail_on_the_selected_or_a_later_slot(mail_slot, target, text):
    mons = mail_party(FIRST_MAIL, mail_slot)
    rig = Rig(mons)
    before = party_image(rig, 3)
    done, why = _pair(deposit(rig, key_of(mons[target])))
    assert done is None and "sPartyMail is never shifted" in why and text in why, (done, why)
    assert rig.writes() == [] and party_image(rig, 3) == before


def test_deposit_allows_mail_on_an_earlier_slot_and_leaves_it_alone():
    mons = mail_party(0xFE, 0)
    rig = Rig(mons)
    mail_record = record_bytes(rig, 0)
    mail_ot = [rig.mem[OTS + i] for i in range(11)]
    done, note = _pair(deposit(rig, key_of(mons[1])))
    assert done is True, note
    assert rig.count() == 2
    assert record_bytes(rig, 0) == mail_record and [rig.mem[OTS + i] for i in range(11)] == mail_ot
    assert record_bytes(rig, 0)[1] == 0xFE


@pytest.mark.parametrize("old,new,mail_slot,target", [
    (MAIL_DEPOSIT, "if false then", 1, 1),                                         # guard removed
    (MAIL_DEPOSIT, "if later.slot == slot and mail[later.held_item] then", 2, 1),  # LATER slots forgotten
])
def test_red_control_deposit_mail_guard_variants_land_the_deposit(monkeypatch, old, new, mail_slot, target):
    mons = mail_party(FIRST_MAIL, mail_slot)
    rig = Rig(mons)
    path = mutated(rig, monkeypatch, old, new)
    done, why = _pair(call(rig, path, "deposit", key_of(mons[target])))
    assert done is True, f"the mail guard is not load-bearing: {why}"


def test_red_control_a_guard_over_the_earlier_slot_is_over_refusal(monkeypatch):
    """Refusing mail on EARLIER slots too (a `true` scope) would break the allowed-earlier test."""
    mons = mail_party(0xFE, 0)
    rig = Rig(mons)
    path = mutated(rig, monkeypatch, MAIL_DEPOSIT, "if mail[later.held_item] then")
    done, _ = _pair(call(rig, path, "deposit", key_of(mons[1])))
    assert done is None
