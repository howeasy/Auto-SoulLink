"""server/data/items — Per-generation item name tables.

Each generation has its own item table (no fallback chain — item IDs are
gen-specific). Adapters import directly from server.data.items.gen{N},
mirroring the pattern in server.data.moves.

Generations:
  gen1.py          — RBY (item IDs 1-83-ish)
  gen3_vanilla.py  — FRLG/Emerald (RR uses rr_items.json loaded by the adapter)
  gen4.py          — HGSS/Platinum
  gen5.py          — BW/B2W2 (1-638)

Gen 2 loads from data/games/gen2_crystal/item_names.json at adapter init.
"""
