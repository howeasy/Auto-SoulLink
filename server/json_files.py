"""Atomic JSON publication to a caller-supplied path."""

import json
import os
import tempfile
import time
from pathlib import Path


def atomic_write_json(path: str | os.PathLike, value) -> None:
    """Replace a JSON file only after its complete replacement has been flushed.

    The temporary file lives beside the destination so replacement stays on the
    same filesystem. No application data directory is selected by this helper.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False,
            dir=destination.parent, prefix=f".{destination.name}-", suffix=".tmp",
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary, destination)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
