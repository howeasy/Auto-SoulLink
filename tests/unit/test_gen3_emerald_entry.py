"""E2-ENTRY+BADGE: `gen3_emerald` is registered in `lua/gen3/entry.lua` (Entry.PACKS /
Entry.PACK_FILES) but deliberately absent from Entry.ROUTED (docs/gen3_emerald/PLAN.md §5 E2
row; owner-lane grant: "gen3_emerald must NOT be added to Entry.ROUTED until EG4").

Same harness as `test_gen3_entry.py` (lupa over the real `lua/gen3/entry.lua`) and
`test_slink_route.py` (lupa over the real `lua/slink.lua`, BizHawk globals stubbed); both are
imported rather than restated (`docs/agents/worker_card.md` reuse-before-writing).
"""
from __future__ import annotations

import json
import re

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
        loaded = _run_launcher("GBA", _rom_gba(header_code="BPEE"), rom_hash=_EMERALD_SHA1)
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


# ── (d) the observer-only seam for the EG2 run (Gen 3 grant 2026-09-26, four guards) ──────
_MSG = "emerald is a known but unadmitted Gen 3 title in gen3_emerald"


def test_an_unadmitted_emerald_observer_build_needs_the_explicit_flag():
    world = World(pack="gen3_emerald", title="emerald", build=False)
    with pytest.raises(lupa.LuaError, match=_MSG):
        world.Entry.build(world.deps())
    for wrong in (True, "1", "gen3_frlg/emerald", "gen3_emerald/firered"):   # exact pack/title only
        with pytest.raises(lupa.LuaError, match=_MSG):
            world.Entry.build(world.deps(allow_unadmitted=wrong))
    assert world.registered == []
    # guard 1: write-free, over the observer's REAL io (shadow_run.build_io: every sink refuses)
    shadow = world.lua.eval(f'dofile("{(REPO / "lua/gen3/shadow_run.lua").as_posix()}")')
    mem = world.lua.table(
        read_u8=lambda a, d=None: (world.rom if d == "ROM" else world.bus).get(int(a), 0),
        read_u16_le=lambda a, d=None: world._read(int(a), 2),
        read_u32_le=lambda a, d=None: world._read(int(a), 4),
        framecount=lambda: world.frame)
    world.io = shadow.build_io(mem, lambda name: 0)
    client, parts = world.Entry.build(world.deps(allow_unadmitted="gen3_emerald/emerald"))
    assert client is None and parts.mode == "observer"
    assert parts.writes is None and parts.native is None and parts.signals is not None
    for sink in ("write_u8", "write_u16", "write_u32", "write_bytes"):
        with pytest.raises(lupa.LuaError):
            world.io[sink](0x02000000, 0)
    # guard 4: one log line names the unadmitted build
    assert [line for line in world.logs if "OBSERVER building unadmitted" in line] == [
        "[SLink-gen3] OBSERVER building unadmitted gen3_emerald/emerald"]


def test_production_refuses_an_unadmitted_title_even_with_the_flag(monkeypatch):
    """Guard 2: the same message in production, flag or not, env or not."""
    from tests.unit.test_gen3_entry import _production
    monkeypatch.setenv("SLINK_SHADOW_UNADMITTED", "gen3_emerald/emerald")
    world = World(pack="gen3_emerald", title="emerald", build=False)
    with pytest.raises(lupa.LuaError, match=_MSG):
        _production(world, allow_unadmitted="gen3_emerald/emerald")
    with pytest.raises(lupa.LuaError, match=_MSG):
        _production(world)
    assert world.registered == []


def test_only_the_observer_reads_the_unadmitted_env_and_slink_never_loads_it():
    """Guard 2: entry.lua takes the flag from deps only; lua/slink.lua never dofiles the
    observer; shadow_run.lua is the one reader of SLINK_SHADOW_UNADMITTED."""
    src = {p: (REPO / p).read_text(encoding="utf-8") for p in (
        "lua/gen3/entry.lua", "lua/gen3/shadow_run.lua", "lua/slink.lua", "lua/gen3/run.lua")}
    assert "SLINK_SHADOW_UNADMITTED" not in src["lua/gen3/entry.lua"]
    assert 'allow_unadmitted = getenv("SLINK_SHADOW_UNADMITTED")' in src["lua/gen3/shadow_run.lua"]
    for launcher in ("lua/slink.lua", "lua/gen3/run.lua"):
        code = re.sub(r"--[^\n]*", "", src[launcher])  # comments may name it
        assert not re.search(r"(dofile|require|loadfile)[^\n]*shadow_run", code), launcher
        assert "allow_unadmitted" not in src[launcher] and "SLINK_SHADOW_UNADMITTED" not in src[launcher]
    assert 'mode == "observer"' in src["lua/gen3/entry.lua"].split("observe_unadmitted =", 1)[1][:200]


@pytest.mark.parametrize("pack,title,kind", [
    ("gen3_frlg", "firered", "clean"), ("gen3_frlg", "leafgreen", "clean"),
    ("gen3_rr", "radical_red", "clean"), ("gen3_rr", "radical_red", "companion"),
])
def test_the_flag_changes_nothing_for_admitted_titles(pack, title, kind):
    """Guard 3: an admitted title builds identically with or without the flag, and logs no
    unadmitted line."""
    a = World(pack=pack, title=title, kind=kind, build=False)
    b = World(pack=pack, title=title, kind=kind, build=False)
    _, pa = a.Entry.build(a.deps())
    _, pb = b.Entry.build(b.deps(allow_unadmitted=f"{pack}/{title}"))
    assert (pa.pack, pa.title, pa.artifact_kind, pa.rom_hash) == (pb.pack, pb.title, pb.artifact_kind, pb.rom_hash)
    assert a.registered == b.registered and a.logs == b.logs
    assert not any("unadmitted" in line for line in b.logs)
