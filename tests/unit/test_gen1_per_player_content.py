"""Two players, two seeds, two different answers to "what does this route hold".

Everything else in SLink asks one run-global adapter. That is correct for rules -- the
supported randomizer settings deliberately exclude types, evolutions, movesets and base
stats, so the species and type clauses are seed-independent -- but it is wrong for CONTENT,
because two players may hold ROMs randomized with different seeds. These tests pin the
narrow per-player path and, just as importantly, that it does not leak into anything else.

The three ingestion states are the substance here. `adapter_for` returning the shipped
tables when nobody reported a ROM is right; returning them for a client whose report we
could NOT read is not, because that client only sends a report when it can see its ROM, so
a failure is evidence something is unusual about that ROM.
"""
from __future__ import annotations

import pytest

from server.adapters import get_adapter
from server.adapters.base import GameAdapter


class _Server:
    """The two attributes adapter_for and _ingest_rom_content actually touch.

    Deliberately not a real SLinkServer: constructing one needs a socket, a data directory
    and a run. The methods under test are bound off the real class so this stays honest --
    if their dependencies grow, this breaks rather than quietly testing a copy.
    """

    def __init__(self, adapter, rom_type="Red"):
        from server.server import SLinkServer
        self.adapter = adapter
        self._player_adapters = {}
        self.connected_players = {"a": {"rom_type": rom_type}, "b": {"rom_type": rom_type}}
        self.state = type("S", (), {"is_rr": False})()
        self.adapter_for = SLinkServer.adapter_for.__get__(self)
        self._ingest_rom_content = SLinkServer._ingest_rom_content.__get__(self)


def _payload(species_index: int, level: int = 3) -> dict:
    """A minimal but VALID rom_content: Route 1 (map 0x0C), grass only, ten equal slots."""
    slots = "".join(f"{level:02X}{species_index:02X}" for _ in range(10))
    return {"variant": "red", "wild": {"12": f"19{slots}00"},
            "old_rod": "8505", "good_rod": "0A9D0A47", "super_rod": {}}


def _server():
    return _Server(get_adapter("gen1_rby", rom_type="Red"))


# ── the three states ─────────────────────────────────────────────────────────────────────
def test_without_a_report_the_shipped_tables_are_used():
    srv = _server()
    table = srv.adapter_for("a").encounter_table("route_1")
    assert [e["name"] for e in table["Grass"]] == ["Pidgey", "Rattata"]


def test_a_valid_report_replaces_them_for_that_player_only():
    srv = _server()
    srv._ingest_rom_content("a", _payload(0x37))          # internal 0x37 -> Koffing
    assert [e["name"] for e in
            srv.adapter_for("a").encounter_table("route_1")["Grass"]] == ["Koffing"]
    # b never reported, so b still sees retail.
    assert [e["name"] for e in
            srv.adapter_for("b").encounter_table("route_1")["Grass"]] == ["Pidgey", "Rattata"]


def test_two_seeds_give_two_different_answers():
    """The whole point: one run, one area, two players, two truths."""
    srv = _server()
    srv._ingest_rom_content("a", _payload(0x37))          # Koffing
    srv._ingest_rom_content("b", _payload(0xB9))          # Oddish
    a = [e["name"] for e in srv.adapter_for("a").encounter_table("route_1")["Grass"]]
    b = [e["name"] for e in srv.adapter_for("b").encounter_table("route_1")["Grass"]]
    assert a == ["Koffing"] and b == ["Oddish"], (a, b)


@pytest.mark.parametrize("bad", [
    {"variant": "gold", "wild": {"12": "00"}},
    {"variant": "red", "wild": {}},
    {"variant": "red", "wild": {"12": "ZZZZ"}},
    {"variant": "red", "wild": {"12": "19"}},
])
def test_an_unreadable_report_shows_nothing_rather_than_retail(bad):
    """A rejected payload must NOT fall back to the shipped tables.

    This is the case the plan is emphatic about: retail species printed beside a randomized
    cartridge is worse than an empty panel, because the player believes it.
    """
    srv = _server()
    srv._ingest_rom_content("a", bad)
    assert srv.adapter_for("a").encounter_table("route_1") is None, (
        "a rejected payload fell back to the shipped tables")
    # And it is scoped to the player who sent it.
    assert srv.adapter_for("b").encounter_table("route_1") is not None


def test_a_generation_that_cannot_read_its_rom_is_unaffected():
    """ingest_rom_content returns None on the base adapter, and None must mean "no change".

    Without this, adding the hook would blank the encounter panel for every other
    generation the moment a client sent anything.
    """
    class _Mute:
        """Duck-typed on purpose: GameAdapter is abstract, and the server only calls
        ingest_rom_content / encounter_table on whatever it is handed."""

        game_id = "mute"

        def ingest_rom_content(self, payload):
            return GameAdapter.ingest_rom_content(self, payload)

        def encounter_table(self, area_id):
            return {"Grass": [{"species_id": 1, "name": "Bulbasaur", "rate": 100,
                               "min_level": 5, "max_level": 5}]}

    srv = _Server(_Mute(), rom_type="")
    srv._ingest_rom_content("a", _payload(0x37))
    assert srv._player_adapters == {}, "a mute adapter should not have been replaced"
    assert srv.adapter_for("a").encounter_table("route_1")["Grass"][0]["name"] == "Bulbasaur"


# ── the adapter contract ─────────────────────────────────────────────────────────────────
def test_none_and_empty_are_different_states_on_the_adapter():
    a = get_adapter("gen1_rby", rom_type="Red")
    assert a.encounter_table("route_1") is not None      # shipped
    a.use_rom_encounters({})
    assert a.encounter_table("route_1") is None          # tried and failed
    a.use_rom_encounters(None)
    assert a.encounter_table("route_1") is not None      # back to shipped


def test_adapters_do_not_share_rom_tables():
    """get_adapter builds a fresh object per call, which is what makes per-player affordable.

    If it ever became a singleton this fails, rather than one player silently seeing the
    other's routes.
    """
    a = get_adapter("gen1_rby", rom_type="Red")
    b = get_adapter("gen1_rby", rom_type="Red")
    assert a is not b
    a.use_rom_encounters({"route_1": {"Grass": [
        {"species_id": 109, "name": "Koffing", "rate": 100, "min_level": 3, "max_level": 3}]}})
    assert [e["name"] for e in b.encounter_table("route_1")["Grass"]] == ["Pidgey", "Rattata"]


def test_the_base_adapter_declines_by_default():
    assert GameAdapter.ingest_rom_content(object(), {"anything": True}) is None
