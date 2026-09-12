"""Real TCP ownership/challenge issuance; physical verification stays an explicit fixture."""
import asyncio
import copy
import pytest

from server.protocol import canonical_json,decode_frame
from tests.unit.test_gen1_execution_authority import request,verifier
from tests.unit.test_gen1_runtime_server import RuntimeCase


@pytest.mark.parametrize("failure",["replayed_challenge","peer_disconnect"])
def test_actual_tcp_operation_window_is_scoped_and_revoked_on_protocol_or_peer_loss(tmp_path,failure):
    async def exercise():
        case=RuntimeCase(tmp_path);case.runtime.verify_operation_execution=verifier
        server=await asyncio.start_server(case.runtime.handle_client,"127.0.0.1",0)
        clients={}
        async def send(player,message):
            reader,writer=clients[player]
            writer.write((canonical_json(message)+"\n").encode());await writer.drain()
            return decode_frame(await asyncio.wait_for(reader.readuntil(b"\n"),1))
        try:
            for player in ("a","b"):
                clients[player]=await asyncio.open_connection("127.0.0.1",server.sockets[0].getsockname()[1])
                response=await send(player,case.hello(player))
                assert response["ack"]=="ACK" and response["commands"]==[]
            response=await send("a",case.envelope("a",{"event":"faint","key":case.keys["a"]}))
            assert response["ack"]=="ACK"
            message=request(case)
            before=case.runtime.journal.snapshot()
            response=await send("b",message)
            assert response["control"]["authority"]=="hold"
            assert response["operation_execution"]["scope"]==message["operation_execution"]["window"]["scope"]
            assert case.runtime.journal.snapshot()==before and case.runtime.state().barrier.ticket() is None
            if failure=="replayed_challenge":
                refused=await send("b",message)
            else:
                clients["a"][1].close();await clients["a"][1].wait_closed()
                notice=decode_frame(await asyncio.wait_for(clients["b"][0].readuntil(b"\n"),1))
                assert notice["event"]=="gen1_hold" and notice["commands"]==[]
                stale=copy.deepcopy(message);stale["seq"]+=1
                refused=await send("b",stale)
            assert refused["ack"]=="NACK" and "operation_execution" not in refused
            assert case.runtime.journal.command("b",message["operation_execution"]["window"]["scope"]["operation_id"])["outcome"] is None
        finally:
            for _,writer in clients.values():writer.close()
            for _,writer in clients.values():await writer.wait_closed()
            server.close();await server.wait_closed()
            for _ in range(50):
                if not case.runtime._writers:break
                await asyncio.sleep(.01)
            assert not case.runtime._writers
            case.close()
    asyncio.run(exercise())
