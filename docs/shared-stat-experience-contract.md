# Shared stat-experience arithmetic

server/stat_experience.py is unchanged from the Gen1 native trade result policy.
It has no file, memory, admission or transaction behavior.

calculate_stat(base, dv, level, experience, hp=False) accepts integer base1..255,
DV0..15, level1..100 and stat experience0..65535. It applies the qualified RBY
integer square-root rounding/cap and HP-versus-other-stat bonus, then caps the
result at999. split_dvs(packed) returns HP, Attack, Defense, Speed, Special DVs
from a16-bit packed value. HP comes from the low bit of each stored DV.

The RBY caller already compares its results with original-engine trade evolution.
The standalone16-case tests cover rounding boundaries, the experience cap, HP
bonus, packed DV extraction and invalid inputs. These pure arithmetic checks
do not qualify another generation's storage layout, withdrawal behavior, mail,
egg state, growth/PP policy or use of the formulas. Gen2 must compare against
its original CalcMonStats before binding this helper.
