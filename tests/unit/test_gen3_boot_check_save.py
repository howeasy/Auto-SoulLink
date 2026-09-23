"""lua/tests/gen3_boot_check.lua save witness vs gen3_codec.qualify_flash (card gen3-P3-C3-27).

Flash images are built with the codec, fed to the Lua through lupa with a fake flash memory
domain, and judged by both. No emulator.
"""
from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "Flash"


def _data(sid: int, size: int) -> bytes:
    return bytes((sid * 7 + j) & 0xFF for j in range(size))


def _put(image: bytearray, index: int, raw: bytes) -> None:
    image[index * codec.SECTOR_SIZE:(index + 1) * codec.SECTOR_SIZE] = raw


def _slot(image: bytearray, counter: int, layout: list[dict], ids=None, slot=None) -> None:
    """Write `ids` into consecutive physical sectors of the slot pret uses for `counter`."""
    base = codec.NUM_SECTORS_PER_SLOT * (counter % 2 if slot is None else slot)
    for i, sid in enumerate(range(14) if ids is None else ids):
        _put(image, base + i, codec.write_sector(_data(sid, layout[sid]["size"]), sid, counter, layout))


def valid(counter: int, cfru: bool = False) -> bytearray:
    """A good save at `counter` beside the previous one at counter-1."""
    layout = codec.slot_layout(codec.CHUNK_SIZE_CFRU if cfru else codec.CHUNK_SIZE_VANILLA)
    image = bytearray(codec.FLASH_SIZE)
    _slot(image, counter - 1, layout)
    _slot(image, counter, layout)
    return image


def old_expression(image: bytes, ctr: int) -> int:
    """The pre-fix sectors_at: all 32 sectors, id read from the unused +0xFF0."""
    n = 0
    for s in range(codec.SECTORS_COUNT):
        raw = image[s * codec.SECTOR_SIZE:(s + 1) * codec.SECTOR_SIZE]
        if (int.from_bytes(raw[0xFF8:0xFFC], "little") == codec.SECTOR_SIGNATURE
                and int.from_bytes(raw[0xFFC:0x1000], "little") == ctr
                and int.from_bytes(raw[0xFF0:0xFF2], "little") < 14):
            n += 1
    return n


CTR = 6
LAYOUT = codec.slot_layout()
BASE = codec.NUM_SECTORS_PER_SLOT * (CTR % 2)


def duplicate_ids() -> bytearray:
    image = valid(CTR)
    _put(image, BASE + 13, codec.write_sector(_data(12, LAYOUT[12]["size"]), 12, CTR, LAYOUT))
    return image


def invalid_id() -> bytearray:
    image = valid(CTR)
    image[(BASE + 5) * codec.SECTOR_SIZE + codec.OFF_SECTOR_ID] = 0x20
    return image


def seven_per_slot() -> bytearray:
    image = bytearray(codec.FLASH_SIZE)
    _slot(image, CTR, LAYOUT, ids=range(7), slot=0)
    _slot(image, CTR, LAYOUT, ids=range(7, 14), slot=1)
    return image


def bad_checksum() -> bytearray:
    image = valid(CTR)
    image[(BASE + 3) * codec.SECTOR_SIZE + 0x10] ^= 0xFF
    return image


class World:
    def __init__(self, image: bytes, title: str = "firered"):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.SLINK_ROOT = ROOT.as_posix()
        g.flash = bytes(image)
        self.lua.execute("""
            frame, dialog, locked, swapped, a_seen, flushes = 0, 0, 0, false, false, 0
            -- START menu fake (card C4-F2): sStartMenuWindowId/sStartMenuCursorPos/
            -- sNumStartMenuItems/sStartMenuOrder at their REAL addresses (independently
            -- hardcoded here, not read off the module -- this is what makes it a falsifier
            -- rather than a tautology). Defaults are "already open, one row, already on SAVE"
            -- (window=1 i.e. not WINDOW_NONE, count=1, order={4}, cursor=0) so every test above
            -- this one, which never touches start-menu state, is unaffected.
            -- down_before_open counts a Down seen while the window still reads WINDOW_NONE --
            -- the exact leak-onto-the-field bug the fix must never reintroduce.
            -- open_delay models the fade-in gap PER OPEN (every real Start press, not just the
            -- first): the window drops to WINDOW_NONE the instant Start is pressed and comes
            -- back `open_delay` frames later, so a caller that reopens the menu several times
            -- (the old row search's own "close, reopen, walk one more row" cycle) is tested on
            -- every one of those opens, not just the first.
            WINDOW_ADDR, COUNT_ADDR, CURSOR_ADDR, ORDER_ADDR = 0x0203ABE0, 0x020370F5, 0x020370F4, 0x020370F6
            WINDOW_NONE = 0xFF
            startmenu_window, startmenu_open_delay, startmenu_open_at = 1, 0, nil
            startmenu_cursor, startmenu_count, startmenu_order = 0, 1, {4}
            down_before_open = 0
            -- C4-6t: the menu READS input only once Task_StartMenuHandleInput runs and sets
            -- sStartMenuCallback = StartCB_HandleInput, `ready_delay` frames after the window
            -- appears (pret start_menu.c:376-392); an A before that is dropped. The SAVE row's A
            -- then moves the callback to StartCB_Save2. startmenu_cb starts STALE (whatever an
            -- earlier menu left: pret never resets it).
            CB_ADDR, TASKS_ADDR = 0x020370F0, 0x03005090
            TASK_FN, CB_INPUT, CB_SAVE2 = 0x0806F1F1, 0x0806F281, 0x0806F5C9
            startmenu_cb, startmenu_task, startmenu_ready_delay, startmenu_ready_at = CB_INPUT, 1, 0, nil
            -- initial_lock_until models the settle-period lock PHYSICAL 2026-09-23 found: a
            -- fresh CONTINUE can hold sLockFieldControls locked for 100+ frames before any
            -- input at all. start_before_free counts a Start seen while that lock still holds
            -- -- gen3_boot_check.lua must wait it out, never press Start hoping it lands.
            initial_lock_until, start_before_free = 0, 0
            local function rd(fmt) return function(a) return (string.unpack(fmt, flash, a + 1)) end end
            local rd32 = rd("<I4")
            memory = {read_u16_le = rd("<I2"),
                read_u32_le = function(a)
                    if a == CB_ADDR then return startmenu_cb end
                    if a == TASKS_ADDR then return startmenu_task == 1 and TASK_FN or 0 end
                    if a > TASKS_ADDR and a < TASKS_ADDR + 16 * 40 then return 0 end
                    return rd32(a)
                end,
                read_u8 = function(a)
                    if a == TASKS_ADDR + 4 then return startmenu_task end
                    if a > TASKS_ADDR and a < TASKS_ADDR + 16 * 40 then return 0 end
                    if a == WINDOW_ADDR then return startmenu_window end
                    if a == COUNT_ADDR then return startmenu_count end
                    if a == CURSOR_ADDR then return startmenu_cursor end
                    if a >= ORDER_ADDR and a < ORDER_ADDR + 9 then
                        return startmenu_order[a - ORDER_ADDR + 1] or 0
                    end
                    return (string.unpack("<I1", flash, a + 1))
                end}
            console = {log = function() end}
            local function true_save_row()
                for i = 0, startmenu_count - 1 do
                    if startmenu_order[i + 1] == 4 then return i end
                end
                return nil
            end
            -- close_on_a: only an A press seen AFTER the flash has already swapped (the
            -- fake's stand-in for "counter/slot already validated") can clear `locked` --
            -- gen3_boot_check.lua must not press A before that point either.
            joypad = {set = function(t)
                if close_on_a and swapped and t and t.A then a_seen = true end
                -- the SAVE row's A moves sSaveDialogCB off whatever it held (0 on a cold
                -- boot, SaveDialogCB_ReturnSuccess after an earlier save); stuck = it never
                -- moves. Gated on the CURSOR actually sitting on the real save row -- a press
                -- on any other row is a real game pressing something else, not SAVE (this is
                -- what makes the falsifier below distinguish "found the row" from "pressed A
                -- on whatever row it happened to be on", the old helper's actual bug class).
                if t and t.A and not dialog_stuck and startmenu_cursor == true_save_row()
                   and startmenu_task == 1 and startmenu_cb == CB_INPUT then
                    dialog = 0x0806F001
                    startmenu_cb = CB_SAVE2
                end
                if t and t.Start then
                    if frame < initial_lock_until then start_before_free = start_before_free + 1 end
                    startmenu_window = WINDOW_NONE
                    startmenu_open_at = frame + startmenu_open_delay
                    startmenu_task, startmenu_ready_at = 0, nil
                    -- mirrors pret's LockPlayerFieldControls, taken out the instant Start is
                    -- processed (start_menu.c ShowStartMenu); close_at/close_on_a/a_seen below
                    -- model the save flow's own later release, same as before.
                    locked = 1
                end
                if t and t.Down then
                    if startmenu_window == WINDOW_NONE then down_before_open = down_before_open + 1 end
                    -- no wrap modeled: save_via_menu never needs it (see gen3_boot_check.lua's
                    -- own comment above the row walk) and a real bug relying on wrap would show
                    -- up here as "cursor never reached the SAVE row", not a false pass.
                    if startmenu_cursor < startmenu_count - 1 then
                        startmenu_cursor = startmenu_cursor + 1
                    end
                end
            end}
            client = {screenshot = function() end, saveram = function() flushes = flushes + 1 end}
            emu = {framecount = function() return frame end,
                   frameadvance = function()
                       frame = frame + 1
                       if startmenu_open_at and frame >= startmenu_open_at then
                           startmenu_window, startmenu_open_at = 1, nil
                           startmenu_ready_at = frame + startmenu_ready_delay
                       end
                       if startmenu_ready_at and frame >= startmenu_ready_at then
                           startmenu_task, startmenu_cb, startmenu_ready_at = 1, CB_INPUT, nil
                       end
                       if initial_lock_until > 0 and frame == initial_lock_until then locked = 0 end
                       if swap_at and frame >= swap_at then flash, swap_at = pending, nil; swapped = true end
                       if close_at and frame >= close_at then locked = 0 end
                       if a_seen then locked = 0 end
                   end}
        """)
        self.G = self.lua.eval(f'dofile("{(ROOT / "lua/tests/gen3_boot_check.lua").as_posix()}")')
        self.G.title = title
        # The menu drive is stubbed at the predicate: callback2 always on the field, the save
        # dialog OPEN is the `dialog` global (sSaveDialogCB), its CLOSE is now
        # `field_controls_locked` -> the `locked` global the frame/joypad hooks control
        # (gen3_boot_check.lua stopped polling `dialog` to detect closed -- pret never resets
        # sSaveDialogCB to NULL, so that predicate can only ever detect OPEN).
        self.lua.execute("""
            local G = ...
            G.pred = function(cp, name)
                if name == "save_dialog_cb" then return dialog, 0 end
                if name == "field_controls_locked" then return locked, 0 end
                return 1, 1
            end
        """, self.G)

    def sectors_at(self, ctr):
        return self.G.sectors_at(DOMAIN, ctr)

    def configure_start_menu(self, *, open_delay=0, cursor=0, count=1, order=(4,), ready_delay=0,
                             stale_cb=None):
        """open_delay=0: the window reads open ~1 frame after every Start press (the common
        case for every test above this one). open_delay=<n>: the window reads WINDOW_NONE for
        n frames after EVERY Start press (initial open and every reopen) -- models the fade-in
        gap the physical bug leaked a Down into."""
        g = self.lua.globals()
        g.startmenu_window = 1
        g.startmenu_open_delay, g.startmenu_open_at = open_delay, None
        g.startmenu_cursor, g.startmenu_count = cursor, count
        g.startmenu_order = self.lua.table(*order)
        g.down_before_open = 0
        g.startmenu_ready_delay = ready_delay
        if stale_cb is not None:
            g.startmenu_cb, g.startmenu_task = stale_cb, 0

    def save(self, after: bytes, swap_at=200, close_at=None, close_on_a=False,
             dialog=0, dialog_stuck=False, initial_lock_frames=0):
        """initial_lock_frames: sLockFieldControls reads locked for this many frames from the
        very start, before any Start press -- models the settle-period lock PHYSICAL 2026-09-23
        found. 0 (default): free from the start, the common case for every test above this one
        (a Start press itself still locks it, same as the real game, until close_at/close_on_a
        release it)."""
        g = self.lua.globals()
        g.dialog = dialog
        g.locked = 1 if initial_lock_frames else 0
        g.initial_lock_until, g.start_before_free = initial_lock_frames, 0
        g.pending, g.swap_at, g.close_at = bytes(after), swap_at, close_at
        g.close_on_a, g.swapped, g.a_seen, g.dialog_stuck = close_on_a, False, False, dialog_stuck
        return self.G.save_via_menu(self.lua.table(), DOMAIN)


@pytest.mark.parametrize("build", [duplicate_ids, invalid_id, seven_per_slot, bad_checksum])
def test_countermodels_fail(build):
    image = bytes(build())
    assert old_expression(image, CTR) >= 14            # it fooled the old witness
    assert not codec.qualify_flash(image)[0]           # the codec refuses it
    n, why = World(image).sectors_at(CTR)
    assert n < 14 and why, (n, why)                    # and so does the fixed witness


@pytest.mark.parametrize("title,cfru", [("firered", False), ("radical_red", True)])
def test_valid_image_passes(title, cfru):
    image = bytes(valid(CTR, cfru))
    assert codec.qualify_flash(image, cfru=cfru) == (True, "ok")
    assert tuple(World(image, title).sectors_at(CTR)) == (14, None)


def test_checksum_table_follows_the_title():
    # A CFRU image judged with the vanilla chunk table must fail on checksums.
    n, why = World(bytes(valid(CTR, cfru=True)), "firered").sectors_at(CTR)
    assert n < 14 and "checksum" in why


def test_save_succeeds_and_flushes():
    w = World(bytes(valid(CTR - 1)))
    ok, before, after, why = w.save(valid(CTR), close_at=400)
    assert (ok, before, after, why) == (True, CTR - 1, CTR, None)
    assert w.lua.globals().flushes == 1


def test_dialog_timeout_returns_false():
    w = World(bytes(valid(CTR - 1)))
    ok, _, after, why = w.save(valid(CTR), close_at=None)
    assert ok is False and after == CTR and "never closed" in why
    assert w.lua.globals().flushes == 0


def test_save_closes_only_after_the_helper_presses_a():
    # No timer (close_at=None) -- only an A press seen after the slot is already validated
    # can clear the lock. card C3-30: the pre-fix helper never presses A while it waits (it
    # only polled sSaveDialogCB, which pret never clears either -- start_menu.c:608-842), so
    # this must fail against the unfixed lua/tests/gen3_boot_check.lua and pass once it does.
    w = World(bytes(valid(CTR - 1)))
    ok, before, after, why = w.save(valid(CTR), close_at=None, close_on_a=True)
    assert (ok, before, after, why) == (True, CTR - 1, CTR, None)
    assert w.lua.globals().flushes == 1


def test_flush_failure_returns_false():
    w = World(bytes(valid(CTR - 1)))
    w.lua.execute('client.saveram = function() error("disk full") end')
    ok, _, _, why = w.save(valid(CTR), close_at=400)
    assert ok is False and "flush failed" in why and "disk full" in why


def test_invalid_new_slot_returns_false():
    w = World(bytes(valid(CTR - 1)))
    ok, _, _, why = w.save(bad_checksum(), close_at=400)
    assert ok is False and "bad checksum" in why


def test_stale_dialog_callback_is_not_an_open_dialog():
    # A second save in one boot: sSaveDialogCB still holds the last save's
    # SaveDialogCB_ReturnSuccess (pret never clears it). If no row ever opens the dialog, the
    # helper must say so -- a bare "~= 0" check "opened" on the first A of any row.
    w = World(bytes(valid(CTR - 1)))
    ok, before, after, why = w.save(valid(CTR), close_at=400, dialog=0x0806F0F1, dialog_stuck=True)
    assert ok is False and after == before and "never opened" in why


def test_second_save_in_one_boot_opens_on_change():
    w = World(bytes(valid(CTR - 1)))
    ok, _, after, why = w.save(valid(CTR), close_at=400, dialog=0x0806F0F1)
    assert (ok, after, why) == (True, CTR, None)


# --- root-cause fix (card gen3-P4-C4-F2): witnessed row navigation, not a counted search -------
#
# PHYSICAL 2026-09-23 (gen3-P4-C4-F): the old row SEARCH re-tapped Start and pressed Down right
# after, with no check that the menu window actually existed yet. Field control locks the
# instant Start registers, but the list window (sStartMenuWindowId) is created a few frames
# later; a Down sent in that gap could still land on whatever the wrong row before it opened,
# walking the player across a map connection mid-save. gen3_boot_check.lua now gates every
# navigation press on the window witness and finds the SAVE row from the engine's own
# sStartMenuOrder/sNumStartMenuItems instead of hunting for it by counting presses.


def test_no_down_presses_before_the_start_menu_window_is_open():
    """The falsifier: a Down must never be sent while sStartMenuWindowId still reads
    WINDOW_NONE. SAVE sits at row 2 of a 3-row menu; the cursor starts at row 0, so 2 Downs are
    needed once the window opens -- but EVERY Start press (the first open and any reopen) is
    followed by a 40-frame fade-in gap, well past every fixed cadence this driver uses (Start's
    own tap is only 3 frames), so any Down sent before the window is back is exactly the
    physical bug. Red against the pre-fix helper (see the manual revert-test note in the card
    report); green here."""
    w = World(bytes(valid(CTR - 1)))
    w.configure_start_menu(open_delay=40, cursor=0, count=3, order=(1, 2, 4))
    ok, before, after, why = w.save(valid(CTR), close_at=400)
    assert (ok, before, after, why) == (True, CTR - 1, CTR, None)
    assert w.lua.globals().down_before_open == 0
    assert w.lua.globals().startmenu_cursor == 2   # landed on the SAVE row itself


@pytest.mark.parametrize("cursor,order,expect_downs", [
    (0, (4,), 0),            # single-row menu, already on SAVE
    (0, (1, 2, 3, 4), 3),    # SAVE last
    (2, (1, 2, 4, 5, 6), 0),  # already sitting on the SAVE row
])
def test_save_row_found_from_the_order_table_not_a_fixed_index(cursor, order, expect_downs):
    w = World(bytes(valid(CTR - 1)))
    w.configure_start_menu(cursor=cursor, count=len(order), order=order)
    ok, _, after, why = w.save(valid(CTR), close_at=400)
    assert (ok, after, why) == (True, CTR, None)
    assert w.lua.globals().startmenu_cursor == order.index(4)


def test_no_save_row_in_the_order_table_is_a_named_failure():
    w = World(bytes(valid(CTR - 1)))
    w.configure_start_menu(cursor=0, count=3, order=(1, 2, 3))   # no action id 4 anywhere
    ok, before, after, why = w.save(valid(CTR), close_at=400)
    assert ok is False and before == after == CTR - 1
    assert "no SAVE row" in why


def test_start_menu_window_never_opening_is_a_named_failure_not_a_hang():
    w = World(bytes(valid(CTR - 1)))
    w.configure_start_menu(open_delay=10_000_000, cursor=0, count=1, order=(4,))
    ok, before, after, why = w.save(valid(CTR), close_at=400)
    assert ok is False and before == after == CTR - 1
    assert "window never opened" in why


def test_waits_out_the_initial_settle_lock_before_ever_pressing_start():
    """PHYSICAL 2026-09-23 (live gen3-P4-C4-F boot-check on firered_party_battle.sav): right
    after boot_to_field returns, sLockFieldControls read locked for ~125 frames with zero
    input -- a settle period the pre-C4-F2 helper never waited for, so its first Start press
    (issued immediately) was silently swallowed and it hung ("the start menu window never
    opened"). The fix waits for the field_controls_locked witness to read free before ever
    touching Start."""
    w = World(bytes(valid(CTR - 1)))
    w.configure_start_menu(cursor=0, count=1, order=(4,))
    ok, before, after, why = w.save(valid(CTR), close_at=600, initial_lock_frames=125)
    assert (ok, before, after, why) == (True, CTR - 1, CTR, None)
    assert w.lua.globals().start_before_free == 0


def test_field_never_freeing_is_a_named_failure_not_a_hang():
    w = World(bytes(valid(CTR - 1)))
    w.configure_start_menu(cursor=0, count=1, order=(4,))
    ok, before, after, why = w.save(valid(CTR), close_at=None, initial_lock_frames=10_000_000)
    assert ok is False and before == after == CTR - 1
    assert "never freed" in why



# ── C4-6t: a second save in one boot (live LG save_then_write) ──────────────────────────────
SAVE_RETURN_SUCCESS = 0x0806F9E1   # SaveDialogCB_ReturnSuccess|1: sSaveDialogCB after a save


def test_a_second_save_after_a_first_save_opens_and_completes():
    """Live LG save_then_write: "the second save: SAVE failed: the save dialog never opened". The
    cursor already sat on SAVE from the first save, so the A went in the frame the window
    appeared -- before Task_StartMenuHandleInput read input -- and was dropped. The helper must
    wait for the menu's input chain, then see the callback leave StartCB_HandleInput."""
    w = World(bytes(valid(CTR - 1)))
    w.configure_start_menu(count=5, order=(0, 1, 2, 3, 4), cursor=0, ready_delay=12)
    ok, before, after, why = w.save(valid(CTR), close_on_a=True)
    assert (ok, before, after, why) == (True, CTR - 1, CTR, None)
    g = w.lua.globals()
    # the second save: cursor still on SAVE (row 4), stale sSaveDialogCB, stale StartCB_Save2
    assert g.startmenu_cursor == 4
    w.configure_start_menu(count=5, order=(0, 1, 2, 3, 4), cursor=4, ready_delay=12,
                           stale_cb=0x0806F5C9)
    ok, before, after, why = w.save(valid(CTR + 1), swap_at=g.frame + 200, close_on_a=True,
                                    dialog=SAVE_RETURN_SUCCESS)
    assert (ok, before, after, why) == (True, CTR, CTR + 1, None), why
    assert g.flushes == 2


def test_a_menu_that_never_reads_input_is_named():
    w = World(bytes(valid(CTR - 1)))
    w.configure_start_menu(ready_delay=100000)
    ok, _, _, why = w.save(valid(CTR), close_at=400)
    assert ok is False and "never took input" in why, why



def test_the_save_witness_is_false_for_every_stale_shape():
    """Codex cx-3e10776a: after an earlier save sSaveDialogCB is non-zero, so the old probe
    witness (`~= 0`) passed on ANY submenu's A. The shared witness must be FALSE for a completed
    save (task gone, callback left on StartCB_Save2), a cancelled dialog (callback back on
    StartCB_HandleInput) and another submenu's A, and TRUE only while Save1/Save2 runs under the
    live Task_StartMenuHandleInput."""
    w = World(bytes(valid(CTR)))
    g = w.lua.globals()
    ready, running = w.G.start_menu_witness("firered")
    g.dialog = SAVE_RETURN_SUCCESS                        # the stale pointer, in every case
    old_witness = lambda: w.G.pred(w.lua.table(), "save_dialog_cb")[0] != 0  # noqa: E731 (HEAD's)
    for task, cb, want in ((0, 0x0806F5C9, False),       # completed save: task destroyed
                           (1, 0x0806F281, False),       # cancelled: back on HandleInput
                           (1, 0x0806F481, False),       # BAG row A: StartMenuBagCallback
                           (1, 0x0806F5A5, True),        # THIS press: StartCB_Save1
                           (1, 0x0806F5C9, True)):       # the dialog running: StartCB_Save2
        g.startmenu_task, g.startmenu_cb = task, cb
        assert running() is want, (task, hex(cb))
        assert old_witness() is True                      # HEAD's witness: true in all five
    g.startmenu_task, g.startmenu_cb = 1, 0x0806F281
    assert ready() is True
