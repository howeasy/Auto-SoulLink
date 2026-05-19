"""HTML render helpers for the status page and stream overlays.

Shared display primitives extracted from server/server.py: type badges,
move tables, status-condition icons, and stat-stage badges. The CSS
palette and split-icon URLs live here as module-level data so callers
import them rather than duplicating.

Pure functions — no state, no I/O, no logging. Safe to import from any
module that renders HTML for the status page or stream overlays.
"""

import html


# CSS color per type name (standard Pokémon type palette).
TYPE_COLOR: dict[str, str] = {
    "Normal":   "#A8A878", "Fighting": "#C03028", "Flying":   "#A890F0",
    "Poison":   "#A040A0", "Ground":   "#E0C068", "Rock":     "#B8A038",
    "Bug":      "#A8B820", "Ghost":    "#705898", "Steel":    "#B8B8D0",
    "???":      "#68A090", "Fire":     "#F08030", "Water":    "#6890F0",
    "Grass":    "#78C850", "Electric": "#F8D030", "Psychic":  "#F85888",
    "Ice":      "#98D8D8", "Dragon":   "#7038F8", "Dark":     "#705848",
    "Fairy":    "#EE99AC",
}


# ── Funnotbun split icons (Physical/Special/Status) ──────────────────────────
_SPLIT_ICON_BASE = "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/main/src/moves"
SPLIT_ICONS = {
    0: f'<img class="split-icon split-physical" src="{_SPLIT_ICON_BASE}/SPLIT_PHYSICAL.png" alt="Physical" title="Physical">',
    1: f'<img class="split-icon split-special" src="{_SPLIT_ICON_BASE}/SPLIT_SPECIAL.png" alt="Special" title="Special">',
    2: f'<img class="split-icon split-status" src="{_SPLIT_ICON_BASE}/SPLIT_STATUS.png" alt="Status" title="Status">',
}


STAT_STAGE_LABELS = ["ATK", "DEF", "SPD", "SATK", "SDEF", "ACC", "EVA"]


def type_badges_html(species_id: int, *, adapter) -> str:
    """Return HTML type badge(s) for a species, or empty string if unknown."""
    if not species_id or not adapter:
        return ""
    pair = adapter.species_types(species_id)
    if not pair:
        return ""
    t1, t2 = pair
    n1 = adapter.type_name(t1)
    n2 = adapter.type_name(t2)
    c1 = TYPE_COLOR.get(n1, "#666")
    def badge(name: str, color: str) -> str:
        text_color = "#000" if name in ("Electric", "Ice", "Normal", "Ground", "Fairy") else "#fff"
        return (f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;'
                f'font-size:0.78em;background:{color};color:{text_color};margin:1px">'
                f'{name}</span>')
    out = badge(n1, c1)
    if n2 and n2 != n1:
        c2 = TYPE_COLOR.get(n2, "#666")
        out += badge(n2, c2)
    return out


def move_table_html(move_details: list[dict], *, is_box: bool = False, mon_key: str = "") -> str:
    """Generate a collapsible move table for a party/box mon.

    Each entry in move_details is:
      {name, type_id, type_name, power, accuracy, pp, split, current_pp}
    """
    if not move_details:
        return ""
    rows = []
    for md in move_details:
        name = html.escape(md.get("name", "?"))
        type_name = md.get("type_name", "")
        type_color = TYPE_COLOR.get(type_name, "#666")
        text_color = "#000" if type_name in ("Electric", "Ice", "Normal", "Ground", "Fairy") else "#fff"
        type_badge = (f'<span class="type-badge" style="background:{type_color};color:{text_color}">'
                      f'{type_name}</span>')
        split = md.get("split", 0)
        split_html = SPLIT_ICONS.get(split, "")
        power = md.get("power", 0)
        pwr_str = str(power) if power > 0 else "—"
        acc = md.get("accuracy", 0)
        acc_str = str(acc) if acc > 0 else "—"
        cur_pp = md.get("current_pp", 0)
        max_pp = md.get("pp", 0)
        if is_box:
            pp_str = str(max_pp) if max_pp else "—"
            pp_cls = ""
        else:
            pp_str = f"{cur_pp}/{max_pp}" if max_pp else "—"
            if max_pp and cur_pp == 0:
                pp_cls = " pp-zero"
            elif max_pp and cur_pp <= max_pp // 4:
                pp_cls = " pp-low"
            else:
                pp_cls = ""
        rows.append(
            f'<tr><td class="move-name">{name}</td>'
            f'<td>{type_badge}</td>'
            f'<td>{split_html}</td>'
            f'<td class="mv-pwr">{pwr_str}</td>'
            f'<td class="mv-acc">{acc_str}</td>'
            f'<td class="pp-cell{pp_cls}">{pp_str}</td></tr>'
        )
    count = len(move_details)
    key_attr = f' data-mon-key="{html.escape(mon_key)}"' if mon_key else ""
    return (
        f'<details{key_attr}><summary>Moves ({count})</summary>'
        f'<table class="move-table"><thead><tr>'
        f'<th>Move</th><th>Type</th><th>Cat</th><th>Pwr</th><th>Acc</th><th>PP</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></details>'
    )


def status_icon_html(status_cond: int) -> str:
    """Return a colored HTML badge for the given status condition bitmask, or ''."""
    if not status_cond:
        return ""
    if status_cond & 0x07:   # bits 0–2: sleep counter (> 0 = asleep)
        return '<span class="status-icon s-slp">SLP</span>'
    if status_cond & 0x80:   # bit 7: badly poisoned (Toxic) — check before PSN, sets both bits
        return '<span class="status-icon s-tox">TOX</span>'
    if status_cond & 0x08:   # bit 3: poisoned
        return '<span class="status-icon s-psn">PSN</span>'
    if status_cond & 0x10:   # bit 4: burned
        return '<span class="status-icon s-brn">BRN</span>'
    if status_cond & 0x20:   # bit 5: frozen
        return '<span class="status-icon s-frz">FRZ</span>'
    if status_cond & 0x40:   # bit 6: paralyzed
        return '<span class="status-icon s-par">PAR</span>'
    return ""


def stat_stages_html(stages) -> str:
    """Return HTML badges for non-neutral stat stages.

    ``stages`` is a 7-element list (ATK–EVA), raw values 0–12 where 6 = neutral.
    Returns '' when all stages are neutral or stages is None/empty/malformed.
    """
    if not isinstance(stages, (list, tuple)) or not stages:
        return ""
    parts = []
    for i, raw in enumerate(stages):
        if i >= len(STAT_STAGE_LABELS):
            break
        try:
            stage = int(raw) - 6
        except (TypeError, ValueError):
            continue
        if not (-6 <= stage <= 6) or stage == 0:
            continue
        sign  = "+" if stage > 0 else "−"
        cls   = "ss-up" if stage > 0 else "ss-dn"
        parts.append(
            f'<span class="stat-stage {cls}">{sign}{abs(stage)} {STAT_STAGE_LABELS[i]}</span>'
        )
    return "".join(parts)
