"""SOURCE/MODEL tests against verified P1 artifacts; no emulator or write grant.

Missing built inputs are errors, never skips or synthetic production evidence.
Counterfacts use an in-memory view and never alter the pinned source clones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import gen_gen2_write_checkpoint as checkpoint
from tools.gen2_source_data import Symbol, load_context, rom_offset


class SourceView:
    """In-memory counterfacts after loading a verified source/artifact boundary."""

    def __init__(self, base, cache):
        self.base = base
        self.cache = cache
        self.overrides = {}
        self.symbols = dict(base.symbols)
        self.rom = base.rom
        self.title = base.title

    def __getattr__(self, name):
        return getattr(self.base, name)

    def symbol(self, name):
        if name not in self.symbols:
            raise ValueError(f"missing required symbol: {name}")
        return self.symbols[name]

    def read_source(self, path):
        if path in self.overrides:
            return self.overrides[path]
        if path not in self.cache:
            self.cache[path] = self.base.read_source(path)
        return self.cache[path]


@pytest.fixture(scope="module")
def sources():
    return {title: (load_context(title), {}) for title in checkpoint.TITLES}


@pytest.fixture
def view(sources):
    def create(title="crystal"):
        return SourceView(*sources[title])
    return create


@pytest.mark.parametrize("title,pc,caller_return,stack_min,stack_end,stack_bank,source_line", [
    ("crystal", 0x6983, 0x6844, 0xC000, 0xC0FF, 0, 495),
    ("gold", 0x68B6, 0x6783, 0xDF03, 0xDFFF, 1, 483),
    ("silver", 0x68B6, 0x6783, 0xDF03, 0xDFFF, 1, 483),
])
def test_real_pinned_candidates(view, title, pc, caller_return, stack_min, stack_end, stack_bank, source_line):
    ctx = view(title)
    pack = checkpoint.build_title(ctx)
    assert list(pack["titles"]) == [title]
    candidate = pack["titles"][title]
    assert candidate["runtime_authorized"] is False
    assert candidate["maturity"] == "SOURCE_CANDIDATE"
    assert candidate["physical"] == {
        "status": "OPEN", "liveness": "UNMEASURED", "negative_controls": "UNRUN",
        "required_controls": candidate["physical"]["required_controls"],
    }
    assert candidate["irq_anchor"]["status"] == "UNAVAILABLE"
    primary = candidate["primary"]
    site = primary["execution_before"]
    assert (site["bank"], site["pc"]) == (0x25, pc)
    assert site["source"]["line_start"] == source_line
    target = ctx.symbol("CheckAPressOW")
    flat = rom_offset(0x25, pc)
    assert ctx.rom[flat:flat + 3] == b"\xcd" + target.address.to_bytes(2, "little")
    stack = primary["caller_stack"]
    assert (stack["minimum_sp"], stack["exclusive_stack_end"], stack["bank"]) == (stack_min, stack_end, stack_bank)
    assert stack["required_words"] == [{"offset_from_sp": 0, "value": caller_return, "endianness": "little"}]
    assert stack["required_read_bytes"] == 2
    assert stack["must_fit_entire_read"] is True
    assert stack["search_for_return_address"] is False
    for anchor in primary["anchors"].values():
        data = bytes.fromhex(anchor["expected_hex"])
        assert data == ctx.rom[anchor["rom_offset"]:anchor["rom_offset"] + len(data)]
        assert anchor["source"]["commit"] == ctx.source_commit
    assert pack["source"]["rom_sha1"] == ctx.lock["outputs"][ctx.artifact]["sha1"]


@pytest.mark.parametrize("title", checkpoint.TITLES)
def test_conjunction_keeps_script_wait_save_and_ownership_obligations(view, title):
    candidate = checkpoint.build_title(view(title))["titles"][title]
    primary = candidate["primary"]
    assert primary["acceptance"] == "ALL_REQUIRED_SAME_HELD_EXECUTION"
    rows = {row["symbol"]: row for row in primary["state_predicates"]}
    assert set(rows) == {
        "wMapStatus", "wMapEventStatus", "wScriptRunning", "wScriptMode", "wScriptFlags",
        "wScriptStackSize", "wJoypadDisable", "wGameLogicPaused", "wInputType", "wBattleMode",
        "wStateFlags", "hMapEntryMethod", "wLinkMode", "hSerialConnectionStatus", "wSavedAtLeastOnce",
    }
    assert (rows["wScriptFlags"]["mask"], rows["wScriptFlags"]["value"]) == (0x0C, 0)
    assert (rows["wScriptMode"]["mask"], rows["wScriptMode"]["value"]) == (255, 0)
    assert (rows["wSavedAtLeastOnce"]["mask"], rows["wSavedAtLeastOnce"]["value"]) == (255, 1)
    assert rows["wMapStatus"]["value"] == 2
    assert rows["hSerialConnectionStatus"]["value"] == 255
    assert all(row["semantic_source"] for row in rows.values())
    ownership = primary["ownership_requirements"]
    assert ownership["effective_wram_bank"] == 1
    assert ownership["mapped_rom_bank_must_equal_shadow"] is True
    assert ownership["cached_frame_acceptance_allowed"] is False
    assert ownership["serial_control"]["mask"] == 0x80
    assert len(ownership["host"]) >= 6


@pytest.mark.parametrize("title", checkpoint.TITLES)
@pytest.mark.parametrize("anchor_name", ["OWPlayerInput", "PlayerEvents"])
def test_one_corrupted_real_anchor_byte_refuses(view, title, anchor_name):
    ctx = view(title)
    mutable = bytearray(ctx.rom)
    mutable[rom_offset(*ctx.symbol(anchor_name))] ^= 1
    ctx.rom = bytes(mutable)
    with pytest.raises(ValueError, match="ROM anchor mismatch"):
        checkpoint.build_title(ctx)


@pytest.mark.parametrize("symbol", ["CheckAPressOW", "wScriptFlags", "wMapEventStatus", "wJoypadDisable",
                                    "wBattleMode", "wSavedAtLeastOnce", "wStackBottom", "hROMBank"])
def test_required_symbol_missing_refuses(view, symbol):
    ctx = view()
    del ctx.symbols[symbol]
    with pytest.raises(ValueError, match="missing required symbol"):
        checkpoint.build_title(ctx)


def test_extra_caller_is_not_hidden_by_valid_original_anchor(view):
    ctx = view()
    ctx.overrides[checkpoint.EVENTS] = ctx.read_source(checkpoint.EVENTS) + "\nOtherCaller:\n\tcall OWPlayerInput\n"
    with pytest.raises(ValueError, match="caller missing/ambiguous"):
        checkpoint.build_title(ctx)


@pytest.mark.parametrize("path,before,after", [
    (checkpoint.EVENTS, "\tcall CheckAPressOW", "\tcall CheckMenuOW"),
    (checkpoint.RAM_CONSTANTS, "\tconst SCRIPT_OFF", "\tconst SCRIPT_UNKNOWN"),
    ("macros/farcall.asm", "\trst FarCall", "\trst Bankswitch"),
    ("engine/menus/save.asm", "\tld [wSavedAtLeastOnce], a", "\tld [wCurBox], a"),
    ("ram/wram.asm", "\tds $100 - 1", "\tds $ff - 1"),
])
def test_source_counterfacts_refuse_without_rom_changes(view, path, before, after):
    ctx = view()
    source = ctx.read_source(path)
    assert before in source
    ctx.overrides[path] = source.replace(before, after, 1)
    with pytest.raises(ValueError, match="source assertion"):
        checkpoint.build_title(ctx)


@pytest.mark.parametrize("title,symbol,bank,address", [
    ("gold", "wStackTop", 0, 0xDFFF),
    ("crystal", "wStackBottom", 0, 0xC001),
    ("gold", "wMapEventStatus", 2, 0xD100),
    ("crystal", "hROMBank", 0, 0xFFFF),
    ("crystal", "PlayerMovement", 0x26, 0x4000),
])
def test_wrong_memory_or_code_ownership_refuses(view, title, symbol, bank, address):
    ctx = view(title)
    ctx.symbols[symbol] = Symbol(bank, address)
    with pytest.raises(ValueError, match="stack allocation|memory ownership|near call crosses"):
        checkpoint.build_title(ctx)


def test_crystal11_has_no_selected_checkpoint_admission(view):
    ctx = view()
    ctx.title = "crystal11"
    with pytest.raises(ValueError, match="unsupported selected title"):
        checkpoint.build_title(ctx)


def _snapshot(root: Path):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_check_and_late_failure_never_publish_partial_candidates(view, monkeypatch, tmp_path):
    monkeypatch.setattr(checkpoint, "ROOT", tmp_path)
    monkeypatch.setattr(checkpoint, "load_context", lambda title, root: view(title))
    assert checkpoint.main(["--check"]) == 1
    assert _snapshot(tmp_path) == {}
    assert checkpoint.main([]) == 0
    original = _snapshot(tmp_path)
    assert len(original) == 3
    assert checkpoint.main(["--check"]) == 0
    assert _snapshot(tmp_path) == original
    assert checkpoint.main([]) == 0
    assert _snapshot(tmp_path) == original

    path = tmp_path / "data/games/gen2_gold/write_checkpoint.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["titles"]["gold"]["runtime_authorized"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    corrupt = _snapshot(tmp_path)
    assert checkpoint.main(["--check"]) == 1
    assert _snapshot(tmp_path) == corrupt

    def fail_on_last_title(title, root):
        if title == "silver":
            raise ValueError("required source unavailable")
        return view(title)

    monkeypatch.setattr(checkpoint, "load_context", fail_on_last_title)
    assert checkpoint.main([]) == 1
    assert _snapshot(tmp_path) == corrupt
