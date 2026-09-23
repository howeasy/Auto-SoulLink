"""Cartridge ordering and contracts, checked against the pinned ROM artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from patch.gen1.tools import inject
from server import upr_pipeline
from server.adapters.gen1_rom_scan import fingerprint_rom

REPO = Path(__file__).resolve().parents[2]


def _vanilla():
    sources = {p: str(REPO / "patch" / "build" / f"gen1_{title}.gb")
               for p, title in (("a", "red"), ("b", "blue"))}
    for path in sources.values():
        if not Path(path).is_file():
            pytest.skip(f"clean dump absent: {path}")
    return sources


def _fake_pair(monkeypatch, check=None):
    def prepare(jar, settings_path, sources, out_dir):
        if check:
            check(sources)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        players = {}
        for seed, (pid, source) in enumerate(sources.items(), 1):
            data = Path(source).read_bytes()
            output = Path(out_dir) / f"{pid}_randomized.gbc"
            output.write_bytes(data)
            players[pid] = {"output": str(output), "seed": seed,
                            "sha1": hashlib.sha1(data).hexdigest(),
                            "fingerprint": fingerprint_rom(data)}
        return {"upr_version": "4.6.1-slink1", "settings_sha256": "abc",
                "categories": ["wild"], "players": players}
    monkeypatch.setattr(upr_pipeline, "prepare_pair", prepare)


def test_vanilla_injects_after_randomizing_and_contract_pins_final(tmp_path, monkeypatch):
    # First falsifier: a contract for the intermediate rejects the handed-out companion.
    from server.cartridges import provision

    sources = _vanilla()
    def clean_inputs(actual):
        assert actual == sources
        assert all(inject.describe(Path(p).read_bytes())["already"] is None
                   for p in actual.values())
    _fake_pair(monkeypatch, clean_inputs)
    result = provision(str(tmp_path), sources, companion=True,
                       randomize={"settings_path": "settings.rnqs"}, jar="fake.jar")
    contract = json.loads((tmp_path / "rom_contract.json").read_text())
    for pid, player in result["players"].items():
        final = Path(player["output"]).read_bytes()
        intermediate = (tmp_path / "roms" / f"{pid}_randomized.gbc").read_bytes()
        assert inject.describe(final)["already"]["abi"] is not None
        assert inject.describe(final)["already"]["identical"]
        assert final != intermediate
        assert contract["players"][pid]["rom_sha1"] == hashlib.sha1(final).hexdigest()
        assert contract["players"][pid]["rom_sha1"] != hashlib.sha1(intermediate).hexdigest()
        assert player["fingerprint"] == fingerprint_rom(final) == fingerprint_rom(intermediate)
        assert contract["players"][pid]["fingerprint"] == player["fingerprint"]
        assert player["kind"] == "rand_companion"
        assert Path(player["output"]) == tmp_path / "roms" / f"{pid}.gb"   # a Red/Blue dump is .gb
        assert "output" not in result["randomizer"]["players"][pid]


def _pure(title="red"):
    path = REPO / ".cache" / "purergb" / f"poke{title}.gbc"
    if not path.is_file():
        pytest.skip(f"pinned pureRGB build absent: {path}")
    return str(path)


@pytest.mark.parametrize("companion", [False, True])
@pytest.mark.parametrize("randomize", [False, True])
def test_vanilla_modes(tmp_path, monkeypatch, companion, randomize):
    from patch.tools.make_ups import ups_apply
    from server import cartridges, patcher

    sources = _vanilla()
    _fake_pair(monkeypatch)
    result = cartridges.provision(str(tmp_path), sources, companion=companion,
                                  randomize={"settings_path": "s.rnqs"} if randomize else None,
                                  jar="fake.jar")
    assert result["family"] == cartridges.FAMILY_VANILLA
    assert result["companion"] is companion
    assert (result["randomizer"] is not None) is randomize
    assert (tmp_path / "rom_contract.json").exists() is randomize
    for pid, title in (("a", "red"), ("b", "blue")):
        player = result["players"][pid]
        original = Path(sources[pid]).read_bytes()
        final = Path(player["output"]).read_bytes()
        expected = original
        if companion:
            expected = (inject.inject(original) if randomize else
                        ups_apply(original, Path(patcher.patch_path(f"rb-{title}")).read_bytes()))
        assert final == expected
        assert player["source"] == sources[pid]
        assert player["source_title"] == upr_pipeline.describe_rom(sources[pid], True)["title"]
        assert player["rom_sha1"] == hashlib.sha1(final).hexdigest()
        assert player["fingerprint"] == fingerprint_rom(final)
        expected_kind = "companion" if companion else "clean"
        if randomize:
            expected_kind = "rand_companion" if companion else "rand"
        assert player["kind"] == expected_kind


def test_a_cartridge_keeps_its_own_extension(tmp_path):
    """BizHawk picks the system by database hit first and by extension second (PLAN A15),
    and a cartridge the run made is never in the database: named .gb, a pureRGB cartridge
    ran on the DMG core in mono (seen by the owner). The output takes the source's
    extension -- Red/Blue dumps .gb, pureRGB (and Yellow) .gbc."""
    from server import cartridges
    result = cartridges.provision(str(tmp_path / "pure"), {"a": _pure("red"), "b": _pure("blue")},
                                  companion=False, randomize=None)
    assert [Path(p["output"]).name for p in result["players"].values()] == ["a.gbc", "b.gbc"]
    red = REPO / "patch" / "build" / "gen1_red.gb"
    if red.is_file():
        result = cartridges.provision(str(tmp_path / "vanilla"), {"a": str(red), "b": str(red)},
                                      companion=False, randomize=None)
        assert [Path(p["output"]).name for p in result["players"].values()] == ["a.gb", "b.gb"]


@pytest.mark.parametrize("title", ["red", "blue", "green"])
@pytest.mark.parametrize("companion", [False, True])
@pytest.mark.parametrize("randomize", [False, True])
def test_pure_modes_and_overlay_before_randomizer(tmp_path, monkeypatch, title, companion, randomize):
    from server import cartridges
    from server.adapters.gen1_rom_scan import identify
    from tools.gen1_playthrough import _overlay_admission_row

    source = _pure(title)
    want, _entry = _overlay_admission_row(f"pure{title}")
    def check_inputs(sources):
        for path in sources.values():
            data = Path(path).read_bytes()
            assert identify(data)["kind"] == ("overlay" if companion else "clean")
            if companion:
                assert hashlib.sha1(data).hexdigest() == want
    _fake_pair(monkeypatch, check_inputs)
    monkeypatch.setattr(upr_pipeline, "jar_is_fork", lambda jar: True)
    def no_inject(*args):
        pytest.fail("vanilla injector must never receive a pureRGB cartridge")
    monkeypatch.setattr(inject, "inject", no_inject)
    result = cartridges.provision(str(tmp_path), {"a": source, "b": source}, companion=companion,
                                  randomize={"settings_path": "s.rnqs"} if randomize else None,
                                  jar="fork.jar")
    assert result["family"] == cartridges.FAMILY_PURE
    assert (tmp_path / "rom_contract.json").exists() is randomize
    for player in result["players"].values():
        data = Path(player["output"]).read_bytes()
        assert player["rom_sha1"] == hashlib.sha1(data).hexdigest()
        assert player["fingerprint"] == fingerprint_rom(data)
        if companion:
            assert player["rom_sha1"] == want
        else:
            assert data == Path(source).read_bytes()
    if randomize:
        contract = json.loads((tmp_path / "rom_contract.json").read_text())
        for pid, player in result["players"].items():
            assert contract["players"][pid]["rom_sha1"] == player["rom_sha1"]


@pytest.mark.parametrize("companion", [False, True])
@pytest.mark.parametrize("randomize", [False, True])
def test_picked_overlay_is_reused_without_repatching(tmp_path, monkeypatch, companion, randomize):
    from server import cartridges

    source = _pure()
    built = cartridges.provision(str(tmp_path / "first"), {"a": source, "b": source},
                                 companion=True, randomize=None)
    sources = {pid: row["output"] for pid, row in built["players"].items()}
    def no_patch(*args):
        pytest.fail("a pinned overlay must not be patched again")
    monkeypatch.setattr(cartridges, "ups_apply", no_patch)
    monkeypatch.setattr(upr_pipeline, "jar_is_fork", lambda jar: True)
    _fake_pair(monkeypatch)
    result = cartridges.provision(str(tmp_path / "second"), sources, companion=companion,
                                  randomize={"settings_path": "s.rnqs"} if randomize else None,
                                  jar="fork.jar")
    assert result["companion"] is companion
    for pid, row in result["players"].items():
        assert Path(row["output"]).read_bytes() == Path(sources[pid]).read_bytes()
        assert row["kind"] == ("rand_companion" if randomize else "companion")


def test_refuses_unpinned_source_before_spending(tmp_path, monkeypatch):
    from server.cartridges import CartridgeError, provision

    sources = _vanilla()
    altered = tmp_path / "modified.gb"
    altered.write_bytes(inject.inject(Path(sources["b"]).read_bytes()))
    sources["b"] = str(altered)
    monkeypatch.setattr(upr_pipeline, "prepare_pair", lambda *args: pytest.fail("spent on refused pair"))
    with pytest.raises(CartridgeError, match="pinned"):
        provision(str(tmp_path / "run"), sources, companion=True,
                  randomize={"settings_path": "s.rnqs"}, jar="fake.jar")
    assert not (tmp_path / "run").exists()


def test_refuses_mixed_families_before_spending(tmp_path, monkeypatch):
    from server.cartridges import CartridgeError, provision

    sources = _vanilla()
    sources["b"] = _pure()
    monkeypatch.setattr(upr_pipeline, "prepare_pair", lambda *args: pytest.fail("spent on mixed pair"))
    with pytest.raises(CartridgeError, match="different families"):
        provision(str(tmp_path / "run"), sources, companion=True,
                  randomize={"settings_path": "s.rnqs"}, jar="fake.jar")
    assert not (tmp_path / "run").exists()


def test_yellow_companion_refuses_before_spending(tmp_path, monkeypatch):
    from server.cartridges import CartridgeError, provision

    yellow = REPO / "Pokemon - Yellow Version (USA, Europe).gbc"
    if not yellow.is_file():
        pytest.skip("clean Yellow dump absent")
    sources = _vanilla()
    sources["b"] = str(yellow)
    monkeypatch.setattr(upr_pipeline, "prepare_pair", lambda *args: pytest.fail("spent on Yellow"))
    with pytest.raises(CartridgeError, match="Yellow has zero free WRAM"):
        provision(str(tmp_path / "run"), sources, companion=True,
                  randomize={"settings_path": "s.rnqs"}, jar="fake.jar")
    result = provision(str(tmp_path / "run"), sources, companion=False, randomize=None)
    assert Path(result["players"]["b"]["output"]).read_bytes() == yellow.read_bytes()


def test_pure_stock_jar_refuses_before_patching_or_randomizing(tmp_path, monkeypatch):
    from server import cartridges

    source = _pure()
    monkeypatch.setattr(upr_pipeline, "jar_is_fork", lambda jar: False)
    monkeypatch.setattr(upr_pipeline, "prepare_pair", lambda *args: pytest.fail("spent on stock jar"))
    monkeypatch.setattr(cartridges, "ups_apply", lambda *args: pytest.fail("patched before jar check"))
    with pytest.raises(cartridges.CartridgeError) as exc:
        cartridges.provision(str(tmp_path / "run"), {"a": source, "b": source}, companion=True,
                             randomize={"settings_path": "s.rnqs"}, jar="stock.jar")
    assert str(exc.value) == upr_pipeline.PUREGB_RANDOMIZER_REFUSAL
    assert not (tmp_path / "run").exists()


def test_pipeline_refusal_preserves_existing_outputs_and_contract(tmp_path, monkeypatch):
    from server.cartridges import CartridgeError, provision

    sources = _vanilla()
    (tmp_path / "roms").mkdir()
    for name in ("a.gb", "b.gb"):
        (tmp_path / "roms" / name).write_bytes(b"old cartridge")
    (tmp_path / "rom_contract.json").write_text("old contract")
    def refuse(*args):
        raise upr_pipeline.UprPipelineError("a real pipeline refusal")
    monkeypatch.setattr(upr_pipeline, "prepare_pair", refuse)
    with pytest.raises(CartridgeError, match="^a real pipeline refusal$"):
        provision(str(tmp_path), sources, companion=True,
                  randomize={"settings_path": "s.rnqs"}, jar="fake.jar")
    assert (tmp_path / "rom_contract.json").read_text() == "old contract"
    assert all((tmp_path / "roms" / name).read_bytes() == b"old cartridge" for name in ("a.gb", "b.gb"))


def test_nonrandomized_reprovision_drops_previous_contract(tmp_path):
    from server.cartridges import provision

    (tmp_path / "rom_contract.json").write_text("old randomization contract")
    provision(str(tmp_path), _vanilla(), companion=False, randomize=None)
    assert not (tmp_path / "rom_contract.json").exists()


def test_overlay_hash_must_match_admission(tmp_path, monkeypatch):
    from server import cartridges

    source = _pure()
    real_lookup = cartridges._overlay_admission_row
    monkeypatch.setattr(cartridges, "_overlay_admission_row",
                        lambda title: ("0" * 40, real_lookup(title)[1]))
    with pytest.raises(cartridges.CartridgeError, match="admitted pureRGB overlay"):
        cartridges.provision(str(tmp_path / "run"), {"a": source, "b": source},
                             companion=True, randomize=None)
    assert not (tmp_path / "run").exists()


def test_missing_jar_and_malformed_settings_refuse(tmp_path, monkeypatch):
    from server.cartridges import CartridgeError, provision

    sources = _vanilla()
    monkeypatch.setattr(upr_pipeline, "find_upr_jar", lambda: None)
    with pytest.raises(CartridgeError, match="jar not found"):
        provision(str(tmp_path), sources, companion=False, randomize={"settings_path": "s.rnqs"})
    with pytest.raises(CartridgeError, match="settings_path"):
        provision(str(tmp_path), sources, companion=False, randomize={})


def test_finds_default_jar(tmp_path, monkeypatch):
    from server.cartridges import provision

    sources = _vanilla()
    _fake_pair(monkeypatch)
    fake = upr_pipeline.prepare_pair
    monkeypatch.setattr(upr_pipeline, "find_upr_jar", lambda: "discovered.jar")
    def check(jar, *args):
        assert jar == "discovered.jar"
        return fake(jar, *args)
    monkeypatch.setattr(upr_pipeline, "prepare_pair", check)
    provision(str(tmp_path), sources, companion=False, randomize={"settings_path": "s.rnqs"})


def test_requires_both_players(tmp_path):
    from server.cartridges import CartridgeError, provision

    with pytest.raises(CartridgeError, match="players a and b"):
        provision(str(tmp_path), {}, companion=False, randomize=None)


def test_missing_source_refuses(tmp_path):
    from server.cartridges import CartridgeError, provision

    with pytest.raises(CartridgeError, match="source ROM not found"):
        provision(str(tmp_path), {"a": "missing.gb", "b": "missing.gb"}, companion=False, randomize=None)


def test_refuses_overwriting_picked_original(tmp_path):
    from server.cartridges import CartridgeError, provision

    sources = _vanilla()
    (tmp_path / "roms").mkdir()
    original = Path(sources["a"]).read_bytes()
    picked = tmp_path / "roms" / "b.gb"
    picked.write_bytes(original)
    sources["a"] = str(picked)
    with pytest.raises(CartridgeError, match="source is a run output"):
        provision(str(tmp_path), sources, companion=True, randomize=None)
    assert picked.read_bytes() == original



def test_refuses_overwriting_another_players_source_with_intermediate(tmp_path, monkeypatch):
    from server.cartridges import CartridgeError, provision

    sources = _vanilla()
    (tmp_path / "roms").mkdir()
    picked = tmp_path / "roms" / "a_randomized.gbc"
    original = Path(sources["b"]).read_bytes()
    picked.write_bytes(original)
    sources["b"] = str(picked)
    _fake_pair(monkeypatch)
    with pytest.raises(CartridgeError, match="source is a run output"):
        provision(str(tmp_path), sources, companion=False,
                  randomize={"settings_path": "s.rnqs"}, jar="fake.jar")
    assert picked.read_bytes() == original


def test_injection_refusal_is_reported_before_final_outputs(tmp_path, monkeypatch):
    from server.cartridges import CartridgeError, provision

    sources = _vanilla()
    _fake_pair(monkeypatch)
    actual_inject = inject.inject
    count = 0
    def fail_second(rom):
        nonlocal count
        count += 1
        if count == 2:
            raise inject.InjectError("second cartridge cannot take the payload")
        return actual_inject(rom)
    monkeypatch.setattr(inject, "inject", fail_second)
    with pytest.raises(CartridgeError, match="second cartridge cannot take the payload"):
        provision(str(tmp_path), sources, companion=True,
                  randomize={"settings_path": "s.rnqs"}, jar="fake.jar")
    assert not (tmp_path / "roms" / "a.gb").exists()
    assert not (tmp_path / "roms" / "b.gb").exists()
    assert not (tmp_path / "rom_contract.json").exists()
