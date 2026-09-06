# Extended-ROM word inside compressed audio

The numeric word at `0x09EC112C` is `0x0201BDE0`, inside the proposed heap-tail
reservation range. It is located inside a strongly corroborated compressed DPCM
record, rather than a demonstrated RAM-pointer literal pool. **No natural game
consumer/channel for this particular sample has yet been identified.** This
classification does not establish exclusive arena ownership.

Against the exact RR base SHA256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`:

| Wave header | Type/status | Frequency field | Decoded samples | Next aligned header |
|---|---|---|---|---|
| `0x09EBCBD4` | 1/0 | 32768000 | 23260 | `0x09EBFAD0` |
| `0x09EBFAD0` | 1/0 | 45158400 | 98676 | `0x09ECC1A8` |
| `0x09ECC1A8` | 1/0 | 45158400 | 59922 | Not used in this check |

Each of the first two records ends at
`align4(header + 16 + ceil(samples / 64) * 33)`. Both boundaries land exactly on
the next complete header. The disputed word lies in the second record's payload.
An all-offset search found no absolute references to the first two headers;
therefore this review does not claim natural playback, runtime reachability, or
that all possible references have been resolved.

The actual RR ARM decoder at `0x081DC71C` computes
`wave + 16 + floor(sample_index / 64) * 33`, reads33 successive bytes, decodes64
samples through the delta table at `0x084899F8`, and writes the buffer at
`0x03002088`. Its channel wave/cache fields are `+0x24/+0x3C`. A source naming aid
is pret's `SoundMainRAM_Unk2` in local `src/m4a_1.s` (source SHA256
`348ed832bb30b24fa3ad9cf90242cc708ad972c19dff43b4dd550de4e5716dbf`).
The source's embedded address labels do not match RR; the actual RR entry was
located and disassembled independently.

`tests/rr/native/test_pcm_literal_cpu.py` executes that unstubbed RR decoder with
a synthetic channel pointing at this wave. Every byte of the disputed word is
read as compressed sample data and agrees with an independent delta decoder.
Writes are confined to the decoding buffer, channel cache and stack; the word is
not dereferenced as an EWRAM address by this execution. This is a bounded CPU
interpretation test, not proof that gameplay selects this sample or that no other
code path can access the proposed arena. The full raw-access and capacity gates
in `GAME_HEAP_RESERVATION.md` remain required.
