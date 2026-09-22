"""The committed Gen 3 write checkpoints are pinned facts, not prose.

Every anchor must still be at its offset in the ROM it claims, every address must still be the
.sym value it claims, and the generator must reproduce the committed bytes exactly.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import gen_gen3_write_checkpoint as G  # noqa: E402

PACK_TITLES = [(pack, title) for pack, titles in G.PACKS.items() for title in titles]


def load(pack: str) -> dict:
    return json.loads(G.out_path(pack).read_text(encoding="utf-8"))


def rom_or_skip(pack: str, title: str, kind: str) -> bytes:
    path, _ = G.ROMS[(pack, title, kind)]
    if not path.exists():
        pytest.skip(f"ROM not present at {path}")
    return G.load_rom(pack, title, kind)


@pytest.mark.parametrize("pack,title", PACK_TITLES)
def test_anchor_bytes_are_in_every_rom(pack: str, title: str) -> None:
    block = load(pack)[title]
    assert block["anchors"], "a checkpoint with no ROM anchor cannot be re-verified"
    for kind in G.PACKS[pack][title][1]:
        rom = rom_or_skip(pack, title, kind)
        for name, anchor in block["anchors"].items():
            want = bytes.fromhex(anchor["expected_hex"][kind])
            off = anchor["rom_offset"]
            assert len(want) == anchor["length"], f"{title}/{kind}/{name}: length disagrees"
            assert rom[off:off + len(want)] == want, f"{title}/{kind}/{name} @ {off:#x}"


@pytest.mark.parametrize("pack,title", PACK_TITLES)
def test_every_symbol_address_equals_the_sym(pack: str, title: str) -> None:
    block = load(pack)[title]
    syms = G.parse_sym(G.SYM_DIR / block["sym"])
    seen = 0
    for entry in list(block["anchors"].values()) + list(block["predicates"].values()) \
            + list(block["pointers"].values()) + [block["tasks"]]:
        symbol = entry.get("symbol")
        if symbol and "address" in entry and entry.get("source", "").startswith("profile.") is False:
            assert entry["address"] == syms[symbol][0], f"{title}: {symbol}"
            seen += 1
        if "expect_symbol" in entry:  # gMain holds a Thumb function pointer
            assert entry["expect"] == syms[entry["expect_symbol"]][0] | 1
            seen += 1
    assert seen >= 10, "the walk found almost nothing -- the file shape changed"


@pytest.mark.parametrize("pack,title", PACK_TITLES)
def test_anchor_offsets_are_inside_their_symbol(pack: str, title: str) -> None:
    block = load(pack)[title]
    syms = G.parse_sym(G.SYM_DIR / block["sym"])
    for name, anchor in block["anchors"].items():
        addr, size = syms[anchor["symbol"]]
        start = G.ROM_BASE + anchor["rom_offset"]
        assert addr <= start and start + anchor["length"] <= addr + size, f"{title}/{name}"


@pytest.mark.parametrize("pack,title", PACK_TITLES)
def test_allowed_tasks_are_even_thumb_free_addresses(pack: str, title: str) -> None:
    tasks = load(pack)[title]["tasks"]
    allowed = tasks["allowed_overworld_tasks"]
    assert set(allowed) == set(G.ALLOWED_TASKS)
    syms = G.parse_sym(G.SYM_DIR / load(pack)[title]["sym"])
    for name, address in allowed.items():
        assert address % 2 == 0, f"{title}/{name}: Thumb bit must be stripped"
        assert address == syms[name][0]
    assert tasks["struct_size"] * tasks["count"] == syms["gTasks"][1]


@pytest.mark.parametrize("pack,title", PACK_TITLES)
def test_version_and_fail_closed_shape(pack: str, title: str) -> None:
    block = load(pack)[title]
    assert block["version"] == "gen3-overworld-v1"
    # the predicates the checkpoint cannot do without
    for key in ("callback1", "callback2", "in_battle", "palette_fade_active",
                "field_controls_locked", "script_context_status", "save_dialog_cb",
                "link_callback"):
        assert key in block["predicates"], f"{title}: missing predicate {key}"
    assert block["pointers"], f"{title}: no SaveBlock pointers to revalidate"


def census_rows(path: str) -> dict[int, int]:
    """The `final` section's `R15=0x... xN` rows of a frame-end census."""
    text = (G.ROOT / path).read_text(encoding="utf-8").split("final at frame", 1)[1]
    return {int(m[0], 16): int(m[1]) for m in re.findall(r"R15=(0x[0-9A-F]+) x(\d+)", text)}


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_frlg_cpu_is_parked_in_wait_for_vblank(title: str) -> None:
    cpu = load("gen3_frlg")[title]["cpu"]
    addr, size = G.parse_sym(G.SYM_DIR / G.PACKS["gen3_frlg"][title][0])["WaitForVBlank"]
    assert (cpu["pc_min"], cpu["pc_max"]) == (addr, addr + size - 1)
    assert cpu["mode"] == 0x1F and cpu["thumb"] == 1 and cpu["symbol"] == "WaitForVBlank"
    if title == "leafgreen":  # no LG census exists; FR's observation must not be copied over
        assert "observed_pc" not in cpu and "census" not in cpu
        return
    rows = census_rows(cpu["census"])
    rom_pcs = {pc for pc in rows if pc >= G.ROM_BASE}
    assert rom_pcs and all(addr <= pc <= cpu["pc_max"] for pc in rom_pcs)
    assert cpu["observed_pc"] == max(rows, key=rows.get)
    # everything else is the BIOS IRQ vector -- refused by the clause, and a small minority
    assert all(pc < 0x4000 for pc in set(rows) - rom_pcs)
    assert sum(rows[pc] for pc in rom_pcs) > 0.9 * sum(rows.values())


def test_rr_cpu_is_the_bios_census() -> None:
    cpu = load("gen3_rr")["radical_red"]["cpu"]
    assert cpu == {"mode": 0x1F, "thumb": 0, "pc_min": 0, "pc_max": 0x3FFF, "observed_pc": 0x1C4,
                   "census": "docs/gen3/probes/census_rr_overworld_2026-09-21.txt"}
    assert census_rows(cpu["census"]) == {0x1C4: 1800}


def test_generator_check_passes_on_the_committed_files() -> None:
    for pack, titles in G.PACKS.items():
        for title in titles:
            for kind in titles[title][1]:
                rom_or_skip(pack, title, kind)
    out = subprocess.run([sys.executable, "tools/gen_gen3_write_checkpoint.py", "--check"],
                         cwd=G.ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
