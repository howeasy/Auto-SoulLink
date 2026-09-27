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
        f"See docs/gen3_requirements.md F-7 -- for gen_rr_priority_trainers.py this is a "
        f"known, currently-reproducible finding (the community Google Sheet has moved on "
        f"from what produced the committed roster), not a broken pin.\n"
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
