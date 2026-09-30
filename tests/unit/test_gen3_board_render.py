"""C-3 -- the dashboard renders Gen 3 (docs/gen3_requirements.md §C-3, row 127).

C-3's evidence column was empty: `test_sprite_html_contract.py` has no Gen 3 case
(it parametrizes `_GB_ADAPTERS = ["gen1_rby", "gen2_gsc"]`, and Gen 3 is neither a
Game Boy generation nor a 7-slot-neutral generation), and there was no browser receipt.
This file is the missing half: a real `SLinkServer` on a real TCP socket, fed a real
event stream, rendering `GET /` for BOTH admitted Gen 3 cartridges -- `firered`
(vanilla FRLG, `is_rr=False`) and `firered_rr` (Radical Red, `is_rr=True`).

The pair matters. `server/adapters/__init__.py:38-41` routes both spellings to the
SAME `gen3_frlge` game_id and the same `Gen3Adapter` class; the two runs differ only in
the `is_rr` flag `server.py:2092` stages out of the hello's rom_type. So a rendering
defect that is really an `is_rr` defect looks identical if you only ever render one of
them: the same page, the same "correct" adapter, and one set of facts quietly wrong.
Every assertion below is written to be wrong in exactly one generation if the adapter
answers wrongly:

  sprites   `SLinkServer._get_sprite_html` (server.py:626) -> `Gen3Adapter.sprite_html`
            (gen3_frlge.py:422). FR falls back to the vendored FireRed/LeafGreen sprite
            set; RR serves its own `server/static/sprites/rr/<id>.png`. Different `src`
            for the same species, asserted both per-run and across the two runs.
  pill      `_macros.html:43 status_pill`, reached from `_board.html:37 combatant`. The
            macro is shared, so the test pins it AGAINST `Gen3Adapter.status_token`
            (gen3_frlge.py:395): Gen 3 has a Toxic bit (0x88 must read TOX, not PSN),
            the Game Boy decoders deliberately have none (`gb_status_token`,
            base.py:633). An adapter that decoded the shared byte with the wrong
            generation's layout would make the two disagree.
  stages    `_board.html:39` -> `_macros.html:64 stat_stages_row` with
            `p.capabilities.stat_stage_labels`, which is
            `ui_capabilities` -> `Gen3Adapter.stat_stage_labels` (base default:
            7 slots, SATK and SDEF independent). Gen 1 blanks SDEF and calls slot 4 SPC,
            so "+2 SATK" / "−2 SDEF" cannot be produced by a Game Boy label set.
  badges    `server/board.py:57 badge_count` (a POPCOUNT of the client's bitmask) ->
            `build_board()` -> `_board.html:153-155`. The mask sent is 0b101 == 5, so a
            renderer that printed the mask instead of its popcount reads "5/8".
            The denominator is `len(capabilities.badges)` == `gym_badge_slugs`, 8 Kanto
            for both Gen 3 cartridges.
  boxes     `server/board.py:61 locate` classifies a half as `where == "box"` from the
            client's `pc_boxes` census -> `pairs()` puts the pair in the "boxed" zone ->
            `_board.html:249-278` draws the zone, its count and "boxed together". The
            box GEOMETRY behind it is adapter data: `memorial_box_index` is 13 for FRLG
            and 24 for Radical Red (gen3_frlge.py:740-744) and `mons_per_box` is 30.
            A mon in box 13 is therefore in the memorial box on FR and in a regular box
            on RR; `GET /api/debug/raw_state` (server.py:4396, drawn by
            `_debug_panel.html::loadMemorial`) is where that difference is visible.
  opponent  `server.py:2370-2373` resolves the tick's `trainer_id` through
            `Gen3Adapter.trainer_info` (gen3_frlge.py:525) -- a different TABLE per
            cartridge -- and `_board.html:182` prints `class name` on the Now card.
            FR and RR therefore read "vs Leader Roxanne" and "vs Gym Leader Falkner"
            for ids that exist in their own roster.

Deliberately NOT asserted here: the Upcoming Key Trainers panel (`trainer_panel_html`,
`_board.html:203`) -- another card is building its FR coverage, and `trainers_for_area`
for vanilla FRLG reads `frlg_trainers.json`, which is a separate piece of work.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from server.adapters import get_adapter
from server.server import SLinkServer, build_app
from tests.unit.test_dashboard_contract import parse

# ── the two admitted Gen 3 cartridges ─────────────────────────────────────────────────────

# rom_type -> (artifact_kind the client declares, wire trainer_id, expected class, name)
# `firered` declares "clean" and `firered_rr` declares "companion"; the run's committed
# artifact kind is set once from the first hello (server.py:2174) and every later hello
# must agree, or the foundation lock refuses it (test_mixed_foundations).
RUNS = {
    "firered": ("clean", 27, "Leader", "Roxanne"),
    "firered_rr": ("companion", 43, "Gym Leader", "Falkner"),
}

# Gen3Adapter.memorial_box_index: FRLG has 14 boxes (last = 13), CFRU 25 (last = 24).
# Pinned in test_memorial_box_index_is_the_cartridges_own; used here only to place a
# census entry that must land in the memorial box on one run and not the other.
MEMORIAL_BOX = {"firered": 13, "firered_rr": 24}

# Client badge bitmasks. 0b101 is 5, which is 2 badges set -- the popcount is the whole
# point of the assertion, so the two numbers must differ.
BADGES = {"a": 0b00000101, "b": 0b11111111}

# Two linked mons in party, one linked pair in the PC, one spare in the memorial box.
A_PIKA, B_RATT = "AA00AA00:13572468", "BB00BB00:24681357"   # species 25 / 19, level 12
A_POLI, B_PSYD = "CC11CC11:11223344", "DD22DD22:55667799"   # species 60 / 54, level 10
A_BOOT, B_BOOT = "0C0C0C0C:33445566", "0D0D0D0D:778899AA"   # pre-run party, then dropped
A_SPARE = "EE33EE33:99AABBCC"                              # census-only, box 13 or 24

# A's own active mon: poisoned (bit 3) and carrying a SpAtk boost / SpDef drop, the two
# slots a Game Boy generation cannot even name.
STAGES = [6, 6, 6, 8, 4, 6, 6]          # ATK DEF SPD SATK SDEF ACC EVA; 6 == neutral
POISON, TOXIC = 0x08, 0x88              # 0x88 = Toxic (bits 3 + 7 set together in game)

_MINUS = "−"                            # _macros.html:76 uses U+2212, not a hyphen


# ── the event stream ─────────────────────────────────────────────────────────────────────

def _party(key, species, nickname, level, *, hp=None, max_hp=None, active=True,
           status=0, stages=None, slot=0):
    max_hp = max_hp if max_hp is not None else 20 + level
    entry = {"key": key, "species_id": species, "nickname": nickname, "level": level,
             "hp": hp if hp is not None else max_hp, "maxHP": max_hp,
             "active": active, "slot": slot, "status_cond": status,
             "held_item_id": 0, "ability_id": 1, "gender": "male", "pp_bonuses": 0}
    if stages is not None:
        entry["stat_stages"] = stages
    return entry


def _box(key, nickname, species, box, slot):
    return {"box": box, "slot": slot, "key": key, "nickname": nickname,
            "species_id": species, "held_item_id": 0, "moves": []}


def _events(rom_type: str) -> list[dict]:
    """The whole run, in the order a cartridge would produce it.

    Sequence mirrors tools/inject_full_mocks.py: hello (empty party, so no identity
    lock) -> a boot tick -> area_enter/capture per pair -> final positions -> the
    party/census ticks that put one pair in party and one in the boxes.
    """
    kind, trainer_id, _cls, _name = RUNS[rom_type]
    foe = {"species_id": 10, "level": 9, "hp": 20, "maxHP": 30, "active": True,
           "status_cond": TOXIC, "held_item_id": 0, "ability_id": 1, "moves": [],
           "pp": [], "nickname": "Caterpie", "key": "WILD_CATE"}
    a_party = [_party(A_PIKA, 25, "Sparky", 12)]
    b_party = [_party(B_RATT, 19, "Ratty", 12, status=POISON, stages=STAGES)]
    return [
        {"event": "hello", "player": "a", "rom_type": rom_type, "artifact_kind": kind,
         "trainer_name": "ALICE", "has_pokeballs": True, "party": []},
        {"event": "hello", "player": "b", "rom_type": rom_type, "artifact_kind": kind,
         "trainer_name": "BOB", "has_pokeballs": True, "party": []},
        {"event": "tick", "player": "a", "has_pokeballs": True,
         "party": [_party(A_BOOT, 1, "Boot", 5, slot=0)]},
        {"event": "tick", "player": "b", "has_pokeballs": True,
         "party": [_party(B_BOOT, 4, "Boot", 5, slot=0)]},
        # pair 1 -- both halves stay in party
        {"event": "area_enter", "player": "a", "area_id": "route_1"},
        {"event": "area_enter", "player": "b", "area_id": "route_1"},
        {"event": "capture", "player": "a", "area_id": "route_1", "species_id": 25,
         "key": A_PIKA, "nickname": "Sparky", "level": 12, "hp": 32, "maxHP": 32,
         "in_box": False, "gender": "male", "ability_id": 1},
        {"event": "capture", "player": "b", "area_id": "route_1", "species_id": 19,
         "key": B_RATT, "nickname": "Ratty", "level": 12, "hp": 32, "maxHP": 32,
         "in_box": False, "gender": "female", "ability_id": 1},
        # pair 2 -- caught, then deposited; the final census is what puts it in the box
        {"event": "area_enter", "player": "a", "area_id": "route_2"},
        {"event": "area_enter", "player": "b", "area_id": "route_2"},
        {"event": "capture", "player": "a", "area_id": "route_2", "species_id": 60,
         "key": A_POLI, "nickname": "Bubbles", "level": 10, "hp": 30, "maxHP": 30,
         "in_box": False, "gender": "male", "ability_id": 1},
        {"event": "capture", "player": "b", "area_id": "route_2", "species_id": 54,
         "key": B_PSYD, "nickname": "Quack", "level": 10, "hp": 30, "maxHP": 30,
         "in_box": False, "gender": "female", "ability_id": 1},
        # final positions
        {"event": "area_enter", "player": "a", "area_id": "route_1"},
        {"event": "area_enter", "player": "b", "area_id": "viridian_forest"},
        {"event": "tick", "player": "a", "has_pokeballs": True, "party": a_party,
         "ball_count": 9, "badges": BADGES["a"]},
        {"event": "tick", "player": "b", "has_pokeballs": True, "party": b_party,
         "ball_count": 7, "badges": BADGES["b"], "in_battle": True,
         "is_trainer_battle": True, "trainer_id": trainer_id, "is_doubles": False,
         "enemy_party": [foe]},
        # the PC census: the boxed pair, plus one mon in the box this cartridge calls
        # its memorial box. Only one of the two runs has a memorial box at 13.
        {"event": "tick", "player": "a", "has_pokeballs": True, "party": a_party,
         "pc_boxes": [_box(A_POLI, "Bubbles", 60, 0, 0),
                      _box(A_SPARE, "Old One", 96, 13, 5)]},   # box 13 on BOTH: memorial on FRLG only
        {"event": "tick", "player": "b", "has_pokeballs": True, "party": b_party,
         "pc_boxes": [_box(B_PSYD, "Quack", 54, 0, 0)]},
    ]


# ── driving a real server ────────────────────────────────────────────────────────────────

async def _run_board(rom_type: str, data_dir) -> _Board:
    """One admitted run, rendered. Returns the server, the parsed page and the JSON API.

    The events go through `SLinkServer.handle_client` over a real socket, NOT
    `_dispatch`: the rom_type route, the foundation lock, `connected_players` and the
    per-connection seq/hello gates all live in the reader (server.py:1536-1712), so a
    `_dispatch`-only test would render a page with `rom_type "?"` and a disconnected
    card -- a different page from the one a live run shows (the same reason
    tests/unit/populated_server.py drives the real handler).
    """
    os.makedirs(data_dir, exist_ok=True)
    srv = SLinkServer(data_dir=str(data_dir))
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0, limit=4 * 1024 * 1024)
    port = tcp.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    for event in _events(rom_type):
        writer.write((json.dumps(event) + "\n").encode())
        await writer.drain()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(reader.readline(), timeout=5)

    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    resp = await client.get("/")
    assert resp.status == 200, f"{rom_type}: GET / answered {resp.status}"
    html = await resp.text()
    api = await (await client.get("/api/status")).json()
    raw = await (await client.get("/api/debug/raw_state")).json()

    async def close():
        await client.close()
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        tcp.close()
        await tcp.wait_closed()

    return _Board(rom_type, srv, parse(html), html, api, raw, close)


class _Board:
    """A rendered run plus the two JSON surfaces the page is drawn from."""

    def __init__(self, rom_type, srv, dom, html, api, raw, close):
        self.rom_type = rom_type
        self.srv = srv
        self.dom = dom
        self.html = html
        self.api = api
        self.raw = raw
        self._close = close

    @property
    def adapter(self):
        """The adapter this run actually installed -- read off the server, not rebuilt."""
        return self.srv.adapter

    def card(self, trainer_name: str):
        """The NOW card (`_board.html:145`) belonging to one trainer."""
        for card in by_class(self.dom, "mk-nowcard"):
            head = first(card, "mk-now-name")
            if head is None:
                continue
            name = head.find("b")
            if name is not None and name.text_content().strip() == trainer_name:
                return card
        return None


# ── the smallest DOM the assertions need ──────────────────────────────────────────────────

def by_class(root, cls):
    return [n for n in root.walk() if cls in (n.get("class") or "").split()]


def first(root, cls):
    for n in by_class(root, cls):
        return n
    return None


def text(node) -> str:
    return re_sub_ws(node.text_content())


def re_sub_ws(s: str) -> str:
    return " ".join(s.split())


def img_attrs(sprite_html: str) -> dict:
    """The attributes of the one <img> an adapter's `sprite_html` produced."""
    node = next((n for n in parse(sprite_html).walk() if n.tag == "img"), None)
    assert node is not None, f"adapter produced no <img>: {sprite_html!r}"
    return node.attrs


@pytest_asyncio.fixture(params=sorted(RUNS))
async def board(request, tmp_path):
    made = await _run_board(request.param, tmp_path / request.param)
    try:
        yield made
    finally:
        await made._close()


# ── 0. the run itself is a Gen 3 run (control: every assertion below is worthless if
#       the adapter never switched, because a base-class adapter answers most of them
#       with an empty string) ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("rom_type", sorted(RUNS))
async def test_the_page_was_drawn_by_the_gen3_adapter_for_this_cartridge(rom_type, tmp_path):
    """server.py:2108-2110 stages the adapter out of the hello's rom_type."""
    made = await _run_board(rom_type, tmp_path / "control")
    try:
        assert made.adapter.game_id == "gen3_frlge"
        assert made.adapter._is_rr is rom_type.endswith("_rr")
        assert made.adapter._rom_type == rom_type
        assert made.api["players"]["a"]["rom_type"] == rom_type
        assert made.api["players"]["a"]["capabilities"]["game_id"] == "gen3_frlge"
        # RR retains the companion panel; the bound vanilla titles also have Explode Mode.
        caps = made.api["players"]["a"]["capabilities"]
        assert caps["info_panel"] is True  # both titles now publish native companions
        assert caps["explode_mode"] is (rom_type.endswith("_rr") or rom_type in ("firered", "leafgreen", "emerald"))
    finally:
        await made._close()


# ── 1. sprites ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_sprite_on_the_board_is_the_one_the_gen3_adapter_built(board):
    """`SLinkServer._get_sprite_html` (server.py:626) -> `Gen3Adapter.sprite_html`
    (gen3_frlge.py:422), drawn by `_board.html:52` (`half`) and `:35` (`combatant`).

    Asserted attribute-by-attribute against a fresh call for the SAME species, so a
    sprite borrowed from another generation -- or one that skipped the CFRU -> NatDex
    conversion -- fails instead of quietly rendering.
    """
    sprites = by_class(board.dom, "mon-sprite")
    assert len(sprites) >= 5, f"expected the pair, the battle and the box sprites: {len(sprites)}"
    for img in sprites:
        species = int(img.get("data-species"))
        want = img_attrs(board.adapter.sprite_html(species))
        assert img.attrs.get("src") == want["src"], (
            f"species {species}: board src {img.get('src')!r} != adapter "
            f"{want['src']!r} -- the page is not drawing Gen3Adapter.sprite_html")
        assert img.attrs.get("onerror") == want["onerror"], f"species {species}: fallback chain differs"
        assert img.get("class") == "mon-sprite", (
            "server.py:1855 swaps mon-sprite -> enc-sprite for the encounter table; a "
            "sprite without the class is bypassed by every CSS rule keyed on it")


@pytest.mark.asyncio
async def test_the_two_gen3_cartridges_do_not_share_a_sprite_source(board):
    """The one thing `is_rr` changes about a sprite. FR has no vendored sprite and
    falls through to the FireRed/LeafGreen set; RR serves its own CFRU art. If the
    flag were lost, this run would draw the other cartridge's Pokémon."""
    src = img_attrs(board.adapter.sprite_html(25))["src"]
    if board.rom_type == "firered_rr":
        assert src == "/static/sprites/rr/25.png"
    else:
        assert src.endswith("/sprites/pokemon/versions/generation-iii/firered-leafgreen/25.png")


@pytest.mark.asyncio
async def test_the_two_gen3_runs_render_different_sprites_for_the_same_species(tmp_path):
    """A cross-run control: the per-run assertion above would still pass if BOTH runs
    took the same wrong branch, so prove the two pages disagree."""
    fr = await _run_board("firered", tmp_path / "fr")
    rr = await _run_board("firered_rr", tmp_path / "rr")
    try:
        fr_src = img_attrs(fr.adapter.sprite_html(25))["src"]
        rr_src = img_attrs(rr.adapter.sprite_html(25))["src"]
        assert fr_src != rr_src
        assert fr_src in fr.html and rr_src in rr.html
    finally:
        await fr._close()
        await rr._close()


# ── 2. the status pill ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_status_pill_agrees_with_the_gen3_status_token(board):
    """`_macros.html:43 status_pill` is shared by every generation, so the macro alone
    proves nothing. What makes it Gen 3 is that it agrees with
    `Gen3Adapter.status_token` (gen3_frlge.py:395) on the byte the cartridge sent.

    0x88 is the discriminator: Toxic sets the poison bit too, so Gen 3 must read TOX
    (checked before PSN, gen3_frlge.py:400) and the Game Boy decoders must not -- see
    `gb_status_token` (base.py:633), which has no bit 7 at all.
    """
    mine, foe = _battle_sides(board)
    assert board.adapter.status_token(POISON) == "PSN"
    assert board.adapter.status_token(TOXIC) == "TOX"
    assert board.adapter.status_token(0) == ""

    pill = first(mine, "sc")
    assert pill is not None and pill.text_content().strip() == board.adapter.status_token(POISON)
    assert "sc-psn" in (pill.get("class") or "")

    toxic = first(foe, "sc")
    assert toxic is not None and toxic.text_content().strip() == "TOX", (
        "0x88 read as something other than TOX: the shared macro and Gen3Adapter."
        "status_token disagree, which is what a wrong generation's layout looks like")
    assert "sc-tox" in (toxic.get("class") or "")
    assert "PSN" not in foe.text_content()


@pytest.mark.asyncio
async def test_a_healthy_mon_draws_no_pill_at_all(board):
    """Player A's lead is the `mk-lead` combatant (`_board.html:187-191`); a status
    byte of 0 must not paint a pill, or every healthy mon reads as statused."""
    lead = first(board.card("ALICE"), "mk-cbt")
    assert lead is not None, "player A's lead combatant is missing from the NOW card"
    assert not by_class(lead, "sc"), "a mon with status_cond 0 rendered a status pill"


# ── 3. stat stages ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_stat_stage_row_uses_the_gen3_labels(board):
    """`_board.html:39` -> `_macros.html:64 stat_stages_row` with
    `p.capabilities.stat_stage_labels` == `Gen3Adapter.stat_stage_labels()` (base
    default, base.py:589): seven slots with SpAtk and Sp.Def independent.

    Gen 1 blanks slot 5 and names slot 4 "SPC" (gen1_rby.py:561), so a Game Boy label
    set cannot produce either chip below -- which is the point of asserting on the two
    SPECIAL slots rather than on Attack.
    """
    mine, _foe = _battle_sides(board)
    labels = board.api["players"]["b"]["capabilities"]["stat_stage_labels"]
    assert labels == board.adapter.stat_stage_labels()
    assert labels == ["ATK", "DEF", "SPD", "SATK", "SDEF", "ACC", "EVA"]

    row = first(mine, "stat-stages-row")
    assert row is not None, "no stat-stage row on the active mon"
    chips = [c.text_content().strip() for c in by_class(row, "stat-stage")]
    assert chips == [f"+2 {labels[3]}", f"{_MINUS}2 {labels[4]}"], f"chips: {chips}"

    up, dn = by_class(row, "ss-up"), by_class(row, "ss-dn")
    assert [c.text_content().strip() for c in up] == ["+2 SATK"]
    assert [c.text_content().strip() for c in dn] == [f"{_MINUS}2 SDEF"]

    # Neutral slots are dropped, not drawn at zero: 6 is neutral in the wire encoding.
    assert len(chips) == 2, f"neutral slots rendered: {chips}"


# ── 4. badges ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_badges_are_the_popcount_of_the_bitmask_and_the_kanto_denominator(board):
    """`server/board.py:57 badge_count` (popcount) -> `build_board()` ->
    `_board.html:153-155`. A sent `0b101` is 5 and 2 badges: a renderer that showed the
    mask reads "5/8". The denominator is `len(capabilities.badges)`, i.e.
    `gym_badge_slugs` -- 8 Kanto for both Gen 3 cartridges (base.py:612), which an
    adapter answering with Johto (16) or Hoenn (24) would change.
    """
    slugs = board.api["players"]["a"]["capabilities"]["badges"]
    assert len(slugs) == 8 and slugs[0] == "Boulder Badge" and slugs[-1] == "Earth Badge"

    for trainer, pid, expected in (("ALICE", "a", "2/8"), ("BOB", "b", "8/8")):
        card = board.card(trainer)
        assert card is not None, f"no NOW card for {trainer}"
        block = first(card, "mk-badges")
        assert block is not None
        assert text(block) == expected, f"{pid}: badge block reads {text(block)!r}, want {expected!r}"

        pips = by_class(block, "mk-badge-pip")
        lit = [p for p in pips if "on" in (p.get("class") or "").split()]
        assert len(pips) == 8, f"{pid}: {len(pips)} slots, want the adapter's 8"
        assert len(lit) == bin(BADGES[pid]).count("1"), f"{pid}: lit pips != popcount"


# ── 5. box counts ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_boxed_pair_is_counted_and_drawn_in_the_boxed_zone(board):
    """`server/board.py:61 locate` -> `where == "box"` -> `pairs()` section "boxed"
    (board.py:122) -> `_board.html:249-278`. The zone header carries the count and the
    bond reads "boxed together"; a boxed half has no live HP, so it must not paint a
    bar (`_board.html:56` skips it when `hp is none`).

    The payload side is checked too: both halves are in the client's `pc_boxes` census
    and in neither party (`SLinkServer._party_snapshot` replaces party_details on every
    tick, server.py:2440), which is what makes them "box" rather than "party".
    """
    zones = {tok for n in by_class(board.dom, "mk-zone")
             for tok in (n.get("class") or "").split() if tok.startswith("zone-")}
    assert "zone-boxed" in zones and "zone-party" in zones, f"zones: {zones}"

    zone = first(board.dom, "zone-boxed")
    mid = first(zone, "mk-h2-mid")
    # the header is "Boxed pair" plus a separate count element: "Boxed pair" + "1"
    assert re.fullmatch(r"Boxed pairs?\s*1", text(mid).strip()), text(mid)

    row = first(zone, "mk-pair")
    assert text(first(row, "mk-bond-area")) == "Route 2"
    assert text(first(row, "mk-bond-state")) == "boxed together"
    for half in by_class(row, "mk-half"):
        assert not by_class(half, "mk-hp"), "a boxed half painted an HP bar it has no numbers for"
        assert "Lv 10" in text(half)

    api = board.api["players"]
    assert [b["key"] for b in api["a"]["pc_boxes"]] == [A_POLI, A_SPARE]
    assert [b["key"] for b in api["b"]["pc_boxes"]] == [B_PSYD]
    assert A_POLI not in api["a"]["party_details"], "the boxed half is still in the party snapshot"
    assert api["a"]["party_keys"] == [A_PIKA], f"A party: {api['a']['party_keys']}"
    assert api["b"]["party_keys"] == [B_RATT], f"B party: {api['b']['party_keys']}"
    # the box geometry every count is built from
    assert api["a"]["capabilities"]["mons_per_box"] == 30
    assert api["a"]["capabilities"]["memorial_box_index"] == MEMORIAL_BOX[board.rom_type]


@pytest.mark.asyncio
async def test_the_memorial_box_index_is_the_cartridges_own_not_the_shared_default(board):
    """`Gen3Adapter.memorial_box_index` (gen3_frlge.py:740) is 13 on FRLG (14 boxes)
    and 24 on CFRU (25 boxes). `GET /api/debug/raw_state` (server.py:4396, drawn by
    `_debug_panel.html::loadMemorial`) counts the census entries that land in it.

    The same mon is in box 13 on both runs. On FR that is the memorial box and it is
    counted; on RR box 13 is an ordinary box and it is not. A run that answered the
    shared base default (or the other cartridge's index) counts it on both or on
    neither.
    """
    mem = board.raw["_memorial"]
    assert mem["memorial_box_index"] == MEMORIAL_BOX[board.rom_type]
    counted = [e["key"] for e in mem["memorial_box_contents"]["a"]]
    if board.rom_type == "firered":
        assert counted == [A_SPARE], f"FRLG: box 13 is the memorial box, counted {counted}"
    else:
        assert counted == [], f"Radical Red: box 13 is a regular box, counted {counted}"
    assert mem["memorial_box_contents"]["b"] == []


def test_the_memorial_box_index_table_matches_the_adapter():
    """The table the event stream above places a census entry with, pinned to the
    adapter, so a changed `memorial_box_index` fails here and not silently moves the
    fixture."""
    fr = get_adapter("gen3_frlge", is_rr=False, rom_type="firered", artifact_kind="clean")
    rr = get_adapter("gen3_frlge", is_rr=True, rom_type="firered_rr", artifact_kind="companion")
    assert fr.memorial_box_index == MEMORIAL_BOX["firered"] == 13
    assert rr.memorial_box_index == MEMORIAL_BOX["firered_rr"] == 24
    assert fr.mons_per_box == rr.mons_per_box == 30


# ── 6. the opponent / trainer name ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_trainer_battle_head_names_the_opponent_from_this_cartridges_table(board):
    """`server.py:2370-2373` resolves the tick's `trainer_id` through
    `Gen3Adapter.trainer_info` (gen3_frlge.py:525) and `_board.html:182` prints
    `vs <class> <name>` on the NOW card. FR reads the pret gTrainers index
    (`frlg_trainers.json`), RR its own 1-based roster -- so the SAME id means a
    different fight on the two cartridges.
    """
    _kind, trainer_id, want_class, want_name = RUNS[board.rom_type]
    bs = board.srv.battle_state["b"]
    assert bs["trainer_id"] == trainer_id and bs["is_trainer_battle"] is True
    assert (bs["opponent_class"], bs["opponent_name"]) == (want_class, want_name), (
        "battle_state was not filled from the adapter's own trainer table")

    card = board.card("BOB")
    head = first(first(card, "mk-battle"), "mk-battle-head")
    assert head is not None, "no battle head on the player's NOW card"
    assert "in battle" in text(head)
    assert text(first(head, "mk-sub")) == f"vs {want_class} {want_name}"

    # Player A is not in a battle, so it has no battle block at all -- the head is
    # per-player, not a run-wide one.
    assert not by_class(board.card("ALICE"), "mk-battle")


@pytest.mark.asyncio
async def test_the_two_gen3_runs_name_different_trainers_for_their_own_rosters(tmp_path):
    """A cross-run control on the one line that must differ: if both runs printed the
    same text, one of them is reading the other cartridge's table (or a hardcode)."""
    fr = await _run_board("firered", tmp_path / "fr")
    rr = await _run_board("firered_rr", tmp_path / "rr")

    def head(made):
        card = made.card("BOB")
        return text(first(first(card, "mk-battle"), "mk-battle-head")).split(" ", 1)[1]

    try:
        assert head(fr).endswith("vs Leader Roxanne")   # the head carries an icon label
        assert head(rr).endswith("vs Gym Leader Falkner")
        assert head(fr) != head(rr)
    finally:
        await fr._close()
        await rr._close()


# ── shared helpers for the battle assertions ─────────────────────────────────────────────

def _battle_sides(board):
    """(own mon, foe) combatant blocks on the battling player's NOW card."""
    battle = first(board.card("BOB"), "mk-battle")
    assert battle is not None, "player B's battle block is missing from the NOW card"
    mine = next((n for n in by_class(battle, "mk-cbt") if "mine" in (n.get("class") or "").split()), None)
    foe = next((n for n in by_class(battle, "mk-cbt") if "foe" in (n.get("class") or "").split()), None)
    assert mine is not None and foe is not None, "the battle drew no own mon / no foe"
    return mine, foe
