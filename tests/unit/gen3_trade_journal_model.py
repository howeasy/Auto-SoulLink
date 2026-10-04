"""Explicit durable-storage seam for client protocol MODEL tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class JournalModel:
    def __init__(self, *, player="a", rom="ab" * 20, run="model-run", ot="0000ABCD", data=None, files=None):
        self.player, self.rom, self.run, self.ot = player, rom, run, ot
        self.data, self.fail, self.calls = data, False, 0
        # `files` (a tests.unit.test_gen3_trade_journal.Files) swaps the in-memory store for the REAL guarded file_store over that OS
        # seam, with `frame=` wired like production: setting files.held = True is then another process holding the guard, and the
        # journal's own read() raises LOCK_BUSY and sets journal.busy (nothing is faked by hand). Set frame_source after the World exists.
        self.files, self.frame_source = files, None

    def __call__(self, lua):
        self.lua = lua
        self.module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
        codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
        if self.data is None and self.files is None:
            self.data = self.module.initial(codec)  # explicit fresh MODEL store, never production recovery

        def update(transform):
            if self.fail:
                raise OSError("MODEL durable journal write failure")
            self.data, answer = transform(self.data)
            self.calls += 1
            return answer

        if self.files is not None:
            store = self.module.file_store(lua.table(json=codec, fs=self.files.table(lua), path="model/slink_gen3_trade"))
            frame = lambda: self.frame_source() if self.frame_source else 0  # noqa: E731
            self.journal = self.module.new(lua.table(json=codec, store=store, rom_sha1=self.rom, player=self.player, frame=frame))
        else:
            self.journal = self.module.new(lua.table(json=codec, store=lua.table(read=lambda: self.data, update=update),
                                                     rom_sha1=self.rom, player=self.player))
        if self.run is not None:
            self.journal.bind(self.journal, self.run, self.ot)
        return self.journal
