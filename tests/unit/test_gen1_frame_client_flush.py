"""Verified control responses release pending readonly closure, never frames."""

from tests.unit.test_client_state_store import runtime as runtime
from tests.unit.test_gen1_frame_client import setup


def test_verified_response_can_close_even_before_runtime_clears_request_marker(runtime):
    setup(runtime, auxiliary=True)
    runtime.execute('''
        grant(20);emit=true;rpc_inflight=true
        assert(tick()and frame==101 and completion()==nil)
        assert(client:blocks_commands()and progress_store:read().progress.active.signals[1].frame==101)
        client:control(binding) -- The real caller has just accepted this response.
        assert(client:flush_closed_after_response()and frame==101)
        assert(completion().payload.receipt.steps==1)
        assert(client:flush_closed_after_response()and #journal:pending_events()==1)
    ''')


def test_response_flush_cannot_consume_an_unexpired_frame_credit(runtime):
    setup(runtime, auxiliary=True)
    runtime.execute('''
        grant(20)
        assert(client:flush_closed_after_response()and frame==100 and completion()==nil)
        assert(client.window:status().remaining==20)
        assert(tick()and frame==101)
    ''')


def test_response_flush_near_deadline_closes_exact_used_prefix(runtime):
    setup(runtime, auxiliary=True)
    runtime.execute('''
        grant(20);assert(tick()and frame==101);now=.96;rpc_inflight=true
        assert(client:flush_closed_after_response()and frame==101)
        assert(completion().payload.receipt.before==100 and completion().payload.receipt.after==101)
    ''')
