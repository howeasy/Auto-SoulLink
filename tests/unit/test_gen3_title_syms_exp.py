"""Generated harness addresses, not runtime/record-layout qualification."""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "lua/tests/gen3_title_syms.lua"
TITLE = "emerald_expansion_28877d73"
GENERATED = ROOT / "lua/tests/gen3_title_syms_exp_28877d73.lua"


SYM_SHA256 = "ac24a47c0137ab9b2233ccf37bf0cabe8b6eb08b715aa7e87f15787507a1f01e"
SYM_SLICE = ROOT / "data/games/gen3_exp/28877d73/harness_rows.sym"


@pytest.fixture
def artifact():
    """The full pinned .sym when available (SLINK_EXPANSION_SYMS or the default .cache path),
    else the committed hash-bound slice -- never skipped, so these tests always run in CI."""
    path = Path(os.environ.get("SLINK_EXPANSION_SYMS",
                              ROOT / ".cache/expansion-output/reference/pokeemerald.sym"))
    if not path.is_file():
        return SYM_SLICE
    assert hashlib.sha256(path.read_bytes()).hexdigest() == SYM_SHA256
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
    from tools import gen_gen3_title_syms_exp as gen

    lua = LuaRuntime()
    main = lua.execute(f'return dofile("{TABLE.as_posix()}")')
    generated = lua.execute(f'return dofile("{GENERATED.as_posix()}")')
    assert set(main.entries) == set(generated.entries)
    # Reuse the generator's own parser (handles both the full .sym and the committed slice's
    # "-- line N" annotations identically), instead of re-deriving row/line lookup here.
    rows = gen.symbols(artifact.read_text(encoding="utf-8"))
    nils = set()
    for name, entry in generated.entries.items():
        assert entry.source
        if entry.address is None:
            nils.add(name)
            assert entry.status == "nil" and "expansion@e8bd1cd7" in entry.source
            # The documented-nil reason is only trustworthy if the symbol it names really is
            # absent from this build -- same requirement generate() enforces (card X3-FIX #1).
            legacy = main.entries[name]
            symbol = legacy.emerald_symbol or legacy.symbol
            assert symbol not in rows, f"documented-nil symbol now present in build: {name} ({symbol})"
            continue
        hit = rows[entry.symbol][entry.occurrence]
        assert entry.address == ((hit["address"] + entry.offset) | int(entry.thumb))
        assert entry.symbol_line == hit["line"] and entry.symbol_size == hit["size"]
    assert nils == {"ACTIVE_BATTLER_ADDR", "BAG_MENU_STATE_ADDR", "TASK_ANIMATE_WIN0V",
                    "TASK_OAKSPEECH_GENDER_INPUT", "TASK_START_MENU_HANDLE_INPUT",
                    "START_CB_HANDLE_INPUT", "START_CB_SAVE1", "START_CB_SAVE2"}
    facts = json.loads((ROOT / "data/games/gen3_exp/28877d73/facts.json").read_text())
    assert generated.entries.GMAIN_CALLBACK2_ADDR.offset == facts["structs"]["Main"]["fields"]["callback2"]["offset"]
    assert generated.entries.PARTY_BASE.symbol == "gParties"
    assert generated.entries.PARTY_COUNT_ADDR.symbol == "gPartiesCount"


def test_slice_rows_match_full_sym_when_present():
    """The committed harness_rows.sym slice must be a byte-for-byte-equivalent excerpt: every row
    it carries (address/size/original line) has to agree with the full pinned .sym (card X3-FIX
    #2). Skips only because it needs the 4.6 MB full artifact this repo doesn't commit."""
    full = Path(os.environ.get("SLINK_EXPANSION_SYMS",
                              ROOT / ".cache/expansion-output/reference/pokeemerald.sym"))
    if not full.is_file():
        pytest.skip(f"pinned expansion build symbols absent: {full}")
    assert hashlib.sha256(full.read_bytes()).hexdigest() == SYM_SHA256

    from tools import gen_gen3_title_syms_exp as gen

    full_rows = gen.symbols(full.read_text(encoding="utf-8"))
    slice_rows = gen.symbols(SYM_SLICE.read_text(encoding="utf-8"))
    assert slice_rows, "slice parsed to no rows"
    for name, hits in slice_rows.items():
        assert hits == full_rows.get(name), f"slice row(s) for {name} disagree with the full .sym"


def test_generator_check_is_read_only_and_rejects_stale_output(artifact, tmp_path, monkeypatch):
    from tools import gen_gen3_title_syms_exp as gen

    assert gen.generate(artifact) == GENERATED.read_text()
    output = tmp_path / "output.lua"
    output.write_bytes(GENERATED.read_bytes())  # exact bytes: --check now compares bytes, not text
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
