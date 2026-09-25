"""E2-ENTRY+BADGE: `gen3_emerald` is registered in `lua/gen3/entry.lua` (Entry.PACKS /
Entry.PACK_FILES) but deliberately absent from Entry.ROUTED (docs/gen3_emerald/PLAN.md §5 E2
row; owner-lane grant: "gen3_emerald must NOT be added to Entry.ROUTED until EG4").

Same harness as `test_gen3_entry.py` (lupa over the real `lua/gen3/entry.lua`) and
`test_slink_route.py` (lupa over the real `lua/slink.lua`, BizHawk globals stubbed); both are
imported rather than restated (`docs/agents/worker_card.md` reuse-before-writing).
"""
from __future__ import annotations

import json

import lupa
import pytest

from tests.unit.test_gen3_entry import PACKS, REPO, World, _admit, lua_to_py
from tests.unit.test_slink_route import _NEW_GEN3_CLIENT, _rom_gba, _run_launcher

_EMERALD_DIR = REPO / "data" / "games" / "gen3_emerald"
_EMERALD_SHA1 = json.loads(
    (_EMERALD_DIR / "engine_signals.json").read_text(encoding="utf-8")
)["titles"]["emerald"]["artifacts"]["clean"]["rom_sha1"]

# The owner-lane pin (docs/gen3_emerald/PLAN.md §0 "ROM" row) -- must equal the shipped
# engine_signals.json pin, or the pack data has drifted from the card's own brief.
_PINNED_EMERALD_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"


def test_the_pinned_emerald_sha1_matches_the_shipped_pack_data():
    assert _EMERALD_SHA1 == _PINNED_EMERALD_SHA1


# ── (a) route: BPEE + the pinned hash is still refused, never dofile'd to gen3/run.lua ──────
def test_a_clean_emerald_sha1_is_still_refused_by_name_not_routed():
    """MUTATION-CHECK: this is the falsifier for 'gen3_emerald must never join Entry.ROUTED
    before EG4'. If a future edit adds `gen3_emerald = true` to Entry.ROUTED, admission by
    hash succeeds AND is routed, `lua/gen3/run.lua` gets dofile'd, and this test goes red
    (both the exception-not-raised assertion and the explicit ROUTED guard below)."""
    with pytest.raises(lupa.LuaError, match="Unsupported Gen 3 cartridge: Pokemon Emerald"):
        _run_launcher("GBA", _rom_gba(header_code="BPEE"), rom_hash=_EMERALD_SHA1)


def test_a_clean_emerald_sha1_never_reaches_gen3_run_lua():
    """The same call as above, but asserting on the positive side: whatever `_run_launcher`
    dofile's, `gen3/run.lua` is never in it, however the refusal happens to be worded."""
    loaded: list[str] = []
    with pytest.raises(lupa.LuaError):
        try:
            loaded = _run_launcher("GBA", _rom_gba(header_code="BPEE"), rom_hash=_EMERALD_SHA1)
        finally:
            pass
    assert _NEW_GEN3_CLIENT not in loaded, loaded


def test_gen3_emerald_is_never_in_entry_routed():
    world = World(pack="gen3_frlg", title="firered", build=False)
    routed = lua_to_py(world.Entry.ROUTED)
    assert "gen3_emerald" not in routed, (
        "gen3_emerald joined Entry.ROUTED -- forbidden before EG4 "
        "(docs/gen3_emerald/PLAN.md owner-lane grant)")


# ── (b) Entry.admit on the Emerald hash ──────────────────────────────────────────────────
def test_entry_admit_on_the_emerald_hash_returns_the_emerald_pack():
    world = World(pack="gen3_frlg", title="firered", build=False)
    got = lua_to_py(_admit(world, rom_hash=_EMERALD_SHA1))
    assert (got["pack"], got["title"], got["kind"]) == ("gen3_emerald", "emerald", "clean")
    assert got["rom_type"] == "emerald"
    assert got["admitted_by"] == "hash"


# ── (c) FR/LG/RR admission is unchanged; admission_table still builds (no collisions) ──────
@pytest.mark.parametrize("pack,title,kind", [
    ("gen3_frlg", "firered", "clean"),
    ("gen3_frlg", "leafgreen", "clean"),
    ("gen3_rr", "radical_red", "clean"),
    ("gen3_rr", "radical_red", "companion"),
])
def test_frlg_and_rr_admission_is_unchanged_by_the_emerald_pack(pack, title, kind):
    world = World(pack="gen3_frlg", title="firered", build=False)
    sha1 = json.loads((REPO / "data" / "games" / pack / "engine_signals.json")
                      .read_text(encoding="utf-8"))["titles"][title]["artifacts"][kind]["rom_sha1"]
    got = lua_to_py(_admit(world, rom_hash=sha1))
    assert (got["pack"], got["title"], got["kind"]) == (pack, title, kind)
    assert got["admitted_by"] == "hash"


def test_admission_table_builds_with_gen3_emerald_registered_no_hash_collisions():
    """Entry.admission_table now iterates gen3_emerald too (Entry.PACKS grew a row): building
    it over the real, unmodified pack tree is the assertion that the Emerald pin doesn't
    collide with any FR/LG/RR/companion digest."""
    world = World(pack="gen3_frlg", title="firered", build=False)
    json_codec = world.lua.eval(
        f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    table = lua_to_py(world.Entry.admission_table(REPO.as_posix(), json_codec))
    assert table[_EMERALD_SHA1.lower()]["pack"] == "gen3_emerald"
    # every FR/LG/RR digest from the existing PACKS map is still present and unambiguous
    for pack, source in PACKS.items():
        titles = json.loads((source / "engine_signals.json").read_text(encoding="utf-8"))["titles"]
        for title, entry in titles.items():
            for kind, artifact in entry["artifacts"].items():
                digest = artifact["rom_sha1"].lower()
                assert table[digest]["pack"] == pack
                assert table[digest]["title"] == title
                assert table[digest]["kind"] == kind
