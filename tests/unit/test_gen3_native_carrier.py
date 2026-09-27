"""Public native-client carrier controls; fake bus, no emulator qualification."""

import pytest
from lupa import lua54

from tests.unit import test_gen3_native as model
from tests.unit.test_gen3_native_trade import TradeNativeWorld


@pytest.fixture(autouse=True)
def bizhawk_lua(monkeypatch):
    monkeypatch.setattr(model, "lupa", lua54)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_frlg_config_binds_control_epoch_and_npc_at_a_safe_checkpoint(title):
    w = TradeNativeWorld(capability=23, title=title)
    assert w.native.trade_capable(w.native)
    control = w.n["BASE"] + 0x800  # producer ABI2 CONTROL, independently fixed contract
    w.output.clear()
    w.native.config(w.native, w.lua.table(overworld_presence=False, pc_trade_npc=True))
    assert w.output == []
    w.safe = False
    w.service()
    assert w.output == []
    w.safe = True
    w.service()
    assert w.read(control, 4) == w.read(w.n["BASE"] + 0x44, 4) == 0x12345678
    assert w.read(control + 8, 1) == 1
    w.native.config(w.native, w.lua.table(pc_trade_npc=False))
    w.service()
    assert w.read(control + 8, 1) == 0


def test_frlg_npc_counter_uses_all_32_bits_and_does_not_replay_old_edges():
    w = TradeNativeWorld(capability=23)
    control = w.n["BASE"] + 0x800
    w.native.config(w.native, w.lua.table(pc_trade_npc=True, overworld_presence=False))
    w.service()
    w.put(control + 4, 255, 4)
    w.service()  # discontinuity is a baseline, not an interaction
    assert w.events == []
    w.put(control + 4, 256, 4)
    w.service()
    assert [event for event, _ in w.events] == ["trade_request"]
    w.service()
    assert len(w.events) == 1
    w.put(control + 4, 0, 4)
    w.service()
    assert len(w.events) == 1
    w.put(control, 0xBAD, 4)
    w.put(control + 4, 1, 4)
    w.service()
    assert len(w.events) == 1, "a foreign CONTROL epoch cannot originate a request"


@pytest.mark.parametrize("method,opcode,result,event,field", [
    ("show_choices", 22, 0, "menu_result", "choice"),
    ("choose_mon", 20, 1, "mon_chosen", "slot"),
    ("show_menu", 17, 1, "menu_result", "choice"),
])
def test_carrier_reports_only_the_matching_native_ack(method, opcode, result, event, field):
    w = TradeNativeWorld(capability=23)
    cmd = w.lua.table(token="carrier-token", text="Trade?", options=w.lua.table("Trade", "Say hey"))
    job = getattr(w.native, method)(w.native, cmd)
    w.service()
    assert job.posted and w.read(w.n["BASE"] + 6, 2) == opcode
    w.put(w.n["BASE"] + 6, 0, 2)  # native owns asynchronous UI, no completion yet
    w.put(w.n["BASE"] + 10, 1, 2)
    w.service()
    assert w.events == []
    w.ack(result=result)
    w.service()
    assert [(name, fields.token, fields[field]) for name, fields in w.events] == [
        (event, "carrier-token", result)
    ]


def test_waiting_trade_yields_to_other_jobs_and_bounds_expensive_reads():
    w = TradeNativeWorld(capability=23)
    reads = []
    original = w.native_io.read_bytes

    def read(address, size):
        if address == w.ram["PARTY_BASE"]:
            reads.append(w.frame)
        return original(address, size)

    w.native_io.read_bytes = read
    prepare = w.native.prepare_trade(w.native, w.lua.table(
        token="wait", old_key=w.old_key, slot=0, dispatch_deadline=w.frame + 60
    ), lambda *_: None, lambda: True)
    reads.clear()
    w.battle = True  # trade field check closed; MODEL general write checkpoint remains open
    sound = w.native.play_sound(w.native, 25)
    w.service()
    assert not prepare.posted and sound.posted, "held trade must not block other native jobs"
    w.ack()
    for _ in range(6):
        w.frame += 1
        w.service()
    assert len(reads) <= 2, "a held trade must not decode the full party every frame"
    w.battle = False
    w.service()
    assert prepare.posted, "resume must perform a fresh safe dispatch"


def test_carrier_stage_cannot_publish_an_opcode_before_dispatch_finishes():
    w = TradeNativeWorld(capability=23)
    job = w.native.show_menu(w.native, w.lua.table(token="t", text="Trade?"))
    job.stages[1][1] = w.n["BASE"] + 6  # a future malformed staging job
    w.output.clear()
    w.service()
    assert not job.posted and w.read(w.n["BASE"] + 6, 2) == 0
    assert w.output == []
