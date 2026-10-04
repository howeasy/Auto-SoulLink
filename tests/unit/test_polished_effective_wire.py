"""Polished variant forms judged as distinct mons end to end (owner rulings 2026-10-04).

A regional/variant form (Alolan Rattata = species 19 form 2) is a DIFFERENT mon: the Lua reads give it its EFFECTIVE
species id (its BaseData record index, polished_codec.effective_species: 295), so every wire species_id (party, foe,
box, capture) carries it and the server's species-keyed rules (names, types, families, the species clause) see 295.
The key never changes: raw 9-bit species + variant form bits (polished_codec.key). A cosmetic form (Unown B) stays
ONE mon: form bits 0 in the key, effective id = the species.

The chain is real: the overlay ROM composed by lua/gen2/entry.lua over a WRAM image, the client's own hello and
capture lines captured off its net and replayed into a real SLinkServer.
"""
from __future__ import annotations

import json
import random

import pytest

from server.adapters import polished_codec as pc
from tests.unit.test_mixed_foundations import _refused, _session
from tests.unit.test_polished_client import _entry, _key, _memory, _rig, _run
from tests.unit.test_polished_lua import ROOT, _mon, _pair, _real, load_variants

lupa = pytest.importorskip("lupa")

ALOLAN, PLAIN, UNOWN_B = (19, 2), (19, 0), (201, 2)   # species_index.json forms: RATTATA ALOLAN_FORM, UNOWN_B_FORM
UMBREON = 197                                          # plain Dark


def _mons():
    rng = random.Random(41)
    mons = []
    for species, form in (ALOLAN, PLAIN, UNOWN_B):
        mon = _mon(rng, species)
        mon.update(form=form, is_egg=False, shiny=False)   # a shiny takes the shiny-bonus path, not the clause
        mons.append(mon)
    return mons


@pytest.fixture(scope="module")
def composed():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    mons = _mons()
    deps, io, log = _rig(lua, _real()[1], _memory(mons))
    parts, why = _pair(_entry(lua).build(deps))
    assert why is None, why
    parts.client.start(parts.client)
    _run(io, parts.client, 20)
    return lua, mons, parts, io, log


def _party(parts):
    party = parts.reads.read_party()   # a lone table, or (nil, why)
    assert not isinstance(party, tuple), party
    return party


def _sent(log, event):
    return [json.loads(line) for line in log.sent.values() if json.loads(line)["event"] == event]


def _capture_line(composed, slot, area_id):
    """client.lua publish_capture over the REAL read record the binder copies (reads.read_party)."""
    lua, _, parts, io, log = composed
    before = len(_sent(log, "capture"))
    party = _party(parts)
    ev = lua.table_from({"kind": "capture", "mon": party.mons[slot + 1], "area_id": area_id,
                         "acquisition": "wild", "destination": "party"})
    parts.client.on_event(parts.client, ev)
    _run(io, parts.client, 2)
    captures = _sent(log, "capture")
    assert len(captures) == before + 1, list(log.lines.values())
    return captures[-1]


def test_the_wire_carries_effective_ids_and_the_unchanged_key(composed):
    _, mons, parts, _, log = composed
    (hello,) = _sent(log, "hello")
    party = hello["party"]
    assert [e["species_id"] for e in party] == [295, 19, 201]
    assert [e["key"] for e in party] == [_key(m) for m in mons]          # byte-identical to polished_codec.key
    fields = [e["key"].split(":") for e in party]                     # DDDDDD:OOOO:SSS:TT
    assert [(f[2], int(f[3], 16) & 0x1F) for f in fields] == [("013", 2), ("013", 0), ("0C9", 0)]  # cosmetic: form 0
    for entry, mon in zip(party, mons, strict=True):                  # the blob stays the RAW record
        assert entry["blob_hex"][:96] == pc.encode_party_mon(mon).hex()
    records = _party(parts).mons
    assert [(records[i + 1].species_id, records[i + 1].form) for i in range(3)] == [(295, 2), (19, 0), (201, 2)]


def test_cosmetic_forms_are_one_mon_and_variants_are_two():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    P = load_variants(lua, lua.eval(f'dofile("{ROOT}/lua/gen2/polished.lua")'))
    base = {"dv_bytes": 0x123456, "ot_id": 0x30B8, "shiny": False, "gender": "male"}
    key = lambda species, form: P.mon_key(lua.table_from(dict(base, species_id=species, form=form)))  # noqa: E731
    assert key(201, 2) == key(201, 3) == pc.key(dict(base, species_id=201, form=2)) == pc.key(dict(base, species_id=201, form=3))
    assert pc.effective_species(201, 2) == pc.effective_species(201, 3) == 201
    # the effective record id keys exactly as the raw (species, form) it stands for; the plain form keys apart
    assert key(295, 2) == key(19, 2) == pc.key(dict(base, species_id=19, form=2)) != key(19, 0)
    box = P.box_entry(lua.table_from(dict(base, species_id=19, form=2, slot=3, level=9, held_item=0,
                                          moves=lua.table_from([33, 0, 0, 0]))), 4)
    assert (box.species_id, box.key) == (295, key(19, 2))


@pytest.mark.asyncio
async def test_the_real_server_judges_the_variant_as_its_own_mon(composed, tmp_path):
    from server.server import SLinkServer
    from server.state import MonInfo
    _, mons, _, _, log = composed
    (hello,) = _sent(log, "hello")
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.species_lock = True
    send, close = await _session(srv)
    try:
        reply = await send(hello)
        assert not _refused(reply) and srv.is_admitted("a"), srv.state.identity_error
        alolan, plain, unown = (_key(m) for m in mons)
        details = srv._build_status_dict()["players"]["a"]["party_details"]
        assert [(details[k]["species_id"], details[k]["species_name"]) for k in (alolan, plain, unown)] == [
            (295, "Rattata (Alolan)"), (19, "Rattata"), (201, "Unown")]
        assert details[alolan]["gender"] in ("male", "female")              # gender_from_key reads the effective id
        adapter = srv.adapter
        assert adapter.species_types(295) == (16, 0) and adapter.species_types(19) == (0, 0)   # Dark/Normal vs Normal
        assert adapter.evo_family(295) != adapter.evo_family(19)
        state = srv.state
        state.type_lock = True
        umbreon = MonInfo(key="000000:0000:0C5:00", species=UMBREON)
        assert "Type clause" in state._check_link_violation(MonInfo(key=alolan, species=295), umbreon)[0]
        assert state._check_link_violation(MonInfo(key=plain, species=19), umbreon) is None

        # the species clause: a plain Rattata pending in route_29, then the Alolan one in route_30 is NOT a dup
        def deaths(reply):   # the reply carries what the capture queued (force_faint + "[x] Dup ...")
            return [c for c in reply["commands"] if c.get("cmd") == "force_faint" or "Dup" in c.get("text", "")]
        first = _capture_line(composed, 1, "route_29")
        assert (first["species_id"], first["key"]) == (19, plain)
        assert deaths(await send(first)) == []
        second = _capture_line(composed, 0, "route_30")
        assert (second["species_id"], second["key"]) == (295, alolan)
        assert deaths(await send(second)) == []
        assert state.pending_captures["route_29"]["a"].species == 19
        assert state.pending_captures["route_30"]["a"].species == 295
        # positive control: the same line with the RAW species (the old wire) is a dup of the pending Rattata
        raw = dict(second, species_id=19, area_id="route_31", key="000001" + second["key"][6:],
                   seq=second["seq"] + 1)   # a fresh mon and message, else the seq/key guards drop it first
        assert len(deaths(await send(raw))) == 2 and "route_31" not in state.pending_captures
    finally:
        await close()


def test_the_adapter_answers_for_effective_ids():
    from server.adapters.gen2_polished import Gen2PolishedAdapter
    adapter = Gen2PolishedAdapter()
    for (species, form), record in pc.variant_records().items():     # one name per mon, however it is asked
        assert adapter.species_name(record) == adapter.species_name(species, form) != adapter.species_name(species)
    key = "31D962:0963:013:42"                                        # Alolan Rattata (form 2), female
    assert adapter.gender_from_key(key, 295) == adapter.gender_from_key(key, 19) == "female"
    assert adapter.gender_from_key(key, 20) == ""                     # another species is still no answer
    assert adapter.gift_link_area("route_30", acquisition="gift", species_id=295) == "gift_route_30"
    assert adapter.sprite_src(295) == ""                              # no pinned art for a variant: no Kanto sprite
