"""S-1/S-2: the scripted gate's PHYSICAL receipt, pinned as a MODEL expectation.

A cartridge printed the SIGNALS line below — it is not something this repo computed — and it is
pinned here so a future regression in lua/gen1/signals.lua or in the per-title site table
(data/games/gen1_rby/engine_signals.json) is caught by a unit run instead of a 4-minute
emulator run. It is labelled PHYSICAL because that is what it is: every frame number in it was
observed by a running game through the real sites.

PROVENANCE. patch/build/test_gen1_scripted_gate_result.txt (written 2026-09-14 09:38), the last
scripted run on this machine: line 1 is `[test_gen1_scripted_gate] title=blue rom=d7037c83`,
and its phase list ends at `lab-loss-complete` — this is the LAB-ONLY chain, for Blue. There is
no `parcel`/`route1` phase and therefore no wild battle group, no `bag_received` and no
`save_witness` in the line. The full `lab,parcel,route1,save` chain (the shape the fixture
builds used: seven wild groups plus a bag/save tail) is not on disk — only this receipt is — so
this is what gets pinned. `check()` handles both shapes: everything about wild groups and the
tail is conditional, so re-pinning against a full-chain line is a one-line change and the
tests that assert the lab-only shape say so.

WHAT WOULD BREAK WITHOUT THIS. The site table is per-title and hand-derived from the decomps
(tools/build_pret_syms.py); the client's whole event stream is gated on it firing at the right
moments. A wrong address reads as plausible bytes and fires at the wrong frame or not at all,
and nothing else in the unit suite observes a real run.

SECOND RECEIPT, RELAYED — AND LABELLED AS SUCH. The full-chain line below (Red, chain
`lab,parcel,save`, 2026-09-14 ~09:5x) is NOT read from a file here: that run's save step was
refused, and its result file was later overwritten by the Blue lab-only run above. It was
relayed verbatim by the coordinator from that run's result file, so its ORIGIN is physical and
its provenance is not checkable from this repo — stated rather than blurred. Everything
asserted about it is structural (frame order, group shape, one-frame announcements, deltas),
so a line that was not actually observed would have to be self-consistent in all of those to
pass.
"""
from __future__ import annotations

import pytest

# Verbatim from the receipt (see PROVENANCE). Two frames are equal on purpose: the starter
# lands on the same frame its site fires (rule 1 below), which is why rule 7 is monotonic.
SIGNALS_LINE = (
    "starter_begin@7953 add_party_mon@7953 starter_end@8114 battle_begin@9161 "
    "add_party_mon@9162 battle_loop_head@9999 battle_loop_head@10507 battle_loop_head@11088 "
    "battle_loop_head@11664 battle_loop_head@12158 battle_loop_head@12737 "
    "battle_loop_head@13225 battle_loop_head@13652 battle_loop_head@14009 "
    "battle_loop_head@14371 battle_faint@14706 battle_end@15008")

# The full chain, Red, relayed (see SECOND RECEIPT in the module docstring): the Oak's-lab
# script, the rival battle, seven wild battles on Route 1 (the parcel route), then the first
# Poké Ball. No `save_witness` — that run's save step was refused.
FULL_CHAIN_LINE = (
    "starter_begin@7979 add_party_mon@7979 starter_end@8130 battle_begin@9063 "
    "add_party_mon@9064 battle_loop_head@9902 battle_loop_head@10448 battle_loop_head@11040 "
    "battle_loop_head@11552 battle_loop_head@12128 battle_loop_head@12720 "
    "battle_loop_head@13184 battle_loop_head@13648 battle_loop_head@14032 "
    "battle_loop_head@14416 battle_faint@14724 battle_end@15040 battle_begin@16128 "
    "wild_begin@16129 battle_loop_head@16724 battle_end@16865 battle_begin@17490 "
    "wild_begin@17491 battle_loop_head@18083 battle_end@18210 battle_begin@20449 "
    "wild_begin@20450 battle_loop_head@21044 battle_end@21170 battle_begin@27059 "
    "wild_begin@27060 battle_loop_head@27651 battle_end@27778 battle_begin@27927 "
    "wild_begin@27928 battle_loop_head@28515 battle_end@28642 battle_begin@28859 "
    "wild_begin@28860 battle_loop_head@29460 battle_end@29586 battle_begin@30024 "
    "wild_begin@30025 battle_loop_head@30612 battle_end@30753 bag_received@32111")

# Events that did not happen anywhere in this run; their presence would mean the client saw
# something the scripted play never did (or that a site is wired to the wrong address).
NEVER = ("blackout", "capture_box", "evolve", "npc_trade", "move_mon", "remove_pokemon")

OPENERS = ("battle_begin", "wild_begin")
TRAINER_COMPANION = "add_party_mon"


def parse(line: str) -> list[tuple[str, int]]:
    """`kind@frame ...` -> [(kind, frame), ...]."""
    out = []
    for token in line.split():
        kind, _, frame = token.partition("@")
        out.append((kind, int(frame)))
    return out


def _is_companion(kinds: list[str], i: int) -> bool:
    """True when the `wild_begin` at i is the second half of a `battle_begin` at i-1/i-2."""
    return kinds[i] == "wild_begin" and any(kinds[j] == "battle_begin" for j in (i - 1, i - 2)
                                            if j >= 0)


def _wild_groups(sequence: list[tuple[str, int]]) -> list[tuple[int, int, int]]:
    """(battle_begin, wild_begin, battle_end) indices for every wild battle in a receipt."""
    kinds = [kind for kind, _frame in sequence]
    out = []
    for i, kind in enumerate(kinds):
        if kind == "battle_begin" and kinds[i + 1:i + 2] == ["wild_begin"]:
            out.append((i, i + 1, kinds.index("battle_end", i)))
    return out


def check(sequence: list[tuple[str, int]]) -> None:
    """Every structural fact the client and docs/gen1_engine_sites.md rely on.

    A plain function rather than a test, so the negative control below can hand it a doctored
    sequence and watch it refuse.
    """
    kinds = [kind for kind, _frame in sequence]
    frames = [frame for _kind, frame in sequence]

    # Rule 7, as the data actually is: frames never go backwards, and the ONE place they stand
    # still is the Oak's-lab gift (rule 1). A literal "strictly increasing" contradicts rule 1
    # on this very receipt — starter_begin and its add_party_mon both fired at 7953.
    assert all(a <= b for a, b in zip(frames, frames[1:], strict=False)), (
        "a signal arrived out of order")
    repeats = [i for i, (a, b) in enumerate(zip(frames, frames[1:], strict=False)) if a == b]
    assert set(repeats) <= {0}, f"frames repeat outside the Oak's-lab gift: {repeats}"

    # Rule 1: the gift lands inside the Oak's-lab script, on the frame the site fires.
    assert kinds[:3] == ["starter_begin", "add_party_mon", "starter_end"], kinds[:3]
    assert sequence[1][1] == sequence[0][1], "add_party_mon did not share starter_begin's frame"

    # Rule 5: nothing of the kind happened, anywhere.
    forbidden = sorted(set(kinds) & set(NEVER))
    assert not forbidden, f"events the scripted play never produced: {forbidden}"

    # Rule 2 + 3 + 4: walk the battle groups.
    groups: list[dict] = []
    cur: dict | None = None
    for i, kind in enumerate(kinds):
        if kind == "battle_begin" or (kind == "wild_begin" and not _is_companion(kinds, i)):
            assert cur is None, f"a battle opened at index {i} while another was open"
            # A REAL wild battle announces itself TWICE: `battle_begin`, then `wild_begin`
            # one frame later (full-chain receipt below, seven times). So the OPENER does not
            # say which kind a group is — its companion token does. Classifying by the opener
            # alone labels every real wild battle a trainer battle and hides a faint inside it.
            cur = {"opener": kind, "wild": kind == "wild_begin", "at": i, "heads": 0,
                   "faints": 0, "end": None}
            groups.append(cur)
            if kind == "battle_begin":
                window = kinds[i + 1:i + 3]           # "within 2 frames"
                companions = [k for k in window
                              if k in (TRAINER_COMPANION, "wild_begin")]
                assert len(companions) == 1, (
                    f"battle_begin at index {i} is followed by {window}, not exactly one of "
                    f"{TRAINER_COMPANION}/wild_begin")
                cur["wild"] = companions[0] == "wild_begin"
        elif cur is not None:
            if kind == "battle_loop_head":
                cur["heads"] += 1
            elif kind == "battle_faint":
                cur["faints"] += 1
            elif kind == "battle_end":
                cur["end"] = i
                cur = None
    assert cur is None, "the sequence ends inside an open battle group"
    for group in groups:
        assert group["end"] is not None, f"a battle opened at index {group['at']} never ended"
        assert group["heads"] >= 1, f"no battle_loop_head inside the group at {group['at']}"

    # Rule 4, as an INVARIANT: a faint may only ever appear inside a trainer group. The count
    # for this particular run is pinned in the receipt tests below — a sequence with no faint
    # at all is legal (the full chain has wild groups and exactly one trainer loss).
    wild_faints = [g["at"] for g in groups if g["wild"] and g["faints"]]
    assert not wild_faints, f"battle_faint inside a wild battle at index {wild_faints}"

    # Rule 6, only for the full chain: the bag arrives after the last WILD battle and the
    # save witness closes the run.
    wild_ends = [g["end"] for g in groups if g["wild"]]
    if "bag_received" in kinds:
        assert wild_ends, "bag_received with no wild battle before it"
        assert kinds.index("bag_received") > max(wild_ends), (
            "bag_received did not follow the last wild battle")
    if "save_witness" in kinds:
        assert kinds.index("save_witness") == len(kinds) - 1, "save_witness is not last"
        if "bag_received" in kinds:
            assert kinds.index("bag_received") < kinds.index("save_witness")


PINNED = parse(SIGNALS_LINE)
FULL_CHAIN = parse(FULL_CHAIN_LINE)

# Kept ALONGSIDE the full-chain receipt for the one case that receipt cannot cover: the tail
# with a `save_witness` (its run had the save refused, so it ends at bag_received). The
# receipt covers the wild-group shape on real data; this covers the save tail.
STARTER = [("starter_begin", 10), ("add_party_mon", 10), ("starter_end", 20)]
WILD_GROUP = [("wild_begin", 100), ("battle_loop_head", 101), ("battle_end", 110)]
TAIL = [("bag_received", 200), ("save_witness", 210)]
WILD_AND_TAIL = STARTER + WILD_GROUP + TAIL


def test_the_pinned_receipt_satisfies_every_structural_rule():
    check(PINNED)


def test_the_receipt_is_the_lab_only_shape():
    """Pins WHAT is pinned: one trainer battle, no wild group, no bag/save tail.

    If a full-chain line is ever pasted in above, this fails on purpose — the reader then has
    to decide whether the old pin should be kept alongside it.
    """
    assert len(PINNED) == 17, f"{len(PINNED)} tokens; the lab-only Blue receipt has 17"
    assert [kind for kind, _f in PINNED].count("battle_begin") == 1
    assert "wild_begin" not in [kind for kind, _f in PINNED]
    assert "bag_received" not in [kind for kind, _f in PINNED]
    assert "save_witness" not in [kind for kind, _f in PINNED]


def test_the_only_repeated_frame_is_the_lab_gift():
    """A receipt-specific fact, so it lives here rather than in the general checker."""
    frames = [frame for _kind, frame in PINNED]
    repeats = [i for i, (a, b) in enumerate(zip(frames, frames[1:], strict=False)) if a == b]
    assert repeats == [0], f"equal frames outside the lab gift: {repeats}"


def test_the_run_lost_exactly_one_battle_and_it_was_the_rival():
    """Receipt-specific: this run's faint is the rival loss, inside the trainer battle."""
    kinds = [kind for kind, _f in PINNED]
    assert kinds.count("battle_faint") == 1, kinds
    assert kinds.index("battle_begin") < kinds.index("battle_faint") < kinds.index("battle_end")
    assert "wild_begin" not in kinds, "a wild group appeared in the lab-only receipt"


def test_the_receipt_never_claims_the_forbidden_events():
    kinds = [kind for kind, _f in PINNED]
    assert sorted(set(kinds) & set(NEVER)) == []


def test_a_wild_group_and_tail_are_accepted():
    """Positive control for the branches the lab-only receipt cannot reach."""
    check(WILD_AND_TAIL)


def test_a_faint_inside_a_wild_group_is_refused():
    """Negative control: the checker must be able to fail, or the assertions above are theatre."""
    doctored = STARTER + [("wild_begin", 100), ("battle_loop_head", 101),
                          ("battle_faint", 105), ("battle_end", 110)] + TAIL
    with pytest.raises(AssertionError):
        check(doctored)


def test_an_out_of_order_frame_is_refused():
    """The second negative control: ordering is what makes the receipt evidence of sequence."""
    doctored = parse(SIGNALS_LINE)
    doctored[5], doctored[6] = doctored[6], doctored[5]     # two loop heads out of order
    with pytest.raises(AssertionError):
        check(doctored)


# ── the full-chain receipt: the wild-battle shape ────────────────────────────────────────
def test_the_full_chain_receipt_satisfies_every_structural_rule():
    check(FULL_CHAIN)


def test_every_wild_battle_is_announced_twice_one_frame_apart():
    """`battle_begin`, then `wild_begin` ONE frame later — both, seven times.

    The client's signal branch accepts either kind; the engine emits both, so the second is
    the signal the handler actually keys on, and the one-frame delta is what says the two
    belong to one battle rather than two.
    """
    groups = _wild_groups(FULL_CHAIN)
    assert len(groups) == 7, f"{len(groups)} wild groups in the parcel route"
    for begin, wild, _end in groups:
        assert FULL_CHAIN[begin][0] == "battle_begin"
        assert FULL_CHAIN[wild][0] == "wild_begin"
        assert FULL_CHAIN[wild][1] - FULL_CHAIN[begin][1] == 1, (
            f"{FULL_CHAIN[begin]} -> {FULL_CHAIN[wild]} is not a one-frame announcement")


def test_every_wild_group_ends_without_a_faint():
    """The route escaped all seven by RUN, so none of them contains a battle_faint."""
    for begin, _wild, end in _wild_groups(FULL_CHAIN):
        span = [kind for kind, _f in FULL_CHAIN[begin:end + 1]]
        assert span[0] == "battle_begin" and span[-1] == "battle_end", span
        assert "battle_faint" not in span, span
        assert span.count("battle_loop_head") >= 1, span


def test_the_trainer_group_is_the_only_one_with_an_enemy_party_build():
    """`add_party_mon` at begin+1 marks the trainer battle — ReadTrainer building its team.

    The other add_party_mon is the Oak's-lab starter gift, at index 1, before any battle.
    """
    kinds = [kind for kind, _f in FULL_CHAIN]
    builds = [i for i, kind in enumerate(kinds) if kind == "add_party_mon"]
    assert len(builds) == 2, builds
    assert builds[0] == 1, "the first add_party_mon is not the starter gift"
    trainer = [i for i in builds if kinds[i - 1] == "battle_begin"]
    assert len(trainer) == 1, f"trainer companions at {trainer}"
    spans = [(begin, end) for begin, _wild, end in _wild_groups(FULL_CHAIN)]
    assert not any(begin <= i <= end for i in builds for begin, end in spans), builds


def test_the_first_pokeball_arrives_after_the_last_wild_battle():
    """bag_received@32111 — and because that run's save was refused, it is the LAST token."""
    kinds = [kind for kind, _f in FULL_CHAIN]
    assert kinds.index("bag_received") > max(end for _b, _w, end in _wild_groups(FULL_CHAIN))
    assert kinds[-1] == "bag_received"
    assert "save_witness" not in kinds, "this receipt is the save-refused run"


def test_a_faint_inside_a_real_wild_group_is_refused():
    """Negative control built from the REAL shape, not a toy.

    This is the case the previous checker missed: it classified a group by its opener, so
    every real wild battle (opened by `battle_begin`, named by `wild_begin`) looked like a
    trainer battle and a faint inside one went unnoticed. The faint is moved out of the
    trainer group and into the first wild group here.
    """
    kinds = [kind for kind, _f in FULL_CHAIN]
    faint = kinds.index("battle_faint")
    first_wild_end = _wild_groups(FULL_CHAIN)[0][2]
    doctored: list[tuple[str, int]] = []
    for i, token in enumerate(FULL_CHAIN):
        if i == first_wild_end:                      # just before that group's battle_end
            doctored.append(("battle_faint", FULL_CHAIN[i][1] - 1))
        if i != faint:                               # the trainer's faint is moved, not copied
            doctored.append(token)
    with pytest.raises(AssertionError):
        check(doctored)
