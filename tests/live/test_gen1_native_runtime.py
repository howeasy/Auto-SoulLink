"""Production native service/windows/TCP; linked-run bootstrap remains explicit."""
import asyncio
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

import pytest

from server.adapters import get_adapter
from server.gen1_admission import CONTRACT_SCHEMA, cartridge_metadata
from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_native_binding import install_native_driver, install_native_execution
from server.gen1_native_policy import NativeTradePolicy
from server.gen1_runtime import Gen1Runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_staged_state import StagedGen1State
from server.identity_registry import IdentityContext, IdentityRegistry, IdentityWitness
from server.protocol import digest
from server.protocol_journal import JournalError
from server.save_identity import SaveIdentity
from server.server import SLinkServer
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState
from server.trade_coordinator import NAMESPACE
from tests.live.test_gen1_paired_native_trade import publish
from tests.unit.test_gen1_party_codec import make_blob
from server.gen1_party_codec import PartyCodec
from tools.build_gen1_companion import build
from tools.run_gb_gate import BIZHAWK_CONFIG, run_gate

ROOT=Path(__file__).resolve().parents[2]
pytestmark=[pytest.mark.live,pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE")!="1",reason="explicit live emulator lane required")]


@pytest.mark.parametrize("variants",[("yellow","yellow"),("red","blue"),("blue","yellow")],ids=lambda v:"-".join(v))
def test_actual_native_commands_use_owned_tcp_windows_and_both_verified_files(variants):
    asyncio.run(run_native_runtime(variants))


@pytest.mark.parametrize('variants',[('yellow','yellow'),('red','blue'),('blue','yellow')],ids=lambda v:'-'.join(v))
def test_original_receptionist_query_drives_saved_native_trade_over_tcp(variants):
    asyncio.run(run_native_runtime(variants,receptionist=True))


@pytest.mark.parametrize('choice,variants',[('cancel',('yellow','yellow')),('cable',('red','blue'))])
def test_receptionist_cancel_and_original_cable_club_return_without_slink_trade(choice,variants):
    asyncio.run(run_native_runtime(variants,receptionist=True,receptionist_choice=choice))


def test_socket_loss_during_native_animation_holds_both_contexts_without_reapplication():
    asyncio.run(run_native_runtime(("yellow","yellow"),disconnect=True))


@pytest.mark.parametrize("decision,variants",[("decline",("yellow","yellow")),("late",("red","blue"))])
def test_native_refusal_or_expired_consent_closes_both_participants_without_trading(decision,variants):
    asyncio.run(run_native_runtime(variants,decision=decision))


def test_late_native_renewal_cannot_attach_to_the_completed_or_next_command():
    asyncio.run(run_native_runtime(("yellow","yellow"),delayed=True))


def test_reproduced_yellow_pair_uses_native_runtime_and_recipient_rom_evolution(tmp_path):
    from server.gen1_prepared_cartridges import PreparedCartridges
    from tests.integration.test_gen1_prepared_cartridges import prepared
    from tests.integration.test_upr_pinned import PRESETS
    cartridges=PreparedCartridges(prepared(tmp_path,settings_changes=PRESETS["combined"]))
    asyncio.run(run_native_runtime(("yellow","yellow"),cartridges=cartridges,receptionist=True))


async def run_native_runtime(variants,*,disconnect=False,delayed=False,cartridges=None,decision="accept",receptionist=False,receptionist_choice='trade'):
    ui_only=receptionist and receptionist_choice!='trade'
    directory=Path(tempfile.mkdtemp(prefix="native-runtime-",dir=ROOT/".cache"))
    run_id=secrets.token_hex(16);players=dict(zip(("a","b"),variants,strict=True))
    if cartridges is None:
        built={v:build(v) for v in set(variants)};artifacts={p:built[v] for p,v in players.items()}
        profiles=companion_profiles()
        contract={"schema":CONTRACT_SCHEMA,"players":{p:cartridge_metadata(profiles[v]) for p,v in players.items()}}
    else:
        contract=cartridges.contract();artifacts={p:cartridges.manifest(p) for p in players}
        for artifact in artifacts.values():
            artifact["output"]=(cartridges.directory/artifact["output"]).relative_to(ROOT).as_posix()
    config=json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"));config["Rewind"]["Enabled"]=False
    config_path=directory/"host.ini";config_path.write_text(json.dumps(config))
    holder={};jobs=[];runtime=None;injected_delay={"a":0.0,"b":0.0};expiry_offset=0
    class DelayedWriter:
        def __init__(self,writer):self.writer=writer;self.timers=[]
        def __getattr__(self,name):return getattr(self.writer,name)
        def write(self,data):
            packet=json.loads(data)
            grant=packet.get("operation_execution")
            if grant and grant["scope"]["phase"]=="native_trade_commit":
                row=holder["execution"].observed.get((packet["player"],grant["scope"]["operation_id"],grant["scope"]["binding_digest"]))
                if row and row["frame"]-row["start"]>=2500:
                    def deliver():
                        if not self.writer.is_closing():self.writer.write(data)
                    injected_delay[packet["player"]]+=.55
                    self.timers.append(asyncio.get_running_loop().call_later(.55,deliver));return
            self.writer.write(data)
        def close(self):
            for timer in self.timers:timer.cancel()
            self.writer.close()
    async def handle(reader,writer):
        if "server" not in holder:writer.close();await writer.wait_closed();return
        await holder["server"].handle_client(reader,DelayedWriter(writer) if delayed else writer)
    listener=await asyncio.start_server(handle,"127.0.0.1",0,limit=4*1024*1024)
    port=listener.sockets[0].getsockname()[1]
    def error_summary(path):
        value=json.loads(path.read_text())
        return json.dumps({"path":str(path),"reason":value["reason"],"metrics":value.get("status",{}).get("metrics")})
    async def progress(name,player):
        path=directory/f"{name}-{player}.json"
        deadline=asyncio.get_running_loop().time()+190
        while asyncio.get_running_loop().time()<deadline:
            for p in players:
                error=directory/f"error-{p}.json"
                if error.exists():raise AssertionError(error_summary(error))
            if path.exists():return json.loads(path.read_text())
            for job in jobs:
                if job.done():
                    passed,result,log=await job
                    raise AssertionError(f"emulator exited before {path}: {passed} {result}\n{log[-7000:]}")
            await asyncio.sleep(.02)
        raise AssertionError(f"native runtime timed out waiting for {path}")
    try:
        source=(ROOT/"lua/tests/test_gen1_native_runtime_gate.lua").read_text()
        for p,v in players.items():
            fixture=None
            if receptionist and p=='a':
                from tools.gen1_receptionist_fixture import make_fixture
                fixture=make_fixture(v,'ViridianPokecenter',directory)
            spec=directory/f"input-{p}.json"
            publish(spec,{"directory":directory.as_posix(),"run_id":run_id,"player":p,"port":port,
                "blob":make_blob(PartyCodec(v),species=38 if cartridges else 153,
                    level=50 if cartridges else 5,dv=0x1000,otid=0).hex().upper(),"manifest":artifacts[p],
                "cartridge":contract["players"][p] if cartridges else None,
                "decision":decision,
                "receptionist":receptionist and p=='a',"fixture":fixture,"ui_only":ui_only,"receptionist_choice":receptionist_choice,
                "expected_disconnect":disconnect})
            script=directory/f"client-{p}.lua"
            gate_name=f"native_runtime_{directory.name}_{p}".replace("-","_")
            script.write_text(source.replace('G.start("test_gen1_native_runtime_gate")',
                f'G.start("{gate_name}")'))
            jobs.append(asyncio.create_task(asyncio.to_thread(run_gate,script.relative_to(ROOT).as_posix(),
                rom_key=v+"_companion",timeout=230,quiet=True,config_base=str(config_path),
                fixture_override=fixture['fixture'] if fixture else None,
                cartridge_override={"path":str(ROOT/artifacts[p]["output"]),
                    "sha256":artifacts[p]["companion"]["final_sha256"],"saveram_name":"candidate.SaveRAM"} if cartridges else None,
                extra_env={"SLINK_NATIVE_RUNTIME_INPUT":str(spec)})))
        observed={p:await progress("observed",p) for p in players}
        contexts={p:IdentityContext(p,"gen1_rby",SaveIdentity(**o["context"]["save_identity"]),
            digest(contract["players"][p]),o["context"]["context_generation"],o["context"]["physical_instance"])
            for p,o in observed.items()}
        assert observed["a"]["host"]["host"]["process_id"]!=observed["b"]["host"]["host"]["process_id"]
        policy=NativeTradePolicy()
        registry=IdentityRegistry(run_id);members=[];halves={}
        state=SoulLinkState(data_dir=str(directory),adapter=get_adapter("gen1_rby",rom_type=variants[0]))
        state.rom_type=variants[0];state.pc_trade_npc=True
        for p,o in observed.items():
            registry.bind_context(contexts[p]);mon=PartyCodec(players[p]).validate_blob(bytes.fromhex(o["snapshot"]["party"][0]))
            members.append(registry.acquire(secrets.token_hex(16),secrets.token_hex(16),
                IdentityWitness(contexts[p],mon.key,mon.sha256,1))["member_id"])
            state.player_identity[p]=o["context"]["save_identity"]
            halves[p]=MonInfo(mon.key,mon.level,mon.species_id,"FISH")
            state.party_keys[p]={mon.key};state.party_size[p]=1;state.pokeballs_obtained[p]=True;state._has_helld.add(p)
            state._ingest_party_blobs(p,[{"slot":0,"key":mon.key,"species_id":mon.species_id,"level":mon.level,"blob_hex":mon.raw.hex()}])
        link=registry.create_link("a",secrets.token_hex(16),members)["link_id"]
        pair=LinkEntry("oaks_lab",halves["a"],halves["b"],LinkStatus.ALIVE)
        state.links.append(pair);state._index_entry(pair);state.area_states["oaks_lab"]=AreaStatus.LINKED
        from server.gen1_runtime_state import state_type_for
        initial=state_type_for(cartridges).initial(StagedGen1State.from_live(state,{"retired_pairs":[]}).document(),
            registry.document(),contract,data_dir=directory)
        def no_gameplay(*args):raise JournalError("ordinary observation bootstrap is outside this native test")
        runtime=Gen1Runtime(directory/"runtime.sqlite3",contract=contract,data_dir=directory,run_id=run_id,
            initial_state=initial,validate_event=no_gameplay,validate_receipt=no_gameplay,
            verify_reconciliation=lambda *args:None,trade_policy=policy,prepared_cartridges=cartridges)
        if decision=="late":runtime.trade.clock=lambda:int(time.monotonic()*1000)+expiry_offset
        execution=install_native_execution(runtime,roms=None if cartridges else {p:(ROOT/artifacts[p]["output"]).read_bytes() for p in players})
        policy.configure(execution,read_checkpoints=lambda:{p:o["checkpoint"] for p,o in observed.items()})
        if receptionist:policy.install_receptionist()
        driver=install_native_driver(runtime,authority=policy.control)
        holder.update(server=SLinkServer(data_dir=str(directory),gen1_runtime=runtime),execution=execution)
        publish(directory/"go.json",{"start":True})
        deadline=asyncio.get_running_loop().time()+185;transaction=None;dropped=False
        while asyncio.get_running_loop().time()<deadline:
            for p in players:
                error=directory/f"error-{p}.json"
                if error.exists():raise AssertionError(error_summary(error))
            async with runtime._lock:
                if transaction is None and set(runtime.gate.sessions)=={"a","b"}:
                    if receptionist:
                        transaction=runtime.state().document()['active_trade']
                    else:
                        owners={p:s.owner for p,s in runtime.gate.sessions.items()}
                    # Declared receptionist-origin fixture; the production offer
                    # validator still checks exact cartridge/context/party/slot.
                        offered={"schema":"rby-receptionist-offer-v1","final_sha1":artifacts["a"]["final_sha1"],
                            "context_generation":contexts["a"].context_generation,"query_generation":1,"offer_generation":2,
                            "token_hex":"A1B2C3D4","slot":0,"key":halves["a"].key,"snapshot":observed["a"]["snapshot"]}
                        reply=runtime.trade.handle("a",secrets.token_hex(16),{"event":"trade_offer","payload":offered},owner=owners["a"])
                        transaction=reply["transaction_id"]
                if transaction:
                    phase=runtime.trade.status(transaction)["phase"]
                    if decision=="late" and any(row.get("prompt_before") and row["armed"] for row in execution.observed.values()):
                        expiry_offset=300001
                    if disconnect and not dropped and any(row["frame"]-row["start"]>=200 for row in execution.observed.values()):
                        runtime._writers["a"][1].close();dropped=True
                    if dropped and runtime.trade.status(transaction)["recovery_required"]:break
                    if phase=="link_committed" and all(not runtime.journal.pending_ids(p) for p in players):break
                    if phase in {"declined","expired"} and all(not runtime.journal.pending_ids(p) for p in players):break
                if ui_only and runtime.state().document()['components'].get('gen1-receptionist',{}).get('a',{}).get('phase')=='closed':
                    assert not transaction and all(not runtime.journal.pending_ids(p) for p in players)
                    break
            await asyncio.sleep(.02)
        if ui_only:
            results={p:await progress('complete',p) for p in players}
            assert runtime.state().document()['active_trade'] is None
            for result in results.values():
                assert result['status']['native_phase']=='idle' and not result['native_calls']
                assert result['status']['host']['host']['physical_stop_verified']
            sequence=results['a']['receptionist']['receipt']['sequence']
            assert sequence==(['after_query','menus_restored','cable'] if receptionist_choice=='cable' else ['after_query','menus_restored'])
            publish(directory/'verified-ui-return.json',{'results':results,'choice':receptionist_choice})
            publish(directory/'finish.json',{'finish':True})
            for job in jobs:
                passed,path,log=await job;assert passed,f'{path}\n{log[-4000:]}'
            return
        if disconnect:
            assert dropped and runtime.trade.status(transaction)["recovery_required"]
            stopped={p:await progress("stopped",p) for p in players}
            for result in stopped.values():
                assert result["frame_before"]==result["frame_after"] and result["status"]["host"]["host"]["physical_stop_verified"]
                assert result["status"]["native_phase"]=="armed" and not result["status"]["window"]["available"]
            trade=runtime.journal.record(NAMESPACE,transaction).value
            assert not trade["applied"] and not trade["verified"]
            assert all(runtime.journal.pending_ids(p) for p in players)
            publish(directory/"verified-disconnect.json",{"stopped":stopped,"trade":trade})
            publish(directory/"finish.json",{"finish":True})
            for job in jobs:
                passed,path,log=await job;assert passed,f"{path}\n{log[-7000:]}"
            return
        if decision!="accept":
            assert runtime.trade.status(transaction)["phase"]==("expired" if decision=="late" else "declined")
            results={p:await progress("complete",p) for p in players}
            trade=runtime.journal.record(NAMESPACE,transaction).value
            assert not trade["applied"] and not trade["verified"] and not trade["ready"]
            for p,result in results.items():
                assert result["status"]["native_phase"]=="idle" and not result["native_calls"]
                assert not result["journal"]["inbox"] and not result["journal"]["outbox"]
                assert result["status"]["host"]["host"]["physical_stop_verified"]
            assert results["b"]["status"]["prompt_phase"]=="closed"
            publish(directory/"verified-refusal.json",{"results":results,"trade":trade})
            publish(directory/"finish.json",{"finish":True})
            for job in jobs:
                passed,path,log=await job;assert passed,f"{path}\n{log[-7000:]}"
            return
        assert transaction and runtime.trade.status(transaction)["phase"]=="link_committed"
        results={p:await progress("complete",p) for p in players}
        trade=runtime.journal.record(NAMESPACE,transaction).value
        for p,result in results.items():
            assert result["status"]["host"]["host"]["physical_stop_verified"]
            assert result["status"]["host"]["steps"]>2000 and result["status"]["window"]["consumed"]>2000
            assert not result["journal"]["inbox"] and not result["journal"]["outbox"]
            assert trade["applied"][p]["counts"]["InternalClockTradeAnim"]==1
            timing=next(value for value in result["status"]["timings"].values() if value["command"]=="native_trade_commit")
            expected=timing["frames"]*4389/262144
            # Normal cases keep the cartridge-rate bound. The fault case also
            # accounts for its explicitly injected transport waiting time.
            assert expected*.95<=timing["elapsed"]<=expected*1.15+1+injected_delay[p],timing
        assert runtime.state().barrier.ticket() is None
        assert len(execution.observed)==7+int(receptionist)
        if receptionist:
            assert results['a']['status']['receptionist_phase']=='complete'
            assert results['a']['journal']['observation']['gen1_receptionist']['phase']=='acknowledged'
        for p in players:
            stages=results[p]['preparation']
            assert stages['phase']=='complete' and set(stages['results'])=={'prompt','save','ready'}
            saved=stages['results']['save']
            assert saved['image_hex']==stages['results']['ready']['checkpoint']['cart_hex']
            assert saved['file']['flushed'] and saved['file']['readback']
        assert results["b"]["status"]["prompt_phase"]=="closed"
        if delayed:
            assert sum(r["status"]["metrics"]["discarded_completed_grants"]+
                r["status"]["metrics"]["terminal_readback_deferred"] for r in results.values())>=1
        if cartridges:
            for p in players:
                assert trade["ready"][p]["details"]["evolved_species"]==38
                assert bytes.fromhex(trade["applied"][p]["after"]["party"]["party"][-1])[0]==38
        publish(directory/"verified.json",{"variants":players,"results":results,"trade":trade,
            "native_execution_policy":"production NativeExecutionPolicy","bootstrap":"explicit linked-run fixture",
            "receptionist_origin":"actual native query and TCP menu/offer/return" if receptionist else "explicit fixture",
            "partner_consent":"actual original cartridge prompt",
            "ordinary_execution":False,"injected_delay_seconds":injected_delay})
        publish(directory/"finish.json",{"finish":True})
        for job in jobs:
            passed,path,log=await job;assert passed,f"{path}\n{log[-7000:]}"
    finally:
        publish(directory/"finish.json",{"finish":True})
        listener.close();await listener.wait_closed()
        await asyncio.gather(*jobs,return_exceptions=True)
        if runtime:runtime.close()
