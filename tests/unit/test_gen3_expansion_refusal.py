"""Owner ruling 39: the Emerald expansion is REGISTERED and UNROUTED on the server.

`gen3_exp` has had an adapter class, a data pack and a `game_id` row since X1, and until this
card nothing on the server said so out loud: `_ROM_TYPE_TO_GAME_ID` mapped
`emerald_expansion_28877d73` to `gen3_exp`, so a hello naming that cartridge resolved a
foundation, bound the adapter and started a live run on a build whose XG track is still open
(the same build the CLIENT half refuses: `profile.json`'s `admitted: false`, and
`Entry.ROUTED` without `gen3_exp` -- pinned by
tests/unit/test_e2e_duo_gen3_exp.py::test_production_still_refuses_the_expansion_build).

Ruling 39 closes the server half: the rom_type is refused BY NAME, the way Archipelago
Crystal is (O-25), and a run persisted under `gen3_exp` is refused on load the way a run
persisted under the removed `gen2_crystal` is. Registered-but-unrouted is the whole shape:
`get_adapter("gen3_exp")` still builds, the label and the capabilities fixture can still NAME
the cartridge, and `_REFUSED_ROM_TYPES` names the reason a refused hello gets.

THE SEAM, AND WHY IT IS A FLAG. The expansion's live track still has to run its duos
(`tools/e2e_duo.py --game gen3_exp`) against a server that refuses that cartridge, exactly as
the client half of that lane admits and routes it through its own logged TEST-ONLY seam. The
server's half is `--test-only-route ROM_TYPE` (server/server.py), a PROCESS flag:

  * an environment variable would be the wrong shape -- every lane on this machine sources one
    shared env file, so an exported variable would hand the seam to the FR/LG, RR and Emerald
    rows running in the same shell. Nothing but the launch can set a flag;
  * it can only enable a rom_type named in `_TEST_ONLY_ROUTES`; asking for anything else
    (`crystal_ap`, `firered`, a typo) is refused and logged, so the flag cannot invent a route
    or un-refuse a ruling;
  * every route it does enable is logged with `production:false`, and the duo harness copies
    that line out of the run's own server log into the attempt's pydec receipt -- so a receipt
    can always be read for whether the cartridge was ROUTED or merely admitted.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from server import adapters
from server.adapters import (
    adapter_class_for_rom_type,
    foundation_for_rom_type,
    game_id_for_rom_type,
    get_adapter,
    test_only_routes as enabled_test_routes,
    unrouted_rom_type_reason,
    variant_label,
)
from server.adapters.gen3_expansion import Gen3ExpansionAdapter
from server.server import SLinkServer
from server.state import UnsafeGameMigration

REPO = Path(__file__).resolve().parents[2]
EXP = "emerald_expansion_28877d73"


@pytest.fixture(autouse=True)
def no_seam():
    """No TEST-ONLY route is enabled, whatever ran before.

    The override is process state on purpose (a launch flag, not a per-run argument), so every
    case here states which world it is in rather than inheriting one.
    """
    adapters.set_test_only_routes([])
    yield
    adapters.set_test_only_routes([])


@pytest.fixture
def expansion_routed():
    """The one process that routes the expansion: the gen3_exp duo lane (ruling 39)."""
    adapters.set_test_only_routes([EXP])
    try:
        yield
    finally:
        adapters.set_test_only_routes([])


def _write_run(tmp_path, *, game_id: str, rom_type: str) -> None:
    (tmp_path / "links.json").write_text(json.dumps({
        "links": [], "area_states": {}, "pending_captures": {}, "mon_stats": {},
        "game_id": game_id, "rom_type": rom_type, "artifact_kind": "clean",
    }))


async def _session(srv):
    """A real TCP client on the server's own handler, the way a BizHawk instance connects."""
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    port = tcp.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)

    async def send(msg):
        w.write((json.dumps(msg) + "\n").encode())
        await w.drain()
        return json.loads(await asyncio.wait_for(r.readline(), 5))

    async def close():
        w.close()
        tcp.close()
        await tcp.wait_closed()
    return send, close


# ── the refusal ─────────────────────────────────────────────────────────────────────────────

def test_the_refusal_is_named_and_every_route_lookup_answers_none():
    reason = unrouted_rom_type_reason(EXP)
    assert reason == adapters._EMERALD_EXPANSION_UNROUTED
    assert "ruling 39" in reason
    assert game_id_for_rom_type(EXP) is None
    assert foundation_for_rom_type(EXP) is None
    assert adapter_class_for_rom_type(EXP) is None
    # ... while the rom_type is still KNOWN, so the dashboard, the capabilities fixture and the
    # calc bridge can name the cartridge. A refusal here is a ruling, not a missing row.
    assert adapters._ROM_TYPE_TO_GAME_ID[EXP] == "gen3_exp"
    assert adapters._VARIANT_LABEL[EXP] == variant_label(EXP) != EXP
    assert unrouted_rom_type_reason("firered") == "not a game this server routes"


def test_the_adapter_is_registered_but_the_cartridge_is_not_routed():
    """Registered-but-unrouted, which is the ruling's own wording: the refusal is not a
    missing module, so it must hold with the adapter deleted from the registry."""
    assert get_adapter("gen3_exp").game_id == "gen3_exp"
    adapters._REGISTRY.pop("gen3_exp", None)
    try:
        assert game_id_for_rom_type(EXP) is None
        assert unrouted_rom_type_reason(EXP) == adapters._EMERALD_EXPANSION_UNROUTED
    finally:
        adapters.register_adapter("gen3_exp", Gen3ExpansionAdapter)


@pytest.mark.asyncio
async def test_a_production_hello_naming_the_expansion_is_refused(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send({"event": "hello", "player": "a", "rom_type": EXP,
                            "artifact_kind": "clean", "trainer_name": "BRENDAN",
                            "ot_id": "12345678", "party": [], "has_pokeballs": True})
        assert any(c.get("cmd") == "hud_show" and "UNKNOWN ROM" in c.get("text", "")
                   for c in reply["commands"]), reply
        assert adapters._EMERALD_EXPANSION_UNROUTED in srv.state.identity_error["a"]
        # The refused cartridge must leave the run exactly as it found it: no adapter swap.
        assert srv.adapter.game_id == "gen3_frlge"
        assert srv.state.rom_type == ""
        # ... and nothing else gets through while the refusal stands.
        await send({"event": "area_enter", "player": "a", "area_id": "route_102"})
        assert "route_102" not in srv.state.area_states
    finally:
        await close()


@pytest.mark.parametrize("rom_type", [EXP, "", "emerald"])
def test_a_run_persisted_under_gen3_exp_is_refused_on_load(tmp_path, rom_type):
    """Whatever the saved rom_type resolves to -- the expansion, nothing yet, or a title that
    routes somewhere else -- the persisted game_id is what is refused, so no half-migrated
    expansion run can reopen under another cartridge's adapter."""
    _write_run(tmp_path, game_id="gen3_exp", rom_type=rom_type)
    with pytest.raises(UnsafeGameMigration, match="gen3_exp"):
        SLinkServer(data_dir=str(tmp_path))


def test_the_persisted_refusal_needs_no_registered_adapter(tmp_path):
    adapters._REGISTRY.pop("gen3_exp", None)
    try:
        _write_run(tmp_path, game_id="gen3_exp", rom_type=EXP)
        with pytest.raises(UnsafeGameMigration, match="gen3_exp"):
            SLinkServer(data_dir=str(tmp_path))
    finally:
        adapters.register_adapter("gen3_exp", Gen3ExpansionAdapter)


# ── the seam ────────────────────────────────────────────────────────────────────────────────

def test_the_seam_routes_the_expansion_and_nothing_else(expansion_routed):
    assert enabled_test_routes() == {EXP: "gen3_exp"}
    assert game_id_for_rom_type(EXP) == "gen3_exp"
    assert foundation_for_rom_type(EXP) == "gen3_exp"
    assert adapter_class_for_rom_type(EXP) is Gen3ExpansionAdapter
    # Every other cartridge answers exactly as it did with the seam closed.
    assert game_id_for_rom_type("emerald") == "gen3_frlge"
    assert foundation_for_rom_type("emerald") == "gen3_emerald"
    assert game_id_for_rom_type("crystal_ap") is None
    assert game_id_for_rom_type("firered") == "gen3_frlge"


@pytest.mark.asyncio
async def test_the_duo_lane_hello_is_admitted_through_the_seam(tmp_path, expansion_routed):
    """The client half of this lane admits the build; the server half is what routes it."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send({"event": "hello", "player": "a", "rom_type": EXP,
                            "artifact_kind": "clean", "trainer_name": "BRENDAN",
                            "ot_id": "12345678", "party": [], "has_pokeballs": True})
        assert not any(c.get("cmd") == "hud_show" and "UNKNOWN ROM" in c.get("text", "")
                       for c in reply["commands"]), reply
        assert not srv.state.identity_error.get("a")
        assert srv.state.rom_type == EXP
        assert srv.adapter.game_id == "gen3_exp"
    finally:
        await close()


def test_a_persisted_expansion_run_loads_inside_the_seam(tmp_path, expansion_routed):
    """The lane's own data dir stays loadable: a refusal that also broke the lane it exists
    for would be a half-seam."""
    _write_run(tmp_path, game_id="gen3_exp", rom_type=EXP)
    srv = SLinkServer(data_dir=str(tmp_path))
    assert srv.state.adapter.game_id == "gen3_exp"
    assert srv.state.rom_type == EXP


def test_the_seam_is_logged_with_production_false(caplog):
    """The receipt requirement, unit-proven: whichever process opens the seam says so in its
    own log, and the duo harness copies that line into the attempt's receipt."""
    with caplog.at_level(logging.WARNING, logger="server.adapters"):
        adapters.set_test_only_routes([EXP])
    lines = [r.getMessage() for r in caplog.records if "TEST-ONLY route of" in r.getMessage()]
    assert len(lines) == 1, lines
    assert EXP in lines[0] and "gen3_exp" in lines[0] and "production:false" in lines[0]


def test_the_seam_cannot_open_a_route_that_is_not_its_own(caplog):
    with caplog.at_level(logging.WARNING, logger="server.adapters"):
        enabled = adapters.set_test_only_routes(["crystal_ap", "firered", "no_such_rom"])
    assert enabled == {}
    assert enabled_test_routes() == {}
    assert game_id_for_rom_type("crystal_ap") is None, "the flag must not un-refuse O-25"
    assert game_id_for_rom_type("firered") == "gen3_frlge"
    refused = [r.getMessage() for r in caplog.records if "is not a TEST-ONLY route" in r.getMessage()]
    assert len(refused) == 3, refused


# ── the production default, in a fresh interpreter ──────────────────────────────────────────

def test_a_server_process_routes_nothing_it_was_not_told_to():
    """Module state, so a fresh process is the only honest witness: nothing is routed until
    a launch asks for it, and the ruling still applies to the expansion."""
    probe = ("from server.adapters import game_id_for_rom_type, test_only_routes;"
             "import json;"
             "print('ROUTE_PROBE ' + json.dumps([sorted(test_only_routes()),"
             " game_id_for_rom_type('emerald_expansion_28877d73'),"
             " game_id_for_rom_type('emerald')]))")
    res = subprocess.run([sys.executable, "-c", probe], cwd=REPO, capture_output=True,
                         text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    line = next(row for row in res.stdout.splitlines() if row.startswith("ROUTE_PROBE "))
    overrides, expansion, emerald = json.loads(line[len("ROUTE_PROBE "):])
    assert overrides == []
    assert expansion is None
    assert emerald == "gen3_frlge"


def test_the_cli_offers_the_seam_flag():
    res = subprocess.run([sys.executable, "-m", "server.server", "--help"], cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    # argparse wraps help text at the terminal width, so compare on collapsed whitespace.
    out = " ".join((res.stdout + res.stderr).split())
    assert "--test-only-route" in out
    assert "ruling 39" in out, "the flag's help must name the ruling it exists for"
