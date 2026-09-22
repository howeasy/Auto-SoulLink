"""Which client `lua/slink.lua` and `lua/slink_gen1.lua` actually load.

The launchers are the only thing a player ever runs: the Manager's generated launcher
sets SLINK_HOST/PORT/PLAYER and dofiles `lua/slink.lua` (server/manager.py), and the
standalone status page does the same. Everything else about the Gen 1 rewrite can be
correct and the shipped run still boots the old `lua/clients/gen1_rby_client.lua` if
these two files point there -- which they did until this pin existed, and no other test
executes the dispatch (`test_manager_launcher.py` checks the generated file's settings,
`test_gen1_entry.py` checks the detector in isolation).

So this executes the real launcher under lupa with BizHawk's globals stubbed, and asserts
on the one observable that matters: the path that gets dofile'd. `dofile` is intercepted
rather than mocked away for `gen1/entry.lua`, so the detection the route depends on is the
real `Entry.detect_title`, not a restatement of it.
"""
from __future__ import annotations

import os

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the launchers")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_LUA = os.path.join(_REPO, "lua").replace("\\", "/")
_NEW_CLIENT = "lua/gen1/run.lua"
_OLD_CLIENT = "lua/clients/gen1_rby_client.lua"
_TITLE_OFFSET = 0x134


def _rom(title: str) -> bytes:
    """A cartridge image whose $0134 title field holds `title`, zero-padded."""
    image = bytearray(_TITLE_OFFSET + 16)
    image[_TITLE_OFFSET:_TITLE_OFFSET + len(title)] = title.encode("ascii")
    return bytes(image)


def _run_launcher(script: str, system_id: str | None, rom: bytes,
                  detected_game_id: str = "gen3_frlge", bizhawk: str = "2.11.1") -> list[str]:
    """dofile `lua/<script>` with stub BizHawk globals; return the paths it dofile'd.

    Only `gen1/entry.lua` is executed for real -- every other dofile target is recorded
    and skipped, so no client ever starts and one run cannot load two clients.
    """
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    loaded: list[str] = []

    def norm(path: str) -> str:
        rel = os.path.relpath(os.path.normpath(path), _REPO)
        return rel.replace("\\", "/")

    real_dofile = g.dofile

    def fake_dofile(path):
        rel = norm(path)
        loaded.append(rel)
        if rel.endswith("gen1/entry.lua"):
            return real_dofile(path)
        return None

    def getsystemid():
        if system_id is None:
            raise RuntimeError("no core loaded")
        return system_id

    g.dofile = fake_dofile
    g.emu = lua.table_from({"getsystemid": getsystemid})
    g.client = lua.table_from({"getversion": lambda: bizhawk})
    g.memory = lua.table_from({
        "read_u8": lambda addr, domain: rom[addr] if 0 <= addr < len(rom) else 0,
    })
    g.console = lua.table_from({"log": lambda *a: None})
    # The console tee would otherwise truncate slink_lua.log in the repo root; a nil
    # handle is the launcher's own "no log available" path.
    g.io.open = lambda *a: None
    g.require = lambda name: lua.table_from({
        "detect": lambda: lua.table_from({
            "module": lua.table_from({"display_name": detected_game_id}),
            "variant": "x", "profile": lua.table_from({}), "game_id": detected_game_id,
        }),
    }) if name == "game_detect" else None

    # The launcher itself is run through the real dofile so only its own calls are stubbed.
    real_dofile(f"{_LUA}/{script}")
    return loaded


@pytest.mark.parametrize("title", ["POKEMON RED", "POKEMON BLUE", "POKEMON YELLOW"])
def test_a_gen1_cartridge_reaches_the_new_client(title):
    loaded = _run_launcher("slink.lua", "GB", _rom(title))
    assert _NEW_CLIENT in loaded, f"{title} did not reach {_NEW_CLIENT}: {loaded}"
    assert _OLD_CLIENT not in loaded, f"{title} still loads the old client: {loaded}"


def test_super_game_boy_mode_reaches_the_new_client():
    """EmuHawk reports "SGB" for a GB cartridge with GbAsSgb on (opt-in); same ROM, same route."""
    loaded = _run_launcher("slink.lua", "SGB", _rom("POKEMON RED"))
    assert _NEW_CLIENT in loaded, f"SGB mode did not reach {_NEW_CLIENT}: {loaded}"


def test_only_one_client_is_ever_loaded():
    """The route returns; it must not fall through into game_detect as well."""
    loaded = _run_launcher("slink.lua", "GBC", _rom("POKEMON YELLOW"))
    clients = [p for p in loaded if "client" in p or p == _NEW_CLIENT]
    assert clients == [_NEW_CLIENT], f"expected exactly one client, got {clients}"


def test_an_old_bizhawk_is_refused_before_the_gen1_client_starts():
    """BizHawk 2.9.1 ran the client with every engine hook dead (live run 2026-09-22): no
    capture, no battle ever reported. Refuse it loudly instead."""
    with pytest.raises(lupa.LuaError, match="too old"):
        _run_launcher("slink.lua", "GBC", _rom("POKEMON GREEN"), bizhawk="2.9.1")


def test_a_non_gameboy_core_is_untouched_by_the_gen1_route():
    """Gen 2-5 keep going through game_detect; the GBA header even says RED."""
    loaded = _run_launcher("slink.lua", "GBA", _rom("POKEMON RED"))
    assert _NEW_CLIENT not in loaded, f"a GBA ROM was routed to Gen 1: {loaded}"
    assert "lua/clients/gen3_frlge_client.lua" in loaded, loaded


def test_an_unrecognised_gameboy_title_falls_through_to_game_detect():
    loaded = _run_launcher("slink.lua", "GBC", _rom("POKEMON CRYSTAL"),
                           detected_game_id="gen2_crystal")
    assert _NEW_CLIENT not in loaded, loaded
    assert "lua/clients/gen2_crystal_client.lua" in loaded, loaded


def test_a_failing_system_probe_does_not_route_to_gen1():
    loaded = _run_launcher("slink.lua", None, _rom("POKEMON RED"))
    assert _NEW_CLIENT not in loaded, loaded


def test_the_manual_gen1_launcher_loads_the_new_client():
    """slink_gen1.lua is what a player loads by hand; it has no detection of its own."""
    loaded = _run_launcher("slink_gen1.lua", "GB", _rom("POKEMON RED"))
    assert loaded == [_NEW_CLIENT], loaded


def test_a_pure_green_header_reaches_the_gen1_route():
    """PureGreen's header is POKEMON GREEN; run.lua then admits by sha1, never by header."""
    loaded = _run_launcher("slink.lua", "GBC", _rom("POKEMON GREEN"))
    assert _NEW_CLIENT in loaded and _OLD_CLIENT not in loaded, loaded


def test_the_production_entry_boots_an_unadmitted_vanilla_header_as_the_named_family():
    """Review finding (bbcd037..HEAD): `Entry.admit` is sha1-first and the vanilla companion-patch
    and randomized artifacts (patch/gen1/build/slink_red.gb, patch/build/gen1_red_ap.gb) are in
    no admission table, so run.lua must keep booting a recognised vanilla header as the named
    vanilla family — exactly what lua/tests/duo/duo_gen1_main.lua does — and must never take
    that path for a PureRed/PureBlue header (the pure builds are admitted by sha1)."""
    with open(os.path.join(_REPO, "lua", "gen1", "run.lua"), encoding="utf-8") as handle:
        src = handle.read()
    assert 'family == "red" or family == "blue" or family == "yellow"' in src
    assert 'pack = "gen1_rby", kind = "named"' in src
    assert "Pure" not in src.split('family == "red"')[1].split("else")[0]
