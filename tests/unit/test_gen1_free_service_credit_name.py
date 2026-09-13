"""An independent New Game credit run cannot prescribe this run's trainer name."""

import pytest

from tests.live.test_gen1_free_service import current_name_binding


def test_name_is_bound_to_its_own_checked_enrollment_not_the_old_credit_run():
    current_name = "9184835080928750898082"  # RED in the current R/B run
    old_credit_name = "98848B8B8E965080928750"  # YELLOW in the old R/B credit run
    assert current_name != old_credit_name
    last = {"fields": {"name": current_name}}
    initial = {"observation": {"source": {"fields": {"name": current_name}}},
               "metadata": {"save_identity": {"ot_id": "C515", "trainer_name": "RED"}}}
    status = {"context": {"save_identity": {"ot_id": "C515", "trainer_name": "RED"}}}

    assert current_name_binding(last, initial, status) == {"current": current_name, "enrollment_bound": True}
    with pytest.raises(AssertionError):
        current_name_binding({"fields": {"name": old_credit_name}}, initial, status)
    with pytest.raises(AssertionError):
        current_name_binding(last, initial, {"context": {"save_identity": {"ot_id": "C515", "trainer_name": "YELLOW"}}})
