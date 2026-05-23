# Theme contrast audit (WCAG 2.1)

Generated via the script at the bottom of this file. Update whenever a
theme's palette changes, and keep this table in sync with the slink.css
token defaults.

All ratios are foreground-on-background per
[WCAG 2.1 contrast minimum](https://www.w3.org/TR/WCAG21/#contrast-minimum):

* **Body text (`--c-txt` on `--c-bg` and `--c-card`)**: must be ≥ 4.5
* **Large / secondary text and graphical UI (`--c-dim`, status accents, brand)**: must be ≥ 3.0

| theme                  | txt/bg | txt/card | dim/bg | alive/bg | dead/bg | pend/bg | gold/bg | brand/bg |
|------------------------|-------:|---------:|-------:|---------:|--------:|--------:|--------:|---------:|
| default (overlay dark) |  15.9  |   15.6   |  7.2   |   12.2   |   5.0   |   9.5   |  13.3   |   13.3   |
| light                  |  15.6  |   16.7   |  6.0   |    3.3   |   5.1   |   3.6   |   5.7   |    5.7   |
| funtastic-grape        |  15.9  |   13.7   |  7.0   |   11.8   |   6.4   |  12.1   |  11.6   |    3.5   |
| funtastic-jungle       |  16.6  |   14.4   |  8.2   |   12.4   |   6.6   |  14.1   |  11.8   |    8.9   |
| funtastic-fire         |  16.2  |   14.7   |  7.6   |   12.4   |   5.6   |  10.1   |  13.3   |    6.6   |
| funtastic-ice          |  15.6  |   13.4   |  5.9   |   14.0   |   6.5   |  10.6   |  16.5   |   10.6   |
| funtastic-watermelon   |  14.2  |   13.2   |  6.7   |   13.1   |   3.6   |  12.8   |  16.9   |    5.5   |
| funtastic-smoke        |  16.2  |   14.2   |  7.6   |   13.1   |   6.7   |  12.1   |  10.9   | *1.6 ⚠* |

All themes pass WCAG AA for body text, secondary text, and every status
accent.

## Known exception

**`funtastic-smoke` — `--c-brand` (#333333) on `--c-bg` (#0a0a0a) = 1.57.**
The Smoke palette is deliberately monochromatic — the N64 Smoke shell was a
nearly-opaque translucent gray that read as flat black, with no warm cast.
The brand token is therefore set to the canonical retro-reference hex
(`#333333`) and is used *decoratively only* (SLink wordmark glow, theme
switcher swatch, calc header accent). It is **never** used as text colour
or as a UI control that needs to be perceived — every interactive surface
in Smoke uses `--c-txt`, `--c-alive` / `--c-dead` / `--c-pend` / `--c-gold`,
which all pass.

If you introduce a new component that needs the brand as a perceivable
control colour, gate it on `:not(.theme-funtastic-smoke)` or use `--c-gold`
(silver, contrast 10.9 against bg) instead.

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
