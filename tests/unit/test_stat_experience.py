"""Shared integer stat arithmetic boundaries used by the RBY native oracle."""

import pytest

from server.stat_experience import calculate_stat, split_dvs


@pytest.mark.parametrize(
    "experience,expected", [(0, 205), (8, 205), (15, 206), (16, 206), (65535, 268)]
)
def test_stat_experience_rounding_boundaries(experience, expected):
    assert calculate_stat(100, 0, 100, experience) == expected


def test_hp_uses_the_distinct_level_bonus_and_capped_experience_term():
    assert calculate_stat(255, 15, 100, 65535, hp=True) == 713
    assert calculate_stat(255, 15, 100, 65535) == 608


@pytest.mark.parametrize(
    "packed,expected",
    [(0xFFFF, (15, 15, 15, 15, 15)), (0xAAAA, (0, 10, 10, 10, 10)), (0x1234, (10, 1, 2, 3, 4))],
)
def test_hp_dv_comes_from_the_low_bit_of_each_stored_dv(packed, expected):
    assert split_dvs(packed) == expected


@pytest.mark.parametrize(
    "arguments",
    [
        (0, 0, 1, 0),
        (256, 0, 1, 0),
        (1, 16, 1, 0),
        (1, 0, 0, 0),
        (1, 0, 101, 0),
        (1, 0, 1, 65536),
        (1, 0, True, 0),
    ],
)
def test_out_of_domain_values_are_refused(arguments):
    with pytest.raises(ValueError):
        calculate_stat(*arguments)
