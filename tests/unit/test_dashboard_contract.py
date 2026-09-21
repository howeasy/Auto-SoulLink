"""The DOM contracts the pair board must keep, asserted on a populated run.

`test_routes_smoke.py` proves a page renders. This proves the page is the one the scripts
were written against (dashboard.js, calc-preview.js, idiomorph) and that the board says
what `server/board.py` computed: one row per bond with A, the bond and B in that order,
battle drawn on a half and never on a row, every zone present for the mock cast. Both
generations, via `populated_server`.

Parsing is stdlib `html.parser` into a tiny tree. It is enough to answer "is this a direct
child", "what is this cell's index" and "does this attribute exist", which is all the
contracts need; a real HTML5 parser would be a dependency for nothing.
"""
from __future__ import annotations

from html.parser import HTMLParser

import pytest
import pytest_asyncio

pytest_plugins = ["tests.unit.populated_server"]

# ── the smallest DOM that answers the questions below ──────────────────────────────────

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children, self.text = [], []

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def find_all(self, tag=None, **attrs):
        for n in self.walk():
            if tag and n.tag != tag:
                continue
            # v=True means "attribute present" — a bare boolean attribute parses as None.
            if all((k in n.attrs) if v is True else n.attrs.get(k) == v
                   for k, v in attrs.items()):
                yield n

    def find(self, tag=None, **attrs):
        return next(self.find_all(tag, **attrs), None)

    def elements(self):
        """Element children only (text is kept separately)."""
        return self.children

    def text_content(self):
        return "".join(self.text) + "".join(c.text_content() for c in self.children)


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.text.append(data)


def parse(html: str) -> Node:
    t = _Tree()
    t.feed(html)
    return t.root


@pytest_asyncio.fixture
async def dashboard(populated):
    srv, client = populated
    resp = await client.get("/")
    assert resp.status == 200
    return srv, parse(await resp.text())


# ── the refresh loop ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_polls_itself_and_selects_itself(dashboard):
    """htmx swaps `#content` with the `#content` of a fresh GET /. Lose the id, the
    hx-select or the morph extension and the page either stops updating or replaces the
    whole document every 2 s, resetting scroll and every open <details>."""
    _, dom = dashboard
    c = dom.find(id="content")
    assert c, "no #content"
    assert c.get("hx-get") == "/" and c.get("hx-select") == "#content"
    assert "morph" in (c.get("hx-ext") or "") and "morph" in (c.get("hx-swap") or "")


# ── <details> persistence across morphs (dashboard.js) ────────────────────────────────

@pytest.mark.asyncio
async def test_every_details_key_has_the_matching_id_idiomorph_matches_on(dashboard):
    """idiomorph pairs old and new nodes BY ID first. A <details data-details-key="k">
    without id="d-k" is re-created rather than morphed, the `open` veto never runs, and the
    panel snaps shut on every 2 s poll. The <summary> must be a direct child, because the
    click handler uses `closest('summary')` then `.parentElement`."""
    _, dom = dashboard
    details = list(dom.find_all("details", **{"data-details-key": True}))
    assert details, "no persisted <details> on the board (the wild-encounter panel at least)"
    ids = set()
    for d in details:
        key = d.get("data-details-key")
        assert d.get("id") == f"d-{key}", f"details[{key!r}] has id={d.get('id')!r}"
        assert d.get("id") not in ids, f"duplicate id {d.get('id')!r}"
        ids.add(d.get("id"))
        first = [c for c in d.elements() if c.tag != "script"]
        assert first and first[0].tag == "summary", f"details[{key!r}]: <summary> is not the first child"


# ── sprites and the calc preview ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sprites_carry_the_class_and_species_the_chroma_key_reads(dashboard):
    """`querySelectorAll('img.mon-sprite, img.enc-sprite')` + `data-species` is what the
    background-removal pass and every stylesheet rule select on."""
    _, dom = dashboard
    imgs = [i for i in dom.find_all("img") if "mon-sprite" in (i.get("class") or "")]
    assert imgs, "no img.mon-sprite on a populated board"
    assert all(i.get("data-species") for i in imgs), "a sprite without data-species"


@pytest.mark.asyncio
async def test_calc_preview_is_one_element_per_battling_player(dashboard):
    """`#calc-preview-{pid}[data-in-battle]` is read by calc-preview.js. Capability gated: a
    generation without battle calc renders none, and rendering one there would be a lie
    the script happily animates."""
    srv, dom = dashboard
    previews = [n for n in dom.walk() if (n.get("id") or "").startswith("calc-preview-")]
    ids = [n.get("id") for n in previews]
    assert len(ids) == len(set(ids)), f"duplicate calc previews: {ids}"
    if srv.state.is_rr:
        assert ids == ["calc-preview-b"], "player B is mid-battle on the Radical Red cast"
        assert all("data-in-battle" in n.attrs and n.get("data-player-moves") for n in previews)
        assert dom.find("script", src="/static/calc-preview.js"), "the preview script is not loaded"
    else:
        assert not previews, "calc preview rendered for a generation without battle calc"
        assert not dom.find("script", src="/static/calc-preview.js")


@pytest.mark.asyncio
async def test_pre_rendered_html_fields_are_not_escaped(dashboard):
    """`sprite_html` and friends are HTML the server already built; a template that forgets
    `|safe` prints `&lt;img` and the sprite becomes text."""
    _, dom = dashboard
    assert "&lt;img" not in dom.text_content(), "an html field was escaped on the way in"


# ── the board itself ──────────────────────────────────────────────────────────────────

def _classes(n):
    return set((n.get("class") or "").split())


@pytest.mark.asyncio
async def test_every_zone_the_mock_cast_produces_is_on_the_page(dashboard):
    """The injector builds five linked pairs in party, a pending capture, a boxed pair, a
    memorial and a dead zone. Each is a zone; a zone that disappears is data the board
    stopped showing."""
    _, dom = dashboard
    zones = {c for n in dom.find_all("section") for c in _classes(n) if c.startswith("zone-")}
    assert zones >= {"zone-party", "zone-pending", "zone-boxed", "zone-fallen"}, zones
    pairs = [p for p in dom.find_all("article") if "mk-pair" in _classes(p)]
    assert len(pairs) == 9, "8 links + 1 pending capture"


@pytest.mark.asyncio
async def test_a_pair_row_is_a_half_the_bond_and_a_half_in_that_order(dashboard):
    """Column position is the only ownership signal the board has: it cannot know who is
    looking. So every row is A's half, then the bond, then B's half, and nothing else."""
    _, dom = dashboard
    for row in (n for n in dom.find_all("article") if "mk-pair" in _classes(n)):
        kids = row.elements()
        assert [k.tag for k in kids] == ["div", "div", "div"], row.get("id")
        assert {"mk-half", "a"} <= _classes(kids[0]), row.get("id")
        assert "mk-bond" in _classes(kids[1]), row.get("id")
        assert {"mk-half", "b"} <= _classes(kids[2]), row.get("id")


@pytest.mark.asyncio
async def test_battle_is_on_the_player_card_and_marked_on_the_half(dashboard):
    """Player B is in a wild battle with the active mon of the Route 1 pair. The battle
    itself (own mon, then the foe with `vs`, each with HP and moves) is on B's NOW card;
    the pair row only marks B's half as fighting, and A's half says nothing about it: two
    games, two states. No row-level battle state exists to get the owner wrong."""
    _, dom = dashboard
    fighting = [n for n in dom.find_all("div") if {"mk-half", "fighting"} <= _classes(n)]
    assert len(fighting) == 1, "exactly one half is fighting on the mock cast"
    assert "b" in _classes(fighting[0])
    assert not any("mk-cbt" in _classes(n) for n in fighting[0].walk()), "the battle leaked into the pair row"
    cards = [n for n in dom.find_all("div") if "mk-nowcard" in _classes(n)]
    battles = [n for c in cards for n in c.walk() if "mk-battle" in _classes(n)]
    assert len(battles) == 1, "exactly one player card shows a battle"
    sides = [n for n in battles[0].walk() if "mk-cbt" in _classes(n)]
    assert {"mine", "foe"} <= {c for n in sides for c in _classes(n)}, "own mon and foe both on the card"
    assert any("mk-move" in _classes(n) for n in battles[0].walk()), "the active mon's moves are on the card"
    leads = [n for c in cards for n in c.walk() if "mk-lead" in _classes(n)]
    assert len(leads) == 1, "the player not in battle shows their party lead"
    assert not [n for n in dom.find_all("div") if {"mk-half", "staked"} <= _classes(n)]
    assert "at stake" not in dom.text_content().lower()
    assert not [n for n in dom.find_all("article") if "at-risk" in _classes(n)]
    rows = [n for n in dom.find_all("article") if "mk-pair" in _classes(n)]
    assert not any("fighting" in _classes(r) or "in-battle" in _classes(r) for r in rows)


@pytest.mark.asyncio
async def test_the_now_cards_sit_in_the_player_columns(dashboard):
    _, dom = dashboard
    cards = [n for n in dom.find_all("div") if "mk-nowcard" in _classes(n)]
    assert [c.get("style") for c in cards] == ["grid-column:1", "grid-column:3"]
    # the area's picture beside each card's area line (server/area_art.py), named by the area
    assert [c.find("img", **{"class": "mk-now-art"}).attrs["src"].startswith("/area-art/") for c in cards] == [True, True]
    assert all("online" in _classes(c) for c in cards), "both players are connected on the mock cast"


@pytest.mark.asyncio
async def test_fallen_rows_carry_no_live_numbers(dashboard):
    """A memorialized pair is a memorial: no HP bar, no ability, no item. The injector's
    party tick still lists the fainted mon, which is exactly the trap."""
    _, dom = dashboard
    for row in (n for n in dom.find_all("article") if {"mk-pair", "fallen"} <= _classes(n)):
        assert not [n for n in row.walk() if "mk-hp" in _classes(n)], row.get("id")
