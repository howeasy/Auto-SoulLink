"""Randomized FR/LG admission kind `rand` on the server (docs/gen3/research/randomized_gen3_design.md
R1, this lane's half): the adapter stores the kind, `rand` never pairs with `clean`, and a `rand`
run never shows retail trainer data or a setdex calc_label."""
from __future__ import annotations

import asyncio
import json

import pytest

from server.adapters import adapter_class_for_rom_type, get_adapter
from server.server import SLinkServer

FR_RAND = {"rom_type": "firered", "artifact_kind": "rand"}
FR_CLEAN = {"rom_type": "firered", "artifact_kind": "clean"}
BROCK = 414


async def _session(srv):
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0, limit=4 * 1024 * 1024)  # as main()
    port = tcp.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)

    async def send(msg):
        w.write((json.dumps(msg) + "\n").encode())
        await w.drain()
        return json.loads(await asyncio.wait_for(r.readline(), 3))

    async def close():
        w.close()
        tcp.close()
        await tcp.wait_closed()
    return send, close


def _hello(player, cart):
    return {"event": "hello", "player": player, "trainer_name": player.upper(),
            "ot_id": "30B8" if player == "a" else "7B0B", "has_pokeballs": True,
            "party": [], **cart}


def test_rand_pairs_only_with_rand():
    gen3 = adapter_class_for_rom_type("firered")
    assert gen3.pairing_kind("rand") == "rand"
    assert gen3.pairing_kind("rand") != gen3.pairing_kind("clean")
    assert gen3.pairing_kind("rand") != gen3.pairing_kind("companion")


@pytest.mark.asyncio
async def test_a_clean_firered_cannot_join_a_rand_run_and_the_kind_reaches_the_adapter(tmp_path):
    from tests.unit.test_gen3_rand_admission import randomized_payload

    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(_hello("a", {**FR_RAND, "rom_content": randomized_payload()}))
        assert srv.state.artifact_kind == "rand"
        assert srv.adapter._artifact_kind == "rand", "set_artifact_kind stored the committed kind"
        await send(_hello("b", FR_CLEAN))
        assert "Mixed artifact kinds" in srv.state.identity_error["b"]
    finally:
        await close()


def test_rand_shows_no_retail_trainers_until_its_cartridge_reports():
    clean = get_adapter("gen3_frlge", rom_type="firered")
    assert clean.trainer_brief(BROCK)["calc_label"] == "Leader Brock"
    for rand in (get_adapter("gen3_frlge", rom_type="firered", artifact_kind="rand"),
                 _after_commit(get_adapter("gen3_frlge", rom_type="firered"))):
        assert rand.trainer_brief(BROCK) is None
        assert rand.trainers_for_area("pewter_city") == []
        assert rand.trainer_info(BROCK) == ("", "")
        assert rand.trainer_party(BROCK) == []


def _after_commit(adapter):
    adapter.set_artifact_kind("rand")
    return adapter


def test_rand_brief_from_an_ingested_table_has_no_calc_label():
    rand = get_adapter("gen3_frlge", rom_type="firered", artifact_kind="rand")
    table =rand._rom_trainer_table({
        "class_names": ["", "Leader"],
        "trainers": {BROCK: {"class": 1, "name": "BROCK",
                             "party": [{"species": 74, "level": 12, "moves": [33, 111, 0, 0]}]}},
    })
    assert table["trainers"][BROCK]["key"] and "calc_label" not in table["trainers"][BROCK]
    rand._rom_trainers = table
    brief = rand.trainer_brief(BROCK)
    assert brief["name"] == "Brock" and brief["class"] == "Leader"
    assert "calc_label" not in brief and brief["level_cap"] == 12
