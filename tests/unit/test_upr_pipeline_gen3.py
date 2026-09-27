"""R3: the Manager randomizer for FireRed / LeafGreen (docs/gen3/research/randomized_gen3_design.md
§4, §6 R3; owner ruling 31, docs/gen3/G4_request_draft.md §6).

The envelope (settings only) runs everywhere. The ROM rows skip by name when the pinned clean
dumps are absent (a present-but-wrong dump fails); the jar row also needs Java and the pinned
SLink fork jar. The widest-envelope output is the design's scratch artifact, supplied by
SLINK_R3_WIDEST_ROM, and skips by name without it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import aiohttp
import pytest

from server import cartridges, upr_pipeline, upr_settings as U
from server.adapters.gen3_rom_tables import DEOXYS
from server.upr_pipeline import UprPipelineError
from tools.gen3_final_cut import ROOT_DUMPS, STAGED, rom_pins

pytest_plugins = ["tests.unit.manager_harness"]
ROOT = Path(__file__).resolve().parents[2]
FRLG = U.FAMILY_FRLG


def _widest() -> bytes:
    """The design's widest file: types, evolutions, movesets, base stats and abilities random,
    plus all 13 tweaks SLink modelled for Gen 1 (the type chart among them)."""
    flags = {"types_UNCHANGED": False, "types_RANDOM_FOLLOW_EVOLUTIONS": True,
             "evolutions_UNCHANGED": False, "evolutions_RANDOM": True,
             "movesets_UNCHANGED": False, "movesets_COMPLETELY_RANDOM": True,
             "baseStats_UNCHANGED": False, "baseStats_RANDOM": True,
             "abilities_UNCHANGED": False, "abilities_RANDOMIZE": True}
    misc = 0
    for name in ("BW_EXP_PATCH", "NERF_X_ACCURACY", "FIX_CRIT_RATE", "FASTEST_TEXT",
                 "RUNNING_SHOES_INDOORS", "RANDOMIZE_PC_POTION", "ALLOW_PIKACHU_EVOLUTION",
                 "NATIONAL_DEX_AT_START", "UPDATE_TYPE_EFFECTIVENESS", "FORCE_CHALLENGE_MODE",
                 "LOWER_CASE_POKEMON_NAMES", "RANDOMIZE_CATCHING_TUTORIAL", "BAN_LUCKY_EGG"):
        misc |= U.MISC_TWEAKS[name]
    return U.build(flags, misc, rom_name="Fire Red (U)")


def _wide_allowed_spec() -> dict:
    """Every FR/LG option switched on (the Gen 3-only ones and all nine tweaks included)."""
    spec = {}
    for key, opt in U.options_for(FRLG).items():
        if opt["kind"] == "bool":
            spec[key] = True
        elif opt["kind"] == "choice":
            spec[key] = list(opt["choices"])[1]
    # the two combinations admission refuses as unverifiable, for every family
    spec.update(trainers_similar_strength=False, trainers="random", wild_restriction="none")
    return spec


# ── the envelope (ruling 31) ────────────────────────────────────────────────────────────
def test_widest_file_is_refused_by_name():
    with pytest.raises(UprPipelineError) as exc:
        upr_pipeline.admit_settings(_widest(), FRLG)
    msg = str(exc.value)
    for name in ("types", "evolutions", "movesets", "base_stats", "abilities",
                 "UPDATE_TYPE_EFFECTIVENESS", "NERF_X_ACCURACY", "FIX_CRIT_RATE", "BW_EXP_PATCH"):
        assert name in msg, (name, msg)


def test_gen3_only_options_are_open_for_frlg_and_closed_for_gen1():
    blob = U.build_spec(_wide_allowed_spec(), family=FRLG)
    parsed = upr_pipeline.admit_settings(blob, FRLG)
    assert U.spec_from_parsed(parsed, FRLG) == {**U.default_spec(FRLG), **_wide_allowed_spec()}
    # the same file is outside the Gen 1 envelope: tutors, trades, shops, pickup, held items
    odd = U.unexpected_settings(U.load(blob), U.FAMILY_VANILLA)
    for byte in (16, 21, 23, 37, 48, 49):
        assert any(o.startswith(f"byte {byte}") for o in odd), (byte, odd)


@pytest.mark.parametrize("key", ["nerf_x_accuracy", "fix_crit_rate", "update_type_effectiveness"])
def test_gen1_only_tweaks_are_not_frlg_options(key):
    with pytest.raises(U.UprSettingsError):
        U.build_spec({key: True}, family=FRLG)
    assert key not in U.default_spec(FRLG)


def test_frlg_rnqs_round_trips():
    spec = {**U.default_spec(FRLG), "tutors": "random", "shops": "shuffle", "national_dex": True}
    back = U.spec_from_parsed(U.load(U.build_spec(spec, family=FRLG)), FRLG)
    assert back == spec
    assert U.load(U.build_spec(spec, family=FRLG))["rom_name"] == "Fire Red (U)"


# ── ROM checks: sites, anchors, rule tables ─────────────────────────────────────────────
def _clean_path(title: str) -> Path:
    candidates = [base / rel for base in (ROOT, *ROOT.parents) for rel in (STAGED[title], ROOT_DUMPS[title])]
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        pytest.skip(f"pinned clean {title} ROM absent (looked for {STAGED[title]} / {ROOT_DUMPS[title]})")
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    assert digest == rom_pins(str(ROOT))[title], f"{path} present but wrong {title} SHA-1 {digest}"
    return path


def _variant(tmp_path, title, edit) -> tuple[str, str]:
    src = _clean_path(title)
    rom = bytearray(src.read_bytes())
    edit(rom)
    out = tmp_path / f"{title}_edited.gba"
    out.write_bytes(bytes(rom))
    return str(src), str(out)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_clean_rom_passes_its_own_check(tmp_path, title):
    src = str(_clean_path(title))
    assert upr_pipeline.gen3_site_mismatches(Path(src).read_bytes(), title) == []
    assert upr_pipeline.describe_rom(src, True)["family"] == FRLG
    tables = upr_pipeline._check_content_gen3(src, src)
    assert upr_pipeline.gen3_content_fingerprint(tables) == upr_pipeline.gen3_fingerprint_rom(Path(src).read_bytes())


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_a_changed_engine_site_is_refused(tmp_path, title):
    site = json.loads((ROOT / "data/games/gen3_frlg/engine_signals.json").read_text())[
        "titles"][title]["artifacts"]["clean"]["sites"]["faint"]
    src, out = _variant(tmp_path, title, lambda r: r.__setitem__(site["rom_offset"], r[site["rom_offset"]] ^ 0xFF))
    with pytest.raises(UprPipelineError, match="faint site"):
        upr_pipeline._check_content_gen3(src, out)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_a_changed_checkpoint_anchor_is_refused(tmp_path, title):
    anchor = json.loads((ROOT / "data/games/gen3_frlg/write_checkpoint.json").read_text())[
        title]["anchors"]["try_saving_data"]
    off = anchor["rom_offset"] + anchor["length"] - 1
    src, out = _variant(tmp_path, title, lambda r: r.__setitem__(off, r[off] ^ 0xFF))
    with pytest.raises(UprPipelineError, match="checkpoint anchor try_saving_data"):
        upr_pipeline._check_content_gen3(src, out)


def _species_row(title: str, species: int) -> int:
    sym = (ROOT / f"data/gen3/pret/poke{title}.sym").read_text().splitlines()
    base = int(next(line for line in sym if line.endswith(" gSpeciesInfo")).split()[0], 16) - 0x08000000
    return base + species * 28


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_changed_base_stats_or_abilities_are_refused(tmp_path, title):
    bulbasaur = _species_row(title, 1)
    src, out = _variant(tmp_path, title, lambda r: r.__setitem__(bulbasaur + 1, r[bulbasaur + 1] + 1))
    with pytest.raises(UprPipelineError, match="base stats"):
        upr_pipeline._check_content_gen3(src, out)
    src, out = _variant(tmp_path, title, lambda r: r.__setitem__(bulbasaur + 22, r[bulbasaur + 22] + 1))
    with pytest.raises(UprPipelineError, match="abilities"):
        upr_pipeline._check_content_gen3(src, out)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_upr_normalizations_are_not_refusals(tmp_path, title):
    """UPR fills an empty second ability with the first, and writes the title's hardcoded
    Deoxys forme stats into its row, on EVERY save (Gen3RomHandler.java:1322-1324, 796-809).
    The clean dump itself stores Deoxys's NORMAL stats (proven below), so this is the actual
    src -> out delta a real UPR save produces, not an arbitrary edit."""
    from server.adapters.gen3_frlge import _DEOXYS_FORME, _DEOXYS_NORMAL
    bulbasaur, deoxys = _species_row(title, 1), _species_row(title, DEOXYS)

    def edit(r):
        assert r[bulbasaur + 23] == 0
        r[bulbasaur + 23] = r[bulbasaur + 22]
        assert bytes(r[deoxys:deoxys + 6]) == _DEOXYS_NORMAL, "clean dump stores the NORMAL stats"
        r[deoxys:deoxys + 6] = _DEOXYS_FORME[title]
    src, out = _variant(tmp_path, title, edit)
    upr_pipeline._check_content_gen3(src, out)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_changed_deoxys_stats_that_are_not_the_forme_are_refused(tmp_path, title):
    """The Deoxys exemption in _gen3_species_rules only tolerates UPR's own hardcoded-forme
    normalisation (Gen3RomHandler.java:796-809); a real edit to that row -- one that does not
    land on the forme bytes -- must still be caught, or a base-stat randomizer on Deoxys would
    pass silently (the bug fixed here: the old code zeroed the row unconditionally)."""
    deoxys = _species_row(title, DEOXYS)
    src, out = _variant(tmp_path, title, lambda r: r.__setitem__(deoxys, r[deoxys] ^ 0xFF))
    with pytest.raises(UprPipelineError, match="base stats"):
        upr_pipeline._check_content_gen3(src, out)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_row_409_is_not_treated_as_deoxys(tmp_path, title):
    """Pins the species-row index convention: DEOXYS = 410 is the exact row the exemption
    applies to; its neighbour (409) must be refused like any other species."""
    assert DEOXYS == 410
    row = _species_row(title, DEOXYS - 1)
    src, out = _variant(tmp_path, title, lambda r: r.__setitem__(row, r[row] ^ 0xFF))
    with pytest.raises(UprPipelineError, match="base stats"):
        upr_pipeline._check_content_gen3(src, out)


def test_changed_evolutions_are_refused(tmp_path):
    from server.adapters.gen3_rom_tables import table_symbols
    head = table_symbols("firered")["gEvolutionTable"]["address"] - 0x08000000
    bulbasaur_target = head + 1 * 40 + 4          # species 1, slot 0, targetSpecies
    src, out = _variant(tmp_path, "firered", lambda r: r.__setitem__(bulbasaur_target, 7))
    with pytest.raises(UprPipelineError, match="evolution targets"):
        upr_pipeline._check_content_gen3(src, out)


# ── malformed data/games/gen3_frlg packs refuse by name, not KeyError/StopIteration ────────
def _deep_copy(obj):
    return json.loads(json.dumps(obj))


def test_a_site_missing_expected_hex_refuses_by_name(monkeypatch):
    real = upr_pipeline._gen3_pack

    def fake(name):
        data = _deep_copy(real(name))
        if name == "engine_signals.json":
            site = next(iter(data["titles"]["firered"]["artifacts"]["clean"]["sites"].values()))
            del site["expected_hex"]
        return data
    monkeypatch.setattr(upr_pipeline, "_gen3_pack", fake)
    with pytest.raises(UprPipelineError, match="expected_hex"):
        upr_pipeline.gen3_site_mismatches(bytes(64), "firered")


def test_a_site_with_an_empty_expected_hex_refuses_by_name(monkeypatch):
    """OMP cx-6cb07509 F3: `expected_hex: ""` decoded to b"" and compared equal to an empty
    slice, so the site counted as verified -- fail-open inside the strict loop."""
    real = upr_pipeline._gen3_pack

    def fake(name):
        data = _deep_copy(real(name))
        if name == "engine_signals.json":
            site = next(iter(data["titles"]["firered"]["artifacts"]["clean"]["sites"].values()))
            site["expected_hex"] = ""
        return data
    monkeypatch.setattr(upr_pipeline, "_gen3_pack", fake)
    with pytest.raises(UprPipelineError, match="expected_hex"):
        upr_pipeline.gen3_site_mismatches(bytes(64), "firered")


def test_a_context_missing_expected_hex_refuses_by_name(monkeypatch):
    real = upr_pipeline._gen3_pack

    def fake(name):
        data = _deep_copy(real(name))
        if name == "engine_signals.json":
            site = next(iter(data["titles"]["firered"]["artifacts"]["clean"]["sites"].values()))
            del site["context"]["expected_hex"]
        return data
    monkeypatch.setattr(upr_pipeline, "_gen3_pack", fake)
    with pytest.raises(UprPipelineError, match="expected_hex"):
        upr_pipeline.gen3_site_mismatches(bytes(64), "firered")


def test_an_anchor_missing_expected_hex_clean_refuses_by_name(monkeypatch):
    real = upr_pipeline._gen3_pack

    def fake(name):
        data = _deep_copy(real(name))
        if name == "write_checkpoint.json":
            anchor = next(iter(data["firered"]["anchors"].values()))
            del anchor["expected_hex"]["clean"]
        return data
    monkeypatch.setattr(upr_pipeline, "_gen3_pack", fake)
    with pytest.raises(UprPipelineError, match="expected_hex"):
        upr_pipeline.gen3_site_mismatches(bytes(64), "firered")


def test_missing_gspeciesinfo_symbol_refuses_by_name(tmp_path, monkeypatch):
    from server.adapters import gen3_rom_tables
    real_symbol_dir = gen3_rom_tables.SYMBOL_DIR
    src = real_symbol_dir / "pokefirered.sym"
    stripped = "\n".join(line for line in src.read_text(encoding="utf-8").splitlines()
                         if not line.endswith(" gSpeciesInfo"))
    (tmp_path / "pokefirered.sym").write_text(stripped, encoding="utf-8")
    monkeypatch.setattr(gen3_rom_tables, "SYMBOL_DIR", tmp_path)
    with pytest.raises(UprPipelineError, match="gSpeciesInfo"):
        upr_pipeline._gen3_species_rules(bytes(4), "firered")


def test_the_design_widest_output_is_refused():
    """The scratch widest-envelope FR output (design §0) is refused before any contract."""
    path = os.environ.get("SLINK_R3_WIDEST_ROM", "")
    if not path or not os.path.isfile(path):
        pytest.skip("SLINK_R3_WIDEST_ROM (the design's FireRed_widest.gba) absent")
    src = str(_clean_path("firered"))
    with pytest.raises(UprPipelineError, match="base stats, types"):
        upr_pipeline._check_content_gen3(src, path)


# ── prepare_pair / provision (the first falsifier and the exit) ─────────────────────────
def test_prepare_pair_on_clean_frlg_with_widest_is_refused_by_name(tmp_path):
    fr, lg = str(_clean_path("firered")), str(_clean_path("leafgreen"))
    settings = tmp_path / "widest.rnqs"
    settings.write_bytes(_widest())
    with pytest.raises(UprPipelineError, match="abilities.*type chart.*types, evolutions, movesets, base_stats"):
        upr_pipeline.prepare_pair("unused.jar", str(settings), {"a": fr, "b": lg}, str(tmp_path / "out"))
    assert not (tmp_path / "out").exists(), "refused before Java or any output"


def test_prepare_pair_refuses_a_stock_jar_for_frlg(tmp_path, monkeypatch):
    """FAMILY_FRLG needs the SLink fork jar the same way FAMILY_PURE does: a trusted-but-not-
    fork jar (e.g. the stock 4.6.1 release, if its hash were ever added to upr_jars.json) must
    be refused by name rather than silently randomizing FR/LG on an unreviewed handler."""
    fr, lg = str(_clean_path("firered")), str(_clean_path("leafgreen"))
    jar = tmp_path / "stock.jar"
    jar.write_bytes(b"not a real jar")
    monkeypatch.setattr(shutil, "which", lambda prog: "/usr/bin/" + prog)
    monkeypatch.setattr(upr_pipeline, "jar_is_trusted", lambda j: True)
    monkeypatch.setattr(upr_pipeline, "jar_is_fork", lambda j: False)
    settings = tmp_path / "default.rnqs"
    settings.write_bytes(U.build_spec(U.default_spec(FRLG), family=FRLG))
    with pytest.raises(UprPipelineError, match="fork jar"):
        upr_pipeline.prepare_pair(str(jar), str(settings), {"a": fr, "b": lg}, str(tmp_path / "out"))
    assert not (tmp_path / "out" / "a_randomized.gba").exists()


def test_provision_refuses_a_stock_jar_for_frlg(tmp_path, monkeypatch):
    fr, lg = str(_clean_path("firered")), str(_clean_path("leafgreen"))
    jar = tmp_path / "stock.jar"
    jar.write_bytes(b"not a real jar")
    monkeypatch.setattr(upr_pipeline, "jar_is_trusted", lambda j: True)
    monkeypatch.setattr(upr_pipeline, "jar_is_fork", lambda j: False)
    settings = tmp_path / "default.rnqs"
    settings.write_bytes(U.build_spec(U.default_spec(FRLG), family=FRLG))
    with pytest.raises(cartridges.CartridgeError, match="fork jar"):
        cartridges.provision(str(tmp_path), {"a": fr, "b": lg}, companion=False,
                             randomize={"settings_path": str(settings)}, jar=str(jar))


def test_published_companions_provision_for_frlg(tmp_path):
    fr, lg = str(_clean_path("firered")), str(_clean_path("leafgreen"))
    result=cartridges.provision(str(tmp_path), {"a": fr, "b": lg}, companion=True, randomize=None)
    assert all(row["kind"]=="companion" for row in result["players"].values())


def _jar() -> str:
    jar = upr_pipeline.find_upr_jar()
    if not jar or not upr_pipeline.jar_is_trusted(jar):
        pytest.skip("pinned SLink UPR fork jar absent (tools/build_upr_fork.py --pin)")
    if not shutil.which("java"):
        pytest.skip("java not on PATH")
    return jar


@pytest.mark.parametrize("spec", ["default", "wide"])
def test_default_spec_provisions_a_contracted_frlg_pair(tmp_path, spec):
    fr, lg = str(_clean_path("firered")), str(_clean_path("leafgreen"))
    jar = _jar()
    settings = tmp_path / "settings.rnqs"
    settings.write_bytes(U.build_spec(U.default_spec(FRLG) if spec == "default" else _wide_allowed_spec(),
                                      family=FRLG))
    result = cartridges.provision(str(tmp_path), {"a": fr, "b": lg}, companion=False,
                                  randomize={"settings_path": str(settings)}, jar=jar)
    contract = json.loads((tmp_path / "rom_contract.json").read_text())
    assert contract["upr_version"] == "4.6.1-slink3"
    assert contract["settings_sha256"] == hashlib.sha256(settings.read_bytes()).hexdigest()
    assert set(contract["categories"]) >= {"wild", "starters", "trainers"}
    assert contract["players"]["a"]["seed"] != contract["players"]["b"]["seed"]
    for pid, title in (("a", "firered"), ("b", "leafgreen")):
        rom = (tmp_path / "roms" / f"{pid}.gba").read_bytes()
        row = contract["players"][pid]
        assert row["rom_sha1"] == hashlib.sha1(rom).hexdigest() == result["players"][pid]["rom_sha1"]
        assert row["fingerprint"] == upr_pipeline.gen3_fingerprint_rom(rom)
        assert upr_pipeline.gen3_site_mismatches(rom, title) == [], "sites and anchors intact"
        assert result["randomizer"]["players"][pid]["sites_intact"] is True
        assert result["players"][pid]["kind"] == "rand"
    assert contract["players"]["a"]["fingerprint"] != contract["players"]["b"]["fingerprint"]


# ── the Manager: family, .rnqs import/export ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_manager_rnqs_export_import_round_trip_for_frlg(manager_client):
    spec = {**U.default_spec(U.FAMILY_VANILLA), "tutors": "random", "pickup": "random",
            "ban_lucky_egg": True, "nerf_x_accuracy": False}
    resp = await manager_client.post("/api/randomizer/settings/export",
                                     json={"spec": spec, "name": "frlg", "family": FRLG})
    assert resp.status == 200
    blob = await resp.read()

    async def imp(data, family):
        form = aiohttp.FormData()
        form.add_field("file", data, filename="x.rnqs", content_type="application/octet-stream")
        form.add_field("family", family)
        return await (await manager_client.post("/api/randomizer/settings/import", data=form)).json()

    back = await imp(blob, FRLG)
    assert back["ok"] and back["spec"]["tutors"] == "random" and back["spec"]["ban_lucky_egg"] is True
    assert (await imp(blob, U.FAMILY_VANILLA))["ok"] is False, "a Gen 1 run refuses the FR/LG options"
    widest = await imp(_widest(), FRLG)
    assert widest["ok"] is False and "abilities" in widest["error"]
    # a Gen 1-only tweak switched on is refused for FR/LG, never coerced
    bad = await manager_client.post("/api/randomizer/settings/export",
                                    json={"spec": {"nerf_x_accuracy": True}, "family": FRLG})
    assert bad.status == 400


def test_manager_names_the_frlg_family():
    from server import manager
    assert manager.GAME_FAMILY["gen3"] == FRLG
    assert "gen3" in manager.new_run_form()["randomizer_games"]
    assert ".gba" in manager.ROM_EXTS
    rows = {r["key"]: r for r in U.option_form(every_family=True)}
    assert rows["tutors"]["families"] == [FRLG, U.FAMILY_EMERALD]
    assert FRLG not in rows["update_type_effectiveness"]["families"]
    assert FRLG in rows["wild"]["families"]


def test_radical_red_run_is_not_offered_the_randomizer():
    """"gen3_rr" (Radical Red) is a DIFFERENT game key from "gen3": RR's map/data no longer
    matches the vanilla FR/LG tables R2 verifies against, so an RR run must never be able to
    pick the FR/LG randomizer family. If a future edit ever added "gen3_rr" to GAME_FAMILY,
    this is the test that catches it."""
    from server import manager
    assert "gen3_rr" not in manager.GAME_FAMILY
    assert "gen3_rr" not in manager.new_run_form()["randomizer_games"]


def test_build_categories_carries_the_frlg_rom_name():
    """The legacy /api/randomizer/settings/categories path (manager.py) builds an FR/LG run's
    file with build_categories; without a family it always named the file "Pokemon Red (U)
    [!]", even for a FireRed / LeafGreen run."""
    parsed = U.load(U.build_categories({"wild"}, family=FRLG))
    assert parsed["rom_name"] == U.ROM_NAME[FRLG] == "Fire Red (U)"
    # the Gen 1 default is unchanged
    assert U.load(U.build_categories({"wild"}))["rom_name"] == "Pokemon Red (U) [!]"


@pytest.mark.asyncio
async def test_manager_randomizes_a_frlg_pair_end_to_end(manager_client, manager_dir):
    """The Manager path a player takes: a FireRed / LeafGreen run, its Cartridges step with the
    form's spec (every row, as the page sends it), a contract, the .gba downloads."""
    from server import manager
    fr, lg = str(_clean_path("firered")), str(_clean_path("leafgreen"))
    jar = _jar()
    run = {"run_id": "run_g3", "name": "Kanto FRLG", "created_at": "2026-09-26T12:00:00", "tcp_port": 54321,
           "http_port": 8081, "status": "stopped", "pid": None, "game": "gen3"}
    manager._save_registry([run])
    (manager_dir / "run_g3").mkdir()
    page = await (await manager_client.get("/runs/run_g3/cartridges")).text()
    assert '"family": "gen3_frlg"' in page
    form_spec = {r["key"]: r["default"] for r in U.option_form(every_family=True)}
    j = await (await manager_client.post("/api/runs/run_g3/cartridges", json={
        "rom_a": fr, "rom_b": lg, "randomize": True, "jar": jar, "spec": form_spec})).json()
    assert j["ok"], j
    contract = json.loads((manager_dir / "run_g3" / "rom_contract.json").read_text())
    assert set(contract["players"]) == {"a", "b"}
    assert j["randomizer"]["players"]["a"]["rom_sha1"] == contract["players"]["a"]["rom_sha1"]
    dl = await manager_client.get("/api/runs/run_g3/rom/a")
    assert dl.status == 200 and dl.headers["Content-Disposition"].endswith('_a.gba"')
    # a Gen 1 pair on a FireRed / LeafGreen run is refused where it can be fixed
    gb = manager_dir / "red.gb"
    gb.write_bytes(bytes(1 << 20))
    wrong = await manager_client.post("/api/runs/run_g3/cartridges", json={
        "rom_a": fr, "rom_b": str(gb), "randomize": True, "jar": jar, "spec": form_spec})
    assert wrong.status == 400
