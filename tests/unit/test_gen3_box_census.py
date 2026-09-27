"""KEY-SCOPE-5: only a complete PC scan can publish a fresh generation."""

import pytest

from tests.unit.test_gen3_client import A, B, live


@pytest.fixture(params=[("gen3_frlg", "firered"), ("gen3_rr", "radical_red")])
def world(request):
    return live(*request.param, pids=(A, B))


def test_each_complete_scan_advances_generation(world):
    first = world.client.driver.hello_fields()
    second = world.client.driver.hello_fields()
    assert isinstance(first.pc_boxes_generation, int)
    assert second.pc_boxes_generation == first.pc_boxes_generation + 1


def test_failed_scan_publishes_neither_boxes_nor_generation(world):
    before = world.client.driver.hello_fields().pc_boxes_generation
    original = world.parts.reads.read_box
    world.parts.reads.read_box = lambda index: (None, "injected unreadable box") if index == 7 else original(index)
    hello = world.client.driver.hello_fields()
    tick = world.client.driver.tick_fields()
    assert hello.pc_boxes_generation is None and hello.pc_boxes is None
    assert tick.pc_boxes_generation is None and tick.pc_boxes is None
    assert world.client.state.box_generation == before


def test_success_after_failure_advances_from_last_complete_scan(world):
    before = world.client.driver.hello_fields().pc_boxes_generation
    original = world.parts.reads.read_box
    world.parts.reads.read_box = lambda *_: (None, "injected unreadable box")
    assert world.client.driver.hello_fields().pc_boxes_generation is None
    world.parts.reads.read_box = original
    assert world.client.driver.hello_fields().pc_boxes_generation == before + 1


def test_soft_reset_preserves_session_generation(world):
    before = world.client.driver.hello_fields().pc_boxes_generation
    world.client.driver.on_reset()
    assert world.client.state.box_generation == before
    assert world.client.driver.hello_fields().pc_boxes_generation == before + 1
