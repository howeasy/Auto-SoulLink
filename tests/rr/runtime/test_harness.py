import pytest
from lupa import LuaError

from tests.rr.runtime.rr_harness import HarnessError, RRHarness


def test_real_modules_and_callback_are_loaded(rr_repo):
    h = RRHarness(rr_repo)
    h.step(31)
    assert h.M.profile_name == "radical_red"
    assert h.MB.present()
    assert h.events("hello")[0]["party"][0]["key"] == h.key(111)
    assert len(h.events("tick")) == 1
    for module, method, relative in [
        ("memory_gba", "forceFaint", "lua/memory_gba.lua"),
        ("mailbox", "poll", "lua/mailbox.lua"),
    ]:
        function = h.lua.globals().package.loaded[module][method]
        h.lua.globals()._TEST_FUNCTION = function
        source = h.lua.eval('debug.getinfo(_TEST_FUNCTION,"S").source')
        assert source.replace("\\", "/") == "@" + (rr_repo / relative).as_posix()


def test_canary_failure_is_not_silently_accepted(rr_repo):
    h = RRHarness(rr_repo)
    guard = h.canary(0x02005000)
    h.lua.globals().memory.write_u8(guard[0], 0)
    with pytest.raises(HarnessError, match="canary changed"):
        h.check_canaries(guard)


def test_production_cannot_write_rom(rr_repo):
    h = RRHarness(rr_repo)
    with pytest.raises(LuaError, match="outside synthetic RAM"):
        h.lua.globals().memory.write_u8(0x08000000, 0)
    with pytest.raises(HarnessError, match="writes="):
        h.assert_healthy()


def test_refusal_ack_uses_the_actual_posted_sequence(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.command("box_mon", key=h.key(111))
    h.step()
    pending = h.pending_native()
    assert pending["opcode"] == 24
    h.engine_ack(ok=False, reason=4)
    assert h.MB.poll(pending["seq"]) == (h.MB.ST_FAIL, 4)


@pytest.mark.parametrize("beacon", ["absent", "abi1"])
def test_unpatched_or_stale_companion_startup_does_not_write_ram(rr_repo, beacon):
    h = RRHarness(rr_repo, load=False)
    if beacon == "absent":
        h.seed_u32(0x0203F800, 0)
    else:
        h.seed_u16(0x0203F804, 1)
    before = len(h.lua.globals()._RR_WRITES)
    h.load_client(expect_patch=False)
    h.command("config", overworld_presence=False, battle_calc=True)
    h.command("force_faint", key=h.key(111))
    h.step(35)
    assert not h.MB.present()
    assert not h.events("hello")
    assert len(h.lua.globals()._RR_WRITES) == before
    assert h.u16(int(h.M.PARTY_BASE) + h.M.OFF_HP) == 50
    assert all("party" not in event for event in h.events("tick"))
