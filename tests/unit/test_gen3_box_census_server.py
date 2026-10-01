"""KEY-SCOPE-5, server half for Gen 3: the foundation stamps `pc_boxes_generation`
(lua/gen3/client.lua, Emerald T3 f4ec8c85), so its box census is generation-based."""
from __future__ import annotations

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer

BOX = [{"box": 0, "slot": 0, "key": "9666:BF1E:5F", "species_id": 95}]


@pytest.fixture(params=[(False, "firered"), (True, "firered_rr")], ids=["frlg", "rr"])
def srv(request, tmp_path):
    is_rr, rom_type = request.param
    server = SLinkServer(data_dir=str(tmp_path))
    server.state.adapter = server.adapter = Gen3Adapter(is_rr=is_rr, rom_type=rom_type)
    return server


def _census(srv, **msg):
    srv._ingest_box_census("a", msg)
    return srv.box_census["a"]["boxes"]


def test_gen3_is_census_capable_without_having_sent_a_generation(srv):
    assert Gen3Adapter().reports_box_census()
    srv._ingest_box_census("a", {"event": "hello", "party": []})     # no generation yet
    assert srv._census_capable("a")


def test_a_stamped_snapshot_updates_the_census_and_older_ones_never_replace_it(srv):
    assert _census(srv, event="hello", party=[], pc_boxes=BOX, pc_boxes_generation=3) == BOX
    assert _census(srv, event="tick", pc_boxes=[], pc_boxes_generation=2) == BOX      # older: ignored
    assert _census(srv, event="tick", party=[], pc_boxes=[], pc_boxes_generation=4) == []


def test_a_snapshot_without_a_generation_makes_the_census_stale(srv):
    assert _census(srv, event="tick", party=[], pc_boxes=BOX, pc_boxes_generation=1) == BOX
    assert _census(srv, event="tick", party=[], pc_boxes=BOX) is None
    # a legacy (non-stamping) foundation keeps presence semantics instead
    srv.state.adapter = srv.adapter = type("Legacy", (Gen3Adapter,), {"reports_box_census": lambda s: False})()
    srv._ingest_box_census("a", {"event": "hello", "party": []})
    assert not srv._census_capable("a")
