"""Verify selected Gen 2 source contexts from the real pinned P1 products."""

import hashlib
import re
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("title,artifact", [("crystal", "pokecrystal"), ("gold", "pokegold"),
                                            ("silver", "pokesilver")])
def test_context_verifies_selected_title_and_exact_source(title, artifact):
    from tools.gen2_source_data import load_context

    ctx = load_context(title)
    assert ctx.artifact == artifact
    assert hashlib.sha1(ctx.rom).hexdigest() == ctx.lock["outputs"][artifact]["sha1"]
    assert ctx.symbol("wPartyMon1").address >= 0xC000
    assert "DEF NUM_BOXES EQU 14" in ctx.read_source("constants/pokemon_data_constants.asm")
    assert ctx.source_record()["evidence_level"] == "SOURCE"


def test_crystal11_is_not_a_selected_title():
    from tools.gen2_source_data import load_context

    with pytest.raises(ValueError, match="selected title"):
        load_context("crystal11")


@pytest.mark.parametrize("relative", ["data/gen2/pokecrystal.sym", "data/gen2/pokegold.map",
                                     ".cache/gen2-build/pokecrystal/pokecrystal.gbc"])
def test_context_refuses_actual_artifact_tampering(monkeypatch, relative):
    from tools.gen2_source_data import ROOT, load_context

    target = (ROOT / relative).resolve()
    original = Path.read_bytes

    def corrupt(path):
        raw = original(path)
        return raw + b"tampered" if path.resolve() == target else raw

    monkeypatch.setattr(Path, "read_bytes", corrupt)
    with pytest.raises(ValueError, match="differs from pinned"):
        load_context("crystal")


@pytest.mark.parametrize("operation", ["head", "dirty"])
def test_context_refuses_wrong_or_dirty_source(monkeypatch, operation):
    from tools.gen2_source_data import load_context

    original = subprocess.run

    def changed_source(args, **kwargs):
        if operation == "head" and args[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "0" * 40, "")
        if operation == "dirty" and "status" in args:
            return subprocess.CompletedProcess(args, 0, " M constants/pokemon_constants.asm\n", "")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", changed_source)
    with pytest.raises(ValueError, match="HEAD differs|dirty"):
        load_context("crystal")


def test_missing_symbol_and_source_escape_fail_explicitly():
    from tools.gen2_source_data import load_context

    ctx = load_context("crystal")
    with pytest.raises(ValueError, match="required symbol"):
        ctx.symbol("MissingRequiredSymbol")
    with pytest.raises(ValueError, match="escapes pinned checkout"):
        ctx.read_source("../pokegold/constants/pokemon_constants.asm")


def test_context_does_not_read_a_different_commit_after_creation(monkeypatch):
    from tools.gen2_source_data import load_context

    ctx = load_context("crystal")
    original = subprocess.run

    def switched_source(args, **kwargs):
        if args[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "0" * 40, "")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", switched_source)
    with pytest.raises(ValueError, match="HEAD"):
        ctx.read_source("constants/pokemon_constants.asm")


def _mutate_happiness_read(monkeypatch):
    original = Path.read_text

    def changed_text(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path.as_posix().endswith("/constants/pokemon_data_constants.asm"):
            text, count = re.subn(r"(DEF HAPPINESS_TO_EVOLVE\s+EQU\s+)220", r"\g<1>1", text)
            assert count == 1, "the injected mutation must reach exactly one source fact"
        return text

    monkeypatch.setattr(Path, "read_text", changed_text)


def test_source_text_is_bound_to_pinned_blob_after_clean_checks(monkeypatch):
    from tools.gen2_source_data import load_context

    ctx = load_context("crystal")
    relative = "constants/pokemon_data_constants.asm"
    original = ctx.read_source(relative)
    assert re.search(r"DEF HAPPINESS_TO_EVOLVE\s+EQU\s+220", original)
    _mutate_happiness_read(monkeypatch)
    # All real Git checks still run. Returning a different buffer from the
    # later worktree read must not relabel that buffer as pinned source.
    assert ctx.read_source(relative) == original


def test_evolution_consumer_cannot_accept_after_check_source_mutation(monkeypatch):
    from tools.gen_gen2_evos import build

    baseline = build("crystal")
    _mutate_happiness_read(monkeypatch)
    generated = build("crystal")
    assert {
        row["minimum_happiness"] for row in generated["methods"]["133"]
        if row["method"] == "HAPPINESS"
    } == {220}
    assert generated == baseline


def test_pinned_blob_preserves_whitespace_and_normalizes_newlines(monkeypatch):
    from tools.gen2_source_data import load_context

    ctx = load_context("crystal")
    relative = "constants/pokemon_data_constants.asm"
    original = subprocess.run
    seen = []

    def blob_bytes(args, **kwargs):
        if "cat-file" in args:
            seen.append(args)
            return subprocess.CompletedProcess(args, 0, b"  start\r\n\r\nnext\rtail \n\n", b"")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", blob_bytes)
    assert ctx.read_source(relative) == "  start\n\nnext\ntail \n\n"
    assert len(seen) == 1
    assert seen[0][-1] == f"{ctx.source_commit}:{relative}"
    assert "--no-replace-objects" in seen[0]


@pytest.mark.parametrize("operation", ("untracked", "dirty", "missing_blob"))
def test_pinned_blob_keeps_checkout_and_missing_object_refusals(monkeypatch, operation):
    from tools.gen2_source_data import load_context

    ctx = load_context("crystal")
    original = subprocess.run

    def changed_source(args, **kwargs):
        if operation == "untracked" and "ls-files" in args:
            return subprocess.CompletedProcess(args, 1, "", "path is not tracked")
        if operation == "dirty" and "status" in args:
            return subprocess.CompletedProcess(args, 0, " M constants/pokemon_data_constants.asm\n", "")
        if operation == "missing_blob" and "cat-file" in args:
            return subprocess.CompletedProcess(args, 1, b"", b"missing pinned blob")
        if operation != "missing_blob" and "cat-file" in args:
            pytest.fail("checkout refusal must happen before reading a blob")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", changed_source)
    with pytest.raises(ValueError, match="not tracked|source changed|pinned source blob"):
        ctx.read_source("constants/pokemon_data_constants.asm")


def test_source_symlink_resolution_cannot_escape_checkout(monkeypatch):
    from tools.gen2_source_data import load_context

    ctx = load_context("crystal")
    relative = "constants/redirected.asm"
    target = ctx.source_dir / relative
    outside = ctx.source_dir.parent / "outside.asm"
    original = Path.resolve

    # Simulate the filesystem's symlink resolution without modifying the clone
    # or requiring Windows symlink privileges in the test environment.
    def redirected(path, *args, **kwargs):
        return outside if path == target else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(ValueError, match="escapes pinned checkout"):
        ctx.read_source(relative)


def test_shared_contexts_hand_every_caller_one_verified_context_per_title():
    """EMU-SPEED item 2: inside shared_contexts() route/qualify/U1/trade facts reuse one context (and
    its read_source memo); outside, every load_context verifies afresh."""
    from tools import gen2_source_data as source
    with source.shared_contexts():
        first = source.load_context("gold")
        assert source.load_context("gold") is first
        with source.shared_contexts():   # nested blocks share the outer run's contexts
            assert source.load_context("gold") is first
        assert source.load_context("silver") is not first
    assert source.load_context("gold") is not first
