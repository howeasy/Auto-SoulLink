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


@pytest.mark.parametrize("title", ("heartgold", "pokemon_black", "pokemon_white_2"))
@pytest.mark.parametrize("kind", ("rand", "rand_overlay"))
@pytest.mark.asyncio
async def test_unbound_randomized_generations_are_refused_at_hello(tmp_path, title, kind):
    server = SLinkServer(data_dir=str(tmp_path))
    async with client(server) as send:
        await send(hello(title, kind))
    assert server.admission["a"]["state"] == "rejected"
    assert title in server.admission["a"]["reason"] and "binding" in server.admission["a"]["reason"]
    assert not server.state.rom_type and not server.state.player_identity


@pytest.mark.parametrize("kind", ("rand", "rand_overlay", "clean", "companion"))
@pytest.mark.asyncio
async def test_platinum_is_refused_as_an_unrouted_game_in_every_artifact_kind(tmp_path, kind):
    """Platinum is bind-only data, not a runtime pack (docs/gen4/PLAN.md 4.5/4.6): its rom_type no longer
    routes, so it is refused by name BEFORE any capability/binding question is asked."""
    server = SLinkServer(data_dir=str(tmp_path))
    async with client(server) as send:
        await send(hello("platinum", kind))
    assert server.admission["a"]["state"] == "rejected"
    assert "platinum" in server.admission["a"]["reason"] and "not a game this server routes" in server.admission["a"]["reason"]
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
def test_gen2_binds_only_the_randomized_companion_overlay(title):
    """R3 (owner "open C-5"): Gen 2 opts in, but only as rand_overlay -- a randomized clean build ("rand")
    lacks the companion every Gen 2 title requires, so the adapter never commits it."""
    adapter = get_adapter("gen2_gsc", rom_type=title)
    assert adapter.supports_randomized(title) is True
    assert adapter.randomized is False
    for kind in ("clean", "overlay", "rand_overlay"):
        adapter.set_artifact_kind(kind)
        assert adapter.randomized is (kind == "rand_overlay")
    for kind in ("rand", "named", "rand_companion"):
        with pytest.raises(ValueError, match="clean/overlay/rand_overlay"):
            adapter.set_artifact_kind(kind)
    assert adapter.randomized is True, "a refused kind must not clobber the committed one"
    assert type(adapter).supports_randomized(["Crystal"]) is False
