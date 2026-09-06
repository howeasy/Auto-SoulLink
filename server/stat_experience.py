"""Pure stat-experience arithmetic, separate from memory layout and admission.

The RBY caller qualifies these mechanics against canonical CalcStat. Other
generation adapters must validate their own layouts, inputs and formula use.
"""
from math import isqrt


def calculate_stat(base: int, dv: int, level: int, experience: int, *, hp: bool = False) -> int:
    for value, low, high, name in ((base, 1, 255, "base stat"), (dv, 0, 15, "DV"),
                                  (level, 1, 100, "level"), (experience, 0, 65535, "stat experience")):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("invalid " + name)
    if type(hp) is not bool:
        raise ValueError("invalid HP selector")
    root = isqrt(experience)
    root = min(255, max(1, root + (root * root < experience)))
    value = ((base + dv) * 2 + root // 4) * level // 100
    return min(999, value + (level + 10 if hp else 5))


def split_dvs(value: int) -> tuple[int, int, int, int, int]:
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError("invalid packed DVs")
    attack, defense, speed, special = ((value >> shift) & 15 for shift in (12, 8, 4, 0))
    hp = (attack & 1) * 8 + (defense & 1) * 4 + (speed & 1) * 2 + (special & 1)
    return hp, attack, defense, speed, special
