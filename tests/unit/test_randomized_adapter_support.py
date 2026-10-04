"""RF-5: randomized cartridge support is opt-in for candidate and committed titles."""
import pytest

from server.adapters import adapter_class_for_rom_type, get_adapter
from server.adapters.base import GameRulesAdapter
from server.server import SLinkServer
from tests.unit.test_gen3_rand_admission import client, hello


def test_an_unknown_adapter_does_not_inherit_randomized_support():
    class UnknownRules(GameRulesAdapter):
        pass

    assert UnknownRules.supports_randomized("unknown") is False


@pytest.mark.parametrize("title", ("heartgold", "platinum", "pokemon_black", "pokemon_white_2"))
@pytest.mark.parametrize("kind", ("rand", "rand_overlay"))
@pytest.mark.asyncio
async def test_unbound_randomized_generations_are_refused_at_hello(tmp_path, title, kind):
    server = SLinkServer(data_dir=str(tmp_path))
    async with client(server) as send:
        await send(hello(title, kind))
    assert server.admission["a"]["state"] == "rejected"
    assert title in server.admission["a"]["reason"] and "binding" in server.admission["a"]["reason"]
    assert not server.state.rom_type and not server.state.player_identity


@pytest.mark.parametrize("title", ("heartgold", "pokemon_black", "unknown-persisted-title"))
def test_an_unsupported_randomized_committed_run_is_refused_even_for_a_clean_candidate(tmp_path, title):
    server = SLinkServer(data_dir=str(tmp_path))
    server.state.rom_type, server.state.artifact_kind = title, "rand"
    # The committed title must be checked even when a candidate doesn't declare randomization.
    reason = server._mixed_games_error("a", title if title != "unknown-persisted-title" else "firered", "clean")
    assert "committed" in reason and title in reason and "binding" in reason
    # the candidate is a PATCHED FireRed ("companion"): a clean one is refused for the companion first
    verdict = server._decide_admission("a", hello("firered", "companion"))
    assert verdict["state"] == "rejected" and "committed" in verdict["reason"]


@pytest.mark.parametrize("game_id,title", (("gen4_hgsspt", "heartgold"), ("gen5_bw", "pokemon_black"),
                                           (None, "unknown")))
@pytest.mark.parametrize("kind", ("rand", "rand_overlay"))
def test_direct_admission_cannot_bypass_the_adapter_capability(tmp_path, game_id, title, kind):
    server = SLinkServer(data_dir=str(tmp_path))
    server.adapter = (get_adapter(game_id, rom_type=title) if game_id
                      else type("UnknownAdapter", (), {})())
    verdict = server._decide_admission("a", hello(title, kind))
    assert verdict["state"] == "rejected" and "binding" in verdict["reason"]


@pytest.mark.parametrize("title", ("red", "Blue", "yellow", "red_ap", "PureRed", "pureblue", "puregreen",
                                   "firered", "leafgreen", "emerald"))
def test_existing_randomized_foundations_explicitly_opt_in(title):
    assert adapter_class_for_rom_type(title).supports_randomized(title) is True


@pytest.mark.parametrize("title", ("Crystal", "gold", "silver"))
def test_gen2_remains_clean_or_overlay_only(title):
    adapter = get_adapter("gen2_gsc", rom_type=title)
    assert adapter.supports_randomized(title) is False
    for kind in ("clean", "overlay"):
        adapter.set_artifact_kind(kind)
    for kind in ("rand", "rand_overlay"):
        with pytest.raises(ValueError, match="clean/overlay"):
            adapter.set_artifact_kind(kind)
