"""Actual generated launchers for reproduced UPR final pairs; execution stays held."""
import os
import pytest
from tests.live.test_gen1_launcher import run_launcher_pair

pytestmark=[pytest.mark.live,pytest.mark.slow,
            pytest.mark.skipif(os.environ.get("SLINK_LIVE")!="1",reason="explicit live emulator lane required")]


@pytest.mark.parametrize("variants",[("red","blue"),("blue","yellow"),("yellow","yellow")],ids=lambda pair:"-".join(pair))
def test_reproduced_final_pair_launches_with_exact_metadata_and_independent_holds(variants):
    run_launcher_pair(variants,randomized=True)
