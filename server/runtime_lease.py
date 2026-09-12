"""One cooperating server process per runtime; readers remain independent."""
from __future__ import annotations

import os
from pathlib import Path


class RuntimeLease:
    def __init__(self, path):
        self.path = Path(path)
        self._file = None

    def __enter__(self):
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if stream.seek(0, 2) == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise RuntimeError("another server owns this runtime, or its lease is unavailable") from error
        self._file = stream
        return self

    def __exit__(self, *_):
        # Closing this exact owned handle releases the OS lease even after an
        # exception. The lock file remains; stale PID files are not ownership.
        if self._file is not None:
            self._file.close()
            self._file = None
