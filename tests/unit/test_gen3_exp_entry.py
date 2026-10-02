"""Production expansion admission uses its exact reference identity and original JSON pack."""
from __future__ import annotations

import json

import lupa
import pytest

from tests.unit.test_gen3_entry import REPO, World, _admit, _production, lua_to_py

TITLE = "emerald_expansion_28877d73"
PACK_DIR = REPO / "data/games/gen3_exp/28877d73"
ARTIFACT = json.loads((PACK_DIR / "engine_signals.json").read_text(encoding="utf-8"))[
    "titles"][TITLE]["artifacts"]["clean"]


def _world():
    return World(pack="gen3_frlg", title="firered", build=False)


def test_the_reference_hash_names_the_expansion_pack():
    for digest in (ARTIFACT["rom_sha1"], ARTIFACT["rom_md5"]):
        got = lua_to_py(_admit(_world(), rom_hash=digest.upper()))
        assert (got["pack"], got["title"], got["kind"], got["rom_type"]) == ("gen3_exp", TITLE, "clean", TITLE)
        assert got["admitted_by"] == "hash"


@pytest.mark.parametrize("digest", (ARTIFACT["rom_sha1"], ARTIFACT["rom_md5"]))
def test_original_production_entry_routes_the_exact_reference_hash(digest):
    world = World(pack="gen3_exp", title=TITLE, build=False)
    codec = world.lua.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    got = world.Entry.admit_routed(world.lua.table(root=REPO.as_posix(), json=codec, rom_hash=digest))
    assert lupa.lua_type(got) == "table", got
    admitted = lua_to_py(got)
    assert admitted["pack"] == "gen3_exp" and admitted["title"] == TITLE and admitted["admitted_by"] == "hash"
    client, parts = _production(world, rom_sha1=ARTIFACT["rom_sha1"])
    assert client is not None and (parts.pack, parts.title, parts.mode) == ("gen3_exp", TITLE, "production")
    assert world.registered == []
    client.start(client)
    assert len(world.registered) == sum(1 + len(site.get("mirror_offsets", [])) for site in world.sites.values())


@pytest.mark.parametrize("header", ("BPEE", "RHHE"))
def test_unknown_hash_with_valid_expansion_anchors_is_refused(header):
    world = World(pack="gen3_exp", title=TITLE, build=False)
    world.Entry.ROUTED.gen3_exp = True  # Isolated VM exposes the anchor guard before the route flip.
    codec = world.lua.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    result = world.Entry.admit_routed(world.lua.table(root=REPO.as_posix(), json=codec,
        rom_hash="0" * 40, rom_read=world._rom_read, header_code=header))
    assert isinstance(result, tuple), "unknown hash was admitted by expansion anchors"
    got, why = result
    assert got is None and ("not a pinned cartridge" in why or "not an admitted Gen 3 cartridge" in why)


@pytest.mark.parametrize("pack,title,header", [("gen3_frlg", "firered", "BPRE"),
    ("gen3_frlg", "leafgreen", "BPGE"), ("gen3_rr", "radical_red", "BPRE"),
    ("gen3_emerald", "emerald", "BPEE")])
def test_vanilla_and_rr_unknown_hash_anchor_admission_is_unchanged(pack, title, header):
    world = World(pack=pack, title=title, build=False)
    codec = world.lua.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    got = world.Entry.admit_routed(world.lua.table(root=REPO.as_posix(), json=codec,
        rom_hash="0" * 40, rom_read=world._rom_read, header_code=header))
    assert lupa.lua_type(got) == "table"
    assert got.pack == pack and got.title == title and got.admitted_by == "anchors"


def test_wrong_hash_header_only_and_wrong_build_remain_refused():
    world = World(pack="gen3_exp", title=TITLE, build=False)
    codec = world.lua.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    for header in ("BPEE", "RHHE"):
        got, why = world.Entry.admit_routed(world.lua.table(root=REPO.as_posix(), json=codec,
            rom_hash="f" * 40, header_code=header))
        assert got is None and ("not a pinned cartridge" in why or "not an admitted Gen 3 cartridge" in why)
    with pytest.raises(lupa.LuaError, match="unknown title"):
        world.Entry.build(world.deps(title="emerald_expansion_wrong_build"))
    with pytest.raises(lupa.LuaError, match="ships no artifact of kind companion"):
        world.Entry.build(world.deps(kind="companion"))


def test_original_production_build_reads_the_admitted_own_pack_without_any_overlay():
    world = World(pack="gen3_exp", title=TITLE, build=False)
    client, parts = _production(world, rom_sha1=ARTIFACT["rom_sha1"])
    assert client is not None and parts.pack == "gen3_exp" and parts.title == TITLE
    assert parts.mode == "production" and not any("unadmitted" in message for message in world.logs)


def test_in_memory_route_and_anchor_eligibility_reverts_are_detected():
    source = (REPO / "lua/gen3/entry.lua").read_text(encoding="utf-8")
    mutations = {
        "route": source.replace("gen3_emerald = true, gen3_exp = true", "gen3_emerald = true", 1),
        "anchor_guard": source.replace("hash_only = true,", "hash_only = false,", 1),
    }
    for name, reverted in mutations.items():
        assert reverted != source
        world = World(pack="gen3_exp", title=TITLE, build=False)
        world.Entry = world.lua.execute(reverted)
        codec = world.lua.eval(f'dofile("{(REPO / "lua/json_codec.lua").as_posix()}")')
        args = world.lua.table(root=REPO.as_posix(), json=codec,
            rom_hash=ARTIFACT["rom_sha1"] if name == "route" else "0" * 40,
            rom_read=world._rom_read, header_code="BPEE")
        result = world.Entry.admit_routed(args)
        if name == "route":
            assert isinstance(result, tuple) and result[0] is None and "not yet routed" in result[1]
        else:
            assert lupa.lua_type(result) == "table" and result.admitted_by == "anchors"
        world.Entry = world.lua.execute(source)
        restored = world.Entry.admit_routed(args)
        assert (lupa.lua_type(restored) == "table") is (name == "route")


def test_in_memory_profile_admission_revert_refuses_production_build():
    source = (REPO / "lua/gen3/entry.lua").read_text(encoding="utf-8")
    needle = "    -- The one exception (Gen 3 grant"
    assert needle in source
    reverted = source.replace(needle, "    profile.admitted = false\n" + needle, 1)
    world = World(pack="gen3_exp", title=TITLE, build=False)
    world.Entry = world.lua.execute(reverted)
    with pytest.raises(lupa.LuaError, match="known but unadmitted"):
        _production(world, rom_sha1=ARTIFACT["rom_sha1"])
    world.Entry = world.lua.execute(source)
    assert _production(world, rom_sha1=ARTIFACT["rom_sha1"])[0] is not None


def test_pack_files_are_the_builds_own_directory():
    files = lua_to_py(_world().Entry.PACK_FILES)["gen3_exp"]
    for rel in files.values():
        assert rel.startswith("data/games/gen3_exp/28877d73/") and (REPO / rel).is_file(), rel
