"""The DOM contracts `server/static/dashboard.js` depends on, asserted on a populated run.

`test_routes_smoke.py` proves a page renders. This proves the page is the one the script
was written against: every id, attribute and nesting the JS reaches for is present on the
dashboard as a real run renders it (both generations, via `populated_server`). Each
assertion names the line of dashboard.js it protects, because the point is to make the
dashboard's markup movable — to a template, to a new layout — with the script still working.

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


# ── encounters table: sort (dashboard.js:160-215) and filter (:228-260) ──────────────────

@pytest.mark.asyncio
async def test_encounter_table_has_the_ids_the_script_binds(dashboard):
    _, dom = dashboard
    assert dom.find("table", id="enc-table"), "getElementById('enc-table')"
    assert dom.find(id="enc-filters"), "getElementById('enc-filters')"
    assert dom.find("input", id="dash-search-input"), "getElementById('dash-search-input')"


@pytest.mark.asyncio
async def test_sortable_headers_name_the_cell_index_they_sort(dashboard):
    """`th.sortable[data-col]` is parsed as an int and used as `row.children[col]`.

    The header row must be inside a real <thead> (`querySelectorAll('thead th')`), the rows
    inside a <tbody>, and each data-col must equal that header's index so the column a user
    clicks is the column that sorts."""
    _, dom = dashboard
    tbl = dom.find("table", id="enc-table")
    thead = tbl.find("thead")
    assert thead, "sort walks tbl.querySelectorAll('thead th')"
    ths = list(thead.find_all("th"))
    sortable = [(i, th) for i, th in enumerate(ths) if "sortable" in (th.get("class") or "")]
    assert sortable, "no th.sortable — the sort UI would have nothing to bind"
    for i, th in sortable:
        assert th.get("data-col") == str(i), f"th #{i} says data-col={th.get('data-col')!r}"
    tbody = tbl.find("tbody")
    assert tbody, "sort reads tbl.querySelector('tbody')"
    rows = list(tbody.find_all("tr"))
    assert rows
    for r in rows:
        cells = [c for c in r.elements() if c.tag in ("td", "th")]
        assert len(cells) == len(ths), "a row with a different cell count than the header"


@pytest.mark.asyncio
async def test_sort_keys_sit_on_the_area_and_level_columns(dashboard):
    """`data-sort` overrides textContent so 'Route 10' sorts after 'Route 9' and a level
    cell full of markup sorts by its number. Columns 0 and 3 carry it today; a template
    that drops it silently degrades to string sorting."""
    _, dom = dashboard
    tbody = dom.find("table", id="enc-table").find("tbody")
    for r in tbody.find_all("tr"):
        cells = [c for c in r.elements() if c.tag == "td"]
        assert cells[0].get("data-sort") is not None, "area column lost data-sort"
        assert cells[3].get("data-sort") is not None, "level column lost data-sort"


@pytest.mark.asyncio
async def test_row_status_values_are_ones_the_filter_groups_know(dashboard):
    """`tr[data-status]` is matched against FILTER_GROUPS; a value outside the union is a
    row no filter can ever show."""
    _, dom = dashboard
    known = {"alive", "linked", "pending_a", "pending_b", "pending_both",
             "dead", "dead_zone", "memorial"}
    tbody = dom.find("table", id="enc-table").find("tbody")
    seen = set()
    for r in tbody.find_all("tr"):
        st = r.get("data-status")
        assert st is not None, "a row without data-status is invisible to the filter"
        assert st in known, f"data-status={st!r} matches no FILTER_GROUPS entry"
        seen.add(st)
    assert seen & {"alive", "linked"}, "the populated run has linked pairs; none rendered"
    assert seen & {"dead", "dead_zone", "memorial"}, "the dead zone and memorial rows are missing"
    assert seen & {"pending_a", "pending_b", "pending_both"}, "the pending capture row is missing"
    buttons = list(dom.find(id="enc-filters").find_all(**{"data-filter": True}))
    assert {b.get("data-filter") for b in buttons} >= {"all", "linked", "pending", "dead"}


@pytest.mark.asyncio
async def test_the_events_log_opts_out_of_the_global_search(dashboard):
    """The search box filters `table:not([data-no-search]) tr`; the events log carries the
    opt-out because its rows are prose, not records."""
    _, dom = dashboard
    assert dom.find("table", **{"data-no-search": True}), "no table opts out of search"


# ── <details> persistence across morphs (dashboard.js:742-830) ────────────────────────────

@pytest.mark.asyncio
async def test_every_details_key_has_the_matching_id_idiomorph_matches_on(dashboard):
    """idiomorph pairs old and new nodes BY ID first. A <details data-details-key="k">
    without id="d-k" is re-created rather than morphed, the `open` veto never runs, and the
    panel snaps shut on every 2 s poll. The <summary> must be a direct child, because the
    click handler uses `closest('summary')` then `.parentElement`."""
    _, dom = dashboard
    details = list(dom.find_all("details", **{"data-details-key": True}))
    assert details, "no persisted <details> on the dashboard"
    ids = set()
    for d in details:
        key = d.get("data-details-key")
        assert d.get("id") == f"d-{key}", f"details[{key!r}] has id={d.get('id')!r}"
        assert d.get("id") not in ids, f"duplicate id {d.get('id')!r}"
        ids.add(d.get("id"))
        first = [c for c in d.elements() if c.tag != "script"]
        assert first and first[0].tag == "summary", f"details[{key!r}]: <summary> is not the first child"


# ── sprites and the calc preview ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sprites_carry_the_class_and_species_the_chroma_key_reads(dashboard):
    """`querySelectorAll('img.mon-sprite, img.enc-sprite')` + `data-species` is what the
    background-removal pass and every stylesheet rule select on."""
    srv, dom = dashboard
    imgs = [i for i in dom.find_all("img") if "mon-sprite" in (i.get("class") or "")]
    assert imgs, "no img.mon-sprite on a populated dashboard"
    assert all(i.get("data-species") for i in imgs), "a sprite without data-species"


@pytest.mark.asyncio
async def test_calc_preview_is_one_element_per_battling_player(dashboard):
    """`#calc-preview-{pid}[data-in-battle]` is read by _CALC_PREVIEW_JS. It is capability
    gated: a generation without battle calc renders none, and rendering one there would
    be a lie the script happily animates."""
    srv, dom = dashboard
    previews = [n for n in dom.walk() if (n.get("id") or "").startswith("calc-preview-")]
    ids = [n.get("id") for n in previews]
    assert len(ids) == len(set(ids)), f"duplicate calc previews: {ids}"
    if srv.adapter.game_id == "gen3_frlge":
        assert previews, "Gen 3 has battle calc and player B is mid-battle"
        assert all("data-in-battle" in n.attrs for n in previews)
    else:
        assert not previews, "calc preview rendered for a generation without battle calc"


@pytest.mark.asyncio
async def test_pre_rendered_html_fields_are_not_escaped(dashboard):
    """`sprite_html` and friends are HTML the server already built; a template that forgets
    `|safe` prints `&lt;img` and the sprite becomes text."""
    _, dom = dashboard
    assert "&lt;img" not in dom.text_content(), "an html field was escaped on the way in"
