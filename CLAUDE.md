# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SLink is a Pokémon Soul Link Nuzlocke automation system. Two BizHawk emulator instances run Lua clients that send JSON events over TCP to a Python/aiohttp server. The server enforces Soul Link rules (linked encounters, faint propagation, party/box sync, clause enforcement) and serves HTTP status pages and OBS stream overlays.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (TCP :54321, HTTP :8080)
python -m server.server
python -m server.server --host 127.0.0.1 --port 54321 --http-port 8080 --reset

# Run all unit tests
pytest tests/unit/ -v

# Run a single test file
pytest tests/unit/test_state.py -v

# Regenerate Lua area maps from JSON data
python tools/gen_area_map.py          # Gen 3 FRLGE
python tools/gen_gen1_area_map.py     # Gen 1 RBY
python tools/gen_gen2_area_map.py     # Gen 2 Crystal
python tools/gen_gen4_area_map.py     # Gen 4 HGSSPT

# Damage calculator (TypeScript)
cd calc && npm run build              # Full compile + HTML hash
cd calc && node build view            # HTML-only rebuild
```

## Architecture

```
[BizHawk instances]
  └─ Lua clients (lua/clients/gen*_client.lua)
       ↓ TCP JSON events (area_enter, capture, faint, party_diff, …)

[server/server.py]  — aiohttp, TCP :54321, HTTP :8080
  ├─ server/state.py        — SoulLinkState FSM (all rule enforcement)
  ├─ server/adapters/       — game-specific logic (Adapter pattern)
  │    ├─ base.py           — GameAdapter ABC
  │    ├─ gen1_rby.py
  │    ├─ gen2_crystal.py
  │    ├─ gen3_frlge.py     — supports vanilla / Archipelago / Radical Red
  │    └─ gen4_hgsspt.py
  ├─ server/manager.py      — multi-run orchestration (:8090)
  ├─ server/pokemon_data.py — species, abilities, types, sprites
  └─ server/move_data.py    — move names and properties

[data/]  — persisted state (written after every state change)
  ├─ links.json
  ├─ memorial.json
  ├─ events.json
  └─ games/<gen>_<game>/    — area maps, RR data

[HTTP routes]
  /               — main status page (parties, links, encounters, battle display)
  /memorial       — tombstone cards for dead pairs
  /debug          — console: link/unlink, mon/area autofill, backup rollback
  /stream/*       — OBS overlays (party-a, party-b, links, deaths, areas, events)
  /calc/          — Radical Red damage calculator with live party bridge
  /api/*          — REST + SSE endpoints
```

## Key Design Patterns

**Adapter isolation** — All game-specific logic lives in `server/adapters/`. Never add `if is_rr` checks or game-specific imports to `server.py`. New game support = new adapter subclass.

**TCP protocol** — Lua clients send newline-delimited JSON; server replies `{"commands": [...]}` on the same connection. Lua connector is fully non-blocking (`settimeout(0)`) with exponential backoff (2 s → 30 s) to avoid emulator stutter when the server is down.

**State machine** — `server/state.py` (`SoulLinkState`) owns all Soul Link rule logic: linking, faint propagation, party sync, clause enforcement, shiny bonus pairs. Tests in `tests/unit/test_state.py` (204 tests) cover the FSM exhaustively.

**Party sync safety** — Box/party move commands are deferred until a safe overworld frame (no battle, menu, or animation). Only one command executes per frame.

**SSE streaming** — The main status page and OBS overlays use Server-Sent Events for near-real-time, flicker-free DOM morphing.

**Memory profiles** — `lua/memory_gba.lua` auto-detects ROM profiles (vanilla, Archipelago, Radical Red/CFRU) and switches address tables accordingly. Gen 4 similarly detects HGSS vs Platinum.

## Test Layout

- `tests/unit/test_state.py` — FSM rules (204 tests)
- `tests/unit/test_gen{1,2,3,4}_adapter.py` — per-game adapter tests
- `tests/unit/test_phase1_comms.py` — TCP integration tests
- `tests/lua/` — BizHawk Lua test scripts
- `tests/TESTING.md` — live 9-step BizHawk test guide

## Supported Games

**Only Gen 3 has been battle-tested in live gameplay.** Gen 1, 2, and 4 have unit tests and Lua clients but have not had significant real-world testing — treat them as alpha quality. When making changes to shared code (server.py, state.py, adapters/base.py), always verify Gen 3 isn't broken first, then run the other gen tests as a secondary check.

| Gen | Games | Status |
|-----|-------|--------|
| 3   | FireRed, LeafGreen, Emerald (vanilla / Archipelago / Radical Red 4.1) | **Battle-tested** |
| 1   | Red, Blue, Yellow (US) | Alpha — unit tests only |
| 2   | Crystal (GBC) | Alpha — unit tests only |
| 4   | HeartGold, SoulSilver, Platinum | Alpha — unit tests only |
| 5   | Black, White, B2W2 | Planned (stubs only) |
