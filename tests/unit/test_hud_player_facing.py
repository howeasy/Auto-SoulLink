"""HUD-PLAYER-FACING: the on-screen HUD is player-facing only.

Two rules, one file because they share a consumer.

**No internal names on screen.** No pending counters, hold reasons, internal code names,
debug ids or ticket names. Everything the client queues as `msgbox` / `gui_prompt` /
`hud_show` is drawn verbatim by `lua/hud.lua` (H.prompt / H.show) and reaches Gen 3 through
`lua/core/session.lua:281-286`. A mon key, a raw `area_id` and a client's `error` code are
the operator's, not the player's -- they belong on the console and in the log line the same
code path already writes.

**Every glyph the screen shows is folded by `lua/hud.lua`'s `sanitize`.** BizHawk marshals
strings byte-by-byte and mangles anything >= U+0080, so a character that is not in
GLYPH_MAP arrives as tofu. The gender-clause prompt embeds a male/female sign, so the fold
is load-bearing here, not theoretical.

Falsifiers: before the fix the key-collision prompt carried `AABBCCDD:11223344` and
`route_1`, and the rival-swap banner carried `patch_required`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState

REPO = Path(__file__).resolve().parents[2]

# A mon key exactly as it travels the wire (Gen 3: personality:otId).
MON_KEY = re.compile(r"\b[0-9A-F]{8}:[0-9A-F]{8}\b")

# The internal codes a native rival_team_replaced ack carries as `error`.
RIVAL_ERRORS = ("patch_required", "patch_failed", "patch_timeout")


def _gen3(tmp_path, **kw):
    return SoulLinkState(data_dir=str(tmp_path), adapter=Gen3Adapter(rom_type="firered"), **kw)


def _mon(key, species=16, nickname=""):
    return MonInfo(key=key, level=5, species=species, nickname=nickname)


def _colliding_with_a_live_link(tmp_path):
    """A live link on A's side; the next capture of A's key collides with it."""
    st = _gen3(tmp_path)
    live = LinkEntry(area_id="route_1", a=_mon("AABBCCDD:11223344"),
                     b=_mon("EEFF0011:22334455"), status=LinkStatus.ALIVE)
    st.links.append(live)
    st._index_entry(live)
    return st._check_link_violation(
        _mon("AABBCCDD:11223344", nickname="PIDGEY"), _mon("99887766:33445566"))


# ── internal ids must not reach the screen ───────────────────────────────────────────

def test_a_key_collision_prompt_shows_no_mon_key(tmp_path):
    violation, _pid = _colliding_with_a_live_link(tmp_path)
    assert violation is not None, "the collision check stopped firing"
    assert not MON_KEY.search(violation), f"mon key on screen: {violation!r}"


def test_a_key_collision_prompt_shows_no_raw_area_id(tmp_path):
    violation, _pid = _colliding_with_a_live_link(tmp_path)
    assert "route_1" not in violation, f"raw area_id on screen: {violation!r}"


def test_a_key_collision_prompt_still_tells_the_player(tmp_path):
    """The control. Forbidding the whole message would satisfy the two above."""
    violation, _pid = _colliding_with_a_live_link(tmp_path)
    assert "Key collision" in violation
    assert "PIDGEY" in violation, "name the mon, not the key"


@pytest.mark.parametrize("err", RIVAL_ERRORS)
def test_a_rival_swap_failure_banner_shows_no_error_code(tmp_path, err):
    st = _gen3(tmp_path)
    st._handle_rival_team_replaced("a", {"trainer_id": 327, "species_ids": [], "error": err})
    shown = _shown(st, "a")
    assert shown, "a failed swap must still say something"
    assert err not in shown, f"internal error code on screen: {shown!r}"


def test_a_rival_swap_failure_banner_still_tells_the_player(tmp_path):
    st = _gen3(tmp_path)
    st._handle_rival_team_replaced("a", {"trainer_id": 327, "species_ids": [],
                                         "error": "patch_required"})
    assert "Rival Swap failed" in _shown(st, "a")


def test_a_successful_rival_swap_queues_no_failure_banner(tmp_path):
    """The control on the other side of that branch."""
    st = _gen3(tmp_path)
    st._handle_rival_team_replaced("a", {"trainer_id": 327, "species_ids": [1, 2]})
    assert not [c for c in st.queued_commands["a"] if c["cmd"] == "hud_show"]


def _shown(st, pid):
    return " ".join(c["text"] for c in st.queued_commands[pid] if "text" in c)


# ── the client's own HUD line: no rejection reason ──────────────────────────────────

def test_the_identity_refusal_banner_shows_no_rejection_reason():
    """lua/core/session.lua draws this one itself. The reason is an internal code
    ("collision", "ambiguous match", ...); the console line above the banner has it."""
    src = (REPO / "lua" / "core" / "session.lua").read_text(encoding="utf-8")
    banner = re.search(r'hud\.show\("IDENTITY CHANGE REFUSED[^"]*"([^)]*)\)', src)
    assert banner, "the identity-refusal banner disappeared; it is player-facing"
    assert "cmd.reason" not in banner.group(0), (
        f"a rejection reason is interpolated into the HUD banner: {banner.group(0)!r}")


# ── every glyph the screen shows is folded to ASCII ──────────────────────────────────

@pytest.fixture(scope="module")
def sanitize():
    """The real lua/hud.lua sanitize, run under lupa -- not a Python re-implementation."""
    lupa = pytest.importorskip("lupa", reason="lupa is needed to run lua/hud.lua")
    path = (REPO / "lua" / "hud.lua").as_posix()
    return lupa.LuaRuntime().eval(f'dofile("{path}").sanitize')


def _clause_prompts(tmp_path):
    """The exact strings the Gen 3 server puts in front of the player for each clause.

    Each pair is picked so the clause under test is the FIRST to fire: the check order in
    _check_link_violation is collision, species, gender, type, so a pair that also shared a
    family or a gender would report its neighbour instead.
    """
    st = _gen3(tmp_path, species_lock=True, gender_lock=True, type_lock=True)
    pairs = (
        (_mon("11111111:11111111", species=16, nickname="PIDGEY"),   # Pidgey
         _mon("22222222:22222222", species=17)),                    # Pidgeotto: one family
        (_mon("11111111:11111111", species=16),                      # Pidgey    50% gender
         _mon("22222222:22222222", species=19)),                    # Rattata   50%, same gender
        (_mon("11111111:11111111", species=81),                      # Magnemite genderless
         _mon("22222222:22222222", species=100)),                   # Voltorb   both Electric
    )
    prompts = []
    for a, b in pairs:
        result = st._check_link_violation(a, b)
        if result:
            prompts.append(result[0])
    return prompts


def test_every_clause_prompt_is_folded_to_drawable_ascii(tmp_path, sanitize):
    """The gender sign is the one non-ASCII character the server still emits; GLYPH_MAP
    folds it, so what BizHawk is handed is printable ASCII."""
    prompts = _clause_prompts(tmp_path)
    assert len(prompts) == 3, f"expected one prompt per clause, got {prompts!r}"
    assert any(ord(ch) > 0x7F for p in prompts for ch in p), \
        "no non-ASCII left to fold -- the glyph half of this test proves nothing"
    for prompt in prompts:
        folded = sanitize(prompt)
        assert all(0x20 <= ord(ch) <= 0x7E for ch in folded), \
            f"a character outside GLYPH_MAP reached the overlay: {prompt!r} -> {folded!r}"
