"""Production downloaded launchers: paired memorial writes, flushes and ACKs."""

import pytest

from tests.live.test_gen1_launcher import pytestmark as pytestmark, run_launcher_pair


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_generated_launchers_complete_both_owned_memorial_save_receipts(variants):
    run_launcher_pair(variants, enrollment=True, faint=True, memorial=True)


@pytest.mark.parametrize('cut',[1,80])
def test_actual_partial_memorial_requires_repair_permit_and_finishes(cut):
    run_launcher_pair(('yellow','yellow'),enrollment=True,faint=True,memorial=True,memorial_fault=cut)


def test_same_core_reconnect_before_save_preserves_prepared_death_and_completes():
    run_launcher_pair(('yellow','yellow'),enrollment=True,faint=True,memorial=True,reconnect_memorial=True)
