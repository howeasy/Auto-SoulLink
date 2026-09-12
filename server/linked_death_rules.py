"""Run-over bookkeeping beside the shared engine: deaths themselves are engine faint events."""
from server.state import LinkStatus


def update_run_over(state):
    if (all(state.pokeballs_obtained.values()) and not state.pending_captures
            and any(link.a and link.b for link in state.links)
            and not any(link.status==LinkStatus.ALIVE for link in state.links)):
        state.run_over=True
