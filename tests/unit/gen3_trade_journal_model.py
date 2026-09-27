"""Explicit durable-storage seam for client protocol MODEL tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class JournalModel:
    def __init__(self, *, player="a", rom="ab" * 20, run="model-run", ot="0000ABCD", data=None):
        self.player, self.rom, self.run, self.ot = player, rom, run, ot
        self.data, self.fail, self.calls = data, False, 0

    def __call__(self, lua):
        self.lua = lua
        self.module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
        codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
        if self.data is None:
            self.data = self.module.initial(codec)  # explicit fresh MODEL store, never production recovery

        def update(transform):
            if self.fail:
                raise OSError("MODEL durable journal write failure")
            self.data, answer = transform(self.data)
            self.calls += 1
            return answer

        self.journal = self.module.new(lua.table(json=codec, store=lua.table(read=lambda: self.data, update=update),
                                                 rom_sha1=self.rom, player=self.player))
        if self.run is not None:
            self.journal.bind(self.journal, self.run, self.ot)
        return self.journal
