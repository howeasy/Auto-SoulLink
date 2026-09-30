"""tests/unit/test_gen3_rr_generators.py -- receipts for the Radical Red data
generators (tools/gen_rr_*.py) against data/gen3_rr_sources.lock.json.
See docs/gen3_requirements.md row F-7.

Offline (always run): the lock parses, and every generator's own
cached_source()/cached_source_path() calls name a source the lock declares
-- and every declared source is actually read by some generator (no orphan
pins).

Online (needs a populated cache): if $SLINK_RR_SRC_CACHE holds the pinned
sources verified against their hashes, this runs each generator's --check
against them. Absent cache => named pytest.skip (never a silent pass);
present-but-wrong-hash => a named FAIL, because cached_source() itself
raises rather than returning unverified bytes. Populate the cache with:
    python tools/fetch_rr_sources.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "data" / "gen3_rr_sources.lock.json"

sys.path.insert(0, str(ROOT / "tools"))
import fetch_rr_sources as rrfetch  # noqa: E402

GENERATOR_SCRIPTS = [
    "tools/gen_rr_species.py",
    "tools/gen_rr_types.py",
    "tools/gen_rr_natdex.py",
    "tools/gen_rr_encounters.py",
    "tools/gen_rr_sprites.py",
    "tools/gen_rr_priority_trainers.py",
]


def _lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _cached_source_names(script_relpath: str) -> set[str]:
    text = (ROOT / script_relpath).read_text(encoding="utf-8")
    return set(re.findall(r'cached_source(?:_path)?\("([^"]+)"', text))


def test_lock_parses():
    lock = _lock()
    assert lock["schema_version"] == 1
    assert lock["sources"], "lock declares no sources"
    for name, entry in lock["sources"].items():
        assert entry.get("fetch_url"), f"{name}: missing fetch_url"
        assert entry.get("sha256") or entry.get("content_sha256"), f"{name}: no hash pin"


@pytest.mark.parametrize("script", GENERATOR_SCRIPTS)
def test_generator_pins_are_declared(script):
    """Every source name a generator's own code passes to cached_source()/
    cached_source_path() must exist in the lock -- catches a generator that
    silently reverted to a live, unpinned fetch."""
    lock = _lock()
    declared = _cached_source_names(script)
    assert declared, f"{script} never calls cached_source()/cached_source_path()"
    missing = declared - set(lock["sources"])
    assert not missing, f"{script} reads {missing}, not declared in {LOCK_PATH}"


def test_every_lock_source_is_read_by_some_generator():
    lock = _lock()
    used: set[str] = set()
    for script in GENERATOR_SCRIPTS:
        used |= _cached_source_names(script)
    unused = set(lock["sources"]) - used
    assert not unused, f"lock declares source(s) no generator reads: {unused}"


@pytest.mark.parametrize("script", GENERATOR_SCRIPTS)
def test_generator_check_against_cache(script):
    """ONLINE: run `python <script> --check` against the cached, pinned
    sources it declares. Skips by name when any of them isn't cached yet;
    a cached-but-wrong-hash file is never treated as a skip -- cached_source
    raises, which surfaces here as a FAIL naming the source."""
    if "openpyxl" in (ROOT / script).read_text(encoding="utf-8"):
        # F2: openpyxl is a dev-only extra (requirements-dev.txt), not a hard
        # dependency -- a fresh env without it gets a named skip here, never
        # a raw ImportError failure.
        pytest.importorskip("openpyxl")
    if script in ("tools/gen_rr_species.py", "tools/gen_rr_encounters.py", "tools/gen_rr_types.py"):
        from tools.rr_rom_encounters import default_rom_path
        if not default_rom_path().exists():
            pytest.skip("ROM-authoritative RR generation requires SLINK_RR_ROM or SLINK_GEN3_ROMS")
    for name in sorted(_cached_source_names(script)):
        try:
            rrfetch.cached_source(name, allow_fetch=False)
        except FileNotFoundError as exc:
            pytest.skip(f"{name} not cached (run `python tools/fetch_rr_sources.py`): {exc}")
    result = subprocess.run(
        [sys.executable, str(ROOT / script), "--check"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"{script} --check drifted from its committed output (exit {result.returncode}). "
        f"See docs/gen3_requirements.md F-7 -- gen_rr_priority_trainers.py's committed "
        f"roster was last regenerated from the {LOCK_PATH.name} pin on 2026-09-27 (card "
        f"RR-PT); a fresh drift here means the pin has moved again since, not a broken "
        f"pin -- re-run `python tools/gen_rr_priority_trainers.py` and diff the result.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


_NETWORK_CALL_PATTERNS = ("urlopen(", "requests.", "httpx.", "socket.")


def _strip_docstrings(text: str) -> str:
    return re.sub(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')', "", text)


@pytest.mark.parametrize("script", GENERATOR_SCRIPTS)
def test_generator_has_no_direct_network_calls(script):
    """F5/F6/F10/F12: every gen_rr_*.py must route fetching through
    fetch_rr_sources.py's cached_source()/cached_source_path() -- never call
    urlopen/requests/httpx/socket directly, which would bypass the pin and
    silently go live again. Only mentions in docstrings (usage examples,
    curl snippets) are allowed."""
    code = _strip_docstrings((ROOT / script).read_text(encoding="utf-8"))
    hits = [p for p in _NETWORK_CALL_PATTERNS if p in code]
    assert not hits, (
        f"{script} appears to call {hits} directly instead of going through "
        f"fetch_rr_sources.cached_source()/cached_source_path()"
    )


def test_fetch_rr_sources_rejects_unknown_flag(monkeypatch):
    """F5/F6/F10/F12: an unrecognised flag must be a parser error (argparse),
    never a silent fall-through to fetching every pinned source live."""
    calls = []
    monkeypatch.setattr(rrfetch, "cached_source",
                         lambda *a, **k: calls.append(a) or b"")
    with pytest.raises(SystemExit):
        rrfetch.main(["--totally-bogus-flag"])
    assert not calls, "an unrecognised flag must not trigger any fetch/verify"


def test_gitignore_covers_rr_src_cache():
    """F5/F6/F10/F12: the default cache dir must not get committed."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/.rr_src_cache/" in gitignore


def test_species_and_types_write_target_matches_check_target():
    """F3: `python tools/gen_rr_{species,types}.py` (no --check) must write
    the exact file --check compares against -- previously each wrote a
    stray, unread data/rr_*.json at the repo root while --check compared
    data/games/gen3_frlge/rr_*.json, so a real (non---check) regen never
    reached any consumer."""
    import gen_rr_species
    import gen_rr_types
    assert Path(gen_rr_species.OUT_JSON) == gen_rr_species.CANONICAL_OUTPUT
    assert Path(gen_rr_types.OUTPUT) == gen_rr_types.CANONICAL_OUTPUT


def test_parse_calc_sets_missing_file_is_loud(tmp_path):
    """F8/F11: a missing calc/normal.js must raise, not silently return []
    and drop every calc-sourced trainer from the roster."""
    import gen_rr_priority_trainers as grpt
    with pytest.raises(FileNotFoundError):
        grpt.parse_calc_sets(tmp_path / "does_not_exist.js")


def test_priority_trainers_default_src_uses_pinned_cache(monkeypatch, tmp_path):
    """F4: with no --src, the generator must resolve through the pinned
    cache (fetch_rr_sources.cached_source_path), never an unverified
    repo-root xlsx."""
    pytest.importorskip("openpyxl")
    import gen_rr_priority_trainers as grpt

    used = {}
    fake_src = tmp_path / "pinned.xlsx"

    def fake_cached_source_path(name):
        used["cached_source_name"] = name
        return fake_src

    def fake_build_roster(src):
        used["build_src"] = src
        return {"parties": {}}, []

    monkeypatch.setattr(rrfetch, "cached_source_path", fake_cached_source_path)
    monkeypatch.setattr(grpt, "_build_roster", fake_build_roster)
    monkeypatch.setattr(grpt, "_write_outputs", lambda out_doc, out: used.setdefault("wrote", True))
    monkeypatch.setattr(sys, "argv",
                         ["gen_rr_priority_trainers.py", "--out", str(tmp_path / "out.json")])
    rc = grpt.main()
    assert rc == 0
    assert used["cached_source_name"] == "rr_priority_trainers_sheet_xlsx"
    assert used["build_src"] == fake_src
    assert used["wrote"]


def test_priority_trainers_explicit_src_warns(monkeypatch, tmp_path, capsys):
    """F4: an explicit --src overrides the pin, but must say so loudly."""
    pytest.importorskip("openpyxl")
    import gen_rr_priority_trainers as grpt

    fake_src = tmp_path / "custom.xlsx"
    fake_src.write_bytes(b"")
    monkeypatch.setattr(grpt, "_build_roster", lambda src: ({"parties": {}}, []))
    monkeypatch.setattr(grpt, "_write_outputs", lambda out_doc, out: None)
    monkeypatch.setattr(sys, "argv",
                         ["gen_rr_priority_trainers.py", "--src", str(fake_src),
                          "--out", str(tmp_path / "out.json")])
    rc = grpt.main()
    assert rc == 0
    err = capsys.readouterr().err
    assert "WARNING" in err and "NOT hash-verified" in err


def _make_xlsx_bytes(image_url: str) -> bytes:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Brock"
    ws["A2"] = f'=IMAGE("{image_url}")'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_content_sha256_covers_extracted_image_urls():
    """F1: two xlsx that differ ONLY in a `=IMAGE(url)` sprite formula must
    hash differently. Both have the identical data_only=True cell view (a
    formula cell with no cached value reads as None either way) -- only the
    extracted image URL differs, which is exactly what a sheet author
    swapping a trainer sprite would look like. sprite_url is committed into
    rr_priority_trainers.json, so this must be covered by the pin."""
    pytest.importorskip("openpyxl")
    a = rrfetch._xlsx_content_sha256(_make_xlsx_bytes("https://example.com/a.png"))
    b = rrfetch._xlsx_content_sha256(_make_xlsx_bytes("https://example.com/b.png"))
    assert a != b


_GEN3_FRLGE_DIR = ROOT / "data" / "games" / "gen3_frlge"

# card RR-PT2 (2026-09-27, tightened same day per a coordinator follow-up):
# the 11 abbreviated building/room keys that used to live here
# (celadon_hotel, cinnabar_gym, cinnabar_isl, dig_house, joyful, mansion_f4,
# nugget_bridge, pewter_museum, rocket_hideout, ss_anne, treasure_bea), plus
# celadon_city_game_corner found in the follow-up, all matched
# gen3_frlge_locations.lua's FINE per-room table but not area_map.json's
# COARSE one, so their trainers could never appear in the Upcoming Key
# Trainers widget in practice: server.py's trainer-panel call
# (`self.player_area_id.get(pid, "") or self.player_area.get(pid, "")`,
# server.py ~:2843) only ever falls back to the fine `player_area` value
# before the player's FIRST coarse area_enter this session -- every
# area_enter/hello after that keeps player_area_id STICKY at the last
# non-empty coarse reading (server.py's handlers only overwrite it
# `if area:`), so a
# fine-only id like "rocket_hideout_b1f" or "celadon_city_game_corner" is,
# in real play, effectively unreachable. tools/gen_rr_priority_trainers.py's
# _AREA_OVERRIDES now maps every one of these to the area_id the client
# actually holds while standing there (the nearest area_map.json-mapped
# ancestor over pret's warps/connections, same rule
# tools/gen_gen3_trainers.py's area_of_map() uses for vanilla FR/LG) --
# see docs/gen3/research/rr_priority_regen_2026-09-26.md for the per-key trace.
# No allowlist needed any more; keep this test bare so a future regen that
# reintroduces a dead key fails loudly instead of silently growing a list.


def _coarse_area_ids() -> set[str]:
    """Every area_id string the RR/FRLG client's trainer panel can actually
    receive in play: area_map.json's coarse per-town/dungeon table only
    (mirrored in gen3_frlge_areas.lua). Deliberately excludes
    gen3_frlge_locations.lua's fine per-room table -- that only ever feeds
    `player_area`, which the trainer panel's `player_area_id.get(pid, "")
    or player_area.get(pid, "")` (server.py ~:2843) falls back to before the
    player's first coarse area_enter this session; every reading after that
    is the sticky coarse value (see the module comment above)."""
    return set(json.loads((_GEN3_FRLGE_DIR / "area_map.json")
                           .read_text(encoding="utf-8")).values())


def test_priority_trainers_areas_are_client_emittable():
    """F-7/RR-PT2: every trainers_by_area key in the committed
    rr_priority_trainers.json must be a COARSE area_id (area_map.json) --
    the only kind the trainer panel actually receives in play once the
    player has ever reported one this session (see the module comment
    above) -- otherwise that area's Upcoming Key Trainers widget silently
    never fires. This is the regression guard for the vermillion_city/
    vermilion_city bug (the community sheet spelled the city both ways;
    only "vermilion_city", one L, is the id area_map.json/the client
    emits) and every dead building/room key card RR-PT2 fixed (e.g.
    "rocket_hideout", "pewter_museum", "celadon_city_game_corner" -- a bare
    building/fine-per-room name is never reachable in the trainer panel;
    see tools/gen_rr_priority_trainers.py's _AREA_OVERRIDES for the
    area_of_map()-derived fix). No allowlist: a regen that reintroduces a
    dead key must fail this test, not grow a grandfather list."""
    valid = _coarse_area_ids()
    roster = json.loads((_GEN3_FRLGE_DIR / "rr_priority_trainers.json")
                         .read_text(encoding="utf-8"))
    keys = set(roster["trainers_by_area"])
    bad = sorted(keys - valid)
    assert not bad, (
        f"trainers_by_area key(s) {bad} aren't a coarse area_id the RR/FRLG "
        f"client ever emits in ordinary play (not in area_map.json) -- their "
        f"trainers can never show. Fix the sheet-text -> area_id mapping in "
        f"tools/gen_rr_priority_trainers.py's _AREA_OVERRIDES/"
        f"_normalize_area_name, don't hand-edit the JSON."
    )


def test_area_overrides_values_are_all_coarse_area_ids():
    """RR-PT3 item 3: every _AREA_OVERRIDES VALUE (not just what happens to
    survive into the committed roster -- test_priority_trainers_areas_are_
    client_emittable only catches a bad value once some sheet header
    actually triggers it) must itself be a coarse area_id in area_map.json.
    An override that maps sheet text to a bogus non-coarse id (e.g. the
    former "ss_aqua", "mt_silver", "faraway_island", "chrono_island" --
    none of which are real pret pokefirered maps at all -- or the former
    "rocket_warehouse", a real place but the wrong, fine-only, id) is a
    latent bug: harmless until the community sheet adds or edits a row
    whose header text happens to match that key, at which point it silently
    produces an unreachable trainers_by_area bucket with no test catching it
    until someone notices trainers missing in play."""
    import gen_rr_priority_trainers as grpt
    valid = _coarse_area_ids()
    bad = {k: v for k, v in grpt._AREA_OVERRIDES.items() if v not in valid}
    assert not bad, (
        f"_AREA_OVERRIDES value(s) aren't coarse area_map.json ids: {bad} -- "
        f"map each to the coarse id the client actually reports at that "
        f"place (BFS to the nearest area_map.json-mapped ancestor, same rule "
        f"as every other entry in _AREA_OVERRIDES), or drop the entry with a "
        f"comment if the place doesn't exist in RR's FR-layout map set at all."
    )


def test_priority_trainers_parties_area_matches_trainers_by_area():
    """RR-PT3 item 1: every rt_id listed under trainers_by_area[area] must
    have parties[id]["area"] == area (or, for an id legitimately placed
    under more than one area, area is among a list and the id is under
    every one of those areas) -- previously steps (b)/(c)/(d) of the
    trainers_by_area build (Nuzlocke Redux / Trainer Order / gym-leader
    rematch inheritance) appended the id to trainers_by_area but never wrote
    the derived area back onto the party record itself, so parties[id]
    silently disagreed with (or omitted) the area trainers_by_area actually
    placed it under. Also checks every placed party carries "area_source"
    (tools/gen_rr_priority_trainers.py's _attach) naming which step placed
    it, so a heuristic (non-header) placement is reviewable rather than
    indistinguishable from a sheet-stated one."""
    roster = json.loads((_GEN3_FRLGE_DIR / "rr_priority_trainers.json")
                         .read_text(encoding="utf-8"))
    parties = roster["parties"]
    tba = roster["trainers_by_area"]
    valid_sources = {"sheet_header", "trainer_order", "name_claim", "rematch_inherit"}
    checked = 0
    for area, ids in tba.items():
        for rid in ids:
            info = parties.get(str(rid))
            assert info is not None, f"trainers_by_area[{area!r}] names rt_id {rid}, not in parties"
            party_area = info.get("area")
            assert party_area, f"parties[{rid}] (in trainers_by_area[{area!r}]) has no area at all"
            areas = party_area if isinstance(party_area, list) else [party_area]
            assert area in areas, (
                f"parties[{rid}][\"area\"] = {party_area!r} doesn't include "
                f"{area!r}, the trainers_by_area bucket it's actually listed under"
            )
            source = info.get("area_source")
            assert source in valid_sources, (
                f"parties[{rid}] is placed (area={party_area!r}) but area_source "
                f"is {source!r}, not one of {sorted(valid_sources)}"
            )
            checked += 1
    assert checked > 0, "expected at least one placed trainer to check"


# Key-fight classes the Upcoming Key Trainers widget must be able to show:
# gym leaders (incl. Johto/RR crossover leaders and their post-game
# "*"-prefixed rematch tiers), Elite Four members, the final Champion battle,
# the overworld Rival battles, and Giovanni's boss fights.
_KEY_FIGHT_CLASSES = {
    "Gym Leader", "Leader", "*Leader", "Elite Four", "*Elite Four",
    "Champion", "Rival", "*Rival", "Giovanni", "Boss",
}

# RR-PT3 item 2: named key fights with NO reachable placement anywhere in
# trainers_by_area, and why -- checked per NAME (not the old per-FAMILY
# floor, which let a name with zero reachable ids hide behind a sibling name
# in the same class family). Every name below is EVERY rt_id under that name
# in a key-fight class having source "calc:..." (a calc/normal.js SETDEX
# entry with no boss-sheet header/Trainer-Order row at all -- see
# tools/gen_rr_priority_trainers.py's _build_roster step 1a/1b comments), so
# there is no sheet location text to map: not a bug, a genuinely separate
# identity from a name that IS placed.
#   "Blue": RR's own sheet labels the final Rival/Champion battle "Rival" in
#     the boss-sheet headers (aliased to rr_trainers.json's "Terry" for id
#     matching, see _NAME_ALIASES) -- placed and reachable under that name.
#     The calc/normal.js SETDEX separately carries "Rival Blue"/"Champion
#     Blue" labels (the vanilla rival's own name) with no sheet counterpart
#     of their own, so those ids never get an area. Same conceptual fight,
#     already reachable under "Terry" -- not a gap in the widget.
_UNPLACED_KEY_FIGHTS = {
    "Blue": "no sheet header/Trainer-Order row for this name -- calc-only "
            "alternate name for the Rival/Champion fight already reachable "
            "under 'Terry'",
}


def test_priority_trainers_key_fights_have_reachable_area_per_name():
    """RR-PT3 item 2: every NAMED key fight (gym leaders incl. rematches,
    rival, Elite Four, champion, Giovanni) must have >=1 reachable rt_id
    under trainers_by_area -- checked per name, not per class family (a
    family-level floor let one reachable name mask every other unreachable
    name sharing its class, e.g. Falkner/Bugsy/etc. all share class
    "Leader"). Any name with zero reachable placements must be explicitly
    listed in _UNPLACED_KEY_FIGHTS with the reason (there is no sheet
    location for it at all) -- a regen that creates a NEW unplaced name, or
    silently fixes a documented one, fails this test rather than passing
    quietly either way."""
    roster = json.loads((_GEN3_FRLGE_DIR / "rr_priority_trainers.json")
                         .read_text(encoding="utf-8"))
    parties = roster["parties"]
    placed = {rid for ids in roster["trainers_by_area"].values() for rid in ids}
    names_all: set[str] = set()
    names_reachable: set[str] = set()
    for rid_str, p in parties.items():
        if p.get("class") not in _KEY_FIGHT_CLASSES:
            continue
        name = p["name"]
        names_all.add(name)
        if int(rid_str) in placed:
            names_reachable.add(name)
    unplaced = names_all - names_reachable
    assert unplaced == set(_UNPLACED_KEY_FIGHTS), (
        f"unplaced key-fight name(s) changed: now {sorted(unplaced)}, "
        f"documented {sorted(_UNPLACED_KEY_FIGHTS)}. A NEW unplaced name "
        f"needs a sheet-location trace (map it via _AREA_OVERRIDES/"
        f"area_of_map if the sheet gives a real Kanto/Sevii place, or add it "
        f"here with the sheet's own text if it gives none); a name that's "
        f"newly placed should be removed from _UNPLACED_KEY_FIGHTS above."
    )


def test_priority_trainers_gym_leader_rematches_inherit_base_area():
    """RR-PT2: a Gym Leader's post-E4 rematch tier (Kanto Rematch/Postgame
    sheets -- the Trainer Order sheet is a single first-playthrough pass and
    never lists these) fights at the SAME gym as the base leader, so it must
    show up in the same trainers_by_area bucket rather than being stranded
    with no area.

    RR-PT3: resolved by NAME from the roster, not hard-coded rt_ids -- a
    regen can renumber ids (rr_trainers.json candidate picking is
    party-size-scored, not identity-stable), so pinning bare integers here
    just breaks on the next unrelated regen. Uses the "area_source" field
    card RR-PT3 added (tools/gen_rr_priority_trainers.py's _attach): a
    leader's "base" id(s) are whichever the sheet/Trainer Order placed
    directly (area_source != "rematch_inherit"); every same-name id tagged
    "rematch_inherit" must land in that same area. Still pins the specific
    leaders the 2026-09-26 regen dropped and RR-PT2 restored (see
    docs/gen3/research/rr_priority_regen_2026-09-26.md): Brock, Misty (two
    rematch tiers), Lt. Surge, Erika, and the Johto crossover leader Clair."""
    roster = json.loads((_GEN3_FRLGE_DIR / "rr_priority_trainers.json")
                         .read_text(encoding="utf-8"))
    parties = roster["parties"]
    tba = roster["trainers_by_area"]

    leaders_by_name: dict[str, dict[int, dict]] = defaultdict(dict)
    for rid_str, info in parties.items():
        if info.get("class") == "Gym Leader":
            leaders_by_name[info["name"]][int(rid_str)] = info

    for name in ("Brock", "Misty", "Lt. Surge", "Erika", "Clair"):
        entries = leaders_by_name.get(name)
        assert entries, f"no Gym Leader roster entries for {name!r}"
        rematches = {rid: info for rid, info in entries.items()
                     if info.get("area_source") == "rematch_inherit"}
        bases = {rid: info for rid, info in entries.items() if rid not in rematches}
        assert rematches, f"{name}: expected at least one rematch-inherited id"
        assert bases, f"{name}: expected at least one base (non-rematch) id"
        base_areas = {info.get("area") for info in bases.values()}
        assert all(base_areas), f"{name}: a base id has no area"
        assert len(base_areas) == 1, f"{name}: base fight(s) span multiple areas: {base_areas}"
        area = next(iter(base_areas))
        for rid in bases:
            assert rid in tba.get(area, []), f"{name} base id {rid} missing from {area}"
        for rid, info in rematches.items():
            assert info.get("area") == area, (
                f"{name} rematch id {rid} area {info.get('area')!r} != base area {area!r}"
            )
            assert rid in tba.get(area, []), (
                f"{name} rematch id {rid} not placed alongside its base fight at {area}"
            )
