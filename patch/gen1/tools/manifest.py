"""The Gen 1 companion patch manifest — one description, two delivery paths.

`build.py` applies this to the two pinned CLEAN dumps and is the deterministic build tool.
`inject.py` applies the same spans to a ROM whose hash we cannot know in advance -- a
randomized cartridge -- using the structural checks instead of the hash.

They must not drift, so neither owns the manifest: this module does. Every span names the
bytes it expects to find BEFORE it is written, which is what makes the structural path
safe without a hash to lean on.

Nothing here imports a toolchain, so the injector can run anywhere.
"""

# Where the module is linked, and therefore where it is injected.
HOOK_BANK = 0x3F
BANK_SIZE = 0x4000
INJECT_OFFSET = HOOK_BANK * BANK_SIZE          # 0xFC000
HOOK_TARGET = 0x4000                            # bank $3F is mapped at $4000

# The `farcall TrackPlayTime` inside VBlank. Unique in the ROM — verified by scanning.
#   ld b, $06 / ld hl, $4DEE / call Bankswitch($35D6)
HOOK_SITE = 0x2094
HOOK_ORIGINAL = bytes([0x06, 0x06, 0x21, 0xEE, 0x4D, 0xCD, 0xD6, 0x35])


# ── The START-menu row ──────────────────────────────────────────────────────────────────
# A declarative, bank-qualified manifest. Every span names the bytes it expects to find
# BEFORE it writes, so a ROM that is not the exact dump these offsets were derived from
# fails loudly rather than being silently corrupted -- the same posture as the hook site.
#
# Red and Blue are byte-identical across all of this, verified by reading both dumps, so
# one manifest serves both.
#
# WHAT THIS INCREMENT DOES, AND DELIBERATELY DOES NOT. It adds a SLINK row to the START
# menu and nothing else: selecting it falls through to CloseStartMenu exactly as EXIT does,
# because the dispatch chain in the home bank ends after `cp 5` and everything past it
# closes the menu. That is the point -- the risky structural change ships inert and
# visible, and the panel it will eventually open is a separate step that cannot break the
# menu if it goes wrong.
#
# WHY THE ROW GOES AFTER EXIT. The dispatch is a `cp N / jp z` chain over wCurrentMenuItem
# (home/start_menu.asm), so inserting anywhere earlier would renumber every item below it
# and silently re-point the menu. Appending leaves indices 0-6 exactly where they are.

MENU_STUB_ADDR = 0x00BE      # ROM0 free space, always mapped, reachable from bank 1
SLINK_TEXT_ADDR = 0x00D1     # immediately after the stub

# Gen 1's charset puts 'A' at $80, so a letter is $80 + (c - 'A'); $50 terminates.
# Cross-checked against the ROM's own "POKéDEX@" at 0x0718F, which reads 8F 8E 8A BA 83 84 97 50.
SLINK_TEXT = bytes([0x92, 0x8B, 0x88, 0x8D, 0x8A, 0x50])          # "SLINK@"

# The stub the DrawStartMenu tail is redirected into. It prints EXIT where EXIT already
# went, advances one menu row (two tile rows), then prints SLINK -- so EXIT keeps its
# position and its index, and SLINK becomes the new last item.
MENU_STUB = bytes([
    0xE5,                    # push hl              -- hl is where EXIT belongs
    0x11, 0xAF, 0x71,        # ld de, StartMenuExitText ($71AF, bank 1: the caller's bank)
    0xCD, 0x55, 0x19,        # call PlaceString ($1955, home)
    0xE1,                    # pop hl
    0x11, 0x28, 0x00,        # ld de, 40            -- SCREEN_WIDTH * 2, one menu row
    0x19,                    # add hl, de
    0x11, SLINK_TEXT_ADDR & 0xFF, SLINK_TEXT_ADDR >> 8,   # ld de, SlinkText
    0xCD, 0x55, 0x19,        # call PlaceString
    0xC9,                    # ret
])

# ── Making the row do something ─────────────────────────────────────────────────────────
# The dispatch is a `cp N / jp z` chain in the HOME bank ending in a fallthrough to
# CloseStartMenu, and there is no room to insert a seventh comparison in place. So the last
# comparison is replaced by a jump into ROM0's second free run, which re-does that
# comparison, adds ours, and falls back to the same fallthrough.
#
# ONE COMPARISON COVERS BOTH MENU SHAPES. home/start_menu.asm does `inc a` before
# dispatching when the player has no Pokedex, precisely so the handlers can use fixed
# numbers -- so SLINK is index 7 at the dispatch whether it was drawn as 6 or 7.
TRAMPOLINE_ADDR = 0x3FA6
PANEL_ENTRY_ADDR = 0x3FB3
SLINK_PANEL_ADDR = 0x4100        # pinned by the SECTION in slink.asm
HOOK_BANK_BYTE = 0x3F

TRAMPOLINE = bytes([
    0xFE, 0x05,                  # cp 5
    0xCA, 0xF6, 0x75,            # jp z, StartMenu_Option ($75F6, bank 4 is mapped here)
    0xFE, 0x07,                  # cp 7                    -- SLINK, both menu shapes
    0xCA, PANEL_ENTRY_ADDR & 0xFF, PANEL_ENTRY_ADDR >> 8,
    0xC3, 0x70, 0x2B,            # jp CloseStartMenu       -- the original fallthrough
])

# Bankswitch saves the caller's bank on the stack and restores it when our code returns,
# which is why the panel can live in bank $3F and still come back to a menu that expects
# bank 4. The existing VBlank hook relies on the same property.
PANEL_ENTRY = bytes([
    0x06, HOOK_BANK_BYTE,        # ld b, $3F
    0x21, SLINK_PANEL_ADDR & 0xFF, SLINK_PANEL_ADDR >> 8,
    0xCD, 0xD6, 0x35,            # call Bankswitch
    0xC3, 0xDF, 0x2A,            # jp RedisplayStartMenu   -- reopen the menu behind it
])

# (offset, expected original, replacement, why)
MENU_PATCHES = [
    (0x00BE, bytes(len(MENU_STUB)), MENU_STUB,
     "print stub in ROM0 free space (zero run 0x00BE-0x00FF, 66 bytes)"),
    (SLINK_TEXT_ADDR, bytes(len(SLINK_TEXT)), SLINK_TEXT,
     "the string SLINK@"),

    # DrawStartMenu, bank 1. The box is drawn before the item count is known, so both the
    # with-Pokedex and without-Pokedex heights need the extra menu row (two tile rows).
    (0x7114, bytes([0x0E]), bytes([0x10]),
     "TextBoxBorder height, with Pokedex: 14 -> 16 rows"),
    (0x711D, bytes([0x0C]), bytes([0x0E]),
     "TextBoxBorder height, without Pokedex: 12 -> 14 rows"),
    (0x714D, bytes([0x06]), bytes([0x07]),
     "wMaxMenuItem without Pokedex: 6 -> 7"),
    (0x7157, bytes([0x07]), bytes([0x08]),
     "wMaxMenuItem with Pokedex: 7 -> 8"),

    # `ld de, StartMenuExitText` + `call PlaceString` -> `call MenuStub` + padding. The
    # three trailing bytes become nops rather than being removed, because shortening the
    # routine would move everything after it.
    (0x7183, bytes([0x11, 0xAF, 0x71, 0xCD, 0x55, 0x19]),
     bytes([0xCD, MENU_STUB_ADDR & 0xFF, MENU_STUB_ADDR >> 8, 0x00, 0x00, 0x00]),
     "DrawStartMenu tail: print EXIT + SLINK via the stub"),

    # home/start_menu.asm wraps the cursor with its own hardcoded item counts, separate
    # from wMaxMenuItem. Without these the cursor cannot reach the new last row: it would
    # wrap from OPTION back to the top and SLINK would be visible but unselectable.
    (0x2B0C, bytes([0x06]), bytes([0x07]),
     "up-wrap target index: 6 -> 7 (the `dec a` below still handles the no-Pokedex case)"),
    (0x2B25, bytes([0x07]), bytes([0x08]),
     "down-wrap item count: 7 -> 8 (the `dec c` below still handles no-Pokedex)"),

    (TRAMPOLINE_ADDR, bytes(len(TRAMPOLINE)), TRAMPOLINE,
     "dispatch trampoline in ROM0's second free run (0x3FA6-0x3FFF, 90 bytes)"),
    (PANEL_ENTRY_ADDR, bytes(len(PANEL_ENTRY)), PANEL_ENTRY,
     "bank-$3F entry for the panel, returning to the menu"),
    (0x2B6B, bytes([0xFE, 0x05, 0xCA, 0xF6, 0x75]),
     bytes([0xC3, TRAMPOLINE_ADDR & 0xFF, TRAMPOLINE_ADDR >> 8, 0x00, 0x00]),
     "the last dispatch comparison -> jump to the trampoline"),
]

# Trade spans, independently read from both pinned clean ROMs and the linked
# trade-only image (trade_service.asm; trade_receptionist.asm:1-15).
# The bridge occupies reserved RST padding declared in pret/home/header.asm:3-38.
# Its exact 32-byte replacement is image[0x0001:0x0021] from rgblink; build.py
# rejects a future source change that would drift from this toolchain-free manifest.
# The span is exactly the section's length and no wider: rgblink pads with 0x00 while
# the clean ROM keeps 0xFF in every RST slot ($08, $10, ..., $30), so a wider slice
# would silently rewrite the `rst $28` byte outside the section.
TRADE_BRIDGE_BEFORE = bytes.fromhex(
    "00000000000000ff00000000000000ff00000000000000ff"
    "00000000000000ff"
)
TRADE_BRIDGE_AFTER = bytes.fromhex(
    "c2b320f5c5d5e5fae9dea72006fa12c53d2008"
    "063f210045cdd635e1d1c1f1c9"
)
TRADE_DELAY_BEFORE = bytes.fromhex("20fac9")
TRADE_DELAY_AFTER = bytes.fromhex("c30100")  # jp SlinkDelayFrameBridge, linked 00:0001
TRADE_DISPATCH_BEFORE = bytes.fromhex("21c5710601cdd6351809")
TRADE_DISPATCH_AFTER = bytes.fromhex("21004c063fcdd6351812")
# The Joypad site (slink.asm "SLink Joypad stub"): Joypad's `call _Joypad` ($01A4, inside
# `homecall _Joypad` at $019A) is pointed at a 23-byte stub in the free ROM0 tail that runs
# _Joypad and then the SFX service, so a menu waiting for input still plays the request.
# Both spans read identically from the two pinned dumps.
JOYPAD_CALL_SITE = 0x01A4
JOYPAD_CALL_BEFORE = bytes.fromhex("cd0040")   # call _Joypad (03:4000)
JOYPAD_STUB_ADDR = 0x3FBE
JOYPAD_CALL_AFTER = bytes((0xCD, JOYPAD_STUB_ADDR & 0xFF, JOYPAD_STUB_ADDR >> 8))
JOYPAD_STUB_BEFORE = bytes(23)
JOYPAD_STUB_AFTER = bytes.fromhex(
    "cd0040fae9dea7c8c5d5e5063f212f40cdd635e1d1c1c9"
)
MENU_PATCHES.extend([
    (0x0001, TRADE_BRIDGE_BEFORE, TRADE_BRIDGE_AFTER,
     "DelayFrame foreground service bridge in reserved RST padding"),
    (JOYPAD_CALL_SITE, JOYPAD_CALL_BEFORE, JOYPAD_CALL_AFTER,
     "Joypad's call _Joypad -> SlinkJoypadStub (menu-loop SFX service)"),
    (JOYPAD_STUB_ADDR, JOYPAD_STUB_BEFORE, JOYPAD_STUB_AFTER,
     "SlinkJoypadStub in the free ROM0 tail"),
    (0x20B7, TRADE_DELAY_BEFORE, TRADE_DELAY_AFTER,
     "DelayFrame tail -> SlinkDelayFrameBridge"),
    (0x29C3, TRADE_DISPATCH_BEFORE, TRADE_DISPATCH_AFTER,
     "Cable Club receptionist -> SlinkReceptionist in bank $3F"),
])

# Never written, at any offset, for any reason: the cartridge header carries the Nintendo
# logo the boot ROM checks and the entrypoint at $0100. The free run found by scanning
# runs 0x00BE-0x0100 INCLUSIVE, and that last byte is the entrypoint's `nop` -- so the
# usable span stops at 0x00FF and this range exists to make that non-negotiable.
PROTECTED_RANGE = (0x0100, 0x014F)


ROMS = {
    "red": ("Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
            "ea9bcae617fdf159b045185467ae58b2e4a48b9a"),
    "blue": ("Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb",
             "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2"),
}


