"""Reproduced local pair selects the composed native service; no emulator claim."""

import pytest

from server.gen1_launcher import NATIVE_FILES, configuration
from server.gen1_native_execution import NativeExecutionPolicy
from server.gen1_prepared_cartridges import PreparedCartridges
from server.gen1_run_config import create_runtime, open_runtime, read_configuration
from server.protocol_journal import JournalError
from tests.integration.test_gen1_prepared_cartridges import prepared
from tests.unit.test_gen1_sessions import contract


def test_reproduced_yellow_pair_selects_native_services_and_reopens_held(tmp_path):
    cartridges = PreparedCartridges(prepared(tmp_path))
    runtime = create_runtime(
        tmp_path,
        cartridges.contract(),
        prepared_cartridges=cartridges,
        native_trade=True,
    )
    try:
        assert (
            runtime.native_trade and runtime.trade and runtime.trade_driver and runtime.receptionist
        )
        assert isinstance(runtime.verify_operation_execution, NativeExecutionPolicy)
        assert runtime.verify_operation_execution.fallback is not None
        assert read_configuration(tmp_path)["native_trade"] is True
        for player in ("a", "b"):
            launch = configuration(runtime, player)
            assert launch["native_manifest"] == cartridges.manifest(player)
            assert set(NATIVE_FILES) <= {item["path"] for item in launch["files"]}
        with pytest.raises(JournalError, match="both native checkpoint"):
            runtime.trade.policy.policy.read_checkpoints()
        assert runtime.state().barrier.ticket() is None
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert runtime.native_trade and runtime.receptionist and runtime.trade_driver
        assert runtime.state().barrier.ticket() is None and not runtime.gate.sessions
    finally:
        runtime.close()


@pytest.mark.parametrize("free_service", [False, True])
def test_native_selection_never_infers_a_local_cartridge_artifact(tmp_path, free_service):
    with pytest.raises(JournalError, match="reproduced prepared"):
        create_runtime(
            tmp_path, contract("yellow", "yellow"), free_service=free_service, native_trade=True
        )
    assert not (tmp_path / "runtime.sqlite3").exists()
