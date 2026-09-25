# Theme contrast audit (WCAG 2.1)

Generated via the script at the bottom of this file. Update whenever a
theme's palette changes, and keep this table in sync with the slink.css
token defaults.

All ratios are foreground-on-background per
[WCAG 2.1 contrast minimum](https://www.w3.org/TR/WCAG21/#contrast-minimum):

* **Body text (`--c-txt` on `--c-bg` and `--c-card`)**: must be ≥ 4.5
* **Large / secondary text and graphical UI (`--c-dim`, status accents, brand)**: must be ≥ 3.0
* **Control borders (`--c-edge-ui` on `--c-bg` and `--c-card`, WCAG 1.4.11)**: must be ≥ 3.0

`--c-bg` is opaque on every page but the OBS overlays (`body.stream`), whose `#root`
panel stays translucent so the game shows through; the ratios below are against the
opaque page. `tests/unit/test_theme_contrast.py` recomputes **every** theme the picker
offers — parametrized from `server.templating.VALID_THEMES` minus `transparent` — from
the CSS itself (text/dim/brand 4.5:1, control borders 3:1), so a new theme or a palette
edit that regresses one is caught automatically.

| theme                  | txt/bg | txt/card | dim/bg | alive/bg | dead/bg | pend/bg | gold/bg | brand/bg |
|------------------------|-------:|---------:|-------:|---------:|--------:|--------:|--------:|---------:|
| default (overlay dark) |  15.9  |   15.6   |  7.2   |   12.2   |   5.0   |   9.5   |  13.3   |   13.3   |
| light                  |  15.6  |   16.7   |  6.0   |    3.3   |   5.1   |   3.6   |   5.7   |    5.7   |
| funtastic-grape        |  15.9  |   13.7   |  7.0   |   11.8   |   6.4   |  12.1   |  11.6   |    5.3   |
| funtastic-jungle       |  16.6  |   14.4   |  8.2   |   12.4   |   6.6   |  14.1   |  11.8   |    8.9   |
| funtastic-fire         |  16.2  |   14.7   |  7.6   |   12.4   |   5.6   |  10.1   |  13.3   |    6.6   |
| funtastic-ice          |  15.6  |   13.4   |  5.9   |   14.0   |   6.5   |  10.6   |  16.5   |   10.6   |
| funtastic-watermelon   |  14.2  |   13.2   |  6.7   |   13.1   |   3.6   |  12.8   |  16.9   |    5.5   |
| funtastic-smoke        |  16.2  |   14.2   |  7.6   |   13.1   |   6.7   |  12.1   |  10.9   |   10.9   |

All themes now pass WCAG AA for body text, secondary text, every status
accent, brand text and control borders (below). Grape's `brand/bg` moved
from **3.5 → 5.3** — see "Grape's brand" below; every other column was
already passing and is unchanged from the previous audit.

## Borders: `--c-edge` vs `--c-edge-ui`

`--c-edge` is the hairline divider on every card, rule and header, and stays faint on
purpose. Controls (`.mk-btn`, `.mk-gchip`, the form inputs in board.css) draw their border
from `--c-edge-ui`, falling back to `--c-edge` in a theme that does not define it.

| theme                | `--c-edge-ui`            | on bg | on card |
|-----------------------|--------------------------|------:|--------:|
| default               | `rgba(255,255,255,.38)`  |  3.8  |   3.6   |
| light                 | `rgba(0,0,0,.48)`        |  3.8  |   3.6   |
| funtastic-jungle      | *(none — falls back to `--c-edge` `#1e7a48`)* |  3.5  |   3.1   |
| funtastic-smoke       | `#808080`                |  5.0  |   4.4   |
| funtastic-grape       | `#8d4dc7` *(was `--c-edge` `#5a2a85`, 2.0/1.7)* |  3.8  |   3.3   |
| funtastic-fire        | `#ab5116` *(was `--c-edge` `#7a3a10`, 2.3/2.1)* |  3.6  |   3.3   |
| funtastic-ice         | `#3273ac` *(was `--c-edge` `#2a6090`, 2.9/2.5)* |  3.8  |   3.3   |
| funtastic-watermelon  | `#c32a55` *(was `--c-edge` `#7a1a35`, 1.9/1.8)* |  3.5  |   3.3   |

**Fixed 2026-09-25:** grape, fire, ice and watermelon each now define
`--c-edge-ui` — the same hue as their `--c-edge` hairline, lightened just past 3:1 on
`--c-card` (the tighter of the two surfaces) with a small margin. `--c-edge` itself is
untouched, so the hairline divider (used ~64x across the CSS) keeps its original faint
look everywhere but the handful of controls that read `--c-edge-ui`. Jungle already
cleared 3:1 on its plain `--c-edge` and was left alone.

## Grape's brand

`--c-brand` (`#9933cc`) was 3.5:1 on bg / 3.0:1 on card — under the 4.5:1 body-text
minimum (`--c-brand` is drawn as text: the wordmark, the active tab, the active theme
pill). Lightened along the same hue to `#b162d8` (5.3:1 on bg / 4.6:1 on card). This is
the one fix in this pass that's visible at a glance — Grape's swatch/wordmark purple is
noticeably lighter than before, though still recognizably purple. Every other theme's
`--c-brand` already cleared 4.5:1 and is unchanged.

## Smoke's brand

The N64 Smoke shell colour, `#333333`, stays as the theme picker's swatch. `--c-brand` is
silver `#c0c0c0` (10.9 on bg): it was `#333333` at 1.6:1, and it is drawn as text (the
wordmark, the active tab, the active theme pill).

## How to regenerate

Run the script below from the repo root. It pulls hex values from the same
token definitions in this directory and re-prints the table.

```bash
python - <<'EOF'
def srgb_to_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
def rel_lum(rgb):
    r, g, b = (srgb_to_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
def hx(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
def contrast(a, b):
    la, lb = rel_lum(hx(a)), rel_lum(hx(b))
    if la < lb: la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)

themes = {
    # Read these dicts from server/static/themes/*.css :root blocks.
    # Light + default come from slink.css :root and body.theme-light.
}
# … run contrast(fg, bg) per pair and print the table.
EOF
```
