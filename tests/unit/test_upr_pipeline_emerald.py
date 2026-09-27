"""E-MGR: Manager identification, provisioning, audit and real server admission."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import aiohttp
import pytest

from server import cartridges, upr_pipeline as P, upr_settings as U
from tests.unit.test_upr_pipeline_gen3 import _clean_path, _jar, _widest

pytest_plugins = ["tests.unit.manager_harness"]
FAMILY = "gen3_emerald"


def test_manager_identifies_pinned_emerald_and_rejects_a_cross_foundation_pair():
    source = str(_clean_path("emerald"))
    info = P.describe_rom(source, jar_fork=True)
    assert info["clean"] and info["family"] == FAMILY and info["variant"] == "Emerald"
    assert P.family_of({"a": source, "b": source}) == FAMILY
    with pytest.raises(P.UprPipelineError, match="different families"):
        P.family_of({"a": source, "b": str(_clean_path("firered"))})


def test_emerald_manager_refuses_the_widest_settings_before_producing_any_rom(tmp_path):
    source = str(_clean_path("emerald"))
    settings = tmp_path / "widest.rnqs"
    settings.write_bytes(_widest())
    with pytest.raises(P.UprPipelineError) as exc:
        P.prepare_pair("unused.jar", str(settings), {"a": source, "b": source}, str(tmp_path / "out"))
    for word in ("abilities", "types", "evolutions", "movesets", "base_stats", "type chart"):
        assert word in str(exc.value)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("entry", ("prepare_pair", "provision"))
def test_emerald_requires_the_fork_even_if_a_stock_jar_were_trusted(tmp_path, monkeypatch, entry):
    source = str(_clean_path("emerald"))
    jar, settings = tmp_path / "stock.jar", tmp_path / "settings.rnqs"
    jar.write_bytes(b"model stock jar")
    settings.write_bytes(U.build_spec(U.default_spec(FAMILY), family=FAMILY))
    monkeypatch.setattr(P, "jar_is_trusted", lambda _: True)
    monkeypatch.setattr(P, "jar_is_fork", lambda _: False)
    monkeypatch.setattr(P.shutil, "which", lambda _: "java")
    with pytest.raises((P.UprPipelineError, cartridges.CartridgeError), match="Emerald.*fork jar"):
        if entry == "prepare_pair":
            P.prepare_pair(str(jar), str(settings), {"a": source, "b": source}, str(tmp_path / "out"))
        else:
            cartridges.provision(str(tmp_path / "out"), {"a": source, "b": source}, companion=False,
                                 randomize={"settings_path": str(settings)}, jar=str(jar))


def test_emerald_companion_stays_refused_and_a_clean_copy_needs_no_randomizer(tmp_path):
    source = str(_clean_path("emerald"))
    sources = {"a": source, "b": source}
    with pytest.raises(cartridges.CartridgeError, match="no Emerald companion"):
        cartridges.provision(str(tmp_path / "held"), sources, companion=True, randomize=None)
    result = cartridges.provision(str(tmp_path / "copy"), sources, companion=False, randomize=None)
    assert result["family"] == FAMILY and result["randomizer"] is None
    assert (tmp_path / "copy/roms/a.gba").read_bytes() == Path(source).read_bytes()


@pytest.fixture(scope="module")
def manager_pair(tmp_path_factory):
    folder = tmp_path_factory.mktemp("manager_emerald_pair")
    source = str(_clean_path("emerald"))
    settings = folder / "settings.rnqs"
    spec = {**U.default_spec(FAMILY), "statics": "random", "wild_held_items": True,
            "trainer_items_regular": True}
    settings.write_bytes(U.build_spec(spec, family=FAMILY))
    result = cartridges.provision(str(folder), {"a": source, "b": source}, companion=False,
                                 randomize={"settings_path": str(settings)}, jar=_jar())
    return folder, result


def test_manager_emerald_pair_contract_names_the_final_gba_files_and_audits(manager_pair):
    folder, result = manager_pair
    contract = json.loads((folder / "rom_contract.json").read_text())
    assert result["family"] == FAMILY
    assert contract["players"]["a"]["seed"] != contract["players"]["b"]["seed"]
    assert contract["players"]["a"]["fingerprint"] != contract["players"]["b"]["fingerprint"]
    for side in ("a", "b"):
        raw = (folder / f"roms/{side}.gba").read_bytes()
        row = contract["players"][side]
        assert row["rom_sha1"] == hashlib.sha1(raw).hexdigest() == result["players"][side]["rom_sha1"]
        assert row["fingerprint"] == P.gen3_fingerprint_rom(raw)
        assert P.gen3_site_mismatches(raw, "emerald") == []
        audit = result["randomizer"]["players"][side]["write_domain"]
        assert audit["changed"] > 0 and {"baseline", "wild", "trainer_parties"} <= set(audit["domains"])


@pytest.mark.asyncio
async def test_manager_produced_emerald_pair_is_admitted_by_the_server(manager_pair):
    from server.server import SLinkServer
    from tests.unit.test_gen3_rand_admission import client, hello
    from tests.unit.test_gen3_rom_content_lua import collector, payload_from, symbols

    folder, result = manager_pair
    server = SLinkServer(data_dir=str(folder))
    async with client(server) as send_a, client(server) as send_b:
        for side, send in (("a", send_a), ("b", send_b)):
            raw = (folder / f"roms/{side}.gba").read_bytes()
            _, obj, _ = collector(raw, symbols("emerald", len(raw)))
            await send(hello("emerald", "rand", player=side, trainer_name=side.upper(),
                             ot_id="7A0A" if side == "a" else "7B0B", rom_content=payload_from(obj),
                             rom_sha1=result["players"][side]["rom_sha1"]))
            assert server.admission[side] == {"state": "admitted", "reason": "cartridge matches the contract"}
            assert server.adapter_for(side).encounter_table("route_102")
    assert server.state.artifact_kind == "rand" and not server.state.identity_error


def test_manager_offers_emerald_options_with_the_fossil_option_unavailable():
    from server import manager

    assert manager.GAME_FAMILY["gen3_e"] == FAMILY
    assert "gen3_e" in manager.new_run_form()["randomizer_games"]
    rows = {row["key"]: row for row in U.option_form(every_family=True)}
    assert FAMILY in rows["tutors"]["families"]
    assert FAMILY not in rows["balance_static_levels"]["families"]


@pytest.mark.asyncio
async def test_manager_emerald_settings_round_trip_and_named_refusal(manager_client):
    spec = {**U.default_spec(FAMILY), "tutors": "random", "pickup": "random"}
    response = await manager_client.post("/api/randomizer/settings/export", json={"spec": spec, "family": FAMILY})
    assert response.status == 200
    payload = aiohttp.FormData()
    payload.add_field("file", await response.read(), filename="emerald.rnqs", content_type="application/octet-stream")
    payload.add_field("family", FAMILY)
    back = await (await manager_client.post("/api/randomizer/settings/import", data=payload)).json()
    assert back["ok"] and back["spec"] == spec
    bad = await manager_client.post("/api/randomizer/settings/export",
                                    json={"spec": {"balance_static_levels": True}, "family": FAMILY})
    assert bad.status == 400 and "balance_static_levels" in await bad.text()
