"""Trusted, cartridge-validated identity supplied by an admitted coordinator.

This value is not decoded from a JSON keyword by the rule engine. A binding must
validate the loaded save and normalize its cartridge-specific trainer identifier
before constructing it. The persisted identity document keeps its legacy shape.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SaveIdentity:
    ot_id: str
    trainer_name: str = ""

    def __post_init__(self):
        if (not isinstance(self.ot_id, str) or not 1 <= len(self.ot_id) <= 128
                or self.ot_id != self.ot_id.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in self.ot_id)):
            raise ValueError("validated, normalized save trainer identity required")
        if (not isinstance(self.trainer_name, str) or len(self.trainer_name) > 64
                or any(ord(char) < 32 or ord(char) == 127 for char in self.trainer_name)):
            raise ValueError("validated save trainer name required")
