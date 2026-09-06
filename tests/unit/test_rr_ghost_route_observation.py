"""Read-only route-observation assertions; synthetic API fixture, not route proof."""
from pathlib import Path

import pytest

from tests.unit.test_rr_ghost_resource_probe import ProbeHarness

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "lua/tests/rr/ghost_route_observation.lua"


def setup(tmp_path):
    h = ProbeHarness(tmp_path)
    h.write(0x02036E38 + 16, 1, 2)
    h.write(0x02036E38 + 18, 1, 2)
    h.write(0x02036E38 + 20, 1, 2)
    h.write(0x02036E38 + 22, 1, 2)
    h.write(0x02036DFC, 0x08130000, 4)
    h.write(0x08130000, 2, 4)
    h.write(0x08130004, 2, 4)
    h.write(0x08130010, 0x08131000, 4)
    h.write(0x08130014, 0x08131100, 4)
    h.write(0x08131014, 0x08132000, 4)
    h.write(0x08131114, 0x08133000, 4)
    h.write(0x03005040, 2, 4)
    h.write(0x03005044, 2, 4)
    h.write(0x03005048, 0x02018000, 4)
    for i, word in enumerate((0x3001, 0x3402, 0x3002, 0x3003)):
        h.write(0x02018000 + i * 2, word, 2)
    h.write(0x08132000 + 2 * 4, 0x01000002, 4)
    return h


def test_observation_captures_real_api_bytes_without_ram_writes_or_mailbox_requests(tmp_path):
    h = setup(tmp_path)
    before = dict(h.ram)
    h.lua.execute(SOURCE.read_text())(h.context)
    out = h.report.evidence.runtime
    assert list(out.map.grid_words.values()) == [0x3001, 0x3402, 0x3002, 0x3003]
    assert out.map.metatile_attributes[3] == 0x01000002
    assert out.player.x == out.player.y == 1
    assert h.ram == before and h.posts == [] and h.frame == 0
    assert out.release_ready is False and "map_observation_complete" in h.assertions
    assert Path(out.screenshot.path).exists()


@pytest.mark.parametrize("address,value", [(0x03005040, 129), (0x03005048, 0x0203FFFE),
                                          (0x02036DFC, 0x02012340), (0x030030F4, 0),
                                          (0x02036E38 + 20, 0)])
def test_unsafe_or_incoherent_observation_fails_without_controls_or_writes(tmp_path, address, value):
    h = setup(tmp_path)
    h.write(address, value, 4 if address != 0x02036E38 + 20 else 2)
    before = dict(h.ram)
    with pytest.raises(AssertionError, match="route_"):
        h.lua.execute(SOURCE.read_text())(h.context)
    assert h.ram == before and h.posts == [] and h.frame == 0
