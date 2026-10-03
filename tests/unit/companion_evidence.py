"""Hello fields that show the SLink companion patch, for tests that connect a cartridge to the server.

Patch-first (owner 2026-10-02): the server refuses a hello for a title that requires the companion unless
it carries the evidence its adapter asks for (`GameRulesAdapter.companion_refusal`). A test that is about
something else (links, trades, the board) connects a PATCHED cartridge, so it merges `companion(rom_type)`
into its hello; the refusal itself is tested in test_companion_required.py. Exempt titles (Yellow, AP,
Gen 4/5) need nothing and get `{}`.
"""
from __future__ import annotations

_RBY = {"red", "blue"}
_PURE = {"purered", "pureblue", "puregreen"}
_GEN3 = {"firered", "leafgreen", "emerald", "firered_rr"}


def companion(rom_type: str) -> dict:
    name = str(rom_type).lower()
    if name in _RBY:
        return {"artifact_kind": "named", "panel": True}
    if name in _PURE:
        return {"artifact_kind": "overlay"}
    if name in _GEN3:
        # the pack-pinned mailbox ABI the cartridge's own mailbox reports (Radical Red ABI1, the rest ABI2)
        return {"artifact_kind": "companion", "companion_abi": 1 if name == "firered_rr" else 2}
    return {}


def patched(hello: dict) -> dict:
    """`hello` with the companion evidence for its rom_type merged under any field it already sets.

    The caller's artifact_kind always wins: a "clean" Gen 1/Gen 3 half keeps committing "clean" (its evidence is
    the panel / `companion_abi` field), and a "clean" pureRGB hello stays clean and is REFUSED (its evidence
    IS the kind). A pureRGB caller that means a patched cartridge says "overlay" itself.
    """
    return {**companion(hello.get("rom_type", "")), **hello}
