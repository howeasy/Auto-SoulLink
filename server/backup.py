"""Rolling backup of links.json and events.json.

Copies the live state files to a sibling `backups/` directory on a
configurable interval, retaining up to ``max_slots`` rotations
(``links.backup.1.json`` newest, ``links.backup.N.json`` oldest).
Only runs while both players are connected, to avoid backing up
unchanging single-player state.

Extracted from server/server.py per the master codebase audit. Each
function takes explicit arguments rather than reading from `self`, so
the module has no SLinkServer dependency and is unit-testable.
"""

import asyncio
import logging
import os
import shutil
from typing import Callable

log = logging.getLogger(__name__)


def do_backup(links_path: str, events_path: str, max_slots: int) -> None:
    """Copy links.json (and events.json) into the next rolling backup slot.

    Rotates the existing slots up by one and writes the current file as
    slot 1 (newest). Silently returns if links.json doesn't exist.
    """
    if not os.path.exists(links_path):
        return
    backup_dir = os.path.join(os.path.dirname(links_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    # Rotate: shift numbered slots up (oldest first, so we don't overwrite).
    for i in range(max_slots, 1, -1):
        for stem in ("links", "events"):
            src = os.path.join(backup_dir, f"{stem}.backup.{i - 1}.json")
            dst = os.path.join(backup_dir, f"{stem}.backup.{i}.json")
            if os.path.exists(src):
                os.replace(src, dst)
    # Write current as slot 1 (newest).
    shutil.copy2(links_path, os.path.join(backup_dir, "links.backup.1.json"))
    if os.path.exists(events_path):
        shutil.copy2(events_path, os.path.join(backup_dir, "events.backup.1.json"))
    log.info("Rolling backup saved (%s)", backup_dir)


async def backup_loop(
    links_path: str,
    events_path: str,
    max_slots: int,
    interval_s: int,
    is_active: Callable[[], bool],
) -> None:
    """Background task: snapshot every ``interval_s`` seconds while ``is_active()``.

    Catches and logs per-cycle exceptions so a single bad write doesn't
    kill the loop. Stops cleanly on asyncio.CancelledError.
    """
    try:
        while True:
            await asyncio.sleep(interval_s)
            if is_active():
                try:
                    do_backup(links_path, events_path, max_slots)
                except Exception as e:
                    log.warning("Backup failed: %s", e)
    except asyncio.CancelledError:
        pass
