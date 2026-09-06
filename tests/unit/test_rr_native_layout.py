"""Permanent shared-layout generation and rejection checks; no ownership inference."""
import copy
import json
import re

import pytest
from lupa import LuaRuntime

from patch.tools import native_layout as layout

BASELINE = {
    "mailbox": (0, 64), "swap": (64, 8), "ghost": (80, 44), "armed_move": (192, 8),
    "peer_interact": (208, 4), "trade_npc": (212, 4), "calc_off": (216, 1),
    "script": (224, 32), "text": (256, 256), "blob": (512, 600),
    "ghost_palette": (1120, 32), "ui": (1152, 12), "choices": (1168, 112),
    "battle_notif": (1280, 8), "events": (1296, 52), "info": (1348, 264),
}


def test_schema_preserves_every_baseline_region_and_accounts_for_all_bytes():
    d = layout.load()
    assert {r["name"]: (r["offset"], r["size"]) for r in d["regions"]} == BASELINE
    assert sum(r["size"] for r in d["regions"]) + sum(row[1] for row in d["reserved_intervals"]) == 2048
    assert d["arena"]["ownership"].startswith("UNRESOLVED")
    assert d["structures"]["NativeDescriptor"]["size"] == 156
    assert d["structures"]["GhostState"]["size"] == 44


def test_all_committed_generated_outputs_are_current():
    layout.generate(check=True)


def test_all_shared_native_types_invoke_their_generated_assertions():
    source = "\n".join((layout.ROOT / path).read_text() for path in
                       ("patch/src/handlers.c", "patch/src/native_mailbox.h"))
    for name in layout.load()["structures"]:
        assert f"SLINK_ASSERT_{layout.macro(name)}({name});" in source


def test_active_companion_consumers_have_no_independent_region_address_literals():
    d = layout.load()
    paths = ["lua/mailbox.lua", "lua/clients/gen3_frlge_client.lua", "lua/peer_ghost_npc.lua",
             "lua/tests/rr/ghost_resource_probe.lua", "lua/tests/rr/ghost_running_probe.lua",
             "patch/src/handlers.c", "patch/src/native_mailbox.h", "patch/src/native_mailbox.c", "patch/tools/build.py"]
    for relative in paths:
        text = (layout.ROOT / relative).read_text(encoding="utf-8")
        if relative.endswith((".c", ".h")):
            text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        elif relative.endswith(".lua"):
            text = re.sub(r"--[^\n]*", "", text)
        else:
            text = re.sub(r"#[^\n]*", "", text)
        for token in re.findall(r"0x[0-9a-fA-F]+", text):
            value = int(token, 16)
            assert not any(d["arena"]["address"] + r["offset"] <= value < d["arena"]["address"] + r["offset"] + r["size"]
                           for r in d["regions"]), (relative, token)


def test_generated_lua_matches_every_region_and_struct_offset_without_memory_access():
    d = layout.load()
    module = LuaRuntime().execute(layout.render(d)[layout.OUTPUTS[1]])
    assert module.sha256 == layout.fingerprint(d)
    for region in d["regions"]:
        got = module.regions[region["name"]]
        assert (got.address, got.size, got.alignment) == (d["arena"]["address"] + region["offset"], region["size"], region["alignment"])
    for name, struct in d["structures"].items():
        assert module.structures[name].size == struct["size"]
        for field in struct["fields"]:
            assert module.structures[name].offsets[field["name"]] == field["offset"]
            assert module.structures[name].bytes[field["name"]] == layout.WIDTHS[field["type"]] * field["count"]


@pytest.mark.parametrize("path,value", [
    (("arena", "address"), 0x0201B800), (("arena", "size"), 2049),
    (("arena", "ownership"), "free"), (("rom", "code_base"), 0x08378CA8),
    (("revision",), True), (("constants", "abi"), 1), (("constants", "reservation_offset"), 16),
    (("capabilities", "payload_leases"), 1), (("capabilities", "payload_leases"), 3),
    (("structures", "GhostState", "size"), 48), (("structures", "GhostState", "fields", 6, "offset"), 8),
    (("structures", "Mailbox", "fields", 0, "count"), 2), (("structures", "Mailbox", "fields", 0, "type"), "u64"),
    (("regions", 1, "offset"), 60), (("regions", 10, "alignment"), 3),
    (("regions", 1, "size"), True), (("regions", 1, "struct"), "Missing"),
    (("reserved_intervals", 0, 1), 7), (("reserved_intervals", 7, 1), 437),
    (("context_fields", "callback2"), 15),
    (("structures", "SlinkInfo", "alignment"), True), (("regions", 1, "struct"), []),
    (("structures", "Mailbox", "fields", 0, "type"), {}),
    (("structures", "SlinkInfo", "fields", 8, "dimensions"), [8, 33]),
])
def test_invalid_or_unreviewed_layout_is_rejected(path, value):
    d = copy.deepcopy(layout.load())
    target = d
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(layout.LayoutError):
        layout.validate(d)


@pytest.mark.parametrize("change", ["omit_lifecycle", "reorder_ghost_tail", "detach_ghost", "shrink_choices"])
def test_revision_one_cannot_hide_actual_native_members_or_buffer_extent(change):
    d = copy.deepcopy(layout.load())
    if change == "omit_lifecycle":
        assert d["structures"]["GhostState"]["fields"].pop()["name"] == "lifecycle"
    elif change == "reorder_ghost_tail":
        fields = d["structures"]["GhostState"]["fields"]
        fields[-2], fields[-1] = fields[-1], fields[-2]
        fields[-2]["offset"], fields[-1]["offset"] = 42, 43
    elif change == "detach_ghost":
        ghost = next(r for r in d["regions"] if r["name"] == "ghost")
        ghost.update(struct=None, size=1, alignment=1)
        d["reserved_intervals"].append([81, 43])
    elif change == "shrink_choices":
        choices = next(r for r in d["regions"] if r["name"] == "choices")
        choices["size"] = 96
        d["reserved_intervals"].append([1264, 16])
    with pytest.raises(layout.LayoutError, match="retained v1"):
        layout.validate(d)


def test_duplicate_or_unknown_schema_keys_are_rejected(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text('{"schema":"a","schema":"b"}')
    with pytest.raises(layout.LayoutError, match="duplicate"):
        layout.load(path)
    d = layout.load()
    d["invented_address"] = 0x0201B800
    with pytest.raises(layout.LayoutError, match="unexpected"):
        layout.validate(d)


def test_fingerprint_covers_ghost_and_reserved_ownership_beyond_mailbox_header():
    d = layout.load()
    changed = copy.deepcopy(d)
    changed["arena"]["ownership"] += "; pending runtime gate"
    assert layout.fingerprint(d) != layout.fingerprint(changed)
    changed = copy.deepcopy(d)
    changed["structures"]["GhostState"]["fields"][1]["name"] = "changed"
    assert layout.fingerprint(d) != layout.fingerprint(changed)
    assert layout.fingerprint(d) == layout.fingerprint(json.loads(json.dumps(d, sort_keys=True)))
    assert layout.render(d) == layout.render(json.loads(json.dumps(d, sort_keys=True)))


def test_check_fails_on_missing_or_edited_generated_file_and_never_repairs_it(tmp_path):
    source = tmp_path / layout.SOURCE
    source.parent.mkdir(parents=True)
    source.write_bytes((layout.ROOT / layout.SOURCE).read_bytes())
    with pytest.raises(layout.LayoutError, match="stale"):
        layout.generate(tmp_path, check=True)
    layout.generate(tmp_path)
    target = tmp_path / layout.OUTPUTS[1]
    target.write_text("return {bad=true}\n")
    with pytest.raises(layout.LayoutError, match="stale"):
        layout.generate(tmp_path, check=True)
    assert target.read_text() == "return {bad=true}\n"


def test_crlf_checkout_generated_text_is_equivalent(tmp_path):
    source = tmp_path / layout.SOURCE
    source.parent.mkdir(parents=True)
    source.write_bytes((layout.ROOT / layout.SOURCE).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    layout.generate(tmp_path)
    for path in layout.OUTPUTS:
        target = tmp_path / path
        target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    assert layout.fingerprint(layout.generate(tmp_path, check=True)) == layout.fingerprint(layout.load())
