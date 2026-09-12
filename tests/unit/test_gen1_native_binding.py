"""Native selection cannot widen an owned run's immutable cartridge contract."""
import pytest

from server.gen1_native_binding import install_native_execution
from server.protocol_journal import JournalError
from tests.unit.test_gen1_runtime_trade import case  # noqa: F401


@pytest.mark.parametrize("roms",[None,{}, {"a":b""}, {"a":bytearray(),"b":bytearray()}, {"a":b"","b":b""}])
def test_missing_mutable_or_wrong_rom_images_do_not_select_native_execution(case,roms):  # noqa: F811
    before=case.runtime.journal.snapshot()
    with pytest.raises((JournalError,ValueError)):install_native_execution(case.runtime,roms=roms)
    assert case.runtime.verify_operation_execution is None
    assert case.runtime.journal.snapshot()==before


def test_existing_native_policy_cannot_be_silently_replaced(case):  # noqa: F811
    policy=lambda *args:None
    case.runtime.verify_operation_execution=policy
    with pytest.raises(JournalError):install_native_execution(case.runtime,roms={"a":b"","b":b""})
    assert case.runtime.verify_operation_execution is policy


def test_changed_contract_cannot_select_native_execution(case):  # noqa: F811
    case.runtime.contract["players"]["a"]["capabilities"]["pc_trade"]=False
    with pytest.raises(JournalError,match="contract"):
        install_native_execution(case.runtime,roms={"a":b"","b":b""})
    assert case.runtime.verify_operation_execution is None
