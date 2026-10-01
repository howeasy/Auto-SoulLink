"""RF-3: the socket and Manager enforce the same cartridge species rules."""
import pytest

from server import upr_pipeline
from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer
from server import upr_gen3_write_domain as write_domain
from tests.unit.test_gen3_rand_admission import client, hello
from tests.unit.test_gen3_rom_content_lua import symbols
from tests.unit.test_gen3_rom_ingest import _clean, _payload, _randomized


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
@pytest.mark.parametrize("boundary", ("admission", "pairing"))
@pytest.mark.asyncio
async def test_changed_growth_rate_is_refused_and_cannot_pair_clean(tmp_path, title, boundary):
    original = _clean(title)
    raw = bytearray(original)
    head = symbols(title, len(raw))["gSpeciesInfo"]["address"] - 0x08000000
    offset = head + 28 + 19                 # Bulbasaur's growthRate (pret SpeciesInfo)
    raw[offset] = (raw[offset] + 1) % 6      # SYNTH: another valid Gen 3 growth curve
    report = _payload(bytes(raw), title)
    source, output = tmp_path / "clean.gba", tmp_path / "changed.gba"
    source.write_bytes(original)
    output.write_bytes(raw)
    # This was already a named Manager refusal; socket admission must agree with it.
    with pytest.raises(upr_pipeline.UprPipelineError, match="growth rates"):
        upr_pipeline._check_content_gen3(str(source), str(output))
    if boundary == "pairing":
        assert Gen3Adapter.pairing_kind_for("rand", report) == "rand"
    else:
        server = SLinkServer(data_dir=str(tmp_path / "run"))
        async with client(server) as send:
            reply = await send(hello(title, "rand", rom_content=report))
        assert server.admission["a"]["state"] == "rejected"
        assert "growth rates" in server.admission["a"]["reason"]
        assert reply["commands"] == [{"cmd": "noop", "refused": "admission"}]


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
@pytest.mark.asyncio
async def test_fork_baseline_writes_are_accepted_by_the_manager_and_socket(tmp_path, title):
    original = _clean(title)
    allowed = _randomized(title, "allowed")
    raw = bytearray(original)
    baseline = write_domain.load_model()["titles"][title]["domains"]["baseline"]
    for start, end in write_domain._ranges(baseline):
        raw[start:end] = allowed[start:end]
    # SYNTH: copy ONLY the fork's always-written byte ranges, including Deoxys + ability fills.
    audit = write_domain.audit(title, original, bytes(raw), {"baseline"})
    assert audit["changed"] > 280 and not audit["stray"]
    report = _payload(bytes(raw), title)
    assert Gen3Adapter.pairing_kind_for("rand", report) == "clean"
    source, output = tmp_path / "clean.gba", tmp_path / "baseline.gba"
    source.write_bytes(original)
    output.write_bytes(raw)
    assert upr_pipeline._check_content_gen3(str(source), str(output))
    server = SLinkServer(data_dir=str(tmp_path / "run"))
    async with client(server) as send:
        reply = await send(hello(title, "rand", rom_content=report))
    assert server.admission["a"]["state"] == "admitted"
    assert not any(c.get("refused") for c in reply["commands"])


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
@pytest.mark.asyncio
async def test_originally_empty_second_ability_only_allows_filling_with_the_first(tmp_path, title):
    original = _clean(title)
    raw = bytearray(original)
    head = symbols(title, len(raw))["gSpeciesInfo"]["address"] - 0x08000000
    offset = head + 28
    assert (raw[offset + 22], raw[offset + 23]) == (65, 0)  # pinned Bulbasaur: OVERGROW/NONE
    raw[offset + 23] = 66                                # a different, nonzero ability
    report = _payload(bytes(raw), title)
    assert Gen3Adapter.pairing_kind_for("rand", report) == "rand"
    server = SLinkServer(data_dir=str(tmp_path / "run"))
    async with client(server) as send:
        await send(hello(title, "rand", rom_content=report))
    assert server.admission["a"]["state"] == "rejected"
    assert "abilities" in server.admission["a"]["reason"]
    source, output = tmp_path / "clean.gba", tmp_path / "changed.gba"
    source.write_bytes(original)
    output.write_bytes(raw)
    with pytest.raises(upr_pipeline.UprPipelineError, match="abilities"):
        upr_pipeline._check_content_gen3(str(source), str(output))
