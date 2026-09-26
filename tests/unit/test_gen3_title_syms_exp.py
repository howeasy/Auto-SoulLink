"""Generated harness addresses, not runtime/record-layout qualification."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "lua/tests/gen3_title_syms.lua"
TITLE = "emerald_expansion_28877d73"
GENERATED = ROOT / "lua/tests/gen3_title_syms_exp_28877d73.lua"


@pytest.fixture
def artifact():
    path = Path(os.environ.get("SLINK_EXPANSION_SYMS",
                              ROOT / ".cache/expansion-output/reference/pokeemerald.sym"))
    if not path.is_file():
        pytest.skip(f"pinned expansion build symbols absent: {path}")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "ac24a47c0137ab9b2233ccf37bf0cabe8b6eb08b715aa7e87f15787507a1f01e")
    return path


def test_expansion_title_uses_generated_reference_addresses():
    module = LuaRuntime().execute(f'return dofile("{TABLE.as_posix()}")')
    result = module.for_title(TITLE)
    # Independent compiler facts and pinned sym rows, not vanilla aliases.
    assert result.PARTY_BASE == 0x02031B64
    assert result.PARTY_COUNT_ADDR == 0x02031B54
    assert result.GMAIN_CALLBACK2_ADDR == 0x030066C4
    assert result.HANDLE_INPUT_CHOOSE_ACTION == 0x0805CCD5
    assert result.PC_MENU_BASE == 0x020310C8
    assert result.ACTIVE_BATTLER_ADDR is None


def test_legacy_columns_are_byte_identical():
    body = TABLE.read_text().split("M.entries = {", 1)[1].split("\nlocal TITLES", 1)[0]
    assert hashlib.sha256(body.encode()).hexdigest() == (
        "44659638f2a833f2f7d42cbf5c7ff2cc8f8568c2f1b31084e31ec8205cacb1bb")


def test_every_generated_entry_resolves_or_is_explicit_nil(artifact):
    lua = LuaRuntime()
    main = lua.execute(f'return dofile("{TABLE.as_posix()}")')
    generated = lua.execute(f'return dofile("{GENERATED.as_posix()}")')
    assert set(main.entries) == set(generated.entries)
    rows = {}
    for line, text in enumerate(artifact.read_text().splitlines(), 1):
        match = re.fullmatch(r"([0-9a-fA-F]{8}) [gl] ([0-9a-fA-F]{8}) (\S+)", text)
        if match:
            address, size, symbol = match.groups()
            rows.setdefault(symbol, []).append((int(address, 16), int(size, 16), line))
    for values in rows.values():
        values.sort()
    nils = set()
    for name, entry in generated.entries.items():
        assert entry.source
        if entry.address is None:
            nils.add(name)
            assert entry.status == "nil" and "expansion@e8bd1cd7" in entry.source
            continue
        address, size, line = rows[entry.symbol][entry.occurrence]
        assert entry.address == ((address + entry.offset) | int(entry.thumb))
        assert entry.symbol_line == line and entry.symbol_size == size
    assert nils == {"ACTIVE_BATTLER_ADDR", "BAG_MENU_STATE_ADDR", "TASK_ANIMATE_WIN0V",
                    "TASK_OAKSPEECH_GENDER_INPUT", "TASK_START_MENU_HANDLE_INPUT",
                    "START_CB_HANDLE_INPUT", "START_CB_SAVE1", "START_CB_SAVE2"}
    facts = json.loads((ROOT / "data/games/gen3_exp/28877d73/facts.json").read_text())
    assert generated.entries.GMAIN_CALLBACK2_ADDR.offset == facts["structs"]["Main"]["fields"]["callback2"]["offset"]
    assert generated.entries.PARTY_BASE.symbol == "gParties"
    assert generated.entries.PARTY_COUNT_ADDR.symbol == "gPartiesCount"


def test_generator_check_is_read_only_and_rejects_stale_output(artifact, tmp_path, monkeypatch):
    from tools import gen_gen3_title_syms_exp as gen

    assert gen.generate(artifact) == GENERATED.read_text()
    output = tmp_path / "output.lua"
    output.write_text(GENERATED.read_text())
    monkeypatch.setattr(gen, "OUTPUT", output)
    monkeypatch.setattr(sys, "argv", ["generator", "--symbols", str(artifact), "--check"])
    stamp = output.stat().st_mtime_ns
    gen.main()
    assert output.stat().st_mtime_ns == stamp
    output.write_text("stale")
    with pytest.raises(SystemExit) as error:
        gen.main()
    assert error.value.code == 1 and output.read_text() == "stale"


def test_generator_refuses_wrong_artifact_and_wrong_rom(artifact, tmp_path):
    from tools import gen_gen3_title_syms_exp as gen

    wrong = tmp_path / "wrong.sym"
    wrong.write_bytes(artifact.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="artifact hash/size"):
        gen.generate(wrong)
    layout = json.loads(gen.LAYOUT.read_text())
    layout["rom_sha1"] = "0" * 40
    wrong_layout = tmp_path / "layout.json"
    wrong_layout.write_text(json.dumps(layout))
    with pytest.raises(ValueError, match="ROM pin"):
        gen.generate(artifact, layout_path=wrong_layout)
