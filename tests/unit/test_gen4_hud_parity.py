"""Card S part 1: MODEL reds for accepted Gen 4 HUD flows, not PHYSICAL evidence.

World drives production; qualification scenarios override no client/reducer/HUD/hook function.
The four positive tests went red on d21147b8 before the implementation. Revert controls
load that same client source with exactly one HUD call deleted, leaving the real reducer,
inputs, core and hook logic intact. The self-check proves the HUD recorder itself works.
"""
import inspect

import pytest

from tests.unit.gen4_world import CTX, ROOT, SD, Mon, World

TITLES = ("heartgold", "soulsilver", "heartgold_hge")
AREA = "function(id) return 'route_' .. id, 'Route ' .. id end"
# SOURCE lua/gen3/client.lua:405-410; lua/hud.lua:408-410 supplies the omitted duration.
NUZLOCKE = ("Nuzlocke Start!", 180)
# SOURCE lua/gen3/client.lua:603-605: exact spaces, RGB and duration, not a new UX.
ENCOUNTER = ("show", "** NEW ENCOUNTER **  Route 61", 255, 220, 60, 240)
# SOURCE lua/gen3/client.lua:716-719.
WHITEOUT = ("show", "WHITED OUT", 255, 60, 60, 300)
# SOURCE lua/gen3/client.lua:1015 and lua/core/deferred.lua:152. Card S adopts KO'd
# for confirmed D7 completion; no request/hold/failed write is a confirmed KO.
LINK_FAINT = ("show", "!! Ember KO'd", 255, 80, 80, 360)


def boot(title, *, balls=False, seeded=True, **kwargs):
    w = World(title, party=[Mon(0x5A3C91E7, hp=20, max_hp=20),
                            Mon(0x0BADF00D, hp=11, max_hp=11)],
              balls=balls, area_of=kwargs.pop("area_of", AREA), **kwargs)
    w.boot(80)
    if seeded:
        w.reply({"cmd": "resolved_areas", "areas": []})
        w.advance(3)
    return w


def nuzlocke_calls(w):
    # The accepted G3 caller omits the duration; H.nuzlocke_start's default is 180.
    # Normalize only that public optional argument, never absent calls or their text.
    return [(row[1], row[2] if len(row) > 2 and row[2] is not None else 180)
            for row in w.hud if row[0] == "nuzlocke_start"]


def encounter_calls(w):
    return [row for row in w.hud if row[0] == "show" and row[1].startswith("** NEW ENCOUNTER **")]


def whiteout_calls(w):
    return [row for row in w.hud if row[0] == "show" and row[1] == "WHITED OUT"]


def set_balls(w, quantity):
    bag = w.prof["bag"]
    slot = w.dyn + w.arrays[bag["array_id"]][1] + bag["balls_pocket_off"]
    for name, value in (("id", bag["ball_ids"][0]), ("quantity", quantity)):
        field = bag["slot_fields"][name]
        w.w(slot + field["off"], value, field["size"])


def set_map(w, map_id):
    w.w(w.dyn + w.arrays[5][1] + w.prof["location"]["map_off"], map_id)


def lose_battle(w):
    w.enter_battle()
    w.advance(5)
    w.set_outcome(w.prof["battle_enums"]["outcomes"]["lose"])
    w.advance(3)
    w.leave_battle()
    w.advance(12)


def armed_faint(title, *, nickname="Ember", **kwargs):
    w = boot(title, **kwargs)
    w.enter_battle(cmd=5)
    w.advance(3)
    w.reply({"cmd": "force_faint", "key": w.party[0].key, "nickname": nickname})
    w.advance(1)
    return w


@pytest.mark.parametrize("title", TITLES)
def test_hud_double_records_shared_show_prompt_and_nuzlocke_start(title):
    w = boot(title)
    # SOURCE lua/core/session.lua:282-287 routes these commands through the supplied H.
    w.reply({"cmd": "hud_show", "text": "HUD self-check", "r": 1, "g": 2, "b": 3, "frames": 41},
            {"cmd": "gui_prompt", "text": "Prompt self-check", "r": 4, "g": 5, "b": 6, "frames": 42})
    w.advance(1)
    assert ("show", "HUD self-check", 1, 2, 3, 41) in w.hud
    assert ("prompt", "Prompt self-check", 4, 5, 6, 42) in w.hud
    assert len(w.events("hello")) == 1
    assert callable(w.hud_t.nuzlocke_start), "World HUD double lacks nuzlocke_start (harness prerequisite)"
    # Exercise the recorder itself; no production function is replaced or manufactured.
    w.hud_t.nuzlocke_start("Nuzlocke Start!", 180)
    assert w.hud == [("show", "HUD self-check", 1, 2, 3, 41),
                     ("prompt", "Prompt self-check", 4, 5, 6, 42),
                     ("nuzlocke_start", "Nuzlocke Start!", 180)]


@pytest.mark.parametrize("title", TITLES)
def test_nuzlocke_start_once_on_first_ball_edge_after_silent_seed(title, pre=None):
    w = boot(title, balls=False, pre=pre)
    assert w.events("hello")[0]["has_pokeballs"] is False
    assert nuzlocke_calls(w) == []
    set_balls(w, 1)
    w.advance(35)
    assert w.events("tick")[-1]["has_pokeballs"] is True
    assert nuzlocke_calls(w) == [NUZLOCKE], "missing first-ball Nuzlocke Start! HUD trigger"
    assert [row[0] for row in w.hud] == ["nuzlocke_start"]
    w.advance(80)
    set_balls(w, 0)
    w.advance(35)
    set_balls(w, 1)
    w.advance(35)
    assert nuzlocke_calls(w) == [NUZLOCKE]  # the run's ball gate latches upward
    w.connected = False
    w.advance(2)
    w.connected = True
    w.advance(35)
    assert len(w.events("hello")) == 2
    assert nuzlocke_calls(w) == [NUZLOCKE]


@pytest.mark.parametrize("title", TITLES)
def test_stocked_save_attach_and_rehello_never_announce_nuzlocke_start(title):
    # SOURCE lua/gen3/client.lua:1182: stocked-save hello is a resume, not acquisition.
    w = boot(title, balls=True)
    assert w.events("hello")[0]["has_pokeballs"] is True
    assert nuzlocke_calls(w) == []
    w.connected = False
    w.advance(2)
    w.connected = True
    w.advance(35)
    assert len(w.events("hello")) == 2
    assert w.events("hello")[-1]["has_pokeballs"] is True
    assert nuzlocke_calls(w) == []


@pytest.mark.parametrize("title", TITLES)
def test_new_encounter_on_later_debounced_area_entry_and_unresolved_reentry(title, pre=None):
    w = boot(title, balls=True, pre=pre)
    assert encounter_calls(w) == []  # SOURCE G3 client.lua:1183-1184 silently seeds the initial area.
    set_map(w, 61)
    w.advance(1)
    assert encounter_calls(w) == []  # G4 poll_events.lua:151-158 requires two agreeing area frames.
    w.advance(1)
    assert [e["area_id"] for e in w.events("area_enter")] == ["route_61"]
    assert encounter_calls(w) == [ENCOUNTER], "missing debounced NEW ENCOUNTER HUD trigger"
    assert w.hud == [ENCOUNTER]
    # SOURCE G3 client.lua:598-608 has no independent shown-once latch while unresolved.
    set_map(w, 60)
    w.advance(2)
    set_map(w, 61)
    w.advance(2)
    assert [row for row in encounter_calls(w) if row[1] == ENCOUNTER[1]] == [ENCOUNTER, ENCOUNTER]
    # SOURCE core/session.lua:294-295 only rearms eligibility; an area change is still required.
    w.reply({"cmd": "resolved_areas", "areas": ["route_61"]})
    w.advance(3)
    set_map(w, 60)
    w.advance(2)
    set_map(w, 61)
    w.advance(2)
    assert [row for row in encounter_calls(w) if row[1] == ENCOUNTER[1]] == [ENCOUNTER, ENCOUNTER]
    w.reply({"cmd": "unresolve_area", "area_id": "route_61"})
    w.advance(3)
    assert [row for row in encounter_calls(w) if row[1] == ENCOUNTER[1]] == [ENCOUNTER, ENCOUNTER]
    set_map(w, 60)
    w.advance(2)
    set_map(w, 61)
    w.advance(2)
    assert [row for row in encounter_calls(w) if row[1] == ENCOUNTER[1]] == [ENCOUNTER] * 3
    route_60 = ("show", "** NEW ENCOUNTER **  Route 60", 255, 220, 60, 240)
    assert w.hud == [ENCOUNTER, route_60, ENCOUNTER, route_60, route_60, ENCOUNTER]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("guard", ["no_balls", "unseeded", "empty_area", "resolved", "in_battle"])
def test_new_encounter_suppressed_by_each_accepted_guard(title, guard):
    # SOURCE G3 client.lua:603-605. Every negative drives a real area transition except
    # the empty id, which G4 refuses to announce at all (poll_events.lua:151).
    area = "function(id) return id == 61 and '' or 'route_' .. id, 'Route ' .. id end"
    w = boot(title, balls=guard != "no_balls", seeded=guard != "unseeded",
             area_of=area if guard == "empty_area" else AREA)
    assert encounter_calls(w) == []
    if guard == "resolved":
        w.reply({"cmd": "resolved_areas", "areas": ["route_61"]})
        w.advance(3)
    if guard == "in_battle":
        w.enter_battle()
        w.advance(3)
    set_map(w, 61)
    w.advance(4)
    assert encounter_calls(w) == []
    if guard == "empty_area":
        assert w.events("area_enter") == []
    else:
        assert [e["area_id"] for e in w.events("area_enter")] == ["route_61"]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.xfail("gift_area" not in inspect.signature(World).parameters,
                   strict=True, reason="card R gift_area")
def test_new_encounter_suppressed_in_a_gift_area(title):
    # SOURCE G3 client.lua:121-138,603-605. The title-owned gift predicate comes from R.
    w = boot(title, balls=True, gift_area=lambda area: area == "route_61")
    set_map(w, 61)
    w.advance(4)
    assert [e["area_id"] for e in w.events("area_enter")] == ["route_61"]
    assert encounter_calls(w) == []


@pytest.mark.parametrize("title", TITLES)
def test_whiteout_popup_once_per_event_not_per_idle_poll(title, pre=None):
    w = boot(title, pre=pre)
    lose_battle(w)
    assert len(w.events("whiteout")) == 1
    assert whiteout_calls(w) == [WHITEOUT], "whiteout event has no WHITED OUT HUD popup"
    w.advance(80)
    assert len(w.events("whiteout")) == 1
    assert whiteout_calls(w) == [WHITEOUT]
    lose_battle(w)
    assert len(w.events("whiteout")) == 2
    assert whiteout_calls(w) == [WHITEOUT, WHITEOUT]
    assert w.hud == [WHITEOUT, WHITEOUT]


@pytest.mark.parametrize("title", TITLES)
def test_game_over_and_rebuild_do_not_repeat_the_whiteout_popup(title):
    w = boot(title)
    lose_battle(w)
    assert len(w.events("whiteout")) == 1
    before = list(whiteout_calls(w))  # positive test above separately requires one, not zero
    w.reply({"cmd": "game_over"}, {"cmd": "rebuild_start", "text": "REBUILDING: Ember"},
            {"cmd": "rebuild_done"})
    w.advance(80)
    assert ("set_game_over",) in w.hud
    assert ("set_rebuilding", "REBUILDING: Ember") in w.hud
    assert ("clear_rebuilding",) in w.hud
    assert len(w.events("whiteout")) == 1
    assert whiteout_calls(w) == before


@pytest.mark.parametrize("title", TITLES)
def test_confirmed_d7_linked_faint_popup_once_and_no_commanded_echo(title, pre=None):
    w = armed_faint(title, pre=pre)
    assert w.hud == []  # request/arm is not a KO
    w.dispatch_seam(cmd=w.d7["seam"]["cmd"])
    w.advance(1)
    assert len(w.writes) == 3  # real production verified writes: battle HP, party HP, faint bit
    assert w.hud == [LINK_FAINT], "confirmed D7 completion has no linked-faint HUD popup"
    w.dispatch_seam(cmd=w.d7["seam"]["cmd"])
    w.advance(20)
    assert w.hud == [LINK_FAINT]
    w.party[0].hp = 0  # native party copy-back after battle; model RAM only
    w.write_party()
    w.leave_battle()
    w.advance(20)
    assert w.events("faint") == []
    assert w.hud == [LINK_FAINT]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("case", ["request", "hold", "noop", "refusal"])
def test_d7_never_announces_a_request_hold_noop_or_refusal(title, case):
    w = armed_faint(title)
    if case == "hold":
        w.advance(60)  # no seam execution: normal input has not yet reached the safe write point
    elif case == "noop":
        w.set_battle_hp(0, 0)
        w.dispatch_seam(cmd=w.d7["seam"]["cmd"])
        w.advance(1)
    elif case == "refusal":
        w.dispatch_seam(cmd=w.d7["seam"]["cmd"], r1=CTX + 4)
        w.advance(1)
    assert w.writes == []
    assert w.hud == []
    assert w.events("faint") == []


@pytest.mark.parametrize("title", TITLES)
def test_first_valid_stocked_bag_observation_is_a_silent_seed(title):
    # An unreadable array is not a measured empty bag. Never announce acquisition on its recovery.
    def unreadable_bag(w):
        save = w.prof["save"]
        header = SD + save["array_headers_off"] + w.prof["bag"]["array_id"] * save["array_header_size"]
        w.w(header + 4, 0)  # array size, invalid only for the real bag reader

    w = boot(title, balls=True, pre=unreadable_bag)
    assert w.events("hello")[0]["has_pokeballs"] is False
    assert nuzlocke_calls(w) == []
    save = w.prof["save"]
    bag_id = w.prof["bag"]["array_id"]
    header = SD + save["array_headers_off"] + bag_id * save["array_header_size"]
    w.w(header + 4, w.arrays[bag_id][0])
    w.advance(35)
    assert w.events("tick")[-1]["has_pokeballs"] is True
    assert nuzlocke_calls(w) == []


@pytest.mark.parametrize("title", TITLES)
def test_d7_completion_without_a_nickname_uses_the_accepted_player_label(title):
    # SOURCE lua/core/deferred.lua:58-60: never use a key/code as player-facing fallback text.
    w = armed_faint(title, nickname=None)
    w.dispatch_seam(cmd=w.d7["seam"]["cmd"])
    w.advance(1)
    assert len(w.writes) == 3
    assert w.hud == [("show", "!! Your Pokemon KO'd", 255, 80, 80, 360)]


@pytest.mark.parametrize("title", TITLES)
def test_partial_d7_write_fault_never_reports_a_confirmed_ko(title):
    w = armed_faint(title)
    w.drop_writes.add(w.battler_addr(0, "hp_off"))
    w.dispatch_seam(cmd=w.d7["seam"]["cmd"])
    w.advance(1)
    assert len(w.writes) == 3  # attempted writes are insufficient: readback refused their result
    assert w.hud == []
    assert w.events("faint") == []


REVERTS = (
    (test_nuzlocke_start_once_on_first_ball_edge_after_silent_seed,
     'p.hud.nuzlocke_start("Nuzlocke Start!")', "missing first-ball"),
    (test_new_encounter_on_later_debounced_area_entry_and_unresolved_reentry,
     'p.hud.show("** NEW ENCOUNTER **  " .. (e.data.loc_name or ""), 255, 220, 60, 240)', "missing debounced"),
    (test_whiteout_popup_once_per_event_not_per_idle_poll,
     'p.hud.show("WHITED OUT", 255, 60, 60, 300)', "whiteout event has no"),
    (test_confirmed_d7_linked_faint_popup_once_and_no_commanded_echo,
     'p.hud.show("!! " .. name .. " KO\'d", 255, 80, 80, 360)', "confirmed D7 completion has no"),
)


def client_revert(call, replacement=""):
    def load_mutant(w):
        source = (ROOT / "lua/gen4/client.lua").read_text(encoding="utf-8")
        assert source.count(call) == 1, "revert control no longer names exactly one production line"
        mutant = source.replace(call, replacement)
        real_dofile, load = w.lua.globals().dofile, w.lua.eval("load")

        def dofile(path):
            if str(path).replace("\\", "/").endswith("lua/gen4/client.lua"):
                return load(mutant, "@revert-client")()
            return real_dofile(path)

        w.lua.globals().dofile = dofile
    return load_mutant


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("scenario,call,reason", REVERTS, ids=[row[0].__name__ for row in REVERTS])
def test_each_hud_trigger_has_a_red_revert_control(title, scenario, call, reason):
    # Removing only presentation must fail the corresponding wire-proven qualification scenario.
    with pytest.raises(AssertionError, match=reason):
        scenario(title, pre=client_revert(call))


@pytest.mark.parametrize("title", TITLES)
def test_landed_d7_cannot_defer_again_when_ending_party_is_unreadable(title, pre=None):
    # SOURCE core/session.lua:189-200 can defer an ending entry WITHOUT battle_write.
    # The callback uses the prior battle snapshot (gen4/client.lua d7_plan), so a final
    # frame may land the write before the field/party copy-back becomes readable.
    w = armed_faint(title, pre=pre)
    w.party[0].hp = 0
    w.write_party()
    w.field(launched=0, driver_state=0)  # battle has ended, native save checkpoint not ready yet
    w.fail_party_reads()
    w.dispatch_seam(cmd=w.d7["seam"]["cmd"])
    w.advance(1)
    assert w.read_fault_hits  # the real read layer refused the ending party, no function override
    assert len(w.writes) == 3
    assert w.hud == [LINK_FAINT]
    deferred_at_close = len(w.session.deferred["items"])
    w.field()
    w.advance(20)
    assert w.hud == [LINK_FAINT], "landed D7 produced a second checkpoint KO popup"
    assert deferred_at_close == 0, "landed D7 was deferred on the unreadable ending frame"
    assert len(w.writes) == 3  # no deferred faint-slot write
    assert w.events("faint") == []


@pytest.mark.parametrize("title", TITLES)
def test_transient_save_read_failure_cannot_rearm_nuzlocke_start(title, pre=None):
    w = boot(title, pre=pre)
    set_balls(w, 1)
    w.advance(35)
    assert nuzlocke_calls(w) == [NUZLOCKE]
    set_balls(w, 0)
    w.run_to((w.frame // 60 + 1) * 60 - 1)
    w.fail_reads(w.prof["save_ptr"]["address"], 4)
    w.advance(4)  # core validation sees unreadable save, calls on_reset, then read recovers
    assert w.read_fault_hits
    assert len(w.events("hello")) == 2
    set_balls(w, 1)
    w.advance(35)
    assert nuzlocke_calls(w) == [NUZLOCKE], "transient save failure rearmed Nuzlocke Start"


@pytest.mark.parametrize("title", TITLES)
def test_transient_save_read_failure_cannot_lose_the_first_ball_edge(title):
    w = boot(title)
    assert nuzlocke_calls(w) == []
    w.run_to((w.frame // 60 + 1) * 60 - 1)
    w.fail_reads(w.prof["save_ptr"]["address"], 4)
    set_balls(w, 1)
    w.advance(35)
    assert w.read_fault_hits
    assert w.events("tick")[-1]["has_pokeballs"] is True
    assert nuzlocke_calls(w) == [NUZLOCKE], "transient save failure lost the first-ball edge"


@pytest.mark.parametrize("title", TITLES)
def test_readable_empty_new_game_rearms_nuzlocke_start(title, pre=None):
    w = boot(title, pre=pre)
    set_balls(w, 1)
    w.advance(35)
    assert nuzlocke_calls(w) == [NUZLOCKE]
    old_party = w.party
    w.party = []
    w.write_party()
    trainer = w.prof["trainer"]
    trainer_id = w.dyn + w.arrays[trainer["array_id"]][1] + trainer["profile_off_in_array"] + trainer["id_off"]
    w.w(trainer_id, 0)  # SOURCE drv.game_is_live: readable OT=0 AND party count=0 is pre-game
    set_balls(w, 0)
    w.advance(65)
    w.w(trainer_id, 0x12345678)
    w.party = old_party
    w.write_party()
    w.advance(4)
    assert len(w.events("hello")) == 2
    assert w.events("hello")[-1]["has_pokeballs"] is False, "new game kept the old ball latch"
    set_balls(w, 1)
    w.advance(35)
    assert nuzlocke_calls(w) == [NUZLOCKE, NUZLOCKE]


@pytest.mark.parametrize("title", TITLES)
def test_latched_balls_still_resolve_no_catch_after_the_bag_is_empty(title, pre=None):
    # SOURCE G3 client.lua:405-410,656-659: acquiring balls starts the run permanently.
    w = boot(title, pre=pre)
    set_balls(w, 1)
    w.advance(35)
    set_balls(w, 0)
    w.advance(35)
    assert w.events("tick")[-1]["has_pokeballs"] is True
    # A transient validation reset clears PE's independent upward latch. This prevents
    # that older latch from masking a regression to raw empty-bag snapshots in the driver.
    w.run_to((w.frame // 60 + 1) * 60 - 1)
    w.fail_reads(w.prof["save_ptr"]["address"], 4)
    w.advance(4)
    assert w.read_fault_hits
    w.enter_battle()
    w.advance(5)
    w.leave_battle()
    w.advance(12)
    assert [{k: e[k] for k in ("area_id", "species_id", "level")} for e in w.events("no_catch")] == [
        {"area_id": "route_60", "species_id": 16, "level": 3}], "lost latched no_catch after reducer reset"
    assert nuzlocke_calls(w) == [NUZLOCKE]


@pytest.mark.parametrize("title", TITLES)
def test_completed_noop_cannot_become_a_checkpoint_ko_on_unreadable_close(title):
    w = armed_faint(title)
    w.set_battle_hp(0, 0)
    w.party[0].hp = 0
    w.put(w.battle_party_rec(0), w.party[0].party_raw())  # coherent native zero in BOTH battle copies
    w.write_party()
    w.field(launched=0, driver_state=0)
    w.fail_party_reads()
    w.dispatch_seam(cmd=w.d7["seam"]["cmd"])
    w.advance(1)
    assert w.read_fault_hits
    assert w.writes == []
    assert any("target already at zero" in row for row in w.logs)
    assert len(w.session.deferred["items"]) == 0
    w.field()
    w.advance(20)
    assert w.writes == []
    assert w.hud == []  # the native game's own faint was never our commanded KO


@pytest.mark.parametrize("title", TITLES)
def test_retiring_one_d7_preserves_the_other_owed_faint(title):
    w = boot(title)
    w.enter_battle(btype=2, local=((0, 0), (2, 1)))
    w.advance(3)
    w.reply({"cmd": "force_faint", "key": w.party[0].key, "nickname": "Ember"},
            {"cmd": "force_faint", "key": w.party[1].key, "nickname": "Other"})
    w.advance(1)
    w.party[0].hp = 0
    w.write_party()
    w.field(launched=0, driver_state=0)
    w.fail_party_reads()
    w.dispatch_seam(cmd=w.d7["seam"]["cmd"])
    w.advance(1)
    assert w.read_fault_hits
    assert len(w.writes) == 3
    assert [e["key"] for e in w.session.deferred["items"].values()] == [w.party[1].key]
    w.field()
    w.advance(20)
    assert len(w.writes) == 4  # other entry still lands its checkpoint party-HP write
    assert w.hud == [LINK_FAINT, ("show", "!! Other KO'd", 255, 80, 80, 360)]


REVIEW_REVERTS = (
    (test_latched_balls_still_resolve_no_catch_after_the_bag_is_empty,
     "has_pokeballs = has_pokeballs(true) }",
     "has_pokeballs = p.has_pokeballs and p.has_pokeballs() or false }",
     "lost latched no_catch after reducer reset"),
    (test_landed_d7_cannot_defer_again_when_ending_party_is_unreadable,
     "table.remove(session.battle_pending, i)", "", "second checkpoint KO"),
    (test_transient_save_read_failure_cannot_rearm_nuzlocke_start,
     "if trainer and trainer.otid == 0 and cleared_party and #cleared_party == 0 then",
     "if true then", "transient save failure rearmed"),
    (test_readable_empty_new_game_rearms_nuzlocke_start,
     "st.has_pokeballs = nil", "", "new game kept the old ball latch"),
)


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("scenario,line,replacement,reason", REVIEW_REVERTS,
                         ids=[row[0].__name__ for row in REVIEW_REVERTS])
def test_completion_and_save_reset_fixes_have_red_revert_controls(title, scenario, line, replacement, reason):
    with pytest.raises(AssertionError, match=reason):
        scenario(title, pre=client_revert(line, replacement))
