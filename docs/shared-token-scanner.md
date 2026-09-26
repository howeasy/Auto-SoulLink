# Bounded byte-token scanner

`lua/token_scanner.lua` shares only byte validation, bounded iteration, termination,
and concatenation. It owns no glyph map, name size, unknown-byte spelling, game
profile, memory reader, field layout, encoding, or Python oracle.

## Interface

```lua
local decode = Scanner.new({
    glyphs = glyphs,          -- plain table: integer byte keys -> token strings
    terminator = terminator, -- integer 0..255; never rendered
    max_length = maximum,    -- finite nonnegative integer, measured in bytes
    unknown = unknown,       -- required function(byte, one_based_index)
})
local text, why = decode(bytes)
```

Missing or malformed policy is a constructor error. The constructor snapshots the
glyph map, bound, terminator and callback. Duplicate glyph strings at distinct
byte values are permitted; the scanner performs no reverse lookup, normalization,
alias selection, or Unicode splitting. An empty or partial glyph table is valid
only with the explicitly supplied unknown-token callback.

`bytes` must be a plain, dense, one-based Lua array of integers 0..255, with no
extra keys or metatable. The scanner validates and snapshots the entire supplied
field before invoking the callback. Sparse arrays, non-byte values and overlength
fields return `nil, reason`, including malformed content after a terminator.
There is no partial-success string. Valid bytes after the terminator are ignored
for display, and do not invoke unknown-token handling. Empty input returns `""`;
a bounded valid field without a terminator decodes in full, preserving Gen 1's
existing name contract.

For an unmapped byte, `unknown(byte, index)` must return a string (including an
explicit empty replacement), or `nil, reason` to refuse. Callback errors and
non-string results also refuse. Input and configuration tables are never modified.
Changing a caller's glyph table requires constructing another decoder.

## Game bindings and ownership

Gen 1 requires `Reads.new(profile, io, Scanner)`. It retains `R.charmap`, the
vanilla glyph runs/EXTRA table, generated pureRGB maps, and first-byte alias codes.
Its policy uses the selected charmap terminator, `profile.derived.name_length`,
and the existing `<$XX>` unknown-byte spelling. Collection reads propagate a
name refusal. Gen 1 Entry must explicitly load `lua/token_scanner.lua` and pass
the module; the release bundle must include that exact shared file. Those
composition files belong to the checkpoint/Entry owner in the current grant.

A Gen 2 binder uses its own generated `charmap.lua` and selected title profile:

```lua
local decode = Scanner.new({glyphs = charmap.glyphs,
    terminator = charmap.terminator, max_length = profile.derived.name_length,
    unknown = function(byte) return string.format("<$%02X>", byte) end})
-- Pass decode as the existing third argument to Reads.new(profile, io, decode).
```

(`lua/gen2/entry.lua:292-296` is the actual call site: `max_length` reads
`profile.derived.name_length`, not `profile.constants.NAME_LENGTH`, and the
Gen 2 reads module is named `Reads`, not `Gen2Reads`.)

That binder contract is exercised with all three generated Gen 2 charmaps; the
Gen 2 decoder is not edited by this extraction. Font/language alias interpretation
remains in each game's generated glyph map. Both Python codecs stay independent
and unchanged. MODEL controls cover malformed fields, terminator boundaries,
aliases, unknowns, Gen 1 differential decoding and the second binder. They do not
qualify emulator behavior or reopen/satisfy physical lanes automatically.
