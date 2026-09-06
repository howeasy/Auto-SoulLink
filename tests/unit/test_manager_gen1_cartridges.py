"""Manager binds actual local files atomically; partial fingerprints never qualify."""
import json
from pathlib import Path

import pytest

from server import gen1_admission as admission, manager as mgr
from tests.unit.test_manager_randomize import _Request, manager_dir  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
ROMS = {p: ROOT / "patch/build" / filename for p, filename in
        (("a", "gen1_red.gb"), ("b", "gen1_yellow.gbc"))}


async def post(body, run_id="run_test"):
    manager = mgr.RunManager("127.0.0.1")
    response = await manager.handle_cartridges(_Request(run_id, body))
    return response.status, json.loads(response.text)


@pytest.mark.asyncio
async def test_clean_setup_persists_each_players_verified_title_hash_and_profile(manager_dir):  # noqa: F811
    status, result = await post({"rom_" + p: str(path) for p, path in ROMS.items()})
    assert status == 200 and result["ok"]
    data = json.loads((manager_dir / "run_test/rom_contract.json").read_text())
    assert admission.validate_contract(data) == result["cartridges"]
    assert data["players"]["a"]["variant"] == "red" and data["players"]["b"]["variant"] == "yellow"
    assert mgr._load_registry()[0]["cartridges"] == data["players"]
    assert not list((manager_dir / "run_test").glob("*.gb*"))


@pytest.mark.parametrize("change", ["species", "header", "padding", "patch", "truncated"])
@pytest.mark.asyncio
async def test_any_unverified_rom_change_creates_no_contract(manager_dir, tmp_path, change):  # noqa: F811
    data = bytearray(ROMS["a"].read_bytes())
    offsets = {"species": 0xD0DF, "header": 0x134, "padding": 0xF8000, "patch": 0x29BF}
    if change == "truncated":
        data.pop()
    else:
        data[offsets[change]] ^= 1
    path = tmp_path / "changed.gb"
    path.write_bytes(data)
    status, result = await post({"rom_a": str(path), "rom_b": str(ROMS["b"])})
    assert status == 400 and not result["ok"]
    assert not (manager_dir / "run_test/rom_contract.json").exists()
    assert "cartridges" not in mgr._load_registry()[0]


@pytest.mark.asyncio
async def test_failed_publication_reports_failure_and_no_success_metadata(manager_dir, monkeypatch):  # noqa: F811
    def fail(*args):
        raise PermissionError("injected publication failure")
    monkeypatch.setattr(admission.os, "replace", fail)
    status, result = await post({"rom_" + p: str(path) for p, path in ROMS.items()})
    assert status == 500 and not result["ok"]
    assert not (manager_dir / "run_test/rom_contract.json").exists()
    assert not list((manager_dir / "run_test").glob(".cartridge-*"))
    assert "cartridges" not in mgr._load_registry()[0]


def test_an_existing_binding_cannot_be_overwritten(tmp_path):
    first = admission.clean_contract(ROMS)
    path = tmp_path / "rom_contract.json"
    admission.write_contract(path, first)
    before = path.read_bytes()
    admission.write_contract(path, first)  # identical retry
    with pytest.raises(admission.AdmissionError, match="already bound"):
        admission.write_contract(path, admission.clean_contract({"a": ROMS["b"], "b": ROMS["a"]}))
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_invalid_body_and_unknown_run(manager_dir):  # noqa: F811
    assert (await post([]))[0] == 400
    assert (await post({}, "missing"))[0] == 404
