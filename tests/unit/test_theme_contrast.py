"""WCAG contrast of the theme tokens, computed from the CSS itself so a palette edit that
breaks it fails here: body text 4.5:1 (1.4.3), control borders 3:1 (1.4.11).

Only the themes fixed in the 2026-09 audit are pinned; server/static/themes/CONTRAST.md has
the full table."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "server" / "static"


def _block(css_file: str, selector: str) -> dict[str, str]:
    css = (STATIC / css_file).read_text(encoding="utf-8")
    m = re.search(r"(?:^|[\s}])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} not in {css_file}"
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)))


def _rgba(v: str) -> tuple[float, float, float, float]:
    v = v.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (*(int(h[i:i + 2], 16) for i in (0, 2, 4)), 1.0)
    nums = [float(n) for n in re.findall(r"[\d.]+", v)]
    return (*nums[:3], nums[3] if len(nums) > 3 else 1.0)


def _over(fg, bg):
    a = fg[3]
    return (*(a * f + (1 - a) * b for f, b in zip(fg[:3], bg[:3], strict=True)), 1.0)


def _lum(c):
    def lin(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(x) for x in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _default():
    return {**_block("slink.css", ":root"), **_block("themes/default.css", ":root"),
            **_block("themes/default.css", ":root:not(:has(body.stream))")}


THEMES = {
    "default": _default,
    "light": lambda: {**_default(), **_block("slink.css", "body.theme-light"),
                      **_block("themes/light.css", "body.theme-light"),
                      **_block("themes/light.css", "body.theme-light:not(.stream)")},
    "funtastic-smoke": lambda: _block("themes/funtastic-smoke.css", ":root"),
}


@pytest.mark.parametrize("theme", THEMES)
def test_theme_contrast(theme):
    t = THEMES[theme]()
    bg = _rgba(t["--c-bg"])
    assert bg[3] == 1.0, "the page background is opaque, so contrast does not depend on the backdrop"
    card = _over(_rgba(t["--c-card"]), bg)
    edge_ui = _over(_rgba(t["--c-edge-ui"]), card)
    for surface in (bg, card):
        assert _ratio(edge_ui, surface) >= 3.0, "control border"
        for tok in ("--c-txt", "--c-dim", "--c-brand"):
            fg = _over(_rgba(t[tok]), surface)
            assert _ratio(fg, surface) >= 4.5, (tok, round(_ratio(fg, surface), 2))
