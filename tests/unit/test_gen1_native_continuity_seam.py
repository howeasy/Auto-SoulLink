"""Source proof of the native-route continuity seam (closed by the B3 hooks; kept as the regression).

server/gen1_runtime.py `_service_continuity_enabled` returns `free_service and not native_trade`,
so a native-selected runtime omits `service_recovery` from HELLO and control responses
(server/durable_runtime.py:175-176, :266-267). The free-service client always installs its
continuity callback (lua/gen1_client_entry.lua: `service_continuity=free and service_continuity`),
and lua/durable_runtime.lua:310-316 then REQUIRES `service_recovery` to be a complete object on
every non-semantic response: the composed native client would fail on its first HELLO reply.

Proposed minimal frozen hook (for Root): `_service_continuity_enabled = lambda: self.free_service`,
with native constraints enforced in the continuity verifier (server/gen1_service_continuity):
refuse a player's continuity proof while that player has a pending native command, while any
trade is active or non-terminal, while the gen1-native-reattach verdict for the player is held,
or while the proof's native lease phase is not idle/released; the proof gains
`native={lease_phase, overlay_published:false, read_digest}` under the same held frame.
"""
import json
from pathlib import Path

import pytest

from server.gen1_prepared_cartridges import PreparedCartridges, stage_canonical_pair
from server.gen1_run_config import create_runtime
from server.gen1_runtime_admission import METADATA_SCHEMA, PROTOCOL

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
CLEAN = ROOT / LOCK["clean_roms"]["pokeyellow"]["filename"]
pytestmark = pytest.mark.skipif(not CLEAN.is_file(), reason="legal clean Yellow cartridge required")


def hello(runtime, player="a"):
    return runtime.process({
        "protocol": PROTOCOL, "run_id": runtime.journal.run_id, "player": player, "event": "hello", "seq": 0,
        "client_nonce": "1" * 32, "operation_id": "1" * 32, "context_generation": player * 32,
        "gen1_metadata": {"schema": METADATA_SCHEMA, "cartridge": runtime.contract["players"][player],
                          "save_identity": {"ot_id": "0000", "trainer_name": "SAME"}, "physical_instance": "1" * 32}}, object())


def test_native_selected_runtime_omits_service_recovery_that_the_free_service_client_requires(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    pair = PreparedCartridges(stage_canonical_pair(run / "prepared", {"a": CLEAN, "b": CLEAN}))
    runtime = create_runtime(run, pair.contract(), prepared_cartridges=pair, native_trade=True, free_service=True)
    try:
        # The seam is closed on this branch (hook 5): the native-selected free service offers continuity
        # and gen1_service_continuity refuses it unless the current admission's held read was released.
        assert runtime.free_service and runtime.native_trade and runtime._service_continuity_enabled() is True
        response = hello(runtime)
        assert response["ack"] == "ACK" and "recovery" in response
        assert response["service_recovery"]["schema"] == "slink-service-recovery-v1"
    finally:
        runtime.close()
    # The same client against a free-service-only runtime gets the document it requires.
    other = tmp_path / "plain"
    other.mkdir()
    plain_pair = PreparedCartridges(stage_canonical_pair(other / "prepared", {"a": CLEAN, "b": CLEAN}))
    plain = create_runtime(other, plain_pair.contract(), prepared_cartridges=plain_pair, native_trade=False, free_service=True)
    try:
        assert plain._service_continuity_enabled() is True
        assert hello(plain)["service_recovery"]["schema"] == "slink-service-recovery-v1"
    finally:
        plain.close()


def test_the_client_entry_installs_the_continuity_callback_for_every_free_service_launch():
    """Source pin of the client side of the seam: the callback is not conditional on the manifest."""
    source = (ROOT / "lua/gen1_client_entry.lua").read_text(encoding="utf-8")
    assert "service_continuity=free and service_continuity or nil" in source
    durable = (ROOT / "lua/durable_runtime.lua").read_text(encoding="utf-8")
    assert 'assert(JSON.kind(service)=="object" and service.schema=="slink-service-recovery-v1"' in durable
