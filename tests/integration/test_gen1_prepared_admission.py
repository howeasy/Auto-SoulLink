"""Reproduced final artifacts bound to a real journal/session gate; gameplay stays held."""
import copy
import asyncio
import json
from types import SimpleNamespace
import pytest

from server.gen1_cartridge_profiles import validate_runtime_contract
from server.gen1_command_receipts import Gen1ReceiptPolicy
from server.gen1_prepared_cartridges import PreparedCartridges
from server.gen1_runtime import Gen1Runtime
from server.gen1_runtime_state import state_type_for
from server.gen1_run_config import configure_runtime,open_runtime,read_configuration
from server.identity_registry import IdentityRegistry
from tests.integration.test_gen1_prepared_cartridges import prepared
from tests.unit.test_gen1_runtime_server import RUN_ID,RuntimeCase


@pytest.mark.parametrize("variants",[("red","blue"),("blue","yellow"),("yellow","yellow")])
def test_reproduced_pair_admits_only_its_exact_metadata_without_widening_default_catalog(variants,tmp_path,monkeypatch):
    directory=prepared(tmp_path,variants);cartridges=PreparedCartridges(directory)
    contract=cartridges.contract()
    with pytest.raises(ValueError):validate_runtime_contract(contract)
    model_dir=tmp_path/"model";model_dir.mkdir()
    model=RuntimeCase(model_dir,variants);model.close()
    runtime_dir=directory
    initial=state_type_for(cartridges).initial(model.rules,IdentityRegistry(RUN_ID).document(),contract,data_dir=runtime_dir)
    options=dict(contract=contract,data_dir=runtime_dir,run_id=RUN_ID,validate_event=lambda *args:None,
        validate_receipt=Gen1ReceiptPolicy(dict(zip(("a","b"),variants))),verify_reconciliation=lambda *args:None,
        clock=lambda:10)
    runtime=Gen1Runtime(runtime_dir/"gen1.sqlite3",initial_state=initial,prepared_cartridges=cartridges,**options)
    try:
        configuration=configure_runtime(runtime)
        assert configuration["prepared_artifacts"]=="."
        assert read_configuration(runtime_dir)==configuration
        before=runtime.journal.snapshot().state["rules"]
        for player in ("a","b"):
            message=model.hello(player);message["gen1_metadata"]["cartridge"]=contract["players"][player]
            response=runtime.process(message,object())
            assert response["ack"]=="ACK" and response["commands"]==[]
            assert response["admission"]["scope"]=="metadata_only_no_physical_readiness"
        assert runtime.state().barrier.ticket() is None and runtime.journal.snapshot().state["rules"]==before
        from server import manager
        monkeypatch.setattr(manager,"MANAGER_DIR",str(runtime_dir.parent))
        monkeypatch.setattr(manager,"_load_registry",lambda:[{"run_id":runtime_dir.name,"name":"Prepared UPR","tcp_port":54321}])
        request=SimpleNamespace(match_info={"run_id":runtime_dir.name,"player":"b"},host="127.0.0.1:8090")
        response=asyncio.run(manager.RunManager("127.0.0.1").handle_launcher(request))
        assert response.status==200 and "held_service" in response.text
        assert contract["players"]["b"]["final_rom_sha1"] in response.text
    finally:runtime.close()
    # A reopened owner must supply independently revalidated artifacts again.
    with pytest.raises(ValueError):Gen1Runtime(runtime_dir/"gen1.sqlite3",**options)
    reopened=open_runtime(runtime_dir)
    try:
        assert reopened.state().barrier.ticket() is None
        wrong=copy.deepcopy(contract);wrong["players"]["a"]["final_rom_sha1"]="f"*40
        with pytest.raises(ValueError):cartridges.validate_contract(wrong)
    finally:reopened.close()
