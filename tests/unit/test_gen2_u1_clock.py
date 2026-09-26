"""U1_CLOCK coverage (tests/live/test_gen2_frame_align.py): every EVOLUTION_TITLES title hunts Route 30 for
a day-only target species (CATERPIE for crystal/gold, WEEDLE for silver; data/pokemon/evos_attacks.asm,
data/wild/johto_grass.asm ROUTE_30 day/nite slots) and so must pin the fixture's RTC
(gen2_synth_fixtures.day_clock) before launch.

Without a pin, the comment on U1_CLOCK says it plainly: "the fixture RTC runs on with the host clock" --
real wall-clock time, not emulated frames. A title left out of U1_CLOCK only passes when the live sweep
happens to reach its u1-evolution leg between 10:00 and 17:59 real time. That gap, not any code regression,
is what let gate/engine_sites/crystal's u1-evolution leg run its whole ~880-battle Route 30 hunt at hour
23/0/1/2 and never see a CATERPIE (fsw-postrc 2026-09-25, gate__engine_sites__crystal.cmd1 result:
"EV battle=... hour=23 map=26:1 ... foe=163/167/60/41" -- Route 30's NITE slots only -- for the whole leg,
"the model binder emitted 0 evolution events, not 1"). df04e065 (the pre-RC freeze, where this cell passed)
carries the exact same U1_CLOCK = {"silver": 11}; the two freezes just happened to run at different real
times of day.
"""
from __future__ import annotations

from tests.live.test_gen2_frame_align import EVOLUTION_TITLES, U1_CLOCK

DAY_START, DAY_END = 10, 18   # data/wild/johto_grass.asm ROUTE_30/31: the day slot is 10:00-17:59


def test_every_evolution_title_pins_its_fixture_clock():
    missing = set(EVOLUTION_TITLES) - U1_CLOCK.keys()
    assert not missing, (f"{missing} hunt a day-only Route 30 species (u1-evolution) but never pin the "
                          f"fixture RTC (gen2_synth_fixtures.day_clock) -- the leg only passes when the "
                          f"live sweep happens to run between {DAY_START}:00 and {DAY_END - 1}:59 real time")


def test_every_pinned_hour_is_inside_the_route30_day_window():
    for title, hour in U1_CLOCK.items():
        assert DAY_START <= hour < DAY_END, f"{title}: U1_CLOCK hour {hour} is outside the Route 30 day slot"
