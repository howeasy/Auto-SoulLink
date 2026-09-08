import asyncio
import json
import sys

import pytest

from server.broadcast_presets import ALIASES, PRESETS
from server.broadcast_sources import SourceError, SourceStore


def settings(**changes):
    return {"name": "Team", "run_id": "run_one", "preset": "party", "players": ["a"], "layout": "", "theme": "transparent", "controls": {}, **changes}


@pytest.fixture
def store(tmp_path):
    runs = {"run_one": {"status": "running"}, "run_two": {"status": "stopped"}}
    return SourceStore(tmp_path / "sources.json", runs.get), runs


def test_presets_cover_every_real_legacy_overlay_without_the_synthetic_gallery():
    from server.overlay_catalog import OVERLAYS
    assert set(ALIASES) == {row["slug"] for row in OVERLAYS if row["slug"] != "all"}
    assert "all" not in PRESETS and len(PRESETS) == 17
    assert all(preset["sizes"] for preset in PRESETS.values())


@pytest.mark.asyncio
async def test_source_identity_survives_retargeting_and_layout_changes(store):
    service, _ = store
    original = await service.create(settings())
    updated = await service.update(original["id"], {"revision": 1, "run_id": "run_two", "name": "Partner", "players": ["b"], "layout": "h", "theme": "light"})
    assert original["id"] == updated["id"] and updated["revision"] == 2
    assert updated["run_id"] == "run_two" and updated["players"] == ["b"]
    assert service.get(original["id"]) == updated
    updated["players"].append("a")
    assert service.get(original["id"])["players"] == ["b"]


@pytest.mark.asyncio
async def test_run_archive_or_deletion_cannot_retarget_or_remove_saved_sources(store):
    service, runs = store
    source = await service.create(settings())
    runs["run_one"]["status"] = "archived"
    assert service.get(source["id"])["run_id"] == "run_one"
    del runs["run_one"]
    assert service.get(source["id"])["run_id"] == "run_one"
    renamed = await service.update(source["id"], {"revision": 1, "name": "History"})
    assert renamed["run_id"] == "run_one"
    with pytest.raises(SourceError, match="no longer exists"):
        await service.create(settings())


@pytest.mark.asyncio
async def test_stale_source_edits_and_identity_changes_are_rejected(store):
    service, _ = store
    source = await service.create(settings())
    await service.update(source["id"], {"revision": 1, "name": "New name"})
    with pytest.raises(SourceError) as error:
        await service.update(source["id"], {"revision": 1, "run_id": "run_two"})
    assert error.value.status == 409
    with pytest.raises(SourceError, match="cannot be changed"):
        await service.update(source["id"], {"revision": 2, "id": "f" * 32})
    with pytest.raises(SourceError) as error:
        await service.delete(source["id"], 1)
    assert error.value.status == 409
    assert service.get(source["id"])["run_id"] == "run_one"


@pytest.mark.asyncio
async def test_parallel_source_creation_preserves_every_record_and_never_reuses_ids(store):
    service, _ = store
    sources = await asyncio.gather(*(service.create(settings(name=f"Source {n}")) for n in range(10)))
    assert len(service.list()) == len({source["id"] for source in sources}) == 10
    old_id = sources[0]["id"]
    await service.delete(old_id, 1)
    new = await service.create(settings())
    assert new["id"] != old_id
    with pytest.raises(SourceError) as error:
        service.get(old_id)
    assert error.value.status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"run_id": None}, {"preset": "all"}, {"theme": "untrusted"}, {"players": ["b", "a"]},
    {"preset": "deaths", "players": ["a", "b"], "controls": {"speed": 1}}, {"layout": "unknown"}])
async def test_only_supported_preset_configuration_is_accepted(store, changes):
    service, _ = store
    with pytest.raises(SourceError):
        await service.create(settings(**changes))
    assert not service.path.exists()


@pytest.mark.asyncio
async def test_corrupt_source_store_is_preserved_before_any_mutation(store):
    service, _ = store
    original = b'{"schema":1,"sources":['
    service.path.write_bytes(original)
    with pytest.raises(SourceError) as error:
        await service.create(settings())
    assert error.value.status == 503 and service.path.read_bytes() == original


@pytest.mark.asyncio
async def test_native_theme_alias_and_literal_names_round_trip_without_data_loss(store):
    service, _ = store
    name = '</script><img data-ui-probe="unsafe">'
    source = await service.create(settings(name=name, theme="dark"))
    assert source["theme"] == "default" and service.get(source["id"])["name"] == name
    assert json.loads(service.path.read_text())["sources"][0]["name"] == name


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["boolean_schema", "float_schema", "duplicate_root", "duplicate_run", "escaped_duplicate_run", "deep_json"])
async def test_ambiguous_store_is_refused_and_preserved_for_every_operation(store, damage):
    service, _ = store
    source = await service.create(settings())
    record = json.dumps(source)
    raw = '{"schema":1,"sources":[' + record + ']}'
    if damage == "boolean_schema":
        raw = raw.replace('"schema":1', '"schema":true')
    elif damage == "float_schema":
        raw = raw.replace('"schema":1', '"schema":1.0')
    elif damage == "duplicate_root":
        raw = raw[:-1] + ',"sources":[]}'
    elif damage in {"duplicate_run", "escaped_duplicate_run"}:
        duplicate = 'run_id' if damage == "duplicate_run" else r'run\u005fid'
        raw = raw.replace('"run_id": "run_one"', '"run_id": "run_one", "' + duplicate + '": "run_two"')
    else:
        depth = sys.getrecursionlimit() + 50
        raw = '[' * depth + '0' + ']' * depth
    original = raw.encode()
    service.path.write_bytes(original)
    for read in (service.list, lambda: service.get(source["id"])):
        with pytest.raises(SourceError) as error:
            read()
        assert error.value.status == 503
    for mutate in (
        lambda: service.create(settings()),
        lambda: service.update(source["id"], {"revision": 1, "name": "Renamed"}),
        lambda: service.delete(source["id"], 1),
    ):
        with pytest.raises(SourceError) as error:
            await mutate()
        assert error.value.status == 503
        assert service.path.read_bytes() == original
