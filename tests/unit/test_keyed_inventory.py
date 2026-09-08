import pytest

from server.keyed_inventory import compare
from server.protocol_journal import JournalError


def test_comparison_is_order_independent_detached_and_does_not_guess_rekeys():
    before = [{'key': 'one', 'slot': 0}, {'key': 'two', 'slot': 1}]
    after = [{'key': 'three', 'slot': 1}, {'key': 'one', 'slot': 1}]
    value = compare(before, after, limit=6)
    assert value == compare(before[::-1], after[::-1], limit=6)
    assert value['added'] == [after[0]] and value['removed'] == [before[1]]
    assert value['matched'] == [{'key': 'one', 'before': before[0], 'after': after[1]}]
    value['matched'][0]['before']['slot'] = 99
    assert before[0]['slot'] == 0


@pytest.mark.parametrize('rows', [None, {}, [None], [{'key': ''}], [{'key': 'x\n'}],
    [{'key': 'x'}, {'key': 'x'}], [{'key': 'x', 'bad': object()}]])
def test_malformed_or_ambiguous_rows_are_refused(rows):
    with pytest.raises(JournalError):
        compare(rows, [], limit=6)
    with pytest.raises(JournalError):
        compare([], rows, limit=6)


@pytest.mark.parametrize('limit', [0, True, -1, 4097, 1.5])
def test_comparison_capacity_must_be_explicit_and_bounded(limit):
    with pytest.raises(JournalError):
        compare([], [], limit=limit)


def test_inventory_cannot_exceed_capacity():
    with pytest.raises(JournalError):
        compare([{'key': 'a'}, {'key': 'b'}], [], limit=1)
