"""X3: `gen3_exp` is REGISTERED in lua/gen3/entry.lua (Entry.PACKS / Entry.PACK_FILES, the E2-ENTRY
precedent) but NOT routed and NOT admitted: the reference build's hash names its pack, the launcher
still refuses it, and only an OBSERVER build that names exactly "gen3_exp/<title>" constructs.
Routing and admission wait for the owner's XG gates (docs/gen3_emerald/PLAN.md X3/XG3).
"""
from __future__ import annotations

import json

from tests.unit.test_gen3_entry import REPO, World, _admit, lua_to_py

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


def test_the_launcher_refuses_it_as_unrouted():
    world = _world()
    codec = world.lua.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    got, why = world.Entry.admit_routed(world.lua.table(root=REPO.as_posix(), json=codec,
                                                        rom_hash=ARTIFACT["rom_sha1"]))
    assert got is None and "gen3_exp" in why and "not yet routed" in why
    assert "gen3_exp" not in lua_to_py(world.Entry.ROUTED)


def test_pack_files_are_the_builds_own_directory():
    files = lua_to_py(_world().Entry.PACK_FILES)["gen3_exp"]
    for rel in files.values():
        assert rel.startswith("data/games/gen3_exp/28877d73/") and (REPO / rel).is_file(), rel
