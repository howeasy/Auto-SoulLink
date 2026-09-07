"""Shared binary write-set composition refuses drift before any changed output."""

import pytest

from server.patch_plan import PatchSpan, apply_spans


def test_multiple_components_compose_without_mutating_input_or_unowned_bytes():
    source = b"abcdefghABCDEFGH"
    result = apply_spans(
        source,
        [PatchSpan(9, b"BC", b"12", "second"), PatchSpan(1, b"bc", b"34", "first")],
        protected=((4, 8),),
        bank_size=8,
    )
    assert result == b"a34defghA12DEFGH" and source == b"abcdefghABCDEFGH"


@pytest.mark.parametrize(
    "spans,protected,bank_size",
    [
        ([PatchSpan(1, b"bc", b"12", "first"), PatchSpan(2, b"c", b"2", "overlap")], (), None),
        ([PatchSpan(1, b"bc", b"12", "first"), PatchSpan(9, b"XX", b"34", "late drift")], (), None),
        ([PatchSpan(1, b"bc", b"12", "protected")], ((2, 4),), None),
        ([PatchSpan(7, b"hA", b"12", "bank")], (), 8),
        ([PatchSpan(15, b"HG", b"12", "outside")], (), None),
        ([PatchSpan(1, b"bc", b"123", "resize")], (), None),
        ([PatchSpan(True, b"b", b"1", "bool offset")], (), None),
        ([PatchSpan(1, b"b", b"1", "range")], ((0, 20),), None),
    ],
)
def test_invalid_or_conflicting_complete_write_set_is_refused(spans, protected, bank_size):
    source = b"abcdefghABCDEFGH"
    with pytest.raises(ValueError):
        apply_spans(source, spans, protected=protected, bank_size=bank_size)
    assert source == b"abcdefghABCDEFGH"
