# Shared GB panel

`lua/gb_panel.lua` (P4.1d) holds the GB in-game panel's platform mechanics: the
`SLNK` beacon + capability handshake, the AWAIT -> STAGED paint handshake with its
observed-transition deadline, the 20x18 tile renderer (rows -> sanitized, paged,
pre-rendered tiles) and the SFX request byte with its drop-oldest queue. Gen 1 and
Gen 2 bind it. Gen 3 does not: it speaks EWRAM opcodes through `lua/mailbox.lua`.

## Interface

`GB.new(spec, io, writes, sanitize)` returns the panel object
(`present`, `sfx_present`, `abi`, `caps_has`, `sfx_code_for`, `request_sfx`,
`hold`, `stage`, `service`, `clear`, `clear_sfx`, `awaiting`, `allow`, `mailbox`).

Every `spec` field is required; a missing one asserts:

- `mailbox`: base address of the mailbox. Offsets, caps bits, panel states and
  SFX codes are `patch/gb/slink_abi.inc`'s; `tests/unit/test_gb_panel.py`
  fails when the Lua constants and the include disagree.
- `tilemap`: the title's tile map (`wTileMap` / `wTilemap`).
- `attrmap`: `{base, fill}` for a CGB title (every page also paints 360 `fill`
  bytes at `base`, after the tiles and before PAGES/STATE), or `false` for DMG.
- `charmap`: callable `ch -> tile id` for one ASCII character.
- `se_map`: server `play_sound` id -> SFX code.
- `deadline`: frames after an observed AWAIT transition within which a page
  may be painted.

`io` needs `read_u8`/`framecount`; `writes` is a `writes.lua` instance (every
write happens inside its `"panel"` window, guarded by `allow`); `sanitize` is
`hud.lua`'s.

## Gen 1 rebind

`lua/gen1/panel.lua` is a binder: the vanilla mailbox `$DEE2` (or
`profile.trade.mailbox` for an overlay), `wTileMap`, `attrmap = false`, the
Gen 1 charmap (`tile_for_charmap`), the Gen 3 SE -> Gen 1 code map, and
`DEADLINE = 60`. It adds one Gen 1 policy on top: server id 25 upgrades to
`SFX_NOTIFY` on a cartridge advertising `CAP_SFX_NOTIFY`. Its behaviour is
unchanged; the Gen 1 panel/tile/writes unit tests and the live patch + SFX gates
pin that.

Text -> sanitized rows stays in this module until a Gen 3 card needs it.
