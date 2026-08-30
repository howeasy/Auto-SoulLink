"""Every adapter's sprite_html must carry the class the rest of the app selects on.

server.py:1855 does `sprite_tag.replace('class="mon-sprite"', 'class="enc-sprite"')` to
shrink a sprite for the encounter table, and the stylesheet keys on both classes to grey
out a fainted mon, size a focus overlay and crop a tombstone. An adapter that emits a bare
<img> gets none of it -- the replace silently no-ops and every rule fails to match, so the
sprite renders at the wrong size with no styling and nothing errors.

Four of the six adapters had this wrong (Gen 1, 2, 4, 5); it was found by review, not by a
test, because the failure is entirely visual. One invariant over every registered adapter
is cheaper than noticing it again on the next generation.
"""
from __future__ import annotations

import pytest

from server.adapters import available_game_ids, get_adapter


def _adapters():
    out = []
    for rom_type in available_game_ids():
        try:
            out.append((rom_type, get_adapter(rom_type)))
        except Exception:                      # noqa: BLE001 — an adapter needing args
            continue
    return out


def test_there_are_adapters_to_check():
    """Control: every parametrised test below vacuously passes on an empty list."""
    assert len(_adapters()) >= 3


@pytest.mark.parametrize("rom_type,adapter", _adapters(), ids=lambda x: x if isinstance(x, str) else "")
def test_sprite_html_carries_the_mon_sprite_class(rom_type, adapter):
    html = adapter.sprite_html(25)          # Pikachu exists in every generation
    if not html:
        pytest.skip(f"{rom_type} renders no sprite at all")
    assert 'class="mon-sprite"' in html, (
        f"{rom_type}.sprite_html has no mon-sprite class — the enc-sprite swap in "
        f"server.py will no-op and every CSS rule keyed on it is bypassed")


@pytest.mark.parametrize("rom_type,adapter", _adapters(), ids=lambda x: x if isinstance(x, str) else "")
def test_the_enc_sprite_swap_actually_swaps(rom_type, adapter):
    """Asserted the way server.py does it, not on the class name in isolation: this is
    the operation that was silently doing nothing."""
    html = adapter.sprite_html(25)
    if not html:
        pytest.skip(f"{rom_type} renders no sprite at all")
    swapped = html.replace('class="mon-sprite"', 'class="enc-sprite"')
    assert swapped != html, f"{rom_type}: the enc-sprite swap changed nothing"
