"""RF-2: randomization and complete box censuses require a title's admitted client binding."""
import copy

import pytest

from server.adapters.gen3_expansion import Gen3ExpansionAdapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer
from tests.unit.test_gen3_rand_admission import client, hello
from tests.unit.test_gen3_rom_ingest import _clean, _payload


def test_expansion_does_not_claim_the_vanilla_clients_box_census(tmp_path):
    adapter = Gen3ExpansionAdapter()
    assert adapter.reports_box_census() is False
    server = SLinkServer(data_dir=str(tmp_path))
    server.state.adapter = server.adapter = adapter
    server._ingest_box_census("a", {"event": "hello", "party": []})
    assert server._census_capable("a") is False
    assert Gen3Adapter(rom_type="firered").reports_box_census() is True
    assert Gen3Adapter(rom_type="emerald").reports_box_census() is True


@pytest.mark.parametrize("kind", ("rand", "rand_overlay"))
@pytest.mark.parametrize("existing_clean", (False, True))
@pytest.mark.parametrize("report", ("missing", "firered-clean", "leafgreen-clean"))
@pytest.mark.asyncio
async def test_emerald_randomized_declarations_require_matching_cartridge_proof(
        tmp_path, kind, existing_clean, report):
    server = SLinkServer(data_dir=str(tmp_path))
    content = {} if report == "missing" else {
        "rom_content": _payload(_clean(report.split("-")[0]), report.split("-")[0])}
    async with client(server) as send:
        if existing_clean:
            await send(hello("emerald", "clean"))
            assert server.admission["a"]["state"] == "admitted"
        before = copy.deepcopy(server.state.player_identity)
        await send(hello("emerald", kind, **content))
    assert server.admission["a"]["state"] == "rejected"
    reason = server.admission["a"]["reason"].lower()
    assert "rom_content" in reason or "mixed artifact kinds" in reason
    assert server.state.player_identity == before
    assert server.adapter_for("a")._rom_trainers is None
    # The pure pairing guard must refuse before a forged clean FR payload can normalize kind.
    server.state.rom_type, server.state.artifact_kind = "emerald", "clean"
    assert "Mixed artifact kinds" in server._mixed_games_error(
        "a", "emerald", kind, rom_content=content.get("rom_content"))


@pytest.mark.parametrize("kind", ("rand", "rand_overlay"))
def test_direct_emerald_admission_also_refuses_even_with_a_valid_frlg_report(tmp_path, kind):
    server = SLinkServer(data_dir=str(tmp_path))
    server.state.adapter = server.adapter = Gen3Adapter(rom_type="emerald")
    verdict = server._decide_admission("a", hello("emerald", kind,
                                                  rom_content=_payload(_clean("firered"), "firered")))
    assert verdict["state"] == "rejected"
    assert "emerald" in verdict["reason"].lower() and "rom_content" in verdict["reason"]
