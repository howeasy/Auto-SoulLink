"""Normal New Game, original frame execution and real server credit accounting."""

import os

import pytest

from server import gen1_frame_control
from tests.live.test_gen1_bootstrap_launcher import run_bootstrap_pair

pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get('SLINK_LIVE') != '1', reason='explicit live emulator lane required')]


@pytest.mark.parametrize('variants,minimum_frames', [(('yellow', 'yellow'), 8), (('red', 'blue'), 8),
                                                    (('yellow', 'yellow'), 120)],
                         ids=['yellow-yellow', 'red-blue', 'yellow-yellow-continuous'])
def test_generated_launcher_moves_under_real_server_credits_then_holds_on_refusal(monkeypatch, variants, minimum_frames):
    original = gen1_frame_control.issue_for_control

    def bounded_test_policy(runtime, player, request):
        entry = runtime.journal.snapshot().state['components'].get('gen1-frame-progress', {}).get(player)
        if entry and entry['ledger']['steps'] >= minimum_frames:
            return None  # Exercise actual control refusal after an accounted range.
        return original(runtime, player, request)

    monkeypatch.setattr(gen1_frame_control, 'issue_for_control', bounded_test_policy)
    run_bootstrap_pair(variants, cold_boot=True, ordinary=True)
