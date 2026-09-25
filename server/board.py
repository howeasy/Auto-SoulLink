"""The pair board: the status payload joined back into the thing a player thinks about.

A soul link's unit is the PAIR — two mons bound across two cartridges, both of which die
if either faints — and `/api/status` hands the two halves back separately: the bond in
`links`, the live HP in each player's `party_details`, the shelf in `pc_boxes`. This
module joins them into one row per bond and sorts the rows into zones, so the template
only has to draw.

Pure functions over the status dict. Nothing here reads server state, which is what makes
`tests/unit/test_board.py` a file of dicts rather than a server harness, and what lets the
Manager render the same board for a stopped run from what it persisted.

The board's founding rule: it cannot know which player is looking at it, so "you" and
"ours" are meaningless — column position is the only ownership signal. Battle is therefore
a PLAYER state drawn on a half, never a pair state drawn on a row.
"""
from __future__ import annotations

import re

SECTION_LABELS = {
    "party": "In party",
    "pending": "Pending link",
    "split": "Split — one half boxed",
    "boxed": "Boxed",
    "linked": "Linked",        # a stopped run: the bond is known, where each half sits is not
    "fallen": "Fallen",
}
# The team first; what is waiting on it second. Then the shelf, then the graveyard.
SECTION_ORDER = ("party", "pending", "split", "boxed", "linked", "fallen")

PIDS = ("a", "b")


def hp_pct(mon: dict) -> int:
    if mon.get("hp") is None:
        return 0
    return max(0, min(100, round(mon["hp"] / max(mon.get("maxHP") or 1, 1) * 100)))


def hp_class(mon: dict) -> str:
    p = hp_pct(mon)
    return "" if p > 50 else "mid" if p > 20 else "low"


def area_name(area_id: str) -> str:
    """`viridian_forest` -> `Viridian Forest`, `route9` -> `Route 9`. A fallback for ids
    the adapter has no display name for."""
    s = re.sub(r"(\d+)", r" \1", (area_id or "").replace("_", " "))
    return " ".join(w[:1].upper() + w[1:] for w in s.split())


def bond_glyph(status: str) -> str:
    return "<>" if status == "alive" else "<·" if status == "pending" else "><"


def badge_count(mask: int) -> int:
    return bin(mask or 0).count("1")


def locate(player: dict, key: str) -> dict | None:
    """Where a mon is right now, with its live numbers if it is somewhere live."""
    in_party = (player.get("party_details") or {}).get(key)
    if in_party:
        return {**in_party, "key": key, "where": "party"}
    for b in player.get("pc_boxes") or []:
        if b.get("key") == key:
            return {**b, "key": key, "where": "box"}
    return None


def active_key(player: dict) -> str | None:
    """The mon this player has out, when they are in battle."""
    if not (player.get("battle_state") or {}).get("in_battle"):
        return None
    for key in player.get("party_keys") or []:
        det = (player.get("party_details") or {}).get(key)
        if det and det.get("active"):
            return key
    return None


def _half(status: dict, link: dict, pid: str) -> dict | None:
    key = link.get(f"{pid}_key")
    if not key:
        return None
    player = status["players"][pid]
    live = locate(player, key)
    in_party = bool(live and live["where"] == "party")
    return {
        "key": key,
        "nickname": link.get(f"{pid}_nickname") or "",
        "species_name": link.get(f"{pid}_species_name") or "",
        "level": (live and live.get("level")) or link.get(f"{pid}_level") or 0,
        "sprite": link.get(f"{pid}_sprite_html") or "",
        "shiny": bool(link.get(f"{pid}_shiny")),
        "hp": live.get("hp") if in_party else None,
        "maxHP": live.get("maxHP") if in_party else None,
        "where": live["where"] if live else None,
        "ability": (live or {}).get("ability_name") or "",
        "item": (live or {}).get("item_name") or "",
        "active": active_key(player) == key,
    }


def pairs(status: dict) -> list[dict]:
    """One row per bond. Each half carries what the link recorded plus, if the run is live
    and the mon is in a party, its current HP."""
    killfeed = {k.get("area_id"): k for k in status.get("killfeed") or []}
    area_states = status.get("area_states") or {}
    rows = []
    for link in status.get("links") or []:
        a, b = _half(status, link, "a"), _half(status, link, "b")
        dead = link.get("status") in ("dead", "memorial")
        dead_zone = not a and not b and area_states.get(link.get("area_id")) == "dead_zone"
        if dead or dead_zone:
            section = "fallen"
        elif not a or not b:
            section = "pending"
        elif a["where"] == "party" and b["where"] == "party":
            section = "party"
        elif a["where"] == "box" and b["where"] == "box":
            section = "boxed"
        elif a["where"] and b["where"]:
            section = "split"
        else:
            section = "linked"   # nothing is located: the run is not live
        rows.append({
            "area": link.get("area_id") or "",
            "area_name": link.get("area_display") or area_name(link.get("area_id")),
            "status": "dead_zone" if dead_zone else link.get("status"),
            "section": section, "a": a, "b": b,
            "death": killfeed.get(link.get("area_id")),
        })
    return rows


def pending_rows(status: dict) -> list[dict]:
    """Captures waiting on the other player. One half filled, the other empty."""
    out = []
    for area, sides in (status.get("pending_captures") or {}).items():
        halves = {}
        for pid in PIDS:
            mon = sides.get(pid)
            halves[pid] = ({**mon, "sprite": mon.get("sprite_html") or "", "hp": None,
                            "where": None, "active": False, "ability": "", "item": ""}
                           if mon else None)
        out.append({"area": area, "area_name": area_name(area), "section": "pending",
                    "status": "pending", "a": halves["a"], "b": halves["b"],
                    "death": None})
    return out


def sections(status: dict, rows: list[dict] | None = None) -> list[tuple[str, list[dict]]]:
    if rows is None:
        rows = pending_rows(status) + pairs(status)
    out = []
    for key in SECTION_ORDER:
        group = [r for r in rows if r["section"] == key]
        if group:
            out.append((key, group))
    return out


def build_board(status: dict) -> dict:
    """Everything `dashboard.html` draws, derived once."""
    players = status.get("players") or {}
    rows = pairs(status)   # built once: sections() would otherwise build every pair again
    return {
        "sections": sections(status, pending_rows(status) + rows),
        "section_labels": SECTION_LABELS,
        "counts": {
            "alive": sum(1 for r in rows if r["section"] != "fallen"),
            "fallen": sum(1 for r in rows if r["section"] == "fallen"),
        },
        "badges": {pid: {"count": badge_count(players.get(pid, {}).get("badges", 0)),
                         "slots": len((players.get(pid, {}).get("capabilities") or {}).get("badges") or []) or 8}
                   for pid in PIDS},
        "active": {pid: active_key(players.get(pid, {})) for pid in PIDS},
        # "?" is what a player who never said hello reports as rom_type.
        "has_data": {pid: bool((players.get(pid, {}).get("rom_type") or "?") != "?"
                               or players.get(pid, {}).get("party_keys"))
                     for pid in PIDS},
        "dead_zones": sorted(k for k, v in (status.get("area_states") or {}).items() if v == "dead_zone"),
    }


RULE_BADGES = (
    ("species_lock", "dna", "Species Clause"),
    ("gender_lock", "gender", "Gender Clause"),
    ("type_lock", "type", "Type Clause"),
    ("explode_mode", "explode", "Explode Mode"),
    ("rival_team_swap", "rival-swap", "Rival Team Swap"),
    ("overworld_presence", "presence", "Overworld Presence"),
)


def phase(status: dict) -> tuple[str, str]:
    """Run lifecycle from the payload alone: nuzlocke_active is pokeballs_obtained."""
    if status.get("run_over"):
        return "game_over", "Game over"
    players = status.get("players") or {}
    if all((players.get(pid) or {}).get("nuzlocke_active") for pid in PIDS):
        return "running", "Run in progress"
    if not any((players.get(pid) or {}).get("connected") for pid in PIDS):
        return "pre", "Waiting for players"
    return "pre", "Waiting for Pokéballs"


def board_context(status: dict, *, run_name: str = "", poll_url: str = "/", live: bool = True,
                  launcher_url: str = "/launcher/{player}", rom_url: str = "",
                  roms_pinned: bool = False, rom_ext: dict | None = None) -> dict:
    """Everything `_board.html` needs, from the payload alone -- so the run server and the
    Manager (which has only the payload, live or persisted) render the same board.

    `poll_url` is what `#content` fetches every 2 s: `/` on a run server, the run's board
    route on the Manager. It has to be passed down because a root-relative URL baked into
    the fragment would poll the wrong page once the fragment is served under a prefix."""
    from server.adapters import variant_label

    players = status.get("players") or {}
    rom_types = [str((players.get(pid) or {}).get("rom_type") or "") for pid in PIDS]
    rom_type = next((rt for rt in rom_types if rt and rt != "?"), "")
    rules = status.get("rules") or {}
    slug, label = phase(status) if live else ("stopped", "Run stopped")
    title = " — ".join(x for x in (variant_label(rom_type) if rom_type else "", run_name) if x)
    return {
        "status": status,
        "board": build_board(status),
        "rules": [(icon, text) for key, icon, text in RULE_BADGES if rules.get(key)],
        "phase_slug": slug,
        "phase_label": label,
        # Where each player's BizHawk launcher downloads from; the empty board points at it.
        "launchers": {pid: launcher_url.format(player=pid) for pid in PIDS},
        # A run that made its players' cartridges: where each downloads from, so the empty
        # board's first step is the cartridge, not the launcher. `roms_pinned`: randomized,
        # so the run admits no other.
        "roms": {pid: rom_url.format(player=pid) for pid in PIDS} if rom_url else {},
        "roms_pinned": bool(rom_url) and roms_pinned,
        # the download labels name the file as handed out (.gbc for Yellow and pureRGB)
        "rom_ext": rom_ext or dict.fromkeys(PIDS, ".gb"),
        "concise_title": title or "Soul Link",
        # The damage calculator is pinned to modern mechanics: Radical Red only.
        "calc_preview": any(rt.endswith("_rr") for rt in rom_types),
        "poll_url": poll_url,
        # False for a stopped run on the Manager: the board is what it persisted, and
        # "waiting for hello" would be a lie about a server that is not listening.
        "live": live,
        "rom_label": variant_label,
        "hp_pct": hp_pct,
        "hp_class": hp_class,
        "bond_glyph": bond_glyph,
    }
